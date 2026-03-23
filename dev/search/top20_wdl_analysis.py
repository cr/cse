#!/usr/bin/env python3
"""
dev/top20_wdl_analysis.py

Step 1: Regenerate all 1,264 valid (T, C1, C3) hash combinations using the
        targeted T-solver (same random seed as hash_search.py).

Step 2: Initial ranking by (fp_count ASC, C1+C3 ASC) using the OLD metric
        (min-fp-count over all (A,B)). Extract top 20.

Step 3: For each of the top 20 candidates, compute the CORRECT fingerprint
        quality metric:
          For each (A,B) in 0..255 x 0..255:
            - fp = (c1*A + c2*B) & 0xFF
            - FP = non-legal string that passes hash + fingerprint
            - min_wdl = min wdist-to-nearest-LEGAL over all FPs
          Best (A,B) = argmax(min_wdl), break ties argmin(fp_count).

Step 4: Print summary ranking (correct metric), statistics, and full FP
        detail for the single best candidate.

Also includes the current design (C1=9, C3=5, A=1, B=166) as a reference row.

Run from /Users/cr/Documents/src/c64/cse/dev/
"""

import sys
import time
import random
import numpy as np
from collections import defaultdict

random.seed(42)
np.random.seed(42)

sys.path.insert(0, '/Users/cr/Documents/src/c64/cse/dev')
from instruction_set import MNEMONICS, sc

# ---------------------------------------------------------------------------
# Mnemonic data
# ---------------------------------------------------------------------------

LEGAL = [m for m, (_, _, cat) in MNEMONICS.items() if cat == 'legal']
assert len(LEGAL) == 56, f"Expected 56 legal mnemonics, got {len(LEGAL)}"

LEGAL_SET = set(LEGAL)
LEGAL_CODES = np.array([(sc(m[0]), sc(m[1]), sc(m[2])) for m in LEGAL], dtype=np.int32)
L_c1 = LEGAL_CODES[:, 0]
L_c2 = LEGAL_CODES[:, 1]
L_c3 = LEGAL_CODES[:, 2]

INVALID = [(a, b, c)
           for a in range(1, 27)
           for b in range(1, 27)
           for c in range(1, 27)
           if chr(a+64)+chr(b+64)+chr(c+64) not in LEGAL_SET]

INV_c1 = np.array([x[0] for x in INVALID], dtype=np.int32)
INV_c2 = np.array([x[1] for x in INVALID], dtype=np.int32)
INV_c3 = np.array([x[2] for x in INVALID], dtype=np.int32)

ACTIVE_C2 = sorted(set(int(v) for v in L_c2))

print(f"Legal mnemonics:        {len(LEGAL)}")
print(f"Invalid 3-letter strings: {len(INVALID)}")
print(f"Active c2 positions ({len(ACTIVE_C2)}): {[chr(v+64) for v in ACTIVE_C2]}")

# ---------------------------------------------------------------------------
# QWERTY adjacency and wdist LUT (26x26, indices 1..26 = A..Z)
# ---------------------------------------------------------------------------

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

# Verify adjacency
_v = wdist("DDC", "DEC")
print(f"\nVerification: wdist('DDC','DEC') = {_v}  (expected 0.5)", end="")
assert _v == 0.5, f"  FAILED! Got {_v}"
print("  PASSED")

WDIST_LUT = np.zeros((27, 27), dtype=np.float32)
for _a in range(1, 27):
    for _b in range(1, 27):
        ca, cb = chr(_a+64), chr(_b+64)
        if _a == _b:
            WDIST_LUT[_a, _b] = 0.0
        elif frozenset([ca, cb]) in QWERTY_ADJ:
            WDIST_LUT[_a, _b] = 0.5
        else:
            WDIST_LUT[_a, _b] = 1.0

# ---------------------------------------------------------------------------
# Precompute wdist from every invalid string to every legal mnemonic
# Shape: (n_inv, 56)  -- used for CORRECT metric
# ---------------------------------------------------------------------------

print("\nPrecomputing WDIST_INV_LEGAL matrix...", flush=True)
t0 = time.time()
WD_c1 = WDIST_LUT[INV_c1[:, None], L_c1[None, :]]
WD_c2 = WDIST_LUT[INV_c2[:, None], L_c2[None, :]]
WD_c3 = WDIST_LUT[INV_c3[:, None], L_c3[None, :]]
WDIST_INV_LEGAL = WD_c1 + WD_c2 + WD_c3          # (n_inv, 56)
MIN_WDL_PER_INV = WDIST_INV_LEGAL.min(axis=1)     # (n_inv,)  min over 56 legal mnes
print(f"  Done in {time.time()-t0:.2f}s  shape={WDIST_INV_LEGAL.shape}")

