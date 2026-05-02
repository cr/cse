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

### log_open
**In:**  Y = level char (`LOG_ERR`/`LOG_WARN`/`LOG_INFO`)
**Out:** cursor after `;` + level char on a fresh row (auto-newlines
when entered mid-line, so caller does not need one)
**Clobbers:** A

Opens a log line.  The caller appends content via `io_puts` / `io_putdec` /
etc., then calls `log_close`.  `rp_tmp`-safe (callers may hold a pointer
there across the `log_open` call).

### log_close
**In:**  none
**Out:** clears to end of line, then advances to the next row
**Clobbers:** A, Y

### log_line
**In:**  Y = level char, A/X = content string pointer
**Out:** complete `;<level><content>` line followed by newline + clear
**Clobbers:** A, X, Y, `rp_tmp` / `rp_tmp+1`

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
**Clobbers:** A, X, Y, `rp_tmp` / `rp_tmp+1`

Called via the `puts str` macro (defined in repl.s's macro header,
shared to every caller).  Read the pointer from the two bytes
immediately after the `jsr`, advance past them, tail-call `io_puts`.

### seg_line / prg_line / free_line
**In:**  `rp_addr` (start address), `rp_cnt` (byte count or end addr —
see per-function), A/X = tag string pointer
**Out:** `"; TAG  AAAA-BBBB NNNNNb [free]"` line printed at cursor
followed by a log_close (clear-eol + newline)
**Clobbers:** A, X, Y, `rp_addr`, `rp_cnt`, formatter scratch

Three variants distinguished by the `rp_cnt` convention:

| Function | `rp_cnt` meaning | Suffix |
|---|---|---|
| `seg_line` | Inclusive end-address (asm_src passes `asm_pc - 1`) | `"b"` |
| `prg_line` | Exclusive end or size (KERNAL LOAD X/Y return, or `rp_addr + size`) | `"b"` |
| `free_line` | Inclusive end-address (cmd_info free-region endpoints) | `"b free"` |

All three display the range with BBBB inclusive.  `prg_line`
decrements internally before calling the shared display core.

### info_line / info_line_head / info_line_tail
**In:**  `rp_addr` (lo), `rp_cnt` (hi), `rp_ptr2` (tag string),
`rp_ptr` (desc string, for info_line), `rp_save2` (highlight flag,
for info_line_tail)
**Out:** `"; TAG  AAAA-BBBB <desc>"` at cursor, optionally
highlighted on the AAAA-BBBB bytes, padded to 40 cols + newline
**Clobbers:** A, X, Y, `rp_save`, `rp_next_lo`, `rp_ptr`

Used by `cmd_info` for multi-line memory-map displays.

**Depends on:** cse_io (io_putc, io_puts, io_putdec_pd,
io_puthex4, io_repc, io_clear_eol, newline, scr_lo, scr_hi),
zp (rp_tmp, rp_ptr, rp_ptr2, rp_addr, rp_cnt, rp_save, rp_save2,
rp_next_lo, _info_mode), strings (str_free_suf, str_tag_prg)

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

Every line-starting entry point is pinned by
`tests/unit/test_log.py::TestEnterAnywhereContract` — a
parametrised sweep over the 9 line-starters, per Principle 8
(contractual coverage is exhaustive, not illustrative).  The
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
```

Used in three contexts:
- Assembler segment summary — one line per `.org` during pass 1.
- `i` command — workspace / free-region map lines.
- PRG save/load summary — one line per file operation tail.

Single formatter, one ownership.  Callers pick the variant that
matches their "end address" convention.

## Caveats

- `log_line` clobbers `rp_tmp` / `rp_tmp+1` (parks the content pointer
  across `log_open`).  Callers holding a pointer in `rp_tmp` across a
  `log_line` call must save it to the 6502 stack first.
- `log_close` ends with `newline` which scrolls if the cursor is on
  the last row.  Callers that want the cursor left exactly where
  `log_open`'s content ended must inline a `log_open` + content
  emit + manual `io_clear_eol` instead of calling `log_close`.
