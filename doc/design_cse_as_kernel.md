# CSE-as-Kernel — design synthesis

> **Status:** Phase 18 landed in commit `a628e65` (2026-04-18).
> This document is retained as the design rationale; the
> codebase now implements it.  Post-Phase-18 commits: `7351292`
> (housekeeping), `fc52046` (code sharing), `8e60b62` (SEI/CLI
> drop), `778a1f4` (disk helper).
> **Created:** 2026-04-17.
>
> The design state is propagated across the corpus:
> - [doc/memory_design.md](memory_design.md) § Stack contract
>   (rewritten: shared stack, no two-image swap)
> - [doc/userland_contract.md](userland_contract.md) (new, formalises §7 + §8 + §4 last clause)
> - [doc/modules/main.md](modules/main.md) (`cse_brk_handler`,
>   `cse_nmi_handler`, `setup_interrupts`, `in_userland`)
> - [doc/modules/debugger.md](modules/debugger.md) (`return_to_userland`,
>   `brk_stub`; two-image swap content removed)
> - [doc/modules/mem.md](modules/mem.md) (`kernal_init` retired;
>   trampolines retired)
> - [doc/modules/repl.md](modules/repl.md) (REPL framed as ISR
>   body; `run_user` wrapper eliminated — commands set
>   `run_user_pending` + rts, main_loop dispatches the gate)
> - [doc/architecture.md](architecture.md) (kernel/userland framing
>   in layer diagram and module summaries)
> - [doc/glossary.md](glossary.md) (kernel/kernal/userland/
>   in_userland/brk_stub/return_to_userland/cold entry/early entry)
> - [doc/TODO.md](TODO.md) (Phase 18 master entry consolidates
>   sub-items; old NMI/IRQ trampoline entry retired into it)
>
> The corpus describes the current (post-Phase-18) state.

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

All of these collapse to one mechanical primitive: **populate `reg_*` shadows, push `brk_stub` onto user's stack, set `in_userland`, push P + PC for RTI, RTI.** A shared `return_to_userland` helper is natural.

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
    bit in_userland
    bne @break_user                ; $80 (bit 7 set) → break into debugger
    jmp cse_refresh                ; kernel mode → refresh screen
@break_user:
    sta reg_a / stx reg_x / sty reg_y
    jmp cse_brk_handler_userland_entry
