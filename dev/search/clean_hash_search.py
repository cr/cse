#!/usr/bin/env python3
"""
clean_hash_search.py

Fully deterministic co-optimisation of mn6 hash parameters and fingerprint.
No randomness anywhere. Fixed, reproducible results.

Hash formula:  h6 = (c1*C1 + c3*C3 + T[c2]) & 0x3F
Fingerprint:   fp = (c1*A + c2*B) & 0xFF
"""

import sys
import time
import numpy as np

sys.path.insert(0, '/Users/cr/Documents/src/c64/cse/dev')
from instruction_set import sc, MNEMONICS

# ============================================================
# Build legal mnemonic list
# ============================================================
LEGAL = sorted(mne for mne, (_, _, cat) in MNEMONICS.items() if cat == 'legal')
assert len(LEGAL) == 56, f"Expected 56 legal mnemonics, got {len(LEGAL)}"

# Decompose each legal mnemonic into (c1, c2, c3) screencodes
LEGAL_CHARS = [(sc(m[0]), sc(m[1]), sc(m[2])) for m in LEGAL]

# ============================================================
# QWERTY adjacency
# ============================================================
QWERTY_ADJ = {frozenset(p) for p in [
    ('Q','W'),('W','E'),('E','R'),('R','T'),('T','Y'),('Y','U'),('U','I'),('I','O'),('O','P'),
    ('A','S'),('S','D'),('D','F'),('F','G'),('G','H'),('H','J'),('J','K'),('K','L'),
    ('Z','X'),('X','C'),('C','V'),('V','B'),('B','N'),('N','M'),
    ('Q','A'),('W','A'),('W','S'),('E','S'),('E','D'),('R','D'),('R','F'),
    ('T','F'),('T','G'),('Y','G'),('Y','H'),('U','H'),('U','J'),('I','J'),
    ('I','K'),('O','K'),('O','L'),('P','L'),
    ('A','Z'),('S','Z'),('S','X'),('D','X'),('D','C'),('F','C'),('F','V'),
    ('G','V'),('G','B'),('H','B'),('H','N'),('J','N'),('J','M'),('K','M'),
]}

def char_wdist(a, b):
    return 0.0 if a == b else (0.5 if frozenset([a, b]) in QWERTY_ADJ else 1.0)

def wdist(s1, s2):
    return sum(char_wdist(a, b) for a, b in zip(s1, s2))

# Verify
assert wdist("DDC", "DEC") == 0.5, "wdist check failed"

# ============================================================
# Build all 26^3 = 17576 3-letter strings
# ============================================================
LEGAL_SET = set(LEGAL)

ALL_STRINGS = []
ALL_SC_LIST = []
for a in range(1, 27):
    for b in range(1, 27):
        for c in range(1, 27):
            ch = chr(a + 64) + chr(b + 64) + chr(c + 64)
            ALL_STRINGS.append(ch)
            ALL_SC_LIST.append((a, b, c))

ALL_STRINGS = np.array(ALL_STRINGS)
ALL_SC = np.array(ALL_SC_LIST, dtype=np.int32)  # shape (17576, 3)
IS_LEGAL = np.array([s in LEGAL_SET for s in ALL_STRINGS], dtype=bool)

# Legal mnemonic arrays
LEGAL_C1 = np.array([c[0] for c in LEGAL_CHARS], dtype=np.int32)
LEGAL_C2 = np.array([c[1] for c in LEGAL_CHARS], dtype=np.int32)
LEGAL_C3 = np.array([c[2] for c in LEGAL_CHARS], dtype=np.int32)

# ============================================================
# Precompute adjacency matrix (screencodes 1..26)
# ============================================================
ADJ = np.zeros((27, 27), dtype=np.float32)
for i in range(1, 27):
    for j in range(1, 27):
        if i == j:
            ADJ[i, j] = 0.0
        elif frozenset([chr(i + 64), chr(j + 64)]) in QWERTY_ADJ:
            ADJ[i, j] = 0.5
        else:
            ADJ[i, j] = 1.0

