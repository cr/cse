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


# ── gb_backspace — delete byte before the gap ─────────────────────────────

def _gap_lo(mem, gb_syms):
    return mem[gb_syms.gap_lo] | (mem[gb_syms.gap_lo + 1] << 8)

def _gap_hi(mem, gb_syms):
    return mem[gb_syms.gap_hi] | (mem[gb_syms.gap_hi + 1] << 8)

def _buf_base(mem, gb_syms):
    return mem[gb_syms.buf_base] | (mem[gb_syms.buf_base + 1] << 8)

def _word(mem, addr):
    return mem[addr] | (mem[addr + 1] << 8)


class TestGbBackspace:
    """gb_backspace deletes the byte at (gap_lo - 1): gap_lo
    decrements by 1, ed_total_lines decrements if the deleted byte
    was a CR, ed_dirty set.  Backspacing at buf_base (empty pre-gap)
    is a no-op.
    """

    def test_single_char_then_backspace(self, gb_syms):
        """Insert 'A', backspace → buffer empty; read_back returns ''."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"A")
        _jsr(cpu, mem, gb_syms.gb_backspace)
        assert _read_back(cpu, mem, gb_syms) == b""

    def test_multi_char_backspace_shortens_by_one(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"HELLO")
        _jsr(cpu, mem, gb_syms.gb_backspace)
        assert _read_back(cpu, mem, gb_syms) == b"HELL"

    def test_backspace_decrements_gap_lo(self, gb_syms):
        """Principle-13 ancillary state: gb_backspace decrements gap_lo
        by exactly 1 on success, leaves gap_hi unchanged."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ABC")
        before_lo = _gap_lo(mem, gb_syms)
        before_hi = _gap_hi(mem, gb_syms)
        _jsr(cpu, mem, gb_syms.gb_backspace)
        after_lo = _gap_lo(mem, gb_syms)
        after_hi = _gap_hi(mem, gb_syms)
        assert before_lo - after_lo == 1, \
            f"gap_lo delta {before_lo - after_lo}, expected 1"
        assert after_hi == before_hi, \
            "gap_hi must stay fixed on backspace (gap grows on pre-gap side)"

    def test_backspace_across_cr_decrements_total_lines(self, gb_syms):
        """Deleting a CR decrements ed_total_lines by 1."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"A\rB")
        assert _total_lines(mem, gb_syms) == 2
        _jsr(cpu, mem, gb_syms.gb_backspace)    # deletes 'B'
        assert _total_lines(mem, gb_syms) == 2  # still 2 — no CR crossed
        _jsr(cpu, mem, gb_syms.gb_backspace)    # deletes CR
        assert _total_lines(mem, gb_syms) == 1, \
            "deleting CR must decrement ed_total_lines"

    def test_backspace_at_buf_base_is_noop(self, gb_syms):
        """With gap_lo == buf_base (nothing to delete), gb_backspace
        must leave all state unchanged."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        # gb_init leaves gap_lo == buf_base == BUF_END (empty pre-gap).
        before_lo = _gap_lo(mem, gb_syms)
        before_base = _buf_base(mem, gb_syms)
        _jsr(cpu, mem, gb_syms.gb_backspace)
        assert _gap_lo(mem, gb_syms) == before_lo, \
            "gap_lo changed despite empty pre-gap"
        assert _buf_base(mem, gb_syms) == before_base


# ── gb_cursor_left / gb_cursor_right — gap movement ──────────────────────

