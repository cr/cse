# editor.s — Gap-Buffer Source Editor

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/editor.s`](../../src/editor.s) | implementation (6502 assembly) |
| [`tests/test_editor.py`](../../tests/test_editor.py) | test contract |

## Interface

All public functions use register/ZP calling convention (single arg
in A or A/X; multi-arg via named ZP variables).

- `enter_editor()` — save REPL screen, switch to editor mode
- `leave_editor()` — restore REPL screen, return to REPL
- `ed_handle_key(ch)` — process one keystroke (A = PETSCII key)
- `ed_ensure_init()` — allocate gap buffer if not yet done
- `ed_new()` — clear source buffer (reset gap buffer, clear filename)
- `ed_save_source(name)` — save source as SEQ file; A=0 on success
- `ed_load_source(name)` — load SEQ file into buffer; A=0 on success
- `ed_read_rewind()` — reset sequential reader to start of source
- `ed_read_line(buf, maxlen)` — read next line into buf; A/X = length or $FFFF at EOF
- `ed_read_byte()` — read next byte from source; A/X = byte or $FFFF at EOF
- `ed_insert_string(text)` — programmatic text insertion at cursor

**Tab width:** `TAB_WIDTH` is a **build-time constant**
(`-DTAB_WIDTH=N`, default 8).  It is not runtime-mutable; there is
no `T` REPL command, no `tab_width` BSS variable.  `TAB_WIDTH`
must be a value in 1..32 at build time.  The default of 8 matches
every C64-era assembler toolchain (Turbo Assembler, MasterSeka,
Relaunch64, ca65 `.lst` output) and makes `col mod TAB_WIDTH`
collapse to `and #$07` on the 6502.

Rationale: `TAB_WIDTH` interacts with the 39-col hard line cap
(below) — changing it at runtime would invalidate every line's
visual width, force a full re-render, and may turn
previously-valid lines into "too long" errors.  Baking it in
eliminates a whole class of bugs at the cost of ~30 bytes saved
(dropped `col_mod_tw` loop + dropped `T` command).

**Statistics:** `ed_save_bytes`, `ed_save_lines` (uint16, BSS) —
counts from last file operation.  `ed_total_lines` (uint16, BSS,
exported) — current line count, used by the REPL's `i` command.

**Depends on:** disk (SEQ callbacks), screen, cse_io, meminfo
(`cse_end` for status bar)

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

`buf_end` is the constant `$D000` — not a variable.

`save_ptr` and `read_ptr` are never active concurrently (save runs
to completion before any read), so they share the same ZP location.
`ed_tmp` and `ed_scr` must be in ZP because they are used with
indirect-indexed addressing (`lda (ed_tmp),y`).
Total: 14 ZP bytes.

### BSS variables

| Name | Size | Role |
|------|------|------|
| `ed_cur_line` | 2 | cursor line (0-based) |
| `ed_cur_col` | 1 | cursor visual column (0-based) |
| `ed_top_line` | 2 | line number at screen row 0 |
| `ed_total_lines` | 2 | total line count in buffer |
| `ed_dirty` | 1 | buffer modified flag |
| `ed_save_bytes` | 2 | bytes from last file op |
| `ed_save_lines` | 2 | lines from last file op |
| `ed_load_split` | 1 | count of lines split on last load (0 if none) |
| `ed_load_split_lines` | 16 | first 8 affected editor line numbers as 16-bit values (`lo, hi, lo, hi, ...`); valid entries = `min(ed_load_split, 8)` |
| `_load_vcol` | 1 | running visual col of the current line during `ed_load_source` — read only by the load_insert callback |
| `_load_line` | 2 | current editor line number during `ed_load_source` — read only by the load_insert callback |
| `save_phase` | 1 | save callback state (0=pre-gap, 1=post-gap) |
| `repl_cur_x` | 1 | saved REPL cursor X |
| `repl_cur_y` | 1 | saved REPL cursor Y |
| `ws_buf` | 39 | Auto-indent whitespace buffer |
| `_src_top` | 2 | Buffer upper bound (for REPL `i` command) |
| `_src_bot` | 2 | Buffer lower bound (for REPL `i` command) |

