# cse_io.s — Screen I/O and Cursor Management

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/cse_io.s`](../../src/cse_io.s) | implementation |
| [`tests/unit/test_cse_io.py`](../../tests/unit/test_cse_io.py) | test contract |
| [`tests/integration/test_m65_terminal.py`](../../tests/integration/test_m65_terminal.py) | tier-I tests on the m65 PRG (P2 T3 T4): `io_geometry` per mode and under a window, output in the mode's bank with the clamp, `io_sync`, the key lookahead and flush |

## Interface

cse_io.s provides screen output, keyboard input, and cursor management
for CSE.  All output goes to screen RAM at $0400; colour RAM is never
written here.  Cursor position uses KERNAL locations $D3 (column)
and $D6 (row).  Single arguments in A or A/X.

**On m65** ([platform_layer.md § Terminal](../platform_layer.md#terminal),
§ Display): output goes to the screen of the current mode — `0.0800`,
or `4.0800` in 80 × 50 — through the far pointer `_io_scr` with the
screen's bank; the cursor is CSE's own `IO_CX` / `IO_CY` in its base
page (no KERNAL cell), told to the KERNAL by `io_sync` (`PLOT`).
`io_init` also runs `io_geometry`.  Every width and height is the
run-time geometry (`WIDTH`, `LAST_COL`, `HEIGHT`, `LAST_ROW`): `io_putc`
clamps at the current last column, `io_clear_eol` clears to it.

### io_geometry (m65)
**In:** none.  **Out:** `HOME HOME` sent (the full screen is the
editor's window); `scr_width`, `scr_height`, `scr_last_col`,
`scr_last_row`, `scr_ed_rows`, `scr_size` (width × height), `scr_bank`
and the tables `scr_lo` / `scr_hi` (one entry per row, stride the
width) set from `SCRORG` and `$D062` (A1: X / Y are the right column
and bottom row).  `scr_width` and `scr_last_col` are base-page cells
(zp.s), the rest BSS here.  **Clobbers:** A, X, Y, Z.  Called by `io_init` and
`screen_mode_set`.  On c64 there is no routine: the geometry is
constants and the tables are RODATA.

### io_kbhit / io_getc on m65
`io_kbhit`: a key waiting in the one-key lookahead `io_key` (CSE's
base page), or, if it is empty, `KCALL GETIN` into it — so a peek
sees all three of `GETIN`'s sources (A1).  `io_getc` takes the
lookahead first, then `GETIN`.  `IO_KBD_FLUSH` empties the lookahead
and drains `GETIN` to 0.  `io_kbhit` returns Z from A (X = 0 is
loaded first), as `IO_KBHIT`'s c64 body `lda $C6` does — main_loop's
`beq @wait` tests it.

### ZP Variables

Allocated in zp.s ([zp.md](zp.md)).

| Name | Size | Purpose |
|------|------|---------|
| `_io_tmp` | 2 | Scratch: string pointer (`io_puts`), dividend (`io_utoa`), repeat counter (`io_repc`) |
| `_io_scr` | 2 (m65: 4, far) | Screen row pointer, re-derived by `_io_scr_setup` before every use (screen.s reuses it as `scroll_up`'s destination pointer); on m65 its bank is the screen's (`FAR_BANK_SCREEN`) |

### BSS Variables

| Name | Size | Purpose | Consumers |
|------|------|---------|-----------|
| `dec_buf` | 6 | `io_utoa` output: 5 PETSCII digits + NUL at [5] | **Exported** — `io_putdec` / `io_putdec_pd` print from it; asm_src.s reads it directly after `io_utoa` (the `.bas` SYS line). |

### KERNAL Locations Used

| Address | Name | Read/Write | Purpose |
|---------|------|-----------|---------|
| $D3 | CUR_COL | R/W | Cursor column (0–39) |
| $D6 | CUR_ROW | R/W | Cursor row (0–24) |
| $D1/$D2 | SCR_PTR | — | NOT used by cse_io; updated by io_sync via KERNAL PLOT |
| $F3/$F4 | COL_PTR | — | NOT used by cse_io; updated by io_sync via KERNAL PLOT |
| $C6 | NDX | R | Keyboard buffer count (`io_kbhit`) |
| $CC | BLNSW | W | Set to 1 (KERNAL cursor blink off) by `io_init` |

### RODATA

| Name | Size | Contents | Consumers |
|------|------|---------|-----------|
| `scr_lo[25]` | 25 | Low bytes of $0400 + row×40 for rows 0–24 | **Exported** — imported by screen.s, editor.s, log.s, disk.s, main.s and repl.s. |
| `scr_hi[25]` | 25 | High bytes of same | **Exported** — same importers as `scr_lo`. |
| `hex_tab[16]` | 16 | Screen codes for hex digits: $30–$39, $01–$06 | Internal — used by io_puthex2.  Not exported. |
| `dec_pow_lo[5]` | 5 | Powers of 10: <1, <10, <100, <1000, <10000 | **Exported**; only `io_utoa` uses them (asm_src.s and repl.s import them without using them). |
| `dec_pow_hi[5]` | 5 | Powers of 10: >1, >10, >100, >1000, >10000 | **Exported** — as `dec_pow_lo`. |

### io_init
**In:** none
**Out:** `$CC` = 1 (KERNAL cursor blink off) — the invariant every
IRQ-safety claim below rests on.
**Clobbers:** A

Called by `main.s` cold init and `hw_reinit_body` (`cse_recover`).
`hygiene_after_userland` (repl.s) re-asserts `$CC` = 1 after user
code.  Clearing and colouring the screen is screen.s's job
(`reset_screen`, `restore_colors`).

### pet_to_scr

**In:** A = PETSCII byte
**Out:** A = screen code
**Clobbers:** flags only

Pure conversion function.  See § Character Encoding Reference for
the full 8-row mapping.

### scr_to_pet

**In:** A = screen code (bit 7 must be stripped by caller)
**Out:** A = PETSCII byte
**Clobbers:** flags only

Pure conversion function, used by repl.s's `read_line`:
$00–$1F → $40–$5F (`ORA #$40`), $20–$3F identity,
$40–$5F → $C0–$DF (`ORA #$80`), $60–$7F identity.

