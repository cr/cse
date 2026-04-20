# addr_mode — Addressing Mode and Operand Parser

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/addr_mode.s`](../../src/addr_mode.s) | implementation (operand values via expr_eval) |
| [`tests/unit/test_addr_mode.py`](../../tests/unit/test_addr_mode.py) | test contract |

## Interface

### mode_parse
**In:** `asm_ptr` (ZP, pointer to operand string in PETSCII), Y=0
**Out:** A = mode index (0–15), X = operand byte count (0–2),
`asm_opr[0..1]` = operand bytes (little-endian).
**Partial-result state** (per testing.md § Principle 13): the
combined position `asm_ptr + Y` on return points at the first byte
beyond the recognised operand — NUL (end of input), `';'` (comment
start), or post-whitespace NUL for the IMP-empty case.  asm_line
depends on this to recognise end-of-instruction without a separate
EOI scan; see `tests/unit/test_addr_mode.py::TestModeParseStopContract`
for the position-pinning witness.
**Clobbers:** A, X, Y

### asm_skip_ws
**In:** `asm_ptr`, Y = current offset
**Out:** Y advanced past spaces ($20) and tabs ($A0).
**Partial-result state** (Principle 13): `asm_skip_ws` is itself a
partial-result function (Y is the ancillary state), but its
contract is transitively pinned by every `test_parse_ok` case in
`tests/unit/test_addr_mode.py` whose operand contains leading,
trailing, or embedded whitespace — the resulting `asm_ptr + Y`
witness proves the skip's Y-advance is correct in situ.  A direct
test would re-exercise the same bytes through a thinner harness.
**Clobbers:** A

### Memory

**ZP (4 bytes):** `asm_ptr` (2), `asm_opr` (2).
Also uses `expr_ptr`, `expr_val`, `expr_wide` (defined in zp.s).

**Depends on:** expr (expr_eval_nb), asm_err (asm_syntax_error,
asm_expr_error, asm_pass), zp

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

### Forward-reference handling

During pass 0, `_au_read_val` consults `asm_pass` (in `asm_err.s`).
When `asm_pass == 0` and the expression uses an undefined symbol,
the routine substitutes `asm_pc + 2` rather than signalling
`asm_expr_error`.  This lets the sizing pass proceed past forward
references; the second pass sees the now-defined symbols and emits
the correct bytes.

## Caveats

- Input is PETSCII.  Register letters are A=$41, X=$58, Y=$59.
- Operand values delegated to `expr_eval_nb` (expr.s), which handles
  `$hex`, `%binary`, decimal, labels, `*`, and operators.
- Whitespace: space ($20) and tab ($A0).
- End-of-expression: NUL, CR ($0D), LF ($0A), `;`, `//`.
- On syntax error: `jmp asm_syntax_error` (in asm_err.s).
- On expression error: `jmp asm_expr_error` (in asm_err.s) — sets
  `asm_expr_err=1` so callers can print the expr-specific message.
- `expr_eval_nb` runs without KERNAL banking — mode_parse is called
  from within `_asm_line_core` where KERNAL is already banked out.
