# help — The HELP popup (m65)

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/help.s`](../../src/help.s) | implementation (m65 only) |
| [`src/help.txt`](../../src/help.txt) | the cheat sheet's text, as the user reads it — the one place it is written; back-link-exempt (every line is shown in the window: no comment syntax) |
| [`src/help_text.s`](../../src/help_text.s) | generated — the text as screen codes (`make tables`, `dev/help_text.py`); back-link-exempt (generated) |
| [`dev/help_text.py`](../../dev/help_text.py) | the generator: `src/help.txt` → `src/help_text.s`, refusing a line too long or a character the charset lacks |
| [`tests/unit/test_help_text.py`](../../tests/unit/test_help_text.py) | test contract — Tier U: the text's lines, its characters, its coverage of the commands and directives; the encoding; the generated file current |
| [`tests/integration/test_m65_help.py`](../../tests/integration/test_m65_help.py) | test contract — Tier I on the m65 PRG (`M65Session`): the window's rows in the three modes, the keys, the screen given back in the REPL and in the editor, RESTORE |
| [`tests/emulator/test_m65_help.py`](../../tests/emulator/test_m65_help.py) | test contract — Tier X in xmega65: the window as M65Emu draws it, the screen given back, the border codes' glyphs in the character ROM |

## Purpose

On the MEGA65 the **HELP** key opens a bordered window over whatever
is on the screen — the REPL or the editor, in any of the three text
modes — showing a one-page cheat sheet: the REPL commands with their
parameters, the global keys, the assembler directives with their
arguments, and the expression syntax.  When the text is longer than
the window, the cursor keys scroll it.  HELP, ESC or RUN/STOP close
the window and the screen is as it was.

The c64 has no HELP key; this module is not in the c64 builds, whose
bytes do not change.

## Interface

### help_popup
**In:** none (called by `main_loop` for the key `$84`, HELP, in either
state, after an armed ESC sequence has ended; the cursor already
hidden by `main_loop`)
**Out:** the screen and CSE's state as before the call; C = 1 when
RUN/STOP closed the window — `main_loop` then sets `stop_cooldown`, so
the key still held does not toggle the editor
**Clobbers:** A, X, Y, `rp_ptr` (its bank too), `_io_scr`, the DMA job's cells
(`sj_*`), the directory buffer `2.D000–2.FFFF`

A modal loop: save the screen, draw the window, then read keys
(`io_getc`) until a closing key, redrawing the text on a scroll, then
restore the screen.  It returns to `main_loop`, which shows the cursor
again; the key that closed the window is consumed (an ESC does not arm
`esc_armed`).  `help_wait` is the loop's key poll: the tests run to it.

**State** — **BSS (44 bytes):**

| Variable | Size | Exported | Purpose |
|---|---|---|---|
| `help_top` | 1 | no | the first text line shown |
| `help_max` | 1 | no | the largest `help_top`: the lines that do not fit, or 0 |
| `help_left` | 1 | no | the window's first column (0, or 20 in 80 columns) |
| `help_r` | 1 | no | `help_draw`: the screen row being built |
| `help_row` | 40 | no | one window row, built and then written to the screen |

**Depends on:** screen (`screen_stash` / `screen_unstash`: the screen
to and from the directory buffer by one DMA copy), cse_io (`io_getc`,
`io_blip`, the key poll through `IO_KBHIT`, the geometry and the row tables `scr_lo` /
`scr_hi`, `scr_bank`), help_text, zp.

## Design

### The window

    ┌ cse help ────────────────────── more ┐
    │ repl                                 │
    │ m [addr] [bb ..]  dump / edit memory │
    │ ...                                  │
    └ crsr scroll  help close ─────── more ┘

- **Size and place.**  40 columns wide — the whole width in 40 × 25,
  centred (columns 20–59) in 80 × 25 and 80 × 50 — and the screen's
  full height (25 or 50 rows).  Inside the border: one blank column,
  then 37 columns of text, `height − 2` lines.
- **The border** in the charset's line graphics (screen codes `$70`
  ┌, `$6E` ┐, `$6D` └, `$7D` ┘, `$40` ─, `$5D` │, which the
  lower/upper set shares with the upper-case set — in the character
  ROM the VIC-IV shows, `$FF7E000`, checked at Tier X; the ROM's font
  at `3.D000` is another one, with `` ` `` and `}` there).  The top border
  carries the title ` cse help `, the bottom border the keys
  ` crsr scroll  help close `.
