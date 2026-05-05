# DDD Log

Self-review of how the DDD System (Method, Corpus, Maintenance,
Escape Analysis, test framework) served each milestone.  Per
[glossary § DDD Log](glossary.md): distinct from the DDD Report
(which summarises *what* changed) and from Escape Analysis (which
reacts to a single escape) — the Log evaluates the *system itself*
against the lived experience of the session.

Newest entries on top.

---

## Phase 26 — v0.1 Release

**Scope:** the v0.1 release-cycle session covering rc1 → rc4 → v0.1.
Five rc1-VICE bugs caught, fixed, and re-tested through three
release candidates; eight permanent documentation-audit scripts
landed under `dev/`; ~50 doc drift fixes; the project published
to `github.com/cr/cse` with MIT licensing and a v0.1 GitHub
Release carrying disk-image + per-CPU PRG artifacts.

### What worked

#### Probe-first debugging unblocked the recurring CHROUT-jank fix

The cursor-jank bug went through THREE landings before reaching
the right code — and the first two were *enumeration-driven*
(rc2 attempt 1 in `reset_screen`; rc2 attempt 2 in `refresh_body`).
The third (rc3) was *probe-driven*: I wrote
`dev/probe_chrout_zp.py` to enumerate which ZP bytes KERNAL
CHROUT actually mutates, and `dev/probe_plot_with_corrupt_ldtb1.py`
to demonstrate the PLOT-with-corrupt-LDTB1 mechanism.  Both
probes ran in py65 against the real C64 KERNAL ROM.  The first
probe revealed that CSE's `io_putc` *bypasses KERNAL CHROUT
entirely* — so the kernel-mode NMI path I'd been patching could
never have been corrupting KERNAL ZP in the first place.  The
second probe demonstrated that PLOT(10, 5) lands on row 9 col 45
when LDTB1 is corrupt, which IS the user-visible jank.

After two enumeration-based attempts that fixed nothing, one
~30-line py65 probe gave the answer in 5 minutes.  This is
exactly the discipline the Phase-25 A1 amendment proposed.  The
amendment paid for itself within one session of becoming policy.

#### Mechanical doc audits surfaced real drift the eye missed

Eight audit scripts landed under `dev/` (umbrella `audit_doc.py`).
Combined, they caught ~50 documentation drift issues that
manual reading had missed across multiple Phase-25-Maintenance
passes.  Notable wins:

- ZP overview claimed "85 bytes ($02-$56)" — actual is 118 bytes
  ($02-$77).  Phase-21 added 33 bytes that no doc touched.
- BSS counts in `dasm.md` and `main.md` off by 3 and 3 bytes
  respectively (added but unaccounted-for `.res` directives).
- "Depends on" lists in `editor.md`, `asm_src.md`, `mn_classify.md`
  named modules that had been refactored away.
- Symbol renames (io_cx/io_cy → CUR_COL/CUR_ROW, _expr_eval →
  expr_eval, clear_eol → io_clear_eol, etc.) — 25+ stale refs.
- `kernal_bank_*` attributed to `symtab.s` but lived in `mem.s`.

The umbrella now gates release-readiness mechanically.  A
maintainer running `dev/audit_doc.py --quiet` before a tag gets
a 30-second guarantee against the entire class of structural
drift.  This is the Phase-25 amendment direction made permanent
infrastructure.

#### Linker-map source-of-truth beat text parsing

The first version of `audit_doc_module_bss.py` parsed `.res`
directives from `src/*.s` directly — and false-positived on
`.res (BP_SLOTS + STEP_SLOTS) * SLOT_SIZE` (breakpoints.s) and
`.res FILENAME_MAX + 2` (repl.s) because expressions need
constant evaluation.  Switched to reading the linker map
(`build/debug/cmos/cse.map` "Modules list" section) which has
the post-evaluation byte counts.  False positives → zero.

Lesson catalogued: when auditing assembled code for size /
layout claims, the linker map is the source-of-truth.  Don't
re-implement what the assembler/linker already computed.

#### DDD discipline survived all four rc cycles

Every fix went through the seven steps: doc → DDD analysis →
TDD analysis → implement → differential DDD → commit → report.
Even the failed CHROUT landings went through their full cycles
— each had an honest commit message acknowledging why the
*previous* attempt was wrong.  Result: the bug entry in
`doc/TODO.md § Bugs` reads as a worked example of the
"three-landings-before-it-landed-right" pattern, which is
*more useful* than a single clean fix would have been.

