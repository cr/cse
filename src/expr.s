; expr.s — Expression parser (recursive descent)
; Owner: doc/modules/expr.md
;
; Grammar:
;   expr     = add_term (('£' | '&' | '^') add_term)*      [parse_expr]
;   add_term = mul_term (('+' | '-') mul_term)*             [parse_add]
;   mul_term = factor (('*' | '/' | '<<' | '>>') factor)*   [parse_mul]
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
;   7 = error: range (m65: outside -$FFFF..$FFFF for expr_eval; never
;       from expr_eval32)
;
; m65: values are 32 bits, expr_wide 3 = FAR; the literals, the flat
; literal H.AAAA and the range rules are expr.md § 32-bit values.
;
; Width rule:
;   - $XX (1-2 hex digits) → narrow
;   - $XXX/$XXXX (3-4 hex digits) → wide
;   - decimal, binary → width from value (>$FF = wide)
;   - label → inherits sym_wide from definition
;   - * → wide if PC > $FF
;   - < and > → always narrow (clear wide)
;   - - (negate), ! → width from result
;   - +, -, *, /, <<, >>, &, £, ^ → wide if either operand wide OR
;     result > $FF (the left operand's width is stacked with its value)

        .export expr_eval
        .export expr_eval_nb            ; no-banking variant for callers already banked out
        .export expr_error_str
        .export last_err                ; asm_line sets 3 (overflow) on a $FFFF wrap
        .export expr_fwd                ; bit 7: undefined read; other bits: sym_fwd read
.ifdef PLATFORM_M65
        .export expr_eval32             ; 32 bits, no range check (expr.md § 32-bit values)
        .export expr_bank               ; the bank a 16-bit consumer also takes
        .export expr_reset              ; an abandoned batch's state cleared
.endif

        .import sym_lookup, sym_fwd
        .import kernal_bank_out, kernal_bank_in
        .importzp sym_name, sym_val, sym_wide

; ── Imports: strings.s ──────────────────────────────────────
        .import err_str_lo, err_str_hi

; ── Return / error codes ───────────────────────────────────
RC_ZP        = 0
RC_ABS       = 1
ERR_EXPECTED = 2
ERR_OVERFLOW = 3
ERR_PAREN    = 4
ERR_UNDEFINED = 5
ERR_DIVZERO  = 6
ERR_RANGE    = 7                ; m65: outside -$FFFF..$FFFF for a 16-bit consumer

EXPR_FAR     = 3                ; m65 expr_wide: bit 1 FAR (FAR implies ABS)

EXPR_MAX_DEPTH = 10             ; nested factor levels: each '(' or unary prefix

; ── ZP imports ─────────────────────────────────────────────
.importzp expr_ptr, expr_val, expr_wide
.importzp asm_pc

; ── ZP scratch (m65: BSS, below) ───────────────────────────
.ifndef PLATFORM_M65
.importzp _ex_tmp, _ex_digits
.endif

; ── BSS ────────────────────────────────────────────────────
.segment "BSS"
last_err:    .res 1
_ex_depth:   .res 1              ; parse_factor nesting depth (reset per eval)
expr_fwd:    .res 1              ; bit 7: undefined read; other bits: sym_fwd read
.ifdef PLATFORM_M65
_ex_tmp:     .res 4              ; the left operand; parse_decimal's x10
_ex_digits:  .res 1              ; digit counter
_mul_tmp:    .res 4              ; multiply: shifted operand; divide: trial
_div_rem:    .res 4              ; divide: remainder
_ex_far:     .res 1              ; bit 7: this evaluation takes 32 bits
expr_bank:   .res 2              ; a top word the range check also passes
_ex_sp:      .res 1              ; the operand stack's top (bytes)
; The pending left operands, one entry per operator waiting for its
; right operand: the operator, the width, the 4 value bytes.  At most
; three per expression level (one each in parse_expr / _add / _mul),
; and the depth guard admits 11 levels.
EX_ENTRY     = 6
EX_STK_SIZE  = 3 * (EXPR_MAX_DEPTH + 1) * EX_ENTRY
_ex_stk:     .res EX_STK_SIZE
.else
_mul_tmp:    .res 2              ; multiply: shifted operand copy
_div_rem:    .res 2              ; divide: remainder
.endif

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
; sym_lookup calls keep this banking (they save and restore $01;
; inside an asm_assemble batch, kernal_out=1 makes both helpers
; no-ops).  Either way, callers of expr_eval never need to think
; about KERNAL banking.
;
; Same wrapper structure as asm_line and dasm_insn.
;
; m65: expr_eval32 is the same evaluation without the range check
; (expr.md § 32-bit values): a 32-bit consumer's entry.
; ═══════════════════════════════════════════════════════════
.ifdef PLATFORM_M65
expr_eval32:
        lda #$80
        sta _ex_far             ; this evaluation takes 32 bits
.endif
.proc expr_eval
        jsr kernal_bank_out      ; (no-op inside an asm batch)
        jsr _expr_eval_inner
        pha                      ; save A across bank_in
        jsr kernal_bank_in
        pla
        rts
.endproc

; ── _expr_eval_inner / expr_eval_nb — the actual evaluator ──
; Runs with KERNAL banked out (or pre-banked by an outer batch).
; expr_eval_nb is the public alias for callers already banked out
; (mode_parse inside asm_line).
; Returns A = 0 (ZP), 1 (ABS), or 2+ (error).
.ifdef PLATFORM_M65
; m65: a value outside -$FFFF..$FFFF is ERR_RANGE unless expr_eval32
; asked for 32 bits; a value inside keeps its low word for the 16-bit
; consumer (-1 is $FFFF, as on the c64).  The opt-in ends here.
expr_eval_nb:
.proc _expr_eval_inner
        lda #0
        sta expr_wide            ; start narrow
        sta _ex_depth
        sta expr_fwd
        sta _ex_sp               ; the operand stack: empty
        jsr skip_sp
        jsr parse_expr
        bcs @out                 ; A = the error
        lda #ERR_UNDEFINED       ; soft error: parsed through an
        bit expr_fwd             ; undefined symbol
        bmi @out
        bit _ex_far
        bmi @ok                  ; 32 bits asked for
        lda expr_val+2
        ora expr_val+3
        beq @ok                  ; 0 .. $FFFF
        lda expr_val+2           ; the caller's bank: its low word
        cmp expr_bank            ; (the same-bank rule)
        bne :+
        lda expr_val+3
        cmp expr_bank+1
        beq @ok
:       lda expr_val+2
        and expr_val+3
        cmp #$FF
        bne @range
        lda expr_val
        ora expr_val+1
        bne @ok                  ; -$FFFF .. -1
@range: lda #ERR_RANGE
        bne @out
@ok:    lda expr_wide
        ora expr_val+1
        beq @out                 ; A = RC_ZP: narrow, <= $FF
        lda #RC_ABS
@out:   sta last_err
        ldx #0
        stx _ex_far              ; the opt-in lasts one evaluation
        rts
.endproc
.else
expr_eval_nb:
.proc _expr_eval_inner
        lda #0
        sta expr_wide            ; start narrow
        sta _ex_depth
        sta expr_fwd
        jsr skip_sp
        jsr parse_expr
        bcs @err
        bit expr_fwd             ; parsed through an undefined symbol?
        bpl :+
        lda #ERR_UNDEFINED       ; soft error: expr_ptr is past the
        bne @err                 ; whole expression (always)
:       ; Success: determine return code from wide flag
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
.endif

; ── Shared helpers for binary-op parsers ──────────────────
; _ex_adv_ptr: advance expr_ptr by 1
_ex_adv_ptr:
        inc expr_ptr
        bne :+
        inc expr_ptr+1
:       rts

.ifdef PLATFORM_M65
; _ex_op_setup — common binary operator preamble
;   Advances past operator char(s), skips whitespace.
;   Caller then pushes expr_wide, expr_val hi, expr_val lo.
;   Call sites: jsr _ex_op_setup  (single-char operator)
;              jsr _ex_op_setup_2adv  (two-char operator like << >>)
_ex_op_setup_2adv:
        jsr _ex_adv_ptr
_ex_op_setup:
        jsr _ex_adv_ptr
        jmp skip_sp

; ═══════════════════════════════════════════════════════════
; m65: the binary operators in 32 bits (expr.md § 32-bit values).
; A pending left operand waits on the operand stack (_ex_stk, BSS),
; not the hardware stack: the operator, its width, its 4 bytes.  An
; error returns at once; _expr_eval_inner empties the stack for the
; next evaluation.
; ═══════════════════════════════════════════════════════════
OP_AND = 0                      ; parse_expr's: the right operand a parse_add
OP_OR  = 1
OP_XOR = 2
OP_ADD = 3                      ; parse_add's: a parse_mul
OP_SUB = 4
OP_MUL = 5                      ; parse_mul's: a parse_factor
OP_DIV = 6
OP_SHL = 7                      ; two characters from here
OP_SHR = 8

.proc parse_expr
        jsr parse_add
        bcs @done
@op:    jsr skip_sp             ; A = the character
        ldy #OP_AND
        cmp #'&'
        beq @bin
        iny
        cmp #$5C                ; £ = OR (pound sign)
        beq @bin
        iny
        cmp #'^'
        beq @bin
        clc
@done:  rts
@bin:   jsr _ex_binop
        bcc @op
        rts
.endproc

.proc parse_add
        jsr parse_mul
        bcs @done
@op:    jsr skip_sp
        ldy #OP_ADD
        cmp #'+'
        beq @bin
        iny
        cmp #'-'
        beq @bin
        clc
@done:  rts
@bin:   jsr _ex_binop
        bcc @op
        rts
.endproc

; '*' alone (no operator context) = PC in parse_factor; here it is
; the binary multiply.
.proc parse_mul
        jsr parse_factor
        bcs @done
@op:    jsr skip_sp             ; A = the character, Y = 0
        iny                     ; Y = 1: the next character
        cmp #'*'
        beq @mul
        cmp #'/'
        beq @div
        cmp #'<'
        beq @shl
        cmp #'>'
        bne @done_clc
        cmp (expr_ptr),y        ; '>>'; a single > ends the expression
        bne @done_clc
        ldy #OP_SHR
        bne @bin
@shl:   cmp (expr_ptr),y        ; '<<'
        bne @done_clc
        ldy #OP_SHL
        bne @bin
@div:   cmp (expr_ptr),y        ; '//' starts a comment: not a divide
        beq @done_clc
        ldy #OP_DIV
        bne @bin
@mul:   ldy #OP_MUL
@bin:   jsr _ex_binop
        bcc @op
        rts
@done_clc:
        clc
@done:  rts
.endproc

; ── _ex_binop — the operator Y at expr_ptr: push the left operand,
;    parse the right one a level tighter, pop the left into _ex_tmp,
;    merge the widths and run the operator (it returns to our caller:
;    expr_val the result, C=0; or C=1, A = the error) ──────────
.proc _ex_binop
        ldx _ex_sp
        cpx #EX_STK_SIZE        ; never at the depth limit; a guard
        bcc :+
        lda #ERR_OVERFLOW       ; C=1
        rts
:       tya
        sta _ex_stk,x           ; the operator
        lda expr_wide
        sta _ex_stk+1,x         ; the left operand's width
        lda expr_val
        sta _ex_stk+2,x
        lda expr_val+1
        sta _ex_stk+3,x
        lda expr_val+2
        sta _ex_stk+4,x
        lda expr_val+3
        sta _ex_stk+5,x
        txa
        adc #EX_ENTRY           ; C=0 from the cpx
        sta _ex_sp
        cpy #OP_SHL
        bcc :+
        jsr _ex_adv_ptr         ; << >>: two characters
:       jsr _ex_op_setup
        ldx _ex_sp
        lda _ex_stk-EX_ENTRY,x  ; the operator again
        cmp #OP_ADD
        bcs :+
        jsr parse_add
        jmp @got
:       cmp #OP_MUL
        bcs :+
        jsr parse_mul
        jmp @got
:       jsr parse_factor
@got:   bcs @r                  ; the error in A
        lda _ex_sp
        sec
        sbc #EX_ENTRY
        sta _ex_sp
        tax
        lda _ex_stk+2,x
        sta _ex_tmp
        lda _ex_stk+3,x
        sta _ex_tmp+1
        lda _ex_stk+4,x
        sta _ex_tmp+2
        lda _ex_stk+5,x
        sta _ex_tmp+3
        lda _ex_stk+1,x         ; the left operand's width
        ora expr_wide
        sta expr_wide
        ldy _ex_stk,x
        lda _ex_op_hi,y
        pha
        lda _ex_op_lo,y
        pha
@r:     rts                     ; → the operator
.endproc

; The operators: _ex_tmp (left) op expr_val (right) → expr_val, then
; the result's class into expr_wide (_ex_class: C=0).
.proc _ex_ops
and4:   ldx #3
:       lda _ex_tmp,x
        and expr_val,x
        sta expr_val,x
        dex
        bpl :-
        jmp _ex_class
or4:    ldx #3
:       lda _ex_tmp,x
        ora expr_val,x
        sta expr_val,x
        dex
        bpl :-
        jmp _ex_class
xor4:   ldx #3
:       lda _ex_tmp,x
        eor expr_val,x
        sta expr_val,x
        dex
        bpl :-
        jmp _ex_class
add4:   jsr _ex_add4
        jmp _ex_class
sub4:   ldx #0
        sec
:       lda _ex_tmp,x
        sbc expr_val,x
        sta expr_val,x
        inx
        txa                     ; (no compare: C is the borrow)
        eor #4
        bne :-
        jmp _ex_class

; ── multiply: shift-and-add over 32 bits; the result wraps ──
mul4:   ldx #3
:       lda expr_val,x
        sta _mul_tmp,x          ; the right operand, shifted right
        lda #0
        sta expr_val,x          ; the product
        dex
        bpl :-
        ldy #32
@ml:    lsr _mul_tmp+3
        ror _mul_tmp+2
        ror _mul_tmp+1
        ror _mul_tmp
        bcc :+
        jsr _ex_add4            ; + the left operand, shifted left
:       asl _ex_tmp
        rol _ex_tmp+1
        rol _ex_tmp+2
        rol _ex_tmp+3
        dey
        bne @ml
        jmp _ex_class

; ── divide: unsigned 32 / 32, shift-and-subtract; the remainder
;    never needs a 33rd bit (it stays below the divisor) ──
div4:   lda expr_val
        ora expr_val+1
        ora expr_val+2
        ora expr_val+3
        bne :+
        lda #ERR_DIVZERO
        sec
        rts
:       lda #0
        ldx #3
:       sta _div_rem,x
        dex
        bpl :-
        ldy #32
@dl:    asl _ex_tmp             ; the dividend's top bit into the
        rol _ex_tmp+1           ; remainder; bit 0 takes the quotient
        rol _ex_tmp+2
        rol _ex_tmp+3
        rol _div_rem
        rol _div_rem+1
        rol _div_rem+2
        rol _div_rem+3
        ldx #0                  ; trial: remainder - divisor
        sec
:       lda _div_rem,x
        sbc expr_val,x
        sta _mul_tmp,x
        inx
        txa
        eor #4
        bne :-
        bcc @ds                 ; remainder < divisor
        ldx #3
:       lda _mul_tmp,x
        sta _div_rem,x
        dex
        bpl :-
        inc _ex_tmp             ; a quotient bit
@ds:    dey
        bne @dl
        jmp _ex_tmp_val

; ── shifts: a count of 32 or more shifts every bit out ──
shl4:   jsr _ex_count
        bcs _ex_tmp_val
        txa
        beq _ex_tmp_val
:       asl _ex_tmp
        rol _ex_tmp+1
        rol _ex_tmp+2
        rol _ex_tmp+3
        dex
        bne :-
        beq _ex_tmp_val
shr4:   jsr _ex_count
        bcs _ex_tmp_val
        txa
        beq _ex_tmp_val
:       lsr _ex_tmp+3
        ror _ex_tmp+2
        ror _ex_tmp+1
        ror _ex_tmp
        dex
        bne :-
        ; fall through
.endproc

; _ex_tmp_val — expr_val := _ex_tmp, then _ex_class
_ex_tmp_val:
        ldx #3
:       lda _ex_tmp,x
        sta expr_val,x
        dex
        bpl :-
        ; fall through
; _ex_class — OR the class of expr_val into expr_wide: FAR above
; $FFFF, ABS above $FF.  C=0.
_ex_class:
        lda expr_val+2
        ora expr_val+3
        beq @n
        lda #EXPR_FAR
        bne @or
@n:     lda expr_val+1
        beq @r
        lda #1
@or:    ora expr_wide
        sta expr_wide
@r:     clc
        rts

; _ex_add4 — expr_val += _ex_tmp; C = the carry out.  Clobbers A, X.
_ex_add4:
        ldx #0
        clc
:       lda expr_val,x
        adc _ex_tmp,x
        sta expr_val,x
        inx
        txa
        eor #4
        bne :-
        rts

; _ex_count — the shift count expr_val: X = it if below 32 (C=0); else
; _ex_tmp := 0, C=1 (every bit shifts out).
_ex_count:
        ldx expr_val
        lda expr_val+1
        ora expr_val+2
        ora expr_val+3
        bne @out
        cpx #32
        bcc @r
@out:   lda #0
        sta _ex_tmp
        sta _ex_tmp+1
        sta _ex_tmp+2
        sta _ex_tmp+3
        sec
@r:     rts

; _ex_zero — expr_val := 0, _ex_digits := 0.  Clobbers A, X.
_ex_zero:
        lda #0
        sta _ex_digits
        ldx #3
:       sta expr_val,x
        dex
        bpl :-
        rts

.segment "RODATA"
_ex_op_lo:
        .byte <(_ex_ops::and4-1), <(_ex_ops::or4-1), <(_ex_ops::xor4-1)
        .byte <(_ex_ops::add4-1), <(_ex_ops::sub4-1), <(_ex_ops::mul4-1)
        .byte <(_ex_ops::div4-1), <(_ex_ops::shl4-1), <(_ex_ops::shr4-1)
_ex_op_hi:
        .byte >(_ex_ops::and4-1), >(_ex_ops::or4-1), >(_ex_ops::xor4-1)
        .byte >(_ex_ops::add4-1), >(_ex_ops::sub4-1), >(_ex_ops::mul4-1)
        .byte >(_ex_ops::div4-1), >(_ex_ops::shl4-1), >(_ex_ops::shr4-1)
.segment "CODE"

.else
; _ex_pop_err: discard stacked left operand + width, propagate error in A (C=1)
_ex_pop_err:
        tax
        pla
        pla
        pla
        txa
        sec
        rts

; _ex_merge_wide: merge the left operand's width (in A, pulled from the
; stack by the caller) + detect a 16-bit result
_ex_merge_wide:
        ora expr_wide
        sta expr_wide
        lda expr_val+1
        beq :+
        lda #1
        sta expr_wide