### io_putc

**In:** A = PETSCII character
**Precondition:** CUR_ROW and CUR_COL are valid (0–24, 0–39)
**Clobbers:** A, X, Y, `_io_scr`

**Behavior:**
1. Convert PETSCII to a screen code (`pet_to_scr`)
2. Compute screen address: `addr = scr_lo[CUR_ROW] | (scr_hi[CUR_ROW] << 8)`
3. Write screen code to `addr + CUR_COL`
4. Increment CUR_COL (clamped at 39: if CUR_COL was 39, stays 39)

**Postconditions:**
- Exactly 1 byte written to screen RAM at row CUR_ROW, column (original CUR_COL)
- CUR_COL = min(original_CUR_COL + 1, 39)
- CUR_ROW unchanged
- `_io_tmp` preserved (safe to call from io_puts)

**Does NOT:**
- Write to color RAM
- Call io_sync
- Modify CUR_ROW
- Scroll the screen

### io_puts

**In:** A/X = pointer to NUL-terminated PETSCII string
**Precondition:** CUR_ROW and CUR_COL are valid
**Clobbers:** A, X, Y, `_io_tmp`, `_io_scr`

**Behavior:** For each byte until NUL: `io_putc(byte)`.  On m65 the
string is in CSE's view (a CPU address under the CSE map): `_io_tmp`'s
bank is set to `BANK_CSE` each call.

**Postconditions:**
- N bytes written to screen RAM starting at (CUR_ROW, original_CUR_COL)
- CUR_COL = min(original_CUR_COL + strlen(s), 39) — characters past
  col 39 overwrite col 39
- CUR_ROW unchanged

### io_puthex2

**In:** A = byte value
**Clobbers:** A, X, Y, `_io_scr`

**Behavior:**
1. Compute screen address from scr_lo/scr_hi[CUR_ROW]
2. Write hex_tab[v >> 4] at CUR_COL
3. Write hex_tab[v & $0F] at CUR_COL + 1
4. Advance CUR_COL by 2 (clamped at 39)

**Output screen codes:** hex_tab values: $30–$39 for 0–9, $01–$06
for a–f (lowercase).

### io_puthex4

**In:** A = lo byte, X = hi byte
**Clobbers:** A, X, Y, `_io_scr`

