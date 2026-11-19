# gap_buffer.s — Gap-Buffer Primitives + Sequential Reader

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/gap_buffer.s`](../../src/gap_buffer.s) | implementation |
| [`tests/unit/test_gap_buffer.py`](../../tests/unit/test_gap_buffer.py) | test contract — Tier-U bundled coverage (36 tests) |

The editor's Tier I tests, [`tests/integration/test_editor.py`](../../tests/integration/test_editor.py)
(owned by [editor.md](editor.md)), exercise this module transitively.

## Purpose

L3 module that owns the gap-buffer data structure and the sequential
reader the source assembler walks.  Pure byte-level memory
manipulation on the gap at `(gap_lo, gap_hi)` and the read cursor at
`(read_ptr)` — no KERNAL calls, no VIC registers, no screen RAM, no
BRK vectors.  This is what makes it bundle-testable at Tier U
independently of the keystroke dispatch / rendering / disk I/O
machinery that lives one layer up in `editor.s`.

The split from `editor.s` makes the tier boundary a compile-time
fact rather than a convention (the same pattern as `breakpoints.s`
under `debugger.s`): anything that depends on `gap_buffer.s` is
strictly one layer up, and `gap_buffer.s` cannot reach screen or
KERNAL machinery because that lives at L4.

## Buffer layout

```
    buf_base ─── gap_lo         gap_hi ─── BUF_END (= __CODE_RUN__)
         │         │                │              │
         ▼         ▼                ▼              ▼
   ┌──────────┬──────────────┬─────────────────┐
   │ text     │ <--- gap --->│ text            │
   └──────────┴──────────────┴─────────────────┘
         │   pre-gap content │   post-gap content
