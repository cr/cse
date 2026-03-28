# CSE Documentation

## Preface: Document-Driven Development

CSE is built under **Document-Driven Development (DDD)**: documentation is
the source of truth for design intent, interfaces, and behaviour.  Code
implements the docs; tests verify the code matches the docs.

```
  doc/        "what and why"    ← humans read and write here first
    ↓
  src/        "how"             ← implementation follows the docs
    ↓
  tests/      "prove it"        ← tests verify the code matches the docs
```

### Goals

1. **A human can understand the whole system** by reading the docs alone.
   The documentation must be complete enough that someone unfamiliar with
   the code can predict what the code does.

2. **An AI agent can work autonomously** from the docs.  Every interface
   contract, every data layout, every encoding rule must be written down
   explicitly — not left to be inferred from source.

3. **Disagreements are resolved by editing the doc first**, then fixing
   the code to match.  Never the reverse.

### Requirements

- **Terse.**  Say it once, say it precisely, move on.
- **Structured.**  Repeating patterns use repeating forms.
- **Complete.**  Every exported symbol, every ZP variable, every calling
  convention is documented.
- **Current.**  Stale docs are worse than no docs.  When code changes,
  the doc changes in the same commit.

---

## The DDD Method

All development work in this repository follows the DDD Method.
There are no exceptions.  There are no shortcuts.  Skipping steps
— even for seemingly trivial changes — is how documentation systems
die.  Every contributor, human or AI, must follow this process for
every change, every time.

**Step 1 — Documentation first.**  Update the relevant
documentation to describe the desired *state* — not the change, but
what the system should look like when the work is done.  This
creates a deliberate delta between documentation and code.  The
delta is the work to be done.  (Desired *changes* and their
rationale belong in `TODO.md`, not in the specification documents.)

**Step 2 — DDD Analysis.**  Before touching code, identify the
relevant documentation and compare it against the existing code
reality.  The analysis covers: documentation quality, coverage,
mismatches between documentation and code (including source comments
and docstrings), and recommends documentation improvements to be
made before proceeding.  The analysis must be presented for
discussion and approval.

