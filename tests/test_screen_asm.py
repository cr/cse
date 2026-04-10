"""
test_screen_asm.py — ASM-level screen module tests via C64Emu.

Tests the real screen.s routines (newline, scroll_up, restore_colors,
reset_screen, cursor_show/hide) against actual screen RAM.

Requires: build/cmos/cse-cmos.prg (built by `make CPU=65c02`).
"""

import subprocess
import pathlib
import pytest

from c64emu import C64Emu, SCREEN, COLS, ROWS, COLOR_RAM

ROOT = pathlib.Path(__file__).parent.parent
PRG  = ROOT / "build" / "cmos" / "cse-cmos.prg"
MAP  = ROOT / "build" / "cmos" / "cse.map"


# ── Build + fixture ─────────────────────────────────────────────────────────

def _ensure_built():
    if not PRG.exists() or not MAP.exists():
        subprocess.run(["make", "CPU=65c02"], cwd=ROOT, check=True,
                       capture_output=True)


@pytest.fixture(scope="session")
def prg_map():
    _ensure_built()
    return PRG, MAP


def make_emu(prg_map):
    """Create a C64Emu with the CMOS PRG loaded and screen initialized."""
    prg, map_path = prg_map
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.jsr(emu.sym("theme_init"))
    emu.jsr(emu.sym("restore_colors"))
    return emu


# ── Helpers ─────────────────────────────────────────────────────────────────

def write_screen_char(emu, row, col, sc):
    """Write a screen code at (row, col)."""
    emu.memory[SCREEN + row * COLS + col] = sc


def read_screen_char(emu, row, col):
    """Read a screen code at (row, col)."""
    return emu.memory[SCREEN + row * COLS + col]


def fill_row(emu, row, sc):
    """Fill an entire screen row with a screen code."""
    base = SCREEN + row * COLS
    for c in range(COLS):
        emu.memory[base + c] = sc


def row_is(emu, row, sc):
    """Check that an entire row contains the given screen code."""
    base = SCREEN + row * COLS
    return all(emu.memory[base + c] == sc for c in range(COLS))


def set_cursor(emu, row, col):
    """Set the cursor position via KERNAL PLOT."""
    code_addr = 0x3000
    code = [0x18, 0xA2, row & 0xFF, 0xA0, col & 0xFF,
            0x20, 0xF0, 0xFF, 0x60]
    for i, b in enumerate(code):
        emu.memory[code_addr + i] = b
    emu.jsr(code_addr)


# ── restore_colors ──────────────────────────────────────────────────────────

class TestRestoreColors:
    """restore_colors sets VIC border/bg and fills color RAM."""

    def test_fills_color_ram(self, prg_map):
        emu = make_emu(prg_map)
        fg = emu.memory[emu.sym("theme_fg")]
        # Check first and last color RAM bytes
        assert emu.memory[COLOR_RAM] == fg
        assert emu.memory[COLOR_RAM + 999] == fg

    def test_sets_border(self, prg_map):
        emu = make_emu(prg_map)
        border = emu.memory[emu.sym("theme_border")]
        assert emu.memory[0xD020] == border

    def test_sets_background(self, prg_map):
        emu = make_emu(prg_map)
        bg = emu.memory[emu.sym("theme_bg")]
        assert emu.memory[0xD021] == bg

    def test_sets_chrcolor(self, prg_map):
        """restore_colors writes theme_fg to KERNAL $0286 (CHRCOLOR)."""
        emu = make_emu(prg_map)
        fg = emu.memory[emu.sym("theme_fg")]
        assert emu.memory[0x0286] == fg


# ── reset_screen ────────────────────────────────────────────────────────────

class TestResetScreen:
    """reset_screen clears screen, restores colors, resets cursor."""

    def test_clears_screen(self, prg_map):
        emu = make_emu(prg_map)
        # Dirty the screen
        for i in range(100):
            emu.memory[SCREEN + i] = 0x01
        emu.jsr(emu.sym("reset_screen"))
        assert row_is(emu, 0, 0x20)
        assert row_is(emu, 24, 0x20)

    def test_resets_cursor(self, prg_map):
        emu = make_emu(prg_map)
        set_cursor(emu, 10, 20)
        emu.jsr(emu.sym("reset_screen"))
        assert emu.memory[0xD6] == 0  # row
        assert emu.memory[0xD3] == 0  # col


# ── newline ─────────────────────────────────────────────────────────────────

