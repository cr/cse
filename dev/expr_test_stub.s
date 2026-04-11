; expr_test_stub.s — Test harness for expr.s + symtab.s
;
; Three entry points:
;   expr_test_eval:   call expr_eval, return A = rc (0=ZP, 1=ABS, 2+=error)
;   expr_test_define: call sym_define (sym_name/sym_val/sym_wide set by test)
;   expr_test_clear:  call sym_clear

        .export expr_test_eval
        .export expr_test_define
        .export expr_test_clear
        .export __CODE_RUN__    : absolute = $4000
        .export __ZP_LAST__    : absolute = $0020
        .import expr_eval
        .import sym_define, sym_lookup, sym_clear

        .segment "ZEROPAGE"
        .exportzp expr_ptr, expr_val, expr_wide
        .exportzp asm_pc
        .exportzp sym_name, sym_val, sym_wide
        .exportzp rp_ptr, rp_ptr2, rp_tmp
        .exportzp buf_base

expr_ptr:   .res 2       ; expression input pointer (in/out)
expr_val:   .res 2       ; result value (out)
expr_wide:  .res 1       ; width: 0=ZP, 1=ABS (out)
asm_pc:      .res 2       ; current PC for '*'
asm_cpu:     .res 1       ; CPU mode (unused by expr)
sym_name:   .res 2       ; symbol name pointer
sym_val:    .res 2       ; symbol value
sym_wide:   .res 1       ; symbol width flag: 0=ZP, nonzero=ABS
rp_ptr:     .res 2       ; mem.s scratch
rp_ptr2:    .res 2       ; mem.s scratch
rp_tmp:     .res 1       ; mem.s scratch
buf_base:   .res 2       ; mem.s (define_ws_syms)

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
