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
    if model.cpu_bm[cpu] and op not in model.bitmap:
        return None
    return vm.get(op)


def test_every_view_decodes_from_the_tables(model):
    _, views, _ = MT.CPU_SETS[model.cpu_set]
    for view in views:
        cpu = MT.ASM_CPU[view]
        want = D.view_map(view)
        for op in range(256):
            assert _decode(model, cpu, op) == want.get(op), (model.cpu_set, view, hex(op))


def test_asm_cpu_tables_padded_to_the_top_cpu(model):
    _, views, _ = MT.CPU_SETS[model.cpu_set]
    top = MT.ASM_CPU[views[-1]]
    assert len(model.cpu_map) == len(model.cpu_bm) == D.N_ASM_CPU
    in_set = {MT.ASM_CPU[v] for v in views}
    for cpu in range(D.N_ASM_CPU):
        if cpu not in in_set:
            assert (model.cpu_map[cpu], model.cpu_bm[cpu]) == \
                (model.cpu_map[top], model.cpu_bm[top])


def test_names_keep_the_decoder_range_compares_valid(model):
    assert model.names[0] == '...'
    assert len(model.names) <= 128 and len(set(model.names)) == len(model.names)
    digit = [i for i, n in enumerate(model.names) if n in I.BIT_DIGIT_MNEMONICS]
    if digit:
        assert model.digit_range == (digit[0], digit[-1])
        assert digit == list(range(digit[0], digit[-1] + 1))
    else:
        assert model.digit_range is None


def test_one_map_per_distinct_view_at_most_one_bitmap(model):
    views = [v for v, _ in model.maps]
    assert len(views) == len(set(views))
    assert sum(model.cpu_bm) <= D.N_ASM_CPU


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
