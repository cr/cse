"""test_log.py — Tier-U unit tests for log.s.

Contract source: [doc/modules/log.md](../../doc/modules/log.md).

Coverage of the documented contract
-----------------------------------
All 13 exported entry points:

    log_open / log_close           — primitive open/close (+ auto-newline
                                      contract: enter anywhere, exit at col 0)
    log_line                       — open + content + close
    log_err / log_warn / log_info  — convenience wrappers (Y preset)
    puts_imm                       — inline-string print (via `puts` macro)
    seg_line / prg_line / free_line — "; TAG  AAAA-BBBB NNNNNb [free]"
    info_line_head / info_line_tail — prefix/suffix halves of info_line

Plus the documented "enter anywhere, exit at col 0" invariant:
  - log_open auto-advances when CUR_COL != 0
    (test_log_open_auto_advances_when_cursor_mid_line)
  - log_open does NOT newline when already at col 0
    (test_log_open_no_newline_when_cursor_at_col_0)

Bundle
------
`zp + strings + cse_io + screen + log + cse_io_test_stub`.  The stub
provides the shared `kplot_stub` symbol (KERNAL PLOT replacement
using cse_io's own scr_lo/scr_hi tables — a sanctioned slim mock
per testing.md § Shared stubs).  $FFF0 is patched at setup time to
jump into `kplot_stub` so cse_io's `io_sync` reaches it.
"""

import pytest

from conftest import make_cpu, push_rts_sentinel, step_until_pc

# ── Screen/layout constants ─────────────────────────────────────────
SCREEN_BASE = 0x0400
COLS        = 40
TEST_ROW    = 10
CONTENT_ADDR = 0x3100   # scratch area for NUL-terminated test strings

# Screen codes (identity with PETSCII for punctuation range)
SC_SPACE = 0x20
SC_SEMI  = 0x3B
SC_EXCL  = 0x21
SC_QMARK = 0x3F
SC_DASH  = 0x2D
SC_B     = 0x02   # 'b' in CSE shifted charset ($01 = 'a')


# ── Harness setup ────────────────────────────────────────────────────

def _patch_plot(mem, kplot_addr):
    """Patch $FFF0 with JMP kplot_stub so cse_io's io_sync reaches
    the shared PLOT replacement from cse_io_test_stub.s."""
    mem[0xFFF0] = 0x4C                          # JMP abs
    mem[0xFFF1] = kplot_addr & 0xFF
    mem[0xFFF2] = (kplot_addr >> 8) & 0xFF


def _setup(log_syms, row=TEST_ROW, col=0):
    """Fresh MPU with log bundle loaded, PLOT patched, cursor at
    (row, col), and TEST_ROW cleared to spaces."""
    cpu, mem = make_cpu(log_syms)
    _patch_plot(mem, log_syms.kplot_stub)

    # Clear TEST_ROW
    base = SCREEN_BASE + row * COLS
    for i in range(COLS):
        mem[base + i] = SC_SPACE

    # Place cursor via KERNAL PLOT (CLC path).  We drive it by
    # priming $D6/$D3 then calling io_sync which reads those back
    # through PLOT's GET+SET cycle — the same path every io_putc
    # implicitly uses.
    mem[0xD6] = row
    mem[0xD3] = col
    _run(cpu, log_syms.io_sync)
    return cpu, mem


def _run(cpu, entry, a=0, x=0, y=0, max_steps=200_000):
    """JSR-sentinel driver: push fake return, set regs, step to
    sentinel, raise on overflow."""
    sentinel = push_rts_sentinel(cpu, sentinel=0x01F0)
    cpu.a = a; cpu.x = x; cpu.y = y
    cpu.pc = entry
    step_until_pc(cpu, sentinel, max_steps=max_steps, what=f"entry=${entry:04X}")


def _row(mem, row=TEST_ROW):
    """Read one screen row as a list of bytes."""
    base = SCREEN_BASE + row * COLS
    return [mem[base + c] for c in range(COLS)]


