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
| [`tests/emu_base.py`](../tests/emu_base.py) | implementation — `EmuBase`, what C64Emu and M65Emu share: registers, run loops, word access, symbols, screen-code decoding, the interrupt scheduler and jiffy tick, `KeyMatrix` and the keyboard calls, `load_prg()` with segment relocation, `set_cursor()`, `init_cse()` |
| [`tests/asm_dasm_runner.py`](../tests/asm_dasm_runner.py) | implementation — exhaustive asm_line / dasm_insn sweeps on py65 (output + cycles) |
| [`dev/capture_golden.py`](../dev/capture_golden.py) | implementation — records the asm/dasm golden files from a known-good tree |
| [`tests/fixtures/golden/`](../tests/fixtures/golden/) | generated — `asm_dasm_<cpu set>.json`, one per C64 CPU set, by `dev/capture_golden.py`; `m65_cpu.json`, the 45GS02 as xmega65 executes it, by `dev/capture_m65_golden.py`; `m65_mem.json`, the CPU view's translation per banking state, by `dev/capture_m65_mem.py`; `m65_dma.json`, DMA jobs, by `dev/capture_m65_dma.py`; back-link-exempt (JSON has no comment syntax) |
| [`tests/unit/test_golden_asm_dasm.py`](../tests/unit/test_golden_asm_dasm.py) | test contract — behaviour and speed against the golden files (TODO § M65, gates 2–3) |
| [`tests/integration/test_size_budget.py`](../tests/integration/test_size_budget.py) | test contract — C64 release PRG sizes within budget (TODO § M65, gate 1) |
| [`tests/unit/test_build_parity.py`](../tests/unit/test_build_parity.py) | test contract — bundle `PROD_DEFS` equal the Makefile's `-D` sets |
| [`tests/unit/test_mnemonic_tables.py`](../tests/unit/test_mnemonic_tables.py) | test contract — the profile-row model of `dev/mnemonic_tables.py` |
| [`tests/unit/test_dasm_tables.py`](../tests/unit/test_dasm_tables.py) | test contract — the disassembler model of `dev/dasm_tables.py` |
| [`tests/m65emu/`](../tests/m65emu/) | implementation — M65Emu, the m65 harness: `MPU45GS02` (`mpu45gs02.py`), its decode table from the compendium fixture (`isa.py`), the CPU golden-file format (`golden.py`), `M65Memory` (`memory.py`), the devices — DMA controller, keyboard queue, CIA1 matrix port, VIC interrupt latch, CIA2 interrupt control (`devices.py`) —, the `M65Emu` harness and its snapshot loading (`harness.py`) ([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)) |
| [`tests/xmega65.py`](../tests/xmega65.py) | implementation — the xmega65 driver (headless start on a cloned SD image, uartmon commands) for Tier X and the M65Emu recordings |
| [`dev/capture_m65_golden.py`](../dev/capture_m65_golden.py) | implementation — records `m65_cpu.json` in xmega65 |
| [`dev/capture_m65_state.py`](../dev/capture_m65_state.py) | implementation — records M65Emu's post-boot snapshot and reference run from xmega65 into `build/m65_state/` (run by hand; holds the ROM, never committed) |
| [`dev/capture_m65_dma.py`](../dev/capture_m65_dma.py) | implementation — records `m65_dma.json` (DMA jobs as xmega65 runs them) |
| [`dev/capture_m65_mem.py`](../dev/capture_m65_mem.py) | implementation — records `m65_mem.json` (the CPU view's translation per banking state) in xmega65 |
| [`tests/fixtures/mega65_instruction_set.csv`](../tests/fixtures/mega65_instruction_set.csv) | dependency — the MEGA65 compendium's instruction tables (bbbc64's `dev/mega65_opcode_extract.py` output, copied unchanged); `MPU45GS02`'s decoder source; back-link-exempt (CSV) |
| [`tests/unit/test_mpu45gs02.py`](../tests/unit/test_mpu45gs02.py) | test contract — `MPU45GS02` against the fixture, the 45GS02-specific behaviour and every case of `m65_cpu.json` |
| [`tests/unit/test_m65emu_harness.py`](../tests/unit/test_m65emu_harness.py) | test contract — the M65Emu harness without a snapshot: `jsr`, `run_until`, registers, `load_prg`, `screen_text`, the I/O log, `restore()` |
| [`tests/integration/test_m65emu.py`](../tests/integration/test_m65emu.py) | test contract — M65Emu on the real MEGA65 KERNAL: the reference runs (`CHROUT`, the DMA scroll) match xmega65's, `GETIN` reads injected keys, and the parity calls reach the KERNAL — the jiffy tick's frame work, STOP through the matrix, RESTORE's NMI, `PLOT` (skipped without the snapshot) |
| [`tests/unit/test_m65dma.py`](../tests/unit/test_m65dma.py) | test contract — the DMA controller against every job of `m65_dma.json`, plus snapshot restore and the modes that raise |
| [`tests/unit/test_m65devices.py`](../tests/unit/test_m65devices.py) | test contract — the keyboard queue and `inject_key()`, the CIA1 matrix port, the VIC interrupt latch (`$D019`), the CIA2 interrupt register (`$DD0D`), device claims and the unmodelled-I/O log |
| [`tests/unit/test_m65memory.py`](../tests/unit/test_m65memory.py) | test contract — `M65Memory` against every state of `m65_mem.json`, plus colour RAM, ROM protection, the CPU port, the page-table triggers and `MAP` run on `MPU45GS02` |
| [`tests/integration/test_c64emu.py`](../tests/integration/test_c64emu.py) | test contract — exercises the C64Emu harness itself (construction, banking, `jsr`, the KERNAL buffer, `PLOT`, `GETIN`, screen access) |
| [`tests/integration/test_c64emu_banking.py`](../tests/integration/test_c64emu_banking.py) | test contract — `$01` banking + KERNAL/BASIC ROM mapping |
| [`tests/integration/test_c64emu_cia.py`](../tests/integration/test_c64emu_cia.py) | test contract — C64-only: the matrix hidden under the character ROM (CHAREN=0) |
| [`tests/integration/test_c64emu_interrupts.py`](../tests/integration/test_c64emu_interrupts.py) | test contract — C64-only: the interrupt vector fetched through the banking |
| [`tests/integration/test_c64emu_jiffy.py`](../tests/integration/test_c64emu_jiffy.py) | test contract — C64-only: the jiffy tick makes the C64 KERNAL count `$A0`–`$A2` |
| [`tests/integration/test_emu_parity.py`](../tests/integration/test_emu_parity.py) | test contract — what `C64Emu` and `M65Emu` share (`emu_base.py`): interrupt scheduler, jiffy tick, keyboard matrix, RESTORE, key injection, `load_prg()` relocation, `set_cursor()`, `init_cse()` — parametrised over both |
| `rom/kernal_cbm.bin` | dependency — stock C64 KERNAL ROM (not committed; see `.gitignore`) |
| `rom/basic_cbm.bin` | dependency — stock C64 BASIC ROM (not committed) |
| `rom/chargen_cbm.bin` | dependency — stock C64 character ROM (not committed) |
| [`rom/kernal_mega.bin`](../rom/kernal_mega.bin) | dependency — MEGA65 Open-ROMs KERNAL (committed) |
| [`rom/basic_mega.bin`](../rom/basic_mega.bin) | dependency — MEGA65 Open-ROMs BASIC (committed) |
| [`rom/chargen_mega.bin`](../rom/chargen_mega.bin) | dependency — MEGA65 Open-ROMs character ROM (committed) |
| `rom/mega65.rom` | dependency — the MEGA65 ROM xmega65 uses (not committed; copied by `make m65-rom`) |
| [`rom/mega65_open.rom`](../rom/mega65_open.rom) | dependency — MEGA65 Open ROMs, MEGA65 build, pinned upstream commit (committed; C64 mode only, see [rom/README.md](../rom/README.md#mega65-roms)) |
| [`dev/find_m65_rom.py`](../dev/find_m65_rom.py) | implementation — finds the MEGA65 ROM in xmega65's data directory and copies it to `rom/mega65.rom` (`make m65-rom`) |
| [`tests/unit/test_find_m65_rom.py`](../tests/unit/test_find_m65_rom.py) | test contract — the MEGA65 ROM discovery: search order, acceptance, copy; the committed Open ROM's pin |
| [`dev/instruction_set.py`](../dev/instruction_set.py) | implementation — authoritative opcode database |
| [`dev/hashes.py`](../dev/hashes.py) | implementation — hash function definitions |
| [`dev/size_report.py`](../dev/size_report.py) | implementation — binary size analysis |
| [`dev/od65_syms.py`](../dev/od65_syms.py) | implementation — od65-based symbol extraction from .o files |
| [`dev/scs_analysis.py`](../dev/scs_analysis.py) | implementation — screen-code sequence analysis tool |
| [`dev/scs_pack.py`](../dev/scs_pack.py) | implementation — screen-code sequence packer |
| [`dev/gen_asm_tests.py`](../dev/gen_asm_tests.py) | implementation — generator for assembler-test fixtures |
| [`dev/strings.txt`](../dev/strings.txt) | implementation — input list for `dev/scs_pack.py` |
| [`dev/test.cfg`](../dev/test.cfg) | implementation — generic linker config for legacy unit-test stubs |
| [`dev/asm_core_test_stub.s`](../dev/asm_core_test_stub.s) | implementation — linker scaffolding for the asm_core test bundle (asm_line + addr_mode + opcode_lookup) |
| [`dev/asm_src_test.cfg`](../dev/asm_src_test.cfg) | implementation — linker config for the asm_src test bundle |
| [`dev/asm_src_test_stub.s`](../dev/asm_src_test_stub.s) | implementation — linker scaffolding for the asm_src test bundle |
| [`dev/breakpoints_test_stub.s`](../dev/breakpoints_test_stub.s) | implementation — linker scaffolding for the breakpoints test bundle |
| [`dev/cse_io_test_stub.s`](../dev/cse_io_test_stub.s) | implementation — linker scaffolding for the cse_io test bundle |
| [`dev/dasm_test_stub.s`](../dev/dasm_test_stub.s) | implementation — linker scaffolding for the dasm test bundle |
| [`dev/repl_test.cfg`](../dev/repl_test.cfg) | implementation — linker config for the repl test bundle |
| [`dev/repl_test_stub.s`](../dev/repl_test_stub.s) | implementation — linker scaffolding for the repl test bundle |
| [`dev/symtab_test_stub.s`](../dev/symtab_test_stub.s) | implementation — linker scaffolding for the symtab test bundle |
| [`dev/search/`](../dev/search/) | implementation — historical hash-search exploration scripts (mn6/mn7 fingerprint search, perfect-hash candidate analysis); kept for provenance, not part of the active build |
| [`dev/src.d64`](../dev/src.d64) | dependency — committed source disk image (sample programs) |
| [`dev/test.d64`](../dev/test.d64) | dependency — disk image used by integration tests |

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

`make disk` writes the compressed PRG to the D64 (D81 on m65).
`make run` launches the uncompressed PRG (no decrunch delay).

The C64 builds use exomizer's default target (`-t 64`, BASIC stub at
`$0801`); the m65 build uses `-t 65` (C65, BASIC stub at `$2001`),
which exomizer 3.1 provides ([§ The m65 PRG](#the-m65-prg)).

## Build targets

| Target | Command | Output |
|--------|---------|--------|
| All (default) | `make` | Same as `release` |
| Release | `make release` | `c64`: all three CPU variants, optimized + exomizer + D64; `m65`: the m65 PRG, optimized + exomizer + D81 |
| Debug | `make debug` | The platform's builds with `-g` (full symbols in `.lbl`) |
| Disk (single) | `make disk` | Per-build disk image in the build dir — D64 on `c64`, D81 on `m65` (for quick iteration) |
| Run | `make run` | Build release + launch in VICE (`c64`) or xmega65 (`m65`) |
| Tables | `make tables` | Regenerate `src/mn*_tables.s` via `mnemonic_tables.py` |
| Tests | `make test` | Build both debug + release, then run all pytest tests |
| MEGA65 ROM | `make m65-rom` | Copy the MEGA65 ROM from xmega65's data directory to `rom/mega65.rom` ([§ MEGA65 ROM](#mega65-rom)) |
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
| `PLATFORM` | `c64` | Target platform (`c64` / `m65`).  `m65` builds the MEGA65 PRG and D81 ([§ The m65 PRG](#the-m65-prg)) and the m65 test bundles |
| `XMEGA65` | `xmega65` | The xmega65 executable for `make run` and Tier X on `m65` (on macOS: `/Applications/xmega65.app/Contents/MacOS/xmega65`) |
| `CPU` | `6510` on `c64`, `45gs02` on `m65` | Target CPU for `run`/`disk`/`size` (`c64`: `6502` / `6510` / `65c02`; `m65`: `45gs02` only) |
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
        m65/    cse-m65.prg  cse-m65-exo.prg  ...
      debug/
        6510/   cse.prg  cse.map  cse.lbl  cse.dbg  src/*.o
        6502/   cse-6502.prg  ...
        cmos/   cse-cmos.prg  ...
        m65/    cse-m65.prg  ...
      cse.d64             distribution D64 (from release, all three C64 CPUs)
      cse-m65.d81         distribution D81 (from release, the m65 PRG)
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
| `PLATFORM` | `c64` `m65` | `c64` | Selects the platform's builds ([§ Builds and CPU sets](#builds-and-cpu-sets)); `m65` sets `PLATFORM_M65` |
| `CPU` | `c64`: `6502` `6510` `65c02`; `m65`: `45gs02` | `6510` / `45gs02` | Selects the build within the platform; sets its defines ([§ Builds and CPU sets](#builds-and-cpu-sets)) |
| `ROMSET` | `cbm` `mega` | `cbm` | ROM set for `make run` (see below) |
| `THEME` | name or hex | default | Colour theme for the REPL |
| `TAB_WIDTH` | 1..32 | `8` | Editor tab stop interval.  Must be a power of two for `col mod TAB_WIDTH` to collapse to a single `and` — non-power-of-two values compile but pay a 10-cycle modulo loop per tab render.  8 matches every C64-era toolchain convention. |

### Builds and CPU sets

A **build** is a (platform, CPU) pair.  Its **CPU set** is the set of
CPUs the assembler and disassembler serve at run time (`.cpu`, `u`);
the build's `CPU` is the set's top member.  `asm_cpu` holds one
member, as a global enumeration — **0 = 6502, 1 = 6510, 2 = 65C02,
3 = 4510, 4 = 45GS02** — so a value means the same CPU in every build.
`CPU_CEIL` is the top member's `asm_cpu` value.

| Build | `PLATFORM` / `CPU` | Defines | CPU set (`asm_cpu`) | Default `asm_cpu` | Classifier |
|---|---|---|---|---|---|
| c64-6502 | `c64` / `6502` | `CPU_6502` `USE_MN6` `CPU_CEIL=0` | 6502 (0) | 0 | `mn6` |
| c64-6510 | `c64` / `6510` | `CPU_6510` `CPU_CEIL=1` | 6502, 6510 (0, 1) | 0 | `mn7` |
| c64-65c02 | `c64` / `65c02` | `CPU_65C02` `CMOS_SUPPORT` `CPU_CEIL=2` | 6502, 6510, 65C02 (0, 1, 2) | 2 | `mn7` |
| m65-45gs02 | `m65` / `45gs02` | `PLATFORM_M65` `CPU_45GS02` `MEGA_SUPPORT` `CPU_CEIL=4` | 6502, 4510, 45GS02 (0, 3, 4) | 4 | `mn7`, m65 keys |

Exactly one `CPU_<top>` define is set per build.  It selects the
build's generated table block ([§ Table generation](#table-generation)).
m65-45gs02 is the only m65 build: its CPU set is fixed, and the 6502
and the 4510 are selected at run time.  Code
paths are gated by the feature defines: `.ifdef CMOS_SUPPORT` (65C02
paths), `.ifdef MEGA_SUPPORT` (the 4510's modes and mnemonics and the
45GS02's Q and far prefixes).  No code path is 6510-specific: the
illegal opcodes are rows of the 6510 CPU sets' tables.  A build contains no
code path, profile, delta row or opcode-map entry for a CPU outside its
set.  The one exception is the C64 `mn7` key set: it spans the 6510 and
the 65C02 names in both `mn7` builds, so the CPU gate can answer a
foreign mnemonic with `;?cpu` instead of `;?syntax`
([asm_line.md § asm_cpu × category gate matrix](modules/asm_line.md#asm_cpu--category-gate-matrix)).  `DEFAULT_CPU` is
the default `asm_cpu` column.

**`asm_cpu` × consumer** (Principle 14 of [testing.md](testing.md#principles);
a cell names the behaviour, `—` means the value cannot occur in any build
the consumer is part of):

| Consumer | 0 (6502) | 1 (6510) | 2 (65C02) | 3 (4510) | 4 (45GS02) |
|---|---|---|---|---|---|
| asm_line CPU gate ([asm_line.md](modules/asm_line.md#asm_cpu--category-gate-matrix)) | legal NMOS, NMOS profiles | + 6510 illegals | + 65C02 extension and 65C02-only keys | + 4510 extension and 4510-only keys | as 3 + Q forms and far operands |
| dasm view ([dasm.md](modules/dasm.md#design)) | 6502 view bitmap | 6510 map | 65C02 map | 4510 map | 4510 map + prefix peel |
| `.cpu` (`set_cpu`) and `u` | accepted in every build | c64-6510, c64-65c02 | c64-65c02 | m65-45gs02 | m65-45gs02 |
| `DEFAULT_CPU` (main.s) | c64-6502, c64-6510 | — | c64-65c02 | — | m65-45gs02 |
| debugger step (`cmp #2` paths) | NMOS step | NMOS step | + `JMP (a,X)`, `BRA` (c64-65c02) | — (no m65 debugger in R7 slice 1) | — (same) |

The m65 build ships as the MEGA65 PRG ([§ The m65 PRG](#the-m65-prg)).
Status: at the end of R7 slice 1 it exists as test bundles (asm_core,
mn7, dasm) only, and `PLATFORM=m65` with a PRG target is refused until
slice 2 — the platform layer — lands
([TODO § M65 slice 2](TODO.md#m65-slice-2--the-mega65-prg-r7-platform-layer)).

### The m65 PRG

The m65-45gs02 build is a native MEGA65 program: it runs in MEGA65
mode, on BASIC 65 and the MEGA65 KERNAL — not in GO64 (operator
ruling, 2026-11-17).

- **Load and start.**  The PRG loads at `$2001`.  Its BASIC 65 stub
  (`SYS 8205`) starts the loader at `$200D`, which copies the payload
  to where it runs and initialises the data area
  ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)).
  `RUN` after `LOAD "CSE-M65"` starts it, as `RUN` does on the C64.
- **Clean 6502 code.**  Every module is assembled with
  `.setcpu "6502"`, in the m65 build as in the C64 builds.  A
  45GS02-only instruction the platform layer needs — `MAP`, `EOM`,
  flat 28-bit access through `[zp],Z`, the `Z` register — is written
  as raw bytes by a macro from `src/m45_ops.inc`, the one place that
  encodes them.  An audit test refuses a 45GS02-only opcode emitted
  anywhere else ([testing.md § Tier U](testing.md#tier-u--unit-module--linking-down)).
- **Distribution.**  `make release PLATFORM=m65` writes
  `build/release/m65/cse-m65.prg`, its exomizer SFX
  `cse-m65-exo.prg` (`exomizer sfx sys -t 65`), and
  `build/cse-m65.d81`, formatted and written by `c1541` (VICE's disk
  tool writes D81 as well as D64), holding the SFX as `cse-m65`.
- **Run.**  `make run PLATFORM=m65` starts `$(XMEGA65)` with the D81
  on drive 8 and `-autoload`; a MEGA65-mode PRG at `$2001` needs no
  `-go64`.

## Table generation

Generated files must be regenerated whenever the authoritative data
changes:

| Generator | Input | Output |
|-----------|-------|--------|
| `dev/mnemonic_tables.py` | `dev/instruction_set.py`, `dev/hashes.py` | `src/mn7_tables.s`, `src/mn6_tables.s`, `src/mn_asm_tables.s`, `src/mn_modes.s`, `src/oplen_tbl.s` |
| `dev/dasm_tables.py` | `dev/instruction_set.py`, `dev/mnemonic_tables.py` (the CPU-set registry) | `src/dasm_tables.s`, `src/dasm_mne_idx.s` |

**One source, one format, sized per build.**  Every opcode fact in
every build comes from `dev/instruction_set.py`; no source file
restates one by hand.  Each generated file holds one block per CPU
set, guarded by that set's `CPU_<top>` define, so a build assembles
only its own block.  The *format* of a table is the same in every
block; its *content and size* are the CPU set's — a C64 block never
carries 4510 or 45GS02 entries.

`instruction_set.py` and `hashes.py` are shared with bbbc64 and
identical in both repositories.  `mnemonic_tables.py` and
`dasm_tables.py` are cse's own since the per-CPU-set tables: they
write ca65 only, and bbbc64 adopts the asm model in its own cycle
([TODO § M65](TODO.md#m65--the-45gs02-assembler-and-disassembler-r7-slice-1)).

### Golden files

`tests/fixtures/golden/asm_dasm_<cpu set>.json` record, per C64 CPU
set, what every instruction assembles to, how every opcode lists
under every `asm_cpu`, and the py65 cycles of each case
(`dev/capture_golden.py`).  `test_golden_asm_dasm.py` holds the
current source to them: identical output, total cycles no higher, no
case more than 10 % slower.  They are re-recorded only by a commit
that deliberately changes what a C64 build assembles or lists, or
what it costs — never to make a refactor pass; that commit states the
reason and the measured cycle change.  The size gate
(`test_size_budget.py`) is a ratchet in the same spirit: a commit
that shrinks a C64 build lowers its budget to the new size.

`tests/fixtures/golden/m65_cpu.json` records the 45GS02 as xmega65
executes it, case by case (`dev/capture_m65_golden.py`, which needs
xmega65 and a configured MEGA65 SD image); `test_mpu45gs02.py` holds
M65Emu's CPU to it.  `m65_mem.json` (`dev/capture_m65_mem.py`) records
the CPU view's translation per banking state; `test_m65memory.py`
holds `M65Memory` to it; `m65_dma.json` (`dev/capture_m65_dma.py`)
and `test_m65dma.py` do the same for the DMA controller.  They are
re-recorded when xmega65 is
updated or a case or state is added; a changed recording is a
behaviour change of the reference, which that commit states
([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)).

Run with `make tables` (both generators; the stamp depends on both
and on their inputs) or directly with `python3 dev/mnemonic_tables.py`
and `python3 dev/dasm_tables.py`.
Generated files carry a "do not edit" comment.  Their owning docs are
[mn_classify.md](modules/mn_classify.md),
[opcode_lookup.md](modules/opcode_lookup.md) and [dasm.md](modules/dasm.md).

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
for `make run`.  All ROM files live in `rom/`; the stock CBM ROMs are
listed in `.gitignore` (not committed), the Open-ROMs sets are
committed ([rom/README.md](../rom/README.md)).

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

### MEGA65 ROM

The MEGA65 ROM (`rom/mega65.rom`, 128 KB) is the m65 counterpart,
copied from the local xmega65 installation and listed in
`.gitignore`.  `make m65-rom` runs `dev/find_m65_rom.py`, which
searches xmega65's data directory (`$XEMU_MEGA65_DIR` if set, else
`~/Library/Application Support/xemu-lgb/mega65/` on macOS and
`~/.local/share/xemu-lgb/mega65/` on Linux; `MEGA65.ROM`, then
`hdos/MEGA65.ROM`), accepts only a 128 KB image with a C65/MEGA65
KERNAL, copies it and prints its version; it exits non-zero, listing
the places searched, when there is none.  The xmega65 driver finds
the SD image (`mega65.img`) in the same directory.

M65Emu takes its ROM from the post-boot snapshot, not from this
file; `dev/capture_m65_state.py` runs the discovery first and
refuses to record when the ROM xmega65 booted differs from
`rom/mega65.rom`, so the snapshot's ROM is always the one in `rom/`.

`rom/mega65_open.rom`, the MEGA65 build of the Open ROMs, is
committed next to it, pinned to an upstream commit and SHA-256.  It
holds no C65/MEGA65 KERNAL and no BASIC 65 — it boots to C64 mode —
so it cannot run the m65 PRG ([rom/README.md](../rom/README.md#mega65-roms)).

## Running tests

```sh
# All tests (builds both debug + release, checks for KERNAL ROM, runs pytest)
make test

# Quick run (direct, via pipenv — assumes builds exist).  Uses
# pyproject.toml testpaths config to include tests/unit + tests/integration.
pipenv run pytest -q

# Only Tier U (fast; no PRG build needed for bundles with their own)
pipenv run pytest tests/unit -q

# Only Tier I (needs debug PRG)
pipenv run pytest tests/integration -q

# Specific file
pipenv run pytest tests/unit/test_expr.py -q
```

See [testing.md](testing.md) for test methodology, conventions, and
the TDD Method.
