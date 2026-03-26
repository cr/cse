; expr_test_stub.s — Test harness for expr.s + symtab.s
;
; Three entry points:
;   expr_test_eval:   call _expr_eval, return A = rc (0=ZP, 1=ABS, 2+=error)
;   expr_test_define: call _sym_define (sym_name/sym_val/sym_wide set by test)
;   expr_test_clear:  call _sym_clear

        .export expr_test_eval
        .export expr_test_define
        .export expr_test_clear
        .export cse_popax

        .import _expr_eval
        .import _sym_define, _sym_lookup, _sym_clear

        .segment "ZEROPAGE"
        .exportzp expr_ptr, expr_val, expr_wide
        .exportzp al_pc
        .exportzp sym_name, sym_val, sym_wide

expr_ptr:   .res 2       ; expression input pointer (in/out)
expr_val:   .res 2       ; result value (out)
expr_wide:  .res 1       ; width: 0=ZP, 1=ABS (out)
al_pc:      .res 2       ; current PC for '*'
al_cpu:     .res 1       ; CPU mode (unused by expr)
sym_name:   .res 2       ; symbol name pointer
sym_val:    .res 2       ; symbol value
sym_wide:   .res 1       ; symbol width flag: 0=ZP, nonzero=ABS

        .segment "CODE"

expr_test_eval:
        jsr _expr_eval
        ; A already has the return code (0=ZP, 1=ABS, 2+=error)
        rts

expr_test_define:
        jsr _sym_define
        rts

expr_test_clear:
        jsr _sym_clear
        rts

cse_popax:
        rts
