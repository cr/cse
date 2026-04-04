; meminfo.s — expose linker segment boundaries as callable functions
;
; The linker defines __MAIN_START__, __BSS_RUN__, __BSS_SIZE__ etc.
; as assembly-level symbols.  We store the values in RODATA and
; provide accessor functions that return them in A/X.

        .export cse_start, cse_end, cse_zp_end
        .import __MAIN_START__
        .import __BSS_RUN__, __BSS_SIZE__
        .import __ZP_LAST__

.segment "RODATA"
_start_val:     .word __MAIN_START__
_end_val:       .word __BSS_RUN__ + __BSS_SIZE__
_zp_end_val:    .byte <(__ZP_LAST__ + 1)

.segment "CODE"

; uint16_t cse_start(void)
cse_start:
        lda _start_val
        ldx _start_val+1
        rts

; uint16_t cse_end(void)
cse_end:
        lda _end_val
        ldx _end_val+1
        rts

; uint8_t cse_zp_end(void) — first free ZP byte
cse_zp_end:
        lda _zp_end_val
        ldx #0
        rts
