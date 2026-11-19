# log — Standardised logging API

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/log.s`](../../src/log.s) | implementation |
| [`src/log.inc`](../../src/log.inc) | shared level constants (`LOG_ERR`, `LOG_WARN`, `LOG_INFO`) |
| [`src/macros.inc`](../../src/macros.inc) | shared `puts` macro that calls `puts_imm` (in this module) |
| [`tests/unit/test_log.py`](../../tests/unit/test_log.py) | test contract |

## Interface

`newline` (screen.s) moves to the next row, scrolling at the bottom;
what it clobbers is in [screen.md](screen.md).  "newline's clobbers"
below means that set.

### log_open
**In:**  Y = level char (`LOG_ERR`/`LOG_WARN`/`LOG_INFO`)
**Out:** cursor after `;` + level char on a fresh row (auto-newlines
when entered mid-line, so caller does not need one)
**Clobbers:** A, X, Y, `_io_scr`; mid-line also newline's clobbers

Opens a log line.  The caller appends content via `io_puts` /
`io_putdec` / etc., then calls `log_close`.  `rp_tmp`-safe (callers may
hold a pointer there across the `log_open` call).

### log_close
**In:**  none
**Out:** clears to end of line, then advances to the next row
**Clobbers:** A, X, Y, `_io_scr`, newline's clobbers

### log_line
**In:**  Y = level char, A/X = content string pointer
**Out:** complete `;<level><content>` line, cleared to end of line,
then newline
**Clobbers:** as `log_open` + `log_close`, plus `rp_tmp` / `rp_tmp+1`
and `_io_tmp`

Composes `log_open` + `io_puts(content)` + `log_close`.

### log_err / log_warn / log_info
**In:**  A/X = content string pointer
**Out:** same as `log_line` with Y preset to the matching level
**Clobbers:** same as `log_line`

Convenience entry points that save `ldy #LOG_*` at each call site.

### puts_imm
**In:**  inline `.word str` argument following the `jsr puts_imm` call
**Out:** prints the RODATA string via `io_puts`; adjusts the return
address to land after the `.word`
**Clobbers:** A, X, Y, `rp_tmp` / `rp_tmp+1`, `_io_tmp`, `_io_scr`

Called via the `puts str` macro (`src/macros.inc`, owned here) —
`jsr puts_imm` + `.word str`.  Reads the pointer from the two bytes
immediately after the `jsr`, advances the stacked return address past
them, tail-calls `io_puts`.

### seg_line / prg_line / free_line
**In:**  `rp_addr` (start address), `rp_cnt` (end address — see the
table), and:
- `seg_line`: `rp_ptr2` = tag string, `rp_save2` = highlight flag
  (0 = none);
- `prg_line`: no tag input — it sets `rp_ptr2` = `str_tag_prg`
  (`prg`) and `rp_save2` = 0;
- `free_line`: `rp_ptr2` = tag string, `_info_mode` (0 = highlight
  the range, 1 = not; copied inverted into `rp_save2`).
**Out:** `"; TAG  AAAA-BBBB NNNNNb"` (`free_line`: `… NNNNNb free`)
line at a fresh row, padded with spaces to column 40, then newline.
`NNNNN` is the inclusive size, right-aligned in five columns; on m65
a whole bank (`0000`–`FFFF`, a size that wraps 16 bits) is `65536`.
**Clobbers:** A, X, Y, `rp_ptr`, `rp_save`, `rp_next_lo`,
`_io_tmp`, `_io_scr`, newline's clobbers; `prg_line` also `rp_ptr2`,
`rp_save2` and `rp_cnt` (decremented); `free_line` also `rp_save2`
and `rp_tmp` (`puts`).  `rp_addr` is not modified.

| Function | `rp_cnt` meaning | Suffix | Caller |
|---|---|---|---|
| `seg_line` | inclusive end (asm_src passes `asm_pc - 1`) | `"b"` | asm_src.s `_seg_log_close` |
| `prg_line` | exclusive end (decremented internally) | `"b"` | repl.s `prg_ok_done` (PRG load/save) |
| `free_line` | inclusive end | `"b free"` | repl.s `cmd_info` |

### info_line / info_line_head / info_line_tail
**In:**  `rp_addr` (lo), `rp_cnt` (hi), `rp_ptr2` (tag string),
`rp_ptr` (desc string, for `info_line`), `rp_save2` (highlight flag,
for `info_line_tail`)
**Out:** `"; TAG  AAAA-BBBB <desc>"` at a fresh row, optionally
highlighted (reverse) on the `AAAA-BBBB` columns, padded to 40 cols +
newline.  `info_line_head` prints the prefix up to and including the
space after `BBBB` and leaves the row's screen address in
`rp_next_lo`; `info_line_tail` pads to the width (`WIDTH`), highlights
and newlines, through `rp_ptr` with the screen's bank
(`FAR_BANK_SCREEN`).

