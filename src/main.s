; main.s — CSE application shell: cold init, warm start, main loop,
;          permanent interrupt dispatch (Phase 18 — ISR-kernel model).
;
; Four-layer architecture:
;   cse_cold_init   — one-time setup (jumped to by loader.s)
;   setup_interrupts — vectors → CSE handlers (before any bank-out)
;   cse_recover    — internal CSE fault (unexpected BRK in kernel)
;   cse_end_debug  — user-initiated debug-session termination
;   cse_refresh    — screen recovery (NMI-in-kernel, ESC/CLR, R cmd)
;   main_loop_top   — iteration top (handler longjmp target)
;
; Interrupt handlers (permanent, vectors never change):
;   cse_brk_handler  — $0316/$0317 (kernal-in) and $FFFE (kernal-out)
;                      via cse_brk_handler_early.  Unified BRK dispatch.
;   cse_nmi_handler  — $0318/$0319 (kernal-in) and $FFFA (kernal-out)
;                      direct (no early-entry stub).  The 6502 sets I=1
;                      as part of the NMI vector sequence, so no SEI
;                      shim is needed to suppress IRQ interleaving.
;   bank_out_stub    — second-RTI-frame target for IRQ early-entry:
;                      banks KERNAL back out and RTIs original frame.
;
; Gate primitives live in debugger.s:
;   save_userland_state    — called by handlers (userland → kernel).
;   restore_userland_state — RTIs into userland (kernel → userland).
;   return_to_userland         — sentinel-push wrapper around
;                             restore_userland_state (fresh starts).
;
; Kernel→userland dispatch from main_loop happens AT TOP LEVEL after
; `jsr exec_line` rts's back: main_loop tests run_user_pending and
; jmps to either `return_to_userland` (fresh start) or
; `restore_userland_state` (resume).  Commands never RTI while inside
; a jsr frame — they just stage state and rts normally.

        .setcpu "6502"
        .macpack longbranch
        .include "macros.inc"

; ── Exports ──────────────────────────────────────────────────
        .export _main
        .export kernel_init_sp, run_user_pending
        .export stop_cooldown
        .importzp state, in_userland, warm_cont                 ; zp.s
        .export cse_recover, cse_end_debug, cse_refresh
        .export hw_reinit_body, end_debug_body, refresh_body
        .export main_loop_top
        .export cse_brk_handler, cse_nmi_handler
        .export cse_brk_handler_early
        .export bank_out_stub
        .export setup_interrupts
        ; MODE_NONE / MODE_JUMP / MODE_RESUME are equates — repl.s
        ; redefines them locally (ca65 doesn't propagate `=` through
        ; .export).  No external export needed.

; ── Runtime ZP ───────────────────────────────────────────────
        .importzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2

; ── Imports ──────────────────────────────────────────────────
        .import io_init, io_putc, io_sync, io_blip
        .import io_getc, io_clear_eol
        .import reset_screen, restore_colors, newline, theme_init
        .import cursor_show, cursor_hide
        .import scr_lo, scr_hi
        .import define_ws_syms
        .import cse_zp_end, cse_start
        .import sym_clear
        .import dbg_init
        .import save_userland_state, restore_userland_state
        .import return_to_userland
        .import brk_stub
        .import dbg_bp_find
        .import unpatch_all
        .import step_next_pc, arm_step_bp
        .import step_state, step_remaining
        .import step_bp
        .importzp dbg_reason, kernal_out, cur_device    ; zp.s
        .import brk_pc, dbg_bp_hit
        .import reg_p, reg_sp
        .import rp_dis_bp, last_cmd
        .import ed_ensure_init
        .import exec_line, read_line, show_prompt, cmd_info
        .import post_run_cleanup, hygiene_after_userland
        .import log_line, log_info                      ; log.s
        .importzp asm_cpu
        .import cur_addr, block_size
        .import ed_handle_key, enter_editor, leave_editor

; ── Imports: strings.s ──────────────────────────────────────
        .import VERSION_STR, s_manual

; ── Constants ────────────────────────────────────────────────
        .include "log.inc"
SCREEN_WIDTH = 40
SCREEN_HEIGHT = 25
MEM_CONFIG   = $01
KEY_REPEAT   = $028A
VIC_MEMCTL   = $D018

; KERNAL vectors
IBRK_VEC     = $0316          ; page-3 BRK dispatch
INMIV_VEC    = $0318          ; page-3 NMI dispatch
NMI_VEC_RAM  = $FFFA          ; RAM shadow (kernal-out)
IRQ_VEC_RAM  = $FFFE
KERNAL_RESTOR = $FF8A
KERNAL_IRQ_BODY = $EA31

