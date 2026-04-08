# CSE — TODO

## Top 10 — stabilization phase (current round)

The current focus is consolidation, simplification, bugfixes,
optimization, and cleanup — *not* new features.  Ordered
roughly by do-first.

1. **Mark stale TODO entries done** — `k` command, `parse_hex.s`
   parenthetical, this stale Top 10 stub.  Hygiene, 15 min.
2. **Warn on quit/switch if dirty flag set** — see
   [Editor](#editor).
3. **Handle files > gap buffer capacity** — see
   [Editor](#editor).
4. **Line-break warnings: sort + dedupe + "…and N more"
   summary** — see [Bugs](#bugs).
5. **Clean up `dev/test.d64`** — remove/fix test programs
   with lines > 39 cols.  See [Bugs](#bugs).
6. **RUN/STOP debounce** — see [Bugs](#bugs).
7. **ZP optimization: overlap scratch** — see
   [Architecture](#architecture).
8. **Audible reject blip** — see [Next](#next).
9. **Revise TDD framework** — deter Python-mirror tests; see
   [Bugs](#bugs).
10. **DDD audit of 7 module docs** — asm_line, au_mode,
    opcode_lookup, mn_classify, mn7, main, meminfo.  See
    [Next](#next).

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
- [x] ~~`ed_scroll_down` memmove broken: scrolling up in the editor
  only updated row 0~~ — fixed: rewrote `ed_scroll_up` /
  `ed_scroll_down` as row-by-row copies using the `scr_lo/scr_hi`
  tables (21 rows × 40 bytes).  The old code had both pointer-dec
  and Y-inc per iter, cancelling out so every byte read/write
  landed on the same address.  Cleanly also saved 45 B and made
  the procs symmetric.  Shipped with the original Phase 7 hand-
  port (`915e84c`) — the commit message comments ("let me do this
  differently", "But Y-indexed indirect doesn't work well going
  down...") betray the author mid-rework.
- [ ] Editor ASM-level regression tests via py65.  `test_editor.py`
  is a pure-Python gap-buffer mirror with no screen-RAM model —
  that's how the broken `ed_scroll_down` memmove slipped through
  for months.  The new `TestScrollMemmove` tests mirror the
  scroll byte-movement contract in Python, but a true ASM-level
  test would need a py65 test binary that links `editor.s` and
  runs `ed_scroll_up` / `ed_scroll_down` against a real
  `$0400`-backed memory region.  Pattern to follow:
  `tests/test_repl.py` already runs compiled REPL code through
  py65 via the `dev/repl_test_stub.s` scaffolding.  An
  `editor_test_stub.s` + `dev/editor_test.cfg` + `test_editor_asm.py`
  would close the gap.  Scope creep warning: the stub has to
  fake `disk_load_seq`, KERNAL PLOT, the render tables, and a
  bunch of other pieces — budget accordingly.
- [x] ~~Revise the TDD framework~~ — done: `doc/testing.md` now
  has Principle 6 ("Test the actual ASM, not a Python copy of
  it") and an Anti-patterns section that calls out mirror tests
  by name.  `test_editor.py::TestRendering` and `TestScrollMemmove`
  carry warning docstrings flagging them as the cautionary
  examples.  No new mirror tests should be added; existing ones
  retire when the py65 editor test binary lands.
- [ ] Clean up `dev/test.d64` — it contains test programs with
  lines that exceed the 39-col hard cap (they predate the cap
  feature).  Load each file in CSE, check for split-line warnings
  from the load path, hand-fix any files that still carry overly
  long lines so the canonical sample-set is clean.
- [x] ~~Review all user-facing strings~~ — done 2026-04-08.
  Codified the convention as a comment block in `repl.s`
  above the `str_*` table:
  ```
  "; ..."        normal status / info  (space after ';')
  "; ! ..."      warning
  ";?tag"        terse error tag, BASIC-style  (no space)
  ";?word ..."   long error explanation
  "; ...? y/n "  yes/no confirmation prompt
  ```
  Always lowercase, single space after `;` for status lines.
  `;?` is the one exception, reserved for error tags so the
  user can scan for `?` at col 1 to find trouble.  Eight
  strings rewritten to match (mostly missing the space after
  `;`).  Doubled-message bug found and fixed: `floppy_status`
  was emitting `00, ok,00,00` from the drive's error channel
  on every successful disk operation.  Now suppresses the
  print when fl_buf starts with "00".  +16 B total.
- [ ] Line-break warnings on file load are incomplete, redundant,
  and out of order.  `print_load_split_warning` (repl.s) prints
  line numbers recorded during `ed_load_source`, but the current
  ordering/dedup logic doesn't match the user's mental model:
  lines are reported in the order they were split, not sorted;
  the same affected line can appear multiple times if more than
  one forced CR falls inside it; and the `SPLIT_LINES_MAX = 8`
  cap silently drops later splits without a summary "…and N
  more".  Audit the recording path in editor.s::load_insert
  (`ed_load_split_lines` fill) and the print path in repl.s
  together.  Fix: sort + dedupe at record time, report
  `"N lines split, showing first 8: …"` when truncated.
- [ ] RUN/STOP debounce: bounces when held.
- [x] ~~`theme_border` / `theme_bg` / `theme_fg` in RODATA but
  written at runtime by the `c BFS` REPL command — would silently
  no-op on the CRT target.~~  Fixed: moved to BSS with a new
  `theme_init` proc called at startup that copies the build-time
  `THEME_BOR`/`THEME_BG`/`THEME_FG` defaults into the BSS slots.
  Costs +16 B on PRG but unblocks the CRT target.
- [ ] `.` (disassembly) shows CSE ZP instead of user ZP after
  j/debugger context.  Companion to the `m` fix landed in
  commit `ac1a31f` (see item below).  `m` now redirects
  reads in $02..$59 through `user_zp_buf` when `dbg_reason
  != 0`, but `.` still reads live memory.  Harder because
  the read is inside `dasm.s` using its own `_dasm_ptr` —
  the redirect point is not the REPL's `emit_dot` but deep
  in the operand-byte fetch path.  Two possible fixes:

    1. Stage 3 bytes (max instruction length) into
       `dbg_zp_view` before calling `dasm_insn`, and point
       `_dasm_ptr` at the view.  Mirror of what `emit_mem`
       already does.  Localized change, keeps `dasm.s` clean,
       but touches 4 read sites in `dasm.s` that use
       `(_dasm_ptr),y` with `y = 1..2`.  Actually the view
       can just be 3 B so all three operand bytes are
       contiguous starting at offset 0 — `emit_dot` already
       knows the instruction length up front from `dasm_insn`'s
       return value, but `_dasm_ptr` needs staging BEFORE
       that call.  Needs a length pre-fetch (read just the
       opcode byte first, look up its length in `oplen_tbl`,
       then stage that many bytes) or just unconditionally
       stage 3.

    2. Export a `dasm_read_byte` hook from `dasm.s` that all
       operand-byte reads go through, and override it in
       `repl.s::emit_dot`.  Cleaner layering but bigger
       surface: every `(_dasm_ptr),y` in `dasm.s` becomes a
       JSR.  Worth maybe +30 B of code and some extra cycles
       per instruction.

  Option 1 is the cheaper fix, ~15 B of code reusing the
  existing `dbg_zp_view` + a small pre-stage loop in
  `emit_dot`.  Low priority: users rarely disassemble at ZP
  (it's a data inspection use case, already covered by `m`),
  but someone will hit it eventually and be confused.
- [x] ~~`.` and `m` show CSE ZP instead of user ZP after j/debugger
  context~~ — **partially done** 2026-04-08 (`m` only, `.` is
  split out as a separate open TODO above):
  * New 88 B BSS buffer `user_zp_buf` in `asm_bridge.s`, holds
    the user's ZP $02..$59 snapshot.  Captured by
    `snap_user_zp` at the very top of `dbg_brk_handler` /
    `dbg_nmi_break` (before any CSE code touches ZP) and on
    the clean-RTS path in `dbg_enter` step 6 alongside the
    register capture.
  * `emit_mem` now checks `dbg_reason` and stages up to 8
    bytes into a new 8 B BSS view (`dbg_zp_view`) — for each
    byte in the dump row, addresses in $02..$59 read from
    `user_zp_buf`, others read from live memory.  Then
    `rp_ptr2` is re-pointed at the staged view and
    `emit_hex_cols` + the ASCII column both see the user's
    ZP values.
  * `.` (cmd_dot disassembly) was **intentionally left out**.
    It would require redirecting `dasm.s`'s own `_dasm_ptr`
    reads, which is a deeper change.  Users rarely disassemble
    at ZP addresses (it's a data inspection use case, covered
    by `m`).  Open follow-up if someone actually needs it.
  * Addresses $00-$01 still read live (the CPU I/O port —
    snapshotting them doesn't make sense).  $5A+ reads live
    too because CSE doesn't touch that range, so user values
    survive across the debug boundary without a snapshot.
  * Cost: 96 B BSS (88 + 8) + ~130 B code.
- [ ] Debugger: stepping into a subroutine then `c` (continue) cannot
  return through the original JSR's pushed return address.  The
  `sp_baseline` RTS trick (commit `c753fc8`) unwinds the stack to
  the point where `@tramp` called into user code, so any bytes
  user code pushed (including JSR return addresses) are abandoned
  on debug return.  Interactive single-stepping is fine, but
  `c`-from-inside-a-stepped-subroutine ends the run early because
  the subroutine's RTS pops the @tramp return instead of the
  original caller.  Acceptable trade-off for now — the user can
  work around it by setting a breakpoint on the caller and using
  `c` from the outer scope.  If we ever revisit this, the fix is
  a 256-byte user-stack snapshot at `$EF00` under KERNAL:
  copy page 1 → $EF00 on debug entry, copy $EF00 → page 1 on
  debug exit.  CSE's own stack is only 8 bytes deep at user-code
  entry (see `memory_design.md` § Stack budget), so we do *not*
  need a second CSE-side snapshot.  Would also fix the NMI-deep-
  stack failure mode.
- [ ] Debugger: stepping `t1` over a JSR to KERNAL ROM ($E000+) now
  silently falls back to step-over (commit `3cc5e42`).  This is the
  right behaviour, but consider showing a one-line note (e.g. `;
  rom step → over`) so the user understands why the next prompt is
  past the JSR instead of inside it.  Low priority — probably file
  under "ideas".
- [x] ~~Stack-snapshot revisit under KERNAL.~~  Resolved
  2026-04-08:
  * `sp_baseline` is the right call for single-step.  The `c`-from-
    subroutine failure mode is captured in the BRK TODO above with
    the concrete 256 B `$EF00` snapshot fix described in-place.
  * Verified CSE's own call depth at `jmp (brk_pc)`: **8 bytes**
    (four nested `jsr` frames — exec_line → cmd_step → run_user →
    dbg_enter → @tramp).  Plus ~2-4 B of BASIC SYS residue until
    startup resets SP (see below).
  * User code therefore gets **≥ 230 bytes** of the 256-byte
    hardware stack, which is ample for any realistic C64 program.
  * The full 512 B reservation at `$EF00–$F0FF` is not needed:
    - `$EF00–$EFFF` (256 B) stays earmarked for the future user-
      stack snapshot described in the BRK TODO.  Not allocated
      until that TODO is implemented.
    - `$F000–$F0FF` (256 B) is now **unreserved free space** —
      available for any future feature that needs a page-aligned
      256-byte region under KERNAL.
  * Documented in `memory_design.md` § Stack budget.  Stale
    "stack snapshot" labels purged from all module docs.
- [x] ~~BASIC SYS residue on the hardware stack~~ — fixed:
  `main.s::startup` now does `ldx #$FF / txs` as its first
  instruction, resetting SP to `$01FF` before any CSE code runs.
  This wipes the ~2-4 B BASIC SYS left behind.  Safe because
  CSE never returns to BASIC (the main loop is `jmp @loop` and
  `@exit` halts).  The BRK/NMI `sp_baseline` path still works —
  it captures its own baseline at `@tramp` entry, independent
  of the startup SP.  User code therefore always sees a clean
  `sp = $01F6` (or deeper once dbg_enter frames are pushed),
  regardless of how BASIC was launched.
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

- [x] ~~DDD audit module docs against code: asm_line, au_mode,
  opcode_lookup, mn_classify, mn7, main, meminfo.~~  Done
  2026-04-08:
  * `main.md`: rewritten Design section with the actual startup
    sequence (SP reset → BSS zero → KDATA copy → _main); fixed
    the RUN/STOP description (it's an inline main-loop key, not
    NMI; NMI is RUN/STOP+RESTORE); REPL key table now lists
    refusal cases for the audible blip.
  * `meminfo.md`: dropped stale `_cse_*` underscores; added
    Memory section + caller list.
  * `mn_classify.md`: clean — covers mn7.s + mn6.s + mn_vars.s
    correctly, no stale entries.  (mn7.s does not need its own
    doc — mn_classify.md is the umbrella.)
  * `opcode_lookup.md`: dropped stale `_al_validate_mode`
    underscore.
  * `au_mode.md`: clean — exports + ZP + mode table all match.
  * `asm_line.md`: removed stale `_jsr_addr` reference and
    `_jsr_vec` ZP byte (both deleted in last round); BSS table
    now reflects actual export names (no underscores) and
    correct sizes (88 B `zp_save_buf`, 96 B total).
- [x] ~~Audit "don't get in the KERNAL's way"~~ — done
  2026-04-08.  Walked every KERNAL variable / vector CSE
  touches and verified the user-code contract:
  * **`$CC`** — CSE sets to 1 at startup.  User code that sets
    it to 0 (e.g. for cursor blink during a CHRIN) would leave
    the KERNAL IRQ blinking a cursor on top of CSE's screen
    output after return.  **Fixed:** `run_user` now restores
    `$CC = 1` after `dbg_enter` returns.  $CC is treated as a
    CSE-domain byte; user code may write it but CSE owns the
    post-return state.
  * **`$0277+` / `$C6` (keyboard buffer)** — user keystrokes
    typed while issuing the `j`/`g`/`t`/`o` command would
    otherwise leak into user code's first `GETIN`/`CHRIN`.
    **Fixed:** `run_user` now zeroes `$C6` before
    `jsr dbg_enter`, draining any queued bytes.
  * **`$D1/$D2`, `$F3/$F4` (line pointers), `$D3/$D6`
    (cursor)** — already correct.  `cmd_jmp` and `cmd_step`
    both call `newline` before `run_user`, and `newline`
    invokes `io_sync` (KERNAL `PLOT`) which updates the line
    pointers from the current row.  Nothing to do.
  * **`$0314` (IRQ)** — never touched by CSE.  Stays at the
    stock KERNAL IRQ (`$EA31`).  ✓
  * **`$0316` (BRK)** — patched and restored by `dbg_enter`
    around the `@tramp` call.  Stock KERNAL BRK is exposed
    to user code only outside the patched window, which is
    fine (user code that BRKs *during* a CSE debug session
    is the whole point of the debugger).  ✓
  * **`$0318` (NMI)** — points permanently at the trampoline
    at `$FF00`, which routes NMI to the stock KERNAL `$FE43`
    when CSE is not running user code (`dbg_running` clear)
    and to `dbg_nmi_break` otherwise.  ✓
  * **Hardware stack** — `startup` resets SP to `$FF`.  User
    code sees ≥ 239 B free.  Clean RTS through `@tramp` works.
    `c`-from-stepped-subroutine remains the documented limit
    (covered by the BRK TODO with the $EF00 snapshot fix).  ✓
  * **`$D018` (charset mode)** — already restored to lowercase
    by `run_user` after `dbg_enter` returns.  ✓
  * **`$0286` (CHRCOLOR)** — fixed in commit 3948e4a (separate
    bug report).  `restore_colors` now writes `theme_fg` to
    `$0286` so KERNAL CHROUT paints in the configured theme
    colour from the very first character of user output.  ✓
  Net code change: +8 B in `run_user` (zero `$C6`, restore
  `$CC`).  All 2729 tests pass.
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
- [x] ~~`k` command: implement.  Confirms before clearing.~~
  Done: `@h_k` in repl.s calls `check_unsaved`, prompts
  `;delete source. are you sure? y/n`, and invokes `ed_new`.
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
- [x] ~~Warn on quit/switch if dirty flag set.~~  Verified
  2026-04-08: all destructive paths already guard.  `cmd_quit`
  (`q`), `cmd_load` (`l`, on the SEQ branch), and `@h_k`
  (delete source) all call `check_unsaved` which prompts
  `;unsaved. y/n?` and aborts on no.  RUN/STOP switch
  REPL↔editor is non-destructive (the buffer survives), so no
  prompt is needed there.  TODO entry was a leftover from
  before those guards were added.
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
- [ ] Replace au_mode hex parser with expr_eval (option C):
  remove the `_insn_buf` round-trip from asm_src.s and switch
  the line assembler from VICII to PETSCII encoding.  Saves
  ~400 bytes code + 80 bytes BSS.  Requires mn_classify char
  conversion and expr error code mapping.  Touches ~4 files.
  (Note: `parse_hex.s` was an earlier orphan already deleted.)

  **Scope note (2026-04-08):** looked at this during a
  stabilization round and deferred.  This is phase-level
  work, not stabilization-sized.  Full blast radius:

    * `asm_src.s` — rewrite ~12 `_insn_buf` insertion sites
      (mnemonic copy, operand emit for each addressing mode)
      to either emit elsewhere or parse source directly.
    * `au_mode.s` — replace every `SC_*` VICII constant with
      the PETSCII equivalent; rewrite the hex-digit detection
      ladder; change `_au_rd_nib` / `_au_rd_byte` / `_au_is_hex`.
    * `mn_classify.s` — add a PETSCII→VICII conversion at the
      entry, since the hash table is VICII-indexed.
    * `asm_line.s` — calling convention comment + any
      encoding assertions.
    * `test_au_mode.py`, `test_asm_line.py`, `test_asm_src.py`
      — rewrite the `sc()` encoder functions and every test
      case that hard-codes VICII bytes.
    * `conftest.py` scaffolding as needed.

  It's a full day of careful migration with the assembler
  test suite re-verified at each step.  The 400 B win is
  real but the risk/reward is wrong for a stabilization
  round — this belongs in its own dedicated phase.
- [x] ~~Redesign function interfaces~~ — done: all calls use
  ZP/register args.  Parameter stack (pushax/cse_popax/sp) eliminated.
- [x] ~~ZP optimization: overlap scratch for non-concurrent
  modules.~~  Investigated 2026-04-08: both candidate overlaps
  blocked by cross-module calls.  asm_src calls `ed_read_line`
  (uses editor ZP), and `cmd_dot` runs `dasm_insn` and
  `asm_line` inside the same command (both touch the proposed
  shared ZP).  See `memory_design.md` § ZP overlap.  No
  code change.
- [ ] BSS optimization: overlap `_load_line` (2 B) + `_load_vcol`
  (1 B) with `ws_buf` (39 B).  `_load_*` live only during
  `editor.s::ed_load_source` → `load_insert`, while `ws_buf` is
  only touched inside the `CH_ENTER` auto-indent handler.  The
  two code paths are mutually exclusive (the load completes
  before the user can press a key), so the three bytes can be
  aliased to the first three bytes of `ws_buf`.  Saves 3 B BSS.
  Needs a comment at both declaration sites so nobody reuses
  `ws_buf` during a load.
- [ ] BSS optimization: collapse `disk_seq_bytes` / `disk_seq_lines`
  (disk.s, 4 B) and `ed_save_bytes` / `ed_save_lines` (editor.s,
  4 B) into a single shared `last_io_stats` struct.  Both track
  the exact same thing — bytes/lines moved by the last file I/O
  — and the REPL reads one pair *or* the other depending on
  which operation just finished.  The two pairs never live
  simultaneously.  Owning module: disk.s (it writes both loads
  and saves).  Saves 4 B BSS.  Touches load/save emit paths in
  repl.s that print the count.
- [ ] BSS optimization: overlap `rp_next_lo` / `rp_next_hi` (4 B,
  used only by `cmd_step`) with `rp_hexbuf` (3 B, used only by
  `cmd_dot`) and the `@new_col` proc-local (1 B, used only by
  the editor insert path).  All three are scoped to their
  owning command and never run concurrently.  Saves 3-4 B BSS.
  Straightforward once the non-concurrency is asserted in
  comments at each declaration.

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
