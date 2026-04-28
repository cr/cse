"""
test_editor_asm.py — ASM-level editor tests via C64Emu.

Tests the real editor.s code (gap buffer, insert, read-back, line reader)
against the production binary.  Replaces the Python mirror anti-pattern.

Requires: build/cmos/cse-cmos.prg (auto-built by cse_prg fixture).
"""

import pytest
from c64emu import C64Emu


def make_emu(cse_prg):
    """Fresh C64Emu with CMOS PRG loaded + editor initialized."""
    prg, map_path = cse_prg
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.init_cse(editor=True)
    return emu


def insert_text(emu, text):
    """Insert a PETSCII string into the editor gap buffer."""
    buf = 0x3000
    for i, ch in enumerate(text):
        emu.memory[buf + i] = ch if isinstance(ch, int) else ord(ch)
    emu.memory[buf + len(text)] = 0
    emu.jsr(emu.sym("ed_insert_string"), a=buf & 0xFF, x=(buf >> 8) & 0xFF)


def read_back(emu):
    """Read the entire gap buffer content via ed_read_rewind + ed_read_byte."""
    emu.jsr(emu.sym("ed_read_rewind"))
    result = []
    for _ in range(10000):
        emu.jsr(emu.sym("ed_read_byte"))
        if emu.a == 0xFF and emu.x == 0xFF:
            break
        result.append(emu.a)
    return bytes(result)


def total_lines(emu):
    """Read ed_total_lines (16-bit)."""
    addr = emu.sym("ed_total_lines")
    return emu.memory[addr] | (emu.memory[addr + 1] << 8)


# ── Gap buffer: insert + read back ─────────────────────────────────────────
#
# TestGapBufferInsert moved to tests/unit/test_gap_buffer.py at the
# 2026-04-20 editor/gap_buffer split.  The tests exercise pure gap-
# buffer primitives (ed_insert_string, ed_read_byte, ed_total_lines,
# ed_dirty) that now live in gap_buffer.s (L3) and bundle-test at
# Tier U against real zp + strings + mem + symtab — no C64Emu, no
# full PRG.  Same coverage, ~50x faster per test.  See
# doc/testing.md § Principle 9 Pattern B (subsumed).


# ── Smart indent (ed_handle_key RETURN) ───────────────────────────────────

def type_keys(emu, keys):
    """Feed keystrokes through ed_handle_key one at a time."""
    for ch in keys:
        code = ch if isinstance(ch, int) else ord(ch)
        emu.jsr(emu.sym("ed_handle_key"), a=code)


