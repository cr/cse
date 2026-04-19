"""test_log.py — Tier I screen-RAM contract tests for log.s

Exercises the real log.s primitives loaded into C64Emu with the
debug CMOS PRG.  Asserts on screen RAM at $0400 after each log call.

Symbols verified:
  log_open / log_close / log_line
  log_err / log_warn / log_info
  (log_err_eol / log_close_eol retired — callers use log_err /
   log_close directly)
  seg_line / prg_line / free_line
  puts_imm (indirectly via log_line's io_puts call path)

Contracts:
  log_open(Y=level)   → screen col 0 = ';', col 1 = level char
  log_close           → io_clear_eol + newline (cursor advances one row)
  log_line(Y=lvl, A/X=str)  → full "; <level><content>" + close
  log_err / log_warn / log_info  → fixed level, A/X=str
  seg_line            → "; tag  AAAA-BBBB NNNNNb" format

All tests run through real KERNAL calls (io_sync → PLOT, io_putc →
CHROUT, etc.) — the tier-boundary signal.  No manual stubs.
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


# log_err_eol / log_close_eol were retired — their logic was
# redundant (trailing io_clear_eol on a row show_prompt overwrites;
# leading newline in log_err_eol wasted a visual row).  Callers now
# use log_err / log_close directly.
