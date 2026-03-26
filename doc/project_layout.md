# CSE Project Layout

## Directory Structure

    cse/
    ├── Makefile                Build system (make all, test, tables, clean)
    ├── .gitignore
    │
    ├── src/                    Source code
    │   ├── main.c              Hardware init, shared utils, main loop (262 lines)
    │   ├── repl.c              REPL command loop, emitters, handlers (751 lines)
    │   ├── repl.h              REPL public API (exec_line, read_line, show_prompt)
    │   ├── editor.c            Source editor: gap buffer, rendering, keys (654 lines)
    │   ├── editor.h            Editor public API (enter/leave/handle_key)
    │   ├── cse.h               Shared declarations across all C modules
    │   ├── cse_io.h            cse_io public API + cursor/color macros
    │   ├── screen.h            Screen management public API
    │   ├── disk.h              Disk I/O public API
    │   ├── expr.h              Expression parser public API
    │   ├── symtab.h            Symbol table public API
    │   ├── asm_src.h           Source assembler public API
    │   │
    │   ├── screen.s            Screen management: clear, scroll, cursor (223 lines)
    │   ├── disk.s              CBM file I/O: load, save, directory (856 lines)
    │   ├── expr.s              Expression parser: hex, decimal, binary, operators (192 lines)
    │   ├── cse_io.s            Raw screen I/O: putc, puts, hex/dec output (310 lines)
    │   │
    │   ├── dasm.s              Disassembler, bit-slice decoder (1366 lines)
    │   ├── dasm_tables.s       Disassembler lookup tables
    │   ├── dasm_mne_idx.s      Disassembler mnemonic index tables
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
    │   ├── asm_src.c           Source assembler (stub, 18 lines)
    │   ├── symtab.c            Symbol table (stub, 21 lines)
    │   │
    │   ├── meminfo.s           Linker symbol shim for C (cse_start, cse_end)
    │   └── c64_cse.cfg         Custom cc65 linker config (expanded ZP)
    │
    ├── dev/                    Development tools and test infrastructure
    │   ├── instruction_set.py  Authoritative opcode database (OPCODES, MNEMONICS)
    │   ├── mnemonic_tables.py  Table generator → src/mn*_tables.s, mn_modes.s
    │   ├── hashes.py           Hash function definitions (h7, h6, HASH_T)
    │   ├── test.cfg            Linker config for py65 test binaries
    │   ├── asm_line_test_stub.s  Test stub for asm_line tests
    │   ├── au_mode_test_stub.s   Test stub for au_mode tests
    │   ├── dasm_test_stub.s      Test stub for dasm tests
    │   ├── expr_test_stub.s      Test stub for expr tests
    │   ├── cse_io_test_stub.s    Test stub for cse_io tests
    │   └── search/             Hash search scripts (historical, not run regularly)
    │
    ├── tests/                  pytest test suite (2076 tests)
    │   ├── conftest.py         Test fixtures, binary builder, py65 CPU emulator
    │   ├── test_asm_line.py    Assembler tests (all mnemonics × modes)
    │   ├── test_au_mode.py     Addressing mode parser tests
    │   ├── test_mnhash.py      Mnemonic hash/fingerprint sweep tests
    │   ├── test_dasm.py        Disassembler tests
    │   ├── test_expr.py        Expression parser tests
    │   ├── test_cse_io.py      Screen I/O tests
    │   └── test_editor.py      Editor tests
    │
    ├── doc/                    Design documentation
    │   ├── project_layout.md   This file
    │   ├── architecture.md     Module architecture and dependency map
    │   ├── repl_commands.md    Full REPL command reference + implementation status
    │   ├── memory_design.md    Memory maps (PRG/CRT), screen switching, ROM guidelines
    │   └── cse_io_api.md       cse_io API specification
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
    │ hex parse│◄──►│ cmd_*    │    │ keys     │
    │ main loop│    │ exec_line│    │ mode sw  │
    │          │    │ disasm   │    │          │
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

    screen.s ──► cse_io.s (scr_lo/scr_hi tables)
    disk.s   ──► cse_io.s
    expr.s   (standalone)
    dasm.s ──► dasm_tables.s, dasm_mne_idx.s
    meminfo.s ──► exports linker symbols to C

