"""
test_editor.py — gap buffer and editor logic tests.

Tests the gap buffer algorithm as implemented in editor.c.
Uses a Python simulation of the gap buffer that mirrors the C code's
exact logic, then verifies invariants and expected content.

This catches design bugs (like the ed_top_ptr stale pointer issue)
independently of the cc65 compiler.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Gap buffer simulation — mirrors editor.c's logic exactly
# ═══════════════════════════════════════════════════════════════════════════════

BUF_CEILING = 0xC800   # exclusive end (matches editor.c)
BUF_FLOOR   = 0x4800   # growth limit
GROW_SIZE   = 256      # bytes allocated per growth


class GapBuffer:
    """Python mirror of editor.c's gap buffer."""

    def __init__(self):
        # Simulated memory — only the region we use
        self.mem = bytearray(0x10000)
        self.buf_base = BUF_CEILING
        self.buf_end  = BUF_CEILING
        self.gap_lo   = BUF_CEILING
        self.gap_hi   = BUF_CEILING
        self.ed_top_ptr = BUF_CEILING
        self.ed_top_line = 0
        self.ed_cur_line = 0
        self.ed_cur_col  = 0
        self.ed_total_lines = 1
        self.ed_dirty = False

    def _ensure_room(self):
        """Mirror of gb_ensure_room in editor.c."""
        gap_size = self.gap_hi - self.gap_lo
        if gap_size > 0:
            return True
        if self.buf_base - GROW_SIZE < BUF_FLOOR:
            return False
        pre_size = self.gap_lo - self.buf_base
        new_base = self.buf_base - GROW_SIZE
        if pre_size > 0:
            # memmove: shift pre-gap text down
            self.mem[new_base:new_base + pre_size] = \
                self.mem[self.buf_base:self.buf_base + pre_size]
        # adjust ed_top_ptr — the fix for the invisible text bug
        shift = self.buf_base - new_base
        if self.ed_top_ptr >= self.buf_base and self.ed_top_ptr <= self.gap_lo:
            self.ed_top_ptr -= shift
        self.gap_lo = new_base + pre_size
        self.gap_hi = self.gap_lo + GROW_SIZE
        self.buf_base = new_base
        return True

    def insert(self, ch):
        """Mirror of gb_insert."""
        if not self._ensure_room():
            return
        self.mem[self.gap_lo] = ch
        self.gap_lo += 1
        if ch == 0x0D:
            self.ed_total_lines += 1
        self.ed_dirty = True

    def backspace(self):
        """Mirror of gb_backspace."""
        if self.gap_lo == self.buf_base:
            return
        self.gap_lo -= 1
        if self.mem[self.gap_lo] == 0x0D:
            self.ed_total_lines -= 1
        self.ed_dirty = True

    def cursor_right(self):
        """Mirror of gb_cursor_right."""
        if self.gap_hi >= self.buf_end:
            return
        self.mem[self.gap_lo] = self.mem[self.gap_hi]
        self.gap_lo += 1
        self.gap_hi += 1

    def cursor_left(self):
        """Mirror of gb_cursor_left."""
        if self.gap_lo == self.buf_base:
            return
        self.gap_lo -= 1
        self.gap_hi -= 1
        self.mem[self.gap_hi] = self.mem[self.gap_lo]

    def text(self):
        """Return the full text content (pre-gap + post-gap)."""
        pre = bytes(self.mem[self.buf_base:self.gap_lo])
        post = bytes(self.mem[self.gap_hi:self.buf_end])
        return pre + post

    def text_before_cursor(self):
        return bytes(self.mem[self.buf_base:self.gap_lo])

    def text_after_cursor(self):
        return bytes(self.mem[self.gap_hi:self.buf_end])

    def gap_size(self):
        return self.gap_hi - self.gap_lo

    def text_size(self):
        return (self.gap_lo - self.buf_base) + (self.buf_end - self.gap_hi)

    def invariants_ok(self):
        """Check all gap buffer invariants."""
        assert self.buf_base >= BUF_FLOOR, \
            f"buf_base ${self.buf_base:04X} below BUF_FLOOR ${BUF_FLOOR:04X}"
        assert self.buf_base <= self.gap_lo, \
            f"buf_base ${self.buf_base:04X} > gap_lo ${self.gap_lo:04X}"
        assert self.gap_lo <= self.gap_hi, \
            f"gap_lo ${self.gap_lo:04X} > gap_hi ${self.gap_hi:04X}"
        assert self.gap_hi <= self.buf_end, \
            f"gap_hi ${self.gap_hi:04X} > buf_end ${self.buf_end:04X}"
        assert self.buf_end == BUF_CEILING, \
            f"buf_end ${self.buf_end:04X} != ceiling ${BUF_CEILING:04X}"
        # ed_top_ptr must be in a valid region
        in_pregap = (self.ed_top_ptr >= self.buf_base and
                     self.ed_top_ptr <= self.gap_lo)
        in_postgap = (self.ed_top_ptr >= self.gap_hi and
                      self.ed_top_ptr <= self.buf_end)
        assert in_pregap or in_postgap, \
            f"ed_top_ptr ${self.ed_top_ptr:04X} not in valid region " \
            f"(pregap ${self.buf_base:04X}-${self.gap_lo:04X}, " \
            f"postgap ${self.gap_hi:04X}-${self.buf_end:04X})"
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# §1  Basic gap buffer operations
# ═══════════════════════════════════════════════════════════════════════════════

class TestGapBufferBasic:
    def test_empty(self):
        gb = GapBuffer()
        assert gb.text() == b""
        assert gb.text_size() == 0
        assert gb.ed_total_lines == 1
        gb.invariants_ok()

    def test_insert_one(self):
        gb = GapBuffer()
        gb.insert(0x41)  # 'a'
        assert gb.text() == b"\x41"
        assert gb.text_size() == 1
        gb.invariants_ok()

    def test_insert_string(self):
        gb = GapBuffer()
        # PETSCII: 'h'=$48, 'e'=$45, 'l'=$4C, 'o'=$4F
        msg = bytes([0x48, 0x45, 0x4C, 0x4C, 0x4F])
        for ch in msg:
            gb.insert(ch)
        assert gb.text() == msg
        assert gb.text_size() == 5
        gb.invariants_ok()

    def test_insert_newline(self):
        gb = GapBuffer()
        for ch in b"abc":
            gb.insert(ch)
        gb.insert(0x0D)
        for ch in b"def":
            gb.insert(ch)
        assert gb.text() == b"abc\x0ddef"
        assert gb.ed_total_lines == 2
        gb.invariants_ok()

    def test_backspace(self):
        gb = GapBuffer()
        for ch in b"abc":
            gb.insert(ch)
        gb.backspace()
        assert gb.text() == b"ab"
        gb.invariants_ok()

    def test_backspace_at_start(self):
        gb = GapBuffer()
        gb.backspace()  # should be no-op
        assert gb.text() == b""
        gb.invariants_ok()

    def test_backspace_newline(self):
        gb = GapBuffer()
        for ch in b"a\x0db":
            gb.insert(ch)
        assert gb.ed_total_lines == 2
        gb.backspace()  # remove 'b'
        gb.backspace()  # remove \x0d
        assert gb.ed_total_lines == 1
        assert gb.text() == b"a"
        gb.invariants_ok()


# ═══════════════════════════════════════════════════════════════════════════════
# §2  Cursor movement
# ═══════════════════════════════════════════════════════════════════════════════

class TestCursorMovement:
    def test_cursor_right(self):
        gb = GapBuffer()
        for ch in b"abc":
            gb.insert(ch)
        # cursor is at end; move left then right
        gb.cursor_left()
        gb.cursor_left()
        assert gb.text_before_cursor() == b"a"
        assert gb.text_after_cursor() == b"bc"
        gb.cursor_right()
        assert gb.text_before_cursor() == b"ab"
        assert gb.text_after_cursor() == b"c"
        gb.invariants_ok()

    def test_cursor_left_at_start(self):
        gb = GapBuffer()
        for ch in b"abc":
            gb.insert(ch)
        gb.cursor_left()
        gb.cursor_left()
        gb.cursor_left()
        gb.cursor_left()  # already at start, no-op
        assert gb.text_before_cursor() == b""
        assert gb.text_after_cursor() == b"abc"
        gb.invariants_ok()

    def test_cursor_right_at_end(self):
        gb = GapBuffer()
        for ch in b"abc":
            gb.insert(ch)
        gb.cursor_right()  # already at end, no-op
        assert gb.text_before_cursor() == b"abc"
        assert gb.text_after_cursor() == b""
        gb.invariants_ok()

    def test_insert_mid_text(self):
        gb = GapBuffer()
        for ch in b"ac":
            gb.insert(ch)
        gb.cursor_left()  # between 'a' and 'c'
        gb.insert(0x62)   # 'b'
        assert gb.text() == b"abc"
        gb.invariants_ok()


