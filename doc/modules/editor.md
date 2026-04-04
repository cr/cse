# editor.s — Gap-Buffer Source Editor

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/editor.s`](../../src/editor.s) | implementation (6502 assembly) |
| [`tests/test_editor.py`](../../tests/test_editor.py) | test contract |

## Interface

All public functions use `__fastcall__` convention (single arg in
A or A/X; multi-arg via parameter stack with `pushax`).

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

**State:** `tab_width` (uint8, BSS, default 8) — tab stop interval
in columns.  Set by the REPL's `T` command (uppercase).  Affects
rendering of $A0 (tab) bytes only; changing it does not modify
buffer contents.

**Statistics:** `ed_save_bytes`, `ed_save_lines` (uint16, BSS) —
counts from last file operation.

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

`buf_end` is the constant `$C800` — not a variable.

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
| `tab_width` | 1 | tab stop interval (default 8) |
| `save_phase` | 1 | save callback state (0=pre-gap, 1=post-gap) |
| `repl_cur_x` | 1 | saved REPL cursor X |
| `repl_cur_y` | 1 | saved REPL cursor Y |

### Internal functions

Internal functions use register/ZP arguments directly — no parameter stack.

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `ed_init` | — | — | reset all state |
| `gb_ensure_room` | — | C=0 fail, C=1 ok | grow buffer if gap exhausted |
| `gb_insert` | A = byte | — | insert at gap_lo |
| `gb_backspace` | — | — | delete before gap_lo |
| `gb_cursor_right` | — | — | move gap right |
| `gb_cursor_left` | — | — | move gap left |
| `gb_home` | — | — | move to start of line |
| `skip_one_line` | ptr in A/X | result in A/X | advance past one line |
| `prev_line_start` | ptr in A/X | result in A/X | retreat to previous line |
| `visual_col` | — | A = column | recompute from line start |
| `char_width` | A = byte, X = vcol | A = width | tab-aware |
| `advance_to_vcol` | A = target col | — | cursor right to column |
| `copy_leading_ws` | — | A = count | auto-indent helper |

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
       ├─ symbol table heap (grows up from cse_end)
       │
       ├─ ··· free ···
       │
       ├─ buf_base (grows down as buffer needs space)
       │
$C800 ─┴─ BUF_END (exclusive, fixed constant)
```

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
  `tab_width` column boundary.  Pads the rest of the row with
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
| C=+SPACE | Insert $A0 (tab byte), advance `ed_cur_col` to next `tab_width` boundary | current row only + status |
| LEFT | `gb_cursor_left`, decrement `ed_cur_col`; if byte crossed is $A0, `ed_cur_col` snaps back to previous tab-stop-aligned column | status pos only |
| RIGHT | `gb_cursor_right`, increment `ed_cur_col`; if byte crossed is $A0, `ed_cur_col` snaps forward to next tab-stop-aligned column (stops at CR/EOF) | status pos only |
| UP | `ed_cursor_up`: home → left (past CR) → home → advance to target col | scroll down if above viewport, else status pos |
| DOWN | `ed_cursor_down`: advance past CR → advance to target col | scroll up if below viewport, else status pos |
| HOME | `gb_home`: slide gap left to start of current line | status pos only |
| DEL | `gb_backspace`, re-render from current row to bottom. At col 0: join with previous line, adjust `ed_cur_line`/`ed_top_line`, re-render | rows from cursor to bottom + status |
| RETURN | Insert $0D, advance `ed_cur_line`. Auto-indent: copy leading whitespace (spaces and $A0 tabs) from current line to new line. Scroll if needed | rows from previous line to bottom + status |
| printable | insert char at gap, increment `ed_cur_col` (max col 38) | current row only + status |

Cursor movement preserves the target column across UP/DOWN (saved
in `target_col` before the move, restored after).  Target column is
the *visual* column, not the byte offset.

### Tab character

C=+SPACE ($A0) is the tab key.  It inserts a single $A0 byte into
the gap buffer.  On screen, $A0 renders as spaces up to the next
`tab_width` column boundary (minimum 1 space).  In the buffer it
remains a literal $A0 byte — one byte per tab, regardless of
visual width.

`tab_width` controls the visual width of tabs.  Changing
`tab_width` (via the REPL's `T` command) does not modify the buffer
— it only changes how $A0 bytes are rendered.  This is the same
model as hard tabs in modern editors.

`tab_width = 0` disables tab rendering; $A0 is displayed as a
single space.

**Visual column tracking.**  `ed_cur_col` tracks the visual
(screen) column, not the byte offset into the line.  A single $A0
byte advances `ed_cur_col` by 1–`tab_width` columns depending on
the current position.  Cursor LEFT/RIGHT over a $A0 byte jumps the
full visual width of that tab in one keystroke.

**Auto-indent.**  RETURN copies leading whitespace from the current
line to the new line.  Both $20 (space) and $A0 (tab) bytes are
copied verbatim.

**Sequential reader.**  `ed_read_line` and `ed_read_byte` pass $A0
through as-is.  The assembler's whitespace skipper (`au_skip_ws`)
must treat $A0 as whitespace.

### File I/O

Save and load use disk.s SEQ callbacks, avoiding a direct dependency
on the disk module's internals.

**Save** (`ed_save_source`): `save_read_fn` is a callback passed to
`disk_save_seq`.  It reads sequentially through the gap buffer —
pre-gap first (`buf_base` to `gap_lo`), then post-gap (`gap_hi` to
BUF_END).  Returns A=byte, X=0 for data; A=$FF, X=$FF for EOF
(matches disk.s convention: `cpx #$FF` to detect EOF).
On success, clears `ed_dirty`.

**Load** (`ed_load_source`): resets the buffer (`ed_init`), then
`disk_load_seq` calls `gb_insert` directly as the insert callback
(A = byte).  After load, the gap is rewound to the start
(`gb_cursor_left` loop) and all state is reset.  On failure,
`ed_init` is called again to leave a clean empty buffer.

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
- The gap buffer shares the $0800–$C7FF region with assembled output
  and the symbol table heap.  The `i` command shows remaining space.
- Screen save/restore copies 1000 bytes (screen RAM only, not color
  RAM).  Color RAM is restored by `restore_colors` on REPL return.
  The save/restore uses banked RAM under KERNAL ($F818–$FBFF) via
  `kernal_bank_out`/`kernal_bank_in`.
- `gb_ensure_room` grows by 256 bytes at a time.  The block copy to
  relocate pre-gap text is the most expensive operation.
- `ed_render_line` does PETSCII-to-screencode conversion inline.
  Two ranges are handled: lowercase ($41–$5A) and uppercase ($C1–$DA).
- Maximum column is 38 (SCREEN_WIDTH - 1).  Column 39 is reserved
  for the cursor, matching the REPL convention.
- $A0 (tab) is one byte in the buffer but 1–`tab_width` columns on
  screen.  Visual column and byte offset diverge on lines with tabs.
- `buf_end` is the constant $C800, not a variable.  This saves 2 ZP
  bytes vs the C implementation.
- `save_ptr` and `read_ptr` overlap in ZP since they are never active
  concurrently.
- `buf_base` is exported (`.exportzp`) so asm_src.s can read it for
  the `workend` symbol.  `update_workend` redefines `workend` in the
  symbol table whenever `buf_base` changes (ed_init, gb_ensure_room).