### Internal functions

Internal functions use register/ZP arguments directly — no parameter stack.

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `ed_init` | — | — | reset all state |
| `gb_ensure_room` | — | C=0 fail, C=1 ok | grow buffer if gap exhausted |
| `gb_insert` | A = byte | — | insert at gap_lo (no cap check; callers at the five text-entry points apply the 39-col cap inline) |
| `gb_backspace` | — | — | delete before gap_lo |
| `gb_cursor_right` | — | — | move gap right |
| `gb_cursor_left` | — | — | move gap left |
| `gb_home` | — | — | move to start of line |
| `skip_one_line` | ptr in A/X | result in A/X | advance past one line |
| `prev_line_start` | ptr in A/X | result in A/X | retreat to previous line |
| `visual_col` | — | A = column | recompute cursor column (0..39) |
| `line_vwidth` | ed_scr = line-start ptr | A = width | total visual width of the line starting at ed_scr, stopping at CR/EOF; returns 0..254 normal or `$FF` overflow sentinel.  Used by backspace-join overflow detection. |
| `cursor_line_vwidth` | — | A = width | walks back from `gap_lo` to the start of the cursor's line (without moving the gap), then calls `line_vwidth` from there.  Used by the printable/tab insert paths to enforce the 39-col cap against the line's total width, not just `ed_cur_col`. |
| `char_width` | A = byte, X = vcol | A = width | tab-aware; uses `TAB_WIDTH` |
| `advance_to_vcol` | A = target col | — | cursor right toward target column, stopping at EOL or when next char would overshoot |
| `copy_leading_ws` | — | Y = count | auto-indent helper; copies leading $20/$A0 bytes into `ws_buf` |
| `load_insert` | A = byte | — | ed_load_source callback: inserts with 39-col cap tracking, forces CR on overflow, records splits in `ed_load_split`/`ed_load_split_lines` |

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
$D000 ─┴─ BUF_END (exclusive, fixed constant)
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
  `buf_end`.  Transparently skips the gap.  Converts PETSCII to
  screen codes: $41–$5A → $01–$1A (lowercase), $C1–$DA → $41–$5A
  (uppercase).  Expands $A0 (tab) to spaces up to the next
  `TAB_WIDTH` column boundary.  Pads the rest of the row with
  spaces.
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
1. Save REPL cursor position (`io_cx`, `io_cy`)
2. Save REPL screen RAM (1000 bytes) to `repl_screen`
3. Initialize gap buffer if first entry (`ed_init`)
4. Clear editor area (rows 0–21) with spaces
5. Copy 2 REPL lines above the prompt to rows 23–24 (context strip)
6. Full render (`ed_render`)
7. Restore editor cursor position, set `state = ST_EDIT`

**`leave_editor`:**
1. Restore REPL screen RAM from `repl_screen`
2. Restore REPL cursor position
3. Set `state = ST_REPL`

This is a full screen swap — no shared display area.  The editor
owns all 25 rows while active.  The REPL gets its screen back
verbatim on return.

### Keystroke dispatch

`ed_handle_key` processes one keystroke per call.  All cases end
with the `reposition` label which syncs `io_cx`/`io_cy` to the
editor cursor.

