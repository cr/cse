; ─────────────────────────────────────────────────────────────────────────────
; au_mode.s  –  addressing-mode argument parser
;
; Parses a null-terminated PETSCII argument string.
; Operand values parsed by expr_eval_nb: $hex, %binary, decimal,
; labels, * (PC), and arithmetic expressions.
;
; Whitespace (space $20, tab $A0) is tolerated between tokens.
; End-of-expression: null ($00), CR ($0D), LF ($0A), ';', '//'.
; '#' terminates when it appears after the operand; at the start of the
; argument it is the IMM prefix ('#$nn') – '#' not followed by '$' → IMP.
;
; Entry:
;   asm_ptr (ZP word)  – pointer to argument string (PETSCII), set by caller
;   Y = 0
;
; Exit:
;   A   – mode index (0 = IMP .. 15 = ZPREL; matches ALL_MODES order in
;          dev/mnemonic_tables.py)
;   X   – operand byte count (0, 1, or 2)
;   asm_opr[0]  – first (or only) operand byte
;   asm_opr[1]  – second operand byte  (absolute addresses: hi byte;
;                 ZPREL: relative offset)
;   For 2-byte absolute addresses $nnnn the bytes are little-endian:
;     asm_opr[0] = lo byte ($nn), asm_opr[1] = hi byte ($nn)
;
; Error: jmp asm_syntax_error (does not return)
; ─────────────────────────────────────────────────────────────────────────────

        .setcpu "6502"

        .export mode_parse              ; main entry point
        .export asm_skip_ws             ; used by asm_line.s
        .import asm_syntax_error        ; provided by caller / test stub
        .import expr_eval_nb            ; no-banking expr evaluator (expr.s)
        .import asm_pass                ; 0=pass 0 (sizing), 1=pass 1 (emit)
        .importzp expr_ptr, expr_val, expr_wide
        .importzp asm_pc                ; for forward-ref dummy value
        .importzp asm_ptr, asm_opr

; ── PETSCII character constants ──────────────────────────────────────────────
SC_LF   = $0A   ; line feed
SC_CR   = $0D   ; carriage return
SC_A    = $41   ; 'A'  (accumulator)
SC_X    = $58   ; 'X'
SC_Y    = $59   ; 'Y'
SC_HASH = $23   ; '#'  (IMM prefix / trailing comment start)
SC_LPAR = $28   ; '('
SC_RPAR = $29   ; ')'
SC_COMM = $2C   ; ','
SC_SLASH= $2F   ; '/'
SC_SEMI = $3B   ; ';'

; ── Mode indices (mirror ALL_MODES order in dev/mnemonic_tables.py) ───────────
MODE_IMP  = 0   ; implied / inherent            –
MODE_ACC  = 1   ; accumulator                   A
MODE_IMM  = 2   ; immediate                     #$nn
MODE_ZP   = 3   ; zero page                     $nn
MODE_ZPX  = 4   ; zero page, X                  $nn,X
MODE_ZPY  = 5   ; zero page, Y                  $nn,Y
MODE_ABS  = 6   ; absolute                      $nnnn
MODE_ABX  = 7   ; absolute, X                   $nnnn,X
MODE_ABY  = 8   ; absolute, Y                   $nnnn,Y
MODE_IND  = 9   ; indirect                      ($nnnn)
MODE_INX  = 10  ; (indirect, X)                 ($nn,X)
MODE_INY  = 11  ; (indirect), Y                 ($nn),Y
MODE_REL  = 12  ; relative  NOTE: syntactically = ZP; Zone B assembler path
                ;                 remaps ZP→REL and treats asm_opr[0] as offset
MODE_ZPI  = 13  ; (zero page)  [65C02]          ($nn)
MODE_AIX  = 14  ; (absolute, X)  [65C02 JMP]    ($nnnn,X)
MODE_ZPREL= 15  ; zero page + relative  [65C02]  $nn,$rr

; ── Code ──────────────────────────────────────────────────────────────────────
        .segment "CODE"

