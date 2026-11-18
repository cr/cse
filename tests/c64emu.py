"""c64emu.py — Minimal C64 emulator for the CSE test harness.

Owner: doc/build_system.md

Contract source: [doc/testing.md § C64Emu](../doc/testing.md#c64emu--emulator-class).

Wraps py65 with:
  - Original C64 KERNAL ROM at $E000–$FFFF (ROM overlay)
  - Bank-switching via $01 processor port (bit 1 = KERNAL)
  - Screen RAM at $0400, color RAM at $D800
  - KERNAL ZP state (cursor, line pointers, keyboard buffer)
  - Unified jsr() run loop with cycle-limit timeout

Usage:
    emu = C64Emu()
    emu.load_prg("build/cse.prg")
    emu.jsr(emu.sym("_asm_line_core"), a=0x42)
    assert emu.a == expected
"""

import pathlib
from py65.devices.mpu6502 import MPU

from emu_base import EmuBase, KeyMatrix, register

_ROM_DIR     = pathlib.Path(__file__).parent.parent / "rom"
_ROM_KERNAL  = _ROM_DIR / "kernal_cbm.bin"
_ROM_BASIC   = _ROM_DIR / "basic_cbm.bin"
_ROM_CHARGEN = _ROM_DIR / "chargen_cbm.bin"


# C64 memory layout constants
SCREEN     = 0x0400
SCREEN_END = 0x07E8   # 1000 bytes
COLOR_RAM  = 0xD800
COLOR_END  = 0xDBE8
COLS       = 40
ROWS       = 25

# KERNAL ZP / page-2 / page-3 locations
CUR_LINE_LO = 0xD1     # current screen line pointer lo
CUR_LINE_HI = 0xD2     # current screen line pointer hi
CUR_COL     = 0xD3     # cursor column
CUR_ROW     = 0xD6     # cursor row
COLOR_LO    = 0xF3     # current color RAM pointer lo
COLOR_HI    = 0xF4     # current color RAM pointer hi
CURSOR_FLAG = 0xCC     # 0 = cursor enabled, 1 = disabled
KBD_BUF     = 0x0277   # keyboard buffer (10 bytes)
KBD_COUNT   = 0xC6     # number of keys in buffer
CHR_COLOR   = 0x0286   # current text colour