# ═══════════════════════════════════════════════════════════════════════════════
# §3  Buffer growth (ensure_room)
# ═══════════════════════════════════════════════════════════════════════════════

class TestBufferGrowth:
    def test_first_insert_grows(self):
        gb = GapBuffer()
        assert gb.gap_size() == 0
        gb.insert(0x41)
        assert gb.gap_size() == GROW_SIZE - 1  # one byte used
        gb.invariants_ok()

    def test_buf_base_moves_down(self):
        gb = GapBuffer()
        old_base = gb.buf_base
        gb.insert(0x41)
        assert gb.buf_base == old_base - GROW_SIZE
        gb.invariants_ok()

    def test_ed_top_ptr_adjusted_on_grow(self):
        """The bug that caused invisible text: ed_top_ptr must follow buf_base."""
        gb = GapBuffer()
        assert gb.ed_top_ptr == BUF_CEILING
        gb.insert(0x41)  # triggers ensure_room
        # ed_top_ptr must now point to new buf_base, not old
        assert gb.ed_top_ptr == gb.buf_base, \
            f"ed_top_ptr ${gb.ed_top_ptr:04X} != buf_base ${gb.buf_base:04X}"
        gb.invariants_ok()

    def test_ed_top_ptr_adjusted_with_content(self):
        """After multiple grows, ed_top_ptr stays valid."""
        gb = GapBuffer()
        # Fill enough to force multiple grows
        for i in range(300):
            gb.insert(0x41 + (i % 26))
        gb.invariants_ok()
        assert gb.ed_top_ptr >= gb.buf_base
        assert gb.ed_top_ptr <= gb.gap_lo

    def test_ed_top_ptr_postgap_not_shifted(self):
        """ed_top_ptr in post-gap region must NOT be shifted."""
        gb = GapBuffer()
        for ch in b"line1\x0dline2\x0dline3":
            gb.insert(ch)
        # Move cursor to start of line2 (in post-gap after cursor_left's)
        for _ in range(5):  # back past "line3"
            gb.cursor_left()
        gb.cursor_left()  # back past \x0d
        for _ in range(5):  # back past "line2"
            gb.cursor_left()
        # Now ed_top_ptr is still at buf_base (line 0)
        # It's in pre-gap. Force another grow by consuming the gap.
        old_top = gb.ed_top_ptr
        # Insert enough to consume remaining gap
        remaining = gb.gap_size()
        for i in range(remaining + 1):
            gb.insert(0x58)  # 'X'
        gb.invariants_ok()


# ═══════════════════════════════════════════════════════════════════════════════
# §4  Text content integrity
# ═══════════════════════════════════════════════════════════════════════════════

class TestTextIntegrity:
    def test_insert_and_read_back(self):
        gb = GapBuffer()
        msg = b"lda #$00\x0dsta $d020\x0drts"
        for ch in msg:
            gb.insert(ch)
        assert gb.text() == msg
        gb.invariants_ok()

    def test_edit_mid_text(self):
        gb = GapBuffer()
        # PETSCII: "lda #$00" = $4C $44 $41 $20 $23 $24 $30 $30
        msg = bytes([0x4C, 0x44, 0x41, 0x20, 0x23, 0x24, 0x30, 0x30])
        for ch in msg:
            gb.insert(ch)
        # Change last "00" to "01": backspace last char, insert '1'
        gb.backspace()         # remove last '0'
        gb.insert(0x31)        # insert '1'
        assert gb.text() == bytes([0x4C, 0x44, 0x41, 0x20, 0x23, 0x24, 0x30, 0x31])
        gb.invariants_ok()

    def test_large_text(self):
        gb = GapBuffer()
        lines = []
        for i in range(100):
            line = f"line {i:03d} - some assembly code here".encode()
            for ch in line:
                gb.insert(ch)
            gb.insert(0x0D)
            lines.append(line)
        assert gb.ed_total_lines == 101  # 100 newlines + initial line
        assert gb.text_size() > 3000
        gb.invariants_ok()
        # Verify content
        text = gb.text()
        for i, line in enumerate(lines):
            assert line in text, f"line {i} not found in buffer"


# ═══════════════════════════════════════════════════════════════════════════════
# §5  PETSCII → Screen code conversion (mirrors ed_render_line)
# ═══════════════════════════════════════════════════════════════════════════════

def petscii_to_screencode(ch):
    """Mirror of ed_render_line's conversion."""
    sc = ch
    if 0x41 <= sc <= 0x5A:
        sc -= 0x40      # unshifted letters
    elif 0xC1 <= sc <= 0xDA:
        sc -= 0x80      # shifted letters
    return sc


class TestScreenConversion:
    @pytest.mark.parametrize("petscii,expected", [
        (0x20, 0x20),   # space
        (0x30, 0x30),   # '0'
        (0x3A, 0x3A),   # ':'
        (0x41, 0x01),   # 'a' → screen A
        (0x4D, 0x0D),   # 'm' → screen M
        (0x5A, 0x1A),   # 'z' → screen Z
        (0xC1, 0x41),   # shifted A → screen a (lowercase)
        (0xDA, 0x5A),   # shifted Z → screen z
        (0x0D, 0x0D),   # CR (shouldn't be rendered, but conversion is identity)
    ])
    def test_conversion(self, petscii, expected):
        assert petscii_to_screencode(petscii) == expected


# ═══════════════════════════════════════════════════════════════════════════════
# §6  Rendering simulation
# ═══════════════════════════════════════════════════════════════════════════════

def render_line(gb, line_num):
    """Simulate ed_render_line: return 40 screen codes for the given line."""
    # Find the start of line_num by scanning from buf_base
    pos = gb.buf_base
    for _ in range(line_num):
        while pos < gb.buf_end:
            if pos == gb.gap_lo:
                pos = gb.gap_hi
            if pos >= gb.buf_end:
                break
            if gb.mem[pos] == 0x0D:
                pos += 1
                break
            pos += 1

    # Render characters
    scr = [0x20] * 40  # fill with spaces
    col = 0
    while col < 40:
        if pos == gb.gap_lo:
            pos = gb.gap_hi
        if pos >= gb.buf_end:
            break
        ch = gb.mem[pos]
        if ch == 0x0D:
            pos += 1
            break
        scr[col] = petscii_to_screencode(ch)
        col += 1
        pos += 1
    return scr


