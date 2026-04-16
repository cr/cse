# CSE - THE ULTIMATE C64 ASM ENV

CSE is the native, integrated assembler environment for the C64 that
you did not know you were missing. Its functionality and workflows are
heavily inspired by MasterSeka, radare2, and SMON. Sketch and iterate
ideas fast, edit, assemble, run, debug in one place, all natively on
the C64 itself, pure and simple.

## Contents

- [Concepts](#concepts)
- [Quick start](#quick-start)
- [REPL commands](#repl-commands)
- [Editor](#editor)
- [Assembler syntax](#assembler-syntax)
- [Memory layout](#memory-layout)
- [Built-in symbols](#built-in-symbols)
- [Development](#development)

## Concepts

CSE has two modes: the **REPL** and the **editor**.  Press RUN/STOP
to switch between them.

The **REPL** is a command prompt for inspecting memory, assembling,
running, and debugging code.  Every command operates on the
*current address* shown in the `AAAA:` prompt.  Navigate with `@`,
`+`, `-`.

The **editor** is a full-screen text editor for writing assembly
source.  The `a` command in the REPL assembles the editor's content
into memory at the current address.

### The edit-assemble-run cycle

1. Write source in the editor (RUN/STOP to enter).
2. Switch back to the REPL (RUN/STOP).
3. Set the origin: `@ $C000` (or use `.org` in source).
4. Assemble: `a`
5. Run: `g` (jumps to `main:` label).
6. Inspect: `d` to disassemble, `m` to hex-dump, `r` for registers.
7. Debug: `b $C010` to set a breakpoint, `g` to run, `t` or `o` to step,
   `c` to continue.

Repeat.  The source stays in the editor buffer between runs.
Save to disk with `s "NAME"` (SEQ file).

### Current address

The REPL prompt shows `AAAA:` — this is the *current address*.
It determines where `d`, `m`, `.`, `a`, `j` operate.  Set it
explicitly with `@ EXPR` or navigate with `+`/`-`.  After
assembly, the current address advances to the `main:` label
if one was defined.

### Block size

Commands like `d` (disassemble) and `m` (memory dump) operate on
a chunk of *block size* bytes.  Default is $10 (16).  Change it
with `B EXPR`.  `+` and `-` also advance/retreat by the block size.
`t` and `o` use it as "number of trace steps".

### Screen editing

`m`, `d`, and `$` output multiple lines to the screen.  For `m`
and `d`, each output line is a valid `.` command.  Move the
cursor to any line, edit the values directly on screen, and
press RETURN to execute the modified line.  This is the C64
screen-editor workflow: the screen *is* your input buffer.

For example, `d` might show:

    C000:. A9 42     LDA #$42
    C002:. 8D 20 D0  STA $D020
    C005:. 60        RTS

Cursor up to the first line, change `42` to `07`, press RETURN —
the byte at $C000 is now patched.

### Expressions

Anywhere CSE expects a number — command arguments, assembler
operands, directive values — you can use a full expression with
arithmetic, labels, and lo/hi byte operators.  See
[Assembler syntax](#expressions-1) for details.

## Quick start

    LOAD "CSE",8,1
    RUN

CSE boots into the REPL. Type commands at the `AAAA:` prompt.
Press RUN/STOP to toggle between the REPL and the source editor.

## REPL commands

### Navigation

| Command | Syntax | Description |
|---------|--------|-------------|
| `@` | `@ EXPR` | Set current address |
| `+` | `+ [EXPR]` | Advance by EXPR (default: block size) |
| `-` | `- [EXPR]` | Retreat by EXPR (default: block size) |
| `B` | `B [EXPR]` | Show or set block size (default $10) |

### Inspect and edit memory

| Command | Syntax | Description |
|---------|--------|-------------|
| `.` | `.` | Disassemble one instruction at current address |
| `.` | `. HH [HH] [HH]` | Poke 1--3 hex bytes at current address |
| `.` | `. MNEM [OPERAND]` | Assemble one instruction at current address |
| `d` | `d` | Disassemble block-size bytes |
| `m` | `m` | Hex+ASCII dump of block-size bytes |
| `m` | `m [HH] [HH] ...` | Edit up to 8 bytes at current address |
| `i` | `i` | Show full memory map |

### Assembler

| Command | Syntax | Description |
|---------|--------|-------------|
| `a` | `a` | Assemble source from editor at current address |
| `u` | `u [MODE]` | Show or set CPU mode: `6502`, `6510`, `65c02` (available modes depend on build) |

After `a`, the current address advances past the assembled code.
If the source defines a `main:` label, `g` will jump there.

### Run and debug

| Command | Syntax | Description |
|---------|--------|-------------|
| `j` | `j [ADDR]` | Execute code at address (default: current) |
| `g` | `g` | Execute at label `main` |
| `t` | `t [EXPR]` | Step into (N instructions, default 1) |
| `o` | `o [EXPR]` | Step over (N instructions, default 1) |
| `c` | `c` | Continue from breakpoint |
| `b` | `b` | List breakpoints |
| `b` | `b ADDR` | Set breakpoint (8 slots) |
| `b` | `b -N` | Delete breakpoint N |
| `b` | `b *` | Clear all breakpoints |
| `r` | `r` | Show registers (A, X, Y, SP, flags) |
| `r` | `r A:XX X:XX ...` | Set registers |

RUN/STOP+RESTORE triggers an NMI break into the debugger.

Stepping into a JSR whose target is in KERNAL ROM ($E000--$FFFF)
automatically falls back to step-over.

### Files

| Command | Syntax | Description |
|---------|--------|-------------|
| `l` | `l "NAME"` | Load file from disk (SEQ->editor, PRG->memory) |
| `s` | `s "NAME" [END]` or `s "NAME" START END` | Save (SEQ from editor, PRG from memory range) |
| `$` | `$ [DEVICE]` | Directory listing (default device 8) |

SEQ files are source code (loaded into the editor).
PRG files are binary (loaded/saved at the current address).
PRG address args are expressions: `s "file" $2000` saves cur_addr..$2000,
`s "file" $1000 $2000` saves $1000..$2000.  If end < start, end is
treated as relative length (end = start + end - 1).

### Utility

| Command | Syntax | Description |
|---------|--------|-------------|
| `?` | `? EXPR` | Calculator -- shows hex, decimal, binary, signed |
| `C` | `C [B] [G] [F]` | Show or set colors (border, background, foreground) |
| `k` | `k` | Delete source (with confirmation) |
| `x` | `x` | Clear screen |
| `Q` | `Q` | Quit CSE (with unsaved guard) |

Color values are single hex digits 0--F (C64 palette).
`C F` sets foreground only; `C B F` sets border+foreground;
`C B G F` sets all three.

## Editor

Press RUN/STOP to enter the editor from the REPL and back.

| Key | Action |
|-----|--------|
| Printable | Insert character (39-column visual limit) |
| RETURN | Newline with auto-indent (see below) |
| DEL | Backspace |
| INS | Insert space at cursor (cursor stays) |
| Cursor keys | Navigate |
| HOME | Start of line |
| SHIFT+SPACE | Tab (to next tab stop) |
| RUN/STOP | Return to REPL |

**Smart indent.**  New lines start with a tab (SHIFT+SPACE).
Typing `:` slides the current line to column 0 — labels are
recognised by the colon and move to the left edge automatically.
RETURN after a colon also strips the gutter from the label line.

*Known quirk:* a colon in a comment (`; note:`) will also strip
the line's leading tab.  Re-add it with SHIFT+SPACE if needed.

The editor uses a gap buffer that grows downward from the CSE
runtime start address (determined at link time, typically ~$7B00).
The status bar shows the cursor position, line count, dirty flag,
and free bytes.

## Assembler syntax

Full syntax spec: [doc/assembler_syntax.md](doc/assembler_syntax.md)

### Source lines

    [label:]  [instruction | directive]  [; comment]

### Labels

    main:           ; global
    .loop:          ; local (scoped to last global)

Case-insensitive. Characters: a--z, 0--9, dot.

### Addressing modes

    LDA #$42        ; immediate
    LDA $42         ; zero page
    LDA $42,X       ; zero page,X
    LDA $1000       ; absolute
    LDA $1000,X     ; absolute,X
    LDA $1000,Y     ; absolute,Y
    LDA ($42,X)     ; (indirect,X)
    LDA ($42),Y     ; (indirect),Y
    JMP ($1000)     ; indirect
    LDA ($42)       ; zero page indirect (65C02 build only)
    JMP ($1000,X)   ; absolute indirect,X (65C02 build only)
    ROL A           ; accumulator
    BEQ .loop       ; relative (assembler computes offset)

### Directives

    .org $C000              ; set origin
    .const NAME EXPR        ; define constant
    .cpu 6502               ; set CPU mode
    .db $41, $42, 0         ; emit bytes
    .dw $1234, label        ; emit words (little-endian)
    .str "hello", 0         ; emit PETSCII string
    .scr "HELLO"            ; emit screen codes
    .res 256, $EA           ; reserve and fill
    .align 256              ; align to boundary
    .bas                    ; emit BASIC SYS stub
    .bas "title"            ; emit BASIC SYS stub with REM

### Expressions

Anywhere a value is expected:

    LDA #<screen            ; lo byte
    STA table+40            ; arithmetic
    LDX #cols-1             ; constant
    LDA #mask & $0F         ; bitwise

Number formats: `$FF` hex, `42` decimal, `%10101010` binary, `*` PC.

Operators (loosest to tightest):

    \pounds & ^             ; OR AND XOR
    + -                     ; add subtract
    * / << >>               ; multiply divide shift
    - ! < >                 ; negate NOT lo-byte hi-byte (unary)
    ( )                     ; grouping

Width rule: `$XX` (1--2 hex digits) is zero-page; `$0XX`+ (3--4
digits) forces absolute.  Width is sticky across operators.

### Example

    .cpu 6502
    .org $C000

    .const border $D020

    main:   ldx #0
    .loop:  stx border
            ldy #4
    .wait:  dey
            bne .wait
            inx
            bne .loop
            rts

Assemble and run:

    C000:a          ; assemble
    g               ; run (jumps to main:)

## Memory layout

At startup CSE shows the free memory available:

      zp 0002-007F       37b free
    lo02 02A7-02FF       89b free
    lo03 0334-03FF      204b free
    work 0800-XXXX    NNNNNb free

| Region | Address | Use |
|--------|---------|-----|
| User ZP | $0002--$007F | Your zero-page variables (saved/restored across run) |
| Low page 2 | $02A7--$02FF | Free RAM (89 bytes) |
| Low page 3 | $0334--$03FF | Free RAM (204 bytes, includes tape buffer) |
| Screen | $0400--$07FF | VIC-II screen RAM |
| Workspace | $0800--workend | Your programs and data |
| CSE | XXXX--$CFFF | CSE runtime code and data |
| I/O | $D000--$DFFF | VIC-II, SID, CIA |
| Symbols | $E000--$EEFF | Symbol table + name heap (under KERNAL ROM) |
| CSE banked | $EF00--$F8D9 | Stack snapshots, KDATA tables, REPL screen (under KERNAL ROM) |
| KERNAL | $F8DA--$FFFF | KERNAL ROM |

CSE unmaps BASIC ROM, so the full $0800--$CFFF range is available
as contiguous workspace.  The $E000--$F8D9 region under KERNAL ROM
holds CSE data (symbol table, lookup tables, screen save); CSE
banks the KERNAL out temporarily when accessing it.

### What your code can use

When you run code with `j`, `g`, `t`, or `o`, your program may
freely use:

- **$02--$7F** — CSE saves and restores these across your run.
- **$02A7--$02FF** — 89 bytes of free low RAM.
- **$0334--$03FF** — 204 bytes (tape buffer at $033C--$03FB is
  included; restore it if you need tape I/O).
- **$0800--workend** — your workspace.

Your code **must preserve:**

- **$80--$FF** — KERNAL zero page.
- **$0100--$01FF** — hardware stack (use normally, but balance
  pushes and pops).
- **$0200--$02A6** — KERNAL editor state.
- **$0300--$0333** — KERNAL/CSE vectors.

Your code may use KERNAL I/O (CHROUT, GETIN, etc.) normally.
CSE restores screen colors, charset, and cursor state on return.
If your code clears or repaints the screen, type `x` in the
REPL to restore the display.

## Built-in symbols

| Symbol | Value | Description |
|--------|-------|-------------|
| `workstart` | first free byte after CSE | Start of workspace |
| `workend` | CSE runtime start - 1 (adjusts with editor) | End of workspace |

Use in assembler: `.org workstart`

Use in REPL: `@ workstart`, `j workstart`

## Development

### Quick start

    make            # build cse.prg (requires ca65/ld65)
    make run        # build + launch in VICE
    make test       # run pytest test suite (requires py65)

### Documentation

All design docs, module specs, and project goals live in
[`doc/`](doc/README.md).

### Build requirements

- [cc65](https://cc65.github.io/) -- provides `ca65` (assembler)
  and `ld65` (linker).  CSE is pure 6502 assembly; the cc65
  C compiler is not used.
- [VICE](https://vice-emu.sourceforge.io/) -- C64 emulator
  (for `make run`)
- Python 3 + [py65](https://pypi.org/project/py65/) -- test harness
- pipenv or virtualenv for the test environment
- C64 KERNAL ROM for testing (copied from VICE; see `make test`)
