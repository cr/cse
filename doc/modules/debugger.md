# debugger — Step State Machine + Kernel↔Userland Gates (L4)

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/debugger.s`](../../src/debugger.s) | implementation: step state, `dbg_init`, `save/restore_userland_state`, `return_to_userland`, `brk_stub` |
| [`tests/integration/test_kernel_transition.py`](../../tests/integration/test_kernel_transition.py) | tier-I tests: kernel↔user transitions, step chains |
| [`tests/integration/test_step_rom.py`](../../tests/integration/test_step_rom.py) | tier-I tests: step-into-ROM fallback |

The debugger is the kernel's **userland gateway**.  It owns the
`return_to_userland` helper (the one place that synthesizes RTI frames
into user code) and the `brk_stub` (the fixed code address user's
top-level RTS lands at).  All BRK/NMI dispatch is owned by main.s
and lives in `cse_brk_handler` / `cse_nmi_handler`.

**Split (2026-04-20 structural refactor).**  Breakpoint-table CRUD
and patching live in [breakpoints.md](breakpoints.md) at L3 — a
pure data-structure module that bundle-tests in isolation.  This
module (debugger.s, L4) keeps everything that genuinely requires
the CPU interrupt protocol + KERNAL vectors: the step state
machine, `save/restore_userland_state` primitives, `return_to_userland`
wrapper, `brk_stub`, and `dbg_init`.  The split makes the tier
boundary compile-time-enforced (L4 `debugger.s` imports from L3
`breakpoints.s`, never the reverse) rather than a disciplined
convention.

For the design framing (CSE as kernel, kernel↔user transitions via
RTI/BRK) see [design_cse_as_kernel.md](../design_cse_as_kernel.md)
and [userland_contract.md](../userland_contract.md).

## Interface

### return_to_userland
**In:** `reg_a`, `reg_x`, `reg_y`, `reg_p`, `brk_pc` populated
with the user state to install.
**Out:** does not return — RTIs into user code at `brk_pc`.
**Clobbers:** all (control transfers to user)

The single shared kernel→userland wrapper, used by `cmd_jmp`
(`j`/`g`) and `cmd_continue` (`c`).  `return_to_userland` pushes a
fresh `brk_stub - 1` sentinel before falling into the shared
body (`restore_userland_state`).  The step-chain tail and `t`/`o`
resume paths jump to `restore_userland_state` directly — no new
sentinel (the one from the initial fresh start is still valid).

Sequence (via `_rtu_body`, shared between `return_to_userland` and
`restore_userland_state`):

1. `patch_all` — write $00 at every armed bp/step slot.
2. `save_kernel_zp` (mem.s) — live ZP → `kernel_zp_buf`,
   single-pass DDR-stash (see mem.s § CPU-port aware ZP
   save/restore).
3. `restore_userland_zp` (mem.s) — `userland_zp_buf` → live ZP,
   DDR=$FF-first backwards copy.
4. `ldx reg_sp / txs` — switch SP to user's saved SP.
5. (return_to_userland only) push sentinel (PCH then PCL of
   `brk_stub - 1`).
6. Push RTI frame — PCH, PCL, P (in that push order, so RTI
   pops them back as P, PCL, PCH).
7. `sta in_userland` = $80 (bit 7 set — the convention required
   by `cse_nmi_handler`'s A-independent `bit / bmi` test).
8. Load A/X/Y from `reg_a` / `reg_x` / `reg_y`.
9. `rti` — CPU pops P/PCL/PCH, jumps to user's PC.

ZP swap and `patch_all` live INSIDE the shared body (rather than
in callers) so every kernel→userland transition is symmetric
with the BRK handler's `save_userland_state` / `unpatch_all`.
This makes the transition primitives the single source of truth
for the bracket contract.

### brk_stub
**Address:** stable code label, exported.

A 1-byte `BRK` instruction (opcode $00) followed by a 1-byte
signature.  When user code performs its top-level RTS, it pops
the (brk_stub-1) sentinel pre-pushed by `return_to_userland`, lands at
`brk_stub`, and the BRK fires immediately.

The BRK handler classifies (PC-2 == brk_stub) as a clean userland
exit: sets `dbg_reason = DBG_RTS` (alive-but-terminal — same
classification as landing at an RTS/RTI opcode mid-step) and
resets `brk_pc := cur_addr` so the display shows a user-meaningful
address rather than brk_stub's internal location.

### dbg_init
**In:** none
**Out:** breakpoint table zeroed, flags cleared
**Clobbers:** A, X

Called at startup and on warm-start recovery.

### save_userland_state / restore_userland_state
The two complementary gate primitives for userland ↔ kernel
transitions.  Both operate on stack-resident regs, the ZP
save/restore buffers in mem.s, and `in_userland`.

**save_userland_state** (called from `cse_brk_handler` /
`cse_nmi_handler` after dispatch and after `in_userland` is
cleared).  Extracts Y/X/A/P/PCL/PCH from the stacked BRK+KERNAL
frame into `reg_*` / `brk_pc`, computes `reg_sp = SP + 8` (the
BRK frame's 6 bytes + the 2-byte jsr return that reached
save_userland_state), then calls `save_userland_zp` (capture user
ZP) and `restore_kernel_zp` (both in mem.s — see the CPU-port
protocol note there).  Raw P is stored; BRK-vs-NMI masking of P
and the `brk_pc` −= 2 adjust (BRK only) happen in the calling
handler, because the masks differ by source.

**restore_userland_state** (called from main_loop's dispatch
after a resume command, and from the BRK handler's step-chain
body) — the shared body `_rtu_body` above.  Does the full
kernel → userland reinstall in the sequence documented in the
return_to_userland Sequence list.

### dbg_bp_set
**In:** A/X = address (lo/hi)
**Out:** C=0 success (A = slot number), C=1 table full
**Clobbers:** A, X, Y

### dbg_bp_del
**In:** A = slot number (0-based)
**Out:** C=0 success, C=1 invalid slot
**Clobbers:** A, X

### dbg_bp_clear
**In:** none
**Out:** all breakpoint slots cleared
**Clobbers:** A, X

### dbg_bp_count
**In:** none
**Out:** A = number of non-empty breakpoint slots (0–8)
**Clobbers:** A, X

### dbg_bp_find
**In:** A = addr lo, X = addr hi
**Out:** C=0 found, A = slot number (0–7).  C=1 not found, A = $FF.
**Clobbers:** A, X, Y

Used by the BRK handler to identify which breakpoint slot was hit.

### REPL (repl.s command handlers)

- `cmd_jmp(args)` — `j`/`g` commands: populate `reg_*`, call
  `return_to_userland`.
- `cmd_continue` — `c` command: re-call `return_to_userland` with
  the saved state from the previous break.
- `cmd_brk(args)` — `b` command: set, list, or delete breakpoints.
- `cmd_step(args, is_next)` — `t`/`o` commands: arm step BRKs,
  call `return_to_userland`, repeat until count exhausted.

**State:**
- `bp_table` — 8 breakpoint slots (see § Breakpoint table)
- `dbg_reason` — session state + break classification.  Ordered so
  "can continue from here?" is a single compare (see § `dbg_reason`
  enum below).  Values: `DBG_NONE` (0), `DBG_RTS` (1), `DBG_BRK` (2),
  `DBG_NMI` (3).
- `brk_pc` — PC where the break occurred / execution will resume
- `dbg_bp_hit` — slot number of the breakpoint that was hit ($FF = none)
- `step_bp` — temporary breakpoint(s) for single-step (2 slots)

#### `dbg_reason` enum — ordered by "liveness"

```
DBG_NONE = 0    ; no session (never started, or ended via end-debug)
DBG_RTS  = 1    ; session active, terminal — landed at RTS/RTI opcode
                ;   or user top-level RTS popped brk_stub sentinel.
                ;   Can't step / continue past this without restarting
                ;   via j/g (which establishes a fresh sentinel).
