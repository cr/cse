"""
test_c64emu.py — Smoke tests for C64Emu and KERNAL compatibility.

Validates that the emulator class works and that the C64 KERNAL
routines we depend on function correctly under py65 without real hardware.
"""

import pytest
from c64emu import C64Emu, SCREEN, COLS, ROWS, COLOR_RAM

# ── Construction ────────────────────────────────────────────────────────────

class TestConstruction:
    """C64Emu initialises to a sane C64 state."""

    def test_memory_size(self):
        emu = C64Emu()
        assert len(emu.memory) == 65536

    def test_processor_port(self):
        emu = C64Emu()
        assert emu.memory[0x00] == 0x2F   # DDR
        assert emu.memory[0x01] == 0x37   # bank config

    def test_screen_cleared(self):
        emu = C64Emu()
        for i in range(1000):
            assert emu.memory[SCREEN + i] == 0x20

    def test_color_ram(self):
        emu = C64Emu()
        assert emu.memory[COLOR_RAM] == 0x01  # white

    def test_cursor_at_origin(self):
        emu = C64Emu()
        assert emu.memory[0xD3] == 0  # col
        assert emu.memory[0xD6] == 0  # row

    def test_cursor_disabled(self):
        emu = C64Emu()
        assert emu.memory[0xCC] == 1

    def test_stack_pointer(self):
        emu = C64Emu()
        assert emu.sp == 0xFF

    def test_kbd_buffer_empty(self):
        emu = C64Emu()
        assert emu.memory[0xC6] == 0


# ── Bank switching ──────────────────────────────────────────────────────────

class TestBanking:
    """$01 processor port toggles KERNAL ROM visibility."""

    def test_rom_mapped_by_default(self):
        emu = C64Emu()
        # $FFF0 should be the PLOT JMP opcode (from ROM)
        assert emu.memory[0xFFF0] == 0x4C  # JMP

    def test_bank_out_exposes_ram(self):
        emu = C64Emu()
        # Write to RAM under ROM
        emu.memory[0x01] = 0x35   # clear bit 1
        # RAM at $FFF0 should be 0 (was never written)
        assert emu.memory[0xFFF0] == 0x00

    def test_bank_back_in(self):
        emu = C64Emu()
        emu.memory[0x01] = 0x35   # ROM out
        assert emu.memory[0xFFF0] == 0x00
        emu.memory[0x01] = 0x37   # ROM back in
        assert emu.memory[0xFFF0] == 0x4C

    def test_write_through_to_ram(self):
        emu = C64Emu()
        # With ROM mapped, write to $E000 goes to RAM underneath
        emu.memory[0xE000] = 0x42
        # Still reads ROM
        assert emu.memory[0xE000] != 0x42  # ROM value, not $42
        # Bank out → now see the RAM write
        emu.memory[0x01] = 0x35
        assert emu.memory[0xE000] == 0x42


# ── JSR execution ───────────────────────────────────────────────────────────

class TestJsr:
    """emu.jsr() runs code and returns on RTS."""

    def test_simple_rts(self):
        emu = C64Emu()
        # Plant an RTS at $2000
        emu.memory[0x2000] = 0x60  # RTS
        cycles = emu.jsr(0x2000)
        assert cycles >= 1

    def test_sets_registers(self):
        emu = C64Emu()
        # LDA #$00; RTS — just returns, we check input regs were set
        emu.memory[0x2000] = 0x60  # RTS
        emu.jsr(0x2000, a=0x42, x=0x13, y=0x7F)
        # A is preserved through RTS (no clobber)
        assert emu.a == 0x42
        assert emu.x == 0x13
        assert emu.y == 0x7F

    def test_timeout_raises(self):
        emu = C64Emu()
        # Infinite loop: JMP $2000
        emu.memory[0x2000] = 0x4C  # JMP
        emu.memory[0x2001] = 0x00
        emu.memory[0x2002] = 0x20
        with pytest.raises(TimeoutError, match="timeout"):
            emu.jsr(0x2000, max_cycles=100)

    def test_carry_flag(self):
        emu = C64Emu()
        # SEC; RTS
        emu.memory[0x2000] = 0x38  # SEC
        emu.memory[0x2001] = 0x60  # RTS
        emu.jsr(0x2000)
        assert emu.carry is True

    def test_carry_clear(self):
        emu = C64Emu()
        # CLC; RTS
        emu.memory[0x2000] = 0x18  # CLC
        emu.memory[0x2001] = 0x60  # RTS
        emu.jsr(0x2000)
        assert emu.carry is False


# ── Keyboard injection ──────────────────────────────────────────────────────

