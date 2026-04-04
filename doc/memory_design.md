# Memory Design — Memory maps, ZP layout, screen switching

**Template:** [subsystem](templates/subsystem.md)

## Design Principles

1. **CSE stays out of the developer's way.** The developer's mental
   model: "my program lives at $1000 and up." CSE lives high.

2. **ROM-ready architecture.** All code and rodata must be separable
   from mutable state.  No self-modifying code.  Constants in RODATA,
   runtime state in BSS (DATA segment is empty).  The same source
   must build as both PRG (RAM at $8000) and CRT (ROM at $8000).

3. **Mutable state is small and relocatable.** CSE's runtime variables,
   parameter stack, screen buffers — all grouped into one region that can move
   between configurations (PRG vs CRT, different RAM layouts).

4. **One screen, memcpy save/restore.** Both REPL and editor use the
   same screen RAM at $0400. On mode switch, the REPL screen content
   (1000 bytes) is saved to / restored from banked RAM under KERNAL.
   Cost: 1000 bytes BSS, ~1ms per switch. The editor view is always
   reconstructable from the source buffer; the REPL screen is not
   (it contains command history and output), hence only the REPL
   screen needs saving.

5. **Source and developer code share the big region.** Source text grows
   downward, assembled output grows upward, classic C64 model (like
   BASIC programs vs strings). The `i` command shows remaining space.

## Memory Map — PRG Target (development)

Build loads to $0801 (standard BASIC start) for easy `RUN` during
development. Future production builds relocate to $8000.

    $0000-$00FF  Zero page (see § Zero Page Layout below)
      $00-$01    CPU I/O port
      $02-$5A    CSE modules (89 bytes)
      $5B-$7F    Free (37 bytes, available for user programs)
      $80-$FF    KERNAL
    $0100-$01FF  6502 hardware stack
    $0200-$03FF  KERNAL/BASIC work area
    $0400-$07E7  Screen RAM (VIC bank 0, default)
    $07E8-$07FF  Sprite pointers (unused by CSE)
    $0800-$0FFF  CSE code (current PRG load point)
      ...        (code + rodata + bss, ~20KB)
    $????-$CFFF  Free (developer + source, see future layout)
    $D000-$DFFF  I/O (VIC/SID/CIA)
    $E000-$E0FF  KERNAL RAM (free, 256 B)
    $E100-$E1FF  KERNAL RAM: CSE stack snapshot (256 B, debugger)
    $E200-$E2FF  KERNAL RAM: User stack snapshot (256 B, debugger)
    $E300-$F817  KERNAL RAM (free, 5.4 KB available)
    $F818-$FBFF  KERNAL RAM: repl_screen (1000 bytes, banked)
    $FC00-$FEFF  KERNAL RAM: sym_table (768 bytes, banked)
    $FF00-$FF09  NMI trampoline (10 bytes, banked)
    $FFFA-$FFFF  HW vectors (NMI/RESET/IRQ)

Note: BASIC ROM ($A000-$BFFF) is unmapped at startup. The RAM
underneath is available.

Note: $E000-$FFFF is KERNAL ROM by default.  The RAM underneath is
accessible by clearing bit 1 of the CPU I/O port ($01).  Interrupts
must be disabled (sei) while the KERNAL is banked out, because the
IRQ vector and KERNAL interrupt handler are not visible when ROM is
unmapped.  An NMI trampoline at $FF00 handles the case where NMI
fires during a bank-out (sei does not mask NMI).  CSE uses this
region for the symbol table (768 bytes at $FC00) and the REPL
screen save buffer (1000 bytes at $F818).  All accesses are
wrapped in sei / bank-out / access / bank-in / cli guard sequences.
See [symtab.md](modules/symtab.md) for details.

## Memory Map — PRG Target (production, relocated)

    $0000-$03FF  System (ZP, stack, KERNAL work)
    $0400-$07E7  Screen RAM (shared REPL / editor, VIC bank 0)
    $0800-$7FFF  Developer's program ↑ / source ↓  (30KB)
    $8000-$BFFF  CSE runtime (code+rodata+data+bss+cstk)
    $C000-$CFFF  Free for developer (popular target address)
    $D000-$DFFF  I/O
    $E000-$E0FF  KERNAL RAM (free, 256 B)
    $E100-$E1FF  KERNAL RAM: CSE stack snapshot (256 B, debugger)
    $E200-$E2FF  KERNAL RAM: User stack snapshot (256 B, debugger)
    $E300-$F817  KERNAL RAM (free, 5.4 KB available)
    $F818-$FBFF  KERNAL RAM: repl_screen (1000 bytes, banked)
    $FC00-$FEFF  KERNAL RAM: sym_table (768 bytes, banked)
    $FF00-$FF09  NMI trampoline (10 bytes, banked)
    $FFFA-$FFFF  HW vectors (NMI/RESET/IRQ)

    Developer workspace: $0800-$7FFF = 30KB (source + output)
    CSE footprint:       $8000-$BFFF = 16KB
    Bonus developer:     $C000-$CFFF =  4KB

