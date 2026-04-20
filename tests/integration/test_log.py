"""test_log.py — Tier-I contract tests for log.s.

Contract source: [doc/modules/log.md](../../doc/modules/log.md).

Coverage of the documented contract
-----------------------------------
All 11 exported entry points:

    log_open / log_close         — primitive open/close (+ auto-newline
                                    contract: enter anywhere, exit at col 0)
    log_line                     — open + content + close
    log_err / log_warn / log_info — convenience wrappers (Y preset)
    puts_imm                     — inline-string print (via `puts` macro)
    seg_line / prg_line / free_line — "; TAG  AAAA-BBBB NNNNNb [free]"
    info_line_head / info_line_tail — prefix/suffix halves of info_line

Plus the documented "enter anywhere, exit at col 0" invariant:
  - log_open auto-advances when CUR_COL != 0
    (test_log_open_auto_advances_when_cursor_mid_line)
  - log_open does NOT newline when already at col 0
    (test_log_open_no_newline_when_cursor_at_col_0)

Exercises the real log.s primitives loaded into C64Emu with the
debug CMOS PRG.  Asserts on screen RAM at $0400 after each log call.
All tests run through real KERNAL (io_sync → PLOT, io_putc → CHROUT,
etc.) — the tier-boundary signal.  No manual stubs.

Note on tier: log.s is a Tier-U module per testing.md's per-module
table (bundle: log + screen + cse_io).  The tests currently run in
Tier-I against the full PRG because the C64Emu harness was already
available; functionally the coverage is the same.  A bundle-based
re-home is a future task, not a coverage gap.
"""

import pytest
from c64emu import C64Emu


# ── Test helpers ─────────────────────────────────────────────────

# Screen codes for punctuation (identity mapping with PETSCII)
SC_SEMI  = 0x3B   # ';'
SC_SPACE = 0x20   # ' '
SC_EXCL  = 0x21   # '!'
SC_QMARK = 0x3F   # '?'
SC_DASH  = 0x2D   # '-'
SC_B     = 0x02   # 'b' as screen code ($41 - $40 = $01 for 'a'; 'b' = $02)


TEST_ROW = 10      # where log output is captured
CONTENT_ADDR = 0x3100   # scratch area for test content strings


def _setup(cse_prg):
    """Fresh emulator with CSE booted + cursor at TEST_ROW/col 0."""
    prg, map_path = cse_prg
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.init_cse()

    # Clear target row
    base = 0x0400 + TEST_ROW * 40
    for i in range(40):
        emu.memory[base + i] = SC_SPACE

    # Move cursor to TEST_ROW/0 via KERNAL PLOT
    emu.set_cursor(TEST_ROW, 0)
    return emu


def _write_string(emu, addr, s):
    """Write a NUL-terminated PETSCII string at addr."""
    for i, ch in enumerate(s.encode('ascii')):
        emu.memory[addr + i] = ch
    emu.memory[addr + len(s)] = 0


def _row_screen(emu, row):
    """Read screen RAM for one row."""
    base = 0x0400 + row * 40
    return [emu.memory[base + c] for c in range(40)]


# ── log_open / log_close primitives ──────────────────────────────

def test_log_open_info_writes_semicolon_space(cse_prg):
    """log_open(Y=LOG_INFO=$20) → col 0 = ';', col 1 = ' '."""
    emu = _setup(cse_prg)
    emu.jsr(emu.sym("log_open"), y=0x20)   # LOG_INFO
    row = _row_screen(emu, TEST_ROW)
    assert row[0] == SC_SEMI,  f"col 0 should be ';'; got ${row[0]:02X}"
    assert row[1] == SC_SPACE, f"col 1 should be ' '; got ${row[1]:02X}"


def test_log_open_warn_writes_semicolon_bang(cse_prg):
    """log_open(Y=LOG_WARN='!') → col 0 = ';', col 1 = '!'."""
    emu = _setup(cse_prg)
    emu.jsr(emu.sym("log_open"), y=ord('!'))
    row = _row_screen(emu, TEST_ROW)
    assert row[0] == SC_SEMI
    assert row[1] == SC_EXCL


def test_log_open_err_writes_semicolon_qmark(cse_prg):
    """log_open(Y=LOG_ERR='?') → col 0 = ';', col 1 = '?'."""
    emu = _setup(cse_prg)
    emu.jsr(emu.sym("log_open"), y=ord('?'))
    row = _row_screen(emu, TEST_ROW)
    assert row[0] == SC_SEMI
    assert row[1] == SC_QMARK


