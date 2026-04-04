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
| **ZP** | Zero-page: address $00–$FF.  Selects 2-byte instruction encoding. |
| **ABS** | Absolute: address $0000–$FFFF.  Selects 3-byte instruction encoding. |
| **wide** | `expr_wide = 1`: expression forced to ABS.  Sticky — once wide, stays wide. |
| **base opcode** | Opcode byte with the mode field (`bbb`) zeroed.  Final opcode = `base | (bbb << 2)`. |
| **mode index** | Integer 0–15 encoding an addressing mode.  Used by `au_mode.s` and `opcode_lookup.s`.  The mapping: 0=IMP, 1=ACC, 2=IMM, 3=ZP, 4=ZPX, 5=ZPY, 6=ABS, 7=ABX, 8=ABY, 9=IND, 10=INX, 11=INY, 12=REL, 13=ZPI, 14=AIX, 15=ZPREL. |
| **operand profile** | Index (0–29) describing which mode indices a mnemonic accepts.  Encoded as a 16-bit bitmask in `mn_modes`.  Example: profile 16 (LDA) = {IMM, ZP, ZPX, ABS, ABX, ABY, INX, INY}. |
| **zone** | Dispatch category (A–H) in the line assembler.  Derived from the operand profile.  Zones A–F are fixed single-mode groups; G and H are multi-mode groups that call `au_parse_mode` + `opcode_lookup`. |
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
| **VICII screen code** | Display encoding for screen RAM.  In shifted mode: $01–$1A = lowercase a–z, $41–$5A = uppercase A–Z.  Used internally by the line assembler. |
| **PETSCII folding** | Collapsing $C1–$DA to $41–$5A (uppercase → lowercase).  Done by `fold_char`.  Hex parsing accepts both ranges. |
| **screen RAM** | $0400–$07E7.  40×25 bytes of screen codes.  The REPL reads and writes this directly. |
| **color RAM** | $D800–$DBE7.  Per-character color nybbles.  Managed by `restore_colors`. |

## Hardware

| Term | Definition |
|------|------------|
| **KERNAL** | C64 ROM routines ($E000–$FFFF).  CSE uses KERNAL for keyboard, disk I/O, and cursor sync. |
| **NMI** | Non-maskable interrupt.  RUN/STOP+RESTORE triggers NMI; CSE intercepts it for mode switching. |
| **al_cpu** | CPU mode selector: 0=6502 (legal only), 1=6510 (+illegal), 2=65C02 (+CMOS). |
| **ca65** | 6502 assembler (part of the cc65 toolchain).  All CSE source is pure assembly. |
| **ld65** | 6502 linker (part of the cc65 toolchain).  Links .o files into the final PRG binary. |
| **py65** | Python 6502 emulator used by the test suite to execute assembled test binaries. |
