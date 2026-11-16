#!/usr/bin/env python3
"""
dev/mnemonic_tables.py

Assembler config table generator for the CSE 6502/65C02 assembler, shared
unchanged with bbbc64 (doc/asm.md § Instruction set); file references below
are CSE's.
Imports all instruction-set definitions from dev/instruction_set.py.
Uses mn6 (6-bit hash, 56 legal NMOS mnemonics) and mn7 (7-bit hash, all 114
mnemonics) from dev/hashes.py.

Generates:
    src/mn_modes.s      – operand profile addressing-mode bitfield table (60 bytes)
    src/mn7_tables.s    – per-mnemonic tables, mn7 7-bit hash (3×128 = 384 bytes)
    src/mn6_tables.s    – per-mnemonic tables, mn6 6-bit hash (3×64  = 192 bytes)
    src/mn_asm_tables.s – mode_offset (64 B) + direct_opcodes (16 B)
    src/oplen_tbl.s     – packed opcode→length table (64 bytes)

    python3 dev/mnemonic_tables.py [--syntax ca65|acme] [--out DIR]

With no --out the tables go to CSE's src/, and only in a tree that is CSE's
(its src/ holds mn6.s); anywhere else --out is required.
"""
import argparse
import functools
import operator
import pathlib
import sys

from instruction_set import (
    ALL_MODES, OPERAND_PROFILES, MNEMONICS, OPCODES,
    _N_OPERAND_PROFILES, _CMOS_PAIRS, _BIT_OPERAND, _BASE_OPCODE_OVERRIDES,
    mne_modes, sc, MODE_OPERAND_BYTES,
)
from hashes import mn6, mn7

ROOT   = pathlib.Path(__file__).resolve().parent.parent
SYNTAX = 'ca65'   # --syntax
OUT    = None     # --out; None = CSE's src/


def _out(name):
    """Output path for a generated table: --out, else CSE's src/ in a CSE tree."""
    global OUT
    if OUT is None:
        if not (ROOT / 'src' / 'mn6.s').exists():
            sys.exit(f"mnemonic_tables.py: {ROOT} is not a CSE tree (no src/mn6.s); pass --out DIR")
        OUT = ROOT / 'src'
    return OUT / name


def _byte():
    return '.byte' if SYNTAX == 'ca65' else '!byte'


def _ca65_only(line):
    """A ca65 directive line (.export, .segment): ACME has no counterpart."""
    return [line] if SYNTAX == 'ca65' else []

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

# ============================================================
# Profile-row model, one per CPU set
#   doc/modules/opcode_lookup.md § Design, doc/modules/mn_classify.md,
#   doc/build_system.md § Builds and CPU sets and § Table generation
# ============================================================

import instruction_set as _I                       # noqa: E402
from dataclasses import dataclass, field           # noqa: E402

# CPU set → (block define, its CPU views low to high, classifier).
CPU_SETS = {
    '6502':  ('CPU_6502',  ('6502',),                 'mn6'),
    '6510':  ('CPU_6510',  ('6502', '6510'),          'mn7'),
    '65c02': ('CPU_65C02', ('6502', '6510', '65c02'), 'mn7'),
}

# The fixed single-shape zones A–F, at pidx 0–5 on the C64 CPU sets.
FIXED_ZONES = 'ABCDEF'
_CAT_SRC = {0: '6502', 1: '6502', 2: '6510', 3: '65c02'}   # cat → view of its NMOS profile


class ModelError(AssertionError):
    pass


@dataclass(frozen=True)
class Profile:
    modes: frozenset          # catalogue mode names the profile accepts
    deltas: tuple             # sorted (mode, opcode ^ base)

    def delta(self, mode):
        return dict(self.deltas)[mode]


EMPTY_PROFILE = Profile(frozenset(), ())


@dataclass
class AsmModel:
    cpu_set: str
    define: str
    classifier: str
    n_modes: int
    profiles: list            # pidx → Profile
    zone_first: dict          # zone letter → first pidx
    row_of: list              # pidx → delta row
    rows: list                # row → [delta per mode index]
    key_base: dict            # key → base opcode
    key_prof: dict            # key → packed profile byte (cat << 6 | pidx)
    key_ext: dict = field(default_factory=dict)   # key → extension pidx (cat 01, CMOS sets)

    def mask(self, pidx):
        bits = 0
        for m in self.profiles[pidx].modes:
            bits |= 1 << ALL_MODES.index(m)
        return bits


