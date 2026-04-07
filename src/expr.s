; expr.s — Expression parser (recursive descent)
;
; Grammar:
;   expr     = bool_term (('£' | '&' | '^') bool_term)*
;   bool_term = add_term (('+' | '-') add_term)*
;   add_term  = mul_term (('*' | '/' | '<<' | '>>') mul_term)*
;   mul_term  = factor
;   factor = '$' hex | '%' binary | decimal | '*'(PC) | label
;          | '-' factor | '!' factor | '<' factor | '>' factor
;          | '(' expr ')'
;
; Operators (C64 keyboard friendly):
;   &  = AND       £  = OR (pound key)    ^ = XOR (↑ key)    ! = NOT
;   +  = add       -  = subtract
;   *  = multiply  /  = integer divide    << = shift left     >> = shift right
;
; Return code in A:
;   0 = success, ZP-eligible (8-bit, result ≤ $FF, no wide factors)
;   1 = success, ABS (16-bit or forced wide)
;   2 = error: expected value
;   3 = error: overflow
;   4 = error: mismatched parentheses
;   5 = error: undefined symbol
;   6 = error: division by zero
;
; Width rule:
;   - $XX (1-2 hex digits) → narrow
;   - $XXX/$XXXX (3-4 hex digits) → wide
;   - decimal, binary → width from value (>$FF = wide)
;   - label → inherits sym_wide from definition
;   - * → wide if PC > $FF
;   - < and > → always narrow (clear wide)
;   - - (negate), ! → width from result
;   - +, -, &, £, ^ → wide if either operand wide OR result > $FF

        .export expr_eval
        .export expr_error_str

        .import sym_lookup
        .import kernal_bank_out, kernal_bank_in
        .importzp sym_name, sym_val, sym_wide

; ── Return / error codes ───────────────────────────────────
RC_ZP        = 0
RC_ABS       = 1
ERR_EXPECTED = 2
ERR_OVERFLOW = 3
ERR_PAREN    = 4
ERR_UNDEFINED = 5
ERR_DIVZERO  = 6

; ── ZP imports ─────────────────────────────────────────────
.importzp expr_ptr, expr_val, expr_wide
.importzp al_pc
asm_pc = al_pc

; ── ZP scratch ─────────────────────────────────────────────
.segment "ZEROPAGE"
_ex_tmp:     .res 2              ; scratch
_ex_digits:  .res 1              ; digit counter
_ex_wide_tmp: .res 1             ; saved wide flag for left operand

; ── BSS ────────────────────────────────────────────────────
.segment "BSS"
last_err:    .res 1
_mul_tmp:    .res 2              ; multiply: shifted operand copy
_div_rem:    .res 2              ; divide: remainder

        .segment "CODE"

; ── Macros ─────────────────────────────────────────────────
.macro PEEK_CHAR
        ldy #0
        lda (expr_ptr),y
.endmacro

.macro ADV_PTR
        inc expr_ptr
        bne :+
        inc expr_ptr+1
:
.endmacro

; ── skip_sp ────────────────────────────────────────────────
; Skip whitespace ($20/$A0) at expr_ptr.
.proc skip_sp
@lp:    PEEK_CHAR
        cmp #' '
        beq @eat
        cmp #$a0
        bne @done
@eat:   jsr _ex_adv_ptr
        jmp @lp
@done:  rts
.endproc

; ═══════════════════════════════════════════════════════════
; expr_eval — entry point
;   Returns A = 0 (ZP), 1 (ABS), or 2+ (error)
;
; expr_eval owns its own KERNAL banking — callers don't manage
; it.  Symbol lookups inside the expression go through sym_lookup,
; which reads sym_table / sym_heap under KERNAL.  By bracketing
; the whole evaluation with one bank pair here, the inner
; sym_lookup calls short-circuit (when run inside an asm_assemble
; batch, kernal_out=1 is already set; in REPL contexts, this
; wrapper IS the bank pair).  Either way, callers of expr_eval
; never need to think about KERNAL banking.
;
; Same wrapper structure as asm_line and dasm_insn.
; ═══════════════════════════════════════════════════════════
.proc expr_eval
        jsr kernal_bank_out      ; (no-op inside an asm batch)
        jsr _expr_eval_inner
        pha                      ; save A across bank_in
        jsr kernal_bank_in
        pla
        rts
