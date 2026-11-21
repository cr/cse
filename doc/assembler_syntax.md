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
label and stored as `global.local` in the symbol table.  A reference
to a local label with no global label above it is `;?N: exp val`;
start the source with a global label before the first local one.  A label that
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

`.const name expression` defines a constant.  The name follows the
global-label grammar ([§ Labels](#labels)): `.const 5 5` or
`.const a.b 1` is `;?N: exp id`.  The expression is
required (`.const k` alone is `;?N: bad val`) and evaluated
immediately.  Width (ZP/ABS) is inherited from the
expression.

**On m65** a constant is 32 bits — `.const far
4.2000`, `.const big 100000` ([expr.md § 32-bit
values](modules/expr.md#32-bit-values-m65)).  Where a 16-bit value is
taken — an operand, `.db` / `.dw` / `.res` / `.align` — a value
outside −$FFFF…$FFFF is refused, never truncated: an operand is `;?N:
range`, a directive's argument `;?N: bad val`.  `<(x>>16)` and
`>(x>>16)` take its bytes 2 and 3 (slice 3, F5a).

## Instructions

```
lda #$42
sta screen
beq .loop
jmp (table)
rol a
rol                  ; same as `rol a` — bare form = ACC
```

The mnemonics of the build's CPU set — 6502 and 6510 on the C64
builds; 6502, 4510 and 45GS02 on the m65 build
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
ldq ($fb),z         ; 45GS02: 32-bit load into Q (A,X,Y,Z)
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

The six mnemonics ASL, LSR, ROL, ROR (always) and INC, DEC (4510
and the CMOS mode only) accept accumulator mode in two equivalent forms:

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

**On m65** a value is 32 bits and two more literal forms exist:
`$` with 5–8 hex digits (width FAR), decimal and binary up to
`$FFFFFFFF`, and the flat literal `H.AAAA` — one to four hex digits
(a value up to $FFF), a dot, exactly four hex digits, its first
character a digit (`4.2000`, `0ffd.3000`) — which is `H` × $10000 +
`AAAA`
([expr.md § 32-bit values](modules/expr.md#32-bit-values-m65)).

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
`;?N: bad insn`.  Its arguments end the line: after them only
whitespace, a `;` or `//` comment may follow — `.db 1 2`, `.org $c000
junk`, `.cpu 6502 x` are `;?N: bad val`, the line laid out as far as
it was read.  A string (`.db`, `.str`, `.scr`, `.bas`) without its
closing quote is `;?N: exp "`.

| Directive | Args | Effect |
|-----------|------|--------|
| `.org` | expr | Set the program counter |
| `.const` | name expr | Define a constant |
| `.cpu` | model | Set the CPU mode for the following lines |
| `.db` | expr [, ...] | Emit bytes |
| `.dw` | expr [, ...] | Emit words (little-endian) |
| `.dd` | expr [, ...] | m65: emit 32-bit words (little-endian) |
| `.str` | "text" [, ...] | Emit PETSCII bytes |
| `.scr` | "text" [, ...] | Emit screen code bytes |
| `.res` | count [, fill] | Emit `count` fill bytes (default $00) |
| `.align` | boundary | Emit $00 up to the next multiple |
| `.bas` | ["text"] | Set the program counter to BASIC's program start (`$0801`; `$2001` on m65) and emit a BASIC SYS stub |

The assembler runs two passes over the source (sizing, then
emission); the pass mechanics are [asm_src.md](modules/asm_src.md).

**On m65** (slice 3, F5b) `.org` takes a 32-bit expression, a
28-bit address (above `$0FFFFFFF` it is `;?N: bad val`).  Above
`$FFFF` it is a **flat origin** (`.org 4.2000`): the bytes go to that
physical address, `*` and the instructions' own addresses are its low
word — where a far start runs the code — and every label the segment
defines has the flat value (`4.2005`).  A 16-bit value — an
instruction's operand, a branch target, `.dw`'s and `.db`'s
arguments — takes a value above `$FFFF` only when its bank is the
segment's, and then its low word (the **same-bank rule**, P-F-6);
any other is refused as F5a refuses it (`;?N: range` for an operand,
`;?N: bad val` for a directive).  `.org 0.3000` is `.org $3000`, and
a value from −$FFFF to −1 is its low word in bank 0, as the 16-bit
consumers take it (`.org $3000-$10000` is `.org $3000`).

The emit gate admits, besides the program region `$2000–$BFFF` of
bank 0, a flat segment in bank 1 from `1.2000` to `1.F6FF` and in
banks 4 and 5 whole (`4.0000–5.FFFF`; the user memory of
[userland_contract.md § 3](userland_contract.md)); any other byte is
`;?N: range`, written nowhere.  A flat segment wraps at the end of its
bank as a CPU segment does at `$FFFF` (later bytes refused), never
into the next bank.  The segment line names the bank as `i`'s rows
do (`; org  4.2000-2011   18b`); the save suggestion covers bank 0's
segments only — `s` saves CPU memory — so a program wholly in a bank
gets none.

`.dd expr [, ...]` (D-F-8) emits 32-bit words, low byte first, of any
32-bit value (`.dd 4.2000` is `00 20 04 00`).  After `a`, the current
address is `main`'s — flat when `main` is — and `g` starts it: a far
start ([repl.md § Far starts](modules/repl.md#far-starts)) in banks
1, 4 and 5 at `$2000–$7FFF`, else `;?range`.  The REPL's `.` at a flat
current address follows the same-bank rule with that address's bank
(another bank's value is `;?expr range`,
[repl.md § Error tag dispatch](modules/repl.md#error-tag-dispatch-mnemonic-assemble-path)).

### `.org` — Set Origin

```
.org $1000
```

Sets the program counter. All subsequent code/data emits to this address.
The default origin, for code before the first `.org`, is the REPL's
current address when `a` runs (`$0800` after start-up; set it with
`@`) — on m65 a flat one too (`@ 4.2000`, then `a`: the code goes to
bank 4).

**Output stays in the workspace.**  Every byte the assembler emits —
instructions and data directives alike — must land in the workspace,
`workstart` ≤ address ≤ `workend` (`$0800` up to the byte below the
source text; [memory_design.md § Memory Map](memory_design.md#memory-map--runtime-c64-builds)),
the same range the breakpoint gate accepts.  A byte outside it (CSE's
own code above the source, I/O, the RAM under the KERNAL, zero page,
or past `$FFFF`) is not written, and its line reports `;?N: range`
once.  The program counter still advances, so labels stay where the
layout puts them.

### `.cpu` — Set CPU Mode

```
.cpu 6502           ; legal opcodes only
.cpu 6510           ; legal + illegal opcodes        (c64-6510)
.cpu 4510           ; the 65C02's instructions + the 4510's (m65)
.cpu 45gs02         ; 4510 + Q and far forms         (m65, default)
```

Affects which mnemonics and addressing modes are accepted.  Only the
members of the build's CPU set are accepted; any other value is an
error.  `.cpu` applies from its line to the end of the source (or the
next `.cpu`); lines above it use the CPU the assembly started with —
on both passes.  After the assembly the REPL's CPU (`u`) is unchanged.

`.cpu 65c02` (legal + CMOS extensions) belongs to the CMOS mode, which
no target build has.  The 6510 is not offered on m65
([build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets)).

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
expanded inline).  Each value must fit a byte — 0–255, or −128..−1 for
a negative value; a larger one (`.db 256`) is `;?N: ovfl`, never
silently truncated (its low byte is still emitted, so the layout does
not move).  The same holds for the byte list after `.str` / `.scr`.

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

Emits the bytes of the characters as typed (PETSCII), with no escape
sequences.  Does NOT automatically NUL-terminate — add `, 0` if
needed.

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
count's value.  `.res FORWARD_LABEL` reports `;?<line>: fwd ref`
(on pass 0, counted once) and the assembly fails (TODO § Bugs: a
symbol defined nowhere gets `fwd ref` twice).  Define the count
above the directive that uses it (`.const COUNT 16` then
`.res COUNT`), or use a literal number.

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
directives reject a forward reference with `;?<line>: fwd ref` on
pass 0, and the assembly fails.

A forward reference is always sized **absolute**, even when the
symbol's value later turns out to fit in a byte: `lda zp` above
`.const zp $10` assembles to `AD 10 00`.  Define zero-page constants
above their first use to get the 2-byte form.  An operand that can
only be zero-page is sized as one even when it is defined below: the
pointer of `(zp),y`, the `zp` of `BBR`/`BBS`, and on m65 `(zp),z`,
`[zp]`, `[zp],z` and `(d,sp),y` (it must then fit a byte).  The
pointer of `(zp,x)` and the CMOS `(zp)` must be defined above its use
— with a forward value those read as `jmp ($nnnn,x)` / `jmp ($nnnn)`
— else `;?N: bad insn`.  A `.const`
itself must not read a later-defined symbol: `.const k later+1` is
`;?N: fwd ref` and `k` stays undefined.

### `.bas` — Emit BASIC SYS Stub

```
.bas                ; emit "0 SYS <addr>"
```

```
.bas "my program"   ; emit "0 SYS <addr>:REM my program"
```

`.bas` is an implicit `.org $0801` (the start of BASIC; on m65 `$2001`
in bank 0, whatever bank the segment before it was in): it sets the
program counter to $0801 and emits a single-line BASIC program that
calls the code immediately following the stub via `SYS`.  Makes the
assembled PRG auto-runnable: `LOAD "FILE",8,1` then `RUN`.

On m65 the start of BASIC is `$2001` (BASIC 65's, `BASIC_START` in
[platform_layer.md § Constants](platform_layer.md#constants)): `.bas`
is an implicit `.org $2001`, and the same line — BASIC 65 has the
C64's `SYS` and `REM` tokens and line layout — is a program `RUN`
starts in MEGA65 mode.  The link pointer is computed from the PC, so
the layout below holds on both platforms.

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
| +10 | 0 or 3+len | `:` + REM token + space + string (if present) |
| | 1 | Null terminator |
| | 2 | $0000 end of BASIC program |

Total: 13 bytes (no string) or 16 + len (with string); the code after
the stub starts at $080E or $0811 + len.

## Assembly Output

On success the `a` command prints, for example (a `.bas` stub, then
code at $1000 and data at $2000):

```
; asm...
; org  0801-080d    13b
; org  1000-1002     3b
; org  2000-2003     4b
; ok
0801:s "out" $2003
```

- **Header:** `; asm...`.
- **Segment rows:** one `; org  AAAA-BBBB  NNb` row per block of
  output (the default origin, each `.org`, `.bas`), printed as the
  block closes on the emitting pass.  Addresses are plain hex; empty
  blocks are not shown.
- **OK row:** `; ok`.
- **Save line:** an executable REPL line, so cursor-up + RETURN saves
  the assembled PRG: `AAAA:s "name" $EEEE`, where AAAA is the lowest
  emitted address, EEEE the highest (inclusive, the `AAAA-BBBB`
  convention) and `name` the current project name (`out` if none).
  The address argument makes it a PRG save to `name.`
  ([repl.md § Project-name and filename semantics](modules/repl.md#project-name-and-filename-semantics-l-and-s)).
  It covers everything from the lowest to the highest address,
  gaps included.  Not shown when no bytes were emitted.

After `; ok` the REPL's current address moves to `main` if the source
defines it.  On errors each one is a row `;?N: <message>` (`N` = the
source line, e.g. `;?2: undef`), the segment rows still appear, and
the summary is `; N err` instead of `; ok` and the save line.  The
assembler reads the first 39 characters of a line (79 on m65); a
longer line gets a warning `;!N: truncated` and loses the rest.  A
line of exactly 39 (79) characters is read whole and gets no
warning.  The messages:
[README.md § Source-assembly messages](../README.md#source-assembly-messages).

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
