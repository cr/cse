; ─────────────────────────────────────────────────────────────────────────────
; Owner: doc/modules/addr_mode.md
; addr_mode.s  –  addressing-mode and operand parser
;
; Parses a null-terminated PETSCII argument string.
; Operand values parsed by expr_eval_nb: $hex, %binary, decimal,
; labels, * (PC), and arithmetic expressions.
;
; Whitespace (space $20, tab $A0) is tolerated between tokens.
; End-of-expression: null ($00), CR ($0D), LF ($0A), ';', '//'.
; '#' terminates when it appears after the operand; at the start of the
; argument it is the IMM prefix ('#$nn', '# 5') – a '#' followed only by
; whitespace and an end mark is a comment → IMP.
;
; Entry:
;   asm_ptr (ZP word)  – pointer to argument string (PETSCII), set by caller
;   Y = 0
;
; Exit:
;   A   – mode index (0 = IMP .. 15 = ZPREL, never 12 = REL; on m65 also
;          18 = ISPY `(e,sp),y`, 19 = ZPIZ `(e),z`; ALL_MODES order in
;          dev/instruction_set.py)
;   _au_far (m65) – nonzero for `[e]` / `[e],z` (ZPI / ZPIZ, far)
;   X   – operand byte count (0, 1, or 2)
;   asm_opr[0]  – first (or only) operand byte
;   asm_opr[1]  – second operand byte  (absolute addresses: hi byte)
;   ZPREL: asm_opr = the second value, the branch target (both bytes);
;          asm_tmp2 = the first, the zero-page byte
;   For 2-byte absolute addresses $nnnn the bytes are little-endian:
;     asm_opr[0] = lo byte ($nn), asm_opr[1] = hi byte ($nn)
;
; Error: jmp asm_syntax_error / asm_expr_error (does not return)
; ─────────────────────────────────────────────────────────────────────────────

        .setcpu "6502"
        .include "platform.inc"

        .export mode_parse              ; main entry point
        .export asm_skip_ws             ; used by asm_line.s
        .export _au_no_acc              ; caller-set: nonzero → 'A' is a label
        .import asm_syntax_error        ; provided by caller / test stub
        .import asm_expr_error          ; expr-specific error (sets asm_err_code=1)
        .import expr_eval_nb            ; no-banking expr evaluator (expr.s)
        .import asm_pass                ; 0=pass 0 (sizing), 1=pass 1 (emit)
        .import sym_lookup              ; for ACC-shadow detection
        .import log_warn                ; emit ";!a shadow" directly on detection
        .import s_a_shadow              ; warning string (strings.s)
        .importzp expr_ptr, expr_val, expr_wide
        .importzp asm_pc                ; for forward-ref dummy value
        .importzp asm_ptr, asm_opr, asm_tmp2   ; asm_tmp2: ZPREL's zero-page byte
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
MODE_REL  = 12  ; relative  NOTE: never returned — a branch target is ZP/ABS;
                ;                 asm_line's zone B computes the offset
MODE_ZPI  = 13  ; (zero page)  [65C02]          ($nn)
MODE_AIX  = 14  ; (absolute, X)  [65C02 JMP]    ($nnnn,X)
MODE_ZPREL= 15  ; zero page + relative  [65C02]  $nn,$rr
.ifdef MEGA_SUPPORT
MODE_ISPY = 18  ; (stack, SP), Y  [4510]         ($nn,SP),Y
MODE_ZPIZ = 19  ; (zero page), Z  [4510]         ($nn),Z
SC_S    = $53   ; 'S'
SC_P    = $50   ; 'P'
SC_Z    = $5A   ; 'Z'
SC_LBRK = $5B   ; '['  (far: a 32-bit pointer, 45GS02)
SC_RBRK = $5D   ; ']'
.endif

; ── BSS ──────────────────────────────────────────────────────────────────────
        .segment "BSS"
; ACC vs label disambiguation flag.  See doc/modules/addr_mode.md
; § ACC vs label disambiguation.
_au_no_acc:    .res 1   ; caller signal: 0 = `A` is ACC, nonzero = `A` is a label
.ifdef MEGA_SUPPORT
        .export _au_far
_au_far:       .res 1   ; result: 1 = the operand was written in brackets ([e], [e],z)
.endif

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

; ─── _au_commit ─────────────────────────────────────────────────────────────
; asm_ptr += Y; Y = 0.  Clobbers A.
_au_commit:
        tya
        clc
        adc asm_ptr
        sta asm_ptr
        bcc :+
        inc asm_ptr+1
:       ldy #0
        rts

; ─── _au_read_val ────────────────────────────────────────────────────────────
; Parse an operand value via expr_eval_nb.  Advances asm_ptr by Y first,
; syncs to expr_ptr, calls expr_eval_nb, stores result in asm_opr.
;
; Out:  A = 0 (ZP/narrow) or 1 (ABS/wide)
;       asm_opr[0..1] = little-endian value from expr_val
;       asm_ptr updated past consumed expression; Y = 0
; Error (bad expression): jmp asm_expr_error (pass 0 undefined: dummy value)
_au_read_val:
        ; Advance asm_ptr by Y (commit chars consumed so far; inline —
        ; this is the hot path, _au_commit is for the ACC peek)
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
.ifdef MEGA_SUPPORT
        lda #0
        sta _au_far