def _row_text(mem, row=TEST_ROW):
    """Decode screen row to ASCII (CSE shifted charset: $01-$1A →
    lowercase, $41-$5A → uppercase, $20-$3F → identity, $00 → '@')."""
    out = []
    for sc in _row(mem, row):
        sc &= 0x7F
        if sc == 0x00:          out.append('@')
        elif 0x01 <= sc <= 0x1A: out.append(chr(sc + 0x60))
        elif 0x20 <= sc <= 0x3F: out.append(chr(sc))
        elif 0x41 <= sc <= 0x5A: out.append(chr(sc))
        else:                    out.append('?')
    return ''.join(out).rstrip()


def _write_string(mem, addr, s):
    """Write a NUL-terminated PETSCII string."""
    for i, ch in enumerate(s.encode('ascii')):
        mem[addr + i] = ch
    mem[addr + len(s)] = 0


def _find_bytes(row, pattern):
    for i in range(len(row) - len(pattern) + 1):
        if row[i:i+len(pattern)] == list(pattern):
            return i
    return -1


# ── log_open / log_close primitives ─────────────────────────────────

def test_log_open_info_writes_semicolon_space(log_syms):
    """log_open(Y=LOG_INFO=$20) → col 0 = ';', col 1 = ' '."""
    cpu, mem = _setup(log_syms)
    _run(cpu, log_syms.log_open, y=0x20)
    row = _row(mem)
    assert row[0] == SC_SEMI,  f"col 0 should be ';'; got ${row[0]:02X}"
    assert row[1] == SC_SPACE, f"col 1 should be ' '; got ${row[1]:02X}"


def test_log_open_warn_writes_semicolon_bang(log_syms):
    """log_open(Y='!') → ';!'."""
    cpu, mem = _setup(log_syms)
    _run(cpu, log_syms.log_open, y=ord('!'))
    row = _row(mem)
    assert row[0] == SC_SEMI
    assert row[1] == SC_EXCL


def test_log_open_err_writes_semicolon_qmark(log_syms):
    """log_open(Y='?') → ';?'."""
    cpu, mem = _setup(log_syms)
    _run(cpu, log_syms.log_open, y=ord('?'))
    row = _row(mem)
    assert row[0] == SC_SEMI
    assert row[1] == SC_QMARK


def test_log_close_advances_cursor(log_syms):
    """log_close does io_clear_eol + newline — cursor moves next row."""
    cpu, mem = _setup(log_syms)
    _run(cpu, log_syms.log_open, y=0x20)
    assert mem[0xD6] == TEST_ROW
    _run(cpu, log_syms.log_close)
    assert mem[0xD6] == TEST_ROW + 1, \
        f"cursor should have advanced one row; got {mem[0xD6]}"


def test_puts_imm_reads_inline_word_correctly(log_syms):
    """puts_imm must read the .word argument after its JSR — verify
    by assembling a tiny stub at RAM that does `jsr puts_imm; .word
    str_known; rts`.  Guards against the Y=$FF backstep regression
    (see optimization.md §19): log_info/err/warn pass A/X directly to
    io_puts and do NOT exercise puts_imm's inline-word path."""
    cpu, mem = _setup(log_syms)
    str_addr = log_syms.s["str_blk_eq"]
    stub = 0x3200
    puts = log_syms.puts_imm
    mem[stub + 0] = 0x20                            # JSR
    mem[stub + 1] = puts & 0xFF
    mem[stub + 2] = (puts >> 8) & 0xFF
    mem[stub + 3] = str_addr & 0xFF                 # .word lo
    mem[stub + 4] = (str_addr >> 8) & 0xFF          # .word hi
    mem[stub + 5] = 0x60                            # RTS
    _run(cpu, stub)
    text = _row_text(mem).lower()
    assert "blk=" in text, f"puts_imm didn't print str_blk_eq; row={text!r}"


# ── Convenience entries (log_err / log_warn / log_info) ─────────────

def test_log_info_full_line(log_syms):
    """log_info(A/X=content) → ';  CONTENT' at cursor + newline."""
    cpu, mem = _setup(log_syms)
    _write_string(mem, CONTENT_ADDR, "hello")
    _run(cpu, log_syms.log_info, a=CONTENT_ADDR & 0xFF, x=(CONTENT_ADDR >> 8))
    row = _row(mem)
    assert row[0] == SC_SEMI
    assert row[1] == SC_SPACE
    assert "HELLO" in _row_text(mem), f"decoded row: {_row_text(mem)!r}"


