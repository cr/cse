#!/usr/bin/env python3
"""
dev/mnemonic_tables.py

Assembler config table generator for the CSE 6502/65C02 assembler.
Imports all instruction-set definitions from dev/instruction_set.py.
Uses mn6 (6-bit hash, 56 legal NMOS mnemonics) and mn7 (7-bit hash, all 114
mnemonics) from dev/hashes.py.

Generates:
    src/mn_modes.s      – operand profile addressing-mode bitfield table (60 bytes)
    src/mn7_tables.s    – per-mnemonic tables, mn7 7-bit hash (3×128 = 384 bytes)
    src/mn6_tables.s    – per-mnemonic tables, mn6 6-bit hash (3×64  = 192 bytes)
    src/mn_asm_tables.s – mode_offset (64 B) + direct_opcodes (16 B)
    src/oplen_tbl.s     – packed opcode→length table (64 bytes)
"""
import functools
import operator
import pathlib

from instruction_set import (
    ALL_MODES, OPERAND_PROFILES, MNEMONICS, OPCODES,
    _N_OPERAND_PROFILES, _CMOS_PAIRS, _BIT_OPERAND, _BASE_OPCODE_OVERRIDES,
    mne_modes, sc, MODE_OPERAND_BYTES,
)
from hashes import mn6, mn7

# ============================================================
# Sanity checks
# ============================================================

def _check():
    assert len(MNEMONICS) == 114, f"Expected 114 mnemonics, got {len(MNEMONICS)}"
    assert len(OPERAND_PROFILES) == 30, f"Expected 30 profiles, got {len(OPERAND_PROFILES)}"

    by_cat = {'legal': [], 'illegal': [], 'cmos': []}
    by_set = {}
    errors = []

    for mne, (profile, cmos_bit, cat) in MNEMONICS.items():
        if cat not in by_cat:
            errors.append(f"{mne}: unknown category {cat!r}")
        else:
            by_cat[cat].append(mne)

        if not (0 <= profile < _N_OPERAND_PROFILES):
            errors.append(f"{mne}: unknown operand profile {profile!r}")
        else:
            by_set.setdefault(profile, []).append(mne)

        if cmos_bit:
            if profile + 1 >= _N_OPERAND_PROFILES:
                errors.append(f"{mne}: cmos_bit set but profile+1={profile+1} not in OPERAND_PROFILES")
            elif profile not in _CMOS_PAIRS:
                errors.append(f"{mne}: cmos_bit set but profile {profile} is not a declared CMOS base")
            else:
                nmos_p = OPERAND_PROFILES[profile]
                cmos_p = OPERAND_PROFILES[profile + 1]
                if not nmos_p < cmos_p:
                    errors.append(f"{mne}: profile {profile+1} is not a proper superset of profile {profile}")

    counts = {k: len(v) for k, v in by_cat.items()}
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        raise AssertionError("Sanity check failed")

    # Invariant: among legal mnemonics (cat 0 or 1), cat==1 ↔ _compute_exc_bit.
    # cat=2 (illegal) must have no exc modes; cat=3 (CMOS-only) may have
    # exc_bit=True (e.g. STZ) but is handled by dir_bit, not the exc path.
    for mne in MNEMONICS:
        cat_code = _compute_cat(mne)
        exc      = _compute_exc_bit(mne)
        if cat_code == 0 and exc:
            raise AssertionError(
                f"cat/exc invariant broken for {mne}: "
                f"cat=0 (legal-no-CMOS) but _compute_exc_bit=True"
            )
        if cat_code == 1 and not exc:
            raise AssertionError(
                f"cat/exc invariant broken for {mne}: "
                f"cat=1 (legal+CMOS) but _compute_exc_bit=False"
            )
        if cat_code == 2 and exc:
            raise AssertionError(
                f"cat/exc invariant broken for {mne}: "
                f"cat=2 (illegal) but _compute_exc_bit=True"
            )

    return by_cat, by_set, counts

# ============================================================
# Reporting
# ============================================================

