; expr_test_stub.s — Test harness for expr.s + symtab.s
;
; ZP interface (no C stack):
;   $F0/$F1 = expr_ptr: input string pointer (in/out)
;   $F2/$F3 = expr_val: result value (out)
;   $F4/$F5 = asm_pc:   current PC for '*' (in)
;   $F6     = al_cpu:   CPU mode (in)
;
; Three entry points:
;   expr_test_eval:   call _expr_eval, return C flag + A = error code
;   expr_test_define: call _sym_define (sym_name/sym_val already set)
;   expr_test_clear:  call _sym_clear

        .export expr_test_eval
        .export expr_test_define
        .export expr_test_clear

        .export cse_popax         ; stub (unused but imported by old expr.s)

        .import _expr_eval
        .import _sym_define, _sym_lookup, _sym_clear

        ; Re-export sym_name/sym_val so tests can set them
        .exportzp sym_name, sym_val

        ; ZP layout — shared with test runner
        .segment "ZEROPAGE"
        .exportzp expr_ptr, expr_val, al_pc
        .exportzp sym_name, sym_val
expr_ptr:  .res 2       ; expression input pointer
expr_val:  .res 2       ; result
al_pc:     .res 2       ; current PC (aliased as asm_pc in expr.s)
al_cpu:    .res 1       ; $F6 — CPU mode
sym_name:  .res 2       ; $F8/$F9 — symbol name pointer (for define/lookup)
sym_val:   .res 2       ; $FA/$FB — symbol value (for define/lookup)

        .segment "CODE"

; ── Entry points (labels at file scope for export) ────────
expr_test_eval:
        jsr _expr_eval
        rts

expr_test_define:
        jsr _sym_define
        rts

expr_test_clear:
        jsr _sym_clear
        rts

cse_popax:
        rts
