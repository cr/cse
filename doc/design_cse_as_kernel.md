# CSE-as-Kernel — design synthesis

> **Status:** Draft design, basis for a phase-scale refactor.
> **Created:** 2026-04-17.
> **DDD delta:** This document describes a *desired* state of the
> runtime's relationship to interrupts, stack, and userland.  The
> current code does not implement it.  The delta between this
> design and the code is *deliberate* and defines the scope of the
> next phase of work.  This is DDD Step 1 for that phase.

---

A consolidated summary of the design threads we've been working through. Structured as a basis for further discussion, not a commitment.

## 1. Core framing: CSE is a kernel

CSE's runtime is an interrupt service routine, not an application. Control flow between CSE (the "kernel") and user code uses the 6502's native interrupt primitives:

- **kernel → user**: RTI from a synthesized user frame (same mechanism a KERNAL ISR uses to return to the interrupted program).
- **user → kernel**: BRK (explicit, breakpoint, or stub-from-RTS) or NMI. Handled by the CSE-kernel's BRK/NMI dispatchers.

The REPL is the ISR body. Cold init establishes ISR context and hands off to the REPL; every BRK from user code re-enters the REPL with a fresh interrupt frame.

Terminology established: **kernal** = CBM KERNAL (the ROM); **kernel** = CSE's runtime. Distinction matters because CSE *uses* the kernal extensively.

## 2. Stack contract

Do not manipulate SP at transitions. The kernel inherits whatever SP the interrupt leaves it with, runs with balanced JSR/RTS discipline, and accepts the constraint that its working depth is bounded by "256 minus whatever the user's stack had consumed at the moment of interrupt."

**Consequences:**
- No two-image stack swap (gone — 512 B KBSS reclaimed, ~1500-cycle transition → ~20 cycles).
- No `sp_baseline`, no `cse_sp`, no clean-RTS sentinel.
- Invariant: *init starts with SP=$FF, must end with SP=$FF.*
- The kernel must be petite and clear about its stack footprint. The userland contract names the maximum kernel stack depth user code must leave room for.
- User code's data above its current SP is preserved because the kernel never pushes into that region (its pushes are all below user SP by construction).

## 3. User entry / exit mechanisms

**Cold init → first REPL entry: maximise code sharing with warm-start.** After `setup_interrupts`, cold init sets up userland-like state (SP=$FF, regs=0, PC to a known marker) and BRKs into the kernel. The BRK lands in the standard dispatcher, is classified as "cold entry," and flows into the warm-start recovery routine **entered at a late-entry label that skips the screen clear**. In other words: factor warm-start so that `warm_start` and `warm_start_no_clear` (or equivalent) are the same code path with two entry points — cold init uses the late entry, a full warm recovery uses the early entry. No separate cold-init prompt routine; the REPL reaches steady state through the same well-tested path that RESTORE uses.