def print_summary():
    by_cat, by_set, counts = _check()
    print(f"Total mnemonics : {len(MNEMONICS)}")
    print(f"  legal         : {counts['legal']}")
    print(f"  illegal       : {counts['illegal']}")
    print(f"  cmos          : {counts['cmos']}")
    print()

    cmos_bit_mnes = [m for m, (_, cb, _) in MNEMONICS.items() if cb]
    print(f"cmos_bit=True   : {len(cmos_bit_mnes)}  {sorted(cmos_bit_mnes)}")
    print()

    print("Operand profile breakdown  (30 profiles: zones A-F idx 0-5, G pairs idx 6-15, H idx 16-29):")
    for profile in range(_N_OPERAND_PROFILES):
        members = by_set.get(profile, [])
        modes_str = ','.join(sorted(OPERAND_PROFILES[profile]))
        pair_mark = '←CMOS' if profile-1 in _CMOS_PAIRS else ('NMOS→' if profile in _CMOS_PAIRS else '     ')
        cats = {}
        for m in members:
            c = MNEMONICS[m][2]
            cats.setdefault(c, []).append(m)
        cat_str = '  '.join(
            f"{c}:[{','.join(sorted(v))}]"
            for c, v in sorted(cats.items())
        )
        print(f"  profile {profile:2d} {pair_mark}  {{{modes_str:<44}}}  n={len(members):2d}  {cat_str}")
    print()


def print_by_category():
    by_cat, _, _ = _check()
    for cat in ('legal', 'cmos', 'illegal'):
        entries = sorted(by_cat[cat])
        print(f"{cat.upper()} ({len(entries)}):")
        for mne in entries:
            profile, cmos_bit, _ = MNEMONICS[mne]
            mode_str = ','.join(sorted(mne_modes(profile, cmos_bit)))
            cb = '+1' if cmos_bit else '  '
            print(f"  {mne}  {profile:2d}{cb}  {{{mode_str}}}")
        print()

# ============================================================
# Opcode verification
# ============================================================

def verify_opcodes():
    """Cross-check OPCODES keys against MNEMONICS mode sets."""
    errors = []
    for mne, (profile, cmos_bit, cat) in MNEMONICS.items():
        if mne not in OPCODES:
            errors.append(f"{mne}: missing from OPCODES")
            continue
        modes    = mne_modes(profile, cmos_bit)
        op_modes = frozenset(OPCODES[mne].keys())
        if op_modes != modes:
            extra   = op_modes - modes
            missing = modes - op_modes
            if extra:
                errors.append(f"{mne}: OPCODES has extra modes {extra}")
            if missing:
                errors.append(f"{mne}: OPCODES missing modes {missing}")
    for e in errors:
        print(f"MISMATCH: {e}")
    if not errors:
        print("verify_opcodes: OK")
    return errors

# ============================================================
# Base-opcode computation
# ============================================================
#
# For each mnemonic, the config table stores a "base opcode" that the
# assembler uses to compute the final emitted opcode:
#
#   Zone A–F (idx 0–5): opcode is fixed; base IS the final opcode.
#     Zone D (idx=3): runtime opcode = base | (bit<<4)   (RMB, SMB)
#     Zone E (idx=4): runtime opcode = base | (bit<<4)   (BBR, BBS)
#
#   Zone G/H (idx 6–29): base encodes aaa and cc with bbb zeroed.
#     Runtime: opcode = base | (bbb<<2),  where bbb = f(addressing mode).
#     Formula: base = reduce(AND, nmos_opcodes) & 0xE3
#       AND clears bits that differ across modes; & 0xE3 zeroes residual bbb.
#
# Five overrides – see _BASE_OPCODE_OVERRIDES in instruction_set.py.
#
# Note: STZ (65C02) has split aaa encoding – ZP/ZPX use aaa=3, while
#   ABS ($9C) has cc=0,aaa=4,bbb=7 and ABX ($9E) has cc=2,aaa=4,bbb=7.
#   No single base | (bbb<<2) formula covers all four modes.

def _compute_base_opcode(mne):
    """
    Return the base opcode for mne.

    Zone A–F (idx ≤ 5): single fixed mode; returns the opcode value directly.
    Zone G/H (idx > 5): returns reduce(AND, nmos_opcodes) & 0xE3.
    Overrides:          returns the hardcoded value from _BASE_OPCODE_OVERRIDES.
    Returns None if no valid (non-None) opcode is found.
    """
    if mne in _BASE_OPCODE_OVERRIDES:
        return _BASE_OPCODE_OVERRIDES[mne]
    profile, cmos_bit, cat = MNEMONICS[mne]
    nmos_modes = OPERAND_PROFILES[profile]
    vals = [v for m, v in OPCODES[mne].items()
            if m in nmos_modes and v is not None]
    if not vals:
        return None
    if profile <= 5:
        return vals[0]
    return functools.reduce(operator.and_, vals) & 0xE3