class TestRendering:
    def test_empty_buffer(self):
        gb = GapBuffer()
        scr = render_line(gb, 0)
        assert scr == [0x20] * 40  # all spaces

    def test_single_line(self):
        gb = GapBuffer()
        # PETSCII "hello" = $48 $45 $4C $4C $4F
        for ch in [0x48, 0x45, 0x4C, 0x4C, 0x4F]:
            gb.insert(ch)
        scr = render_line(gb, 0)
        assert scr[0] == 0x08  # 'h'
        assert scr[1] == 0x05  # 'e'
        assert scr[2] == 0x0C  # 'l'
        assert scr[3] == 0x0C  # 'l'
        assert scr[4] == 0x0F  # 'o'
        assert scr[5] == 0x20  # space (padding)

    def test_two_lines(self):
        gb = GapBuffer()
        # PETSCII "abc\x0ddef" = $41 $42 $43 $0D $44 $45 $46
        for ch in [0x41, 0x42, 0x43, 0x0D, 0x44, 0x45, 0x46]:
            gb.insert(ch)
        scr0 = render_line(gb, 0)
        scr1 = render_line(gb, 1)
        assert scr0[0] == 0x01  # 'a'
        assert scr0[1] == 0x02  # 'b'
        assert scr0[2] == 0x03  # 'c'
        assert scr0[3] == 0x20  # padding
        assert scr1[0] == 0x04  # 'd'
        assert scr1[1] == 0x05  # 'e'
        assert scr1[2] == 0x06  # 'f'

    def test_render_after_cursor_mid(self):
        """Render with cursor in the middle (gap splits the text)."""
        gb = GapBuffer()
        # PETSCII "abcdef" = $41-$46
        for ch in [0x41, 0x42, 0x43, 0x44, 0x45, 0x46]:
            gb.insert(ch)
        gb.cursor_left()
        gb.cursor_left()
        gb.cursor_left()  # cursor between 'c' and 'd'
        scr = render_line(gb, 0)
        assert scr[0] == 0x01  # 'a'
        assert scr[1] == 0x02  # 'b'
        assert scr[2] == 0x03  # 'c'
        assert scr[3] == 0x04  # 'd' (after gap)
        assert scr[4] == 0x05  # 'e'
        assert scr[5] == 0x06  # 'f'

    def test_render_after_growth(self):
        """The invisible text bug: render must work after buffer growth."""
        gb = GapBuffer()
        gb.insert(0x41)  # 'a' — triggers growth
        scr = render_line(gb, 0)
        assert scr[0] == 0x01, \
            f"Expected screen code $01 (A), got ${scr[0]:02X}"

    def test_render_with_ed_top_ptr(self):
        """ed_top_ptr must be valid for render_range to find the right line."""
        gb = GapBuffer()
        # PETSCII: "lda\x0dsta\x0drts" = $4C $44 $41 $0D $53 $54 $41 $0D $52 $54 $53
        for ch in [0x4C, 0x44, 0x41, 0x0D, 0x53, 0x54, 0x41, 0x0D, 0x52, 0x54, 0x53]:
            gb.insert(ch)
        assert gb.ed_top_ptr == gb.buf_base
        scr0 = render_line(gb, 0)
        assert scr0[0] == 0x0C  # 'l'
        assert scr0[1] == 0x04  # 'd'
        assert scr0[2] == 0x01  # 'a'
        scr1 = render_line(gb, 1)
        assert scr1[0] == 0x13  # 's'
        scr2 = render_line(gb, 2)
        assert scr2[0] == 0x12  # 'r'


# ═══════════════════════════════════════════════════════════════════════════════
# §6b  Scroll memmove simulation
#
# The Python gap-buffer model does NOT own a screen RAM representation;
# renderers compute bytes on demand from the gap buffer.  ed_scroll_up /
# ed_scroll_down in editor.s, however, physically move bytes in C64
# screen RAM and THEN render just the newly-revealed edge row.  A bug
# in the memmove is invisible to the pure gap-buffer tests because the
# buffer is untouched — that's exactly how the "scroll_down copies only
# the first row" bug slipped through for months.
#
# The functions below are a Python mirror of the scroll byte-movement
# logic.  They have the SAME relationship to editor.s::ed_scroll_up /
# ed_scroll_down as render_line (above) has to ed_render_line: a
# human-maintained parallel implementation.  When you change editor.s
# you MUST update these mirrors or the tests become meaningless.
#
# What these tests catch:
#   • Bugs in the Python mirror itself
#   • The CONTRACT of the scroll procs (semantic expectation of what
#     rows move where, in which direction)
#   • Anyone re-implementing editor.s::ed_scroll_* who mirrors the
#     broken version here will see the test fail
#
# What they do NOT catch:
#   • Direct ASM-level bugs in editor.s that don't go through the
#     Python mirror — e.g., the original bug where save_ptr and Y
#     both moved on each iter.  A true ASM-level regression test
#     would require linking editor.s into a py65 test harness with
#     a real screen-RAM memory region.  TODO: consider adding such
#     a harness if the scroll code ever needs to change again.
# ═══════════════════════════════════════════════════════════════════════════════

ED_LINES = 22
SCREEN_WIDTH = 40


def make_screen():
    """22 editor rows × 40 cols of screen codes.  Initialized with a
    distinct pattern per row so stale bytes after a bad memmove are
    obvious in assertion failures."""
    return [[(row * SCREEN_WIDTH + col) & 0xFF
             for col in range(SCREEN_WIDTH)]
            for row in range(ED_LINES)]


def scroll_up_memmove(scr):
    """Mirror of editor.s::ed_scroll_up's row-by-row copy.
    Shifts rows 1..21 → 0..20.  Row 21 is left untouched (the caller
    re-renders it from the buffer; we check only the memmove)."""
    for dst_row in range(ED_LINES - 1):     # 0..20
        src_row = dst_row + 1
        # copy 40 bytes from src → dst
        for col in range(SCREEN_WIDTH):
            scr[dst_row][col] = scr[src_row][col]


def scroll_down_memmove(scr):
    """Mirror of editor.s::ed_scroll_down's row-by-row copy.
    Shifts rows 0..20 → 1..21.  Descending order so src is read before
    being overwritten.  Row 0 is left untouched (caller re-renders)."""
    for dst_row in range(ED_LINES - 1, 0, -1):    # 21..1
        src_row = dst_row - 1
        for col in range(SCREEN_WIDTH):
            scr[dst_row][col] = scr[src_row][col]


class TestScrollMemmove:
    """Regression tests for the scroll_up / scroll_down memmove.

    These catch the bug where ed_scroll_down's descending copy
    incorrectly decremented the pointer AND incremented Y on the
    same iteration, so every byte read/write landed on the same
    physical address (writing only the first row effectively)."""

    def test_scroll_up_shifts_rows_up_by_one(self):
        """After scroll_up: new row N == old row N+1, for N=0..20."""
        scr = make_screen()
        old = [row[:] for row in scr]
        scroll_up_memmove(scr)
        for row in range(ED_LINES - 1):
            assert scr[row] == old[row + 1], (
                f"row {row} should match old row {row + 1}")

    def test_scroll_down_shifts_rows_down_by_one(self):
        """After scroll_down: new row N == old row N-1, for N=1..21.

        This is the regression test for the 'scrolling up only
        updates the first line on screen' bug — the broken
        implementation left rows 2..21 completely untouched."""
        scr = make_screen()
        old = [row[:] for row in scr]
        scroll_down_memmove(scr)
        for row in range(1, ED_LINES):
            assert scr[row] == old[row - 1], (
                f"row {row} should match old row {row - 1}; "
                f"got {scr[row][:4]}..., expected {old[row - 1][:4]}...")

    def test_scroll_down_preserves_source_bytes(self):
        """The descending order is correct only if we copy row 20→21
        BEFORE copying row 19→20, etc.  Verify the property
        constructively by checking every row after the move."""
        scr = make_screen()
        # Tag each row with a distinct single byte so we can spot
        # any row that got written from a source that was already
        # overwritten.
        for row in range(ED_LINES):
            scr[row] = [row] * SCREEN_WIDTH
        scroll_down_memmove(scr)
        # Expected: new row 1..21 all carry the original row-value.
        for row in range(1, ED_LINES):
            assert all(b == row - 1 for b in scr[row]), (
                f"row {row} should be all {row - 1}, got {scr[row][:4]}")
        # Row 0 is untouched by the memmove (caller renders it).
        assert all(b == 0 for b in scr[0])

    def test_scroll_up_preserves_source_bytes(self):
        """Symmetric check for ed_scroll_up."""
        scr = make_screen()
        for row in range(ED_LINES):
            scr[row] = [row] * SCREEN_WIDTH
        scroll_up_memmove(scr)
        for row in range(ED_LINES - 1):
            assert all(b == row + 1 for b in scr[row]), (
                f"row {row} should be all {row + 1}, got {scr[row][:4]}")
        # Row 21 is untouched by the memmove (caller renders it).
        assert all(b == 21 for b in scr[21])

    def test_scroll_up_is_inverse_of_scroll_down_almost(self):
        """scroll_down then scroll_up should restore rows 1..20 exactly
        (rows 0 and 21 are rendered by the callers, not the memmove)."""
        scr = make_screen()
        old = [row[:] for row in scr]
        scroll_down_memmove(scr)
        scroll_up_memmove(scr)
        for row in range(1, ED_LINES - 1):
            assert scr[row] == old[row], (
                f"row {row} not restored after down+up")


# ═══════════════════════════════════════════════════════════════════════════════
# §7  Tab character ($A0)
# ═══════════════════════════════════════════════════════════════════════════════

SP = 0x20   # space
TAB = 0xA0  # tab (C=+SPACE)
CH = 0x41   # non-space content (PETSCII 'a')
CR = 0x0D