```

- **`buf_base`** — floor of the buffer.  Grows downward (`buf_base -=
  $100`) when `gb_ensure_room` needs more space, never below
  `__BUF_FLOOR__`.
- **`gap_lo`** — first byte of the gap.  Bytes `[buf_base, gap_lo)`
  are pre-cursor content.
- **`gap_hi`** — first byte after the gap.  Bytes `[gap_hi, BUF_END)`
  are post-cursor content.
- **`BUF_END`** (c64: `__CODE_RUN__`) — ceiling, exclusive.  Fixed at
  link time as the start of runtime code.  Defined once, in
  platform.inc, with `BUF_FLOOR`; editor.s and gap_buffer.s both use
  it ([platform_layer.md § Constants](../platform_layer.md#constants)).
- **`BUF_FLOOR`** (c64: `__BUF_FLOOR__`) — the lowest address the
  buffer may grow to, computed per build by `dev/compute_layout.py`
  (`$0800` + one ninth of the workspace, page-aligned down), so the
  source text and the assembled output growing up from `$0800` meet
  at about the same time.  It must be page-aligned (the growth check
  compares high bytes only).
- **Cursor** — logically sits "in" the gap.  Moving right consumes
  the first byte of post-gap (copies it into the pre-gap side).
  Moving left does the reverse.
- **`read_ptr`** — sequential reader position, independent of the
  cursor.  Walks from `buf_base` to `BUF_END` transparently skipping
  the gap (jumps from `gap_lo` to `gap_hi` when it reaches the gap
  boundary).

**On m65** the layout is the same, in the source region
([memory_design.md § Source Code Storage](../memory_design.md#source-code-storage)):
`BUF_END` and `BUF_FLOOR` are platform constants, offsets inside
the source bank (`$C000` and `$4000`).  The buffer's pointers are far pointers
([zp.md](zp.md)): their 16-bit offsets are the arithmetic above, the
same code on both platforms, and their bank is set to the source bank
wherever they are set into the text (`FAR_BANK`): `gap_lo`, `gap_hi`,
`buf_base` and `ed_top_ptr` live in the text, so `gb_init` sets their
banks once and every other site rewrites their offsets only; the
shared scratch pointers get theirs in the routine that points them —
`ed_tmp` in `gb_home` (and editor.s's `find_line_start`,
`prev_line_start`), `ed_scr` / `save_ptr` in `gb_ensure_room`'s copy
and `read_ptr` in `ed_read_rewind` (`BANK_SRC`); `ed_read_line`'s
destination and `ed_insert_string`'s text are in CSE's view
(`BANK_CSE`, the latter again after each `gb_insert`, whose growth
borrows `save_ptr`).  editor.s points `ed_scr`, `ed_tmp` and `save_ptr`
at the screen with `FAR_BANK_SCREEN`.  The byte accesses
go through `FAR_LDA` / `FAR_STA`
([platform_layer.md § Far memory](../platform_layer.md#far-memory)),
whose m65 clobbers (the `Z` register; N/Z on a store) no caller here
relies on, so no clobber list below changes.  On m65 the source text
and the user's output are in different regions and do not compete for
space.

Lines are separated by `$0D` (CR); there is no terminator after the
last line.  The workspace this buffer shares with the assembled
output is mapped in
[memory_design.md § Source Code Storage](../memory_design.md#source-code-storage).

## Interface

The clobber lists below include what a callee pulls in: every
`gb_insert` can grow the buffer, and growth calls `update_workend`
→ `sym_define` ([symtab.md](symtab.md)), which clobbers A, X, Y,
`sym_name` / `sym_val` / `sym_wide` and symtab's `_st_*` ZP.  That
set is written "symtab ZP" below.

### gb_init
**In:** none
**Out:** empty buffer — `buf_base = gap_lo = gap_hi = BUF_END`,
`ed_top_ptr = BUF_END`, `src_top = src_bot = BUF_END`, `ed_total_lines = 1`
(the implicit empty line), `ed_dirty = 0`.
**Clobbers:** A.

**Leaf — does not touch the symbol table.**  Callers that need
the `workend` symbol republished after a `buf_base` change call
`update_workend` (or `define_ws_syms`) explicitly:
- `editor.s::ed_init` does so as part of its full reset wrapper.
- `main.s` cold init does so via `define_ws_syms` right after
  `ed_ensure_init` ([main.md § Layer 1](main.md)).

This is what lets cold init call `ed_ensure_init` before `sym_clear`
has set up the name heap.  `editor.s::ed_init` resets the rendering
state (`ed_cur_line`, `ed_cur_col`, `ed_top_line`) after this returns.

### ed_ensure_init
**In:** none
**Out:** if `ed_total_lines` is zero (BSS-zero: never initialised),
runs `gb_init`; otherwise no-op.
**Clobbers:** A.

Lazy init guard.  Called by `ed_read_rewind`, `ed_insert_string`,
`editor.s` (`enter_editor`, `ed_save_source`), `main.s` cold init
and `repl.s` (`s` of a SEQ file), so first use does a full init and
later use is a cheap check.

### gb_insert
**In:** A = byte to insert
**Out:** C=1 success, C=0 failure (buffer full — byte discarded,
nothing changed).  Calls `gb_ensure_room` first, then stores at the
cursor (= `gap_lo`); `gap_lo` advances by 1.  Bumps
`ed_total_lines` if the byte is CR.  Sets `ed_dirty` on success.
**Clobbers:** A, Y, `ed_tmp`; when the buffer grows also X,
`ed_scr`, `read_ptr` (= save_ptr) and symtab ZP.

### gb_backspace
**In:** none
**Out:** byte immediately before the cursor is deleted (`gap_lo -= 1`).
Decrements `ed_total_lines` if the deleted byte was CR.  Sets
`ed_dirty`.  No-op (and `ed_dirty` untouched) if the cursor is at
`buf_base`.
**Clobbers:** A, Y.

### gb_cursor_left / gb_cursor_right
**In:** none
**Out:** moves one byte in the given direction by shifting a byte
across the gap.  No-op at the respective buffer end (`buf_base` /
`BUF_END`).  Crosses CRs like any other byte; `ed_dirty` untouched.
**Clobbers:** A, Y.

### gb_home
**In:** none
**Out:** moves the cursor left until it lands at the start of the
current logical line (either the byte after the previous CR or
`buf_base`).  Loop of `gb_cursor_left` calls.
**Clobbers:** A, Y, `ed_tmp`.

### gb_ensure_room
**In:** none
**Out:** C=1 if the gap has at least one byte free (growing first if
needed); C=0 if the gap is empty and `buf_base - 256` would fall
below `__BUF_FLOOR__`.  To grow, it subtracts 256 from `buf_base`,
copies the pre-gap content down by 256, leaves a 256-byte gap, moves
`ed_top_ptr` down with the text when it points into the pre-gap,
sets `src_bot = buf_base` and calls `update_workend`.
**Clobbers:** A, `ed_tmp`; when it grows also X, Y, `ed_scr`,
`read_ptr` (= save_ptr) and symtab ZP.

### ed_insert_string
**Test-only export.**  No production code calls it (the editor's
keystrokes and `load_insert` call `gb_insert` directly); it stays
exported for the gap_buffer and editor tests to seed buffer content.
**In:** A/X = NUL-terminated PETSCII string pointer
**Out:** string inserted at cursor (bytes fed into `gb_insert`).
It ignores `gb_insert`'s carry: once the buffer is full the rest of
the string is dropped and the call returns normally — the caller
gets no indication.  A production caller would have to check the
carry per byte instead.
**Clobbers:** A, X, Y, `read_ptr` (= save_ptr, the text pointer),
and everything `gb_insert` clobbers.

### ed_read_rewind
**In:** none
**Out:** `read_ptr = buf_base`, ready for a fresh scan.  Calls
`ed_ensure_init` first so a rewind on an uninitialised buffer
works.
**Clobbers:** A.

### ed_read_byte
**In:** none
**Out:** A = next byte from the buffer, X = 0; or A = X = $FF at EOF.
Advances `read_ptr` by 1 (or skips from `gap_lo` to `gap_hi` when it
lands inside the gap).
**Clobbers:** A, X, Y.

### ed_read_line
**In:** A/X = destination buffer pointer (40 bytes: at most 39
characters and the NUL; on m65 80 bytes: `LINE_MAX` = 79, the source
line length there — [editor.md § On m65](editor.md#on-m65-the-layout-follows-the-mode);
every 39 below is `LINE_MAX`).
**Out:** A = length copied (0–39), buffer NUL-terminated; X = 0 when
the whole line fit, X = 39 (non-zero, positive) when characters past
the 39th were dropped; or A = X = $FF at EOF (nothing left to read).
Copies bytes from `read_ptr` up to the next CR or EOF; the CR is
consumed, not stored.  A line longer than 39 characters is
**truncated**: the first 39 are stored, the rest is consumed up to
the CR and dropped, and X says so — a line of exactly 39 characters
returns X = 0.
**Clobbers:** A, X, Y, `ed_scr`, `ed_tmp`.

### Partial-result contract

`ed_read_line` and `ed_read_byte` are partial-result functions
([testing.md § Principles](../testing.md#principles), item 13):
`read_ptr` is the ancillary state.  Each successful call advances
`read_ptr` past the consumed bytes; callers (the two-pass source
assembler, `repl.s::warn_long_lines`) depend on this to compose
repeated reads into a stream walk.

- `ed_read_byte` — advances `read_ptr` by 1 on each non-EOF call,
  stepping over the gap when `read_ptr` lands on `gap_lo`.  Returns
  A = X = $FF at EOF without further advance.
- `ed_read_line` — on a CR-terminated line the advance is exactly
  (bytes on the line + 1), truncated bytes included.  On the final
  line with no trailing CR, `read_ptr` ends at `BUF_END` (it crosses
  the gap if the gap lies after the content).  **EOF is
  idempotent:** once a call has returned EOF, further calls keep
  returning EOF and leave `read_ptr` stable.  The *first* EOF call
  may still advance (from `gap_lo` across the gap to `BUF_END`);
  what callers can rely on is that `read_ptr` is stable across
  repeated EOF calls.

### check_buf_end
**In:** `ed_scr` = pointer to check.
**Out:** C=1 if `ed_scr >= BUF_END` (past end); C=0 if still in
buffer.
**Clobbers:** A.

Shared helper for `editor.s`'s rendering code.

### define_ws_syms / update_workend
**In:** none
**Out:** `define_ws_syms` registers the `workstart` symbol at `$0800`
(fixed) and falls through into `update_workend`, which (re)defines
the `workend` symbol at `buf_base - 1` (dynamic — tracks buffer
growth).  Both symbols are absolute (`sym_wide = 1`).
**Clobbers:** A, X, Y, symtab ZP.

**On m65:** `workstart` and `workend` are the program region's
bounds, `PROG_LO` and `PROG_HI`
([memory_design.md § Memory Map — m65](../memory_design.md#memory-map--m65-mega65-mode));
`workend` does not move, because the source text is not in bank 0.  `update_workend`
still runs where it runs on c64 and defines the same value.

`define_ws_syms` is called from `main.s` cold init and from
`asm_src.s::asm_assemble` after `sym_clear`.  `update_workend` is
called by `gb_ensure_room` after a gap grow shifts `buf_base` down,
and by `editor.s::ed_init` after every full editor reset.  It is
**not** called by `gb_init` (see § gb_init).

### Memory

**BSS (6 bytes):** `ed_total_lines` (2), `src_top` (2), `src_bot` (2).

**ZP (from zp.s, allocation in [zp.md](zp.md)):** `gap_lo`, `gap_hi`,
`buf_base`, `ed_top_ptr`, `read_ptr` (= save_ptr), `ed_tmp`, `ed_scr`,
`ed_dirty`.

**Depends on:** `zp` (ZP vars), `strings` (`s_workstart`,
`s_workend`), `symtab` (`sym_define` + sym_name/val/wide ZP),
`platform.inc` (`FAR_PTR`, `FAR_BANK`, `FAR_LDA`, `FAR_STA`).
Linker-provided `__CODE_RUN__` (= BUF_END) and `__BUF_FLOOR__` on c64;
platform constants on m65.

## Test contract

Full Tier U coverage via `tests/unit/test_gap_buffer.py` (36 tests):

| Test class | Coverage |
|---|---|
| `TestGapBufferInsert` (5) | `ed_insert_string`, `gb_insert`, `ed_total_lines` bump on CR, `ed_dirty` flag. |
| `TestEdReadLine` (8) | `ed_read_rewind`, `ed_read_byte`, `ed_read_line`, the dropped-characters flag (38/39/40/60 characters, CR- and EOF-ended) + 4 position-pinning cases (exact delta for CR-terminated, empty-line, no-CR-last-line, post-EOF idempotency). |
| `TestGbBackspace` (5) | `gb_backspace` content shortening, gap_lo decrement (ancillary state), CR-deletion decrements `ed_total_lines`, no-op at buf_base. |
| `TestGbCursorMove` (6) | `gb_cursor_left` / `gb_cursor_right` content preservation, round-trip, gap_lo/gap_hi co-movement, no-op at buffer ends. |
| `TestGbHome` (3) | `gb_home` single-line → buf_base, multi-line → just past CR, already-at-start no-op. |
| `TestGbEnsureRoom` (3) | First insert triggers growth, content preserved across multiple growth rounds, BUF_FLOOR returns C=0. |
| `TestEdInsertStringFull` (1) | `ed_insert_string` on a full buffer drops the rest of the string, nothing written past the gap. |
| `TestGbInitLeaf` (1) | `gb_init` does not reach the symbol table (`$0000`–`$0007` untouched with `_st_heap` = 0). |
| `TestWorkspaceSymbols` (3) | `define_ws_syms` registers `workstart = $0800`, `workend = buf_base - 1`, and `update_workend` tracks growth. |
| `TestBufferBoundsState` (3) | `src_top` / `src_bot` BSS state reflects buffer bounds. |

`ed_read_byte`'s per-call advance is also witnessed transitively by
the `_read_back` helper, which walks the whole buffer byte by byte
and asserts the reconstructed content in every insert case.

The bundle links `zp + strings + mem + symtab + gap_buffer` — no
behavioural mocks.  `sym_table` at `$E000` is writable RAM in py65
so the real symtab code runs.  Linker-provided `__CODE_RUN__=$4000`
and `__BUF_FLOOR__=$1500` via `ld65 -D` flags.

## Design

**Why `ed_total_lines` / `src_top` / `src_bot` are here and not in
`editor.s`.**  All three are gap-buffer state: `ed_total_lines` is
bumped on CR insert/delete (inside gb_insert/gb_backspace); `src_top`
is set at buffer init; `src_bot` moves with `gb_ensure_room`'s
allocation.  Their semantics index into the data structure this
module owns, so they belong here — even though they're READ by L4
code (rendering + the REPL `i` command).  Same reasoning as
`dbg_bp_hit` in breakpoints.s.

**Why the sequential reader is here and not in editor.s.**  It's
the canonical CONSUMER of the gap data structure — it walks from
`buf_base` to `BUF_END`, jumping over the gap.  No screen, no KERNAL.
Pure data-structure traversal.

**What does NOT belong here.**  Anything that reads or writes the
screen, dispatches keystrokes, renders lines, manages scroll,
handles disk I/O, or tracks visual cursor state lives in `editor.s`
(L4).  Specifically: `ed_handle_key`, `ed_render*`, `ed_scroll_*`,
`ed_cursor_*` (visual cursor movement — different from `gb_cursor_*`
which is gap-byte movement), `enter_editor`, `leave_editor`,
`ed_save_source`, `ed_load_source`, and the `ed_cur_line` /
`ed_cur_col` / `ed_top_line` BSS triple.

## Caveats

- **`save_ptr` / `read_ptr` aliasing.**  `save_ptr` is a
  compile-time alias for `read_ptr`; `ed_insert_string` (its text
  pointer), `gb_ensure_room` (the source pointer of the pre-gap block
  copy) and the reader all use it, and they are never live at the
  same time.  `ed_insert_string` pushes / pops its text pointer
  around each `gb_insert`, because a growth with pre-gap content
  overwrites it (`TestGbEnsureRoom::test_growth_preserves_content`).
  A read in progress does not survive an insert that grows the buffer.
- Growth is in 256-byte steps; the block copy of the pre-gap text is
  the most expensive operation in the module.
