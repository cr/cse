# Memory Design — Memory maps, ZP layout, calling convention

**Template:** [subsystem](templates/subsystem.md)

## Design Principles

1. **CSE stays out of the developer's way.** The developer's mental
   model: "my program lives at `workstart` and up."  CSE code lives
   above the workspace.

2. **ROM-ready architecture.** Code and RODATA are separable from
   mutable state.  No self-modifying code.  Constants in RODATA,
   runtime state in BSS.  The same source must build as both PRG
   (RAM) and CRT (ROM at $8000).

3. **Mutable state is small and relocatable.** All runtime variables
   live in BSS (zeroed at boot) or ZP.  No initialized DATA segment.

4. **One screen, save/restore.** Both REPL and editor use screen RAM
   at $0400.  On mode switch, the REPL screen (1000 bytes) is saved
   to / restored from banked RAM under KERNAL ($F818).  The editor
   view is always reconstructable from the gap buffer; only the REPL
   screen needs saving.

5. **Source and output share the workspace.** Source text grows down
   from $C800, assembled output grows up from `workstart`.  The `i`
   command shows the gap between them.

## Calling Convention

All modules are pure 6502 assembly.  One consistent convention:

### Register arguments

| Args | Convention |
|------|-----------|
| 0 | — |
| 1 (8-bit) | A |
| 1 (16-bit) | A/X (lo/hi) |
| 2 | First arg pushed via `pushax`; second (last) in A/X |
| 3+ | Earlier args pushed right-to-left; last in A/X |

### Return values

| Type | Convention |
|------|-----------|
| 8-bit value | A |
| 16-bit value | A/X (lo/hi) |
| Success/failure | C flag: C=0 success, C=1 failure (or vice versa per function doc) |
| Void | — |

### Shared state (ZP interface)

Several subsystems pass data through named ZP variables rather than
registers.  This is preferred for multi-field I/O:

| ZP group | Owner | Fields | Used by |
|----------|-------|--------|---------|
| Assembler I/O | asm_vars | `al_pc`, `al_out`, `al_cpu`, `al_len`, `al_mode` | asm_line, asm_src, asm_bridge |
| Symbol I/O | asm_vars | `sym_name` (ptr), `sym_val`, `sym_wide` | symtab, asm_src, expr, repl |
| Expression I/O | asm_vars | `expr_ptr` (ptr), `expr_val`, `expr_wide` | expr, asm_src, repl |
| Mnemonic chars | mn_vars | `mn_c1`, `mn_c2`, `mn_c3` | mn_classify, mn7/mn6, asm_line |

Callers set the input fields, call the function, read the output
fields.  The function may modify any field in its group.

### Register clobbering

Functions clobber A, X, Y unless documented otherwise.  ZP variables
outside the function's own group are preserved.  The hardware stack
is balanced (no net push/pop across a call).

### Multi-argument calls

Functions with 2+ arguments use named ZP variables for the first
arguments and A/X for the last.  Examples:

- `disk_load_prg`: `disk_ptr` = name, A/X = addr
- `asm_line`: `al_pc`/`al_out` set by caller, A/X = text
- `ed_read_line`: A/X = buf pointer (maxlen hardcoded)

No software parameter stack.  All arguments pass through registers
or ZP variables.

## Memory Map — PRG Target (development)

    $0000-$00FF  Zero page (see § Zero Page Layout)
      $00-$01    CPU I/O port
      $02-$5A    CSE ZP variables (89 bytes, 14 modules)
      $5B-$7F    Free (37 bytes, available for user programs)
      $80-$FF    KERNAL work area
    $0100-$01FF  6502 hardware stack (shared CSE + user code)
    $0200-$03FF  KERNAL work area
    $0400-$07E7  Screen RAM (40×25, VIC bank 0)
    $07E8-$07FF  Sprite pointers (unused by CSE)
    $0800        CSE binary (BASIC stub + startup + code + rodata)
      ...        (~20KB code + rodata, BSS follows)
    workstart    First free page after BSS (rounded up to $100)
      ...        Assembled output ↑ (grows up)
      ...        Free workspace
      ...        Source text ↓ (grows down)
    $C800        buf_end — exclusive top of gap buffer (fixed)
    $C800-$CFFF  Parameter stack (2KB, grows down from $D000)
    $D000-$DFFF  I/O (VIC-II, SID, CIA1, CIA2)
    $E000-$E0FF  Free under KERNAL (256 B)
    $E100-$E1FF  CSE stack snapshot (debugger context switch)
    $E200-$E2FF  User stack snapshot (debugger context switch)
    $E300-$E6F1  KDATA tables (1010 B, copied from PRG at startup)
    $E6F2-$F817  Free under KERNAL (4.3 KB)
    $F818-$FBFF  REPL screen save buffer (1000 B, banked)
    $FC00-$FEFF  Symbol table (768 B, 128 slots, banked)
    $FF00-$FF09  NMI trampoline (10 B, banked)
    $FFFA-$FFFF  Hardware vectors (NMI/RESET/IRQ)

BASIC ROM ($A000-$BFFF) is unmapped at startup.  The RAM underneath
is available for CSE code/data.

KERNAL ROM ($E000-$FFFF) remains mapped.  The RAM underneath is
accessed by clearing bit 1 of $01 (sei required; NMI trampoline at
$FF00 handles NMI during bank-out).

## Memory Map — Relocated (production)

    $0000-$03FF  System
    $0400-$07E7  Screen RAM
    $0800-$7FFF  Workspace (30 KB: output ↑ / source ↓)
    $8000-$BFFF  CSE binary (16 KB)
    $C000-$CFFF  CSE BSS + parameter stack (4 KB)
    $D000-$DFFF  I/O
    $E000-$FFFF  KERNAL ROM + banked data (as above)

