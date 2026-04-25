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
(`m`, `d`, `f`, `t`) work on configurable ranges.  Auto-advance and
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

A two-pass 6502/6510/65C02 assembler with:

- Global and local labels, constants, forward references
- Full expression language (arithmetic, bitwise, lo/hi byte, grouping)
- Directives: `.org`, `.db`, `.dw`, `.str`, `.scr`, `.res`, `.align`,
  `.cpu`, `.const`
- Automatic ZP/ABS mode selection — no manual overrides needed
- Runtime CPU switching: legal-only 6502, 6510 with illegals, or 65C02

### The Disassembler

A compact bit-slice decoder that understands all three CPU modes.
Used by the `.` and `d` commands, it decodes the `aaabbbcc` opcode
structure without 256-entry lookup tables.

## Features

**REPL commands** — single-character, addressable (`AAAA:cmd`):

| Area | Commands | What they do |
|------|----------|--------------|
| Memory | `m` | Hex dump and in-place byte editing |
| Assembly | `.` `d` `a` | Single-line asm/disasm, block disassembly, full source assembly |
| Execution | `j` | JSR to address, show registers on return |
| Registers | `r` | View/edit A, X, Y, SP, and individual flags |
| Navigation | `@` `+` `-` `B` | Seek, advance, retreat, set block size |
| Files | `l` `s` `$` | Load/save PRG and SEQ files, disk directory/commands |
| Utility | `?` `i` `C` `u` | Expression calculator, memory map, colors, CPU mode |
| Debug | `b` `t` `o` `c` `g` | Breakpoints, trace, trace-over, continue, go |

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

The available modes are bounded at build time by `CPU_CEIL` (0=6502
only, 1=6502+6510, 2=all three) and `CMOS_SUPPORT` (includes 65C02
tables and code).  A 6502-only build excludes all illegal and CMOS
code, saving ROM space.

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
   with the KERNAL.  Disk I/O uses KERNAL calls.  `q` restores BASIC
   cleanly.  The NMI vector is intercepted for mode switching but
   the KERNAL's IRQ handler continues running (keyboard scan, jiffy
   clock).

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

