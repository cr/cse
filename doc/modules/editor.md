# editor.s — Keystroke Dispatch + Screen Rendering + Disk I/O (L4)

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/editor.s`](../../src/editor.s) | implementation |
| [`tests/integration/test_editor.py`](../../tests/integration/test_editor.py) | test contract |
| [`tests/integration/test_m65_source_editor.py`](../../tests/integration/test_m65_source_editor.py) | test contract — the editor on the m65 PRG in each text mode (P2 T10, § On m65) |

## Purpose

The full-screen source editor.  The gap buffer it edits and the
sequential reader the assembler walks belong to
[gap_buffer.md](gap_buffer.md) (L3, bundle-testable without screen
or KERNAL); this module (L4) keeps everything that needs screen RAM,
the KERNAL or the disk: keystroke dispatch, the rendering pipeline,
scroll drivers, smart indent, `enter_editor` / `leave_editor`, and
SEQ save/load.  The layering is compile-time: editor.s imports from
gap_buffer.s, never the reverse.

## Interface

All entry points take their arguments in A or A/X; state lives in
named ZP / BSS variables.  The clobber lists include what a callee
pulls in: an insert that grows the gap buffer clobbers `read_ptr`
and symtab ZP (via `update_workend` → `sym_define`, see
[gap_buffer.md § Interface](gap_buffer.md#interface)), written
"growth" below.

### enter_editor
**In:** none (`CUR_COL` / `CUR_ROW` = the REPL cursor)
**Out:** REPL screen and cursor saved, editor drawn, `state = ST_EDIT`.
Editor cursor and scroll position are the ones left at the last
`leave_editor` (BSS, not reset).  Steps in § Mode switching.
**Clobbers:** A, X, Y, `ed_tmp`, `ed_scr`, `read_ptr` (= save_ptr);
growth on the empty-buffer seed.

### leave_editor
**In:** none
**Out:** REPL screen RAM and cursor restored as `enter_editor` saved
them, `state = ST_REPL`.
**Clobbers:** A, X, Y, `ed_scr`, `read_ptr` (= save_ptr).

### ed_handle_key
**In:** A = PETSCII key code (any key but RUN/STOP, which the main
loop handles)
**Out:** the key's edit or move applied (§ Keystroke dispatch), the
affected rows and status bar redrawn, KERNAL cursor synced to the
editor cursor.  A refused key blips (`io_blip`) and changes nothing.
**Clobbers:** A, X, Y, `ed_tmp`, `ed_scr`, `read_ptr`; growth.

### ed_new
**In:** none
**Out:** empty buffer (`gb_init`), cursor and scroll state zeroed,
`workend` republished, `ed_dirty = 0`, project name cleared
(`cur_project_name[0] = 0`).
**Clobbers:** A, X, Y, symtab ZP.

### ed_save_source
**In:** A/X = filename pointer (NUL-terminated PETSCII)
**Out:** success — A = 0, X = 0, Z = 1; `ed_dirty = 0`;
`ed_save_bytes` / `ed_save_lines` = the counts written.  Disk error
— A = 1, X = 0, Z = 0; `ed_dirty` and the buffer unchanged.  Writes
the pre-gap then the post-gap bytes as a SEQ file through
`disk_save_seq` (`@:` replace, see [disk.md](disk.md)).  "Disk
error" means the OPEN failed or the drive refused the file (its
status code is not `0x`: write protect, disk full).
**Clobbers:** A, X, Y, `disk_ptr`, `read_ptr` (= save_ptr), and what
`disk_save_seq` clobbers.

### ed_load_source
**In:** A/X = filename pointer (NUL-terminated PETSCII)
**Out:** A = 0 success: buffer holds the file verbatim, cursor and
scroll at line 1 col 0, `ed_dirty = 0`, `ed_save_bytes` /
`ed_save_lines` = the counts read.  A = 1: disk error or empty file.
A = 2: the file does not fit the buffer.  On 1 and 2 the buffer is
left empty (`ed_init`).  X = 0 and Z set from A on every path (the
REPL's `l` branches on Z).
**Clobbers:** A, X, Y, `disk_ptr`, `ed_tmp`, `ed_scr`, `read_ptr`,
symtab ZP, and what `disk_load_seq` clobbers.

### ed_save_bytes / ed_save_lines
uint16 BSS, exported: byte and line counts of the last successful
SEQ save or load (lines = CRs + 1), printed by the REPL's
`print_seq_stats` as `Nl Mb`.  repl.s's `i` command also writes them
(line count and allocated buffer size) to reuse that printer.

`ed_init` (full reset: `gb_init`, cursor/scroll zeroed,
`update_workend`) is internal; `ed_new` and `ed_load_source` call
it.  The gap-buffer entry points the REPL, `main.s` and the
assembler use (`ed_ensure_init`, `ed_read_*`, `ed_total_lines`,
`src_top` / `src_bot`, `define_ws_syms`) are gap_buffer.s exports
— see [gap_buffer.md](gap_buffer.md).

**Tab width:** `TAB_WIDTH` is a **build-time constant**
(`make TAB_WIDTH=N`, default 8; [build_system.md](../build_system.md)).
It must be a power of two in 1..32 — 1, 2, 4, 8, 16 or 32 — because
`col mod TAB_WIDTH` is computed as `col and TAB_WIDTH-1`; any other
value stops the build with an `.error`.  There is no runtime tab
setting.

**Depends on:** gap_buffer (gb_init, ed_ensure_init, gb_insert,
gb_backspace, gb_cursor_left, gb_cursor_right, gb_home,
check_buf_end, ed_total_lines, update_workend), cse_io (io_sync,
io_blip, scr_lo, scr_hi), mem (kernal_bank_out, kernal_bank_in),
disk (disk_save_seq, disk_load_seq, disk_seq_bytes, disk_seq_lines),
screen (m65: screen_save, screen_restore),
zp (cur_project_name, state, ed_dirty, disk_ptr and the editor ZP
below).  Linker-provided `__CODE_RUN__` (= `BUF_END`).  editor.s
also imports gb_ensure_room, ed_insert_string, ed_read_rewind,
ed_read_byte, ed_read_line, src_top and src_bot without using them
(dead imports, [TODO.md § Code bugs](../TODO.md)).

### Zero-page variables

Allocated in zp.s ([zp.md](zp.md)); `gap_lo`, `gap_hi`, `buf_base`
and `read_ptr` are the gap buffer's ([gap_buffer.md § Buffer
layout](gap_buffer.md#buffer-layout)).

| Name | Size | Role here |
|------|------|-----------|
| `ed_top_ptr` | 2 | buffer position of the first visible line (reset by `gb_init`, moved by `gb_ensure_room`) |
| `ed_tmp` | 2 | scratch pointer (indirect addressing) |
| `ed_scr` | 2 | buffer walk / screen pointer for rendering (indirect addressing) |
| `save_ptr` | (2) | alias of `read_ptr`: `save_read_fn`'s position, the scroll copies' source row |
| `ed_dirty` | 1 | buffer modified (cross-module flag: written by gap_buffer.s on every edit and by editor.s; read by repl.s's unsaved-changes gates) |
| `state` | 1 | `ST_EDIT` / `ST_REPL`, set by `enter_editor` / `leave_editor` |
| `cur_project_name` | 17 | shown in the status bar; cleared by `ed_new`; on m65 zp.s's BSS, not the base page |

### BSS variables

| Name | Size | Role |
|------|------|------|
| `ed_cur_line` | 2 | cursor line (0-based) |
| `ed_cur_col` | 1 | cursor visual column (0-based, ≤ 39) |
| `ed_top_line` | 2 | line number at screen row 0 |
| `ed_save_bytes` | 2 | bytes from last file op |
| `ed_save_lines` | 2 | lines from last file op |
| `_load_overflow` | 1 | sticky flag: set if `gb_insert` failed during `ed_load_source` |
| `save_phase` | 1 | save callback state (0 = pre-gap, 1 = post-gap) |
| `repl_cur_x` | 1 | saved REPL cursor column |
| `repl_cur_y` | 1 | saved REPL cursor row |

Fifteen proc-local scratch bytes (`ed_render_line`, `div10`,
`ed_render_status`, `ed_render_range`, `visual_col`, `line_vwidth`,
`advance_to_vcol`, `ed_cursor_up` / `ed_cursor_down`, `ed_handle_key`)
are BSS too, declared inside their `.proc`; CODE is never written
(memory_design.md § Design Principles).

### Internal functions

| Function | Args | Returns | Notes |
|----------|------|---------|-------|
| `ed_init` | — | — | full reset (see § Interface) |
| `ed_render_line` | X = row, `ed_scr` = line start | A = 1 more text / 0 EOF; `ed_scr` past the CR | § Rendering |
| `ed_render_range` | X = from, Y = to (exclusive) | — | walks from `ed_top_ptr` |
| `ed_render` / `ed_render_rows` | — / X, Y | — | all 22 rows / a range, then the full status bar |
| `ed_scroll_up` / `ed_scroll_down` | — | — | § Rendering |
| `skip_one_line` | `ed_scr` | `ed_scr` (advanced) | advance `ed_scr` past one line |
| `prev_line_start` | `ed_scr` | `ed_scr` (retreated) | retreat `ed_scr` to previous line start |
| `find_line_start` | — | `ed_scr` = start of the cursor's line | does not move the gap; preserves X |
| `visual_col` | — | A = column | visual column of the cursor (0..254) |
| `line_vwidth` | `ed_scr` = line start | A = width | visual width up to CR/EOF; `$FF` on 8-bit overflow |
| `cursor_line_vwidth` | — | A = width | `find_line_start` + `line_vwidth`; the INS / TAB / printable cap checks |
| `char_width` | A = byte, X = vcol | A = width | 1, or 1..`TAB_WIDTH` for `$A0`.  **Clobbers `ed_tmp`** |
| `advance_to_vcol` | A = target col | — | cursor right toward the target, stopping at CR/EOF or before a char that would overshoot |
| `_strip_label_tab` / `_strip_leading_tab` | — | — | smart-colon (§ Tab character) |
| `load_insert` | A = byte | — | `ed_load_source` callback: `gb_insert`, sets `_load_overflow` on failure, then drops the rest |
| `save_read_fn` | — | A = byte, X = 0; A = X = $FF at EOF | `ed_save_source` callback |

## Design

### Screen layout

```
Rows 0–21   Source text (ED_LINES = 22 visible lines)
Row 22      Status bar (reversed video)
Rows 23–24  Context strip: the 2 REPL rows above the prompt
```

The status bar (40 columns, all reversed):

```
*filename        free:0800-HHHH LLLL,CC
0  1-16         19-23 24-27 29-32 33-36 37 38-39
```

- Col 0: dirty flag (`*` if modified, space if clean)
- Cols 1–16: project name (`cur_project_name`, a trailing `,x` type
  suffix stripped)
- Cols 19–23: `free:` label
- Cols 24–27: lower free address — always `0800` (`workstart`)
- Col 28: `-`
- Cols 29–32: upper free address, `buf_base - 1` (= `workend`)
- Cols 33–39: cursor position as `LLLL,CC` (1-based): the line
  number right-aligned in cols 33–36 with leading blanks (col 33 is
  blank below line 1000, so it doubles as the separator), clamped
  at 9999; the column as two digits in cols 38–39.

The status bar is rebuilt in full (`ed_render_status`) by every
redraw that goes through `ed_render` / `ed_render_rows` — mode
entry and most edits.  Cursor moves update only cols 33–39
(`ed_status_pos`).  Every edit ends in `ed_mark_edited`, which sets
`ed_dirty`, draws the reversed `*` in col 0 and refreshes cols 29–32
(`ed_status_free`) and the position — so the marker appears on edits
that scroll instead of re-rendering (RETURN on the bottom row).

### Rendering

`ed_top_line` and `ed_top_ptr` cache the line number and buffer
position of the first visible line.  All rendering works from this
anchor.

- `ed_render_line` — renders one line from `ed_scr` into a screen
  row, transparently skipping the gap.  PETSCII → screen code:
  $41–$5A → $01–$1A (lowercase), $C1–$DA → $41–$5A (uppercase),
  everything else stored as is.  `$A0` (tab) expands to spaces up to
  the next `TAB_WIDTH` column.  A line wider than 39 columns gets a
  normal (not reversed) `>` ($3E) in col 39 and the rest of it is
  skipped; the row is padded with spaces.
- `ed_render_range` — renders screen rows `from` to `to` by
  advancing from `ed_top_ptr`; rows past EOF are blanked.
- `ed_render` — full redraw: all 22 rows + status bar.

Scrolling copies the 21 rows that stay on screen RAM and renders
only the new one:

- `ed_scroll_up` — cursor moved below row 21: copy rows 1–21 up to
  0–20, render the new bottom row, advance `ed_top_ptr` /
  `ed_top_line`.
- `ed_scroll_down` — cursor moved above row 0: copy rows 0–20 down
  to 1–21, render the new top row, retreat `ed_top_ptr` /
  `ed_top_line`.

The editor writes screen RAM only; colour RAM keeps the theme colour
([screen.md § Design](screen.md#design)).

### Mode switching

RUN/STOP toggles between REPL and editor; the main loop handles the
key (with release debounce) and calls `enter_editor` /
`leave_editor` ([main.md § Keyboard](main.md#keyboard)).
RUN/STOP+RESTORE in the editor redraws the REPL and sets
`state = ST_REPL`; the source is kept (main.md § Global keys).

**`enter_editor`:**
1. Save the REPL cursor (`CUR_COL`, `CUR_ROW`).
2. Save REPL screen RAM (1000 bytes) to the REPL screen save buffer
   under the KERNAL ROM ([memory_design.md § Banked
   layout](../memory_design.md)).  A pure write passes through to the
   RAM under the ROM, so no banking is needed.
3. `ed_ensure_init`.
4. Smart indent seed: if the buffer is **truly empty** — both
   `gap_lo == buf_base` (no content before the gap) AND
   `gap_hi == BUF_END` (no content after the gap) — insert a
   single `$A0` (tab) byte and set `ed_cur_col = TAB_WIDTH`,
   leaving `ed_dirty = 0`.  Both halves of the test are needed
   because after `ed_load_source` the cursor is at the start:
   `gap_lo == buf_base` holds although the loaded source lives in
   `[gap_hi, BUF_END)`.
5. Clear rows 0–21.
6. Context strip: copy two rows of the saved REPL screen — starting
   two rows above the REPL cursor row, or row 0 when the cursor is
   in rows 0–1 — to rows 23–24 (reading the save buffer needs
   `kernal_bank_out` / `kernal_bank_in`).
7. Full render (`ed_render`).
8. Sync the KERNAL cursor to the editor cursor, `state = ST_EDIT`.

**`leave_editor`:** copy the saved REPL screen back
(`kernal_bank_out` for the read), restore the REPL cursor
(`io_sync`), `state = ST_REPL`.

This is a full screen swap — no shared display area.  The editor
owns all 25 rows while active; the REPL gets its screen back
verbatim.

### Keystroke dispatch

`ed_handle_key` handles one key per call and always ends by syncing
the KERNAL cursor to the editor cursor (`ed_sync_cursor`).  "Refused"
means: `io_blip`, nothing changes.

| Key | Action | Redraw |
|-----|--------|--------|
| SHIFT+SPACE ($A0) | Tab: insert one `$A0` byte, `ed_cur_col` advances to the next `TAB_WIDTH` column.  Refused if a tab at the end of the line would pass col 39, or the buffer is full. | cursor row + status |
| LEFT | `gb_cursor_left`, `ed_cur_col` recomputed (`visual_col`; a tab is crossed in one step).  Refused at col 0 — LEFT does not wrap to the previous line. | status pos |
| RIGHT | `gb_cursor_right`, `ed_cur_col` recomputed.  Refused at a CR (no wrap), at EOF, or at col 39. | status pos |
| UP | `ed_cursor_up`: home → left over the CR → home → `advance_to_vcol(old col)`.  Refused on line 1. | scroll down if above the viewport, else status pos |
| DOWN | `ed_cursor_down`: right past the CR → `advance_to_vcol(old col)`.  Refused on the last line. | scroll up if below the viewport, else status pos |
| HOME | `gb_home`: start of the current line, col 0 | status pos |
| DEL | `gb_backspace` (a tab goes in one step).  At col 0 of a later line: join with the previous line (the viewport follows if the cursor leaves it).  At col 0 of line 1: refused. | cursor row to bottom + status |
| INS | `gb_insert($20)` then `gb_cursor_left`: opens a space at the cursor, cursor stays.  Refused if the line is already 39 columns wide, or the buffer is full. | cursor row + status |
| RETURN | Smart indent (§ Tab character).  Refused if the buffer is full. | previous row to bottom (or scroll) + status |
| printable ($20–$7E, $C1–$DA) | Insert at the cursor, `ed_cur_col + 1`.  Refused if the line is already 39 columns wide, or the buffer is full.  `:` typed at the end of a line triggers the smart colon (§ Tab character). | cursor row + status |
| anything else | Ignored, no blip (control codes, $7F–$C0 but $A0, $DB–$FF). | — |

UP / DOWN aim for the cursor's current visual column; on a shorter
line the cursor stops at its end (or before a tab that would
overshoot), and that shorter column is the target of the next move —
there is no remembered goal column.

### Buffer-full refuse

Every inserting key (RETURN, INS, TAB, printable) checks the carry
returned by `gb_insert` and is refused when the gap buffer is full
(`buf_base` at `__BUF_FLOOR__` and the gap exhausted — see
[gap_buffer.md § gb_ensure_room](gap_buffer.md#gb_ensure_room)):
`ed_cur_col` / `ed_cur_line` do not move, so the bookkeeping never
drifts from the buffer contents.

`ed_load_source` uses a separate mechanism: `load_insert` sets the
sticky `_load_overflow` flag on the first failed `gb_insert` and
drops every later byte; `ed_load_source` then empties the buffer and
returns 2 ("file too large"), which the REPL reports as `;?too big`.

### Tab character

SHIFT+SPACE ($A0) is the tab key.  It inserts a single `$A0` byte
into the gap buffer.  On screen, `$A0` renders as spaces up to the
next `TAB_WIDTH` column (minimum 1 space).  In the buffer it remains
one literal `$A0` byte, whatever its visual width.

**Visual column tracking.**  `ed_cur_col` is the visual (screen)
column, not the byte offset into the line.  A tab advances it by
1–`TAB_WIDTH` columns depending on where it starts; LEFT / RIGHT /
DEL cross a tab in one keystroke.

**Smart indent.**  RETURN applies these steps in order:

1. If the cursor is at column 0: insert `$0D`, done.  This keeps
   labels and unindented content below the split as they are.
2. Remove every `$A0` directly left and right of the cursor (all
   adjacent tabs, absorbed into the gap).
3. If the byte now left of the cursor is `:`, the smart colon runs
   (below).
4. Insert `$0D` + `$A0`.  With room for the `$0D` only (one byte
   left at `__BUF_FLOOR__`), the new line opens without its tab and
   `ed_cur_col` = 0; with no room, RETURN is refused.

**Smart colon.**  `_strip_label_tab` removes **one** `$A0` — the
first byte of the line, if it is a tab — so a label slides to
column 0; it does nothing when the line has a `;` before the cursor
(a colon in a comment).  It runs when `:` is typed at the end of a
line and in RETURN step 3.

So every new line gets a gutter tab when it fits, labels lose their
gutter when they are typed (or when RETURN follows the colon), and
splitting a line in mid-gutter removes the tabs around the split so
neither side gets a double tab.  `enter_editor` seeds one tab when
the buffer is empty so the first line is ready for an instruction.

The sequential reader passes `$A0` through as is; the assembler's
whitespace skipper treats `$A0` as whitespace.

### On m65: the layout follows the mode

The editor uses the whole screen of the current mode (operator,
2026-11-18).  Every number in § Screen layout is the run-time
geometry ([platform_layer.md § Display](../platform_layer.md#display),
*The geometry*):

```
Rows 0 … H−4   Source text (ED_ROWS = H − 3: 22 in 40 × 25 and 80 × 25, 47 in 80 × 50)
Row  H−3       Status bar
Rows H−2, H−1  Context strip: the 2 REPL rows above the prompt
```

The status bar keeps the c64 fields and their order.  Cols 0–18 (the
dirty flag, the project name, at most 16 characters) are as on c64;
the `free:` field and the position field are anchored to the right
edge — `free:aaaa-bbbb` at W − 21 … W − 8, `LLLL,CC` at W − 7 … W − 1 —
so in 40 columns the bar is the c64 bar and in 80 columns the gap
between is blank.  The free field shows the program region,
`workstart`–`workend` (`2000`–`BFFF`): fixed on m65, because the source
text is not in bank 0.  The screen save around the editor is the
mode's width × height ([platform_layer.md § Screen save](../platform_layer.md#screen-save));
`ESC 4` / `5` / `8` are refused while the editor runs.

**Line length on m65:** `LINE_MAX` = 79 visual columns (operator,
2026-11-18), a platform constant (c64 39), not the width.  Typing is
refused at `LINE_MAX` and at the screen's last column, whichever is
smaller: in 40 × 25 the cap is 39, and a longer line (written in 80
columns, or loaded) shows `>` in col 39 as on c64 and cannot grow
there.  Since `LINE_MAX` is 80 columns' last column, the editor's
caps (printable, INS, TAB, RIGHT) are `LAST_COL` in every mode — the
c64 code with its 39 named by the operand define.

**Entering after a mode change.**  The cursor's line and column
outlive the editor between visits, the mode may not: on entry a
column past the last column puts the cursor at its line's start
(`gb_home`), and a cursor row at or below `ED_ROWS` makes the
cursor's line the top of the view (as the DEL join's top adjustment).
The source is not changed.

**The m65 bodies.**  The screen save is screen.s's `screen_save` /
`screen_restore` (one DMA copy of the mode's width × height); the
context rows are copied from the save by the far byte loop; the
source rows are not cleared first (`ed_render` writes every one).
The row scrolls (`ed_scroll_up` / `ed_scroll_down`) stay the c64
row-by-row copies on far pointers, `ED_LAST` rows of `WIDTH` bytes:
D-P2-10's one-DMA-job scroll is screen.s's `scroll_up`, the REPL's.
The status bar's right fields are written through `_ed_status_right`
(the row's address + width − 40, so the c64 columns 19–39 serve);
`free:` shows `PROG_LO`–`PROG_HI` and is not redrawn by
`ed_mark_edited`, since it never changes.  Tests:
`tests/integration/test_m65_source_editor.py`.  A source with lines over 39 columns assembles on m65 and is
truncated, with the warning, by the C64 build.

### Long lines and the overflow indicator

Typing never makes a line wider than 39 visual columns (printable,
INS and TAB are refused at the cap) and RIGHT stops at col 39, so
`ed_cur_col` stays ≤ 39.  Lines in the buffer may still be wider —
from a loaded file or a DEL join.

**Rendering.**  The renderer clips at the screen edge: a line wider
than 39 columns shows `>` (normal video) in col 39 instead of its
40th column.  The hidden part cannot be reached — there is no
horizontal scrolling.  The fix is manual: split the line, shorten an
expression or a comment.

**Warnings.**  After every successful SEQ load and save the REPL
scans the buffer and prints `;!long LN` (1-based line number) for
each line wider than 39 visual columns.  The assembler reads at most
39 bytes of a line (gap_buffer.md § ed_read_line) and warns
`;!N: truncated` ([asm_src.md § Caveats](asm_src.md#caveats)).

### Assembly errors

The editor shows no assembler messages itself.  `a` is a REPL
command: it assembles the buffer and prints each error in the REPL
as `;?N: message`, where N is the 1-based source line — the same
number the status bar shows in `LLLL` — followed by the error count
(formats: [asm_src.md § Caveats](asm_src.md#caveats); messages:
[README.md § Error and warning messages](../../README.md#error-and-warning-messages)).
Pressing RUN/STOP then opens the editor with the two REPL rows above
the prompt in the context strip (rows 23–24) — normally the last
error and the count — still in view.  There is no go-to-line
command: move the cursor until the status bar shows line N.

### File I/O

Save and load go through disk.s's SEQ callbacks, so disk.s never
depends on the editor.

**Save** (`ed_save_source`): `save_read_fn` is the read callback
passed to `disk_save_seq`.  It reads sequentially through the gap
buffer — pre-gap first (`buf_base` to `gap_lo`), then post-gap
(`gap_hi` to `BUF_END`) — and returns A = byte, X = 0, or
A = X = $FF at the end.

**Load** (`ed_load_source`): resets the buffer (`ed_init`) and
`_load_overflow`, then `disk_load_seq` calls `load_insert` with each
byte.  Bytes are stored as is — no line-width enforcement, so a load
that fits preserves the file verbatim.  Afterwards the gap is
rewound to the start (`gb_cursor_left` loop) and cursor / scroll
state reset.  On an error, an empty file or an overflow `ed_init`
runs again, leaving an empty buffer.  The project name is the
REPL's business (`l` / `s`), not the editor's.

## Caveats

- Lines are separated by `$0D` (CR); `ed_read_line` strips it.
- The gap buffer shares the workspace with the assembled output
  ([memory_design.md § Source Code Storage](../memory_design.md#source-code-storage));
  the status bar's `free:` field and the REPL's `i` command show
  what is left.
- Screen save/restore copies the 1000 bytes of screen RAM only;
  colour RAM is never touched by the editor.
- `ed_load_source` returns with Z = 1 on every path (flags from
  `ldx #0`): test A, not Z.
- `BUF_END` is the link-time constant `__CODE_RUN__`, not a variable.
