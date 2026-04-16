; debugger.s — Breakpoints, tracing, and execution control
;
; Breakpoint table: 8 slots × 4 bytes = 32 bytes BSS
;   Offset 0: addr lo
;   Offset 1: addr hi
;   Offset 2: saved byte (original opcode at addr)
;   Offset 3: flags (bit 0 = enabled)
;   addr=$0000 marks an empty slot.
;
; Step BRK table: same 4-byte format, 2 slots (lo/hi branch targets).
; Placed contiguously after bp_table so combined patch/unpatch can
; iterate all 10 slots in one loop.
; Caller fills addr+flags, dbg_enter patches/unpatches around user code.
; Invariant: all BRKs always unpatched before returning to REPL.
;
; Context switch: dbg_enter uses JSR+JMP(indirect) — user code shares
; the CSE 6502 stack.  The BRK handler restores SP from sp_baseline
; and RTS returns to dbg_enter.  No stack page swap.
;
; The debugger is a consumer of the CSE BRK vector, not the owner.
; main.s installs cse_brk_handler permanently at $0316; it dispatches
; to dbg_brk_core when dbg_running != 0.  dbg_enter does NOT touch
; $0316/$0317.
;
; See doc/modules/debugger.md for full design.

        .setcpu "6502"

        .export dbg_init
        .export dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .export dbg_bp_count
        .export dbg_bp_find
        .export dbg_enter
        .export dbg_brk_core
        .export dbg_nmi_break
        .export bp_table, step_bp
        .export dbg_running, dbg_reason, brk_pc, dbg_bp_hit
        .export dbg_step_clear
        .export patch_all, unpatch_all

        .importzp rp_ptr          ; scratch pointer (main.s)
        .import reg_a, reg_x, reg_y, reg_sp, reg_p
        .import zp_save_buf, user_zp_buf

; ── ZP save range — MUST match asm_line.s ──
; The buffer `zp_save_buf` is allocated by asm_line.s.  If these
; constants drift away from the asm_line.s definitions, dbg_enter
; will either overflow the buffer (HI too high) or fail to save the
; full CSE ZP (HI too low, corrupting CSE state on debug return).
; Last byte $59 = end of editor.o ZP allocation, per the linker map.
ZP_SAVE_LO  = $02
ZP_SAVE_HI  = $59
ZP_SAVE_LEN = ZP_SAVE_HI - ZP_SAVE_LO + 1     ; 88 bytes

; Reason codes
DBG_NONE = 0
DBG_BRK  = 1
DBG_NMI  = 2

BP_SLOTS    = 8
STEP_SLOTS  = 2
SLOT_SIZE   = 4         ; bytes per slot
TOTAL_SLOTS = BP_SLOTS + STEP_SLOTS     ; 10

; ── BSS ────────────────────────────────────────────────────────────────
.segment "BSS"

; bp_table and step_bp MUST be contiguous — combined patch/unpatch
; iterates offsets 0..(TOTAL_SLOTS*SLOT_SIZE-1) from bp_table.
bp_table:      .res BP_SLOTS * SLOT_SIZE     ; 32 bytes: 8 slots × 4
step_bp:       .res STEP_SLOTS * SLOT_SIZE   ; 8 bytes: 2 step slots × 4

dbg_running:   .res 1          ; $80 = user code active, 0 = REPL
dbg_reason:    .res 1          ; why we returned (0=none, 1=BRK, 2=NMI)
brk_pc:        .res 2          ; PC where break occurred / resume address
dbg_bp_hit:    .res 1          ; slot# of breakpoint that was hit ($FF = none)
sp_baseline:   .res 1          ; SP at @tramp entry (just after jsr @tramp's
                                ; push).  The BRK/NMI handlers restore SP to
                                ; this value before rts so that rts pops the
                                ; @tramp return address — bypassing any bytes
                                ; the user pushed (e.g. JSR return) since the
                                ; jmp(brk_pc).  Without this, a BRK fired after
                                ; the user did a JSR would rts through the
                                ; user-pushed return address and never reach
                                ; dbg_enter.

; ── CODE ───────────────────────────────────────────────────────────────
.segment "CODE"

; ── dbg_init ──────────────────────────────────────────────────────────
; Zero breakpoint + step tables and all debugger state.
; Clobbers: A, X
;
dbg_init:
        ; Clear both tables (bp + step = 40 bytes contiguous)
        ldx #TOTAL_SLOTS * SLOT_SIZE - 1
        jsr clear_bp_x
        ; Clear remaining state
        sta dbg_running
        sta dbg_reason
        sta brk_pc
        sta brk_pc+1
        lda #$FF
        sta dbg_bp_hit
        sta reg_sp             ; sane default SP for cold t/j
        lda #$20                ; bit 5 always set, I=0, all flags clear
        sta reg_p
        rts

