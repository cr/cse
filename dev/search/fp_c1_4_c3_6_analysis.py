#!/usr/bin/env python3
"""
dev/fp_c1_4_c3_6_analysis.py

Full false-positive cross-analysis for hash candidate C1=4, C3=6
with fingerprint fp=(c1*1 + c2*230) & $FF.

1. Recover T table via targeted T-solver.
2. Print full 27-byte T table annotated A..Z.
3. Verify wdist("DDC","DEC") == 0.5.
4. Run full FP analysis.
5. Print FP table sorted by WDL ASC, FP alphabetically.
6. Print bucket counts.
7. Print c2*230 lookup table (index 0..26 in hex).

Run from /Users/cr/Documents/src/c64/cse/dev/
"""

import sys
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

LEGAL   = [m for m, (_, _, cat) in MNEMONICS.items() if cat == 'legal']
ALL114  = list(MNEMONICS.keys())
assert len(LEGAL) == 56, f"Expected 56 legal, got {len(LEGAL)}"

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

# ---------------------------------------------------------------------------
# QWERTY adjacency (full physical including cross-row diagonals)
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

# Verify
_v = wdist("DDC", "DEC")
print(f"Verify: wdist('DDC','DEC') = {_v}  (expected 0.5)", end="")
assert _v == 0.5, f"  FAILED! Got {_v}"
print("  OK")

# Build WDIST LUT (indices 1..26)
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
# T-solver: for (C1, C3) find T via greedy group assignment
# ---------------------------------------------------------------------------

_c2_groups = defaultdict(list)
for i, row in enumerate(LEGAL_CODES):
    _c2_groups[int(row[1])].append((i, int(row[0]), int(row[2])))

def try_solve_T(C1, C3, seed_offset=0):
    """Return T array making h=(c1*C1+c3*C3+T[c2])&0x3F a perfect hash, or None."""
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
        r = random.Random(42 + seed_offset + c2v)
        order = list(range(64))
        r.shuffle(order)
        for s in order:
            slots = {(b + s) & 0x3F for b in bases}
            if not (slots & used_slots):
                T_sol[c2v] = s
                used_slots |= slots
                ok = True
                break
        if not ok:
            return None
    return T_sol

def is_perfect(C1, C3, T_np):
    h = (L_c1 * C1 + L_c3 * C3 + T_np[L_c2]) & 0x3F
    return len(np.unique(h)) == 56

# ---------------------------------------------------------------------------
# Solve T for C1=4, C3=6
# ---------------------------------------------------------------------------

C1 = 4
C3 = 6

print(f"\n{'='*70}")
print(f"Targeted T-solver for C1={C1}, C3={C3}")
print(f"{'='*70}")

T_sol = None
for attempt in range(200):
    T_try = try_solve_T(C1, C3, seed_offset=attempt * 100)
    if T_try is not None and is_perfect(C1, C3, T_try):
        T_sol = T_try
        print(f"  Solved in attempt {attempt+1}")
        break

if T_sol is None:
    print("  FAILED to find valid T after 200 attempts")
    sys.exit(1)

print(f"\nFull 27-byte T table (indices 0..26, VICII screencodes):")
print(f"  Index  Letter  T[idx]")
print(f"  -----  ------  ------")
for i in range(27):
    letter = chr(i+64) if i > 0 else '(0)'
    print(f"  {i:5d}  {letter:>6}  ${int(T_sol[i]):02X}")

print(f"\nT = [" + ", ".join(f"${int(v):02X}" for v in T_sol) + "]")

# Verify
assert is_perfect(C1, C3, T_sol), "Perfect hash verification FAILED!"
print(f"\nPerfect hash verified: PASSED (56/64 slots used)")

# Non-zero active entries
print(f"\nNon-zero active T entries:")
for pos in ACTIVE_C2:
    v = int(T_sol[pos])
    if v != 0:
        print(f"  T[{chr(pos+64)}={pos}] = ${v:02X} ({v})")

# ---------------------------------------------------------------------------
# Precompute WDIST_INV_LEGAL: (n_inv, 56) matrix
# ---------------------------------------------------------------------------