DBG_BRK  = 2    ; session active, resumable — stopped at a non-return
                ;   op (step BRK, user bp, unplanned user BRK).
DBG_NMI  = 3    ; session active, resumable — NMI landed in userland.
```

**Ordering invariant:** `dbg_reason >= DBG_BRK` iff the session can
proceed via `c` or be extended via `t`/`o`.  Single compare:

```asm
lda dbg_reason
cmp #DBG_BRK
bcs @resumable       ; active AND can continue
; else: DBG_NONE (0) or DBG_RTS (1) — no resume
```

| Check | Code | Bytes |
|---|---|---|
| Any session at all | `lda / bne` | 4 |
| Resumable (`c`, warm step) | `lda / cmp #DBG_BRK / bcs` | 5 |
| No session (dead) | `lda / beq` | 4 |
| At RTS (terminal-alive) | `lda / cmp #DBG_BRK / bcc + bne` | 7 |

The consolidation of "clean exit via brk_stub" and "stopped at
RTS/RTI opcode" under a single `DBG_RTS` means the handler is the
sole site that classifies by inspecting the break-PC and opcode.
Every consumer (show_break_result, cmd_continue, cmd_step) reads
`dbg_reason` alone — no brk_pc address comparisons, no opcode peeks
outside the handler.

(The `dbg_running` flag from earlier designs is replaced by main.s's
`in_userland` flag, which is the single source of truth.)

