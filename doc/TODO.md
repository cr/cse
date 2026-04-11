# CSE — TODO

## Bugs

Open bugs, roughly ordered by priority.

- [ ] RUN/STOP debounce: bounces when held.  Primary mode-switch
  key feels broken.
- [ ] `.` (disassembly) shows CSE ZP instead of user ZP after
  j/debugger context.  Companion to the `m` fix in `ac1a31f`.
  `m` redirects reads in $02..$59 through `user_zp_buf` when
  `dbg_reason != 0`, but `.` still reads live memory.  Cheaper
  fix: unconditionally stage 3 bytes from `user_zp_buf` into
  `dbg_zp_view` before calling `dasm_insn` (~15 B code).  Low
  priority — users rarely disassemble at ZP.
- [ ] Debugger: stepping into a subroutine then `c` (continue)
  cannot return through the original JSR's pushed return address.
  The `sp_baseline` RTS trick unwinds the stack, so the
  subroutine's RTS pops the @tramp return instead of the original
  caller.  Fix: 256 B user-stack snapshot at `$EF00` under
  KERNAL (copy page 1 on debug entry/exit).  Acceptable
  trade-off for now.
- [ ] Debugger: `t1` traces over conditional branches (BNE etc.)
  instead of tracing into them.  The BRK-based step logic computes
  both branch target and fall-through, arms BRK at both, but the
  branch is not taken at runtime.  Likely cause: `reg_p` flags not
  correctly captured/restored across BRK, or the BRK at the branch
  target clobbers the instruction before it can execute.  Needs a
  test case: step through a tight DEX/BNE loop and verify PC follows
  the branch.
- [ ] Debugger: stepping `t1` over a JSR to KERNAL ROM ($E000+)
  silently falls back to step-over.  Consider showing a one-line
  note (e.g. `; rom step -> over`).  Low priority.

### Fixed bugs (reference)

<details>
<summary>Click to expand</summary>

- [x] 13 CMOS mnemonic gate bugs — fixed in `2939a94`.
- [x] expr.s test harness: 12 xfails — resolved, 146 tests pass.
- [x] al_cpu 3-valued semantics — fixed.
- [x] `j` command: reset colors after user code returns.
- [x] `print_load_split_warning` leading-comma bug.
- [x] `ed_scroll_down` memmove broken — rewrote as row-by-row copies.
- [x] Revise TDD framework — Principle 6 + Anti-patterns section.
- [x] 8 xfailed `TestStepIntoJSR_ROMFallback` — ported to
  `test_step_rom.py` using C64Emu.  0 xfails remain.
- [x] Clean up `dev/test.d64`.
- [x] Review all user-facing strings — terse convention established.
- [x] Line-break warnings on file load — one per split.
- [x] `theme_border`/`theme_bg`/`theme_fg` in RODATA — moved to BSS.
- [x] `.` and `m` show CSE ZP — partially done (`m` fixed, `.` open above).
- [x] Stack-snapshot revisit under KERNAL — resolved.
- [x] BASIC SYS residue on hardware stack — SP reset at startup.
- [x] `dbg_enter` ZP save buffer sizing — fixed.
- [x] cc65 -O ternary miscompilation — eliminated (pure asm).
- [x] cc65 -O zero-extension bug — eliminated (pure asm).
- [x] User CHROUT overwrites prompt row — newline before run_user.
- [x] asm_src test stub blank line truncation — $FF EOF sentinel.
- [x] `dev/test.d64` T-COUNT: renamed from COUNTDOWN, loads and
  displays correctly after page-alignment fix.

</details>

## Phase 9 — Test harness rewrite

`C64Emu` emulator class + production PRG replaces per-test build
systems, ASM stubs, and test-specific linker configs.

### Done

- [x] `tests/c64emu.py` — C64Emu class: py65 + KERNAL ROM overlay,
  $01 bank switching, screen RAM, jsr(), sym(), keyboard injection.
- [x] `tests/test_c64emu.py` — 34 smoke tests.
- [x] `tests/test_editor_asm.py` — 10 ASM-level editor tests
  (gap buffer, ed_new, dirty flag, ed_read_line).
- [x] `tests/test_screen_asm.py` — 15 ASM-level screen tests
  (scroll_up, newline, restore_colors, reset_screen, cursor toggle).
- [x] `tests/test_step_rom.py` — 8 debugger step-into ROM tests
  (replaced xfailed tests).
- [x] Makefile: `-Ln` label file, `check-roms` gate, `cse_prg` fixture.
- [x] KERNAL ROM setup: screen line link table ($D9-$F1), HIBASE,
  page-3 vectors via RESTOR.