; ─── asm_skip_ws ─────────────────────────────────────────────────────────────
; Advance Y past spaces ($20) and tabs ($A0).
asm_skip_ws:
        lda (asm_ptr),y
        cmp #$20                ; space
        beq @eat
        cmp #$a0                ; tab (SHIFT+SPACE)
        beq @eat
        rts
@eat:   iny
        bne asm_skip_ws         ; (Y wraps at 256 – safe for any sane line length)
        rts

; ─── _au_is_end ──────────────────────────────────────────────────────────────
; Test A for end-of-expression: null, LF, CR, ';', '//'.
; NOTE: '#' is NOT tested here; it is handled separately in _au_check_end and
;       at the start of mode_parse (where it is the IMM prefix).
; Returns: C=1 if end/comment, C=0 otherwise.  May clobber A.
_au_is_end:
        beq @yes                ; $00 (null)
        cmp #SC_LF
        beq @yes
        cmp #SC_CR
        beq @yes
        cmp #SC_SEMI            ; ';'
        beq @yes
        cmp #SC_SLASH           ; '/' – check for '//'
        bne @no
        iny                     ; peek next byte
        lda (asm_ptr),y
        dey
        cmp #SC_SLASH
        beq @yes
@no:    clc
        rts
@yes:   sec
        rts

; ─── _au_check_end ───────────────────────────────────────────────────────────
; Skip whitespace, then require end-of-expression (null, LF, CR, ';', '//', '#').
; Jumps to asm_syntax_error if any other (non-comment) character follows.
; Used after every successfully-parsed operand token.
_au_check_end:
        jsr asm_skip_ws
        lda (asm_ptr),y
        beq @ok                 ; null
        cmp #SC_LF
        beq @ok
        cmp #SC_CR
        beq @ok
        cmp #SC_SEMI            ; ';'
        beq @ok
        cmp #SC_HASH            ; '#'  (trailing comment, post-operand)
        beq @ok
        cmp #SC_SLASH           ; '//' ?
        bne @err
        iny
        lda (asm_ptr),y
        dey
        cmp #SC_SLASH
        beq @ok
@err:   jmp asm_syntax_error
@ok:    rts

; ─── _au_expect_rpar ─────────────────────────────────────────────────────────
; Require A == ')'.  jmp asm_syntax_error if not.
_au_expect_rpar:
        cmp #SC_RPAR
        beq :+
        jmp asm_syntax_error
:       rts

; ─── _au_expect_x ────────────────────────────────────────────────────────────
; Require A == 'X' (PETSCII $58).  jmp asm_syntax_error if not.
_au_expect_x:
        cmp #SC_X
        beq :+
        jmp asm_syntax_error
:       rts

; ─── _au_read_val ────────────────────────────────────────────────────────────
; Parse an operand value via expr_eval_nb.  Advances asm_ptr by Y first,
; syncs to expr_ptr, calls expr_eval_nb, stores result in asm_opr.
;
; Out:  A = 0 (ZP/narrow) or 1 (ABS/wide)
;       asm_opr[0..1] = little-endian value from expr_val
;       asm_ptr updated past consumed expression; Y = 0
; Error (bad expression): jmp asm_syntax_error
_au_read_val:
        ; Advance asm_ptr by Y (commit chars consumed so far)
        tya
        clc
        adc asm_ptr
        sta asm_ptr
        bcc :+
        inc asm_ptr+1
:
        ; Sync asm_ptr → expr_ptr
        lda asm_ptr
        sta expr_ptr
        lda asm_ptr+1
        sta expr_ptr+1

        jsr expr_eval_nb

        ; Check for error (A >= 2)
        cmp #2
        bcc @val_ok

        ; Error — check for forward reference on pass 0
        cmp #5                  ; ERR_UNDEFINED?
        bne @err
        lda asm_pass
        bne @err                ; pass 1: real error
        ; Pass 0: substitute dummy value (asm_pc+2) for sizing
        lda asm_pc
        clc
        adc #2
        sta expr_val
        lda asm_pc+1
        adc #0
        sta expr_val+1
        lda #1
        sta expr_wide           ; force ABS (conservative sizing)