def _compute_exc_bit(mne):
    """
    True if ≥1 of this mnemonic's modes doesn't follow base_op|(bbb<<2).
    Covers: ZPI for cc=01 group, ACC for DEC/INC, IMM for BIT, IND/AIX for JMP.
    """
    profile, cmos_bit, _ = MNEMONICS[mne]
    if profile <= 5:
        return False  # Zone A-F: opcode fixed, no formula
    # RMB/SMB/BBR/BBS use digit-encoded override — no multi-mode exceptions
    if mne in _BASE_OPCODE_OVERRIDES and mne != 'JMP':
        return False
    base_op = _compute_base_opcode(mne)
    if base_op is None:
        return False
    # Check every mode (including CMOS extensions) against the NMOS-derived base
    for mode, opcode in OPCODES[mne].items():
        if opcode is None:
            continue
        if (opcode ^ base_op) & 0xE3 != 0:
            return True
    return False


def _compute_dir_bit(mne):
    """
    True if the mnemonic requires direct per-mode opcode lookup (split aaa/cc
    across NMOS modes — the bbb formula can't represent all modes).
    Currently only STZ triggers this (profile 28: ZP/ZPX use cc=0 aaa=3 while
    ABS uses cc=0 aaa=4 and ABX uses cc=2 aaa=4 — multiple aaa/cc values).
    Cross-mnemonic bbb conflicts (e.g. TRB vs TSB sharing profile 29, or
    zone=3/ABY where profiles 18/24 need bbb=7 while 25/27 need bbb=6) are
    left as $FF in mode_offset and handled by runtime exception code in
    opcode_lookup.s.
    """
    profile, cmos_bit, _ = MNEMONICS[mne]
    if profile <= 5:
        return False
    if mne in _BASE_OPCODE_OVERRIDES:
        return False
    nmos_modes = OPERAND_PROFILES[profile]
    aaa_cc = set()
    for mode in nmos_modes:
        opcode = OPCODES[mne].get(mode)
        if opcode is not None:
            aaa_cc.add(opcode & 0xE3)
    return len(aaa_cc) > 1


def _compute_cat(mne):
    """
    Return the 2-bit category code for the profile byte's bits 7:6.

        00  legal NMOS — no 65C02 extensions
        01  legal NMOS + 65C02 extensions (implies exc_bit: ≥1 non-formula CMOS mode)
        10  illegal NMOS
        11  CMOS-only mnemonic

    Mapping from MNEMONICS entry (profile, cmos_bit, category):
        category='legal',   cmos_bit=False  →  0
        category='legal',   cmos_bit=True   →  1
        category='illegal'                  →  2
        category='cmos'                     →  3

    Invariant: (_compute_cat(mne) == 1) == _compute_exc_bit(mne) for all mnemonics.
    """
    _, cmos_bit, category = MNEMONICS[mne]
    if category == 'illegal':
        return 2
    if category == 'cmos':
        return 3
    # legal
    return 1 if cmos_bit else 0


def verify_base_opcodes():
    """
    Verify that for every Zone G/H mnemonic (excluding overrides), the base
    opcode satisfies:  (opcode ^ base) & 0xE3 == 0  for all NMOS mode opcodes.
    """
    errors = []
    notes  = []
    for mne, (profile, cmos_bit, cat) in MNEMONICS.items():
        if profile <= 5:
            continue
        if mne in _BASE_OPCODE_OVERRIDES:
            continue
        nmos_modes = OPERAND_PROFILES[profile]
        vals = [(m, v) for m, v in OPCODES[mne].items()
                if m in nmos_modes and v is not None]
        if not vals:
            continue
        aaa_cc = {v & 0xE3 for _, v in vals}
        if len(aaa_cc) > 1:
            detail = ', '.join(f'{m}=${v:02X}' for m, v in sorted(vals))
            notes.append(f"{mne}: split aaa/cc; bbb formula n/a  ({detail})")
            continue
        base = _compute_base_opcode(mne)
        if base is None:
            errors.append(f"{mne}: no base opcode computed")
            continue
        for m, opcode in vals:
            if (opcode ^ base) & 0xE3 != 0:
                errors.append(
                    f"{mne} mode {m}: opcode=${opcode:02X} ^ base=${base:02X} "
                    f"has aaa/cc mismatch (diff=${(opcode ^ base) & 0xE3:02X})")
    for n in notes:
        print(f"NOTE: {n}")
    for e in errors:
        print(f"BASE_OPCODE ERROR: {e}")
    if not errors:
        suffix = f" ({len(notes)} note(s) above)" if notes else ""
        print(f"verify_base_opcodes: OK{suffix}")
    return errors

# ============================================================
# Mode bitfield helper
# ============================================================

def mode_bits(modes):
    """Return a 16-bit integer with bit i set iff ALL_MODES[i] ∈ modes."""
    bits = 0
    for i, m in enumerate(ALL_MODES):
        if m in modes:
            bits |= (1 << i)
    return bits