.endproc

; ── _expr_eval_inner — the actual evaluator ──
; Runs with KERNAL banked out (or pre-banked by an outer batch).
; Returns A = 0 (ZP), 1 (ABS), or 2+ (error).
.proc _expr_eval_inner
        lda #0
        sta expr_wide            ; start narrow
        jsr skip_sp
        jsr parse_expr
        bcs @err
        ; Success: determine return code from wide flag
        lda expr_val+1
        bne @abs                 ; result > $FF → ABS
        lda expr_wide
        bne @abs                 ; forced wide → ABS
        lda #RC_ZP
        sta last_err
        rts
@abs:   lda #RC_ABS
        sta last_err
        rts
@err:   ; A already has error code (2+)
        sta last_err
        rts
.endproc

; ── Shared helpers for binary-op parsers ──────────────────
; _ex_adv_ptr: advance expr_ptr by 1
_ex_adv_ptr:
        inc expr_ptr
        bne :+
        inc expr_ptr+1
:       rts

; _ex_pop_err: discard stacked left operand, propagate error in A (C=1)
_ex_pop_err:
        tax
        pla
        pla
        txa
        sec
        rts

; _ex_merge_wide: merge saved wide flag + detect 16-bit result
_ex_merge_wide:
        lda _ex_wide_tmp
        ora expr_wide
        sta expr_wide
        lda expr_val+1
        beq :+
        lda #1
        sta expr_wide
:       rts

; ═══════════════════════════════════════════════════════════
; parse_expr — bool_term (('&' | '£' | '^') bool_term)*
; ═══════════════════════════════════════════════════════════
.proc parse_expr
        jsr parse_add
        bcs @done

@op:    jsr skip_sp
        PEEK_CHAR
        cmp #'&'
        beq @and
        cmp #$5C                ; £ = OR (pound sign)
        beq @or
        cmp #'^'
        beq @xor
        clc
@done:  rts

@and:   jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_add
        bcs @bool_err
        pla
        and expr_val
        sta expr_val
        pla
        and expr_val+1
        sta expr_val+1
        jsr @merge_wide
        jmp @op

@or:    jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_add
        bcs @bool_err
        pla
        ora expr_val
        sta expr_val
        pla
        ora expr_val+1
        sta expr_val+1
        jsr @merge_wide
        jmp @op

@xor:   jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_add
        bcs @bool_err
        pla
        eor expr_val
        sta expr_val
        pla
        eor expr_val+1
        sta expr_val+1
        jsr @merge_wide
        jmp @op

@bool_err:
        jmp _ex_pop_err
@merge_wide:
        jmp _ex_merge_wide
.endproc

; ═══════════════════════════════════════════════════════════
; parse_add — add_term (('+' | '-') add_term)*
; ═══════════════════════════════════════════════════════════
.proc parse_add
        jsr parse_mul
        bcs @done

@op:    jsr skip_sp
        PEEK_CHAR
        cmp #'+'
        beq @add
        cmp #'-'
        beq @sub
        clc
@done:  rts

@add:   jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_mul
        bcs @add_err
        ; add
        pla
        clc
        adc expr_val
        sta expr_val
        pla
        adc expr_val+1
        sta expr_val+1
        jsr @merge_wide
        jmp @op

@sub:   jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_mul
        bcs @add_err
        ; left - right
        pla
        sec
        sbc expr_val
        sta expr_val
        pla
        sbc expr_val+1
        sta expr_val+1
        jsr @merge_wide
        jmp @op

@add_err:
        jmp _ex_pop_err
@merge_wide:
        jmp _ex_merge_wide
.endproc

; ═══════════════════════════════════════════════════════════
; parse_mul — mul_term (('*' | '/' | '<<' | '>>') mul_term)*
;   Note: '*' alone (no operator context) = PC in parse_factor.
;   Here '*' is binary multiply (between two values).
; ═══════════════════════════════════════════════════════════
.proc parse_mul
        jsr parse_factor
        bcs @done

