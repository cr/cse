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
;   $08 = dbg_enter (caller pre-loads brk_pc, reg_*, step_bp, etc.)
;
; Result: A on return; $0B03 = flags (bit 0 = carry)
;         $0B04 = result value (slot#, count, etc.)

        .export dbg_test_entry

        .import dbg_init
        .import dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .import dbg_bp_count
        .import patch_all, unpatch_all
        .import dbg_bp_find
        .import dbg_enter
        .import dbg_brk_core
        .import bp_table, step_bp
        .import dbg_running, dbg_reason, brk_pc, dbg_bp_hit

        .export reg_a, reg_x, reg_y, reg_sp, reg_p
        .export zp_save_buf, user_zp_buf
        .export kernal_bank_out, kernal_bank_in

.segment "BSS"
reg_a:         .res 1
reg_x:         .res 1
reg_y:         .res 1
reg_sp:        .res 1
reg_p:         .res 1
zp_save_buf:   .res 128        ; ZP save buffer ($00..$7F inclusive,
                                 ;  matches debugger.s::ZP_SAVE_LEN)
user_zp_buf:   .res 128        ; user ZP snapshot (same size)

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
        cmp #$08
        beq @enter
        rts                     ; unknown command

@init:  jsr dbg_init
        ; Install BRK handler at $0316 — dbg_enter no longer does this.
        ; CSE production code has cse_brk_handler (main.s) permanently
        ; installed; in tests we point directly to dbg_brk_core.
        lda #<dbg_brk_core
        sta $0316
        lda #>dbg_brk_core
        sta $0317
        rts

@set:   lda ARG1                ; addr lo
        ldx ARG2                ; addr hi
        jsr dbg_bp_set
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
        jsr dbg_bp_del
        bcc @del_ok
        lda #$01
        sta RFLAGS
        rts
@del_ok:
        lda #$00
        sta RFLAGS
        rts

@clear: jsr dbg_bp_clear
        rts

@count: jsr dbg_bp_count
        sta RVAL
        rts

@patch: jsr patch_all
        rts

@unpatch:
        jsr unpatch_all
        rts

@find:  lda ARG1                ; addr lo
        ldx ARG2                ; addr hi
        jsr dbg_bp_find
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

@enter: jsr dbg_enter
        rts
.endproc

; Stubs for KERNAL banking (no-ops in test environment)
kernal_bank_out:
kernal_bank_in:
        rts
