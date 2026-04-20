# Testing — TDD Method and test framework conventions

**Template:** [subsystem](templates/subsystem.md)

## Test tiers

CSE tests fall into three explicit tiers that reflect the module
architecture.  A test lives in exactly one tier; the tier is
determined by the module's dependency profile, not by the test's
size or shape.

### Tier U — Unit (module + "linking down")

A module is **unit-testable** when its transitive dependency
closure contains only strictly lower-layer modules (plus acyclic
forward intra-layer edges — see
[architecture.md § Dependency Rules](architecture.md#dependency-rules)).
Link a bundle of [module + closure] with a minimal stub for
linker scaffolding (`__CODE_RUN__`, test entry point, BSS buffers),
and exercise via bare `py65.MPU` — no KERNAL ROM, no BASIC header,
no loader, no interrupt vectors.

Tests live in `tests/unit/`.  One pytest file per module (or
per bundle — the `asm_core` and `mn6`/`mn7` bundles group
tightly-coupled neighbours).

This is **bundled unit testing** (see [glossary.md § Process](glossary.md#process)):
a CSE-specific variant of Martin Fowler's *sociable unit testing*,
where the SUT runs against its real transitive dependencies instead
of mocks.  Stubs provide linker scaffolding only — never behaviour.
The codebase's stratified shape makes this cheap: a bundle is a
downward slice through the dependency DAG, so every test cell
exercises real code on real code without combinatorial blow-up.

### Tier I — Integration (C64Emu + full PRG)

A test graduates to Tier I when any of the following holds:
- Crosses the Layer-5 `main ↔ repl` cycle — these cannot be
  isolated topologically, only co-exercised.
- Requires the runtime environment: KERNAL ROM, interrupt
  vectors, banked memory, screen RAM at `$0400`, BASIC
  header + loader relocation.
- Exercises multi-module state transitions that depend on
  cold-init wiring (flag seeds, vector patches, dbg_init seed
  values).
- Inspects observable behaviour (screen-RAM contents, key
  dispatch, command prompts, disk I/O through KERNAL).

Tests live in `tests/integration/`.  All go through the
`C64Emu` harness + production/debug PRG fixture; no per-test
build systems, no stubs beyond what the C64Emu provides (real
KERNAL, real memory map).

### Tier M — Manual (VICE / hardware)

Timing-dependent, audible, visual, or real-I/O behaviour that
py65 cannot faithfully simulate: SID audio envelopes, VIC-II
raster effects, real 1541 drive timing, keyboard autorepeat
rhythms, thermal quirks.  Not automated.  Verified in VICE or
on hardware; documented in the relevant module's Caveats
section.

### The tier-boundary signal

**If a test needs to manually stub out KERNAL calls, it's in the
wrong tier.**  Either link the real KERNAL via C64Emu (Tier I),
or write the test at a level where the KERNAL doesn't matter
(Tier U — pure data structures, pure arithmetic, pure parsing).

Per-module assignment is enumerated in the
[per-module tier table](#per-module-tier-assignment) below.

## The TDD Method

The TDD Method is the testing companion to the DDD Method (see
[README.md § The DDD Method](README.md#the-ddd-method), step 3).  It governs how
tests are written, when they are written, and what they test.

### Principles

1. **Design for testability.**  Code and interface design must keep
   testability in mind from the start.  This does not mean everything
   gets automated tests — it means the question is always asked and
   consciously answered.

2. **Test contracts, not implementation.**  Tests verify the
   documented interface — given these inputs, expect these outputs,
   this carry flag, this error code.  Tests do not assert internal
   state (ZP scratch, loop counters, intermediate buffers) unless
   that state *is* the contract.

   Example: the sticky-OR width rule (`$00 + $0000` → ABS) is a
   design decision.  Tests pin it down because changing it silently
   breaks user code.  But *how* expr.s implements the OR (which ZP
   byte, what order) is an implementation detail tests must not
   depend on.

3. **Automation is a judgement call.**  Not all behaviour is suited
   for automated testing.  The TDD Analysis must evaluate each
   change and explicitly state whether automated tests are
   practical, impractical, or unnecessary.  When automation is
   impractical, say so and state the alternative (DDD audit, manual
   VICE testing, code review).

4. **UI-heavy code gets selective testing.**  The REPL command loop
   (exec_line, read_line, show_prompt) is tested via `test_repl.py`
   by calling real functions in the production binary through
   `C64Emu`.  The editor is tested the same way.  Full
   keyboard/cursor/scroll interaction remains manual (VICE).  The
   principle: test the command logic and data paths; leave visual
   presentation to manual testing.

5. **Don't drown in harness complexity.**  The test harness must
   remain simpler than the code it tests.  `C64Emu` + the real PRG
   binary eliminates per-test build systems, ASM stubs, and KERNAL
   mocking.  If a test still requires elaborate scaffolding beyond
   what `C64Emu` provides, that is a signal to test at a different
   level or to rely on manual verification.

6. **Test the actual ASM, not a Python copy of it.**  Load the
   production binary into `C64Emu` and exercise the real code.
   Do **not** write a Python function that re-implements the
   algorithm and assert that the Python and the Python agree —
   that is a tautology dressed as a test.  See the
   [Anti-patterns](#anti-patterns) section below for the
   cautionary examples currently in the tree.

7. **Pre-cutover stress tests for phase-scale refactors.**  When a
   refactor introduces a new mechanism that *claims to handle* a
   scenario the old code prevented (by masking / locking / guarding),
   write stress tests that force that scenario through the new
   mechanism **before** you trust the design enough to remove the
   old guard.  Passing the existing test suite + documenting the
   desired state (DDD Step 1) is *not* sufficient — the old guard
   was often masking latent bugs that the new mechanism has to
   handle on its own.

   Cautionary example: Phase 18 introduced `cse_brk_handler_early`
   with stack surgery to handle "IRQ fires while KERNAL is banked
   out" transparently.  The pre-existing SEI guards in
   `kernal_bank_out/in` had been masking that scenario entirely.
   Phase 18 landed with the new handler and all tests green
   (`a628e65`).  A later optimisation commit dropped the "now
   redundant" SEIs (`8e60b62`) — which *finally exposed the new
   mechanism to the stress it was designed for*, and three latent
   bugs in the handler surfaced in quick succession (`c347fa8`,
   `941435d`), triggered by the user running common workflows.

   The discipline: for every "new mechanism replaces old guard"
   refactor, write a test that *forces the scenario the old guard
   prevented* and asserts the new mechanism handles it correctly —
   **before** removing the guard.  For IRQs, this means a test
   that schedules an IRQ at each cycle across the critical window.
   For stack-contract changes, tests that exercise the edge case
   the old contract forbade.  The asymmetric C64Emu fixture
   (`test_kernel_transition.py`) is the right shape for these —
   expand it systematically when new mechanisms land.

8. **Contractual coverage is exhaustive, not illustrative.**  Module
   documentation is an API contract.  Every exported symbol is
   load-bearing — internal callers link to it by name, and every
   promise the doc makes is something downstream code is entitled
   to rely on.

   - **Every exported function** gets at least one correctness
     test.  Not a smoke test — a test that would fail if the
     function stopped meeting its documented contract.
   - **Every exported data symbol** (RODATA table, BSS byte,
     constant) gets at least a content/addressability test so a
     stale value or mis-linked symbol is caught.
   - **Edge cases** (zero-length, single-element, boundary
     values, end-of-range clamping) are part of the contract and
     get tested explicitly.  Parametrised tests covering the
     full boundary-adjacent range (0, 1, N-1, N, N+1) are the
     baseline; full sweeps (e.g. all 17 576 mn7 inputs) are the
     ceiling.
   - **"User-facing" vs. "implementation-detail" is not a valid
     excuse.**  A symbol exported across module boundaries is by
     definition not an implementation detail; other modules link
     to it.  (This principle was added after a test-audit round
     in which several L1 exports had been deferred as
     "internal sibling helpers" and received no coverage.  If a
     symbol is exported, someone depends on it; that someone is
     what the test protects.)

9. **Vocal omissions — skipped tests must state a reason in code.**
   When a contractual test is not automated, the omission must be
   explicit and machine-readable.  Use pytest primitives:

   - `@pytest.mark.skip(reason="…")` — permanent skip for a
     behaviour that cannot be exercised at this test tier (e.g.
     hardware side-effect that py65 doesn't model).  The reason
     must say what tier can exercise it (manual VICE, real C64,
     integration-tier C64Emu).
   - `@pytest.mark.skipif(cond, reason="…")` — conditional skip
     when a build flag or environment dictates applicability.
   - `@pytest.mark.xfail(reason="…", strict=…)` — known-failing
     test pinning a pending bug; `strict=True` makes the test
     fail if it starts unexpectedly passing.
   - `pytest.skip(reason="…")` (function body) — runtime skip
     when a precondition can't be established at fixture time.

   Every skip/xfail reason must name the specific contract
   clause that isn't being verified and where it *is* verified
   (another test, another tier, or the manual-VICE checklist).
   "TODO" and silent `pass` bodies are not acceptable
   substitutes — the test file must be vocal about what it
   covers AND what it deliberately doesn't.

   `pytest --runxfail` re-runs xfailed tests without the mark,
   which is useful after a pending fix has landed.  `pytest
   --strict-markers` catches typoed marker names.

   #### Skip-reason patterns

   A skip reason must fit one of three categories.  Unsure which
   one applies → the test probably shouldn't be skipped, it should
   either be written or deleted.

   **A. Out-of-tier.**  The behaviour IS testable, just not in
   this harness.  The reason must name the tier that covers it:

   ```python
   @pytest.mark.skip(reason=(
       "$01 reads fully-latched under DDR=$FF (mem.md § CPU-port "
       "aware ZP save/restore): py65 has no CPU-port emulation. "
       "Byte-level round-trip is verified here (TestSaveUserlandZp); "
       "the fully-latched guarantee is verified on the VICE manual "
       "checklist.  If C64Emu ever gains CPU-port modelling, convert "
       "this skip into a real test."
   ))
   ```

   **B. Subsumed by another test.**  Write this skip only after
   retiring the test — leave a one-line pointer at the same source
   location so `grep` still finds where the coverage lives:

   ```python
   # test_round_trip retired — subsumed by TestSaveRestoreEdgePatterns::
   # test_userland_round_trip (four patterns, strictly better coverage).
   ```

   Prefer pointer-comments over skipped-test-bodies for this case:
   `pytest.mark.skip` wastes a test slot for something that is
   actively redundant.

   **C. Cannot be enforced at any unit tier.**  System-level
   invariants that live outside the module's control.  The reason
   must name the enforcement mechanism that IS used (code review,
   grep, build check).

   ```python
   @pytest.mark.skip(reason=(
       "$CC=1 lifetime invariant (cse_io.md § IRQ Safety): the "
       "invariant requires $CC=1 for the program lifetime.  No "
       "unit test can verify that other modules won't later clear "
       "$CC.  Enforcement today: code review + grep for '$CC' in "
       "src/ (currently only io_init references it)."
   ))
   ```

   #### Risk preamble for high-impact gaps

   When a skip covers a contract clause whose regression would
   ship silently (hardware-only, system-level), mark the gap with
   a dated preamble comment at its source location:

   ```python
   # ⚠  TOP-RISK L1 GAP (per coverage audit 2026-04-20):
   #    The DDR-stash protocol is the most-likely place an undetected
   #    L1 regression could land — a "clever" refactor of save_*_zp
   #    that byte-round-trips on py65 but breaks the fully-latched-$01
   #    read on silicon would pass CI and ship.  The only backstop
   #    is the VICE manual checklist.
   ```

   Risk tiers:
   - **TOP** — silent-ship regression is plausible and impact is
     module-wide (corruption, crash, silent data loss).  Treat
     the VICE checklist as mandatory before merging any change to
     the flagged code path.
   - **HIGH** — silent-ship possible but requires specific
     conditions; scope is bounded.  Code review is the primary
     mitigation.
   - **LOW** — regression requires a separate maintainer mistake
     (e.g. copying a broken harness pattern).  A single existing
     assertion elsewhere is already a de-facto guard — the skip
     exists mainly to document the reasoning.

   The preamble's date stamps the audit pass.  Future audits
   either refresh the date, upgrade/downgrade the risk tier, or
   remove the preamble if the gap is closed (e.g. a new integration
   test covers it).

   #### When to prefer `xfail` over `skip`

   Use `xfail(strict=True)` for a test whose code is WRITTEN and
   whose expected behaviour IS the contract, but which currently
   fails against a known bug.  This makes the test fail the suite
   the moment the bug gets fixed — a free alarm that the skip can
   now go away.

   Use `skip` for behaviour that isn't implemented at the test
   tier at all (no code to run).

   Never use `xfail(strict=False)` — it silences both failure and
   unexpected passes, defeating the point.

10. **Test bundles must mirror production build configs.**  A module
    built by the Makefile as N distinct binaries (different `-D`
    flag combinations, different source subsets) is effectively N
    modules for testing purposes.  The test harness owes coverage
    to each production variant.  One bundle per variant; one fixture
    per bundle; one test class per fixture.

    **Why this is load-bearing.**  Any code path gated by a
    conditional-compilation flag is INVISIBLE to a test bundle
    whose flags don't match.  If asm_line.s has `.ifdef CMOS_SUPPORT`
    around the CMOS reject gate, and the asm_core test bundle always
    sets `-DCMOS_SUPPORT`, then bugs in the non-CMOS_SUPPORT path
    cannot fail a test.  They will ship undetected.

    **Mechanics.**  When a module ships as N production variants,
    [conftest.py](../tests/conftest.py) parametrises the bundle
    config (`_AC_FLAGS[config]`, `_AC_CLASSIFIER_SOURCES[config]`,
    etc.) and exposes N session fixtures (e.g. `asm_syms`,
    `asm_6510_syms`, `asm_6502_syms`).  Each variant has a matching
    test class in the module's test file.  When adding or removing
    a production variant (Makefile `-D` changes), the bundle list
    moves with it — same commit.

    Cautionary example: the asm_cpu gate escape (doc/README.md
    § Escape Analysis, first canonical application).  The gate bug
    was invisible because only one bundle existed, matching only the
    65C02 production build.  Adding 6510 and 6502 bundles made the
    bug a failing test in one commit.

11. **Contract matrices drive test matrices.**  When a doc describes
    behaviour parametrised by N axes (e.g. asm_cpu × category,
    build-flag × classifier, side × operation), the doc enumerates
    each cell and the test suite covers each cell.  "Rejects CMOS
    on NMOS" is one cell of a 12-cell matrix and tells you nothing
    about the other 11.

    **How this shows up in docs.**  Prefer tables over prose for any
    conditional behaviour.  A contract written as "accepts X on Y;
    rejects otherwise" hides the matrix; a two-axis table makes
    every cell an enumerable testable commitment.  Use [asm_line.md
    § asm_cpu × category gate matrix](modules/asm_line.md) and
    [mn_classify.md § Variants](modules/mn_classify.md) as templates.

    **How this shows up in tests.**  Parametrise the test function
    over the matrix axes.  `@pytest.mark.parametrize` over a list
    of `(source, asm_cpu, expected_behaviour)` tuples makes every
    cell a named case with its own failure line.  Cells the
    contract intentionally leaves open (e.g. "undefined behaviour
    on asm_cpu=3") still belong in the matrix — marked with a
    vocal skip per Principle 9.

    Cautionary example (asm_cpu gate): same as Principle 10.
    Pre-amendment asm_line.md documented "asm_cpu values 0/1/2"
    and "the CMOS gate rejects non-CMOS" — a one-axis spec for a
    two-axis problem.  Eleven of twelve cells were unspecified;
    22 of them shipped broken for years before the matrix audit
    surfaced the gap.

    Cautionary example (dot-command input shapes, Escape Analysis
    2026-04-20): the REPL `.` command accepts *four* input shapes
    — empty, hex-pair(s), mnemonic, and an implicit "garbage"
    fallback.  Pre-amendment repl.md listed only three (empty,
    hex, mnemonic); the garbage cell was handled by the code's
    default fallthrough, which silently mapped it to "silent
    redisplay" instead of the intended "syntax error".  Inputs
    like `. .`, `. ,`, `. $`, `. 123` produced no emit and no
    error — the user got zero feedback.  Writing out the full
    four-cell matrix forces the default-case cell to be a named
    commitment ("other → SYNTAX ERROR") rather than whatever the
    code happens to do.  Rule of thumb: every input-classification
    gate needs an explicit rejection cell — "anything else
    silently ignored" is never a contract, it's a bug waiting to
    be found.

12. **Axiomatic modules need no unit tests.**  An **axiomatic module**
    is one that declares only symbol exports — layout slots, RODATA
    literals and tables, BSS reservations, numeric constants — and
    contains no CODE segment.  In CSE these are all of L0 (`zp`,
    `strings`, every `*_tables`, `mn_config`, `oplen_tbl`,
    `dasm_mne_idx`) plus `mn_vars` at L1 (pure BSS scratch).  An
    axiomatic module has no testable contract beyond "the symbols
    exist and link," which the linker enforces on every build.

    **Why no unit tests.**  A unit test needs something to assert.
    Asserting `mn_modes[16] == $00F0` against the generator's own
    output is a mirror test (see Anti-patterns § Mirror tests).
    Asserting `strings_prompt == "cse>"` against a string literal
    is tautology.  The only meaningful correctness check for
    axiomatic data is "does it make consumers behave correctly" —
    and that check lives in the consumers' bundled tests, which
    already link the module.

    **Transitive coverage is the contract.**  Every bundled test
    that links an axiomatic module is a data-integrity test for
    that module.  A corrupt `oplen_tbl[$A9]` fails `test_dasm`; a
    misaligned ZP slot crashes any bundle that uses it; a wrong
    `mn_modes` bit fails `test_addr_mode`.  Axiomatic-module bugs
    can't hide — they manifest in every bundle that links the
    broken data.

    **Generated-table subtlety.**  Tables produced by
    `dev/mnemonic_tables.py` (`mn_asm_tables`, `mn6/7_tables`,
    `mn_modes`, `oplen_tbl`) have a second failure mode: a
    generator bug that produces *consistently wrong* data could
    hide from a consumer's test if the generator and consumer
    share the wrong assumption.  The guard is that
    `test_asm_line::test_assemble` and `test_dasm` both cross-
    reference every opcode against `dev/instruction_set.py` — the
    independent authoritative source the generator reads.  Tables
    are tested against an oracle, not against themselves.

    **TDD Maintenance rule.**  Axiomatic modules are not flagged
    as untested.  The per-module tier table below uses `—` in the
    Tier column with a brief note on where coverage lives.  If an
    axiomatic module ever grows behaviour (a runtime helper, a
    computed lookup, anything in a CODE segment), it ceases to be
    axiomatic and gets a test file at that point.

13. **Partial-result contracts need position-pinning tests.**  A
    function whose success value depends on state *other than* its
    return code — the position of an input pointer after a partial
    parse, a side-effect counter, a residual-input marker — must
    have unit tests that pin that ancillary state, not just the
    return code.  Callers composing such a function can only reason
    correctly about it when the partial-result state is both
    documented (module doc) and executable (test file).

    **How this shows up in docs.**  Any function whose contract
    admits "I consumed some of the input" must publish a table of
    stopping positions for representative inputs.  See
    [expr.md § Partial-mode contract](modules/expr.md#partial-mode-contract)
    as the reference template: a short grammar, a stopping-position
    table, a greediness clause.  The prose must explicitly name the
    caller's obligation (here: enforce end-of-input if you wanted a
    complete parse).

    **How this shows up in tests.**  A `TestStopContract` class (or
    equivalent section) parametrises `(input, expected_value,
    expected_ptr_offset)` tuples and asserts all three fields.
    Asserting only `return_code + value` leaves the partial-result
    state under-specified and invites silent-partial-success bugs
    at every caller.

    **Transitive pinning via hot-loop composition** (Pattern C
    subsumption — see Principle 9).  A partial-result function whose
    ancillary state is *consumed in a hot loop* by a higher-level
    test is transitively pinned: the composition can only succeed if
    the advancement is correct on every iteration, so a regression
    in the advancement corrupts every test that walks it.  Examples:
    `expr.skip_sp` and `addr_mode.asm_skip_ws` are pinned by
    `TestStopContract` / `TestModeParseStopContract`'s whitespace-
    surrounding cases; `editor.ed_read_byte` is pinned by
    `test_editor.py::read_back` walking the full gap buffer byte
    by byte.  When a partial-result function is already transitively
    pinned, a direct `TestStopContract` would re-exercise the same
    bytes through a thinner harness without catching additional
    regressions — a vocal skip citing Pattern B (subsumed) with an
    explicit pointer at the hot-loop caller is the correct response.
    The module doc still carries the partial-result clause; only the
    direct unit test is subsumed, not the contract itself.

    Cautionary example (Escape Analysis 2026-04-20): `expr_eval`
    accepted `"1x"` as value `1` and left `expr_ptr` at `'x'`.  This
    is *correct partial-mode behaviour* — assembler-operand callers
    depend on it to parse prefixes like `$10,X`.  But the REPL's `?`
    command, which wanted "one complete expression and nothing
    else," had no way to reason about this because the parser's
    stopping contract was implicit: expr.md mentioned `expr_ptr
    advances past the parsed expression` but never tabulated what
    that meant for `"1x"` vs. `"1+1"` vs. `"1,2"`.  `? 1x` silently
    displayed `$01` for years.  A `TestStopContract` at unit tier
    would have made the contract audit-able at a glance; this
    principle would have forced it to exist.

## Anti-patterns

These exist in the current test tree.  Don't add more of them;
when you touch one of them, consider whether to retire it.

### Mirror tests

A "mirror test" is a Python function that re-implements an
algorithm under test, plus assertions that compare the mirror's
output against expected values.  The trap: the test verifies
the *mirror*, not the ASM.  When the ASM diverges from the
mirror, the test still passes because the mirror is what's
running.

Examples previously in `tests/test_editor.py` (retired — preserved
for historical reference in `tests/retired/test_editor.py`):

- **`render_line`** mirrors `editor.s::ed_render_line` in pure
  Python, including the PETSCII→screen-code conversion table.
  `TestRendering` verifies the mirror.  If `ed_render_line`
  changes its conversion rule (or stops handling the gap, or
  reads from the wrong pointer), this test will not catch it.
- **`TestScrollMemmove`** mirrors `editor.s::ed_scroll_up` /
  `ed_scroll_down` as `scroll_up_memmove` / `scroll_down_memmove`
  in Python.  This was added as a regression test for the
  ed_scroll_down byte-level memmove bug that lived undetected
  for months — but the regression test it added cannot
  detect the same class of bug because the actual ASM never
  runs.

The right fix for both: load the production PRG into `C64Emu`
and exercise the real `ed_render_line` / `ed_scroll_up` /
`ed_scroll_down` against real screen RAM at `$0400`.  `C64Emu`
provides the KERNAL, screen RAM, and banking — no ASM stubs
needed.

### Implementation-detail tests

A test that asserts on internal state — a particular ZP byte,
loop counter, intermediate buffer — locks the implementation
to its current shape and prevents legitimate refactoring.

Test contracts.  A contract is what the documented interface
promises: inputs, outputs, side effects on documented state,
return flags, error codes.  Anything else is implementation
detail and the test must not depend on it.

The exception: if the test exists *because* a previous bug was
caused by an internal state slip-up (e.g. a stale accumulator,
a clobbered Y register), and the test is documented as a
regression test for that specific bug, then asserting on the
internal state is fine — but flag it explicitly in the test
docstring so future maintainers know why it looks unusual.

### The TDD Analysis

The TDD Analysis is performed as step 3 of the DDD Method, after
the DDD Analysis and before implementation.  It must:

1. **Identify test gaps** — what existing tests cover the affected
   code, and where are the holes?
2. **Recommend test changes** — new tests to write, existing tests
   to update, obsolete tests to remove.
3. **Assess automation feasibility** — for each change, is automated
   testing practical?  If not, state why and what alternative
   verification is used.
4. **Flag implications** — if the test analysis reveals that the
   intended code change needs adjustment (e.g. an interface must
   change to be testable), this triggers a DDD Feedback Round before
   proceeding.

The TDD Analysis is included in the final DDD Report.

The output of the TDD Analysis — the list of tests to write or
update — feeds directly into Step 4.  Within Step 4, tests are
written first (matching the documentation), then code is written
to pass them.  Tests are the specification in executable form;
they must be green before Step 5 begins.

## Per-module tier assignment

| Module | Layer | Tier | Harness |
|---|---|---|---|
| zp, strings, *_tables, mn_config, oplen_tbl, dasm_mne_idx | 0 | — | (pure data; generator tests in `dev/`) |
| mn_vars | 1 | — | (single-byte ZP scratch; no behaviour) |
| **cse_io** | 1 | U | standalone leaf bundle |
| **mem** | 1 | U | standalone leaf bundle |
| **mn6 / mn7 / mn_classify** | 1 | U | `mn6` / `mn7` bundles |
| **screen** | 2 | I | hardware-adjacent by nature (VIC registers, KERNAL cursor sync); C64Emu is the natural home even though it doesn't model VIC internals |
| **log** | 2 | U | bundle: log + screen + cse_io (PLOT via shared `kplot_stub`) |
| **symtab** | 2 | U | bundle: symtab + mem |
| **asm_err** | 2 | U | bundle: asm_err + mem |
| **expr** | 3 | U | via `asm_core` bundle |
| **opcode_lookup** | 3 | U | via `asm_core` bundle |
| **addr_mode** | 3 | U | via `asm_core` bundle (`test_addr_mode.py`) |
| **asm_line** | 3 | U | `asm_core` bundle |
| **dasm** | 3 | U | `dasm` bundle |
| **breakpoints** | 3 | U | standalone `breakpoints` bundle — BP-table CRUD (extracted from debugger.s at the 2026-04-20 split) |
| **debugger** | 4 | I | step/BRK state + userland-transition gates; BP-table CRUD now lives in `breakpoints` at L3 |
| **asm_src** | 4 | U | `asm_src` bundle |
| **disk** | 4 | I | needs KERNAL LOAD/SAVE/CHKIN |
| **editor** | 4 | I | observable behaviour goes through screen RAM + keys |
| **repl / main** | 5 | I | Layer-5 cycle; only testable full-PRG |
| **loader** | 6 | I | exercised implicitly by C64Emu `load_prg` |

## Framework

All tests use **pytest**.  The test tree is split into two directories
reflecting the tier boundary:

```
tests/
├── c64emu.py                    — emulator harness
├── conftest.py                  — bundle fixtures + cse_prg fixture
├── unit/                        — Tier U tests (bare MPU + bundles)
└── integration/                 — Tier I tests (C64Emu + full PRG)
```

Unit-tier tests load a small bundle binary (module + its
linking-down closure + a stub for linker scaffolding) into a bare
`py65.MPU`.  No KERNAL, no banked memory, no interrupts — just the
module's code + its data.

Integration-tier tests load the debug CMOS PRG
(`build/debug/cmos/cse-cmos.prg`) into `C64Emu` and call into any
function by its `.lbl`-file address.  Debug builds include `-g`
symbols, so the `.lbl` file contains all labels (~1800 symbols)
rather than just exports (~230).  For build details see
[build_system.md § Test build pipeline](build_system.md#test-build-pipeline).

### C64Emu — emulator class

`C64Emu` is a single class used by every test fixture.  It provides
a 6502 CPU, 64 KB RAM, the original C64 KERNAL ROM at $E000–$FFFF,
and just enough C64 hardware modelling to run CSE code under py65.

#### Construction

```python
from c64emu import C64Emu

emu = C64Emu()          # default: KERNAL loaded, screen cleared
```

On construction:

- 64 KB RAM zeroed.
- Original C64 KERNAL ROM (`rom/kernal_cbm.bin`) loaded as a ROM
  overlay at $E000–$FFFF.
- Processor port ($01) set to $37 (KERNAL + BASIC + I/O mapped).
- Bank-switch emulation: writes to $01 toggle the KERNAL ROM
  overlay — clearing bit 1 exposes the underlying RAM at
  $E000–$FFFF (used by `mem.s::kernal_bank_out`); setting it
  restores the ROM image.
- Screen RAM ($0400–$07E7) filled with $20 (space).
- Color RAM ($D800–$DBE7) filled with $01 (white).
- KERNAL ZP state initialised: cursor at row 0 col 0, screen line
  pointers ($D1/$D2, $F3/$F4) set for row 0, cursor disabled
  ($CC = 1), text colour ($0286) = $01, keyboard buffer empty
  ($C6 = 0).
- CPU stack pointer at $FF.

The KERNAL is **not** initialised via the reset vector — ZP state
is set up directly.  This avoids the KERNAL init routine's
hardware probing (VIC-II, CIA) which has no effect in py65.

#### Execution

```python
cycles = emu.jsr(addr, a=0, x=0, y=0, max_cycles=500_000)
```

`jsr(addr)` simulates a JSR to `addr`:

1. Pushes a sentinel return address onto the stack.
2. Sets A/X/Y from keyword arguments, sets PC = `addr`.
3. Steps the CPU until PC reaches the sentinel address.
4. Returns the cycle count.
5. Raises `TimeoutError` if `max_cycles` is exceeded (reports
   the stuck PC).

After `jsr()` returns, the CPU registers and memory are
available for assertions:

```python
assert emu.a == 0x42
assert emu.memory[result_addr] == expected
assert emu.carry                # carry flag
```

#### Register accessors

`emu.a`, `emu.x`, `emu.y`, `emu.sp`, `emu.p` — read/write CPU
registers.  `emu.carry`, `emu.zero`, `emu.negative`,
`emu.overflow` — read/write individual status flags.
`emu.pc` — program counter.  `emu.memory` — the 64 KB
address space (with bank-switching applied transparently).

#### Keyboard injection

```python
emu.inject_key(petscii_byte)    # enqueue one byte at $0277+
emu.inject_keys(b"HELLO\r")    # enqueue a string
```

Writes to the KERNAL keyboard buffer ($0277–$0280) and
increments $C6.  Used by tests that exercise `GETIN`-based
input (cse_io.s `io_kbhit`, REPL `read_line`).

#### PRG loading

```python
emu = C64Emu()              # KERNAL + screen ready
emu.load_prg("build/cse.prg")   # load production binary
```

`load_prg(path)` reads a `.prg` file (2-byte load-address header
+ payload), writes the payload at the load address, and parses
the companion `.map` file for symbol resolution.  All exported
symbols become attributes on the emulator instance:

```python
addr = emu.sym("_asm_line_core")      # look up any exported symbol
```

Since the full production binary is loaded, every module's real
code satisfies every import — no ASM stubs are needed for
inter-module dependencies.  The emulator + real KERNAL provide
the hardware environment (PLOT, GETIN, screen RAM, banking).

Application-level test setup (writing input buffers, pre-loading
symbols, preparing gap-buffer content) is done from Python by
writing directly to memory at the symbol's address.

### SymbolTable — encapsulated symbol resolution

All symbol lookups — in conftest bundles, leaf module tests, and
C64Emu integration tests — go through the `SymbolTable` class in
`conftest.py`.  Test code accesses symbols by name and never
touches file formats, paths, or parsing logic:

```python
from conftest import SymbolTable

s = SymbolTable(lbl_path)
addr = s["mode_parse"]       # KeyError with helpful message if missing
addr = s.get("sym_wide")     # None if missing
"bar" in s                   # membership test
```

`SymbolTable` parses ld65 `.lbl` files (VICE label format).  All
test binaries are assembled with `ca65 -g` and linked with
`ld65 -Ln`, so the `.lbl` file contains every label — exported,
module-internal, and `@local` — at absolute addresses.  No
map-file regex, no listing-file segment offsets, no BSS arithmetic.

### conftest.py — fixtures and auto-rebuild

`conftest.py` provides session-scoped fixtures that auto-build
test binaries when sources change.

**Test bundle architecture.**  Interdependent modules are linked
into a single "bundle" test binary rather than per-module binaries
with expanding mock stubs.  True leaf modules (zero or few imports)
get their own small binary.

#### conftest bundles

| Bundle | Modules | Stub | Tests |
|--------|---------|------|-------|
| `asm_core` | zp, opcode_lookup, asm_line, addr_mode, asm_err, expr, symtab, mem, mn7, mn_classify, mn_modes, mn_asm_tables | `asm_core_test_stub.s` (linker symbols) | test_addr_mode, test_asm_line, test_opcode_lookup |
| `mn6` / `mn7` | mn_classify + mn_vars + mn6/mn7 + tables | (none — pure leaf) | test_mn_classify |
| `asm_src` | asm_core + asm_src | `asm_src_test_stub.s` (ed_read_line mock) | test_asm_src |
| `dasm` | zp, dasm, dasm_tables, mem | `dasm_test_stub.s` (linker scaffolding only) | test_dasm |
| `log` | zp, strings, cse_io, screen, log | `cse_io_test_stub.s` (shared `kplot_stub`) | test_log |

The `asm_core` bundle includes the `asm_err` leaf module for
error-state primitives that `addr_mode`, `opcode_lookup`, and
`asm_line` share.

The bundle principle: when adding a cross-module dependency, add
the module to the existing bundle rather than creating new mocks.
Only create a new bundle when the dependency graph forks into a
genuinely separate subsystem.

#### Shared slim mocks

The stubs listed in the tables above are almost all pure linker
scaffolding (`__CODE_RUN__`, BSS buffers, test entry points) — no
behavioural substitution for real modules.  One exception is
sanctioned: **`cse_io_test_stub.s` exposes `kplot_stub`, a short
functional replacement for KERNAL `$FFF0` (PLOT)** using cse_io's
own `scr_lo` / `scr_hi` tables.  py65 has no KERNAL ROM, so every
Tier U bundle that exercises `io_sync` (directly or transitively)
must supply PLOT from somewhere.  Giving each bundle its own inline
re-implementation would violate Principle 5 (mock scope) — instead
all bundles that need PLOT link the shared `cse_io_test_stub.s`
and patch `$FFF0 → kplot_stub` at setup time.

Policy:
- Behavioural mocks are *exceptional* and must be *shared* — one
  implementation in `dev/`, linked into every bundle that needs it.
- Each behavioural mock is documented here with its justification
  (why an inline replacement is necessary, what production behaviour
  it replicates).
- A mock that drifts from production behaviour is a bug; the
  `kplot_stub` tracks PLOT's CLC-set / SEC-get contract exactly,
  using cse_io's production row-address tables so mock/prod
  divergence is structurally impossible.
- New mocks require explicit sign-off via DDD Method (contract
  clause + test policy change).  Not an ad-hoc decision.

#### Leaf module tests

Well-encapsulated leaf modules — those with zero or near-zero
cross-module dependencies — build their own test binaries inline.
The stub provides only linker-required scaffolding (banking
helpers, BSS buffers), not reimplementations of other modules.

| Test file | Module | Stub | Why leaf |
|-----------|--------|------|----------|
| `test_cse_io.py` | cse_io.s | `cse_io_test_stub.s` | Zero imports |
| `test_symtab.py` | symtab.s | `symtab_test_stub.s` | Only banking helpers |
| `test_debugger.py` | debugger.s | `debugger_test_stub.s` | Only register BSS buffers |

Leaf tests build with `ca65 -g` + `ld65 -Ln` and use `SymbolTable`
for all symbol lookups — the same encapsulation as conftest bundles.

Complex modules with substantive production dependencies should NOT
build standalone test binaries.  They belong in a conftest bundle
(if they share an import graph with existing bundles) or in C64Emu
integration tests (if they depend on most of the codebase).

**TODO:** migrate test_expr.py to the asm_core bundle (expr.s is
already linked there) and test_repl.py to C64Emu integration
(repl.s is the central hub with 8+ subsystem dependencies).

**test_repl.py witness resolution:** Disk I/O witness addresses
(`save_addr`, `save_size`, `load_result`) are resolved from the
stub's RODATA `sym_refs` table (slots 11–13), not from hardcoded
BSS offsets.  The old `stub_bss + 185` pattern broke whenever BSS
layout changed.  All stub-local addresses should be resolved via
the `sym_refs` table or via `SymbolTable` when the test migrates
to C64Emu.

### Running a test

```python
def test_something(cse):
    emu = C64Emu()
    cse.load_into(emu)
    emu.memory[emu.sym("asm_ptr")]     = lo
    emu.memory[emu.sym("asm_ptr") + 1] = hi
    emu.jsr(emu.sym("_asm_line_core"))
    assert emu.a == expected
```

Functions under test end with `rts` which returns to the sentinel
address pushed by `jsr()`, halting the emulation loop.

### Conventions

- **PETSCII encoding:** Test inputs use a `_petscii()` helper that
  converts Python strings to C64 PETSCII (lowercase → $41-$5A
  uppercase).

- **ca65 character literals:** With `-t c64`, ca65 maps character
  literals to PETSCII (`'a'` = $41, not $61).  Without `-t c64`,
  literals use ASCII (`'a'` = $61).  **Use numeric constants**
  (`$41`, `$61`) for PETSCII values in code shared across both
  build modes.  The asm_core bundle builds without `-t c64`.

- **Auto-rebuild:** `conftest.py` invokes `make debug` (or
  `make release`) which handles dependency tracking.  PRGs are
  cached in `build/debug/` and `build/release/`.

- **xfail:** Known limitations (e.g. CMOS gate bugs) are marked
  `pytest.mark.xfail` with a reason string.

- **KERNAL ROM:** Tests require the original C64 KERNAL ROM at
  `rom/kernal_cbm.bin` (copied from a local VICE installation; not
  committed to the repository — see `.gitignore`).  Run `make test`
  for instructions if the ROM is missing.
