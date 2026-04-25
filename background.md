# CSE — Background

Long-form context for the project: what CSE is, who it's for, why it
exists, how it compares to its peers, and what keeps it honest.
Complements the user-facing [README](README.md) (reference manual) and
the [corpus](doc/README.md) (authoritative technical specification).

---

## What CSE is

CSE (C64 Screen Editor) is an integrated assembler development
environment that runs natively on the Commodore 64, with C128 and 65C02
support. Editor, assembler, disassembler, hex monitor, expression
calculator, and step debugger share a single screen and a single
command grammar. The screen is the command buffer: every line is
executable, every address is reachable by typing it, and the loop from
*I want to try something* to *I am watching it run* has no build step
in the middle.

It combines the immediacy of MasterSeka (single-line assembly,
integrated editor, fast iteration) with the addressable REPL idiom of
radare2 (short commands, `AAAA:cmd` addressing, block operations,
screen-as-buffer) — on the real machine, using only the C64 keyboard.

## Why CSE exists

CSE was born from a specific pedagogical problem: how do you give a
child a computer to learn programming on, without also giving them a
gaming console, a social network, and an infinite feed?

The modern default answer is a Raspberry Pi running Python. It works,
and it teaches real programming, but it buys breadth at the cost of
transparency — the learner wields a large world before understanding a
small one. Package managers, operating system layers, browser tabs, an
editor with a plugin ecosystem; the *computer itself* is hidden under
several kilometres of abstraction the learner has no need for yet.

The older answer was a Commodore 64 running BASIC. It had the right
shape — one machine, one focus, one user — but the wrong language.
BASIC hides the CPU behind an interpreter, which is the very thing the
learner should be able to see. The classic "BASIC first, then assembly
later" on-ramp required an unlearning step precisely where the mental
model should be getting sharper.

CSE is the third answer. Drop a learner in front of the C64 with a
6502 book and the CSE cheat sheet, and the entire computer fits in
their head. 64 KiB of RAM they can read all of. Fifty-six documented
instructions on a documented CPU. A memory map that prints on one page.
A screen that is literally the command buffer. No browser, no
notifications, no package manager, no operating system update nagging.
The scope is finite, the ceiling is visible, and the computer stops
when the user does.

This focus — the computer as a single-purpose instrument with no
distractions — is what makes the C64 a uniquely good teaching machine
in 2026. It is also, not coincidentally, what makes it a good sketchpad
for anyone who already knows how to program.

## One environment, two audiences

The same properties that make CSE a good first environment make it a
good sketchpad for a seasoned developer. This is the duality the
project refuses to compromise on.

**For the seasoned developer**, CSE is an immediate-mode 6502 REPL
with no toolchain, no build step, no context switch back to a host OS.
Sketch a routine, poke at the hardware, try three variants of an inner
loop, watch the cycle count change, get out. The command vocabulary is
MasterSeka's short verbs with radare2's addressable grammar; the
assembler has everything a sketch needs (labels, expressions, ZP/ABS
auto-encoding, forward references, directives for bytes, words,
strings, reserved space, alignment); the disassembler and debugger
expose the real CPU state in real time. For experiments where the
question is *what does this sequence of instructions actually do on the
bare metal*, CSE answers in the tightest loop any 6502 environment
currently offers.

**For the learner**, CSE is a first environment whose surface area is
the whole language to be learned. There is no IDE to master before
getting to the subject. Type `?` to calculate, `i` to see the memory
map, `m` to see the bytes at an address, `.` to assemble one
instruction, `t` to step one CPU cycle forward. The cheat sheet *is*
the environment. A 6502 book, the cheat sheet, and a few hours is
enough to start writing programs that do things on the screen.

The project commits to serving both without splitting the surface. No
"beginner mode" and "advanced mode." No dumbed-down surface an expert
has to work around, and no expert-only feature that leaves a beginner
lost. Features that would help one audience at the cost of the other do
not ship. The reasoning: a beginner and an expert both benefit from a
computer whose surface area fits in their head. The expert isn't paying
a tax on the learner's behalf; the learner isn't being talked down to.
The same design serves them because the constraint — *hold the whole
thing in mind* — is the same constraint in both cases.

This is where CSE diverges from almost every other tool in the space.
Cross-development toolchains, power-user reverse engineering
frameworks, and modern teaching environments each solve one audience
well. CSE argues that the C64 is rare in 2026 precisely because it
lets one tool serve both.

## How CSE compares to its peers