def test_log_err_prefix_question(log_syms):
    """log_err(A/X=content) → ';?CONTENT'."""
    cpu, mem = _setup(log_syms)
    _write_string(mem, CONTENT_ADDR, "oops")
    _run(cpu, log_syms.log_err, a=CONTENT_ADDR & 0xFF, x=(CONTENT_ADDR >> 8))
    row = _row(mem)
    assert row[0] == SC_SEMI
    assert row[1] == SC_QMARK


def test_log_warn_prefix_bang(log_syms):
    """log_warn(A/X=content) → ';!CONTENT'."""
    cpu, mem = _setup(log_syms)
    _write_string(mem, CONTENT_ADDR, "careful")
    _run(cpu, log_syms.log_warn, a=CONTENT_ADDR & 0xFF, x=(CONTENT_ADDR >> 8))
    row = _row(mem)
    assert row[0] == SC_SEMI
    assert row[1] == SC_EXCL


# ── Range-line formatters (seg_line / prg_line / free_line) ─────────

def test_seg_line_shows_range_and_size(log_syms):
    """seg_line formats '; TAG  AAAA-BBBB NNNNNb' (inclusive end)."""
    cpu, mem = _setup(log_syms)
    tag = log_syms.s["str_tag_org"]
    mem[log_syms.rp_ptr2]     = tag & 0xFF
    mem[log_syms.rp_ptr2 + 1] = (tag >> 8) & 0xFF
    mem[log_syms.rp_addr]     = 0x00
    mem[log_syms.rp_addr + 1] = 0xC0
    mem[log_syms.rp_cnt]      = 0x0F
    mem[log_syms.rp_cnt + 1]  = 0xC0
    mem[log_syms.rp_save2]    = 0

    _run(cpu, log_syms.seg_line)

    row = _row(mem)
    # "C000-C00F" — 'C'=$03, '0'=$30, '-'=$2D, 'F'=$06
    pattern = [0x03, 0x30, 0x30, 0x30, SC_DASH, 0x03, 0x30, 0x30, 0x06]
    assert _find_bytes(row, pattern) >= 0, \
        f"AAAA-BBBB pattern not found; row={[hex(b) for b in row]}"
    non_space = [b for b in row if b != SC_SPACE]
    assert non_space[-1] == SC_B, \
        f"last non-space should be 'b' ($02); row={[hex(b) for b in row]}"


def test_prg_line_decrements_inclusive(log_syms):
    """prg_line takes exclusive-end rp_cnt, emits inclusive-end display.
    rp_addr=$1000, rp_cnt=$1010 (exclusive) → shows $1000-$100F."""
    cpu, mem = _setup(log_syms)
    mem[log_syms.rp_addr]     = 0x00
    mem[log_syms.rp_addr + 1] = 0x10
    mem[log_syms.rp_cnt]      = 0x10
    mem[log_syms.rp_cnt + 1]  = 0x10
    _run(cpu, log_syms.prg_line)

    row = _row(mem)
    pattern = [0x31, 0x30, 0x30, 0x30, SC_DASH, 0x31, 0x30, 0x30, 0x06]
    assert _find_bytes(row, pattern) >= 0, \
        f"$1000-$100F pattern not found; row={[hex(b) for b in row]}"


def test_free_line_appends_free_suffix(log_syms):
    """free_line emits '; TAG  AAAA-BBBB NNNNNb free' — identical to
    seg_line plus ' free' suffix + highlight control via _info_mode."""
    cpu, mem = _setup(log_syms)
    tag = log_syms.s["str_tag_org"]
    mem[log_syms.rp_ptr2]     = tag & 0xFF
    mem[log_syms.rp_ptr2 + 1] = (tag >> 8) & 0xFF
    mem[log_syms.rp_addr]     = 0x00
    mem[log_syms.rp_addr + 1] = 0xC0
    mem[log_syms.rp_cnt]      = 0x0F
    mem[log_syms.rp_cnt + 1]  = 0xC0
    mem[log_syms._info_mode]  = 1
    _run(cpu, log_syms.free_line)

    text = _row_text(mem).lower()
    assert "c000-c00f" in text, f"AAAA-BBBB missing: {text!r}"
    assert "free" in text,      f"'free' suffix missing: {text!r}"


