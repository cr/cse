# opcode_lookup.s — Opcode Byte Computation

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/opcode_lookup.s`](../../src/opcode_lookup.s) | implementation |
| [`src/mn_asm_tables.s`](../../src/mn_asm_tables.s) | generated — one block per CPU set: `asm_row` (1 B per profile) + `asm_delta` (one row per delta row) + `asm_oplen` (operand bytes per mode; read by asm_line) + `ASM_ZONE_G`, produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py); back-link-exempt (generated) |
| [`src/mn_modes.s`](../../src/mn_modes.s) | generated — one block per CPU set: the profile validity masks, one plane per 8 modes (`mn_modes_lo`, `mn_modes_hi`; `mn_modes_x` on `MEGA_SUPPORT`), 1 B per profile per plane, produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py); back-link-exempt (generated) |
| [`src/oplen_tbl.s`](../../src/oplen_tbl.s) | generated — packed opcode → single-byte-instruction length (64 B, 2 bits/opcode; prefixes not counted).  One content for all C64 CPU sets (every `OPCODES` row's length; where a 6510 crash opcode (JAM) shares a byte with another row, e.g. `$D2` CIM / 65C02 `CMP (zp)`, the other row's length wins; any other length conflict stops the generator); the m65 CPU set gets its own block.  Produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py).  Consumers: `debugger.s`, `repl.s` (cmd_step).; back-link-exempt (generated) |
| [`tests/unit/test_opcode_lookup.py`](../../tests/unit/test_opcode_lookup.py) | test contract (every profile × mode of every C64 CPU set; end to end by test_asm_line.py::test_assemble) |

## Interface

### asm_opcode_lookup
**In:** `asm_pidx`, `asm_base`, `asm_mode` (all ZP)
**Out:** C=0 and A = opcode byte
(`asm_base ^ asm_delta[asm_row[asm_pidx] + asm_mode]`) if the profile
accepts the mode; C=1 (A undefined) if not.
**Clobbers:** A, X, Y

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
byte; per delta row one byte per mode, the row being as wide as the
CPU set's highest used mode index + 1 (13 on the 6502 and 6510 sets,
16 on the 65C02 set, 20 on the m65 set).  `asm_row[pidx]` holds the
row's byte offset into `asm_delta` (row × width), so the lookup is a
mask test, one indexed load and an `EOR`:

```
bit = _bit_tab[mode & 7]; plane = mode >> 3
if (mn_modes_<plane>[pidx] & bit) == 0:  C = 1
else:  A = asm_base ^ asm_delta[asm_row[pidx] + mode];  C = 0
```

A mode the set never uses has no mask bit in any profile, so the load
never indexes past a row.  Delta rows are merged wherever two
profiles never disagree on a mode both accept, to the exact minimum —
the chromatic number of the profiles' conflict graph, computed by the
generator.

**Mode constants** (the catalogue index of `dev/instruction_set.py`
`ALL_MODES`; append-only): 0 IMP, 1 ACC, 2 IMM, 3 ZP, 4 ZPX, 5 ZPY,
6 ABS, 7 ABX, 8 ABY, 9 IND, 10 INX, 11 INY, 12 REL, 13 ZPI, 14 AIX,
15 ZPREL; on `MEGA_SUPPORT` also 16 IMM16, 17 REL16, 18 ISPY, 19 ZPIZ.

**Profile index layout (`pidx`).**  The generator numbers the profiles
of a CPU set in zones.  A key's zone is how asm_line *parses* it, not
only what it encodes:

| Zone | Holds | Parsed by |
|---|---|---|
| A | implied-only profiles | asm_line inline |
| B | branch profiles (modes ⊆ {REL, REL16}) | asm_line inline |
| F | absolute-only profiles | asm_line inline |
| C | immediate-only profiles | asm_line inline |
| D | digit-zone ZP (`RMB`/`SMB`) | asm_line inline |
| E | digit-zone ZPREL (`BBR`/`BBS`) | asm_line inline |
| G | multi-mode extension pairs: (NMOS profile, extension profile) adjacent | mode_parse + lookup |
| Q | (`MEGA_SUPPORT` only) the 45GS02 quad groups: (NMOS, extension, Q) or (plain, Q), adjacent | mode_parse + lookup |
| H | the remaining multi-mode profiles | mode_parse + lookup |

- The **fixed zones** come first, in the order A B F C D E, one
  profile each on the C64 CPU sets, and a set numbers only the zones
  it has: the order makes every set's zones a prefix (6502: A B F;
  6510: A B F C; 65C02: all six), so no set carries an empty profile
  and asm_line's jump table is indexed by `pidx` directly.
- **`ASM_ZONE_G`** (generated) is the first multi-mode `pidx`; the
  m65 block adds the bounds its dispatch needs (the branch zone's
  range, `ASM_ZONE_Q`, `ASM_ZONE_H`).
- The two members of an **extension pair** are adjacent — the
  extension of a key is at `pidx + 1` — and both multi-mode; where a
  4510 extension leaves its NMOS profile's fixed zone (`JSR`: `ABS` →
  `ABS`/`IND`/`AIX`), both members lie in zone G.  The Q profile of a
  key is at its *effective* profile + 1
  ([asm_line.md § Gate](asm_line.md#asm_cpu--category-gate-matrix)).
- **Sharing.**  A multi-mode key shares the `pidx` of any multi-mode
  profile identical to its own (a pair member included), never a
  fixed-zone profile's: the 4510's zero-page-only `DEW`/`INW` encode
  like zone D's profile but are not bit-digit keys.

The generator refuses to write tables that break any of these rules.

## Caveats

- Mask planes are separate tables indexed by `pidx`, not a
  multi-byte record per profile, so a plane test is one indexed
  `AND`.
