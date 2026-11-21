# Memory Design — Memory maps, banked layout, stack contract, calling convention

**Template:** [subsystem](templates/subsystem.md)

This document owns the memory map, the banked layout under the
KERNAL ROM, the stack contract between the kernel and user code, and
the calling convention.  What user programs may rely on is owned by
[userland_contract.md](userland_contract.md); the zero-page
allocation by [zp.md](modules/zp.md); how the runtime start is
computed by [build_system.md](build_system.md#main-build-pipeline).

**Platform scope.**  The sections without a platform in their name
describe the C64 builds; [§ Memory Map — m65](#memory-map--m65-mega65-mode)
describes the m65 build, and the platform-neutral sections (the
calling convention, the stack contract) say where m65 differs.

## Design Principles

1. **CSE stays out of the developer's way.** The developer's mental
   model: "my program lives at `workstart` and up."  CSE code lives
   above the workspace.

2. **ROM-ready architecture.** Code and RODATA are separable from
   mutable state.  No self-modifying code.  Constants in RODATA,
   runtime state in BSS.  The same source is meant to build as both
   PRG (RAM) and CRT (ROM at $8000).

3. **Mutable state is small and relocatable.** All runtime variables
   live in BSS (zeroed by the loader at boot) or ZP.  No initialized
   DATA segment.

4. **One screen, save/restore.** Both REPL and editor use screen RAM
   at $0400 (m65: the KERNAL's screen, § Memory Map — m65).  Entering the editor saves the REPL screen (1000 bytes)
   to banked RAM under the KERNAL ([§ Banked layout](#banked-layout-e000ffff));
   leaving it restores the screen.  The editor view is always
   reconstructable from the gap buffer; only the REPL screen needs
   saving.

5. **Source and output share the workspace** (c64).  Source text
   grows down from the CSE runtime start (`__CODE_RUN__`), assembled
   output grows up from `workstart`.  The `i` command shows the gap
   between them.  On m65 the source has a region of its own
   ([§ Source Code Storage](#source-code-storage)).

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
registers.  This is preferred for multi-field I/O.  All of these
live in zp.s ([zp.md](modules/zp.md)):

| ZP group | Fields | Used by |
|----------|--------|---------|
| Assembler I/O | `asm_pc`, `asm_out`, `asm_cpu`, `asm_len`, `asm_mode` | asm_line, asm_src |
| Symbol I/O | `sym_name` (ptr), `sym_val`, `sym_wide` | symtab, asm_src, expr, repl |
| Expression I/O | `expr_ptr` (ptr), `expr_val`, `expr_wide` | expr, asm_src, repl |
| Mnemonic chars | `mn_c1`, `mn_c2`, `mn_c3` | mn_classify, mn7/mn6, asm_line |

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
- `asm_line`: `asm_pc`/`asm_out` set by caller, A/X = text
- `ed_read_line`: A/X = buf pointer (maxlen hardcoded)

No software parameter stack.  All arguments pass through registers
or ZP variables.

## Glossary

| Term | Meaning |
|------|---------|
| **CODE** | Executable code in main RAM, from the runtime start up |
| **RODATA** | Read-only constants in main RAM (follows CODE) |
| **BSS** | Uninitialized runtime state in main RAM (follows RODATA; zeroed by the loader; no PRG space) |
| **KDATA** | Read-only tables under the KERNAL ROM, copied from the PRG payload by the loader |
| **KBSS** | Structures under the KERNAL ROM that take no PRG space.  The loader does not clear them; each owner initialises its own ([§ Banked layout](#banked-layout-e000ffff)) |

## Target Compatibility

CSE targets:
- Stock C64 KERNAL ROM
- Stock C128 KERNAL ROM (C64 mode)
- The MEGA65 KERNAL in MEGA65 mode, ROM 920413 (release 0.97) or
  later — the m65 build only; verified on 920413 and 920421
  ([build_system.md § MEGA65 ROM](build_system.md#mega65-rom))
  ([§ Memory Map — m65](#memory-map--m65-mega65-mode))

Stretch targets — not supported until their TODO items close
([TODO § M65 slice 2, Stretch goal](TODO.md#stretch-goal--cse-on-the-open-roms)):
- The Open ROMs' C64 build on C64/C128 hardware (excluding
  MEMORY_MODEL_60K) — `rom/*_mega.bin`, `ROMSET=mega`
- The Open ROMs' MEGA65 build — `rom/mega65_open.rom`, which has no
  C65/MEGA65 KERNAL ([rom/README.md](../rom/README.md#mega65-roms))

The 60K exclusion means $02A7-$02FF remains usable (the 60K model
repurposes this range).  Low memory ($0000-$03FF) is assumed to be
"C64-shaped" across all C64 targets.  The m65 build does not assume
it: its KERNAL variables and internals come from the m65 platform
constants.

## CSE ↔ KERNAL Contract

CSE is a KERNAL-compatible application that replaces BASIC
interaction while active.  It keeps the KERNAL working: the KERNAL's
IRQ handler keeps running, and CSE calls KERNAL routines for the
keyboard, cursor sync and disk I/O.  Which KERNAL cells in zero page
and pages 2–3 CSE writes is listed in
[userland_contract.md § 2](userland_contract.md#2-state-contract).

**CSE owns (sets at cold init, restores on exit):**
- $01 (CPU I/O port — BASIC ROM unmapped)
- $02-$7F (CSE zero page — snapshot of $01–$7F taken at cold init)
- $0316/$0317 (IBRK — BRK dispatch)
- $0318/$0319 (INMIV — NMI dispatch)
- $FFFA/$FFFB (NMI vector RAM shadow — read by the CPU while the KERNAL is banked out)
- $FFFE/$FFFF (IRQ/BRK vector RAM shadow — read by the CPU while the KERNAL is banked out)

**Hook invariant.**  `setup_interrupts` (main.s) installs all four
vectors before the first bank-out, so no interrupt can ever read a
stale RAM vector.  The RAM shadows point at the handlers'
early-entry code; there are no separate trampolines.  Mechanism:
[main.md § setup_interrupts](modules/main.md#setup_interrupts) and
[§ IRQ early-entry bank-out](modules/main.md#irq-early-entry-bank-out).

**Exit obligation.**  `cse_exit_to_basic` puts the machine back as
BASIC expects it: KERNAL vectors reset by RESTOR, $01–$7F restored
from the cold-init snapshot, screen reinitialised, BASIC warm start.
Sequence: [main.md § Exit path](modules/main.md#exit-path).

## User Code Contract

What user code (anything run by `j`, `g`, `c`, `t` or `o`) may use,
what it must preserve, and what CSE does to the machine across a
run is owned by [userland_contract.md](userland_contract.md):
§ 2 (state tiers), § 3 (memory regions), § 4 (stack), § 5 (vector
and banking hazards).

## Memory Map — Runtime (C64 builds)

    $0000-$00FF  Zero page
      $00-$01    CPU I/O port
      $02-$7B    CSE ZP variables (zp.md)
      $7C-$7F    Not allocated by CSE
      $80-$FF    KERNAL work area
    $0100-$01FF  6502 hardware stack (shared CSE + user code)
    $0200-$02A6  KERNAL editor state, input buffer
    $02A7-$02FF  Free (89 bytes)
    $0300-$0333  KERNAL vectors (CSE hooks at $0316, $0318)
    $0334-$03FF  Free (204 bytes; the tape buffer $033C-$03FB inside it)
    $0400-$07E7  Screen RAM (40×25, VIC bank 0)
    $07E8-$07FF  Sprite pointers (unused by CSE)
    $0800        workstart — first free workspace byte
      ...        Assembled output ↑ (grows up)
      ...        Free workspace
    workend      last byte below the source text (buf_base − 1)
      ...        Source text ↓ (grows down)
    runtime start  CSE CODE (page-aligned)
      ...        CSE RODATA
      ...        CSE BSS
      ...        Slack below $D000 (under one page; unused, not cleared)
    $D000-$DFFF  I/O (VIC-II, SID, CIA1, CIA2)
    $E000-$FFFF  Banked data under KERNAL ROM (see § Banked layout)

The ZP lines are the CSE view.  During a user run the whole of
$00–$7F is the user's: CSE swaps it out and in at every transition
([userland_contract.md § 3](userland_contract.md#3-memory-regions)).

**Runtime start.**  CODE, RODATA and BSS are packed together at the
top of main RAM below $D000.  The start address is fixed at link
time by the build ([build_system.md § Main build
pipeline](build_system.md#main-build-pipeline)), so it moves as the
code grows or shrinks; the workspace takes everything below it.
`make size` prints the start, the segment sizes and the slack for a
build, and the `i` command shows the workspace at run time.

BASIC ROM ($A000-$BFFF) is unmapped at startup.  The RAM underneath
is part of the CSE runtime (code spans across $A000 freely).

KERNAL ROM ($E000-$FFFF) remains mapped.  The RAM underneath is
**read** by clearing bit 1 of $01 (`kernal_bank_out` /
`kernal_bank_in`, [mem.md](modules/mem.md)).  The bank toggle runs
with interrupts enabled: an IRQ that fires while the KERNAL is banked
out vectors through the $FFFE RAM shadow to code that banks the
KERNAL in for its IRQ body and restores the interrupted $01
afterwards ([main.md § IRQ early-entry
bank-out](modules/main.md#irq-early-entry-bank-out)); the $FFFA
shadow points straight at `cse_nmi_handler`.  **Writes always pass
through** to the underlying RAM regardless of $01 bit 1, so
pure-writer code (`sym_clear`, `setup_interrupts`, the loader's
KDATA copy, the REPL-screen save in `enter_editor`) does not bank —
only readers do.

The `kernal_out` ZP flag lets long-running batches (`asm_assemble`
over both passes) hold the KERNAL banked out across many inner calls:
while it is set, `kernal_bank_out` and `kernal_bank_in` do nothing.
The ordering rule for batch callers is in
[mem.md § Banking protocol](modules/mem.md#banking-protocol).

### Banked layout ($E000–$FFFF)

    $E000-$E5FF  KBSS   symbol table (256 slots × 6 B = 1536 B)
    $E600-$EEFF  KBSS   symbol name heap (2304 B)
    $EF00-$F0FF  free   (512 B)
    $F100-$F4F1  KDATA  lookup tables (1010 B window)
    $F4F2-$F8D9  KBSS   REPL screen save (1000 B)
    $F8DA-$F958  KBSS   cold-init ZP snapshot (127 B, $01-$7F)
    $F959-$FFF9  free   (1697 B)
    $FFFA-$FFFB  NMI vector shadow → cse_nmi_handler
    $FFFC-$FFFD  Reset vector (untouched)
    $FFFE-$FFFF  IRQ/BRK vector shadow → cse_brk_handler_early

    KBSS 4967 B · KDATA window 1010 B · free 2209 B · vectors 6 B

| Region | Defined in | Initialised by |
|--------|-----------|----------------|
| Symbol table | `sym_table` (symtab.s) | `sym_clear` at cold init and before each assembly |
| Name heap | `SYM_HEAP`/`SYM_HEAP_END` (symtab.s) | `sym_clear` resets the heap pointer; names are written before they are read |
| KDATA | the `KDATA` segment (c64_cse.cfg) | the loader copies it from the PRG |
| REPL screen save | `REPL_SCREEN` (editor.s) | `enter_editor` writes it before `leave_editor` reads it |
| Cold-init ZP snapshot | `COLD_ZP` (main.s) | `_main` at cold init; read by `cse_exit_to_basic` |
| Vector shadows | main.s | `setup_interrupts` |

**KDATA window.**  The KDATA tables must stay inside
$F100–$F4F1, below the REPL screen save.  How much of the window a
build fills depends on its CPU set (`make size` lists KDATA).  The
linker region in `c64_cse.cfg.in` (and `c64_trial.cfg`) is exactly
that window, `start = $F100`, `size = $03F2`, so a KDATA that grows
into the screen save fails the link (test_makefile_guards.py pins
both configs).

## Warmstart entry points

Three entry points in main.s bring the kernel back to a clean state
from anywhere; none of them cold-boots (no BSS re-zero, no KDATA
recopy).  Their bodies and order are owned by
[main.md § Layer 3](modules/main.md#layer-3-reason-named-warmstart-entry-points).

| Entry point | Reason | Composes |
|-------------|--------|----------|
| `cse_recover` | Internal CSE fault (unexpected BRK in kernel code) | hw_reinit + end_debug + refresh; SP := $FF |
| `cse_end_debug` | The user ended the debug session (a `y` at a gate) | end_debug; SP := `kernel_init_sp` |
| `cse_refresh` | The user asked for the view back (RUN/STOP+RESTORE in kernel mode, ESC/CLR, `R`) | refresh; SP := `reg_sp` (the session's user stack is kept) |

A fault recovery also resets the REPL globals (`state`, `cur_addr`,
`block_size`, `cur_device`) — `cse_recover` does not trust them.

### Editor invariant

No warmstart entry point touches `buf_base`, `gap_lo`, `gap_hi`,
`ed_dirty`, `ed_top_ptr`, or the gap-buffer-backed memory in the
workspace region.  The user's source is preserved across **every**
warmstart, fault recovery included.

### Breakpoint invariant

`bp_table` is the user's persistent intent — it survives every
warmstart, fault recovery included (only cold init clears it).  On
m65 a slot names a physical byte (a flat
address), so the intent survives the program's remapping too.  What
changes across `end_debug_body` is the in-memory representation: the
$00 bytes of patched breakpoints are restored to the original
opcodes by `unpatch_all`.  The next run re-patches from `bp_table`.
Table layout: [breakpoints.md](modules/breakpoints.md).

## Stack contract

CSE and user code **share** the single 6502 hardware stack page at
`$0100–$01FF`.  Transitions between kernel and userland are flat
RTI/RTS-driven: their stack handling costs about 20 cycles each
direction (the whole transition's cost: [§ Cost](#cost)).

The kernel is structured as an interrupt service routine
([design_cse_as_kernel.md](design_cse_as_kernel.md)).  After a
break it runs on the user's stack page directly below the user's SP,
with balanced JSR/RTS discipline.

### Invariants

1. **Cold init starts at SP = `STACK_TOP`** (the loader resets it;
   [platform_layer.md § Stack](platform_layer.md#stack)).  Without a
   debug session the kernel's loop runs at SP = `STACK_TOP`.
2. **The kernel never writes a stack byte above the user's SP.**  The
   bytes from the user's SP + 1 up to $01FF are the user's live stack
   (return addresses, the `brk_stub` sentinel, pushed data) and survive
   the break.  The bytes below the user's SP are free for the kernel
   while it runs.
3. **The user leaves at least 64 bytes of stack headroom** below its
   SP for kernel re-entry on a break
   ([userland_contract.md § 4](userland_contract.md#4-stack-contract)).
4. **`in_userland` tracks the mode**, not the SP layout: `$80` while
   user code runs, 0 in the kernel.  It is the single source of truth
   for "kernel or user code running" and drives NMI dispatch.

### Entry and exit

Mechanism and code: [debugger.md § return_to_userland](modules/debugger.md#return_to_userland)
(entry) and [main.md § cse_brk_handler](modules/main.md#cse_brk_handler)
(exit).  The memory-level contract:

- **Entry.**  The kernel switches SP to `reg_sp`.  A fresh start
  (`j`, `g`, and the first run after a cold preview) pushes the
  `brk_stub - 1` sentinel there as the program's top-level return
  address; a resume (`c`, `t`, `o`) does not, because the sentinel of
  the fresh start is still on the user's stack.  An RTI frame built
  from `brk_pc`/`reg_p` enters the user code.
- **Exit.**  A BRK (breakpoint, step breakpoint, the program's own
  `brk`, or `brk_stub` after the top-level RTS) or an NMI enters the
  kernel.  The handler records the user's registers, SP and ZP, then
  sets SP to `reg_sp` and jumps to `main_loop_top`: a
  `setjmp`/`longjmp` with the setjmp implicit at `main_loop_top`.
  The kernel never returns into the frame that started the run.  A
  step chain instead re-enters user code directly.

### Kernel stack budget

The kernel's stack use after a break lands below the user's SP:

- **BRK frame and handler chain** — 3 bytes of CPU frame plus
  `FRAME_DEPTH` (3 on c64, 5 on m65:
  [platform_layer.md § Interrupt frame](platform_layer.md#interrupt-frame))
  plus the handler's short `jsr` chain.
- **The command the user types at the break** — `m`, `.`, `d`, `r`,
  stepping — runs from `main_loop` on the same stack.

The contract is **64 bytes** of headroom below the user's SP
([userland_contract.md § Kernel stack
budget](userland_contract.md#kernel-stack-budget), which also gives
the measured depths).  On every return from user code
`post_run_cleanup` warns `;!stk N` when `reg_sp` is below 64.

### Cost

Stack handling per user-entry:  ~20 cycles (push sentinel, push RTI frame, RTI)
Stack handling per user-exit:   ~20 cycles (BRK hardware + KERNAL push + handler entry)

No copy of the stack page, no bank toggles around a stack swap.  On
c64 the cost of a transition is the ZP swap: two 128-byte copies of
$00–$7F (about 3.6k cycles); on m65 it is two `MAP` switches and a
`B` switch — no swap ([platform_layer.md § Base page](platform_layer.md#base-page)) —
and, at every break, the resident stub's `hyppo_get_mapping` (a
Hypervisor trap, [platform_layer.md § Constants](platform_layer.md#constants))
and `bank_state_swap`'s `KCALL SYSFLAGS`; the way back to the
program calls `SYSFLAGS` again for the program's bits.

## Memory Map — PRG Load Image

The PRG file loads at $0801 via `LOAD "CSE",8,1 : RUN`.  At load
time, the file is a flat image:

    $07FF-$0800  PRG load address (2 bytes, file header)
    $0801-$080C  BASIC stub "SYS 2061"
    $080D        Loader code (discardable bootstrap)
      ...        CODE + RODATA payload
      ...        KDATA payload (copied to $F100+ under the KERNAL;
                   KBSS regions are not in the file)
    end of file

The loader is the first code to run.  It moves the payload to its
run-time position ([§ Loader Module](#loader-module-loaders)), then
becomes part of the workspace.  The PRG contains no filler — the
file is exactly as large as the loader + payload.

For D64 distribution, the PRG is wrapped with exomizer SFX
compression (smaller file, faster disk load).  The SFX stub
decompresses to $0801, then the BASIC stub and loader run normally.
`make run` uses the uncompressed PRG (no decrunch delay).

## Memory Map — Cartridge (CRT)

A planned build (roadmap R5, [TODO.md](TODO.md)):

    $0000-$03FF  System
    $0400-$07E7  Screen RAM
    $0800-...    Workspace (output ↑ / source ↓)
    ...-$BFFF    CSE ROM (code + rodata, zero RAM cost)
    $C000-$CFFF  CSE RAM (BSS, 4 KB max)
    $D000-$DFFF  I/O
    $E000-$FFFF  KERNAL ROM + banked data (as above)

The CRT build has no loader — CODE + RODATA live in ROM at their
final address.  Its init code zeroes BSS, copies KDATA, then jumps
to `_main`.

## Memory Map — m65 (MEGA65 mode)

The m65 build is a native MEGA65-mode program on the MEGA65 KERNAL,
within the ROM floor of [platform_layer.md § Platforms and
defines](platform_layer.md#platforms-and-defines).  The PRG
installs this machine ([build_system.md § The m65 builds](build_system.md#the-m65-builds));
CSE runs the REPL, the editor (in the three text modes), the
assembler, the debugger and the disk in it, and `Q` returns to
BASIC 65.  The monitor takes 28-bit flat addresses and reads the
program's CPU view through its map
([repl.md § Banks (m65)](modules/repl.md#banks-m65)), user code
also starts in banks 1, 4 and 5 as `JSRFAR` would start it
([repl.md § Far starts](modules/repl.md#far-starts)), expressions
carry 32-bit values
([expr.md § 32-bit values (m65)](modules/expr.md#32-bit-values-m65)),
and CSE's code and data — the cold code (KCODE) with the rest — fill
one area of bank 3 across the code window and the data window, the
help text the reserve above (below).
Its premise is the machine a BASIC 65 program finds when `RUN` starts
it through its `SYS` line; user programs run in that machine, and CSE
keeps out of it.  The facts below that are not book citations were
recorded in xmega65 ([platform_layer.md § Platform references](platform_layer.md#platform-references)).

**The run premise.**  At the `SYS` entry of a RUN-started PRG: `A X Y
Z B` = 0; P = `$20` — `E` = 1 (an 8-bit stack in page 1), `I` = 0,
`D` = 0; SP = `$01EF`, a return address on top that leads to the
KERNAL's `SYS` return path in page 3, which restores BASIC's map; the
user map below; CPU port `$FF`/`$85`; `$D030` = `$64`; 80 × 25 at
`0.0800`, the MEGA65 I/O personality, 40 MHz; `0.1600–0.1EFF`
untouched.  What of this a program run under CSE can rely on is
[userland_contract.md § 3](userland_contract.md#3-memory-regions)'s.

**Two 16-bit maps.**  CSE uses two `MAP` settings, switched at every
kernel ↔ user transition by the resident stub.  Both keep
`$0000–$1FFF` in bank 0, I/O at `$D000` and the KERNAL at `$E000` →
`3.E000` — the jump table's and the interrupt handlers'
prerequisites — and both leave `$D030` as the KERNAL has it, so
`$C000–$CFFF` is the **interface ROM** (`2.C000`), which the KERNAL
needs (its default `IBRK` handler is there).

    CSE map   $0000–$1FFF  bank 0: KERNAL variables, screen, stack, CSE's base page and stub
              $2000–$7FFF  → 3.2000  the code window: CODE + RODATA (24 K)
              $8000–$BFFF  → 3.8000  the data window (16 K)
              $C000–$CFFF  the interface ROM
              $D000–$DFFF  I/O         $E000–$FFFF  → 3.E000  KERNAL
              MAPLO $E300 (X=$E3 A=$00)  ·  MAPHI $B300 (Z=$B3 Y=$00): one offset, $30000

    user map  $0000–$BFFF  bank 0 RAM
              $C000–$CFFF  the interface ROM
              $D000–$DFFF  I/O         $E000–$FFFF  → 3.E000  KERNAL
              MAPLO $E000 (X=$E0 A=$00)  ·  MAPHI $8300 (Z=$83 Y=$00)

The CSE map is BASIC 65's own map at the READY prompt: CSE takes
BASIC's place in BASIC's map.  The user map is the KERNAL's `SYS`
map.  **No other window is possible:** `MAP` has one offset per 32 K
half; the KERNAL at `$E000` pins the upper half to `$30000`
(interrupts — the NMI included — fetch their vectors and run through
the map), and the lower half holds bank 0's `$0000–$1FFF` and the
code window.  Memory outside the two windows is reached through far
pointers ([platform_layer.md § Far memory](platform_layer.md#far-memory)).

**Banks and what occupies them.**  Who may use what is
[userland_contract.md § 3](userland_contract.md#3-memory-regions)'s.

    0.0000–0.0001  base page 0: the CPU port                    the user (swapped)
    0.0002–0.0009    the KERNAL's far-call cells                the KERNAL
    0.000A–0.008F    BASIC 65's cells, free under CSE           the user
    0.0090–0.00FA    the KERNAL's cells                         the KERNAL
    0.00FB–0.00FF    free                                       the user
    0.0100–0.01FF  the stack (8-bit, E = 1), top at $01F1       shared
    0.0200–0.15FF  KERNAL variables; the screen at 0.0800       the KERNAL
                   (40 × 25 and 80 × 25)
    0.1600–0.1EFF  free for programs                            —
    0.1F00–0.1FAF  CSE's base page (B = $1F)                    CSE
    0.1FB0–0.1FFF  the resident stub                            CSE
    0.2000–0.BFFF  the program region                           —
    0.C000–0.FEFF  RAM behind the interface ROM, I/O, KERNAL    —
    0.FF00–0.FFFF  reserved (book 14-11): shared vectors and    —
                   trampolines across maps; not handed over
    1.0000–1.1FFF  DOS buffers                                  the KERNAL
    1.2000–1.F6FF  free (BASIC's arrays when BASIC runs)        —
    1.F700–1.FFFF  reserved; the colour RAM window              the KERNAL
    2.0000–2.3FFF  CBDOS                                        the KERNAL
    2.4000–2.BFFF  the source region (32 K)                     CSE
    2.C000–2.CFFF  the interface ROM                            the KERNAL
    2.D000–2.FFFF  the directory buffer (`$`; 12 K, a full      CSE
                   D81 directory takes under 10 K); the screen
                   under the help window
    3.0000–3.1FFF  the monitor                                  the ROM
    3.2000–3.9EFF  CODE, RODATA, KDATA, KCODE, BSS              CSE
    3.9F00–3.BFFF  symbol table and heap,                       CSE
                   REPL screen save (sized for 80 × 50)
    3.C000–3.CFFF  reserve (4 K): the help popup's text         CSE
    3.D000–3.DFFF  character set B                              the ROM
    3.E000–3.FFFF  KERNAL                                       the KERNAL
    4.0000–5.FFFF  free, except the screen in 80 × 50           the KERNAL's screen
                   (4.0800–4.179F; the KERNAL writes nothing     in 80 × 50
                   else in banks 4–5, measured on M65Emu)
    800.0000+      Attic RAM                                    —

**CSE's window (`3.2000–3.9EFF`).**  The CSE map's two halves have one
offset, `$30000`, so the code window and the data window show bank 3
contiguously from `$2000` to `$BFFF`: CODE, RODATA, KDATA, KCODE (the
cold code, glossary) and BSS are one linker area, packed in that order
across the two halves, bounded below the fixed homes — nothing is
placed per window
([build_system.md § The m65 builds](build_system.md#the-m65-builds)).
Above it, the C64's under-KERNAL homes at fixed addresses,
page-aligned as the C64's (symtab.s indexes its table from a page
boundary):

    3.2000–3.9EFF  CODE, RODATA, KDATA, KCODE, then BSS (31.75 K; the linker bounds it)
    3.9F00–3.A6FF  SYM_TABLE: the symbol table (256 × 8 bytes: 32-bit values)
    3.A700–3.AFFF  SYM_HEAP … SYM_HEAP_END ($B000): the name heap
    3.B000–3.BF9F  REPL_SCREEN: the REPL screen save (80 × 50 = 4000)
    3.BFA0–3.BFFF  free

`HIMEM` (`cse_end`) is `PROG_HI + 1` = `$C000`: the first byte past
the program region, which is what the user's map offers
([mem.md § cse_end](modules/mem.md#cse_end)).

CSE's regions in banks 2–3 held C65 BASIC, BASIC 65's graphics
material and the C64-mode ROMs (C64 BASIC, C64 KERNAL, character sets
A and C) — nothing the MEGA65-mode KERNAL uses: with all of them
zeroed, the KERNAL's IRQ, the calls CSE makes and the ESC 4 / 5 / 8
mode switches behave identically.  Banks 2–3 are RAM the Hypervisor
loads and write-protects; the loader makes them writable
(`hyppo_rom_writeenable`), and quitting reloads them (`hyppo_reset`,
[platform_layer.md § Constants](platform_layer.md#constants)).  BASIC
65 and C64 mode are gone for the session.

**CSE's base page and the resident stub (`0.1F00`).**  BASIC 65's
bitmap-graphics base page, idle while CSE runs: `0.1F00–0.1FAF` is
CSE's zero page ([zp.md](modules/zp.md)), `0.1FB0–0.1FFF` the
resident stub — CSE's only code in bank 0, visible in both maps
because `$0000–$1FFF` is unmapped in both.  It switches the maps at
every transition, enters `_main` at cold start, and holds `brk_stub`
([mem.md § The resident stub](modules/mem.md#the-resident-stub-m65-only)).

**Interrupts.**  `MAP` holds off interrupts until the next `EOM`, so
a map switch is atomic; `EOM` releases that hold and leaves the I
flag as it was (recorded — the book's "re-enables interrupts (similar
to CLI)", 14-23, describes the hold, not the flag).  The KERNAL's
interrupt entry keeps the current map, so its IRQ runs in either map,
and a BRK or an NMI reaches the resident stub whichever map was
current ([platform_layer.md § Interrupt frame](platform_layer.md#interrupt-frame)).

**The installed machine.**  After the loader
([loader.md § Design](modules/loader.md#design)): the resident stub
at `0.1FB0`, CSE's base page cleared but for the stub's cold target
(`_main`; the stub's targets live in the base page, [zp.md](modules/zp.md)),
CODE + RODATA + KDATA + KCODE at `3.2000`, the help text at `3.C000` and BSS cleared,
banks 2–3 writable; control in `_main` under the CSE map with `B =
$1F`.  The PRG image:

    $1FFF–$2000  PRG load address (file header)
    $2001–$200C  the SYS line "SYS 8205"
    $200D        loader (discardable; its DMA jobs are data)
      ...        the stub image, the CODE + RODATA image, the KDATA image

The D81's PRG is the same file
([build_system.md § The m65 builds](build_system.md#the-m65-builds)).

**Instructions.**  All code is 6502 code; the 45GS02-only
instructions the platform bodies use are raw bytes
([platform_layer.md § Raw-byte instructions](platform_layer.md#raw-byte-instructions)).

**Screen.**  80 × 25 at `0.0800` by default; 40 × 25 (also at
`0.0800`) and 80 × 50 (at `4.0800`, 50 rows) by the screen editor's
ESC 4 / ESC 5 / ESC 8.  The base, width and height are read from the
hardware and the KERNAL, never assumed
([platform_layer.md § Display](platform_layer.md#display)).

## Loader Module (loader.s)

The loader is a **discardable bootstrap** linked into the PRG build
only: it runs once at startup, moves CODE + RODATA to the runtime
start, zeroes BSS, copies KDATA under the KERNAL and jumps to
`_main`.  After that nothing references it — its bytes are part of
the workspace.  It does not bank and does not touch KBSS or the
vectors (`setup_interrupts` installs those at cold init).  Steps and
copy direction: [loader.md](modules/loader.md).  On m65 the loader
also installs the resident stub and makes the ROM banks writable
([§ Memory Map — m65](#memory-map--m65-mega65-mode)).

## Memory Manager Module (mem.s)

mem.s is the permanent home of the memory services: KERNAL banking
with the `kernal_out` batch flag, the CPU-port-aware ZP save/restore
used at every kernel↔userland transition, and the runtime-extent
queries (`cse_start`, `cse_end`, `cse_zp_end`).  On m65 it has no
ZP save/restore (no swap) and hosts the resident stub instead.
Interface: [mem.md](modules/mem.md).

## Source Code Storage

Source text lives in a gap buffer at the top of the workspace,
growing downward from the CSE runtime start:

    $0800          workstart (fixed)
      ...          assembled output (grows up)
                     ... free gap ...
    workend        buf_base − 1
    buf_base  ←──  source text (grows down toward $0800)
      ...
                   CSE runtime start

The `workstart` and `workend` symbols are pre-defined in the symbol
table (`define_ws_syms`, gap_buffer.s, called by `_main` at cold init
and by `asm_assemble` before and after its passes) and usable in
assembly (`.org workstart`) and REPL expressions (`@ workend`,
`j workstart`).  `workstart` is always $0800.  `workend` is
`buf_base − 1` and moves when the gap buffer is reset or grows:
`update_workend` (gap_buffer.s) runs from `ed_init` (editor.s) and
from `gb_ensure_room` after a gap grow.

On m65 the gap buffer is not in the workspace: it is the 32 K source
region `2.4000–2.BFFF` (`BUF_FLOOR` … `BUF_END`, constants of the
platform layer, so the region moves by changing them), and the
program region `0.2000–0.BFFF` is wholly the user's: `workstart` is
`$2000` and `workend` `$BFFF`, fixed
([§ Memory Map — m65](#memory-map--m65-mega65-mode)).  The buffer's
pointers are far pointers with the source bank
([platform_layer.md § Far memory](platform_layer.md#far-memory)).

## Zero Page Layout

The allocation of $02–$7B — every variable, its address and its
module — is owned by [zp.md](modules/zp.md) (source: `src/zp.s`).
$7C–$7F are not allocated by CSE.  On c64 user code may use all of
$00–$7F, since CSE swaps the whole range
([userland_contract.md § 3](userland_contract.md#3-memory-regions));
on m65 CSE's zero page is its own base page, `0.1F00`, and base page
0 is the user's ([platform_layer.md § Base page](platform_layer.md#base-page)).

### Sharing ZP between modules

Modules that never run at the same time could share ZP addresses
([project.md § Implementation Principles](project.md#1-zp-is-precious--use-the-stack-for-scratch)).
The two obvious candidates do overlap at run time, so they keep
separate blocks:

| Overlap | Why it is unsafe |
|---------|------------------|
| Editor scratch ↔ assembler scratch | `asm_src` reads source lines through `ed_read_line` (gap_buffer.s), which uses the editor's ZP block.  Editor ZP is live during `a`. |
| Disassembler ↔ assembler scratch | The REPL `.` command disassembles (`dasm_insn`) and assembles (`asm_line`) in the same command.  Both modules' ZP are live together. |

### KERNAL ZP locations (read/written directly)

The KERNAL cells CSE reads or writes — cursor position and line
pointers, the cursor-blink switch, the keyboard-buffer count, the
screen-line link table — are listed with what writes them in
[userland_contract.md § 2](userland_contract.md#2-state-contract).
