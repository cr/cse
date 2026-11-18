# main.s — Application Shell + Interrupt Dispatch

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/main.s`](../../src/main.s) | implementation (6502 assembly) |

**Test coverage** — Pattern A (out-of-tier) per
[testing.md § Principle 9](../testing.md).  No dedicated test file
for `main.s`; it is exercised at Tier I on the production PRG in
[`tests/integration/test_kernel_transition.py`](../../tests/integration/test_kernel_transition.py):
vectors (`TestSetupInterrupts`), cold init (`TestColdInitHandoff`,
`TestColdInitTerminalState`, `TestBootsCleanly`), the BRK/NMI
dispatch and its classification (`TestBreakpointHit`,
`TestNmiUserland`, `TestNmiKernelMode`, `TestBrkKernelFault`,
`TestStepChain`, `TestTagClassification`, `TestDecimalFlag`), the
warmstart bodies (`TestWarmstartBodySubs`, `TestWarmCont`,
`TestRecoverKeepsBreakpoints`, `TestRefreshKeepsSession`,
`TestRefreshInEditor`, `TestRestoreDuringAssembly`), the IRQ
early entry (`TestIrqKeepsBanking`), the REPL keys
(`TestReplInsKey`), `TestMainCodeReadOnly` and `TestExitToBasic`.
[`tests/integration/test_step_rom.py`](../../tests/integration/test_step_rom.py)
covers the step-into-KERNAL fallback.  Every C64Emu integration test
also boots the production PRG through the loader → `_main` →
`main_loop` path.  Unit-tier isolation is not productive: the
synthesised state needed to drive the dispatcher in isolation
(vector table, banking config, BRK frame, ZP flags) is essentially
the integration-tier setup minus the work that makes it observable.

## Interface

main.s hosts the entry and exit bodies of the platform driver layer
— vectors, cold start, exit, the IRQ early entry
([platform_layer.md](../platform_layer.md)).  The entries below state
the c64 body; an **On m65** paragraph states the m65 body of the same
entry.

### _main
**In:** jumped to by `loader.s` after relocation (BSS zero, KDATA in
place); SP = `$FF`.
**Out:** does not return — runs the cold-init sequence (§ Layer 1)
and `jmp main_loop_top`.
**Clobbers:** everything.

**On m65:** reached from the resident stub's cold entry under the CSE
map, after the loader's install ([loader.md](loader.md)); SP = `$FF`,
`B = CSE_BP`, interrupts off.  Same sequence, with the per-step
differences of § Layer 1.

### setup_interrupts
**In:** none
**Out:** $0316/$0317 → `cse_brk_handler`; $0318/$0319 and $FFFA/$FFFB
→ `cse_nmi_handler`; $FFFE/$FFFF → `cse_brk_handler_early`.
**Clobbers:** A

Called by `_main` (step 4, before any bank-out) and by
`hw_reinit_body`.  Direct stores; writes to $FFFA/$FFFE reach the RAM
under the KERNAL regardless of `$01`.

| Vector | Address | Patched to |
|--------|---------|------------|
| IBRK | $0316/$0317 | `cse_brk_handler` (KERNAL-in entry, after $FF48's push) |
| INMIV | $0318/$0319 | `cse_nmi_handler` (KERNAL-in entry, via $FE43) |
| NMI shadow | $FFFA/$FFFB | `cse_nmi_handler` (KERNAL-out entry) |
| IRQ/BRK shadow | $FFFE/$FFFF | `cse_brk_handler_early` (KERNAL-out entry) |

**On m65:** **In:** interrupts disabled (the caller's `sei`).
**Out:** the KERNAL's vector table read with `KCALL VECTOR` into the
data window, `IBRK` (offset 2) → `stub_brk`, `INMI` (offset 4) →
`stub_nmi`, the table written back with `KCALL VECTOR`; the stub's
target words `stub_brk_target` → `cse_brk_handler`, `stub_nmi_target`
→ `cse_nmi_handler`.  `IIRQ` untouched; no RAM shadows (the KERNAL is
mapped in every map).
**Clobbers:** A, X, Y, Z ([platform_layer.md § Vectors](../platform_layer.md#vectors)).

### cse_brk_handler
**In:** entered via $0316 (KERNAL in, after $FF48 pushed A/X/Y) or
from `cse_brk_handler_early` (same stack shape): SP+1..SP+6 = Y, X,
A, P, PCL, PCH.
**Out:** does not return.  Kernel fault → `cse_recover`; userland
break → `restore_userland_state` (step chain) or `handler_finalize`
(→ `main_loop_top` with SP = `reg_sp`).
**Clobbers:** everything; live ZP $00–$7F becomes the kernel's
again.

**On m65:** *stated with P1* ([platform_layer.md § Interrupt frame](../platform_layer.md#interrupt-frame), § Banking).

### cse_nmi_handler
**In:** entered via $0318 (KERNAL in, after $FE43) or $FFFA (KERNAL
out): SP+1..SP+3 = P, PCL, PCH; A/X/Y live.
**Out:** does not return.  Kernel mode → `cse_refresh`; userland →
`handler_finalize` with `dbg_reason = DBG_NMI`.
**Clobbers:** everything.

**On m65:** *stated with P1* ([platform_layer.md § Interrupt frame](../platform_layer.md#interrupt-frame), § Banking).

### cse_brk_handler_early
c64 only (`.ifdef PLATFORM_C64`; [platform_layer.md § IRQ early
entry](../platform_layer.md#irq-early-entry)).
**In:** the $FFFE RAM-shadow entry, taken when an IRQ or BRK arrives
with the KERNAL banked out: SP+1..SP+3 = P, PCL, PCH; A/X/Y live.
**Out:** B=1 (BRK) → `cse_brk_handler` with the $FF48 stack shape;
B=0 (IRQ) → the KERNAL IRQ body `$EA31` with `$01 = $36` and a second
RTI frame aimed at `bank_out_stub` (§ IRQ early-entry bank-out).
**Clobbers:** nothing the interrupted code can see — A/X/Y reach
`$EA31` / `cse_brk_handler` as they were; `_irq_saved_a`.

### bank_out_stub
c64 only, with `cse_brk_handler_early`.
**In:** reached only by the KERNAL IRQ body's closing RTI, with the
interrupted `$01` value on top of the stack and the original
interrupt frame below it.
**Out:** `$01` = the interrupted value; RTI to the interrupted code.
**Clobbers:** nothing visible (A preserved via `_irq_saved_a`).

### cse_recover
**In:** any state — reached by `jmp` from `cse_brk_handler` on a BRK
in kernel code (`in_userland = 0`).
**Out:** does not return.  SP = `$FF`, `kernel_init_sp = $FF`,
`hw_reinit_body`, `end_debug_body`, `refresh_body`, then
`main_loop_top`.  A second entry before the first finished
(`warm_guard`) jumps to the platform's cold-start fallback,
`PLAT_COLD_START` — the KERNAL cold start `$FCE2` on c64,
`hyppo_reset` on m65 ([platform_layer.md § Cold start and exit](../platform_layer.md#cold-start-and-exit)).
**Clobbers:** everything.

### cse_end_debug
**In:** a gate set `warm_cont` (or not) and jumped here — `repl.s`'s
`a` and `j`/`g` gates on "yes".
**Out:** does not return.  SP = `kernel_init_sp`, `end_debug_body`,
`main_loop_top`.
**Clobbers:** everything.

### cse_refresh
**In:** jumped to by `cse_nmi_handler` (NMI in kernel mode),
`main_loop` (CLR, i.e. SHIFT+CLR/HOME, or ESC in the REPL) and
`repl.s`'s `R` (after `end_debug_body`).
**Out:** does not return.  SP = `reg_sp` (the user's SP at the
break, `$FF` without a session), `refresh_body`, falls through into
`main_loop_top`.  A live debug session is kept.
**Clobbers:** everything.

### hw_reinit_body
**In:** none
**Out:** `$01 = $36`; vectors re-installed (`setup_interrupts`);
`dbg_init` (step state, `reg_*`, `dbg_reason`; not the breakpoint
table); `reset_globals` (`state = ST_REPL`, `cur_addr = $0800`,
`block_size = $10`, `cur_device = 8`, `run_user_pending = 0`);
`io_init`, `theme_init`, `restore_colors`, `set_charset`.
**Clobbers:** A, X, Y (and what its callees clobber).

Caller: `cse_recover`.

**On m65:** *stated with P1* ([platform_layer.md § Interrupt frame](../platform_layer.md#interrupt-frame), § Banking).

### end_debug_body
**In:** none
**Out:** the debug session is gone: `unpatch_all` (every patched
breakpoint's byte restored); `dbg_reason`, `run_user_pending`,
`in_userland`, `stop_cooldown`, `last_cmd`, `cold_preview_done` = 0;
`reg_sp = $FF`; `dbg_bp_hit = $FF`; then `repl.s::step_cleanup`
(`step_state` / `step_remaining` = 0, step slots zeroed, a breakpoint
a step disabled enabled again).  Editor state and the breakpoint
table are kept.
**Clobbers:** A, X, Y, `rp_ptr`.

Callers: `cse_recover`, `cse_end_debug`, `repl.s`'s `R`.

### refresh_body
**In:** none
**Out:** `state = ST_REPL`; `$01 = $36` and `kernal_out = 0` (an NMI
can land inside a bank-out window, e.g. RUN/STOP+RESTORE during `a`,
which abandons the assembly); `reset_screen`; cursor at row 24,
column 0, that row cleared.
**Clobbers:** A, X, Y.

Callers: `cse_recover`, `cse_refresh`.

**On m65:** *stated with P1* ([platform_layer.md § Interrupt frame](../platform_layer.md#interrupt-frame), § Banking).

### main_loop_top
**In:** any SP the caller set (§ Longjmp SP convention).
**Out:** does not return — `cli`, then: `state = ST_STOP` →
`cse_exit_to_basic`; `warm_cont` set → consume it, replay `line_buf`
through `exec_line` and dispatch its `run_user_pending`; otherwise
`post_run_cleanup` if `dbg_reason`, `step_state` or
`run_user_pending` is nonzero (the break panel), `show_prompt`, and
into `main_loop`.
**Clobbers:** everything.

Reached from `_main`, `handler_finalize`, `cse_recover`,
`cse_end_debug` and (falling through) `cse_refresh`.

**State** — **BSS (6 bytes):** (main.s keeps no mutable byte in
CODE — [memory_design.md](../memory_design.md): no self-modifying
code)

| Variable | Exported | Purpose |
|---|---|---|
| `kernel_init_sp` | yes (no importer) | SP for `cse_end_debug`; `tsx` at the end of cold init (`$FF`), `$FF` again by `cse_recover`. |
| `run_user_pending` | yes (repl.s) | `MODE_NONE` (0) / `MODE_JUMP` (1) / `MODE_RESUME` (2): set by `j`/`g`/`c`/`t`/`o`, dispatched by `main_loop` after `exec_line` returns. |
| `stop_cooldown` | yes (repl.s) | RUN/STOP edge filter (§ Keyboard). |
| `warm_guard` | no | `cse_recover` re-entry guard. |
| `_irq_saved_a` | no | A while `cse_brk_handler_early` / `bank_out_stub` work. |
| `main_key` | no | the key `main_loop` is dispatching. |

`COLD_ZP` (`$F8DA`, 127 B under the KERNAL) holds the `$01–$7F`
snapshot taken at cold init for `cse_exit_to_basic`.

The cross-module flags main.s reads and writes (`state`,
`in_userland`, `warm_cont`, `kernal_out`, `dbg_reason`, `cur_device`)
live in `zp.s`; their meaning and writers are
[zp.md § Cross-module flags](zp.md#cross-module-flags).
The `dbg_reason` values come from `src/dbg_reason.inc`
([debugger.md § `dbg_reason` enum](debugger.md#dbg_reason-enum)).

**Depends on:** repl, editor, gap_buffer, debugger, breakpoints,
asm_line (`reg_p`, `reg_sp`), screen, cse_io, symtab, log, mem,
strings, zp

## Design

### Four-layer architecture

#### Layer 1: `_main` (cold init, one-time setup)

Runs once after `loader.s` jumps to `_main`.  Sequence is
ordered by dependency: each step's prerequisites are satisfied
by earlier steps, with no hidden cross-subsystem reach-ins.

1. **Keyboard / charset-switch setup.**  `KEY_REPEAT` |= $80;
   `$0291` = $80 (disable C= + SHIFT charset toggle).
2. **Save $01-$7F to `COLD_ZP`** (RAM under the KERNAL) so
   `cse_exit_to_basic` can restore BASIC's ZP and CPU port.
3. **Unmap BASIC ROM** (`$01 &= ~1` → $36).  CSE owns $A000-$BFFF
   from this point.
4. **`setup_interrupts`** — patch all four vectors.  Must happen
   before any bank-out so the KERNAL-out entries are reachable.
5. **`bp_init` + `dbg_init`** — zero the breakpoint table (cold
   init only: `hw_reinit_body` runs `dbg_init` alone, so breakpoints
   survive `cse_recover`), zero the step state and `reg_*`, seed the
   CPU-port bytes of both ZP save buffers
   ([debugger.md § dbg_init](debugger.md#dbg_init)).
6. **`sym_clear`** — empty the symbol table.  Strictly precedes
   step 8, the first `sym_define` caller (§ Caveats).
7. **`ed_ensure_init`** — first-time gap-buffer init, which sets
   `buf_base` ([gap_buffer.md](gap_buffer.md)).  A leaf: no symbol
   table contact.
8. **`define_ws_syms`** — register `workstart` and `workend`
   (`buf_base - 1`, so after step 7).
9. **CPU-mode default** — `asm_cpu = DEFAULT_CPU`.
10. **Free-ZP fill** — `$FF` from `cse_zp_end` through `$7F`.
11. **Workspace fill** — `$00` from `$0800` up to the page of
    `cse_start` (this also wipes the BASIC stub and the loader).
12. **I/O + screen** — `io_init`, `theme_init`, `reset_screen`,
    `set_charset`.
13. **Global state** — `reset_globals` (as in `hw_reinit_body`).
14. **Splash** — version line, `cmd_info` in splash mode (its rows:
    [repl.md § Splash screen](repl.md#splash-screen)), manual line,
    cursor to the prompt row.
15. **Capture `kernel_init_sp`** — `tsx; stx kernel_init_sp`.
16. **`jmp main_loop_top`** — enter the REPL.  The screen is not
    cleared again, so the splash stays; the prompt is drawn by
    `main_loop_top`'s `show_prompt`.

**On m65** the steps differ as follows; the others run as they are.

| Step | m65 |
|---|---|
| 1 | the charset and key-repeat settings through the KERNAL (`SYSFLAGS`) — *stated with P2* |
| 2 | absent: quitting is a Hypervisor reset, so BASIC's ZP is never restored and `COLD_ZP` does not exist |
| 3 | absent: no BASIC ROM to unmap — the CSE map is in place since `stub_cold` |
| 4 | `setup_interrupts`' m65 body (Interface above) |
| 5 | `dbg_init` without the CPU-port seeds: there are no ZP save buffers ([mem.md § ZP swap on m65](mem.md#zp-swap-on-m65)) |
| 10 | the free part of CSE's base page (from `cse_zp_end`) is filled; base page 0, the user's, is not touched |
| 11 | `$00` over the program region (`PROG_LO`–`PROG_HI`) by one DMA fill job (this wipes the PRG image and the loader, as on the C64) |
| 12, 14 | the screen and the `i` rows of the m65 bodies — *stated with P2* |

The order is load-bearing.  `_main` must reach `main_loop_top`
without `cse_brk_handler` or `cse_recover` ever being entered —
see [testing.md § Principles (Cold-init terminal-state
assertion)](../testing.md#principles).  No user code runs during cold
init: the first transition to userland is the user's first
`j`/`g`/`c`/`t`/`o`.

#### Layer 2: `setup_interrupts`

See Interface above.  The four vectors stay pointed at CSE for the
program's lifetime; only `cse_exit_to_basic` undoes the page-3 pair
(KERNAL RESTOR).

#### Layer 3: Reason-named warmstart entry points

Three entry points, each named after **why** control arrived (the
triggering event), not what it does:

| Entry point | Reason | Reached from |
|-------------|--------|--------------|
| `cse_recover` | CSE internal fault (BRK in kernel code) | `cse_brk_handler` with `in_userland = 0` |
| `cse_end_debug` | the user chose to end the debug session | `a`, `j`/`g` gates (`warm_cont = 1`, replay) |
| `cse_refresh` | the user asked for the view back | NMI in kernel mode; CLR / ESC in the REPL; `R` |

They compose the three body subroutines (Interface above):

```
cse_recover:     ldx #$FF / txs / stx kernel_init_sp
                 jsr hw_reinit_body
                 jsr end_debug_body
                 jsr refresh_body
                 jmp main_loop_top

