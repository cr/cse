# Build System — Toolchain, pipeline, targets, test binaries

**Template:** [subsystem](templates/subsystem.md)

## Owned files

| File | Role |
|------|------|
| [`Makefile`](../Makefile) | implementation |
| [`src/c64_trial.cfg`](../src/c64_trial.cfg) | implementation — trial linker config (size measurement) |
| [`src/c64_cse.cfg.in`](../src/c64_cse.cfg.in) | implementation — production linker config template |
| [`dev/compute_layout.py`](../dev/compute_layout.py) | implementation — computes runtime start, generates production config |
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
| `exomizer` | SFX compressor — produces self-extracting PRG for disk |
| `pytest` | Test runner (via pipenv virtualenv) |
| `py65` | Python 6502 CPU emulator, used by `C64Emu` |

## Main build pipeline

```
src/*.s ──ca65──► build/src/*.o ──┐
                                  ├─ld65 (trial)──► trial.map
                                  │                     │
                                  │          compute_layout.py
                                  │                     │
                                  │                     ▼
                                  ├─ld65 (production)──► cse.prg
                                  └────────────────────────────
```

**Two-pass link.**  The 6502 has no MMU — code must be linked for
the address where it will actually run.  CSE packs its runtime
(CODE+RODATA+BSS) at the end of main RAM, ending at $CFFF, to
maximize workspace.  The exact start address depends on the total
size of these segments, which is only known after linking.

Pass 1 (trial): `ld65 -C c64_trial.cfg` links everything into a
flat image at $0800 — the addresses are wrong, but the segment
**sizes** in `trial.map` are correct.

`compute_layout.py` reads the sizes from `trial.map`, computes
`RUNTIME_START = $D000 - (CODE + RODATA + BSS)`, and stamps that
value into `c64_cse.cfg.in` to produce `build/c64_cse.cfg`.

Pass 2 (production): `ld65 -C build/c64_cse.cfg` links with the
correct runtime addresses.  CODE and RODATA use ld65's `load`/`run`
address split — they are placed in the file after the loader
(load address ≈ $0870) but all symbol references resolve to the
runtime address (≈ $7D00+).  The loader copies them at boot.

### The ld65 load/run split

ld65 natively supports placing a segment at one address in the
output file while resolving all its symbols for a different
(runtime) address.  This is configured per segment:

```
CODE: load = LOADIMG, run = RUNTIME, type = ro, define = yes;
```

- `load = LOADIMG` — the segment's bytes go into the LOADIMG
  memory region in the output file (after the loader).
- `run = RUNTIME` — all labels and references within CODE resolve
  to addresses in the RUNTIME memory region (high memory).
- `define = yes` — the linker generates `__CODE_LOAD__`,
  `__CODE_RUN__`, and `__CODE_SIZE__` symbols.  The loader
  imports these to know where to copy from and to.

The loader (`loader.s`, in the LOADER segment) runs at its load
address ($080D).  It copies CODE+RODATA from their LOADIMG
position to their RUNTIME position, zeros BSS, copies KDATA
under the KERNAL, then `jmp _main`.  After the jump, the loader's
memory ($0800–LOADER_END) becomes part of the workspace.

No C compiler, no `c64.lib` — the entire codebase is hand-written
6502 assembly.

### Exomizer compression

Each build also produces an exomizer SFX-compressed PRG
(`cse-exo.prg`) alongside the uncompressed one.  The SFX is a
self-extracting binary: on `RUN`, exomizer's decrunch stub
decompresses the payload in-place, then the BASIC SYS stub and
loader run normally.  ~38% smaller than the raw PRG.

`make disk` writes the compressed PRG to the D64.
`make run` launches the uncompressed PRG (no decrunch delay).

## Build targets

| Target | Command | Output |
|--------|---------|--------|
| All (default) | `make` | All three CPU variants (raw + compressed) + distribution D64 |
| Disk (single) | `make disk` | Per-CPU D64 in build dir (for quick iteration) |
| Run | `make run` | Launch uncompressed PRG in VICE (no decrunch delay) |
| Tables | `make tables` | Regenerate `src/mn*_tables.s` via `mnemonic_tables.py` |
| Tests | `make test` | Run all pytest tests |
| Size | `make size` | Size breakdown of selected PRG (`CPU=`) |
| Clean | `make clean` | Remove `build/` directory |
| Themes | `make themes` | List available colour themes |
| Help | `make help` | List all targets and options |

`make` builds all three CPU targets (6510, 6502, 65C02), each
producing both a raw PRG and a compressed PRG (`*-exo.prg`), then
creates `build/cse.d64` with all three compressed variants:

    build/cse.d64           distribution D64 (all three CPU targets)
      cse                   6510 compressed (53 blocks, default)
      cse-6502              6502 compressed
      cse-cmos              65C02 compressed
    build/6510/cse.prg      6510 raw (for make run / debugging)
    build/6510/cse-exo.prg  6510 compressed
    build/6502/...           6502 variants
    build/cmos/...           65C02 variants

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

`C64Emu.load_prg()` automatically handles the load/run address
split: after loading the PRG at its file address, it checks for
segments where `__SEG_LOAD__` ≠ `__SEG_RUN__` and copies them to
their runtime positions (mirroring what `loader.s` does on real
hardware).  Test code always references runtime addresses.

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
