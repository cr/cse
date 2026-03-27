# editor.c — Gap-Buffer Source Editor

## Interface

- `enter_editor()` — save REPL screen, switch to editor mode
- `leave_editor()` — restore REPL screen, return to REPL
- `ed_handle_key(ch)` — process one keystroke (__fastcall__)
- `ed_ensure_init()` — allocate gap buffer if not yet done
- `ed_new()` — clear source buffer (reset gap buffer)
- `ed_save_source(name)` — save source as SEQ file; returns 0 on success
- `ed_load_source(name)` — load SEQ file into buffer; returns 0 on success
- `ed_read_rewind()` — reset sequential reader to start of source
- `ed_read_line(buf, maxlen)` — read next line into buf; returns length or -1 at EOF
- `ed_insert_string(text)` — programmatic text insertion

**Statistics:** `ed_save_bytes`, `ed_save_lines` — counts from last file operation.

**Depends on:** disk (SEQ callbacks), screen

## Design

Gap buffer: contiguous memory with a movable gap at the cursor.
Insertions and deletions are O(1) at the cursor, O(n) for cursor
movement (gap slides).  Source grows downward from $C7FF; assembled
output grows upward from the origin address.

Screen layout: rows 0–21 = source text, row 22 = status bar
(dirty flag, filename, free bytes, line:col), rows 23–24 = preserved
for REPL restore.

The sequential reader (`ed_read_rewind` / `ed_read_line`) provides
a line-at-a-time interface for asm_src.s without exposing gap buffer
internals.  The assembler calls `ed_read_rewind` before each pass,
then `ed_read_line` in a loop until EOF (-1).

## Caveats

- `ed_read_line` returns a NUL-terminated PETSCII string.  Lines are
  separated by $0D (CR) internally but the CR is stripped on read.
- The gap buffer shares the $0800–$C7FF region with assembled output.
  The `i` command shows remaining space.
- Screen save/restore on mode switch copies 1000 bytes (screen RAM only,
  not color RAM).
