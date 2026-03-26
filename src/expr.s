; expr.s — Expression parser (recursive descent)
;
; Grammar:
;   expr   = term (('+' | '-') term)*
;   term   = factor
;   factor = '$' hex | '#' decimal | '%' binary | '*' | label
;          | '<' factor | '>' factor | '(' expr ')'
;
; Interface (ZP-based, no C stack):
;   expr_ptr  (2B, imported): in/out — pointer to PETSCII input
;   expr_val  (2B, imported): out — 16-bit result
;   asm_pc    (2B, imported): in — current PC for '*'
;
;   _expr_eval:  C=0 success, C=1 error (A = error code)
;
; Error codes returned in A:
;   ERR_EXPECTED  = 1   expected value
;   ERR_OVERFLOW  = 2   value too large
;   ERR_PAREN     = 3   mismatched parentheses
;   ERR_UNDEFINED = 4   undefined symbol

        .export _expr_eval
        .export _expr_error_str

        .import _sym_lookup
        .importzp sym_name, sym_val

; ── Error codes ─────────────────────────────────────────────
ERR_NONE      = 0
ERR_EXPECTED  = 1
ERR_OVERFLOW  = 2
ERR_PAREN     = 3
ERR_UNDEFINED = 4

; ── ZP imports ──────────────────────────────────────────────
; expr_ptr/expr_val: shared pipeline registers (asm_vars.s)
; al_pc: current program counter (asm_vars.s) — used for '*'
.importzp expr_ptr, expr_val
.importzp al_pc
asm_pc = al_pc                   ; alias for readability

; ── ZP scratch ──────────────────────────────────────────────
.segment "ZEROPAGE"
_ex_tmp:     .res 2              ; scratch for left-side save
_ex_digits:  .res 1              ; digit counter

; ── BSS ─────────────────────────────────────────────────────
.segment "BSS"
last_err:    .res 1              ; last error code

        .segment "CODE"

; ── Helper: read current char (non-destructive) ────────────
; Returns char in A, Y=0.  Does NOT advance pointer.
.macro PEEK_CHAR
        ldy #0
        lda (expr_ptr),y
.endmacro

; ── Helper: advance expr_ptr by 1 ──────────────────────────
.macro ADV_PTR
        inc expr_ptr
        bne :+
        inc expr_ptr+1
:
.endmacro

; ── Helper: skip spaces ────────────────────────────────────
.proc skip_sp
@lp:    PEEK_CHAR
        cmp #' '
        bne @done
        ADV_PTR
        jmp @lp
@done:  rts
.endproc

; ═══════════════════════════════════════════════════════════
; _expr_eval — top level entry
;   Parses expr at expr_ptr, writes result to expr_val.
;   Returns C=0 ok, C=1 error (A = error code).
; ═══════════════════════════════════════════════════════════
.proc _expr_eval
        jsr skip_sp
        jsr parse_expr
        bcs @err
        lda #ERR_NONE
        clc
        rts
@err:   rts                      ; A = error code, C=1
.endproc

; ═══════════════════════════════════════════════════════════
; parse_expr — expr = term (('+' | '-') term)*
; ═══════════════════════════════════════════════════════════
.proc parse_expr
        jsr parse_factor         ; first term → expr_val
        bcs @done

@op:    jsr skip_sp
        PEEK_CHAR
        cmp #'+'
        beq @add
        cmp #'-'
        beq @sub
        clc                      ; success — not an operator, stop
@done:  rts

@add:   ADV_PTR
        jsr skip_sp
        ; save left side on hardware stack
        lda expr_val+1
        pha
        lda expr_val
        pha
        ; parse right side
        jsr parse_factor
        bcs @add_err
        ; add: left (stack) + right (expr_val)
        pla                      ; left lo
        clc
        adc expr_val
        sta expr_val
        pla                      ; left hi
        adc expr_val+1
        sta expr_val+1
        jmp @op
@add_err:
        pla
        pla                      ; clean stack
        sec
        rts

@sub:   ADV_PTR
        jsr skip_sp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_factor
        bcs @sub_err
        ; subtract: left (stack) - right (expr_val)
        pla                      ; left lo
        sec
        sbc expr_val
        sta expr_val
        pla                      ; left hi
        sbc expr_val+1
        sta expr_val+1
        jmp @op