**Behavior:** `io_puthex2(hi)`, then `io_puthex2(lo)`.  Writes 4 hex
digits, advances CUR_COL by 4 (clamped at 39).

### io_repc

**In:** A = PETSCII character, X = repeat count (0 = no-op)
**Out:** A unchanged
**Clobbers:** X, Y, `_io_tmp`, `_io_scr`

**Behavior:** Call `io_putc(A)` X times.  If X=0, returns immediately.

### io_utoa

**In:** A = lo byte, X = hi byte.  Carry flag selects mode:
- CLC → skip leading zeros, return offset to first significant digit
- SEC → replace leading zeros with spaces, return 0
**Out:** `dec_buf` = 5 PETSCII characters + NUL at [5]; A = offset
into `dec_buf` (CLC: 0–4, SEC: always 0)
**Clobbers:** A, X, Y, `_io_tmp`, flags

**Behavior:**
1. Convert A/X to 5 PETSCII digits in dec_buf[0..4]
2. Replace leading '0's with ' ' (the last digit always stays)
3. Return the offset in A

`dec_buf[5]` holds the buffer position during the conversion and
gets its NUL at the end — callers see the NUL, never the scratch.

### io_putdec

**In:** A = lo byte, X = hi byte
**Clobbers:** A, X, Y, `_io_tmp`, `_io_scr`

**Behavior:** CLC + io_utoa + io_puts.  Prints decimal at cursor,
leading zeros suppressed ("0"–"65535").

### io_putdec_pd

**In:** A = lo byte, X = hi byte.  Caller sets C flag:
- CLC → zero-suppressed (same as io_putdec)
- SEC → space-padded 5-digit field ("    0"–"65535")
**Clobbers:** A, X, Y, `_io_tmp`, `_io_scr`

**Behavior:** io_utoa + io_puts.  Entry point between CLC and
jsr io_utoa in io_putdec — caller's carry passes through.

### io_clear_eol

**Precondition:** CUR_ROW and CUR_COL are valid
**Clobbers:** A, X, Y, `_io_scr`

**Behavior:**
1. Compute screen address from scr_lo/scr_hi[CUR_ROW]
2. Fill screen RAM from CUR_COL to column 39 with $20 (space)

**Postconditions:**
- Columns CUR_COL through 39 of current row are $20
- CUR_COL unchanged
- CUR_ROW unchanged

### io_getc

**Out:** A = PETSCII key code (nonzero), X = 0
**Clobbers:** Y (KERNAL GETIN)

**Behavior:** Call KERNAL GETIN ($FFE4) in a loop until nonzero.
Returns raw KERNAL codes (RETURN = $0D, RUN/STOP = $03, SHIFT+SPACE
= $A0).

### io_kbhit

**Out:** A = $C6 (keyboard buffer count), X = 0; Z set from X (test A)

**Behavior:** Return the value of $C6.  0 = no key pending,
nonzero = keys waiting.

### io_sync

**In:** CUR_ROW, CUR_COL
**Clobbers:** A, X, Y (KERNAL PLOT)

**Behavior:** Call KERNAL PLOT ($FFF0) with CLC, X=CUR_ROW, Y=CUR_COL.
This updates $D1/$D2 (screen line pointer) and $F3/$F4 (color
line pointer) to match the current cursor position.

**When to call:** After modifying CUR_ROW ($D6).  Not needed after
modifying only CUR_COL ($D3).

**Note:** cse_io's output functions (io_putc, io_puts, io_puthex*,
io_putdec, io_clear_eol) do NOT use $D1/$D2.  They compute the
screen address directly from scr_lo/scr_hi[CUR_ROW].  io_sync exists
for the KERNAL's benefit (screen editor state, and user code that
prints with CHROUT).

### io_blip

**Out:** a short triangle pulse (~0.2 ms) on SID voice 1; SID volume
($D418) left at 10.
**Clobbers:** A, X.  Preserves Y.

Audible feedback for refused input.  Callers: the editor
(`ed_handle_key`) and the REPL key handling in main.s (line cap,
backspace into the left wall, cursor at a screen edge).  The volume
byte stays set after the first call so later blips skip the
re-init; user code that wants its own SID setup re-initialises it.

### _io_scr_setup