class TestNewline:
    """newline advances cursor to next row col 0, scrolls at bottom."""

    def test_advance_row(self, prg_map):
        emu = make_emu(prg_map)
        set_cursor(emu, 5, 10)
        emu.jsr(emu.sym("newline"))
        assert emu.memory[0xD6] == 6   # row advanced
        assert emu.memory[0xD3] == 0   # col reset

    def test_scroll_at_bottom(self, prg_map):
        """At row 24, newline scrolls up and stays on row 24."""
        emu = make_emu(prg_map)
        # Put recognizable content on row 1
        fill_row(emu, 1, 0x01)  # row 1 = all 'A' screen codes
        set_cursor(emu, 24, 0)
        emu.jsr(emu.sym("newline"))
        assert emu.memory[0xD6] == 24  # still on last row
        assert emu.memory[0xD3] == 0
        # Row 1's content should now be on row 0 (scrolled up by 1)
        assert row_is(emu, 0, 0x01)

    def test_no_scroll_mid_screen(self, prg_map):
        emu = make_emu(prg_map)
        fill_row(emu, 0, 0x02)  # marker on row 0
        set_cursor(emu, 10, 0)
        emu.jsr(emu.sym("newline"))
        # Row 0 should be untouched (no scroll happened)
        assert row_is(emu, 0, 0x02)


# ── scroll_up ───────────────────────────────────────────────────────────────

class TestScrollUp:
    """scroll_up(n) scrolls screen RAM up by n rows."""

    def test_scroll_1(self, prg_map):
        emu = make_emu(prg_map)
        # Put unique data on each row
        for r in range(ROWS):
            fill_row(emu, r, r + 1)
        set_cursor(emu, 0, 0)
        emu.jsr(emu.sym("scroll_up"), a=1)
        # Row 0 should now have what was on row 1
        assert read_screen_char(emu, 0, 0) == 2
        # Row 23 should have what was on row 24
        assert read_screen_char(emu, 23, 0) == 25
        # Row 24 should be cleared (space)
        assert row_is(emu, 24, 0x20)

    def test_scroll_5(self, prg_map):
        emu = make_emu(prg_map)
        for r in range(ROWS):
            fill_row(emu, r, r + 1)
        set_cursor(emu, 12, 0)
        emu.jsr(emu.sym("scroll_up"), a=5)
        # Row 0 should have what was on row 5
        assert read_screen_char(emu, 0, 0) == 6
        # Last 5 rows should be cleared
        for r in range(20, 25):
            assert row_is(emu, r, 0x20), f"row {r} should be cleared"

    def test_scroll_full(self, prg_map):
        """Scrolling >= 25 rows clears the entire screen (via reset_screen)."""
        emu = make_emu(prg_map)
        for r in range(ROWS):
            fill_row(emu, r, 0x42)
        emu.jsr(emu.sym("scroll_up"), a=25)
        for r in range(ROWS):
            assert row_is(emu, r, 0x20), f"row {r} should be cleared"


# ── cursor_show / cursor_hide ──────────────────────────────────────────────

class TestCursorToggle:
    """cursor_show XORs $80 at cursor position; cursor_hide does the same."""

    def test_show_inverts(self, prg_map):
        emu = make_emu(prg_map)
        set_cursor(emu, 0, 0)
        emu.memory[SCREEN] = 0x01  # 'A' screen code
        emu.jsr(emu.sym("cursor_show"))
        assert emu.memory[SCREEN] == 0x81  # inverted

    def test_hide_restores(self, prg_map):
        emu = make_emu(prg_map)
        set_cursor(emu, 0, 0)
        emu.memory[SCREEN] = 0x01
        emu.jsr(emu.sym("cursor_show"))
        emu.jsr(emu.sym("cursor_hide"))
        assert emu.memory[SCREEN] == 0x01  # restored

    def test_cursor_at_position(self, prg_map):
        """Cursor toggle affects the correct screen position."""
        emu = make_emu(prg_map)
        set_cursor(emu, 5, 10)
        addr = SCREEN + 5 * COLS + 10
        emu.memory[addr] = 0x04  # 'D'
        emu.jsr(emu.sym("cursor_show"))
        assert emu.memory[addr] == 0x84
        # Verify adjacent cells unaffected
        assert emu.memory[addr - 1] == 0x20  # space
        assert emu.memory[addr + 1] == 0x20
