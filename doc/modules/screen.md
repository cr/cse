# screen.s — Screen Management

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/screen.s`](../../src/screen.s) | implementation |
| [`tests/integration/test_screen.py`](../../tests/integration/test_screen.py) | test contract — Tier I (full PRG via `C64Emu`) |
| [`tests/integration/test_m65_display.py`](../../tests/integration/test_m65_display.py) | tier-I tests on the m65 PRG (P2 T5): `screen_mode_set`, `vic_reset` against the recorded register sets, colours, clear, scroll, newline, cursor, `kernal_screen_reset`, the hygiene |

## Interface

**On m65** each entry below has the body of
[platform_layer.md § Display](../platform_layer.md#display)'s m65
column: `vic_reset` writes the current mode's recorded VIC-IV
register set and keeps the screen's content; `restore_colors` fills
the mode's colour RAM by one DMA job; `reset_screen` clears width ×
height bytes in the screen's bank by one DMA job; `scroll_up` moves
the rows by one DMA copy; `kernal_screen_reset` is `ESC O`, `HOME
HOME`, `io_kbd_flush`.  `screen_mode_set` (m65 only): `ESC 4` / `5` / `8`
through `BSOUT`, then `io_geometry`, `vic_reset` and `reset_screen`;
the editor refuses it while it runs.  `screen_save` / `screen_restore` (m65
only, the editor's): the screen's `scr_size` bytes to / from
`REPL_SCREEN` (`3.B000`) by one DMA copy ([platform_layer.md § Screen save](../platform_layer.md#screen-save)).
Every size is the run-time geometry (`WIDTH`, `HEIGHT`, `scr_size`).

`screen_stash` / `screen_unstash` (m65 only, the help
popup's): the same copy to / from the directory buffer `DIR_BUF`
(`2.D000`) instead of `REPL_SCREEN`, which holds the REPL's screen
while the editor runs ([help.md § Saving the screen](help.md#saving-the-screen)).

### theme_init
**In:** none
**Out:** `theme_border` / `theme_bg` / `theme_fg` = the build-time
`THEME_BOR` / `THEME_BG` / `THEME_FG`.
**Clobbers:** A

Called by `main.s` cold init and by `hw_reinit_body` (the
`cse_recover` warmstart), each time before `restore_colors` — so a
fault recovery also drops colours set with the REPL's `C` command
back to the build default.

### restore_colors
**In:** none (reads `theme_border`, `theme_bg`, `theme_fg`)
**Out:** VIC border ($D020) and background ($D021) set; the KERNAL
text colour `$0286` (the colour CHROUT writes) = `theme_fg`; all 1024
bytes of colour RAM from $D800 filled with `theme_fg`.
**Clobbers:** A, X (m65: A, X, Y)

Writing `$0286` keeps user code that prints with `jsr $FFD2` in the
theme colour instead of whatever colour BASIC left behind.

### reset_screen
**In:** none
**Out:** `restore_colors`, screen RAM ($0400, 1024 bytes) filled with
spaces, cursor at row 0 col 0, `io_sync` done.
**Clobbers:** A, X, Y

Callers: `main.s` cold init and `refresh_body` (the `cse_refresh`
warmstart), the REPL's `x` command, and `scroll_up` for a scroll of
25 rows or more.

`reset_screen` does NOT touch KERNAL screen-edit ZP
(`$C6/$D4/$D5/$D8/$CE/$D9-$F1`).  The line-link table and `$D5`
reflect the *displayed content*; cold init and the `x` command rely
on KERNAL CHROUT continuing to position correctly relative to that
state, so sanitizing it on every `reset_screen` would corrupt later
positioning.  `kernal_screen_reset` is the dedicated sanitizer, run
only when control returns from user code.

### kernal_screen_reset

**In:** none
**Out:** KERNAL screen-edit ZP reset to pristine post-init state, the
keyboard buffer empty (`$C6` = 0; m65: `ESC O`, `HOME HOME`,
`io_kbd_flush` — the typed keys dropped on both platforms)
**Clobbers:** A, X (m65: A, X, Y)

Defends against userland-NMI-during-CHROUT corruption.  CSE's
*own* screen output (`io_putc`) writes screen RAM directly and
does NOT call KERNAL CHROUT — so kernel-mode NMI cannot corrupt
KERNAL screen-edit ZP.  USER programs, however, commonly use
`jsr $FFD2` for output.  When the user presses RESTORE inside a
tight `$FFD2` loop the NMI fires *inside the KERNAL CHROUT path*
(typically PC=$E9D6) and leaves transient mid-update values in
several ZP bytes that PLOT does not touch.  Without this defence,
the very next CSE-side cursor move (REPL or editor) calls
`io_sync` → KERNAL PLOT, which walks the corrupt LDTB1 to
compute the wrong screen-RAM pointer and column: the cursor
drifts off-screen or jumps by surprising amounts.

| Addr | Name | Reset to | Why |
|------|------|----------|-----|
| `$C6` | NDX | 0 | Drain key buffer; in-flight keys typed during the interrupted op have no valid consumer. |
| `$D4` | QTSW | 0 | Quote mode off (mid-string `"` may have set it). |
| `$D5` | LNMX | 39 | Single-physical-line logical line (mid-wrap may have set it to 79). |
| `$D8` | INSRT | 0 | No insert pending. |
| `$CE` | GDBLN | 0 | No char-under-cursor cached. |
| `$D9..$F1` | LDTB1 | $80 \| scr_hi[r] | Line-link table: every row is the start of its own logical line, AND the row's screen-address page is encoded in the low 7 bits (KERNAL reads this when CHROUT advances to a new row to recompute `$D1/$D2`). Rows 0-6 → $84, rows 7-12 → $85, rows 13-19 → $86, rows 20-24 → $87. |

