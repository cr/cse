; debugger.s — Breakpoints, tracing, and execution control
;
; Phase A: breakpoint table management (bp_set, bp_del, bp_clear, bp_count)
; Phase B: BRK handler, context switch, NMI upgrade (planned)
; Phase C: single-step t/n (planned)
;
; Breakpoint table: 8 slots × 4 bytes = 32 bytes BSS
;   Offset 0: addr lo
;   Offset 1: addr hi
;   Offset 2: saved byte (original opcode at addr)
;   Offset 3: flags (bit 0 = enabled)
;   addr=$0000 marks an empty slot.
;
; See doc/modules/debugger.md for full design.

        .setcpu "6502"

        .export _dbg_init
        .export _dbg_bp_set, _dbg_bp_del, _dbg_bp_clear
        .export _dbg_bp_count
        .export _dbg_bp_patch, _dbg_bp_unpatch
        .export _dbg_bp_find
        .export _bp_table
        .export _dbg_running, _dbg_reason, _brk_pc, _dbg_bp_hit

        .importzp ptr1          ; cc65 scratch pointer ($4E/$4F)

BP_SLOTS = 8
BP_SIZE  = 4            ; bytes per slot

; ── BSS ────────────────────────────────────────────────────────────────
.segment "BSS"

_bp_table:      .res BP_SLOTS * BP_SIZE ; 32 bytes: 8 slots × 4

_dbg_running:   .res 1          ; $80 = user code active, 0 = REPL
_dbg_reason:    .res 1          ; why we returned (0=none, 1=BRK, 2=NMI, 3=RTS)
_brk_pc:        .res 2          ; PC where break occurred / resume address
_dbg_bp_hit:    .res 1          ; slot# of breakpoint that was hit ($FF = none)

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
