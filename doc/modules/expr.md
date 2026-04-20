# expr.s — Expression Parser

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/expr.s`](../../src/expr.s) | implementation |
| [`tests/unit/test_expr.py`](../../tests/unit/test_expr.py) | test contract |

## Interface

### expr_eval
**In:** `expr_ptr` (ZP, pointer to PETSCII expression string),
`asm_pc` (ZP, current PC for `*` operator)
**Out:** `expr_val` (ZP, 16-bit result), `expr_wide` (ZP, 0=ZP 1=ABS).
Returns A = return code.
**Clobbers:** A, X, Y, `_ex_tmp`, `_ex_digits`, `_ex_wide_tmp`

`expr_eval` owns its own KERNAL banking — callers don't manage it.
The expression evaluator calls `sym_lookup` to resolve labels;
`sym_lookup` reads `sym_table` and `sym_heap` under KERNAL ROM.
By bracketing the whole evaluation with one bank pair here, the
inner `sym_lookup` calls short-circuit (when called inside an
`asm_assemble` batch, `kernal_out=1` is already set; in REPL
contexts, this wrapper IS the bank pair).  Either way, callers
of `expr_eval` never need to think about KERNAL banking.

Same wrapper structure as `asm_line` (`asm_line.s`) and
`dasm_insn` (`dasm.s`).  Test contract:
`tests/unit/test_expr.py::TestExprEvalBankContract` pins that every
exit path (success ZP, success ABS, error, sym_lookup hit,
undefined symbol) leaves `$01` bit 1 set and the I flag clear.

**Return codes:**

| A | Meaning |
|---|---------|
| 0 | Success, ZP-eligible (value ≤ $FF, no wide factors) |
| 1 | Success, ABS (16-bit or forced wide) |
| 2 | Error: expected value |
| 3 | Error: overflow |
| 4 | Error: mismatched parentheses |
| 5 | Error: undefined symbol |
| 6 | Error: division by zero |

### _expr_error_str
**In:** none (uses last error state)
**Out:** A/X = pointer to NUL-terminated error message

### Memory

**ZP (4 bytes):** `_ex_tmp` (2), `_ex_digits` (1), `_ex_wide_tmp` (1).

**BSS (5 bytes):** `last_err` (1), `_mul_tmp` (2), `_div_rem` (2).

**Depends on:** symtab (`sym_lookup` for label resolution),
mem (`kernal_bank_out` / `kernal_bank_in` for the wrapper),
strings (err_str_lo/hi, error string labels)

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

**Width tracking:** The ZP flag `expr_wide` determines whether the
result selects 2-byte (ZP) or 3-byte (ABS) instruction encoding.
It is reset to 0 (narrow) at the start of each `_expr_eval` call
and accumulates via OR — once wide, always wide.

Width sources (leaves):

| Factor | Narrow (ZP) | Wide (ABS) |
|--------|-------------|------------|
| `$` hex literal | 1–2 digits (`$00`–`$ff`) | 3–4 digits (`$000`–`$ffff`) |
| Decimal literal | value ≤ $FF | value > $FF |
| `%` binary literal | value ≤ $FF | value > $FF |
| Label | `sym_wide` = 0 at definition | `sym_wide` = 1 at definition |
| `*` (PC) | `asm_pc` ≤ $FF | `asm_pc` > $FF |

Width propagation (operators):

| Operator | Rule |
|----------|------|
| `+` `-` `*` `/` `<<` `>>` `&` `£` `^` | Wide if **either** operand is wide **or** result > $FF |
| `<` (lo byte) | Always narrow — clears `expr_wide` |
| `>` (hi byte) | Always narrow — clears `expr_wide` |
| `-` (negate) | Inherits from operand; wide if result > $FF |
| `!` (NOT) | Inherits from operand; wide if result > $FF |
| `( )` | Transparent — inherits from inner expression |

The sticky-OR rule means `$00 + $0000` → ABS even though the result
is $0000 and fits in a byte.  This is deliberate: the programmer
wrote a 4-digit literal, signalling absolute intent.

**Operators (C64 keyboard mapping):**
- `£` = OR (pound key), `&` = AND, `^` = XOR (↑ key)
- `!` = NOT (bitwise complement)
- `<` = lo byte, `>` = hi byte (unary prefix)

**Label resolution:** Sets `sym_name` to point into the expression
buffer, NUL-terminates at the end of the identifier, calls
`sym_lookup`, restores the original char.

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
- `expr_wide` is reset to 0 at the start of each `_expr_eval` call.
  No contamination from previous calls.
- Label charset: letters, digits, `.` (dot).  No underscore (not
  typeable on C64 keyboard).  Accepts PETSCII $41–$5A (the letter
  keys); no case folding needed since the C64 keyboard produces
  only one PETSCII range for letters.
- The `*` symbol is context-dependent: alone or after an operator it
  means PC; between two values it means multiply.
- **Unary minus** (`-expr`) is supported as a prefix operator.
  `-1` evaluates to `$FFFF` (two's complement).
- **16-bit wraparound:** Arithmetic on computed results silently
  wraps: `$FFFF + 1 = $0000`, `$100 * $100 = $0000`.  Overflow
  errors only apply to literal parsing (5+ hex digits, decimal
  >65535, 17+ binary digits).
