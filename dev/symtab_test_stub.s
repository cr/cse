; symtab_test_stub.s — Test harness for symtab.s
;
; 12 bytes each: JSR(3) + LDA(2) + BCC(2) + LDA(2) + STA_ZP(2) + RTS(1)

        .export test_define, test_lookup, test_clear
        .export __CODE_RUN__    : absolute = $4000
        .export __ZP_LAST__    : absolute = $0020
        .exportzp sym_name, sym_val, sym_wide
        .exportzp rp_ptr, rp_ptr2, rp_tmp
        .exportzp buf_base

        .import sym_define, sym_lookup, sym_clear

.segment "ZEROPAGE"
sym_name:  .res 2
sym_val:   .res 2
sym_wide:  .res 1
rp_ptr:    .res 2
rp_ptr2:   .res 2
rp_tmp:    .res 1
buf_base:  .res 2

.segment "CODE"

test_define:
        jsr sym_define
        lda #0
        bcc :+
        lda #1
:       sta $F4
        rts

test_lookup:
        jsr sym_lookup
        lda #0
        bcc :+
        lda #1
:       sta $F4
        rts

test_clear:
        jmp sym_clear
