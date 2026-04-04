# Module Architecture — Module map, dependency graph, boundary rules

**Template:** [subsystem](templates/subsystem.md)

## Layer Diagram

```
┌──────────────────────────────────────────┐
│                main.c                    │  init, mode switch, main loop
├────────────────┬─────────────────────────┤
│    repl.s      │       editor.c          │  user-facing modes
├────────────────┴──┬───────────┬──────────┤
│    asm_src.s      │  expr.s   │ symtab.s │  source assembler pipeline
├───────────────────┴───────────┴──────────┤
│  asm_line.s  │   dasm.s   │   disk.s     │  core engines
├──────────────┴────────────┴──────────────┤
│          screen.s     │    cse_io.s      │  output layers
└───────────────────────┴──────────────────┘
```

Higher layers depend on lower layers.  No upward or circular
dependencies.  Each layer can be understood without reading the
layers above it.

## Modules

| Module | Purpose | Doc |
|--------|---------|-----|
| main.c | Hardware init, main loop, mode switch | [main.md](modules/main.md) |
| repl.s | REPL command dispatch and emitters | [repl.md](modules/repl.md) |
| editor.c | Gap-buffer source editor, sequential reader | [editor.md](modules/editor.md) |
| asm_src.s | Two-pass source assembler | [asm_src.md](modules/asm_src.md) |
| asm_line.s | Single-line instruction assembler (VICII input) | [asm_line.md](modules/asm_line.md) |
| asm_bridge.s | C ↔ assembly bridge, PETSCII→VICII, error recovery | [asm_line.md](modules/asm_line.md) |
| expr.s | Recursive-descent expression parser | [expr.md](modules/expr.md) |
| symtab.s | Hash-table symbol storage with name heap | [symtab.md](modules/symtab.md) |
| dasm.s | Bit-slice disassembler (6502/6510/65C02) | [dasm.md](modules/dasm.md) |
| debugger.s | BRK-based breakpoints, single-step, context switch | [debugger.md](modules/debugger.md) |
| disk.s | CBM file I/O via KERNAL (PRG and SEQ, callback-based) | [disk.md](modules/disk.md) |
| screen.s | Scroll, newline, cursor, color theme | [screen.md](modules/screen.md) |
| cse_io.s | Raw screen I/O, keyboard, PETSCII→screencode | [cse_io.md](modules/cse_io.md) |

Support modules (internal to the assembler pipeline):

| Module | Purpose | Doc |
|--------|---------|-----|
| mn7.s / mn6.s | Perfect hash mnemonic classifier (mn7: 114, mn6: 56) | [mn_classify.md](modules/mn_classify.md) |
| opcode_lookup.s | (profile, mode) → opcode byte | [opcode_lookup.md](modules/opcode_lookup.md) |
| au_mode.s | Addressing mode operand parser | [au_mode.md](modules/au_mode.md) |
| meminfo.s | Linker symbol shim: `_cse_start` / `_cse_end` / `_cse_zp_end` | [meminfo.md](modules/meminfo.md) |
| mn_classify.s | Build-time dispatcher: selects mn6 or mn7 | [mn_classify.md](modules/mn_classify.md) |
| asm_vars.s | Shared ZP variable definitions | — |
| mn_vars.s | Mnemonic classifier ZP variables | — |
| parse_hex.s | Hex literal parser for au_mode | — |

Generated files (do not edit — regenerate with `make tables`):

| File | Generator |
|------|-----------|
| mn7_tables.s, mn_asm_tables.s, mn_modes.s, mn_config.s | mnemonic_tables.py |
| dasm_tables.s | dasm_tables.py |

## Dependency Graph

```
main.c
├── repl.s
│   ├── asm_bridge.s ── asm_line.s ── opcode_lookup.s
│   │                       ├── au_mode.s ── parse_hex.s
│   │                       └── mn_classify.s ── mn7.s ── mn7_tables.s
│   ├── asm_src.s ── asm_bridge.s, expr.s, symtab.s, editor.c
│   ├── dasm.s ── dasm_tables.s
│   ├── debugger.s
│   ├── expr.s ── symtab.s
│   ├── disk.s ── screen.s ── cse_io.s
│   └── screen.s
└── editor.c
    ├── disk.s
    └── screen.s
```

## Dependency Rules

1. **No circular dependencies.**  The graph is a DAG.
2. **Leaf modules have no dependencies:** cse_io, symtab, dasm, debugger.
3. **Screen output flows one way:** module → screen → cse_io.
4. **disk.s uses callbacks** for SEQ I/O to avoid depending on editor.
5. **Expression parser depends only on symtab** — no I/O.
6. **All .s modules are self-contained** with explicit `.import`/`.export`.

## C / Assembly Boundary

| Language | Modules |
|----------|---------|
| C | main.c, editor.c |
| Assembly | everything else |

Assembly modules define their own calling convention via ZP variables
and register returns — never the cc65 C ABI.  `asm_bridge.s` is the
sole translation point between the two conventions.

The boundary is shifting toward full assembly.  When a C module is
replaced, its interface to lower layers is unchanged.
