# repl.c — REPL Command Interface

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/repl.c`](../../src/repl.c) | implementation |
| [`src/repl.h`](../../src/repl.h) | header |

## Interface

- `exec_line()` — parse current screen line, dispatch command
- `read_line()` — capture screen row at io_cy into line_buf (PETSCII)
- `show_prompt()` — write `AAAA:` at cursor using cur_addr

**State:**
- `cur_addr` (uint16) — current address, default $1000
- `cur_device` (uint8) — disk device number, default 8
- `cur_filename` (char[]) — last used filename
- `last_cmd` (char) — last command (for RETURN repeat)
- `block_size` (uint16) — block size for m/d/f/>/+/-, default $10

**Depends on:** asm_bridge (`.`), asm_src (`a`), dasm (`d`), expr (`?`),
disk (`l`/`s`/`$`), debugger (`b`/`c`/`t`/`o`), editor, screen, cse_io

## Design

### Prompting loop

The main loop owns the prompt.  Command handlers never write it.

1. Assume the cursor is on the line where the prompt is to appear.
2. Write `AAAA:` at column 0, where `AAAA` is `cur_addr`.
3. Leave the cursor at column 5 for user input.
4. Dispatch keystrokes to the keystroke handler; wait for RETURN.
5. `read_line` — capture the screen row into `line_buf`.
6. If the line begins with `AAAA:`, write `AAAA` to `cur_addr` and
   consume five characters from the line.
7. Seek to the first non-whitespace character; mark its column as
   *start*.  Seek to the first `;` or end-of-line; mark that column
   as *end*.
8. If *start* = *end* and column 6 holds `;`: advance to the next
   line, clear it, go to 1.
9. If *start* = *end* (empty, no `;`): dispatch command repetition
   (`last_cmd`), go to 1.
10. Otherwise dispatch the line from *start* to *end* to the command
    parser.
11. Go to 1.

`show_prompt` writes `AAAA:` and positions the cursor — nothing
else.  Whether the prompt line is cleared before `show_prompt`
runs is the responsibility of the previous command handler
(principle 5).

### Command handler principles

1. **The screen is the command buffer.**  Every screen line is
   executable.  The parser reads from column 0 to `;` or end-of-line.
   The screen operates in lowercase mode (VICII charset 2).

2. **Commands are case-sensitive single characters.**  `a`–`z` and
   `A`–`Z` are distinct command keys — 52 letter slots available.
   Lowercase is the default; uppercase requires SHIFT.  `read_line`
   maps lowercase screen codes ($01–$1A) to PETSCII $41–$5A and
   uppercase screen codes ($41–$5A) to PETSCII $C1–$DA.

3. **Commands own their output lines.**  Every line a handler writes
   must be `clear_eol`'d — no leftover characters from previous
   content.

4. **Commands own their prompt line.**  In block-edit mode (`.` with
   args, `m` with hex bytes), the handler rewrites its prompt line to
   reflect the edited state.  What's on screen is the truth.

5. **Commands own the next line's clearing.**  Before returning,
   handlers clear the prompt line (`clear_eol`) so the loop's
   `show_prompt` writes `AAAA:` onto a clean line.  Exception: `.`
   and `m` in edit mode leave the next line intact — this is the
   block-edit workflow (cursor up, modify, re-RETURN).  `show_prompt`
   itself never clears.

6. **Non-executable output starts with `;`.**  Info text, status
   lines, and error messages are prefaced with `;` so they're inert
   if the user hits RETURN on them.

7. **Executable output without a `cur_addr` relation omits `AAAA:`.**
   If an output line is meant to be re-executable but doesn't
   correspond to a sequential address, it has no address prefix.

8. **Auto-advance and repeat.**  Block-paging commands (`.`, `m`, `d`)
   update `cur_addr` to the continuation address.  RETURN on an empty
   prompt repeats `last_cmd` at the new `cur_addr`, always without
   args (dump/disassemble mode).  This supports paging:
   `d`‹RETURN›‹RETURN›‹RETURN› to scroll through disassembly, or
   `.`‹RETURN›‹RETURN› to step one instruction at a time.
   `last_cmd` stores only the command character — no args buffer.

9. **Block commands are thin loops over single-line emitters.**  `d`
   calls `emit_dot` repeatedly; `m` (dump) calls `emit_mem`
   repeatedly.  The emitter is the unit of work.

10. **`;` is a no-op command.**  Screen output accumulates as a
    readable, scrollable log.

### Error reporting

Errors use the prefix `;?` — the `;` makes the line non-executable
(principle 5), the `?` signals an error.  Examples:

    ;?asm           assembly error
    ;?cmd           unknown command
    ;?name          missing filename
    ;?range         invalid address range

The `?` expression calculator is not confused by this because `;`
terminates parsing before `?` is reached.

### Block-edit workflow

The block-edit workflow is how the user inspects and modifies code or
data in bulk.  It has two phases: **dump** and **edit**.

**Dump phase** — `d` and `m` (without args) are block commands.  They
operate on `block_size` bytes and output a screenful of executable
lines:

- `d` outputs `AAAA:. HH HH HH  MNE OPR` lines (via `emit_dot`)
- `m` outputs `AAAA:m HH HH ... cccccccc` lines (via `emit_mem`)

Each output line is a valid command.  The block command clears the
final prompt line and stops.  The screen is now a buffer of editable
commands.

**Edit phase** — the user cursors to any line on screen:

- Modify hex bytes in an `m` line, press RETURN → `m` re-executes
  with the edited bytes, rewrites the line to reflect the new memory
  state, advances `cur_addr`.
- Modify the mnemonic or operand in a `.` line, press RETURN → `.`
  re-assembles, rewrites the line with the new disassembly, advances.

When `.` or `m` are called **with arguments** (the user edited a
dump line and pressed RETURN), they enter block-edit mode:
1. Execute the edit (assemble instruction / write bytes)
2. Rewrite their own prompt line to reflect the new state (principle 3)
3. Do **not** clear the next line (principle 5 exception)
4. Advance `cur_addr` to the continuation address (principle 8)

The handler returns.  The prompting loop writes `AAAA:` over the
first five columns of the trailing line (updating the address
prefix) without clearing the rest — the existing dump content
from column 5 onward remains intact and editable.

Without arguments, these same commands are in dump mode (`.` disassembles
one line; `m` dumps `block_size` bytes) and clear the prompt line
normally.

The user can continue editing the next line or cursor back to edit
another line.  This creates a fluid cycle: dump → edit → re-execute
→ advance, all without leaving the screen.

### The `.` command in detail

The `.` handler has three modes:

1. **With hex byte args that differ from memory:** write the bytes to
   memory at `cur_addr`.
2. **With hex byte args that match memory:** pass the remaining text
   (mnemonic + operand) to the line assembler.
3. **Without args:** disassemble one instruction at `cur_addr`.

**Expression support:** In mode 2, the operand is evaluated through
`_expr_eval` before being passed to the line assembler.  This means
full expressions work in the `.` command:

    1000:. lda screen+$20     ; label + arithmetic
    1000:. sta <addr           ; lo byte operator
    1000:. ldx #cols-1         ; constant expression

Symbols and labels from the last source assembly (`a` command) are
available, since the symbol table heap persists between assemblies.

The operand is evaluated to a numeric value, formatted as `$XX` or
`$XXXX` (based on `expr_wide`), and the prefix/suffix characters
(`#`, `(`, `,x`, `)`, etc.) are preserved around it.  The formatted
string is then passed to `_asm_line` which handles only hex operands.