The system worked exactly as designed: wrong attempts get
DOCUMENTED, not hidden.

#### VICE test plan generalised from per-rc fix-list to permanent gate

Initial intent was a checklist for v0.1 final readiness.  Once
written, the structure obviously generalised: `doc/vice_test_plan.md`
is now a permanent test-plan reference where § E (rc-fix
verifications) refreshes per release but A–D, F–H stay constant.
Future v0.2 / v0.3 inherit it.

The Phase-25 A2 amendment (TODO closure with commit) and the
new permanent test plan together close the loop:
findings → bug entries → fixes → permanent VICE-verifiable
contract.

#### Public-publication mechanics were trivial after the discipline

The transition from "tagged v0.1 locally" to "live at
github.com/cr/cse" was three commands: `gh repo create`,
`git push -u origin main`, `git push origin v0.1` (plus
`gh release create` for the binary release page).  Total
elapsed time: ~3 minutes once SSH→HTTPS auth was configured.

The reason this was trivial is that everything was already
in shape: README rendered correctly with screenshots,
LICENSE auto-detected by GitHub for the sidebar badge, all
audits green, all rc tags accumulated as a public tag history.
The discipline did the publish.

### What didn't work

#### Same-bug-class multi-landing is a correctness smell I missed in real time

Three landings on the CHROUT-jank bug.  Phase-25 had A1 (probe
before enumerating) but I didn't internalise the principle as
a *real-time signal*.  The pattern: when a fix doesn't resolve
the user-reported symptom on first try, the second attempt
should NOT be "narrow the scope of the same enumeration" —
it should be "stop, write a probe, reset assumptions."  I did
attempt 2 (narrow scope) and only after that failed did I
write the probe.

Lesson for amendment: explicit "second-landing trigger" — if a
fix doesn't resolve the reported symptom, the *next* action is
mandatory probe-writing, not another enumeration attempt.

#### Audit-suite false positives delayed the initial value

Step 1B (symbol existence) initially flagged 198 names.  Most
were false positives: module file names referenced as concepts
("the asm_src module"), build-time `-D` macros, KERNAL ROM
addresses CSE references but doesn't define, conceptual handler
names (`cmd_continue` is `@h_c` in code).  Spent ~30% of the
audit-development time iterating filters before the audit gave
clean signal.

The right pattern, in retrospect: pick mechanical-fail gating
tests EARLY (false negatives are fine — bug entries can be
filed for residuals), then refine.  Don't try to ship a
zero-false-positive audit on the first cut.  The Phase-25 A4
amendment direction (enum codes over booleans) generalises:
report-only audits should escalate to gating only when their
false-positive rate is genuinely low.

#### License + ROM attribution were caught by the user, not by the corpus

The user caught the missing LICENSE during pre-tag.  I caught
the MEGA65-ROM-without-attribution on `gh repo create`.  Both
should have been gated by a `release_checklist.md` (mechanical
pre-flight).  Both are exactly the kind of "we forgot something
obvious" issue that a checklist catches and a verbal "I think
we're ready" doesn't.

#### Semantic correctness of user-facing examples is a class the audits don't catch

