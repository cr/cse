# disk.s — CBM File I/O

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/disk.s`](../../src/disk.s) | implementation |
| [`tests/integration/test_disk.py`](../../tests/integration/test_disk.py) | test contract — every export on the real PRG: with no drive (error codes, no file left open, no hang) and on a virtual 1541 (transfers, status, directory) |
| [`tests/integration/test_m65_disk.py`](../../tests/integration/test_m65_disk.py) | test contract — the same on the m65 PRG, on IEC unit 10 (§ On m65): `$` into `DIR_BUF` with the program region untouched, the header in each mode's bank, PRG / SEQ load and save, `s` / `l` typed |

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
the data), A = X = 0 on error; `_io_tmp` = start address (where the
file landed).  LFN 1 is closed on both paths.  `fl_buf` = the drive's
status.
**Clobbers:** A, X, Y, `ptr`

The load itself is KERNAL `LOAD` with SA=0, to a known address:
- addr ≠ 0 → that address.
- addr = 0 → the file's 2-byte header address, read first through
  `OPEN 2` + two `CHRIN`s on the same name (SA=1 would load there too,
  but leave the start unknown to the caller).  A file with nothing
  after its header is an error — `LOAD` would wait for data forever.

### disk_save_prg
**In:** A/X = size in bytes; `disk_ptr` = filename; `_io_tmp` = start
address
**Out:** A = 0, X = 0, Z = 1 on success; A = 1, X = 0, Z = 0 if the
OPEN failed or the drive refused the file (its status code is not
`0x`: write protect, disk full).  `fl_buf` = the drive's status.
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
and `disk_seq_lines` = CRs + 1.  `fl_buf` = the drive's status.
**Clobbers:** A, X, Y, `ptr`, `open_buf`, `eof_flag`, `callback`, and
what the callback clobbers

The callback is called once per byte with the byte in A, before the
counters are updated; it may clobber A, X, Y and the KERNAL status
byte `$90`.  The loop runs until READST reports EOF (bit 6).  For a
missing file the drive sends one byte with error status; it reaches
the callback before the error is detected.

### disk_save_seq
**In:** A/X = read callback; `disk_ptr` = filename
**Out:** A = 0, X = 0, Z = 1 on success; A = 1, X = 0, Z = 0 if the
OPEN failed or the drive refused the file (status code not `0x`).
After a successful OPEN, `disk_seq_bytes` / `disk_seq_lines` = bytes
and CRs + 1 written.  `fl_buf` = the drive's status.
**Clobbers:** A, X, Y, `ptr`, `open_buf`, `callback`, and what the
callback clobbers

The callback returns a byte in A with X = 0, or X = $FF for the end
(the editor's returns A = X = $FF).  The file is opened with `@:`
and `,s,w`.

### On m65

The same entries with the same contracts, on the MEGA65 KERNAL's
jump table ([platform_layer.md](../platform_layer.md) § Constants,
§ Disk bank).  What differs:

- **The units.**  Units 8 and 9 are usually CBDOS's (the internal
  drive or a mounted D81 image; the book, 6-3), every other unit the
  IEC bus's.  disk.s does not tell them apart: the KERNAL routes each
  call.  Tested: CBDOS units in xmega65 (Tier X, `cse.d81` on unit
  8), IEC units in M65Emu (Tier I, a virtual drive on unit 10 —
  [testing.md](../testing.md) § The m65 PRG on M65Emu).
- **`ST`.**  No KERNAL cell is read or written
  ([platform_layer.md](../platform_layer.md) § Constants, *KERNAL
  cells*): the status comes from `READSS` (`$FFB7`, as `READST`).
  `floppy_read_status`'s device probe is `LISTEN` · `UNLSN` ·
  `READSS`, bit 7 = device not present; the C64 body clears `ST`
  first, which the m65 body cannot and need not do — `LISTEN` starts
  a new operation, and `READSS` reports it.
- **The filename pointer** `ptr` is `disk_local_ptr`, a 2-byte cell
  of CSE's base page (not `$FD`): it only ever reads filenames in
  CSE's own view, `(ptr),y`, so it needs no bank.
- **The directory buffer.**  `list_directory` loads `$` into
  `DIR_BUF`, `2.D000–2.FFFF` (CSE's 12 K reserve in the source bank —
  [memory_design.md](../memory_design.md) § Memory Map — m65), not
  into the user's program region: a full D81 directory (296 entries)
  is under 10 K.  `PLAT_SETBNK DIR_BANK` gives `LOAD` that bank; the
  walk reads it through `disk_ptr` with `FAR_BANK disk_ptr, DIR_BANK`.
  So `$` leaves the user's memory alone on m65 (on c64 it clobbers
  the workspace from `$0801`).
- **The pointer banks.**  `disk_save_prg` reads the program through
  `_io_tmp` as a user address (`FAR_USER _io_tmp`);
  `list_directory`'s reverse-video cell (`@putc_inv`) is a screen
  pointer (`FAR_BANK_SCREEN _io_tmp`).
- **The load target** of a PRG `l` is the user's bank 0
  (`PLAT_SETBNK`'s default `BANK_USER`), a SEQ `l` goes through
  `CHRIN` into the source region (gap_buffer.s), unchanged.

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
[userland_contract.md § 2](../userland_contract.md)'s.  On m65 it is
`disk_local_ptr` in CSE's own base page (zp.s), not a hardcoded
address (§ On m65).

**BSS (84 bytes):**

| Variable | Size | Purpose |
|----------|------|---------|
| `disk_seq_bytes` | 2 | Bytes transferred (last SEQ op) |
| `disk_seq_lines` | 2 | Lines transferred (last SEQ op) |
| `fl_buf` | 32 | Drive status line (left by every transfer) / directory line buffer (exported) |
| `open_buf` | 28 | Filename build buffer for CBM open |
| `callback` | 2 | SEQ I/O function pointer |
| `eof_flag` | 1 | READST value after the last CHRIN of a SEQ read |
| proc-local `@` scratch | 17 | `str_setup`, `build_open_str`, `list_directory`, `disk_save_prg` locals — in BSS, so disk.s's CODE stays read-only |

**Depends on:** log (puts_imm, log_info), screen (newline), cse_io
(io_putc, io_putdec, io_getc, io_kbhit, io_clear_eol, scr_lo,
scr_hi), strings (str_dname, str_dir_brk, str_blk_free, str_blk_pre,
str_blk_suf), zp (disk_ptr, _io_tmp, cur_device).

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

**Error channel:** Every transfer (`disk_load_prg`, `disk_save_prg`,
`disk_load_seq`, `disk_save_seq`) ends, after its CLOSE, by reading
the drive's error channel (channel 15) into `fl_buf`, on success and
on error — empty when no drive answers.  (Never between OPEN and
CHKIN: that disrupts the serial bus channel.)  The drive clears its
message once it is read, so this is the only read: a save checks the
code there (a drive can accept the OPEN and still refuse the file —
write protect, disk full — which ST does not show), and the REPL
prints `fl_buf` after `l` / `s` without reading again; `$` prints
`floppy_read_status`'s line.

## Caveats

- PRG load uses KERNAL LOAD (after an OPEN / CHKIN / CHRIN read of
  the header when no address is given); PRG save and both SEQ paths
  use OPEN / CHKOUT or CHKIN / CHROUT or CHRIN / CLOSE.
- Saves use the `@:` prefix: an existing file is replaced silently,
  no "file exists" error.
- A drive's refusal after a successful OPEN is detected by its
  status code after CLOSE (§ Design, Error channel), not as it
  happens: the bytes are sent first.
- An empty SEQ file (0 bytes read) is treated as an error by
  `disk_load_seq` (returns 1).
- `build_open_str` uses `open_buf` (28B BSS) as scratch.
- Mutable locals live in CODE, not BSS: `write_name_at` (`@nlen`),
  `build_open_str` (`@mode`, `@type`, `@nlen`), `list_directory`
  (ten bytes: `@is_first` … `@fn_tmp`) and `disk_save_prg`
  (`@size_lo`, `@size_hi`).  They block a ROM build
  (memory_design.md § Design Principles).
