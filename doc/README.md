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
- **Testable where it matters.**  Modules with clean interfaces
  (assembler, parser, symbol table, disassembler) have py65 tests.
  UI-facing code (REPL, editor) is verified by DDD audits and manual
  testing — the cost of simulating screen RAM and keyboard input
  outweighs the benefit.

### 5. Test contracts, not implementation

Tests verify the documented interface: given these inputs, expect
these outputs, this carry flag, this error code.  Tests do not
assert internal state (ZP scratch values, loop counters, intermediate
buffers) unless that state *is* the contract.

Example: the sticky-OR width rule (`$00 + $0000` → ABS) is a design
decision documented in assembler_syntax.md and expr.md.  Tests pin
it down because changing it would silently break user code.  But
*how* expr.s implements the OR (which ZP byte it uses, in what order)
is an implementation detail that tests must not depend on.

### 6. ZP is precious — use the stack for scratch

The 6502 requires zero page for indirect addressing (`(ptr),y`).
Every ZP byte used for scratch is a byte unavailable for pointers.

- **ZP** — pointers used with indirect addressing, hot inner-loop state
- **Stack** — scratch values (saved/restored via `pha`/`pla`)
- **BSS** — persistent state that doesn't need fast access

Modules that never run concurrently (e.g. assembler vs disassembler)
can share ZP addresses.  See memory_design.md § Zero Page Layout.

---

## Documentation Principles

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

If you're unsure: ask "who needs to change when this fact changes?"
The answer points to the owner.

### 4. Natural reading order

Documents are ordered so each one depends only on documents listed
before it.  A reader going top-to-bottom never hits an undefined term.

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
| testing.md | Test framework architecture, py65 harness, coding guidelines *(TODO)* |

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

---

## Remaining Documentation Work

### Done

- [x] DDD preface, principles, index (this file)
- [x] Project goals and description (project.md)
- [x] Architecture overview with layer diagram (architecture.md)
- [x] Module docs for all modules (doc/modules/)
- [x] Glossary extracted from root README (glossary.md)
- [x] Root README.md thinned to pointer
- [x] De-duplication: module details only in module docs

### Still needed

- [ ] Update project_layout.md (stale file list, line counts, test count)
- [ ] Update assembler_syntax.md (labels require colon, `.const` not `=`, verify directive list against asm_src.s)
- [ ] Update modules/symtab.md (local labels ARE implemented, remove "PLANNED" markers)
- [x] ~~Update repl_commands.md~~ — merged into modules/repl.md
- [ ] Update TODO.md (prune completed items)
- [ ] Verify: every directive in assembler_syntax.md is implemented in asm_src.s
- [ ] Verify: every ZP variable in module docs matches actual ZP layout
- [ ] Fix stale comment in asm_vars.s: `al_cpu` is 0=6502, 1=6510, 2=65C02 (not 0=NMOS, 1=65C02)