P_B_FLAG     = $10            ; mask: bit 4 of stacked P
BANK_IN      = $36
BANK_OUT     = $34

; Reason codes — ordered by liveness (higher = more alive).
; `cmp #DBG_BRK / bcs` identifies a resumable session in one compare.
DBG_NONE = 0    ; no session (never started / ended)
DBG_RTS  = 1    ; alive-but-terminal: landed at RTS/RTI or clean exit
DBG_BRK  = 2    ; resumable: non-return break
DBG_NMI  = 3    ; resumable: NMI

; run_user_pending values.  Set by command handlers; dispatched by
; main_loop after exec_line rts's back.
MODE_NONE   = 0
MODE_JUMP   = 1       ; fresh execution: push sentinel → return_to_userland
MODE_RESUME = 2       ; resume: restore_userland_state directly

; Run states
ST_STOP      = 0
ST_REPL      = 1
ST_EDIT      = 2

; Key codes
CH_ENTER     = 13
CH_STOP      = 3
CH_DEL       = 20
CH_INS       = 148
CH_CURS_UP   = 145
CH_CURS_DOWN = 17
CH_CURS_LEFT = 157
CH_CURS_RIGHT = 29
CH_HOME      = 19
CH_CLR       = 147
CH_ESC       = $1B

CUR_COL      = $D3
CUR_ROW      = $D6

TXTTAB       = $0801
WORKSTART    = TXTTAB - 1

COLD_ZP      = $F8DA          ; KBSS: 127 B snapshot of $01-$7F

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

warm_guard:        .res 1
kernel_init_sp:    .res 1      ; setjmp SP target for cse_recover /
                                ; cse_end_debug / cse_refresh; also
                                ; captured once by cold init.  Normal
                                ; break/resume longjmps to reg_sp.
run_user_pending:  .res 1      ; MODE_NONE / MODE_JUMP / MODE_RESUME —
                                ; set by command handlers, read by
                                ; main_loop after exec_line rts.
_irq_saved_a:      .res 1      ; scratch for cse_brk_handler_early's
                                ; @irq_path: user A is saved here
                                ; while we clobber A with the
                                ; bank_out_stub address bytes, then
                                ; restored for the FF48-style push.
stop_cooldown:     .res 1      ; RUN/STOP edge-filter:
                                ;   set to 1 when (a) we process a STOP
                                ;     press (so the same hold doesn't
                                ;     re-trigger via autorepeat), or
                                ;   set to 1 by hygiene_after_userland on
                                ;     an NMI break (STOP was held to
                                ;     cause the break; the stale CH_STOP
                                ;     in $C6 must be swallowed).
                                ; Cleared by main_loop's @wait poll as
                                ; soon as KERNAL STOP ($FFE1) reports
                                ; STOP up — so the next press is honoured.

; ── PRG load address ─────────────────────────────────────────
.segment "LOADADDR"
        .word $0801

; ── EXEHDR — BASIC stub ─────────────────────────────────────
.segment "EXEHDR"
        .word @next
        .word 2026
        .byte $9E
        .byte "2061", 0
@next:  .word 0

; ── CODE ────────────────────────────────────────────────────
.segment "CODE"

; ═════════════════════════════════════════════════════════════
; Layer 1: cse_cold_init
; ═════════════════════════════════════════════════════════════
.proc _main
        ; ── 1. Keyboard / charset-switch setup ──
        lda KEY_REPEAT
        ora #$80
        sta KEY_REPEAT
        lda #$80
        sta $0291

        ; ── 2. Save $01-$7F to KBSS ──
        ldx #0
@save_zp:
        lda $01,x
        sta COLD_ZP,x
        inx
        cpx #$7F
        bne @save_zp

        ; ── 3. Unmap BASIC ROM ──
        lda MEM_CONFIG
        and #$FE
        sta MEM_CONFIG

        ; ── 4. Install interrupt hooks BEFORE any bank-out ──
        jsr setup_interrupts

        ; ── 5. Init debugger (zeroes bp+step tables, reg_*) ──
        jsr dbg_init

        ; ── 6. Symbol table ──
        ; Must precede any sym_define caller (e.g. ed_ensure_init,
        ; which reaches sym_define transitively via gb_init →
        ; update_workend pre-F2).  See doc/modules/main.md
        ; § Caveats — cold-init sequence prerequisite.
        jsr sym_clear

        ; ── 7. Init editor buffer ──
        jsr ed_ensure_init

        ; ── 8. Workspace symbols ──
        jsr define_ws_syms

        ; ── 9. CPU mode default ──
