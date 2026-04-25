# repl.s — REPL Command Interface (the kernel's ISR body)

**Template:** [module](../templates/module.md)

REPL command interpreter and screen output.  Hex parsing helpers
(`_hex_val`, `_is_hex`, `_hex_val_to_char`) are local to repl.s.

The REPL is the body of CSE's ISR-style kernel.  `main_loop` resets
SP to a known value at the top of each iteration, calls `show_prompt`
/ `read_line` / `exec_line`, then loops.  When `exec_line` dispatches
an execution command (`j`, `g`, `c`, `t`, `o`), the handler eventually
calls `return_to_userland` (debugger.s) which RTIs to user code; control
returns via `cse_brk_handler`'s longjmp back to `main_loop_top`.  See
[design_cse_as_kernel.md](../design_cse_as_kernel.md) for the design
framing.

## Owned files

| File | Role |
|------|------|
| [`src/repl.s`](../../src/repl.s) | implementation (assembly) |

## Interface

- `exec_line()` — parse current screen line, dispatch command
- `read_line()` — capture screen row at io_cy into line_buf (PETSCII)
- `show_prompt()` — write `AAAA:` at cursor using cur_addr

**State:**
- `cur_addr` (uint16) — current address, default $1000
- `cur_device` (uint8) — disk device number, default 8
- `cur_project_name` (char[]) — stem of the current project (without
  trailing type marker or dot); used to derive disk filenames for
  `l` and `s`.  Default `"out"` when empty.
- `last_cmd` (char) — last command (for RETURN repeat)
- `block_size` (uint16) — block size for m/d/f/>/+/-, default $10

**Logging API** — moved to [log.md](log.md) as of Phase 21.  repl.s
still owns two local line-ending wrappers that are specific to the
prompt-row discipline:

- `log_err_eol(A/X)` — newline + `log_err` + clear (error-only exits)
- `log_close_eol()` — `log_close` + clear (multi-part exits)

Both wrap the core `log_*` primitives from `log.s`.  Other modules
(`disk.s`, `editor.s`, `asm_src.s`, `main.s`) import directly from
`log.s` — no longer from here.

**Range/info line family** — moved to [log.md](log.md) as of Phase 21
(`seg_line`, `prg_line`, `free_line`).  repl.s imports them for
`cmd_info` and the PRG save/load summary lines.

### Memory

**BSS (107 bytes):**

