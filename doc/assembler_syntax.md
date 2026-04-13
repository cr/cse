# Assembler Syntax — Source language specification

**Template:** [subsystem](templates/subsystem.md)

## Lines

```
[label:]  [instruction | directive]  [; comment]
```

Blank lines and comment-only lines are ignored.  Everything after
`;` is a comment.

## Labels

```
main:           ; global label = current PC
.loop:          ; local label (scoped to last global)
main: lda #0   ; label and instruction on the same line
```

Labels end with `:` (required).  A label may appear alone on a line
or followed by an instruction.

Case insensitive (input is folded to uppercase internally).
Characters: a-z, 0-9, dot.  No underscore (not typeable on C64
keyboard).

Local labels (dot prefix) are scoped to the last preceding global
label and stored as `global.local` in the symbol table.

## Constants

```
.const screen $0400
.const cols   40
.const mask   %11110000
.const border vic + $20
```

`.const name expression` defines a constant.  The expression is
evaluated immediately.  Width (ZP/ABS) is inherited from the
expression.

## Instructions

```
lda #$42
sta screen
beq .loop
jmp (table)
rol a
```

Standard 6502/65C02 mnemonics. Operands support the full expression
syntax (labels, arithmetic, lo/hi byte operators, etc.).

## Expressions

Anywhere a value is expected, the full expression parser is available:

```
lda #<screen        ; lo byte of label
sta table+40        ; label + arithmetic
ldx #cols-1         ; constant in expression
lda #mask & $0f     ; bitwise AND
```

### Numeric formats
- `$ff` — hex (requires `$` prefix, digits 0-9 and a-f lowercase only)
- `42` — decimal (bare digits)
- `%10101010` — binary (requires `%` prefix)

Hex digit count selects ZP vs ABS encoding: `$00`–`$ff` (1–2 digits)
→ ZP, `$000`–`$ffff` (3–4 digits) → ABS.  `$0042` forces absolute
even though the value fits in a byte.  Width is sticky: if any term
in an expression is ABS, the whole expression is ABS (`$00 + $0000`
→ ABS).  See [expr.md](modules/expr.md) for full width propagation
rules.

### Operators (by precedence, loosest first)
- `£` `&` `^` — OR (pound key), AND, XOR (↑ key)
- `+` `-` — add, subtract
- `*` `/` `<<` `>>` — multiply, integer divide, shift left/right
- `-` `!` `<` `>` — negate, NOT (complement), lo byte, hi byte (unary prefix)
- `(` `)` — grouping

### Special
- `*` alone (not binary operator) — current PC

## Directives

### Summary

| Directive | Args | Pass 0 (collect) | Pass 1 (emit) |
|-----------|------|-------------------|---------------|
| `.org` | expr | Set `asm_pc` and `_asm_org` | Set `asm_pc` only |
| `.const` | name expr | `sym_define(name, expr_val)` | Skip |
| `.cpu` | model | Set `asm_cpu` | Set `asm_cpu` |
| `.db` | expr [, ...] | Advance `asm_pc` by count | Emit bytes |
| `.dw` | expr [, ...] | Advance `asm_pc` by 2×count | Emit words (little-endian) |
| `.str` | "text" [, ...] | Advance `asm_pc` by length | Emit PETSCII bytes |
| `.scr` | "text" [, ...] | Advance `asm_pc` by length | Emit screen code bytes |
| `.res` | count [, fill] | Advance `asm_pc` by count | Emit fill bytes (default $00) |
| `.align` | boundary | Advance `asm_pc` to next multiple | Emit $00 padding |
| `.bas` | ["text"] | Advance `asm_pc` past stub | Emit BASIC SYS stub |

### `.org` — Set Origin

```
.org $c000
```

Sets the program counter. All subsequent code/data emits to this address.
Default: `$0800`.

### `.cpu` — Set CPU Mode

```
.cpu 6502           ; legal opcodes only
.cpu 6510           ; legal + illegal opcodes
.cpu 65c02          ; legal + CMOS extensions
```

Affects which mnemonics and addressing modes are accepted.
Limited by the build-time CPU ceiling.

