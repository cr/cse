# au_mode.s — Addressing Mode Parser

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/au_mode.s`](../../src/au_mode.s) | implementation (operand values via expr_eval) |
| [`tests/test_au_mode.py`](../../tests/test_au_mode.py) | test contract |

## Interface

### mode_parse
**In:** `asm_ptr` (ZP, pointer to operand string in PETSCII), Y=0
**Out:** A = mode index (0–15), X = operand byte count (0–2),
`asm_opr[0..1]` = operand bytes (little-endian)
**Clobbers:** A, X, Y

### asm_skip_ws
**In:** `asm_ptr`, Y = current offset
**Out:** Y advanced past spaces ($20) and tabs ($A0)
**Clobbers:** A

### Memory

**ZP (4 bytes):** `asm_ptr` (2), `asm_opr` (2).
Also uses `expr_ptr`, `expr_val`, `expr_wide` (defined in zp.s).

**Depends on:** asm_line (asm_syntax_error, asm_expr_error), expr (expr_eval_nb)

## Design

Parses PETSCII operand strings.  Recognizes all 6502 addressing
mode syntaxes:

| Syntax | Mode | Index |
|--------|------|-------|
| (none) | IMP | 0 |
| `A` | ACC | 1 |
| `#expr` | IMM | 2 |
| `expr` (narrow) | ZP | 3 |
| `expr,X` (narrow) | ZPX | 4 |
| `expr,Y` (narrow) | ZPY | 5 |
| `expr` (wide) | ABS | 6 |
| `expr,X` (wide) | ABX | 7 |
| `expr,Y` (wide) | ABY | 8 |
| `(expr)` (wide) | IND | 9 |
| `(expr,X)` (narrow) | INX | 10 |
| `(expr),Y` (narrow) | INY | 11 |
| `expr` (branch context) | REL | 12 |
| `(expr)` (narrow) | ZPI | 13 |
| `(expr,X)` (wide) | AIX | 14 |
| `expr,expr` | ZPREL | 15 |

Operand values parsed by `expr_eval_nb` (no-banking variant of
`expr_eval`).  Accepts `$hex`, `%binary`, decimal, labels, `*` (PC),
and arithmetic expressions.  ZP vs ABS determined by `expr_wide`:
narrow (0) → ZP modes, wide (1) → ABS modes.

Character constants for PETSCII: A=$41, X=$58, Y=$59, #=$23,
$=$24, (=$28, )=$29, ,=$2C.

## Caveats

- Input is PETSCII.  Register letters are A=$41, X=$58, Y=$59.
- Operand values delegated to `expr_eval_nb` (expr.s), which handles
  `$hex`, `%binary`, decimal, labels, `*`, and operators.
- Whitespace: space ($20) and tab ($A0).
- End-of-expression: NUL, CR ($0D), LF ($0A), `;`, `//`.
- On syntax error: `jmp asm_syntax_error` (in asm_line.s).
- On expression error: `jmp asm_expr_error` (in asm_line.s) — sets
  `asm_expr_err=1` so callers can print the expr-specific message.
- `expr_eval_nb` runs without KERNAL banking — mode_parse is called
  from within _asm_line_core where KERNAL is already banked out.