# ---------------------------------------------------------------------------
# Current T
# ---------------------------------------------------------------------------

T_CURRENT = np.array([
    0x00, 0x0D, 0x08, 0x04, 0x05, 0x00, 0x00, 0x00,
    0x04, 0x0A, 0x00, 0x00, 0x00, 0x0D, 0x02, 0x00,
    0x03, 0x00, 0x01, 0x00, 0x00, 0x00, 0x0A, 0x00,
    0x04, 0x0A, 0x00,
], dtype=np.int32)

# ---------------------------------------------------------------------------
# Perfect-hash check
# ---------------------------------------------------------------------------

def is_perfect(C1, C3, T_np):
    h = (L_c1 * C1 + L_c3 * C3 + T_np[L_c2]) & 0x3F
    return len(np.unique(h)) == 56

# ---------------------------------------------------------------------------
# T-solver (greedy, randomised): for a given (C1, C3), find T values
# ---------------------------------------------------------------------------

_c2_groups = defaultdict(list)
for i, row in enumerate(LEGAL_CODES):
    _c2_groups[int(row[1])].append((i, int(row[0]), int(row[2])))

def try_solve_T(C1, C3):
    """Return a T array that makes h=(c1*C1+c3*C3+T[c2])&0x3F a perfect hash,
    or None if the greedy assignment fails."""
    group_bases = {}
    for c2v, members in _c2_groups.items():
        bases = [(c1v * C1 + c3v * C3) & 0x3F for (_, c1v, c3v) in members]
        group_bases[c2v] = bases
    # Intra-group collision check
    for c2v, bases in group_bases.items():
        if len(set(bases)) < len(bases):
            return None
    # Greedy assignment (largest groups first)
    used_slots = set()
    T_sol = np.zeros(27, dtype=np.int32)
    for c2v, bases in sorted(group_bases.items(), key=lambda x: -len(x[1])):
        ok = False
        for s in random.sample(range(64), 64):
            slots = {(b + s) & 0x3F for b in bases}
            if not (slots & used_slots):
                T_sol[c2v] = s
                used_slots |= slots
                ok = True
                break
        if not ok:
            return None
    return T_sol

# ---------------------------------------------------------------------------
# INITIAL RANKING: fast min-fp-count (OLD metric, count only) for all 1264
# ---------------------------------------------------------------------------

def min_fp_count(C1, C3, T_np):
    """Return minimum achievable fp_count over all (A,B) [0..255]^2.

    Uses frequency-based approach: O(|unique (d1,d2)| * 256) per candidate,
    much faster than the original O(n_coll * 256) loop.
    """
    lh = (L_c1 * C1 + L_c3 * C3 + T_np[L_c2]) & 0x3F
    ih = (INV_c1 * C1 + INV_c3 * C3 + T_np[INV_c2]) & 0x3F

    lsm = np.zeros(64, dtype=bool)
    lsm[lh] = True
    ci = np.where(lsm[ih])[0]
    if len(ci) == 0:
        return (0, 0, 0)

    s2l = np.full(64, -1, dtype=np.int32)
    s2l[lh] = np.arange(56, dtype=np.int32)
    li = s2l[ih[ci]]

    ic1 = INV_c1[ci].astype(np.uint8)
    ic2 = INV_c2[ci].astype(np.uint8)
    lc1 = L_c1[li].astype(np.uint8)
    lc2 = L_c2[li].astype(np.uint8)

    d1 = (ic1 - lc1).astype(np.uint8)  # mod-256 difference
    d2 = (ic2 - lc2).astype(np.uint8)

    # Build frequency table of (d1, d2) pairs
    freq = np.zeros((256, 256), dtype=np.int32)
    for i in range(len(d1)):
        freq[int(d1[i]), int(d2[i])] += 1

    # For each (A,B): counts[A,B] = sum_{d1v,d2v} freq[d1v,d2v] * ((d1v*A+d2v*B) & 0xFF == 0)
    A_vals = np.arange(256, dtype=np.int32)
    B_vals = np.arange(256, dtype=np.int32)
    counts = np.zeros((256, 256), dtype=np.int32)

    nz = np.argwhere(freq > 0)
    for d1v, d2v in nz:
        cnt = int(freq[d1v, d2v])
        term_A = (int(d1v) * A_vals) & 0xFF          # (256,)
        term_B = (int(d2v) * B_vals) & 0xFF          # (256,)
        # match[A,B] = (term_A[A] + term_B[B]) & 0xFF == 0
        match = ((term_A[:, None].astype(np.uint8) +
                  term_B[None, :].astype(np.uint8)) == 0)
        counts += match.astype(np.int32) * cnt

    best = int(np.argmin(counts))
    bA, bB = divmod(best, 256)
    return (bA, bB, int(counts[bA, bB]))

