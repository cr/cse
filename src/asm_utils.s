; cc65 ASM accessor
; uint8_t __fastcall__ is_legal_opcode(uint8_t op);
; in:  A = op
; out: A = 0/1
;
        .export _is_legal_opcode
        .segment "RODATA"

t_6510_legal_packed_128:
        .byte $63,$67,$63,$63,$63,$63,$63,$63
        .byte $65,$67,$F7,$F7,$67,$E7,$67,$E7

        .segment "CODE"

_is_legal_opcode:
        and     #$7F            ; fold
        tay                     ; keep op in Y
        lsr     a               ; A = op >> 1
        lsr     a               ; A = op >> 2
        lsr     a               ; A = op >> 3  (byte index 0..15)
        tax                     ; X = index
        tya                     ; A = op
        and     #$07            ; bit index 0..7
        tay                     ; Y = bit index
        lda     t_6510_legal_packed_128,x

@shift: cpy     #$00
        beq     @done
        lsr     a
        dey
        bne     @shift

@done:  and     #$01
        rts