:       rts

; _ex_op_setup — common binary operator preamble
;   Advances past operator char(s), skips whitespace.
;   Caller then pushes expr_wide, expr_val hi, expr_val lo.
;   Call sites: jsr _ex_op_setup  (single-char operator)
;              jsr _ex_op_setup_2adv  (two-char operator like << >>)
_ex_op_setup_2adv:
        jsr _ex_adv_ptr
_ex_op_setup:
        jsr _ex_adv_ptr
        jmp skip_sp

; ═══════════════════════════════════════════════════════════
; parse_expr — add_term (('&' | '£' | '^') add_term)*
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

@and:   jsr _ex_op_setup
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

@or:    jsr _ex_op_setup
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

@xor:   jsr _ex_op_setup
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

@bool_err:
        jmp _ex_pop_err
@merge_wide:
        jmp _ex_merge_wide
.endproc

; ═══════════════════════════════════════════════════════════
; parse_add — mul_term (('+' | '-') mul_term)*
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

@add:   jsr _ex_op_setup
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

@sub:   jsr _ex_op_setup
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

@add_err:
        jmp _ex_pop_err
@merge_wide:
        jmp _ex_merge_wide
.endproc

; ═══════════════════════════════════════════════════════════
; parse_mul — factor (('*' | '/' | '<<' | '>>') factor)*
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
        bne @chk_shl
        ldy #1                  ; '//' starts a comment: not a divide
        cmp (expr_ptr),y
        bne @div
        beq @done_clc
