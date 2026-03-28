# CSE Source Assembler Syntax

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
| `.org` | expr | Set `al_pc` and `_asm_org` | Set `al_pc` only |
| `.const` | name expr | `sym_define(name, expr_val)` | Skip |
| `.cpu` | model | Set `al_cpu` | Set `al_cpu` |
| `.db` | expr [, ...] | Advance `al_pc` by count | Emit bytes |
| `.dw` | expr [, ...] | Advance `al_pc` by 2×count | Emit words (little-endian) |
| `.str` | "text" [, ...] | Advance `al_pc` by length | Emit PETSCII bytes |
| `.scr` | "text" [, ...] | Advance `al_pc` by length | Emit screen code bytes |
| `.res` | count [, fill] | Advance `al_pc` by count | Emit fill bytes (default $00) |
| `.align` | boundary | Advance `al_pc` to next multiple | Emit $00 padding |

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

### `.bin` — Include Binary Data (planned)

**Not yet implemented.** Will read a raw binary file from disk
and emit its contents at the current PC.  Useful for embedding
sprite data, character sets, music, etc.

### `.inc` — Include Source File (planned)

**Not yet implemented.** Will read and assemble source from a
separate file mid-assembly. Primary use case: shared constant
definitions and hardware address headers.

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
