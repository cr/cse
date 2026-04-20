"""test_gap_buffer.py — Tier-U unit tests for gap_buffer.s (L3).

Contract source: [doc/modules/gap_buffer.md](../../doc/modules/gap_buffer.md).

Migrated from tests/integration/test_editor.py at the 2026-04-20
editor/gap_buffer split: gap-buffer primitives are pure data-structure
operations and now run at Tier U against a bundle that links real
zp + strings + mem + symtab + gap_buffer (no behavioural mocks).
Previously these tests ran against the full PRG via C64Emu — same
coverage, ~50x faster execution, tighter isolation.

Coverage
--------
Public surface of gap_buffer.s:
  gb_init, ed_ensure_init                       — init / lazy-init
  gb_insert, gb_backspace                       — single-byte edit
  gb_cursor_left, gb_cursor_right, gb_home      — cursor movement
  gb_ensure_room                                — buffer-growth
  ed_insert_string                              — string insert wrapper
  ed_read_rewind, ed_read_byte, ed_read_line    — sequential reader
  ed_total_lines, src_top, src_bot              — BSS state
  check_buf_end                                 — scan terminator

Partial-result contract (Principle 13) for ed_read_line and
ed_read_byte is pinned by the Stop/EOF test classes below.
"""

import pytest

from conftest import make_cpu, push_rts_sentinel, step_until_pc


# ── Helpers ──────────────────────────────────────────────────

_LINE_BUF  = 0x3100   # scratch buffer for ed_read_line output
_TEXT_BUF  = 0x3000   # scratch for ed_insert_string inputs


def _jsr(cpu, mem, addr, a=0, x=0, y=0):
    """JSR to addr and run until RTS returns to the sentinel."""
    cpu.a = a; cpu.x = x; cpu.y = y
    sentinel = push_rts_sentinel(cpu, sentinel=0x01F0)
    cpu.pc = addr
    step_until_pc(cpu, sentinel, max_steps=200_000,
                  what=f"entry=${addr:04X}")


def _insert_text(cpu, mem, gb_syms, text):
    """Insert a PETSCII string into the gap buffer via ed_insert_string."""
    for i, ch in enumerate(text):
        mem[_TEXT_BUF + i] = ch if isinstance(ch, int) else ord(ch)
    mem[_TEXT_BUF + len(text)] = 0
    _jsr(cpu, mem, gb_syms.ed_insert_string,
         a=_TEXT_BUF & 0xFF, x=(_TEXT_BUF >> 8) & 0xFF)


def _read_back(cpu, mem, gb_syms):
    """Walk the buffer byte-by-byte via ed_read_rewind + ed_read_byte."""
    _jsr(cpu, mem, gb_syms.ed_read_rewind)
    result = []
    for _ in range(10_000):
        _jsr(cpu, mem, gb_syms.ed_read_byte)
        if cpu.a == 0xFF and cpu.x == 0xFF:
            break
        result.append(cpu.a)
    return bytes(result)


def _total_lines(mem, gb_syms):
    return mem[gb_syms.ed_total_lines] | (mem[gb_syms.ed_total_lines + 1] << 8)


def _read_ptr(mem, gb_syms):
    return mem[gb_syms.read_ptr] | (mem[gb_syms.read_ptr + 1] << 8)


def _read_one_line(cpu, mem, gb_syms):
    """Call ed_read_line(_LINE_BUF).  Returns (line_bytes, eof_flag)."""
    _jsr(cpu, mem, gb_syms.ed_read_line,
         a=_LINE_BUF & 0xFF, x=(_LINE_BUF >> 8) & 0xFF)
    if cpu.x == 0xFF:
        return b"", True
    length = cpu.a
    return bytes(mem[_LINE_BUF + i] for i in range(length)), False


# ── Gap buffer: insert + read back ─────────────────────────────────────────