@chk_shl:
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
@mul:   jsr _ex_op_setup
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

; ── divide ────────────────────────────────────────────
@div:   jsr _ex_op_setup
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

@mul_err:
        jmp _ex_pop_err
@divzero:
        pla
        pla
        pla
        lda #ERR_DIVZERO
        sec
        rts

; ── shift left ────────────────────────────────────────
@shl:   jsr _ex_op_setup_2adv           ; skip << + save
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
        lda expr_val+1
        pha
        lda expr_val
        pha
        jsr parse_factor
        bcs @mul_err
        ; Left shift: left << right (16-bit count; >= 16 → 0)
        pla
        sta _ex_tmp
        pla
        sta _ex_tmp+1
        jsr @shift_count        ; X = count 0..15, or C=1: all out
        bcs @shl_done
        txa
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

; ── shift right ───────────────────────────────────────
@shr:   jsr _ex_op_setup_2adv           ; skip >> + save
        lda expr_wide           ; left operand's width, stacked (nests)
        pha
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
        jsr @shift_count        ; X = count 0..15, or C=1: all out
        bcs @shr_done
        txa
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
        pla                     ; left operand's width
        jsr @merge_wide
        jmp @op

; ── shift count: X = expr_val if < 16 (C=0); else zero the operand,
;    C=1 (every bit shifts out — expr.md § Caveats) ───────
@shift_count:
        ldx expr_val
        lda expr_val+1
        bne @all_out
        cpx #16
        bcc @cnt_ok
