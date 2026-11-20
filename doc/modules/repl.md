# repl.s — REPL Command Interface (the kernel's ISR body)

**Template:** [module](../templates/module.md)

The REPL command interpreter: it reads a screen row, parses an
optional `AAAA:` address prefix and a one-character command, and
dispatches to the command's handler.  It also owns the break panel
that follows a run of user code and the cleanup that runs after it.
Hex parsing helpers (`_hex_val`, `_is_hex`, `_hex_val_to_char`) are
local to repl.s.

The REPL is the body of CSE's ISR-style kernel.  `main_loop`
([main.md](main.md)) calls `read_line` / `exec_line` /
`show_prompt`.  A command that runs user code (`j`, `g`, `c`, `t`,
`o`) never enters user code itself: it stages the state, sets
`run_user_pending` and returns, and `main_loop` jumps to the
debugger's gate ([§ Command → userland dispatch](#command--userland-dispatch)).
Control comes back through the BRK / NMI handler's longjmp to
`main_loop_top`, which calls `post_run_cleanup`.  See
[design_cse_as_kernel.md](../design_cse_as_kernel.md) for the design
framing.  The user-facing command reference is the root
[README.md § REPL commands](../../README.md#repl-commands).

## Owned files

| File | Role |
|------|------|
| [`src/repl.s`](../../src/repl.s) | implementation (assembly) |
| [`tests/integration/test_repl.py`](../../tests/integration/test_repl.py) | test contract — Tier I (full PRG via `C64Emu`) |
| [`tests/emulator/test_m65_far_start.py`](../../tests/emulator/test_m65_far_start.py) | test contract (Tier X) — `j 4.2000` in xmega65 on each ROM: the KERNAL's map record holds the far map from the first instruction, a CBDOS call returns into bank 4, `r` shows `ml:e400` (slice 3, F3) |
| [`tests/emulator/test_m65_flat.py`](../../tests/emulator/test_m65_flat.py) | test contract (Tier X) — flat addresses typed in xmega65 on each ROM: `@ 4.2000`, `m` and `.` into bank 4, `d`, a refused write into bank 3; the bytes and every screen M65Emu's (slice 3, F1) |
| [`tests/integration/test_m65_repl.py`](../../tests/integration/test_m65_repl.py) | test contract — Tier I on the m65 PRG: the cold start, the REPL and the debugger typed (P2 T7–T9) |
| [`tests/integration/test_repl_disk.py`](../../tests/integration/test_repl_disk.py) | test contract — Tier I disk-command paths (`l`, `s`, `$`) routed through `exec_line`, on C64Emu with a virtual 1541 |

Further REPL contracts live with the subsystem they exercise:
`TestOutputHygiene` and `TestQueryUserOutcomes` in
`tests/integration/test_kernel_transition.py` (run through
`main_loop`).

## Interface

### exec_line
**In:** `line_buf` = the command line (NUL-terminated PETSCII, as
`read_line` leaves it); `cur_addr`, `last_cmd`.
**Out:** the command has run.  An `AAAA:` prefix has set `cur_addr`;
the command may have moved `cur_addr`, set `last_cmd`
([§ Repeat](#repeat)) or set `run_user_pending` (`j`/`g`/`c`/`t`/`o`;
the caller clears it before the call and dispatches on it after).
Most handlers return normally.  Three paths do not: `R` (yes) ends
in `cse_refresh`, and the end-debug gates of `a` / `j` / `g` (yes)
set `warm_cont` and jump to `cse_end_debug` — warmstarts that
replay `line_buf` through `exec_line` ([main.md](main.md),
[memory_design.md § Warmstart entry points](../memory_design.md#warmstart-entry-points)).
`Q` (yes) sets `state = ST_STOP` and returns.
**Clobbers:** A, X, Y, `rp_ptr`, `rp_ptr2`, `rp_tmp`, `rp_tmp2`,
`rp_addr`, `rp_cnt`, `rp_save`, `rp_save2`, `rp_next_lo`, and
whatever the dispatched command's callees clobber (expr, asm, dasm,
disk, editor state).

### read_line
**In:** `CUR_ROW` ($D6) = the screen row to read.
**Out:** `line_buf` = the row's 40 characters, reverse-video bit
stripped, screen codes converted by `scr_to_pet` (lowercase letters
→ $41–$5A, SHIFTed letters → $C1–$DA), trailing spaces trimmed,
NUL-terminated.
**Clobbers:** A, X, Y, `rp_ptr`.

### show_prompt
**In:** `cur_addr`.
**Out:** `AAAA:` written at column 0 of the cursor row; cursor at
column 5.  Nothing else on the row changes (clearing the row is the
previous handler's job, [§ Command handler principles](#command-handler-principles)).
**Clobbers:** A, X, Y (and cse_io's screen pointer).

### cmd_info
**In:** C=0 full map (`i` command), C=1 splash mode (main.s's
startup screen).
**Out:** the memory-map rows ([§ `i` — Memory map](#i--memory-map));
`_info_mode` = 0 full / 1 splash.  Splash mode prints only the free
rows (zp, the two low fragments, work; m65: low, work and the `ext`
banks).  On m65 `info_bank` is 0 again on return.
**Clobbers:** A, X, Y, `rp_ptr`, `rp_ptr2`, `rp_addr`, `rp_cnt`,
`rp_save2`, `rp_next_hi`, `rp_opc`; with source loaded also
`ed_save_lines` / `ed_save_bytes`.

### step_cleanup
Ends a step: `step_state` = STEP_NONE, `step_remaining` = 0, the two
step slots zeroed (`dbg_step_clear`), the breakpoint `cmd_step`
disabled (`rp_dis_bp` = slot × 4) enabled again, `rp_dis_bp` = $FF.
Called by `post_run_cleanup` (a step landed), `cmd_step` (a step was
refused) and main.s's `end_debug_body` (the session ended).
**In:** `rp_dis_bp`.  **Out:** as above.  **Clobbers:** A, X.

### post_run_cleanup
Called by `main_loop_top` after user code broke back into the kernel
(`dbg_reason`, `step_state` or `run_user_pending` non-zero).
**Out:** `;!stk N` (LOG_WARN) when `reg_sp` < 64
(`kernel_stack_budget` — [userland_contract.md § Kernel stack budget](../userland_contract.md#kernel-stack-budget));
then, if a step was running, `step_cleanup`; then the break panel
(`show_break_result`, debugger.md § Break panel); after a
clean exit (`; rts`) the `pc:` field shows `cur_addr` at exit time;
`cur_addr` = `brk_pc`.  After a step that ended the session
(`DBG_RTS`) `last_cmd` = 0, so RETURN does not repeat the step.
**Clobbers:** A, X, Y and the REPL's ZP scratch.

### kernel_stack_budget
**Value:** 64 (exported equate, defined once in repl.s).

The kernel-reentry headroom of
[userland_contract.md § 4](../userland_contract.md#4-stack-contract);
`post_run_cleanup`'s `;!stk` check is its only reader.  Exported for
the test harness's label lookup; no module imports it.

### hygiene_after_userland
Called by main.s's `handler_finalize` on every return from user code.
**Out:** `$CC` = 1 (KERNAL cursor off), `$0291` = $80 (SHIFT+C=
charset toggle locked), the three SID voice control registers
($D404/$D40B/$D412) = 0, `vic_reset`, `restore_colors`,
`stop_cooldown` = 1 after an NMI break, `kernal_screen_reset`, then
`io_sync`.
**Clobbers:** A, X, Y.

**State** (BSS, read by main.s):
- `cur_addr` (word) — the current address shown in the prompt.
  `reset_globals` (main.s) sets it to $0800 at cold start and on
  `cse_recover`.
- **m65:** the current address carries its
  space ([§ Banks](#banks-m65)): `cur_flat` (byte, BSS: 0 = a CPU
  address, nonzero = flat) and `cur_bank` (word, BSS: the flat
  address's bank and megabyte, bits 16–27).  Every site that sets
  `cur_addr` from a CPU source — `@` with an expression,
  `reset_globals`, a break panel, `a`'s `main`, `j` — clears
  `cur_flat`; a prefix or `@` with a flat literal sets all three; an
  advance (`m`, `.`, `d`, `+`, `-`) keeps the space and, in flat
  space, carries into `cur_bank` when the low word wraps.  The
  command scratch mirrors it: `rp_flat`, `rp_bank` beside `rp_addr`
  (`load_curaddr` copies all of them; `exec_line` clears `rp_flat`
  first, so a command not loaded from the current address works on a
  CPU address).  The c64 has neither: its code is unchanged.
- `block_size` (word) — block size for `m`, `d`, `+`, `-` and a bare
  PRG `s`; default $0010 (`reset_globals`).
- `last_cmd` (byte) — the repeatable command RETURN repeats
  ([§ Repeat](#repeat)); cleared by `end_debug_body`.
- `line_buf` (42 B) — the command line.  `cse_end_debug`'s replay
  re-runs it.
- `cold_preview_done` (byte) — set by `t`/`o`'s cold preview,
  consumed by `set_run_mode`, cleared by `end_debug_body`.

`cur_device` (default 8) and `cur_project_name` are REPL state kept
in zp.s; see [zp.md](zp.md) — both in zero page on c64; on m65
`cur_project_name` is zp.s's BSS
([zp.md § The m65 base page](zp.md#the-m65-base-page)).

### Memory

**BSS (110 bytes):**

| Variable | Size | Purpose |
|----------|------|---------|
| `cur_addr` | 2 | Current address (REPL prompt) |
| `last_cmd` | 1 | Repeatable command byte |
| `block_size` | 2 | Block size |
| `disk_name_buf` | 18 | Composed disk filename (FILENAME_MAX + 2) |
| `_verbatim_type` | 1 | 0 / 's' / 'p' from `strip_and_classify` |
| `_arg_count` | 1 | Numeric argument count from the last `l`/`s` parse (0–2) |
| `line_buf` | 42 (m65 82) | Screen line capture buffer: the widest row, its NUL and a spare |
| `dot_asm_buf` | 24 | `.` instruction text handed to `asm_line` |
| `rp_next_hi` | 2 | 16-bit scratch pair (`rp_next_lo` is in zp.s) |
| `rp_opc` | 1 | Command character / scratch (`emit_mem` columns, `info_emit_rows` count) |
| `rp_dis_bp` | 1 | `cmd_step`: disabled breakpoint slot × 4 ($FF = none) |
| `rp_hexbuf` | 3 (m65 5; `INSN_MAX`) | `cmd_dot` hex byte parse: up to `INSN_MAX` pairs, the longest instruction |
| `cold_preview_done` | 1 | Cold-preview marker |
| `zp_stage_buf` | 8 (m65 16; `MEM_ROW_MAX`) | User-ZP staging buffer for `m` dump and `.` disasm ([§ User-ZP view](#user-zp-view)) |
| `wl_vcol` | 1 | `warn_long_lines`: visual column of the current line |
| `wl_line` | 2 | `warn_long_lines`: 0-based line number |

**Depends on:** asm_src (`asm_assemble`, `seg_print_save`), asm_line
(`asm_line`, `reg_a`/`reg_x`/`reg_y`/`reg_sp`/`reg_p`; m65 `asm_rel16`), asm_err
(`asm_err_code`), dasm (`dasm_insn_pre`, `_dasm_in`, `_dasm_ptr`, `dasm_buf`; m65 `_dasm_mode`), expr (`expr_eval`,
`expr_error_str`), symtab (`sym_lookup`), breakpoints (`dbg_bp_set`,
`dbg_bp_del`, `dbg_bp_clear`, `dbg_step_clear`, `bp_table`,
`dbg_bp_hit`), debugger (`brk_pc`, `brk_stub`,
`step_next_pc`, `arm_step_bp`, `step_state`, `step_remaining`,
`step_next_lo`, `step_next_hi`), main (`run_user_pending`,
`stop_cooldown`, `cse_refresh`, `cse_end_debug`, `end_debug_body`),
editor (`ed_save_source`, `ed_load_source`, `ed_new`,
`ed_save_lines`, `ed_save_bytes`), gap_buffer (`ed_ensure_init`,
`ed_total_lines`, `ed_read_rewind`, `ed_read_byte`, `src_top`,
`src_bot`), disk (`list_directory`, `disk_load_prg`,
`disk_save_prg`, `floppy_read_status`, `fl_buf`),
mem (`userland_zp_buf`, `ZP_SAVE_LO`, `ZP_SAVE_LEN`, `cse_start`,
`cse_end`), log (`log_*`, `prg_line`, `free_line`,
`info_line*`, `puts_imm`), cse_io, screen, strings, zp (`state`,
`dbg_reason`, `warm_cont`, `ed_dirty`, `buf_base`, `asm_cpu`,
`cur_device`, `cur_project_name`, the `rp_*` scratch)

## Design

### Prompting loop

The main loop ([main.md § Keyboard](main.md#keyboard)) owns the
prompt; command handlers never write it.  On RETURN it calls
`read_line` (the cursor row → `line_buf`), clears
`run_user_pending`, calls `exec_line`, then either jumps to the
userland gate (`run_user_pending` set) or calls `show_prompt` and
waits for the next key.  `exec_line`:

1. Skips leading spaces.
2. If the line starts with four hex digits and a `:`, sets
   `cur_addr` to them and skips the prefix and following spaces.
3. Reads the command character.
   - NUL (empty line): if `last_cmd` is set, prints `AAAA:c` (the
     repeated command after the address) on the row and dispatches
     it with no arguments; else advances to a clean row.
   - `;`: clears `last_cmd`, advances to a clean row (a comment
     line is a no-op).
4. Skips the command character and one following space, records a
   repeatable command in `last_cmd`, and dispatches through the
   command table ([§ Command dispatch](#command-dispatch)).

### Command dispatch

The dispatch table is three parallel arrays local to `.proc
exec_line`:

- `@cmd_chars` — the command bytes, `0`-terminated.  Lowercase keys
  are the PETSCII bytes `read_line` produces for unshifted letters
  ($41–$5A, written `'a'` in the source); SHIFTed keys are $C1–$DA
  (`B` = $C2, `C` = $C3, `Q` = $D1, `R` = $D2).
- `@cmd_lo` / `@cmd_hi` — the handler addresses, `@h_<key>` labels
  in the same proc.

`exec_line` scans `@cmd_chars` for the command byte, loads the
handler address into `rp_ptr2` and `jmp (rp_ptr2)`; no match is
`;?cmd`.  A handler is either a `jmp` to a `cmd_…` proc or the
command body inline.

**Adding a command:** add the key byte to `@cmd_chars` and the
handler's `<`/`>` bytes at the same index of `@cmd_lo` / `@cmd_hi`
(the three rows must stay aligned), write `@h_<key>` (or a `jmp` to a
`cmd_…` proc), add the key to [§ Free / reserved keys](#free--reserved-keys)
and to the user manual.

**Handler entry contract.**
- `rp_ptr` points past the command character and at most one space:
  at the first argument byte, a space, `;` or NUL.  Handlers that
  accept more spaces skip them themselves (`skip_sp_ptr1`,
  `skip_peek_ptr1`).
- `cur_addr` already holds the `AAAA:` prefix value.
- The stack is exactly as `main_loop`'s `jsr exec_line` left it:
  the handler runs at exec_line's level (entered by `jmp`, no frame
  of its own), so its final `rts` returns to `main_loop`.  The
  pop-trick helpers below depend on this.

**Shared parse helpers.**
- `try_expr` — skips spaces, evaluates one expression at `rp_ptr`
  and advances `rp_ptr` past it.  C=1: success, value in
  `expr_val`.  C=0 and Z=1: empty (NUL or `;`).  C=0 and Z=0:
  expression error; `try_expr` has already printed `;?expr <detail>`.
  A command with an optional argument acts on "empty" only and does
  nothing on an error ([§ Single-expression command contract](#single-expression-command-contract)).
- `try_expr_or_err` — `try_expr`, then on success
  `_require_eoi_or_err` on the rest of the line.  Same C/Z results;
  trailing garbage never returns (pop-trick).
- `_require_eoi_or_err` — Y = offset from `rp_ptr`; accepts only
  spaces ($20 / $A0) then NUL or `;`.  On anything else it pops its
  caller's return address and jumps to `log_err` (`;?syntax`), whose
  `rts` returns to `main_loop`: the handler body stops at the check.
  **One-jsr-deep rule:** call it (or `try_expr_or_err`) only from the
  handler itself — one `jsr` below exec_line's level.  From a nested
  subroutine it would drop the wrong frame.  `expr_or_blocksize`
  (`+`/`-`) uses the same pop-trick for its error path, and
  `parse_filename`'s unterminated-quote path drops three frames
  (`get_filename`, `parse_ls_args`, `cmd_load`/`cmd_write`).
- `_syntax_err` — the shared `;?syntax` tail (`jmp` or `jsr`).

### Repeat

`last_cmd` holds the last *repeatable* command: `.`, `d`, `m`, `t`,
`o` (`@rep_chars`, scanned with `ldx #4`).  Other commands leave it
unchanged; a `;` line, an empty line with nothing to repeat, and a
step that ends the session (`DBG_RTS`) clear it.  RETURN on an empty
prompt runs `last_cmd` at the current `cur_addr` with no arguments:
`d` pages the disassembly, `m` the dump, `.` shows the next
instruction, `t`/`o` take one more step.  `last_cmd` stores only the
command character, no arguments.

### Command handler principles

1. **The screen is the command buffer.**  Every screen row is
   executable.  The parser reads from column 0 to `;` or the end of
   the row.  The screen uses the lowercase character set.

2. **Commands are case-sensitive single characters.**  Lowercase
   keys are the default; SHIFTed keys (`B`, `C`, `Q`, `R`) are
   distinct commands — 52 letter slots.

3. **Commands own their output lines.**  Every row a handler writes
   is `io_clear_eol`'d — no leftover characters.

4. **Commands own their prompt line.**  In block-edit mode (`.` with
   arguments, `m` with hex bytes) the handler rewrites its own row
   to show the edited state.  What is on screen is the truth.

5. **Commands own the next line's clearing.**  Before returning,
   handlers clear the row the prompt will go on, so `show_prompt`
   writes `AAAA:` onto a clean row.  Exception: `.` and `m` in edit
   mode leave the next row intact — the block-edit workflow (cursor
   up, modify, RETURN again).

6. **Non-executable output starts with `;`.**  Info, status and
   error rows are inert when RETURN is pressed on them.

7. **Executable output without a `cur_addr` relation omits `AAAA:`**
   (for example the `r` register row).

8. **Auto-advance.**  `.`, `m` and `d` leave `cur_addr` at the
   continuation address, so [§ Repeat](#repeat) pages on.

9. **Block commands are loops over single-line emitters.**  `d`
   calls `emit_dot` per row, the `m` dump `emit_mem`.

10. **No spurious blank lines.**  Every row a command emits carries
    content.  A fully blank row between a command's first output row
    and the next prompt is a bug.  Pinned by one smoke test,
    `TestOutputHygiene`, over a representative slice of commands;
    individual layouts (row counts, cursor arithmetic) are checked
    on real hardware / VICE, not pinned by unit contracts.

### Error reporting

Errors are `;?<tag>` (LOG_ERR), warnings `;!<tag>` (LOG_WARN), info
`; <text>` ([log.md](log.md)).  The REPL's tags:

| Row | Source |
|-----|--------|
| `;?syntax` | trailing garbage, bad `.`/`r`/`C` input, unterminated `"`, `b` with a bad argument |
| `;?expr <detail>` | expression error (`exp val`, `ovfl`, `exp )`, `undef`, `div0`) |
| `;?cpu` | `.` mnemonic refused by the CPU mode |
| `;?cmd` | unknown command key |
| `;?range` | `b ADDR` outside the workspace; PRG `s` of size 0 |
| `;?full` | `b ADDR` with all 8 breakpoint slots in use |
| `;?bad val` | `b -N` with N not 1–8 |
| `;?no ctx` | `c` without a resumable session; `t`/`o` after the session ended |
| `;?fail` | disk load / save failed |
| `;?too big` | SEQ file larger than the source buffer |
| `;!range` | a step refused: its BRK would land outside the workspace |
| `;!unsaved`, `;!debug` | gate warnings ([§ Gating pattern](#gating-pattern)) |
| `;!long LNN` | a loaded / saved source line wider than 39 columns |
| `;!stk N` | user SP below the kernel stack budget at a break |

The source assembler's own rows (`;?N: <msg>`, `;!N: truncated`,
`; N err`) are owned by [asm_src.md](asm_src.md); the user-facing
list is [README.md § Error and warning messages](../../README.md#error-and-warning-messages).

### Block-edit workflow

The block-edit workflow is how the user inspects and modifies code or
data in bulk.  It has two phases: **dump** and **edit**.

**Dump phase** — `d` and `m` (without edit bytes) operate on
`block_size` bytes and print executable rows:

- `d` prints `AAAA:.  HH HH HH  mne opr` rows (`emit_dot`); on m65
  five byte columns, `AAAA:.  HH HH HH HH HH  mne opr`
  ([§ Line format and address handling](#line-format-and-address-handling)).
- `m` prints `AAAA:m HH HH HH HH HH HH HH HH;cccccccc` rows
  (`emit_mem`).  The `;` before the character column makes the row
  re-executable: `_require_eoi_or_err` accepts `;` as the end of
  input, so RETURN on the row treats the characters as a comment and
  the 8 hex bytes as an edit.

**By width** (operator, 2026-11-18): an `m` row holds 8 bytes in 40
columns and **16 bytes in 80 columns** — `AAAA:m` + 16 × ` HH` + `;` +
16 characters, 71 columns; on m65 the width decides at each row, on
c64 it is always 8.  An edit accepts up to 16 bytes on m65 (8 on c64),
whatever the width, so a 16-byte row typed in 80 columns and recalled
in 40 still executes.  `zp_stage_buf` holds 16 bytes on m65.  The
other emitters do not change with the width.

The block command clears the final prompt row and stops.  The screen
is now a buffer of editable commands.

**Edit phase** — the user cursors to any row:

- Change hex bytes in an `m` row, RETURN → `m` writes them, rewrites
  the row from memory, advances `cur_addr`.
- Change the bytes, mnemonic or operand in a `.` row, RETURN → `.`
  pokes or re-assembles, rewrites the row, advances.

With arguments, `.` and `m`:
1. Execute the edit (assemble / write bytes).
2. Rewrite their own row to the new state.
3. Do **not** clear the next row.
4. Leave `cur_addr` at the continuation address.

The prompting loop then writes `AAAA:` over the first five columns of
the next row without clearing the rest — the dump content from column
5 on stays editable.  Without arguments the same commands are in dump
mode (`.` shows one instruction, `m` dumps `block_size` bytes) and
clear the prompt row normally.

### The `.` command in detail

**m65:** at a flat current address `.` works on
the flat bytes (§ Banks): a poke writes them there, a disassembly
reads them there, and an assembly sets `asm_out` to the flat address
and `asm_pc` to its low word.  A write into `2.0000–3.FFFF`, in
either space, is `;?range`, before any byte is written.

The `.` handler (`cmd_dot`) has three modes:

1. **Hex bytes that differ from memory:** write them at `cur_addr`.
2. **Hex bytes that match memory, followed by text:** assemble the
   text (mnemonic + operand) — the path a re-executed `d` row takes.
   The instruction keeps its width: on m65, when the matched bytes are
   a 16-bit branch (`REL16`, which lists like an 8-bit one), the text
   is assembled as `REL16` (`asm_rel16`, [asm_line.md § Branches](asm_line.md#branches-zone-b)),
   so RETURN on an unchanged row writes the same bytes.
3. **No arguments:** disassemble one instruction at `cur_addr`.

**Expression support.**  In mode 2 (and for a bare `. mne opr`) the
operand is evaluated by `expr_eval` before `asm_line` sees it, so
full expressions work:

    1000:. lda screen+$20     ; label + arithmetic
    1000:. sta <addr          ; lo byte operator
    1000:. ldx #cols-1        ; constant expression

Symbols from the last `a` are available (the symbol table persists
between assemblies).

`dot_assemble` copies the mnemonic word (letters and, on mn7 builds,
digits — asm_line judges them; at most 8 — the bit-op mnemonics such as `rmb3`;
on m65 also the `q` names and the `q` suffix,
[asm_line.md § Mnemonic word](asm_line.md#mnemonic-word)), keeps a
leading `#`, `(` and, on m65, `[`, evaluates the operand to `$XX` or
`$XXXX` (by `expr_eval`'s width result), copies the rest of the
operand (`,x`, `)`, `),y` …) unchanged, and passes the text to
`asm_line` with `asm_pc` = `asm_out` = `cur_addr`.  An operand that is
the bare accumulator `a` is evaluated as an expression too, so
`. asl a` is `;?syntax`; write `. asl` (TODO § Bugs › Both platforms).
On m65 the operand's rest includes `],z`, `),z` and `,sp),y`.

In all three modes the handler finishes by disassembling the
instruction at `cur_addr` and rewriting its row with the result.

**User-ZP redirect (modes 1 and 3).**  See [§ User-ZP view](#user-zp-view).
Mode 2 (assembly) writes through `asm_line` to live memory and is not
redirected; to put bytes into user ZP, use the hex-poke form.

#### `.` command input-shape matrix

Testing matrix: `tests/integration/test_repl.py::TestDotHexEdit`.

| After the `.` (+ whitespace) | Behaviour | Example |
|---|---|---|
| Nothing (`NUL`) | Redisplay of the current instruction | `.` |
| `;` comment | Redisplay | `. ; note` |
| Two hex digits + space/`;`/NUL, up to 3 pairs (5 on m65) | Hex-byte poke at `cur_addr` | `. a9 42` |
| Letter `a`–`z` (mnemonic start) | Assemble via `dot_assemble` | `. lda #$00` |
| **Anything else** | **`;?syntax`** | `. .`, `. ,`, `. $`, `. 123` |

The pair limit is the build's longest instruction: 3 on c64, 5 on
m65 (a 45GS02 instruction with its prefixes).  Every mnemonic has at
least three letters, so a mnemonic is never read as a pair.

#### Error tag dispatch (mnemonic-assemble path)

When `dot_assemble` returns 0 the handler reads `asm_err_code` (set
by [asm_err.s](asm_err.md)):

| `asm_err_code` | Tag | Example trigger |
|---|---|---|
| 0 | `;?syntax` | unknown mnemonic, bad mode for the profile |
| 1 | `;?expr <detail>` | undefined symbol, overflow — `<detail>` from `expr_error_str` |
| 2 | `;?cpu` | mnemonic refused by the CPU mode (`lax` on 6502, `taz` on 6502 on m65) |

An operand expression error found by `dot_assemble` itself (before
`asm_line`) also returns 0; the tag then follows whatever
`asm_err_code` holds.

### User-ZP view

ZP locations in the save range `[ZP_SAVE_LO, ZP_SAVE_LO +
ZP_SAVE_LEN)` ($00–$7F, exported from [mem.s](../../src/mem.s))
have two images:

- **Live ZP** — CSE's own ZP while the kernel runs.
- **Saved user ZP** — `userland_zp_buf` (128 B BSS, owned by
  [mem.md](mem.md)), seeded by `dbg_init` at cold start and refreshed
  on every userland → kernel transition.  The next entry into user
  code restores it.

The `m` and `.` commands **always** read and write the saved image
for addresses in the save range — CSE's live ZP there is never shown
to or accepted from the REPL user:

| Command | Path | Redirect |
|---------|------|----------|
| `m` dump | read a row (`MEM_ROW_MAX`: 8, m65 16) for display | yes — staged from `userland_zp_buf` into `zp_stage_buf` |
| `m` edit | write each edited byte | yes — lands in `userland_zp_buf` |
| `.` disasm | read `INSN_MAX` bytes (3, m65 5) for the disassembler | yes — staged into `zp_stage_buf` |
| `.` hex poke | write each parsed byte | yes — lands in `userland_zp_buf` |
| `.` mnemonic | `asm_line` emits at `asm_pc` | **no** — live memory |

For reads (`zp_stage_prep`) and writes (`zp_poke`) the effective
address is the full 16-bit `base + offset`, which wraps past `$FFFF`
to `$0000` as `(zp),y` does: an edit run that starts at `$FFFC` lands
its fifth byte in the user's `$00` (`userland_zp_buf`), never in the
live CPU port or CSE's own ZP, and `m fffc` shows the user's
`$00`–`$03` in its last four columns.  Only a base in page 0 or page
`$FF` is staged; other runs are read in place.  Outside the save
range reads and writes go to memory: $80–$FF is KERNAL ZP and not
mirrored.

`zp_stage_prep` fills `zp_stage_buf` (`MEM_ROW_MAX` bytes) from `(rp_ptr2)`,
taking `userland_zp_buf` bytes for in-range offsets and live bytes
for the rest, then points `rp_ptr2` at the buffer, so `emit_dot` (which copies
the staged bytes into `_dasm_in` and enters `dasm_insn_pre` with the
real PC, so branch targets stay right), `emit_hex_cols` and `cmd_dot`'s compare loop read the view
uniformly.  `zp_poke` (A = byte, `rp_ptr2` + Y = address) mirrors it
for single-byte writes.  Both assume the save range lies in page 0
and `ZP_SAVE_LO` = 0 (the lower-bound test is elided); the
`INTROSPECT` build compiles both to plain live access.

**On m65** the save range is the CPU port, `$00–$01`
(`ZP_SAVE_LEN` = 2): the transitions swap the port and nothing else
of base page 0, which CSE never writes
([platform_layer.md § Base page](../platform_layer.md#base-page)).
The same routines serve both platforms: `m 00` and `m 01` show and
edit the user's port in `userland_zp_buf`, and every other address is
read and written live through `rp_ptr2` / `rp_ptr` set with
`FAR_USER`.  `zp_stage_prep`'s pointer to `zp_stage_buf` carries
`BANK_CSE`.

### Line format and address handling

`AAAA:cmd [args]` or bare `cmd [args]`; `;` ends parsing.  The
`AAAA:` prefix is always four plain hex digits.  Commands operate on
`cur_addr`; `.`, `m` and `d` leave it past the bytes they handled,
`@`, `+`, `-` set it, a break panel sets it to the break PC, and `a`
sets it to `main` when the source defines one.

Row formats (40 columns):

    AAAA:.  HH HH HH  mne opr                 . / d (3 byte columns)
    AAAA:.  HH HH HH HH HH  mne opr           . / d on m65 (5 columns)
    AAAA:m HH HH HH HH HH HH HH HH;cccccccc   m
    r pc:XXXX a:XX x:XX y:XX s:XX nv-bdizc    r (set flags uppercase)

The REPL's line-editing keys (DEL, INS, cursor keys, HOME,
SHIFT+CLR/HOME) are main.s's: [main.md § Keyboard](main.md#keyboard).

### Commands — Memory

| Key | Name     | Addressed | Example                     | Notes                                      |
|-----|----------|-----------|-----------------------------|----------------------------------------------|
| `m` | memory   | yes       | `1000:m` dump, `1000:m a9 00 …` edit, `m 2000` dump at $2000 | An optional 4-digit hex address (not an expression) after `m` overrides `cur_addr`.  Bare = dump `block_size` bytes; with hex pairs = edit up to 8 bytes.  Rejects trailing garbage (§ Single-expression command contract). |

### Commands — Assembly / Disassembly

| Key | Name       | Addressed | Example              | Notes                                        |
|-----|------------|-----------|-----------------------|----------------------------------------------|
| `.` | asm/disasm | yes       | `1000:. lda #$00`    | Single instruction; full expressions in operands.  See the input-shape matrix. |
| `d` | disassemble| yes       | `1000:d`              | Disassemble `block_size` bytes.  Takes no arguments; rejects trailing content. |
| `a` | assemble   | yes       | `a`                   | Assemble the source buffer; the default origin is `cur_addr` ([asm_src.md](asm_src.md)).  Prints `; asm...`, the segment rows, then `; ok` and the executable save row, or `; N err`.  On success `dbg_reason` = DBG_NONE and `cur_addr` = `main` if defined. |

### Commands — Execution

| Key | Name | Addressed | Example          | Notes                                      |
|-----|------|-----------|------------------|--------------------------------------------|
| `j` | jump | yes       | `1000:j` or `j main` | Run at the expression, or at `cur_addr` when bare; an expression error runs nothing.  Rejects trailing garbage. |
| `g` | go   | —         | `g`              | Run at `main`; at `cur_addr` when `main` is undefined. |
| `c` | continue | —    | `c`              | Resume a resumable session (`DBG_BRK`/`DBG_NMI`), else `;?no ctx`.  Deletes the breakpoint that was hit, steps past a user `BRK` at `brk_pc`, then resumes; after a cold preview it is a fresh start ([debugger.md § `c`](debugger.md)). |

The debug-session gates of these commands, `t`/`o`, `a` and `R` are
[debugger.md § `dbg_reason` × command matrix](debugger.md#dbg_reason--command-matrix) (owner).

### Commands — Debug / Trace

| Key | Name      | Addressed | Example         | Notes                                    |
|-----|-----------|-----------|-----------------|------------------------------------------|
| `r` | registers | —         | `r` or `r a:05 x:07` | Bare = show.  Fields by label in any order and subset: `a:XX` `x:XX` `y:XX` `s:XX` `pc:XXXX` (hex digits) and the 8-character flags field (`nv-bdizc`; uppercase = set, lowercase / `-` / `.` = clear; bit 5 stays 0).  The whole line is checked before anything is applied; a bad field is `;?syntax`. |
| `b` | breakpoint| —         | `b $1020`, `b main`, `b -1`, `b *`, `b` | Set (expression; must be in the workspace, else `;?range`; an address already set reuses its slot), delete slot 1–8, clear all, list the 8 user slots.  An expression error is its `;?expr` row alone; trailing garbage is `;?syntax`.  See [breakpoints.md](breakpoints.md). |
| `t` | trace     | —         | `t` or `t 5`    | Step into, count = expression (default 1).  No session: cold preview.  Rejects trailing garbage. |
| `o` | trace over| —         | `o` or `o 5`    | Step over (a `jsr` runs to completion), otherwise as `t`. |

`t`/`o` take the count as a 16-bit expression; 0 and an empty
argument mean 1.  An expression error in the count is reported and
nothing else happens — no step, no cold preview (as `j`).

### Commands — Navigation

| Key | Name    | Addressed | Example       | Notes                                    |
|-----|---------|-----------|---------------|------------------------------------------|
| `@` | seek    | —         | `@ $1000` or `@ main` | Set `cur_addr` to the expression; bare or an expression error = no change.  Rejects trailing garbage. |
| `+` | forward | —         | `+` or `+ $20` | Advance `cur_addr` by the expression, or by `block_size` when bare or 0; an expression error moves nothing.  Rejects trailing garbage. |
| `-` | back    | —         | `-` or `- $20` | As `+`, backwards. |

### Commands — I/O

| Key | Name   | Addressed | Example              | Notes                                   |
|-----|--------|-----------|----------------------|-----------------------------------------|
| `l` | load   | yes       | `l "proj"` / `l "proj" $2000` | Load SEQ by default; PRG when address arguments are present |
| `s` | save   | yes       | `s "proj"` / `s "proj" $2000` | Save SEQ by default; PRG when address arguments are present |
| `$` | directory | —      | `$`, `$ 9`            | Directory listing; selects a device first.  See [§ Directory listing](#directory-listing). |

### Project-name and filename semantics (`l` and `s`)

The user interacts with projects by **stem name**, not disk filename.
Disk filenames are derived from the project stem + mode.  For each
project "proj":

- **Source (SEQ)** lives on disk as the bare stem `proj`.
- **Binary (PRG)** lives on disk as `proj.` (trailing dot).

Two files with the same stem cannot coexist on a CBM DOS disk (the
type byte in the directory doesn't disambiguate the filename lookup),
so the trailing dot is how CSE distinguishes the two artefacts of one
project.

**Project name storage** (`cur_project_name`): the stem of the
last-used project, updated whenever the user supplies a quoted name;
`"out"` when none was ever given.  On store:
1. Strip a trailing `,s` or `,p` suffix (if present).
2. Strip any trailing dot(s) from the remaining string.
3. Copy the result (at most 16 characters) to `cur_project_name`.

This prevents dot or suffix accumulation across consecutive saves.

**Argument parsing** (shared between `l` and `s`, strictly positional):

1. Optional `"quoted name"`.  Quotes required.  An unterminated
   string (opening quote without a closing quote) is `;?syntax` and
   the command aborts before any disk I/O or name change.  The empty
   form `""` and the bare form (no quote) both reuse the project
   name.
2. Numeric arguments via the expression parser, up to two.  Parsing
   stops at the first failed expression, `;` or the end of input.

Count of numeric arguments → slots:

| Args | start    | end   |
|------|----------|-------|
| 0    | cur_addr | 0     |
| 1    | cur_addr | arg1  |
| 2    | arg1     | arg2  |

**Mode classification** (shared):

- Name ends with `,s`/`,S`: **SEQ (verbatim)** — use the bare name
  (suffix stripped).
- Name ends with `,p`/`,P`: **PRG (verbatim)** — use the bare name.
- Any other 2-character suffix starting with `,` is part of the name.
- Else if numeric arguments > 0: **PRG (derived)**.
- Else: **SEQ (derived)**.

**Disk filename**:

- Verbatim: the typed name (suffix stripped, **trailing dot kept**).
- SEQ (derived): `cur_project_name`.
- PRG (derived): `cur_project_name` + `.`.

**Save PRG end-address semantics** (save only).  Inclusive end,
matching the `AAAA-BBBB` display convention used everywhere else:

- `end == 0` → `size = block_size` (bare PRG `s`).
- `end <= start` → `size = end` (the argument is a byte count).
- `end > start` → `size = end - start + 1` (absolute inclusive end).

A size of 0 is `;?range`.

**Load semantics**:

- SEQ: start and end are unused; load into the editor via
  `ed_load_source(name)`.  With unsaved edits the `l` gate asks first
  ([§ Gating pattern](#gating-pattern)).
- PRG: `end` is the target address.  `end == 0` → the PRG header's
  load address.  Otherwise load to `end`.  The result line
  `; prg  AAAA-BBBB NNNb` shows where the file landed: AAAA its start,
  BBBB its last byte.

After a successful SEQ load or save the REPL prints `; Nl Mb` and
one `;!long LNN` per line wider than `LINE_MAX` columns (39; 79 on
m65 — `warn_long_lines`; the editor shows such lines with `>` in its
last column); a PRG load or
save prints `; prg AAAA-BBBB NNb` ([log.md](log.md)).  Both end with
the drive status row.

**Examples** (addresses are workspace addresses):

| Command | Mode | Disk name | Addresses |
|---------|------|-----------|-----------|
| `s "demo"`                  | SEQ derived | `demo`  | — (source) |
| `s "demo" $1000`            | PRG derived | `demo.` | start=cur_addr end=$1000 |
| `s "demo" $1000 $2000`      | PRG derived | `demo.` | start=$1000 end=$2000 |
| `s "demo" $1000 $100`       | PRG derived | `demo.` | start=$1000 size=$100 (fallback) |
| `s "demo,p"`                | PRG verbatim | `demo` | start=cur_addr size=block_size |
| `s "demo,s"`                | SEQ verbatim | `demo` | — |
| `s "demo.,p"`               | PRG verbatim | `demo.` | (dot preserved) |
| `s`                         | reuse project | derived | — (SEQ if no args) |
| `s $1000`                   | PRG, reuse project | `proj.` | start=cur_addr end=$1000 |
| `l "demo"`                  | SEQ derived | `demo`  | load into editor |
| `l "demo" 0`                | PRG derived | `demo.` | load at PRG header address |
| `l "demo" $2000`            | PRG derived | `demo.` | load to $2000 |
| `l "demo,p"`                | PRG verbatim | `demo` | load at PRG header |

**Auto-generated save line (from `a`)**: after a successful assembly
`seg_print_save` ([asm_src.md](asm_src.md)) prints
`AAAA:s "project" $EEEE`, where AAAA is the lowest emitted address
and EEEE the highest (inclusive) and `project` is
`cur_project_name` (`out` when empty).  The address argument makes
it a PRG save to `project.`; RETURN on the row saves the binary.

### Commands — Info / Utility

| Key   | Name    | Addressed | Example               | Notes                                |
|-------|---------|-----------|----------------------|--------------------------------------|
| `i`   | info    | —         | `i`                  | Show the memory map |
| `?`   | calc    | —         | `? $1000+20`         | Expression calculator: hex (`$xx` below 256, `$xxxx` from 256 on), decimal, and for values below 256 binary and signed.  Takes exactly one expression; rejects trailing garbage. |
| `k`   | kill    | —         | `k`                  | Delete the source buffer (gated) |
| `B`   | block   | —         | `B $40` or `B`       | Set block size (expression; 0 or an error keeps it); always shows `; blk=XXXX`.  Rejects trailing garbage. |
| `C`   | color   | —         | `C 6`, `C 06`, `C 0e6`, `C` | Set fg / bg+fg / border+bg+fg from 1–3 adjacent hex digits; bare = show.  See [§ `C`](#c--color-uppercase). |
| `u`   | cpu     | —         | `u 6502`, `u 6510`, `u 45gs02` | Set the CPU mode for `.`, `a` and the disassembler; always shows the modes. |
| `Q`   | quit    | —         | `Q`                  | Exit CSE (gated) |
| `R`   | reset   | —         | `R`                  | Warmstart (gated); ends any debug session, redraws the screen |
| `x`   | clear   | —         | `x`                  | Clear the screen |
| `;`   | comment | —         | `; note`             | No-op; clears the repeat command |

### Single-expression command contract

A subset of REPL commands take **exactly one complete expression
(or none) and nothing else**: `?`, `@`, `B`, `C`, `j`, `t`/`o`,
`+`/`-`, `b ADDR`, `d` (no arguments), `m` (after the optional
address and after the last edit byte).

For these commands the parser's
[expr.md § Partial-mode contract](expr.md#partial-mode-contract)
is a footgun: `expr_eval` returns success on `"1x"` with
`expr_val = 1` and `expr_ptr` at `'x'`, which is right for operand
callers (`$10,x`) but wrong for a single-expression command.  The
caller **must** enforce end of input after a successful parse:

1. Skip trailing whitespace (`$20`, `$A0`).
2. Verify the next byte is NUL or `;`.  Anything else is garbage.
3. On garbage: `;?syntax`, no state change.

`_require_eoi_or_err` does all three ([§ Command dispatch](#command-dispatch)
for its pop-trick and the one-jsr-deep rule).  Callers invoke it
**before** applying any state change (`cur_addr`, `block_size`,
theme colours), so garbage never leaves state half-modified.

**A bad expression is not an empty one.**  `try_expr` returns C=1 on
success; on C=0 it sets Z=1 for an empty argument and Z=0 for an
expression error (whose `;?expr …` row it has already printed).  A
command whose argument is optional acts on "empty" only: `j` with no
argument jumps to `cur_addr`, `+`/`-` with none move by
`block_size`, but `j nosuchsym` or `+ 1/0` print the error and do
nothing — no run, no move (`TestBadExpressionAborts`).  `@` and `B`
likewise change nothing on an error.  `t`/`o` are the exception
noted under [§ Commands — Debug / Trace](#commands--debug--trace).

Test contract (`tests/integration/test_repl.py`): parametrised
trailing-garbage rejection per command —
`TestCalculator::test_calc_rejects_trailing_garbage`,
`TestAddressCommands::test_seek_rejects_trailing_garbage`,
`TestBlockSize::test_block_rejects_trailing_garbage`,
`TestColorCommand::test_color_rejects_trailing_garbage` — plus
whitespace / comment acceptance cases.

### Gating pattern

Commands that change state the user may want to keep ask first, after
showing why:

1. **Warning rows** via `warn_if_unsaved` (`;!unsaved` when
   `ed_dirty` ≠ 0) and/or `warn_if_debug` (`;!debug` when
   `dbg_reason` ≠ 0), at LOG_WARN.  Both are no-ops otherwise.
2. **The prompt** via `query_user(A/X = stem)`, which prints
   `;!<stem>? y/n` at LOG_WARN and waits for a key.
3. `query_user` returns C=1 on `y` (proceed); any other key is C=0
   (cancel — the command changes nothing).

Gate matrix (the commands that use this pattern):

| Command | Warnings | Prompt | Yes-path |
|---------|----------|--------|----------|
| `k` | `;!unsaved` if dirty | `;!del src? y/n` (always) | `ed_new` |
| `Q` | `;!unsaved` if dirty | `;!quit? y/n` (always) | `state = ST_STOP` → `cse_exit_to_basic` |
| `R` | — | `;!init? y/n` (always) | `end_debug_body` (no-op without a session) + `cse_refresh` |
| `a` | `;!debug` | `;!asm? y/n` — only in a resumable session (`DBG_BRK`/`DBG_NMI`) | `warm_cont := 1`, `cse_end_debug` (the session ends, then `a` is replayed) |
| `j`, `g` | `;!debug` | `;!go? y/n` — only in a resumable session | as `a` |
| `l` (SEQ) | `;!unsaved` | `;!load? y/n` — only when the source is dirty | load |

Without a prompt the command runs directly: `a`/`j`/`g` outside a
resumable session, `l` with a clean buffer, every PRG `l`, every `s`.
The debug-session part of this matrix is
[debugger.md § `dbg_reason` × command matrix](debugger.md#dbg_reason--command-matrix) (owner).
`c`, `t`, `o` are not gated; they refuse with `;?no ctx` where the
session does not allow them.

Every gate's yes and no outcome (`k`, `Q`, `R`, the `j` and `a`
end-debug gates, the `l` dirty-source gate) is pinned by
`TestQueryUserOutcomes` in `tests/integration/test_kernel_transition.py`.

### Internal helpers

**`confirm_yn`** — `cursor_show`, `io_getc`, `cursor_hide`.  Returns
Z=1 if the key was `y`.  Clobbers A.

**`query_user(A/X = action stem)`** — prints `;!` + stem + `? y/n`
(`str_qynq`) at LOG_WARN, runs `confirm_yn`; returns A = the key,
C=1 on yes, C=0 on cancel (the prompt row cleared).  Each action
string is just the verb stem (`"del src"`, `"quit"`, `"init"`,
`"asm"`, `"go"`, `"load"`).

**`warn_if_unsaved`** / **`warn_if_debug`** — see above; tail-call
`log_warn`.

The dirty flag `ed_dirty` is owned by the editor ([editor.md](editor.md)).

### Command → userland dispatch

Execution commands (`j`, `g`, `t`, `o`, `c`) never RTI into user code
from inside their own `jsr` frame.  Each stages state and sets
`run_user_pending`, then returns to `main_loop`:

* `MODE_JUMP` — fresh start; the gate pushes a `brk_stub - 1`
  sentinel so the user's top-level RTS returns to `brk_stub`.  Set by
  `cmd_jmp` (`j`/`g`, after `brk_pc` := `cur_addr`), and by
  `set_run_mode` for the first `t`/`o`/`c` after a cold preview
  (consuming `cold_preview_done`).
* `MODE_RESUME` — resume from an existing break; the sentinel of the
  session's fresh start is still on the user stack.  Set by
  `set_run_mode` otherwise.

`main_loop` (main.s) then jumps to `return_to_userland` (MODE_JUMP) or
`restore_userland_state` (MODE_RESUME), both in
[debugger.md](debugger.md).  Control returns through the BRK / NMI
handler's longjmp to `main_loop_top`, not to the command.

`pre_userland_run` (shared by `j`/`g`/`t`/`o`) moves to a fresh row
and drains the keyboard buffer (`$C6` = 0) so the user's first CHROUT
and GETIN start clean; `c` drains the buffer itself.
`hygiene_after_userland` runs on every return from user code
([§ hygiene_after_userland](#hygiene_after_userland)).

**`cmd_step` (`t` / `o`)** does not loop.  With no session it shows
the cold preview (`; dbg at $PC`, registers, the instruction at
`cur_addr`), sets `dbg_reason` = DBG_BRK and `cold_preview_done` = 1,
and runs nothing.  In a resumable session it sets `step_state`,
skips a user `BRK` at `brk_pc` for `o`, disables the hit breakpoint
(`rp_dis_bp`), computes the next PC(s) with `step_next_pc`, refuses
with `;!range` (and `step_cleanup`) when a step BRK would land
outside the workspace (`bp_range_check_step`: `WORKSTART` ≤ addr <
the workspace's upper bound, or `brk_stub`), for a single step re-prints the
instruction about to run three rows up, arms the step BRKs
(`arm_step_bp`), sets `step_remaining` = count − 1 and returns via
`set_run_mode`.  Later iterations chain inside the BRK handler
([debugger.md § Single-step](debugger.md)); the kernel stack use is
the same for `t 100` as for `t 1`.

`bp_range_check` (the `b` gate) is the strict form: `WORKSTART` ≤
addr < the workspace's upper bound, the same workspace the
assembler's emit gate uses — `$0800`–`buf_base` on c64, `$2000`–`$C000`
on m65 ([platform_layer.md § Constants](../platform_layer.md#constants)).
On m65 the upper bound is page-aligned and fixed, so both gates
compare the high byte only (`.ifdef` bodies).

### Splash screen

At startup main.s prints the version row, then `cmd_info` in splash
mode (C=1), then the manual link ([main.md § Layer 1](main.md#layer-1-_main-cold-init-one-time-setup), step 14).
Splash mode prints only the free rows:

    ; zp   0002-007f   126b free
    ; low  02a7-02ff    89b free
    ; low  0334-03ff   204b free
    ; work 0800-XXXX NNNNNb free

The work row ends at `buf_base - 1` and follows the build's runtime
start and the loaded source.

On m65 the splash's free rows are the user's regions with their
banks — the two free stretches of base page 0 first (in 80 × 50
without the bank-4 row: the screen is there), from row height − 12:

    ; zp   0.000a-008f   134b free
    ; zp   0.00fb-00ff     5b free
    ; low  0.1600-1eff  2304b free
    ; work 0.2000-bfff 40960b free
    ; ext  1.2000-f6ff 55040b free
    ; ext  4.0000-ffff 65536b free
    ; ext  5.0000-ffff 65536b free

### `B` — Block size (uppercase)

`B` sets the 16-bit block size used by `m`, `d`, `+`/`-` and a bare
PRG `s`.  Default: `$0010` (16 bytes = 2 dump rows).  The argument is
an expression (bare digits are decimal):

    B $40    set to 64 bytes (8 dump rows)
    B 192    set to 192 bytes
    B        show the current block size

### Directory listing

`$` lists the directory of the current device, followed by the drive
status row.  A decimal device number after `$` (optional space) in
4–30 sets `cur_device` permanently first; any other number keeps the
current device.  There are no drive commands.  Tests: `TestDirDevice`
(`tests/integration/test_repl_disk.py`).

### Tab width (build-time constant)

The tab width is a **build-time constant** (`-DTAB_WIDTH=N`, default
8, a power of two — [build_system.md](../build_system.md)); there is
no runtime command for it.  Baking it in keeps the column arithmetic
a mask and matches the C64-era convention (Turbo Assembler,
MasterSeka, Relaunch64 all default to 8).  `warn_long_lines` uses the
same constant.

### `i` — Memory map

`i` prints the whole 64 K map; free regions carry a byte count and
`free`:

    ; cpu  0000-0001 port
    ; zp   0002-007f   126b free
    ; sys  0080-00ff kernal
    ; stk  0100-01ff stack
    ; sys  0200-02a6 kernal
    ; low  02a7-02ff    89b free
    ; sys  0300-0333 kernal
    ; low  0334-03ff   204b free
    ; scr  0400-07ff scr
    ; work 0800-XXXX NNNNNb free
    ; src  XXXX-XXXX Nl NNb          (only when source is loaded)
    ; cse  XXXX-cfff cse
    ; io   d000-dfff io
    ; cse  e000-f8d9 banked
    ; rom  f8da-ffff kernal

The work row spans $0800 to `buf_base - 1`; the `src` row is the
source text (`src_bot`..`src_top - 1`, with `ed_total_lines`); the
first `cse` row runs from `cse_start` (the runtime start) to
`cse_end - 1`.  The `zp`, `low` and `work` rows are computed in
`cmd_info`; the fixed rows come from the `info_tbl_*` tables in
repl.s.  The banked row's bounds ($E000–$F8D9) are fixed in the table
and do not follow the KERNAL-RAM layout
([memory_design.md § Banked layout](../memory_design.md#banked-layout-e000ffff)):
the `rom` row ($F8DA–$FFFF, tagged `kernal`) also covers CSE's
cold-init ZP snapshot (`COLD_ZP`, $F8DA–$F958, main.s) in the RAM
under the ROM.

Contract pinned by `TestInfoFullMode`: the rows run in address
order and cover `$0000`–`$FFFF` without gap or overlap; the `src`
row appears only when source is loaded.

**On m65** ([platform_layer.md § Info map](../platform_layer.md#info-map))
the rows are [memory_design.md § Memory Map — m65](../memory_design.md#memory-map--m65-mega65-mode)'s
bank table, in bank order, each range written `b.aaaa-bbbb`:

    ; zp   0.000a-008f   134b free       BASIC 65's base page
    ; zp   0.00fb-00ff     5b free
    ; low  0.1600-1eff  2304b free
    ; cse  0.1f00-1fff base             CSE's base page and the stub
    ; work 0.2000-bfff 40960b free       the program region, workstart-workend
    ; ext  1.2000-f6ff 55040b free       above the DOS buffers
    ; src  2.XXXX-XXXX Nl NNb            the source text (only when loaded)
    ; cse  3.2000-7fff code              CODE + RODATA
    ; cse  3.8000-bfff data              KDATA, BSS and the homes
    ; ext  4.0000-ffff 65536b free       not in 80 x 50 (its screen)
    ; ext  5.0000-ffff 65536b free

The fixed rows are the `info_m65` table (9 bytes a row: tag, lo, hi,
desc — 0 for a free row, whose size is computed — and the bank),
written by `info_m65_rows`; a whole bank's size is `65536b`.  The
`src` row is the shared dynamic row with `info_bank` = `BANK_SRC`.
The map is not a cover of the 28-bit space: the KERNAL's cells (base
page `$00–$09` and `$90–$FA`, `0.0200–0.15FF`) and the KERNAL's and
the ROM's banks are not listed; the `zp` rows are the program's part
of base page 0 ([userland_contract.md § 3 On m65](../userland_contract.md#on-m65)).  Tests: `tests/integration/test_m65_repl.py`.

### Banks (m65)

**Status (slice 3, [TODO § Slice 3 — banks](../TODO.md#slice-3--banks)):**
F1–F3 have landed: both address forms, the prompt, `@`, `m`, `.`,
`d`, `+`, `-`, the write refusal, the CPU space through the program's
bank state, `r`'s and `M`'s map, and far starts — `j` with a flat
argument or at a flat current address, a cold `t` / `o` at one — work
as stated.  **Delta, not yet built:** flat breakpoints are F4's (until
then a breakpoint is patched through the map in force at the patch);
`.org H.AAAA` and `g` in the bank `main` was assembled to are F5's —
until then `g` starts `main` as a CPU address.

On m65 an address is in one of two spaces, told apart by a dot
([glossary.md](../glossary.md), *CPU address*, *flat address*):

| Form | Space | What it reaches |
|---|---|---|
| `AAAA` | **CPU address** | what the program's CPU sees at that 16-bit address: read through the program's bank state — its `MAP`, CPU port and `$D030` ([platform_layer.md § Far memory](../platform_layer.md#far-memory)) |
| `H.AAAA` | **flat address** | physical memory, around `MAP`: one to four hex digits (bits 16–27 of the 28-bit address, megabyte and bank; a fourth digit can only be 0), a dot, four hex digits — `4.2000`, `1.f6ff`, `800.0000`, `ffd.3000` |

There is no mode command.  The current address carries its space;
the prompt shows it (`2000:` or `4.2000:`), and every row a command
prints carries the same form and re-executes in it.

**Entering a space.**  `@ 4.2000` makes the current address flat;
`@ $2000`, `@ label` or a break (the panel sets the current address
to the PC, a CPU address) make it a CPU address.  A row's prefix sets
the space with the address: `4.2000:m` and `2000:m` are different
commands.

**Writing a flat address.**  At a line's start the prefix is
recognised by its shape — hex digits, a dot, four hex digits, a
colon.  In an argument a flat literal begins with a digit `0`–`9`
(`0ffd.3000`), so that a dotted label (`a.beef`) stays a label; it is
a literal, not an expression, until the evaluator knows 32 bits (F5),
and it is read before the evaluator sees the argument.  CSE prints a
flat address in lower case with the fewest digits before the dot.

**The commands:**

| Command | CPU space | Flat space |
|---|---|---|
| `m` (dump, edit), `.` (poke) | the bytes the program would read and write there; at `$00` / `$01` the program's port ([§ User-ZP view](#user-zp-view)) | the physical bytes; `0.0000` / `0.0001` are the RAM beneath the port |
| `.` (assemble) | at the address, as today | the bytes go to the flat address; the instruction's own address — a branch's base, `*` — is the low word, the address the code has when its bank is started ([§ Far starts](#far-starts)) |
| `d` | through the bank state | the physical bytes; a branch target is shown in the low word |
| `+`, `-`, and a row's advance | wraps from `$FFFF` to `$0000`; the translation is made again at every 8 K block edge | carries into the next bank (`4.ffff` → `5.0000`) |
| `j`, `g`, `t`, `o` | start or continue the program at the address, in its map | a far start ([§ Far starts](#far-starts)) |
| `b` | a breakpoint at the byte the address resolves to now | a breakpoint at that byte (F4: [breakpoints.md](breakpoints.md)) |

**A write into CSE's or the KERNAL's banks is refused.**  `m`, `.`
and the assembler do not write a byte whose flat address is in
`2.0000–3.FFFF` — in either space (`$E000` in the standard map is
`3.E000`): CSE keeps those banks writable, and they hold the KERNAL,
CSE and the source text.  The row answers `;?range`.

#### Far starts

A flat address given to `j` (or the current flat address for a bare
`j`, a cold `t` / `o`, and `g` after an assembly to a bank) starts the
program **as `JSRFAR` would start it**
([userland_contract.md § 5.6](../userland_contract.md#56-on-m65-memory-maps-and-kernal-calls)):
a fresh start with `$2000–$7FFF` mapped to the bank (`MAP` X = `$E0`
with the bank in its low nibble, A = 0, Y = 0, Z = `$83`), the same
four bytes in the KERNAL's map record, and PC the address's low word.
The program may use the whole KERNAL API from its first instruction;
its `RTS` returns to CSE as any run's does.

| Flat address | `j` |
|---|---|
| `1.2000–1.7FFF`, `4.2000–4.7FFF`, `5.2000–5.7FFF` | a far start |
| `0.AAAA` | the plain start at `$AAAA` (`j $AAAA`) |
| anything else — outside `$2000–$7FFF`, banks 2–3, a megabyte | `;?range` |

The window is `JSRFAR`'s (book I-31), and not CSE's choice: code runs
at the 16-bit address it was assembled for, block 0 stays bank 0 for
the KERNAL and CSE's page, and the upper half's one offset is the
KERNAL's.  After a far start the program's map *is* the far map, so
a break shows a CPU address (`2010:`) and `m`, `d` and the steps see
the bank through it.

**The CPU space.**  A CPU address reads and
writes what the program's CPU would, through its bank state
([mem.md § far_user](mem.md#far_user-far_user_w-m65-only)): `zp_stage_prep`
stages every byte of a CPU-space row through `far_user` — the user-ZP
view at `$00` / `$01` among them — and `zp_poke` writes every byte
through `far_user_w`, so a row that crosses a 4 K page edge, or wraps
from `$FFFF` to `$0000`, shows and edits what the program would.  A
write to a page whose ROM the program sees goes to the RAM beneath,
as the CPU's would: `m c000 00` writes `0.C000` (the RAM under the
interface ROM), and the row it prints shows the ROM still.  The write
guard applies to the translated address (`m e000 00`, the KERNAL
through `MAP`, is `;?range`).  `.`'s assembly writes through
`asm_out`, translated once for its first byte: an instruction across
a page edge is written where its first byte translates (a caveat,
§ Caveats).

#### The map in `r` and `M`

`r` shows the two halves of the program's `MAP` after the flags, as
the Matrix Mode monitor names them — `ml:XXXX` (MAPLO: X in the high
byte, A in the low) and `mh:XXXX` (MAPHI: Z, Y):

    r pc:2010 a:00 x:00 y:00 z:00 b:00 s:ed nv-Bdizc ml:e400 mh:8300

In 40 columns they are on the second row, `r z:XX b:XX ml:XXXX
mh:XXXX`.  Both are fields like the others: an edit changes the
program's bank state — what the next resume installs, and what the
CPU space shows from then on.

`M` (upper case) prints the program's map, one row for every run of
8 K blocks with the same translation, and a last row with the
megabyte selectors and `$D030` that re-executes as an edit:

    2010:M
    ; map  0000-1fff 0.0000
    ; map  2000-7fff 4.2000 mapped
    ; map  8000-bfff 0.8000
    ; map  c000-cfff 2.c000 rom
    ; map  d000-dfff ffd.3000 io
    ; map  e000-ffff 3.e000 mapped
    M mb:0000 d030:64

**Rows in 40 columns.**  A flat prefix is two to five columns wider
than `AAAA:`.  A flat `m` row in 40 columns shows its 8 bytes without
the ASCII column (`4.2000:m HH … HH`, at most 36 columns); a flat `d`
row with a one-digit bank is 40 columns at most, and with a wider
prefix it is clipped at the right edge — the mnemonic and operand
stay readable for banks 0–9 and A–F, the cases a program uses
(TODO, O-F-1, proposed).  In 80 columns every row fits: the widest,
an `m` row with a four-digit prefix, is 76 columns.

### `C` — Color (uppercase)

Takes 1, 2 or 3 adjacent hex digits and applies them at once
(`restore_colors`: border, background, colour RAM); anything after
the digits other than spaces / `;` is `;?syntax` and changes nothing.
Every form ends with `; color: BGF` (border, background, foreground).
Tests: `TestColorApply`, `TestColorCommand`.

    C 6          text = blue
    C 06         background = black, text = blue
    C 0e6        border = black, background = light blue, text = blue
    C            show the current colours

### `u` — CPU mode

    u 6502       standard NMOS 6502                     every build
    u 6510       6510 (with illegal opcodes)            6510 build
    u 4510       CSG 4510 (65CE02 set + MAP/EOM)        m65
    u 45gs02     45GS02 (4510 + Q and far forms)        m65

`u` accepts only the modes its build offers, ignores anything else,
and always prints them, the active one marked `*`
(`; cpu: 6502* 6510`).  The modes are the build's CPU set
([build_system.md § Builds and CPU sets](../build_system.md#builds-and-cpu-sets)):
the 6510 build offers 6502 and 6510; the m65 build 6502, 4510 and
45gs02 (`; cpu: 6502 4510 45gs02*`).
`u` selects the assembler's CPU and the disassembler's view; the
debugger's step follows the real CPU ([debugger.md § Next-PC](debugger.md#next-pc)).

### Free / reserved keys

    e   reserved — editor mode (source buffer)
    p   reserved — print / evaluate
    v   reserved — visual mode
    f h n q w y z    free
    all SHIFTed letters except B C Q R    free

### Emitters

Single-line output routines, called by both edit-mode and block-mode
paths; each starts at column 0 and ends with `io_clear_eol`.

- `emit_dot(rp_addr)` — `AAAA:.  HH HH HH  mne opr`, returns the
  instruction length in A.  On m65 five byte columns, in every screen
  mode: the mnemonic at
  column 24, a row 38 columns at most (`lda ($12,sp),y`), so it fits
  40 columns.
- `emit_mem(rp_addr, A = columns 1–8)` — `AAAA:m HH … HH;cccccccc`
  (characters $20–$7E as themselves, others `.`).
- `emit_reg()` — `r pc:xxxx a:xx x:xx y:xx s:xx nv-bdizc` (set flags
  uppercase); on m65 in 80 columns `r pc:xxxx a:xx x:xx y:xx z:xx
  b:xx s:xx nv-bdizc`, in 40 columns that c64 line and a second row
  `r z:xx b:xx` ([debugger.md § `r`](debugger.md#r)).  The break panel
  is a row taller in m65's 40 columns, and `cmd_step`'s re-print moves
  up by the panel's height, not by 3.

## Caveats

- `exec_line` modifies `cur_addr` as a side effect of the `AAAA:`
  prefix.
- **m65, `.` across a 4 K page edge:** in CPU space `.`'s assembly
  writes through `asm_out`, translated once for the instruction's
  first byte; an instruction whose bytes cross a page edge is written
  where that first byte translates (`m` and the `.` pokes translate
  every byte, § Banks).
- **Expression arguments:** `@`, `j`, `+`, `-`, `b`, `s`, `l`, `t`,
  `o`, `B` take full expressions (`$hex`, decimal, `%binary`,
  symbols, operators).  Bare digits are decimal — hex needs `$`, and
  hex digits are lowercase ([expr.md](expr.md)).  The `AAAA:` prefix,
  `m`'s address, `.`/`m` byte pairs, `r` fields and `C` digits are
  plain hex.
