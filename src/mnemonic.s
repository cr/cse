; ============================================================
; mnemonic.s -- 7-bit perfect hash mnemonic classifier
; ============================================================
;
; Identifies 114 NMOS 6502 + 65C02 mnemonics via a collision-
; free 7-bit hash combined with a 1-byte fingerprint that
; eliminates all false positives.
;
; Algorithm
; ---------
;   hash slot:   h7  = (c1*4 + c3 + mn_hash_t[c2]) & $7F
;   fingerprint: fp  = (c2<<3) | (c3>>2)
;
; where c1/c2/c3 are the first, middle, and last letter of
; the three-character mnemonic.
;
; Character encoding
; ------------------
; VICII screencodes:  A=$01 .. Z=$1A
; PETSCII uppercase:  subtract $40 to obtain screencode.
; mn_hash_t[0] = $FF guards the unused '@' slot.
;
; Calling convention
; ------------------
; 1. Store the three VICII screencodes in mn_c1/mn_c2/mn_c3.
; 2. JSR mnemonic_classify.
; 3. On return:
;      C = 0  →  valid mnemonic;  A = hash slot (0..$7D)
;      C = 1  →  invalid mnemonic; A = undefined
; Clobbers: A, X, Y, mn_fp_tmp.
;
; Verification
; ------------
; 114 distinct hash slots in [0..$7D]                     ✓
; Max h8 for any valid mnemonic = 238 ≤ 255 (no ADC carry) ✓
; Zero fingerprint false positives over 17,462 invalid
;   three-letter strings                                   ✓
; Fingerprint sentinel $FF unreachable (max valid fp=$D6)  ✓
; ============================================================

        .export mnemonic_classify
        .export mn_c1, mn_c2, mn_c3

; ------------------------------------------------------------
; Zero-page variables
; ------------------------------------------------------------
.segment "ZEROPAGE"

mn_c1:      .res 1          ; first  letter VICII screencode (1=A..26=Z)
mn_c2:      .res 1          ; middle letter VICII screencode
mn_c3:      .res 1          ; last   letter VICII screencode
mn_fp_tmp:  .res 1          ; scratch: holds c3>>2 during fingerprint check

; ------------------------------------------------------------
; Read-only tables
; ------------------------------------------------------------
.segment "RODATA"

; mn_hash_t: 27 bytes, indexed by VICII screencode.
; Index 0 = '@' (unused guard = $FF); indices 1..26 = A..Z.
; Derived from 0-based table via: T_new[sc] = (T_old[sc-1] - 5) mod 128
mn_hash_t:
;             @    A    B    C    D    E    F    G    H
        .byte $FF, $7B, $5B, $50, $0F, $4F, $7B, $00, $0D
;             I    J    K    L    M    N    O    P    Q
        .byte $15, $7B, $7B, $7B, $69, $13, $2C, $45, $7B
;             R    S    T    U    V    W    X    Y    Z
        .byte $32, $7F, $47, $7B, $7E, $7B, $30, $56, $7B

; mn_fp_table: 128 bytes, indexed by hash slot.
; Occupied slots store (c2<<3)|(c3>>2) of the owning mnemonic.
; Empty slots store $FF (sentinel; max legal fp = $D6 < $FF).
mn_fp_table:
;        +0    +1    +2    +3    +4    +5    +6    +7
        .byte $7B, $C0, $08, $91, $90, $6C, $7C, $FF  ;   0  ROL TXA AAC SRE TRB CMP ROR ---
        .byte $FF, $B0, $60, $61, $7C, $FF, $FF, $9B  ;   8  --- BVC CLC CLD TOP --- --- ASL
        .byte $62, $64, $9B, $C4, $A0, $9C, $20, $0E  ;  16  CLI ALR ASO TXS STA ASR ADC AAX
        .byte $A2, $B4, $70, $71, $71, $65, $28, $29  ;  24  RTI BVS ANC AND ANE CLV SEC SED
        .byte $71, $6C, $A4, $C8, $2A, $98, $98, $C8  ;  32  BNE JMP RTS SYA SEI ISB ISC TYA
        .byte $FF, $46, $10, $A6, $A6, $A6, $4B, $65  ;  40  --- AHX SBC STX STY STZ CIM HLT
        .byte $0B, $4D, $3B, $68, $99, $C0, $FF, $68  ;  48  JAM BIT IGN RMB LSE AXA --- SMB
        .byte $FF, $9C, $70, $90, $60, $0C, $0C, $16  ;  56  --- JSR INC BRA PLA LAR LAS SBX
        .byte $20, $9C, $FF, $0E, $60, $92, $FF, $C4  ;  64  LDA LSR --- LAX RLA BRK --- AXS
        .byte $94, $58, $74, $64, $7C, $4B, $40, $76  ;  72  ARR SKB INS PLP DOP KIL PHA INX
        .byte $76, $98, $7C, $66, $66, $98, $63, $26  ;  80  INY TSB EOR PLX PLY USB SLO LDX
        .byte $26, $83, $40, $18, $08, $44, $0C, $0E  ;  88  LDY BPL SHA BCC XAA PHP TAS SAX
        .byte $0E, $C0, $28, $0E, $0E, $46, $46, $9E  ;  96  SAY LXA DEC TAX TAY PHX PHY TSX
        .byte $2C, $86, $86, $1C, $44, $1B, $0C, $90  ; 104  BEQ CPX CPY BCS SHS DCM XAS ORA
        .byte $1C, $46, $46, $FF, $7C, $14, $14, $2E  ; 112  DCP SHX SHY --- NOP BBR BBS DEX
        .byte $2E, $FF, $6A, $90, $FF, $C0, $FF, $FF  ; 120  DEY --- BMI RRA --- SXA --- ---

; ------------------------------------------------------------
; mnemonic_classify
; ------------------------------------------------------------
.segment "CODE"

mnemonic_classify:
        lda     mn_c3           ; c3 = last char (1..26)
        lsr     a               ; c3>>1
        lsr     a               ; c3>>2  (0..6; carry = bit 1 of c3, ignored)
        sta     mn_fp_tmp       ; save fingerprint low bits

        lda     mn_c1           ; c1 = first char (1..26)
        asl     a               ; c1*2   (<=52,  carry=0 since c1<=26)
        asl     a               ; c1*4   (<=104, carry=0 since c1*2<=52)
        adc     mn_c3           ; c1*4+c3   (<=130, carry=0)
        ldy     mn_c2           ; Y = c2 for table index
        adc     mn_hash_t,y     ; h8 = c1*4+c3+T[c2]  (max 238, carry=0)
        and     #$7F            ; 7-bit slot
        tax                     ; X = hash slot (0..$7D)

        tya                     ; A = c2
        asl     a               ; c2<<1  (<=52,  carry=0)
        asl     a               ; c2<<2  (<=104, carry=0)
        asl     a               ; c2<<3  (<=208, carry=0)
        ora     mn_fp_tmp       ; fp = (c2<<3)|(c3>>2)
        cmp     mn_fp_table,x   ; fingerprint match?
        bne     @invalid        ; no  →  definitely not a mnemonic

        txa                     ; A = hash slot
        clc                     ; C=0: valid
        rts

@invalid:
        sec                     ; C=1: invalid
        rts