class BankedMemory:
    """64 KB address space modelling the C64 6510 CPU port + ROM overlays.

    Banking (via `$01` processor port, with `$00` as DDR):
      bit 0 (LORAM)  — BASIC ROM at $A000-$BFFF when set (also needs HIRAM)
      bit 1 (HIRAM)  — KERNAL ROM at $E000-$FFFF when set
      bit 2 (CHAREN) — I/O at $D000-$DFFF when set, else character ROM

    CSE runtime default: $01 = $36 = 0011 0110 → LORAM=0 (BASIC
    banked out), HIRAM=1 (KERNAL visible), CHAREN=1 (I/O visible).

    Writes always latch all 8 bits of `$01` (bits 3-7 track cassette
    and are inert for CSE).  Reads of `$01` are DDR-gated:
      output bits (DDR[N]=1) → latched value
      input bits  (DDR[N]=0) → external pin state (default $17 =
                                cassette-sense-released floating)

    `$00` writes latch DDR.  Reads return the latched DDR (the CPU
    port register is always readable).

    Character-ROM overlay at $D000-$DFFF is loaded from
    `rom/chargen_cbm.bin` (4 KB × 2 = 4096 B covering just the
    chargen region).  BASIC ROM from `rom/basic_cbm.bin`.  Both
    are optional — if missing, those overlays stay disabled and
    LORAM/CHAREN have no effect.
    """

    __slots__ = (
        'ram',
        'rom_kernal', 'rom_basic', 'rom_chargen',
        'loram', 'hiram', 'charen',
        'external_01',
        'keys',                    # KeyMatrix: the held keys
        'cia2_nmi_latch',          # bit 4 of $DD0D — RESTORE-key latch
    )

    # External pin state for input bits on $01 (bits configured as
    # DDR=0).  Default: $17 = bits 0,1,2,4 set — mimics the C64's
    # cassette-sense-no-button / datasette-disconnected state.
    DEFAULT_EXTERNAL_01 = 0x17

    def __init__(self, rom_kernal, rom_basic=None, rom_chargen=None):
        self.ram = [0] * 65536
        self.rom_kernal  = list(rom_kernal)     # 8 KB $E000-$FFFF
        self.rom_basic   = list(rom_basic)   if rom_basic   else None
        self.rom_chargen = list(rom_chargen) if rom_chargen else None
        # Boot default: $01 = $37 (LORAM=HIRAM=CHAREN=1, BASIC + KERNAL + I/O).
        self.loram  = True
        self.hiram  = True
        self.charen = True
        self.external_01 = self.DEFAULT_EXTERNAL_01
        self.keys = KeyMatrix()         # set via C64Emu.press_key
        self.cia2_nmi_latch = 0         # set when RESTORE triggers NMI

    def __len__(self):
        return 65536

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(65536)
            return [self._read(i) for i in range(start, stop, step or 1)]
        return self._read(key)

    def _read(self, addr):
        # KERNAL ROM overlay (HIRAM)
        if 0xE000 <= addr <= 0xFFFF and self.hiram:
            return self.rom_kernal[addr - 0xE000]
        # BASIC ROM overlay (LORAM + HIRAM both required)
        if 0xA000 <= addr <= 0xBFFF and self.loram and self.hiram and self.rom_basic:
            return self.rom_basic[addr - 0xA000]
        # Character ROM overlay ($D000-$DFFF when CHAREN=0 and HIRAM=1)
        if 0xD000 <= addr <= 0xDFFF and self.hiram and not self.charen and self.rom_chargen:
            return self.rom_chargen[addr - 0xD000]
        # CIA1 keyboard matrix read ($DC01 returns row bits for
        # the column mask written to $DC00; pressed keys = 0 bits,
        # unpressed = 1).  Only modelled when I/O is actually visible
        # (HIRAM=1 and CHAREN=1).
        if addr == 0xDC01 and self.hiram and self.charen:
            return self.keys.rows(self.ram[0xDC00])
        # CIA2 ICR read — bit 4 = RESTORE-latched NMI.  Reading ICR
        # clears all latched bits (real-hardware semantics).
        if addr == 0xDD0D and self.hiram and self.charen:
            val = self.cia2_nmi_latch
            self.cia2_nmi_latch = 0
            return val
        # CIA2 port A: the serial (IEC) bus with no device attached.
        # The open-collector lines are pulled high unless the C64
        # itself pulls them low through its inverting drivers, so
        # CLK IN (bit 6) = NOT CLK OUT (bit 4) and DATA IN (bit 7) =
        # NOT DATA OUT (bit 5).  The KERNAL's serial routines then
        # see "device not present" (ST = $80, error 5) at once.
        if addr == 0xDD00 and self.hiram and self.charen:
            val = self.ram[0xDD00]
            return (val & 0x3F) | ((~val << 2) & 0xC0)
        # DDR-gated $01 read: output bits return latched, input bits
        # return external pin state.
        if addr == 0x01:
            ddr     = self.ram[0x00]
            latched = self.ram[0x01]
            return ((latched & ddr) | (self.external_01 & (ddr ^ 0xFF))) & 0xFF
        return self.ram[addr]

    def __setitem__(self, key, val):
        if isinstance(key, slice):
            start, stop, step = key.indices(65536)
            indices = range(start, stop, step or 1)
            if hasattr(val, '__len__'):
                for i, v in zip(indices, val):
                    self._write(i, v)
            else:
                for i in indices:
                    self._write(i, val)
            return
        self._write(key, val)

    def _write(self, addr, val):
        if addr == 0x01:
            # Update banking latches from output-bit writes.  Input
            # bits (DDR=0) still latch (the bit in the register is
            # written) but don't drive the pin.  For simplicity we
            # let all three banking bits reflect the latched state —
            # CSE never configures any banking bit as input.
            self.loram  = bool(val & 0x01)
            self.hiram  = bool(val & 0x02)
            self.charen = bool(val & 0x04)
        self.ram[addr] = val


