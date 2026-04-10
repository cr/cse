"""
test_editor_asm.py — ASM-level editor tests via C64Emu.

Tests the real editor.s code (gap buffer, scroll, render) against
actual screen RAM in the C64Emu emulator.  Replaces the pure-Python
mirror tests in test_editor.py with tests that exercise the actual ASM.

Requires: build/cmos/cse-cmos.prg (built by `make CPU=65c02`).
"""

import subprocess
import pathlib
import pytest

from c64emu import C64Emu, SCREEN, COLS, ROWS

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
    """Session-scoped: ensure PRG is built, return (prg_path, map_path)."""
    _ensure_built()
    return PRG, MAP


def make_emu(prg_map):
    """Create a C64Emu loaded with the CMOS PRG.  Runs theme_init +
    kernal_init + ed_ensure_init to get the editor to a usable state."""
    prg, map_path = prg_map
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    # Run essential init routines (the ones main.s runs at startup).
    # theme_init → restore_colors → kernal_init → ed_ensure_init
    emu.jsr(emu.sym("theme_init"))
    emu.jsr(emu.sym("restore_colors"))
    emu.jsr(emu.sym("kernal_init"))
    emu.jsr(emu.sym("ed_ensure_init"))
    return emu


# ── Helpers ─────────────────────────────────────────────────────────────────

def insert_text(emu, text):
    """Insert a PETSCII string into the editor gap buffer."""
    # Write NUL-terminated string to a safe RAM location
    buf = 0x3000
    for i, ch in enumerate(text):
        emu.memory[buf + i] = ch if isinstance(ch, int) else ord(ch)
    emu.memory[buf + len(text)] = 0
    # ed_insert_string: A/X = pointer
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

    def test_insert_single_char(self, prg_map):
        emu = make_emu(prg_map)
        insert_text(emu, b"A")
        assert read_back(emu) == b"A"

    def test_insert_line(self, prg_map):
        emu = make_emu(prg_map)
        insert_text(emu, b"HELLO WORLD")
        assert read_back(emu) == b"HELLO WORLD"

    def test_insert_with_newline(self, prg_map):
        emu = make_emu(prg_map)
        insert_text(emu, b"LINE1\rLINE2")
        data = read_back(emu)
        assert data == b"LINE1\rLINE2"

    def test_total_lines_after_insert(self, prg_map):
        emu = make_emu(prg_map)
        assert total_lines(emu) == 1  # empty buffer = 1 line
        insert_text(emu, b"A\rB\rC")
        assert total_lines(emu) == 3

    def test_dirty_flag(self, prg_map):
        emu = make_emu(prg_map)
        assert emu.memory[emu.sym("ed_dirty")] == 0
        insert_text(emu, b"X")
        assert emu.memory[emu.sym("ed_dirty")] != 0


# ── ed_new — reset buffer ──────────────────────────────────────────────────

class TestEdNew:
    """ed_new clears the buffer and resets state."""

    def test_new_clears_content(self, prg_map):
        emu = make_emu(prg_map)
        insert_text(emu, b"SOME TEXT\rLINE2")
        emu.jsr(emu.sym("ed_new"))
        assert total_lines(emu) == 1
        assert read_back(emu) == b""

    def test_new_clears_dirty(self, prg_map):
        emu = make_emu(prg_map)
        insert_text(emu, b"X")
        assert emu.memory[emu.sym("ed_dirty")] != 0
        emu.jsr(emu.sym("ed_new"))
        assert emu.memory[emu.sym("ed_dirty")] == 0


# ── ed_read_line — sequential line reader ──────────────────────────────────

LINE_BUF = 0x3100   # scratch buffer for ed_read_line output


class TestEdReadLine:
    """ed_read_line reads one line at a time for the assembler."""

    def _read_one_line(self, emu):
        """Call ed_read_line(buf), return (line_bytes, eof_flag).
        ed_read_line: A/X = buf ptr, returns length in A, X=0 ok / X=$FF eof."""
        emu.jsr(emu.sym("ed_read_line"),
                a=LINE_BUF & 0xFF, x=(LINE_BUF >> 8) & 0xFF)
        length = emu.a
        eof = (emu.x == 0xFF)
        if eof:
            return b"", True
        line = bytes(emu.memory[LINE_BUF + i] for i in range(length))
        return line, False

    def test_single_line(self, prg_map):
        emu = make_emu(prg_map)
        insert_text(emu, b"HELLO")
        emu.jsr(emu.sym("ed_read_rewind"))
        line, eof = self._read_one_line(emu)
        assert line == b"HELLO"

    def test_multi_line(self, prg_map):
        emu = make_emu(prg_map)
        insert_text(emu, b"AAA\rBBB\rCCC")
        emu.jsr(emu.sym("ed_read_rewind"))
        l1, _ = self._read_one_line(emu)
        l2, _ = self._read_one_line(emu)
        l3, _ = self._read_one_line(emu)
        assert l1 == b"AAA"
        assert l2 == b"BBB"
        assert l3 == b"CCC"

    def test_eof_after_last_line(self, prg_map):
        emu = make_emu(prg_map)
        insert_text(emu, b"ONLY")
        emu.jsr(emu.sym("ed_read_rewind"))
        _, eof = self._read_one_line(emu)
        # After reading the only line, next call should signal EOF
        _, eof2 = self._read_one_line(emu)
        assert eof2 is True