print(f"\nPrecomputing WDIST_INV_LEGAL...", flush=True)
WD_c1 = WDIST_LUT[INV_c1[:, None], L_c1[None, :]]
WD_c2 = WDIST_LUT[INV_c2[:, None], L_c2[None, :]]
WD_c3 = WDIST_LUT[INV_c3[:, None], L_c3[None, :]]
WDIST_INV_LEGAL = WD_c1 + WD_c2 + WD_c3           # (n_inv, 56)
MIN_WDL_PER_INV = WDIST_INV_LEGAL.min(axis=1)      # (n_inv,)
# Also track nearest legal index
NEAR_LEGAL_IDX = np.argmin(WDIST_INV_LEGAL, axis=1)  # (n_inv,)

# Also precompute WDIST_INV_ALL114 for Near-all / WDA
ALL114_CODES = np.array([(sc(m[0]), sc(m[1]), sc(m[2])) for m in ALL114], dtype=np.int32)
A114_c1 = ALL114_CODES[:, 0]
A114_c2 = ALL114_CODES[:, 1]
A114_c3 = ALL114_CODES[:, 2]

WDA_c1 = WDIST_LUT[INV_c1[:, None], A114_c1[None, :]]
WDA_c2 = WDIST_LUT[INV_c2[:, None], A114_c2[None, :]]
WDA_c3 = WDIST_LUT[INV_c3[:, None], A114_c3[None, :]]
WDIST_INV_ALL = WDA_c1 + WDA_c2 + WDA_c3
MIN_WDA_PER_INV = WDIST_INV_ALL.min(axis=1)
NEAR_ALL_IDX   = np.argmin(WDIST_INV_ALL, axis=1)
print(f"  Done.")

# ---------------------------------------------------------------------------
# Fingerprint parameters
# ---------------------------------------------------------------------------

FP_A = 1
FP_B = 230

print(f"\n{'='*70}")
print(f"Fingerprint: fp = (c1*{FP_A} + c2*{FP_B}) & $FF")
print(f"{'='*70}")

# Hash slots for legal mnemonics
lh = (L_c1 * C1 + L_c3 * C3 + T_sol[L_c2]) & 0x3F
# Hash slots for invalid strings
ih = (INV_c1 * C1 + INV_c3 * C3 + T_sol[INV_c2]) & 0x3F

# Legal slot occupancy
lsm = np.zeros(64, dtype=bool)
lsm[lh] = True

# Slot-to-legal index
s2l = np.full(64, -1, dtype=np.int32)
s2l[lh] = np.arange(56, dtype=np.int32)

# Fingerprint table: stored fp per slot
fp_tbl = np.zeros(64, dtype=np.int32)
fp_tbl[lh] = (L_c1 * FP_A + L_c2 * FP_B) & 0xFF

# Collision candidates (hash-slot match)
ci = np.where(lsm[ih])[0]
print(f"\nHash-slot collisions (before fingerprint): {len(ci)}")

# False positives: also fingerprint match
if len(ci) > 0:
    fp_match = ((INV_c1[ci] * FP_A + INV_c2[ci] * FP_B) & 0xFF) == fp_tbl[ih[ci]]
    fp_inv_indices = ci[fp_match]
else:
    fp_inv_indices = np.array([], dtype=np.int32)

print(f"False positives (hash+fingerprint match): {len(fp_inv_indices)}")

# ---------------------------------------------------------------------------
# Build detail rows
# ---------------------------------------------------------------------------

