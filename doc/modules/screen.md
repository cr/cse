# screen.s — Screen Management

## Interface

### restore_colors
**In:** none (reads theme_border, theme_bg, theme_fg)
**Out:** VIC border/bg set, `_io_color` set, color RAM filled with theme_fg
**Clobbers:** A, X

### reset_screen
**In:** none
**Out:** screen cleared with spaces, colors restored, cursor to 0,0
**Clobbers:** A, X, Y

### scroll_up
**In:** A = number of rows to scroll (__fastcall__)
**Out:** screen RAM scrolled up, bottom rows cleared with spaces,
io_cy adjusted (clamped to 0).  If A ≥ 25: full screen clear.
**Clobbers:** A, X, Y

### newline
**In:** none (uses io_cy, io_cx)
**Out:** io_cx = 0, io_cy incremented.  If at bottom row (24),
scrolls up 1 instead of incrementing.  Calls `io_sync`.
**Clobbers:** A, X, Y

### print_string
**In:** A/X = pointer to NUL-terminated PETSCII string (__fastcall__)
**Out:** string printed at cursor via `io_puts`
**Clobbers:** A, X, Y

Thin wrapper — `jmp _io_puts`.  Does not interpret newline characters.

### cursor_show / cursor_hide
**In:** none (uses io_cy, io_cx)
**Out:** screen byte at cursor XOR'd with $80 (toggles reverse)
**Clobbers:** A, X, Y

`cursor_hide` is aliased to `cursor_show` — same toggle operation.

**Depends on:** cse_io (io_puts, io_sync, io_color, scr_lo/scr_hi)

## Theme System

Three DATA bytes control the color scheme: `theme_border`,
`theme_bg`, `theme_fg`.  Values are C64 color indices 0–F.

**Build-time selection:** `make THEME=BFS` where B, F, S are hex
nybbles for border, background, and foreground.  Decoded by the
Makefile into `-DTHEME_BOR=N -DTHEME_BG=N -DTHEME_FG=N`.

**Runtime:** the `c BFS` REPL command writes to the same three
globals and calls `restore_colors`.

| Name          | Code | Border | Bg     | Fg     |
|---------------|------|--------|--------|--------|
| RADIOACTIVITY | cb5  | lt grey| dk grey| green  |
| GREENLAND     | d50  | lt grn | green  | black  |
| MRSPIGGY      | a21  | lt red | red    | white  |
| BRUCELEE      | 770  | yellow | yellow | black  |
| LEEBRUCE      | 007  | black  | black  | yellow |
| MATRIX        | 005  | black  | black  | green  |
| MILKYWAY      | 001  | black  | black  | white  |
| HERCULES      | 008  | black  | black  | orange |
| ORANGE        | 880  | orange | orange | black  |
| MUDDY         | 990  | brown  | brown  | black  |
| CLOUDY        | cbc  | grey   | dk grey| grey   |
| C64           | e6e  | lt blue| blue   | lt blue|
| C128          | dbd  | lt grn | lt grey| lt grn |

Default: RADIOACTIVITY (cb5).

## Design

Pure 6502 assembly.  No cc65 runtime dependencies.

**Color RAM is static.**  `restore_colors` fills all 1000 nybbles
once; `scroll_up` only scrolls screen RAM.  This avoids the cost of
a second memmove and is correct because CSE uses a single text color
(set by the `c` command).

`scroll_up` uses SEI/CLI around the screen RAM copy to prevent the
VIC from reading partially scrolled data (cosmetic: avoids 1-frame
tear).

Cursor show/hide toggle the high bit of the screen byte at the cursor
position.  No KERNAL cursor — CSE manages its own via $CC=1.

## Caveats

- Requires $CC=1 (KERNAL cursor disabled).  Set at startup by io_init.
- `scroll_up` uses ZP $FB–$FE (src_ptr/dst_ptr) as scratch.  These
  overlap with KERNAL's FNADR/FNADR+1 but that's safe since CSE
  doesn't call KERNAL file routines during scroll.
- `scroll_up` saves/restores row indices via the 6502 stack
  (`pha`/`pla`).  Stack depth during scroll: 3 bytes (n, src_row,
  dst_row) plus the JSR return address.
- `newline` at row 24 scrolls then stays at row 24.  Below row 24
  it increments.  Both paths reset io_cx to 0.
