"""
dev/fp_wdist_search.py

Search for the best mn6 fingerprint function fp(c1,c2) = (c1*A + c2*B) & 0xFF
in terms of minimising close false positives, measured by weighted Hamming
distance on QWERTY keyboard layout.

Hash: h6 = (c1*9 + c3*5 + T[c2]) & 0x3F  (64 slots, 56 legal NMOS mnemonics)
VICII screencodes: A=1, B=2, ... Z=26

Usage:
    python fp_wdist_search.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from instruction_set import sc, MNEMONICS
from hashes import mn6

# ============================================================
# QWERTY adjacency
# ============================================================

QWERTY_ROWS = [
    "QWERTYUIOP",
    "ASDFGHJKL",
    "ZXCVBNM",
]

def _build_adjacency():
    """Build set of adjacent character pairs on QWERTY keyboard."""
    adj = set()
    for row in QWERTY_ROWS:
        for i in range(len(row) - 1):
            a, b = row[i], row[i + 1]
            adj.add((a, b))
            adj.add((b, a))
    return adj

ADJACENT = _build_adjacency()


def wdist_char(a, b):
    """Weighted distance between two characters at one position."""
    if a == b:
        return 0.0
    if (a, b) in ADJACENT:
        return 0.5
    return 1.0


def wdist(s1, s2):
    """Total weighted Hamming distance between two 3-char strings."""
    return wdist_char(s1[0], s2[0]) + wdist_char(s1[1], s2[1]) + wdist_char(s1[2], s2[2])


# ============================================================
# Precompute universe of all AAA..ZZZ strings
# ============================================================

LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def build_universe(slot_map):
    """Build list of (string, c1, c2, c3, slot, slot_wdist) for all 17576 strings.

    slot_wdist is the wdist to the legal mnemonic in the slot (None if slot empty).
    """
    universe = []
    legal_set = frozenset(slot_map.values())

    for a in LETTERS:
        for b in LETTERS:
            for c in LETTERS:
                s = a + b + c
                c1v = sc(a)
                c2v = sc(b)
                c3v = sc(c)
                h = (c1v * mn6.C1 + c3v * mn6.C3 + mn6.T[c2v]) & 0x3F
                slot = h

                if slot in slot_map:
                    legal_mne = slot_map[slot]
                    sw = wdist(s, legal_mne) if s not in legal_set else None
                else:
                    sw = None  # empty slot — cannot be FP

                universe.append((s, c1v, c2v, c3v, slot, sw))

    return universe, legal_set


# ============================================================
# Fast numpy search
# ============================================================

def search_numpy(universe, slot_map, legal_set):
    """Search all 256x256 (A,B) pairs using numpy vectorisation."""
    import numpy as np

    print("Using numpy for vectorised search.")

    # Separate legal and non-legal strings with occupied slots (potential FPs)
    fp_candidates = []   # (string, c1, c2, c3, slot_wdist)
    legal_fp_vals = {}   # slot -> (c1, c2) for legal mnemonic

    for s, c1v, c2v, c3v, slot, sw in universe:
        if s in legal_set:
            if slot in slot_map:
                legal_fp_vals[slot] = (c1v, c2v)
        else:
            if slot in slot_map and sw is not None:
                fp_candidates.append((s, c1v, c2v, c3v, slot, sw))

    n_cands = len(fp_candidates)
    print(f"  {n_cands} non-legal strings with occupied slots (potential FPs)")

    if not fp_candidates:
        print("No potential false positives found.")
        return []

    # Arrays for candidates
    cand_c1   = np.array([x[1] for x in fp_candidates], dtype=np.uint16)
    cand_c2   = np.array([x[2] for x in fp_candidates], dtype=np.uint16)
    cand_slot = np.array([x[4] for x in fp_candidates], dtype=np.int32)
    cand_wd   = np.array([x[5] for x in fp_candidates], dtype=np.float32)
    cand_str  = [x[0] for x in fp_candidates]

    # For each slot, build the legal (c1, c2)
    slots_arr = np.array(sorted(slot_map.keys()), dtype=np.int32)
    legal_c1_by_slot = np.zeros(64, dtype=np.uint16)
    legal_c2_by_slot = np.zeros(64, dtype=np.uint16)
    for slot, (lc1, lc2) in legal_fp_vals.items():
        legal_c1_by_slot[slot] = lc1
        legal_c2_by_slot[slot] = lc2

    # The legal fp for a candidate's slot: (legal_c1*A + legal_c2*B) & 0xFF
    # The candidate fp:                    (cand_c1*A  + cand_c2*B)  & 0xFF
    # It's a FP when candidate_fp == legal_fp (mod 256)
    # i.e. ((cand_c1 - legal_c1)*A + (cand_c2 - legal_c2)*B) & 0xFF == 0

    # Precompute delta arrays (mod 256, signed difference)
    legal_c1_for_cand = legal_c1_by_slot[cand_slot]
    legal_c2_for_cand = legal_c2_by_slot[cand_slot]

    delta1 = ((cand_c1 - legal_c1_for_cand) % 256).astype(np.uint8)
    delta2 = ((cand_c2 - legal_c2_for_cand) % 256).astype(np.uint8)

    # For each (A, B), FP iff (delta1*A + delta2*B) & 0xFF == 0
    # Process in chunks of A to keep memory manageable
    CHUNK = 64  # process 64 A values at a time

    results = []  # list of (min_wd, fp_count, A, B)

    A_vals = np.arange(256, dtype=np.uint32)
    B_vals = np.arange(256, dtype=np.uint32)

    # Precompute delta1*A for all A, delta2*B for all B
    # delta1: shape (n_cands,), A_vals: shape (256,)
    # d1A[i, a] = (delta1[i] * A_vals[a]) & 0xFF
    d1 = delta1.astype(np.uint32)  # (n_cands,)
    d2 = delta2.astype(np.uint32)  # (n_cands,)

    # d1A shape: (256, n_cands)
    d1A = ((d1[np.newaxis, :] * A_vals[:, np.newaxis]) & 0xFF).astype(np.uint8)

    # d2B shape: (256, n_cands)
    d2B = ((d2[np.newaxis, :] * B_vals[:, np.newaxis]) & 0xFF).astype(np.uint8)

    best_min_wd = -1.0
    pareto = []  # (min_wd, fp_count, A, B)

    total_pairs = 256 * 256
    processed = 0

    for A in range(256):
        d1A_row = d1A[A].astype(np.uint16)  # shape (n_cands,)

        for B in range(256):
            # FP mask: (d1A[A] + d2B[B]) & 0xFF == 0
            fp_mask = ((d1A_row + d2B[B].astype(np.uint16)) & 0xFF) == 0

            fp_count = int(fp_mask.sum())

            if fp_count == 0:
                min_wd = 999.0
            else:
                min_wd = float(cand_wd[fp_mask].min())

            # Pareto: keep if not dominated
            # dominated = exists result with min_wd >= this AND fp_count <= this
            # We track all non-dominated solutions
            results.append((min_wd, fp_count, A, B))

        processed += 256
        if (A + 1) % 32 == 0:
            print(f"  ... {processed}/{total_pairs} pairs processed", flush=True)

    return results, cand_str, cand_wd, fp_mask, d1A, d2B, delta1, delta2


# ============================================================
# Pure Python fallback search
# ============================================================

def search_python(universe, slot_map, legal_set):
    """Search all 256x256 (A,B) pairs in pure Python."""
    print("Using pure Python search (numpy not available).")

    fp_candidates = []
    legal_fp_vals = {}

    for s, c1v, c2v, c3v, slot, sw in universe:
        if s in legal_set:
            if slot in slot_map:
                legal_fp_vals[slot] = (c1v, c2v)
        else:
            if slot in slot_map and sw is not None:
                fp_candidates.append((s, c1v, c2v, c3v, slot, sw))

    n_cands = len(fp_candidates)
    print(f"  {n_cands} non-legal strings with occupied slots (potential FPs)")

    # Precompute delta pairs
    deltas = []
    for s, c1v, c2v, c3v, slot, sw in fp_candidates:
        lc1, lc2 = legal_fp_vals[slot]
        d1 = (c1v - lc1) & 0xFF
        d2 = (c2v - lc2) & 0xFF
        deltas.append((d1, d2, sw, s))

    results = []

    for A in range(256):
        for B in range(256):
            fp_count = 0
            min_wd = 999.0
            for d1, d2, sw, _ in deltas:
                if ((d1 * A + d2 * B) & 0xFF) == 0:
                    fp_count += 1
                    if sw < min_wd:
                        min_wd = sw
            results.append((min_wd, fp_count, A, B))

        if (A + 1) % 16 == 0:
            print(f"  ... {(A+1)*256}/65536 pairs processed", flush=True)

    return results


# ============================================================
# Main
# ============================================================

def main():
    print("=" * 70)
    print("mn6 fingerprint weighted-distance search")
    print("=" * 70)

    # Build slot map and universe
    slot_map = mn6.build_slot_map()
    print(f"Slot map: {len(slot_map)} legal NMOS mnemonics in 64 slots")

    universe, legal_set = build_universe(slot_map)
    print(f"Universe: {len(universe)} strings (AAA..ZZZ)")

    # Try numpy, fall back to pure Python
    try:
        import numpy as np
        numpy_available = True
    except ImportError:
        numpy_available = False

    print()

    if numpy_available:
        # Run numpy search and collect results
        fp_candidates = []
        legal_fp_vals = {}

        for s, c1v, c2v, c3v, slot, sw in universe:
            if s in legal_set:
                if slot in slot_map:
                    legal_fp_vals[slot] = (c1v, c2v)
            else:
                if slot in slot_map and sw is not None:
                    fp_candidates.append((s, c1v, c2v, c3v, slot, sw))

        import numpy as np

        print("Using numpy for vectorised search.")
        n_cands = len(fp_candidates)
        print(f"  {n_cands} non-legal strings with occupied slots (potential FPs)")

        cand_c1   = np.array([x[1] for x in fp_candidates], dtype=np.uint32)
        cand_c2   = np.array([x[2] for x in fp_candidates], dtype=np.uint32)
        cand_slot = np.array([x[4] for x in fp_candidates], dtype=np.int32)
        cand_wd   = np.array([x[5] for x in fp_candidates], dtype=np.float32)
        cand_str  = [x[0] for x in fp_candidates]

        legal_c1_by_slot = np.zeros(64, dtype=np.uint32)
        legal_c2_by_slot = np.zeros(64, dtype=np.uint32)
        for slot, (lc1, lc2) in legal_fp_vals.items():
            legal_c1_by_slot[slot] = lc1
            legal_c2_by_slot[slot] = lc2

        legal_c1_for_cand = legal_c1_by_slot[cand_slot]
        legal_c2_for_cand = legal_c2_by_slot[cand_slot]

        delta1 = ((cand_c1.astype(np.int32) - legal_c1_for_cand.astype(np.int32)) % 256).astype(np.uint32)
        delta2 = ((cand_c2.astype(np.int32) - legal_c2_for_cand.astype(np.int32)) % 256).astype(np.uint32)

        A_vals = np.arange(256, dtype=np.uint32)
        B_vals = np.arange(256, dtype=np.uint32)

        # d1A[a, i] = (delta1[i] * a) & 0xFF  — shape (256, n_cands)
        d1A = ((delta1[np.newaxis, :] * A_vals[:, np.newaxis]) & 0xFF).astype(np.uint8)
        # d2B[b, i] = (delta2[i] * b) & 0xFF  — shape (256, n_cands)
        d2B = ((delta2[np.newaxis, :] * B_vals[:, np.newaxis]) & 0xFF).astype(np.uint8)

        results = []

        total_pairs = 256 * 256
        print(f"  Scanning {total_pairs} (A,B) pairs...")

        for A in range(256):
            d1A_row = d1A[A].astype(np.uint16)  # (n_cands,)

            for B in range(256):
                fp_mask = ((d1A_row + d2B[B].astype(np.uint16)) & 0xFF) == 0
                fp_count = int(fp_mask.sum())

                if fp_count == 0:
                    min_wd = 999.0
                else:
                    min_wd = float(cand_wd[fp_mask].min())

                results.append((min_wd, fp_count, A, B))

            if (A + 1) % 32 == 0:
                print(f"  ... {(A+1)*256}/{total_pairs} pairs processed", flush=True)

    else:
        # Pure Python
        fp_candidates = []
        legal_fp_vals = {}

        for s, c1v, c2v, c3v, slot, sw in universe:
            if s in legal_set:
                if slot in slot_map:
                    legal_fp_vals[slot] = (c1v, c2v)
            else:
                if slot in slot_map and sw is not None:
                    fp_candidates.append((s, c1v, c2v, c3v, slot, sw))

        print("Using pure Python search (numpy not available).")
        n_cands = len(fp_candidates)
        print(f"  {n_cands} non-legal strings with occupied slots (potential FPs)")

        deltas = []
        for s, c1v, c2v, c3v, slot, sw in fp_candidates:
            lc1, lc2 = legal_fp_vals[slot]
            d1 = (c1v - lc1) & 0xFF
            d2 = (c2v - lc2) & 0xFF
            deltas.append((d1, d2, sw, s))

        results = []
        print(f"  Scanning 65536 (A,B) pairs...")
        for A in range(256):
            for B in range(256):
                fp_count = 0
                min_wd = 999.0
                for d1, d2, sw, _ in deltas:
                    if ((d1 * A + d2 * B) & 0xFF) == 0:
                        fp_count += 1
                        if sw < min_wd:
                            min_wd = sw
                results.append((min_wd, fp_count, A, B))
            if (A + 1) % 16 == 0:
                print(f"  ... {(A+1)*256}/65536 pairs processed", flush=True)

    print()

    # --------------------------------------------------------
    # Sort and filter: top-20 by (min_wdist DESC, fp_count ASC)
    # Exclude A=0,B=0 (trivial all-same fingerprint)
    # --------------------------------------------------------

    # Filter out (0,0) as degenerate
    results_filtered = [(wd, cnt, A, B) for wd, cnt, A, B in results if not (A == 0 and B == 0)]

    # Sort: primary = min_wd DESC, secondary = fp_count ASC
    results_sorted = sorted(results_filtered, key=lambda x: (-x[0], x[1]))

    top20 = results_sorted[:20]

    # --------------------------------------------------------
    # For top results, find the FP strings at the worst wdist
    # We need to reconstruct which strings are FPs and at min_wd
    # --------------------------------------------------------

    def get_fp_strings_at_min_wd(A, B, min_wd_target):
        """Return FP strings that achieve the minimum wdist for (A,B)."""
        found = []
        for s, c1v, c2v, c3v, slot, sw in universe:
            if s in legal_set:
                continue
            if slot not in slot_map:
                continue
            if sw is None:
                continue
            lc1, lc2 = legal_fp_vals[slot]
            cand_fp  = (c1v * A + c2v * B) & 0xFF
            legal_fp = (lc1 * A + lc2 * B) & 0xFF
            if cand_fp == legal_fp:
                if abs(sw - min_wd_target) < 1e-6:
                    found.append((s, slot_map[slot], sw))
        return found

    # Build legal_fp_vals for use in get_fp_strings_at_min_wd
    legal_fp_vals = {}
    for s, c1v, c2v, c3v, slot, sw in universe:
        if s in legal_set and slot in slot_map:
            legal_fp_vals[slot] = (c1v, c2v)

    print("=" * 70)
    print("Top-20 fingerprint functions (A,B) by min_wdist DESC, fp_count ASC")
    print("=" * 70)
    print(f"{'A':>4} {'B':>4}  {'fp_count':>8}  {'min_wdist':>9}  worst-FP strings")
    print("-" * 70)

    for min_wd, fp_count, A, B in top20:
        if min_wd >= 999.0:
            wd_str = "  inf"
            worst = []
        else:
            wd_str = f"{min_wd:5.1f}"
            worst = get_fp_strings_at_min_wd(A, B, min_wd)

        worst_str = "  ".join(
            f"{s}~{legal}({wd:.1f})" for s, legal, wd in worst[:5]
        )
        print(f"{A:>4} {B:>4}  {fp_count:>8}  {wd_str}       {worst_str}")

    print()

    # --------------------------------------------------------
    # Summary table of min_wdist thresholds
    # --------------------------------------------------------

    print("=" * 70)
    print("Summary: achievable min_wdist thresholds")
    print("=" * 70)

    for threshold in [0.5, 1.0, 1.5, 2.0]:
        count = sum(1 for wd, cnt, A, B in results_filtered if wd >= threshold)
        print(f"  min_wdist >= {threshold:.1f}: {count:5d} candidates")

    print()

    # --------------------------------------------------------
    # Current mn6 fingerprint (A=9, B=1) for reference
    # --------------------------------------------------------
    current_A, current_B = 9, 1
    current_results = [(wd, cnt, A, B) for wd, cnt, A, B in results
                       if A == current_A and B == current_B]
    if current_results:
        wd, cnt, A, B = current_results[0]
        worst_cur = get_fp_strings_at_min_wd(A, B, wd) if wd < 999.0 else []
        worst_str = "  ".join(f"{s}~{legal}({w:.1f})" for s, legal, w in worst_cur[:5])
        print("=" * 70)
        print(f"Current mn6 fingerprint A={current_A}, B={current_B}:")
        print(f"  fp_count={cnt}  min_wdist={wd:.1f}  worst FPs: {worst_str}")
        print("=" * 70)


if __name__ == '__main__':
    main()
