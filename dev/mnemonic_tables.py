#!/usr/bin/env python3
"""
dev/mnemonic_tables.py — the assembler's generated tables.
Owner: doc/build_system.md

Every opcode fact the assembler and the debugger use comes from
dev/instruction_set.py through this file; no source file restates one.
The tables come in one block per CPU set, selected at assembly time by
the build's CPU_<top> define (doc/build_system.md § Table generation).

Generates into src/:
    mn_modes.s      – profile validity masks (2 planes × profiles; 3 on m65)
    mn_asm_tables.s – asm_row, asm_delta, asm_oplen, the zone bounds
    mn6_tables.s    – mn6 classifier: hash T, fp_c2, fp / base_op / profile
    mn7_tables.s    – mn7 classifier: hash T, fp / base_op / profile (and on
                      m65 the mn7gs keys and mn7_c02)
    oplen_tbl.s     – packed opcode → length (one content for the C64 sets,
                      one for m65)

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
ASM_CPU = {'6502': 0, '6510': 1, '65c02': 2, '4510': 3, '45gs02': 4}


def search_T(keys, c1=4, c3=1, bits=7):
    """A collision-free T for `keys` by displacement search — a function of
    the key set alone (sorted inside): the middle letters with the most keys
    first, each T[c2] the smallest value that puts that letter's keys into
    distinct free slots.  T[0] = $FF (c2 is never 0); a letter with no keys
    keeps 0.  (bbbc64's dev/asm_tables.py, the same search.)"""
    from hashes import sc
    keys = sorted(set(keys))
    mask = (1 << bits) - 1
    groups = {}
    for k in keys:
        groups.setdefault(sc(k[1]), []).append(k)
    T = [0xFF] + [0] * 26
    used = set()
    for c2 in sorted(groups, key=lambda c: (-len(groups[c]), c)):
        for t in range(mask + 1):
            slots = {(sc(k[0]) * c1 + sc(k[2]) * c3 + t) & mask for k in groups[c2]}
            if len(slots) == len(groups[c2]) and not (slots & used):
                T[c2] = t
                used |= slots
                break
        else:
            raise ModelError(f"search_T: no displacement for middle letter {c2}")
    return T


class mn7gs(mn7):
    """mn7's form over the m65 key set — the 45GS02's keys, which hold the
    6502's, the 65C02's and the 4510's, and no 6510 one (mn_classify.md
    § Variants).  T is pinned; search_T over the sorted keys reproduces it
    (bbbc64 pins the same)."""
    KEYS = frozenset(r.key for r in I.instructions('45gs02'))
    T = [
        0xFF, 0x1A, 0x18, 0x02, 0x0A, 0x00, 0x00, 0x00,  # @ A B C D E F G
        0x27, 0x12, 0x00, 0x00, 0x0B, 0x24, 0x08, 0x57,  # H I J K L M N O
        0x00, 0x00, 0x7C, 0x08, 0x10, 0x00, 0x21, 0x00,  # P Q R S T U V W
        0x07, 0x28, 0x05,                                  # X Y Z
    ]

    @classmethod
    def build_slot_map(cls):
        out = {}
        for k in sorted(cls.KEYS):
            h = cls.hash(k)
            if h in out:
                raise ValueError(f"mn7gs collision: {k!r} and {out[h]!r} both map to slot {h}")
            out[h] = k
        return out

    @classmethod
    def verify(cls):
        slot_mne = cls.build_slot_map()
        assert len(slot_mne) == len(cls.KEYS)
        assert cls.T == search_T(cls.KEYS), "mn7gs: the pinned T is not search_T's"
        return slot_mne


# CPU set → (block define, its CPU views low to high, classifier class).
# The set's name is its top CPU; test bundles and golden files use it too.
CPU_SETS = {
    '6502':  ('CPU_6502',  ('6502',),                 mn6),
    '6510':  ('CPU_6510',  ('6502', '6510'),          mn7),
    '65c02': ('CPU_65C02', ('6502', '6510', '65c02'), mn7),
    '45gs02': ('CPU_45GS02', ('6502', '65c02', '4510', '45gs02'), mn7gs),
}
M65_SETS = frozenset({'45gs02'})      # the m65 platform's (D-P4-10)

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


# The modes asm_line refuses at asm_cpu 2 on m65 although the profile it
# uses there (the 4510's extension) has them: the 65C02 lacks them.
# (`(e)` there is the eight (zp) opcodes, the 4510's ZPIZ.)
C02_REFUSED = frozenset({'ISPY', 'REL16', 'ZPIZ'})


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
    q: Profile = None         # m65: the Q profile of a quad stem
    c02: bool = False         # m65: the 65C02 has the key (cat 3) or its extension (cat 1)


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
    zones: dict = None        # m65: zone letter → first pidx (B F D Q H)
    key_c02: dict = None      # m65: key → mn7_c02 bit

    def mask(self, pidx):
        return sum(1 << ALL_MODES.index(m) for m in self.profiles[pidx].modes)

    def effective_pidx(self, key, view):
        """The profile asm_line uses for `key` under CPU `view` (its gate's
        upgrade: + 1 for a category-1 key on the extension CPU — on m65 the
        4510, and the 65C02 where mn7_c02 says so); None where the gate
        refuses the key."""
        prof = self.key_prof[key]
        cat, pidx = prof >> 6, prof & 0x3F
        if self.cpu_set not in M65_SETS:
            return pidx + (1 if cat == 1 and view == EXT_VIEW else 0)
        c02 = self.key_c02[key]
        if view == '6502':
            return pidx if cat < 2 else None
        if view == '65c02':
            if cat == 2 or (cat == 3 and not c02):
                return None
            return pidx + (1 if cat == 1 and c02 else 0)
        if cat == 2 and view != '45gs02':
            return None
        return pidx + (1 if cat == 1 else 0)


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


def q_rows():
    """quad stem → {mode: opcode} of its Q forms (the `$42 $42` rows of the
    45GS02 view, far ones aside); a Q name's rows are its stem's too."""
    out = {}
    for r in I.instructions('45gs02'):
        if r.prefix == I.PREFIX_Q:
            out.setdefault(I.Q_NAMES.get(r.key, r.key), {})[r.mode] = r.opcode
    return out


def m65_entries():
    """key → Entry for the m65 set (mn_classify.md § cat; D-P4-10).

    cat 0 legal NMOS, the same on the 4510; 1 legal NMOS with a 4510
    extension profile at pidx + 1; 2 a Q name (its pidx is its stem's Q
    profile); 3 not NMOS.  c02: the 65C02 has the key (cat 3) or the
    extension (cat 1).  A quad stem's Q profile follows its group.
    """
    rows = {v: view_rows(v) for v in ('6502', '65c02', '4510')}
    qrows = q_rows()
    entries = {}
    for key in sorted(mn7gs.KEYS):          # sorted: a frozenset's order varies per run
        if key in I.Q_NAMES:
            ops = qrows[I.Q_NAMES[key]]
            base = base_of(ops)
            entries[key] = Entry(2, base, _profile(ops, base))
            continue
        ops = rows['4510'][key]
        base = base_of(ops)
        prof = _profile(ops, base)
        nmos = rows['6502'].get(key)
        if nmos is not None:
            cat = 1 if nmos != ops else 0
            c02 = cat == 1 and rows['65c02'][key] != nmos
            ext = prof if cat == 1 else None
            prof = _profile(nmos, base)
        else:
            cat, c02, ext = 3, key in rows['65c02'], None
        if key in I.BIT_DIGIT_MNEMONICS:
            zone = 'D' if prof.modes == {'ZP'} else 'E'
        elif {'REL', 'REL16'} >= prof.modes:
            zone = 'B'                       # the branch zone: a range on m65
        else:
            zone = None if ext else _ZONE_OF_MODES.get(prof.modes)
        q = _profile(qrows[key], base) if key in qrows else None
        entries[key] = Entry(cat, base, prof, ext, zone, q, c02)
    return entries


def set_entries(cpu_set):
    """key → Entry for every key of the set's classifier."""
    if cpu_set in M65_SETS:
        return m65_entries()
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


# The m65 branch zone, in pidx order: a cat-1 branch's REL profile is
# followed by its extension (REL, REL16); BSR has REL16 alone.
_B_RANGE = (frozenset({'REL'}), frozenset({'REL', 'REL16'}), frozenset({'REL16'}))


def place_m65(entries):
    """Number the m65 profiles: (profiles, zones, key → pidx).

    Fixed zones A, B (a range), F, C, D, E; then G — the extension
    pairs (NMOS, extension) without a Q form; then Q — the quad stems'
    groups, (NMOS, extension, Q) or (plain, Q), adjacent, so the Q
    profile is the effective one + 1; then H, every other profile, shared
    by identity with H profiles only (a key never lands in zone Q, whose
    profiles admit the `q` suffix, unless it is a quad stem).
    """
    profiles, zones, pidx_of = [], {}, {}
    fixed = {}
    for key, e in entries.items():
        if e.zone and e.zone != 'B':
            if fixed.setdefault(e.zone, e.prof) != e.prof:
                raise ModelError(f"zone {e.zone} holds more than one profile ({key})")
    branch = {e.prof.modes for e in entries.values() if e.zone == 'B'} \
        | {e.ext.modes for e in entries.values() if e.zone == 'B' and e.ext}
    if not branch <= set(_B_RANGE):
        raise ModelError(f"zone B: unexpected branch profiles {branch}")
    b_prof = {}
    for e in entries.values():
        if e.zone == 'B':
            for p in (e.prof, e.ext):
                if p is not None:
                    b_prof[p.modes] = p
    profiles.append(fixed['A'])
    zones['B'] = len(profiles)
    for modes in _B_RANGE:
        profiles.append(b_prof[modes])
    for z in 'FCDE':
        zones[z] = len(profiles)
        profiles.append(fixed[z])
    zones['G'] = len(profiles)
    pair_at, group_at, h_at = {}, {}, {}
    for e in entries.values():                       # G: pairs without a Q form
        if e.ext and not e.q and e.zone != 'B' and (e.prof, e.ext) not in pair_at:
            pair_at[(e.prof, e.ext)] = len(profiles)
            profiles += [e.prof, e.ext]
    zones['Q'] = len(profiles)
    for key, e in entries.items():                   # Q: the quad groups
        if e.q and (e.prof, e.ext, e.q) not in group_at:
            group_at[(e.prof, e.ext, e.q)] = len(profiles)
            profiles += [p for p in (e.prof, e.ext, e.q) if p is not None]
    zones['H'] = len(profiles)
    for key, e in entries.items():
        if e.cat == 2:                               # a Q name: its stem's Q profile
            stem = entries[I.Q_NAMES[key]]
            g = group_at[(stem.prof, stem.ext, stem.q)]
            pidx_of[key] = g + (2 if stem.ext else 1)
            if profiles[pidx_of[key]] != e.prof:
                raise ModelError(f"{key}: not its stem's Q profile")
        elif e.zone == 'B':
            pidx_of[key] = zones['B'] + _B_RANGE.index(e.prof.modes)
        elif e.zone:
            pidx_of[key] = 0 if e.zone == 'A' else zones[e.zone]
        elif e.q:
            pidx_of[key] = group_at[(e.prof, e.ext, e.q)]
        elif e.ext:
            pidx_of[key] = pair_at[(e.prof, e.ext)]
        else:
            if e.prof not in h_at:
                h_at[e.prof] = len(profiles)
                profiles.append(e.prof)
            pidx_of[key] = h_at[e.prof]
    return profiles, zones, pidx_of


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
    zones = None
    if cpu_set in M65_SETS:
        profiles, zones, pidx_of = place_m65(entries)
        zone_g = zones['G']
    else:
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
        zones=zones,
        key_c02={k: e.c02 for k, e in entries.items()} if zones else None,
    )
    validate_asm_model(model)
    return model


