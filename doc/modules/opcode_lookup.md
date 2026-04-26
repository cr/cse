# opcode_lookup.s — Opcode Byte Computation

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/opcode_lookup.s`](../../src/opcode_lookup.s) | implementation |
| [`src/mn_asm_tables.s`](../../src/mn_asm_tables.s) | generated — `mode_offset` (64 B) + `direct_opcodes` (16 B), produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py).  Also consumed by `dasm.s`. |
| [`src/mn_modes.s`](../../src/mn_modes.s) | generated — operand-profile addressing-mode bitfield (30 profiles × 2 B = 60 B), produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py).  Also consumed by `dasm.s`. |
| [`src/oplen_tbl.s`](../../src/oplen_tbl.s) | generated — packed opcode→instruction-length table (64 B), produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py).  Consumers: `asm_line.s`, `debugger.s`, `repl.s` (cmd_step). |
| [`tests/unit/test_opcode_lookup.py`](../../tests/unit/test_opcode_lookup.py) | test contract (asm_validate_mode predicate; asm_opcode_lookup covered exhaustively by test_asm_line.py::test_assemble) |

## Interface

### asm_validate_mode
**In:** `asm_pidx` (ZP), `asm_mode` (ZP)
**Out:** C=0 if mode is valid for this profile, C=1 if invalid
**Clobbers:** A, Y

### asm_opcode_lookup
**In:** `asm_pidx`, `asm_prof`, `asm_base`, `asm_mode` (all ZP)
**Out:** A = final opcode byte.  On invalid mode: `jmp asm_error`.
**Clobbers:** A, X, Y

### Memory

**ZP (1 byte):** `_asm_ok_tmp` (1) — scratch, caches cat bits at entry.

**RODATA (8 bytes):** `_bit_tab` (8) — bit masks for Zone D/E.

**Depends on:** mn_modes (mode bitmasks), mn_asm_tables (mode_offset,
direct_opcodes), asm_err (asm_error), zp

## Design

Computes `opcode = asm_base | mode_offset[zone*16 + asm_mode]` for
regular instructions.  Five dispatch steps handle exceptions:

1. `dir_bit=1` → `direct_opcodes[asm_mode]` (STZ, profile 28)
2. `cat=11` → profile 29 special (TRB/TSB: ZP→base, ABS→base|$08)
3. `cat=01` → CMOS exception check (ZPI, ACC, IND, AIX, BIT IMM=$89)
4. `zone=3 + ABY` → inline bbb dispatch (bbb=6 vs 7 conflict)
5. Fall-through → formula

**Packed profile byte (`asm_prof`):**
- bits 7:6 = cat (00=legal-NMOS, 01=CMOS-extended, 10=illegal, 11=special)
- bit 5 = dir_bit (1=direct opcode table)
- bits 4:0 = pidx (profile index 0–29)

**Mode constants (0–15):** IMP, ACC, IMM, ZP, ZPX, ZPY, ABS, ABX,
ABY, IND, INX, INY, REL, ZPI, AIX, ZPREL

## Caveats

- `mode_offset[cc=11][ABY]` = $FF (sentinel).  Step 4 diverts all
  zone=3/ABY before the table is read.
- `_ok_tmp` ZP byte caches cat bits at entry; repurposed for zone*16
  at step 5.
