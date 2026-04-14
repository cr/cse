"""
test_editor_asm.py — ASM-level editor tests via C64Emu.

Tests the real editor.s code (gap buffer, insert, read-back, line reader)
against the production binary.  Replaces the Python mirror anti-pattern.

Requires: build/cmos/cse-cmos.prg (auto-built by cse_prg fixture).
"""

import pytest
from c64emu import C64Emu

LINE_BUF = 0x3100   # scratch buffer for ed_read_line output


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

class TestGapBufferInsert:
    """ed_insert_string writes to the gap buffer, ed_read_byte reads it back."""

    def test_insert_single_char(self, cse_prg):
        emu = make_emu(cse_prg)
        insert_text(emu, b"A")
        assert read_back(emu) == b"A"

    def test_insert_line(self, cse_prg):
        emu = make_emu(cse_prg)
        insert_text(emu, b"HELLO WORLD")
        assert read_back(emu) == b"HELLO WORLD"

    def test_insert_with_newline(self, cse_prg):
        """ed_insert_string inserts CR raw (no auto-indent)."""
        emu = make_emu(cse_prg)
        insert_text(emu, b"LINE1\rLINE2")
        assert read_back(emu) == b"LINE1\rLINE2"

    def test_total_lines_after_insert(self, cse_prg):
        emu = make_emu(cse_prg)
        assert total_lines(emu) == 1
        insert_text(emu, b"A\rB\rC")
        assert total_lines(emu) == 3

    def test_dirty_flag(self, cse_prg):
        emu = make_emu(cse_prg)
        assert emu.memory[emu.sym("ed_dirty")] == 0
        insert_text(emu, b"X")
        assert emu.memory[emu.sym("ed_dirty")] != 0


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


# ── ed_read_line — sequential line reader ──────────────────────────────────

class TestEdReadLine:
    """ed_read_line reads one line at a time for the assembler."""

    def _read_one_line(self, emu):
        """Call ed_read_line(buf).  Returns (line_bytes, eof_flag)."""
        emu.jsr(emu.sym("ed_read_line"),
                a=LINE_BUF & 0xFF, x=(LINE_BUF >> 8) & 0xFF)
        if emu.x == 0xFF:
            return b"", True
        length = emu.a
        return bytes(emu.memory[LINE_BUF + i] for i in range(length)), False

    def test_single_line(self, cse_prg):
        emu = make_emu(cse_prg)
        insert_text(emu, b"HELLO")
        emu.jsr(emu.sym("ed_read_rewind"))
        line, _ = self._read_one_line(emu)
        assert line == b"HELLO"

    def test_multi_line(self, cse_prg):
        emu = make_emu(cse_prg)
        insert_text(emu, b"AAA\rBBB\rCCC")
        emu.jsr(emu.sym("ed_read_rewind"))
        l1, _ = self._read_one_line(emu)
        l2, _ = self._read_one_line(emu)
        l3, _ = self._read_one_line(emu)
        assert l1 == b"AAA"
        assert l2 == b"BBB"
        assert l3 == b"CCC"

    def test_eof_after_last_line(self, cse_prg):
        emu = make_emu(cse_prg)
        insert_text(emu, b"ONLY")
        emu.jsr(emu.sym("ed_read_rewind"))
        self._read_one_line(emu)
        _, eof = self._read_one_line(emu)
        assert eof is True
