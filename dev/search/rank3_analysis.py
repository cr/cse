#!/usr/bin/env python3
"""
dev/rank3_analysis.py

Full analysis of hash candidate ranked #3 in the min_wdl summary:
  C1=59, C3=30, fp=(c1*2 + c2*81) & $FF, 24 FPs, min_wdl=1.5

1. Run targeted T-solver to find a T table for C1=59, C3=30.
2. Verify h6 = (c1*59 + c3*30 + T[c2]) & 0x3F is a perfect hash over 56 legal.
3. Full FP cross-analysis with fp = (c1*2 + c2*81) & $FF and CORRECT QWERTY adjacency.
4. WDL bucket counts + worst offender.
5. 6502 arithmetic cost assessment.

Run from /Users/cr/Documents/src/c64/cse/dev/
"""

import sys
import random
import numpy as np
from collections import defaultdict

# Use same seed as top20_wdl_analysis.py so T-solver behaviour is reproducible
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

# ---------------------------------------------------------------------------
# QWERTY adjacency (cross-row diagonals included) — as specified
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

# Verify adjacency example
_v = wdist("DDC", "DEC")
print(f"Verification: wdist('DDC','DEC') = {_v}  (expected 0.5)", end="")
assert _v == 0.5, f"  FAILED! Got {_v}"
print("  PASSED")

# WDIST LUT (indices 1..26 = A..Z)
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

# Precompute min wdist from every invalid string to nearest legal mnemonic
print("Precomputing WDIST_INV_LEGAL matrix...", flush=True)
WD_c1 = WDIST_LUT[INV_c1[:, None], L_c1[None, :]]
WD_c2 = WDIST_LUT[INV_c2[:, None], L_c2[None, :]]
WD_c3 = WDIST_LUT[INV_c3[:, None], L_c3[None, :]]
WDIST_INV_LEGAL = WD_c1 + WD_c2 + WD_c3          # (n_inv, 56)
MIN_WDL_PER_INV = WDIST_INV_LEGAL.min(axis=1)     # (n_inv,)
print(f"  Done  shape={WDIST_INV_LEGAL.shape}")

# ---------------------------------------------------------------------------
# T-solver (greedy, randomised) — same as top20_wdl_analysis.py
# ---------------------------------------------------------------------------
_c2_groups = defaultdict(list)
for i, row in enumerate(LEGAL_CODES):
    _c2_groups[int(row[1])].append((i, int(row[0]), int(row[2])))

def try_solve_T(C1, C3):
    group_bases = {}
    for c2v, members in _c2_groups.items():
        bases = [(c1v * C1 + c3v * C3) & 0x3F for (_, c1v, c3v) in members]
        group_bases[c2v] = bases
    for c2v, bases in group_bases.items():
        if len(set(bases)) < len(bases):
            return None
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

def is_perfect(C1, C3, T_np):
    h = (L_c1 * C1 + L_c3 * C3 + T_np[L_c2]) & 0x3F
    return len(np.unique(h)) == 56

# ===========================================================================
# PART 1: Find T table for C1=59, C3=30
# ===========================================================================

print("\n" + "="*70)
print("PART 1: T-solver for C1=59, C3=30")
print("="*70)

C1 = 59
C3 = 30

T_found = None
N_ATTEMPTS = 200  # try harder since we need exactly this (C1,C3)
for attempt in range(N_ATTEMPTS):
    T_sol = try_solve_T(C1, C3)
    if T_sol is not None and is_perfect(C1, C3, T_sol):
        T_found = T_sol
        print(f"  Solution found on attempt {attempt+1}")
        break

if T_found is None:
    print(f"  ERROR: No T solution found in {N_ATTEMPTS} attempts!")
    sys.exit(1)

T = T_found

print(f"\n  27-byte T table (hex):")
hex_vals = [f"${int(v):02X}" for v in T]
# Print in groups of 8 for readability
for i in range(0, 27, 8):
    chunk = hex_vals[i:i+8]
    print("    " + ", ".join(chunk))

