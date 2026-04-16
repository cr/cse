# CSE — TODO

## Bugs

Open bugs, roughly ordered by priority.

- [x] ~~Disable C64 SHIFT+C= mode switch on CSE init~~ (fixed: main.s)
- [x] ~~`i` command output shows stale memory map~~ (fixed: repl.s
  tail table now shows sym $E000-$EEFF, cse $EF00-$F8D9 banked,
  rom $F8DA-$FFFF instead of single rom $E000-$FFFF)
- [x] ~~`.const FOO` then `sta FOO` not found~~ (fixed: expr.s label
  scanner now folds $C1-$DA → $41-$5A in-place; shifted uppercase
  letters from the lowercase/uppercase charset are accepted)
- [x] ~~Uppercase REPL commands parsed as lowercase.~~  (fixed:
  `scr_to_pet` now maps screen code $40–$5F → PETSCII $C0–$DF.
  Latent bug from Phase 6 — `read_line`'s screen→PETSCII
  conversion always collapsed uppercase into the lowercase
  range.  Dispatch table entries $C2/$C3/$D1 were unreachable.
  Phase 17)
- [ ] `l` command hang: loading a non-existing file may hang.
  Not yet reproducible.  Suspect: `disk_load_prg` or
  `ed_load_source` not handling KERNAL file-not-found error,
  or floppy status channel read blocking.
- [x] ~~INS in REPL: overwrites char under cursor~~ (fixed: main.s
  INS shift loop had off-by-one — `beq` exited before copying the
  char at cursor position; removed the early exit)
- [x] ~~`?` calculator wrong decimal for >= $2000~~ (fixed: repl.s
  `put_dec5_sp` replaced with `io_putdec` delegation; `utoa_sub`
  rewritten with pha/pla pattern from io_putdec)
- [x] ~~`a` save line writes filename "oup"~~ (fixed: asm_src.s
  seg_print_save now checks for `,s` suffix before poking; if no
  suffix, appends `,p` instead of overwriting last char)
- [x] ~~`l "out,p" $2000` doesn't load to $2000~~ (fixed: disk.s
  SETLFS secondary address was inverted — SA=0 means use X/Y addr,
  SA=1 means use PRG header addr; code had them backwards)
- [x] ~~RUN/STOP debounce~~ (already debounced: `@deb_wait` polls
  $91 until key released, then drains keyboard buffer)
- [ ] `.` and `m` show CSE ZP instead of user ZP after j/debugger
  context.  `m` was partially fixed in `ac1a31f` (redirects $02..$59
  through `user_zp_buf` when `dbg_reason != 0`), but `.` still reads
  live memory.  Both commands need consistent treatment.  Cheaper fix:
  stage bytes from `user_zp_buf` into a view buffer before calling
  `dasm_insn` or `emit_hex_cols` (~15 B code).  Low priority.
- [x] ~~**CRITICAL**: save writes wrong memory region~~ (fixed:
  disk.s had a local `_io_tmp = $FB` shadowing the canonical
  symbol in zp.s at `$2D`.  Commit `278a2f6` changed repl.s's
  `sta $FB` → `sta _io_tmp` which resolved to `$2D`, but
  disk.s still read from `$FB`.  Fix: removed the local
  define; disk.s now imports `_io_tmp` from zp.s.  Phase 17.)
- [ ] One too many newline before floppy status in save command.
  Same issue likely affects load too.  Cursor lands on a blank
  row between the "; Nb AAAA-BBBB" line and the drive status.
- [ ] l/s stores the full filename (with ,p suffix) as project
  name, so repeated saves accumulate ",p,p,p..." in cur_filename.
  Should store the stripped project name; derive filenames on
  demand with the appropriate CBM DOS suffix.
- [ ] `r` command flags decode: the dash in the flag string (e.g.
  the `-` between `b` and `D` in `nv-bdizc`) becomes an uppercased
  strange char on screen.  Screen RAM has no dash equivalent at
  the uppercase position.  Replace with a neutral placeholder that
  survives the case-flip (e.g. `.` or keep lowercase always).
