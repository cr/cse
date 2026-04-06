# asm_src.s — Two-Pass Source Assembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_src.s`](../../src/asm_src.s) | implementation |
| [`dev/asm_src_test_stub.s`](../../dev/asm_src_test_stub.s) | test harness |
| [`tests/test_asm_src.py`](../../tests/test_asm_src.py) | test contract |

## Interface

### _asm_assemble
**In:** none (reads source via ed_read_line)
**Out:** A/X = error count (uint16).  `_asm_org`, `_asm_size`, `_asm_errors` updated.
**Clobbers:** all

**Exported state (DATA):**
- `_asm_org` (2B) — origin address after assembly
- `_asm_size` (2B) — total bytes emitted
- `_asm_errors` (2B) — error count (pass 1 only)

### _define_ws_syms
**In:** none (reads `cse_end` and `buf_base`)
**Out:** defines `workstart` and `workend` in the symbol table.
**Clobbers:** A, X, Y, sym_name, sym_val, sym_wide

Pre-defines two workspace labels:
- `workstart` = `(cse_end + $FF) & $FF00` — first free page
- `workend` = `buf_base - 1` — inclusive upper bound

Called by main.s at startup and by `asm_assemble` after `sym_clear`.

**Depends on:** asm_line (via asm_bridge), expr, symtab, editor
(ed_read_line, ed_read_rewind, buf_base), cse_io (error output),
meminfo (workstart)

## Design

Two passes over the editor source:

**Pass 0:** Collect labels and constants, compute instruction sizes.
- Labels: `name:` → sym_define(name, al_pc).  Colon required.
- Local labels: `.name:` → stored as `scope.name` in symbol table.
- Constants: `.const name expr` → sym_define(name, expr_val).
- Instructions: rebuilt as PETSCII in `_insn_buf`, passed to
  `_asm_line` to determine size.  al_pc advanced by returned length.
- Forward references: dummy target `al_pc+2` used so branches
  assemble in-range (offset=0) and return correct size.
- Errors not counted in pass 0.

**Pass 1:** Resolve references, emit bytes, count errors.
- Same scan as pass 0 but `asm_line` writes bytes to memory.
- Undefined symbols → error.  `emit_error` increments `_asm_errors`.
- Directives emit data directly (not via `asm_line`).

**KERNAL banking:** `asm_assemble` holds the KERNAL banked out
across both passes via the `kernal_out` flag (set to 1 before pass 0,
back to 0 after pass 1).  Inside the batch, `asm_line`'s own
`kernal_bank_out`/`kernal_bank_in` calls short-circuit, so each
line costs only the flag check — not a full sei + `$01` write.
This makes `asm_line` the single shared bank-aware entry point for
both `asm_src` and the REPL `.` command (see
[asm_line.md](asm_line.md)).

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

**BSS:** `_asm_pass` (1B), `_line_num` (2B), `_line_buf` (80B),
`_scope_name` (24B), `_full_label` (48B), `_insn_buf` (32B),
`_expr_buf` (48B), `_as_conv` (1B, screen code conversion flag),
`_as_flags` (1B, operand prefix bits: bit 0=#, bit 1=paren),
`_eb_idx` (1B, write index into _expr_buf),
`_ib_idx` (1B, write index into _insn_buf)

## Caveats

- `_insn_buf` is rebuilt as PETSCII each pass.  `_asm_line` converts
  PETSCII→VICII in-place, but the buffer is rewritten from source
  each time so the in-place conversion is harmless.
- `fold_block` folds PETSCII shifted uppercase ($C1–$DA) to plain
  uppercase ($41–$5A).  Plain uppercase passes through unchanged.
- The `.const` handler NUL-terminates the name in the source buffer,
  then advances `expr_ptr` by name_len+1 to skip past the NUL before
  evaluating the value expression.
- Forward-reference dummy uses `al_pc+2` (not $0000) so branch
  instructions get correct 2-byte size in pass 0.
- Error messages are only printed in pass 1 (`emit_error` checks
  `_asm_pass`).  Format: `;?N: message` where N is the source
  line number.  Uses `;?` prefix consistent with the REPL error
  convention (non-executable line).
