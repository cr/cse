; expr.s — Expression parser (hex literal stub)
;
; Currently only handles: [$]hhhh (1-4 hex digits, optional $ prefix)
; Will be extended with: %binary, decimal, labels, +, -, *, /, <, >, ()

        .export _expr_eval, _expr_error_str

        .import cse_popax

; ── ZP ───────────────────────────────────────────────────
pp_ptr  = $FB           ; 2 bytes: pointer to *pp / then reused as string ptr
res_ptr = $FD           ; 2 bytes: pointer to result uint16_t

; ── BSS ──────────────────────────────────────────────────
        .segment "BSS"
last_err: .res 2        ; pointer to error string (or 0)
sav_pp:   .res 2        ; saved pp_ptr (need it at end to write back)
eval:     .res 2        ; accumulated value
edigits:  .res 1        ; digit count

        .segment "CODE"

; ═════════════════════════════════════════════════════════
; expr_eval(pp, result_ptr)
;   __fastcall__: result_ptr in A/X, pp on C stack
;   Returns 0=success, 1=error
; ═════════════════════════════════════════════════════════
.proc _expr_eval
        ; Save result_ptr
        sta res_ptr
        stx res_ptr+1

        ; Pop pp (pointer to pointer)
        jsr cse_popax
        sta pp_ptr
        stx pp_ptr+1

        ; Save pp_ptr for later write-back
        lda pp_ptr
        sta sav_pp
        lda pp_ptr+1
        sta sav_pp+1

        ; Load *pp into pp_ptr (reuse as string pointer)
        ldy #0
        lda (pp_ptr),y
        tax
        iny
        lda (pp_ptr),y
        sta pp_ptr+1
        stx pp_ptr

        ; skip spaces
@skip:  ldy #0
        lda (pp_ptr),y
        cmp #' '
        bne @sp_done
        inc pp_ptr
        bne @skip
        inc pp_ptr+1
        bne @skip               ; always
@sp_done:

        ; skip optional '$'
        cmp #'$'
        bne @no_dollar
        inc pp_ptr
        bne @no_dollar
        inc pp_ptr+1
@no_dollar:

        ; Init accumulator
        lda #0
        sta eval
        sta eval+1
        sta edigits

        ; Parse hex digits
@loop:  ldy #0
        lda (pp_ptr),y
        ; inline hex check
        cmp #'0'
        bcc @done
        cmp #'9'+1
        bcc @digit
        cmp #'a'
        bcc @done
        cmp #'f'+1
        bcs @done
        ; hex letter a-f
        sec
        sbc #'a'-10
        jmp @nybble
@digit: sec
        sbc #'0'
@nybble:
        ; val = (val << 4) | nybble
        pha
        asl eval
        rol eval+1
        asl eval
        rol eval+1
        asl eval
        rol eval+1
        asl eval
        rol eval+1
        pla
        ora eval
        sta eval

        ; advance pointer
        inc pp_ptr
        bne :+
        inc pp_ptr+1
:
        ; check digit count
        inc edigits
        lda edigits
        cmp #5
        bcc @loop

        ; overflow
        lda #<err_overflow
        ldx #>err_overflow
        bne @set_err            ; always

@done:
        lda edigits
        beq @no_input

        ; Success: *result_ptr = eval
        ldy #0
        lda eval
        sta (res_ptr),y
        iny
        lda eval+1
        sta (res_ptr),y

        ; Write back updated string position to *pp
        ; pp_ptr currently IS the string pos; sav_pp has the original pp
        ; Need a ZP pointer to write to *sav_pp. Reuse res_ptr (done with it).
        lda sav_pp
        sta res_ptr
        lda sav_pp+1
        sta res_ptr+1
        ldy #0
        lda pp_ptr
        sta (res_ptr),y
        iny
        lda pp_ptr+1
        sta (res_ptr),y

        ; Clear error
        lda #0
        sta last_err
        sta last_err+1
        tax                     ; return 0
        rts

@no_input:
        lda #<err_expected
        ldx #>err_expected

@set_err:
        sta last_err
        stx last_err+1
        lda #1
        ldx #0
        rts
.endproc

; ═════════════════════════════════════════════════════════
; expr_error_str() → pointer to error string in A/X
; ═════════════════════════════════════════════════════════
.proc _expr_error_str
        lda last_err
        ora last_err+1
        beq @empty
        lda last_err
        ldx last_err+1
        rts
@empty:
        lda #<@str
        ldx #>@str
        rts
@str:   .byte 0
.endproc

; ── Error strings ────────────────────────────────────────
        .segment "RODATA"
err_overflow: .byte "overflow", 0
err_expected: .byte "expected value", 0
