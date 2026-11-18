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

The m65 build leaves bank 0 to the user's program and keeps itself
in the BASIC ROM banks and bank 1
([memory_design.md § Memory Map — m65](memory_design.md#memory-map--m65-mega65-mode)).
User code runs in the *user map* — the machine a `SYS` from BASIC 65
gives: bank 0 RAM to `$CFFF`, I/O at `$D000`, the KERNAL at `$E000`.

| Region | Address | User code may use |
|--------|---------|-------------------|
| Base page 0 | `0.0000–0.00FF` | as on the C64 (`$00–$7F` the user's, swapped at every transition) — subject to open item P-Q4, settled with P0 |
| Stack page | `0.0100–0.01FF` | § 4 |
| KERNAL variables, screen | `0.0200–0.15FF` | **No** — the MEGA65 KERNAL's (screen at `0.0800`); only through the KERNAL's jump table |
| Resident stub | `0.1600` – the stub's end | **No** — CSE's only code in bank 0; overwriting it breaks every break and return |
| Free | the stub's end – `0.1EFF` | Yes |
| Free if no bitmap graphics | `0.1F00–0.1FFF` | Yes (BASIC 65's graphics base page; CSE does not use it) |
| Workspace | `0.2000–0.CFFF` | Yes — the user's; CSE writes it only when asked (`a`, `m`, `.`, `l`).  `workstart` = `$2000`, `workend` = `$CFFF` |
| I/O | `$D000–$DFFF` | Yes |
| KERNAL | `$E000–$FFFF` (→ `3.E000`) | **No** — must stay mapped for interrupts (§ 5) |
| DOS buffers | `1.0000–1.1FFF` | **No** — the KERNAL's |
| Source text | `1.2000–1.F6FF` | **No** — the editor's buffer |
| Colour RAM window, reserved | `1.F700–1.FFFF` | through the screen only |
| ROM | `2.0000–2.FFFF` | **No** |
| CSE | `3.0000–3.FFFF` | **No** — CSE's code and data, and the KERNAL |
| Banks 4, 5, Attic RAM | `4.0000–5.FFFF`, `800.0000`+ | Yes — CSE never touches them (bitmap and double buffering are the user's) |

The stub's end is a link-time value; `i` shows it.  What survives a
quit (`Q` is a Hypervisor reset) is nothing this contract promises.
The rest of the m65 contract — state tiers, the stack, the vector
and map hazards — is stated with P1 of
[TODO § M65 slice 2](TODO.md#m65-slice-2--the-mega65-platform-r7-platform-layer).

## 4. Stack contract

CSE and user code **share** the single 6502 stack page.  There is no
two-image swap; user→kernel and kernel→user transitions are flat
RTI/RTS-driven and cost about 20 cycles.

### Layout at userland entry

A fresh start pushes the sentinel at the user's SP (`reg_sp`, $FF
unless changed with `r s:`), then an RTI frame below it.  For
`reg_sp` = $FF, just before the RTI:

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
3 KERNAL push), the handler's call chain, and the REPL commands
typed at a break (`m`, `.`, `d`, `r`, stepping), with margin.

The deepest kernel path, the assembler, never runs on a break's
stack: `a` with a live session ends the session first (§ 1), which
resets SP to $FF.  `tests/unit/test_asm_src.py::TestKernelStackDepth`
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
