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
    emu.jsr(emu.sym("al_line_asm"), a=0x42)
    assert emu.a == expected
"""

import pathlib
from py65.devices.mpu6502 import MPU

_ROM_PATH = pathlib.Path(__file__).parent.parent / "rom" / "kernal.bin"

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
    """64 KB address space with ROM overlay and $01 bank switching.

    When rom_mapped is True, reads from $E000–$FFFF return ROM data.
    Writes always go to RAM (write-through).  Writing to $01 toggles
    bit 1: set = KERNAL ROM visible, clear = RAM visible.
    """

    __slots__ = ('ram', 'rom', 'rom_mapped')

    def __init__(self, rom_data):
        self.ram = [0] * 65536
        self.rom = list(rom_data)      # 8192 bytes ($E000–$FFFF)
        self.rom_mapped = True

    def __len__(self):
        return 65536

    def __getitem__(self, key):
        if isinstance(key, slice):
            start, stop, step = key.indices(65536)
            return [self._read(i) for i in range(start, stop, step or 1)]
        return self._read(key)

    def _read(self, addr):
        if self.rom_mapped and 0xE000 <= addr <= 0xFFFF:
            return self.rom[addr - 0xE000]
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
            self.rom_mapped = bool(val & 0x02)
        self.ram[addr] = val


class C64Emu:
    """Minimal C64 emulator for testing CSE assembly code."""

    # Sentinel address — the RTS target for jsr().
    # Placed in I/O area ($D000–$DFFF) which CSE never executes from.
    SENTINEL = 0xDFF0

    def __init__(self, rom_path=None):
        rom_path = pathlib.Path(rom_path) if rom_path else _ROM_PATH
        rom_data = rom_path.read_bytes()
        assert len(rom_data) == 8192, f"KERNAL ROM must be 8192 bytes, got {len(rom_data)}"

        self._mem = BankedMemory(rom_data)
        self._cpu = MPU()
        self._cpu.memory = self._mem
        self._syms = {}

        # -- processor port --
        self._mem.ram[0x00] = 0x2F       # DDR: all output
        self._mem.ram[0x01] = 0x37       # default bank config

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
        self._init_kernal_vectors(rom_data)

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

        raise TimeoutError(
            f"C64Emu: timeout after {max_cycles} cycles at "
            f"${self._cpu.pc:04X}"
        )

    # ── Keyboard injection ──────────────────────────────────────

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

        return load_addr

    def _parse_map(self, map_path):
        """Parse ld65 map file for exported symbols, and the companion
        .lbl file (VICE label format) for all labels including
        module-internal ones."""
        import re
        # -- map file: exported symbols --
        in_exports = False
        for line in map_path.read_text().splitlines():
            if "Exports list by name" in line:
                in_exports = True
                continue
            if in_exports:
                if line.strip() == "" or "Exports list by value" in line:
                    break
                for name, addr in re.findall(
                    r"(\w+)\s+([0-9a-fA-F]{6})\s+\w+", line
                ):
                    self._syms[name] = int(addr, 16)
        # -- label file: all symbols (VICE format: "al XXXX .name") --
        lbl_path = map_path.with_suffix('.lbl')
        if lbl_path.exists():
            for line in lbl_path.read_text().splitlines():
                m = re.match(r"al\s+([0-9a-fA-F]+)\s+\.(\w+)", line)
                if m:
                    name = m.group(2)
                    addr = int(m.group(1), 16)
                    # lbl names may shadow map exports — map wins
                    if name not in self._syms:
                        self._syms[name] = addr

    def sym(self, name):
        """Look up an exported symbol address by name."""
        try:
            return self._syms[name]
        except KeyError:
            raise KeyError(
                f"Symbol {name!r} not found in map. "
                f"Available: {', '.join(sorted(self._syms)[:20])}..."
            ) from None

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
        """Read one screen row as a Python string (screen code → ASCII)."""
        codes = self.screen_row(row)
        chars = []
        for sc in codes:
            sc &= 0x7F
            if 0x01 <= sc <= 0x1A:       # screen A-Z → ASCII a-z
                chars.append(chr(sc + 0x60))
            elif sc == 0x00:
                chars.append('@')
            elif 0x20 <= sc <= 0x3F:      # identity range
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

        Runs theme_init + restore_colors + kernal_init.
        If editor=True, also runs ed_ensure_init.
        """
        self.jsr(self.sym("theme_init"))
        self.jsr(self.sym("restore_colors"))
        self.jsr(self.sym("kernal_init"))
        if editor:
            self.jsr(self.sym("ed_ensure_init"))
