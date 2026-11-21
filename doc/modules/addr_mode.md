# addr_mode — Addressing Mode and Operand Parser

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/addr_mode.s`](../../src/addr_mode.s) | implementation (operand values via expr_eval) |
| [`tests/unit/test_addr_mode.py`](../../tests/unit/test_addr_mode.py) | test contract |

## Interface

### mode_parse
**In:** `asm_ptr` (ZP, pointer to the operand text, PETSCII,
NUL-terminated), Y = 0 (offset); `_au_no_acc` (BSS, set by the
caller); `asm_pass` (asm_err.s) and `asm_pc` for the forward-reference
rule; KERNAL banked out (it calls `expr_eval_nb`).
**Out:** A = mode index (0–15 on C64 builds; 0–19 on the m65 build —
[opcode_lookup.md § Mode constants](opcode_lookup.md#design)),
X = operand byte count (0–2), `asm_opr[0..1]` = operand bytes
(little-endian; for ZPREL `asm_opr` is the second value, the branch
target, both bytes, and `asm_tmp2` the first, the zero-page byte); `asm_ptr` advanced past the consumed text; on
`MEGA_SUPPORT` also `_au_far` (BSS).
**Partial-result state** (per testing.md § Principle 13): the
combined position `asm_ptr + Y` on return points at the first byte
beyond the recognised operand and its trailing whitespace — NUL (end
of input), `;`, `//`, `#` (a trailing comment), or the post-whitespace
NUL for the IMP-empty case.  mode_parse itself requires that end
(`_au_check_end`, else `asm_syntax_error`), so its callers need no
end-of-operand scan; asm_line does not read Y afterwards.  See
`tests/unit/test_addr_mode.py::TestModeParseStopContract` for the
position-pinning witness.
**Errors:** `jmp asm_syntax_error` for a malformed operand,
`jmp asm_expr_error` for an expression error (except an undefined
symbol on pass 0, § Forward-reference handling) — neither returns
([asm_err.md](asm_err.md)).
**Clobbers:** A, X, Y; `asm_opr`, `asm_tmp2` (ZPREL, in a set with the digit zones), `_au_far` (m65), `expr_ptr`, `expr_val`, `expr_wide`
and everything `expr_eval_nb` clobbers ([expr.md](expr.md)); on the
pass-1 shadow path also `sym_name` and what `sym_lookup` / `log_warn`
clobber.

### asm_skip_ws
**In:** `asm_ptr`, Y = current offset
**Out:** Y advanced past spaces ($20) and tabs ($A0); A = the first
other byte.
**Partial-result state** (Principle 13): `asm_skip_ws` is itself a
partial-result function (Y is the ancillary state); its contract is
pinned transitively by every `test_parse_ok` case in
`tests/unit/test_addr_mode.py` whose operand contains leading,
trailing, or embedded whitespace (spaces and `$A0`), and by
`TestModeParseStopContract`'s offsets (`TestAsmSkipWs` is a vocal
skip that says so).
**Clobbers:** A

