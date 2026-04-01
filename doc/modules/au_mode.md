# au_mode.s — Addressing Mode Parser

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/au_mode.s`](../../src/au_mode.s) | implementation (includes inline hex parsing) |
| [`tests/test_au_mode.py`](../../tests/test_au_mode.py) | test contract |

## Interface

### au_parse_mode
**In:** `au_ptr` (ZP, pointer to operand string in VICII screen codes), Y=0
**Out:** A = mode index (0–15), X = operand byte count (0–2),
`au_opr[0..1]` = operand bytes (little-endian)
**Clobbers:** A, X, Y

### au_skip_ws
**In:** `au_ptr`, Y = current offset
**Out:** Y advanced past spaces ($20), tabs ($A0), and legacy ASCII tabs ($09)
**Clobbers:** A

**Depends on:** asm_bridge (au_syntax_error)

## Design

Parses VICII screen code strings.  Recognizes all 6502 addressing
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

## Caveats

- VICII screen codes, not PETSCII or ASCII.  A=$01, X=$18, Y=$19.
- Whitespace: space ($20), shifted-space/tab ($A0), and VICII 'I'
  ($09) tolerated between tokens.  **Warning:** VICII 'I'=$09 =
  ASCII TAB.  `au_skip_ws` must not be called before mnemonic
  characters are consumed.
- End-of-expression: NUL, CR ($0D), LF ($0A), `;`, `//`.
- On syntax error: `jmp au_syntax_error` (in asm_bridge.s).
