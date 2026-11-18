# CSE — TODO

## Corpus status snapshot — 2026-04-20 handover

> *Historical reference point captured at the end of the L0–L5 TDD-
> compliance milestone.  Not refreshed; later phases (21 BSS migration,
> 22 debugger workflow, 23 CDD Streamlining) have moved the corpus on.
> Newer phase summaries live in the auto-memory under
> `project_phase*_complete.md`.*


**Full TDD compliance across L0–L5.**  3138 tests passing, 18 vocal
skips, 0 failures.  Every behavioural module's documented contract
is exercised at its prescribed tier:

- **L0** (zp, strings, *_tables, mn_config, oplen_tbl, mn_vars):
  axiomatic per testing.md § Principle 12 — no unit tests, covered
  transitively by every bundled test that links them.
- **L1–L3** (15 modules): every export covered at Tier U.  Includes
  the two new L3 extractions from this session: `breakpoints.s`
  (bundle-tested at L3, was formerly debugger-internal) and
  `gap_buffer.s` (bundle-tested at L3, was formerly editor-internal).
- **L4** (asm_src, editor, disk, debugger): every export covered at
  its correct tier — `asm_src` at U via the asm_core bundle, the
  other three at I via C64Emu.
- **L5** (main, repl): comprehensive C64Emu command-loop coverage at I.
- **L6** (loader): implicit via every integration test's load path,
  acceptable per testing.md's Tier I definition.

**Process ratchets added this session** (CDD System amendments):

- testing.md Principle 10: test bundles mirror production build configs.
- testing.md Principle 11: contract matrices drive test matrices.
- testing.md Principle 12: axiomatic modules need no unit tests.
- testing.md Principle 13: partial-result contracts need position-
  pinning tests (direct or transitive via hot-loop composition).
- README.md § Escape Analysis step 5: two-axis sweep — class-wide
  AND cross-module handoff — on every escape.
- README.md § TDD Maintenance item 11: periodic audit of Principle 13
  compliance + dead-code-sweep gotcha (grep direct calls + `.import`
  references + test-harness lookups before retiring).
- Glossary: solitary / sociable / bundled unit testing, axiomatic
  module / behavioural module, partial-mode function.

**Escape Analyses resolved this session** (5 total): asm_cpu gate on
6510 build, `? 1x` trailing garbage, `. .` silent BRK, log enter-
anywhere under-testing, prompt-row overwrite from the log contract's
cross-module handoff regression.  Class closure applied for the `?`
garbage-trailing pattern across `@` / `B` / `C` / `j` via the shared
`_require_eoi_or_err` helper.  Plus a latent `ed_insert_string`
save_ptr clobber caught by the L3 TDD sweep.

**Structural refactors** (two module extractions): `breakpoints.s`
split from debugger.s, `gap_buffer.s` split from editor.s.  Both
were pure re-layering — zero behavioural change — to convert the
tier boundary from a disciplined convention into a compile-time fact
enforced by the linker.  L3 grew from 5 to 7 modules as a result.

**Remaining open (not blocking):** one TDD follow-up —
class-wide trailing-garbage closure for `+` / `-` — deferred because
their `expr_or_blocksize` fallback creates a double-error-on-undef
risk that needs a design pass.  See the Escape Analysis follow-up
entry below.  Everything else in this file is feature work, not
TDD.

## M65 — the 45GS02 assembler and disassembler (R7, slice 1)

**Branch:** `m65` (cut from `main` @ 910d96d, 2026-11-16).
**Goal:** the m65 platform's CPU layer — line assembler, source
assembler and disassembler for the 45GS02, with the 4510 and the
6502 as runtime alternatives — built from the one instruction set
that serves every build.  The rest of R7 (screen driver, memory
model, KERNAL interface, debugger) is not this slice: it is
[slice 2](#m65-slice-2--the-mega65-prg-r7-platform-layer), which
turns the m65 build into the MEGA65 PRG.

**Hard constraint (operator, 2026-11-16):** no change made for the
m65 target may make any C64 build bigger or significantly slower.
Tables grow only where the platform is m65.

**Rationale — one source, one format, sized per build.**
`dev/instruction_set.py` is the single source of every opcode fact
for every build (operator ruling, 2026-11-16).  Today two consumers
re-state facts in hand-written code: `opcode_lookup.s` (five
exception steps, the `dir` bit, the zone-3 `ABY` conflict) and the
bit-slice decoder in `dasm.s` (`g1_mne`/`g1_mode`, the per-CPU
exception chains, `mode_len`, `dasm_mode_fmt`), plus `asm_line.s`'s
`_asm_oplen`.  A 4510 extension of either would add more of the
same — the 4510 defines all 256 opcodes and four new modes.  So both
move to a table format the generator derives completely, and every
build gets that format sized to its own CPU set:

- **Assembler — profile rows** (the design bbbc64 locked for cse to
  adopt — bbbc64 repository, `doc/asm.md` § Line assembler):
  `opcode = base ^ asm_delta[asm_row[pidx] + mode]` behind the
  existing mode-mask test.  Replaces `opcode_lookup.s`'s dispatch,
  `mode_offset` and `direct_opcodes`.
- **Disassembler — opcode map**: per opcode a mnemonic index and a
  mode, a 256-bit view bitmap per subset CPU view, generated mode
  lengths and formats.  Replaces the bit-slice group decoders; the
  operand formatter stays.
- **45GS02 prefixes** (`$42 $42` Q, `$EA` far) are modifiers on
  4510 single-byte rows, never opcodes: the assembler emits them in
  front of the looked-up opcode, the disassembler peels them before
  the map lookup.  Instruction length becomes 1–5 on the m65 build.

**Model for the m65 set (2026-11-16, `instruction_set.py` via exact
row colouring, 20 modes; not yet built):** 36 profiles, 7 delta rows,
≈ 284 B of masks + rows + index.  The C64 sets are built — see
*Measured* below.

**Baseline (measured 2026-11-16, fresh `make release` at 910d96d +
uncommitted docs; ca65 + `od65`, CODE+RODATA+KDATA bytes):**

| Build | PRG (unpacked) | asm_line | opcode_lookup + mn_asm_tables + mn_modes | dasm + dasm_tables | oplen_tbl | classifier + tables | addr_mode |
|---|---|---|---|---|---|---|---|
| c64-6502 | 20 790 | 394 | 224 + 80 + 60 = 364 | 1084 + 230 = 1314 | 64 | mn6 104 + 192 | 543 |
| c64-6510 | 21 232 | 394 | 364 | 1348 + 230 = 1578 | 64 | mn7 63 + 384 | 543 |
| c64-65c02 | 21 688 | 408 | 364 | 1731 + 230 = 1961 | 64 | mn7 63 + 384 | 543 |

**Measured after the assembler slice (release builds, 2026-11-16):**

| Build | PRG | Profiles × rows × row width | opcode_lookup + mn_asm_tables + mn_modes | asm sweep cycles |
|---|---|---|---|---|
| c64-6502 | 20 549 (−241) | 14 × 3 × 13 | 48 + 66 + 28 = 142 (was 364) | −4.6 % |
| c64-6510 | 21 028 (−204) | 22 × 4 × 13 | 48 + 87 + 44 = 179 | −4.3 % |
| c64-65c02 | 21 555 (−133) | 30 × 6 × 16 | 48 + 142 + 60 = 250 | −4.4 % |

Worst single case +0.5 %; all 6912 asm golden cases identical.  The
disassembler (A4) followed: see A4 below.

**Acceptance gates (Phase A, per C64 build):**

1. **Size:** the unpacked PRG is no larger than its budget — the
   baseline above, ratcheted down whenever a commit shrinks a build
   (`tests/integration/test_size_budget.py`).
2. **Speed:** over the exhaustive sweeps (every instruction-set row
   through `asm_line`; every opcode × every `asm_cpu` of the build
   through `dasm_insn`), total py65 cycles ≤ baseline, and no single
   case more than 10 % above its baseline.
3. **Behaviour:** both sweeps match the oracle derived from
   `instruction_set.py`, and are byte-identical to the baseline
   build's output except where the baseline disagrees with the
   oracle; each such case is a baseline defect, listed in the Phase A
   report and filed under Bugs.

### Phase A — C64 builds move to the generated formats (no behaviour change)

- [x] ~~A0. Sync the four shared generator files from bbbc64
  (`instruction_set.py`, `hashes.py`, `mnemonic_tables.py`,
  `dasm_tables.py`).  Verified 2026-11-16: bbbc64's copies regenerate
  cse's seven tables byte-identically.~~  (Done 2026-11-16: synced; tables
  unchanged; suite 3139 passed / 18 skipped.)