### Memory

**BSS (~48 bytes):**

| Variable | Size | Purpose |
|----------|------|---------|
| `bp_table` | 32 | 8 breakpoint slots × 4 bytes |
| `step_bp` | 8 | 2 step breakpoint slots × 4 bytes |
| `brk_pc` | 2 | PC at break / resume address |
| `dbg_bp_hit` | 1 | Slot of breakpoint hit ($FF = none) |
| `reg_a/x/y/p/sp` | 5 | User register shadows |
| `reg_pc_lo/hi` | 2 | User PC shadow (= `brk_pc` low/hi) |
| `step_state` | 1 | 0=not stepping, 1=`t`, 2=`o` (handler-resident state machine) |
| `step_remaining` | 1 | Iterations left after current step |

**No KBSS** — Phase 18 dropped the two 256-byte stack image
buffers (`user_stack_buf`, `cse_stack_buf`) and the `cse_sp` BSS
byte.  User and kernel share the single hardware stack page.

**Cross-module flags (in zp.s):**

| Name | Size | Role |
|---|---|---|
| `dbg_reason` | 1 | Session state + break reason.  `DBG_NONE` (0), `DBG_RTS` (1), `DBG_BRK` (2), `DBG_NMI` (3) — ordered by liveness (`>= DBG_BRK` is resumable).  See § `dbg_reason` enum. |
| `in_userland` | 1 | 1 = user code running, 0 = kernel |

Both are `.exportzp` in zp.s.  debugger.s writes them; main.s and
repl.s read them for dispatch decisions.

**Depends on:** asm_line (register state, ZP save), dasm (instruction
length for step), mem (ZP save/restore primitives), oplen_tbl, zp

## Design

### Breakpoint table

```
8 slots × 4 bytes = 32 bytes BSS

Offset  Size  Field
  0       2   addr       breakpoint address ($0000 = unused slot)
  2       1   saved      original byte at addr
  3       1   flags      bit 0 = enabled
```

Slot 0–7.  Address $0000 = empty.  The `saved` byte is captured
when the breakpoint is patched and restored when unpatched.

### Step breakpoints

2 additional slots (same layout, 8 bytes) used by `t` and `o` for
temporary breakpoints.  Cleaned up automatically after each step.
Two slots are needed because a branch instruction has two possible
next addresses (taken / not taken).

### Kernel ↔ userland transition