.ifndef DEFAULT_CPU
  DEFAULT_CPU = 1
.endif
        lda #DEFAULT_CPU
        sta asm_cpu

        ; ── 10. Fill free ZP with $FF ──
        jsr cse_zp_end
        tax
        lda #$FF
@zp:    sta $00,x
        inx
        cpx #$80
        bcc @zp

        ; ── 11. Fill free workspace with $00 ──
        lda #<WORKSTART
        sta rp_ptr
        lda #>WORKSTART
        sta rp_ptr+1
        jsr cse_start
        ldy #0
        tya
@work:  sta (rp_ptr),y
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       cpx rp_ptr+1
        bne @work

        ; ── 12. I/O + screen ──
        jsr io_init
        jsr theme_init
        jsr reset_screen
        jsr set_charset

        ; ── 13. Global state ──
        jsr reset_globals

        ; ── 14. Splash ──
        lda #SCREEN_HEIGHT - 10
        jsr splash_row
        lda #<VERSION_STR
        ldx #>VERSION_STR
        jsr log_info
        jsr newline
        sec                     ; splash mode
        jsr cmd_info
        jsr newline
        lda #<s_manual
        ldx #>s_manual
        jsr log_info
        ; Prompt row
        lda #SCREEN_HEIGHT - 1
        jsr splash_row
        jsr io_clear_eol

        ; ── 15. Capture kernel_init_sp (fault-recovery target only) ──
        tsx
        stx kernel_init_sp

        ; ── 16. Enter the REPL.  Splash is already drawn; the prompt
        ;       is drawn by main_loop_top's first `jsr show_prompt`.
        jmp main_loop_top
.endproc

; ═════════════════════════════════════════════════════════════
; Layer 3: Reason-named warmstart entry points.
;
; Three composable entry points, each named after the reason it
; was reached.  They share three rts-returning body subroutines:
;   hw_reinit_body  — HW + software re-init (SP, $01, vectors,
;                     dbg state, I/O, theme, charset).
;   end_debug_body  — discard any active debug context; unpatch_all
;                     so the program as-written is what's in memory.
;   refresh_body    — reset screen, draw prompt row, position cursor.
;
; Order is load-bearing: cse_refresh sits immediately before
; main_loop_top so its tail falls through (saves the trailing
; `jmp main_loop_top`).  Body subroutines live further down in the
; file (after the BRK/NMI handlers).
;
; See doc/memory_design.md § Warmstart entry points for the
; invariants (editor and breakpoint-table survival).
; ═════════════════════════════════════════════════════════════

; ── cse_recover — internal CSE fault recovery ────────────────
; Reset SP first, then call the bodies as balanced jsr-subs.  The
; `ldx #$FF / txs` discards whatever kernel frames were on the
; stack when the fault struck.
cse_recover:
        lda warm_guard
        bne @hard_fail
        inc warm_guard

        ldx #$FF
        txs
        stx kernel_init_sp              ; X=$FF, captured for end_debug
                                        ; / refresh; SP doesn't change
                                        ; across the balanced jsrs below
        jsr hw_reinit_body
        jsr end_debug_body              ; fault → context is suspect
        jsr refresh_body

        lda #0
        sta warm_guard

        jmp main_loop_top

@hard_fail:
        jmp $FCE2               ; KERNAL cold start — last resort

; ── cse_end_debug — explicit debug-session termination ──────
cse_end_debug:
        ldx kernel_init_sp
        txs
        jsr end_debug_body
        jmp main_loop_top

; ── cse_refresh — user asked for the view back ──────────────
; Falls through into main_loop_top (saves the trailing `jmp`).
cse_refresh:
        ldx kernel_init_sp
        txs
        jsr refresh_body