**Step 3 — TDD Analysis.**  Defined in full in
[testing.md § The TDD Method](testing.md#the-tdd-method).  Identifies test gaps,
recommends test framework changes, and assesses automation
feasibility.  If the TDD Analysis reveals implications for the
intended code change, it must be discussed and approved before
proceeding.  The TDD Analysis must be included in the final report.

**Step 4 — Implementation.**  Code and test changes proceed as
designed.  If implementation requires unexpected significant changes
outside the original scope, a Scope Creep discussion is triggered:
the unplanned changes are presented for discussion and approval
before being put through the DDD Method recursively.  Recursion
terminates at the discretion of the approver.

**Step 5 — Differential DDD Analysis.**  After implementation, a
second DDD Analysis identifies all documentation discrepancies
created by the development work.  The required documentation
updates are then implemented.

**Step 6 — Commit.**  All changes — documentation, tests, and
code — are committed to version control.

**Step 7 — Final DDD Report.**  A summary of all changes made to
the repository (documentation, tests, code), highlighting any
unplanned changes and suggesting future improvements.

The DDD Method does not have an opinion about how the plan that
triggers it was created.  It starts with a plan and ends with a
report.

---

## Principles

### 1. Layered depth

Each topic has one document.  Within that document, information flows
from general to specific:

```
  Purpose          — one sentence: what is this module for?
  Interface        — how do callers use it? (inputs, outputs, side effects)
  Design           — how does it work internally? (algorithms, data layouts)
  Caveats          — what surprises lurk? (encoding quirks, clobber rules)
```

### 2. Shared descriptive forms

The same kind of thing is always described the same way.

**Module doc** (one file per module, `doc/modules/<module>.md`):

```
# module_name — One-Line Purpose

## Interface
- `function_name(args)` — what it does
**Depends on:** list of imported modules

## Design
How it works internally.

## Caveats
Encoding quirks, clobber rules, etc.
```

Module docs live in `doc/modules/` and are reached through
[architecture.md](architecture.md).  They are not listed in this
index.  Crossing into `doc/modules/` means crossing into technical
specification: the level of detail needed to implement code and
write tests.

**Module summary** (used in architecture.md — one line only, links to module doc):

```
| [module_name](modules/module.md) | one-line purpose |
```

**ZP / BSS variable table** (used in API docs):

```
| Address | Name     | Size | Purpose                 |
|---------|----------|------|-------------------------|
| $xx     | var_name | N    | one-line description    |
```

**Function spec** (used in API docs):

```
### function_name
**In:**  register/ZP inputs
**Out:** register/ZP outputs, carry flag meaning
**Clobbers:** what it destroys
**Notes:** caveats, preconditions
```

**Test case form** (used in test docs):

```
{ source, expected_bytes, expected_errors }
```

### 3. Single source of truth

Every fact has exactly one authoritative location.  If information
appears in two places, one of them is a derived copy and must say so.
When something changes, you fix it in one place — never two.

When data from a document is duplicated into code or another file,
the owning document must list its dependants so that changes
propagate.  Format:

```
**Dependants:** Makefile (_THEME_MAP), src/screen.s (color constants)
```

The dependant is responsible for staying in sync with the owner.
The owner is responsible for listing who depends on it.

This is why module details live in per-module docs, not in the
architecture overview.  The architecture doc links to the module docs;
it does not duplicate their content.

**Where does this fact live?**  Decision tree:

| You're documenting... | It goes in... |
|----------------------|---------------|
| What a user types (syntax, commands, directives) | `assembler_syntax.md` or `modules/repl.md` |
| How a directive/command behaves across passes | `assembler_syntax.md` (it's the language spec) |
| How a module works internally (algorithms, buffers, ZP) | `doc/modules/<module>.md` |
| Which modules exist and how they connect | `architecture.md` (one-line summaries, links only) |
| A term's definition | `glossary.md` |
| Memory addresses and layout | `memory_design.md` |
| Project goals, components, priorities | `project.md` |
| A bug, missing feature, or cleanup task | `TODO.md` |
| Instruction set data (opcodes, profiles, modes) | `dev/instruction_set.py` |
| Hash parameters and table generation | `dev/hashes.py` |
| Build-time options (CPU, theme) | `Makefile` (mechanism) + relevant module doc (spec) |
| Test method, architecture, conventions | `testing.md` |
| Directory structure, build pipeline | `project_layout.md` |

If you're unsure: ask "who needs to change when this fact changes?"
The answer points to the owner.

### 4. Natural reading order

Documents are ordered so each one depends only on documents listed
before it.  A reader going top-to-bottom never hits an undefined term.

### 5. Test contracts, not implementation

Tests verify the documented interface, not internal state.
See [testing.md § The TDD Method](testing.md#the-tdd-method).

### 6. ZP is precious — use the stack for scratch

- **ZP** — pointers for indirect addressing, hot inner-loop state
- **Stack** — scratch values (saved/restored via `pha`/`pla`)
- **BSS** — persistent state that doesn't need fast access

Modules that never run concurrently (e.g. assembler vs disassembler)
can share ZP addresses.  See [memory_design.md § Zero Page Layout](memory_design.md#zero-page-layout).

### 7. All instructive characters must be typeable on the C64 keyboard

No syntax element (operator, delimiter, directive prefix) may use a
character that the C64 keyboard cannot produce.

### 8. CSE uses shifted PETSCII (lowercase mode)

The screen operates in VICII charset 2 (shifted / "business" mode).
In this mode, PETSCII $41–$5A are lowercase a–z and $C1–$DA are
uppercase A–Z.  The KERNAL returns $41–$5A for unshifted keypresses
and $C1–$DA for shifted.  `read_line` preserves this distinction.
Screen codes follow the same convention: $01–$1A = lowercase,
$41–$5A = uppercase.

All internal text processing — command parsing, hex input, mnemonic
matching, source text — uses these PETSCII values directly.  cc65
character literals follow the same mapping: `'a'` = $41, `'A'` = $C1.

---

## Document Index

### Project

| Document | Scope |
|----------|-------|
| [project.md](project.md) | What CSE is, components, features, design priorities |

### System overview

| Document | Scope |
|----------|-------|
| [architecture.md](architecture.md) | Module map, dependency graph, module summaries → `modules/` |
| [glossary.md](glossary.md) | Shared terminology (instruction, operand, label, ZP, PETSCII, ...) |
| [project_layout.md](project_layout.md) | Directory structure, build system, test infra |
| [memory_design.md](memory_design.md) | Memory maps (PRG/CRT), ZP layout, screen switching, ROM rules |
| [testing.md](testing.md) | The TDD Method, test framework architecture, py65 harness |

### User-facing behaviour

| Document | Scope |
|----------|-------|
| [assembler_syntax.md](assembler_syntax.md) | Source language: labels, instructions, directives, expressions |

### Project management

| Document | Scope |
|----------|-------|
| [TODO.md](TODO.md) | Outstanding work: bugs, features, cleanup, architecture |

### Authoritative data files (dev/)

| File | What it defines |
|------|-----------------|
| `dev/instruction_set.py` | OPCODES, MNEMONICS, OPERAND_PROFILES — the instruction set |
| `dev/hashes.py` | Hash functions (h6, h7), fingerprint formulas, HASH_T |
| `dev/mnemonic_tables.py` | Table generator: reads instruction_set.py, writes src/mn*_tables.s |
| `dev/dasm_tables.py` | Disassembler table generator: writes src/dasm_tables.s |