def _view_rows(variant):
    """key → {mode: opcode} of one CPU view; a digit key by its digit-0 row."""
    out = {}
    for r in _I.instructions(variant):
        if r.prefix:
            continue
        if r.key in _I.BIT_DIGIT_MNEMONICS and r.suffix != '0':
            continue
        out.setdefault(r.key, {})[r.mode] = r.opcode
    return out


def _base_of(opcodes):
    """The key's own zero-page opcode, else its absolute one, else its lowest mode's."""
    if 'ZP' in opcodes:
        return opcodes['ZP']
    if 'ABS' in opcodes:
        return opcodes['ABS']
    return opcodes[min(opcodes, key=ALL_MODES.index)]


def _profile(opcodes, base):
    return Profile(frozenset(opcodes),
                   tuple(sorted((m, op ^ base) for m, op in opcodes.items())))


def _fixed_zone(key, prof):
    modes = prof.modes
    if key in _I.BIT_DIGIT_MNEMONICS:
        return 'D' if modes == {'ZP'} else 'E'
    return {frozenset({'IMP'}): 'A', frozenset({'REL'}): 'B',
            frozenset({'IMM'}): 'C', frozenset({'ABS'}): 'F'}.get(modes)


def _conflicts(profiles):
    n = len(profiles)
    return [[any(profiles[a].delta(m) != profiles[b].delta(m)
                 for m in profiles[a].modes & profiles[b].modes)
             for b in range(n)] for a in range(n)]


def _colour(profiles):
    """Exact minimum colouring of the profile conflict graph (backtracking)."""
    conf = _conflicts(profiles)
    n = len(profiles)
    order = sorted(range(n), key=lambda i: -sum(conf[i]))
    best = {'k': n + 1, 'colours': [0] * n}

    def bt(idx, colours, k):
        if k >= best['k']:
            return
        if idx == n:
            best['k'], best['colours'] = k, list(colours)
            return
        v = order[idx]
        used = {colours[u] for u in range(n) if colours[u] is not None and conf[v][u]}
        for c in range(k):
            if c not in used:
                colours[v] = c
                bt(idx + 1, colours, k)
                colours[v] = None
        colours[v] = k
        bt(idx + 1, colours, k + 1)
        colours[v] = None
    bt(0, [None] * n, 0)
    return best['colours'], max(best['k'], 1)


def classifier_keys(classifier):
    if classifier == 'mn6':
        return [m for m, (_, _, cat) in MNEMONICS.items() if cat == 'legal']
    return list(MNEMONICS)


def build_asm_model(cpu_set):
    """The profile-row tables of one CPU set, from instruction_set.py."""
    define, views, classifier = CPU_SETS[cpu_set]
    n_modes = 16
    rows = {v: _view_rows(v) for v in views}
    has_ext = '65c02' in views

    entries = {}                      # key → (cat, nmos Profile, ext Profile | None, base)
    for key in classifier_keys(classifier):
        cat = _compute_cat(key)
        src = _CAT_SRC[cat]
        if src not in rows or key not in rows[src]:
            entries[key] = (cat, None, None, 0)
            continue
        ops = rows[src][key]
        base = _base_of(ops)
        ext = None
        if cat == 1 and has_ext:
            ext = _profile(rows['65c02'][key], base)
        entries[key] = (cat, _profile(ops, base), ext, base)

    profiles = []
    index = {}

    def place(p):
        profiles.append(p)
        index.setdefault(p, len(profiles) - 1)
        return len(profiles) - 1

    # Zones A–F: exactly one profile each, at pidx 0–5.
    fixed = {z: set() for z in FIXED_ZONES}
    for key, (cat, p, e, _) in entries.items():
        if p is not None and e is None:
            z = _fixed_zone(key, p)
            if z:
                fixed[z].add(p)
    zone_first = {}
    for z in FIXED_ZONES:
        if len(fixed[z]) > 1:
            raise ModelError(f"{cpu_set}: zone {z} holds {len(fixed[z])} profiles")
        zone_first[z] = len(profiles)
        place(next(iter(fixed[z])) if fixed[z] else EMPTY_PROFILE)

    # Zone G: extension pairs (NMOS, extension), adjacent.
    zone_first['G'] = len(profiles)
    pair_at = {}
    for key, (cat, p, e, _) in entries.items():
        if e is None:
            continue
        if _fixed_zone(key, p) or _fixed_zone(key, e):
            raise ModelError(f"{cpu_set}: pair of {key} leaves the multi-mode zones")
        if (p, e) not in pair_at:
            pair_at[(p, e)] = len(profiles)
            profiles.append(p)
            profiles.append(e)

    # Zone H: every other profile, shared by identity with any already placed.
    zone_first['H'] = len(profiles)
    pidx_of = {}
    for key, (cat, p, e, _) in entries.items():
        if p is None:
            pidx_of[key] = 0
        elif e is not None:
            pidx_of[key] = pair_at[(p, e)]
        elif _fixed_zone(key, p):
            pidx_of[key] = zone_first[_fixed_zone(key, p)]
        else:
            pidx_of[key] = index[p] if p in index else place(p)
    if len(profiles) > 64:
        raise ModelError(f"{cpu_set}: {len(profiles)} profiles exceed the 6-bit pidx")

    colours, n_rows = _colour(profiles)
    if n_rows * n_modes > 256:
        raise ModelError(f"{cpu_set}: {n_rows} delta rows overflow the row offset byte")
    delta_rows = [[0] * n_modes for _ in range(n_rows)]
    for pidx, prof in enumerate(profiles):
        for m, d in prof.deltas:
            delta_rows[colours[pidx]][ALL_MODES.index(m)] = d

    model = AsmModel(
        cpu_set=cpu_set, define=define, classifier=classifier, n_modes=n_modes,
        profiles=profiles, zone_first=zone_first, row_of=colours, rows=delta_rows,
        key_base={k: e[3] for k, e in entries.items()},
        key_prof={k: (entries[k][0] << 6) | pidx_of[k] for k in entries},
        key_ext={k: pair_at[(e[1], e[2])] + 1 for k, e in entries.items() if e[2] is not None},
    )
    validate_asm_model(model)
    return model