CSE is structured as a kernel; transitions are RTI/BRK-driven and
flat.  See [memory_design.md § Stack contract](../memory_design.md#stack-contract)
for the full contract.

**Kernel → userland (return_to_userland):**

```
return_to_userland:
        ; push user's top-level RTS sentinel
        lda #>(brk_stub - 1)
        pha
        lda #<(brk_stub - 1)
        pha
        ; build RTI frame (push order: P, PCH, PCL — RTI pops PCL/PCH/P)
        lda reg_p
        pha
        lda brk_pc+1
        pha
        lda brk_pc
        pha
        ; install live regs and mode flag
        lda #1
        sta in_userland
        ldx reg_x
        ldy reg_y
        lda reg_a
        rti
```

The RTI pops PCL/PCH/P, jumps to user's PC.  Below the RTI frame
sits the `brk_stub - 1` sentinel; user's top-level RTS pops it
and lands at `brk_stub`.

**Userland → kernel** routes through one of:

- BRK at debugger breakpoint slot (patched $00).
- BRK at step-BRK slot (patched $00 by `cmd_step`).
- BRK at `brk_stub` (clean exit).
- NMI in userland (RUN/STOP+RESTORE).
- Unplanned BRK ($00 opcode in user code, no slot match).

`cse_brk_handler` (main.s) classifies and calls
`dbg_brk_capture` (or `dbg_nmi_capture`) to populate the `reg_*`
shadows.  Then it longjmps SP to `main_loop_top` and resumes the
REPL.

### BRK mechanism (C64 hardware flow)

```
BRK executes at user address $AAAA:
  1. CPU pushes PChi, PClo ($AAAA+2), P (B=1, I=1) → stack
  2. CPU sets I=1 (masks IRQ)
  3. CPU loads PC from ($FFFE)
       kernal-in:  → $FF48 (KERNAL ROM)
       kernal-out: → cse_brk_handler early-entry label (RAM shadow)

KERNAL at $FF48:
  4. PHA; TXA; PHA; TYA; PHA          (saves A, X, Y on stack)
  5. TSX; LDA $0104,X; AND #$10       (checks B flag in stacked P)
  6. BEQ → normal IRQ handling         (keyboard, timers, cursor)
     BNE → JMP ($0316)                 (BRK dispatch — cse_brk_handler)

Stack at handler entry (SP = user_SP − 9):
  SP+1: Y    (KERNAL)
  SP+2: X    (KERNAL)
  SP+3: A    (KERNAL)
  SP+4: P    (CPU, B=1)
  SP+5: PClo (CPU, = breakpoint addr + 2)
  SP+6: PChi (CPU)
  — user's prior stack data above —
```

The early-entry path (kernal-out) replicates $FF48's prologue
(register pushes + B-flag test) and then converges with the
$FF48-arrived path at `cse_brk_handler`'s common entry.

**Key property:** The KERNAL's B-flag check happens *before* any IRQ
servicing.  BRK dispatch does not clobber KERNAL state: no keyboard
scan, no cursor blink, no timer service has occurred.  The user's
KERNAL interaction state is intact.

### NMI break mechanism

```
NMI fires during user code:
  1. CPU pushes PChi, PClo (exact addr), P → stack
  2. CPU loads PC from ($FFFA)
       kernal-in:  → $FE43 (KERNAL ROM)
                    KERNAL: SEI; JMP ($0318) → cse_nmi_handler
       kernal-out: → cse_nmi_handler early-entry label (RAM shadow)

Stack at handler entry (SP = user_SP − 3):
  SP+1: P    (CPU)
  SP+2: PClo (CPU, exact resume address — no +2 unlike BRK)
  SP+3: PChi (CPU)
  — A, X, Y are live (NOT on stack) —
```

`cse_nmi_handler` (main.s) reads `in_userland`.  When set, it
stashes live A/X/Y, then routes into the BRK-style entry path so
`dbg_nmi_capture` runs the same capture/longjmp tail.

When `in_userland` is clear (NMI in kernel mode), the handler
swallows: simply RTI, kernel code resumes.  No automatic screen
recovery — ESC/CLR is the user's binding for that.

**Key difference from BRK:**
- NMI stacks exact PC (not PC+2).  No adjustment needed on resume.
- KERNAL NMI entry does NOT push A/X/Y.  Handler saves from regs.
- The CPU NMI frame is 3 bytes (not 6 like BRK+KERNAL).

### Saved state at break

| Component | Size | Location | Notes |
|-----------|------|----------|-------|
| ZP $00–$7F | 128 B | `kernel_zp_buf` (BSS) | CSE's ZP image; restored on next return_to_userland. |
| ZP $00–$7F | 128 B | `userland_zp_buf` (BSS) | User's ZP snapshot.  `m` and `.` always read from and write to this buffer for addresses in the save range (`[ZP_SAVE_LO, ZP_SAVE_LO + ZP_SAVE_LEN)` — today $00–$7F); see [repl.md § User-ZP view](repl.md#user-zp-view). |
| Registers (A,X,Y,P) | 4 B | `reg_a/x/y/p` (BSS) | |
| Stack pointer | 1 B | `reg_sp` (BSS) | User's SP at break |
| PC | 2 B | `brk_pc` (BSS) | (= `reg_pc_lo/hi`) |

### Cold-init handoff

`brk_stub` is also the target of cold init's userland synthesis.
At boot:

1. Cold init does `setup_interrupts`, `dbg_init` (zeroes bp_table,
   sets `reg_a/x/y/p` to a clean default).
2. Splash drawn.
3. Cold-init userland handoff (in main.s): synth RTI frame with PC
   = `brk_stub`, sentinel below; RTI.
4. CPU lands at brk_stub, BRK fires.
5. `cse_brk_handler` classifies (PC-2 == brk_stub) → clean exit.
6. Handler longjmps to `main_loop_no_clear`.
7. REPL runs, splash visible.

This shares cold-init's first-prompt code path with normal
userland-recovery.  No separate "first prompt" routine.

### Single-step: `t` (trace into) — handler-resident state machine

`cmd_step` cannot loop in REPL code, because the BRK handler's
longjmp to `main_loop_top` discards the kernel call chain on every
break.  Instead, multi-step iteration runs **inside the BRK
handler**, with `cmd_step` providing only the seed.

State (BSS in debugger.s):

| Variable | Size | Purpose |
|----------|------|---------|
| `step_state` | 1 | 0 = not stepping; 1 = `t` (into); 2 = `o` (over) |
| `step_remaining` | 1 | Iterations left after current step |

Plus the existing `step_bp` slots (2 × 4 B) for the temporary
breakpoint addresses.

**Seed (cmd_step in repl.s):**

```
1. Read opcode at brk_pc; compute next-PC(s) (see below).
2. Place temp BRK(s) in step_bp slots; arm.
3. step_state := 1 or 2; step_remaining := N - 1.
4. jsr return_to_userland → RTI to user → user runs one instruction →
   BRK fires at next-PC.
   (return_to_userland does not return to here; control resumes via
   the BRK handler.)
```

**Chain (cse_brk_handler tail in main.s, after dbg_brk_capture):**

```
if dbg_bp_hit ∈ step_bp slots and step_remaining > 0
   and dbg_reason != DBG_NMI:
        ; chain another step
        step_remaining -= 1
        compute next-PC(s) from current brk_pc (re-using the
          same dispatch logic as cmd_step's seed)
        place new step BRK(s)
        ; tail call return_to_userland (it pushes RTI frame and RTIs)
        jmp return_to_userland
else:
        ; done — show result and longjmp to REPL
        unpatch_all
        restore CSE ZP from kernel_zp_buf
        ldx kernel_init_sp; txs
        jmp main_loop_top      ; show_break_result runs from REPL
```

**Next-PC determination (shared by seed and chain):**

```
Linear insn:   next = PC + length (via dasm_insn / oplen_tbl)
Branch (Bxx):  next₁ = PC + 2 + signed_offset (taken)
               next₂ = PC + 2 (not taken)
JMP abs:       next = operand
JMP (ind):     next = peek16(operand)
JSR abs:       next = operand                    ← `t`: step INTO
               EXCEPT if operand >= $E000:
               next = PC + 3 (step OVER — KERNAL ROM is unpatchable)
RTS/RTI:       stop (break before executing — flag in step_state)
BRK:           stop (don't step into vector)
```

For `o` (step-over), JSR's next-PC is always `PC + 3` (the
instruction after the JSR); the subroutine runs to completion at
full speed.  For conditional branches, `o` places only the
fall-through step BRK.