@sub_err:
        pla
        pla
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_factor — single value or unary operator
; ═══════════════════════════════════════════════════════════
.proc parse_factor
        jsr skip_sp
        PEEK_CHAR

        cmp #'$'
        beq @hex
        cmp #'%'
        beq @binary
        cmp #'*'
        beq @star
        cmp #'<'
        beq @lo_byte
        cmp #'>'
        beq @hi_byte
        cmp #'('
        beq @paren

        ; Check for bare decimal digit (0-9 without prefix)
        cmp #'0'
        bcc @chk_label
        cmp #'9'+1
        bcc @decimal_bare
        ; Check for label: starts with a letter (PETSCII $41-$5A)
@chk_label:
        cmp #$41
        bcc @err_expected
        cmp #$5B
        bcc @to_label
        cmp #'.'
        beq @to_label
        cmp #'_'
        beq @to_label

@err_expected:
        lda #ERR_EXPECTED
        sec
        rts

@to_label:
        jmp @label

; ── $hex ────────────────────────────────────────────────
@hex:   ADV_PTR                  ; skip '$'
        jmp parse_hex

; ── bare decimal (no prefix) ───────────────────────────
@decimal_bare:
        jmp parse_decimal        ; digit still current, no skip

; ── %binary ─────────────────────────────────────────────
@binary:
        ADV_PTR                  ; skip '%'
        jmp parse_binary

; ── * (program counter) ────────────────────────────────
@star:  ADV_PTR
        lda asm_pc
        sta expr_val
        lda asm_pc+1
        sta expr_val+1
        clc
        rts

; ── < (lo byte) ────────────────────────────────────────
@lo_byte:
        ADV_PTR
        jsr parse_factor         ; recursive
        bcs @ret
        lda #0
        sta expr_val+1           ; hi = 0, lo unchanged
        clc
@ret:   rts

; ── > (hi byte) ────────────────────────────────────────
@hi_byte:
        ADV_PTR
        jsr parse_factor         ; recursive
        bcs @ret2
        lda expr_val+1
        sta expr_val
        lda #0
        sta expr_val+1
        clc
@ret2:  rts

; ── ( expr ) ───────────────────────────────────────────
@paren: ADV_PTR                  ; skip '('
        jsr skip_sp
        jsr parse_expr           ; recursive
        bcs @ret3
        jsr skip_sp
        PEEK_CHAR
        cmp #')'
        bne @err_paren
        ADV_PTR                  ; skip ')'
        clc
@ret3:  rts

@err_paren:
        lda #ERR_PAREN
        sec
        rts

; ── label ──────────────────────────────────────────────
@label:
        ; expr_ptr points to start of identifier
        ; Set sym_name = expr_ptr for sym_lookup
        lda expr_ptr
        sta sym_name
        lda expr_ptr+1
        sta sym_name+1
        ; Scan past identifier chars (letters, digits, '_', '.')
@lscan: ADV_PTR
        PEEK_CHAR
        cmp #$41
        bcc @lchk_dig
        cmp #$5B
        bcc @lscan               ; a-z
@lchk_dig:
        cmp #'0'
        bcc @lchk_other
        cmp #'9'+1
        bcc @lscan               ; 0-9
@lchk_other:
        cmp #'_'
        beq @lscan
        cmp #'.'
        beq @lscan
        ; End of identifier — expr_ptr now past it
        ; We need to NUL-terminate the name for sym_lookup.
        ; But we can't modify the input string!
        ; Instead, save the char at the end, write NUL, lookup, restore.
        PEEK_CHAR
        pha                      ; save original char
        lda #0
        sta (expr_ptr),y         ; temporary NUL
        jsr _sym_lookup
        pla
        sta (expr_ptr),y         ; restore original char
        bcs @err_undef
        ; sym_val has the value
        lda sym_val
        sta expr_val
        lda sym_val+1
        sta expr_val+1
        clc
        rts

@err_undef:
        lda #ERR_UNDEFINED
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_hex — parse 1-4 hex digits at expr_ptr
; ═══════════════════════════════════════════════════════════
.proc parse_hex
        lda #0
        sta expr_val
        sta expr_val+1
        sta _ex_digits