- [x] `c64emu.py` load/run segment relocation: auto-copies segments
  with load ≠ run addresses (mirrors loader.s).

### Open

- [ ] Migrate remaining test files to C64Emu + full PRG.  Each old
  test file (test_repl, test_cse_io, test_expr, test_symtab,
  test_debugger, test_au_mode, test_mnhash, test_asm_line,
  test_dasm, test_asm_src) has its own build system, map parser,
  and run loop.  Migration removes ~1200 lines of harness code,
  9 ASM stub files, and 3 linker configs.
- [ ] Editor scroll/render screen-RAM tests.  `ed_scroll_down` and
  `ed_render_line` are `.proc`-scoped (not in .lbl); test path is
  through `ed_handle_key` with cursor keys, which needs full editor
  state.  Deferred until `enter_editor` can be called via C64Emu.
- [ ] Retire `test_editor.py` mirror tests once ASM-level coverage
  is complete.
- [ ] README cross-reference tests: parse command tables in
  `README.md`, verify each command key has a handler symbol in the
  `.lbl` file.  See DDD Maintenance item 8.

## Planned

Defined scope, needs work.

### REPL

- [ ] `.` without args: behave like `d` (disassemble one instruction).
- [ ] `/` command: search for byte pattern in memory.
- [ ] `f` command: fill memory range with byte.
- [ ] `>` command: transfer/copy memory block.
- [ ] `=` command: define/query symbols from REPL.
- [ ] `r` command: uppercase set flags (`NV-BDIZC` vs `nv-bdizc`).
- [ ] `r` command: accept expressions for register values
  (`r a:cols-1`).  Currently plain hex only (`r a:FF`).
- [ ] `m` address argument: accept expression (`m screen+40`).
  Currently plain 4-digit hex only.
- [ ] Disk command channel: unified under `$` (`$ s:file`, `$9`, etc.).
- [ ] Floppy status consistency: `$` prints status inline (always
  shows), `l`/`s` use `floppy_status` via `disk_done`.  Verify
  both paths produce identical output on stock KERNAL.
- [ ] `e` command: open editor at decimal line number (`e 42`).
  Centers the target line on screen as much as possible.  Ties
  into assembler error line numbers — assemble, see error at
  line 42, type `e 42` to jump straight there.

### Help

- [ ] In-app help system.  Help text lives in KDATA (under
  KERNAL ROM, $F100 area), not RODATA — must not bloat the
  relocatable runtime.  Minimal CODE overhead: a small dispatcher
  that pages through KDATA strings.  Candidates: one-screen
  REPL command cheat sheet, editor key summary, assembler
  syntax quick ref.  Paging output (see below) would pair
  naturally.

### Output

- [ ] Paging for commands that produce more than ~23 lines of
  output (`d`, `m`, `$`, assembler messages).  Pause with
  "more" prompt, any key continues, RUN/STOP aborts.  The
  `out_log` output wrappers already funnel all command output
  through a single path — hooking a line counter there should
  be straightforward.

### Assembler

- [ ] `.bas` directive: emit a BASIC SYS stub that calls `main`.
  Optional string argument becomes a REM comment on the same line
  (`.bas "MY PROGRAM"` → `10 SYS 49152 REM MY PROGRAM`).  Makes
  assembled PRGs auto-runnable via `RUN` after `LOAD "FILE",8,1`.
- [ ] Assembler error display: show source line number + context.
- [ ] Per-segment assembly summary (one line per `.org` block).

### Editor