**SP discipline during chaining:**

Each iteration's stack consumption is bounded by the BRK handler's
own depth + return_to_userland's pushes, NOT by accumulation across
iterations.  The handler's `unpatch_all`-on-exit branch happens
only at chain termination; during chaining, the handler tail-jumps
to `return_to_userland` while still inside its own first-call frame.

This means stepping `t 100` consumes the same kernel stack budget
as `t 1` — no SP creep.

**Branch handling:** conditional branches (BCC, BEQ, BNE, etc.)
have two possible next addresses.  Both get a step BRK — the
taken target (`PC + 2 + signed_offset`) and the not-taken target
(`PC + 2`).  Whichever path the CPU takes, it hits a BRK.
`patch_all` saves both original bytes; `unpatch_all` restores both.

**RTS/RTI guard:** the step loop stops BEFORE executing RTS or RTI.
The instruction is displayed but not run.  This prevents following
a garbage return address when no JSR context exists.

### Single-step: `o` (trace over / step over)

Identical to `t` except for JSR and conditional branches:

**JSR:**
- `t` (trace into): step BRK at subroutine entry (`operand`) —
  follows the call, next step is the first instruction of the sub.
- `o` (trace over): step BRK at `PC + 3` — the instruction after
  the JSR.  The subroutine runs to completion at full speed.

**Conditional branches (BCC, BCS, BEQ, BNE, BPL, BMI, BVC, BVS):**
- `t` (trace into): step BRKs at BOTH the taken target and the
  fall-through.  Whichever path the CPU takes, the next step
  fires.
- `o` (trace over): step BRK at the fall-through ONLY.  If the
  branch is taken, the code runs at full speed until it naturally
  reaches the fall-through address (e.g., a loop runs to
  completion).

**Caveat:** `o` on a branch assumes the fall-through will
eventually be reached.  If the loop body contains a JMP or JSR
that exits sideways without passing through the fall-through
address, execution escapes and only NMI (RUN/STOP+RESTORE) can
break out — same as `o` on a JSR to a routine that never returns.

### KERNAL ROM JSR fallback