class TestKeyboard:
    """inject_key / inject_keys populate the KERNAL keyboard buffer."""

    def test_inject_single(self):
        emu = C64Emu()
        emu.inject_key(0x41)  # 'A'
        assert emu.memory[0xC6] == 1
        assert emu.memory[0x0277] == 0x41

    def test_inject_multiple(self):
        emu = C64Emu()
        emu.inject_keys(b"HI\r")
        assert emu.memory[0xC6] == 3
        assert emu.memory[0x0277] == ord('H')
        assert emu.memory[0x0278] == ord('I')
        assert emu.memory[0x0279] == 0x0D

    def test_buffer_overflow(self):
        emu = C64Emu()
        emu.inject_keys(b"0123456789")  # fill 10
        with pytest.raises(OverflowError):
            emu.inject_key(0x41)


# ── KERNAL PLOT compatibility ───────────────────────────────────────────────

class TestKernalPlot:
    """KERNAL PLOT ($FFF0) works under py65."""

    def _call_plot_set(self, emu, row, col):
        """Call KERNAL PLOT with carry clear (SET mode)."""
        # CLC; LDX #row; LDY #col; JSR $FFF0; RTS
        code = [
            0x18,               # CLC
            0xA2, row & 0xFF,   # LDX #row
            0xA0, col & 0xFF,   # LDY #col
            0x20, 0xF0, 0xFF,   # JSR $FFF0
            0x60,               # RTS
        ]
        base = 0x2000
        for i, b in enumerate(code):
            emu.memory[base + i] = b
        emu.jsr(base)

    def _call_plot_get(self, emu):
        """Call KERNAL PLOT with carry set (GET mode).  Returns (row, col)."""
        code = [
            0x38,               # SEC
            0x20, 0xF0, 0xFF,   # JSR $FFF0
            0x60,               # RTS
        ]
        base = 0x2000
        for i, b in enumerate(code):
            emu.memory[base + i] = b
        emu.jsr(base)
        return emu.x, emu.y

    def test_plot_set_row0(self):
        """PLOT SET stores cursor position and sets line pointers."""
        emu = C64Emu()
        self._call_plot_set(emu, row=0, col=5)
        assert emu.memory[0xD6] == 0     # row
        assert emu.memory[0xD3] == 5     # col
        # Screen line pointer should be $0400 (row 0)
        line = emu.memory[0xD1] | (emu.memory[0xD2] << 8)
        assert line == SCREEN

    def test_plot_set_row10(self):
        """PLOT SET for row 10 sets correct line pointer."""
        emu = C64Emu()
        self._call_plot_set(emu, row=10, col=20)
        assert emu.memory[0xD6] == 10
        assert emu.memory[0xD3] == 20
        line = emu.memory[0xD1] | (emu.memory[0xD2] << 8)
        expected = SCREEN + 10 * COLS
        assert line == expected, f"expected ${expected:04X}, got ${line:04X}"

    def test_plot_set_row24(self):
        """PLOT SET for last row."""
        emu = C64Emu()
        self._call_plot_set(emu, row=24, col=0)
        assert emu.memory[0xD6] == 24
        line = emu.memory[0xD1] | (emu.memory[0xD2] << 8)
        expected = SCREEN + 24 * COLS
        assert line == expected

    def test_plot_get(self):
        """PLOT GET reads back the current cursor position."""
        emu = C64Emu()
        self._call_plot_set(emu, row=12, col=30)
        row, col = self._call_plot_get(emu)
        assert row == 12
        assert col == 30

    def test_plot_color_pointer(self):
        """PLOT SET also updates the color RAM pointer ($F3/$F4)."""
        emu = C64Emu()
        self._call_plot_set(emu, row=5, col=0)
        color = emu.memory[0xF3] | (emu.memory[0xF4] << 8)
        expected = COLOR_RAM + 5 * COLS
        assert color == expected, f"expected ${expected:04X}, got ${color:04X}"

    def test_plot_all_rows(self):
        """PLOT SET works for all 25 rows."""
        emu = C64Emu()
        for row in range(ROWS):
            self._call_plot_set(emu, row=row, col=0)
            line = emu.memory[0xD1] | (emu.memory[0xD2] << 8)
            expected = SCREEN + row * COLS
            assert line == expected, f"row {row}: expected ${expected:04X}, got ${line:04X}"


# ── KERNAL GETIN compatibility ─────────────────────────────────────────────

