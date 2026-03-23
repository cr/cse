; meminfo.s — expose linker symbols to C code
;
; The cc65 linker defines __MAIN_START__, __BSS_RUN__, __BSS_SIZE__
; etc. but they're assembly-level symbols.  C code sees names with
; an extra underscore prefix.  This shim re-exports them.

        .export _cse_start = __MAIN_START__
        .export _cse_end              ; computed below

        .import __MAIN_START__
        .import __BSS_RUN__, __BSS_SIZE__

.segment "RODATA"

; cse_end = __BSS_RUN__ + __BSS_SIZE__  (end of BSS = first free byte)
; We can't do arithmetic on imports in .export, so store as a word.
_cse_end_val:
        .word __BSS_RUN__ + __BSS_SIZE__

.segment "CODE"

; uint16_t cse_end(void) — returns first byte after BSS
_cse_end:
        lda _cse_end_val
        ldx _cse_end_val+1
        rts
