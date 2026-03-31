; debugger.s — Breakpoints, tracing, and execution control
;
; Phase A: breakpoint table management (bp_set, bp_del, bp_clear, bp_count)
; Phase B: context switch (dbg_enter, dbg_brk_handler, dbg_nmi_break)
; Phase C: single-step t/n (step_bp, step_clear/patch/unpatch, usr_stk_byte)
;
; Breakpoint table: 8 slots × 4 bytes = 32 bytes BSS
;   Offset 0: addr lo
;   Offset 1: addr hi
;   Offset 2: saved byte (original opcode at addr)
;   Offset 3: flags (bit 0 = enabled)
;   addr=$0000 marks an empty slot.
;
; Step BRK table: same 4-byte format, 2 slots (lo/hi branch targets).
; C fills addr+flags, dbg_enter patches/unpatches around user code.
; Invariant: all BRKs always unpatched before returning to REPL.
;
; See doc/modules/debugger.md for full design.

        .setcpu "6502"

        .export _dbg_init
        .export _dbg_bp_set, _dbg_bp_del, _dbg_bp_clear
        .export _dbg_bp_count
        .export _dbg_bp_patch, _dbg_bp_unpatch
        .export _dbg_bp_find
        .export _dbg_enter
        .export _dbg_brk_handler
        .export _dbg_nmi_break
        .export _bp_table
        .export _dbg_running, _dbg_reason, _brk_pc, _dbg_bp_hit, _dbg_has_ctx
        .export _step_bp
        .export _dbg_step_clear, _dbg_step_patch, _dbg_step_unpatch
        .export _dbg_usr_stk_byte

        .importzp ptr1          ; cc65 scratch pointer ($4E/$4F)
        .import _reg_a, _reg_x, _reg_y, _reg_sp, _reg_p
        .import _zp_save_buf
        .import _kernal_bank_out, _kernal_bank_in

ZP_SAVE_LO  = $02              ; must match asm_bridge.s
ZP_SAVE_HI  = $5C
ZP_SAVE_LEN = ZP_SAVE_HI - ZP_SAVE_LO + 1     ; 91 bytes

CSE_STK     = $E100            ; CSE stack snapshot (KERNAL RAM)
USR_STK     = $E200            ; user stack snapshot (KERNAL RAM)

; Reason codes
DBG_NONE = 0
DBG_BRK  = 1
DBG_NMI  = 2

BP_SLOTS    = 8
BP_SIZE     = 4         ; bytes per slot
STEP_SLOTS  = 2
STEP_SIZE   = 4         ; same 4-byte format

; ── BSS ────────────────────────────────────────────────────────────────
.segment "BSS"

_bp_table:      .res BP_SLOTS * BP_SIZE   ; 32 bytes: 8 slots × 4

_dbg_running:   .res 1          ; $80 = user code active, 0 = REPL
_dbg_reason:    .res 1          ; why we returned (0=none, 1=BRK, 2=NMI)
_brk_pc:        .res 2          ; PC where break occurred / resume address
_dbg_bp_hit:    .res 1          ; slot# of breakpoint that was hit ($FF = none)
_cse_saved_sp:  .res 1          ; CSE's 6502 SP saved before entering user code
_saved_brk_lo:  .res 1          ; original $0316 value (lo)
_saved_brk_hi:  .res 1          ; original $0317 value (hi)
_dbg_has_ctx:   .res 1          ; $80 = user context in $E200 is valid

_step_bp:       .res STEP_SLOTS * STEP_SIZE ; 8 bytes: 2 step slots × 4
_dbg_stk_tmp:   .res 1          ; temp for usr_stk_byte banking

; ── CODE ───────────────────────────────────────────────────────────────
.segment "CODE"

; ── _dbg_init ──────────────────────────────────────────────────────────
; Zero the breakpoint table and all debugger state.
; Clobbers: A, X
;
_dbg_init:
        lda #0
        ldx #BP_SLOTS * BP_SIZE - 1