class TestSmartIndent:
    """Smart indent: BOL early-out, strip tabs around cursor, colon strips line."""

    # ── Normal RETURN (end of line) ──

    def test_return_eol(self, cse_prg):
        """RETURN at end of instruction line → CR + tab."""
        emu = make_emu(cse_prg)
        type_keys(emu, b"LDA #1")
        type_keys(emu, b"\r")
        assert read_back(emu) == b"LDA #1\r\xa0"

    def test_return_multiple(self, cse_prg):
        """Each RETURN adds tab on new line."""
        emu = make_emu(cse_prg)
        type_keys(emu, b"A\rB\r")
        assert read_back(emu) == b"A\r\xa0B\r\xa0"

    # ── BOL early-out: just CR, no tab ──

    def test_return_bol_before_label(self, cse_prg):
        """RETURN at col 0 before label → just CR, label stays put."""
        emu = make_emu(cse_prg)
        insert_text(emu, b"MAIN:")
        type_keys(emu, [0x13])  # HOME
        type_keys(emu, b"\r")
        assert read_back(emu) == b"\rMAIN:"

    def test_return_bol_before_tabbed(self, cse_prg):
        """RETURN at col 0 before tabbed content → just CR."""
        emu = make_emu(cse_prg)
        insert_text(emu, b"\xa0RTS")
        type_keys(emu, [0x13])  # HOME
        type_keys(emu, b"\r")
        assert read_back(emu) == b"\r\xa0RTS"

    def test_return_bol_empty(self, cse_prg):
        """RETURN on empty line at col 0 → just CR."""
        emu = make_emu(cse_prg)
        type_keys(emu, b"\r")
        assert read_back(emu) == b"\r"

    # ── Strip tabs around cursor on split ──

    def test_split_strips_left_tab(self, cse_prg):
        """Split after gutter: left tab stripped, new line gets tab."""
        emu = make_emu(cse_prg)
        insert_text(emu, b"\xa0RTS")
        type_keys(emu, [0x13])  # HOME
        type_keys(emu, [0x1D])  # RIGHT over tab
        type_keys(emu, b"\r")
        assert read_back(emu) == b"\r\xa0RTS"

    # ── Smart colon: strips leading tab on keystroke ──

    def test_colon_strips_gutter(self, cse_prg):
        """Typing ':' removes leading $A0 in real time."""
        emu = make_emu(cse_prg)
        # Seed tab with correct ed_cur_col via C=+SPACE keystroke
        type_keys(emu, [0xA0])
        type_keys(emu, b"LOOP:")
        assert read_back(emu) == b"LOOP:"

    def test_colon_in_comment_no_strip(self, cse_prg):
        """Typing ':' at EOL after ';' does NOT strip gutter."""
        emu = make_emu(cse_prg)
        type_keys(emu, [0xA0])
        type_keys(emu, b"; NOTE:")
        # Semicolon in line → colon is in a comment, gutter stays
        assert read_back(emu)[:1] == b"\xa0"

    def test_colon_mid_line_no_strip(self, cse_prg):
        """Typing ':' mid-line does NOT strip gutter."""
        emu = make_emu(cse_prg)
        # Insert "\xa0LDA :" raw with cursor mid-line (content after colon)
        insert_text(emu, b"\xa0LDA ")
        # Cursor col not tracked by insert_text, so type via keystroke
        # to get correct col tracking. Use a fresh emu instead:
        emu = make_emu(cse_prg)
        type_keys(emu, [0xA0])       # tab
        type_keys(emu, b"LDA #")
        # Now insert content AFTER cursor position via raw insert
        insert_text(emu, b"00")
        # Move left to be before "00"
        type_keys(emu, [0x9D, 0x9D])  # LEFT LEFT
        # Type colon here (mid-line, not EOL)
        type_keys(emu, b":")
        # Gutter should still be there — colon is not at EOL
        assert read_back(emu)[:1] == b"\xa0"

    def test_colon_at_return(self, cse_prg):
        """RETURN after colon: label at col 0, new line gets tab."""
        emu = make_emu(cse_prg)
        type_keys(emu, [0xA0])  # tab (sets ed_cur_col = TAB_WIDTH)
        type_keys(emu, b"MAIN:")
        type_keys(emu, b"\r")
        assert read_back(emu) == b"MAIN:\r\xa0"

    def test_split_label_tab_rts(self, cse_prg):
        """Split label:\\xa0rts: label loses gutter, rts gets tab."""
        emu = make_emu(cse_prg)
        # Type label + tab + instruction via keystrokes
        type_keys(emu, b"LOOP:")
        type_keys(emu, [0xA0])  # C=+SPACE (tab)
        type_keys(emu, b"RTS")
        # Move cursor to between : and tab
        type_keys(emu, [0x13])  # HOME
        for _ in range(6):      # RIGHT over L O O P : = 5 chars at col 0
            type_keys(emu, [0x1D])
        type_keys(emu, b"\r")
        assert read_back(emu) == b"LOOP:\r\xa0RTS"


# ── ed_new — reset buffer ──────────────────────────────────────────────────

class TestEdNew:
    """ed_new clears the buffer and resets state."""

    def test_new_clears_content(self, cse_prg):
        emu = make_emu(cse_prg)
        insert_text(emu, b"SOME TEXT\rLINE2")
        emu.jsr(emu.sym("ed_new"))
        assert total_lines(emu) == 1
        assert read_back(emu) == b""

    def test_new_clears_dirty(self, cse_prg):
        emu = make_emu(cse_prg)
        insert_text(emu, b"X")
        emu.jsr(emu.sym("ed_new"))
        assert emu.memory[emu.sym("ed_dirty")] == 0