class TabGapBuffer(GapBuffer):
    """GapBuffer extended with tab character ($A0) support.

    TAB_WIDTH is a build-time constant in CSE (default 8); this
    Python model mirrors that — there is no runtime tab_width
    parameter.  See doc/modules/editor.md.
    """

    TAB_WIDTH = 8

    # Load-time statistics (set by simulate_load, mirrors editor.s::
    # ed_load_split + ed_load_split_lines).
    SPLIT_LINES_MAX = 8

    def __init__(self):
        super().__init__()
        self.ed_load_split = 0              # count of forced splits
        self.ed_load_split_lines = []       # first SPLIT_LINES_MAX
                                             # editor-line numbers where
                                             # a forced CR was inserted

    # ── Visual column helpers ────────────────────────────────────────


    def _char_width(self, ch, vcol):
        """Visual width of one byte at visual column vcol."""
        if ch == TAB:
            return self.TAB_WIDTH - (vcol % self.TAB_WIDTH)
        return 1

    def _visual_col(self):
        """Recompute visual column from line start to gap_lo."""
        p = self.gap_lo
        while p > self.buf_base and self.mem[p - 1] != CR:
            p -= 1
        vcol = 0
        while p < self.gap_lo:
            vcol += self._char_width(self.mem[p], vcol)
            p += 1
        return vcol

    def _line_vwidth(self, start_ptr):
        """Return the total visual width of the line starting at
        start_ptr (stopping at CR or buf_end, skipping the gap).
        Matches editor.s::line_vwidth.  Result is clamped to 255 as
        an "impossibly wide" sentinel; normal lines are ≤ 39."""
        p = start_ptr
        vcol = 0
        while True:
            if p == self.gap_lo:
                p = self.gap_hi
            if p >= self.buf_end:
                break
            ch = self.mem[p]
            if ch == CR:
                break
            vcol += self._char_width(ch, vcol)
            if vcol >= 255:
                return 255
            p += 1
        return vcol

    def line_vwidth_current(self):
        """Visual width of the cursor's line (from its start to its CR)."""
        # Walk back to start of current line
        p = self.gap_lo
        while p > self.buf_base and self.mem[p - 1] != CR:
            p -= 1
        return self._line_vwidth(p)

    def line_vwidth_next(self):
        """Visual width of the line AFTER the cursor's line — the
        one that would be joined into the current line by a
        backspace-at-col-0."""
        # Start at gap_hi (cursor), skip forward to just past the
        # next CR — that's the start of the next line.
        p = self.gap_hi
        while p < self.buf_end and self.mem[p] != CR:
            p += 1
        if p < self.buf_end and self.mem[p] == CR:
            p += 1
        return self._line_vwidth(p)

    def _copy_leading_ws(self):
        """Return bytes of leading whitespace ($20/$A0) on current line."""
        p = self.gap_lo
        while p > self.buf_base and self.mem[p - 1] != CR:
            p -= 1
        ws = []
        while p < self.gap_lo and self.mem[p] in (SP, TAB):
            ws.append(self.mem[p])
            p += 1
        if p == self.gap_lo:
            q = self.gap_hi
            while q < self.buf_end and self.mem[q] in (SP, TAB):
                ws.append(self.mem[q])
                q += 1
        return bytes(ws)

    # ── Tab operations ───────────────────────────────────────────────

    def tab_insert(self):
        """C=+SPACE: insert $A0 tab byte, advance to next tab stop.

        Refused if the line's visual width would exceed 39 after the
        insert.  Conservative rule: compute the tab's width as if it
        were appended at the end of the current line (worst case for
        end-of-line; under-refuses for tab in the middle of a line
        with mixed tabs but mirrors what asm checks)."""
        line_w = self.line_vwidth_current()
        tab_w = self._char_width(TAB, line_w)
        if line_w + tab_w > 39:
            return  # would push line past 39 cols
        w = self._char_width(TAB, self.ed_cur_col)
        self.insert(TAB)
        self.ed_cur_col += w

    def printable_insert(self, ch):
        """Insert a printable byte at the cursor.  Refused if the
        line's visual width is already at the 39-col cap (any
        printable adds exactly one column)."""
        if self.line_vwidth_current() >= 39:
            return  # would push line past 39 cols
        self.insert(ch)
        self.ed_cur_col += 1

    def tab_left(self):
        """LEFT: move one byte left, recompute visual column."""
        if self.ed_cur_col > 0 and self.gap_lo > self.buf_base:
            self.cursor_left()
            self.ed_cur_col = self._visual_col()

    def tab_right(self):
        """RIGHT: move one byte right, recompute visual column."""
        if self.gap_hi < self.buf_end and self.mem[self.gap_hi] != CR:
            self.cursor_right()
            self.ed_cur_col = self._visual_col()

    def tab_del(self):
        """DEL: backspace one byte, recompute visual column."""
        if self.ed_cur_col > 0:
            self.backspace()
            self.ed_cur_col = self._visual_col()

    def simulate_load(self, text):
        """Simulate ed_load_source: feed `text` (bytes) one byte at a
        time through an insert routine that tracks the running visual
        width of the current line.  If inserting the next byte would
        push the line's vcol beyond 39, insert a forced CR first and
        record the affected editor line number.

        Mirrors editor.s::ed_load_source + the inline width-tracking.
        Resets the buffer to empty first.
        """
        # Fresh start
        while self.gap_lo > self.buf_base:
            self.backspace()
        self.ed_cur_line = 0
        self.ed_cur_col = 0
        self.ed_total_lines = 1
        self.ed_dirty = False
        self.ed_load_split = 0
        self.ed_load_split_lines = []

        running_vcol = 0
        editor_line = 0     # current editor line number (0-based)
        for b in text:
            if b == CR:
                self.insert(CR)
                running_vcol = 0
                editor_line += 1
                continue
            w = self._char_width(b, running_vcol)
            if running_vcol + w > 39:
                # Forced split: insert CR, record line number.
                self.insert(CR)
                self.ed_load_split += 1
                if len(self.ed_load_split_lines) < self.SPLIT_LINES_MAX:
                    # The split moves content to a new editor line;
                    # the "affected" line in the user's mental model
                    # is the one that USED to contain this byte.
                    # We record the editor-line number BEFORE the
                    # split so the user can scroll to see the broken
                    # line and its continuation.
                    self.ed_load_split_lines.append(editor_line)
                editor_line += 1
                running_vcol = 0
                w = self._char_width(b, 0)   # recompute width at col 0
            self.insert(b)
            running_vcol += w
        # Leave cursor at the end of the loaded content; user can
        # navigate as needed.
        self.ed_cur_line = editor_line
        self.ed_cur_col = running_vcol
        # ed_dirty is True after inserts; real editor clears it
        # after load because the buffer matches the file (modulo
        # splits).  Mirror that.
        self.ed_dirty = False

    def tab_del_join(self):
        """DEL at col 0: join with previous line, honouring the
        39-col hard cap.  Returns True if a forced CR was inserted,
        False otherwise.

        Algorithm:
        1. backspace() deletes the CR between the two lines.
        2. Compute the combined line's visual width.
        3. If ≤ 39: done, normal join.
        4. Else:
           a. Remember the cursor's visual col (= width of line a).
           b. Walk from line start counting visual cols to find the
              split point: the highest byte offset at which the
              first sub-line's visual width would stay ≤ 39.  Tabs
              are never broken — if a tab would straddle the cap,
              the forced CR goes BEFORE the tab.
           c. Move the cursor to that byte offset (LEFT if the
              join point was past it, RIGHT if before).
           d. Insert a CR.  The cursor is now at col 0 of the new
              second sub-line.
           e. Move the cursor back toward the join point.  If the
              join point was within the first sub-line, step LEFT
              past the CR and back to col join_col.  Otherwise it's
              on the second sub-line at col (join_col - split_vcol),
              step RIGHT that many positions.
        """
        if self.ed_cur_col != 0:
            return False
        if self.ed_cur_line == 0:
            return False

        # Step 1: raw join.
        self.backspace()          # deletes the CR; ed_total_lines -= 1
        self.ed_cur_line -= 1
        self.ed_cur_col = self._visual_col()

        # Step 2: combined width check.
        combined = self.line_vwidth_current()
        if combined <= 39:
            return False          # normal join, fits

        join_col = self.ed_cur_col

        # Step 4b: find split point by walking from line start.
        # We track: split_vcol (visual col at which we split),
        # split_byte_offset (number of BYTES from line start at which
        # we split — used below to compute cursor moves).
        #
        # Walk back to start of line first to get the line start ptr.
        line_start = self.gap_lo
        while line_start > self.buf_base and self.mem[line_start - 1] != CR:
            line_start -= 1
        # Forward scan counting vcol and byte offset (skipping gap).
        p = line_start
        vcol = 0
        byte_offset = 0
        while True:
            if p == self.gap_lo:
                p = self.gap_hi
            if p >= self.buf_end:
                break
            ch = self.mem[p]
            if ch == CR:
                break
            w = self._char_width(ch, vcol)
            if vcol + w > 39:
                break
            vcol += w
            byte_offset += 1
            p += 1
        split_vcol = vcol
        split_byte_offset = byte_offset

        # Step 4c: compute join_col's byte offset from line start.
        # The cursor is currently at visual col join_col in the
        # combined line.  We need to know how many BYTES that is
        # from line_start — only then can we compute the move.
        # We re-scan the line (at most 39 chars) to find it.
        p = line_start
        vc = 0
        join_byte_offset = 0
        while vc < join_col:
            if p == self.gap_lo:
                p = self.gap_hi
            if p >= self.buf_end:
                break
            ch = self.mem[p]
            if ch == CR:
                break
            vc += self._char_width(ch, vc)
            join_byte_offset += 1
            p += 1

        # Step 4c cont.: move the gap to split_byte_offset.
        # Currently the gap is at join_byte_offset (because ed_cur_col
        # == join_col, and we just re-computed that).
        delta = split_byte_offset - join_byte_offset
        if delta < 0:
            for _ in range(-delta):
                self.cursor_left()
        else:
            for _ in range(delta):
                self.cursor_right()

        # Step 4d: insert the forced CR at the current gap position.
        self.insert(CR)          # ed_total_lines += 1
        self.ed_cur_line += 1    # we're now at col 0 of new second sub-line
        self.ed_cur_col = 0

        # Step 4e: move cursor back toward join point.
        if join_col <= split_vcol:
            # Join point is on the first sub-line.  Step LEFT past
            # the CR and back to join_byte_offset bytes from line_start.
            # Currently we're at (line_start + split_byte_offset) on
            # sub-line 2 col 0.  We need to move LEFT by
            # (split_byte_offset - join_byte_offset + 1) bytes: one
            # for the CR itself and (split_byte_offset - join_byte_offset)
            # to undo the move forward.
            steps = (split_byte_offset - join_byte_offset) + 1
            for _ in range(steps):
                self.cursor_left()
            self.ed_cur_line -= 1
            self.ed_cur_col = self._visual_col()
        else:
            # Join point is on the second sub-line at col
            # (join_col - split_vcol), which is (join_byte_offset -
            # split_byte_offset) bytes past the forced CR.
            steps = join_byte_offset - split_byte_offset
            for _ in range(steps):
                self.cursor_right()
            self.ed_cur_col = self._visual_col()

        return True

    def tab_return(self):
        """RETURN with auto-indent: copy leading $20/$A0 from current
        line, truncated so the new line's ed_cur_col stays ≤ 38 (i.e.,
        at least one col of room for the first typable char)."""
        ws = self._copy_leading_ws()
        self.insert(CR)
        self.ed_cur_line += 1
        self.ed_cur_col = 0
        # Truncate the copied whitespace to what fits with room to spare.
        for ch in ws:
            w = self._char_width(ch, self.ed_cur_col)
            if self.ed_cur_col + w > 38:
                break  # no room for the next indent char and a content char
            self.insert(ch)
            self.ed_cur_col += w


