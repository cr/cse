# main.s — Application Shell + Interrupt Dispatch

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/main.s`](../../src/main.s) | implementation (6502 assembly) |

## Interface

- `_main` — entry point (jumped to by `loader.s` after
  relocation, BSS zero, KDATA copy).  Contains four layers:
  `cse_cold_init`, `setup_interrupts`, the warmstart entry points
  (`cse_recover` / `cse_end_debug` / `cse_refresh`), and `main_loop`.
- `state` — exported BSS byte: 0=STOP, 1=REPL, 2=EDIT
- `in_userland` — exported BSS byte: 1 = user code is currently
  running, 0 = kernel.  Set by `return_to_userland` (debugger.s),
  cleared on BRK handler entry.  Read by `cse_nmi_handler` to
  pick its dispatch (swallow vs. break-into-debugger).

**Interrupt handlers (owned by main.s):**

### cse_brk_handler
**In:** invoked via $0316 (kernal-in path) or $FFFE early-entry
(kernal-out path).  CPU + KERNAL have pushed Y/X/A/P/PChi/PClo onto
the stack (6 bytes total).
**Out:** does not return to caller — longjmps SP to main_loop's
known value and `jmp main_loop_top`.
**Clobbers:** all registers, all of $00–$7F (after capture)

The unified BRK dispatcher.  Classifies the BRK source and routes:

- $FFFE early-entry path (kernal banked out at BRK time): bank
  kernal in, then fall through to standard path.  See § IRQ
  early-entry bank-out below for the IRQ subcase.
- B=0 (a real IRQ that fired while kernal was banked out):
  delegate to kernal IRQ via stack surgery so the kernal's natural
  RTI routes through a bank-out stub.  Returns via RTI to original
  code with kernal banked back out.
- B=1 (BRK):
  - PC-2 == `brk_stub` → user clean exit (`dbg_reason = 0`).
  - PC-2 matches an armed breakpoint slot → breakpoint hit
    (`dbg_reason = DBG_BRK`, `dbg_bp_hit = slot`).
  - PC-2 matches an armed step-BRK slot → step iteration; the
    handler-resident state machine (see [debugger.md § Single-step](debugger.md))
    decides chain-or-finish.
  - Otherwise → unplanned user BRK (`dbg_reason = DBG_BRK`,
    `dbg_bp_hit = $FF`).

After classification, the handler captures user state into the
`reg_*` shadows (debugger.s), clears `in_userland`, runs `vic_reset`
and SID voice-gate clear, calls `unpatch_all` and restores CSE ZP
from `kernel_zp_buf`, then performs the longjmp:

```
        ldx kernel_init_sp
        txs
        jmp main_loop_top
```

### cse_nmi_handler
**In:** invoked via $0318 (kernal-in path) or $FFFA early-entry
(kernal-out path).  CPU has pushed P/PChi/PClo (3 bytes); A/X/Y
are still live in the CPU registers.
**Out:** either swallows (RTI back to interrupted code) or routes
through the BRK-style entry path (does not return).
**Clobbers:** A on swallow path; everything on break path.

Dispatches on `in_userland`:

```
cse_nmi_handler:
        bit in_userland         ; bit 7 → N, bit 0 → Z (after BIT)
        bne @break_user         ; in_userland != 0 → break into debugger
        ; kernel mode: user wants the view back.  Discard the NMI
        ; frame and jump to the refresh entry point.
        jmp cse_refresh

@break_user:
        ; userland mode: stash live A/X/Y, fall into BRK path
        sta reg_a / stx reg_x / sty reg_y
        jmp cse_brk_handler_userland_entry
