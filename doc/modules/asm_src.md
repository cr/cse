# asm_src.s — Two-Pass Source Assembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_src.s`](../../src/asm_src.s) | implementation |
| [`tests/unit/test_asm_src.py`](../../tests/unit/test_asm_src.py) | test contract |

Its test bundle's stub, [`dev/asm_src_test_stub.s`](../../dev/asm_src_test_stub.s),
is owned by [build_system.md](../build_system.md).

The source language (labels, directives, expressions, output) is
specified in [assembler_syntax.md](../assembler_syntax.md); this
document is the module contract behind it.

## Interface

### asm_assemble
**In:** A/X = default origin (used for code before the first `.org`;
the REPL passes `cur_addr`); `asm_cpu` (the CPU the assembly starts
with); the editor source, read through `ed_read_rewind` /
`ed_read_line`.
**Out:** A/X = error count (uint16) — also in `asm_errors`;
`asm_org`, `asm_size` updated; the symbol table holds the
assembly's symbols with stamp 0 (`sym_stamp` = 0).  `asm_cpu` is the
caller's again (`.cpu` never leaks).  The KERNAL is banked in
(`kernal_out` = 0).
**Clobbers:** all

**Exported state (BSS):**
- `asm_org` (2B) — origin address of the first segment: the default
  origin (A/X) if any byte is emitted before the first `.org`/`.bas`,
  else the first `.org`/`.bas` address.
- `asm_size` (2B) — total bytes laid out across all segments (pass 1;
  counted whether or not `_emit_byte` wrote them).
