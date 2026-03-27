# CSE — TODO

## Bugs

- [ ] 13 CMOS mnemonic gate bugs: pure CMOS mnemonics (BRA, PHX, PHY,
  PLX, PLY, TRB, TSB, STZ) assemble on NMOS when they shouldn't.
  CMOS *modes* (ZPI, ACC, AIX, BIT IMM) are correctly gated.
  See `test_nmos_rejects_cmos` xfail list.
- [ ] expr.s test harness: 12 xfails from missing cc65 C stack stubs.
  Redesign expr.s to use ZP args or fix the test stub.
- [ ] Stale comment in asm_vars.s:35 — `al_cpu` is 0=6502, 1=6510,
  2=65C02 (not 0=NMOS, 1=65C02).
- [ ] `j` command: reset colors after user code returns (user code
  may change VIC regs).
- [ ] RUN/STOP debounce: bounces when held.
- [ ] read_line: cc65 -O ternary miscompilation documented but not
  guarded — add regression test.

## Next

Small, concrete, ready to do now.

- [ ] Remove unused cse_io.h macros: io_cursor_on/off, io_bordercolor,
  io_bgcolor.
- [ ] Remove sym_top/sym_bot from repl.c (always NULL, dead branches
  in cmd_info).
- [ ] Merge print_string wrapper in screen.s (trivial jmp to io_puts)
  — have disk.s call io_puts directly.
- [ ] Write doc/testing.md: py65 harness architecture, conftest.py
  conventions, stub patterns, "test contracts not implementation"
  guidelines.  Migrate test harness rules from project_layout.md.
- [ ] Update project_layout.md: stale file list, line counts, test
  count.
- [ ] Update assembler_syntax.md: verify directive list against
  asm_src.s implementation.

## Planned

Defined scope, needs work.

### REPL

- [ ] Expression parsing for command address arguments: `j`, `m`, `s`,
  `l`, `w`, `+`, `-`, `b`.  Replace `parse_hex_flex` with `expr_eval`.
  Enables `j start`, `m screen`, `s table+$100`.  Consequence: bare
  `8000` becomes decimal; hex requires `$8000`.  The `AAAA:` prompt
  prefix stays as 4 hex digits — no expressions.
- [ ] `.` without args: behave like `d` (disassemble one instruction).
  Bare `.` (no `AAAA:` prefix) operates on `cur_addr` and rewrites
  its prompt line to include `AAAA:.`.
- [ ] `h` command: hunt/search for byte pattern in memory.
- [ ] `f` command: fill memory range with byte.
- [ ] `t` command: transfer/copy memory block.
- [ ] `k` command: implement (currently `n` in code, needs reassign).
  Confirms before clearing.
- [ ] Breakpoints (`!` command): BRK vector intercept, breakpoint table.
- [ ] Single-step (`n` command): step 1 or N instructions.
- [ ] Step-over (`o` command): skip into JSR.
- [ ] `g` command: JMP to address (no return) / continue from BRK.
- [ ] `=` command: define/query symbols from REPL.
- [ ] `@` command: disk command channel.

### Assembler

- [ ] dasm.s: wrap 65C02 decode paths and tables in `.ifdef
  CMOS_SUPPORT`.  Currently CMOS code always present, gated at
  runtime only.  Saves bytes for 6502/6510-only builds.
- [ ] Assembler error display: show source line number + context.

### Editor

- [ ] Handle files > gap buffer capacity (show error, don't crash).
- [ ] Warn on quit/switch if dirty flag set.
- [ ] Page up/down with shift+cursor or F-keys.
- [ ] Search (ctrl+f equivalent via F-key).
- [ ] Goto line number.

### Memory

- [ ] Utilize RAM under KERNAL ($E000-$FFFF) and I/O ($D000-$DFFF)
  for data structures that aren't hot all the time.  Bank in via $01,
  use, bank out.  Example: symbol table (768B) is only hot during
  assembly — disable interrupts and blank the screen for the duration.
  Candidates: symbol table, name heap, assembled output staging.
- [ ] C128: enable 2 MHz mode during assembly (VIC blanked anyway
  for banking).  Double assembly speed on C128 hardware.

### Architecture

- [ ] After full asm rewrite: relocate CSE code to end of memory
  ($8000+), freeing $0800-$7FFF as contiguous user workspace.
- [ ] Replace au_mode hex parser with expr_eval (option C): eliminate
  parse_hex.s, remove _insn_buf round-trip from asm_src.s, switch
  line assembler from VICII to PETSCII encoding.  Saves ~400 bytes
  code + 80 bytes BSS.  Requires mn_classify char conversion and
  expr error code mapping.  Touches 5 files.
- [ ] Redesign .s function interfaces to use ZP/register args instead
  of C stack.  Eliminates cse_popax shim.  Targets: disk.s, expr.s,
  asm_bridge.s.
- [ ] ZP optimization: overlap scratch for non-concurrent modules.
  ~14 bytes reclaimable from cold scratch, ~8 bytes overlappable
  (dasm vs asm_line).  See doc/README.md § principle 6.
- [ ] Relocate CSE to $8000 (PRG) or cartridge ROM (CRT).
- [ ] Dual linker configs: c64_cse.cfg (PRG) and c64_cse_crt.cfg (CRT).

### Size Optimization

- [ ] `repl.c` is 7KB CODE (34% of binary).  Port hot functions to
  asm: emit_dot, emit_mem, show_prompt, exec_line dispatch.
- [ ] `editor.c` is 4.4KB CODE (21%).  Port gap buffer ops and
  rendering to asm.

## Ideas

Exploratory, not yet scoped.

- [ ] PRG load: auto-detect load address from PRG header, show in output.
- [ ] `$` command: filter directory by filename glob.
- [ ] `d` command: show ASCII alongside disassembly (like `m`).
- [ ] `.` command: when no operand given for mnemonic that requires
  one, show help instead of ;?asm.
- [ ] Color command `c`: show color preview swatches.
- [ ] Disk I/O: timeout handling for unresponsive drives.
- [ ] NMI: not interruptible during `j` user code — flag checked only
  on return.
- [ ] REU (RAM Expansion Unit) support for large source files.
- [ ] Bank switching for >16KB cartridge (EasyFlash).
- [ ] Macro support: .macro/.endmacro.
- [ ] Conditional assembly: .if/.else/.endif.
- [ ] Include files: .inc (read and assemble from separate file).
- [ ] Detect PAL/NTSC at startup.