- [ ] Handle files > gap buffer capacity (show error, don't crash).
- [ ] Gap buffer compaction: `buf_base` only grows down (via
  `gb_ensure_room`), never shrinks.  `ed_init`/`n` should reset
  `buf_base` to BUF_END.  Line deletion could trigger compaction
  but consider the trade-off (O(n) vs immediate undo).
- [ ] Page up/down with shift+cursor or F-keys.
- [ ] Search (ctrl+f equivalent via F-key).
- [ ] Goto line number.
- [ ] Consider switching tab representation from `$A0` to `$09`.

### Architecture

- [x] Relocating startup: done (Roadmap R2, Session 10).
- [ ] Replace au_mode hex parser with expr_eval (option C):
  remove `_insn_buf` round-trip, switch line assembler from VICII
  to PETSCII encoding.  Saves ~400 B code + 80 B BSS.  Phase-level
  work — see scope note below.
- [ ] BSS optimization: overlap `_load_line`/`_load_vcol` with
  `ws_buf` (saves 3 B).
- [ ] BSS optimization: collapse `disk_seq_bytes`/`disk_seq_lines`
  with `ed_save_bytes`/`ed_save_lines` (saves 4 B).
- [ ] BSS optimization: overlap `rp_next_lo`/`rp_next_hi` with
  `rp_hexbuf` + `@new_col` (saves 3-4 B).
- [ ] Global release version: single `VERSION` definition (currently
  Makefile `VERSION ?= 0.1`) that flows to D64 disk name, PRG
  filenames, splash screen string, and documentation.  Current
  version: v0.1a.  The D64 disk label, `$` listing, and any
  release artifacts must show the version.

## Roadmap

Long-term milestones in dependency order.

### R1 — Compile-time CPU gating (done)

All CPU-specific code gated with `.ifdef`/`.ifndef` instead of
runtime checks.

### R2 — Relocating startup (done)

CSE runtime relocated to high memory (floating start, page-aligned,
ending at $CFFF).  Discardable loader at $080D copies CODE+RODATA
at boot.  Two-pass link auto-computes runtime start address.
Workspace at $0800, ~30 KB free.  Exomizer SFX compression for
D64 distribution (~38% smaller).

### R3 — Universal C64/C128 binary

Single PRG runs on both machines.  Machine differences isolated to
three leaf functions (banking, NMI trampoline, keyboard).

### R4 — 80-column VDC mode (C128 only)

Self-contained VDC display driver, same interface as VIC-II routines.

### R5 — Cartridge ROM (CRT)

Build target for at least one CRT layout.  Candidates: Ocean Type 1
(simple banked ROM, wide emulator support) or EasyFlash (2×64 banks,
writable, real-hardware friendly).  Dual linker configs — one for
PRG, one for CRT.  Instant boot, no loader needed.  R2 (relocating
startup) provides the foundation: CODE+RODATA already position-
independent relative to their link address.

### R6 — Port C to asm (done)

All C ported to assembly.  cc65 C compiler eliminated.

### R7 — MEGA65 native support (stretch goal)

Native MEGA65 platform target, separate from C64-compatible mode.
The MEGA65 is a much more capable machine (32-bit address space,
relocated ZP internals in native mode, VIC-IV) requiring bigger
adaptations than a compatibility shim.  Alongside C128 native
(R3/R4), this would be a distinct platform target with its own
screen driver and memory model.  Far-future — depends on R3.

## Ideas

Exploratory, not yet scoped.

### Keyboard & input

- [ ] KERNAL keyboard CTRL combos: explore what key combinations
  the default KERNAL keyboard I/O delivers.  CTRL+key produces
  PETSCII control codes ($01–$1F) — identify which are usable
  without conflicting with KERNAL screen editor behaviour.
- [ ] SHIFT+CLR/HOME in REPL: clear screen.  C=+CLR/HOME: clear
  from cursor to end of screen.  Both use KERNAL screen editor
  codes (SHIFT+CLR = $93, CLR/HOME = $13).
- [ ] F-key bindings: assign useful functions to F1–F8 in both
  REPL and editor.  REPL candidates: help, repeat last command,
  toggle hex/dec, disassemble at PC.  Editor candidates: save,
  assemble, goto line, search.
- [ ] Revise RUN/STOP+RESTORE and NMI handling.  Nothing must
  ever crash out of CSE — even a CSE crash should land in the
  REPL.  RUN/STOP+RESTORE triggers NMI which currently toggles
  REPL/editor; could double as a cheap "reset screen state"
  function without needing a dedicated command.  Investigate
  making the NMI handler unconditionally safe (re-entrant stack
  cleanup, screen state restore).

### Features

- [ ] PRG load: auto-detect load address from PRG header.
- [ ] `$` command: filter directory listing by filename glob.
- [ ] `d` command: show ASCII alongside disassembly (like `m`).
- [ ] `.` command: show help when mnemonic given without operand.
- [ ] Color command `C`: show color preview swatches.
- [ ] Disk I/O: timeout handling for unresponsive drives.
- [ ] NMI during `j` user code: flag checked only on return.
- [ ] REU support for large source files.
- [ ] Macro support: .macro/.endmacro.
- [ ] Conditional assembly: .if/.else/.endif.
- [ ] Include files: .inc.
- [ ] Detect PAL/NTSC at startup.
- [ ] MEGA65 Open-KERNAL compatibility (C64-compatible mode):
  `$` works (LOAD-based).  Floppy status empty (shows `; `)
  — blocked on upstream IEC channel-I/O fixes
  (MEGA65/open-roms#116, #117).  Channel-based dir code
  preserved in `1348247` for when fixes land.  All other
  features work.  Native mode is roadmap R7.
- [ ] DDD back-reference tracking: link source files to their
  documentation via a machine-readable index.  DDD Maintenance
  verifies code changes trigger doc updates for all covering
  documents.