; ── dbg_bp_set ────────────────────────────────────────────────────────
; Set a breakpoint at the given address.
; In:  A = addr lo, X = addr hi
; Out: C=0 success, A = slot number (0–7)
;      C=1 table full (A undefined)
; Clobbers: A, X, Y
;
; Note: does not check for duplicate addresses.  Setting the same
; address twice uses two slots.  The caller (repl.s) can check if
; desired.
;
dbg_bp_set:
        ; Stash target address in rp_ptr (ZP scratch, not used by loop)
        sta rp_ptr
        stx rp_ptr+1

        ; Find first empty slot (addr lo | addr hi == 0)
        ldy #0                  ; slot index
        ldx #0                  ; table byte offset
@find:  lda bp_table,x
        ora bp_table+1,x
        beq @found              ; empty slot
        inx
        inx
        inx
        inx
        iny
        cpy #BP_SLOTS
        bne @find

        ; Table full
        lda #$FF
        sec
        rts

@found: lda rp_ptr
        sta bp_table,x         ; addr lo
        lda rp_ptr+1
        sta bp_table+1,x       ; addr hi
        lda #0
        sta bp_table+2,x       ; saved = 0 (not yet patched)
        lda #1
        sta bp_table+3,x       ; flags = enabled
        tya                     ; A = slot number
        clc
        rts

; ── dbg_bp_del ────────────────────────────────────────────────────────
; Delete a breakpoint by slot number.
; In:  A = slot number (0–7)
; Out: C=0 success, C=1 invalid slot
; Clobbers: A, X
;
dbg_bp_del:
        cmp #BP_SLOTS
        bcs @bad                ; slot >= 8 → invalid
        ; Compute table offset: slot × 4
        asl
        asl
        tax
        lda #0
        sta bp_table,x         ; addr lo = 0
        sta bp_table+1,x       ; addr hi = 0
        sta bp_table+2,x       ; saved = 0
        sta bp_table+3,x       ; flags = 0
        clc
        rts
@bad:   lda #$FF
        sec
        rts

; ── dbg_bp_clear ──────────────────────────────────────────────────────
; Delete all breakpoints (bp_table only, not step slots).
; Clobbers: A, X
;
dbg_bp_clear:
        ldx #BP_SLOTS * SLOT_SIZE - 1
        ; fall through

; ── clear_bp_x — zero bp_table[0..X] ─────────────────────
clear_bp_x:
        lda #0
@z:     sta bp_table,x
        dex
        bpl @z
        rts

; ── dbg_bp_count ──────────────────────────────────────────────────────
; Count active breakpoints (non-empty slots).
; Out: A = count (0–8)
; Clobbers: X, Y
;
dbg_bp_count:
        lda #0                  ; count
        ldy #0                  ; table offset
@cnt:   ldx bp_table,y
        bne @hit
        ldx bp_table+1,y
        beq @skip               ; both zero → empty slot
@hit:   clc
        adc #1
@skip:  iny
        iny
        iny
        iny
        cpy #BP_SLOTS * SLOT_SIZE
        bne @cnt
        rts

; ── dbg_bp_find ───────────────────────────────────────────────────────
; Find a breakpoint by address.
; In:  A = addr lo, X = addr hi
; Out: C=0 found, A = slot number (0–7)
;      C=1 not found, A = $FF
; Clobbers: A, X, Y
;
dbg_bp_find:
        sta rp_ptr                ; stash target in ZP scratch
        stx rp_ptr+1
        ldy #0                  ; slot index
        ldx #0                  ; table byte offset
@loop:  lda bp_table,x
        cmp rp_ptr
        bne @next
        lda bp_table+1,x
        cmp rp_ptr+1
        bne @next
        ; Found
        tya                     ; A = slot number
        clc
        rts
@next:  inx
        inx
        inx
        inx
        iny
        cpy #BP_SLOTS
        bne @loop
        ; Not found
        lda #$FF
        sec
        rts

; ── patch_all ──────────────────────────────────────────────────────────
; Patch all enabled slots (bp_table + step_bp): save original byte,
; write $00 (BRK).  Forward order: bp slots first, then step slots.
; Step may overwrite a BRK that bp_patch left — step_patch saves that
; BRK so unpatch_all can restore it in reverse order.
; Clobbers: A, X, Y, rp_ptr
;
patch_all:
        ldx #0
        ldy #0                  ; for (rp_ptr),y indirect indexed