@clr:   sta _bp_table,x
        dex
        bpl @clr
        sta _dbg_running
        sta _dbg_reason
        sta _brk_pc
        sta _brk_pc+1
        sta _dbg_has_ctx
        lda #$FF
        sta _dbg_bp_hit
        rts

; ── _dbg_bp_set ────────────────────────────────────────────────────────
; Set a breakpoint at the given address.
; In:  A = addr lo, X = addr hi
; Out: C=0 success, A = slot number (0–7)
;      C=1 table full (A undefined)
; Clobbers: A, X, Y
;
; Note: does not check for duplicate addresses.  Setting the same
; address twice uses two slots.  The caller (repl.c) can check if
; desired.
;
_dbg_bp_set:
        ; Save target address temporarily
        sta _bps_addr_lo
        stx _bps_addr_hi

        ; Find first empty slot (addr lo | addr hi == 0)
        ldy #0                  ; slot index
        ldx #0                  ; table byte offset
@find:  lda _bp_table,x
        ora _bp_table+1,x
        beq @found              ; empty slot
        inx
        inx
        inx
        inx
        iny
        cpy #BP_SLOTS
        bne @find

        ; Table full — return $FF for C callers
        lda #$FF
        sec
        rts

@found: lda _bps_addr_lo
        sta _bp_table,x         ; addr lo
        lda _bps_addr_hi
        sta _bp_table+1,x       ; addr hi
        lda #0
        sta _bp_table+2,x       ; saved = 0 (not yet patched)
        lda #1
        sta _bp_table+3,x       ; flags = enabled
        tya                     ; A = slot number
        clc
        rts

; ── _dbg_bp_set temporaries (BSS, ROM-safe) ──
.segment "BSS"
_bps_addr_lo: .res 1
_bps_addr_hi: .res 1
.segment "CODE"

; ── _dbg_bp_del ────────────────────────────────────────────────────────
; Delete a breakpoint by slot number.
; In:  A = slot number (0–7)
; Out: C=0 success, C=1 invalid slot
; Clobbers: A, X
;
_dbg_bp_del:
        cmp #BP_SLOTS
        bcs @bad                ; slot >= 8 → invalid
        ; Compute table offset: slot × 4
        asl
        asl
        tax
        lda #0
        sta _bp_table,x         ; addr lo = 0
        sta _bp_table+1,x       ; addr hi = 0
        sta _bp_table+2,x       ; saved = 0
        sta _bp_table+3,x       ; flags = 0
        clc
        rts
@bad:   lda #$FF
        sec
        rts

; ── _dbg_bp_clear ──────────────────────────────────────────────────────
; Delete all breakpoints.
; Clobbers: A, X
;
_dbg_bp_clear:
        lda #0
        ldx #BP_SLOTS * BP_SIZE - 1
@z:     sta _bp_table,x
        dex
        bpl @z
        rts

; ── _dbg_bp_count ──────────────────────────────────────────────────────
; Count active breakpoints (non-empty slots).
; Out: A = count (0–8)
; Clobbers: X, Y
;
_dbg_bp_count:
        lda #0                  ; count
        ldy #0                  ; table offset
@cnt:   ldx _bp_table,y
        bne @hit
        ldx _bp_table+1,y
        beq @skip               ; both zero → empty slot
@hit:   clc
        adc #1
@skip:  iny
        iny
        iny
        iny
        cpy #BP_SLOTS * BP_SIZE
        bne @cnt
        rts

; ── _dbg_bp_patch ──────────────────────────────────────────────────────
; Patch all enabled breakpoints: save original byte, write $00 (BRK).
; Must be called before entering user code.
; Clobbers: A, X, Y, ptr1
;
_dbg_bp_patch:
        ldx #0                  ; table byte offset
        ldy #0                  ; for indirect indexed
@loop:  lda _bp_table,x         ; addr lo
        ora _bp_table+1,x       ; |= addr hi
        beq @next               ; empty slot → skip
        lda _bp_table+3,x       ; flags
        beq @next               ; not enabled → skip
        ; Load target address into ptr1
        lda _bp_table,x
        sta ptr1
        lda _bp_table+1,x
        sta ptr1+1
        ; Save original byte
        lda (ptr1),y            ; read from target
        sta _bp_table+2,x       ; saved byte
        ; Write BRK
        lda #$00
        sta (ptr1),y
