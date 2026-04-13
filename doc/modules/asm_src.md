# asm_src.s — Two-Pass Source Assembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_src.s`](../../src/asm_src.s) | implementation |
| [`dev/asm_src_test_stub.s`](../../dev/asm_src_test_stub.s) | test harness |
| [`tests/test_asm_src.py`](../../tests/test_asm_src.py) | test contract |

## Interface

### asm_assemble
**In:** A/X = default origin (used when source has no `.org`)
**Out:** A/X = error count (uint16).  Exported state updated.
**Clobbers:** all

**Exported state (BSS):**
- `asm_org` (2B) — origin address of first segment
- `asm_size` (2B) — total bytes emitted across all segments
- `asm_errors` (2B) — error count (pass 1 only)

**Assembly log:** Segment tracking runs silently during both passes
(no screen I/O mid-pass).  After `asm_assemble` returns, the repl
`@h_a` handler calls `seg_print_summary` to print the segment list
and save command.  Output format:

```
; asm...ok
; org  0801-0814  20b
; org  1000-1002  3b
; org  2000-2003  4b
0801:s "t-org" $2004
```

Segment lines are informational comments (`;` prefix, no `$` on
addresses).  The save command is an executable REPL line — placed
last so cursor-up+return saves the PRG.  The filename comes from
`cur_filename` (set by the last `l` or `s` command); if empty,
defaults to `"out"`.

**Exported segment API:**
- `seg_print_summary` — prints segment list + save command.
  Called by repl `@h_a` after successful assembly.
  Uses repl logging API (`out_log_open`, `io_puthex4`, `io_putdec`,
  `out_close`).
- `_min_pc` (2B) — global lowest origin
- `_max_pc` (2B) — global highest byte (exclusive, ready for save)

### _define_ws_syms
**In:** none (reads `cse_end` and `buf_base`)
**Out:** defines `workstart` and `workend` in the symbol table.
**Clobbers:** A, X, Y, sym_name, sym_val, sym_wide

Pre-defines two workspace labels:
- `workstart` = `(cse_end + $FF) & $FF00` — first free page
- `workend` = `buf_base - 1` — inclusive upper bound

Called by main.s at startup and by `asm_assemble` after `sym_clear`.

**Depends on:** asm_line, expr, symtab, editor
(ed_read_line, ed_read_rewind, buf_base), repl (out_log_open,
out_close, puts_imm for error/summary output), mem (define_ws_syms)

## Design

Two passes over the editor source:

**Pass 0:** Collect labels and constants, compute instruction sizes.
- Labels: `name:` → sym_define(name, asm_pc).  Colon required.
- Local labels: `.name:` → stored as `scope.name` in symbol table.
- Constants: `.const name expr` → sym_define(name, expr_val).
- Instructions: rebuilt as PETSCII in `_insn_buf`, passed to
  `_asm_line` to determine size.  asm_pc advanced by returned length.
- Forward references: dummy target `asm_pc+2` used so branches
  assemble in-range (offset=0) and return correct size.
- Errors not counted in pass 0.

**Pass 1:** Resolve references, emit bytes, count errors.
- Same scan as pass 0 but `asm_line` writes bytes to memory.
- Undefined symbols → error.  `emit_error` increments `_asm_errors`.
- Directives emit data directly (not via `asm_line`).

**KERNAL banking:** `asm_assemble` holds the KERNAL banked out
across both passes.  Inside the batch, `asm_line`'s own
`kernal_bank_out`/`kernal_bank_in` calls short-circuit, so each
line costs only a flag check — not a full sei + `$01` write.
This makes `asm_line` the single shared bank-aware entry point
for both `asm_src` and the REPL `.` command (see
[asm_line.md](asm_line.md)).

**Ordering matters.** Both `kernal_bank_out` and `kernal_bank_in`
honour the `kernal_out` flag and become no-ops when it is set.  The
batch must therefore do the *real* bank operation BEFORE setting the
flag (and clear the flag BEFORE the real bank-in), or the very call
that's supposed to bank will short-circuit and KERNAL stays mapped:

```
jsr kernal_bank_out      ; real bank-out (flag=0, fires)
lda #1
sta kernal_out           ; flag set: inner calls become no-ops
... do_pass 0 / do_pass 1 ...
lda #0
sta kernal_out           ; clear flag first
jsr kernal_bank_in       ; real bank-in (flag=0, fires)
```

**Error output during assembly:** `emit_error` temporarily banks
KERNAL in (direct `$01` manipulation) to print error lines via
the logging API, then banks out again.  This is necessary because
screen output calls `io_sync` → KERNAL PLOT at `$FFF0`.

The test contract pins this with a bank-witness in the asm_src
test stub: `ed_read_line` OR's the live `$01` into `_bank_witness`
on every call, so a regression that leaves KERNAL mapped during
the passes is caught immediately.

**Whitespace.**  The line parser treats both $20 (space) and $A0
(tab) as whitespace when skipping between tokens — leading
whitespace, mnemonic/operand separator, and spaces after `#` and
`(` prefixes.  Word boundaries (mnemonic scan) stop at either.

**Line parser:** Each line is split into words.  `;` or end-of-line
terminates the line.

1. If the first word ends with `:`, it is a label — dispatch to the
   label handler (see [symtab.md](symtab.md)), then advance to the
   next word.
2. If the word starts with `.`, dispatch it and the rest of the line
   to the directive handler.  Done.
3. Otherwise, dispatch the word and the rest of the line to the
   instruction assembler (see [asm_line.md](asm_line.md)).

Directives are handled directly by asm_src.s, not via asm_line.
See [assembler_syntax.md § Directives](../assembler_syntax.md#directives)
for the full list, parameters, and per-pass behaviour.

**ZP locals:** `_as_ptr` (2B, parse pointer), `_as_wsize` (1B, scratch)

**BSS:** `_asm_pass` (1B), `_line_num` (2B), `_line_buf` (40B),
`_scope_name` (24B), `_full_label` (48B), `_insn_buf` (32B),
`_expr_buf` (48B), `_as_conv` (1B, screen code conversion flag),
`_eb_idx` (1B, write index into _expr_buf),
`_ib_idx` (1B, write index into _insn_buf),
`_seg_pc` (2B, current segment start),
`_seg_start_lo/hi` + `_seg_end_lo/hi` (4×8 = 32B, segment table),
`_seg_count` (1B), `_org_set` (1B),
`_min_pc` (2B), `_max_pc` (2B)

## Caveats

- `ed_read_line` truncates at 40 raw bytes.  If truncation occurs
  (returned length == 39), the assembler emits a line warning.
  This is not a fatal error — assembly continues with the
  truncated line.  In practice only trailing comments are lost.
- `_insn_buf` is rebuilt as PETSCII each pass.  `asm_line` operates
  on PETSCII directly — no encoding conversion.
- `fold_block` folds PETSCII shifted uppercase ($C1–$DA) to plain
  uppercase ($41–$5A).  Plain uppercase passes through unchanged.
- The `.const` handler NUL-terminates the name in the source buffer,
  then advances `expr_ptr` by name_len+1 to skip past the NUL before
  evaluating the value expression.
- Forward-reference dummy uses `asm_pc+2` (not $0000) so branch
  instructions get correct 2-byte size in pass 0.
- Error messages are only printed in pass 1 (`emit_error` checks
  `_asm_pass`).  Format: `;?N: message` where N is the source
  line number.  Uses `;?` prefix consistent with the REPL error
  convention (non-executable line).
