        .export _c64_op_len_bool_asm

; ------------------------------------------------------------
; Zero-page temporaries (linker-allocated, safe)
; ------------------------------------------------------------
.segment "ZEROPAGE"

op_tmp:     .res 1    ; original opcode
l1_tmp:     .res 1    ; L1 bit (0/1)
l0_tmp:     .res 1    ; L0 bit (0/1)

; ------------------------------------------------------------
; Code
; ------------------------------------------------------------
.segment "CODE"

; uint8_t __fastcall__ c64_op_len_bool_asm(uint8_t opcode)
; A = opcode on entry
; A = (L1<<1)|L0 on return

.export _c64_op_len_bool_asm

        ; save opcode
        sta op_tmp

; ------------------------------------------------------------
; L1 = B0 | C0 | (!B1 & ((A2 & !B2) | (B2 & !C1) | (A0 & !A1 & !C1)))
; ------------------------------------------------------------

        lda op_tmp
        and #%00000101      ; B0 | C0
        beq @l1_check_b1
        lda #1
        sta l1_tmp
        jmp @l1_done

@l1_check_b1:
        lda op_tmp
        and #%00001000      ; B1
        bne @l1_zero

        ; term: A2 & !B2
        lda op_tmp
        and #%10000000
        beq @l1_term2
        lda op_tmp
        and #%00010000
        bne @l1_term2
        lda #1
        sta l1_tmp
        jmp @l1_done

@l1_term2:
        ; term: B2 & !C1
        lda op_tmp
        and #%00010000
        beq @l1_term3
        lda op_tmp
        and #%00000010
        bne @l1_term3
        lda #1
        sta l1_tmp
        jmp @l1_done

@l1_term3:
        ; term: A0 & !A1 & !C1
        lda op_tmp
        and #%00100000
        beq @l1_zero
        lda op_tmp
        and #%01000000
        bne @l1_zero
        lda op_tmp
        and #%00000010
        bne @l1_zero
        lda #1
        sta l1_tmp
        jmp @l1_done

@l1_zero:
        lda #0
        sta l1_tmp

@l1_done:

; ------------------------------------------------------------
; L0 = (B1 & (B0 | B2 | !C0))
;    | (!C0 & !B0 & ((B2 & C1) | (!A2 & !B2)))
; ------------------------------------------------------------

        ; part 1: B1 & (B0 | B2 | !C0)
        lda op_tmp
        and #%00001000      ; B1
        beq @l0_part2

        lda op_tmp
        and #%00010100      ; B0 | B2
        bne @l0_one

        lda op_tmp
        and #%00000001      ; C0
        beq @l0_one

@l0_part2:
        ; part 2: !C0 & !B0 & ((B2 & C1) | (!A2 & !B2))
        lda op_tmp
        and #%00000001      ; C0
        bne @l0_zero
        lda op_tmp
        and #%00000100      ; B0
        bne @l0_zero

        ; subterm: B2 & C1
        lda op_tmp
        and #%00010000
        beq @l0_sub2
        lda op_tmp
        and #%00000010
        bne @l0_one

@l0_sub2:
        ; subterm: !A2 & !B2
        lda op_tmp
        and #%10000000
        bne @l0_zero
        lda op_tmp
        and #%00010000
        bne @l0_zero

@l0_one:
        lda #1
        sta l0_tmp
        jmp @l0_done

@l0_zero:
        lda #0
        sta l0_tmp

@l0_done:

; ------------------------------------------------------------
; return (L1<<1) | L0
; ------------------------------------------------------------

        lda l1_tmp
        asl
        ora l0_tmp
        rts

.endproc
