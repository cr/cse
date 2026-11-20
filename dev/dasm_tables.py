#!/usr/bin/env python3
"""
dev/dasm_tables.py — the disassembler's generated tables.
Owner: doc/build_system.md

Every opcode fact dasm.s uses comes from dev/instruction_set.py through
this file (doc/modules/dasm.md § Design).  One block per CPU set,
selected by the set's CPU_<top> define; the CPU-set registry is
dev/mnemonic_tables.py's CPU_SETS.

Generates into src/:
    dasm_tables.s   – map blocks, per-asm_cpu view tables, subset bitmap,
                      mode lengths and formats, packed mnemonic strings
    dasm_mne_idx.s  – MNE_UNK and the decoration index ranges (.include'd
                      by dasm.s, so the decoder's code can test them)

    python3 dev/dasm_tables.py [--out DIR]
"""
import argparse
import pathlib
import sys
from dataclasses import dataclass

import instruction_set as I
import mnemonic_tables as MT

ROOT = pathlib.Path(__file__).resolve().parent.parent

# asm_cpu tables are padded to the highest asm_cpu any set of the platform
# holds (the C64 sets and the CMOS mode: the 65C02's 2; m65: the 45GS02's
# 4), so a value outside the build's CPU set reads the top CPU's view, never
# past the table.
def n_asm_cpu(cpu_set):
    return 5 if cpu_set in MT.M65_SETS else 3

# Listing-name order (dasm.md § Design, *Listing name*): where several rows
# name one opcode, the name whose key comes last here wins.
LISTING_ORDER = list(I.OPCODES) + list(I.OPCODES_4510_ADDED)
_RANK = {k: i for i, k in enumerate(LISTING_ORDER)}

# Operand-format byte (dasm.md § Design, *Mode formatting*).
_FMT_SPECIAL = {'IMP': 0x00, 'ACC': 0x60, 'REL': 0x70, 'ZPREL': 0x80, 'REL16': 0xA0}
_FMT_SUFFIX = {'': 0, ',X': 1, ',Y': 2, ')': 3, ',X)': 4, '),Y': 5, '),Z': 6, ',S),Y': 7}


class DasmModelError(AssertionError):
    pass


def mode_format(mode):
    if mode in _FMT_SPECIAL:
        return _FMT_SPECIAL[mode]
    shape, wide = I.MODE_SHAPE[mode], I.MODE_OPERAND_BYTES[mode] == 2
    if shape.startswith('#'):
        hi = 9 if wide else 3
    elif shape.startswith('('):
        hi = 5 if wide else 4
    else:
        hi = 2 if wide else 1
    return (hi << 4) | _FMT_SUFFIX[shape[shape.index('e') + 1:]]


def view_map(view):
    """opcode → (listing key, mode) of one CPU view, unprefixed rows only.
    A bit-digit key is listed by its key; dasm.s appends the digit."""
    best = {}
    for r in I.instructions(view):
        if r.prefix:
            continue
        cur = best.get(r.opcode)
        if cur is None or _RANK[r.key] >= _RANK[cur.key]:
            best[r.opcode] = r
    return {op: (r.key, r.mode) for op, r in best.items()}


@dataclass
class DasmModel:
    cpu_set: str
    define: str
    maps: list                # [(view, opcode → (key, mode))], map blocks in order
    cpu_map: list             # asm_cpu → map index (padded, n_asm_cpu)
    subset_cpu: int           # the asm_cpu whose view is the subset bitmap, or None
    bitmap: set               # the opcodes that view defines, or None
    names: list               # mnemonic index → name; 0 = '...'
    digit_range: tuple        # (lo, hi) of the bit-digit keys' indexes, or None
    n_modes: int
    qmap: list = None         # m65: opcode → 0 / 1 Q form / 2 Q form written ($nn)
    qsfx_range: tuple = None  # m65: the Q-suffix stems' indexes
    qname_range: tuple = None # m65: LDA LDQ STA STQ … — a stem, then its Q name

    @property
    def byte_modes(self):     # m65: one mode byte per opcode, not a nibble
        return self.n_modes > 16


def _m65_subset(view, host):
    """The opcodes of `view` as a subset of the 4510 map `host`: each lists
    there as in the view, after D3 ($EA lists EOM in every view)."""
    vm = view_map(view)
    for op, (key, mode) in vm.items():
        hk, hm = host[op]
        same_mode = hm == mode
        if not (same_mode and (hk == key or (op == 0xEA and hk == 'EOM'))):
            raise DasmModelError(f"{view} ${op:02X} {key} {mode}: not {hk} {hm} of the 4510 map")
    return set(vm)