In all three cases, the handler finishes by disassembling the
instruction at `cur_addr` and rewriting the prompt line with the
result.  What's on screen always reflects the actual memory state.

### Line format and address handling

`AAAA:cmd [args]` or bare `cmd [args]`.  `;` terminates parsing
(inline comment).

If the line begins with `AAAA:`, the parser sets `cur_addr` to AAAA
before dispatching the command.  Commands operate on `cur_addr`, which
they may override with an optional address argument of their own.
After execution, commands update `cur_addr` to point past all the
bytes they consumed.

### Line editor rules

The REPL's line editor operates within the 40-column screen:

1. **Cursor movement stays within the screen.**  Left/right/up/down
   move within the visible 40×25 area.  No wrapping between lines,
   no scrolling.
2. **Character insertion fills up to column 38.**  Column 39 is
   reserved for the cursor.  Overflow shifts characters out at the
   right edge.
3. **DEL (backspace) left-deletes.**  Content right of the cursor
   shifts left; a space shifts in from the right edge.  Stops at
   start of line.  If column 5 contains `:` (a clean prompt line),
   stops at column 6 to protect the `AAAA:` prefix.  Cursor
   movement can still position past the `:` for on-screen edits.
4. **INS right-shifts.**  Content at and right of the cursor shifts
   right; a space opens at the cursor.  Overflow at column 38 is
   lost.

### Line formats (40 columns)

    AAAA:. HH HH HH  MNEMONIC OPERAND     asm / disasm
    AAAA:m HH HH HH HH HH HH HH HH cccc hex dump / edit
    r pc:XXXX a:XX x:XX y:XX s:XX nv-bdizc CPU registers

### Commands — Memory

