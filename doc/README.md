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

*Cycle-detection rule.*  When the same procedure (or section of
documentation) is modified three or more times in one session for
the same concern, the spec is unclear — pause and clarify with the
approver before iterating again.  Each repetition is evidence the
contract has not been pinned, not a refinement of the
implementation.  Continuing burns commits and obscures the
inflection point at which the contract diverged from the design.

**Step 5 — Differential DDD Analysis.**  After implementation, a
second DDD Analysis identifies all documentation discrepancies
created by the development work.  The required documentation
updates are then implemented.

**Step 6 — Commit.**  All changes — documentation, tests, and
code — are committed to version control.

*Granularity rule.*  One fix per commit unless the fixes are
trivially co-dependent (one cannot land without the other in the
same diff).  Independent fixes that happen to land in the same
session belong in separate commits: each easier to bisect,
easier to revert individually, easier to credit in a changelog.
Bundling unrelated fixes erases the "which change broke this"
trail without saving any work.

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

## TDD Maintenance

DDD Maintenance audits prose against code.  **TDD Maintenance** is
its counterpart for the executable half of the Corpus: a periodic
audit of the test suite against the contracts it's supposed to
verify.  Tests drift the same way docs do — they accrete during
feature work, duplicate each other, couple to implementation,
quietly cover one cell of a matrix while claiming to cover the
whole surface.  TDD Maintenance walks the corpus module by module
and tightens the test contracts.

**Trigger:** at each project milestone (shared with DDD
Maintenance), and reactively whenever an Escape Analysis amends
a [testing.md](testing.md) principle — the new principle may
reveal gaps across modules that weren't previously considered
principle-relevant.

**Audit scope:**

1. **Contract-to-test mapping** — every exported symbol in every
   module doc has a matching correctness test OR a vocal skip.
   Walk each module's `.export` / `.exportzp` list; walk each
   documented RODATA / BSS / ZP export; each must resolve to a
   test name or a skip.  No silent gaps.

2. **Test-file naming** — one test file per source module, name
   mirrors the source file (`src/foo.s` → `tests/unit/test_foo.py`
   or `tests/integration/test_foo.py`).  Historical names get
   renamed; cross-module tests move to the module they actually
   cover.

3. **Test-bundle production parity** — every production build
   variant (Makefile `_*_DEFS`) has a matching test bundle.  No
   `.ifdef`-guarded code path lives behind a missing test config.
   This is [testing.md § Principle 10](testing.md); audit
   enforces it across the corpus.

4. **Harness dependency direction** — every test stub links real
   lower-layer modules; any mock of an L<N> symbol from an L<N>
   (or below) test bundle is a dependency-direction violation.
   Stubs provide only linker scaffolding (`__CODE_RUN__`, test
   entry points) — never re-implement code that exists as a real
   leaf module.

5. **Mock scope** — stubs are minimal.  A stub that duplicates a
   real module's behaviour (even a small one) risks mock/prod
   divergence.  If the real module can link into the bundle, it
   does.

6. **Duplicate coverage** — two tests asserting the same contract
   clause: keep the stronger, retire the weaker with a pointer
   comment naming its replacement.  Pointer comments stay so
   future greps still land on the surviving coverage.

7. **Implementation coupling** — tests that assert internal
   state (exact byte offsets between related labels, ZP scratch
   values, internal table contents consumed only within the
   module) are demoted to vocal skips (Pattern B) or deleted.
   [testing.md § Principle 2](testing.md) is the authority.

8. **Non-contractual retention** — tests that aren't strictly
   contractual stay only if they catch a distinct regression
   class the contract-direct tests don't.  Each such test carries
   a docstring justifying its existence.  If the justification
   can't be written, the test goes.

9. **Skip hygiene** — every `@pytest.mark.skip` / `xfail` has a
   reason string matching Pattern A (out-of-tier) / Pattern B
   (subsumed) / Pattern C (cannot be enforced at any unit tier)
   from [testing.md § Principle 9](testing.md).  No silent `pass`
   bodies, no TODO skips, no unexplained `xfail(strict=False)`.

