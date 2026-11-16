# CSE Documentation Templates

Templates define the required structure for document categories that
appear more than once in the corpus.  Every document of a given
category must conform to its template. Individual files may have a
template, but for them templating is not a requirement.

When a document category reaches two or more instances, a template
must be defined here before the second instance is written.

## Active templates

| Template | Applies to | Instances |
|----------|------------|-----------|
| [module.md](module.md) | `doc/modules/*.md` — one doc per source module | 23 |
| [subsystem.md](subsystem.md) | `doc/*.md` — top-level subsystem docs | 9 |
| [todo.md](todo.md) | `doc/TODO.md` — the project's running TODO file | 1 |
| [cdd_log_entry.md](cdd_log_entry.md) | `doc/cdd_log.md` entries — one per milestone | 2 |

## Non-templated top-level docs

Some `doc/*.md` files are deliberately out of template because they
belong to single-instance categories or are running artefacts whose
shape is owned by a different process.  Each is recognised as
out-of-template by category, not as drift.

| Category | Files | Why no template |
|----------|-------|-----------------|
| Index | [README.md](../README.md) | The corpus index itself; the structure is the index. |
| Glossary | [glossary.md](../glossary.md) | Single-instance reference; structure is `## category` + table. |
| Running log | [cdd_log.md](../cdd_log.md) | Single-instance container; conventions live in the file's header.  Entries inside the container follow [cdd_log_entry.md](cdd_log_entry.md). |
| Process / checklist | [optimization.md](../optimization.md), [vice_test_plan.md](../vice_test_plan.md) | Single-instance procedural references.  When a second instance lands (e.g. a proposed `release_checklist.md`), promote a template before the second instance is written, per the rule above. |
