# opcode_lookup.s — Opcode Byte Computation

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/opcode_lookup.s`](../../src/opcode_lookup.s) | implementation |
| [`src/mn_asm_tables.s`](../../src/mn_asm_tables.s) | generated — one block per CPU set: `asm_row` (1 B per profile) + `asm_delta` (one row of `ASM_N_MODES` bytes per delta row) + `asm_oplen` (operand bytes per mode, `ASM_N_MODES` B; read by asm_line) + the zone constants, produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py) |
| [`src/mn_modes.s`](../../src/mn_modes.s) | generated — one block per CPU set: the profile validity masks, one plane per 8 modes (`mn_modes_lo`, `mn_modes_hi`; `mn_modes_x` on `MEGA_SUPPORT`), 1 B per profile per plane, produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py) |
| [`src/oplen_tbl.s`](../../src/oplen_tbl.s) | generated — one block per CPU set: packed opcode → single-byte-instruction length (64 B, 2 bits/opcode; prefixes not counted), produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py).  Consumers: `debugger.s`, `repl.s` (cmd_step). |
| [`tests/unit/test_opcode_lookup.py`](../../tests/unit/test_opcode_lookup.py) | test contract (asm_validate_mode predicate; asm_opcode_lookup covered exhaustively by test_asm_line.py::test_assemble) |

## Interface

### asm_validate_mode
**In:** `asm_pidx` (ZP), `asm_mode` (ZP)
**Out:** C=0 if the profile accepts the mode, C=1 if not
**Clobbers:** A, X, Y

### asm_opcode_lookup
**In:** `asm_pidx`, `asm_base`, `asm_mode` (all ZP).  Precondition:
`asm_validate_mode` accepted (`asm_pidx`, `asm_mode`).
**Out:** A = opcode byte (`asm_base ^ asm_delta[asm_row[asm_pidx] + asm_mode]`).
No error exit — every accepted (profile, mode) pair has a delta.
**Clobbers:** A, X

### Memory

**ZP:** none.

**RODATA (8 bytes):** `_bit_tab` (8) — bit masks for the mode's bit
within its mask plane.

**Depends on:** mn_modes (validity masks), mn_asm_tables (`asm_row`,
`asm_delta`), zp

## Design

**Profile.**  A profile is a pair: the set of modes a key accepts and
the delta row that turns the key's `base` opcode into each mode's
opcode.  `base` is the key's own zero-page opcode, else its absolute
opcode, else its lowest mode's — so it is always one of the key's
opcodes — and `delta[mode] = opcode ^ base`.  Every special case of an
encoding (`STZ`, `TRB`/`TSB`, `BIT #`, `JMP (a,X)`, the `cc=11` `ABY`
column, every 4510 row) is a row of the tables, not code.

**Tables.**  Per profile one mask byte per plane and one `asm_row`
byte; per delta row `ASM_N_MODES` bytes (16 on C64 CPU sets, 20 on m65
CPU sets).  `asm_row[pidx]` holds the row's byte offset into
`asm_delta` (row × `ASM_N_MODES`), so the lookup is one indexed load
and an `EOR`:

```
validate:  bit = _bit_tab[mode & 7]; plane = mode >> 3
           C = (mn_modes_<plane>[pidx] & bit) == 0
lookup:    A = asm_base ^ asm_delta[asm_row[pidx] + mode]
```

Delta rows are merged wherever two profiles never disagree on a mode
both accept, to the exact minimum — the chromatic number of the
profiles' conflict graph, computed by the generator.

**Mode constants** (the catalogue index of `dev/instruction_set.py`
`ALL_MODES`; append-only): 0 IMP, 1 ACC, 2 IMM, 3 ZP, 4 ZPX, 5 ZPY,
6 ABS, 7 ABX, 8 ABY, 9 IND, 10 INX, 11 INY, 12 REL, 13 ZPI, 14 AIX,
15 ZPREL; on `MEGA_SUPPORT` also 16 IMM16, 17 REL16, 18 ISPY, 19 ZPIZ.

**Profile index layout (`pidx`).**  The generator numbers the profiles
of a CPU set in zones, so every modifier decision downstream is a
range compare on `pidx` against a generated constant:

| Zone | Constant (first `pidx`) | Holds | Parsed by |
|---|---|---|---|
| A | `ASM_ZONE_A` | implied-only profiles | asm_line inline |
| B | `ASM_ZONE_B` | branch profiles (modes ⊆ {REL, REL16}) | asm_line inline |
| C | `ASM_ZONE_C` | immediate-only profiles | asm_line inline |
| D | `ASM_ZONE_D` | digit-zone ZP (`RMB`/`SMB`) | asm_line inline |
| E | `ASM_ZONE_E` | digit-zone ZPREL (`BBR`/`BBS`) | asm_line inline |
| F | `ASM_ZONE_F` | absolute-only profiles | asm_line inline |
| G | `ASM_ZONE_G` | multi-mode extension pairs: (NMOS profile, extension profile) adjacent | mode_parse + lookup |
| Q | `ASM_ZONE_Q` (`MEGA_SUPPORT` only) | the 45GS02 quad groups: (NMOS, extension, Q) or (plain, Q), adjacent | mode_parse + lookup |
| H | `ASM_ZONE_H` | the remaining multi-mode profiles | mode_parse + lookup |

A zone may be empty (its constant equals the next one's).  The two
members of an extension pair always lie in one zone; where the
extension leaves its NMOS profile's zone (the 4510 `JSR`: `ABS` →
`ABS`/`IND`/`AIX`), both members lie in zone G.  The extension of a
key is at `pidx + 1`; the Q profile of a key is at its *effective*
profile + 1 ([asm_line.md § Gate](asm_line.md#asm_cpu--category-gate-matrix)).
The generator refuses to write tables that break any of these
placement rules.

## Caveats

- `asm_opcode_lookup` trusts its precondition: called with a mode
  the profile rejects, it returns an unspecified byte.  asm_line
  always validates first.
- Mask planes are separate tables indexed by `pidx`, not a
  multi-byte record per profile, so a plane test is one indexed
  `AND`.