CSE sits in a crowded but oddly bimodal landscape. C64 development
tooling has historically split between **native on-machine tools**
(fast feedback, cramped by 64 KiB) and **modern cross-development
toolchains** (powerful but off-machine). CSE's distinguishing move is
to pull the modern REPL idiom back onto the bare metal.

### Against native C64 peers

The direct ancestors are *MasterSeka*, *SMON*, and the *Turbo
Assembler* family (Turbo Assembler / Turbo Macro Pro).

MasterSeka pioneered the single-line-assembly-and-run loop CSE
explicitly inherits — type a line, assemble it, see the bytes, keep
going. But MasterSeka is essentially an editor with an assembler
stapled on: no addressable command REPL, no block operations, no step
debugger, no expression calculator.

SMON is the classic C64 machine-language monitor — excellent at
disassembly, memory editing, and simple single-line assembly, but it
is a monitor, not an authoring environment. There is no source editor,
no two-pass assembler with symbols, no way to iterate on a multi-line
routine in source form.

Turbo Assembler is a more powerful source assembler with macros and
better symbol handling, but it treats the machine-code monitor as a
separate tool the user leaves the editor to reach. The edit-run-inspect
loop crosses program boundaries.

CSE collapses those worlds into one surface. The same screen is
editor, assembler, disassembler, hex editor, expression calculator,
register inspector, breakpoint debugger, and disk shell. The `.`
command assembling one line at the cursor is MasterSeka's ethos; the
`AAAA:cmd` addressing and block operations are new territory for a
native tool.

### Against cartridge monitors

*Final Cartridge III*, *Action Replay*, the *Ultimate 64* freezer, and
*JiffyDOS*-adjacent tools offer machine-language monitors with
disassembly, memory editing, and simple single-line assembly. CSE's
REPL surface overlaps heavily — `m`, `d`, `.`, `j`, `r`, `b`, `t`,
`c` all have counterparts — but cartridge monitors don't integrate a
full source editor or a two-pass assembler with symbols, forward
references, and directives. They are inspection and patch tools, not
authoring tools.

CSE's editor-plus-assembler-plus-debugger integration is what makes it
a development environment rather than a monitor. The ROM-ready,
no-self-modifying-code architecture also telegraphs where this is
going: CSE is built to become one of those cartridges eventually,
costing the user zero RAM for code.

### Against radare2 (and modern REPLs)

CSE borrows radare2's addressable command grammar (`addr:cmd`,
block-size-aware operations, terse single-character verbs), its
screen-as-buffer philosophy, and its fluent seek/block model. The
expression evaluator with full precedence, the shared grammar across
inspection and editing, and treating every line as re-executable are
all radare2 DNA.

The differences are constraints. Radare2 runs on a host with gigabytes
of RAM, a real keyboard, and scripting via Python or JavaScript. CSE
runs in a few KiB of code on a machine with 64 KiB total, uses only
characters typeable on the unmodified C64 keyboard (hence `£` for OR,
`^` for XOR, no underscores in labels), and has no scripting layer.
Radare2 is a reverse-engineering Swiss Army knife; CSE is an authoring
environment that happens to borrow its verbs.

### Against cross-development toolchains

The modern C64 programmer's default stack is *ca65/cc65*, *ACME*,
*64tass*, or *KickAssembler*, combined with *VICE* for emulation and
debugging and a host-side editor (often *CBM prg Studio*, *Relaunch64*,
or VS Code with plugins). Those toolchains dominate CSE on raw
assembler power — macros, scopes, structs, linker segments, library
ecosystems, 64-bit host CPUs doing instant builds — and on debugger
fidelity via VICE's remote-monitor protocol.

Where CSE wins is *feedback latency* in the original sense: zero
context switch, zero toolchain, zero file-system round trip. Edit,
assemble, run, poke, re-run, all on one screen with no build step.
For sketching ideas and playing with the hardware, this is
qualitatively different from a cross-dev loop. For shipping a 40 KB
demo, a modern cross-assembler is the correct tool. CSE does not
contest that ground.

### Against other integrated C64 IDEs

*CBM prg Studio* and *Relaunch64* are the closest modern analogues
conceptually — integrated editor + assembler + emulator — but they run
on a PC and drive VICE. CSE's niche is the narrow intersection of
"integrated environment" and "runs on the real machine." That
intersection was populated in the 1980s and has been almost empty
since. CSE is deliberately reviving it, informed by three decades of
REPL and IDE design that did not exist when MasterSeka shipped.

