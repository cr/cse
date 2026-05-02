# editor.s — Keystroke Dispatch + Screen Rendering + Disk I/O (L4)

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/editor.s`](../../src/editor.s) | implementation (6502 assembly) |
| [`tests/integration/test_editor.py`](../../tests/integration/test_editor.py) | test contract |

**Split (2026-04-20 structural refactor).**  Gap-buffer primitives
and the sequential reader live in [gap_buffer.md](gap_buffer.md) at
L3 — a pure data-structure module that bundle-tests in isolation.
This module (editor.s, L4) keeps everything that genuinely requires
screen RAM + KERNAL + disk: keystroke dispatch, rendering pipeline,
scroll drivers, smart indent, enter/leave_editor, disk I/O.  The
split makes the tier boundary compile-time-enforced (L4 editor.s
imports from L3 gap_buffer.s, never the reverse) rather than a
disciplined convention — same pattern as the breakpoints split
from debugger.s.

## Interface

All public functions use register/ZP calling convention (single arg
in A or A/X; multi-arg via named ZP variables).

Owned by editor.s (L4):
- `enter_editor()` — save REPL screen, switch to editor mode
- `leave_editor()` — restore REPL screen, return to REPL
- `ed_handle_key(ch)` — process one keystroke (A = PETSCII key)
- `ed_init()` — full reset: calls `gb_init`, zeros rendering state, calls `update_workend` to republish the `workend` symbol against the new `buf_base`
- `ed_new()` — clear source buffer (calls `ed_init` + clears filename)
- `ed_save_source(name)` — save source as SEQ file; A=0 on success
- `ed_load_source(name)` — load SEQ file into buffer; A=0 on success

Owned by gap_buffer.s (L3), re-listed here for editor-consumer convenience:
- `ed_ensure_init()` — allocate gap buffer if not yet done
- `ed_read_rewind()` — reset sequential reader to start of source
- `ed_read_line(buf)` — read next line into buf (maxlen=40 hardcoded); A/X = length or $FFFF at EOF
- `ed_read_byte()` — read next byte from source; A/X = byte or $FFFF at EOF
- `ed_insert_string(text)` — programmatic text insertion at cursor

See [gap_buffer.md](gap_buffer.md) for the L3 module's full
contract (insert/delete/cursor primitives, partial-result behaviour
of the reader, buffer-growth semantics).

**Tab width:** `TAB_WIDTH` is a **build-time constant**
(`-DTAB_WIDTH=N`, default 8).  It is not runtime-mutable; there is
no `T` REPL command, no `tab_width` BSS variable.  `TAB_WIDTH`
must be a value in 1..32 at build time.  The default of 8 matches
every C64-era assembler toolchain (Turbo Assembler, MasterSeka,
Relaunch64, ca65 `.lst` output) and makes `col mod TAB_WIDTH`
collapse to `and #$07` on the 6502.

Rationale: baking `TAB_WIDTH` in eliminates the `col_mod_tw`
runtime loop and the `T` REPL command (~30 bytes saved).

**Statistics:** `ed_save_bytes`, `ed_save_lines` (uint16, BSS) —
counts from last file operation.  `ed_total_lines` (uint16, BSS,
exported) — current line count, used by the REPL's `i` command.

**Depends on:** disk (SEQ callbacks), screen, cse_io, log, symtab
(sym_define for `update_workend`), mem (cse_start), strings
(s_workend), zp (state, ed_dirty cross-module flags)

Phase 21.1 Move 6a resolved the pre-existing `cur_project_name`
back-edge by hosting the buffer in `zp.s` as `.exportzp` (17 bytes
at $5E-$6E).  editor.s now `.importzp`s it — no repl-bound
dependency for state remains.

### Zero-page variables

All pointers are 16-bit, little-endian.

| Name | Size | Role |
|------|------|------|
| `gap_lo` | 2 | first byte of gap (insert point) |
| `gap_hi` | 2 | first byte after gap (read point) |
| `buf_base` | 2 | lowest address of buffer (grows down) |
| `ed_top_ptr` | 2 | cached buffer position for first visible line |
| `read_ptr` | 2 | sequential reader position |
| `save_ptr` | 2 | save callback read position (overlaps read_ptr) |
| `ed_tmp` | 2 | scratch pointer (indirect addressing) |
| `ed_scr` | 2 | screen pointer for rendering (indirect addressing) |

