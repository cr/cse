# Module Architecture — Module map, dependency graph, boundary rules

**Template:** [subsystem](templates/subsystem.md)

## Layer Diagram

```
┌──────────────────────────────────────────┐
│                main.s                    │  init, mode switch, main loop
├────────────────┬─────────────────────────┤
│    repl.s      │       editor.s          │  user-facing modes
├────────────────┴──┬───────────┬──────────┤
│    asm_src.s      │  expr.s   │ symtab.s │  source assembler pipeline
├───────────────────┴───────────┴──────────┤
│  asm_line.s  │   dasm.s   │   disk.s     │  core engines
├──────────────┴────────────┴──────────────┤
│  debugger.s  │  screen.s  │   cse_io.s   │  low-level services
└──────────────┴────────────┴──────────────┘
       │
       │  context switch (j/g/t/o/c commands)
       ▼
┌──────────────────────────────────────────┐
│             user code                    │  runs in workspace memory
│  own registers, shared 6502 stack        │  BRK/NMI returns to CSE
└──────────────────────────────────────────┘
```

Higher layers depend on lower layers.  No upward or circular
dependencies.  Each layer can be understood without reading the
layers above it.

**User code** is not a CSE module — it is assembled output living
in workspace memory (`workstart`–`workend`).  The debugger's
context switch (`dbg_enter`) saves CSE's ZP state, patches
breakpoints, loads user registers, and jumps to the target address.
User code runs with full CPU access until a BRK instruction or NMI
returns control to CSE via the BRK/NMI handler.  The handler
restores CSE's ZP, unpatches breakpoints, and resumes the REPL.
User code shares the 6502 hardware stack with CSE but has its own
register state (`reg_a`, `reg_x`, `reg_y`, `reg_sp`, `reg_p`).

## Modules

| Module | Purpose | Doc |
|--------|---------|-----|
| main.s | Hardware init, BSS/stack setup, main loop, mode switch | [main.md](modules/main.md) |
| repl.s | REPL command dispatch and emitters | [repl.md](modules/repl.md) |
| editor.s | Gap-buffer source editor, sequential reader, workend update | [editor.md](modules/editor.md) |
| asm_src.s | Two-pass source assembler | [asm_src.md](modules/asm_src.md) |
| asm_line.s | Single-line instruction assembler (VICII input) | [asm_line.md](modules/asm_line.md) |
| asm_bridge.s | Calling convention bridge, PETSCII→VICII, error recovery | [asm_line.md](modules/asm_line.md) |
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
main.s
├── repl.s
│   ├── asm_bridge.s ── asm_line.s ── opcode_lookup.s
│   │                       ├── au_mode.s ── parse_hex.s
│   │                       └── mn_classify.s ── mn7.s ── mn7_tables.s
│   ├── asm_src.s ── asm_bridge.s, expr.s, symtab.s, editor.s
│   ├── dasm.s ── dasm_tables.s
│   ├── debugger.s
│   ├── expr.s ── symtab.s
│   ├── disk.s ── screen.s ── cse_io.s
│   └── screen.s
└── editor.s
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

## Calling Conventions

All modules are pure 6502 assembly.  No C compiler is used.

- **Internal calls** use ZP variables and register returns.
  No shared stack protocol.
- **Cross-module calls** use `__fastcall__` convention: last
  (or only) argument in A/X, preceding arguments pushed via
  `pushax` onto the parameter stack (`sp` in ZP).
- **`asm_bridge.s`** translates between the parameter-stack
  convention and the assembler's ZP-based interface.
- **Callbacks** (disk.s SEQ I/O) pass function addresses in
  A/X; the callee invokes via `jmp (callback)`.
