# expr.s — Expression Parser

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/expr.s`](../../src/expr.s) | implementation |
| [`tests/unit/test_expr.py`](../../tests/unit/test_expr.py) | test contract |
| [`tests/unit/test_expr_m65.py`](../../tests/unit/test_expr_m65.py) | test contract: the m65 32-bit values, the range, the symbol table's 4-byte values |

## Interface

### expr_eval
**In:** `expr_ptr` (ZP, pointer to the PETSCII expression text),
`asm_pc` (ZP, value of the `*` operand)
**Out:** A = return code (table below), also stored in `last_err`;
`expr_val` (ZP, 16-bit result; m65 32-bit), `expr_wide` (ZP, 0 =
ZP-eligible, 1 = ABS; m65 3 = FAR); `expr_ptr` advanced to the first unparsed byte
([§ Partial-mode contract](#partial-mode-contract)); `expr_fwd`
(BSS, exported): nonzero iff the expression read a symbol that is
undefined (rc 5, see [§ Undefined symbols](#undefined-symbols)) or
one that `sym_lookup` reported with `sym_fwd` — a forward reference
in the current pass
([symtab.md § Pass stamp](symtab.md#pass-stamp-mega_support)).  Bit 7
marks the undefined case (rc 5); a `sym_fwd` read only sets other
bits and also makes the result wide, matching the ABS size pass 0
gave the then-undefined symbol.
**Clobbers:** A, X, Y; `_ex_tmp`, `_ex_digits` (ZP; m65 BSS); `_ex_depth`,
`_mul_tmp`, `_div_rem`, on m65 `_ex_sp`, `_ex_stk`, `_ex_far` (BSS); `sym_name`, and through `sym_lookup`
`sym_val`, `sym_wide`, `sym_fwd` and symtab's ZP scratch.  **Writes
the input text:** a shifted letter ($C1–$DA) inside a label is folded
to $41–$5A in place, and the byte after each label is NUL'd for the
lookup and then restored.

`expr_eval` owns its KERNAL banking — callers don't manage it.  It
brackets the evaluation with `kernal_bank_out` / `kernal_bank_in`
because `sym_lookup` reads `sym_table` and `sym_heap` under the
KERNAL ROM.  `sym_lookup` saves and restores the caller's `$01`, so it
keeps this banking; inside an `asm_assemble` batch (`kernal_out` = 1)
both helpers are no-ops.  Same wrapper structure as `asm_line`
(`asm_line.s`) and `dasm_insn` (`dasm.s`).  Test contract:
`tests/unit/test_expr.py::TestExprEvalBankContract` pins that every
exit path (success ZP, success ABS, error, sym_lookup hit, undefined
symbol) leaves `$01` bit 1 set and the I flag clear.

**Return codes:**

| A | Meaning | `expr_error_str` text |
|---|---------|------|
| 0 | Success, ZP-eligible (value ≤ $FF, no wide factors) | (empty) |
| 1 | Success, ABS (16-bit or forced wide) | (empty) |
| 2 | Error: expected value | `exp val` |
| 3 | Error: overflow (literal too large, or nesting deeper than 10 levels) | `ovfl` |
| 4 | Error: mismatched parentheses | `exp )` |
| 5 | Error: undefined symbol | `undef` |
| 6 | Error: division by zero | `div0` |
| 7 | m65: the value is outside −$FFFF…$FFFF ([§ 32-bit values](#32-bit-values-m65)); never from `expr_eval32` | `range` |

### expr_eval32 (m65)
`expr_eval` without the range check — the 32-bit value as computed ([§ 32-bit values](#32-bit-values-m65)).
**In / Out / Clobbers:** as `expr_eval`.

### expr_eval_nb
The evaluator without the banking bracket, for callers that already
run with the KERNAL banked out — `mode_parse` (addr_mode.s) inside
`asm_line`.  **In / Out / Clobbers:** as `expr_eval`; `$01` is
neither read nor written by the evaluator itself (`sym_lookup`
restores whatever it found).

### expr_error_str
**In:** `last_err` (BSS)
**Out:** A/X = pointer (lo/hi) to the NUL-terminated message for
`last_err` (table above, from `err_str_lo` / `err_str_hi` in
strings.s).  A `last_err` of 7 or more reads as 0 (empty string)
— on m65 8 or more.
**Clobbers:** A, X

### last_err
Exported BSS byte: the last return code (`expr_eval` writes it on
every exit).  `asm_line` also stores 3 into it when an instruction
would run past `$FFFF`, so `expr_error_str` names that error `ovfl`
([asm_line.md](asm_line.md)).

### Memory

**ZP (3 bytes):** `_ex_tmp` (2), `_ex_digits` (1).  The left
operand's width lives on the stack.  m65: none — both are expr.s's
BSS, `_ex_tmp` 4 bytes ([zp.md § The m65 base page](zp.md#the-m65-base-page)).

**BSS (7 bytes):** `last_err` (1, exported), `_ex_depth` (1, nesting
depth), `expr_fwd` (1, exported), `_mul_tmp` (2), `_div_rem` (2).
m65: 216 bytes — `_ex_tmp` (4), `_ex_digits` (1), `_mul_tmp` and
`_div_rem` 4 each, `_ex_far` (1), `_ex_sp` (1) and the operand stack
`_ex_stk` (198,
[§ 32-bit values](#32-bit-values-m65)).

**Depends on:** symtab (`sym_lookup`, `sym_fwd`), mem
(`kernal_bank_out` / `kernal_bank_in` for the wrapper), strings
(`err_str_lo` / `err_str_hi`), zp (`expr_ptr`,
`expr_val`, `expr_wide`, `asm_pc`, `sym_name`, `sym_val`, `sym_wide`,
`_ex_tmp`, `_ex_digits`)

## Design

Recursive descent parser.  Grammar (loosest precedence first):

```
expr       = add_term  (('£' | '&' | '^') add_term)*       [parse_expr]
add_term   = mul_term  (('+' | '-') mul_term)*              [parse_add]
mul_term   = factor    (('*' | '/' | '<<' | '>>') factor)* [parse_mul]
factor     = '$'hex | '%'bin | decimal | '*' | label        [parse_factor]
           | '-' factor | '!' factor | '<' factor | '>' factor
           | '(' expr ')'
