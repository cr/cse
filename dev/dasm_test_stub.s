; dasm_test_stub.s — test harness for disassembler in py65
;
; Entry point: jsr $0600
;   Before call:
;     $00F0/$00F1 = pointer to instruction bytes
;   After return:
;     A = instruction length returned by _disasm
;     Screen RAM at $0400+ contains the disassembled text

        .export dasm_test_entry

        .import _dasm_insn
        .import _io_sync
        .import scr_lo, scr_hi
        .import kplot_stub

.segment "CODE"

dasm_test_entry:
        ; Reset cursor to 0,0
        lda #0
        sta $D3                 ; CUR_COL
        sta $D6                 ; CUR_ROW
        ; Sync KERNAL line pointers
        clc
        ldx #0
        ldy #0
        jsr $FFF0               ; KERNAL PLOT (uses kplot_stub)

        ; Clear first screen row
        ldy #39
        lda #$20
@clr:   sta $0400,y
        dey
        bpl @clr

        ; Call disassembler: addr in A/X (lo/hi) -- __fastcall__
        lda $F0                 ; ptr lo
        ldx $F1                 ; ptr hi
        jsr _dasm_insn

        ; A = instruction length, return it
        rts