@all_out:
        lda #0
        sta _ex_tmp
        sta _ex_tmp+1
        sec
@cnt_ok:
        rts

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

.endif

; ═══════════════════════════════════════════════════════════
; parse_factor — single value or unary operator
;   Depth guard: every '(' and unary prefix recurses through here,
;   so counting entries bounds the recursion (and its stack use) at
;   EXPR_MAX_DEPTH levels; one more returns ERR_OVERFLOW.  `dec`
;   keeps the body's A and C.
; ═══════════════════════════════════════════════════════════
parse_factor:
        inc _ex_depth
        lda _ex_depth
        cmp #EXPR_MAX_DEPTH+2   ; levels above the innermost value
        bcs @deep
        jsr _parse_factor_body
        dec _ex_depth
        rts
@deep:  lda #ERR_OVERFLOW        ; C=1 from the cmp
        rts

.proc _parse_factor_body
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

        ; label (a-z, or shifted-uppercase $C1-$DA folded in-place)
@chk_label:
        ; Fold shifted uppercase $C1-$DA → $41-$5A in-place (mirrors @lscan).
        ; Without this, a symbol whose first char is SHIFT+letter on the C64
        ; (PETSCII $C1-$DA) is rejected as "expected expression".
        cmp #$C1
        bcc @cnoshift
        cmp #$DB
        bcs @cnoshift
        sec
        sbc #$80
        ldy #0
        sta (expr_ptr),y        ; fold in-place so sym_lookup sees $41-$5A