def test_info_line_head_prints_tag_and_range(log_syms):
    """info_line_head prefix: '; TAG  AAAA-BBBB ' with tag padded to 5 cols."""
    cpu, mem = _setup(log_syms)
    tag = log_syms.s["str_tag_org"]
    mem[log_syms.rp_ptr2]     = tag & 0xFF
    mem[log_syms.rp_ptr2 + 1] = (tag >> 8) & 0xFF
    mem[log_syms.rp_addr]     = 0x00
    mem[log_syms.rp_addr + 1] = 0x20
    mem[log_syms.rp_cnt]      = 0xFF
    mem[log_syms.rp_cnt + 1]  = 0x2F
    _run(cpu, log_syms.info_line_head)

    text = _row_text(mem).lower()
    assert text.startswith(";"),   f"missing leading ';': {text!r}"
    assert "org" in text,          f"tag 'org' missing: {text!r}"
    assert "2000-2fff" in text,    f"AAAA-BBBB missing: {text!r}"


def test_info_line_tail_pads_to_40_and_newlines(log_syms):
    """info_line_tail pads remainder of row with spaces and advances."""
    cpu, mem = _setup(log_syms)
    tag = log_syms.s["str_tag_org"]
    mem[log_syms.rp_ptr2]     = tag & 0xFF
    mem[log_syms.rp_ptr2 + 1] = (tag >> 8) & 0xFF
    mem[log_syms.rp_addr]     = 0x00
    mem[log_syms.rp_addr + 1] = 0x30
    mem[log_syms.rp_cnt]      = 0x00
    mem[log_syms.rp_cnt + 1]  = 0x33
    mem[log_syms.rp_save2]    = 0
    _run(cpu, log_syms.info_line_head)
    _run(cpu, log_syms.info_line_tail)

    assert mem[0xD6] == TEST_ROW + 1, \
        f"cursor row = {mem[0xD6]}, expected {TEST_ROW + 1}"
    row = _row(mem)
    assert row[-1] == SC_SPACE, f"last col not padded: ${row[-1]:02X}"


# ── log_open auto-newline contract (enter-anywhere, exit-at-col-0) ──

def test_log_open_auto_advances_when_cursor_mid_line(log_syms):
    """log_open's 'enter-anywhere, exit-at-col-0' contract: if
    CUR_COL != 0 at entry, log_open must advance to a fresh row
    before emitting ';'.  See [log.md § Interface]."""
    cpu, mem = _setup(log_syms, row=TEST_ROW, col=12)
    _run(cpu, log_syms.log_open, y=0x20)

    assert mem[0xD6] == TEST_ROW + 1, \
        f"cursor row = {mem[0xD6]}, expected TEST_ROW+1"
    next_row = _row(mem, TEST_ROW + 1)
    assert next_row[0] == SC_SEMI
    assert next_row[1] == SC_SPACE


def test_log_open_no_newline_when_cursor_at_col_0(log_syms):
    """When CUR_COL=0, log_open does NOT consume a row — it emits
    ';' + level char at the current row."""
    cpu, mem = _setup(log_syms)
    assert mem[0xD3] == 0
    row_before = mem[0xD6]
    _run(cpu, log_syms.log_open, y=0x20)
    assert mem[0xD6] == row_before, \
        f"cursor row advanced unexpectedly: {mem[0xD6]} != {row_before}"
    row = _row(mem, row_before)
    assert row[0] == SC_SEMI
    assert row[1] == SC_SPACE


# log_err_eol / log_close_eol were retired pre-Tier-U move — their
# logic was redundant (trailing io_clear_eol on a row show_prompt
# overwrites; leading newline wasted a visual row).  Callers use
# log_err / log_close directly now.