class TestGbCursorMove:
    """The gap-move primitives shift a single byte across the gap:
    gb_cursor_left moves a byte from pre-gap to post-gap (gap_lo and
    gap_hi both decrement by 1); gb_cursor_right does the reverse.
    Net visible content is unchanged — confirmed by read-back.
    Movement at the respective buffer end is a no-op.
    """

    def test_cursor_left_preserves_content(self, gb_syms):
        """Insert 'ABCD', cursor_left ×2, read_back → still 'ABCD'."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ABCD")
        _jsr(cpu, mem, gb_syms.gb_cursor_left)
        _jsr(cpu, mem, gb_syms.gb_cursor_left)
        assert _read_back(cpu, mem, gb_syms) == b"ABCD"

    def test_cursor_left_then_right_round_trip(self, gb_syms):
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ABCD")
        before_lo, before_hi = _gap_lo(mem, gb_syms), _gap_hi(mem, gb_syms)
        _jsr(cpu, mem, gb_syms.gb_cursor_left)
        _jsr(cpu, mem, gb_syms.gb_cursor_right)
        assert _gap_lo(mem, gb_syms) == before_lo
        assert _gap_hi(mem, gb_syms) == before_hi
        assert _read_back(cpu, mem, gb_syms) == b"ABCD"

    def test_cursor_left_decrements_gap_by_one(self, gb_syms):
        """Principle-13 ancillary state: gb_cursor_left decrements
        gap_lo AND gap_hi by exactly 1 (one byte shifted across)."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ABC")
        before_lo, before_hi = _gap_lo(mem, gb_syms), _gap_hi(mem, gb_syms)
        _jsr(cpu, mem, gb_syms.gb_cursor_left)
        assert _gap_lo(mem, gb_syms) == before_lo - 1
        assert _gap_hi(mem, gb_syms) == before_hi - 1

    def test_cursor_right_increments_gap_by_one(self, gb_syms):
        """Principle-13 ancillary state: gb_cursor_right increments
        gap_lo AND gap_hi by exactly 1 (one byte shifted across)."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ABC")
        _jsr(cpu, mem, gb_syms.gb_cursor_left)    # pre-position
        _jsr(cpu, mem, gb_syms.gb_cursor_left)
        before_lo, before_hi = _gap_lo(mem, gb_syms), _gap_hi(mem, gb_syms)
        _jsr(cpu, mem, gb_syms.gb_cursor_right)
        assert _gap_lo(mem, gb_syms) == before_lo + 1
        assert _gap_hi(mem, gb_syms) == before_hi + 1

    def test_cursor_left_at_buf_base_is_noop(self, gb_syms):
        """cursor_left at gap_lo == buf_base leaves state unchanged."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        before_lo, before_hi = _gap_lo(mem, gb_syms), _gap_hi(mem, gb_syms)
        _jsr(cpu, mem, gb_syms.gb_cursor_left)
        assert _gap_lo(mem, gb_syms) == before_lo
        assert _gap_hi(mem, gb_syms) == before_hi

    def test_cursor_right_at_buf_end_is_noop(self, gb_syms):
        """cursor_right at gap_hi == BUF_END leaves state unchanged
        (post-gap region is empty)."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ABC")
        # After insert, gap_hi == BUF_END (no post-gap content).
        before_lo, before_hi = _gap_lo(mem, gb_syms), _gap_hi(mem, gb_syms)
        _jsr(cpu, mem, gb_syms.gb_cursor_right)
        assert _gap_lo(mem, gb_syms) == before_lo
        assert _gap_hi(mem, gb_syms) == before_hi


# ── gb_home — move cursor to start of current line ───────────────────────

class TestGbHome:
    """gb_home walks gap_lo backward (via gb_cursor_left) until it
    reaches buf_base OR the byte immediately before gap_lo is CR.
    Result: gap is positioned at the start of the logical line the
    cursor was on.  Content is preserved.
    """

    def test_single_line_home_goes_to_buf_base(self, gb_syms):
        """With no CRs in the buffer, gb_home walks back to buf_base."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ABC")
        _jsr(cpu, mem, gb_syms.gb_home)
        assert _gap_lo(mem, gb_syms) == _buf_base(mem, gb_syms), \
            "single-line home should land at buf_base"
        # Content preserved
        assert _read_back(cpu, mem, gb_syms) == b"ABC"

    def test_multi_line_home_stops_after_cr(self, gb_syms):
        """gb_home from the middle of the last line stops immediately
        after the preceding CR — at the start of the current logical
        line."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"LINE1\rLINE2")
        # Before: gap at end (after "LINE2").
        #   buf layout: [L I N E 1 CR L I N E 2] gap ...
        #   gap_lo = buf_base + 11.  After home, gap_lo should be at
        #   buf_base + 6 (just after the CR).
        _jsr(cpu, mem, gb_syms.gb_home)
        expected = _buf_base(mem, gb_syms) + 6    # position of 'L' in LINE2
        assert _gap_lo(mem, gb_syms) == expected, \
            f"gap_lo after home: ${_gap_lo(mem, gb_syms):04X}, " \
            f"expected ${expected:04X} (one past the CR)"
        assert _read_back(cpu, mem, gb_syms) == b"LINE1\rLINE2"

    def test_home_at_line_start_is_noop(self, gb_syms):
        """If gap_lo is already at buf_base, gb_home makes no change."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"ABC")
        _jsr(cpu, mem, gb_syms.gb_home)
        before = _gap_lo(mem, gb_syms)
        _jsr(cpu, mem, gb_syms.gb_home)
        assert _gap_lo(mem, gb_syms) == before


