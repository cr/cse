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

_ROM_DIR     = pathlib.Path(__file__).parent.parent / "rom"
_ROM_KERNAL  = _ROM_DIR / "kernal_cbm.bin"
_ROM_BASIC   = _ROM_DIR / "basic_cbm.bin"
_ROM_CHARGEN = _ROM_DIR / "chargen_cbm.bin"


# ── Keyboard matrix (PETSCII → (row, col)) ───────────────────────
#
# C64 keyboard is scanned as an 8×8 matrix via CIA1 $DC00/$DC01.
# This table covers the keys most tests care about: letters, digits,
# common punctuation, RETURN, SPACE, STOP.  Lowercase PETSCII maps
# to the same matrix cell as uppercase.
_KEY_MATRIX = {
    # Control keys
    0x0D: (0, 1),    # RETURN
    0x20: (7, 4),    # SPACE
    0x03: (7, 7),    # STOP
    # Digits (row 7 alternates 1/2, then row 1 for 3/4 etc.)
    0x31: (7, 0), 0x32: (7, 3), 0x33: (1, 0), 0x34: (1, 3),
    0x35: (2, 0), 0x36: (2, 3), 0x37: (3, 0), 0x38: (3, 3),
    0x39: (4, 0), 0x30: (4, 3),
    # Letters
    0x41: (1, 2), 0x42: (3, 4), 0x43: (2, 4), 0x44: (2, 2),
    0x45: (1, 6), 0x46: (2, 5), 0x47: (3, 2), 0x48: (3, 5),
    0x49: (4, 1), 0x4A: (4, 2), 0x4B: (4, 5), 0x4C: (5, 2),
    0x4D: (4, 4), 0x4E: (4, 7), 0x4F: (4, 6), 0x50: (5, 1),
    0x51: (7, 6), 0x52: (2, 1), 0x53: (1, 5), 0x54: (2, 6),
    0x55: (3, 6), 0x56: (3, 7), 0x57: (1, 1), 0x58: (2, 7),
    0x59: (3, 1), 0x5A: (1, 4),
    # Common punctuation
    0x2C: (5, 7), 0x2E: (5, 4), 0x2F: (6, 7), 0x3A: (5, 5),
    0x3B: (6, 2), 0x3D: (6, 5), 0x2B: (5, 0), 0x2D: (5, 3),
    0x2A: (6, 1), 0x40: (5, 6),
}


def _petscii_to_matrix(ch):
    """Resolve a PETSCII char (int or 1-char str) to (row, col)."""
    if isinstance(ch, str):
        if len(ch) != 1:
            raise ValueError(f"press/release_key expects single char, got {ch!r}")
        ch = ord(ch)
    # Lowercase ($61-$7A) → uppercase ($41-$5A).
    if 0x61 <= ch <= 0x7A:
        ch -= 0x20
    # Shifted uppercase ($C1-$DA) → plain uppercase.
    if 0xC1 <= ch <= 0xDA:
        ch -= 0x80
    if ch not in _KEY_MATRIX:
        raise KeyError(f"no matrix mapping for PETSCII ${ch:02X}")
    return _KEY_MATRIX[ch]

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
        'keyboard_pressed',        # set of (row, col) currently depressed
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
        self.keyboard_pressed = set()   # populated via C64Emu.press_key
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
            return self._read_keyboard_rows()
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

    def _read_keyboard_rows(self):
        """Return $DC01 row-bit value based on current column mask at
        $DC00 and the set of pressed keys.  Pressed → 0, unpressed → 1."""
        col_mask = self.ram[0xDC00]
        rows = 0xFF
        for r, c in self.keyboard_pressed:
            if ((col_mask >> c) & 1) == 0:   # column selected (0)
                rows &= ~(1 << r) & 0xFF
        return rows

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


