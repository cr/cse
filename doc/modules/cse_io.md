# cse_io.s — Screen I/O and Cursor Management

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/cse_io.s`](../../src/cse_io.s) | implementation |
| [`tests/unit/test_cse_io.py`](../../tests/unit/test_cse_io.py) | test contract |

## Interface

cse_io.s provides screen output, keyboard input, and cursor management
for CSE.  All output goes to screen RAM
at $0400.  Cursor position uses KERNAL locations $D3 (column) and
$D6 (row).

### ZP Variables

| Address | Name | Size | Purpose |
|---------|------|------|---------|
| (alloc) | _io_tmp | 2 | Scratch: string pointer (io_puts), dividend (io_putdec) |
| (alloc) | _io_scr | 2 | Screen row pointer (computed per write call) |

### BSS Variables

| Name | Size | Purpose | Consumers |
|------|------|---------|-----------|
| io_color | 1 | Text color for screen clears | **Exported** — written by screen.s (theme_init) and read by screen.s/disk.s when filling color RAM.  cse_io itself neither reads nor writes it. |
| dec_buf | 6 | io_utoa output: 5-digit PETSCII + permanent NUL at [5] | **Exported** — io_putdec / io_putdec_pd produce output here; callers may read it directly after io_utoa returns (e.g. inspecting the five-digit field before output). |

### KERNAL Locations Used

| Address | Name | Read/Write | Purpose |
|---------|------|-----------|---------|
| $D3 | CUR_COL | R/W | Cursor column (0–39).  Aliased as `io_cx` in code. |
| $D6 | CUR_ROW | R/W | Cursor row (0–24).  Aliased as `io_cy` in code. |
| $D1/$D2 | SCR_PTR | — | NOT used by cse_io; updated by io_sync via KERNAL PLOT |
| $F3/$F4 | COL_PTR | — | NOT used by cse_io; updated by io_sync via KERNAL PLOT |
| $C6 | KEY_COUNT | R | Keyboard buffer count (io_kbhit) |
| $CC | CURS_FLAG | — | Set to 1 by io_init at startup; not modified afterward |

### RODATA

| Name | Size | Contents | Consumers |
|------|------|---------|-----------|
| scr_lo[25] | 25 | Low bytes of $0400 + row×40 for rows 0–24 | **Exported** — imported by screen.s (scroll, clear) and log.s (info_line_head snapshot row pointer). |
| scr_hi[25] | 25 | High bytes of same | **Exported** — same callers as scr_lo. |
| hex_tab[16] | 16 | Screen codes for hex digits: $30–$39, $01–$06 | Internal — used by io_puthex2.  Not exported. |
| dec_pow_lo[5] | 5 | Powers of 10: <1, <10, <100, <1000, <10000 | **Exported** — asm_src.s and repl.s reuse them for their own decimal-conversion paths. |
| dec_pow_hi[5] | 5 | Powers of 10: >1, >10, >100, >1000, >10000 | **Exported** — same callers as dec_pow_lo. |

### pet_to_scr

**Input:** A = PETSCII byte
**Output:** A = screen code
**Clobbers:** flags only

Pure conversion function.  See § Character Encoding Reference for
the full 8-row mapping.  Extracted from io_putc for testability.

### scr_to_pet

**Input:** A = screen code (bit 7 must be stripped by caller)
**Output:** A = PETSCII byte
**Clobbers:** flags only

Pure conversion function.  $00–$1F → $40–$5F (A + $40),
$20–$7F → identity.  Extracted from read_line for testability.

### io_putc

**Input:** A = PETSCII character
**Precondition:** io_cy and io_cx are valid (0–24, 0–39)

**Behavior:**
1. Convert PETSCII `ch` to screen code using the table above
2. Compute screen address: `addr = scr_lo[io_cy] | (scr_hi[io_cy] << 8)`
3. Write screen code to `addr + io_cx`
4. Increment io_cx (clamped at 39: if io_cx was 39, stays 39)

**Postconditions:**
- Exactly 1 byte written to screen RAM at row io_cy, column (original io_cx)
- io_cx = min(original_io_cx + 1, 39)
- io_cy unchanged
- _io_scr clobbered (used internally)
- _io_tmp preserved (safe to call from io_puts)

**Does NOT:**
- Write to color RAM
- Call io_sync
- Modify io_cy
- Scroll the screen

### io_puts

**Input:** A/X = pointer to NUL-terminated PETSCII string
**Precondition:** io_cy and io_cx are valid

**Behavior:**
For each byte in `s` until NUL: call io_putc(byte).

**Postconditions:**
- N bytes written to screen RAM starting at (io_cy, original_io_cx)
- io_cx = min(original_io_cx + strlen(s), 39)
- io_cy unchanged
- _io_tmp clobbered (used for string pointer)

### io_puthex2

**Input:** A = byte value

**Behavior:**
1. Compute screen address from scr_lo/scr_hi[io_cy]
2. Write hex_tab[v >> 4] at io_cx
3. Write hex_tab[v & $0F] at io_cx + 1
4. Advance io_cx by 2 (clamped at 39)

**Output screen codes:** hex_tab values: $30–$39 for 0–9, $01–$06 for A–F

### io_puthex4

**Input:** A = lo byte, X = hi byte

**Behavior:** Call io_puthex2(hi), then io_puthex2(lo).
Writes 4 hex digits, advances io_cx by 4.

### io_repc

**Input:** A = PETSCII character, X = repeat count (0 = no-op)

**Behavior:** Call io_putc(A) X times.  If X=0, returns immediately.

**Clobbers:** X, Y, _io_tmp

### io_utoa

**Input:** A = lo byte, X = hi byte.  Carry flag selects mode:
- CLC → skip leading zeros, return offset to first significant digit
- SEC → replace leading zeros with spaces, return 0

**Behavior:**
1. Convert A/X to 5 PETSCII digits in dec_buf[0..4]
2. Scan leading '0's: replace with ' ' (space)
3. Return offset in A (CLC: 0–4, SEC: always 0)

dec_buf[5] is a permanent NUL (BSS-zeroed, never written by io_utoa).
io_utoa only writes positions 0–4.

**Clobbers:** X, Y, _io_tmp, flags

### io_putdec

**Input:** A = lo byte, X = hi byte

**Behavior:** CLC + io_utoa + io_puts.  Prints decimal at cursor,
leading zeros suppressed ("0"–"65535").

### io_putdec_pd

**Input:** A = lo byte, X = hi byte.  Caller sets C flag:
- CLC → zero-suppressed (same as io_putdec)
- SEC → space-padded 5-digit field ("    0"–"65535")

**Behavior:** io_utoa + io_puts.  Entry point between CLC and
jsr io_utoa in io_putdec — caller's carry passes through.

### io_clear_eol

**Precondition:** io_cy and io_cx are valid

**Behavior:**
1. Compute screen address from scr_lo/scr_hi[io_cy]
2. Fill screen RAM from io_cx to column 39 with $20 (space)

**Postconditions:**
- Columns io_cx through 39 of current row are $20
- io_cx unchanged
- io_cy unchanged

### io_getc

**Output:** A = PETSCII key code (nonzero)

**Behavior:** Call KERNAL GETIN ($FFE4) in a loop until nonzero.
Return the PETSCII key code.

**Note:** Returns raw KERNAL codes.  RETURN = $0D.

### io_kbhit

**Output:** A = $C6 (keyboard buffer count)

**Behavior:** Return the value of $C6.  0 = no key pending,
nonzero = keys waiting.

### io_sync

**Behavior:** Call KERNAL PLOT ($FFF0) with CLC, X=io_cy, Y=io_cx.
This updates $D1/$D2 (screen line pointer) and $F3/$F4 (color
line pointer) to match the current cursor position.

**When to call:** After modifying io_cy ($D6).  Not needed after
modifying only io_cx ($D3).

**Note:** cse_io's output functions (io_putc, io_puts, io_puthex*,
io_putdec, io_clear_eol) do NOT use $D1/$D2.  They compute the
screen address directly from scr_lo/scr_hi[io_cy].  io_sync exists
for the KERNAL's benefit (cursor blink, screen editor state).

### io_blip

**Behavior:** Short audible reject blip via SID voice 1 (triangle).
Called by editor and REPL on refused input (line cap, backspace
into left wall, unknown command).

### _io_scr_setup

**Input:** `CUR_ROW` ($D6)
**Output:** `_io_scr` / `_io_scr+1` = `scr_lo[CUR_ROW] | (scr_hi[CUR_ROW] << 8)`
**Clobbers:** A, X

Populates the `_io_scr` ZP pointer with the screen-RAM address of
the current row.  Leading underscore marks it as a shared internal
helper rather than a user-facing API entry point — but it IS
exported because screen.s uses it in its own scroll/clear routines
instead of duplicating the two-byte load.

Not called directly by most clients; the io_putc/io_puts/io_puthex*
family calls this internally before writing.  Documented here
because it crosses a module boundary to screen.s.

### Cursor Position

Cursor position is read/written directly via KERNAL ZP:
- `$D3` (CUR_COL) — column 0–39
- `$D6` (CUR_ROW) — row 0–24

Call `io_sync` after changing CUR_ROW to update line pointers.

**Depends on:** KERNAL (GETIN $FFE4, PLOT $FFF0)

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
ca65 `-t c64` character literals produce.  The $60–$BF range is
avoided:

| Screencodes | Canonical PETSCII | Avoid | Why |
|-------------|-------------------|-------|-----|
| $40–$5F | **$C0–$DF** | $60–$7F | KERNAL GETIN returns $C1–$DA for shifted letters; `'A'` (ca65) = $C1 |
| $60–$7F | **$E0–$FF** | $A0–$BF | Matches the shifted-uppercase convention; $E0-$FF is what scr_to_pet produces |

**Rule:** uppercase letters everywhere in CSE (string constants,
generated output, keyboard input, screen-read input) live in
$C0–$DF.  The $60–$7F range should not appear; if it does, it's
a bug (case-insensitive comparators should still tolerate both).

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
and $A0–$BF (graphics) duplications.  The round-trip through screen
RAM is **lossy for the avoided ranges** — any $60–$BF value that
somehow reached the screen comes back as $C0–$FF.

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

#### Where $C0–$DF uppercase PETSCII appears

$C0–$DF is the canonical uppercase range in CSE.  It appears from
two sources:

- **KERNAL GETIN** — raw keyboard input returns $C1–$DA for
  shifted letters.
- **`scr_to_pet`** — screen code $40–$5F (uppercase on screen)
  maps to $C0–$DF via ORA #$80.

Code that needs case-insensitive comparison (assembler, expression
parser, symbol table) must fold $C0–$DF → $40–$5F:

- `fold_char` in `symtab.s` — folds $C0–$DF → $40–$5F
- Label scanner in `expr.s` — folds $C0–$DF in-place
- Assembler in `asm_src.s` — folds $C0–$DF for mnemonics
- `_hex_val` in `repl.s` — accepts $C0–$DF for hex A–F
- `editor.s` — key handler folds $C0–$DF → screencodes for display

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

- Set `$CC=1` (`io_cursor_off()`) at startup.  Never re-enable KERNAL cursor.
- Call `io_sync()` after changing `io_cy`.
- Fill screen RAM and color RAM at startup (`memset`).
- Use `SEI`/`CLI` around screen RAM memmove in `scroll_up` (cosmetic).
- Manage cursor visibility via `cursor_show()`/`cursor_hide()`.