# ── gb_ensure_room — buffer growth primitive ─────────────────────────────

class TestGbEnsureRoom:
    """gb_ensure_room grows the buffer by 256 bytes when the gap is
    exhausted, by decrementing buf_base and shifting the pre-gap
    content down.  src_bot tracks buf_base.  Returns C=0 at BUF_FLOOR.
    """

    def test_first_insert_triggers_growth(self, gb_syms):
        """After gb_init, gap is empty (gap_lo == gap_hi == BUF_END).
        First gb_insert must call gb_ensure_room, which drops buf_base
        by $100 and updates src_bot to match."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        before_base = _buf_base(mem, gb_syms)
        assert before_base == gb_syms.BUF_END, \
            "gb_init should leave buf_base == BUF_END"
        _insert_text(cpu, mem, gb_syms, b"X")
        after_base = _buf_base(mem, gb_syms)
        assert before_base - after_base == 0x100, \
            f"buf_base should drop by $100; got ${before_base - after_base:04X}"
        # src_bot must track buf_base
        src_bot = _word(mem, gb_syms.src_bot)
        assert src_bot == after_base, \
            f"src_bot (${src_bot:04X}) must equal buf_base (${after_base:04X})"

    def test_growth_preserves_content(self, gb_syms):
        """Inserting enough bytes to trigger multiple growth rounds
        must preserve the content (the pre-gap block-copy during
        growth must not corrupt bytes).  Uses printable ASCII only
        to avoid NUL terminators in _insert_text and CR-line-count
        side-effects."""
        cpu, mem = make_cpu(gb_syms)
        # 300 bytes > $100 forces at least two growth rounds.
        # 3 × 95 printable = 285 > $100 — at least two growth rounds.
        payload = bytes(range(0x20, 0x7F)) * 3
        assert len(payload) > 0x100
        assert 0 not in payload and 0x0D not in payload
        _insert_text(cpu, mem, gb_syms, payload)
        assert _read_back(cpu, mem, gb_syms) == payload

    def test_out_of_memory_returns_carry_clear(self, gb_syms):
        """Force buf_base to BUF_FLOOR, gap == 0 (empty), then call
        gb_ensure_room — must return C=0 without modifying buf_base."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        # Set buf_base = BUF_FLOOR, gap_lo = gap_hi = BUF_FLOOR (no room).
        floor = gb_syms.BUF_FLOOR
        mem[gb_syms.buf_base]     = floor & 0xFF
        mem[gb_syms.buf_base + 1] = (floor >> 8) & 0xFF
        mem[gb_syms.gap_lo]       = floor & 0xFF
        mem[gb_syms.gap_lo + 1]   = (floor >> 8) & 0xFF
        mem[gb_syms.gap_hi]       = floor & 0xFF
        mem[gb_syms.gap_hi + 1]   = (floor >> 8) & 0xFF
        _jsr(cpu, mem, gb_syms.gb_ensure_room)
        assert cpu.p & 0x01 == 0, \
            "gb_ensure_room at BUF_FLOOR must return C=0 (no room)"
        # buf_base untouched
        assert _buf_base(mem, gb_syms) == floor


# ── define_ws_syms / update_workend — workspace symbol registration ──────