def model_opcode(model, key, mode, view, digit=0, q=False):
    """The opcode the tables give (key, mode) under CPU `view`; None if masked
    out.  m65: `q` takes the Q profile (effective + 1, a Q name its own);
    on the 65C02 `(e)` (ZPI) is the 4510's ZPIZ and C02_REFUSED is out."""
    pidx = model.effective_pidx(key, view)
    if pidx is None:
        return None
    if model.cpu_set in M65_SETS:
        if q and model.key_prof[key] >> 6 != 2:
            if not model.zones['Q'] <= pidx < model.zones['H']:
                return None
            pidx += 1
        if view == '65c02':
            if mode in C02_REFUSED:
                return None
            if mode == 'ZPI' and (model.mask(pidx) >> ALL_MODES.index('ZPIZ')) & 1:
                mode = 'ZPIZ'
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
    if model.cpu_set in M65_SETS:
        errors += _validate_m65_prefixed(model)
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


def _validate_m65_prefixed(model):
    """The 45GS02's prefixed rows: a Q row is the key's Q profile (a stem's
    effective + 1, a Q name's own), a far row the same mode unprefixed —
    the prefix is emitted, never looked up."""
    errors = []
    for r in I.instructions('45gs02'):
        if not r.prefix:
            continue
        q = r.prefix.startswith(I.PREFIX_Q)
        got = model_opcode(model, r.key, r.mode, '45gs02', q=q)
        if got != r.opcode:
            errors.append(f"{r.mnemonic} {r.mode} (prefix {r.prefix.hex()}): "
                          f"tables give {got}, instruction set has ${r.opcode:02X}")
    return errors


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
        out = (_bytes('mn_modes_lo', [x & 0xFF for x in masks])
               + _bytes('mn_modes_hi', [(x >> 8) & 0xFF for x in masks]))
        if m.n_modes > 16:                  # m65: modes 16-19 in a third plane
            out = ['        .export mn_modes_x'] + out \
                + _bytes('mn_modes_x', [x >> 16 for x in masks])
        return out

    lines = _header('mn_modes.s', [
        'Profile validity masks (doc/modules/opcode_lookup.md § Design), indexed by pidx.',
        f'  mn_modes_lo bits 0-7: {" ".join(ALL_MODES[0:8])}',
        f'  mn_modes_hi bits 0-7: {" ".join(ALL_MODES[8:16])}',
        f'  mn_modes_x  bits 0-3: {" ".join(ALL_MODES[16:])} (m65 only)', *_PER_SET])
    lines += ['        .export mn_modes_lo, mn_modes_hi', '', '.segment "KDATA"', '']
    path = _write('mn_modes.s', lines + _blocks(models, emit))
    print(f"wrote {path}  ({', '.join(f'{m.cpu_set}: {len(m.profiles)} profiles' for m in models)})")