cse_end_debug:   ldx kernel_init_sp / txs
                 jsr end_debug_body
                 jmp main_loop_top

cse_refresh:     ldx reg_sp / txs
                 jsr refresh_body
                 ; falls through
main_loop_top:   ...
```

`cse_recover` and `cse_end_debug` end any debug session and reset SP
to `$FF`.  `cse_refresh` keeps the session, so it resets SP to
`reg_sp`: the user's stack above it (the `brk_stub` sentinel and
whatever the program pushed) stays intact under the kernel's own
calls, and `c`/`t`/`o` resume correctly after CLR, ESC or
RUN/STOP+RESTORE at the prompt.  With no session `reg_sp` is `$FF`.
On the next `main_loop_top` pass a live session's break panel is
shown again (`post_run_cleanup`).

`cse_recover` also resets the REPL globals (`reset_globals`:
`cur_addr`, `block_size`, `cur_device`) and the step state; the
breakpoint table survives, with `end_debug_body` unpatching any
breakpoint that was patched at the fault.  The invariants every
entry point keeps (editor state, breakpoint table) are
[memory_design.md § Warmstart entry points](../memory_design.md#warmstart-entry-points)'s.

#### Layer 4: `main_loop` (event loop)

`main_loop_top` (Interface above) is the iteration entry after any
non-local transfer; `main_loop` is the per-key loop.  RETURN runs
`read_line` + `exec_line` with `run_user_pending = 0` first; after
`exec_line` returns:

- `run_user_pending = MODE_JUMP` → `jmp return_to_userland` (fresh
  start: the `brk_stub` sentinel is pushed);
- `MODE_RESUME` → `jmp restore_userland_state`;
- otherwise `show_prompt` and the next key.

Commands never RTI from inside a `jsr` frame: they stage state, set
`run_user_pending` and return; the transfer happens at this top
level.  Control comes back from userland only through the BRK/NMI
handlers.

**Continuation flag (`warm_cont`).**  Set by a gate
([repl.md § Gating pattern](repl.md#gating-pattern)) before it jumps
to `cse_end_debug`; consumed at the next `main_loop_top` pass, which
replays `line_buf` through `exec_line` (`line_buf` survives every
warmstart body, so the replayed command has the arguments the user
typed) and dispatches the replayed command's `run_user_pending`
itself.  It must not fall back to `main_loop_top` with
`run_user_pending` set: that pass would read it as "just returned
from userland" and show a break panel for a run that never happened.

### Longjmp SP convention

`main_loop` never resets SP; each entry to `main_loop_top` sets it
once and the loop's own stack use is balanced:

| Entry | SP |
|---|---|
| `_main` | `$FF` (loader's reset; balanced `jsr`s) |
| `handler_finalize` (end of every userland break) | `reg_sp` — the user's SP at the break |
| `cse_refresh` | `reg_sp` (`$FF` without a session) |
| `cse_recover` | `$FF` |
| `cse_end_debug` | `kernel_init_sp` (`$FF`) |

The kernel runs on the user's stack page below `reg_sp`, so the
user's frames — the `brk_stub` sentinel among them — survive a break
and a later resume.  The stack contract itself (headroom, user
budget) is [memory_design.md § Stack contract](../memory_design.md#stack-contract)
and [userland_contract.md § 4](../userland_contract.md#4-stack-contract).

### BRK dispatch

`cse_brk_handler` starts with `cld`: user code may break with the
decimal flag set (NMOS interrupts do not clear D), and every
`adc`/`sbc` in the handler and the kernel after it (`reg_sp`,
`brk_pc − 2`, the REPL's arithmetic) must run in binary.  The user's
D stays in `reg_p` and is restored by the next resume.

Then:

1. `in_userland = 0` → kernel fault → `jmp cse_recover`.
2. `in_userland := 0`; `save_userland_state` (debugger.s: `reg_*`,
   `brk_pc`, `reg_sp`, ZP swap); `reg_p &= $DF`; `brk_pc -= 2`;
   `dbg_reason = DBG_BRK`, `dbg_bp_hit = $FF`.
3. `brk_pc == brk_stub` → the user's top-level RTS popped the
   sentinel: `brk_pc := cur_addr`, `dbg_reason = DBG_RTS`,
   `handler_finalize`.  This is the only site that sets `DBG_RTS`.
4. `dbg_bp_find(brk_pc)` hits → `dbg_bp_hit = slot`,
   `handler_finalize`.
5. Stepping (`step_state ≠ 0`), `step_remaining ≠ 0` and `brk_pc`
   equals step slot 8 or 9 → chain: `unpatch_all`, `step_next_pc`,
   `arm_step_bp`, `step_remaining -= 1` (16-bit),
   `jmp restore_userland_state`
   ([debugger.md § Single-step](debugger.md#single-step)).
6. Otherwise (last step landed, or an unplanned user BRK) →
   `handler_finalize`.

`handler_finalize`: `unpatch_all`, `hygiene_after_userland` (repl.s:
VIC, colours, SID gates, `$CC`, keyboard buffer, KERNAL screen state),
SP := `reg_sp`, `jmp main_loop_top`.  Hygiene runs before the `txs`
so its `jsr`s cannot overwrite the user's stack above `reg_sp`, and
it runs here (not in `post_run_cleanup`) so clean `j`/`g` exits get
it too.

The handler never peeks opcodes; the panel's tag follows from
`dbg_reason` alone ([debugger.md § Break panel](debugger.md#break-panel)).

### NMI dispatch

`cse_nmi_handler` also starts with `cld`, then tests `in_userland`
with `bit` / `bmi` — A holds the user's live value and must not be
loaded over before the decision, which is why `in_userland` uses the
`$80` / 0 convention (set to `$80` by `restore_userland_state`,
cleared by both handlers and `end_debug_body`).

- **Userland** (RUN/STOP+RESTORE while user code runs): push A, X, Y
  so the stack has the $FF48 BRK shape, `in_userland := 0`,
  `save_userland_state`, `reg_p &= $CF`, `brk_pc` unchanged (an NMI
  stacks the exact PC), `dbg_reason = DBG_NMI`, `dbg_bp_hit = $FF`,
  `handler_finalize`.
- **Kernel** (RUN/STOP+RESTORE at the prompt, in the editor, or
  during a command): `jmp cse_refresh` — the interrupted kernel work
  is abandoned, the REPL is redrawn, a debug session is kept.

No SEI is needed on either path: the 6502 sets I as part of the NMI
sequence.  Both entries (KERNAL-in via $FE43 and $0318, KERNAL-out
via $FFFA) arrive with the same stack shape, so NMI needs no early
entry stub.

### IRQ early-entry bank-out

When an IRQ fires while the KERNAL is banked out (user code with
`$01 = $35`/`$34`/`$30`, or CSE's own bank-out windows), the CPU
reads the $FFFE RAM shadow and enters `cse_brk_handler_early` with
P, PCL, PCH stacked and A/X/Y live.

```
cse_brk_handler_early:
        pha / txa / pha         ; user A, X (X must be saved before tsx)
        tsx
        lda $0103,x / and #$10  ; B flag of the stacked P
        beq @to_irq_path
        tya / pha               ; B=1: complete the $FF48 shape
        jmp cse_brk_handler