```

**`in_userland` flag:**
- **Set** just before RTI to user, in the shared `return_to_userland` helper invoked by `cmd_j`, `cmd_g`, `cmd_c`, `cmd_t`, `cmd_o`, and any future RTI-to-user commands.
- **Cleared** at BRK handler entry.
- Not touched by IRQ handling (IRQ doesn't transition user↔kernel in CSE's mode-sense).

Two paths, one flag, no deferred state.  RESTORE at the REPL
prompt routes to `cse_refresh` (the classic C64 screen-recovery
affordance); the debug context, if any, is preserved across the
NMI.  See [main.md § cse_nmi_handler](modules/main.md) and
[memory_design.md § Warmstart entry points](memory_design.md#warmstart-entry-points).

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

Status updated after corpus propagation (2026-04-17):

- **Kernel stack depth measurement.** ⏳ Open — empirical audit
  deferred to implementation phase.  Conservative documented
  contract: **64 bytes** of user-side headroom (deliberately
  generous, sized to accommodate the assembler pipeline depth as
  a worst-case reference).  Once measured, the contract tightens
  and CSE adds a runtime warning (`;!stk N`) on every BRK handler
  entry where user's SP is below the budget.  Tracked in
  [TODO.md § Phase 18](TODO.md) as "Kernel stack-depth measurement"
  + "CSE re-entry stack-headroom warning."
- **Cold init → warm-start shared path detail.** ✅ Resolved by
  propagation: cold-init handoff RTIs to `brk_stub`, BRK fires,
  handler classifies as clean exit, longjmps to
  `main_loop_no_clear`.  See [modules/main.md](modules/main.md)
  § Four-layer architecture.
- **IRQ early-entry bank-out mechanism.** ✅ Resolved: stub in
  CODE; second RTI frame synthesised before `JMP $EA31` (kernal
  IRQ body); kernal's RTI lands at the bank-out stub which banks
  kernal back out and RTIs the original frame.  Reentrance under
  NMI is non-problematic because both NMI and IRQ early-entry
  paths bank kernal back to a consistent state before exiting.
  Full byte sequence in [modules/main.md § IRQ early-entry bank-out](modules/main.md).
- **brk_stub placement.** ✅ Resolved: code label in main RAM at
  link-time address.  Reachable from user RTS via the
  pre-pushed `(brk_stub - 1)` sentinel.  See
  [modules/debugger.md](modules/debugger.md) § brk_stub.
- **Shared `return_to_userland` helper.** ✅ Resolved: documented in
  [modules/debugger.md](modules/debugger.md) § return_to_userland.
  Includes ZP save and patch_all (pairs with handler tail's
  unpatch_all + ZP restore).  Implementation lives in debugger.s.
- **`cmd_step` chaining model.** ✅ Resolved: handler-resident
  state machine (Option B).  cmd_step seeds `step_state` /
  `step_remaining`, sets `run_user_pending`, and rts's; the
  main_loop dispatches through `return_to_userland` (cold) or
  `restore_userland_state` (hot).  The BRK handler tail decides
  chain-or-finish (step-chain path reuses `restore_userland_state`
  directly).  No SP creep across iterations.  See
  [modules/debugger.md § Single-step](modules/debugger.md).
- **NMI in kernel mode.** ✅ Resolved: routes to `cse_refresh`
  (Phase 20 — warmstart restructure).  Kernel-mode NMI is the
  classic C64 RUN/STOP+RESTORE screen-recovery affordance; the
  debug context is preserved across the refresh.  Previously this
  was handled by swallowing.  See
  [main.md § cse_nmi_handler](modules/main.md).
- **`kernel_init_sp` longjmp target.** ✅ Resolved: 1-byte BSS
  in main.s, captured at cold-init top, used by every BRK handler
  longjmp.  See [modules/main.md § Longjmp SP convention](modules/main.md).
- **Userland contract document.** ✅ Resolved:
  [doc/userland_contract.md](userland_contract.md).
- **Stack contract document.** ✅ Resolved: rewritten in
  [memory_design.md § Stack contract](memory_design.md#stack-contract).

---

## Phase 18 retrospective (for future work in this area)

Phase 18 was executed as one large atomic cutover (commit
`a628e65`) after the design had been fully propagated across the
corpus.  The cutover covered: gate primitives, handler_finalize
universal longjmp, CPU-port-aware ZP swap, direct vector patching,
command-loop flag-and-rts pattern, $80/0 `in_userland` convention,
`brk_stub` sentinel.  Follow-up commits tightened the result:
`7351292` housekeeping, `fc52046` code sharing, `8e60b62` SEI/CLI
redundancy, `778a1f4` disk helper.

Remaining Phase 18 tail items (tracked in `TODO.md`):
- Kernel stack depth audit — refine the 64 B headroom contract
  from conservative to measured-plus-margin.
- SID voice-gate silence at the userland → kernel boundary.

If a similar phase-scale refactor comes up again, the working
pattern was: document the desired state across the corpus first
(DDD Step 1), then implement as a single atomic cutover once all
affected modules' docs are mutually consistent.  Tests (especially
C64Emu-level kernel-transition tests) get written in Step 3
alongside the design review.

## Cross-reference

- Existing trampoline bug TODO in `doc/TODO.md` (NMI/IRQ trampolines: asymmetric + latent crash windows) — subsumed by §4 and §6 of this document.  Closed as a side effect when Phase 18 landed (`a628e65`).
- Phase 17 two-image stack swap (`8f68f28`, `c7de394`, etc.) — replaced by this design's flat shared-stack model.  512 B KBSS and ~1500 cycles per transition reclaimed in Phase 18.
