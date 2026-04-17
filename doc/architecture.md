# Module Architecture — Module map, dependency graph, boundary rules

**Template:** [subsystem](templates/subsystem.md)

## CSE as a kernel

CSE's runtime is a **kernel** in the OS sense, not an application.
The REPL is the body of an interrupt service routine reached via
BRK; user programs are an alternate execution mode reached via RTI
from a synthesized frame.

- **kernel → userland**: `return_to_user` (debugger.s) synthesizes
  an RTI frame, sets `in_userland`, RTIs into user code.
- **userland → kernel**: BRK (breakpoint, step-BRK, or `brk_stub`
  on user's top-level RTS) or NMI (RUN/STOP+RESTORE).  Handled by
  `cse_brk_handler` / `cse_nmi_handler` in main.s.

Vocabulary distinction (also in [glossary.md](glossary.md)):

- **kernal** = the CBM KERNAL ROM ($E000–$FFFF).  Spelled with `a`.
- **kernel** = CSE's runtime.  Spelled with `e`.
- **userland** = the execution mode where user code runs.

Full design: [design_cse_as_kernel.md](design_cse_as_kernel.md).
Contract user code may rely on / must preserve:
[userland_contract.md](userland_contract.md).

## Layer Diagram

```
┌──────────────────────────────────────────┐
│                main.s                    │  ISR dispatcher: cse_brk_handler,
│                                          │  cse_nmi_handler, setup_interrupts,
│                                          │  in_userland flag, main_loop
├────────────────┬─────────────────────────┤
│    repl.s      │       editor.s          │  user-facing modes
├────────────────┴──┬───────────┬──────────┤
│    asm_src.s      │  expr.s   │ symtab.s │  source assembler pipeline
├───────────────────┴───────────┴──────────┤
│  asm_line.s  │   dasm.s   │   disk.s     │  core engines
├──────────────┴────────────┴──────────────┤
│  debugger.s  │  screen.s  │   cse_io.s   │  low-level services
│  (return_to_user, brk_stub, bp table)    │
├──────────────────────────────────────────┤
│                 mem.s                    │  memory manager, banking
└──────────────────────────────────────────┘
       │
       │  return_to_user (RTI to synthesized frame; j/g/t/o/c)
       ▼
┌──────────────────────────────────────────┐
│             user code                    │  runs in workspace memory
│  own register state, shared 6502 stack   │  BRK / NMI / brk_stub → kernel
└──────────────────────────────────────────┘
```

Higher layers depend on lower layers.  No upward or circular
dependencies.  Each layer can be understood without reading the
layers above it.

**User code** is not a CSE module — it is assembled output living
in workspace memory (`workstart`–`workend`).  `return_to_user`
synthesizes an RTI frame from `reg_a`/`reg_x`/`reg_y`/`reg_p`/
`brk_pc`, pushes `brk_stub - 1` as user's top-level RTS sentinel,
sets `in_userland`, and RTIs.  User code runs with full CPU access
until BRK or NMI.  On break, the kernel captures user state into
the `reg_*` shadows, longjmps SP back to its main_loop value, and
flows back into the REPL.  User and kernel **share** the single
hardware stack page; the kernel never reads bytes below the user's
SP, and the user must leave a documented headroom for kernel re-entry
(see [userland_contract.md § 4](userland_contract.md#4-stack-contract)).

## Modules

| Module | Purpose | Doc |
|--------|---------|-----|
| main.s | ISR dispatch (cse_brk_handler, cse_nmi_handler), setup_interrupts, in_userland flag, main_loop | [main.md](modules/main.md) |
| mem.s | Memory manager: banking, copy/fill, segment queries | [memory_design.md](memory_design.md) |
| repl.s | REPL command dispatch and emitters (the ISR body) | [repl.md](modules/repl.md) |
| editor.s | Gap-buffer source editor, sequential reader, workend update | [editor.md](modules/editor.md) |
| asm_src.s | Two-pass source assembler | [asm_src.md](modules/asm_src.md) |
| asm_line.s | Single-line instruction assembler (PETSCII input), kernal banking, error recovery | [asm_line.md](modules/asm_line.md) |
| expr.s | Recursive-descent expression parser | [expr.md](modules/expr.md) |
| symtab.s | Hash-table symbol storage with name heap (banking via mem.s) | [symtab.md](modules/symtab.md) |
| dasm.s | Bit-slice disassembler (6502/6510/65C02) | [dasm.md](modules/dasm.md) |
| debugger.s | BRK-based breakpoints, single-step, return_to_user helper, brk_stub | [debugger.md](modules/debugger.md) |
| disk.s | CBM file I/O via kernal (PRG and SEQ, callback-based) | [disk.md](modules/disk.md) |
| screen.s | Scroll, newline, cursor, color theme, vic_reset | [screen.md](modules/screen.md) |
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