**Commands that transition kernel → user** (each synthesizes an RTI frame, sets `in_userland`, manages `brk_stub` on user's stack, and RTIs):

- `j` (jump) — start execution at a user-supplied address, with specified registers.
- `g` (go) — likely an alias for `j` that reuses the current saved state (PC, regs) rather than taking new arguments; "continue from where we are."
- `c` (continue) — resume user code from the captured break state; same mechanism as `g` but semantically "exit the debugger."
- `t` (trace / step) — set a one-shot breakpoint on the next instruction (or the return target for step-over), then RTI.
- `o` (step out) — set a one-shot breakpoint at the return address on user's stack, then RTI.
- Any other RTI-to-user exits (future `step-into-call`, etc.) follow the same pattern.

All of these collapse to one mechanical primitive: **populate `reg_*` shadows, push `brk_stub` onto user's stack, set `in_userland`, push P + PC for RTI, RTI.** A shared `return_to_user` helper is natural.

**BRK dispatcher**, on any entry, classifies:
- `B=0` → **real IRQ that fired while kernal was banked out**. The dispatcher banks kernal in, delegates to the kernal's IRQ handler, banks out before the RTI. Handled via stack surgery so the kernal's natural RTI routes through our bank-out stub. (This is the "early entry" case from §4.)
- `B=1` → BRK → look at `brk_pc - 1`:
  - matches `brk_stub` → user returned normally (top-level RTS).
  - matches an armed breakpoint → breakpoint hit.
  - otherwise → unplanned BRK (crash / `$00` opcode).

## 4. Interrupt vectors and trampolines

**No separate trampolines.** Patch the RAM shadows of `$FFFA` and `$FFFE` directly to point at CSE's handler "early-entry" labels. This closes the "trampoline executed in banked memory" window and eliminates a layer of indirection.

**"Early entry" is meaningful by construction.** The CPU only reads RAM at `$FFFA`/`$FFFE` when the kernal is banked out (KERNAL ROM is what's there otherwise). Therefore reaching the early-entry handler unambiguously means **"this interrupt fired while the kernal was banked out."** No runtime check needed — the entry point itself is the signal. Consequence: the early-entry path **must bank the kernal back out before its final RTI** so the interrupted CSE code resumes with the banking state it had.

The standard kernal-in paths (`$FE43` for NMI, `$FF48` for IRQ/BRK) still dispatch through `$0318`/`$0316` into the same handlers. Those paths arrive with kernal already banked in and don't need the bank-out stub.

**Dispatcher entry shape:**

- IRQ/BRK early entry: ~10-byte prologue replicating `$FF48`'s register push + B-flag test, then jumps to the appropriate handler. No `$01` manipulation in the prologue; banking is handled within the specific IRQ delegation path (which needs to bank in + out around the kernal IRQ call).
- NMI early entry: minimal, since `$FE43`-style dispatch is already trivial; hands directly to the NMI dispatcher.

**Userland contract clause on interrupt state:**

> Messing with the NMI vector breaks debug recoverability — the user loses their always-available RESTORE escape hatch. Messing with the IRQ vector breaks breakpoints, because CSE's BRK handling flows through the IRQ dispatcher. Messing with ROM banking must be handled with extreme care, especially when combined with vector changes; an inconsistent banking/vector pair is not recoverable by CSE and will require a warm start or reset.

## 5. NMI contract

NMI means: **stop whatever we're doing and give the user a REPL prompt that always works.** Interrupting the kernal or CSE-kernel may leave state broken; we accept this as the price of always-reliable RESTORE.

**Handler:**
```
nmi_handler:
    pha
    lda in_userland
    beq @not_userland
    pla
    pha / txa / pha / tya / pha     ; $FF48-equivalent register save
    jmp cse_brk_handler             ; treat as BRK-like entry
@not_userland:
    pla
    rti                             ; swallow; interrupted code resumes
```

**`in_userland` flag:**
- **Set** just before RTI to user, in the shared `return_to_user` helper invoked by `cmd_j`, `cmd_g`, `cmd_c`, `cmd_t`, `cmd_o`, and any future RTI-to-user commands.
- **Cleared** at BRK handler entry.
- Not touched by IRQ handling (IRQ doesn't transition user↔kernel in CSE's mode-sense).

Two paths, one flag, no deferred state, no `nmi_pending` quiet-point plumbing. RESTORE-at-prompt does nothing (user can bind screen-redraw to a different key if desired).

## 6. Interrupt hooking: unified setup routine

Merge `kernal_init` and `install_hooks` into a single `setup_interrupts` called **before any bank-out** in cold init. Direct writes to `$0316`/`$0318` using hardcoded C64 addresses (step 1); future migration to kernal VECTOR for cross-kernal compatibility (step 2).

**Invariant:** bank-out is forbidden until the vector table points at CSE-kernel handlers. Move `sym_clear` / `define_ws_syms` after `setup_interrupts`.

**Trampolines are no longer required.** The handlers live in the CODE segment (at their link-time addresses in `$7F00+`). RAM `$FFFA`/`$FFFE` point directly at handler early-entry labels. The IRQ/BRK handler's ~10-byte dispatch prologue is part of its normal code, not a separate trampoline region.

## 7. Userland state contract

Three tiers, explicit:

**Preserved (kernel guarantees):**
- CPU state: A/X/Y/P/PC/SP (for `c`/`t` continuation).
- ZP `$80-$FF` (kernel uses only `$00-$7F`).
- User's memory outside kernel regions (workspace, heap).

**Clobbered (kernel freely modifies; documented):**
- Screen RAM, color RAM (REPL renders its prompt, editor, logs).
- VIC registers forced to readable state on debug entry (display on, text mode, standard charset pointer, sprites off, raster IRQ off).
- ZP `$00-$7F` (kernel's half).
- Cursor position and related kernal ZP.
- **SID voice gates** cleared at user→kernel transition to stop stuck notes. Register values otherwise preserved so the user can inspect what was set.

**Compromised (neither kernel nor user should expect recovery):**
- IEC bus state — CSE uses disk for `l`/`s`; any in-flight user disk operation is forfeit.
- Tape / RS-232 state — same.
- Kernal-internal ZP `$80-$FF` — kernel calls kernal routines.
- Interrupt-timing-sensitive behavior (CIA timers, user raster IRQs).

**Untouched (kernel does not read or write):**
- SID registers (`$D400-$D41C`) beyond the voice-gate clear above. `io_blip` remains for now; it writes a brief error tone and is out of scope for the current refactor. User SID state (register values) is preserved across the gate-clear.
- Sprites — registers untouched. May render over REPL visually, but state survives.
- CIAs beyond what kernal IRQ handling perturbs.

## 8. KERNAL-as-terminal feature

Because CSE leaves the kernal functional and the REPL writes through the kernal's screen conventions, **user programs can treat the REPL as a terminal.** Any output via `jsr CHROUT` (or other kernal screen I/O) appears interleaved with CSE's REPL output naturally; any input via `jsr CHRIN` reads from the same keyboard queue the REPL uses.

This turns CSE into something closer to a modern terminal application for simple line-oriented I/O: user programs `jsr`-printf debug messages, prompt the user, read a line, etc., without building any custom I/O infrastructure. The REPL "hosts" the user program's stdout/stdin. Combined with the debugger, this gives a development loop of "write code that prints → assemble → `j` → see output next to the prompt → break → inspect → iterate" without ever leaving CSE's screen.

Document this as an intentional affordance, not a leak.

## 9. Outstanding TODOs captured in `doc/TODO.md`

- Interrupt hooking + trampoline rework (step 1: merge + hardcoded; step 2: kernal VECTOR migration).
- Loader reverse-direction copy (eliminates `payload_end < runtime_start` build cap).
- VIC sanity reset on kernel/userland boundary.
- SID silence (REPL command + voice-gate clear at boundary).

## 10. Known gaps / next design passes

- **Kernel stack depth measurement.** Need a worst-case audit so the userland contract can state "user code must leave at least N bytes of stack headroom."
- **Cold init → warm-start shared path detail.** Identify the exact label in the warm-start routine where the screen-clear is skipped; confirm the rest of the warm path is safe to enter at that point without preconditions cold-init doesn't satisfy.
- **IRQ early-entry bank-out mechanism.** Stack surgery so the kernal's RTI routes through our bank-out stub. Reentrance under NMI. 2-byte BSS stash vs stack-resident save.
- **brk_stub placement.** Must be at a fixed, non-banked address reachable from user's pushed RTS return.
- **Shared `return_to_user` helper.** Implementation detail: one code path used by all RTI-to-user commands (`j`, `g`, `c`, `t`, `o`, ...).
- **Userland contract document.** Formalise §7 as `doc/userland_contract.md` or a section in `doc/modules/debugger.md`, including the §4 clause on vector/banking hazards and the §8 terminal-affordance framing.
- **Stack contract document.** Formalise §2 as a section in `doc/memory_design.md`.

---

## How to resume this work

Next session should:

1. **Read this document end-to-end** before touching any code.
2. **Pick a starting point** from §10 (Known gaps).  Highest-leverage
   candidates:
   - Drafting the formal stack-contract section in
     `doc/memory_design.md` (unblocks most implementation).
   - Drafting the userland contract document (unblocks user-facing
     promises + enables meaningful tests).
   - Measuring kernel stack depth (empirical, forms a constraint on
     the contract).
3. **Do DDD Step 1 for the chosen slice** — update the relevant
   module doc(s) to describe the desired state before writing any
   code.  Get approval on the doc delta before proceeding to
   Step 2 (DDD Analysis) and Step 3 (TDD Analysis).
4. **Do NOT begin implementation** until the relevant contract
   document is drafted, reviewed, and approved.  The design in
   this document is comprehensive but still a sketch; module-level
   docs need to flesh out the mechanics before code can be written
   correctly.

The refactor this design enables is phase-scale.  Expect multiple
DDD cycles, each covering one or two sections of this document.
Do not attempt to implement §1-§8 in a single commit or even a
single session — the scope is too large, and the interactions
between sections require incremental verification.

## Cross-reference

- Existing trampoline bug TODO in `doc/TODO.md` (NMI/IRQ trampolines: asymmetric + latent crash windows) — subsumed by §4 and §6 of this document.  Once this design lands, that TODO closes as a side effect.
- Phase 17 two-image stack swap (committed as `8f68f28`, `c7de394`, etc.) — this design *replaces* that mechanism with a simpler one.  The swap stays in place until this refactor is executed.
