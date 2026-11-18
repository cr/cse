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

        .import sym_lookup, sym_fwd
        .import kernal_bank_out, kernal_bank_in
        .importzp sym_name, sym_val, sym_wide

; ── Imports: strings.s ──────────────────────────────────────
        .import err_str_lo, err_str_hi
        .import err_none, err_expected, err_overflow
        .import err_paren, err_undefined, err_divzero

; ── Return / error codes ───────────────────────────────────
RC_ZP        = 0
RC_ABS       = 1
ERR_EXPECTED = 2
ERR_OVERFLOW = 3
ERR_PAREN    = 4
ERR_UNDEFINED = 5
ERR_DIVZERO  = 6

EXPR_MAX_DEPTH = 10             ; nested factor levels: each '(' or unary prefix

; ── ZP imports ─────────────────────────────────────────────
.importzp expr_ptr, expr_val, expr_wide
.importzp asm_pc

; ── ZP scratch ─────────────────────────────────────────────
.importzp _ex_tmp, _ex_digits

; ── BSS ────────────────────────────────────────────────────
.segment "BSS"
last_err:    .res 1
_ex_depth:   .res 1              ; parse_factor nesting depth (reset per eval)
expr_fwd:    .res 1              ; bit 7: undefined read; other bits: sym_fwd read
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
; sym_lookup calls keep this banking (they save and restore $01;
; inside an asm_assemble batch, kernal_out=1 makes both helpers
; no-ops).  Either way, callers of expr_eval never need to think
; about KERNAL banking.
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

; ── _expr_eval_inner / expr_eval_nb — the actual evaluator ──
; Runs with KERNAL banked out (or pre-banked by an outer batch).
; expr_eval_nb is the public alias for callers already banked out
; (mode_parse inside asm_line).
; Returns A = 0 (ZP), 1 (ABS), or 2+ (error).
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

; ── Shared helpers for binary-op parsers ──────────────────
; _ex_adv_ptr: advance expr_ptr by 1
_ex_adv_ptr:
        inc expr_ptr
        bne :+
        inc expr_ptr+1
:       rts

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
        bcs @ret2               ; error: keep C=1 and the code in A
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
        bcs @ret2               ; error: keep C=1 and the code in A
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
        lda sym_val
        sta expr_val
        lda sym_val+1
        sta expr_val+1
        lda sym_fwd
        ora expr_fwd
        sta expr_fwd
        lda sym_wide
        ora sym_fwd
        ora expr_wide
        sta expr_wide
        clc
        rts

@err_undef:                      ; undefined: read as 0 (wide), note it,
        lda #$80                 ; and parse on (expr.md § Undefined symbols)
        sta expr_fwd
        lda #0
        sta expr_val
        sta expr_val+1
        lda #1
        sta expr_wide
        clc
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