`t` (trace into) on a `JSR $XXXX` where `$XXXX >= $E000` cannot
work as written.  CSE patches a BRK at the target so the step
fires when execution reaches it, but writes to ROM addresses pass
through to the underlying RAM while the CPU still fetches the
original ROM byte — the BRK is never seen, the user code runs
into the KERNAL routine, and on return there is no step BRK to
catch it.  Symptom: stepping into `JSR $FFD2` (CHROUT) "hangs",
typically with screen output corruption from the runaway execution.

`cmd_step` detects this and silently falls back to step-over for
KERNAL targets.  The user steps PAST the JSR instead of into it.

`$A000–$BFFF` is **NOT** a fallback case: CSE unmaps BASIC ROM at
startup (clearing `$01` bit 0), so that range is RAM workspace and
JSR into the user's own code there steps in normally.

### User code output and the prompt row

`return_to_userland` does NOT save/restore `CUR_ROW`/`CUR_COL` across
user code execution.  Instead, the CALLER is responsible for moving
the cursor to a fresh row before invoking it:

- **`cmd_jmp` (j/g):** does `newline` + `io_clear_eol` once before
  `return_to_userland`.  User CHROUT output then writes to the row below
  the typed command, not on top of it.  When the user code returns,
  the cursor is wherever the user code left it; `nl_clear` advances
  one more row, and `show_prompt` writes the new prompt there.
- **`cmd_step` (t/o):** does `newline` + `io_clear_eol` once BEFORE
  the step loop, not per iteration.  Multi-step commands like `t10`
  therefore add only one fresh row of vertical space, not ten.

This integrates with the kernal-as-terminal affordance — see
[userland_contract.md § 6](../userland_contract.md#6-kernal-as-terminal-affordance).

### User BRK detection

If a BRK fires at an address that is NOT one of our breakpoint
slots, NOT a step breakpoint, and NOT `brk_stub`, it's a BRK in
the user's own code.  The debugger reports it as a user BRK (not
a breakpoint hit) and sets `brk_pc` to the BRK instruction's
address.  The user can inspect state and `c` to continue past it
(PC advances by 2, as the 6502 skips the BRK signature byte).

## Commands

### `b` — Breakpoints

```
b               list all breakpoints
b ADDR          set breakpoint at ADDR (next free slot)
b -N            delete breakpoint in slot N (1–8)
b *             delete all breakpoints
```

List output:
```
; bp 1: $1000
; bp 2: $2050
; bp 3: ----
  ...
```

### `c` — Continue

```
c               continue execution from brk_pc
```

If the break was caused by a user breakpoint, `c` **deletes that
breakpoint** before continuing.  The user must re-set it with `b`
if they want to break there again.  This eliminates the re-entry
problem (breakpoint at current PC would immediately re-trigger).

If the break was caused by NMI or a user BRK instruction (not one
of our breakpoints), `c` simply continues without deleting anything.

Error if no active break context.

### `t` — Trace (step-into)

```
t               step 1 instruction
t N             step N instructions (N in hex)
```

`t N` with N > 1 is an internal chain via the handler-resident
state machine.  Each iteration computes the next-PC, arms a
temporary step BRK, and enters user code for one instruction.

Bare `t` is single-step (count = 1).  `t N` overrides for this
invocation only.  `block_size` is NOT consulted by trace — it is a
memory-block setting (m/l/s commands) and unrelated to stepping
cadence.

JSR: steps into the subroutine.

The loop exits early if:
- A BRK opcode is encountered (user BRK, not a debugger breakpoint)
- An NMI fires or a regular breakpoint is hit mid-sequence
- RTS or RTI is reached (stops before executing — prevents
  following a garbage return address)

#### Step output: the edit workflow

`t` / `o` produce a running **audit trail** of executed
instructions culminating in a break panel for the current state.
Pressing RETURN repeatedly advances one instruction per press,
leaving behind the history of what ran.

The panel abstracts to:

- **Info** — `"; TAG at $PC"`, tag selected from `dbg_reason`
  (debug / brk / nmi / rts).
- **Regs** — one-line `r pc:.. a:.. x:.. y:.. sp:.. p:..`.
- **Lookahead** — disassembly of the next-to-run instruction
  (STEP_OVER semantics: fall-through for conditional branches
  and `jsr`; target for `jmp`; the instruction itself for
  RTS/RTI/BRK, where "next" is undefined).

The step primitive (handler-resident chain, `step_next_pc`,
patch/unpatch arming) is untouched — this is pure UX layered on
top of it.  Screen mechanics (where each row sits, how the panel
shifts, cursor positioning) are an implementation detail and
live in the code; they're verified on real hardware/VICE rather
than pinned by contract.