| Key | Action | Redraw |
|-----|--------|--------|
| C=+SPACE | Insert $A0 (tab byte), advance `ed_cur_col` to next `TAB_WIDTH` boundary.  Refused if the line's total visual width plus the tab's width at end-of-line would exceed 39 (`cursor_line_vwidth() + char_width($A0, line_vwidth) > 39`). | current row only + status |
| LEFT | `gb_cursor_left`, decrement `ed_cur_col`; if byte crossed is $A0, `ed_cur_col` snaps back to previous tab-stop-aligned column | status pos only |
| RIGHT | `gb_cursor_right`, increment `ed_cur_col`; if byte crossed is $A0, `ed_cur_col` snaps forward to next tab-stop-aligned column (stops at CR/EOF) | status pos only |
| UP | `ed_cursor_up`: home → left (past CR) → home → advance to target col | scroll down if above viewport, else status pos |
| DOWN | `ed_cursor_down`: advance past CR → advance to target col | scroll up if below viewport, else status pos |
| HOME | `gb_home`: slide gap left to start of current line | status pos only |
| DEL | `gb_backspace`, re-render from current row to bottom.  At col 0 of line > 0: join with previous line — if the combined width would exceed 39 a forced CR is inserted at the last safe col (no blip, operation succeeds; see "Backspace-join and the 39-col cap" below).  At col 0 of line 0: refused (blip, left wall). | rows from cursor to bottom + status |
| RETURN | Insert $0D, advance `ed_cur_line`. Auto-indent: copy leading whitespace (spaces and $A0 tabs) from current line to new line.  Auto-indent is truncated if it would exceed 38 cols (leaving at least one col for the first typable char). | rows from previous line to bottom + status |
| printable | insert char at gap, increment `ed_cur_col`.  Refused if the cursor's line is at the cap (`cursor_line_vwidth() ≥ 39`) — checks the line's total visual width, not just `ed_cur_col`, so an insert in the middle of a full line is also refused. | current row only + status |

Cursor movement preserves the target column across UP/DOWN (saved
in `target_col` before the move, restored after).  Target column is
the *visual* column, not the byte offset.

### Tab character

C=+SPACE ($A0) is the tab key.  It inserts a single $A0 byte into
the gap buffer.  On screen, $A0 renders as spaces up to the next
`TAB_WIDTH` column boundary (minimum 1 space).  In the buffer it
remains a literal $A0 byte — one byte per tab, regardless of
visual width.

`TAB_WIDTH` is a **build-time constant** (default 8, settable via
`make TAB_WIDTH=N`).  It is not runtime-mutable.  Once chosen at
build time, every tab on every line renders at that width, and
the 39-col hard cap (below) is calculated against it.

**Visual column tracking.**  `ed_cur_col` tracks the visual
(screen) column, not the byte offset into the line.  A single $A0
byte advances `ed_cur_col` by 1–`TAB_WIDTH` columns depending on
the current position.  Cursor LEFT/RIGHT over a $A0 byte jumps the
full visual width of that tab in one keystroke.

**Auto-indent.**  RETURN copies leading whitespace from the current
line to the new line.  Both $20 (space) and $A0 (tab) bytes are
copied verbatim.  The copy is **truncated** if continuing it would
leave the new line with no room for the first typable char:
auto-indent stops at the longest prefix of the parent line's
leading whitespace that leaves the new `ed_cur_col` ≤ 38.  (Cap is
39 content cols; auto-indent leaves at least one col for the user.)

**Sequential reader.**  `ed_read_line` and `ed_read_byte` pass $A0
through as-is.  The assembler's whitespace skipper (`asm_skip_ws`)
must treat $A0 as whitespace.

### The 39-column hard cap

**Terminology.**  Screen columns are 0-indexed.  Content may fill
visual cols **0..38** inclusive → a line holds up to **39 chars**
of content.  Col **39** is the "cursor rest" position where the
cursor sits after a full line; no content goes there.  The
`ed_cur_col` BSS variable is this 0-indexed column; its valid
range is **0..39**.

Every line in the buffer is guaranteed to fit in ≤ 39 content
chars (equivalently, `ed_cur_col` at end-of-line ≤ 39).  This is
a **hard invariant**: rendering, cursor motion, status-bar position
display, and all scroll/row math assume it.  The editor enforces
the cap at every point where text can enter the buffer:

1. **Printable character insert** — refused if the **cursor's
   line** is already at the cap (`cursor_line_vwidth() ≥ 39`).
   The check uses the line's *total* visual width, not just
   `ed_cur_col`, so an insert in the middle of a full line is
   refused even though the cursor is not yet at col 39.
