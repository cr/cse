# debugger — Breakpoints, Tracing, and Execution Control

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/debugger.s`](../../src/debugger.s) | BRK handler, context switch, patch/unpatch |
| [`tests/test_debugger.py`](../../tests/test_debugger.py) | test contract |

## Interface

### Assembly (debugger.s)

### _dbg_init
**In:** none
**Out:** breakpoint table zeroed, flags cleared
**Clobbers:** A, X

Called at startup and on warm-start recovery.

### _dbg_enter
**In:** `_reg_a`, `_reg_x`, `_reg_y`, `_reg_p` — user register
state.  `_brk_pc` — target address.  `_step_bp` — armed step
breakpoints (if any).
**Out:** returns normally after BRK or NMI fires.  `_brk_pc`,
`_reg_*`, `_dbg_reason`, `_dbg_bp_hit` updated.
**Clobbers:** A, X, Y, ptr1

Saves CSE ZP, patches breakpoints, then `jsr @tramp` to enter
user code.  `@tramp` captures `sp_baseline`
(SP just after the jsr push), sets `dbg_running`, restores user
A/X/Y/P, and `jmp (brk_pc)`.  User code shares the CSE 6502 stack.
When a BRK or NMI fires, the handler restores SP from `sp_baseline`
and RTS returns to dbg_enter — see below for why.  After @tramp
returns, dbg_enter unpatches breakpoints, restores CSE ZP,
and RTS.  The debugger does NOT install or restore BRK/NMI
vectors — CSE owns them permanently (see [main.md](main.md)).

### _dbg_brk_core
**In:** called from `cse_brk_handler` (main.s) when user BRK fires
**Out:** RTS to `_dbg_enter` via `sp_baseline`
**Clobbers:** A, X

Extracts user registers from the KERNAL stack frame (Y, X, A, P,
PChi, PClo at fixed offsets from SP).  Computes `_brk_pc` =
pushed PC − 2.  Calls `_dbg_bp_find` to identify which breakpoint
was hit.  Then restores `SP = sp_baseline` and RTS — this pops
the @tramp return address and lands at "after jsr @tramp" in
dbg_enter.

**Why `sp_baseline` and not strip+rts?** The earlier strip-and-rts
approach (`tsx; adc #6; txs; rts`, removing the 6-byte BRK+KERNAL
frame) only worked when user code did NOT push anything before BRK
fired.  Stepping into a JSR is a counterexample: the JSR pushes its
own 2-byte return address before the BRK at the JSR target fires.
The strip+rts then uncovered those 2 user-pushed bytes and rts'd
through them as the next PC, jumping to "instruction after JSR" in
user code instead of returning to dbg_enter — the "t1 hangs on
JSR" bug.

