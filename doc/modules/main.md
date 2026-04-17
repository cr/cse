# main.s — Application Shell + Interrupt Dispatch

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/main.s`](../../src/main.s) | implementation (6502 assembly) |

## Interface

- `_main` — entry point (jumped to by `loader.s` after
  relocation, BSS zero, KDATA copy).  Contains four layers:
  `cse_cold_init`, `setup_interrupts`, `cse_warm_start`, and
  `main_loop`.
- `state` — exported BSS byte: 0=STOP, 1=REPL, 2=EDIT
- `in_userland` — exported BSS byte: 1 = user code is currently
  running, 0 = kernel.  Set by `return_to_user` (debugger.s),
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
from `zp_save_buf`, then performs the longjmp:

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
        bne @break_user         ; in_userland != 0 → break
        ; kernel mode: swallow (interrupted CSE code resumes)
        rti

@break_user:
        ; userland mode: stash live A/X/Y, fall into BRK path
        sta reg_a / stx reg_x / sty reg_y
        jmp cse_brk_handler_userland_entry
```

The kernel-mode swallow accepts that interrupting CSE code may
leave kernel state broken; the price of always-reliable RESTORE
is bounded to "you may need to ESC/CLR or warm-start the screen".

RESTORE-from-kernel-mode therefore does *not* trigger screen
recovery automatically.  ESC/CLR remains the user's screen-recovery
binding.

### setup_interrupts
**In:** none
**Out:** $0316/$0317, $0318/$0319, $FFFA/$FFFB, $FFFE/$FFFF all
patched to point at handler labels
**Clobbers:** A, X

Called once during cold init, **before any bank-out**.  Replaces
the older split between `kernal_init` (trampolines) and
`install_hooks` (RAM vector-table patching).

| Vector | Address | Patched to |
|--------|---------|------------|
| IBRK | $0316/$0317 | `cse_brk_handler` (kernal-in entry) |
| INMIV | $0318/$0319 | `cse_nmi_handler` (kernal-in entry) |
| NMI shadow | $FFFA/$FFFB | `cse_nmi_handler` early-entry label |
| IRQ/BRK shadow | $FFFE/$FFFF | `cse_brk_handler` early-entry label |

Direct stores; no kernal VECTOR call (step 1 of the design — see
`doc/design_cse_as_kernel.md` § 6).  A future step 2 may migrate
the $0316/$0318 patches to use `KERNAL_VECTOR` ($FF8D) for
cross-kernal compatibility (R3 universal C64/C128 binary).

### Memory

**ZP (6 bytes):** `rp_ptr` (2), `rp_ptr2` (2), `rp_tmp` (1),
`rp_tmp2` (1) — scratch pointers/bytes shared by repl.s,
debugger.s, asm_line.s.

**BSS (4 bytes):** `state` (1), `warm_guard` (1), `in_userland` (1),
`kernel_init_sp` (1).

`kernel_init_sp` is the SP value the BRK handler longjmps to when
returning control to the REPL.  Set once during cold init, just
before the cold-init userland handoff: `tsx; stx kernel_init_sp`.
Read by `cse_brk_handler` tail (`ldx kernel_init_sp; txs`) and by
`cse_warm_start` for hard recovery.

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
9. **Cold-init userland handoff** — synthesise a userland-shaped
   RTI frame whose PC = `brk_stub`, push the brk_stub-1 sentinel
   below it, set `in_userland = 1`, RTI.  This BRKs immediately
   into `cse_brk_handler`, which classifies "PC == brk_stub" as
   a clean exit and longjmps into `main_loop` via the warm-start
   tail's late-entry label (skipping the screen clear so the
   splash remains visible).

The cold path shares its tail with userland-recovery: cold init
≡ "first RTS from a zero-cost user program."  No separate
"first prompt" code path.

#### Layer 2: `setup_interrupts`

See Interface above.  Runs as step 4 of cold init, before any
banking activity.

#### Layer 3: `cse_warm_start` (idempotent recovery)

Reachable from `cse_brk_handler` (internal fault) when the BRK
fired in kernel mode at an address that is not a recognised slot
or `brk_stub` (i.e. CSE itself executed an unexpected $00).

Re-entry guard (`warm_guard`) prevents infinite BRK→warm-start
loops; falls through to kernal cold start ($FCE2) as last resort.

Resets SP, restores $01=$36, calls `setup_interrupts` (idempotent),
calls `dbg_init`, resets globals, reinits I/O/theme/colors/charset,
falls through to `cse_warm_screen`.

`cse_warm_screen` — secondary entry point (screen recovery):
clears screen, draws prompt, falls through to `main_loop`.
Used by ESC/CLR key and by the warm-start tail.

`main_loop_no_clear` — late entry into `main_loop` that skips
screen-clear; used by the cold-init handoff (splash already drawn).

| Entry point | Used by | Severity |
|-------------|---------|----------|
| `cse_warm_start` | `cse_brk_handler` (in-kernel fault) | Hard recovery |
| `cse_warm_screen` | ESC/CLR key, warm-start tail | Screen recovery |
| `main_loop_no_clear` | cold-init handoff via brk_stub | First boot |

#### Layer 4: `main_loop` (event loop / ISR body)

The REPL is the body of an interrupt service routine.  Each
iteration resets SP to a known value (`main_loop_top`) so that
the BRK handler's longjmp lands on a clean stack frame.

```
main_loop_top:
        ldx kernel_init_sp     ; or hardcoded ldx #$FF / txs
        txs
        ; (cli — re-enable IRQs if not already)
        jsr show_prompt
        jsr read_line
        jsr exec_line
        jmp main_loop_top
```

For non-execution commands, `exec_line` returns normally and the
loop re-iterates.  For execution commands (`j`, `g`, `c`, `t`,
`o`), `exec_line`'s handler eventually calls `return_to_user`
which RTIs into user code; control comes back via
`cse_brk_handler`'s longjmp to `main_loop_top`.

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

`main_loop_top` is reached only via this longjmp (from
`cse_brk_handler` or from `cse_warm_screen`).  Each iteration of
`main_loop` therefore starts from a guaranteed-clean SP.

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
| RUN/STOP+RESTORE | NMI break — handled by `cse_nmi_handler`.  In userland: breaks into the debugger (same path as BRK).  In kernel mode: swallowed (no automatic screen recovery; use ESC/CLR if needed). |

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
  kernel's pre-`return_to_user` stack frames.  This is by design:
  `return_to_user` is the last statement in its caller's effective
  control flow — there is nothing for the kernel to return to.
- `src_top`/`src_bot` are owned by editor.s.
- `ed_ensure_init` is called at startup to initialize the gap
  buffer before `define_ws_syms` (workend needs `buf_base`).
- `cse_warm_start` must not call `leave_editor` — editor state
  may be corrupt.
- The cold-init userland handoff uses the same code path as a
  clean `j`-then-RTS.  This sharing is the design's main lever
  for code economy; keep it.
