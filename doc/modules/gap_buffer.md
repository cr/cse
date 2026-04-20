# gap_buffer.s — Gap-Buffer Primitives + Sequential Reader

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/gap_buffer.s`](../../src/gap_buffer.s) | implementation |
| tier-I integration tests | [`tests/integration/test_editor.py`](../../tests/integration/test_editor.py) (via the full PRG for now; a dedicated Tier-U bundle is a queued follow-up) |

## Purpose

L3 module that owns the gap-buffer data structure and the sequential
reader the source assembler walks.  Pure byte-level memory
manipulation on the gap at `(gap_lo, gap_hi)` and the read cursor at
`(read_ptr)` — no KERNAL calls, no VIC registers, no screen RAM, no
BRK vectors.  This is what makes it bundle-testable at Tier U
independently of the keystroke dispatch / rendering / disk I/O
machinery that lives one layer up in `editor.s`.

Split from `editor.s` at the 2026-04-20 structural refactor so the
tier boundary becomes a compile-time fact rather than a disciplined
convention — same pattern as the `breakpoints.s` split from
`debugger.s`.  Anything that depends on `gap_buffer.s` is strictly
one layer up, and `gap_buffer.s` itself can't reach into screen /
KERNAL machinery because that machinery lives at L4.

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
  $100`) when `gb_ensure_room` needs more space; clamps at
  `__BUF_FLOOR__` (set by `dev/compute_layout.py`).
- **`gap_lo`** — first byte of the gap.  Bytes `[buf_base, gap_lo)`
  are pre-cursor content.
- **`gap_hi`** — first byte after the gap.  Bytes `[gap_hi, BUF_END)`
  are post-cursor content.
- **`BUF_END`** (= `__CODE_RUN__`) — ceiling, exclusive.  Fixed at
  link time as the start of runtime code.
- **Cursor** — logically sits "in" the gap.  Moving right consumes
  the first byte of post-gap (copies it into the pre-gap side).
  Moving left does the reverse.
- **`read_ptr`** — sequential reader position, independent of the
  cursor.  Walks from `buf_base` to `BUF_END` transparently skipping
  the gap (jumps from `gap_lo` to `gap_hi` when it reaches the gap
  boundary).

## Interface

### gb_init
**In:** none
**Out:** empty buffer — `buf_base = gap_lo = gap_hi = BUF_END`,
`ed_top_ptr = BUF_END`, `src_top = src_bot = BUF_END`, `ed_total_lines = 1`
(the implicit empty line), `ed_dirty = 0`.  Calls `update_workend`.
**Clobbers:** A.

Called by `editor.s::ed_init` at cold init and on `ed_new` / disk
load.  `editor.s` handles the additional rendering-state reset
(`ed_cur_line`, `ed_cur_col`, `ed_top_line`) after this returns.

### ed_ensure_init
**In:** none
**Out:** if `ed_total_lines` is zero, runs `gb_init`; otherwise no-op.
**Clobbers:** A.

Lazy init guard.  Called by the sequential reader, `ed_insert_string`,
and `editor.s::enter_editor` so first use does a full init but later
use is a cheap check.

### gb_insert
**In:** A = byte to insert
**Out:** C=1 success, C=0 failure (buffer full — byte discarded).
Inserts at the cursor (= `gap_lo`); `gap_lo` advances by 1.  Bumps
`ed_total_lines` if the byte is CR.  Sets `ed_dirty`.
**Clobbers:** A, Y.

### gb_backspace
**In:** none
**Out:** byte immediately before the cursor is deleted (`gap_lo -= 1`).
Decrements `ed_total_lines` if the deleted byte was CR.  Sets
`ed_dirty`.  No-op if cursor is at `buf_base`.
**Clobbers:** A.

### gb_cursor_left / gb_cursor_right
**In:** none
**Out:** moves one byte in the given direction by shifting a byte
across the gap.  No-op at the respective buffer end.
**Clobbers:** A.

