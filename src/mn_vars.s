; mn_vars.s — shared zero-page mnemonic classifier inputs
;
; Provides the three VICII-screencode input registers consumed by
; both mn6_classify (mn6.s) and mn7_classify (mn7.s).
;
; Calling convention (both classifiers):
;   Store the first / middle / last letter screencodes in
;   mn_c1 / mn_c2 / mn_c3, then JSR mn6_classify or mn7_classify.
;
; VICII screencodes: A=$01 .. Z=$1A  (1-based; 0 = unused guard)

        .importzp mn_c1, mn_c2, mn_c3