# ---------------------------------------------------------------------------
# CORRECT METRIC: best (A,B) by argmax(min_wdl), break ties argmin(fp_count)
# ---------------------------------------------------------------------------

def find_best_fp_wdl(C1, C3, T_np):
    """Returns (best_A, best_B, fp_count, min_wdl) using the correct objective:
    For each (A,B): min_wdl = min wdist-to-nearest-LEGAL over all FPs.
    Best = argmax(min_wdl), ties broken by argmin(fp_count).
    """
    lh = (L_c1 * C1 + L_c3 * C3 + T_np[L_c2]) & 0x3F
    ih = (INV_c1 * C1 + INV_c3 * C3 + T_np[INV_c2]) & 0x3F

    lsm = np.zeros(64, dtype=bool)
    lsm[lh] = True
    ci = np.where(lsm[ih])[0]
    if len(ci) == 0:
        return (0, 0, 0, 3.0)

    s2l = np.full(64, -1, dtype=np.int32)
    s2l[lh] = np.arange(56, dtype=np.int32)
    li = s2l[ih[ci]]

    ic1 = INV_c1[ci]
    ic2 = INV_c2[ci]
    lc1_fp = L_c1[li]
    lc2_fp = L_c2[li]

    mwdl = MIN_WDL_PER_INV[ci]          # min wdist-to-nearest-LEGAL per collision

    d1 = (ic1 - lc1_fp).astype(np.int32)
    d2 = (ic2 - lc2_fp).astype(np.int32)

    B_range = np.arange(256, dtype=np.int32)

    best_score  = (-1.0, 10**9)
    best_params = (0, 0, 0, -1.0)

    for A in range(256):
        term_A  = (d1 * A) & 0xFF                                               # (n_coll,)
        term_AB = (term_A[:, None] + d2[:, None] * B_range[None, :]) & 0xFF    # (n_coll, 256)
        coll    = (term_AB == 0)                                                # (n_coll, 256)

        fp_cnt = coll.sum(axis=0)                                               # (256,)
        min_wdl = np.where(coll, mwdl[:, None], 3.0).min(axis=0)              # (256,)

        order = np.lexsort((fp_cnt, -min_wdl))
        bb = int(order[0])
        mw = float(min_wdl[bb])
        fc = int(fp_cnt[bb])

        score = (mw, -fc)
        if score > best_score:
            best_score  = score
            best_params = (A, bb, fc, mw)

    return best_params

# ===========================================================================
# STEP 1: Generate all 1,264 valid (T, C1, C3) combinations
# ===========================================================================

print("\n" + "="*70)
print("STEP 1: Generating all valid (T, C1, C3) combinations")
print("  Method: targeted T-solver (C1,C3 in 1..63 x 1..63, 5 attempts each)")
print("="*70, flush=True)

t_step1 = time.time()
solved_tables = []   # list of (T_np, C1, C3)
N_ATTEMPTS = 5

for C1 in range(1, 64):
    for C3 in range(1, 64):
        for attempt in range(N_ATTEMPTS):
            T_sol = try_solve_T(C1, C3)
            if T_sol is not None and is_perfect(C1, C3, T_sol):
                solved_tables.append((T_sol.copy(), C1, C3))
                break

# Also include current T
for C1 in range(1, 64):
    for C3 in range(1, 64):
        if is_perfect(C1, C3, T_CURRENT):
            # Add if not already present (current T might match a solved entry)
            already = any(
                np.array_equal(T_np, T_CURRENT) and c1 == C1 and c3 == C3
                for (T_np, c1, c3) in solved_tables
            )
            if not already:
                solved_tables.append((T_CURRENT.copy(), C1, C3))

