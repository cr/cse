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

- **xfail:** Known limitations (e.g. CMOS gate bugs, missing C stack
  stubs) are marked `pytest.mark.xfail` with a reason string.
