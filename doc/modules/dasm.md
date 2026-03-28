# dasm.s — Disassembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/dasm.s`](../../src/dasm.s) | implementation |
| [`src/dasm_mne_idx.s`](../../src/dasm_mne_idx.s) | implementation — mnemonic index table |
| [`tests/test_dasm.py`](../../tests/test_dasm.py) | test contract |

## Interface

### _dasm_insn
**In:** A/X = instruction address (lo/hi)
**Out:** A = instruction length (1–3).  `_dasm_buf` filled with
NUL-terminated PETSCII string.
**Clobbers:** A, X, Y, all _dasm_* ZP vars

**BSS:** `_dasm_buf` (24B) — output buffer, PETSCII, NUL-terminated.

**Depends on:** dasm_tables (GENERATED)

## Design

Bit-slice decoder exploiting the 6502 `aaabbbcc` opcode structure.
Dispatches on `cc = opcode & 3`:

| cc | Group | Strategy |
|----|-------|----------|
| 01 | Group 1 | Perfectly regular: `aaa`→mnemonic, `bbb`→mode.  8-entry tables. |
| 10 | Group 2 | Semi-regular: odd `bbb` rows regular, even rows use exception tables. |
| 00 | Group 0 | Sub-dispatch: branches, implied (bbb=2,6), memory ops. |
| 11 | Group 3 | CPU-dependent: 6502→`???`, 6510→illegal table, 65C02→RMB/SMB/BBR/BBS. |

**CPU mode** (`al_cpu`): 0=6502 (legal only, illegals→`...`),
1=6510 (legal+illegal), 2=65C02 (legal+CMOS).

**Mnemonic packing:** 3 chars packed into 2 bytes (5 bits per char,
A=1..Z=26, 27=dot).  Unknown opcodes pack as 27,27,27 → `...`.
Unpacked to PETSCII for output.

**Mode formatting:** 16 mode descriptors (1 byte each) encode prefix,
operand size, and suffix.  Instruction length derived from mode.

**CMOS guard:** 65C02-specific code and tables should be wrapped in
`.ifdef CMOS_SUPPORT` so they're excluded from 6502/6510-only builds.
**Currently not implemented** — CMOS paths are always present, gated
at runtime only.  See TODO.md.

## Caveats

- Output is PETSCII (not VICII screen codes).  Caller does
  `io_puts(dasm_buf)` to display.
- The disassembler has zero I/O dependency — pure computation.
- `_dasm_buf` is 24 bytes: 3 (mnemonic) + 1 (space) + up to 9
  (operand, longest is ZPREL `$XX,$XXXX`) + NUL + padding.
