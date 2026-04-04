# Project Layout — Directory structure

**Template:** [subsystem](templates/subsystem.md)

## Directory Structure

```
cse/
├── Makefile                Build system (make help for targets)
├── src/                    Source code
│   ├── main.c              Init, main loop, mode dispatch
│   ├── repl.s              REPL command loop and handlers (assembly)
│   ├── editor.s            Gap buffer editor, rendering, keys (assembly)
│   ├── asm_src.s            Two-pass source assembler
│   ├── asm_bridge.s        C↔asm bridge for _asm_line
│   ├── asm_line.s          Single-line assembler, zone dispatch
│   ├── asm_vars.s          Assembler ZP variables
│   ├── opcode_lookup.s     (profile, mode) → opcode byte
│   ├── au_mode.s           Addressing mode parser
│   ├── parse_hex.s         Hex operand parser
│   ├── mn_classify.s       Mnemonic classifier dispatcher
│   ├── mn7.s / mn6.s       Hash-based mnemonic lookup
│   ├── mn_vars.s           Mnemonic classifier ZP variables
│   ├── expr.s              Expression parser (recursive descent)
│   ├── symtab.s            Symbol table (hash + linear probe)
│   ├── dasm.s              Disassembler (bit-slice decoder)
│   ├── screen.s            Screen management, scroll, cursor
│   ├── cse_io.s            Raw screen I/O (putc, puts, hex/dec)
│   ├── disk.s              CBM file I/O (load, save, directory)
│   ├── meminfo.s           Linker symbol shim (cse_start/end/zp_end)
│   ├── mn*_tables.s        ┐
│   ├── mn_modes.s          │ GENERATED — do not edit
│   ├── mn_config.s         │ (regenerate: make tables)
│   ├── mn_asm_tables.s     │
│   └── dasm_tables.s       ┘
│   ├── cse.h               Shared C definitions (main.c only)
│   └── c64_cse.cfg         Custom ld65 linker config (expanded ZP)
│
├── dev/                    Development tools
│   ├── instruction_set.py  Authoritative opcode database
│   ├── mnemonic_tables.py  Table generator → src/mn*_tables.s
│   ├── hashes.py           Hash function definitions
│   ├── dasm_tables.py      Disassembler table generator
│   ├── *_test_stub.s       Test entry point stubs
│   ├── *_test.cfg          Test linker configs
│   └── search/             Hash search scripts (historical)
│
├── tests/                  pytest test suite
│   ├── conftest.py         Fixtures, build helpers, py65 emulator
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
├── doc/                    Documentation (see doc/README.md)
│   ├── README.md           DDD methodology, document index
│   ├── modules/            Per-module technical specs
│   └── *.md                System-level docs
│
└── build/                  Build output (git-ignored)
    ├── cse.prg             Main C64 binary
    ├── cse.dbg / cse.map   Debug symbols / linker map
    └── src/                Intermediate .s and .o files
```

## Further reading

- [build_system.md](build_system.md) — toolchain, build pipeline, build-time options, test binaries
- [architecture.md](architecture.md) — module map and dependency graph
- [testing.md](testing.md) — TDD Method, test conventions
