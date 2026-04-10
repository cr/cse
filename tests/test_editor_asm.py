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