| Key | Name     | Addressed | Example                     | Notes                                      |
|-----|----------|-----------|-----------------------------|----------------------------------------------|
| `m` | memory   | yes       | `1000:m` dump, `1000:m A9 00...` edit | Bare = dump `B` bytes; with hex = edit  |
| `f` | fill     | yes       | `1000:f EA`                 | Fill `B` bytes with value *(planned)*        |
| `>` | transfer | yes       | `1000:> 2000`               | Copy `B` bytes from AAAA to arg *(planned)*  |
| `/` | search   | yes       | `1000:/ A9 00`              | Search for byte pattern *(planned)*          |

### Commands — Assembly / Disassembly

| Key | Name       | Addressed | Example              | Notes                                        |
|-----|------------|-----------|-----------------------|----------------------------------------------|
| `.` | asm/disasm | yes       | `1000:. lda #$00`    | Single instruction; full expressions in operands |
| `d` | disassemble| yes       | `1000:d`              | Disassemble `b` bytes (block mode)           |
| `a` | assemble   | —         | `a`                   | Assemble source buffer (two-pass)            |

### Commands — Execution

| Key | Name | Addressed | Example          | Notes                                      |
|-----|------|-----------|------------------|--------------------------------------------|
| `j` | jump | yes       | `1000:j` or `j main` | Start execution at expression. Patches breakpoints, enters debugger loop. Shows registers on break/RTS. |
| `g` | go   | —         | `g`              | Shorthand for `j main`. Falls back to `j cur_addr` if `main` undefined. |
| `c` | continue | —    | `c`              | Continue from last break (BRK/NMI). Error if no active break context. |

### Commands — Debug / Trace

| Key | Name      | Addressed | Example         | Notes                                    |
|-----|-----------|-----------|-----------------|------------------------------------------|
| `r` | registers | —         | `r` or `r a:05...` | View / edit CPU registers             |
| `b` | breakpoint| —         | `b $1020`, `b main`, `b -1`, `b *` | Set (expr), delete, list. See [debugger.md](debugger.md). |
| `t` | trace     | —         | `t` or `t 5`    | Step-into N instructions (default `B`). Enters subroutines. |
| `o` | trace over| —         | `o` or `o 5`    | Step-over N instructions (default `B`). JSR runs to completion. |

### Commands — Navigation

| Key | Name    | Addressed | Example       | Notes                                    |
|-----|---------|-----------|---------------|------------------------------------------|
| `@` | seek    | —         | `@ $C000` or `@ main` | Set `cur_addr` to expression; bare = no-op |
| `B` | block   | —         | `B 40`        | Set block size (hex bytes); bare = show (uppercase) |
| `+` | forward | —         | `+` or `+ $20` | Advance cur_addr by block_size (or expr) |
| `-` | back    | —         | `-` or `- $20` | Retreat cur_addr by block_size (or expr) |

### Commands — I/O

| Key | Name   | Addressed | Example              | Notes                                   |
|-----|--------|-----------|----------------------|-----------------------------------------|
| `l` | load   | yes       | `1000:l "file"`      | Load PRG to addr; remembers filename     |
| `s` | save   | yes       | `1000:s "file" $2000` | Save addr..EEEE-1 (expr); remembers filename |
| `$` | disk   | —         | `$`, `$9`, `$ s:file` | Directory, drive select, drive command *(cmd planned)*. See below. |

### Commands — Info / Utility

| Key   | Name    | Addressed | Example               | Notes                                |
|-------|---------|-----------|----------------------|--------------------------------------|
| `i`   | info    | —         | `i`                  | Show memory map                       |
| `?`   | calc    | —         | `? 1000+20`          | Hex expression calculator             |
| `k`   | kill    | —         | `k`                  | Clear source buffer (confirms first)  |
| `B`   | block   | —         | `B 40` or `B`       | Set/show block size (uppercase)        |
| `C`   | color   | —         | `C 06` or `C 0e6`   | Set text/bg/border color (uppercase)  |
| `T`   | tab     | —         | `T 4` or `T`         | Set/show tab width; reindents source (uppercase) |
| `u`   | cpu     | —         | `u 6502` or `u 65c02` | Set CPU mode for asm/disasm        |
| `q`   | quit    | —         | `q`                  | Exit CSE                              |
| `clr` | clear   | —         | `clr` (or `cls`)     | Clear screen                          |
| `;`   | comment | —         | `; note`             | No-op (inline comment)                |

### `B` — Block size (uppercase)

The `B` command sets a 16-bit block size used by `m`, `d`, `f`, `>`,
`/`, `t`, `o`, and `+`/`-` navigation.  Default: `$0010` (16 bytes
= 2 hex dump lines).

    B 40     set to 64 bytes (8 hex lines)
    B C0     set to 192 bytes (full screen of hex)
    B 0100   set to 256 bytes (4-digit)
    B        show current block size

### `$` — Disk

The `$` command is a unified interface for disk directory, drive
selection, and drive commands.  Parsing is prefix-based:

    $              directory listing (current drive)
    $9             select drive 9 as current, show directory
    $ s:file       send drive command (scratch file)
    $ i            send drive command (initialize)
    $9 s:file      select drive 9, send command

