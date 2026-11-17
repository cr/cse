"""
c64emu.py — Minimal C64 emulator for the CSE test harness.

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

from emu_base import EmuBase, KeyMatrix, decode_screen_codes

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

    # ── Register accessors (the rest: EmuBase) ──────────────────

    @property
    def sp(self):
        return self._cpu.sp

    @sp.setter
    def sp(self, val):
        self._cpu.sp = val & 0xFF

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

    @property
    def _keys(self):
        return self._mem.keys

    def _latch_restore(self):
        self._mem.cia2_nmi_latch |= 0x10

    def _queue_key(self, petscii):
        """Into the KERNAL keyboard buffer ($0277, count in $C6)."""
        count = self._mem.ram[KBD_COUNT]
        if count >= 10:
            raise OverflowError("Keyboard buffer full (10 keys)")
        self._mem.ram[KBD_BUF + count] = petscii
        self._mem.ram[KBD_COUNT] = count + 1

    @property
    def _ram(self):
        """load_prg() writes RAM under any ROM."""
        return self._mem.ram

    # ── Helpers ─────────────────────────────────────────────────

    def screen_row(self, row):
        """Read screen codes for one row (40 bytes) as a list."""
        base = SCREEN + row * COLS
        return [self._mem[base + c] for c in range(COLS)]

    def screen_text(self, row):
        """One screen row as text (emu_base.decode_screen_codes)."""
        return decode_screen_codes(self.screen_row(row))