detail_rows = []
for inv_idx in fp_inv_indices:
    ic1v = int(INV_c1[inv_idx])
    ic2v = int(INV_c2[inv_idx])
    ic3v = int(INV_c3[inv_idx])
    fp_str = chr(ic1v+64) + chr(ic2v+64) + chr(ic3v+64)

    h_slot   = int(ih[inv_idx])
    leg_idx  = int(s2l[h_slot])
    hslot_mne = LEGAL[leg_idx]

    # WDH: wdist to H-slot mnemonic
    wdh = float(WDIST_LUT[ic1v, int(L_c1[leg_idx])] +
                WDIST_LUT[ic2v, int(L_c2[leg_idx])] +
                WDIST_LUT[ic3v, int(L_c3[leg_idx])])
    ham = sum(1 for a, b in zip(fp_str, hslot_mne) if a != b)

    # WDL: wdist to nearest LEGAL mnemonic
    wdl_val  = float(MIN_WDL_PER_INV[inv_idx])
    near_leg = LEGAL[int(NEAR_LEGAL_IDX[inv_idx])]

    # WDA: wdist to nearest ANY (all 114) mnemonic
    wda_val  = float(MIN_WDA_PER_INV[inv_idx])
    near_all = ALL114[int(NEAR_ALL_IDX[inv_idx])]

    # Notes: differences vs nearest legal
    notes_parts = []
    for pos_i, (fc_ch, nc_ch) in enumerate(zip(fp_str, near_leg)):
        if fc_ch != nc_ch:
            adj = frozenset([fc_ch, nc_ch]) in QWERTY_ADJ
            notes_parts.append(f"c{pos_i+1}:{fc_ch}->{nc_ch}{'(adj)' if adj else ''}")
    notes = ' '.join(notes_parts) if notes_parts else '(identical)'

    detail_rows.append({
        'fp':       fp_str,
        'hslot':    hslot_mne,
        'wdh':      wdh,
        'near_leg': near_leg,
        'wdl':      wdl_val,
        'near_all': near_all,
        'wda':      wda_val,
        'ham':      ham,
        'notes':    notes,
    })

# Sort by WDL ASC, FP alphabetically
detail_rows.sort(key=lambda r: (r['wdl'], r['fp']))

# ---------------------------------------------------------------------------
# Print FP table
# ---------------------------------------------------------------------------

print(f"\n{'='*70}")
print(f"Full FP table — sorted by WDL ASC, FP alphabetically")
print(f"  Fingerprint:  fp = (c1*{FP_A} + c2*{FP_B}) & $FF")
print(f"  Hash:         h  = (c1*{C1} + c3*{C3} + T[c2]) & $3F")
print(f"{'='*70}")
hdr = (f"  {'FP':<5}  {'H-slot':<7}  {'Near-leg':<9}  "
       f"{'WDL':>5}  {'Near-all':<9}  {'WDA':>5}  {'Ham':>3}  Notes (vs nearest legal)")
print(hdr)
print("  " + "-" * (len(hdr) - 2))
for r in detail_rows:
    print(f"  {r['fp']:<5}  {r['hslot']:<7}  {r['near_leg']:<9}  "
          f"{r['wdl']:5.1f}  {r['near_all']:<9}  {r['wda']:5.1f}  {r['ham']:3d}  {r['notes']}")

# ---------------------------------------------------------------------------
# Bucket counts
# ---------------------------------------------------------------------------

cnt_lt10 = sum(1 for r in detail_rows if r['wdl'] <  1.0)
cnt_eq10 = sum(1 for r in detail_rows if r['wdl'] == 1.0)
cnt_eq15 = sum(1 for r in detail_rows if r['wdl'] == 1.5)
cnt_ge20 = sum(1 for r in detail_rows if r['wdl'] >= 2.0)

print(f"\nFP count by WDL bucket:")
print(f"  WDL < 1.0  : {cnt_lt10}")
print(f"  WDL = 1.0  : {cnt_eq10}")
print(f"  WDL = 1.5  : {cnt_eq15}")
print(f"  WDL >= 2.0 : {cnt_ge20}")
print(f"  Total      : {len(detail_rows)}")

# ---------------------------------------------------------------------------
# c2*230 lookup table (index 0..26 in hex)
# ---------------------------------------------------------------------------

print(f"\n{'='*70}")
print(f"c2*230 lookup table  (fp_B={FP_B} = $E6)")
print(f"  Index = VICII screencode (0 = unused, 1=A .. 26=Z)")
print(f"{'='*70}")
print(f"  Idx  Letter  c2*{FP_B} mod 256  hex")
print(f"  ---  ------  -----------  ---")
for i in range(27):
    letter = chr(i+64) if i > 0 else '(0)'
    val = (i * FP_B) & 0xFF
    print(f"  {i:3d}  {letter:>6}     {val:10d}  ${val:02X}")

print(f"\n  As 27-byte table (index 0..26):")
vals_hex = ", ".join(f"${(i * FP_B) & 0xFF:02X}" for i in range(27))
print(f"  [{vals_hex}]")

print(f"\nDone.")