10. **Risk preamble coverage** — every high-impact gap (a skip
    whose regression could ship silently) has a dated preamble
    `⚠ TOP/HIGH/LOW-RISK L<N> GAP (per coverage audit YYYY-MM-DD)`
    with a named enforcement mechanism (VICE, code review,
    integration tier).  Expired preambles are refreshed or closed
    during the audit.

11. **Partial-result contracts have position-pinning tests** —
    per [testing.md § Principle 13](testing.md).  For every
    module, inventory the functions whose success value depends
    on ancillary state (input-pointer position, counters, residual
    markers) in addition to their return code: parsers, tokenizers,
    stream consumers, partial readers, bulk operations with
    progress counters.  Each must have a test class (or equivalent
    section) that parametrises representative inputs and asserts
    the ancillary state, not just `(rc, value)`.  A partial-result
    function with no position-pinning witness is a findings entry —
    either add the tests inline or flag as a coverage gap.

    Direct `TestStopContract`-style tests and transitive hot-loop
    pinning (Principle 13 § Transitive pinning via hot-loop
    composition) both count as witnesses.  When claiming transitive
    pinning, the vocal skip must name the hot-loop caller explicitly.

    **Dead-code sweep gotcha.**  When auditing whether a symbol has
    callers, grep for all three forms: direct `jsr <symbol>` /
    `jmp <symbol>`, the `.import <symbol>` declaration, AND the
    symbol's appearance as a pytest harness lookup
    (`emu.sym("<symbol>")` or `syms.<symbol>`).  A symbol can look
    dead by direct-call search alone when test harnesses or
    conditional code paths keep it alive.  False-negative audits
    create retirement proposals that would break builds or tests.

**Output:** a TDD Maintenance Report listing findings by category.
Mechanical corrections (rename test file, retire duplicate, move
misplaced test class to its module's file, update stale stub
comment) may be applied inline.  Substantive findings become
either TODO items (follow through via DDD Method) or new Escape
Analysis candidates (if a bug is suspected).

**Relationship to the other processes:**

TDD Maintenance is the test-corpus twin of DDD Maintenance and
inherits the same rhythm.  Escape Analysis produces principle
amendments; TDD Maintenance propagates them.  The DDD Method
continues to use TDD Analysis (step 3) for per-change test
planning — TDD Maintenance is the orthogonal periodic check that
nothing has drifted since the last audit.

---

## Escape Analysis

The DDD Method protects the Corpus during planned change; DDD
Maintenance catches drift at milestone boundaries.  **Escape
Analysis** is the third entry point — reactive, invoked whenever a
bug is discovered that the test suite failed to catch.  Every such
bug is evidence that the Corpus was silent or ambiguous where it
should have been prescriptive.  Fixing only the bug wastes the
evidence; Escape Analysis turns the escape into a permanent
tightening of the Corpus.

**Trigger:** a bug found in production, by manual inspection, by
a new contributor asking "what should this do?", or by any other
route that exposes behaviour the test suite silently accepts but
should have rejected.  Applies equally to functional bugs, test-
harness bugs, and doc-code fidelity gaps.

**Process:**

1. **Capture the escape.**  Write a test that fails against the
   current code.  Confirm it fails for the right reason (the bug
   itself, not a harness quirk).  The failing test is the evidence.

2. **Trace to the test miss.**  Which existing test should have
   caught this?  Three cases:
   - A test exists but passes incorrectly.  The harness is lying
     about what it covers — mirror test, single-bundle coverage of
     a matrix contract, wrong build config, implementation-coupled
     assertion.  Fix the harness before moving on.
   - A test exists for an adjacent case but not this one.  The
     matrix was under-enumerated.  Extend the parametrisation.
   - No test covers the affected clause.  Proceed to step 3.

3. **Trace to the contract miss.**  Which doc clause should have
   prompted a covering test?  Three cases:
   - The clause exists but is ambiguous or prose-buried.  Rewrite
     for enumerability — replace narrative with tables where the
     contract has axes (asm_cpu × category, build-flag × mnemonic-
     class, etc.).
   - The clause is missing.  Add it.  The Corpus is incomplete
     until observable behaviour is documented.
   - The module has multiple variants (`.ifdef` or `-D` flag
     combinations) that the doc treated as one artifact.  Add a
     Variants table.  See `doc/modules/mn_classify.md` for the
     canonical shape.

