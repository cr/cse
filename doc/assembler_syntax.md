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
or followed by an instruction.  A `:` with no name in front of it
(a lone `:`, `x: : nop`) is an error, `;?N: exp id`; the rest of the
line is skipped.

Case insensitive (input is folded to uppercase internally).
No underscore (not typeable on C64 keyboard).

**Grammar.**

| Form | Rule | Examples |
|------|------|----------|
| global label | a letter, then letters and digits | `main:`, `loop2:` |
| local label | a dot, then one or more letters and digits | `.loop:`, `.1:` |

Local labels (dot prefix) are scoped to the last preceding global
label and stored as `global.local` in the symbol table.  A label that
breaks the grammar — `a_b:`, `5x:`, `a.b:`, `.:` — is `;?N: exp id`
and is not defined.

**References.**  In an operand or expression a name is a global
(`main`), a local of the current scope (`.loop` — the assembler
prefixes the current global), or a *qualified* local of any scope
(`main.loop`).  Only a dot that starts a name gets the scope prefixed;
a dot inside a name never does.

The symbol table holds 256 symbols (labels, constants and the
built-ins `workstart`/`workend`) with 2304 bytes of names; a label or
constant that does not fit is `;?N: sym full` and stays undefined.

A label name is at most **23 characters** — for a local label, the
part after the dot.  A longer one is `;?N: too long` and is not
defined (a too-long global label also clears the scope).  An
instruction's text, after each local reference `.name` in its operand
is expanded to `global.name`, must fit the assembler's 57-character
instruction buffer; a longer one is `;?N: too long` as well.

## Constants

```
.const screen $0400
.const cols   40
.const mask   %11110000
.const border vic + $20
```

`.const name expression` defines a constant.  The expression is
required (`.const k` alone is `;?N: bad val`) and evaluated
immediately.  Width (ZP/ABS) is inherited from the
expression.

## Instructions

```
lda #$42
sta screen
beq .loop
jmp (table)
rol a
rol                  ; same as `rol a` — bare form = ACC
```

Standard 6502/6510/65C02 mnemonics on C64 builds; 6502/4510/45GS02
mnemonics on the m65 build — the CPUs of the build's CPU set
([build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets)).
Operands support the full expression syntax (labels, arithmetic, lo/hi
byte operators, etc.).

### 4510 and 45GS02 instructions (m65)

```
ldz #$00            ; 4510: Z register
lda ($fb),z         ; 4510: zero-page indirect adds Z
lda ($02,sp),y      ; 4510: stack-relative, also written ($02,s),y
phw #$1234          ; 4510: push word (16-bit immediate)
bne far_away        ; 8-bit or 16-bit offset, chosen by distance
ldq ($fb)           ; 45GS02: 32-bit load into Q (A,X,Y,Z)
adcq $10            ; 45GS02: Q form, stem + q
staq $2000          ; 45GS02: same as `stq $2000`
lda [$fb],z         ; 45GS02: far — 32-bit pointer at $fb
rmb3 $12            ; bit-op: the bit number is the mnemonic's digit
```