# ============================================================
# Table generators
# ============================================================

def write_mode_table(out_path=None):
    """
    Write src/mn_modes.s: a 30-entry × 2-byte operand profile mode bitfield table.

        mn_modes_lo  bits 0-7 : IMP ACC IMM ZP  ZPX ZPY ABS ABX
        mn_modes_hi  bits 0-7 : ABY IND INX INY REL ZPI AIX ZPREL

    Indexed by the 5-bit operand profile index (0-29).  30 × 2 = 60 bytes total.
    """
    if out_path is None:
        out_path = pathlib.Path(__file__).parent / '../src/mn_modes.s'
    out_path = pathlib.Path(out_path)

    profiles = list(range(_N_OPERAND_PROFILES))

    lo_bytes, hi_bytes = [], []
    for profile in profiles:
        bits = mode_bits(OPERAND_PROFILES[profile])
        lo_bytes.append(bits & 0xFF)
        hi_bytes.append((bits >> 8) & 0xFF)

    lo_legend = ' '.join(ALL_MODES[0:8])
    hi_legend  = ' '.join(ALL_MODES[8:16])

    def pair_comment(base):
        chunk  = profiles[base:base + 4]
        parts  = []
        for profile in chunk:
            if profile in _CMOS_PAIRS:
                parts.append(f'{profile}=NMOS')
            elif (profile - 1) in _CMOS_PAIRS:
                parts.append(f'{profile}=CMOS')
            else:
                parts.append(str(profile))
        return '  '.join(parts)

    lines = [
        '; mn_modes.s',
        '; Generated by dev/mnemonic_tables.py – DO NOT EDIT BY HAND',
        ';',
        '; Operand profile addressing-mode bitfield table.  30 profiles × 2 bytes = 60 bytes.',
        '; Indexed by the 5-bit operand profile field in the per-mnemonic config table (0..29).',
        ';',
        '; Index zones (see dev/instruction_set.py for full assembler dispatch map):',
        ';   idx = 0        IMP: no operand',
        ';   idx = 1        REL: 1-byte relative',
        ';   idx = 2        IMM: 1-byte immediate',
        ';   idx = 3        ZP:  leading bit(0-7) operand → opcode; 1-byte ZP addr',
        ';   idx = 4        ZPREL: leading bit(0-7) operand → opcode; ZP + rel',
        ';   idx = 5        ABS: 2-byte absolute  (JSR only)',
        ';   idx = 0..5     opcode fixed by mnemonic; no mode disambiguation',
        ';   idx = 6..15    NMOS/CMOS pairs: even=NMOS, odd=CMOS',
        ';                  if (idx & 1 == 0) and cpu==65C02: use idx+1',
        ';   idx = 16..29   standalone multi-mode, no CMOS upgrade',
        ';                  27=profile 8 bits  28=profile 10 bits  29=profile 12 bits (Zone G overflow)',
        f';   mn_modes_lo  bits 0-7 : {lo_legend}',
        f';   mn_modes_hi  bits 0-7 : {hi_legend}',
        '; A set bit means that addressing mode is supported by this profile.',
        '',
        '        .export mn_modes_lo, mn_modes_hi',
        '',
        '.segment "KDATA"',
        '',
    ]

    def emit_table(label, data):
        lines.append(f'{label}:')
        for base in range(0, len(profiles), 4):
            chunk    = profiles[base:base + 4]
            vals     = data[base:base + len(chunk)]
            hex_vals = ','.join(f'${v:02X}' for v in vals)
            hex_vals = f'{hex_vals:<23}'
            names    = '  '.join(str(p) for p in chunk)
            lines.append(f'        .byte   {hex_vals}  ; {names}')
        lines.append('')

    emit_table('mn_modes_lo', lo_bytes)
    emit_table('mn_modes_hi', hi_bytes)

    out_path.write_text('\n'.join(lines) + '\n')
    print(f"wrote {out_path.resolve()}  ({len(lo_bytes) + len(hi_bytes)} bytes, "
          f"{len(profiles)} operand profiles)")