.endif
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
        ; Peek at the char after 'A' (relative to the operand start: commit
        ; the leading whitespace first, so 'A' is at Y=0) — whitespace, '#'
        ; or an end-of-expression mark → ACC; anything else → label.
        jsr _au_commit          ; 'A' at (asm_ptr),0
        iny
        lda (asm_ptr),y         ; Y=1: char after 'A' (Z set for NUL)
        jsr _au_is_end          ; NUL, CR, LF, ';', '//' (A kept if not)
        bcs @is_acc
        cmp #' '
        beq @is_acc
        cmp #$A0
        beq @is_acc
        cmp #SC_HASH
        beq @is_acc
        dey                     ; Y=0: back at 'A' → label parse
        lda #SC_A
        jmp @not_acc
@is_acc:
        ; Pass-1 shadow detection runs FIRST, then we explicitly set Y=1
        ; (past the 'A', which _au_commit put at offset 0).  This avoids a tya/pha/pla/tay
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
        ; mode_parse runs banked out; the screen output needs the KERNAL
        ; (io_sync → PLOT), so bank it in around the warning.
        BANK_PUSH
        BANK_IN_A
        lda #<s_a_shadow
        ldx #>s_a_shadow
        jsr log_warn
        BANK_POP                ; back to the caller's banking
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
.ifdef MEGA_SUPPORT
        ; ── Far: '[' — [$nn] → ZPI, [$nn],Z → ZPIZ, _au_far = 1 ──────────────
        cmp #SC_LBRK
        bne @not_far
        iny                     ; consume '['
        jsr asm_skip_ws
        jsr _au_read_val
        beq :+                  ; narrow only
        jmp asm_syntax_error
:       inc _au_far
        jsr _au_ws_load
        cmp #SC_RBRK
        beq :+
        jmp asm_syntax_error
:       iny                     ; consume ']'
        jsr _au_ws_load
        jsr _au_is_end
        bcc :+
        jmp @ret_zpi
:       jmp @ind_z              ; ',Z' → ZPIZ (A preserved)
@not_far:
.endif
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
.ifdef MEGA_SUPPORT
@ind_z:
.endif
        cmp #SC_COMM            ; A preserved by _au_is_end
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume ','
        jsr _au_ws_load
.ifdef MEGA_SUPPORT
        cmp #SC_Z
        beq @zpiz
        ldx _au_far             ; [$nn],Y is no form
        beq :+
        jmp asm_syntax_error
:
.endif
        cmp #SC_Y
        beq :+
        jmp asm_syntax_error
:
        iny                     ; consume 'Y'
        jsr _au_check_end
        lda #MODE_INY           ; ($nn),Y → INY
        ldx #1
        rts
.ifdef MEGA_SUPPORT
@zpiz:  iny                     ; consume 'Z'
        jsr _au_check_end
        lda #MODE_ZPIZ          ; ($nn),Z / [$nn],Z → ZPIZ
        ldx #1
        rts
.endif

@ret_zpi:
        lda #MODE_ZPI           ; ($nn) → ZPI
        ldx #1
        rts

@ind_1b_ix:                     ; ($nn,X) → INX
        iny                     ; consume ','
        jsr _au_ws_load
.ifdef MEGA_SUPPORT
        cmp #SC_S
        beq @ispy
.endif
        jsr _au_expect_x
        iny                     ; consume 'X'
        jsr _au_ws_load
        jsr _au_expect_rpar
        iny                     ; consume ')'
        jsr _au_check_end
        lda #MODE_INX           ; ($nn,X) → INX
        ldx #1
        rts

.ifdef MEGA_SUPPORT
@ispy:                          ; ($nn,SP),Y or ($nn,S),Y → ISPY
        iny                     ; consume 'S'
        lda (asm_ptr),y
        cmp #SC_P
        bne :+
        iny                     ; consume 'P'
:       jsr _au_ws_load
        jsr _au_expect_rpar
        iny                     ; consume ')'
        jsr _au_ws_load
        cmp #SC_COMM
        beq :+
        jmp asm_syntax_error
:       iny                     ; consume ','
        jsr _au_ws_load
        cmp #SC_Y
        beq :+
        jmp asm_syntax_error
:       iny                     ; consume 'Y'
        jsr _au_check_end
        lda #MODE_ISPY
        ldx #1
        rts
.endif

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
        bcs @ret_zp             ; → ZP
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
        ; Not X or Y → ZPREL: expr,expr — the zero-page byte to asm_tmp2,
        ; the branch target (both bytes) to asm_opr
        lda asm_opr
        sta asm_tmp2
        jsr _au_read_val        ; parse second operand → asm_opr
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
        lda #MODE_ZP            ; (zone B takes it as a zero-page branch target)
        ldx #1
        rts

; asm_syntax_error is imported – provided by the assembler's error handler
; (or by dev/asm_core_test_stub.s for host-side testing)
