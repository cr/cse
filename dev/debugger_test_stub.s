; debugger_test_stub.s — Test harness stub for debugger.s
;
; Protocol: Python writes a command byte + arguments to fixed addresses,
; then JSRs to dbg_test_entry.  The stub dispatches based on the command.
;
; Commands (at $0B00):
;   $00 = dbg_init
;   $01 = bp_set:   addr at $0B01/$0B02 (lo/hi)
;   $02 = bp_del:   slot# at $0B01
;   $03 = bp_clear
;   $04 = bp_count
;   $05 = bp_patch
;   $06 = bp_unpatch
;   $07 = bp_find:  addr at $0B01/$0B02 (lo/hi)
;
; Result: A on return; $0B03 = flags (bit 0 = carry)
;         $0B04 = result value (slot#, count, etc.)

        .export dbg_test_entry

        .import _dbg_init
        .import _dbg_bp_set, _dbg_bp_del, _dbg_bp_clear
        .import _dbg_bp_count
        .import _dbg_bp_patch, _dbg_bp_unpatch
        .import _dbg_bp_find
        .import _bp_table
        .import _dbg_running, _dbg_reason, _brk_pc, _dbg_bp_hit

        .exportzp ptr1          ; provide cc65 scratch pointer for debugger.s
        .export _reg_a, _reg_x, _reg_y, _reg_sp, _reg_p
        .export _zp_save_buf
        .export _kernal_bank_out, _kernal_bank_in

.segment "ZEROPAGE"
ptr1:   .res 2                  ; cc65 scratch pointer

.segment "BSS"
_reg_a:         .res 1
_reg_x:         .res 1
_reg_y:         .res 1
_reg_sp:        .res 1
_reg_p:         .res 1
_zp_save_buf:   .res 91         ; ZP save buffer (matches asm_bridge.s)

.segment "CODE"

CMD     = $0B00
ARG1    = $0B01
ARG2    = $0B02
RFLAGS  = $0B03
RVAL    = $0B04

; ── Entry point MUST be first in this module's CODE ──
.proc dbg_test_entry
        lda CMD
        beq @init
        cmp #$01
        beq @set
        cmp #$02
        beq @del
        cmp #$03
        beq @clear
        cmp #$04
        beq @count
        cmp #$05
        beq @patch
        cmp #$06
        beq @unpatch
        cmp #$07
        beq @find
        rts                     ; unknown command

@init:  jsr _dbg_init
        rts

@set:   lda ARG1                ; addr lo
        ldx ARG2                ; addr hi
        jsr _dbg_bp_set
        bcc @set_ok
        lda #$01
        sta RFLAGS              ; C=1 → table full
        rts
@set_ok:
        sta RVAL                ; slot#
        lda #$00
        sta RFLAGS              ; C=0 → success
        rts

@del:   lda ARG1                ; slot#
        jsr _dbg_bp_del
        bcc @del_ok
        lda #$01
        sta RFLAGS
        rts
@del_ok:
        lda #$00
        sta RFLAGS
        rts

@clear: jsr _dbg_bp_clear
        rts

@count: jsr _dbg_bp_count
        sta RVAL
        rts

@patch: jsr _dbg_bp_patch
        rts

@unpatch:
        jsr _dbg_bp_unpatch
        rts

@find:  lda ARG1                ; addr lo
        ldx ARG2                ; addr hi
        jsr _dbg_bp_find
        bcc @find_ok
        lda #$01
        sta RFLAGS              ; C=1 → not found
        lda #$FF
        sta RVAL
        rts
@find_ok:
        sta RVAL                ; slot#
        lda #$00
        sta RFLAGS
        rts
.endproc

; Stubs for KERNAL banking (no-ops in test environment)
_kernal_bank_out:
_kernal_bank_in:
        rts