- [ ] Debugger: stepping into a subroutine then `c` (continue)
  cannot return through the original JSR's pushed return address.
  The `sp_baseline` RTS trick unwinds the stack, so the
  subroutine's RTS pops the @tramp return instead of the original
  caller.  Fix: 256 B user-stack snapshot at `$EF00` under
  KERNAL (copy page 1 on debug entry/exit).  Acceptable
  trade-off for now.
- [x] ~~Assembler: `bne <nonexisting>` reports "bad insn"~~ (fixed:
  `asm_expr_error` entry point sets `asm_expr_err=1`; `.` command
  and source assembler now print `expr_error_str` detail e.g. "undef")
- [ ] Debugger: stepping `t1` over a JSR to KERNAL ROM ($E000+)
  silently falls back to step-over.  Consider showing a one-line
  note (e.g. `; rom step -> over`).  Low priority.
- [ ] Debugger: refuse to write breakpoints outside workspace memory
  (`$0800`–`__CODE_RUN__`).  Writing BRK to KERNAL, I/O, or CSE
  code corrupts the system.  `bp_set` and `bp_patch` must range-check.

### Fixed bugs (reference)

<details>
<summary>Click to expand</summary>

- [x] `s` command PRG save address stale ZP ref — repl.s wrote to
  hardcoded `$FB/$FC` instead of `_io_tmp`; stale from Phase 12.
- [x] Editor INS key ignored — inserts space via `gb_insert` +
  `gb_cursor_left`; refused at 39-col cap.
- [x] 13 CMOS mnemonic gate bugs — fixed in `2939a94`.
- [x] expr.s test harness: 12 xfails — resolved, 146 tests pass.
- [x] asm_cpu 3-valued semantics — fixed.
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
- [ ] `.` and `m` show CSE ZP — `m` fixed in `ac1a31f`, `.` still open (see above).
- [x] Stack-snapshot revisit under KERNAL — resolved.
- [x] BASIC SYS residue on hardware stack — SP reset at startup.
- [x] `dbg_enter` ZP save buffer sizing — fixed.
- [x] cc65 -O ternary miscompilation — eliminated (pure asm).
- [x] cc65 -O zero-extension bug — eliminated (pure asm).
- [x] User CHROUT overwrites prompt row — newline before run_user.
- [x] asm_src test stub blank line truncation — $FF EOF sentinel.
- [x] `dev/test.d64` T-COUNT: renamed from COUNTDOWN, loads and
  displays correctly after page-alignment fix.
- [x] NMI trampoline corrupted $01 — trampoline no longer modifies
  $01; handler chain runs in main RAM.  Added IRQ/BRK trampoline
  at $FF04 (defensive).  Phase 14.
- [x] IRQ/BRK trampoline verified safe — IRQs blocked by SEI,
  user BRK path returns through `run_user` which restores $01.
- [x] `t1` step over taken branches — `compute_rel_target` clobbered
  N flag with `ldy #0` before `bpl`.  Negative offsets treated as
  positive.  Fixed with BIT-abs skip trick.  Phase 14.

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

- [x] ~~Review l/s command tests~~ (fixed: test_repl.py now resolves
  `save_addr`/`save_size`/`load_result` via RODATA `sym_refs` table
  slots 11–13, replacing fragile hardcoded BSS offsets)
- [ ] Use debug builds and `od65 --dump-all foo.o` for extracting
  all symbols (exported and unexported) from object files for
  testing.  Use stripped production builds only for superficial
  end-to-end integration tests.  This eliminates fragile BSS
  offset computation and map-file parsing in test harnesses.
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
- [x] `r` command: uppercase set flags (`Nv-bDizc` vs `nv-bdizc`). (Phase 16)
- [ ] `?` command: for values < 256, show PETSCII and screen code
  character interpretation alongside the hex/decimal/binary output.
- [ ] `m` address argument: accept expression (`m screen+40`).
  Currently plain 4-digit hex only.
- [ ] New `S` command for scratching files. Requires confirmation.
- [ ] Disk command channel: unified under `$` (`$ s:file`, `$9`, etc.).
- [ ] Floppy status consistency: `$` prints status inline (always
  shows), `l`/`s` use `floppy_status` via `disk_done`.  Verify
  both paths produce identical output on stock KERNAL.