@next:  inx
        inx
        inx
        inx
        cpx #BP_SLOTS * BP_SIZE
        bne @loop
        rts

; ── _dbg_bp_unpatch ────────────────────────────────────────────────────
; Restore all patched breakpoints: write saved byte back.
; Must be called after returning from user code.
; Clobbers: A, X, Y, ptr1
;
_dbg_bp_unpatch:
        ldx #0
        ldy #0
@loop:  lda _bp_table,x
        ora _bp_table+1,x
        beq @next               ; empty slot
        lda _bp_table+3,x
        beq @next               ; not enabled
        ; Load target address
        lda _bp_table,x
        sta ptr1
        lda _bp_table+1,x
        sta ptr1+1
        ; Restore original byte
        lda _bp_table+2,x
        sta (ptr1),y
@next:  inx
        inx
        inx
        inx
        cpx #BP_SLOTS * BP_SIZE
        bne @loop
        rts

; ── _dbg_bp_find ───────────────────────────────────────────────────────
; Find a breakpoint by address.
; In:  A = addr lo, X = addr hi
; Out: C=0 found, A = slot number (0–7)
;      C=1 not found, A = $FF
; Clobbers: A, X, Y
;
_dbg_bp_find:
        sta _bps_addr_lo
        stx _bps_addr_hi
        ldy #0                  ; slot index
        ldx #0                  ; table byte offset
@loop:  lda _bp_table,x
        cmp _bps_addr_lo
        bne @next
        lda _bp_table+1,x
        cmp _bps_addr_hi
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

; ═══════════════════════════════════════════════════════════════════════════
; Context switch — enter user code / return to REPL
; ═══════════════════════════════════════════════════════════════════════════

; ── _dbg_enter ─────────────────────────────────────────────────────────
; void dbg_enter(void);
;
; Saves CSE context, patches breakpoints, enters user code via RTI.
; Does not return normally — the BRK/NMI handler restores CSE context
; and returns to the C caller of dbg_enter (via the saved stack).
;
; Before calling: set _brk_pc to target address, _reg_* to desired
; register state.  For resume: _dbg_has_ctx must be $80.
;
_dbg_enter:
        ; ── 1. Save CSE ZP → _zp_save_buf ──
        ldx #ZP_SAVE_LEN - 1
@szp:   lda ZP_SAVE_LO,x
        sta _zp_save_buf,x
        dex
        bpl @szp

        ; ── 2. Save CSE SP ──
        tsx
        stx _cse_saved_sp

        ; ── 3. Stack page snapshot ──
        ;  Save CSE stack to $E100.
        ;  If resuming (_dbg_has_ctx=$80), restore user stack from $E200.
        jsr _kernal_bank_out    ; sei + bank out KERNAL
        ldx #0
        lda _dbg_has_ctx
        bmi @swap_stacks        ; has valid user context → swap

        ; Fresh start: only save CSE stack, don't load user stack
@save_cse_only:
        lda $0100,x
        sta CSE_STK,x
        dex
        bne @save_cse_only
        beq @stacks_done        ; always

@swap_stacks:
        lda $0100,x
        sta CSE_STK,x           ; save CSE stack
        lda USR_STK,x
        sta $0100,x             ; restore user stack
        dex
        bne @swap_stacks

@stacks_done:
        jsr _kernal_bank_in     ; bank in KERNAL + cli

        ; ── 4. Save current $0316, install our BRK handler ──
        lda $0316
        sta _saved_brk_lo
        lda $0317
        sta _saved_brk_hi
        lda #<_dbg_brk_handler
        sta $0316
        lda #>_dbg_brk_handler
        sta $0317

        ; ── 5. Patch breakpoints then step BRKs ──
        jsr _dbg_bp_patch
        jsr _dbg_step_patch

        ; ── 6. Set running flag ──
        lda #$80
        sta _dbg_running

        ; ── 7. Switch to user SP ──
        ldx _reg_sp
        txs

        ; ── 8. Build RTI frame ──
        ; RTI pops P first, then PClo, PChi.
        ; Push order: PChi, PClo, P
        lda _brk_pc+1
        pha                     ; PChi
        lda _brk_pc
        pha                     ; PClo
        lda _reg_p
        pha                     ; P (status register)

        ; ── 9. Load user registers ──
        lda _reg_a
        ldx _reg_x
        ldy _reg_y

        ; ── 10. RTI → user code ──
        rti