@loop:  lda bp_table,x         ; addr lo
        ora bp_table+1,x       ; |= addr hi
        beq @next               ; empty slot → skip
        lda bp_table+3,x       ; flags
        beq @next               ; not enabled → skip
        ; Load target address into rp_ptr
        lda bp_table,x
        sta rp_ptr
        lda bp_table+1,x
        sta rp_ptr+1
        ; Save original byte
        lda (rp_ptr),y            ; read from target
        sta bp_table+2,x       ; saved byte
        ; Write BRK
        lda #$00
        sta (rp_ptr),y
@next:  inx
        inx
        inx
        inx
        cpx #TOTAL_SLOTS * SLOT_SIZE
        bne @loop
        rts

; ── unpatch_all ────────────────────────────────────────────────────────
; Restore all patched slots: write saved byte back.
; Reverse order: step slots first (offsets 36,32), then bp slots
; (28,24,...,0).  This ensures step unpatches the BRK that bp_patch
; wrote, then bp_unpatch restores the original byte.
; Clobbers: A, X, Y, rp_ptr
;
unpatch_all:
        ldx #(TOTAL_SLOTS - 1) * SLOT_SIZE      ; 36 = last slot offset
        ldy #0
@loop:  lda bp_table,x
        ora bp_table+1,x
        beq @next               ; empty slot
        lda bp_table+3,x
        beq @next               ; not enabled
        ; Load target address
        lda bp_table,x
        sta rp_ptr
        lda bp_table+1,x
        sta rp_ptr+1
        ; Restore original byte
        lda bp_table+2,x
        sta (rp_ptr),y
@next:  dex
        dex
        dex
        dex
        bpl @loop               ; X=$FC (negative) after offset 0 → exits
        rts

; ── dbg_step_clear ────────────────────────────────────────────────────
; Zero the step BRK table (2 slots × 4 bytes).
; Caller fills addr+flags before calling dbg_enter.
; Clobbers: A, X
;
dbg_step_clear:
        lda #0
        ldx #STEP_SLOTS * SLOT_SIZE - 1
@z:     sta step_bp,x
        dex
        bpl @z
        rts

; ═══════════════════════════════════════════════════════════════════════════
; Context switch — enter user code / return to REPL
; ═══════════════════════════════════════════════════════════════════════════

; ── dbg_enter ─────────────────────────────────────────────────────────
; void dbg_enter(void);
;
; Saves CSE ZP, patches breakpoints, enters user code via JSR+JMP.
; User code shares the CSE 6502 stack.  Returns normally after the
; BRK/NMI handler strips its frame and RTS back here.
;
; Before calling: set brk_pc to target address, _reg_* to desired
; register state, step_bp slots for step targets.
;
dbg_enter:
        ; ── 1. Save CSE ZP → zp_save_buf ──
        ldx #ZP_SAVE_LEN - 1