class TestKernalGetin:
    """KERNAL GETIN ($FFE4) reads from the keyboard buffer."""

    def _call_getin(self, emu):
        """Call KERNAL GETIN, returns A (the key read)."""
        code = [
            0x20, 0xE4, 0xFF,   # JSR $FFE4
            0x60,               # RTS
        ]
        base = 0x2000
        for i, b in enumerate(code):
            emu.memory[base + i] = b
        emu.jsr(base)
        return emu.a

    def test_getin_empty(self):
        """GETIN returns 0 when buffer is empty."""
        emu = C64Emu()
        key = self._call_getin(emu)
        assert key == 0

    def test_getin_reads_key(self):
        """GETIN returns the first key and decrements count."""
        emu = C64Emu()
        emu.inject_key(0x41)  # 'A'
        key = self._call_getin(emu)
        assert key == 0x41
        assert emu.memory[0xC6] == 0  # buffer now empty

    def test_getin_fifo(self):
        """GETIN reads keys in FIFO order."""
        emu = C64Emu()
        emu.inject_keys(b"AB")
        k1 = self._call_getin(emu)
        k2 = self._call_getin(emu)
        assert k1 == ord('A')
        assert k2 == ord('B')
        assert emu.memory[0xC6] == 0


# ── PRG loading ─────────────────────────────────────────────────────────────

class TestPrgLoading:
    """load_prg reads .prg format and parses .map symbols."""

    def test_load_prg_basic(self, tmp_path):
        """Load a minimal PRG: 2-byte header + payload."""
        prg = tmp_path / "test.prg"
        # Load at $2000, payload: LDA #$42; RTS
        prg.write_bytes(bytes([0x00, 0x20, 0xA9, 0x42, 0x60]))
        emu = C64Emu()
        addr = emu.load_prg(prg)
        assert addr == 0x2000
        assert emu.memory[0x2000] == 0xA9
        # Execute it
        emu.jsr(0x2000)
        assert emu.a == 0x42

    def test_load_prg_with_map(self, tmp_path):
        """load_prg parses companion .lbl for symbols."""
        prg = tmp_path / "test.prg"
        prg.write_bytes(bytes([0x00, 0x20, 0x60]))  # RTS at $2000
        # Write a fake map file (load_prg needs it as argument)
        map_file = tmp_path / "test.map"
        map_file.write_text("")
        # Write a .lbl file (VICE label format) — this is what
        # _parse_map actually reads for symbol resolution.
        lbl_file = tmp_path / "test.lbl"
        lbl_file.write_text("al 002000 .my_func\n")
        emu = C64Emu()
        emu.load_prg(prg, map_file)
        assert emu.sym("my_func") == 0x2000


# ── Screen helpers ──────────────────────────────────────────────────────────

class TestScreenHelpers:
    """read_word, write_word, screen_row, screen_text."""

    def test_read_write_word(self):
        emu = C64Emu()
        emu.write_word(0x3000, 0xBEEF)
        assert emu.memory[0x3000] == 0xEF
        assert emu.memory[0x3001] == 0xBE
        assert emu.read_word(0x3000) == 0xBEEF

    def test_screen_row_empty(self):
        emu = C64Emu()
        row = emu.screen_row(0)
        assert len(row) == 40
        assert all(c == 0x20 for c in row)

    def test_screen_text(self):
        emu = C64Emu()
        # Write "hello" in screen codes: h=8, e=5, l=12, l=12, o=15
        for i, sc in enumerate([0x08, 0x05, 0x0C, 0x0C, 0x0F]):
            emu.memory[SCREEN + i] = sc
        assert emu.screen_text(0) == "hello"


# ── VERSION propagation (A1) ────────────────────────────────────────────────

class TestVersionPropagation:
    """VERSION_STR in the PRG reflects the Makefile VERSION."""

    def _makefile_version(self):
        import pathlib, re
        mk = pathlib.Path(__file__).parent.parent / "Makefile"
        for line in mk.read_text().splitlines():
            m = re.match(r'\s*VERSION\s*\?=\s*(\S+)', line)
            if m:
                return m.group(1)
        raise AssertionError("no VERSION line in Makefile")

    def test_version_str_contains_version(self, cse_prg):
        """VERSION_STR bytes encode 'cse v<VERSION> by cr' in PETSCII.

        ca65 -t c64 remaps ASCII a-z in string literals to PETSCII
        $41-$5A, so the on-disk bytes match the ASCII *uppercase*
        form of the source string even though the display shows
        lowercase (charset 2).
        """
        prg, map_path = cse_prg
        emu = C64Emu()
        emu.load_prg(prg, map_path)
        addr = emu.sym("VERSION_STR")
        buf = []
        for i in range(64):
            b = emu.memory[addr + i]
            if b == 0:
                break
            buf.append(b)
        s = bytes(buf).decode('latin1')
        version = self._makefile_version()
        expected = f"cse v{version} by cr".upper()
        assert s == expected, \
            f"VERSION_STR = {s!r} (expected Makefile VERSION={version})"
