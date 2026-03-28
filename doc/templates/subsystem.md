# Subsystem Doc Template

Use this template for top-level documents in `doc/` that describe a
technical subsystem and own repository files.  One file per subsystem.

---

```
# Subsystem Name — One-Line Purpose

**Template:** [subsystem](templates/subsystem.md)

## Owned files

| File | Role |
|------|------|
| [`path/file`](../path/file) | implementation / test contract / generated / header |

[content sections — free-form, specific to the subsystem]
```

---

## Rules

**Title**
- Follows the `# Name — Purpose` form, consistent with the module
  doc template.
- Name identifies the subsystem, not the filename.

**Owned files**
- Same table format and role vocabulary as the module doc template:
  `implementation`, `test contract`, `generated`, `header`.
- Mandatory when the doc owns at least one repository file.
- Omit the section entirely if the doc is purely descriptive
  (design spec, reference, process) and owns no files.
- Links are repo-relative from `doc/`: `../src/`, `../tests/`.

**Content**
- Free-form.  No prescribed sections — subsystems vary too widely.
- Cross-references to related docs are encouraged.
