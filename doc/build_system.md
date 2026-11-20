# Build System — Toolchain, pipeline, targets, test binaries

**Template:** [subsystem](templates/subsystem.md)

## Owned files

| File | Role |
|------|------|
| [`Makefile`](../Makefile) | implementation |
| [`src/c64_trial.cfg`](../src/c64_trial.cfg) | implementation — trial linker config (size measurement) |
| [`src/c64_cse.cfg.in`](../src/c64_cse.cfg.in) | implementation — production linker config template |
| [`src/m65_cse.cfg`](../src/m65_cse.cfg) | implementation — the m65 linker config, one bounded area per region ([§ The m65 builds](#the-m65-builds)) |
| [`dev/compute_layout.py`](../dev/compute_layout.py) | implementation — computes runtime start, generates production config |
| [`dev/mnemonic_tables.py`](../dev/mnemonic_tables.py) | implementation — mnemonic table generator |
| [`dev/dasm_tables.py`](../dev/dasm_tables.py) | implementation — disassembler table generator |
| [`tests/conftest.py`](../tests/conftest.py) | implementation — test fixtures and auto-rebuild |
| [`tests/c64emu.py`](../tests/c64emu.py) | implementation — C64 emulator class (C64Emu) |
| [`tests/iec_drive.py`](../tests/iec_drive.py) | implementation — the virtual IEC drive C64Emu and M65Emu share (`Drive1541`, `IECBus`; `EmuBase.attach_drive()` puts one on a unit) |
| [`tests/emu_base.py`](../tests/emu_base.py) | implementation — `EmuBase`, what C64Emu and M65Emu share: registers, run loops, word access, symbols, screen-code decoding, `run_steps()`, the interrupt scheduler and jiffy tick, `KeyMatrix` and the keyboard calls, `place_prg()` and `load_prg()` (placement with segment relocation), `screen_text()`, `set_cursor()`, `init_cse()`, PC traps (`add_trap()`), the virtual drives (`attach_drive()`, `detach_drive()`, `drive()`) |
| [`tests/asm_dasm_runner.py`](../tests/asm_dasm_runner.py) | implementation — exhaustive asm_line / dasm_insn sweeps on py65, or M65Emu for the m65 set (output + cycles) |
| [`dev/capture_golden.py`](../dev/capture_golden.py) | implementation — records the asm/dasm golden files from a known-good tree |
| [`tests/fixtures/golden/`](../tests/fixtures/golden/) | generated — `asm_dasm_<cpu set>.json`, one per CPU set, by `dev/capture_golden.py`; `m65_cpu.json`, the 45GS02 as xmega65 executes it, by `dev/capture_m65_golden.py`; `m65_mem.json`, the CPU view's translation per banking state, by `dev/capture_m65_mem.py`; `m65_dma.json`, DMA jobs, by `dev/capture_m65_dma.py`; `m65_latches.json`, the VIC and CIA2 interrupt latches, by `dev/capture_m65_latches.py`; `m65_premise.json`, the run premise and the Hypervisor's answers per ROM, by `dev/capture_m65_premise.py`; `m65_editor.json`, the MEGA65 screen editor's API as the terminal and display seams would use it, per ROM, by `dev/capture_m65_editor.py`; back-link-exempt (JSON has no comment syntax) |
| [`tests/unit/test_golden_asm_dasm.py`](../tests/unit/test_golden_asm_dasm.py) | test contract — behaviour and speed against the golden files (TODO § M65, gates 2–3) |
| [`tests/integration/test_size_budget.py`](../tests/integration/test_size_budget.py) | test contract — the C64 and m65 release PRG sizes within budget (TODO § M65, gate 1) |
| [`tests/unit/test_build_freshness.py`](../tests/unit/test_build_freshness.py) | test contract — no test runs on a stale binary: the PRG fixtures always run `make`, objects depend on their includes, bundles on `src/*.inc` |
| [`tests/unit/test_clean_build.py`](../tests/unit/test_clean_build.py) | test contract — a fresh `git worktree` of `HEAD` builds with one `make release` (no re-run) |
| [`tests/integration/test_release_smoke.py`](../tests/integration/test_release_smoke.py) | test contract — the release 6510 PRG boots from `SYS 2061` to the main loop and shows its splash |
| [`tests/unit/test_makefile_guards.py`](../tests/unit/test_makefile_guards.py) | test contract — `make release` / `debug PLATFORM=m65` build the m65-45gs02 PRG through `src/m65_cse.cfg`; `make release` / `disk PLATFORM=m65` write the D81 with `c1541`; `make run PLATFORM=m65` (and `TARGET=m65`) starts `$(XMEGA65)` with the release PRG and the D81 on unit 8, not VICE; `make size PLATFORM=m65` reports the m65 PRG; an unknown platform is refused; each m65 region is bounded and an overflow fails the link |
| [`tests/integration/test_m65_roms.py`](../tests/integration/test_m65_roms.py) | test contract — the verified MEGA65 ROMs (§ MEGA65 ROM): with any M65Emu snapshot present, each verified ROM has one, of the current snapshot format |
| [`tests/emulator/test_m65_boot.py`](../tests/emulator/test_m65_boot.py) | test contract (Tier X) — the m65 PRG boots to `_main` in xmega65 on each ROM, the installed machine M65Emu's `install_prg()` makes; `typed_run`, the typed-key loop it shares with `test_m65_step.py` and `test_m65_asm_run.py` |
| [`tests/unit/test_build_parity.py`](../tests/unit/test_build_parity.py) | test contract — bundle `PROD_DEFS` equal the Makefile's `-D` sets (the CMOS mode has no Makefile build) |
| [`tests/unit/test_mnemonic_tables.py`](../tests/unit/test_mnemonic_tables.py) | test contract — the profile-row model of `dev/mnemonic_tables.py` |
| [`tests/unit/test_dasm_tables.py`](../tests/unit/test_dasm_tables.py) | test contract — the disassembler model of `dev/dasm_tables.py` |
| [`tests/m65emu/`](../tests/m65emu/) | implementation — M65Emu, the m65 harness: `MPU45GS02` (`mpu45gs02.py`), its decode table from the compendium fixture (`isa.py`), the CPU golden-file format (`golden.py`), `M65Memory` (`memory.py`), the devices — DMA controller, keyboard queue, CIA1 matrix port, VIC interrupt latch, CIA2 interrupt control, the Hypervisor traps (`devices.py`) —, the `M65Emu` harness, its per-ROM snapshot loading, the run premise (`enter_premise`, `run_premise`) and the m65 PRG's installed machine (`install_prg`) (`harness.py`), the raw-byte macros as the CPU decodes them (`m45_ops.py`) ([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)) |
| [`tests/xmega65.py`](../tests/xmega65.py) | implementation — the xmega65 driver (headless start on a cloned SD image, optionally with a given ROM on it and a PRG it runs or a D81 it autoloads; uartmon commands; typing through the `ADDKEY` driver, `addkeys()`; a breakpoint hit in a given base page, `run_to_page()`; the mounted D81 read back, `mounted_d81()`; why Tier X cannot run here, `missing()`) for Tier X and the M65Emu recordings |
| [`tests/unit/test_xmega65.py`](../tests/unit/test_xmega65.py) | test contract — the driver's pure parts: the FAT partition's offset from the clone's MBR, the start arguments with a ROM, a PRG and a D81, `run_to`'s registers at the hit, the `ADDKEY` driver's code |
| [`dev/capture_m65_golden.py`](../dev/capture_m65_golden.py) | implementation — records `m65_cpu.json` in xmega65 |
| [`dev/capture_m65_state.py`](../dev/capture_m65_state.py) | implementation — records M65Emu's post-boot snapshot for a given ROM and its reference runs from xmega65 into `build/m65_state/<ROM>/`, refusing a booted ROM other than the one given (default `rom/mega65.rom`) (run by hand; holds the ROM, never committed) |
| [`dev/capture_m65_dma.py`](../dev/capture_m65_dma.py) | implementation — records `m65_dma.json` (DMA jobs as xmega65 runs them) |
| [`dev/capture_m65_latches.py`](../dev/capture_m65_latches.py) | implementation — records `m65_latches.json` (the `$D019` and `$DD0D` interrupt latches as xmega65 shows them) |
| [`dev/capture_m65_premise.py`](../dev/capture_m65_premise.py) | implementation — records `m65_premise.json` (the run premise of a `RUN`-started PRG and `hyppo_getversion`'s answer, per ROM) in xmega65 |
| [`dev/capture_m65_editor.py`](../dev/capture_m65_editor.py) | implementation — records `m65_editor.json` (analysis task A1: the screen editor's jump-table entries, `SCRORG` and `PLOT` per mode and window, logical lines, an interrupted `BSOUT`, quote and insert mode, the keyboard calls, the base-page cells each call writes, per ROM) in xmega65 |
| [`tests/unit/test_m65_premise.py`](../tests/unit/test_m65_premise.py) | test contract — memory_design.md's run premise against every entry of `m65_premise.json`, the entries' agreement across ROMs, M65Emu's `hyppo_getversion` |
| [`dev/capture_m65_mem.py`](../dev/capture_m65_mem.py) | implementation — records `m65_mem.json` (the CPU view's translation per banking state) in xmega65 |
| [`tests/fixtures/m65_keys.json`](../tests/fixtures/m65_keys.json) | dependency — the PETSCII the MEGA65's typing queue presents for its keys and `$D60A`'s modifier bits, from xemu's hardware tables (the monitor cannot type a key, so no recording); the REPL and editor suites type with it; back-link-exempt (JSON) |
| [`tests/fixtures/mega65_instruction_set.csv`](../tests/fixtures/mega65_instruction_set.csv) | dependency — the MEGA65 compendium's instruction tables (bbbc64's `dev/mega65_opcode_extract.py` output, copied unchanged); `MPU45GS02`'s decoder source; back-link-exempt (CSV) |
| [`tests/unit/test_mpu45gs02.py`](../tests/unit/test_mpu45gs02.py) | test contract — `MPU45GS02` against the fixture, the 45GS02-specific behaviour and every case of `m65_cpu.json` |
| [`tests/unit/test_m65emu_harness.py`](../tests/unit/test_m65emu_harness.py) | test contract — the M65Emu harness without a snapshot: `jsr`, `run_until`, registers, `load_prg` into bank 0, `screen_text`, the I/O log, `restore()`, `load_snapshot()` refusing a missing or outdated snapshot, the per-ROM snapshot directories |
| [`tests/integration/test_m65_editor.py`](../tests/integration/test_m65_editor.py) | test contract — M65Emu against `m65_editor.json`: the recorder's own probes, run on M65Emu with each snapshot's ROM, answer as xmega65 recorded (P2 T1) |
| [`tests/integration/test_m65emu.py`](../tests/integration/test_m65emu.py) | test contract — M65Emu on the real MEGA65 KERNAL: the reference runs (`CHROUT`, the DMA scroll) match xmega65's, `GETIN` reads injected keys, and the parity calls reach the KERNAL — the jiffy tick's frame work, STOP through the matrix, RESTORE's NMI, `PLOT`; the virtual IEC drive behind the KERNAL's jump table — `OPEN` · `CHKIN` · `CHRIN`, `LOAD`, an absent unit failing without a hang (skipped without the snapshot) |
| [`tests/unit/test_m65dma.py`](../tests/unit/test_m65dma.py) | test contract — the DMA controller against every job of `m65_dma.json`, plus snapshot restore and the modes that raise |
| [`tests/unit/test_m65devices.py`](../tests/unit/test_m65devices.py) | test contract — the keyboard queue and `inject_key()`, the CIA1 matrix port, the VIC interrupt latch (`$D019`) and the CIA2 interrupt register (`$DD0D`) against `m65_latches.json`, the Hypervisor traps, device claims and the unmodelled-I/O log |
| [`tests/unit/test_m65memory.py`](../tests/unit/test_m65memory.py) | test contract — `M65Memory` against every state of `m65_mem.json`, plus colour RAM, ROM protection, the CPU port, the page-table triggers and `MAP` run on `MPU45GS02` |
| [`tests/integration/test_c64emu.py`](../tests/integration/test_c64emu.py) | test contract — exercises the C64Emu harness itself (construction, banking, `jsr`, the KERNAL buffer, `PLOT`, `GETIN`, screen access) |
| [`tests/unit/test_c64emu_disk.py`](../tests/unit/test_c64emu_disk.py) | test contract — C64Emu's virtual IEC drive: the `Drive1541` model (channels, commands, status, directory, the D64 reader) and the drive under the real KERNAL (`OPEN`/`CHKIN`/`CHRIN`/`CHKOUT`/`CHROUT`/`CLOSE`/`LOAD`/`SAVE`), `add_trap()` |
| [`tests/integration/test_c64emu_banking.py`](../tests/integration/test_c64emu_banking.py) | test contract — `$01` banking + KERNAL/BASIC ROM mapping |
| [`tests/integration/test_c64emu_cia.py`](../tests/integration/test_c64emu_cia.py) | test contract — C64-only: the matrix hidden under the character ROM (CHAREN=0) |
| [`tests/integration/test_c64emu_interrupts.py`](../tests/integration/test_c64emu_interrupts.py) | test contract — C64-only: the interrupt vector fetched through the banking |
| [`tests/integration/test_c64emu_jiffy.py`](../tests/integration/test_c64emu_jiffy.py) | test contract — C64-only: the jiffy tick makes the C64 KERNAL count `$A0`–`$A2` |
| [`tests/integration/test_emu_parity.py`](../tests/integration/test_emu_parity.py) | test contract — what `C64Emu` and `M65Emu` share (`emu_base.py`): interrupt scheduler, jiffy tick, keyboard matrix, RESTORE, key injection, `load_prg()` relocation, `set_cursor()`, `init_cse()` — parametrised over both |
| `rom/kernal_cbm.bin` | dependency — stock C64 KERNAL ROM (not committed; see `.gitignore`) |
| `rom/basic_cbm.bin` | dependency — stock C64 BASIC ROM (not committed) |
| `rom/chargen_cbm.bin` | dependency — stock C64 character ROM (not committed) |
| [`rom/README.md`](../rom/README.md) | implementation — the ROM files: where each comes from, its licence, whether it is committed |
| [`rom/kernal_mega.bin`](../rom/kernal_mega.bin) | dependency — Open ROMs KERNAL, C64 (generic) build, pinned (committed); back-link-exempt (binary) |
| [`rom/basic_mega.bin`](../rom/basic_mega.bin) | dependency — Open ROMs BASIC, C64 (generic) build, pinned (committed); back-link-exempt (binary) |
| [`rom/chargen_mega.bin`](../rom/chargen_mega.bin) | dependency — Open ROMs character ROM (PXL font 2.3), pinned (committed); back-link-exempt (binary) |
| [`tests/unit/test_open_roms.py`](../tests/unit/test_open_roms.py) | test contract — the committed C64 Open ROMs are the pinned upstream files |
| `rom/mega65.rom` | dependency — the MEGA65 ROM xmega65 uses (not committed; copied by `make m65-rom`) |
| [`rom/mega65_open.rom`](../rom/mega65_open.rom) | dependency — MEGA65 Open ROMs, MEGA65 build, pinned upstream commit (committed; C64 mode only, see [rom/README.md](../rom/README.md#mega65-roms)); back-link-exempt (binary) |
| [`dev/find_m65_rom.py`](../dev/find_m65_rom.py) | implementation — finds the MEGA65 ROM in xmega65's data directory and copies it to `rom/mega65.rom` (`make m65-rom`) |
| [`tests/unit/test_find_m65_rom.py`](../tests/unit/test_find_m65_rom.py) | test contract — the MEGA65 ROM discovery: search order, acceptance, copy; the committed Open ROM's pin |
| [`dev/instruction_set.py`](../dev/instruction_set.py) | implementation — authoritative opcode database; back-link-exempt (shared verbatim with bbbc64) |
| [`dev/hashes.py`](../dev/hashes.py) | implementation — hash function definitions; back-link-exempt (shared verbatim with bbbc64) |
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
| [`dev/cse_io_test_stub.s`](../dev/cse_io_test_stub.s) | implementation — linker scaffolding for the cse_io test bundle |
| [`dev/dasm_test_stub.s`](../dev/dasm_test_stub.s) | implementation — linker scaffolding for the dasm test bundle |
| [`dev/symtab_test_stub.s`](../dev/symtab_test_stub.s) | implementation — linker scaffolding for the symtab test bundle |
| [`dev/audit_doc.py`](../dev/audit_doc.py) | implementation — runs the doc audits below in one report |
| [`dev/audit_doc_depends_on.py`](../dev/audit_doc_depends_on.py) | implementation — doc audit: module docs' depends-on lists against the sources' imports, both directions |
| [`dev/audit_doc_links.py`](../dev/audit_doc_links.py) | implementation — doc audit: every corpus link resolves (CDD Maintenance item 4) |
| [`dev/audit_doc_module_bss.py`](../dev/audit_doc_module_bss.py) | implementation — doc audit: BSS sizes module docs state against the build |
| [`dev/audit_doc_numbers.py`](../dev/audit_doc_numbers.py) | implementation — doc audit: numerical claims against the code |
| [`dev/audit_doc_owned_files.py`](../dev/audit_doc_owned_files.py) | implementation — the ownership audit (CDD Maintenance item 2, [README.md § Ownership](README.md#ownership)) |
| [`dev/check_deps.py`](../dev/check_deps.py) | implementation — layer checker: every src import goes to the same or a lower layer of architecture.md's Modules table |
| [`tests/unit/test_check_deps.py`](../tests/unit/test_check_deps.py) | test contract — the layer checker and the Depends-on audit's import → doc direction, on small trees and the real tree |
| [`tests/unit/test_audit_owned_files.py`](../tests/unit/test_audit_owned_files.py) | test contract — the ownership audit on small trees: completeness, uniqueness, directory rows, back-links, exemptions, local-file rows |
| [`dev/audit_doc_structure.py`](../dev/audit_doc_structure.py) | implementation — doc audit: tone and structure (CDD Maintenance item 1) |
| [`dev/audit_doc_symbols.py`](../dev/audit_doc_symbols.py) | implementation — doc audit: code symbols named in docs exist |
| [`dev/audit_phase_markers.py`](../dev/audit_phase_markers.py) | implementation — historical-marker sweep (CDD Maintenance item 9) |
| [`dev/probe_chrout_repeated.py`](../dev/probe_chrout_repeated.py) | implementation — investigation probe, run by hand against the real KERNAL (not a test): where CHROUT lands output rows after an `LDTB1` reset |
| [`dev/probe_chrout_zp.py`](../dev/probe_chrout_zp.py) | implementation — investigation probe, run by hand against the real KERNAL (not a test): which KERNAL ZP bytes CHROUT mutates |
| [`dev/probe_ldtb1_encoding.py`](../dev/probe_ldtb1_encoding.py) | implementation — investigation probe, run by hand against the real KERNAL (not a test): what the KERNAL puts in `LDTB1` after its init |
| [`dev/probe_plot_with_corrupt_ldtb1.py`](../dev/probe_plot_with_corrupt_ldtb1.py) | implementation — investigation probe, run by hand against the real KERNAL (not a test): PLOT with a corrupt line-link table |
| [`dev/search/`](../dev/search/) | implementation — historical hash-search exploration scripts (mn6/mn7 fingerprint search, perfect-hash candidate analysis); kept for provenance, not part of the active build |
| [`dev/src.d64`](../dev/src.d64) | dependency — committed source disk image (sample programs); back-link-exempt (binary) |
| [`dev/test.d64`](../dev/test.d64) | dependency — disk image used by integration tests; back-link-exempt (binary) |
| [`dev/search/mn6_fingerprint_collisions.txt`](../dev/search/mn6_fingerprint_collisions.txt) | generated — output of the hash-search scripts above; back-link-exempt (generated data) |
| [`dev/search/mn6_hash_candidates.txt`](../dev/search/mn6_hash_candidates.txt) | generated — output of the hash-search scripts above; back-link-exempt (generated data) |

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
flat image after the BASIC header at $0801 — the addresses are
wrong, but the segment **sizes** in `trial.map` are correct.

`compute_layout.py` reads the sizes from `trial.map` and computes

    RUNTIME_START = ($D000 − (CODE + RODATA + DATA + PAD + BSS)) & $FF00
    PAD           = (CODE + RODATA + DATA) & 1

— rounded down to a page boundary, because the editor's `BUF_END`
checks compare the high byte only.  It fills three placeholders of
`c64_cse.cfg.in` to produce `build/<profile>/<cpu>/c64_cse.cfg`:
`@@RUNTIME_START@@`, `@@BSS_START@@` (`RUNTIME_START` + CODE +
RODATA + DATA, rounded up to an even address: the BSS segment is
2-aligned, [disk.md § Caveats](modules/disk.md#caveats); `PAD`
above is that byte) and `@@BUF_FLOOR@@` (the source/output split of the
workspace: `$0800` + one ninth of the workspace, rounded down to a
page).  It prints the result as a `layout:` line, and stops the
build when `RUNTIME_START` falls below `$0900`.

Pass 2 (production): `ld65 -C build/<profile>/<cpu>/c64_cse.cfg`
links with the correct runtime addresses.  CODE and RODATA use ld65's
`load`/`run` address split — they are placed in the file directly
after the loader, but all symbol references resolve to the runtime
address.  The loader copies them at boot.  The figures of a build
(runtime start, segment sizes, free regions) are the `layout:` line
and `make size`; this document states none, since every change moves
them.

**Incremental builds.**  Each object's prerequisites are its source,
every file it `.include`s (`macros.inc`, `log.inc`, `dasm_mne_idx.s`,
`version.inc` — recorded by `ca65 --create-dep` in a `.d` file beside
the object), the flags stamp and `version.inc`.  A changed include
rebuilds exactly its includers; a no-op `make debug` takes a fraction
of a second.

**Clean builds.**  On a fresh checkout (no `build/`) a single `make`
(or `make release debug`) succeeds; no re-run is needed.  The object
directory `build/<profile>/<cpu>/src` is an order-only prerequisite
named without a trailing slash: with a trailing slash, GNU make 3.81
(macOS's `/usr/bin/make`) stops matching the pattern rule once the
first object's recipe has created the directory, and every later
object fails with "No rule to make target".
`tests/unit/test_clean_build.py` builds a fresh `git worktree` of
`HEAD` once.

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

1. **Source string** — the Makefile writes
   `build/<profile>/<cpu>/version.inc` containing
   `.define VERSION_STRING "<value>"` whenever the flags stamp
   changes (`VERSION` is part of it).
   `strings.s` does `.include "version.inc"` (via `ca65 -I
   $(BUILD)`) and uses the macro in the `VERSION_STR` byte
   sequence.  Result: the splash line reads `cse v<value> by cr`.
2. **Disk label** — the `_dist` and `disk` Makefile targets pass
   `"cse $(VERSION),01"` to `c1541 -format`, so the D64 label
   (visible in `$` listings) carries the version.

PRG filenames (`cse.prg`, `cse-6502.prg`, `cse-m65.prg`) are
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

Mechanism: the Makefile passes `-DINTROSPECT` to `ca65` when
`INTROSPECT=1` (any other value, `INTROSPECT=0` included, leaves it
off), which ca65 `.ifdef`s in [repl.s](../src/repl.s)
`zp_stage_prep` and `zp_poke`.  In the INTROSPECT build both helpers become
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
loader run normally.  About a third smaller than the raw PRG
(the `_one` line of `make release` prints both sizes).

`make disk` writes the compressed PRG to the D64.
`make run` launches the uncompressed PRG (no decrunch delay).

Exomizer serves the C64 builds only, with its default target (`-t
64`, BASIC stub at `$0801`).  The m65 build ships uncompressed
([§ The m65 builds](#the-m65-builds)).

## Build targets

| Target | Command | Output |
|--------|---------|--------|
| All (default) | `make` | Same as `release` |
| Release | `make release` | `c64`: both CPU variants, optimized + exomizer + D64; `m65`: the m65 PRG + D81, uncompressed |
| Debug | `make debug` | The platform's builds with `-g` (full symbols in `.lbl`) |
| Disk (single) | `make disk` | `c64`: a D64 per build in the build dir (for quick iteration); `m65`: as `release`, the distribution D81 |
| Run | `make run` | Build release + launch in VICE (`c64`) or xmega65 (`m65`) |
| Tables | `make tables` | Run both generators, `dev/mnemonic_tables.py` and `dev/dasm_tables.py`, when a generator or its input is newer than `build/.tables.stamp` ([§ Table generation](#table-generation)) |
| Tests | `make test` | Build both debug + release, check the ROMs, then run all pytest tests |
| Check ROMs | `make check-roms` | Fail with copy instructions when `rom/kernal_cbm.bin` is missing (a prerequisite of `test`) |
| MEGA65 ROM | `make m65-rom` | Copy the MEGA65 ROM from xmega65's data directory to `rom/mega65.rom` ([§ MEGA65 ROM](#mega65-rom)) |
| Size | `make size` | Size breakdown of selected release PRG (`CPU=`): the segments in file order (their sum the PRG's size), the modules, the categories; the memory map on `c64` only |
| Clean | `make clean` | Remove `build/` directory |
| Clean tables | `make clean-tables` | Remove the generated table sources in `src/` and the tables stamp |
| Themes | `make themes` | List available colour themes |
| Help | `make help` | List all targets and options |

Every target works with `PLATFORM=m65` ([§ The m65 builds](#the-m65-builds)).

### Build profiles

Two build profiles share the same `_one` sub-target in the Makefile.
Only the output directory and assembler flags differ:

| Profile | Flags | Exomizer | Symbols in `.lbl` |
|---------|-------|----------|-------------------|
| `release` | `-t c64` | yes (C64 builds) | ~410 (exports only) |
| `debug` | `-g -t c64 -DDEBUG` | no | ~2040 (all labels) |

The `-g` flag tells ca65 to embed debug symbols in `.o` files.
When linked with `ld65 -Ln`, the resulting `.lbl` file contains
every label — exported, module-internal, and `@local` — at its
absolute address.

### Command-line options

| Variable | Default | Effect |
|----------|---------|--------|
| `PLATFORM` | `c64` | Target platform (`c64` / `m65`).  `m65` builds the MEGA65 PRG and D81 ([§ The m65 builds](#the-m65-builds)) and the m65 test bundles.  Every target works on m65 (`release`, `debug`, `disk`, `run`, `size`; `help`, `themes`, `clean`, `clean-tables`, `tables`, `m65-rom`, `check-roms`); an unknown platform is refused.  `TARGET=` on the command line is a synonym (`make run TARGET=m65`); giving both with different values is an error |
| `XMEGA65` | `/Applications/xmega65.app/Contents/MacOS/xmega65` | The xmega65 executable: `make run PLATFORM=m65` starts it, and `tests/xmega65.py` reads the same environment variable (Tier X, the M65Emu recordings) |
| `CPU` | `6510` on `c64`; `45gs02` on `m65` (fixed) | Target CPU for `run`/`disk`/`size` (`c64`: `6502` / `6510`; any other is refused) |
| `THEME` | `CLOUDY` | Named theme or 3-digit hex code (`make themes` for list) |
| `TAB_WIDTH` | `8` | Editor tab-stop column width |
| `VERSION` | `0.1` | Version string embedded in splash + D64 label |
| `ROMSET` | `cbm` | KERNAL/BASIC/CHARGEN set for `run` (`cbm` / `mega`) |
| `INTROSPECT` | unset | `=1` disables the user-ZP redirect in `m`/`.` (see above); any other value leaves it on |

`PLATFORM`, `CPU`, `THEME`, `TAB_WIDTH`, `VERSION`, `INTROSPECT` and the profile
form `BUILD_FLAGS`, which the Makefile records in the flags stamp
`build/<profile>/<cpu>/.build_flags`; a value that differs from the
recorded one reassembles every object of that build.  `ROMSET` only
selects the ROMs `run` passes to VICE.

The tools are variables too: `CA65`, `LD65`, `PYTHON` (`pipenv run
python`), `PYTEST` (`pipenv run pytest`), `VICE` (`x64sc`), `C1541`,
`EXOMIZER`.

### Directory layout

    build/
      release/
        6510/   cse.prg  cse-exo.prg  cse.map  cse.lbl  cse.dbg
                trial.prg  trial.map  c64_cse.cfg  version.inc
                .build_flags  src/*.o  src/*.d
        6502/   cse-6502.prg  cse-6502-exo.prg  ...
        m65/    cse-m65.prg  cse.map  cse.lbl  cse.dbg  version.inc
                .build_flags  src/*.o  src/*.d  (no -exo.prg, no trial)
      debug/
        6510/   cse.prg  cse.map  cse.lbl  cse.dbg  ...  (no -exo.prg)
        6502/   cse-6502.prg  ...
        m65/    cse-m65.prg  ...
      cse.d64             distribution D64 (from release, both C64 CPUs)
      cse-m65.d81         distribution D81 (from release, the m65 PRG)
      .tables.stamp       `make tables`
      version.inc         the test bundles' (`VERSION_STRING "test"`)
      <bundle>.bin .map .lbl .flags
                          test bundles (`conftest.Bundle`, built with -g;
                          list in testing.md § conftest bundles)
      <module>_<tag>.o    their objects
      m65_state/<ROM>/    M65Emu's post-boot snapshots, one per ROM (dev/capture_m65_state.py)

PRG names are the same in both profiles — the `release/` vs `debug/`
directory disambiguates.

A C64 cartridge is a planned future target (R5) using the same source
with a different linker config.

## Build-time options

Passed as `make OPTION=value`:

| Option | Values | Default | Effect |
|--------|--------|---------|--------|
| `PLATFORM` | `c64` `m65` | `c64` | Selects the platform's builds ([§ Builds and CPU sets](#builds-and-cpu-sets)); sets `PLATFORM_C64` or `PLATFORM_M65` |
| `CPU` | `c64`: `6502` `6510`; `m65`: `45gs02` (fixed) | `6510` / `45gs02` | Selects the build within the platform; sets its defines ([§ Builds and CPU sets](#builds-and-cpu-sets)) |
| `ROMSET` | `cbm` `mega` | `cbm` | ROM set for `make run` (see below) |
| `THEME` | name or hex | `CLOUDY` | Colour theme for the REPL |
| `TAB_WIDTH` | 1 2 4 8 16 32 | `8` | Editor tab stop interval.  A power of two, so `col mod TAB_WIDTH` is a single `and`; any other value is a build error.  8 matches every C64-era toolchain convention. |

### Builds and CPU sets

A **build** is a (platform, CPU) pair.  Its **CPU set** is the set of
CPUs the assembler and disassembler serve at run time (`.cpu`, `u`);
the build's `CPU` is the set's top member.  `asm_cpu` holds one
member, as a global enumeration — **0 = 6502, 1 = 6510, 2 = 65C02,
3 = 4510, 4 = 45GS02** — so a value means the same CPU in every build.
`CPU_CEIL` is the top member's `asm_cpu` value.

| Build | `PLATFORM` / `CPU` | Defines | CPU set (`asm_cpu`) | Default `asm_cpu` | Classifier |
|---|---|---|---|---|---|
| c64-6502 | `c64` / `6502` | `PLATFORM_C64` `CPU_6502` `USE_MN6` `CPU_CEIL=0` | 6502 (0) | 0 | `mn6` |
| c64-6510 | `c64` / `6510` | `PLATFORM_C64` `CPU_6510` `CPU_CEIL=1` | 6502, 6510 (0, 1) | 0 | `mn7` |
| m65-45gs02 | `m65` / `45gs02` | `PLATFORM_M65` `CPU_45GS02` `MEGA_SUPPORT` `CPU_CEIL=4` | 6502, 4510, 45GS02 (0, 3, 4) | 4 | `mn7gs` (the m65 keys) |
| *the CMOS mode* (no build) | — | `CPU_65C02` `CMOS_SUPPORT` `CPU_CEIL=2` | 6502, 65C02 (0, 2) | 2 | `mn7` |

No target has a 65C02.  The assembler and the disassembler keep a
**CMOS mode** for a later port to a 65C02 machine: the CPU set
{6502, 65C02}, its generated table blocks and its `CMOS_SUPPORT`
paths, built only as test bundles (`asm_core`, `dasm`, `mn7`,
`asm_src`; [testing.md § conftest bundles](testing.md#conftest-bundles))
and held to its golden file like every set.  No PRG, budget or hash
belongs to it; the platform modules (the debugger, the REPL, the
platform layer) have no 65C02 paths.

Exactly one `PLATFORM_<platform>` define is set per build — the C64
builds carry `PLATFORM_C64` as the m65 build carries `PLATFORM_M65`,
so a platform body is always selected by its own name
([platform_layer.md § Platforms and defines](platform_layer.md#platforms-and-defines)).
Exactly one `CPU_<top>` define is set per build.  It selects the
build's generated table block ([§ Table generation](#table-generation)).
The m65 platform has one build, **m65-45gs02** — its CPU set fixed,
the 6502 and the 4510 selected at run time; the 6510 is not in it, as
the 45GS02 runs none of the 6510's illegal opcodes.  Code paths are
gated by the feature defines: `.ifdef CMOS_SUPPORT` (the CMOS mode's
65C02 paths), `.ifdef MEGA_SUPPORT` (the 4510's modes and mnemonics —
the 65C02's among them — and the 45GS02's Q and far prefixes).  No
code path is 6510-specific: the illegal opcodes are rows of the 6510
set's tables.  A build contains no code path, profile, delta row,
opcode-map entry or classifier key for a CPU outside its set: a
mnemonic only another CPU has is no word (`;?syntax`), one of a set
member the current `asm_cpu` lacks is `;?cpu`
([asm_line.md § asm_cpu × category gate matrix](modules/asm_line.md#asm_cpu--category-gate-matrix)).
`DEFAULT_CPU` is the default `asm_cpu` column.

**`asm_cpu` × consumer** (Principle 14 of [testing.md](testing.md#principles);
a cell names the behaviour, `—` means the value cannot occur in any build
the consumer is part of):

| Consumer | 0 (6502) | 1 (6510) | 2 (65C02) | 3 (4510) | 4 (45GS02) |
|---|---|---|---|---|---|
| asm_line CPU gate ([asm_line.md](modules/asm_line.md#asm_cpu--category-gate-matrix)) | legal NMOS, NMOS profiles | + 6510 illegals | + 65C02 extension and 65C02-only keys (the CMOS mode) | + 4510 extension and 4510-only keys | as 3 + Q forms and far operands |
| dasm view ([dasm.md](modules/dasm.md#design)) | 6502 view bitmap | 6510 map | 65C02 map (the CMOS mode) | 4510 map | 4510 map + prefix peel |
| `.cpu` (`set_cpu`) and `u` | accepted in every set | c64-6510 | the CMOS mode | m65-45gs02 | m65-45gs02 |
| `DEFAULT_CPU` (main.s) | c64-6502, c64-6510 | — | the CMOS mode | — | m65-45gs02 |
| debugger step ([debugger.md § Next-PC](modules/debugger.md#next-pc)) | NMOS step (c64); m65: the 45GS02 step | NMOS step | — | the 45GS02 step | the 45GS02 step (m65 does not read `asm_cpu`) |

The m65 build ships as a PRG and a D81
([§ The m65 builds](#the-m65-builds)).  `PLATFORM=m65` builds the
m65-45gs02 PRG and its D81; `conftest.PROD_DEFS` holds its defines
beside the C64 sets' and the CMOS mode's, and its test bundles run on M65Emu's
`MPU45GS02` (its far stores need the 45GS02).

### The m65 builds

The m65 build is a native MEGA65 program: it runs in MEGA65
mode on the MEGA65 KERNAL, within the ROM floor of
[platform_layer.md § Platforms and defines](platform_layer.md#platforms-and-defines)
— not in GO64.  Where its
parts live at run time is [memory_design.md § Memory Map —
m65](memory_design.md#memory-map--m65-mega65-mode); how its
platform bodies are selected is [platform_layer.md](platform_layer.md).

**Defines.**  `PLATFORM_M65` and m65-45gs02's CPU-set defines
([§ Builds and CPU sets](#builds-and-cpu-sets)).
ca65 assembles it with `-t c64`, as the C64 builds: the target
selects ca65's string translation to PETSCII, which MEGA65 mode
shares, and cse sets its CPU with `.setcpu` in every module.

**Clean 6502 code.**  Every module is assembled with
`.setcpu "6502"`; the 45GS02-only instructions the platform bodies
need are raw bytes from `src/m45_ops.inc`
([platform_layer.md § Raw-byte instructions](platform_layer.md#raw-byte-instructions)).

**Segments and the linker config** (`src/m65_cse.cfg`, used as it
is: there is nothing to compute): one MEMORY area per place the code
runs, each bounded by its region's size, so an overflow fails the
link instead of overwriting the neighbour:

| Segment(s) | Runs at (CPU view) | Lives in | Bound | Load |
|---|---|---|---|---|
| `LOADADDR`, `EXEHDR` | `$2001` | bank 0, the PRG image | — | the file |
| `LOADER` | `$200D` | bank 0, the PRG image (discarded) | — | the file |
| `STUB` | `$1FB0` | `0.1FB0` | `$0050` (to `0.1FFF`) | the file, copied by the loader |
| `CODE`, `RODATA` | `$2000` | `3.2000` | `$6000` (24 K) | the file, DMA'd by the loader |
| `KDATA` | `$8000` | the data window `3.8000` | with `KCODE` and `BSS`: `$1F00`, to `SYM_TABLE` | the file, DMA'd by the loader |
| `KCODE` | after `KDATA` | the data window | (the same area) | the file, DMA'd by the loader with `KDATA`, as one block |
| `BSS` | after `KCODE` | the data window | (the same area) | cleared by the loader |

`KCODE` is code that runs in the data window: the code window
(`$2000–$7FFF`) had 1.4 K left at slice 3's F2, which the banking
work alone would fill, while the data window, mapped in CSE's own
map like the code window, had 6 K.  m65-only code that is not on a
hot path goes there (the CPU lens, the flat-address helpers, `M`);
the m65 test bundles' config (`dev/m65_test.cfg`) has the segment
too.
| `ZEROPAGE` | `$00` (base-page offsets) | CSE's base page `0.1F00` (`B = $1F`) | `$00B0`, below the resident stub | cleared by the loader |

The source region (`2.4000–2.BFFF`), the directory buffer
(`2.D000–2.FFFF`) and the reserve `3.C000–3.CFFF` are not segments:
they hold nothing at load time and are reached through far pointers.

There is no two-pass layout on m65 (`compute_layout.py` is the C64
builds' runtime-start computation): every run address is fixed by
the region it lives in.  The C64's KBSS homes under the KERNAL
(symbol table, name heap, REPL screen save) are fixed homes at the top
of the data window on m65, constants as on the C64
([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode));
the cold-init ZP snapshot has no m65 counterpart.  CSE's zero page is
the same layout as the C64's with each far pointer widened to 4 bytes
([zp.md](modules/zp.md)).

**Outputs.**  `make release PLATFORM=m65` and `make debug
PLATFORM=m65` each build the one m65 build into
`build/<profile>/m65/`: `cse-m65.prg`, `cse.map`, `cse.lbl` (the
debug profile with `-g`), `cse.dbg`.  `PLATFORM=m65` selects the
m65-45gs02 CPU set whatever `CPU` says.

**Load and start.**  The PRG loads at `$2001`.  Its BASIC 65 stub
(`SYS 8205`) starts the loader at `$200D`, which installs the stub,
the code and the data and enters `_main` through the stub
([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)).
`RUN` after `LOAD "CSE-M65"` starts it, as `RUN` does on the C64.

**Distribution — raw, no exomizer.**  The 1581 and the disk images
load fast enough that packing buys nothing; every m65 output is
uncompressed.

- `make release PLATFORM=m65` writes `build/release/m65/cse-m65.prg`.
- `make release PLATFORM=m65` and `make disk PLATFORM=m65` write
  `build/cse-m65.d81` too, formatted and written by `c1541` (VICE's
  disk tool writes D81 as well as D64; disk name `cse <version>`, id
  `01`), holding the PRG as `cse-m65`: `DLOAD "CSE-M65"` and `RUN`
  start it.
- No cartridge yet: a later release's, from A3's record
  ([TODO § Analysis tasks](TODO.md#analysis-tasks-own-cycles-their-results-are-doc-deltas)).

**Run.**  `make run PLATFORM=m65` builds the release PRG and the D81
and starts `$(XMEGA65)` with both: `-prg build/release/m65/cse-m65.prg
-prgmode 65` loads the PRG into the MEGA65's memory and RUNs it once
BASIC 65 is up (a MEGA65-mode PRG at `$2001` needs no `-go64`), and
`-8 build/cse-m65.d81` mounts the D81 as unit 8 — the C64 run's
`-autostart` PRG plus `-8` D64.  xmega65 starts
with its own configuration — the user's SD image and ROM, its window,
its keymap — so the run is what the user sees on a MEGA65.  In
xmega65's default keymap RUN/STOP is the PC's End key (fn+→ on a Mac),
RESTORE Page Down, and the PC's Escape is the MEGA65's ESC.  Automation never starts xmega65 without
`-headless` ([testing.md § Tier X](testing.md#tier-x--xmega65-m65-automated));
`make run` is for people.

**Gates.**  The C64 release PRGs stay byte-identical through every
m65 step ([platform_layer.md § Gates](platform_layer.md#gates)); the
m65 PRG's two banks are bounded by the linker as above, and its size
joins `BUDGET` once it first builds ([§ Size gate](#size-gate)).

## Table generation

Generated files must be regenerated whenever the authoritative data
changes:

| Generator | Input | Output |
|-----------|-------|--------|
| `dev/mnemonic_tables.py` | `dev/instruction_set.py`, `dev/hashes.py` | `src/mn7_tables.s`, `src/mn6_tables.s`, `src/mn_asm_tables.s`, `src/mn_modes.s`, `src/oplen_tbl.s`, `src/cpu_set.inc` (the mode and `asm_cpu` constants, the sets' switches) |
| `dev/dasm_tables.py` | `dev/instruction_set.py`, `dev/mnemonic_tables.py` (the CPU-set registry) | `src/dasm_tables.s`, `src/dasm_mne_idx.s` |

**One source, one format, sized per build.**  Every opcode fact in
every build comes from `dev/instruction_set.py`; no source file
restates one by hand.  Each generated file holds one block per CPU
set that uses it, guarded by that set's `CPU_<top>` define, so a build
assembles only its own block (`mn6_tables.s` has the one `{6502}`
block, `mn7_tables.s` the 6510, 65C02 and m65 blocks — the C64
and CMOS ones over one `T` (the 6510 and 65C02 names), each block
with its own set's keys, the m65 one over `mn7gs`, mn7's form with its
own `T`, defined in `mnemonic_tables.py`).  The *format* of a table is the same in every
block; its *content and size* are the CPU set's — a C64 block never
carries 4510 or 45GS02 entries.  The m65 block adds what only its set
needs: a third mask plane, the zone bounds, the Q map,
byte-wide dasm modes, and its tables in KDATA.  The exception is
`oplen_tbl.s`: one 64-byte table (2 bits per opcode) shared by both
C64 builds, the 6510's lengths (every 6502 row is a 6510 row), and
none for m65, whose debugger steps by the disassembler's 45GS02
length.  A set
is validated derive-or-die: the tables must reproduce every row of
every view of the set (on m65 the prefixed rows too) and mask out
everything else.

`instruction_set.py` and `hashes.py` are shared with bbbc64 and
identical in both repositories.  `mnemonic_tables.py` and
`dasm_tables.py` are cse's own since the per-CPU-set tables: they
write ca65 only, and bbbc64 adopts the asm model in its own cycle
([TODO § M65](TODO.md#m65--the-45gs02-assembler-and-disassembler-r7-slice-1)).

### Golden files

`tests/fixtures/golden/asm_dasm_<cpu set>.json` record, per CPU set,
what every instruction assembles to, how every opcode lists under
every `asm_cpu`, and the cycles of each case (`dev/capture_golden.py`):
py65's for the C64 sets, `MPU45GS02`'s — one per instruction — for the
m65 set (`asm_dasm_45gs02.json`; M65Emu has no cycle model, so the
m65 speed gate is an instruction-count gate; the
45GS02's instructions include the prefixed forms, its listing every
prefix sequence the peel accepts).  `test_golden_asm_dasm.py` holds the
current source to them: identical output, total cycles no higher, no
case more than 10 % slower.  They are re-recorded only by a commit
that deliberately changes what a build assembles or lists, or what
it costs — never to make a refactor pass; that commit states the
reason and the measured cycle change.

### Size gate

`tests/integration/test_size_budget.py` holds each C64 release PRG
(unpacked) to its byte budget, `BUDGET`.  The budget is a ratchet, in
the spirit of the golden files:

- **Shrink.**  A commit that makes a C64 build smaller lowers that
  build's budget to the new size, in the same commit, so the saving
  cannot silently erode.
- **Growth.**  A deliberate C64 feature that makes a build bigger
  raises that build's budget in a commit of its own, whose message
  states the feature and the growth in bytes per build.  A failing
  size gate is never fixed by raising the budget inside the commit
  that caused it.
- **m65 work** may not grow any C64 build at all
  ([TODO § M65](TODO.md#m65--the-45gs02-assembler-and-disassembler-r7-slice-1),
  acceptance gate 1); a C64 defect it finds is fixed as a C64 change
  under *Growth*, in its own commit; moving the C64 builds onto the platform layer
  leaves them byte-identical ([platform_layer.md § Gates](platform_layer.md#gates)).
- **The m65 build**, m65-45gs02, is in `BUDGET` under the same
  ratchet; its code window
  and data window are bounded by the linker as well
  ([§ The m65 builds](#the-m65-builds)).
- **Parallel fix tracks.**  When independent fixes run in parallel
  worktrees, every worktree is cut from the integration branch, none
  touches `BUDGET`, and the budget is re-measured once after the
  merge, in a commit of its own.  After the merge, the ownership audit
  (`dev/audit_doc.py`; a modify/delete conflict can resurrect a
  deleted file) and the full suite run before any of the tracks' TODO
  items is ticked.

`tests/fixtures/golden/m65_cpu.json` records the 45GS02 as xmega65
executes it, case by case (`dev/capture_m65_golden.py`, which needs
xmega65 and a configured MEGA65 SD image); `test_mpu45gs02.py` holds
M65Emu's CPU to it.  `m65_mem.json` (`dev/capture_m65_mem.py`) records
the CPU view's translation per banking state; `test_m65memory.py`
holds `M65Memory` to it; `m65_dma.json` (`dev/capture_m65_dma.py`)
and `test_m65dma.py` do the same for the DMA controller, `m65_latches.json`
(`dev/capture_m65_latches.py`) and `test_m65devices.py` for the two
interrupt latches, `m65_premise.json` (`dev/capture_m65_premise.py`,
one entry per ROM) and `test_m65_premise.py` for the run premise and
the Hypervisor's answers.  They are
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

## Release pre-flight

Before a tag without an `-rc` suffix — a public release — every item
holds; an `-rc` tag needs the first four.

1. `python3 dev/audit_doc.py --quiet` reports every gating audit
   clean (required, not recommended, for a release tag).
2. The full suite passes (`pytest -q`, and `pytest tests/emulator` on
   both verified ROMs for a release with an m65 build).
3. `LICENSE` is present, with the right author and year; every
   committed binary has its provenance documented, as
   [`rom/README.md`](../rom/README.md) does for the ROMs.
4. The user-facing examples (the root `README.md`,
   [assembler_syntax.md](assembler_syntax.md)) use only workspace or
   KERNAL addresses, never CSE's own runtime image
   ([memory_design.md](memory_design.md); CDD Maintenance item 8,
   *Semantic verification*).
5. The release candidates' tags are pushed, and the release page
   carries the binaries (the D64 and the PRGs; the D81 and m65 PRG
   with an m65 release).

Origin: the v0.1 release (Phase 26), where `LICENSE` and the ROM
attribution were caught at the last minute and three `$C000`
examples in the README would have assembled over CSE.

## ROM compatibility constraints

These apply to all code and apply regardless of build target:

- **Put lookup tables in `RODATA`.**  RODATA lives in ROM on the
  planned CRT target — anything written at runtime must be in BSS.
- **No self-modifying code.**  All routines work from ROM.  Runtime
  state lives in ZP or BSS, never in patched inline code.
- **Minimize initialized data.**  Prefer runtime initialization.
  The loader zeroes BSS; the DATA segment is empty (all runtime
  state is in BSS, all constants in RODATA).
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
| `mega` | `kernal_mega.bin` | `basic_mega.bin` | `chargen_mega.bin` | Open ROMs, C64 (generic) build — the `mega` name is the set's, not the platform's |

ROM filenames follow the pattern `{type}_{romset}.bin`.  Adding a
new ROM set (e.g. `ROMSET=jiffy`) only requires dropping three
files with matching names — no Makefile changes needed.

Usage:

    make run                # stock CBM ROMs (default)
    make run ROMSET=mega    # Open ROMs (C64 build)

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
6510 PRG (`build/debug/6510/cse.prg`, the default build), which has
full symbol coverage via its `.lbl` file (~2040 symbols).  The
`cse_release_prg` fixture serves the shipping binary:
`test_release_smoke.py` boots the release 6510 PRG from its `SYS`
target through the loader to the main loop.

Test bundles are built by `conftest.Bundle` with `ca65 -g` and
`ld65 -Ln`, producing their own `.lbl` files with complete symbol
coverage; the list of bundles and their variants is
[testing.md § conftest bundles](testing.md#conftest-bundles).

### How it works

1. The PRG fixtures (`cse_prg`, `cse_release_prg`,
   `cse_prg_per_cpu`) run `make debug` (or `make release`) once per
   session, whether or not the PRG exists — make is incremental, so
   the PRG is never older than its sources.  A bundle rebuilds when it
   is missing, older than a source, a shared include (`src/*.inc`),
   a listed generated dependency or the linker config, or built with
   another `-D` set (recorded in its `.flags` stamp).
2. `conftest.py` parses the `.lbl` file (VICE label format) for
   all symbols at absolute addresses.
3. Each test creates a fresh `C64Emu`, loads the PRG, looks up
   function addresses by name, and calls them via `emu.jsr()`.

`load_prg()` (`tests/emu_base.py`) handles the load/run address
split: after loading the PRG at its file address, it copies each
segment with `__<SEG>_LOAD__`/`__<SEG>_RUN__`/`__<SEG>_SIZE__`
symbols to its run address, as `loader.s` does on the C64
(`test_loader.py` holds the two to the same result).  Test code
always references runtime addresses.

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
tests use `SymbolTable` as their sole symbol resolution mechanism;
`load_prg()` reads the `.lbl` beside the map through it.

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
KERNAL (vectors at `$3FFFA`), copies it — replacing a stale copy — and
prints its version (`V920421` …, at offset `$16`); it exits non-zero,
listing the places searched, when there is none.  The xmega65 driver finds
the SD image (`mega65.img`) in the same directory.

M65Emu takes its ROM from a post-boot snapshot, not from this file.
`dev/capture_m65_state.py` records one snapshot per ROM it is given —
by default `rom/mega65.rom`, after the discovery — booting xmega65 on
it through the session's SD clone, and refuses to record when the ROM
xmega65 booted differs from the one given
([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)).

**The verified ROMs.**  The m65 build is verified on two MEGA65 ROMs,
in Tier I (M65Emu, from each ROM's snapshot) and Tier X (xmega65 on
each ROM): **920413**, the floor (MEGA65 release 0.97; the loader
refuses anything older), and **920421**, the current ROM — the one
the installed xmega65 ships, which `make m65-rom` copies.  A newer ROM
joins the list by its own commit: its snapshot captured, the m65
tiers green on it, this paragraph and `test_m65_roms.py`'s list
updated.

`rom/mega65_open.rom`, the MEGA65 build of the Open ROMs — the
project's only MEGA65 image — is committed next to it, pinned to an
upstream commit and SHA-256.  It holds no C65/MEGA65 KERNAL and no
BASIC 65: it starts in its legacy (C64) mode, and its own native mode
(`GO 65`) runs on the same C64-style KERNAL, without the C65 jump
table the m65 build uses, so it cannot run the m65 PRG as designed
([rom/README.md](../rom/README.md#mega65-roms)).

## Running tests

```sh
# All tests (builds both debug + release, checks for KERNAL ROM, runs pytest)
make test

# Direct, via pipenv.  The PRG fixtures run make themselves, the
# bundles rebuild themselves; pyproject.toml's testpaths select
# tests/unit + tests/integration.
pipenv run pytest -q

# Only Tier U (bundles; the oplen oracle and the build-gate tests
# also run make)
pipenv run pytest tests/unit -q

# Only Tier I (the PRG fixtures)
pipenv run pytest tests/integration -q

# Specific file
pipenv run pytest tests/unit/test_expr.py -q
```

See [testing.md](testing.md) for test methodology, conventions, and
the TDD Method.
