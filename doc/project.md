# CSE — Project Goals and Description

## What Is CSE?

CSE (C64 Screen Editor) is an integrated assembler development
environment for the Commodore 64.  It also runs on the C128 in C64
mode, with 65C02 support for the 8502 CPU.

It is built for programmers who want to **sketch ideas fast and play
with them as they go** — write a few lines of code, assemble, run,
poke at registers, tweak a byte, re-run.  The entire cycle happens
on the C64 itself, with no cross-development toolchain required.

CSE combines the workflow of **MasterSeka** (immediate single-line
assembly, integrated editor, fast iteration) with the power of a
**radare2-style REPL** (addressable commands, hex editing, expression
calculator, memory inspection, block operations).

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
- **Debug** — call subroutines with `j`, inspect registers on return
  *(breakpoints, stepping, and watchpoints are planned)*

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
| Block ops | `f` `>` `/` | Fill, transfer, search *(planned)* |

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

1. **Minimal footprint.**  Every byte of CSE is a byte the user can't
   use for their project.  Code is hand-optimized 6502 assembly where
   it matters.  ROM-ready architecture (no self-modifying code) enables
   a future cartridge build where CSE costs zero RAM for code.

2. **Maximum workspace.**  The user's mental model: "my program lives
   at $0800 and up."  CSE stays out of the way.  The `i` command shows
   exactly what's free.

3. **Fluent interaction.**  If you know MasterSeka or radare2, CSE
   feels immediately familiar.  Short commands, screen-as-buffer,
   edit-in-place.  No modes to memorize beyond REPL and editor.

4. **C64 keyboard is the only input device.**  Every character used
   in source syntax, commands, and expressions must be typeable on
   the unmodified C64 keyboard.  This is why OR is `£` (not `|`),
   XOR is `^` (the ↑ key), and labels have no underscore.

5. **KERNAL-friendly.**  CSE completely replaces BASIC but cooperates
   with the KERNAL.  Disk I/O uses KERNAL calls.  `q` restores BASIC
   cleanly.  The NMI vector is intercepted for mode switching but
   the KERNAL's IRQ handler continues running (keyboard scan, jiffy
   clock).

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

### 3. CSE uses shifted PETSCII (lowercase mode)

The screen operates in VICII charset 2 (shifted / "business" mode).
In this mode, PETSCII $41–$5A are lowercase a–z and $C1–$DA are
uppercase A–Z.  The KERNAL returns $41–$5A for unshifted keypresses
and $C1–$DA for shifted.  `read_line` preserves this distinction.
Screen codes follow the same convention: $01–$1A = lowercase,
$41–$5A = uppercase.

All internal text processing — command parsing, hex input, mnemonic
matching, source text — uses these PETSCII values directly.  ca65
character literals follow the same mapping: `'a'` = $41, `'A'` = $C1.

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
all use compile-time gating.  Runtime `al_cpu` checks remain within
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

**Current status:** fully audited 2026-04-08.  Every KERNAL
location CSE touches has been walked and verified:

- Theme colour via `$0286` (CHRCOLOR) and VIC registers —
  refreshed by `restore_colors` before any user-code entry
  and after every return.
- Startup SP reset.
- `$0316` BRK vector — saved/restored by `dbg_enter` around
  the user-code window.
- `$0314` IRQ and `$0318` NMI — never touched directly; NMI
  routes through the `$FF00` trampoline which delegates to
  the stock KERNAL when `dbg_running` is clear.
- `$D018` charset mode — restored to lowercase by
  `run_user` after `dbg_enter` returns.
- `$D1/$D2`, `$F3/$F4`, `$D3/$D6` (KERNAL screen-editor
  state) — `io_sync` keeps them in lockstep with CSE's
  cursor; `cmd_jmp` / `cmd_step` both call `newline` before
  `run_user` which calls `io_sync`.
- `$CC` cursor flag — `run_user` restores it to 1 after
  `dbg_enter` returns, in case user code re-enabled the
  KERNAL cursor.
- `$C6` keyboard buffer count — `run_user` zeroes it before
  `dbg_enter` so user code's first `GETIN`/`CHRIN` sees an
  empty queue, not user keystrokes typed ahead while
  issuing the command.
- Hardware stack — user code sees ≥ 239 B free.  See
  [memory_design.md § Stack budget](memory_design.md#stack-budget).
  The `c`-from-stepped-subroutine corner case is the
  documented limit (open BRK TODO).
