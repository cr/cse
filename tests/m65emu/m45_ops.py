"""m45_ops.py — the raw-byte macros of src/m45_ops.inc, as M65Emu sees them.

Owner: doc/platform_layer.md

Contract source: [doc/platform_layer.md § Raw-byte instructions](../../doc/platform_layer.md#raw-byte-instructions)
and [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Each macro is assembled with ca65 as 6502 code, as CSE's modules are,
and its bytes decoded with M65Emu's table (isa.py, from the
compendium), so clean mode's allowed set is what the macros really
emit — never a second list of opcodes:

    MPU45GS02(memory, clean=regions, allow=m45_ops.allowed_keys())
"""

import functools
import pathlib
import re
import subprocess
import tempfile

from . import isa

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
INC = SRC / "m45_ops.inc"
OPERAND = 0x12             # the argument a macro with one is assembled with

_MACRO = re.compile(r"^[ \t]*\.macro[ \t]+(\w+)[ \t]*(\w*)", re.M)
_CFG = """MEMORY { M: start = $1000, size = $1000, file = %O; }
SEGMENTS { CODE: load = M, type = ro; }
"""


def macros():
    """Macro name → its argument's name, or '' for none."""
    return dict(_MACRO.findall(INC.read_text()))


@functools.lru_cache(maxsize=None)
def assemble(name):
    """The bytes macro `name` assembles to (its argument: OPERAND)."""
    arg = f" ${OPERAND:02X}" if macros()[name] else ""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = pathlib.Path(tmp)
        (tmp / "m.s").write_text(
            f'.include "m45_ops.inc"\n.segment "CODE"\n        {name}{arg}\n')
        (tmp / "m.cfg").write_text(_CFG)
        subprocess.run(["ca65", "--cpu", "6502", "-I", str(SRC),
                        str(tmp / "m.s"), "-o", str(tmp / "m.o")], check=True)
        subprocess.run(["ld65", "-C", str(tmp / "m.cfg"), str(tmp / "m.o"),
                        "-o", str(tmp / "m.bin")], check=True)
        return (tmp / "m.bin").read_bytes()


@functools.lru_cache(maxsize=None)
def _table():
    return isa.decode_table()


def decode(code):
    """(decode key, compendium row) of the instruction `code` starts
    with: the longest leading bytes that are a key (EOM alone is one)."""
    table = _table()
    key = next(tuple(code[:n]) for n in (4, 3, 2, 1)
               if tuple(code[:n]) in table)
    return key, table[key]


def allowed_keys():
    """The decode keys of every macro: clean mode's `allow`."""
    return frozenset(decode(assemble(name))[0] for name in macros())
