; symtab_test_stub.s — Test harness for symtab.s

        .export test_define, test_lookup, test_clear
        .exportzp sym_name, sym_val, sym_wide

        .import _sym_define, _sym_lookup, _sym_clear

.segment "ZEROPAGE"
sym_name:  .res 2      ; pointer to NUL-terminated name string
sym_val:   .res 2      ; value (16-bit)
sym_wide:  .res 1      ; ZP/ABS flag (0=ZP, nonzero=ABS)

.segment "CODE"

; 12 bytes each: JSR(3) + LDA(2) + BCC(2) + LDA(2) + STA_ZP(2) + RTS(1)
test_define:
        jsr _sym_define
        lda #0
        bcc :+
        lda #1
:       sta $F4
        rts

test_lookup:
        jsr _sym_lookup
        lda #0
        bcc :+
        lda #1
:       sta $F4
        rts

test_clear:
        jmp _sym_clear
