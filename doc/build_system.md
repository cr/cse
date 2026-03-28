# CSE Build System

## Owned files

| File | Role |
|------|------|
| [`Makefile`](../Makefile) | implementation |
| [`src/c64_cse.cfg`](../src/c64_cse.cfg) | implementation — main linker config |
| [`dev/mnemonic_tables.py`](../dev/mnemonic_tables.py) | implementation — mnemonic table generator |
| [`dev/dasm_tables.py`](../dev/dasm_tables.py) | implementation — disassembler table generator |
| [`dev/test.cfg`](../dev/test.cfg) | implementation — test binary linker config (asm) |
| [`dev/expr_test.cfg`](../dev/expr_test.cfg) | implementation — test binary linker config (expr) |
| [`dev/asm_src_test.cfg`](../dev/asm_src_test.cfg) | implementation — test binary linker config (asm_src) |
| [`tests/conftest.py`](../tests/conftest.py) | implementation — test build and py65 harness |

## Toolchain

| Tool | Role |
|------|------|
| `cc65` | C compiler — compiles `main.c`, `repl.c`, `editor.c` to `.s` |
| `ca65` | Assembler — assembles all `.s` files to `.o` |
| `ld65` | Linker — links `.o` files into final binary; generates `.map` |
| `make` | Build orchestration |
| `python3` | Table generation (`dev/mnemonic_tables.py`, `dev/dasm_tables.py`) |
| `pytest` | Test runner (via pipenv virtualenv) |
| `py65` | Python 6502 emulator used by the test harness |

## Main build pipeline

```
src/*.c  ──cc65──►  build/src/*.s  ──ca65──►  build/src/*.o ─┐
src/*.s  ───────────────────────────ca65──►  build/src/*.o ──┤
                                                              ├──ld65──► build/cse.prg
c64.lib ──────────────────────────────────────────────────────┘
```

Linker config: `src/c64_cse.cfg` — custom ZP layout ($02–$7F), expanded
beyond the cc65 default.  Produces `build/cse.prg` (PRG, loads at $0801),
`build/cse.map` (symbol map), and `build/cse.dbg` (debug info).

## Build targets

| Target | Command | Output |
|--------|---------|--------|
| Default PRG | `make` | `build/cse.prg` — loads at $0801 |
| Tables | `make tables` | `src/mn*_tables.s`, `src/dasm_tables.s` |
| Tests | `make test` | runs pytest suite |
| Themes list | `make themes` | lists available colour themes |
| Help | `make help` | lists all targets and options |

CRT target (cartridge) is a planned future target using the same source
with a different linker config.  See [memory_design.md](memory_design.md)
for the CRT memory layout.

## Build-time options

Passed as `make OPTION=value`:

| Option | Values | Default | Effect |
|--------|--------|---------|--------|
| `CPU` | `6502` `6510` `65c02` | `6510` | Sets `CPU_CEIL` and `CMOS_SUPPORT` defines |
| `THEME` | name or hex | default | Colour theme for the REPL |
| `DEBUG` | `1` | off | Enables debug output |

`CPU_CEIL` (0=6502 only, 1=6502+6510, 2=all three) and `CMOS_SUPPORT`
gate which mnemonic tables and decoder paths are compiled in.  A
`CPU=6502` build excludes all illegal and CMOS code.

## Table generation

Generated files must be regenerated whenever the authoritative data
changes:

| Generator | Input | Output |
|-----------|-------|--------|
| `dev/mnemonic_tables.py` | `dev/instruction_set.py` | `src/mn7_tables.s`, `src/mn6_tables.s`, `src/mn_asm_tables.s`, `src/mn_modes.s`, `src/mn_config.s` |
| `dev/dasm_tables.py` | `dev/instruction_set.py` | `src/dasm_tables.s` |

Run with `make tables` or directly with `python3 dev/mnemonic_tables.py`.
Generated files carry a "do not edit" comment.  Their owning docs are
[mn_classify.md](modules/mn_classify.md) and [dasm.md](modules/dasm.md).

## ROM compatibility constraints

These apply to all code and apply regardless of build target:

- **Use `const` for all lookup tables.**  cc65 places `const` data in
  `RODATA`, which lives in ROM on the CRT target.
- **No self-modifying code.**  All assembly routines work from ROM.
  Runtime values live in ZP or BSS, never in patched inline code.
- **Minimize initialized data.**  Prefer runtime initialization.
  Static `= 0` is free (BSS); static `= nonzero` costs ROM + RAM
  (DATA segment is copied to RAM at startup).
- **Keep BSS small.**  Every byte of BSS is a byte unavailable to
  the developer.
- **C stack budget: 2KB max.**  Avoid deep recursion or large locals.

## Test build pipeline

Tests run against three independent binaries, each assembled and linked
from a subset of the source tree without a C64 KERNAL or ROM:

| Binary | Linker config | Entry point | Covers |
|--------|--------------|-------------|--------|
| `build/test_asm.bin` | `dev/test.cfg` | `test_entry` | asm_line, au_mode, mn7, opcode_lookup, parse_hex, mn_asm_tables, mn7_tables, mn_modes, mn_classify, mn_config, mn_vars, asm_vars |
| `build/test_expr.bin` | `dev/expr_test.cfg` | `expr_test_entry` | expr, symtab, asm_vars |
| `build/test_asm_src.bin` | `dev/asm_src_test.cfg` | `asm_src_test_entry` | asm_src, expr, symtab, asm_bridge, asm_line, + full assembler stack |

Each binary is built by `conftest.py` on first use and cached in
`build/`.  `conftest.py` checks source timestamps and rebuilds only
when sources change.

Build steps per binary:
1. Assembly modules: `ca65`
2. C modules: `cc65` → `ca65`
3. Link: `ld65` with bare-metal config → binary + `.map` file

### Symbol resolution

Function addresses are resolved from the ld65 `.map` file, not from
listing offsets.  Map-file resolution is reliable because ld65 exports
are absolute addresses after linking.

For module-internal labels (not in the exports list), the harness
computes: `segment_start + module_offset_in_segment`.

## Running tests

```sh
# All tests (via pipenv virtualenv)
make test

# Quick run (direct pytest)
/Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/pytest tests/ -q

# Specific module
pytest tests/test_expr.py -q

# Verbose
pytest tests/ -v
```

See [testing.md](testing.md) for test methodology, conventions, and
the TDD Method.
