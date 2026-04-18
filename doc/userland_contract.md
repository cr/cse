# Userland Contract — What user code may rely on, and what it must preserve

This document defines the contract between the CSE **kernel** (the
runtime) and **userland** (any program executed via `j`, `g`, `c`,
`t`, or `o`).  It covers what state the kernel guarantees across a
user-code run, what state user code may freely modify, and where
user code can break the kernel's recovery guarantees if it crosses
specific lines.

For the design rationale that motivates this contract see
[design_cse_as_kernel.md](design_cse_as_kernel.md).

---

## 1. Mode model

CSE has two execution modes:

- **Kernel mode** — the CPU is running CSE code (REPL, editor,
  assembler, debugger).  Tracked implicitly: `in_userland = 0`.
- **Userland mode** — the CPU is running the user's program.
  Tracked by `in_userland = 1`.

Transitions:

- **kernel → userland**: `return_to_userland` synthesises an RTI frame
  from `reg_*` shadows, pushes `brk_stub - 1` onto the stack as
  user's top-level RTS sentinel, sets `in_userland = 1`, and RTIs.
- **userland → kernel**: any of three events:
  - **BRK** at a debugger breakpoint or step-BRK slot.
  - **BRK** at `brk_stub` (user's top-level RTS popped the sentinel).
  - **NMI** (RUN/STOP+RESTORE) — handler dispatches on
    `in_userland`.

The shared `cse_brk_handler` performs classification (bp / step /
clean / NMI / unplanned).  The `cse_nmi_handler` swallows NMI in
kernel mode and routes it through the BRK path in userland mode.

## 2. Three-tier state contract

User code's view of CPU and memory state, by tier:

### Preserved — kernel guarantees these survive every user run

- **CPU registers**: `A`, `X`, `Y`, `P`, `PC`, `SP` are saved on
  user→kernel transition and restored on the next kernel→userland
  transition (so `c`, `t`, `o` resume seamlessly after a break).
- **ZP `$80–$FF`** — kernal work area; CSE never writes here.
- **The user's own memory** outside the kernel's regions:
  workspace ($0800–workend), heap, page-2 / page-3 free fragments
  (provided the user owns those bytes per § 4 below).

### Clobbered — kernel freely modifies; documented for reference

- **Screen RAM** ($0400–$07E7) and **color RAM** ($D800–$DBE7).
  REPL renders prompt/disassembly/logs across the screen.
- **VIC registers** are forced to a readable text-mode state on
  every userland → kernel transition (display on, 25 rows, text
  mode, no extended/bitmap, sprites off, raster IRQ off, charset
  pointer = standard, scroll = 0).  See `vic_reset` in main.s.
- **ZP `$00–$7F`** — CSE's half of zero page.  Saved at userland
  entry to `kernel_zp_buf` and restored at userland exit; the live
  view between break and resume reflects the user's ZP, not CSE's.
- **Cursor position and related kernal ZP** ($D1/$D2, $D3/$D6,
  $F3/$F4, $CC) — REPL re-syncs via `io_sync` on every kernel
  display.
- **SID voice gate bits** ($D404 / $D40B / $D412 bit 0) are cleared
  at userland → kernel transition to stop stuck notes.  The other
  SID register values are preserved so the user can inspect what
  was set.

### Compromised — neither side should expect recovery

- **IEC bus state** — CSE uses disk for `l`/`s` and directory; any
  in-flight user disk operation is forfeit.
- **Tape / RS-232 state** — same.
- **Kernal-internal ZP `$80–$FF`** — kernel calls kernal routines
  that mutate this region.
- **Interrupt-timing-sensitive behaviour** — CIA timers, user raster
  IRQs, anything that depends on cycle-precise IRQ delivery.  CSE
  blocks IRQs around its bank-toggle windows.

### Untouched — kernel does not read or write these

- **SID registers** ($D400–$D41C) beyond the voice-gate clear
  above.  User SID register values are preserved across the break.
- **Sprites** — registers untouched.  Sprites may render over the
  REPL visually, but state survives.
- **CIAs** beyond what kernal IRQ handling perturbs.

## 3. Memory regions

| Region | Address | User code may use |
|--------|---------|-------------------|
| User ZP | $00–$7F | Yes — saved/restored per run |
| Kernal ZP | $80–$FF | **No** — must preserve |
| Stack page | $0100–$01FF | Yes — see § 5 (Stack contract) |
| Kernal editor state | $0200–$02A6 | **No** |
| Free | $02A7–$02FF | Yes (89 B) |
| Kernal vectors | $0300–$0333 | **No** — CSE hooks live here |
| Free (incl. tape buffer) | $0334–$03FB | Yes (200 B; restore if using tape) |
| BSOUT save | $03FC–$03FF | Avoid |
| Screen + sprite ptrs | $0400–$07FF | Clobbered each kernel display |
| Workspace | $0800–workend | User owns this — kernel never writes |
| CSE runtime | workend+1 – $CFFF | **No** — overwriting CSE is fatal |
| I/O | $D000–$DFFF | Yes |
| Banked under kernal | $E000–$FFFF | **No** — CSE owns banked layout |

## 4. Stack contract

CSE and user code **share** the single 6502 stack page.  There is no
two-image swap; user→kernel and kernel→user transitions are flat
RTI/RTS-driven and cost ~20 cycles.

### Layout at userland entry

Just before `return_to_userland`'s RTI, the stack from SP downward looks
like:

```
$01XX  PClo  ─┐
$01XX-1 PChi │ RTI frame (popped by RTI)
$01XX-2 P    ─┘
$01XX-3 (brk_stub - 1) lo  ─┐  user's top-level RTS sentinel
$01XX-4 (brk_stub - 1) hi  ─┘
... below: kernel state from the moment of return_to_userland ...
```

The kernel state below the sentinel is *not used after the RTI*: the
BRK handler longjmps back to `main_loop` and discards everything
above its target SP.  User code can therefore safely overwrite any
byte below its current SP — those bytes will never be read again by
the kernel.

### User stack budget

User code starts with **~240 bytes** of free stack on first entry.
Concretely: SP at the moment of RTI ≈ $FF − (kernel call chain) − 5
(sentinel + RTI frame).  Worst-case kernel chain at `return_to_userland`
is small (main_loop → exec_line → cmd_X → return_to_userland, ≤ 8
bytes), so first-entry user SP is around $F2.

User code may reset SP to $FF and claim the entire 256-byte page;
if it does so, the brk_stub sentinel is overwritten and the user's
top-level RTS must explicitly land somewhere meaningful (or the
program must terminate via BRK / forced jump rather than RTS).

### Kernel stack budget

The user contract: **user code must leave at least 64 bytes of stack
headroom when calling kernal routines or when a debugger break may
occur.**

This number is **conservative**, pending empirical measurement (see
[TODO.md § Phase 18](TODO.md)).  The 64 B has to cover:

- BRK frame: 6 B (3 hardware + 3 kernal $FF48 push sequence).
- BRK-handler internal call chain to longjmp / chain-step: currently
  ~8 B peak (`jsr save_userland_zp`, `jsr dbg_bp_find` — non-nested),
  but reserved up to the depth of the deepest non-execution kernel
  path that could ever run on the BRK return side.
- The deepest kernel call chain that may legitimately run from the
  BRK handler tail before returning to the REPL.  **Worst case
  reference: the assembler pipeline (`asm_src` → `asm_line` →
  `expr_eval` → recursive descent), which is the deepest kernel
  path in the system.**  Future debugger features (conditional
  breakpoints with expression evaluation, trace BPs that print via
  io_puts, watchpoints) may add comparable depth on the BRK path.
- Safety margin.

**Once empirical measurement lands**, the contract will be tightened
and CSE will add a runtime warning: at every BRK-handler entry, if
user's SP indicates insufficient headroom, log `;!stk N` (where N is
the actual headroom) so the user can see the violation.  A runtime
test in the suite will exercise the deepest kernel path against the
chosen budget.