The fix: `@tramp` captures `tsx → sp_baseline` immediately after
`jsr @tramp` pushes its return address.  The handler ignores the
strip count entirely and just sets `SP = sp_baseline` before its
RTS.  This pops the @tramp return address regardless of how many
bytes user code pushed.  The user-pushed bytes are abandoned in
stack memory (they sit below the new SP and will be overwritten
by CSE's stack use during cleanup).

Caveat: the user's stack contents between the BRK and the next
dbg_enter call are NOT preserved, so a `c` (continue) from inside
a stepped-into subroutine cannot pop the original JSR return
address — the subroutine's RTS will pop the @tramp return instead,
ending the run early.  For interactive single-stepping, this is
acceptable.  Test contract: `test_debugger.py::TestDbgEnterStepIntoJSR`
pins the no-runaway behaviour.

### _dbg_bp_set
**In:** A/X = address (lo/hi)
**Out:** C=0 success (A = slot number), C=1 table full
**Clobbers:** A, X, Y

### _dbg_bp_del
**In:** A = slot number (0-based)
**Out:** C=0 success, C=1 invalid slot
**Clobbers:** A, X

### _dbg_bp_clear
**In:** none
**Out:** all breakpoint slots cleared
**Clobbers:** A, X

### _dbg_bp_count
**In:** none
**Out:** A = number of non-empty breakpoint slots (0–8)
**Clobbers:** A, X

### _dbg_bp_find
**In:** A = addr lo, X = addr hi
**Out:** C=0 found, A = slot number (0–7).  C=1 not found, A = $FF.
**Clobbers:** A, X, Y

Used by the BRK handler to identify which breakpoint slot was hit.

### REPL (repl.s command handlers)

- `cmd_brk(args)` — `b` command: set, list, or delete breakpoints
- `c` handling (inline in `exec_line`) — continue execution from break
- `cmd_step(args, is_next)` — `t`/`o` commands: `is_next=0` for step-into, `is_next=1` for step-over

**State:**
- `_bp_table` — 8 breakpoint slots (see § Breakpoint table)
- `_dbg_running` — $80 while user code is active, 0 in REPL
- `_dbg_reason` — why we returned (0=none, 1=BRK, 2=NMI)
- `_brk_pc` — PC where the break occurred / execution will resume
- `_dbg_bp_hit` — slot number of the breakpoint that was hit ($FF = none)
- `_step_bp` — temporary breakpoint(s) for single-step (2 slots)

**Depends on:** asm_line (register state, ZP save), dasm (instruction
length for step), main (BRK/NMI dispatch)

### Memory

**BSS (46 bytes):**

| Variable | Size | Purpose |
|----------|------|---------|
| `_bp_table` | 32 | 8 breakpoint slots x 4 bytes |
| `_step_bp` | 8 | 2 step breakpoint slots x 4 bytes |
| `_dbg_running` | 1 | User code active flag ($80 = running) |
| `_dbg_reason` | 1 | Break reason (0=none, 1=BRK, 2=NMI) |
| `_brk_pc` | 2 | PC at break / resume address |
| `_dbg_bp_hit` | 1 | Slot of breakpoint hit ($FF = none) |
| `_sp_baseline` | 1 | SP at @tramp entry — handler restores SP to this on BRK/NMI |

## Command Reassignment

The debugger needs `b`, `c`, `t`, `o`.  Displaced commands move
to uppercase or symbol keys:

| Key | Old function | New key | Rationale |
|-----|-------------|---------|-----------|
| `b` | block size | `B` (uppercase) | Infrequent settings command; uppercase is appropriate |
| `c` | color | `C` (uppercase) | Same reasoning |
| `s` | seek | `@` | `@` = "at address"; seek is infrequent |
| `w` | save/write | `s` | `s` for save (matches SMON/Action Replay tradition) |

After reassignment:

| Key | Function | Status |
|-----|----------|--------|
| `b` | breakpoints | new (was block size, now `B`) |
| `c` | continue execution | new (was color, now `C`) |
| `t` | trace (step-into) | new |
| `o` | trace over (step-over) | new |
| `s` | save | moved from `w` |
| `B` | block size | moved from `b` (uppercase) |
| `C` | color | moved from `c` (uppercase) |
| `@` | seek | moved from `s` |

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

### BRK mechanism (C64 hardware flow)

```
BRK executes at user address $AAAA:
  1. CPU pushes PChi, PClo ($AAAA+2), P (B=1, I=1) → stack
  2. CPU sets I=1 (masks IRQ)
  3. CPU loads PC from ($FFFE) → $FF48 (KERNAL ROM)

KERNAL at $FF48:
  4. PHA; TXA; PHA; TYA; PHA          (saves A, X, Y on stack)
  5. TSX; LDA $0104,X; AND #$10       (checks B flag in stacked P)
  6. BEQ → normal IRQ handling         (keyboard, timers, cursor)
     BNE → JMP ($0316)                 (BRK dispatch — our handler)

Stack at handler entry (SP = user_SP − 9):
  SP+1: Y    (KERNAL)
  SP+2: X    (KERNAL)
  SP+3: A    (KERNAL)
  SP+4: P    (CPU, B=1)
  SP+5: PClo (CPU, = breakpoint addr + 2)
  SP+6: PChi (CPU)
  — user's prior stack data above —
```

**Key property:** The KERNAL's B-flag check happens *before* any IRQ
servicing.  BRK dispatch does not clobber KERNAL state: no keyboard
scan, no cursor blink, no timer service has occurred.  The user's
KERNAL interaction state is intact.

### NMI break mechanism

```
NMI fires during user code:
  1. CPU pushes PChi, PClo (exact addr), P → stack
  2. CPU loads PC from ($FFFA)

If KERNAL is banked in: ($FFFA) → $FE43 (KERNAL ROM)
  3. KERNAL: SEI; JMP ($0318)
  4. ($0318) → _nmi_handler (CSE, in cse_io.s)

If KERNAL is banked out: ($FFFA) → $FF00 (RAM, our trampoline)
  3. Trampoline re-banks KERNAL, then JMP ($0318)
  4. ($0318) → _nmi_handler

Stack at handler entry (SP = user_SP − 3):
  SP+1: P    (CPU)
  SP+2: PClo (CPU, exact resume address — no +2 unlike BRK)
  SP+3: PChi (CPU)
  — A, X, Y are live (NOT on stack) —
```

The NMI dispatcher lives in main.s (`cse_nmi_handler`).  When
`dbg_running` bit 7 is set, it dispatches to `dbg_nmi_break` in
debugger.s.  Otherwise it sets `nmi_pending` and RTI.

```asm
; in main.s:
cse_nmi_handler:
        bit _dbg_running        ; bit 7 → N flag
        bmi @break_user         ; user code active → break
        ; Normal NMI (REPL/editor): set flag, RTI
        pha
        lda #1
        sta _nmi_pending
        pla
        rti

@break_user:
        ; Save A/X/Y (not on stack for NMI)
        sta _reg_a
        stx _reg_x
        sty _reg_y
        ; ... extract PC and P from stack ...
        ; ... restore SP = sp_baseline, RTS to dbg_enter ...
```

**Key difference from BRK:**
- NMI stacks exact PC (not PC+2).  No adjustment needed on resume.
- KERNAL NMI entry does NOT push A/X/Y.  Handler saves from regs.
- The CPU NMI frame is 3 bytes (not 6 like BRK+KERNAL), but the
  handler still uses the same `sp_baseline` trick to return — see
  `dbg_brk_core` for the rationale.

### Context switch

User code shares the CSE 6502 stack — no stack page swap, no
KERNAL banking.  The same approach as `jsr_addr` in asm_line.s.

**Saved state:**

| Component | Size | Location | Notes |
|-----------|------|----------|-------|
| ZP $02–$5A | 89 B | `_zp_save_buf` (BSS) | All CSE ZP: sp, ptr1–2, tmp1–2, assembler, editor, etc. |
| Registers (A,X,Y,P) | 5 B | `_reg_a..p` (BSS) | existing, from asm_line |
| PC | 2 B | `_brk_pc` (BSS) | |

**Enter user code** (`j` / `c` / `t` step):

```
1.  Save CSE ZP ($02–$5A) → _zp_save_buf
2.  patch_all: write $00 at all enabled bp + step slots
3.  Set _dbg_running = $80
4.  PHA _reg_p, load A/X/Y from _reg_*, PLP
5.  JSR @tramp → JMP (_brk_pc) → user code
    ... user code runs, BRK fires ...
    ... cse_brk_handler dispatches to dbg_brk_core ...
    ... handler restores SP, RTS back here ...
6.  unpatch_all: restore original bytes
7.  Restore CSE ZP from _zp_save_buf
8.  CLI + RTS
```

`dbg_enter` is a **normal function call** — it returns after the
BRK/NMI handler restores SP to `sp_baseline` and RTS pops the
@tramp return address.

**BRK handler** (`dbg_brk_core`, called from `cse_brk_handler`):

```
1.  Snapshot user ZP → user_zp_buf
2.  Extract Y, X, A, P, PClo, PChi from stack (fixed offsets)
3.  _brk_pc = PChi:PClo − 2
4.  _reg_sp = SP + 6 (user's pre-BRK SP)
5.  _dbg_bp_find(_brk_pc) → _dbg_bp_hit
6.  _dbg_running = 0
7.  SP = sp_baseline; RTS → dbg_enter step 6
```

**NMI handler** (`dbg_nmi_break`, called from `cse_nmi_handler`):

Same pattern but saves A/X/Y from live regs (NMI doesn't push them)
and computes `_reg_sp = SP + 3` (CPU frame only, no KERNAL regs).

**Trade-off:** user code shares the CSE stack.  Deep CSE call chains
+ deep user subroutines could overflow.  For single-step, user code
runs one instruction at a time — minimal stack usage.

### Single-step: `t` (trace into)

```
1. Read opcode at _brk_pc
2. Determine next-PC(s):
     Linear insn:   next = PC + length (via dasm_insn)
     Branch (Bxx):  next₁ = PC + 2 + signed_offset (taken)
                    next₂ = PC + 2 (not taken)
     JMP abs:       next = operand
     JMP (ind):     next = peek16(operand)
     JSR abs:       next = operand                    ← step INTO
                    EXCEPT if operand >= $E000:
                    next = PC + 3 (step OVER, KERNAL ROM is unpatchable)
     RTS/RTI:       stop (break before executing)
     BRK:           stop (don't step into vector)
3. Place temp BRK(s) at next-PC(s) in _step_bp slots
4. run_user: dbg_enter, restore VIC charset, io_sync.
   (run_user does NOT save/restore the cursor — see "User code
   output and the prompt row" below.  cmd_step does newline +
   clreol once before the loop so user CHROUT output starts on
   a fresh row, not on top of the typed command.)
5. If NMI or regular bp interrupted → show_break_result, stop
6. Increment loop counter; if < count, repeat from 1
7. Display register line + disassembly at final _brk_pc
```

**Branch handling:** conditional branches (BCC, BEQ, BNE, etc.)
have two possible next addresses.  Both get a step BRK — the
taken target (`PC + 2 + signed_offset`) and the not-taken target
(`PC + 2`).  Whichever path the CPU takes, it hits a BRK.
`patch_all` saves both original bytes; `unpatch_all` restores both.

**RTS/RTI guard:** the step loop stops BEFORE executing RTS or RTI.
The instruction is displayed but not run.  This prevents following
a garbage return address when no JSR context exists.

### Single-step: `o` (trace over / step over)

Identical to `t` except for JSR:

- `t` (trace into): step BRK at subroutine entry (`operand`) —
  follows the call, next step is the first instruction of the sub.
- `o` (trace over): step BRK at `PC + 3` — the instruction after
  the JSR.  The subroutine runs to completion at full speed.

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

(BASIC unmap was originally a long-standing latent bug — the
startup code did `and #$DF` which clears the cassette motor bit
instead of LORAM.  Until a user attempted to read the workspace at
$A000–$BFFF, nothing tripped it.  Fixed in main.s as part of the
KERNAL JSR fallback work.)

### User code output and the prompt row

`run_user` (in repl.s) is a thin wrapper around `dbg_enter` used by
`g`, `j`, `t`, and `o`.  It does NOT save/restore `CUR_ROW`/`CUR_COL`
across the user code execution.  Instead, the CALLER is responsible
for moving the cursor to a fresh row before the first `run_user`
call:

- **`cmd_jmp` (j/g):** does `newline` + `io_clear_eol` once before
  `run_user`.  User CHROUT output then writes to the row below the
  typed command, not on top of it.  When the user code returns,
  the cursor is wherever the user code left it; `nl_clear` advances
  one more row, and `show_prompt` writes the new prompt there.
- **`cmd_step` (t/o):** does `newline` + `io_clear_eol` once BEFORE
  the step loop, not per iteration.  Multi-step commands like `t10`
  therefore add only one fresh row of vertical space, not ten.

This was a bug fix.  Originally `run_user` saved `CUR_ROW`/`CUR_COL`
at entry and restored them at exit, which was meant to keep the
display "compact" across user code execution.  In practice it did
the opposite: at the moment user code started, the cursor was at
col 0 of the prompt row (the main loop sets `CUR_COL=0` after
`read_line`, before `exec_line`).  Any user `JSR $FFD2` (CHROUT)
written during the step then overwrote the typed command at cols
0..N of the prompt row.  Symptom from the wild: `g` over a program
that prints "hello world" via CHROUT corrupted the typed `6000:g`
to `..00:g` with the first two characters replaced by the last two
characters CHROUT happened to leave there before the next prompt
overwrote them.

Test program for this path: load `t-hello,s` from the test disk
(generated by `dev/gen_asm_tests.py`), edit `.org $6000` if needed,
`a` to assemble, `g` to run.  Expected output:

```
6000:g
hello world
6000:
```

— with no prompt corruption and no register dump (clean RTS).

### User BRK detection

If a BRK fires at an address that is NOT one of our breakpoint
slots and NOT a step breakpoint, it's a BRK in the user's own
code.  The debugger reports it as a user BRK (not a breakpoint hit)
and sets `_brk_pc` to the BRK instruction's address.  The user can
inspect state and `c` to continue past it (PC advances by 2, as
the 6502 skips the BRK signature byte).

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
c               continue execution from _brk_pc
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
t               step block_size instructions
t N             step N instructions (N in hex)
```

`t N` is a loop of N × `t 1`.  Each iteration computes the next-PC,
arms a temporary step BRK, and enters user code for one instruction.
On completion (or early exit), one register line and one disassembly
line are printed showing the final state:

```
> t 3
r a:00 x:03 y:00 sp:f5 nvdizc
 1005  sta $d021
1008:
```

Bare `t` uses `block_size` as the count (default $10 = 16 steps).
`t N` overrides for this invocation only — does not change
`block_size`.

JSR: steps into the subroutine.

The loop exits early if:
- A BRK opcode is encountered (user BRK, not a debugger breakpoint)
- An NMI fires or a regular breakpoint is hit mid-sequence
- RTS or RTI is reached (stops before executing — prevents
  following a garbage return address)

### `o` — Trace over (step-over)

```
o               step block_size instructions (over subroutines)
o N             step N instructions (over subroutines)
```

Same semantics as `t` (loop of N × `o 1`, bare `o` uses
`block_size`).  JSR: the subroutine runs to completion, temporary
breakpoint placed at PC+3.

### `j` — Jump (start execution)

Upgraded from current behavior.  When breakpoints exist, `j`
patches them and enters the debugger execution loop.  When no
breakpoints exist and no `t`/`o` is pending, `j` behaves as
before (JSR + capture regs on RTS).

```
j [ADDR]        start execution at ADDR (default: cur_addr)
```

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
are applied when execution resumes.

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
; (runs to RTS)
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
; run/stop+restore
1000:
```

Existing behavior — clear screen, fresh prompt.

## Memory Layout Under KERNAL (updated)

```
$E000–$E5FF  sym_table (1536 B, 256 slots)
$E600–$EEFF  sym_heap (2304 B)
$EF00–$EFFF  earmarked: user stack snapshot (256 B, unallocated)
$F000–$F0FF  free (256 B)
$F100–$F4F1  KDATA tables (1010 B)
$F4F2–$F8D9  repl_screen (1000 B)
$F8DA–$F958  cold-init ZP snapshot (127 B, main.s)
$F959–$FEFF  free (1446 B)
$FF00–$FF09  NMI trampoline (10 B)
$FFFA–$FFFB  NMI vector → $FF00
```

User code shares the CSE 6502 hardware stack at `$0100–$01FF`.
`main.s::startup` resets SP to `$FF` on entry (CSE never returns
to BASIC), so user code sees 239+ bytes of free stack after CSE's
8-byte call-chain frame at `jmp (brk_pc)`.  See
[`memory_design.md` § Stack budget](../memory_design.md#stack-budget)
for the full stack walkthrough.

The `$EF00–$EFFF` region is earmarked but not yet allocated — it
will hold a 256-byte user-stack snapshot when the `c`-from-
stepped-subroutine TODO is implemented.

## Cost Estimate

| Component | Bytes | Segment |
|-----------|-------|---------|
| BRK handler + NMI handler | ~80 | CODE |
| dbg_enter (ZP save, patch, tramp, unpatch, restore) | ~60 | CODE |
| Breakpoint patch/unpatch (combined loop) | ~50 | CODE |
| Breakpoint table management | ~100 | CODE |
| REPL commands: b, c, t, o | ~400 | CODE |
| Breakpoint table (8 × 4) | 32 | BSS |
| Step-break temp slots (2 × 4) | 8 | BSS |
| Flags and state | ~6 | BSS |
| **Total** | **~690 CODE, ~46 BSS** | |

## Caveats

- **Shared stack:** user code shares the CSE 6502 stack, but
  `main.s::startup` resets SP to `$FF` and CSE's deepest call
  chain at user-code entry is only **8 bytes** (four nested
  JSRs: `exec_line → cmd_* → run_user → dbg_enter → @tramp`),
  so user code has **≥ 239 bytes** free.  Deeply recursive user
  code can still overflow the page; the fix for `c`-from-stepped-
  subroutine stack loss is a 256 B user-stack snapshot at
  `$EF00` (see TODO).
- Breakpoints only work in RAM.  Cannot set a breakpoint in ROM
  or I/O space (the BRK byte must be writable).
- `o` (step-over) on JSR places BRK at PC+3.  If the subroutine
  never returns (e.g., JMP to a loop), the BRK is never hit.  Use
  NMI (RUN/STOP+RESTORE) to break out.
- `t`/`o` stop BEFORE executing RTS or RTI.  The debugger does not
  follow return addresses — the user must `c` or `j` to continue.
- Self-modifying code may overwrite a patched BRK byte between the
  patch and the hit, causing the breakpoint to be silently lost.
- $0316 (BRK vector) is permanently owned by CSE.  If user code
  overwrites $0316, the debugger's BRK dispatch is bypassed.
  User code must preserve KERNAL vectors per the user code
  contract (see [memory_design.md](../memory_design.md)).
