# Testing — TDD Method and test framework conventions

**Template:** [subsystem](templates/subsystem.md)

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
   using a stub that provides screen RAM, cse_io.s, and mock
   peripherals in py65.  The editor uses a similar approach
   (`test_editor.py`).  Full keyboard/cursor/scroll interaction
   remains manual (VICE).  The principle: test the command logic
   and data paths; leave visual presentation to manual testing.

5. **Don't drown in harness complexity.**  The test harness must
   remain simpler than the code it tests.  If a test requires
   elaborate scaffolding (fake KERNAL, screen RAM simulation,
   interrupt mocking), that is a signal to test at a different level
   or to rely on manual verification.  Some testing is better left
   to the user feedback cycle.

6. **Test the actual ASM, not a Python copy of it.**  When you
   need to verify low-level behaviour, link the real `.s` source
   into a py65 test binary (the pattern in `tests/test_repl.py` /
   `dev/repl_test_stub.s`) and exercise it.  Do **not** write a
   Python function that re-implements the algorithm and assert
   that the Python and the Python agree — that is a tautology
   dressed as a test.  See the [Anti-patterns](#anti-patterns)
   section below for the cautionary examples currently in the
   tree.

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

Examples currently in `tests/test_editor.py`:

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

The right fix for both: add a py65 test binary that links
`editor.s` against an `editor_test_stub.s` (mirroring the
existing `dev/repl_test_stub.s` pattern) and exercise the
real ASM with a real screen RAM region at `$0400`.  This is
captured as a TODO under the *Bugs* section.

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

## Framework

All tests use **pytest** with a **py65** 6502 CPU emulator.  Tests run
against three independent binaries built from subsets of the source
tree.  For the build pipeline, binary layout, symbol resolution, and
run commands, see [build_system.md § Test build pipeline](build_system.md#test-build-pipeline).

### Running a test

```python
def run(cpu, addr, *, input_a=0, input_x=0):
    cpu.memory[0xFFFF] = 0  # sentinel
    cpu.r.pc = addr
    cpu.r.a = input_a
    cpu.r.x = input_x
    while cpu.r.pc != 0xFFFF:
        cpu.step()
```

Functions under test end with `rts` which returns to an address
previously set up on the stack (`$FFFF`), halting the run loop.

### Conventions

- **PETSCII encoding:** Test inputs use a `_petscii()` helper that
  converts Python strings to C64 PETSCII (lowercase → $41-$5A
  uppercase).  The ca65 `-t c64` flag ensures character literals
  in assembly match.

- **Auto-rebuild:** `conftest.py` checks source timestamps and
  rebuilds the test binary only when sources change.  The binary
  is cached in `build/`.

- **xfail:** Known limitations (e.g. CMOS gate bugs) are marked
  `pytest.mark.xfail` with a reason string.
