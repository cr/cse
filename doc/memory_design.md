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
   to / restored from banked RAM under KERNAL ($F4F2).  The editor
   view is always reconstructable from the gap buffer; only the REPL
   screen needs saving.

5. **Source and output share the workspace.** Source text grows down
   from $D000, assembled output grows up from `workstart`.  The `i`
   command shows the gap between them.

## Calling Convention

All modules are pure 6502 assembly.  One consistent convention:

### Register arguments

| Args | Convention |
|------|-----------|
| 0 | — |
| 1 (8-bit) | A |
| 1 (16-bit) | A/X (lo/hi) |
| 2+ | Earlier args in named ZP variables; last in A/X |

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

## Glossary

| Term | Meaning |
|------|---------|
| **CODE** | Executable code in main RAM (XXXX–$CFFF) |
| **RODATA** | Read-only constants in main RAM (follows CODE) |
| **BSS** | Uninitialized runtime state in main RAM (follows RODATA, zeroed at startup, no PRG space) |
| **KDATA** | Read-only tables under KERNAL ROM ($E000–$FFFF), copied from PRG payload at startup |
| **KBSS** | Uninitialized structures under KERNAL ROM, zeroed at startup (no PRG space) |

## Memory Map — Runtime (all targets)

    $0000-$00FF  Zero page (see § Zero Page Layout)
      $00-$01    CPU I/O port
      $02-$57    CSE ZP variables (86 bytes, 13 modules)
      $58-$7F    Free (40 bytes, available for user programs)
      $80-$FF    KERNAL work area
    $0100-$01FF  6502 hardware stack (shared CSE + user code)
    $0200-$03FF  KERNAL work area
    $0400-$07E7  Screen RAM (40×25, VIC bank 0)
    $07E8-$07FF  Sprite pointers (unused by CSE)
    $0800        workstart — first free workspace byte
      ...        Assembled output ↑ (grows up)
      ...        Free workspace
      ...        Source text ↓ (grows down)
    XXXX-1       workend — last free workspace byte
    XXXX         CSE CODE (position determined by build size)
      ...        CSE RODATA
      ...        CSE BSS
    $CFFF        CSE runtime end (contiguous, no gaps)
    $D000-$DFFF  I/O (VIC-II, SID, CIA1, CIA2)
    $E000-$FFFF  Banked data under KERNAL ROM (see § Banked layout)

The runtime start address XXXX is not fixed — it floats based on
the combined size of CODE + RODATA + BSS:

    XXXX = $D000 - sizeof(CODE + RODATA + BSS)

This maximizes the workspace automatically.  With the current 6510
build (~20 KB code + rodata, ~800 B BSS), XXXX ≈ $80CF, giving
~31 KB of workspace ($0800–$80CE).  As the codebase grows or
shrinks, workend adjusts and the user sees it via `i`.

BASIC ROM ($A000-$BFFF) is unmapped at startup.  The RAM underneath
is part of the CSE runtime (code spans across $A000 freely).

KERNAL ROM ($E000-$FFFF) remains mapped.  The RAM underneath is
**read** by clearing bit 1 of $01 (sei required; NMI trampoline at
$FF00 handles NMI during bank-out).  **Writes always pass through**
to the underlying RAM regardless of $01 bit 1, so pure-writer code
(`sym_clear`, `kernal_init`, the SCREEN→`repl_screen` save in
`enter_editor`) does not bank — only readers do.

The `kernal_out` flag in BSS lets long-running batches (e.g.
`asm_assemble` over both passes) hold the KERNAL banked out across
many inner calls without paying sei + `$01` write overhead per
call: when set, `kernal_bank_out` and `kernal_bank_in` both
short-circuit to `rts`.

### Banked layout ($E000–$FFFF)

All data under the KERNAL ROM is initialized by the loader at
startup.  KDATA regions are copied from the PRG payload; KBSS
regions are zeroed (no PRG space required).

    $E000-$E5FF  KBSS: symbol table (1536 B, 256 slots × 6B)
    $E600-$EEFF  KBSS: symbol name heap (2304 B)
    $EF00-$EFFF  Earmarked: user stack snapshot (256 B, see § Stack budget)
    $F000-$F0FF  Free (256 B)
    $F100-$F4F1  KDATA: asm/dasm lookup tables (1010 B)
    $F4F2-$F8D9  KBSS: REPL screen save buffer (1000 B)
    $F8DA-$FEFF  Free (1574 B)
    $FF00-$FF09  KDATA: NMI trampoline (10 B)
    $FFFA-$FFFF  Hardware vectors (NMI/RESET/IRQ)

    KDATA total:  1020 B (in PRG payload)
    KBSS total:   4840 B (zeroed, no PRG space)
    Free:         2070 B (+ 256 earmarked)