; ── _dbg_brk_handler ──────────────────────────────────────────────────
; Entered from KERNAL via ($0316) when BRK fires.
;
; Stack at entry (SP+1 upward):
;   Y  X  A  P(B=1)  PClo(brk+2)  PChi
;   ─── KERNAL pushed ───  ─── CPU pushed ───
;
; The KERNAL's IRQ entry at $FF48 pushes A/X/Y and checks B flag.
; BRK dispatch occurs BEFORE any IRQ servicing.
;
_dbg_brk_handler:
        ; ── 1. Extract user registers from stack ──
        tsx
        lda $0101,x             ; Y (KERNAL pushed last)
        sta _reg_y
        lda $0102,x             ; X
        sta _reg_x
        lda $0103,x             ; A
        sta _reg_a
        lda $0104,x             ; P (CPU pushed, B=1)
        sta _reg_p
        ; PC: CPU pushed brk_addr+2 — adjust back
        lda $0105,x             ; PClo
        sec
        sbc #2
        sta _brk_pc
        lda $0106,x             ; PChi
        sbc #0
        sta _brk_pc+1

        ; ── 2. Compute user's pre-BRK SP ──
        ; CPU pushed 3 (P, PClo, PChi), KERNAL pushed 3 (A, X, Y) = 6
        txa
        clc
        adc #6
        sta _reg_sp

        ; ── 3. Set reason = BRK, find which bp ──
        lda #DBG_BRK
        sta _dbg_reason
        lda _brk_pc
        ldx _brk_pc+1
        jsr _dbg_bp_find
        sta _dbg_bp_hit         ; slot# or $FF

        ; Fall through to common return
        jmp _dbg_return_common

; ── _dbg_nmi_break ────────────────────────────────────────────────────
; Entered from cse_io.s _nmi_handler when _dbg_running bit 7 is set.
;
; At entry: A/X/Y have user's live values (NMI doesn't push them).
; Stack: P  PClo  PChi  (3 bytes, CPU pushed)
; KERNAL NMI entry ($FE43) does SEI + JMP ($0318) — no register pushes.
;
_dbg_nmi_break:
        ; ── 1. Save user registers (live in CPU regs) ──
        sta _reg_a
        stx _reg_x
        sty _reg_y

        ; ── 2. Extract P and PC from stack ──
        tsx
        lda $0101,x             ; P
        sta _reg_p
        lda $0102,x             ; PClo (exact address, no +2)
        sta _brk_pc
        lda $0103,x             ; PChi
        sta _brk_pc+1

        ; ── 3. Compute user's pre-NMI SP ──
        txa
        clc
        adc #3                  ; CPU pushed 3 bytes
        sta _reg_sp

        ; ── 4. Set reason = NMI, no bp hit ──
        lda #DBG_NMI
        sta _dbg_reason
        lda #$FF
        sta _dbg_bp_hit

        ; Fall through to common return

; ── _dbg_return_common ────────────────────────────────────────────────
; Shared return path for BRK handler and NMI break.
; Restores CSE context and returns to the C caller of dbg_enter.
;
_dbg_return_common:
        ; ── 1. Clear running flag ──
        lda #0
        sta _dbg_running

        ; ── 2. Unpatch step BRKs, then regular breakpoints ──
        ; Step first: if a step target coincides with a regular bp,
        ; step_unpatch restores the BRK bp_patch left; bp_unpatch then
        ; restores the original byte.
        ; Switch to a temporary SP — user stack may be inconsistent.
        ldx #$FF
        txs
        jsr _dbg_step_unpatch
        jsr _dbg_bp_unpatch

        ; ── 3. Restore $0316 ──
        lda _saved_brk_lo
        sta $0316
        lda _saved_brk_hi
        sta $0317

        ; ── 4. Stack page snapshot: user → $E200, CSE ← $E100 ──
        jsr _kernal_bank_out
        ldx #0