```

### 32-bit values (m65)

On m65 a value is 32 bits (slice 3, F5a): `expr_val` is 4 bytes (base
page), `_ex_tmp`, `_mul_tmp` and `_div_rem` 4 (BSS), and every
operator computes in 32 bits by 4-byte loops — `*` and `/` by a
32-bit shift-and-add / shift-and-subtract, a shift count of 32 or more
shifts every bit out.  A result wraps at 32 bits as the c64's wraps at
16.  The c64 stays 16-bit, its code unchanged.

A pending left operand waits on an **operand stack** in BSS
(`_ex_stk`), not the hardware stack: an entry is 6 bytes — the
operator, the width, the 4 value bytes — pushed by `_ex_binop` before
it parses the right operand and popped after.  At most three wait per
expression level (one each in `parse_expr`, `parse_add`,
`parse_mul`) and the depth guard admits 11 levels, so 33 entries (198
bytes); a guard answers `ovfl` past them.  An error returns at once,
leaving the stack to the next evaluation's reset.  The m65 evaluator
therefore pushes only return addresses: its hardware-stack use is
below the c64's 3 bytes a pending operand
([memory_design.md § Kernel stack budget](../memory_design.md#kernel-stack-budget)).

| Factor (m65) | Value | Width |
|---|---|---|
| `$` hex, 1–2 / 3–4 / 5–8 digits | as written (a ninth digit `ovfl`) | ZP / ABS / **FAR** |
| decimal, `%` binary | as written, up to $FFFFFFFF (`ovfl` past it) | by value: ≤ $FF ZP, ≤ $FFFF ABS, else FAR |
| `H.AAAA` — a flat literal, first character a digit 0–9 | `H` × $10000 + `AAAA` | FAR |
| `*` | `asm_pc`'s low word, as on the c64 | by value |
| a label | the symbol's 32-bit value (symtab.md) | as stored, FAR when above $FFFF |

The flat literal is the REPL's (repl.md § Banks): one to four hex
digits with a value up to $FFF, a dot, exactly four hex digits — `4.2000`,
`0ffd.3000` (a leading digit, so `ffd.3000` stays a label).  Digits
not in that shape are a decimal number as before (`4.200` is `4`,
the parse stopping at the dot).

`expr_wide` gains a third value: 0 ZP, 1 ABS, 3 **FAR** (bit 1: the
value, or a factor it came from, is above $FFFF; FAR implies ABS, so
the OR that merges two widths keeps the wider).  `<` and `>` are
bytes 0 and 1 as before (narrow); bytes 2 and 3 are `<(x>>16)` and
`>(x>>16)` (D-F-7).  The return code keeps its meaning: 0 ZP, 1 ABS
or FAR (`expr_wide` tells them apart).

**Range.**  `expr_eval` (and `expr_eval_nb`) serve the 16-bit
consumers — an operand, `.db` / `.dw` / `.org` / `.res` / `.align`,
a REPL argument — so a value outside −$FFFF…$FFFF (in range: the top
word $0000, or $FFFF with a nonzero low word) is **rc 7, `range`**
instead of a truncation; a value inside keeps its low word, so `-1`
is `$FFFF` as on the c64.  **`expr_eval32`** is the same evaluator
with the check off, for the consumers that take 32 bits: a constant
(`.const`, symtab.md) and `?`.  The opt-in lasts one evaluation.

### Width propagation

The ZP flag `expr_wide` decides whether the result selects 2-byte (ZP)
or 3-byte (ABS) instruction encoding.  `expr_eval` resets it to 0
(narrow) on entry; leaves set it, operators combine it.

Width sources (leaves):

| Factor | Narrow (ZP) | Wide (ABS) |
|--------|-------------|------------|
| `$` hex literal | 1–2 digits (`$00`–`$ff`) | 3–4 digits (`$000`–`$ffff`) |
| Decimal literal | value ≤ $FF | value > $FF |
| `%` binary literal | value ≤ $FF | value > $FF |
| Label | `sym_wide` = 0 at definition, read backward | `sym_wide` = 1 at definition, or a forward read (`sym_fwd`), or undefined |
| `*` (PC) | `asm_pc` ≤ $FF | `asm_pc` > $FF |

On m65 a third class, FAR, above both ([§ 32-bit values](#32-bit-values-m65)).

Operators:

| Operator | Rule |
|----------|------|
| `+` `-` `*` `/` `<<` `>>` `&` `£` `^` | Wide if **either** operand is wide **or** result > $FF |
| `<` (lo byte) | Always narrow — clears `expr_wide` |
| `>` (hi byte) | Always narrow — clears `expr_wide` |
| `-` (negate) | Inherits from operand; wide if result > $FF |
| `!` (NOT) | Inherits from operand; wide if result > $FF |
| `( )` | Transparent — inherits from inner expression |

Each binary operator pushes its left operand's width onto the
hardware stack (m65: the operand stack, [§ 32-bit
values](#32-bit-values-m65)) with the left operand's value while the
right operand is parsed, and ORs it back in afterwards, so a nested `<`/`>` or a
nested operator never erases an outer operand's width:
`$0000+(<$12+1)` is ABS.

The either-operand rule means `$00 + $0000` → ABS even though the
result is $0000 and fits in a byte.  This is deliberate: the
programmer wrote a 4-digit literal, signalling absolute intent.

**Operators (C64 keyboard mapping):**
- `£` = OR (pound key), `&` = AND, `^` = XOR (↑ key)
- `!` = NOT (bitwise complement)
- `<` = lo byte, `>` = hi byte (unary prefix)

**Label resolution:** sets `sym_name` to point into the expression
text, NUL-terminates it at the end of the identifier, calls
`sym_lookup`, and restores the original byte.

## Undefined symbols

An undefined symbol does not stop the parse.  It reads as 0 (wide)
and sets `expr_fwd`; the parse goes on to the end of the expression,
so `expr_ptr` stops where it would for a defined symbol.  A later
hard error (2, 3, 4, 6) is still returned as such; otherwise the
return code is 5 (undefined).  Callers that tolerate a forward
reference — the assembler's pass 0 ([addr_mode.md § Forward-reference handling](addr_mode.md#forward-reference-handling),
`.db`/`.dw`) — thereby see the expression's full extent and size the
statement exactly as pass 1 will.

## Partial-mode contract

`expr_eval` is a **partial-mode parser.**  On success it consumes as
much of the input as forms a valid expression and leaves `expr_ptr`
at the first unparsed byte.  Partial mode is deliberate, not a
footgun: every assembler-operand caller (`addr_mode`, `asm_src`, the
REPL's `try_expr`) relies on this behaviour to parse prefixes like
`$10,X`, `AAAA:`, or `label+3,Y`, where the "trailing" bytes are
meaningful continuation syntax the caller consumes next.

**Consequence for single-expression callers.**  Callers that expect
*exactly one complete expression and nothing else* (the REPL's `?`,
`@`, `B`, `C` commands) **must enforce their own end-of-input check**
after `expr_eval` returns success — skip trailing whitespace, then
verify the next byte is `$00` (end of line_buf) or `';'` (comment
start).  Anything else is trailing garbage and must be reported as
a syntax error at the caller's contract tier.  See
[repl.md § `?` command](repl.md) for the reference implementation.

**Stopping positions** (pinned by
`tests/unit/test_expr.py::TestStopContract`):

| Input | val | `expr_ptr` stops at |
|-------|-----|---------------------|
| `"1x"` | 1 | `'x'` (offset 1) |
| `"$10gg"` | $10 | `'g'` (offset 3) |
| `"1 + 1"` | 2 | NUL (offset 5, fully consumed) |
| `"1 x"` | 1 | `'x'` (offset 2 — space consumed by `parse_mul::skip_sp`) |
| `"1,2"` | 1 | `','` (offset 1 — `,` is not a recognised operator) |
| `"42;cmt"` | 42 | `';'` (offset 2) |
| `"1 // c"` | 1 | the first `'/'` (offset 2 — `//` starts a comment, it is not a divide) |