# ============================================================
# Precompute wdist matrix
# ============================================================
print("Precomputing wdist matrix (17576 x 56)...", flush=True)
t0 = time.time()

WDIST_MATRIX = np.zeros((len(ALL_SC), 56), dtype=np.float32)
for k in range(3):
    col_all = ALL_SC[:, k]
    col_leg = np.array([sc(LEGAL[j][k]) for j in range(56)], dtype=np.int32)
    d = ADJ[col_all[:, None], col_leg[None, :]]  # (17576, 56)
    WDIST_MATRIX += d

MIN_WDIST_TO_LEGAL = WDIST_MATRIX.min(axis=1)   # (17576,)
NEAREST_LEGAL_IDX = WDIST_MATRIX.argmin(axis=1)  # (17576,)

print(f"Wdist matrix computed in {time.time()-t0:.2f}s", flush=True)

# ============================================================
# T-table solver (DETERMINISTIC iterative backtracking)
# ============================================================

def solve_T(C1, C3):
    """
    Find the first valid T table using bitmask backtracking.
    Each group's slot occupancy is a 64-bit integer; overlap checks are O(1).
    Groups processed largest-first (most constrained = best pruning).
    Returns T as a list of 27 ints, or None if no solution exists.
    """
    bases = [(chars[0] * C1 + chars[2] * C3) & 0x3F for chars in LEGAL_CHARS]

    c2_to_idx = {}
    for idx, chars in enumerate(LEGAL_CHARS):
        c2_to_idx.setdefault(chars[1], []).append(idx)

    # Most constrained group first
    c2_order = sorted(c2_to_idx.keys(), key=lambda c2: -len(c2_to_idx[c2]))
    n_groups = len(c2_order)

    # Precompute 64 bitmask patterns per group (one per candidate T value)
    # pattern[g][t] = bitmask of 64-bit slots occupied when T[c2_g] = t
    group_c2   = []
    group_pats = []
    for c2 in c2_order:
        grp_bases = [bases[i] for i in c2_to_idx[c2]]
        # Intra-group feasibility: all bases must be distinct mod 64
        if len(set(b & 0x3F for b in grp_bases)) < len(grp_bases):
            return None  # permanent collision regardless of T
        pats = []
        for t in range(64):
            mask = 0
            for b in grp_bases:
                mask |= 1 << ((b + t) & 0x3F)
            pats.append(mask)
        group_c2.append(c2)
        group_pats.append(pats)

    T   = [0] * 27
    tv  = [0] * n_groups        # next T value to try at each level
    occ = [0] * (n_groups + 1)  # cumulative slot bitmask at each level
    g   = 0
    while g < n_groups:
        pats    = group_pats[g]
        cur_occ = occ[g]
        found   = False
        for t in range(tv[g], 64):
            if pats[t] & cur_occ == 0:   # no slot overlap — O(1) bitmask AND
                T[group_c2[g]] = t
                tv[g]    = t + 1
                occ[g+1] = cur_occ | pats[t]
                if g + 1 < n_groups:
                    tv[g+1] = 0
                g    += 1
                found = True
                break
        if not found:
            tv[g] = 0
            if g == 0:
                return None
            g -= 1

    return T


def verify_perfect_hash(C1, C3, T):
    slots = [(chars[0] * C1 + chars[2] * C3 + T[chars[1]]) & 0x3F for chars in LEGAL_CHARS]
    return len(set(slots)) == 56


def compute_slots(C1, C3, T):
    return [(chars[0] * C1 + chars[2] * C3 + T[chars[1]]) & 0x3F for chars in LEGAL_CHARS]


# ============================================================
# Fingerprint search (DETERMINISTIC, numpy)
# ============================================================

