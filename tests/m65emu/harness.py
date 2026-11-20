"""harness.py — M65Emu, the m65 integration harness.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

MPU45GS02 on M65Memory behind EmuBase's surface (the one C64Emu has:
M65Emu supplies EmuBase's hooks — interrupt entry through the CPU, a
jiffy tick that latches $D019's raster bit, RESTORE in $DD0D, keys
into the hardware queue; the two Hypervisor services the loader uses),
plus the m65 PRG's start: enter_premise() puts a ROM's run premise in
place (run_premise() reads it from m65_premise.json), install_prg()
the machine the m65 loader installs.  Started either blank or from a post-boot
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
                      Hypervisor, IECPort, KeyboardQueue, RasterLine,
                      VICHotRegisters, VICInterruptLatch)
from .memory import COLOUR, M65Memory
from .mpu45gs02 import MPU45GS02

ROOT = pathlib.Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "build" / "m65_state"
CAPTURE = "python dev/capture_m65_state.py [--rom PATH]..."
FORMAT = 3                  # of the snapshot; state.json's "format"
# The MEGA65 ROMs the m65 build is verified on (build_system.md § MEGA65
# ROM, *The verified ROMs*): the floor and the current one.
VERIFIED_ROMS = ("920413", "920421")
PREMISE = ROOT / "tests" / "fixtures" / "golden" / "m65_premise.json"

# The installed machine (memory_design.md § Memory Map — m65,
# platform.inc's m65 block), the one home of these numbers on the test
# side: the two maps' MAP operands and register values, B, the stub,
# the stack top, the base page the loader clears, the banks.
MAP_CSE = (0x00, 0xE3, 0x00, 0xB3)          # A X Y Z
MAP_USER = (0x00, 0xE0, 0x00, 0x83)
CSE_BP = 0x1F
STUB_BASE = 0x1FB0
STACK_TOP = 0xF1
BP_CLEARED = 0xB0                           # 0.1F00-0.1FAF (ZP_FILL_END)
STUB_COLD_INDEX = 4                         # the loader enters stub_cold with X = 4
IEC_FLAGS = 0xA2            # bit 7: the serial device is slow (no fast serial)
MSGFLG = 0x9D               # the KERNAL's message flag: $00 at a RUN-started PRG's
                            # _main, $80 in the direct-mode snapshot (recorded, both ROMs)
KMAP_REC = 0x011C           # the KERNAL's map record, A X Y Z: SYS's map at a RUN-started
                            # PRG (D-P3-8, Tier X), BASIC's ($00 $E3 $00 $B3) in the snapshot
BANK_USER, BANK_SRC, BANK_CSE, BANK_SCREEN50 = 0, 2, 3, 4
# the text modes (platform_layer.md § Display): the key after ESC that
# selects one, its width, height and the screen's bank
TEXT_MODES = {"80x25": ("8", 80, 25, BANK_USER), "40x25": ("4", 40, 25, BANK_USER),
              "80x50": ("5", 80, 50, BANK_SCREEN50)}


def map_registers(a, x, y, z):
    """(MAPL, MAPH) as MAP sets them from A X Y Z."""
    return x << 8 | a, z << 8 | y


CSE_MAP, USER_MAP = map_registers(*MAP_CSE), map_registers(*MAP_USER)


def flat(bank, addr=0):
    """The flat address of `addr` in `bank`."""
    return bank << 16 | addr


def run_premise(rom):
    """The run premise m65_premise.json records for ROM `rom`
    (e.g. "V920413")."""
    for entry in json.loads(PREMISE.read_text())["roms"]:
        if entry["rom"] == rom:
            return entry
    raise KeyError(f"no run premise recorded for {rom} in {PREMISE.name}; "
                   f"run: python dev/capture_m65_premise.py --rom PATH")


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


def verified_rom_gaps(root=STATE_DIR):
    """What keeps the snapshots under `root` from covering the verified
    ROMs, one line each: a ROM with no snapshot, or one an older
    recorder made.  Empty when every verified ROM has a current one —
    or when there is no snapshot at all (the m65 tests skip)."""
    root = pathlib.Path(root)
    have = {d.name: d for d in snapshot_dirs(root)}
    if not have:
        return []
    gaps = []
    for rom in VERIFIED_ROMS:
        if rom not in have:
            gaps.append(f"no snapshot of ROM {rom} in {root}; run: {CAPTURE}")
            continue
        fmt = json.loads((have[rom] / "state.json").read_text()).get("format")
        if fmt != FORMAT:
            gaps.append(f"snapshot {rom} is format {fmt}, not {FORMAT}; run: {CAPTURE}")
    return gaps


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
        mem.attach(IECPort(mem), 0xD00)
        mem.attach(self.vic_irq, 0x019)
        mem.attach(RasterLine(mem, lambda: self._steps), 0x012)
        self.vic_hot = VICHotRegisters(mem)
        for off in VICHotRegisters.REGISTERS:
            mem.attach(self.vic_hot, off)
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

    # ── the m65 PRG's start ───────────────────────────────────────

    def enter_premise(self, premise):
        """The machine at a RUN-started PRG's SYS entry: the recorded
        registers, MAP and P, the stack bytes above SP (the SYS return
        path's), and what RUN leaves (_run_leaves)."""
        cpu = self._cpu
        for name, value in premise["regs"].items():
            setattr(cpu, name, value)
        above = bytes.fromhex(premise["stack_above_sp"])
        self._mem.load(cpu.sp + 1, above)
        self._run_leaves()

    def _run_leaves(self):
        """What RUN leaves that the direct-mode snapshot lacks: the
        KERNAL's messages off, its map record the SYS map."""
        self._ram[MSGFLG] = 0x00
        self._ram[KMAP_REC:KMAP_REC + 4] = bytes(MAP_USER)

    def install_prg(self, prg_path, map_path=None):
        """The m65 PRG in bank 0 as LOAD puts it, its symbols, and the
        machine its loader installs (loader.md § Design, m65) — where
        EmuBase's load_prg(), which M65Emu shares with C64Emu, copies
        segments within bank 0: the stub
        at STUB_BASE, CSE's base page cleared but for the stub's cold
        target (_main), CODE + RODATA and KDATA in bank 3, BSS cleared,
        banks 2-3 writable, SP at STACK_TOP, interrupts off, the CSE map
        and B = CSE_BP with A X Y Z as the stub's cold entry leaves them
        (A and X its dispatch index 4, pushed and pulled: the byte stays at
        the stack top), PC at _main; and of the run premise, what RUN
        leaves that the direct-mode snapshot lacks (_run_leaves).
        Return the load address."""
        load_addr = self.place_prg(prg_path, map_path)
        mem, cpu, s = self._mem, self._cpu, self.sym
        stub = s("__STUB_RUN__")
        self._ram[stub:stub + s("__STUB_SIZE__")] = \
            self._ram[s("__STUB_LOAD__"):s("__STUB_LOAD__") + s("__STUB_SIZE__")]
        self._ram[CSE_BP << 8:(CSE_BP << 8) + BP_CLEARED] = bytes(BP_CLEARED)
        self.write_word(CSE_BP << 8 | s("stub_cold_target"), s("_main"))
        mem.rom_protect = False
        for load, run, size in [
                (s("__CODE_LOAD__"), s("__CODE_RUN__"),
                 s("__CODE_SIZE__") + s("__RODATA_SIZE__")),
                (s("__KDATA_LOAD__"), s("__KDATA_RUN__"), s("__KDATA_SIZE__"))]:
            mem.load(flat(BANK_CSE, run), bytes(self._ram[load:load + size]))
        mem.load(flat(BANK_CSE, s("__BSS_RUN__")), bytes(s("__BSS_SIZE__")))
        cpu.sp = 0x0100 | STACK_TOP
        cpu.p |= 0x04
        cpu.mapl, cpu.maph = CSE_MAP
        _, x, y, z = MAP_CSE
        self._ram[0x0100 | STACK_TOP] = STUB_COLD_INDEX
        self._run_leaves()
        cpu.a, cpu.x, cpu.y, cpu.z, cpu.b = STUB_COLD_INDEX, STUB_COLD_INDEX, y, z, CSE_BP
        cpu.pc = s("_main")
        return load_addr

    def cell(self, name):
        """The CPU address, under the CSE map, of a CSE variable: a
        base-page symbol is in 0.1F00, the rest in the data window."""
        v = self.sym(name)
        return CSE_BP << 8 | v if v < 0x100 else v

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

    # ── the virtual drive's hooks (iec_drive.IECBus) ─────────────

    def _kernal_byte(self, addr):
        """The KERNAL's byte at `addr` as the CPU sees it (the jump
        table at `$FF00`: both maps put the KERNAL at `$E000`)."""
        return self._mem[addr]

    def _iec_slow_device(self):
        """The KERNAL's LISTEN / TALK note whether the device answered
        the fast-serial handshake in `$A2` bit 7 (1: slow — `2.CC0C`
        clears and sets it, both ROMs); `LOAD` takes its byte-by-byte
        path only for a slow device (`BBS7 $A2`) and otherwise the fast
        loader.  A 1541 is slow, so the drive leaves the bit set."""
        self._mem[IEC_FLAGS] |= 0x80


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