```

The two branches correspond to two distinct user intents:

- **NMI in userland** (user pressed RUN/STOP+RESTORE while their
  code was running) → break into the debugger.  Indistinguishable
  at the hardware level from a BRK breakpoint; the same capture
  logic runs.
- **NMI in kernel** (user pressed RUN/STOP+RESTORE at the REPL
  prompt) → `cse_refresh`.  The classic C64 affordance: "my view
  got messed up, give me a clean screen."  Debug context (if any)
  is preserved.

### setup_interrupts
**In:** none
**Out:** $0316/$0317, $0318/$0319, $FFFA/$FFFB, $FFFE/$FFFF all
patched to point at handler labels
**Clobbers:** A, X

Called once during cold init, **before any bank-out**.  Also
re-called by `cse_recover` for idempotent fault recovery.

| Vector | Address | Patched to |
|--------|---------|------------|
| IBRK | $0316/$0317 | `cse_brk_handler` (kernal-in entry) |
| INMIV | $0318/$0319 | `cse_nmi_handler` (kernal-in entry) |
| NMI shadow | $FFFA/$FFFB | `cse_nmi_handler` (direct — see note) |
| IRQ/BRK shadow | $FFFE/$FFFF | `cse_brk_handler_early` |

Direct stores; no kernal VECTOR call (step 1 of the design — see
`doc/design_cse_as_kernel.md` § 6).  A future step 2 may migrate
the $0316/$0318 patches to use `KERNAL_VECTOR` ($FF8D) for
cross-kernal compatibility (R3 universal C64/C128 binary).

**No NMI early-entry shim.**  BRK's early-entry does real work
(`bank_out_stub` insertion when $FFFE fires as IRQ with kernal
banked out — see `cse_brk_handler_early`).  NMI has no such need:
the 6502 hardware sets I=1 as part of the NMI vector sequence
(push PC, push P with B=0, **set I**, fetch $FFFA), so IRQs are
already masked when the handler runs.  Both entry paths (kernal-in
via KERNAL's $FE43 dispatch through $0318, kernal-out via direct
$FFFA fetch) land at the same `cse_nmi_handler` label with the
same stack shape.

### Memory

**ZP (6 bytes):** `rp_ptr` (2), `rp_ptr2` (2), `rp_tmp` (1),
`rp_tmp2` (1) — scratch pointers/bytes shared by repl.s,
debugger.s, asm_line.s.

**BSS (7 bytes):** `state` (1), `warm_guard` (1), `in_userland` (1),
`kernel_init_sp` (1), `run_user_pending` (1), `stop_cooldown` (1),
`warm_cont` (1).

`kernel_init_sp` is the SP value the warmstart entry points
longjmp to when returning control to the REPL.  Set once during
cold init, just before the cold-init userland handoff:
`tsx; stx kernel_init_sp`.  Read by `cse_brk_handler` tail
(`ldx kernel_init_sp; txs`) and by `cse_recover` for hard recovery.

`warm_cont` (0 = fresh prompt, 1 = replay `line_buf`) is the
continuation flag gates set before jumping to a warmstart entry
point.  `main_loop_top` consumes it on each iteration.  See
Layer 4 above.

`run_user_pending` is the command → main_loop handoff for userland
execution.  Commands (`j`, `g`, `c`, `t`, `o`) stage their state
and rts normally after setting this to `MODE_JUMP` (push sentinel →
fresh start) or `MODE_RESUME` (reuse existing sentinel).  The
main_loop dispatches via `jmp return_to_userland` / `jmp
restore_userland_state` at top level — never RTI from within a jsr
frame.  Cleared by main_loop before each `exec_line` call, and
again after `post_run_cleanup` consumes it.

`stop_cooldown` is main_loop's RUN/STOP edge-filter: set to 1 when
a STOP press is processed (so autorepeat doesn't re-toggle) or by
`hygiene_after_userland` on an NMI break (the STOP key was held to
cause the break; the stale CH_STOP in $C6 must be swallowed).
Cleared by main_loop's `@wait` poll as soon as the C64-specific
STOP shadow $91 reports STOP released.  See `main_loop` for the
edge-trigger discipline.

**KBSS (cold-init snapshot, under kernal ROM):**
- `_cold_zp` (127 B) — snapshot of $01-$7F at cold-init entry

**Depends on:** repl, editor, screen, cse_io, debugger, symtab,
disk, mem, strings

## Design

### Four-layer architecture

#### Layer 1: `cse_cold_init` (one-time setup)

Runs once after `loader.s` jumps to `_main`.  Sequence:

1. Save $01-$7F to KBSS.
2. Reset SP to $FF.
3. Unmap BASIC ROM ($01 = $36).
4. `setup_interrupts` — patch all four vectors (must happen before
   any bank-out so the early-entry handlers are reachable).
5. Initialise subsystems: dbg_init, sym_clear, screen, theme,
   cse_io.
6. `define_ws_syms` (workspace symbols for assembler).
7. Fill free memory with $00.
8. Draw splash screen.
9. Capture `kernel_init_sp` (fault-recovery setjmp target), then
   `jmp main_loop_no_clear` — enter the REPL with splash still
   visible.  Prompt is drawn by `main_loop_top`'s `show_prompt`
   call.

A cold-init BRK-into-kernel handoff was considered (would share
the first-prompt code path with userland clean-exit recovery)
but not implemented: unnecessary failure surface at startup.
`dbg_init` instead pre-seeds `userland_zp_buf` and `kernel_zp_buf`
with the CPU-port default ($00=$2F, $01=$36) so the first user
entry via `return_to_userland` has sane banking.

#### Layer 2: `setup_interrupts`

See Interface above.  Runs as step 4 of cold init, before any
banking activity.

#### Layer 3: Reason-named warmstart entry points

Three orthogonal entry points, each named after **why** control
arrived here (the triggering event), not what it does (which may
shift over time).  All three jump to `main_loop_top` when finished;
`main_loop_top` consults `warm_cont` to decide whether the next
iteration shows a fresh prompt or replays the pre-warmstart
command line (see Layer 4).

| Entry point | Reason | Used by |
|-------------|--------|---------|
| `cse_recover` | CSE internal fault (unexpected BRK in kernel code) | `cse_brk_handler` @not_clean_in_kernel |
| `cse_end_debug` | user chose to end the current debug session | `a`/`l` gates; `R` command when debug active |
| `cse_refresh` | user asked for the view back (screen recovery) | NMI-in-kernel; ESC/CLR; `R` command |

The three entry points compose via a trio of rts-returning "body"
subroutines:

```
hw_reinit_body   — SP, $01, setup_interrupts, dbg_init, reset_globals,
                   io_init, theme_init, restore_colors, set_charset.
                   Idempotent; may be called from any CSE state.