- `asm_errors` (2B) — error count: every `emit_error` on pass 1, plus
  the vocal forward-reference errors of pass 0
  ([§ `_vocal_fwd_err`](#_vocal_fwd_err)).

### The CPU set

`cpu_names` (RODATA) lists the build's CPU set
([build_system.md § Builds and CPU sets](../build_system.md#builds-and-cpu-sets)):
per member its `asm_cpu` value, its name and a NUL, `$FF` at the
end — selected by the build's `CPU_<top>` define.  `cpu_lookup`
(**In:** `expr_ptr` → a word; **Out:** C = 0 and A = the member's
`asm_cpu` value when the word, ended by NUL, whitespace or `;`, names
a member, else C = 1; **Clobbers:** X, Y, `asm_tmp`) serves `.cpu`
and the REPL's `u`, which also lists `cpu_names`
([repl.md § `u`](repl.md#u--cpu-mode)).

### seg_print_save
Prints the executable save line `AAAA:s "NAME" $BBBB` for the
assembled range — `AAAA` = `_min_pc`, `BBBB` = `_max_pc - 1`
(inclusive end, the `s` command's convention), `NAME` =
`cur_project_name`, or `out` when it is empty — then clears to end of
line and calls `newline`.  Prints nothing when no segment was emitted
(`_min_pc` = $FFFF).
**In:** `_min_pc`, `_max_pc` (BSS, from the last assembly),
`cur_project_name`; KERNAL banked in.
**Called by:** repl.s `exec_line` (`a`) after an assembly with no
errors.
**Clobbers:** A, X, Y and what `io_puthex4` / `io_puts` / `newline`
clobber.

The address argument makes the `s` command save a PRG; see
[repl.md](repl.md) for the project-name and filename rules.

### Assembly log

Segment lines print inline during pass 1: each `.org`/`.bas` (and the
end of the pass) closes the open segment through `_seg_log_close`,
which prints `; org  AAAA-BBBB NNNNNb` via `seg_line`
([log.md](log.md); inclusive end, size right-aligned in five columns)
with the KERNAL banked in temporarily; empty segments are suppressed.  The complete user-visible transcript — the
`; asm...` header, `; ok` / `; N err`, the save line — is in
[assembler_syntax.md § Assembly Output](../assembler_syntax.md#assembly-output);
the error and warning lines are specified in
[§ Error and warning lines](#error-and-warning-lines) below.

**Depends on:** asm_line (`asm_line`), asm_err (`asm_err_code`,
`asm_pass`), expr (`expr_eval`, `expr_error_str`, `expr_fwd`), symtab
(`sym_define`, `sym_clear`, `sym_stamp`), gap_buffer
(`define_ws_syms`, `ed_read_line`, `ed_read_rewind`), log
(`log_open`, `log_close`, `seg_line`, `puts_imm`), mem
(`kernal_bank_out`, `kernal_bank_in`), cse_io (`io_puts`, `io_putc`,
`io_putdec`, `io_puthex4`, `io_clear_eol`, `io_utoa`, `dec_buf`),
screen (`newline`), strings (`str_tag_org`, `str_range`,
`str_cpu_err`, `err_overflow`, the `s_*` messages), zp (`kernal_out`,
`asm_*`, `expr_*`, `sym_*`, `_as_ptr`, `_as_wsize`, `buf_base`,
`cur_project_name`, `rp_addr`, `rp_cnt`, `rp_save2`, `rp_ptr2`).
asm_src.s also imports `dec_pow_lo` / `dec_pow_hi` (strings) without
using them.

The ACC label-shadow warning `;!a shadow` is emitted by
`addr_mode.s::mode_parse`, not by asm_src
([addr_mode.md § ACC vs label disambiguation](addr_mode.md#acc-vs-label-disambiguation)).

## Internal helpers

The directive handlers and `process_line` share these helpers; a new
directive uses them rather than writing memory or printing itself.

### _emit_byte
The single gate for every output byte — instruction bytes and data.
**In:** A = byte; `asm_pc`, `asm_pass`, `_pc_wrap`, `buf_base`.
**Out:** on pass 1, when `$0800` ≤ `asm_pc` < `buf_base` (the
workspace `workstart`..`workend`, the range `bp_range_check` accepts)
and `asm_pc` has not wrapped past `$FFFF` (`_pc_wrap` = 0), the byte is
stored at `(asm_pc)`.  Otherwise, on pass 1, it is dropped and `_oor`
is set — `do_pass` reports `;?N: range` once for the line.  On pass 0
nothing is written and nothing is checked.  Always: `asm_pc` += 1,
`asm_size` += 1 (`inc_pc_size`); an `asm_pc` wrap from `$FFFF` to
`$0000` sets `_pc_wrap` (cleared by `.org`/`.bas` and at each pass
start).
**Clobbers:** Y, flags.  Preserves A and X (callers loop on X).

`_emit_word` emits A (lo) then X (hi) through it.

### emit_error
**In:** A/X = pointer to a NUL-terminated message; `asm_pass`,
`_line_num`.  Called with the KERNAL banked out (inside the passes).
**Out:** on pass 0 nothing (silent, not counted).  On pass 1:
`asm_errors` += 1 and the line `;?N: msg` is printed
([§ Error and warning lines](#error-and-warning-lines)); for the print
it sets `$01` bit 1 directly (`_bank_in_tmp` — `kernal_bank_in` is a
no-op while `kernal_out` = 1) and clears it again afterwards
(`_bank_out_tmp`).  Returns normally, so it may be reached by `jsr`
or as a tail `jmp`.
**Clobbers:** A, X, Y and what `log_open`, `io_putdec`, `io_puts`,
`log_close` clobber.

### _bad_val_err
`lda #<s_bad_val / ldx #>s_bad_val / jmp emit_error`: the shared
`bad val` error.  Reached by `jmp` (a tail call — `emit_error`'s `rts`
returns to the handler's caller) or by `jsr` (returns to the handler).
`_exp_name_err` (`exp id`) and `_too_long_err` (`too long`) are the
same shape.

### _vocal_fwd_err
`emit_error(s_fwd_ref)` with `asm_pass` forced to 1 for the call and
restored afterwards, so `;?N: fwd ref` is printed and counted even on
pass 0.  Used by `.res` (count and fill) and `.align`, whose pass-0
size depends on the value; the caller then abandons the directive
(nothing laid out).
**Clobbers:** as `emit_error`.

## Design

Two passes over the editor source, `do_pass` each.  Every pass starts
at the default origin (`_def_org`), with the caller's CPU
(`_cpu_save`), line number 0, `_pc_wrap` = 0, and the default segment
open; then `process_line` runs for each line `ed_read_line` returns.

**Pass 0:** collect labels and constants, compute sizes.
- Labels: `name:` → `sym_define(name, asm_pc)`; `.name:` → stored as
  `scope.name`.  Constants: `.const name expr`.
- Instructions: rebuilt as PETSCII in `_insn_buf`, assembled by
  `asm_line` into the scratch `_insn_out`; the bytes go through
  `_emit_byte`, which on pass 0 only advances `asm_pc`.
- Forward references in instruction operands: `_au_read_val`
  substitutes `asm_pc+2` (wide) so the instruction gets its pass-1
  size ([addr_mode.md § Forward-reference handling](addr_mode.md#forward-reference-handling)).
  In `.db` / `.dw`, pass 0 ignores the return code: every `.db`
  argument is one byte and every `.dw` argument two, whatever the
  value.
- `.res` / `.align` with a forward reference in the count, fill or
  boundary: `;?N: fwd ref` on pass 0 (`_vocal_fwd_err`, counted) and
  nothing laid out.  On pass 1 the symbol is defined and the
  directive uses its value, so the layout after it differs between
  the passes — the assembly has already failed (error count ≥ 1).
- All other errors are silent on pass 0 (`emit_error` returns).

**Pass 1:** resolve references, emit bytes, count errors.
- Same scan; `_emit_byte` now writes (inside the workspace).
- An undefined symbol is an error; `emit_error` prints and counts.
- The ACC label-shadow warning comes from `mode_parse` on pass 1
  only.

**Emission.**  `asm_line` assembles every instruction into the
scratch buffer `_insn_out` (overlaying `_full_label`), never into the
target; `process_line` emits its bytes one by one through
`_emit_byte`, like the directives.  So every output byte passes one
gate ([§ `_emit_byte`](#_emit_byte)), and pass 0 writes nothing at
all.

**Pass stamp:** each pass first sets `sym_stamp` (`SYM_P0` for pass
0, 0 for pass 1), then defines the built-in symbols (`workstart`,
`workend`, `define_ws_syms`); labels and `.const` are defined on
*both* passes, so every symbol defined before a read in the same pass
carries that pass's stamp.  `sym_stamp` stays 0 after the assembly.
A pass-1 read of a symbol still stamped `SYM_P0` is a forward
reference: expr sizes it ABS, as pass 0 did when it was undefined —
so `lda zp` before `.const zp $10` is `AD 10 00` on both passes and
every later label keeps its pass-0 address
([symtab.md § Pass stamp](symtab.md#pass-stamp)).  A `.const` whose
expression reads a later-defined symbol cannot be defined on pass 0;
on pass 1 it is `;?N: fwd ref` and stays undefined.  Because symbols
are defined on pass 1 too, a full table is reported where errors are
vocal (`;?N: sym full`).

**`.cpu` scope:** `asm_assemble` saves the caller's `asm_cpu`
(`_cpu_save`); every pass starts with it, and it is restored when the
assembly ends, so a `.cpu` line changes the CPU only for the lines
after it, identically on both passes, and never leaks into the REPL.

**KERNAL banking:** `asm_assemble` holds the KERNAL banked out
across both passes.  Inside the batch, `asm_line`'s and symtab's
`kernal_bank_out`/`kernal_bank_in` calls are no-ops, so each line
costs only a flag check — not a full `$01` write.  This makes
`asm_line` the single shared bank-aware entry point for both
`asm_src` and the REPL `.` command (see [asm_line.md](asm_line.md)).

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

**Screen output during assembly:** `emit_error`, the truncation
warning and `_seg_log_close` bank the KERNAL in through `$01`
directly (`_bank_in_tmp` / `_bank_out_tmp`) around their output,
because screen output calls `io_sync` → KERNAL PLOT at `$FFF0`.  No
SEI is needed (the RAM IRQ vector handles an IRQ while banked out —
[memory_design.md](../memory_design.md)).

The test contract pins the batch with a bank-witness in the asm_src
test stub: `ed_read_line` ORs the live `$01` into `_bank_witness`
on every call, so a regression that leaves KERNAL mapped during
the passes is caught immediately.

**Whitespace.**  The line parser treats both $20 (space) and $A0
(tab) as whitespace when skipping between tokens — leading
whitespace, mnemonic/operand separator, and spaces after `#` and
`(` prefixes.  Word boundaries (mnemonic scan) stop at either.

**Line parser (`process_line`):** each line is split into words.
`;` or end-of-line terminates the line.

1. **Label loop.**  A word whose last character is `:` is a label:
   the name is folded (`fold_block`), NUL-terminated in place,
   checked against the label grammar (`_name_ok`) and defined
   (`define_label`); then the next word is examined, so several
   labels may precede the statement.  A `:` with no name is `exp id`
   and ends the line.
2. **Directive.**  A word starting with `.` (and not ending in `:`)
   goes to `process_directive` — see below.
3. **Instruction.**  Otherwise the mnemonic word (at most 8
   characters) and, after one space, the operand are copied into
   `_insn_buf`, each local reference `.name` in the operand expanded
   to `scope.name` (a dot inside a name — `main.loop` — is left
   alone).  `asm_line` assembles the text; on a zero return the
   `asm_err_code` category selects the message: 0 → `bad insn`,
   1 → the `expr_error_str` text, 2 → `cpu`.

**Directive recognition.**  `process_directive` is entered with
`_as_ptr` on the first character after the dot.  It compares the word
byte for byte against the names in `_dir_names` (`align`, `bas`,
`cpu`, `const`, `db`, `dw`, `org`, `res`, `str`, `scr`, NUL-separated,
`$FF`-terminated).  A name matches only when the word also ends there
— at whitespace ($20/$A0), `;` or NUL — so `.co`, `.oops`, `.dbx` match
nothing.  The comparison does not fold case: a directive is written
with the unshifted letter keys.  On a match `expr_ptr` is set past the
name (`set_expr_off`) and the handler at the same index of
`_dir_lo`/`_dir_hi` is entered by the RTS trick; every handler returns
C=0.  An unknown word returns C=1 and `process_line` reports
`bad insn`.  Adding a directive means adding its name to `_dir_names`
and its handler to `_dir_lo` and `_dir_hi` at the same position.
Each directive's syntax and per-pass behaviour is
[assembler_syntax.md § Directives](../assembler_syntax.md#directives).

**ZP locals:** `_as_ptr` (2B, parse pointer; `.res` reuses it as the
count), `_as_wsize` (1B, `.db`/`.dw` word size; scratch elsewhere).

**BSS:**

| Variable | Size | Purpose |
|---|---|---|
| `asm_org` | 2 | exported, above |
| `_def_org` | 2 | default origin; every pass starts here |
| `_cpu_save` | 1 | the caller's `asm_cpu` |
| `asm_size` | 2 | exported, above |
| `asm_errors` | 2 | exported, above |
| `_line_num` | 2 | current source line, 1-based |
| `_line_buf` | 40 | the line `ed_read_line` returns |
| `_scope_name` | 24 | last global label (≤ 23 chars + NUL) |
| `_full_label` | 48 | `scope.local` (≤ 23 + `.` + ≤ 23 + NUL); also `_insn_out`, `asm_line`'s output scratch |
| `_insn_buf` | 58 | instruction text: mnemonic word ≤ 8 + space + operand with locals expanded, NUL — `@put` refuses the 58th byte with `too long` |
| `_as_conv` | 1 | `.scr` screen-code conversion flag |
| `_eb_idx` | 1 | `.bas` string length |
| `_ib_idx` | 1 | write index into `_insn_buf` |
| `_seg_pc` | 2 | current segment start |
| `_min_pc` | 2 | lowest segment start ($FFFF = no segment) |
| `_max_pc` | 2 | highest segment end (exclusive) |
| `_seg_open` | 1 | nonzero while a segment is open |
| `_pc_wrap` | 1 | nonzero once `asm_pc` wrapped past $FFFF |
| `_oor` | 1 | nonzero: the current line dropped a byte (`range`) |
| `_org_set` | 1 | nonzero after the first `.org`/`.bas` of pass 0 |

`asm_pass` is not asm_src's: it is BSS of asm_err.s
([asm_err.md](asm_err.md)); asm_src writes it at each pass.
`_min_pc` / `_max_pc` are not exported; `seg_print_save` is their
only reader outside the segment logger.

## Caveats

### Error and warning lines

This section owns the formats of the lines an assembly prints; other
documents point here.

| Line | Printed by | When |
|---|---|---|
| `;?N: msg` | `emit_error` | an error on source line `N` (decimal, 1-based), pass 1 — and `fwd ref` from `.res`/`.align` on pass 0 |
| `;!N: truncated` | `do_pass` | pass 1, a line longer than 39 characters (`ed_read_line` dropped the rest) |
| `;!a shadow` | `addr_mode.s::mode_parse` | pass 1, `ASL A` style operand while a symbol `A` is defined |
| `; org  AAAA-BBBB NNNNNb` | `_seg_log_close` → `seg_line` (log.s) | pass 1, each non-empty segment |
| `; N err` | repl.s `exec_line` (`a`) | after the assembly, `N` = `asm_assemble`'s nonzero error count |
| `; ok` + save line | repl.s `exec_line` (`a`), `seg_print_save` | after an assembly with no errors |

`msg` is one of: `bad insn` (asm_line syntax error or unknown
directive), `cpu` (CPU gate), the expression text of `expr_error_str`
for an instruction operand (`exp val`, `ovfl`, `exp )`, `undef`,
`div0`), `bad val` (a directive's value), `ovfl` (`.db` value outside
a byte), `exp id` (missing or malformed name), `exp "` (string
directive without a quote), `fwd ref`, `sym full`, `too long`,
`range`.  There is no `expr` prefix in a source error — `;?12: undef`,
not `;?12: expr undef` (that form is the REPL `.` command's).  `;?`
marks the line as non-executable, consistent with the REPL's error
convention.  The `;?` / `;!` / `; ` prefixes come from `log_open`
([log.md](log.md)).

### Other caveats

- `ed_read_line` keeps at most `LINE_MAX` characters of a line (39;
  79 on m65, whose `_line_buf` is 80 bytes).  When it
  dropped characters (X ≠ 0 on return) the assembler emits the
  warning above; a line of exactly 39 characters is read whole and
  gets no warning.  This is not a fatal error — assembly continues
  with the truncated line.  In practice only trailing comments are
  lost.
- Label length is bounded by the buffers above
  ([assembler_syntax.md § Labels](../assembler_syntax.md#labels)):
  `define_label` refuses a global label over 23 characters or a local
  name over 23 characters after its dot with `too long`, before any
  byte past the buffer is written; a too-long global also clears
  `_scope_name`.
- `_insn_buf` is rebuilt as PETSCII each pass.  `asm_line` operates
  on PETSCII directly — no encoding conversion.
- `fold_block` folds shifted letters ($C1–$DA) in a label or `.const`
  name to $41–$5A **in the source line buffer**; other bytes are
  unchanged.
- The `.const` handler NUL-terminates the name in the line buffer,
  then advances `expr_ptr` by name_len+1 to skip past the NUL before
  evaluating the value expression.  It keeps the name pointer in
  `asm_tmp`/`asm_tmp2` across `expr_eval` — a symbol in the value
  (`.const border vic + $20`) repoints `sym_name` — and restores it
  before defining the name and restoring the displaced byte.  A name
  that ends the line (no value) is `bad val`.
- `.db` on pass 1 checks each value against a byte ($00–$FF or
  −128..−1): a wider value is `ovfl`, and its low byte is still
  emitted so the layout does not move.
- `.cpu` (`set_cpu`) accepts exactly the build's CPU set (§ The CPU
  set); anything else is `bad val`.
