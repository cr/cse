; ─────────────────────────────────────────────────────────────────────────────
; addr_mode.s  –  addressing-mode and operand parser
;   (renamed from au_mode.s in Phase 21)
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
        .export _au_no_acc              ; caller-set: nonzero → 'A' is a label
        .import asm_syntax_error        ; provided by caller / test stub
        .import asm_expr_error          ; expr-specific error (sets asm_expr_err)
        .import expr_eval_nb            ; no-banking expr evaluator (expr.s)
        .import asm_pass                ; 0=pass 0 (sizing), 1=pass 1 (emit)
        .import sym_lookup              ; for ACC-shadow detection
        .import log_warn                ; emit ";!a shadow" directly on detection
        .import s_a_shadow              ; warning string (strings.s)
        .importzp expr_ptr, expr_val, expr_wide
        .importzp asm_pc                ; for forward-ref dummy value
        .importzp asm_ptr, asm_opr
        .importzp sym_name              ; sym_lookup input

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

; ── BSS ──────────────────────────────────────────────────────────────────────
        .segment "BSS"
; ACC vs label disambiguation flag.  See doc/modules/addr_mode.md
; § ACC vs label disambiguation.
_au_no_acc:    .res 1   ; caller signal: 0 = `A` is ACC, nonzero = `A` is a label

; ── RODATA ───────────────────────────────────────────────────────────────────
        .segment "RODATA"
_str_A: .byte 'A', 0    ; PETSCII "A\0" — sym_lookup probe for shadow detection

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

; ─── _au_ws_load ─────────────────────────────────────────────────────────────
; Skip whitespace, then load next char into A.
; Out:  A = (asm_ptr),y  (the first non-whitespace char)
_au_ws_load:
        jsr asm_skip_ws
        lda (asm_ptr),y
        rts

; ─── _au_is_end ──────────────────────────────────────────────────────────────
; Test A for end-of-expression: null, LF, CR, ';', '//'.
; NOTE: '#' is NOT tested here; it is handled separately in _au_check_end and
;       at the start of mode_parse (where it is the IMM prefix).
; Returns: C=1 if end/comment, C=0 otherwise.  Preserves A when C=0.
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
        tax                     ; save '/' in X
        iny                     ; peek next byte
        lda (asm_ptr),y
        dey
        cmp #SC_SLASH
        beq @yes
        txa                     ; restore '/' in A
@no:    clc
        rts
@yes:   sec
        rts

; ─── _au_check_end ───────────────────────────────────────────────────────────
; Skip whitespace, then require end-of-expression (null, LF, CR, ';', '//', '#').
; Jumps to asm_syntax_error if any other (non-comment) character follows.
; Used after every successfully-parsed operand token.
_au_check_end:
        jsr _au_ws_load
        jsr _au_is_end
        bcs @ok
        cmp #SC_HASH            ; '#'  (trailing comment, post-operand)
        beq @ok
        jmp asm_syntax_error
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

@err:   jmp asm_expr_error

; ─────────────────────────────────────────────────────────────────────────────
; mode_parse  –  main entry point
; ─────────────────────────────────────────────────────────────────────────────
mode_parse:
        jsr _au_ws_load

        ; ── IMP: empty / end-of-expression ───────────────────────────────────
        jsr _au_is_end
        bcs @ret_imp

        ; _au_is_end preserves A when C=0.

        ; ── ACC: bare 'A' (only if followed by end/whitespace, not ident) ─
        ; Gated on _au_no_acc: when the caller (asm_line) signals that
        ; the current profile rejects ACC, this whole branch is skipped
        ; so 'A' falls through to the value/label parser.  See
        ; doc/modules/addr_mode.md § ACC vs label disambiguation.
        cmp #SC_A
        bne @not_acc
        ldx _au_no_acc
        bne @not_acc            ; A still = SC_A; falls through to label parse
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
        ; Pass-1 shadow detection runs FIRST (with Y=0 invariant from
        ; the peek-ahead's `dey`), then we explicitly set Y=1 to match
        ; the iny we'd otherwise need.  This avoids a tya/pha/pla/tay
        ; pair around sym_lookup + log_warn — both clobber Y, but Y is
        ; dead until we set it for `_au_check_end` below.  Pass 0 is
        ; suppressed so each shadow site produces exactly one warning
        ; (mode_parse runs once per pass; warning fires only on pass 1).
        lda asm_pass
        beq @no_shdw            ; pass 0 → skip detection + emit
        lda #<_str_A
        sta sym_name
        lda #>_str_A
        sta sym_name+1
        jsr sym_lookup
        bcs @no_shdw            ; not found → no shadow → no emit
        ; Symbol `A` is defined: emit ";!a shadow" directly via log_warn.
        ; This is the documented contract for the explicit `<acc-mne> A`
        ; form; see doc/modules/addr_mode.md § ACC vs label disambiguation.
        lda #<s_a_shadow
        ldx #>s_a_shadow
        jsr log_warn
@no_shdw:
        ldy #1                  ; consume 'A' (was iny — Y is dead here)
        jsr _au_check_end       ; validate end (Y advances past trailing ws)
        lda #MODE_ACC
        ldx #0
        rts

@not_acc:
        ; ── IMM or trailing comment: '#' ─────────────────────────────────────
        cmp #SC_HASH
        bne @not_hash
        iny                     ; consume '#'
        jsr _au_ws_load         ; tolerate space: '# $nn' same as '#$nn'
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
        jsr _au_ws_load
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
        jsr _au_ws_load
        jsr _au_expect_x
        iny                     ; consume 'X'
        jsr _au_ws_load
        jsr _au_expect_rpar
        iny                     ; consume ')'
        jsr _au_check_end
        lda #MODE_AIX
        ldx #2
        rts

@ind_1b:
        ; 1-byte indirect: ZPI / INX / INY  (asm_opr already set by _au_read_val)
        jsr _au_ws_load
        cmp #SC_COMM
        beq @ind_1b_ix          ; ($nn,X) → INX
        jsr _au_expect_rpar
        iny                     ; consume ')'
        jsr _au_ws_load
        jsr _au_is_end
        bcs @ret_zpi            ; ($nn) end → ZPI
        cmp #SC_COMM            ; A preserved by _au_is_end
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume ','
        jsr _au_ws_load
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
        jsr _au_ws_load
        jsr _au_expect_x
        iny                     ; consume 'X'
        jsr _au_ws_load
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
        jsr _au_ws_load
        jsr _au_is_end
        bcs @ret_abs            ; → ABS
        cmp #SC_COMM            ; A preserved by _au_is_end
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume ','
        jsr _au_ws_load
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
        jsr _au_ws_load
        jsr _au_is_end
        bcs @ret_zp             ; → ZP (Zone B remaps to REL)
        cmp #SC_COMM            ; A preserved by _au_is_end
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume ','
        jsr _au_ws_load
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