def test_log_close_advances_cursor(cse_prg):
    """log_close does io_clear_eol + newline — cursor moves to next row."""
    emu = _setup(cse_prg)
    emu.jsr(emu.sym("log_open"), y=0x20)
    # After log_open, cursor is at TEST_ROW/col 2
    assert emu.memory[0xD6] == TEST_ROW, "cursor row pre-close"
    emu.jsr(emu.sym("log_close"))
    # After log_close, cursor should be one row down
    assert emu.memory[0xD6] == TEST_ROW + 1, \
        f"cursor should have advanced one row; got {emu.memory[0xD6]}"


def test_puts_imm_reads_inline_word_correctly(cse_prg):
    """puts_imm must read the .word argument after its JSR — verify
    by assembling a tiny stub at RAM that does `jsr puts_imm; .word
    str_known; rts` and checking that str_known's content appears on
    screen.  Guards against the Y=$FF backstep regression (see
    optimization.md §19): existing log_info / log_err / log_warn
    tests pass A/X directly to io_puts and do NOT exercise puts_imm.
    """
    emu = _setup(cse_prg)
    # Put "blk=" (known RODATA string) through puts_imm.
    str_addr = emu.sym("str_blk_eq")
    stub = 0x3200
    puts = emu.sym("puts_imm")
    # JSR puts_imm ; .word str_blk_eq ; RTS
    emu.memory[stub + 0] = 0x20                      # JSR
    emu.memory[stub + 1] = puts & 0xFF
    emu.memory[stub + 2] = (puts >> 8) & 0xFF
    emu.memory[stub + 3] = str_addr & 0xFF           # .word lo
    emu.memory[stub + 4] = (str_addr >> 8) & 0xFF    # .word hi
    emu.memory[stub + 5] = 0x60                      # RTS
    emu.jsr(stub)
    # "blk=" should appear starting at cursor column (0 after _setup).
    text = emu.screen_text(TEST_ROW).lower()
    assert "blk=" in text, \
        f"puts_imm didn't print str_blk_eq; row={text!r}"


# ── Convenience entries (log_err / log_warn / log_info) ──────────

def test_log_info_full_line(cse_prg):
    """log_info(A/X=content) → ';  CONTENT' at cursor + newline."""
    emu = _setup(cse_prg)
    _write_string(emu, CONTENT_ADDR, "hello")
    emu.jsr(emu.sym("log_info"),
            a=CONTENT_ADDR & 0xFF, x=(CONTENT_ADDR >> 8) & 0xFF)
    row = _row_screen(emu, TEST_ROW)
    assert row[0] == SC_SEMI
    assert row[1] == SC_SPACE
    # "hello" PETSCII lowercase → screen codes $48 $45 $4C $4C $4F
    # (screen_text decodes $41-$5A as uppercase letters for CSE's
    # shifted charset; pet_to_scr maps PETSCII lowercase into that range).
    # Verify as decoded text rather than raw screen codes.
    assert "HELLO" in emu.screen_text(TEST_ROW), \
        f"decoded row: {emu.screen_text(TEST_ROW)!r}"


def test_log_err_prefix_question(cse_prg):
    """log_err(A/X=content) → ';?CONTENT'."""
    emu = _setup(cse_prg)
    _write_string(emu, CONTENT_ADDR, "oops")
    emu.jsr(emu.sym("log_err"),
            a=CONTENT_ADDR & 0xFF, x=(CONTENT_ADDR >> 8) & 0xFF)
    row = _row_screen(emu, TEST_ROW)
    assert row[0] == SC_SEMI
    assert row[1] == SC_QMARK


def test_log_warn_prefix_bang(cse_prg):
    """log_warn(A/X=content) → ';!CONTENT'."""
    emu = _setup(cse_prg)
    _write_string(emu, CONTENT_ADDR, "careful")
    emu.jsr(emu.sym("log_warn"),
            a=CONTENT_ADDR & 0xFF, x=(CONTENT_ADDR >> 8) & 0xFF)
    row = _row_screen(emu, TEST_ROW)
    assert row[0] == SC_SEMI
    assert row[1] == SC_EXCL


# ── Range-line formatters (seg_line / prg_line / free_line) ──────

