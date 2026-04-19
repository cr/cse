# Module Architecture — Module map, dependency graph, boundary rules

**Template:** [subsystem](templates/subsystem.md)

## CSE as a kernel

CSE's runtime is a **kernel** in the OS sense, not an application.
The REPL is the body of an interrupt service routine reached via
BRK; user programs are an alternate execution mode reached via RTI
from a synthesized frame.

- **kernel → userland**: `return_to_userland` (debugger.s) synthesizes
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
┌─────────────────────────────────────────────────────────────────────┐
│ L6  loader                                                          │  bootstrap
├─────────────────────────────────────────────────────────────────────┤
│ L5  main, repl                                                      │  dispatchers
├─────────────────────────────────────────────────────────────────────┤
│ L4  asm_src, editor, disk, debugger                                 │  application subsystems
├─────────────────────────────────────────────────────────────────────┤
│ L3  asm_line, addr_mode, opcode_lookup, expr, dasm                  │  core engines
├─────────────────────────────────────────────────────────────────────┤
│ L2  screen, symtab, log, asm_err                                    │  structured services
├─────────────────────────────────────────────────────────────────────┤
│ L1  mem, cse_io, mn_classify (mn6 / mn7 / mn_vars)                  │  primitive services
├─────────────────────────────────────────────────────────────────────┤
│ L0  zp, strings, *_tables, mn_config, oplen_tbl, dasm_mne_idx       │  pure data
└─────────────────────────────────────────────────────────────────────┘
       │
       │  return_to_userland (RTI to synthesized frame; j/g/t/o/c)
       ▼