print(f"  Found {len(solved_tables)} valid (T, C1, C3) combinations  [{time.time()-t_step1:.2f}s]")

# ===========================================================================
# STEP 2: Initial ranking using OLD metric (min fp_count over all (A,B))
# ===========================================================================

print("\n" + "="*70)
print("STEP 2: Initial ranking by (fp_count ASC, C1+C3 ASC) [OLD metric]")
print("="*70, flush=True)

t_step2 = time.time()
initial_results = []
n = len(solved_tables)
for idx, (T_np, C1, C3) in enumerate(solved_tables):
    is_curr = (np.array_equal(T_np, T_CURRENT) and C1 == 9 and C3 == 5)
    bA, bB, fc = min_fp_count(C1, C3, T_np)
    initial_results.append({
        'T_np': T_np, 'C1': C1, 'C3': C3,
        'A_old': bA, 'B_old': bB, 'fp_old': fc,
        'is_current': is_curr,
    })
    if (idx + 1) % 100 == 0 or idx + 1 == n:
        elapsed = time.time() - t_step2
        print(f"  {idx+1}/{n}  elapsed={elapsed:.1f}s", flush=True)

initial_results.sort(key=lambda r: (r['fp_old'], r['C1'] + r['C3']))
print(f"\n  Ranking complete: {len(initial_results)} candidates  [{time.time()-t_step2:.1f}s]")

print(f"\n  Top 20 by (fp_count ASC, C1+C3 ASC) [OLD metric = min wdist to H-slot]:")
print(f"  {'#':>3}  {'C1':>4}  {'C3':>4}  {'A_old':>6}  {'B_old':>6}  {'fp_old':>8}  curr?")
print("  " + "-"*52)
for i, r in enumerate(initial_results[:20], 1):
    curr_marker = " <-- current" if r['is_current'] else ""
    print(f"  {i:3d}  {r['C1']:4d}  {r['C3']:4d}  {r['A_old']:6d}  {r['B_old']:6d}  {r['fp_old']:8d}{curr_marker}")

top20 = initial_results[:20]

# ===========================================================================
# STEP 3: CORRECT metric for each of the top 20
# ===========================================================================

print("\n" + "="*70)
print("STEP 3: CORRECT metric for top 20  (min_wdl = min wdist-to-nearest-LEGAL)")
print("  For each candidate: find best (A,B) by argmax(min_wdl), then argmin(fp_count)")
print("="*70, flush=True)

t_step3 = time.time()
for i, r in enumerate(top20, 1):
    C1, C3, T_np = r['C1'], r['C3'], r['T_np']
    print(f"  [{i:2d}/20] C1={C1:2d} C3={C3:2d}...", end="", flush=True)
    t_s = time.time()
    A, B, fc, mw = find_best_fp_wdl(C1, C3, T_np)
    r['A_corr'] = A
    r['B_corr'] = B
    r['fp_corr'] = fc
    r['mw_corr'] = mw
    print(f"  A={A:3d} B={B:3d} fp={fc:4d} min_wdl={mw:.3f}  [{time.time()-t_s:.2f}s]")

print(f"\n  Step 3 complete  [{time.time()-t_step3:.1f}s]")

# ===========================================================================
# STEP 3b: Results table
# ===========================================================================

print("\n" + "="*70)
print("STEP 3: RESULTS — Top 20 candidates with CORRECT metric")
print("  fp = (c1*A + c2*B) & $FF")
print("="*70)
print(f"  {'#':>3}  {'C1':>4}  {'C3':>4}  {'A':>5}  {'B':>5}  {'fp_count':>9}  {'min_wdl':>8}  note")
print("  " + "-"*60)
for i, r in enumerate(top20, 1):
    note = " <-- current" if r['is_current'] else ""
    print(f"  {i:3d}  {r['C1']:4d}  {r['C3']:4d}  {r['A_corr']:5d}  {r['B_corr']:5d}  {r['fp_corr']:9d}  {r['mw_corr']:8.3f}{note}")

