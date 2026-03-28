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
# §7  Tab character ($A0)
# ═══════════════════════════════════════════════════════════════════════════════

SP = 0x20   # space
TAB = 0xA0  # tab (C=+SPACE)
CH = 0x41   # non-space content (PETSCII 'a')
CR = 0x0D


class TabGapBuffer(GapBuffer):
    """GapBuffer extended with tab character ($A0) support."""

    def __init__(self, tab_width=8):
        super().__init__()
        self.tab_width = tab_width

    # ── Visual column helpers ────────────────────────────────────────


    def _char_width(self, ch, vcol):
        """Visual width of one byte at visual column vcol."""
        if ch == TAB and self.tab_width > 0:
            return self.tab_width - (vcol % self.tab_width)
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
        """C=+SPACE: insert $A0 tab byte, advance to next tab stop."""
        tw = self.tab_width
        if tw == 0:
            return
        w = self._char_width(TAB, self.ed_cur_col)
        if self.ed_cur_col + w > 38:
            return  # would overflow screen
        self.insert(TAB)
        self.ed_cur_col += w

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

    def tab_return(self):
        """RETURN with auto-indent: copy leading $20/$A0 from current line."""
        tw = self.tab_width
        ws = self._copy_leading_ws() if tw > 0 else b""
        self.insert(CR)
        self.ed_cur_line += 1
        self.ed_cur_col = 0
        for ch in ws:
            self.insert(ch)
        self.ed_cur_col = self._visual_col()


def _make_tab_buf(line_bytes, cursor_col=0, tab_width=8):
    """Create a TabGapBuffer with one line, cursor at given column."""
    gb = TabGapBuffer(tab_width=tab_width)
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