### Headers

| Header       | Provides                                              |
|--------------|-------------------------------------------------------|
| `cse.h`      | State defs, SCREEN, screen utils, hex parse, asm bridge, floppy, meminfo |
| `cse_io.h`   | io_putc/puts/hex/dec, io_getc/kbhit/sync, cursor/color macros |
| `screen.h`   | reset_screen(), scroll_up(), newline(), cursor_show/hide() |
| `disk.h`     | floppy_status(), list_directory(), disk_load/save_prg/seq() |
| `expr.h`     | expr_eval(), expr_error_str() |
| `repl.h`     | exec_line(), read_line(), show_prompt()                |
| `editor.h`   | enter_editor(), leave_editor(), ed_handle_key()       |
| `symtab.h`   | sym_define(), sym_lookup(), sym_clear(), sym_count()   |
| `asm_src.h`  | asm_assemble(), asm_org, asm_errors                    |

## Build System

    make              Build cse.prg (default)
    make tables       Regenerate mn*_tables.s from Python
    make test         Run pytest tests
    make test-bins    Assemble py65 test binaries only
    make run          Build + launch in VICE
    make clean        Remove build/

### Build pipeline

    src/*.c  ──cc65──►  build/src/*.s  ──ca65──►  build/src/*.o ─┐
    src/*.s  ──────────────────────────ca65──►  build/src/*.o ──┤
                                                                 ├──ld65──► cse.prg
    c64.lib ─────────────────────────────────────────────────────┘

C sources: main.c, repl.c, editor.c, asm_src.c, symtab.c (compiled via pattern rule).
ASM sources: 23 .s files (assembled via pattern rule).
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

    tests/conftest.py       Builds test binaries, loads into py65 CPU
    tests/test_asm_line.py  Assembler tests (all mnemonics × every valid mode)
    tests/test_au_mode.py   Addressing mode parser tests
    tests/test_mnhash.py    Hash collision and fingerprint sweep tests
    tests/test_dasm.py      Disassembler tests
    tests/test_expr.py      Expression parser tests
    tests/test_cse_io.py    Screen I/O tests
    tests/test_editor.py    Editor tests

Run: `/path/to/virtualenv/bin/pytest tests/ -q`
Virtualenv: `/Users/cr/.local/share/virtualenvs/cse-rXGMsE9U`

### py65 Test Harness Rules

**The 6502 has a flat address space with no memory protection.** Writing test
data to the wrong address silently overwrites code. The CPU executes your
data as instructions. Symptoms are bizarre (e.g., "carry flag wrong after
SEC" because SEC was overwritten with EOR).

**RULE 1: Never hardcode test data addresses.** Read the map file to find
where CODE, RODATA, and BSS end. Place test data ABOVE that boundary.
Use `$0A00` or higher as a safe default — verify against the map.

**RULE 2: Use `mpu.memory` directly.** py65's `MPU()` has its own internal
memory. Creating a separate `bytearray` and loading code into it does
nothing unless you assign `mpu.memory = mem`. Always either use
`mpu.memory` directly or assign after loading.

**RULE 3: Check the map file when adding new test modules.** The linker
places segments contiguously. A new .s file added to the test binary
shifts all subsequent addresses. A data address that was safe yesterday
may collide with code today.

**RULE 4: The `_call` helper must reset SP.** Each test call should start
with a clean stack (SP=$FF, return sentinel at $01FE/$01FF). The 6502
stack at $0100-$01FF is shared between the test harness and the code
under test. Unbalanced JSR/RTS corrupts the return address.

**RULE 5: ca65 character literals ARE PETSCII with `-t c64`.** The
assembler maps `'s'` to $53 (PETSCII), not $73 (ASCII). This is correct
for C64 code. Do not "fix" character comparisons by using hex unless
there is a genuine encoding mismatch.