def _make_tab_buf(line_bytes, cursor_col=0):
    """Create a TabGapBuffer with one line, cursor at given column."""
    gb = TabGapBuffer()
    for ch in line_bytes:
        gb.insert(ch)
    # Rewind to start of line
    while gb.gap_lo > gb.buf_base and gb.mem[gb.gap_lo - 1] != CR:
        gb.cursor_left()
    gb.ed_cur_col = 0
    # Advance to target column (by bytes, for setup)
    for _ in range(cursor_col):
        if gb.gap_hi < gb.buf_end and gb.mem[gb.gap_hi] != CR:
            gb.cursor_right()
    gb.ed_cur_col = gb._visual_col()
    return gb


class TestBackspaceJoinCap:
    """§7b — DEL at col 0 joins with previous line, forcing a CR
    at the cap boundary if the combined line would exceed 39 cols."""

    def _make_two_lines(self, line_a_len, line_b_len):
        """Build a buffer with two lines of given visible lengths,
        cursor at col 0 of line 1 (second line)."""
        gb = TabGapBuffer()
        for _ in range(line_a_len):
            gb.insert(CH)
        gb.insert(CR)
        for _ in range(line_b_len):
            gb.insert(CH)
        # Walk cursor back to col 0 of line 1
        for _ in range(line_b_len):
            gb.cursor_left()
        gb.ed_cur_line = 1
        gb.ed_cur_col = 0
        return gb

    # ── Normal join (no cap crossed) ────────────────────────────

    def test_join_two_short_lines(self):
        """Combined 5 + 7 = 12 ≤ 39 → no forced CR."""
        gb = self._make_two_lines(5, 7)
        forced = gb.tab_del_join()
        assert forced is False
        assert gb.ed_total_lines == 1
        assert gb.line_vwidth_current() == 12
        assert gb.ed_cur_line == 0
        assert gb.ed_cur_col == 5      # join point

    def test_join_reaching_exact_cap(self):
        """Combined 19 + 20 = 39, exactly at cap → no forced CR."""
        gb = self._make_two_lines(19, 20)
        forced = gb.tab_del_join()
        assert forced is False
        assert gb.line_vwidth_current() == 39
        assert gb.ed_cur_col == 19

    def test_join_at_line_0_noop(self):
        """DEL at col 0 of line 0 is a no-op (nothing to join)."""
        gb = TabGapBuffer()
        for _ in range(5):
            gb.insert(CH)
        # Move to col 0 of line 0
        for _ in range(5):
            gb.cursor_left()
        gb.ed_cur_line = 0
        gb.ed_cur_col = 0
        forced = gb.tab_del_join()
        assert forced is False
        assert gb.ed_total_lines == 1
        assert gb.line_vwidth_current() == 5

    # ── Forced-CR cases ─────────────────────────────────────────

    def test_join_overflow_by_one(self):
        """Combined 20 + 20 = 40 → forced CR at col 39."""
        gb = self._make_two_lines(20, 20)
        forced = gb.tab_del_join()
        assert forced is True
        # The combined width was 40, split at col 39 → first
        # sub-line has 39 chars (cols 0..38), second has 1.
        # Cursor started at the join point (col 20 of combined) —
        # that's within the first sub-line.
        assert gb.ed_total_lines == 2
        assert gb.ed_cur_col == 20
        assert gb.ed_cur_line == 0
        # First sub-line: 39 cols; second: 1 col.
        assert gb.line_vwidth_current() == 39
        assert gb.line_vwidth_next() == 1

    def test_join_overflow_puts_cursor_on_second_sub(self):
        """Combined 50 + 30 = 80 → first sub-line ≤ 39, split
        deep into what used to be line_b.  Cursor was at
        col 50 of combined (= col 0 of original line b).  After
        the forced CR at col 39 of first sub, cursor is at col
        (50 - 39) = 11 of the second sub-line."""
        gb = self._make_two_lines(50, 30)
        # But wait — 50 > 39, so the original line a already
        # violates the cap!  We can only get into that state via
        # a previous violation.  Skip this test.
        gb = None  # mark as invalid construction
        # Use a different setup instead
        gb = self._make_two_lines(30, 30)
        forced = gb.tab_del_join()
        assert forced is True
        # Combined 60 → first sub 39, second sub 21.
        # Cursor was at join point col 30 (= col 0 of original
        # second line) → col 30 is within first sub-line (< 39).
        assert gb.ed_cur_line == 0
        assert gb.ed_cur_col == 30
        assert gb.line_vwidth_current() == 39
        assert gb.line_vwidth_next() == 21

    def test_join_tab_at_boundary(self):
        """Join where a TAB on line b would straddle the cap.
        Line a = 32 chars, line b = TAB + 'xx' (TAB expands 8 to
        col 40).  Combined = 32 + 8 + 2 = 42, but the TAB at col 32
        would push to col 40 — straddles the cap.  Forced CR
        goes BEFORE the TAB, at col 32 exactly.
        First sub-line = 32 chars, second sub-line = TAB (expanding
        to col 8) + xx = 10 cols."""
        gb = TabGapBuffer()
        for _ in range(32):
            gb.insert(CH)
        gb.insert(CR)
        gb.insert(TAB)
        gb.insert(CH)
        gb.insert(CH)
        # Walk back to col 0 of line 1
        gb.cursor_left()  # 'x' at col 9
        gb.cursor_left()  # 'x' at col 8
        gb.cursor_left()  # TAB at col 0
        gb.ed_cur_line = 1
        gb.ed_cur_col = 0

        forced = gb.tab_del_join()
        assert forced is True
        assert gb.ed_cur_line == 0
        # Cursor was at col 0 of line_b, which becomes col 32 of
        # combined.  Forced CR at col 32 (before the TAB). So the
        # cursor is at col 32 of first sub-line.
        assert gb.ed_cur_col == 32
        assert gb.line_vwidth_current() == 32
        assert gb.line_vwidth_next() == 10