print(f"\n  Full list: [{', '.join(hex_vals)}]")

print(f"\n  Non-zero active entries (c2 positions that appear in legal mnemonics):")
for pos in ACTIVE_C2:
    v = int(T[pos])
    print(f"    T[{chr(pos+64)}={pos:2d}] = ${v:02X} = {v:3d}")

# ===========================================================================
# PART 2: Verify perfect hash — slot assignments for all 56 legal mnemonics
# ===========================================================================

print("\n" + "="*70)
print("PART 2: Perfect hash verification — slot assignments for all 56 legal mnemonics")
print(f"  h6 = (c1*{C1} + c3*{C3} + T[c2]) & $3F")
print("="*70)

h_legal = (L_c1 * C1 + L_c3 * C3 + T[L_c2]) & 0x3F
assert len(np.unique(h_legal)) == 56, "NOT a perfect hash!"

# Print sorted by slot
slot_mne = sorted(zip(h_legal.tolist(), LEGAL))
print(f"\n  {'Slot':>5}  {'Mnemonic':<8}  {'c1':>4}  {'c2':>4}  {'c3':>4}  {'T[c2]':>6}  {'raw mod 64':>10}")
print("  " + "-"*55)
for slot, mne in slot_mne:
    c1v = sc(mne[0])
    c2v = sc(mne[1])
    c3v = sc(mne[2])
    tv  = int(T[c2v])
    raw = (c1v * C1 + c3v * C3) & 0x3F
    print(f"  {slot:5d}  {mne:<8}  {c1v:4d}  {c2v:4d}  {c3v:4d}  {tv:6d}  {raw:10d}")

print(f"\n  Unique slots: {len(np.unique(h_legal))} / 56  -> PERFECT HASH CONFIRMED")

# ===========================================================================
# PART 3: Full FP cross-analysis with fp = (c1*2 + c2*81) & $FF
# ===========================================================================

print("\n" + "="*70)
print("PART 3: Full FP cross-analysis")
print(f"  fp = (c1*2 + c2*81) & $FF  with  h6 = (c1*{C1} + c3*{C3} + T[c2]) & $3F")
print("="*70)

A_fp = 2
B_fp = 81

# Compute hash slots for invalid strings
ih = (INV_c1 * C1 + INV_c3 * C3 + T[INV_c2]) & 0x3F
lh = h_legal

# Legal slot mask and slot->legal index mapping
lsm = np.zeros(64, dtype=bool)
lsm[lh] = True

s2l = np.full(64, -1, dtype=np.int32)
s2l[lh] = np.arange(56, dtype=np.int32)

# Fingerprint table: fp value stored per hash slot (from legal mnemonic that owns that slot)
fp_tbl = np.zeros(64, dtype=np.int32)
fp_tbl[lh] = (L_c1 * A_fp + L_c2 * B_fp) & 0xFF

# Hash colliders (invalid strings that land in a legal slot)
ci = np.where(lsm[ih])[0]
print(f"\n  Hash colliders (invalid strings landing in a legal h-slot): {len(ci)}")

# Among colliders, those that also match the fingerprint
if len(ci) > 0:
    inv_fp = (INV_c1[ci] * A_fp + INV_c2[ci] * B_fp) & 0xFF
    legal_fp = fp_tbl[ih[ci]]
    fp_match = (inv_fp == legal_fp)
    fp_inv_indices = ci[fp_match]
else:
    fp_inv_indices = np.array([], dtype=np.int32)

print(f"  False positives (hash + fp match):                         {len(fp_inv_indices)}")

