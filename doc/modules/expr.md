# expr.s — Expression Parser

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/expr.s`](../../src/expr.s) | implementation |
| [`src/expr.h`](../../src/expr.h) | header |
| [`tests/test_expr.py`](../../tests/test_expr.py) | test contract |

## Interface

### _expr_eval
**In:** `expr_ptr` (ZP, pointer to PETSCII expression string),
`al_pc` (ZP, current PC for `*` operator)
**Out:** `expr_val` (ZP, 16-bit result), `expr_wide` (ZP, 0=ZP 1=ABS).
Returns A = return code.
**Clobbers:** A, X, Y, `_ex_tmp`, `_ex_digits`, `_ex_wide_tmp`

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

**Depends on:** symtab (_sym_lookup for label resolution)

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
| `*` (PC) | `al_pc` ≤ $FF | `al_pc` > $FF |

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
`_sym_lookup`, restores the original char.

## Caveats

- `skip_sp` skips $20 (space) and $A0 (tab) between tokens.
- `expr_ptr` is advanced past the parsed expression on return.
  The caller can check what follows (e.g., `,` for comma-separated lists).
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