class TestWorkspaceSymbols:
    """define_ws_syms registers `workstart` = $0800 (fixed) and
    `workend` = buf_base - 1 (dynamic — tracks growth).  update_workend
    redefines `workend` alone after buf_base changes.  Both share a
    fallthrough in gap_buffer.s for byte savings.
    """

    def _lookup(self, cpu, mem, gb_syms, name_ptr):
        """Call sym_lookup(name_ptr) → (carry, val).  Returns
        (True, val) on hit, (False, None) on miss."""
        mem[gb_syms.sym_name]     = name_ptr & 0xFF
        mem[gb_syms.sym_name + 1] = (name_ptr >> 8) & 0xFF
        _jsr(cpu, mem, gb_syms.sym_lookup)
        if cpu.p & 0x01:    # C=1 → not found
            return False, None
        return True, _word(mem, gb_syms.sym_val)

    def test_define_ws_syms_registers_workstart(self, gb_syms):
        """After define_ws_syms, `workstart` symbol resolves to $0800."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.sym_clear)          # init symtab heap pointers
        _jsr(cpu, mem, gb_syms.ed_ensure_init)    # sets up buf_base
        _jsr(cpu, mem, gb_syms.define_ws_syms)
        hit, val = self._lookup(cpu, mem, gb_syms, gb_syms.s_workstart)
        assert hit, "workstart symbol not found after define_ws_syms"
        assert val == 0x0800, \
            f"workstart = ${val:04X}, expected $0800"

    def test_define_ws_syms_registers_workend(self, gb_syms):
        """After define_ws_syms, `workend` resolves to buf_base - 1."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.sym_clear)
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        _jsr(cpu, mem, gb_syms.define_ws_syms)
        hit, val = self._lookup(cpu, mem, gb_syms, gb_syms.s_workend)
        assert hit, "workend symbol not found"
        expected = (_buf_base(mem, gb_syms) - 1) & 0xFFFF
        assert val == expected, \
            f"workend = ${val:04X}, expected ${expected:04X}"

    def test_update_workend_tracks_growth(self, gb_syms):
        """After buffer growth (via ed_insert_string → gb_ensure_room →
        update_workend), the `workend` symbol value must follow the
        new buf_base."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.sym_clear)
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        _jsr(cpu, mem, gb_syms.define_ws_syms)
        _, initial = self._lookup(cpu, mem, gb_syms, gb_syms.s_workend)
        _insert_text(cpu, mem, gb_syms, b"X")     # triggers gb_ensure_room
        _, after = self._lookup(cpu, mem, gb_syms, gb_syms.s_workend)
        expected = (_buf_base(mem, gb_syms) - 1) & 0xFFFF
        assert after == expected, \
            f"workend not updated: got ${after:04X}, expected ${expected:04X}"
        assert after < initial, \
            f"workend should shrink on growth: ${initial:04X} → ${after:04X}"


# ── src_top / src_bot / check_buf_end — miscellaneous state ──────────────

class TestBufferBoundsState:
    """src_top (upper bound, set once by gb_init) and src_bot (lower
    bound, moves with gb_ensure_room).  check_buf_end is an internal
    helper transitively pinned by ed_read_line's EOF tests; this
    class ensures the bounds BSS symbols reflect the buffer state
    observable by the `i` command (REPL info)."""

    def test_src_top_set_by_init(self, gb_syms):
        """gb_init sets src_top = BUF_END."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        assert _word(mem, gb_syms.src_top) == gb_syms.BUF_END

    def test_src_bot_set_by_init(self, gb_syms):
        """gb_init sets src_bot = BUF_END (empty buffer)."""
        cpu, mem = make_cpu(gb_syms)
        _jsr(cpu, mem, gb_syms.ed_ensure_init)
        assert _word(mem, gb_syms.src_bot) == gb_syms.BUF_END

    def test_src_bot_tracks_buf_base_on_growth(self, gb_syms):
        """src_bot is updated by gb_ensure_room to match the new
        (lower) buf_base after growth."""
        cpu, mem = make_cpu(gb_syms)
        _insert_text(cpu, mem, gb_syms, b"X")     # triggers growth
        assert _word(mem, gb_syms.src_bot) == _buf_base(mem, gb_syms)