# Build detail rows
detail_rows = []
for inv_idx in fp_inv_indices:
    ic1v = int(INV_c1[inv_idx])
    ic2v = int(INV_c2[inv_idx])
    ic3v = int(INV_c3[inv_idx])
    fp_str = chr(ic1v+64) + chr(ic2v+64) + chr(ic3v+64)

    h_slot   = int(ih[inv_idx])
    leg_idx  = int(s2l[h_slot])
    hslot_mne = LEGAL[leg_idx]

    # wdist to H-slot mnemonic (= WDH)
    wdh = float(WDIST_LUT[ic1v, int(L_c1[leg_idx])] +
                WDIST_LUT[ic2v, int(L_c2[leg_idx])] +
                WDIST_LUT[ic3v, int(L_c3[leg_idx])])
    ham_h = sum(1 for a, b in zip(fp_str, hslot_mne) if a != b)

    # Nearest legal mnemonic (min wdist over all 56)
    wdl_vec    = WDIST_INV_LEGAL[inv_idx, :]
    min_wdl_v  = float(wdl_vec.min())
    near_leg_idx = int(np.argmin(wdl_vec))
    near_leg   = LEGAL[near_leg_idx]

    # wdist from FP to nearest-all (= WDA; same as WDL since over all 56)
    wda = min_wdl_v  # wdist to nearest legal = wdist to nearest all

    # Hamming distance (position-wise mismatches vs H-slot mne)
    ham = ham_h

    # Notes: differences vs nearest legal
    notes_parts = []
    for pos_i, (fc_ch, nc_ch) in enumerate(zip(fp_str, near_leg)):
        if fc_ch != nc_ch:
            adj = frozenset([fc_ch, nc_ch]) in QWERTY_ADJ
            notes_parts.append(f"c{pos_i+1}:{fc_ch}->{nc_ch}{'(adj)' if adj else ''}")
    notes_vs_near = ' '.join(notes_parts) if notes_parts else "(identical)"

    detail_rows.append({
        'fp':        fp_str,
        'h_slot':    h_slot,
        'hslot_mne': hslot_mne,
        'wdh':       wdh,
        'near_leg':  near_leg,
        'wdl':       min_wdl_v,
        'wda':       wda,
        'ham':       ham,
        'notes':     notes_vs_near,
    })

detail_rows.sort(key=lambda r: (r['wdl'], r['fp']))

# Print table
print(f"\n  Full FP table (sorted by WDL ASC, then FP alphabetically):")
hdr = (f"  {'FP':<5}  {'H-slot':>6}  {'Near-leg':>8}  {'WDL':>5}  {'Near-all':>8}  "
       f"{'WDA':>5}  {'Ham':>4}  Notes (vs nearest legal)")
sep = "  " + "-"*100
print(hdr)
print(sep)
for r in detail_rows:
    print(f"  {r['fp']:<5}  {r['hslot_mne']:>6}  {r['near_leg']:>8}  "
          f"{r['wdl']:5.1f}  {r['near_leg']:>8}  "
          f"{r['wda']:5.1f}  {r['ham']:>4}  {r['notes']}")

# ===========================================================================
# PART 4: WDL bucket counts + worst offender
# ===========================================================================

print("\n" + "="*70)
print("PART 4: WDL statistics")
print("="*70)

cnt_lt10 = sum(1 for r in detail_rows if r['wdl'] <  1.0)
cnt_eq10 = sum(1 for r in detail_rows if r['wdl'] == 1.0)
cnt_eq15 = sum(1 for r in detail_rows if r['wdl'] == 1.5)
cnt_ge20 = sum(1 for r in detail_rows if r['wdl'] >= 2.0)

print(f"\n  WDL < 1.0  : {cnt_lt10}")
print(f"  WDL = 1.0  : {cnt_eq10}")
print(f"  WDL = 1.5  : {cnt_eq15}")
print(f"  WDL >= 2.0 : {cnt_ge20}")
print(f"  Total FPs  : {len(detail_rows)}")

