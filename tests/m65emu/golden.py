"""golden.py — the 45GS02 golden file shared by recorder and replay.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

dev/capture_m65_golden.py records, in xmega65, one case per
instruction sequence into tests/fixtures/golden/m65_cpu.json;
tests/unit/test_mpu45gs02.py replays each case on MPU45GS02.

The file:
    source    the xmega65 version, the date, the instruction fixture
    regions   [[flat start, length], ...] — the memory a case may touch
    base      {flat addr (hex): byte} — what every case starts with on
              top of pattern(addr): the pointers the indirect modes use
    cases     one per line

A case:
    name      what it exercises
    code      the instruction under test, hex bytes, at `before.pc`
    before    registers when it starts: pc a x y z b sp p mapl maph
    mem       {flat addr (hex): byte} — differences from pattern + base
              when it starts, outside the sequence's own code (the
              case's operands, what the register preamble pushed)
    cpu_view  {CPU addr (hex): byte} — bytes the instruction reads
              outside `regions`, as the CPU saw them (BRK's vector)
    steps     xmega65 steps to complete it (a prefix byte is a step)
    after     registers when it has completed
    mem_after {flat addr (hex): byte} — what it changed in `regions`
"""

import json
import pathlib

GOLDEN = (pathlib.Path(__file__).resolve().parents[1]
          / "fixtures" / "golden" / "m65_cpu.json")

REG_NAMES = ("pc", "a", "x", "y", "z", "b", "sp", "p", "mapl", "maph")


def pattern(addr):
    """The byte every region holds before `base` and a case's `mem`."""
    return (addr * 0x9E3779B1 >> 16 ^ addr) & 0xFF


def load(path=GOLDEN):
    with open(path) as f:
        return json.load(f)


def addrs(table):
    """A file's {hex addr: byte} table with integer addresses."""
    return {int(a, 16): v for a, v in table.items()}


def start_memory(data, case):
    """{flat addr: byte} of every region byte when the case starts."""
    mem = {a: pattern(a) for start, n in data["regions"]
           for a in range(start, start + n)}
    mem.update(addrs(data["base"]))
    mem.update(addrs(case["mem"]))
    mem.update(enumerate(bytes.fromhex(case["code"]), case["before"]["pc"]))
    return mem