**In:** `CUR_ROW` ($D6)
**Out:** `_io_scr` / `_io_scr+1` = `scr_lo[CUR_ROW] | (scr_hi[CUR_ROW] << 8)`
**Clobbers:** A, X.  Preserves Y.

Populates the `_io_scr` ZP pointer with the screen-RAM address of
the current row.  The leading underscore marks it as a shared
internal helper rather than a user-facing API entry point — it is
exported because screen.s (`cursor_show`) uses it instead of
duplicating the two-byte load.  The io_putc / io_puthex* /
io_clear_eol family calls it before every write.

### Cursor Position

Cursor position is read/written directly via KERNAL ZP:
- `$D3` (CUR_COL) — column 0–39
- `$D6` (CUR_ROW) — row 0–24

Call `io_sync` after changing CUR_ROW to update line pointers.

**Depends on:** KERNAL (GETIN $FFE4, PLOT $FFF0), zp (`_io_tmp`,
`_io_scr`)

## Design

### Character Encoding Reference

CSE uses the C64 **lower/upper charset** (VIC $D018 bit 1 = 1).
Three encodings interact: PETSCII (software), screen codes (VIC
chip), and keyboard input (KERNAL GETIN).  Getting these wrong
causes silent case-flipping bugs.  This section is the single
source of truth.

#### PETSCII (how software stores text)

KERNAL GETIN returns PETSCII.  All CSE strings, buffers, and the
assembler/expression parser work in PETSCII.  Think in 32-byte
chunks — never sub-ranges.

| PETSCII | Contents |
|---------|----------|
| $00–$1F | control codes |
| $20–$3F | space, digits, punctuation |
| $40–$5F | **lowercase** (letters a–z at $41–$5A, plus @[]↑← ) |
| $60–$7F | **uppercase** (letters A–Z at $61–$7A, plus graphics) ← avoid |
| $80–$9F | (control codes, shifted) |
| $A0–$BF | shifted graphics / special chars ← avoid |
| $C0–$DF | **uppercase** (duplicate of $60–$7F) ← canonical |
| $E0–$FF | shifted graphics (duplicate of $A0–$BF) ← canonical |

**The $40–$5F = lowercase convention is the opposite of ASCII.**
PETSCII $41 is lowercase `a`, not uppercase `A`.  This is the
single most common source of confusion.

#### Duplicate ranges and canonical usage

$60–$7F and $C0–$DF produce identical screencodes ($40–$5F).
$A0–$BF and $E0–$FF produce identical screencodes ($60–$7F).

CSE uses the $C0–$FF range as canonical for uppercase/shifted
content because that's what the KERNAL keyboard input layer and
ca65 `-t c64` character literals produce:

| Screencodes | Canonical PETSCII | Avoid | Why |
|-------------|-------------------|-------|-----|
| $40–$5F | **$C0–$DF** | $60–$7F | KERNAL GETIN returns $C1–$DA for shifted letters; `'A'` (ca65) = $C1; `scr_to_pet` produces $C0–$DF |
| $60–$7F | **$E0–$FF** | $A0–$BF | Matches the shifted-uppercase convention |

**Rule:** uppercase letters everywhere in CSE (string constants,
generated output, keyboard input, screen-read input) live in
$C0–$DF.  Case-insensitive comparators should still tolerate both.
Exceptions to the canonical ranges: SHIFT+SPACE (tab) is $A0, and
`scr_to_pet` returns graphics screen codes $60–$7F as PETSCII
$60–$7F (identity) — see § Screen Code → PETSCII.

#### Screen codes (what VIC reads from $0400)

In the lower/upper charset:

| Screen code | Displays as |
|-------------|-------------|
| $00–$1F | a–z (lowercase) |
| $20–$3F | space, digits, punctuation |
| $40–$5F | A–Z (uppercase) |
| $60–$7F | graphics |
| $80–$FF | reverse-video versions of $00–$7F |

#### PETSCII → Screen Code (io_putc)