end_debug_body   — dbg_reason/step_state/run_user_pending/in_userland
                   to 0; reg_sp to $FF; kernal_out to 0;
                   stop_cooldown to 0; rp_dis_bp/dbg_bp_hit reset;
                   unpatch_all (restores user's in-memory bytes that
                   breakpoints had overwritten with $00); last_cmd
                   cleared.  Editor state and bp_table untouched.

refresh_body     — reset_screen, splash_row, io_clear_eol.
                   Puts the cursor on the bottom row, column 0.
```

Composition:

```
cse_recover:     jsr hw_reinit_body
                 jsr end_debug_body
                 jsr refresh_body
                 jmp main_loop_top

cse_end_debug:   jsr end_debug_body
                 jmp main_loop_top

cse_refresh:     jsr refresh_body
                 jmp main_loop_top
```

`cse_recover` guards against re-entry (`warm_guard`) to prevent
infinite BRK→recover loops; falls through to kernal cold start
($FCE2) as last resort.

**Invariants preserved by every warmstart entry point** (documented
in [memory_design.md § Warmstart entry points](../memory_design.md#warmstart-entry-points)):

1. Editor state — `buf_base`, `gap_lo`, `gap_hi`, `gap_sz`, `ed_dirty`,
   `ed_top_ptr`, and the buffer-backed memory pages — is untouched by
   any entry point.  User's source survives every warmstart.
2. Breakpoint table (`bp_table`) is preserved as the user's *intent*;
   `end_debug_body` calls `unpatch_all` to restore the in-memory
   bytes, but the slots themselves remain.  Next `j`/`g` re-patches.

`main_loop_no_clear` — late entry into `main_loop` that skips
screen-clear; used by the cold-init handoff (splash already drawn).

#### Layer 4: `main_loop` (event loop / ISR body)

The REPL is the body of an interrupt service routine.  Each
iteration resets SP to a known value (`main_loop_top`) so that
the BRK handler's longjmp lands on a clean stack frame.

```
main_loop_top:
        ldx kernel_init_sp
        txs
        cli
        lda warm_cont           ; continuation flag set by a gate?
        beq @normal
        lda #0
        sta warm_cont           ; consume
        jsr exec_line           ; replay the gated command's line_buf
        jmp main_loop_top
@normal:
        ; (post_run_cleanup if returning from userland)
        jsr show_prompt
        jsr read_line
        jsr exec_line
        jmp main_loop_top