class C64Emu:
    """Minimal C64 emulator for testing CSE assembly code."""

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

        self._mem = BankedMemory(kernal_data, basic_data, chargen_data)
        self._cpu = MPU()
        self._cpu.memory = self._mem
        self._syms = {}

        # Cycle counter (monotonic across jsr/run_until calls) +
        # pending-interrupt queue for schedule_irq / schedule_nmi.
        # Each entry: (fire_cycle, kind) where kind is 'irq', 'nmi',
        # or 'jiffy' (a self-re-scheduling IRQ used for the KERNAL
        # clock tick).
        self._cycle_total = 0
        self._pending = []
        self._jiffy_interval = 0     # 0 = disabled

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

    # ── Register accessors ──────────────────────────────────────

    @property
    def a(self):
        return self._cpu.a

    @a.setter
    def a(self, val):
        self._cpu.a = val & 0xFF

    @property
    def x(self):
        return self._cpu.x

    @x.setter
    def x(self, val):
        self._cpu.x = val & 0xFF

    @property
    def y(self):
        return self._cpu.y

    @y.setter
    def y(self, val):
        self._cpu.y = val & 0xFF

    @property
    def sp(self):
        return self._cpu.sp

    @sp.setter
    def sp(self, val):
        self._cpu.sp = val & 0xFF

    @property
    def pc(self):
        return self._cpu.pc

    @pc.setter
    def pc(self, val):
        self._cpu.pc = val & 0xFFFF

    @property
    def p(self):
        return self._cpu.p

    @p.setter
    def p(self, val):
        self._cpu.p = val & 0xFF

    @property
    def carry(self):
        return bool(self._cpu.p & self._cpu.CARRY)

    @carry.setter
    def carry(self, val):
        if val:
            self._cpu.p |= self._cpu.CARRY
        else:
            self._cpu.p &= ~self._cpu.CARRY

    @property
    def zero(self):
        return bool(self._cpu.p & self._cpu.ZERO)

    @property
    def negative(self):
        return bool(self._cpu.p & self._cpu.NEGATIVE)

    @property
    def overflow(self):
        return bool(self._cpu.p & self._cpu.OVERFLOW)

    @property
    def memory(self):
        return self._mem

    # ── Scheduled interrupts ────────────────────────────────────
    #
    # The run loops (jsr, run_until) consult a pending-interrupt
    # queue every CPU step.  Each entry fires when the cycle counter
    # reaches its scheduled target.  IRQs honour the I flag (deferred
    # until cleared); NMIs fire unconditionally and are edge-triggered.
    # Vector fetch respects banking ($FFFA/$FFFE read through
    # BankedMemory, so KERNAL-out tests see the RAM-shadow vectors).

    def schedule_irq(self, cycles_from_now):
        """Enqueue an IRQ to fire `cycles_from_now` steps from now.

        IRQs fire only while I=0.  Multiple IRQs at the same cycle
        are coalesced into a single fire (matches real hardware —
        IRQ is level-triggered)."""
        self._pending.append((self._cycle_total + max(cycles_from_now, 0), 'irq'))
        self._pending.sort()

    def schedule_nmi(self, cycles_from_now):
        """Enqueue an NMI to fire `cycles_from_now` steps from now.

        NMIs fire unconditionally (edge-triggered — once per schedule)."""
        self._pending.append((self._cycle_total + max(cycles_from_now, 0), 'nmi'))
        self._pending.sort()

    def cancel_pending_interrupts(self):
        """Drop all queued IRQ/NMI schedules (does not disable jiffy)."""
        self._pending.clear()

    # ── Jiffy clock ─────────────────────────────────────────────
    #
    # On real C64 hardware the KERNAL programs CIA1 Timer A to
    # underflow every ~16400 cycles, triggering an IRQ whose handler
    # (at $EA31) increments the jiffy counter at $A0-$A2 and scans
    # the keyboard.  We simulate this as a repeating IRQ that
    # re-schedules itself after each fire.
    #
    # Opt-in via enable_jiffy_clock() — tests that assume no IRQs
    # are unaffected by default.

    JIFFY_INTERVAL = 16421   # matches KERNAL RAM-init timer value

    def enable_jiffy_clock(self, interval=None):
        """Schedule a repeating IRQ at `interval` cycles apart
        (default: 16421, matching KERNAL's CIA1 Timer A setup).
        Each fire re-schedules the next tick automatically.

        Pair with `init_cse()` + a cleared I flag for KERNAL's IRQ
        handler to pick up and tick $A0-$A2."""
        self._jiffy_interval = interval if interval is not None else self.JIFFY_INTERVAL
        self._pending.append((self._cycle_total + self._jiffy_interval, 'jiffy'))
        self._pending.sort()

    def disable_jiffy_clock(self):
        """Stop the repeating jiffy IRQ.  Existing pending jiffy
        entries are dropped; other scheduled IRQs/NMIs stay."""
        self._jiffy_interval = 0
        self._pending = [(w, k) for w, k in self._pending if k != 'jiffy']

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

    def _dispatch_pending(self):
        """Called after each CPU step: fire any interrupts whose
        scheduled cycle has arrived.  NMI first (higher priority);
        IRQ (including 'jiffy' kind) only when I flag is clear."""
        if not self._pending:
            return
        # Separate due events by kind.
        due_nmi = False
        due_irq_count = 0
        due_jiffy = False
        remaining = []
        for when, kind in self._pending:
            if when <= self._cycle_total:
                if kind == 'nmi':
                    due_nmi = True
                elif kind == 'irq':
                    due_irq_count += 1
                elif kind == 'jiffy':
                    due_jiffy = True
            else:
                remaining.append((when, kind))

        if due_nmi:
            self._fire_interrupt('nmi')
            # Other due events stay pending for the next dispatch tick.
            self._pending = remaining + [
                (self._cycle_total, 'irq')   for _ in range(due_irq_count)
            ] + (
                [(self._cycle_total, 'jiffy')] if due_jiffy else []
            )
            return

        if due_irq_count or due_jiffy:
            if not (self._cpu.p & self._cpu.INTERRUPT):
                self._fire_interrupt('irq')
                # Consume one IRQ event; jiffy re-schedules.
                self._pending = remaining
                if due_jiffy and self._jiffy_interval:
                    self._pending.append(
                        (self._cycle_total + self._jiffy_interval, 'jiffy')
                    )
                    self._pending.sort()
                # Any extra due IRQs roll over to the next step.
                if due_irq_count > 1:
                    self._pending.extend(
                        [(self._cycle_total + 1, 'irq')] * (due_irq_count - 1)
                    )
                    self._pending.sort()
            else:
                # I=1 — requeue all due IRQ/jiffy for re-poll next step.
                self._pending = remaining
                self._pending.extend(
                    [(self._cycle_total + 1, 'irq')] * due_irq_count
                )
                if due_jiffy:
                    self._pending.append((self._cycle_total + 1, 'jiffy'))
                self._pending.sort()
            return

    # ── Execution ───────────────────────────────────────────────

    def jsr(self, addr, *, a=None, x=None, y=None, carry=None,
            max_cycles=500_000):
        """Simulate JSR to addr.  Returns cycle count.

        Sets up a sentinel return address on the stack so that the
        target routine's RTS halts emulation.  Raises TimeoutError
        if max_cycles is exceeded.
        """
        sentinel = self.SENTINEL
        self._mem.ram[sentinel] = 0xEA  # NOP — marker

        # Push (sentinel - 1) as return address (RTS adds 1)
        self._cpu.sp = 0xFF
        self._mem.ram[0x01FF] = ((sentinel - 1) >> 8) & 0xFF
        self._mem.ram[0x01FE] = (sentinel - 1) & 0xFF
        self._cpu.sp = 0xFD

        if a is not None:
            self._cpu.a = a & 0xFF
        if x is not None:
            self._cpu.x = x & 0xFF
        if y is not None:
            self._cpu.y = y & 0xFF
        if carry is not None:
            self.carry = carry

        self._cpu.pc = addr
        cycles = 0
        while cycles < max_cycles:
            if self._cpu.pc == sentinel:
                return cycles
            self._cpu.step()
            cycles += 1
            self._cycle_total += 1
            if self._pending:
                self._dispatch_pending()

        raise TimeoutError(
            f"C64Emu: timeout after {max_cycles} cycles at "
            f"${self._cpu.pc:04X}"
        )

    # ── Keyboard matrix (CIA1 $DC00/$DC01) ──────────────────────

    def press_key(self, ch):
        """Mark a key as pressed in the CIA1 keyboard matrix.

        Reads of $DC01 with the appropriate $DC00 column mask will
        see the key's row bit cleared.  Multiple keys can be held
        simultaneously.  Use PETSCII char (int) or single-char string.
        """
        row, col = _petscii_to_matrix(ch)
        self._mem.keyboard_pressed.add((row, col))

    def release_key(self, ch):
        """Release a previously-pressed matrix key.  No-op if not held."""
        row, col = _petscii_to_matrix(ch)
        self._mem.keyboard_pressed.discard((row, col))

    def release_all_keys(self):
        """Clear the matrix to all-released."""
        self._mem.keyboard_pressed.clear()

    def press_stop(self):
        """Convenience: press the STOP key (matrix row 7 col 7)."""
        self._mem.keyboard_pressed.add((7, 7))

    def release_stop(self):
        self._mem.keyboard_pressed.discard((7, 7))

    def press_restore(self):
        """Simulate RESTORE key: latches CIA2 ICR bit 4 and schedules
        an NMI.  The RESTORE key on C64 is hard-wired to the NMI line,
        not the keyboard matrix."""
        self._mem.cia2_nmi_latch |= 0x10
        self.schedule_nmi(0)

    # ── KERNAL keyboard buffer injection ────────────────────────

    def inject_key(self, petscii):
        """Enqueue one PETSCII byte into the KERNAL keyboard buffer."""
        count = self._mem.ram[KBD_COUNT]
        if count >= 10:
            raise OverflowError("Keyboard buffer full (10 keys)")
        self._mem.ram[KBD_BUF + count] = petscii & 0xFF
        self._mem.ram[KBD_COUNT] = count + 1

    def inject_keys(self, data):
        """Enqueue multiple PETSCII bytes into the keyboard buffer."""
        for b in data:
            self.inject_key(b)

    # ── PRG loading and symbol resolution ───────────────────────

    def load_prg(self, prg_path, map_path=None):
        """Load a .prg file and optionally parse its .map for symbols.

        The .prg format: 2-byte little-endian load address, then payload.
        Payload is written starting at the load address.
        If map_path is not given, replaces .prg with .map.

        After loading, if the map reveals segments with load != run
        addresses (e.g. CODE relocated to high memory), those segments
        are copied from their load position to their run position,
        mirroring what the loader.s bootstrap does on real hardware.
        """
        prg_path = pathlib.Path(prg_path)
        data = prg_path.read_bytes()
        load_addr = data[0] | (data[1] << 8)
        payload = data[2:]
        for i, b in enumerate(payload):
            self._mem.ram[load_addr + i] = b

        # Parse map file for symbols
        if map_path is None:
            map_path = prg_path.with_suffix('.map')
        map_path = pathlib.Path(map_path)
        if map_path.exists():
            self._parse_map(map_path)
            self._relocate_segments(map_path)

        return load_addr

    def _relocate_segments(self, map_path):
        """Copy segments from load to run address when they differ.

        Uses __SEG_LOAD__ / __SEG_RUN__ symbols (generated by ld65
        when segments have define=yes) to identify relocated segments.
        Mirrors what loader.s does at startup on real hardware.
        """
        import re
        # Find all segments that have both LOAD and RUN symbols
        seg_names = set()
        for sym in self._syms:
            m = re.match(r"__(\w+)_LOAD__$", sym)
            if m:
                seg_names.add(m.group(1))
        for name in seg_names:
            load_sym = f"__{name}_LOAD__"
            run_sym = f"__{name}_RUN__"
            size_sym = f"__{name}_SIZE__"
            if all(s in self._syms for s in (load_sym, run_sym, size_sym)):
                load = self._syms[load_sym]
                run = self._syms[run_sym]
                size = self._syms[size_sym]
                if load != run and size > 0:
                    for i in range(size):
                        self._mem.ram[run + i] = self._mem.ram[load + i]

    def _parse_map(self, map_path):
        """Load symbols from the .lbl file (VICE label format) companion
        to the ld65 map file.  Uses conftest.SymbolTable for parsing."""
        from conftest import SymbolTable
        lbl_path = map_path.with_suffix('.lbl')
        if lbl_path.exists():
            st = SymbolTable(lbl_path)
            for name in st.keys():
                self._syms[name] = st[name]

    def sym(self, name):
        """Look up a symbol address by name."""
        try:
            return self._syms[name]
        except KeyError:
            raise KeyError(
                f"Symbol {name!r} not found. "
                f"Available: {', '.join(sorted(self._syms)[:20])}..."
            ) from None

    def sym_opt(self, name):
        """Look up a symbol address; return None if not present.

        Useful for feature-gated tests that should skip cleanly when
        a symbol is missing (e.g. during staged refactors).
        """
        return self._syms.get(name)

    def run_until(self, stop_addr, *, start_at=None, max_cycles=500_000):
        """Step CPU until PC == stop_addr (or max_cycles exceeded).

        Unlike jsr(), this does not install a sentinel return — the
        caller arranges that control reaches stop_addr some other way
        (e.g. via a longjmp/RTI-into-user-code path).

        If start_at is given, PC is set to that address first.
        """
        if start_at is not None:
            self._cpu.pc = start_at
        cycles = 0
        while cycles < max_cycles:
            if self._cpu.pc == stop_addr:
                return cycles
            self._cpu.step()
            cycles += 1
            self._cycle_total += 1
            if self._pending:
                self._dispatch_pending()
        raise TimeoutError(
            f"C64Emu: run_until({stop_addr:#06X}) timeout after "
            f"{max_cycles} cycles at PC=${self._cpu.pc:04X}"
        )

    def trigger_nmi(self, user_pc, *, user_p=0x20):
        """Synthesise a CPU NMI frame on the stack and set PC to the
        NMI vector's target.  Stack ordering matches what the CPU
        pushes on an NMI: PChi, PClo, P (in that push order — pop
        order at RTI is P, PClo, PChi).

        After this, step/run to the handler; an RTI in the handler
        will pop back to user_pc with user_p installed in P.

        Typically used by tests that want to exercise cse_nmi_handler
        without CIA timer fiddling.
        """
        sp = self._cpu.sp
        self._mem.ram[0x0100 + sp] = (user_pc >> 8) & 0xFF
        sp = (sp - 1) & 0xFF
        self._mem.ram[0x0100 + sp] = user_pc & 0xFF
        sp = (sp - 1) & 0xFF
        self._mem.ram[0x0100 + sp] = user_p & 0xFF
        sp = (sp - 1) & 0xFF
        self._cpu.sp = sp

    # ── Helpers ─────────────────────────────────────────────────

    def read_word(self, addr):
        """Read a 16-bit little-endian word from memory."""
        return self._mem[addr] | (self._mem[addr + 1] << 8)

    def write_word(self, addr, val):
        """Write a 16-bit little-endian word to memory."""
        self._mem[addr] = val & 0xFF
        self._mem[addr + 1] = (val >> 8) & 0xFF

    def screen_row(self, row):
        """Read screen codes for one row (40 bytes) as a list."""
        base = SCREEN + row * COLS
        return [self._mem[base + c] for c in range(COLS)]

    def screen_text(self, row):
        """Read one screen row as a Python string (screen code → ASCII).

        Decodes using the lowercase/uppercase charset (CSE's runtime
        mode):
          $00        → '@'
          $01-$1A    → 'a'-'z'  (lowercase)
          $20-$3F    → identity (space, punctuation, digits)
          $41-$5A    → 'A'-'Z'  (uppercase)
          everything else → '?'
        """
        codes = self.screen_row(row)
        chars = []
        for sc in codes:
            sc &= 0x7F
            if sc == 0x00:
                chars.append('@')
            elif 0x01 <= sc <= 0x1A:        # lowercase a-z
                chars.append(chr(sc + 0x60))
            elif 0x20 <= sc <= 0x3F:        # identity range
                chars.append(chr(sc))
            elif 0x41 <= sc <= 0x5A:        # uppercase A-Z
                chars.append(chr(sc))
            else:
                chars.append('?')
        return ''.join(chars).rstrip()

    def set_cursor(self, row, col):
        """Set cursor position via KERNAL PLOT (CLC path)."""
        # CLC; LDX #row; LDY #col; JSR $FFF0; RTS
        stub = 0xDF80  # small stub area in I/O gap
        code = [0x18, 0xA2, row & 0xFF, 0xA0, col & 0xFF,
                0x20, 0xF0, 0xFF, 0x60]
        for i, b in enumerate(code):
            self._mem.ram[stub + i] = b
        self.jsr(stub)

    def init_cse(self, *, editor=False):
        """Run CSE init routines.  Call after load_prg().

        Runs the minimal cold-init sequence — theme_init +
        restore_colors + setup_interrupts + dbg_init + sym_clear.
        `sym_clear` is mandatory because update_workend (called
        from editor init and asm_assemble) writes to the symbol
        heap via sym_define; without sym_clear the heap pointer
        is \$0000 (BSS default) and writes corrupt zero page.
        If editor=True, also runs ed_ensure_init.
        """
        self.jsr(self.sym("theme_init"))
        self.jsr(self.sym("restore_colors"))
        self.jsr(self.sym("setup_interrupts"))
        self.jsr(self.sym("dbg_init"))
        self.jsr(self.sym("sym_clear"))
        if editor:
            self.jsr(self.sym("ed_ensure_init"))