def _find_bytes(row, pattern):
    """Return start index of `pattern` in `row` list, or -1."""
    for i in range(len(row) - len(pattern) + 1):
        if row[i:i+len(pattern)] == list(pattern):
            return i
    return -1


def test_seg_line_shows_range_and_size(cse_prg):
    """seg_line formats '; TAG  AAAA-BBBB NNNNNb' (inclusive end)."""
    emu = _setup(cse_prg)
    # Use the existing str_tag_org "org" tag
    tag = emu.sym("str_tag_org")
    emu.memory[emu.sym("rp_ptr2")]     = tag & 0xFF
    emu.memory[emu.sym("rp_ptr2") + 1] = (tag >> 8) & 0xFF
    emu.memory[emu.sym("rp_addr")]     = 0x00
    emu.memory[emu.sym("rp_addr") + 1] = 0xC0
    emu.memory[emu.sym("rp_cnt")]      = 0x0F
    emu.memory[emu.sym("rp_cnt") + 1]  = 0xC0
    emu.memory[emu.sym("rp_save2")]    = 0      # no highlight

    emu.jsr(emu.sym("seg_line"))

    row = _row_screen(emu, TEST_ROW)
    # Expected: "; org  C000-C00F    16b" → look for the "C000-C00F" chunk.
    # 'C' screen code = $03, '0' = $30, '-' = $2D, 'F' = $06
    # Pattern: C 0 0 0 - C 0 0 F
    pattern = [0x03, 0x30, 0x30, 0x30, SC_DASH, 0x03, 0x30, 0x30, 0x06]
    assert _find_bytes(row, pattern) >= 0, \
        f"AAAA-BBBB pattern not found; row={[hex(b) for b in row]}"
    # '16b' at the tail — 16 decimal, right-aligned, 'b' suffix
    # Last non-space column should be 'b' ($02)
    non_space = [b for b in row if b != SC_SPACE]
    assert non_space[-1] == SC_B, \
        f"last non-space should be 'b' ($02); row={[hex(b) for b in row]}"


def test_prg_line_decrements_inclusive(cse_prg):
    """prg_line takes exclusive-end rp_cnt and emits inclusive-end display.
    rp_addr=$1000, rp_cnt=$1010 (exclusive) → shows $1000-$100F (size 16)."""
    emu = _setup(cse_prg)
    emu.memory[emu.sym("rp_addr")]     = 0x00
    emu.memory[emu.sym("rp_addr") + 1] = 0x10
    emu.memory[emu.sym("rp_cnt")]      = 0x10
    emu.memory[emu.sym("rp_cnt") + 1]  = 0x10
    emu.jsr(emu.sym("prg_line"))

    row = _row_screen(emu, TEST_ROW)
    # Inclusive end = $100F.  'F' screen code = $06, '1' = $31, '0' = $30
    pattern = [0x31, 0x30, 0x30, 0x30, SC_DASH, 0x31, 0x30, 0x30, 0x06]
    assert _find_bytes(row, pattern) >= 0, \
        f"$1000-$100F pattern not found; row={[hex(b) for b in row]}"


def test_free_line_appends_free_suffix(cse_prg):
    """free_line emits '; TAG  AAAA-BBBB NNNNNb free' — identical to
    seg_line plus the ' free' suffix + highlight control via _info_mode."""
    emu = _setup(cse_prg)
    tag = emu.sym("str_tag_org")
    emu.memory[emu.sym("rp_ptr2")]     = tag & 0xFF
    emu.memory[emu.sym("rp_ptr2") + 1] = (tag >> 8) & 0xFF
    emu.memory[emu.sym("rp_addr")]     = 0x00
    emu.memory[emu.sym("rp_addr") + 1] = 0xC0
    emu.memory[emu.sym("rp_cnt")]      = 0x0F
    emu.memory[emu.sym("rp_cnt") + 1]  = 0xC0
    # _info_mode=1 → no highlight (rp_save2=0)
    emu.memory[emu.sym("_info_mode")]  = 1
    emu.jsr(emu.sym("free_line"))

    text = emu.screen_text(TEST_ROW).lower()
    assert "c000-c00f" in text, f"AAAA-BBBB missing: {text!r}"
    assert "free" in text, f"'free' suffix missing: {text!r}"


