# CSE — TODO

## M65 — the 45GS02 assembler and disassembler (R7, slice 1)

**Branch:** `m65` (cut from `main` @ 910d96d, 2026-11-16).
**Goal:** the m65 platform's CPU layer — line assembler, source
assembler and disassembler for the 45GS02, with the 4510 and the
6502 as runtime alternatives (D-P4b-1; D-P4-10's 65C02 member
dropped) — built from the one
instruction set that serves every build.  The rest of R7 (screen driver, memory
model, KERNAL interface, debugger) is not this slice: it is
[slice 2](#m65-slice-2--the-mega65-platform-r7-platform-layer), the
platform layer.  **Order (operator, 2026-11-18):** Phase B and A3b
waited for slice 2's P0–P2 — the m65 build had to exist, boot and run
user code before the CPU layer was finished on it.  **Status
(2026-11-19):** Phase A done but A5; Phase B done as slice 2's P4;
A3b deferred (D-P4-4).

**Hard constraint (operator, 2026-11-16):** no change made for the
m65 target may make any C64 build bigger or significantly slower.
Tables grow only where the platform is m65.

**Rationale — one source, one format, sized per build.**
`dev/instruction_set.py` is the single source of every opcode fact
for every build (operator ruling, 2026-11-16).  Before Phase A two
consumers re-stated facts in hand-written code: `opcode_lookup.s` (five
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
row colouring, 20 modes):** 36 profiles, 7 delta rows, ≈ 284 B of
masks + rows + index — an estimate; the set built in P4 step (3) has
45 profiles and 7 × 20 rows (its record below).  The C64 sets are built — see
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
- [ ] A3b. *(follow-up, own CDD cycle; deferred past P4, operator
  2026-11-19 — P4 puts its new state in BSS)* Recompact ZP over the freed
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
  round trip over every row (done for the m65 set in P4, T7); generator tests (placement rules refuse
  violating input, minimal row count, no foreign entries per block).

### Phase B — the m65 build (m65-45gs02)

- [x] B1. Build defines `PLATFORM_M65`, `CPU_45GS02`, `MEGA_SUPPORT`;
  `asm_cpu` values 3 and 4 (6502 and 4510 selectable at run time;
  D-P4-10 added the 65C02, `asm_cpu` 2, D-P4b-1 dropped it again); m65
  test bundles ([build_system.md](build_system.md)).
- [x] B2. Classifier: `mn7` over the m65 key set
  ([mn_classify.md § Variants](modules/mn_classify.md#variants)).
- [x] B3. `mode_parse`: `(e),z`, `(e,sp),y`, `[e]`, `[e],z`
  ([addr_mode.md](modules/addr_mode.md)); the wide immediate is
  asm_line's IMM16 promotion (B4).
- [x] B4. `asm_line`: mnemonic suffix (digit, `q`), Q zone, far flag,
  prefix emission, `REL`/`REL16` selection, the m65 gate matrix
  ([asm_line.md](modules/asm_line.md)).
- [x] B4b. Pass-stable branch width.  The pass stamp itself landed on
  every build with the later-defined ZP constant fix (f13e739:
  `sym_stamp` / `sym_fwd`, `expr_fwd`, asm_src's per-pass stamp —
  [symtab.md § Pass stamp](modules/symtab.md#pass-stamp-mega_support));
  zone B's `REL` / `REL16` choice reads `expr_fwd` (B4, P4 step (5)).
- [x] B5. `.cpu` / `u` on m65 ([assembler_syntax.md](assembler_syntax.md),
  [repl.md](modules/repl.md)).
- [x] B6. `dasm_insn`: prefix peel, m65 modes, 1–5-byte length
  ([dasm.md](modules/dasm.md)).
- [x] B7. REPL `.` / `d`: hex columns = the build's maximum length;
  `dot_assemble` passes suffixes, `[`, `,z`, `,sp`
  ([repl.md](modules/repl.md)).

### Prerequisite bug (separate fix, lands before B4)

- [x] **Bit-op mnemonics are not assembled.**  (Fixed in P4 step (1), 2026-11-19.)  `asm_line.s` zones D/E
  (`RMB`/`SMB`/`BBR`/`BBS`) are `jmp asm_error` ("not yet tested"),
  while [asm_line.md](modules/asm_line.md) documents them as working;
  `dot_assemble` also stops the mnemonic at the first digit.  Affects
  c64-65c02 today; the 4510 keeps all four.  Fix under its own CDD
  cycle (digit suffix scan + digit zone), then B4 builds on it.

- [x] **`.cpu` and `u` do not enforce the CPU set.**  (Fixed in P4 step (2), 2026-11-19.)  `asm_src.s::set_cpu`
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

- [x] **Debugger single-step on m65.**  (Done in P4 step (9), 60c2c1c.)  `debugger.s::step_next_pc`
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
  default, 6502 and 4510 selectable at run time (amended by D-P4-10:
  the 65C02 too; D-P4b-1: not again).  One feature define,
  `MEGA_SUPPORT`.
- **D1. Branch width under forward references:** the per-pass symbol
  stamp (B4b) — a target read before its definition in the current
  pass takes `REL`; otherwise by distance.
- **D2.** c64-65c02's CPU set includes 6510 (see the `.cpu`/`u` bug).
  (Superseded by D-P4b-1/-2: no c64-65c02 build; the CMOS mode is
  {6502, 65C02}.)
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

## M65 slice 2 — the MEGA65 platform (R7, platform layer)

**Branch:** `m65`.  **Status (2026-11-19):** the harness (S2-3), P0
(the m65 PRG installs itself and reaches `_main`), P1 (user code,
maps, vectors and the debugger on m65), P2 (the screen, the keyboard,
the REPL and the editor) and P3 (the disk and the D81) and P4 (the 45GS02 assembler, disassembler
and step — slice 1's Phase B) and P4b (no 65C02 on the targets; the
assembler's CMOS mode bundle-only) are done; P5 is next.

**How this plan is read.**  Under CDD the documents are the truth:
each milestone below is a **Step-1 doc delta** — the documents that
are written to their desired state and what they will state.  The
CDD Analysis (doc against code), its approval, the TDD Analysis and
the code follow *from* the delta, mechanically; an implementation
line under a milestone only says which contract the code and tests
will satisfy, it is not a second plan.  Where a seam's m65 body is
not yet stated, the document says *stated with P<n>* and the
milestone's delta fills it in.

**Order (operator, 2026-11-18).**  The platform first: before the
ZP recompaction (slice 1 A3b) and before the 45GS02 assembler and
disassembler (slice 1 Phase B), the m65 build must exist, install
itself where it belongs and reach the cold boot vector (P0); then
user code, maps, vectors and the debugger (P1, foundational), then
the screen and keyboard (P2).  Phase B and P3–P5 follow.

### Rulings (operator, 2026-11-17/18)

- **Native, not GO64.**  The m65 build runs in MEGA65 mode on the
  MEGA65 KERNAL.  **ROM floor: 920413** (the stable release, 0.97); a
  later beta becomes the floor only for a good reason.  No C65 ROMs
  (2026-11-18).
- **Distribution: PRG, D81 and a MEGA65-style CRT** (amended
  2026-11-19: the first release is PRG and D81 only, the CRT a later
  release's — § Later release: the m65 cartridge) per the
  MEGA65-style cartridge standard
  ([wiki, work in progress](https://mega65.atlassian.net/wiki/spaces/MEGA65/pages/36962324/MEGA65+Style+Cartridge+Work+in+Progress));
  the standard is in flux, we follow it.  (The image's type and size
  are the later release's: A3's record.)
- **Home: the ROM banks.**  The loader lifts the ROM write
  protection and installs the code in C65 BASIC's 24 K (`3.2000`) and
  the data structures in BASIC's 16 K graphics bank (`3.8000`).
  **Nothing under the KERNAL, no C64-style banking tricks.**
- **The premise is a RUN-started program** (2026-11-18): user code
  runs in the machine a BASIC 65 `SYS` gives — its map, registers,
  stack and free memory — as closely as sensibly possible, and CSE
  moves to where it least disturbs that: ROM banks 2–3 (C65 BASIC,
  BASIC 65's graphics material, the C64-mode ROMs — nothing the
  MEGA65-mode KERNAL uses) and one page of bank 0, `0.1F00`, BASIC
  65's bitmap base page.  Bank 0 (with `0.1600–0.1EFF`), bank 1,
  banks 4 and 5 and the Attic stay the user's.
- **The source text lives in bank 2**, `2.4000–2.BFFF` (32 K), with
  its base and ceiling as constants so it can move (2026-11-18).
- **Cross-bank pointers are 32-bit** (D1, 2026-11-18): every pointer
  that may reach memory outside the kernel's 16-bit view is a far
  pointer — 4 bytes on m65, the bank set where the pointer is set;
  CSE runs with its own base page (`0.1F00`, `B = $1F`) to hold
  them, and calls the KERNAL with `B = 0` (`KCALL`).  No MAP windows:
  `MAP`'s one offset per 32 K half is taken by the KERNAL (upper) and
  bank 0 plus the code (lower).
- **Inline platform sites are macros** (D2, 2026-11-18): their c64
  expansion is today's code, so the C64 builds stay byte-identical.
- **The ROM is RAM loaded by the Hypervisor**, not a shadow: quitting
  (`Q`) ends in a Hypervisor reset (`hyppo_reset`).  No stash.
- **No exomizer on m65**; the PRG and the D81 ship raw.
- **The KERNAL API, not its internals**: jump table and vector
  table only; full past-present-future KERNAL compatibility
  outranks speed.
- **Screen: 80 × 25 by default**, 80 × 50 and 40 × 25 by ESC 5 / ESC
  8 / ESC 4; the MEGA65's new keys and combinations supported where
  possible.
- **Clean 6502 code**; 45GS02-only instructions as raw bytes from
  one macro include.
- **No code duplication**: one module, one interface, the
  platform's body by `.ifdef` — the platform driver layer of
  [platform_layer.md](platform_layer.md).
- **The C64 builds do not change** (byte-identical through every
  step; the slice-1 hard constraint).
- **M65Emu** is the m65 build's Tier I, xmega65 its Tier X, the
  hardware confirms (S2-3, done).
- **Commits** name the model that made the major contribution.

### The doc layer

The documents that carry the m65 contract, and what each owns.  The
MEGA65 Book and the cartridge wiki page are the authorities for the
machine; the documents cite them per seam
([platform_layer.md § Platform references](platform_layer.md#platform-references))
and do not restate them, and every citation is re-verified in
xmega65 by the milestone that relies on it.

| Document | Owns, for m65 |
|---|---|
| [platform_layer.md](platform_layer.md) | the seams and their contracts per platform; the no-literals rule; the gates |
| [memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode) | the run premise, the two maps, the banks, the stub's place, the installed machine, interrupts; § Source Code Storage for bank 2 |
| [userland_contract.md](userland_contract.md) | what a user program owns and may rely on, per platform; what survives a run and `Q` |
| [build_system.md § The m65 builds](build_system.md#the-m65-builds) | `PLATFORM=m65`, the defines, the linker layout per bank, the PRG, the D81, no exomizer, the m65 gates |
| [testing.md](testing.md) | the m65 PRG fixture and Tier I on M65Emu, Tier X, the ROM versions the port is verified on, the byte-identical gate and the literal audit as tests |
| [architecture.md](architecture.md) | the driver as a role of the leaves (rule 9) |
| [README.md](../README.md) | the MEGA65 chapter: starting from the PRG or the D81, screen modes, keys, memory for your programs, `Q`, `i` |
| [glossary.md](glossary.md) | CSE map, user map, resident stub, seam, the `b.xxxx` notation |
| module docs | each seam host's Interface states the per-platform body or points to platform_layer.md: [mem.md](modules/mem.md), [cse_io.md](modules/cse_io.md), [screen.md](modules/screen.md), [main.md](modules/main.md), [loader.md](modules/loader.md), [disk.md](modules/disk.md), [gap_buffer.md](modules/gap_buffer.md), [debugger.md](modules/debugger.md), [breakpoints.md](modules/breakpoints.md), [zp.md](modules/zp.md); [editor.md](modules/editor.md), [repl.md](modules/repl.md), [log.md](modules/log.md) state that they carry no platform knowledge and are width-driven |

### Milestones

**P0 — the build exists and boots to the cold vector.**

Step-1 delta, first round (2026-11-18; **superseded** where the second round below differs — kept as the record):
- [x] [platform_layer.md](platform_layer.md): the rule, the seams, the
  c64 column in full, the m65 column for the memory, transition,
  vector, frame, cold-start/exit and loader seams.  (Written and approved
  2026-11-18.)
- [x] [memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)
  and § Source Code Storage: the maps, banks, stub, install,
  interrupts, exit, bank 1.  (Written and approved 2026-11-18.)
- [x] [build_system.md § The m65 builds](build_system.md#the-m65-builds):
  the defines (`PLATFORM_C64` / `PLATFORM_M65`, `CPU_45GS02`,
  `MEGA_SUPPORT`), `-t c64` for PETSCII, the segments per bank with
  their linker bounds, the raw PRG, D81 and 32 K cartridge, no
  exomizer, the gates.  (Written and approved 2026-11-18.)
- [x] [testing.md](testing.md): the platform-layer gates (literal
  audit; the C64 PRG hashes, `c64_prg_sha256.json`), § The m65 PRG on
  M65Emu (fixtures, the real loader run, `load_prg()`/`init_cse()`,
  the one Hypervisor trap modelled, Tier X boot).  (Written and approved
  2026-11-18.)
- [x] [loader.md](modules/loader.md) (the m65 entry, the seven-step
  sequence, the ROM-version refusal), [mem.md](modules/mem.md)
  (banking no-ops, `cse_start` on m65, the resident stub and its
  target words), [main.md](modules/main.md) (`_main`,
  `setup_interrupts`, the per-step cold-init differences, the fallback,
  the exit), [gap_buffer.md](modules/gap_buffer.md) (bank 1,
  `SRC_LDA`/`SRC_STA`, `workstart`/`workend`), [zp.md](modules/zp.md)
  (`umem_fp`, P-Q4), [glossary.md](glossary.md) (bank notation, the
  two maps, stub, flat pointer, Hypervisor reset, platform driver
  layer, seam).  (Written and approved 2026-11-18.)
- [x] [userland_contract.md § 3](userland_contract.md#3-memory-regions):
  the m65 regions.  (Written and approved 2026-11-18.)
- [x] Corrections to the approved deltas, from the post-boot snapshot
  and the CPU recording (2026-11-18): the CSE map's MAPLO is `$E3`,
  not `$F3` (block 0 stays unmapped; the CSE map is BASIC 65's own
  map); `EOM` releases `MAP`'s interrupt hold and leaves the I flag
  alone; the CPU-port seeds are `$FF`/`$85`; the user transition
  carries the user's registers on the stack (`PLAT_TO_USER`,
  `stub_user`); one shared flat pointer instead of 4-byte pointers;
  no user-memory block copy; no cold-init ZP snapshot on m65; the
  quit command is `Q`, not `x`.

**P0 analysis record (2026-11-18).**  Doc against code: an
exhaustive inventory of the C64 code's platform sites (≈ 400 in 17
modules), re-verified; the machine: probes in headless xmega65
0870689e on ROMs 920413 and 920421 (Hyppo 1.2, HDOS 1.3), identical
on both.  Recorded:

- The `SYS` entry of a RUN-started PRG: `A X Y Z B` = 0, P = `$20`
  (`E` = 1, `I` = 0), SP `$01EF` with a return into the KERNAL's page-3
  `SYS` return path; map MAPLO `$E000` / MAPHI `$8300`; CPU port
  `$FF`/`$85`; `$D030` = `$64`, so `$C000` is the interface ROM, which
  the KERNAL needs (its default `IBRK` is there); 80 × 25 at `0.0800`,
  40 MHz; `0.1600–0.1EFF` untouched.
- The KERNAL's interrupt entry (identical bytes in both ROMs) pushes A
  X Y Z B, sets `B = 0`, keeps the map, and jumps through
  `$0314/$0316/$0318`; the frame is confirmed under both maps.
- Base page 0: the IRQ writes nothing in it; CSE's call mix writes
  only `$C2–$C5 $DA $E0 $E1 $E8 $E9 $EB $EC`; with `$02–$7F` patterned
  results and screen are identical.  A private base page at `0.1F00`
  (`B = $1F`) survives interrupts, and KERNAL calls work with `B = 0`
  around them.
- `Z`: any value is fine at a call; some calls change it.
- Hypervisor services: `hyppo_getversion` 1.2; `hyppo_rom_writeenable`
  enables writes to banks 2–3, idempotently (`$D640 ← $70` toggles);
  `hyppo_reset` boots back to BASIC 65 with banks 2–3 reloaded, banks
  0, 4, 5 kept, bank 1 cleared.
- With `3.2000–3.CFFF`, `2.4000–2.BFFF` and `2.D000–2.FFFF` zeroed, the
  IRQ, the call mix and ESC 4 / 5 / 8 behave identically.  (A first
  attempt at this did not overwrite anything — the monitor's writes
  respect the ROM protection — and was redone with the protection
  lifted and the zeros verified.)
- 920413 lacks `VERSIONQ`, `RESET_RUN`, `CURSOR`; it has every other
  entry CSE uses.

Doc corrections it forced (written in P0's second delta below): the
c64 column (STOP never called, the real file-call list, `$EA31` and
`$FCE2` the only internals, `TXTTAB` = `$0801`, `$0314` untouched, the
missing cells and homes), 13 classes of site no seam covered, the
user map's values and the `$C000` ROM, no `Z` invariant, the ROM
floor and the Hypervisor services, the layout below.  Decisions: D1
32-bit far pointers + CSE base page (no MAP windows), D2 macros, D3
recording on 920413 through an SD clone (mtools).

**Second delta round (2026-11-18)** — written and approved:
- [x] [platform_layer.md](platform_layer.md) rewritten: the rule
  (platform facts only in `platform.inc` or `.ifdef` blocks), the
  corrected c64 column, new seams (KERNAL calls, Base page, Far
  memory; the banking, terminal and display macros), the m65 column
  as recorded, `P_KEEP` (P bit 5 is `E`), `brk_stub` in the stub.
- [x] [memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode):
  the premise, the two maps as recorded, the bank table (CSE in banks
  2–3 and `0.1F00`), the stub at `0.1FB0`, the install gate,
  interrupts; § Source Code Storage (bank 2); § Target Compatibility
  (920413).
- [x] [build_system.md § The m65 builds](build_system.md#the-m65-builds)
  (ROM floor, `STUB` and `ZEROPAGE` areas, non-segment regions),
  [testing.md § The m65 PRG on M65Emu](testing.md#the-m65-prg-on-m65emu)
  (per-ROM snapshots, the SD-clone ROM, the gate, the two modelled
  Hypervisor services).
- [x] [loader.md](modules/loader.md) (the gate, the six-step install),
  [mem.md](modules/mem.md) (the stub and `brk_stub`, no ZP swap on
  m65, `cse_start`/`cse_end` = `$C000`), [main.md](modules/main.md)
  (`B`, `KCALL VECTOR`, the base-page fill, `hyppo_reset`),
  [gap_buffer.md](modules/gap_buffer.md) (bank 2, far pointers),
  [zp.md](modules/zp.md) (CSE's base page, `FAR_PTR`).
- [x] [userland_contract.md § 3](userland_contract.md#3-memory-regions)
  (the m65 regions and the run premise), [glossary.md](glossary.md),
  [architecture.md](architecture.md) rule 9.
- [x] A CDD Quality pass over the round (2026-11-18): two independent
  readers (correctness and consistency; duplication, layering and
  readability), each finding verified before it was fixed.  Fixed:
  the `KCALL` base-page operand; tail calls (`KJMP`); banking macros
  that compose byte-identically; the far-access clobbers; a false
  `E`-flag hazard (`RTI` does not load `E`, recorded); the 80 × 50
  screen in bank 4 (recorded: `$D062` = 4); one owner per fact —
  routine bodies in the module docs, the stub in mem.md, the install
  in loader.md, the premise and maps in memory_design.md, the
  Hypervisor services, ROM floor and raw-byte list in
  platform_layer.md, user rights and `Q` in userland_contract.md, the
  far-pointer list in zp.md; c64-only statements in memory_design.md
  scoped; the snapshot per ROM; terms defined in the glossary.

**P0 TDD analysis (2026-11-18), approved with its feedback round.**
The tests, written first, in this order (each red until its code
lands, except T1, which is green by construction):

- [x] T1. The C64 hash gate: `c64_prg_sha256.json` recorded before the
  first refactor commit, in a commit of its own.  (Done 2026-11-18:
  `test_platform_audit.py::test_c64_prgs_are_the_recorded_ones`.)
- [x] T2. The literal audit as a ratchet (baseline fixture of today's
  sites; unit tests of the audit on synthetic sources).  (Done
  2026-11-18: 142 sites in 13 files; the address-literal classes are
  in `dev/audit_platform_literals.py`.)
- [x] T3. The raw-byte audit (static); clean mode by PC region (run
  time).  (Done 2026-11-18: `raw_byte_sites` in the audit tool,
  `test_m45_ops.py`, `MPU45GS02(clean=[(first, last), ...])` by the
  PC's flat address through `memory.flat_of`.)
- [x] T4. The m65 build: test_makefile_guards' refusal tests become
  build tests (`make release/debug PLATFORM=m65`, m65-6502); a region
  overflow fails the link.  (Done 2026-11-18: the m65 `disk`, `run`,
  `size` and an unknown platform refused; each of the four areas of
  `src/m65_cse.cfg` bounded as stated, shrunk by one byte it fails the
  link; the m65 PRG in `BUDGET`.)
- [x] T5. M65Emu: one post-boot snapshot per ROM, the `m65_snapshot`
  fixture, the existing m65 suites on each; `capture_m65_state.py
  --rom`.  (Done 2026-11-18: `build/m65_state/920413/`, `920421/`,
  format 3; `test_m65emu.py` runs on both.)
- [x] T6. M65Emu: `hyppo_getversion` and `hyppo_rom_writeenable`;
  any other trap raises.  (Done 2026-11-18: the `Hypervisor` device,
  `HypervisorNotModelled`.)
- [x] T7. The m65 macro bodies in a small m65 bundle on M65Emu
  (`KCALL`/`KJMP` keep `B`; far loads and stores across banks 0, 2, 3,
  4; `FAR_BANK` kept A until the P2 review dropped that).  (Done 2026-11-18: `test_platform_m65.py`,
  clean mode, plus `PLAT_SETBNK`.)
- [x] T8. The loader on each ROM: the install field by field; the gate's
  two refusals; `load_prg()`/`init_cse()` equal to the real loader.
  (Moved to step (5): it runs the real loader in the linked m65 PRG.
  Done 2026-11-18: `test_loader.py` on both snapshots, entered with
  each ROM's premise; `M65Emu.install_prg()` equals the loader over all
  of chip RAM; refusals for Hyppo 1.1 / 0.9 and a non-`JMP` entry, with
  nothing of CSE's written.  `init_cse()` on m65 waits for the display
  bodies, P2.)
- [x] T9. The run premise and the services' answers as a golden file
  (`capture_m65_premise.py` → `m65_premise.json`, per ROM).  (Done
  2026-11-18: memory_design.md's premise holds on both ROMs; they
  differ only in their own `SYS` return path — `$039D` / `$03A1`.)
- [x] T10. Tier X: the PRG boots to `_main` on both ROMs through the SD
  clone (`tests/xmega65.py` gains `prg=`, `rom=`).  (Done 2026-11-18:
  `tests/emulator/test_m65_boot.py`, each ROM taken from its snapshot;
  at `_main` the CSE map, `B = $1F`, SP `$01F1`, the stub, the base
  page and bank 3 equal to `install_prg()`'s, banks 2–3 writable — the
  probe reads protected at READY.)
- [x] T11. The `PLAT_PENDING` count (only goes down).  (Done
  2026-11-18: `pending_counts` in the audit tool; P1 4, P2 13,
  recorded exactly.)

Feedback round, written into the docs (I1–I4): the m65 build is
m65-6502 until P4 (build_system.md § Builds and CPU sets); pending
m65 bodies are `PLAT_PENDING` (platform_layer.md § Pending bodies);
clean mode by PC region (testing.md § M65Emu); the literal audit is a
ratchet until the last seam (platform_layer.md § Gates, testing.md
§ Tier U).

Then the code, in this order — (1) T1; the C64 build moved onto the
seams as a pure refactor, byte-identical, under the full suite, one
commit per seam (Constants; KERNAL calls; Banking; Far memory; Base
page; Terminal; Display; Vectors and frame; Cold start and exit; Disk
bank; Info map; Loader), each lowering T2's baseline to empty;
(2) `src/m45_ops.inc` and T3; (3) the harness: T5, T6, T9; (4) the
m65 bodies of the memory seams, the base page, the stub and the
loader, with T7, T8, T11; (5) the m65-6502 build target (T4) and Tier
X (T10).  Gate: the m65 PRG reaches `_main` in M65Emu and xmega65, on
920413 and 920421, with the map, the base page, the stub and the ROM
protection as memory_design.md states; the C64 PRGs byte-identical;
every test above green.

P0 progress (step (1), one commit per seam, each byte-identical):
- [x] Constants — the literal baseline 142 → 20 (repl.s's info map).
- [x] KERNAL calls — `KCALL` / `KJMP` at the 45 jump-table sites.
- [x] Banking — the `BANK_*` macros; mem.s's two routines by platform.
- [x] Far memory — `FAR_PTR` for zp.md's 14 pointers, `FAR_LDA` /
  `FAR_STA` / `FAR_ORA` at their 170 accesses.  Feedback round:
  `FAR_ORA` added to the contract (disk.s's directory walk, two
  sites).  `FAR_BANK`'s set sites are placed per pointer with the
  milestone whose tests first run its module on m65 (P1, P2, P3:
  platform_layer.md § Far memory); on c64 it is empty.
- [x] Base page — the swap primitives, buffers and seeds under
  `PLATFORM_C64`; the user-ZP view `PLAT_PENDING 1` on m65.  Feedback
  round: an access to a CSE base-page symbol in an *absolute* mode
  reaches page `0.00xx` on m65, not CSE's `0.1F00` — now `BP_ABS(sym)`
  ([platform_layer.md § Base page](platform_layer.md#base-page)) at
  the nine sites (`cur_project_name`'s abs,y accesses and pointers,
  repl.s's `jmp (rp_ptr2)` dispatch), pinned by the base-page check.
  `PLAT_PENDING` is defined; its signature byte follows `BRK`, so the
  raw-byte audit (T3) must not read it as an opcode.
- [x] Terminal — `IO_CX` / `IO_CY` at the 55 cursor-cell sites;
  `IO_STOP_DOWN`, `IO_KBHIT`, `IO_KBD_FLUSH`; cse_io.s's `io_init`,
  `io_getc`, `io_kbhit` and the row tables by platform.
- [x] Display — `PLAT_HYGIENE`; screen.s's `restore_colors`,
  `vic_reset`, `reset_screen`, `kernal_screen_reset` by platform
  (m65: `PLAT_PENDING 2`).  `scroll_up`, `newline` and the cursor stay
  shared: they name no platform fact, only `scr_lo` / `scr_hi` and the
  geometry, which P2 makes run-time.
- [x] Vectors and frame — `setup_interrupts` by platform (m65:
  `PLAT_PENDING 1`); `save_userland_state`'s offsets and `reg_sp`
  derived from `FRAME_DEPTH`; the IRQ early entry (`cse_brk_handler_early`,
  `bank_out_stub`, `_irq_saved_a`) under `PLATFORM_C64`.  The two
  handlers stay shared until P1 states their m65 bodies (the NMI
  handler's A X Y push is the c64 frame's shape).
- [x] Cold start and exit — `PLAT_COLD_START`; `_main`'s steps 1–3,
  `set_charset` and `cse_exit_to_basic` by platform (m65: step 1 and
  `set_charset` `PLAT_PENDING 2`; steps 2–3 absent).
- [x] Disk bank — `PLAT_SETBNK` before disk.s's three `OPEN`s and
  two `LOAD`s (before `LOAD`'s register arguments).
- [x] Info map — the `info_tbl_*` rows and the free holes' bounds in
  one `PLATFORM_C64` data block; `cmd_info`'s body `PLAT_PENDING 2`
  on m65.  The literal audit reached zero: the baseline fixture is
  deleted and the test asserts zero.
- [x] Loader — loader.s's copy loop and main.s's `SYS 2061` stub
  under `PLATFORM_C64`.  Step (1) is complete.
- Stack top (feedback round, 2026-11-18): CSE's base page is
  private, the stack is shared; on m65 the stack top is `$F1`, so a
  fresh start leaves the program at the run premise's SP `$EF` with
  the sentinel where `SYS` puts its return address
  ([platform_layer.md § Stack](platform_layer.md#stack)).
  `STACK_TOP` at the four c64 sites (the loader, `cse_recover`,
  `end_debug_body`, `dbg_init`), byte-identical, pinned by the
  stack-top check.
- [x] Step (2): `src/m45_ops.inc` (eleven macros) and T3.  Feedback
  round: the far access is `PHY` · `PLZ` before the flat op (the
  45GS02 has no `TYZ`, which the contract had named); the DMA trigger
  is an I/O store, not a raw-byte instruction (a DMAgic row in
  § Constants); the audit's *opcode position* rule — a `.byte` after
  an instruction that can fall through — with `brk`'s signature byte
  and data after a transfer exempt; clean-mode regions are flat, so
  user code at CSE's CPU addresses under the user map runs unchecked.
  Known limit: a `.byte` table after a branch pair that is always
  taken (repl.s's `@rep_chars`) is an opcode position to the audit;
  its first byte, `'.'`, is a 6502 opcode.
- [x] Step (3): the harness — T5, T6, T9.  `tests/xmega65.py` gained
  `rom=` (the ROM onto the SD clone's FAT partition, `-romfromsd`)
  and `prg=` (`-prg`, `-prgmode 65`), which T10 also needs.
  Recording finding: the `SYS` return address differs between ROMs
  (within page 3), as do BASIC's frames above its saved map; the
  premise names neither, and CSE replaces both with its sentinel.
- [x] Step (4a): `platform.inc`'s m65 block — the KERNAL entries,
  the Hypervisor services (`HYPPO` macro), `CSE_BP`, `STUB_BASE`, the
  banks, the two maps' operands, `FRAME_DEPTH` 5, `STACK_TOP` `$F1`,
  `PROG_LO`/`PROG_HI` — and the m65 bodies of `KCALL`, `KJMP`, the far
  access macros, `FAR_BANK`, `PLAT_SETBNK`, `PLAT_COLD_START`; T7,
  T11.  Plan change: T8 runs the real loader on the linked PRG, so it
  moves to step (5) with the build target.
- [x] Step (4c): the resident stub (mem.s's `STUB` segment, 73 of
  80 bytes: `stub_brk`, `stub_nmi`, `stub_cold`, `stub_user`,
  `brk_stub` — moved there from debugger.s on m65 — and the three
  targets); the loader's m65 body (the gate through `$FF00,x`, nothing
  written before it passes; the stub copy, the base-page clear, the
  cold target; `hyppo_rom_writeenable`; one F018B list of three
  chained jobs; `jmp stub_cold`); `_main`'s steps 10 (`ZP_FILL_END`)
  and 11 (one DMA fill job); `cse_exit_to_basic` = `hyppo_reset`; the
  m65 BASIC stub `10 SYS 8205`.  The loader and debugger assemble for
  m65; mem.s and main.s wait for step (5)'s m65 answers (`HIMEM`, the
  screen geometry), and T8 tests the install there.
- Step (4b), decided 2026-11-18: `FAR_BANK` at the set sites moves
  to P1 / P2 / P3 by pointer (platform_layer.md § Far memory): a
  site's bank is decided where a test runs the module on m65.  Each
  milestone's step-1 delta below names its pointers.
- The m65 bodies the docs state for P0, written in step (4) with the
  harness that tests them: `KCALL` / `KJMP`, `FAR_SIZE` and the far
  access macros, `FAR_BANK` at every far pointer's set sites,
  `BP_PAGE = CSE_BP`, `STACK_TOP = $F1`, `PLAT_SETBNK`, `PLAT_COLD_START` and `cse_exit_to_basic`
  (`hyppo_reset`), `_main`'s steps 10–11 (the base-page fill bound,
  the program-region DMA fill), the resident stub, the loader.
- [x] Step (5): the m65-6502 build — `make release/debug
  PLATFORM=m65` (`src/m65_cse.cfg`, no layout pass, no exomizer;
  21 054 B, CODE + RODATA to `$6F84`, KDATA + BSS to `$840A`, the base
  page to `$93`); T4, T8, T10.  The first link forced a doc delta
  (2026-11-18), written before the code: **pending values**
  (`PLAT_PENDING_VALUE`, platform_layer.md § Pending bodies) for the
  constants inline code names whose m65 value P2 / P3 states —
  `IO_CX`, `IO_CY`, `SCREEN`, `SCREEN_WIDTH`, `SCREEN_HEIGHT` (P2),
  `ST`, `DISK_LOCAL_PTR` (P3) — the cells in `BP_PENDING` (`$AB–$AF`
  of CSE's base page), counted with the pending bodies (P2 13 → 18,
  P3 0 → 2: the one raise of the count, at the first link); the data
  window's fixed homes (`SYM_TABLE` `$A100`, `SYM_HEAP` `$A700`,
  `SYM_HEAP_END` / `REPL_SCREEN` `$B000`; memory_design.md); `HIMEM`
  = `PROG_HI + 1` for `cse_start` / `cse_end`; `BUF_FLOOR` / `BUF_END`
  `$4000` / `$C000`; the SID registers; `scr_lo` / `scr_hi` as BSS
  run-time tables (filled in P2); `KC_BRANCH` for three disk.s
  branches a 14-byte `KCALL` puts out of range; the linker config
  `src/m65_cse.cfg` (no `.in`: nothing to compute).
- **P0 gate met (2026-11-18):** the m65 PRG reaches `_main` in M65Emu
  and xmega65 on 920413 and 920421, with the map, the base page, the
  stub and the ROM protection as memory_design.md states; the C64
  PRGs byte-identical; T1–T11 green.
- Finding for P2: the screen pointers `_io_scr` (cse_io.s, screen.s's
  `dst_ptr`) and `scr_src` (screen.s's `src_ptr`) reach the screen,
  which is in bank 4 in 80 × 50, but are not in zp.md's far-pointer
  list (`ed_scr` is); P2's delta adds them.

**P1 — running user code: maps, vectors, debugger.**  **Gate met
(2026-11-18):** T1–T11 green on 920413 and 920421 (M65Emu) and in
xmega65; the P1 pending count 0; the C64 PRGs byte-identical; m65-6502
21 485 B.  Code commits 5f81880 (harness), 184d062 (far pointers),
658e56e (bank state, stub, handlers), f0ab625 (`r`, Tier X).

Found by P0's analysis, for this delta: `brk_stub` moves to the
resident stub; the user-ZP view of `m` and `.` reads base page 0
through far pointers (no swap buffers on m65); `reg_z`, `reg_b` join
the register snapshot and `r`.  (The C64 handlers' clearing of P bit
5 — `E` on the 45GS02 — is harmless: `RTI` and `PLP` do not load
`E`, recorded.)

Step-1 delta (written 2026-11-18; approved with the CDD Analysis and the revised D-P1-3, 2026-11-18):
- [x] `FAR_BANK` / `FAR_USER` at the set sites of the user-memory
  pointers (`rp_ptr`, `rp_ptr2`, `_dasm_ptr`, `asm_out`, `asm_pc`):
  a **user address** is the address the program sees under the user
  map, translated by `FAR_USER` (four rows: bank 0, the interface ROM
  `2.C000`, the I/O bank `FFD.3000`, the KERNAL `3.E000`), each
  pointer's sites by role in [zp.md](modules/zp.md);
  [platform_layer.md § Far memory](platform_layer.md#far-memory),
  [mem.md § far_user](modules/mem.md#far_user-m65-only).
- [x] [userland_contract.md](userland_contract.md) for m65 in full:
  the mode model in two-map terms (§ 1), the state tiers with the
  bank state preserved (§ 2 On m65), base page 0 live, the port's
  image and the addresses (§ 3), the 8-byte frame in the stack budget
  (§ 4), the hazards in vector-table terms, reachability and `E`
  (§ 5.5), the must-list (§ 7).  What survives `Q` was stated with
  P0.
- [x] The **bank state** (D-P1-3, revised 2026-11-18): the program's
  `MAP` setting, CPU port and `$D030` captured at every break — the
  map through `hyppo_get_mapping` in the resident stub, into the
  first six bytes of CSE's base page — and installed at every resume;
  the run premise's at a fresh start;
  [platform_layer.md § User transitions](platform_layer.md#user-transitions),
  [mem.md](modules/mem.md) (the stub's shared CSE entry, `stub_user`'s
  two `MAP`s, `um_map`, `um_d030`, the port as a two-byte
  `userland_zp_buf`), [zp.md](modules/zp.md),
  [glossary.md](glossary.md) (*bank state*).
- [x] [platform_layer.md](platform_layer.md): the user-ZP view's m65
  body (§ Base page), `FAR_USER` and `FAR_BANK`'s megabyte (§ Far
  memory), the transition's map and its interrupt window (§ User
  transitions), `reg_z` / `reg_b` from the frame (§ Interrupt frame),
  the workspace's upper bound (§ Constants).
- [x] [main.md](modules/main.md) (`cse_brk_handler`, `cse_nmi_handler`
  on m65; § BRK dispatch, § NMI dispatch), [debugger.md](modules/debugger.md)
  (`dbg_init`, `save_userland_state`, `restore_userland_state` through
  `PLAT_TO_USER`, `brk_stub`, `step_next_pc`, `r` with `z:` and `b:`,
  the caveats), [breakpoints.md](modules/breakpoints.md) (bank 0 once
  per loop), [repl.md](modules/repl.md) (the user-ZP view, the range
  gates, `emit_reg`), [design_cse_as_kernel.md](design_cse_as_kernel.md)
  (§ 3 and § 4 in two-map terms), [assembler_syntax.md](assembler_syntax.md)
  (`.bas` at `BASIC_START`).
- [x] [testing.md § The m65 PRG on M65Emu](testing.md#the-m65-prg-on-m65emu):
  the debugger at the routine level on M65Emu, the two flat facts and
  the NMI line in M65Emu, Tier X's break in user code.

**P1 analysis record (2026-11-18), doc against code — approved 2026-11-18.**
An inventory of every set site of the five pointers (66 sites;
recorded by role in zp.md) and of the pending sites (P1: 4).  Found:

- **`rp_ptr` is mostly CSE's line parser**, not a user pointer: 22
  of its 35 sites walk `line_buf` (bank 3), rooted at one `exec_line`
  site and three restores from `expr_ptr` / `rp_addr`.  On m65 today
  every parse reads bank 0 — the bank the loader left — so the m65
  REPL could not have parsed a line; the four root sites get `FAR_BANK
  rp_ptr, BANK_CSE`.  Its user sites (`brk_skip_user`, `step_next_pc`,
  the breakpoint loops) all run after the line is parsed.  Four sites
  are the screen (P2).
- **A user address needs a translation, not a bank**: `$C000–$FFFF`
  under the user map is the interface ROM, I/O and the KERNAL, which
  a bank-0 flat access misses (a `t` at a break inside a KERNAL call
  would disassemble RAM).  The MEGA65 personality's I/O is at
  `FFD.3000` (recorded with T1).  T1's recording overruled the xemu
  source on the other point: a flat access to `0`/`1` reaches the RAM
  beneath the port, never the port.
- **The workspace gates compare against `buf_base`** (`b`, the step
  gate, the assembler's emit gate), which on m65 is an offset in the
  source bank: the upper bound becomes a platform fact (`buf_base` /
  `HIMEM`).  `bp_range_check`'s `cpx #$08` is `WORKSTART`'s literal.
- **`.bas` hard-codes `$0801`** (asm_src.s `d_bas`), a literal the
  audit's address classes miss: it becomes `BASIC_START`.
- `asm_pc` and `_dasm_ptr` need no set site (gated / not read in the
  product); `asm_out` switches between a user address (`.`) and CSE's
  buffers (`a`); `compose_disk_name` reads `rp_ptr2` set either in
  bank 3 or in CSE's base page (bank 0).
- `hygiene_after_userland` (`PLAT_HYGIENE`, the display) is P2's, so
  on m65 every return from user code ends at a pending body until P2:
  P1's tests stop there (testing.md).

Decisions for approval:
- **D-P1-1** User addresses through the user map (`FAR_USER`, four
  rows), not bank 0 only — +~35 B on m65, nothing on c64.
- **D-P1-2** A run past a row's edge is not translated again (`m
  bffc`'s last columns show `0.C000`; past `$FFFF` reaches `4.0000`):
  documented, not handled.
- **D-P1-3** (revised; operator, 2026-11-18: "the debugger must
  remain transparent … we go the hyppo route") The program's bank
  state is captured at every break and installed at every resume:
  the map through `hyppo_get_mapping` (the CPU has no instruction
  that reads `MAP`, book 14-42; the KERNAL's own convention — whoever
  sets `MAP` keeps its record, I-31, I-79/80 — cannot be asked of a
  debugged program), and with it the CPU port, which the trap needs
  (it is an I/O store) and which makes `m 00`/`m 01` the program's as
  on c64, and `$D030`.  The first draft's "the map is lost at a
  break, it cannot be read" was a claim from memory, not checked
  against the book — withdrawn.  Costs: one Hypervisor trap per
  break; the stub's shared CSE entry (≈ 80 of 80 bytes — if it does
  not fit, `STUB_BASE` moves down); M65Emu models the trap, recorded
  on both ROMs.
- **D-P1-4** `r` shows `z:` and `b:` on m65; bit 5 (`E`) stays `-`.
  The layout depends on the width (operator, 2026-11-18): the one-line
  80-column form now, the 40-column form a P2 item.
- **D-P1-5** The gate below is met at the routine level; the typed
  commands on m65 move to P2's gate.

Gate: every debugger contract that is platform-neutral passes on the
m65 build at the routine level — a fresh start, `RTS`, a user `BRK`,
a breakpoint and its resume, the NMI in user and kernel code, the `t`
/ `o` chain — in M65Emu, and a break in user code in xmega65; the
pending count for P1 at zero; the C64 PRGs byte-identical.  The same
commands typed at the prompt are P2's gate.

**P1 TDD analysis (2026-11-18) — approved 2026-11-18**, with `r`'s
layout split by width (80 columns now, 40 columns a P2 item).  The tests, written
first, in this order; each is red until its code lands.  Automation
judgement: everything P1 states is automatable on M65Emu with the real
ROM and the installed PRG — the BRKs, NMIs and `MAP`s run through the
real KERNAL's interrupt entry, so no frame is faked (unlike the C64's
`_fake_brk_at`); only what is *rendered* waits, because `io_putc`
writes the screen through P2's row tables.  Tier X confirms the two
recorded behaviours M65Emu models and one round trip end to end.

- [x] T1. M65Emu, flat accesses: `capture_m65_mem.py` records a flat
  read and write of `0.0000`/`0.0001` (with block 0 unmapped and
  mapped) and of the windows `FFD.0000–FFD.3FFF` under each `$D02F`
  key; `M65Memory` models both; `test_m65memory.py` replays them.
  (Harness, `tests/m65emu/`.)  Recorded 2026-11-18, feedback round:
  `0`/`1` flat are the RAM beneath the port (the delta had said the
  port; platform_layer.md and testing.md corrected); every window
  shows the one register bank, as `M65Memory` already models it.
- [x] T2. M65Emu, `hyppo_get_mapping`: `capture_m65_premise.py`
  records, on both ROMs, the six bytes for the user map, the CSE map
  and a map with a megabyte offset (the Attic's `$80`; MB `$08`
  crashes xmega65), whether `Y` names a CPU-view or a flat bank-0
  page, the registers and SP after the trap, and the trap from an
  interrupt handler with I set; the `Hypervisor` device answers it,
  every other trap still raises (`test_m65devices.py`).  A recording
  that contradicts the delta (the destination, a clobber) is a
  feedback round before the stub is written.  Recorded 2026-11-18,
  identical on 920413 and 920421: the six bytes are `MAP`'s X A Z Y
  operands and the two megabytes; the page is a CPU-view address
  under the current map (the stub's `$1F00` needs block 0 unmapped,
  which § 5.5 already asks); registers, flags and stack kept — no
  contradiction.
- [x] T3. M65Emu, the NMI: `schedule_nmi` on the m65 snapshot enters
  the KERNAL's NMI entry, which pushes the five-byte frame and jumps
  through `INMI`; and `MAP` holds an NMI until `EOM` (T9's stress case
  relies on it).  Done 2026-11-18 in `tests/integration/test_m65emu.py`
  (it needs the snapshot's ROM, so not `test_m65emu_harness.py`).
  Green at once: `MPU45GS02` already modelled both; the tests pin them
  (a mutant without the `MAP` hold fails).
- [x] T4. `FAR_USER` / `far_user` and `FAR_BANK`'s megabyte, in the m65
  macro bundle on M65Emu in clean mode (`test_platform_m65.py`): each
  row's edges — `$0000`, `$0001` (the RAM beneath the port), `$1F00`, `$BFFF`,
  `$C000`, `$CFFF`, `$D000`, `$D020`, `$DFFF`, `$E000`, `$FFFF` — read
  and written through the pointer; A, X, Y preserved by the routine;
  a pointer set to I/O and then `FAR_BANK`'d reaches bank 3, not
  `FFD.xxxx`; D-P1-2's edge pinned (`$BFFC` + Y = 4 reaches `0.C000`).
  Done 2026-11-18; plan change: `far_user` is mem.s's, which the macro
  bundle cannot link, so its rows run on the installed PRG
  (`test_m65_debugger.py`, against `M65Memory`'s user-map view); the
  megabyte and the edge stay in the bundle.
- [x] T5. The workspace bound on m65, on the installed PRG by `jsr`
  (`tests/integration/test_m65_debugger.py`): `bp_range_check` refuses
  `$1FFF` and `$C000` and takes `$2000` and `$BFFF`;
  `bp_range_check_step` also takes `brk_stub`; `_emit_byte` writes
  `$2000` and `$BFFF` and drops `$C000` with `_oor` set.  The c64 side
  is the existing suite plus the hash gate.
- [x] T6. The line parser in bank 3: `exec_line` on m65 with `r z:12
  b:16 x:05` in `line_buf`, stopped at `emit_reg` (rendering is P2's):
  `reg_x` = 5, `reg_z` = `$12`, `reg_b` = `$16`; a malformed field
  changes nothing (`;?syntax` path reached).  Red today: the parser
  reads bank 0.  Step (2) done 2026-11-18: `r x:05 a:3c` applies both
  fields (it timed out in the KERNAL before the root's `FAR_BANK`);
  `z:` / `b:` and the malformed field join with step (4).  Step (4)
  done: `r z:12 b:16 x:05` sets all three (`reg_z`, `reg_b` follow
  `reg_p` on m65, the labels `z b` extend `reg_labels`); `r z:12 b:1g`
  changes nothing.  `emit_reg`'s 80-column line is P2's (a vocal skip).
- [x] T7. The user-ZP view on m65 (`jsr` on the installed PRG):
  `zp_stage_prep` and `peek_user` take `$00`/`$01` from the captured
  port and every other base-page byte live from base page 0;
  `zp_poke` to `$00`/`$01` lands in the captured port, to `$02` in
  base page 0; a run from `$FFFC` stages the port from the image for
  its wrapped part (the c64 code's wrap) — the live part follows
  D-P1-2.
- [x] T8. The transitions (`test_m65_debugger.py`, each ROM; the m65
  counterpart of `test_kernel_transition.py`, real user code entered
  through `return_to_userland` / `restore_userland_state`, stopped at
  `hygiene_after_userland`, or at `cse_refresh` / `cse_recover`): a.
  fresh start and `RTS` (`DBG_RTS`, `brk_pc` = `cur_addr`, the sentinel
  at `$01F0`/`$01F1`); b. a user `BRK` with every register non-zero,
  `Z` and `B` among them (`B` set to a page of the program's); c. a
  breakpoint hit, the byte restored, then the resume running on to
  the `RTS`; d. an NMI in user code (`DBG_NMI`, the exact PC); e. an
  NMI in kernel code → `cse_refresh`, a live session's captured
  state unchanged; f. a `BRK` in kernel code → `cse_recover`, likewise;
  g. a `t` / `o` chain over a `JSR` and a taken branch, with
  `step_next_pc` and `arm_step_bp` as `cmd_step` uses them, SP bounded
  over 20 steps; h. user pushes above SP survive a break and a resume;
  i. `reg_sp` = the SP before the BRK (the 8-byte frame); j. base page
  0 untouched by the kernel across a break and resume (all 256 bytes,
  a pattern).
- [x] T9. The bank state (`test_m65_debugger.py`, each ROM; Principle
  7's stress shape): parametrised over a program that maps its own
  window (MAPLO offset, MAPHI with the Attic megabyte), one that banks
  the I/O out through the port, one that changes `$D030`, and all
  three; each breaks by breakpoint, step, user `BRK` and NMI, and after
  the resume reads back exactly what it set (`memory.flat_of()` over
  the CPU view, the port, `$D030`).  A `j` after such a run starts with
  the run premise's state.  The stress case: an NMI scheduled at each
  instruction from `PLAT_TO_USER`'s first store to `stub_user`'s `RTI`,
  each run resumed with `c` — the program completes as without it.
  Step (3) done 2026-11-18 (T7–T9 green on both ROMs).  The stress
  case found a real bug: an NMI in `PLAT_TO_USER` before the stub's
  `MAP` recorded the CSE map and CSE's registers as the program's —
  fixed by opening the m65 tail with a `MAP` hold and setting
  `in_userland` inside it.  Feedback round, into the docs: a megabyte
  outlasts a one-`MAP` switch, so the stub's switch to the CSE map is
  the two-`MAP` form; the stub's targets live in CSE's base page (the
  stub's 80 bytes are full); `$D030` is captured in
  `save_userland_state`; `setup_interrupts` holds interrupts itself;
  `BP_ABS` needs `a:` where the instruction has a zero-page form.
  P1's pending count is 0.
- [x] T10. Tier X (`tests/emulator/test_m65_break.py`, each ROM): a
  user `BRK` stopped at `hygiene_after_userland` with the snapshot, the
  CSE map and `B = CSE_BP` as M65Emu has them; a program that maps a
  window and banks the I/O out, breaks, is resumed through
  `restore_userland_state` from the monitor, and stores what it reads
  back where the test finds it.  Done 2026-11-18 on 920413 and 920421:
  the snapshot and the real Hypervisor's capture equal M65Emu's; the
  banked program reads back its window, `$34` and `$00` after `c`.
- [x] T11. The gates: the P1 pending count zero
  (`test_platform_audit.py`'s recorded counts: P1 4 → 0); the C64
  release PRGs byte-identical after every commit (T1 of P0); the m65
  areas bounded (P0's T4 — the stub's 80 bytes among them).

Not automated now, by design (vocal skips in `test_m65_debugger.py`,
pattern A, pointing at P2): the break panel, `emit_reg`'s line with
`z:` and `b:`, `m`'s and `.`'s rendering, and every command typed at
the prompt — P2's gate (D-P1-5).  `.bas` at `$2001` runs only through
`a`, whose source side is P2's: the c64 bytes are pinned by the hash
gate now, the m65 address by P2's `a` test.

Then the code, in this order — (1) the harness: T1, T2, T3; (2) the
far pointers: `far_user` and `FAR_USER`, `FAR_BANK`'s megabyte, the
set sites by zp.md's roles, the workspace bound, `.bas` — T4, T5, T6;
(3) the bank state, the stub and the handlers: `um_map`, `um_d030`,
the port image (`ZP_SAVE_LEN` 2), the stub's shared entry and
`stub_user`, `PLAT_TO_USER`, `setup_interrupts` through `VECTOR`, the
handlers' m65 bodies, `save_userland_state`'s `Z` and `B`, the seeds
— T7, T8, T9; (4) `r`'s `z:` / `b:` fields (T6's last part), Tier X
(T10), the pending count (T11).  One commit per step at least, the
hash gate green in each; optimization.md applies to every m65 body
(the stub first: it must fit its 80 bytes).

**P2 — the KERNAL API layer: screen and keyboard.**  **Gate met (2026-11-19)** — below, after the TDD plan.

Step-1 delta (written 2026-11-19; approved with the CDD Analysis,
2026-11-19; it builds on A1):
- [x] `FAR_BANK` at the set sites of the screen, string and source
  pointers (`ed_scr`, `_io_tmp`, `gap_lo`, `gap_hi`, `buf_base`,
  `ed_top_ptr`, `read_ptr`, `ed_tmp`, and `_io_scr` / `scr_src`, far
  from P2), with the screen's bank by mode (`FAR_BANK_SCREEN`) and the
  source region's `BANK_SRC` ([platform_layer.md § Far memory](platform_layer.md#far-memory),
  [zp.md](modules/zp.md)).
- [x] [platform_layer.md](platform_layer.md) § Terminal and
  § Display: the m65 bodies (A1's means), `screen_mode_set` and
  `io_geometry`, *The geometry* (run-time cells, operand defines), the
  MEGA65's keys; § Screen save (DMA, 80 × 50, refused mode change);
  § Info map (the m65 rows, `b.aaaa-bbbb`); § User transitions (the
  program's `SYSFLAGS`); § Constants (geometry, VIC-IV).
- [x] [cse_io.md](modules/cse_io.md), [screen.md](modules/screen.md):
  the m65 entries (`io_geometry`, the lookahead, far screen pointers,
  DMA fill / copy).
- [x] [editor.md](modules/editor.md) (§ On m65: the layout follows the
  mode, `LINE_MAX` 79), [repl.md](modules/repl.md) (`m` rows by width,
  `line_buf`, `emit_reg`, the panel's height), [debugger.md § `r`](modules/debugger.md#r)
  (40 columns: two rows), [gap_buffer.md](modules/gap_buffer.md) and
  [asm_src.md](modules/asm_src.md) (`LINE_MAX`).  log.md needs nothing:
  its rows are at most 28 columns and pad to the width.
- [x] [README.md § On the MEGA65](../README.md#on-the-mega65): the
  modes, the wider rows, the editor, the keys, the program's state.
- [x] [userland_contract.md § 2 On m65](userland_contract.md#on-m65):
  the clobbered screen-side list, `SYSFLAGS` preserved.
- [x] [testing.md § The m65 PRG on M65Emu](testing.md#the-m65-prg-on-m65emu):
  the REPL on m65, M65Emu against the editor recording, Tier X's REPL
  and `Q`.

**P2 analysis record (2026-11-19), doc against code — approved 2026-11-19.**
An inventory of every geometry and display site (all of `src/`): about
35 width sites (40, 39, 38), 11 height sites, 20 editor-row sites (22
rows, row 22, rows 23–24), the 1000-, 920-, 880- and 80-byte copies, 14
walks of `scr_lo` / `scr_hi`, 3 routines on VIC registers, 1 on colour
RAM; 9 pending bodies and 4 pending macros of P2.  Found:

- **`line_buf` overflows on m65** (42 bytes; `read_line` writes the
  width + 1): 82 bytes.
- **The source-line cap disagrees on m65**: the editor caps at the
  width − 1, the assembler at 39 (`ed_read_line`, `_line_buf`,
  `warn_long_lines`) — `LINE_MAX`, one platform constant.
- **`_io_scr` and `scr_src` are 16-bit** and cannot reach the 80 × 50
  screen in bank 4 (P0's finding); and about 20 far screen-pointer
  sites (the editor, `read_line`, main's INS / DEL, log's row tail,
  disk's `@putc_inv`) set no bank: `FAR_BANK_SCREEN`.
- **`vic_reset` clears `$D01A`** — on the MEGA65 that is the KERNAL's
  raster IRQ: the KERNAL's value instead.
- `cmd_step` moves up 3 rows for the break panel; the editor's status
  bar has its columns as literals; `emit_reg` has no m65 form;
  `BANK_SCREEN50` is used nowhere; the documented
  `screen_mode_set` / `screen_geometry` did not exist.
- Two edge bugs on both platforms, filed, not P2's: `io_puthex2`
  writes its second digit past the last column into the next row;
  disk.s's `@putc_inv` inverts the wrong cell when the clamp held the
  cursor at the last column.

Decisions (operator, 2026-11-18):
- **D-P2-1** An `m` row follows the width: 16 bytes in 80 columns, 8
  in 40; an edit takes up to 16 on m65.
- **D-P2-2** The display reset rewrites the VIC-IV registers to the
  KERNAL's set for the current mode (recorded per ROM) and keeps the
  screen's content.
- **D-P2-3** Function-key macros off while CSE reads keys; the
  program's `SYSFLAGS` is captured and restored with its bank state;
  a fresh start gets `$00`.  (Settles D-A1-5.)
- **D-P2-4** The editor uses the whole screen of the mode.
- **D-P2-5** `LINE_MAX` = 79 on m65 in every mode (c64 39); in 40
  columns a longer line shows `>` and cannot grow.

Decisions (approved 2026-11-19):
- **D-P2-6** `r` in 40 columns on m65: two rows, the c64 line and `r
  z:XX b:XX` — each re-executes on its own.
- **D-P2-7** The MEGA65's extra keys in P2: TAB is the editor's tab;
  HELP, F9–F14 and the ALT / MEGA combinations do nothing yet.
- **D-P2-8** The geometry as base-page cells set by `io_geometry`,
  named at inline sites through operand defines (`cpy WIDTH`:
  `#40` on c64, `scr_width` on m65), so the C64 builds stay
  byte-identical.
- **D-P2-9** A mode switch is `ESC 4` / `5` / `8` at the prompt (CSE
  obeys the sequence itself), clears the screen, and is refused in
  the editor.
- **D-P2-10** Clears, colour fills, scrolls and the screen save are
  one DMA job each on m65 (width × height, and 80 × 50 is 4000 bytes).

**P2 TDD analysis (2026-11-19) — approved 2026-11-19.**  The tests, written
first, in this order; each is red until its code lands.  Automation
judgement: all of P2 is automatable on M65Emu (the real ROM; the
typing queue takes `inject_keys`; the screen is read where the VIC-IV
shows it), provided M65Emu answers the editor calls as xmega65 does —
T1 checks that first.  Tier X confirms the prompt, the typed commands
and `Q`; what a human sees (colours, flicker) stays manual.

- [x] T1. M65Emu against the editor: `capture_m65_editor.py` also
  records the VIC-IV register set (`$D011`, `$D016`, `$D018`, `$D01A`,
  `$D031`, `$D054`, `$D058–$D05E`, `$D060–$D065`, `$D07B`) and the
  colour-RAM offset the KERNAL leaves after `ESC 4` / `5` / `8`;
  `tests/integration/test_m65_editor.py` replays every probe of
  `m65_editor.json` on M65Emu with each snapshot's ROM — the jump table,
  `SCRORG` / `PLOT` per mode and window, logical lines, the interrupted
  `BSOUT` (a sample), quote and insert mode, the keyboard calls, the
  base-page cells, the register sets.  A mismatch is an M65Emu fix
  (or a feedback round) before any P2 code.  Done 2026-11-19: the
  register sets are identical on both ROMs (the modes differ in
  `$D016`, `$D031` `$E0 / $E8 / $60`, `$D058` / `$D05E` 80 / 40, `$D062`,
  `$D07B` 24 / 49; the colour RAM at offset 0 in every mode, `$D01A`
  `$E1`).  Two mismatches, both fixed: M65Emu lacked the VIC-IV's hot
  registers (a write to `$D011` / `$D016` / `$D018` / `$D031` re-derives
  the text layout; the KERNAL's mode switches rely on it — the
  `VICHotRegisters` device, after xemu's vic4.c); the base-page probe
  measured from an arbitrary state (now from a fixed one).
- [x] T2. The MEGA65's keys: `GETIN`'s PETSCII for TAB, HELP, F9–F14
  and the ALT / MEGA / CTRL combinations, from the KERNAL's key table
  on M65Emu (typing events injected as the hardware queue presents
  them, xemu's mapping), recorded as a fixture the REPL and editor
  tests share; `$D60A`'s modifier bits per the book (F-3).  Done:
  the hardware, not the KERNAL, translates keys (`$D619`); the codes
  from xemu's tables in `tests/fixtures/m65_keys.json`; `GETIN` passes
  each through with the macros off and expands F1 with them on.
  Found: F9–F14 send CTRL + P / U / V / W / Y / Z's codes.
- [x] T3. The geometry (`test_m65_terminal.py`, new, each ROM, the installed
  PRG): `io_geometry` in 80 × 25, 40 × 25 and 80 × 50 sets `scr_width`,
  `scr_height`, `scr_last_col`, `scr_last_row`, `scr_ed_rows`,
  `scr_size`, `scr_bank` and the row tables as `SCRORG` and `$D062`
  give them; under a program's window it first leaves it.
- [x] T4. The terminal on m65: `io_putc`, `io_puts`, `io_puthex2`,
  `io_clear_eol` land in the mode's screen (bank 4 in 80 × 50) and
  clamp at its last column; `io_sync` puts the KERNAL's cursor where
  CSE's is (a `BSOUT` after it lands there); `io_kbhit` / `io_getc` /
  `IO_KBD_FLUSH` over a key typed into the queue and one `ADDKEY`ed;
  `IO_STOP_DOWN` with STOP held and released (`press_stop`).  Step (2)
  done 2026-11-19: T3 and T4 in `tests/integration/test_m65_terminal.py`
  (owner cse_io.md; the plan's `test_m65_repl.py` is for T8),
  `IO_STOP_DOWN` in the m65 macro bundle with a stand-in `ScanStopKey`.
  Feedback round: the base page could not take all the geometry —
  `scr_width` / `scr_last_col` stay there (the clamp's), the rest is
  cse_io's BSS, and `BP_PENDING` moved to `$AD`; `TZA` joined the
  raw-byte macros (`SCRORG`'s address high byte comes in Z);
  `ScanStopKey` joined the loader's gate.  P2's pending count 18 → 11.
- [x] T5. The display on m65: `vic_reset` after a program changed the
  VIC-IV registers (bitmap, 40 columns, raster IRQ off) writes the
  mode's recorded set back and keeps the screen's content;
  `restore_colors` fills the mode's colour RAM (width × height) and
  sets border and background; `reset_screen` clears width × height in
  the mode's bank; `scroll_up` in each mode; `kernal_screen_reset` turns
  a program's quote mode and window off; `screen_mode_set` round trips
  4 → 5 → 8; `PLAT_HYGIENE` gates the SID voices and sets CSE's
  `SYSFLAGS` bits.  Step (3) done 2026-11-19 in
  `tests/integration/test_m65_display.py` (owner screen.md).  Found:
  `$D018`'s hot write resets the character pointer, so `vic_reset`
  ends with `$0E` through `BSOUT` (the KERNAL's lowercase switch moves
  `$D069` only); M65Emu's hot-register model gained the character
  pointer; a char literal `'O'` under `-t c64` is `$CF` — ESC O is
  written `$4F`.
- [x] T6. The program's `SYSFLAGS` (`test_m65_debugger.py`, T9's
  shape): a program that sets bits 4–7, breaks and resumes reads them
  back; CSE reads raw function keys meanwhile; a fresh start gets
  `$00`.  Done: the KERNAL keeps `SYSFLAGS` in base page 0, so a fresh
  start's `$00` writes that cell — the program's state, not a clobber
  (the base-page test takes its snapshot with it set).  `um_sysflags`
  is BSS (the base page is full).
- [x] T7. Cold start on m65: `_main` to `main_loop_top` with Principle
  16's watchers (no `cse_brk_handler`, no `cse_recover`); the splash
  and the prompt at 80 × 25 as screen rows; the pending count's P2
  sites gone from the path.
- [x] T8. The REPL typed: `?`, `m` (16 bytes a row in 80 columns, 8 in
  40; a 16-byte edit in either), `.`, `d`, `r` (one row in 80, two in
  40, each re-executing), `i` (the m65 rows, `b.aaaa-bbbb`), a command
  line 80 columns wide (`line_buf`), `ESC 4` / `5` / `8` at the prompt,
  the break panel and `t`'s re-print in 40 and 80 columns.
- [x] T9. The debugger typed (moved from P1, D-P1-5): `j`, `g`, `c`,
  `t`, `o`, `b`, `r`, `d` at the prompt and the
  [dbg_reason × command matrix](modules/debugger.md#dbg_reason--command-matrix)
  through the REPL on the m65 PRG — the C64 suites' rows, parametrised
  over the platform where their assertions are platform-neutral.
  Step (4) done 2026-11-19: T7–T9 in `tests/integration/test_m65_repl.py`
  (owner repl.md; `M65Session`, the C64 Session on M65Emu — the C64
  rows re-stated there rather than parametrised, since the C64 suites
  drive `$C6` / `$D3` directly).  The code: `cmd_info`'s m65 rows (the
  `info_m65` table, `info_m65_rows`, `b.aaaa-bbbb` by `info_bank`, a
  whole bank's `65536b`); the splash and prompt rows, main_loop's keys,
  `read_line` and log's row tail on the run-time geometry with the
  screen's bank; `line_buf` `2 + SCREEN_WIDTH_MAX`; `m` rows by width
  (`mem_row`), edits up to `MEM_ROW_MAX`; `emit_reg`'s m65 rows and
  `cmd_step`'s panel height; ESC 4 / 5 / 8 at the prompt
  (`esc_armed`); `cur_addr` = `workstart`; the C64-only info strings
  and `info_emit_rows` gated off m65.  Found: **`io_kbhit` left Z from
  X** on m65 (`ldx #0` last), so main_loop's `beq @wait` never saw a
  key — fixed, Z from A as `IO_KBHIT`'s `lda $C6`; **`io_puts` set no
  bank** for its far `_io_tmp` — now `BANK_CSE`.  P2's pending count
  4 → 3 (the three values, T12).
- [x] T10. The editor on m65, each mode: its rows (`ED_ROWS`), the
  status bar (fields anchored right), typing up to `LINE_MAX` 79 and
  the cap at the last column in 40 × 25 with `>`, the screen saved and
  restored, `ESC 4` / `5` / `8` refused; the assembler reads 79
  columns (`;!N: truncated` past them), `warn_long_lines` at 79.
  Step (5) done 2026-11-19 in `tests/integration/test_m65_source_editor.py`
  (owner editor.md, 25 tests × 2 ROMs).  The code: the editor's rows
  and caps through the operand defines (`ED_ROWS`, `ED_STATUS_ROW`,
  the new `ED_LAST` / `scr_ed_last`, `WIDTH`, `LAST_COL`); the status
  bar's right fields by `_ed_status_right`, `free:` the program
  region; `screen_save` / `screen_restore` (screen.s, one DMA copy
  each); the context rows from the save; `LINE_MAX` (platform.inc)
  in `ed_read_line`, `_line_buf`, `warn_long_lines`.  Found: **the
  source text had no bank** — the gap buffer's far pointers were never
  given `BANK_SRC`, so the text landed in bank 0's program region
  (`$4000–$BFFF`) — now set by `gb_init` for the four that live in the
  text and per routine for the shared scratch pointers (`gb_home`'s
  `ed_tmp` was the last found, by the cursor-up test); **`workend`
  followed `buf_base`** on m65 — now `PROG_HI`.  Feedback round (CDD
  amendment, editor.md): a cursor left past the last column or below
  the last row by a mode change between editor visits is brought back
  on entry.  D-P2-10 read as the REPL's scroll: the editor's row
  scrolls stay the row loop on far pointers (editor.md, *The m65
  bodies*).
- [x] T11. Tier X (`tests/emulator/test_m65_boot.py`): the PRG to the
  prompt; xmega65's screen rows equal M65Emu's after the same commands
  (typed through `ADDKEY` from a driver); `Q` ends in BASIC 65 at
  READY with banks 2–3 reloaded.  Done 2026-11-19: one key per driver
  call (registers, P and `B` kept; back to where `main_loop` stopped),
  the run on to `main_loop`; 11 screens compared as text — the splash,
  `?`, `i`, `m`, `r`, `.`, `@`, `d`, the editor and back, 80 × 50 and
  back — equal on both ROMs; `Q` (shifted, `$D1`) and `y` reach READY.
  `wait_for_basic` cannot tell BASIC 65's map from CSE's (CSE's map is
  BASIC's), so the test waits for READY on the screen.
- [x] T12. The gates: the P2 pending count (18) to 0 — the bodies and
  the five values `IO_CX`, `IO_CY`, `SCREEN`, `SCREEN_WIDTH`,
  `SCREEN_HEIGHT`; the C64 PRGs byte-identical after every commit; the
  m65 budget raised in commits of their own.  Done: the three screen
  values are no placeholders but c64 constants only — no m65 code
  names them (screen.s's `SCR_W` / `SCR_H` gated to c64); the count
  is 0; m65-6502 22 753 B (unchanged by the step).

Not automated: what the screen looks like (colours, the 80 × 50
font, flicker) — manual in xmega65 and on hardware, a checklist row.

Then the code, in this order — (1) the harness: T1, T2; (2) the
geometry and the terminal: the operand defines (byte-identical on
c64), `io_geometry`, the far screen pointers and `FAR_BANK_SCREEN`,
cse_io's m65 bodies, the lookahead, `ScanStopKey` — T3, T4; (3) the
display: screen.s's m65 bodies, the DMA jobs, the VIC-IV tables, the
mode switch, `PLAT_HYGIENE`, `SYSFLAGS` in the bank state — T5, T6;
(4) the cold start and the REPL: `_main`'s steps, `set_charset`, the
splash, `line_buf`, `m`, `r`, `i`, the panel — T7, T8, T9; (5) the
editor and `LINE_MAX` — T10; (6) Tier X and the gates — T11, T12.  One
commit per step at least, the hash gate green in each; optimization.md
applies to every m65 body.

Gate: `?`, `m`, `.`, the editor and `Q` at 80 × 25 in M65Emu and
xmega65; 40 × 25 and 80 × 50 render; the debugger commands typed at
the prompt (`j`, `g`, `c`, `t`, `o`, `b`, `r`, `d`) and the lifecycle
matrix through the REPL (moved from P1, D-P1-5).

- **P2 gate met (2026-11-19):** T1–T12 green on 920413 and 920421 in
  M65Emu (`test_m65_editor.py`, `test_m65_terminal.py`,
  `test_m65_display.py`, `test_m65_repl.py`, `test_m65_source_editor.py`,
  the T6 rows of `test_m65_debugger.py`) and in xmega65
  (`test_m65_boot.py`, `test_m65_break.py`); the P2 pending count 0;
  the C64 PRGs byte-identical; m65-6502 22 753 B.  Code commits
  a09f7ff, 254841c, d71093c, e7fd330, 9caf1c6 and step (6).  Found on
  the way, fixed: `io_kbhit`'s Z, `io_puts`' bank, the source text's
  bank, `workend`; filed, not P2's: the two edge bugs of the analysis
  record (`io_puthex2`, disk.s's `@putc_inv`).  Left manual: what the
  screen looks like (colours, the 80 × 50 font, flicker).
- **Review of the P2 commits (2026-11-19):** one platform divergence
  fixed — the m65 `kernal_screen_reset` did not drop the keys typed
  while a program ran (the c64 body's `$C6` = 0 does), so they reached
  the REPL: now `io_kbd_flush` ends it.  Simplifications: `FAR_BANK` /
  `FAR_BANK_SCREEN` no longer save A (no site needs it), `scr_dma`
  writes only the job fields that vary, `screen_mode_set` ends in
  `reset_screen`, `gb_init` shares one `lda #0`, the m65 `io_kbhit`
  drops a meaningless `ldx #0`; the test helpers `cell` and the text
  modes moved into `M65Emu` / `harness.TEXT_MODES`; stale c64 numbers
  in shared comments (rows, columns, byte counts) rewritten in the
  operand defines' terms.  m65-6502 22 753 → 22 665 B.  Second pass
  (the review's open items): `i` and the splash list bank 5 in 80 × 50
  too — measured on M65Emu on both ROMs, the KERNAL's 80 × 50 (mode
  switches, scrolling, the editor's save and restore) writes nothing in
  banks 4–5 but its screen, 4.0800–4.179F, so the delta's "banks 4–5
  in 40 × 25 and 80 × 25" hid a free bank (amended: platform_layer.md
  § Info map, memory_design.md, repl.md); `warn_long_lines`' comments in
  `LINE_MAX` terms.  Not changed: a fresh start's `SYSFLAGS` is the
  premise's `$00` whole — D-P2-3, the operator's ruling, and the
  recorded premise.

**P3 — the disk and the distribution formats (PRG and D81).**  **Gate
met (2026-11-19)** — below, after the TDD plan.  Operator, 2026-11-19: "Postpone CRT to a later release, first release
will be PRG/D81 only" — the cartridge leaves P3 (§ Later release:
the m65 cartridge, below).

Step-1 delta (written 2026-11-19; approved 2026-11-19 with the
analysis):
- [x] [disk.md § On m65](modules/disk.md#on-m65): the units (8/9
  CBDOS's, the others IEC — the KERNAL routes), `ST` through `READSS`,
  the probe without clearing `ST`, `ptr` = `disk_local_ptr`, the
  directory into `DIR_BUF` `2.D000` (`PLAT_SETBNK DIR_BANK`, `FAR_BANK
  disk_ptr`), the pointer banks (`FAR_USER _io_tmp` in `disk_save_prg`,
  `FAR_BANK_SCREEN _io_tmp` in `@putc_inv`), the load targets.
- [x] [platform_layer.md](platform_layer.md): § Constants
  (`DISK_LOCAL_PTR`, the directory buffer), § Disk bank (`PLAT_SETBNK
  [bank]`, the units), § Pending bodies (no pending value left;
  `BP_PENDING` and `PLAT_PENDING_VALUE` go).
- [x] [zp.md](modules/zp.md) (`disk_local_ptr`; the segment bound back
  to `$B0`), [memory_design.md](memory_design.md) (`2.D000–2.FFFF` the
  directory buffer).
- [x] [build_system.md](build_system.md): every target works on m65;
  the D81 from `release` and `disk` (`c1541`, `cse <version>,01`, the
  PRG as `cse-m65`); `make run` adds `-8 cse-m65.d81`; `make size` on
  m65; the guard test's row.
- [x] [testing.md § The m65 PRG on M65Emu](testing.md#the-m65-prg-on-m65emu),
  *The disk on m65*: the virtual drive moved to `EmuBase`, M65Emu's
  traps at the jump table (recorded), `ST` at `0.0090` (recorded),
  `$D012` advancing, `test_m65_disk.py` on unit 10; Tier X on the
  D81, unit 8.
- [x] [README.md § On the MEGA65](../README.md#on-the-mega65): starting
  from the D81, `make run`'s keys, `Q`, `$` / `l` / `s` on any unit.
- [x] The cartridge out of the first release: build_system.md (the
  targets, the tree, the CRT paragraph rewritten from A3's record),
  platform_layer.md § Loader, loader.md, memory_design.md,
  testing.md, README.md.
- [x] D-P3-8's feedback round (step (5)): the KERNAL's map record in
  the bank state — [platform_layer.md § User transitions](platform_layer.md#user-transitions),
  [debugger.md](modules/debugger.md) (`bank_state_swap`, `um_kmap`),
  [main.md](modules/main.md), [glossary.md](glossary.md) (*bank
  state*), [userland_contract.md](userland_contract.md), testing.md
  (the run premise's record).

**P3 analysis record (2026-11-19), doc against code — approved 2026-11-19**
(D-P3-1 as amended by the operator: no cartridge in the first release).
Recorded on M65Emu with both ROMs (920413, 920421):

- **The disk path.**  `$` on unit 8 hangs in M65Emu: the KERNAL hands
  unit 8 to CBDOS, which polls the floppy controller in the interface
  ROM (`$C9E7–$CB06`), and M65Emu models none.  On unit 10 (IEC) the
  KERNAL reaches `LISTEN` through the jump table (`OPEN` → `$F426` →
  `jsr $FFB1` → `JMP ($0336)` → `$CC69`, the interface ROM); all eight
  serial entries are `JMP (vector)` into `$0334–$0343` on both ROMs.
  So C64Emu's virtual drive (traps at the jump table) serves IEC units
  on M65Emu unchanged.  Without a drive, the KERNAL's IEC delay loop
  polls `$D012` (`$CB9A`) — static in M65Emu, so it hangs: M65Emu needs
  a raster line that advances.
- **`ST`.**  `READST` (`$FFB7`) is `JMP` to `lda $90` · `rts` on both
  ROMs: the MEGA65 KERNAL keeps `ST` in base page 0's `$90`.  disk.s
  writes `ST` (the probe clears it) and reads it directly — no KERNAL
  cell on m65: `READSS` only (D-A1-1's rule).
- **`DISK_LOCAL_PTR`.**  `ptr` reads only filenames in CSE's view —
  `str_setup`'s `(ptr),y`, then `SETNAM` with `ptr`'s value — so a
  plain 2-byte base-page cell does: not a far pointer, as the delta
  had it.  CSE's base page uses `$00–$AB`; with it, `$00–$AD`.
- **The directory.**  `list_directory` loads `$` to `BASIC_START`
  (`0.2001` on m65, the user's program region) and walks it through
  `disk_ptr`, whose bank nothing sets.  A full D81 directory is under
  10 K; `2.D000–2.FFFF` is CSE's unused 12 K reserve.
- **The pointer banks.**  `disk_save_prg` reads the program through
  `_io_tmp`, left at `BANK_CSE` by `io_puts` — so the m65 `s` would
  save CSE's bank 3, not the user's program; `@putc_inv` writes the
  screen through `_io_tmp` without the screen's bank (bank 4 in
  80 × 50).  And the filed edge bug: `@putc_inv` inverts the wrong cell
  when the clamp held the cursor at the last column (both platforms).
- **The build.**  `make disk` / `size` with `PLATFORM=m65` are refused;
  `size_report.py` prints a C64 memory map whatever the build.
- **The cartridge** (P3's third format): A3's record (§ Analysis
  tasks) — the ROM copies 8 K and jumps to `$8000`; a hardware
  cartridge shows 16 K unbanked; `Q` from a cartridge start would
  restart CSE (the reset path finds the cartridge again).  Postponed
  to a later release (the operator's ruling above).

Decisions (approved 2026-11-19):
- **D-P3-1** P3 is the disk on m65 and the D81 (this delta); the
  cartridge is a later release's (operator: the first release is PRG
  and D81 only).
- **D-P3-2** M65Emu's disk tests use an IEC unit (10) and the shared
  virtual drive; CBDOS (units 8/9) is Tier X with `cse-m65.d81`.
  (Alternative: model the floppy controller and a D81 in M65Emu — the
  CBDOS path in Tier I, at the cost of a device model.)
- **D-P3-3** The directory buffer is `2.D000–2.FFFF`: `$` leaves the
  user's memory alone on m65.  (Alternative: the C64's way, the
  program region from `BASIC_START`.)
- **D-P3-4** `DISK_LOCAL_PTR` = `disk_local_ptr`, a plain 2-byte cell.
- **D-P3-5** `make run PLATFORM=m65` = `-prg` as now plus `-8
  cse-m65.d81` (CSE starts at once; the D81 is there for `$` / `l` /
  `s`).  (Alternative: `-8` with `-autoload`, the D81's own start.)
- **D-P3-6** Fix the filed `@putc_inv` bug in P3 on both platforms,
  since the routine changes anyway: the C64 PRGs change by that fix
  alone (their hashes re-recorded in its own commit).  (Alternative:
  leave it filed.)  **Amended in step (2), on a new fact:** the bug
  is unreachable — the header it inverts is at most 32 columns
  (`fl_buf` keeps 30 characters) — so it is closed, not fixed, and the
  C64 PRGs stay byte-identical (§ Bugs).
- **D-P3-7** `make size PLATFORM=m65`: `size_report.py` takes the
  platform and prints the segment and module parts only.
- **D-P3-8** (feedback round, step (5); operator 2026-11-19: "Swap
  the map record").  Tier X on the D81 found: a KERNAL disk call
  through CBDOS (unit 8) returns under the KERNAL's map record
  `0.011C–011F` — the interface ROM's IEC / DOS wrapper and the
  KERNAL's far-call return end in `LDQ $011C` · `MAP` (both ROMs) — and
  the record holds the `SYS` map, so a PRG `s` / `l` came back with
  CSE's code mapped away (a BRK in bank 0's zeros).  M65Emu's IEC unit
  never takes that path.  The fix: the record is part of the bank
  state — the CSE map while CSE runs (`bank_state_swap` at every break
  and, through `dbg_init`, at the cold start), the program's own at
  every resume (`um_kmap`, written inside `PLAT_TO_USER`'s hold — the
  P3 code review), the user map at a fresh start.  The one KERNAL cell CSE writes on m65;
  the alternative, a bank-0 trampoline restoring CSE's map after each
  call, needed bank-0 space CSE does not have.

**P3 TDD analysis (2026-11-19) — approved 2026-11-19.**  The tests, written
first, in this order; each was written red, before its code.
Automation judgement: everything but real drive timing is automatable — the
KERNAL's IEC path on M65Emu (a virtual drive behind the jump table),
CBDOS on the D81 in xmega65 (Tier X).

- [x] T1. The virtual drive, shared (`tests/emu_base.py`): C64Emu's
  `attach_drive`, `Drive1541`, `IECBus` move to `EmuBase`, behaviour-
  neutral — every C64 disk test (`test_disk.py`, `test_repl_disk.py`,
  `test_editor.py`'s) green unchanged.  The bus accepts a `JMP` or a
  `JMP (vector)` at each of the eight entries and returns through the
  platform's stack (M65Emu: the 45GS02's, E = 1); `ST` is the KERNAL's
  `$90` on both.  New, on M65Emu (each ROM): `attach_drive(10)` serves
  `OPEN` · `CHKIN` · `CHRIN` of a file through the real KERNAL;
  `READSS` reports EOI at its end; with no drive on unit 10 `OPEN`
  fails with device not present instead of hanging — M65Emu's `$D012`
  advances (a raster counter beside the latch), which the KERNAL's IEC
  delays poll.
- [x] T2. disk.s on m65 (`tests/integration/test_m65_disk.py`, new,
  owner disk.md, each ROM, unit 10): `test_disk.py`'s contract —
  without a drive: the error codes, no file left open, an empty
  status, no hang; with one: a PRG loaded to its header address and to
  a given one in bank 0, saved from bank 0 (the bytes of the user's
  program, not CSE's bank 3), replaced with `@`; SEQ save and load with
  their counts; the status line; `list_directory`'s header, entries,
  blocks free and the STOP break — into `DIR_BUF` (`2.D000`) with the
  program region `0.2000–0.BFFF` untouched, its reversed header in the
  screen's bank in 80 × 25, 40 × 25 and 80 × 50.
- [x] T3. The REPL over it (`test_m65_disk.py`, typed through
  `M65Session`): `$10` (and `cur_device` 10 after it), `s` / `l` of a
  PRG range and of the source (the editor's text back in bank 2),
  `;!long` after a SEQ load at `LINE_MAX`.
- [x] ~~T4. `@putc_inv` (D-P3-6, both platforms): the directory's header
  reversed at the right cells when the clamp holds the cursor at the
  last column — a C64 test in `test_disk.py` and its m65 twin in T2.~~
  Dropped with D-P3-6's amendment: no directory header reaches the
  last column.
- [x] T5. The build (`test_makefile_guards.py`): `make disk` and
  `make release PLATFORM=m65` write `build/cse-m65.d81` with `c1541
  -format "cse <version>,01" d81` and the PRG as `cse-m65`; `make run
  PLATFORM=m65` adds `-8` with it; `make size PLATFORM=m65` runs
  `size_report.py` for the m65 PRG (segments and modules, no C64 map).
- [x] T6. Tier X (`tests/emulator/test_m65_d81.py`, each ROM): the
  D81 (`-8`, `-autoload`) starts CSE to the prompt; on unit 8, through
  CBDOS, typed as in `test_m65_boot.py`: `$` lists `cse-m65` as
  `c1541 -list` does, the display keeping the VIC-IV's own font
  (CHARPTR `$001800`); `s` of a PRG range and `l` back (the bytes
  equal, the file as `c1541` reads it); the source saved from the
  editor, read back by `c1541`; CBDOS's status `00,ok,00,00` (no
  space after the code, unlike a 1541's).  It found D-P3-8.
- [x] T7. The gates: P3's pending count 2 → 0 (`PLAT_PENDING_VALUE`,
  `BP_PENDING` gone); the C64 PRGs byte-identical; the m65 budget
  held (22 750 B within 22 753 B: no raise).

The code went in this order — (1) the harness: T1; (2) the C64
`@putc_inv` fix: T4 (dropped, D-P3-6 amended); (3) disk.s on m65 — `READSS`, `disk_local_ptr`, `DIR_BUF`, the pointer
banks, `PLAT_SETBNK [bank]`, the pending values gone: T2, T3, T7; (4)
the build: T5; (5) Tier X: T6; then the P3 close (Step 5, the gate).

- **P3 gate met (2026-11-19):** T1–T3 and T5–T7 green on 920413 and
  920421 — in M65Emu (`test_m65_disk.py` on IEC unit 10, the IEC rows
  of `test_m65emu.py`, the map-record rows of `test_m65_debugger.py`)
  and in xmega65 (`test_m65_d81.py`: the D81 through CBDOS on unit 8,
  with `test_m65_boot.py` and `test_m65_break.py`); the P3 pending
  count 0, no pending value left; the C64 PRGs byte-identical;
  m65-6502 22 750 B, within the P2 budget (22 753 B: no raise in P3).
  Code commits 016f9aa, ffd9b1d, d1c86a4, b92b388, f9e3ddf.  Found on
  the way, fixed: D-P3-8 (CBDOS's calls return under the KERNAL's map
  record), `M65Session.idle()` stepping past the harness's traps (P2's
  harness); recorded on both ROMs: the KERNAL's serial entries are
  `JMP (vector)`; `LISTEN` / `TALK` note a slow device in `$A2` bit 7
  and `LOAD` reads byte by byte only then (else its fast loader); `ST`
  and `LDTND` are base page 0's `$90` and `$98`; a `RUN`-started PRG
  has `MSGFLG` `$00` (the snapshot `$80`) and the `SYS` map in the
  KERNAL's map record; a filename for `SETBNK`'s filename bank must be
  in CSE's view (`$2000` and up — all of CSE's are); CBDOS's status
  reads `00,ok,00,00`.  Closed, not fixed: `@putc_inv`'s
  last-column case (unreachable, D-P3-6).  The cartridge is a later
  release's (below).  Left manual: real drive timing, a physical
  MEGA65's internal drive.

**Later release: the m65 cartridge** (not in R7's first release;
operator, 2026-11-19).  Starts from A3's record (§ Analysis tasks):
its own delta settles the bootstrap that fetches past the ROM's 8 K,
a banked type for the hardware (an unbanked cartridge shows 16 K) or
xmega65's flat 32 K, `Q`'s exit (a reset restarts the cartridge), the
`.CRT` writer in `dev/`, and Tier X with `-cart`.

**P4 — the CPU layer on the platform.**  **Gate met (2026-11-19)** —
below, after the TDD plan.  P4 = slice 1 Phase B (B1–B7,
B4b, its prerequisite bugs) and the debugger's 45GS02 step, now with
an m65 build to run on: the m65-45gs02 build replaces m65-6502.  Its
deltas are slice 1's ([assembler_syntax.md](assembler_syntax.md),
the CPU-layer module docs), brought up to slice 2's reality below.

Operator, 2026-11-19 ("Go for P4.  Mind that the line disassembler
needs to make room for up to five hex bytes"), and the rulings asked
for in the analysis:
- **D-P4-1** `d` / `.` rows on m65 always have five byte columns —
  every `u` view, every screen mode; the mnemonic at column 24, a row
  38 columns at most, so 40 columns hold it.  C64 stays at three.
- **D-P4-2** A `.` row re-entered over matching bytes keeps its width:
  a 16-bit branch lists like an 8-bit one, so `.` passes `asm_rel16`
  and the unchanged row writes the same bytes.
- **D-P4-3** The debugger's step is in P4 and follows the real 45GS02
  whatever `u` selects (prefixes, 16-bit branches, `BSR`, `JSR (ind)`
  / `(abs,X)`, `RTN #`); with it the c64-65c02 `BBR` / `BBS` step bug.
- **D-P4-4** A3b stays deferred, its own cycle.
- **D-P4-10** (operator, 2026-11-19, after the analysis; its 65C02
  member dropped by D-P4b-1) The m65 CPU
  set is every CPU but the 6510: {6502, 65C02, 4510, 45GS02} (`asm_cpu`
  0, 2, 3, 4; 45GS02 the default) — the 45GS02 runs none of the
  6510's illegal opcodes.  `u` selects the assembler's CPU and the
  disassembler's view, as on the C64.  The 65C02 member: one
  generated bitmap, `mn7_c02` (16 B), marks the keys and extensions
  the 65C02 has; at `asm_cpu` 2 the 4510-only modes (`(e,sp),y`,
  far, a written `,z`, `REL16`) are refused and `(e)` is the eight
  `(zp)` opcodes; the disassembler's 65C02 view is a second bitmap
  over the 4510 map, listing `ZPIZ` as `($nn)`.  (An intermediate
  ruling, a 45GS02-only listing, was withdrawn the same day.)

Step-1 delta (written 2026-11-19; approved 2026-11-19 with the analysis):
- [x] [repl.md](modules/repl.md): five byte columns on m65 (the block
  dump, § Line format, `emit_dot`), `.` takes up to 5 pairs, mode 2
  keeps the width (`asm_rel16`), `dot_assemble`'s word with a digit
  and the m65 forms, `u` per build (6510 on c64-65c02, D2).
- [x] [README.md](../README.md): the poke's 1–5 bytes on the MEGA65;
  § On the MEGA65 *The CPU*.
- [x] [asm_line.md](modules/asm_line.md): the suffixes as built (no
  "planned"), `_asm_sink` 4 B on `MEGA_SUPPORT`, zone B a range on
  m65, zones D/E assembled, `asm_rel16`.
- [x] [opcode_lookup.md](modules/opcode_lookup.md) (`mn_modes_x`, the
  m65 `oplen_tbl` block — retired in step (9)), [dasm.md](modules/dasm.md) (KDATA map blocks
  on m65, the 6502 and 65C02 views over the 4510 map — D-P4-10 — no
  "planned"), [addr_mode.md](modules/addr_mode.md),
  [mn_classify.md](modules/mn_classify.md), [symtab.md](modules/symtab.md):
  "planned" gone; [assembler_syntax.md](assembler_syntax.md): `ldq
  ($fb),z` (LDQ's row is `ZPIZ`).
- [x] [debugger.md](modules/debugger.md) § Next-PC: the m65 table,
  `BBR` / `BBS`, the ROM boundary per platform.
- [x] [build_system.md](build_system.md): m65-45gs02 the one m65 build
  (m65-6502 retired), the consumer matrix's debugger row, golden files
  per CPU set (`asm_dasm_45gs02.json`); [platform_layer.md](platform_layer.md);
  [testing.md](testing.md) (the m65 `asm_core` / `dasm` bundles).
- [x] Slice 1's list: B3 (the wide immediate is B4's), B4b (the stamp
  landed in f13e739), A3b deferred.

**P4 analysis record (2026-11-19), doc against code — approved 2026-11-19.**
- **The build.**  The Makefile forces `CPU := 6502` on m65; no source
  defines or reads `MEGA_SUPPORT` / `CPU_45GS02`; `CPU_CEIL` is passed
  and read by nothing.  `conftest.PROD_DEFS` has the C64 sets only;
  `Bundle(platform="m65")` works.  The m65 asm bundles must run on
  `MPU45GS02` (`_asm_emit` stores through `FAR_STA`, `[ptr],z`).
- **The generators.**  `dev/mnemonic_tables.py` knows the C64 sets
  only; given the 45gs02 set it dies in validation (no m65
  categories, no Q zone, two mask planes for 20 modes, zone B a single
  profile — the m65 branches are a range: `REL`, `REL`+`REL16`,
  `REL16`).  `dev/dasm_tables.py` dies on 20 modes in nibbles, has no
  Q map, and its subset test fails on `$EA` (the 6502 view's `NOP`
  against the 4510 map's `EOM`, D3); with the 65C02 view (D-P4-10)
  the eight `(zp)` opcodes differ too (`ZPI` against `ZPIZ`).  `instruction_set.py` serves the
  `4510` / `45gs02` views (98 keys); the model is 36 profiles, 7 delta
  rows × 20 modes, 284 B (up to 45 profiles, 320 B, if adjacency
  forces copies).  `oplen_tbl` has one C64 content, linked on m65 too.
- **The classifier.**  mn6 on m65 today; mn7 over the m65 keys needs
  its own `T` (bbbc64's `mn7gs` search is the reference).
- **The assembler.**  No suffix scan; zones D/E are `jmp asm_error`
  (the prerequisite bug — on m65 the 4510 keeps all four bit-ops);
  zone B handles `REL` only; the gate has the CMOS `cmp #2` path only;
  `_asm_sink` is 3 B (`cpx #3`), short for a 5-byte instruction at
  `$FFFF`; addr_mode has none of the m65 forms.  `asm_pc` / `asm_out`
  are far pointers already and `_asm_emit` stores far.
- **`.cpu` / `u`.**  `set_cpu` accepts `65xx` only and checks no set
  (`.cpu 65c02` works on m65-6502); `u` cannot parse `4510` /
  `45gs02` and masks by build.
- **The disassembler.**  No peel, no IMM16 / REL16 formats, no `,z` /
  `,sp),y` suffixes (an unknown suffix falls into `),y`), no `[ ]`,
  8-bit branch targets only, 4-bit modes; `_dasm_in` 3 B.
- **The REPL.**  `emit_dot` hard-codes 3 columns; `.` parses 3 pairs
  (`rp_hexbuf` 3 B, the poke's `cmp #3`), so a 5-byte row re-entered
  would hand bytes to `dot_assemble`; `dot_assemble` stops at a digit.
  A REL16 branch re-entered unchanged would shrink (D-P4-2).
- **The debugger.**  `step_next_pc` uses the C64 `oplen_tbl` and the
  `(op & $1F) = $10` branch test; its BRA / `JMP (a,X)` paths are
  `CMOS_SUPPORT` only, absent on m65; `BBR` / `BBS` are linear, so a
  taken one escapes the step on c64-65c02 too.
- **Room.**  m65-6502 is 22 750 B (budget 22 753).  Code window
  `$2000–$7FFF`: 2 529 B free; data window `3.8000–3.A0FF`: about
  7 200 B free; CSE's base page: 2 B free (P4 needs none).  Estimated
  growth: classifier +150, asm tables +250, asm_line / addr_mode
  +250–400, dasm tables +250 (KDATA) and peel / formats +150, REPL and
  debugger +200 — roughly 1.2–1.5 K, most of it code.

Decisions (approved 2026-11-19):
- **D-P4-5** The generators: cse's `mnemonic_tables.py` and
  `dasm_tables.py` gain the m65 set {6502, 65C02, 4510, 45GS02} — m65
  categories, the Q zone, zone B as a range, a third mask plane;
  byte-wide modes, the Q map, the listing-name rule across views,
  the 6502 and 65C02 subset views (D-P4-10), five view entries,
  `mn7_c02`; an m65 `oplen_tbl` block (retired in step (9): the step
  takes the disassembler's length).  bbbc64's `asm_tables.py`
  and `mn7gs` are the reference, not the source (cse selects the CPU at
  run time; bbbc64 does not).
- **D-P4-6** On m65 the generated tables live in KDATA (the data
  window, always mapped while CSE runs), the code window kept for code.
- **D-P4-7** The two prerequisite bugs land first, each in its own
  step: the bit-op mnemonics (c64-65c02 assembles `RMB` … `BBS`;
  the 65c02 golden file re-recorded) and the `.cpu` / `u` CPU set (D2).
  Each C64 build they grow gets its budget raise in a commit of its
  own.  The KDATA-bound bug is C64-only and stays out of P4.
- **D-P4-8** `_asm_sink` is 4 B on `MEGA_SUPPORT` only.
- **D-P4-9** m65-45gs02 gets its golden file and speed baseline in P4
  (`asm_dasm_45gs02.json`, cycles from `MPU45GS02`); its size budget
  is raised in a commit of its own before each step that grows it.

The code, in this order — (1) the bit-op mnemonics (D-P4-7); (2) the
CPU set of `.cpu` / `u` (D2); (3) the generators' m65 set, host tests
only (D-P4-5, D-P4-6); (4) the m65-45gs02 build: defines, the m65
bundles on `MPU45GS02`, mn7 over the m65 keys, m65-6502 retired (B1,
B2); (5) mode_parse and asm_line on m65 (B3, B4, B4b, D-P4-8); (6)
`.cpu` / `u` on m65 (B5); (7) the disassembler (B6); (8) the REPL's
five columns, `.` with five pairs and `asm_rel16` (B7, D-P4-1, D-P4-2);
(9) the 45GS02 step (D-P4-3); (10) the golden file, Tier X, the P4
close (D-P4-9).

Step (1) done 2026-11-19 (budget e24cc75, then the feature commit):
every mn7 build reads the digit; zones D / E assemble on c64-65c02;
mode_parse's ZPREL now hands asm_line the whole target (`asm_opr`)
and the zero-page byte (`asm_tmp2`) — the old low-byte-only output
could not compute a far offset (a contract change found while
coding, addr_mode.md).  Measured: c64-6510 +24 B, c64-65c02 +89 B
(budgets raised), c64-6502 −12 B and m65-6502 −15 B (the shared
offset helper; budgets lowered); asm sweep cycles over the old cases
6502 −0.02 %, 6510 +1.9 %, 65c02 +2.5 %, worst case +9.4 %; the three
golden files re-recorded with the 768 digit rows (96 accepted on
65c02).  Found on the way, fixed in its own commit (853a533):
`disk.s`'s `jmp (callback)` vector at `$CEFF` in the debug c64-65c02
build — the BSS segment is now 2-aligned.

Step (2) done 2026-11-19: one table, `cpu_names` (the build's members,
value + name), and one scan, `cpu_lookup` (asm_src.s), serve `.cpu`,
`u` and `u`'s listing; c64-65c02 offers the 6510 (D2).  Every build
shrank: c64-6502 −40, c64-6510 −61, c64-65c02 −55, m65-6502 −49 B
(budgets lowered).

Step (3) done 2026-11-19, host-side: `mnemonic_tables.py` builds the
m65 set (45 profiles — G pairs and Q groups repeat their members — 7
rows × 20 modes, three mask planes, zones B 1–3 F 4 C 5 D 6 E 7 G 8
Q 16 H 35; `mn7gs`, 0 false positives; `mn7_c02`; the 4510's
`oplen_tbl` block), validated derive-or-die over the four views and
the prefixed rows; `dasm_tables.py` the one 4510 map with the 6502 and
65C02 bitmaps, the Q map, byte modes, 98 names, all in KDATA (695 +
196 B), the view tables padded per platform so the C64 blocks stay
byte-identical.  The bundle-driven sweeps take a set once it has a
bundle (`PROD_DEFS`, step (4)).

Step (4) done 2026-11-19: the m65 build is m65-45gs02 (`_45gs02_DEFS`;
m65-6502 retired), 23 642 B (budget eaa3662).  dasm.s reads the m65
map — byte-wide modes, the bitmap offset in `dasm_cpu_bm` — and the
C64 gate makes the build a 6502 assembler until step (5); `$EA` lists
`eom` (D3).  The m65 `asm_core` and `dasm` bundles (`M65_CONFIGS`)
link by `dev/m65_test.cfg` and run on M65Emu in clean mode through
`asm_dasm_runner`; the classifier sweep and table check over the 98
keys pass.  Found on the way: `mnemonic_tables.py` iterated a
frozenset, so the m65 profile numbering changed with Python's hash
seed — sorted now, and a test generates under two seeds.  Tier I and
Tier X (52) green on the new build.

Step (5) done 2026-11-19: mode_parse reads `(e),z`, `(e,sp),y` /
`(e,s),y`, `[e]`, `[e],z` (`_au_far`); asm_line on `MEGA_SUPPORT` reads
the `q` suffix, gates by the m65 matrix (the 65C02 row through
`mn7_c02`), takes the Q profile at effective + 1, dispatches the
zone-B range, chooses REL / REL16 from one 16-bit distance (forward:
REL; the `asm_rel16` request), applies the far / 65C02 / IMM16 rules
and emits `$42 $42` / `$EA` before the opcode; `_asm_sink` is 4 B;
`asm_opcode_lookup` reads the third plane.  test_asm_m65.py: all 950
rows of the four views assemble at their CPU, the gate matrix, the
word, the Z rule, far, stack-relative, IMM16, branch width, the
`$FFFF` edge; test_opcode_lookup's sweep and a pass-stable far branch
in a source (test_m65_asm_src.py) on m65 too.  Found while coding:
`asm_opcode_lookup`'s new third-plane test cleared C on the hi-plane
rejection path (a rejected mode 8–15 read as accepted, opcode `$00`).
m65-45gs02 24 141 B.  C64 PRGs byte-identical.

Step (6) done 2026-11-19 by step (2)'s table: `cpu_names` holds the m65
set under `CPU_45GS02`, so `.cpu` and `u` take 6502, 65c02, 4510 and
45gs02 and refuse 6510 on m65 — tests only (T6).

Step (7) done 2026-11-19: dasm.s on `MEGA_SUPPORT` snapshots 5 bytes,
peels the prefixes at `asm_cpu` 4 (Q by the Q map, far by the map's
`ZPIZ`, both; the snapshot shifted, `_dasm_pfx`), adds them to the
length, lists Q names and `q` stems, and formats `#$1234`, 16-bit
targets, `),z`, `,sp),y`, `[ ]`, `ZPIZ` as `($nn)` (the 65C02 view, the
Q-map-2 forms) and the accumulator bare.  test_dasm_m65.py: every
opcode at `asm_cpu` 0 / 2 / 3 / 4 as its view, every prefixed row at
4, no peel below, and the asm → dasm → asm round trip over the 45GS02
view.  m65-45gs02 24 484 B.

Step (8) done 2026-11-19: `DOT_MAX` (3 c64, 5 m65) sizes `.`'s pairs,
`rp_hexbuf`, `emit_dot`'s copy and columns; `.` re-entered over
matching bytes disassembles them first and passes `asm_rel16` for a
16-bit branch; `dot_assemble` keeps `[`.  M65Session tests: five
columns in every mode (the 38-column row at column 24 in 40), a
five-byte poke, unchanged rows re-entered byte for byte (16-bit
branches in reach among them), an edited branch by distance, the m65
forms through `.`; test_m65_repl's rows are five columns wide.  Found
on the way, in the harness: the screen-text helpers knew no `[` `]`
(`_scr`, `decode_screen_codes`).  m65-45gs02 24 510 B.

Step (9) done 2026-11-19: on `MEGA_SUPPORT` `step_next_pc` reads the
instruction's length and base opcode from the disassembler at
`asm_cpu` 4 (`dasm_insn_pre`, `step_len`), whatever `u` lists; a
prefixed instruction is linear; `$x3` 16-bit branches, `BRA` `$83`,
`BSR`, `JSR (ind)` / `(abs,X)`, `RTN #` and `JMP (ind)` without the
wrap follow debugger.md's m65 table; `$7C`, `$80` and `$xF` need no
`asm_cpu` check.  m65 links no `oplen_tbl` (the generator's m65 block
retired).  c64-65c02: `BBR` / `BBS` step as branches (they were
linear, so `t` ran a taken one through) — one `asm_cpu` check now
guards `$7C`, `$80` and `$xF`; the 3-byte branches put `PC + 3` in
`step_next_lo` through the linear add (the two slots are alike).
cse-cmos.prg re-recorded (the deliberate C64 change); 6510 and 6502
byte-identical.  Found on the way: `.`'s width check (step 8) read the
bytes with `dasm_insn`, whose far pointer kept stale bank bytes and
which skips the user-ZP image — it now shares `emit_dot`'s staged read
(`DOT_DASM`).  Tier X `test_m65_step.py`: a typed program stepped in
xmega65 lands where M65Emu does, `JMP ($30FF)` included (no wrap on
the real CPU).  c64-65c02 21 879 B, m65-45gs02 24 714 B.

Step (10) done 2026-11-19: the golden sweeps take the m65 set's cases
(every opcode behind each prefix; every 4510 and 45GS02 row with each
spelling of its mode) and `asm_dasm_45gs02.json` is recorded from
063220c; `test_golden_asm_dasm.py` holds it.  Tier X
`test_m65_asm_run.py`: a program typed with `.` (`PHW #`, `PLA`, `LDQ`
/ `STQ`, a far `LDA`, a taken 16-bit `BEQ`) and run with `j` stores
the predicted bytes in xmega65 and M65Emu; the typed-run loop is
`test_m65_boot.typed_run`, shared with `test_m65_step.py`.

**P4 TDD analysis (2026-11-19) — approved 2026-11-19.**  The tests, written
first, step by step; each is red until its code lands.  Automation
judgement: all of it is automatable — the generators on the host,
the assembler and disassembler as bundles (py65 for the C64 sets,
`MPU45GS02` for the m65 set), the REPL and the debugger on the PRGs
(C64Emu, M65Emu), the real CPU in xmega65 (Tier X).  Left to the
hardware: O1 and O3, as before.

- [x] T1. Bit-op mnemonics (step 1; `test_asm_line.py`, the c64-65c02
  bundle): `rmb0`–`rmb7` / `smb0`–`smb7 $12` assemble the opcode with
  the digit in bits 6:4; `bbr0`–`bbs7 $12,target` likewise, the
  target as zone B's (`REL` only, out of reach `;?syntax`); `rmb $12`,
  `rmb8`, `lda3`, `rmb0x` are `;?syntax`; on c64-6510 `rmb0` is
  `;?cpu`, on c64-6502 `;?syntax`.  `dot_assemble` passes `rmb3 $12`
  (`test_repl.py`); a source line `bbs7 $12,label` assembles in both
  passes (`test_asm_src.py`).  The 65c02 golden file is re-recorded
  with the digit rows (their asm cases were `;?syntax` before).
- [x] T2. The CPU set of `.cpu` / `u` (step 2; on each C64 PRG):
  `.cpu` accepts exactly the build's set and refuses any other value
  as it refuses an unknown one today; `u 6510` works on c64-65c02; `u`
  lists the set, the active one marked.
- [x] T3. The generators' m65 set (step 3; host tests, the
  `model` fixtures of `test_mnemonic_tables.py` and
  `test_dasm_tables.py` parametrised over it): every existing rule
  holds for the m65 set; three mask planes; zone B a range in the
  order `REL`, `REL`+`REL16`, `REL16`; the Q zone's groups adjacent;
  the categories of mn_classify.md; byte-wide modes; the Q map equal
  to `instruction_set.py`'s Q forms (the seven `($nn)` ones flagged
  2); the m65 set's one map with the 6502 and 65C02 views as bitmaps
  over it (`ZPI` = `ZPIZ` for the 65C02 view), `$EA` `EOM` in every
  view; five view entries; `mn7_c02` equal to the 65C02 view's keys
  and extensions; the m65 `oplen_tbl` block = the 4510's
  lengths (retired in step (9) with its test); the m65 `mn7` `T` with no false positive over the invalid
  strings (as the C64 test).  The C64 blocks byte-identical (the C64
  PRG hashes hold).
- [x] T4. The m65-45gs02 build (step 4; `test_makefile_guards.py`,
  `conftest.PROD_DEFS`): `PLATFORM=m65` passes `CPU_45GS02`
  `MEGA_SUPPORT` `CPU_CEIL=4` `DEFAULT_CPU=4`; the m65 `asm_core` and
  `dasm` bundles link and run on `MPU45GS02` in clean mode; the
  classifier test over every m65 key and the invalid strings; after
  the cold start `asm_cpu` = 4.  Every m65 Tier I and Tier X suite of
  P0–P3 stays green on the new build.
- [x] T5. The assembler on m65 (step 5; the m65 `asm_core` bundle):
  every row of the 6502, 65C02, 4510 and 45GS02 views through
  `asm_line` at each `asm_cpu` gives the oracle's bytes or error (the
  sweep the golden file records); targeted: the m65 gate matrix cell
  by cell, its `asm_cpu=2` row by `mn7_c02`; at `asm_cpu` 2 `lda ($12)`
  is `$B2 $12`, `lda ($12),z` `;?syntax`, `lda ($12,sp),y` and
  `lda [$12]` `;?cpu`, `jsr ($1234)` and `stx $1234,y` refused as on
  a 65C02, `bra` out of reach `;?syntax`;
  the suffix rules (`q`, digit, `staq` = `stq`, `nop` = `eom` = `$EA`);
  the Z rule (`(e)` / `(e),z` per Q form, `,z` where Z is not added
  refused); `(e,sp),y` and `(e,s),y`; `[e]` / `[e],z` and their
  `;?cpu` at `asm_cpu` 0 / 3; the prefix order `$42 $42 $EA op`;
  `PHW #$1234`; branch width — in reach `REL`, out of reach `REL16`,
  a forward target `REL`, `BSR` `REL16` only, `asm_rel16` forcing
  `REL16` and cleared after the instruction; the sink — a 5-byte
  instruction ending at `$FFFF` accepted, one byte later refused,
  nothing at `$0000`/`$0001`.  Source assembly (`test_asm_src.py`,
  m65): a forward and a backward far branch give the same addresses
  in both passes.
- [x] T6. `.cpu` / `u` on m65 (step 6; M65Session): `.cpu 6502`,
  `65c02`, `4510`, `45gs02` set 0 / 2 / 3 / 4, `6510` refused;
  `u` lists `6502 65c02 4510 45gs02` with the active one marked.
- [x] T7. The disassembler on m65 (step 7; the m65 `dasm` bundle):
  every opcode at `asm_cpu` 0 / 2 / 3 / 4 and every prefix sequence
  the peel accepts (`$42 $42` + each Q opcode, `$EA` + each
  far-capable one, both) lists as the oracle, with its length; the
  peel only at `asm_cpu` 4 (`$42` alone `neg`, a lone `$EA` `eom` in
  every view); the 65C02 view lists `$B2 $12` as `lda ($12)` and a
  4510-only opcode as `...`;
  the formats: `#$1234`, a 16-bit branch target counted from the last
  byte, `($12),z`, `($12,sp),y`, `[$12],z`, the Q names and
  decorations, the seven `($nn)` Q forms.  Round trip: every row
  assembled, listed and assembled again gives the same bytes (A5's
  round trip, on the m65 set).
- [x] T8. The REPL on m65 (step 8; M65Session, each mode): `d` rows
  with five columns, the mnemonic at column 24, the longest row
  within 40 columns; `. 42 42 ea b2 10` pokes five bytes; RETURN on an
  unchanged `d` row writes the same bytes for a sample of every mode
  and prefix, a 16-bit branch in reach among them; an edited row
  assembles by the usual rules; `dot_assemble` takes `rmb3`, `ldq`,
  `staq`, `[`, `,z`, `,sp),y`; the break panel and `t`'s row show five
  columns.  `test_m65_repl.py`'s `3001:.  ea        nop` row becomes
  the five-column `eom` row.  The C64 rows are unchanged (the
  existing tests).
- [x] T9. The 45GS02 step (step 9; `test_m65_debugger.py`): every row
  of debugger.md's m65 Next-PC table through `step_next_pc`, at
  `asm_cpu` 0, 2, 3 and 4 alike — prefixed lengths (Q, far, both), the
  16-bit branches under `t` and `o`, `BRA`, `BSR`, `JSR (ind)` /
  `(abs,X)`, `RTN #`, `JMP (ind)` without the page wrap — and `t` /
  `o` run on M65Emu landing where the CPU goes.  On c64-65c02 (C64Emu)
  `BBR` / `BBS` under `t` and `o`, taken and not.  Tier X: a stepped
  program with a Q, a far and a 16-bit branch in xmega65 stops where
  M65Emu stops — `JMP (ind)` at `$xxFF` among them, the real CPU's
  answer on the wrap.
- [x] T10. The close (step 10): `asm_dasm_45gs02.json` recorded and
  held by `test_golden_asm_dasm.py`; `test_size_budget.py`'s
  m65-45gs02 entry; Tier X — a program assembled by CSE (Q, far,
  16-bit branches, `PHW`) runs in xmega65 with the results the oracle
  predicts.

- **P4 gate met (2026-11-19):** T1–T10 green — Tier U and I on
  M65Emu and the C64 bundles (6195 passed), Tier X on 920413 and
  920421 in xmega65 (164 passed)
  (`test_m65_boot.py`, `test_m65_break.py`, `test_m65_d81.py`, and
  P4's `test_m65_step.py`, `test_m65_asm_run.py`).  The m65 build is
  m65-45gs02 (m65-6502 retired): the CPU set {6502, 65C02, 4510,
  45GS02}, `asm_cpu` 4 by default; five byte columns in `d` / `.`;
  the debugger steps the 45GS02 whatever `u` lists.
  `asm_dasm_45gs02.json` recorded (1792 dasm + 6520 asm cases; a
  cycle on M65Emu is an instruction).  Sizes: m65-45gs02 24 714 B;
  c64-6510 21 192 B, c64-6502 20 834 B, c64-65c02 21 879 B — every
  C64 change deliberate and recorded (steps (1), (2), (9)).  Code
  commits 853a533, 5de8c9e, f4cbc93, fe0eabe, 98965a0, 2b3dd38,
  7cd6ed4, 035bb97, 7a931c5, 60c2c1c, 063220c and the close.  Found
  on the way, fixed: the bit-op mnemonics and the CPU-set gate (the
  prerequisite bugs), disk.s's callback on an odd address (BSS
  2-aligned), mode_parse's ZPREL output (the whole target),
  opcode_lookup's third-plane C, the generators' iteration order
  (hash-seed test), `.`'s width-check read (`DOT_DASM`), c64-65c02's
  `BBR` / `BBS` step.  Recorded: `aslq a` is `ASLQ` with the label
  `a` (a Q form takes no explicit accumulator, asm_line.md); `PHW`
  pushes the low byte first; the real CPU's `JMP ($xxFF)` does not
  wrap.  Deferred: A3b (D-P4-4).

**P4b — no 65C02 on the targets.**  **Gate met (2026-11-19)** — below,
after the TDD plan.  Operator, 2026-11-19: "Drop cmos
support from both our targets, but assembler and disassembler are to
retain a fully supported and tested cmos mode for later ports").  No
CBM machine has a 65C02; what it cost was measured first (P4 review
follow-up): on m65 about 130 B and the hardest special cases (`(e)`
as `ZPIZ`, `mn7_c02`, a second view bitmap); on the C64 a whole build
with its fixtures, golden file, hash and budget, but almost no code —
the 4510 is a 65C02 with additions, so the 65C02's machinery stays
for m65 either way.

Rulings (operator, 2026-11-19):
- **D-P4b-1** The targets have no 65C02: the c64-65c02 build is
  dropped (`make CPU=65c02` is refused like any unknown CPU), and the
  m65 set is {6502, 4510, 45GS02} (`asm_cpu` 0, 3, 4) — D-P4-10's
  65C02 member goes.
- **D-P4b-2** The assembler and the disassembler keep a **CMOS mode**,
  fully supported and tested, for a later 65C02 port: the CPU set
  reshaped to {6502, 65C02} (`asm_cpu` 0, 2 — no 6510 member, whose
  illegals no 65C02 machine runs), built only as test bundles
  (`asm_core`, `dasm`, `mn7`, `asm_src`) and held to its golden file.
- **D-P4b-3** The debugger's 65C02 step paths go (platform code; a
  later port writes its own step); the 45GS02 step keeps its rows.

Step-1 delta (written 2026-11-19; approved 2026-11-19 with the analysis):
- [x] [build_system.md](build_system.md) (the builds table and the
  CMOS mode, the consumer matrix, the classifier keys rule, the
  `oplen_tbl` content, the directory layout, the default test PRG),
  [testing.md](testing.md) (the default PRG, the bundle variants, the
  per-CPU fixture), [asm_line.md](modules/asm_line.md) (variants, the
  gate matrices, the word),
  [mn_classify.md](modules/mn_classify.md) (key sets per set, no
  `mn7_c02`), [dasm.md](modules/dasm.md) (one subset view per set),
  [opcode_lookup.md](modules/opcode_lookup.md) (`oplen_tbl`, zone C in
  the CMOS mode), [debugger.md](modules/debugger.md) (no 65C02 rows),
  [repl.md](modules/repl.md), [assembler_syntax.md](assembler_syntax.md),
  [project.md](project.md), README, glossary, asm_err.md,
  addr_mode.md, architecture.md, optimization.md, project_layout.md,
  [vice_test_plan.md](vice_test_plan.md) (two C64 variants).

**P4b analysis record (2026-11-19), doc against code — approved
2026-11-19.**
- **Build.**  The Makefile builds c64-65c02 (`_65c02_DEFS`, the
  `release` / `debug` / `_dist` / `disk` / `size` rules, `cmos/`
  dirs, `cse-cmos` on the D64); `test_size_budget.py` and
  `c64_prg_sha256.json` hold it; `test_build_parity.py` compares every
  `PROD_DEFS` set to the Makefile.
- **Generators.**  `CPU_SETS['65c02']` has the views 6502, 6510,
  65c02; both C64 `mn7` blocks hold all 114 names; `oplen_lengths()`
  merges the 6510 and 65C02 rows with the crash-yield rule; the 65c02
  set's disassembler has two maps (65C02, 6510); fixed zones are
  numbered as a prefix of A B F C D E, which the reshaped set breaks
  (D and E without a C key).  On m65: the 65c02 view, `mn7_c02` /
  `key_c02`, `C02_REFUSED`, the `ZPI` = `ZPIZ` view rule, two view
  bitmaps (`dasm_cpu_bm` = 1 + offset).
- **asm_line.**  The C64 gate's `cat` 11 reject and the digit scan
  are compiled into c64-6510, which then has no `cat` 01 / 11 or digit
  key; m65: `_asm_c02`, the gate's `asm_cpu` 2 branch, the 65C02 block
  of `_asm_m65_mode`, `@b_try16`'s 65C02 check.
- **dasm.**  m65: `@paren_z`'s `asm_cpu` 2 check and the two-bitmap
  offset path.
- **asm_src.**  `cpu_names` offers 6510 on `CPU_65C02` and 65c02 on
  `CPU_45GS02`.
- **debugger.**  `.if CMOS or MEGA` blocks with their C64 `asm_cpu`
  checks, the `CMOS_SUPPORT` `JMP ($xxFF)` path, and P4 step (9)'s
  c64-65c02 `BBR` / `BBS` step.
- **Tests.**  `cse_prg` / `cse_release_prg` are the CMOS PRGs and
  `cse_prg_per_cpu` has a `cmos` member; tests run 65C02 behaviour on
  the PRG (the step's `JMP (abs,X)`, `BBR` / `BBS` and no-wrap rows,
  `.cpu` / `u` per build, the REPL's bit-op `.`); the 6510 and 45gs02
  golden files hold the present answers (`STZ` `;?cpu` on c64-6510,
  `asm_cpu` 2 cases on m65).
- **Measured cost** (P4 review follow-up): m65 ≈ 130 B; c64-65c02's
  own code 12 sites; 910 of 6278 collected tests are its variants.

Decisions (approved 2026-11-19):
- **D-P4b-4** Every set's classifier holds exactly its own keys: the C64
  `mn7` exception goes; c64-6510 answers `stz` with `;?syntax` (no CPU
  of its set has it), as c64-6502 already does.  One `T` serves the
  6510 and CMOS blocks.
- **D-P4b-5** `oplen_tbl` is the 6510 view's lengths: the crash (JAM)
  opcodes `$x2` are 1 byte, the conflict check and the crash-yield
  rule go.  A deliberate C64 change (the C64 hashes re-recorded).
- **D-P4b-6** The CMOS mode keeps the zone order A B F C D E with one
  unused zone-C profile, so asm_line's fixed-zone table stays indexed
  by `pidx`.
- **D-P4b-7** The digit scan is compiled where the set has digit keys
  (`BIT_OPS`: the CMOS mode, m65), not into c64-6510.
- **D-P4b-8** The default C64 test PRG is the 6510 build (debug and
  release); `cse_prg_per_cpu` is {6510, 6502}.  The un-suffixed
  bundle names stay the `65c02` set's, now the CMOS mode, so the
  bulk of the asm tests keep it exercised; 65C02 behaviour tested on
  the PRG moves to the bundles, the debugger's goes with its code.
- **D-P4b-9** Goldens: `asm_dasm_65c02.json` (reshaped set),
  `asm_dasm_6510.json` (D-P4b-4) and `asm_dasm_45gs02.json` (no
  `asm_cpu` 2) re-recorded, each in the commit that changes it;
  `asm_dasm_6502.json` unchanged.  Budgets: c64-65c02 leaves
  `BUDGET`; the others are lowered to their new sizes in the commits
  that shrink them.

Code order: (1) the generators — the CMOS mode reshaped, per-set
keys, `oplen_tbl`, zone C, the m65 set without the 65C02 — with the
bundle tests; (2) asm_line and asm_src on the C64 and in the CMOS
mode (gate, digit scan, `cpu_names`); (3) m65 without the 65C02
(asm_line, dasm, asm_src); (4) the build and the fixtures (Makefile,
default PRG, budget, hashes, parity); (5) the debugger's 65C02 paths;
(6) the close — full suite, Tier X, Step 5, the P4b record.

**P4b TDD analysis (2026-11-19) — approved 2026-11-19.**  The tests,
written first, step by step; each is red until its code lands.  Where
a test holds today's 65C02 answer it is rewritten to the new contract,
not deleted, unless its subject goes (the debugger's 65C02 paths).
- [x] T1. The generators (step 1; `test_mnemonic_tables.py`,
  `test_dasm_tables.py`, `test_mn_classify.py`): the `65c02` set's
  views are 6502 and 65c02; each set's classifier block holds exactly
  its keys (6510 102, CMOS 68, the m65 98), the C64 and CMOS blocks
  over one `T`, no false positive in either; `oplen_tbl` is the 6510
  view's lengths (`$x2` 1, no conflict path left); the CMOS mode's
  zones A B F C D E with an unused C; the m65 set's views 6502, 4510,
  45gs02, no `mn7_c02`, one view bitmap; the CMOS set's disassembler
  one map and a 6502 bitmap.  `test_m65_c02_marks_what_the_65c02_has`
  goes with `mn7_c02`; the `mn7` bundle has `6510` and `65c02`
  variants.
- [x] T2. The assembler on the C64 sets and in the CMOS mode (step 2;
  `test_asm_line.py`, `test_asm_src.py`, the golden files): every
  cell of asm_line.md's C64 / CMOS gate matrix per bundle — on
  `asm_6510_syms` a 65C02 key (`stz`, `rmb0`, `bra`) is `;?syntax`,
  on the CMOS bundle a 6510 illegal (`lax`) is `;?syntax` and `.cpu
  6510` an error; the digit scan absent from c64-6510 (`rmb0`, `lda4`
  `;?syntax`); `.cpu` takes exactly each set.  The CMOS bundle's
  existing tests that use 6510 illegals move to `asm_6510_syms`.
  `asm_dasm_65c02.json` and `asm_dasm_6510.json` re-recorded (D-P4b-9).
- [x] T3. m65 without the 65C02 (step 3; `test_asm_m65.py`,
  `test_dasm_m65.py`, `test_m65_repl.py`): the views 6502, 4510,
  45gs02 (`asm_cpu` 0, 3, 4); the gate matrix without the `asm_cpu`
  2 row; `u 65c02` and `.cpu 65c02` refused, `u` listing `6502 4510
  45gs02*`; the lower-CPU refusals 6502 → 4510 and 4510 → 45gs02.
  `asm_dasm_45gs02.json` re-recorded.
- [x] T4. The build and the fixtures (step 4; `test_makefile_guards.py`,
  `test_build_parity.py`, `test_build_freshness.py`,
  `test_clean_build.py`, `test_size_budget.py`, `test_platform_audit.py`,
  conftest): `make CPU=65c02` refused; `make release` / `debug` build
  the 6502 and 6510 PRGs (and m65), the D64 two files; parity over the
  Makefile's sets (the CMOS mode excluded by name); `BUDGET` and the
  hashes without c64-65c02, the 6510 and 6502 hashes re-recorded
  (D-P4b-5); `cse_prg` / `cse_release_prg` the 6510 PRGs,
  `cse_prg_per_cpu` {6510, 6502}; the bundles with no CPU-gated code
  on the `6510` `-D` set.  The C64Emu tests that ran 65C02 behaviour on
  the PRG (test_repl's `u` / bit-op `.`, test_asm_src's per-build
  `.cpu`) hold the two C64 sets; their 65C02 cases live in the CMOS
  bundles (T2).
- [x] T5. The debugger (step 5; `test_kernel_transition.py`): on the
  C64 builds the opcodes the 65C02 gives other meanings are the
  6510 view's — `$0F` (`SLO` abs) 3 bytes, `$80` (`SKB` #) 2, `$7C`
  1 (no row names it; `d` lists `...`) — and `JMP ($xxFF)` wraps,
  whatever `asm_cpu` holds; `TestStepBitBranch`, `test_jmp_ind_no_wrap_65c02` and
  `test_jmp_abs_x_vector_from_user_zp_65c02` go with the code they
  test.  The m65 step tests (`test_m65_debugger.py`) hold unchanged
  at `asm_cpu` 0, 3, 4.
- [x] T6. The close (step 6): the full suite, Tier X, the C64 hashes
  and budgets at their new values, the audits clean.

Steps (1), (2) and (4) done 2026-11-19, one commit: the generators'
set change moves the assembler and the PRGs at once, so they could not
land apart.  `mn7_6510` / `mn7_cmos` (mn7 over each set's categories,
one `T`; `hashes.py` untouched, it is shared with bbbc64); a legal key
is `cat` 1 only in a set with the 65C02, so the C64 blocks — c64-6502's
too — hold `cat` 00 and 10 alone; the CMOS mode's unused zone-C
profile; `oplen_tbl` from the 6510 view (`$7C` is 1 byte: no 6510 row
names it, and `d` lists `...` — before P4b the 65C02's `JMP (a,X)` made
it 3).  asm_line: a gate per set (none on c64-6502), the digit scan
under `BIT_OPS`; asm_src: `.cpu 6510` only on `CPU_6510`.  The Makefile
builds 6502 and 6510 and refuses any other C64 `CPU` (there was no
such guard; `CPU=6503` built a broken PRG).  Tests: the gate matrices
assert the error category; `test_assemble` runs an illegal on the 6510
bundle; `TestDotBitOps` went (no C64 set has a digit key; m65 covers
`. rmb3`); the debugger's 65C02 tests went and `TestNmosStep` (T5's)
holds the C64 step at `asm_cpu` 0, 1, 2.  Goldens re-recorded: 6510
(294 CMOS cases `;?cpu` → `;?syntax`, disassembly identical) and the
CMOS mode (the `asm_cpu` 1 cases gone, 1068 illegals `;?cpu` →
`;?syntax`).  c64-6510 21 192 → 21 153 B, c64-6502 20 834 → 20 808 B,
both hashes re-recorded (the deliberate C64 change); m65 unchanged.

Step (3) done 2026-11-19: the m65 set is {6502, 4510, 45GS02} —
`mn7_c02`, `key_c02`, `C02_REFUSED` and the `ZPI` = `ZPIZ` view rule
gone from the generators, one view bitmap (the disassembler's
two-bitmap offset path gone), `_asm_c02` and the gate's `asm_cpu` 2
branch, the 65C02 block of `_asm_m65_mode`, `@b_try16`'s 65C02 check
and `@paren_z`'s gone; `cpu_names` offers 65c02 on `CPU_65C02` only.
`asm_dasm_45gs02.json` re-recorded (only the `asm_cpu` 2 cases gone,
the rest identical).  m65-45gs02 24 595 → 24 458 B.

Step (5) done 2026-11-19: the debugger's `.if CMOS or MEGA` blocks
are `.ifdef MEGA_SUPPORT`, the C64 `asm_cpu` checks and the
`CMOS_SUPPORT` no-wrap path gone, `asm_cpu` imported on m65 only — no
build assembled them since step (4), so all three PRGs are
byte-identical (T5's tests, `TestNmosStep`, landed with step (4)).

- **P4b gate met (2026-11-19):** T1–T6 green — 5958 passed, Tier X
  168 passed on 920413 and 920421, the gating doc audits clean.  The
  builds are c64-6502, c64-6510 and m65-45gs02 ({6502, 4510, 45GS02});
  the CMOS mode {6502, 65C02} lives in its bundles and its golden file.
  Sizes: c64-6510 21 153 B, c64-6502 20 808 B (both hashes
  re-recorded, deliberate), m65-45gs02 24 458 B; c64-65c02 left
  `BUDGET`.  Code commits 7b8eefd, f51fbe3, 4d3bf53 and the close.
  Found on the way: the Makefile had no guard against an unknown C64
  `CPU` (`CPU=6503` built a broken PRG), now refused; the doc audits
  read the cmos debug build (now the 6510's).

- **P4b review (2026-11-20, operator: "The entire assembly and
  disassembly chain needs a full review after the cmos surgery"):**
  four reviewers (generators, assembler, dasm / REPL / debugger, docs
  and tests), each finding checked against the live code.  The
  generator now writes `cpu_set.inc` — the mode index, the `asm_cpu`
  values and per set `INSN_MAX`, `SET_EXT`, `HAS_ZONE_C` / `HAS_ZONE_D`
  — so asm_line.s, addr_mode.s, dasm.s, repl.s and debugger.s share
  one source for what four of them typed by hand (`MODE_*`, `DOT_MAX`
  / `DASM_INSN_MAX`, `cpx #4`), and derive their `.ifdef`s from the
  set instead of from `USE_MN6` / `CMOS_SUPPORT` / `MEGA_SUPPORT`
  by hand (`BIT_OPS` became `HAS_ZONE_D`).  Stripped: the CMOS and m65
  gates into one body (the Q-name lines MEGA-only); c64-6502's zone C
  and c64-6510's D / E dispatch entries and bodies; the C64 ZPREL
  parse (no C64 set has the form); the dead `asm_slot` store (a
  write-only ZP cell since before m65) and `_dasm_opc` (a copy of
  `_dasm_in[0]`), both cells held unallocated; the disassembler's
  `dasm_cpu_bm` table (one subset view per set: the generated
  `DASM_SUBSET_CPU` names it) and two m65 branch-range forks that no
  longer needed the range; the debugger's three hand-written
  `brk_pc + n` adds and a copy of `@jmp_abs`.  Generators: the
  C64-platform ladder (`PLATFORM_VIEWS`, `EXT_VIEW`, `key_category`)
  and a duplicate Entry construction replaced by one `_entry`, the
  multi-bitmap generality gone — every table byte-identical.  Stale
  comments and docs (114 mnemonics, 65C02 build, two bitmaps, the
  debugger's duplicated Next-PC rows) rewritten; tests derive the CPU
  sets from the generator's registry.  Deliberate C64 change (hashes
  re-recorded): c64-6510 21 153 → 21 080 B, c64-6502 20 808 →
  20 732 B; m65-45gs02 24 458 → 24 400 B.  5959 passed, Tier X 168.

**P5 — the contract closed:** the ROM versions the port is verified
on (920413, the floor, and the current one; the Open ROMs boot to C64
mode and cannot run the m65 build — [build_system.md § MEGA65 ROM](build_system.md#mega65-rom)) in Tier I; the
m65 size and cycle gates; every *stated with P<n>* resolved; the CDD
Report.

### Analysis tasks (own cycles; their results are doc deltas)

- [x] **A1. KERNAL API survey** (before P1 and P2).  For every KERNAL
  call, ROM internal and KERNAL cell the C64 build uses, the MEGA65
  jump-table replacement, its prerequisites (bank, `B`, interrupts)
  and its behaviour on the MEGA65 ROM versions in use — from the
  book's Appendix I, confirmed in xmega65 against both ROMs.  Output:
  the m65 column of every seam in
  [platform_layer.md](platform_layer.md) that still says *stated
  with P<n>*.

  **A1 record (2026-11-18) — approved 2026-11-18**, D-A1-1..5 as below.  The inventory: 14 jump-
  table calls (the same addresses on the MEGA65, under `KCALL`), 3
  ROM internals (gone on m65 since P0), 16 KERNAL cells.  The book
  documents the screen editor only through the jump table, the editor
  vectors, the ESC sequences and the VIC-IV registers, and says so:
  "Except where explicitly documented, programs are not expected to
  read or modify KERNAL variables directly" (14-13); the ROM is still
  developed.  So no KERNAL cell crosses to m65; each has a documented
  replacement, recorded in xmega65 on 920413 and 920421 by
  `dev/capture_m65_editor.py` (`m65_editor.json`; identical on both
  ROMs except as noted):

  | C64 | m65 means | Recorded |
  |---|---|---|
  | the cursor in `$D3` / `$D6` (`IO_CX`, `IO_CY`) | CSE's own two cells in its base page; `PLOT` (C = 0) tells the KERNAL | `PLOT` is relative to the editor's *window* (`ESC T` / `ESC B` / BASIC's `WINDOW`), sets C outside it; `HOME HOME` (`$13 $13` through `BSOUT`) leaves the window |
  | the line pointers (`io_sync`) | `PLOT` | — |
  | `kernal_screen_reset` (`$C6 $CE $D4 $D5 $D8`, the line links `$D9–$F1`) | `ESC O`, `HOME HOME`, `PLOT` | logical lines follow the screen's content, no table survives CSE's direct writes (a RETURN after printing past the margin skips the linked row; after the rows were rewritten in screen RAM it does not); a scrolling `BSOUT` (5464 steps) abandoned at any of 51 points spread over it recovers with `PLOT` alone (`ESC O` + `PLOT` too): the next print lands where `PLOT` put it and RETURN goes to the next row.  Quote and insert mode, left on by a program, survive `PLOT` and every later `BSOUT` (a later `ESC 8` is then printed, not obeyed); `ESC O` cancels both, as RETURN and shifted RETURN do; a second `"` ends quote mode only (each case on a fresh machine) |
  | the key count `$C6` (`IO_KBHIT`, `IO_KBD_FLUSH`), `GETIN` | `GETIN` over its three sources (the macro, the KERNAL buffer `ADDKEY` feeds, the hardware typing queue); drain = `GETIN` until 0; a peek has no KERNAL means — `ASCIIKEY` `$D610` ≠ 0 shows the hardware queue only (book F-3) | `GETIN` empty: A = 0, C = 0; `ADDKEY 'Q'` then `GETIN` → `'Q'`, then 0 |
  | the STOP row `$91` (`IO_STOP_DOWN`) | `ScanStopKey` (`$FFEA`): A = `$7F` while STOP is held, `$FF` otherwise — the C64 cell's values; no side effects (`STOP` closes channels and flushes keys) | idle: A = `$FF`, N = 1 |
  | the blink switch `$CC` | nothing: off for code started by `SYS` (book I-21); `CURSOR` exists from 920421 only | `CURSOR` (`$FF35`) is `$FF` on 920413 |
  | `CHRCOLOR` `$0286` | a colour code through `BSOUT` | `$1E` then a character: colour 5 in colour RAM |
  | the charset lock `$0291`; key repeat `$028A` | `SYSFLAGS` bit 7 (Mega + Shift lock), bit 5 (function-key macros off); repeat: the hardware typing queue's, no setting | `SYSFLAGS` at the run premise: `$00` |
  | `SCREEN`, the width and height | `SCRORG`: C = 1 in 40 columns; A / Z the window's top-left address (16 bits); X / Y the window's **right column and bottom row** — the book says width and height; the recording overrules it.  The 80 × 50 screen's bank is not in `SCRORG`: `$D060–$D063` (book Q) | 80 × 25 `$0800`, 79, 24, C = 0; 80 × 50 `$0800`, 79, 49 with `$D060–$D063` = `00 08 04 00`; 40 × 25 39, 24, C = 1; window (2,3)–(10,40): `$08A3`, 40, 10 |
  | `ST` `$90` (disk.s, P3) | `READSS` (`$FFB7`) | — |

  Also recorded: `BSOUT`, `BASIN`, `GETIN` and `STOP` are `JMP ($nnnn)`
  (vectored) in the jump table, every other entry CSE would call a
  `JMP` — the loader's gate accepts both; the base-page-0 cells the
  calls write (the userland contract's clobbered list): `BSOUT` `$EC
  $EF $F0` (a RETURN also `$C4 $C5 $DA $E0 $E1 $EA $EB`), `PLOT` `$C4
  $C5 $DA $E0 $E1 $E8 $E9 $EB $EC` (`$DA` at the read on 920413, at
  the set on 920421), `SCRORG`, `GETIN`, `ScanStopKey`, `SYSFLAGS`
  none.

  Decisions (approved; P2's delta takes them):
  - **D-A1-1** No KERNAL cell on m65: `IO_CX` / `IO_CY` become CSE's
    own base-page cells (the `BP_PENDING` placeholders made real),
    `io_sync` tells the KERNAL with `PLOT`.
  - **D-A1-2** `io_kbhit` = a one-key lookahead fed by `GETIN`, so a
    peek sees all three sources and needs no I/O register; the flush
    drains `GETIN` and empties the lookahead.  (Alternative: `$D610`,
    which misses `ADDKEY`'s keys.)
  - **D-A1-3** `kernal_screen_reset` on m65 = `ESC O` (quote and
    insert mode off — first, so what follows is obeyed, not printed),
    `HOME HOME` (a program's window does not survive a break: CSE needs
    the full screen), then `io_sync`.  No line-link repair: there is
    none to do.
  - **D-A1-4** The screen's address, width and height come from
    `SCRORG` (X + 1, Y + 1 after `HOME HOME`), its bank from `$D062`;
    `screen_mode_set` is `ESC 4 / 5 / 8` through `BSOUT`.
  - **D-A1-5** Function-key macros: open for P2 — `SYSFLAGS` bit 5 set
    while CSE reads keys, and what a program finds (the premise's
    `$00`) — README's P2 item says "off while CSE runs".
- [ ] **A2. Zero page and low memory** (after P1; changes the
  userland contract).  Answered by P0's analysis: CSE's own base page
  (`0.1F00`), base page 0 wholly the user's and the KERNAL's.  Still
  open: which cells of base page 0 and `0.0200–0.15FF` the KERNAL
  needs (a list for the user), and a private 16-bit stack (`E`
  clear) for user programs — what it costs, what it buys.  Output: a delta to
  [userland_contract.md](userland_contract.md) and
  [zp.md](modules/zp.md).
- [x] **A3. The MEGA65 cartridge standard** (before P3): the wiki
  page, the ROM's implementation (mega65-rom-public issue 62, the
  `"m65"` magic's last byte — `$34` or `$35`), the test cartridge,
  what xmega65 supports.  Output: the CRT section of
  [build_system.md](build_system.md) — a later release's delta (§ Later release: the m65 cartridge).

  **A3 record (2026-11-19).**  From the ROMs'
  code (920413 and 920421 byte-identical here; disassembled, the key
  bytes re-checked by hand), xemu's `targets/mega65/cart.c`, the
  wiki's draft ("MEGA65 Style Cartridge (Work in Progress)") and
  mega65-rom-public issue 62 (public, closed 2023-12-03):

  | Question | Answer | Source |
  |---|---|---|
  | Where the check runs | the reset path, not `PHOENIX` (`$FF5C` boots the floppy): `3.FFFC` → `$FB1A` → `JMP $C800` (2.C800, the interface ROM): standard C65 map, IOINIT, `JSR $C85E` | ROM code |
  | The signature | through a 28-bit pointer at `$400.8006`: flags bit 0 set (auto-start), then `$4D $36 $35` at `$400.8007–9` — "M65" in upper case; the last byte is `$35` (the wiki's prose and an issue comment say `$34`; its code sample and the ROM say `$35`) | ROM code |
  | The cold start | one F018B DMA copy of **8 K** (`$2000`) from `$400.8000` to `0.8000`; `MAP` with A = X = Y = 0, `Z = $83` (only `$E000–$FFFF` → `3.E000`, the KERNAL; BASIC not mapped); `JMP $8000` — a JMP *instruction* at `$8000`, not a vector | ROM code |
  | The state at `$8000` | A = X = 0, **Z = `$83`**, B = 0, E = 1, SP `$01FF`, interrupts on; RESTOR, CINT and the DOS initialised, BASIC not; `$D030` = `$64` (IOINIT's, inferred) | ROM code |
  | The warm start | RUN/STOP + RESTORE: the KERNAL's NMI path re-inits, `JMP ($1100)` → `2.C892`, which re-copies the 8 K and does `JMP $8003` (a second JMP instruction) — while the program leaves `$0318` and `$1100` alone | ROM code |
  | Hardware visibility | the port decodes /ROML for `$8000–$9FFF` and /ROMH for `$A000–$BFFF` and `$E000–$FFFF` (mirrored): a cartridge without banking shows 8 K + 8 K; `$400.C000–$400.DFFF` reaches neither | mega65-core `expansion_port_controller.vhdl` |
  | xmega65 `-cart` | a `.CRT` with `"MEGA65 CARTRIDGE"` (and only that: C64 CRTs are refused) — header assumed `$40` bytes, of each CHIP packet only the load address and size used — or a raw binary whose bytes 7–9 are `"M65"`, at `$8000`, up to 32 K; seen flat at `$400.0000–$400.FFFF`, no banking, no EXROM / GAME; auto-start by the ROM's own check | xemu `cart.c`, `memory_mapper.c` |
  | The `.CRT` container | VICE's layout (big-endian; signature, header length `$40`, version, hardware type, EXROM, GAME, name; CHIP packets: length, type, bank, load address, size) with the signature `"MEGA65 CARTRIDGE"`; proposed types 0 generic, 1 EasyFlash, 2 GMod2 — a draft its author calls unverified | wiki, issue 62 |

  Found for CSE: (1) the ROM copies **8 K**, not the 32 K the draft
  plan assumed: the bootstrap at `$8000` must fetch the rest itself,
  from `$400.A000` up; (2) on real hardware an unbanked 32 K image
  shows only 16 K (8 K ROML + 8 K ROMH) — the full 32 K is xmega65's
  flat view, so a 32 K cartridge for hardware needs a banked type;
  (3) **`Q` from a cartridge start restarts CSE**: the Hypervisor
  reset runs the reset path, which finds the cartridge again; (4)
  `Z = $83` at entry — CSE's code is clean 6502 but its far
  accesses and `(zp),z` macros assume what `PHY · PLZ` sets, so the
  bootstrap needs no `ldz #0` beyond that, while RESTORE re-entering
  at `$8003` is a path CSE's own NMI vector replaces (it installs
  `INMI`).  These are the later release's decisions (§ Later
  release: the m65 cartridge); build_system.md's CRT paragraph now
  states the first release has none, with these facts.

### Open design items (settled by a milestone's analysis)

- ~~**P-Q3.** The `"m65"` magic's last byte (A3).~~  Settled by A3:
  `$35` — the magic is `$4D $36 $35`, "M65".
- **P-Q5.** Whether the source region's base is only a build constant
  or also a run-time setting (the far pointers allow both).

**Settled 2026-11-18:** P-Q1 (the source region: `2.4000–2.BFFF`,
32 K), P-Q2 (after `Q`: banks 0, 4, 5 kept, bank 1 cleared, the
source text gone), P-Q4 (CSE has its own base page; base page 0 is the
user's).

### Stretch goal — CSE on the Open ROMs

Operator, 2026-11-18: supporting CSE on the Open ROMs on both
platforms is a stretch goal.  Both images are mirrored and pinned
([rom/README.md](../rom/README.md)): the C64 (generic) build as
`rom/*_mega.bin`, the MEGA65 build as `rom/mega65_open.rom` — the
project's only MEGA65 image, starting in its legacy (C64) mode, its
own native mode (`GO 65`) running on the same C64-style KERNAL with
no C65 jump table besides `PRIMM`.  Neither is a supported target
today ([memory_design.md § Target Compatibility](memory_design.md#target-compatibility)).

- [ ] **OR1. The C64 builds on the Open ROMs' C64 build.**  Which of
  the KERNAL internals and cells the C64 builds use
  ([platform_layer.md § Constants](platform_layer.md#constants), the
  c64 column) the Open ROMs provide with the same meaning; the gaps become a ROM variant of
  the c64 column in [platform_layer.md](platform_layer.md) (a define
  beside `PLATFORM_C64`, not a fork).  Tier I: C64Emu on
  `kernal_mega.bin` runs the platform-neutral suites.
- [ ] **OR2. The m65 build on the Open ROMs' MEGA65 build.**  Its
  native mode lacks `VECTOR`, `SETBNK`, `SCRORG`, `JSRFAR`,
  `VERSIONQ`, the `SYS` map and BASIC 65's banks; what the m65 seams
  would need there (a ROM variant of the m65 column: the C64-style
  vectors, the C64-style screen editor at 80 columns, its own bank
  layout) is the analysis.  The layer is shaped for it: a ROM variant
  is one more column of bodies under `.ifdef`, never a second copy.
- Both stay outside every milestone's gate; neither may cost a byte
  in the supported builds.

### Done (S2-3, the harness)

- [x] S2-3. M65Emu, the m65 integration harness
  ([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)).
  - [x] S2-3a. `MPU45GS02`: the whole 45GS02 — all 256 4510 opcodes,
    the Q and flat prefixes, `Z`, `B`, the 16-bit stack, the `MAP`
    latch; decoder from the compendium fixture; clean mode.  Golden
    file `m65_cpu.json` recorded in xmega65 by
    `dev/capture_m65_golden.py`; `test_mpu45gs02.py`.  Done
    2026-11-17: 518 recorded cases replay; the recording overruled
    the reading on BCD (NMOS-style) and `BIT #` (sets `N`/`V`).  The
    xmega65 driver is `tests/xmega65.py`.
  - [x] S2-3b. `M65Memory`: the 28-bit store, the `MAP` / `$01` /
    `$D030` / `$D02F` page table (16 × 4 KB), the CPU port, ROM
    protection, colour RAM and its window, flat access;
    `test_m65memory.py` against `m65_mem.json`
    (`dev/capture_m65_mem.py`).  Done 2026-11-17: all 29 recorded
    states replay; a latched `$D030` keeps banking in VIC-II mode;
    the base colour window is 4-bit in VIC-II mode, the extended one
    never; I/O registers are the same in every I/O mode.
  - [x] S2-3c. The post-boot state (`dev/capture_m65_state.py` →
    `build/m65_state/`, captured by hand; holds the ROM, never
    committed) with a reference run; `tests/emu_base.py` shared by
    `C64Emu` and `M65Emu`; the first Tier I test calls `CHROUT` on
    the real MEGA65 KERNAL and matches xmega65.  Done 2026-11-17.
  - [x] S2-3d. Devices as the KERNAL needs them: the DMA controller
    (`m65_dma.json`, a scroll reference run), the keyboard queue and
    `inject_keys()`, the CIA1 matrix port.  Done 2026-11-17.
  - [x] S2-3e. Feature parity with `C64Emu`: the interrupt scheduler
    and jiffy tick, the keyboard matrix with STOP and RESTORE,
    `inject_key()`, `load_prg()` with relocation, `set_cursor()`,
    `init_cse()` in `EmuBase`; the `$D019` and `$DD0D` latches
    (`m65_latches.json`).  Done 2026-11-17: the MEGA65 KERNAL keeps
    no jiffy counter (`RDTIM` reads the CIA1 TOD) and does its frame
    work only when `$D019` bit 7 is set; `test_emu_parity.py` runs
    the shared contracts on both harnesses.
  - Still to check in xmega65 (P0): that the KERNAL's IRQ frame work
    runs on a latched raster bit, the jiffy tick's stand-in for a
    frame.

**Superseded:** the earlier S2-1/2/4/5/6/7/8 items and S2-Q1–Q6 are
folded into the milestones and rulings above.

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

- [ ] **Filing dedup** (A-R7, [CDD Log R7](cdd_log.md)).  Before
  filing a Quality Sweep finding, search the open findings for the
  same defect: one item per defect, with cross-references.  Home:
  README.md § CDD Quality Sweep, Discipline.

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

- [ ] **The doc side of the pending count** (P1 Step 5, 2026-11-18).
  The pending-body count (`test_platform_audit.py`) counts
  `PLAT_PENDING` sites in the code only; a seam whose m65 body is
  shared code but whose doc still says *stated with P<n>* escapes it.
  P1 closed with two such markers left (main.md `hw_reinit_body`,
  `refresh_body`), found by Step 5's grep, not by a gate.  Proposal:
  the audit also counts *stated with P<n>* in `doc/`, recorded per
  milestone beside the code count, zero when the milestone closes.
- [ ] **Machine facts are cited or recorded before they enter a
  delta** (P1, 2026-11-18).  Two P1 claims entered the delta
  unverified: "the 45GS02 cannot read `MAP`, so the map is lost at a
  break" (from memory; the book's `hyppo_get_mapping` answers it —
  the operator caught it at Step 2), and "a flat access to `0`/`1`
  reaches the CPU port" (from the xemu source; T1's recording
  overruled it).  Proposal: platform_layer.md § Platform references
  gains the rule that a Step-1 delta names, for each new machine
  fact, its book page or the recording that will confirm it; Step 2
  checks the list.

#### C2. Corpus-coverage gaps (CDD Maintenance 2026-04-25)

*Tracked further down under § Planned / Corpus.  The items
there are mechanical fixes; this header just acknowledges they
belong in the same taxonomy.*

#### C3. Parallel fix tracks (CDD Log R7, 2026-11-18)

- [ ] Cut every fix worktree from the integration branch; re-measure
  `BUDGET` once at the merge, in its own commit; after the merge run
  the ownership audit (a modify/delete conflict can resurrect a
  deleted file) and the full suite before ticking.  Home:
  build_system.md § size gate and testing.md.

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
- [x] **Edits past `$FFFF` wrap into the live CPU port.**  `m`, `.`
  and assembly wrap `(zp),y` / `asm_out` to `$0000`/`$0001` — not the
  user-ZP image — e.g. `m fffc 00 00 00 00 2f 30` banks out KERNAL and
  I/O and crashes; `ffff:. 4c 2f 30` sets `$01` to `$32`; CSE's own ZP
  `$02`–`$07` is overwritten.  The user-ZP redirect applies only when
  the base's high byte is 0.
  REPL side fixed 2026-11-18: `zp_poke` (`m` edit, `.` hex poke) computes the
  16-bit effective address, so a run wrapping past `$FFFF` lands in
  `userland_zp_buf`, test `TestEditWrapPastFFFF`.  Assembler side fixed
  2026-11-18 (30e963f on the assembler track): output past `$FFFF` is
  refused.  Open: the `m`/`.` display of a wrapping run still reads live
  ZP (`zp_stage_prep` stages only page-0 bases).
  Fixed 2026-11-18: `zp_stage_prep` stages page-$FF bases with the 16-bit effective address, and `emit_dot` hands `dasm_insn_pre` the real PC (staged branch targets were relative to `zp_stage_buf`), tests `TestEditWrapPastFFFF::test_wrapped_display_reads_user_zp` / `test_staged_branch_target_is_the_real_pc`.
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
- [x] **Chained steps skip the `;!range` gate**: `t N` / `o N`
  (N > 1) range-checks only the first step (`cmd_step`); the
  handler's step chain arms every later step BRK unchecked, so a
  chained step can patch `$00` into I/O, ROM-shadow or CSE memory.
  Fixed 2026-11-18: the gate is `repl.s::step_targets_check`, called
  by `cmd_step` and by main.s's `@chain`; a refused chained step
  stops the chain at the instruction that would have run
  (`step_state` bit 7 → `post_run_cleanup` prints `;!range` with the panel),
  session kept, test `TestChainedStepRange`.

### Code bugs — assembler

- [x] **A lone `:` hangs `a`** (`:`, ` : nop`, `x: : nop`): a
  zero-length label re-scans the same word forever (`asm_src.s`
  `@adv_lbl`).
  Fixed 2026-11-18: a ':' with no name is `;?N: exp id` (shared
  _exp_name_err tail), test test_errors[lone colon*].
- [x] **Symbol-heap overflow corrupts KDATA.**  `heap_copy_name`
  advances `_st_heap` before its bound check and never rolls back;
  enough long labels overwrite `$F100`+ (KDATA) and the REPL screen
  save — the assembler and disassembler stay broken until reload
  (`NOP` disassembles as `VBX`).  symtab.md claims the check prevents
  it.
  Fixed 2026-11-18: heap_copy_name measures the name and refuses it
  before writing; _st_heap never passes $EF00. Test TestHeapOverflow
  (test_symtab.py, replaces the vocal skip).
- [x] **Long labels overrun BSS.**  A global label of ≥ 24 characters
  followed by a local overruns `_scope_name` / `_full_label` /
  `_expr_buf` (no bounds), corrupting `_seg_pc`, `_min_pc`,
  `_max_pc`, `kernel_zp_buf`, `userland_zp_buf`.  No label-length
  limit is documented.
  Fixed 2026-11-18: labels are at most 23 characters (local: after the
  dot) and the expanded instruction text at most 57, else `;?N: too
  long` (assembler_syntax.md § Labels); the operand is expanded
  straight into a bounded _insn_buf (_expr_buf gone). Test
  TestLabelLength.
- [x] **Expression nesting has no depth limit**: ~30 `(` wrap the
  hardware stack (`expr.s` parse_factor recursion).
  Fixed 2026-11-18: at most 10 nested levels (each `(` or unary
  prefix); the 11th returns 3 (overflow) — parse_factor counts its
  entries; errors under unary -/! now propagate. Test TestNestingDepth
  (test_expr.py).
- [x] **Pass-0 forward references with an offset size to 0 bytes.**
  `lda tbl+1` (also `jsr fwd+3`, `bne fwd+2`, `sta fwd+1,x`)
  substitutes `asm_pc + 2` but leaves `expr_ptr` after the name, so
  the operand is a syntax error on pass 0 (silent there) and later
  labels shift: `.org $c000 / lda tbl+1 / jmp end / end: rts /
  tbl: .db 1,2` → `ad 05 c0 4c 03 c0`, 0 errors.
  Fixed 2026-11-18: an undefined symbol reads as 0 (wide), sets
  expr_fwd and the parse continues to the end of the expression (rc 5
  unless a hard error follows), so pass 0 sizes `tbl+1` like pass 1.
  Tests TestUndefinedParsesOn (test_expr.py), test_assemble[forward
  ref with offset*] (test_asm_src.py).
- [x] **Pass-0/pass-1 width mismatch for later-defined ZP constants.**
  `lda zp` with `.const zp $10` after it is sized ABS on pass 0 and ZP
  on pass 1; following labels are one byte off (`jmp` into its own
  operand), 0 errors.  Pass 0 also writes bytes.
  Fixed 2026-11-18: the pass stamp now runs on every build: labels and
  .const are defined on both passes, a pass-1 read of a symbol still
  stamped by pass 0 is forward and sized ABS (as pass 0 did); a .const
  reading a later symbol is `fwd ref`; pass 0 writes nothing (emission
  commit). Tests test_assemble[later-defined ZP constant*],
  TestPassStamp (test_symtab.py), TestPassZeroWritesNothing.
- [x] **Code before the first `.org`** gets labels from the pass-0
  layout (default origin) while pass 1 emits at the first `.org`
  (`_set_first_org` overwrites `asm_org`; every pass starts at it).
  Fixed 2026-11-18: every pass starts at the default origin
  (_def_org); asm_org is the first .org only when nothing was emitted
  before it. Test TestCodeBeforeFirstOrg.
- [x] **Emitting past `$FFFF` wraps into `$0000`/`$0001`** (the CPU
  port) — no wrap check in `_asm_emit` / `_emit_byte`.
  Fixed 2026-11-18: asm_src assembles each instruction into a scratch
  buffer and emits every byte through _emit_byte, which drops bytes
  once asm_pc wrapped (`;?N: range`, once per line); asm_line parks
  bytes after a wrap in _asm_sink and refuses (`;?expr ovfl`). Tests
  TestNoWrapPastFFFF, TestAsmLineNoWrap (test_asm_src.py).
- [x] **A full symbol table is silent**: 300 labels → 0 errors, 44
  dropped; `sym full` is reported only on pass 0, where `emit_error`
  is silent.
  Fixed 2026-11-18: labels and .const are defined on pass 1 too (pass-
  stamp commit), so a symbol that does not fit is `;?N: sym full`
  where errors are vocal; contract in assembler_syntax.md § Labels.
  Test TestSymbolTableFull.
- [x] **Directives read past their NUL**: `.o…` matches `.org` on the
  first letter (`.oops` = `.org`), `.co`/`.cp` likewise; `.const k`
  with no value reads stale `_line_buf` bytes.
  Fixed 2026-11-18: process_directive matches the whole word against a
  name table (ending at whitespace, ';' or NUL), unknown words are
  `bad insn`; `.const k` without a value is `bad val`
  (assembler_syntax.md § Directives). Tests test_errors[directive *,
  .const without a value].
- [x] **`.cpu` in source changes `asm_cpu` for pass 1 from the start**
  (lines before the directive) and leaks into the REPL afterwards; not
  restored by `asm_assemble`.
  Fixed 2026-11-18: asm_assemble saves the caller's asm_cpu, starts
  every pass with it and restores it at the end (assembler_syntax.md §
  .cpu). Test TestCpuDirectiveScope.
- [x] **REPL `.` with a symbol operand reads tables from ROM.**
  `sym_lookup`'s `kernal_bank_in` really banks in inside `asm_line`
  (non-nesting helpers), so `.asl $12,zz` emits `A2 12 02`, 0 errors.
  Fixed 2026-11-18: sym_define/sym_lookup save $01 on entry and
  restore it on every exit (never bank_in), so asm_line's bank-out
  survives a symbol lookup; mem.s unchanged. Tests TestBankGuardNests
  (test_symtab.py), TestReplDotAfterSymbol (test_asm_src.py).
- [x] **Non-letters reach the mnemonic hash**: 906 false positives on
  mn7 builds (`ld8` → DEX, `xb` → BCC, `fo0` → NOP), 884 on mn6;
  `_asm_rd_upper` passes bytes below `$41`, and the tables are indexed
  out of range.  An empty line assembles to BRK on mn7 builds.
  Fixed 2026-11-18: _asm_rd_upper accepts letters only ($41-$5A,
  $61-$7A, $C1-$DA; AND #$5F) and refuses anything else with ;?syntax
  before mn_classify, so an empty line no longer assembles to BRK.
  Test TestNonLetterKeys (test_asm_line.py).
- [x] **Implied instructions ignore their operand**: `rts garbage`,
  `nop $1234`, `inxy` assemble silently (zone A has no end check;
  asm_line.md says a fifth character is `;?syntax`).
  Fixed 2026-11-18: zone A requires an empty operand (end, ';' or
  '//'), and the character after the three-letter key must be
  whitespace, end or ';' (asm_line.md § Mnemonic word, § Zone
  dispatch). Test TestImpliedAndWordEnd (test_asm_line.py).
- [x] **A narrow branch operand is emitted as a raw offset**:
  `BNE $10` → `D0 10` (asm_line.md: the operand is the target).
  Fixed 2026-11-18: zone B treats a narrow operand as a zero-page
  target like a wide one (-4 B). Test TestNarrowBranchTarget
  (test_asm_line.py).
- [x] **`expr` loses the wide flag after a nested `<`/`>`**:
  `$0000+(<$12+1)` returns narrow (the saved flag is not stacked).
  Fixed 2026-11-18: each binary operator pushes its left operand's
  width with the operand (expr.md § Width propagation); _ex_wide_tmp
  is unused. Test test_positive[wide left, *] (test_expr.py).
- [x] **Immediate values > 255 are truncated silently**
  (`lda #$1234` → `A9 34`).
  Fixed 2026-11-18: an IMM operand must fit a byte ($00-$FF or
  -128..-1), else expression overflow (asm_line.md § Immediate range);
  _asm_imm_chk in zones C and G/H. Tests TestImmediateRange
  (test_asm_line.py), test_errors[immediate *] (test_asm_src.py).
- [x] **`//` comments are parsed as division** (`lda #1 // c` → expr
  error), though addr_mode.md lists `//` as end-of-expression.
  Fixed 2026-11-18: parse_mul treats '/' followed by '/' as the end of
  the expression, not a divide (expr.md § Partial-mode contract).
  Tests test_stop_position[// is a comment*] (test_expr.py),
  test_double_slash_comment (test_asm_line.py).
- [x] **Shift counts ignore their high byte**: `1<<256` = 1,
  `$8000>>256` = `$8000`.
  Fixed 2026-11-18: the shift count is the full 16-bit operand; 16 or
  more gives 0 (expr.md § Caveats). Tests test_positive[shl/shr by *]
  (test_expr.py).
- [x] Latent: `mode_parse`'s accumulator test assumes `A` at offset 0
  (`ldy #1`) and has no CR/LF in its peek; production strips leading
  whitespace first.
  Fixed 2026-11-18: the ACC peek commits the leading whitespace first
  (_au_commit) and tests the following char with _au_is_end (NUL, CR,
  LF, ';', '//') plus whitespace and '#' (addr_mode.md § ACC vs
  label). Tests test_parse_ok[ A, A\\r, ...], test_stop_position[ACC
  after leading ws].

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
- [x] **Mutable bytes in CODE**: `main.s` `@key`, `dasm.s` `@adj`,
  `disk.s` `disk_save_prg`'s `@size_lo`/`@size_hi`
  (blocks a ROM/CRT build; memory_design.md "no self-modifying code").
  `dasm.s` `@adj` fixed 2026-11-18: _compute_branch_target folds the
  adjustment into its arithmetic, test TestCodeIsReadOnly (test_dasm.py).
  `main.s` `@key` fixed 2026-11-18: now `main_key` in BSS, test
  `TestMainCodeReadOnly`.  Open: `disk.s` `disk_save_prg`'s size bytes.
  `disk.s` fixed 2026-11-18: `disk_save_prg`'s size bytes and the other 15 proc-local bytes in disk.s's CODE (`str_setup`, `build_open_str`, `list_directory`) moved to BSS (-17 B), test `test_save_prg_payload_leaves_code_read_only` (test_disk.py; OPEN / CHKOUT / CHROUT redirected through the KERNAL vectors).
- [x] `disk.s` closes LFN 1 on an OPEN failure although the file is
  LFN 2; the SEQ error paths close nothing.
  Fixed 2026-11-18: `_disk_open_buf` closes LFN 2 when OPEN fails (dead `@err_close` removed); C64Emu models an empty serial bus, test test_disk.py.
- [x] Dead code and imports: `kernel_stack_budget` (exported, unused;
  repl.s duplicates it as `KSTK_MIN`), `str_end_dbg`, `str_no_name`,
  `io_color` (written, never read), `mn_vars.s` (empty shell); dead
  imports in `asm_src.s` (`buf_base`, `dec_pow_lo/hi`), `symtab.s`
  (`kernal_out`), `editor.s` (seven), `disk.s` (`io_color`, `io_puts`,
  `io_puthex2/4`), `repl.s` (`oplen_tbl`), `asm_src_test_stub.s`
  (`_min_pc`, `_max_pc`); `test_asm_src.py`'s dead `xfail` path.
  Fixed 2026-11-18: `kernel_stack_budget` defined once in repl.s; `str_no_name` and `io_color` deleted; `mn_vars.s` retired; the listed imports and a further sweep (asm_line, expr `err_*`, main, test stubs) dropped; `asm_src.s` `buf_base` is in use (workspace range check), kept.  `_ex_wide_tmp` / `asm_bit` ZP holes left to the parallel track that freed them.  Checked by the full suite (no behaviour change).
- [x] `ed_insert_string` has no production caller and ignores
  `gb_insert`'s carry — keep as a test-only export (documented) or
  retire.
  Fixed 2026-11-18: kept as a documented test-only export (gap_buffer.md: ignores the carry, drops the rest on a full buffer), test TestEdInsertStringFull.
- [x] `dbg_reason` enum defined twice (`main.s`, `repl.s`).
  Fixed 2026-11-18: the enum lives in `src/dbg_reason.inc` (owner
  debugger.md), included by main.s and repl.s, test
  `TestDbgReasonSingleDefinition`.

### Code bugs — found by the live example run (2026-11-18)

- [x] **`.const` with a symbol in its expression defines nothing**:
  `.const vic $d000 / .const border vic + $20 / sta border` →
  `;?…: undef` (expr's label lookup overwrites `sym_name`, which the
  `.const` handler still holds).  assembler_syntax.md's own example.
  Fixed 2026-11-18 (ac1f426 on the assembler track: the .const name is kept across expr_eval).
- [x] **The `;!a shadow` warning crashes `a`**: printed while the
  KERNAL is banked out, `newline` → `io_sync` calls into the KERNAL
  area (CSE data there) → BRK → `cse_recover`.
  Fixed 2026-11-18 (e1211d7 on the assembler track: the warning banks the KERNAL in).
- [x] **CLR/HOME or ESC at a breakpoint, then `c`, hangs**:
  `cse_refresh` resets SP to `kernel_init_sp`, and kernel `jsr`s
  overwrite the user's `brk_stub` sentinel at `$01FE/$01FF`; README
  promises the debug context is preserved.
  Fixed 2026-11-18 (runtime track): `cse_refresh` resets SP to `reg_sp`
  in a live session, test in test_kernel_transition.py.
- [x] **Dotted global labels**: `jmp main.loop` is `undef`; a global
  label with an embedded dot is defined but cannot be referenced (the
  operand expansion prefixes the scope at every `.`); `a_b:` is
  accepted though `_` is not a label character, and the reference
  fails.  Settle the label grammar (assembler_syntax.md) and enforce it.
  Fixed 2026-11-18 (737b1ab on the assembler track: label grammar settled in assembler_syntax.md and enforced).
- [x] **`.db` values > 255 truncate silently** (`.db 256` → `$00`);
  **`.const 5 5`** defines a symbol named `5` (no `exp id`).
  Fixed 2026-11-18 (841c27c on the assembler track: `.db` byte range and `.const` name checks).
- [x] **The assembler writes outside the workspace**: `.org $c000`
  assembles over CSE's own code with no error (the breakpoint range
  gate already refuses such addresses); add the same guard to emit.
  Fixed 2026-11-18 (ad3b42c on the assembler track: emit outside $0800..buf_base is `;?N: range`).
- [x] **`scroll_up` uses `$FB–$FE`** — the C64's free user ZP —
  although userland_contract.md promises CSE never writes `$80–$FF`
  beyond the listed KERNAL cells; use CSE's own ZP.
  Fixed 2026-11-18 (d01cc76 on the track branch): `scr_src` at `$78–$79`,
  destination reuses `_io_scr`; user-free ZP is now `$7A–$7F`.

### Code bugs — found by the doc-drift round (2026-11-18)

- [x] **`?` shows a 16-bit value whose low byte is 0 in the 8-bit
  form**: `? $1000` prints `;   $00   4096` (`@calc_16bit` falls back
  to the 8-bit form when the low byte is 0).
  Fixed 2026-11-18: the low-byte fallback is gone, a value ≥ 256 always shows `$xxxx` (−10 B, budget lowered), test test_calc_hex_form_follows_the_value.
- [x] **`t nosuchsym` / `o nosuchsym` step anyway** after `;?expr
  undef` (or do a cold preview) — the shape of the fixed `j` bug:
  `cmd_step` treats an error as an empty argument.
  Fixed 2026-11-18: `cmd_step` returns on try_expr's Z=0 (error) before the gate, as `j` does (+2 B), test test_bad_step_count_neither_steps_nor_previews.
- [x] **`b nosuch` prints `;?expr undef` and then an extra `;?syntax`.**
  Fixed 2026-11-18: `cmd_brk` returns on try_expr's Z=0; only the empty case is `;?syntax` (±0 B), test test_bad_expr_is_one_error_row.
- [x] **`;!N: truncated` fires for a line of exactly 39 characters**,
  which is not truncated.
  Fixed 2026-11-18: `ed_read_line` returns X ≠ 0 when it dropped characters past the 39th and `do_pass` warns on that flag, not on length 39 (−17 B, budget lowered; README corrected to "more than 39"), tests test_dropped_characters_set_x, test_warns_only_when_characters_were_dropped.
- [x] **Steps chained inside the handler (`t N`, N > 1) skip the
  `;!range` gate** — only the first step is range-checked, so a chained
  step can patch `$00` into I/O or ROM-shadow memory.
  Fixed 2026-11-18 (b5d31eb; the same item, filed again under § Code bugs "Chained steps skip the `;!range` gate"), test TestChainedStepRange.
- [x] **`warn_long_lines` keeps mutable bytes in CODE** (`@vcol`,
  `@line`, `@tw`) — the same class as "Mutable bytes in CODE".
  Fixed 2026-11-18: the counters are `wl_vcol` / `wl_line` in BSS and the tab step is `(vcol | TAB_MASK) + 1`, so `@tw` is gone (−14 B, budget lowered), test TestWarnLongLines::test_counts_in_bss_and_warns.
- [x] **A clean `make release debug` fails** with "No rule to make
  target …/src/loader.o" (the `.d` dependency bootstrap); a second run
  succeeds.
  Fixed 2026-11-18: not the `.d` files — the objects' order-only directory prerequisite `$(BUILD)/src/` had a trailing slash, which make 3.81 stops matching once the first object created the directory; now `$(BUILD)/src`, test test_fresh_worktree_builds_in_one_make.

### Code bugs — found by the editor/disk doc group (2026-11-18)

- [x] **`l` of a SEQ file reports every failed load as a success**:
  `ed_load_source` ends with `ldx #0` (Z=1 on every path) and
  `cmd_load` tests `beq`, so a disk error, an empty file or an
  oversize file prints the stats instead of `;?fail` / `;?too big` —
  the pattern fixed for `ed_save_source`.
  Fixed 2026-11-18 (aae55f8 on the IEC track: `ed_load_source` sets Z from A; `;?fail` / `;?too big` shown, test on the virtual drive).
- [x] **Mutable bytes in CODE, the full set**: besides `disk_save_prg`,
  editor.s has ~15 `.byte` locals, disk.s ~16, repl.s ~4
  (`warn_long_lines`' among them) — all to BSS/ZP scratch.
  Fixed 2026-11-18: disk.s (d153321), repl.s (953405d), main.s (be86231) and now editor.s's 15 locals are BSS (−15 B, budget lowered); no `.byte` scratch is left in any CODE segment, test TestCodeReadOnly::test_editing_session_leaves_code_unchanged.
- [x] **A disk write error after a successful OPEN is not detected**:
  SEQ and PRG saves report success and clear `ed_dirty`; read the
  status (ST / the command channel) after the write.
  Fixed 2026-11-18 (fa20f2e on the IEC track: every disk.s transfer reads the drive status into `fl_buf`; a refused save fails and keeps `ed_dirty`).
- [x] `ed_status_dirty` is effectively dead: `gb_insert` /
  `gb_backspace` set `ed_dirty` before `ed_mark_edited` checks it.
  Fixed 2026-11-18: not only dead — a RETURN that scrolled (ed_scroll_up redraws no status) left a clean source without its `*`. `ed_mark_edited` now always draws the marker, `ed_status_dirty` is folded into it (−17 B, budget lowered), tests TestDirtyMarker.

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
- [x] Untested contracts: `dbg_step_clear`, `dbg_init`'s outputs,
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
  Assembler-track part closed 2026-11-18: `seg_print_save`
  (test_asm_src.py::TestSegPrintSave), `info_line`
  (test_log.py::TestInfoLine), `$A0` / leading whitespace
  (test_addr_mode.py test_parse_ok / TestModeParseStopContract cases).
  Fixed 2026-11-18: the editor's remaining part runs on C64Emu's virtual 1541 — ed_save_source / ed_load_source success, code 1 on a missing or empty file, code 2 (file too large) — the explained skip is gone, tests test_editor.py::TestEdDiskOnADrive.
- [x] Bundle hygiene: `test_repl_disk.py` still builds its own
  bare-MPU binary with stubbed disk calls and a map regex (Tranche 4);
  behavioural stubs in `asm_core_test_stub.s` (`log_warn`) and
  `asm_src_test_stub.s` (log, cse_io, editor, gap_buffer routines)
  are outside the mock policy; the mem, log, gap_buffer, symtab,
  breakpoints and cse_io bundles are hand-rolled, not `Bundle`;
  `cse_release_prg` is unused.
  Done 2026-11-18 except Tranche 4: the six bundles are `conftest.Bundle` with `PROD_DEFS` and `-t c64`; the stubs' mocks are recorded in testing.md § Shared slim mocks; `cse_release_prg` feeds test_release_smoke.py.  Open: `test_repl_disk.py` — blocked on a virtual IEC disk (C64Emu models only an empty serial bus).
  Fixed 2026-11-18: C64Emu has a virtual 1541 (attach_drive); test_repl_disk.py runs on it with the production PRG, dev/repl_test_stub.s and dev/repl_test.cfg are deleted, tests test_repl_disk.py (TestSaveCommand, TestLoadCommand, TestDirDevice).

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

- [x] Facts restated in many docs, several already contradicting each
  other: the ZP allocation table, the KERNAL-RAM banked layout, the
  interrupt vectors, the stack contract, the cold-init sequence, the
  user memory regions, the cross-module flags, the `dbg_reason` enum,
  the breakpoint table, warmstart bodies, the runtime start address.
  Keep one owner each; the copies become pointers.
  Fixed 2026-11-18 by the doc-drift round: each fact has one owner (zp.md 108f742, memory_design.md eac9ca1, main.md 5704c74, debugger.md df2fe92, breakpoints.md 0136ba8, userland_contract.md 74a2dd5, build_system.md 72d5863); project.md (afec8cc), glossary.md (f35cc50) and the module docs link to them.
- [x] memory_design.md restates module interfaces (mem.s exports,
  loader steps, warmstart bodies, `return_to_userland` and the BRK
  handler) — move to the module docs, keep the invariants.
  Fixed 2026-11-18 (eac9ca1): memory_design.md keeps the maps, banked layout and invariants and links mem.md, loader.md, main.md and debugger.md for the mechanisms.
- [x] The user manual carries mechanism (gap buffer, internal names,
  runtime start) and lacks a REPL-keys table; project.md and the
  glossary restate addresses and sizes.
  Fixed 2026-11-18: README.md speaks of the workspace and has a REPL-keys table (c76280c, bd2825c); project.md (afec8cc) and glossary.md (f35cc50) link instead of restating addresses.
- [x] Missing guidance for agents: the REPL command-dispatch table
  and handler entry contract (`rp_ptr`, `try_expr`'s C=0 meaning, the
  one-jsr-deep rule, the repeat list); the asm_src directive switch
  and its helper contracts (`_emit_byte`, `emit_error`,
  `_bad_val_err`, `_vocal_fwd_err`); the asm_src test input format;
  the size gate's growth procedure.
  Fixed 2026-11-18: repl.md § dispatch table, handler entry, `try_expr`, one-jsr-deep rule and repeat list (bc55a57); asm_src.md § helper specs and directive recognition (eb8495d); testing.md the asm_src case format (cf1985a); build_system.md the size gate's growth procedure (72d5863).
- [x] Audit tooling: `audit_doc_depends_on.py` checks only doc →
  import (add import → doc); `dev/check_deps.py` (architecture.md
  cites it) does not exist.
  Fixed 2026-11-18: `audit_doc_depends_on.py` check (c) names every imported-from module in the Depends-on block; `dev/check_deps.py` parses the layers from architecture.md § Modules and refuses upward imports; both run in `dev/audit_doc.py`, test `test_check_deps.py`.

## Bugs

Open bugs, roughly ordered by priority.

- [ ] **`io_puthex2` writes past the last column.**  It stores its two
  digits at Y and Y + 1 with no bound, so a hex pair started in the
  last column puts its second digit into the next row's first cell
  (`io_putc` clamps, `io_puthex2` does not).  Both platforms.  Found by
  P2's geometry inventory, 2026-11-19.  Own CDD cycle.
- [x] ~~**disk.s's `@putc_inv` inverts the wrong cell at the last
  column.**~~  Closed 2026-11-19 (P3, step 2) as unreachable: its only
  caller is `list_directory`'s header, a line `fl_buf` truncates to 30
  characters (`cpy #30`), after `"; "` — it ends by column 31, so the
  clamp never holds the cursor there, in 40 columns or 80.  Fixing it
  would cost every build bytes for a path that cannot run.  Reopen if
  `@putc_inv` gets a caller that can reach the last column.

- [ ] **disk.s writes `$FD`/`$FE`, which the userland contract keeps
  free.**  [userland_contract.md](userland_contract.md) § 2, § 3 and
  § 7 promise that CSE never writes the C64's free cells `$FB–$FE`;
  disk.s's private pointer is `ptr = $FD` (`str_setup` stores it),
  outside the swapped `$00–$7F`, so a disk command clobbers the
  user's `$FD`/`$FE`.  Found by the P0 quality pass, 2026-11-18.  Own
  CDD cycle: move the pointer into CSE's ZP block (zp.s; the C64 builds
  change, so not part of the byte-identical platform refactor).

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

- [x] **Migrate `tests/integration/test_repl.py` from the bare-MPU +
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
  Fixed 2026-11-18: the non-disk half had moved already; the disk half (test_repl_disk.py) now runs on C64Emu's virtual 1541, the stub and its config are deleted, tests test_repl_disk.py.

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

- [x] **Virtual IEC disk (D64-backed)** — intercept KERNAL IEC entry
  points (`$FFC0` OPEN, `$FFD5` LOAD, `$FFD8` SAVE, `$FFCF` CHRIN,
  `$FFD2` CHROUT, etc.) with a Python callback backed by a virtual
  D64 image.  Unlocks Tranche 4 (test_repl migration) + hazard tests
  (overwrite, file-not-found, device-not-present).  Moderate-to-high
  effort; timing-accuracy concerns — flagged as out-of-scope at
  extension-planning time.
  Fixed 2026-11-18: traps one level lower, on the KERNAL's serial routines (TALK…UNLSN), so OPEN/CHKIN/LOAD/SAVE stay the ROM's own; Drive1541 is an in-memory 1541 (channels, command channel, DOS status, `$`, write protect, disk full) with a .d64 reader; no timing; contract testing.md § Virtual IEC drives, tests tests/unit/test_c64emu_disk.py.

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

- [ ] `.` REPL command: accept the explicit accumulator form (`. asl a`,
  `. rol a`, `. lsr a`, `. ror a`, and on 65C02 / m65 `. inc a`,
  `. dec a`).  Today it is `;?syntax` (checked 2026-11-19: `. asl`
  assembles `$0A`, `. asl a` does not), while the source assembler
  takes both forms (asm_line.md § ACC mode handling) and the
  disassembler lists `asl a` — so RETURN on a `d` row that shows
  `asl a` fails, and README.md § REPL states that as a limit
  ("the REPL assembles the accumulator form only bare").  Cause: the
  same as the item below — `dot_assemble` pre-evaluates the operand
  through `expr_eval`, so `mode_parse`'s SC_A path never sees the bare
  `a`.  Done when `. asl a` assembles the ACC opcode on every build
  (and still reaches a defined label `a` on mnemonics without ACC, as
  `lda a` does), a `d` row with `asl a` re-executes, and the README's
  limit paragraph is deleted.  Fixing the item below by option (b)
  fixes this one too.
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
and disassembler) — is done but A3b and A5, its Phase B as slice 2's
P4: see [M65](#m65--the-45gs02-assembler-and-disassembler-r7-slice-1).
Slice 2 — the platform layer: a native MEGA65-mode program living
in the BASIC ROM banks, shipped as PRG and D81 (a MEGA65-style CRT
in a later release) — is in progress, P0–P4 done, P5 next: see
[M65 slice 2](#m65-slice-2--the-mega65-platform-r7-platform-layer).
Slice 2 does the c64/m65 leaf-function isolation R3 asks for; R3
later adds the C128 to it.

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
