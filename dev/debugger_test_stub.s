; debugger_test_stub.s — Test harness stub for debugger.s
;
; Protocol: Python writes a command byte + arguments to fixed addresses,
; then JSRs to dbg_test_entry.  The stub dispatches based on the command.
;
; Scope (post-Phase-18): breakpoint-table CRUD only.  The old @enter
; command (dbg_enter / two-image swap) is gone; kernel-transition
; behaviour is covered by test_kernel_transition.py using C64Emu +
; full PRG instead.
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

        .import dbg_init
        .import dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .import dbg_bp_count
        .import patch_all, unpatch_all
        .import dbg_bp_find
        .import bp_table, step_bp
        .import brk_pc, dbg_bp_hit
        .importzp dbg_reason, in_userland     ; zp.s (Phase 21 Move 4)

        .export reg_a, reg_x, reg_y, reg_sp, reg_p
        .export kernel_zp_buf, userland_zp_buf
        .export kernal_bank_out, kernal_bank_in
        .export save_userland_zp, restore_userland_zp
        .export save_kernel_zp, restore_kernel_zp
        ; in_userland now lives in zp.s (Phase 21 Move 4); this stub
        ; no longer defines it.  kernel_zp_buf / userland_zp_buf /
        ; save/restore helpers remain local stubs because mem.s is
        ; not linked into the debugger test bundle.

.segment "BSS"
reg_a:         .res 1
reg_x:         .res 1
reg_y:         .res 1
reg_sp:        .res 1
reg_p:         .res 1
kernel_zp_buf:   .res 128        ; ZP save buffer ($00..$7F inclusive,
                                 ;  matches debugger.s::ZP_SAVE_LEN)
userland_zp_buf:   .res 128        ; user ZP snapshot (same size)

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

@init:  jmp dbg_init

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

; Stubs for KERNAL banking (no-ops in test environment)
kernal_bank_out:
kernal_bank_in:
        rts

; Stubs for the four ZP save/restore primitives (no-ops — the
; bp-table CRUD tests never exercise userland transitions).
save_userland_zp:
restore_userland_zp:
save_kernel_zp:
restore_kernel_zp:
        rts