A single digit after `$` (8 or 9) sets `cur_device` permanently.
Any other argument is sent to the drive command channel (#15)
*(planned — requires disk.s extension)*.
Bare `$` lists the directory.

### `T` — Tab width

The `T` command (uppercase) sets the editor's tab stop interval.
Default: `8`.  Value range: 1–32 (hex).

    T 4      set to 4 columns
    T 8      set to 8 columns
    T        show current tab width

When the tab width changes, `ed_reindent` walks every line in the
source buffer.  Leading spaces are decomposed into indent levels
and a remainder: `levels = spaces / old_width`, `remainder = spaces
% old_width`.  The new indent is `levels * new_width + remainder`.
This preserves sub-tab-stop alignment while rescaling full indent
levels.

### `i` — Memory map

    zp   0002-007f cse runtime
    stk  0100-01ff 6502 stack
    scr  0400-07e7 screen
    cse  0801-2a4f code+data+bss
    free 2a50-c7ff 40880 bytes
    cstk c800-cfff c stack
    src  ----      (not allocated)
    sym  ----      (not allocated)
    io   d000-dfff vic/sid/cia
    kern e000-ffff kernal rom

### `C` — Color (uppercase)

Accepts 1, 2, or 3 single hex digits.  Extra characters ignored.

    C 6          set text color to blue
    C 06         set bg=black, text=blue
    C 0e6        set border=black, bg=dark grey, text=blue

### `u` — CPU mode

    u 6502       standard NMOS 6502
    u 6510       6510 (with illegal opcodes)
    u 65c02      WDC 65C02 (CMOS extensions)

### Free / reserved keys

    e   reserved — editor mode (source buffer)
    h   free (was hunt, now `/`)
    n   free (was next/step-over, now `o`)
    p   reserved — print / evaluate
    v   reserved — visual mode (split screen?)
    w   free (was write/save, now `s`)
    x   free (was breakpoints, now `b`)
    y   free
    z   free

### Emitters

Single-line output functions, called by both edit-mode and block-mode
paths:

- `emit_dot(addr)` — writes `AAAA:. HH HH HH  MNE OPR`, returns
  instruction length.  Two spaces between hex bytes and mnemonic.
- `emit_mem(addr, cols)` — writes `AAAA:m HH HH HH HH HH HH HH HH cccc`
- `emit_reg()` — writes `r pc:xxxx a:xx x:xx y:xx s:xx nv-bdizc`
  (lowercase, active flags shown as letter, inactive as `.`)

Each emitter starts at column 0 and calls `clear_eol` at the end.

### Implementation status

    [x] .   asm/disasm single instruction
    [x] d   disassemble block
    [x] m   memory dump / edit
    [x] a   assemble source buffer
    [x] j   JSR / start execution
    [x] r   registers view / edit
    [x] @   seek (was s)
    [x] $   directory listing (+ drive select, + drive command)
    [x] q   quit
    [x] clr clear screen
    [x] +   seek forward
    [x] -   seek backward
    [x] i   memory map info
    [x] ?   hex expression calculator
    [x] B   block size (uppercase, was `b`)
    [x] C   color theme (uppercase, was `c`)
    [x] T   tab width (uppercase)
    [x] u   cpu mode select
    [x] k   kill source (clear editor buffer, confirms first)
    [x] l   load file from disk
    [x] s   save memory to disk (was `w`)
    [x] b   breakpoints (was `x`). See debugger.md
    [x] c   continue execution (was color). See debugger.md
    [x] t   trace / step-into. See debugger.md
    [x] o   trace over / step-over (was `n`). See debugger.md
    [x] g   go — shorthand for j main (falls back to j cur_addr)
    [ ] f   fill
    [ ] >   transfer
    [ ] /   search (was `h`)
    [ ] =   labels

## Caveats

- `read_line` reads screen RAM at the cursor row, converting screen
  codes to PETSCII.  Lowercase screen codes ($01–$1A) map to $41–$5A;
  uppercase screen codes ($41–$5A) map to $C1–$DA.  This preserves
  case for command dispatch.
- `exec_line` modifies `cur_addr` as a side effect of the `AAAA:` prefix.
- The `?` command uses `_expr_eval` directly — labels from the last
  assembly are available.
- **Expression arguments:** Commands `@`, `j`, `+`, `-`, `b`, `s` accept
  full expressions (`$hex`, decimal, symbols, operators).  Bare digits
  are decimal — hex requires `$` prefix.  The `AAAA:` prompt prefix and
  `t`/`o` counts remain plain hex.  `B` block size is also plain hex.
- File type (PRG vs SEQ) detected by `,s` suffix in filename.