2. **Tab insert** — refused if the line's total visual width
   plus the tab's width *at end of line* would exceed 39, i.e.
   `line_vwidth + char_width($A0, line_vwidth) > 39`.  This is a
   conservative check: it treats the tab as if appended at line
   end (worst case), and may *under-refuse* tab inserts in the
   middle of a tab-mixed line where realignment of trailing tabs
   could push the line over the cap.  We accept that edge case
   as the simplicity trade-off — `TAB_WIDTH=8` makes it rare in
   practice.
3. **Auto-indent on RETURN** — the copied leading whitespace is
   **truncated** to a prefix that leaves the new line's
   `ed_cur_col` ≤ 38, so the user can immediately type at least
   one char.
4. **Backspace-join** at col 0 — see below.
5. **Load from SEQ file** — see below.

These are the **only** entry points for text.  Once enforced at
entry, the invariant is maintained forever without further checks.

### Backspace-join and the 39-col cap

DEL at col 0 of line N > 0 joins line N with line N-1: delete
the CR at end of line N-1, concatenating the two.  If
`line_vwidth(N-1) + line_vwidth(N) > 39`, the join would
otherwise violate the cap.

**Policy: forced newline.**  The join always proceeds — the
cursor does not hear the reject blip, because this is not a
refused edit, it's a successful one that ends up in an
unexpected shape:

1. `gb_backspace` deletes the CR between N-1 and N.
2. The handler measures the combined visual width.
3. If ≤ 39, the result is a single line; the cursor is
   restored to the join point.
4. If ≥ 40, the handler advances the cursor to the largest
   col ≤ 39 on the combined line *without breaking a tab*
   (a tab whose expansion would straddle the boundary is
   left on the post-CR side), then inserts a forced CR
   there.  Two lines remain but the split point has moved.
   No data is lost.

Net effect: the user sees their backspace "work" (one CR
disappeared where they pressed DEL) but a **different** CR
may have appeared at a col such that the first sub-line's
width stays ≤ 39.  The cursor lands at col 0 of whatever
sub-line now contains the first byte of the original line N.
No blip — the operation is not a refusal.

Rationale: flat refusal was tried briefly and rejected.  It
felt wrong in practice: the user issued a valid edit (the
combined text is perfectly legal, just doesn't fit on one
line) and the editor doing nothing is surprising.  Forced
newline preserves every byte in order, which is the principle
that matters.  The split boundary is a cosmetic inconvenience;
data loss would be worse.  The file-load path (see below) uses
the same policy for the same reason.

### Load from SEQ file

`ed_load_source` reads bytes from the SEQ file one at a time via
`disk_load_seq`, feeding them through `gb_insert` directly.  The
file format (CR-terminated text lines) is unchanged.

**Line-width enforcement.**  A small inline check in the load
callback tracks the running visual width of the current line
(`ed_cur_col`).  Before each insert, it calls a character-width
computation (`char_width` for tabs, else 1) to determine the
expansion of the incoming byte.  If inserting the next byte
would push the visual width to 40 or beyond (i.e., beyond the
cursor-rest col 39), the loader **forces a CR at the cap
boundary**, then inserts the byte as the first char of the next
line.  The user's logical line N in the file becomes two editor
lines N and N+1, each with visual width ≤ 39.  Tabs are never
split — if a tab would straddle the cap, the forced CR goes
*before* the tab and the tab becomes the first char of the new
line.

**Warning on split.**  Each forced split increments a counter.
When the load finishes, if any splits happened, the REPL prints
a warning identifying the affected editor line numbers:

    ; loaded "file,s" — 312 bytes, 47 lines
    ;   ! 3 lines split on load at editor lines 14, 22, 39

The user can scroll to each flagged line, see the forced CR, and
manually re-format (usually by joining with RETURN-to-indent or
by rearranging tokens).  The load itself always succeeds — the
file is preserved in the buffer, just reshaped.

