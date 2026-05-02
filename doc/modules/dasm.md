# dasm.s — Disassembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/dasm.s`](../../src/dasm.s) | implementation |
| [`src/dasm_tables.s`](../../src/dasm_tables.s) | generated — packed mnemonic strings (115 entries, 230 B), produced by [`dev/dasm_tables.py`](../../dev/dasm_tables.py) |
| [`src/dasm_mne_idx.s`](../../src/dasm_mne_idx.s) | generated — mnemonic index constants (`MNE_*`), produced by [`dev/dasm_tables.py`](../../dev/dasm_tables.py) |
| [`tests/unit/test_dasm.py`](../../tests/unit/test_dasm.py) | test contract |

## Interface

### dasm_insn
**In:** A/X = instruction address (lo/hi).  `asm_cpu` (ZP) selects
CPU mode: 0=6502, 1=6510, 2=65C02.
**Out:** A = instruction length (1–3).  `dasm_buf` filled with
NUL-terminated PETSCII string.
**Clobbers:** A, X, Y, all _dasm_* ZP vars

`dasm_insn` owns its own KERNAL banking: it banks out at entry,
calls the inner `dasm_decode` (which reads `dasm_mne_str` and
the mode/operand tables under KERNAL), and banks back in at
every exit.  Callers — currently `repl.s::emit_dot` (used by
both the `d` block-disassemble command and the `.` single-line
command) — just call `dasm_insn` and don't manage banking.

The wrapper structure is the same as `asm_line` in
`asm_line.s`: a thin entry that brackets the decoder with
`kernal_bank_out` / `kernal_bank_in`.  Because the wrapper
guards the call with `pha` / `jsr kernal_bank_in` / `pla`, the
length result returned by any of `dasm_decode`'s exits (the
common `finish` path, the cc=11 RMB/SMB inline `rts`, and the
cc=11 BBR/BBS inline `rts`) all pair correctly with the entry
`bank_out`.  No exit can leave the KERNAL mapped out by accident.

### Memory

**ZP (8 bytes):** `_dasm_ptr` (2), `_dasm_opc` (1), `_dasm_mne` (2), `_dasm_wptr` (1), `_dasm_midx` (1), `_dasm_mode` (1).

**BSS (27 bytes):** `dasm_buf` (24) — output buffer for the
disassembled instruction text (PETSCII + NUL); `_dasm_in` (3) —
input snapshot of the 3 max-insn bytes read from the user's
address before banking out (see Caveats).

**Depends on:** dasm_tables (GENERATED), kernal_bank_out /
kernal_bank_in (mem.s)

## Design

Bit-slice decoder exploiting the 6502 `aaabbbcc` opcode structure.
Dispatches on `cc = opcode & 3`:

| cc | Group | Strategy |
|----|-------|----------|
| 01 | Group 1 | Perfectly regular: `aaa`→mnemonic, `bbb`→mode.  8-entry tables. |
| 10 | Group 2 | Semi-regular: odd `bbb` rows regular, even rows use exception tables. |
| 00 | Group 0 | Sub-dispatch: branches, implied (bbb=2,6), memory ops. |
| 11 | Group 3 | CPU-dependent: 6502→`???`, 6510→illegal table, 65C02→RMB/SMB/BBR/BBS. |

**CPU mode** (`asm_cpu`): 0=6502 (legal only, illegals→`...`),
1=6510 (legal+illegal), 2=65C02 (legal+CMOS).

**Mnemonic packing:** 3 chars packed into 2 bytes (5 bits per char,
A=1..Z=26, 27=dot).  Unknown opcodes pack as 27,27,27 → `...`.
Unpacked to PETSCII for output.

**Mode formatting:** 16 mode descriptors (1 byte each) encode prefix,
operand size, and suffix.  Instruction length derived from mode.

**Compile-time guards:** 65C02-specific code and tables are wrapped
in `.ifdef CMOS_SUPPORT`; 6510 illegal opcode paths use
`.ifndef CPU_6502`.  A 6502-only build contains neither.  Runtime
`lda asm_cpu` checks remain within guarded blocks for the 6510 vs
65C02 distinction.

## Caveats

- Output is PETSCII (not VICII screen codes).  Caller does
  `io_puts(dasm_buf)` to display.
- The disassembler has zero I/O dependency — pure computation.
- `dasm_buf` is 24 bytes: 3 (mnemonic) + 1 (space) + up to 9
  (operand, longest is ZPREL `$XX,$XXXX`) + NUL + padding.
- **KERNAL ROM snapshot.**  `dasm_insn` snapshots 3 bytes from
  the user's address into `_dasm_in` BEFORE banking out, using
  whatever bank state the caller had in force.  The decoder
  then reads opcode/operand bytes from `_dasm_in` via
  `lda _dasm_in,y` instead of `(_dasm_ptr),y`.  `_dasm_ptr`
  itself stays at the user's actual address — used by
  `_compute_branch_target` for PC-relative branch destinations
  (`bcc $XXXX` / `bne $XXXX` / `BBR` / `BBS`).  Without the
  snapshot, disassembly of `$E000+` would read the RAM under
  KERNAL (mostly $00 → BRK).  See `tests/integration/test_dasm_rom.py`.
