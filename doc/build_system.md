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
| `rom/kernal_cbm.bin` | dependency — stock C64 KERNAL ROM (not committed; see `.gitignore`) |
| `rom/basic_cbm.bin` | dependency — stock C64 BASIC ROM (not committed) |
| `rom/chargen_cbm.bin` | dependency — stock C64 character ROM (not committed) |
| [`rom/kernal_mega.bin`](../rom/kernal_mega.bin) | dependency — MEGA65 Open-ROMs KERNAL (committed) |
| [`rom/basic_mega.bin`](../rom/basic_mega.bin) | dependency — MEGA65 Open-ROMs BASIC (committed) |
| [`rom/chargen_mega.bin`](../rom/chargen_mega.bin) | dependency — MEGA65 Open-ROMs character ROM (committed) |
| [`dev/instruction_set.py`](../dev/instruction_set.py) | implementation — authoritative opcode database |
| [`dev/hashes.py`](../dev/hashes.py) | implementation — hash function definitions |
| [`dev/size_report.py`](../dev/size_report.py) | implementation — binary size analysis |
| [`dev/od65_syms.py`](../dev/od65_syms.py) | implementation — od65-based symbol extraction from .o files |

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

**Copy direction: top-down.**  The loader uses a reverse-direction
memcpy (highest byte first) for the CODE+RODATA and KDATA copies.
Backward copy is safe whenever `dst >= src`, which is exactly the
direction CSE uses — payload at low addresses, runtime at high.
This means the build has no payload/runtime overlap ceiling: CODE
+ RODATA may grow all the way up to `RUNTIME_START` without
tripping any sanity check in `compute_layout.py`.  The only
remaining layout gate is the workspace-overlap check
(`RUNTIME_START < $0900`).

No C compiler, no `c64.lib` — the entire codebase is hand-written
6502 assembly.

### Version propagation

`VERSION` is defined in the Makefile (default `0.1`).  It flows
to the binary and to the distribution disk via two mechanisms:

1. **Source string** — the Makefile writes `build/version.inc`
   containing `.define VERSION_STRING "<value>"` on every build.
   `strings.s` does `.include "version.inc"` (via `ca65 -I
   $(BUILD)`) and uses the macro in the `VERSION_STR` byte
   sequence.  Result: the splash line reads `cse v<value> by cr`.
2. **Disk label** — the `_dist` and `disk` Makefile targets pass
   `"cse $(VERSION),01"` to `c1541 -format`, so the D64 label
   (visible in `$` listings) carries the version.

PRG filenames (`cse.prg`, `cse-6502.prg`, `cse-cmos.prg`) are
**not** versioned: the CPU suffix is architectural, the version
lives in the splash and disk label.  Downstream consumers rely
on the stable filename layout.

### Introspection builds (`INTROSPECT=1`)