def build_m65_model(cpu_set):
    """The m65 set: the 4510 map (the 45GS02's, plus the prefix peel), the
    6502 view as a bitmap over it, the Q map."""
    define, views, _cls = MT.CPU_SETS[cpu_set]
    host = view_map('4510')
    n = n_asm_cpu(cpu_set)
    bitmap = _m65_subset('6502', host)                # the subset view
    qmap = [0] * 256
    for r in I.instructions('45gs02'):
        if r.prefix == I.PREFIX_Q:
            qmap[r.opcode] = 2 if (r.mode, host[r.opcode][1]) == ('ZPI', 'ZPIZ') else 1
    used = sorted({k for k, _ in host.values()})
    digit = [k for k in used if k in I.BIT_DIGIT_MNEMONICS]
    qsfx = sorted(k for k in used if k in I.Q_SUFFIX_STEMS)
    qname = [n for q, stem in I.Q_NAMES.items() for n in (stem, q)]
    rest = [k for k in used if k not in I.BIT_DIGIT_MNEMONICS
            and k not in qsfx and k not in qname]
    names = ['...'] + digit + qsfx + qname + rest
    n_modes = 1 + max(I.ALL_MODES.index(md) for _, md in host.values())
    if len(names) > 128:
        raise DasmModelError(f"{cpu_set}: {len(names)} names do not fit")
    lo = 1 + len(digit)
    return DasmModel(cpu_set, define, [('4510', host)], [0] * n, MT.ASM_CPU['6502'], bitmap,
                     names, (1, len(digit)), n_modes, qmap,
                     (lo, lo + len(qsfx) - 1), (lo + len(qsfx), lo + len(qsfx) + len(qname) - 1))


def build_dasm_model(cpu_set):
    if cpu_set in MT.M65_SETS:
        return build_m65_model(cpu_set)
    define, views, _cls = MT.CPU_SETS[cpu_set]
    maps, cpu_map, subset_cpu, bitmap = [], {}, None, None
    for view in reversed(views):                       # top CPU first
        vm = view_map(view)
        host = next((i for i, (_, m) in enumerate(maps)
                     if all(m.get(op) == e for op, e in vm.items())), None)
        if host is None:
            maps.append((view, vm))
            cpu_map[MT.ASM_CPU[view]] = len(maps) - 1
        else:
            if bitmap is not None:
                raise DasmModelError(f"{cpu_set}: more than one subset view")
            subset_cpu, bitmap = MT.ASM_CPU[view], set(vm)
            cpu_map[MT.ASM_CPU[view]] = host
    top = MT.ASM_CPU[views[-1]]
    pad_map = [cpu_map.get(c, cpu_map[top]) for c in range(n_asm_cpu(cpu_set))]

    used = sorted({k for _, m in maps for k, _ in m.values()})
    digit = [k for k in used if k in I.BIT_DIGIT_MNEMONICS]
    names = ['...'] + digit + [k for k in used if k not in I.BIT_DIGIT_MNEMONICS]
    n_modes = 1 + max(I.ALL_MODES.index(md) for _, m in maps for _, md in m.values())
    if len(names) > 128 or n_modes > 16:
        raise DasmModelError(f"{cpu_set}: {len(names)} names / {n_modes} modes do not fit")
    return DasmModel(cpu_set, define, maps, pad_map, subset_cpu, bitmap, names,
                     (1, len(digit)) if digit else None, n_modes)


def pack_name(s):
    def cv(c):
        return 27 if c == '.' else ord(c) - ord('A') + 1
    s = s.upper().ljust(3, '.')[:3]
    v = (cv(s[0]) << 10) | (cv(s[1]) << 5) | cv(s[2])
    return v >> 8, v & 0xFF


def map_block(model, m):
    """256 mnemonic indexes, then the modes: 128 bytes packed (even opcode
    in the low nibble), or on m65 256 bytes, one per opcode."""
    idx = {n: i for i, n in enumerate(model.names)}
    mne = [idx[m[op][0]] if op in m else 0 for op in range(256)]
    mode = [I.ALL_MODES.index(m[op][1]) if op in m else 0 for op in range(256)]
    if model.byte_modes:
        return mne + mode
    return mne + [mode[i] | (mode[i + 1] << 4) for i in range(0, 256, 2)]


