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
**Out:** A = mode index (0–15 on C64 builds; 0–19 on the m65 build —
[opcode_lookup.md § Mode constants](opcode_lookup.md#design)),
X = operand byte count (0–2), `asm_opr[0..1]` = operand bytes
(little-endian); on `MEGA_SUPPORT` also `_au_far` (BSS).
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

**BSS (1 byte):**

| Variable | Size | Purpose |
|----------|------|---------|
| `_au_no_acc` | 1 | Caller signal: 0 = ACC syntax allowed, nonzero = the literal `A` operand must be parsed as a label.  Written by `asm_line.s` per profile.  Read by mode_parse's SC_A branch. |
| `_au_far` | 1 | `MEGA_SUPPORT` only.  Result: 1 = the operand was written in brackets (`[e]`, `[e],z`), 0 otherwise.  Written by every mode_parse call; read by asm_line (far prefix). |

**Depends on:** expr (expr_eval_nb), asm_err (asm_syntax_error,
asm_expr_error, asm_pass), symtab (sym_lookup — for shadow detection),
log (log_warn — emits `;!a shadow` directly when an explicit `A`
operand parses as ACC against a defined symbol `A`), strings
(s_a_shadow), zp

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

On `MEGA_SUPPORT` (m65-45gs02) also:

| Syntax | Mode | Index |
|--------|------|-------|
| `(expr),Z` (narrow) | ZPIZ | 19 |
| `(expr,SP),Y` or `(expr,S),Y` (narrow) | ISPY | 18 |

and the far forms, which set `_au_far` (asm_line accepts them at
`asm_cpu=4` only):

| Syntax | Mode | `_au_far` |
|--------|------|-----------|
| `[expr]` (narrow) | ZPI (13) | 1 |
| `[expr],Z` (narrow) | ZPIZ (19) | 1 |

`IMM16` (16) and `REL16` (17) are never returned: `#expr` is always
IMM, and asm_line promotes it to IMM16 on a profile that has IMM16 and
no IMM (`PHW`); a branch target is returned as ZP/ABS and asm_line
selects REL or REL16 ([asm_line.md § Branches](asm_line.md#branches-zone-b)).
A wide value in a narrow-only form (`(expr),Z`, `(expr,SP),Y`,
`[expr]`) is a syntax error, as for `(expr,X)` today.

Operand values parsed by `expr_eval_nb` (no-banking variant of
`expr_eval`).  Accepts `$hex`, `%binary`, decimal, labels, `*` (PC),
and arithmetic expressions.  ZP vs ABS determined by `expr_wide`:
narrow (0) → ZP modes, wide (1) → ABS modes.

Character constants for PETSCII: A=$41, X=$58, Y=$59, #=$23,
$=$24, (=$28, )=$29, ,=$2C.

### ACC vs label disambiguation

The single-character operand `A` is genuinely ambiguous between the
ACC addressing mode and a one-character label named `A`.  mode_parse
resolves this from a single signal — `_au_no_acc` — written by the
caller (asm_line) before the call:

|  | `_au_no_acc = 0` (profile accepts ACC) | `_au_no_acc ≠ 0` (profile rejects ACC) |
|---|---|---|
| operand exactly `A` followed by end-of-expr | **MODE_ACC** — `A` shadows any defined symbol of the same name; mode_parse emits `;!a shadow` via `log_warn` (pass 1 only) when `sym_lookup("A")` succeeds | label parse via `_au_read_val` |
| operand `A` + ident chars (`AB`, `AX`, …) | label parse | label parse |
| empty / pure whitespace | MODE_IMP (asm_line promotes to MODE_ACC for ACC-accepting profiles — see [asm_line.md](asm_line.md)) | MODE_IMP |
| anything else (`#`, `(`, digit, `$`, `*`, …) | normal parse | normal parse |

"Exactly `A` followed by end-of-expr" means: optional leading
whitespace, `A`, then whitespace, `#`, or an end-of-expression mark —
NUL, CR, LF, `;`, `//` (the same set `_au_is_end` tests).  The test is
relative to wherever the operand starts, not to offset 0 of the
argument string.

The decision is **purely textual + caller-flag-based**.  It does not
consult symtab to *change* the parse choice — only to detect the
shadow case for the warning.  Pass 0 sees identical bytes for `A`
as ACC vs `A` as label-with-undef-symbol (both 1 byte: ACC is 1, the
ABS sizing fallback is 2; ACC always wins for ACC-accepting profiles
regardless of symbol state).  This is a deliberate choice: the
parse must be invariant across passes, and "is `A` a defined symbol
*right now*?" is not — symbols can be defined later in the source.

The shadow rule means a user who defines `A:` somewhere and then
writes `ASL A` gets accumulator mode, *not* a memory access to the
labelled location.  mode_parse emits `;!a shadow` directly on
pass 1 (via `log_warn`) so the source assembler's output makes the
shadow visible.  mode_parse runs with the KERNAL banked out (inside
`asm_assemble`'s batch, or `asm_line`'s own bank-out), and screen
output reaches KERNAL PLOT through `io_sync`, so the warning is
bracketed by saving `$01`, banking the KERNAL in, and restoring `$01`
afterwards.  Use a different label name or write the address
explicitly (`ASL <expr>`) to address symbol `A` from one of the
six ACC-accepting mnemonics (ASL/LSR/ROL/ROR; INC/DEC on CMOS).

### Forward-reference handling

During pass 0, `_au_read_val` consults `asm_pass` (in `asm_err.s`).
When `asm_pass == 0` and the expression uses an undefined symbol,
the routine substitutes `asm_pc + 2` (wide) rather than signalling
`asm_expr_error`.  expr_eval has already parsed the *whole*
expression ([expr.md § Undefined symbols](expr.md#undefined-symbols)),
so `expr_ptr` is past it and the operand's tail — `tbl+1`, `fwd+3,x`,
`(fwd+1),y` — is parsed as on pass 1.  This lets the sizing pass
proceed past forward references with the same size pass 1 will use;
the second pass sees the now-defined symbols and emits the correct
bytes.

## Caveats

- Input is PETSCII.  Register letters are A=$41, X=$58, Y=$59; on
  the m65 build also S=$53, P=$50 (in `,SP`) and Z=$5A.  `[`=$5B and
  `]`=$5D (typed SHIFT+`:` / SHIFT+`;` on the C64 keyboard).
- Operand values delegated to `expr_eval_nb` (expr.s), which handles
  `$hex`, `%binary`, decimal, labels, `*`, and operators.
- Whitespace: space ($20) and tab ($A0).
- End-of-expression: NUL, CR ($0D), LF ($0A), `;`, `//`.
- On syntax error: `jmp asm_syntax_error` (in asm_err.s) — writes
  `asm_err_code=0`.
- On expression error: `jmp asm_expr_error` (in asm_err.s) — writes
  `asm_err_code=1` so callers can print the expr-specific message
  via `expr_error_str`.  See
  [asm_err.md § Error categories](asm_err.md#error-categories).
- `expr_eval_nb` runs without KERNAL banking — mode_parse is called
  from within `_asm_line_core` where KERNAL is already banked out.
- ACC syntax (`A` operand) is recognised only when the caller has
  cleared `_au_no_acc`.  See § ACC vs label disambiguation.  Single-
  letter labels named `A` are accepted as labels only when the
  caller signals "ACC not valid here"; otherwise `A` always means
  the accumulator.  `X` and `Y` are not register tokens for
  mode_parse — they only appear as the trailing index in `,X` /
  `,Y` forms — so single-letter labels named `X` or `Y` are
  unambiguous and parsed normally.
