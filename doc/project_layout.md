# Project Layout — Directory structure

**Template:** [subsystem](templates/subsystem.md)

## Directory Structure

```
cse/
├── Makefile                Build system (make help for targets)
├── src/                    Source code
│   ├── main.s              Init, main loop, mode dispatch
│   ├── repl.s              REPL command loop and handlers
│   ├── editor.s            Gap buffer editor, rendering, keys
│   ├── asm_src.s            Two-pass source assembler
│   ├── asm_line.s          Single-line assembler, zone dispatch
│   ├── asm_vars.s          Assembler ZP variables
│   ├── opcode_lookup.s     (profile, mode) → opcode byte
│   ├── au_mode.s           Addressing mode parser
│   ├── mn_classify.s       Mnemonic classifier dispatcher
│   ├── mn7.s / mn6.s       Hash-based mnemonic lookup
│   ├── mn_vars.s           Mnemonic classifier ZP variables
│   ├── expr.s              Expression parser (recursive descent)
│   ├── symtab.s            Symbol table (hash + linear probe)
│   ├── dasm.s              Disassembler (bit-slice decoder)
│   ├── screen.s            Screen management, scroll, cursor
│   ├── cse_io.s            Raw screen I/O (putc, puts, hex/dec)
│   ├── disk.s              CBM file I/O (load, save, directory)
│   ├── debugger.s          Breakpoint handler, step, register display
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
├── tests/                  pytest test suite
│   ├── c64emu.py           C64 emulator class (py65 + KERNAL ROM)
│   ├── conftest.py         Fixtures, build helpers
│   ├── test_asm_line.py    Assembler tests
│   ├── test_au_mode.py     Addressing mode parser tests
│   ├── test_mnhash.py      Mnemonic hash tests
│   ├── test_expr.py        Expression parser tests
│   ├── test_symtab.py      Symbol table tests
│   ├── test_asm_src.py     Source assembler tests
│   ├── test_repl.py        REPL command tests
│   ├── test_debugger.py    Breakpoint/debugger tests
│   ├── test_dasm.py        Disassembler tests
│   ├── test_cse_io.py      Screen I/O tests
│   └── test_editor.py      Editor gap-buffer tests
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