@swap:  lda $0100,x
        sta USR_STK,x           ; save user stack
        lda CSE_STK,x
        sta $0100,x             ; restore CSE stack
        dex
        bne @swap
        jsr _kernal_bank_in

        ; ── 5. Mark user context as valid ──
        lda #$80
        sta _dbg_has_ctx

        ; ── 6. Restore CSE SP ──
        ldx _cse_saved_sp
        txs

        ; ── 7. Restore CSE ZP ──
        ldx #ZP_SAVE_LEN - 1
@rzp:   lda _zp_save_buf,x
        sta ZP_SAVE_LO,x
        dex
        bpl @rzp

        ; ── 8. Return to C caller of dbg_enter ──
        ; The CSE stack now has the return address from when C called
        ; dbg_enter.  RTS returns there.  CLI re-enables interrupts.
        cli
        rts

; ═══════════════════════════════════════════════════════════════════════════
; Phase C — Step BRK management
; ═══════════════════════════════════════════════════════════════════════════

; ── _dbg_step_clear ────────────────────────────────────────────────────
; Zero the step BRK table (2 slots × 4 bytes).
; C fills addr+flags before calling dbg_enter.
; Clobbers: A, X
;
_dbg_step_clear:
        lda #0
        ldx #STEP_SLOTS * STEP_SIZE - 1
@z:     sta _step_bp,x
        dex
        bpl @z
        rts

; ── _dbg_step_patch ────────────────────────────────────────────────────
; Patch all enabled step BRKs: save original byte, write $00.
; Called by _dbg_enter after _dbg_bp_patch.
; Clobbers: A, X, Y, ptr1
;
_dbg_step_patch:
        ldx #0
        ldy #0
@loop:  lda _step_bp,x
        ora _step_bp+1,x
        beq @next               ; empty slot (addr=$0000) → skip
        lda _step_bp+3,x
        beq @next               ; flags=0 → disabled → skip
        lda _step_bp,x
        sta ptr1
        lda _step_bp+1,x
        sta ptr1+1
        lda (ptr1),y            ; read current byte (may already be BRK from bp_patch)
        sta _step_bp+2,x        ; save it
        lda #$00
        sta (ptr1),y            ; write BRK
@next:  inx
        inx
        inx
        inx
        cpx #STEP_SLOTS * STEP_SIZE
        bne @loop
        rts

; ── _dbg_step_unpatch ──────────────────────────────────────────────────
; Restore all patched step BRKs: write saved byte back.
; Called by _dbg_return_common before _dbg_bp_unpatch.
; Clobbers: A, X, Y, ptr1
;
_dbg_step_unpatch:
        ldx #0
        ldy #0
@loop:  lda _step_bp,x
        ora _step_bp+1,x
        beq @next               ; empty slot → skip
        lda _step_bp+3,x
        beq @next               ; disabled → skip
        lda _step_bp,x
        sta ptr1
        lda _step_bp+1,x
        sta ptr1+1
        lda _step_bp+2,x        ; saved byte
        sta (ptr1),y            ; restore it
@next:  inx
        inx
        inx
        inx
        cpx #STEP_SLOTS * STEP_SIZE
        bne @loop
        rts

; ── _dbg_usr_stk_byte ──────────────────────────────────────────────────
; Read one byte from the user stack snapshot in KERNAL RAM ($E200).
; In:  A = stack offset (uint8_t, __fastcall__)
; Out: A = byte at USR_STK + offset
; Clobbers: X
;
_dbg_usr_stk_byte:
        tax                     ; X = offset
        jsr _kernal_bank_out    ; sei + bank out KERNAL
        lda USR_STK,x
        sta _dbg_stk_tmp
        jsr _kernal_bank_in     ; bank in KERNAL + cli
        lda _dbg_stk_tmp
        rts
