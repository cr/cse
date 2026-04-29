# DDD Log — Phase 25 (Release Polish)

**Scope:** the v0.1 release-polish session covering ~18 commits from
the single-letter-label fix through the Phase 25 DDD Maintenance pass.
Self-review of how the DDD System (Method, Corpus, Maintenance,
Escape Analysis, test framework) served the work — what worked, what
didn't, what to amend.

Per [glossary § DDD Log](glossary.md): distinct from the DDD Report
(which summarises *what* changed) and from Escape Analysis (which
reacts to a single escape).  This Log evaluates the *system itself*
against the lived experience of the session.

## What worked

### The Step 2/3 approval gate caught multiple wrong directions

The DDD Method's mandatory analysis-and-approval gate before
implementation paid for itself several times:

- **Single-letter label fix.**  My first proposal was a per-call
  `_au_no_acc` flag.  The approval gate forced me to articulate an
  alternative ("Approach 1: ACC takes precedence" vs "Approach 2:
  symbol takes precedence with ACC fallback").  The articulation
  itself revealed Approach 2 was infeasible in a two-pass assembler
  (forward-ref symbols defeat pass-invariant decisions) — a
  conclusion I hadn't reached before being asked.
- **`.dw` / `.res` differential.**  Initial fix tolerated all error
  classes on pass 0; the user pointed out pass 0 *needs no warn at
  all* because size is value-independent for `.db`/`.dw`.  That
  insight didn't survive my first design pass; it survived the
  pushback at the gate.

The lesson: presenting two named approaches (with explicit feasibility
claims) is much more useful than presenting one and asking "OK?".  The
contrast surfaces hidden assumptions.

### Doc-first made implementations mechanical

Writing the "ACC vs label disambiguation" matrix in `addr_mode.md`
*before* touching code turned the implementation into a translation
exercise.  Each table cell mapped to a code path; tests targeted
cells; the doc and the code converged automatically.  The same
worked for the error-category cleanup (asm_err.md error code table
was the spec, code followed).

### Differential DDD Analysis (Step 5) caught real drift

Several times Step 5 found a doc-code mismatch I'd introduced
during implementation:

- The shadow-warning emission was documented as "asm_line emits"
  but the implementation had `asm_src` doing it.  Step 5 caught it;
  asm_src.md and asm_line.md got reconciled.
- The optimization-round helper extraction (`_bad_val_err`) updated
  call-site code but I'd forgotten to update the count in the
  `### Memory` table of the affected modules — Step 5 caught it.

### Escape Analysis discipline preserved evidence

When the truncation bug surfaced during a pha/pla audit, the
DDD-trained instinct was "file the bug, don't conflate with the
optimization commit."  That kept the optimization commit clean and
let the truncation fix get its own first-class entry, test, and
explanation.  The principle worked: discoveries are evidence, not
opportunistic patches.

### Bundled testing held up

The asm_core / asm_src bundles continued to pay off.  When the
error-category refactor renamed `asm_expr_err` → `asm_err_code`,
the failure surface was *exactly* the bundle that linked the
renamed symbol — three short link-error iterations and the test
suite was green.  No mock / stub gymnastics.

## What didn't work

### Agents over-promised, often confidently

This is the strongest finding of the session.  Three different
optimization-survey agents returned HIGH-confidence findings that
were false positives on verification:

- "`set_cpu` uses lda/cmp/sta only, all preserve C" — but `cmp`
  affects C.  An hour saved by NOT applying the agent's "carry-
  preserving tail-call" suggestion.
- "`_asm_line_core` dead export" — actually used by tests via the
  label-file lookup (`emu.sym("_asm_line_core")`).  Agent's
  `.import` grep didn't model that consumption mode.
- "`asm_org` / `asm_size` / `asm_errors` dead exports" — same
  pattern.  Tests consume them via `s["..."]` lookups.
- "Inline `_expr_eval_inner` saves ~17 B" — the proc has a *dual
  entry label* (`expr_eval_nb`) sharing the body; you can't inline
  without losing the public alias.

The common shape: agents trace control flow shallowly and don't
account for non-source-call consumers (test fixtures, dual-entry
labels, multi-exit-rts shapes).  Verification was always required;
in some rounds verification turned every HIGH finding into a
false positive.

### Stale-comment cleanup is iterative; one sweep doesn't catch all

I cleaned up Phase 21 / Move N comments in repl.s during the broad
optimization round.  A later DDD Maintenance pass surfaced more
of the same shape in `dev/repl_test_stub.s` that I'd missed.  An
even later session-internal pass surfaced still more in the same
file.  The pattern: stale historical markers accumulate everywhere
they can hide, and a single grep against a single area is never
exhaustive.

### TODO.md drift between fix and closure

The "Loader reverse-direction copy" entry was open in TODO.md long
after Phase 19 had landed the fix.  The closure was elsewhere in
the file (in the closed-bugs reference block) but never propagated
to retire the open entry.  This is the same shape as the
`_expr_error_str` doc typo — corpus drift between when work lands
and when the references catch up.

### Boolean abstractions outgrew their semantics

`asm_expr_err` started as a 0/1 flag for "was this error from the
expression evaluator or a syntax error?"  When the CPU-gate
escape revealed a *third* error category (`;?cpu`) was needed, the
boolean had to grow into a 3-state code.  Renaming to
`asm_err_code` propagated through 4 files.  The abstraction would
have been better as a code byte from day one — the cost of
"unused enumeration values" is zero, the cost of "rename a
public flag" is non-trivial.

### Cross-module handoff sweep happens too late in the Method

The `.` REPL command's missing ACC label-shadow warning (an
asymmetry filed as feature work, not a bug) was discovered only
*after* the fix landed and got documented.  The cross-module
handoff — that mode_parse's flag is read by asm_src but the `.`
path bypasses mode_parse via `expr_eval` pre-evaluation — would
have been caught earlier if the DDD Analysis step (2) had been
required to include "for every code path that consumes the new
contract, identify whether it actually flows through".  Step 5
catches the doc-code drift after the fact; Step 2 should catch
the design gap before the fact.

