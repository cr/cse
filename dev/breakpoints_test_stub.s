; breakpoints_test_stub.s — Test harness stub for breakpoints.s (L3)
;
; Protocol: Python writes a command byte + arguments to fixed addresses,
; then JSRs to bp_test_entry.  The stub dispatches based on the command.
;
; Scope: breakpoint-table CRUD only.  The L3 breakpoints.s module is
; pure data-structure manipulation — no KERNAL, no vectors, no
; userland transitions.  Kernel-transition behaviour lives in
; debugger.s (L4) and is covered by test_kernel_transition.py using
; C64Emu + full PRG.
;
; Renamed from debugger_test_stub.s at the 2026-04-20 debugger split
; (structural refactor that extracted breakpoint-table CRUD into its
; own L3 module).  The bundle now links breakpoints.s + zp.s only —
; no reg_*/kernel_zp_buf/kernal_bank_out stubs needed because
; breakpoints.s doesn't reference those symbols.
;
; Commands (at $0B00):
;   $00 = bp_init
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

        .export bp_test_entry

        .import bp_init
        .import dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .import dbg_bp_count
        .import patch_all, unpatch_all
        .import dbg_bp_find
        .import bp_table, step_bp
        .import dbg_bp_hit

.segment "CODE"

CMD     = $0B00
ARG1    = $0B01
ARG2    = $0B02
RFLAGS  = $0B03
RVAL    = $0B04

; ── Entry point MUST be first in this module's CODE ──
.proc bp_test_entry
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

@init:  jmp bp_init

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

@clear: jmp dbg_bp_clear

@count: jsr dbg_bp_count
        sta RVAL
        rts

@patch: jmp patch_all

@unpatch:
        jmp unpatch_all

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
.endproc