; ═════════════════════════════════════════════════════════════
; Layer 4: main_loop_top / main_loop
;
; main_loop_top is the target of:
;   * cse_brk_handler's longjmp (handler_finalize) — SP = reg_sp.
;   * cse_recover and cse_end_debug (warmstart `jmp`s);
;     cse_refresh falls through directly above.
;     SP = kernel_init_sp ($FF) on all three.
;   * The cold-init userland handoff (`_main`'s final jmp).
; All are valid entries; main_loop's internal stack use is balanced.
; ═════════════════════════════════════════════════════════════
main_loop_top:
        cli
        lda state
        bne @live
        jmp cse_exit_to_basic

@live:
        ; Warmstart continuation dispatch.  A gate may have set
        ; warm_cont before jumping to a warmstart entry point; honour
        ; it by replaying line_buf through exec_line.  See
        ; doc/modules/main.md § Layer 4.
        lda warm_cont
        beq @check_post_run
        lda #0
        sta warm_cont           ; consume
        jsr exec_line           ; replay the gated command
        jmp main_loop_top

@check_post_run:
        ; Post-run cleanup if we just came back from userland.
        ; run_user_pending is non-zero iff a command (j/g/c/t/o) set
        ; it on this cycle — so it's our "just returned from userland"
        ; signal even on clean brk_stub exits where dbg_reason=0 and
        ; step_state=0.  Without it the clean-exit regs display in
        ; post_run_cleanup would be skipped.
        lda dbg_reason
        ora step_state
        ora run_user_pending
        beq @prompt
        jsr post_run_cleanup
        lda #0
        sta run_user_pending    ; consume; don't re-display on next
                                ; main_loop_top entry (e.g. ESC warm).
@prompt:
        jsr show_prompt

; main_loop body — regular iteration.  Entered from main_loop_top
; (above) or from the RETURN-key branch below via `jmp main_loop`
; after a non-execution command.
;
; RUN/STOP handling (STOP in REPL enters editor; STOP in editor leaves):
; a single `stop_cooldown` flag covers both the post-NMI stale-STOP
; case and the post-toggle bounce case.  Set to 1 whenever we ignore
; a STOP we've already consumed (or hygiene_after_userland on an NMI
; break).  Cleared by the poll at @wait as soon as KERNAL STOP ($FFE1)
; reports the key released (Z=0).  Any STOP received while the flag is
; set is silently swallowed; once the user releases, the next fresh
; press is honoured.  No wait loops, no buffer drain.
main_loop:
        lda state
        bne :+
        jmp cse_exit_to_basic
:
        jsr cursor_show

@wait:  ; Poll for release (clears cooldown) or a buffered key.
        ;
        ; PLATFORM-SPECIFIC (C64 KERNAL):
        ;   Reads $91 directly — the C64 KERNAL keyscan maintains
        ;   this as a STOP-key shadow ($7F = down, $FF = up).  We
        ;   avoid KERNAL STOP ($FFE1) here despite it being a
        ;   stable entry point, because $F6ED (its default target)
        ;   clears $C6 when STOP is down as a side effect — which
        ;   would swallow every CH_STOP (and any typed-ahead keys)
        ;   before we can read them.
        ;
        ; R3 (universal C64/C128 binary) will need to abstract this
        ;   into a leaf function — other kernals may not expose the
        ;   same shadow layout.  See TODO.md § R3.
        lda $91
        cmp #$7F
        beq @still_down
        lda #0
        sta stop_cooldown
@still_down:
        lda $C6                 ; kb buffer count (non-blocking kbhit)
        beq @wait
        jsr io_getc
        sta @key
        jsr cursor_hide

        lda @key
        cmp #CH_STOP
        bne @not_stop
        lda stop_cooldown
        bne main_loop           ; cooldown active → swallow
        lda #1
        sta stop_cooldown       ; arm until user releases
        lda state
        cmp #ST_REPL
        bne @stop_edit
        jsr enter_editor
        jmp main_loop
@stop_edit:
        cmp #ST_EDIT
        bne main_loop
        jsr leave_editor
        jmp main_loop
@not_stop:

        lda state
        cmp #ST_EDIT
        bne @repl_mode
        lda @key
        jsr ed_handle_key
        jmp main_loop

@repl_mode:
        lda @key

        cmp #CH_ENTER
        bne @not_enter
        jsr read_line
        ; Cursor intentionally NOT homed to col 0 here.  exec_line
        ; receives the cursor wherever the user was when RETURN fired
        ; — typically mid-line at the end of their typed command.
        ; Command handlers reposition as needed:
        ;   - Display emitters (`.`, `m`, `d`) call io_addr_cmd which
        ;     explicitly sets CUR_COL=0 to overwrite the prompt row.
        ;   - Log-emitting commands let log_open's auto-advance
        ;     (CUR_COL != 0 → newline) move to a fresh row — the
        ;     "enter anywhere" half of log.md's Contract.
        ; Homing CUR_COL=0 here would force log_open to see a
        ; "safe at col 0" state and skip its advance, overwriting
        ; the user's typed command line.  See Escape Analysis for
        ; the 2026-04-20 log contract regression.
        lda #0
        sta run_user_pending    ; clear before exec_line
        jsr exec_line
        lda run_user_pending
        beq @no_run
        cmp #MODE_JUMP
        bne @resume
        jmp return_to_userland      ; fresh: sentinel + restore
