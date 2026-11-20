# Userland Contract — What user code may rely on, and what it must preserve

This document defines the contract between the CSE **kernel** (the
runtime) and **userland** (any program executed via `j`, `g`, `c`,
`t`, or `o`).  It covers what state the kernel guarantees across a
user-code run, what state user code may freely modify, and where
user code can break the kernel's recovery guarantees if it crosses
specific lines.

For the design rationale that motivates this contract see
[design_cse_as_kernel.md](design_cse_as_kernel.md); for the memory
map and the kernel side of the stack contract see
[memory_design.md](memory_design.md).

---

## 1. Mode model

CSE has two execution modes:

- **Kernel mode** — the CPU is running CSE code (REPL, editor,
  assembler, debugger).  `in_userland = 0`.
- **Userland mode** — the CPU is running the user's program.
  `in_userland = $80`.

Transitions:

- **kernel → userland**: the kernel restores the user's ZP and
  registers, switches SP to the user's `reg_sp`, and enters the user
  code with an RTI.  A fresh start (`j`, `g`, and the first run after
  a cold preview) first pushes `brk_stub - 1` as the program's
  top-level return address (§ 4); a resume (`c`, `t`, `o`) does not.
- **userland → kernel**: any of three events:
  - **BRK** at a debugger breakpoint, a step breakpoint, or the
    program's own `brk`.
  - **BRK** at `brk_stub` (the program's top-level RTS popped the
    sentinel) — a clean exit, shown as `; rts`.
  - **NMI** (RUN/STOP+RESTORE).

