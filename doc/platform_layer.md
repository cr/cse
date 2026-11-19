# Platform Layer — The seams between CSE and the machine (c64, m65, c128)

**Template:** [subsystem](templates/subsystem.md)

This document owns the *platform driver layer*: the seams through
which CSE touches the machine it runs on — KERNAL entries and cells,
the base page, banking, far memory, the interrupt frame, the screen,
the keyboard, the loader — with each seam's contract, its macros and
constants per platform, and the machine facts they rest on (the
Hypervisor services, the 45GS02's raw-byte instructions, the m65
platform's ROM floor).  The memory maps the seams switch between are
[memory_design.md](memory_design.md)'s; what user programs may rely
on is [userland_contract.md](userland_contract.md)'s; the build is
[build_system.md](build_system.md)'s.  A routine that hosts a seam
states its per-platform body in its own module doc; this document
states the seam's contract and points there.

## Owned files

| File | Role |
|------|------|
| [`src/platform.inc`](../src/platform.inc) | header — every platform constant and macro, selected by `.ifdef` |
| [`src/m45_ops.inc`](../src/m45_ops.inc) | header — the 45GS02-only instructions as raw-byte macros ([§ Raw-byte instructions](#raw-byte-instructions)) |
| [`dev/audit_platform_literals.py`](../dev/audit_platform_literals.py) | implementation — the literal audit (the address-literal classes, the per-file counts), the base-page, stack-top, raw-byte and KERNAL-call checks, the pending count |
| [`tests/unit/test_platform_audit.py`](../tests/unit/test_platform_audit.py) | test contract — the byte-identical gate; the literal audit, the base-page, stack-top, raw-byte and KERNAL-call checks; the count of pending bodies and values |
| [`tests/unit/test_platform_m65.py`](../tests/unit/test_platform_m65.py) | test contract — the m65 macro bodies on M65Emu in clean mode: `KCALL` / `KJMP` (B = 0 for the KERNAL, registers through), the far accesses in banks 0, 2, 3, 4, `FAR_BANK`, `PLAT_SETBNK` |
| [`dev/m65_macros_test.s`](../dev/m65_macros_test.s), [`dev/m65_test.cfg`](../dev/m65_test.cfg) | test helper — the m65 macro bundle and its linker config (base page at `0.1F00`, code at `$4000`) |
| [`tests/unit/test_m45_ops.py`](../tests/unit/test_m45_ops.py) | test contract — each raw-byte macro is the compendium's encoding of its instruction |
| [`tests/m65emu/m45_ops.py`](../tests/m65emu/m45_ops.py) | test helper — the macros assembled and decoded: clean mode's allowed keys |
| [`tests/fixtures/golden/c64_prg_sha256.json`](../tests/fixtures/golden/c64_prg_sha256.json) | generated — the recorded SHA-256 of each C64 release PRG; back-link-exempt (JSON data) |


## The rule

**A platform fact lives in exactly one of two places.**  A ROM
address, a KERNAL cell, a VIC, SID, CIA or MMU register, a screen or
colour base, a banking value, a memory home, the shape of an
interrupt frame — every such fact is either a constant or a macro in
`src/platform.inc`, or code inside a `.ifdef PLATFORM_<platform>`
block.  A module may *expand* a `platform.inc` macro anywhere; it may
not *name* a platform fact outside such a block; a file named for
its platform (`c64_cse.cfg.in`) is itself such a block.  The audit
(`dev/audit_platform_literals.py`) enumerates the address literals of
these facts — its classes are listed in the tool — over `src/*.s`,
`src/*.inc` and `src/*.cfg.in` and fails on any outside those places.

**One module, one interface, bodies selected at assembly time.**  A
seam is one name — a constant, a macro or an exported routine — with
one contract; its platform bodies are selected with `.ifdef
PLATFORM_C64` / `.ifdef PLATFORM_M65` / `.ifdef PLATFORM_C128` (never
`.if PLATFORM = n`: the ca65 `.if`-inside-`.proc` caveat).  No
parallel modules, no duplicated bodies.

**Zero cost on the C64 builds.**  The layer is assembly-time only —
constants, macros and `.ifdef` bodies; no jump tables, no vectors, no
added `jsr` levels.  Each c64 expansion below is the instruction
sequence the C64 code has at that site, so moving the C64 build onto
the seams leaves every C64 release PRG byte-identical, and every
platform body is invisible to the other platforms' builds: the
slice-1 hard constraint (no C64 build grows or slows for m65) holds
by construction ([§ Gates](#gates)).

Shapes: a **constant** for an address, a cell, a size or a home; a
**macro** for an inline site whose instructions differ per platform;
an **`.ifdef` body inside the existing proc** for a routine-sized
difference; a **separate proc** only where the body is already a
proc.

## Platforms and defines

| Platform | Define | Machine | Status |
|---|---|---|---|
| c64 | `PLATFORM_C64` | C64 (and the C128 in C64 mode), stock KERNAL | shipping |
| m65 | `PLATFORM_M65` | MEGA65 in MEGA65 mode; **MEGA65 ROM 920413 (release 0.97) or later, Hyppo 1.2 or later** — the ROM floor | R7 slice 2 ([TODO](TODO.md#m65-slice-2--the-mega65-platform-r7-platform-layer)) |
| c128 | `PLATFORM_C128` | C128 in C128 mode (MMU, VDC) | reserved — R3 / R4 ([TODO § Roadmap](TODO.md#roadmap)); the seams are shaped so it adds a column, not a refactor |

The Makefile passes exactly one platform define to every assembly,
the C64 builds included.  A seam whose body is the same on two
platforms states so once.  Where the m65 column says *stated with
P<n>*, that milestone's doc delta fills it in; until then the m65
build still assembles every module, and the seam's m65 body is
`PLAT_PENDING` ([§ Pending bodies](#pending-bodies)).  The m65 build
is m65-6502 until its CPU layer lands in P4
([build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets)).  The Open ROMs are a
stretch target, not a platform
([memory_design.md § Target Compatibility](memory_design.md#target-compatibility)).

## The seams

| Seam | Host | What the upper layers see |
|---|---|---|
| [Constants](#constants) | `platform.inc` (L0) | named entries, cells, homes, sizes; never a literal |
| [KERNAL calls](#kernal-calls) | `platform.inc` | `KCALL entry`, `KJMP entry`, `KC_BRANCH` |
| [Base page](#base-page) | `platform.inc`; zp.s (L0), mem.s (L1) | where CSE's zero page is; `BP_PAGE`, `BP_ABS`; the user-ZP swap |
| [Stack](#stack) | `platform.inc` | `STACK_TOP` |
| [Banking](#banking) | mem.s (L1), `platform.inc` | `kernal_bank_out` / `kernal_bank_in`, `kernal_out`; `BANK_PUSH`, `BANK_POP`, `BANK_IN_A`, `BANK_FORCE_IN`, `BANK_FORCE_OUT`, `BANK_KERNEL` |
| [Far memory](#far-memory) | `platform.inc`; zp.s | `FAR_PTR`, `FAR_BANK`, `FAR_LDA`, `FAR_STA`, `FAR_ORA` |
| [User transitions](#user-transitions) | `platform.inc`; mem.s hosts the m65 resident stub | `PLAT_TO_USER` |
| [Vectors](#vectors) | main.s (L5) | `setup_interrupts` |
| [Interrupt frame](#interrupt-frame) | `platform.inc`; debugger.s, main.s | `FRAME_DEPTH` and the offsets derived from it |
| [IRQ early entry](#irq-early-entry) | main.s | c64 only |
| [Cold start and exit](#cold-start-and-exit) | main.s | `_main`'s hardware steps, `cse_exit_to_basic`, `PLAT_COLD_START` |
| [Terminal](#terminal) | cse_io.s (L1), `platform.inc` | cse_io's routines; `IO_CX`, `IO_CY`, `IO_STOP_DOWN`, `IO_KBHIT`, `IO_KBD_FLUSH` |
| [Display](#display) | screen.s (L2), `platform.inc` | screen's routines; `PLAT_HYGIENE`; the geometry |
| [Screen save](#screen-save) | editor.s | the REPL screen saved and restored around the editor |
| [Disk bank](#disk-bank) | disk.s, `platform.inc` | `PLAT_SETBNK` |
| [Info map](#info-map) | repl.s | the rows of `i`, one `.ifdef` data block per platform |
| [Loader](#loader) | loader.s (L6) | `loader_entry`; the cartridge bootstrap under `PLAT_CRT` |

Layering ([architecture.md](architecture.md)): the layer is a role of
the existing leaves, not a new layer.  `platform.inc` is L0 data and
macros; mem.s and cse_io.s are the L1 drivers; screen.s the L2
display driver; main.s and loader.s keep their platform-bound entry
and exit bodies because they are the dispatcher's entry and exit.
Every other module expands macros and names no platform fact.

## Seam contracts

### Constants

`src/platform.inc`, included by every module that needs one.  Each
constant is defined once per platform under `.ifdef`; a constant a
platform lacks is absent there, so a stray use fails to assemble.

| Group | c64 | m65 |
|---|---|---|
| KERNAL entries CSE calls | `GETIN $FFE4`, `PLOT $FFF0`, `RESTOR $FF8A`, `CINT $FF81`; the file calls `SETLFS $FFBA`, `SETNAM $FFBD`, `OPEN $FFC0`, `CLOSE $FFC3`, `CHKIN $FFC6`, `CHKOUT $FFC9`, `CLRCHN $FFCC`, `CHRIN $FFCF`, `CHROUT $FFD2`, `LOAD $FFD5`, `READST $FFB7`, `LISTEN $FFB1`, `UNLSN $FFAE` | the same addresses for the same calls (book I-5/6), except `RESTOR` and `CINT`, which the m65 exit does not need; plus `VECTOR $FF8D`, `SETBNK $FF6B`, `SCRORG $FFED`, `SYSFLAGS $FF47`, `ScanStopKey $FFEA`.  `BSOUT` (`CHROUT`), `BASIN` (`CHRIN`), `GETIN` and `STOP` are `JMP ($nnnn)` in the jump table, the others `JMP` (recorded, A1).  ROM 920413 lacks `VERSIONQ`, `RESET_RUN` and `CURSOR` (recorded: `$FF35` holds `$FF`); CSE does not use them |
| KERNAL internals called directly | `$EA31` (the IRQ body, from the early entry), `$FCE2` (cold start, the fallback); BASIC's warm-start vector `($A002)` | none |
| KERNAL cells | `ST $90`, the STOP row `$91`, the key count `$C6`, the blink switch `$CC`, `$CE`, the cursor column `$D3`, `$D4`, `$D5`, the cursor row `$D6`, `$D8`, the line-link table `$D9–$F1`, `CHRCOLOR $0286`, `KEY_REPEAT $028A`, the charset lock `$0291` | none, read or written (book 14-13: KERNAL variables are not an interface): `ST` → `READSS`; STOP → `ScanStopKey`; the keys → `GETIN`; the cursor → CSE's cells and `PLOT`; the editor's modes and lines → `ESC O`, `HOME HOME`, `PLOT`; the colour → a colour code through `BSOUT`; the charset lock → `SYSFLAGS` bit 7; key repeat → the hardware's, no setting ([§ Terminal](#terminal), A1 in [TODO § M65 slice 2](TODO.md#m65-slice-2--the-mega65-platform-r7-platform-layer)) |
| Vector table | `$0316` (`IBRK`), `$0318` (`INMI`) written directly; RAM shadows `$FFFA`/`$FFFE`; `$0314` (`IIRQ`) untouched | the KERNAL's table, read and written only through `VECTOR` |
| `FRAME_DEPTH` | 3 | 5 ([§ Interrupt frame](#interrupt-frame)) |
| Homes — the names (`HIMEM`, `WORKSTART`, `BASIC_START`, `SYM_TABLE`, `SYM_HEAP`, `KDATA_RUN`, `REPL_SCREEN`, `COLD_ZP`, `CSE_BP`, `STUB_BASE`, `BUF_FLOOR`, `BUF_END`, `PROG_LO`, `PROG_HI`) | values: [memory_design.md § Memory Map — Runtime](memory_design.md#memory-map--runtime-c64-builds) and § Banked layout | values: [memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode) |
| `ROM_BASE_HI` (the debugger does not step into ROM) | `$E0` | `$C0` (the interface ROM at `$C000` in the user map) |
| The workspace's upper bound (`b`, the step gate, the assembler's emit gate: `WORKSTART` ≤ address < the bound) | `buf_base`: the source text's base, dynamic ([gap_buffer.md](modules/gap_buffer.md)) | `HIMEM` (`$C000`): fixed and page-aligned, so a high-byte compare; the source text is not in bank 0 |
| User ZP | [§ Base page](#base-page) | [§ Base page](#base-page) |
| `STACK_TOP` | [§ Stack](#stack) | [§ Stack](#stack) |
| Screen geometry | `SCREEN $0400`, `COLOR_RAM $D800`, `SCREEN_WIDTH 40`, `SCREEN_HEIGHT 25` and the sizes derived from them (the editor's 22 rows, its status columns, the 1000-, 920-, 880- and 80-byte copies) | run-time state: `io_geometry` reads it from `SCRORG` and `$D060–$D063` after every mode change ([§ Display](#display), *The geometry*) |
| VIC | `$D011`, `$D015`, `$D016`, `$D018`, `$D019`, `$D01A`, `$D020`, `$D021` | VIC-IV: the register set the KERNAL leaves for each text mode, recorded per mode and ROM (`m65_editor.json`), which `vic_reset` writes back ([§ Display](#display)); `$D020` / `$D021` as on c64 |
| SID | `$D400`, `$D401`, `$D404`, `$D40B`, `$D412`, `$D418` | the same |
| BASIC format | `SYS` token `$9E`, `REM` token `$8F` | the same in BASIC 65 |
| CPU-port seeds | `$00 = $2F`, `$01 = $36` | the run premise's `$00 = $FF`, `$01 = $85`: the kernel's port while CSE runs, and a fresh start's ([§ User transitions](#user-transitions)) |
| `$D030` seed (m65) | — | `$64`, the run premise's: the kernel's while CSE runs, and a fresh start's |
| DMAgic | none | the job-list address and trigger registers `$D700–$D705` (the loader's install, `_main`'s step 11); the F018B option and the job commands |
| The free-ZP fill (`_main` step 10) | `ZP_BASE` `$00`, `ZP_FILL_END` `$80` | `ZP_BASE` `$00`, `ZP_FILL_END` = `STUB_BASE`'s low byte: the free part of CSE's base page |
| The jump-table page (the loader's gate) | none | `KERNAL_JUMP_PAGE` `$FF00`: every entry CSE calls is in it |
| `DISK_LOCAL_PTR` (disk.s's private pointer) | `$FD` — in the KERNAL half; see [TODO § Bugs](TODO.md#bugs) | a far pointer in CSE's base page — *stated with P3* |

**Hypervisor services (m65).**  The documented Hypervisor traps the
m65 build uses (book Appendix N, "available since Hyppo 1.2"); each
is `lda #<service>` · `sta <register>` · `clv`:

| Service | Trap | In / Out | Effect |
|---|---|---|---|
| `hyppo_getversion` | `$D640 ← $00` | Out: A.X = Hyppo version, Y.Z = HDOS version | — |
| `hyppo_rom_writeenable` | `$D641 ← $02` | — | banks 2–3 become writable; idempotent |
| `hyppo_get_mapping` | `$D640 ← $74` | In: Y = the destination page (`$00–$7E`) | the current `MAP` setting written to `$YY00–$YY05`: MAPLO, MAPHI (big-endian words), the two megabytes (book N-45) — `MAP`'s X, A, Z, Y operands in that order, then the lower and upper megabytes.  Recorded on both ROMs: `$YY00` is a CPU-view address under the current map (not flat bank 0); every register, every flag (the I flag among them) and the stack are kept — the resident stub's capture |
| `hyppo_reset` | `$D640 ← $7E` | does not return | warm boot: the ROM banks are reloaded from the SD card and the KERNAL boots to BASIC 65 |

### KERNAL calls

`KCALL entry` and `KJMP entry` (macros): call or tail-jump to a
KERNAL jump-table entry under the KERNAL's prerequisites.  **In /
Out:** those of the entry; `A`, `X`, `Y` and `C` pass through
unchanged in both directions.  **Clobbers:** those of the entry, and
N/Z.

| Platform | `KCALL entry` | `KJMP entry` |
|---|---|---|
| c64 | `jsr entry` | `jmp entry` (cse_io.s's `io_sync`, disk.s's final `CLOSE`) |
| m65 | `pha` · `lda #0` · `tab` · `pla` · `jsr entry` · `pha` · `lda #CSE_BP` · `tab` · `pla` — the jump table needs `B = 0` (book I-3); CSE runs with its own base page | `KCALL entry` · `rts` |

Every call of a jump-table entry is a `KCALL` or `KJMP`: a bare `jsr`
or `jmp` to an entry's name is a site the KERNAL-call check refuses
([§ Gates](#gates)), because on m65 it would run the entry with
`B = CSE_BP`.  The entries are the `$FFxx` names of [§ Constants](#constants);
loader.s is exempt, as both its bodies run before CSE's base page
exists, with `B = 0`.

`KC_BRANCH op, inverse, target` (macro): a conditional branch across
`KCALL`s.  c64: `op target`.  m65: `inverse` over a `jmp target` — a
`KCALL` is 14 bytes there, so a C64 short branch across some is out
of range (disk.s, three sites).

### Base page

Where CSE's zero page is, and what a transition does with the user's.

| Platform | CSE's zero page | The user's zero page |
|---|---|---|
| c64 | base page 0, `$02–$79` ([zp.md](modules/zp.md)) | `$00–$7F`, swapped at every kernel ↔ user transition by mem.s's four primitives |
| m65 | its own base page: `B = CSE_BP` (`$1F`, the page `0.1F00`) whenever kernel code runs | base page 0, never touched by CSE: the transitions switch `B`, not bytes |

`B` names a page of the CPU's 16-bit address space, and `MAP`
translates a base-page access like any other.  `CSE_BP` reaches bank
0 because both maps leave `$0000–$1FFF` unmapped
([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)):
the page is `0.1F00` in either map, which the resident stub at its
top relies on.  A `B` in a mapped block would follow the map (`$20`
is `3.2000` in the CSE map, inside the code window).  The base page
is CSE's own; the stack is not ([§ Stack](#stack)).

On m65 `B = CSE_BP` is set by the resident stub's CSE entries and
restored by every `KCALL`; the KERNAL's interrupt entry saves `B` and
sets `B = 0` for itself ([§ Interrupt frame](#interrupt-frame)), so
an interrupt during kernel code finds its own base page, and the
user's `B` travels in the frame.  Three consequences for code: a
base-page access never reaches the CPU port (with `B = $1F` a
base-page access to `$00` is `0.1F00`; the transitions reach it with
absolute addressing); a KERNAL cell in base page 0, where one
must be read, is read with absolute addressing (`a:$xx`); and the
converse — an access to a CSE base-page symbol in an *absolute* mode
(`jmp (sym)`, `op sym,y` where no zero-page,y form exists, i.e.
anything but `LDX` / `STX`) or a 16-bit pointer to one (`#<sym` /
`#>sym`, `.word sym`) is written `BP_ABS(sym)`:

| Name | c64 | m65 |
|---|---|---|
| `BP_PAGE` (constant) | `$00` | `CSE_BP` |
| `BP_ABS(sym)` (`.define`) | `sym` (+ `BP_PAGE · 256` = 0) | `sym + $1F00`: the page `0.1F00`, bank 0 in the CSE map, so a far pointer to it carries `BANK_USER` |

The expansion opens with a unary `+` so that `BP_ABS(sym),y` stays
absolute-indexed (an operand opening with `(` parses as `(zp),y`).
Where the instruction also has a zero-page form (`lda`, `sta`, `bit`
without an index), ca65 picks it for a zero-page symbol's
expression, so such a site writes `a:BP_ABS(sym)` (the resident stub,
the loader: both run with `B = 0`).
A static check pins the rule ([§ Gates](#gates)).

The user-ZP swap is mem.s's four primitives, their two buffers and
debugger.s's seeds, all `.ifdef PLATFORM_C64`; on m65 the transitions
switch `B` and `save_userland_state`'s swap tail is an `rts`.

The **user-ZP view** of `m`, `.` and the step engine (repl.s's
`zp_stage_prep`, `zp_poke`; debugger.s's `peek_user`): on c64 the
saved image `userland_zp_buf` for `$00–$7F`
([repl.md § User-ZP view](modules/repl.md#user-zp-view)); on m65
base page 0 itself, live, through the far pointer, except the CPU
port: CSE never writes base page 0, but it swaps the port at every
transition ([§ User transitions](#user-transitions)), so `$00`/`$01`
have an image, the captured port.  The three routines are the c64
bodies with the save range two bytes long — `ZP_SAVE_LO` = 0,
`ZP_SAVE_LEN` = 2, and `userland_zp_buf` the captured port in CSE's
base page, addressed `BP_ABS(userland_zp_buf)` (on c64 the same
expansion as today).  A flat access to `0.0000`/`0.0001` reaches the
RAM beneath the port, not the port, whether block 0 is mapped or not
(recorded, `m65_mem.json` `flat_port`; the xemu source suggested the
port): the port is reached only through the CPU view, with absolute
addressing, and a far pointer never shows it.

### Stack

Neither platform gives CSE a stack of its own: the kernel and user
code share the one stack page, and the kernel runs below the user's
SP ([memory_design.md § Stack contract](memory_design.md#stack-contract)).
The platform fact is `STACK_TOP` (constant): the SP with which the
loader enters `_main` and `cse_recover` and `cse_end_debug` restart
the kernel, and `reg_sp` without a session — the SP at which a fresh
start pushes the `brk_stub` sentinel:

| Platform | Stack page | `STACK_TOP` | The user's SP at a fresh start |
|---|---|---|---|
| c64 | `$0100–$01FF` | `$FF` | `$FD`: the whole page below the sentinel |
| m65 | `0.0100–0.01FF`, 8-bit (`E` = 1) | `$F1` | `$EF`, with the sentinel on top: the run premise's SP and return address |

On m65 `$01F2–$01FF` stays unused, so that a program finds the SP a
`RUN`-started PRG finds ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)),
its top-level return address in the same two bytes.  On both
platforms `r s:` moves `reg_sp`, and user code may reset SP and claim
the whole page ([userland_contract.md § 4](userland_contract.md#4-stack-contract)).

### Banking

`kernal_bank_out` / `kernal_bank_in` — mem.s
([mem.md § Interface](modules/mem.md#interface)).  Contract: between
a `kernal_bank_out` and the matching `kernal_bank_in` the data under
the KERNAL is readable; writes reach it at all times; both are no-ops
while the `kernal_out` batch flag is set; the I flag is never
touched; **Clobbers:** A.  Beside them, macros for the sites whose
banking does not fit the batch protocol; they compose (addr_mode.s
is `BANK_PUSH` · `BANK_IN_A` … `BANK_POP`):

| Macro | Contract | c64 expansion (the sites) | m65 |
|---|---|---|---|
| `BANK_PUSH` | A ← the caller's configuration, pushed | `lda $01` · `pha` (symtab.s `sym_define`, `sym_lookup`; addr_mode.s) | empty |
| `BANK_POP` | the pushed configuration back; C kept | `pla` · `sta $01` (the same sites) | empty |
| `BANK_IN_A` | bank the KERNAL in from the configuration in A | `ora #$02` · `sta $01` (addr_mode.s) | empty |
| `BANK_FORCE_IN` / `BANK_FORCE_OUT` | bank the KERNAL in / out regardless of `kernal_out` | `lda $01` · `ora #$02` / `and #$FD` · `sta $01` (asm_src.s `_bank_in_tmp`, `_bank_out_tmp`) | empty |
| `BANK_KERNEL` | the kernel's configuration: KERNAL in, BASIC out | `lda #$36` · `sta $01` (main.s `hw_reinit_body`, `refresh_body`) | empty |

The two routines' bodies:

| Platform | `kernal_bank_out` / `kernal_bank_in` |
|---|---|
| c64 | `$01` bit 1 cleared / set; an IRQ in between is carried by the [IRQ early entry](#irq-early-entry) |
| m65 | `rts`: nothing of CSE's is under the KERNAL; the data window is mapped at all times.  `kernal_out` stays — its writers (asm_src.s, main.s's `refresh_body`) are platform-neutral — and means nothing |
| c128 | MMU `$FF00` |

### Far memory

A **far pointer** is a ZP pointer that may reach memory outside the
kernel's own 16-bit view: user memory, the screen, the source text —
and, where the same pointer also serves CSE's own buffers, CSE's
data.  Which pointers are far is [zp.md](modules/zp.md)'s list.

- **Declaration** (zp.s): `FAR_PTR name` reserves `FAR_SIZE` bytes —
  2 on c64 (the pointer as it is), 4 on m65 (offset lo, hi, bank, 0:
  the 45GS02's flat pointer).  The c64 ZP layout does not move.
- **Bank:** `FAR_BANK name, bank` sets the pointer's bank wherever
  the pointer is set.  c64: empty.  m65: `pha` · `lda #bank` · `sta
  name+2` · `pla`; **Clobbers:** N/Z.  The banks are constants:
  `BANK_USER` (0: user memory, the screen in 40 × 25 and 80 × 25, the
  KERNAL's pages), `BANK_SCREEN50` (4: the screen in 80 × 50),
  `BANK_SRC` (2: the source region), `BANK_CSE` (3: CSE's code and
  data — the CSE map's `$2000–$BFFF` is flat `3.2000–3.BFFF`).  On
  m65 `FAR_BANK` also clears byte 3 (the megabyte), which only
  `FAR_USER` sets.  A pointer that serves user memory and CSE scratch
  alike carries whichever bank it was set to.  A pointer's `FAR_BANK`
  sites are written with the milestone whose tests first run its
  module on m65, so each bank is decided where a test can check it:
  P1 the user-memory pointers (`rp_ptr`, `rp_ptr2`, `_dasm_ptr`,
  `asm_out`, `asm_pc`), P2 the screen, string and source pointers
  (`ed_scr`, `_io_tmp`, `gap_lo`, `gap_hi`, `buf_base`, `ed_top_ptr`,
  `read_ptr`, `ed_tmp`, and `_io_scr` / `scr_src`, far from P2: the
  screen is in bank 4 in 80 × 50) — a screen pointer by
  `FAR_BANK_SCREEN` (the mode's bank, [§ Display](#display)), a source
  pointer `BANK_SRC`, the screen save's `BANK_CSE`; P3 `disk_ptr`.  Until then a far pointer's
  bank is 0 (`BANK_USER`): the loader clears CSE's base page.  A
  pointer that only ever reaches bank 0 below `$C000` has no set
  site at all: its bank is the loader's 0 for the whole session, and
  zp.md says so in its entry.
- **User addresses:** `FAR_USER name` (macro) — the pointer's
  offset holds a *user address*, the 16-bit address user code sees
  (what `m`, `.`, `d`, `a`, `b`, `j`, `g`, `brk_pc` and the step
  engine name); it sets the bank and megabyte to where that address
  is in the user map
  ([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)).
  c64: empty — the kernel's view is the user's (`$01 = $36`, the
  user-ZP view aside).  m65: `ldx #name` · `jsr far_user` (mem.s,
  [mem.md § far_user](modules/mem.md#far_user-m65-only)); **Clobbers:**
  X, N/Z.

  | User address | Far address (m65) |
  |---|---|
  | `$0000–$BFFF` | `0.0000–0.BFFF`: base page 0 (at `$00`/`$01` the RAM beneath the CPU port — the user-ZP view shows the captured port there instead), the stack, the KERNAL's pages, CSE's page, the program region |
  | `$C000–$CFFF` | `2.C000–2.CFFF`: the interface ROM |
  | `$D000–$DFFF` | `FFD.3000–FFD.3FFF`: the I/O registers of the MEGA65 personality (offset `$3000–$3FFF`, bank `$FD`, megabyte `$0F`) — the one row that rewrites the offset's high byte.  Recorded: a register reads and writes the same through every window `FFD.0000–FFD.3FFF` and the CPU view, under every `$D02F` key (`m65_mem.json` `flat_io`) |
  | `$E000–$FFFF` | `3.E000–3.FFFF`: the KERNAL |

  The translation is made where the pointer is set, for the row of
  the address it is set to.  An access or a walk that runs past the
  row's end (pointer + `Y`, or an `inc` of the high byte, across
  `$C000`, `$D000`, `$E000` or `$FFFF`) is not translated again: it
  reaches the next flat bytes of the same bank — `m bffc` shows
  `0.C000–0.C003` in its last four columns, not the interface ROM,
  and a run past `$FFFF` reaches `4.0000`, not `$0000`.  Only the
  rows' edges are affected; the c64 is not.  Code that needs the user
  address after `FAR_USER` reads it from where it came (`rp_addr`,
  `brk_pc`, the breakpoint table), never from the pointer, whose high
  byte the I/O row rewrites.  The P1 analysis lists every set site of
  the five user-memory pointers with its row
  ([TODO § M65 slice 2](TODO.md#m65-slice-2--the-mega65-platform-r7-platform-layer)).
- **Access:** `FAR_LDA name` / `FAR_STA name` — `A` ← / → the byte at
  the pointer + `Y`; `FAR_ORA name` — `A` ← `A` OR that byte (disk.s's
  directory walk tests a link for zero).

| Platform | `FAR_LDA` / `FAR_STA` / `FAR_ORA` | Clobbers |
|---|---|---|
| c64 | `lda (name),y` / `sta (name),y` / `ora (name),y` | load and or: A, N/Z; store: nothing |
| m65 | `PHY` · `PLZ` · `lda [name],z` / `sta [name],z` / `ora [name],z` (the 45GS02 has no `TYZ`; `PHY` · `PLZ` keeps A) | load and or: A, N/Z, the `Z` register; store: N/Z, the `Z` register |
| c128 | `(name),y` with the MMU's bank, settled by R3 | — |

The store's added N/Z clobber matters only at a site that tests a
flag set before the store; no `FAR_STA` site does (checked by the P0
refactor: each is followed by an instruction that sets N/Z itself, a
`jmp`, or an `rts` whose callers do not test N/Z).  The KERNAL keeps no invariant on the `Z` register.  User-stack
peeks (`lda $0100,x` in debugger.s) need no far access: page 1 is
bank 0, visible in both maps.  What user memory is per platform is
[userland_contract.md § 3](userland_contract.md#3-memory-regions);
where the source text lives,
[memory_design.md § Source Code Storage](memory_design.md#source-code-storage).

### User transitions

`PLAT_TO_USER` (macro) is the kernel → user transition, the tail of
`_rtu_body` ([debugger.md](modules/debugger.md)).  **In:** the RTI
frame (PC, P) on the stack, the user's registers in the snapshot
(`reg_a`, `reg_x`, `reg_y`; on m65 also `reg_z`, `reg_b`), the
user's ZP in place.  **Out:** the user's instruction runs with the
user's registers, P and SP, in the user machine of
[userland_contract.md](userland_contract.md).

| Platform | `PLAT_TO_USER` | User → kernel |
|---|---|---|
| c64 | `ldx reg_x` · `ldy reg_y` · `lda reg_a` · `rti` | the vectors reach the handlers directly |
| m65 | `$D030` and the CPU port back to the user's; push `reg_a`, `reg_x`, `reg_y`, `reg_z`, `reg_b` and the user map's `MAP` operands above the RTI frame, load the megabyte operands; `jmp stub_user` | the vectors reach the resident stub's BRK and NMI entries, which capture the user's bank state, restore the CSE map and base page and jump to the handlers |

**The user's bank state (m65).**  The debugger is transparent to the
program's banking as it is to its registers: a break captures the
**bank state** — the `MAP` setting (both halves' offsets, selection
masks and megabytes), the CPU port (`$00`, `$01`) and `$D030` — and
the resume installs exactly that state again.  A program cannot be
expected to tell the kernel how it mapped (the KERNAL's own
convention, that whoever sets `MAP` keeps its record — book I-31,
I-79/80 — covers cooperating code, not a debugged program), so CSE
reads it: the CPU has no instruction that reads `MAP` (book 14-42),
and the Hypervisor's `hyppo_get_mapping` does ([§ Constants](#constants)).

- **Capture** (the stub's BRK and NMI entries, under the program's
  map, before they switch maps; userland only — an entry with
  `in_userland` clear captures nothing, so a kernel fault or a
  RUN/STOP+RESTORE at the prompt never overwrites a live session's
  state): the CPU port saved and set to the run premise's (`$FF` /
  `$85`), which makes the I/O visible for the trap whatever the
  program banked out; `hyppo_get_mapping` into the first six bytes of
  CSE's base page (the trap writes at a page start: `0.1F00`).
  `save_userland_state`, which both handlers call on their userland
  path, then saves `$D030` and sets the premise's (`$64`).  The
  stub's switch to the CSE map is the two-`MAP` form — megabytes 0,
  then the CSE map — because a megabyte outlasts a one-`MAP` switch
  (book 14-40): a program's megabyte would otherwise move CSE's code
  window.
- **Install** (`PLAT_TO_USER` and `stub_user`): first a `MAP` of the
  CSE map onto itself, which holds IRQ and NMI off until `stub_user`'s
  `EOM` (recorded, T3); then `in_userland` (on m65 set here, inside
  the hold); `$D030`, then the CPU port, back to the captured values
  while the kernel's code is still mapped (neither moves the CSE map's
  code and data windows, which `MAP` places); the map in `stub_user`,
  megabytes first, then offsets and masks — the second `MAP`'s
  operands on the stack — and `EOM` once.
- **The program's `SYSFLAGS`** (function-key macros, the Mega + Shift
  and No Scroll locks) travels with the bank state, though it is KERNAL
  state, not banking: `save_userland_state` reads it (`KCALL
  SYSFLAGS`, C = 1) into `um_sysflags` (debugger.s's BSS), the
  hygiene sets CSE's (bits 5 and 7, [§ Display](#display)); `_rtu_body`
  writes the program's back before `PLAT_TO_USER` (a KERNAL call cannot
  run inside its `MAP` hold); a fresh start gives the run premise's `$00` (P2,
  operator 2026-11-18: CSE reads raw function keys, a program finds
  its own).
- **Fresh start** (`j`, `g`): the bank state is the run premise's —
  the user map, the port `$FF` / `$85`, `$D030` = `$64` — written into
  the saved state by `return_to_userland`, so a run starts as `RUN`
  starts a program whatever the last one left.

The transition is atomic from `PLAT_TO_USER`'s hold to `stub_user`'s
`EOM`.  The hold is needed: an NMI in the kernel's tail with
`in_userland` set would record the CSE map and the kernel's transient
registers as the program's (the stress test found it).  After `EOM` a
break is resumable: it interrupts the stub's pops under the user map,
the program's registers still on the stack above `reg_sp`, and the
resume re-enters the stub, which pops them.  An NMI at every
instruction of the transition is a test
([testing.md § The m65 PRG on M65Emu](testing.md#the-m65-prg-on-m65emu)).

The resident stub, its entries and `brk_stub`'s place in it are
[mem.md § The resident stub](modules/mem.md#the-resident-stub-m65-only)'s;
its location, [memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode).

### Vectors

`setup_interrupts` — main.s
([main.md § setup_interrupts](modules/main.md#setup_interrupts)).
Contract: afterwards a BRK and an NMI in user or kernel code reach
`cse_brk_handler` and `cse_nmi_handler`, whatever the memory
configuration at the moment; the IRQ keeps running the KERNAL's own
handler; the exit puts the KERNAL's defaults back.  c64: direct
stores into the page-3 vectors and the RAM shadows, from `_main` with
interrupts on.  m65: through `VECTOR` only, no shadows, with
interrupts off.

### Interrupt frame

`FRAME_DEPTH` (`platform.inc`): the bytes above the CPU's three (P,
PCL, PCH) when control reaches `cse_brk_handler` or
`cse_nmi_handler`.  `save_userland_state`
([debugger.md](modules/debugger.md)) derives every frame offset and
`reg_sp` from it.

| Platform | Frame (top → bottom) | How it is built |
|---|---|---|
| c64 | Y X A · P PCL PCH | the KERNAL's BRK entry (`$FF48`) pushes A X Y; the NMI entry pushes nothing, and `cse_nmi_handler` pushes A X Y itself to the same shape |
| m65 | B Z Y X A · P PCL PCH | the KERNAL's interrupt entry (BRK, IRQ and NMI alike) pushes A X Y Z B, sets `B = 0`, keeps the current map and jumps through `$0314` / `$0316` / `$0318` |

On m65 `RTI` and `PLP` do not load the `E` flag (P bit 5); the stack
mode is the CPU's, not the frame's.  The c64 handlers' clearing of
bit 5 in `reg_p` is therefore harmless on m65.

On m65 `save_userland_state` also reads `reg_z` (P − 4) and `reg_b`
(P − 5); the BRK and the NMI frame are the same shape, so
`cse_nmi_handler` pushes nothing of its own there.  The handler
bodies are [main.md § cse_brk_handler](modules/main.md#cse_brk_handler)'s
and [§ cse_nmi_handler](modules/main.md#cse_nmi_handler)'s.

### IRQ early entry

`cse_brk_handler_early` and `bank_out_stub`
([main.md § IRQ early-entry bank-out](modules/main.md#irq-early-entry-bank-out))
exist where the KERNAL can be unmapped while interrupts run: c64
only (`.ifdef PLATFORM_C64`).  On m65 the KERNAL is mapped in every
map; c128 settles it with R3.

### Cold start and exit

main.s ([main.md § _main](modules/main.md#_main),
[§ Exit path](modules/main.md#exit-path)) states each platform's
steps.  Contract: after `_main`'s hardware steps the machine is in
CSE's configuration; after `cse_exit_to_basic` it is the host
BASIC's again; `PLAT_COLD_START` restarts the machine when recovery
is impossible.

| Platform | Exit (`Q`) | `PLAT_COLD_START` |
|---|---|---|
| c64 | `RESTOR`, the cold-init ZP snapshot back, `CINT`, BASIC's warm start | `jmp $FCE2` |
| m65 | `hyppo_reset` | `hyppo_reset` |

### Terminal

cse_io.s ([cse_io.md § Interface](modules/cse_io.md#interface)), and
for the inline sites in other modules two `platform.inc` cells
(`IO_CX`, `IO_CY`) and three macros.  A routine or macro whose m65
column says *P2* is `PLAT_PENDING 2` until then.

| Name | c64 | m65 |
|---|---|---|
| `io_init` | `$CC ← 1` (the KERNAL's blink off) | nothing: the KERNAL keeps its blink off for code started by `SYS` (book I-21); CSE draws its own cursor |
| `io_sync` | `KJMP PLOT` with C = 0 | the same; `PLOT` is relative to the editor's window, which CSE keeps at the full screen (`kernal_screen_reset`) |
| `io_getc` / `io_kbhit` | `GETIN`; `$C6` | `KCALL GETIN` — its three sources: a function-key macro, the KERNAL buffer `ADDKEY` feeds, the hardware typing queue (book I-30s, F-3); `io_kbhit` through a one-key lookahead that `GETIN` fills (no KERNAL means peeks), which `io_getc` takes first |
| `IO_CX`, `IO_CY` (the cursor cells; main, repl, editor, log, disk, screen, cse_io) | `$D3`, `$D6` | CSE's own two cells in its base page — no KERNAL cell is read or written on m65 (book 14-13); `io_sync` tells the KERNAL |
| `IO_STOP_DOWN` (main_loop's STOP-held test) | `lda $91` · `cmp #$7F` | `KCALL ScanStopKey` · `cmp #$7F`: A = `$7F` while STOP is held, `$FF` otherwise (recorded), no side effects |
| `IO_KBHIT` (main_loop's inline peek; A ≠ 0 and Z clear when a key waits) | `lda $C6` | `jsr io_kbhit` (the lookahead; Z from A) |
| `IO_KBD_FLUSH` (repl's drains) | `sta $C6` (A = 0) | `GETIN` until it answers 0 (recorded: empty answers A = 0, C = 0), the lookahead emptied |
| `scr_lo` / `scr_hi`, the width | RODATA tables of `SCREEN` + 40·row; `COLS = 40` | run-time tables and width from `SCRORG` after `HOME HOME`: A / Z the top-left address, X + 1 columns, Y + 1 rows (recorded: X / Y are the window's right column and bottom row, not the book's width and height); the bank from `$D062` (80 × 50: 4) |
| `io_blip` | SID voice 1 | the same |
| The MEGA65's keys (TAB, HELP, F9–F14, ALT / MEGA / CTRL combinations) | — | the PETSCII the hardware typing queue presents (`$D619`) and `GETIN` passes on unchanged with the macros off (P2 T2, `tests/fixtures/m65_keys.json` from xemu's tables): TAB `$09`, HELP `$84`, ESC `$1B`, F9 / F11 / F13 `$10 $16 $19`, F10 / F12 / F14 (shifted) `$15 $17 $1A` — the codes of CTRL + P, V, Y, U, W, Z, so `GETIN` cannot tell them apart; the ALT combinations have no PETSCII.  `$D60A`'s modifier bits: SHIFT left / right 0 / 1, CTRL 2, MEGA 3, ALT 4, NO SCROLL 5, CAPS LOCK 6 (book F-3).  With the macros on (the run premise) `GETIN` expands a function key into its BASIC macro |

### Display

screen.s ([screen.md § Interface](modules/screen.md#interface)),
cse_io.s's geometry, and two macros.

| Name | c64 | m65 |
|---|---|---|
| `vic_reset` | VIC-II registers to CSE's text mode | the current mode's VIC-IV register set, as the KERNAL leaves it after `ESC 4` / `5` / `8` (recorded per ROM: a RODATA table per mode), the hot registers first; sprites off; then `$0E` through `BSOUT`, because `$D018`'s hot write reset the character pointer to the upper-case set.  The screen's content kept — a program's `BSOUT` output stays visible, as on c64.  `$D01A` is the KERNAL's (its raster IRQ), not 0 |
| `restore_colors` | border, background, `CHRCOLOR`, a 1 K fill of `$D800–$DBFF` | border and background as on c64; the text colour as a colour code through `BSOUT`; the colour RAM of the current mode — width × height bytes from the colour-RAM offset the VIC-IV names — filled by one DMA job |
| `kernal_screen_reset` | the KERNAL's screen-editor cells re-seeded | `ESC O`, `HOME HOME`, `io_sync` (A1; below) |
| `reset_screen` | colours, clear, home | the same: the screen's width × height bytes in the mode's bank filled by one DMA job, then home |
| `scroll_up`, `newline`, `cursor_show` / `hide` | through `scr_lo`/`scr_hi` | the same, through far pointers with the screen's bank; `scroll_up` moves the rows with one DMA copy and one fill |
| `PLAT_HYGIENE` (repl's `hygiene_after_userland`) | `$CC ← 1`, `$0291 ← $80`, SID voices 1–3 gated off | SID voices 1–3 gated off; `SYSFLAGS` bit 5 (function-key macros off) and bit 7 (Mega + Shift locked) set for CSE — the program's `SYSFLAGS` is part of its bank state ([§ User transitions](#user-transitions)) |
| `screen_mode_set` (screen.s) | — (one mode) | `ESC 4` / `5` / `8` through `BSOUT` (each clears the screen), then `io_geometry`, `restore_colors` |
| `io_geometry` (cse_io.s) | — (constants) | `HOME HOME`, then `SCRORG`: A / Z the screen's address, X + 1 the width, Y + 1 the height (A1: X / Y are the right column and bottom row); the bank from `$D062`; then `scr_lo` / `scr_hi` filled for that width and height |

**The geometry.**  On c64 the width, height and screen address are
constants; on m65 they are run-time state — `scr_width` and
`scr_last_col` in CSE's base page (every character's clamp reads
them), `scr_height`, `scr_last_row`, `scr_ed_rows`, `scr_ed_last`, `scr_bank`,
`scr_size` and `scr_lo` / `scr_hi` (50 rows) in cse_io's BSS (the base
page is full) — set by `io_geometry` at cold start and after every
mode change.  An inline site names them through **operand defines**, which
expand to an immediate on c64 (byte-identical) and to a base-page cell
on m65:

| Define | c64 | m65 |
|---|---|---|
| `WIDTH`, `LAST_COL` | `#40`, `#39` | `scr_width`, `scr_last_col` |
| `HEIGHT`, `LAST_ROW` | `#25`, `#24` | `scr_height`, `scr_last_row` |
| `ED_ROWS`, `ED_STATUS_ROW` (the editor: height − 3, its status row) | `#22`, `#22` | `scr_ed_rows`, the same cell |
| `ED_LAST` (the editor's last source row: height − 4) | `#21` | `scr_ed_last` |

Two build-time maxima size the buffers that hold a row:
`SCREEN_WIDTH_MAX` (40; m65 80 — `line_buf` is 2 more) and
`MEM_ROW_MAX`, the most bytes an `m` row shows or an edit takes (8;
m65 16 — `zp_stage_buf`; repl.md, *By width*).  `LINE_MAX` (39; m65
79) is a source line's length: the assembler's read (`_line_buf` is
one more) and `warn_long_lines`; the editor's typing cap is the last
column (`LAST_COL`), which equals `LINE_MAX` in 80 columns and is 39
in 40.  A routine that
depends on the mode reads the cells: `mem_row` (repl.s, m65) gives 16
in 80 columns, 8 in 40; `emit_reg` and `cmd_step`'s panel height test
`scr_width` against 80.

so `cpy WIDTH` is `cpy #40` on c64 and `cpy scr_width` on m65.  A
size a loop counts (a screen copy, the save) is a DMA job's length on
m65 (width × height, computed by `io_geometry` into `scr_size`), not a
loop bound.  Every screen pointer is a far pointer; `FAR_BANK_SCREEN
name` sets its bank from `scr_bank` (c64: empty; m65: `lda scr_bank` ·
`sta name+2` · `lda #0` · `sta name+3`, A kept) — zp.md lists them.
The modes: 80 × 25 (default) and 40 × 25 at `0.0800`, 80 × 50 at
`4.0800`; `ESC 4` / `5` / `8` typed at the prompt or in the editor
reach `screen_mode_set` (CSE reads its keys itself, so it obeys these
sequences itself).

`kernal_screen_reset` on m65 (A1, recorded): `ESC O` through `BSOUT`
— quote and insert mode off (a program can leave either on; both
survive `PLOT` and turn every later control code, `HOME` included,
into a printed glyph) — then `HOME HOME` (a program's window does not
survive a break, CSE needs the full screen), then `io_sync`.  There is no line-link table to repair: the MEGA65
editor's logical lines follow the screen's content, and a `BSOUT` a
program's NMI abandoned leaves nothing `PLOT` does not resync.  The
rest of the display's m65 bodies (VIC-IV registers, colours, the
fill) are the table's.

On m65 the screen is at `0.0800` in 40 × 25 and 80 × 25 and at
`4.0800` in 80 × 50 (recorded), so the display bodies reach it
through far pointers with the mode's bank.

### Screen save

The editor saves and restores the REPL screen around itself
([editor.md](modules/editor.md)) into a buffer whose home is
`REPL_SCREEN`: under the KERNAL on c64, bracketed by the banking
calls where it reads the buffer; in the data window on m65, sized for
80 × 50 (4000 bytes), saved and restored by one DMA copy of the
current mode's width × height bytes between the screen's bank and
`3.B000` (screen.s's `screen_save` / `screen_restore`).  A mode change while the editor runs is refused (the saved
screen is the mode's).  The colour RAM is not saved on either
platform: `restore_colors` repaints it.

### Disk bank

`PLAT_SETBNK` (macro) precedes each `OPEN` and `LOAD` in disk.s
([disk.md](modules/disk.md)).  c64: empty.  m65: `KCALL SETBNK` with
`SETBNK`'s data-bank argument `BANK_USER` and its filename-bank
argument `BANK_CSE`.  Where the directory listing is loaded (the C64
build loads it to `BASIC_START`) is *stated with P3*.

### Info map

The rows of the `i` command ([repl.md](modules/repl.md)) are a data
block per platform (`.ifdef`), each stating that platform's map in
[memory_design.md](memory_design.md)'s terms: the fixed rows
(`info_tbl_*`) and the bounds of the fixed free holes (`INFO_ZP_*`,
`INFO_LOW1_*`, `INFO_LOW2_*`).  `cmd_info`'s sequence of fixed and
dynamic rows is the c64 map's.  On m65 the rows are
[memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)'s
bank table — the user's regions (`0.1600–0.1EFF`, the program region
with `workstart` / `workend`, bank 1 above the DOS buffers, banks 4–5
in 40 × 25 and 80 × 25), CSE's page, the source region, CSE's code and
data windows — each written with its bank, `b.aaaa-bbbb`
([glossary.md](glossary.md)).

### Loader

`loader_entry` ([loader.md](modules/loader.md)) is one entry with a
body per platform: the C64's copy loop; the m65's gate and install
([loader.md § Design](modules/loader.md#design)).  The cartridge
bootstrap is the same body assembled with `PLAT_CRT`, reading its
payload from the cartridge's bank (*stated with P3*).

## Pending bodies

`PLAT_PENDING n` (macro, m65 only): the m65 body of a seam whose m65
contract is *stated with P<n>* but not yet stated.  It assembles to a
`BRK` followed by the signature byte `n` (the milestone), so the m65
build links every module from P0 on, and executing a pending body
stops in a recognisable break instead of running C64 code on a
MEGA65.  It is never an expansion on c64.  The pending sites are
counted by a test whose recorded count only goes down; it is zero
when P3 closes, and a milestone is not done while one of its pending
sites remains ([§ Gates](#gates)).

`PLAT_PENDING_VALUE name, value, n` (macro, m65 only): the m65 value
of a constant whose m65 contract is *stated with P<n>* — a cell or a
size that inline code in several modules names, where no body can
stand in for it.  It defines `name` as a placeholder so the m65 build
links; the code that names it runs only past a pending body (`_main`
stops at its first one in P0), so the placeholder is never read as
the machine's fact.  A placeholder cell is a byte of CSE's own base
page set aside for them (`BP_PENDING`, `$AD–$AF` since P2 stated the
cursor cells; [zp.md](modules/zp.md)),
so a stray access touches nothing of the user's or the KERNAL's; a
placeholder size is the run premise's default (80 × 25 at `0.0800`).
The test counts them with the pending bodies, under the same
milestone:

| Name | Placeholder | Stated with |
|---|---|---|
| `SCREEN`, `SCREEN_WIDTH`, `SCREEN_HEIGHT` | `$0800`, 80, 25 | P2 ([§ Display](#display)) |
| `ST` (the I/O status disk.s reads) | `BP_PENDING` | P3 ([§ Disk bank](#disk-bank)) |
| `DISK_LOCAL_PTR` (disk.s's private pointer) | `BP_PENDING + 1` (2 bytes) | P3 ([§ Constants](#constants)) |

(`IO_CX` and `IO_CY` were placeholders until P2 stated them: CSE's own
cursor cells, [§ Terminal](#terminal).)

## Raw-byte instructions

All code is assembled as 6502 code; a 45GS02-only instruction is a
macro in `src/m45_ops.inc` that emits its bytes, and no other file
encodes one ([testing.md § Tier U](testing.md#tier-u--unit-module--linking-down)).
The macros are the instructions the m65 platform bodies use:

| Macro | Instruction |
|---|---|
| `M45_MAP`, `M45_EOM` | `MAP`, `EOM` (`EOM` is the 6502's `NOP`; the macro names the intent) |
| `M45_LDZ_IMM value` | `LDZ #value` |
| `M45_TAB`, `M45_TZA` | `TAB`, `TZA` |
| `M45_PHY`, `M45_PLY`, `M45_PLX`, `M45_PLZ` | `PHY`, `PLY`, `PLX`, `PLZ` |
| `M45_JMP_IND_X addr` | `JMP (addr,X)` — the resident stub's dispatch to its three CSE targets |
| `M45_FAR_LDA zp`, `M45_FAR_STA zp`, `M45_FAR_ORA zp` | `LDA [zp],Z`, `STA [zp],Z`, `ORA [zp],Z`: the `EOM` prefix before `(zp),Z` |

The DMAgic's job lists are data and its trigger a store to an I/O
register ([§ Constants](#constants)): neither is a raw-byte
instruction.

The raw-byte audit ([§ Gates](#gates)) checks the rule in the source.
A `.byte` line in an executable segment (`CODE`, `LOADER`, `STUB`)
or in a macro body is an *opcode position* when the statement before
it is an instruction that can fall through — anything but `rts`,
`rti`, `jmp` and `brk`; a label between does not matter, since the
CPU falls into it.  An opcode position starts with a literal 6502
opcode (the BIT-skip idiom, `.byte $2C`).  A `.byte` after `brk` is
a signature byte (`brk_stub`'s, `PLAT_PENDING`'s) and one after a
transfer or other data is data; neither is decoded.  A macro call
counts as what the macro's body ends with when the macro is defined
above in the same file (loader.s's `ENTRY` ends in data), and as an
instruction that falls through otherwise.  The audit is the static
half; the run-time half is M65Emu's clean mode
([testing.md § M65Emu](testing.md#m65emu--the-m65-integration-harness)).

On the 45GS02 every
documented NMOS opcode decodes to the same instruction as on the
6502, so the shared modules assemble unchanged; the 6510's illegal
opcodes are 4510 instructions there and never appear in CSE's own
code.

## Gates

1. **Byte-identical C64 builds.**  Moving the C64 build onto the
   seams and every later platform body leave each C64 release PRG
   byte-identical: `test_platform_audit.py` compares each with its
   SHA-256 in `tests/fixtures/golden/c64_prg_sha256.json`, re-recorded
   only by a commit that deliberately changes a C64 build
   ([testing.md § Tier U](testing.md#tier-u--unit-module--linking-down));
   the size and golden gates stand beside it
   ([build_system.md § Size gate](build_system.md#size-gate)).
2. **The literal audit** ([§ The rule](#the-rule)): zero sites.
   (While the C64 build moved onto the seams it was a ratchet against
   a recorded baseline, which each seam's commit lowered, so every
   commit of the refactor was green and none could add a site; the
   Info map seam emptied it.)  Beside it, the base-page check
   ([§ Base page](#base-page); zero from the start), the stack-top
   check ([§ Stack](#stack): no literal `#$FF` put in SP or `reg_sp`;
   zero from the start), the raw-byte
   audit ([§ Raw-byte instructions](#raw-byte-instructions)), the
   KERNAL-call check ([§ KERNAL calls](#kernal-calls): no bare `jsr`
   or `jmp` to a jump-table entry outside platform.inc and loader.s;
   zero from the start — it found the one site the seam had missed)
   and the pending-body count ([§ Pending bodies](#pending-bodies)).
3. **Per-seam tests.**  Each seam's platform body is pinned at the
   tier its host module uses ([testing.md](testing.md)): the m65
   bodies on M65Emu, the c64 bodies by the existing suite.

## Platform references

The m65 column rests on two sources.

- **The MEGA65 Book** (MEGA65 Team, *The MEGA65 Book*, the compendium
  edition the project uses): the Chip RAM map and the SYS map, 14-11
  and 14-16/17; `MAP` and interrupts, 14-21 to 14-23 and K-7/8; ROM
  write protection, 14-39/40 and J-11; the jump table and its
  prerequisites, I-3 and I-5/6; the vector table and the interrupt
  frame, I-79/80; screen memory and colour RAM, 14-25 to 14-28; the
  ESC sequences, E-6; the typing queue, F-3/4; the Hypervisor
  services, Appendix N.  The book says only the documented contract
  holds across ROM versions ("The Memory Map Contract", 14-13).
- **Recordings in xmega65** (Xemu `0870689e`, on MEGA65 ROMs 920413
  and 920421, Hyppo 1.2, HDOS 1.3; identical results on both ROMs):
  every m65 fact here and in [memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)
  that is not a book citation.  Where a recording overrules the book,
  the document says so.  The recorders become committed tools with
  golden files when the tests that rely on them land
  ([testing.md § The m65 PRG on M65Emu](testing.md#the-m65-prg-on-m65emu)).
