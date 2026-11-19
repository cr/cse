"""test_m65_source_editor.py — the source editor and LINE_MAX on the m65 PRG (P2 T10).

Owner: doc/modules/editor.md

Contract source: [doc/modules/editor.md § On m65: the layout follows the mode](../../doc/modules/editor.md#on-m65-the-layout-follows-the-mode),
[doc/modules/gap_buffer.md](../../doc/modules/gap_buffer.md) (*On m65*: the
source region, `LINE_MAX`), [doc/modules/asm_src.md § Caveats](../../doc/modules/asm_src.md#caveats),
[doc/platform_layer.md § Screen save](../../doc/platform_layer.md#screen-save).

The debug m65 PRG, cold-started and driven through main_loop as in
test_m65_repl.py; RUN/STOP ($03 in the typing queue) enters and leaves
the editor.  Per mode (80 x 25, 40 x 25, 80 x 50):

- the layout: ED_ROWS = height - 3 text rows, the status bar on row
  height - 3 (all reversed; `free:2000-bfff` and `LLLL,CC` anchored
  to the right edge), the two REPL rows above the prompt below it;
- the source text in bank 2 (the source region), bank 0's program
  region untouched; `workend` is $BFFF;
- typing up to LINE_MAX 79 in 80 columns, 39 in 40 columns; a longer
  line shows `>` in 40 columns and cannot grow there;
- the REPL screen saved and restored (80 x 50 too); ESC 4 / 5 / 8
  switch nothing while the editor runs;
- scrolling keeps the status bar and the context rows;
- the assembler reads 79 columns (`;!N: truncated` past them),
  `warn_long_lines` warns past 79.
"""

import re

import pytest

from m65emu.harness import flat
from test_m65_repl import M65Session

STOP, RETURN, ESC, TAB = 0x03, 0x0D, 0x1B, 0xA0
ST_REPL, ST_EDIT = 1, 2
MODES = {"80x25": ("8", 80, 25), "40x25": ("4", 40, 25), "80x50": ("5", 80, 50)}
SRC_LO, SRC_HI = 0x4000, 0xC000          # the source region's offsets, bank 2


@pytest.fixture
def s(cse_m65_prg, m65_snapshot):
    return M65Session(cse_m65_prg, m65_snapshot)


def in_mode(s, name):
    key, width, height = MODES[name]
    if name != "80x25":
        s.mode(key)
    assert (s.width, s.height) == (width, height)
    return width, height


def raw(s, r):
    width = s.width
    base = flat(s.v("scr_bank"), 0x0800 + r * width)
    return [s.e.memory.read_flat(base + c) for c in range(width)]


def edit(s):
    s.keys(bytes([STOP]))
    assert s.v("state") == ST_EDIT


def leave(s):
    s.keys(bytes([STOP]))
    assert s.v("state") == ST_REPL


def source(s):
    """The buffer's text, pre-gap then post-gap, read in bank 2."""
    m = s.e.memory

    def span(a, b):
        return bytes(m.read_flat(flat(2, k)) for k in range(a, b))
    return span(s.w("buf_base"), s.w("gap_lo")) + span(s.w("gap_hi"), SRC_HI)


def put_source(s, text):
    """Lines into the buffer as a load inserts them (gb_insert), cursor at the end."""
    s.call("ed_ensure_init")
    for ch in text:
        s.call("gb_insert", a=ch)


def load_source(s, text):
    """put_source, then rewound as ed_load_source leaves it: the gap at
    the start, the view at the top."""
    put_source(s, text)
    for _ in text:
        s.call("gb_cursor_left")
    top = s.cell("ed_top_ptr")
    s.e.memory[top], s.e.memory[top + 1] = s.e.memory[s.cell("buf_base")], \
        s.e.memory[s.cell("buf_base") + 1]


# ── the layout ─────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(MODES))
def test_layout_status_bar_and_context_rows(s, name):
    width, height = in_mode(s, name)
    s.type("? 1")
    s.type("? 2")
    cy = s.v("io_cy")
    above = [s.row(cy - 2), s.row(cy - 1)]
    edit(s)
    assert s.v("scr_ed_rows") == height - 3
    bar = raw(s, height - 3)
    assert all(c & 0x80 for c in bar), "the status bar is reversed"
    text = s.row(height - 3)
    assert text[width - 21:width - 7] == "free:2000-bfff"
    assert text[width - 7:] == "   1,09"            # line 1, the seeded tab's col 9
    assert text[:width - 21].strip() == ""
    assert [s.row(height - 2), s.row(height - 1)] == above
    assert s.v("io_cy") == 0 and s.v("io_cx") == 8   # the cursor after the seed tab


@pytest.mark.parametrize("name", list(MODES))
def test_typed_text_lands_in_bank_2_and_renders(s, name):
    in_mode(s, name)
    for k in range(SRC_LO, SRC_HI, 0x0400):          # bank 0's program region: a pattern
        s.e.memory.write_flat(flat(0, k), 0xA5)
    edit(s)
    s.keys(b"LDA #1\rRTS")
    assert source(s) == b"\xa0LDA #1\r\xa0RTS"
    assert s.row(0) == "        lda #1"
    assert s.row(1) == "        rts"
    assert all(s.e.memory.read_flat(flat(0, k)) == 0xA5 for k in range(SRC_LO, SRC_HI, 0x0400))
    assert SRC_LO <= s.w("buf_base") < SRC_HI


