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

        .exportzp mn_c1, mn_c2, mn_c3

.segment "ZEROPAGE"

mn_c1:  .res 1          ; first  letter VICII screencode  (1=A .. 26=Z)
mn_c2:  .res 1          ; middle letter VICII screencode
mn_c3:  .res 1          ; last   letter VICII screencode
