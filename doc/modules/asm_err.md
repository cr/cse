# asm_err — Assembler error state + longjmp unwind

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_err.s`](../../src/asm_err.s) | implementation |

## Interface

### asm_syntax_error
**In:**  none
**Out:** does not return — unwinds SP via `_asm_saved_sp`, banks KERNAL
back in, returns 0 to asm_line's caller
**Clobbers:** A, X, SP

Called by `addr_mode.s` / `opcode_lookup.s` / `asm_line.s` on any
non-expression syntax error.  Clears `asm_expr_err`.

### asm_error
**In:**  none
**Out:** same as `asm_syntax_error` (they share the same body)
**Clobbers:** A, X, SP

Generic error exit.  Used by `opcode_lookup.s` for invalid mode /
bad mnemonic combinations.

### asm_expr_error
**In:**  none
**Out:** same unwind as `asm_syntax_error`, but sets `asm_expr_err=1`
first so the caller (`cmd_dot`, `asm_src`'s error line emitter) can
print the expression-specific message via `expr_error_str`
**Clobbers:** A, X, SP

### Memory

**ZP (1 byte):** `_asm_saved_sp` — SP snapshot taken at asm_line entry,
used by the error exits to unwind nested `jsr` frames in one step.

**BSS (2 bytes):**

| Name | Size | Purpose |
|---|---|---|
| `asm_expr_err` | 1 | Nonzero if the last assembler error was an expression-eval failure; consulted by callers to select the error message |
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

All three error exits (`asm_error`, `asm_syntax_error`, `asm_expr_error`)
share the same body; the only difference is whether `asm_expr_err` is
set to 0 or 1 on the way in.

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
it only sets `asm_expr_err` so callers know to invoke `expr_error_str`
themselves.  Split ownership: the *flag* lives here; the *message
table* lives in expr.s where the message producers live.

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