@resume:
        jmp restore_userland_state
@no_run:
        jsr show_prompt
        jmp main_loop
@not_enter:

        cmp #CH_DEL
        bne @not_del
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_ptr
        lda scr_hi,x
        sta rp_ptr+1
        ldy #4
        lda (rp_ptr),y
        cmp #$3A
        bne @del_min0
        lda CUR_COL
        cmp #6
        jcc @reject
        jmp @del_shift
@del_min0:
        lda CUR_COL
        jeq @reject
@del_shift:
        dec CUR_COL
        ldy CUR_COL
@del_loop:
        iny
        lda (rp_ptr),y
        dey
        sta (rp_ptr),y
        iny
        cpy #SCREEN_WIDTH - 1
        bcc @del_loop
        lda #$20
        ldy #SCREEN_WIDTH - 1
        sta (rp_ptr),y
        jmp main_loop
@not_del:

        cmp #CH_INS
        bne @not_ins
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_ptr
        lda scr_hi,x
        sta rp_ptr+1
        ldy #SCREEN_WIDTH - 2
@ins_loop:
        cpy CUR_COL
        bcc @ins_done_shift
        lda (rp_ptr),y
        iny
        sta (rp_ptr),y
        dey
        dey
        jmp @ins_loop
@ins_done_shift:
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        bcs @ins_pad
        tay
        lda #$20
        sta (rp_ptr),y
@ins_pad:
        lda #$20
        ldy #SCREEN_WIDTH - 1
        sta (rp_ptr),y
        jmp main_loop
@not_ins:

        cmp #CH_CURS_UP
        bne @not_up
        lda CUR_ROW
        jeq @reject
        dec CUR_ROW
        jsr io_sync
        jmp main_loop
@not_up:

        cmp #CH_CURS_DOWN
        bne @not_down
        lda CUR_ROW
        cmp #SCREEN_HEIGHT - 1
        jcs @reject
        inc CUR_ROW
        jsr io_sync
        jmp main_loop
@not_down:

        cmp #CH_CURS_LEFT
        bne @not_left
        lda CUR_COL
        jeq @reject
        dec CUR_COL
        jmp main_loop
@not_left:

        cmp #CH_CURS_RIGHT
        bne @not_right
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        jcs @reject
        inc CUR_COL
        jmp main_loop
@not_right:

        cmp #CH_HOME
        bne @not_home
        lda #0
        sta CUR_COL
        jmp main_loop
@not_home:

        cmp #CH_CLR
        beq @do_clr
        cmp #CH_ESC
        bne @default
@do_clr:
        jmp cse_refresh
@default:
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        jcs @reject
        lda @key
        jsr io_putc
        jmp main_loop

@reject:
        jsr io_blip
        jmp main_loop

@key:   .byte 0

; ═════════════════════════════════════════════════════════════
; setup_interrupts — install all four vectors.
; Direct stores to $0316/$0318 (page-3) AND $FFFA/$FFFE (RAM shadows).
; Writes to $FFFA/$FFFE pass through to RAM regardless of $01 bit 1.
; MUST run before any bank-out in cold init.
; Clobbers: A.
; ═════════════════════════════════════════════════════════════
.proc setup_interrupts
        lda #<cse_brk_handler
        sta IBRK_VEC
        lda #>cse_brk_handler
        sta IBRK_VEC + 1
        lda #<cse_nmi_handler
        sta INMIV_VEC
        sta NMI_VEC_RAM
        lda #>cse_nmi_handler
        sta INMIV_VEC + 1
        sta NMI_VEC_RAM + 1
        lda #<cse_brk_handler_early
        sta IRQ_VEC_RAM
        lda #>cse_brk_handler_early
        sta IRQ_VEC_RAM + 1
        rts
.endproc

; ── reset_globals ────────────────────────────────────────────
reset_globals:
        lda #ST_REPL
        sta state
        lda #$10
        sta block_size
        lda #0
        sta block_size+1
        sta cur_addr
        sta run_user_pending
        lda #$08                ; cur_device + cur_addr+1 share the value
        sta cur_device
        sta cur_addr+1
        rts