## Stack budget

CSE and user code share the single 256-byte 6502 hardware stack at
`$0100–$01FF`.  This section documents how much of that page is
available to user code when they run it via `j`, `g`, `t`, or `o`.

**Startup resets SP.**  `loader.s::loader_entry` begins with
`ldx #$FF / txs`, wiping whatever BASIC's `SYS` command left.
This is safe because CSE never returns to BASIC — the main loop
is `jmp @loop` and `@exit` halts via its own infinite loop.  Every
subsequent `jsr` therefore layers onto a cleanly empty stack.

**Stack depth at user-code entry.**  Traced from the main loop
through to the `jmp (brk_pc)` inside `debugger.s::@tramp`:

    @loop:         (jmp-loop, no push)
      jsr exec_line                     → 2 B on stack
        jmp (rp_ptr2)  ← command dispatch, no frame
          jmp cmd_{jmp,step,…}  ← tail call, no frame
            jsr run_user                → 4 B
              jsr dbg_enter             → 6 B
                jsr @tramp              → 8 B
                  tsx; stx sp_baseline  ← SP captured here
                  jmp (brk_pc)          ← user code enters

User code therefore starts with **8 bytes** of CSE call-chain on
the stack.  The hardware stack is 256 bytes, minus SP underflow
guard room — in practice the C64 convention is to leave the very
top `$01F6`+ available for IRQ pushes (PC lo/hi + P = 3 bytes),
so CSE effectively has `$0100..$01F6 = 247 bytes` usable.  After
CSE's 8-byte frame, **user code has ≥ 239 bytes** of the hardware
stack free, comfortably above the 230-byte threshold we consider
"sufficient" for any realistic C64 user program.

**Stack-snapshot reservation.**  `$EF00–$EFFF` is earmarked (not
allocated) for a future user-stack snapshot used by the debugger's
`c`-from-subroutine fix — see the BRK TODO in `doc/TODO.md`.  If
and when that snapshot is implemented, `debugger.s` will
`memcpy(page_1 → $EF00)` on debug entry and reverse on exit,
preserving any bytes user code pushed below `sp_baseline`.  CSE
itself is shallow enough (8 B frame) that no CSE-side snapshot is
needed; the original 512 B reservation at `$EF00–$F0FF` has been
halved, with the second 256 B at `$F000` now unreserved free
space.

## Memory Map — PRG Load Image

The PRG file loads at $0801 via `LOAD "CSE",8,1 : RUN`.  At load
time, the file is a flat image:

    $07FF-$0800  PRG load address (2 bytes, file header)
    $0801-$080C  BASIC stub "SYS 2061"
    $080D        Loader code (discardable bootstrap)
      ...        CODE + RODATA payload (raw or compressed)
      ...        KDATA payload (copied to $F100+ and $FF00
                   under KERNAL; KBSS regions are not in file)
    end of file

The loader is the first code to run.  It relocates the payload to
its final position (see § Loader module), then becomes part of the
workspace.  The PRG contains no filler — the file is exactly as
large as the loader + payload.

For release/D64 builds, the payload may be exomizer-compressed.
The loader then contains the decompressor instead of a raw copy
loop.  For development (`make run`), the payload is uncompressed
to keep the build-test cycle fast.

## Memory Map — Cartridge (CRT)

    $0000-$03FF  System
    $0400-$07E7  Screen RAM
    $0800-XXXX   Workspace (output ↑ / source ↓)
    XXXX-$BFFF   CSE ROM (code + rodata, zero RAM cost)
    $C000-$CFFF  CSE RAM (BSS, 4 KB max)
    $D000-$DFFF  I/O
    $E000-$FFFF  KERNAL ROM + banked data (as above)

The CRT build has no loader — CODE + RODATA live in ROM at their
final address.  Only BSS zeroing, KDATA copy, and KBSS zeroing
are needed at startup.  The CRT init code performs these steps
then jumps to `_main`.

## Loader Module (loader.s)

The loader is a **discardable bootstrap** linked into the PRG
build only.  It runs once at startup, then its memory is
reclaimed as workspace.  Analogous to an ELF loader that maps
segments and jumps to the entry point.