Bytes deliberately NOT touched: `$D1/$D2/$D3/$D6/$F3/$F4` are set
by the `io_sync` (KERNAL PLOT) that follows in
`hygiene_after_userland`.

**Call-site discipline.**  Exactly one caller:
`hygiene_after_userland` in repl.s, immediately before its
tail-call to `io_sync`.  It runs on every return from user code
(`handler_finalize` in main.s: BRK, NMI, clean RTS) — the only
transition after which KERNAL screen-edit ZP can have been left
mid-update.  It is not on the `reset_screen` path (cold init, `x`,
`cse_refresh`): there the line-link state matches the displayed
content and must survive, and a kernel-mode NMI cannot interrupt a
CHROUT.

Mechanism witness:
[tests/integration/test_screen.py::TestPlotAgainstCorruptLdtb1](../../tests/integration/test_screen.py).
The middle test reproduces the drift in py65 against the real C64
KERNAL ROM (corrupt LDTB1 → PLOT(10,5) lands on row 9 col 45
instead of row 10 col 5); the third test confirms
`kernal_screen_reset` restores clean PLOT behaviour.

### vic_reset
**In:** none
**Out:** VIC forced into known-readable text-mode state —
$D011=$1B (display on, 25 rows, text, no ECM/BMM),
$D016=$C8 (40 cols, no MCM, no scroll),
$D018=$16 (screen=$0400, charset=$1800 = char ROM $D800 =
lowercase/uppercase font),
$D015=0 (sprites off), $D01A=0 (no VIC IRQs),
$D019=$0F (ack pending IRQ latches).
**Clobbers:** A (m65: A, X, Y, `sj_tmp`, and what `CHROUT` clobbers —
it tail-calls `CHROUT` with `$0E`, the lower/upper-case set)

Called on every userland → kernel transition (via
`hygiene_after_userland` in repl.s) so user code that flipped VIC
into bitmap/multicolor/extended-color mode, blanked the display,
moved the screen/charset pointer, enabled sprites, or armed a
raster IRQ doesn't leave the REPL unreadable.  Colour RAM and
CHROUT colour are (re)applied by `restore_colors`; this routine
only handles the mode registers.

### scroll_up
**In:** A = number of rows to scroll
**Out:** screen RAM scrolled up by A rows, the bottom A rows cleared
with spaces, `CUR_ROW` reduced by A (clamped to 0), `io_sync` done.
If A ≥ 25: `reset_screen` instead (cursor to 0,0).
**Clobbers:** A, X, Y, `scr_src`, `_io_scr`

### newline
**In:** none (uses CUR_ROW, CUR_COL)
**Out:** CUR_COL = 0, CUR_ROW incremented.  If at bottom row (24),
scrolls up 1 instead of incrementing.  Calls `io_sync`.
**Clobbers:** A, X, Y, `scr_src`, `_io_scr`

### cursor_show / cursor_hide
**In:** none (uses CUR_ROW, CUR_COL)
**Out:** screen byte at cursor XOR'd with $80 (toggles reverse)
**Clobbers:** A, X, Y, `_io_scr`

`cursor_hide` is aliased to `cursor_show` — same toggle operation.

### Memory