@to_irq_path:
        pla / tax / pla         ; back to [P, PCL, PCH], A/X restored
@irq_path:
        sta _irq_saved_a
        lda $01 / pha           ; the interrupted $01
        lda #>bank_out_stub / pha
        lda #<bank_out_stub / pha
        php                     ; second RTI frame → bank_out_stub
        lda _irq_saved_a / pha / txa / pha / tya / pha   ; $FF48 shape
        lda #$36 / sta $01      ; KERNAL in
        jmp $EA31               ; KERNAL IRQ body

bank_out_stub:                  ; the IRQ body's RTI lands here
        sta _irq_saved_a
        pla / sta $01           ; the interrupted $01, exactly
        lda _irq_saved_a
        rti                     ; original frame → interrupted code
```

Stack handed to `$EA31` (top first): Y, X, A, P', `bank_out_stub`
(lo, hi), the interrupted `$01`, then the original P, PCL, PCH.  The
KERNAL IRQ body restores Y/X/A and RTIs into `bank_out_stub`, which
puts back the exact `$01` the interrupted code had — `$35` (KERNAL
out, I/O in) keeps its I/O — and RTIs the original frame.

### Exit path

`cse_exit_to_basic` (reached when `state = ST_STOP`, set by `Q`):
`sei`; `$0291 = 0` (charset toggle allowed again); KERNAL RESTOR
(`$FF8A`: the $0314–$0333 vectors back to the KERNAL's — the
$FFFA/$FFFE RAM shadows keep CSE's addresses but are not seen while
the KERNAL is mapped); KERNAL out to read `COLD_ZP`; `$02–$7F`
restored from it, then `$01`; `cli`; `$0800 = 0` (the byte before
BASIC's program start, so the program link chain is clean); CINT
(`$FF81`); `jmp ($A002)` (BASIC warm start).

**On m65:** `cse_exit_to_basic` is `hyppo_reset`
([platform_layer.md § Constants](../platform_layer.md#constants)):
the Hypervisor reloads the ROM banks CSE took and the KERNAL boots to
BASIC 65's READY prompt.  Nothing is restored by hand — no vectors,
no ZP, no CPU port.  What a user may expect afterwards is
[userland_contract.md § 3](../userland_contract.md#3-memory-regions)'s.

## Keyboard

`main_loop` reads keys with `io_getc` and dispatches by `state`.

### Global keys (both modes)

| Key | Action |
|-----|--------|
| RUN/STOP | Toggle REPL ↔ editor (`enter_editor` / `leave_editor`).  Edge-filtered by `stop_cooldown`: a press sets it, and while it is set further STOPs are swallowed; the `@wait` poll clears it when the KERNAL's STOP shadow `$91` reports the key released.  `hygiene_after_userland` sets it after an NMI break, so the STOP still held from RUN/STOP+RESTORE does not toggle. |
| RUN/STOP+RESTORE | NMI — § NMI dispatch.  In userland: break into the debugger.  Otherwise `cse_refresh`, which always lands in the REPL (`state = ST_REPL`, the editor source kept), so the next keys are REPL keys, matching the screen. |

### REPL mode keys

| Key | Action |
|-----|--------|
| Printable characters | Written at the cursor (overwrite, `io_putc`).  Refused (audible blip) at col 39. |
| Cursor keys | Move within the screen, no wrap.  Refused (blip) at the screen edges. |
| RETURN | `read_line` the cursor row, `exec_line`, then the userland dispatch or `show_prompt` (§ Layer 4). |
| DEL | Backspace, shifting the rest of the row left.  Refused at col 0, or below col 6 on an `AAAA:cmd` row (`:` in col 4). |
| INS | Right-shift the row from the cursor, opening a space there (any column, 0 included); the character pushed into column 39 is dropped, column 39 stays blank.  Only the cursor row changes. |
| HOME | Cursor to col 0 of the current row. |
| CLR (SHIFT+CLR/HOME) / ESC | `cse_refresh`: redraw the REPL screen, prompt on the bottom row; a debug session is kept. |

### Editor mode keys

Handled by `ed_handle_key`.  See [editor.md](editor.md).

## Caveats

- **Cold-init sequence prerequisite.**  `sym_clear` (step 6) must run
  before any code that can call `sym_define` — in `_main` that is
  `define_ws_syms` (step 8).  Before `sym_clear`, `_st_heap` is
  BSS-zero and a `sym_define` would copy its name through `$0000`,
  over the CPU port and CSE's ZP.  The same constraint applies to any
  caller added to cold init.
- `cse_brk_handler`'s longjmp to `main_loop_top` discards the
  kernel's frames below `reg_sp` that led to the userland transfer.
  By design: `return_to_userland` / `restore_userland_state` are the
  last statement of `main_loop`'s control flow — there is nothing to
  return to.
- An NMI in kernel mode abandons whatever CSE was doing (an assembly,
  a disk command, a scroll); `refresh_body` banks the KERNAL in and
  clears `kernal_out` so the redraw works from any bank-out window.
- None of the warmstart entry points call `leave_editor` or touch the
  editor's buffer — the source survives every warmstart.
- `kernel_init_sp` is exported but imported by no module; only
  `cse_end_debug` reads it.
- `main.s` imports `log_line` without using it.