# Reference: current design A=1, B=166
print("\n  --- Reference: current design (C1=9, C3=5, T_current, A=1, B=166) ---")
_lh = (L_c1 * 9 + L_c3 * 5 + T_CURRENT[L_c2]) & 0x3F
_ih = (INV_c1 * 9 + INV_c3 * 5 + T_CURRENT[INV_c2]) & 0x3F
_lsm = np.zeros(64, dtype=bool); _lsm[_lh] = True
_fp_tbl = np.zeros(64, dtype=np.int32)
_fp_tbl[_lh] = (L_c1 * 1 + L_c2 * 166) & 0xFF
_ci = np.where(_lsm[_ih])[0]
if len(_ci) > 0:
    _fp_match = ((INV_c1[_ci] * 1 + INV_c2[_ci] * 166) & 0xFF) == _fp_tbl[_ih[_ci]]
    _fp_idx = _ci[_fp_match]
    ref_fc = int(_fp_match.sum())
    ref_mwdl = float(MIN_WDL_PER_INV[_fp_idx].min()) if ref_fc > 0 else 3.0
else:
    ref_fc = 0; ref_mwdl = 3.0
print(f"  REF  C1=9  C3=5  A=1  B=166  fp_count={ref_fc}  min_wdl={ref_mwdl:.3f}")

# ===========================================================================
# SUMMARY RANKING
# ===========================================================================

print("\n" + "="*70)
print("SUMMARY RANKING — sorted by (min_wdl DESC, fp_count ASC)")
print("="*70)

ranked = sorted(top20, key=lambda r: (-r['mw_corr'], r['fp_corr']))

print(f"  {'Rank':>4}  {'C1':>4}  {'C3':>4}  {'A':>5}  {'B':>5}  {'fp_count':>9}  {'min_wdl':>8}  note")
print("  " + "-"*63)
for rank, r in enumerate(ranked, 1):
    note = " <-- current" if r['is_current'] else ""
    print(f"  {rank:4d}  {r['C1']:4d}  {r['C3']:4d}  {r['A_corr']:5d}  {r['B_corr']:5d}  {r['fp_corr']:9d}  {r['mw_corr']:8.3f}{note}")
print(f"\n  REF  (current design A=1,B=166)  fp_count={ref_fc}  min_wdl={ref_mwdl:.3f}")

cnt_ge15 = sum(1 for r in top20 if r['mw_corr'] >= 1.5)
cnt_ge20 = sum(1 for r in top20 if r['mw_corr'] >= 2.0)
best = ranked[0]
print(f"\n  Candidates with min_wdl >= 1.5 : {cnt_ge15} / 20")
print(f"  Candidates with min_wdl >= 2.0 : {cnt_ge20} / 20")
print(f"  Best min_wdl: {best['mw_corr']:.3f}  fp_count={best['fp_corr']}  C1={best['C1']} C3={best['C3']}")

# ===========================================================================
# STEP 4: Full detail for the single best candidate
# ===========================================================================

print("\n" + "="*70)
print("STEP 4: FULL DETAIL — Single best candidate")
print("="*70)

bc = ranked[0]
C1b = bc['C1']
C3b = bc['C3']
Ab  = bc['A_corr']
Bb  = bc['B_corr']
T_b = bc['T_np']

T_hex = ', '.join(f'${int(v):02X}' for v in T_b)
print(f"\nBest candidate:")
print(f"  C1 = {C1b},  C3 = {C3b}")
print(f"  A  = {Ab},  B  = {Bb}")
print(f"  fp_count = {bc['fp_corr']}")
print(f"  min_wdl  = {bc['mw_corr']:.3f}")
print(f"\n  Hash formula:        h6 = (c1*{C1b} + c3*{C3b} + T[c2]) & $3F")
print(f"  Fingerprint formula: fp = (c1*{Ab} + c2*{Bb}) & $FF")
print(f"\n  T table (27 bytes, hex):")
print(f"    [{T_hex}]")
print(f"\n  Non-zero active T entries:")
for pos in ACTIVE_C2:
    v = int(T_b[pos])
    if v != 0:
        print(f"    T[{chr(pos+64)}={pos}] = ${v:02X}")

# Verify perfect hash
assert is_perfect(C1b, C3b, T_b), "Perfect hash verification FAILED!"
print(f"\n  Perfect hash verification: PASSED (56/64 slots used)")

# Collect all FPs
lh_b = (L_c1 * C1b + L_c3 * C3b + T_b[L_c2]) & 0x3F
ih_b = (INV_c1 * C1b + INV_c3 * C3b + T_b[INV_c2]) & 0x3F

lsm_b = np.zeros(64, dtype=bool)
lsm_b[lh_b] = True

