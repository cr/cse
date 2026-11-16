#!/usr/bin/env python3
"""
dev/mnemonic_tables.py — the assembler's generated tables.
Owner: doc/build_system.md

Every opcode fact the assembler and the debugger use comes from
dev/instruction_set.py through this file; no source file restates one.
The tables come in one block per CPU set, selected at assembly time by
the build's CPU_<top> define (doc/build_system.md § Table generation).

Generates into src/:
    mn_modes.s      – profile validity masks (2 planes × profiles)
    mn_asm_tables.s – asm_row, asm_delta, asm_oplen, ASM_ZONE_G
    mn6_tables.s    – mn6 classifier: hash T, fp_c2, fp / base_op / profile
    mn7_tables.s    – mn7 classifier: hash T, fp / base_op / profile
    oplen_tbl.s     – packed opcode → length (one content for the C64 sets)

    python3 dev/mnemonic_tables.py [--out DIR]

The model is doc/modules/opcode_lookup.md § Design; the profile byte is
doc/modules/mn_classify.md.
"""
import argparse
import pathlib
import sys
from dataclasses import dataclass

import instruction_set as I
from instruction_set import ALL_MODES, MNEMONICS, OPCODES, MODE_OPERAND_BYTES, mne_modes
from hashes import mn6, mn7

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT  = None     # --out; None = src/


def _out(name):
    return (OUT or ROOT / 'src') / name


# ============================================================
# CPU sets (doc/build_system.md § Builds and CPU sets)
# ============================================================

# asm_cpu: the global enumeration of the CPUs.
ASM_CPU = {'6502': 0, '6510': 1, '65c02': 2}

# CPU set → (block define, its CPU views low to high, classifier class).
# The set's name is its top CPU; test bundles and golden files use it too.
CPU_SETS = {
    '6502':  ('CPU_6502',  ('6502',),                 mn6),
    '6510':  ('CPU_6510',  ('6502', '6510'),          mn7),
    '65c02': ('CPU_65C02', ('6502', '6510', '65c02'), mn7),
}

# The C64 platform's CPU ladder.  A key's category (profile byte bits 7:6)
# is a property of the key on the platform, the same in every CPU set:
#   0  legal NMOS, identical on the extension CPU
#   1  legal NMOS with more modes on the extension CPU (profile pair)
#   2  first defined by the 6510 (illegal)
#   3  first defined by the extension CPU
PLATFORM_VIEWS = ('6502', '6510', '65c02')
EXT_VIEW = '65c02'

# Fixed single-shape zones, in pidx order.  The order makes every C64 set's
# present zones a prefix (6502: A B F; 6510: A B F C; 65C02: all six), so no
# set carries an empty profile.  D and E are the bit-digit keys' zones.
FIXED_ZONES = 'ABFCDE'
_ZONE_OF_MODES = {frozenset({'IMP'}): 'A', frozenset({'REL'}): 'B',
                  frozenset({'ABS'}): 'F', frozenset({'IMM'}): 'C'}


class ModelError(AssertionError):
    pass


# ============================================================
# Sanity checks on the instruction-set data
# ============================================================

def verify_opcodes():
    """MNEMONICS' mode sets and OPCODES' keys agree (instructions() reads both)."""
    errors = []
    for mne, (profile, cmos_bit, _cat) in MNEMONICS.items():
        if mne not in OPCODES:
            errors.append(f"{mne}: missing from OPCODES")
            continue
        modes, op_modes = mne_modes(profile, cmos_bit), frozenset(OPCODES[mne])
        if op_modes != modes:
            errors.append(f"{mne}: OPCODES modes {sorted(op_modes)} != MNEMONICS modes {sorted(modes)}")
    if errors:
        raise ModelError("instruction set inconsistent:\n  " + "\n  ".join(errors))


# ============================================================
# Profile-row model, one per CPU set
# ============================================================

@dataclass(frozen=True)
class Profile:
    modes: frozenset          # catalogue mode names the profile accepts
    deltas: tuple             # sorted (mode, opcode ^ base)

    def delta(self, mode):
        return dict(self.deltas)[mode]