def write_asm_tables(models):
    """mn_asm_tables.s — asm_row, asm_delta, asm_oplen and ASM_ZONE_G."""
    def emit(m):
        if m.zones:                         # m65: the zone bounds asm_line needs
            digit = [f'ASM_ZONE_{z} = {m.zones[z]}' for z in 'BFDQH'] \
                + ['        .export ' + ', '.join(f'ASM_ZONE_{z}' for z in 'BFDQH')]
        else:
            zone_d = FIXED_ZONES.index('D')  # fixed zones are a prefix of FIXED_ZONES
            digit = ([f'ASM_ZONE_D = {zone_d}', '        .export ASM_ZONE_D']
                     if m.zone_g > zone_d else [])
        return ([f'ASM_ZONE_G = {m.zone_g}'] + digit
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
        '  ASM_ZONE_D = the digit zone D\'s pidx (E follows), where the set has it',
        '  m65 also: ASM_ZONE_B / _F (the branch range B..F-1), _Q, _H (the quad zone Q..H-1)',
        'Rows are as wide as the set\'s highest used mode index + 1.', *_PER_SET])
    lines += ['        .export asm_row, asm_delta, asm_oplen, ASM_ZONE_G', '',
              '.segment "KDATA"', '']
    path = _write('mn_asm_tables.s', lines + _blocks(models, emit))
    print(f"wrote {path}  ({', '.join(f'{m.cpu_set}: {len(m.rows)}×{m.n_modes}' for m in models)})")