### `.db` — Define Bytes

```
.db $41, $42, $43
.db 0
.db <label, >label
.db "A"             ; single character as byte value
.db "ABC"           ; multi-character: emits 3 bytes
```

Emits one byte per comma-separated expression.  Quoted strings emit
each character as its PETSCII value (multi-character strings are
expanded inline).

### `.dw` — Define Words

```
.dw $1234
.dw label, label+$100
```

Emits 16-bit values in little-endian order (lo byte first).

### `.str` — PETSCII String

```
.str "hello world"
.str "score: "
.str "hello", 0     ; string followed by explicit NUL
```

Emits PETSCII bytes for each character. Does NOT automatically
NUL-terminate — add `, 0` if needed. Supports escape sequences:
(TBD — probably none for v1, raw PETSCII).

### `.scr` — Screen Code String

```
.scr "HELLO WORLD"
.scr "SCORE: ", 0    ; trailing byte expressions supported
```

Like `.str` but converts PETSCII to C64 screen codes (full 6-range
mapping: $40-$5F−$40, $60-$7F−$20, $C0-$DF−$80, others identity).
Useful for direct screen memory writes.

### `.res` — Reserve / Fill

```
.res 16             ; reserve 16 bytes (filled with $00)
.res 256, $ea       ; reserve 256 bytes filled with $EA (NOP)
.res $100           ; reserve a full page
```

Advances PC by N bytes. In pass 1, emits N copies of the fill byte
(default $00). Useful for BSS-style reservations and padding.

### `.align` — Align PC

```
.align 256          ; align to next page boundary
.align $100         ; same thing
.align 4            ; align to 4-byte boundary
```

Advances PC to the next multiple of the given value. The gap is
filled with $00. If PC is already aligned, does nothing.

### `.bas` — Emit BASIC SYS Stub

```
.org $0801
.bas                ; emit "0 SYS <addr>"
```

```
.org $0801
.bas "MY PROGRAM"   ; emit "0 SYS <addr>:REM MY PROGRAM"
```

Emits a single-line BASIC program that calls the code immediately
following the stub via `SYS`.  Makes the assembled PRG auto-runnable:
`LOAD "FILE",8,1` then `RUN`.

The SYS address (always 5 decimal digits) is the first byte after
the BASIC end marker — where `asm_pc` points after `.bas` completes.

With a string argument, `:REM text` is appended on the same BASIC
line.  The REM text appears in `LIST` output as a program title.

Byte layout:

| Offset | Bytes | Content |
|--------|-------|---------|
| +0 | 2 | Link pointer → end marker |
| +2 | 2 | Line number 0 |
| +4 | 1 | SYS token ($9E) |
| +5 | 5 | 5-digit decimal SYS address |
| +10 | 0 or 2+len | `:` + REM token + string (if present) |
| | 1 | Null terminator |
| | 2 | $0000 end of BASIC program |

Total: 13 bytes (no string) or 15 + len (with string).

## Assembly Output

On successful assembly, the `a` command prints:

```
; asm...ok
; org  0801-0814  20b
; org  1000-1002  3b
; org  2000-2003  4b
0801:s "t-org" $2004
```

- **Header:** `; asm...ok` — the repl header with success status.
- **Segment lines:** One `; org  AAAA-BBBB  NNb` line per `.org`
  or `.bas` block.  Addresses are plain hex (no `$` prefix).
  Empty segments (0 bytes) are suppressed.
- **Save command:** Executable REPL line placed last so
  cursor-up+return saves the assembled PRG.  Format:
  `AAAA:s "name" $EEEE` where AAAA is the lowest origin,
  EEEE is one past the highest byte, and name is the loaded
  filename (or `"out"` if none).

On error, the segment summary and save command are suppressed.
Only the error count is shown: `; asm...N errors`.

## Example Program

```
; simple border color cycler

.cpu 6502
.org $c000

.const border $d020
.const delay  4

main:   ldx #0
.loop:  stx border
        ldy #delay
.wait:  dey
        bne .wait
        inx
        bne .loop
        rts

; data
colors: .db 0, 6, 14, 3, 1
        .db 0
```