**Greediness.**  The parser is greedy within each grammar production:
`parse_expr`, `parse_add`, and `parse_mul` each call `skip_sp`
between their inner sub-parse and their operator peek, so inter-token
whitespace is always consumed if followed by a valid operator.  The
parser never "un-skips" whitespace it already consumed — if the
operator peek fails, `expr_ptr` stays where `skip_sp` last parked it.

## Caveats

- `skip_sp` skips $20 (space) and $A0 (tab) between tokens.
- `expr_ptr` is advanced past the parsed prefix on return (see
  § Partial-mode contract above for the formal statement).
- `expr_wide` is reset to 0 at the start of each `expr_eval` call.
  No contamination from previous calls.
- Label characters: a label starts with a letter or `.` and continues
  with letters, digits and `.`.  Letters are PETSCII $41–$5A (the
  unshifted letter keys); a shifted letter ($C1–$DA) is folded to
  $41–$5A **in the input text** and then matches.  No underscore.  The
  label grammar the assembler enforces at definition is
  [assembler_syntax.md § Labels](../assembler_syntax.md#labels).
- Hex digits: `0`–`9` and the letters `a`–`f` as typed unshifted
  (PETSCII $41–$46, or ASCII $61–$66); shifted letters are not hex
  digits.
- The `*` symbol is context-dependent: alone or after an operator it
  means PC; between two values it means multiply.
- **Unary minus** (`-expr`) is supported as a prefix operator.
  `-1` evaluates to `$FFFF` (two's complement); on m65 to
  `$FFFFFFFF`, whose low word `$FFFF` a 16-bit consumer takes.
- **Nesting depth:** at most 10 nested levels — each `(` and each
  unary prefix `-` `!` `<` `>` is one level (`<(` is two).  The 11th
  level returns 3 (overflow) without recursing further, which bounds
  the recursive descent's hardware-stack use.  An error inside any
  level, including under a unary prefix, propagates unchanged to the
  caller.
- **Shifts:** the count is the full 16-bit right operand; a count of
  16 or more shifts every bit out (`1<<256` = 0, `$8000>>16` = 0).
  On m65 the count is 32 bits and 32 or more shifts every bit out.
- **16-bit wraparound:** Arithmetic on computed results silently
  wraps: `$FFFF + 1 = $0000`, `$100 * $100 = $0000`.  Overflow
  (3) comes only from literal parsing (5+ hex digits, decimal
  >65535, 17+ binary digits) and from the nesting limit.  On m65 the
  arithmetic wraps at 32 bits, the literals overflow past 8 hex
  digits, $FFFFFFFF and 32 binary digits, and a value outside
  −$FFFF…$FFFF is `range` (7) for a 16-bit consumer.
