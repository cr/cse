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
**Out:** breakpoint table zeroed, BRK vector saved, flags cleared
**Clobbers:** A, X

Called once at startup.  Saves the default $0316 value.

### _dbg_enter
**In:** `_reg_a`, `_reg_x`, `_reg_y`, `_reg_sp`, `_reg_p` — user
register state.  `_brk_pc` — target address.
**Out:** does not return normally.  Returns to REPL via longjmp
when a BRK or NMI break occurs.
**Clobbers:** everything (context switch)

Saves CSE context (ZP, stack page, SP), patches breakpoints,
loads user registers, and RTIs to the target address.  Returns
to the REPL when a BRK fires, an NMI break occurs, or user
code hits RTS (if no breakpoints are set).

### _dbg_brk_handler
**In:** called from KERNAL via ($0316) on BRK
**Out:** returns to REPL with `_dbg_reason = DBG_BRK`
**Clobbers:** everything (context switch)

Extracts user registers from the KERNAL stack frame, unpatches
breakpoints, restores CSE context, and longjmps to the REPL.

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

### C (repl.c command handlers)

- `cmd_brk(args)` — `x` command: set, list, or delete breakpoints
- `cmd_continue()` — `c` command: continue execution from break
- `cmd_trace(args)` — `t` command: step-into N instructions
- `cmd_next(args)` — `n` command: step-over N instructions

**State:**
- `_bp_table` — 8 breakpoint slots (see § Breakpoint table)
- `_dbg_running` — $80 while user code is active, 0 in REPL
- `_dbg_reason` — why we returned (BRK, NMI, RTS, step)
- `_brk_pc` — PC where the break occurred / execution will resume
- `_dbg_bp_hit` — slot number of the breakpoint that was hit ($FF = none)
- `_step_count` — remaining step count for `t`/`n`
- `_step_bp` — temporary breakpoint(s) for single-step (2 slots)

**Depends on:** asm_bridge (register state, ZP save), dasm (instruction
length for step), cse_io (NMI handler upgrade), symtab (KERNAL banking)

## Command Reassignment

The debugger commands `c`, `t` conflict with existing REPL
commands.  Reassignment:

| Key | Old function | New key | Rationale |
|-----|-------------|---------|-----------|
| `c` | color | `C` (uppercase) | Color is an infrequent settings command; uppercase is appropriate |
| `t` | transfer (planned) | `>` | `>` suggests "move to"; matches common shell/editor metaphor |

After reassignment:

| Key | Function | Status |
|-----|----------|--------|
| `x` | breakpoints | new |
| `c` | continue execution | new (was color, now `C`) |
| `t` | trace (step-into) | new (was transfer, now `>`) |
| `n` | next (step-over) | new |
| `b` | block size | unchanged |
| `C` | color | moved from `c` |
| `T` | tab width | unchanged |
| `>` | transfer/copy | moved from `t` (planned) |

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

2 additional slots (same layout, 8 bytes) used by `t` and `n` for
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

The NMI handler is upgraded with a two-path check:

```asm
_nmi_handler:
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
        ; ... context switch back to REPL (same as BRK handler) ...
```

**Key difference from BRK:**
- NMI stacks exact PC (not PC+2).  No adjustment needed on resume.
- KERNAL NMI entry does NOT push A/X/Y.  Handler saves from regs.
- Stack frame is 3 bytes, not 6.

### Context switch

The debugger maintains two execution contexts — CSE (REPL) and
user code — with full isolation.

**Saved state per context:**

| Component | Size | Location | Notes |
|-----------|------|----------|-------|
| ZP $02–$5C | 91 B | `_zp_save_buf` (BSS) | existing, from asm_bridge |
| Stack page $0100–$01FF | 256 B | $E100 / $E200 (KERNAL RAM) | CSE snapshot / user snapshot |
| SP | 1 B | `_cse_saved_sp` / `_reg_sp` | |
| Registers (A,X,Y,P) | 4 B | `_reg_a..p` (BSS) | existing, from asm_bridge |
| PC | 2 B | `_brk_pc` (BSS) | |

**Enter user code** (`j` / `c` / `t` step):

