#!/usr/bin/env python3
"""
dev/fp_wdist_analysis.py

Weighted Hamming distance analysis of false positives for three fingerprint
candidates using full physical QWERTY keyboard adjacency (including diagonals).
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from instruction_set import sc, MNEMONICS
from hashes import mn6

# ============================================================
# QWERTY physical adjacency (all pairs including diagonals)
# ============================================================

QWERTY_ADJ = {
    frozenset(pair) for pair in [
        # Row 0 horizontal
        ('Q','W'),('W','E'),('E','R'),('R','T'),('T','Y'),('Y','U'),('U','I'),('I','O'),('O','P'),
        # Row 1 horizontal
        ('A','S'),('S','D'),('D','F'),('F','G'),('G','H'),('H','J'),('J','K'),('K','L'),
        # Row 2 horizontal
        ('Z','X'),('X','C'),('C','V'),('V','B'),('B','N'),('N','M'),
        # Row0-Row1 diagonals
        ('Q','A'),('W','A'),('W','S'),('E','S'),('E','D'),('R','D'),('R','F'),
        ('T','F'),('T','G'),('Y','G'),('Y','H'),('U','H'),('U','J'),('I','J'),
        ('I','K'),('O','K'),('O','L'),('P','L'),
        # Row1-Row2 diagonals
        ('A','Z'),('S','Z'),('S','X'),('D','X'),('D','C'),('F','C'),('F','V'),
        ('G','V'),('G','B'),('H','B'),('H','N'),('J','N'),('J','M'),('K','M'),
    ]
}


def char_wdist(a, b):
    if a == b:
        return 0.0
    if frozenset([a, b]) in QWERTY_ADJ:
        return 0.5
    return 1.0


def wdist(s1, s2):
    return sum(char_wdist(a, b) for a, b in zip(s1, s2))


# ============================================================
# Verification
# ============================================================

print("=== Verification ===")
v1 = wdist("DDC", "DEC")
v2 = wdist("QXS", "AXS")
print(f"wdist('DDC','DEC') = {v1}  (expected 0.5)")
print(f"wdist('QXS','AXS') = {v2}  (expected 0.5)")
if v1 != 0.5:
    print("ERROR: DDC/DEC check FAILED - check adjacency definition")
if v2 != 0.5:
    print("ERROR: QXS/AXS check FAILED - check adjacency definition")
if v1 == 0.5 and v2 == 0.5:
    print("Both checks PASSED")
print()

# ============================================================
# Mnemonic sets
# ============================================================

# All 56 legal NMOS mnemonics
LEGAL_MNES = [mne for mne, (_, _, cat) in MNEMONICS.items() if cat == 'legal']
# All 114 mnemonics
ALL_MNES   = list(MNEMONICS.keys())

assert len(LEGAL_MNES) == 56, f"Expected 56 legal, got {len(LEGAL_MNES)}"
assert len(ALL_MNES)   == 114, f"Expected 114 total, got {len(ALL_MNES)}"

# ============================================================
# mn6 slot map (shared across all candidates)
# ============================================================

SLOT_MAP = mn6.build_slot_map()   # {slot: mne}

# mn6 hash constants
C1   = mn6.C1   # 9
C3   = mn6.C3   # 5
T    = mn6.T
MASK = mn6._mask()  # 0x3F

# ============================================================
# Fingerprint candidates
# ============================================================

# Each candidate: (A, B) where fp(c1,c2) = (c1*A + c2*B) & 0xFF
CANDIDATES = [
    (9,   1),
    (1, 166),
    (1,  53),
]

# ============================================================
# Helper: compute fp_table for a candidate
# ============================================================

def build_fp_table(A, B):
    """Return 64-entry fp table for fp = (c1*A + c2*B) & 0xFF."""
    fp = [0] * 64
    for h, mne in SLOT_MAP.items():
        c1v = sc(mne[0])
        c2v = sc(mne[1])
        fp[h] = (c1v * A + c2v * B) & 0xFF
    return fp

# ============================================================
# Helper: find nearest mnemonic(s) in a set by wdist
# ============================================================

def nearest(fp_str, mne_list):
    """Return (min_dist, [list of nearest mnes])."""
    best_d = float('inf')
    best   = []
    for m in mne_list:
        d = wdist(fp_str, m)
        if d < best_d:
            best_d = d
            best   = [m]
        elif d == best_d:
            best.append(m)
    return best_d, best

# ============================================================
# Helper: per-position notes vs h-slot mnemonic
# ============================================================

def position_notes(fp_str, hslot_mne):
    notes = []
    for i, (a, b) in enumerate(zip(fp_str, hslot_mne)):
        if a != b:
            adj = frozenset([a, b]) in QWERTY_ADJ
            pos_label = ['c1', 'c2', 'c3'][i]
            notes.append(f"{pos_label}:{a}→{b}{'(adj)' if adj else ''}")
    return ' '.join(notes)

# ============================================================
# Analysis per candidate
# ============================================================

LETTERS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
LEGAL_SET = frozenset(LEGAL_MNES)
ALL_SET   = frozenset(ALL_MNES)

for (A, B) in CANDIDATES:
    fp_table = build_fp_table(A, B)

    # Collect false positives
    fps = []
    for a in LETTERS:
        for b in LETTERS:
            for c in LETTERS:
                mne = a + b + c
                if mne in ALL_SET:
                    continue   # skip any real mnemonic (legal/illegal/cmos)
                c1v, c2v, c3v = sc(a), sc(b), sc(c)
                h = (c1v * C1 + c3v * C3 + T[c2v]) & MASK
                if h not in SLOT_MAP:
                    continue
                fp_val = (c1v * A + c2v * B) & 0xFF
                if fp_table[h] != fp_val:
                    continue
                # It's a false positive
                hslot_mne = SLOT_MAP[h]
                # Nearest among legal
                dl, nl_list = nearest(mne, LEGAL_MNES)
                # Nearest among all 114
                da, na_list = nearest(mne, ALL_MNES)
                # Ham vs h-slot
                ham = sum(1 for x, y in zip(mne, hslot_mne) if x != y)
                # wdist vs h-slot
                wdh = wdist(mne, hslot_mne)
                # Notes
                notes = position_notes(mne, hslot_mne)
                fps.append({
                    'fp':     mne,
                    'hslot':  hslot_mne,
                    'nl':     nl_list[0],   # first nearest-legal
                    'wdl':    dl,
                    'na':     na_list[0],   # first nearest-all
                    'wda':    da,
                    'ham':    ham,
                    'wdh':    wdh,
                    'notes':  notes,
                })

    # Sort: WDist-NL ASC, then WDist-NA ASC
    fps.sort(key=lambda r: (r['wdl'], r['wda']))

    # ---- Print ----
    print(f"{'='*80}")
    print(f"Fingerprint candidate: fp = (c1*{A} + c2*{B}) & 0xFF")
    print(f"Total false positives: {len(fps)}")
    print(f"{'='*80}")
    print()

    # Table header
    hdr = f"{'FP':<5}  {'H-slot':<6}  {'Near-legal':<10} {'WDL':>5}  {'Near-all':<8} {'WDA':>5}  {'Ham':>3} {'WDH':>5}  Notes"
    sep = '-' * len(hdr)
    print(hdr)
    print(sep)

    for r in fps:
        line = (
            f"{r['fp']:<5}  "
            f"{r['hslot']:<6}  "
            f"{r['nl']:<10} "
            f"{r['wdl']:>5.1f}  "
            f"{r['na']:<8} "
            f"{r['wda']:>5.1f}  "
            f"{r['ham']:>3} "
            f"{r['wdh']:>5.1f}  "
            f"{r['notes']}"
        )
        print(line)

    print()

    # ---- Summary ----
    cnt_lt1  = sum(1 for r in fps if r['wdl'] <  1.0)
    cnt_eq1  = sum(1 for r in fps if r['wdl'] == 1.0)
    cnt_gt1  = sum(1 for r in fps if r['wdl'] >  1.0)

    print(f"Summary for fp=(c1*{A}+c2*{B})&0xFF:")
    print(f"  Total FPs              : {len(fps)}")
    print(f"  FPs with WDL < 1.0    : {cnt_lt1}  (single adjacent-key typo reaches legal mnemonic)")
    print(f"  FPs with WDL = 1.0    : {cnt_eq1}")
    print(f"  FPs with WDL > 1.0    : {cnt_gt1}")

    if fps:
        worst = fps[0]  # sorted by WDL ASC so first = smallest WDL (worst offender)
        print(f"  Worst offender (min WDL):")
        print(f"    FP={worst['fp']}  H-slot={worst['hslot']}  Near-legal={worst['nl']}  WDL={worst['wdl']}  Near-all={worst['na']}  WDA={worst['wda']}  Ham={worst['ham']}  WDH={worst['wdh']}  Notes: {worst['notes']}")

    print()
