# Module Architecture — Module map, dependency graph, boundary rules

**Template:** [subsystem](templates/subsystem.md)

## CSE as a kernel

CSE's runtime is a **kernel** in the OS sense, not an application.
The REPL is the body of an interrupt service routine reached via
BRK; user programs are an alternate execution mode reached via RTI
from a synthesized frame.

- **kernel → userland**: `return_to_userland` (fresh start) or
  `restore_userland_state` (resume), both in debugger.s, synthesize an
  RTI frame, set `in_userland`, and RTI into user code.
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
│ L3  asm_line, addr_mode, opcode_lookup, expr, dasm, breakpoints,    │  core engines
│     gap_buffer                                                      │
├─────────────────────────────────────────────────────────────────────┤
│ L2  screen, symtab, log, asm_err                                    │  structured services
├─────────────────────────────────────────────────────────────────────┤
│ L1  mem, cse_io, mn_classify (mn6 / mn7 / mn_vars)                  │  primitive services
├─────────────────────────────────────────────────────────────────────┤
│ L0  zp, strings, *_tables, oplen_tbl, dasm_mne_idx                  │  pure data
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
in workspace memory (`workstart`–`workend`).  The kernel enters it
with an RTI built from `reg_a`/`reg_x`/`reg_y`/`reg_p`/`brk_pc`; a
fresh start first pushes `brk_stub - 1` as the program's top-level
return address.  User code runs with full CPU access until BRK or
NMI.  On break, the kernel captures user state into the `reg_*`
shadows, sets SP to the user's SP and flows back into the REPL,
which runs on the stack below it.  User and kernel **share** the
single hardware stack page; the kernel never writes above the
user's SP, and the user leaves a documented headroom below it for
kernel re-entry
(see [userland_contract.md § 4](userland_contract.md#4-stack-contract)).

## Modules

| Module | Layer | Purpose | Doc |
|--------|-------|---------|-----|
| main.s | 5 | ISR dispatch (cse_brk_handler, cse_nmi_handler), setup_interrupts, main_loop, warmstart entry points | [main.md](modules/main.md) |
| repl.s | 5 | REPL command dispatch and emitters (the ISR body) | [repl.md](modules/repl.md) |
| asm_src.s | 4 | Two-pass source assembler | [asm_src.md](modules/asm_src.md) |
| editor.s | 4 | Keystroke dispatch, screen rendering, disk I/O, enter/leave_editor | [editor.md](modules/editor.md) |
| disk.s | 4 | CBM file I/O via kernal (PRG and SEQ, callback-based) | [disk.md](modules/disk.md) |
| debugger.s | 4 | Step state machine, kernel↔userland gates (save/restore_userland_state, return_to_userland), brk_stub, dbg_init | [debugger.md](modules/debugger.md) |
| asm_line.s | 3 | Single-line instruction assembler (PETSCII input) | [asm_line.md](modules/asm_line.md) |
| breakpoints.s | 3 | Breakpoint-table CRUD + patch/unpatch (bundle-testable) | [breakpoints.md](modules/breakpoints.md) |
| gap_buffer.s | 3 | Gap-buffer primitives + sequential reader (bundle-testable) | [gap_buffer.md](modules/gap_buffer.md) |
| addr_mode.s | 3 | Addressing-mode and operand parser | [addr_mode.md](modules/addr_mode.md) |
| opcode_lookup.s | 3 | (profile, mode) → opcode byte | [opcode_lookup.md](modules/opcode_lookup.md) |
| expr.s | 3 | Recursive-descent expression parser | [expr.md](modules/expr.md) |
| dasm.s | 3 | Opcode-map disassembler over the CPU set's generated tables; 45GS02 prefix peel on m65 | [dasm.md](modules/dasm.md) |
| screen.s | 2 | Scroll, newline, cursor, color theme, vic_reset | [screen.md](modules/screen.md) |
| symtab.s | 2 | Hash-table symbol storage with name heap (banking via mem.s) | [symtab.md](modules/symtab.md) |
| log.s | 2 | Standardised logging API (log_open / log_close / log_err / log_warn / log_info) | [log.md](modules/log.md) |
| asm_err.s | 2 | Assembler error state + longjmp unwind (asm_error, asm_syntax_error, asm_expr_error, asm_cpu_error, asm_pass) | [asm_err.md](modules/asm_err.md) |
| mem.s | 1 | Memory manager: banking, ZP save/restore, segment queries | [mem.md](modules/mem.md) |
| cse_io.s | 1 | Raw screen I/O, keyboard, PETSCII→screencode | [cse_io.md](modules/cse_io.md) |
| mn_classify.s | 1 | Build-time dispatcher: selects mn6 or mn7 | [mn_classify.md](modules/mn_classify.md) |
| mn7.s / mn6.s | 1 | Perfect hash mnemonic classifier (mn7: 114 on C64, 98 on m65; mn6: 56) | [mn_classify.md](modules/mn_classify.md) |
| mn_vars.s | 1 | Empty shell: states the classifier input convention; `mn_c1`/`mn_c2`/`mn_c3` live in zp.s | [mn_classify.md](modules/mn_classify.md) |
| zp.s | 0 | Central zero-page layout (all user ZP + shared cross-module flags) | [zp.md](modules/zp.md) |
| strings.s | 0 | Centralised user-facing string constants (RODATA) | [strings.md](modules/strings.md) |
| loader.s | 6 | Discardable cold-boot stub (copies CODE+RODATA+KDATA into runtime location) | [loader.md](modules/loader.md) |

Generated files (do not edit — regenerate with `make tables`):

| File | Generator | Owning doc |
|------|-----------|------------|
| mn7_tables.s, mn6_tables.s | [`dev/mnemonic_tables.py`](../dev/mnemonic_tables.py) | [mn_classify.md](modules/mn_classify.md) |
| mn_asm_tables.s, mn_modes.s | [`dev/mnemonic_tables.py`](../dev/mnemonic_tables.py) | [opcode_lookup.md](modules/opcode_lookup.md) |
| oplen_tbl.s | [`dev/mnemonic_tables.py`](../dev/mnemonic_tables.py) | [opcode_lookup.md](modules/opcode_lookup.md) |
| dasm_tables.s, dasm_mne_idx.s | [`dev/dasm_tables.py`](../dev/dasm_tables.py) | [dasm.md](modules/dasm.md) |

## Dependency Graph

Per-module dependencies, as the `.import`/`.importzp` statements of
`src/*.s` resolve them (the module that exports each symbol).
Every entry goes to a strictly lower layer, or to a same-layer
sibling permitted by [rule 2](#dependency-rules).

| Module | → depends on |
|---|---|
| loader | main (+ linker symbols) |
| main | repl, editor, debugger, asm_line, breakpoints, gap_buffer, screen, symtab, log, mem, cse_io, strings, zp |
| repl | main, asm_src, editor, disk, debugger, asm_line, breakpoints, gap_buffer, dasm, expr, symtab, screen, log, asm_err, mem, cse_io, oplen_tbl, strings, zp (+ linker symbols) |
| asm_src | asm_line, gap_buffer, expr, symtab, screen, log, asm_err, mem, cse_io, strings, zp |
| editor | disk, gap_buffer, mem, cse_io, zp (+ linker symbols) |
| disk | screen, log, cse_io, strings, zp |
| debugger | asm_line, breakpoints, oplen_tbl, mem, zp |
| asm_line | addr_mode, opcode_lookup, expr, mn_classify, mn_asm_tables, mn_modes, asm_err, mem, zp |
| breakpoints | zp |
| gap_buffer | symtab, strings, zp (+ linker symbols) |
| addr_mode | expr, symtab, log, asm_err, strings, zp |
| opcode_lookup | mn_asm_tables, mn_modes, zp |
| expr | symtab, mem, strings, zp |
| dasm | dasm_tables, mem, zp (`.include`s dasm_mne_idx.s) |
| screen | cse_io, zp |
| symtab | mem, zp |
| log | screen, cse_io, strings, zp |
| asm_err | mem, zp |
| mem | zp (+ linker symbols) |
| cse_io | zp |
| mn_classify | mn6 / mn7, mn6_tables / mn7_tables |
| mn6 / mn7 | mn6_tables / mn7_tables, zp |
| mn_vars | zp (imports only; exports nothing) |
| zp, strings, *_tables, oplen_tbl, dasm_mne_idx | (leaves) |

No module exports state for a higher layer to reach down into:
the shared flags, `cur_project_name` and the output-formatter
scratch (`rp_addr`, `rp_cnt`, `rp_save`, `rp_save2`, `rp_next_lo`,
`_info_mode`) live in zp.s, the range formatters (`seg_line`,
`prg_line`, `free_line`) in log.s, and the register shadows
(`reg_*`) in asm_line.s, below every module that uses them.
`main.s` and `repl.s` include `dbg_reason.inc`, the one definition
of the `dbg_reason` values.

## Dependency Rules

1. **DAG, strictly downward cross-layer.**  Every `.import` /
   `.importzp` that crosses a layer boundary resolves to a module
   in a strictly lower layer.  `dev/check_deps.py` checks it by
   scanning the source tree.
2. **Same-layer imports are permitted when acyclic.**  Within a
   layer, forward imports among siblings are allowed if the induced
   subgraph is a DAG.  Current intentional intra-layer edges:
   - L1: `mn_classify → mn6 / mn7` (build-time mutually exclusive).
   - L2: `log → screen` (log uses newline).
   - L3: `asm_line → addr_mode → expr`, `asm_line → expr` and
     `asm_line → opcode_lookup` (the core-engines chain).
   - L4: `editor → disk` (SEQ callbacks).
   - L5: **`main ↔ repl` cycle (intentional)** — the two
     dispatchers co-operate by design.  main owns the ISR bodies
     and warmstart entry points; repl owns the command handlers,
     which reach back for the warmstart entry points and
     `run_user_pending`.  This is the only permitted cycle in the
     corpus.
3. **Near-leaf modules have minimal dependencies:** cse_io imports
   only zp; mem imports only zp; strings has zero imports.
4. **Screen output flows one way:** module → log or screen → cse_io.
5. **disk.s uses callbacks** for SEQ I/O to avoid depending on editor.
6. **Expression parser depends only on symtab** (plus mem for banking
   and strings for its error texts) — no I/O.
7. **Shared cross-module flags live in zp.s** (`in_userland`, `state`,
   `warm_cont`, `kernal_out`, `ed_dirty`, `dbg_reason`, `cur_device`;
   writers and readers in [zp.md](modules/zp.md)).  Modules that
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
