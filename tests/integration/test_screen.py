"""
test_screen_asm.py — ASM-level screen module tests via C64Emu.

Tests the real screen.s routines (newline, scroll_up, restore_colors,
reset_screen, cursor_show/hide) against actual screen RAM.

Requires: build/cmos/cse-cmos.prg (auto-built by cse_prg fixture).
"""

import pytest
from c64emu import C64Emu, SCREEN, COLS, ROWS, COLOR_RAM


def make_emu(cse_prg):
    """Fresh C64Emu with CMOS PRG loaded + screen initialized."""
    prg, map_path = cse_prg
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.init_cse()
    return emu


def fill_row(emu, row, sc):
    base = SCREEN + row * COLS
    for c in range(COLS):
        emu.memory[base + c] = sc


def row_is(emu, row, sc):
    base = SCREEN + row * COLS
    return all(emu.memory[base + c] == sc for c in range(COLS))


# ── restore_colors ──────────────────────────────────────────────────────────

class TestRestoreColors:
    """restore_colors sets VIC border/bg and fills color RAM."""

    def test_fills_color_ram(self, cse_prg):
        emu = make_emu(cse_prg)
        fg = emu.memory[emu.sym("theme_fg")]
        assert emu.memory[COLOR_RAM] == fg
        assert emu.memory[COLOR_RAM + 999] == fg

    def test_sets_border(self, cse_prg):
        emu = make_emu(cse_prg)
        assert emu.memory[0xD020] == emu.memory[emu.sym("theme_border")]

    def test_sets_background(self, cse_prg):
        emu = make_emu(cse_prg)
        assert emu.memory[0xD021] == emu.memory[emu.sym("theme_bg")]

    def test_sets_chrcolor(self, cse_prg):
        emu = make_emu(cse_prg)
        assert emu.memory[0x0286] == emu.memory[emu.sym("theme_fg")]


# ── reset_screen ────────────────────────────────────────────────────────────

class TestResetScreen:
    """reset_screen clears screen, restores colors, resets cursor."""

    def test_clears_screen(self, cse_prg):
        emu = make_emu(cse_prg)
        for i in range(100):
            emu.memory[SCREEN + i] = 0x01
        emu.jsr(emu.sym("reset_screen"))
        assert row_is(emu, 0, 0x20)
        assert row_is(emu, 24, 0x20)

    def test_resets_cursor(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(10, 20)
        emu.jsr(emu.sym("reset_screen"))
        assert emu.memory[0xD6] == 0
        assert emu.memory[0xD3] == 0


# ── newline ─────────────────────────────────────────────────────────────────

class TestNewline:
    """newline advances cursor to next row col 0, scrolls at bottom."""

    def test_advance_row(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(5, 10)
        emu.jsr(emu.sym("newline"))
        assert emu.memory[0xD6] == 6
        assert emu.memory[0xD3] == 0

    def test_scroll_at_bottom(self, cse_prg):
        emu = make_emu(cse_prg)
        fill_row(emu, 1, 0x01)
        emu.set_cursor(24, 0)
        emu.jsr(emu.sym("newline"))
        assert emu.memory[0xD6] == 24
        assert emu.memory[0xD3] == 0
        assert row_is(emu, 0, 0x01)  # row 1 scrolled to row 0

    def test_no_scroll_mid_screen(self, cse_prg):
        emu = make_emu(cse_prg)
        fill_row(emu, 0, 0x02)
        emu.set_cursor(10, 0)
        emu.jsr(emu.sym("newline"))
        assert row_is(emu, 0, 0x02)  # row 0 untouched


# ── scroll_up ───────────────────────────────────────────────────────────────

class TestScrollUp:
    """scroll_up(n) scrolls screen RAM up by n rows."""

    def test_scroll_1(self, cse_prg):
        emu = make_emu(cse_prg)
        for r in range(ROWS):
            fill_row(emu, r, r + 1)
        emu.set_cursor(0, 0)
        emu.jsr(emu.sym("scroll_up"), a=1)
        assert emu.memory[SCREEN] == 2        # was row 1
        assert emu.memory[SCREEN + 23*COLS] == 25  # was row 24
        assert row_is(emu, 24, 0x20)           # cleared

    def test_scroll_5(self, cse_prg):
        emu = make_emu(cse_prg)
        for r in range(ROWS):
            fill_row(emu, r, r + 1)
        emu.set_cursor(12, 0)
        emu.jsr(emu.sym("scroll_up"), a=5)
        assert emu.memory[SCREEN] == 6  # was row 5
        for r in range(20, 25):
            assert row_is(emu, r, 0x20), f"row {r} should be cleared"

    def test_scroll_full(self, cse_prg):
        emu = make_emu(cse_prg)
        for r in range(ROWS):
            fill_row(emu, r, 0x42)
        emu.jsr(emu.sym("scroll_up"), a=25)
        for r in range(ROWS):
            assert row_is(emu, r, 0x20)


# ── cursor_show / cursor_hide ──────────────────────────────────────────────

class TestCursorToggle:
    """cursor_show XORs $80 at cursor position; cursor_hide is identical."""

    def test_show_inverts(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(0, 0)
        emu.memory[SCREEN] = 0x01
        emu.jsr(emu.sym("cursor_show"))
        assert emu.memory[SCREEN] == 0x81

    def test_hide_restores(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(0, 0)
        emu.memory[SCREEN] = 0x01
        emu.jsr(emu.sym("cursor_show"))
        emu.jsr(emu.sym("cursor_hide"))
        assert emu.memory[SCREEN] == 0x01

    def test_cursor_at_position(self, cse_prg):
        emu = make_emu(cse_prg)
        emu.set_cursor(5, 10)
        addr = SCREEN + 5 * COLS + 10
        emu.memory[addr] = 0x04
        emu.jsr(emu.sym("cursor_show"))
        assert emu.memory[addr] == 0x84
        assert emu.memory[addr - 1] == 0x20
        assert emu.memory[addr + 1] == 0x20