def fingerprint_search(C1, C3, T):
    """
    Find best (A, B) in 0..255 for fingerprint fp = (c1*A + c2*B) & 0xFF.
    Returns (best_A, best_B, fp_count, min_wdl).
    """
    T_arr = np.array(T, dtype=np.int32)
    sc1 = ALL_SC[:, 0].astype(np.int64)
    sc2 = ALL_SC[:, 1].astype(np.int64)
    sc3 = ALL_SC[:, 2].astype(np.int64)

    h6_all = (sc1 * C1 + sc3 * C3 + T_arr[ALL_SC[:, 1]]) & 0x3F

    slots = compute_slots(C1, C3, T)
    h6_to_legal = np.full(64, -1, dtype=np.int32)
    for i, s in enumerate(slots):
        h6_to_legal[s] = i

    occ_legal_idx = h6_to_legal[h6_all]  # -1 if not a legal slot
    is_occupied = (occ_legal_idx >= 0)
    is_fp_candidate = is_occupied & ~IS_LEGAL

    if not np.any(is_fp_candidate):
        return (0, 0, 0, float('inf'))

    cand_mask = is_fp_candidate
    cand_sc1 = ALL_SC[cand_mask, 0].astype(np.int64)
    cand_sc2 = ALL_SC[cand_mask, 1].astype(np.int64)
    cand_leg_idx = occ_legal_idx[cand_mask].astype(np.int64)

    leg_sc1_cand = LEGAL_C1[cand_leg_idx].astype(np.int64)
    leg_sc2_cand = LEGAL_C2[cand_leg_idx].astype(np.int64)

    # FP condition: (cand_sc1*A + cand_sc2*B) ≡ (leg_sc1*A + leg_sc2*B) (mod 256)
    # delta1*A + delta2*B ≡ 0 (mod 256)
    delta1 = (cand_sc1 - leg_sc1_cand) & 0xFF
    delta2 = (cand_sc2 - leg_sc2_cand) & 0xFF
    n_cands = len(delta1)

    cand_indices = np.where(cand_mask)[0]
    cand_min_wdl = MIN_WDIST_TO_LEGAL[cand_indices].astype(np.float64)

    # Fast approach: group candidates by unique (delta1, delta2) pair.
    # For a given (d1, d2), the set of (A,B) where the candidate is a FP is:
    #   {(A,B) : (d1*A + d2*B) & 0xFF == 0}
    # This solution matrix is computed in one (256,256) numpy broadcast per group.
    # With c1,c2 screencodes in 1..26 the differences span at most 51 values each,
    # giving at most 51*51 = 2601 unique groups — far fewer Python iterations than
    # the previous approach (n_cands * 256 ≈ 4M iterations).
    A_vals = np.arange(256, dtype=np.uint16)
    B_vals = np.arange(256, dtype=np.uint16)

    fp_count_matrix = np.zeros((256, 256), dtype=np.int32)
    min_wdl_matrix  = np.full((256, 256), np.inf, dtype=np.float32)

    # Group candidate indices by (delta1, delta2)
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for k in range(n_cands):
        groups[(int(delta1[k]), int(delta2[k]))].append(k)

    for (d1, d2), idx_list in groups.items():
        group_wdl = float(cand_min_wdl[idx_list].min())
        count     = len(idx_list)
        # (A,B) solution matrix: (d1*A + d2*B) mod 256 == 0
        d1A   = (d1 * A_vals)[:, None] & 0xFF   # (256, 1)
        d2B   = (d2 * B_vals)[None, :] & 0xFF   # (1, 256)
        is_fp = ((d1A + d2B) & 0xFF) == 0       # (256, 256) bool
        fp_count_matrix += count * is_fp.astype(np.int32)
        min_wdl_matrix   = np.where(is_fp,
                                    np.minimum(min_wdl_matrix, group_wdl),
                                    min_wdl_matrix)

    min_wdl_out = np.where(fp_count_matrix == 0, np.inf, min_wdl_matrix)

    # Best (A,B): max min_wdl, then min fp_count, then min A*256+B
    best_min_wdl_val = min_wdl_out.max()

    tol = 1e-9
    cand_ab = (min_wdl_out >= best_min_wdl_val - tol)
    # Among these, min fp_count
    fp_filtered = np.where(cand_ab, fp_count_matrix, 999999)
    min_fp_val = fp_filtered.min()
    final_mask = cand_ab & (fp_count_matrix == min_fp_val)
    # First in row-major order (A ascending, then B ascending)
    a_idx, b_idx = np.argwhere(final_mask)[0]

    return (int(a_idx), int(b_idx), int(fp_count_matrix[a_idx, b_idx]),
            float(min_wdl_out[a_idx, b_idx]))


