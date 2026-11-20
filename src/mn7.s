; ============================================================
; Owner: doc/modules/mn_classify.md
; mn7.s -- 7-bit perfect hash mnemonic classifier
; ============================================================
;
; Identifies the keys of the build's mn7 CPU set (mn_classify.md
; § Variants: 102 on c64-6510, 68 in the CMOS mode, 98 on m65) via a
; collision-free 7-bit hash with a zero-false-positive bit-pack
; fingerprint; the C64 blocks share one T over all 114 C64 names.
;
; Algorithm
; ---------
;   hash slot:   h7 = (c1*4 + c3 + mn7_hash_t[c2]) & $7F
;   fingerprint: fp = (c2<<3) | (c3>>2)
;
; where c1/c2/c3 are the normalized letter values (1..26) of the
; first, middle, and last letters of the three-character mnemonic.
;
; Character encoding
; ------------------
; Normalized values:  A=1 .. Z=26  (asm_line's _asm_rd_upper maps the
; PETSCII letters onto them and refuses anything else; see mn_classify.md)
; mn7_hash_t[0] = $FF fills the never-read index 0.
;
; Calling convention
; ------------------
; 1. Store the three normalized letter values in mn_c1 / mn_c2 / mn_c3.
; 2. JSR mn7_classify.
; 3. On return:
;      C = 0  →  recognised mnemonic;  A = hash slot (0..$7D)
;      C = 1  →  not recognised;  A = undefined
;    On success the caller may index mn7_base_op / mn7_profile
;    (exported from mn7_tables.s) with the returned slot.
; Clobbers: A, X, Y, mn7_h_tmp.
;
; Hash arithmetic – carry analysis
; ---------------------------------
;   c1×4:     c1 ≤ 26 → 104 max  (2 ASLs; bit 7 never set, no carry)
;   +c3:      c1×4+c3 ≤ 130      (ADC; no carry in, result < 256)
;   +T[c2]:   c1×4+c3+T[c2] ≤ 257; may overflow 8 bits
;             256 ≡ 0 (mod 128), so AND $7F absorbs the carry correctly.
;             NO CLC required anywhere in the hash sequence.
;
; Fingerprint design
; ------------------
; fp = (c2<<3) | (c3>>2):
;   bits 7–3 ← low 5 bits of c2  (c2 ≤ 26, fits in 5 bits)
;   bits 2–0 ← c3>>2             (c3 ≤ 26 → c3>>2 ≤ 6; 3 bits)
; c2<<3 always has bits 0–2 clear; c3>>2 ≤ 6 < 8 so OR is a clean pack.
; c2 ≥ 1 ⟹ fp ≥ 8; the $00 empty-slot sentinel in mn7_fp is unreachable.
; No carry, no CLC: 2 LSR + STA + 3 ASL + ORA + CMP (9 instructions total).
; TYA saves one instruction since Y = mn_c2 after the hash table lookup.
; Zero false positives over all 17,576 three-letter strings.
;
; Table sizes  (mn7_tables.s is generated; do not edit by hand)
;   mn7_hash_t  27 bytes  (mn7_tables.s, generated)
;   mn7_fp     128 bytes  (mn7_tables.s)
;   mn7_base_op 128 bytes  (mn7_tables.s)
;   mn7_profile 128 bytes  (mn7_tables.s)
;   mn7_h_tmp    1 byte   (zp.s)
;   Total: mn7_tables.s 27 + 384 = 411 bytes, + 1 ZP byte
; ============================================================

        .export mn7_classify
        .importzp mn_c1, mn_c2, mn_c3
        .import mn7_fp, mn7_hash_t

        .importzp mn7_h_tmp

; ------------------------------------------------------------
; mn7_classify
; ------------------------------------------------------------
.segment "CODE"

mn7_classify:
        ; ── fingerprint low bits: c3>>2 ───────────────────────
        ; Computed first so A is free for the hash calculation.
        lda     mn_c3
        lsr     a               ; c3>>1
        lsr     a               ; c3>>2  (0..6; bits 0–2 only)
        sta     mn7_h_tmp       ; save for fingerprint OR

        ; ── hash: c1*4 + c3 + T[c2] ───────────────────────────
        lda     mn_c1
        asl     a               ; c1*2   (max  52, carry=0)
        asl     a               ; c1*4   (max 104, carry=0)
        adc     mn_c3           ; c1*4+c3   (max 130, carry=0)
        ldy     mn_c2           ; Y = c2 for table index
        adc     mn7_hash_t,y    ; + T[c2]  (max 257; overflow absorbed by AND)
        and     #$7F            ; 7-bit slot  (0..$7F)
        tax                     ; X = slot

        ; ── fingerprint: fp = (c2<<3) | (c3>>2) ──────────────
        ; Y still holds mn_c2 from above; TYA saves an LDA.
        ; c2<<3: c2 ≤ 26 → 3 ASLs never set carry.
        ; OR with c3>>2 is clean (no bit overlap).
        tya                     ; A = c2
        asl     a               ; c2<<1  (max  52, carry=0)
        asl     a               ; c2<<2  (max 104, carry=0)
        asl     a               ; c2<<3  (max 208, carry=0)
        ora     mn7_h_tmp       ; | (c3>>2)
        cmp     mn7_fp,x        ; compare with stored fingerprint
        bne     @invalid

        txa                     ; A = slot
        clc                     ; C=0: recognised mnemonic
        rts

@invalid:
        sec                     ; C=1: not recognised
        rts