`BUF_END` is the constant `__CODE_RUN__` (CSE runtime start,
floating) — not a variable.

`save_ptr` and `read_ptr` are never active concurrently (save runs
to completion before any read), so they share the same ZP location.
`ed_tmp` and `ed_scr` must be in ZP because they are used with
indirect-indexed addressing (`lda (ed_tmp),y`).
Total: 14 ZP bytes.

### Cross-module flag (in zp.s)

| Name | Size | Role |
|------|------|------|
| `ed_dirty` | 1 | buffer modified flag |

`ed_dirty` is an `.exportzp` in zp.s; editor.s writes it; repl.s
reads it for the unsaved-changes gates (`k`, `Q`, `l`, etc.).

### BSS variables

| Name | Size | Role |
|------|------|------|
| `ed_cur_line` | 2 | cursor line (0-based) |
| `ed_cur_col` | 1 | cursor visual column (0-based) |
| `ed_top_line` | 2 | line number at screen row 0 |
| `ed_total_lines` | 2 | total line count in buffer |
| `ed_save_bytes` | 2 | bytes from last file op |
| `ed_save_lines` | 2 | lines from last file op |
| `_load_overflow` | 1 | sticky flag: set if gap buffer overflowed during `ed_load_source` |
| `save_phase` | 1 | save callback state (0=pre-gap, 1=post-gap) |
| `repl_cur_x` | 1 | saved REPL cursor X |
| `repl_cur_y` | 1 | saved REPL cursor Y |
| `src_top` | 2 | Buffer upper bound (for REPL `i` command) |
| `src_bot` | 2 | Buffer lower bound (for REPL `i` command) |

### Internal functions

Internal functions use register/ZP arguments directly — no parameter stack.

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `ed_init` | — | — | reset all state |
| `gb_ensure_room` | — | C=0 fail, C=1 ok | grow buffer if gap exhausted |
| `gb_insert` | A = byte | C=1 ok, C=0 full | insert at gap_lo |
| `gb_backspace` | — | — | delete before gap_lo |
| `gb_cursor_right` | — | — | move gap right |
| `gb_cursor_left` | — | — | move gap left |
| `gb_home` | — | — | move to start of line |
| `skip_one_line` | ed_scr | ed_scr (advanced) | advance ed_scr past one line |
| `prev_line_start` | ed_scr | ed_scr (retreated) | retreat ed_scr to previous line start |
| `visual_col` | — | A = column | recompute cursor column (0..254) |
| `line_vwidth` | ed_scr = line-start ptr | A = width | total visual width of the line starting at ed_scr, stopping at CR/EOF; returns 0..254 normal or `$FF` overflow sentinel.  Used by the renderer to detect lines wider than 39 columns (for the `>` overflow indicator). |
| `cursor_line_vwidth` | — | A = width | walks back to line start, calls `line_vwidth`; used by insert/tab cap checks |
| `char_width` | A = byte, X = vcol | A = width | tab-aware; uses `TAB_WIDTH`. **Clobbers `ed_tmp`** |
| `advance_to_vcol` | A = target col | — | cursor right toward target column, stopping at EOL or when next char would overshoot |
| `load_insert` | A = byte | — | ed_load_source callback: inserts byte via `gb_insert`; no width enforcement |

## Design

### Gap buffer

Standard gap buffer in a contiguous memory region.  Text before the
cursor lives in the pre-gap; text after the cursor lives in the
post-gap.  A movable gap sits between them.

```
buf_base ──→ [pre-gap text] [  GAP  ] [post-gap text] ←── buf_end
                             ^        ^
                          gap_lo    gap_hi
```

- **Insert:** write at `gap_lo++`.  O(1).
- **Backspace:** decrement `gap_lo`.  O(1).
- **Cursor right:** copy one byte from `gap_hi` to `gap_lo`.  O(1).
- **Cursor left:** copy one byte from `gap_lo` to `gap_hi`.  O(1).
- **Line movement:** slide the gap to the target position.  O(n)
  where n is the distance moved.

