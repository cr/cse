# asm_line.s — Single-Line Instruction Assembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_line.s`](../../src/asm_line.s) | implementation — line assembler core, KERNAL banking, error recovery |
| [`tests/unit/test_asm_line.py`](../../tests/unit/test_asm_line.py) | test contract |
| [`tests/unit/test_asm_m65.py`](../../tests/unit/test_asm_m65.py) | test contract — the m65 set on its bundle (M65Emu): every row of the three views at its CPU, the m65 gate matrix, the word, the Z rule, far, stack-relative, IMM16, branch width and the width request, the `$FFFF` edge |
| [`tests/emulator/test_m65_asm_run.py`](../../tests/emulator/test_m65_asm_run.py) | tier-X tests (xmega65, P4): a program typed with `.` (`PHW #`, Q, far, a 16-bit branch) and run with `j` stores the predicted bytes, each screen M65Emu's |

Its ZP definitions are in [`src/zp.s`](../../src/zp.s), owned by
[zp.md](zp.md).

Statements marked `MEGA_SUPPORT` describe the m65-45gs02 build.

## Interface

### asm_line (public entry point)
**In:** A/X = text pointer (lo/hi, PETSCII, NUL-terminated);
`asm_pc` (ZP, address of the instruction — the base of branch
offsets), `asm_out` (ZP, where the bytes go), `asm_cpu` (ZP, CPU
mode — the global enumeration of
[build_system.md § Builds and CPU sets](../build_system.md#builds-and-cpu-sets)).
**Out (success):** A = byte count (1–3 on the C64 builds; 1–5 on the
m65 build, prefixes included), X = 0; the bytes at `[asm_out]`;
`asm_out` advanced past them; `asm_len` = byte count.
**Out (error):** A = 0, X = 0, `asm_err_code` = the category
([asm_err.md § Error categories](asm_err.md#error-categories)); for
an expression error `last_err` (expr.s) holds the detail code.
**Clobbers:** A, X, Y; `asm_ptr` (advanced), `asm_opr`,
`asm_base`, `asm_prof`, `asm_pidx`, `asm_mode`, `asm_tmp`,
`mn_c1`–`mn_c3`, `_asm_saved_sp`, `_au_no_acc`, and everything
`mode_parse` and `expr_eval_nb` clobber
([addr_mode.md](addr_mode.md), [expr.md](expr.md)).

**m65:** `asm_out` is a far pointer and may hold
a flat address in any bank; `asm_pc` stays the 16-bit address the
code will run at.  At a flat REPL address `.` sets `asm_out` to the
flat address and `asm_pc` to its low word, so a branch's offset is
computed for the code where a far start runs it
([repl.md § Banks](repl.md#banks-m65)).  asm_line itself does not
change.

`asm_line` saves the 6502 SP in `_asm_saved_sp` (the unwind point of
[asm_err.md](asm_err.md)), banks the KERNAL out, `ldy #0`, calls
`_asm_line_core`, refuses a wrapped output (below), banks the KERNAL
back in and returns the byte count.

**Output never wraps.**  An instruction whose bytes would run past
`$FFFF` is refused: `last_err` = 3 and `asm_expr_error` (the REPL
shows `;?expr ovfl`), and nothing is written at `$0000`/`$0001` (the
CPU port).  `_asm_emit` parks any byte after the wrap in
`_asm_sink` (3 bytes; 4 on `MEGA_SUPPORT`, where an instruction is up
to 5 bytes); `asm_line` refuses when one landed there.  An
instruction whose last byte is at `$FFFF` is accepted.  The source
assembler never reaches this check — it assembles into a scratch
buffer and places the bytes itself
([asm_src.md § `_emit_byte`](asm_src.md#_emit_byte)).

`asm_line` is the **single shared entry point** for both the
source pass and the line-asm REPL command:

| Caller | Path |
|--------|------|
| `asm_src.s::process_line` | inside `asm_assemble`'s batched bank-out (`kernal_out=1`) — `asm_line`'s bank helpers are no-ops; `asm_out` points at the scratch `_insn_out` |
| `repl.s::dot_assemble` | single-line REPL `.` command — `asm_line`'s bank helpers do the actual KERNAL bank-out for the KDATA-table reads; `asm_out` is the target address |

`asm_line` owns its KERNAL banking (a `kernal_bank_out` /
`kernal_bank_in` bracket around the `_asm_line_core` call).  Callers do
not — and must not — bank the KERNAL themselves.  The error-unwind
path (`asm_error` / `asm_syntax_error` / `asm_expr_error` /
`asm_cpu_error`, in [asm_err.md](asm_err.md)) also banks the KERNAL
back in before returning 0, so success and error exits are symmetric.
The entry points encode three categories into `asm_err_code` so
callers can pick the right user-visible tag — see
[asm_err.md § Error categories](asm_err.md#error-categories).

Input is PETSCII.  Each of the three key characters must be a letter
— `$41`–`$5A`, `$61`–`$7A` or shifted `$C1`–`$DA` (the fold `AND #$5F`
also maps `$E1`–`$FA` onto the letters) — and is normalized to 1–26
for the classifier ([mn_classify.md](mn_classify.md)).  Any other
character there (a digit, punctuation, NUL — so also an empty line) is
`;?syntax` before the hash runs, so the classifier's 27-entry tables
are never indexed out of range and no non-letter key can collide with
a mnemonic.  Leading spaces ($20 only) before the key are skipped.

### _asm_line_core
The assembler body without the banking and SP bracket; exported for
the unit-test bundles, which call it directly.
**In:** `asm_ptr` (ZP, text pointer), `asm_pc`, `asm_out`, `asm_cpu`
as for `asm_line`; KERNAL banked out (the classifier and opcode tables
are KDATA).  It sets Y = 0 itself.
**Out:** bytes written to `[asm_out]`, `asm_len` = byte count, C = 0.
On an error it jumps to an `asm_err.s` entry point, which unwinds to
the SP saved in `_asm_saved_sp` — a direct caller must set it.
**Clobbers:** as `asm_line`, except `_asm_saved_sp`.

### reg_a, reg_x, reg_y, reg_sp, reg_p
BSS bytes exported for the debugger: the user's saved registers,
written by debugger.s / main.s on BRK and NMI entry, shown and edited
by repl.s (`r`), and reloaded by debugger.s before user code resumes.
They live here so debugger.s and repl.s share them without a
back-edge; their meaning is owned by [debugger.md](debugger.md).

### Mnemonic word

The mnemonic is one word: a three-letter **key** and an optional
one-character **suffix** directly after it.

| Suffix | Builds | Meaning |
|---|---|---|
| digit `0`–`7` | the 65C02 and 4510 sets (the CMOS mode, m65-45gs02) | the bit number of a digit-zone key (`RMB` `SMB` `BBR` `BBS`), ORed into the opcode's bits 6:4 |
| `q` | `MEGA_SUPPORT` | the Q form of a quad stem ([§ Prefixes](#prefixes-45gs02)) |

The character after the word must be whitespace ($20 or $A0), the
end of the line or `;`.  A digit on any other key, a digit-zone key
without a digit, `q` on a key with no Q form, any other fourth
character, or a fifth character is `;?syntax` — `inxy`, `lda4`,
`nopx`.  On a build without the digit zones (c64-6502, c64-6510)
`rmb0` is `;?syntax`: `RMB` is no key of its set.  `lda
x` is `LDA` with the label `x`; `ldax` is no word.

**Accepted spellings on the m65 build** (`MEGA_SUPPORT`) — a second
spelling is accepted only when the scanner alone can map it onto an
existing row (it adds no row and no table fact):

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

**ZP:** none of its own.  It writes the shared assembler ZP of
[zp.md](zp.md) (`asm_*`, `mn_c1`–`mn_c3`, `_asm_saved_sp`); the
error-category byte `asm_err_code` is BSS of asm_err.s.  `asm_tmp`
holds the digit suffix from the word scan to zone D / E (`bit << 4 |
1`, 0 for none — bit 0 is set in every digit-zone opcode, so the
`ora` keeps it); zone E saves the opcode before the branch-offset
helper (`_asm_rel8` on the C64 builds, `_asm_reld` on m65; zones B
and E) reuses `asm_tmp` as scratch.  ZPREL's zero-page byte comes in `asm_tmp2`
([addr_mode.md](addr_mode.md)).

**BSS (8 bytes; 13 on m65):**

| Variable | Size | Purpose |
|----------|------|---------|
| `reg_a` | 1 | user A register (exported, see above) |
| `reg_x` | 1 | user X register |
| `reg_y` | 1 | user Y register |
| `reg_sp` | 1 | user stack pointer |
| `reg_p` | 1 | user status flags |
| `reg_z`, `reg_b` | 1 each (m65 only) | user Z and B registers |
| `_asm_sink` | 3 (4 on `MEGA_SUPPORT`) | bytes emitted past a `$FFFF` wrap land here (refused) |

**BSS (`MEGA_SUPPORT`, 2 bytes):** `asm_pfx` — the instruction's
prefixes: bit 0 Q (`$42 $42`), bit 1 far (`$EA`), bit 6 the word's `q`
suffix, bit 7 the width request; `asm_rel16` (exported) — the
caller's width request for a branch, `$80`
([§ Branches](#branches-zone-b)): `_asm_line_core` moves it into
`asm_pfx` bit 7 and clears it first thing, so no exit — the error
unwind included — leaves it set.

**Depends on:** expr (`last_err`, `expr_fwd`), addr_mode (`mode_parse`,
`asm_skip_ws`, `_au_no_acc`; `_au_far` on `MEGA_SUPPORT`),
opcode_lookup (`asm_opcode_lookup`), mn_asm_tables (`asm_oplen`,
`ASM_ZONE_G`, `ASM_ZONE_D`; on m65 `ASM_ZONE_Q`, `ASM_ZONE_H`),
mn_classify (`mn_classify`, `mn_base_op`, `mn_profile`), mn_modes (`mn_modes_lo` — the ACC-bit test that sets
`_au_no_acc`), asm_err (`asm_error`, `asm_expr_error`,
`asm_cpu_error`), mem
(`kernal_bank_out` / `kernal_bank_in`), zp (`_asm_saved_sp`,
`asm_pc`, `asm_out`, `asm_len`, `asm_cpu`, `asm_prof`,
`asm_pidx`, `asm_base`, `asm_mode`, `asm_tmp`, `asm_tmp2`, `asm_ptr`, `asm_opr`,
`mn_c1`–`mn_c3`); `.include`s `cpu_set.inc` (`MODE_*`, `ASM_CPU_*`,
the set's `SET_EXT`, `HAS_ZONE_C`, `HAS_ZONE_D` —
[opcode_lookup.md § Owned files](opcode_lookup.md#owned-files)).

## Build-time variants

Four variants — two C64 builds, the CMOS mode (bundles only) and the
m65 build (see
[build_system.md § Builds and CPU sets](../build_system.md#builds-and-cpu-sets)).
Each instantiates this module with different `-D` flags, and the
generated `cpu_set.inc` derives the set's switches from them: the
classifier, the gate and the zones compiled in depend on the set — so
the module ships as distinct binaries, each with its own contract.

| Variant | Feature `-D` flags | Classifier | Gate (`SET_EXT`: extension / `cat` 11) | Illegal gate | Zones (`HAS_ZONE_C/D`) | Accepts |
|---|---|---|---|---|---|---|
| **c64-6502** | `CPU_6502` `USE_MN6` | mn6 (56 legal only) | — (not compiled) | — (not compiled) | A B F | legal NMOS |
| **c64-6510** | `CPU_6510` | mn7 (102: legal + illegal) | — (not compiled) | **compiled in** | A B F C | legal + illegals |
| **the CMOS mode** (bundles only) | `CPU_65C02` `CMOS_SUPPORT` | mn7 (68: legal + CMOS) | compiled in | — (not compiled) | A B F C D E | legal + CMOS |
| **m65-45gs02** | `CPU_45GS02` `MEGA_SUPPORT` | mn7gs, m65 keys (98) | compiled in, with the Q names | — | A B F C D E, Q, H | legal + 4510 (the 65C02's instructions among them); Q and far forms at `asm_cpu=4` |

Every build also passes `DEFAULT_CPU`, `CPU_CEIL` and `TAB_WIDTH`
(Makefile `_<cpu>_DEFS`); asm_line reads none of them.

A set's classifier accepts every key of the set (56 on c64-6502, 102
on c64-6510, 68 in the CMOS mode, 98 on m65) and no other, so the
gate sees only the set's own categories and only the gate the set
needs is compiled: none on c64-6502 (every key is `cat` 00), the
illegal gate on c64-6510, the extension gate (`SET_EXT`) in the CMOS
mode and on m65.  The gate is the sole defence against the user
asking for an instruction of a set member the current `asm_cpu` is
not.

Bundle-test parity: each variant — the CMOS mode's too — has a matching unit-test
bundle in [conftest.py](../../tests/conftest.py) (`AsmCoreSymbols(config=…)`)
and a test class in [test_asm_line.py](../../tests/unit/test_asm_line.py)
(`TestCpuGateCmosBundle`, `TestCpuGate6510Bundle`, `TestAsmLine6502Bundle`);
the m65 variant's tests are [test_asm_m65.py](../../tests/unit/test_asm_m65.py).
See [testing.md § Principle 10](../testing.md).

## asm_cpu × category gate matrix

Every mnemonic's `asm_prof` byte encodes a 2-bit category in bits
7:6.  The CPU-mode gate in `_asm_line_core` implements the table
below.  Reject cells `jmp asm_cpu_error` (so the caller selects the
`;?cpu` tag rather than the strictly-correct-but-misleading
`;?syntax`); accept cells fall through with the appropriate profile
(upgraded to the extension profile — `pidx` + 1 — when `cat=01` and
`asm_cpu` is not the 6502, in a set with `SET_EXT`).  A category no key of the set
has cannot occur (—): the C64 sets have no CMOS key, the CMOS mode no
illegal one.

| | `cat=00` legal NMOS | `cat=01` legal + CMOS-ext | `cat=10` illegal NMOS | `cat=11` pure CMOS |
|---|---|---|---|---|
| `asm_cpu=0` (6502), every C64 set | accept | accept (NMOS profile; the CMOS mode) | **REJECT** (c64-6510) | **REJECT** (the CMOS mode) |
| `asm_cpu=1` (6510), c64-6510 | accept | — | accept | — |
| `asm_cpu=2` (65C02), the CMOS mode | accept | accept (CMOS profile) | — | accept |

**m65 build** (`MEGA_SUPPORT`, `asm_cpu` ∈ {0, 3, 4}):

| | `cat=00` legal NMOS | `cat=01` legal + extension | `cat=10` Q name | `cat=11` not NMOS |
|---|---|---|---|---|
| `asm_cpu=0` (6502)   | accept | accept (NMOS profile) | **REJECT** | **REJECT** |
| `asm_cpu=3` (4510)   | accept | accept (extension profile) | **REJECT** | accept |
| `asm_cpu=4` (45GS02) | accept | accept (extension profile) | accept (Q, `pidx` is the Q profile) | accept |

The **effective profile** is `pidx` after the extension upgrade.  The
`q` suffix is accepted iff `asm_cpu=4`, `cat≠10`, and the effective
profile lies in zone Q ([opcode_lookup.md § Profile index layout](opcode_lookup.md#design));
the Q profile is then effective + 1.  Otherwise `q` is `;?cpu` on
`asm_cpu` 0/3 for a quad stem, `;?syntax` for any other key.

Every cell of the C64 sets and the CMOS mode is tested per variant
bundle in `TestCpuGateCmosBundle` and `TestCpuGate6510Bundle`
(test_asm_line.py), the m65 cells in test_asm_m65.py.

## Design

**Zone dispatch:** The effective profile's zone
([opcode_lookup.md § Profile index layout](opcode_lookup.md#design))
determines which path assembles the instruction.  A `pidx` below the
generated `ASM_ZONE_G` is a fixed zone and indexes the jump table
directly (order A B F C D E, the table holding only the zones the set
has — `HAS_ZONE_C`, `HAS_ZONE_D`; on m65 zone B is three profiles,
`pidx` 1–3 — `REL`, `REL` + `REL16`, `REL16` — and the table holds
zone B three times); the rest is multi-mode:

| Zone | Mode | Examples |
|------|------|---------|
| A | Implied — the operand must be empty (end of line, `;` or `//` comment), else `;?syntax` | BRK, CLC, DEX, NOP, RTS; on m65 also TAZ, MAP, EOM, … |
| B | Branch (REL; REL16 on `MEGA_SUPPORT`, where zone B is a range of profiles: `REL`, `REL` + `REL16`, `REL16` only) | BCC, BEQ, BNE, BPL, …; on m65 also BRA, BSR |
| C | Immediate only | illegal ANC/ALR/…; on m65 RTN |
| D | Bit-op ZP (RMB/SMB): the digit suffix is the bit | RMB0–7, SMB0–7 |
| E | Bit-op ZP,REL (BBR/BBS): the digit is the bit, then a branch target as zone B (`REL` only) | BBR0–7, BBS0–7 |
| F | Absolute only | JSR (C64); ASW, ROW (m65) |
| G | Multi-mode extension pairs | DEC, INC, BIT, JMP, LDA, …; JSR on m65 |
| Q | Multi-mode quad groups (`MEGA_SUPPORT`) | LDA/LDQ, ADC/ADCQ, ASL/ASLQ, … |
| H | Multi-mode, the rest | LDX, STX, CPX, CPY, … |

Zones A–F handle fixed single-shape instructions inline.  Zones G, Q
and H call `mode_parse` to determine the addressing mode, then
`asm_opcode_lookup`, which rejects a mode the profile does not accept
(→ `asm_error`, `;?syntax`) and otherwise returns the opcode byte;
the operand byte count is the generated `asm_oplen[mode]`.

### Branches (zone B)

The operand is the target address; the offset is computed — for a
narrow operand too: `bne $10` branches to `$0010` (out of reach
anywhere but page zero), it is not a raw offset byte.  For `REL`
the offset is `target − (asm_pc + 2)`, valid in −128..127; out of
reach is `asm_error` (`;?syntax`).  On `MEGA_SUPPORT` a profile may
also (or only) accept `REL16`, a 16-bit offset `target − (asm_pc + 2)`
(the address of the instruction's last byte).  Width: a **forward**
target — `expr_fwd` set: the target expression reads a symbol not yet
defined in the current pass
([symtab.md § Pass stamp](symtab.md#pass-stamp)) — takes `REL` where
the profile has it; otherwise `REL` if the profile has it and the
target is in reach, else `REL16` if the profile has it, else out of
range (`;?syntax`).  Both passes see the same forward/backward split,
so the width — and every later address — is pass-stable.  A forward
`REL` whose target is out of reach on pass 1 is an error; the source
then needs a backward target or a `jmp`.

On m65 zone B computes `d = target − (asm_pc + 2)` once, 16 bits:
`REL`'s offset when it fits a byte, `REL16`'s in any case, probing
the profile for each mode through `asm_opcode_lookup`.

**Width request** (`MEGA_SUPPORT`): `asm_rel16` set by the caller
makes a profile that has `REL16` take it whatever the distance.  The
REPL's `.` sets it when the bytes it re-assembles over are a 16-bit
branch ([repl.md § The `.` command in detail](repl.md#the--command-in-detail)),
so a `d` row re-entered unchanged keeps its width — `REL16` lists
like `REL`.  `_asm_line_core` clears it on entry (BSS above), so it
applies to one instruction; the source assembler never sets it.

### Immediate range

An `IMM` operand must fit a byte: `$00`–`$FF`, or a negative value
−128..−1 (`#-1` is `$FF`).  Anything else — `lda #$1234`, `lda #-129`,
`lda #label` for a label above page zero — is refused as an expression
overflow (`last_err` = 3, `asm_expr_error`: `;?expr ovfl`, in a source
`;?N: ovfl`) instead of being truncated to its low byte.  A wide
literal that fits (`#$0012`) is fine.  Not checked for an operand that
read an undefined symbol (`expr_fwd` bit 7 — pass 0 only sizes it); on
an IMM16 profile (`MEGA_SUPPORT`) the full word is emitted instead.
`_asm_imm_chk` runs in zone C and in zones G/H.

### IMM16 promotion (`MEGA_SUPPORT`)

`mode_parse` returns IMM for every `#expr`.  On a profile that accepts
IMM16 and not IMM (`PHW`), asm_line promotes IMM to IMM16 and emits
both operand bytes; elsewhere IMM stays IMM and emits the low byte, as
on the C64 builds.  Same shape as the IMP → ACC promotion.

### Prefixes (45GS02)

`MEGA_SUPPORT`.  The 45GS02's Q and far forms are modifiers on a 4510
row, not opcodes.  A Q form (the `q` suffix or a `cat=10` key) emits
`$42 $42`; a far operand (`[e]`, `[e],z` — flagged by mode_parse) emits
`$EA`.  Far is valid exactly where the effective profile accepts the
parsed zero-page-indirect mode (`ZPI` or `ZPIZ`), so the mask test that
admits `(e)` / `(e),z` admits `[e]` / `[e],z`.  Emission order:
`$42 $42` if Q, `$EA` if far, the opcode, `asm_oplen[mode]` operand
bytes.  Both prefixes exist only at `asm_cpu=4`: on 0 and 3 a Q form or
a far operand is `;?cpu`.

### ACC mode handling

Six mnemonics accept the accumulator addressing mode: ASL, LSR, ROL,
ROR (always); INC, DEC (the CMOS mode and the 4510).  Each maps to an operand profile
whose mode set includes ACC (`{ACC, ZP, ABS, ZPX, ABX}`; the profile's
index differs per CPU set — the generator numbers them).  Both
syntactic forms produce the ACC opcode:

- **Bare** (`ASL`) — mode_parse returns MODE_IMP for an empty operand;
  asm_line's zone G/H path promotes IMP → ACC when
  `mn_modes_lo[asm_pidx]` has the ACC bit set.  Profiles that don't
  accept ACC keep MODE_IMP, which `asm_opcode_lookup` then rejects
  (`;?syntax`).
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
single-letter symbol `A` instead of failing with `;?syntax`.

On m65 a Q form (the `q` suffix or a Q name) sets `_au_no_acc` too —
after a Q form `a` is a label — and the bare promotion does not read
it: IMP always becomes ACC in zones G / Q / H, since no multi-mode
profile takes IMP, so `asm_opcode_lookup` judges (`aslq` is the Q
accumulator, `aslq a` the label `a`).

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

asm_line itself jumps to three of them: `asm_error` for a non-letter
key, a bad word end, an unknown mnemonic (classifier miss), a
non-empty implied operand, a wrong mode for a fixed zone, a branch out
of reach, and a mode `asm_opcode_lookup` rejects; `asm_expr_error` for
an immediate out of range and an output wrap past `$FFFF`;
`asm_cpu_error` for the CPU-gate reject paths.  mode_parse reaches
`asm_syntax_error` and `asm_expr_error` on its own
([addr_mode.md](addr_mode.md)).

## Caveats

- Input is PETSCII (letters $41–$5A, $61–$7A, $C1–$DA — and $E1–$FA,
  which `AND #$5F` folds onto them — in the key).  `_asm_rd_upper`
  refuses anything else.
- `asm_cpu` values: 0=6502, 1=6510, 2=65C02, 3=4510, 4=45GS02 (one
  global enumeration).  The C64 / CMOS gate's compares are compiled
  only into the C64 builds and the CMOS mode, the m65 gate's (4510,
  45GS02) only into the m65 build, so each build compares within its
  own CPU set.
- `mn7_classify` clobbers Y (sets Y=mn_c2).  `ldy #0` is required
  before zone dispatch.
- `_asm_emit` clobbers A and Y and preserves X and C.
