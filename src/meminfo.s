; meminfo.s — expose linker segment boundaries to C code
;
; The cc65 linker defines __MAIN_START__, __BSS_RUN__, __BSS_SIZE__
; etc. as assembly-level symbols.  C sees names with an underscore
; prefix, and treats them as addresses of variables — not the values
; themselves.  So we store the values in RODATA and provide accessor
; functions.

        .export _cse_start, _cse_end, _cse_zp_end
        .import __MAIN_START__
        .import __BSS_RUN__, __BSS_SIZE__
        .import __ZP_LAST__

.segment "RODATA"
_start_val:     .word __MAIN_START__
_end_val:       .word __BSS_RUN__ + __BSS_SIZE__
_zp_end_val:    .byte <(__ZP_LAST__ + 1)

.segment "CODE"

; uint16_t cse_start(void)
_cse_start:
        lda _start_val
        ldx _start_val+1
        rts

; uint16_t cse_end(void)
_cse_end:
        lda _end_val
        ldx _end_val+1
        rts

; uint8_t cse_zp_end(void) — first free ZP byte
_cse_zp_end:
        lda _zp_end_val
        ldx #0
        rts