@dataclass
class Entry:
    """One classifier key in one CPU set."""
    cat: int
    base: int = 0
    prof: Profile = None      # None: the key has no row in this set
    ext: Profile = None       # extension profile (cat 1, sets with the extension CPU)
    zone: str = None          # fixed zone letter, or None for the multi-mode zones


@dataclass
class AsmModel:
    cpu_set: str
    define: str
    classifier: type
    n_modes: int              # delta-row width: highest used mode index + 1
    profiles: list            # pidx → Profile
    zone_g: int               # first multi-mode pidx
    row_of: list              # pidx → delta row
    rows: list                # row → [delta per mode index]
    key_base: dict            # key → base opcode
    key_prof: dict            # key → packed profile byte (cat << 6 | pidx)

    def mask(self, pidx):
        return sum(1 << ALL_MODES.index(m) for m in self.profiles[pidx].modes)

    def effective_pidx(self, key, view):
        """The profile asm_line uses for `key` under CPU `view` (its gate's
        upgrade: + 1 for a category-1 key on the extension CPU)."""
        prof = self.key_prof[key]
        return (prof & 0x3F) + (1 if prof >> 6 == 1 and view == EXT_VIEW else 0)


def view_rows(view):
    """key → {mode: opcode} of one CPU view; a digit key by its digit-0 row."""
    out = {}
    for r in I.instructions(view):
        if r.prefix or (r.key in I.BIT_DIGIT_MNEMONICS and r.suffix != '0'):
            continue
        out.setdefault(r.key, {})[r.mode] = r.opcode
    return out


def base_of(opcodes):
    """The key's own zero-page opcode, else its absolute one, else its lowest mode's."""
    for mode in ('ZP', 'ABS'):
        if mode in opcodes:
            return opcodes[mode]
    return opcodes[min(opcodes, key=ALL_MODES.index)]


def _profile(opcodes, base):
    return Profile(frozenset(opcodes),
                   tuple(sorted((m, op ^ base) for m, op in opcodes.items())))


def key_category(key, rows):
    """`rows`: view → view_rows(view) over PLATFORM_VIEWS."""
    if key in rows['6502']:
        return 1 if rows[EXT_VIEW][key] != rows['6502'][key] else 0
    return 2 if key in rows['6510'] else 3


def set_entries(cpu_set):
    """key → Entry for every key of the set's classifier."""
    _, views, classifier = CPU_SETS[cpu_set]
    rows = {v: view_rows(v) for v in PLATFORM_VIEWS}
    entries = {}
    for key in classifier.build_slot_map().values():
        cat = key_category(key, rows)
        home = ('6502', '6502', '6510', EXT_VIEW)[cat]
        if home not in views:
            entries[key] = Entry(cat)
            continue
        ops = rows[home][key]
        base = base_of(ops)
        prof = _profile(ops, base)
        ext = _profile(rows[EXT_VIEW][key], base) if cat == 1 and EXT_VIEW in views else None
        if key in I.BIT_DIGIT_MNEMONICS:
            zone = 'D' if prof.modes == {'ZP'} else 'E'
        else:
            zone = None if ext else _ZONE_OF_MODES.get(prof.modes)
        entries[key] = Entry(cat, base, prof, ext, zone)
    return entries


