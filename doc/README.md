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
Judgement calls are expected — not every one-line fix needs a full
seven-step cycle — but the bias must always be toward following the
process.  Changes that affect design intent, interfaces, test
coverage, or documentation require the full Method.  When in doubt,
follow the steps.

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

**Step 4 — Implementation.**  Tests are written first to match the
documentation (they will fail — this is expected).  Code is then
written to match both the documentation and the tests.  If
implementation requires unexpected significant changes outside the
original scope, a Scope Creep discussion is triggered:
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

## DDD Maintenance

The DDD Method protects the corpus during active development.  DDD
Maintenance is the complementary recurring process that catches drift,
gaps, and decay that no single change introduced — or that predates
the DDD System entirely.

**Trigger:** at each project milestone, before the milestone commit.

**Audit scope:**

1. **Template conformance** — all documents in a templated category
   conform to their template.
2. **Ownership completeness** — every file in the repository is claimed
   by exactly one document.  Unclaimed files are corpus gaps.
3. **Doc-code fidelity** — each module doc matches its source file:
   function signatures, ZP addresses, algorithms, clobber rules.
4. **Cross-reference integrity** — all links in the corpus resolve:
   no broken targets, no stale links pointing to renamed or removed
   sections, no missing links where a concept is referenced but not
   linked to its definition or owner.
5. **Glossary health** — all terms used across the corpus are defined;
   no stale or orphaned entries.
6. **TODO hygiene** — completed items checked off; stale items removed;
   Ideas and Planned items reflect current intent.
7. **Test contract health** — xfails reviewed: graduated to bugs or
   confirmed still expected; all documented modules have a test
   contract or an explicit reason they don't.
8. **User manual fidelity** — the root `README.md` is the user
   reference manual linked from the splash screen.  It is not a
   corpus document (it owns no code), but it derives from corpus
   documents: `assembler_syntax.md`, `modules/repl.md`,
   `modules/editor.md`, `modules/debugger.md`, `modules/expr.md`,
   `memory_design.md`.  Verify that every command, directive,
   addressing mode, and key binding listed in the README matches
   the current code as documented in those source documents.

**Output:** a DDD Maintenance Report listing findings by category.
Mechanical corrections (broken links, stale comments, formatting)
that don't affect design intent may be fixed inline.  Substantive
findings become TODO items and go through the DDD Method.

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

Document categories that appear more than once in the corpus have a
**template** in [`doc/templates/`](templates/README.md).  Every
document of that category must conform to its template.  The template
is the authoritative definition of the form — the description here is
a summary only.

**Module doc** (one file per module, `doc/modules/<module>.md`):
full template at [`doc/templates/module.md`](templates/module.md).
Sections: Owned files → Interface → Design → Caveats.

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
| Build-time options, toolchain, test binaries | `build_system.md` |
| Test method, architecture, conventions | `testing.md` |
| Directory structure, build pipeline | `project_layout.md` |

If you're unsure: ask "who needs to change when this fact changes?"
The answer points to the owner.

### 4. Explicit ownership

Every file in the repository is owned by exactly one document.
The owning document explicitly links to every file it owns and
names the relation.  Valid relations:

| Relation | Meaning |
|----------|---------|
| `implementation` | The file implements the behaviour this doc specifies. |
| `test contract` | The file verifies the interface this doc defines. |
| `generated` | The file is produced from data this doc is authoritative for. |
| `header` | The file exposes the C interface this doc describes. |

A file with no owning document is an undocumented file — a gap in
the Corpus.  DDD Maintenance must resolve all gaps.

This principle is what the **Owned files** section in module docs
(see [templates/module.md](templates/module.md)) implements.
Top-level documents without a template must carry an equivalent
ownership declaration wherever appropriate.

### 5. Natural reading order

Documents are ordered so each one depends only on documents listed
before it.  A reader going top-to-bottom never hits an undefined term.

### 6. Regular corpus maintenance

The corpus must be audited periodically, independent of feature work,
to catch drift and gaps that individual changes miss.
See [DDD Maintenance](#ddd-maintenance) for the full audit scope and trigger.

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
| [project_layout.md](project_layout.md) | Directory structure |
| [memory_design.md](memory_design.md) | Memory maps (PRG/CRT), ZP layout, screen switching |
| [build_system.md](build_system.md) | Toolchain, build pipeline, targets, options, test binaries |
| [testing.md](testing.md) | The TDD Method, py65 harness conventions |

### User-facing behaviour

| Document | Scope |
|----------|-------|
| [README.md](../README.md) | User reference manual (REPL commands, editor, assembler, debugger, memory map).  Not a corpus document — maintained via DDD Maintenance item 8. |
| [assembler_syntax.md](assembler_syntax.md) | Source language: labels, instructions, directives, expressions |

### Project management

| Document | Scope |
|----------|-------|
| [TODO.md](TODO.md) | Outstanding work: bugs, features, cleanup, architecture |
| [templates/README.md](templates/README.md) | Active document templates and their coverage |

### Authoritative data files (dev/)

| File | What it defines |
|------|-----------------|
| `dev/instruction_set.py` | OPCODES, MNEMONICS, OPERAND_PROFILES — the instruction set |
| `dev/hashes.py` | Hash functions (h6, h7), fingerprint formulas, HASH_T |
| `dev/mnemonic_tables.py` | Table generator: reads instruction_set.py, writes src/mn*_tables.s |
| `dev/dasm_tables.py` | Disassembler table generator: writes src/dasm_tables.s |