### Against BASIC on the same machine

Worth naming explicitly, because BASIC is the obvious on-ramp for a
learner on a C64. BASIC is a better first language for getting
something on the screen quickly — `PRINT "HELLO"` works, and that is
the correct first experience for some learners.

CSE makes a different bet. Rather than teaching an interpreter first
and revealing the machine later, it puts the learner directly in front
of the CPU from day one. The trade-off is a steeper first few hours
(no `PRINT`, no `GOTO`; the learner must understand registers, memory,
and opcodes before anything happens) in exchange for a shorter total
path to genuine fluency: the mental model the learner builds on day one
is the model that will still be correct on year five. There is no
unlearning step.

### Net positioning

CSE trades raw assembler horsepower and ecosystem reach for tight
feedback, a unified surface, and a ROM-able footprint on the target
machine itself. Against native peers it is a generational jump in REPL
integration; against cross-dev toolchains it is a deliberate step back
into the machine for the ergonomic payoff; against cartridge monitors
it is an authoring environment rather than an inspection tool; against
BASIC on the C64 it is a bet on transparency over convenience.

## Design priorities in context

The full, corpus-authoritative list lives in
[doc/project.md § Design Priorities](doc/project.md#design-priorities).
The short version, with the reasoning this document has just built up:

- **Minimal footprint.** Every byte of CSE is a byte the user cannot
  use. ROM-ready architecture is not nostalgia — it is a commitment to
  a future build where CSE costs zero RAM for code.
- **Maximum workspace.** The user's mental model is "my program lives
  at `$0800` and up." CSE stays out of the way; `i` shows exactly
  what is free.
- **Fluent, immediate interaction.** No build step, no context switch;
  one grammar across editor, assembler, monitor, calculator, and
  debugger; no modes to memorize beyond REPL and editor.
- **C64 keyboard is the only input device.** Every syntax element must
  be reachable on the unmodified keyboard. This is what allows the
  tool and the machine to be the same surface.
- **KERNAL-friendly.** CSE replaces BASIC but cooperates with the
  KERNAL so that user code running under CSE sees a working C64, not
  a stripped-down environment.
- **Transparency.** CSE interposes nothing between the user and the
  CPU. No interpreter, no VM, no managed runtime. Every level — source,
  bytes, registers, memory — is inspectable and directly editable.
  This is the principle that rules out a "quick BASIC-like wrapper"
  and other design moves that would hide the thing the user came here
  to see.
- **One environment, two audiences.** CSE must serve both the learner
  and the seasoned developer without splitting the surface. No
  beginner mode, no expert mode. Features that would help one at the
  cost of the other do not ship.

## What keeps the promise honest

CSE is developed under **Document-Driven Development**. The `doc/`
tree is the source of truth for design intent, interfaces, and
behaviour; code implements the docs; tests prove the code matches.
Documentation is not a byproduct of the work, it is the work — the
`src/` tree is downstream of `doc/`, and the test suite is downstream
of both.

For both audiences this matters. For the learner, the printed cheat
sheet and the user manual are derived from the same corpus the code is
audited against (via DDD Maintenance item 8 — "User manual fidelity").
The paper on the child's desk does not lie to them. For the seasoned
user sketching an experiment, the interface contracts are specified
precisely enough that *what does this command actually do at the edge*
has a written answer.

Three standing processes protect this discipline. The **DDD Method**
governs planned change: update the doc first, analyse the delta
between doc and code, plan tests, implement, reconcile, commit.
**DDD/TDD Maintenance** sweeps the corpus at milestone boundaries for
drift — broken links, stale docs, untested exports, coverage gaps.
**Escape Analysis** handles any bug the tests missed by tracing it
back through test miss → contract miss → principle miss, so the same
class of bug cannot escape twice. The full method lives in
[doc/README.md](doc/README.md).

This is unusual for a 6502 assembler project and is a deliberate bet:
the long-term story for a tool serving a learner over years, or an
expert whose trust compounds with every session, is only as good as
its discipline against drift. CSE treats drift as the primary enemy.

## Getting started

Read the [README](README.md) for the reference manual — REPL
commands, editor keys, assembler syntax, memory layout.

Read a 6502 book alongside it. Any of the classics works; the CPU is
small enough that the choice barely matters.

Boot the machine. Type `?` for the expression calculator, `i` to see
the memory map, `.` to assemble one line. The rest you can find by
trying.
