# CSE — Project Goals and Description

## What Is CSE?

CSE (C64 Screen Editor) is an integrated assembler development
environment for the Commodore 64.  It also runs on the C128 in C64
mode, with 65C02 support for the 8502 CPU.

CSE serves **two audiences on one surface**.  For the seasoned
developer it is a sketchpad — write a few lines of code, assemble,
run, poke at registers, tweak a byte, re-run, with no cross-development
toolchain and no context switch.  For the learner it is a first
environment whose whole surface is the language to be learned —
64 KiB of documented RAM, 56 documented instructions, a memory map
that prints on one page, and a cheat sheet that is the environment.
Both audiences get the same tool, undiluted.  See
[Design Priorities § 7](#design-priorities) for the commitment this
implies.

CSE combines the workflow of **MasterSeka** (immediate single-line
assembly, integrated editor, fast iteration) with the power of a
**radare2-style REPL** (addressable commands, hex editing, expression
calculator, memory inspection, block operations).

For the motivating context — why CSE exists, how it compares to its
peers, and the pedagogical thesis the design priorities below derive
from — see [background.md](../background.md).  The priorities and
audiences stated here are the corpus-authoritative summary;
background.md is the user-facing long form.

## Components

### The REPL

The REPL is CSE's command center.  The screen is the command buffer:
every line is executable.  From here the user can:

- **Inspect state** — disassemble code, dump memory, view registers
- **Modify state** — edit bytes in-place, patch instructions, set registers
- **Assemble** — single-line (`.` command) for quick patches, or full
  two-pass source assembly (`a` command) from the editor buffer
- **Manage files** — load and save PRG binaries and SEQ source files,
  browse disk directories
- **Calculate** — full expression evaluator with hex, decimal, binary,
  bitwise operators, lo/hi byte extraction
- **Debug** — breakpoints (`b`), step-into (`t`), step-over (`o`),
  continue (`c`), NMI break, register inspect.

Commands are terse single-character keys.  Block-size-aware operations
(`m`, `d`, `+`, `-`) work on configurable ranges.  Auto-advance and
repeat-on-RETURN keep the flow uninterrupted.

### The Editor

One keypress (RUN/STOP) switches to a full-screen source editor
optimized for writing 6502 assembly on the C64's limited keyboard.
It borrows only the simplest, most powerful tools from modern IDEs:

- Gap-buffer storage for fast insert/delete anywhere
- Real-time status bar (dirty flag, filename, free memory, position)
- 22 lines of source, immediate cursor response

The editor stores source as PETSCII text in a gap buffer that shares
memory with the assembled output — the classic C64 model of programs
growing up and source growing down, with the `i` command always
showing how much room is left.

### The Assembler

A two-pass assembler for the CPUs of the build's platform — 6502,
6510 and 65C02 on the C64; 6502, 65C02, 4510 and 45GS02 on the
MEGA65 — with:

- Global and local labels, constants, forward references
- Full expression language (arithmetic, bitwise, lo/hi byte, grouping)
- Directives: `.org`, `.db`, `.dw`, `.str`, `.scr`, `.res`, `.align`,
  `.cpu`, `.const`
- Automatic ZP/ABS mode selection — no manual overrides needed
- Runtime CPU switching within the build's CPU set: legal-only 6502,
  6510 with illegals, or 65C02 on the C64; legal-only 6502, 65C02,
  4510, or 45GS02 (Q and far forms) on the MEGA65

### The Disassembler

A table-driven decoder over a generated opcode map, sized to the
build's CPU set, that understands every CPU mode of the build.  Used
by the `.` and `d` commands.  On the MEGA65 it decodes the 45GS02's
prefixed (Q and far) instructions as single instructions.

## Features

**REPL commands** — single-character, addressable (`AAAA:cmd`):

| Area | Commands | What they do |
|------|----------|--------------|
| Memory | `m` | Hex dump and in-place byte editing |
| Assembly | `.` `d` `a` | Single-line asm/disasm, block disassembly, full source assembly |
| Execution | `j` `g` | Run at an address / at `main`; a top-level RTS returns to the REPL and shows the registers |
| Registers | `r` | View/edit A, X, Y, SP, and individual flags |
| Navigation | `@` `+` `-` `B` | Seek, advance, retreat, set block size |
| Files | `l` `s` `$` | Load/save PRG and SEQ files, disk directory |
| Utility | `?` `i` `C` `u` | Expression calculator, memory map, colors, CPU mode |
| Debug | `b` `t` `o` `c` | Breakpoints, trace, trace-over, continue |

The screen is the command buffer.  Every line is executable.  RETURN
on an empty line repeats the last command at the next address.
`;` marks inline comments.

**Editor:**

- RUN/STOP toggles between REPL and editor instantly
- Gap-buffer storage, cursor keys, insert/delete
- Status bar: dirty flag, filename, free bytes, cursor position
- Source saved as SEQ files, loaded back losslessly

**Assembler — source language:**

- Labels: `main:` (global), `.loop:` (local, scoped to last global)
- Constants: `.const name expr`
- Numeric formats: `$hex`, `%binary`, decimal
- Expressions: `+` `-` `*` `/` `<<` `>>` `&` `£` `^` `!` `<` `>` `()`
- Directives: `.org` `.db` `.dw` `.str` `.scr` `.res` `.align` `.cpu`
- Forward references resolved automatically across two passes
- ZP/ABS encoding selected automatically from value width

**CPU modes** — switchable at runtime with `u`:

| Mode | Mnemonics | Use case |
|------|-----------|----------|
| `6502` | 56 legal | Standard NMOS, portable code |
| `6510` | 56 + illegals | C64-native, undocumented opcodes |
| `65c02` | 56 + CMOS | C128 (8502), WDC boards |

Both assembler and disassembler respect the active CPU mode.

Which modes a build offers is fixed at build time by its CPU set
([build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets)).
A 6502-only build excludes all illegal and CMOS code, saving space.

**Expression calculator** (`?` command):

Full-precedence evaluator usable from the REPL.  Supports labels and
constants from the last assembly.  Output shows hex, decimal, and
(for 8-bit values) binary.

## Design Priorities

**Dependants:** [README.md § Who it's for](../README.md) (framing
summary for end users); [background.md](../background.md) (long-form
motivation and peer comparison).  Both are derived from this section;
changes here must propagate.

1. **Minimal footprint.**  Every byte of CSE is a byte the user can't
   use for their project.  Code is hand-optimized 6502 assembly where
   it matters.  ROM-ready architecture (no self-modifying code) enables
   a future cartridge build where CSE costs zero RAM for code.

2. **Maximum workspace.**  The user's mental model: "my program lives
   at $0800 and up."  CSE stays out of the way.  The `i` command shows
   exactly what's free.

3. **Fluent, immediate interaction.**  The edit-assemble-run-inspect
   cycle has no build step and no context switch.  The screen is the
   command buffer; every line is executable; RETURN repeats at the
   next address.  Commands are single characters, addressable as
   `AAAA:cmd`, with one grammar shared across editor, assembler,
   monitor, calculator, and debugger.  No modes to memorize beyond
   REPL and editor.  Users familiar with MasterSeka or radare2 should
   feel at home immediately; users new to both should not find the
   surface any larger than the work requires.

4. **C64 keyboard is the only input device.**  Every character used
   in source syntax, commands, and expressions must be typeable on
   the unmodified C64 keyboard.  This is why OR is `£` (not `|`),
   XOR is `^` (the ↑ key), and labels have no underscore.  This is
   also what lets the tool and the machine share a single surface:
   every key the user can press is a key CSE can parse.

5. **KERNAL-friendly.**  CSE completely replaces BASIC but cooperates
   with the KERNAL.  Disk I/O uses KERNAL calls.  `Q` restores BASIC
   cleanly.  The BRK and NMI vectors are taken over for the debugger
   and RUN/STOP+RESTORE, but the KERNAL's IRQ handler continues
   running (keyboard scan, jiffy clock).

6. **Transparency.**  CSE interposes nothing between the user and the
   CPU.  The assembler emits bytes the user can see; the disassembler
   and monitor show memory and instructions as they are; the debugger
   steps the real CPU one instruction at a time.  Every level of the
   stack — source, bytes, registers, memory — is inspectable and
   directly editable.  CSE does not ship an interpreter, a virtual
   machine, or a managed runtime.  If the user wants to know what the
   machine is doing, the answer is always one command away.

   This rules out any layer that would stand between the user and the
   instruction stream: a BASIC-like command wrapper, a scripting
   layer on top of the REPL, or a pseudo-register / pseudo-address
   illusion that simplifies the surface by lying about it.  The
   environment is the whole thing; nothing lives on top of it.

7. **One environment, two audiences.**  CSE is simultaneously a first
   environment for a programmer learning 6502 and a sketchpad for a
   seasoned developer.  Design decisions must serve both.  No
   "beginner mode" or "advanced mode" split.  No dumbed-down surface
   an expert has to work around, and no expert-only feature that
   leaves a beginner lost.  The cheat sheet is the whole language.
   Features that would help one audience at the cost of the other do
   not ship.

   The duality does not require splitting the surface because the
   underlying constraint — *the whole environment fits in the user's
   head* — is the same in both cases.  It also implies a feature
   filter: the mental model the learner builds on day one must still
   be correct on year five.  Any feature that teaches a temporarily-
   useful lie fails the dual-audience test, because the learner would
   have to unlearn it and the expert never wanted it.

## Implementation Principles

Constraints that govern how the code is written.

### 1. ZP is precious — use the stack for scratch

- **ZP** — pointers for indirect addressing, hot inner-loop state
- **Stack** — scratch values (saved/restored via `pha`/`pla`)
- **BSS** — persistent state that doesn't need fast access

Modules that never run concurrently can share ZP addresses — once
the call graph confirms they never overlap (the obvious candidates
do; see [memory_design.md § Zero Page Layout](memory_design.md#zero-page-layout)).

### 2. All syntax characters must be typeable on the C64 keyboard

No syntax element (operator, delimiter, directive prefix) may use a
character that the C64 keyboard cannot produce.  This is why OR is
`£` (not `|`), XOR is `^` (the ↑ key), and labels have no underscore.

### 3. CSE uses the lower/upper charset (lowercase mode)

The screen operates in VICII charset 2 (lower/upper mode, VIC $D018
bit 1 = 1).  All encoding work uses **32-byte chunks** — never
sub-ranges.

| PETSCII | Contents | Screen code |
|---------|----------|-------------|
| $40–$5F | **lowercase** (a–z + symbols) | $00–$1F |
| $60–$7F | uppercase (duplicate of $C0–$DF) ← avoid | $40–$5F |
| $C0–$DF | **uppercase** (A–Z + symbols) ← canonical | $40–$5F |

**$40–$5F = lowercase — the opposite of ASCII.**  PETSCII $41 is
lowercase `a`, not uppercase `A`.

$60–$7F and $C0–$DF produce identical screencodes.  CSE uses the
$C0–$DF range as canonical for uppercase because that's what the
KERNAL keyboard layer (GETIN returns $C1–$DA for shifted letters)
and ca65 `-t c64` character literals (`'A'` = $C1) produce.  The
`scr_to_pet` codec maps uppercase screen codes $40–$5F back to
$C0–$DF, so the round-trip through screen RAM **preserves case**.
Case-insensitive comparators (assembler, symbol table, expression
parser) fold $C0–$DF → $40–$5F at their own boundaries.

The full mapping tables and rules live in
[cse_io.md § Character Encoding Reference](modules/cse_io.md#character-encoding-reference)
— that is the single source of truth.

### 4. CPU-specific code must be compile-time gated

Code and tables specific to a CPU (6502, 6510, 65C02, 4510, 45GS02)
must be excluded at compile time — not gated at runtime.  Each build
serves a CPU set ([build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets));
the Makefile defines its top CPU (`CPU_<top>`, `CPU_CEIL`) and its
feature defines (`CMOS_SUPPORT`, `MEGA_SUPPORT`).  A build must not contain instruction paths, tables or
decode logic for a CPU outside its set (one exception, the C64 `mn7`
key set, is stated there).  This keeps the binary small
on constrained targets, and keeps the C64 builds untouched by the
MEGA65's larger CPU.

**Current status:** the generated tables come in one block per CPU set
(`.ifdef CPU_<top>`); code paths use the feature defines.  Runtime
`asm_cpu` checks remain only between members of the build's own set.

### 5. Don't get in the KERNAL's way — user code sees a working C64

User programs launched from the REPL (via `j`, `g`, `c`, `t`, `o`)
are expected to use the C64 KERNAL as their I/O layer, much as
a modern program uses its host terminal.  A user program's
`JSR $FFD2` is the equivalent of `write(1, …)` on Unix: it
must land on the REPL screen at the current cursor position,
with the current CSE theme colour, and it must work from the
very first character without the user having to re-initialize
anything first.

Concretely, CSE must ensure that at every moment user code
could start running:

- **KERNAL vectors lead to the real KERNAL.**  The IRQ/BRK/NMI
  vectors are either the stock KERNAL addresses or CSE-installed
  handlers that *delegate to the KERNAL path* for anything they
  don't themselves use.  CSE takes over BRK and NMI (`$0316`,
  `$0318`) for the debugger and RUN/STOP+RESTORE while it runs; the
  KERNAL's IRQ handler keeps running; RESTOR puts the KERNAL's
  vectors back on exit.
- **Screen state is coherent.**  VIC border / background /
  `$D018` charset mode / `$0286` (CHRCOLOR) all reflect the
  current theme.  The KERNAL's screen-editor state (line
  pointers, cursor position) is kept in sync with CSE's cursor
  so the KERNAL can resume where CSE left off.
- **No inherited junk.**  Values that BASIC's `SYS` or a
  previous user-code run might have left in well-known
  locations (a stale text colour, keys still queued) are reset
  before user code can observe them.

The rule-of-thumb statement: **user code that does not
explicitly configure colour, cursor, or screen mode must see
whatever the current CSE theme is — not BASIC defaults, not
garbage from a previous run.**  Anywhere CSE overrides a
KERNAL variable for its own use (e.g. `$CC` = 1 to disable the
KERNAL cursor so CSE can manage its own) it must either
restore the KERNAL value before the user gains control, or
document the override as part of the user-code contract.

The KERNAL cells and hardware registers CSE writes, and when, are
listed in [userland_contract.md § 2](userland_contract.md#2-state-contract);
the stack page the user's program shares with CSE in
[userland_contract.md § 4](userland_contract.md#4-stack-contract).