```

For non-execution commands, `exec_line` returns normally and the
loop re-iterates.  For execution commands (`j`, `g`, `c`, `t`,
`o`), `exec_line`'s handler eventually calls `return_to_userland`
which RTIs into user code; control comes back via
`cse_brk_handler`'s longjmp to `main_loop_top`.

**Continuation flag (`warm_cont`).**  BSS byte.  Set by gate code
(see [repl.md § Gating pattern](repl.md#gating-pattern)) before
jumping to a warmstart entry point; consumed once at the next
`main_loop_top` pass.

| Value | Meaning |
|-------|---------|
| 0 | No continuation — fresh prompt (default). |
| 1 | Replay `line_buf` through `exec_line` — the gate user said "yes" to re-runs the command they typed. |

`line_buf` is BSS and untouched by any warmstart body, so the
replayed command always has the arguments the user typed.  `a`
(no args) and `l "PROJ"` (arg in line_buf) both work identically.

### Permanent hooks

Installed by `setup_interrupts` during cold init.  All four
vectors are CSE-owned and remain pointed at CSE handlers for the
program's lifetime; only `cse_exit_to_basic` undoes them via
KERNAL RESTOR.

### IRQ early-entry bank-out

When an IRQ fires while kernal is banked out, the CPU reads the
$FFFE RAM shadow → jumps into `cse_brk_handler`'s early-entry
label.  At that moment:

- `$01` bit 1 is clear (kernal banked out).
- CPU has pushed P, PChi, PClo (3 bytes).
- A/X/Y are still live in CPU registers.

The early-entry handler must:

1. Save A/X/Y (replicating $FF48's prologue).
2. Test the B flag in stacked P.
3. **B=1 (BRK):** continue into the standard BRK path; banking
   doesn't matter for BRK because the handler will run to longjmp
   anyway.
4. **B=0 (real IRQ):** delegate to kernal's IRQ body, but route
   the kernal's eventual RTI through a bank-out stub so the
   interrupted code resumes with kernal banked back out.

The IRQ delegation uses **stack frame surgery**:

```
; Stack at early-entry (SP = original_SP - 3):
;   SP+1: P     (CPU push)
;   SP+2: PClo  (CPU push)
;   SP+3: PChi  (CPU push)

cse_brk_handler_early:                 ; vector $FFFE points here
        pha
        txa / pha
        tya / pha                      ; 6-byte stack now (Y,X,A,P,PCL,PCH)
        tsx
        lda $0104,x                    ; stacked P
        and #$10                       ; B-flag test
        bne @brk_path                  ; B=1 → BRK dispatch (kernal-out
                                       ; doesn't matter, handler longjmps)
        ; ── B=0: real IRQ during kernal-out ──
        ; Goal: hand off to kernal IRQ body with kernal banked in;
        ; arrange so its RTI lands at our bank-out stub.

        ; Step 1: replace stacked PClo/PChi with bank_out_stub.
        ; The kernal IRQ body's final RTI will pop our addr and
        ; "return" into the stub, which banks kernal out and RTIs
        ; the original frame.
        lda #<bank_out_stub
        sta $0105,x                    ; PClo slot (BRK semantics: PC was
                                       ; pushed PC-of-IRQ; we OK because
                                       ; for IRQ, pushed PC = exact return)
        lda #>bank_out_stub
        sta $0106,x

        ; Wait — RTI pops in order: P, PClo, PChi.  We need the
        ; kernal IRQ body's RTI to pop P (whatever the kernal pushed
        ; last) and return to bank_out_stub which then RTIs the
        ; outer frame back to the original interrupted PC.
        ;
        ; Concretely, we push a SECOND frame (P + bank_out_stub) on
        ; top of the existing one, then JMP to kernal IRQ body.
        ; Kernal sees Y/X/A on top (just like $FF48 entry pattern),
        ; runs IRQ body, RTIs → pops second-frame P + bank_out_stub
        ; → lands at bank_out_stub.  Stub does sta $01 / RTI →
        ; original frame popped → real return.
        ;
        ; Order of pushes:
        ;   pha {P=current}     ← becomes second-frame P
        ;   pha {PCH=stub-hi}   ← second-frame PCH
        ;   pha {PCL=stub-lo}   ← second-frame PCL
        ; Then bank kernal in; jmp $EA31 (kernal IRQ body).

        php                            ; current P → second frame
        lda #>bank_out_stub
        pha
        lda #<bank_out_stub
        pha
        lda #$36
        sta $01                        ; bank kernal in
        jmp $EA31                      ; kernal IRQ body entry

@brk_path:
        jmp cse_brk_handler            ; standard B=1 dispatch (already
                                       ; common to both kernal-in and
                                       ; kernal-out arrival paths)

; ── bank_out_stub ─────────────────────────────────────────────
; Reached via the kernal IRQ body's RTI popping the second frame
; we synthesised above.  Banks kernal back out and RTIs the
; outer (original) frame back to the interrupted PC.
bank_out_stub:
        pha                            ; preserve A across $01 store
        lda #$34
        sta $01                        ; bank kernal out
        pla
        rti                            ; pop original frame, resume
