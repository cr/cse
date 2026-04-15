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
| _io_color | 1 | Text color for screen clears |
| dec_start_col | 1 | Start column for io_putdec (leading-zero suppression) |
| _nmi_pending | 1 | Set by NMI handler, checked in main loop |

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
| dec_lo[5] | 5 | Low bytes of 10000, 1000, 100, 10, 1 |
| dec_hi[5] | 5 | High bytes of same |

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

### io_putdec

**Input:** A = lo byte, X = hi byte

**Behavior:**
1. Compute screen address from scr_lo/scr_hi[io_cy]
2. For each power of 10 (10000, 1000, 100, 10, 1):
   subtract repeatedly, count digits
3. Suppress leading zeros (except: always print at least "0")
4. Write each digit as hex_tab[digit] ($30–$39)

**Output:** 1–5 screen code bytes.  io_cx advances by the number of
digits written.

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

### PETSCII → Screen Code Conversion

Used by `io_putc`.  Input: PETSCII byte.  Output: screen code byte.

| PETSCII range | Screen code | Rule | Example |
|---------------|-------------|------|---------|
| $00–$1F | $00–$1F | identity | (control chars, rarely used) |
| $20–$3F | $20–$3F | identity | space, 0–9, :, ., +, -, etc. |
| $40–$5F | $00–$1F | A − $40 | $41→$01 (A), $4D→$0D (M), $5A→$1A (Z) |
| $60–$7F | $40–$5F | A − $20 | $61→$41 (a), $7A→$5A (z) |
| $80–$BF | $80–$BF | identity | (reversed chars, pass through) |
| $C0–$DF | $40–$5F | A − $80 | $C1→$41 (shifted A), $DA→$5A |
| $E0–$FF | $E0–$FF | identity | (rarely used) |

### Screen Code → PETSCII Conversion

Used by `read_line`.  Input: screen code byte (bit 7 masked off).
Output: PETSCII byte.

| Screen code | PETSCII | Rule |
|-------------|---------|------|
| $00–$1F | $40–$5F | A + $40 |
| $20–$3F | $20–$3F | identity |
| $40–$5F | $40–$5F | identity |
| $60–$7F | $60–$7F | identity |

Note: the `and #$7F` in read_line strips the reverse-video bit before
conversion.  Screen codes $40–$5F map to PETSCII $40–$5F which are
the uppercase-letter range in CSE's PETSCII convention ($41='a',
$42='b', ...; see `project.md` § PETSCII conventions).

### IRQ Safety

**With $CC=1 (KERNAL cursor disabled), cse_io is fully IRQ-safe.**

The KERNAL IRQ at $EA31 with $CC=1 only does:
- Jiffy clock increment ($A0-$A2)
- Keyboard scan (CIA1 → buffer at $0277, count at $C6)
- STOP key check (CIA1)

It does NOT touch: screen RAM, color RAM, $D1/$D2/$D3/$D6/$F3/$F4.

Therefore:
- io_putc, io_puts, io_puthex2/4, io_putdec, io_clear_eol: **no SEI needed**
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