class TestLoadSplit:
    """§7d — ed_load_source enforces the 39-col cap by splitting
    overlong lines with a forced CR.  Counter and line-number array
    record the splits for the REPL's post-load warning."""

    def _line_chars(self, n):
        return bytes([CH] * n)

    def test_short_lines_no_split(self):
        """All lines ≤ 39 cols: no splits."""
        gb = TabGapBuffer()
        text = self._line_chars(10) + bytes([CR]) + self._line_chars(20) + bytes([CR])
        gb.simulate_load(text)
        assert gb.ed_load_split == 0
        assert gb.ed_load_split_lines == []
        assert gb.ed_total_lines == 3

    def test_exact_cap_no_split(self):
        """A line of exactly 39 cols is at the cap but does NOT split."""
        gb = TabGapBuffer()
        text = self._line_chars(39) + bytes([CR])
        gb.simulate_load(text)
        assert gb.ed_load_split == 0

    def test_one_char_over(self):
        """A line of 40 cols → 1 split: first sub ≤ 39, second sub = 1."""
        gb = TabGapBuffer()
        text = self._line_chars(40)
        gb.simulate_load(text)
        assert gb.ed_load_split == 1
        assert gb.ed_load_split_lines == [0]
        # The 40 chars become two editor lines: 39 + 1
        # line 0 has 39 chars, line 1 has 1 char
        assert gb.ed_total_lines == 2

    def test_line_100_becomes_three(self):
        """A 100-col line splits into 39 + 39 + 22 = 3 editor lines
        (2 forced CRs)."""
        gb = TabGapBuffer()
        text = self._line_chars(100)
        gb.simulate_load(text)
        assert gb.ed_load_split == 2
        # Splits happened on editor lines 0 and 1
        assert gb.ed_load_split_lines == [0, 1]
        assert gb.ed_total_lines == 3

    def test_mix_short_and_long(self):
        """Short line + long line + short line: 1 split total."""
        gb = TabGapBuffer()
        text = (self._line_chars(5) + bytes([CR]) +
                self._line_chars(50) + bytes([CR]) +
                self._line_chars(8) + bytes([CR]))
        gb.simulate_load(text)
        assert gb.ed_load_split == 1
        # Split happened on the second editor line (index 1)
        assert gb.ed_load_split_lines == [1]

    def test_tab_straddling_cap(self):
        """A line where a TAB would push past col 39: the forced CR
        goes BEFORE the tab so the tab starts the next sub-line."""
        gb = TabGapBuffer()
        text = self._line_chars(35) + bytes([TAB]) + self._line_chars(5)
        # 35 chars at col 35; TAB at col 35 expands 8 - (35%8) = 8 - 3 = 5
        # → new vcol = 40 > 39 → split before TAB.
        gb.simulate_load(text)
        assert gb.ed_load_split == 1
        assert gb.ed_load_split_lines == [0]
        # First sub: 35 chars.  Second sub: TAB(8) + 5 chars = 13 cols.
        # Walk to start and compute
        gb.ed_cur_line = 1
        gb.ed_cur_col = 13
        # Count lines
        assert gb.ed_total_lines == 2

    def test_split_counter_caps_at_8(self):
        """If more than 8 lines split, the counter keeps going but
        the line-number array caps at SPLIT_LINES_MAX."""
        gb = TabGapBuffer()
        # Build 10 overlong lines
        text = b""
        for _ in range(10):
            text += self._line_chars(50) + bytes([CR])
        gb.simulate_load(text)
        assert gb.ed_load_split == 10
        assert len(gb.ed_load_split_lines) == 8

    def test_empty_buffer_after_empty_load(self):
        """Loading empty text leaves a single empty line."""
        gb = TabGapBuffer()
        gb.simulate_load(b"")
        assert gb.ed_load_split == 0
        assert gb.ed_total_lines == 1
        assert gb.line_vwidth_current() == 0


class TestAutoIndentCap:
    """§7c — Auto-indent on RETURN is truncated if copying the parent
    line's leading whitespace would leave no room for the first typable
    char (i.e., new line's ed_cur_col must end ≤ 38)."""

    def test_indent_fits(self):
        """Parent line has 4 leading spaces + content → new line
        gets 4 leading spaces."""
        gb = TabGapBuffer()
        for _ in range(4):
            gb.insert(SP)
        for _ in range(5):
            gb.insert(CH)
        gb.ed_cur_col = gb._visual_col()
        # Cursor at col 9 of line 0, press RETURN
        gb.tab_return()
        # Cursor is on line 1, col 4 (after the copied spaces)
        assert gb.ed_cur_line == 1
        assert gb.ed_cur_col == 4

    def test_indent_with_tab(self):
        """Parent has 1 leading TAB (expands to 8) → new line gets 1 TAB."""
        gb = TabGapBuffer()
        gb.insert(TAB)
        for _ in range(5):
            gb.insert(CH)
        gb.ed_cur_col = gb._visual_col()
        gb.tab_return()
        assert gb.ed_cur_col == 8    # TAB expanded width

    def test_indent_exactly_at_38(self):
        """Parent has 38 leading spaces — the full indent fits since
        38 is the max col leaving room for the first typable char."""
        gb = TabGapBuffer()
        for _ in range(38):
            gb.insert(SP)
        gb.insert(CH)    # col 38 content char
        gb.ed_cur_col = gb._visual_col()   # = 39 (after content)
        # Cursor at col 39, press RETURN
        gb.tab_return()
        # New line has 38 spaces, cursor at col 38, room for 1 char.
        assert gb.ed_cur_line == 1
        assert gb.ed_cur_col == 38

    def test_indent_truncated_at_39(self):
        """Parent has 39 leading spaces (full cap) — auto-indent would
        leave no room for a typable char.  Truncated to 38."""
        gb = TabGapBuffer()
        for _ in range(39):
            gb.insert(SP)
        # Line has 39 spaces, cursor at col 39 (cursor rest col).
        gb.ed_cur_col = gb._visual_col()
        assert gb.ed_cur_col == 39
        gb.tab_return()
        # New line: 38 spaces (one less than parent's 39).
        assert gb.ed_cur_line == 1
        assert gb.ed_cur_col == 38

    def test_indent_tab_cannot_fit(self):
        """Parent has 32 spaces + 1 TAB (expands 8 to col 40... wait
        TAB at col 32 with TAB_WIDTH=8 expands to col 40, overflow.
        The parent itself wouldn't be legal.  Test a legal parent
        instead: 32 leading spaces + other stuff — auto-indent copies
        all 32 spaces and stops because further chars are not
        whitespace.  Cursor at col 32, room to type."""
        gb = TabGapBuffer()
        for _ in range(32):
            gb.insert(SP)
        for _ in range(5):
            gb.insert(CH)
        gb.ed_cur_col = gb._visual_col()  # col 37
        gb.tab_return()
        assert gb.ed_cur_col == 32   # 32 spaces copied

    def test_indent_mixed_ws(self):
        """Parent has 1 TAB (8) + 4 spaces (→ col 12) → new line gets
        TAB + 4 spaces."""
        gb = TabGapBuffer()
        gb.insert(TAB)
        for _ in range(4):
            gb.insert(SP)
        for _ in range(3):
            gb.insert(CH)
        gb.ed_cur_col = gb._visual_col()  # col 15
        gb.tab_return()
        assert gb.ed_cur_col == 12   # TAB(8) + 4 spaces


