# disk.s — CBM File I/O

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/disk.s`](../../src/disk.s) | implementation |
| [`tests/integration/test_disk.py`](../../tests/integration/test_disk.py) | test contract — every export on the real PRG: with no drive (error codes, no file left open, no hang) and on a virtual 1541 (transfers, status, directory) |

**Test coverage** — Tier I on the real PRG (`test_disk.py`).  With no
drive, C64Emu models an empty serial bus, so every KERNAL OPEN / LOAD
on a serial device fails with "device not present": the error codes,
no file left open, the status read that must not hang.  With a
virtual 1541 on the bus
([testing.md § Virtual IEC drives](../testing.md#virtual-iec-drives))
every export runs its transfer through the KERNAL for real:
`disk_load_prg` (header and given address, file not found),
`disk_save_prg` (header + payload, `@:` replace), `disk_load_seq` /
`disk_save_seq` (bytes, line and byte counts, missing and empty
files), `floppy_read_status` / `floppy_status`, `list_directory`
(header, entries, blocks free, other devices, a D64 image).  The REPL
commands over them (`l`, `s`, `$`) are tested in
`test_repl_disk.py`.  Real-hardware specifics the model leaves out
(bus timing, the MEGA65 Open-KERNAL's channel I/O) remain VICE /
xmega65 walks.

## Interface

Every entry that takes a filename reads it from `disk_ptr` (ZP, set
by the caller; NUL-terminated PETSCII) and uses the hardcoded ZP
pointer `ptr` = `$FD`/`$FE` for it (§ Memory).  The device is
`cur_device` (zp.s) except for `list_directory`, which takes it in A.

### floppy_read_status
**In:** none
**Out:** the drive's command-channel status line in `fl_buf`: at most
30 characters, a trailing CR stripped, NUL-terminated.  Uses LFN 14 /
SA 15 and closes it.  `fl_buf` empty, nothing opened, when no drive
answers.
**Clobbers:** A, X, Y

The device is probed first (`LISTEN` + `UNLSN`, then `ST` bit 7):
`OPEN` with an empty name sends nothing on the bus, and the KERNAL's
`CHKIN` on a missing serial device waits forever in its talk
turnaround — a stock C64 hangs there.  With no drive the routine
returns at once, nothing opened.

### floppy_status
**In:** none
**Out:** `floppy_read_status`, then `fl_buf` printed as an info line
(`log_info`: `; <status>`).
**Clobbers:** A, X, Y and what `log_info` clobbers ([log.md](log.md))

### list_directory
**In:** A = device number
**Out:** the directory printed, one screen line per entry (each
cleared to the end of the row, then `newline`):
- header: `; ` then the disk name and id, from the first `"` on, in
  reverse video (RVS codes dropped, shifted spaces as spaces);
- files: `l "name,t"; N blocks` — a line the user can RETURN on to
  load the file;
- last: `; N blocks free.`

A key in the keyboard buffer between entries is taken: RUN/STOP ends
the listing early with `break` (no blocks-free line); any other key
is dropped and the listing goes on.  On a LOAD error nothing is
printed.
**Clobbers:** A, X, Y, `disk_ptr`, `_io_tmp`, `fl_buf`, the
workspace from `$0801` to the end of the loaded directory (~5 KB for
a full disk), and what `newline` clobbers

Uses KERNAL LOAD (SA 0) to read the directory into the workspace at
$0801, then walks the in-memory BASIC-style lines.  This approach
(vs OPEN+CHKIN+CHRIN) works on both the stock CBM KERNAL and the
MEGA65 Open-KERNAL (see MEGA65/open-roms#116, #117 for the
channel-I/O bugs).  The caller reads the drive status afterwards
(the REPL's `$` prints `floppy_read_status`'s line).

### disk_load_prg
**In:** A/X = load address, or 0 for the file's own; `disk_ptr` =
filename
**Out:** A/X = end address (KERNAL LOAD's end: the first byte after
the data), A = X = 0 on error.  LFN 1 is closed on both paths.
**Clobbers:** A, X, Y, `_io_tmp`, `ptr`