def model_opcode(model, key, mode, extended=False, digit=0):
    """The opcode the tables produce for (key, mode), or None if masked out."""
    pidx = model.key_ext[key] if extended else model.key_prof[key] & 0x3F
    if not (model.mask(pidx) >> ALL_MODES.index(mode)) & 1:
        return None
    delta = model.rows[model.row_of[pidx]][ALL_MODES.index(mode)]
    return (model.key_base[key] ^ delta) | (digit << 4)


def validate_asm_model(model):
    """Derive-or-die: the tables reproduce every row of every view of the CPU
    set, and mask out every (key, mode) that is no row."""
    _, views, _ = CPU_SETS[model.cpu_set]
    errors = []
    for prof_a, prof_b in ((a, b) for a in range(len(model.profiles))
                           for b in range(len(model.profiles))
                           if model.row_of[a] == model.row_of[b]):
        pa, pb = model.profiles[prof_a], model.profiles[prof_b]
        for m in pa.modes & pb.modes:
            if pa.delta(m) != pb.delta(m):
                errors.append(f"row {model.row_of[prof_a]}: pidx {prof_a}/{prof_b} disagree on {m}")
    for z, n in zip(FIXED_ZONES, range(6)):
        if model.zone_first[z] != n:
            errors.append(f"zone {z} not at pidx {n}")
    for key, prof in model.key_prof.items():
        cat = prof >> 6
        view = _CAT_SRC[cat]
        if view not in views:
            continue
        for v, ext in ((view, False), ('65c02', True)):
            if ext and key not in model.key_ext:
                continue
            want = {}
            for r in _I.instructions(v):
                if r.key == key and not r.prefix:
                    want.setdefault(r.mode, set()).add((r.opcode, int(r.suffix or 0)))
            for mode in ALL_MODES[:model.n_modes]:
                if mode not in want:
                    if model_opcode(model, key, mode, ext) is not None:
                        errors.append(f"{model.cpu_set} {key} {mode}: masked in but no row in {v}")
                    continue
                for opcode, digit in want[mode]:
                    got = model_opcode(model, key, mode, ext, digit)
                    if got != opcode:
                        errors.append(f"{model.cpu_set} {key} {mode} d{digit}: "
                                      f"tables give {got}, {v} has ${opcode:02X}")
    if errors:
        raise ModelError("asm model invalid:\n  " + "\n  ".join(errors[:30]))


# ============================================================
# Table writers — one block per CPU set
# ============================================================

def _block_lines(models, emit):
    lines = []
    for m in models:
        lines += [f'.ifdef {m.define}' if SYNTAX == 'ca65' else f'!ifdef {m.define} {{',
                  f'; ── CPU set {m.cpu_set} ' + '─' * 40]
        lines += emit(m)
        lines += ['.endif' if SYNTAX == 'ca65' else '}', '']
    return lines


def _byte_rows(label, data, per=8, names=None):
    out = [f'{label}:']
    for i in range(0, len(data), per):
        chunk = data[i:i + per]
        hexs = ','.join(f'${v:02X}' for v in chunk)
        note = ('  ; ' + ' '.join(names[i:i + per])) if names else ''
        out.append(f'        {_byte()}   {hexs}{note}')
    return out