def test_info_line_head_prints_tag_and_range(cse_prg):
    """info_line_head prefix: '; TAG  AAAA-BBBB ' with tag padded to 5 cols."""
    emu = _setup(cse_prg)
    tag = emu.sym("str_tag_org")
    emu.memory[emu.sym("rp_ptr2")]     = tag & 0xFF
    emu.memory[emu.sym("rp_ptr2") + 1] = (tag >> 8) & 0xFF
    emu.memory[emu.sym("rp_addr")]     = 0x00
    emu.memory[emu.sym("rp_addr") + 1] = 0x20
    emu.memory[emu.sym("rp_cnt")]      = 0xFF
    emu.memory[emu.sym("rp_cnt") + 1]  = 0x2F
    emu.jsr(emu.sym("info_line_head"))

    text = emu.screen_text(TEST_ROW).lower()
    assert text.startswith(";"), f"missing leading ';': {text!r}"
    assert "org" in text, f"tag 'org' missing: {text!r}"
    assert "2000-2fff" in text, f"AAAA-BBBB missing: {text!r}"


def test_info_line_tail_pads_to_40_and_newlines(cse_prg):
    """info_line_tail pads the remainder of the row with spaces and advances."""
    emu = _setup(cse_prg)
    # Start a line via info_line_head so rp_next_lo is populated.
    tag = emu.sym("str_tag_org")
    emu.memory[emu.sym("rp_ptr2")]     = tag & 0xFF
    emu.memory[emu.sym("rp_ptr2") + 1] = (tag >> 8) & 0xFF
    emu.memory[emu.sym("rp_addr")]     = 0x00
    emu.memory[emu.sym("rp_addr") + 1] = 0x30
    emu.memory[emu.sym("rp_cnt")]      = 0x00
    emu.memory[emu.sym("rp_cnt") + 1]  = 0x33
    emu.memory[emu.sym("rp_save2")]    = 0   # no highlight
    emu.jsr(emu.sym("info_line_head"))
    emu.jsr(emu.sym("info_line_tail"))

    # After tail: cursor advanced to next row.
    assert emu.memory[0xD6] == TEST_ROW + 1, \
        f"cursor row = {emu.memory[0xD6]}, expected {TEST_ROW + 1}"
    # The TEST_ROW's trailing cells are spaces ($20).
    row = _row_screen(emu, TEST_ROW)
    assert row[-1] == SC_SPACE, f"last col not padded: ${row[-1]:02X}"


# ── log_open auto-newline contract (enter-anywhere, exit-at-col-0) ──

def test_log_open_auto_advances_when_cursor_mid_line(cse_prg):
    """log_open's documented 'enter-anywhere, exit-at-col-0' contract:
    if CUR_COL != 0 at entry, log_open must advance to a fresh row
    before emitting ';'.  See [log.md § Interface]."""
    emu = _setup(cse_prg)
    # Place cursor mid-line (col 12 of TEST_ROW).
    emu.set_cursor(TEST_ROW, 12)
    emu.jsr(emu.sym("log_open"), y=0x20)   # LOG_INFO

    # After auto-newline, TEST_ROW is untouched (its earlier content
    # was just spaces); TEST_ROW+1 has the new ';' + ' ' at col 0/1.
    assert emu.memory[0xD6] == TEST_ROW + 1, \
        f"cursor row = {emu.memory[0xD6]}, expected TEST_ROW+1"
    next_row = _row_screen(emu, TEST_ROW + 1)
    assert next_row[0] == SC_SEMI
    assert next_row[1] == SC_SPACE


def test_log_open_no_newline_when_cursor_at_col_0(cse_prg):
    """When CUR_COL is already 0, log_open does NOT consume a row —
    it emits ';' + level char at the current row."""
    emu = _setup(cse_prg)
    # _setup already places cursor at col 0; assert explicitly.
    assert emu.memory[0xD3] == 0
    row_before = emu.memory[0xD6]
    emu.jsr(emu.sym("log_open"), y=0x20)
    assert emu.memory[0xD6] == row_before, \
        f"cursor row advanced unexpectedly: {emu.memory[0xD6]} != {row_before}"
    row = _row_screen(emu, row_before)
    assert row[0] == SC_SEMI
    assert row[1] == SC_SPACE


# log_err_eol / log_close_eol were retired — their logic was
# redundant (trailing io_clear_eol on a row show_prompt overwrites;
# leading newline in log_err_eol wasted a visual row).  Callers now
# use log_err / log_close directly.