- [ ] `l` command PRG mode: report actual load address in stats
  line.  Currently shows `cur_addr` which may be wrong when the
  PRG loads at its own header address (addr=0 path).
- [ ] PRG range display: unify format to `AAAA-EEEE  NNNb` (range
  first, size second).  Currently `l` PRG stats prints `NNNb AAAA-EEEE`
  (size first).  Shared `print_prg_range` should use the same
  order as the assembler `; org` lines and the splash screen.
- [ ] `e` command: open editor at decimal line number (`e 42`).
  Centers the target line on screen as much as possible.  Ties
  into assembler error line numbers — assemble, see error at
  line 42, type `e 42` to jump straight there.
- [ ] `l`/`s` log line: always show actual file type suffix (`,s`
  or `,p`) in the `; load/save "name"...` output, even when the
  user omitted it.  The user should see what CBM DOS mode is used.
- [ ] Refactor internal default filename to a global project name
  without file type extension (e.g. `"test"`).  Actual filenames
  `"test,s"` and `"test,p"` are derived on demand.  The project
  name is set by source loads and saves only.  `l`/`s` without a
  string argument derive from the project name; error if none set.
  Replaces `cur_filename` (which stores the raw name with suffix).
  **Note:** `"foo,s"` and `"foo,p"` cannot co-exist on a D64 —
  CBM DOS ignores the type suffix for name uniqueness.  The
  derivation scheme needs a different naming convention (e.g.
  `"foo"` for source, `"foo.prg"` for binary, or user-specified).
- [ ] Investigate more shared logic for `l`/`s` argument parsing
  and filename handling.  `parse_ls_args`, `print_op_name`, and
  `print_prg_range` are a start — look for further dedup in the
  SEQ/PRG branches, error paths, and stats display.

### Debugger

- [ ] BRK tracer rewrite: use BRK's signature byte ($00 XX) to
  encode breakpoint metadata.  The 6502 skips the byte after BRK
  but the handler can read it at pushed_PC-1.  Encoding candidates:
  slot number (0-7), type (trace/watch/assert), step mode
  (into/over), managed vs unmanaged BRK.  Eliminates the
  `dbg_bp_find` address search — the handler reads the signature
  byte directly.  Simplifies step BRK vs user BP distinction.
- [ ] Single-RETURN single-step workflow: bare `t` (repeated via
  RETURN) should default to 1 step when there's an active debug
  context (`dbg_reason != 0`), not `block_size`.  Enables rapid
  `t1, RETURN, RETURN, RETURN...` stepping.

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
  `log_line` output wrappers already funnel all command output
  through a single path — hooking a line counter there should
  be straightforward.

### Assembler

- [x] `.bas` directive: emit a BASIC SYS stub.  (Phase 12, done)
  Single BASIC line: `.bas` → `0 SYS NNNNN`.
  `.bas "TEXT"` → `0 SYS NNNNN:REM TEXT`.
  Always 5 decimal digits (260 B).  2799 tests.
- [ ] Assembler error display: show source line number + context.
- [x] Per-segment assembly summary — bug fixes + streaming design.
  Fixed bugs (pass-0 output, stale asm_pc, asm_org clobber,
  expr_val clobber, filename `,s`→`,p`).  Streaming segment lines
  during pass 1, `; ok` + save command after.  +70 B, 6 tests.
- [ ] Assembly `; ok` line: show symbol count (`; ok  NNN syms`).
  Needs `sym_count` (2B BSS) in symtab.s, incremented by `sym_define`,
  but only if the symbol didn't exist before.

### Editor