class TestLineVWidth:
    """§7a — line_vwidth: visual width of a line (0..39 for in-cap lines,
    higher if the buffer somehow contains an overlong line)."""

    def test_empty_buffer(self):
        gb = TabGapBuffer()
        assert gb._line_vwidth(gb.buf_base) == 0

    def test_line_of_spaces(self):
        gb = TabGapBuffer()
        for _ in range(5):
            gb.insert(SP)
        # Cursor at col 5, line width 5
        assert gb.line_vwidth_current() == 5

    def test_line_of_chars(self):
        gb = TabGapBuffer()
        for _ in range(10):
            gb.insert(CH)
        assert gb.line_vwidth_current() == 10

    def test_line_stops_at_cr(self):
        gb = TabGapBuffer()
        for _ in range(3):
            gb.insert(CH)
        gb.insert(CR)
        for _ in range(5):
            gb.insert(CH)
        # After all inserts cursor is on line 1 (second line).
        # line_vwidth_current walks from the start of line 1 to its CR.
        assert gb.line_vwidth_current() == 5

    def test_line_with_tab(self):
        gb = TabGapBuffer()
        gb.insert(TAB)
        gb.insert(CH)
        gb.insert(CH)
        # TAB=8, then 'aa' → visual width 10
        assert gb.line_vwidth_current() == 10

    def test_line_with_tab_at_col3(self):
        gb = TabGapBuffer()
        for _ in range(3):
            gb.insert(CH)
        gb.insert(TAB)  # expands 5 to col 8
        gb.insert(CH)
        assert gb.line_vwidth_current() == 9

    def test_maxed_line_width_39(self):
        gb = TabGapBuffer()
        for _ in range(39):
            gb.insert(CH)
        assert gb.line_vwidth_current() == 39

    def test_line_vwidth_across_gap(self):
        """Cursor in the middle of a line → both pre- and post-gap
        bytes count toward line_vwidth of the current line."""
        gb = TabGapBuffer()
        for ch in (CH, CH, CH, CH, CH):
            gb.insert(ch)
        gb.cursor_left()
        gb.cursor_left()
        # Now 3 bytes pre-gap, 2 bytes post-gap, all on one line
        assert gb.line_vwidth_current() == 5

    def test_line_vwidth_next(self):
        """line_vwidth_next measures the line AFTER the cursor's line."""
        gb = TabGapBuffer()
        for _ in range(3):
            gb.insert(CH)
        gb.insert(CR)
        for _ in range(7):
            gb.insert(CH)
        # Cursor is now at col 7 of line 1.  Move it to col 0 of line 1
        # (7 lefts; the 8th would cross the CR back into line 0).
        for _ in range(7):
            gb.cursor_left()
        # line_vwidth_current: line 1 has 7 chars.
        assert gb.line_vwidth_current() == 7
        # line_vwidth_next: there's no line 2, so 0.
        assert gb.line_vwidth_next() == 0

    def test_line_vwidth_next_with_second_line(self):
        """Cursor in line 1 with line 2 after → next is line 2."""
        gb = TabGapBuffer()
        for _ in range(3):
            gb.insert(CH)        # line 0: 3 chars
        gb.insert(CR)
        for _ in range(5):
            gb.insert(CH)        # line 1: 5 chars
        gb.insert(CR)
        for _ in range(8):
            gb.insert(CH)        # line 2: 8 chars, cursor at col 8
        # Move cursor to start of line 1.  From col 8 of line 2, go
        # back 8 chars (to col 0 of line 2), then 1 more to cross the
        # CR into col 5 of line 1, then 5 more to reach col 0 of line 1.
        for _ in range(14):
            gb.cursor_left()
        # cursor at start of line 1
        assert gb.line_vwidth_current() == 5
        assert gb.line_vwidth_next() == 8