- [x] ~~A0b. **Before any code change:** dasm bundles for c64-6502 and
  c64-6510 (today only the 65c02 variant is built); test oracles
  rewritten over `instruction_set.instructions(variant)` (no
  hand-coded `CMOS_ADDITIONS`); golden files recorded from the current
  code — every instruction-set row through `asm_line`, every opcode ×
  `asm_cpu` through `dasm_insn`, per C64 variant, with py65 cycle
  counts ([testing.md § Principle 7](testing.md#principles)).~~  (Done
  2026-11-16: `dasm_bundle(config)` for 6502/6510/cmos with `PROD_DEFS`;
  `asm_core` on `PROD_DEFS`; `tests/asm_dasm_runner.py`,
  `dev/capture_golden.py`, `tests/fixtures/golden/` — 1536 dasm + 6912
  asm cases.  The oracle surfaced the listing-name rule for aliases,
  now in [dasm.md § Design](modules/dasm.md#design).)
- [x] ~~A0c. Gate tooling: a size-budget test (each C64 release PRG ≤ its
  baseline) and a `dev/` benchmark comparing cycles to the golden
  files.~~  (Done 2026-11-16 as tests: `test_size_budget.py` (gate 1),
  `test_golden_asm_dasm.py` (gates 2–3), `test_build_parity.py`.)
- [x] ~~A1. Generator: per-CPU-set table blocks
  ([build_system.md § Table generation](build_system.md#table-generation));
  the profile-row model moved into the shared `mnemonic_tables.py`
  with ca65 output; `_asm_oplen` generated.~~  (Done 2026-11-16:
  `build_asm_model` + derive-or-die `validate_asm_model`; `mn_modes`,
  `mn_asm_tables`, `mn6/7_tables` (hash `T` moved in) and `oplen_tbl`
  in per-CPU-set blocks; `tests/unit/test_mnemonic_tables.py`.)
- [x] ~~A1d. The disassembler's tables in `dasm_tables.py`: opcode map,
  mode map, view bitmaps, mode lengths and formats.~~  (Done
  2026-11-16 with A4; `make tables` now runs both generators.)
- [x] ~~A1b. Feature define `ILLEGAL_SUPPORT` replacing the
  `.ifndef CPU_6502` gate on 6510 illegal paths.~~  (Closed as
  unneeded, 2026-11-16: the gate's only user was the bit-slice
  `dasm.s`; the opcode-map decoder has no 6510-specific path — the
  illegal opcodes are rows of the 6510 sets' tables — so no build
  defines it.)
- [x] ~~A2. Profile byte: `cat` (2) + `pidx` (6), no `dir` bit
  ([mn_classify.md](modules/mn_classify.md)).~~  (Done 2026-11-16.)
- [x] ~~A3. `opcode_lookup.s` → profile-row lookup
  ([opcode_lookup.md](modules/opcode_lookup.md)); it needs no ZP, so
  `_asm_ok_tmp` is removed and `$2C` is left unallocated
  ([zp.md](modules/zp.md)).~~  (Done 2026-11-16.  Measured, release
  builds: PRG 20 790 → 20 579 / 21 232 → 21 058 / 21 688 → 21 573 B;
  opcode machinery 364 → 169 / 206 / 265 B; asm sweep cycles −3.5 /
  −3.2 / −3.4 %, worst single case +0.5 %; golden behaviour identical.
  A review pass the same day removed the empty and duplicate profiles,
  trimmed the row width, merged validate into `asm_opcode_lookup`,
  wired `ASM_ZONE_G`, and fixed the sharing rule that would have put
  the 4510's `DEW`/`INW` into zone D — figures under *Measured* above.)
- [ ] A3b. *(follow-up, own CDD cycle)* Recompact ZP over the freed
  `$2C`: every later allocation moves down one byte and the user ZP
  becomes `$77–$7F` (9 bytes) — a userland-contract change
  ([userland_contract.md](userland_contract.md)), so not bundled.
- [x] ~~A4. `dasm.s` → opcode-map decoder ([dasm.md](modules/dasm.md)).~~
  (Done 2026-11-16.  Map blocks in RODATA, the set's own mnemonic
  strings in KDATA.  Measured, release builds: PRG 20 549 → 20 220 /
  21 028 → 20 563 / 21 555 → 21 144 B; dasm + dasm_tables 1314 → 985 /
  1578 → 1113 / 1961 → 1550 B; dasm sweep cycles −3.8 / −7.5 / −4.7 %,
  worst single case +5.7 % (an unknown opcode, which the bit-slice
  short-circuited); all 1536 dasm golden cases identical.)
- [ ] A5. Gates 1–3 measured and recorded here; asm → dasm → asm
  round trip over every row; generator tests (placement rules refuse
  violating input, minimal row count, no foreign entries per block).

### Phase B — the m65 build (m65-45gs02)

- [ ] B1. Build defines `PLATFORM_M65`, `CPU_45GS02`, `MEGA_SUPPORT`;
  `asm_cpu` values 3 and 4 (6502 and 4510 selectable at run time); m65
  test bundles ([build_system.md](build_system.md)).
- [ ] B2. Classifier: `mn7` over the m65 key set
  ([mn_classify.md § Variants](modules/mn_classify.md#variants)).
- [ ] B3. `mode_parse`: `(e),z`, `(e,sp),y`, `[e]`, `[e],z`, wide
  immediate ([addr_mode.md](modules/addr_mode.md)).
- [ ] B4. `asm_line`: mnemonic suffix (digit, `q`), Q zone, far flag,
  prefix emission, `REL`/`REL16` selection, the m65 gate matrix
  ([asm_line.md](modules/asm_line.md)).
- [ ] B4b. Pass stamp for pass-stable branch width: `sym_stamp` /
  `sym_fwd` ([symtab.md § Pass stamp](modules/symtab.md#pass-stamp-mega_support)),
  `expr_fwd` ([expr.md](modules/expr.md)), per-pass stamp and built-in
  refresh in asm_src ([asm_src.md](modules/asm_src.md)) — all
  `MEGA_SUPPORT` only, so the C64 builds do not grow.
- [ ] B5. `.cpu` / `u` on m65 ([assembler_syntax.md](assembler_syntax.md),
  [repl.md](modules/repl.md)).
- [ ] B6. `dasm_insn`: prefix peel, m65 modes, 1–5-byte length
  ([dasm.md](modules/dasm.md)).
- [ ] B7. REPL `.` / `d`: hex columns = the build's maximum length;
  `dot_assemble` passes suffixes, `[`, `,z`, `,sp`
  ([repl.md](modules/repl.md)).

### Prerequisite bug (separate fix, lands before B4)

- [ ] **Bit-op mnemonics are not assembled.**  `asm_line.s` zones D/E
  (`RMB`/`SMB`/`BBR`/`BBS`) are `jmp asm_error` ("not yet tested"),
  while [asm_line.md](modules/asm_line.md) documents them as working;
  `dot_assemble` also stops the mnemonic at the first digit.  Affects
  c64-65c02 today; the 4510 keeps all four.  Fix under its own CDD
  cycle (digit suffix scan + digit zone), then B4 builds on it.

- [ ] **`.cpu` and `u` do not enforce the CPU set.**  `asm_src.s::set_cpu`
  accepts `6502`/`6510`/`65c02` on every build (no ceiling check,
  though [assembler_syntax.md § `.cpu`](assembler_syntax.md#cpu--set-cpu-mode)
  says "limited by the build-time CPU ceiling"); `repl.s` `u` refuses
  `6510` on c64-65c02 (`and #5`), while
  [build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets)
  gives that build the set {6502, 6510, 65C02}.  **Ruled (D2,
  2026-11-16):** the c64-65c02 set includes 6510; `u` is fixed to
  accept it and `set_cpu` to refuse values outside the set — own CDD
  cycle, before B5.

- [ ] **The linker does not bound KDATA.**  memory_design.md gives KDATA
  $F100–$F4F1 (1010 B), with KBSS (the REPL screen save) from $F4F2,
  but `src/c64_cse.cfg.in` declares the KDATA area `size = $0EFA`, so
  a KDATA overflow would silently overwrite the KBSS area instead of
  failing the link.  Usage today: 400 / 681 / 776 B.  Own CDD cycle:
  `size = $03F2`, plus KBSS in the config so the linker sees both.

### Known issues filed by the Step-2 handoff audit (not this slice)

- [ ] **Debugger single-step on m65.**  `debugger.s::step_next_pc`
  takes `brk_pc + oplen_tbl[opcode]`; on a Q or far instruction that
  is the prefix's length, so the step BRK would land inside the
  instruction.  Also missing: `REL16` branches, `BSR`, `JSR (ind)` /
  `(abs,X)`, `RTS #`.  Belongs to the R7 debugger slice; it must use
  the prefix rule of [dasm.md § Prefix peel](modules/dasm.md#prefix-peel).
- [ ] **bbbc64's shared-file contract.**  Since A1
  `dev/mnemonic_tables.py` is cse's own (per-CPU-set blocks, ca65
  only; the `--syntax acme` paths went with the old writers), and
  bbbc64's golden copies of cse's tables (pinned at cse 910d96d) no
  longer describe cse's output.  `instruction_set.py`, `hashes.py` and
  `dasm_tables.py` are still identical in both repositories.  bbbc64
  adopts the model in its own CDD cycle; its `asm_tables.py` holds the
  same profile-row logic for ACME.
- [ ] **Retire the hand-numbered profile scheme in
  `instruction_set.py`.**  `OPERAND_PROFILES`' index order, `cmos_bit`,
  `_CMOS_PAIRS`, `_BIT_OPERAND` and the `JMP`/`TRB`/`TSB`/`AHX` entries
  of `_BASE_OPCODE_OVERRIDES` no longer drive any table: the generator
  derives profiles, categories and bases from `instructions(view)`.
  `OPCODES` already lists every mode per mnemonic, so `MNEMONICS`
  could shrink to (key → category).  The file is shared with bbbc64 —
  own CDD cycle, coordinated with the item above.

### Step-2 rulings (operator, 2026-11-16)

- **Single m65 build.**  m65-45gs02 is the only m65 target: 45GS02 by
  default, 6502 and 4510 selectable at run time.  One feature define,
  `MEGA_SUPPORT`.
- **D1. Branch width under forward references:** the per-pass symbol
  stamp (B4b) — a target read before its definition in the current
  pass takes `REL`; otherwise by distance.
- **D2.** c64-65c02's CPU set includes 6510 (see the `.cpu`/`u` bug).
- **D3.** `$EA` lists as `eom` in every view of the m65 build.
- **D4.** `rtn #$nn` is the spelling of `$62` (`rts #$nn` refused),
  per bbbc64's leniency criterion.
- **D5.** O1 and O3 stay open until checked on hardware; Phase A does
  not depend on them.
- **doc/README.md** § Authoritative data files gets its row update
  after the operator's pending README edits are committed.

### Open questions (hardware)

- **O1. `REL16` offset base.**  Contract states `target − (PC + 2)`
  (the address of the instruction's last byte).  Verify against the
  compendium and on hardware.
- **O3. Q-mode coverage** (`Q_MODES`) is checked against the
  compendium only; confirm the edge rows (`LDQ ($nn),Z`, `ASLQ $nn,X`)
  on hardware.

O1 and O3 get a provisional answer from xmega65 (slice 2, S2-3a and
S2-8): an emulator's answer, which the hardware confirms.  M65Emu
cannot answer them on its own — its semantics are our reading of the
compendium until its golden file, recorded in xmega65, says otherwise.

**Provisional answers (xmega65 `0870689e`, S2-3a golden file,
2026-11-17)** — both still open for the hardware:
- O1: xmega65 agrees with the contract — a 16-bit branch or `BSR`
  lands at its last byte plus the offset (cases `BRA 16-bit
  relative`, `BRA16 backwards`, `BSR backwards`).
- O3: both edge rows exist and behave as listed — `LDQ ($nn),Z` adds
  `Z` to the pointer (case `LDQ ($20),Z Z=03`), `ASLQ $nn,X` shifts the
  four bytes at base page + `X` (case `ASLQ base-page quad,X`).

## M65 slice 2 — the MEGA65 PRG (R7, platform layer)

**Depends on:** [slice 1](#m65--the-45gs02-assembler-and-disassembler-r7-slice-1)
(the m65 CPU layer, Phase B).  Its own CDD cycle: this section is the
plan; the CDD Analysis settles the open design items (S2-Q1…Q5)
before any test or code lands.

**Target (operator, 2026-11-17).**  The m65-45gs02 build ships as a
native MEGA65 program — MEGA65 mode (BASIC 65 and the MEGA65
KERNAL), not GO64:

- **Load and start.**  A PRG loading at `$2001`, whose BASIC 65
  stub `SYS`es the loader; the loader copies the payload to where it
  runs and initialises the data area, as the C64 loader does
  ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)).
- **Distribution.**  The PRG (raw and exomizer SFX, `-t 65`) and a
  D81 (`build/cse-m65.d81`, written by `c1541`)
  ([build_system.md § The m65 PRG](build_system.md#the-m65-prg)).
- **Clean 6502 code.**  Every module stays `.setcpu "6502"`.  A
  45GS02-only instruction the platform layer needs — banking (`MAP`,
  `EOM`), flat 28-bit access (`[zp],Z`), the `Z` register — is
  written as raw bytes through one macro include, `src/m45_ops.inc`,
  and nowhere else.
- **The C64 builds do not change** (the slice-1 hard constraint
  holds).

**Carried over unchanged** (checked 2026-11-17 against the MEGA65 ROM
in xmega65's data directory):
- The KERNAL jump table.  `CHROUT`, `CHRIN`, `GETIN`, `STOP`, `OPEN`
  are the same `JMP ($03xx)` stubs at the same addresses as the
  C64's; `LOAD`, `PLOT`, `SETLFS` sit at the same jump-table
  addresses.
- The loader's copy scheme ([memory_design.md § Loader Module](memory_design.md#loader-module-loaders)).
- The CPU layer (slice 1).

**Needs an m65 counterpart** (survey 2026-11-17):
- **C64 ROM internals called directly:** `$EA31`, `$EA81`, `$FE43`,
  `$F8DA`, `$E544`, `$E9D6`, `$FCE2`, `$F6ED` (main, mem, debugger,
  cse_io, repl).  The MEGA65 KERNAL's internals are elsewhere (its NMI
  entry is `$FAC1`, not `$FE43`).
- **KERNAL RAM variables used directly:** `$C6`, `$CC`, `$D1`–`$D3`,
  `$D6`, `$F3`–`$F4`
  ([memory_design.md § KERNAL ZP locations](memory_design.md#kernal-zp-locations-readwritten-directly)),
  and the `$0316`/`$0318` hooks.
- **Screen:** 40×25 at `$0400` with colour RAM at `$D800` (screen,
  cse_io, editor, repl, log, main); MEGA65 mode boots 80×25 at
  `$0800`.
- **Data under the KERNAL:** `$E000`–`$FFFF` through `$01` bit 1
  (symbol table, heap, KDATA, screen save, ZP snapshot), and the
  `$FFFA`/`$FFFE` RAM-shadow vectors.
- **Zero page `$02`–`$7F`** and the cold-init snapshot, against
  BASIC 65's zero-page use.

**Plan:**

- [ ] S2-1. Build: the `PLATFORM=m65` PRG target — linker config,
  BASIC 65 stub at `$2001`, loader, exomizer `-t 65`; `make disk`
  writes the D81, `make run` starts xmega65
  ([build_system.md § The m65 PRG](build_system.md#the-m65-prg)).
  With it, M65Emu's first run of cse itself: the m65 test bundles
  and an m65 PRG fixture, `load_prg()` of the real PRG (its
  relocated segments included) and `init_cse()` against its symbols
  — so far tested only on synthetic PRGs (CDD audit, 2026-11-17).
- [ ] S2-2. `src/m45_ops.inc`, the raw-byte macros, and an audit
  test: no module encodes a 45GS02-only instruction outside it.
- [x] S2-3. M65Emu, the m65 integration harness
  ([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)).
  It depends on none of the open design items, so it lands first
  (operator, 2026-11-17).
  - [x] S2-3a. `MPU45GS02`: the whole 45GS02 — all 256 4510 opcodes,
    the Q and flat prefixes, `Z`, `B`, the 16-bit stack, the `MAP`
    latch; decoder from the compendium fixture; clean mode.  Its golden
    file `m65_cpu.json`, recorded in xmega65 by
    `dev/capture_m65_golden.py`, and `test_mpu45gs02.py` against it.
    Done 2026-11-17: 518 recorded cases replay; the recording overruled
    the reading on BCD (NMOS-style) and `BIT #` (sets `N`/`V`)
    ([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)).
    The xmega65 driver is `tests/xmega65.py`, shared with S2-8.
  - [x] S2-3b. `M65Memory`: the 28-bit store, the `MAP` / `$01` /
    `$D030` / `$D02F` page table (16 × 4 KB), the CPU port, ROM
    protection, colour RAM and its window, flat access;
    `test_m65memory.py` against translations recorded in xmega65 by
    `dev/capture_m65_mem.py` (`m65_mem.json`).  Done 2026-11-17: all
    29 recorded states replay; the recording added rules the reading
    lacked (a latched `$D030` keeps banking in VIC-II mode; the base
    colour window is 4-bit in VIC-II mode, the extended one never;
    I/O registers are the same in every I/O mode).
  - [x] S2-3c. The post-boot state (`dev/capture_m65_state.py` →
    `build/m65_state/`, captured by hand) with a reference run; the
    harness base shared with `C64Emu` (`tests/emu_base.py`) and
    `M65Emu`; a first Tier I test calls `CHROUT` on the real MEGA65
    KERNAL and matches xmega65's reference run.  Done 2026-11-17: the
    reference run matches step for step and byte for byte; `C64Emu`
    moved onto the base unchanged in behaviour (suite before and
    after: 4552 passed).
  - [x] S2-3d. Devices, as the KERNAL needs them: the DMA controller
    (scrolling; checked against jobs recorded in xmega65,
    `dev/capture_m65_dma.py` → `m65_dma.json`, and a scroll reference
    run), the keyboard queue and `inject_keys()` (`GETIN`), the CIA1
    matrix port.  (Raster timing and the CIA timers stay unmodelled:
    S2-3e.)
    Done 2026-11-17: all 28 recorded jobs and the 30-line scroll
    replay byte for byte; options stay for a whole chained session.
  - [x] S2-3e. Feature parity with `C64Emu` — the goal is C64Emu's
    test surface, not a fuller MEGA65 (operator, 2026-11-17).  What
    both harnesses offer moves into `EmuBase`: the interrupt scheduler
    and the jiffy tick, the keyboard matrix with STOP and RESTORE,
    `inject_key()`, `load_prg()` with segment relocation,
    `set_cursor()` and `init_cse()`; M65Emu adds the two latches the
    MEGA65 KERNAL reads — `$D019` (the tick's VIC interrupt) and
    `$DD0D` (RESTORE).  C64Emu's behaviour stays as it is, its own
    tests unchanged in what they assert.  Not part of parity, because
    C64Emu does not model them either: raster timing, CIA timers, the
    TOD clock (the MEGA65's `RDTIM` reads it), the hypervisor, disk.
    `init_cse()` runs on a real m65 build once S2-1 makes one.
    Done 2026-11-17: the MEGA65 KERNAL keeps no jiffy counter (its
    `RDTIM` reads the CIA1 TOD clock) and does its frame work only when
    `$D019` bit 7 is set, so M65Emu's tick latches the raster bit; its
    STOP scan reads the CIA1 matrix into `$91`, as the C64's does.
    `test_emu_parity.py` runs the shared contracts on both harnesses;
    C64Emu's earlier tests pass unchanged against the new base.
- [ ] S2-4. Memory model: the data area in a RAM bank outside BASIC
  65's use, mapped into a 16-bit window by `MAP`, so the `(zp),y`
  readers stay unchanged and only mem.s's bank-in/out helpers change;
  the interrupt-vector shadows
  ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)).
- [ ] S2-5. Platform constants: the KERNAL internals and RAM
  variables, one include per platform.
- [ ] S2-6. Screen driver for MEGA65 mode.
- [ ] S2-7. Debugger hooks (BRK, NMI) on the MEGA65 KERNAL.
- [ ] S2-8. Tier X: the xmega65 tests — boot to the prompt from the
  PRG and the D81, typed REPL commands, the screen dump, the golden
  re-check of S2-3; provisional answers to O1 and O3
  ([testing.md § Tier X](testing.md#tier-x--xmega65-m65-automated)).
  Also check in xmega65 that the KERNAL's IRQ frame work runs on a
  latched raster bit — the jiffy tick's stand-in for a frame
  ([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness),
  "Not in the recording"; CDD audit, 2026-11-17).  (The two latches'
  register behaviour is recorded: `m65_latches.json`, 2026-11-17 —
  it corrected bit 7 of `$D019` to the IRQ line and bits 5–6 to 1.)

**Open design items** (the CDD Analysis settles them):

- **S2-Q1. Data bank and window.**  Which 64 KB bank holds the data
  area, which 16-bit window `MAP` maps it into, how that interacts
  with the KERNAL's own mapping, and how interrupts behave while it
  is mapped.
- **S2-Q2. Screen width.**  80×25 native or 40×25 (editor width,
  REPL layout, `m`/`d` line formats).
- **S2-Q3. Zero page.**  Share base page 0 with BASIC 65 and the
  KERNAL (save and restore, as on the C64), or a private base page
  through the `B` register (every KERNAL call needs `B` = 0).
- **S2-Q4. Exit to BASIC 65.**  What `x` restores.
- **S2-Q5. CPU speed.**  Run at 40 MHz (a register write, not an
  instruction) or keep the BASIC 65 setting.
- **S2-Q6. R3 dependency.**  The R7 roadmap entry makes the platform
  layer depend on [R3](#r3--universal-c64c128-binary) (machine
  differences isolated to leaf functions).  Either slice 2 waits for
  R3, or slice 2 does that isolation for c64/m65 (S2-4, S2-5) and R3
  later adds the C128 to it.

### Slice-2 rulings (operator, 2026-11-17)

- **Native, not GO64.**  The m65 PRG runs in MEGA65 mode, loads at
  `$2001` and copies itself to where it belongs.
- **Distribution:** PRG and D81.
- **Clean 6502 code;** 45GS02-only instructions as raw bytes.
- **M65Emu: a full 45GS02 port of py65 plus the MEGA65 memory
  layout,** devices as tests need them — a subclass in `tests/`, the
  way py65's own 65C02 MPU extends its 6502 MPU, not a patch to the
  installed package.  It is the m65 build's Tier I, checked against
  xmega65.

## CDD amendments pending

Session retrospective findings (debugger trace workflow,
2026-04-22 to -24) and 2026-04-25 CDD Maintenance round.

Items are classified by **scope of applicability**, not by their
source.  *Universal* amendments tighten the CDD/TDD method itself;
*domain-class* amendments apply only to projects of a particular
shape; *project-specific* items belong to CSE alone.

**Status (2026-04-27):** Tier A landed three amendments to
README.md (CDD Method + Escape Analysis); Tier B landed two
principles in testing.md (14 + 15) and one in README.md
(Principle 7); Tier C1 was *initially* closed with a documented
"harness limitation" in testing.md, then **re-opened** when
deeper RCA showed the diagnosis was wrong, and finally **closed
2026-04-27 by Phase 24** — the cold-init bug fix landed (F1 +
F2), the testing.md harness-limitations entry was retired, and
three new Escape-Analysis principles (16: cold-init terminal-
state assertion; 17: sequence-prerequisite declaration; 18:
multi-CPU integration-test parity) were promoted from the
bug-entry candidates into testing.md.  `mn_config.s` retirement
closed cleanly under § Architecture.

### Tier A — Universal CDD System amendments

*Apply to any project under CDD discipline, regardless of domain.
These amendments belong in [doc/README.md](README.md) (CDD Method
/ Escape Analysis) or [doc/testing.md](testing.md) at the
process-level layers, not at the principle-list layer.*

- [x] ~~**Escape Analysis "triage" gate between sweep and commit**~~
  (closed 2026-04-25).  README.md § Escape Analysis: step 5
  rewritten to produce a *candidate list* (not yet decisions); new
  step 6 *Triage the sweep* sits between sweep and commit, splitting
  candidates into mechanical-inline / queued-TODO / skip-worthy
  buckets.  Step 6 (commit) renumbered to step 7.

- [x] ~~**Cycle-detection heuristic**~~ (closed 2026-04-25).
  README.md § CDD Method step 4 (Implementation) gained the
  *Cycle-detection rule*: ≥3 modifications of the same proc/section
  in one session for the same concern signals an unclear spec —
  pause and clarify before iterating.

- [x] ~~**Commit granularity rule**~~ (closed 2026-04-25).
  README.md § CDD Method step 6 (Commit) gained the *Granularity
  rule*: one fix per commit unless the fixes are trivially
  co-dependent.  Escape Analysis step 7 explicitly suspends the
  rule (the value of an EA closure is in seeing the bug fix, the
  missing test, and the contract/principle amendment land as one
  auditable unit).

### Tier B — Domain-class amendments

*Apply only to projects of a particular shape.  Not universal:
a project outside the named class does not need the amendment.
Each item names the class it depends on.*

#### B1. State-machine projects

*Projects with enumerated states consumed by multiple sites:
compilers, debuggers, protocol implementations, workflow engines,
game logic.  Pure libraries and stateless tools are out of class.*

- [x] ~~**State-introduction principle** (proposed testing.md
  Principle 14)~~ (closed 2026-04-25).  Landed as testing.md
  Principle 14 (*Enumerated-state introductions enumerate the
  cross-product*) with the dbg_reason × command escape as
  cautionary example.  Scope-limited to projects with enumerated
  states consumed by multiple sites — explicitly NOT universal
  per the Tier B1 classification.

#### B2. Projects with rendered output / UX

*Projects whose contract surface includes pixels, screen layout,
or stream-formatted output: TUI tools, GUIs, REPLs with on-screen
panels.  Pure libraries with structured-data return values are
out of class.*

- [x] ~~**Display-content vs state-content test distinction**
  (proposed testing.md Principle 15)~~ (closed 2026-04-25).
  Landed as testing.md Principle 15 (*Display-content and
  state-content are different contracts*) with the DBG_RTS
  panel-render escape as cautionary example.  Cross-references
  README.md Principle 7 (*Contract the model, not the render*)
  for the doc-side complement.

- [x] ~~**CDD-Lite for UX**~~ (closed 2026-04-25).  Landed as
  README.md Principle 7 (*Contract the model, not the render*)
  with the debugger.md "Step output semantics" appendix as
  cautionary example.  Names testing.md Principle 15 as the
  test-side complement.  Together the two principles draw the
  line: docs specify abstract behaviour, tests assert abstract
  visible results, code owns the render.

### Tier C — Project-specific (CSE)

#### C1. Process / methodology debt

- [x] ~~**Test-harness layout fragility investigation**~~
  (closed 2026-04-27 alongside the cold-init bug fix).  The
  2026-04-25 closure attributed the fragility to a py65 step-
  engine artifact (wrong diagnosis); the 2026-04-25 RCA pass
  showed it was a production cold-init bug; the Phase-24
  dedicated session landed F1 (cold-init order swap) and F2
  (`gb_init` becomes a leaf, `update_workend` lifts to
  `ed_init`'s wrapper).  All 17 previously-fragile tests in
  `test_kernel_transition.py` are stable green without
  per-test triage — exactly as the bug-entry prediction table
  forecast.  See [§ Bugs](#bugs) for the closed bug entry.

#### C2. Corpus-coverage gaps (CDD Maintenance 2026-04-25)

*Tracked further down under § Planned / Corpus.  The items
there are mechanical fixes; this header just acknowledges they
belong in the same taxonomy.*

### Phase 24 retrospective — amendment candidates (2026-04-27)

*Findings from the Phase-24 session retrospective (cold-init bug
fix + warm/cold init survey).  These are candidates for a future
CDD Review round; not yet triaged into Tier A / B / C.*

- [ ] **Optimization survey checklist: fall-through opportunities
  across reorderable proc boundaries.**  The Phase-24 init survey
  initially missed the warmstart fall-through (`cse_refresh` →
  `main_loop_top`) on the first pass and only caught it after the
  user prompted for a second look.  Candidate addition to
  [doc/optimization.md](optimization.md): when surveying a code
  region, explicitly list adjacent procs whose reorder would
  enable a `jmp foo` → fall-through conversion (saves 3 B per
  collapsed jump).  Likely **Tier A** (universal optimization
  technique, applies to any assembly project).

- [x] ~~**CDD Maintenance: flag stale "Moved from …" historical
  headers after a time threshold.**~~  (Closed 2026-05-02 by
  Step 1E of the doc-audit pass.)  Phase-24 had retired three
  "Moved from editor.s 188..208 / 210..228 / 230..356" comment
  blocks in `gap_buffer.s` that had outlived their refactor
  context.  Step 1E mechanised the grep via
  `dev/audit_phase_markers.py` and surfaced ten more
  `; Moved from editor.s ...` comments still in `gap_buffer.s`
  (rows 296, 331, 365, 393, 423, 465, 480, 520, 573, 591) —
  all retired in the same commit.  The script remains as
  permanent infrastructure for the next maintenance round.

  Note for the next CDD Review: this audit class still belongs
  in the README.md § CDD Maintenance "8-item audit" list
  (currently item 9 candidate per **A3** above).  The script
  generalises **A3** mechanically — anything matching `Phase \d`,
  `Move \d`, `moved to`, `previously`, `was formerly`, or
  `TODO:` shows up in the report sorted by frequency, ready for
  human triage.

- [ ] **TDD principle: probe assumptions before encoding them in
  tests.**  Phase-24 hit three test-bugs in succession from
  unverified assumptions: (a) PETSCII vs screencode encoding for
  `"workend"` ($57 vs $17); (b) `WORKSTART` value (0x07FF vs
  0x0800 = TXTTAB-1); (c) `cse_start` / `cse_zp_end` treated as
  byte-valued symbols when they're routine entry points.  Each
  cost a red-bar cycle.  Candidate addition to testing.md as a
  new principle: *Probe before you pin.*  When a test asserts a
  numeric value derived from a memory map, encoding, or symbol
  semantic, prove the value with a one-liner probe (read the
  PRG, jsr the routine and read A) before hardcoding it.
  Cautionary example: Phase-24 cold-init tests.  Likely
  **Tier B** (domain-class: low-level systems with multiple
  encoding/layout layers; less relevant to high-level apps).

- [x] ~~**CDD pattern: pre-draft Escape-Analysis principles inside
  the bug entry.**~~  (Closed 2026-05-08.)  Landed as the
  *Pre-drafted principles* italic note in README.md § Escape
  Analysis step 4 (Trace to the principle miss), with the
  Phase-24 cold-init bug entry's pre-drafted Principles 16 / 17 /
  18 text as cautionary example.  The Phase-24 bug entry's
  Phase-4 section contained pre-drafted principle text before
  the principles were promoted; step-4 transcription was trivial
  because the drafts were already publication-quality by the
  time the fix landed — the evidence the new note cites.

- [ ] **CDD Method: build-cache awareness for tests targeting
  debug builds.**  Phase-24 lost a debugging cycle to a stale
  debug PRG: `make` rebuilt only release variants, leaving the
  debug PRG (which `cse_prg` fixture uses) at the pre-fix
  binary.  Candidate addition to build_system.md or testing.md:
  when a fix targets behaviour observable only under debug
  symbols, run `make debug` (or equivalent) explicitly before
  running the test suite — `make` alone is not sufficient.
  Likely **Tier C** (CSE-specific: depends on this project's
  build target layout).

### Phase 25 retrospective — amendment candidates (2026-04-29)

*Findings from the Phase-25 release-polish session CDD Log.
See [doc/cdd_log.md § Phase 25](cdd_log.md) for the full
self-review and motivating evidence behind each candidate.
Not yet triaged into Tier A / B / C; the Log frames all five
as universal (Tier A).*

- [x] ~~**A1. Agent-finding verification principle.**~~  (Closed
  2026-05-08.)  Landed as the *Agent-finding verification* italic
  sub-rule in README.md § CDD Method step 4 (Implementation),
  alongside the existing *Cycle-detection rule*, with the
  Phase-25 false-positive optimisation findings (set_cpu
  carry-preservation; `_asm_line_core` / `asm_org` / `asm_size` /
  `asm_errors` "dead" exports actually consumed via test label
  lookups; `_expr_eval_inner` inlining blocked by dual-entry
  label `expr_eval_nb`) as cautionary example.

- [x] ~~**A2. TODO closure-with-commit rule.**~~  (Closed
  2026-05-08.)  Landed as the *TODO closure rule* italic sub-rule
  in README.md § CDD Method step 6 (Commit), alongside the
  existing *Granularity rule*, with the *Loader reverse-direction
  copy* entry as cautionary example.

- [x] ~~**A3. Stale historical markers as a CDD Maintenance
  audit item.**~~  (Closed 2026-05-08.)  Landed as audit item 9
  (*Historical-marker drift*) in README.md § CDD Maintenance,
  citing the existing `dev/audit_phase_markers.py` mechanism that
  Phase-24 already deployed.  The Phase-24 candidate "flag stale
  'Moved from …' historical headers after a time threshold"
  (closed 2026-05-02) is the same audit class — both surface the
  same drift category and are now jointly retired.  Motivating
  evidence: stale-marker cleanup recurred in three distinct
  Phase-25 sessions despite each being thorough at the time.

- [x] ~~**A4. Prefer enumeration codes over boolean flags.**~~
  (Closed 2026-05-08.)  Landed as Principle 8 in README.md §
  Principles, with `asm_expr_err` → `asm_err_code` (Phase-25
  rename through four files) as cautionary example.  The
  principle is a code-design discipline (sibling to Principle
  7's *Contract the model, not the render*), not a corpus-
  discipline principle.

- [x] ~~**A5. Cross-module handoff sweep in Step 2, not after
  the fact.**~~  (Closed 2026-05-08.)  Landed as the *Cross-module
  handoff audit* italic sub-rule in README.md § CDD Method step 2
  (CDD Analysis), with the `.` REPL command's missing ACC
  label-shadow warning as cautionary example.  The proactive
  step-2 audit complements the reactive step-5(b) sweep that
  Escape Analysis already prescribes.

- [ ] **Meta: CDD Log cadence.**  The glossary entry for *CDD
  Log* (added Phase 25) describes the practice but does not
  fix a cadence.  The Log itself recommends: *performed at each
  milestone, alongside CDD Maintenance — the Log is the
  reflective half of the milestone gate (CDD Maintenance audits
  the artefact; the Log audits the process).*  Candidate
  amendment to the glossary entry to lock that cadence in.
  Likely **Tier A**.

## CDD Maintenance + Quality Sweep findings (2026-11-17/18)

Findings of the repo-wide CDD Maintenance pass (eight doc-vs-code
reviewers) and the first CDD Quality Sweep
([README.md § CDD Quality Sweep](README.md#cdd-quality-sweep): source
edge-probes, lifecycle matrix, cross-doc fact clusters, task-driven
cold reader, live example execution).  Every **code bug** below was
reproduced live on the debug PRG under C64Emu (repro scripts kept with
the sweep notes); every doc item was read on both sides.  Code and
test items go through the CDD Method; doc-drift items are fixed in the
documentation round that follows this filing.

### Code bugs — debugger and breakpoints

- [x] **A breakpoint that never ran writes `$00` into user code.**
  `dbg_bp_set` stores `saved = 0` (`breakpoints.s` set path) and
  `unpatch_all` restores `saved` for every enabled slot, patched or
  not, so `b ADDR` followed by any `end_debug_body` (`R`, the
  `a`/`j`/`g` end-debug gate) writes `$00` at ADDR.  Track "patched"
  per slot or skip unpatched slots.
  Fixed 2026-11-18: flags bit 7 marks a patched slot; `patch_all`
  sets it (and skips patched slots), `unpatch_all` restores and
  clears only patched ones, tests `TestBpPatchedFlag`,
  `TestBreakpointNeverRun`.
- [x] **`cse_recover` wipes the breakpoint table and leaves patched
  `$00` bytes behind.**  `hw_reinit_body` → `dbg_init` → `bp_init`
  zeroes `bp_table` before `end_debug_body` runs, so breakpoints
  patched in at the fault are never unpatched; contradicts
  memory_design.md § Breakpoint invariant ("survives every
  warmstart").  `reset_globals` also resets `cur_addr`,
  `block_size`, `cur_device` on recovery (undocumented).
  Fixed 2026-11-18: `dbg_init` no longer calls `bp_init`; `_main`
  zeroes the table once at cold init, so `cse_recover`'s
  `end_debug_body` unpatches with the table intact; the
  `reset_globals` reset on recovery is now documented
  (memory_design.md § Warmstart entry points), test
  `TestRecoverKeepsBreakpoints`.
- [x] **The decimal flag leaks from user code into the kernel.**
  `SED; RTS` → `save_userland_state`'s `adc #8` and the brk_pc
  `sbc #2` run in decimal → bad `reg_sp`, missed brk_stub match →
  kernel BRK → `cse_recover`; D stays set afterwards (`+ $0a` gives
  `$0314`).  No `cld` on any kernel entry (BRK, NMI, IRQ early entry).
  Fixed 2026-11-18: `cld` first in `cse_brk_handler` and
  `cse_nmi_handler` (the user's D stays in `reg_p`), test
  `TestDecimalFlag`.
- [x] **A cold preview (`t` with no session) counts as resumable.**
  It promotes `dbg_reason` to DBG_BRK with `reg_sp = $FF` and no
  sentinel; `c` then resumes and the user's RTS jumps into zero page
  (`;!stk 1`, `brk at $fffe`).
  Fixed 2026-11-18: `c` and `t`/`o` share `set_run_mode`: after a
  cold preview the first run is MODE_JUMP (sentinel pushed) and
  consumes `cold_preview_done`, test `TestColdPreviewSession`.
- [x] **`cold_preview_done` survives `end_debug_body`.**  A later real
  step uses MODE_JUMP and pushes a second sentinel; the subroutine's
  RTS ends the session early (`; rts`).
  Fixed 2026-11-18: `end_debug_body` clears `cold_preview_done`
  (exported by repl.s), test
  `TestColdPreviewSession::test_end_debug_clears_cold_preview`.
- [x] **A refused step (`;!range`) leaves the hit breakpoint disabled
  and `step_state` set** (`cmd_step` writes them before the range
  gate; `@oor_warn` undoes nothing; `end_debug_body` does not
  re-enable the slot).
  Fixed 2026-11-18: new `step_cleanup` (repl.s) undoes a step — step
  state, step slots, the disabled bp — and runs on the refusal,
  after a step lands, and in `end_debug_body` (after its
  `unpatch_all`), test `TestRefusedStep`.
- [x] **`dbg_bp_hit` survives `b *` / `b ADDR`**: `c` then deletes the
  unrelated breakpoint now in that slot.
  Fixed 2026-11-18: `dbg_bp_del` of the hit slot and `dbg_bp_clear`
  set `dbg_bp_hit = $FF`, tests `TestBpHitInvalidation`,
  `TestBpHitAfterTableEdit`.
- [x] **RUN/STOP+RESTORE in the editor** redraws the REPL but leaves
  `state = ST_EDIT`; the next keys silently edit the source.
  Fixed 2026-11-18: `refresh_body` sets `state = ST_REPL` (the view
  it draws; the source is kept), test `TestRefreshInEditor`.
- [x] **RUN/STOP+RESTORE during `a`** refreshes with `kernal_out = 1`
  and `$01 = $34` → kernel BRK → `cse_recover` (assembly abandoned,
  globals and breakpoints reset).
  Fixed 2026-11-18: `refresh_body` banks the KERNAL in (`$01` = $36,
  `kernal_out` = 0; moved there from `end_debug_body`), so RESTORE
  abandons the assembly and lands at a working prompt, test
  `TestRestoreDuringAssembly`.
- [x] **`j <bad expression>` runs anyway**: `try_expr` returns C=0 for
  both empty and error, so `j nosuchsym` prints `;?expr undef` and
  jumps to the old `cur_addr`.  Same shape in `+`/`-` (moves by
  `block_size` after the error).
  Fixed 2026-11-18: `try_expr` returns Z=0 for an error, Z=1 for
  empty; `j` runs only on success or empty, `expr_or_blocksize`
  drops the `+`/`-` handler on an error, test
  `TestBadExpressionAborts`.
- [x] **`cse_zp_end` returns `$79`, not the first free byte `$78`**
  (`mem.s` `<(__ZP_LAST__ + 1)`; ld65's `__ZP_LAST__` already is the
  first free byte); cold init leaves `$78` unfilled.
  `test_mem.py` pins the `+ 1`.
  Fixed 2026-11-18: `cse_zp_end` returns `<__ZP_LAST__` (immediate;
  the RODATA byte is gone), so cold init fills $78; tests `TestColdI
  nitTerminalState::test_zp_end_is_first_byte_after_cse_zp`,
  `TestCseZpEnd::test_returns_zp_last_low_byte`.
- [ ] **Edits past `$FFFF` wrap into the live CPU port.**  `m`, `.`
  and assembly wrap `(zp),y` / `asm_out` to `$0000`/`$0001` — not the
  user-ZP image — e.g. `m fffc 00 00 00 00 2f 30` banks out KERNAL and
  I/O and crashes; `ffff:. 4c 2f 30` sets `$01` to `$32`; CSE's own ZP
  `$02`–`$07` is overwritten.  The user-ZP redirect applies only when
  the base's high byte is 0.
  REPL side fixed 2026-11-18: `zp_poke` (`m` edit, `.` hex poke) computes the
  16-bit effective address, so a run wrapping past `$FFFF` lands in
  `userland_zp_buf`, test `TestEditWrapPastFFFF`.  Open: the
  assembler's `asm_out` wrap (`.` mnemonic, `a`) belongs to the
  assembler track; the `m`/`.` display of a wrapping run still reads
  live ZP (`zp_stage_prep` stages only page-0 bases).
- [x] **INS at column 0 of the REPL hangs and writes the workspace**
  (`main.s` `@ins_loop`: unsigned `cpy CUR_COL` with CUR_COL = 0 never
  ends; Y wraps over `(rp_ptr)+0..255`).
  Fixed 2026-11-18: the shift loop ends on `Y == CUR_COL` (col 39
  skips it), then blanks that column, test `TestReplInsKey`.
- [x] **The IRQ early-entry stub forces `$01 = $34`** on return
  (`bank_out_stub`), so user code running with KERNAL out and I/O in
  (`$35`) loses I/O after the first IRQ; contradicts
  userland_contract.md § 5.3.
  Fixed 2026-11-18: `@irq_path` pushes the interrupted `$01` under
  the second frame and `bank_out_stub` restores it, test
  `TestIrqKeepsBanking`.
- [x] **`r` parses its fields by position, not by label**: `r x:05`
  sets A, `r a:zz` / `r a` set every register to `$FF` with no error;
  a following `c` resumes with SP = `$FF` and crashes.
  Fixed 2026-11-18: `cmd_reg` matches fields by label (`a:` `x:`
  `y:` `s:` `pc:`, 8-char flags), any order and subset; the line is
  checked in full before anything is applied, a bad field is
  `;?syntax`, tests `TestRegisterFieldsByLabel`.
- [x] **Step over `JMP ($xxFF)` ignores the NMOS page wrap**: the step
  BRK is armed at the wrong target, user code runs free, and `$00`
  stays patched there.
  Fixed 2026-11-18: `step_next_pc` reads the high byte from $xx00
  (only the low byte of the vector address is incremented) unless
  `asm_cpu` is 65C02, tests
  `TestStepIndirectJump::test_jmp_ind_page_wrap_nmos` /
  `test_jmp_ind_no_wrap_65c02`.
- [x] **Step over `JMP (zp)` / `JMP (abs,X)` reads the vector from the
  kernel's ZP**, not `userland_zp_buf` (refused with `;!range`, or a
  wrong target).
  Fixed 2026-11-18: `step_next_pc` reads the vector through
  `peek_user` (`userland_zp_buf` for $00-$7F), tests
  `TestStepIndirectJump::test_jmp_zp_vector_from_user_zp` /
  `test_jmp_abs_x_vector_from_user_zp_65c02`.
- [x] **`t N` / `o N` take N mod 256** (`t 257` steps 1, `t 300`
  steps 44): `step_remaining` is one byte.
  Fixed 2026-11-18: `step_remaining` is 16-bit (cmd_step stores both
  bytes, the handler tests and decrements both), test
  `TestStepCount`.
- [x] **`b` accepts a duplicate address**: a second slot re-breaks at
  the same place after `c`; duplicates fill the table.
  Fixed 2026-11-18: `dbg_bp_set` returns the slot that already holds
  the address, tests `TestBpSetDuplicate`,
  `TestDuplicateBreakpoint`.
- [x] **The editor status bar shows lines ≥ 1000 as garbage**
  (`:00`, `<34`, `t00`) — no clamp on the 3-digit field.
  Fixed 2026-11-18: `ed_status_pos` writes the line right-aligned in
  cols 33-36 (blank-padded, clamped at 9999) with a div10 loop, test
  `TestStatusLineNumber` (test_editor.py).

### Code bugs — assembler

- [ ] **A lone `:` hangs `a`** (`:`, ` : nop`, `x: : nop`): a
  zero-length label re-scans the same word forever (`asm_src.s`
  `@adv_lbl`).
- [ ] **Symbol-heap overflow corrupts KDATA.**  `heap_copy_name`
  advances `_st_heap` before its bound check and never rolls back;
  enough long labels overwrite `$F100`+ (KDATA) and the REPL screen
  save — the assembler and disassembler stay broken until reload
  (`NOP` disassembles as `VBX`).  symtab.md claims the check prevents
  it.
- [ ] **Long labels overrun BSS.**  A global label of ≥ 24 characters
  followed by a local overruns `_scope_name` / `_full_label` /
  `_expr_buf` (no bounds), corrupting `_seg_pc`, `_min_pc`,
  `_max_pc`, `kernel_zp_buf`, `userland_zp_buf`.  No label-length
  limit is documented.
- [ ] **Expression nesting has no depth limit**: ~30 `(` wrap the
  hardware stack (`expr.s` parse_factor recursion).
- [ ] **Pass-0 forward references with an offset size to 0 bytes.**
  `lda tbl+1` (also `jsr fwd+3`, `bne fwd+2`, `sta fwd+1,x`)
  substitutes `asm_pc + 2` but leaves `expr_ptr` after the name, so
  the operand is a syntax error on pass 0 (silent there) and later
  labels shift: `.org $c000 / lda tbl+1 / jmp end / end: rts /
  tbl: .db 1,2` → `ad 05 c0 4c 03 c0`, 0 errors.
- [ ] **Pass-0/pass-1 width mismatch for later-defined ZP constants.**
  `lda zp` with `.const zp $10` after it is sized ABS on pass 0 and ZP
  on pass 1; following labels are one byte off (`jmp` into its own
  operand), 0 errors.  Pass 0 also writes bytes.
- [ ] **Code before the first `.org`** gets labels from the pass-0
  layout (default origin) while pass 1 emits at the first `.org`
  (`_set_first_org` overwrites `asm_org`; every pass starts at it).
- [ ] **Emitting past `$FFFF` wraps into `$0000`/`$0001`** (the CPU
  port) — no wrap check in `_asm_emit` / `_emit_byte`.
- [ ] **A full symbol table is silent**: 300 labels → 0 errors, 44
  dropped; `sym full` is reported only on pass 0, where `emit_error`
  is silent.
- [ ] **Directives read past their NUL**: `.o…` matches `.org` on the
  first letter (`.oops` = `.org`), `.co`/`.cp` likewise; `.const k`
  with no value reads stale `_line_buf` bytes.
- [ ] **`.cpu` in source changes `asm_cpu` for pass 1 from the start**
  (lines before the directive) and leaks into the REPL afterwards; not
  restored by `asm_assemble`.
- [ ] **REPL `.` with a symbol operand reads tables from ROM.**
  `sym_lookup`'s `kernal_bank_in` really banks in inside `asm_line`
  (non-nesting helpers), so `.asl $12,zz` emits `A2 12 02`, 0 errors.
- [ ] **Non-letters reach the mnemonic hash**: 906 false positives on
  mn7 builds (`ld8` → DEX, `xb` → BCC, `fo0` → NOP), 884 on mn6;
  `_asm_rd_upper` passes bytes below `$41`, and the tables are indexed
  out of range.  An empty line assembles to BRK on mn7 builds.
- [ ] **Implied instructions ignore their operand**: `rts garbage`,
  `nop $1234`, `inxy` assemble silently (zone A has no end check;
  asm_line.md says a fifth character is `;?syntax`).
- [ ] **A narrow branch operand is emitted as a raw offset**:
  `BNE $10` → `D0 10` (asm_line.md: the operand is the target).
- [ ] **`expr` loses the wide flag after a nested `<`/`>`**:
  `$0000+(<$12+1)` returns narrow (the saved flag is not stacked).
- [ ] **Immediate values > 255 are truncated silently**
  (`lda #$1234` → `A9 34`).
- [ ] **`//` comments are parsed as division** (`lda #1 // c` → expr
  error), though addr_mode.md lists `//` as end-of-expression.
- [ ] **Shift counts ignore their high byte**: `1<<256` = 1,
  `$8000>>256` = `$8000`.
- [ ] Latent: `mode_parse`'s accumulator test assumes `A` at offset 0
  (`ldy #1`) and has no CR/LF in its peek; production strips leading
  whitespace first.

### Code bugs — editor, build, tooling

- [x] **`TAB_WIDTH` accepts 1..32 but only powers of two work**
  (`and #TAB_MASK`); add a power-of-two `.error` and narrow the doc.
  Fixed 2026-11-18: editor.s refuses any TAB_WIDTH but 1/2/4/8/16/32 at build time; editor.md and build_system.md narrowed, test test_tab_width_must_be_power_of_two.
- [x] **RETURN at one byte of room**: the gutter-tab insert ignores
  carry; `ed_cur_col` drifts (editor.md says it cannot).
  Fixed 2026-11-18: a failed gutter-tab insert leaves `ed_cur_col` = 0 (CR kept, no indent), test test_return_with_one_byte_of_room_opens_line_without_indent.
- [x] **Tier I tests run against a stale PRG**: `conftest.py` calls
  `make` only when the PRG or map is missing; `.inc` files are not
  prerequisites in the Makefile or the bundles.
  Fixed 2026-11-18: conftest runs `make` once per session unconditionally; objects depend on their includes (`ca65 --create-dep`); bundles on `src/*.inc`, test test_build_freshness.py.
- [x] **`make … PLATFORM=m65` silently builds the C64 PRGs** — add a
  refusal guard until S2-1 (or fold into B1).
  Fixed 2026-11-18: the Makefile stops every PRG target with an error when PLATFORM≠c64, test test_makefile_guards.py.
- [x] **`oplen_tbl` keeps the last row where a 6510 and a 65C02
  opcode share a byte**; the generator should refuse a conflict.
  Fixed 2026-11-18: `oplen_lengths()` refuses a length conflict; a crash (JAM) row yields, so `$D2` is 2 (65C02 `CMP (zp)`, was 1), tests test_oplen_*.
- [ ] **Mutable bytes in CODE**: `main.s` `@key`, `dasm.s` `@adj`,
  `disk.s` `disk_save_prg`'s `@size_lo`/`@size_hi`
  (blocks a ROM/CRT build; memory_design.md "no self-modifying code").
  `main.s` half fixed 2026-11-18: `@key` is now `main_key` in BSS,
  test `TestMainCodeReadOnly`.  Open: `dasm.s` `@adj` (disassembler
  track), `disk.s` `disk_save_prg`'s size bytes.
- [x] `disk.s` closes LFN 1 on an OPEN failure although the file is
  LFN 2; the SEQ error paths close nothing.
  Fixed 2026-11-18: `_disk_open_buf` closes LFN 2 when OPEN fails (dead `@err_close` removed); C64Emu models an empty serial bus, test test_disk.py.
- [ ] Dead code and imports: `kernel_stack_budget` (exported, unused;
  repl.s duplicates it as `KSTK_MIN`), `str_end_dbg`, `str_no_name`,
  `io_color` (written, never read), `mn_vars.s` (empty shell); dead
  imports in `asm_src.s` (`buf_base`, `dec_pow_lo/hi`), `symtab.s`
  (`kernal_out`), `editor.s` (seven), `disk.s` (`io_color`, `io_puts`,
  `io_puthex2/4`), `repl.s` (`oplen_tbl`), `asm_src_test_stub.s`
  (`_min_pc`, `_max_pc`); `test_asm_src.py`'s dead `xfail` path.
- [x] `ed_insert_string` has no production caller and ignores
  `gb_insert`'s carry — keep as a test-only export (documented) or
  retire.
  Fixed 2026-11-18: kept as a documented test-only export (gap_buffer.md: ignores the carry, drops the rest on a full buffer), test TestEdInsertStringFull.
- [x] `dbg_reason` enum defined twice (`main.s`, `repl.s`).
  Fixed 2026-11-18: the enum lives in `src/dbg_reason.inc` (owner
  debugger.md), included by main.s and repl.s, test
  `TestDbgReasonSingleDefinition`.

### Code bugs — found by the live example run (2026-11-18)

- [ ] **`.const` with a symbol in its expression defines nothing**:
  `.const vic $d000 / .const border vic + $20 / sta border` →
  `;?…: undef` (expr's label lookup overwrites `sym_name`, which the
  `.const` handler still holds).  assembler_syntax.md's own example.
- [ ] **The `;!a shadow` warning crashes `a`**: printed while the
  KERNAL is banked out, `newline` → `io_sync` calls into the KERNAL
  area (CSE data there) → BRK → `cse_recover`.
- [ ] **CLR/HOME or ESC at a breakpoint, then `c`, hangs**:
  `cse_refresh` resets SP to `kernel_init_sp`, and kernel `jsr`s
  overwrite the user's `brk_stub` sentinel at `$01FE/$01FF`; README
  promises the debug context is preserved.
- [ ] **Dotted global labels**: `jmp main.loop` is `undef`; a global
  label with an embedded dot is defined but cannot be referenced (the
  operand expansion prefixes the scope at every `.`); `a_b:` is
  accepted though `_` is not a label character, and the reference
  fails.  Settle the label grammar (assembler_syntax.md) and enforce it.
- [ ] **`.db` values > 255 truncate silently** (`.db 256` → `$00`);
  **`.const 5 5`** defines a symbol named `5` (no `exp id`).
- [ ] **The assembler writes outside the workspace**: `.org $c000`
  assembles over CSE's own code with no error (the breakpoint range
  gate already refuses such addresses); add the same guard to emit.
- [x] **`scroll_up` uses `$FB–$FE`** — the C64's free user ZP —
  although userland_contract.md promises CSE never writes `$80–$FF`
  beyond the listed KERNAL cells; use CSE's own ZP.
  Fixed 2026-11-18 (d01cc76 on the track branch): `scr_src` at `$78–$79`,
  destination reuses `_io_scr`; user-free ZP is now `$7A–$7F`.

### Test gaps

- [x] The loader never runs in a test (`load_prg` relocates in
  Python); add one Tier I test running `loader_entry`.
  Fixed 2026-11-18: `loader_entry` runs on each unrelocated C64 PRG and is compared with `_relocate_segments()`, test test_loader.py.
- [x] `test_mem.py`'s TOP-RISK CPU-port skip is closable — C64Emu
  models the DDR; add the Tier I test.
  Fixed 2026-11-18: the skip is a C64Emu test on the PRG (fails if save_userland_zp skips the DDR unmask), test test_dollar_01_reads_fully_latched_under_ddr_ff.
- [x] No oracle test for `oplen_tbl` (testing.md claims test_dasm
  guards it; no bundle links it).
  Fixed 2026-11-18: the table is read out of each C64 PRG and held to instruction_set.py per opcode, test test_oplen_tbl_in_each_prg_matches_instruction_set.
- [ ] Untested contracts: `dbg_step_clear`, `dbg_init`'s outputs,
  breakpoint overlap and step slots 8–9; `leave_editor`,
  `ed_save_source`, `ed_load_source` (return codes 1/2);
  `seg_print_save`; `info_line`; REPL `k`, `Q`, `R`, `x`, `$`, `i`
  (full), `c`, `C` colours, `b` through `cmd_brk`, every `query_user`
  yes/no outcome; `cse_exit_to_basic`; `$A0` / leading whitespace in
  `test_addr_mode`.
  Editor part, 2026-11-18: `leave_editor` and `ed_load_source` code 1 tested (TestLeaveEditor, TestEdDiskErrors on C64Emu's empty serial bus); code 2 and the success paths are an explained skip until a virtual IEC disk exists.
  `ed_save_source` code 1, 2026-11-18: it reported success on a disk error (Z taken from `disk_save_seq`'s `ldx #0`) and cleared `ed_dirty`; fixed, test test_save_with_no_drive_returns_1_and_keeps_buffer_dirty.
  Runtime part covered 2026-11-18: `dbg_step_clear`, step slots 8-9
  and overlap (TestStepSlots / TestStepClear / TestOverlap),
  `dbg_init` (TestDbgInitOutputs), `k` `Q` `R` and every
  `query_user` outcome (TestQueryUserOutcomes), `x` and `C`
  (TestClearScreen / TestColorApply), `$` devices (TestDirDevice; it
  revealed `$ 260` selecting device 4, fixed), `i` full mode
  (TestInfoFullMode), `c` (TestContinueCommand), `b` via `cmd_brk`
  (TestBreakCommand), `cse_exit_to_basic` (TestExitToBasic).  Still
  open: the editor, asm_src, log and addr_mode contracts of this
  item.
- [ ] Bundle hygiene: `test_repl_disk.py` still builds its own
  bare-MPU binary with stubbed disk calls and a map regex (Tranche 4);
  behavioural stubs in `asm_core_test_stub.s` (`log_warn`) and
  `asm_src_test_stub.s` (log, cse_io, editor, gap_buffer routines)
  are outside the mock policy; the mem, log, gap_buffer, symtab,
  breakpoints and cse_io bundles are hand-rolled, not `Bundle`;
  `cse_release_prg` is unused.
  Done 2026-11-18 except Tranche 4: the six bundles are `conftest.Bundle` with `PROD_DEFS` and `-t c64`; the stubs' mocks are recorded in testing.md § Shared slim mocks; `cse_release_prg` feeds test_release_smoke.py.  Open: `test_repl_disk.py` — blocked on a virtual IEC disk (C64Emu models only an empty serial bus).

### Doc drift (to fix in the documentation round)

Stale against the code, by document (each item verified both ways):

- **debugger.md** — next-PC table and RTS/RTI stepping; the
  `_rtu_need_sentinel` description; NMI in kernel mode (refresh, not
  swallow); the `return_to_userland` listing (push order, `$80`);
  `dbg_bp_*` entries and the Memory table (owned by breakpoints.s /
  asm_line.s); seven undocumented exports; the step chain; callers of
  the gate; phantom `dbg_brk_capture` / `dbg_nmi_capture`; "N-iteration
  loop"; the `;!range` gate; SP at entry (−6); `kernel_zp_buf`
  direction; example output; history.
- **breakpoints.md** — `rp_ptr` clobbers; `dbg_bp_set($0000)`; test
  class names.  **mem.md** — Depends-on; history.
- **editor.md** — overflow `>` (normal); Tab is SHIFT+SPACE (also
  test comments); `BUF_FLOOR` computed; strip one leading tab; status
  bar; state and tests now in gap_buffer; `ed_init` not exported;
  workspace map; load can fail; `line_vwidth`; history.
- **gap_buffer.md** — clobber lists; `ed_read_line` 39 + NUL;
  `ed_insert_string`; 36 tests.  **cse_io.md** — `scr_to_pet` mapping;
  `dec_buf[5]`; `io_init`; `io_color`; Depends-on.  **screen.md** —
  default theme GREENLAND; `theme_init`; `$0286`; `$FB–$FE`; source
  comments.
- **asm_src.md** — `_min_pc`/`_max_pc` not exported; `asm_pass` in
  asm_err; `asm_line` not `_asm_line_core`; `.res`/`.align`
  pass-stability; Depends-on; history.  **symtab.md** — SEI/CLI
  snippet; hash before bank-out.  **strings.md** — five undocumented
  labels; aliases; `s_workstart` consumer; `str_qynq`.  **log.md** —
  `log_open`/`log_close` clobbers; `seg_line`/`prg_line`/`free_line`
  inputs; `puts` macro location.  **zp.md** — flag writer/reader
  table; **zp.s** header comment and flag comments.  **dasm.md** —
  `@adj`; Depends-on.
- **asm_line.md** — BSS 5 bytes; `-D` column; profile number; caller
  of `asm_error`; history.  **addr_mode.md** — `(expr),Y`; REL never
  returned; `#` comments; asm_line and Y.  **mn_classify.md** —
  Memory table; mn6 `T[0]`.  **asm_err.md** — callers; 13-byte body.
  **expr.md** — case folding writes the input; clobbers;
  `expr_eval_nb`; `last_err` ≥ 7; Depends-on.
- **repl.md** — the debug-gate matrix (debugger.md is right); `B`
  takes an expression; `$` device range, no drive commands; `i` map
  and splash; `cur_addr` default `$0800`; phantom `f`, `>`, `/`;
  `x` and `Q`; `+`/`-` covered; `C`; `m` row format; error examples;
  undocumented exports; Depends-on; test-file descriptions; history.
- **main.md** — BRK longjmp to `reg_sp`; `main_loop_top`;
  `cse_nmi_handler`; `in_userland = $80`; `stop_cooldown` / `warm_cont`
  location; the IRQ early-entry listing; "cold-init handoff";
  undocumented exports; Depends-on.  **disk.md** — ZP, `cur_device`,
  save path, `floppy_status`; clobbers.  **loader.md** — does not
  bank ROM.
- **memory_design.md** — stack contract (longjmp to `reg_sp`); the
  rejected cold-start sentinel; KBSS not zeroed; I flag around bank
  toggles; flags in ZP; runtime start and slack; mem.s role; KDATA
  1010 B is the reserved window; group tables; ws_buf / `_dasm_buf` /
  line cites / `gap_sz`; warmstart body details; `;!stk` landed;
  `DBG_RTS`; vector early-entry; `workend`; history.
- **architecture.md** — dependency table and rule 7; `asm_src →
  editor` edge gone; `debugger → asm_line`; `dev/check_deps.py` does
  not exist.  **userland_contract.md** — page 3: `$0334–$03FF` is
  free, 204 B (researched 2026-11-18: no KERNAL/BASIC access to
  `$03FC–$03FF`; the "BSOUT save" row has no source); SID control
  registers zeroed whole; first-entry SP `$FD`; stack diagram;
  cold-start sentinel; `;!stk` landed; `j`/`g` gate; CSE's writes to
  `$80–$FF`; sprites; § 5 pointer.  **design_cse_as_kernel.md** —
  status ledger stale; `g`/`o` semantics.
- **glossary.md** — block size; KDATA; BSS zeroing; flags' storage;
  "swallow"; `KERNAL_VECTOR`; cold entry; workend; orphans.
- **README.md** (user manual) — **unsafe** `@ $C000` (inside CSE);
  `b $C010` is rejected; `C` syntax; workstart; gating prompts;
  `;?full`, `;?bad val`, `;?no name`, `;?no ctx`; splash rows;
  fixed tab quirk; `m` rows; `r` syntax; workspace; runtime start;
  `£`; SHIFT+CLR/HOME; `;!N: truncated` and `;!long`; `bad val`;
  error prefix; status bar; patched-byte address; lowercase hex.
  userland_contract.md's hello-world uses ca65 `@l:` locals (CSE:
  `.l`) and omits the `; rts` / register lines of the transcript;
  README's capitals (`$C000`, `LDA`) typed with SHIFT fail — show the
  lowercase convention; `t` cold preview missing from the manual;
  `;?full` also means the breakpoint table; expr.md says no case
  folding but shifted names resolve.
  **assembler_syntax.md** — **unsafe** `.org $c000` ×2; `a = $2000`
  (no such syntax); save line; `; N err`; BASIC stub size; `.bas`
  implies `.org $0801`; default origin.
- **build_system.md** — conftest rebuild; RUNTIME_START formula;
  targets table; `_parse_map`; symbol counts; BUILD_FLAGS /
  version.inc / INTROSPECT; `oplen_tbl` has no per-CPU block; size
  figures; size-gate growth procedure.  **testing.md** — phantom
  `test_debugger.py`; finished migrations; `_AC_FLAGS`; bundle table;
  `oplen_tbl` claim; mock policy vs stubs; MID-RISK tier; xfail
  convention; dead `cse` fixture recipe; C64Emu API details.
  **project_layout.md** — phantoms (`tests/retired/`,
  `build/6510/`) and about 60 unlisted paths.  **vice_test_plan.md**
  — a closed v0.1 checklist.  **optimization.md** — seven stale
  symbols.

### Duplication and layering (systemic; a scoped arc each)

- [ ] Facts restated in many docs, several already contradicting each
  other: the ZP allocation table, the KERNAL-RAM banked layout, the
  interrupt vectors, the stack contract, the cold-init sequence, the
  user memory regions, the cross-module flags, the `dbg_reason` enum,
  the breakpoint table, warmstart bodies, the runtime start address.
  Keep one owner each; the copies become pointers.
- [ ] memory_design.md restates module interfaces (mem.s exports,
  loader steps, warmstart bodies, `return_to_userland` and the BRK
  handler) — move to the module docs, keep the invariants.
- [ ] The user manual carries mechanism (gap buffer, internal names,
  runtime start) and lacks a REPL-keys table; project.md and the
  glossary restate addresses and sizes.
- [ ] Missing guidance for agents: the REPL command-dispatch table
  and handler entry contract (`rp_ptr`, `try_expr`'s C=0 meaning, the
  one-jsr-deep rule, the repeat list); the asm_src directive switch
  and its helper contracts (`_emit_byte`, `emit_error`,
  `_bad_val_err`, `_vocal_fwd_err`); the asm_src test input format;
  the size gate's growth procedure.
- [ ] Audit tooling: `audit_doc_depends_on.py` checks only doc →
  import (add import → doc); `dev/check_deps.py` (architecture.md
  cites it) does not exist.

## Bugs

Open bugs, roughly ordered by priority.

- [x] ~~**BUG** `m` dump line is not re-executable — cursor-up
  + RETURN on a memory-dump row logs `;?syntax`.~~  (v0.1-rc3
  VICE-testing fix, 2026-05-05.)  Cursor-up onto an `m` dump
  line and pressing RETURN logged `;?syntax` instead of
  re-writing the 8 bytes.  The `m` edit path's
  `_require_eoi_or_err` correctly rejected the trailing ASCII
  column as garbage — but the dump format was the problem:
  `emit_mem` separated hex from ASCII with a single space,
  leaving no comment marker.  Fix: swap the space for `;`
  (same width, since the line is already at 39/40 cols).
  `_require_eoi_or_err` recognises `;` as valid EOI, so the
  trailing ASCII column is treated as a comment.

  - **`src/repl.s::emit_mem`** — `lda #' ' / jsr io_putc` →
    `lda #';' / jsr io_putc`.  Single-byte swap; output line
    width unchanged.
  - **`tests/integration/test_repl.py::TestMemoryEdit::test_m_dump_line_is_re_executable`**
    — regression test that feeds the literal dump-line shape
    `m 2f 36 00 00 00 00 00 00;/6......` to exec_line and
    asserts the 8 bytes are written.
  - **`doc/modules/repl.md`** — output-format description
    updated to show the `;` separator and explain the
    re-executability contract.
  - **Cost:** zero source bytes.

- [x] ~~**BUG** Disassembling KERNAL ROM (`$E000-$FFFF`) produces
  only "BRK" / "..." instead of real instructions.~~  (v0.1-rc5
  VICE-testing fix, 2026-05-02.)

  **Symptom.**  `d $E000` (or any address `>= $E000`) shows every
  byte as the BRK opcode (or `...` from filler $FF), regardless of
  what's actually in KERNAL ROM.

  **Root cause.**  `dasm_insn` (`src/dasm.s`) banks KERNAL OUT at
  entry so its internal tables — `mn_modes`, `mode_offset`,
  `dasm_mne_str` — which live in the KDATA segment under KERNAL
  ROM are accessible.  All `lda (_dasm_ptr),y` reads of the user's
  target address therefore see RAM under KERNAL (mostly $00, hence
  BRK), never the actual ROM bytes.

  **Resolution.**  Snapshot 3 max-insn bytes from the user's
  address into a new BSS buffer `_dasm_in` BEFORE banking out,
  using whatever bank state the caller had in force:

  - At the REPL prompt that's KERNAL-in, so `d $E000` snapshots
    real ROM bytes.
  - Inside `asm_assemble` (kernal_out=1 batch) that's KERNAL-out,
    so user RAM under KERNAL is what the user wrote.

  Either way, the user's "current view" of memory is what gets
  disassembled.  `_dasm_ptr` stays pointing at the user's actual
  address (used by branch-target arithmetic in `_compute_branch_target`
  for `bcc $XXXX` / `bne $XXXX` / BBR / BBS); the 8 byte reads of
  opcode/operand inside the decoder switch from
  `lda (_dasm_ptr),y` (zp,y indirect) to `lda _dasm_in,y` (abs,y
  direct).
  - **`src/dasm.s::dasm_insn`** — pre-bank-out snapshot loop +
    new `_dasm_in: .res 3` BSS slot.
  - **`src/dasm.s` decode + format_operand + cc11 paths** — 8
    reads switched to `lda _dasm_in,y`; the branch-offset read
    in `_compute_branch_target` switches but its `adc _dasm_ptr`
    is preserved so target addresses match the user's PC.
  - **`tests/integration/test_dasm_rom.py`** — new file, 7
    tests against real C64 KERNAL ROM (`$E000`, `$FF8A`, `$FFD2`,
    `$FFE4`).  Pre-fix 6 of 7 fail (length=1, mnemonic="BRK");
    post-fix all 7 pass.  Plus a regression-net test pinning
    `RAM disassembly still works` — the fix didn't break the
    non-ROM path.
  - **Cost.**  +16-18 B per production variant (`abs,y` reads
    are 1 byte longer than `zp,y` indirect, ×8 sites).
  - **Discovered via** v0.1-rc5 VICE testing (2026-05-02).

- [x] ~~**BUG** `a+g+NMI(in kernelland)+g` runs straight into a
  phantom brk on the first replay after the "go? y/n"
  prompt.~~  (v0.1-rc4 VICE-testing fix, 2026-05-01, commit
  `5bd916b`.)  Sequence: assemble code with `a`, run with
  `g`, press RESTORE during user code's CHROUT loop (`NMI in
  kernelland` = NMI lands inside the KERNAL ROM region — the
  user's program had called `$FFD2`), then `g` to run again.
  CSE prompts `;!debug` + `go? y/n`; user confirms; CSE
  appears to immediately hit a brk at the program's start
  address, even though no user code actually executed.
  Subsequent `g` commands work normally (one-shot bug).

  **Root cause.**  `main_loop_top`'s warm-cont path
  (`@live` branch, runs after `cse_end_debug` consumes the
  debug session) did `jsr exec_line; jmp main_loop_top`.
  When the replayed `g` set `run_user_pending = MODE_JUMP`,
  the bare `jmp main_loop_top` re-entered at the top —
  where `@check_post_run` interprets `run_user_pending` as
  a "just-returned-from-userland" signal (its dual purpose,
  the same byte serves both pre-dispatch and post-return)
  and falsely runs `post_run_cleanup` against `brk_pc =
  cur_addr`.  User code never ran.  The RETURN-key path in
  `main_loop @not_enter` had the missing dispatch since
  forever; the warm-cont path didn't.

  **Why "only the first time".**  After the phantom
  cleanup, `dbg_reason` is reset; the user's next `g` goes
  through the regular RETURN-key path, which dispatches
  correctly.

  **Resolution.**  `main.s::main_loop_top @live` now
  replicates the @not_enter post-exec dispatch:

  - Clear `run_user_pending` before `jsr exec_line` so the
    post-exec check sees only what THIS cycle's command
    produced.
  - After `jsr exec_line`, read `run_user_pending`; if
    `MODE_JUMP` → `jmp return_to_userland`; if `MODE_RESUME`
    → `jmp restore_userland_state`; else fall through to
    `jmp main_loop_top` (no userland was requested).

  - **`tests/integration/test_kernel_transition.py::TestWarmCont::test_warm_cont_replay_dispatches_userland`**
    — pre-fix fails with `TimeoutError` (idle in
    `main_loop @wait` after the phantom cleanup); post-fix
    passes (PC reaches user code).
  - **`tests/integration/test_kernel_transition.py::TestNmiKernelMode::test_refresh_preserves_run_user_pending`**
    — contract-pin: cse_refresh deliberately preserves
    `run_user_pending` / `dbg_reason` / `step_state`.  Any
    future change to that contract must flip the assertion.

  **Audit follow-ups** (filed in [§ Architecture](#architecture)):
  - "Split `run_user_pending` into pre-dispatch and post-
    return flags" — removes the dual-purpose ambiguity that
    enabled this bug class.
  - "Close the `cse_refresh` micro-race on `run_user_pending`"
    — the only remaining path where rc4-shape false signals
    can manifest (microseconds-window race; not exploitable
    in practice but worth closing alongside the split).

  **Cost:** +18 B per production variant.

- [x] ~~**BUG** RESTORE-during-CHROUT corrupts KERNAL screen-edit
  state.~~  (v0.1-rc1 VICE-testing fix, 2026-04-30, Approach B
  per the analysis below.)  Symptoms (v0.1-rc1 VICE testing,
  2026-04-29):
  1. In the editor: after RESTORE during a tight `$FFD2` (CHROUT)
     loop (NMI fires inside the KERNAL, e.g. PC=$E9D6), the first
     cursor-up / cursor-down keystroke produces no visible
     movement; the second keystroke moves *two* lines.
  2. In the REPL: cursor movements during line editing become
     erratic — the cursor can drift off-screen, line-wrap
     handling misbehaves, characters appear at wrong columns.

  **Root cause (working hypothesis).**  KERNAL CHROUT mid-write
  maintains transient state across several zero-page bytes:
   - `$D5` (LNMX) — current logical-line max column, mid-update
     during line wraps.
   - `$D9–$F1` (line-link table, 25 bytes) — flips $80 ↔ 0 to
     mark logical-line starts; mid-write may have a partial
     update.
   - `$D8` (QTSW) — quote-mode flag, toggled by `"` chars.
   - `$D4` (INSRT) — insert-mode pending count.
   - `$CE` (GDBLN) — char under cursor, used by blink and
     by `^` (CHR$(94)) handling.
   - `$C6` (NDX) — keyboard buffer count; a key typed *during*
     the interrupted CHROUT sits here unconsumed.

  When CSE's NMI handler `cse_nmi_handler` (`src/main.s`
  line 944) is in kernel mode (`in_userland=0`), it `jmp`s
  directly to `cse_refresh`, which calls `reset_screen` →
  `io_sync` (KERNAL PLOT).  PLOT resets `$D1/$D2/$D3/$D6/$F3/$F4`
  but does **not** touch `$D5`, the line-link table, `$D8`,
  `$D4`, `$CE`, or `$C6`.  Subsequent CHROUT / cursor / line-
  editing operations read the stale values and produce wrong
  positions; the buffered key in `$C6` is consumed without
  being routed to the cursor handler in editor mode.

  **Verification path.**  In VICE: monitor-set PC=$E9D6
  (mid-CHROUT), trigger NMI via RESTORE, examine
  `m d5`, `m d9..f1`, `m c6` — confirm transient values
  visibly survive `cse_refresh`.

  **Proposed approaches** (one named alternative each, per
  CDD Method Step 2 — pick before implementing):

  - **A. Defer NMI dispatch in kernel mode.**  Re-introduce a
    `nmi_pending` flag (the Phase-18 swallow-in-kernel model
    eliminated this; reversing).  `cse_nmi_handler` while
    `in_userland=0` sets the flag and RTIs immediately.  Output
    paths (`io_puts`, `log_line`, `log_close`, `cursor_show`,
    `cursor_hide`) check the flag at safe points and dispatch
    `cse_refresh` from there.  Pros: bullet-proof — atomic
    CHROUT semantics restored; no KERNAL-state archaeology
    needed.  Cons: reverses Phase-18 decision; RESTORE response
    is delayed until next safe point; adds polling overhead at
    every output point; needs an audit of every output path.

  - **B. Sanitize KERNAL screen-edit ZP on `cse_refresh`.**
    Extend `reset_screen` (or its caller) to explicitly reset
    `$D5 ← 39`, `$D9-$F1 ← $80` (25 bytes, every row a logical-
    line start), `$D8 ← 0`, `$D4 ← 0`, `$CE ← 0`, `$C6 ← 0`
    before `io_sync`.  Pros: local, surgical, ~30 B; no
    architectural change.  Cons: requires correctly enumerating
    every KERNAL ZP byte CHROUT touches — the list above is a
    best-effort survey and could be incomplete; future KERNAL
    CHROUT changes (none expected on stock C64) wouldn't be
    covered.

  Recommendation: **B for v0.1-rc2**, with A as a follow-up
  candidate if rc2 testing surfaces residual cases B doesn't
  catch.  B's downside (incomplete enumeration) is testable —
  if we list a byte CHROUT touches and don't cover it, the
  symptom remains and we add the byte.

  **Resolution (Approach B, third-landing 2026-05-01).**

  This bug went through three landings before reaching the right
  call site — a worked example for the Phase-25 CDD Log
  amendment "A1 Agent-finding verification principle" (don't
  trust enumeration without a probe).

  - **rc2 attempt 1 (2026-04-30, commit 207a704):** put
    `kernal_screen_reset` inside `reset_screen`.  Regressed
    userland CHROUT positioning during repeated `g` runs —
    cold init and the `x` command also call `reset_screen`,
    neither of which has a mid-CHROUT KERNAL state to recover
    from.  Wiping LDTB1 / `$D5` on those paths left KERNAL's
    line-link view disagreeing with the displayed content.
  - **rc2 attempt 2 (2026-04-30, commit f53f2f7):** narrowed
    to `refresh_body` (cse_refresh / kernel-mode NMI dispatch).
    No regression but cursor still janky — symptom unchanged.
    The fix wasn't actually running on the bug's path.
  - **rc3 attempt 3 (2026-05-01, this entry):** root-caused via
    py65 probe.  CSE's own screen output (`io_putc`) writes
    screen RAM directly and bypasses KERNAL CHROUT entirely,
    so kernel-mode NMI cannot corrupt KERNAL ZP.  The rc1
    scenario is *userland* NMI: user's program calls `$FFD2`
    in a loop, RESTORE fires NMI inside KERNAL at `$E9D6`,
    dispatch goes through `cse_nmi_handler @userland_nmi →
    save_userland_state → handler_finalize →
    hygiene_after_userland → main_loop_top` — never through
    cse_refresh.  Mechanism witness via
    `tests/integration/test_screen.py::TestPlotAgainstCorruptLdtb1`:
    PLOT(10, 5) with corrupt LDTB1 lands on row 9 col 45
    instead of row 10 col 5, reproducible in py65 against the
    real C64 KERNAL ROM.
  - **`src/screen.s::kernal_screen_reset`** — exported helper
    that resets `$C6/$D4/$D5/$D8/$CE` to post-init values and
    rewrites the 25-byte line-link table at `$D9-$F1` to all
    `$80`.  PLOT-set bytes (`$D1/$D2/$D3/$D6/$F3/$F4`)
    deliberately untouched — the following `io_sync` sets them.
  - **`src/repl.s::hygiene_after_userland`** — calls `jsr
    kernal_screen_reset` immediately before its tail-call to
    `io_sync`.  Replaces the prior manual `lda #0; sta $C6`
    drain (kernal_screen_reset clears $C6 anyway).
  - **`src/main.s::refresh_body`** — restored to the pre-rc2
    shape (no kernal_screen_reset call).  Kernel-mode NMI
    cannot have mid-CHROUT KERNAL state to recover from
    because CSE bypasses KERNAL CHROUT for screen output.
  - **`src/screen.s::reset_screen`** — unchanged from rc1; a
    regression-net test pins this.
  - **`dev/repl_test_stub.s::kernal_screen_reset`** — no-op
    stub so the repl test bundle links (real-screen-ZP
    contracts are pinned in test_screen.py against the real
    screen.o, not the bundle).
  - **`tests/integration/test_screen.py::TestKernalScreenReset`**
    — 7 contract tests on the helper itself.
  - **`tests/integration/test_screen.py::TestPlotAgainstCorruptLdtb1`**
    — 3 mechanism-witness tests demonstrating the rc1 jank
    (PLOT lands wrong with corrupt LDTB1) and the defence
    (kernal_screen_reset before PLOT recovers).
  - **`dev/probe_chrout_zp.py`** + **`dev/probe_plot_with_corrupt_ldtb1.py`**
    — investigation scripts that produced the root-cause
    diagnosis.  Kept as future reference for similar
    "enumeration vs probe" debugging.
  - **`doc/modules/screen.md`** — `kernal_screen_reset`
    section rewritten with the user-NMI scenario, the
    mechanism witness pointer, and the historical detour
    (three landings before it landed right).
  - **Cost:** +27 B per production variant (rc2 size unchanged
    — moving the call site preserves byte count, the
    optimisation in commit 44754fd already shaved 4 raw B).
  - **Generalisation candidate:** see [§ Architecture](#architecture)
    for the C-split TODO that promotes the pattern from a fixed
    enumeration into a buffered swap (covers any KERNAL byte in
    the `$C0-$FF` zone, not just the enumerated ones).

- [x] ~~**BUG** Expression parser: symbols cannot start with a
  capital (SHIFTed) letter.~~  (v0.1-rc1 VICE-testing fix,
  2026-04-29.)  In `src/expr.s::parse_factor::@chk_label`, the
  first-character classifier tested only `$41-$5A` (unshifted
  PETSCII letters) and rejected anything outside that range.
  The continuation loop `@lscan` already folded shifted-uppercase
  `$C1-$DA → $41-$5A` in-place, but the entry check did not — so
  a symbol whose first byte was a SHIFT+letter on the C64
  keyboard (`$C1-$DA`) failed with `;?<line>: expected` before the
  fold ever ran.  Affected every consumer of `expr_eval`: the
  source assembler operand parser, the `.` REPL command, `.const`
  values, `.org`, `.dw` / `.db` lists, etc.  Label *definitions*
  were unaffected (asm_src calls `fold_block` before
  `define_label`).  Found during VICE user-testing of v0.1-rc1.
  - **`src/expr.s::parse_factor::@chk_label`** — fold inserted
    before the `$41-$5A` range check, mirroring `@lscan`'s
    in-place fold pattern (sta back so `sym_lookup` sees the
    folded byte).
  - **Tests** — 5 new POSITIVE entries in
    `tests/unit/test_expr.py` exercising uppercase / mixed-case
    first chars (`START`, `Start`, `TOP`, `PORT+1`, `<PORT`) —
    `_petscii()` already encoded `A-Z → $C1-$DA`, so the test
    inputs map straight onto the failing path.  Pre-fix all 5
    failed with `rc=ERR_EXPECTED`; post-fix all 5 pass.
  - **Cost:** +15 B per production variant for the inline fold
    (6510 21159→21174, 6502 20717→20732, cmos 21613→21628).

- [x] ~~**BUG** Source assembler: `;<line>: truncated` warning
  never fires.~~  (Phase 25 fix.)  In `asm_src.s::do_pass`,
  `txa` clobbered the length returned by `ed_read_line` (A=lo,
  X=hi=0 for non-EOF) before the saved-for-truncation `pha`.
  The subsequent `cmp #39` always saw 0, so `bne @no_trunc`
  always took and the truncation log line was dead code.  Lines
  ≥39 chars were silently truncated.  Found during the
  optimization-round pha/pla audit 2026-04-28.
  - **`src/asm_src.s::do_pass`** — `pha` now precedes `txa` so
    the length is saved before A is clobbered with the sign byte;
    EOF takes a new `@done_pop` trampoline that pulls and falls
    into `@done`.
  - **`dev/asm_src_test_stub.s`** — log_open stub now increments
    `_warn_witness` on `LOG_WARN` calls (only path that triggers
    inside asm_src is the truncation warning), giving tests a
    counter.
  - **Tests** — `TestTruncationWarning` (3 cases) in
    `tests/unit/test_asm_src.py`: 38-char line emits 0 warnings,
    39-char line emits 1, two 39-char lines emit 2.  Pre-fix all
    three would have asserted 0 (regression net for the silent-
    drop bug).
  - **Cost:** +1 B per production variant (the new `pla` at
    `@done_pop`).
  - **Test suite:** 3112 passed / 18 skipped.

- [x] ~~**★ HIGH — Cold-init silently faults and recovers on CMOS;
  6510 build is fully broken in test path.**~~  **Closed
  2026-04-27, Phase 24.**  Fixed by:

  - **F1** (commit d9cac91 — *Phase 24 F1: order sym_clear before
    ed_ensure_init in cold init*).  Reorders `_main` cold-init
    so `sym_clear` precedes `ed_ensure_init`.  `_st_heap` is
    valid by the time `gb_init`'s tail-call to `update_workend`
    fires; `heap_copy_name` writes to SYM_HEAP ($E600) rather
    than $0000-$0007; the `$01` corruption + BASIC-shadow BRK
    chain is gone.
  - **F2** (this commit — *Phase 24 F2: …*).  Removes
    `gb_init`'s `jmp update_workend` tail-call (gb_init becomes
    a pure leaf with no symbol-table contact); lifts the
    workend publication to `editor.s::ed_init` as an explicit
    `jmp update_workend` tail-call.  Eliminates the layering
    inversion (gap buffer reaching into the symbol table) that
    let the bug exist.

  Net code delta: gap_buffer.s -2 B (jmp→rts), editor.s +3 B
  (added jmp), main.s ±0 B (reorder).  Total +1 B.

  Tier I tests pinning the new contract (testing.md
  Principle 16, *Cold-init terminal-state assertion*) added
  in `test_kernel_transition.py::TestColdInitTerminalState`:
  no-BRK/no-recover, workstart/workend resolvable, $0000-$0007
  uncorrupted, free-ZP `$FF` fill, free-workspace `$00` fill.
  Tier U test pinning F2's leaf contract added in
  `test_gap_buffer.py::TestGbInitLeaf`.

  Verification: full suite 3057 passed / 18 skipped; the 17
  previously-fragile tests now stable green.  6510 build no
  longer enters the BASIC ROM shadow during cold init (the
  fault chain is gone in all variants because the corruption
  itself is gone).  Multi-CPU integration-test parity is
  tracked separately under § Architecture as a follow-up.

  Original symptom + RCA preserved below for the audit trail.

  ### Original RCA (pre-fix)

  #### Symptom

  After `_cold_init_to_prompt(emu)` runs against the production
  CMOS PRG via the integration-test harness, `$01` reads `$36`
  and tests pass.  Pretty-printed banking looks normal.  But the
  intended `_main` flow has not actually completed — control has
  jumped through a kernel-fault recovery path and arrived at
  `main_loop_top` via an entirely different route than `_main`'s
  source code suggests.

  The 17-test fragility under `_cold_init_to_prompt` (previously
  attributed to a py65 step-engine edge case) is in fact this
  bug: the fault chain is layout-dependent because the byte
  patterns in BASIC ROM determine whether the BRK fires cleanly,
  whether `cse_brk_handler` reaches `cse_recover` cleanly, and
  whether `cse_recover`'s subsequent path stays out of the
  shadow.  Real silicon and VICE were never tested against this
  flow because both auto-bank correctly via the `$01` write CSE
  *thinks* it's making — but on emulator + py65 the wild ride
  through BASIC ROM bytes is observable.

  #### Reproduction

  Three probes against `build/debug/cmos/cse-cmos.prg`:

  **Probe 1** — `_cold_init_to_prompt`, then read `$01`:
  ```
  After cold-init: PC=$7C94 (main_loop_top) $01=$36
  ```
  Looks normal.

  **Probe 2** — same, hooking every write to `$01`:
  ```
  [0] save_zp+0xf            $36 →  $36
  [1] kernal_bank_out+0x9    $36 →  $34
  [2] heap_copy_name+0xd     $34 → ★$4F   ← corruption
  [3] kernal_bank_in+0x9     $4F →  $47   ← LORAM=1, BASIC banked IN
  [4] hw_reinit_body+0x3     $47 → ★$36   ← fault recovery resets $01
  ```

  **Probe 3** — same, watching for CPU entries to fault paths:
  ```
  cyc=1137  $A4F4   BRK at define_ws_syms+0x1
  cyc=1148  $7EBD   enter cse_brk_handler  in_userland=0 → fault
  cyc=1151  $7F8C   enter cse_recover
  cyc=1157  $7FC3   enter hw_reinit_body
  cyc=6464  $7C94   REACHED main_loop_top
  ```

  #### Full chain

  1. **Order bug in `main.s` cold-init.**  Line 224 calls
     `ed_ensure_init` before line 227 calls `sym_clear`.
     `ed_ensure_init` → `gb_init` → `update_workend` →
     `sym_define` → `heap_copy_name`.  `heap_copy_name` reads
     `_st_heap` (zp `$3D-$3E`) which is BSS-zero ($0000) at this
     point — `sym_clear` hasn't run.  The inner copy loop
     `sta (_st_heap),y` writes the source name `"workend\0"`
     across `$0000-$0007`.

  2. **DDR + CPU-port corruption.**  `$0000` (DDR) gets the first
     name byte ($57 = `'W'` screen-code).  `$0001` (CPU port latch)
     gets the second ($4F = `'O'`).  After the next
     `kernal_bank_in` ORs bit 1 in, the latch is `$47`: LORAM=1
     (BASIC banked IN), HIRAM=1, CHAREN=1, plus stray bit 6.

  3. **`define_ws_syms` falls in the BASIC shadow.**  At
     `main.s:228` the next instruction is `jsr define_ws_syms`.
     `define_ws_syms` lives at `$A4F3` (CMOS) — inside `$A000-$BFFF`.
     With LORAM=1 the CPU fetches BASIC ROM at `$A4F3`, not the
     real `define_ws_syms`.  BASIC ROM byte at offset `$04F3` is
     a one-byte instruction; PC advances to `$A4F4`; BASIC ROM
     byte at offset `$04F4` is `$00` → BRK fires.

  4. **Kernel-mode BRK trap.**  `cse_brk_handler` reads
     `in_userland`, finds it `0`, takes the kernel-fault branch:
     `jmp cse_recover`.

  5. **Fault recovery as accidental cold-init.**  `cse_recover`
     resets SP to `$FF`, calls `hw_reinit_body` (which writes
     `$36` to `$01` — fixing the banking — then runs
     `setup_interrupts`, `dbg_init`, `reset_globals`, `io_init`,
     `theme_init`, `restore_colors`, `set_charset`), then
     `end_debug_body`, then `refresh_body`, then
     `jmp main_loop_top`.

  #### What this means

  **`main.s` cold-init never reaches lines 227+ on CMOS.**  The
  intended cold-init flow from `sym_clear` onward (sym_clear,
  define_ws_syms, CPU-mode default, free-ZP fill, free-workspace
  fill, the splash sequence, the first userland transition,
  global state init) is dead code in practice.  The production
  CMOS build always cold-boots through the recovery path.

  **6510 build is broken differently.**  Probe against
  `build/debug/6510/cse.prg` shows the same corruption (writes
  [0]–[3] identical) but no write [4] — `hw_reinit_body` never
  fires because the BASIC ROM bytes at 6510's `define_ws_syms`
  address don't produce a clean BRK.  `$01` stays at `$47`.
  `dbg_bp_clear` (`$A226`) and `return_to_userland` (`$A333`) are
  in the shadow and unreachable; the CPU times out wandering
  through BASIC ROM.  Integration tests don't exercise the 6510
  PRG so this is currently invisible.

  **Test suite is only green because** the integration tests
  use only the CMOS PRG, and CMOS happens to fault in a way
  that recovers cleanly.  Layout shifts that change BASIC ROM
  byte patterns at the affected addresses can:
  - move the fault from the clean `BRK at $A4F4` to a different
    address, possibly one where recovery doesn't reach
    `main_loop_top`;
  - cause the recovery path to itself land in the shadow at a
    bad byte;
  - mask the fault entirely (BASIC ROM byte happens to be a
    benign instruction sequence that returns to RAM).

  This is exactly the "fluctuates pass/fail at $B5xx / $7Dxx"
  symptom the C1 entry described — but it's the *production*
  cold-init that's fragile, not the harness.

  #### Fix candidates

  - **F1 — Reorder cold-init.**  Swap `main.s:224` and `:227`:
    `sym_clear` before `ed_ensure_init`.  Prevents the heap
    corruption, prevents the BRK, prevents the silent recovery.
    One-line change.  Low-risk if the rest of cold-init is sound.

  - **F2 — Decouple `gb_init` from the symbol table.**  Remove
    the `jmp update_workend` tail call from `gap_buffer.s::gb_init`.
    Make `update_workend` an explicit call at every cold-init /
    `ed_new` / disk-load site.  Cleaner separation of concerns.
    Subsumes the F1 fix.  More call-site churn.

  - **F3 — Defend `heap_copy_name`.**  If `_st_heap < SYM_HEAP`,
    refuse to write or fall through to `sec; rts`.  Mask only;
    doesn't fix the upstream ordering issue.  Useful as a
    belt-and-braces against future regressions.

  #### Phased landing plan

  Per session CDD Method.  Each phase has an explicit gate.

  **Phase 0 — Read past `main.s:266`.**  Tabulate everything
  `_main` does between line 227 (`sym_clear`) and the final
  `jmp main_loop_top`.  Tabulate everything `cse_recover` does
  between its entry and its `jmp main_loop_top`.  Diff the two.
  The diff is the body of state changes that **today never
  occur on CMOS cold-init**.  Outcome: a delta table that
  predicts what F1 will newly observe.

  **Phase 1 — Predict latent issues from the delta.**  For each
  delta entry, decide: (a) does it matter?  (b) does any test
  assert it post-cold-init?  Likely candidates for surprise:
  - free-ZP fill with `$FF` (lines 237–244)
  - free-workspace fill with `$00` (lines 246–259)
  - the splash + first-userland-transition pair (after line
    266, unread)
  - the symbol table actually getting a real `workstart` /
    `workend` instead of corrupted `$0000` ZP pointers

  **Phase 2 — Apply F1.**  One-line swap.  Run the full test
  suite.  Triage any new failures: they're the latent issues
  Phase 1 predicted (or didn't).

  **Phase 3 — Decide F2.**  After F1 is green, evaluate whether
  `gb_init`'s tail call to `update_workend` should be removed.
  `gb_init` is called from at least three places (`ed_init`,
  `ed_ensure_init`, and possibly disk-load); each needs an
  explicit `update_workend` if F2 lands.

  **Phase 4 — Escape Analysis pass.**  This bug class —
  *layout-dependent silent fault during cold-init recovers
  transparently and the test suite reads recovery state as if
  it were intended behaviour* — escaped because:
  (a) tests don't compare cold-init paths against expected
      sequences;
  (b) `cse_recover` is too willing to act as a cold-init
      fallback (it runs the full hw_reinit + soft-reset
      sequence, which is everything cold-init needs);
  (c) the test suite runs only CMOS, so the 6510 break is
      invisible.

  Candidate principles to amend (testing.md / README.md):
  - **Cold-init terminal-state assertion.**  `_main` must
    reach `main_loop_top` without `cse_brk_handler` or
    `cse_recover` ever being entered.  Asserted by a Tier I
    test that hooks both entry points and fails if either
    fires during cold-init.
  - **Sequence-prerequisite declaration.**  Modules whose
    entry points depend on prior init (e.g. `gb_init` requires
    sym table to be initialised because of its tail call) must
    declare the prerequisite in their module doc and assert it
    in tests if any caller could violate it.
  - **Multi-CPU integration-test parity.**  At least one
    integration test should run against each production PRG
    variant (6502/6510/cmos), not just CMOS.  Otherwise CPU-
    specific cold-init breakage is invisible.

  #### Latent issues F1 may surface

  After F1 lands, anything `_main` 227+ does that `cse_recover`
  doesn't may newly become observable.  Known differences:

  | Step | What `_main` does (line) | Done by `cse_recover`? |
  |------|--------------------------|------------------------|
  | `sym_clear` (227) | clears 256 hash slots, resets `_st_heap` | **No** |
  | `define_ws_syms` (228) | defines `workstart`/`workend` | **No** |
  | `sta asm_cpu` (234) | sets default CPU mode | maybe via `reset_globals` — verify |
  | free-ZP fill `$FF` (237–244) | scratch sentinel | **No** |
  | free-workspace fill `$00` (246–259) | clears user RAM | **No** |
  | `io_init`, `theme_init` (262–263) | I/O + theme | **Yes** (in `hw_reinit_body`) |
  | `reset_screen`, `set_charset` (264–265) | screen + charset | **Yes** (in `hw_reinit_body`) |
  | rest (266+) | unread; tabulate in Phase 0 | ? |

  #### Investigation artifacts

  Probes used during the 2026-04-25 RCA (now removed but
  reproducible):

  - `_rca_probe.py` — confirm `$01=$47` after cold-init, trace
    8 instructions from `return_to_userland`.
  - `_rca_probe2.py` — hook every `$01` write during cold-init,
    log the call site.
  - `_rca_probe3.py` — capture `_st_heap` at the moment of the
    offending `sta (_st_heap),y`.
  - `_rca_probe4.py` — log every write to `$3D`/`$3E` during
    cold-init (proves `sym_clear` runs *after* the corruption).
  - `_rca_callchain.py` — watch every CPU step for entries to
    `cse_brk_handler`, `cse_recover`, `hw_reinit_body`; dump
    BRK frame to identify origin.

- [x] ~~Disable C64 SHIFT+C= mode switch on CSE init~~ (fixed: main.s)
- [x] ~~`i` command output shows stale memory map~~ (fixed: repl.s
  tail table now shows sym $E000-$EEFF, cse $EF00-$F8D9 banked,
  rom $F8DA-$FFFF instead of single rom $E000-$FFFF)
- [x] ~~`.const FOO` then `sta FOO` not found~~ (fixed: expr.s label
  scanner now folds $C1-$DA → $41-$5A in-place; shifted uppercase
  letters from the lowercase/uppercase charset are accepted)
- [x] ~~Uppercase REPL commands parsed as lowercase.~~  (fixed:
  `scr_to_pet` now maps screen code $40–$5F → PETSCII $C0–$DF.
  Latent bug from Phase 6 — `read_line`'s screen→PETSCII
  conversion always collapsed uppercase into the lowercase
  range.  Dispatch table entries $C2/$C3/$D1 were unreachable.
  Phase 17)
- [x] ~~INS in REPL: overwrites char under cursor~~ (fixed: main.s
  INS shift loop had off-by-one — `beq` exited before copying the
  char at cursor position; removed the early exit)
- [x] ~~`?` calculator wrong decimal for >= $2000~~ (fixed: repl.s
  `put_dec5_sp` replaced with `io_putdec` delegation; `utoa_sub`
  rewritten with pha/pla pattern from io_putdec)
- [x] ~~`a` save line writes filename "oup"~~ (fixed: asm_src.s
  seg_print_save now checks for `,s` suffix before poking; if no
  suffix, appends `,p` instead of overwriting last char)
- [x] ~~`l "out,p" $2000` doesn't load to $2000~~ (fixed: disk.s
  SETLFS secondary address was inverted — SA=0 means use X/Y addr,
  SA=1 means use PRG header addr; code had them backwards)
- [x] ~~RUN/STOP debounce~~ (already debounced: `@deb_wait` polls
  $91 until key released, then drains keyboard buffer)
- [x] ~~`.` and `m` show CSE ZP instead of user ZP after j/debugger
  context.~~  (Phase 19 — fixed: unified user-ZP redirect for
  both read and write across `m` and `.` via `zp_stage_prep` /
  `zp_poke` helpers in repl.s.  See [repl.md § User-ZP view](modules/repl.md#user-zp-view).
  Inline mnemonic assembly into ZP during a break remains
  unredirected by design — the hex-poke form handles the real
  use case.)
- [x] ~~**CRITICAL**: save writes wrong memory region~~ (fixed:
  disk.s had a local `_io_tmp = $FB` shadowing the canonical
  symbol in zp.s at `$2D`.  Commit `278a2f6` changed repl.s's
  `sta $FB` → `sta _io_tmp` which resolved to `$2D`, but
  disk.s still read from `$FB`.  Fix: removed the local
  define; disk.s now imports `_io_tmp` from zp.s.  Phase 17.)
- [x] ~~One too many newline before floppy status~~ (fixed:
  disk_done's `log_close` was redundant — callers (prg_line,
  log_err) already close their line with a newline.  Phase 17.)
- [x] ~~l/s accumulates `,p,p,p...` in cur_filename~~ (fixed
  twice in Phase 17.  First pass: `seg_print_save` recognised an
  existing `,p` suffix.  Final fix: the project-name refactor —
  `cur_project_name` stores a clean stem (no suffix, no trailing
  dot), so accumulation is impossible at the source.  See the
  "Refactor internal default filename" item below.)
- [x] ~~`r` command flags decode: the dash becomes a strange char~~
  (fixed: added `cmp #'a'; bcc @fp` before the `and #$DF` so
  non-alphabetic chars like `-` pass through unchanged.  The
  dash now displays as `-` regardless of P-bit state.  The
  deeper convention/flip bug is tracked separately.  Phase 17.)
- [x] ~~`r` command flags handling inverted/broken~~ (fixed:
  display now `cmp #'a'; bcc; ora #$80` for alphabetic letters
  only (lowercase → canonical uppercase $C0-$DF); parser now
  sets bit=1 only when typed char is uppercase ($80 bit set
  after scr_to_pet fold).  Lowercase → bit=0, dash or missing
  → bit=0.  Input is position-based: each slot checks only its
  own flag letter.  Userland update works automatically via
  `@tramp` in dbg_enter which reads reg_a/x/y/p at JSR-to-
  user-code time.  Phase 17.)
- [x] ~~NIT: `.bas` stub lacks a space after `REM`~~ (fixed:
  asm_src's emit_bas now emits a space byte between the REM
  token and the string text.  Stub length adjusted +1.  Phase 17.)
- [x] ~~NIT: unsaved-changes prompt appears twice~~ (fixed:
  merged `check_unsaved` and per-command prompts into a shared
  `confirm_action` helper.  `k`, `q` show `"; del src? y/n"` /
  `"; quit? y/n"` when clean, `";!unsaved. del src? y/n"` /
  `";!unsaved. quit? y/n"` when dirty.  LOG_WARN level when
  dirty, LOG_INFO when clean.  Phase 17.)
- [x] ~~`s:name` overwrite~~ (fixed: PRG save now uses OPEN+CHKOUT+
  CHROUT+CLOSE like SEQ save, with `"@:<name>,p,w"` constructed
  via the shared `build_open_str` helper.  Both paths now have
  symmetric KERNAL call structure and consistent overwrite
  semantics.  PRG payload writes a 2-byte load-address header
  then the bytes.  `build_open_str` generalised to take type
  ('s' or 'p') in X in addition to mode in A.  Phase 17.)
- [x] ~~Debugger: stepping into a subroutine then `c` (continue)
  cannot return through the original JSR's pushed return address.~~
  (fixed via the Phase 18 shared-stack model: user and kernel share
  the hardware stack; kernel never writes below user's SP, so JSR
  return addresses pushed during stepping stay intact across
  break/resume cycles.  The old two-image swap design was
  superseded before implementation.  See
  [memory_design.md § Stack contract](memory_design.md#stack-contract).)
- [x] ~~Assembler: `bne <nonexisting>` reports "bad insn"~~ (fixed:
  `asm_expr_error` entry point sets `asm_expr_err=1`; `.` command
  and source assembler now print `expr_error_str` detail e.g. "undef")
- [x] ~~**TDD Maintenance finding** (Principle 13 sweep 2026-04-20):
  `editor.ed_read_line` has no position-pinning witness.~~  (resolved
  via option b: four new test methods in
  `tests/integration/test_editor.py::TestEdReadLine` pin read_ptr
  advancement — exact-delta for CR-terminated lines, empty-line
  edge case, no-CR-last-line scan-to-EOF behaviour, and post-EOF
  idempotency.  The contract in editor.md was also tightened:
  the earlier "at EOF returns without advance" phrasing was
  imprecise — the *first* EOF call may advance (to cross the gap
  and reach BUF_END); what callers rely on is that subsequent EOF
  calls are idempotent.  Closes L4 TDD parity with L0–L3.)
- [x] ~~**BUG** (class-wide, Escape Analysis 2026-04-20): REPL commands
  that take a single expression silently accept trailing garbage.~~
  (resolved: extracted `_require_eoi_or_err` helper in repl.s and
  applied to `@` (seek), `B` (block size), `C` (color), and `j`
  (jump) — all now reject trailing non-whitespace/non-comment
  content as `;?syntax`.  Tests parametrised in test_repl.py across
  TestAddressCommands / TestBlockSize / TestColorCommand /
  TestCalculator.  repl.md § Single-expression command contract
  updated to list all five commands (`?` `@` `B` `C` `j`) as
  covered.  Remaining: `+` and `-` share the class but are
  complicated by their `expr_or_blocksize` fallback — tracked as a
  follow-up below.)

- [x] ~~**Escape Analysis follow-up** (Principle 11 class closure):
  apply the `_require_eoi_or_err` pattern to `+` and `-`.~~
  (resolved: commit 805ece5 added an unconditional EOI check after
  `expr_or_blocksize` in both `@h_plus` and `@h_minus`.  The double-
  error concern in the original entry turns out to be narrower than
  feared — `try_expr` advances `rp_ptr` past the expression even on
  error, so the EOI check on `+ undefsym\0` sees NUL at rp_ptr and
  passes silently (one error only).  Double-error only fires on
  `+ undefsym GARBAGE` where there's actual trailing content after
  the bad expression — acceptable: the user typed two distinct
  errors and gets one complaint per.  The same migration also
  covered `t`/`o` (via `try_expr_or_err` wrapper — see § 37 of
  optimization.md), `b ADDR`, `m` (both @dump and @ed_done),
  and `d`.  Full Principle 11 class closure on single-expression
  commands.)

- [x] ~~**BUG** Disk: `l "foo` (filename with missing closing quote)
  errs `;?expr undef` but loads the file anyway.~~  (Phase 25 fix.)
  Root cause: `parse_filename` (repl.s) treated NUL during the
  scan-for-closing-quote loop as a successful close.  The "name"
  was extracted (`"foo"` between opening quote and NUL) but
  `rp_ptr` was *not advanced* past it, so `parse_ls_args` then
  re-parsed the same bytes via `try_expr` — which raised
  `;?expr undef` on the undefined symbol `foo` while
  `parse_filename` had already declared success and the load
  proceeded with name `FOO`.  Two layered defects: wrong error
  class (expr undef vs syntax), and load-despite-error.
  Resolved by:
  - **`src/repl.s`** — `parse_filename` splits the NUL-during-scan
    path from `@close`: NUL → `@unterm` (new), which uses the
    multi-level pop-trick (extension of optimization.md § 36) to
    discard three caller frames (`get_filename`, `parse_ls_args`,
    `cmd_load` / `cmd_write`) and tail-jump to `log_err` with
    `str_syntax`.  The `;?syntax` message is emitted; `log_err`'s
    rts pops `main_loop`'s return → next prompt.  No disk I/O.
  - **`doc/modules/repl.md`** — § Argument parsing now declares
    the unterminated-quote rule explicitly.
  - **Tests** — `TestUnterminatedQuote` in
    `tests/integration/test_repl_disk.py` (3 cases):
    `l "foo` → no load, `s "foo` → no save, project name
    untouched after aborted parse.
  - **Cost:** +13 B per production variant.
  - **Test suite:** 3088 passed / 18 skipped (was 3085 / 18).
- [x] ~~**BUG** Assembler: `.dw` / `.db` with a forward-ref label
  silently sizes as zero bytes on pass 0, causing labels defined
  afterward to drift to too-low addresses; pass 1 then emits both
  the data bytes and any jump/branch operands using those wrong
  addresses.~~  (Phase 25 fix — discovered during a PC-advance
  audit, originally suspected by the user but not reproducible
  without targeted tests.)  Root cause: `emit_data_bytes` checked
  `expr_eval`'s rc and tail-jumped to `emit_error` on any
  rc ≥ 2 — including ERR_UNDEFINED — bypassing `_emit_word` /
  `_emit_byte` and their pass-aware PC advance.  Pass 0 errors are
  silent (intended), but the PC advance was a casualty.  Resolved by:
  - **`src/asm_src.s::emit_data_bytes`** — on rc==5 (ERR_UNDEFINED)
    AND pass 0, fall through to the emit path.  `_emit_byte` /
    `_emit_word` skip the store on pass 0 and advance asm_pc by
    `_as_wsize`, so two-pass sizing stays consistent.  Pass 1 +
    undef still errors.  Other error classes (parse, paren,
    overflow, divzero) fall through to `emit_error` unchanged.
  - **Tests** — three new MANUAL_TESTS cases in
    `tests/unit/test_asm_src.py`: `.dw target / target:` resolves
    correctly; `.db <target / target:` (lo-byte forward ref);
    `.dw target / jmp target / target:` (jump across the .dw
    lands at the right address — the user's recollected
    symptom).
  - **Doc** — `asm_src.md` § Design now spells out the pass-0
    forward-ref rules for both instruction operands (via
    `_au_read_val`) and data directives (via `emit_data_bytes`).
  - **Cost:** +9 B per production variant.
  - **Test suite:** 3094 passed / 18 skipped.

- [x] ~~**Sibling bug class** (Escape Analysis sweep — same shape
  as the `.dw` forward-ref drift): `.res N` and `.align M` use
  the expression *value* to determine pass-0 size.~~  (Phase 25
  fix — landed alongside a refinement of the `.db`/`.dw` fix.)
  Resolution: forward refs in `.res`/`.align` are now a hard
  error on BOTH passes (vocal pass 0 + vocal pass 1).  The new
  `_vocal_fwd_err` helper in `asm_src.s` temporarily promotes
  `asm_pass = 1` across the `emit_error` call to bypass the
  silent-pass-0 guard for this specific case; the directive
  aborts (no PC advance) so layout stays pass-stable.  Covers
  count, fill (.res second arg), and boundary (.align).  New
  string `s_fwd_ref` ("fwd ref") in strings.s.  Test coverage:
  three new ERROR_TESTS cases pin the vocal-error contract.

  Same commit also simplified the `.db`/`.dw` fix per design
  feedback: pass 0 size is value-independent for these (every
  arg is exactly `_as_wsize` bytes), so pass 0 skips the rc
  check entirely and just lets `_emit_byte`/`_emit_word`'s
  pass-aware advance handle size — saves the cmp-#5 special
  case from the previous attempt and keeps multi-arg lists
  (`.dw $1234, FORWARD, $5678`) consistent across passes.
  Cost +49 B per variant net; suite 3097 passed / 18 skipped.

- [x] ~~**BUG** Editor: switching to the editor after `l` always
  inserts a tab on entry, even when the buffer already has
  source loaded (so the first line gets a leading tab where it
  shouldn't).~~  (Phase 25 fix.)  Root cause: `enter_editor`'s
  smart-indent seed test checked only `gap_lo == buf_base` ("no
  content before the gap").  After `ed_load_source` the cursor
  is rewound to the start, so `gap_lo == buf_base` holds even
  though loaded content fills `[gap_hi, BUF_END)` — the test
  fired falsely and a tab was inserted into the just-loaded file.
  Resolved by:
  - **`src/editor.s`** — `enter_editor`'s emptiness check now
    requires BOTH halves of the gap envelope: `gap_lo == buf_base`
    AND `gap_hi == BUF_END`.  Both fences must be at their init
    positions for the buffer to be truly empty.
  - **`doc/modules/editor.md`** — § enter_editor step 4 now
    spells out the two-half rule and names the post-`l`
    failure mode as the regression class.
  - **Tests** — `TestEnterEditorSeed` (3 cases) in
    `tests/integration/test_editor.py`: tab seeded only when
    truly empty; not seeded after a simulated load (insert +
    rewind to buf_base); not seeded when content lives before
    the gap.
  - **Cost:** +12 B per production variant.
  - **Test suite:** 3091 passed / 18 skipped (was 3088 / 18).

- [x] ~~**BUG** Debugger: regular RTS from userland with debug
  off prints a bogus `; rts at $<main_addr>` info line~~ — the
  address shown is the j-target (cur_addr the handler reset
  brk_pc to), not the actual rts instruction's location.
  Reproduce: `j main` on a program that returns cleanly; the
  panel reads e.g. `; rts at $0800` even though main's rts
  is at $0814.  Three possible fixes (in order of effort):
    (a) Pure `; rts` (drop the address) — cheapest; clear
        signal that the program returned, no misleading addr.
    (b) Drop the info line entirely, show just the reg dump
        — minimal "session ended" panel.
    (c) `; rts at <real rts addr>` — would need to track the
        actual rts PC at handler entry (before the brk_stub
        reset) and surface it; doable but more state.
  The current behaviour came from the DBG_RTS handler classifier
  (fd1c67b) resetting brk_pc := cur_addr so the disas line in
  the panel showed user-meaningful code; the info-line address
  inherited that reset and now misrepresents.
  (Fixed 1ecc863: option (a) — show_break_result skips the
  " at $PC" emit for DBG_RTS.  Pure "; rts" + reg row.)

- [x] ~~**BUG** Debugger: repeated `t` after a clean-exit RTS
  alternates between `; brk` and `; rts` (visible on tight loops
  like a one-rts test program).  Cause: clean exit lands at
  brk_stub → handler sets DBG_RTS + clears last_cmd.  User must
  type `t` (RETURN no longer repeats).  cmd_step gates DBG_RTS
  to cold-preview path → emits `; dbg`, promotes dbg_reason to
  DBG_BRK, arms cold_preview_done.  Next `t` steps the rts via
  @rts → lands at brk_stub again → DBG_RTS again.  Result: the
  user perceives an alternating `; brk` / `; rts` pattern (the
  `; dbg` cold-preview tag may be misread as `; brk`, or the
  next step's actual `; brk` panel from a non-trivial program
  alternates with the `; rts` clean exit).  Reproduce: tight
  test with `j main / t / t / t / ...` after the program has
  already returned once.  Investigation: cmd_step's cold-preview
  re-firing after every clean exit may be the wrong UX — once a
  session has terminated, perhaps subsequent `t` should be
  rejected entirely (mirroring `c` after DBG_RTS) instead of
  silently restarting.  Or: the cold-preview path could detect
  "this is a re-entry to the same brk_pc" and skip the preview
  emit, going straight to step.  Tied to the broader question
  of "what does `t` mean when the session is terminal?".~~
  (Fixed 1ecc863: cmd_step now rejects t/o on DBG_RTS with
  "; ?no ctx", mirroring cmd_continue.  DBG_NONE still triggers
  cold preview as before; DBG_RTS terminal session needs j/g
  to restart.)

- [x] ~~**Escape Analysis sibling (bug 2)**: enumerate the
  `dbg_reason × command` matrix in doc/modules/debugger.md and
  ensure every cell is specified + tested.~~  (Matrix landed in
  debugger.md § dbg_reason × command matrix; code aligned in
  the same commit.  Three behavioural patterns per command:
  *transparent* (r, l, s, R — no debug gating), *gated by
  reason* (c, t, o), *end-debug-and-replay* (j, g, a — warn,
  ask, end debug, replay command).  Code changes: cmd_jmp got
  the warn+ask gate (covers j and g); cmd_load lost its
  warn_if_debug (l/s now transparent); @h_reset simplified to a
  single "init? y/n" + idempotent end_debug_body.  str_go added
  for the j/g prompt.  Tests still need cell-by-cell coverage —
  separate TODO if pursued.)

- [x] ~~**★ MUST — BUG** Assembler: single-letter label resolution
  fails as an instruction operand, reporting "bad insn".~~  (Phase 25
  fix.)  Root cause: `mode_parse` had a fixed peek-ahead at the
  SC_A character that classified bare `A` as MODE_ACC unconditionally,
  even for mnemonics whose profile rejects ACC (JMP, JSR, LDA, BNE,
  …).  `asm_validate_mode` then errored with `;?bad insn` and the
  defined label `A` was never consulted.  The expression calculator
  worked because it never goes through this peek-ahead — it calls
  `expr_eval` directly.  Resolved by:
  - **`addr_mode.s`** — new `_au_no_acc` BSS flag.  The SC_A path
    is gated on it: profile rejects ACC → `A` falls through to
    label parse.
  - **`asm_line.s`** — sets `_au_no_acc` once per instruction from
    `mn_modes_lo[asm_pidx] & MODE_ACC_BIT`, before zone dispatch.
    Adds an IMP→ACC promotion in zone G/H so bare `ASL` / `LSR` /
    `ROL` / `ROR` (and CMOS bare `INC` / `DEC`) emit the ACC opcode
    without requiring the explicit `A` form.
  - **Shadow warning** — when the user defines `A:` and writes the
    explicit `<acc-mne> A` form, ACC wins (the contract is
    pass-invariant; cannot depend on transient symtab state).
    `mode_parse` calls `sym_lookup("A")` on pass 1; on hit, emits
    `;!a shadow` directly via `log_warn`.  No cross-module flag.
  - **Tests** — four new classes in `test_asm_line.py`
    (TestAccBareForm, TestSingleLetterLabelResolution,
    TestAccLabelShadow, TestNoAccFlagSetByAsmLine) — 25 cases
    pinning the matrix.
  - **Docs** — addr_mode.md § ACC vs label disambiguation,
    asm_line.md § ACC mode handling, asm_src.md (warning emit
    contract), assembler_syntax.md § Accumulator addressing —
    bare and explicit forms (user-facing rule + shadow example).
  - **Cost:** +67 B per production variant (6510/6502/cmos), 1 BSS,
    2 RODATA bytes for `"A\0"` probe + `"a shadow"` string in
    strings.s.
  - **Test suite:** 3088 passed / 18 skipped (was 3057 / 18).

- [x] ~~**BUG**: `. .` is accepted as a valid dot-assemble source~~
  (fixed via Escape Analysis c8501d2: the actual symptom was
  "silent no-op" not "emits $00" — the cmd_dot @try_mne gate in
  repl.s silently fell through to the display-only @show path for
  non-letter input.  Fixed by splitting the gate: NUL/`;` →
  @show (valid silent redisplay), letter → dot_assemble, anything
  else → @syn_err.  repl.md now documents the `.` command's input-
  shape matrix as a four-cell commitment; testing.md Principle 11
  gains this as a second cautionary example after the asm_cpu gate.)
- [x] ~~**BUG**: not all log functions honour the "enter anywhere,
  exit at col 0" contract~~ (resolved via Escape Analysis: the
  bug turned out to be under-testing, not under-implementation —
  a probe of all 9 line-starters at CUR_COL=12 showed every one
  auto-advances correctly.  The invariant was transitively honoured
  through composition (log_line/err/warn/info → log_open;
  seg/prg/free_line → info_line_head) but only pinned at
  log_open directly.  Fixed by TestEnterAnywhereContract in
  test_log.py: a parametrised sweep over all 9 line-starters,
  each asserting (a) cursor advanced past TEST_ROW, (b) TEST_ROW
  at cols 12+ untouched.  log.md's Contract section now
  enumerates the per-function behaviour as a table (enter-anywhere
  × exit-at-col-0 matrix), turning the compositional guarantee
  into a per-function commitment per Principle 8.)
- [x] ~~Userland exit does not restore screen state.~~ (fixed:
  `vic_reset` in screen.s forces $D011=$1B, $D016=$C8, $D018=$15,
  $D015=0, $D01A=0, $D019=$0F on every userland → kernel
  transition.  Wired into `hygiene_after_userland`; the old
  `ora #$02` on $D018 replaced by absolute `lda #$15 / sta`.
  `restore_colors` still applies theme + colour RAM.  Promotes
  the Planned `vic_reset` item below to Done.)
- [x] ~~Debugger: what do we do if we trace into an actual BRK?~~
  Resolved (see debugger.md § User BRK workflow).  Rules: `o` and
  `c` skip past via `brk_skip_user` (advance brk_pc by 2 — past
  BRK + signature byte, matching CPU's RTI semantics).  `t`
  deliberately hangs to interrupt the return-step workflow for
  inspection.  No new `dbg_reason` value — opcode peek at command
  time distinguishes user BRK from step BRK / user BP via the
  centralised `brk_skip_user` helper.  IRQ vector is never
  invoked — we side-step BRK entirely.
- [x] ~~**Phase 18 — CSE as a Kernel.**~~  (done.  ISR-style kernel
  model: shared flat stack with 64-byte kernel headroom contract,
  direct vector patching via `setup_interrupts`, unified
  `save_userland_state` / `restore_userland_state` / `return_to_userland`
  gate primitives, command-loop flag-and-rts pattern, CPU-port-aware
  ZP save/restore primitives in mem.s, `vic_reset`, single
  `hygiene_after_userland` in `handler_finalize`.  See
  [design_cse_as_kernel.md](design_cse_as_kernel.md),
  [userland_contract.md](userland_contract.md),
  [memory_design.md § Stack contract](memory_design.md#stack-contract).)

  Sub-item status (all resolved unless marked [ ]):

  - [x] ~~Stack contract — drop the two-image stack swap.~~  (flat
    shared-stack; −512 B KBSS, ~−100 B CODE, ~−1500 cycles per
    transition.)
  - [x] ~~`return_to_userland` helper.~~  (in debugger.s; shares
    `_rtu_body` with `restore_userland_state`.)
  - [x] ~~`brk_stub` and clean userland exit.~~
  - [x] ~~Cold-init userland handoff.~~  (splash stays visible —
    cold init `jmp`s directly to `main_loop_top` after drawing
    the splash; main_loop_top does not clear the screen.)
  - [x] ~~`in_userland` flag.~~  ($80/0 convention for `bit/bmi`
    dispatch; owned by main.s.)
  - [x] ~~`setup_interrupts` — unified vector setup.~~  (direct
    stores to $0316/$0318/$FFFA/$FFFE.)
  - [x] ~~Direct vector patching — no separate trampolines.~~
  - [x] ~~IRQ early-entry bank-out mechanism.~~  (`bank_out_stub`
    in main.s; second-RTI-frame surgery.)
  - [x] ~~Kernel stack-depth measurement.~~  (Phase 19 — done:
    `TestKernelStackDepth` in tests/unit/test_asm_src.py measures the
    `asm_src → asm_line → expr_eval` chain from a fresh SP.
    Current numbers: ~30 B trivial, ~50 B realistic, ~130 B at
    8 levels of paren nesting in an operand.  The contract stays
    at 64 B; those numbers characterise the pipeline and catch
    regressions, not the BRK-tail re-entry path.  See
    [userland_contract.md § Kernel stack budget](userland_contract.md#kernel-stack-budget).)
  - [x] ~~CSE re-entry stack-headroom warning.~~  (Phase 19 — done:
    `post_run_cleanup` (repl.s) checks `reg_sp < 64` on every
    userland exit; emits `;!stk N` where N is the decimal
    headroom.  Three tests in
    `TestStackHeadroomWarning` cover the trigger, the at-budget
    boundary, and the healthy-SP no-warn path.)
  - [x] ~~VIC sanity reset (`vic_reset`).~~  (in screen.s; called
    from `hygiene_after_userland`.  $D011/$D015/$D016/$D018/$D019/
    $D01A.)
  - [x] ~~SID silence at boundary.~~  (Phase 19 — done:
    `hygiene_after_userland` (repl.s) writes $00 to $D404/$D40B/
    $D412, releasing all three voice gates and clobbering the
    waveform selection (SID is write-only so read-modify-write of
    just bit 0 isn't possible; clobber is the practical silence
    primitive).  +11 B.)
  - [x] ~~Userland contract document — published.~~  See
    [userland_contract.md](userland_contract.md).  Three-tier state
    model, kernal-as-terminal affordance, vector/banking hazards.

  Phase 18 tail is complete.

- [x] ~~**Loader reverse-direction copy.**~~  (Phase 19 — done:
  `copy_pages_back` in loader.s, payload-end sanity check
  dropped from `compute_layout.py`.  CODE + RODATA can now grow
  up to `runtime_start`.  See [build_system.md § Copy direction](build_system.md#the-ld65-loadrun-split).
  +11 B in the discardable LOADER segment.)
- [x] ~~Debugger: refuse to write breakpoints outside workspace memory~~
  (fixed: cmd_brk now rejects BP addresses outside [$0800, __CODE_RUN__)
  with a "; ? range" error before calling dbg_bp_set.  Phase 17.)

- [x] ~~**Phase 21 — Dependency-tree simplification.**~~
  (done, commits `45ab846` → `81aaa78`.  Five moves eliminated the
  planned back-edges and established a 7-layer almost-strict DAG.
  See [architecture.md § Layer Diagram](architecture.md).)

  Five moves (as landed):

  - [x] **Move 5 — Rename `au_mode.s` → `addr_mode.s`.** Pure rename.
  - [x] **Move 1 — `mem.s` sheds `define_ws_syms`.** −49 B (6510/6502), −24 B (cmos).
  - [x] **Move 4 — Cross-module flags → `zp.s`.** Seven 1-byte flags
    (`in_userland`, `state`, `warm_cont`, `kernal_out`, `ed_dirty`,
    `dbg_reason`, `cur_device`).  −58 B per build (BSS→ZP access
    shortens every use).
  - [x] **Move 2 — Extract `asm_err.s` (Layer 2).** Owns
    `asm_syntax_error`, `asm_expr_error`, `asm_error`, `asm_expr_err`,
    `asm_pass`.  Size-neutral (pure relocation).
  - [x] **Move 3 — Extract `log.s` (Layer 2, partial).** Owns
    `log_open/close/line/err/warn/info`, `puts_imm`, log.inc.  Size-
    neutral.  Range-line formatters (`seg_line`/`prg_line`/`free_line`)
    stayed in repl.s — see follow-up below.

  **Totals:** −107 B (6510/6502), −82 B (cmos).  2681/2681 tests
  green at every commit.  Every back-edge in the Step-2 CDD Analysis
  was eliminated except the residuals listed below.

  Residual back-edges — **all cleared in Phase 21.1** (commits
  `1362bb6` + `647f0f2`):

  - [x] ~~`asm_src → repl` via `seg_line` + BSS scratch.~~  Phase 21.1
    Move 3B: shared scratch pool (`rp_addr`, `rp_cnt`, `rp_save`,
    `rp_save2`, `rp_next_lo`, `_info_mode`) migrated to `zp.s`;
    range-line formatter family (`seg_line`/`prg_line`/`free_line` +
    `info_line_*` + `_range_core` + `log_err_eol` + `log_close_eol`)
    hoisted from `repl.s` to `log.s`.  −224 to −232 B per build
    (the scratch ZP promotion hits ~209 access sites).
  - [x] ~~`asm_src → repl` via `cur_project_name`.~~  Phase 21.1
    Move 6a: 17-byte filename-stem buffer moved to `zp.s` at
    $5E-$6E.  Y→X refactor in `editor.s::ed_status` filename scan
    recovers 2 extra bytes that would otherwise fall back to abs,Y.
    −8 B per build; 17 ZP bytes spent.
  - [x] ~~`editor → repl` via `cur_project_name`.~~  Same commit.

  **Phase 21 total (including 21.1):** −339 B 6510 / −339 B 6502 /
  −314 B cmos; zero back-edges; workspace gained 256 B (runtime
  start shifted up one page).

  Revisit items:

  - [ ] **If ZP space gets tight, reconsider `cur_project_name` placement.**
    The 17-byte buffer in ZP at $5E-$6E claims space that could
    host hotter single-byte flags or 2-byte pointers.  ~40% of
    the buffer's accesses (the `(rp_ptr2),y` loops in
    `copy_stem_to_project`) can't benefit from zp encoding.
    If user-ZP pressure ever exceeds the current 8-byte free
    margin ($78-$7F), move `cur_project_name` to `disk.s` BSS
    — cost 0 ZP, code-size penalty ~8 bytes, restores no
    back-edge regression.

  Deferred Phase-21 test additions (written up in the TDD Analysis,
  scheduled for a separate commit after the phase lands):

  - [ ] `dev/check_deps.py` — mechanical scanner that parses every
    `.import` / `.importzp` in `src/*.s`, resolves each against
    per-module `.export`s, and asserts every edge is strictly
    downward per the [layer table](architecture.md#modules).
    Permanent enforcement of the strict-DAG invariant.  ~50 LOC
    Python.  Run in CI.
  - [x] ~~`tests/unit/test_asm_err.py`~~ — landed as test-restructure
    Tranche 2 (commit `ee01914`, 7 Tier-U tests covering the
    longjmp unwind contract).
  - [x] ~~`tests/integration/test_log.py`~~ — landed as Tranche 2
    (10 Tier-I tests for log primitives + range-line family via
    C64Emu screen-RAM assertions).

- [x] ~~**Phase 20 — Warmstart restructure and debug-session lifecycle.**~~
  (done, commits `c4c1992` + `08e9756`.  Reason-named entry points
  `cse_recover`/`cse_end_debug`/`cse_refresh` compose from rts-returning
  body subs.  Gates on `a`/`l`/`R` let the user end the current debug
  session cleanly.  `R` command added.  `c` errors out without an
  active debug session.  NMI in kernel mode routes to `cse_refresh`.
  Gating strings decomposed: `warn_if_unsaved` / `warn_if_debug` emit
  `;!unsaved` / `;!debug` log lines ahead of a simple "action? y/n"
  prompt; two warnings stack (unsaved before debug).  +229 B total,
  2681 tests green.  See
  [main.md § Layer 3](modules/main.md),
  [memory_design.md § Warmstart entry points](memory_design.md#warmstart-entry-points),
  [repl.md § Gating pattern](modules/repl.md#gating-pattern).)

  Follow-ups (size + coverage) — each is isolated and post-v0.1:

  - [ ] **Gate shape consolidation.**  `cmd_asm`/`cmd_load`/`cmd_reset`
    share a near-identical skeleton (warn → prompt → on-yes:
    either `end_debug_body + refresh/jmp` or `warm_cont := 1 + jmp
    cse_end_debug`).  A shared `_gate_debug(prompt_str, yes_vec)`
    helper could factor this.  Worth attempting only if the
    per-command continuation differences can be expressed as one
    dispatch byte rather than multiple branches; estimate ~20-30 B
    savings if the shape works out.

  - [ ] **`end_debug_body` zero-loop.**  Currently 8 × 3 B of
    `sta abs` (zero stores) + 3 × 3 B of `sta abs` (`$FF` stores)
    = ~33 B of straight-line stores.  Could drop to ~10 B if the
    11 fields lived contiguously in BSS.  Requires coordinating
    layout across `main.s`/`mem.s`/`repl.s`/`debugger.s` — invasive
    refactor for a ~20 B saving.  Defer until the next BSS
    reshuffle pass.

  - [ ] **Warmstart fall-through from `cse_refresh` into
    `main_loop_top`.**  Placing the three warmstart entry points
    immediately before `main_loop_top` in the file would let
    `cse_refresh` drop its `jmp main_loop_top` (-3 B).  Reorder
    and verify branch ranges don't regress anywhere.

  - [x] ~~**Shared `@*_cancel` exit in `exec_line` dispatch.**~~
    Closed 2026-04-27 with partial gain.  Investigation showed
    the headline ~12 B saving via "single shared label" was not
    achievable: the 5 cancels span ~500 lines inside `exec_line`
    and `bcc`'s ±127-byte range can't fold them all.  Each of
    the 4 in-`exec_line` cancels (`k`/`a`/`Q`/`R`) is already at
    the minimum 5-byte shape (`bcc @x_cancel` 2 B + trailing
    `@x_cancel: jmp nl_clear` 3 B).  The 5th cancel
    (`cmd_load::@l_cancel`) was 8 B (`jcc` 5 B + trailing label
    + jmp 3 B); inverted polarity to `bcs @do_load / jmp nl_clear`
    inline (5 B) saves 3 B.  Q/R cancel chaining was also viable
    for another -3 B but adds a cross-handler label dependency
    that exceeds its byte value.  Net result: -3 B landed on
    cmd_load only.

  - [ ] **End-to-end gate tests (keypress injection).**  Current
    `TestGating` covers only the `warn_if_*` helpers directly.
    The full `R`/`a`/`l` flows (warn → prompt → y/n → outcome)
    would benefit from integration tests that inject keys via
    `C64Emu.inject_key`.  Coverage, not size.

  - [x] ~~**String aliasing for new gating strings.**~~  (Done in
    the polish pass — `confirm_action` renamed to `query_user`,
    `"? y/n"` folded into a shared `str_qynq` trailer printed by
    the helper, and each action string shortened to its verb stem.
    -25 B per build.)

  - [x] ~~**Cold init ↔ `hw_reinit_body` sharing.**~~  Closed
    2026-04-27 as **considered, not worth it.**  Re-examined
    during the Phase-24 follow-up survey of the init paths.
    The overlap looks tempting (six shared steps), but the
    *order* differs meaningfully: cold init runs
    `setup_interrupts` and `dbg_init` early (before any code
    that could fault), then sym/editor/workspace setup, then
    I/O + screen + globals at the end.  `hw_reinit_body`
    bundles HW + globals together because fault recovery
    doesn't have to interleave with sym/editor init.  Forcing
    a shared pipeline would either break cold init's
    ordering constraint or carry a configurable-middle-step
    parameter through both call sites — net cost in clarity
    likely exceeds the ~9-12 B saving.  Decision recorded.

### Fixed bugs (reference)

<details>
<summary>Click to expand</summary>

- [x] `s` command PRG save address stale ZP ref — repl.s wrote to
  hardcoded `$FB/$FC` instead of `_io_tmp`; stale from Phase 12.
- [x] Editor INS key ignored — inserts space via `gb_insert` +
  `gb_cursor_left`; refused at 39-col cap.
- [x] 13 CMOS mnemonic gate bugs — fixed in `2939a94`.
- [x] expr.s test harness: 12 xfails — resolved, 146 tests pass.
- [x] asm_cpu 3-valued semantics — fixed.
- [x] `j` command: reset colors after user code returns.
- [x] `print_load_split_warning` leading-comma bug.
- [x] `ed_scroll_down` memmove broken — rewrote as row-by-row copies.
- [x] Revise TDD framework — Principle 6 + Anti-patterns section.
- [x] 8 xfailed `TestStepIntoJSR_ROMFallback` — ported to
  `test_step_rom.py` using C64Emu.  0 xfails remain.
- [x] Clean up `dev/test.d64`.
- [x] Review all user-facing strings — terse convention established.
- [x] Line-break warnings on file load — one per split.
- [x] `theme_border`/`theme_bg`/`theme_fg` in RODATA — moved to BSS.
- [x] `.` and `m` show CSE ZP — fully resolved in Phase 19 via the user-ZP redirect (see open-section entry above).
- [x] Stack-snapshot revisit under KERNAL — resolved.
- [x] BASIC SYS residue on hardware stack — SP reset at startup.
- [x] `dbg_enter` ZP save buffer sizing — fixed.
- [x] cc65 -O ternary miscompilation — eliminated (pure asm).
- [x] cc65 -O zero-extension bug — eliminated (pure asm).
- [x] User CHROUT overwrites prompt row — newline before run_user.
- [x] asm_src test stub blank line truncation — $FF EOF sentinel.
- [x] `dev/test.d64` T-COUNT: renamed from COUNTDOWN, loads and
  displays correctly after page-alignment fix.
- [x] NMI trampoline corrupted $01 — trampoline no longer modifies
  $01; handler chain runs in main RAM.  Added IRQ/BRK trampoline
  at $FF04 (defensive).  Phase 14.
- [x] IRQ/BRK trampoline verified safe — IRQs blocked by SEI,
  user BRK path returns through `run_user` which restores $01.
- [x] `t1` step over taken branches — `compute_rel_target` clobbered
  N flag with `ldy #0` before `bpl`.  Negative offsets treated as
  positive.  Fixed with BIT-abs skip trick.  Phase 14.

</details>

## Phase 9 — Test harness rewrite

`C64Emu` emulator class + production PRG replaces per-test build
systems, ASM stubs, and test-specific linker configs.

### Done

- [x] `tests/c64emu.py` — C64Emu class: py65 + KERNAL ROM overlay,
  $01 bank switching, screen RAM, jsr(), sym(), keyboard injection.
- [x] `tests/integration/test_c64emu.py` — 34 smoke tests.
- [x] `tests/integration/test_editor.py` — 10 ASM-level editor tests
  (gap buffer, ed_new, dirty flag, ed_read_line).
- [x] `tests/integration/test_screen.py` — 15 ASM-level screen tests
  (scroll_up, newline, restore_colors, reset_screen, cursor toggle).
- [x] `tests/integration/test_step_rom.py` — 8 debugger step-into ROM tests
  (replaced xfailed tests).
- [x] Makefile: `-Ln` label file, `check-roms` gate, `cse_prg` fixture.
- [x] KERNAL ROM setup: screen line link table ($D9-$F1), HIBASE,
  page-3 vectors via RESTOR.
- [x] `c64emu.py` load/run segment relocation: auto-copies segments
  with load ≠ run addresses (mirrors loader.s).

### Open

- [x] ~~Review l/s command tests~~ (fixed: test_repl.py now resolves
  `save_addr`/`save_size`/`load_result` via RODATA `sym_refs` table
  slots 11–13, replacing fragile hardcoded BSS offsets)
- [ ] Use debug builds and `od65 --dump-all foo.o` for extracting
  all symbols (exported and unexported) from object files for
  testing.  Use stripped production builds only for superficial
  end-to-end integration tests.  This eliminates fragile BSS
  offset computation and map-file parsing in test harnesses.
- [ ] Migrate remaining test files to C64Emu + full PRG.  Each old
  test file (test_repl, test_cse_io, test_expr, test_symtab,
  test_debugger, test_addr_mode, test_mn_classify, test_asm_line,
  test_dasm, test_asm_src) has its own build system, map parser,
  and run loop.  Migration removes ~1200 lines of harness code,
  9 ASM stub files, and 3 linker configs.
- [ ] Editor scroll/render screen-RAM tests.  `ed_scroll_down` and
  `ed_render_line` are `.proc`-scoped (not in .lbl); test path is
  through `ed_handle_key` with cursor keys, which needs full editor
  state.  Deferred until `enter_editor` can be called via C64Emu.
- [ ] Retire `test_editor.py` mirror tests once ASM-level coverage
  is complete.
- [ ] README cross-reference tests: parse command tables in
  `README.md`, verify each command key has a handler symbol in the
  `.lbl` file.  See CDD Maintenance item 8.

### Test restructure Tranche 4 — `test_repl.py` → C64Emu

- [ ] **Migrate `tests/integration/test_repl.py` from the bare-MPU +
  `dev/repl_test_stub.s` harness to full C64Emu + production PRG.**
  Blocked on the C64Emu virtual-IEC-disk extension (see the
  C64Emu extension roadmap below) because `TestSaveCommand` and
  `TestLoadCommand` (~30 tests, ~300 lines) currently observe
  behaviour via the stub's `_save_addr` / `_save_size` / `_save_name` /
  `_load_result` / `_load_name` / `_op_witness` BSS instrumentation
  that records what the commands *would have done*.  Without a
  virtual disk, C64Emu tests for these commands have no way to
  assert success.

  Non-disk classes (17 of 20, ~50 tests covering prompt / read_line /
  address / memory / disasm / calculator / register / block / repeat /
  semicolon / unknown / cpu / dothex) migrate cleanly to C64Emu —
  they already use real production code paths.  Splitting into
  two files to migrate the non-disk half immediately is possible
  but creates a maintenance burden until the disk half can follow.

  Prerequisite: C64Emu virtual IEC disk (below).
  Payoff: drops `dev/repl_test_stub.s` (~300 lines), `dev/repl_test.cfg`,
  the bare-MPU `_build()` / `_parse_map()` / `ReplSymbols` scaffolding
  in test_repl.py, and the `sym_refs` RODATA table workaround.
  Net: -400–500 LOC of test harness, zero new test logic.

### C64Emu extension roadmap

Planned emulator feature additions (scoped during test-restructure
discussion).  Each block is independent; do in any order.

- [x] ~~**Full `$01` banking**~~ — landed as C64Emu extension 1
  (commit `77ef7a4`).  Three-bit banking (LORAM/HIRAM/CHAREN) with
  BASIC + CHARGEN ROM overlays.  Default `$01` now `$36` (CSE
  runtime config) instead of `$37`.
- [x] ~~**DDR-aware `$00`/`$01` model**~~ — landed with extension 1.
  `$01` read returns `(latched & DDR) | (external & ~DDR)`.
- [x] ~~**Scheduled interrupts**~~ — landed as extension 2 (commit
  `a755c9d`).  `schedule_irq` / `schedule_nmi` / `cancel_pending_interrupts`
  + cycle-accurate pending queue honouring I flag + NMI edge.
- [x] ~~**CIA1/CIA2 register shadows + keyboard matrix**~~ — landed
  as extension 3 (commit `30d9dbf`).  `$DC00/$DC01` 8×8 matrix,
  `press_key` / `release_key` / `press_stop` / `press_restore`,
  CIA2 `$DD0D` NMI latch.
- [x] ~~**Jiffy clock tick**~~ — landed as extension 4 (commit
  `d426040`).  `enable_jiffy_clock` / `disable_jiffy_clock` on top
  of the scheduled-IRQ infra; default 16421 cycles matches KERNAL.

- [ ] **Virtual IEC disk (D64-backed)** — intercept KERNAL IEC entry
  points (`$FFC0` OPEN, `$FFD5` LOAD, `$FFD8` SAVE, `$FFCF` CHRIN,
  `$FFD2` CHROUT, etc.) with a Python callback backed by a virtual
  D64 image.  Unlocks Tranche 4 (test_repl migration) + hazard tests
  (overwrite, file-not-found, device-not-present).  Moderate-to-high
  effort; timing-accuracy concerns — flagged as out-of-scope at
  extension-planning time.

- [ ] **VIC raster counter auto-increment** — `$D012` derived from
  cycle counter (~63 cycles/line).  Unlocks raster-synced user
  programs.  Not needed for CSE itself (no raster tricks); low
  priority.  ~30 LOC.

- [ ] **REU / cartridge emulation** — out of scope until R5 (CRT
  build target).  Placeholder for the roadmap.

## Planned

Defined scope, needs work.

### Corpus

- [x] ~~**CDD follow-up for the 2026-04-22 Design Priorities expansion.**~~
  Closed 2026-04-25 by Phase 23 CDD Streamlining maintenance round.
  Six absorption gaps from `background.md` folded into corpus voice in
  `doc/project.md`: §4 keyboard rule gained its "shared surface" *why*;
  §6 Transparency gained an exclusion paragraph (BASIC-like wrappers,
  scripting layers, pseudo-register/pseudo-address illusions); §7 Two
  audiences gained the "fits in the user's head" justification and the
  no-unlearning-step feature filter; § *What Is CSE?* gained a pointer
  to background.md for motivating context.  Principle-3 hygiene:
  `**Dependants:**` annotation added under § Design Priorities;
  background.md indexed in `doc/README.md` § *User-facing behaviour* as
  a derived document.  No corpus contradictions found.  TDD delta
  confirmed nil (priorities are design constraints, no behavioural
  contract).  No copies of the priorities list exist elsewhere
  (verified by grep over `doc/`); architecture.md intro stays focused
  on kernel framing, no drift introduced.

- [x] ~~**L0 data modules unowned** (CDD Maintenance 2026-04-25, item 2).~~
  Closed 2026-04-25.  Each generated table is now claimed by the
  module that consumes it: `mn7_tables.s`, `mn6_tables.s`,
  `mn_config.s` → `mn_classify.md`; `mn_asm_tables.s`, `mn_modes.s`,
  `oplen_tbl.s` → `opcode_lookup.md`; `dasm_tables.s`,
  `dasm_mne_idx.s` → `dasm.md`; `loader.s` → new `loader.md`;
  `mn_vars.s` was already in `mn_classify.md`.  `architecture.md`'s
  L1 module table and Generated-files table now link every L0 file
  to its owning doc.  `mn_config.s` flagged in its claim row as a
  vestigial 256-byte table (predecessor of `mn7_tables.s`); follow-up
  TODO under § Architecture to retire the file from the build.

- [x] ~~**dev/ tooling unowned** (CDD Maintenance 2026-04-25, item 2).~~
  Closed 2026-04-25.  `build_system.md` § Owned files extended to
  claim every previously-unowned `dev/` file: `scs_analysis.py`,
  `scs_pack.py`, `gen_asm_tests.py`, `strings.txt`, `test.cfg`, the
  six test-bundle stubs (`asm_core_test_stub.s`, `asm_src_test_stub.s`,
  `breakpoints_test_stub.s`, `cse_io_test_stub.s`, `dasm_test_stub.s`,
  `repl_test_stub.s`, `symtab_test_stub.s`), the two test-bundle
  configs (`asm_src_test.cfg`, `repl_test.cfg`), the `dev/search/`
  exploration scripts (claimed wholesale as historical hash-search
  provenance), and the two committed disk images (`src.d64`,
  `test.d64`).

- [x] ~~**Tests unclaimed** (CDD Maintenance 2026-04-25, item 2).~~
  Closed 2026-04-25.  Test files added to module-doc Owned files
  blocks: `test_asm_err.py` → `asm_err.md`; `test_gap_buffer.py` →
  `gap_buffer.md` (existing transitive-via-editor row preserved);
  `test_log.py` → `log.md`; `test_repl.py` and `test_repl_disk.py`
  → `repl.md`; `test_screen.py` → `screen.md`.  The five C64Emu
  harness tests (`test_c64emu*.py`) added to `build_system.md`
  alongside `c64emu.py`.  `tests/retired/` was initially claimed by
  `testing.md § Mirror tests` as a worked-example archive, then
  retired entirely (its anti-pattern descriptions inlined into the
  same section); the tree itself was removed when it was found to
  shadow `tests/conftest.py` and break `pytest tests/`.

- [x] ~~**`main.s` lacks dedicated unit tests** (CDD Maintenance
  2026-04-25, item 7).~~  Closed 2026-04-25.  `doc/modules/main.md`
  now declares Pattern A coverage explicitly: dispatcher
  classification (`cse_brk_handler`, `cse_nmi_handler`) covered at
  Tier I via `test_kernel_transition.py` + `test_step_rom.py`;
  vector installation and cold-init covered transitively by every
  integration test that boots the production PRG.  Unit-tier
  isolation rejected as not productive — the synthesised state
  needed to drive the dispatcher is essentially the integration
  setup.

- [x] ~~**`disk.s` coverage gap undocumented** (CDD Maintenance
  2026-04-25, item 7).~~  Closed 2026-04-25.  `doc/modules/disk.md`
  now declares Pattern C coverage explicitly: KERNAL IEC entry
  points are not modelled by py65 + C64Emu (no virtual IEC bus, no
  D64 backend), so coverage is manual VICE walks of `l` / `s` / `$`
  paths.  Cross-references the queued
  § C64Emu extension roadmap → Virtual IEC disk item.

- [x] ~~**`loader.s` triple gap** (CDD Maintenance 2026-04-25, items
  2, 6, 7).~~  Closed 2026-04-25 by the new `doc/modules/loader.md`
  (interface + design + caveats + Pattern A coverage statement) and
  the architecture.md ownership-link update.  The legacy duplicate
  entry under § Architecture (line ~1285, "Missing module doc:
  `src/loader.s`") is now obsolete and removed.

### REPL

- [x] ~~`.` without args: behave like `d` (disassemble one instruction).~~
  (already the behaviour: `cmd_dot` falls through to `emit_dot`
  when no hex bytes and no mnemonic were parsed.)
- [ ] `/` command: search for byte pattern in memory.
- [ ] `f` command: fill memory range with byte.
- [ ] `>` command: transfer/copy memory block.
- [ ] `=` command: define/query symbols from REPL.
- [x] `r` command: uppercase set flags (`Nv-bDizc` vs `nv-bdizc`). (Phase 16)
- [ ] `?` command: for values < 256, show PETSCII and screen code
  character interpretation alongside the hex/decimal/binary output.
- [ ] `m` address argument: accept expression (`m screen+40`).
  Currently plain 4-digit hex only.
- [ ] New `S` command for scratching files. Requires confirmation.
- [x] ~~VIC sanity reset on kernel/userland boundary.~~ (done:
  `vic_reset` in screen.s forces $D011=$1B, $D016=$C8, $D018=$15,
  $D015=0, $D01A=0, $D019=$0F.  Called from `hygiene_after_userland`
  on every break/resume cycle.  Future work: call from
  `cse_refresh` too so ESC/CLR recovers from a kernel-resident
  program that glitched VIC.)
- [ ] SID silence: stop stuck notes when user code leaves SID running.
  Two complementary mechanisms:
  1. **REPL command** (probably one of the existing mnemonic-free
     letters, or a dedicated key chord) — zeroes all SID registers
     (`$D400-$D418`).  Useful when the user's code has SID voices
     playing and leaves them running after a break.
  2. **Contractually at the kernel/userland boundary** — on every
     transition from user code back into the CSE kernel (BRK,
     breakpoint, NMI-userland-break, brk_stub return), zero the
     SID's gate bits (`$D404`/`$D40B`/`$D412` bit 0) to release
     voices.  Keeps SID register values otherwise intact so the
     user can see what was set.  ~6 bytes on the BRK handler
     path.  Pairs with dropping `io_blip` to give the contract
     clause "SID is yours except voice gates at debug entry."
  The two together give the user a clean audio environment on
  break, and a manual way to silence mid-session if a user
  command (like `j` into a program) leaves SID noisy.
- [ ] Disk command channel: unified under `$` (`$ s:file`, `$9`, etc.).
- [ ] Floppy status consistency: `$` prints status inline (always
  shows), `l`/`s` use `floppy_status` via `disk_done`.  Verify
  both paths produce identical output on stock KERNAL.
- [ ] `l` command PRG mode: report actual load address in stats
  line.  Currently shows `cur_addr` which may be wrong when the
  PRG loads at its own header address (addr=0 path).
- [ ] PRG range display: unify format to `AAAA-EEEE  NNNb` (range
  first, size second).  Currently `l` PRG stats prints `NNNb AAAA-EEEE`
  (size first).  Shared `print_prg_range` should use the same
  order as the assembler `; org` lines and the splash screen.
- [ ] SHIFT+RETURN in REPL: clear the repeat buffer (so the next
  RETURN starts empty instead of re-executing the last command) and
  open a fresh prompt line.  Useful for breaking out of a repeated
  `t`/`RETURN` stepping rhythm without having to type a cancel.
- [ ] `e` command: open editor at decimal line number (`e 42`).
  Centers the target line on screen as much as possible.  Ties
  into assembler error line numbers — assemble, see error at
  line 42, type `e 42` to jump straight there.
- [ ] `l`/`s` log line: always show the effective CBM DOS type
  (SEQ vs PRG) in the `; load/save "name"...` output.  Under the
  project-name refactor the on-disk name is derived (`stem` vs
  `stem.`) and the user should still see which classification path
  was taken when derivation was automatic.
- [x] ~~Refactor internal default filename to a project name~~
  (Phase 17.  `cur_filename` → `cur_project_name`, stem only
  (no `,s`/`,p` suffix, no trailing dot).  Derivation: SEQ = stem,
  PRG = stem + `.`.  Shared argument parsing between `l` and `s`
  via `parse_ls_args` — positional, expression parser, 0-2 numeric
  args.  Verbatim names (`,s`/`,p` suffix at tail) bypass
  derivation.  See `doc/modules/repl.md` § Project-name and
  filename semantics.)

### Debugger

- [ ] `t1` over a JSR to KERNAL ROM ($E000+) silently falls back to
  step-over (per @jsr's RAM-target check).  Show a one-line note
  (e.g. `; rom step → over`) so the user knows.  The workspace
  gate added later — step-BRK arming refuses outside [workstart,
  workend] with `;!range` — catches the broader cases, but this
  specific JSR-to-ROM path still slips through silently because
  `step_next_pc` rewrites the lookahead to PC+3 (in-workspace)
  before the gate sees it.

- [ ] Fast turnaround in the BRK handler for long trace loops.
  Today every step iteration runs the full save/restore_userland_zp
  + save/restore_kernel_zp pair — two 128-byte ZP copies (one
  user→buf, one buf→live) per break/resume cycle.  For `t 100`-class
  stepping the ZP churn dwarfs the actual user instruction cost.
  Opportunity: detect "we're mid-chain, no REPL code will run
  between break and resume, kernel ZP state hasn't been consumed"
  and skip the ZP swap entirely — keep user ZP live across the
  handler's chain body (step_next_pc doesn't touch user ZP, only
  reads abs/stack addresses).  NMI breakouts: if NMI fires during
  the fast-turnaround chain, fall back to the full ZP swap and
  longjmp so post_run_cleanup sees a consistent ZP view.  Consider
  a flag (`step_fast_chain` or similar) that save_userland_state
  tests to skip the ZP swap when set, armed by cmd_step's seed +
  the handler's chain path.  Expected saving: ~2 * 128 = 256
  cycles per step iteration.

- [ ] Show wall-clock execution time on the `j`/`g` clean-exit
  panel.  Sample KERNAL jiffy clock ($A0/$A1/$A2, the TOD-style
  3-byte counter incremented by the IRQ at 60 Hz on NTSC,
  50 Hz on PAL) at userland entry (in `_rtu_body` just before
  the RTI) and again at handler entry (`cse_brk_handler`),
  store the delta somewhere the panel can read (e.g. a 3-byte
  `run_jiffies` slot).  Format on the DBG_RTS panel:
    < 1 s        → `Nms` (jiffy * 1000 / clock_hz, 0–999)
    1 s ..< 1 m  → `Ns` or `N.NNNs`
    1 m ..< 1 h  → `NmNs`
    >= 1 h       → `NhNmNs`
  Render as a tail field on the info or regs row, e.g.
  `; rts at $0800  3.4s` or `r pc:0800 ... s:ff  217ms`.
  Notes:
    - Jiffy clock wraps after ~4.7 days (24-bit counter at
      60 Hz) — fine for typical debug sessions; longer runs
      get `>4d` clamp.
    - PAL/NTSC detection: the assembled binary already knows
      via build flag (CMOS / 6502 / 6510 builds may differ);
      otherwise sample $02A6 at startup (KERNAL sets 0=NTSC,
      1=PAL).
    - Jiffy clock pauses while the kernel runs (IRQ disabled
      during handler), so the delta excludes our overhead —
      only user code time is reported.  Good.
    - `t`/`o` step-result panels probably DON'T need this
      (single steps are sub-microsecond), but a `t100`-class
      batch could surface aggregate time.

- [x] ~~BRK tracer rewrite: use BRK's signature byte ($00 XX)~~
  Scratched: BRK must remain 1 byte only.  The 6502 BRK
  instruction is documented as 1 byte; the byte at PC+1 is a
  user-controlled signature for their own purposes (e.g. the
  ".db" pattern in user BRK debug breakpoints — see "user BRK
  workflow" below).  Encoding metadata into that byte would
  collide with user code.  step BRK / user BP discrimination
  stays via the dbg_bp_find address search.

- [x] ~~Single-RETURN single-step workflow~~  (done: combined
  effect of ef667ce — bare `t` defaults to 1 step (not block_size)
  — and the cold-preview / warm-step / step-through-rts work
  in 9c6abaf..d591a13.  `t / RETURN / RETURN / ...` now does
  rapid single-stepping with full panel after each step.)
- [x] ~~Extend userland ZP backup to $00–$7F~~  (done: Phase 17.
  ZP_SAVE_LO/HI widened to $00/$7F (128 B), covering the full
  user-accessible half.  `m`/`.` now read a uniform user-ZP view —
  the redirect's range check in repl.s simplified from the $02/$5A
  double bounds + subtract to a single `cmp #$80`.  run_user's
  external `lda $01/pha` pair dropped (banking now round-trips via
  zp_save_buf since $01 is inside the saved range).  +80 B BSS,
  −7 B CODE in repl.s, −4 B CODE from the removed $01 dance.)

### Help

- [ ] In-app help system.  Help text lives in KDATA (under
  KERNAL ROM, $F100 area), not RODATA — must not bloat the
  relocatable runtime.  Minimal CODE overhead: a small dispatcher
  that pages through KDATA strings.  Candidates: one-screen
  REPL command cheat sheet, editor key summary, assembler
  syntax quick ref.  Paging output (see below) would pair
  naturally.

### Output

- [ ] Paging for commands that produce more than ~23 lines of
  output (`d`, `m`, `$`, assembler messages).  Pause with
  "more" prompt, any key continues, RUN/STOP aborts.  The
  `log_line` output wrappers already funnel all command output
  through a single path — hooking a line counter there should
  be straightforward.

### Assembler

- [ ] `.` REPL command: emit ACC label-shadow warning to match the
  source-assembler behaviour.  `dot_assemble` (in repl.s) pre-
  evaluates expressions via `expr_eval` *before* calling `asm_line`
  and rebuilds the operand as a `$xxxx` literal, so `mode_parse`
  never sees the bare `A` token and the `_au_warn_shdw` path is
  never entered.  Net effect: typing `.asl a` against a defined
  `a:` gets the labelled memory address (because `expr_eval`
  resolves `a` first), with no warning.  Source-assembly users
  get accumulator mode + the `;!a shadow` warning — this is the
  asymmetry.  Resolution options: (a) Make `dot_assemble` skip
  the pre-eval for bare-`A` operands when the mnemonic is in
  profile 11 — small special case; (b) move the entire pre-eval
  out of `dot_assemble` and let `asm_line`'s expression-aware
  pipeline handle everything (larger change, also closes other
  asymmetries).  Low priority — the `.` command shows immediate
  output, so the user sees what was assembled.

- [x] `.bas` directive: emit a BASIC SYS stub.  (Phase 12, done)
  Single BASIC line: `.bas` → `0 SYS NNNNN`.
  `.bas "TEXT"` → `0 SYS NNNNN:REM TEXT`.
  Always 5 decimal digits (260 B).  2799 tests.

- [x] ~~**Error-category tables are part of the contract.**~~
  (Phase 25 fix.)  Resolved by:
  - **`src/asm_err.s`** — boolean `asm_expr_err` replaced with
    a 3-state `asm_err_code` byte (0=syntax, 1=expr, 2=cpu).
    New `asm_cpu_error` entry point added to the BIT-abs-skip
    cascade so all four exits share the same SP-restore/bank-in
    tail.
  - **`src/asm_line.s`** — CPU-gate rejects (cat=11 on non-CMOS,
    cat=10 on non-6510) now `jmp asm_cpu_error` instead of
    `jmp asm_error`.
  - **`src/strings.s`** — new `str_cpu_err: "cpu"` string.
  - **`src/asm_src.s::process_line @bad`** + **`src/repl.s::cmd_dot`**
    — both error dispatchers now branch on `asm_err_code` (0/1/2)
    to pick the right user-visible tag.
  - **Tests** — `test_asm_err.py` updated for the rename, gains
    `test_asm_cpu_error_writes_code_2`.  New
    `TestErrorCategoryDispatch` in `test_asm_line.py` (5 cases)
    pins the asm_err_code matrix end-to-end via the assembly
    pipeline (unknown mnemonic, bad mode, undef symbol, pure-CMOS
    on 6502, illegal NMOS on 65C02).
  - **Docs** — `asm_err.md` § Error categories now lists the table
    as a first-class contract.  `asm_line.md`, `asm_src.md`,
    `repl.md`, `addr_mode.md` cross-reference the table; `repl.md`
    § cmd_dot gains the dispatch table for the user-visible tags.
  - **Cost:** +29 B per production variant.  Suite 3103 passed /
    18 skipped (was 3097 / 18; +6 new asm_err + dispatch tests).
- [x] Per-segment assembly summary — bug fixes + streaming design.
  Fixed bugs (pass-0 output, stale asm_pc, asm_org clobber,
  expr_val clobber, filename `,s`→`,p`).  Streaming segment lines
  during pass 1, `; ok` + save command after.  +70 B, 6 tests.
- [ ] Assembly `; ok` line: show symbol count (`; ok  NNN syms`).
  Needs `sym_count` (2B BSS) in symtab.s, incremented by `sym_define`,
  but only if the symbol didn't exist before.

### Editor

- [x] ~~Handle files > gap buffer capacity (show error, don't crash).~~
  (Phase 25 fix.)  Two paths covered:
  - **Load path** was already safe — `_load_overflow` flag in
    `editor.s::load_insert` short-circuits subsequent bytes,
    `ed_load_source` resets the buffer and returns code 2 → REPL
    shows `;?too big`.  Now pinned by tests.
  - **Keystroke path** was the actual crash class — `gb_insert`
    sites in `ed_handle_key` ignored the C=0 (full) signal and
    advanced `ed_cur_col` / `ed_cur_line` regardless, drifting
    bookkeeping from buffer contents and corrupting all
    subsequent rendering.  Fixed by adding `jcc @reject` after
    each gb_insert in the RETURN, INS, TAB, and printable paths.
    Refuse semantics: audible blip + cursor resync, no col/line
    advance.
  - **Tests** — `TestBufferOverflow` in
    `tests/integration/test_editor.py` (6 cases) pins both
    halves: `_load_overflow` set/sticky behaviour and per-key
    refuse for printable / TAB / RETURN / INS.  Setup pokes
    `buf_base = BUF_FLOOR` + zero-byte gap directly so the test
    runs in milliseconds rather than fill-loop seconds.
  - **Doc** — `editor.md` § Buffer-full refuse spells out the
    contract and the load-path mechanism.
  - **Cost:** +25 B per production variant (5 × `jcc @reject`).
  - **Test suite:** 3109 passed / 18 skipped.
- [ ] Gap buffer floor above directory load area: if `list_directory`
  stays LOAD-based (loads to $0801, max ~5.1 KB), set gap buffer
  bottom to $0801+$1400=$1C01 so `$` can never clobber source.
  Currently BUF_FLOOR is computed dynamically by `compute_layout.py`
  — would need a minimum floor of $1C01.
- [ ] Gap buffer compaction: `buf_base` only grows down (via
  `gb_ensure_room`), never shrinks.  `ed_init`/`n` should reset
  `buf_base` to BUF_END.  Line deletion could trigger compaction
  but consider the trade-off (O(n) vs immediate undo).
- [ ] Page up/down with shift+cursor or F-keys.
- [ ] Search (ctrl+f equivalent via F-key).
- [ ] Goto line number (see `e` command)
- [ ] `$A0` and `$09` should be both be interpreted as TAB, both from
  keyboard input, and when handled in source code.

### Size optimization

**Post-Phase-18 optimization sweep.**  Exhaustive three-agent review
after Phase 18 landed.  Ongoing — see commits `7351292` (A),
`fc52046` (B), `8e60b62` (SEI/CLI), `778a1f4` (disk) for progress.
Net so far: ~−80 B across all builds.

*Done:*

- [x] ~~Phase A: repl.s stale TODO comment removed; loader.s
  `copy_pages` + `zero_pages` helpers; debugger.s `dbg_init` /
  `clear_bp_x` unified sweep; repl.s `peek_brk_opcode` dedup.~~
  (`7351292`)
- [x] ~~Phase B: repl.s `pre_userland_run` helper; dasm.s
  `_compute_branch_target` + `_emit_target` helpers.~~  (`fc52046`)
- [x] ~~SEI/CLI guards dropped from mem.s `kernal_bank_in/out` and
  asm_src.s `_bank_in_tmp` / `_bank_out_tmp` — the Phase 18 IRQ
  early-entry + `bank_out_stub` handles IRQ-during-bank-out
  transparently, so the I-flag management is redundant.~~
  (`8e60b62`)
- [x] ~~disk.s `_disk_open_buf` helper for the three SEQ/PRG OPEN
  sites (disk_load_seq, disk_save_seq, disk_save_prg).~~  (`778a1f4`)

*Evaluated and declined:*

- ~~Phase A: cse_exit_to_basic `and #$FD` removal — **false
  positive**.  That bank-out is required so the subsequent COLD_ZP
  reads resolve to the saved RAM copy at $F8DA (under KERNAL ROM),
  not to the ROM bytes.~~
- ~~Phase A: step_next_pc CMOS gating — **already done**.~~
- ~~Phase B: centralize `_bank_in_tmp` / `_bank_out_tmp` into mem.s
  — **false positive**.  They bypass mem.s's flag-gated helpers on
  purpose (asm_src runs inside a batch with `kernal_out = 1`).~~
- ~~Phase B: skipws_ep / skipws_as consolidation — **no net
  saving**.  Wrapper/macro approaches match or exceed current
  size.~~
- ~~Phase B: patch_all / unpatch_all shared skeleton — **load-
  bearing by design**.  The forward/reverse order is a correctness
  contract for overlapping user-bp / step-bp slots at the same
  address: forward-patch saves the real byte first (later slots
  save $00); reverse-unpatch writes the $00s first and the real
  byte last, leaving the user's RAM correct.  Uniform direction
  would corrupt overlapping addresses.~~
- ~~Phase D: editor.s ed_handle_key table dispatch — **not a size
  win**.  ~10-key cmp/bne chain is ~40 B; table + scan loop +
  indirect-jump glue would be ~56 B.  Could be a clarity win paired
  with handler-tail consolidation, but that's a separate refactor.~~

*Open — Phase C (stack / ZP wins, ~20 B code + ~6 B kernel stack):*

- [ ] **Phase C — promote hot state out of BSS into ZP, and out of
  the hardware stack into ZP scratch.**  Three sub-items:
  1. [screen.s scroll_up] Replace the `pha/pla` pairs for `n` /
     `src_row` / `dst_row` with ZP temps.  ~37 B ZP is free at
     $5B–$7F per zp.s.  Saves ~6 stack bytes per scroll + cycles
     per row.
  2. [asm_src.s .const handling] Similar `pha/pla` dance around
     name-folding.  Move to ZP scratch.  ~4 stack bytes, ~15 B code.
  3. Promote hot BSS flags to ZP: `stop_cooldown`, `dbg_reason`,
     `run_user_pending` — each read at multiple hot sites.  Each
     ZP promotion saves ~1 B code per access and a cycle per read.
     `in_userland` is debatable (only read in interrupt dispatch).
  Total estimate: ~20 B code, ~6 B kernel stack headroom, plus
  hot-path cycle wins in main_loop's `@wait` and scroll_up's row
  loop.

*Open — other small wins flagged during the sweep:*

- [ ] [main.s setup_interrupts] Four vector-write pairs could use a
  small helper or indexed loop.  ~10 B.
- [ ] [debugger.s _rtu_body sentinel push] Branch pattern could be
  slightly tighter.  ~2 B.

**CSE exit cleanup via KERNAL TIMB ($FE66).**  Instead of `cse_exit_to_basic`
hand-rolling the ZP restore + MEM_CONFIG reset + `jsr KERNAL_CINT +
jmp ($A002)` sequence, do only what's ours to undo (e.g. restore the
editor-specific ZP state we disturbed), then `jmp $FE66` (KERNAL's
TIMB — "warm-restart" entry used by BASIC's STOP+RESTORE path).
$FE66 reinitialises I/O, resets vectors, redraws screen, and drops
into BASIC READY.  Eliminates our manual teardown (~30 B code plus
the COLD_ZP KBSS area we reserve just for the restore).  Verify that
the KERNAL routine's prerequisites (banking, stack shape) are met
from our exit context.

- [ ] Table-drive `cmd_info`: replace procedural line-by-line
  memory map display with a data table + loop (~50-80 B saving).
- [ ] PRG/SEQ save dedup: `cmd_write` and `cmd_load` have shared
  patterns in filename parsing and stats display (~30-50 B).
- [ ] `exec_line` handler code sharing: inline `@h_*` handlers
  share common tail code (log_close, nl_clear, error paths).
  Factor into shared exit points.
- [ ] Disassembler `format_operand`: investigate table-driven
  formatting (packed format byte per mode, like Woz's Apple II
  disassembler) instead of procedural per-mode branches.
  Currently 220 B, could save ~80-100 B.
- [ ] Disassembler opcode table: investigate replacing the
  `aaabbbcc` bit-slice decoder with a compact 256-byte opcode
  lookup table.  Trades CODE (~350 B decode_cc00_mem alone)
  for RODATA (256 B).  Changes the architecture fundamentally.

### Architecture

- [ ] **Doc-audit Step 5 — examples-as-tests.**  The seven
  audit scripts under `dev/` (driven by `dev/audit_doc.py`)
  catch structural drift mechanically — broken cross-refs,
  numerical claims, BSS counts, owned-files coverage,
  depends-on accuracy.  What they don't catch is *executable*
  drift: code fences that no longer assemble, REPL command
  examples that no longer parse, or build-command snippets
  whose targets have been renamed.

  Step 5 of the doc-audit plan proposed a permanent regression
  net: a pytest fixture that, for each fenced code block in
  README.md / `doc/assembler_syntax.md` / `doc/modules/*.md`:

  1. Classifies the block by language hint (asm / repl /
     shell / output-sample).
  2. For asm blocks: feeds them through asm_assemble + checks
     for clean assembly (zero `;?<line>` errors).
  3. For repl blocks: parses the `AAAA:CMD` shape and
     dispatches via the test harness's `set_line_buf` +
     `exec_line`, asserting no error logs.
  4. For shell blocks: extracts `make TARGET` invocations and
     verifies the targets exist in the current Makefile.
  5. Output-samples (lines starting with `;` or matching the
     `; org AAAA-BBBB Nb` shape) are inert — skip with a
     comment.

  Estimated effort: ~1 full session (the harness already has
  most pieces — `cse_prg` fixture, `set_line_buf`, `exec_line`,
  `asm_assemble` test stubs).  Build-block extraction is the
  novel part.

  Why not v0.1: the structural audits already cover ~95% of
  documented drift.  Code-block drift is rare and self-flagging
  (a maintainer trying the example sees it fail).  Defer to
  v0.2 architecture sweep.

- [x] ~~**Multi-CPU integration-test parity.**~~  Closed
  2026-04-27.  Implemented as a coarse smoke check
  rather than a full per-CPU re-run of detailed contract
  tests, per the principle's actual intent (proving the
  boot path *executes* on every variant, not duplicating
  per-target contract assertions).  Detailed contract
  tests remain on the canonical CMOS-only `emu` fixture.
  Landed:
  - `cse_prg_per_cpu` fixture in
    [tests/conftest.py](../tests/conftest.py)
    (params=`["6510", "6502", "cmos"]`).
  - `emu_per_cpu` fixture +
    `TestBootsCleanly::test_cold_init_completes` in
    [tests/integration/test_kernel_transition.py](
    ../tests/integration/test_kernel_transition.py) —
    pytest expands to 3 invocations.
  - [doc/testing.md § Principle 18](
    testing.md#principles) clarified to spell out the
    coarse-vs-detailed division of labour.

  All three variants currently pass.  Confirms the
  Phase-24 prediction that the heap-corruption root
  cause was CPU-agnostic; F1 + F2 fixed all three even
  though only CMOS was directly tested at fix time.

- [x] ~~**Triage the 17 cold-init-fragile tests in
  test_kernel_transition.py.**~~  Closed 2026-04-27 as a no-op:
  all 17 tests have been stable green across the F1, F2,
  multi-CPU smoke, and cleanup commits with no per-test
  changes — exactly as the bug entry's prediction table
  forecast.  The fragility was a manifestation of the
  cold-init heap-corruption bug; with the corruption fixed,
  the underlying contracts each test asserts are sound and
  the tests pass cleanly.  No `_minimal_init` rewrites, no
  Pattern A skips, no retentions-with-caveats needed.

- [x] ~~**Retire `src/mn_config.s`**~~ (closed 2026-04-25).
  Removed from `Makefile` (ASM_SRCS + TABLE_OUTS), from
  `dev/mnemonic_tables.py` (deleted dead `write_config_table`
  function and its caller stub; tidied generator-doc comments
  that referenced it), and from `dev/size_report.py`.  Source
  file deleted.  Doc updates: `mn_classify.md` Owned files row
  removed, `architecture.md` Generated-files + L0 leaves listings
  pruned, `testing.md` Principle 12 + per-module tier table
  pruned, `build_system.md` generator outputs row corrected
  (also gained `oplen_tbl.s` which was missing).  Build verified:
  `make tables` clean, `make CPU=6510` produces a 21031-byte
  PRG (was 21287, exactly **−256 B saved per build variant**;
  3051 tests pass, 18 expected skips).

- [x] Relocating startup: done (Roadmap R2, Session 10).

- [x] **PETSCII pipeline unification + expr_eval in line assembler.**
  Phase-level work (~2-3 sessions).  Estimated savings: ~474 B
  CODE + 80 B BSS.  Eliminates the VICII/PETSCII encoding split,
  the `_insn_buf` round-trip, and the duplicate hex parser.  Gives
  the `.` command full expression support (labels, arithmetic) for
  free.  Four steps:

  **Step 1 — Hash encoding: resolved, no work needed.** (Phase 12)
  AND #$1F normalization in `_asm_rd_upper` maps PETSCII
  uppercase ($41–$5A), PETSCII lowercase ($61–$7A), and VICII
  screen codes ($01–$1A) identically to 1–26.  All hash tables,
  fingerprint tables, and T arrays are encoding-agnostic.

  **Step 2 — Switch assembler pipeline to PETSCII + rename.** (Phase 12, done)
  Merged asm_bridge.s into asm_line.s (KERNAL banking, error
  recovery, SP save/restore).  Deleted PETSCII→VICII conversion
  loop.  au_mode.s operates on PETSCII: SC_* constants updated
  (A=$41, X=$58, Y=$59), hex ranges ($41–$46 for A–F).
  Renamed: `al_` → `asm_`, `au_` → `asm_`/`mode_` across all
  source, test, stub, and doc files.  2788 tests pass.

  **Step 3 — Replace mode_parse hex parser with expr_eval.** (Phase 12, done)
  Removed `_au_rd_nib`, `_au_rd_byte`, `_au_is_hex` (-73 B).
  mode_parse calls `_au_read_val` → `expr_eval_nb` (no-banking
  variant).  Operands now accept `$hex`, `%binary`, decimal,
  labels, `*`, and arithmetic.  Fixed `hex_nybble` in expr.s
  to accept uppercase A-F (`ora #$20` case fold; numeric constants
  for portability across ca65 `-t c64` and plain `--cpu 6502`).
  Test framework: asm_core bundle replaces per-module test binaries.
  Pass flag deferred to Step 4.  2797 tests pass.

  **Step 4 — Unify source assembler with line assembler.** (Phase 12, done)
  asm_src.s passes expanded source text directly to asm_line instead
  of pre-evaluating expressions and reconstructing hex.  Removed:
  hex_tab (16 B RODATA), mode detection (#/( flags), expression
  evaluation, hex formatting, suffix copying (~197 B total).
  Local label expansion (.name → scope.name) stays in asm_src.
  Forward-reference handling: pass flag (asm_pass) in _au_read_val
  substitutes asm_pc+2 on pass 0 when symbols are undefined.
  DEFAULT_CPU moved from asm_line.s to main.s init.
  ACC detection in mode_parse hardened: bare 'A' only if followed
  by end/whitespace (not identifier chars like label names).
  2797 tests pass.
- [x] ~~BSS optimization: overlap with `ws_buf`~~ (moot: `ws_buf`
  removed in smart indent rewrite, Phase 15)
- [x] **Back-links for every test file.**  Only 16 of the 44
  Python files under `tests/` carry the `Owner:` line the
  back-link convention requires
  ([README.md § Ownership](README.md#ownership)); the files the
  M65Emu work touched have theirs (CDD audit, 2026-11-17).  Add
  the line (and `Contract source:`) to the rest, owner
  `doc/build_system.md`, or exempt a file explicitly in its row.
  Done 2026-11-17, with the next item: every non-exempt file under CDD
  regime (src/, tests/, dev/, rom/, the Makefile) carries its
  back-link; generated tables, binaries, the two files shared verbatim
  with bbbc64 and the hash-search outputs are exempt in their rows.

- [x] **Ownership audit outside `src/`.**  `dev/audit_doc_owned_files.py`
  checks module docs against `src/` only; nothing checks the Owned
  files table of `doc/build_system.md` (`tests/`, `dev/`, `rom/`,
  fixtures) for completeness, uniqueness or back-links, which is how
  an unclaimed `rom/README.md`, missing back-links and binary rows
  without `back-link-exempt` went unnoticed until the 2026-11-17 CDD
  audit.  Extend the script to every Owned files table and every
  file under CDD regime.  Done 2026-11-17 (`test_audit_owned_files.py`);
  the first run found 14 unclaimed files, 4 files with two owners
  (resolved by owner-of-record: the earlier claim stays, the later one
  became a cross-reference), 82 missing back-links and 2 binaries
  without exemption — all fixed.

- [x] **Historical-marker sweep outside `doc/` and `src/`.**
  `dev/audit_phase_markers.py` (CDD Maintenance item 9) scans `doc/`
  and `src/` only; source comments and docstrings under `tests/` and
  `dev/` are not swept (CDD audit, 2026-11-17).  Add them.  Done
  2026-11-17 (`dev/search/` excepted); of the 40 new hits, 23 stale
  ones were retired, the 17 left are load-bearing (named design
  phases, quoted docs) or the sweep's own patterns.

- [ ] **ZP swap: extend isolation to KERNAL screen-edit zone
  (`$C0-$FF`).**  Today `save_userland_zp` / `save_kernel_zp`
  swap only `$00-$7F` between userland and CSE-kernel views
  (`ZP_SAVE_LO=$00`, `ZP_SAVE_LEN=128`, see [doc/modules/mem.md](
  modules/mem.md)).  The KERNAL screen-edit zone (`$C6/$C8/$CC/
  $CE/$D0-$F2`) is shared — userland code that touches any of
  these bytes (custom IRQ, screen tricks, tape state) leaks into
  CSE-kernel CHROUT and vice-versa.

  *C-split* design (analysed 2026-04-30 alongside the
  RESTORE-during-CHROUT bug fix above): keep the existing
  `$00-$7F` zone, add a second `$C0-$FF` zone (64 B, two buffers
  → +128 B BSS).  Skip `$80-$BF` to avoid disturbing the KERNAL
  jiffy clock at `$A0-$A2` (continuously running across modes
  today; userland may rely on this) and tape/file scratch state.
  Cost: +128 B BSS, +~25 B code (second loop body), +~1 K cycles
  (≈1 ms) per userland↔kernel transition.

  Side benefit: provides a free generalisation of the rc1-fix
  Approach B above.  Today `screen.s::_kernal_screen_reset`
  resets a *fixed enumeration* of bytes (`$D5/$D9-$F1/$D8/$D4/
  $CE/$C6`); with C-split + a one-shot pristine snapshot
  captured at init, the kernel-mode NMI path could `restore
  kernel_zp` from that snapshot and recover *any* corrupted
  byte in `$C0-$FF` — not just the enumerated ones.  Eliminates
  the "did we list every byte CHROUT touches?" risk that was
  Approach B's documented weakness.

  Pairs naturally with a future architectural sweep that
  audits userland↔kernel state isolation; not blocking on the
  RESTORE bug fix (B already covers it for v0.1).
  See `doc/TODO.md` § Bugs § RESTORE-during-CHROUT for the full
  three-way A/B/C analysis that produced this entry.

- [ ] **Split `run_user_pending` into pre-dispatch and
  post-return flags.**  Today the byte serves two purposes:

  - (A) "Command set MODE; needs userland dispatch" — written
    by `cmd_jmp` / `cmd_step` / `cmd_continue`, consumed by
    `main_loop @not_enter` and (since the rc4 fix) by
    `main_loop_top @live` warm-cont path.  Drives `jmp
    return_to_userland` / `jmp restore_userland_state`.
  - (B) "User code returned; needs cleanup" — same byte
    survives the RTI/userland round-trip; consumed by
    `main_loop_top @check_post_run` to fire `post_run_cleanup`.

  Phase A → B transition relies on the dispatch *not* clearing
  the flag.  Any caller that runs `exec_line` and then
  re-enters `main_loop_top` without dispatching falsely
  conflates A as B — exactly the rc4 bug shape (a+g+NMI+g
  produced a phantom brk because the warm-cont replay set A
  but no dispatch fired, then `@check_post_run` consumed it
  as B).  Fixed in `main.s` commit `5bd916b` by adding the
  dispatch.

  Proposed split: `run_pending_mode` (A) and `run_returned`
  (B).  Each has a single writer-set, single reader-consume
  contract.  The dispatch (return_to_userland or
  restore_userland_state's prologue) sets `run_returned` and
  clears `run_pending_mode`.  The handler/userland-return
  path leaves `run_returned` set; `@check_post_run` consumes
  it.  Cost: +1 B BSS, ~+10 B code (extra clearing logic),
  removes the dual-purpose ambiguity entirely.

  Not blocking: rc4's fix closes the only known manifestation.
  File for the v0.2 architecture sweep.  See [§ Bugs](#bugs)
  § "BUG a+g+NMI+g phantom brk" for the rc4 audit chain.

- [ ] **Close the `cse_refresh` micro-race on `run_user_pending`.**
  When kernel-mode NMI fires in the ~5–10 cycle window
  between a command setting `run_user_pending` (e.g.
  `cmd_jmp.@run`'s `sta run_user_pending`) and `main_loop
  @not_enter`'s post-exec dispatch reading it, `cse_refresh`
  runs while the flag is set.  Falls through to
  `main_loop_top @check_post_run` which interprets the flag
  as a "just returned from userland" signal and runs
  `post_run_cleanup` against `brk_pc=cur_addr` — phantom
  break display.

  Not exploitable in practice: the window is microseconds in
  idle code paths and the user can recover by typing the
  command again.  But it's the only remaining path where
  the rc4 bug class can manifest, so worth closing.

  Two ways to close it:
  - **Cheap:** `lda #0; sta run_user_pending` in
    `refresh_body` (or in `cse_refresh` proper).  +4 B.
    Side effect: also clears the flag on legitimate RESTORE-
    after-userland-return cycles, suppressing any redisplay
    of break/regs that depended on the dual-purpose flag.
    **Verify** the existing "show break info on RESTORE"
    behaviour against
    `tests/integration/test_kernel_transition.py::TestNmiKernelMode::test_refresh_preserves_run_user_pending`
    — that test pins the current preserve-the-flag contract;
    landing this fix means flipping the test's assertion.
  - **Comprehensive:** Land the run_user_pending split above;
    `cse_refresh` clears `run_pending_mode` but not
    `run_returned`.  Race window closes cleanly without
    affecting the redisplay behaviour.

  Recommendation: bundle with the dual-purpose split (the
  comprehensive option) rather than landing the cheap fix
  in isolation.

- [ ] BSS optimization: collapse `disk_seq_bytes`/`disk_seq_lines`
  with `ed_save_bytes`/`ed_save_lines` (saves 4 B).
- [ ] BSS optimization: overlap `rp_next_lo`/`rp_next_hi` with
  `rp_hexbuf` + `@new_col` (saves 3-4 B).
- [ ] Test framework: migrate dasm, expr, repl test binaries to bundle
  pattern or C64Emu integration tests.  Eliminates per-module stubs.
  See testing.md § Test bundle architecture.
- [x] Central `zp.s` owning the entire zero-page layout.  (Phase 12, done)
  All 85 ZP bytes defined in `src/zp.s` with `.exportzp`.  13 modules
  migrated from local `.segment "ZEROPAGE"` to `.importzp`.  `asm_vars.s`
  deleted (role absorbed by zp.s).  All test stubs and configs updated
  to link zp.s.  Pure refactor: 0 bytes size change, 2797 tests pass.
- [x] ~~CDD template drift~~ (fixed: moved `### Memory` before
  `**Depends on:**` in 11 module docs; Phase 15 audit remediation)
- [x] ~~Missing module doc: `src/mem.s`~~ (fixed: `doc/modules/mem.md`
  created; Phase 15 audit remediation)
- [x] ~~Missing module doc: `src/loader.s` has no `doc/modules/*.md`.~~
  (fixed 2026-04-25: `doc/modules/loader.md` created during Phase 23
  CDD Maintenance round.)
- [x] ~~debugger.md: all symbol names use `_` prefix~~ (fixed:
  stripped `_` prefix from all symbol names throughout the document
  to match actual exports; Phase 17 CDD Maintenance)
- [x] ~~README: missing `.bas` directive~~ (fixed: Phase 15 audit)
- [x] ~~README: `a` command description says "advances past assembled
  code"~~ (fixed: README now reads "Assemble source from editor
  at current address")
- [x] ~~README: "gap buffer grows down from $D000"~~ (fixed: Phase 15)
- [x] ~~editor.md + memory_design.md: `BUF_END` / gap buffer described
  as `$D000`~~ (fixed: updated to `__CODE_RUN__` in editor.md ×3
  and memory_design.md Design Principle 5; Phase 17 CDD Maintenance)
- [ ] Export `LOG_INFO`, `LOG_WARN`, `LOG_ERR` from repl.s so
  consumers (main.s, asm_src.s, disk.s) can import them instead
  of redefining locally.
- [x] ~~Dedup asm_src segment formatter with cmd_info free-line~~
  (fixed: shared `range_line` with two entry points `free_line`
  (suffix "b free") and `seg_line` (suffix "b").  Right-aligned
  5-digit decimal, 1-space gutter.  `s_seg_pfx` removed.  Phase 17)
- [x] ~~Rework `asm_src.s` newline handling~~ (fixed: removed 4
  redundant `jsr newline` calls; `log_close` provides trailing
  newline.  "asm..." line now uses `log_close` instead of bare
  `io_clear_eol`.  `seg_print_save` no longer needs its own
  newline.  Phase 17)
- [x] ~~Global release version: single `VERSION` propagation.~~
  (Phase 19 — done: Makefile generates `build/version.inc`
  per-build; strings.s `.include`s it and composes
  `VERSION_STR` as `"cse v" + VERSION_STRING + " by cr"`.  The
  D64 label format became `cse $(VERSION),01`.  PRG filenames
  stay stable.  See [build_system.md § Version propagation](build_system.md#version-propagation).)

## Roadmap

Long-term milestones in dependency order.

### R1 — Compile-time CPU gating (done)

All CPU-specific code gated with `.ifdef`/`.ifndef` instead of
runtime checks.

### R2 — Relocating startup (done)

CSE runtime relocated to high memory (floating start, page-aligned,
ending at $CFFF).  Discardable loader at $080D copies CODE+RODATA
at boot.  Two-pass link auto-computes runtime start address.
Workspace at $0800, ~30 KB free.  Exomizer SFX compression for
D64 distribution (~38% smaller).

### R3 — Universal C64/C128 binary

Single PRG runs on both machines.  Machine differences isolated to
three leaf functions (banking, NMI trampoline, keyboard).

### R4 — 80-column VDC mode (C128 only)

Self-contained VDC display driver, same interface as VIC-II routines.

### R5 — Cartridge ROM (CRT)

Build target for at least one CRT layout.  Candidates: Ocean Type 1
(simple banked ROM, wide emulator support) or EasyFlash (2×64 banks,
writable, real-hardware friendly).  Dual linker configs — one for
PRG, one for CRT.  Instant boot, no loader needed.  R2 (relocating
startup) provides the foundation: CODE+RODATA already position-
independent relative to their link address.

### R6 — Port C to asm (done)

All C ported to assembly.  cc65 C compiler eliminated.

### R7 — MEGA65 native support (in progress)

Native MEGA65 platform target, separate from C64-compatible mode.
The MEGA65 is a much more capable machine (32-bit address space,
relocated ZP internals in native mode, VIC-IV) requiring bigger
adaptations than a compatibility shim.  Alongside C128 native
(R3/R4), this would be a distinct platform target with its own
screen driver and memory model.  Slice 1 — the CPU layer (assembler
and disassembler) — is active: see
[M65](#m65--the-45gs02-assembler-and-disassembler-r7-slice-1).
Slice 2 — the platform layer, shipped as a MEGA65-mode PRG at
`$2001` with a D81 — follows it: see
[M65 slice 2](#m65-slice-2--the-mega65-prg-r7-platform-layer).
The dependency on R3 applies to the platform layer (screen, memory,
KERNAL), not to the CPU layer; whether slice 2 waits for R3 or does
the platform isolation itself is S2-Q6.

## Ideas

Exploratory, not yet scoped.

### Keyboard & input

- [ ] KERNAL keyboard CTRL combos: explore what key combinations
  the default KERNAL keyboard I/O delivers.  CTRL+key produces
  PETSCII control codes ($01–$1F) — identify which are usable
  without conflicting with KERNAL screen editor behaviour.
- [ ] SHIFT+CLR/HOME in REPL: clear screen.  C=+CLR/HOME: clear
  from cursor to end of screen.  Both use KERNAL screen editor
  codes (SHIFT+CLR = $93, CLR/HOME = $13).
- [ ] F-key bindings: assign useful functions to F1–F8 in both
  REPL and editor.  REPL candidates: help, repeat last command,
  toggle hex/dec, disassemble at PC.  Editor candidates: save,
  assemble, goto line, search.
- [x] Revise RUN/STOP+RESTORE and NMI handling.  (Phase 14, done)
  Permanent NMI dispatcher (`cse_nmi_handler`) at $0318.
  NMI-in-REPL → `cse_warm_screen` (clean screen recovery).
  Internal BRK → `cse_warm_start` (idempotent hard recovery).
  Warm-start re-entry guard prevents infinite BRK loops.
  NMI trampoline no longer corrupts $01.

### Features

- [ ] PRG load: auto-detect load address from PRG header.
- [ ] `$` command: filter directory listing by filename glob.
- [ ] `d` command: show ASCII alongside disassembly (like `m`).
- [ ] `.` command: show help when mnemonic given without operand.
- [ ] Color command `C`: show color preview swatches.
- [ ] Disk I/O: timeout handling for unresponsive drives.
- [x] NMI during `j` user code.  (Phase 14, done)
  `cse_nmi_handler` dispatches on `dbg_running` — user-code
  NMI breaks into debugger immediately via `dbg_nmi_break`.
- [ ] REU support for large source files.
- [ ] Macro support: .macro/.endmacro.
- [ ] Conditional assembly: .if/.else/.endif.
- [ ] Include files: .inc.
- [ ] `.brk [n]` directive: emit a 2-byte BRK instruction (BRK
  opcode + signature byte).  Optional `n` is the signature byte
  (default 0).  Replaces the verbose `brk; .db $XX` pattern that
  the lazy-debug user-BRK workflow currently requires (see
  debugger.md § User BRK workflow).  Without `.brk`, the user
  must manually pair `brk` with `.db $XX`; forgetting the .db
  loses the next code byte to CSE's STEP_OVER / continue +2 skip.
  `.brk` makes the convention explicit and forgive-by-default.
  Use cases: `.brk` (default sig byte 0), `.brk $42` (custom),
  `.brk MARKER` (expression).  Single line in source maps to
  the canonical 2-byte BRK that matches CPU's RTI semantics.
  *(Demoted from Planned 2026-04-28: nice-to-have, not release-
  relevant — the manual `brk; .db $XX` pairing is documented and
  works.)*
- [ ] Assembler error display: show source line number + context.
  *(Demoted from Planned 2026-04-28: nice-to-have, not release-
  relevant — current `;? <line> : <message>` carries the line
  number; the source-context preview is a polish item.)*
- [ ] Assembler: `a` source-assemble warn+ask when emit
  destination is outside [workstart, workend].  `.org $f100\nlda #0`
  silently writes to KDATA today.  Same risk class as bug 3
  (CSE state corruption during a debug workflow), same gate
  range.  Pattern: per-segment check at `_seg_log_open` time
  (or per-byte at emit time, whichever has the lower overhead);
  if first emit address is out-of-range, prompt
  `;!range / asm? y/n`.  Yes proceeds (user override); no
  cancels the assemble.  This is the only sibling from bug 3's
  sweep judged worth chasing — other footguns (m-poke,
  .-assemble at `@`-set cur_addr, l-to-address) are explicit
  user actions and stay un-gated; the assemble case is special
  because `.org` lives in source code and is easy to typo into
  CSE-shadow ranges without realising.
  *(Demoted from Bugs 2026-04-28: not release-relevant — the
  user can see workmem and is expected to comply.)*
- [ ] Detect PAL/NTSC at startup.
- [ ] MEGA65 Open-KERNAL compatibility (C64-compatible mode):
  `$` works (LOAD-based).  Floppy status empty (shows `; `)
  — blocked on upstream IEC channel-I/O fixes
  (MEGA65/open-roms#116, #117).  Channel-based dir code
  preserved in `1348247` for when fixes land.  All other
  features work.  Native mode is roadmap R7.
- [ ] CDD back-reference tracking: link source files to their
  documentation via a machine-readable index.  CDD Maintenance
  verifies code changes trigger doc updates for all covering
  documents.
- [x] ~~**RESTORE-only screen recovery.**~~  (Phase 20 — done
  alongside the warmstart restructure.  NMI in kernel mode now
  routes directly to `cse_refresh` instead of swallowing, so
  RUN/STOP+RESTORE at the REPL gets the user their view back —
  the classic C64 affordance.  Debug context is preserved across
  the NMI.  See [main.md § cse_nmi_handler](modules/main.md)
  and [memory_design.md § Warmstart entry points](memory_design.md#warmstart-entry-points).)