@szp:   lda ZP_SAVE_LO,x
        sta zp_save_buf,x
        dex
        bpl @szp

        ; ── 2. Patch all breakpoints + step BRKs ──
        jsr patch_all

        ; ── 3. Clear stale break state ──
        ; (dbg_running is set inside @tramp, after sp_baseline is captured —
        ; so there's no window in which the NMI handler could see
        ; dbg_running set but sp_baseline stale.)
        lda #0
        sta dbg_reason         ; 0 = no break (set by handler if BRK fires)
        lda #$FF
        sta dbg_bp_hit         ; $FF = no bp hit (set by handler if BRK fires)

        ; ── 4. Enter user code via the trampoline ──
        ; jsr @tramp: pushes the return address so the BRK/NMI handler
        ; can rts back here.  @tramp captures sp_baseline, sets the
        ; running flag, loads user A/X/Y/P, and jmps to brk_pc.
        jsr @tramp
        ; ── we arrive here after BRK handler does RTS or user RTS ──
        ;
        ; Capture user registers AND user ZP on the clean-RTS path.
        ; BRK/NMI handlers already populate reg_* and call
        ; snap_user_zp themselves on entry, so dbg_reason != 0
        ; means we don't touch them here.  On a plain user RTS the
        ; registers are LIVE in the CPU and the live ZP is still
        ; the user's — the next jsr unpatch_all would destroy
        ; both.
        ;
        ; ─── Invariant ────────────────────────────────────────
        ;   PHP is the VERY FIRST instruction after entering CSE
        ;   from userland — no instruction between the user's RTS
        ;   and the PHP below may touch N/V/Z/C/I/D.  PHP and PHA
        ;   themselves never modify flags, so PHP → PHA is safe.
        ;   Adding anything else here would silently corrupt the
        ;   captured P.
        php                     ; save user P  ← must be first
        pha                     ; save user A  (pha doesn't touch flags)
        lda dbg_reason
        bne @skip_user_cap
        pla                     ; pop A
        sta reg_a
        pla                     ; pop P
        ; Clean-RTS: strip the two hardware-transport bits that PHP
        ; unconditionally sets (bit 5 "unused" and bit 4 "B").  No
        ; BRK happened, so reg_p must not claim one, and bit 5 is a
        ; never-meaningful artefact of how any P byte reaches a
        ; stack slot.  PLP on re-entry ignores both bits anyway, so
        ; this is purely to make reg_p a faithful status-flag view.
        and #%11001111          ; clear bits 5, 4
        sta reg_p
        stx reg_x
        sty reg_y
        tsx
        stx reg_sp
        jsr snap_user_zp
        jmp @user_cap_done
@skip_user_cap:
        pla                     ; discard saved A
        pla                     ; discard saved P
@user_cap_done:

        ; ── 5. Unpatch all breakpoints ──
        jsr unpatch_all

        ; ── 6. Restore CSE ZP ──
        ldx #ZP_SAVE_LEN - 1
@rzp:   lda zp_save_buf,x
        sta ZP_SAVE_LO,x
        dex
        bpl @rzp

        ; ── 7. Re-enable interrupts ──
        ; BRK/NMI handler leaves I=1 (SEI by hardware).
        ; Must restore before returning to REPL or io_getc hangs.
        cli
        rts

; ── @tramp ─────────────────────────────────────────────────────────
; Reached via `jsr @tramp` from dbg_enter step 4.
;
;   1. tsx; stx sp_baseline — capture SP just after jsr @tramp's push.
;      This is the SP value the BRK/NMI handlers must restore to so
;      that their `rts` pops the @tramp return address and lands at
;      "after jsr @tramp" in dbg_enter.
;   2. set dbg_running — gates the NMI handler.  Order matters:
;      sp_baseline must be valid before dbg_running is set, otherwise
;      an NMI fired in this window would call dbg_nmi_break with a
;      stale sp_baseline.
;   3. Load user A/X/Y/P from reg_*.  PHA/PLP restores the flags.
;   4. jmp (brk_pc) — user code starts.
;
; ─── Invariant ──────────────────────────────────────────────────────
;   PLP is the VERY LAST instruction before control transfers to
;   userland.  No instruction between PLP and JMP (BRK_PC) may touch
;   N/V/Z/C/I/D.  JMP (abs) never modifies flags, so PLP → JMP is
;   safe.  This is the mirror of dbg_enter's "PHP first" invariant
;   on the return path — together they guarantee the user's flag
;   state flows intact into and out of every debugger entry/exit.
@tramp:
        tsx
        stx sp_baseline
        lda #$80
        sta dbg_running
        lda reg_p
        pha
        lda reg_a
        ldx reg_x
        ldy reg_y
        plp                     ; ← must be last flag-touching insn before jmp
        jmp (brk_pc)

; ── snap_user_zp ─────────────────────────────────────────────────────
; Copy live ZP $02..$59 → user_zp_buf.  Called at the very start
; of dbg_brk_core / dbg_nmi_break (where the live ZP is still
; the user's working state) and from dbg_enter step 6 on the
; clean-RTS path (same — user RTSed back, ZP not yet clobbered).
;
; Critical: this proc must NOT use any ZP scratch byte itself
; (those bytes ARE the user state we're snapshotting).  Uses X
; only.  Preserves A/Y.
.proc snap_user_zp
        pha
        txa
        pha
        ldx #ZP_SAVE_LEN - 1
@l:     lda ZP_SAVE_LO,x
        sta user_zp_buf,x
        dex
        bpl @l
        pla
        tax
        pla
        rts
.endproc

; ── dbg_brk_core ─────────────────────────────────────────────────────
; Called from cse_brk_handler (main.s) when user BRK fires
; (dbg_running != 0).
;
; Stack at entry (SP+1 upward):
;   Y  X  A  P(B=1)  PClo(brk+2)  PChi
;   ─── KERNAL pushed ───  ─── CPU pushed ───
;
; The KERNAL's IRQ entry at $FF48 pushes A/X/Y and checks B flag.
; BRK dispatch occurs BEFORE any IRQ servicing.
;
dbg_brk_core:
        ; ── 0. Snapshot user ZP before doing anything else.
        ; The handler about to follow uses ZP scratch (e.g.
        ; dbg_bp_find), so the live user ZP must be captured
        ; first or it's gone.
        jsr snap_user_zp
        ; ── 1. Extract user registers from stack ──
        tsx
        lda $0101,x             ; Y (KERNAL pushed last)
        sta reg_y
        lda $0102,x             ; X
        sta reg_x
        lda $0103,x             ; A
        sta reg_a
        ; P (CPU pushed).  Bit 5 is the hardware "unused = 1" — strip
        ; it so reg_p cleanly represents the semantic flag state.
        ; Bit 4 (B) is kept: hardware set it to 1 for BRK dispatch
        ; (what we're in right now) and to 0 for plain IRQ, and we
        ; want reg_p to reflect that distinction.
        lda $0104,x
        and #%11011111          ; clear bit 5 only; keep B
        sta reg_p
        ; PC: CPU pushed brk_addr+2 — adjust back
        lda $0105,x             ; PClo
        sec
        sbc #2
        sta brk_pc
        lda $0106,x             ; PChi
        sbc #0
        sta brk_pc+1

        ; ── 2. Compute user's pre-BRK SP ──
        ; CPU pushed 3 (P, PClo, PChi), KERNAL pushed 3 (A, X, Y) = 6
        txa
        clc
        adc #6
        sta reg_sp

        ; ── 3. Set reason = BRK, find which bp ──
        lda #DBG_BRK
        sta dbg_reason
        lda brk_pc
        ldx brk_pc+1
        jsr dbg_bp_find
        sta dbg_bp_hit         ; slot# or $FF

        ; ── 4. Clear running flag ──
        lda #0
        sta dbg_running

        ; ── 5. Restore SP to sp_baseline and rts back to dbg_enter ──
        ; sp_baseline was captured by @tramp right after `jsr @tramp` pushed
        ; its return address.  Setting SP = sp_baseline puts the @tramp ret
        ; addr at SP+1/SP+2, so the rts pops it and lands at "after jsr
        ; @tramp" in dbg_enter — REGARDLESS of how many bytes the user
        ; pushed (e.g. via JSR) before BRK fired.  The previous strip+adc#6
        ; approach uncovered the user-pushed bytes and rts'd through them,
        ; which produced the "t1 hangs on JSR" bug: stepping into a JSR
        ; popped the JSR's return address as the BRK handler's rts target,
        ; jumping to "instruction after JSR" in user code instead of back
        ; to dbg_enter.
        ldx sp_baseline
        txs
        rts

; ── dbg_nmi_break ────────────────────────────────────────────────────
; Entered from main.s cse_nmi_handler when dbg_running bit 7 is set.
;
; At entry: A/X/Y have user's live values (NMI doesn't push them).
; Stack: P  PClo  PChi  (3 bytes, CPU pushed)
; KERNAL NMI entry ($FE43) does SEI + JMP ($0318) — no register pushes.
;
dbg_nmi_break:
        ; ── 0. Snapshot user ZP before any handler code.
        jsr snap_user_zp
        ; ── 1. Save user registers (live in CPU regs) ──
        sta reg_a
        stx reg_x
        sty reg_y

        ; ── 2. Extract P and PC from stack ──
        tsx
        ; P (CPU pushed).  NMI hardware push puts bit 5=1, bit 4=0.
        ; Strip both: bit 5 is a meaningless transport artefact, and
        ; bit 4 cleanly stays 0 (NMI is never "a BRK").
        lda $0101,x
        and #%11001111          ; clear bits 5, 4
        sta reg_p
        lda $0102,x             ; PClo (exact address, no +2)
        sta brk_pc
        lda $0103,x             ; PChi
        sta brk_pc+1

        ; ── 3. Compute user's pre-NMI SP ──
        txa
        clc
        adc #3                  ; CPU pushed 3 bytes
        sta reg_sp

        ; ── 4. Set reason = NMI, no bp hit ──
        lda #DBG_NMI
        sta dbg_reason
        lda #$FF
        sta dbg_bp_hit

        ; ── 5. Clear running flag, restore SP to sp_baseline, return ──
        ; Same trick as dbg_brk_core: SP = sp_baseline puts the @tramp
        ; ret addr at SP+1/SP+2, so rts pops it and lands at "after jsr
        ; @tramp" in dbg_enter — bypassing any user-pushed bytes.
        lda #0
        sta dbg_running
        ldx sp_baseline
        txs
        rts