### _au_no_acc
Exported BSS byte, the caller's ACC signal for the next `mode_parse`:
0 = a bare `A` operand is the accumulator, nonzero = `A` is a label
([§ ACC vs label disambiguation](#acc-vs-label-disambiguation)).
`asm_line` writes it once per instruction from the profile's mode
mask.

### Memory

**ZP:** none of its own; it uses `asm_ptr`, `asm_opr`, `expr_ptr`,
`expr_val`, `expr_wide`, `asm_pc`, `sym_name` ([zp.md](zp.md)).

**RODATA (2 bytes):** `_str_A` — `"A"`, the `sym_lookup` probe for the
shadow warning.

**BSS (1 byte; 2 on `MEGA_SUPPORT`):**

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
| `(expr)` (narrow) | ZPI | 13 |
| `(expr,X)` (wide) | AIX | 14 |
| `expr,expr` | ZPREL (the CMOS mode, m65 — `HAS_ZONE_D`; elsewhere `;?syntax`, as no set member has the form) | 15 |

REL (12) is never returned: a branch target is returned as ZP (3) or
ABS (6) and asm_line's zone B computes the offset
([asm_line.md § Branches](asm_line.md#branches-zone-b)).

On `MEGA_SUPPORT` (the m65-45gs02 build) also:

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

`IMM16` (16) and `REL16` (17) are never returned either: `#expr` is
always IMM, and asm_line promotes it to IMM16 on a profile that has
IMM16 and no IMM (`PHW`); for a branch target asm_line selects REL or
REL16.  A wide value in a narrow-only form (`(expr),Z`, `(expr,SP),Y`,
`[expr]`) is a syntax error, as a wide `(expr),Y` is on every build.

Operand values parsed by `expr_eval_nb` (no-banking variant of
`expr_eval`).  Accepts `$hex`, `%binary`, decimal, labels, `*` (PC),
and arithmetic expressions.  ZP vs ABS determined by `expr_wide`:
narrow (0) → ZP modes, wide (1) → ABS modes.

`#` has two roles.  At the start of the operand it is the IMM prefix
(whitespace may follow: `# $10` = `#$10`); a `#` followed only by
whitespace and an end mark is a comment and yields IMP.  After a
complete operand, and after a bare `A`, `#` ends the operand like `;`
(a trailing comment).

Character constants for PETSCII: A=$41, X=$58, Y=$59, #=$23,
(=$28, )=$29, ,=$2C.  Only these exact bytes are register letters:
the unshifted keys.

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
shadow case for the warning.  ACC always wins for ACC-accepting
profiles regardless of symbol state, so both passes choose the same
mode and size.  This is a deliberate choice: the parse must be
invariant across passes, and "is `A` a defined symbol *right now*?"
is not — symbols can be defined later in the source.

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
six ACC-accepting mnemonics (ASL/LSR/ROL/ROR; INC/DEC on the 4510 and in the CMOS mode).

### Forward-reference handling

During pass 0, `_au_read_val` consults `asm_pass` (in `asm_err.s`).
When `asm_pass == 0` and the expression uses an undefined symbol,
the routine substitutes `asm_pc + 2` (wide) rather than signalling
`asm_expr_error`.  expr_eval has already parsed the *whole*
expression ([expr.md § Undefined symbols](expr.md#undefined-symbols)),
so `expr_ptr` is past it and the operand's tail — `tbl+1`, `fwd+3,x`,
`(vec)` of `JMP` — is parsed as on pass 1.  This lets the sizing pass
proceed past forward references with the same size pass 1 will use.
On pass 1 the symbol is defined (pass 0 defined it), but its pass
stamp marks it as a forward read, so `expr_eval_nb` makes it wide —
the same ABS size — and the operand gets the real value
([symtab.md § Pass stamp](symtab.md#pass-stamp)).

A form whose operand is zero-page only — `(zp),y`, `(zp,x)`, the
CMOS `(zp)`, the `zp,rel` of BBR/BBS, and on m65 `(zp),z`, `[zp],z`
and `(d,sp),y` — has no wide variant, so a forward symbol there is
wide on both passes and the line fails with `;?N: bad insn`
(`asm_syntax_error`).  Such a pointer must be defined above its use
(TODO § Bugs: a forward zero-page pointer never assembles).

## Caveats

- Input is PETSCII.  Register letters are A=$41, X=$58, Y=$59; on
  the m65 build also S=$53, P=$50 (in `,SP`) and Z=$5A.  `[`=$5B and
  `]`=$5D (typed SHIFT+`:` / SHIFT+`;` on the C64 keyboard).
- Operand values delegated to `expr_eval_nb` (expr.s), which handles
  `$hex`, `%binary`, decimal, labels, `*`, and operators.
- Whitespace: space ($20) and tab ($A0).
- End-of-expression (`_au_is_end`): NUL, CR ($0D), LF ($0A), `;`,
  `//`; after an operand also `#` (`_au_check_end`).
- On syntax error: `jmp asm_syntax_error` (in asm_err.s) — writes
  `asm_err_code=0`.  On the C64 builds `asm_syntax_error` is the same
  entry as `asm_error`.
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