## Memory Map — Cartridge (CRT)

    $0000-$03FF  System
    $0400-$07E7  Screen RAM
    $0800-$7FFF  Workspace (30 KB)
    $8000-$BFFF  CSE ROM (code + rodata, 16 KB, zero RAM cost)
    $C000-$CFFF  CSE RAM (BSS + parameter stack, 4 KB)
    $D000-$DFFF  I/O
    $E000-$FFFF  KERNAL ROM + banked data (as above)

## Source Code Storage

Source text lives in a gap buffer at the top of the workspace,
growing downward from $C800:

    workstart ──→  assembled output (grows up)
                     ... free gap ...
    buf_base  ←──  source text (grows down toward workstart)
    $C800          buf_end (exclusive, fixed)

The `workstart` and `workend` symbols are pre-defined in the symbol
table, usable in assembly (`.org workstart`) and REPL expressions
(`@ workend`, `j workstart`).

## Zero Page Layout

### Overview

89 bytes across 13 modules, linker-assigned from $02 upward.
37 bytes free ($5B–$7F) for user programs.

### Module allocation (6510 build)

| Range | Bytes | Module | Variables |
|-------|-------|--------|-----------|
| $02–$07 | 6 | main | `rp_ptr` (2), `rp_ptr2` (2), `rp_tmp` (1), `rp_tmp2` (1) |
| $08–$0A | 3 | asm_bridge | `ab_saved_sp` (1), `jsr_vec` (2) |
| $0B–$22 | 24 | asm_vars | assembler + symbol + expression I/O (see § Shared state) |
| $23–$25 | 3 | asm_src | `as_ptr` (2), `as_wsize` (1) |
| $26–$28 | 3 | mn_vars | `mn_c1` (1), `mn_c2` (1), `mn_c3` (1) |
| $29 | 1 | mn7 | `mn7_h_tmp` (1) |
| $2A–$2E | 5 | au_mode | `au_ptr` (2), `au_opr` (2), `au_tmp` (1) |
| $2F | 1 | opcode_lookup | `ok_tmp` (1) |
| $30–$33 | 4 | cse_io | `io_tmp` (2), `io_scr` (2) |
| $34–$35 | 2 | disk | `disk_ptr` (2) |
| $36–$39 | 4 | expr | `ex_tmp` (2), `ex_digits` (1), `ex_wide_tmp` (1) |
| $3A–$44 | 11 | symtab | hash/probe state, heap pointers |
| $45–$4C | 8 | dasm | decode state, output pointer |
| $4D–$5A | 14 | editor | gap pointers, screen scratch |

### Non-concurrent groups

Several module groups never execute simultaneously.  Their scratch
variables could share addresses:

| Group | Modules | ZP | BSS | Active when |
|-------|---------|-----|------|-------------|
| **Assembler** | asm_src, asm_line, asm_bridge, opcode_lookup, au_mode, mn7, mn_vars | 41 | 253 | `a` command |
| **Editor** | editor | 14 | 59 | ST_EDIT mode |
| **Disassembler** | dasm | 8 | 24 | `d`/`t`/`o` |
| **Disk I/O** | disk | — | 67 | `l`/`s`/`$` |
| **Always active** | main, cse_io, symtab, expr, repl | 27 | 116 | any time |

Assembler and editor are fully non-concurrent.  Assembler and
disassembler are also non-concurrent.  Expression evaluation
(`expr`) is called from both REPL and assembler — cannot overlap.

### Optimization opportunities

**ZP overlap** (not yet implemented):

| Overlap | Bytes saved | Constraint |
|---------|-------------|------------|
| Editor scratch (`ed_tmp`/`ed_scr` 4B) ↔ assembler scratch (`_as_ptr`/`_as_wsize` 3B + `_ok_tmp` 1B) | 4 | Editor not active during assembly |
| Dasm (8B) ↔ assembler scratch (10B) | 8 | Never concurrent |
| **Total ZP reclaimable** | **~12 B** | |

**BSS overlap** (not yet implemented):

| Buffer A | Size | Buffer B | Size | Saving | Constraint |
|----------|------|----------|------|--------|------------|
| asm_src `_line_buf` | 80 | repl `line_buf` | 42 | 42 | Assembler doesn't run from REPL line buffer |
| asm_src `_full_label` | 48 | editor `ws_buf` | 39 | 39 | Editor not active during assembly |
| dasm `_dasm_buf` | 24 | repl `dot_asm_buf` | 24 | 24 | Disasm output consumed before `.` command |
| **Total BSS reclaimable** | | | | **~105 B** | |

**Completed optimizations:**
- `_zp_save_buf` trimmed: $5E → $5A (4B BSS saved)
- Parameter stack eliminated: `pushax`/`cse_popax`/`sp` removed,
  all multi-arg calls use ZP variables (2KB workspace gained)
- KDATA tables under KERNAL: 1010B of lookup tables at $E300+
- Packed opcode→length table: 64B, replaces dasm_insn in cmd_step
  (5× faster stepping)

### KERNAL ZP locations (read/written directly)

| Address | Name | Purpose |
|---------|------|---------|
| $00–$01 | CPU I/O port | Memory banking ($01 bit 1 = KERNAL) |
| $C6 | KEY_COUNT | Keyboard buffer count (read by `io_kbhit`) |
| $CC | CURS_FLAG | Set to 1 at startup (disables KERNAL cursor) |
| $D1–$D2 | Screen line ptr | Updated by `io_sync` via KERNAL PLOT |
| $D3 | CUR_COL | Cursor column (0–39) |
| $D6 | CUR_ROW | Cursor row (0–24) |
| $F3–$F4 | Color line ptr | Updated by `io_sync` via KERNAL PLOT |