set_charset:
        lda VIC_MEMCTL
        ora #$02
        sta VIC_MEMCTL
        rts

splash_row:
        sta CUR_ROW
        lda #0
        sta CUR_COL
        jmp io_sync

; ═════════════════════════════════════════════════════════════
; cse_brk_handler_early — $FFFE RAM-shadow entry (kernal-out).
;
; Replicate KERNAL $FF48's Y/X/A push prologue, then test the B flag:
;   B=1 → BRK: fall into cse_brk_handler (banking doesn't matter;
;         handler longjmps anyway).
;   B=0 → real IRQ during kernal-out: synthesise a second RTI frame
;         pointing at bank_out_stub, bank KERNAL in, JMP $EA31.
;         The KERNAL IRQ body's RTI pops our second frame → lands at
;         bank_out_stub → banks KERNAL out → RTIs original frame.
; ═════════════════════════════════════════════════════════════
cse_brk_handler_early:
        ; $FFFE RAM-shadow entry (CPU vectored here because KERNAL was
        ; banked out at the moment of interrupt).  Entry stack from
        ; CPU push: [PChi, PClo, P] (top = P).  A, X, Y are user's
        ; live values.  Classify BRK (B=1) vs IRQ (B=0) via stacked P
        ; while preserving A/X/Y.
        ;
        ; Two subtleties we have to honour:
        ;   a) `tsx` clobbers X — so we push user X BEFORE tsx to
        ;      preserve it.
        ;   b) `pla` resets N/Z from the pulled value — so we branch
        ;      on the B-flag result BEFORE any pla.
        ;
        ; BRK path: we've already pushed A and X in the right FF48
        ; order; pushing Y completes the FF48-style prologue and we
        ; jump straight into cse_brk_handler.
        ; IRQ path: unwind the A/X pushes back into registers and
        ; jump to @irq_path, which sees the untouched [PChi, PClo, P]
        ; stack layout it expects.
        pha                     ; save user A
        txa
        pha                     ; save user X
        tsx                     ; X = current SP (user X safely on stack)
        lda $0103,x             ; stacked P sits 3 bytes above current SP
        and #P_B_FLAG
        beq @to_irq_path        ; Z=1 → B=0 → real IRQ

        ; B=1 (BRK): finish the FF48-style prologue (push Y), go.
        tya
        pha
        jmp cse_brk_handler

@to_irq_path:
        ; Unwind A/X so the stack is back to CPU-push state
        ; [PChi, PClo, P] and A/X are in registers as entry.
        pla
        tax
        pla
        jmp @irq_path

        ; B=0 (real IRQ during kernal-out): surgery plan
        ;
        ;   Current stack (top → bottom): P, PClo, PChi.
        ;
        ;   Insert a second frame *above* the existing one so
        ;   $EA81's concluding RTI pops OUR frame (→ bank_out_stub),
        ;   then bank_out_stub's RTI pops the original frame (→
        ;   interrupted PC).  Then push Y/X/A so $EA81's opening
        ;   PLA/TAY/PLA/TAX/PLA sequence finds user's regs where it
        ;   expects them.
        ;
        ;   Final stack layout for `jmp $EA31`:
        ;     Y  X  A  (our P, PClo, PChi = bank_out_stub)  orig P PCL PCH
        ;
        ;   RTI-expected push order is PChi, PClo, P (so P ends up
        ;   on top of the 3).
@irq_path:
        ; User A/X/Y are still in registers (@to_irq_path restored them
        ; from the early-classification pushes).  We need user A for the
        ; FF48-style push below, but loading the bank_out_stub address
        ; bytes will clobber A.  Stash user A in a dedicated BSS byte
        ; first (rather than a shared ZP scratch — the interrupted code
        ; may be mid-use of ZP temps).
        sta _irq_saved_a
        lda #>bank_out_stub
        pha
        lda #<bank_out_stub
        pha
        php                     ; clean P for bank_out_stub's RTI target
        ; Replicate $FF48's A/X/Y push so $EA81's pla/tay/pla/tax/pla
        ; gets user's real registers.
        lda _irq_saved_a
        pha                     ; user A
        txa
        pha                     ; user X
        tya
        pha                     ; user Y
        lda #BANK_IN
        sta MEM_CONFIG
        jmp KERNAL_IRQ_BODY

; bank_out_stub — RTI target for the IRQ surgery above.  Banks
; KERNAL back out, then RTIs the original (outer) frame to the
; interrupted code at the banking state it had.
bank_out_stub:
        pha                     ; preserve A across $01 write
        lda #BANK_OUT
        sta MEM_CONFIG
        pla
        rti