**ZP (from zp.s, allocation in [zp.md](zp.md)):** `scr_src` (2; m65
4, far, the screen's bank) — `scroll_up`'s source row pointer.  The
destination row pointer is cse_io's transient `_io_scr`.

**BSS (3 bytes):** `theme_border` (1), `theme_bg` (1),
`theme_fg` (1) — runtime color theme, set by `theme_init`, rewritten
by the REPL's `C` command, read by `restore_colors` and the REPL's
colour display.  BSS, not RODATA, so this works on the planned CRT
target where RODATA lives in ROM.

**Depends on:** cse_io (io_sync, scr_lo, scr_hi, _io_scr_setup),
zp (_io_scr, scr_src).

## Theme System

Three BSS bytes control the color scheme: `theme_border`,
`theme_bg`, `theme_fg`.  Values are C64 color indices 0–F.

**Build-time selection:** `make THEME=NAME` or `make THEME=BGF`
(three hex nybbles: border, background, foreground).  The default is
CLOUDY on every platform: white on grey, readable on a C64 monitor
and on the MEGA65's (GREENLAND's green on green was not, on
xmega65).  The Makefile
maps names through `_THEME_MAP` and passes
`-DTHEME_BOR=N -DTHEME_BG=N -DTHEME_FG=N`
([build_system.md](../build_system.md)).

**Runtime:** the REPL's `C` command updates the same three bytes
(1, 2 or 3 hex digits for fg / bg+fg / border+bg+fg) and calls
`restore_colors` ([repl.md](repl.md)).

| Name          | Code | Border | Bg     | Fg     |
|---------------|------|--------|--------|--------|
| CLOUDY        | fc1  | lt grey| grey   | white  |
| CONCRETE      | fbf  | lt grey| dk grey| lt grey|
| ASPHALT       | fc0  | lt grey| grey   | black  |
| JIFFY         | e61  | lt blue| blue   | white  |
| GREENLAND     | d51  | lt grn | green  | white  |
| MOSS          | d5d  | lt grn | green  | lt grn |
| RADIOACTIVITY | cb5  | grey   | dk grey| green  |
| MSPIGGY       | a21  | lt red | red    | white  |
| BRUCELEE      | 770  | yellow | yellow | black  |
| LEEBRUCE      | 007  | black  | black  | yellow |
| MATRIX        | 005  | black  | black  | green  |
| MILKYWAY      | 001  | black  | black  | white  |
| HERCULES      | 009  | black  | black  | brown |
| ORANGE        | 880  | orange | orange | black  |
| MUDDY         | 990  | brown  | brown  | black  |
| C64           | e6e  | lt blue| blue   | lt blue|
| C128          | dbd  | lt grn | dk grey| lt grn |
| MEGA          | 661  | blue   | blue   | white  |

Default: CLOUDY (fc1) — the Makefile's `THEME ?= CLOUDY`.
screen.s's own fallback (cb5) applies only when it is assembled
without the `-DTHEME_*` flags.

**Dependants:** `Makefile` (`_THEME_MAP`)

## Design

Pure 6502 assembly.

**Color RAM is static.**  `restore_colors` fills it once; `scroll_up`
only scrolls screen RAM.  This avoids a second memmove and is correct
because CSE uses a single text color (`theme_fg`).

`scroll_up` uses SEI/CLI around the screen RAM copy to prevent the
VIC from reading partially scrolled data (cosmetic: avoids 1-frame
tear).

Cursor show/hide toggle the high bit of the screen byte at the cursor
position.  No KERNAL cursor — CSE manages its own with `$CC` = 1.

## Caveats

- Requires `$CC` = 1 (KERNAL cursor disabled).  Set by `io_init`
  (cold init, `cse_recover`) and by `hygiene_after_userland`.
- `scroll_up`'s row pointers live in CSE's own ZP: the source in
  `scr_src` (zp.s), the destination in cse_io's transient `_io_scr`
  (every reader re-derives it via `_io_scr_setup`).  It never writes
  ZP `$80`–`$FF`, so `$FB`–`$FE` survive every REPL scroll
  ([userland_contract.md § 2](../userland_contract.md)).
- On c64 `scroll_up` ends with an unconditional CLI: called with
  I = 1, it returns with interrupts enabled.  The m65 body (two DMA
  jobs) does not touch I.
- `scroll_up` saves/restores row indices via the 6502 stack
  (`pha`/`pla`).  Stack depth during scroll: 3 bytes (n, src_row,
  dst_row) plus the JSR return address.
- `newline` at row 24 scrolls then stays at row 24.  Below row 24
  it increments.  Both paths reset CUR_COL to 0.
