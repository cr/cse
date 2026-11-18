; m65_macros_test.s – the m65 bodies of platform.inc's macros, for T7.
; Owner: doc/platform_layer.md
;
; Assembled with -DPLATFORM_M65 and linked by dev/m65_test.cfg;
; tests/unit/test_platform_m65.py runs each entry on M65Emu in clean
; mode with B = CSE_BP, as kernel code runs.

        .setcpu "6502"
        .include "platform.inc"

        .segment "ZEROPAGE"
        FAR_PTR fp

        .segment "BSS"
seen:   .res 5                  ; what fake_entry found: A X Y P B

        .segment "CODE"

; A stand-in KERNAL entry: records A, X, Y, P and B as it finds them,
; returns A = $5A, X = $A5, Y = $3C, C = 1.
fake_entry:
        php
        sta seen+0
        stx seen+1
        sty seen+2
        pla
        sta seen+3
        .byte $7B               ; TBA (test code: the raw-byte rule is src/'s)
        sta seen+4
        lda #$5A
        ldx #$A5
        ldy #$3C
        sec
        rts

t_kcall:
        KCALL fake_entry
        rts

t_kjmp:
        KJMP fake_entry

t_far_lda:
        FAR_LDA fp
        rts

t_far_sta:
        FAR_STA fp
        rts

t_far_ora:
        FAR_ORA fp
        rts

t_far_bank:
        FAR_BANK fp, BANK_SRC
        rts

t_setbnk:
        PLAT_SETBNK
        rts