class C64Emu(EmuBase):
    """Minimal C64 emulator for testing CSE assembly code.  The
    registers, run loops, word access and symbols come from EmuBase."""

    NAME = "C64Emu"

    # Sentinel address — the RTS target for jsr().
    # Placed in I/O area ($D000–$DFFF) which CSE never executes from.
    SENTINEL = 0xDFF0

    def __init__(self, rom_path=None):
        # KERNAL is required.  BASIC and CHARGEN are optional — if
        # missing, LORAM / CHAREN banking simply has no ROM to
        # overlay and those regions stay RAM regardless of $01 state.
        kernal_path = pathlib.Path(rom_path) if rom_path else _ROM_KERNAL
        kernal_data = kernal_path.read_bytes()
        assert len(kernal_data) == 8192, \
            f"KERNAL ROM must be 8192 bytes, got {len(kernal_data)}"

        basic_data   = _ROM_BASIC.read_bytes()   if _ROM_BASIC.exists()   else None
        chargen_data = _ROM_CHARGEN.read_bytes() if _ROM_CHARGEN.exists() else None
        if basic_data is not None:
            assert len(basic_data) == 8192, \
                f"BASIC ROM must be 8192 bytes, got {len(basic_data)}"
        if chargen_data is not None:
            assert len(chargen_data) == 4096, \
                f"CHARGEN ROM must be 4096 bytes, got {len(chargen_data)}"

        mem = BankedMemory(kernal_data, basic_data, chargen_data)
        cpu = MPU()
        cpu.memory = mem
        EmuBase.__init__(self, cpu, mem)
        self._keys = mem.keys            # the held keys
        self._ram = mem.ram              # load_prg() writes RAM under any ROM

        # -- processor port --
        # CSE runtime default: $01 = $36 = 0011 0110 → LORAM=0
        # (BASIC banked OUT so $A000-$BFFF is RAM workspace),
        # HIRAM=1 (KERNAL in), CHAREN=1 (I/O in).  Matches what CSE
        # cold-init sets; tests that jump to CSE functions without
        # running cold-init still see the runtime banking.  Tests
        # that need BASIC (or RAM under KERNAL) can write to $01
        # explicitly.
        self._mem.ram[0x00] = 0x2F       # DDR: default C64 mask
        self._mem.ram[0x01] = 0x36       # CSE runtime default
        self._mem.loram  = False         # BASIC out
        self._mem.hiram  = True          # KERNAL in
        self._mem.charen = True          # I/O visible

        # -- screen + color RAM --
        for i in range(SCREEN, SCREEN_END):
            self._mem.ram[i] = 0x20      # space screen code
        for i in range(COLOR_RAM, COLOR_END):
            self._mem.ram[i] = 0x01      # white

        # -- KERNAL ZP state --
        self._mem.ram[CUR_COL] = 0
        self._mem.ram[CUR_ROW] = 0
        self._set_line_ptrs(0)
        self._mem.ram[CURSOR_FLAG] = 1   # cursor disabled (CSE convention)
        self._mem.ram[KBD_COUNT] = 0
        self._mem.ram[CHR_COLOR] = 0x01  # white text

        # -- screen editor state --
        # HIBASE: screen memory page (high byte of $0400)
        self._mem.ram[0x0288] = (SCREEN >> 8) & 0xFF
        # Screen line link table at $D9–$F1 (25 entries).
        # Each entry: high byte of screen line address (bits 1:0)
        # with bit 7 set = "start of new logical line" (no wrap).
        # The KERNAL PLOT subroutine reads this table to compute
        # screen line addresses and detect line wrapping.
        for row in range(ROWS):
            addr = SCREEN + row * COLS
            hi = (addr >> 8) & 0xFF
            self._mem.ram[0xD9 + row] = hi | 0x80  # bit 7 = no wrap

        # -- page-3 I/O vectors --
        # Run RESTOR ($FF8A) in a temporary CPU to populate the
        # default I/O vectors at $0314–$0333.
        self._init_kernal_vectors(kernal_data)

        # -- stack --
        self._cpu.sp = 0xFF

        # -- the serial bus: empty until attach_drive() --
        self._bus = None

    def _set_line_ptrs(self, row):
        """Set KERNAL screen/color line pointers for the given row."""
        scr = SCREEN + row * COLS
        col = COLOR_RAM + row * COLS
        self._mem.ram[CUR_LINE_LO] = scr & 0xFF
        self._mem.ram[CUR_LINE_HI] = (scr >> 8) & 0xFF
        self._mem.ram[COLOR_LO] = col & 0xFF
        self._mem.ram[COLOR_HI] = (col >> 8) & 0xFF

    def _init_kernal_vectors(self, rom_data):
        """Populate page-3 I/O vectors ($0314–$0333) by running
        KERNAL RESTOR ($FF8A) in a temporary CPU.  RESTOR is a pure
        memory copy — no hardware access."""
        tmp = MPU()
        tmp.memory = [0] * 65536
        tmp.memory[0xE000:0x10000] = list(rom_data)
        sentinel = self.SENTINEL
        tmp.memory[sentinel] = 0x00
        tmp.sp = 0xFF
        tmp.memory[0x01FF] = ((sentinel - 1) >> 8) & 0xFF
        tmp.memory[0x01FE] = (sentinel - 1) & 0xFF
        tmp.sp = 0xFD
        tmp.pc = 0xFF8A
        for _ in range(500):
            if tmp.pc == sentinel:
                break
            tmp.step()
        for addr in range(0x0314, 0x0334):
            val = tmp.memory[addr]
            if val != 0:
                self._mem.ram[addr] = val

    sp = register("sp", 0xFF)        # the other registers: EmuBase

    # ── Interrupts (the scheduler: EmuBase) ─────────────────────

    def _enter_irq(self):
        if self._cpu.p & self._cpu.INTERRUPT:
            return False
        self._fire_interrupt("irq")
        return True

    def _enter_nmi(self):
        self._fire_interrupt("nmi")
        return True

    def _fire_interrupt(self, kind):
        """Synthesise the CPU's IRQ/NMI entry: push PCH, PCL, P, set I,
        fetch the vector through BankedMemory, jump."""
        pc = self._cpu.pc
        self._mem.ram[0x0100 + self._cpu.sp] = (pc >> 8) & 0xFF
        self._cpu.sp = (self._cpu.sp - 1) & 0xFF
        self._mem.ram[0x0100 + self._cpu.sp] = pc & 0xFF
        self._cpu.sp = (self._cpu.sp - 1) & 0xFF
        # Clear B in pushed P (IRQ and NMI both push P with B=0).
        self._mem.ram[0x0100 + self._cpu.sp] = self._cpu.p & 0xEF
        self._cpu.sp = (self._cpu.sp - 1) & 0xFF
        # Set I to mask further IRQs.
        self._cpu.p |= self._cpu.INTERRUPT
        vec_addr = 0xFFFA if kind == 'nmi' else 0xFFFE
        lo = self._mem[vec_addr]
        hi = self._mem[vec_addr + 1]
        self._cpu.pc = (hi << 8) | lo

    # ── Execution (the loops: EmuBase) ──────────────────────────

    def _push_return(self, ret):
        """jsr(): a fresh stack holding `ret`; a NOP marks the sentinel."""
        self._mem.ram[self.SENTINEL] = 0xEA
        self._mem.ram[0x01FF] = (ret >> 8) & 0xFF
        self._mem.ram[0x01FE] = ret & 0xFF
        self._cpu.sp = 0xFD

    # ── Keyboard (the calls: EmuBase) ───────────────────────────

    def _latch_restore(self):
        self._mem.cia2_nmi_latch |= 0x10

    def _queue_key(self, petscii):
        """Into the KERNAL keyboard buffer ($0277, count in $C6)."""
        count = self._mem.ram[KBD_COUNT]
        if count >= 10:
            raise OverflowError("Keyboard buffer full (10 keys)")
        self._mem.ram[KBD_BUF + count] = petscii
        self._mem.ram[KBD_COUNT] = count + 1

    # ── Helpers ─────────────────────────────────────────────────

    def screen_row(self, row):
        """Read screen codes for one row (40 bytes) as a list."""
        base = SCREEN + row * COLS
        return [self._mem[base + c] for c in range(COLS)]

    # ── Virtual IEC drives ──────────────────────────────────────

    def attach_drive(self, device=8, drive=None):
        """Put a drive (a fresh `Drive1541` unless one is given) on
        the serial bus as `device` (8-11); return it.  The first
        drive installs the bus traps (`IECBus`)."""
        if not 8 <= device <= 11:
            raise ValueError(f"device {device}: a 1541 answers as 8-11")
        if self._bus is None:
            self._bus = IECBus(self)
        drive = drive if drive is not None else Drive1541()
        self._bus.drives[device] = drive
        return drive

    def detach_drive(self, device):
        """Take a drive off the bus; with the last one gone the bus is
        empty again (the `$DD00` model, no traps)."""
        if self._bus is None:
            return
        self._bus.drives.pop(device, None)
        if not self._bus.drives:
            self._bus.remove()
            self._bus = None

    def drive(self, device=8):
        """The drive attached as `device`."""
        return self._bus.drives[device]

    def _rts(self):
        """Return from the routine PC is in, as its RTS would."""
        sp = self._cpu.sp
        lo = self._mem.ram[0x0100 + ((sp + 1) & 0xFF)]
        hi = self._mem.ram[0x0100 + ((sp + 2) & 0xFF)]
        self._cpu.sp = (sp + 2) & 0xFF
        self._cpu.pc = (((hi << 8) | lo) + 1) & 0xFFFF


