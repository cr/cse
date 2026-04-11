; ============================================================
; mn7.s -- 7-bit perfect hash mnemonic classifier (all 114 mnemonics)
; ============================================================
;
; Identifies all 114 NMOS 6502 + 65C02 mnemonics (legal, illegal,
; CMOS) via a collision-free 7-bit hash with a zero-false-positive
; bit-pack fingerprint.
;
; Algorithm
; ---------
;   hash slot:   h7 = (c1*4 + c3 + mn7_hash_t[c2]) & $7F
;   fingerprint: fp = (c2<<3) | (c3>>2)
;
; where c1/c2/c3 are the normalized letter values (AND #$1F) of the
; first, middle, and last letters of the three-character mnemonic.
;
; Character encoding
; ------------------
; Normalized values:  A=1 .. Z=26  (AND #$1F maps PETSCII upper/lower
; and VICII screencodes identically; see mn_classify.md)
; mn7_hash_t[0] = $FF guards the unused index-0 slot.
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
;   mn7_hash_t  27 bytes  (here, RODATA)
;   mn7_fp     128 bytes  (mn7_tables.s)
;   mn7_base_op 128 bytes  (mn7_tables.s)
;   mn7_profile 128 bytes  (mn7_tables.s)
;   mn7_h_tmp    1 byte   (ZEROPAGE)
;   Total: 27 + 384 + 1 = 412 bytes
; ============================================================

        .export mn7_classify
        .importzp mn_c1, mn_c2, mn_c3
        .import mn7_fp

        .importzp mn7_h_tmp

; ------------------------------------------------------------
; T7 lookup table  (generated constant; see dev/mnemonic_tables.py)
; ------------------------------------------------------------
.segment "RODATA"

; mn7_hash_t: 27 bytes.  Index 0 = $FF guard (c2 is always 1..26).
; Indices 1..26 correspond to A..Z.  Max value = $7F.
; Formula: h7 = (c1*4 + c3 + mn7_hash_t[c2]) & $7F
mn7_hash_t:
;             @     A     B     C     D     E     F     G     H
        .byte $FF, $7B, $5B, $50, $0F, $4F, $7B, $00, $0D
;             I     J     K     L     M     N     O     P     Q
        .byte $15, $7B, $7B, $7B, $69, $13, $2C, $45, $7B
;             R     S     T     U     V     W     X     Y     Z
        .byte $32, $7F, $47, $7B, $7E, $7B, $30, $56, $7B

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