if detail_rows:
    worst = max(detail_rows, key=lambda r: (r['wdl'], r['fp']))
    best  = min(detail_rows, key=lambda r: (r['wdl'], r['fp']))

    print(f"\n  Worst offender (highest WDL):")
    print(f"    FP={worst['fp']}  H-slot={worst['hslot_mne']}  Near-leg={worst['near_leg']}"
          f"  WDL={worst['wdl']:.1f}  Ham={worst['ham']}  Notes: {worst['notes']}")

    if cnt_lt10 > 0:
        print(f"\n  Most dangerous FP (lowest WDL):")
        print(f"    FP={best['fp']}  H-slot={best['hslot_mne']}  Near-leg={best['near_leg']}"
              f"  WDL={best['wdl']:.1f}  Ham={best['ham']}  Notes: {best['notes']}")

# ===========================================================================
# PART 5: 6502 arithmetic cost assessment
# ===========================================================================

print("\n" + "="*70)
print("PART 5: 6502 arithmetic cost assessment")
print("="*70)

print("""
  Hash formula: h6 = (c1*59 + c3*30 + T[c2]) & $3F
  Fingerprint:  fp = (c1*2  + c2*81) & $FF

  ── C1 = 59 = 64 - 5 ──────────────────────────────────────────────────
  Goal: compute c1*59 mod 64  (only low 6 bits matter for & $3F)

  59 ≡ -5 (mod 64), so:
    c1 * 59 ≡ -(c1 * 5) (mod 64)
    c1 * 5  = c1 * 4 + c1 = (c1 << 2) + c1

  Assembly sequence (A = c1, result in A, mod-64 kept by final AND):
    ; A = c1 (screencode, 1..26)
    ASL A          ; A = c1*2
    ASL A          ; A = c1*4
    STA tmp        ; save c1*4
    LSR A          ; A = c1*2  (restore)
    LSR A          ; A = c1    (restore original c1)
    -- wait, cleaner approach:
    ; X = c1
    TXA            ; A = c1
    ASL A          ; A = c1*2
    ASL A          ; A = c1*4
    ADC #0         ; clear carry (or SEC then SBC below)
    ; actually: c1*5 = c1*4 + c1
    ; use TAX to preserve c1, then:

  Cleanest 6502 sequence for c1*59 mod 64:
    ; assume c1 in X (or saved)
    TXA            ; A = c1
    ASL A          ; A = c1*2
    ASL A          ; A = c1*4   (carry might be set if c1 > 15, but mod 64 = low 6 bits)
    STA tmp        ; tmp = c1*4
    TXA            ; A = c1
    ADC tmp        ; A = c1 + c1*4 = c1*5  (carry from ASL may corrupt - need CLC)
    ; With proper carry handling:
    TXA            ; A = c1
    CLC
    ASL A          ; c1*2
    ASL A          ; c1*4
    STA tmp
    TXA
    CLC
    ADC tmp        ; A = c1*5
    ; negate mod 256, then AND $3F gives mod 64:
    EOR #$FF
    CLC
    ADC #1         ; A = -c1*5 (two's complement)
    ; OR: SEC / SBC #0 after EOR won't work; use:
    ; EOR #$FF / ADC #1 with CLC... actually:
    ; -c1*5 mod 256 = (256 - c1*5) & $FF
    ; Since c1 in 1..26: c1*5 in 5..130, so 256-c1*5 in 126..251
    ; Then & $3F gives the low 6 bits = (64 - c1*5 mod 64) mod 64 ✓

  Cost for c1*59 (mod 64): ~8 instructions (TXA, CLC, ASL, ASL, STA tmp, TXA, CLC/ADC, EOR, ADC)
  = roughly 8 bytes + tmp byte

  ── C3 = 30 = 32 - 2 ──────────────────────────────────────────────────
  Goal: compute c3*30 mod 64

  30 ≡ -2 (mod 32) and mod 64: c3*30 = c3*(32-2) = c3*32 - c3*2
  mod 64: c3*32 mod 64 = (c3 & 1)*32  (only bit 0 of c3 survives *32 mod 64)
          c3*2 mod 64  = (c3 << 1) & $3F

  Simpler: 30 = 64 - 34... not helpful.
  Or: -c3*2 mod 64:
    c3*30 mod 64 = -(c3*2) mod 64  [since 30 ≡ -2 mod 32, but mod 64 is different]
    30 mod 64 = 30, -2 mod 64 = 62. These differ. So the mod-64 shortcut doesn't apply cleanly.

  Direct: c3*30 = c3*(16+8+4+2) = c3*16 + c3*8 + c3*4 + c3*2
    But keeping mod-64 throughout:
    c3 in 1..26:  c3*30 in 30..780
    c3*2:  c3 << 1 (≤52, fits in 6 bits for c3≤26)
    c3*4:  c3 << 2 (≤104)
    c3*8:  c3 << 3 (≤208)
    c3*16: c3 << 4 (≤416, wraps mod 64 to (c3<<4)&$3F)

  Practical 6502 sequence for c3*30 mod 64:
    ; Y = c3
    TYA            ; A = c3
    ASL A          ; c3*2
    STA tmp        ; save c3*2
    ASL A          ; c3*4
    ASL A          ; c3*8
    ASL A          ; c3*16
    CLC
    ADC tmp        ; c3*18 (=c3*16+c3*2)  -- hmm, need c3*30
    ; c3*30 = c3*32 - c3*2; or c3*30 = c3*16 + c3*8 + c3*4 + c3*2
    ; Restart:
    TYA            ; A = c3
    ASL A          ; c3*2  -> save
    STA tmp2
    ASL A          ; c3*4
    STA tmp3
    ASL A          ; c3*8
    STA tmp4
    ASL A          ; c3*16
    CLC
    ADC tmp4       ; c3*24
    ADC tmp3       ; c3*28
    ADC tmp2       ; c3*30
    ; 4 saves, 4 adds = expensive

  Cheaper via c3*30 = c3*(32-2) = -c3*2 mod 32, extended to mod 64:
    c3 in 1..26: c3*30 = c3*30.
    c3*30 mod 64: note 30 mod 64 = 30. For c3=1: 30. c3=2: 60. c3=3: 90→26. c3=4:120→56. etc.

    Alternative: c3*30 = (c3*2)*15 = (c3*2)*(16-1)
    Let t = c3*2 (1 ASL):
      t*16 - t = (t<<4) - t
      = c3*32 - c3*2
    mod 64: c3*32 mod 64 = (c3 % 2)*32  [only bit 0 matters for *32 mod 64]
    So: c3*30 mod 64 = ((c3 & 1)*32 - c3*2) & $3F
                     = ((c3 & 1)*32 + (-(c3*2)) ) & $3F

    6502 sequence:
    TYA            ; A = c3
    ASL A          ; A = c3*2, carry = c3 bit 6 (but c3≤26 so no carry)
    STA tmp        ; save c3*2
    EOR #$FF
    ADC #1         ; A = -(c3*2) [two's complement, carry will be 1 if c3*2 > 0]
    ; Need to add (c3 & 1)*32:
    TYA
    AND #$01       ; A = c3 & 1
    ASL A
    ASL A
    ASL A
    ASL A
    ASL A          ; A = (c3 & 1)*32
    CLC
    ADC tmp_neg    ; ... messy

  SIMPLEST: just use a 26-entry lookup table for c3*30 mod 64
    4 bytes: LDX c3 / LDA c3_30_tab,X / (merged with T table access)

  Or use two-step: c3*30 = c3*2*15. Store (c3*2) values in T lookup and multiply by 15 at runtime?

  Verdict on C3=30 cost:
    - Direct shift-add: 3-4 ASL + 3 CLC/ADC + 2 STA = ~10 bytes/cycles
    - Lookup table (26 bytes for c3): cheapest at 3 cycles (LDA abs,X)
    - Compared to C3=5 (current): c3*5 = c3*4+c3 = ASL,ASL,ADC = ~5 ops

  ── Fingerprint arithmetic ───────────────────────────────────────────────
  fp = (c1*2 + c2*81) & $FF

  c1*2:  1 ASL   (1 instruction, 2 cycles)

  c2*81 via 27-byte lookup table:
    Precompute table FP81[0..26] = (i * 81) & $FF for i = 0..26
    Values: 0,81,162,243,68,149,230,55,136,217,42,123,204,29,110,191,
            16,97,178,3,84,165,246,71,152,233,58
    At runtime: LDX c2 / LDA FP81,X   (5 cycles abs,X)

    This is the correct approach: no multiplication at runtime, just
    a 27-byte ROM table. Same cost as the existing HASH_T table.

    Total fingerprint cost: ASL (c1*2) + LDA FP81,X (c2*81) + ADC = ~3 instructions
""")

