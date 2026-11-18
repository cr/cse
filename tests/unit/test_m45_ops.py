"""test_m45_ops.py — the raw-byte macros of src/m45_ops.inc.

Owner: doc/platform_layer.md

Contract source: [doc/platform_layer.md § Raw-byte instructions](../../doc/platform_layer.md#raw-byte-instructions).

Each macro assembles, with ca65 as 6502 code, to the encoding the
MEGA65 compendium gives the instruction it names (M65Emu's decode
table, tests/fixtures/mega65_instruction_set.csv — not
dev/instruction_set.py), and the set of macros is the contract's.
"""

import pytest

from m65emu import isa
from m65emu import m45_ops

# The contract's table: macro → (compendium mnemonic, compendium mode).
CONTRACT = {
    "M45_MAP": ("MAP", "implied"),
    "M45_EOM": ("EOM", "implied"),
    "M45_LDZ_IMM": ("LDZ", "immediate 8bit"),
    "M45_TAB": ("TAB", "implied"),
    "M45_PHY": ("PHY", "implied"),
    "M45_PLY": ("PLY", "implied"),
    "M45_PLX": ("PLX", "implied"),
    "M45_PLZ": ("PLZ", "implied"),
    "M45_FAR_LDA": ("LDA", "[indirect],Z"),
    "M45_FAR_STA": ("STA", "[indirect],Z"),
    "M45_FAR_ORA": ("ORA", "[indirect],Z"),
    "M45_JMP_IND_X": ("JMP", "(indirect,X)"),
}


def test_the_macros_are_the_contracts():
    assert set(m45_ops.macros()) == set(CONTRACT)


@pytest.mark.parametrize("name", sorted(CONTRACT))
def test_each_macro_is_the_compendium_encoding(name):
    code = m45_ops.assemble(name)
    key, row = m45_ops.decode(code)
    assert (row.mnemonic, row.mode) == CONTRACT[name]
    assert len(code) == row.length
    width = row.length - len(key)                  # the operand: a byte or a word
    assert code[len(key):] == (m45_ops.OPERAND.to_bytes(width, "little") if width else b"")


def test_allowed_keys_are_the_macros_decode_keys():
    keys = m45_ops.allowed_keys()
    assert (0x5C,) in keys and (0xEA, 0xB2) in keys
    assert len(keys) == len(CONTRACT)
    assert keys <= set(isa.decode_table())