- [ ] Handle files > gap buffer capacity (show error, don't crash).
- [ ] Gap buffer floor above directory load area: if `list_directory`
  stays LOAD-based (loads to $0801, max ~5.1 KB), set gap buffer
  bottom to $0801+$1400=$1C01 so `$` can never clobber source.
  Currently BUF_FLOOR is computed dynamically by `compute_layout.py`
  — would need a minimum floor of $1C01.
- [ ] Gap buffer compaction: `buf_base` only grows down (via
  `gb_ensure_room`), never shrinks.  `ed_init`/`n` should reset
  `buf_base` to BUF_END.  Line deletion could trigger compaction
  but consider the trade-off (O(n) vs immediate undo).
- [ ] Page up/down with shift+cursor or F-keys.
- [ ] Search (ctrl+f equivalent via F-key).
- [ ] Goto line number (see `e` command)
- [ ] `$A0` and `$09` should be both be interpreted as TAB, both from
  keyboard input, and when handled in source code.

### Size optimization

- [ ] Table-drive `cmd_info`: replace procedural line-by-line
  memory map display with a data table + loop (~50-80 B saving).
- [ ] PRG/SEQ save dedup: `cmd_write` and `cmd_load` have shared
  patterns in filename parsing and stats display (~30-50 B).
- [ ] `exec_line` handler code sharing: inline `@h_*` handlers
  share common tail code (log_close, nl_clear, error paths).
  Factor into shared exit points.
- [ ] Disassembler `format_operand`: investigate table-driven
  formatting (packed format byte per mode, like Woz's Apple II
  disassembler) instead of procedural per-mode branches.
  Currently 220 B, could save ~80-100 B.
- [ ] Disassembler opcode table: investigate replacing the
  `aaabbbcc` bit-slice decoder with a compact 256-byte opcode
  lookup table.  Trades CODE (~350 B decode_cc00_mem alone)
  for RODATA (256 B).  Changes the architecture fundamentally.

### Architecture

- [x] Relocating startup: done (Roadmap R2, Session 10).

- [x] **PETSCII pipeline unification + expr_eval in line assembler.**
  Phase-level work (~2-3 sessions).  Estimated savings: ~474 B
  CODE + 80 B BSS.  Eliminates the VICII/PETSCII encoding split,
  the `_insn_buf` round-trip, and the duplicate hex parser.  Gives
  the `.` command full expression support (labels, arithmetic) for
  free.  Four steps:

  **Step 1 — Hash encoding: resolved, no work needed.** (Phase 12)
  AND #$1F normalization in `_asm_rd_upper` maps PETSCII
  uppercase ($41–$5A), PETSCII lowercase ($61–$7A), and VICII
  screen codes ($01–$1A) identically to 1–26.  All hash tables,
  fingerprint tables, and T arrays are encoding-agnostic.

  **Step 2 — Switch assembler pipeline to PETSCII + rename.** (Phase 12, done)
  Merged asm_bridge.s into asm_line.s (KERNAL banking, error
  recovery, SP save/restore).  Deleted PETSCII→VICII conversion
  loop.  au_mode.s operates on PETSCII: SC_* constants updated
  (A=$41, X=$58, Y=$59), hex ranges ($41–$46 for A–F).
  Renamed: `al_` → `asm_`, `au_` → `asm_`/`mode_` across all
  source, test, stub, and doc files.  2788 tests pass.

  **Step 3 — Replace mode_parse hex parser with expr_eval.** (Phase 12, done)
  Removed `_au_rd_nib`, `_au_rd_byte`, `_au_is_hex` (-73 B).
  mode_parse calls `_au_read_val` → `expr_eval_nb` (no-banking
  variant).  Operands now accept `$hex`, `%binary`, decimal,
  labels, `*`, and arithmetic.  Fixed `hex_nybble` in expr.s
  to accept uppercase A-F (`ora #$20` case fold; numeric constants
  for portability across ca65 `-t c64` and plain `--cpu 6502`).
  Test framework: asm_core bundle replaces per-module test binaries.
  Pass flag deferred to Step 4.  2797 tests pass.

  **Step 4 — Unify source assembler with line assembler.** (Phase 12, done)
  asm_src.s passes expanded source text directly to asm_line instead
  of pre-evaluating expressions and reconstructing hex.  Removed:
  hex_tab (16 B RODATA), mode detection (#/( flags), expression
  evaluation, hex formatting, suffix copying (~197 B total).
  Local label expansion (.name → scope.name) stays in asm_src.
  Forward-reference handling: pass flag (asm_pass) in _au_read_val
  substitutes asm_pc+2 on pass 0 when symbols are undefined.
  DEFAULT_CPU moved from asm_line.s to main.s init.
  ACC detection in mode_parse hardened: bare 'A' only if followed
  by end/whitespace (not identifier chars like label names).
  2797 tests pass.
- [x] ~~BSS optimization: overlap with `ws_buf`~~ (moot: `ws_buf`
  removed in smart indent rewrite, Phase 15)
- [ ] BSS optimization: collapse `disk_seq_bytes`/`disk_seq_lines`
  with `ed_save_bytes`/`ed_save_lines` (saves 4 B).
- [ ] BSS optimization: overlap `rp_next_lo`/`rp_next_hi` with
  `rp_hexbuf` + `@new_col` (saves 3-4 B).
- [ ] Test framework: migrate dasm, expr, repl test binaries to bundle
  pattern or C64Emu integration tests.  Eliminates per-module stubs.
  See testing.md § Test bundle architecture.
- [x] Central `zp.s` owning the entire zero-page layout.  (Phase 12, done)
  All 85 ZP bytes defined in `src/zp.s` with `.exportzp`.  13 modules
  migrated from local `.segment "ZEROPAGE"` to `.importzp`.  `asm_vars.s`
  deleted (role absorbed by zp.s).  All test stubs and configs updated
  to link zp.s.  Pure refactor: 0 bytes size change, 2797 tests pass.
- [x] ~~DDD template drift~~ (fixed: moved `### Memory` before
  `**Depends on:**` in 11 module docs; Phase 15 audit remediation)
- [x] ~~Missing module doc: `src/mem.s`~~ (fixed: `doc/modules/mem.md`
  created; Phase 15 audit remediation)
- [ ] Missing module doc: `src/loader.s` has no `doc/modules/*.md`.
- [x] ~~debugger.md: all symbol names use `_` prefix~~ (fixed:
  stripped `_` prefix from all symbol names throughout the document
  to match actual exports; Phase 17 DDD Maintenance)
- [x] ~~README: missing `.bas` directive~~ (fixed: Phase 15 audit)
- [x] ~~README: `a` command description says "advances past assembled
  code"~~ (fixed: README now reads "Assemble source from editor
  at current address")
- [x] ~~README: "gap buffer grows down from $D000"~~ (fixed: Phase 15)
- [x] ~~editor.md + memory_design.md: `BUF_END` / gap buffer described
  as `$D000`~~ (fixed: updated to `__CODE_RUN__` in editor.md ×3
  and memory_design.md Design Principle 5; Phase 17 DDD Maintenance)
- [ ] Export `LOG_INFO`, `LOG_WARN`, `LOG_ERR` from repl.s so
  consumers (main.s, asm_src.s, disk.s) can import them instead
  of redefining locally.
- [x] ~~Dedup asm_src segment formatter with cmd_info free-line~~
  (fixed: shared `range_line` with two entry points `free_line`
  (suffix "b free") and `seg_line` (suffix "b").  Right-aligned
  5-digit decimal, 1-space gutter.  `s_seg_pfx` removed.  Phase 17)
- [x] ~~Rework `asm_src.s` newline handling~~ (fixed: removed 4
  redundant `jsr newline` calls; `log_close` provides trailing
  newline.  "asm..." line now uses `log_close` instead of bare
  `io_clear_eol`.  `seg_print_save` no longer needs its own
  newline.  Phase 17)
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
- [x] Revise RUN/STOP+RESTORE and NMI handling.  (Phase 14, done)
  Permanent NMI dispatcher (`cse_nmi_handler`) at $0318.
  NMI-in-REPL → `cse_warm_screen` (clean screen recovery).
  Internal BRK → `cse_warm_start` (idempotent hard recovery).
  Warm-start re-entry guard prevents infinite BRK loops.
  NMI trampoline no longer corrupts $01.

### Features

- [ ] PRG load: auto-detect load address from PRG header.
- [ ] `$` command: filter directory listing by filename glob.
- [ ] `d` command: show ASCII alongside disassembly (like `m`).
- [ ] `.` command: show help when mnemonic given without operand.
- [ ] Color command `C`: show color preview swatches.
- [ ] Disk I/O: timeout handling for unresponsive drives.
- [x] NMI during `j` user code.  (Phase 14, done)
  `cse_nmi_handler` dispatches on `dbg_running` — user-code
  NMI breaks into debugger immediately via `dbg_nmi_break`.
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
