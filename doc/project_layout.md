# CSE Project Layout

## Directory Structure

    cse/
    ├── Makefile                Build system (make all, test, tables, clean)
    ├── .gitignore
    │
    ├── src/                    Source code
    │   ├── main.c              Hardware init, shared utils, main loop (360 lines)
    │   ├── repl.c              REPL command loop, emitters, handlers (517 lines)
    │   ├── repl.h              REPL public API (exec_line, read_line, show_prompt)
    │   ├── editor.c            Source editor: gap buffer, rendering, keys (357 lines)
    │   ├── editor.h            Editor public API (enter/leave/handle_key)
    │   ├── cse.h               Shared declarations across all C modules
    │   │
    │   ├── asm_bridge.s        C↔asm bridge: _asm_line wrapper, _jsr_addr, ZP save
    │   ├── asm_line.s          Single-line assembler, zone dispatch A–H
    │   ├── asm_vars.s          Assembler ZP variables
    │   ├── opcode_lookup.s     (profile, mode) → opcode byte
    │   ├── au_mode.s           Addressing mode parser
    │   ├── parse_hex.s         Hex operand parsing for assembler
    │   │
    │   ├── mn_classify.s       Mnemonic classifier dispatcher (mn6 + mn7)
    │   ├── mn7.s               7-bit hash mnemonic lookup (114 mnemonics)
    │   ├── mn6.s               6-bit hash mnemonic lookup (56 legal only)
    │   ├── mn_vars.s           Mnemonic classifier ZP variables
    │   │
    │   ├── mn7_tables.s        ┐
    │   ├── mn6_tables.s        │ GENERATED — do not edit
    │   ├── mn_asm_tables.s     │ (regenerate with: make tables)
    │   ├── mn_modes.s          │
    │   ├── mn_config.s         ┘
    │   │
    │   ├── meminfo.s           Linker symbol shim for C (cse_start, cse_end)
    │   ├── c64_cse.cfg         Custom cc65 linker config (expanded ZP)
    │   │
    │   ├── asm.c               (legacy — not linked)
    │   ├── asm.s               (legacy — not linked)
    │   ├── asm_utils.c         (legacy — not linked)
    │   ├── asm_utils.s         (legacy — not linked)
    │   ├── mnemonic.s          (legacy — not linked)
    │   ├── oplen.c             (legacy — not linked)
    │   ├── oplen.h             (legacy — not linked)
    │   └── oplen.s             (legacy — not linked)
    │
    ├── dev/                    Development tools and test infrastructure
    │   ├── instruction_set.py  Authoritative opcode database (OPCODES, MNEMONICS)
    │   ├── mnemonic_tables.py  Table generator → src/mn*_tables.s, mn_modes.s
    │   ├── hashes.py           Hash function definitions (h7, h6, HASH_T)
    │   ├── test.cfg            Linker config for py65 test binaries
    │   ├── asm_line_test_stub.s  Test stub for asm_line tests
    │   ├── au_mode_test_stub.s   Test stub for au_mode tests
    │   └── search/             Hash search scripts (historical, not run regularly)
    │
    ├── tests/                  pytest test suite (1222 tests)
    │   ├── conftest.py         Test fixtures, binary builder, py65 CPU emulator
    │   ├── test_asm_line.py    Assembler tests (all mnemonics × modes)
    │   ├── test_au_mode.py     Addressing mode parser tests
    │   └── test_mnhash.py      Mnemonic hash/fingerprint sweep tests
    │
    ├── doc/                    Design documentation
    │   ├── project_layout.md   This file
    │   ├── repl_commands.md    Full REPL command reference + implementation status
    │   └── memory_design.md    Memory maps (PRG/CRT), screen switching, ROM guidelines
    │
    └── build/                  Build output (git-ignored)
        ├── cse.prg             Main C64 binary
        ├── cse.dbg             Debug symbols
        └── src/                Intermediate .s and .o files

## Source Code Architecture