def write_config_table_7bit(out_path=None):
    """
    Write src/mn7_tables.s: three 128-byte tables indexed by 7-bit hash h7.

        mn7_fp[h]        fingerprint: (c2<<3)|(c3>>2)  (0 = empty slot)
        mn7_base_op[h]   base opcode
        mn7_profile[h]   bits7:6=cat, bit5=dir_bit, bits4:0=profile_index(0-29)
                         cat: 00=legal-NMOS  01=legal+CMOS(exc)  10=illegal  11=CMOS-only

    384 bytes total.  Empty slots contain $00 in all three tables.

    The fingerprint is (c2<<3)|(c3>>2).  At runtime: TYA / 3×ASL / ORA mn7_h_tmp
    / CMP mn7_fp,X  (Y holds c2 and mn7_h_tmp holds c3>>2 from the hash phase).
    Since c2 ≥ 1, fp ≥ 8 always, so the $00 empty-slot sentinel is unreachable.
    Zero false positives over all 17,576 three-letter strings.
    See dev/hashes.py (mn7 class) and src/mn7.s.
    """
    if out_path is None:
        out_path = pathlib.Path(__file__).parent / '../src/mn7_tables.s'
    out_path = pathlib.Path(out_path)

    slot_mne      = mn7.build_slot_map()
    fp_table      = mn7.fingerprint_table()
    base_op_table = [0x00] * 128
    profile_table = [0x00] * 128

    for h, mne in slot_mne.items():
        profile, _, _    = MNEMONICS[mne]
        base_op          = _compute_base_opcode(mne)
        base_op_table[h] = base_op if base_op is not None else 0x00
        cat      = _compute_cat(mne)
        dir_flag = 1 if _compute_dir_bit(mne) else 0
        packed   = (cat << 6) | (dir_flag << 5) | profile
        profile_table[h] = packed

    lines = [
        '; mn7_tables.s',
        '; Generated by dev/mnemonic_tables.py – DO NOT EDIT BY HAND',
        ';',
        '; Per-mnemonic tables for the 7-bit full-114-mnemonic hash.',
        ';   h7  = (c1*4 + c3*1 + T7[c2]) & $7F  (VICII screencodes A=1..Z=26)',
        ';   fp  = (c2<<3) | (c3>>2)',
        ';',
        '; mn7_fp[h]       8-bit fingerprint  (0 = empty slot; fp ≥ 8 always)',
        '; mn7_base_op[h]  base opcode',
        '; mn7_profile[h]  bits7:6=cat(00=legal 01=legal+CMOS 10=illegal 11=CMOS-only)',
        ';                 bit5=dir_bit, bits4:0=profile_index(0-29)',
        ';',
        f'; {len(slot_mne)}/128 slots filled  ({128 - len(slot_mne)} empty)',
        '; 0 false positives — see dev/hashes.py mn7.verify_fingerprint()',
        '',
        '        .export mn7_fp',
        '        .export mn7_base_op, mn7_profile',
        '',
        '.segment "KDATA"',
        '',
    ]

    def emit_table(label, data):
        lines.append(f'{label}:')
        for row_base in range(0, 128, 8):
            chunk   = data[row_base:row_base + 8]
            hex_str = ','.join(f'${v:02X}' for v in chunk)
            mnes    = [f'{slot_mne.get(row_base + i, "---"):<3}' for i in range(8)]
            comment = '  '.join(mnes)
            lines.append(f'        .byte   {hex_str:<31}  ; {comment}')
        lines.append('')

    emit_table('mn7_fp',      fp_table)
    emit_table('mn7_base_op', base_op_table)
    emit_table('mn7_profile', profile_table)

    out_path.write_text('\n'.join(lines) + '\n')
    print(f"wrote {out_path.resolve()}  "
          f"(3×128 = 384 bytes, {len(slot_mne)}/128 slots filled)")


