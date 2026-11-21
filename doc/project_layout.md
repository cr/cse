# Project Layout — Directory structure

**Template:** [subsystem](templates/subsystem.md)

## Directory Structure

Every directory and file group of the repository.  Each file's owning
document is in that document's *Owned files* table
([README.md § Ownership](README.md#ownership)); this page is the map.

```
cse/
├── Makefile                Build system (make help for targets)
├── README.md               User manual
├── background.md           Project background
├── LICENSE
├── Pipfile, Pipfile.lock   Python environment (pipenv: py65, pytest)
├── pyproject.toml          pytest configuration (testpaths)
├── .gitignore
│
├── src/                    Source code (6502 assembly, ca65)
│   ├── main.s              BASIC SYS stub, cold init, main loop, interrupt hooks
│   ├── loader.s            Discardable bootstrap (PRG → runtime relocation)
│   ├── repl.s              REPL command loop and handlers
│   ├── editor.s            Keystroke dispatch, screen rendering, disk I/O (L4)
│   ├── gap_buffer.s        Gap-buffer primitives + sequential reader (L3)
│   ├── debugger.s          Step state machine, return_to_userland, brk_stub (L4)
│   ├── breakpoints.s       BP-table CRUD + patch/unpatch (L3)
│   ├── asm_src.s           Two-pass source assembler
│   ├── asm_line.s          Single-line assembler
│   ├── asm_err.s           Assembler error state + unwind
│   ├── addr_mode.s         Addressing mode + operand parser
│   ├── opcode_lookup.s     (profile, mode) → opcode byte
│   ├── mn_classify.s       Mnemonic classifier dispatcher
│   ├── mn7.s / mn6.s       Hash-based mnemonic lookup
│   ├── expr.s              Expression parser (recursive descent)
│   ├── symtab.s            Symbol table (hash + linear probe)
│   ├── dasm.s              Disassembler (opcode-map decoder)
│   ├── log.s               Logging API (error, warning, info and range lines)
│   ├── screen.s            Screen management, scroll, cursor, themes
│   ├── cse_io.s            Raw screen I/O (putc, puts, hex/dec)
│   ├── disk.s              CBM file I/O (load, save, directory)
│   ├── mem.s               Memory manager (banking, ZP save/restore, segment queries)
│   ├── strings.s           Shared strings (RODATA)
│   ├── zp.s                Central zero-page layout (all modules)
│   ├── platform.inc        The platform layer: c64 / m65 constants and macros (KCALL…)
│   ├── m45_ops.inc         45GS02 opcodes as .byte macros (MAP, TAB, …)
│   ├── *.inc               Shared includes: macros.inc, log.inc, dbg_reason.inc, bp.inc
│   ├── mn6_tables.s        ┐
│   ├── mn7_tables.s        │
│   ├── mn_modes.s          │ GENERATED — do not edit
│   ├── mn_asm_tables.s     │ (regenerate: make tables)
│   ├── oplen_tbl.s         │
│   ├── cpu_set.inc         │
│   ├── dasm_tables.s       │
│   ├── dasm_mne_idx.s      ┘
│   ├── c64_trial.cfg       ld65 trial linker config (size measurement)
│   ├── c64_cse.cfg.in      ld65 production linker config template
│   └── m65_cse.cfg         ld65 linker config of the m65 build (fixed layout)
│
├── dev/                    Development tools (owner: build_system.md)
│   ├── instruction_set.py  Authoritative opcode database (shared with bbbc64)
│   ├── hashes.py           Hash function definitions (shared with bbbc64)
│   ├── mnemonic_tables.py  Generator → src/mn*_tables.s, mn_modes.s, mn_asm_tables.s, oplen_tbl.s, cpu_set.inc
│   ├── dasm_tables.py      Generator → src/dasm_tables.s, dasm_mne_idx.s
│   ├── compute_layout.py   Two-pass link: trial map → production config
│   ├── size_report.py      make size
│   ├── od65_syms.py        Symbol extraction from .o files
│   ├── find_m65_rom.py     make m65-rom
│   ├── scs_*.py, strings.txt   Screen-code sequence analysis and packing
│   ├── gen_asm_tests.py    Assembler-test fixture generator
│   ├── capture_*.py        Golden-file and M65Emu-state recorders
│   ├── audit_*.py          Doc audits (CDD Maintenance)
│   ├── probe_*.py          Investigation probes against the real KERNAL (run by hand)
│   ├── *_test_stub.s       Test-bundle stubs (linker scaffolding, recorded mocks)
│   ├── test.cfg, *_test.cfg    Test-bundle linker configs
│   ├── src.d64, test.d64   Disk images (sample programs; integration tests)
│   └── search/             Hash-search scripts and their output (historical)
│
├── tests/                  pytest test suite (see doc/testing.md)
│   ├── conftest.py         Bundle, bundle and PRG fixtures, SymbolTable
│   ├── emu_base.py         EmuBase: what C64Emu and M65Emu share
│   ├── c64emu.py           C64Emu (py65 + the C64 KERNAL ROM)
│   ├── iec_drive.py        the virtual IEC drive (Drive1541, IECBus), both harnesses
│   ├── m65emu/             M65Emu: MPU45GS02, M65Memory, devices, harness
│   ├── xmega65.py          xmega65 driver (recorders; Tier X)
│   ├── asm_dasm_runner.py  Exhaustive asm_line / dasm_insn sweeps
│   ├── fixtures/           Golden files (golden/*.json), MEGA65 compendium tables (CSV)
│   ├── unit/test_*.py      Tier U — module bundles (bare py65 MPU), MPU45GS02 and
│   │                       M65Memory, generator, audit and build-gate tests
│   ├── integration/test_*.py   Tier I — C64Emu / M65Emu + full PRG
│   └── emulator/test_*.py      Tier X — xmega65 (run by path)
│
├── rom/                    ROM images (rom/README.md: source, licence)
│   ├── README.md
│   ├── *_cbm.bin           Stock Commodore ROMs (git-ignored; make check-roms)
│   ├── *_mega.bin          MEGA65 Open-ROMs, C64-compatible build (committed)
│   ├── mega65.rom          MEGA65 ROM from xmega65 (git-ignored; make m65-rom)
│   └── mega65_open.rom     MEGA65 Open-ROMs, MEGA65 build (committed)
│
├── img/                    Screenshots for README.md (*.png, theme-*.png)
│
├── doc/                    Documentation (see doc/README.md)
│   ├── README.md           CDD methodology, document index
│   ├── TODO.md             Open work, findings, plans
│   ├── cdd_log.md          CDD cycle log
│   ├── *.md                System-level docs
│   ├── modules/            Per-module technical specs
│   └── templates/          Document templates
│
└── build/                  Build output (git-ignored;
                            build_system.md § Directory layout)
    ├── release/{6510,6502,m65}/    Optimized PRGs, exomizer SFX, map, lbl, objects
    ├── debug/{6510,6502,m65}/      -g PRGs with full .lbl
    ├── cse.d64             Distribution D64 (all CPU variants, compressed)
    ├── cse-m65.d81         Distribution D81 of the m65 build (the raw PRG)
    └── *_test.*, *.o       Test bundles and their objects
```

## Further reading

- [build_system.md](build_system.md) — toolchain, build pipeline, build-time options, test binaries
- [architecture.md](architecture.md) — module map and dependency graph
- [testing.md](testing.md) — TDD Method, test conventions
