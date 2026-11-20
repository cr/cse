# asm_err — Assembler error state + longjmp unwind

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_err.s`](../../src/asm_err.s) | implementation |
| [`tests/unit/test_asm_err.py`](../../tests/unit/test_asm_err.py) | test contract |

## Interface

All four entry points are reached by `jmp`, never `jsr`, from inside
an `asm_line` call (after `asm_line` stored `_asm_saved_sp`).

### asm_syntax_error
**In:** `_asm_saved_sp` (ZP; m65 BSS, [zp.md § The m65 base page](zp.md#the-m65-base-page))
**Out:** does not return to the jumper — writes `asm_err_code = 0`,
restores SP from `_asm_saved_sp`, calls `kernal_bank_in`, and returns
A = 0, X = 0 to `asm_line`'s caller.
**Clobbers:** A, X, SP

Jumped to by `addr_mode.s` (`mode_parse`) on a malformed operand.

### asm_error
The same entry as `asm_syntax_error` (two labels on one instruction);
same In / Out / Clobbers.

Jumped to by `asm_line.s` on a non-letter key, a bad word end, an
unknown mnemonic, a non-empty implied operand, a wrong mode for a
fixed zone, a branch out of reach, and a mode `asm_opcode_lookup`
rejects ([asm_line.md](asm_line.md)).

### asm_expr_error
**In / Clobbers:** as `asm_syntax_error`.
**Out:** the same unwind, with `asm_err_code = 1`.

Jumped to by `addr_mode.s::_au_read_val` when `expr_eval_nb` returns an
error — except an undefined symbol on pass 0, which reads as a dummy
value ([addr_mode.md § Forward-reference handling](addr_mode.md#forward-reference-handling));
and by `asm_line.s` for an immediate operand out of byte range and for
output that would wrap past `$FFFF` (both set `last_err` = 3 first).
The detail is in expr.s's `last_err`.

### asm_cpu_error
**In / Clobbers:** as `asm_syntax_error`.
**Out:** the same unwind, with `asm_err_code = 2`.

Jumped to by `asm_line.s`'s CPU-mode gate when a mnemonic is rejected
for the current `asm_cpu` (LAX on 6502, a 65C02-only opcode at 6502 in the CMOS mode,
…).  The distinct code lets the dispatcher emit `;?cpu` instead of the
strictly-correct-but-misleading `;?syntax`.

### asm_err_code, asm_pass
Exported BSS bytes, see [§ Memory](#memory).

## Error categories

The four entry points encode three categories into a single byte
(`asm_err_code`).  Callers (`asm_src.s::process_line` and
`repl.s::cmd_dot`, after `dot_assemble`) read the code after `asm_line` returns 0 and
pick the user-visible error tag.

| Code | Entry point | Meaning | Tag emitted by caller |
|---|---|---|---|
| 0 | `asm_error` / `asm_syntax_error` | generic syntax / invalid mode / unknown mnemonic | `;?syntax` (REPL) or `;?<line>: bad insn` (asm_src) |
| 1 | `asm_expr_error` | expression-eval error (undef / overflow / paren / divzero) | `;?expr <detail>` (REPL) or `;?<line>: <detail>` (asm_src), via [`expr_error_str`](expr.md#expr_error_str) |
| 2 | `asm_cpu_error` | CPU-gate rejection (`asm_line.s` § asm_cpu × category gate) | `;?cpu` (REPL) or `;?<line>: cpu` (asm_src) |

The actual emitted strings live in [`strings.s`](../../src/strings.s):
`str_syntax`, `str_cpu_err`, `s_bad_insn`.  The expr family lives in the
`err_str_lo`/`err_str_hi` table indexed by expr.s's `last_err`
(see [expr.md § expr_eval](expr.md#expr_eval) for the per-code strings).
The source assembler's line format is owned by
[asm_src.md § Error and warning lines](asm_src.md#error-and-warning-lines).

The four entry points share a single 13-byte tail (`sta asm_err_code`
through `rts`); the distinguishing `lda #N` is implemented as a
BIT-abs skip cascade so the three loaders chain into the shared
store + unwind tail.

### Memory

**ZP (1 byte):** `_asm_saved_sp` — SP snapshot taken at asm_line entry,
used by the error exits to unwind nested `jsr` frames in one step.

**BSS (2 bytes):**

| Name | Size | Purpose |
|---|---|---|
| `asm_err_code` | 1 | Error category (0/1/2 per the table above), set by every error exit; read by callers (asm_src.s, repl.s) for tag dispatch |
| `asm_pass` | 1 | 0 = pass 0 (sizing), 1 = pass 1 (emit).  Written by `asm_src.s` at the start of each pass (and forced to 1 around `_vocal_fwd_err`); read by `addr_mode.s` (`_au_read_val` forward references, the shadow warning) and `asm_src.s` (`emit_error`, `_emit_byte`, `.db`/`.const` checks) |

**Depends on:** mem (`kernal_bank_in`), zp (`_asm_saved_sp`)

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
assembler's error state in one low-layer file, so addr_mode does not
import from asm_src (its caller's caller).

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
- `asm_cpu_error` is the *only* error exit not used by the syntactic
  parsing chain; it is reached only from `asm_line.s`'s CPU-mode gate,
  after a successful classify but before any mode parsing.
  Strict-syntax errors (unknown mnemonic, bad mode, REL out of range)
  all stay on `asm_error` because the user's immediate problem is the
  source text, not the CPU profile.
- A direct caller of `_asm_line_core` (the unit-test bundles) must
  set `_asm_saved_sp` itself, or an error unwinds to a stale SP.
