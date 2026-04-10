# Build System — Toolchain, pipeline, targets, test binaries

**Template:** [subsystem](templates/subsystem.md)

## Owned files

| File | Role |
|------|------|
| [`Makefile`](../Makefile) | implementation |
| [`src/c64_cse.cfg`](../src/c64_cse.cfg) | implementation — main linker config |
| [`dev/mnemonic_tables.py`](../dev/mnemonic_tables.py) | implementation — mnemonic table generator |
| [`dev/dasm_tables.py`](../dev/dasm_tables.py) | implementation — disassembler table generator |
| [`tests/conftest.py`](../tests/conftest.py) | implementation — test fixtures and auto-rebuild |
| [`tests/c64emu.py`](../tests/c64emu.py) | implementation — C64 emulator class (C64Emu) |
| `rom/kernal.bin` | dependency — C64 KERNAL ROM (not committed; see `.gitignore`) |
| [`dev/instruction_set.py`](../dev/instruction_set.py) | implementation — authoritative opcode database |
| [`dev/hashes.py`](../dev/hashes.py) | implementation — hash function definitions |
| [`dev/size_report.py`](../dev/size_report.py) | implementation — binary size analysis |

## Toolchain

| Tool | Role |
|------|------|
| `ca65` | Assembler — assembles all `.s` files to `.o` |
| `ld65` | Linker — links `.o` files into final binary; generates `.map` |
| `make` | Build orchestration |
| `python3` | Table generation (`dev/mnemonic_tables.py`, `dev/dasm_tables.py`) |
| `pytest` | Test runner (via pipenv virtualenv) |
| `py65` | Python 6502 CPU emulator, used by `C64Emu` |

## Main build pipeline

```
src/*.s  ──ca65──►  build/src/*.o ──ld65──► build/cse.prg
```

Linker config: `src/c64_cse.cfg` — custom ZP layout ($02–$7F),
custom segment placement for the KERNAL-RAM KDATA region.  Produces
`build/cse.prg` (PRG, loads at $0801), `build/cse.map` (symbol map),
and `build/cse.dbg` (debug info).  No C compiler, no `c64.lib` —
the entire codebase is hand-written 6502 assembly.

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
| `TAB_WIDTH` | 1..32 | `8` | Editor tab stop interval.  Must be a power of two for `col mod TAB_WIDTH` to collapse to a single `and` — non-power-of-two values compile but pay a 10-cycle modulo loop per tab render.  8 matches every C64-era toolchain convention. |
| `DEBUG` | `1` | off | Enables debug output |

`CPU_CEIL` (0=6502 only, 1=6502+6510, 2=all three), `CMOS_SUPPORT`,
`CPU_6502`, `CPU_6510`, and `CPU_65C02` gate which mnemonic tables
and decoder paths are compiled in.  Assembly uses `.ifdef CMOS_SUPPORT`
(65C02 paths) and `.ifndef CPU_6502` (6510 illegal paths).  A
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

- **Put lookup tables in `RODATA`.**  RODATA lives in ROM on the
  planned CRT target — anything written at runtime must be in BSS.
- **No self-modifying code.**  All routines work from ROM.  Runtime
  state lives in ZP or BSS, never in patched inline code.
- **Minimize initialized data.**  Prefer runtime initialization.
  BSS is zeroed for free; the DATA segment is currently empty (all
  runtime state is in BSS, all constants in RODATA — see Phase 8).
- **Keep BSS small.**  Every byte of BSS is a byte unavailable to
  the developer's workspace.

## Test build pipeline

Tests run against the real production binary (`build/cse.prg`),
loaded into a `C64Emu` emulator instance that provides a C64
execution environment with the original C64 KERNAL ROM.  No
separate test binaries, no ASM stub files, no test-specific linker
configs.  Every module's real code satisfies every import; the
emulator + real KERNAL provides the hardware environment.

### How it works

1. `conftest.py` invokes `make` to rebuild `build/cse.prg` (if
   sources changed — `make` handles dependency tracking).
2. `conftest.py` parses `build/cse.map` for all exported symbols
   (absolute addresses) and segment starts.
3. Each test creates a fresh `C64Emu`, loads the PRG, looks up
   function addresses by name, and calls them via `emu.jsr()`.

No per-test build, no per-test linker config, no per-test stubs.

### Symbol resolution

Function addresses are resolved from the ld65 `.map` file.
Map-file resolution is reliable because ld65 exports are absolute
addresses after linking.

For module-internal labels (not in the exports list), the harness
computes: `segment_start + module_offset_in_segment`.

### KERNAL ROM

The original C64 KERNAL ROM (`rom/kernal.bin`, 8192 bytes) is copied
from a local VICE installation and listed in `.gitignore` (not
committed).  `C64Emu` loads it as a ROM overlay at $E000–$FFFF,
providing real KERNAL routines (PLOT, GETIN, CHROUT, etc.) instead
of hand-crafted ASM or Python stubs.  Bank-switching via $01 toggles
between ROM and RAM at $E000–$FFFF.  Run `make test` for setup
instructions if the ROM is missing.

## Running tests

```sh
# All tests (checks for KERNAL ROM, rebuilds PRG, runs pytest)
make test

# Quick run (direct, via pipenv)
pipenv run pytest tests/ -q

# Specific module
pipenv run pytest tests/test_expr.py -q
```

See [testing.md](testing.md) for test methodology, conventions, and
the TDD Method.
