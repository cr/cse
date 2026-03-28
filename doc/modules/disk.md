# disk.s — CBM File I/O

**Template:** [module](../templates/module.md)

## Interface

### floppy_status
**In:** none
**Out:** prints drive status to screen
**Clobbers:** A, X, Y

### list_directory
**In:** A = device number (__fastcall__)
**Out:** prints directory listing to screen
**Clobbers:** A, X, Y

### disk_load_prg
**In:** A/X = load address (__fastcall__), C stack = filename ptr
**Out:** A/X = end address (nonzero on success, 0 on error)
**Clobbers:** A, X, Y

If load address is 0, uses the PRG header address (secondary = 0).

### disk_save_prg
**In:** A/X = size (__fastcall__), C stack = filename ptr (bottom),
start address (top)
**Out:** A = 0 on success, nonzero on error
**Clobbers:** A, X, Y

### disk_load_seq
**In:** A/X = insert callback (__fastcall__), C stack = filename ptr
**Out:** A = 0 on success, nonzero on error (includes empty file).
`disk_seq_bytes`, `disk_seq_lines` set.
**Clobbers:** A, X, Y

The callback receives each byte in A.  Called once per byte read.

### disk_save_seq
**In:** A/X = read callback (__fastcall__), C stack = filename ptr
**Out:** A = 0 on success, nonzero on error.
`disk_seq_bytes`, `disk_seq_lines` set.
**Clobbers:** A, X, Y

The callback returns a byte in A (lo) and X=0.  EOF is signalled
by returning A=$FF, X=$FF (int16 -1).

**BSS:** `disk_seq_bytes` (2B), `disk_seq_lines` (2B) — transfer counts.
Line count starts at 1: N newlines = N+1 lines.

**Depends on:** screen (newline, print_string), cse_io (io_puts,
io_putc, io_putdec, io_puthex2/4, io_getc, io_kbhit, io_clear_eol)

## Design

All file I/O uses direct KERNAL calls (SETLFS, SETNAM, OPEN, CLOSE,
CHKIN, CHKOUT, CHRIN, CHROUT, LOAD, SAVE, READST, CLRCHN).  No cc65
cbm wrappers.

**Device number** comes from `_cur_device` (imported from repl.c).

**SEQ open strings** are built by `build_open_str`, which copies the
filename into `open_buf` and appends `,s,r` (read) or `@:` prefix +
`,s,w` (write, overwrite mode).

**SEQ I/O uses callbacks** so disk.s never depends on editor.c.  The
editor passes its insert function for loading and its read function
for saving.  Callbacks are stored in `callback` (2B BSS) and invoked
via `jmp (callback)`.

**SEQ read loop:** After each CHRIN, READST is called immediately
(before the callback) to capture the EOF flag — the callback may
clobber the KERNAL status byte at $90.

**Error channel:** After every disk operation, the drive error channel
(channel 15) is read automatically via `floppy_status` and printed
to screen.

**ZP usage:** Reuses cse_io's scratch at $FB-$FE (`_io_tmp` 2B,
`ptr` 2B).  Not in the ZEROPAGE segment — hardcoded addresses.

## Caveats

- PRG load/save use KERNAL LOAD/SAVE directly.  LOAD returns end
  address in X/Y on success.
- SEQ save uses `@:` prefix for automatic overwrite.  No "file exists"
  error — the old file is replaced silently.
- An empty SEQ file (0 bytes read) is treated as an error by
  `disk_load_seq` (returns 1).
- `build_open_str` uses `open_buf` (28B BSS) as scratch.