┌──────────────────────────────────────────┐
│             user code                    │  runs in workspace memory
│  own register state, shared 6502 stack   │  BRK / NMI / brk_stub → kernel
└──────────────────────────────────────────┘
```

**Strict DAG invariant.**  Every `.import` / `.importzp` resolves to
a module in a *strictly lower* layer.  No back-edges, no mutual
recursion, no siblings-reach-sideways.  The graph is mechanically
verifiable by scanning the source tree (see
[Dependency Rules](#dependency-rules) below).

Higher layers depend on lower layers.  No upward or circular
dependencies.  Each layer can be understood without reading the
layers above it.

**User code** is not a CSE module — it is assembled output living
in workspace memory (`workstart`–`workend`).  `return_to_userland`
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

| Module | Layer | Purpose | Doc |
|--------|-------|---------|-----|
| main.s | 5 | ISR dispatch (cse_brk_handler, cse_nmi_handler), setup_interrupts, main_loop, warmstart entry points | [main.md](modules/main.md) |
| repl.s | 5 | REPL command dispatch and emitters (the ISR body) | [repl.md](modules/repl.md) |
| asm_src.s | 4 | Two-pass source assembler | [asm_src.md](modules/asm_src.md) |
| editor.s | 4 | Gap-buffer source editor, sequential reader, workend update | [editor.md](modules/editor.md) |
| disk.s | 4 | CBM file I/O via kernal (PRG and SEQ, callback-based) | [disk.md](modules/disk.md) |
| debugger.s | 4 | BRK-based breakpoints, single-step, return_to_userland helper, brk_stub | [debugger.md](modules/debugger.md) |
| asm_line.s | 3 | Single-line instruction assembler (PETSCII input) | [asm_line.md](modules/asm_line.md) |
| addr_mode.s | 3 | Addressing-mode and operand parser | [addr_mode.md](modules/addr_mode.md) |
| opcode_lookup.s | 3 | (profile, mode) → opcode byte | [opcode_lookup.md](modules/opcode_lookup.md) |
| expr.s | 3 | Recursive-descent expression parser | [expr.md](modules/expr.md) |
| dasm.s | 3 | Bit-slice disassembler (6502/6510/65C02) | [dasm.md](modules/dasm.md) |
| screen.s | 2 | Scroll, newline, cursor, color theme, vic_reset | [screen.md](modules/screen.md) |
| symtab.s | 2 | Hash-table symbol storage with name heap (banking via mem.s) | [symtab.md](modules/symtab.md) |
| log.s | 2 | Standardised logging API (log_open / log_close / log_err / log_warn / log_info) | [log.md](modules/log.md) |
| asm_err.s | 2 | Assembler error state + longjmp unwind (asm_syntax_error, asm_expr_error, asm_pass) | [asm_err.md](modules/asm_err.md) |
| mem.s | 1 | Memory manager: banking, ZP save/restore, segment queries | [memory_design.md](memory_design.md) |
| cse_io.s | 1 | Raw screen I/O, keyboard, PETSCII→screencode | [cse_io.md](modules/cse_io.md) |
| mn_classify.s | 1 | Build-time dispatcher: selects mn6 or mn7 | [mn_classify.md](modules/mn_classify.md) |
| mn7.s / mn6.s | 1 | Perfect hash mnemonic classifier (mn7: 114, mn6: 56) | [mn_classify.md](modules/mn_classify.md) |
| mn_vars.s | 1 | Mnemonic classifier inputs (mn_c1/c2/c3) | — |
| zp.s | 0 | Central zero-page layout (all user ZP + shared cross-module flags) | [zp.md](modules/zp.md) |
| strings.s | 0 | Centralised user-facing string constants (RODATA) | [strings.md](modules/strings.md) |
| loader.s | 6 | Discardable cold-boot stub (copies CODE+RODATA+KDATA into runtime location) | — |

Generated files (do not edit — regenerate with `make tables`):

| File | Generator |
|------|-----------|
| mn7_tables.s, mn_asm_tables.s, mn_modes.s, mn_config.s | mnemonic_tables.py |
| dasm_tables.s | dasm_tables.py |

## Dependency Graph

Per-module dependency list (target state).  Every entry goes to a
strictly lower layer; no back-edges.

| Module | → depends on |
|---|---|
| loader | main (+ linker constants) |
| main | repl, editor, debugger, asm_line, screen, cse_io, symtab, mem, log, strings, zp |
| repl | asm_src, editor, disk, debugger, asm_line, dasm, expr, symtab, screen, log, asm_err, mem, cse_io, oplen_tbl, strings, zp |
| asm_src | editor, asm_line, expr, symtab, log, asm_err, mem, cse_io, strings, zp |
| editor | disk, screen, symtab, log, mem, cse_io, strings, zp |

All Layer-4 modules depend strictly downward after Phase 21 + 21.1.
The `cur_project_name` buffer, the `seg_line`/`prg_line`/`free_line`
range formatters, and the shared scratch pool (`rp_addr`/`rp_cnt`/
`rp_save`/`rp_save2`/`rp_next_lo`/`_info_mode`) all live in their
semantic homes (zp.s or log.s) and the dispatcher modules no longer
export state that lower layers reach up for.
| disk | screen, log, cse_io, strings, zp |
| debugger | asm_line, mem, oplen_tbl, zp |
| asm_line | addr_mode, opcode_lookup, mn_classify, asm_err, mem, zp |
| addr_mode | expr, asm_err, zp |
| opcode_lookup | mn_asm_tables, mn_modes, asm_err, zp |
| expr | symtab, strings, mem, zp |
| dasm | dasm_tables, mem, zp |
| screen | cse_io, strings, zp |
| symtab | mem, zp |
| log | cse_io, strings, zp |
| asm_err | mem, zp |
| mem | zp |
| cse_io | zp |
| mn_classify | mn6, mn7, mn6_tables, mn7_tables |
| mn6 / mn7 | mn_vars, mn6_tables / mn7_tables, zp |
| mn_vars | zp |
| zp, strings, *_tables, mn_config, oplen_tbl, dasm_mne_idx | (leaves) |

## Dependency Rules

1. **DAG, strictly downward cross-layer.**  Every `.import` /
   `.importzp` that crosses a layer boundary resolves to a module
   in a strictly lower layer.  Mechanically verifiable by scanning
   the source tree (the deferred `dev/check_deps.py` tool will
   enforce this in CI).
2. **Same-layer imports are permitted when acyclic.**  Within a
   layer, forward imports among siblings are allowed if the induced
   subgraph is a DAG.  Current intentional intra-layer edges:
   - L1: `mn_classify → mn6 / mn7` (build-time mutually exclusive).
   - L2: `log → screen` (log uses newline).
   - L3: `asm_line → addr_mode → expr` and `asm_line → opcode_lookup`
     (the core-engines chain).
   - L4: `asm_src → editor` (source reader), `editor → disk`
     (SEQ callbacks).
   - L5: **`main ↔ repl` cycle (intentional)** — the two
     dispatchers co-operate by design.  main owns the ISR bodies
     and warmstart entry points; repl owns the command loop.
     Phase 18 established this coupling.  This is the only
     permitted cycle in the corpus.
3. **Near-leaf modules have minimal dependencies:** cse_io imports
   only zp; mem imports only zp; strings has zero imports.
4. **Screen output flows one way:** module → log or screen → cse_io.
5. **disk.s uses callbacks** for SEQ I/O to avoid depending on editor.
6. **Expression parser depends only on symtab** (and mem for banking) — no I/O.
7. **Shared cross-module flags live in zp.s** (`in_userland`, `state`,
   `warm_cont`, `kernal_out`, `ed_dirty`, `dbg_reason`).  Modules that
   own a flag's semantics write it; modules that observe it read it.
   No module hosts a flag read by a *lower* layer.
8. **All .s modules are self-contained** with explicit `.import`/
   `.export`.  No implicit-scope leakage.

## Calling Conventions

All modules are pure 6502 assembly.  No C compiler is used.

- **All calls** use register/ZP convention: last (or only)
  argument in A/X, preceding arguments in named ZP variables.
  No software parameter stack.  See memory_design.md § Calling
  Convention.
- **Callbacks** (disk.s SEQ I/O) pass function addresses in
  A/X; the callee invokes via `jmp (callback)`.