def place_profiles(entries):
    """Number the profiles: (profiles, zone_g, key → pidx).

    Fixed zones first, one profile each, in FIXED_ZONES order and only
    while present.  Then the multi-mode profiles — extension pairs adjacent
    (NMOS, extension), every other profile shared by identity with any
    multi-mode profile already placed, never with a fixed-zone one: a
    key's zone is how asm_line parses it, not only what it encodes.
    """
    fixed = {}
    for key, e in entries.items():
        if e.zone:
            if fixed.setdefault(e.zone, e.prof) != e.prof:
                raise ModelError(f"zone {e.zone} holds more than one profile ({key})")
    present = [z for z in FIXED_ZONES if z in fixed]
    if present != list(FIXED_ZONES[:len(present)]):
        raise ModelError(f"fixed zones {present} are not a prefix of {FIXED_ZONES}")
    profiles = [fixed[z] for z in present]
    zone_g = len(profiles)

    index = {}                               # multi-mode Profile → pidx
    pair_at = {}
    pidx_of = {}
    for key, e in entries.items():           # pairs first, so they stay adjacent
        if e.ext and (e.prof, e.ext) not in pair_at:
            pair_at[(e.prof, e.ext)] = len(profiles)
            for p in (e.prof, e.ext):
                index.setdefault(p, len(profiles))
                profiles.append(p)
    for key, e in entries.items():
        if e.prof is None:
            pidx_of[key] = 0                 # never used: the gate rejects the key
        elif e.zone:
            pidx_of[key] = present.index(e.zone)
        elif e.ext:
            pidx_of[key] = pair_at[(e.prof, e.ext)]
        else:
            if e.prof not in index:
                index[e.prof] = len(profiles)
                profiles.append(e.prof)
            pidx_of[key] = index[e.prof]
    return profiles, zone_g, pidx_of


def _conflicts(profiles):
    n = len(profiles)
    return [[any(profiles[a].delta(m) != profiles[b].delta(m)
                 for m in profiles[a].modes & profiles[b].modes)
             for b in range(n)] for a in range(n)]


def colour(profiles):
    """Exact minimum colouring of the profile conflict graph: (pidx → row, rows)."""
    conf = _conflicts(profiles)
    n = len(profiles)
    order = sorted(range(n), key=lambda i: -sum(conf[i]))
    best = {'k': n + 1, 'colours': None}

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
    return best['colours'], best['k']


def build_asm_model(cpu_set):
    """The profile-row tables of one CPU set, from instruction_set.py."""
    define, _views, classifier = CPU_SETS[cpu_set]
    entries = set_entries(cpu_set)
    profiles, zone_g, pidx_of = place_profiles(entries)
    if len(profiles) > 64:
        raise ModelError(f"{cpu_set}: {len(profiles)} profiles exceed the 6-bit pidx")

    n_modes = 1 + max(ALL_MODES.index(m) for p in profiles for m in p.modes)
    row_of, n_rows = colour(profiles)
    if n_rows * n_modes > 256:
        raise ModelError(f"{cpu_set}: {n_rows} delta rows overflow the row offset byte")
    rows = [[0] * n_modes for _ in range(n_rows)]
    for pidx, prof in enumerate(profiles):
        for m, d in prof.deltas:
            rows[row_of[pidx]][ALL_MODES.index(m)] = d

    model = AsmModel(
        cpu_set=cpu_set, define=define, classifier=classifier, n_modes=n_modes,
        profiles=profiles, zone_g=zone_g, row_of=row_of, rows=rows,
        key_base={k: e.base for k, e in entries.items()},
        key_prof={k: (e.cat << 6) | pidx_of[k] for k, e in entries.items()},
    )
    validate_asm_model(model)
    return model


def model_opcode(model, key, mode, view, digit=0):
    """The opcode the tables give (key, mode) under CPU `view`; None if masked out."""
    pidx = model.effective_pidx(key, view)
    m = ALL_MODES.index(mode)
    if not (model.mask(pidx) >> m) & 1:
        return None
    return (model.key_base[key] ^ model.rows[model.row_of[pidx]][m]) | (digit << 4)


def validate_asm_model(model):
    """Derive-or-die: for every key the gate admits under every view of the
    set, the tables reproduce each row and mask out every (key, mode) that
    is no row."""
    _, views, _ = CPU_SETS[model.cpu_set]
    errors = []
    for view in views:
        want = {}
        for r in I.instructions(view):
            if not r.prefix:
                want.setdefault(r.key, {}).setdefault(r.mode, []).append((r.opcode, int(r.suffix or 0)))
        for key in model.key_prof:
            rows = want.get(key, {})
            if not rows:
                continue                      # the gate rejects the key on this CPU
            for mode in ALL_MODES:
                if mode not in rows:
                    if model_opcode(model, key, mode, view) is not None:
                        errors.append(f"{key} {mode} on {view}: masked in, but no row")
                    continue
                for opcode, digit in rows[mode]:
                    got = model_opcode(model, key, mode, view, digit)
                    if got != opcode:
                        errors.append(f"{key} {mode} on {view}: tables give {got}, "
                                      f"instruction set has ${opcode:02X}")
    if errors:
        raise ModelError(f"asm model {model.cpu_set} invalid:\n  " + "\n  ".join(errors[:30]))


