; expr_test_stub.s — Test harness for expr.s + symtab.s
;
; Three entry points:
;   expr_test_eval:   call expr_eval, return A = rc (0=ZP, 1=ABS, 2+=error)
;   expr_test_define: call sym_define (sym_name/sym_val/sym_wide set by test)
;   expr_test_clear:  call sym_clear
;
; ZP variables provided by zp.s (linked into the test binary).

        .export expr_test_eval
        .export expr_test_define
        .export expr_test_clear
        .export __CODE_RUN__    : absolute = $4000
        .import expr_eval
        .import sym_define, sym_lookup, sym_clear

        .segment "CODE"

expr_test_eval:
        jsr expr_eval
        ; A already has the return code (0=ZP, 1=ABS, 2+=error)
        rts

expr_test_define:
        jsr sym_define
        rts

expr_test_clear:
        jsr sym_clear
        rts
