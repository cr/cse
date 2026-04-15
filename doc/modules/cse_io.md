# cse_io.s — Screen I/O and Cursor Management

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/cse_io.s`](../../src/cse_io.s) | implementation |
| [`tests/test_cse_io.py`](../../tests/test_cse_io.py) | test contract |

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

| Name | Size | Purpose |
|------|------|---------|
| io_color | 1 | Text color for screen clears |
| dec_buf | 6 | io_utoa output: 5-digit PETSCII + permanent NUL at [5] |
| nmi_pending | 1 | Set by NMI handler, checked in main loop |

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

| Name | Size | Contents |
|------|------|---------|
| scr_lo[25] | 25 | Low bytes of $0400 + row×40 for rows 0–24 |
| scr_hi[25] | 25 | High bytes of same |
| hex_tab[16] | 16 | Screen codes for hex digits: $30–$39, $01–$06 |
| *(dec_pow_lo/hi moved to strings.s)* | | |

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

### Cursor Position

Cursor position is read/written directly via KERNAL ZP:
- `$D3` (CUR_COL) — column 0–39
- `$D6` (CUR_ROW) — row 0–24

Call `io_sync` after changing CUR_ROW to update line pointers.

**Depends on:** KERNAL (GETIN $FFE4, PLOT $FFF0),
strings (dec_pow_lo/hi for io_putdec)

## Design

### Character Encoding Reference

CSE uses the C64 **lower/upper charset** (VIC $D018 bit 1 = 1).
Three encodings interact: PETSCII (software), screen codes (VIC
chip), and keyboard input (KERNAL GETIN).  Getting these wrong
causes silent case-flipping bugs.  This section is the single
source of truth.

#### PETSCII (how software stores text)

KERNAL GETIN returns PETSCII.  All CSE strings, buffers, and the
assembler/expression parser work in PETSCII.

| PETSCII | Meaning | Keyboard |
|---------|---------|----------|
| $20–$3F | space, digits, punctuation | unshifted |
| $41–$5A | **lowercase** a–z | unshifted letter keys |
| $61–$7A | **uppercase** A–Z (preferred range) | — |
| $A0–$BF | shifted graphics / special chars (preferred range) | shifted |
| $C1–$DA | **uppercase** A–Z (keyboard alias) | shifted letter keys |
| $E0–$FF | shifted graphics / special chars (redundant mirror of $A0–$BF) | — |

**The $41–$5A = lowercase convention is the opposite of ASCII.**
PETSCII $41 is lowercase `a`, not uppercase `A`.  This is the
single most common source of confusion.

#### Duplicate ranges and preferred usage

PETSCII has redundant ranges that map to the same screen codes.
CSE picks one canonical range for each and avoids the other:

| Screen code | Preferred PETSCII | Avoid | Why |
|-------------|-------------------|-------|-----|
| $41–$5A (uppercase A–Z) | **$61–$7A** | $C1–$DA | $61 maps cleanly (A−$20), $C1 collides with shifted/control zone |
| $60–$7F (graphics/specials) | **$A0–$BF** | $E0–$FF | $A0 maps cleanly (A−$40), $E0 is a redundant Commodore wiring quirk |

**Rule:** string constants and generated output must use the
preferred ranges.  The avoided ranges exist only in keyboard input
and must be folded at the input boundary (see "Where shifted
PETSCII appears" below).

#### Screen codes (what VIC reads from $0400)

In the lower/upper charset:

| Screen code | Displays as |
|-------------|-------------|
| $01–$1A | a–z (lowercase) |
| $20–$3F | space, digits, punctuation |
| $41–$5A | A–Z (uppercase) |
| $00 | `@` |
| $1B–$1F | `[`, `£`, `]`, `↑`, `←` |
| $60–$7F | graphics/special characters |
| $80–$FF | reverse-video versions of $00–$7F |

#### PETSCII → Screen Code (io_putc)

| PETSCII range | Screen code | Rule | Notes |
|---------------|-------------|------|-------|
| $00–$1F | $80–$9F | ORA #$80 | reverse-video control chars |
| $20–$3F | $20–$3F | identity | space, digits, punctuation |
| $40–$5F | $00–$1F | A − $40 | **lowercase** a–z ($41→$01) |
| $60–$7F | $40–$5F | A − $20 | **uppercase** A–Z ($61→$41) ← preferred |
| $80–$9F | $80–$9F | identity | reverse video |
| $A0–$BF | $60–$7F | A − $40 | graphics/specials ($A0→$60) ← preferred |
| $C0–$FF | $40–$7F | A − $80 | **uppercase** + graphics ($C1→$41, $E0→$60) ← avoid |

The last row covers both $C1–$DA (uppercase alias) and $E0–$FF
(graphics alias).  Both map to the same screencodes as the
preferred ranges $61–$7A and $A0–$BF respectively.  The
round-trip through screen RAM is **lossy** — the distinction
between preferred and alias ranges is destroyed.

#### Screen Code → PETSCII (read_line)

`read_line` strips bit 7 (`AND #$7F`) to remove reverse video,
then converts:

| Screen code (after AND #$7F) | PETSCII | Rule |
|------------------------------|---------|------|
| $00–$1F | $40–$5F | A + $40 |
| $20–$7F | $20–$7F | identity |

**Critical consequence:** screencodes $01–$1A (lowercase a–z on
screen) map to PETSCII $41–$5A.  Screencodes $41–$5A (uppercase
A–Z on screen) map to PETSCII $41–$5A.  **Both cases produce the
same PETSCII range.**  `read_line` is inherently case-insensitive —
text round-tripped through screen RAM loses the uppercase/lowercase
distinction.  This is by design: the REPL and assembler are
case-insensitive.

#### Where shifted PETSCII ($C1–$DA) appears

Shifted PETSCII only comes from **KERNAL GETIN** (keyboard input).
It never appears in text that went through `read_line`, because the
screen round-trip collapses it to $41–$5A.

Code that receives raw keyboard input (not screen-read text) must
handle $C1–$DA explicitly.  Currently:

- `editor.s` — key handler folds $C1–$DA → screencodes for display
- `_hex_val` in `repl.s` — accepts $C1–$C6 for hex A–F
- `fold_char` in `symtab.s` — folds $C1–$DA → $41–$5A
- Label scanner in `expr.s` — folds $C1–$DA in-place
- Assembler in `asm_src.s` — folds $C1–$DA for mnemonics

Modules that only process screen-read text (via `read_line`) do
NOT need $C1–$DA handling — they will never see it.

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