## Suggested amendments

These are concrete proposals.  None landed in this session
(per the DDD Log's role: feed the next Maintenance round); they are
candidates for a future testing.md / README.md amendment pass.

### A1.  Agent-finding verification principle

**Proposal**: amend `doc/README.md` § DDD Method Step 4 (Implementation)
or add a new subsection: "Findings produced by an agent are
*candidates*, not conclusions.  Each finding must be verified by an
independent grep / read / test before being acted on.  Verification
checks at minimum: (a) all consumption modes (jsr, jmp, .import,
test-fixture label lookup, indirect dispatch, dual-entry labels),
(b) the assumption underlying the finding's claim (e.g. "X preserves
C" requires reading X's body)."

The motivating evidence is in this Log § Agents over-promised.

### A2.  TODO closure-with-commit rule

**Proposal**: amend `doc/README.md` § DDD Method Step 6 (Commit) to
require: "if the commit closes one or more entries in `doc/TODO.md`,
the same commit ticks (`[x]` and strikes-through) those entries.  A
commit that lands a fix without retiring the corresponding TODO
entry is incomplete."

The rationale is the "Loader reverse-direction copy" pattern: closed
work that stays open in the queue rots into stale documentation.

### A3.  Stale-marker grep as a DDD Maintenance item

**Proposal**: add a new item to `doc/README.md` § DDD Maintenance
audit scope: "**Stale historical markers** — grep the corpus
(source comments AND prose) for `Phase \d`, `Move \d`, `moved to`,
`previously`, `was formerly`, `TODO:` and confirm each is either
load-bearing (describing a still-current invariant) or stale (and
therefore retired in this audit).  This is item 9, complementing
items 6 (TODO hygiene) and 8 (User manual fidelity)."

The motivating evidence: stale-marker cleanup recurred in 3 distinct
sessions despite each being thorough at the time.

### A4.  Prefer enumeration codes over boolean flags

**Proposal**: add a new principle to `doc/testing.md` (or the
glossary): "When adding a flag byte, if there is *any* prospect of
a third state (a future error class, mode, level, etc.), encode as
a single-byte enumeration from day one.  Boolean (0/1) flags are
correct only when the underlying domain is genuinely binary and
will stay so."

The motivating evidence: `asm_expr_err` → `asm_err_code` rename in
this session.  The cost of an unused enumeration value is one byte
of code (`cmp #2`); the cost of a rename is propagation through
the entire consumer chain.

### A5.  Cross-module handoff sweep in Step 2, not just after the fact

**Proposal**: amend `doc/README.md` § DDD Method Step 2 (DDD
Analysis) to add: "For every code path that will consume the new
contract or signal, walk the path explicitly: does the consumer
actually receive the signal under all conditions, or are there
intermediate transformations (pre-evaluation, mock paths, build-
variant differences) that bypass it?  Document the answer; if any
path bypasses, file as a known asymmetry before implementation."

The motivating evidence: the `.` REPL command's missing
ACC-shadow warning was an asymmetry that survived implementation
because Step 2 didn't audit the dot-command pre-eval path.

## Meta: should DDD Logs be regular?

The glossary entry I added describes the DDD Log as a self-review
practice; it doesn't say *when* to do one.  Three plausible cadences:

1. **Every commit** — too noisy.  Not every commit changes the
   system enough to retrospect on.
2. **Every milestone (alongside DDD Maintenance)** — natural
   pairing with the milestone audit; the Log's findings feed the
   next round.  This is the cadence I'd recommend.
3. **Every Escape Analysis** — already covered by Escape Analysis
   itself; a separate Log would duplicate.

Recommendation: amend the glossary entry to say "performed at each
milestone, alongside DDD Maintenance" — the Log is the
*reflective* half of the milestone gate (DDD Maintenance audits
the artefact; the Log audits the process).

## Closing summary

Phase 25 closed cleanly: 5 user-facing bugs fixed, 1 directive class
expanded (bare ACC), error-category surface expanded with `;?cpu`
and `;!a shadow`, ~120 B added per production variant, 55 new tests
(3057 → 3112), all DDD Maintenance items reconciled.  The DDD
System held throughout — every commit is doc + tests + code, every
audit went through Steps 2/3 approval, every escape produced
permanent corpus tightening.

The five amendments above (A1–A5) represent the *next* tightening
the system needs.  None block v0.1; all should be considered before
the next milestone.
