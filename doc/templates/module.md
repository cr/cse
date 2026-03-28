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

## Interface

### function_name                          (assembly modules)
**In:**  ZP vars, registers, preconditions
**Out:** ZP vars, registers, carry semantics
**Clobbers:** registers and ZP vars destroyed

- `function_name(args)` — description      (C modules)

**State:** persistent variables, if any    (omit if none)
**Depends on:** imported modules           ("nothing" for leaf modules)

## Design

Free-form prose, tables, and code blocks.
Decomposed into ### subsections for complex modules.

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

**Interface**
- Assembly modules use the `### function_name` form with
  **In:** / **Out:** / **Clobbers:** fields.
- C modules use the `- bullet` form.  Do not mix forms within one doc.
- **State:** lists persistent module-level variables (BSS, DATA).
  Omit the line entirely if the module has no persistent state.
- **Depends on:** is always present and always the last line of the
  Interface section.  Use "nothing" for leaf modules.

**Design**
- Free-form.  Use `###` subsections when the module has distinct
  internal subsystems worth naming.
- Flat prose + tables for simple modules.

**Caveats**
- Flat bullet list only.  No sub-bullets, no tables, no prose paragraphs.
- Each bullet is one gotcha: an encoding quirk, a clobber trap, a
  non-obvious precondition, or a performance cliff.
- Omit the section entirely if there are genuinely no caveats.
