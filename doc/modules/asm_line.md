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

**Depends on:** addr_mode (mode_parse, asm_skip_ws, _au_no_acc),
opcode_lookup (asm_opcode_lookup), mn_classify (mn_base_op,
mn_profile), mn_modes (mn_modes_lo — for the ACC-bit test that
drives _au_no_acc; the IMP→ACC promotion reuses _au_no_acc rather
than re-reading the table), asm_err (asm_syntax_error /
asm_expr_error / asm_expr_err / _asm_saved_sp), mem (kernal_bank_out
/ kernal_bank_in), zp

## Build-time variants

Three production builds (see Makefile `_*_DEFS`) instantiate this
module with different `-D` flag combinations.  The classifier choice
and the in-binary gate behaviour both depend on the flags — so the
module effectively ships as three distinct binaries, each with its
own contract.

| Variant | `-D` flags | Classifier | CMOS reject gate | CMOS upgrade | Illegal gate | Accepts |
|---|---|---|---|---|---|---|
| **6502** | `USE_MN6` | mn6 (56 legal only) | — (unreachable) | — | — (unreachable) | legal NMOS |
| **6510** | (none) | mn7 (114) | **compiled in** | — (tables absent) | **compiled in** | legal + illegals |
| **65C02** | `CMOS_SUPPORT` | mn7 (114) | compiled in | compiled in | compiled in | legal + CMOS |

On mn6 builds, unsupported mnemonics are rejected at the classifier
tier (mn6 doesn't hash them), so the in-binary gate never sees
them — but the gate code is linked anyway (the `cat` byte paths
sit dormant without cost).  On mn7 builds, the classifier accepts
all 114 mnemonics; the gate is the sole defence against the user
asking for an instruction the current `asm_cpu` shouldn't emit.

Bundle-test parity: each production variant has a matching unit-test
bundle in [conftest.py](../../tests/conftest.py) (`AsmCoreSymbols(config=…)`)
and a test class in [test_asm_line.py](../../tests/unit/test_asm_line.py)
(`TestCpuGateCmosBundle`, `TestCpuGate6510Bundle`, `TestAsmLine6502Bundle`).
See [testing.md § Principle 10](../testing.md).

## asm_cpu × category gate matrix

Every mnemonic's `asm_prof` byte encodes a 2-bit category in bits
7:6.  The gate at [asm_line.s:247](../../src/asm_line.s) implements
the table below.  Reject cells emit `jmp asm_error`; accept cells
fall through with the appropriate profile (upgraded to the CMOS
variant when `cat=01` and `asm_cpu>=2` under `CMOS_SUPPORT`).

| | `cat=00` legal NMOS | `cat=01` legal + CMOS-ext | `cat=10` illegal NMOS | `cat=11` pure CMOS |
|---|---|---|---|---|
| `asm_cpu=0` (6502)  | accept | accept (NMOS profile) | **REJECT** | **REJECT** |
| `asm_cpu=1` (6510)  | accept | accept (NMOS profile) | accept | **REJECT** |
| `asm_cpu=2` (65C02) | accept | accept (CMOS profile, needs `CMOS_SUPPORT`) | **REJECT** | accept (needs `CMOS_SUPPORT`) |

Every cell is tested per-variant-bundle in `TestCpuGateCmosBundle`
and `TestCpuGate6510Bundle` (test_asm_line.py).  Populating this
matrix was a direct consequence of the asm_cpu gate Escape Analysis
(doc/README.md § Escape Analysis) — prior to it, the doc named only
`asm_cpu` values and the CMOS gate fact-of-existence; the other 11
cells were unspecified and the 6510 variant's gate was silently
omitted under `.ifdef CMOS_SUPPORT`.

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

### ACC mode handling

Six mnemonics accept the accumulator addressing mode: ASL, LSR, ROL,
ROR (always); INC, DEC (CMOS only).  All six map to operand profile
11 with the mode set `{ACC, ZP, ABS, ZPX, ABX}`.  Both syntactic
forms produce the ACC opcode:

- **Bare** (`ASL`) — mode_parse returns MODE_IMP for an empty operand;
  asm_line's zone G/H entry promotes IMP → ACC when `mn_modes_lo[asm_pidx]`
  has the ACC bit set.  Profiles that don't accept ACC keep MODE_IMP
  (validate_mode then rejects, producing `;?bad insn`).
- **Explicit** (`ASL A`) — mode_parse returns MODE_ACC directly via
  the SC_A path, gated on `_au_no_acc = 0`.

asm_line writes `_au_no_acc` once per instruction, before any
`mode_parse` call:

```
_au_no_acc = (mn_modes_lo[asm_pidx] & MODE_ACC_BIT) ? 0 : nonzero
```

When the profile rejects ACC, `_au_no_acc` is nonzero and the SC_A
path in mode_parse falls through to label resolution.  This is what
lets `JMP A`, `LDA A`, `JSR A`, `BNE A`, etc. resolve a defined
single-letter symbol `A` instead of failing with `;?bad insn`.

### Label-shadow warning

When mode_parse takes the explicit-`A` path on pass 1 and a symbol
named `A` is defined, mode_parse emits `;!a shadow` directly via
`log_warn`.  asm_line is not involved — the warning emission is a
property of the parser's recognition of the shadow case, not a
post-hoc check by the line assembler.  The warning is emitted
exactly once per shadow site (pass-0 detections are suppressed in
mode_parse).

The contract this surfaces: when the user writes `ASL A` against a
defined label `A`, accumulator mode wins.  The user must use a
different name or write the address explicitly to access symbol
`A` from one of the six ACC-accepting mnemonics.  See
[addr_mode.md § ACC vs label disambiguation](addr_mode.md#acc-vs-label-disambiguation)
for the full matrix.

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
