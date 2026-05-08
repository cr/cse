# Module Doc Template

Use this template for every file in `doc/modules/`.
One file per module. Filename matches the source file: `module.md` for `module.s` or `module.c`.

---

```
# module — One-Line Purpose

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/module.s`](../../src/module.s) | implementation |
| [`tests/test_module.py`](../../tests/test_module.py) | test contract |

**Test coverage** — *(optional preamble; see Rules)*

## Purpose                                  (optional; see Rules)

Short prose framing.

## Interface

### function_name                          (assembly modules)
**In:**  ZP vars, registers, preconditions
**Out:** ZP vars, registers, carry semantics
**Clobbers:** registers and ZP vars destroyed

- `function_name(args)` — description      (C modules)

**State:** persistent variables, if any    (omit if none)
**Depends on:** imported modules           ("nothing" for leaf modules)

## Test contract                            (optional; see Rules)

What the test bundle exercises and what is deliberately out of scope.

## Design

Free-form prose, tables, and code blocks.
Decomposed into ### subsections, or hoisted to ## subsections, for
complex modules (see Rules).

## Caveats

- One bullet per gotcha.
```

---

## Rules

**Owned files**
- Roles are drawn from a fixed set: `implementation`, `test contract`,
  `generated`, `header`.
- List every file this document is authoritative for.
- If no test file exists yet, omit the row — no placeholders.
- Links are repo-relative from `doc/modules/`: `../../src/`, `../../tests/`.

**Test coverage** *(optional)*
- Use a single bold preamble paragraph immediately under the Owned
  files table when the module's coverage situation needs explicit
  framing — typically when the module has no dedicated test file
  and is exercised transitively, or when its coverage relies on a
  named [testing.md](../testing.md) skip pattern (A / B / C).
- Do not promote this to a `##` heading — it is a preamble, not a
  section.  Modules with conventional one-test-file-per-module
  coverage omit it entirely.
- Examples in the corpus: [main.md](../modules/main.md),
  [disk.md](../modules/disk.md), [loader.md](../modules/loader.md).

**Purpose** *(optional)*
- Use `## Purpose` between Owned files and Interface when the
  module's role requires more than the one-line title can carry —
  typically for modules carved out of a parent module
  (extraction-history rationale) or for tier-leaf modules where
  the framing matters for callers.
- Keep it short — a paragraph or two.  If the prose belongs in
  Design, put it in Design.
- Examples in the corpus: [breakpoints.md](../modules/breakpoints.md),
  [gap_buffer.md](../modules/gap_buffer.md).

**Interface**
- Assembly modules use the `### function_name` form with
  **In:** / **Out:** / **Clobbers:** fields.
- C modules use the `- bullet` form.  Do not mix forms within one doc.
- **State:** lists persistent module-level variables (BSS, DATA).
  Omit the line entirely if the module has no persistent state.
- **Depends on:** is always present and always the last line of the
  Interface section.  Use "nothing" for leaf modules.

**Test contract** *(optional)*
- Use `## Test contract` between Interface and Design when the
  module's test-bundle scope needs to be enumerated explicitly —
  typically for L3 leaf modules where what is *deliberately not*
  tested at unit tier is as load-bearing as what is.
- Lists what the test bundle exercises and what is out of scope
  (with a one-line reason or a pointer to the tier that does
  cover it, per [testing.md § Skip-reason patterns](../testing.md)).
- Modules with comprehensive single-tier coverage omit it.
- Examples in the corpus: [breakpoints.md](../modules/breakpoints.md),
  [gap_buffer.md](../modules/gap_buffer.md).

**Design**
- Free-form.  Use `###` subsections when the module has distinct
  internal subsystems worth naming.
- For complex modules, named subsections may be hoisted to `##`
  level and placed alongside Design rather than nested inside it
  (canonical examples: `## Memory`, `## RODATA`, `## Keyboard`,
  `## Buffer layout`, `## Table layout`).  Both forms are
  conformant.  Choose `##` when the subsection has independent
  consumers (e.g. an addressing-mode table consulted by other
  modules); choose `###` when it elaborates a Design point that
  only makes sense in context.
- Flat prose + tables for simple modules.

**Caveats**
- Flat bullet list only.  No sub-bullets, no tables, no prose paragraphs.
- Each bullet is one gotcha: an encoding quirk, a clobber trap, a
  non-obvious precondition, or a performance cliff.
- Omit the section entirely if there are genuinely no caveats.