| PETSCII range | Screen code | Rule | Notes |
|---------------|-------------|------|-------|
| $00–$1F | $80–$9F | ORA #$80 | reverse-video control chars |
| $20–$3F | $20–$3F | identity | space, digits, punctuation |
| $40–$5F | $00–$1F | A − $40 | **lowercase** a–z ($41→$01) |
| $60–$7F | $40–$5F | A − $20 | **uppercase** A–Z ($61→$41) ← avoid |
| $80–$9F | $80–$9F | identity | reverse video |
| $A0–$BF | $60–$7F | A − $40 | graphics/specials ($A0→$60) ← avoid |
| $C0–$FF | $40–$7F | A − $80 | **uppercase** + graphics ($C1→$41, $E0→$60) ← canonical |

The $C0–$FF row is the canonical uppercase/shifted range.  A single
operation (A − $80) covers both the $60–$7F (uppercase letters)
and $A0–$BF (graphics) duplications.

#### Screen Code → PETSCII (scr_to_pet, used by read_line)

`read_line` strips bit 7 (`AND #$7F`) to remove reverse video,
then calls `scr_to_pet`:

| Screen code (after AND #$7F) | PETSCII | Rule |
|------------------------------|---------|------|
| $00–$1F | $40–$5F | ORA #$40 (lowercase a–z) |
| $20–$3F | $20–$3F | identity (digits, punctuation) |
| $40–$5F | $C0–$DF | ORA #$80 (uppercase A–Z) |
| $60–$7F | $60–$7F | identity (graphics) |

Uppercase screen codes ($40–$5F) map to the $C0–$DF PETSCII range.
This matches both the KERNAL keyboard input encoding (GETIN returns
$C1–$DA for shifted letters) and ca65 `-t c64` character literals
(`'B'` = $C2).  The round-trip through screen RAM **preserves case**:
lowercase `b` (screen $02) → PETSCII $42, uppercase `B` (screen
$42) → PETSCII $C2.

The round trip is **not closed for graphics**: screen $60–$7F reads
back as PETSCII $60–$7F, which `pet_to_scr` displays as $40–$5F
(uppercase letters).  Reverse video is lost by `read_line`'s
`AND #$7F`.

#### Where $C0–$DF uppercase PETSCII appears

$C0–$DF is the canonical uppercase range in CSE.  It appears from
two sources:

- **KERNAL GETIN** — raw keyboard input returns $C1–$DA for
  shifted letters.
- **`scr_to_pet`** — screen code $40–$5F (uppercase on screen)
  maps to $C0–$DF via ORA #$80.

Code that needs case-insensitive comparison or display folds it:

- `fold_char` in `symtab.s` — folds $C0–$DF → $40–$5F
- Label scanner in `expr.s` — folds $C0–$DF in-place
- `fold_block` / `fold_char_a` in `asm_src.s` — folds $C0–$DF for mnemonics
- `_hex_val` in `repl.s` — accepts $C0–$DF for hex A–F
- `editor.s` renderer — maps $C1–$DA → screen codes $41–$5A

### IRQ Safety

**With $CC=1 (KERNAL cursor disabled), cse_io is fully IRQ-safe.**

The KERNAL IRQ at $EA31 with $CC=1 only does:
- Jiffy clock increment ($A0-$A2)
- Keyboard scan (CIA1 → buffer at $0277, count at $C6)
- STOP key check (CIA1)

It does NOT touch: screen RAM, color RAM, $D1/$D2/$D3/$D6/$F3/$F4.

Therefore:
- io_putc, io_repc, io_puts, io_puthex2/4, io_putdec, io_clear_eol: **no SEI needed**
- io_sync (KERNAL PLOT): **no SEI needed** (PLOT is reentrant)
- cursor_show/cursor_hide: **no SEI needed** (IRQ doesn't touch screen RAM)
- scroll_up (memmove screen RAM): **SEI optional** — prevents VIC-II from
  reading partially scrolled data (cosmetic: avoids 1-frame visual tear)

**If $CC is ever set to 0 (cursor enabled), all bets are off** — the KERNAL
IRQ would read/write screen RAM at $D1+$D3, conflicting with cse_io output.
CSE keeps $CC=1 at all times and manages the cursor via cursor_show/hide.

## Caveats

- `io_init` must run before any output (`$CC` = 1).  Never re-enable
  the KERNAL cursor.
- Call `io_sync` after changing `CUR_ROW`.
- Output never wraps or scrolls: everything past col 39 lands on
  col 39.  Line breaks are screen.s's `newline`.
- `io_getc` and `io_kbhit` return X = 0, so Z reflects X — test A.