; ═════════════════════════════════════════════════════════════
; cse_brk_handler — unified BRK dispatcher.
; Entered via $0316 (kernal-in, after $FF48 pushed Y/X/A) OR from
; cse_brk_handler_early (same stack shape after its prologue).
; ═════════════════════════════════════════════════════════════
cse_brk_handler:
        lda in_userland
        bne @userland_brk
        ; Kernel fault — BRK in kernel code.
        jmp cse_recover

@userland_brk:
        lda #0
        sta in_userland

        ; Capture user state (raw Y/X/A/P/PC into reg_*/brk_pc,
        ; snap user ZP, restore kernel ZP).
        jsr save_userland_state

        ; BRK-specific fixup:
        ;   reg_p: clear bit 5 (transport); keep bit 4 (B=1 marker).
        ;   brk_pc: subtract 2 (CPU pushed brk_addr + 2).
        lda reg_p
        and #%11011111
        sta reg_p
        lda brk_pc
        sec
        sbc #2
        sta brk_pc
        lda brk_pc+1
        sbc #0
        sta brk_pc+1

        ; Default classification: DBG_BRK, no slot.
        lda #DBG_BRK
        sta dbg_reason
        lda #$FF
        sta dbg_bp_hit

        ; Clean exit via brk_stub?  User's top-level RTS popped the
        ; sentinel, landing at brk_stub where this BRK fired.  Promote
        ; to DBG_RTS (alive-but-terminal) and reset brk_pc := cur_addr
        ; so the display layer shows a user-meaningful address.
        lda brk_pc
        cmp #<brk_stub
        bne @not_clean
        lda brk_pc+1
        cmp #>brk_stub
        bne @not_clean
        lda cur_addr
        sta brk_pc
        lda cur_addr+1
        sta brk_pc+1
        lda #DBG_RTS
        sta dbg_reason
        jmp handler_finalize

@not_clean:
        ; User-visible bp hit?
        lda brk_pc
        ldx brk_pc+1
        jsr dbg_bp_find
        bcs @not_bp
        sta dbg_bp_hit
        jmp handler_finalize

@not_bp:
        ; Step BRK match?  (step_bp = bp_table + 32; last 2 slots.)
        lda step_state
        beq handler_finalize    ; not stepping — unplanned user BRK
        lda step_remaining
        beq handler_finalize    ; stepping done, finalise

        lda step_bp
        cmp brk_pc
        bne @chk_s1
        lda step_bp+1
        cmp brk_pc+1
        beq @chain
@chk_s1:
        lda step_bp+4
        cmp brk_pc
        bne handler_finalize
        lda step_bp+5
        cmp brk_pc+1
        bne handler_finalize

@chain:
        ; Step chain iteration.  Sequence:
        ;   1. Unpatch current step_bp so step_next_pc sees the
        ;      original opcode at brk_pc.
        ;   2. step_next_pc + arm_step_bp write the new targets.
        ;   3. dec step_remaining.
        ;   4. jmp restore_userland_state — same door as main_loop's
        ;      resume path; its txs reg_sp releases the BRK+KERNAL
        ;      frame and pushes a fresh RTI frame.  Zero SP creep
        ;      by construction.  restore_userland_state re-patches
        ;      via its internal patch_all.
        jsr unpatch_all
        jsr step_next_pc
        jsr arm_step_bp
        dec step_remaining
        jmp restore_userland_state

; ── handler_finalize ─────────────────────────────────────────
; All non-chain userland-exit paths converge here.  Unpatch BRKs,
; run KERNAL/VIC hygiene (color/border/$D018/sprites/IRQs/kbd/$CC),
; longjmp SP to reg_sp, jump to main_loop_top.  The longjmp to
; reg_sp is the setjmp/longjmp equivalent — it releases the BRK
; frame + handler's own (balanced) jsr chain in one store.
;
; Hygiene runs BEFORE txs because after txs the stack pointer is
; at user's reg_sp — any jsr would push its return address into
; the slot the user's top-level RTS would have popped.  It runs
; HERE (not in post_run_cleanup) so that clean `j`/`g` exits —
; where dbg_reason=0 and step_state=0, so post_run_cleanup is
; skipped — still get their colours / VIC / $CC / kbd-buffer
; reset.  save_userland_state has already restored the kernel's
; ZP by this point, so hygiene's reads of theme_* / io_color /
; scr_lo/hi all hit the kernel's ZP view as intended.
; ═════════════════════════════════════════════════════════════
handler_finalize:
        jsr unpatch_all
        jsr hygiene_after_userland
        ldx reg_sp
        txs
        jmp main_loop_top