s2l_b = np.full(64, -1, dtype=np.int32)
s2l_b[lh_b] = np.arange(56, dtype=np.int32)

fp_tbl_b = np.zeros(64, dtype=np.int32)
fp_tbl_b[lh_b] = (L_c1 * Ab + L_c2 * Bb) & 0xFF

ci_b = np.where(lsm_b[ih_b])[0]
if len(ci_b) > 0:
    fp_match_b = ((INV_c1[ci_b] * Ab + INV_c2[ci_b] * Bb) & 0xFF) == fp_tbl_b[ih_b[ci_b]]
    fp_inv_indices = ci_b[fp_match_b]
else:
    fp_inv_indices = np.array([], dtype=np.int32)

# Build FP detail rows
detail_rows = []
for inv_idx in fp_inv_indices:
    ic1v = int(INV_c1[inv_idx])
    ic2v = int(INV_c2[inv_idx])
    ic3v = int(INV_c3[inv_idx])
    fp_str = chr(ic1v+64) + chr(ic2v+64) + chr(ic3v+64)

    h_slot  = int(ih_b[inv_idx])
    leg_idx = int(s2l_b[h_slot])
    hslot_mne = LEGAL[leg_idx]

    # wdist to H-slot mne
    wdh = float(WDIST_LUT[ic1v, int(L_c1[leg_idx])] +
                WDIST_LUT[ic2v, int(L_c2[leg_idx])] +
                WDIST_LUT[ic3v, int(L_c3[leg_idx])])
    ham_h = sum(1 for a, b in zip(fp_str, hslot_mne) if a != b)

    # nearest legal mnemonic
    wdl_vec = WDIST_INV_LEGAL[inv_idx, :]          # (56,)
    min_wdl_v = float(wdl_vec.min())
    near_leg_idx = int(np.argmin(wdl_vec))
    near_leg = LEGAL[near_leg_idx]

    # notes: which positions differ from H-slot and adjacency
    notes_parts = []
    for pos_i, (fc_ch, nc_ch) in enumerate(zip(fp_str, hslot_mne)):
        if fc_ch != nc_ch:
            adj = frozenset([fc_ch, nc_ch]) in QWERTY_ADJ
            notes_parts.append(f"c{pos_i+1}:{fc_ch}->{nc_ch}{'(adj)' if adj else ''}")
    notes = ' '.join(notes_parts)

    detail_rows.append({
        'fp':       fp_str,
        'hslot':    hslot_mne,
        'near_leg': near_leg,
        'wdl':      min_wdl_v,
        'ham':      ham_h,
        'wdh':      wdh,
        'notes':    notes,
    })

detail_rows.sort(key=lambda r: (r['wdl'], r['fp']))

# WDL bucket counts
cnt_lt10 = sum(1 for r in detail_rows if r['wdl'] <  1.0)
cnt_eq10 = sum(1 for r in detail_rows if r['wdl'] == 1.0)
cnt_eq15 = sum(1 for r in detail_rows if r['wdl'] == 1.5)
cnt_ge20 = sum(1 for r in detail_rows if r['wdl'] >= 2.0)

print(f"\nFP count by wdl bucket:")
print(f"  wdl < 1.0  : {cnt_lt10}")
print(f"  wdl = 1.0  : {cnt_eq10}")
print(f"  wdl = 1.5  : {cnt_eq15}")
print(f"  wdl >= 2.0 : {cnt_ge20}")
print(f"  Total      : {len(detail_rows)}")
assert len(detail_rows) == bc['fp_corr'], f"FP count mismatch: {len(detail_rows)} vs {bc['fp_corr']}"

# Print FP table
print(f"\nFull FP table  (sorted by wdl ASC, fp ASC):")
hdr = f"  {'FP':<5}  {'H-slot':<7}  {'Near-leg':<9}  {'WDL':>5}  {'Ham':>4}  {'WDH':>5}  Notes"
sep = "  " + "-"*(len(hdr)-2)
print(hdr)
print(sep)
for r in detail_rows:
    print(f"  {r['fp']:<5}  {r['hslot']:<7}  {r['near_leg']:<9}  "
          f"{r['wdl']:5.1f}  {r['ham']:4d}  {r['wdh']:5.1f}  {r['notes']}")

print(f"\nTotal elapsed: {time.time()-t0:.1f}s")
print("\nDone.")
