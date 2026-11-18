# Platform Layer — The seams between CSE and the machine (c64, m65, c128)

**Template:** [subsystem](templates/subsystem.md)

This document owns the *platform driver layer*: the set of seams
through which CSE touches the machine it runs on — KERNAL entry
points and cells, banking and memory maps, the interrupt frame, the
screen, the keyboard, the loader — and the contract of each seam per
platform.  Above the seams CSE is one program; below them each
platform has its own body.  The memory maps themselves are owned by
[memory_design.md](memory_design.md), what user programs may rely on
by [userland_contract.md](userland_contract.md), the build by
[build_system.md](build_system.md); the module docs of the modules
that *host* a seam point here for its per-platform body.

## Owned files

| File | Role |
|------|------|
| `src/platform.inc` | header — every platform constant, selected by `.ifdef` (planned, P0-3) |
| `src/mem.inc` | header — the user-memory access macros (planned, P0-3) |
| `dev/audit_platform_literals.py` | implementation — the literal audit (planned, P0-3) |
| `tests/unit/test_platform_audit.py` | test contract — the audit's rule and the byte-identical gate (planned, P0-3) |

The files are listed as they will exist; until P0-3 lands they are
not in the repository.

## The rule

**No platform knowledge above the seams.**  A ROM address, a KERNAL
cell, a VIC, SID, CIA or MMU register, a screen or colour base, a
banking value, the shape of an interrupt frame — every such fact
appears in exactly one of two places: as a constant in
`src/platform.inc`, or inside the platform body of a seam in the
module that hosts it.  Nothing else in `src/` names one.  The audit
(`dev/audit_platform_literals.py`) enumerates the literals and fails
on any outside those places; it is part of the test tree.

**One module, one interface, bodies selected at assembly time.**  A
seam is one exported name (or one macro) with one contract; its
platform bodies live in the same module under `.ifdef PLATFORM_C64`
/ `.ifdef PLATFORM_M65` / `.ifdef PLATFORM_C128` (never `.if
PLATFORM = n`: the ca65 `.if`-inside-`.proc` caveat).  No parallel
modules, no duplicated bodies.

