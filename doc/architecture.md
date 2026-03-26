# CSE Module Architecture

## Module Map

```
┌──────────────────────────────────────────┐
│                 main.c                   │  init, mode switch, main loop
├───────────────┬──────────────────────────┤
│    repl.c     │        editor.c          │  user-facing modes
├───────────────┴──┬───────────┬───────────┤
│    asm_src.c     │  expr.s   │ symtab.s  │  source assembler pipeline
├──────────────────┴───────────┴───────────┤
│  asm_line.s  │  dasm.s    │   disk.s     │  core engines
├──────────────┴────────────┴──────────────┤
│          screen.s    │    cse_io.s       │  output layers
└──────────────────────┴───────────────────┘
```

## Modules

### main.c — Application Shell
- Hardware init (IRQ, charset, memory config)
- Main loop: read key, dispatch to REPL or editor
- Mode switching (RUN/STOP toggles REPL ↔ editor)
- Startup splash screen

**Depends on:** screen, repl, editor

### screen.s — Screen Management
- `reset_screen()` — reset colors, clear screen
- `scroll_up(n)` — scroll screen + color RAM with SEI/CLI
- `newline()` — advance cursor, scroll if at bottom
- `print_string(str)` — scroll-aware string output
- `cursor_show()` / `cursor_hide()` — XOR $80 at cursor
- `restore_colors()` — set color scheme + fill color RAM

**Depends on:** cse_io

**Design notes:** All functions are pure 6502 asm. `scroll_up` uses
SEI/CLI to prevent IRQ during memmove. Screen save/restore for editor
mode switching lives here.

### cse_io.s — Raw Screen I/O (6502 asm)
- `io_putc(ch)` — PETSCII char to screen RAM at cursor, advance
- `io_puts(str)` — PETSCII string at cursor
- `io_puthex2(v)` / `io_puthex4(v)` — hex output
- `io_putdec(v)` — decimal output
- `io_clear_eol()` — fill to end of row with spaces
- `io_getc()` — blocking KERNAL GETIN, returns raw PETSCII key code
- `io_kbhit()` — non-blocking keyboard check
- `io_sync()` — sync KERNAL cursor state via PLOT

**Depends on:** nothing (leaf module)

**Contract:** Requires $CC=1 (KERNAL cursor disabled). Cursor tracked
in `$D3` (col) / `$D6` (row). Screen writes use `_io_scr` ZP pointer
computed from `scr_lo`/`scr_hi` lookup tables.

### disk.s — CBM File I/O
- `floppy_status()` — read drive error channel, print to screen
- `list_directory(device)` — list directory to screen
- `disk_load_prg(name, addr)` — load PRG file to address
- `disk_save_prg(name, addr, len)` — save memory range as PRG
- `disk_load_seq(name, insert_fn)` — read SEQ file, call insert_fn per byte
- `disk_save_seq(name, read_fn)` — write SEQ file, call read_fn for bytes

**Depends on:** screen (for directory output, status display)

**Design notes:** SEQ I/O uses callbacks so disk.s doesn't depend on
editor.c. The editor passes `gb_insert` as insert_fn for loading.
After every disk operation, the drive error channel is read
automatically (no I command sent — just read channel 15).

### repl.c — REPL Mode
- `read_line()` — read screen row → PETSCII line_buf
- `exec_line()` — parse AAAA:cmd, dispatch
- Command handlers: `.` `d` `m` `j` `r` `s` `b` `c` `i` `u` `l` `w` `+` `-` `;` `$` `q`
- Emit functions: `emit_dot` `emit_mem` `emit_reg`
- `show_prompt()` — write `AAAA:` at cursor

**Depends on:** asm_line (`.` command), dasm (disassembly in emit_dot),
expr (address parsing), disk (l/w/$ commands), screen

### editor.c — Source Editor Mode
- Gap buffer: `gb_insert` `gb_backspace` `gb_cursor_*` `gb_ensure_room`
- Rendering: `ed_render_line` `ed_render_range` `ed_render_status`
- Editor loop: `ed_handle_key`
- Mode entry/exit: `enter_editor` `leave_editor`

**Depends on:** disk (load/save SEQ via callbacks), screen

