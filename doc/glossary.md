# CSE Glossary

All terms are used consistently across source code, comments, tests,
and documentation.

## User-facing

| Term | Definition |
|------|------------|
| **REPL** | Read-eval-print loop.  CSE's command-line mode.  The screen is the command buffer. |
| **editor** | Full-screen source code editor.  RUN/STOP toggles between REPL and editor. |
| **block size** | Number of bytes operated on by `m`, `d`, `f`, `t`, `h`, `+`, `-`.  Set by `b`. |
| **block edit** | Workflow: dump a block (`d`/`m`), cursor to a line, edit in-place, RETURN. |
| **cur_addr** | The REPL's current address.  Set by `AAAA:` prefix; advanced by commands. |
| **project name** | User-facing identifier for a source+binary pair.  Stored in `cur_project_name` as a bare stem (no type suffix, no trailing dot).  The disk filename is derived: SEQ = stem, PRG = stem + `.`.  Default `"out"` when unset. |
| **verbatim name** | A quoted filename with a `,s` or `,p` type suffix at the tail (`foo,s` / `foo,p`).  Tells `l`/`s` to use the bare name (suffix stripped) on disk with no derivation.  Lets the user bypass the project-name convention for ad-hoc files. |
| **derived name** | Disk filename computed from `cur_project_name`: SEQ = stem, PRG = stem + `.`.  Used when the user supplies a plain quoted name (no `,m` suffix) or no quoted name at all. |

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
| **pass 0** | First scan: collect labels/constants, compute instruction sizes.  Errors not counted. |
| **pass 1** | Second scan: all symbols resolved; emit bytes, count errors. |
| **ZP** | Zero-page: address $00–$FF.  Selects 2-byte instruction encoding.  Also: the `.segment "ZEROPAGE"` allocation in the linker. |
| **ABS** | Absolute: address $0000–$FFFF.  Selects 3-byte instruction encoding. |
| **BSS** | Uninitialized runtime state segment.  Zeroed at boot by main.s.  All mutable module variables live here. |
| **RODATA** | Read-only data segment.  Constants, string literals, lookup tables.  Linked into the runtime image alongside CODE. |
| **KDATA** | Data segment that lives under KERNAL ROM ($F100–$F4F1).  Copied from the PRG load image to banked RAM by loader.s at startup.  Contains lookup tables (mn_modes, mode_offset, dasm strings). |
| **workspace** | The $0800–workend memory region shared by user programs and source text.  The gap buffer grows downward from `__CODE_RUN__`; user output grows upward from $0800. |
| **gap buffer** | The editor's text storage: a contiguous buffer with a movable gap at the cursor.  Insertions fill the gap (O(1)); the gap slides on cursor movement.  `buf_base` is the buffer floor, `BUF_END = __CODE_RUN__` is the ceiling. |
| **symbol table** | Hash table at $E000–$E5FF (256 slots × 6 bytes) under KERNAL ROM.  Stores assembler labels and constants.  Name strings live in the adjacent heap. |
| **heap** | Symbol-name storage at $E600–$EEFF under KERNAL ROM.  Grows upward; cleared by `sym_clear`. |
| **fingerprint** | Mnemonic disambiguation byte: `fp = (c2<<3) | (c3>>2)`.  After the h7 hash selects a slot, the fingerprint confirms the exact mnemonic with zero false positives. |
| **mnemonic hash** | `h7 = (c1×4 + c3 + HASH_T[c2]) & $7F`.  Maps a 3-letter mnemonic to a 7-bit slot index (0–127).  Uses VICII-normalized letter values (A=1..Z=26). |
| **wide** | `expr_wide = 1`: expression forced to ABS.  Sticky — once wide, stays wide. |
| **base opcode** | Opcode byte with the mode field (`bbb`) zeroed.  Final opcode = `base | (bbb << 2)`. |
| **mode index** | Integer 0–15 encoding an addressing mode.  Used by `au_mode.s` and `opcode_lookup.s`.  The mapping: 0=IMP, 1=ACC, 2=IMM, 3=ZP, 4=ZPX, 5=ZPY, 6=ABS, 7=ABX, 8=ABY, 9=IND, 10=INX, 11=INY, 12=REL, 13=ZPI, 14=AIX, 15=ZPREL. |
| **operand profile** | Index (0–29) describing which mode indices a mnemonic accepts.  Encoded as a 16-bit bitmask in `mn_modes`.  Example: profile 16 (LDA) = {IMM, ZP, ZPX, ABS, ABX, ABY, INX, INY}. |
| **zone** | Dispatch category (A–H) in the line assembler.  Derived from the operand profile.  Zones A–F are fixed single-mode groups; G and H are multi-mode groups that call `mode_parse` + `asm_opcode_lookup`. |
| **mnemonic suffix** | Digit `0`–`7` after RMB/SMB/BBR/BBS: the `3` in `RMB3`.  Encodes a bit index. |

## Process