# ═══════════════════════════════════════════════════════════════
# The virtual IEC drive (testing.md § C64Emu, Virtual IEC drives)
# ═══════════════════════════════════════════════════════════════

ST = 0x90                       # KERNAL I/O status byte
ST_TIMEOUT_READ = 0x02
ST_EOI = 0x40
ST_DEVICE_NOT_PRESENT = 0x80

BLOCKS_TOTAL = 664              # a formatted 1541 disk
DIR_LOAD_ADDR = 0x0401          # the "$" file's load address

_DOS_MESSAGES = {
    0: " OK", 1: "FILES SCRATCHED", 26: "WRITE PROTECT ON",
    30: "SYNTAX ERROR", 31: "SYNTAX ERROR", 33: "SYNTAX ERROR",
    34: "SYNTAX ERROR", 61: "FILE NOT OPEN", 62: "FILE NOT FOUND",
    63: "FILE EXISTS", 64: "FILE TYPE MISMATCH", 72: "DISK FULL",
    73: "CBM DOS V2.6 1541",
}
_TYPE_LETTERS = {0x53: "SEQ", 0x50: "PRG", 0x55: "USR", 0x4C: "REL"}
_MODE_LETTERS = {0x52: "R", 0x57: "W", 0x41: "A", 0x4D: "M"}
_D64_TYPES = {0: "DEL", 1: "SEQ", 2: "PRG", 3: "USR", 4: "REL"}


