# asm_line.s — Single-Line Instruction Assembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_line.s`](../../src/asm_line.s) | implementation — line assembler core, KERNAL banking, error recovery |
| [`src/zp.s`](../../src/zp.s) | ZP definitions (central, shared by all modules) |
| [`tests/unit/test_asm_line.py`](../../tests/unit/test_asm_line.py) | test contract |

## Interface

### _asm_line_core
**In:** `asm_ptr` (ZP, text pointer, PETSCII), `asm_pc` (ZP, address),
`asm_out` (ZP, output pointer), `asm_cpu` (ZP, CPU mode), Y=0
**Out:** bytes written to `[asm_out]`, `asm_len` = byte count (1–3),
C = 0 (clear) on success
**Clobbers:** A, X, Y, all asm_* ZP vars

### asm_line (public entry point)
**In:** A/X = text pointer (PETSCII), `asm_pc`/`asm_out` set by caller
**Out:** A = byte count (0 = error), X = 0
**Clobbers:** all

`asm_line` is the **single shared entry point** for both the
source-pass and the line-asm REPL command:

| Caller | Path |
|--------|------|
| `asm_src.s::process_line` | inside `asm_assemble`'s batched bank-out (`kernal_out=1`) — `asm_line`'s inner bank helpers short-circuit, so the per-call cost is just the flag check |
| `repl.s::dot_assemble` | single-line REPL `.` command — `asm_line`'s inner bank helpers do the actual KERNAL bank-out for KDATA-table reads |

`asm_line` owns its own KERNAL banking (bracket of
`kernal_bank_out`/`kernal_bank_in` around the `_asm_line_core` call).
Callers do not — and must not — bank the KERNAL themselves.  The
error-unwind path (`asm_error` / `asm_syntax_error` / `asm_expr_error`,
in [asm_err.md](asm_err.md)) also banks the KERNAL back in before
returning 0, so success and error exits are symmetric.

Input is PETSCII.  Mnemonic characters are normalized to 1–26 via
AND #$1F (handles uppercase, lowercase, and legacy VICII screen
codes identically — see [mn_classify.md](mn_classify.md)).

### Memory (asm_line.s)

**ZP:** none of its own.  The error-recovery SP snapshot
(`_asm_saved_sp`) and the expression-error flag (`asm_expr_err`)
both live in [asm_err.md](asm_err.md).

**BSS (182 bytes — user register shadows):**

| Variable | Size | Purpose |
|----------|------|---------|
| `reg_a` | 1 | Saved user A register (read by debugger.s + repl.s) |
| `reg_x` | 1 | Saved user X register |
| `reg_y` | 1 | Saved user Y register |
| `reg_sp` | 1 | Saved user stack pointer |
| `reg_p` | 1 | Saved user status flags |
(The ZP save/restore buffers `kernel_zp_buf` and `userland_zp_buf`
used to live here; as of Phase 18 they are owned by `mem.s`
alongside the `save_userland_zp` / `restore_userland_zp` /
`save_kernel_zp` / `restore_kernel_zp` primitives.)

**Depends on:** addr_mode (mode_parse, asm_skip_ws), opcode_lookup
(asm_opcode_lookup), mn_classify (mn_base_op, mn_profile), asm_err
(asm_syntax_error / asm_expr_error / asm_expr_err / _asm_saved_sp),
mem (kernal_bank_out / kernal_bank_in), zp

## Design

**Zone dispatch:** The mnemonic's operand profile (from mn7_profile)
determines which zone handles assembly.  30 profiles mapped to 8 zones:

| Zone | Profiles | Mode | Examples |
|------|----------|------|---------|
| A | 0 | Implied | BRK, CLC, DEX, NOP, RTS, ... |
| B | 1 | Relative (branch) | BCC, BEQ, BNE, BPL, ... |
| C | 2 | Immediate | LDX #$00, CPX #$FF, ... |
| D | 3 | Bit-op ZP (RMB/SMB) | RMB0–7, SMB0–7 |
| E | 4 | Bit-op ZP,REL (BBR/BBS) | BBR0–7, BBS0–7 |
| F | 5 | Absolute (JSR only) | JSR $XXXX |
| G | 6–15 | Multi-mode (2–5 modes) | LDX, STX, CPX, CPY, DEC, INC, ... |
| H | 16–29 | Multi-mode (3–8 modes) | LDA, STA, ADC, AND, ORA, JMP, ... |

Zones A–F handle fixed single-mode instructions inline.  Zones G and H
call `mode_parse` to determine the addressing mode, then
`asm_opcode_lookup` to compute the opcode byte.

**Error handling:** On any error, `jmp asm_error` (in asm_err.s)
restores the 6502 SP from `_asm_saved_sp` and returns 0 to the
caller.  `asm_expr_err` is cleared to 0.  Expression evaluation
errors use the `asm_expr_error` entry point, which loads A=1 then
merges into `asm_error`'s shared tail via a BIT-abs skip (the
`lda #0` at `asm_error` is consumed as a BIT operand, preserving
A=1).  Both paths store A into `asm_expr_err` and share the SP
restore, bank-in, and return.  Callers check `asm_expr_err` after
a zero return to distinguish syntax errors from expression errors
and can call
`expr_error_str` for the specific message (e.g. "undef").

## Caveats

- Input is PETSCII (uppercase $41–$5A or lowercase $61–$7A).
  AND #$1F normalization in `_asm_rd_upper` handles both cases
  and is also backward-compatible with raw VICII screen codes.
- `asm_cpu` values: 0=6502, 1=6510, 2=65C02.  CMOS gate uses
  `cmp #2`/`bcs`/`bcc` — only asm_cpu=2 enables CMOS extensions.
- Zone B accepts `$XXXX` absolute target for branches; computes
  signed offset internally.
- `mn7_classify` clobbers Y (sets Y=mn_c2).  `ldy #0` is required
  before zone dispatch.