@loop:  PEEK_CHAR
        jsr hex_nybble           ; A = 0-15 or C=1
        bcs @done
        ; shift val left 4 and OR
        pha
        asl expr_val
        rol expr_val+1
        asl expr_val
        rol expr_val+1
        asl expr_val
        rol expr_val+1
        asl expr_val
        rol expr_val+1
        pla
        ora expr_val
        sta expr_val
        ADV_PTR
        inc _ex_digits
        lda _ex_digits
        cmp #5
        bcc @loop
        ; overflow — 5+ digits
        lda #ERR_OVERFLOW
        sec
        rts

@done:  lda _ex_digits
        beq @no_digits
        clc
        rts
@no_digits:
        lda #ERR_EXPECTED
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_decimal — parse decimal digits after '#'
; Result in expr_val.  Max 65535.
; ═══════════════════════════════════════════════════════════
.proc parse_decimal
        lda #0
        sta expr_val
        sta expr_val+1
        sta _ex_digits

@loop:  PEEK_CHAR
        cmp #'0'
        bcc @done
        cmp #'9'+1
        bcs @done
        sec
        sbc #'0'                 ; A = digit 0-9
        pha

        ; val = val * 10: val*8 + val*2
        ; Save val
        lda expr_val
        sta _ex_tmp
        lda expr_val+1
        sta _ex_tmp+1
        ; val *= 2
        asl expr_val
        rol expr_val+1
        bcs @overflow
        ; val *= 4
        asl expr_val
        rol expr_val+1
        bcs @overflow
        ; val += saved (now val = orig*4 + orig = orig*5)
        lda expr_val
        clc
        adc _ex_tmp
        sta expr_val
        lda expr_val+1
        adc _ex_tmp+1
        bcs @overflow
        ; val *= 2 (now val = orig*10)
        asl expr_val
        rol expr_val+1
        bcs @overflow

        ; val += digit
        pla
        clc
        adc expr_val
        sta expr_val
        lda expr_val+1
        adc #0
        sta expr_val+1
        bcs @overflow

        ADV_PTR
        inc _ex_digits
        jmp @loop

@overflow:
        pla                      ; clean stack (digit was pushed)
        lda #ERR_OVERFLOW
        sec
        rts

@done:  lda _ex_digits
        beq @no_digits
        clc
        rts
@no_digits:
        lda #ERR_EXPECTED
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_binary — parse binary digits after '%'
; ═══════════════════════════════════════════════════════════
.proc parse_binary
        lda #0
        sta expr_val
        sta expr_val+1
        sta _ex_digits

@loop:  PEEK_CHAR
        cmp #'0'
        beq @bit
        cmp #'1'
        beq @bit
        jmp @done

@bit:   sec
        sbc #'0'                 ; A = 0 or 1
        ; Shift val left and OR
        asl expr_val
        rol expr_val+1
        bcs @overflow_chk        ; check if bit 16 was shifted out
        ora expr_val
        sta expr_val
        ADV_PTR
        inc _ex_digits
        lda _ex_digits
        cmp #17
        bcc @loop
@overflow_chk:
        lda #ERR_OVERFLOW
        sec
        rts

@done:  lda _ex_digits
        beq @no_digits
        clc
        rts
@no_digits:
        lda #ERR_EXPECTED
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; hex_nybble — convert char in A to 0-15
;   Returns value in A, C=0. If not hex, C=1.
; ═══════════════════════════════════════════════════════════
.proc hex_nybble
        cmp #'0'
        bcc @bad
        cmp #'9'+1
        bcc @digit
        cmp #'a'
        bcc @bad
        cmp #'f'+1
        bcs @bad
        sec
        sbc #'a'-10
        clc
        rts
@digit: sec
        sbc #'0'
        clc
        rts
@bad:   sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; _expr_error_str — return pointer to error string
; ═══════════════════════════════════════════════════════════
.proc _expr_error_str
        ldx last_err
        lda err_str_lo,x
        pha
        lda err_str_hi,x
        tax
        pla
        rts
.endproc

; ── Error string table ──────────────────────────────────
        .segment "RODATA"
err_str_lo:
        .byte <err_none, <err_expected, <err_overflow, <err_paren, <err_undefined
err_str_hi:
        .byte >err_none, >err_expected, >err_overflow, >err_paren, >err_undefined

err_none:      .byte 0
err_expected:  .byte "expected value", 0
err_overflow:  .byte "overflow", 0
err_paren:     .byte "missing )", 0
err_undefined: .byte "undefined", 0
