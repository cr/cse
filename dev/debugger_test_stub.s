; debugger_test_stub.s — Test harness stub for debugger.s
;
; Provides a thin entry point that Python calls to exercise
; _dbg_init, _dbg_bp_set, _dbg_bp_del, _dbg_bp_clear, _dbg_bp_count.
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
;
; Result: A on return (slot# for set, count for count, etc.)
;         Carry in bit 0 of $0B03 (result flags)

        .export dbg_test_entry

        .import _dbg_init
        .import _dbg_bp_set, _dbg_bp_del, _dbg_bp_clear
        .import _dbg_bp_count
        .import _bp_table
        .import _dbg_running, _dbg_reason, _brk_pc, _dbg_bp_hit

CMD     = $0B00
ARG1    = $0B01
ARG2    = $0B02
RFLAGS  = $0B03

.segment "CODE"

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
        sta RFLAGS+1            ; slot# in RFLAGS+1 ($0B04)
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
        ; A = count, store at RFLAGS+1
        sta RFLAGS+1
        rts
.endproc
