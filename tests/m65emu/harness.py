"""harness.py — M65Emu, the m65 integration harness.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

MPU45GS02 on M65Memory behind EmuBase's surface (the one C64Emu has),
started either blank or from the post-boot snapshot that
dev/capture_m65_state.py records from xmega65 into build/m65_state/:

    chip.bin       chip RAM, $00000-$5FFFF (the ROM image included)
    colour.bin     colour RAM, 32 KB
    io.bin         the I/O page $D000-$D7FF, read in VIC-IV mode
    state.json     registers, MAP, CPU port, $D030, I/O mode, source
    reference.json what xmega65 did next from that state (the oracle
                   of tests/integration/test_m65emu.py)

The snapshot holds the MEGA65 ROM, so it is never committed.
"""

import json
import pathlib

from emu_base import EmuBase, decode_screen_codes

from .devices import CIA1Ports, DMAController, KeyboardQueue
from .memory import COLOUR, M65Memory
from .mpu45gs02 import MPU45GS02

STATE_DIR = pathlib.Path(__file__).resolve().parents[2] / "build" / "m65_state"
CAPTURE = "python dev/capture_m65_state.py"


class SnapshotMissing(FileNotFoundError):
    """No post-boot snapshot: run dev/capture_m65_state.py."""


def load_snapshot(state_dir=STATE_DIR):
    """The snapshot's parts: chip, colour, io (bytes), state, reference."""
    d = pathlib.Path(state_dir)
    names = ("chip.bin", "colour.bin", "io.bin", "state.json", "reference.json")
    missing = [n for n in names if not (d / n).exists()]
    if missing:
        raise SnapshotMissing(f"no M65Emu post-boot snapshot in {d} "
                              f"(missing {', '.join(missing)}); run: {CAPTURE}")
    return dict(chip=(d / "chip.bin").read_bytes(),
                colour=(d / "colour.bin").read_bytes(),
                io=(d / "io.bin").read_bytes(),
                state=json.loads((d / "state.json").read_text()),
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
        self.cia1 = CIA1Ports()
        mem.attach(self.dma, 0x700, 0x70F)
        for off in KeyboardQueue.REGISTERS:
            mem.attach(self.keyboard, off)
        mem.attach(self.cia1, 0xC00, 0xC01)
        if snapshot is not None:
            st = snapshot["state"]
            mem.load(0, snapshot["chip"])
            mem.load(COLOUR, snapshot["colour"])
            mem.restore_io(snapshot["io"])
            mem.restore(ddr=st["ddr"], port=st["port"], d030=st["d030"],
                        io_mode=st["io_mode"])
        cpu = MPU45GS02(mem)
        EmuBase.__init__(self, cpu, mem)
        if snapshot is not None:
            for name, value in snapshot["state"]["regs"].items():
                setattr(cpu, name, value)
            self.snapshot = snapshot

    @classmethod
    def from_snapshot(cls, state_dir=STATE_DIR):
        return cls(load_snapshot(state_dir))

    # ── the 45GS02's own registers ────────────────────────────────

    @property
    def z(self):
        return self._cpu.z

    @z.setter
    def z(self, val):
        self._cpu.z = val & 0xFF

    @property
    def b(self):
        return self._cpu.b

    @b.setter
    def b(self, val):
        self._cpu.b = val & 0xFF

    @property
    def sp(self):
        return self._cpu.sp

    @sp.setter
    def sp(self, val):
        self._cpu.sp = val & 0xFFFF

    # ── running and loading ───────────────────────────────────────

    def _push_return(self, ret):
        """jsr(): push onto the current stack, as JSR would."""
        self._cpu._push_word(ret)

    def inject_keys(self, data):
        """Queue PETSCII bytes in the keyboard scanner, as typed."""
        for petscii in data:
            self.keyboard.push(petscii)

    def load_prg(self, prg_path, map_path=None):
        """Put the payload at its load address in bank 0, as the
        KERNAL's LOAD does, and load the symbols of the .lbl beside
        the map; return the load address."""
        prg_path = pathlib.Path(prg_path)
        load_addr, payload = self._read_prg(prg_path)
        self._mem.load(load_addr, payload)
        self._load_symbols(map_path or prg_path.with_suffix(".map"))
        return load_addr

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

    def screen_text(self, row):
        return decode_screen_codes(self.screen_row(row))