# ============================================================
# Get FP details
# ============================================================
def get_fp_details(C1, C3, T, A, B):
    """Return list of (fp_string, slot, near_slot, near_wdl, wdl, fp_val) for all FPs."""
    T_arr = np.array(T, dtype=np.int32)
    sc1 = ALL_SC[:, 0].astype(np.int64)
    sc2 = ALL_SC[:, 1].astype(np.int64)
    sc3 = ALL_SC[:, 2].astype(np.int64)

    h6_all = (sc1 * C1 + sc3 * C3 + T_arr[ALL_SC[:, 1]]) & 0x3F
    slots = compute_slots(C1, C3, T)
    h6_to_legal = np.full(64, -1, dtype=np.int32)
    for i, s in enumerate(slots):
        h6_to_legal[s] = i

    occ_legal_idx = h6_to_legal[h6_all]
    is_occupied = (occ_legal_idx >= 0)
    is_fp_candidate = is_occupied & ~IS_LEGAL

    fp_all = (sc1 * A + sc2 * B) & 0xFF
    # Expected fp for each occupied slot
    leg_fp_arr = np.array([(LEGAL_CHARS[i][0] * A + LEGAL_CHARS[i][1] * B) & 0xFF
                            for i in range(56)], dtype=np.int64)
    safe_occ = np.maximum(occ_legal_idx, 0)
    expected_fp = leg_fp_arr[safe_occ]
    is_fp = is_fp_candidate & (fp_all == expected_fp)

    result = []
    for idx in np.where(is_fp)[0]:
        s = ALL_STRINGS[idx]
        slot = int(h6_all[idx])
        leg_idx = int(occ_legal_idx[idx])
        near_slot = LEGAL[leg_idx]
        wdl = float(MIN_WDIST_TO_LEGAL[idx])
        near_wdl = LEGAL[NEAREST_LEGAL_IDX[idx]]
        fp_val = int(fp_all[idx])
        result.append((s, slot, near_slot, near_wdl, wdl, fp_val))

    result.sort(key=lambda x: (x[4], x[0]))
    return result


# ============================================================
# Main search: C1 in 1..63, C3 in 1..63
# ============================================================
print("\nStarting main search C1 in 1..63, C3 in 1..63...", flush=True)
total_candidates = 63 * 63
print(f"Total (C1,C3) pairs: {total_candidates}", flush=True)

results = []
candidate_count = 0
t_search_start = time.time()

for C1 in range(1, 64):
    for C3 in range(1, 64):
        candidate_count += 1
        if candidate_count % 500 == 0:
            elapsed = time.time() - t_search_start
            rate = candidate_count / elapsed
            eta = (total_candidates - candidate_count) / rate
            print(f"  Progress: {candidate_count}/{total_candidates} "
                  f"(C1={C1}, C3={C3}) valid={len(results)} "
                  f"elapsed={elapsed:.0f}s ETA={eta:.0f}s", flush=True)

        T = solve_T(C1, C3)
        if T is None:
            continue

        best_A, best_B, fp_count, min_wdl = fingerprint_search(C1, C3, T)
        results.append({
            'C1': C1, 'C3': C3, 'T': tuple(T),
            'A': best_A, 'B': best_B,
            'fp_count': fp_count, 'min_wdl': min_wdl,
        })

print(f"\nSearch complete in {time.time()-t_search_start:.1f}s. "
      f"Valid (C1,C3) pairs: {len(results)}", flush=True)

# ============================================================
# Current hash reference
# ============================================================
T_current = [0x00,0x0D,0x08,0x04,0x05,0x00,0x00,0x00,0x04,0x0A,0x00,0x00,0x00,0x0D,0x02,0x00,
             0x03,0x00,0x01,0x00,0x00,0x00,0x0A,0x00,0x04,0x0A,0x00]
C1_curr, C3_curr = 9, 5

