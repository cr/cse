; symtab_test_stub.s — Test harness for symtab.s
;
; 12 bytes each: JSR(3) + LDA(2) + BCC(2) + LDA(2) + STA_ZP(2) + RTS(1)

        .export test_define, test_lookup, test_clear
        .exportzp sym_name, sym_val, sym_wide

        .import sym_define, sym_lookup, sym_clear

.segment "ZEROPAGE"
sym_name:  .res 2
sym_val:   .res 2
sym_wide:  .res 1

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
