# CSE Source Assembler Syntax

## Lines

```
[label[:]]  [instruction | directive]  [; comment]
```

Blank lines and comment-only lines are ignored. Labels can optionally
end with `:`. Everything after `;` is a comment.

## Labels

```
main            ; label = current PC (no colon)
main:           ; label = current PC (with colon)
.loop           ; local label (dot prefix, scoped to last global)
.loop:          ; local with colon
```

Labels at the start of a line, followed by an instruction or nothing.
Case insensitive. Characters: a-z, 0-9, dot. No underscore.
Local labels are stored as `global.local` (full path) in the symbol table.

## Constants

```
screen = $0400
cols   = 40
mask   = %11110000
border = vic + $20
```

`name = expression` defines a constant. The expression is evaluated
immediately. Width (ZP/ABS) is inherited from the expression.

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
- `$ff` — hex (requires $ prefix)
- `42` — decimal (bare digits)
- `%10101010` — binary (requires % prefix)

### Operators (by precedence, loosest first)
- `£` `&` `^` — OR (pound key), AND, XOR (↑ key)
- `+` `-` — add, subtract
- `*` `/` `<<` `>>` — multiply, integer divide, shift left/right
- `!` `<` `>` — NOT (complement), lo byte, hi byte (unary prefix)
- `(` `)` — grouping

### Special
- `*` alone (not binary operator) — current PC

## Directives

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
```

Emits one byte per comma-separated expression. String characters
emit their PETSCII value.

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
```

Like `.str` but converts PETSCII to C64 screen codes.
Useful for direct screen memory writes.

### `.res` — Reserve / Fill

```
.res 16             ; reserve 16 bytes (filled with $00)
.res 256, $ea       ; reserve 256 bytes filled with $EA (NOP)
.res $100           ; reserve a full page
```

Advances PC by N bytes. In pass 2, emits N copies of the fill byte
(default $00). Useful for BSS-style reservations and padding.

### `.align` — Align PC

```
.align 256          ; align to next page boundary
.align $100         ; same thing
.align 4            ; align to 4-byte boundary
```

Advances PC to the next multiple of the given value. The gap is
filled with $00. If PC is already aligned, does nothing.

### `.bin` — Include Binary Data

```
.bin "sprite.bin"
.bin "charset.bin"
```

Reads a raw binary file from disk and emits its contents at the
current PC. Advances PC by the file size. Useful for embedding
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

border = $d020
delay  = 4

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
