"""test_m65dma.py — M65Emu's DMA controller against xmega65.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier U: every job list recorded in xmega65
(tests/fixtures/golden/m65_dma.json, dev/capture_m65_dma.py) is
started on M65Emu as the recorder's code started it — the DMA
registers written through the CPU's view — and must change memory
exactly as it did in xmega65.  Targeted tests pin what the recording
cannot: the registers a snapshot restores, and the modes that raise.
"""

import json
import pathlib

import pytest

from m65emu import M65Emu
from m65emu.devices import DMANotModelled
from m65emu.golden import pattern
from m65emu.memory import VIC4

GOLDEN = json.loads((pathlib.Path(__file__).resolve().parents[1]
                     / "fixtures" / "golden" / "m65_dma.json").read_text())


def machine():
    emu = M65Emu()
    emu.memory.restore(ddr=0xFF, port=0x35, d030=0x00, io_mode=VIC4)
    return emu


def start(mem, list_at, *, rev, mb, enhanced):
    mem[0xD703] = rev
    mem[0xD704] = mb
    mem[0xD702] = list_at >> 16 & 0x7F
    mem[0xD701] = list_at >> 8 & 0xFF
    mem[0xD705 if enhanced else 0xD700] = list_at & 0xFF


def addresses():
    for start_, n in GOLDEN["regions"] + [GOLDEN["rom"]]:
        yield from range(start_, start_ + n)


@pytest.mark.parametrize("case", GOLDEN["cases"],
                         ids=[c["name"] for c in GOLDEN["cases"]])
def test_recorded_job(case):
    emu = machine()
    mem = emu.memory
    for start_, n in GOLDEN["regions"]:
        mem.load(start_, bytes(pattern(a) for a in range(start_, start_ + n)))
    mem.load(GOLDEN["list_at"], bytes.fromhex(case["list"]))
    before = {a: mem.read_flat(a) for a in addresses()}
    start(mem, GOLDEN["list_at"], rev=case["rev"], mb=case["mb"],
          enhanced=case["enhanced"])
    want = before | {int(a, 16): v for a, v in case["changes"].items()}
    diff = {f"{a:07X}": (mem.read_flat(a), v) for a, v in want.items()
            if mem.read_flat(a) != v}
    assert not diff, diff


def test_dma_registers_are_not_logged_as_unmodelled():
    mem = machine().memory
    mem.io_log.clear()
    mem.load(0x1C00, bytes([0x03, 1, 0, 0x5A, 0, 0, 0, 0x1A, 0, 0, 0]))
    start(mem, 0x1C00, rev=0, mb=0, enhanced=False)
    assert not mem.io_log


def test_restoring_registers_starts_no_job_and_keeps_the_revision():
    emu = machine()
    mem = emu.memory
    io = bytearray(0x800)
    io[0x700:0x707] = bytes([0x00, 0x1C, 0x00, 0x01, 0x00, 0x00, 0x00])
    mem.load(0x1A40, bytes([1, 2, 3, 4]))
    # COPY 4 from $1A40 to $1B00 with F018B sub-command 2: source held.
    # Read as F018A, the same bytes are a plain copy.
    mem.load(0x1C00, bytes([0x00, 4, 0, 0x40, 0x1A, 0, 0, 0x1B, 0, 0x02, 0, 0]))
    mem.restore_io(io)
    assert mem.read_flat(0x1B00) == 0                 # nothing ran
    mem[0xD700] = 0x00                                # now it runs
    assert [mem.read_flat(0x1B00 + k) for k in range(4)] == [1, 1, 1, 1]   # F018B


@pytest.mark.parametrize("register, option", [(0xD706, None), (0xD707, None),
                                              (0xD705, 0x87), (0xD705, 0x97)])
def test_unmodelled_modes_raise(register, option):
    mem = machine().memory
    lst = ([0x0B, option, 0x00, 0x00] if option else []) + \
        [0x00, 1, 0, 0, 0x1A, 0, 0, 0x1B, 0, 0, 0, 0]
    mem.load(0x1C00, bytes(lst))
    mem[0xD702], mem[0xD701] = 0x00, 0x1C
    with pytest.raises(DMANotModelled):
        mem[register] = 0x00


def test_modulo_raises():
    mem = machine().memory
    mem.load(0x1C00, bytes([0x00, 1, 0, 0, 0x1A, 0x20, 0, 0x1B, 0, 0, 0]))   # source MOD
    with pytest.raises(DMANotModelled):
        start(mem, 0x1C00, rev=0, mb=0, enhanced=False)