The full spelling contract — which forms are accepted, which are
refused, and how the disassembler lists each — is
[asm_line.md § Mnemonic word](modules/asm_line.md#mnemonic-word);
the operand forms are [addr_mode.md § Design](modules/addr_mode.md#design).
Branch width and forward references:
[asm_line.md § Branches](modules/asm_line.md#branches-zone-b).

### Accumulator addressing — bare and explicit forms

The six mnemonics ASL, LSR, ROL, ROR (always) and INC, DEC (CMOS
only) accept accumulator mode in two equivalent forms:

| Form | Example | Bytes |
|------|---------|-------|
| bare mnemonic | `asl` | $0A |
| explicit `A` | `asl a` | $0A |

For all *other* mnemonics, `A` in operand position is parsed as a
one-character label.  This is what lets `jmp a`, `lda a`, `jsr a`,
`bne a`, etc. resolve a defined symbol `a`.

**Shadow rule.** If the user defines a label named `a` and then
writes the explicit form `asl a` (or any of the six ACC-accepting
mnemonics), accumulator mode wins — the symbol is *shadowed*.  The
assembler emits `;!a shadow` once per occurrence, on pass 1.  To
read or write memory at symbol `a` from one of these six mnemonics,
use a different label name, or write the address explicitly:

```
.const a $2000      ; defines symbol `a`
asl a               ; ACC mode → $0A      (warning: ;!a shadow)
asl a+0             ; address mode → $0E $00 $20  (no warning)
asl $2000           ; address mode → $0E $00 $20
```

`X` and `Y` are not register tokens at the start of an operand —
they only appear as the trailing index in `,X` / `,Y` forms — so
labels named `x` or `y` are unambiguous and never shadowed.

## Expressions

Anywhere a value is expected, the full expression parser is available:

```
lda #<screen        ; lo byte of label
sta table+40        ; label + arithmetic
ldx #cols-1         ; constant in expression
lda #mask & $0f     ; bitwise AND
```

An immediate operand (`#expr`) must fit a byte — 0–255, or −128..−1
for a negative value; a larger one is `;?N: ovfl`, never truncated.
Use `#<expr` / `#>expr` to take a byte of a 16-bit value.

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

A directive is the whole word after the dot and must be one of the
names below exactly, followed by whitespace, a `;` comment or the end
of the line; anything else (`.oops`, `.co`, `.dbx`) is
`;?N: bad insn`.

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
.org $1000
```

Sets the program counter. All subsequent code/data emits to this address.
Default: `$0800`.  Code before the first `.org` is assembled at the
default origin.

**Output stays in the workspace.**  Every byte the assembler emits —
instructions and data directives alike — must land in the workspace,
`workstart` ≤ address ≤ `workend` (`$0800` up to the byte below the
source text; [memory_design.md § Memory Map](memory_design.md#memory-map--runtime-all-targets)),
the same range the breakpoint gate accepts.  A byte outside it (CSE's
own code above the source, I/O, the RAM under the KERNAL, zero page,
or past `$FFFF`) is not written, and its line reports `;?N: range`
once.  The program counter still advances, so labels stay where the
layout puts them.

### `.cpu` — Set CPU Mode

```
.cpu 6502           ; legal opcodes only
.cpu 6510           ; legal + illegal opcodes        (C64 builds)
.cpu 65c02          ; legal + CMOS extensions        (C64 builds)
.cpu 4510           ; 65C02 set + 4510 additions     (m65)
.cpu 45gs02         ; 4510 + Q and far forms         (m65, default)
```

Affects which mnemonics and addressing modes are accepted.  Only the
members of the build's CPU set are accepted; any other value is an
error.  `.cpu` applies from its line to the end of the source (or the
next `.cpu`); lines above it use the CPU the assembly started with —
on both passes.  After the assembly the REPL's CPU (`u`) is unchanged.

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

**Forward refs not allowed.**  The count and fill expressions must
resolve on pass 0 — the directive's pass-0 size depends on the
count's value.  `.res FORWARD_LABEL` reports `;?<line>: fwd ref` on
both passes.  Define the count above the directive that uses it
(`.const COUNT 16` then `.res COUNT`), or use a literal number.

### `.align` — Align PC

```
.align 256          ; align to next page boundary
.align $100         ; same thing
.align 4            ; align to 4-byte boundary
```

Advances PC to the next multiple of the given value. The gap is
filled with $00. If PC is already aligned, does nothing.

**Forward refs not allowed.**  Like `.res`, the boundary expression
drives pass-0 size and so cannot tolerate an unresolved symbol.
`.align FORWARD_LABEL` reports `;?<line>: fwd ref`.

### Forward references

Labels defined later in the source can be used in expressions for
most directives and instruction operands — the assembler runs two
passes (sizing then emit) so forward refs to *labels* always work
in `.db`, `.dw`, branches, and absolute jumps:

```
        jmp end             ; OK — `end` is defined below
        .dw  end             ; OK — emits the address
        .db  <end, >end      ; OK — lo/hi bytes
end:    rts
```

The exception is `.res` and `.align`, where the *value* of the
expression determines how much PC advances on pass 0.  Those two
directives reject forward refs vocally on both passes.

A forward reference is always sized **absolute**, even when the
symbol's value later turns out to fit in a byte: `lda zp` above
`.const zp $10` assembles to `AD 10 00`.  Define zero-page constants
above their first use to get the 2-byte form.  A `.const` itself must
not read a later-defined symbol: `.const k later+1` is
`;?N: fwd ref` and `k` stays undefined.

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
; asm...
; org  0801-0814  20b
; org  1000-1002  3b
; org  2000-2003  4b
; ok
0801:s "t-org,p" $2004
```

- **Header:** `; asm...` — the repl header (stays open during pass 1).
- **Segment lines:** One `; org  AAAA-BBBB  NNb` line per `.org`
  or `.bas` block.  Printed inline during pass 1.  Addresses are
  plain hex (no `$` prefix).  Empty segments (0 bytes) are suppressed.
- **OK line:** `; ok` — printed after successful pass 1.
- **Save command:** Executable REPL line placed last so
  cursor-up+return saves the assembled PRG.  Format:
  `AAAA:s "name,p" $EEEE` where AAAA is the lowest origin,
  EEEE is the highest byte (inclusive, matching the `AAAA-BBBB`
  range convention used everywhere), and name is the loaded
  filename with `,s` → `,p` suffix (or `"out,p"` if none).
  Suppressed when no bytes were emitted.

On error, the segment lines still appear (they print during pass 1)
but the ok and save lines are suppressed.  The error count is shown:
`; N errors`.

## Example Program

```
; simple border color cycler

.cpu 6502
.org $1000

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