# ── enter_editor smart-indent seed ────────────────────────────────────────

class TestEnterEditorSeed:
    """The smart-indent seed in enter_editor inserts a single $A0
    (tab) byte only when the buffer is **truly empty**.  Empty
    means both halves of the gap-buffer envelope are at their
    init positions — no content before the gap (`gap_lo ==
    buf_base`) AND no content after (`gap_hi == BUF_END`).

    Pre-fix bug (TODO.md): only the first half was checked.  After
    `l NAME` (load source), the cursor is rewound to the start so
    `gap_lo == buf_base` even though the loaded source lives in
    `[gap_hi, BUF_END)`.  enter_editor's emptiness test fired
    spuriously and inserted a leading tab into the loaded file.
    """

    def test_seed_on_truly_empty_buffer(self, cse_prg):
        """Empty buffer + enter_editor → exactly one $A0 byte
        seeded, ed_cur_col = TAB_WIDTH, ed_dirty stays 0."""
        emu = make_emu(cse_prg)
        # Buffer is empty after init_cse(editor=True).
        emu.jsr(emu.sym("enter_editor"))
        assert read_back(emu) == b"\xa0"
        # Smart indent leaves ed_dirty=0 (seed is not a user edit).
        assert emu.memory[emu.sym("ed_dirty")] == 0

    def test_no_seed_when_loaded_buffer_at_start(self, cse_prg):
        """Loaded source + cursor rewound to start → enter_editor
        must NOT insert a tab.  Simulates the post-`l` state where
        gap_lo == buf_base but content lives in [gap_hi, BUF_END)."""
        emu = make_emu(cse_prg)
        # Insert content (cursor ends up at end of inserted text).
        insert_text(emu, b"LOADED\rTEXT")
        # Mimic ed_load_source's @rewind loop: walk cursor to start.
        emu.jsr(emu.sym("gb_home"))            # to start of last line
        # gb_home only goes to start of current line — repeat
        # gb_cursor_left until gap_lo == buf_base.
        for _ in range(64):
            gap_lo = (emu.memory[emu.sym("gap_lo")]
                      | (emu.memory[emu.sym("gap_lo") + 1] << 8))
            buf_base = (emu.memory[emu.sym("buf_base")]
                        | (emu.memory[emu.sym("buf_base") + 1] << 8))
            if gap_lo == buf_base:
                break
            emu.jsr(emu.sym("gb_cursor_left"))
        else:
            pytest.fail("could not rewind cursor to buf_base")

        emu.jsr(emu.sym("enter_editor"))
        # Buffer must be exactly what was loaded — no leading $A0.
        assert read_back(emu) == b"LOADED\rTEXT"

    def test_no_seed_when_buffer_has_content_before_gap(self, cse_prg):
        """Non-empty buffer with cursor at end (post-typing state)
        → enter_editor must NOT insert a tab.  This is the case the
        original `gap_lo == buf_base` check correctly rejected; the
        regression guard ensures the new (stricter) check still
        rejects it."""
        emu = make_emu(cse_prg)
        insert_text(emu, b"X")
        emu.jsr(emu.sym("enter_editor"))
        assert read_back(emu) == b"X"


# ── ed_read_line — sequential line reader ──────────────────────────────────
#
# TestEdReadLine (incl. all 7 cases + the 4 Principle-13 position-pinning
# tests) moved to tests/unit/test_gap_buffer.py at the 2026-04-20
# editor/gap_buffer split.  ed_read_line is pure gap-buffer traversal
# (no screen, no KERNAL) and now lives in gap_buffer.s (L3); the tests
# run against the Tier U gap_buffer bundle instead of the full PRG via
# C64Emu.  Same coverage, ~50x faster per test.  See doc/testing.md
# § Principle 9 Pattern B (subsumed).