def write_config_table_6bit(out_path=None):
    """
    Write src/mn6_tables.s: three 64-byte tables indexed by 6-bit hash h6.

        mn6_fp[h]        fingerprint: (c1 + c2*218) & $FF  (0 = empty slot)
        mn6_base_op[h]   base opcode
        mn6_profile[h]   bits7:6=cat, bit5=dir_bit, bits4:0=profile_index(0-29)
                         cat: 00=legal-NMOS  01=legal+CMOS(exc)  10=illegal  11=CMOS-only
                         (mn6 only recognises legal NMOS; cat is always 00 for mn6 slots)

    192 bytes total.  Empty slots contain $00 in all three tables.

    The fingerprint is (c1 + c2*218) & $FF.  At runtime: LDA mn_c1 / CLC /
    ADC mn6_fp_c2,Y / CMP mn6_fp,X  (Y holds c2 from the hash phase).
    mn6_fp_c2 is a 27-byte table of (i*218)&$FF for i=0..26 in mn6.s.
    16 false positives remain (0.09%); all at min_wdl ≥ 1.5 (no false
    positive is within Hamming distance 1.5 of any legal mnemonic).
    See dev/mn6_fingerprint_collisions.txt.
    """
    if out_path is None:
        out_path = pathlib.Path(__file__).parent / '../src/mn6_tables.s'
    out_path = pathlib.Path(out_path)

    slot_mne    = mn6.build_slot_map()
    fp_table    = mn6.fingerprint_table()
    base_op_table = [0x00] * 64
    profile_table = [0x00] * 64

    for h, mne in slot_mne.items():
        profile, _, _    = MNEMONICS[mne]
        base_op          = _compute_base_opcode(mne)
        base_op_table[h] = base_op if base_op is not None else 0x00
        cat      = _compute_cat(mne)
        dir_flag = 1 if _compute_dir_bit(mne) else 0
        packed   = (cat << 6) | (dir_flag << 5) | profile
        profile_table[h] = packed

    lines = [
        '; mn6_tables.s',
        '; Generated by dev/mnemonic_tables.py – DO NOT EDIT BY HAND',
        ';',
        '; Per-mnemonic tables for the 6-bit legal-only NMOS mnemonic hash.',
        ';   h6  = (c1*8 + c3*15 + T6[c2]) & $3F  (VICII screencodes A=1..Z=26)',
        ';   fp  = (c1   + c2*218) & $FF',
        ';',
        '; mn6_fp[h]       8-bit fingerprint  (0 = empty slot)',
        '; mn6_base_op[h]  base opcode',
        '; mn6_profile[h]  bits7:6=cat(always 00 for mn6)  bit5=dir_bit  bits4:0=profile_index(0-29)',
        ';',
        f'; {len(slot_mne)}/64 slots filled  ({64 - len(slot_mne)} empty)',
        '; 16 known false positives (0.09%) — see dev/mn6_fingerprint_collisions.txt',
        '',
        '        .export mn6_fp',
        '        .export mn6_base_op, mn6_profile',
        '',
        '.segment "KDATA"',
        '',
    ]

    def emit_table(label, data):
        lines.append(f'{label}:')
        for row_base in range(0, 64, 8):
            chunk   = data[row_base:row_base + 8]
            hex_str = ','.join(f'${v:02X}' for v in chunk)
            mnes    = [f'{slot_mne.get(row_base + i, "---"):<3}' for i in range(8)]
            comment = '  '.join(mnes)
            lines.append(f'        .byte   {hex_str:<31}  ; {comment}')
        lines.append('')

    emit_table('mn6_fp',      fp_table)
    emit_table('mn6_base_op', base_op_table)
    emit_table('mn6_profile', profile_table)

    out_path.write_text('\n'.join(lines) + '\n')
    print(f"wrote {out_path.resolve()}  "
          f"(3×64 = 192 bytes, {len(slot_mne)}/64 slots filled)")