@cnoshift:
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
.ifdef PLATFORM_M65
        lda #0                  ; the low word (F5b: flat)
        sta expr_val+2
        sta expr_val+3
.endif
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
.ifdef PLATFORM_M65
        sta expr_val+2
        sta expr_val+3
.endif
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
.ifdef PLATFORM_M65
        sta expr_val+2
        sta expr_val+3
.endif
        sta expr_wide            ; > always produces ZP
        clc
@ret2:  rts

; ── ! (complement / NOT) ──────────────────────────────
@complement:
        jsr _ex_adv_ptr
        jsr parse_factor
        bcs @ret2               ; error: keep C=1 and the code in A
.ifdef PLATFORM_M65
        ldx #3
:       lda expr_val,x
        eor #$FF
        sta expr_val,x
        dex
        bpl :-
        jmp _ex_class
.else
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
.endif

; ── - (negate / unary minus) ──────────────────────────
@negate:
        jsr _ex_adv_ptr
        jsr parse_factor
        bcs @ret2               ; error: keep C=1 and the code in A
.ifdef PLATFORM_M65
        ldx #0                  ; 0 - the value, over 4 bytes
        sec
:       lda #0
        sbc expr_val,x
        sta expr_val,x
        inx
        txa
        eor #4
        bne :-
        jmp _ex_class