| Variable | Size | Purpose |
|----------|------|---------|
| `cur_addr` | 2 | Current memory address (REPL prompt) |
| `last_cmd` | 1 | Last executed command byte |
| `block_size` | 2 | Block size for `+`/`-` commands |
| `disk_name_buf` | 18 | Composed disk filename (FILENAME_MAX + 2) |
| `_verbatim_type` | 1 | 0 / 's' / 'p' from strip_and_classify |
| `_arg_count` | 1 | Numeric argument count from last parse (0–2) |
| `line_buf` | 42 | Screen line capture buffer |
| `dot_asm_buf` | 24 | Inline assembler instruction buffer |
| `rp_next_hi` | 2 | cmd_step: next-instruction hi pair (lo lives in zp.s) |
| `rp_opc` | 1 | cmd_step: saved opcode |
| `rp_dis_bp` | 1 | cmd_step: disabled breakpoint slot |
| `rp_hexbuf` | 3 | Hex byte parse buffer |
| `cold_preview_done` | 1 | cmd_step cold-preview marker |
| `zp_stage_buf` | 8 | User-ZP staging buffer for `m` dump and `.` disasm (see [User-ZP view](#user-zp-view)) |

The 16-bit scratch pointers `rp_addr`, `rp_save`, `rp_save2`, `rp_cnt`,
`rp_next_lo` and the byte `cur_device`, plus the project-name string
`cur_project_name`, were migrated to zp.s in Phase 21.1.  The decimal
output buffer `fbuf` was retired when log.s absorbed the formatting.

**Depends on:** asm_src (`a`), editor (`n`/`l`/`s`), disk (`l`/`s`/`$`),
debugger (`b`/`c`/`t`/`o`), asm_line (`.`), dasm (`d`), expr (`?`),
symtab (`?` lookup), screen, log (logging primitives), asm_err
(expr_error_str path), mem, cse_io, oplen_tbl, strings, zp (shared
flags: `state`, `in_userland`, `warm_cont`, `dbg_reason`, `ed_dirty`,
`stop_cooldown`)

## Design

### Prompting loop

The main loop owns the prompt.  Command handlers never write it.

1. Assume the cursor is on the line where the prompt is to appear.
2. Write `AAAA:` at column 0, where `AAAA` is `cur_addr`.
3. Leave the cursor at column 5 for user input.
4. Dispatch keystrokes to the keystroke handler; wait for RETURN.
5. `read_line` — capture the screen row into `line_buf`.
6. If the line begins with `AAAA:`, write `AAAA` to `cur_addr` and
   consume five characters from the line.
7. Seek to the first non-whitespace character; mark its column as
   *start*.  Seek to the first `;` or end-of-line; mark that column
   as *end*.
8. If *start* = *end* and column 6 holds `;`: advance to the next
   line, clear it, go to 1.
9. If *start* = *end* (empty, no `;`): dispatch command repetition
   (`last_cmd`), go to 1.
10. Otherwise dispatch the line from *start* to *end* to the command
    parser.
11. Go to 1.

`show_prompt` writes `AAAA:` and positions the cursor — nothing
else.  Whether the prompt line is cleared before `show_prompt`
runs is the responsibility of the previous command handler
(principle 5).

### Command handler principles

1. **The screen is the command buffer.**  Every screen line is
   executable.  The parser reads from column 0 to `;` or end-of-line.
   The screen operates in lowercase mode (VICII charset 2).

2. **Commands are case-sensitive single characters.**  `a`–`z` and
   `A`–`Z` are distinct command keys — 52 letter slots available.
   Lowercase is the default; uppercase requires SHIFT.  `read_line`
   maps lowercase screen codes ($01–$1A) to PETSCII $41–$5A and
   uppercase screen codes ($41–$5A) to PETSCII $C1–$DA.

3. **Commands own their output lines.**  Every line a handler writes
   must be `clear_eol`'d — no leftover characters from previous
   content.

4. **Commands own their prompt line.**  In block-edit mode (`.` with
   args, `m` with hex bytes), the handler rewrites its prompt line to
   reflect the edited state.  What's on screen is the truth.

5. **Commands own the next line's clearing.**  Before returning,
   handlers clear the prompt line (`clear_eol`) so the loop's
   `show_prompt` writes `AAAA:` onto a clean line.  Exception: `.`
   and `m` in edit mode leave the next line intact — this is the
   block-edit workflow (cursor up, modify, re-RETURN).  `show_prompt`
   itself never clears.

6. **Non-executable output starts with `;`.**  Info text, status
   lines, and error messages are prefaced with `;` so they're inert
   if the user hits RETURN on them.

7. **Executable output without a `cur_addr` relation omits `AAAA:`.**
   If an output line is meant to be re-executable but doesn't
   correspond to a sequential address, it has no address prefix.

8. **Auto-advance and repeat.**  Block-paging commands (`.`, `m`, `d`)
   update `cur_addr` to the continuation address.  RETURN on an empty
   prompt repeats `last_cmd` at the new `cur_addr`, always without
   args (dump/disassemble mode).  This supports paging:
   `d`‹RETURN›‹RETURN›‹RETURN› to scroll through disassembly, or
   `.`‹RETURN›‹RETURN› to step one instruction at a time.
   `last_cmd` stores only the command character — no args buffer.

9. **Block commands are thin loops over single-line emitters.**  `d`
   calls `emit_dot` repeatedly; `m` (dump) calls `emit_mem`
   repeatedly.  The emitter is the unit of work.

10. **`;` is a no-op command.**  Screen output accumulates as a
    readable, scrollable log.

11. **No spurious blank lines.**  Every row a command emits carries
    content — a tag, a dump line, a disassembly, a register row, a
    prompt.  Commands must never leave a fully-blank row (all `$20`)
    between their first output row and the following prompt.
    Screen real estate is scarce (25 rows, minus splash / reserved
    rows); blank rows that serve no separator purpose are a bug.

    Enforced by a single smoke test (`TestOutputHygiene`) that runs
    a representative slice of commands and fails if any blank row
    appears in the output region.  Individual command output layout
    (row counts, cursor-up arithmetic, panel heights) is verified
    on real hardware / VICE rather than pinned by unit contracts.

### Error reporting

Errors use the prefix `;?` — the `;` makes the line non-executable
(principle 5), the `?` signals an error.  Examples:

    ;?asm           assembly error
    ;?cmd           unknown command
    ;?name          missing filename
    ;?range         invalid address range

The `?` expression calculator is not confused by this because `;`
terminates parsing before `?` is reached.

### Block-edit workflow

The block-edit workflow is how the user inspects and modifies code or
data in bulk.  It has two phases: **dump** and **edit**.

**Dump phase** — `d` and `m` (without args) are block commands.  They
operate on `block_size` bytes and output a screenful of executable
lines:

- `d` outputs `AAAA:. HH HH HH  MNE OPR` lines (via `emit_dot`)
- `m` outputs `AAAA:m HH HH ... cccccccc` lines (via `emit_mem`)

Each output line is a valid command.  The block command clears the
final prompt line and stops.  The screen is now a buffer of editable
commands.

**Edit phase** — the user cursors to any line on screen:

- Modify hex bytes in an `m` line, press RETURN → `m` re-executes
  with the edited bytes, rewrites the line to reflect the new memory
  state, advances `cur_addr`.
- Modify the mnemonic or operand in a `.` line, press RETURN → `.`
  re-assembles, rewrites the line with the new disassembly, advances.

When `.` or `m` are called **with arguments** (the user edited a
dump line and pressed RETURN), they enter block-edit mode:
1. Execute the edit (assemble instruction / write bytes)
2. Rewrite their own prompt line to reflect the new state (principle 3)
3. Do **not** clear the next line (principle 5 exception)
4. Advance `cur_addr` to the continuation address (principle 8)

The handler returns.  The prompting loop writes `AAAA:` over the
first five columns of the trailing line (updating the address
prefix) without clearing the rest — the existing dump content
from column 5 onward remains intact and editable.

Without arguments, these same commands are in dump mode (`.` disassembles
one line; `m` dumps `block_size` bytes) and clear the prompt line
normally.

The user can continue editing the next line or cursor back to edit
another line.  This creates a fluid cycle: dump → edit → re-execute
→ advance, all without leaving the screen.

### The `.` command in detail

The `.` handler has three modes:

1. **With hex byte args that differ from memory:** write the bytes to
   memory at `cur_addr`.
2. **With hex byte args that match memory:** pass the remaining text
   (mnemonic + operand) to the line assembler.
3. **Without args:** disassemble one instruction at `cur_addr`.

**Expression support:** In mode 2, the operand is evaluated through
`_expr_eval` before being passed to the line assembler.  This means
full expressions work in the `.` command:

    1000:. lda screen+$20     ; label + arithmetic
    1000:. sta <addr           ; lo byte operator
    1000:. ldx #cols-1         ; constant expression

Symbols and labels from the last source assembly (`a` command) are
available, since the symbol table heap persists between assemblies.

The operand is evaluated to a numeric value, formatted as `$XX` or
`$XXXX` (based on `expr_wide`), and the prefix/suffix characters
(`#`, `(`, `,x`, `)`, etc.) are preserved around it.  The formatted
string is then passed to `_asm_line` which handles only hex operands.

In all three cases, the handler finishes by disassembling the
instruction at `cur_addr` and rewriting the prompt line with the
result.  What's on screen always reflects the actual memory state.

**User-ZP redirect (mode 1 and 3).**  See [User-ZP view](#user-zp-view)
below.  When `cur_addr` is in the save range, mode 1 (hex poke)
writes to `userland_zp_buf` and mode 3 (disasm) reads from
`userland_zp_buf` — so the `.` line always shows the user's ZP
image and edits survive `c` (continue).  Mode 2 (inline mnemonic
assembly into ZP) is intentionally not redirected: it writes
through the asm_line pipeline to live memory.  If the user wants
to put a byte into user ZP, they use the hex-poke form.

### User-ZP view

ZP locations in the save range `[ZP_SAVE_LO, ZP_SAVE_LO +
ZP_SAVE_LEN)` (today $00–$7F, exported from [mem.s](../../src/mem.s))
have two relevant images:

- **Live ZP** — CSE's own ZP (restored on userland exit via
  `save_userland_zp` + `restore_kernel_zp`).
- **Saved user ZP** — `userland_zp_buf` (128 B BSS, owned by
  `mem.s`), seeded by `dbg_init` at cold boot ($00=$2F, $01=$36,
  rest zero) and refreshed on every userland → kernel transition.
  On `c`, the debugger restores this image back to live ZP before
  RTI.

The `m` and `.` commands **always** read from and write to the
saved image for addresses in the save range — CSE's own live ZP
within that range is an implementation detail and is never shown
to or accepted from the REPL user.  Both reads and writes go
through the redirect:

| Command | Path | Redirect |
|---------|------|----------|
| `m` dump | read 8 bytes for display | yes — stages from `userland_zp_buf` via `zp_stage_buf` |
| `m` edit | `sta (addr)` per edited byte | yes — writes land in `userland_zp_buf` |
| `.` disasm (no args) | read up to 3 bytes for the disassembler | yes — stages into `zp_stage_buf`, `dasm_insn` reads from there |
| `.` hex poke | `sta (addr)` for each parsed byte | yes — writes land in `userland_zp_buf` |
| `.` mnemonic | asm_line emits via `asm_pc` | **no** — goes to live memory (documented; see mode 2 above) |

The redirect gate: effective address in `[ZP_SAVE_LO, ZP_SAVE_LO
+ ZP_SAVE_LEN)` (currently $00–$7F).  Outside that range, reads
and writes go to live memory — $80–$FF is KERNAL territory and
not mirrored in `userland_zp_buf`, and addresses past page 0 are
real workspace.

Implementation: the `zp_stage_prep` helper in repl.s fills the
8-byte `zp_stage_buf` from (rp_ptr2), mixing `userland_zp_buf`
bytes for in-range offsets with live `(rp_ptr2),y` reads for the
rest, and re-points rp_ptr2 at the staged buffer so downstream
consumers (`dasm_insn`, `emit_hex_cols`, the compare loop in
cmd_dot) read the view uniformly.  The `zp_poke` helper mirrors
this for single-byte writes: given A=byte, rp_ptr2+Y=effective
address, it stores into `userland_zp_buf[addr - ZP_SAVE_LO]` for
in-range effective addresses, else to live `(rp_ptr2),y`.  Both
live in repl.s and are used only there — other modules read live
ZP directly through their own `(ptr),y` indirections.

Range-gating assumes the save range lies entirely within page 0
(`ZP_SAVE_LO + ZP_SAVE_LEN ≤ $100`) and `ZP_SAVE_LO = 0` (lower
bound is trivially satisfied and elided).  If either assumption
changes, the helpers need an explicit lower-bound check.

### Line format and address handling

`AAAA:cmd [args]` or bare `cmd [args]`.  `;` terminates parsing
(inline comment).

If the line begins with `AAAA:`, the parser sets `cur_addr` to AAAA
before dispatching the command.  Commands operate on `cur_addr`, which
they may override with an optional address argument of their own.
After execution, commands update `cur_addr` to point past all the
bytes they consumed.

### Line editor rules

The REPL's line editor operates within the 40-column screen:

1. **Cursor movement stays within the screen.**  Left/right/up/down
   move within the visible 40×25 area.  No wrapping between lines,
   no scrolling.
2. **Character insertion fills up to column 38.**  Column 39 is
   reserved for the cursor.  Overflow shifts characters out at the
   right edge.
3. **DEL (backspace) left-deletes.**  Content right of the cursor
   shifts left; a space shifts in from the right edge.  Stops at
   start of line.  If column 5 contains `:` (a clean prompt line),
   stops at column 6 to protect the `AAAA:` prefix.  Cursor
   movement can still position past the `:` for on-screen edits.
4. **INS right-shifts.**  Content at and right of the cursor shifts
   right; a space opens at the cursor.  Overflow at column 38 is
   lost.

### Line formats (40 columns)

    AAAA:. HH HH HH  MNEMONIC OPERAND     asm / disasm
    AAAA:m HH HH HH HH HH HH HH HH cccc hex dump / edit
    r pc:XXXX a:XX x:XX y:XX s:XX Nv-bDizc CPU registers (UC=set)

### Commands — Memory

| Key | Name     | Addressed | Example                     | Notes                                      |
|-----|----------|-----------|-----------------------------|----------------------------------------------|
| `m` | memory   | yes       | `1000:m` dump, `1000:m A9 00...` edit | Bare = dump `B` bytes; with hex = edit.  Rejects trailing garbage after the (optional) ADDR or after the last edit byte (§ Single-expression command contract). |

### Commands — Assembly / Disassembly

| Key | Name       | Addressed | Example              | Notes                                        |
|-----|------------|-----------|-----------------------|----------------------------------------------|
| `.` | asm/disasm | yes       | `1000:. lda #$00`    | Single instruction; full expressions in operands. See *Input-shape matrix* below. |
| `d` | disassemble| yes       | `1000:d`              | Disassemble `b` bytes (block mode).  Takes no inline args; rejects trailing content (§ Single-expression command contract). |
| `a` | assemble   | —         | `a`                   | Assemble source buffer (two-pass)            |

#### `.` command input-shape matrix

The dot command has three valid input shapes plus an explicit
rejection cell.  Testing matrix:
`tests/integration/test_repl.py::TestDotHexEdit`.

| After the `.` (+ whitespace) | Behaviour | Example |
|---|---|---|
| Nothing (`NUL`) | Silent redisplay of current line | `.` |
| `';'` comment | Silent redisplay | `. ; note` |
| Two hex digits + space/NUL (1–3 pairs) | Hex-byte poke at `cur_addr` | `. a9 42` |
| Letter `a`–`z` (mnemonic start) | Mnemonic assemble via `dot_assemble` | `. lda #$00` |
| **Anything else** | **Syntax error** (`;?syntax`) | `. .`, `. ,`, `. $`, `. 123` |

Pre-fix (Escape Analysis 2026-04-20), the "anything else" cell
silently fell through to the redisplay path — `. .` emitted nothing
and produced no error.  The `@try_mne` gate in `cmd_dot` now
distinguishes "nothing after `.`" (valid silent redisplay) from
"non-letter garbage" (syntax error).

### Commands — Execution

| Key | Name | Addressed | Example          | Notes                                      |
|-----|------|-----------|------------------|--------------------------------------------|
| `j` | jump | yes       | `1000:j` or `j main` | Start execution at expression. Patches breakpoints, enters debugger loop. Shows registers on break/RTS.  When an expression is provided, rejects trailing garbage (§ Single-expression command contract). |
| `g` | go   | —         | `g`              | Shorthand for `j main`. Falls back to `j cur_addr` if `main` undefined. |
| `c` | continue | —    | `c`              | Continue from last break (BRK/NMI). Error if no active break context. |

### Commands — Debug / Trace

| Key | Name      | Addressed | Example         | Notes                                    |
|-----|-----------|-----------|-----------------|------------------------------------------|
| `r` | registers | —         | `r` or `r a:05...` | View / edit CPU registers             |
| `b` | breakpoint| —         | `b $1020`, `b main`, `b -1`, `b *` | Set (expr), delete, list. See [debugger.md](debugger.md).  The `b ADDR` set-form rejects trailing garbage (§ Single-expression command contract). |
| `t` | trace     | —         | `t` or `t 5`    | Step-into EXPR instructions (bare = single step). Enters subroutines. Rejects trailing garbage (§ Single-expression command contract). |
| `o` | trace over| —         | `o` or `o 5`    | Step-over EXPR instructions (bare = single step). JSR runs to completion. Rejects trailing garbage (§ Single-expression command contract). |

### Commands — Navigation

| Key | Name    | Addressed | Example       | Notes                                    |
|-----|---------|-----------|---------------|------------------------------------------|
| `@` | seek    | —         | `@ $C000` or `@ main` | Set `cur_addr` to expression; bare = no-op.  Rejects trailing non-whitespace / non-comment content as a syntax error (§ Single-expression command contract). |
| `B` | block   | —         | `B $40`       | Set block size (expression); bare = show (uppercase).  Rejects trailing garbage (§ Single-expression command contract). |
| `+` | forward | —         | `+` or `+ $20` | Advance cur_addr by block_size (or expr).  Rejects trailing garbage (§ Single-expression command contract). |
| `-` | back    | —         | `-` or `- $20` | Retreat cur_addr by block_size (or expr).  Rejects trailing garbage (§ Single-expression command contract). |

### Commands — I/O

| Key | Name   | Addressed | Example              | Notes                                   |
|-----|--------|-----------|----------------------|-----------------------------------------|
| `l` | load   | yes       | `l "proj"`  / `l "proj" $c000` | Load SEQ by default; PRG when args present |
| `s` | save   | yes       | `s "proj"`  / `s "proj" $2000` | Save SEQ by default; PRG when args present |
| `$` | disk   | —         | `$`, `$9`             | Directory listing, drive select. See below. |

### Project-name and filename semantics (`l` and `s`)

The user interacts with projects by **stem name**, not disk filename.
Disk filenames are derived from the project stem + mode.  For each project
"proj":

- **Source (SEQ)** lives on disk as the bare stem `proj`.
- **Binary (PRG)** lives on disk as `proj.` (trailing dot).

Two files with the same stem cannot coexist on a CBM DOS disk (the type
byte in the directory doesn't disambiguate the filename lookup), so the
trailing dot is how CSE distinguishes the two artefacts of one project.

**Project name storage** (`cur_project_name`):
The stem of the last-used project, updated whenever the user supplies a
quoted name.  Default `"out"` when empty.  On store:
1. Strip a trailing `,s` or `,p` suffix (if present).
2. Strip any trailing dot(s) from the remaining string.
3. Copy the result to `cur_project_name`.

This prevents dot or suffix accumulation across consecutive saves.

**Argument parsing** (shared between `l` and `s`, strictly positional):

1. Optional `"quoted name"`.  Quotes required.
2. Numeric args via the expression parser, up to two.  Stops at first
   failed expression, `;`, or end of input.

Count of numeric args → slots:

| Args | start    | end   |
|------|----------|-------|
| 0    | cur_addr | 0     |
| 1    | cur_addr | arg1  |
| 2    | arg1     | arg2  |

**Mode classification** (shared):

- Name ends with `,s`/`,S` (comma at second-to-last position):
  **SEQ (verbatim)** — use the bare name (suffix stripped).
- Name ends with `,p`/`,P`: **PRG (verbatim)** — use the bare name.
- Any other 2-char suffix starting with `,` is not recognised and
  treated as part of the name (no verbatim classification, no strip).
- Else if numeric args > 0: **PRG (derived)**.
- Else: **SEQ (derived)**.

**Disk filename**:

- Verbatim: the bare typed name (suffix stripped, **trailing dot kept**).
- SEQ (derived): `cur_project_name`.
- PRG (derived): `cur_project_name` + `.`.

**Save PRG end-address semantics** (save only).  Inclusive end, matching
the `AAAA-BBBB` display convention used everywhere else:

- `end == 0` → `size = block_size` (bare `s` default).
- `end <= start` → `size = end` (length fallback — treat the arg as a
  byte count rather than an address).
- `end > start` → `size = end - start + 1` (absolute inclusive end).

**Load semantics**:

- SEQ: start and end are unused; load into editor via
  `ed_load_source(name)`.
- PRG: `end` is the target address.  `end == 0` → use the PRG header's
  load address (SETLFS SA=1 path).  Otherwise load to `end` (SA=0 path).

**Examples**:

| Command | Mode | Disk name | Addresses |
|---------|------|-----------|-----------|
| `s "demo"`                  | SEQ derived | `demo`  | — (source) |
| `s "demo" $1000`            | PRG derived | `demo.` | start=cur_addr end=$1000 |
| `s "demo" $1000 $2000`      | PRG derived | `demo.` | start=$1000 end=$2000 |
| `s "demo" $1000 $100`       | PRG derived | `demo.` | start=$1000 end=$1100 (fallback) |
| `s "demo,p"`                | PRG verbatim | `demo` | start=cur_addr end=cur_addr+blocksize |
| `s "demo,s"`                | SEQ verbatim | `demo` | — |
| `s "demo.,p"`               | PRG verbatim | `demo.` | (dot preserved) |
| `s`                         | reuse project | derived | — (SEQ if no args) |
| `s $1000`                   | PRG, reuse project | `proj.` | start=cur_addr end=$1000 |
| `l "demo"`                  | SEQ derived | `demo`  | load into editor |
| `l "demo" 0`                | PRG derived | `demo.` | load at PRG header address |
| `l "demo" $c000`            | PRG derived | `demo.` | load to $c000 |
| `l "demo,p"`                | PRG verbatim | `demo` | load at PRG header |

**Auto-generated save line (from `a`)**: after successful assembly
`seg_print_save` emits `AAAA:s "project" $EEEE` where AAAA is the lowest
origin and EEEE is the highest byte (inclusive, matching the `AAAA-BBBB`
range convention).  The address argument forces PRG mode; disk name
becomes `project.`.  Pressing RETURN on this line saves the binary.

### Commands — Info / Utility

| Key   | Name    | Addressed | Example               | Notes                                |
|-------|---------|-----------|----------------------|--------------------------------------|
| `i`   | info    | —         | `i`                  | Show memory map                       |
| `?`   | calc    | —         | `? 1000+20`          | Hex expression calculator.  Takes exactly one complete expression; rejects trailing non-whitespace / non-comment content as a syntax error (§ Single-expression command contract). |
| `k`   | kill    | —         | `k`                  | Clear source buffer; guards unsaved   |
| `B`   | block   | —         | `B 40` or `B`       | Set/show block size (uppercase)        |
| `C`   | color   | —         | `C 06` or `C 0e6`   | Set text/bg/border color (uppercase).  1–3 hex digits; rejects non-hex trailing content (§ Single-expression command contract). |
| `u`   | cpu     | —         | `u 6502` or `u 65c02` | Set CPU mode for asm/disasm        |
| `Q`   | quit    | —         | `Q`                  | Exit CSE (uppercase; guards unsaved)  |
| `R`   | reset   | —         | `R`                  | Warmstart (uppercase; ends debug if active, then refreshes screen) |
| `x`   | clear   | —         | `x`                  | Clear screen                          |
| `;`   | comment | —         | `; note`             | No-op (inline comment)                |

### Single-expression command contract

A subset of REPL commands take **exactly one complete expression
and nothing else**.  Currently covered: `?` (calc), `@` (seek),
`B` (block size), `C` (color), `j` (jump), `t`/`o` (trace),
`+`/`-` (advance/retreat), `b ADDR` (breakpoint set), `d` (disasm,
no inline args), `m` (memory — final-arg check on both `@dump`
and `@ed_done` sub-forms).

For these commands, the parser's
[expr.md § Partial-mode contract](expr.md#partial-mode-contract)
is a footgun: `expr_eval` returns success on `"1x"` with `expr_val = 1`
and `expr_ptr` at `'x'`, which is correct for assembler-operand
callers (`$10,X` is a valid prefix for INX mode) but silently wrong
for a single-expression command.  The caller **must** enforce
end-of-input after a successful parse:

1. Skip trailing whitespace (`$20`, `$A0`) at the parse pointer.
2. Verify the next byte is `$00` (end of `line_buf`) or `';'` (comment
   start).  Anything else is trailing garbage.
3. On garbage: emit `;?syntax` as a log_err line, no value applied.

Implementation: the shared `_require_eoi_or_err` helper in `repl.s`
does all three steps.  On clean EOI it returns; on garbage it pops
the caller's return address and tail-calls `log_err` with
`str_syntax`, so control flows back to `exec_line` and the command
body never runs past the check.  Callers must invoke the helper
**before** applying any state change (cur_addr, block_size, theme
colors) — otherwise garbage input would leave state half-modified.

Test contract:
`tests/integration/test_repl.py` parametrises trailing-garbage
rejection cases for each command:

- `TestCalculator::test_calc_rejects_trailing_garbage` (6 cases)
- `TestAddressCommands::test_seek_rejects_trailing_garbage` (4 cases)
- `TestBlockSize::test_block_rejects_trailing_garbage` (3 cases)
- `TestColorCommand::test_color_rejects_trailing_garbage` (3 cases)

Plus whitespace / comment acceptance tests where relevant to
distinguish valid-empty-tail cases from garbage.

**Not (yet) covered:** `+` and `-` share the class but are
complicated by their `expr_or_blocksize` fallback (empty → use
block_size).  Adding the EOI check without emitting a double
error on `+ undefsym` needs a distinct design — tracked as a
follow-up.

### Gating pattern

Several commands need the user to confirm a state-changing
operation, sometimes after acknowledging a precondition (dirty
editor, active debug session).  The pattern is uniform:

1. Emit any applicable **warning lines** via `warn_if_unsaved`
   and/or `warn_if_debug`.  Both are tail-to-`log_line` helpers
   that print `;!unsaved` or `;!debug` at LOG_WARN level when
   the condition holds, no-op otherwise.  Stacking order when
   both fire: **unsaved first, debug second**.
2. Emit the **action prompt** via `query_user`, which prints
   `;!<stem>? y/n ` at LOG_WARN and waits for a y/n key.
3. If `query_user` returns C=1 (yes): proceed with the action.
   C=0 (no) → cancel.

This decomposes the old dirty/clean composite strings (`;!unsaved.
quit? y/n`) into orthogonal warning + prompt lines, so any
combination of conditions composes without per-command variant
strings.

Gate matrix (the commands that use this pattern):

| Command | Warnings | Prompt | Yes-path |
|---------|----------|--------|----------|
| `k` | `warn_if_unsaved` | `str_del_src` → `;!del src? y/n` | clear source |
| `Q` | `warn_if_unsaved` | `str_quit` → `;!quit? y/n` | set `state = ST_STOP` → `cse_exit_to_basic` |
| `R` | `warn_if_debug` (if active) | `str_end_dbg` → `;!end debug? y/n` if active, else `str_init` → `;!init? y/n` | `end_debug_body` if active + `jmp cse_refresh` |
| `a` | `warn_if_debug` (skipped when debug inactive) | `str_asm` → `;!asm? y/n` (only when debug active) | `warm_cont := 1; jmp cse_end_debug` |
| `l` | `warn_if_unsaved` (SEQ only), `warn_if_debug` | `str_load` → `;!load? y/n` (when any warning fires) or proceed silently | `warm_cont := 1; jmp cse_end_debug` (debug case) or load directly |

When **no warning fires and the action isn't inherently
destructive**, the prompt is skipped entirely and the action runs
directly.  That keeps the common "clean state" case frictionless:
`a` at a clean REPL just assembles; `l "foo"` with no edits and no
debug just loads.

The `c` (continue) command is **not gated** — it requires an
active debug context and errors with `;?no ctx` via `log_err_eol`
when `dbg_reason == 0`.

### Internal helpers

**`confirm_yn`** — shows the cursor (`cursor_show`), waits for a
keypress (`io_getc`), hides the cursor (`cursor_hide`).  Returns
Z=1 if the key was `y`.  Used by `query_user`.

**`query_user(A/X = action-stem str)`** — prints `;!` + stem + `? y/n `
at LOG_WARN, runs `confirm_yn`, returns A = keypress byte and
C=1 on yes, C=0 on cancel.  The `? y/n ` trailer is a single
shared string (`str_qynq`) printed by the helper, so each action
string is just the verb stem (`"del src"`, `"quit"`, etc.).  Pure
print-prompt-wait; no state-based variant selection.

**`warn_if_unsaved`** — emits `;!unsaved` at LOG_WARN when
`ed_dirty != 0`.  Tail-calls `log_line`; no-op when clean.

**`warn_if_debug`** — emits `;!debug` at LOG_WARN when
`dbg_reason != 0`.  Tail-calls `log_line`; no-op when no debug
context.

The dirty flag (`ed_dirty`) is maintained by editor.s: set on any
insert/delete, cleared on save (`ed_save_source`) and load
(`ed_load_source`).  Exported for repl.s to read.

### The `R` command (reset)

`R` (uppercase) is the explicit warmstart key.  Behaviour:

| State | Prompt | Yes-path |
|-------|--------|----------|
| No active debug | `; init? y/n` | `jmp cse_refresh` |
| Active debug | `;!debug` + `; end debug? y/n` | `jsr end_debug_body` + `jmp cse_refresh` |

After a successful yes, the screen is cleared, the prompt row is
redrawn, and main_loop starts fresh.  The editor buffer is
preserved ([memory_design.md § Editor invariant](../memory_design.md#editor-invariant)).

**Command → userland dispatch (Phase 18 pattern).**  Execution
commands (`j`, `g`, `t`, `o`, `c`) never RTI into userland from
inside their own jsr frame.  Instead each command *stages* state
and sets a mode flag, then rts normally up to `main_loop`:

* `run_user_pending = MODE_JUMP` — fresh start; the gate must push
  a `brk_stub - 1` sentinel so the user's top-level RTS returns
  cleanly to `brk_stub`.  Set by `cmd_jmp` (`j`/`g`) and by
  `cmd_step` on its cold entry (no prior debug context).
* `run_user_pending = MODE_RESUME` — resume from an existing break;
  the sentinel pushed by a prior MODE_JUMP is still on the user
  stack and must not be duplicated.  Set by `cmd_c` (continue),
  `cmd_step` on hot entry.

After `exec_line` rts's back to `main_loop` (in main.s), the loop
reads `run_user_pending`:

    MODE_JUMP   → jmp return_to_userland      (sentinel + RTI)
    MODE_RESUME → jmp restore_userland_state  (no sentinel; RTI)

Both gate primitives live in [debugger.s](debugger.md); both do
`save_kernel_zp` / `restore_userland_zp` / `txs reg_sp` / push RTI
frame / `sta in_userland` / `rti`.  Control returns via the BRK or
NMI handler's longjmp to `main_loop_top`, *not* to the command.

`cmd_jmp` drains `$C6` (keyboard buffer) and emits a newline before
setting the flag so the user's first CHROUT lands on a fresh row.
`hygiene_after_userland` ($C6 drain, $CC=1, $0291=$80, VIC reset,
colour restore, cursor sync) runs unconditionally in
`handler_finalize` on every return — not in any per-command wrapper.

**`cmd_step` (`t` / `o`)** — does NOT loop.  Computes the first
step's next-PC(s), arms step BRK(s) in `bp_table`'s step slots,
seeds the handler-resident step state machine (`step_state`,
`step_remaining`), sets `run_user_pending` (MODE_JUMP cold /
MODE_RESUME hot), and rts's.  Subsequent step iterations chain
inside the BRK handler tail (see [debugger.md § Single-step](debugger.md)).
Multi-step iteration's stack budget is constant regardless of count
— `t 100` consumes the same kernel stack as `t 1`.

**`warn_long_lines`** — scans the buffer via `ed_read_byte`,
computing visual width per line (including tab expansion).
Prints `;!long LNN` for each line exceeding 39 visual columns.
Called after successful SEQ load and after successful SEQ save.

Several local helpers factor out repeated compound operations
(expression evaluation with address copy, block-size defaults,
breakpoint log formatting, color display).  The `u` (cpu) command
uses a table-driven dispatch instead of cascaded comparisons.
See `doc/optimization.md` strategies 22–23 for rationale.

### Splash screen

Displayed at startup by main.s.  Three memory summary lines show
hex address ranges and decimal free byte counts:

      zp 0002-007f      126 free
     sys 0200-03ff      512 free
    work XXXX-cfff    NNNNN free

All values are computed from linker symbols (`cse_end`) and the
`BUF_END` constant.  The work line's start address and byte count
update automatically as the binary grows.

### `B` — Block size (uppercase)

The `B` command sets a 16-bit block size used by `m`, `d`, `f`, `>`,
`/`, `t`, `o`, and `+`/`-` navigation.  Default: `$0010` (16 bytes
= 2 hex dump lines).

    B 40     set to 64 bytes (8 hex lines)
    B C0     set to 192 bytes (full screen of hex)
    B 0100   set to 256 bytes (4-digit)
    B        show current block size

### `$` — Disk

The `$` command is a unified interface for disk directory, drive
selection, and drive commands.  Parsing is prefix-based:

    $              directory listing (current drive)
    $9             select drive 9 as current, show directory

A single digit after `$` (8 or 9) sets `cur_device` permanently.
Bare `$` lists the directory.

### Tab width (build-time constant)

CSE's tab width is a **build-time constant** (`-DTAB_WIDTH=N`,
default 8).  It is not runtime-mutable — there is no `T` command.

Rationale: baking it in saves ~30 bytes (eliminates the runtime
`col_mod_tw` loop and the `T` command) and matches the C64-era
convention (Turbo Assembler, MasterSeka, Relaunch64 all default
to 8).

The "4-space" convention from modern high-level languages
doesn't fit 6502 assembly on a 40-column screen anyway — use 8.
If you really need a different value, rebuild with
`make TAB_WIDTH=N`.

### Loading files with long lines

`ed_load_source` loads file content verbatim — no line splitting
or width enforcement.  After load (and after save), the REPL
scans the buffer and prints one `;!long LNN` warning per line
exceeding 39 visual columns.  Lines show `>` in col 39 in the
editor.  Save writes the buffer verbatim, preserving the
original file structure.

### `i` — Memory map

Shows the full C64 memory layout.  Free regions are highlighted
(inverse address range).  All addresses are computed at build time
or runtime — nothing hardcoded.

     cpu 0000-0001      2  i/o port
      zp 0002-007f    126  free            ← highlighted
     sys 0080-00ff    128  kernal zp
     stk 0100-01ff    256  6502 stack
     sys 0200-02a6    167  kernal
    lo02 02a7-02ff     89  free            ← highlighted
     sys 0300-0333     52  kernal
    lo03 0334-03ff    204  free            ← highlighted
     scr 0400-07ff   1024  screen + sprites
    work 0800-XXXX  NNNNN  free            ← highlighted
     src XXXX-XXXX    NNN  N lines         (if source loaded)
     cse XXXX-CFFF  NNNNN  cse runtime     (from linker)
      io d000-dfff   4096  vic/sid/cia
     sym e000-eeff   3840  symbols
     cse ef00-f8d9   2522  banked
     rom f8da-ffff   1830  kernal rom

The lo02/lo03 rows match the splash screen layout — these are
the usable fragments in pages 2 and 3 between KERNAL work areas
and page-3 vectors.  The work row spans $0800 to `buf_base - 1`.
When source is loaded, the free region shrinks and the src row
appears.  The src line count comes from `ed_total_lines`.  The
KERNAL RAM region ($E000–$FFFF) is broken into three rows: `sym`
for the symbol table and heap, `cse` for banked data (stack
snapshots, KDATA tables, REPL screen save), and `rom` for actual
KERNAL ROM.

### `C` — Color (uppercase)

Accepts 1, 2, or 3 single hex digits.  Extra characters ignored.

    C 6          set text color to blue
    C 06         set bg=black, text=blue
    C 0e6        set border=black, bg=dark grey, text=blue

### `u` — CPU mode

    u 6502       standard NMOS 6502
    u 6510       6510 (with illegal opcodes)
    u 65c02      WDC 65C02 (CMOS extensions)

### Free / reserved keys

    e   reserved — editor mode (source buffer)
    h   free (was hunt, now `/`)
    n   free (was next/step-over, now `o`)
    p   reserved — print / evaluate
    v   reserved — visual mode (split screen?)
    w   free (was write/save, now `s`)
    x   free (was breakpoints, now `b`)
    y   free
    z   free

### Emitters

Single-line output functions, called by both edit-mode and block-mode
paths:

- `emit_dot(addr)` — writes `AAAA:. HH HH HH  MNE OPR`, returns
  instruction length.  Two spaces between hex bytes and mnemonic.
- `emit_mem(addr, cols)` — writes `AAAA:m HH HH HH HH HH HH HH HH cccc`
- `emit_reg()` — writes `r pc:xxxx a:xx x:xx y:xx s:xx Nv-bDizc`
  (set flags uppercase, clear flags lowercase; AND #$DF on PETSCII)

Each emitter starts at column 0 and calls `clear_eol` at the end.

### Implementation status

    [x] .   asm/disasm single instruction
    [x] d   disassemble block
    [x] m   memory dump / edit
    [x] a   assemble source buffer
    [x] j   JSR / start execution
    [x] r   registers view / edit
    [x] @   seek (was s)
    [x] $   directory listing (+ drive select, + drive command)
    [x] q   quit
    [x] clr clear screen
    [x] +   seek forward
    [x] -   seek backward
    [x] i   memory map info
    [x] ?   hex expression calculator
    [x] B   block size (uppercase, was `b`)
    [x] C   color theme (uppercase, was `c`)
    [x] u   cpu mode select
    [x] k   kill source (clear editor buffer, confirms first)
    [x] l   load file from disk
    [x] s   save memory to disk (was `w`)
    [x] b   breakpoints (was `x`). See debugger.md
    [x] c   continue execution (was color). See debugger.md
    [x] t   trace / step-into. See debugger.md
    [x] o   trace over / step-over (was `n`). See debugger.md
    [x] g   go — shorthand for j main (falls back to j cur_addr)

## Caveats

- `read_line` reads screen RAM at the cursor row, converting screen
  codes to PETSCII.  Lowercase screen codes ($01–$1A) map to $41–$5A;
  uppercase screen codes ($41–$5A) map to $C1–$DA.  This preserves
  case for command dispatch.
- `exec_line` modifies `cur_addr` as a side effect of the `AAAA:` prefix.
- The `?` command uses `expr_eval` directly — labels from the last
  assembly are available.  Decimal output delegates to `io_putdec`
  (cse_io.s) with space-padding for right-aligned 5-digit display.
- **Expression arguments:** Commands `@`, `j`, `+`, `-`, `b`, `s`,
  `t`, `o`, `B` accept full expressions (`$hex`, decimal, symbols,
  operators).  Bare digits are decimal — hex requires `$` prefix.
  The `AAAA:` prompt prefix remains plain hex.
- File type (PRG vs SEQ) determined by: verbatim `,s`/`,p` suffix first;
  otherwise plain names default to SEQ (no address args) or PRG (any
  numeric args).  See § Project-name and filename semantics.