**Edge cases:**

- A single byte wider than 39 cols at col 0 (impossible for a
  printable char, but a tab at col 0 with `TAB_WIDTH > 39` would
  hit it).  Not reachable under the documented `TAB_WIDTH` range
  1..32.
- A line of exactly 39 cols followed by a CR: no split, no
  warning (fits the cap exactly; cursor at col 39 at end of line).
- A line of 40+ cols: exactly one split per overflow; a 120-col
  line becomes 4 editor lines (roughly 39 + 39 + 39 + 3) and
  produces one warning for the logical file line.
- Trailing $A0 tabs at the end of a line: counted toward the
  visual width normally; if the tab's expansion would push past
  col 39, the split CR goes before the tab.

**`ed_load_split` BSS counter** (1 byte) holds the number of
splits from the last load.  **`ed_load_split_lines`** (16 bytes)
holds the first 8 affected editor line numbers as 16-bit values
(`lo, hi, lo, hi, ...`); only the first `min(ed_load_split, 8)`
entries are valid.  The REPL's `cmd_load` / `print_load_split_warning`
read both after `ed_load_source` returns and print the warning.
Both counters are reset at the start of each load.

Implementation: the running load state lives in two BSS-local
variables — `_load_vcol` (1 byte, running visual col of the
current line) and `_load_line` (2 bytes, current editor line
number) — read only by the `load_insert` callback.  They are
zeroed by `ed_load_source` before calling `disk_load_seq`.

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
load-split state (`ed_load_split`, `_load_vcol`, `_load_line`), then
`disk_load_seq` calls `load_insert` as the insert callback (A = byte).
`load_insert` is a cap-aware wrapper over `gb_insert`: it tracks the
running visual width of the current line and forces a CR on overflow
(see "The 39-column hard cap" and "Load from SEQ file" above).
After load, the gap is rewound to the start (`gb_cursor_left` loop)
and all cursor state is reset.  On failure, `ed_init` is called again
to leave a clean empty buffer.

### Sequential reader

The assembler needs line-at-a-time access to the source without
knowing about the gap buffer.  Three functions provide this:

- `ed_read_rewind()` — reset `read_ptr` to `buf_base`.
- `ed_read_line(buf, maxlen)` — copy bytes into `buf` until CR or
  EOF, transparently skipping the gap.  Returns line length or -1
  at EOF.  Long lines are silently truncated to `maxlen - 1`.
- `ed_read_byte()` — single-byte read, skipping the gap.  Returns
  byte or -1 at EOF.

The read pointer is independent of the cursor/gap position.  The
assembler calls `ed_read_rewind` before each pass.

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
- **39-content-column hard cap.**  Content may fill visual cols
  0..38 inclusive (39 chars max); col 39 is the cursor-rest
  position, matching the REPL convention.  `ed_cur_col` ranges
  0..39.  Enforced at every text-entry point (insert, tab,
  auto-indent, backspace-join, load).  The renderer, cursor
  math, and status bar all assume it.
- $A0 (tab) is one byte in the buffer but 1–`TAB_WIDTH` columns on
  screen.  Visual column and byte offset diverge on lines with
  tabs.  `TAB_WIDTH` is a build-time constant (default 8).
- Long lines in a loaded SEQ file are **split** at the cap
  boundary.  The load always succeeds; the REPL prints a warning
  with the affected editor line numbers so the user can fix them
  manually.  Saving back writes the split version — the original
  file structure is **not** preserved across load→save.  Users
  wanting lossless round-trip for long-line source should
  pre-format in their cross-dev tool.
- `buf_end` is the constant $D000, not a variable.  This saves 2 ZP
  bytes vs the C implementation.
- `save_ptr` and `read_ptr` overlap in ZP since they are never active
  concurrently.
- `buf_base` is exported (`.exportzp`) so asm_src.s can read it for
  the `workend` symbol.  `update_workend` redefines `workend` in the
  symbol table whenever `buf_base` changes (ed_init, gb_ensure_room).