def asm_models():
    return [build_asm_model(c) for c in CPU_SETS]


# ============================================================
# Table writers
# ============================================================

def _blocks(models, emit):
    lines = []
    for m in models:
        lines += [f'.ifdef {m.define}', f'; ── CPU set {m.cpu_set} ' + '─' * 40,
                  *emit(m), '.endif', '']
    return lines


def _bytes(label, data, per=8, names=None):
    out = [f'{label}:']
    for i in range(0, len(data), per):
        hexs = ','.join(f'${v:02X}' for v in data[i:i + per])
        note = ('  ; ' + ' '.join(names[i:i + per])) if names else ''
        out.append(f'        .byte   {hexs}{note}')
    return out


def _header(name, what):
    return [f'; {name}',
            '; Generated by dev/mnemonic_tables.py – DO NOT EDIT BY HAND',
            ';', *[f'; {w}' for w in what], '']


_PER_SET = ['One block per CPU set, selected by the build\'s CPU_<top> define',
            '(doc/build_system.md § Table generation).']


def _write(name, lines):
    path = _out(name)
    path.write_text('\n'.join(lines) + '\n')
    return path


def write_mode_table(models):
    """mn_modes.s — profile validity masks, one plane per 8 modes."""
    def emit(m):
        masks = [m.mask(p) for p in range(len(m.profiles))]
        return (_bytes('mn_modes_lo', [x & 0xFF for x in masks])
                + _bytes('mn_modes_hi', [x >> 8 for x in masks]))

    lines = _header('mn_modes.s', [
        'Profile validity masks (doc/modules/opcode_lookup.md § Design), indexed by pidx.',
        f'  mn_modes_lo bits 0-7: {" ".join(ALL_MODES[0:8])}',
        f'  mn_modes_hi bits 0-7: {" ".join(ALL_MODES[8:16])}', *_PER_SET])
    lines += ['        .export mn_modes_lo, mn_modes_hi', '', '.segment "KDATA"', '']
    path = _write('mn_modes.s', lines + _blocks(models, emit))
    print(f"wrote {path}  ({', '.join(f'{m.cpu_set}: {len(m.profiles)} profiles' for m in models)})")


def write_asm_tables(models):
    """mn_asm_tables.s — asm_row, asm_delta, asm_oplen and ASM_ZONE_G."""
    def emit(m):
        return ([f'ASM_ZONE_G = {m.zone_g}']
                + _bytes('asm_row', [r * m.n_modes for r in m.row_of])
                + _bytes('asm_delta', [d for row in m.rows for d in row], per=m.n_modes)
                + _bytes('asm_oplen', [MODE_OPERAND_BYTES[x] for x in ALL_MODES[:m.n_modes]],
                         per=m.n_modes))

    lines = _header('mn_asm_tables.s', [
        'Profile-row opcode tables (doc/modules/opcode_lookup.md § Design):',
        '  opcode     = base ^ asm_delta[asm_row[pidx] + mode]',
        '  asm_row    = the profile\'s delta-row byte offset (row × row width)',
        '  asm_oplen  = operand bytes per mode',
        '  ASM_ZONE_G = first multi-mode pidx (lower ones are asm_line\'s fixed zones)',
        'Rows are as wide as the set\'s highest used mode index + 1.', *_PER_SET])
    lines += ['        .export asm_row, asm_delta, asm_oplen, ASM_ZONE_G', '',
              '.segment "KDATA"', '']
    path = _write('mn_asm_tables.s', lines + _blocks(models, emit))
    print(f"wrote {path}  ({', '.join(f'{m.cpu_set}: {len(m.rows)}×{m.n_modes}' for m in models)})")


