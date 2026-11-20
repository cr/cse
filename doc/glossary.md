# CSE Glossary

All terms are used consistently across source code, comments, tests,
and documentation.

## User-facing

| Term | Definition |
|------|------------|
| **REPL** | Read-eval-print loop.  CSE's command-line mode.  The screen is the command buffer. |
| **editor** | Full-screen source code editor.  RUN/STOP toggles between REPL and editor. |
| **block size** | Number of bytes `m` and `d` show, the default step of `+` and `-`, and the default length of a PRG `s`.  Set by `B`. |
| **block edit** | Workflow: dump a block (`d`/`m`), cursor to a line, edit in-place, RETURN. |
| **cur_addr** | The REPL's current address.  Set by `AAAA:` prefix; advanced by commands. |
| **project name** | User-facing identifier for a source+binary pair.  Stored in `cur_project_name` as a bare stem (no type suffix, no trailing dot).  The disk filename is derived: SEQ = stem, PRG = stem + `.`.  Default `"out"` when unset. |
| **verbatim name** | A quoted filename with a `,s` or `,p` type suffix at the tail (`foo,s` / `foo,p`).  Tells `l`/`s` to use the bare name (suffix stripped) on disk with no derivation.  Lets the user bypass the project-name convention for ad-hoc files. |
| **derived name** | Disk filename computed from `cur_project_name`: SEQ = stem, PRG = stem + `.`.  Used when the user supplies a plain quoted name (no `,s`/`,p` suffix) or no quoted name at all. |

## Source language

| Term | Definition |
|------|------------|
| **instruction** | A complete assembler statement: `mnemonic [operand]`. |
| **mnemonic** | The 3-letter instruction name: `LDA`, `BBR`, `NOP`, etc. |
| **operand** | Everything after the mnemonic: encodes addressing mode and value.  Example: `($D0,X)`. |
| **addressing mode** | The syntactic form of the operand: how the CPU locates the data.  Example: "zero-page indexed X" means `$XX,X`. |
| **expression** | A numeric value: literal, symbol, label, or arithmetic combination.  Example: `BASE+$20`. |
| **literal** | A numeric constant in source: `$D020`, `255`, `%11001000`. |
| **symbol** | A named constant: `.const name expr`.  Has a **value**. |
| **label** | An address marker: `name:`.  Has a **slot** (the LC at the point of definition). |
| **local label** | Dot-prefixed label (`.loop:`), scoped to the last preceding global label.  Stored as `global.local`. |
| **directive** | Pseudo-instruction controlling assembly state, not emitting a CPU opcode: `.org`, `.db`, `.cpu`, etc. |
| **forward reference** | Use of a symbol or label before its definition.  Resolved in pass 1. |

## Assembler internals

