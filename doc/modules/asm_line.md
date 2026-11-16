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
`asm_out` (ZP, output pointer), `asm_cpu` (ZP, CPU mode — the global
enumeration of [build_system.md § Builds and CPU sets](../build_system.md#builds-and-cpu-sets)), Y=0
**Out:** bytes written to `[asm_out]`, `asm_len` = byte count (1–3 on
C64 builds; 1–5 on the m65 build, prefixes included), C = 0 (clear) on
success
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
error-unwind path (`asm_error` / `asm_syntax_error` / `asm_expr_error`
/ `asm_cpu_error`, in [asm_err.md](asm_err.md)) also banks the KERNAL
back in before returning 0, so success and error exits are symmetric.
The four entry points encode three categories into `asm_err_code` so
callers can pick the right user-visible tag — see
[asm_err.md § Error categories](asm_err.md#error-categories).

Input is PETSCII.  Mnemonic characters are normalized to 1–26 via
AND #$1F (handles uppercase, lowercase, and legacy VICII screen
codes identically — see [mn_classify.md](mn_classify.md)).

### Mnemonic word

The mnemonic is one word: a three-letter **key** and an optional
one-character **suffix** directly after it.

| Suffix | Builds | Meaning |
|---|---|---|
| digit `0`–`7` | CPU sets with 65C02 or 4510 | the bit number of a digit-zone key (`RMB` `SMB` `BBR` `BBS`), ORed into the opcode's bits 6:4 |
| `q` | `MEGA_SUPPORT` | the Q form of a quad stem ([§ Prefixes](#prefixes-45gs02)) |

A digit on any other key, a digit-zone key without a digit, `q` on a
key with no Q form, any other fourth character, or a fifth character
is `;?syntax`.  `lda x` is `LDA` with the label `x`; `ldax` is no word.

**Accepted spellings on the m65 build** — a second spelling is accepted
only when the scanner alone can map it onto an existing row (it adds
no row and no table fact):

| Form | Accepted | Listed by the disassembler as |
|---|---|---|
| accumulator | bare or `a`; after a Q form bare only | bare |
| zero-page indirect | `(e),z` where the CPU adds Z; `(e)` on the seven Q forms that do not (`adcq` `andq` `cmpq` `eorq` `orq` `sbcq` `stq`) | as accepted |
| far (32-bit pointer) | `[e],z` / `[e]`, by the same Z rule | as accepted |
| stack-relative | `(e,sp),y` or `(e,s),y` | `(e,sp),y` |
| `$EA` | `nop`, `eom` | `eom` |
| quad form | the key (`stq`, `ldq`) or stem + `q` (`staq`, `ldaq`) | the compendium name (`stq`, `adcq`) |

A spelling that misstates the CPU is `;?syntax` regardless: `(e)`
where Z is added, `,z` where it is not, a register operand after a Q
form (`aslq a` names the label `a`).

### Memory (asm_line.s)

**ZP:** none of its own.  The error-recovery SP snapshot
(`_asm_saved_sp`) and the error-category byte (`asm_err_code`) both
live in [asm_err.md](asm_err.md).

**BSS (`MEGA_SUPPORT` only, 1 byte):** `asm_pfx` — prefix
enumeration for the instruction being assembled: 0 = none, 1 = Q,
2 = far, 3 = Q + far.

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

**Depends on:** expr (`expr_fwd`, `MEGA_SUPPORT` only), addr_mode
(mode_parse, asm_skip_ws, _au_no_acc;
`_au_far` on `MEGA_SUPPORT`), opcode_lookup (asm_validate_mode,
asm_opcode_lookup), mn_asm_tables (`asm_oplen`, the `ASM_ZONE_*`
constants), mn_classify (mn_base_op,
mn_profile), mn_modes (mn_modes_lo — for the ACC-bit test that
drives _au_no_acc; the IMP→ACC promotion reuses _au_no_acc rather
than re-reading the table), asm_err (asm_error, asm_syntax_error,
asm_cpu_error), mem (kernal_bank_out / kernal_bank_in), zp
(`_asm_saved_sp`, `asm_pc`, `asm_out`, `asm_len`, `asm_*`
slot/profile state).

The `asm_err_code` byte itself is BSS owned by asm_err.s — it's
written by `asm_error` and read by asm_src.s; asm_line is not in
the read or write path.

## Build-time variants

Four CPU sets (see [build_system.md § Builds and CPU sets](../build_system.md#builds-and-cpu-sets))
instantiate this module with different `-D` flag combinations.  The classifier choice
and the in-binary gate behaviour both depend on the flags — so the
module effectively ships as three distinct binaries, each with its
own contract.

| Variant | `-D` flags | Classifier | CMOS reject gate | CMOS upgrade | Illegal gate | Accepts |
|---|---|---|---|---|---|---|
| **c64-6502** | `USE_MN6` | mn6 (56 legal only) | — (unreachable) | — | — (unreachable) | legal NMOS |
| **c64-6510** | `ILLEGAL_SUPPORT` | mn7 (114) | **compiled in** | — (tables absent) | **compiled in** | legal + illegals |
| **c64-65c02** | `ILLEGAL_SUPPORT` `CMOS_SUPPORT` | mn7 (114) | compiled in | compiled in | compiled in | legal + CMOS |
| **m65-45gs02** | `MEGA_SUPPORT` | mn7, m65 keys (98) | compiled in | compiled in (4510 extension) | — | legal + 65C02 + 4510; Q and far forms at `asm_cpu=4` |

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
the table below.  Reject cells emit `jmp asm_cpu_error` (so the
caller's dispatcher selects the `;?cpu` tag rather than the
strictly-correct-but-misleading `;?syntax`); accept cells fall
through with the appropriate profile (upgraded to the CMOS variant
when `cat=01` and `asm_cpu>=2` under `CMOS_SUPPORT`).

| | `cat=00` legal NMOS | `cat=01` legal + CMOS-ext | `cat=10` illegal NMOS | `cat=11` pure CMOS |
|---|---|---|---|---|
| `asm_cpu=0` (6502)  | accept | accept (NMOS profile) | **REJECT** | **REJECT** |
| `asm_cpu=1` (6510)  | accept | accept (NMOS profile) | accept | **REJECT** |
| `asm_cpu=2` (65C02) | accept | accept (CMOS profile, needs `CMOS_SUPPORT`) | **REJECT** | accept (needs `CMOS_SUPPORT`) |

**m65 build** (`asm_cpu` ∈ {0, 3, 4}):

| | `cat=00` legal NMOS | `cat=01` legal + 4510 ext | `cat=10` Q name | `cat=11` 4510-only |
|---|---|---|---|---|
| `asm_cpu=0` (6502)   | accept | accept (NMOS profile) | **REJECT** | **REJECT** |
| `asm_cpu=3` (4510)   | accept | accept (extension profile) | **REJECT** | accept |
| `asm_cpu=4` (45GS02) | accept | accept (extension profile) | accept (Q, `pidx` is the Q profile) | accept |

The **effective profile** is `pidx` after the extension upgrade.  The
`q` suffix is accepted iff `asm_cpu=4`, `cat≠10`, and the effective
profile lies in zone Q ([opcode_lookup.md § Profile index layout](opcode_lookup.md#design));
the Q profile is then effective + 1.  Otherwise `q` is `;?cpu` on
`asm_cpu` 0/3 for a quad stem, `;?syntax` for any other key.

Every cell is tested per-variant-bundle in `TestCpuGateCmosBundle`
and `TestCpuGate6510Bundle` (test_asm_line.py).  Populating this
matrix was a direct consequence of the asm_cpu gate Escape Analysis
(doc/README.md § Escape Analysis) — prior to it, the doc named only
`asm_cpu` values and the CMOS gate fact-of-existence; the other 11
cells were unspecified and the 6510 variant's gate was silently
omitted under `.ifdef CMOS_SUPPORT`.

## Design

**Zone dispatch:** The effective profile's zone (generated constants
`ASM_ZONE_*`, [opcode_lookup.md § Profile index layout](opcode_lookup.md#design))
determines which path assembles the instruction:

| Zone | Mode | Examples |
|------|------|---------|
| A | Implied | BRK, CLC, DEX, NOP, RTS; on m65 also TAZ, MAP, EOM, … |
| B | Branch (REL; REL16 on `MEGA_SUPPORT`) | BCC, BEQ, BNE, BPL, …; on m65 also BSR |
| C | Immediate only | illegal ANC/ALR/…; on m65 RTN |
| D | Bit-op ZP (RMB/SMB) | RMB0–7, SMB0–7 |
| E | Bit-op ZP,REL (BBR/BBS) | BBR0–7, BBS0–7 |
| F | Absolute only | JSR (C64); ASW, ROW (m65) |
| G | Multi-mode extension pairs | DEC, INC, BIT, JMP, LDA, …; JSR on m65 |
| Q | Multi-mode quad groups (`MEGA_SUPPORT`) | LDA/LDQ, ADC/ADCQ, ASL/ASLQ, … |
| H | Multi-mode, the rest | LDX, STX, CPX, CPY, … |

Zones A–F handle fixed single-shape instructions inline.  Zones G, Q
and H call `mode_parse` to determine the addressing mode, then
`asm_validate_mode` and `asm_opcode_lookup` to compute the opcode byte;
the operand byte count is the generated `asm_oplen[mode]`.

### Branches (zone B)

The operand is the target address; the offset is computed.  For `REL`
the offset is `target − (asm_pc + 2)`, valid in −128..127.  On
`MEGA_SUPPORT` a profile may also (or only) accept `REL16`, a 16-bit
offset `target − (asm_pc + 2)` (the address of the instruction's last
byte).  Width: a **forward** target — `expr_fwd` set: the target
expression reads a symbol not yet defined in the current pass
([symtab.md § Pass stamp](symtab.md#pass-stamp-mega_support)) — takes
`REL` where the profile has it; otherwise `REL` if the profile has it
and the target is in reach, else `REL16` if the profile has it, else
out of range (`;?syntax`).  Both passes see the same forward/backward
split, so the width — and every later address — is pass-stable.  A
forward `REL` whose target is out of reach on pass 1 is an error; the
source then needs a backward target or a `jmp`.

### IMM16 promotion (`MEGA_SUPPORT`)

`mode_parse` returns IMM for every `#expr`.  On a profile that accepts
IMM16 and not IMM (`PHW`), asm_line promotes IMM to IMM16 and emits
both operand bytes; elsewhere IMM stays IMM and emits the low byte, as
on the C64 builds.  Same shape as the IMP → ACC promotion.

### Prefixes (45GS02)

The 45GS02's Q and far forms are modifiers on a 4510 row, not
opcodes.  A Q form (the `q` suffix or a `cat=10` key) emits `$42 $42`;
a far operand (`[e]`, `[e],z` — flagged by mode_parse) emits `$EA`.
Far is valid exactly where the effective profile accepts the parsed
zero-page-indirect mode (`ZPI` or `ZPIZ`), so the mask test that admits
`(e)` / `(e),z` admits `[e]` / `[e],z`.  Emission order: `$42 $42` if
Q, `$EA` if far, the opcode, `asm_oplen[mode]` operand bytes.  Both
prefixes exist only at `asm_cpu=4`: on 0 and 3 a Q form or a far
operand is `;?cpu`.

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

**Error handling:** On any error, asm_line's chain jumps into one
of four entry points in [`asm_err.s`](asm_err.md): `asm_error` /
`asm_syntax_error` (code 0), `asm_expr_error` (code 1), or
`asm_cpu_error` (code 2).  All four restore the 6502 SP from
`_asm_saved_sp`, bank the KERNAL back in, and return 0; they differ
only in the value written to `asm_err_code`.  Callers read
`asm_err_code` after a zero return to pick the user-visible tag —
see [asm_err.md § Error categories](asm_err.md#error-categories)
for the full table.

asm_line itself uses two of these directly: `jmp asm_error` for
unknown mnemonics (mn_classify miss) and bad-mode-for-profile;
`jmp asm_cpu_error` for the CPU-gate reject paths.  The third
(`asm_expr_error`) is reached transitively via
`addr_mode.s::_au_read_val` when `expr_eval` returns an error on
pass 1.

## Caveats

- Input is PETSCII (uppercase $41–$5A or lowercase $61–$7A).
  AND #$1F normalization in `_asm_rd_upper` handles both cases
  and is also backward-compatible with raw VICII screen codes.
- `asm_cpu` values: 0=6502, 1=6510, 2=65C02, 3=4510, 4=45GS02 (one
  global enumeration).  The CMOS gate's `cmp #2` compares are compiled
  only into C64 builds, the 4510 gate's `cmp #3` only into the m65 build,
  so each build compares within its own CPU set.
- Zone B accepts `$XXXX` absolute target for branches; computes
  signed offset internally.
- `mn7_classify` clobbers Y (sets Y=mn_c2).  `ldy #0` is required
  before zone dispatch.