.endif
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
        ; Fold shifted uppercase $C1-$DA → $41-$5A in-place
        cmp #$C1
        bcc @lnoshift
        cmp #$DB
        bcs @lnoshift
        sec
        sbc #$80
        ldy #0
        sta (expr_ptr),y        ; fold in-place
@lnoshift:
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
        ; sym_val, sym_wide, sym_fwd set by lookup.  A forward read
        ; (defined later in this pass) is wide: pass 0 sized it ABS.
.ifdef PLATFORM_M65
        ldx #3                  ; the symbol's 32 bits
:       lda sym_val,x
        sta expr_val,x
        dex
        bpl :-
.else
        lda sym_val
        sta expr_val
        lda sym_val+1
        sta expr_val+1
.endif
        lda sym_fwd
        ora expr_fwd
        sta expr_fwd
        lda sym_wide
        ora sym_fwd
        ora expr_wide
        sta expr_wide
.ifdef PLATFORM_M65
        jmp _ex_class           ; FAR when above $FFFF
.else
        clc
        rts
.endif

@err_undef:                      ; undefined: read as 0 (wide), note it,
        lda #$80                 ; and parse on (expr.md § Undefined symbols)
        sta expr_fwd
        lda #0
        sta expr_val
        sta expr_val+1
.ifdef PLATFORM_M65
        sta expr_val+2
        sta expr_val+3
