# screen.s — Screen Management

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/screen.s`](../../src/screen.s) | implementation |
| [`tests/integration/test_screen.py`](../../tests/integration/test_screen.py) | test contract — Tier I (full PRG via `C64Emu`) |

## Interface

### restore_colors
**In:** none (reads theme_border, theme_bg, theme_fg)
**Out:** VIC border/bg set, `_io_color` set, color RAM filled with theme_fg
**Clobbers:** A, X

### reset_screen
**In:** none
**Out:** screen cleared with spaces, colors restored, cursor to 0,0
**Clobbers:** A, X, Y

`reset_screen` does NOT touch KERNAL screen-edit ZP
(`$C6/$D4/$D5/$D8/$CE/$D9-$F1`).  The line-link table and
`$D5` reflect the *displayed content*; cold-init and the `x`
(clear-screen) command rely on KERNAL CHROUT continuing to
position correctly relative to that state, so a wholesale
sanitize on every reset_screen would corrupt subsequent
positioning.  See `kernal_screen_reset` for the dedicated
sanitize entry point used only on the cse_refresh path.

### kernal_screen_reset

**In:** none
**Out:** KERNAL screen-edit ZP reset to pristine post-init state
**Clobbers:** A, X

Defends against NMI-during-CHROUT corruption.  When RESTORE fires
inside a tight `$FFD2` loop, KERNAL CHROUT leaves several ZP bytes
mid-update; CSE's NMI handler dispatches to `cse_refresh →
refresh_body`, which calls `kernal_screen_reset` BEFORE
`reset_screen`'s tail-call to `io_sync` (KERNAL PLOT).  Without
this step the editor swallows the first cursor key and the REPL's
line-edit cursor drifts off-screen.

| Addr | Name | Reset to | Why |
|------|------|----------|-----|
| `$C6` | NDX | 0 | Drain key buffer; in-flight keys typed during an interrupted CHROUT have no valid consumer. |
| `$D4` | QTSW | 0 | Quote mode off (mid-string `"` may have set it). |
| `$D5` | LNMX | 39 | Single-physical-line logical line (mid-wrap may have set it to 79). |
| `$D8` | INSRT | 0 | No insert pending. |
| `$CE` | GDBLN | 0 | No char-under-cursor cached. |
| `$D9..$F1` | LDTB1 | $80 each | Line-link table: every row is the start of its own logical line (matches the just-cleared screen). |

Bytes deliberately NOT touched: `$D1/$D2/$D3/$D6/$F3/$F4` are set
by the `io_sync` call that immediately follows (KERNAL PLOT
populates them from `CUR_COL`/`CUR_ROW`).

**Call-site discipline.**  Exactly one caller: `refresh_body` in
main.s.  NOT called from cold-init's `reset_screen`, the `x`
command, or `scroll_up`'s full-clear path — those callers own
the screen transition and do not have a transiently-mid-CHROUT
KERNAL state to recover from.  An earlier rc2 candidate placed
the call inside `reset_screen` and regressed userland CHROUT
positioning (cold-init wiped LDTB1 / `$D5` before the splash
prints, leaving the screen-editor's view of logical lines
disagreeing with the displayed content).

### vic_reset
**In:** none
**Out:** VIC forced into known-readable text-mode state —
$D011=$1B (display on, 25 rows, text, no ECM/BMM),
$D016=$C8 (40 cols, no MCM, no scroll),
$D018=$16 (screen=$0400, charset=$1800 = char ROM $D800 =
lowercase/uppercase font),
$D015=0 (sprites off), $D01A=0 (no VIC IRQs),
$D019=$0F (ack pending IRQ latches).
**Clobbers:** A

Called on every userland → kernel transition (via
`hygiene_after_userland` in repl.s) so user code that flipped VIC
into bitmap/multicolor/extended-color mode, blanked the display,
moved the screen/charset pointer, enabled sprites, or armed a
raster IRQ doesn't leave the REPL unreadable.  Colour RAM and
CHROUT colour are (re)applied by `restore_colors`; this routine
only handles the mode registers.

### scroll_up
**In:** A = number of rows to scroll
**Out:** screen RAM scrolled up, bottom rows cleared with spaces,
io_cy adjusted (clamped to 0).  If A ≥ 25: full screen clear.
**Clobbers:** A, X, Y

### newline
**In:** none (uses io_cy, io_cx)
**Out:** io_cx = 0, io_cy incremented.  If at bottom row (24),
scrolls up 1 instead of incrementing.  Calls `io_sync`.
**Clobbers:** A, X, Y

### cursor_show / cursor_hide
**In:** none (uses io_cy, io_cx)
**Out:** screen byte at cursor XOR'd with $80 (toggles reverse)
**Clobbers:** A, X, Y

`cursor_hide` is aliased to `cursor_show` — same toggle operation.

### Memory

**BSS (3 bytes):** `theme_border` (1), `theme_bg` (1),
`theme_fg` (1) — runtime color theme.  Initialized from the
build-time constants `THEME_BOR` / `THEME_BG` / `THEME_FG` by
`theme_init` (called from `main.s` startup before the first
`reset_screen`).  The `c BFS` REPL command rewrites them at
runtime.  BSS, not RODATA, so this works on the planned CRT
target where RODATA lives in ROM.

**Depends on:** cse_io (io_puts, io_sync, io_color, scr_lo/scr_hi)

## Theme System

Three RODATA bytes control the color scheme: `_theme_border`,
`_theme_bg`, `_theme_fg`.  Values are C64 color indices 0–F.

**Build-time selection:** `make THEME=BFS` where B, F, S are hex
nybbles for border, background, and foreground.  Decoded by the
Makefile into `-DTHEME_BOR=N -DTHEME_BG=N -DTHEME_FG=N`.

**Runtime:** the `c [B][G]F` REPL command updates the same three
globals (1, 2, or 3 hex digits for fg / bg+fg / border+bg+fg) and
calls `restore_colors`.

| Name          | Code | Border | Bg     | Fg     |
|---------------|------|--------|--------|--------|
| RADIOACTIVITY | cb5  | lt grey| dk grey| green  |
| GREENLAND     | d5d  | lt grn | green  | black  |
| MRSPIGGY      | a21  | lt red | red    | white  |
| BRUCELEE      | 770  | yellow | yellow | black  |
| LEEBRUCE      | 007  | black  | black  | yellow |
| MATRIX        | 005  | black  | black  | green  |
| MILKYWAY      | 001  | black  | black  | white  |
| HERCULES      | 009  | black  | black  | brown |
| ORANGE        | 880  | orange | orange | black  |
| MUDDY         | 990  | brown  | brown  | black  |
| CLOUDY        | cbc  | grey   | dk grey| grey   |
| C64           | e6e  | lt blue| blue   | lt blue|
| C128          | dbd  | lt grn | lt grey| lt grn |

Default: RADIOACTIVITY (cb5).

**Dependants:** `Makefile` (`_THEME_MAP`)

## Design

Pure 6502 assembly.

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
