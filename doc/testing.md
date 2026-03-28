# Testing

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

4. **UI code is not tested in the harness.**  The REPL and editor
   interact with screen RAM, color RAM, keyboard, and cursor state.
   Simulating these in py65 would require a fake C64 for
   questionable benefit.  Instead: DDD audits (doc ↔ code
   comparison) plus manual testing in VICE.  However, internal
   components with clean interfaces (gap buffer operations,
   sequential reader, reindent logic) can and should be tested
   through the harness when feasible.

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

## Framework

All tests use **pytest** with a **py65** 6502 CPU emulator.

```
tests/
  conftest.py          — fixtures, build helpers, symbol resolution
  test_mnhash.py       — mnemonic classifier (mn6/mn7)
  test_au_mode.py      — addressing mode parser
  test_asm_line.py     — single-line assembler
  test_dasm.py         — disassembler
  test_expr.py         — expression parser
  test_symtab.py       — symbol table
  test_asm_src.py      — two-pass source assembler
  test_cse_io.py       — screen I/O
  test_editor.py       — editor gap buffer
```

### conftest.py architecture

Three independent test binaries, each with its own build pipeline:

| Binary | Linker config | Modules | Entry point |
|--------|--------------|---------|-------------|
| `build/test_asm.bin` | `dev/test.cfg` | asm_line, au_mode, mn7, opcode_lookup, parse_hex, mn_asm_tables, mn7_tables, mn_modes, mn_classify, mn_config, mn_vars, asm_vars | `test_entry` |
| `build/test_expr.bin` | `dev/expr_test.cfg` | expr, symtab, asm_vars | `expr_test_entry` |
| `build/test_asm_src.bin` | `dev/asm_src_test.cfg` | asm_src, expr, symtab, asm_bridge, asm_line, + full assembler stack | `asm_src_test_entry` |

Each binary is:
1. Assembled with `ca65` (assembly modules) or `cc65` + `ca65` (C modules)
2. Linked with `ld65` using a bare-metal config (no C64 KERNAL, no ROM)
3. Loaded into py65 memory at the configured addresses
4. Symbol addresses resolved from the ld65 `.map` file

### Symbol resolution

The test harness resolves function addresses from the ld65 map file,
not from listing offsets.  Map-file resolution is reliable because
ld65 exports are absolute addresses after linking.

For symbols not in the exports list (module-internal labels), the
harness computes: `segment_start + module_offset_in_segment`.

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

## Running tests

```sh
# All tests (uses pipenv virtualenv)
make test

# Quick run (direct pytest)
/Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/pytest tests/ -q

# Specific module
pytest tests/test_expr.py -q

# With verbose output
pytest tests/ -v
```