The README's `.org $C000` examples would have crashed CSE if
pasted by a user (CSE runtime is at `$7B00-$CFFF`; user code
at `$C000` corrupts CSE's own BSS).  The structural audits
catch broken cross-refs and stale numbers but not "this
example, if executed, breaks the system."  This is a different
drift class — *semantic* validity of examples — and warrants
its own audit step.

The user caught the C000 issue and asked me to double-check;
I found 3 residuals beyond the user's pass.  This is the kind
of finding a Step-5-style "examples-as-tests" audit would
catch automatically.

### Suggested amendments

These are concrete proposals, none of which landed in this
session.  They feed the next Maintenance round.

#### A6.  Probe-first debugging: second-landing trigger

**Proposal**: amend `doc/README.md` § DDD Method Step 4
(Implementation) or a new subsection: "When a fix does not
resolve the reported symptom on first attempt, the next action
is *mandatory probe-writing* — not another enumeration-based
fix.  Multi-landing fixes (more than one attempt at the same
bug class in a session without a probe in between) are a
correctness smell.  The probe is what reveals which assumption
was wrong; without it, the second attempt is just noise."

The motivating evidence is in this Log § Same-bug-class
multi-landing.  The Phase-25 A1 amendment proposed probe-driven
verification of *findings*; A6 extends it to probe-driven
verification of *root causes* before re-attempting fixes.

#### A7.  Pre-publish release checklist

**Proposal**: add a new `doc/release_checklist.md` (or section
of `doc/vice_test_plan.md`) covering the mechanical pre-flight
before any tag intended for public release:

- LICENSE file present + author/year correct.
- All committed binary artifacts have provenance documented
  (rom/README.md style).
- README user-facing examples use only addresses in
  workspace ($0800-workend) or KERNAL ranges; no examples
  referencing CSE runtime ($7B00-$CFFF).
- `dev/audit_doc.py --quiet` reports all gating audits green.
- All rc tags pushed to remote.
- v0.x release page exists with binary artifacts attached.

Both LICENSE and ROM attribution were caught last-minute this
session — exactly the class of issue a checklist catches.

#### A8.  Semantic-correctness audit for user-facing examples

**Proposal**: Step 5 of the doc-audit plan
(`examples-as-tests`, currently filed as v0.2 candidate)
gains a *semantic correctness* dimension beyond mere
assembleability: every `$XXXX` in user-facing prose
(README.md, doc/assembler_syntax.md) that names a memory
location should be classified safe / unsafe based on the
runtime memory map.  Unsafe addresses (CSE runtime, BSS,
KERNAL ROM under-RAM) flag for review.

The motivating evidence: three `$C000` residuals in README
this session, all of which would have crashed CSE if
executed.  The user's `.org $C000` cleanup pass caught
some; the others survived.  A mechanical scanner that
knows the memory map would catch all of them.

#### A9.  Audit-suite gates for v0.x final tags

**Proposal**: amend `doc/release_checklist.md` (per A7) to
formally require all gating audits in `dev/audit_doc.py`
green before any tag without an `-rc` suffix.  Currently the
umbrella exists and is recommended; A9 makes it required for
release tags.  Combined with A7, it converts a discipline
into a process.

### Closing summary

Phase 26 closed cleanly: v0.1 published at github.com/cr/cse,
five rc1-VICE bugs all closed and retested, ~50 doc drift
fixes, eight permanent audit scripts under `dev/`, MIT
licensing applied, ROM attribution documented, release page
with disk-image + 3 PRG variants.  The DDD System held
through four rc cycles.  Every bug entry traceable from
symptom → root-cause-via-probe → fix → regression test →
public release.

Phase 25's five amendments (A1-A5) all landed implicitly via
the work this session demanded.  A1 (probe-first) was
internalised the hard way (three landings before it stuck).
A2 (TODO closure with commit) was honoured automatically.
A3 (stale-marker grep) became `audit_phase_markers.py`.  A4
(enum codes) didn't apply directly but informed the
report-only-vs-gating audit distinction.  A5 (cross-module
handoff in Step 2) showed up as the audit infrastructure
itself.

The four new amendments above (A6-A9) extend the system from
*correctness discipline* into *release-readiness gating* —
the mechanical pre-flight that closes the loop between
"tested" and "shipped."

Next is v0.2: the audit suite catches its first generation
of drift, the new amendments apply at every release, and
the DDD whitepaper takes the methodology where the corpus
documentation can't reach.

---

## Phase 25 — Release Polish

**Scope:** the v0.1 release-polish session covering ~18 commits from
the single-letter-label fix through the Phase 25 DDD Maintenance pass.

### What worked

#### The Step 2/3 approval gate caught multiple wrong directions

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

#### Doc-first made implementations mechanical

Writing the "ACC vs label disambiguation" matrix in `addr_mode.md`
*before* touching code turned the implementation into a translation
exercise.  Each table cell mapped to a code path; tests targeted
cells; the doc and the code converged automatically.  The same
worked for the error-category cleanup (asm_err.md error code table
was the spec, code followed).

#### Differential DDD Analysis (Step 5) caught real drift

Several times Step 5 found a doc-code mismatch I'd introduced
during implementation:

- The shadow-warning emission was documented as "asm_line emits"
  but the implementation had `asm_src` doing it.  Step 5 caught it;
  asm_src.md and asm_line.md got reconciled.
- The optimization-round helper extraction (`_bad_val_err`) updated
  call-site code but I'd forgotten to update the count in the
  `### Memory` table of the affected modules — Step 5 caught it.

#### Escape Analysis discipline preserved evidence

When the truncation bug surfaced during a pha/pla audit, the
DDD-trained instinct was "file the bug, don't conflate with the
optimization commit."  That kept the optimization commit clean and
let the truncation fix get its own first-class entry, test, and
explanation.  The principle worked: discoveries are evidence, not
opportunistic patches.

#### Bundled testing held up

The asm_core / asm_src bundles continued to pay off.  When the
error-category refactor renamed `asm_expr_err` → `asm_err_code`,
the failure surface was *exactly* the bundle that linked the
renamed symbol — three short link-error iterations and the test
suite was green.  No mock / stub gymnastics.

### What didn't work

#### Agents over-promised, often confidently

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

#### Stale-comment cleanup is iterative; one sweep doesn't catch all

I cleaned up Phase 21 / Move N comments in repl.s during the broad
optimization round.  A later DDD Maintenance pass surfaced more
of the same shape in `dev/repl_test_stub.s` that I'd missed.  An
even later session-internal pass surfaced still more in the same
file.  The pattern: stale historical markers accumulate everywhere
they can hide, and a single grep against a single area is never
exhaustive.

#### TODO.md drift between fix and closure

The "Loader reverse-direction copy" entry was open in TODO.md long
after Phase 19 had landed the fix.  The closure was elsewhere in
the file (in the closed-bugs reference block) but never propagated
to retire the open entry.  This is the same shape as the
`_expr_error_str` doc typo — corpus drift between when work lands
and when the references catch up.

#### Boolean abstractions outgrew their semantics

`asm_expr_err` started as a 0/1 flag for "was this error from the
expression evaluator or a syntax error?"  When the CPU-gate
escape revealed a *third* error category (`;?cpu`) was needed, the
boolean had to grow into a 3-state code.  Renaming to
`asm_err_code` propagated through 4 files.  The abstraction would
have been better as a code byte from day one — the cost of
"unused enumeration values" is zero, the cost of "rename a
public flag" is non-trivial.

#### Cross-module handoff sweep happens too late in the Method

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

### Suggested amendments

These are concrete proposals.  None landed in this session
(per the DDD Log's role: feed the next Maintenance round); they are
candidates for a future testing.md / README.md amendment pass.

#### A1.  Agent-finding verification principle

**Proposal**: amend `doc/README.md` § DDD Method Step 4 (Implementation)
or add a new subsection: "Findings produced by an agent are
*candidates*, not conclusions.  Each finding must be verified by an
independent grep / read / test before being acted on.  Verification
checks at minimum: (a) all consumption modes (jsr, jmp, .import,
test-fixture label lookup, indirect dispatch, dual-entry labels),
(b) the assumption underlying the finding's claim (e.g. "X preserves
C" requires reading X's body)."

The motivating evidence is in this Log § Agents over-promised.

#### A2.  TODO closure-with-commit rule

**Proposal**: amend `doc/README.md` § DDD Method Step 6 (Commit) to
require: "if the commit closes one or more entries in `doc/TODO.md`,
the same commit ticks (`[x]` and strikes-through) those entries.  A
commit that lands a fix without retiring the corresponding TODO
entry is incomplete."

The rationale is the "Loader reverse-direction copy" pattern: closed
work that stays open in the queue rots into stale documentation.

#### A3.  Stale-marker grep as a DDD Maintenance item

**Proposal**: add a new item to `doc/README.md` § DDD Maintenance
audit scope: "**Stale historical markers** — grep the corpus
(source comments AND prose) for `Phase \d`, `Move \d`, `moved to`,
`previously`, `was formerly`, `TODO:` and confirm each is either
load-bearing (describing a still-current invariant) or stale (and
therefore retired in this audit).  This is item 9, complementing
items 6 (TODO hygiene) and 8 (User manual fidelity)."

The motivating evidence: stale-marker cleanup recurred in 3 distinct
sessions despite each being thorough at the time.

#### A4.  Prefer enumeration codes over boolean flags

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

#### A5.  Cross-module handoff sweep in Step 2, not just after the fact

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

### Meta: should DDD Logs be regular?

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

### Closing summary

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
