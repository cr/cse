"""
dev/fp_candidate_analysis.py

Detailed false-positive cross-analysis for the top-3 best (A,B) fingerprint
candidates identified by fp_wdist_search.py.

Hash: h6 = (c1*9 + c3*5 + T[c2]) & 0x3F  (64 slots, 56 legal NMOS mnemonics)
Fingerprint candidate: fp = (c1*A + c2*B) & 0xFF
VICII screencodes: A=1, B=2, ... Z=26

Usage:
    python fp_candidate_analysis.py
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
    adj = set()
    for row in QWERTY_ROWS:
        for i in range(len(row) - 1):
            a, b = row[i], row[i + 1]
            adj.add((a, b))
            adj.add((b, a))
    return adj

ADJACENT = _build_adjacency()


def wdist_char(a, b):
    if a == b:
        return 0.0
    if (a, b) in ADJACENT:
        return 0.5
    return 1.0


def wdist(s1, s2):
    return wdist_char(s1[0], s2[0]) + wdist_char(s1[1], s2[1]) + wdist_char(s1[2], s2[2])


def ham(s1, s2):
    return sum(1 for a, b in zip(s1, s2) if a != b)


# ============================================================
# Build slot map and legal set
# ============================================================

LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'

slot_map = mn6.build_slot_map()
ALL_LEGAL = frozenset(slot_map.values())      # 56 NMOS legal mnemonics
ALL_MNE   = frozenset(MNEMONICS.keys())       # all 114 mnemonics


def fp_byte(c1, c2, A, B):
    return (c1 * A + c2 * B) & 0xFF


def get_fps(A, B):
    """Return list of (fp_str, slot_mne, slot_wdist) for all false positives."""
    # Precompute legal fp values per slot
    legal_fp = {}
    for slot, mne in slot_map.items():
        c1, c2 = sc(mne[0]), sc(mne[1])
        legal_fp[slot] = fp_byte(c1, c2, A, B)

    fps = []
    for a in LETTERS:
        for b in LETTERS:
            for c in LETTERS:
                s = a + b + c
                if s in ALL_LEGAL:
                    continue
                c1v, c2v, c3v = sc(a), sc(b), sc(c)
                h = (c1v * mn6.C1 + c3v * mn6.C3 + mn6.T[c2v]) & 0x3F
                if h not in slot_map:
                    continue
                cand_fp = fp_byte(c1v, c2v, A, B)
                if cand_fp == legal_fp[h]:
                    sw = wdist(s, slot_map[h])
                    fps.append((s, slot_map[h], sw))
    return fps


def nearest_mne(fp_str):
    """Return (nearest_mne, wdist_val) — closest of all 114 mnemonics."""
    best_mne = None
    best_wd  = 999.0
    for mne in ALL_MNE:
        wd = wdist(fp_str, mne)
        if wd < best_wd or (wd == best_wd and mne < best_mne):
            best_wd  = wd
            best_mne = mne
    return best_mne, best_wd


def pos_notes(fp_str, nearest):
    """Build Notes string: which positions differ and whether QWERTY-adjacent."""
    parts = []
    for i, (fc, nc) in enumerate(zip(fp_str, nearest)):
        if fc != nc:
            adj = (fc, nc) in ADJACENT
            label = f"pos{i}: {nc}\u2192{fc}"
            if adj:
                label += " adjacent"
            parts.append(label)
    return ",  ".join(parts) if parts else ""


def analyse_candidate(A, B):
    fps = get_fps(A, B)
    # min_wdist from search: minimum wdist(FP, H-slot) — matches search ranking
    min_hslot_wd = min((sw for _, _, sw in fps), default=999.0)
    fp_count = len(fps)

    # Compute nearest wdist for all FPs to determine worst offender in table
    fp_enriched = []
    for fp_str, h_mne, h_wd in fps:
        near_mne, near_wd = nearest_mne(fp_str)
        fp_enriched.append((fp_str, h_mne, h_wd, near_mne, near_wd))

    min_near_wd = min((x[4] for x in fp_enriched), default=999.0)

    print(f"{'=' * 72}")
    print(f"Candidate  fp = (c1*{A} + c2*{B}) & $FF")
    print(f"{'=' * 72}")
    print(f"Total FP count : {fp_count}")
    print(f"Min wdist      : {min_hslot_wd:.1f}  (worst offender proximity, FP vs H-slot)")
    print()

    # Sort: nearest wdist ASC, then fp_str alphabetically
    fp_enriched_sorted = sorted(fp_enriched, key=lambda x: (x[4], x[0]))

    print(f"  {'FP':<6}  {'H-slot':<7}  {'Nearest':<8}  {'Ham':>3}  {'WDist':>5}  Notes")
    print(f"  {'---':<6}  {'------':<7}  {'-------':<8}  {'---':>3}  {'-----':>5}  -----")

    for fp_str, h_mne, h_wd, near_mne, near_wd in fp_enriched_sorted:
        n_val  = ham(fp_str, near_mne)
        notes  = pos_notes(fp_str, near_mne)
        marker = "  <- worst offender" if abs(near_wd - min_near_wd) < 1e-6 else ""
        print(f"  {fp_str:<6}  {h_mne:<7}  {near_mne:<8}  {n_val:>3}  {near_wd:>5.1f}  {notes}{marker}")

    print()


# ============================================================
# Main
# ============================================================

def main():
    # Top-3 from fp_wdist_search.py — all have min_wdist=2.5, fp_count=22
    # (ranked by min_wdist DESC, fp_count ASC; first three distinct entries)
    top3 = [
        (1,  53),
        (1, 166),
        (3, 159),
    ]

    print("=" * 72)
    print("mn6 fingerprint candidate analysis — top-3 (A,B) by min_wdist")
    print("=" * 72)
    print()
    print("Hash:        h6 = (c1*9 + c3*5 + T[c2]) & 0x3F")
    print("Fingerprint: fp = (c1*A + c2*B) & $FF")
    print()
    print("Top-3 candidates (highest min_wdist=2.5, fewest FPs=22):")
    print("  (A,B) = (1,53), (1,166), (3,159)")
    print()

    for A, B in top3:
        analyse_candidate(A, B)

    # Reference: current mn6 fingerprint
    print("=" * 72)
    print("Reference: current mn6 fingerprint  fp = (c1*9 + c2*1) & $FF")
    print("=" * 72)
    ref_fps = get_fps(9, 1)
    ref_hslot_min_wd = min((sw for _, _, sw in ref_fps), default=999.0)
    print(f"Total FP count : {len(ref_fps)}")
    print(f"Min wdist      : {ref_hslot_min_wd:.1f}  (FP vs H-slot)")
    print()

    ref_enriched = []
    for fp_str, h_mne, h_wd in ref_fps:
        near_mne, near_wd = nearest_mne(fp_str)
        ref_enriched.append((fp_str, h_mne, h_wd, near_mne, near_wd))
    ref_min_near_wd = min((x[4] for x in ref_enriched), default=999.0)
    ref_enriched_sorted = sorted(ref_enriched, key=lambda x: (x[4], x[0]))

    print(f"  {'FP':<6}  {'H-slot':<7}  {'Nearest':<8}  {'Ham':>3}  {'WDist':>5}  Notes")
    print(f"  {'---':<6}  {'------':<7}  {'-------':<8}  {'---':>3}  {'-----':>5}  -----")
    for fp_str, h_mne, h_wd, near_mne, near_wd in ref_enriched_sorted:
        n_val  = ham(fp_str, near_mne)
        notes  = pos_notes(fp_str, near_mne)
        marker = "  <- worst offender" if abs(near_wd - ref_min_near_wd) < 1e-6 else ""
        print(f"  {fp_str:<6}  {h_mne:<7}  {near_mne:<8}  {n_val:>3}  {near_wd:>5.1f}  {notes}{marker}")

    print()


if __name__ == '__main__':
    main()