def write_asm_tables(out_path=None):
    """
    Write src/mn_asm_tables.s with two tables needed by the assembler's
    opcode-computation logic:

        mode_offset        64 bytes – 4 zones × 16 modes, byte = bbb<<2 to OR into
                                       base_op; $FF = invalid/exception sentinel
        direct_opcodes     16 bytes – direct opcode per mode for profile 28 (STZ);
                                       $00 = unused mode slot

    Zones: cc=00 at offset 0, cc=01 at offset 16, cc=10 at offset 32, cc=11 at offset 48.
    cc=11 is used by illegal NMOS opcodes (ASO/SLO, RLA, SRE/LSE, RRA, SAX/AAX, LAX,
    DCP/DCM, ISB/INS/ISC, SHA/AXA, TAS/SHS/XAS, LAS/LAR/LAX-absy).
    Slots where multiple mnemonics disagree on the bbb value are left as $FF;
    the runtime exception code in opcode_lookup.s handles those cases.
    All data derived from instruction_set.OPCODES.
    """
    if out_path is None:
        out_path = pathlib.Path(__file__).parent / '../src/mn_asm_tables.s'
    out_path = pathlib.Path(out_path)

    # ── mode_offset[zone][mode]: bbb<<2 to OR into base_op ────────────────
    # Initialise all entries to $FF (sentinel = invalid / exception-handled)
    # 4 zones: cc=00, cc=01, cc=10, cc=11 (cc=11 used by illegal NMOS mnemonics)
    mode_offset = [[0xFF] * 16 for _ in range(4)]

    errors = []
    # First pass: collect all (bbb_offset, mne) per (zone, mode_idx) slot
    slot_candidates = {}   # (zone, mode_idx) -> list of (bbb_offset, mne)
    for mne, (profile, cmos_bit, cat) in MNEMONICS.items():
        if profile <= 5:
            continue                 # Zone A-F: opcode fixed
        if cat == 'cmos':
            continue                 # CMOS-only: handled by CMOS runtime path
        if _compute_dir_bit(mne):
            continue                 # dir_bit: all modes are direct, skip formula
        base_op = _compute_base_opcode(mne)
        if base_op is None:
            continue
        zone = base_op & 0x03       # cc bits → zone index (0/1/2/3)
        nmos_modes = OPERAND_PROFILES[profile]
        for mode in nmos_modes:
            opcode = OPCODES[mne].get(mode)
            if opcode is None:
                continue
            # Skip modes that don't follow the formula (exc_bit exceptions)
            if (opcode ^ base_op) & 0xE3 != 0:
                continue
            bbb_offset = opcode & 0x1C   # = (bbb<<2)
            mode_idx   = list(ALL_MODES).index(mode)
            key = (zone, mode_idx)
            slot_candidates.setdefault(key, []).append((bbb_offset, mne))

    # Second pass: fill mode_offset, marking conflicted slots as $FF (exception)
    for (zone, mode_idx), candidates in slot_candidates.items():
        bbb_values = {bbb for bbb, _ in candidates}
        if len(bbb_values) == 1:
            mode_offset[zone][mode_idx] = candidates[0][0]
        else:
            # Genuine conflict: multiple mnemonics disagree on bbb for this
            # (zone, mode) slot.  Leave as $FF; the runtime exception code in
            # opcode_lookup.s handles all members of the conflicting slot
            # before @formula_table is reached.
            mne_list = ', '.join(f'{mne}=${bbb:02X}' for bbb, mne in candidates)
            print(f"NOTE: mode_offset conflict zone={zone} "
                  f"mode={list(ALL_MODES)[mode_idx]}: {mne_list} → $FF "
                  f"(handled by runtime exception in opcode_lookup.s)")

    # ── direct_opcodes: 16 bytes per dir_bit profile ──────────────────────
    # Profile 28 (STZ) has dir_bit=1 due to split aaa/cc.
    FIRST_DIR_PROFILE = 28
    N_DIR_PROFILES    = 1    # profiles 28..(28+N-1); 29-31 reserved
    direct_opcodes    = [0x00] * (N_DIR_PROFILES * 16)
    for mne, (profile, cmos_bit, _) in MNEMONICS.items():
        if not _compute_dir_bit(mne):
            continue
        dir_idx = profile - FIRST_DIR_PROFILE
        if not (0 <= dir_idx < N_DIR_PROFILES):
            errors.append(f"{mne}: dir profile {profile} out of range")
            continue
        all_mne_modes = mne_modes(profile, cmos_bit)
        for mode in all_mne_modes:
            opcode = OPCODES[mne].get(mode)
            if opcode is None:
                continue
            mode_idx = list(ALL_MODES).index(mode)
            direct_opcodes[dir_idx * 16 + mode_idx] = opcode
    if errors:
        for e in errors:
            print(f"ERROR: {e}")
        raise AssertionError("direct_opcodes table errors")

    # ── emit ──────────────────────────────────────────────────────────────
    mode_names = list(ALL_MODES)

    def fmt_row(data, base, n, label_fn=None):
        chunk = data[base:base+n]
        hex_  = ','.join(f'${v:02X}' for v in chunk)
        lbl   = label_fn(base, n) if label_fn else ''
        return f'        .byte   {hex_:<{n*4-1}}  ; {lbl}'

    lines = [
        '; mn_asm_tables.s',
        '; Generated by dev/mnemonic_tables.py – DO NOT EDIT BY HAND',
        ';',
        '; mode_offset      64 bytes  – 4 zones × 16 modes; byte = bbb<<2 to OR',
        ';                             into base_op; $FF = invalid/exception',
        ';                             zones: cc=00 [0..15], cc=01 [16..31], cc=10 [32..47], cc=11 [48..63]',
        f'; direct_opcodes   {N_DIR_PROFILES*16} bytes  – direct opcode per mode for dir_bit profiles',
        f';                             profile 28 (STZ) at offset 0  (FIRST_DIR_PROFILE=28)',
        ';',
        '        .export mode_offset, direct_opcodes',
        f'        .export FIRST_DIR_PROFILE',
        '',
        '.segment "KDATA"',
        '',
    ]

    # mode_offset
    zone_names = ['cc=00', 'cc=01', 'cc=10', 'cc=11 (illegal NMOS)']
    lines.append('mode_offset:')
    for z in range(4):
        row = mode_offset[z]
        lines.append(f'; {zone_names[z]}')
        for base in range(0, 16, 8):
            chunk = row[base:base+8]
            hex_  = ','.join(f'${v:02X}' for v in chunk)
            names = '  '.join(f'{ALL_MODES[base+i][:3]}' for i in range(8))
            lines.append(f'        .byte   {hex_:<35}  ; {names}')
        if z == 3:
            lines.append('        ; NOTE: ABY=$FF — genuine bbb conflict (bbb=6 vs bbb=7).')
            lines.append('        ;   All zone=3/ABY handled by runtime exception in opcode_lookup.s')
        lines.append('')

    # direct_opcodes
    lines.append(f'FIRST_DIR_PROFILE = {FIRST_DIR_PROFILE}')
    lines.append('direct_opcodes:')
    dir_profile_names = {28: 'profile 28 (STZ)'}
    for d in range(N_DIR_PROFILES):
        pname = dir_profile_names.get(FIRST_DIR_PROFILE + d, f'profile {FIRST_DIR_PROFILE+d}')
        lines.append(f'; {pname}')
        for base in range(0, 16, 8):
            chunk = direct_opcodes[d*16+base:d*16+base+8]
            hex_  = ','.join(f'${v:02X}' for v in chunk)
            names = '  '.join(f'{ALL_MODES[base+i][:3]}' for i in range(8))
            lines.append(f'        .byte   {hex_:<35}  ; {names}')
        lines.append('')

    out_path.write_text('\n'.join(lines) + '\n')
    print(f"wrote {out_path.resolve()}  "
          f"({64+N_DIR_PROFILES*16} bytes: 64 mode_offset + {N_DIR_PROFILES*16} direct_opcodes)")


