# CSE — TODO

## Code Cleanup

- [ ] Fix 13 CMOS mnemonic gate bugs: pure CMOS mnemonics (BRA, PHX, PHY, PLX, PLY, TRB, TSB, STZ) assemble on NMOS when they shouldn't. CMOS *modes* (ZPI, ACC, AIX, BIT IMM) are correctly gated. See `test_nmos_rejects_cmos` xfail list.
- [ ] Fix expr.s test harness: needs proper cc65 C stack simulation (pushax/popax) or redesign expr.s to not use C stack. See `test_expr.py` xfail.
- [ ] Redesign .s function interfaces to use ZP/register args instead of C stack. Eliminates need for cse_popax shim. Targets: disk.s, expr.s, asm_bridge.s.

## Documentation

- [ ] Update architecture.md: screen.c→screen.s, disk.c→disk.s, expr.c→expr.s
- [ ] Update architecture.md: disk function signatures (floppy_status, not disk_status)
- [ ] Update architecture.md: expr only supports hex literals, not full expressions
- [ ] Update repl_commands.md: mark i, ?, c, u as implemented
- [ ] Update memory_design.md: source grows from $C7FF not $7FFF; self-mod code removed
- [ ] Update project_layout.md: stale line counts, missing modules, deleted legacy files
- [ ] Sync doc/cse_io_api.md with actual cse_io.s exports (cse_popax/cse_popa added)

## Size Optimization

- [ ] `repl.c` is 7KB CODE (34% of binary). Port hot functions to asm: emit_dot, emit_mem, show_prompt, exec_line dispatch.
- [ ] `editor.c` is 4.4KB CODE (21%). Port gap buffer ops and rendering to asm.
- [ ] Merge `print_string` wrapper (trivial jmp to io_puts) — call io_puts directly.
- [ ] Replace strncpy in repl.c with manual byte copy (~68 bytes saved).
- [ ] Remove symtab.o/asm_src.o stubs from link until needed (~40 bytes).

## Test Coverage

- [ ] build_open_str unit tests (suffix detection was buggy)
- [ ] parse_hex.s standalone tests (VICII screencode edge cases)
- [ ] Assembler→disassembler round-trip tests
- [ ] Editor gap buffer binary tests (currently Python-only simulation)

## Features

- [ ] Disassembler: finish fixing remaining test failures across all 3 CPU modes
- [ ] Source assembler (asm_src.c): 2-pass assembly from gap buffer
- [ ] Symbol table (symtab.c): hash table for labels
- [ ] Expression parser: extend beyond hex literals (+, -, *, /, <, >, labels, %)
- [ ] Breakpoints (! command)
- [ ] Single-step trace (t command)
- [ ] Relocate CSE to $8000 (PRG) or cartridge ROM (CRT)