@op:    jsr skip_sp
        PEEK_CHAR
        cmp #'*'
        beq @mul
        cmp #'/'
        beq @div
        cmp #'<'
        bne @chk_shr
        ; peek next char — << or just < (end of expr)?
        ldy #1
        lda (expr_ptr),y
        cmp #'<'
        bne @done_clc           ; single < = not our operator
        jmp @shl
@chk_shr:
        cmp #'>'
        bne @done_clc
        ldy #1
        lda (expr_ptr),y
        cmp #'>'
        bne @done_clc
        jmp @shr

@done_clc:
        clc
@done:  rts

; ── multiply ──────────────────────────────────────────
@mul:   jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_factor
        bcs @mul_err
        ; 16-bit multiply: left (stack) × right (expr_val)
        ; Result in expr_val. Uses _ex_tmp as accumulator.
        pla
        sta _ex_tmp             ; left lo
        pla
        sta _ex_tmp+1           ; left hi
        jsr @do_mul16
        jsr @merge_wide
        jmp @op

; ── divide ────────────────────────────────────────────
@div:   jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_factor
        bcs @mul_err
        ; Check divisor == 0
        lda expr_val
        ora expr_val+1
        beq @divzero
        ; 16-bit divide: left (stack) / right (expr_val)
        pla
        sta _ex_tmp             ; left lo = dividend
        pla
        sta _ex_tmp+1           ; left hi
        jsr @do_div16
        jsr @merge_wide
        jmp @op

@mul_err:
        jmp _ex_pop_err
@divzero:
        pla
        pla
        lda #ERR_DIVZERO
        sec
        rts

; ── shift left ────────────────────────────────────────
@shl:   jsr _ex_adv_ptr                 ; skip first <
        jsr _ex_adv_ptr                 ; skip second <
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_factor
        bcs @mul_err
        ; Left shift: left << right (right = shift count in expr_val lo)
        pla
        sta _ex_tmp
        pla
        sta _ex_tmp+1
        ldx expr_val            ; shift count
        beq @shl_done
@shl_loop:
        asl _ex_tmp
        rol _ex_tmp+1
        dex
        bne @shl_loop
@shl_done:
        lda _ex_tmp
        sta expr_val
        lda _ex_tmp+1
        sta expr_val+1
        jsr @merge_wide
        jmp @op

; ── shift right ───────────────────────────────────────
@shr:   jsr _ex_adv_ptr
        jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_factor
        bcs @mul_err
        pla
        sta _ex_tmp
        pla
        sta _ex_tmp+1
        ldx expr_val
        beq @shr_done
@shr_loop:
        lsr _ex_tmp+1
        ror _ex_tmp
        dex
        bne @shr_loop
@shr_done:
        lda _ex_tmp
        sta expr_val
        lda _ex_tmp+1
        sta expr_val+1
        jsr @merge_wide
        jmp @op

; ── 16-bit multiply: _ex_tmp × expr_val → expr_val ───
; Shift-and-add: shift right operand (expr_val), add left (_ex_tmp)
; when bit is set. Result accumulates in place.
@do_mul16:
        lda expr_val
        sta _mul_tmp               ; right operand (shifted)
        lda expr_val+1
        sta _mul_tmp+1
        lda #0
        sta expr_val            ; accumulator = 0
        sta expr_val+1
        ldx #16
@m_loop:
        lsr _mul_tmp+1               ; shift right operand right
        ror _mul_tmp
        bcc @m_skip
        lda expr_val            ; add left operand
        clc
        adc _ex_tmp
        sta expr_val
        lda expr_val+1
        adc _ex_tmp+1
        sta expr_val+1
@m_skip:
        asl _ex_tmp             ; shift left operand left
        rol _ex_tmp+1
        dex
        bne @m_loop
        rts

; ── 16-bit divide: _ex_tmp / expr_val → expr_val ─────
; Unsigned 16/16 → 16 quotient. Remainder discarded.
@do_div16:
        ; dividend in _ex_tmp, divisor in expr_val
        ; Algorithm: shift-subtract, 16 iterations
        lda #0
        sta _div_rem               ; remainder = 0
        sta _div_rem+1
        ldx #16