## Memory Map — CRT Target (cartridge)

    $0000-$03FF  System (ZP, stack, KERNAL work)
    $0400-$07E7  Screen RAM (shared REPL / editor, VIC bank 0)
    $0800-$7FFF  Developer's program ↑ / source ↓  (30KB)
    $8000-$BFFF  CSE cartridge ROM (code + rodata, 16KB)
    $C000-$CFFF  CSE mutable state (BSS + parameter stack)
    $D000-$DFFF  I/O
    $E000-$E0FF  KERNAL RAM (free, 256 B)
    $E100-$E1FF  KERNAL RAM: CSE stack snapshot (256 B, debugger)
    $E200-$E2FF  KERNAL RAM: User stack snapshot (256 B, debugger)
    $E300-$F817  KERNAL RAM (free, 5.4 KB available)
    $F818-$FBFF  KERNAL RAM: repl_screen (1000 bytes, banked)
    $FC00-$FEFF  KERNAL RAM: sym_table (768 bytes, banked)
    $FF00-$FF09  NMI trampoline (10 bytes, banked)
    $FFFA-$FFFF  HW vectors (NMI/RESET/IRQ)

    Developer workspace: $0800-$7FFF = 30KB (source + output)
    CSE ROM:             $8000-$BFFF = 16KB (zero RAM cost)
    CSE RAM:             $C000-$CFFF =  4KB (state + stack)

Note: In the CRT layout, $C000-$CFFF is used by CSE's mutable state.
In the PRG layout it's free for the developer since CSE's mutable
state lives within the $8000-$BFFF region alongside the code.

## Source Code Storage

Source text lives at $C7FF growing downward. It shares the $1000-$C7FF
region with the developer's assembled output (which grows up from
$1000). This is the classic C64 model: programs and strings growing
toward each other.

    $1000  ──→  assembled output (grows up)
                  ... free gap ...
    $C7FF  ←──  source text (grows down)

The gap between them is free memory. The `i` command reports the gap
size. The 2-pass assembler reads source from the top-down region and
writes output to the bottom-up region. As long as they don't collide,
everything works.

For large programs where source + output exceed the available space:
save source to disk, assemble, then the full region is available for
the binary.

## Screen Switching

Both REPL and editor use the same screen RAM at $0400.  On mode
switch, the REPL screen content (1000 bytes) is saved to / restored
from a buffer in CSE's BSS.

    static uint8_t repl_screen_buf[1000];

    /* REPL → editor */
    memcpy(repl_screen_buf, SCREEN, 1000);  /* save REPL */
    clrscr();                                /* render editor view */

    /* editor → REPL */
    memcpy(SCREEN, repl_screen_buf, 1000);  /* restore REPL */

Cost: 1000 bytes BSS, ~1ms per switch.  No VIC bank switching, no
special screen addresses, identical code for PRG and CRT.  The editor
view is always reconstructable from the source buffer; the REPL screen
is not (it contains command history and output), hence only the REPL
screen needs saving.

For build targets, linker configs, and ROM compatibility constraints,
see [build_system.md](build_system.md).

## Zero Page Layout

Authoritative ZP allocation.  Module docs reference this table.
Addresses are assigned by the linker from $02 upward.

### CSE modules ($02–$5A)

Addresses assigned by the linker from $02 upward.  Exact layout
depends on link order; the table below reflects the 6510 build.

| Range | Size | Module | Variables |
|-------|------|--------|-----------|
| $02–$09 | 8 | main | `sp` (2), `ptr1` (2), `ptr2` (2), `tmp1` (1), `tmp2` (1) |
| $0A–$0C | 3 | asm_bridge | `_ab_saved_sp` (1), `_jsr_vec` (2) |
| $0D–$24 | 24 | asm_vars | `al_pc` (2), `al_out` (2), `al_cpu` (1), `al_len` (1), `al_slot` (1), `al_prof` (1), `al_pidx` (1), `al_base` (1), `al_bit` (1), `al_mode` (1), `_al_tmp` (1), `_al_tmp2` (1), `sym_name` (2), `sym_val` (2), `sym_wide` (1), `expr_ptr` (2), `expr_val` (2), `expr_wide` (1) |
| $25–$27 | 3 | asm_src | `_as_ptr` (2), `_as_wsize` (1) |
| $28–$2A | 3 | mn_vars | `mn_c1` (1), `mn_c2` (1), `mn_c3` (1) |
| $2B | 1 | mn7 | `mn7_h_tmp` (1) |
| $2C–$30 | 5 | au_mode | `au_ptr` (2), `au_opr` (2), `_au_tmp` (1) |
| $31 | 1 | opcode_lookup | `_ok_tmp` (1) |
| $32–$35 | 4 | cse_io | `_io_tmp` (2), `_io_scr` (2) |
| $36–$39 | 4 | expr | `_ex_tmp` (2), `_ex_digits` (1), `_ex_wide_tmp` (1) |
| $3A–$44 | 11 | symtab | `_st_hash` (1), `_st_idx` (1), `_st_ptr` (2), `_st_nptr` (2), `_st_count` (1), `_st_heap` (2), `_st_heap_base` (2) |
| $45–$4C | 8 | dasm | `_dasm_ptr` (2), `_dasm_opc` (1), `_dasm_mne` (2), `_dasm_wptr` (1), `_dasm_midx` (1), `_dasm_mode` (1) |
| $4D–$5A | 14 | editor | `gap_lo` (2), `gap_hi` (2), `buf_base` (2), `ed_top_ptr` (2), `read_ptr`/`save_ptr` (2, overlapped), `ed_tmp` (2), `ed_scr` (2) |

### Fixed locations (not in ZEROPAGE segment)

| Address | Used by | Purpose |
|---------|---------|---------|
| $00–$01 | CPU | I/O port (memory banking) |
| $C6 | cse_io | `KEY_COUNT` — keyboard buffer count (read by `io_kbhit`) |
| $CC | cse_io | `CURS_FLAG` — set to 1 at startup, never changed (disables KERNAL cursor) |
| $D3 | cse_io | `CUR_COL` — cursor column (0–39), aliased as `io_cx` |
| $D6 | cse_io | `CUR_ROW` — cursor row (0–24), aliased as `io_cy` |
| $FB–$FE | screen | `src_ptr` / `dst_ptr` — scratch for `scroll_up` |
