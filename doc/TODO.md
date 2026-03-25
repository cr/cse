# CSE — TODO

## Code Cleanup

- [ ] Fix 13 CMOS mnemonic gate bugs: pure CMOS mnemonics (BRA, PHX, PHY, PLX, PLY, TRB, TSB, STZ) assemble on NMOS when they shouldn't. CMOS *modes* (ZPI, ACC, AIX, BIT IMM) are correctly gated. See `test_nmos_rejects_cmos` xfail list.
- [ ] Fix expr.s test harness: needs proper cc65 C stack simulation or redesign expr.s to not use C stack. See `test_expr.py` xfail.
- [ ] Redesign .s function interfaces to use ZP/register args instead of C stack. Eliminates need for cse_popax shim. Targets: disk.s, expr.s, asm_bridge.s.
- [ ] Remove unused cse_io.h macros: io_cursor_on/off, io_bordercolor, io_bgcolor (defined but never called)
- [ ] Remove sym_top/sym_bot from repl.c (always NULL, dead branches in cmd_info)
- [ ] Merge print_string wrapper in screen.s (trivial jmp to io_puts) — have disk.s call io_puts directly

## Documentation

- [x] Update architecture.md (in progress — agent fixing)
- [x] Update repl_commands.md (in progress)
- [x] Update memory_design.md (in progress)
- [x] Update project_layout.md (in progress)
- [x] Update cse_io_api.md (in progress)

## Size Optimization

- [ ] `repl.c` is 7KB CODE (34% of binary). Port hot functions to asm: emit_dot, emit_mem, show_prompt, exec_line dispatch.
- [ ] `editor.c` is 4.4KB CODE (21%). Port gap buffer ops and rendering to asm.
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
- [ ] Editor: handle files > gap buffer capacity gracefully (show error, don't crash)
- [ ] Editor: warn on quit/switch if dirty flag set
- [ ] Disk I/O: timeout handling for unresponsive drives
- [ ] read_line: cc65 -O ternary miscompilation documented but not guarded — add regression test
- [ ] RUN/STOP debounce: currently bounces when held. Move editor toggle to a different key, or implement proper debounce.
- [ ] NMI (RUN/STOP+RESTORE): not interruptible during `j` user code — flag checked only on return.

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

- [x] CRT-ready: all self-modifying code removed
- [x] .s files free of cc65 runtime imports (cse_popax shim in cse_io.s)
- [x] NMI handler intercepts RUN/STOP+RESTORE
- [x] Cold start exit (JMP $FCE2) — clean BASIC restore
- [x] Free memory filled with $FF on init
- [ ] Relocate CSE to $8000 (PRG) or cartridge ROM (CRT)
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