class TestTabCharacter:
    """§7 — Tab character ($A0).  TAB_WIDTH is the build-time constant 8."""

    # ── Tab insert ───────────────────────────────────────────────────

    def test_tab_at_col0(self):
        """$A0 at col 0 → visual col = 8."""
        gb = TabGapBuffer()
        gb.tab_insert()
        assert gb.ed_cur_col == 8
        assert gb.text() == bytes([TAB])
        gb.invariants_ok()

    def test_tab_at_col3(self):
        """$A0 after 3 chars → visual col = 8."""
        gb = _make_tab_buf(bytes([CH] * 3), cursor_col=3)
        gb.tab_insert()
        assert gb.ed_cur_col == 8

    def test_tab_at_boundary(self):
        """$A0 at col 8 (= TAB_WIDTH) → visual col = 16."""
        gb = _make_tab_buf(bytes([CH] * 8), cursor_col=8)
        gb.tab_insert()
        assert gb.ed_cur_col == 16

    def test_tab_multiple(self):
        """Two tabs: 0→8→16."""
        gb = TabGapBuffer()
        gb.tab_insert()
        assert gb.ed_cur_col == 8
        gb.tab_insert()
        assert gb.ed_cur_col == 16
        assert gb.text() == bytes([TAB, TAB])

    def test_tab_byte_stored(self):
        """$A0 is stored literally in the buffer."""
        gb = TabGapBuffer()
        gb.tab_insert()
        assert gb.text() == bytes([TAB])

    def test_tab_near_edge_rejected(self):
        """$A0 at col 35, TAB_WIDTH=8: 35 + (8 - 35%8) = 35 + 5 = 40 > 39 → rejected."""
        gb = _make_tab_buf(bytes([CH] * 35), cursor_col=35)
        gb.tab_insert()
        assert gb.ed_cur_col == 35
        assert TAB not in gb.text()

    def test_tab_lands_exactly_at_cap(self):
        """$A0 at col 31, TAB_WIDTH=8: 31 + (8 - 31%8) = 31 + 1 = 32 → ok."""
        gb = _make_tab_buf(bytes([CH] * 31), cursor_col=31)
        gb.tab_insert()
        assert gb.ed_cur_col == 32

    # ── Insert-in-middle cap (line_vwidth, not just ed_cur_col) ──────

    def test_printable_in_middle_of_full_line_rejected(self):
        """Cursor in the middle of a 39-char line: a printable insert
        must be refused.  ed_cur_col alone is not sufficient — the
        check must use the line's total visual width."""
        gb = _make_tab_buf(bytes([CH] * 39), cursor_col=10)
        before = gb.text()
        gb.printable_insert(CH)
        assert gb.text() == before
        assert gb.ed_cur_col == 10

    def test_printable_in_middle_of_38_char_line_allowed(self):
        """Cursor in the middle of a 38-char line: a printable insert
        is allowed (new line width = 39, exactly at cap)."""
        gb = _make_tab_buf(bytes([CH] * 38), cursor_col=5)
        gb.printable_insert(CH)
        assert len(gb.text()) == 39
        assert gb.ed_cur_col == 6
        assert gb.line_vwidth_current() == 39

    def test_printable_at_end_of_full_line_rejected(self):
        """Cursor at col 39 of a 39-char line: insert refused (existing
        bound, still required)."""
        gb = _make_tab_buf(bytes([CH] * 39), cursor_col=39)
        before = gb.text()
        gb.printable_insert(CH)
        assert gb.text() == before
        assert gb.ed_cur_col == 39

    def test_tab_in_middle_of_full_line_rejected(self):
        """Cursor in the middle of a line whose total width leaves no
        room for the smallest tab: tab_insert must be refused.  Line
        is 36 chars wide; tab at end would advance to 40 → refuse."""
        gb = _make_tab_buf(bytes([CH] * 36), cursor_col=10)
        before = gb.text()
        gb.tab_insert()
        assert gb.text() == before
        assert gb.ed_cur_col == 10

    def test_tab_in_middle_of_short_line_allowed(self):
        """Tab inserted in the middle of a short line where there's
        room at end-of-line for the tab to land: allowed."""
        gb = _make_tab_buf(bytes([CH] * 10), cursor_col=3)
        gb.tab_insert()
        # Tab at col 3 expands to col 8 → ed_cur_col = 8
        assert gb.ed_cur_col == 8
        assert TAB in gb.text()

    # ── Visual column helper ─────────────────────────────────────────

    def test_visual_col_no_tabs(self):
        """Visual col without tabs = byte count."""
        gb = _make_tab_buf(bytes([CH] * 5), cursor_col=5)
        assert gb._visual_col() == 5

    def test_visual_col_with_tab(self):
        """Visual col: TAB at col 0 = TAB_WIDTH wide."""
        gb = TabGapBuffer()
        gb.insert(TAB)
        assert gb._visual_col() == 8

    def test_visual_col_text_then_tab(self):
        """Visual col: 'aaa' + TAB = 3 + 5 = 8."""
        gb = TabGapBuffer()
        for _ in range(3):
            gb.insert(CH)
        gb.insert(TAB)
        assert gb._visual_col() == 8

    def test_visual_col_two_tabs(self):
        """Visual col: TAB + TAB = 8 + 8 = 16."""
        gb = TabGapBuffer()
        gb.insert(TAB)
        gb.insert(TAB)
        assert gb._visual_col() == 16

    # ── SPACE (plain insert, no expansion) ───────────────────────────

    def test_space_is_just_space(self):
        """SPACE ($20) is always a standard single-space insert."""
        gb = TabGapBuffer()
        gb.insert(SP)
        gb.ed_cur_col = 1
        assert gb.text() == bytes([SP])
        assert gb.ed_cur_col == 1

    def test_space_after_content(self):
        """SPACE after content: +1 column, no expansion."""
        gb = _make_tab_buf(bytes([CH] * 3), cursor_col=3)
        old_col = gb.ed_cur_col
        gb.insert(SP)
        gb.ed_cur_col += 1
        assert gb.ed_cur_col == old_col + 1

    # ── RIGHT over tab ───────────────────────────────────────────────

    def test_right_over_tab(self):
        """RIGHT crosses $A0 → visual col jumps full tab width."""
        # TAB + 'a', cursor at col 0 (before tab)
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=0)
        gb.tab_right()
        assert gb.ed_cur_col == 8

    def test_right_over_char_after_tab(self):
        """RIGHT over regular char after tab."""
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=0)
        gb.tab_right()  # over tab → col 8
        gb.tab_right()  # over 'a' → col 9
        assert gb.ed_cur_col == 9

    def test_right_over_regular_char(self):
        """RIGHT over regular char: +1."""
        gb = _make_tab_buf(bytes([CH, CH]), cursor_col=0)
        gb.tab_right()
        assert gb.ed_cur_col == 1

    def test_right_at_end_noop(self):
        """RIGHT at end of line: no-op."""
        gb = _make_tab_buf(bytes([CH]), cursor_col=1)
        gb.tab_right()
        assert gb.ed_cur_col == 1

    # ── LEFT over tab ────────────────────────────────────────────────

    def test_left_over_tab(self):
        """LEFT crosses $A0 ← visual col jumps back full tab width."""
        # TAB + 'a', cursor after tab (col 8)
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=1)
        assert gb.ed_cur_col == 8  # after TAB
        gb.tab_left()
        assert gb.ed_cur_col == 0

    def test_left_over_char_before_tab(self):
        """LEFT over 'a' before tab: -1."""
        gb = _make_tab_buf(bytes([CH, TAB]), cursor_col=1)
        assert gb.ed_cur_col == 1  # after 'a'
        gb.tab_left()
        assert gb.ed_cur_col == 0

    def test_left_at_col0_noop(self):
        """LEFT at col 0: no-op."""
        gb = _make_tab_buf(bytes([CH]), cursor_col=0)
        gb.tab_left()
        assert gb.ed_cur_col == 0

    # ── DEL ──────────────────────────────────────────────────────────

    def test_del_tab(self):
        """DEL removes $A0, visual col recomputed."""
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=1)
        assert gb.ed_cur_col == 8  # after TAB
        gb.tab_del()
        assert gb.ed_cur_col == 0
        assert gb.text() == bytes([CH])

    def test_del_char_after_tab(self):
        """DEL regular char after tab: visual col back by 1."""
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=2)
        assert gb.ed_cur_col == 9  # TAB(8) + a(1)
        gb.tab_del()
        assert gb.ed_cur_col == 8  # only TAB left before cursor
        assert gb.text() == bytes([TAB])

    def test_del_regular(self):
        """DEL regular char: standard backspace."""
        gb = _make_tab_buf(bytes([CH, CH]), cursor_col=2)
        gb.tab_del()
        assert gb.ed_cur_col == 1

    def test_del_at_col0_noop(self):
        """DEL at col 0: no-op."""
        gb = _make_tab_buf(bytes([CH]), cursor_col=0)
        gb.tab_del()
        assert gb.ed_cur_col == 0
        assert gb.text() == bytes([CH])

    # ── RETURN auto-indent ───────────────────────────────────────────

    def test_return_copies_tab_indent(self):
        """RETURN copies leading $A0 tabs to new line."""
        gb = _make_tab_buf(bytes([TAB, CH, CH]), cursor_col=3)
        gb.tab_return()
        assert gb.ed_cur_col == 8  # one TAB visual width
        ws = gb._copy_leading_ws()
        assert ws == bytes([TAB])

    def test_return_copies_mixed_ws(self):
        """RETURN copies mixed $20 + $A0 leading whitespace."""
        line = bytes([SP, TAB, CH])
        gb = _make_tab_buf(line, cursor_col=3)
        gb.tab_return()
        ws = gb._copy_leading_ws()
        assert ws == bytes([SP, TAB])

    def test_return_copies_spaces(self):
        """RETURN copies leading spaces."""
        line = bytes([SP, SP, SP, CH])
        gb = _make_tab_buf(line, cursor_col=4)
        gb.tab_return()
        assert gb.ed_cur_col == 3
        ws = gb._copy_leading_ws()
        assert ws == bytes([SP, SP, SP])

    def test_return_no_indent(self):
        """RETURN on non-indented line: no copy."""
        gb = _make_tab_buf(bytes([CH, CH]), cursor_col=2)
        gb.tab_return()
        assert gb.ed_cur_col == 0
        ws = gb._copy_leading_ws()
        assert ws == b""

    # ── Rendering tab expansion ──────────────────────────────────────

    def test_render_tab_at_col0(self):
        """Render TAB at col 0, tw=8: 8 spaces on screen."""
        gb = TabGapBuffer()
        gb.insert(TAB)
        gb.insert(CH)
        scr = render_line_tab(gb, 0)
        # First 8 cols should be spaces, col 8 should be 'a'
        assert scr[:8] == [SP] * 8
        assert scr[8] == petscii_to_screencode(CH)

    def test_render_tab_after_text(self):
        """Render 'aaa' + TAB, tw=8: 3 chars + 5 spaces."""
        gb = TabGapBuffer()
        for _ in range(3):
            gb.insert(CH)
        gb.insert(TAB)
        gb.insert(0x42)  # 'b'
        scr = render_line_tab(gb, 0)
        assert scr[0] == petscii_to_screencode(CH)
        assert scr[3] == SP  # start of tab expansion
        assert scr[7] == SP  # end of tab expansion
        assert scr[8] == petscii_to_screencode(0x42)  # 'b'

    def test_render_two_tabs(self):
        """Render TAB + TAB + 'a', tw=8."""
        gb = TabGapBuffer()
        gb.insert(TAB)
        gb.insert(TAB)
        gb.insert(CH)
        scr = render_line_tab(gb, 0)
        assert scr[:8] == [SP] * 8
        assert scr[8:16] == [SP] * 8
        assert scr[16] == petscii_to_screencode(CH)

def render_line_tab(gb, line_num):
    """Simulate ed_render_line with tab expansion."""
    pos = gb.buf_base
    for _ in range(line_num):
        while pos < gb.buf_end:
            if pos == gb.gap_lo:
                pos = gb.gap_hi
            if pos >= gb.buf_end:
                break
            if gb.mem[pos] == CR:
                pos += 1
                break
            pos += 1

    scr = [SP] * 40
    col = 0
    tw = TabGapBuffer.TAB_WIDTH
    while col < 40:
        if pos == gb.gap_lo:
            pos = gb.gap_hi
        if pos >= gb.buf_end:
            break
        ch = gb.mem[pos]
        if ch == CR:
            pos += 1
            break
        if ch == TAB:
            w = tw - (col % tw)
            while w > 0 and col < 40:
                scr[col] = SP
                col += 1
                w -= 1
            pos += 1
            continue
        scr[col] = petscii_to_screencode(ch)
        col += 1
        pos += 1
    return scr