**On m65** every range is written with its bank, `b.AAAA-BBBB`
([glossary.md](../glossary.md)): `info_line_head` prints the digit in
`info_bank` (log.s's BSS) and `.` before `AAAA`, and the highlight
covers columns 7–17.  `info_bank` is 0 — the program region's bank,
so the assembler's segment and PRG rows read `0.aaaa-bbbb` — except
while `cmd_info` writes its rows.
**Clobbers:** A, X, Y, `rp_save`, `rp_next_lo`, `rp_ptr`, `_io_tmp`,
`_io_scr`, newline's clobbers

Used by `cmd_info` for multi-line memory-map displays.

**Depends on:** cse_io (`io_putc`, `io_puts`, `io_putdec_pd`,
`io_puthex4`, `io_repc`, `io_clear_eol`, `scr_lo`, `scr_hi`), screen
(`newline`), zp (`rp_tmp`, `rp_ptr`, `rp_ptr2`, `rp_addr`, `rp_cnt`,
`rp_save`, `rp_save2`, `rp_next_lo`, `_info_mode`), strings
(`str_free_suf`, `str_tag_prg`)

## Design

Three log levels distinguished by the first column of the line:

| Level | Char | Prefix | Use |
|---|---|---|---|
| `LOG_ERR`  | `?` | `;?` | error |
| `LOG_WARN` | `!` | `;!` | warning |
| `LOG_INFO` | ` ` (space) | `; ` | info |

Contract: **enter anywhere, exit at col 0.** `log_open` (and
`info_line_head`) auto-advance to a fresh row when `CUR_COL != 0`,
so callers never need a defensive `jsr newline` before opening a
log line.  `log_close` then does `io_clear_eol + newline`, so
output flows line-by-line without explicit newlines at call
sites.

The contract is **compositional** — it's the paired
open-and-close operation that guarantees both halves, not any
individual function:

| Entry point | Enter-anywhere | Exit-at-col-0 | How |
|---|---|---|---|
| `log_open` | yes | no (leaves cursor after `;X`) | auto-advance if CUR_COL != 0 |
| `log_close` | n/a (called mid-line) | yes | `io_clear_eol + newline` |
| `log_line` / `log_err` / `log_warn` / `log_info` | yes | yes | log_open + content + log_close |
| `info_line_head` | yes | no (leaves cursor mid-line) | auto-advance if CUR_COL != 0 |
| `info_line_tail` | n/a | yes | pad-to-40 + `newline` |
| `info_line` / `seg_line` / `prg_line` / `free_line` | yes | yes | info_line_head + content + info_line_tail |
| `puts_imm` | n/a (inline text) | n/a (inline text) | outside the contract |

The ten line-starting entry points are pinned by
`tests/unit/test_log.py::TestEnterAnywhereContract` — a parametrised
sweep over nine of them — and `TestInfoLine` for `info_line`, per
Principle 8 (contractual coverage is exhaustive, not illustrative).  The
line-enders' exit-at-col-0 guarantees are pinned by
`test_log_close_advances_cursor` and
`test_info_line_tail_pads_to_40_and_newlines`.

Address context goes in the `AAAA:` prefix (caller's job).  Line
references go at the tail of the content (`LNNN`).

### Range-line format

The `seg_line` / `prg_line` / `free_line` family emits a fixed-width
range line that doubles as a log line (leading `;` + space at column 0):

```
; TAG  AAAA-BBBB NNNNNb [free]
; TAG  b.AAAA-BBBB NNNNNb [free]       (m65)
```

Used in three contexts:
- Assembler segment summary — one line per segment during pass 1
  ([asm_src.md § Error and warning lines](asm_src.md#error-and-warning-lines)).
- `i` command — free-region map lines.
- PRG save/load summary — one line per file operation tail.

Single formatter, one ownership.  Callers pick the variant that
matches their "end address" convention.

## Caveats

- `log_line` and `puts_imm` clobber `rp_tmp` / `rp_tmp+1` (they park
  a pointer there).  Callers holding a pointer in `rp_tmp` across a
  `log_line` call must save it to the 6502 stack first.
- `log_close` ends with `newline` which scrolls if the cursor is on
  the last row.  Callers that want the cursor left exactly where
  `log_open`'s content ended must inline a `log_open` + content
  emit + manual `io_clear_eol` instead of calling `log_close`.