# Print the actual FP81 table values for reference
print("  FP81 table values (c2 * 81) & $FF for c2 = 0..26:")
fp81 = [(i * 81) & 0xFF for i in range(27)]
fp81_hex = [f"${v:02X}" for v in fp81]
for i in range(0, 27, 8):
    chunk = fp81_hex[i:i+8]
    indices = [f"{j}" for j in range(i, min(i+8, 27))]
    print(f"    [{', '.join(chunk)}]  ; c2={i}..{min(i+7,26)}")
print(f"  Full: [{', '.join(fp81_hex)}]")

print(f"\n  Assembly cost summary:")
print(f"    c1*59 (hash): ~8-9 bytes  (ASL*2 + ADC + NEG sequence)")
print(f"    c3*30 (hash): ~8-10 bytes (ASL*4 + ADC*3) or 3-byte table lookup")
print(f"    T[c2] lookup: LDX c2 / LDA HASH_T,X  = 2 instructions")
print(f"    c1*2  (fp):   ASL A = 1 instruction")
print(f"    c2*81 (fp):   LDX c2 / LDA FP81,X = 2 instructions")
print(f"    fp combine:   ADC = 1 instruction")
print(f"")
print(f"    vs current (C1=9, C3=5):")
print(f"    c1*9  = c1*8+c1 = ASL,ASL,ASL,ADC (4 ops)")
print(f"    c3*5  = c3*4+c3 = ASL,ASL,ADC (3 ops)")
print(f"    C1=59, C3=30 is more expensive than current C1=9, C3=5.")
print(f"    The fingerprint fp=(c1*2+c2*81)&FF costs similarly to current")
print(f"    (current uses c1*A+c2*B with small A,B coefficients).")

print(f"\n  NOTE: If h-slot mod-64 result is all that matters (AND $3F at end),")
print(f"  intermediate carries don't pollute result. The final AND $3F")
print(f"  ensures only low 6 bits matter, so we only need")
print(f"  (c1*59 + c3*30 + T[c2]) mod 64, not full 8-bit arithmetic.")
print(f"  This allows some shortcuts:")
print(f"    c3*30 mod 64 = c3*(30 mod 64) mod 64 = c3*30 mod 64")
print(f"    30 in binary = 011110, so c3*30 = c3*(32-2) = (c3<<5)-(c3<<1)")
print(f"    (c3<<5) mod 64: only c3's bit 0 and bit 1 survive:")
print(f"      (c3<<5) & $3F = (c3 & 1) << 5 ... = (c3 bit 0) * 32")
print(f"    So: c3*30 mod 64 = (c3_bit0)*32 - c3*2 (mod 64)")
print(f"    = ((c3 & 1) ? 32 : 0) - (c3*2) (mod 64)")
print(f"    Sequence: TYA / LSR A / BCC skip / LDA #32 / skip: SBC c3*2_val")
print(f"    ~5-6 instructions. Better than 10.")

print("\nDone.")