def _header(name, what):
    return [f'; {name}',
            '; Generated by dev/mnemonic_tables.py – DO NOT EDIT BY HAND',
            ';', *[f'; {w}' for w in what], ';',
            '; One block per CPU set, selected by the build\'s CPU_<top> define',
            '; (doc/build_system.md § Table generation).', '']


def asm_models():
    return [build_asm_model(c) for c in CPU_SETS]


def write_mode_table(models, out_path=None):
    """src/mn_modes.s — profile validity masks, one plane per 8 modes."""
    path = pathlib.Path(out_path or _out('mn_modes.s'))

    def emit(m):
        n = len(m.profiles)
        lo = [m.mask(p) & 0xFF for p in range(n)]
        hi = [(m.mask(p) >> 8) & 0xFF for p in range(n)]
        return (_byte_rows('mn_modes_lo', lo) + _byte_rows('mn_modes_hi', hi))

    lines = _header('mn_modes.s', [
        'Profile validity masks (doc/modules/opcode_lookup.md § Design), indexed by pidx.',
        f'  mn_modes_lo bits 0-7: {" ".join(ALL_MODES[0:8])}',
        f'  mn_modes_hi bits 0-7: {" ".join(ALL_MODES[8:16])}'])
    lines += [*_ca65_only('        .export mn_modes_lo, mn_modes_hi'), '',
              *_ca65_only('.segment "KDATA"'), '']
    lines += _block_lines(models, emit)
    path.write_text('\n'.join(lines) + '\n')
    print(f"wrote {path.resolve()}  ({', '.join(f'{m.cpu_set}: {2 * len(m.profiles)} B' for m in models)})")


def write_asm_tables(models, out_path=None):
    """src/mn_asm_tables.s — asm_row, asm_delta, asm_oplen and the zone constants."""
    path = pathlib.Path(out_path or _out('mn_asm_tables.s'))

    def emit(m):
        out = []
        for z in FIXED_ZONES + 'GH':
            out.append(f'ASM_ZONE_{z} = {m.zone_first[z]}')
        out.append(f'ASM_N_MODES = {m.n_modes}')
        out += _byte_rows('asm_row', [r * m.n_modes for r in m.row_of])
        flat = [d for row in m.rows for d in row]
        out += _byte_rows('asm_delta', flat, per=16)
        out += _byte_rows('asm_oplen', [MODE_OPERAND_BYTES[x] for x in ALL_MODES[:m.n_modes]],
                          per=16)
        return out

    lines = _header('mn_asm_tables.s', [
        'Profile-row opcode tables (doc/modules/opcode_lookup.md § Design):',
        '  opcode  = base ^ asm_delta[asm_row[pidx] + mode]',
        '  asm_row = the profile\'s delta-row byte offset; asm_oplen = operand bytes per mode'])
    lines += [*_ca65_only('        .export asm_row, asm_delta, asm_oplen'),
              *_ca65_only('        .export ASM_ZONE_A, ASM_ZONE_B, ASM_ZONE_C, ASM_ZONE_D'),
              *_ca65_only('        .export ASM_ZONE_E, ASM_ZONE_F, ASM_ZONE_G, ASM_ZONE_H, ASM_N_MODES'),
              '', *_ca65_only('.segment "KDATA"'), '']
    lines += _block_lines(models, emit)
    path.write_text('\n'.join(lines) + '\n')
    print(f"wrote {path.resolve()}  ({', '.join(f'{m.cpu_set}: {len(m.rows)} rows' for m in models)})")


def _write_classifier(cls, prefix, nslots, models, out_path, extra_rodata=()):
    path = pathlib.Path(out_path)
    slot_mne = cls.build_slot_map()
    fp = cls.fingerprint_table()

    def emit(m):
        base = [0] * nslots
        prof = [0] * nslots
        for h, mne in slot_mne.items():
            base[h] = m.key_base[mne]
            prof[h] = m.key_prof[mne]
        names = [f'{slot_mne.get(i, "---"):<3}' for i in range(nslots)]
        out = ['.segment "RODATA"' if SYNTAX == 'ca65' else '',
               *_byte_rows(f'{prefix}_hash_t', list(cls.T), per=9),
               *[ln for lab, data in extra_rodata for ln in _byte_rows(lab, data, per=9)],
               '.segment "KDATA"' if SYNTAX == 'ca65' else '']
        out += _byte_rows(f'{prefix}_fp', fp, names=names)
        out += _byte_rows(f'{prefix}_base_op', base, names=names)
        out += _byte_rows(f'{prefix}_profile', prof, names=names)
        return out

    exports = [f'{prefix}_hash_t', f'{prefix}_fp', f'{prefix}_base_op', f'{prefix}_profile']
    exports += [lab for lab, _ in extra_rodata]
    lines = _header(path.name, [
        f'{prefix} classifier tables: hash T, fingerprint, base opcode, profile byte',
        '  profile byte = cat (bits 7:6) | pidx (bits 5:0)  (doc/modules/mn_classify.md)'])
    lines += [*_ca65_only('        .export ' + ', '.join(exports)), '']
    lines += _block_lines([m for m in models if m.classifier == prefix], emit)
    path.write_text('\n'.join(lines) + '\n')
    print(f"wrote {path.resolve()}  ({len(slot_mne)}/{nslots} slots)")


