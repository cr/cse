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

- [ ] Fix 13 xfails: CMOS mnemonic gate in assembler (test_nmos_rejects_cmos)
- [ ] Fix 12 xfails: expr.s test harness cc65 C stack stubs (test_expr.py)
- [ ] Fix 1 xpass: test_zero in expr accidentally passes — tighten test
- [ ] build_open_str unit tests (suffix detection was buggy)
- [ ] parse_hex.s standalone tests (VICII screencode edge cases)
- [ ] Assembler→disassembler round-trip tests
- [ ] Editor gap buffer binary tests (currently Python-only simulation)

## Robustness

- [ ] `j` command: reset colors after user code returns (user code may change VIC regs)
- [ ] `j` command with arg: `j 1234` should JSR to $1234, not just cur_addr
- [ ] Editor: handle files > gap buffer capacity gracefully (show error, don't crash)
- [ ] Editor: warn on quit/switch if dirty flag set
- [ ] Disk I/O: timeout handling for unresponsive drives
- [ ] read_line: cc65 -O ternary miscompilation documented but not guarded — add regression test
- [ ] `w` PRG without end address: save exactly block_size bytes (currently broken?)

## UX Polish

- [ ] `h` command: hunt/search for byte pattern in memory
- [ ] `f` command: fill memory range with byte
- [ ] `t` command: transfer/copy memory block
- [ ] `n` command: compare two memory blocks
- [ ] `.` command: when no operand given for mnemonic that requires one, show help not ?asm
- [ ] `d` command: show ascii representation alongside disassembly (like the m command)
- [ ] `$` command: support `$ pattern` to filter directory by filename glob
- [ ] Editor: page up/down with shift+cursor or F-keys
- [ ] Editor: search (ctrl+f equivalent via F-key)
- [ ] Editor: goto line number
- [ ] Startup: detect PAL/NTSC and adjust timing-sensitive code if any
- [ ] Color command `c`: show color preview swatches on C64 color palette

## Architecture

- [ ] Relocate CSE to $8000 (PRG) or cartridge ROM (CRT)
- [ ] CRT-ready: all self-modifying code removed ✓ — verify no regressions
- [ ] Dual linker configs: c64_cse.cfg (PRG at $0801) and c64_cse_crt.cfg (ROM at $8000)
- [ ] Editor screen: use $0C00 (CRT) or $8000 (PRG relocated) — currently saves to BSS
- [ ] Consider: REU (RAM Expansion Unit) support for large source files
- [ ] Consider: bank switching for >16KB cartridge (EasyFlash)

## Features

- [ ] Source assembler (asm_src.c): 2-pass assembly from gap buffer
- [ ] Symbol table (symtab.c): hash table for labels
- [ ] Expression parser: extend beyond hex literals (+, -, *, /, <, >, labels, %)
- [ ] Directives: *= (origin), .byte, .word, .text, .cpu, .include
- [ ] Labels: name: at start of line, .local labels with . prefix
- [ ] Assembler error display: line number + source context
- [ ] Breakpoints (! command): BRK vector intercept, breakpoint table
- [ ] Single-step trace (t command): BRK after each instruction
- [ ] `a` command: assemble source buffer to target memory
- [ ] `=` command: define/query symbols from REPL
- [ ] `>` / `<` commands: save/load memory blocks with address ranges
- [ ] PRG load: auto-detect load address from PRG header, show in output
- [ ] Macro support (future): .macro/.endmacro
- [ ] Conditional assembly (future): .if/.else/.endif
