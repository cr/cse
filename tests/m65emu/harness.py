"""harness.py — M65Emu, the m65 integration harness.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

MPU45GS02 on M65Memory behind EmuBase's surface (the one C64Emu has:
M65Emu supplies EmuBase's hooks — interrupt entry through the CPU, a
jiffy tick that latches $D019's raster bit, RESTORE in $DD0D, keys
into the hardware queue, load_prg() into bank 0; the two Hypervisor
services the loader uses), started either blank or from a post-boot
snapshot that dev/capture_m65_state.py records from xmega65, one per
ROM, into build/m65_state/<ROM version>/ (snapshot_dirs() lists them;
the fixture m65_snapshot in tests/conftest.py runs a test on each):

    chip.bin       chip RAM, $00000-$5FFFF (the ROM image included)
    colour.bin     colour RAM, 32 KB
    io.bin         the I/O page $D000-$D7FF, read in VIC-IV mode
    state.json     format, registers, MAP, CPU port, $D030, I/O mode,
                   the ROM's version and SHA-256, the xmega65 version
    reference.json what xmega65 did next from that state (the oracle
                   of tests/integration/test_m65emu.py)

The snapshot holds the MEGA65 ROM, so it is never committed.
"""

import json
import pathlib
import re

from emu_base import EmuBase, KeyMatrix, register

from .devices import (CIA1Ports, CIA2InterruptControl, DMAController,
                      Hypervisor, KeyboardQueue, VICInterruptLatch)
from .memory import COLOUR, M65Memory
from .mpu45gs02 import MPU45GS02

STATE_DIR = pathlib.Path(__file__).resolve().parents[2] / "build" / "m65_state"
CAPTURE = "python dev/capture_m65_state.py [--rom PATH]..."
FORMAT = 3                  # of the snapshot; state.json's "format"


class SnapshotMissing(FileNotFoundError):
    """No post-boot snapshot, or one an older recorder made: run
    dev/capture_m65_state.py."""


def snapshot_name(rom):
    """A snapshot's directory name: the six digits of the ROM's
    `V9xxxxx` version string at $16."""
    m = re.match(rb"V(9\d{5})", rom[0x16:0x1D])
    if not m:
        raise ValueError("not a MEGA65 ROM: no V9xxxxx version at $16")
    return m.group(1).decode()


def snapshot_dirs(root=STATE_DIR):
    """The snapshot directories under `root`, one per ROM, in order."""
    root = pathlib.Path(root)
    if not root.is_dir():
        return []
    return sorted(d for d in root.iterdir()
                  if d.is_dir() and (d / "state.json").exists())


def load_snapshot(state_dir):
    """The snapshot's parts: chip, colour, io (bytes), state, reference."""
    d = pathlib.Path(state_dir)
    names = ("chip.bin", "colour.bin", "io.bin", "state.json", "reference.json")
    missing = [n for n in names if not (d / n).exists()]
    if missing:
        raise SnapshotMissing(f"no M65Emu post-boot snapshot in {d} "
                              f"(missing {', '.join(missing)}); run: {CAPTURE}")
    state = json.loads((d / "state.json").read_text())
    if state.get("format") != FORMAT:
        raise SnapshotMissing(f"the M65Emu post-boot snapshot in {d} is in "
                              f"an older format; run: {CAPTURE}")
    return dict(chip=(d / "chip.bin").read_bytes(),
                colour=(d / "colour.bin").read_bytes(),
                io=(d / "io.bin").read_bytes(), state=state,
                reference=json.loads((d / "reference.json").read_text()))


class M65Emu(EmuBase):
    NAME = "M65Emu"
    SENTINEL = 0x0002           # jsr()'s RTS target, compared by PC only
    JSR_REGS = ("a", "x", "y", "z", "b")

    def __init__(self, snapshot=None):
        """A blank machine (no ROM, CPU reset), or the one in `snapshot`
        (from load_snapshot()); either with the devices attached."""
        mem = M65Memory()
        self.dma = DMAController(mem)
        self.keyboard = KeyboardQueue()
        self._keys = KeyMatrix()
        self._ram = memoryview(mem.chip)[:0x10000]   # load_prg(): bank 0, as LOAD
        self.cia1 = CIA1Ports(self._keys)
        self.cia2_icr = CIA2InterruptControl()
        self.vic_irq = VICInterruptLatch(mem)
        mem.attach(self.dma, 0x700, 0x70F)
        for off in KeyboardQueue.REGISTERS:
            mem.attach(self.keyboard, off)
        mem.attach(self.cia1, 0xC00, 0xC01)
        mem.attach(self.cia2_icr, 0xD0D)
        mem.attach(self.vic_irq, 0x019)
        self.hypervisor = Hypervisor(mem)
        mem.attach(self.hypervisor, Hypervisor.FIRST, Hypervisor.LAST)
        if snapshot is not None:
            st = snapshot["state"]
            mem.load(0, snapshot["chip"])
            mem.load(COLOUR, snapshot["colour"])
            mem.restore_io(snapshot["io"])
            mem.restore(ddr=st["ddr"], port=st["port"], d030=st["d030"],
                        io_mode=st["io_mode"])
        cpu = MPU45GS02(mem)
        self.hypervisor.cpu = cpu
        EmuBase.__init__(self, cpu, mem)
        if snapshot is not None:
            for name, value in snapshot["state"]["regs"].items():
                setattr(cpu, name, value)

    z = register("z", 0xFF)             # the 45GS02's own registers
    b = register("b", 0xFF)
    sp = register("sp", 0xFFFF)

    # ── EmuBase's hooks ───────────────────────────────────────────

    def _push_return(self, ret):
        """jsr(): push onto the current stack, as JSR would."""
        self._cpu._push_word(ret)

    def _enter_irq(self):
        """MPU45GS02's entry: refused while I is set, a prefix or the
        MAP latch is pending."""
        return self._cpu.irq()

    def _enter_nmi(self):
        return self._cpu.nmi()

    def _jiffy_tick(self):
        """The tick stands for a frame: the raster interrupt latched,
        as the KERNAL's IRQ handler checks before its frame work."""
        self.vic_irq.latch(0x01)

    def _latch_restore(self):
        self.cia2_icr.latch(0x10)

    def _queue_key(self, petscii):
        """Into the hardware keyboard queue (no limit)."""
        self.keyboard.push(petscii)

    # ── the screen, where the VIC-IV shows it ─────────────────────

    def _screen(self):
        io = self._mem.io
        base = io[0x60] | io[0x61] << 8 | io[0x62] << 16 | (io[0x63] & 0x0F) << 24
        return base, io[0x58] | io[0x59] << 8, io[0x5E]

    def screen_row(self, row):
        """One row's screen codes, from the VIC-IV screen pointer
        ($D060-$D063), line step ($D058-$D059) and width ($D05E)."""
        base, step, cols = self._screen()
        start = base + row * step
        return [self._mem.read_flat(start + c) for c in range(cols)]