**Zero cost on the C64 builds.**  The layer is assembly-time only —
constants, macros and `.ifdef` bodies; no jump tables, no vectors, no
added `jsr` levels.  Moving the C64 build onto the seams leaves every
C64 release PRG byte-identical, and every later platform body is
invisible to the C64 builds: the slice-1 hard constraint (no C64
build grows or slows for m65) holds by construction, and the size
and golden gates ([build_system.md § Size gate](build_system.md#size-gate))
stand guard.

Rules of thumb for the shape of a seam: a **constant** for an
address or a cell; a **macro** for an inline site whose instruction
differs (`lda (p),y` against `lda [p],z`); an **`.ifdef` body inside
the existing proc** for a routine-sized difference; a **separate
proc** only where the body is already a proc.

## Platforms and defines

| Platform | Define | Machine | Status |
|---|---|---|---|
| c64 | `PLATFORM_C64` | C64 (and the C128 in C64 mode), stock KERNAL or Open ROMs | shipping; the column below is the current code |
| m65 | `PLATFORM_M65` | MEGA65 in MEGA65 mode, on BASIC 65 and the MEGA65 KERNAL | R7 slice 2 ([TODO](TODO.md#m65-slice-2--the-mega65-platform-r7-platform-layer)) |
| c128 | `PLATFORM_C128` | C128 in C128 mode (MMU, VDC) | reserved — R3 / R4 ([TODO § Roadmap](TODO.md#roadmap)); the seams are shaped so it adds a column, not a refactor |

The Makefile passes exactly one platform define to every assembly,
the C64 builds included, so a site may test any of the three.  A
seam whose body is the same on two platforms states so once; it does
not carry two copies.

## The seams

| Seam | Host | What the upper layers see |
|---|---|---|
| [Constants](#constants) | `platform.inc` (L0) | named addresses and cells; never a literal |
| [Banking](#banking) | mem.s (L1) | `kernal_bank_out` / `kernal_bank_in`, the `kernal_out` batch flag |
| [User memory](#user-memory) | `mem.inc`, mem.s (L1) | `UMEM_PTR`, `UMEM_LDA`, `UMEM_STA`, `umem_copy` |
| [Source text](#source-text) | gap_buffer.s (L3) through the user-memory seam | the gap buffer's bytes, wherever they live |
| [User transitions](#user-transitions) | mem.s (L1) | `plat_user_enter`, `plat_user_leave` |
| [Vectors](#vectors) | main.s (L5) | `plat_vectors_install`, `plat_vectors_restore` |
| [Interrupt frame](#interrupt-frame) | `platform.inc`; debugger.s, main.s | `FRAME_DEPTH` and the frame offsets derived from it |
| [IRQ early entry](#irq-early-entry) | main.s | present on platforms whose KERNAL can be unmapped; absent elsewhere |
| [Cold start and exit](#cold-start-and-exit) | main.s | `plat_hw_init`, `cse_exit_to_basic`, `PLAT_COLD_START` |
| [Terminal](#terminal) | cse_io.s (L1) | `io_init`, `io_sync`, `io_getc`, `io_kbhit`, `io_stop_down`, `scr_lo`/`scr_hi`, the width |
| [Display](#display) | screen.s (L2) | `vic_reset`, `restore_colors`, `kernal_screen_reset`, `reset_screen`, `scroll_up`, `cursor_show`/`hide`, `screen_mode_set`, `screen_geometry` |
| [Screen save](#screen-save) | editor.s through `umem_copy`; its home from `platform.inc` | the REPL screen saved and restored around the editor |
| [Disk bank](#disk-bank) | disk.s | `PLAT_SETBNK` before `OPEN`, `LOAD`, `SAVE` |
| [Info map](#info-map) | repl.s | the rows of the `i` command |
| [Loader](#loader) | loader.s (L6) | `loader_entry`; the cartridge bootstrap is the same body under `PLAT_CRT` |

Layering ([architecture.md](architecture.md)): the layer is a *role*
of the existing leaves, not a new layer.  `platform.inc` is L0 data;
mem.s and cse_io.s are the L1 drivers; screen.s the L2 display
driver; main.s and loader.s keep their platform-bound entry and exit
bodies because they *are* the dispatcher's entry and exit.  Every
other module — editor, repl, asm_src, disk, debugger, breakpoints,
log — carries no platform knowledge and calls the seams.

## Seam contracts

Each seam states its contract once, then its body per platform.  A
platform column marked *stated with its milestone* is filled in by
that milestone's Step-1 doc delta; the c64 column is the current
code.

### Constants

`src/platform.inc`, included by every module that needs one.  Each
constant is defined once per platform under `.ifdef`; a constant a
platform lacks is simply absent there, so a stray use fails to
assemble.

| Group | c64 | m65 | c128 |
|---|---|---|---|
| KERNAL entries CSE calls | `CHROUT $FFD2`, `GETIN $FFE4`, `PLOT $FFF0`, `RESTOR $FF8A`, `CINT $FF81`, `STOP $FFE1`, the file API `SETLFS $FFBA` … `CLALL $FFE7` | the same addresses for these ([book I-5/6](#platform-references)); plus `VECTOR $FF8D`, `SETBNK $FF6B`, `SCRORG $FFED`, `CURSOR $FF35`, `SYSFLAGS $FF47`, `VERSIONQ $FF2F`, `RESET_RUN $FF32`, `PRIMM $FF7D` | reserved |
| KERNAL internals called directly | `$EA31` (IRQ body), `$EA81`, `$FE43`, `$F8DA`, `$E544`, `$E9D6`, `$FCE2` (cold start), `$F6ED` — see [userland_contract.md § 6](userland_contract.md#6-kernal-as-terminal-affordance) | **none** — every use is a jump-table call or absent (the IRQ early entry does not exist) | reserved |
| KERNAL cells | cursor `$D3` (col) / `$D6` (row), line pointers `$D1`/`$F3`, blink switch `$CC`, key count `$C6`, STOP row `$91`, status `$90`, `CHRCOLOR $0286`, charset lock `$0291`, `TXTTAB $2B` | `$90` status; the rest are replaced by API calls (`PLOT`, `CURSOR`, `GETIN`, `STOP`, `SYSFLAGS`) or by the typing-queue registers — no cell of `0.0002–0.15FF` is written directly except the I/O status | reserved |
| Vector table | `$0314` (`IIRQ`), `$0316` (`IBRK`), `$0318` (`INMI`), written directly; RAM shadows `$FFFA`/`$FFFE` | the same table, reached only through `VECTOR`/`RESTOR` (offsets 0, 2, 4); no shadows | reserved |
| `FRAME_DEPTH` | 3 (the KERNAL pushes A, X, Y) | 5 (A, X, Y, Z, B) | 3 |
| Screen | `SCREEN $0400`, `COLOR_RAM $D800`, 40 × 25, VIC-II `$D011`–`$D021`, SID `$D400` | the screen base is runtime (`$D060–$D063`), colour RAM at `FF8.0000` + `$D064/5`, width and height from `SCRORG`; VIC-IV registers; SID `$D400` | VIC-II or VDC |
| Memory bounds | `HIMEM $D000`, `workstart $0800`, the KDATA/KBSS homes under the KERNAL | the two maps of [memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode): the stub at `0.1600`, the user's `0.2000–0.CFFF`, the source region's end `1.F700`, the data bank `3.8000` | reserved |
| Cold start / exit entries | `$FCE2`; exit by `CINT` + `jmp ($A002)` | `RESET_RUN` A=1 for both | reserved |
| CPU-port seeds | `$00 = $2F`, `$01 = $36` | `$00 = $3F`, `$01 = $35` (MEGA65 mode's values; `MAP` overrides them for mapped blocks) | reserved |

### Banking

`kernal_bank_out` / `kernal_bank_in` — mem.s,
[mem.md § Interface](modules/mem.md#interface).  Contract: between a
`kernal_bank_out` and the matching `kernal_bank_in` the data area
under the KERNAL is readable; writes to it pass through at all
times; both are no-ops while the `kernal_out` batch flag is set; the
I flag is never touched; **Clobbers:** A.

| Platform | Body |
|---|---|
| c64 | `$01` bit 1 cleared / set; an IRQ in between is carried by the [IRQ early entry](#irq-early-entry) |
| m65 | **both are no-ops** (and assemble to `rts`): nothing of CSE's is under the KERNAL — the data area is in the data bank, always mapped in the CSE map ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)).  `kernal_out` is kept (its readers are platform-neutral) and means nothing |
| c128 | MMU configuration register `$FF00` |

### User memory

`src/mem.inc` macros, with `umem_copy` in mem.s.  Contract: the
upper layers address *user memory* — the memory a user program sees
at a 16-bit address — through these and nothing else:

- `UMEM_PTR ptr, addr_lo, addr_hi` — point `ptr` at a 16-bit user
  address (the platform adds its bank).
- `UMEM_LDA ptr` / `UMEM_STA ptr` — `A` ← / → the byte at `ptr` +
  the index register the platform's instruction takes.  Clobbers
  nothing but A (load) and the flags.
- `umem_copy` — a block between user memory and CSE data, size in
  A/X; **Clobbers:** A, X, Y and the platform's scratch.

The users of the seam are the assembler's emit paths (asm_src
`_emit_byte`, asm_line), the REPL's `m`, `.` and `d`, the
disassembler's fetch, breakpoint patching and un-patching, the
editor's screen save and the gap buffer.  What user memory *is* per
platform is [userland_contract.md § 3](userland_contract.md#3-memory-regions).

| Platform | Body |
|---|---|
| c64 | `(ptr),y` with a 2-byte ZP pointer — the instruction the code has today; user memory is the workspace, directly addressable |
| m65 | `[ptr],Z` flat 28-bit access with a 4-byte ZP pointer (lo, hi, bank, 0), the index in `Z`; the raw bytes come from `src/m45_ops.inc`; `umem_copy` is a DMA job.  User memory is bank 0 and is *not* visible through the CSE map's `$2000–$BFFF`, which holds CSE itself |
| c128 | `(ptr),y` with the MMU's bank for the access |

Pointer width differs by platform, so the ZP pointers the seam's
users own are allocated by [zp.md](modules/zp.md) with the
platform's width.

### Source text

The gap buffer ([gap_buffer.md](modules/gap_buffer.md)) addresses
its bytes through the [user-memory seam](#user-memory) with its own
pointer; where the text lives is a platform fact of
[memory_design.md § Source Code Storage](memory_design.md#source-code-storage):
the workspace below the runtime on c64; `1.2000–1.F6FF`, growing down
from `1.F700`, on m65 (its base and cap are one pointer pair, so the
region relocates by changing them); RAM 1 on c128.

### User transitions

`plat_user_enter` / `plat_user_leave` — mem.s.  Contract:
`plat_user_enter` is the last thing the kernel does before control
reaches user code (called from `return_to_userland`,
[debugger.md](modules/debugger.md)); `plat_user_leave` the first thing
the break path does after the KERNAL has delivered the interrupt
(called from the break and NMI handlers, [main.md](modules/main.md)).
Between them the machine is the *user machine* of
[userland_contract.md](userland_contract.md).  Neither touches the
registers the handlers have saved; **Clobbers:** A (and the
platform's map state).

| Platform | Body |
|---|---|
| c64 | nothing but the KERNAL banked in (`$01`): the user machine *is* the kernel machine with the KERNAL mapped |
| m65 | `MAP` to the user map / to the CSE map, executed in the resident stub at `0.1600` ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)): the stub is the only code reachable in both maps |
| c128 | MMU configuration |

### Vectors

`plat_vectors_install` / `plat_vectors_restore` — main.s
([main.md § setup_interrupts](modules/main.md#setup_interrupts)).
Contract: after `plat_vectors_install` a BRK and an NMI in user or
kernel code reach `cse_brk_handler` and `cse_nmi_handler`, whatever
the memory configuration at the moment of the interrupt; the IRQ
keeps running the KERNAL's own handler; `plat_vectors_restore` puts
the KERNAL's defaults back.  Called with interrupts disabled;
**Clobbers:** A, X, Y.

| Platform | Body |
|---|---|
| c64 | writes `$0316`/`$0318` and the RAM shadows `$FFFA`/`$FFFE` (read by the CPU while the KERNAL is banked out); restore by `RESTOR` |
| m65 | `VECTOR` reads the 56-byte table into CSE data, `IBRK` (offset 2) and `INMI` (offset 4) are pointed at the resident stub's entries, `VECTOR` writes it back; no shadows — the KERNAL is mapped in every map CSE allows; restore by `RESTOR` |
| c128 | `$0316`/`$0318`; restore by `RESTOR` |

### Interrupt frame

`FRAME_DEPTH` (`platform.inc`): the number of bytes the KERNAL's
interrupt entry pushes after the CPU's three (P, PC) before it
dispatches through the vector table.  `save_userland_state`
([debugger.md](modules/debugger.md)) and the handlers in main.s derive
every stack offset from it, and the register snapshot (`reg_a`,
`reg_x`, `reg_y`, …) is filled from the frame by the constant's
layout; the m65 frame also carries `Z` and `B`, which the kernel
saves and restores with the others.

| Platform | Frame (top → bottom) |
|---|---|
| c64 | Y X A · P PCL PCH (`$FF48`) |
| m65 | B Z Y X A · P PCL PCH (book I-80) |
| c128 | Y X A · P PCL PCH |

### IRQ early entry

`cse_brk_handler_early` and `bank_out_stub`
([main.md § IRQ early-entry bank-out](modules/main.md#irq-early-entry-bank-out))
exist on a platform whose KERNAL can be unmapped while interrupts are
enabled, and nowhere else.

| Platform | Body |
|---|---|
| c64 | the `$FFFE` RAM shadow's target: classifies BRK against IRQ, banks the KERNAL in for `$EA31`'s body, restores the interrupted `$01` |
| m65 | **absent** (`.ifdef PLATFORM_C64`): the KERNAL is always mapped |
| c128 | present in its MMU form, or absent, settled by R3 |

### Cold start and exit

`plat_hw_init` (the hardware part of `_main`'s cold init),
`cse_exit_to_basic` and the `PLAT_COLD_START` fallback — main.s
([main.md § _main](modules/main.md#_main), [§ Exit path](modules/main.md#exit-path)).
Contract: after `plat_hw_init` the machine is in CSE's configuration
(memory, vectors not yet installed, the charset lock set); after
`cse_exit_to_basic` the machine is the host BASIC's again; the
fallback restarts the machine when recovery is impossible.

| Platform | Body |
|---|---|
| c64 | `$01` (BASIC ROM out), `$0291 ← $80`; exit: `RESTOR`, `$01`–`$7F` from the cold snapshot, `CINT`, `jmp ($A002)`; fallback `$FCE2` |
| m65 | the I/O personality knock (`$D02F ← $47, $53`), `SYSFLAGS` for the charset lock; exit **and** fallback: `RESET_RUN` A=1 — the Hypervisor reloads the ROM BASIC's banks that CSE overwrote ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)); nothing is restored by hand |
| c128 | MMU; exit through the C128 KERNAL |

### Terminal

cse_io.s ([cse_io.md § Interface](modules/cse_io.md#interface)).  The
contract of every exported routine is the module's and does not
change per platform; what changes is the body of these:

| Routine | c64 | m65 | c128 |
|---|---|---|---|
| `io_init` | `$CC ← 1` (blink off) | `CURSOR` C=1 | `$CC`-equivalent |
| `io_sync` | `PLOT` C=0 | `PLOT` C=0 (window-relative; the window is the full screen) | `PLOT` |
| `io_getc` / `io_kbhit` | `GETIN`; `$C6` | `GETIN`; `$D60A` bit 7 (queue not empty) | `GETIN`; `$D0` |
| `io_stop_down` | `$91 = $7F` | `STOP` (`$FFE1`) | the C128 STOP row |
| `scr_lo` / `scr_hi`, the width | RODATA tables of `$0400` + 40·row; `COLS = 40` immediate | filled at init and after a mode switch from `$D060–$D063` and `SCRORG`: the width is a variable, the tables are BSS | VDC or VIC tables |
| `io_blip` | SID `$D400` | the same SID | the same SID |

The m65 bodies and the key codes of the MEGA65's new keys are
*stated with P2* ([TODO](TODO.md#m65-slice-2--the-mega65-platform-r7-platform-layer)).

### Display

screen.s ([screen.md § Interface](modules/screen.md#interface)).  As
for the terminal: the routines' contracts are the module's; the
bodies differ.

| Routine | c64 | m65 | c128 |
|---|---|---|---|
| `vic_reset` | VIC-II mode registers to text mode | VIC-IV: the KERNAL's text mode re-asserted through the registers of the current mode | VIC-II / VDC |
| `restore_colors` | border, background, `$0286`, 1000-byte `$D800` fill | border, background, the KERNAL's colour, a DMA fill of width × height bytes at `FF8.0000` + `$D064/5` | VIC-II / VDC |
| `kernal_screen_reset`, `reset_screen` | KERNAL line-link table and `CINT`-shaped reset | `BSOUT` control codes (clear, home) | the same through the C128 editor |
| `scroll_up`, `newline` | row copy through `scr_lo`/`hi` | the same through the runtime tables (or one DMA job) | the same |
| `screen_mode_set` (new) | no-op (40 × 25 only) | prints `ESC 4` / `ESC 8` / `ESC 5` through `BSOUT`, then `screen_geometry` | VDC / VIC switch (R4) |
| `screen_geometry` (new) | constants | reads `SCRORG` and `$D060–$D063`, fills the terminal's tables and width | VDC or VIC |

*Stated with P2.*

### Screen save

The editor saves and restores the REPL screen around itself
([editor.md](modules/editor.md)) through `umem_copy`; the buffer's
home is a constant: under the KERNAL (`REPL_SCREEN`) on c64, in the
data bank on m65 (sized for the largest mode, 80 × 50), RAM 1 on
c128.

### Disk bank

`PLAT_SETBNK` (macro, `platform.inc`) precedes every `OPEN`, `LOAD`
and `SAVE` in disk.s ([disk.md](modules/disk.md)): nothing on c64;
`SETBNK` with the user bank for the data and the filename on m65
(`$FF6B`) and c128 (`$FF68`).

### Info map

The rows of the `i` command ([repl.md](modules/repl.md)) are a data
block per platform (`.ifdef`), each stating that platform's map in
[memory_design.md](memory_design.md)'s terms.

### Loader

`loader_entry` ([loader.md](modules/loader.md)) is one entry with a
body per platform: the C64's copy loop; the m65's install sequence
([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode))
— stub copy, ROM write protection off, DMA of the payload into the
code bank, the data bank cleared, then the stub's `MAP` and `_main`;
the cartridge bootstrap is the same body assembled with `PLAT_CRT`,
reading its payload from the cartridge's own bank instead of the PRG
image.

## Gates

1. **Byte-identical C64 builds.**  Moving the C64 build onto the
   seams (P0-3) and every later platform body leave each C64 release
   PRG byte-identical to the build before; `test_platform_audit.py`
   compares against the recorded hashes, and the size and golden
   gates stand ([build_system.md § Size gate](build_system.md#size-gate)).
2. **The literal audit.**  `dev/audit_platform_literals.py` scans
   `src/` for the literal classes of [§ The rule](#the-rule) and
   fails on one outside `platform.inc` or a seam's platform body.
3. **Per-seam tests.**  Each seam's platform body is pinned at the
   tier its host module uses ([testing.md](testing.md)): the m65
   bodies on M65Emu, the c64 bodies by the existing suite.

## Platform references

The MEGA65 Book (`~/Documents/mega65/mega65-book.pdf`) is the
authority for the m65 column; this document cites it and does not
restate it.  Per seam: the Chip RAM map and the SYS map, 14-11 and
14-16/17; `MAP` and interrupts, 14-21 to 14-23 and K-7/8; ROM write
protection, 14-39/40 and J-11; the jump table and its
prerequisites, I-3 and I-5/6; the vector table and the interrupt
frame, I-79/80; screen memory and colour RAM, 14-25 to 14-28; the
screen editor's ESC sequences, E-6; the typing-event queue and
modifier bits, F-3/4; the cartridge protocol, the MEGA65-style
cartridge page of the MEGA65 wiki (work in progress).  Every citation
is re-verified against xmega65 and the ROM by the milestone that
depends on it; the book itself says only the documented contract
holds across ROM versions ("The Memory Map Contract", 14-13).