### dasm.s — Disassembler (6502 asm)
- `dasm_insn(addr)` — disassemble one instruction at addr
- Output: NUL-terminated PETSCII string in `dasm_buf` (24 bytes BSS)
- Returns: instruction length in A
- CPU-aware: reads `al_cpu` (0=6502, 1=6510, 2=65C02)

**Depends on:** nothing (reads memory directly, writes to buffer)

**Design notes:** Bit-slice decoder exploiting aaabbbcc opcode structure.
No 256-entry tables. Group tables (8 entries each) + small exception
lists. CMOS support guarded by `.ifdef CMOS_SUPPORT`.

### asm_line.s — Single-Line Assembler (6502 asm)
- `al_line_asm` — assemble one instruction from VICII screencode string
- Input: `al_pc` (address), `au_ptr` (text pointer), `al_cpu` (CPU mode)
- Output: bytes written to `[al_out]`, length in `al_len`

**Depends on:** opcode_lookup, au_mode, mn_classify, mn7/mn6 tables

### expr.s — Expression Parser (6502 asm)
- `_expr_eval` — ZP in: expr_ptr (string pointer), al_pc (for `*`).
  Out: expr_val (16-bit), expr_wide (0/1). Returns A = 0 (ZP), 1 (ABS), 2+ (error).
- `_expr_error_str` — return pointer to last error's text
- Supports: `$hex`, `%binary`, decimal, labels, `+` `-` `<` `>` `&` `|` `^` `~` `()` `*`
- Label charset: a-z, 0-9, `.` (case insensitive, no underscore)

**Depends on:** symtab.s (`_sym_lookup` for label resolution)

**Design notes:** Recursive descent. Width tracking: 3+ hex digits force
ABS, labels inherit from definition, `<`/`>` always produce ZP.

### symtab.s — Symbol Table (6502 asm)
- `_sym_define` — ZP in: sym_name (ptr), sym_val (16-bit), sym_wide (0/1). C=1 if full.
- `_sym_lookup` — ZP in: sym_name (ptr). Out: sym_val, sym_wide. C=1 if not found.
- `_sym_clear` — wipe all slots
- `_sym_count` — return count in A

**Depends on:** nothing (standalone data structure)

**Design:** 128-slot hash table with linear probing, 6-byte entries
(hash + value + name_ptr + scope). Names stored as PETSCII strings
pointed to by name_ptr (into source during assembly, snapshot heap
after). Case-insensitive (uppercase folded to lowercase). Scope byte
carries ZP/ABS flag (bit 7) and local label parent_id (bits 5-0).
See `doc/symtab_design.md` for full details.

### asm_src.c — Source Assembler (stub)
- `asm_assemble()` — 2-pass assembly of gap buffer contents
- `asm_org` — current origin address
- `asm_errors` — error count after assembly

**Depends on:** asm_line (instruction assembly), symtab (labels),
expr (operand expressions), editor (gap buffer read access)

**Design notes:** Pass 1: scan source, record label addresses, track
origin. Pass 2: assemble each line via asm_line, resolve forward
references. Directives: `*=` (origin), `.byte` `.word` (data),
`.cpu` (select CPU mode). Error reporting references source line
numbers.

## Dependency Rules

1. **No circular dependencies.** The graph above is a DAG.
2. **Leaf modules have no dependencies:** cse_io, dasm, symtab.
3. **Screen output flows one way:** module → screen → cse_io.
4. **disk.s uses callbacks** for SEQ I/O to avoid depending on editor.
5. **Expression parser is standalone** — no screen or I/O.
6. **All asm modules (.s) are self-contained** with explicit .import/.export.

## Asm Replacement Path

Every C module is designed so its interface (header file) stays fixed
while the implementation moves from C to 6502 asm:

1. Functions use `__fastcall__` where the hot path benefits
2. Interfaces use fixed-size types (uint8_t, uint16_t)
3. State lives in known ZP/BSS locations (not C locals)
4. No malloc/free — all memory is statically allocated or arena-based
5. Callbacks use function pointers (C) or jump vectors (asm)

Priority for asm rewrite (by code size impact):
1. repl.c (biggest C module)
2. editor.c
3. expr.s / symtab.s / asm_src.c (TBD)
