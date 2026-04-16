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
├──────────────┴────────────┴──────────────┤
│                 mem.s                    │  memory manager, banking
└──────────────────────────────────────────┘
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
| main.s | Hardware init, main loop, mode switch | [main.md](modules/main.md) |
| mem.s | Memory manager: banking, copy/fill, segment queries, init | [memory_design.md](memory_design.md) |
| repl.s | REPL command dispatch and emitters | [repl.md](modules/repl.md) |
| editor.s | Gap-buffer source editor, sequential reader, workend update | [editor.md](modules/editor.md) |
| asm_src.s | Two-pass source assembler | [asm_src.md](modules/asm_src.md) |
| asm_line.s | Single-line instruction assembler (PETSCII input), KERNAL banking, error recovery | [asm_line.md](modules/asm_line.md) |
| expr.s | Recursive-descent expression parser | [expr.md](modules/expr.md) |
| symtab.s | Hash-table symbol storage with name heap (banking via mem.s) | [symtab.md](modules/symtab.md) |
| dasm.s | Bit-slice disassembler (6502/6510/65C02) | [dasm.md](modules/dasm.md) |
| debugger.s | BRK-based breakpoints, single-step, context switch | [debugger.md](modules/debugger.md) |
| disk.s | CBM file I/O via KERNAL (PRG and SEQ, callback-based) | [disk.md](modules/disk.md) |
| screen.s | Scroll, newline, cursor, color theme | [screen.md](modules/screen.md) |
| cse_io.s | Raw screen I/O, keyboard, PETSCII→screencode | [cse_io.md](modules/cse_io.md) |
| strings.s | Centralised user-facing string constants (RODATA) | [strings.md](modules/strings.md) |

Support modules (internal to the assembler pipeline):

| Module | Purpose | Doc |
|--------|---------|-----|
| mn7.s / mn6.s | Perfect hash mnemonic classifier (mn7: 114, mn6: 56) | [mn_classify.md](modules/mn_classify.md) |
| opcode_lookup.s | (profile, mode) → opcode byte | [opcode_lookup.md](modules/opcode_lookup.md) |
| au_mode.s | Addressing mode operand parser | [au_mode.md](modules/au_mode.md) |
| mn_classify.s | Build-time dispatcher: selects mn6 or mn7 | [mn_classify.md](modules/mn_classify.md) |
| zp.s | Central zero-page layout (all 85 bytes) | — |
| mn_vars.s | Mnemonic classifier inputs (mn_c1/c2/c3) | — |

Generated files (do not edit — regenerate with `make tables`):

| File | Generator |
|------|-----------|
| mn7_tables.s, mn_asm_tables.s, mn_modes.s, mn_config.s | mnemonic_tables.py |
| dasm_tables.s | dasm_tables.py |

## Dependency Graph

```
main.s ── strings.s
├── mem.s (init, banking, segment queries) ── strings.s
├── repl.s ── strings.s
│   ├── asm_line.s ── opcode_lookup.s
│   │       ├── au_mode.s
│   │       └── mn_classify.s ── mn7.s ── mn7_tables.s
│   ├── asm_src.s ── asm_line.s, expr.s, symtab.s, editor.s, mem.s, strings.s
│   ├── dasm.s ── dasm_tables.s
│   ├── debugger.s
│   ├── expr.s ── symtab.s, strings.s
│   ├── disk.s ── screen.s ── cse_io.s, strings.s
│   └── screen.s
├── editor.s ── mem.s, strings.s
│   ├── disk.s
│   └── screen.s
└── symtab.s ── mem.s
```

## Dependency Rules

1. **No circular dependencies.**  The graph is a DAG.
2. **Near-leaf modules have minimal dependencies:** cse_io and strings
   have zero imports.  dasm and debugger import only ZP symbols and
   banking helpers from mem.s.
3. **Screen output flows one way:** module → screen → cse_io.
4. **disk.s uses callbacks** for SEQ I/O to avoid depending on editor.
5. **Expression parser depends only on symtab** — no I/O.
6. **All .s modules are self-contained** with explicit `.import`/`.export`.

## Calling Conventions

All modules are pure 6502 assembly.  No C compiler is used.

- **All calls** use register/ZP convention: last (or only)
  argument in A/X, preceding arguments in named ZP variables.
  No software parameter stack.  See memory_design.md § Calling
  Convention.
- **Callbacks** (disk.s SEQ I/O) pass function addresses in
  A/X; the callee invokes via `jmp (callback)`.
