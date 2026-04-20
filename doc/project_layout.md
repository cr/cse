# Project Layout — Directory structure

**Template:** [subsystem](templates/subsystem.md)

## Directory Structure

```
cse/
├── Makefile                Build system (make help for targets)
├── src/                    Source code
│   ├── main.s              Init, main loop, mode dispatch
│   ├── repl.s              REPL command loop and handlers
│   ├── asm_src.s            Two-pass source assembler
│   ├── asm_line.s          Single-line assembler, zone dispatch
│   ├── zp.s                Central zero-page layout (all modules)
│   ├── opcode_lookup.s     (profile, mode) → opcode byte
│   ├── addr_mode.s         Addressing mode + operand parser
│   ├── mn_classify.s       Mnemonic classifier dispatcher
│   ├── mn7.s / mn6.s       Hash-based mnemonic lookup
│   ├── mn_vars.s           Mnemonic classifier ZP variables
│   ├── expr.s              Expression parser (recursive descent)
│   ├── symtab.s            Symbol table (hash + linear probe)
│   ├── dasm.s              Disassembler (bit-slice decoder)
│   ├── screen.s            Screen management, scroll, cursor
│   ├── cse_io.s            Raw screen I/O (putc, puts, hex/dec)
│   ├── disk.s              CBM file I/O (load, save, directory)
│   ├── breakpoints.s       BP-table CRUD + patch/unpatch (L3, bundle-testable)
│   ├── debugger.s          Step state machine, return_to_userland, brk_stub (L4)
│   ├── gap_buffer.s        Gap-buffer primitives + sequential reader (L3, bundle-testable)
│   ├── editor.s            Keystroke dispatch, screen rendering, disk I/O (L4)
│   ├── loader.s            Discardable bootstrap (PRG → runtime relocation)
│   ├── mem.s               Memory manager (banking, segment queries, workspace)
│   ├── mn*_tables.s        ┐
│   ├── mn_modes.s          │
│   ├── mn_config.s         │ GENERATED — do not edit
│   ├── mn_asm_tables.s     │ (regenerate: make tables)
│   ├── dasm_tables.s       │
│   └── oplen_tbl.s         ┘
│   ├── c64_trial.cfg       ld65 trial linker config (size measurement)
│   └── c64_cse.cfg.in      ld65 production linker config template
│
├── dev/                    Development tools
│   ├── instruction_set.py  Authoritative opcode database
│   ├── mnemonic_tables.py  Table generator → src/mn*_tables.s
│   ├── hashes.py           Hash function definitions
│   ├── dasm_tables.py      Disassembler table generator
│   ├── compute_layout.py   Two-pass link: trial map → production config
│   ├── *_test_stub.s       Test entry point stubs
│   ├── *_test.cfg          Test linker configs
│   └── search/             Hash search scripts (historical)
│
├── tests/                  pytest test suite (see doc/testing.md)
│   ├── c64emu.py           C64 emulator class (py65 + KERNAL ROM)
│   ├── conftest.py         Bundle fixtures + cse_prg fixture
│   ├── unit/               Tier U — module bundles (bare py65 MPU)
│   │   ├── test_addr_mode.py       addr_mode.s (asm_core)
│   │   ├── test_asm_err.py         asm_err.s (asm_core)
│   │   ├── test_asm_line.py        asm_line.s (asm_core)
│   │   ├── test_asm_src.py         asm_src.s + asm_core
│   │   ├── test_cse_io.py          cse_io.s leaf
│   │   ├── test_dasm.py            dasm.s bundle
│   │   ├── test_breakpoints.py     breakpoints.s BP-table CRUD (L3)
│   │   ├── test_expr.py            expr.s (asm_core)
│   │   ├── test_log.py             log.s bundle (log + screen + cse_io)
│   │   ├── test_mem.py             mem.s — banking + ZP save/restore
│   │   ├── test_mn_classify.py     mn_classify + mn6 + mn7 + mn_vars
│   │   ├── test_opcode_lookup.py   opcode_lookup.s (asm_core)
│   │   └── test_symtab.py          symtab.s leaf
│   ├── integration/        Tier I — C64Emu + full PRG
│   │   ├── test_c64emu.py        Emulator harness smoke
│   │   ├── test_editor.py        Editor via C64Emu
│   │   ├── test_kernel_transition.py  Phase-18 kernel↔user
│   │   ├── test_repl.py          REPL command E2E
│   │   ├── test_screen.py        screen.s via C64Emu (hardware-adjacent)
│   │   └── test_step_rom.py      Debugger ROM-step fallback
│   └── retired/            Anti-pattern tests, kept for reference
│       └── test_editor.py  Python-mirror (superseded by integration)
│
├── rom/                    KERNAL/BASIC/CHARGEN ROM images
│   ├── *_cbm.bin           Stock Commodore ROMs (git-ignored)
│   └── *_mega.bin          MEGA65 Open-ROMs (committed)
│
├── doc/                    Documentation (see doc/README.md)
│   ├── README.md           DDD methodology, document index
│   ├── modules/            Per-module technical specs
│   └── *.md                System-level docs
│
└── build/                  Build output (git-ignored)
    ├── cse.d64             Distribution D64 (all CPU variants, compressed)
    ├── 6510/               6510 build
    │   ├── cse.prg         Raw PRG (for make run / debugging)
    │   ├── cse-exo.prg     Exomizer SFX compressed PRG
    │   ├── cse.dbg/.map    Debug symbols / linker map
    │   └── src/            Intermediate .o files
    ├── 6502/               6502 build (same structure)
    └── cmos/               65C02 build (same structure)
```

## Further reading

- [build_system.md](build_system.md) — toolchain, build pipeline, build-time options, test binaries
- [architecture.md](architecture.md) — module map and dependency graph
- [testing.md](testing.md) — TDD Method, test conventions