By default, `m` and `.` redirect ZP reads and writes through
`userland_zp_buf` for the save range (see
[repl.md § User-ZP view](modules/repl.md#user-zp-view)) so the
user sees their program's ZP, not CSE's internal state.

When debugging CSE itself this redirect is in the way: the
developer wants to see what CSE's own ZP (`rp_ptr`, gap buffer
pointers, the assembler's working state) actually contains.
Setting `INTROSPECT=1` on the Makefile command line drops the
redirect — `m` and `.` then read and write live ZP directly:

    make run INTROSPECT=1       # release + introspection
    make debug INTROSPECT=1     # debug + introspection
    make release INTROSPECT=1   # release + introspection

Mechanism: the Makefile passes `-DINTROSPECT` to `ca65`, which
ca65 `.ifdef`s in [repl.s](../src/repl.s) `zp_stage_prep` and
`zp_poke`.  In the INTROSPECT build both helpers become
pass-through stubs (`rts` / `sta (rp_ptr2),y / rts`) and the
redirect code is not assembled.  The flag is part of
`BUILD_FLAGS`, so toggling it triggers a full rebuild.

This is a developer-only affordance — **shipping builds must
leave INTROSPECT unset.**  It breaks the user-visible contract
that `m` always means "user ZP" ([project.md § Design
Priority 3](project.md#design-priorities)) and exposes
implementation details the user should never see.  Orthogonal to
the `debug`/`release` profile split (full .lbl symbols vs raw
production PRG); pick each independently.

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
| All (default) | `make` | Same as `release` |
| Release | `make release` | All three CPU variants, optimized + exomizer + D64 |
| Debug | `make debug` | All three CPU variants with `-g` (full symbols in `.lbl`) |
| Disk (single) | `make disk` | Per-CPU D64 in build dir (for quick iteration) |
| Run | `make run` | Build release + launch in VICE |
| Tables | `make tables` | Regenerate `src/mn*_tables.s` via `mnemonic_tables.py` |
| Tests | `make test` | Build both debug + release, then run all pytest tests |
| Size | `make size` | Size breakdown of selected release PRG (`CPU=`) |
| Clean | `make clean` | Remove `build/` directory |
| Themes | `make themes` | List available colour themes |
| Help | `make help` | List all targets and options |

### Build profiles

Two build profiles share the same `_one` sub-target in the Makefile.
Only the output directory and assembler flags differ:

| Profile | Flags | Exomizer | Symbols in `.lbl` |
|---------|-------|----------|-------------------|
| `release` | `-t c64` | yes | ~230 (exports only) |
| `debug` | `-g -t c64 -DDEBUG` | no | ~1800 (all labels) |

The `-g` flag tells ca65 to embed debug symbols in `.o` files.
When linked with `ld65 -Ln`, the resulting `.lbl` file contains
every label — exported, module-internal, and `@local` — at its
absolute address.

### Command-line options

| Variable | Default | Effect |
|----------|---------|--------|
| `CPU` | `6510` | Target CPU for `run`/`disk`/`size` (`6502` / `6510` / `65c02`) |
| `THEME` | `GREENLAND` | Named theme or 3-digit hex code (`make themes` for list) |
| `TAB_WIDTH` | `8` | Editor tab-stop column width |
| `VERSION` | `0.1` | Version string embedded in splash + D64 label |
| `ROMSET` | `cbm` | KERNAL/BASIC/CHARGEN set for `run` (`cbm` / `mega`) |
| `INTROSPECT` | unset | If `=1`, disable the user-ZP redirect in `m`/`.` (see above) |

All of these are part of `BUILD_FLAGS` and trigger a full rebuild when
changed between invocations.

### Directory layout

    build/
      release/
        6510/   cse.prg  cse-exo.prg  cse.map  cse.lbl  cse.dbg  src/*.o
        6502/   cse-6502.prg  cse-6502-exo.prg  ...
        cmos/   cse-cmos.prg  cse-cmos-exo.prg  ...
      debug/
        6510/   cse.prg  cse.map  cse.lbl  cse.dbg  src/*.o
        6502/   cse-6502.prg  ...
        cmos/   cse-cmos.prg  ...
      cse.d64             distribution D64 (from release, all three CPUs)
      asm_core_test.*     conftest.py test bundles (built with -g)
      mn6_test.*          ...
      mn7_test.*          ...
      asm_src_test.*      ...
      dasm_test.*         ...

PRG names are the same in both profiles — the `release/` vs `debug/`
directory disambiguates.

CRT target (cartridge) is a planned future target using the same source
with a different linker config.  See [memory_design.md](memory_design.md)
for the CRT memory layout.

## Build-time options

Passed as `make OPTION=value`:

| Option | Values | Default | Effect |
|--------|--------|---------|--------|
| `CPU` | `6502` `6510` `65c02` | `6510` | Sets `CPU_CEIL` and `CMOS_SUPPORT` defines |
| `ROMSET` | `cbm` `mega` | `cbm` | ROM set for `make run` (see below) |
| `THEME` | name or hex | default | Colour theme for the REPL |
| `TAB_WIDTH` | 1..32 | `8` | Editor tab stop interval.  Must be a power of two for `col mod TAB_WIDTH` to collapse to a single `and` — non-power-of-two values compile but pay a 10-cycle modulo loop per tab render.  8 matches every C64-era toolchain convention. |

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

## ROM sets

`ROMSET=` selects which KERNAL, BASIC, and CHARGEN ROMs VICE uses
for `make run`.  All ROM files live in `rom/` and are listed in
`.gitignore` (not committed).

| `ROMSET` | KERNAL | BASIC | CHARGEN | Source |
|----------|--------|-------|---------|--------|
| `cbm` (default) | `kernal_cbm.bin` | `basic_cbm.bin` | `chargen_cbm.bin` | Stock Commodore C64 ROMs (from VICE) |
| `mega` | `kernal_mega.bin` | `basic_mega.bin` | `chargen_mega.bin` | MEGA65 Open-ROMs, C64-compatible build |

ROM filenames follow the pattern `{type}_{romset}.bin`.  Adding a
new ROM set (e.g. `ROMSET=jiffy`) only requires dropping three
files with matching names — no Makefile changes needed.

Usage:

    make run                # stock CBM ROMs (default)
    make run ROMSET=mega    # MEGA65 Open-ROMs

The `mega` set is useful for testing CSE against the open-source
KERNAL replacement to identify compatibility issues (particularly
around cursor positioning and screen editor internals).

Non-stock ROM sets automatically enable True Drive Emulation
(`-drive8truedrive`).  VICE's default virtual drive mode intercepts
specific addresses in the stock KERNAL's serial bus routines —
with a different KERNAL those traps don't match, and serial I/O
hangs.  TDE emulates the real 1541 CPU and DOS ROM, so the serial
protocol works regardless of which KERNAL is loaded.

## Test build pipeline

`make test` requires both the **debug** and **release** builds.
Most tests (including C64Emu-based tests) run against the debug
CMOS PRG (`build/debug/cmos/cse-cmos.prg`), which has full symbol
coverage via its `.lbl` file (~1800 symbols).  A `cse_release_prg`
fixture is available for E2E integration tests that verify the
actual shipping binary.

Test bundles (asm_core, mn6, mn7, asm_src, dasm) are built by
`conftest.py` with `ca65 -g` and `ld65 -Ln`, producing their
own `.lbl` files with complete symbol coverage.

### How it works

1. `conftest.py` invokes `make debug` (or `make release`) to
   rebuild the CMOS PRG if sources changed.
2. `conftest.py` parses the `.lbl` file (VICE label format) for
   all symbols at absolute addresses.
3. Each test creates a fresh `C64Emu`, loads the PRG, looks up
   function addresses by name, and calls them via `emu.jsr()`.

`C64Emu.load_prg()` automatically handles the load/run address
split: after loading the PRG at its file address, it checks for
segments where `__SEG_LOAD__` ≠ `__SEG_RUN__` and copies them to
their runtime positions (mirroring what `loader.s` does on real
hardware).  Test code always references runtime addresses.

No per-test build, no per-test linker config, no per-test stubs.

### Symbol resolution

All symbol addresses are resolved from ld65 `.lbl` files (VICE
label format: `al HEXADDR .NAME`).  Both the full PRG and the
test bundles are assembled with `ca65 -g` and linked with
`ld65 -Ln`, so the `.lbl` file contains **every** label —
exported, module-internal, and `@local` — at absolute addresses.

The `SymbolTable` class in `conftest.py` encapsulates all symbol
resolution.  Test code accesses symbols by name (`s["label"]`,
`s.get("label")`) and never touches file formats, paths, or
parsing logic.  Both conftest bundle fixtures and leaf module
tests use `SymbolTable` as their sole symbol resolution mechanism.
`C64Emu._parse_map()` also delegates to `SymbolTable` internally.

For pre-link symbol inspection, `dev/od65_syms.py` extracts
exports and debug symbols from `.o` files via `od65`.

### KERNAL ROM

The original C64 KERNAL ROM (`rom/kernal_cbm.bin`, 8192 bytes) is copied
from a local VICE installation and listed in `.gitignore` (not
committed).  `C64Emu` loads it as a ROM overlay at $E000–$FFFF,
providing real KERNAL routines (PLOT, GETIN, CHROUT, etc.) instead
of hand-crafted ASM or Python stubs.  Bank-switching via $01 toggles
between ROM and RAM at $E000–$FFFF.  Run `make test` for setup
instructions if the ROM is missing.

## Running tests

```sh
# All tests (builds both debug + release, checks for KERNAL ROM, runs pytest)
make test

# Quick run (direct, via pipenv — assumes builds exist)
pipenv run pytest tests/ -q

# Specific module
pipenv run pytest tests/test_expr.py -q
```

See [testing.md](testing.md) for test methodology, conventions, and
the TDD Method.