Tag taxonomy:

| `dbg_reason` | Tag     | When                                      |
| :---         | :---    | :---                                      |
| `DBG_NONE`   | `debug` | Cold preview: first `t`/`o` with no session; "debug" signals we're merely showing current state, not the outcome of a step. |
| `DBG_BRK`    | `brk`   | Step landed on a non-return instruction, or user BP hit. |
| `DBG_NMI`    | `nmi`   | NMI fired in userland. |
| `DBG_RTS`    | `rts`   | Step landed at RTS/RTI, or clean exit via brk_stub. |

Multi-step (`t N` / `o N` with N > 1) is implemented as an
N-iteration loop of the single-step path.  Each iteration is a
full REPL round-trip.  Future optimisation (see
TODO "handler t loop short circuit") would fold the iteration
into the handler-resident chain; not done yet.

##### DBG_RTS: two sources, unified display

`DBG_RTS` is set in two sites corresponding to the two ways to
end up "at a return op":

- **Handler (main.s)** — `brk_pc == brk_stub`, i.e. user code's
  top-level RTS popped our sentinel.  Handler sets `DBG_RTS` and
  resets `brk_pc := cur_addr` so the address shown is user-
  meaningful (not the sentinel's internal address).

- **cmd_step RTS-early-stop (repl.s)** — `step_next_pc` returns
  zeros (brk_pc's opcode is `$60`/`$40`/`$00`).  cmd_step sets
  `DBG_RTS` and jumps to `post_run_cleanup` without entering
  userland.  This fires on the SECOND `t`/`o` when the user is
  sitting on an RTS — the first landing (via a step-BRK trap)
  stays `DBG_BRK` because we BROKE at that instruction without
  executing it.

There is **no opcode peek in the handler**.  The opcode-based
classification lives in `step_next_pc` and in cmd_step's early-
stop path.  The handler's only RTS-related check is
`brk_pc == brk_stub`.

The "twice" pattern users see (`; brk` on first landing, `; rts`
on the second try to step past) is intentional, not a workaround:
the first is "we trapped here", the second is "we can't step
past".

**Session semantics in RTS state**: `DBG_RTS` is alive-but-
terminal.  `c` (continue) and `t` (step) refuse to proceed — the
`cmp #DBG_BRK / bcs` gate fails.  User must `j` / `g` to start a
fresh run.  For landed-at-RTS, we can't step past an RTS without
peeking user's stack; for clean-exit, the session is already
over — resuming makes no sense.

##### Session-state contracts

- `dbg_reason` — see § `dbg_reason` enum above.  Life-cycle:
  - **Cold**: `DBG_NONE`.  Cold preview sets `DBG_BRK`.
  - **Handler**: sets `DBG_BRK` for normal traps; promotes to
    `DBG_RTS` when at RTS/RTI opcode or clean-exit brk_stub
    path; sets `DBG_NMI` for NMI.
  - **RTS-early-stop in cmd_step**: sets `DBG_RTS` (same as a
    handler-classified RTS landing — unified display behavior).
  - **end-debug** (`R` command): clears to `DBG_NONE`.

- `_rtu_need_sentinel` — 1 = the next userland transition (via
  `restore_userland_state`) must push a fresh brk_stub sentinel
  onto user's stack.  Set by `return_to_userland` (always, for
  `j`/`g`/cold-init); set by cold preview (so the first real
  userland transition after preview pushes a sentinel); **not
  reset by `restore_userland_state`** (lets cold-preview's flag
  survive until the gate consumes it).  `_rtu_body` clears the
  flag after pushing.

### `o` — Trace over (step-over)

```
o               step 1 instruction (over subroutines)
o N             step N instructions (over subroutines)
```

Same semantics as `t` (loop of N × `o 1`, bare `o` is single-step).
JSR: the subroutine runs to completion, temporary breakpoint placed
at PC+3.

### `j` — Jump (start execution)

```
j [ADDR]        start execution at ADDR (default: cur_addr)
```

Populates `reg_pc` from ADDR (or `cur_addr`) and calls
`return_to_userland`.  When breakpoints exist, they are patched
into user memory before transfer; `cse_brk_handler` unpatches
on return.

On break, displays:
```
; brk 3 at $1000                         ← breakpoint hit
; a:00 x:03 y:00 sp:f5 Nvdizc
1000:

; nmi break at $0823                     ← RUN/STOP+RESTORE
; a:ff x:00 y:03 sp:f7 NVdizc
0823:
```

### `r` — Registers (unchanged)

```
r               display registers
r a:XX x:XX y:XX s:XX NvBdizc    set registers
```

Register modifications via `r` between a break and `c`/`t`/`o`
are applied when execution resumes (next call to `return_to_userland`
reads the updated `reg_*` shadows).

## Workflow Examples

### Set breakpoint, run, inspect, continue

```
1000: b 1020
; bp 1: $1020
1000: j
; brk 1 at $1020
; a:42 x:00 y:03 sp:f3 nvdizc
1020: m 00fb 0100
  ...
1020: c
; brk 1 at $1020
1020: b *
; breakpoints cleared
1020: c
; (runs to RTS — clean exit via brk_stub)
; a:00 x:00 y:00 sp:f5 nvdizc
1000:
```

### Trace through code

```
1000: t 5
r a:00 x:ff y:00 sp:f3 Nvdizc
 1042  stx $d020
1044:
```

Output shows final state after 5 steps.

### Step over subroutine

```
1008: o
r a:00 x:00 y:00 sp:f5 nvdizc
 100b  ldx #$00
100b:
```

### NMI break from runaway code

```
1000: j
  (user presses RUN/STOP + RESTORE)
; nmi break at $0823
; a:ff x:00 y:03 sp:f7 NVdizc
0823: r
; a:ff x:00 y:03 sp:f7 NVdizc
0823: c
  (continues running; or t to step from here)
```

### NMI in REPL (no user code running)

```
1000:
  (user presses RUN/STOP + RESTORE)
1000:
```

NMI is swallowed in kernel mode.  Use ESC/CLR for screen recovery
if needed.

## Cost Estimate

| Component | Bytes | Segment |
|-----------|-------|---------|
| return_to_userland | ~30 | CODE |
| brk_stub | 2 | CODE |
| Breakpoint patch/unpatch (combined loop) | ~50 | CODE |
| Breakpoint table management | ~100 | CODE |
| Step BRK arming logic | ~120 | CODE |
| dbg_brk_capture / dbg_nmi_capture | ~80 | CODE |
| REPL commands: b, c, t, o | ~400 | CODE |
| Breakpoint table (8 × 4) | 32 | BSS |
| Step-break temp slots (2 × 4) | 8 | BSS |
| Flags and state (reg_*, brk_pc, dbg_reason, dbg_bp_hit) | ~10 | BSS |
| **Total** | **~780 CODE, ~50 BSS** | |

Phase 18 net delta vs. two-image swap design:
- **−512 B KBSS** (no `user_stack_buf` / `cse_stack_buf`).
- **−1 B BSS** (`cse_sp` retired; `in_userland` lives in main.s).
- **~−100 B CODE** (no `@tramp` swap-in / swap-out memcpy).
- **~−1500 cycles** per user transition (memcpy gone, 9 ms each
  way → ~20 cycles each way).

## Caveats

- **Shared stack:** user code shares the CSE stack page; the
  contract is "user must leave 64 bytes of headroom for kernel
  re-entry on break."  See
  [userland_contract.md § 4](../userland_contract.md#4-stack-contract).
- **`return_to_userland` does not return.**  Control transfers to user
  code via RTI; the next time the kernel runs, it's via
  `cse_brk_handler`'s longjmp to `main_loop_top`.  Callers cannot
  rely on instructions placed after `return_to_userland` running on
  the user-bound code path.
- **`dbg_init` runs at cold init**, before the cold-init userland
  handoff.  `reg_a/x/y/p` must be initialised to clean defaults
  (e.g. all zero, P with bit 5 = 0) so the synthesized RTI frame
  is well-defined.
- Breakpoints only work in RAM.  Cannot set a breakpoint in ROM
  or I/O space (the BRK byte must be writable).
- `o` (step-over) on JSR places BRK at PC+3.  If the subroutine
  never returns (e.g., JMP to a loop), the BRK is never hit.  Use
  NMI (RUN/STOP+RESTORE) to break out.
- `t`/`o` stop BEFORE executing RTS or RTI.  The debugger does not
  follow return addresses — the user must `c` or `j` to continue.
- Self-modifying code may overwrite a patched BRK byte between the
  patch and the hit, causing the breakpoint to be silently lost.
- $0316/$0318 (BRK/NMI vectors) and $FFFE/$FFFA (RAM shadows) are
  permanently owned by CSE.  If user code overwrites any of them,
  the corresponding interrupt path is bypassed.  See
  [userland_contract.md § 5](../userland_contract.md#5-interrupt-vector-and-banking-hazards).
