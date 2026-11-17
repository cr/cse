"""golden.py — the 45GS02 golden file shared by recorder and replay.

Owner: doc/build_system.md

dev/capture_m65_golden.py records, in xmega65, one case per
instruction sequence into tests/fixtures/golden/m65_cpu.json;
tests/unit/test_mpu45gs02.py replays each case on MPU45GS02.  Both
sides build the same starting memory: every byte of REGIONS holds
pattern(addr), then the case's recorded differences are applied.

A case:
    name      what it exercises
    code      the instruction under test, hex bytes
    before    registers when it starts: pc a x y z b sp p mapl maph
    mem       {flat addr (hex): byte} — differences from the pattern
              when it starts (the code bytes, the case's operands,
              what the preamble pushed)
    steps     xmega65 steps to complete it (a prefix byte is a step)
    after     registers when it has completed
    mem_after {flat addr (hex): byte} — what it changed in REGIONS
"""

import json
import pathlib

GOLDEN = (pathlib.Path(__file__).resolve().parents[1]
          / "fixtures" / "golden" / "m65_cpu.json")

# Flat ranges the cases may touch; all in block 0 ($0000-$1FFF, which
# the post-boot MAP leaves unmapped, so CPU address = flat address)
# except the flat-addressing target page.
REGIONS = (
    (0x00100, 0x200),     # stack page and the page above (16-bit stack)
    (0x01800, 0x100),     # code
    (0x01900, 0x100),     # base page (B = $19)
    (0x01A00, 0x200),     # data
    (0x40000, 0x100),     # flat-addressing target, outside the CPU view
)

REG_NAMES = ("pc", "a", "x", "y", "z", "b", "sp", "p", "mapl", "maph")


def pattern(addr):
    """The byte every region holds before a case's differences."""
    return (addr * 0x9E3779B1 >> 16 ^ addr) & 0xFF


def region_addrs():
    for start, length in REGIONS:
        yield from range(start, start + length)


def load(path=GOLDEN):
    with open(path) as f:
        return json.load(f)


def memory_for(case, memory_cls):
    """A fresh memory holding the case's starting state."""
    mem = memory_cls()
    for a in region_addrs():
        mem.write_flat(a, pattern(a))
    for a, v in case["mem"].items():
        mem.write_flat(int(a, 16), v)
    return mem


def expected_memory(case):
    want = {a: pattern(a) for a in region_addrs()}
    for a, v in case["mem"].items():
        want[int(a, 16)] = v
    for a, v in case["mem_after"].items():
        want[int(a, 16)] = v
    return want