def test_workend_is_the_program_regions_end(s):
    edit(s)
    s.keys(b"NOP")
    leave(s)
    s.type("? workend")
    s.find(r"^; \$bfff  49151$")


# ── LINE_MAX and the caps ──────────────────────────────────────────

@pytest.mark.parametrize("name,cap", [("80x25", 79), ("40x25", 39), ("80x50", 79)])
def test_typing_stops_at_the_cap(s, name, cap):
    in_mode(s, name)
    edit(s)
    s.keys(b"X" * 100)
    assert source(s) == b"\xa0" + b"X" * (cap - 8)
    assert s.v("ed_cur_col") == cap


def test_a_long_line_shows_gt_in_40_columns_and_cannot_grow(s):
    edit(s)
    s.keys(b"Y" * 60)                                 # 68 columns, in 80
    leave(s)
    s.mode("4")
    edit(s)
    assert raw(s, 0)[39] == 0x3E                      # '>' in col 39, not reversed
    before = source(s)
    s.keys(b"\x11")                                   # cursor down: stays on line 1
    s.keys(b"Z")
    assert source(s) == before


@pytest.mark.parametrize("name", list(MODES))
def test_right_stops_at_the_last_column(s, name):
    width, _ = in_mode(s, name)
    load_source(s, b"Q" * (width + 5) + b"\r")
    edit(s)
    s.keys(b"\x1d" * (width + 10))                    # cursor right
    assert s.v("ed_cur_col") == width - 1


# ── the screen save, the mode keys, scrolling ─────────────────────

@pytest.mark.parametrize("name", list(MODES))
def test_the_repl_screen_is_saved_and_restored(s, name):
    _, height = in_mode(s, name)
    for k in range(height - 1):
        s.type(f"? {k}")
    before = s.rows()
    cursor = (s.v("io_cy"), s.v("io_cx"))
    edit(s)
    s.keys(b"LDA #2\r" * 3)
    leave(s)
    assert s.rows() == before
    assert (s.v("io_cy"), s.v("io_cx")) == cursor


def test_esc_mode_keys_switch_nothing_in_the_editor(s):
    edit(s)
    s.keys(bytes([ESC]) + b"4")
    assert (s.width, s.height) == (80, 25)
    assert s.v("state") == ST_EDIT
    leave(s)
    s.mode("5")                                       # the REPL still switches
    assert s.height == 50


@pytest.mark.parametrize("name", list(MODES))
def test_scrolling_keeps_the_status_bar_and_the_context(s, name):
    _, height = in_mode(s, name)
    edit(s)
    rows = height - 3
    bar, ctx = s.row(height - 3), [s.row(height - 2), s.row(height - 1)]
    s.keys(b"".join(b"L%d\r" % k for k in range(rows + 2)))
    assert s.v("ed_top_line") == 3
    assert s.row(0) == "        l3"                   # the seed tab, then L3
    assert s.row(rows - 2) == f"        l{rows + 1}"
    assert s.row(rows - 1) == ""                      # the new line: its tab
    free = s.width - 7                                # the bar up to the position field
    assert s.row(height - 3)[1:free] == bar[1:free]      # col 0: the dirty '*'
    assert [s.row(height - 2), s.row(height - 1)] == ctx
    for k in range(4):                                # back up past the top: scroll down
        s.keys(b"\x91" * rows)
    assert s.v("ed_top_line") == 0
    assert s.row(0) == "        l0"


# ── the assembler and warn_long_lines at LINE_MAX ─────────────────

def test_the_assembler_reads_79_characters(s):
    put_source(s, b"\xa0NOP ;" + b"C" * 73 + b"\r")   # 79 bytes: read whole
    put_source(s, b"\xa0NOP ;" + b"D" * 74 + b"\r")   # 80: truncated
    s.type("a")
    rows = s.screen()
    assert ";!2: truncated" in rows
    assert ";!1: truncated" not in rows


def test_warn_long_lines_past_79(s):
    put_source(s, b"\xa0" + b"E" * 71 + b"\r")        # 79 columns: no warning
    put_source(s, b"\xa0" + b"F" * 72 + b"\r")        # 80
    s.call("warn_long_lines")
    text = s.screen()
    assert re.search(r";!long L2\b", text)
    assert not re.search(r";!long L1\b", text)


# ── a mode change between visits ──────────────────────────────────

def test_a_cursor_past_the_last_column_comes_back_on_entry(s):
    """A cursor at col 68 (80 columns) is at its line's start when the
    editor opens in 40 columns: on the screen, the line kept."""
    edit(s)
    s.keys(b"Y" * 60)
    leave(s)
    s.mode("4")
    edit(s)
    assert s.v("ed_cur_col") == 0
    assert s.v("io_cx") == 0 and s.v("io_cy") == 0
    assert source(s) == b"\xa0" + b"Y" * 60


def test_a_cursor_below_the_last_row_comes_back_on_entry(s):
    """A cursor on row 40 (80 x 50) makes its line the top when the
    editor opens in 80 x 25."""
    s.mode("5")
    edit(s)
    s.keys(b"".join(b"L%d\r" % k for k in range(40)))
    assert s.w("ed_cur_line") == 40 and s.w("ed_top_line") == 0
    leave(s)
    s.mode("8")
    edit(s)
    assert s.w("ed_top_line") == 40
    assert s.v("io_cy") == 0
    assert s.row(0) == ""                             # line 40: its seed tab
    s.keys(b"\x91")                                   # up: scrolls one line back
    assert s.w("ed_top_line") == 39 and s.row(0) == "        l39"