@d_loop:
        ; shift dividend left, MSB into remainder
        asl _ex_tmp
        rol _ex_tmp+1
        rol _div_rem
        rol _div_rem+1
        ; try subtract divisor from remainder
        lda _div_rem
        sec
        sbc expr_val
        tay
        lda _div_rem+1
        sbc expr_val+1
        bcc @d_skip             ; remainder < divisor
        ; fit: store remainder, set quotient bit
        sta _div_rem+1
        sty _div_rem
        inc _ex_tmp             ; set bit 0 of quotient
@d_skip:
        dex
        bne @d_loop
        ; quotient in _ex_tmp
        lda _ex_tmp
        sta expr_val
        lda _ex_tmp+1
        sta expr_val+1
        rts

@merge_wide:
        jmp _ex_merge_wide
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
        bne :+
        jmp @paren
:       cmp #'!'                ; NOT (complement)
        bne :+
        jmp @complement
:       cmp #'-'                ; unary minus (negate)
        bne :+
        jmp @negate
:

        ; bare decimal (0-9)
        cmp #'0'
        bcc @chk_label
        cmp #'9'+1
        bcc @decimal_bare

        ; label (a-z)
@chk_label:
        cmp #$41
        bcc @err_expected
        cmp #$5B
        bcc @to_label
        cmp #'.'
        beq @to_label

@err_expected:
        lda #ERR_EXPECTED
        sec
        rts

@to_label:
        jmp @label

; ── $hex ───────────────────────────────────────────────
@hex:   jsr _ex_adv_ptr
        jmp parse_hex

; ── bare decimal ───────────────────────────────────────
@decimal_bare:
        jmp parse_decimal

; ── %binary ────────────────────────────────────────────
@binary:
        jsr _ex_adv_ptr
        jmp parse_binary

; ── * (program counter) ───────────────────────────────
@star:  jsr _ex_adv_ptr
        lda asm_pc
        sta expr_val
        lda asm_pc+1
        sta expr_val+1
        ; wide if PC > $FF
        lda asm_pc+1
        beq @star_zp
        lda #1
        sta expr_wide
@star_zp:
        clc
        rts

; ── < (lo byte) — clears wide ────────────────────────
@lo_byte:
        jsr _ex_adv_ptr
        jsr parse_factor
        bcs @ret
        lda #0
        sta expr_val+1
        sta expr_wide            ; < always produces ZP
        clc
@ret:   rts

; ── > (hi byte) — clears wide ────────────────────────
@hi_byte:
        jsr _ex_adv_ptr
        jsr parse_factor
        bcs @ret2
        lda expr_val+1
        sta expr_val
        lda #0
        sta expr_val+1
        sta expr_wide            ; > always produces ZP
        clc
@ret2:  rts

; ── ! (complement / NOT) ──────────────────────────────
@complement:
        jsr _ex_adv_ptr
        jsr parse_factor
        bcs @ret3
        lda expr_val
        eor #$FF
        sta expr_val
        lda expr_val+1
        eor #$FF
        sta expr_val+1
        ; wide if result > $FF
        lda expr_val+1
        beq @ret3
        lda #1
        sta expr_wide
@ret3:  clc
        rts

; ── - (negate / unary minus) ──────────────────────────
@negate:
        jsr _ex_adv_ptr
        jsr parse_factor
        bcs @ret3b
        ; two's complement: EOR $FF, then INC16
        lda expr_val
        eor #$FF
        clc
        adc #1
        sta expr_val
        lda expr_val+1
        eor #$FF
        adc #0
        sta expr_val+1
        ; wide if result > $FF
        lda expr_val+1
        beq @ret3b
        lda #1
        sta expr_wide
@ret3b: clc
        rts

; ── ( expr ) ──────────────────────────────────────────
@paren: jsr _ex_adv_ptr
        jsr skip_sp
        jsr parse_expr
        bcs @ret4
        jsr skip_sp
        PEEK_CHAR
        cmp #')'
        bne @err_paren
        jsr _ex_adv_ptr
        clc
@ret4:  rts

@err_paren:
        lda #ERR_PAREN
        sec
        rts

; ── label ─────────────────────────────────────────────
@label:
        lda expr_ptr
        sta sym_name
        lda expr_ptr+1
        sta sym_name+1
