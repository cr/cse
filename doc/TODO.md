# CSE — TODO

## Bugs

- [x] ~~13 CMOS mnemonic gate bugs~~ — fixed in `2939a94`: added
  cat=11 check in asm_line.s CMOS gate.
- [x] ~~expr.s test harness: 12 xfails~~ — resolved, 146 tests pass.
- [x] ~~al_cpu 3-valued semantics~~ — fixed: asm_line.s uses
  `cmp #2`/`bcs`/`bcc`, comments updated, tests use al_cpu=2.
- [x] ~~`j` command: reset colors after user code returns~~ — done:
  `restore_colors()` called in both `cmd_jmp()` paths (direct and debugger).
- [ ] RUN/STOP debounce: bounces when held.
- [ ] `.` and `m` commands show/modify CSE's internal ZP state instead
  of the user's ZP state from `j`/debugger context.  After `j` returns
  (BRK/NMI), CSE restores its own ZP — so `.`/`m` on $00–$7F see CSE
  variables, not what the user's code left there.  Fix: save/restore
  user ZP snapshot on debug return; `.`/`m` should read from that
  snapshot when addressing $00–$7F.
- [x] ~~read_line: cc65 -O ternary miscompilation~~ — eliminated:
  repl.s is pure asm (Phase 6).  (CC65 -O BUG #1)
- [x] ~~cmd_step: cc65 -O uint8_t return zero-extension bug~~ —
  eliminated: repl.s is pure asm (Phase 6).  (CC65 -O BUG #2)

## Next

Small, concrete, ready to do now.

- [x] ~~Remove unused cse_io.h macros~~ — done: io_cursor_on/off,
  io_bordercolor, io_bgcolor deleted.
- [x] ~~Remove sym_top/sym_bot from repl.c~~ — done: always NULL,
  dead branches in cmd_info removed.
- [x] ~~Merge print_string wrapper in screen.s~~ — done: disk.s
  calls io_puts directly, wrapper removed.
- [ ] DDD audit module docs against code: asm_line, au_mode,
  opcode_lookup, mn_classify, mn7, editor, main, meminfo.

## Planned

Defined scope, needs work.

### REPL

- [x] ~~Expression parsing for command address arguments~~ — done:
  `@`, `j`, `+`, `-`, `b ADDR`, `s END` use `expr_eval`.  Enables
  `j main`, `@ table+$100`, `b start`.  Bare digits are now decimal;
  hex requires `$`.  `t`/`o` counts and `B` size stay as plain hex.
- [ ] `.` without args: behave like `d` (disassemble one instruction).
  Bare `.` (no `AAAA:` prefix) operates on `cur_addr` and rewrites
  its prompt line to include `AAAA:.`.
- [ ] `/` command: search for byte pattern in memory.
- [ ] `f` command: fill memory range with byte.
- [ ] `>` command: transfer/copy memory block (was `t`).
- [ ] `k` command: implement.  Confirms before clearing.
- [x] Debugger: `b` (breakpoints), `c` (continue), `t` (trace/step-into),
  `o` (trace-over/step-over).  BRK-based, full context switch with stack page
  snapshot.  NMI as ad-hoc break.  See [debugger.md](modules/debugger.md).
- [x] Command reassignment: `c`→`C`, `b`→`B`, `s`→`@`, `w`→`s`.
- [x] `g` command: run from `main` symbol; falls back to `j cur_addr` if
  `main` undefined.  After `a` (assemble), `cur_addr` advances to `main`
  if it was defined.
- [ ] `=` command: define/query symbols from REPL.
- [ ] Disk command channel: unified under `$` (`$ s:file`, `$9`, etc.).
  Drive select and directory work; command send needs disk.s extension.

### Assembler

- [x] ~~Compile-time CPU gating~~ — done: asm_line.s, dasm.s, repl.c
  all use `.ifdef CMOS_SUPPORT` / `.ifndef CPU_6502` / `#ifdef`.
  See Roadmap R1.
- [ ] Assembler error display: show source line number + context.

### Editor

- [x] Intelligent tabbing: gutter model with RETURN auto-indent,
  SPACE/INS indent to tab stop, DEL unindent, cursor gutter skip.
  `tab_width ≥ 1` enables; `tab_width = 0` disables.
- [ ] Handle files > gap buffer capacity (show error, don't crash).
- [ ] Warn on quit/switch if dirty flag set.
- [ ] Page up/down with shift+cursor or F-keys.
- [ ] Search (ctrl+f equivalent via F-key).
- [ ] Goto line number.

### Memory

- [x] ~~Utilize RAM under KERNAL~~ — done in `440d8e3`: sym_table
  (768B) at $FC00, repl_screen (1000B) at $F818, NMI trampoline
  at $FF00.  Banking guards (sei/cli + $01 bit 1).  6.0 KB free
  at $E000-$F817 for future use.
- [ ] Move more data under KERNAL: asm error strings (~176B RODATA),
  mnemonic/dasm tables (RODATA, needs startup copy).  Low priority.

### Architecture

- [ ] Relocating startup: see Roadmap R2.
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
  (dasm vs asm_line).  See [project.md § ZP is precious](project.md#1-zp-is-precious--use-the-stack-for-scratch).
### Size Optimization

- [x] ~~Port C to asm: see Roadmap R6.~~ — done: repl.c (Phase 6)
  and editor.c (Phase 7) ported to assembly.  main.c (~244 lines)
  remains as the only C file.

## Roadmap

Long-term milestones in dependency order.

### R1 — Compile-time CPU gating (done)

All CPU-specific code gated with `#ifdef`/`.ifdef`/`.ifndef` instead
of runtime checks.  A 6502 build does not contain 65C02 or 6510
decode paths.  Guards: `.ifdef CMOS_SUPPORT` (65C02 paths),
`.ifndef CPU_6502` (6510 illegal paths), `#ifdef CMOS_SUPPORT` (C).
Files: asm_line.s, dasm.s (15 sites + 3 RODATA tables), repl.c.
See [project.md § principle 4](project.md#4-cpu-specific-code-must-be-compile-time-gated).

### R2 — Relocating startup

Move CSE code to $8000+, freeing $0800–$7FFF as contiguous user
workspace.  Startup shim at $0801 copies code to final location.
Prerequisite for universal binary and cartridge ROM.

### R3 — Universal C64/C128 binary

Single PRG runs on both machines.  Identical code layout at $8000+
— no runtime address patching.  Machine differences isolated to
three leaf functions that branch on a detection flag.

1. **Machine detection** (~10 B): check $D030 or MMU register.
2. **Banking abstraction** (~30 B): `kernal_bank_out/in` branches
   on machine flag — `$01` on C64, `$FF00` MMU on C128.
3. **NMI trampoline relocation**: $FF00 is MMU on C128 (not RAM).
   Trampoline needs a different address or uses MMU common-RAM.
4. **KERNAL RAM access** ($E000+): C128 uses MMU bank switch
   instead of $01 bit manipulation.  Same accessor functions,
   different banking inside.
5. **2 MHz mode** (~5 B): enable 8502 fast mode during assembly
   and memory search (VIC blanked during banking anyway).
6. **C128 keyboard**: map ESC, TAB, HELP, numeric keypad.

Same 40-column VIC-II screen on both machines.  No VDC code
shipped to C64.  Zero RAM overhead on C64.

### R4 — 80-column VDC mode (C128 only)

Self-contained VDC display driver: same interface as VIC-II
routines (`io_putc`, `io_puts`, `newline`, `scroll_up`,
`clear_eol`), writing through VDC register port ($D600/$D601).

The universal PRG (R3) carries both drivers.  The relocating
startup (R2) copies the VDC driver into the final memory layout
only on C128 detection.  C64 users pay zero RAM cost.  Startup
offers 40/80 choice on C128.

Wider line formats: 16-byte `m` dump, longer disassembly lines,
wider editor (80×22 visible source).  Low priority.

### R5 — Cartridge ROM (CRT)

Dual linker configs: `c64_cse.cfg` (PRG) and `c64_cse_crt.cfg`
(CRT).  Instant boot, no load time.  Requires R2 (relocating
startup) since cartridge ROM is at $8000.  EasyFlash bank
switching for >16KB.

### R6 — Port C to asm (done)

`repl.c` (Phase 6) and `editor.c` (Phase 7) ported to assembly.
Eliminated cc65 runtime overhead and two known cc65 -O bugs.
Binary size: 6510=21811B (was 28345 pre-R6, 24091 post-Phase 6).
Total savings: 6534B (23%).  `main.c` (~244 lines) remains.

## Ideas

Exploratory, not yet scoped.

- [ ] PRG load: auto-detect load address from PRG header, show in output.
- [ ] `$` command: filter directory listing by filename glob.
- [ ] `d` command: show ASCII alongside disassembly (like `m`).
- [ ] `.` command: when no operand given for mnemonic that requires
  one, show help instead of ;?asm.
- [ ] Color command `C`: show color preview swatches.
- [ ] Disk I/O: timeout handling for unresponsive drives.
- [ ] NMI during `j` user code: flag checked only on return.  NMI
  trampoline ($FF00) handles KERNAL banking; separate from `j` issue.
- [ ] REU (RAM Expansion Unit) support for large source files.
- [ ] Universal C64/C128 binary: see Roadmap R3.
- [ ] 80-column VDC mode: see Roadmap R4.
- [ ] Cartridge ROM: see Roadmap R5.
- [ ] Macro support: .macro/.endmacro.
- [ ] Conditional assembly: .if/.else/.endif.
- [ ] Include files: .inc (read and assemble from separate file).
- [ ] Detect PAL/NTSC at startup.
