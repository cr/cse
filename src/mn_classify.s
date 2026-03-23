; mn_classify.s — compile-time mnemonic classifier selector
;
; Provides a single entry point  mn_classify  that forwards to
; either the 6-bit (56-mnemonic legal-NMOS) or the 7-bit
; (114-mnemonic full) hash classifier.
;
; Selection
; ---------
;   Default (no define)  →  mn7_classify  (full 114-mnemonic hash)
;   ca65 -D USE_MN6      →  mn6_classify  (legal-NMOS 56-mnemonic hash)
;
; Calling convention (unchanged regardless of variant):
;   Store VICII screencodes in mn_c1 / mn_c2 / mn_c3, then JSR mn_classify.
;   On return: C=0 → recognised, A = hash slot; C=1 → not recognised.
;
; The JMP trampoline costs 3 bytes and 3 cycles — negligible in context.

        .export mn_classify

.ifdef USE_MN6
        .import mn6_classify
.else
        .import mn7_classify
.endif

.segment "CODE"

mn_classify:
.ifdef USE_MN6
        jmp     mn6_classify
.else
        jmp     mn7_classify
.endif
