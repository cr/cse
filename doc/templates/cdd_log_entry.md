# CDD Log Entry Template

Use this template for each entry in the project's `doc/cdd_log.md`.
One entry per milestone, plus mid-milestone entries when a session
surfaces significant methodology friction worth capturing at the
moment.

The CDD Log is the reflective audit of the CDD System itself.  See
[`README.md` § CDD Log](../README.md#cdd-log) for the full process
specification.

---

```
## <Milestone identifier> — <Subject> (<YYYY-MM-DD>)

*Optional one-paragraph framing: what the milestone was, what
made it methodology-relevant.*

### What worked

- *Concrete instance of process discipline producing value.*
- *Another instance.  Specific, not a general endorsement.*

### What didn't

- ***<Symptom>.***  *Underlying gap.  Evidence: <session, bug,
  near-miss>.*
- ***<Symptom>.***  *...*

### Suggested amendments

*Each amendment carries an ID (`A<N>` Tier A universal, `B<N>`
Tier B domain-class, `C<N>` Tier C project-specific) and proposes
a home (a specific section of `README.md`, `testing.md`, the
glossary, or a new artefact).  These flow into
[`TODO.md` § CDD amendments pending](../TODO.md#cdd-amendments-pending)
for the next CDD Maintenance round to triage.*

- **<ID>. <Subject>.**  Body of proposal.  Motivating evidence:
  <reference>.  Likely **Tier <A|B|C>**.

### Closing summary

One paragraph naming the methodology trajectory: what the
milestone confirmed, what changed, what the next round inherits.
```

---

## Rules

**Title.**  Single `## <Milestone identifier> — <Subject>
(<YYYY-MM-DD>)` heading.  The milestone identifier matches the
project's convention (`R1`/`R2`/…, `v0.1`/`v0.2`/…, `M1`/`M2`/…,
or `Phase <N>`).

**Section order.**  Fixed: What worked → What didn't → Suggested
amendments → Closing summary.  Sections may carry empty placeholders
if no item belongs there for this milestone, but the four-section
shape is invariant — readers expect the same slots in every entry.

**What worked.**  One sub-bullet per discipline instance.
Specificity matters: name the session, the bug, the contract.
"The Method worked" is no entry; "Step-2 cross-module audit on
command X surfaced asymmetry Y before implementation" is.

**What didn't.**  Same shape as What worked, with bold-symptom
prefix to make scanning easy.  Each item has three components:
symptom (what was observed), underlying gap (what was missing),
evidence (what session / bug / artefact carries the trace).

**Suggested amendments.**  IDs are project-defined (per
[`TODO.md` § Conventions](../TODO.md)).  Each amendment proposes
a concrete home — the destination must exist (or be a new
artefact named explicitly).  Amendments without proposed homes
cannot triage cleanly.

**Closing summary.**  One paragraph; not a recap of the entry's
four sections but a forward-looking trajectory note: where the
methodology is now, what the next milestone inherits.

**Newest on top.**  In `doc/cdd_log.md`, entries are appended
above prior entries.  The most recent milestone is the first one
a reader sees.