```
1.  Save CSE ZP → _zp_save_buf
2.  Save CSE SP → _cse_saved_sp
3.  Bank out KERNAL:
      memcpy($0100 → $E100, 256)     ; CSE stack snapshot
      memcpy($E200 → $0100, 256)     ; restore user stack (skip for fresh j)
    Bank in KERNAL
4.  Save user's $0316 → _user_brk_vec
5.  Install _dbg_brk_handler at $0316
6.  Patch all enabled breakpoints (write $00)
7.  Set _dbg_running = $80
8.  Set SP = _reg_sp
9.  Build stack frame:
      For fresh j:  push _reg_p, push (_brk_pc − 1) hi/lo
      For c/t:      user stack already has BRK/NMI frame (adjust as needed)
10. Load A/X/Y from _reg_*
11. RTI → user code resumes
```

**Return to REPL** (BRK or NMI fires):

```
1.  Extract user regs → _reg_* (from stack for BRK, from regs for NMI)
2.  Compute break address → _brk_pc
3.  Compute user's pre-break SP → _reg_sp
4.  Set _dbg_running = 0
5.  Unpatch all breakpoints (restore original bytes)
6.  Restore user's $0316 from _user_brk_vec
7.  Bank out KERNAL:
      memcpy($0100 → $E200, 256)     ; user stack snapshot
      memcpy($E100 → $0100, 256)     ; restore CSE stack
    Bank in KERNAL
8.  Restore CSE ZP from _zp_save_buf
9.  Restore CSE SP from _cse_saved_sp
10. CLI                               ; re-enable interrupts
11. Return to REPL with status in _dbg_reason
```

**User's IRQ handlers continue firing** after step 10.  The CLI
re-enables interrupts, so any raster IRQ, music player, or
timer-driven code the user set up keeps running during the
debugger prompt.  The KERNAL's keyboard/cursor IRQ also resumes.

### KERNAL interaction preservation

The debugger does not touch:

| Resource | Why it's safe |
|----------|--------------|
| $0314 (IRQ vector) | User's IRQ chain untouched |
| $0316 (BRK vector) | Saved/restored around execution |
| CIA timers ($DC04–$DD0B) | Never modified |
| KERNAL I/O state ($0200–$03FF) | Not in CSE's ZP save range |
| KERNAL ZP ($80–$FF) | CSE saves $02–$5C only |
| Open files/channels | KERNAL file table untouched |
| Screen/color RAM | Debugger uses CSE's I/O (direct screen writes) |

User code that interacts with the KERNAL (OPEN, CLOSE, CHROUT,
CHRIN, LOAD, SAVE, etc.) works identically whether breakpoints
are set or not.  The BRK dispatch occurs before the KERNAL's
IRQ processing, so no KERNAL state is modified between the
user's last instruction and the debugger gaining control.

### Single-step: `t` (trace into)

```
1. Disassemble instruction at _brk_pc → length, type
2. Determine next-PC(s):
     Linear insn:   next = PC + length
     Branch (Bxx):  next₁ = PC + length (not taken)
                    next₂ = PC + 2 + signed_offset (taken)
     JMP abs:       next = operand
     JMP (ind):     next = peek16(operand)
     JSR abs:       next = operand                    ← step INTO
     RTS:           next = peek16(SP+1) + 1
     RTI:           next = peek16(SP+2)               (SP+1 = P)
     BRK:           next = peek16($0316) or peek16($FFFE)
3. Place temp BRK(s) at next-PC(s) in _step_bp slots
4. Execute via context switch (same path as c)
5. BRK fires at next instruction → clean up _step_bp
6. Decrement _step_count; if > 0, repeat from 1
7. Report to REPL
```

### Single-step: `n` (next / step over)

Identical to `t` except for JSR handling:

```
     JSR abs:       next = PC + 3                     ← step OVER
```

Places BRK at the instruction *after* the JSR.  The subroutine
runs to completion at full speed, then BRK fires on return.

### User BRK detection

If a BRK fires at an address that is NOT one of our breakpoint
slots and NOT a step breakpoint, it's a BRK in the user's own
code.  The debugger reports it as a user BRK (not a breakpoint hit)
and sets `_brk_pc` to the BRK instruction's address.  The user can
inspect state and `c` to continue past it (PC advances by 2, as
the 6502 skips the BRK signature byte).

## Commands

### `x` — Breakpoints

```
x               list all breakpoints
x ADDR          set breakpoint at ADDR (next free slot)
x -N            delete breakpoint in slot N (1–8)
x *             delete all breakpoints
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
breakpoint** before continuing.  The user must re-set it with `x`
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

Each step shows the disassembled instruction and register state:

```
> t 3
 1000  lda #$00         a:00 x:03 y:00 sp:f5 nvdizc
 1002  sta $d020        a:00 x:03 y:00 sp:f5 nvdizc
 1005  sta $d021        a:00 x:03 y:00 sp:f5 nvdizc