def _name_bytes(name):
    """A file name as PETSCII bytes (a str is taken byte for byte)."""
    return name.encode("latin-1") if isinstance(name, str) else bytes(name)


def cbm_blocks(size):
    """Blocks a file of `size` bytes takes (254 data bytes each; an
    empty file still takes one)."""
    return max(1, -(-size // 254))


def cbm_match(pattern, name):
    """CBM DOS name matching: `?` matches any one byte, `*` the rest."""
    for i, c in enumerate(pattern):
        if c == 0x2A:
            return True
        if i >= len(name) or (c != 0x3F and c != name[i]):
            return False
    return len(pattern) == len(name)


class DiskFile:
    """One directory entry: name (PETSCII bytes), type, data."""

    def __init__(self, name, data=b"", type="PRG", locked=False):
        self.name = _name_bytes(name)
        self.data = bytes(data)
        self.type = type
        self.locked = locked

    @property
    def blocks(self):
        return cbm_blocks(len(self.data))


class _Channel:
    """An open data channel: a read cursor or a write buffer."""

    def __init__(self, mode, data=b"", name=None, type=None, replace=None):
        self.mode = mode            # "R" or "W"
        self.data = bytearray(data)
        self.pos = 0
        self.name = name            # W: the file to commit on close
        self.type = type
        self.replace = replace      # W: the entry it replaces, or None


class Drive1541:
    """An in-memory 1541: a directory of named files and the DOS seen
    from the bus — channels 0-14 for files, 15 for commands and the
    status.  No disk geometry, no timing."""

    def __init__(self, disk_name=b"CSE TEST", disk_id=b"01"):
        self.disk_name = _name_bytes(disk_name)
        self.disk_id = _name_bytes(disk_id)
        self.files = []             # DiskFile, in directory order
        self.write_protect = False
        self._channels = {}
        self._cmd = bytearray()
        self.set_status(73)         # the power-on message

    # ── the host side (what a test sets up and checks) ──

    def put(self, name, data, type="PRG"):
        """Write a file straight onto the disk (replacing one of the
        same name); return its entry."""
        entry = DiskFile(name, data, type)
        old = self.find(entry.name)
        if old is not None:
            self.files[self.files.index(old)] = entry
        else:
            self.files.append(entry)
        return entry

    def find(self, name):
        """The first entry matching `name` (CBM wildcards), or None."""
        name = _name_bytes(name)
        return next((f for f in self.files if cbm_match(name, f.name)), None)

    def get(self, name):
        """The data of file `name`; KeyError if the disk has none."""
        entry = self.find(name)
        if entry is None:
            raise KeyError(f"no file {name!r} on the disk")
        return entry.data

    def names(self):
        return [f.name for f in self.files]

    @property
    def blocks_free(self):
        return BLOCKS_TOTAL - sum(f.blocks for f in self.files)

    @property
    def status(self):
        """The error channel's message, as the drive would send it."""
        return self._status.decode("latin-1")

    def set_status(self, code, track=0, sector=0):
        self._status = (f"{code:02d},{_DOS_MESSAGES[code]},"
                        f"{track:02d},{sector:02d}").encode("latin-1")
        self._status_pos = 0

    # ── the DOS (what the bus calls) ──

    def open(self, ch, name):
        """OPEN on channel `ch` with the name sent under it."""
        name = bytes(name)
        if ch == 15:
            if name:
                self._command(name)
            return
        self._channels.pop(ch, None)
        if name[:1] == b"$":
            self._channels[ch] = _Channel("R", self.directory(name[1:]))
            self.set_status(0)
            return
        replace = name[:1] == b"@"
        if replace:
            name = name[1:]
        if b":" in name:
            drv, _, rest = name.partition(b":")
            if drv.isdigit() or not drv:
                name = rest
        fname, *params = name.split(b",")
        ftype = mode = None
        for p in params:
            if p[:1] and p[0] in _TYPE_LETTERS and ftype is None and mode is None:
                ftype = _TYPE_LETTERS[p[0]]
            elif p[:1] and p[0] in _MODE_LETTERS:
                mode = _MODE_LETTERS[p[0]]
            else:
                return self.set_status(30)
        if mode is None:
            mode = "W" if ch == 1 else "R"
        if not fname:
            return self.set_status(34)
        if mode == "R":
            entry = self.find(fname)
            if entry is None:
                return self.set_status(62)
            if ftype is not None and entry.type != ftype:
                return self.set_status(64)
            self._channels[ch] = _Channel("R", entry.data)
            return self.set_status(0)
        if mode not in ("W", "A"):
            return self.set_status(31)
        if b"*" in fname or b"?" in fname:
            return self.set_status(33)
        if self.write_protect:
            return self.set_status(26)
        entry = self.find(fname)
        if mode == "A":
            if entry is None:
                return self.set_status(62)
            self._channels[ch] = _Channel("W", entry.data, entry.name,
                                          entry.type, entry)
            return self.set_status(0)
        if entry is not None and not replace:
            return self.set_status(63)
        ftype = ftype or ("PRG" if ch == 1 else "SEQ")
        self._channels[ch] = _Channel("W", b"", fname, ftype, entry)
        self.set_status(0)

    def close(self, ch):
        """CLOSE: a written file is committed now.  Closing channel 15
        closes every channel."""
        for c in (list(self._channels) if ch == 15 else [ch]):
            chan = self._channels.pop(c, None)
            if chan is None or chan.mode != "W":
                continue
            entry = DiskFile(chan.name, chan.data, chan.type)
            used = sum(f.blocks for f in self.files if f is not chan.replace)
            if used + entry.blocks > BLOCKS_TOTAL:
                self.set_status(72)
                continue
            if chan.replace in self.files:
                self.files[self.files.index(chan.replace)] = entry
            else:
                self.files.append(entry)

    def write(self, ch, byte):
        """One byte LISTENed to channel `ch`."""
        if ch == 15:
            self._cmd.append(byte)
            return
        chan = self._channels.get(ch)
        if chan is not None and chan.mode == "W":
            chan.data.append(byte)

    def unlisten(self, ch):
        """The end of a LISTEN to `ch`: a command on 15 runs now."""
        if ch == 15 and self._cmd:
            cmd, self._cmd = bytes(self._cmd), bytearray()
            self._command(cmd)

    def read(self, ch):
        """The next byte TALKed from channel `ch` as (byte, eoi), or
        None when the channel has nothing to send."""
        if ch == 15:
            msg = self._status + b"\r"
            byte = msg[self._status_pos]
            self._status_pos += 1
            if self._status_pos < len(msg):
                return byte, False
            self.set_status(0)          # read out: the error clears
            return byte, True
        chan = self._channels.get(ch)
        if chan is None or chan.mode != "R" or chan.pos >= len(chan.data):
            return None
        byte = chan.data[chan.pos]
        chan.pos += 1
        return byte, chan.pos == len(chan.data)

    def _command(self, cmd):
        cmd = cmd.rstrip(b"\r")
        op = cmd[:1]
        arg = cmd.partition(b":")[2]
        if op == b"S":
            if self.write_protect:
                return self.set_status(26)
            pats = [p for p in arg.split(b",") if p]
            if not pats:
                return self.set_status(34)
            gone = [f for f in self.files if not f.locked
                    and any(cbm_match(p, f.name) for p in pats)]
            self.files = [f for f in self.files if f not in gone]
            return self.set_status(1, len(gone))
        if op == b"R":
            new, _, old = arg.partition(b"=")
            old = old.partition(b":")[2] if b":" in old else old
            if not new or not old:
                return self.set_status(34)
            if self.write_protect:
                return self.set_status(26)
            if self.find(new) is not None:
                return self.set_status(63)
            entry = self.find(old)
            if entry is None:
                return self.set_status(62)
            entry.name = bytes(new)
            return self.set_status(0)
        if op == b"N":
            if self.write_protect:
                return self.set_status(26)
            dname, _, did = arg.partition(b",")
            if not dname:
                return self.set_status(34)
            self.disk_name = dname
            if did:
                self.disk_id = did[:2]
            self.files = []
            return self.set_status(0)
        if op in (b"I", b"V"):
            return self.set_status(0)
        if cmd in (b"UJ", b"U:"):
            self._channels.clear()
            return self.set_status(73)
        return self.set_status(31)

    # ── the directory, as the "$" file ──

    def directory(self, spec=b""):
        """The "$" file, as a 1541 sends it: a BASIC program loading at
        $0401 — the header line (drive 0: the disk name in reverse,
        padded with shifted spaces, the ID and "2A"), one line per file
        (blocks; name in quotes; type, `<` if locked),
        and "BLOCKS FREE.".  `spec` (after the "$"): an optional drive
        digit and ":pattern"."""
        pattern = spec.partition(b":")[2] if b":" in spec else b"*"
        out = bytearray(DIR_LOAD_ADDR.to_bytes(2, "little"))

        def line(number, text):
            out.extend(b"\x01\x01" + number.to_bytes(2, "little") + text + b"\x00")

        name16 = self.disk_name[:16].ljust(16, b"\xa0")
        line(0, b"\x12\"" + name16 + b"\" " + self.disk_id[:2].ljust(2, b"\xa0")
             + b"\xa02A")
        for f in self.files:
            if not cbm_match(pattern, f.name):
                continue
            b = f.blocks
            lead = b" " * (3 if b < 10 else 2 if b < 100 else 1 if b < 1000 else 0)
            text = (lead + b"\"" + f.name + b"\"" + b" " * (16 - len(f.name))
                    + b" " + f.type.encode() + (b"<" if f.locked else b" "))
            line(b, text.ljust(27, b" "))
        line(max(self.blocks_free, 0), b"BLOCKS FREE.".ljust(25, b" "))
        out.extend(b"\x00\x00")
        return bytes(out)

    # ── a D64 image ──

    @classmethod
    def from_d64(cls, path):
        """A drive holding the files of a 35-track .d64 image (read
        once; nothing is written back)."""
        img = pathlib.Path(path).read_bytes()

        def sector(t, s):
            spt = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
            off = (sum(spt[:t - 1]) + s) * 256
            return img[off:off + 256]

        bam = sector(18, 0)
        drive = cls(bam[0x90:0xA0].rstrip(b"\xa0"), bam[0xA2:0xA4])
        t, s, seen = 18, 1, set()
        while t and (t, s) not in seen:
            seen.add((t, s))
            sec = sector(t, s)
            for i in range(8):
                e = sec[i * 32:i * 32 + 32]
                kind = e[2] & 0x07
                if not e[2] & 0x80 or kind not in _D64_TYPES or kind == 0:
                    continue            # empty, unclosed or deleted
                data, ft, fs, chain = bytearray(), e[3], e[4], set()
                while ft and (ft, fs) not in chain:
                    chain.add((ft, fs))
                    blk = sector(ft, fs)
                    ft, fs = blk[0], blk[1]
                    data += blk[2:fs + 1] if ft == 0 else blk[2:]
                entry = DiskFile(e[5:21].rstrip(b"\xa0"), data, _D64_TYPES[kind],
                                 locked=bool(e[2] & 0x40))
                drive.files.append(entry)
            t, s = sec[0], sec[1]
        return drive


class IECBus:
    """The serial bus with drives on it.  Traps on the KERNAL's own
    serial routines (TALK, LISTEN, SECOND, TKSA, CIOUT, ACPTR, UNTLK,
    UNLSN — at the addresses the KERNAL's jump table names) carry each
    byte to and from the addressed drive, so OPEN, CLOSE, CHKIN,
    CHKOUT, CHRIN, CHROUT, CLRCHN, LOAD and SAVE run the KERNAL's own
    code above them.  A device with no drive leaves ST = $80 (device
    not present)."""

    _JUMP_TABLE = {"talk": 0xFFB4, "listen": 0xFFB1, "second": 0xFF93,
                   "tksa": 0xFF96, "ciout": 0xFFA8, "acptr": 0xFFA5,
                   "untlk": 0xFFAB, "unlsn": 0xFFAE}

    def __init__(self, emu):
        self.emu = emu
        self.drives = {}
        self._listener = self._talker = None
        self._listen_ch = self._talk_ch = None
        self._opening = False
        self._name = bytearray()
        rom = emu._mem.rom_kernal
        self._addrs = []
        for routine, vec in self._JUMP_TABLE.items():
            assert rom[vec - 0xE000] == 0x4C, f"no JMP at ${vec:04X}"
            addr = rom[vec + 1 - 0xE000] | rom[vec + 2 - 0xE000] << 8
            handler = getattr(self, "_" + routine)
            emu.add_trap(addr, lambda e, h=handler: self._serve(h))
            self._addrs.append(addr)

    def remove(self):
        for addr in self._addrs:
            self.emu.remove_trap(addr)

    def _serve(self, handler):
        handler(self.emu)
        self.emu.carry = False
        self.emu._rts()

    def _st(self, bits):
        self.emu.memory[ST] = self.emu.memory[ST] | bits

    def _address(self, dev):
        drive = self.drives.get(dev & 0x1F)
        if drive is None:
            self._st(ST_DEVICE_NOT_PRESENT)
        return drive

    def _talk(self, emu):
        self._talker, self._talk_ch = self._address(emu.a), None

    def _listen(self, emu):
        self._listener, self._listen_ch = self._address(emu.a), None
        self._opening = False

    def _second(self, emu):
        if self._listener is None:
            return
        cmd, ch = emu.a & 0xF0, emu.a & 0x0F
        self._listen_ch = ch
        self._opening = cmd == 0xF0
        self._name = bytearray()
        if cmd == 0xE0:
            self._listener.close(ch)
            self._listen_ch = None

    def _tksa(self, emu):
        if self._talker is not None:
            self._talk_ch = emu.a & 0x0F

    def _ciout(self, emu):
        if self._listener is None or self._listen_ch is None:
            return
        if self._opening:
            self._name.append(emu.a)
        else:
            self._listener.write(self._listen_ch, emu.a)

    def _unlsn(self, emu):
        drive, ch = self._listener, self._listen_ch
        if drive is not None and ch is not None:
            if self._opening:
                drive.open(ch, self._name)
            else:
                drive.unlisten(ch)
        self._listener = self._listen_ch = None
        self._opening = False

    def _acptr(self, emu):
        got = None
        if self._talker is not None and self._talk_ch is not None:
            got = self._talker.read(self._talk_ch)
        if got is None:                 # nobody sends: the read times out
            byte = 0x0D
            self._st(ST_EOI | ST_TIMEOUT_READ)
        else:
            byte, eoi = got
            if eoi:
                self._st(ST_EOI)
        emu.a = byte
        p = emu.p & ~(emu.cpu.ZERO | emu.cpu.NEGATIVE)
        emu.p = p | (emu.cpu.ZERO if byte == 0 else 0) | (byte & 0x80)

    def _untlk(self, emu):
        self._talker = self._talk_ch = None