Lines are separated by $0D (CR).  `ed_total_lines` is maintained
incrementally: +1 on CR insert, -1 on CR delete.

### Memory layout

The buffer occupies the top of the working area, growing downward:

```
$0800 ─┬─ CSE code + data + BSS
       │
       ├─ assembled output (grows up from .org)
       │
       ├─ ··· free ···
       │
       ├─ buf_base (grows down as buffer needs space)
       │
XXXX ─┴─ BUF_END = __CODE_RUN__ (exclusive, floating)
```

The symbol table and name heap live under the KERNAL ROM
($E000–$EEFF), not in the workspace.

`BUF_FLOOR` ($4800) is the lowest address the buffer can grow to.
When the gap is exhausted, `gb_ensure_room` extends `buf_base`
downward by 256 bytes, relocating the pre-gap text with an inline
block copy (ascending copy, since source and destination don't
overlap destructively in the downward direction).  `ed_top_ptr` is
adjusted if it falls in the pre-gap region.

`src_bot` and `src_top` track the buffer bounds for the REPL's `i`
command.

### Screen layout

```
Rows 0–21   Source text (ED_LINES = 22 visible lines)
Row 22      Status bar (reversed video)
Rows 23–24  Last 2 REPL lines above the prompt (context strip)
```

The status bar layout (40 columns, all reversed):

```
*filename        free:LLLL-HHHH LLL,CC
0  1-17         18 19-32      33 34-39
```

- Col 0: dirty flag (`*` if modified, space if clean)
- Cols 1–17: filename (`,s` suffix stripped)
- Cols 19–23: `free:` label
- Cols 24–27: lower free address (`cse_end`, static)
- Col 28: `-`
- Cols 29–32: upper free address (`buf_base - 1`, updates on grow)
- Cols 34–39: cursor position as `LLL,CC` (1-based)

Four partial update functions avoid full redraws:

| Function | Updates | When |
|----------|---------|------|
| `ed_status_pos` | cols 34–39 (LLL,CC) | every cursor move |
| `ed_status_dirty` | col 0 (dirty flag) | first edit only |
| `ed_status_free` | cols 29–32 (HHHH) | buffer grows |
| `ed_render_status` | all 40 columns | mode enter, load, save |

### Rendering

`ed_top_line` and `ed_top_ptr` cache the line number and buffer
position of the first visible line.  All rendering works from this
anchor.

- `ed_render_line(row, &pos)` — render one line from buffer position
  `pos` to screen row `row`.  Advances `pos` past the CR or to
  `BUF_END`.  Transparently skips the gap.  Converts PETSCII to
  screen codes: $41–$5A → $01–$1A (lowercase), $C1–$DA → $41–$5A
  (uppercase).  Expands $A0 (tab) to spaces up to the next
  `TAB_WIDTH` column boundary.  If content extends beyond col 38,
  writes `>` (reversed) in col 39 as an overflow indicator.  Pads
  the rest of the row with spaces.
- `ed_render_range(from, to)` — render screen rows `from` to `to`
  by advancing from `ed_top_ptr`.
- `ed_render()` — full redraw: all 22 lines + status bar.

Scrolling uses an inline block copy on screen RAM for the 21 lines
that don't change, then renders only the single new line:

- `ed_scroll_up` — cursor moved below row 21: copy rows 1–21 up
  to 0–20 (ascending copy), render new bottom line, advance
  `ed_top_ptr`/`ed_top_line`.
- `ed_scroll_down` — cursor moved above row 0: copy rows 0–20
  down to 1–21 (descending copy), render new top line, retreat
  `ed_top_ptr`/`ed_top_line`.

### Mode switching

RUN/STOP toggles between REPL and editor.

**`enter_editor`:**
1. Save REPL cursor position (`CUR_COL`, `CUR_ROW`)
2. Save REPL screen RAM (1000 bytes) to `repl_screen`
3. Initialize gap buffer if first entry (`ed_ensure_init`)
4. Smart indent seed: if the buffer is **truly empty** — both
   `gap_lo == buf_base` (no content before the gap) AND
   `gap_hi == BUF_END` (no content after the gap) — insert a
   single `$A0` (tab) byte and set `ed_cur_col = TAB_WIDTH`,
   leaving `ed_dirty = 0`.  Both halves of the emptiness test
   are required because after `ed_load_source` the cursor is
   rewound to the start: `gap_lo == buf_base` holds even though
   loaded source lives in `[gap_hi, BUF_END)`.  Skipping the
   `gap_hi` half would silently insert a leading tab into a
   just-loaded file.