| Term | Definition |
|------|------------|
| **DDD System** | The totality of document-driven practices in this repository: the DDD Method, the TDD Method, the DDD Corpus, and the DDD Maintenance process.  The system's goal is that documentation is always the source of truth and never drifts from code. |
| **DDD Corpus** | The complete body of documentation that defines the system: `doc/` files, module docs in `doc/modules/`, authoritative data files in `dev/`, and the test contracts in `tests/`.  The Corpus is the source of truth for all design intent, interfaces, and behaviour. |
| **DDD Method** | The seven-step development process defined in [README.md § The DDD Method](README.md#the-ddd-method): doc first → DDD Analysis → TDD Analysis → implement → differential DDD → commit → report.  Mandatory for all repository changes, no exceptions. |
| **DDD Maintenance** | A periodic audit of the DDD Corpus independent of feature work.  See [README.md § DDD Maintenance](README.md#ddd-maintenance) for the full audit scope and trigger. |
| **DDD Analysis** | Comparison of documentation against code reality.  Covers quality, coverage, and mismatches (including source comments and docstrings).  Performed before implementation (step 2) and after (step 5, differential). |
| **TDD Principle** | Code and interface design must be designed with testability in mind.  Not all behaviour is automatable — the principle requires conscious evaluation, not blind coverage.  See [testing.md § The TDD Method](testing.md#the-tdd-method). |
| **TDD Analysis** | Test framework equivalent of the DDD Analysis.  Identifies test gaps, recommends framework changes, and flags when automation is impractical.  See [testing.md § The TDD Analysis](testing.md#the-tdd-analysis). |
| **Scope Creep** | Unplanned significant changes discovered during implementation.  Triggers a discussion-and-approval gate before the DDD Method is applied recursively to the new scope.  Recursion terminates at the approver's discretion. |
| **DDD Feedback Round** | The discussion triggered by scope creep or by a TDD Analysis that reveals implications for the original plan.  Must be resolved before implementation continues. |
| **DDD Report** | The final deliverable of the DDD Method.  Summarises all changes (documentation, tests, code), highlights unplanned changes, and suggests future improvements. |

## Design vocabulary

| Term | Definition |
|------|------------|
| **emitter pattern** | A reusable output template: set `io_cx = 0`, write fields with `io_put*` calls, `io_clear_eol`.  Used by REPL commands (`emit_dot`, `emit_mem`, `show_prompt`) and any code that renders a formatted screen line. |
| **convention** | A naming or formatting pattern followed for consistency.  Example: `mn_` prefix for mnemonic table symbols.  Violating a convention looks wrong but doesn't break anything. |
| **guideline** | A recommended practice that admits exceptions.  Example: "prefer the stack for scratch."  When a guideline is overridden, the reason should be documented. |
| **contract** | A binding interface agreement between two modules (or between a module and its callers).  Specifies inputs, outputs, side effects, and who owns what.  Violating a contract is a bug. |
| **invariant** | A condition that must hold at every observable point during execution.  Example: "emitters always leave the cursor on the last column written."  If an invariant is temporarily broken, it must be restored before any code that depends on it runs. |
| **guarantee** | A postcondition that a function promises to its caller.  Example: "`show_prompt` leaves the cursor at column 5."  The caller may rely on a guarantee without checking. |
| **template** | A repeating structural form used across the codebase.  Example: the emitter pattern (`io_cx = 0`, write fields, `clear_eol`).  Templates reduce cognitive load — once you've read one instance, the rest are familiar. |
| **design pattern** | A named, reusable solution to a recurring design problem.  Broader than a template: includes the problem context, the forces in tension, and why this shape resolves them.  Example: the block-edit workflow (dump editable lines, re-execute in place, preserve trailing content). |

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
| **in_userland** | A 1-byte BSS flag (owned by main.s) that names the current execution mode.  Set by `return_to_userland` just before its RTI to user code; cleared at BRK handler entry.  Read by the NMI handler to choose between "swallow" (kernel) and "break into debugger" (userland) dispatch. |
| **return_to_userland** | The shared kernel→userland helper.  Synthesises an RTI frame from `reg_*` shadows, pushes `brk_stub - 1` onto the stack as user's top-level RTS sentinel, sets `in_userland`, and RTIs.  Used by `j`, `g`, `c`, `t`, `o`. |
| **brk_stub** | A 1-byte BRK instruction at a stable, non-banked code address.  When user code performs its top-level RTS, it pops the sentinel address pre-pushed by `return_to_userland` and lands at `brk_stub`.  The BRK fires; the handler classifies "PC-1 == brk_stub" as a clean userland exit. |
| **cold entry** | The first user→kernel transition at boot: cold init synthesises a userland-shaped frame whose PC points at `brk_stub`, then RTIs.  The BRK handler dispatches the resulting BRK as a clean exit and flows into the warm-start tail (skipping the screen clear).  Same code path as RESTORE-from-userland recovery. |
| **early entry** | An interrupt handler entry point reached only when the kernal was banked out at the moment of interrupt — i.e. the CPU read the IRQ/NMI vector from RAM at $FFFA/$FFFE.  Reaching the early-entry label is itself the signal that the kernal needs to be banked back out before the final RTI. |
| **KERNAL** | Legacy spelling carried in source labels (`KERNAL_RESTOR`, `KERNAL_VECTOR`).  Treated as a synonym for **kernal** in prose; new prose prefers lower-case "kernal" to distinguish from CSE's kernel. |
| **banking** | Switching $01 bit 1 to hide kernal ROM and expose the underlying RAM ($E000–$FFFF).  CSE stores its symbol table, heap, KDATA tables, and screen save in this region.  `kernal_bank_out`/`kernal_bank_in` (mem.s) manage the switch. |
| **BRK** | 6502 software interrupt instruction.  CSE uses BRK as the universal user → kernel transition: debugger breakpoints overwrite a byte with $00; user top-level RTS lands at `brk_stub`; cold init synthesises an RTI to `brk_stub`. |
| **NMI** | Non-maskable interrupt.  RUN/STOP+RESTORE triggers NMI; CSE's NMI handler dispatches on `in_userland` (break into debugger / swallow). |
| **asm_cpu** | CPU mode selector: 0=6502 (legal only), 1=6510 (+illegal), 2=65C02 (+CMOS). |
| **ca65** | 6502 assembler (part of the cc65 toolchain).  All CSE source is pure assembly. |
| **ld65** | 6502 linker (part of the cc65 toolchain).  Links .o files into the final PRG binary. |
| **py65** | Python 6502 emulator used by the test suite to execute assembled test binaries. |
