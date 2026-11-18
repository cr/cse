; ============================================================
; Owner: doc/modules/mn_classify.md
; mn6.s -- 6-bit perfect hash mnemonic classifier (legal NMOS only)
; ============================================================
;
; Identifies the 56 standard NMOS 6502 legal mnemonics via a
; collision-free 6-bit hash with a single-byte fingerprint check.
;
; Algorithm
; ---------
;   hash slot:   h6 = (c1*8 + c3*15 + mn6_hash_t[c2]) & $3F
;   fingerprint: mn6_fp[h6] == (c1 + c2*218) & $FF
;
; where c1/c2/c3 are the normalized letter values (AND #$1F) of the
; first, middle, and last letters of the three-character mnemonic.
;
; Character encoding
; ------------------
; Normalized values:  A=1 .. Z=26  (AND #$1F maps PETSCII upper/lower
; and VICII screencodes identically; see mn_classify.md)
;
; Calling convention
; ------------------
; 1. Store the three normalized letter values in mn_c1 / mn_c2 / mn_c3.
; 2. JSR mn6_classify.
; 3. On return:
;      C = 0  →  recognised legal NMOS mnemonic;  A = hash slot (0..$3F)
;      C = 1  →  not recognised;  A = undefined
;    On success the caller may index mn6_base_op / mn6_profile
;    (exported from mn6_tables.s) with the returned slot.
; Clobbers: A, X, Y, mn6_h_tmp.
;
; Hash arithmetic – carry analysis
; ---------------------------------
;   c1×8:      c1 ≤ 26 → 208 max  (3 ASLs; no carry out)
;   c3×16:     c3 ≤ 26 → 416; overflows for c3 ≥ 16 (carry out of 4th ASL)
;   c3×15:     SEC;SBC mn_c3: (c3×16 mod 256) - c3 = c3×15 mod 256  ✓
;              c3×15 ≤ 390 → mod 256 ≤ 134; SEC/SBC leaves carry undefined
;   +c1×8:     CLC required — SEC/SBC leaves carry undefined
;   +T[c2]:    c1×8+c3×15 (mod 256) max 208+134=342; may overflow 8 bits
;              CLC required before this ADC
;   AND #$3F:  256≡0 (mod 64), so any overflow is absorbed correctly
;
; Two CLC instructions are required:
;   1. CLC before  ADC mn6_h_tmp    — SEC/SBC (c3×15) leaves carry set/clear
;   2. CLC before  ADC mn6_hash_t,Y — c1×8+c3×15 (mod 256) may set carry
; Without either CLC, mnemonics with large c1/c3 values receive wrong slots.
; See dev/mn6_fingerprint_collisions.txt for the carry-correctness analysis.
;
; Fingerprint design
; ------------------
; fp = (c1 + c2*218) & $FF.  A=1 ⟹ the c1 term costs nothing extra — just
; load mn_c1 directly.  c2*218 mod 256 is read from the 27-byte mn6_fp_c2
; table (Y still holds mn_c2 from the hash computation).
;
; 16 false positives remain out of 17,576 possible 3-letter strings (0.09%).
; All differ from every legal mnemonic in all 3 characters (Hamming=3).
; All are at weighted QWERTY distance ≥ 1.5 from every legal mnemonic —
; two independent key errors are required to produce any false positive.
; See dev/mn6_fingerprint_collisions.txt for the complete list.
;
; Table sizes  (mn6_tables.s is generated; do not edit by hand)
;   mn6_hash_t   27 bytes  (mn6_tables.s, generated)
;   mn6_fp_c2    27 bytes  (mn6_tables.s, generated)
;   mn6_fp       64 bytes  (mn6_tables.s)
;   mn6_base_op  64 bytes  (mn6_tables.s)
;   mn6_profile  64 bytes  (mn6_tables.s)
;   mn6_h_tmp     1 byte   (ZEROPAGE)
;   Total: mn6_tables.s 54 + 192 = 246 bytes, + 1 ZP byte
; ============================================================

        .export mn6_classify
        .importzp mn_c1, mn_c2, mn_c3, mn6_h_tmp
        .import mn6_fp, mn6_hash_t, mn6_fp_c2

; ------------------------------------------------------------
; mn6_classify
; ------------------------------------------------------------
.segment "CODE"

mn6_classify:
        ; ── c1 × 8 ────────────────────────────────────────────────
        lda     mn_c1
        asl     a               ; c1×2   (max  52, carry=0)
        asl     a               ; c1×4   (max 104, carry=0)
        asl     a               ; c1×8   (max 208, carry=0)
        sta     mn6_h_tmp       ; save c1×8 for later addition

        ; ── c3 × 15 = c3×16 − c3 ─────────────────────────────────
        lda     mn_c3
        asl     a               ; c3×2
        asl     a               ; c3×4
        asl     a               ; c3×8
        asl     a               ; c3×16  (overflows for c3≥16; carry undefined)
        sec                     ; ensure borrow=0 for SBC
        sbc     mn_c3           ; c3×15 mod 256  (carry now undefined)

        ; ── + c1×8 ────────────────────────────────────────────────
        clc                     ; SEC/SBC leaves carry undefined
        adc     mn6_h_tmp       ; c3×15 + c1×8  (may overflow 8 bits)

        ; ── + T[c2] ───────────────────────────────────────────────
        ldy     mn_c2
        clc                     ; c1×8+c3×15 may have set carry
        adc     mn6_hash_t,y    ; + T[c2]  (h6 raw; overflow absorbed by AND)
        and     #$3F            ; 6-bit slot  (0..$3F)
        tax                     ; X = slot

        ; ── single-byte fingerprint: fp = (c1 + c2*218) & $FF ────
        ; A=1 ⟹ c1 term is free — load mn_c1 directly, no multiply.
        ; mn6_fp_c2[c2] = (c2*218)&$FF; Y still holds mn_c2 from above.
        ;
        ; Empty-slot guard: mn6_fp uses $00 as the empty-slot sentinel, but
        ; fp=0 is reachable for (c1=J,c2=G) and (c1=T,c2=N).  No legal NMOS
        ; mnemonic produces fp=0, so we can safely reject any slot whose
        ; stored fingerprint is $00 before doing the comparison.
        lda     mn_c1
        clc
        adc     mn6_fp_c2,y     ; A = computed fp = c1 + (c2×218 mod 256)
        sta     mn6_h_tmp       ; save computed fp (c1×8 no longer needed)
        lda     mn6_fp,x        ; stored fp  ($00 = empty slot)
        beq     @invalid        ; empty slot — reject immediately
        cmp     mn6_h_tmp       ; stored == computed?
        bne     @invalid

        txa                     ; A = slot
        clc                     ; C=0: recognised legal NMOS mnemonic
        rts

@invalid:
        sec                     ; C=1: not recognised
        rts