assert verify_perfect_hash(C1_curr, C3_curr, T_current), "Current hash is NOT perfect!"
print(f"Verified: current hash (C1=9, C3=5) is a perfect hash.", flush=True)

curr_A, curr_B, curr_fp_count, curr_min_wdl = fingerprint_search(C1_curr, C3_curr, T_current)
curr_entry = {
    'C1': C1_curr, 'C3': C3_curr, 'T': tuple(T_current),
    'A': curr_A, 'B': curr_B,
    'fp_count': curr_fp_count, 'min_wdl': curr_min_wdl,
}
# Update or append current entry
found_curr = False
for i, r in enumerate(results):
    if r['C1'] == C1_curr and r['C3'] == C3_curr:
        results[i] = curr_entry  # use original T, not solver's T
        found_curr = True
        break
if not found_curr:
    results.append(curr_entry)
    print(f"Added current config (C1=9, C3=5) as extra entry.")

# ============================================================
# Sort
# ============================================================
def sort_key(r):
    mw = r['min_wdl']
    # -inf for min_wdl (descending), then fp_count asc, then C1 asc, C3 asc
    neg_mw = -mw if mw != float('inf') else float('-inf')
    # Actually inf is best, so we want inf first then descending
    if mw == float('inf'):
        primary = -9999.0  # sort as best (most negative → sort last in ascending → we want FIRST)
    else:
        primary = -mw
    return (primary, r['fp_count'], r['C1'], r['C3'])

# max min_wdl = inf is best, so reverse sign:
# sort by (-min_wdl when finite, else -inf → but inf should be first)
# Let's convert: inf → very large positive for -mw perspective
def sort_key2(r):
    mw = r['min_wdl']
    neg_mw = -(mw if mw != float('inf') else 1e9)
    return (neg_mw, r['fp_count'], r['C1'], r['C3'])

results.sort(key=sort_key2)

# ============================================================
# Print results table
# ============================================================
SEP = "="*112
SEP2 = "-"*112
print("\n" + SEP)
print("RESULTS TABLE (sorted: min_wdl DESC, fp_count ASC, C1 ASC, C3 ASC)")
print(SEP)
print(f"{'Rank':>5}  {'C1':>3}  {'C3':>3}  {'A':>3}  {'B':>3}  {'FPs':>5}  {'min_wdl':>8}  T_hex (first 8 bytes)")
print(SEP2)

for rank, r in enumerate(results, 1):
    wdl_str = f"{r['min_wdl']:.1f}" if r['min_wdl'] != float('inf') else "  inf"
    t_hex = ' '.join(f'{v:02X}' for v in r['T'][:8])
    label = f"{rank:>5}"
    if r['C1'] == C1_curr and r['C3'] == C3_curr:
        label = "  cur"
    print(f"{label}  {r['C1']:>3}  {r['C3']:>3}  {r['A']:>3}  {r['B']:>3}  "
          f"{r['fp_count']:>5}  {wdl_str:>8}  {t_hex}")

# ============================================================
# Helpers for detailed output
# ============================================================
def print_T_annotated(T, C1, C3, A, B, label=""):
    print(f"\n  === {label} ===")
    print(f"  C1={C1}  C3={C3}  A={A}  B={B}")
    active_c2 = set(chars[1] for chars in LEGAL_CHARS)
    print(f"  Full 27-byte T table (index = c2 screencode; 0=guard, 1=A..26=Z):")
    print(f"  {'idx':>4}  {'ch':>2}  {'act':>3}  {'hex':>4}  {'dec':>3}")
    for i in range(27):
        ch = chr(i + 64) if i > 0 else '_'
        act = '*' if i in active_c2 else ' '
        print(f"  {i:>4}  {ch:>2}  {act:>3}  0x{T[i]:02X}  {T[i]:>3}")
    print(f"  T list: [{', '.join(f'0x{T[i]:02X}' for i in range(27))}]")
    print(f"  h6 formula: h6 = (c1*{C1} + c3*{C3} + T[c2]) & 0x3F")
    print(f"  fp formula: fp = (c1*{A} + c2*{B}) & 0xFF")


