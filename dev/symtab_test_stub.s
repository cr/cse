; symtab_test_stub.s — Test harness for symtab.s
;
; ZP variables provided by zp.s (linked into the test binary).

        .export test_define, test_lookup, test_clear
        .export __CODE_RUN__    : absolute = $4000

        .import sym_define, sym_lookup, sym_clear

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
