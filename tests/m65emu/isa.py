"""isa.py — the 45GS02 instruction table M65Emu decodes from.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Built from tests/fixtures/mega65_instruction_set.csv, the MEGA65
compendium's Appendix L tables as extracted by bbbc64's
dev/mega65_opcode_extract.py, never from dev/instruction_set.py: the
emulator must not share the tables the assembler is generated from.

A decode key is the tuple of code bytes up to and including the
opcode: (op,) for a 4510 row, (0xEA, op) for a flat row, (0x42, 0x42,
op) for a Q row, (0x42, 0x42, 0xEA, op) for a flat Q row.
"""

import csv
import pathlib
from typing import NamedTuple

FIXTURE = (pathlib.Path(__file__).resolve().parents[1]
           / "fixtures" / "mega65_instruction_set.csv")

# The 6502 set's undocumented mnemonics (the compendium lists them in
# its 6502 tables); NOP counts as documented only at $EA, and $EB is
# the undocumented duplicate of SBC #.
_UNDOCUMENTED_6502 = frozenset(
    "ALR ANC ARR DCP ISC KIL LAS LAX RLA RRA SAX SBX SHA SHX SHY SLO "
    "SRE TAS XAA".split())
_UNDOCUMENTED_KEYS = frozenset({(0xEB,)})

# Q-prefixed rows the compendium reserves: no semantics to emulate.
RESERVED = frozenset({"RESQ", "RSVQ"})


class Row(NamedTuple):
    cpu_set: str     # 6502 | 4510 | 45GS02
    mnemonic: str
    mode: str        # the compendium's mode name, e.g. "base-page,X"
    key: tuple       # decode key (see module docstring)
    length: int      # instruction length in bytes, prefixes included


def rows(path=FIXTURE):
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            code = tuple(int(b, 16) for b in r["bytes"].split())
            yield Row(r["set"], r["mnemonic"], r["mode"], code,
                      int(r["length"]))


def decode_table(path=FIXTURE):
    """Decode key → Row for the 4510 set and the 45GS02 prefixed rows.

    Where the compendium lists one prefixed encoding twice (the
    reserved RESQ/RSVQ rows), the first row wins; both are reserved.
    """
    table = {}
    for row in rows(path):
        if row.cpu_set == "6502":
            continue
        table.setdefault(row.key, row)
    return table


def documented_6502(path=FIXTURE):
    """The documented NMOS 6502 opcodes (151), as decode keys."""
    keys = set()
    for row in rows(path):
        if row.cpu_set != "6502" or row.mnemonic in _UNDOCUMENTED_6502:
            continue
        if row.mnemonic == "NOP" and row.key != (0xEA,):
            continue
        if row.key in _UNDOCUMENTED_KEYS:
            continue
        keys.add(row.key)
    return frozenset(keys)