# ============================================================
# Opcode → instruction length table (packed, 2 bits per opcode)
# ============================================================

def write_oplen_table():
    """Generate src/oplen_tbl.s — packed opcode→length table.

    64 bytes: 256 opcodes × 2 bits each, 4 per byte.
    Packing: byte[opc>>2], bits (opc&3)*2.  Position 0 in bits 1:0,
    position 1 in bits 3:2, position 2 in bits 5:4, position 3 in bits 7:6.
    This makes position 0 (the most common for aligned opcodes) the
    cheapest to extract (no shifts needed).

    Uses the full 65C02 instruction set — safe for all CPU modes since
    NMOS JAM opcodes (where lengths differ) halt the CPU anyway.
    """
    # Build 256-entry length array from OPCODES table
    lengths = [1] * 256  # default: 1 byte (implied/undefined)

    for mne, modes in OPCODES.items():
        for mode, opcode in modes.items():
            if opcode is None:
                continue
            insn_len = 1 + MODE_OPERAND_BYTES[mode]
            lengths[opcode] = insn_len

    # Pack into 64 bytes: 4 opcodes per byte
    # Bit layout: [p3:p2:p1:p0] where p0 = bits 1:0
    packed = []
    for i in range(0, 256, 4):
        b = 0
        for j in range(4):
            b |= (lengths[i + j] & 3) << (j * 2)
        packed.append(b)

    assert len(packed) == 64

    # Write the .s file
    path = pathlib.Path(__file__).parent / '../src/oplen_tbl.s'
    lines = [
        '; oplen_tbl.s — packed opcode→instruction length table',
        '; Generated by dev/mnemonic_tables.py — DO NOT EDIT BY HAND',
        ';',
        '; 64 bytes: 256 opcodes × 2 bits.  4 entries per byte.',
        '; Packing: byte = opcode >> 2.  Position = opcode & 3.',
        ';   pos 0 = bits 1:0, pos 1 = bits 3:2,',
        ';   pos 2 = bits 5:4, pos 3 = bits 7:6.',
        '; Values: 1 = 1 byte, 2 = 2 bytes, 3 = 3 bytes.',
        '; Safe for all CPU modes (65C02 superset).',
        '',
        '        .export oplen_tbl',
        '',
        '.segment "RODATA"',
        '',
        'oplen_tbl:',
    ]

    for row in range(8):
        vals = packed[row * 8:(row + 1) * 8]
        hex_str = ','.join(f'${v:02X}' for v in vals)
        start_opc = row * 32
        lines.append(f'        .byte {hex_str}  ; ${start_opc:02X}-${start_opc+31:02X}')

    lines.append('')

    path.write_text('\n'.join(lines) + '\n')
    print(f'wrote {path}  (64 bytes, 256 opcodes packed)')


# ============================================================
# Entry point
# ============================================================

if __name__ == '__main__':
    print_summary()
    print_by_category()
    verify_opcodes()
    verify_base_opcodes()
    write_mode_table()
    mn6.verify()
    mn6.verify_fingerprint()
    write_config_table_6bit()
    mn7.verify()
    mn7.verify_fingerprint()
    write_config_table_7bit()
    write_asm_tables()
    write_oplen_table()