```

**Reentrance under NMI:** if NMI fires while we are inside the
kernal IRQ body (after the `jmp $EA31`), the NMI handler runs at
its own bank-state (kernal in, since we just banked it in).  The
NMI handler swallows or breaks-into-debugger as usual.  On NMI
RTI, control returns to the kernal IRQ body which finishes
normally and then RTIs through our bank-out stub.  No conflict
with the bank-out stub: it runs only after the IRQ body's RTI,
which only happens once.

**Note on the bank_out_stub's P preservation:** the stub's
`pha/pla` around `sta $01` keeps A clean for the original
interrupted code.  P is not modified by the stub itself; the RTI
pops the original P from the outer frame.

### Longjmp SP convention

`kernel_init_sp` (BSS, 1 byte) is captured during cold init right
before the cold-init userland handoff and used by every BRK
handler longjmp to reset SP to a known value.  This is the kernel's
"setjmp" point; the BRK handler's `ldx kernel_init_sp; txs` is the
"longjmp."

`main_loop_top` is reached only via this longjmp — from
`cse_brk_handler` or from any of the three warmstart entry points
(`cse_recover`, `cse_end_debug`, `cse_refresh`).  Each iteration
of `main_loop` therefore starts from a guaranteed-clean SP.

### Exit path

`cse_exit_to_basic`: RESTOR ($FF8A) restores $0314-$0333
defaults (also overwriting $FFFA/$FFFE shadows via kernal's
own routine), $01-$7F restored from KBSS snapshot, writes $00
to `($2B)-1` (byte before TXTTAB) so BASIC's program link chain
is clean, CINT ($FF81) reinits screen, `jmp ($A002)` enters
BASIC warm start.

### Splash screen

Shows zp, lo02, lo03, and work free ranges at startup.  Drawn
before the cold-init userland handoff; remains visible because the
handoff routes through `main_loop_no_clear`.

## Keyboard

The main loop reads keys via `io_getc()` and dispatches based on the
current mode.  Some keys are handled globally (before mode dispatch),
others are mode-specific.

### Global keys (both modes)

| Key | Action |
|-----|--------|
| RUN/STOP | Toggle REPL ↔ editor (handled inline in the main loop, with key-release debounce so holding it only toggles once) |
| RUN/STOP+RESTORE | NMI break — handled by `cse_nmi_handler`.  In userland: breaks into the debugger (same path as BRK).  In kernel mode: routes to `cse_refresh` (screen recovery; debug context preserved). |

### REPL mode keys

| Key | Action |
|-----|--------|
| Printable characters | Insert at cursor.  Refused (audible blip) at col 39. |
| Cursor keys | Move within screen, no wrap.  Refused (audible blip) at the screen edges. |
| RETURN | `read_line` the cursor row, `exec_line`, `show_prompt` |
| DEL | Backspace, shifting row left.  Refused at col 0, or at or before col 5 of an `AAAA:cmd` row. |
| INS | Right-shift the row, opening a space at the cursor |
| HOME | Cursor to col 0 of current row |
| Shift+HOME / ESC | `reset_screen` + `show_prompt` |

### Editor mode keys

Handled by `ed_handle_key()`.  See [editor.md](editor.md).

## Caveats

- Hex parsing helpers (`hex_val`, `parse_hex*`, `skip_sp`) are
  local to repl.s.
- `cse_brk_handler` and `cse_nmi_handler` are owned by main.s
  but classification logic for BRK source delegates to
  `dbg_bp_find` (debugger.s).
- `cse_brk_handler`'s longjmp to `main_loop_top` discards the
  kernel's pre-`return_to_userland` stack frames.  This is by design:
  `return_to_userland` is the last statement in its caller's effective
  control flow — there is nothing for the kernel to return to.
- `src_top`/`src_bot` are owned by editor.s.
- `ed_ensure_init` is called at startup to initialize the gap
  buffer before `define_ws_syms` (workend needs `buf_base`).
- None of the warmstart entry points (`cse_recover`, `cse_end_debug`,
  `cse_refresh`) call `leave_editor` or touch editor state — the
  editor invariant says the source survives every warmstart.
- The cold-init userland handoff uses the same code path as a
  clean `j`-then-RTS.  This sharing is the design's main lever
  for code economy; keep it.