Modules that never run concurrently (e.g. assembler vs disassembler)
can share ZP addresses.  See [memory_design.md § Zero Page Layout](memory_design.md#zero-page-layout).

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
See [feedback: ca65 char literals](../feedback_ca65_charlit.md).

The full mapping tables and rules live in
[cse_io.md § Character Encoding Reference](cse_io.md#character-encoding-reference)
— that is the single source of truth.

### 4. CPU-specific code must be compile-time gated

Code that is specific to a CPU target (6502, 6510, 65C02) must be
excluded at compile time via `.ifdef` — not gated at runtime.  The Makefile defines `CMOS_SUPPORT` for
65C02 builds and `CPU_CEIL` (0/1/2) for all targets.  A 6502
build must not contain 65C02 instruction paths, tables, or
decode logic.  This keeps the binary small on constrained targets.

**Current status:** implemented.  The mnemonic classifier uses
compile-time selection (mn6 vs mn7).  The assembler (`.ifdef
CMOS_SUPPORT`), disassembler (`.ifdef CMOS_SUPPORT` +
`.ifndef CPU_6502`), and debugger step logic (`#ifdef CMOS_SUPPORT`)
all use compile-time gating.  Runtime `asm_cpu` checks remain within
guarded blocks for 6510 vs 65C02 distinction.

### 5. Don't get in the KERNAL's way — user code sees a working C64

User programs launched from the REPL (via `j`, `g`, `t`, `o`)
are expected to use the C64 KERNAL as their I/O layer, much as
a modern program uses its host terminal.  A user program's
`JSR $FFD2` is the equivalent of `write(1, …)` on Unix: it
must land on the REPL screen at the current cursor position,
with the current CSE theme colour, and it must work from the
very first character without the user having to re-initialize
anything first.

Concretely, CSE must ensure that at every moment user code
could start running:

- **KERNAL vectors are the real KERNAL.**  $0314/$0316/$0318
  (IRQ/BRK/NMI) are either the stock KERNAL addresses or
  CSE-installed handlers that *delegate to the KERNAL path*
  for anything they don't themselves use.  The debugger patches
  $0316 for BRK capture, and restores it on exit.
- **Screen state is coherent.**  VIC border / background /
  $D018 charset mode / `$0286` (CHRCOLOR) all reflect the
  current theme.  The KERNAL's screen editor invariants
  ($D1/$D2 line pointer, $F3/$F4 color pointer, cursor
  position at $D3/$D6) are kept in sync via `io_sync` so
  the KERNAL can resume where CSE left off.
- **No inherited junk.**  Values that BASIC's `SYS` or a
  previous user-code run might have left in well-known
  locations (hardware stack residue, $0286 stale colour,
  $0277 keyboard buffer crud) are reset before user code
  can observe them.

The rule-of-thumb statement: **user code that does not
explicitly configure colour, cursor, or screen mode must see
whatever the current CSE theme is — not BASIC defaults, not
garbage from a previous run.**  Anywhere CSE overrides a
KERNAL variable for its own use (e.g. $CC=1 to disable the
KERNAL cursor so CSE can manage its own) it must either
restore the KERNAL value before the user gains control, or
document the override as part of the user-code contract.

**Current status:** fully audited 2026-04-08; revised for the
Phase 18 design 2026-04-17.  Every kernal location CSE touches
has been walked and verified.  The full state contract lives in
[userland_contract.md](userland_contract.md); summary here:

- Theme colour via `$0286` (CHRCOLOR) and VIC registers —
  refreshed by `restore_colors` before any user-code entry
  and after every return.  Phase 18 adds `vic_reset` for VIC
  text-mode normalisation.
- Startup SP reset to $FF (cold-init invariant).
- `$0316` (IBRK) and `$0318` (INMIV) — permanently owned by
  CSE, patched once by `setup_interrupts` (main.s) at cold init.
  Restored at exit via kernal RESTOR.
- `$FFFA`/`$FFFE` RAM shadows — also patched by
  `setup_interrupts` to early-entry handler labels (no separate
  trampolines).  See [main.md § setup_interrupts](modules/main.md).
- NMI dispatch routes on `in_userland` (main.s flag): swallow
  in kernel mode; break-into-debugger in userland.
- `$D018` charset mode — forced to $16 (lowercase/uppercase) by
  `vic_reset` on every userland → kernel transition, called from
  `hygiene_after_userland` in `handler_finalize` (main.s).  User
  code is free to change it during its run; state is snapped back
  on exit.
- `$D1/$D2`, `$F3/$F4`, `$D3/$D6` (kernal screen-editor state)
  — `io_sync` keeps them in lockstep with CSE's cursor.
  `cmd_jmp` emits a newline before rts'ing to `main_loop` so
  the user's first CHROUT lands on a fresh row;
  `hygiene_after_userland` calls `io_sync` on exit.
- `$CC` cursor flag — re-asserted to 1 by `hygiene_after_userland`
  on every userland → kernel transition.  Hardware kernal cursor
  stays disabled; CSE manages its own.
- `$C6` keyboard buffer count — zeroed by `cmd_jmp` before the
  userland run (so user code's first `GETIN`/`CHRIN` sees an
  empty queue) and by `hygiene_after_userland` on return (so
  keystrokes typed during the run don't leak into the REPL).
- `$0291` (SHIFT+C= lock) — re-asserted to $80 by
  `hygiene_after_userland` to keep the charset-toggle key combo
  disabled even if userland cleared it.
- Hardware stack — user code sees ~240 B free; user must leave
  64 B of headroom for kernel re-entry on break.  See
  [memory_design.md § Stack contract](memory_design.md#stack-contract)
  and [userland_contract.md § 4](userland_contract.md#4-stack-contract).
  The two-image swap (formerly required for `c`-from-stepped-
  subroutine correctness) is retired; the new contract guarantees
  the stack page is preserved naturally because the kernel never
  pushes below the user's SP.