**Responsibilities:**
1. Reset the 6502 hardware stack (`ldx #$FF / txs`)
2. Copy CODE + RODATA from the load position to the runtime
   position (XXXX–XXXX+sizeof(CODE+RODATA)-1)
3. Zero BSS (XXXX+sizeof(CODE+RODATA) through $CFFF)
4. Initialize banked region under KERNAL (pure writer, no
   banking needed): copy KDATA to $F100+ and $FF00,
   zero KBSS areas (sym_table, heap, screen save)
5. Jump to `_main` (now at its runtime address)

The loader lives in the LOADER segment, placed at $080D (right
after the BASIC stub).  After step 5, nothing references the
loader — the entire $0800–XXXX range becomes workspace.

For compressed builds, the copy in step 2 is replaced by an
exomizer decrunch call.  The decompressor itself is part of the
loader and equally discardable.

**CRT builds** do not link the loader.  The CRT init code
performs only steps 1, 3–5 (stack reset, BSS zero, banked init,
jump to `_main`), since CODE + RODATA are already in ROM.

**C128 consideration:** The loader architecture does not assume
a specific memory banking model.  A future C128-native loader
could copy code to a different bank or address range without
changing the permanent runtime.

## Memory Manager Module (mem.s)

The memory manager is a **permanent module** that consolidates
all runtime memory services.  It consolidates memory management
code formerly scattered across main.s (fill_free_memory),
symtab.s (kernal banking), meminfo.s (segment queries), and
asm_src.s (workspace symbols).

**Exports:**

| Function | Purpose |
|----------|---------|
| `kernal_bank_out` | SEI + clear $01 bit 1 (honours `kernal_out` flag) |
| `kernal_bank_in` | Set $01 bit 1 + CLI (honours `kernal_out` flag) |
| `kernal_init` | Install NMI trampoline at $FF00 |
| `kernal_out` | BSS flag: nonzero = KERNAL held banked out |
| `cse_start` | Returns runtime start address (XXXX) in A/X |
| `cse_end` | Returns first byte past runtime ($D000) in A/X |
| `cse_zp_end` | Returns first free ZP byte in A |

After the loader (or CRT init) jumps to `_main`, the main loop
calls mem.s functions for one-time setup (BASIC unmap, NMI
trampoline, workspace symbols, free memory fill).

The KERNAL banking functions move from symtab.s to mem.s.
symtab.s imports them like any other module.  The ordering rule
for batch callers (bank before flag, flag before unbank) is
unchanged — see the inline documentation.

## Source Code Storage

Source text lives in a gap buffer at the top of the workspace,
growing downward from the CSE runtime start:

    $0800          workstart (fixed)
      ...          assembled output (grows up)
                     ... free gap ...
    buf_base  ←──  source text (grows down toward $0800)
    XXXX           workend + 1 = CSE runtime start

The `workstart` and `workend` symbols are pre-defined in the symbol
table by `_main` (via `define_ws_syms`), usable in assembly (`.org workstart`) and REPL
expressions (`@ workend`, `j workstart`).  `workstart` is always
$0800.  `workend` adjusts when the editor resizes the gap buffer
(`update_workend` in editor.s).

## Zero Page Layout

### Overview

86 bytes across 13 modules, linker-assigned from $02 upward.
40 bytes free ($58–$7F) for user programs.

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

**ZP overlap** — investigated 2026-04-08, both candidates
unsafe, dropped:

| Overlap | Why unsafe |
|---------|------------|
| Editor scratch ↔ assembler scratch | `asm_src.s` calls `ed_read_line` (`asm_src.s:1204`), which uses `ed_scr`/`ed_tmp` from the editor's ZP block.  Editor ZP is therefore live during the `a` command. |
| Dasm ↔ assembler scratch | `repl.s::cmd_dot` calls `dasm_insn` (`repl.s:765`) inside the `.` command path that *also* runs `asm_line` for verification.  Both modules' ZP are concurrently live. |

The earlier estimate of ~12 B savings was a paper analysis
that didn't trace the actual call graph.  Both overlaps are
blocked by cross-module calls.  No code change.

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
  all multi-arg calls use ZP variables
- Symbol table doubled: 128 → 256 slots, moved to $E000 under KERNAL
- Name heap moved under KERNAL at $E600 (2304B), frees main RAM
- BUF_END raised: $C800 → $D000 (+2KB workspace)
- KDATA tables under KERNAL: 1010B of lookup tables at $F100+
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