1008:
```

JSR: steps into the subroutine.

### `n` — Next (step-over)

```
n               step 1 instruction (over subroutines)
n N             step N instructions (over subroutines)
```

Same display as `t`.  JSR: the subroutine runs to completion,
breakpoint placed at the return address (PC+3).

### `j` — Jump (start execution)

Upgraded from current behavior.  When breakpoints exist, `j`
patches them and enters the debugger execution loop.  When no
breakpoints exist and no `t`/`n` is pending, `j` behaves as
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

Register modifications via `r` between a break and `c`/`t`/`n`
are applied when execution resumes.

## Workflow Examples

### Set breakpoint, run, inspect, continue

```
1000: x 1020
; bp 1: $1020
1000: j
; brk 1 at $1020
; a:42 x:00 y:03 sp:f3 nvdizc
1020: m 00fb 0100
  ...
1020: c
; brk 1 at $1020
1020: x *
; breakpoints cleared
1020: c
; (runs to RTS)
; a:00 x:00 y:00 sp:f5 nvdizc
1000:
```

### Trace through code

```
1000: t 5
 1000  lda #$00         a:00 x:03 y:00 sp:f5 nvdizc
 1002  sta $d020        a:00 x:03 y:00 sp:f5 nvdizc
 1005  sta $d021        a:00 x:03 y:00 sp:f5 nvdizc
 1008  jsr $1040        a:00 x:03 y:00 sp:f5 nvdizc
 1040  ldx #$ff         a:00 x:ff y:00 sp:f3 Nvdizc
1042:
```

### Step over subroutine

```
1008: n
 1008  jsr $1040        a:00 x:00 y:00 sp:f5 nvdizc
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
$E000–$E0FF  free (256 B)
$E100–$E1FF  CSE stack snapshot (256 B)
$E200–$E2FF  User stack snapshot (256 B)
$E300–$F817  free (5.4 KB)
$F818–$FBFF  repl_screen (1000 B)
$FC00–$FEFF  sym_table (768 B)
$FF00–$FF09  NMI trampoline (10 B)
$FFFA–$FFFB  NMI vector → $FF00
```

## Cost Estimate

| Component | Bytes | Segment |
|-----------|-------|---------|
| BRK handler + NMI upgrade | ~120 | CODE |
| Context switch (stack copy, ZP save) | ~80 | CODE |
| Breakpoint patch/unpatch | ~60 | CODE |
| Step: instruction length + target resolution | ~100 | CODE |
| REPL commands: b, c, t, n | ~400 | CODE |
| Breakpoint table (8 × 4) | 32 | BSS |
| Step-break temp slots (2 × 4) | 8 | BSS |
| Flags, saved vectors, state | ~12 | BSS |
| Stack snapshots (2 × 256) | 512 | KERNAL RAM |
| **Total** | **~760 CODE, ~52 BSS, 512 KERNAL** | |

## Caveats

- Breakpoints only work in RAM.  Cannot set a breakpoint in ROM
  or I/O space (the BRK byte must be writable).
- `n` (step-over) on JSR places BRK at PC+3.  If the subroutine
  never returns (e.g., JMP to a loop), the BRK is never hit.  Use
  NMI (RUN/STOP+RESTORE) to break out.
- Self-modifying code may overwrite a patched BRK byte between the
  patch and the hit, causing the breakpoint to be silently lost.
- If user code replaces the hardware IRQ vector at $FFFE in RAM
  (by banking out KERNAL) with a handler that doesn't check the
  B flag, BRK will be treated as an IRQ and the debugger will not
  gain control.  This is rare in practice.
- `t` stepping through an instruction that enables interrupts (CLI)
  will allow pending IRQs to fire as a side effect.  The IRQ handler
  runs to completion before the step-break triggers.  This is
  correct 6502 behavior.
- The 256-byte stack page copy costs ~1 ms per context switch.
  Imperceptible to the user but adds latency to each `t` step
  when stepping rapidly (e.g., `t 100`).
- User's $0316 (BRK vector) is saved/restored.  If user code sets
  $0316 between breakpoint patches, the user's handler will not fire
  until the debugger is inactive.