4. **Trace to the principle miss.**  Which [testing.md](testing.md)
   principle, if applied, would have forced step 3's amendment?
   - If such a principle exists and was followed: the principle
     itself has an edge case it didn't cover.  Refine the principle.
   - If no such principle exists: add one.  This is the deepest
     amendment and prevents the entire class of bug, not just the
     instance.  Reference the specific escape in the new principle
     so future readers see the evidence that produced it.

5. **Sweep the corpus — two axes.**  The "same class of bug
   cannot escape twice" guarantee is only real if the class is
   actively hunted, not just the instance.  Sweep along both
   axes:

   **(a) Class-wide sweep.**  What other code in the corpus fits
   this bug's shape?  For a trailing-garbage bug in one REPL
   command, probe the other commands.  For an ifdef-gated reject
   path that was invisible, scan every `.ifdef` in the module.
   For a partial-result contract without position-pinning tests,
   inventory every partial-result function.

   **(b) Cross-module handoff sweep.**  When the fix introduces
   or revises a contract that depends on *ancillary state* — a
   ZP flag, a global variable, a register value at entry — audit
   every upstream caller for whether that state holds as the
   contract assumes.  A contract like "`log_open` auto-advances
   if `CUR_COL != 0`" silently depends on whoever sets `CUR_COL`
   before the call.  If some caller silently sets `CUR_COL = 0`
   (as `main.s`'s RETURN path did, pre-`d65a624`), the contract
   is defeated without any doc being wrong in isolation — the
   bug lives in the composition, not in either side.  For each
   piece of ancillary state the new contract reads: grep every
   write to that state in the call chain; verify each write
   produces a value consistent with the contract's assumption.

   Both sweep axes produce a **candidate list** — sites that share
   the bug's shape, callers whose state provision could defeat the
   contract, or principle proposals raised by the analysis.  The
   list is the input to step 6, not yet a commitment.

6. **Triage the sweep.**  Present the candidate list to the owner
   for scope triage *before* proposing amendments.  For each
   candidate, the triage answers: *in scope for this escape*,
   *queued as a separate `TODO.md` entry*, or *skip-worthy
   entirely*.  Triage produces three buckets:

   - **Mechanical sibling fixes** land in the same commit as the
     original escape.
   - **Non-mechanical siblings** become explicit `doc/TODO.md`
     entries naming the class and cross-referencing the principle.
     Flagged, not forgotten.
   - **Skip-worthy candidates** are dropped — surface-resemblant
     but not the same class.  The triage discussion is the record;
     no entry is filed.

   *Why this gate exists.*  Without it, every escape inflates into
   a multi-site refactor proposal whose cost dwarfs the original
   fix.  Empirically, ~80% of swept candidates trim to skip-worthy
   on triage; spending implementation effort before the gate is
   waste, and — worse — the sweep itself becomes a disincentive to
   do escape analyses thoroughly.

7. **Commit all amendments together.**  A single commit contains:
   the bug fix, the new test that would have caught it, the
   contract amendment, any testing.md principle amendment, the
   sweep findings (inline fixes or queued TODOs), and a commit
   message naming Escape Analysis explicitly so the log preserves
   the chain of reasoning.  The DDD Method's commit-granularity
   rule (one fix per commit) is suspended for Escape Analysis on
   purpose — the value of the closure is in seeing the bug fix,
   the missing test, and the contract/principle amendment land
   together as one auditable unit.

**Output:** a tighter Corpus.  The same class of bug cannot
escape twice — at the corpus level, not just at the reported
instance.  Patterns across escapes (noted in commit messages)
inform future DDD Maintenance audits.

**Relationship to the other processes:**

| Process | Trigger | Direction | Audits |
|---|---|---|---|
| DDD Method | Planned change | Forward | Docs → tests → code for one change |
| TDD Analysis | Step 3 of DDD Method | Forward | Test gaps for that one change |
| DDD Maintenance | Milestone boundary | Cross-cutting | Doc corpus integrity |
| TDD Maintenance | Milestone boundary or post-Escape-Analysis | Cross-cutting | Test corpus integrity |
| Escape Analysis | Bug discovered | Backward | Bug → test → contract → principle |

Any Escape Analysis that uncovers multiple missing clauses at
once is still one Escape Analysis, but it is evidence of a
larger DDD/TDD Maintenance gap — log it for the next scheduled
audit.

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

### 7. Contract the model, not the render

*Applies to documents covering modules with rendered output —
TUIs, REPLs, panels, formatted streams.*

Module docs specify *abstract behaviour and invariants*; the code
owns the *render*.  A doc states what the user sees as a property
("the panel shows the new PC value"; "an error line begins with
`?`"); the doc does NOT specify pixel-level mechanics (cursor row
offsets, exact column positions, overwrite sequences, the order
in which characters arrive on screen).

The line between the two is "could the implementation change
without invalidating the contract?"  If yes, the detail is render
and belongs in code comments; if no, the detail is contract and
belongs in the doc — and a test must pin it.

**Why.**  Pixel-level specifications pin implementation choices
that the contract should be free to revise.  When the UX evolves
— a panel layout changes, a status line moves, a render strategy
gets rewritten — every pixel-level clause has to be edited in
lockstep.  The clauses that *should* hold steady (what the user
must see) drown in the clauses that change (where exactly the
cursor lands).  Tests written against pixel-level specs catch
neither real layout bugs (the spec drifted with the bug) nor
contract violations (the spec was never the contract).

This principle is the doc-side complement of
[testing.md § Principle 15](testing.md) (display-content vs.
state-content): tests assert abstract visible results; docs
specify the abstract contract; the render is the
implementation's prerogative.

Cautionary example (Escape Analysis 2026-04-22): debugger.md once
carried a ~240-line "Step output semantics" appendix pinning
"emit, skip, emit", "up 3 lines", "cursor underflow clamp", and
the exact column at which each tag appeared.  Tests scanned for
the tags at those columns.  When the UX evolved (Phase 22), the
appendix had to be ripped out and the tests rewritten — and
during the years it lived, the tests caught zero contract
violations and zero real layout bugs.  They pinned implementation.

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
| [memory_design.md](memory_design.md) | Memory maps (PRG/CRT), ZP layout, stack contract, banking |
| [design_cse_as_kernel.md](design_cse_as_kernel.md) | Cross-cutting design: CSE-as-kernel framing, RTI/BRK transitions, vector ownership |
| [userland_contract.md](userland_contract.md) | What user code may rely on / must preserve: three-tier state contract, kernel-as-terminal, vector/banking hazards |
| [build_system.md](build_system.md) | Toolchain, build pipeline, targets, options, test binaries |
| [testing.md](testing.md) | The TDD Method, py65 harness conventions |

### User-facing behaviour

| Document | Scope |
|----------|-------|
| [README.md](../README.md) | User reference manual (REPL commands, editor, assembler, debugger, memory map).  Not a corpus document — maintained via DDD Maintenance item 8.  Derived in part from [project.md § Design Priorities](project.md#design-priorities). |
| [background.md](../background.md) | User-facing long-form motivation: why CSE exists, how it compares to its peers, what keeps the promise honest.  Not a corpus document — derived from [project.md](project.md) (§ *What Is CSE?* and § *Design Priorities*) and [README.md](../README.md).  Maintained under the same drift audit as the README. |
| [assembler_syntax.md](assembler_syntax.md) | Source language: labels, instructions, directives, expressions |

### Project management

| Document | Scope |
|----------|-------|
| [TODO.md](TODO.md) | Outstanding work: bugs, features, cleanup, architecture |
| [templates/README.md](templates/README.md) | Active document templates and their coverage |
| [ddd_log.md](ddd_log.md) | DDD Log — running self-review of how the DDD System serves each milestone (newest entries on top); findings feed the next Maintenance round |

### Authoritative data files (dev/)

| File | What it defines |
|------|-----------------|
| `dev/instruction_set.py` | OPCODES, MNEMONICS, OPERAND_PROFILES — the instruction set |
| `dev/hashes.py` | Hash functions (h6, h7), fingerprint formulas, HASH_T |
| `dev/mnemonic_tables.py` | Table generator: reads instruction_set.py, writes src/mn*_tables.s |
| `dev/dasm_tables.py` | Disassembler table generator: writes src/dasm_tables.s |