class TestTabCharacter:
    """§7 — Tab character ($A0)."""

    # ── Tab insert ───────────────────────────────────────────────────

    def test_tab_at_col0(self):
        """$A0 at col 0 → visual col = tw."""
        gb = TabGapBuffer(tab_width=8)
        gb.tab_insert()
        assert gb.ed_cur_col == 8
        assert gb.text() == bytes([TAB])
        gb.invariants_ok()

    def test_tab_at_col3(self):
        """$A0 after 3 chars, tw=8 → visual col = 8."""
        gb = _make_tab_buf(bytes([CH] * 3), cursor_col=3, tab_width=8)
        gb.tab_insert()
        assert gb.ed_cur_col == 8

    def test_tab_at_boundary(self):
        """$A0 at col 8 (= tw), tw=8 → visual col = 16."""
        gb = _make_tab_buf(bytes([CH] * 8), cursor_col=8, tab_width=8)
        gb.tab_insert()
        assert gb.ed_cur_col == 16

    def test_tab_tw4(self):
        """$A0 at col 1, tw=4 → visual col = 4."""
        gb = _make_tab_buf(bytes([CH]), cursor_col=1, tab_width=4)
        gb.tab_insert()
        assert gb.ed_cur_col == 4

    def test_tab_tw0_noop(self):
        """tw=0 → tab insert is no-op."""
        gb = TabGapBuffer(tab_width=0)
        gb.tab_insert()
        assert gb.text() == b""
        assert gb.ed_cur_col == 0

    def test_tab_multiple(self):
        """Two tabs: 0→8→16."""
        gb = TabGapBuffer(tab_width=8)
        gb.tab_insert()
        assert gb.ed_cur_col == 8
        gb.tab_insert()
        assert gb.ed_cur_col == 16
        assert gb.text() == bytes([TAB, TAB])

    def test_tab_byte_stored(self):
        """$A0 is stored literally in the buffer."""
        gb = TabGapBuffer(tab_width=8)
        gb.tab_insert()
        assert gb.text() == bytes([TAB])

    def test_tab_near_edge_rejected(self):
        """$A0 near col 38 rejected if it would overflow."""
        gb = _make_tab_buf(bytes([CH] * 35), cursor_col=35, tab_width=8)
        gb.tab_insert()
        # 35 + (8 - 35%8) = 35 + 5 = 40 > 38 → rejected
        assert gb.ed_cur_col == 35
        assert TAB not in gb.text()

    def test_tab_exactly_fits(self):
        """$A0 at col 35, tw=4: 35 + (4 - 35%4) = 35 + 1 = 36 ≤ 38 → ok."""
        gb = _make_tab_buf(bytes([CH] * 35), cursor_col=35, tab_width=4)
        gb.tab_insert()
        assert gb.ed_cur_col == 36

    # ── Visual column helper ─────────────────────────────────────────

    def test_visual_col_no_tabs(self):
        """Visual col without tabs = byte count."""
        gb = _make_tab_buf(bytes([CH] * 5), cursor_col=5, tab_width=8)
        assert gb._visual_col() == 5

    def test_visual_col_with_tab(self):
        """Visual col: TAB at col 0 = tw wide."""
        gb = TabGapBuffer(tab_width=8)
        gb.insert(TAB)
        assert gb._visual_col() == 8

    def test_visual_col_text_then_tab(self):
        """Visual col: 'aaa' + TAB = 3 + 5 = 8."""
        gb = TabGapBuffer(tab_width=8)
        for _ in range(3):
            gb.insert(CH)
        gb.insert(TAB)
        assert gb._visual_col() == 8

    def test_visual_col_two_tabs(self):
        """Visual col: TAB + TAB = 8 + 8 = 16."""
        gb = TabGapBuffer(tab_width=8)
        gb.insert(TAB)
        gb.insert(TAB)
        assert gb._visual_col() == 16

    # ── SPACE (plain insert, no expansion) ───────────────────────────

    def test_space_is_just_space(self):
        """SPACE ($20) is always a standard single-space insert."""
        gb = TabGapBuffer(tab_width=8)
        gb.insert(SP)
        gb.ed_cur_col = 1
        assert gb.text() == bytes([SP])
        assert gb.ed_cur_col == 1

    def test_space_after_content(self):
        """SPACE after content: +1 column, no expansion."""
        gb = _make_tab_buf(bytes([CH] * 3), cursor_col=3, tab_width=8)
        old_col = gb.ed_cur_col
        gb.insert(SP)
        gb.ed_cur_col += 1
        assert gb.ed_cur_col == old_col + 1

    # ── RIGHT over tab ───────────────────────────────────────────────

    def test_right_over_tab(self):
        """RIGHT crosses $A0 → visual col jumps full tab width."""
        # TAB + 'a', cursor at col 0 (before tab)
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=0, tab_width=8)
        gb.tab_right()
        assert gb.ed_cur_col == 8

    def test_right_over_char_after_tab(self):
        """RIGHT over regular char after tab."""
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=0, tab_width=8)
        gb.tab_right()  # over tab → col 8
        gb.tab_right()  # over 'a' → col 9
        assert gb.ed_cur_col == 9

    def test_right_over_regular_char(self):
        """RIGHT over regular char: +1."""
        gb = _make_tab_buf(bytes([CH, CH]), cursor_col=0, tab_width=8)
        gb.tab_right()
        assert gb.ed_cur_col == 1

    def test_right_at_end_noop(self):
        """RIGHT at end of line: no-op."""
        gb = _make_tab_buf(bytes([CH]), cursor_col=1, tab_width=8)
        gb.tab_right()
        assert gb.ed_cur_col == 1

    # ── LEFT over tab ────────────────────────────────────────────────

    def test_left_over_tab(self):
        """LEFT crosses $A0 ← visual col jumps back full tab width."""
        # TAB + 'a', cursor after tab (col 8)
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=1, tab_width=8)
        assert gb.ed_cur_col == 8  # after TAB
        gb.tab_left()
        assert gb.ed_cur_col == 0

    def test_left_over_char_before_tab(self):
        """LEFT over 'a' before tab: -1."""
        gb = _make_tab_buf(bytes([CH, TAB]), cursor_col=1, tab_width=8)
        assert gb.ed_cur_col == 1  # after 'a'
        gb.tab_left()
        assert gb.ed_cur_col == 0

    def test_left_at_col0_noop(self):
        """LEFT at col 0: no-op."""
        gb = _make_tab_buf(bytes([CH]), cursor_col=0, tab_width=8)
        gb.tab_left()
        assert gb.ed_cur_col == 0

    # ── DEL ──────────────────────────────────────────────────────────

    def test_del_tab(self):
        """DEL removes $A0, visual col recomputed."""
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=1, tab_width=8)
        assert gb.ed_cur_col == 8  # after TAB
        gb.tab_del()
        assert gb.ed_cur_col == 0
        assert gb.text() == bytes([CH])

    def test_del_char_after_tab(self):
        """DEL regular char after tab: visual col back by 1."""
        gb = _make_tab_buf(bytes([TAB, CH]), cursor_col=2, tab_width=8)
        assert gb.ed_cur_col == 9  # TAB(8) + a(1)
        gb.tab_del()
        assert gb.ed_cur_col == 8  # only TAB left before cursor
        assert gb.text() == bytes([TAB])

    def test_del_regular(self):
        """DEL regular char: standard backspace."""
        gb = _make_tab_buf(bytes([CH, CH]), cursor_col=2, tab_width=8)
        gb.tab_del()
        assert gb.ed_cur_col == 1

    def test_del_at_col0_noop(self):
        """DEL at col 0: no-op."""
        gb = _make_tab_buf(bytes([CH]), cursor_col=0, tab_width=8)
        gb.tab_del()
        assert gb.ed_cur_col == 0
        assert gb.text() == bytes([CH])

    # ── RETURN auto-indent ───────────────────────────────────────────

    def test_return_copies_tab_indent(self):
        """RETURN copies leading $A0 tabs to new line."""
        gb = _make_tab_buf(bytes([TAB, CH, CH]), cursor_col=3, tab_width=8)
        gb.tab_return()
        assert gb.ed_cur_col == 8  # one TAB visual width
        ws = gb._copy_leading_ws()
        assert ws == bytes([TAB])

    def test_return_copies_mixed_ws(self):
        """RETURN copies mixed $20 + $A0 leading whitespace."""
        line = bytes([SP, TAB, CH])
        gb = _make_tab_buf(line, cursor_col=3, tab_width=8)
        gb.tab_return()
        ws = gb._copy_leading_ws()
        assert ws == bytes([SP, TAB])

    def test_return_copies_spaces(self):
        """RETURN copies leading spaces."""
        line = bytes([SP, SP, SP, CH])
        gb = _make_tab_buf(line, cursor_col=4, tab_width=8)
        gb.tab_return()
        assert gb.ed_cur_col == 3
        ws = gb._copy_leading_ws()
        assert ws == bytes([SP, SP, SP])

    def test_return_no_indent(self):
        """RETURN on non-indented line: no copy."""
        gb = _make_tab_buf(bytes([CH, CH]), cursor_col=2, tab_width=8)
        gb.tab_return()
        assert gb.ed_cur_col == 0
        ws = gb._copy_leading_ws()
        assert ws == b""

    def test_return_tw0_no_indent(self):
        """RETURN with tw=0: no auto-indent."""
        line = bytes([SP, SP, CH])
        gb = _make_tab_buf(line, cursor_col=3, tab_width=0)
        gb.tab_return()
        assert gb.ed_cur_col == 0

    # ── Rendering tab expansion ──────────────────────────────────────

    def test_render_tab_at_col0(self):
        """Render TAB at col 0, tw=8: 8 spaces on screen."""
        gb = TabGapBuffer(tab_width=8)
        gb.insert(TAB)
        gb.insert(CH)
        scr = render_line_tab(gb, 0)
        # First 8 cols should be spaces, col 8 should be 'a'
        assert scr[:8] == [SP] * 8
        assert scr[8] == petscii_to_screencode(CH)

    def test_render_tab_after_text(self):
        """Render 'aaa' + TAB, tw=8: 3 chars + 5 spaces."""
        gb = TabGapBuffer(tab_width=8)
        for _ in range(3):
            gb.insert(CH)
        gb.insert(TAB)
        gb.insert(0x42)  # 'b'
        scr = render_line_tab(gb, 0)
        assert scr[0] == petscii_to_screencode(CH)
        assert scr[3] == SP  # start of tab expansion
        assert scr[7] == SP  # end of tab expansion
        assert scr[8] == petscii_to_screencode(0x42)  # 'b'

    def test_render_tab_tw4(self):
        """Render 'a' + TAB, tw=4: col 1 → 3 spaces → content at col 4."""
        gb = TabGapBuffer(tab_width=4)
        gb.insert(CH)
        gb.insert(TAB)
        gb.insert(0x42)
        scr = render_line_tab(gb, 0)
        assert scr[0] == petscii_to_screencode(CH)
        assert scr[1] == SP
        assert scr[2] == SP
        assert scr[3] == SP
        assert scr[4] == petscii_to_screencode(0x42)

    def test_render_two_tabs(self):
        """Render TAB + TAB + 'a', tw=8."""
        gb = TabGapBuffer(tab_width=8)
        gb.insert(TAB)
        gb.insert(TAB)
        gb.insert(CH)
        scr = render_line_tab(gb, 0)
        assert scr[:8] == [SP] * 8
        assert scr[8:16] == [SP] * 8
        assert scr[16] == petscii_to_screencode(CH)

    def test_render_tab_tw0_single_space(self):
        """Render TAB with tw=0: single space."""
        gb = TabGapBuffer(tab_width=0)
        gb.insert(TAB)
        gb.insert(CH)
        scr = render_line_tab(gb, 0)
        assert scr[0] == SP
        assert scr[1] == petscii_to_screencode(CH)


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
    tw = gb.tab_width
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
            w = (tw - (col % tw)) if tw > 0 else 1
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