; ═════════════════════════════════════════════════════════════
; cse_nmi_handler — NMI dispatcher.  Reached from both:
;   * $0318 (kernal-in): KERNAL's $FE43 dispatch does SEI + JMP
;     ($0318) and we land here.
;   * $FFFA (kernal-out): CPU fetches the RAM-shadow vector and
;     jumps directly here.
; No SEI needed in either path — the 6502 sets I=1 as part of the
; NMI vector sequence (push PC/P, set I, fetch $FFFA), so IRQs are
; already masked on entry.
;
; At NMI entry A holds the user's live register value.  We can't
; clobber it with `lda in_userland` before deciding the dispatch,
; because on the swallow path we'd have no way to restore it.
; Use `bit in_userland / bmi` instead: bit 7 of the operand goes
; directly into the N flag, independent of A.  This relies on
; in_userland using the $80 / 0 convention (set by restore_userland_
; state; cleared by this handler and cse_brk_handler).
; ═════════════════════════════════════════════════════════════
cse_nmi_handler:
        bit in_userland
        bmi @userland_nmi
        ; Kernel mode: user wants the view back.  The NMI frame on
        ; stack is discarded by cse_refresh's `ldx kernel_init_sp /
        ; txs`; debug context (if any) is preserved.
        jmp cse_refresh

@userland_nmi:
        ; Normalize stack to match $FF48-BRK shape (Y/X/A/P/PClo/PChi)
        ; so save_userland_state can be shared.  The CPU didn't push
        ; A/X/Y on NMI; they're user's live values.
        pha                     ; A
        txa
        pha                     ; X
        tya
        pha                     ; Y (top of frame after these three)
        lda #0
        sta in_userland

        jsr save_userland_state

        ; NMI-specific fixup:
        ;   reg_p: clear bits 4 and 5 (both transport; no BRK semantics).
        ;   brk_pc: unchanged (NMI pushes exact PC).
        lda reg_p
        and #%11001111
        sta reg_p

        lda #DBG_NMI
        sta dbg_reason
        lda #$FF
        sta dbg_bp_hit
        jmp handler_finalize

; ═════════════════════════════════════════════════════════════
; Body subroutines (called by the warmstart entry points above —
; cse_recover / cse_end_debug / cse_refresh, located just before
; main_loop_top).  Balanced jsr-subs — SP discipline is the
; caller's responsibility.  Entry points do the SP reset once
; before jsr'ing in.
; ═════════════════════════════════════════════════════════════

; hw_reinit_body — full HW + software re-init.  Idempotent.
hw_reinit_body:
        lda #BANK_IN
        sta MEM_CONFIG
        jsr setup_interrupts
        jsr dbg_init
        jsr reset_globals
        jsr io_init
        jsr theme_init
        jsr restore_colors
        jmp set_charset                 ; tail-call

; end_debug_body — discard any active debug context.  Preserves
; editor state and bp_table; unpatches live breakpoints so the
; user's program memory reflects what they actually wrote.
end_debug_body:
        lda #0
        sta dbg_reason
        sta step_state
        sta step_remaining
        sta run_user_pending
        sta in_userland
        sta kernal_out
        sta stop_cooldown
        sta last_cmd
        lda #$FF
        sta reg_sp                      ; userland SP reset
        sta dbg_bp_hit
        sta rp_dis_bp
        jmp unpatch_all                 ; tail-call

; refresh_body — reset screen, draw prompt row, position cursor.
refresh_body:
        jsr reset_screen
        lda #SCREEN_HEIGHT - 1
        jsr splash_row
        jmp io_clear_eol                ; tail-call

; ═════════════════════════════════════════════════════════════
; cse_exit_to_basic
; ═════════════════════════════════════════════════════════════
cse_exit_to_basic:
        sei
        lda #$00
        sta $0291
        jsr KERNAL_RESTOR
        lda MEM_CONFIG
        and #$FD
        sta MEM_CONFIG
        ldx #1
@rzp:   lda COLD_ZP,x
        sta $01,x
        inx
        cpx #$7F
        bne @rzp
        lda COLD_ZP
        sta MEM_CONFIG
        cli
        lda #0
        sta TXTTAB - 1
        jsr $FF81               ; KERNAL CINT
        jmp ($A002)
