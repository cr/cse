# CSE Project Layout

## Directory Structure

```
cse/
├── Makefile                Build system (make help for targets)
├── src/                    Source code
│   ├── main.c              Init, main loop, splash screen
│   ├── repl.c              REPL command loop and handlers
│   ├── editor.c            Gap buffer editor, rendering, keys
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
│   ├── *.h                 C headers (cse.h, repl.h, editor.h, etc.)
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
│   └── test_asm_src.py     Source assembler tests
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

## Build Pipeline

```
src/*.c  ──cc65──►  build/src/*.s  ──ca65──►  build/src/*.o ─┐
src/*.s  ──────────────────────────ca65──►  build/src/*.o ──┤
                                                             ├──ld65──► cse.prg
c64.lib ─────────────────────────────────────────────────────┘
```

C sources: `main.c`, `repl.c`, `editor.c` (compiled via cc65 → ca65).
ASM sources: all `.s` files (assembled directly by ca65).
Linker config: `src/c64_cse.cfg` (ZP expanded to $02–$7F).

Build-time options: `CPU=6502|6510|65c02`, `THEME=NAME|hex`,
`DEBUG=1`.  See `make help` and `make themes`.

## Architecture and module details

See [architecture.md](architecture.md) for the module map and
dependency graph.  Per-module specs live in `doc/modules/`.

## Test infrastructure

See [testing.md § The TDD Method](testing.md#the-tdd-method) for test
principles, py65 harness architecture, and conventions.
