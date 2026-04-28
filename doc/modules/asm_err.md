# asm_err — Assembler error state + longjmp unwind

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_err.s`](../../src/asm_err.s) | implementation |
| [`tests/unit/test_asm_err.py`](../../tests/unit/test_asm_err.py) | test contract |

## Interface

### asm_syntax_error
**In:**  none
**Out:** does not return — unwinds SP via `_asm_saved_sp`, banks KERNAL
back in, returns 0 to asm_line's caller; writes `asm_err_code = 0`
**Clobbers:** A, X, SP

Called by `addr_mode.s` / `opcode_lookup.s` / `asm_line.s` on any
non-expression syntax error.

### asm_error
**In:**  none
**Out:** same as `asm_syntax_error` (they share the same body and
write the same code)
**Clobbers:** A, X, SP

Generic error exit.  Used by `opcode_lookup.s` for invalid mode /
bad mnemonic combinations.

### asm_expr_error
**In:**  none
**Out:** same unwind as `asm_syntax_error`, writes `asm_err_code = 1`
**Clobbers:** A, X, SP

Used by `addr_mode.s::_au_read_val` when `expr_eval` returns an error
on pass 1 (undefined symbol, overflow, paren mismatch, divide by zero).

### asm_cpu_error
**In:**  none
**Out:** same unwind as `asm_syntax_error`, writes `asm_err_code = 2`
**Clobbers:** A, X, SP

Used by `asm_line.s`'s CPU-mode gate when a mnemonic is rejected for
the current `asm_cpu` (PHY on 6502, illegal NMOS opcode on 65C02, …).
The distinct code lets the dispatcher emit `;?cpu` instead of the
strictly-correct-but-misleading `;?syntax`.

## Error categories

The four entry points encode three categories into a single byte
(`asm_err_code`).  Callers (`asm_src.s::process_line` and
`repl.s::dot_assemble`) read the code after `asm_line` returns 0 and
pick the user-visible error tag.

| Code | Entry point | Meaning | Tag emitted by caller |
|---|---|---|---|
| 0 | `asm_error` / `asm_syntax_error` | generic syntax / invalid mode / unknown mnemonic | `;?syntax` (REPL) or `;?<line>: bad insn` (asm_src) |
| 1 | `asm_expr_error` | expression-eval error (undef / overflow / paren / divzero) | `;?expr <detail>` (REPL) or `;?<line>: <detail>` (asm_src), via [`expr_error_str`](expr.md#expr_error_str) |
| 2 | `asm_cpu_error` | CPU-gate rejection (`asm_line.s` § asm_cpu × category gate) | `;?cpu` (REPL) or `;?<line>: cpu` (asm_src) |

The actual emitted strings live in [`strings.s`](../../src/strings.s):
`str_syntax`, `str_cpu_err`, `s_bad_insn`.  The expr family lives in the
`err_str_lo`/`err_str_hi` table indexed by [`expr.s`](expr.md)'s rc value
(see [`expr.md`](expr.md) for the per-rc strings).

The four entry points share a single 12-byte unwind body; the
distinguishing `lda #N / sta asm_err_code` is implemented as a
BIT-abs skip cascade so the three loaders chain into the shared
store + unwind tail.

### Memory

**ZP (1 byte):** `_asm_saved_sp` — SP snapshot taken at asm_line entry,
used by the error exits to unwind nested `jsr` frames in one step.

**BSS (2 bytes):**

| Name | Size | Purpose |
|---|---|---|
| `asm_err_code` | 1 | Error category (0/1/2 per the table above), set by every error exit; read by callers (asm_src.s, repl.s) for tag dispatch |
| `asm_pass` | 1 | 0 = pass 0 (sizing), 1 = pass 1 (emit).  Read by `addr_mode.s` (forward-reference handling in `_au_read_val`) and written by `asm_src.s` at the start of each pass |

**Depends on:** mem (kernal_bank_in), zp

## Design

### Longjmp-style unwind

The assembler pipeline is a deep call chain:
`asm_line → _asm_line_core → mode_parse → _au_read_val → expr_eval`.
An error anywhere in that chain must abort cleanly and return to
`asm_line`'s caller without the caller having to check an error flag
at every level.

The primitive is a hand-rolled longjmp:

```
asm_line:                         asm_syntax_error:
  tsx                               …
  stx _asm_saved_sp                 ldx _asm_saved_sp
  jsr kernal_bank_out               txs            ; unwind
  …                                 jsr kernal_bank_in
                                    lda #0 / tax   ; return 0
                                    rts            ; to asm_line's caller
```

All four error exits (`asm_error`, `asm_syntax_error`, `asm_expr_error`,
`asm_cpu_error`) share the same body; the only difference is the value
written to `asm_err_code` on the way in.  The cascade uses BIT-abs
($2C) skips so the three loaders share the store and tail:

```
asm_cpu_error:
        lda #2
        .byte $2C               ; BIT abs — skip the next lda #1
asm_expr_error:
        lda #1
        .byte $2C               ; BIT abs — skip the next lda #0
asm_error:
asm_syntax_error:
        lda #0
        sta asm_err_code
        ; … shared unwind tail …
```

### asm_pass ownership

`asm_pass` belongs in `asm_err.s` because it is consulted *inside* the
error-prone operand parser (`addr_mode.s::_au_read_val` substitutes
`asm_pc+2` for undefined symbols during pass 0 to allow forward
references without a hard error).  Hosting it here keeps the
error-state invariant in one file instead of scattering the pass flag
in `asm_src.s` where only its writer lives.

### expr_error_str interaction

`expr.s` owns `expr_error_str` (the getter that returns the current
expression-error message pointer).  `asm_err.s` does not call it —
it only sets `asm_err_code = 1` so callers know to invoke
`expr_error_str` themselves.  Split ownership: the *category* lives
here; the *message table* lives in expr.s where the message producers
live.

## Caveats

- The error exits do NOT return to their immediate caller.  They
  restore SP to `_asm_saved_sp` (set at `asm_line` entry) and then
  `rts` — which pops the return address asm_line pushed, landing
  control at asm_line's caller.
- `_asm_saved_sp` is written exactly once per top-level `asm_line`
  invocation.  Nested re-entry would corrupt it; asm_line is not
  re-entrant.
- `kernal_bank_in` is called unconditionally on error.  Inside an
  `asm_assemble` batch (`kernal_out=1`) this is a no-op, which is
  the correct behaviour — the batch caller will re-bank at its own
  exit.
- `asm_pass` reset at the start of each pass is asm_src.s's
  responsibility.  asm_err.s only declares and exports it.
- `asm_cpu_error` is the *only* error exit not used directly by the
  syntactic parsing chain; it is reached only from
  `asm_line.s`'s CPU-mode gate, after a successful classify but before
  any mode parsing.  Strict-syntax errors (unknown mnemonic, bad
  mode, REL out of range) all stay on `asm_error` because the user's
  immediate problem is the source text, not the CPU profile.
