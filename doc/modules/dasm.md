# dasm.s — Disassembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/dasm.s`](../../src/dasm.s) | implementation — entry, prefix peel, map decode, operand formatter |
| [`src/dasm_tables.s`](../../src/dasm_tables.s) | generated — one block per CPU set: the map blocks, the per-`asm_cpu` view tables (`dasm_cpu_map_lo/hi`; `dasm_cpu_bm` + `dasm_view_bm` where a view is a subset bitmap), `dasm_mode_len` and `dasm_mode_fmt` (one byte per mode) in RODATA; the packed mnemonic strings (the set's names only) in KDATA; on `MEGA_SUPPORT` also the Q map, and on m65 the map blocks in KDATA instead (§ Design).  Produced by [`dev/dasm_tables.py`](../../dev/dasm_tables.py); back-link-exempt (generated) |
| [`src/dasm_mne_idx.s`](../../src/dasm_mne_idx.s) | generated, `.include`d by `dasm.s` — one block per CPU set: `MNE_UNK` (= 0), and only where the set needs them the decoder's switches `DASM_SUBSET`, `MNE_DIGIT_LO/HI` (on `MEGA_SUPPORT` also `MNE_QSFX_*`, `MNE_QNAME_*`).  Produced by [`dev/dasm_tables.py`](../../dev/dasm_tables.py); back-link-exempt (generated) |
| [`tests/unit/test_dasm.py`](../../tests/unit/test_dasm.py) | test contract |
| [`tests/unit/test_dasm_m65.py`](../../tests/unit/test_dasm_m65.py) | test contract — the m65 set on its bundle (M65Emu): every opcode at `asm_cpu` 0 / 2 / 3 / 4, every prefixed row at 4, no peel below, the asm → dasm → asm round trip |
| [`tests/integration/test_dasm_rom.py`](../../tests/integration/test_dasm_rom.py) | test contract — Tier I: `dasm_insn` reads the bytes of `$E000`+ through the caller's banking (KERNAL ROM at the REPL prompt) |

## Interface

### dasm_insn
**In:** A/X = instruction address (lo/hi).  `asm_cpu` (ZP) selects
the CPU view — one member of the build's CPU set
([build_system.md § Builds and CPU sets](../build_system.md#builds-and-cpu-sets)).
**Out:** A = instruction length (1–3 on C64 builds; 1–5 on the m65
build, prefixes included).  `dasm_buf` filled with
NUL-terminated PETSCII string.  `$01` as the caller had it.
**Clobbers:** A, X, Y, all `_dasm_*` ZP vars, `_dasm_in`

### dasm_buf
Exported BSS (24 B): the output text of the last `dasm_insn`.

### dasm_insn_pre
As `dasm_insn`, but the caller has already filled `_dasm_in` (3 B; 5 on m65)
with the instruction bytes and `_dasm_ptr` with their real address
(used for branch targets).  `repl.s::emit_dot` uses it for its
user-ZP staged view, whose bytes are not at the address shown.  It
is a label inside `dasm_insn`, so the decoder's layout is unchanged.

`dasm_insn` owns its own KERNAL banking: it banks out at entry,
calls the inner `dasm_decode` (which reads the generated tables
under KERNAL), and banks back in at every exit.  Callers —
currently `repl.s::emit_dot` (used by both the `d` block-disassemble
command and the `.` single-line command) — just call `dasm_insn` and
don't manage banking.

The wrapper structure is the same as `asm_line` in
`asm_line.s`: a thin entry that brackets the decoder with
`kernal_bank_out` / `kernal_bank_in`.  The decoder has a single
exit (`finish`), whose length result the wrapper preserves across
`kernal_bank_in` with `pha` / `pla`.  No exit can leave the KERNAL
mapped out by accident.

### Memory

**ZP (8 bytes):** `_dasm_ptr` (2), `_dasm_opc` (1), `_dasm_mne` (2), `_dasm_wptr` (1), `_dasm_midx` (1), `_dasm_mode` (1).

**BSS:** `dasm_buf` (24) — output buffer for the disassembled
instruction text (PETSCII + NUL); `_dasm_in` (3 on C64 builds, 5 on
the m65 build) — input snapshot of the maximum-length instruction read
from the user's address before banking out (see Caveats);
`_dasm_pfx` (1, `MEGA_SUPPORT` only) — the peeled prefixes: bit 0 Q,
bit 1 far, bit 2 a Q-map-2 form (its `ZPIZ` printed `($nn)`); the
length adds 2 for Q, 1 for far.

**No mutable bytes in CODE:** every scratch value lives in ZP or BSS
(the branch-target adjustment is folded into the arithmetic of
`_compute_branch_target`), so dasm.s runs unchanged from ROM
([memory_design.md § Design Principles](../memory_design.md#design-principles),
"No self-modifying code").

**Depends on:** dasm_tables (GENERATED — `dasm_mne_str`,
`dasm_mode_len`, `dasm_mode_fmt`, `dasm_cpu_map_lo/hi`; `dasm_cpu_bm`,
`dasm_view_bm` where `DASM_SUBSET`), dasm_mne_idx, mem
(`kernal_bank_out` / `kernal_bank_in`), zp (`asm_cpu`, `_dasm_*`).
`dasm_mne_idx.s` is `.include`d (generated constants), not linked.

## Design

**Opcode map.**  Every opcode fact comes from the generated tables;
the decoder holds none.  A **map block** (RODATA; KDATA on m65,
where the data window keeps the code window for code — both are
mapped whenever CSE runs) holds one CPU view:
256 B of mnemonic indexes (`MNE_UNK` = 0 where the CPU defines no
opcode), then the mode of every opcode — two 4-bit modes per byte
(even opcode in the low nibble) on C64 CPU sets, one byte per opcode
on the m65 set.  `dasm_cpu_map_lo/hi[asm_cpu]` point at the block of
that CPU's view, so decoding is a pointer load and two indexed loads:

```
block = dasm_cpu_map[asm_cpu]
mne   = block[op]
mode  = block[256 + op/2]  (nibble by op bit 0)
```

**Views.**  The generator takes the set's CPUs from the top down;
each either decodes as a subset of an existing map — every opcode it
defines decodes identically there — or gets a map of its own.  A
subset view is the **view bitmap** `dasm_view_bm` (32 B, one bit per
opcode) over its host map, flagged by `dasm_cpu_bm[asm_cpu]`; an
opcode whose bit is clear decodes as `MNE_UNK`, mode IMP, length 1.
A C64 set has at most one subset view, the m65 set two, one 32-byte
bitmap each, back to back in `dasm_view_bm`; `dasm_cpu_bm[asm_cpu]`
is 0 for a full view, else 1 + the bitmap's offset (1 and 33 on m65:
the 6502 and the 65C02).  Only a set with a subset view carries the
bitmaps, the flag table and the check (`DASM_SUBSET`).  On m65 the
map's modes are one byte per opcode (`DASM_BYTE_MODES`) and the Q map
is `dasm_q_map`.

| CPU set | Maps | Subset view |
|---|---|---|
| {6502} | 6502 | — |
| {6502, 6510} | 6510 | 6502, over the 6510 map |
| {6502, 6510, 65C02} | 65C02; 6510 | 6502, over the 65C02 map |
| {6502, 65C02, 4510, 45GS02} | 4510 | 6502 and 65C02, over the 4510 map |

The per-`asm_cpu` tables are padded to the platform's top `asm_cpu`
(3 entries on C64 sets, 5 on m65); a value outside the build's set
reads the top CPU's view.

The 45GS02 view is the 4510 map plus the prefix peel.  The 65C02 view
is a subset of the 4510 map but for the eight `(zp)` opcodes (`$12`
… `$F2`), which the 4510 decodes `ZPIZ`: the generator compares
`ZPI` and `ZPIZ` as one mode for that view, and the decoder lists
`ZPIZ` as `($nn)` in it — the 65C02's spelling of the same opcode.
The debugger's step follows the real 45GS02 whatever the view
([debugger.md § Next-PC](debugger.md#next-pc)).

**Mnemonic strings** (`dasm_mne_str`, KDATA).  3 chars packed into
2 bytes (5 bits per char, A=1..Z=26, 27=dot); `MNE_UNK` packs as
27,27,27 → `...`.  Only the names the set's maps use are stored.  The
generator orders the indices so that every decoration is a range
compare against a generated constant:

| Range | Holds | Display |
|---|---|---|
| `MNE_DIGIT_LO`..`MNE_DIGIT_HI` | `RMB` `SMB` `BBR` `BBS` | name + the opcode's bits 6:4 as a digit (`rmb3`) |
| `MNE_QSFX_LO`..`MNE_QSFX_HI` (`MEGA_SUPPORT`) | the Q suffix stems | under a Q prefix: name + `q` (`adcq`) |
| `MNE_QNAME_LO`..`MNE_QNAME_HI` (`MEGA_SUPPORT`) | `LDA` `STA` `ORA` `DEC` `INC`, each followed by its Q name | under a Q prefix: the string at index + 1 (`ldq`) |

**Listing name.**  Where several rows name one opcode (the 6510
aliases such as `SAX`/`AAX`; `NOP`/`EOM` on the 4510), the map holds the
name whose key comes last in the listing-name order: `OPCODES` order,
then `OPCODES_4510_ADDED` order (`dev/instruction_set.py`).  So the m65
CPU set lists `$EA` as `EOM` in every view (ruling D3).  The generator
applies the rule across the set's views before it compares them, so
the 6502 and 65C02 views — whose `$EA` is `NOP` by itself — stay
subsets of the 4510 map.

### Prefix peel

`MEGA_SUPPORT`.  With `asm_cpu` = 4 (45GS02), before the map lookup:

1. **Q:** bytes 0–1 are `$42 $42`, and byte 2 has a Q form in the
   **Q map** (2 bits per opcode, 64 B: 0 = no Q form, 1 = Q form,
   2 = Q form whose `ZPIZ` operand is written `($nn)`) — or byte 2 is
   `$EA` and byte 3 is far-capable with a Q form.  The Q prefix is 2
   bytes.
2. **Far:** the byte after any Q prefix is `$EA` and the next byte is
   far-capable: its mode in the map is `ZPIZ`.  The far prefix is 1
   byte.
3. The snapshot is shifted left by the prefix length, so the decoder
   sees the base opcode at `_dasm_in[0]`, and `_dasm_pfx` records the
   prefixes.

Otherwise `$42` is `NEG` and `$EA` is `EOM`, each one byte.  In the
4510, 65C02 and 6502 views no prefix is peeled.  Prefixes never precede a
branch, so `_dasm_ptr` (the instruction's own address) stays correct
for branch-target arithmetic.

**Length** is the prefix length plus `dasm_mode_len[mode]`.

**Mode formatting.**  `dasm_mode_fmt` (one byte per mode, generated
from `MODE_SHAPE` and `MODE_OPERAND_BYTES`) encodes prefix, operand
size and suffix: hi nybble 0 = none, 1 = `$`+8, 2 = `$`+16, 3 = `#$`+8,
4 = `($`+8, 5 = `($`+16, 6 = `a` (bare on m65: after a Q form `a`
would read back as a label), 7 = branch target (REL), 8 = ZPREL,
9 = `#$`+16 (IMM16), 10 = branch target (REL16); lo nybble 0 = none,
1 = `,x`, 2 = `,y`, 3 = `)`, 4 = `,x)`, 5 = `),y`, 6 = `),z`,
7 = `,sp),y`.  A far prefix prints `[` / `]` in place of `(` / `)`; a
Q-map value 2, and the 65C02 view, print `ZPIZ` as `($nn)`.

**Branch targets.**  REL: `PC + 2 + offset8`; ZPREL: `PC + 3 +
offset8`; REL16: `PC + 2 + offset16` (the address of the
instruction's last byte).

**Compile-time guards:** a build assembles only its CPU set's table
block (`.ifdef CPU_<top>`).  The decoder's optional paths are switched
by the generated constants, not by CPU defines: the subset check by
`DASM_SUBSET`, the digit decoration by `MNE_DIGIT_LO`; the prefix peel
and `_dasm_pfx` exist only on `MEGA_SUPPORT`.

## Caveats

- Output is PETSCII (not VICII screen codes).  Caller does
  `io_puts(dasm_buf)` to display.
- The disassembler has zero I/O dependency — pure computation.
- `dasm_buf` is 24 bytes: up to 4 (mnemonic) + 1 (space) + up to 10
  (operand, longest are `($XX,sp),y` and ZPREL `$XX,$XXXX`) + NUL +
  padding.
- **KERNAL ROM snapshot.**  `dasm_insn` snapshots the maximum
  instruction length (3 bytes; 5 on the m65 build) from the user's address into
  `_dasm_in` BEFORE banking out, using whatever bank state the caller
  had in force.  The decoder then reads opcode/operand bytes from
  `_dasm_in` via `lda _dasm_in,y` instead of `(_dasm_ptr),y`.
  `_dasm_ptr` itself stays at the user's actual address — used by
  `_compute_branch_target` for PC-relative branch destinations
  (`bcc $XXXX` / `bne $XXXX` / `BBR` / `BBS`).  Without the
  snapshot, disassembly of `$E000+` would read the RAM under
  KERNAL (mostly $00 → BRK).  See `tests/integration/test_dasm_rom.py`.
- Disassembly that starts inside a prefixed instruction decodes from
  that byte (the second `$42` lists as `NEG`), as on any byte stream.