| Term | Definition |
|------|------------|
| **LC (location counter)** | The assembler's current output address.  Set by `.org`; advanced by every emitted byte. |
| **pass 0** | First scan: define labels/constants, compute instruction sizes.  Writes no bytes; errors not counted. |
| **pass 1** | Second scan: labels/constants defined again, all symbols resolved; emit bytes, count errors. |
| **ZP** | Zero-page: address $00–$FF.  Selects 2-byte instruction encoding.  Also: the `.segment "ZEROPAGE"` allocation in the linker. |
| **ABS** | Absolute: address $0000–$FFFF.  Selects 3-byte instruction encoding. |
| **BSS** | Uninitialized runtime state segment.  Zeroed at boot by the loader.  All mutable module variables outside zero page live here. |
| **RODATA** | Read-only data segment.  Constants, string literals, lookup tables.  Linked into the runtime image alongside CODE. |
| **KDATA** | Read-only data segment that lives in the RAM under the KERNAL ROM ([memory_design.md § Banked layout](memory_design.md#banked-layout-e000ffff)).  Copied from the PRG load image by the loader at startup.  Holds lookup tables: the mnemonic classifier tables, `mn_modes`, `asm_row`/`asm_delta`, the disassembler's mnemonic strings. |
| **workspace** | The main-RAM region below the CSE runtime, shared by user programs and source text.  User output grows upward from `workstart` ($0800) to `workend`; the source text (the gap buffer) sits above `workend` and grows downward from the runtime start.  See [memory_design.md § Source Code Storage](memory_design.md#source-code-storage). |
| **gap buffer** | The editor's text storage: a contiguous buffer with a movable gap at the cursor.  Insertions fill the gap (O(1)); the gap slides on cursor movement.  `buf_base` is the buffer floor, the runtime start (`__CODE_RUN__`) the ceiling. |
| **symbol table** | Hash table in the RAM under the KERNAL ROM ([memory_design.md § Banked layout](memory_design.md#banked-layout-e000ffff)).  Stores assembler labels and constants.  Name strings live in the adjacent heap. |
| **heap** | Symbol-name storage next to the symbol table under the KERNAL ROM.  Grows upward; reset by `sym_clear`. |
| **fingerprint** | Mnemonic disambiguation byte: `fp = (c2<<3) | (c3>>2)`.  After the h7 hash selects a slot, the fingerprint confirms the exact mnemonic with zero false positives. |
| **mnemonic hash** | `h7 = (c1×4 + c3 + HASH_T[c2]) & $7F`.  Maps a 3-letter mnemonic to a 7-bit slot index (0–127).  Uses VICII-normalized letter values (A=1..Z=26). |
| **wide** | `expr_wide = 1`: expression forced to ABS.  Sticky — once wide, stays wide. |
| **base opcode** | A key's own zero-page opcode, else its absolute opcode, else its lowest mode's — always one of the key's opcodes.  Final opcode = `base ^ delta[mode]`. |
| **mode index** | Integer encoding an addressing mode — the catalogue index of `ALL_MODES` in `dev/instruction_set.py` (append-only).  0=IMP, 1=ACC, 2=IMM, 3=ZP, 4=ZPX, 5=ZPY, 6=ABS, 7=ABX, 8=ABY, 9=IND, 10=INX, 11=INY, 12=REL, 13=ZPI, 14=AIX, 15=ZPREL; on the m65 build also 16=IMM16, 17=REL16, 18=ISPY, 19=ZPIZ. |
| **operand profile** | A pair (accepted modes, delta row), indexed by `pidx` (numbered per CPU set by the generator).  The modes are a bitmask in the `mn_modes` planes; the delta row turns the base opcode into each mode's opcode.  Example: the LDA profile on the C64 = {IMM, ZP, ZPX, ABS, ABX, ABY, INX, INY}. |
| **delta row** | One byte per mode, `opcode ^ base`, shared by every profile that never disagrees with it on a mode both accept.  `asm_delta`, indexed by `asm_row[pidx] + mode`. |
| **CPU set** | The CPUs a build serves at run time (`.cpu`, `u`); its top member is the build's `CPU`.  Generated tables come in one block per CPU set.  See [build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets). |
| **opcode map** | The disassembler's generated per-opcode table: mnemonic index and mode of every opcode of the set's top CPU but the 45GS02 (the 4510's on m65, the 45GS02 being that map plus the prefix peel — [dasm.md § Design](modules/dasm.md#design)). |
| **view bitmap** | 256 bits marking which opcodes a lower CPU of the set defines as the opcode map does; the disassembler shows the others as `...` in that CPU's view. |
| **Q prefix** | `$42 $42` (NEG NEG) on the 45GS02: the following 4510 instruction operates on the 32-bit Q register (A, X, Y, Z). |
| **far prefix** | `$EA` (EOM/NOP) on the 45GS02: a following `($nn),Z` (or Q `($nn)`) instruction reads a 32-bit pointer — written `[$nn],z` / `[$nn]`. |
| **zone** | Dispatch category in the line assembler: a range of `pidx`; the first multi-mode index is the generated `ASM_ZONE_G`.  Zones A–F are fixed single-shape groups; G (extension pairs), Q (45GS02 quad groups) and H are multi-mode groups that call `mode_parse` + `asm_opcode_lookup`. |
| **mnemonic suffix** | The optional fourth character of a mnemonic word: a digit `0`–`7` after RMB/SMB/BBR/BBS (the `3` in `RMB3`, a bit index), or `q` after a quad stem on the 45GS02 (`ADCQ`). |

## Process

| Term | Definition |
|------|------------|
| **CDD System** | The totality of contract-driven practices in this repository: the CDD Method, the TDD Method, the CDD Corpus, the CDD Maintenance and TDD Maintenance processes, the CDD Quality Sweep, and Escape Analysis.  The system's goal is that documentation is always the source of truth and never drifts from code.  Tests are the executable form of the contracts; they drift the same way prose does, and get audited the same way. |
| **CDD Corpus** | The complete body of documentation that defines the system: `doc/` files, module docs in `doc/modules/`, authoritative data files in `dev/`, and the test contracts in `tests/`.  The Corpus is the source of truth for all design intent, interfaces, and behaviour. |
| **CDD Method** | The seven-step development process defined in [README.md § The CDD Method](README.md#the-cdd-method): doc first → CDD Analysis → TDD Analysis → implement → differential CDD → commit → report.  Mandatory for all repository changes, no exceptions. |
| **CDD Maintenance** | A periodic audit of the CDD Corpus independent of feature work.  See [README.md § CDD Maintenance](README.md#cdd-maintenance) for the full audit scope and trigger. |
| **TDD Maintenance** | A periodic audit of the test corpus, analogous to CDD Maintenance for prose.  Walks every exported symbol in every module doc, confirms each has a correctness test or a vocal skip, flags duplicates, implementation coupling, harness dependency-direction violations, and bundle-to-production parity gaps.  Also triggered reactively when an Escape Analysis amends a testing.md principle, to propagate that principle across the whole corpus.  See [README.md § TDD Maintenance](README.md#tdd-maintenance) for the full audit scope. |
| **CDD Quality Sweep** | The operator-invoked deep, varied-lens pass over the corpus against four quality criteria — correctness, human and agent readability, no duplications, appropriate abstraction layering — the on-demand parallel to the cadenced CDD Maintenance gate.  Each invocation runs at least two complementary lenses on an axis earlier sweeps under-covered; findings are verified against live source, doc defects fixed, code and test defects filed.  See [README.md § CDD Quality Sweep](README.md#cdd-quality-sweep). |
| **CDD Analysis** | Comparison of documentation against code reality.  Covers quality, coverage, and mismatches (including source comments and docstrings).  Performed before implementation (step 2) and after (step 5, differential). |
| **TDD Principle** | Code and interface design must be designed with testability in mind.  Not all behaviour is automatable — the principle requires conscious evaluation, not blind coverage.  See [testing.md § The TDD Method](testing.md#the-tdd-method). |
| **TDD Analysis** | Test framework equivalent of the CDD Analysis.  Identifies test gaps, recommends framework changes, and flags when automation is impractical.  See [testing.md § The TDD Analysis](testing.md#the-tdd-analysis). |
| **Solitary unit testing** | Martin Fowler's term for tests that isolate the SUT with test doubles (mocks, stubs, fakes) for all collaborators.  Each test exercises exactly one module; dependencies are simulated.  Narrow blast radius, but only exercises the SUT against a *model* of its collaborators — so test passes don't prove integration.  See [Fowler 2014](https://martinfowler.com/bliki/UnitTest.html). |
| **Sociable unit testing** | Fowler's complement to solitary: tests drive the SUT with its *real* collaborators linked in.  A failing sociable test can implicate the SUT or any of its transitive dependencies; the blast radius is wider, but coverage is real code exercising real code.  Requires a codebase shape where each module's dependency closure is bounded and composable — which is what stratification delivers. |
| **Bundled unit testing** | CSE's flavor of sociable testing.  Each test bundle is a linker artifact built from the SUT plus its full dependency closure (no behavioural mocks — only minimal linker scaffolding in `dev/*_test_stub.s`).  One SUT per bundle; one test file per bundle; one production-build config mirrored per bundle (e.g. `asm_core` has 6502 / 6510 / 65c02 (the CMOS mode) / 45gs02 variants — see [testing.md § Principle 10](testing.md)).  Enabled by — and in turn enforces — the codebase's stratified shape: a bundle *is* a downward slice through the DAG. |
| **Scope Creep** | Unplanned significant changes discovered during implementation.  Triggers a discussion-and-approval gate before the CDD Method is applied recursively to the new scope.  Recursion terminates at the approver's discretion. |
| **CDD Feedback Round** | The discussion triggered by scope creep or by a TDD Analysis that reveals implications for the original plan.  Must be resolved before implementation continues. |
| **CDD Report** | The final deliverable of the CDD Method.  Summarises all changes (documentation, tests, code), highlights unplanned changes, and suggests future improvements. |
| **CDD Log** | Self-review of a session that examines how the CDD System served the work — where the Method, Corpus discipline, Maintenance, Escape Analysis, or test framework worked well, where they didn't, why, and concrete suggestions for improvement.  Distinct from the CDD Report (which summarises what changed) and from Escape Analysis (which reacts to a single escape): the Log evaluates the *system itself* against the lived experience of the session.  Performed at each milestone, alongside CDD Maintenance: the Log is the reflective half of the milestone gate (Maintenance audits the artefact, the Log audits the process).  Findings feed the next Maintenance round; principle-level proposals feed testing.md / README.md amendments. |
| **Escape Analysis** | Reactive CDD process invoked when a bug is found that the test suite failed to catch.  Traces the escape backward: the missing test → the contract clause that should have prompted the test → the testing.md principle that should have forced the clause.  Amendments at all three layers are committed together, plus a two-axis corpus sweep: (a) class-wide (other code fitting the same bug shape) and (b) cross-module handoff (upstream callers whose state provision could silently defeat the new contract).  Each Escape Analysis tightens the corpus permanently — the same class of bug cannot escape twice.  See [README.md § Escape Analysis](README.md#escape-analysis). |

## Design vocabulary

| Term | Definition |
|------|------------|
| **emitter pattern** | A reusable output template: set `io_cx = 0`, write fields with `io_put*` calls, `io_clear_eol`.  Used by REPL commands (`emit_dot`, `emit_mem`, `show_prompt`) and any code that renders a formatted screen line. |
| **convention** | A naming or formatting pattern followed for consistency.  Example: `mn_` prefix for mnemonic table symbols.  Violating a convention looks wrong but doesn't break anything. |
| **contract** | A binding interface agreement between two modules (or between a module and its callers).  Specifies inputs, outputs, side effects, and who owns what.  Violating a contract is a bug. |
| **invariant** | A condition that must hold at every observable point during execution.  Example: "emitters always leave the cursor on the last column written."  If an invariant is temporarily broken, it must be restored before any code that depends on it runs. |
| **guarantee** | A postcondition that a function promises to its caller.  Example: "`show_prompt` leaves the cursor at column 5."  The caller may rely on a guarantee without checking. |
| **platform driver layer** | The seams through which CSE touches the machine — KERNAL entries and cells, banking, memory maps, the interrupt frame, screen, keyboard, loader — each one interface with a body per platform selected by `.ifdef`.  A role of the existing leaf modules, not a layer of its own ([platform_layer.md](platform_layer.md)). |
| **seam** | One entry of the platform driver layer: one name (a constant, a macro or a routine), one contract, a body per platform.  Code above a seam names no machine fact. |
| **template** | A repeating structural form used across the codebase.  Example: the emitter pattern (`io_cx = 0`, write fields, `clear_eol`).  Templates reduce cognitive load — once you've read one instance, the rest are familiar. |
| **axiomatic module** | A module that declares only symbol exports — layout slots, RODATA literals and tables, BSS reservations, numeric constants — and contains no CODE segment.  Has no testable contract beyond "the symbols exist and link," which the linker enforces on every build.  In CSE: all of L0.  Axiomatic modules do not receive unit test files; correctness is enforced transitively by every bundled test that links them.  See [testing.md § Principle 12](testing.md). |
| **behavioural module** | A module with a CODE segment and an exported contract over its runtime behaviour.  The complement of *axiomatic module*.  Every behavioural module gets a test file under `tests/unit/` or `tests/integration/`; every exported symbol is backed by a correctness test or a vocal skip (Principle 8). |
| **partial-mode function** | A function whose success depends on ancillary state — an input-pointer position, a residual-input marker, a progress counter — in addition to its return code.  Callers can only reason correctly about composition with a partial-mode function when that ancillary state is both documented (stopping-position table in the module doc) and executable (position-pinning tests per Principle 13).  Canonical example: `expr_eval` returns success with `expr_val` set AND leaves `expr_ptr` at the first unparsed byte; internal assembler callers rely on this to parse prefixes like `$10,X`, but single-expression REPL commands must enforce their own end-of-input check.  See [expr.md § Partial-mode contract](modules/expr.md#partial-mode-contract). |

## Encoding

| Term | Definition |
|------|------------|
| **PETSCII** | C64 character encoding.  Two modes: *unshifted* ($41–$5A = uppercase, $C1–$DA = graphics) and *shifted* ($41–$5A = lowercase, $C1–$DA = uppercase).  CSE uses shifted mode.  KERNAL returns $41–$5A for unshifted keypresses, $C1–$DA for shifted. |
| **VICII screen code** | Display encoding for screen RAM.  In shifted mode: $01–$1A = lowercase a–z, $41–$5A = uppercase A–Z.  The mnemonic hash uses normalized values 1–26 (same as VICII lowercase screen codes) but derives them via AND #$1F, which works identically on PETSCII and VICII input. |
| **PETSCII folding** | Collapsing $C1–$DA to $41–$5A (uppercase → lowercase).  Done by `fold_char`.  Hex parsing accepts both ranges. |
| **screen RAM** | $0400–$07E7.  40×25 bytes of screen codes.  The REPL reads and writes this directly. |
| **color RAM** | $D800–$DBE7.  Per-character color nybbles.  Managed by `restore_colors`. |

## Hardware

| Term | Definition |
|------|------------|
| **kernal** | The CBM KERNAL ROM ($E000–$FFFF) — Commodore's stock OS routines.  Spelled "kernal" with an `a` (CBM's spelling) to distinguish it from CSE's own kernel.  CSE uses the kernal for keyboard, disk I/O, and cursor sync. |
| **kernel** | The CSE runtime — code that runs above the user's program and services it.  Spelled "kernel" with an `e`.  CSE is a kernel in the OS sense: it owns the BRK and NMI vectors, multiplexes the screen, and provides a host environment for user code.  See [design_cse_as_kernel.md](design_cse_as_kernel.md). |
| **userland** | The execution mode where the CPU is running user code (started by `j`, `g`, `c`, `t`, or `o`).  Tracked by the `in_userland` flag.  Userland → kernel transitions happen via BRK or NMI; kernel → userland transitions happen via RTI from a synthesized frame. |
| **in_userland** | A 1-byte ZP flag (zp.s) that names the current execution mode: `$80` while user code runs, 0 in the kernel.  Set just before the RTI into user code (`return_to_userland` / `restore_userland_state`); cleared at BRK and NMI handler entry.  Read by the NMI handler to choose between a screen refresh (kernel) and a break into the debugger (userland). |
| **return_to_userland** | The fresh-start kernel→userland gate (debugger.s).  Pushes `brk_stub - 1` on the user's stack as the program's top-level return address, then enters user code like `restore_userland_state`: restores the user's ZP, synthesises an RTI frame from the `reg_*` shadows, sets `in_userland`, RTIs.  Used for `j`, `g` and the first run after a cold preview; resumes (`c`, `t`, `o`) use `restore_userland_state`, which pushes no sentinel. |
| **brk_stub** | A BRK instruction and its signature byte at a stable, non-banked code address (debugger.s).  When user code performs its top-level RTS, it pops the sentinel address pushed by `return_to_userland` and lands at `brk_stub`.  The BRK fires; the handler classifies a BRK whose address (pushed PC − 2) is `brk_stub` as a clean exit (`; rts`). |
| **early entry** | The IRQ/BRK handler entry `cse_brk_handler_early`, reached only when the kernal was banked out at the moment of interrupt — the CPU read the vector from the RAM at $FFFE.  Reaching it is itself the signal: an IRQ there runs the kernal's IRQ body with the kernal banked in, then puts the interrupted `$01` back before the final RTI.  (The NMI shadow at $FFFA points straight at `cse_nmi_handler`.) |
| **KERNAL** | Legacy spelling carried in source labels (`KERNAL_RESTOR`, `KERNAL_IRQ_BODY`).  Treated as a synonym for **kernal** in prose; new prose prefers lower-case "kernal" to distinguish from CSE's kernel. |
| **banking** | Switching $01 bit 1 to hide kernal ROM and expose the underlying RAM ($E000–$FFFF).  CSE stores its symbol table, heap, KDATA tables, and screen save in this region.  `kernal_bank_out`/`kernal_bank_in` (mem.s) manage the switch.  On the m65 build the helpers are no-ops: nothing of CSE's is under the KERNAL there ([platform_layer.md § Banking](platform_layer.md#banking)). |
| **BRK** | 6502 software interrupt instruction.  CSE uses BRK as the universal user → kernel transition: debugger breakpoints overwrite a byte with $00; user top-level RTS lands at `brk_stub`. |
| **NMI** | Non-maskable interrupt.  RUN/STOP+RESTORE triggers NMI; CSE's NMI handler dispatches on `in_userland` (break into the debugger / refresh the REPL screen). |
| **asm_cpu** | CPU mode selector: 0=6502 (legal only), 1=6510 (+illegal), 2=65C02 (+CMOS; the CMOS mode), 3=4510, 4=45GS02.  A build accepts only its CPU set's values ([build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets)). |
| **MEGA65 mode** | The MEGA65's native mode: BASIC 65 and the MEGA65 KERNAL, BASIC text at `$2001`.  The m65 build runs in it.  Its opposite is **GO64**, the C64 mode, which the m65 build does not use. |
| **raw-byte instruction** | A 45GS02-only instruction written as `.byte` data by a macro from `src/m45_ops.inc`, because all CSE code is assembled as 6502 code ([platform_layer.md § Raw-byte instructions](platform_layer.md#raw-byte-instructions)). |
| **xmega65** | Xemu's MEGA65 emulator.  Runs the m65 build headless for Tier X and records the golden files M65Emu is checked against ([testing.md § Tier X](testing.md#tier-x--xmega65-m65-automated)). |
| **M65Emu** | The m65 build's Tier I harness: a full 45GS02 in py65 (`MPU45GS02`), the MEGA65 memory layout (`M65Memory`) and the devices the KERNAL needs, started from the post-boot snapshot; it offers `C64Emu`'s test surface through their shared base, `EmuBase` ([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)).  The m65 counterpart of `C64Emu`. |
| **bank notation** | `b.xxxx` names a MEGA65 address by its 64 K bank and the offset in it: `3.2000` is flat `$32000`, `0.1F00` is `$01F00`, `$400.8000` is the cartridge's flat `$4008000` (the MEGA65 Book's notation). |
| **CBDOS** | The MEGA65's disk system in the interface ROM (bank 2): it serves units 8 and 9 — usually the internal drive or a mounted D81 image — while the KERNAL sends every other unit to the IEC bus ([disk.md § On m65](modules/disk.md#on-m65)). |
| **CSE map** | The m65 build's 16-bit memory map while the kernel runs — BASIC 65's own map at the READY prompt, with CSE's code window and data window in bank 3 ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)). |
| **data window** | On m65, `$8000–$BFFF` of the CSE map, showing `3.8000–3.BFFF`: CSE's BSS, KDATA, symbol table and REPL screen save, directly addressable.  The *code window* is `$2000–$7FFF` → `3.2000`. |
| **interface ROM** | The MEGA65 ROM's `2.C000–2.CFFF`, visible at `$C000` in both m65 maps through `$D030`; the KERNAL depends on it. |
| **run premise** | The machine a BASIC 65 program finds when `RUN` starts it through its `SYS` line — map, registers, stack, free memory.  User programs run under CSE in that machine, as closely as sensibly possible ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)). |
| **program region** | On m65, the bank-0 memory the user's program owns, `PROG_LO`–`PROG_HI` (`workstart`–`workend`); the C64 counterpart is the workspace. |
| **source region** | On m65, the region holding the editor's source text (the gap buffer), in a ROM bank CSE owns. |
| **KCALL** | The platform macro that calls a KERNAL jump-table entry under the KERNAL's prerequisites: `jsr` on c64; on m65 with `B = 0` around the call ([platform_layer.md § KERNAL calls](platform_layer.md#kernal-calls)). |
| **Hyppo** | The MEGA65's Hypervisor program; its documented traps (`hyppo_getversion`, `hyppo_rom_writeenable`, `hyppo_reset`) are the Hypervisor services the m65 build uses ([platform_layer.md § Constants](platform_layer.md#constants)). |
| **user map** | The m65 build's 16-bit memory map while user code runs: the KERNAL's `SYS` map ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)). |
| **bank state** | On m65, the user program's banking as a break finds it: its `MAP` setting (read through the Hypervisor's `hyppo_get_mapping`), its CPU port and `$D030` — and, though KERNAL state, its `SYSFLAGS` and the KERNAL's map record (`0.011C–011F`).  Captured at every break, installed again at every resume; a fresh start installs the run premise's ([platform_layer.md § User transitions](platform_layer.md#user-transitions)). |
| **KERNAL's map record** | On m65, `0.011C–011F`: the A X Y Z `MAP` operands the MEGA65 KERNAL keeps for its far calls (the book's "KERNAL-managed memory map") and restores when one returns — CBDOS's disk calls included.  Part of the bank state: the CSE map while CSE runs ([platform_layer.md § User transitions](platform_layer.md#user-transitions)). |
| **resident stub** | The m65 build's only code in bank 0, at the top of CSE's base page and visible in both maps: it switches between the CSE map and the user map and holds `brk_stub` ([mem.md § The resident stub](modules/mem.md#the-resident-stub-m65-only)). |
| **far pointer** | A ZP pointer that may reach memory outside the kernel's own 16-bit view — user memory, the screen, the source text, and CSE's data where the same pointer also serves CSE's buffers.  2 bytes on c64, 4 on m65 (with its bank) ([platform_layer.md § Far memory](platform_layer.md#far-memory)). |
| **CSE base page** | The m65 build's own zero page (`B = CSE_BP`, the page `0.1F00` in both maps); base page 0 stays the user's and the KERNAL's, and the stack is shared ([platform_layer.md § Base page](platform_layer.md#base-page)). |
| **Hypervisor reset** | `hyppo_reset`, the Hypervisor's warm boot: it reloads the ROM banks and the KERNAL boots to BASIC 65.  How the m65 build quits ([platform_layer.md § Constants](platform_layer.md#constants)). |
| **C64Emu** | The C64 builds' Tier I harness: py65's 6502 on the C64 memory map with the real KERNAL ROM and a synthesised KERNAL state ([testing.md § C64Emu](testing.md#c64emu--emulator-class)). |
| **post-boot snapshot** | M65Emu's starting state — one per MEGA65 ROM it is checked on — recorded from xmega65 at the BASIC 65 prompt by `dev/capture_m65_state.py` into `build/m65_state/` with its reference runs; it holds the MEGA65 ROM, so it is never committed. |
| **reference run** | Code run in xmega65 from the post-boot snapshot whose registers and memory changes M65Emu must reproduce ([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)). |
| **golden file** | A recorded oracle committed under `tests/fixtures/golden/`: what each CPU set assembles and lists, or what xmega65's 45GS02, memory layout and DMA do ([build_system.md § Golden files](build_system.md#golden-files)). |
| **jiffy tick** | The emulators' repeating scheduled IRQ (`enable_jiffy_clock()`), standing for the C64's CIA1 timer interrupt or the MEGA65's frame. |
| **ca65** | 6502 assembler (part of the cc65 toolchain).  All CSE source is pure assembly. |
| **ld65** | 6502 linker (part of the cc65 toolchain).  Links .o files into the final PRG binary. |
| **py65** | Python 6502 emulator used by the test suite to execute assembled test binaries.  The m65 build runs on M65Emu's `MPU45GS02`, a py65 subclass. |