The BRK handler classifies the break and records the user's state;
the NMI handler routes a userland NMI the same way (a break into
the debugger) and a kernel-mode NMI to `cse_refresh` (the classic
RUN/STOP+RESTORE screen recovery; the debug context is kept).
Mechanism: [main.md § cse_brk_handler](modules/main.md#cse_brk_handler),
[§ cse_nmi_handler](modules/main.md#cse_nmi_handler).

**On m65** the model is the same; what moves is the map and the base
page.  Kernel mode runs under the CSE map with `B = $1F` (CSE's own
base page, `0.1F00`); userland runs under the program's map — the
user map at a fresh start, whatever the program set since — with the
user's `B`.  The resident stub in CSE's page switches them: its user
entry installs the program's map and registers before the RTI,
and every BRK and NMI reaches it through the KERNAL's interrupt
entry, which pushes A X Y Z B and sets `B = 0`, and leaves it under
the CSE map ([platform_layer.md § User transitions](platform_layer.md#user-transitions)).
The program's bank state (its map, CPU port and `$D030`) is captured
at the break and installed at the resume; nothing else of base page 0
is swapped, because CSE never writes it.

### Ending a debug session

A break leaves a debug session behind (`c`, `t`, `o` continue it).
Commands that cannot share the machine with a live session — `j`,
`g`, `a`, and `R` — ask before ending it; the full per-command
behaviour is the
[debugger.md § dbg_reason × command matrix](modules/debugger.md#dbg_reason--command-matrix).

Ending a session restores the bytes under patched breakpoints,
clears the break state, and resets the user's SP to $FF.  The editor
buffer, the breakpoint table and the user's ZP image are kept.
See [memory_design.md § Warmstart entry points](memory_design.md#warmstart-entry-points).

## 2. State contract

User code's view of CPU and memory state, by tier:

### Preserved — the kernel guarantees these survive every user run

- **CPU registers**: `A`, `X`, `Y`, `P`, `PC`, `SP` are saved on
  user→kernel transition and restored on the next kernel→userland
  transition (so `c`, `t`, `o` resume seamlessly after a break).
  This includes the decimal flag: user code may stop with D set
  (`SED` then `RTS`, a breakpoint, RUN/STOP+RESTORE); the kernel
  clears D on entry and keeps the user's value in `reg_p`.
- **ZP `$00–$7F`** — the user's own image of this range, swapped out
  at every user→kernel transition and back in at the next
  kernel→userland transition (§ 3).
- **ZP `$80–$FF`**, except the KERNAL cells listed under *Clobbered*.
  The C64's free cells `$FB–$FE` are never written.
- **The user's stack** — every byte above the user's SP (§ 4).
- **The user's own memory** outside the kernel's regions: the
  workspace below the source text, the free fragments of pages 2
  and 3 (§ 3).

### Clobbered — the kernel modifies these; documented for reference

- **Screen RAM** ($0400–$07E7) and **colour RAM** ($D800–$DBE7).
  The REPL renders its prompt, listings and logs across the screen;
  a screen clear also overwrites the sprite pointers ($07F8–$07FF).
- **VIC registers**, forced to a readable text-mode state on every
  return from user code (`vic_reset`, screen.s): `$D011` = $1B
  (display on, 25 rows, text, no extended/bitmap mode), `$D016` = $C8
  (40 columns, no multicolour), `$D018` = $16 (screen $0400,
  lower/upper-case charset), `$D015` = 0 (sprites off), `$D01A` = 0
  (no raster or collision IRQs), pending VIC IRQs acknowledged.
  Border, background (`$D020`/`$D021`), colour RAM and the KERNAL
  text colour (`$0286`) are set to the CSE theme.
- **KERNAL cells CSE writes**:
  - `$C6` (keyboard-buffer count) — zeroed before a run, so the
    program's first `GETIN`/`CHRIN` sees an empty queue, and after
    it, so keys typed during the run do not reach the REPL.
  - `$CC` (cursor blink switch) — set to 1: the KERNAL cursor stays
    off, CSE draws its own.
  - `$D3`/`$D6` (cursor column/row); `$D1`/`$D2` and `$F3`/`$F4`
    (screen and colour line pointers, through the KERNAL's `PLOT`).
  - `$CE`, `$D4`, `$D5`, `$D8` and the screen-line link table
    `$D9–$F1` — reset to a clean screen-editor state after every run
    (`kernal_screen_reset`, screen.s).
  - `$0291` — set to $80 (the SHIFT+C= charset toggle stays locked);
    `$028A` bit 7 — set at cold init (all keys repeat).
  - Whatever the KERNAL routines CSE calls write in their own work
    areas: `PLOT` for the cursor, the disk routines for `l`, `s`, `$`.
- **SID**: the three voice control registers (`$D404`, `$D40B`,
  `$D412`) are zeroed — waveform and gate — on every return from user
  code, to stop stuck notes.  (They are write-only, so the gate bit
  alone cannot be cleared.)  CSE's reject blip (`io_blip`, on refused
  input) writes voice 1's frequency and control and sets the volume
  (`$D418`) to 10.
- **Stack bytes below the user's SP** — the kernel runs there while
  the REPL is active (§ 4).

### Compromised — neither side should expect recovery

- **IEC bus state** — CSE uses the disk for `l`/`s` and the
  directory; any in-flight user disk operation is forfeit.
- **Tape / RS-232 state** — same.
- **Interrupt-timing-sensitive behaviour** — CIA timers, user raster
  IRQs, anything that depends on cycle-precise IRQ delivery.  The
  KERNAL's IRQ keeps running while the kernel is active, and user
  raster IRQs are switched off at every return.

### Untouched — the kernel does not write these

- **SID registers** ($D400–$D41C) other than those named above.
- **Sprite registers** other than the enable register `$D015`:
  positions, colours, expansion and priority survive.
- **CIAs** beyond what the KERNAL's IRQ handling perturbs.

### On m65

The four tiers, for a program run under CSE on the MEGA65
([§ 3 On m65](#on-m65) for the regions):

- **Preserved:** the registers `A`, `X`, `Y`, `Z`, `B`, `P`, `PC` and
  `SP` (the decimal flag as on c64; `E` stays 1, § 5.5); the **bank
  state** — the `MAP` setting, the CPU port and `$D030` — captured at
  every break and installed again by every resume, so a break inside
  the program's own mapping resumes inside it; its `SYSFLAGS`
  (function-key macros and the keyboard locks) and the KERNAL's map
  record (`0.011C–011F`, the map the KERNAL's far calls return to),
  likewise; base page 0
  entirely,
  wherever `B` points — CSE never writes it, so there is no image to
  swap (the port aside); the user's stack above SP (§ 4); the user's memory:
  `0.1600–0.1EFF`, the program region, bank 1 above the DOS buffers,
  banks 4 and 5, the Attic RAM.
- **Clobbered:** the screen and the colour RAM of the current mode
  (`0.0800` and its colour RAM, `4.0800` in 80 × 50) — CSE writes the
  REPL there, and a program's `BSOUT` output stays visible as on c64;
  the VIC-IV text-mode registers CSE writes back on every return (the
  register set the KERNAL leaves for the current mode — a program's
  bitmap, sprite or raster setup does not survive a break); the border
  and background colours (the theme); the KERNAL screen editor's
  modes and window (`ESC O`, `HOME HOME`: quote and insert mode off,
  the full screen); the KERNAL's base page `$90–$FA`, which its IRQ
  and the calls CSE makes write (`BSOUT` and `PLOT` alone: `$C4 $C5
  $DA $E0 $E1 $E8 $E9 $EA $EB $EC $EF $F0`, recorded; the disk calls
  more — § Zero page); the SID's three voice gates; the stack below
  the user's SP (§ 4).
- **Compromised:** the IEC and disk state, interrupt timing — as on
  c64.
- **Untouched:** the I/O personality; bank 1, banks 4–5 (but for the
  80 × 50 screen at `4.0800–4.179F`) and the Attic RAM.

A fresh start (`j`, `g`) does not take the last run's bank state: it
installs the run premise's — the user map, the port `$FF` / `$85`,
`$D030` = `$64`, `SYSFLAGS` = `$00`, the KERNAL's map record the user
map — as `RUN` would.

## 3. Memory regions

| Region | Address | User code may use |
|--------|---------|-------------------|
| User ZP | $00–$7F | Yes — the whole range is the user's during a run (see below) |
| KERNAL ZP | $80–$FF | **No** — must preserve; `$FB–$FE` are free (CSE never writes them) |
| Stack page | $0100–$01FF | Yes — see § 4 (Stack contract) |
| KERNAL editor state | $0200–$02A6 | **No** |
| Free | $02A7–$02FF | Yes (89 B) |
| KERNAL vectors | $0300–$0333 | **No** — CSE hooks live here |
| Free (incl. tape buffer) | $0334–$03FF | Yes (204 B; the tape buffer $033C–$03FB is inside it — restore it if the program uses tape) |
| Screen + sprite ptrs | $0400–$07FF | Clobbered by the REPL (§ 2) |
| Workspace | $0800–workend | Yes — the user's; CSE writes it only when asked (`a`, `m`, `.`, `l`) |
| Source text | workend+1 – runtime start − 1 | **No** — the editor's buffer |
| CSE runtime | runtime start – $CFFF | **No** — overwriting CSE is fatal |
| I/O | $D000–$DFFF | Yes |
| Banked under KERNAL | $E000–$FFFF | **No** — CSE owns the banked layout |

`workend` and the runtime start move with the source text and the
build; `i` shows them, and `workend` is a predefined symbol
([memory_design.md § Source Code Storage](memory_design.md#source-code-storage)).

**Zero page.**  User code may use all of $00–$7F.  The kernel saves
the whole range ($00–$7F) when user code stops and restores it when
user code runs again, so CSE's own ZP variables never meet the
user's.  Between runs, `m` and `.` on $00–$7F show and edit the
user's image, not CSE's live ZP.  Before the first run the image is
zero except the CPU port: `$00` = $2F, `$01` = $36.  That CSE leaves
$7A–$7F unallocated ([zp.md](modules/zp.md)) concerns CSE only; it
does not change what user code may use.  `$00`/`$01` are the CPU
port: see § 5.3.

### On m65

A program run under CSE on the MEGA65 finds the machine a BASIC 65
program finds when `RUN` starts it — the *run premise* of
[memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode) —
as far as CSE can leave it so: the KERNAL's `SYS` map, an 8-bit
stack in page 1, and all memory the KERNAL does not use, except CSE's
one page in bank 0.  That includes everything BASIC 65 holds when it
runs — its base-page cells, its program text and variables, bank 1's
arrays and strings, the bitmap banks 4 and 5: BASIC 65 is gone while
CSE runs, so a program under CSE is the machine-code program of the
book's chapter 14, which "is free to use any region of Chip RAM that
would otherwise be used by BASIC" and must avoid only the KERNAL's
(14-12).  The one BASIC region CSE keeps is its bitmap-graphics base
page, `0.1F00–0.1FFF`: CSE's page.

| Region | Address | User code may use |
|--------|---------|-------------------|
| CPU port | `0.0000–0.0001` | Yes — swapped with the rest of the bank state (§ Zero page below) |
| KERNAL far-call cells | `0.0002–0.0009` | **No** — the KERNAL's: the parameters of `JSRFAR` / `JMPFAR` (bank, address, P A X Y Z; book I-30/31) |
| BASIC 65's base page | `0.000A–0.008F` | Yes — free (134 bytes): BASIC 65 is gone while CSE runs, and neither CSE nor the KERNAL uses them |
| KERNAL base page | `0.0090–0.00FA` | **No** — the KERNAL's: I/O status `$90`, the STOP key flag `$91`, the file and disk cells, the jiffy clock, the screen editor's character attributes, insert and scroll state up to `$FA` |
| Free base page | `0.00FB–0.00FF` | Yes — free (5 bytes), untouched by CSE and the KERNAL; the book's own example keeps a pointer at `$FD–$FF` (`PFKEY`, I-47) |
| Stack page | `0.0100–0.01FF` | § 4 |
| KERNAL variables, screen | `0.0200–0.15FF` | **No** — the MEGA65 KERNAL's (the screen at `0.0800` in 40 × 25 and 80 × 25); only through the KERNAL's jump table |
| Free for programs | `0.1600–0.1EFF` | Yes — untouched by CSE |
| CSE's page | `0.1F00–0.1FFF` | **No** — CSE's base page and resident stub; overwriting it breaks every break and return |
| Program region | `0.2000–0.BFFF` | Yes — the user's; CSE writes it only when asked (`a`, `m`, `.`, `l`).  `workstart` = `$2000`, `workend` = `$BFFF` |
| Interface ROM | `$C000–$CFFF` | **No** — the KERNAL needs it there |
| I/O | `$D000–$DFFF` | Yes |
| KERNAL | `$E000–$FFFF` | **No** — must stay mapped while interrupts can occur |
| RAM behind ROM, I/O and KERNAL | `0.C000–0.FEFF` | Yes, through flat access or `MAP` — the rest of BASIC 65's program text and its scalar variables when BASIC runs; CSE does not use it |
| Shared top page | `0.FF00–0.FFFF` | **Not handed over** — reserved (book 14-11): the page shared across maps and bank switches by vectors, interrupt handlers and trampolines.  CSE does not use it; a program that does takes on those intricacies itself |
| DOS buffers | `1.0000–1.1FFF` | **No** — the KERNAL's |
| Bank 1 | `1.2000–1.F6FF` | Yes — BASIC 65's arrays and strings when BASIC runs; CSE never touches it |
| Colour RAM window, reserved | `1.F700–1.FFFF` | through the screen only |
| ROM banks | `2.0000–3.FFFF` | **No** — CBDOS, the interface ROM, the KERNAL, and CSE's code, data and source text |
| Banks 4, 5 | `4.0000–5.FFFF` | Yes — BASIC 65's bitmap graphics when BASIC runs; CSE never touches them (bitmaps, double buffering); in 80 × 50 the KERNAL's screen is at `4.0800–4.179F` |
| Attic RAM | `800.0000`+ | Yes — CSE never touches it |

**A run starts as `RUN` starts a program:** in the `SYS` map, with
the registers `r` shows (initially `A X Y Z B` = 0 and P = `$20`: the
8-bit stack, interrupts on), and a return address on the stack that
the program's final `RTS` takes back to CSE — to `brk_stub` in CSE's
page, as BASIC's `SYS` returns through the KERNAL's page 3.  The
KERNAL's vectors differ from BASIC's in one way: BRK and NMI lead to
CSE's debugger.  BASIC 65 itself is gone while CSE runs; a program
that calls into BASIC 65's ROM code does not work under CSE.

**Zero page.**  Base page 0 is the program's and the KERNAL's, by
the rows above: `$0A–$8F` and `$FB–$FF` are the program's (139
bytes; `i` and the splash list them as `zp`), `$02–$09` and
`$90–$FA` the KERNAL's — the far-call cells by the book (I-30/31),
`$90–$FA` by the KERNAL's own use (operator, 2026-11-20): I/O status,
the STOP key, the file, disk and clock cells, and from `$F0` the
screen editor's character attributes, insert and scroll state.  The
recordings confirm the program's part: through a CSE session on
M65Emu (ROMs 920413 and 920421) and in xmega65 — output, `i`, `m`,
`d`, `.`, a program run that calls `BSOUT`, steps, the disk commands,
the 80 × 50 switch and the editor — no cell of `$0A–$8F` or `$FB–$FF`
changed (`test_m65_repl.py`, `test_m65_disk.py`,
`test_m65_base_page.py`).  `m` and `.` on `$00–$FF` show and edit
base page 0 itself, live, because CSE never writes it — except `$00`
and `$01`, the CPU port, which CSE swaps like the rest of the bank
state: there `m` and `.` show and edit the program's port, as on c64.
A program that sets `B` elsewhere has its base page there; `m` shows
memory by address, and `r` shows `B`.

**Addresses.**  An address given to `m`, `.`, `d`, `a`, `b`, `j` or
`g`, and the PC of a break, is the 16-bit address the program sees
under the user map: `$0000–$BFFF` bank 0, `$C000–$CFFF` the
interface ROM, `$D000–$DFFF` the I/O registers, `$E000–$FFFF` the
KERNAL ([platform_layer.md § Far memory](platform_layer.md#far-memory)).
Breakpoints and step targets must lie in the program region,
`$2000–$BFFF` ([debugger.md § Caveats](modules/debugger.md#caveats)).
The other banks are reached by the program itself, not by these
commands.

**Stack.**  Shared as on c64 (§ 4), with its top at `$01F1`
(`STACK_TOP`, [platform_layer.md § Stack](platform_layer.md#stack)):
a fresh start pushes the sentinel at `$01F1`/`$01F0`, and the program
starts with SP = `$EF`, 240 bytes of free stack below the sentinel —
the SP and the return-address bytes a `RUN`-started PRG finds.
`$01F2–$01FF` stays unused.

**Quitting (`Q`)** is a Hypervisor reset.  This contract promises
nothing across it; the source text is lost (CSE warns when it is
unsaved).  Observed, not promised: banks 0, 4 and 5 keep what they
hold, bank 1 is cleared.

The state tiers on m65 are [§ 2 On m65](#on-m65)'s, the vector and
map hazards [§ 5.5](#55-on-m65)'s.

## 4. Stack contract

CSE and user code **share** the single 6502 stack page.  There is no
two-image swap; user→kernel and kernel→user transitions are flat
RTI/RTS-driven and cost about 20 cycles.

### Layout at userland entry

A fresh start pushes the sentinel at the user's SP (`reg_sp`: the
stack top, $FF, unless changed with `r s:`; on m65 § 3), then an RTI
frame below it.  For `reg_sp` = $FF, just before the RTI:

```
$01FF  (brk_stub - 1) hi  ─┐  the program's top-level return address
$01FE  (brk_stub - 1) lo  ─┘
$01FD  PC hi  ─┐
$01FC  PC lo   │  RTI frame (popped by the RTI)
$01FB  P      ─┘
```

The user code starts with **SP = $FD**: 254 bytes of free stack
below the sentinel.  Its top-level RTS pops the sentinel and lands
at `brk_stub`, which ends the run cleanly.  A resume (`c`, `t`, `o`)
enters with SP at the user's `reg_sp` and pushes no sentinel — the
one from the fresh start is still in place.

User code may reset SP to $FF and claim the entire page; it then
overwrites the sentinel, and its top-level RTS must land somewhere
meaningful itself (or the program ends by a BRK or a jump).

### What the kernel touches on the stack

When user code stops, the kernel runs on the stack below the user's
SP: the BRK frame, the handler, and every REPL command typed at the
break push there.  It never writes a byte above the user's SP —
the user's return addresses, pushed data and the sentinel survive,
so `c` can resume.  Bytes below the user's SP are scratch for the
kernel and must not be relied on across a break.

### Kernel stack budget

**User code must leave at least 64 bytes of stack below its SP** when
a break may occur.  The 64 bytes hold the BRK frame (6 bytes: 3 CPU,
3 KERNAL push; on m65 8 bytes: 3 CPU, 5 KERNAL push), the handler's
call chain, and the REPL commands typed at a break (`m`, `.`, `d`,
`r`, stepping), with margin.

The deepest kernel path, the assembler, never runs on a break's
stack: `a` with a live session ends the session first (§ 1), which
resets SP to the stack top.  `tests/unit/test_asm_src.py::TestKernelStackDepth`
measures the assembler's depth from a fresh SP and pins ceilings
(80 B for realistic programs, 160 B for deeply nested expressions).
Typing a deeply nested expression at a break while the user's SP is
already low can still underrun; that is known and not gated.

**Runtime warning**: on every return from user code,
`post_run_cleanup` checks `reg_sp`.  When `reg_sp < 64` the REPL
emits `;!stk N` (N = `reg_sp` in decimal — the bytes left below the
user's SP) before showing the break result.

User code that recurses to within the budget of stack exhaustion and
then breaks overflows the page: the kernel's pushes wrap below $0100
and corrupt the top of the stack page.  The kernel cannot guard
against it; it can only warn.

## 5. Interrupt vector and banking hazards

Three classes of action will break the kernel's recovery guarantees:

### 5.1 NMI vector ($0318/$0319 RAM, $FFFA RAM under kernal-out)

Modifying the NMI vector breaks the **always-available RESTORE
escape hatch**.  After a custom NMI handler is installed:

- RUN/STOP+RESTORE no longer enters the debugger from runaway code.
- The user must reset to recover.

If the user wants to install their own NMI handler, the contract is:
do so only as part of a deliberate "no debugger" run; the user
accepts that they cannot break out interactively.

### 5.2 IRQ/BRK vector ($0316/$0317 RAM, $FFFE RAM under kernal-out)

Modifying the IRQ/BRK vector breaks **debugger breakpoints** and the
**clean userland exit** (`brk_stub`).  After a custom IRQ vector is
installed:

- BRK at a breakpoint slot routes to the user's handler instead of
  the debugger.
- User's top-level RTS lands at `brk_stub` and BRKs, but the user's
  handler sees the BRK rather than the kernel.

User code that wants to handle its own IRQs should chain to CSE's
`cse_brk_handler` for BRK frames (B=1) and to its own routine for
IRQ frames (B=0), or accept the loss of debugger support.

### 5.3 ROM banking ($01)

Modifying $01 with kernal banked out is recoverable as long as the
$FFFE/$FFFA vectors remain pointed at CSE's early-entry handlers
(the standard layout): an IRQ/NMI fired during the kernal-out window
hits the early-entry handler, which detects the kernal-out state
(by the very fact of being reached from RAM-resident vectors), banks
kernal in for the KERNAL's IRQ body, and restores `$01` to exactly
the interrupted code's value before the final RTI — KERNAL out with
I/O in (`$35`) stays `$35`.

But if user code combines:

- Banking kernal out, AND
- Repointing $FFFE or $FFFA to a non-CSE handler that does not bank
  kernal back in,

then an IRQ in that window will execute random ROM bytes (or RAM
bytes from the user's handler that doesn't know to bank).  This is
not recoverable by CSE; warm start or hardware reset required.

The rule of thumb: **changes to the IRQ/NMI vectors and to kernal
banking are individually safe but combined dangerously**.  The
kernel's invariant is "vectors at $FFFE/$FFFA always point at code
that is reachable in the current banking state."

### 5.5 On m65

The KERNAL's vector table ([platform_layer.md § Vectors](platform_layer.md#vectors))
replaces the C64's page-3 vectors and RAM shadows; the hazards are
stated in its terms.

- **`IBRK` and `INMI`** (vector-table offsets 2 and 4) lead to CSE's
  resident stub.  A program that replaces them through `VECTOR` (or
  writes the table) loses breakpoints, the clean exit and the
  RUN/STOP+RESTORE escape as in § 5.1 and § 5.2; a program that wants
  its own BRK handling chains to the vector it found there.  `IIRQ`
  is the program's as it is BASIC's program's.
- **CSE's page** (`0.1F00–0.1FFF`: the base page and the stub) must
  survive: every break and every return passes through the stub, and
  a program that overwrites it breaks both.
- **`MAP`, the CPU port and `$D030`.**  A program may map and bank as
  it likes while it runs; the debugger captures all three at a break
  and installs them again at the resume (§ 2 On m65).  What a break
  needs is only that it can reach CSE: the KERNAL mapped at `$E000`
  while interrupts can occur (its interrupt entry and the vector
  fetch run under the current map — book 14-23) and CSE's page
  visible at `$1F00` (block 0 unmapped) — a program that maps either
  away cannot break, as it could not take an interrupt under BASIC
  65.  The capture runs the Hypervisor's `hyppo_get_mapping`, so a
  break costs one Hypervisor trap.
- **`E`** (the 8-bit stack).  User code runs with `E` = 1 and must
  have it set again when a break can occur; a break with `E` = 0 puts
  the KERNAL's frame where an 8-bit stack does not find it.  A
  private 16-bit stack for programs is analysis task A2's.

## 6. KERNAL-as-terminal affordance

Because CSE leaves the kernal functional and the REPL writes through
the kernal's screen conventions, **user programs can treat the REPL
as a terminal**:

- `jsr CHROUT` ($FFD2) writes a character at the current cursor —
  the same cursor the REPL is using.  Output appears interleaved
  with subsequent REPL output, naturally flowing into the log.
- `jsr CHRIN` ($FFCF) reads from the same keyboard queue the REPL
  uses.
- `jsr GETIN` ($FFE4) likewise non-blocking.

This makes CSE a host environment for "just print debug messages"
style development.  Typed into the editor (local labels are written
`.name` and belong to the global label before them):

```asm
main:
        ldx #0
.l:     lda msg,x
        beq .done
        jsr $ffd2            ; chrout
        inx
        bne .l
.done:  rts                  ; clean exit → back to the REPL

msg:    .str "hello, world", 13, 0
```

After `a` and `g`, the REPL reads:

```
0800:g
hello, world
; rts
r pc:0800 a:00 x:0d y:00 s:ff nv-BdiZc
0800:
```

The program's output comes first; `; rts` reports the clean exit
through `brk_stub`, and the register line shows the state the
program returned with.

This is an intentional affordance, not a leak.  The userland contract
documents it as supported behaviour: CHROUT/CHRIN/GETIN work, and
their output integrates with REPL display.

## 7. Practical guarantees, summarised

When user code is `j`/`g`/`c`/`t`/`o`-launched, it can rely on:

1. The screen is in text mode with the lower/upper-case charset,
   CSE's theme colours, and the KERNAL's IRQ running at the jiffy
   rate.
2. `JSR $FFD2` (CHROUT) writes to the visible REPL cursor.
3. CPU registers and ZP $00–$7F are what the previous break left, as
   edited with `r` (registers) and `m`/`.` (ZP).
4. The kernel never writes a byte above the user's SP.
5. RUN/STOP+RESTORE will break into the debugger.
6. A top-level RTS returns cleanly to the REPL (unless the program
   overwrote the sentinel, § 4).
7. The workspace ($0800–workend) is the user's; CSE writes it only
   when asked.

On m65 items 3 and 5–7 hold as stated, with the program region
(`$2000–$BFFF`) for the workspace; item 1 waits for P2's screen
contract.  User code on m65 **must** keep CSE's page
(`0.1F00–0.1FFF`), the KERNAL's pages (`0.0200–0.15FF`), `IBRK` and
`INMI`, the KERNAL mapped at `$E000` and block 0 unmapped, and `E` =
1 at a break (§ 5.5).

User code **must**:

1. Preserve $80–$FF (except `$FB–$FE`), $0200–$02A6, $0300–$0333.
2. Not overwrite the source text or the CSE runtime (workend+1 to
   $CFFF).
3. Leave at least 64 bytes of stack headroom if a break may occur.
4. Not leave the kernal banked out across an IRQ if it has also
   redirected $FFFE/$FFFA away from CSE handlers.

Beyond these, user code is free.

## 8. Cross-references

- [design_cse_as_kernel.md](design_cse_as_kernel.md) — design rationale
- [memory_design.md](memory_design.md) § Stack contract — the kernel side
- [modules/main.md](modules/main.md) — `cse_brk_handler`,
  `cse_nmi_handler`, `setup_interrupts`, the warmstart entry points
- [modules/debugger.md](modules/debugger.md) — `return_to_userland`,
  `brk_stub`, register save/restore, the gate matrix
