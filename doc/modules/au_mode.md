# au_mode.s — Addressing Mode Parser

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/au_mode.s`](../../src/au_mode.s) | implementation (includes inline hex parsing) |
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

**Depends on:** asm_line (asm_syntax_error)

### Memory

**ZP (5 bytes):** `asm_ptr` (2), `asm_opr` (2), `_asm_au_tmp` (1).

## Design

Parses PETSCII operand strings.  Recognizes all 6502 addressing
mode syntaxes:

| Syntax | Mode | Index |
|--------|------|-------|
| (none) | IMP | 0 |
| `A` | ACC | 1 |
| `#$XX` | IMM | 2 |
| `$XX` | ZP | 3 |
| `$XX,X` | ZPX | 4 |
| `$XX,Y` | ZPY | 5 |
| `$XXXX` | ABS | 6 |
| `$XXXX,X` | ABX | 7 |
| `$XXXX,Y` | ABY | 8 |
| `($XXXX)` | IND | 9 |
| `($XX,X)` | INX | 10 |
| `($XX),Y` | INY | 11 |
| `$XXXX` (branch context) | REL | 12 |
| `($XX)` | ZPI | 13 |
| `($XXXX,X)` | AIX | 14 |
| `$XX,$XXXX` | ZPREL | 15 |

ZP vs ABS determined by operand digit count: 1–2 hex digits → ZP,
3–4 digits → ABS.  All operands require `$` prefix.

Character constants for PETSCII: A=$41, X=$58, Y=$59, #=$23,
$=$24, (=$28, )=$29, ,=$2C.

## Caveats

- Input is PETSCII.  Register letters are A=$41, X=$58, Y=$59.
  Hex digits: 0–9=$30–$39, A–F=$41–$46 (uppercase).
- Whitespace: space ($20) and tab ($A0).
- End-of-expression: NUL, CR ($0D), LF ($0A), `;`, `//`.
- On syntax error: `jmp asm_syntax_error` (in asm_line.s).
