# CSE-as-Kernel — design rationale

Why CSE's runtime is shaped as an interrupt-driven kernel, and what
follows from that.  The contracts themselves are owned elsewhere:
what user code may rely on by
[userland_contract.md](userland_contract.md), the stack and memory
invariants by [memory_design.md § Stack
contract](memory_design.md#stack-contract), the handlers by
[main.md](modules/main.md), the gates and stepping by
[debugger.md](modules/debugger.md).

## 1. Core framing: CSE is a kernel

CSE's runtime is an interrupt service routine, not an application.
Control flow between CSE (the "kernel") and user code uses the
6502's native interrupt primitives:

- **kernel → user**: RTI from a synthesized user frame (same
  mechanism a KERNAL ISR uses to return to the interrupted program).
- **user → kernel**: BRK (a breakpoint, a step breakpoint, the
  program's own `brk`, or `brk_stub` after the top-level RTS) or NMI.
  Handled by the kernel's BRK/NMI dispatchers.

The REPL is the ISR body.  Every BRK from user code re-enters the
REPL with a fresh interrupt frame.

Terminology: **kernal** = CBM KERNAL (the ROM); **kernel** = CSE's
runtime.  The distinction matters because CSE *uses* the kernal
extensively.

## 2. Stack: shared, never swapped

The kernel does not swap the stack page at transitions.  After a
break it runs on the user's stack page, below the user's SP, with
balanced JSR/RTS discipline; its working depth is bounded by what
the user left free below its SP.

**Consequences:**
- A transition costs about 20 cycles of stack handling instead of a
  copy of the stack page, and no banked RAM is spent on a second
  stack image.
- The user's data above its SP survives a break, because the kernel
  never writes there; that is what lets `c` resume a program that
  stopped deep inside its subroutines.
- The kernel must be petite and clear about its stack footprint: the
  userland contract names the headroom user code leaves for it
  ([userland_contract.md § 4](userland_contract.md#4-stack-contract)).
- One fixed return path for user code: a fresh start pushes the
  address of `brk_stub` (minus 1) as the program's top-level return
  address, so a plain RTS ends the run with a BRK the kernel
  recognises.

## 3. User entry and exit

**Cold init enters the REPL directly.**  After `setup_interrupts`
and the rest of the one-time setup, cold init draws the splash,
records the kernel's SP and jumps to `main_loop_top` — the same
point every warm start and every break ends at.

**Commands that run user code** (`j`, `g`, `c`, `t`, `o`) do not
transfer control themselves.  They stage the state (`brk_pc`, the
step state) and the mode (`run_user_pending`), and return to the
main loop, which performs the transition at top level:

- `j` — start at an address (default: the current address).
- `g` — start at the label `main`.
- `c` — resume from the captured break state.
- `t` — step into: arm a step breakpoint on the next instruction(s)
  and resume.
- `o` — step over: like `t`, but a `JSR` is stepped over, its return
  address armed instead of its target.

All of them collapse to one primitive: restore the user's ZP and
registers, switch SP to the user's, push the `brk_stub` sentinel on
a fresh start only, push P and PC, set `in_userland`, RTI.  A fresh
start (`j`, `g`, the first run after a cold preview) uses
`return_to_userland`; a resume uses `restore_userland_state`, which
pushes no second sentinel.

**The BRK dispatcher** classifies every entry:
- `B=0` → a **real IRQ that fired while the kernal was banked out**.
  The dispatcher banks the kernal in, delegates to the kernal's IRQ
  body, and puts the interrupted `$01` back before the final RTI —
  by stack surgery, so the kernal's own RTI routes through a
  bank-out stub (§ 4).
- `B=1` → BRK at the address the CPU pushed minus 2:
  - `brk_stub` → the program returned normally (top-level RTS).
  - a breakpoint → breakpoint hit.
  - a step breakpoint while stepping → the next step, or the end of
    the step run.
  - otherwise → an unplanned BRK (crash / `$00` opcode).

**On the MEGA65** the same primitive and the same dispatcher run in
two-map terms.  The kernel runs under the CSE map (its code and data
in bank 3) with its own base page (`B = $1F`); user code runs under
the user map — the `SYS` map a `RUN`-started program finds — with
its own `B`.  The one piece of code both maps show, the resident stub
in CSE's page `0.1F00`, makes every switch: the primitive's last step
pushes the user's A X Y Z B and jumps into the stub, which installs
the user map, pops them and RTIs; a BRK or an NMI reaches the stub
through the KERNAL's vectors, the KERNAL's entry having pushed A X Y
Z B and set `B = 0`, and the stub installs the CSE map and `B = $1F`
and jumps to the dispatcher.  What is swapped is the bank state — the
program's map, CPU port and `$D030`, captured at the break and
installed at the resume; base page 0 is the user's throughout, and
the stack is shared as on the C64 (§ 2).
There is no `B=0` IRQ case: the KERNAL is mapped in both maps, so an
IRQ always runs the KERNAL's own handler.  The kernel reaches user
memory through far pointers, translating each user address through
the user map ([platform_layer.md § Far memory](platform_layer.md#far-memory)).

## 4. Interrupt vectors without trampolines

The RAM shadows of `$FFFA` and `$FFFE` point directly at the
handlers' "early-entry" code.  There is no trampoline region to
execute in banked memory and no extra indirection.

**"Early entry" is meaningful by construction.**  The CPU only reads
RAM at `$FFFA`/`$FFFE` when the kernal is banked out (the KERNAL ROM
is what's there otherwise).  Reaching the IRQ early entry therefore
means "this interrupt fired while the kernal was banked out" — no
runtime check is needed, the entry point itself is the signal.  The
early-entry path must leave `$01` exactly as the interrupted code
had it before its final RTI.

The kernal-in paths (`$FE43` for NMI, `$FF48` for IRQ/BRK) still
dispatch through `$0318`/`$0316` into the same handlers.  They arrive
with the kernal banked in and need no bank-out stub.  The NMI shadow
points straight at the NMI handler: the CPU sets I=1 as part of the
NMI sequence, so no shim is needed.

**Hook installation.**  One routine, `setup_interrupts`, writes all
four vectors (`$0316`, `$0318`, `$FFFA`, `$FFFE`) with direct stores,
and cold init calls it **before any bank-out**.  Invariant: the
kernal is never banked out while a vector could still point at
something else.  The code: [main.md § IRQ early-entry
bank-out](modules/main.md#irq-early-entry-bank-out).

**Userland contract clause on interrupt state:**

> Messing with the NMI vector breaks debug recoverability — the user
> loses their always-available RESTORE escape hatch.  Messing with
> the IRQ vector breaks breakpoints, because CSE's BRK handling flows
> through the IRQ dispatcher.  Messing with ROM banking must be
> handled with extreme care, especially when combined with vector
> changes; an inconsistent banking/vector pair is not recoverable by
> CSE and will require a warm start or reset.

Formalised in [userland_contract.md § 5](userland_contract.md#5-interrupt-vector-and-banking-hazards).

**On the MEGA65** there is one hook site, the KERNAL's vector table,
written through `VECTOR` with interrupts off, and no RAM shadows:
the KERNAL's interrupt entry is mapped in every map, so the early
entry has no reason to exist.  `IBRK` and `INMI` lead to the
resident stub, `IIRQ` stays the KERNAL's; the stub's CSE entries are
the only trampoline, and they exist because the kernel's code is not
visible in the user map ([§ 3](#3-user-entry-and-exit)).  The
banking clause becomes a reachability clause: a program may map and
bank as it likes — the stub captures its map (through the
Hypervisor's `hyppo_get_mapping`, as the CPU cannot read `MAP`), its
CPU port and `$D030` at every break, and the resume installs them
again — provided the KERNAL and CSE's page stay where an interrupt
finds them ([userland_contract.md § 5.5](userland_contract.md#55-on-m65)).

## 5. NMI contract

NMI means: **stop whatever we're doing and give the user a REPL
prompt that always works.**  Interrupting the kernal or the kernel
may leave state broken; that is the price of an always-reliable
RESTORE.

The NMI handler dispatches on `in_userland` without touching A
(`bit in_userland`, so bit 7 decides — the flag is `$80` while user
code runs, 0 in the kernel):

- **userland** — push A/X/Y into the same frame shape a BRK has and
  break into the debugger through the shared capture path
  (`dbg_reason` = NMI).
- **kernel** — `cse_refresh`: redraw the REPL (the classic
  RUN/STOP+RESTORE screen recovery).  The debug context, if any, is
  kept.

**`in_userland`** is set just before the RTI into user code (the
shared tail of `return_to_userland` and `restore_userland_state`)
and cleared at handler entry.  IRQ handling does not touch it: an
IRQ is not a user↔kernel transition.  Two paths, one flag, no
deferred state.  Details: [main.md §
cse_nmi_handler](modules/main.md#cse_nmi_handler).

## 6. Userland state contract

The kernel sorts the machine state user code sees into explicit
tiers — **preserved** (registers, the user's ZP image, the user's
stack and memory), **clobbered** (screen, VIC, the KERNAL cells CSE
manages, SID voice gates), **compromised** (IEC, tape, interrupt
timing) and **untouched** — so a program knows what survives a
break.  The tiers and their contents are owned by
[userland_contract.md § 2](userland_contract.md#2-state-contract).

## 7. KERNAL-as-terminal feature

Because CSE leaves the kernal functional and the REPL writes through
the kernal's screen conventions, **user programs can treat the REPL
as a terminal.**  Any output via `jsr CHROUT` (or other kernal screen
I/O) appears interleaved with CSE's REPL output naturally; any input
via `jsr CHRIN` reads from the same keyboard queue the REPL uses.

This turns CSE into something closer to a modern terminal
application for simple line-oriented I/O: user programs `jsr`-printf
debug messages, prompt the user, read a line, etc., without building
any custom I/O infrastructure.  The REPL "hosts" the user program's
stdout/stdin.  Combined with the debugger, this gives a development
loop of "write code that prints → assemble → `j` → see output next to
the prompt → break → inspect → iterate" without ever leaving CSE's
screen.

It is an intentional affordance, not a leak
([userland_contract.md § 6](userland_contract.md#6-kernal-as-terminal-affordance)).
