# CSE — TODO

## Top 10 — stabilization phase

The current focus is consolidation, simplification, bugfixes,
optimization, and cleanup — *not* new features.  Items 1–4 of
the original Top 10 have been resolved; the remaining list is:

1. **DDD audit module docs against code** — asm_line, au_mode,
   opcode_lookup, mn_classify, mn7, main, meminfo.  See
   [Next](#next).
2. **Warn on quit/switch if dirty flag set** — small UX safety
   net, prevents losing work.  See [Editor](#editor).
3. **Handle files > gap buffer capacity** (show error, don't
   crash) — load-time safety hole.  See [Editor](#editor).
4. **ZP optimization: overlap scratch for non-concurrent
   modules** — ~14 B reclaimable from cold scratch, ~8 B
   overlappable (dasm vs asm_line).  See
   [Architecture](#architecture).
5. **RUN/STOP debounce** — bounces when held; small input-layer
   bug.  See [Bugs](#bugs).
6. **Audible reject blip** — single shared SID-voice-3 ping
   from every input-refusal site (line cap, left-wall backspace,
   refused commands).  See [Next](#next).
7. **Move `theme_*` from RODATA to BSS** — required for the CRT
   target so the `c BFS` runtime command keeps working.  See
   [Bugs](#bugs).

Resolved this round (commit forthcoming):

- ~~Fix `print_load_split_warning` leading-comma bug~~
- ~~Doc cleanup: purge stale C/cc65 cruft~~
- ~~Delete `src/parse_hex.s` orphan~~
- ~~Delete dead `jsr_addr` / `_jsr_vec` / `@trampoline`~~

Anything else in this file is feature work or longer-horizon and
should wait until the stabilization phase wraps up.

## Bugs

- [x] ~~13 CMOS mnemonic gate bugs~~ — fixed in `2939a94`: added
  cat=11 check in asm_line.s CMOS gate.
- [x] ~~expr.s test harness: 12 xfails~~ — resolved, 146 tests pass.
- [x] ~~al_cpu 3-valued semantics~~ — fixed: asm_line.s uses
  `cmp #2`/`bcs`/`bcc`, comments updated, tests use al_cpu=2.
- [x] ~~`j` command: reset colors after user code returns~~ — done:
  `restore_colors()` called in both `cmd_jmp()` paths (direct and debugger).
- [x] ~~`print_load_split_warning` leading-comma bug~~ — fixed: the
  first-iteration guard now reads `lda @idx` / `beq @no_sep` so the
  comma+space is suppressed on iteration 0.
- [ ] RUN/STOP debounce: bounces when held.
- [ ] `theme_border` / `theme_bg` / `theme_fg` are declared in the
  RODATA segment of `screen.s` but written to at runtime by the
  `c BFS` REPL command (`sta theme_*` in repl.s).  This works on
  the PRG target because RODATA lives in RAM, but the eventual
  CRT target (R5) puts RODATA in ROM — the `c` command will
  silently no-op there.  Move the three bytes to BSS, leaving the
  build-time defaults `THEME_BOR`/`THEME_BG`/`THEME_FG` as inits
  copied at startup.
- [ ] `.` and `m` commands show/modify CSE's internal ZP state instead
  of the user's ZP state from `j`/debugger context.  After `j` returns
  (BRK/NMI), CSE restores its own ZP — so `.`/`m` on $00–$7F see CSE
  variables, not what the user's code left there.  Fix: save/restore
  user ZP snapshot on debug return; `.`/`m` should read from that
  snapshot when addressing $00–$7F.
- [ ] Debugger: stepping into a subroutine then `c` (continue) cannot
  return through the original JSR's pushed return address.  The
  sp_baseline rts trick (commit `c753fc8`) abandons user-pushed
  bytes on every BRK return.  For interactive single-stepping this
  is acceptable, but `c`-from-inside-stepped-subroutine ends the
  run early because the subroutine's RTS pops the @tramp return
  instead of the original caller.  Proper fix: snapshot the user's
  stack page contents on BRK and restore them on the next dbg_enter.
- [ ] Debugger: stepping `t1` over a JSR to KERNAL ROM ($E000+) now
  silently falls back to step-over (commit `3cc5e42`).  This is the
  right behaviour, but consider showing a one-line note (e.g. `;
  rom step → over`) so the user understands why the next prompt is
  past the JSR instead of inside it.  Low priority — probably file
  under "ideas".
- [ ] Debugger: NMI break trapped during user code that has pushed
  bytes via JSR/PHA/PHP suffers the same sp_baseline trade-off as
  BRK.  Acceptable for now; see the BRK item above for the proper
  fix.
- [ ] Stack-snapshot revisit under KERNAL.  `debugger.md` used to
  reserve `$EF00–$EFFF` (CSE stack snapshot) + `$F000–$F0FF` (user
  stack snapshot) = 512 B under KERNAL ROM for a planned
  "swap-stacks-on-debug-entry" scheme, but the implementation was
  abandoned when Phase 6 replaced it with the `sp_baseline` trick.
  The space is now labelled "free" in `symtab.s` and
  `memory_design.md`.  Two things to investigate and decide:
    1. **Is the sp_baseline trick still the right call?**  The two
       BRK/NMI TODO items above document its failure modes (user
       pushes via JSR/PHA/PHP between patches get abandoned; `c`
       from inside a stepped subroutine can't return through the
       original caller's pushed address).  A genuine stack-page
       snapshot in the $EF00 region would fix both — page 1 copies
       out on debug entry, page 1 restores on exit.  Measure how
       deep the CSE call chain actually runs during typical debug
       flows (`t1`, `o`, `c`, assembly pass).  Old memory_design
       notes guessed ~30 B; verify.
    2. **Same for the user side.**  For interactive stepping we
       execute one instruction at a time, so deep user chains only
       matter across `c`/`j`.  If the answer to (1) is "snapshot",
       a symmetric user-stack snapshot in the $F000 region makes
       `c`-from-subroutine work even when CSE's own stack usage
       has clobbered the user's pushed bytes.
  Possible outcomes: (a) implement the 512 B snapshot scheme and
  close both debugger TODOs above; (b) confirm sp_baseline is fine
  and reclaim the 512 B for something else (e.g. a larger
  `repl_screen` on 80-column mode, or a breakpoint history ring);
  (c) keep it reserved but document *why* (leaving bytes on the
  table "in case" is the worst option — decide either way).
- [x] ~~Debugger: `dbg_enter` saves CSE ZP $02..$5E into `zp_save_buf`,
  but the buffer in asm_bridge.s is sized for $02..$5A (89 bytes,
  not 93).~~  Fixed: both files now share `ZP_SAVE_HI = $59` (the
  actual end of editor.o's ZP allocation per the linker map).
  Buffer is 88 bytes, save loops cover the same range exactly.
- [x] ~~read_line: cc65 -O ternary miscompilation~~ — eliminated:
  repl.s is pure asm (Phase 6).  (CC65 -O BUG #1)
- [x] ~~cmd_step: cc65 -O uint8_t return zero-extension bug~~ —
  eliminated: repl.s is pure asm (Phase 6).  (CC65 -O BUG #2)
- [x] ~~`g`/`j`/`t`/`o`: user CHROUT output overwrites the typed
  command at col 0 of the prompt row.~~  Fixed: `cmd_jmp` and
  `cmd_step` now `newline + clear_eol` once before `run_user`,
  so user code output starts on a fresh row.  See
  [debugger.md § User code output and the prompt row](modules/debugger.md#user-code-output-and-the-prompt-row).
- [x] ~~asm_src test stub: blank lines in source truncate assembly.~~
  Fixed: the stub now uses `$FF` as an EOF sentinel (cannot appear
  in legitimate assembly source) instead of double-NUL.  Blank
  lines are a lone NUL and work correctly.  Regression tests in
  `test_asm_src.py::MANUAL_TESTS` cover single blanks, multiple
  consecutive blanks, leading blanks, and the full hello-world
  pattern.

## Next

Small, concrete, ready to do now.

- [ ] DDD audit module docs against code: asm_line, au_mode,
  opcode_lookup, mn_classify, mn7, main, meminfo.
- [x] ~~Doc cleanup — remove stale C/cc65 cruft~~ — done:
  `__fastcall__` annotations and "parameter stack" notes purged
  from `cse_io.md`, `disk.md`, `screen.md`; `build_system.md`
  pipeline diagram and ROM-compatibility section rewritten for
  pure-asm; `README.md` describes ca65/ld65 explicitly; stale
  fastcall comments in `disk.s` source itself also fixed.
- [x] ~~Delete `src/parse_hex.s`~~ — done: file removed,
  `tests/conftest.py` and `dev/size_report.py` updated.
- [x] ~~Delete dead `jsr_addr`/`_jsr_vec`/`@trampoline` from
  `asm_bridge.s`~~ — done: ~50 B code + 2 ZP bytes removed; the
  `reg_a..reg_p` BSS bytes are kept (still used by debugger.s
  for register save/restore and repl.s for register display).
- [ ] Audible reject blip: emit a short tone when keyboard input
  is rejected (line cap, backspace into the left wall, refused
  printable/tab, etc.).  Single shared "reject" routine called
  from each refusal site in `editor.s` (and potentially the REPL
  for refused commands).  SID voice 3 with a quick triangle
  envelope is the C64-traditional way; ~30 B of code + a tiny
  shutoff hook so the blip self-cancels.

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

- [x] ~~Compile-time CPU gating~~ — done: asm_line.s, dasm.s, repl.s
  all use `.ifdef CMOS_SUPPORT` / `.ifndef CPU_6502`.
  See Roadmap R1.
- [x] Built-in workspace labels: `workstart` and `workend` are
  pre-defined symbols.  `workstart` = first free page (cse_end
  rounded up).  `workend` = buf_base - 1 (inclusive, updated as gap
  buffer grows).  Available in assembler (`.org workstart`) and
  REPL expressions (`@ workend`, `j workstart`).
- [ ] Assembler error display: show source line number + context.

### Editor

- [x] Intelligent tabbing: gutter model with RETURN auto-indent,
  SPACE/INS indent to tab stop, DEL unindent, cursor gutter skip.
  `TAB_WIDTH` is a build-time constant (default 8); there is no
  runtime `tab_width = 0` disable — the feature is always on.
- [x] ~~Runtime `T` tab-width command~~ — removed.  `TAB_WIDTH` is
  now a build-time constant (see `build_system.md`).  Runtime
  tab-width changes interacted badly with the 39-col hard line cap
  (changing the width could turn previously-valid lines into
  "too long" errors, and required recomputing `ed_cur_col` + full
  re-render).  Baking it in at build time eliminates the whole
  class of edge cases.
- [x] ~~39-col hard line cap enforced~~ — done.  The editor
  guarantees every line ≤ 38 visual cols.  Enforced on:
  printable insert, tab insert, auto-indent, backspace-join
  (forced newline at last safe col), and load from SEQ file
  (forced newline + warning listing affected editor line numbers).
- [ ] Handle files > gap buffer capacity (show error, don't crash).
- [ ] Warn on quit/switch if dirty flag set.
- [ ] Page up/down with shift+cursor or F-keys.
- [ ] Search (ctrl+f equivalent via F-key).
- [ ] Goto line number.
- [ ] Consider switching internal tab representation from `$A0`
  (shifted space / C=+SPACE) to the PETSCII tab character (`$09`).
  Rationale: `$09` is semantically "tab" across platforms, would
  interoperate cleanly with cross-dev tools and with any future
  CSE-aware terminal/editor, and would free `$A0` for its original
  meaning (shifted space, a typeable character).  Caveat: on the
  C64 PETSCII `$09` is "disable CBM+SHIFT case switch", not a
  visual tab — so adopting it means treating it as meta-only and
  relying on the editor (and printing code) to recognise it.
  Requires a status-quo analysis of what other C64 assemblers
  and editors (Turbo Assembler, MasterSeka, Relaunch64, etc.)
  use for an in-source tab byte, to see whether `$09` is already
  a de-facto convention or whether `$A0` is.  Touches `editor.s`
  (key handler, rendering, cursor skip — tab expansion is now
  fixed to `TAB_WIDTH` so the constant is the same, only the
  byte representation changes), `asm_src.s` (au_mode's whitespace
  skip), `disk.s` (SEQ I/O conversion), and the assembler_syntax
  doc.  Low priority — deferred until a cross-dev interop need
  actually arises.

### Memory

- [x] ~~Utilize RAM under KERNAL~~ — sym_table (256 slots, 1536B)
  at $E000, name heap (2304B) at $E600, KDATA tables (1010B) at
  $F100, repl_screen (1000B) at $F4F2, NMI trampoline at $FF00.
  Banking guards (sei/cli + $01 bit 1).  1.6 KB free at $F8DA–$FEFF.
- [x] ~~Move data under KERNAL~~ — done: mnemonic tables (mn7/mn6),
  config tables, dasm tables, mode tables → KDATA segment at $F100
  (1010B).  Copied from PRG load area to KERNAL RAM at startup.
  Assembly and disassembly run with KERNAL banked out.  `kernal_out`
  flag prevents symtab bank_in during assembly passes.

### Architecture

- [ ] Relocating startup: see Roadmap R2.
- [ ] Replace au_mode hex parser with expr_eval (option C): eliminate
  parse_hex.s, remove _insn_buf round-trip from asm_src.s, switch
  line assembler from VICII to PETSCII encoding.  Saves ~400 bytes
  code + 80 bytes BSS.  Requires mn_classify char conversion and
  expr error code mapping.  Touches 5 files.
- [x] ~~Redesign function interfaces~~ — done: all calls use
  ZP/register args.  Parameter stack (pushax/cse_popax/sp) eliminated.
- [ ] ZP optimization: overlap scratch for non-concurrent modules.
  ~14 bytes reclaimable from cold scratch, ~8 bytes overlappable
  (dasm vs asm_line).  See [project.md § ZP is precious](project.md#1-zp-is-precious--use-the-stack-for-scratch).
### Size Optimization

- [x] ~~Port C to asm: see Roadmap R6.~~ — done: repl.c (Phase 6),
  editor.c (Phase 7), and main.c (Phase 8) all ported to assembly.
  Zero C files remain.  cc65 C compiler eliminated from toolchain.
- [x] ~~Segment cleanup~~ — done: DATA segment eliminated (all
  runtime state in BSS), variables moved to owning modules,
  theme colors moved to RODATA.

## Roadmap

Long-term milestones in dependency order.

### R1 — Compile-time CPU gating (done)

All CPU-specific code gated with `.ifdef`/`.ifndef` instead of
runtime checks.  A 6502 build does not contain 65C02 or 6510
decode paths.  Guards: `.ifdef CMOS_SUPPORT` (65C02 paths),
`.ifndef CPU_6502` (6510 illegal paths).
Files: asm_line.s, dasm.s (15 sites + 3 RODATA tables), repl.s.
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

All C ported to assembly: repl.c (Phase 6), editor.c (Phase 7),
main.c (Phase 8).  Zero C files remain.  cc65 C compiler dropped;
toolchain is ca65 + ld65 only.  c64.lib eliminated.
Eliminated cc65 runtime overhead (~559B) and two cc65 -O bugs.
Binary size: 6510=21165B (was 28345 pre-R6).
Total savings: 7180B (25.3%).

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
