; mn_vars.s — mnemonic classifier inputs (calling convention only)
; Owner: doc/modules/mn_classify.md
;
; Defines and emits nothing: the three inputs mn_c1 / mn_c2 / mn_c3
; are ZP variables of zp.s, consumed by mn6_classify (mn6.s) and
; mn7_classify (mn7.s).
;
; Calling convention (both classifiers):
;   Store the first / middle / last letter, normalized to 1..26
;   (A=1 .. Z=26), in mn_c1 / mn_c2 / mn_c3, then JSR mn_classify.

        .importzp mn_c1, mn_c2, mn_c3