.endif
        lda #1
        sta expr_wide
        clc
        rts
.endproc

.ifdef PLATFORM_M65
; ═══════════════════════════════════════════════════════════
; m65: the literals in 32 bits (expr.md § 32-bit values).
; parse_hex — 1-8 hex digits: 3-4 wide, 5-8 FAR; a ninth is ovfl.
; ═══════════════════════════════════════════════════════════
.proc parse_hex
        jsr _ex_zero
@loop:  PEEK_CHAR
        jsr hex_nybble
        bcs @done
        ldx _ex_digits
        cpx #8
        bcs @ovfl               ; a ninth digit
        ldx #4
:       asl expr_val
        rol expr_val+1
        rol expr_val+2
        rol expr_val+3
        dex
        bne :-
        ora expr_val
        sta expr_val
        jsr _ex_adv_ptr
        inc _ex_digits
        bne @loop               ; always
@ovfl:  lda #ERR_OVERFLOW       ; C=1 from the cpx
        rts
@done:  lda _ex_digits
        beq _ex_no_digits
        cmp #3
        bcc @narrow
        ldx #1
        cmp #5
        bcc :+
        ldx #EXPR_FAR
:       txa
        ora expr_wide
        sta expr_wide
@narrow:
        clc
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_decimal — bare digits, up to $FFFFFFFF.  Width by value.
; A flat literal H.AAAA first (_ex_flat), as it begins with a digit.
; ═══════════════════════════════════════════════════════════
.proc parse_decimal
        jsr _ex_flat
        bcs :+
        rts                     ; C=0: a flat literal
:       jsr _ex_zero
@loop:  PEEK_CHAR
        cmp #'0'
        bcc @done
        cmp #'9'+1
        bcs @done
        and #$0F                ; the digit
        pha
        ldx #3                  ; val = val * 10 = (val * 4 + val) * 2
:       lda expr_val,x
        sta _ex_tmp,x
        dex
        bpl :-
        jsr @shl1
        bcs @ovfl_pla
        jsr @shl1
        bcs @ovfl_pla
        jsr _ex_add4
        bcs @ovfl_pla
        jsr @shl1
        bcs @ovfl_pla
        pla                     ; val += digit
        adc expr_val            ; C=0
        sta expr_val
        bcc @next
        inc expr_val+1
        bne @next
        inc expr_val+2
        bne @next
        inc expr_val+3
        beq @ovfl               ; carried out of bit 31
@next:  jsr _ex_adv_ptr
        inc _ex_digits
        jmp @loop
@ovfl_pla:
        pla
@ovfl:  lda #ERR_OVERFLOW
        sec
        rts
@done:  lda _ex_digits
        beq _ex_no_digits
        jmp _ex_class
@shl1:  asl expr_val
        rol expr_val+1
        rol expr_val+2
        rol expr_val+3
        rts
.endproc

_ex_no_digits:
        lda #ERR_EXPECTED
        sec
        rts

