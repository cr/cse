"""test_m65_display.py — the display on the m65 PRG (P2 T5).

Owner: doc/modules/screen.md

Contract source: [doc/modules/screen.md § Interface](../../doc/modules/screen.md#interface)
(*On m65*) and [doc/platform_layer.md § Display](../../doc/platform_layer.md#display).

The debug m65 PRG installed on each post-boot snapshot.  A mode is set
as screen_mode_set sets it; screen.s's routines are called with
B = CSE_BP.

- vic_reset writes the mode's recorded VIC-IV register set back
  (tests/fixtures/golden/m65_editor.json, vic_modes) and keeps the
  screen's content; the character set stays the lower/upper-case one.
- restore_colors: border and background, the colour RAM of the mode
  (width x height at the colour RAM), the KERNAL's text colour.
- reset_screen, scroll_up, newline, cursor_show in each mode's bank.
- kernal_screen_reset ends a program's quote mode and window.
- screen_mode_set round trips 4 -> 5 -> 8.
- hygiene_after_userland: the SID gates off, CSE's SYSFLAGS bits set.
"""

import json
import pathlib

import pytest

from m65emu import M65Emu
from m65emu.harness import CSE_BP, flat

ROOT = pathlib.Path(__file__).resolve().parents[2]
EDITOR = json.loads((ROOT / "tests" / "fixtures" / "golden"
                     / "m65_editor.json").read_text())
BSOUT, PLOT, SCRORG, SYSFLAGS = 0xFFD2, 0xFFF0, 0xFFED, 0xFF47
ESC = 0x1B
COLOUR = 0xFF80000
MODES = {"80x25": ("8", 80, 25, 0), "40x25": ("4", 40, 25, 0),
         "80x50": ("5", 80, 50, 4)}


@pytest.fixture
def emu(cse_m65_prg, m65_snapshot):
    emu = M65Emu(m65_snapshot)
    emu.install_prg(*cse_m65_prg)
    emu.rom = m65_snapshot["state"]["rom"]
    return emu


def addr(emu, name):
    v = emu.sym(name)
    return CSE_BP << 8 | v if v < 0x100 else v


def call(emu, name, **regs):
    emu.jsr(emu.sym(name), b=CSE_BP, **regs)


def kernal(emu, entry, **regs):
    emu.jsr(entry, b=0, **regs)


def set_mode(emu, name):
    call(emu, "screen_mode_set", a=ord(MODES[name][0]))


def screen(emu, name):
    _, width, height, bank = MODES[name]
    return bytes(emu.memory.read_flat(flat(bank, 0x0800 + k)) for k in range(width * height))


def fill_screen(emu, name, pattern):
    _, width, height, bank = MODES[name]
    for k in range(width * height):
        emu.memory.write_flat(flat(bank, 0x0800 + k), pattern(k))


def vic(emu, regs):
    return {r: emu.memory[0xD000 + int(r[2:], 16)] for r in regs}


def recorded_vic(emu, name):
    for rom in EDITOR["roms"]:
        if rom["rom"] == emu.rom:
            return rom["vic_modes"][name]
    pytest.skip(f"no editor recording for {emu.rom}")


# ── screen_mode_set and vic_reset ──────────────────────────────────

@pytest.mark.parametrize("name", list(MODES))
def test_screen_mode_set_switches_and_reads_the_geometry(emu, name):
    set_mode(emu, name)
    _, width, height, bank = MODES[name]
    m = emu.memory
    assert (m[addr(emu, "scr_width")], m[addr(emu, "scr_height")]) == (width, height)
    assert m[addr(emu, "scr_bank")] == bank
    want = recorded_vic(emu, name)
    assert vic(emu, want) == want


def test_screen_mode_set_round_trip(emu):
    for name in ("40x25", "80x50", "80x25"):
        set_mode(emu, name)
        assert emu.memory[addr(emu, "scr_width")] == MODES[name][1]


@pytest.mark.parametrize("name", list(MODES))
def test_vic_reset_writes_the_modes_set_and_keeps_the_screen(emu, name):
    set_mode(emu, name)
    fill_screen(emu, name, lambda k: (k * 7) & 0x7F)
    before = screen(emu, name)
    m = emu.memory
    m[0xD031], m[0xD016], m[0xD011] = 0x00, 0x18, 0x3B   # 40 cols, multicolour, bitmap
    m[0xD01A], m[0xD015] = 0x00, 0xFF                    # raster IRQ off, sprites on
    call(emu, "vic_reset")
    want = recorded_vic(emu, name)
    assert vic(emu, want) == want
    assert m[0xD015] == 0
    assert m[0xD069] == 0x18                             # lower/upper-case set
    assert screen(emu, name) == before


# ── colours, clear, scroll, newline, cursor ────────────────────────