@val_ok:
        ; Save width result
        pha

        ; Copy expr_val → asm_opr
        lda expr_val
        sta asm_opr
        lda expr_val+1
        sta asm_opr+1

        ; Sync expr_ptr → asm_ptr (expr_eval advanced past expression)
        lda expr_ptr
        sta asm_ptr
        lda expr_ptr+1
        sta asm_ptr+1

        ldy #0
        pla                     ; A = 0 (ZP) or 1 (ABS)
        rts

@err:   jmp asm_syntax_error

; ─────────────────────────────────────────────────────────────────────────────
; mode_parse  –  main entry point
; ─────────────────────────────────────────────────────────────────────────────
mode_parse:
        jsr asm_skip_ws

        ; ── IMP: empty / end-of-expression ───────────────────────────────────
        lda (asm_ptr),y
        jsr _au_is_end
        bcs @ret_imp

        ; Reload: _au_is_end may have clobbered A (// lookahead).
        lda (asm_ptr),y

        ; ── ACC: bare 'A' (only if followed by end/whitespace, not ident) ─
        cmp #SC_A
        bne @not_acc
        ; Peek at char after 'A' — if it's a letter/digit, 'A' starts a label
        iny
        lda (asm_ptr),y
        dey                     ; restore Y=0
        ; Space, tab, NUL, ';', '#' → ACC;  letter/digit → label
        cmp #' '
        beq @is_acc
        cmp #$A0
        beq @is_acc
        cmp #0
        beq @is_acc
        cmp #SC_SEMI
        beq @is_acc
        cmp #SC_HASH
        beq @is_acc
        cmp #SC_SLASH           ; could be '//' comment
        beq @is_acc
        ; Anything else (letter, digit) → not ACC, fall through
        lda #SC_A
        jmp @not_acc
@is_acc:
        iny                     ; consume 'A'
        jsr _au_check_end       ; validate end (handles // correctly)
        lda #MODE_ACC
        ldx #0
        rts

@not_acc:
        ; ── IMM or trailing comment: '#' ─────────────────────────────────────
        cmp #SC_HASH
        bne @not_hash
        iny                     ; consume '#'
        jsr asm_skip_ws         ; tolerate space: '# $nn' same as '#$nn'
        ; Check if something parseable follows (not end-of-expr → try value)
        lda (asm_ptr),y
        jsr _au_is_end
        bcs @ret_imp            ; '#' at end → treat as comment → IMP
        jsr _au_read_val        ; parse value expression
        jsr _au_check_end
        lda #MODE_IMM
        ldx #1
        rts

@ret_imp:
        lda #MODE_IMP
        ldx #0
        rts

@not_hash:
        ; ── Indirect family: '(' ─────────────────────────────────────────────
        cmp #SC_LPAR
        beq :+
        jmp @not_lpar
:
        iny                     ; consume '('
        jsr asm_skip_ws
        jsr _au_read_val        ; parse expression → asm_opr, A=0(ZP)/1(ABS)
        bne @ind_abs            ; wide → 4-byte indirect
        jmp @ind_1b             ; narrow → 1-byte indirect

@ind_abs:
        ; 2-byte: ($nnnn) or ($nnnn,X)
        jsr asm_skip_ws
        lda (asm_ptr),y
        cmp #SC_COMM
        beq @ind_4b_ix          ; ($nnnn,X) → AIX
        jsr _au_expect_rpar
        iny                     ; consume ')'
        jsr _au_check_end
        lda #MODE_IND           ; ($nnnn) → IND
        ldx #2
        rts

@ind_4b_ix:                     ; ($nnnn,X) → AIX
        iny                     ; consume ','
        jsr asm_skip_ws
        lda (asm_ptr),y
        jsr _au_expect_x
        iny                     ; consume 'X'
        jsr asm_skip_ws
        lda (asm_ptr),y
        jsr _au_expect_rpar
        iny                     ; consume ')'
        jsr _au_check_end
        lda #MODE_AIX
        ldx #2
        rts

@ind_1b:
        ; 1-byte indirect: ZPI / INX / INY  (asm_opr already set by _au_read_val)
        jsr asm_skip_ws
        lda (asm_ptr),y
        cmp #SC_COMM
        beq @ind_1b_ix          ; ($nn,X) → INX
        jsr _au_expect_rpar
        iny                     ; consume ')'
        jsr asm_skip_ws
        lda (asm_ptr),y
        jsr _au_is_end
        bcs @ret_zpi            ; ($nn) end → ZPI
        lda (asm_ptr),y         ; reload (_au_is_end may clobber)
        cmp #SC_COMM
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume ','
        jsr asm_skip_ws
        lda (asm_ptr),y
        cmp #SC_Y
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume 'Y'
        jsr _au_check_end
        lda #MODE_INY           ; ($nn),Y → INY
        ldx #1
        rts

@ret_zpi:
        lda #MODE_ZPI           ; ($nn) → ZPI
        ldx #1
        rts

@ind_1b_ix:                     ; ($nn,X) → INX
        iny                     ; consume ','
        jsr asm_skip_ws
        lda (asm_ptr),y
        jsr _au_expect_x
        iny                     ; consume 'X'
        jsr asm_skip_ws
        lda (asm_ptr),y
        jsr _au_expect_rpar
        iny                     ; consume ')'
        jsr _au_check_end
        lda #MODE_INX           ; ($nn,X) → INX
        ldx #1
        rts

@not_lpar:
        ; ── Direct addressing: value expression ──────────────────────────────
        jsr _au_read_val        ; parse expression → asm_opr, A=0(ZP)/1(ABS)
        bne @direct_abs         ; wide → ABS / ABX / ABY
        jmp @direct_1b          ; narrow → ZP / ZPX / ZPY / ZPREL

@direct_abs:
        ; 2-byte: ABS / ABX / ABY  (asm_opr already set)
        jsr asm_skip_ws
        lda (asm_ptr),y
        jsr _au_is_end
        bcs @ret_abs            ; → ABS
        lda (asm_ptr),y         ; reload
        cmp #SC_COMM
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume ','
        jsr asm_skip_ws
        lda (asm_ptr),y
        cmp #SC_X
        beq @abx
        cmp #SC_Y
        beq @aby
        jmp asm_syntax_error

@abx:   iny                     ; consume 'X'
        jsr _au_check_end
        lda #MODE_ABX
        ldx #2
        rts

@aby:   iny                     ; consume 'Y'
        jsr _au_check_end
        lda #MODE_ABY
        ldx #2
        rts

@ret_abs:
        lda #MODE_ABS
        ldx #2
        rts

@direct_1b:
        ; 1-byte: ZP / ZPX / ZPY / ZPREL  (asm_opr already set by _au_read_val)
        jsr asm_skip_ws
        lda (asm_ptr),y
        jsr _au_is_end
        bcs @ret_zp             ; → ZP (Zone B remaps to REL)
        lda (asm_ptr),y         ; reload
        cmp #SC_COMM
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume ','
        jsr asm_skip_ws
        lda (asm_ptr),y
        cmp #SC_X
        beq @zpx
        cmp #SC_Y
        beq @zpy
        ; Not X or Y → ZPREL: expr,expr
        lda asm_opr             ; save first operand (ZP address)
        pha
        jsr _au_read_val        ; parse second operand → asm_opr[0]
        lda asm_opr             ; grab second operand lo byte
        sta asm_opr+1           ; store as relative offset
        pla
        sta asm_opr             ; restore first operand (ZP address)
        jsr _au_check_end
        lda #MODE_ZPREL
        ldx #2
        rts

@zpx:   iny                     ; consume 'X'
        jsr _au_check_end
        lda #MODE_ZPX
        ldx #1
        rts

@zpy:   iny                     ; consume 'Y'
        jsr _au_check_end
        lda #MODE_ZPY
        ldx #1
        rts

@ret_zp:
        lda #MODE_ZP            ; NOTE: Zone B assembler path treats this as REL
        ldx #1
        rts

; asm_syntax_error is imported – provided by the assembler's error handler
; (or by dev/asm_core_test_stub.s for host-side testing)