5. Clear editor area (rows 0–21) with spaces
6. Copy 2 REPL lines above the prompt to rows 23–24 (context strip)
7. Full render (`ed_render`)
8. Restore editor cursor position, set `state = ST_EDIT`

**`leave_editor`:**
1. Restore REPL screen RAM from `repl_screen`
2. Restore REPL cursor position
3. Set `state = ST_REPL`

This is a full screen swap — no shared display area.  The editor
owns all 25 rows while active.  The REPL gets its screen back
verbatim on return.

### Keystroke dispatch

`ed_handle_key` processes one keystroke per call.  All cases end
with the `reposition` label which syncs `CUR_COL`/`CUR_ROW` to the
editor cursor.

| Key | Action | Redraw |
|-----|--------|--------|
| C=+SPACE | Insert $A0 (tab byte), advance `ed_cur_col` to next `TAB_WIDTH` boundary. | current row only + status |
| LEFT | `gb_cursor_left`, decrement `ed_cur_col`; if byte crossed is $A0, `ed_cur_col` snaps back to previous tab-stop-aligned column | status pos only |
| RIGHT | `gb_cursor_right`, increment `ed_cur_col`; if byte crossed is $A0, `ed_cur_col` snaps forward to next tab-stop-aligned column (stops at CR/EOF) | status pos only |
| UP | `ed_cursor_up`: home → left (past CR) → home → advance to target col | scroll down if above viewport, else status pos |
| DOWN | `ed_cursor_down`: advance past CR → advance to target col | scroll up if below viewport, else status pos |
| HOME | `gb_home`: slide gap left to start of current line | status pos only |
| DEL | `gb_backspace`, re-render from current row to bottom.  At col 0 of line > 0: join with previous line.  At col 0 of line 0: refused (blip, left wall). | rows from cursor to bottom + status |
| INS | `gb_insert($20)` then `gb_cursor_left`: opens a space at cursor, cursor stays put.  Refused if line is at 39-col cap. | current row only + status |
| RETURN | Smart indent (see below). | rows from previous line to bottom + status |
| printable | insert char at gap, increment `ed_cur_col`.  Typing `:` at end of line strips the leading $A0 (label slides to column 0) unless the line contains `;` (comment). | current row only + status |

Cursor movement preserves the target column across UP/DOWN (saved
in `target_col` before the move, restored after).  Target column is
the *visual* column, not the byte offset.

### Buffer-full refuse

Every inserting keystroke (RETURN, INS, TAB, printable) checks the
carry returned by `gb_insert` and routes to `@reject` when the
gap buffer is full (`buf_base` at `BUF_FLOOR` and gap exhausted —
see [gap_buffer.md](gap_buffer.md) § gb_ensure_room).  Refuse means:
audible blip via `io_blip`, and `ed_cur_col` / `ed_cur_line` do NOT
advance.  Without the carry check the bookkeeping would drift from
the actual buffer contents, corrupting all subsequent rendering.

