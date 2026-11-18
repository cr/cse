; macros.inc — shared assembler macros for CSE
; Owner: doc/modules/log.md
;
; Include with `.include "macros.inc"` after `.setcpu` and before
; any code that uses these macros.

; ── puts: print an inline RODATA string ────────────────────
; Saves 2 bytes per call site over the explicit
;     lda #<str ; ldx #>str ; jsr io_puts
; triple.  Implementation lives in repl.s::puts_imm and is
; imported by users.
.macro puts str
        jsr puts_imm
        .word str
.endmacro