def _bytes(label, data, per=16, names=None):
    out = [f'{label}:'] if label else []
    for i in range(0, len(data), per):
        note = ('  ; ' + names[i // per]) if names else ''
        out.append('        .byte   ' + ','.join(f'${v:02X}' for v in data[i:i + per]) + note)
    return out


def write(models, out):
    t = ['; dasm_tables.s',
         '; Generated by dev/dasm_tables.py – DO NOT EDIT BY HAND',
         ';',
         '; Disassembler tables (doc/modules/dasm.md § Design).  One block per CPU set,',
         '; selected by the set\'s CPU_<top> define.',
         ';   dasm_cpu_map_lo/hi[asm_cpu]  map block of that CPU\'s view',
         ';   dasm_view_bm                 the subset view\'s bitmap over its map (sets',
         ';                                with one only: DASM_SUBSET_CPU names its asm_cpu)',
         ';   map block: 256 B mnemonic index per opcode, then the modes — two 4-bit',
         ';              modes per byte (128 B), or one per byte (256 B: DASM_BYTE_MODES)',
         ';   dasm_q_map (MEGA_SUPPORT): 2 bits per opcode, its Q form (0 none, 1, 2:',
         ';              ZPIZ written ($nn))',
         '',
         '        .export dasm_mne_str, dasm_mode_len, dasm_mode_fmt',
         '        .export dasm_cpu_map_lo, dasm_cpu_map_hi',
         '']
    x = ['; dasm_mne_idx.s',
         '; Generated by dev/dasm_tables.py – DO NOT EDIT BY HAND',
         ';',
         '; .include\'d by dasm.s: the constants its code tests.  MNE_DIGIT_LO/HI exist',
         '; only in CPU sets with the bit-digit keys (RMB SMB BBR BBS), DASM_SUBSET_CPU',
         '; only in sets where one CPU view is a subset bitmap over a map.',
         '']
    for m in models:
        # m65: every table in KDATA, the data window (D-P4-6)
        seg = '.segment "KDATA"' if m.cpu_set in MT.M65_SETS else '.segment "RODATA"'
        t += [f'.ifdef {m.define}', f'; ── CPU set {m.cpu_set} ' + '─' * 40, seg]
        t += ['dasm_cpu_map_lo:', f'        .byte   ' + ','.join(f'<_dasm_map_{i}' for i in m.cpu_map)]
        t += ['dasm_cpu_map_hi:', f'        .byte   ' + ','.join(f'>_dasm_map_{i}' for i in m.cpu_map)]
        if m.bitmap is not None:
            bm = [0] * 32
            for op in m.bitmap:
                bm[op >> 3] |= 1 << (op & 7)
            t += ['        .export dasm_view_bm']
            t += ['; the subset view\'s bitmap, 32 B: bit (opcode & 7) of byte (opcode >> 3)']
            t += _bytes('dasm_view_bm', bm)
        if m.qmap is not None:
            q = [sum(m.qmap[i + j] << (2 * j) for j in range(4)) for i in range(0, 256, 4)]
            t += ['        .export dasm_q_map',
                  '; Q map, 2 bits per opcode (byte opcode >> 2, bits (opcode & 3) * 2):',
                  '; 0 no Q form, 1 a Q form, 2 a Q form whose ZPIZ is written ($nn)']
            t += _bytes('dasm_q_map', q)
        t += _bytes('dasm_mode_len', [1 + I.MODE_OPERAND_BYTES[md] for md in I.ALL_MODES[:m.n_modes]])
        t += _bytes('dasm_mode_fmt', [mode_format(md) for md in I.ALL_MODES[:m.n_modes]])
        mode_rows = (16 if m.byte_modes else 32)
        for i, (view, vm) in enumerate(m.maps):
            t += [f'; map {i}: the {view} view']
            t += _bytes(f'_dasm_map_{i}', map_block(m, vm),
                        names=[f'${r:02X}-${r + 15:02X}' for r in range(0, 256, 16)]
                        + [f'modes ${r:02X}-${r + mode_rows - 1:02X}'
                           for r in range(0, 256, mode_rows)])
        t += ['.segment "KDATA"', 'dasm_mne_str:']
        for i, n in enumerate(m.names):
            hi, lo = pack_name(n)
            t.append(f'        .byte   ${hi:02X},${lo:02X}    ; {i:3d} {n}')
        t += ['.endif', '']
        x += [f'.ifdef {m.define}', 'MNE_UNK = 0']
        if m.bitmap is not None:
            x += [f'DASM_SUBSET_CPU = {m.subset_cpu}             ; its view is the subset bitmap dasm_view_bm']
        if m.digit_range:
            x += [f'MNE_DIGIT_LO = {m.digit_range[0]}', f'MNE_DIGIT_HI = {m.digit_range[1]}']
        if m.qsfx_range:
            x += [f'MNE_QSFX_LO = {m.qsfx_range[0]}', f'MNE_QSFX_HI = {m.qsfx_range[1]}',
                  f'MNE_QNAME_LO = {m.qname_range[0]}', f'MNE_QNAME_HI = {m.qname_range[1]}',
                  'DASM_BYTE_MODES = 1             ; one mode byte per opcode']
        x += ['.endif', '']
    (out / 'dasm_tables.s').write_text('\n'.join(t) + '\n')
    (out / 'dasm_mne_idx.s').write_text('\n'.join(x) + '\n')


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--out', type=pathlib.Path, help='output directory (default: src/)')
    args = ap.parse_args(argv)
    out = args.out or ROOT / 'src'
    out.mkdir(parents=True, exist_ok=True)
    models = [build_dasm_model(c) for c in MT.CPU_SETS]
    write(models, out)
    for m in models:
        n = len(m.cpu_map)
        has_bm = m.bitmap is not None
        size = 2 * n + 32 * has_bm \
            + 2 * m.n_modes + (512 if m.byte_modes else 384) * len(m.maps) \
            + (64 if m.qmap else 0)
        where = 'KDATA' if m.cpu_set in MT.M65_SETS else 'RODATA'
        print(f"CPU set {m.cpu_set}: {len(m.maps)} map(s), "
              f"{int(has_bm)} subset bitmap(s), {len(m.names)} names; "
              f"{where} {size} B + KDATA {2 * len(m.names)} B")


if __name__ == '__main__':
    sys.exit(main())