def write_config_table_7bit(models, out_path=None):
    _write_classifier(mn7, 'mn7', 128, models, out_path or _out('mn7_tables.s'))


def write_config_table_6bit(models, out_path=None):
    fp_c2 = [(i * 218) & 0xFF for i in range(27)]
    _write_classifier(mn6, 'mn6', 64, models, out_path or _out('mn6_tables.s'),
                      extra_rodata=(('mn6_fp_c2', fp_c2),))


# ============================================================
# Opcode → instruction length table (packed, 2 bits per opcode)
# ============================================================

def write_oplen_table(models=None):
    """Generate src/oplen_tbl.s — packed opcode→length table, one block per CPU set.

    64 bytes per block: 256 opcodes × 2 bits each, 4 per byte.
    Packing: byte[opc>>2], bits (opc&3)*2.  Position 0 in bits 1:0,
    position 1 in bits 3:2, position 2 in bits 5:4, position 3 in bits 7:6.
    The length counts the opcode and its operand, never a prefix.

    The C64 blocks share one content: every OPCODES row's length (last row
    wins where a 6510 and a 65C02 opcode coincide).  The debugger steps every
    C64 build with it; a JAM opcode, the only one where the lengths matter,
    halts the CPU anyway.
    """
    lengths = [1] * 256  # default: 1 byte (implied/undefined)
    for mne, modes in OPCODES.items():
        for mode, opcode in modes.items():
            if opcode is None:
                continue
            lengths[opcode] = 1 + MODE_OPERAND_BYTES[mode]

    packed = []
    for i in range(0, 256, 4):
        b = 0
        for j in range(4):
            b |= (lengths[i + j] & 3) << (j * 2)
        packed.append(b)
    assert len(packed) == 64

    def emit(m):
        out = ['oplen_tbl:']
        for row in range(8):
            vals = packed[row * 8:(row + 1) * 8]
            hex_str = ','.join(f'${v:02X}' for v in vals)
            out.append(f'        {_byte()} {hex_str}  ; ${row * 32:02X}-${row * 32 + 31:02X}')
        return out

    path = _out('oplen_tbl.s')
    lines = _header('oplen_tbl.s', [
        'Packed opcode → instruction length (prefixes not counted), 64 bytes per block.',
        'Packing: byte = opcode >> 2; position = opcode & 3 (pos 0 = bits 1:0 … pos 3 = bits 7:6).',
        'Values: 1, 2 or 3 bytes.'])
    lines += [*_ca65_only('        .export oplen_tbl'), '', *_ca65_only('.segment "RODATA"'), '']
    lines += _block_lines(models or asm_models(), emit)
    path.write_text('\n'.join(lines) + '\n')
    print(f'wrote {path}  (64 bytes per CPU set)')


# ============================================================
# Entry point
# ============================================================

if __name__ == '__main__':
    _ap = argparse.ArgumentParser(description='Generate the assembler tables from dev/instruction_set.py.')
    _ap.add_argument('--syntax', choices=('ca65', 'acme'), default='ca65')
    _ap.add_argument('--out', type=pathlib.Path, help="output directory (default: CSE's src/)")
    _args = _ap.parse_args()
    SYNTAX = _args.syntax
    if _args.out is not None:
        OUT = _args.out
        OUT.mkdir(parents=True, exist_ok=True)
    _out('mn_modes.s')                    # refuse outside a CSE tree before any work
    print_summary()
    print_by_category()
    verify_opcodes()
    _models = asm_models()
    write_mode_table(_models)
    mn6.verify()
    mn6.verify_fingerprint()
    write_config_table_6bit(_models)
    mn7.verify()
    mn7.verify_fingerprint()
    write_config_table_7bit(_models)
    write_asm_tables(_models)
    write_oplen_table(_models)
