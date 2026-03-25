; mn_classify.s — compile-time mnemonic classifier selector
;
; Provides common entry points that forward to either the 6-bit
; (56-mnemonic legal-NMOS) or the 7-bit (114-mnemonic full) hash
; classifier, depending on the USE_MN6 build define.
;
; Exports:
;   mn_classify   — classify 3-letter mnemonic (JSR entry)
;   mn_base_op    — base opcode table (re-exported alias)
;   mn_profile    — profile table (re-exported alias)
;
; Selection:
;   Default (no define)  →  mn7 (full 114-mnemonic hash)
;   ca65 -D USE_MN6      →  mn6 (legal-NMOS 56-mnemonic hash)

        .export mn_classify

.ifdef USE_MN6
        .import mn6_classify
        .import mn6_base_op, mn6_profile
        mn_base_op = mn6_base_op
        mn_profile = mn6_profile
.else
        .import mn7_classify
        .import mn7_base_op, mn7_profile
        mn_base_op = mn7_base_op
        mn_profile = mn7_profile
.endif

        .export mn_base_op, mn_profile

.segment "CODE"

mn_classify:
.ifdef USE_MN6
        jmp     mn6_classify
.else
        jmp     mn7_classify
.endif
