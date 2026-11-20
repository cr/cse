"""test_dasm_tables.py — the disassembler model of dev/dasm_tables.py.

Owner: doc/build_system.md

Contract source: [doc/modules/dasm.md § Design](../../doc/modules/dasm.md#design).

Tier: generator (pure Python).  The emitted bytes are exercised by
test_dasm (every opcode × every asm_cpu of every C64 build against the
instruction set) and test_golden_asm_dasm; these tests pin the model's
own rules: every CPU view decodes from its map (and the subset bitmap),
the per-asm_cpu tables are padded safely, the name indexes keep the
decoder's range compares valid, and the operand formats are dasm.md's.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import dasm_tables as D                          # noqa: E402
import instruction_set as I                      # noqa: E402
import mnemonic_tables as MT                     # noqa: E402


@pytest.fixture(scope="module", params=list(MT.CPU_SETS))
def model(request):
    return D.build_dasm_model(request.param)


def _decode(model, cpu, op):
    """(key, mode) the tables give opcode `op` under asm_cpu `cpu`, or None."""
    _, vm = model.maps[model.cpu_map[cpu]]
    if cpu == model.subset_cpu and op not in model.bitmap:
        return None
    return vm.get(op)


def _listed(model, view):
    """What `view` lists: its rows, on m65 with $EA as EOM in every view."""
    want = D.view_map(view)
    if model.cpu_set in MT.M65_SETS:
        want = {op: (('EOM', m) if op == 0xEA else (k, m)) for op, (k, m) in want.items()}
    return want


def test_every_view_decodes_from_the_tables(model):
    _, views, _ = MT.CPU_SETS[model.cpu_set]
    for view in views:
        cpu = MT.ASM_CPU[view]
        want = _listed(model, view)
        for op in range(256):
            assert _decode(model, cpu, op) == want.get(op), (model.cpu_set, view, hex(op))


def test_asm_cpu_tables_padded_to_the_top_cpu(model):
    _, views, _ = MT.CPU_SETS[model.cpu_set]
    top = MT.ASM_CPU[views[-1]]
    n = D.n_asm_cpu(model.cpu_set)
    assert n == (5 if model.cpu_set in MT.M65_SETS else 3)
    assert len(model.cpu_map) == n
    in_set = {MT.ASM_CPU[v] for v in views}
    for cpu in range(n):
        if cpu not in in_set:
            assert model.cpu_map[cpu] == model.cpu_map[top] and cpu != model.subset_cpu


def test_names_keep_the_decoder_range_compares_valid(model):
    assert model.names[0] == '...'
    assert len(model.names) <= 128 and len(set(model.names)) == len(model.names)
    digit = [i for i, n in enumerate(model.names) if n in I.BIT_DIGIT_MNEMONICS]
    if digit:
        assert model.digit_range == (digit[0], digit[-1])
        assert digit == list(range(digit[0], digit[-1] + 1))
    else:
        assert model.digit_range is None


def test_one_map_per_distinct_view_and_its_bitmap(model):
    views = [v for v, _ in model.maps]
    assert len(views) == len(set(views))
    assert (model.bitmap is None) == (model.subset_cpu is None)
    if model.cpu_set in MT.M65_SETS:            # one map, the 6502 view over it
        assert views == ['4510'] and model.bitmap is not None
        assert model.subset_cpu == 0                # the 6502 view
    if model.cpu_set == '65c02':                # the CMOS mode: 6502 over 65C02
        assert views == ['65c02'] and model.bitmap is not None


# ── the m65 set (dasm.md § Design, § Prefix peel; D-P4-10) ─────────────────

@pytest.fixture(scope="module")
def m65():
    return D.build_dasm_model('45gs02')


def test_m65_modes_are_bytes_and_every_table_kdata(m65):
    assert m65.byte_modes and m65.n_modes == 20
    assert len(D.map_block(m65, m65.maps[0][1])) == 512


def test_m65_q_map_is_the_q_forms(m65):
    host = m65.maps[0][1]
    want = [0] * 256
    for r in I.instructions('45gs02'):
        if r.prefix == I.PREFIX_Q:
            want[r.opcode] = 2 if (r.mode, host[r.opcode][1]) == ('ZPI', 'ZPIZ') else 1
    assert m65.qmap == want
    assert sum(v == 2 for v in m65.qmap) == 7     # adcq andq cmpq eorq orq sbcq stq


def test_m65_name_ranges(m65):
    lo, hi = m65.qsfx_range
    assert sorted(m65.names[lo:hi + 1]) == sorted(I.Q_SUFFIX_STEMS)
    lo, hi = m65.qname_range
    pairs = m65.names[lo:hi + 1]
    assert [(pairs[i], pairs[i + 1]) for i in range(0, len(pairs), 2)] == \
        [(s, q) for s in ('LDA', 'STA', 'ORA', 'DEC', 'INC')
         for q, st in I.Q_NAMES.items() if st == s]


# dasm.md § Design, *Mode formatting*: hi nybble prefix/size, lo nybble suffix.
_DOC_FORMATS = {
    'IMP': 0x00, 'ACC': 0x60, 'IMM': 0x30, 'ZP': 0x10, 'ZPX': 0x11, 'ZPY': 0x12,
    'ABS': 0x20, 'ABX': 0x21, 'ABY': 0x22, 'IND': 0x53, 'INX': 0x44, 'INY': 0x45,
    'REL': 0x70, 'ZPI': 0x43, 'AIX': 0x54, 'ZPREL': 0x80,
}


@pytest.mark.parametrize("mode", list(_DOC_FORMATS))
def test_mode_format_is_dasm_md(mode):
    assert D.mode_format(mode) == _DOC_FORMATS[mode]


def test_listing_name_is_last_in_listing_order():
    """The 6510 aliases list by the name whose key comes last in OPCODES order."""
    vm = D.view_map('6510')
    for op, (key, _mode) in vm.items():
        rivals = [r.key for r in I.instructions('6510') if r.opcode == op and not r.prefix]
        assert key == max(rivals, key=D._RANK.get), hex(op)