The load path uses a separate mechanism: the `_load_overflow` BSS
flag is set on first `gb_insert` failure inside `load_insert`.
Subsequent bytes from `disk_load_seq` are silently dropped;
`ed_load_source` then resets the buffer and returns code 2 ("file
too large") which the REPL surfaces as `;?too big`.

### Tab character

C=+SPACE ($A0) is the tab key.  It inserts a single $A0 byte into
the gap buffer.  On screen, $A0 renders as spaces up to the next
`TAB_WIDTH` column boundary (minimum 1 space).  In the buffer it
remains a literal $A0 byte — one byte per tab, regardless of
visual width.

`TAB_WIDTH` is a **build-time constant** (default 8, settable via
`make TAB_WIDTH=N`).  It is not runtime-mutable.  Once chosen at
build time, every tab on every line renders at that width.

**Visual column tracking.**  `ed_cur_col` tracks the visual
(screen) column, not the byte offset into the line.  A single $A0
byte advances `ed_cur_col` by 1–`TAB_WIDTH` columns depending on
the current position.  Cursor LEFT/RIGHT over a $A0 byte jumps the
full visual width of that tab in one keystroke.

**Smart indent.**  RETURN applies these steps in order:

1. If cursor is at column 0 (beginning of line): insert $0D, done.
   This preserves labels and unindented content below the split.
2. Strip all $A0 tabs adjacent to the cursor (left and right).
3. If the byte now left of the cursor is `:`, strip all leading
   $A0 tabs from the current line (label slides to column 0).
4. Insert $0D + $A0 tab.

Every new line gets a gutter tab (step 4).  Labels lose their
gutter when RETURN follows a colon (step 3).  Splitting a line
in mid-gutter removes the tabs around the split point (step 2)
so neither side gets a double tab.

`enter_editor` seeds one $A0 tab when the buffer is empty so the
first line is ready for an instruction.

**Sequential reader.**  `ed_read_line` and `ed_read_byte` pass $A0
through as-is.  The assembler's whitespace skipper (`asm_skip_ws`)
must treat $A0 as whitespace.

### Long lines and the overflow indicator

Lines in the buffer may exceed 39 visual columns (e.g. from
loaded files or backspace-join).  Interactive input (printable
characters, tabs) is refused when it would push a line past 39
visual columns.  Cursor-right stops at col 39.

**Rendering.**  The renderer clips at the screen edge (col 39).
If a line has content beyond col 38, the renderer writes `>`
(reversed screen code $3E|$80) in col 39 as an overflow
indicator.  The hidden portion is not accessible — there is no
horizontal scrolling.

**Workflow.**  The user sees the `>` indicator and knows the line
is too long.  The fix is manual: insert a newline, shorten an
expression, or split a comment.  This matches the C64 workflow
where screen width is a hard physical constraint.

### Load from SEQ file

`ed_load_source` reads bytes from the SEQ file one at a time via
`disk_load_seq`, feeding them through `gb_insert` directly.  The
file format (CR-terminated text lines) is unchanged.  No
line-width enforcement is applied during loading — lines are
stored as-is regardless of visual width.

The load always succeeds and the file content is preserved
verbatim.  After loading, the REPL scans the buffer and prints
one `;!long LNN` warning per line exceeding 39 visual columns.
The same scan runs after save.  Lines show the `>` overflow
indicator in the editor.

### File I/O

Save and load use disk.s SEQ callbacks, avoiding a direct dependency
on the disk module's internals.

**Save** (`ed_save_source`): `save_read_fn` is a callback passed to
`disk_save_seq`.  It reads sequentially through the gap buffer —
pre-gap first (`buf_base` to `gap_lo`), then post-gap (`gap_hi` to
BUF_END).  Returns A=byte, X=0 for data; A=$FF, X=$FF for EOF
(matches disk.s convention: `cpx #$FF` to detect EOF).
On success, clears `ed_dirty`.

**Load** (`ed_load_source`): resets the buffer (`ed_init`) and the
overflow flag (`_load_overflow`), then `disk_load_seq` calls
`load_insert` as the insert callback (A = byte).  `load_insert`
inserts bytes directly via `gb_insert` with no width enforcement.
After load, the gap is rewound to the start (`gb_cursor_left` loop)
and all cursor state is reset.  On failure, `ed_init` is called again
to leave a clean empty buffer.

### Sequential reader

The assembler needs line-at-a-time access to the source without
knowing about the gap buffer.  Three functions provide this:

- `ed_read_rewind()` — reset `read_ptr` to `buf_base`.
- `ed_read_line(buf)` — copy bytes into `buf` until CR or EOF,
  transparently skipping the gap.  Returns line length or -1 at
  EOF.  Maxlen is hardcoded to 40; lines exceeding 39 raw bytes
  are truncated (the assembler emits a warning on truncation).
- `ed_read_byte()` — single-byte read, skipping the gap.  Returns
  byte or -1 at EOF.

The read pointer is independent of the cursor/gap position.  The
assembler calls `ed_read_rewind` before each pass.

**Partial-result contract** (testing.md § Principle 13).  Both
`ed_read_line` and `ed_read_byte` are partial-result functions —
`read_ptr` (ZP, 2 bytes, owned by editor.s) is the ancillary state.
Each successful call advances `read_ptr` past the consumed bytes;
callers (the two-pass source assembler, `warn_long_lines`) depend
on this advancement to compose repeated reads into a stream walk.

Stopping behaviour:
- `ed_read_byte` — advances `read_ptr` by 1 on each non-EOF call,
  transparently stepping over the gap when `read_ptr` lands inside
  it.  Returns $FFFF (A=X=$FF) at EOF without further advance.
- `ed_read_line` — scans from `read_ptr` until CR or EOF,
  transparently skipping the gap.  On a CR-terminated line, the
  advance is exactly (content_length + 1).  On the final line with
  no trailing CR, the advance may continue past the content
  (through the gap) to BUF_END — the delta is then
  implementation-dependent, and any subsequent call returns EOF.
  **EOF is idempotent:** once a call has returned EOF, further
  calls keep returning EOF and leave `read_ptr` stable.  (The
  *first* EOF call may still advance if content ended just before
  the gap — it has to cross the gap to reach BUF_END before
  reporting EOF.  What callers can rely on is that `read_ptr` is
  stable across repeat EOF calls.)

Position pinning:
- `ed_read_byte`'s per-call advancement is transitively witnessed
  by `tests/integration/test_editor.py`'s `read_back` helper, which
  walks the entire gap buffer byte by byte and asserts the
  reconstructed content — any regression that left `read_ptr` stuck
  or skipping bytes would corrupt every `TestGapBufferInsert` case.
- `ed_read_line`'s advancement is pinned directly by
  `TestEdReadLine::test_advances_read_ptr_on_success` (exact delta
  for CR-terminated lines), `test_empty_line_advances_by_one`
  (empty-line edge case), `test_last_line_no_cr_ends_at_buf_end`
  (no-CR last line crosses to BUF_END), and
  `test_eof_calls_are_idempotent` (post-EOF stability).

## Caveats

- Lines are separated by $0D (CR) internally; CR is stripped by
  `ed_read_line`.
- The gap buffer shares the workspace ($0800–$CFFF) with assembled
  output.  The `i` command shows remaining space.
- Screen save/restore copies 1000 bytes (screen RAM only, not color
  RAM).  Color RAM is restored by `restore_colors` on REPL return.
  The save/restore uses banked RAM under KERNAL ($F4F2–$F8D9).
  `enter_editor` copies SCREEN → REPL_SCREEN: this is a pure write
  to the under-KERNAL region, which passes through to RAM
  regardless of `$01` bit 1, so no banking is required.
  `leave_editor` reads REPL_SCREEN back, so it must `kernal_bank_out`
  for the duration of the copy.
- `gb_ensure_room` grows by 256 bytes at a time.  The block copy to
  relocate pre-gap text is the most expensive operation.
- `ed_render_line` does PETSCII-to-screencode conversion inline.
  Two ranges are handled: lowercase ($41–$5A) and uppercase ($C1–$DA).
- Lines may exceed 39 visual columns.  The renderer clips at
  col 39 and shows `>` (reversed) as an overflow indicator.
  The hidden portion is not accessible (no horizontal scroll).
  `ed_cur_col` has no upper bound enforced by the editor.
- $A0 (tab) is one byte in the buffer but 1–`TAB_WIDTH` columns on
  screen.  Visual column and byte offset diverge on lines with
  tabs.  `TAB_WIDTH` is a build-time constant (default 8).
- `ed_read_line` truncates at 40 raw bytes.  The assembler
  emits a line warning when truncation occurs.  Long lines in
  loaded SEQ files are preserved verbatim (no splitting); the
  REPL warns about the count of lines exceeding 39 visual cols.
- `BUF_END` is the constant `__CODE_RUN__` (floating), not a variable.
  This saves 2 ZP bytes vs the C implementation.
- `save_ptr` and `read_ptr` overlap in ZP since they are never active
  concurrently.
- `buf_base` is exported (`.exportzp`) so asm_src.s can read it for
  the `workend` symbol.  `update_workend` redefines `workend` in the
  symbol table whenever `buf_base` changes (ed_init, gb_ensure_room).