- **Scroll marks.**  ` more ` at the right of the top border while
  lines are hidden above, at the right of the bottom border while
  lines are hidden below.
- **Colours.**  The window writes screen codes only; the colour RAM
  keeps the theme's single text colour (`restore_colors` paints it
  whole), so nothing of it needs saving.

### Keys

| Key | In the window |
|-----|---------------|
| CRSR ↓ / CRSR ↑ | Scroll one line; refused with `io_blip` at the end / the start |
| HOME | Back to the first line |
| HELP, ESC, RUN/STOP | Close (RUN/STOP: C = 1, above) |
| any other | Ignored |

The window opens at the first line every time.  When the text fits
the scroll keys only blip; the 58 lines of the current text scroll in
every mode (80 × 50 shows 48).

### Saving the screen

The screen under the window is saved whole — the mode's `scr_size`
bytes, at most 80 × 50 = 4000 — into the **directory buffer**
`2.D000–2.FFFF`, CSE's 12 K reserve, which `$` fills only while it
lists ([disk.md § On m65](disk.md)), and copied back on close, each by
one DMA copy (screen.s's `screen_stash` / `screen_unstash`).
`REPL_SCREEN` (`3.B000`) is not used: it holds the REPL's screen
while the editor runs.  RUN/STOP+RESTORE while the
window is open is `cse_refresh`, as anywhere else: the REPL is redrawn
and the saved copy forgotten.

### The text

`src/help.txt` is the cheat sheet as the user reads it: plain ASCII,
one window line per text line, at most 37 characters, in four
sections — the REPL commands (every command of
[repl.md § Commands](repl.md#commands--memory), with its parameters),
the global keys (RUN/STOP, ESC 4 / 5 / 8, HELP), the directives (every
one of [assembler_syntax.md § Summary](../assembler_syntax.md#summary),
with its arguments), the expression syntax (number formats, operators,
`*`), separated by blank lines — 58 lines.  The commands' and the
directives' lines start with the command or the directive in an
18-column command column, the description after it.

`dev/help_text.py` (`make tables`, as the mnemonic tables) writes
`src/help_text.s`: `HELP_LINES` (the line count) and `help_text`, each
line a length byte and its screen codes (the lower/upper set: `a–z` →
`$01–$1A`, `A–Z` → `$41–$5A`, `@` `[` `£` `]` `↑` `←` from their
PETSCII places, the rest of `$20–$3F` as is).  A line over 37
characters, or a character the charset has no glyph for (`|`, `\`,
`{`, `}`, `~`, `` ` ``, the underscore), is refused: the generator stops.  The
line at `help_top` is found by walking the length bytes.  The
window's own labels (` cse help `, ` crsr scroll  help close `,
` more `) are help.s's `KDATA`, as screen codes.

### Where it lives

`help_text` is the `HELP` segment, which the loader copies to the
reserve `3.C000` — bank 3, but not in the CSE map (`$C000` is the
interface ROM) — so `help_draw` reads it through `rp_ptr` as a far
pointer (`FAR_BANK rp_ptr, BANK_CSE`, `FAR_LDA`).  The text takes no
room in CSE's window; `help.s`'s code (`KCODE`: cold code, in the
open on m65), its labels (`KDATA`) and its BSS are there
([build_system.md § The m65 builds](../build_system.md#the-m65-builds)).

## Caveats

- The window is drawn over the screen RAM directly, never through
  `io_putc` / the KERNAL: CSE's cursor (`IO_CX`, `CUR_ROW`) and the
  KERNAL's screen-editor cells are untouched.
- A command or a directive added to repl.md or assembler_syntax.md
  must get its line in `src/help.txt`: `test_help_text.py` fails
  until it does.