; ═══════════════════════════════════════════════════════════
; parse_binary — after %: up to 32 digits.  Width by value.
; ═══════════════════════════════════════════════════════════
.proc parse_binary
        jsr _ex_zero
@loop:  PEEK_CHAR
        cmp #'0'
        beq @bit
        cmp #'1'
        bne @done
@bit:   ldx _ex_digits
        cpx #32
        bcs @ovfl               ; a 33rd digit
        lsr                     ; '0' / '1': bit 0 into C
        rol expr_val
        rol expr_val+1
        rol expr_val+2
        rol expr_val+3
        jsr _ex_adv_ptr
        inc _ex_digits
        bne @loop               ; always
@ovfl:  lda #ERR_OVERFLOW       ; C=1 from the cpx
        rts
@done:  lda _ex_digits
        beq _ex_no_digits
        jmp _ex_class
.endproc

; ═══════════════════════════════════════════════════════════
; _ex_flat — a flat literal at expr_ptr (repl.md § Banks): one to four
; hex digits valued up to $FFF (the bank word), a dot, exactly four
; hex digits.  C=0: parsed — expr_val = the 28-bit address, FAR,
; expr_ptr past it.  C=1: not that shape (expr_ptr kept; the caller
; reads a decimal).  The first character is a digit (the caller's).
; ═══════════════════════════════════════════════════════════
.proc _ex_flat
        jsr _ex_zero
        tay                     ; Y = 0
@bank:  lda (expr_ptr),y
        jsr hex_nybble
        bcs @dot
        cpy #4
        bcs @no                 ; a fifth digit
        ldx #4
:       asl expr_val+2
        rol expr_val+3
        dex
        bne :-
        ora expr_val+2
        sta expr_val+2
        iny
        bne @bank               ; always
@dot:   lda expr_val+3
        cmp #$10
        bcs @no                 ; above $FFF
        lda (expr_ptr),y
        cmp #'.'
        bne @no
        lda #4
        sta _ex_digits
@off:   iny
        lda (expr_ptr),y
        jsr hex_nybble
        bcs @no
        ldx #4
:       asl expr_val
        rol expr_val+1
        dex
        bne :-
        ora expr_val
        sta expr_val
        dec _ex_digits
        bne @off
        iny
        lda (expr_ptr),y
        jsr hex_nybble
        bcc @no                 ; a fifth offset digit
        tya                     ; past the literal
        clc
        adc expr_ptr
        sta expr_ptr
        bcc :+
        inc expr_ptr+1
:       lda #EXPR_FAR
        ora expr_wide
        sta expr_wide
        clc
        rts
@no:    sec
        rts
.endproc

.else
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

.endif

; ═══════════════════════════════════════════════════════════
; hex_nybble — A = char → 0-15 (C=0) or C=1 if not hex
; ═══════════════════════════════════════════════════════════
.proc hex_nybble
        cmp #$30                ; '0'
        bcc @bad
        cmp #$3A                ; '9'+1
        bcc @digit
        ora #$20                ; fold uppercase $41-$46 → $61-$66
        cmp #$61                ; 'a'
        bcc @bad
        cmp #$67                ; 'f'+1
        bcs @bad
        sec
        sbc #$61-10             ; 'a'-10
        clc
        rts
@digit: sec
        sbc #$30                ; '0'
        clc
        rts
@bad:   sec
        rts
.endproc

.ifdef PLATFORM_M65
; ═══════════════════════════════════════════════════════════
; expr_reset — no bank, no 32-bit opt-in: after RESTORE abandoned an
; assembly or an evaluation (main.md § refresh_body).  Clobbers A.
; ═══════════════════════════════════════════════════════════
.proc expr_reset
        lda #0
        sta _ex_far
        sta expr_bank
        sta expr_bank+1
        rts
.endproc
.endif

; ═══════════════════════════════════════════════════════════
; expr_error_str — return pointer to error string
; ═══════════════════════════════════════════════════════════
.proc expr_error_str
        ldx last_err
.ifdef PLATFORM_M65
        cpx #ERR_RANGE+1        ; 0-7 valid error codes
.else
        cpx #7                  ; 0-6 valid error codes
.endif
        bcc :+
        ldx #0
:       lda err_str_lo,x
        pha
        lda err_str_hi,x
        tax
        pla
        rts
.endproc

