# disk.s — CBM File I/O

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/disk.s`](../../src/disk.s) | implementation |

## Interface

### floppy_read_status
**In:** none
**Out:** drive error channel read into `fl_buf` (NUL-terminated)
**Clobbers:** A, X, Y

### floppy_status
**In:** none
**Out:** reads drive status and prints it as an info line
**Clobbers:** A, X, Y

Calls `floppy_read_status` then `out_info(fl_buf)`.

### list_directory
**In:** A = device number
**Out:** prints directory listing to screen
**Clobbers:** A, X, Y

Caller is responsible for reading drive status after return
(e.g. via `floppy_status` or `floppy_read_status`).

### disk_load_prg
**In:** A/X = load address; `disk_ptr` (ZP) = filename ptr
**Out:** A/X = end address (nonzero on success, 0 on error)
**Clobbers:** A, X, Y

If load address is 0, uses the PRG header address (secondary = 0).

### disk_save_prg
**In:** A/X = size; `disk_ptr` (ZP) = filename ptr;
`_io_tmp` (ZP) = start address
**Out:** A = 0 on success, nonzero on error
**Clobbers:** A, X, Y

### disk_load_seq
**In:** A/X = insert callback; `disk_ptr` (ZP) = filename ptr
**Out:** A = 0 on success, nonzero on error (includes empty file).
`disk_seq_bytes`, `disk_seq_lines` set.
**Clobbers:** A, X, Y

The callback receives each byte in A.  Called once per byte read.

### disk_save_seq
**In:** A/X = read callback; `disk_ptr` (ZP) = filename ptr
**Out:** A = 0 on success, nonzero on error.
`disk_seq_bytes`, `disk_seq_lines` set.
**Clobbers:** A, X, Y

The callback returns a byte in A (lo) and X=0.  EOF is signalled
by returning A=$FF, X=$FF (int16 -1).

**Depends on:** repl (out_info), screen (newline), cse_io (io_puts,
io_putc, io_putdec, io_puthex2/4, io_getc, io_kbhit, io_clear_eol)

### Memory

**ZP (2 bytes):** `disk_ptr` (2) — filename pointer, set by caller
before disk_load_prg/save_prg/load_seq/save_seq.

**BSS (67 bytes):**

| Variable | Size | Purpose |
|----------|------|---------|
| `_disk_seq_bytes` | 2 | Bytes transferred (last SEQ op) |
| `_disk_seq_lines` | 2 | Lines transferred (last SEQ op) |
| `fl_buf` | 32 | File listing line buffer |
| `open_buf` | 28 | Filename build buffer for CBM open |
| `callback` | 2 | SEQ I/O function pointer |
| `eof_flag` | 1 | READST EOF flag for SEQ read |

## Design

All file I/O uses direct KERNAL calls (SETLFS, SETNAM, OPEN, CLOSE,
CHKIN, CHKOUT, CHRIN, CHROUT, LOAD, SAVE, READST, CLRCHN).

**Device number** comes from `_cur_device` (imported from repl.s).

**SEQ open strings** are built by `build_open_str`, which copies the
filename into `open_buf` and appends `,s,r` (read) or `@:` prefix +
`,s,w` (write, overwrite mode).

**SEQ I/O uses callbacks** so disk.s never depends on editor.s.  The
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