def write_classifier_tables(cls, models, extra_rodata=()):
    """mn6_tables.s / mn7_tables.s — hash T, fingerprint, base opcode, profile byte."""
    prefix = cls.__name__
    slot_mne = cls.build_slot_map()
    names = [f'{slot_mne.get(i, "---"):<3}' for i in range(cls.SLOTS)]

    def emit(m):
        base = [m.key_base.get(slot_mne.get(i), 0) for i in range(cls.SLOTS)]
        prof = [m.key_prof.get(slot_mne.get(i), 0) for i in range(cls.SLOTS)]
        out = ['.segment "RODATA"', *_bytes(f'{prefix}_hash_t', list(cls.T), per=9)]
        for label, data in extra_rodata:
            out += _bytes(label, data, per=9)
        return (out + ['.segment "KDATA"']
                + _bytes(f'{prefix}_fp', cls.fingerprint_table(), names=names)
                + _bytes(f'{prefix}_base_op', base, names=names)
                + _bytes(f'{prefix}_profile', prof, names=names))

    exports = [f'{prefix}_hash_t', *[lab for lab, _ in extra_rodata],
               f'{prefix}_fp', f'{prefix}_base_op', f'{prefix}_profile']
    lines = _header(f'{prefix}_tables.s', [
        f'{prefix} classifier tables (doc/modules/mn_classify.md): hash T, fingerprint,',
        'base opcode, profile byte = cat (bits 7:6) | pidx (bits 5:0).', *_PER_SET])
    lines += ['        .export ' + ', '.join(exports), '']
    path = _write(f'{prefix}_tables.s',
                  lines + _blocks([m for m in models if m.classifier is cls], emit))
    print(f"wrote {path}  ({len(slot_mne)}/{cls.SLOTS} slots)")


def write_oplen_table():
    """oplen_tbl.s — packed opcode → length, 2 bits per opcode, 64 bytes.

    Packing: byte[opc >> 2], bits (opc & 3) * 2.  The length counts the
    opcode and its operand.  One content for all C64 CPU sets: every
    OPCODES row's length (last row wins where a 6510 and a 65C02 opcode
    coincide).  The debugger steps every C64 build with it; a JAM opcode,
    the only place the lengths differ in effect, halts the CPU anyway.
    """
    lengths = [1] * 256
    for modes in OPCODES.values():
        for mode, opcode in modes.items():
            if opcode is not None:
                lengths[opcode] = 1 + MODE_OPERAND_BYTES[mode]
    packed = [sum((lengths[i + j] & 3) << (j * 2) for j in range(4)) for i in range(0, 256, 4)]

    lines = _header('oplen_tbl.s', [
        'Packed opcode → instruction length, 64 bytes: 256 opcodes × 2 bits.',
        'byte = opcode >> 2; position = opcode & 3 (pos 0 = bits 1:0 … pos 3 = bits 7:6).',
        'One content for all C64 CPU sets.'])
    lines += ['        .export oplen_tbl', '', '.segment "RODATA"', '']
    lines += _bytes('oplen_tbl', packed)
    path = _write('oplen_tbl.s', lines)
    print(f'wrote {path}  (64 bytes)')


# ============================================================
# Entry point
# ============================================================

def main(argv=None):
    global OUT
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', type=pathlib.Path, help='output directory (default: src/)')
    args = ap.parse_args(argv)
    if args.out is not None:
        OUT = args.out
        OUT.mkdir(parents=True, exist_ok=True)

    verify_opcodes()
    for cls in (mn6, mn7):
        cls.verify()
        cls.verify_fingerprint()
    models = asm_models()
    for m in models:
        print(f"CPU set {m.cpu_set}: {len(m.profiles)} profiles, "
              f"{len(m.rows)} delta rows × {m.n_modes} modes, "
              f"{3 * len(m.profiles) + len(m.rows) * m.n_modes + m.n_modes} B")
    write_mode_table(models)
    write_asm_tables(models)
    write_classifier_tables(mn6, models, extra_rodata=(('mn6_fp_c2', [(i * 218) & 0xFF for i in range(27)]),))
    write_classifier_tables(mn7, models)
    write_oplen_table()


if __name__ == '__main__':
    sys.exit(main())
