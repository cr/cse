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

## Framework

All tests use **pytest** with a `C64Emu` emulator class
([`tests/c64emu.py`](../tests/c64emu.py)) that wraps **py65** and
provides a minimal but authentic C64 execution environment.  Tests
load the real production binary (`build/cse.prg`) and call into
any function by its map-file address — no separate test binaries,
no ASM stubs, no test-specific linker configs.  For build details
see [build_system.md § Test build pipeline](build_system.md#test-build-pipeline).

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

### conftest.py — fixtures and auto-rebuild

`conftest.py` provides session-scoped fixtures that auto-build
test binaries when sources change.

**Test bundle architecture.**  Interdependent modules are linked
into a single "bundle" test binary rather than per-module binaries
with expanding mock stubs.  True leaf modules (zero or few imports)
get their own small binary.  Current layout:

| Bundle | Modules | Stub | Tests |
|--------|---------|------|-------|
| `asm_core` | asm_vars, opcode_lookup, asm_line, au_mode, expr, symtab, mem, mn7, mn_classify, mn_modes, mn_asm_tables | `asm_core_test_stub.s` (BRK error + linker symbols) | test_au_mode, test_asm_line |
| `mn6` / `mn7` | mn_vars + mn6/mn7 + tables | (none — pure leaf) | test_mnhash |
| `asm_src` | asm_core + asm_src | `asm_src_test_stub.s` (ed_read_line mock) | test_asm_src |

The bundle principle: when adding a cross-module dependency, add
the module to the existing bundle rather than creating new mocks.
Only create a new bundle when the dependency graph forks into a
genuinely separate subsystem.

**TODO:** migrate dasm, expr, repl test binaries to the bundle
pattern (or C64Emu integration tests) to eliminate their stubs.

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

- **Auto-rebuild:** `conftest.py` invokes `make` which handles
  dependency tracking.  The PRG is cached in `build/`.

- **xfail:** Known limitations (e.g. CMOS gate bugs) are marked
  `pytest.mark.xfail` with a reason string.

- **KERNAL ROM:** Tests require the original C64 KERNAL ROM at
  `rom/kernal_cbm.bin` (copied from a local VICE installation; not
  committed to the repository — see `.gitignore`).  Run `make test`
  for instructions if the ROM is missing.