@lscan: jsr _ex_adv_ptr
        PEEK_CHAR
        cmp #$41
        bcc @lchk_dig
        cmp #$5B
        bcc @lscan
@lchk_dig:
        cmp #'0'
        bcc @lchk_other
        cmp #'9'+1
        bcc @lscan
@lchk_other:
        cmp #'.'
        beq @lscan
        ; End of identifier — NUL-terminate, lookup, restore
        PEEK_CHAR
        pha
        lda #0
        sta (expr_ptr),y
        jsr sym_lookup
        pla
        ldy #0
        sta (expr_ptr),y
        bcs @err_undef
        ; sym_val and sym_wide set by lookup
        lda sym_val
        sta expr_val
        lda sym_val+1
        sta expr_val+1
        lda sym_wide
        ora expr_wide
        sta expr_wide
        clc
        rts

@err_undef:
        lda #ERR_UNDEFINED
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_hex — 1-4 hex digits. Sets wide if 3+ digits.
; ═══════════════════════════════════════════════════════════
.proc parse_hex
        lda #0
        sta expr_val
        sta expr_val+1
        sta _ex_digits

@loop:  PEEK_CHAR
        jsr hex_nybble
        bcs @done
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
        jsr _ex_adv_ptr
        inc _ex_digits
        lda _ex_digits
        cmp #5
        bcc @loop
        lda #ERR_OVERFLOW
        sec
        rts

@done:  lda _ex_digits
        beq @no_digits
        ; Set wide if 3+ digits
        cmp #3
        bcc @narrow
        lda #1
        ora expr_wide
        sta expr_wide
@narrow:
        clc
        rts
@no_digits:
        lda #ERR_EXPECTED
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_decimal — bare digits. Wide if result > $FF.
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
        sbc #'0'
        pha
        ; val = val * 10
        lda expr_val
        sta _ex_tmp
        lda expr_val+1
        sta _ex_tmp+1
        asl expr_val
        rol expr_val+1
        bcs @overflow
        asl expr_val
        rol expr_val+1
        bcs @overflow
        lda expr_val
        clc
        adc _ex_tmp
        sta expr_val
        lda expr_val+1
        adc _ex_tmp+1
        bcs @overflow
        sta expr_val+1
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
        bcs @overflow2

        jsr _ex_adv_ptr
        inc _ex_digits
        jmp @loop

@overflow:
        pla
@overflow2:
        lda #ERR_OVERFLOW
        sec
        rts

@done:  lda _ex_digits
        beq @no_digits
        ; wide if result > $FF
        lda expr_val+1
        beq :+
        lda #1
        ora expr_wide
        sta expr_wide
:       clc
        rts
@no_digits:
        lda #ERR_EXPECTED
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_binary — after %. Wide if result > $FF.
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
        sbc #'0'
        asl expr_val
        rol expr_val+1
        bcs @overflow_chk
        ora expr_val
        sta expr_val
        jsr _ex_adv_ptr
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
        lda expr_val+1
        beq :+
        lda #1
        ora expr_wide
        sta expr_wide
:       clc
        rts
@no_digits:
        lda #ERR_EXPECTED
        sec
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; hex_nybble — A = char → 0-15 (C=0) or C=1 if not hex
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
; expr_error_str — return pointer to error string
; ═══════════════════════════════════════════════════════════
.proc expr_error_str
        ldx last_err
        cpx #7                  ; 0-6 valid error codes
        bcc :+
        ldx #0
:       lda err_str_lo,x
        pha
        lda err_str_hi,x
        tax
        pla
        rts
.endproc

        .segment "RODATA"
err_str_lo:
        .byte <err_none, <err_none             ; 0=ZP, 1=ABS (not errors)
        .byte <err_expected, <err_overflow
        .byte <err_paren, <err_undefined
        .byte <err_divzero
err_str_hi:
        .byte >err_none, >err_none
        .byte >err_expected, >err_overflow
        .byte >err_paren, >err_undefined
        .byte >err_divzero

err_none:      .byte 0
err_expected:  .byte "expected value", 0
err_overflow:  .byte "overflow", 0
err_paren:     .byte "missing )", 0
err_undefined: .byte "undefined", 0
err_divzero:   .byte "division by zero", 0