KERNAL SETLFS secondary address selects the load mode:
- addr ≠ 0 → SA=0: KERNAL loads to the address in X/Y (caller's addr).
- addr = 0 → SA=1: KERNAL loads to the PRG file's 2-byte header address.

### disk_save_prg
**In:** A/X = size in bytes; `disk_ptr` = filename; `_io_tmp` = start
address
**Out:** A = 0, X = 0 on success; A = 1, X = 0 if the OPEN failed.
Writes the 2-byte load-address header (the start address,
little-endian), then `size` bytes from the start address.
**Clobbers:** A, X, Y, `_io_tmp` (left past the last byte written),
`ptr`, `open_buf`

Uses OPEN + CHKOUT + CHROUT + CLOSE on LFN 2 / SA 2 (same flow as
`disk_save_seq`) with the name built by `build_open_str` for type
`p`: `@:` save-with-replace prefix and a `,p,w` suffix.  No KERNAL
SAVE call.

### disk_load_seq
**In:** A/X = insert callback; `disk_ptr` = filename
**Out:** A = 0, X = 0 on success.  A = 1, X = 0 if the OPEN failed,
READST reported an error (bits 0, 1 or 7) at the end, or the file
was empty.  After a successful OPEN, `disk_seq_bytes` = bytes read
and `disk_seq_lines` = CRs + 1.
**Clobbers:** A, X, Y, `ptr`, `open_buf`, `eof_flag`, `callback`, and
what the callback clobbers

The callback is called once per byte with the byte in A, before the
counters are updated; it may clobber A, X, Y and the KERNAL status
byte `$90`.  The loop runs until READST reports EOF (bit 6).  For a
missing file the drive sends one byte with error status; it reaches
the callback before the error is detected.

### disk_save_seq
**In:** A/X = read callback; `disk_ptr` = filename
**Out:** A = 0, X = 0 on success; A = 1, X = 0 if the OPEN failed.
After a successful OPEN, `disk_seq_bytes` / `disk_seq_lines` = bytes
and CRs + 1 written.
**Clobbers:** A, X, Y, `ptr`, `open_buf`, `callback`, and what the
callback clobbers

The callback returns a byte in A with X = 0, or X = $FF for the end
(the editor's returns A = X = $FF).  The file is opened with `@:`
and `,s,w`.

### Memory

**ZP** (allocation in [zp.md](zp.md)): `disk_ptr` (2, filename
pointer, set by the caller; `list_directory` also walks the loaded
directory with it), `_io_tmp` (2, cse_io's scratch: the load / save
address, `list_directory`'s reverse-video pointer), `cur_device`
(1, read).

**Hardcoded ZP:** `ptr` = `$FD`/`$FE` (2) — the filename pointer of
`str_setup` / `build_open_str`, written by every entry that takes a
filename.  It lies outside CSE's ZEROPAGE segment, in `$80`–`$FF`;
what user code may assume about that range is
[userland_contract.md § 2](../userland_contract.md)'s.

**BSS (67 bytes):**

| Variable | Size | Purpose |
|----------|------|---------|
| `disk_seq_bytes` | 2 | Bytes transferred (last SEQ op) |
| `disk_seq_lines` | 2 | Lines transferred (last SEQ op) |
| `fl_buf` | 32 | Drive status line / directory line buffer (exported) |
| `open_buf` | 28 | Filename build buffer for CBM open |
| `callback` | 2 | SEQ I/O function pointer |
| `eof_flag` | 1 | READST value after the last CHRIN of a SEQ read |

**Depends on:** log (puts_imm, log_info), screen (newline), cse_io
(io_putc, io_putdec, io_getc, io_kbhit, io_clear_eol, scr_lo,
scr_hi), strings (str_dname, str_dir_brk, str_blk_free, str_blk_pre,
str_blk_suf), zp (disk_ptr, _io_tmp, cur_device).  disk.s also
imports io_puts, io_puthex2, io_puthex4 and io_color without using
them (dead imports, [TODO.md § Code bugs](../TODO.md)).

## Design

All file I/O uses direct KERNAL calls: SETLFS, SETNAM, OPEN, CLOSE,
CHKIN, CHKOUT, CHRIN, CHROUT, LOAD, READST, CLRCHN.  SAVE is never
called (PRG save writes through CHROUT).

**Device number** comes from `cur_device`, a cross-module byte in
zp.s (default 8, set by the REPL's `$` command).

**CBM DOS open strings** are built by `build_open_str`, which takes
mode (`r`/`w` in A) and file type (`s` for SEQ, `p` for PRG in X).
It copies the filename into `open_buf`, prepends `@:` for write
(save-with-replace), and appends `,<type>,<mode>` — or only
`,<mode>` if the name already ends with `,s` / `,p`, or nothing if it
ends with `,r` / `,w`.  `write_name_at` is the `@:`-prefix half.
Shared by the SEQ paths and PRG save.

**SEQ I/O uses callbacks** so disk.s never depends on editor.s.  The
editor passes its insert function for loading and its read function
for saving.  Callbacks are stored in `callback` (2B BSS) and invoked
via `jmp (callback)`.

**No file left open.**  Every entry returns with none of its
logical files open, on success and on error.  The SEQ and PRG-save
paths open LFN 2 through `_disk_open_buf`; when OPEN fails there
(device not present), the KERNAL has already entered LFN 2 in its
file table, so `_disk_open_buf` closes LFN 2 again before returning
C = 1 — otherwise every later OPEN 2 would fail with "file open".
`disk_load_prg` (KERNAL LOAD, LFN 1) closes LFN 1 on both paths.

**SEQ read loop:** After each CHRIN, READST is called immediately
(before the callback) to capture the EOF flag — the callback may
clobber the KERNAL status byte at $90.

**Error channel:** disk.s does not read the drive's error channel
after a transfer — opening channel 15 between OPEN and CHKIN
disrupts the serial bus channel.  The caller does it: the REPL's
`l` / `s` end in `disk_done` → `floppy_status`, and `$` prints
`floppy_read_status`'s line.  That status line is also the only
report of a write error after a successful OPEN.

## Caveats

- PRG load uses KERNAL LOAD; PRG save and both SEQ paths use
  OPEN / CHKOUT or CHKIN / CHROUT or CHRIN / CLOSE.
- Saves use the `@:` prefix: an existing file is replaced silently,
  no "file exists" error.
- Write errors after a successful OPEN are not detected: the save
  entries return 0 (see § Design, Error channel).
- An empty SEQ file (0 bytes read) is treated as an error by
  `disk_load_seq` (returns 1).
- `build_open_str` uses `open_buf` (28B BSS) as scratch.
- Mutable locals live in CODE, not BSS: `write_name_at` (`@nlen`),
  `build_open_str` (`@mode`, `@type`, `@nlen`), `list_directory`
  (ten bytes: `@is_first` … `@fn_tmp`) and `disk_save_prg`
  (`@size_lo`, `@size_hi`).  They block a ROM build
  (memory_design.md § Design Principles).