@pytest.mark.parametrize("name", list(MODES))
def test_restore_colors_fills_the_modes_colour_ram(emu, name):
    set_mode(emu, name)
    _, width, height, _ = MODES[name]
    m = emu.memory
    for k in range(width * height + 8):
        m.write_flat(COLOUR + k, 0x0F)
    m[addr(emu, "theme_border")], m[addr(emu, "theme_bg")], m[addr(emu, "theme_fg")] = 2, 6, 7
    call(emu, "restore_colors")
    assert (m[0xD020] & 0x0F, m[0xD021] & 0x0F) == (2, 6)
    assert all(m.read_flat(COLOUR + k) & 0x0F == 7 for k in range(width * height))
    assert m.read_flat(COLOUR + width * height) == 0x0F  # nothing past the screen
    kernal(emu, PLOT, x=3, y=4, carry=False)
    kernal(emu, BSOUT, a=ord("Q"))                       # the KERNAL's colour is the theme's
    assert m.read_flat(COLOUR + 3 * width + 4) & 0x0F == 7


@pytest.mark.parametrize("name", list(MODES))
def test_reset_screen_clears_the_mode_and_homes(emu, name):
    set_mode(emu, name)
    fill_screen(emu, name, lambda k: 0x41)
    m = emu.memory
    m[addr(emu, "io_cx")], m[addr(emu, "io_cy")] = 9, 9
    call(emu, "reset_screen")
    assert set(screen(emu, name)) == {0x20}
    assert (m[addr(emu, "io_cx")], m[addr(emu, "io_cy")]) == (0, 0)


@pytest.mark.parametrize("name", list(MODES))
@pytest.mark.parametrize("n", [1, 3])
def test_scroll_up_moves_the_rows_in_the_modes_bank(emu, name, n):
    set_mode(emu, name)
    _, width, height, _ = MODES[name]
    fill_screen(emu, name, lambda k: 1 + (k // width) % 60)  # row r holds 1 + r
    m = emu.memory
    m[addr(emu, "io_cy")] = height - 1
    call(emu, "scroll_up", a=n)
    s = screen(emu, name)
    for row in range(height - n):
        assert set(s[row * width:(row + 1) * width]) == {1 + (row + n) % 60}, row
    for row in range(height - n, height):
        assert set(s[row * width:(row + 1) * width]) == {0x20}, row
    assert m[addr(emu, "io_cy")] == height - 1 - n


@pytest.mark.parametrize("name", list(MODES))
def test_newline_at_the_last_row_scrolls(emu, name):
    set_mode(emu, name)
    _, width, height, _ = MODES[name]
    fill_screen(emu, name, lambda k: 1 + (k // width) % 60)
    m = emu.memory
    m[addr(emu, "io_cy")], m[addr(emu, "io_cx")] = height - 1, 5
    call(emu, "newline")
    assert (m[addr(emu, "io_cy")], m[addr(emu, "io_cx")]) == (height - 1, 0)
    assert set(screen(emu, name)[(height - 1) * width:]) == {0x20}


@pytest.mark.parametrize("name", list(MODES))
def test_cursor_show_inverts_the_cell_in_the_modes_bank(emu, name):
    set_mode(emu, name)
    _, width, height, bank = MODES[name]
    m = emu.memory
    row, col = height - 1, width - 1
    cell = flat(bank, 0x0800 + row * width + col)
    m.write_flat(cell, 0x01)
    m[addr(emu, "io_cy")], m[addr(emu, "io_cx")] = row, col
    call(emu, "cursor_show")
    assert m.read_flat(cell) == 0x81
    call(emu, "cursor_hide")
    assert m.read_flat(cell) == 0x01


# ── kernal_screen_reset ────────────────────────────────────────────

def test_kernal_screen_reset_ends_quote_mode_and_the_window(emu):
    set_mode(emu, "80x25")
    for row, col, key in ((2, 3, "T"), (10, 40, "B")):   # a program's window
        kernal(emu, PLOT, x=row, y=col, carry=False)
        kernal(emu, BSOUT, a=ESC)
        kernal(emu, BSOUT, a=ord(key))
    kernal(emu, BSOUT, a=0x22)                           # and quote mode
    call(emu, "kernal_screen_reset")
    kernal(emu, SCRORG)
    assert (emu.x, emu.y) == (79, 24)                    # the full screen
    kernal(emu, PLOT, x=12, y=5, carry=False)
    kernal(emu, BSOUT, a=0x1D)                           # cursor right: moves
    assert emu.memory.read_flat(0x0800 + 12 * 80 + 5) == 0x20


# ── hygiene_after_userland ─────────────────────────────────────────

def test_hygiene_gates_the_sid_and_sets_cses_sysflags(emu):
    set_mode(emu, "80x25")
    m = emu.memory
    kernal(emu, SYSFLAGS, a=0x00, carry=False)           # the run premise's
    for reg in (0xD404, 0xD40B, 0xD412):
        m[reg] = 0x11
    call(emu, "hygiene_after_userland")
    assert all(m[reg] == 0 for reg in (0xD404, 0xD40B, 0xD412))
    kernal(emu, SYSFLAGS, carry=True)
    assert emu.a & 0xA0 == 0xA0                          # raw F-keys, Mega+Shift locked


# ── the default theme ──────────────────────────────────────────────

def test_the_default_theme_is_mega(emu):
    """The m65 build's default THEME is MEGA, 661: the MEGA65's own
    white on blue (screen.md § Theme System)."""
    call(emu, "theme_init")
    m = emu.memory
    assert (m[addr(emu, "theme_border")], m[addr(emu, "theme_bg")],
            m[addr(emu, "theme_fg")]) == (6, 6, 1)
