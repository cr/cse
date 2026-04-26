# disk.s — CBM File I/O

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/disk.s`](../../src/disk.s) | implementation |

**Test coverage** — Pattern C (cannot be enforced at any unit tier)
per [testing.md § Principle 9](../testing.md).  No automated test
file for `disk.s`.  Every export (`list_directory`, `floppy_status`,
`floppy_read_status`, the SETLFS / SETNAM / OPEN / LOAD / SAVE
wrappers) drives KERNAL IEC entry points that are not modelled by
the py65 + C64Emu harness — there is no virtual IEC bus, no D64
backend, and no IEC timing simulation.  Coverage is therefore
manual: VICE with a mounted D64 image, exercising `l` / `s` /
`$` REPL commands across PRG / SEQ / verbatim-name forms,
device-not-present, file-not-found, and overwrite paths.  Plans
to graduate this to Tier I are tracked under
[TODO.md § C64Emu extension roadmap — Virtual IEC disk](../TODO.md).
Until that lands, every disk.s edit must be VICE-walked before
commit.

## Interface

### floppy_read_status
**In:** none
**Out:** drive error channel read into `fl_buf` (NUL-terminated)
**Clobbers:** A, X, Y

### floppy_status
**In:** none
**Out:** reads drive status and prints it as an info line
**Clobbers:** A, X, Y

Calls `floppy_read_status` then `log_info(fl_buf)`.

### list_directory
**In:** A = device number
**Out:** prints directory listing to screen
**Clobbers:** A, X, Y, workspace at $0801+ (~5 KB max)

Uses KERNAL LOAD to read the directory into workspace at $0801,
then walks the in-memory buffer to display entries.  Workspace
contents are overwritten.  This approach (vs OPEN+CHKIN+CHRIN)
is compatible with both stock CBM KERNAL and MEGA65 Open-KERNAL
(see MEGA65/open-roms#116, #117 for the channel-I/O bugs).

Caller is responsible for reading drive status after return
(e.g. via `floppy_status` or `floppy_read_status`).

### disk_load_prg
**In:** A/X = load address; `disk_ptr` (ZP) = filename ptr
**Out:** A/X = end address (nonzero on success, 0 on error)
**Clobbers:** A, X, Y

KERNAL SETLFS secondary address selects the load mode:
- addr ≠ 0 → SA=0: KERNAL loads to the address in X/Y (caller's addr).
- addr = 0 → SA=1: KERNAL loads to the PRG file's 2-byte header address.

### disk_save_prg
**In:** A/X = size; `disk_ptr` (ZP) = filename ptr;
`_io_tmp` (ZP) = start address
**Out:** A = 0 on success, nonzero on error
**Clobbers:** A, X, Y

Uses OPEN + CHKOUT + CHROUT + CLOSE (same flow as `disk_save_seq`),
with a `,p,w` CBM DOS qualifier and `@:` save-with-replace prefix.
Writes the 2-byte load-address header (little-endian) to the DOS
data channel, then the payload bytes.  No `SAVE` KERNAL call — the
caller already supplies the filename, `@:` overwrite is applied
via `build_open_str` at type='p'.

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

**Depends on:** log (log_info), screen (newline), cse_io (io_puts,
io_putc, io_putdec, io_puthex2/4, io_getc, io_kbhit, io_clear_eol),
strings (str_dname, str_dir_brk, str_blk_free, str_blk_pre, str_blk_suf),
zp (disk_ptr, _io_tmp, cur_device)

`cur_device` (formerly imported from repl.s) now lives in zp.s as a
cross-module flag, eliminating the repl back-edge.

## Design

All file I/O uses direct KERNAL calls (SETLFS, SETNAM, OPEN, CLOSE,
CHKIN, CHKOUT, CHRIN, CHROUT, LOAD, SAVE, READST, CLRCHN).

**Device number** comes from `_cur_device` (imported from repl.s).

**CBM DOS open strings** are built by `build_open_str`, which takes
mode (`r`/`w` in A) and file type (`s` for SEQ, `p` for PRG in X).
It copies the filename into `open_buf`, appends `,<type>,<mode>` if
no existing type suffix is present, and prepends `@:` for write
(save-with-replace).  Shared by SEQ and PRG save paths.
`write_name_at` extracts just the `@:`-prefix logic for callers that
don't need the `,type,mode` tail.

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