def print_fp_breakdown(fp_details):
    fp_count = len(fp_details)
    print(f"\n  FP count: {fp_count}")
    if fp_count == 0:
        print(f"  (No false positives — perfect fingerprint for this hash)")
        return
    buckets = {'<1.0': [], '=1.0': [], '=1.5': [], '>=2.0': []}
    for row in fp_details:
        wdl = row[4]
        if wdl < 1.0:
            buckets['<1.0'].append(row)
        elif abs(wdl - 1.0) < 1e-9:
            buckets['=1.0'].append(row)
        elif abs(wdl - 1.5) < 1e-9:
            buckets['=1.5'].append(row)
        else:
            buckets['>=2.0'].append(row)
    print(f"  WDL bucket breakdown:")
    for k, v in buckets.items():
        print(f"    WDL {k}: {len(v)}")
    min_wdl = min(r[4] for r in fp_details)
    print(f"  min_wdl over all FPs: {min_wdl:.1f}")
    print(f"\n  Complete FP table (sorted WDL ASC, then FP string ASC):")
    print(f"  {'FP':>4}  {'H-slot':>6}  {'Near-slot':>9}  {'Near-wdl':>8}  {'WDL':>5}  fp_val")
    print(f"  {'-'*4}  {'-'*6}  {'-'*9}  {'-'*8}  {'-'*5}  ------")
    for s, slot, near_slot, near_wdl, wdl, fp_val in fp_details:
        print(f"  {s:>4}  {slot:>6}  {near_slot:>9}  {near_wdl:>8}  {wdl:>5.1f}  0x{fp_val:02X}")


# ============================================================
# Detailed top 5
# ============================================================
print("\n" + SEP)
print("DETAILED OUTPUT: TOP 5 CANDIDATES")
print(SEP)

for rank, r in enumerate(results[:5], 1):
    wdl_str = f"{r['min_wdl']:.1f}" if r['min_wdl'] != float('inf') else "inf"
    print(f"\n{'='*80}")
    print(f"RANK {rank}: C1={r['C1']} C3={r['C3']} A={r['A']} B={r['B']} "
          f"FPs={r['fp_count']} min_wdl={wdl_str}")
    print_T_annotated(r['T'], r['C1'], r['C3'], r['A'], r['B'],
                      label=f"Rank {rank}: C1={r['C1']} C3={r['C3']}")
    fp_details = get_fp_details(r['C1'], r['C3'], r['T'], r['A'], r['B'])
    print_fp_breakdown(fp_details)

# ============================================================
# Special detailed analysis
# ============================================================
print("\n" + SEP)
print("SPECIAL DETAILED ANALYSIS: TOP CANDIDATE, C1=4/C3=6, C1=9/C3=5 (current)")
print(SEP)

special = []
# Top candidate
top = results[0]
special.append(('Top candidate', top['C1'], top['C3'], list(top['T']), top['A'], top['B']))

# C1=4, C3=6
r46 = next((r for r in results if r['C1'] == 4 and r['C3'] == 6), None)
if r46:
    special.append(('C1=4 C3=6', 4, 6, list(r46['T']), r46['A'], r46['B']))
else:
    T46 = solve_T(4, 6)
    if T46 and verify_perfect_hash(4, 6, T46):
        A46, B46, fp46, wdl46 = fingerprint_search(4, 6, T46)
        special.append(('C1=4 C3=6', 4, 6, T46, A46, B46))
    else:
        print("C1=4 C3=6: no perfect hash found (not in search results).")

# Current
special.append(('C1=9 C3=5 (current)', C1_curr, C3_curr,
                 T_current, curr_A, curr_B))

for label, C1, C3, T, A, B in special:
    fp_details = get_fp_details(C1, C3, T, A, B)
    wdl_str = f"{min((x[4] for x in fp_details), default=float('inf')):.1f}" if fp_details else "inf"
    print(f"\n{'='*80}")
    print(f"CONFIG: {label}")
    print_T_annotated(T, C1, C3, A, B, label=label)
    print_fp_breakdown(fp_details)

print("\nDone.")