def write_classifier_tables(cls, models, extra_rodata=()):
    """mn6_tables.s / mn7_tables.s — hash T, fingerprint, base opcode, profile
    byte; on m65 (mn7gs in mn7_tables.s) also mn7_c02, the 65C02 bitmap."""
    prefix = cls.__name__
    slot_mne = cls.build_slot_map()

    def emit(m):
        k = m.classifier                    # cls, or mn7gs in cls's file
        slots = k.build_slot_map()
        names = [f'{slots.get(i, "---"):<3}' for i in range(k.SLOTS)]
        base = [m.key_base.get(slots.get(i), 0) for i in range(k.SLOTS)]
        prof = [m.key_prof.get(slots.get(i), 0) for i in range(k.SLOTS)]
        out = ['.segment "RODATA"', *_bytes(f'{prefix}_hash_t', list(k.T), per=9)]
        for label, data in extra_rodata:
            out += _bytes(label, data, per=9)
        out += (['.segment "KDATA"']
                + _bytes(f'{prefix}_fp', k.fingerprint_table(), names=names)
                + _bytes(f'{prefix}_base_op', base, names=names)
                + _bytes(f'{prefix}_profile', prof, names=names))
        if m.key_c02 is not None:            # bit (slot & 7) of byte (slot >> 3)
            bm = [0] * (k.SLOTS // 8)
            for i, key in slots.items():
                if m.key_c02[key]:
                    bm[i >> 3] |= 1 << (i & 7)
            out += ['        .export mn7_c02'] + _bytes('mn7_c02', bm)
        return out

    exports = [f'{prefix}_hash_t', *[lab for lab, _ in extra_rodata],
               f'{prefix}_fp', f'{prefix}_base_op', f'{prefix}_profile']
    lines = _header(f'{prefix}_tables.s', [
        f'{prefix} classifier tables (doc/modules/mn_classify.md): hash T, fingerprint,',
        'base opcode, profile byte = cat (bits 7:6) | pidx (bits 5:0).', *_PER_SET])
    lines += ['        .export ' + ', '.join(exports), '']
    path = _write(f'{prefix}_tables.s',
                  lines + _blocks([m for m in models if issubclass(m.classifier, cls)], emit))
    print(f"wrote {path}  ({len(slot_mne)}/{cls.SLOTS} slots)")


# The 6510's crash opcodes: they halt the CPU, so their length never
# matters to the debugger's step and yields to any other row's.
_CRASH_MNEMONICS = frozenset({'CIM', 'HLT', 'JAM', 'KIL'})


def oplen_lengths(opcodes=None):
    """Opcode → instruction length (opcode + operand bytes), 256 entries.

    One content for all C64 CPU sets: every OPCODES row's length.  Where
    a 6510 and a 65C02 row share an opcode with different lengths, a
    crash row (JAM) yields to the other; any other length conflict is a
    ModelError — the table cannot serve both.
    """
    opcodes = OPCODES if opcodes is None else opcodes
    rows = {}                                   # opcode → {length: [mnemonics]}
    for mne, modes in opcodes.items():
        for mode, opcode in modes.items():
            if opcode is not None:
                rows.setdefault(opcode, {}).setdefault(
                    1 + MODE_OPERAND_BYTES[mode], []).append(mne)
    lengths, errors = [1] * 256, []
    for opcode, by_len in sorted(rows.items()):
        live = {n: m for n, m in by_len.items() if not set(m) <= _CRASH_MNEMONICS} or by_len
        if len(live) > 1:
            errors.append(f"${opcode:02X}: " + ", ".join(
                f"{'/'.join(sorted(m))} = {n} B" for n, m in sorted(live.items())))
        lengths[opcode] = max(live)
    if errors:
        raise ModelError("oplen_tbl: opcode length conflict:\n  " + "\n  ".join(errors))
    return lengths


def m65_oplen_lengths():
    """Opcode → length on the m65 set: the 4510's rows, every opcode defined
    once (no conflict); prefixes are the debugger's (debugger.md § Next-PC)."""
    lengths = [1] * 256
    for r in I.instructions('4510'):
        lengths[r.opcode] = 1 + MODE_OPERAND_BYTES[r.mode]
    return lengths


def write_oplen_table():
    """oplen_tbl.s — packed opcode → length, 2 bits per opcode, 64 bytes.

    Packing: byte[opc >> 2], bits (opc & 3) * 2; lengths from
    oplen_lengths() — one content for the C64 sets — and on m65 from
    m65_oplen_lengths().  The debugger's step reads it.
    """
    def pack(lengths):
        return [sum((lengths[i + j] & 3) << (j * 2) for j in range(4)) for i in range(0, 256, 4)]

    lines = _header('oplen_tbl.s', [
        'Packed opcode → instruction length, 64 bytes: 256 opcodes × 2 bits.',
        'byte = opcode >> 2; position = opcode & 3 (pos 0 = bits 1:0 … pos 3 = bits 7:6).',
        'One content for all C64 CPU sets, one for m65 (the 4510\'s lengths).'])
    lines += ['        .export oplen_tbl', '', '.segment "RODATA"', '']
    lines += ['.ifdef CPU_45GS02'] + _bytes('oplen_tbl', pack(m65_oplen_lengths())) + ['.else']
    lines += _bytes('oplen_tbl', pack(oplen_lengths())) + ['.endif']
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
    for cls in (mn6, mn7, mn7gs):
        cls.verify()
        cls.verify_fingerprint()
    models = asm_models()
    for m in models:
        print(f"CPU set {m.cpu_set}: {len(m.profiles)} profiles, "
              f"{len(m.rows)} delta rows × {m.n_modes} modes, "
              f"{(2 + (m.n_modes > 16) + 1) * len(m.profiles) + len(m.rows) * m.n_modes + m.n_modes} B")
    write_mode_table(models)
    write_asm_tables(models)
    write_classifier_tables(mn6, models, extra_rodata=(('mn6_fp_c2', [(i * 218) & 0xFF for i in range(27)]),))
    write_classifier_tables(mn7, models)
    write_oplen_table()


if __name__ == '__main__':
    sys.exit(main())