### gb_home
**In:** none
**Out:** moves the cursor left until it lands at the start of the
current logical line (either the byte after the previous CR or
`buf_base`).  Loop of `gb_cursor_left` calls.
**Clobbers:** A, Y, `ed_tmp`.

### gb_ensure_room
**In:** none
**Out:** C=1 if the gap has at least one byte free; C=0 if the
buffer floor has been reached.  If the gap is exhausted but growth
is still possible, subtracts 256 from `buf_base` and copies the
pre-gap content down, making room at the gap_hi side.  Updates
`src_bot` and calls `update_workend`.
**Clobbers:** A, Y, `ed_tmp`, `ed_scr`, save_ptr (= `read_ptr`).

### ed_insert_string
**In:** A/X = NUL-terminated PETSCII string pointer
**Out:** string inserted at cursor (bytes fed into `gb_insert`).
On buffer-full mid-string, insertion stops silently — the caller is
responsible for checking `_load_overflow` in editor.s.
**Clobbers:** A, Y, save_ptr (= `read_ptr`).

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
**Clobbers:** A, X, Y, `ed_tmp`.

Partial-result contract (Principle 13): on success `read_ptr`
advances by 1 byte (virtual), possibly jumping across the gap
physically.  On EOF `read_ptr` is stable (already at or past BUF_END).

### ed_read_line
**In:** A/X = destination buffer pointer (maxlen hardcoded to 40).
**Out:** A = length copied (0–40), X = 0 on success; A = X = $FF at
EOF.  Scan runs from `read_ptr` until CR or EOF, copies bytes into
the buffer, returns length.  On CR termination, `read_ptr` advances
by (length + 1).  On no-CR-last-line, `read_ptr` advances to
`BUF_END` (crossing the gap).  On EOF, `read_ptr` is stable.
**Clobbers:** A, X, Y, `ed_scr`, `ed_tmp`.

See [editor.md § Partial-result contract](editor.md) for the
full stopping-position matrix.

### check_buf_end
**In:** `ed_scr` = pointer to check.
**Out:** C=1 if `ed_scr >= BUF_END` (past end); C=0 if still in
buffer.
**Clobbers:** A.

Internal helper shared between `gap_buffer.s`'s reader and
`editor.s`'s rendering code.

### define_ws_syms / update_workend
**In:** none
**Out:** registers the `workstart` symbol at `$0800` (fixed) and
the `workend` symbol at `buf_base - 1` (dynamic — tracks buffer
growth).  Called from main.s cold-init and `asm_src::asm_assemble`
after `sym_clear`.
**Clobbers:** A.  (sym_define call uses the standard sym_name/val/wide
ZP as input.)

`update_workend` is also called internally by `gb_init` and
`gb_ensure_room` whenever `buf_base` changes.

### Memory

**BSS (6 bytes):** `ed_total_lines` (2), `src_top` (2), `src_bot` (2).

**ZP reads (from zp.s):** `gap_lo`, `gap_hi`, `buf_base`,
`ed_top_ptr`, `read_ptr` (= save_ptr), `ed_tmp`, `ed_scr`, `ed_dirty`.

**Depends on:** `zp` (ZP vars), `strings` (`s_workstart`,
`s_workend`), `symtab` (`sym_define` + sym_name/val/wide ZP).
Linker-provided `__CODE_RUN__` (= BUF_END) and `__BUF_FLOOR__`.

## Test contract

Currently exercised through `tests/integration/test_editor.py` (C64Emu
+ full PRG).  `TestGapBufferInsert` and `TestEdReadLine` (including
the Principle-13 position-pinning tests) cover the module's public
surface — but via the heavier integration harness.

A queued follow-up migrates the pure-gap-buffer tests to a dedicated
Tier U bundle (`gap_buffer + zp + strings + symtab + mem +
gap_buffer_test_stub`) on the same pattern as the breakpoints bundle.
The existing integration-tier coverage is sufficient for correctness
— the Tier U bundle is a speed/isolation win, not a coverage gap.

## Design notes

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
