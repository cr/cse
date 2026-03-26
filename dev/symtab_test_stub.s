; symtab_test_stub.s — Test harness for symtab.s
;
; Entry points:
;   test_define:   JSR sym_define, capture carry → $F4
;   test_lookup:   JSR sym_lookup, capture carry → $F4
;   test_clear:    JSR sym_clear

        .export test_define, test_lookup, test_clear
        .exportzp sym_name, sym_val, sym_wide
        .exportzp sp

        .import _sym_define, _sym_lookup, _sym_clear

.segment "ZEROPAGE"
sp:        .res 2      ; cc65 C stack pointer (unused)
sym_name:  .res 2      ; pointer to NUL-terminated name string
sym_val:   .res 2      ; value (16-bit)
sym_wide:  .res 1      ; width flag: 0=ZP, nonzero=ABS

.segment "CODE"

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