User code that runs deep recursion to within the budgeted bytes of
stack exhaustion and then triggers a break will overflow the page
and corrupt low memory ($00FF↓ wraps).  This is the documented
limit; the kernel cannot guard against it (only warn, after the
empirical measurement TODO lands).

### Cold-start sentinel

On boot, cold init synthesises the very first userland frame:

- SP set to a known value (e.g. $FE) with `(brk_stub - 1)` at $01FF.
- RTI frame for PC = `brk_stub`, P = clean.
- RTI → CPU lands at `brk_stub` → BRK fires immediately.

The BRK handler classifies this as a clean exit (PC-1 == brk_stub)
and flows into the warm-start tail at the late-entry label that
skips the screen clear (the splash screen is already drawn).  The
REPL then runs normally.  Cold init shares its post-init code path
with userland-recovery via this mechanism.

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
(by the very fact of being reached from RAM-resident vectors) and
banks kernal back in before the final RTI.

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
style development:

```asm
        ldx #0
@l:     lda msg,x
        beq @done
        jsr $FFD2            ; CHROUT
        inx
        bne @l
@done:  rts                  ; clean exit → REPL prompt below output

msg:    .str "hello, world", 13, 0
```

After `g`, the REPL reads:

```
0800:g
hello, world
0800:
```

This is an intentional affordance, not a leak.  The userland contract
documents it as supported behaviour: CHROUT/CHRIN/GETIN work, and
their output integrates with REPL display.

## 7. Practical guarantees, summarised

When user code is `j`/`g`/`c`/`t`/`o`-launched, it can rely on:

1. The screen is text-mode, lowercase charset, sprites off, IRQs
   running at the kernal jiffy rate.
2. `JSR $FFD2` (CHROUT) writes to the visible REPL cursor.
3. CPU registers and ZP $00–$7F are restored to whatever the user
   set with `r` (or to the values from the previous break).
4. The hardware stack page is the user's; the kernel will not
   touch any byte below the user's current SP.
5. RUN/STOP+RESTORE will break into the debugger.
6. Top-level RTS will return cleanly to the REPL (regardless of
   whether the user reset SP, provided their RTS puts a valid
   address on the stack).
7. The workspace ($0800–workend) is the user's exclusively; CSE
   reads it only for assembly source / disassembly / hex dump.

User code **must**:

1. Preserve $80–$FF, $0200–$02A6, $0300–$0333.
2. Not overwrite the CSE runtime (workend+1 to $CFFF).
3. Leave at least 64 bytes of stack headroom if a break may occur.
4. Not leave the kernal banked out across an IRQ if it has also
   redirected $FFFE/$FFFA away from CSE handlers.

Beyond these, user code is free.

## 8. Cross-references

- [design_cse_as_kernel.md](design_cse_as_kernel.md) — design synthesis
- [memory_design.md](memory_design.md) § Stack contract — implementation
- [modules/main.md](modules/main.md) — `cse_brk_handler`,
  `cse_nmi_handler`, `setup_interrupts`, `in_userland`
- [modules/debugger.md](modules/debugger.md) — `return_to_userland`,
  `brk_stub`, register save/restore