### C modules (compiled with cc65)

    ┌──────────┐    ┌──────────┐    ┌──────────┐
    │  main.c  │    │  repl.c  │    │ editor.c │
    │          │    │          │    │          │
    │ globals  │    │ line I/O │    │ gap buf  │
    │ hw init  │    │ emitters │    │ render   │
    │ screen   │◄──►│ cmd_*    │    │ keys     │
    │ hex parse│    │ exec_line│    │ mode sw  │
    │ floppy   │    │ disasm   │    │          │
    │ main loop│    │          │    │          │
    │ oplen tbl│    │          │    │          │
    └────┬─────┘    └────┬─────┘    └────┬─────┘
         │               │               │
         └───────┬───────┘               │
                 ▼                       │
            ┌─────────┐                  │
            │  cse.h  │◄─────────────────┘
            │ shared  │
            │ decls   │
            └─────────┘

### Assembly modules (assembled with ca65)

    asm_bridge.s ──► asm_line.s ──► opcode_lookup.s
        │                │               │
        │                ▼               ▼
        │           mn_classify.s   mn_asm_tables.s
        │            │       │      mn_modes.s
        │            ▼       ▼
        │          mn7.s   mn6.s
        │            │       │
        │            ▼       ▼
        │       mn7_tables  mn6_tables
        │            │       │
        │            ▼       ▼
        │          mn_config.s
        │
        ├──► au_mode.s ──► parse_hex.s
        │
        └──► asm_vars.s, mn_vars.s  (ZP variables)

    meminfo.s ──► exports linker symbols to C

### Headers

| Header     | Provides                                              |
|------------|-------------------------------------------------------|
| `cse.h`    | State defs, SCREEN, screen utils, hex parse, asm bridge, oplen table, floppy, meminfo |
| `repl.h`   | exec_line(), read_line(), show_prompt()                |
| `editor.h` | enter_editor(), leave_editor(), ed_handle_key()       |

## Build System

    make              Build cse.prg (default)
    make tables       Regenerate mn*_tables.s from Python
    make test         Run 1222 pytest tests
    make test-bins    Assemble py65 test binaries only
    make run          Build + launch in VICE
    make clean        Remove build/

### Build pipeline

    src/*.c  ──cc65──►  build/src/*.s  ──ca65──►  build/src/*.o ─┐
    src/*.s  ──────────────────────────ca65──►  build/src/*.o ──┤
                                                                 ├──ld65──► cse.prg
    c64.lib ─────────────────────────────────────────────────────┘

C sources: main.c, repl.c, editor.c (compiled via pattern rule).
ASM sources: 15 .s files (assembled via pattern rule).
Linker config: src/c64_cse.cfg (expanded ZP: $02–$7F).

### Generated files (do not edit by hand)

    src/mn7_tables.s      3×128 bytes: fingerprint, base_op, profile
    src/mn6_tables.s      3×64 bytes: fingerprint, base_op, profile
    src/mn_asm_tables.s   64+16 bytes: mode_offset + direct_opcodes
    src/mn_modes.s        2×30 bytes: mode bitmask lo/hi
    src/mn_config.s       Configuration constants

Regenerate: `make tables` (runs dev/mnemonic_tables.py).

## Test Infrastructure

Tests use py65 (6502 CPU emulator in Python) to execute the assembled
code in a simulated C64 environment.

    tests/conftest.py     Builds test binaries, loads into py65 CPU
    tests/test_asm_line.py  1100+ tests: every mnemonic × every valid mode
    tests/test_au_mode.py   ~100 tests: addressing mode parsing
    tests/test_mnhash.py    ~20 tests: hash collision and fingerprint sweeps

Run: `/path/to/virtualenv/bin/pytest tests/ -q`
Virtualenv: `/Users/cr/.local/share/virtualenvs/cse-rXGMsE9U`

## Legacy Files

The following files in src/ are from earlier development iterations
and are NOT linked into cse.prg:

    asm.c, asm.s          Earlier C-based assembler attempt
    asm_utils.c, asm_utils.s  Opcode validation utilities
    mnemonic.s            Earlier mnemonic lookup approach
    oplen.c, oplen.h, oplen.s  Opcode length as separate module

These can be removed once confirmed unused by any active code path.