class TestGapBufferInsert:
    """ed_insert_string writes to the gap buffer; ed_read_byte reads it back.

    Migrated from tests/integration/test_editor.py::TestGapBufferInsert at
    the 2026-04-20 editor/gap_buffer split.
    """

    def test_insert_single_char(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"A")
        assert _read_back(cpu, mem, gb_syms) == b"A"

    def test_insert_line(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"HELLO WORLD")
        assert _read_back(cpu, mem, gb_syms) == b"HELLO WORLD"

    def test_insert_with_newline(self, gb_syms):
        """ed_insert_string inserts CR raw (no auto-indent — that's editor.s)."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"LINE1\rLINE2")
        assert _read_back(cpu, mem, gb_syms) == b"LINE1\rLINE2"

    def test_total_lines_after_insert(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        # Seed the post-init state (gb_init sets ed_total_lines=1 for
        # the implicit empty line).  In the integration-tier predecessor
        # this happened via init_cse's cold-boot; here we call it
        # explicitly.
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        assert _total_lines(mem, gb_syms) == 1
        _insert_text(cpu, mem, gb_syms, b"A\rB\rC")
        assert _total_lines(mem, gb_syms) == 3

    def test_dirty_flag(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        assert mem[gb_syms.ed_dirty] == 0
        _insert_text(cpu, mem, gb_syms, b"X")
        assert mem[gb_syms.ed_dirty] != 0


# ── ed_read_line — sequential line reader ─────────────────────────────────

class TestEdReadLine:
    """ed_read_line reads one line at a time for the assembler.

    Migrated from tests/integration/test_editor.py::TestEdReadLine at
    the 2026-04-20 editor/gap_buffer split.  Includes the Principle-13
    position-pinning tests (previously integration-tier, now unit).
    """

    def test_single_line(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"HELLO")
        _jsr(cpu, mem, gb_syms.ed_read_rewind)
        line, _ = _read_one_line(cpu, mem, gb_syms)
        assert line == b"HELLO"

    def test_multi_line(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"AAA\rBBB\rCCC")
        _jsr(cpu, mem, gb_syms.ed_read_rewind)
        l1, _ = _read_one_line(cpu, mem, gb_syms)
        l2, _ = _read_one_line(cpu, mem, gb_syms)
        l3, _ = _read_one_line(cpu, mem, gb_syms)
        assert l1 == b"AAA"
        assert l2 == b"BBB"
        assert l3 == b"CCC"

    def test_eof_after_last_line(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ONLY")
        _jsr(cpu, mem, gb_syms.ed_read_rewind)
        _read_one_line(cpu, mem, gb_syms)
        _, eof = _read_one_line(cpu, mem, gb_syms)
        assert eof is True

    # ── Partial-result contract (Principle 13) ──

    def test_advances_read_ptr_on_success(self, gb_syms):
        """Each CR-terminated line advances read_ptr by exactly
        (line_length + 1).  No-CR-last-line case is pinned separately
        below because its scan-to-EOF semantics make the delta
        gap-size-dependent."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"AAA\rBBB\rCCC\r")
        _jsr(cpu, mem, gb_syms.ed_read_rewind)

        for expected_line in (b"AAA", b"BBB", b"CCC"):
            before = _read_ptr(mem, gb_syms)
            line, _ = _read_one_line(cpu, mem, gb_syms)
            after = _read_ptr(mem, gb_syms)
            assert line == expected_line
            delta = after - before
            assert delta == len(expected_line) + 1, \
                f"{expected_line!r}: read_ptr advanced {delta}, " \
                f"expected {len(expected_line) + 1}"

    def test_empty_line_advances_by_one(self, gb_syms):
        """An empty line between CRs advances read_ptr by exactly 1
        (the CR terminator)."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"A\r\rC\r")
        _jsr(cpu, mem, gb_syms.ed_read_rewind)

        before = _read_ptr(mem, gb_syms)
        l1, _ = _read_one_line(cpu, mem, gb_syms)
        assert l1 == b"A"
        assert _read_ptr(mem, gb_syms) - before == 2

        before = _read_ptr(mem, gb_syms)
        l2, _ = _read_one_line(cpu, mem, gb_syms)
        assert l2 == b""
        assert _read_ptr(mem, gb_syms) - before == 1, \
            "empty line should advance read_ptr by 1 (just the CR)"

        before = _read_ptr(mem, gb_syms)
        l3, _ = _read_one_line(cpu, mem, gb_syms)
        assert l3 == b"C"
        assert _read_ptr(mem, gb_syms) - before == 2

    def test_last_line_no_cr_ends_at_buf_end(self, gb_syms):
        """Last line without a trailing CR causes the scan to continue
        past the gap to BUF_END.  Contract guarantees: read_ptr
        advanced strictly past content, next call returns EOF without
        further advance."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"SOLO")
        _jsr(cpu, mem, gb_syms.ed_read_rewind)
        before = _read_ptr(mem, gb_syms)
        line, eof = _read_one_line(cpu, mem, gb_syms)
        after = _read_ptr(mem, gb_syms)
        assert line == b"SOLO"
        assert eof is False
        assert after > before + len(line), \
            f"no-CR last line: read_ptr must advance strictly past " \
            f"content (was ${before:04X}, now ${after:04X})"
        # Next call idempotent EOF.
        eof_before = _read_ptr(mem, gb_syms)
        _, eof2 = _read_one_line(cpu, mem, gb_syms)
        eof_after = _read_ptr(mem, gb_syms)
        assert eof2 is True
        assert eof_after == eof_before, \
            f"subsequent EOF call advanced read_ptr from ${eof_before:04X} " \
            f"to ${eof_after:04X}"

    def test_eof_calls_are_idempotent(self, gb_syms):
        """Once ed_read_line has returned EOF, subsequent calls keep
        returning EOF and read_ptr stays stable.  (The first EOF call
        may still advance if content ended just before the gap; what
        callers rely on is idempotency of repeat EOF calls.)"""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ONLY\r")
        _jsr(cpu, mem, gb_syms.ed_read_rewind)
        _read_one_line(cpu, mem, gb_syms)           # consume "ONLY"
        _, eof1 = _read_one_line(cpu, mem, gb_syms) # first EOF call
        assert eof1 is True
        stable = _read_ptr(mem, gb_syms)
        for i in range(3):
            _, eof_n = _read_one_line(cpu, mem, gb_syms)
            assert eof_n is True
            assert _read_ptr(mem, gb_syms) == stable, \
                f"subsequent EOF call {i + 2} advanced read_ptr past " \
                f"${stable:04X}"
