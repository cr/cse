; ─────────────────────────────────────────────────────────────────────────────
; au_mode.s  –  addressing-mode argument parser
;
; Parses a pre-resolved, null-terminated argument string in VICII screen
; encoding.  All numbers are $-prefixed hex: $nn (1 byte) or $nnnn (2 bytes).
;
; Whitespace (space, tab) is tolerated between tokens.
; End-of-expression: null ($00), CR ($0D), LF ($0A), ';', '//'.
; '#' terminates when it appears after the operand; at the start of the
; argument it is the IMM prefix ('#$nn') – '#' not followed by '$' → IMP.
;
; Entry:
;   au_ptr (ZP word)  – pointer to argument string, set by caller
;   Y = 0
;
; Exit:
;   A   – mode index (0 = IMP .. 15 = ZPREL; matches ALL_MODES order in
;          dev/mnemonic_tables.py)
;   X   – operand byte count (0, 1, or 2)
;   au_opr[0]  – first (or only) operand byte
;   au_opr[1]  – second operand byte  (absolute addresses: hi byte;
;                 ZPREL: relative offset)
;   For 2-byte absolute addresses $nnnn the bytes are little-endian:
;     au_opr[0] = lo byte ($nn), au_opr[1] = hi byte ($nn)
;
; Error: jmp au_syntax_error (does not return)
; ─────────────────────────────────────────────────────────────────────────────

        .setcpu "6502"

        .export au_parse_mode           ; main entry point
        .export au_skip_ws              ; used by asm_line.s
        .export au_ptr, au_opr          ; ZP i/o variables
        .import au_syntax_error         ; provided by caller / test stub

; ── Screen-code constants ─────────────────────────────────────────────────────
SC_LF   = $0A   ; line feed
SC_CR   = $0D   ; carriage return
SC_A    = $01   ; 'A'  (accumulator)
SC_X    = $18   ; 'X'
SC_Y    = $19   ; 'Y'
SC_HASH = $23   ; '#'  (IMM prefix / trailing comment start)
SC_DOLL = $24   ; '$'
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
                ;                 remaps ZP→REL and treats au_opr[0] as offset
MODE_ZPI  = 13  ; (zero page)  [65C02]          ($nn)
MODE_AIX  = 14  ; (absolute, X)  [65C02 JMP]    ($nnnn,X)
MODE_ZPREL= 15  ; zero page + relative  [65C02]  $nn,$rr

; ── Zero page ─────────────────────────────────────────────────────────────────
        .segment "ZEROPAGE"

au_ptr:         .res 2  ; pointer to argument string
au_opr:         .res 2  ; output operand bytes (lo, hi)
_au_tmp:        .res 1  ; scratch

; ── Code ──────────────────────────────────────────────────────────────────────
        .segment "CODE"

; ─── au_skip_ws ───────────────────────────────────────────────────────────────
; Advance Y past any spaces or tabs.
au_skip_ws:
        lda (au_ptr),y
        cmp #$20                ; space
        beq @eat
        cmp #$09                ; tab
        bne @done
@eat:   iny
        bne au_skip_ws          ; (Y wraps at 256 – safe for any sane line length)
@done:  rts

; ─── au_is_end ────────────────────────────────────────────────────────────────
; Test A for end-of-expression: null, LF, CR, ';', '//'.
; NOTE: '#' is NOT tested here; it is handled separately in au_check_end and
;       at the start of au_parse_mode (where it is the IMM prefix).
; Returns: C=1 if end/comment, C=0 otherwise.  May clobber A.
au_is_end:
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
        lda (au_ptr),y
        dey
        cmp #SC_SLASH
        beq @yes
@no:    clc
        rts
@yes:   sec
        rts

; ─── au_check_end ─────────────────────────────────────────────────────────────
; Skip whitespace, then require end-of-expression (null, LF, CR, ';', '//', '#').
; Jumps to au_syntax_error if any other (non-comment) character follows.
; Used after every successfully-parsed operand token.
au_check_end:
        jsr au_skip_ws
        lda (au_ptr),y
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
        lda (au_ptr),y
        dey
        cmp #SC_SLASH
        beq @ok
@err:   jmp au_syntax_error
@ok:    rts

; ─── _au_rd_nib ───────────────────────────────────────────────────────────────
; Read one hex digit from (au_ptr),y → A (0–15), advance Y.
; Jumps to au_syntax_error on non-hex character.
_au_rd_nib:
        lda (au_ptr),y
        iny
        cmp #$01                ; $01–$06 → screen codes A–F
        bcc @bad
        cmp #$07
        bcc @alpha
        cmp #$30                ; $30–$39 → digits 0–9
        bcc @bad
        cmp #$3A
        bcs @bad
        sec
        sbc #$30
        rts
@alpha: clc
        adc #9                  ; $01→10 … $06→15
        rts
@bad:   jmp au_syntax_error

; ─── _au_rd_byte ──────────────────────────────────────────────────────────────
; Read exactly two hex digits from (au_ptr),y → A, advance Y by 2.
_au_rd_byte:
        jsr _au_rd_nib          ; high nibble
        asl
        asl
        asl
        asl
        sta _au_tmp
        jsr _au_rd_nib          ; low nibble
        ora _au_tmp
        rts

; ─── _au_is_hex ───────────────────────────────────────────────────────────────
; Peek (au_ptr),y without consuming.  C=1 if hex digit, C=0 if not.
; Preserves A and Y.
_au_is_hex:
        pha
        lda (au_ptr),y
        cmp #$01
        bcc @no
        cmp #$07
        bcc @yes
        cmp #$30
        bcc @no
        cmp #$3A
        bcc @yes
@no:    pla
        clc
        rts
@yes:   pla
        sec
        rts

; ─────────────────────────────────────────────────────────────────────────────
; au_parse_mode  –  main entry point
; ─────────────────────────────────────────────────────────────────────────────
au_parse_mode:
        jsr au_skip_ws

        ; ── IMP: empty / end-of-expression ───────────────────────────────────
        lda (au_ptr),y
        jsr au_is_end
        bcs @ret_imp

        ; Reload: au_is_end may have clobbered A (// lookahead).
        lda (au_ptr),y

        ; ── ACC: bare 'A' ────────────────────────────────────────────────────
        cmp #SC_A
        bne @not_acc
        iny                     ; consume 'A'
        jsr au_check_end
        lda #MODE_ACC
        ldx #0
        rts

@not_acc:
        ; ── IMM or trailing comment: '#' ─────────────────────────────────────
        cmp #SC_HASH
        bne @not_hash
        iny                     ; consume '#'
        jsr au_skip_ws          ; tolerate space: '# $nn' same as '#$nn'
        lda (au_ptr),y
        cmp #SC_DOLL
        bne @ret_imp            ; '#' not followed by '$' → treat as comment → IMP
        iny                     ; consume '$'
        jsr _au_rd_byte
        sta au_opr
        lda #0
        sta au_opr+1
        jsr au_check_end
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
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_DOLL
        beq :+
        jmp au_syntax_error     ; '(' must be followed by '$'
:
        iny                     ; consume '$'

        jsr _au_rd_byte         ; first 2 digits → A (hi byte of addr if 4-digit)
        jsr _au_is_hex          ; peek: is there a 2nd byte?
        bcc @ind_1b             ; no → 1-byte ZP address

        ; 4-digit: ($nnnn) or ($nnnn,X)
        pha                     ; save hi byte
        jsr _au_rd_byte         ; next 2 digits → A = lo byte
        sta au_opr              ; au_opr[0] = lo
        pla
        sta au_opr+1            ; au_opr[1] = hi
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_COMM
        beq @ind_4b_ix          ; ($nnnn,X) → AIX
        cmp #SC_RPAR
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume ')'
        jsr au_check_end
        lda #MODE_IND           ; ($nnnn) → IND
        ldx #2
        rts

@ind_4b_ix:                     ; ($nnnn,X) → AIX
        iny                     ; consume ','
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_X
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume 'X'
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_RPAR
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume ')'
        jsr au_check_end
        lda #MODE_AIX
        ldx #2
        rts

@ind_1b:
        ; 1-byte indirect: ZPI / INX / INY
        sta au_opr              ; au_opr[0] = ZP address
        lda #0
        sta au_opr+1
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_COMM
        beq @ind_1b_ix          ; ($nn,X) → INX
        cmp #SC_RPAR
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume ')'
        jsr au_skip_ws
        lda (au_ptr),y
        jsr au_is_end
        bcs @ret_zpi            ; ($nn) end → ZPI
        lda (au_ptr),y          ; reload (au_is_end may clobber)
        cmp #SC_COMM
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume ','
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_Y
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume 'Y'
        jsr au_check_end
        lda #MODE_INY           ; ($nn),Y → INY
        ldx #1
        rts

@ret_zpi:
        lda #MODE_ZPI           ; ($nn) → ZPI
        ldx #1
        rts

@ind_1b_ix:                     ; ($nn,X) → INX
        iny                     ; consume ','
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_X
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume 'X'
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_RPAR
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume ')'
        jsr au_check_end
        lda #MODE_INX           ; ($nn,X) → INX
        ldx #1
        rts

@not_lpar:
        ; ── Direct: '$' ──────────────────────────────────────────────────────
        cmp #SC_DOLL
        beq :+
        jmp au_syntax_error     ; no recognisable prefix → error
:
        iny                     ; consume '$'

        jsr _au_rd_byte         ; first 2 digits → A (hi byte if 4-digit)
        jsr _au_is_hex          ; peek: second byte?
        bcc @direct_1b          ; no → 1-byte ZP/ZPX/ZPY/ZPREL

        ; 4-digit: ABS / ABX / ABY
        pha                     ; save hi byte
        jsr _au_rd_byte         ; → A = lo byte
        sta au_opr              ; au_opr[0] = lo
        pla
        sta au_opr+1            ; au_opr[1] = hi
        jsr au_skip_ws
        lda (au_ptr),y
        jsr au_is_end
        bcs @ret_abs            ; → ABS
        lda (au_ptr),y          ; reload
        cmp #SC_COMM
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume ','
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_X
        beq @abx
        cmp #SC_Y
        beq @aby
        jmp au_syntax_error

@abx:   iny                     ; consume 'X'
        jsr au_check_end
        lda #MODE_ABX
        ldx #2
        rts

@aby:   iny                     ; consume 'Y'
        jsr au_check_end
        lda #MODE_ABY
        ldx #2
        rts

@ret_abs:
        lda #MODE_ABS
        ldx #2
        rts

@direct_1b:
        ; 1-byte: ZP / ZPX / ZPY / ZPREL
        sta au_opr              ; au_opr[0] = ZP address (or relative offset)
        lda #0
        sta au_opr+1
        jsr au_skip_ws
        lda (au_ptr),y
        jsr au_is_end
        bcs @ret_zp             ; → ZP (Zone B remaps to REL)
        lda (au_ptr),y          ; reload
        cmp #SC_COMM
        beq :+
        jmp au_syntax_error
:
        iny                     ; consume ','
        jsr au_skip_ws
        lda (au_ptr),y
        cmp #SC_X
        beq @zpx
        cmp #SC_Y
        beq @zpy
        cmp #SC_DOLL
        beq @zprel              ; $nn,$rr → ZPREL
        jmp au_syntax_error

@zpx:   iny                     ; consume 'X'
        jsr au_check_end
        lda #MODE_ZPX
        ldx #1
        rts

@zpy:   iny                     ; consume 'Y'
        jsr au_check_end
        lda #MODE_ZPY
        ldx #1
        rts

@zprel:                         ; $nn,$rr → ZPREL
        iny                     ; consume '$'
        jsr _au_rd_byte         ; → A = relative byte
        sta au_opr+1            ; au_opr[1] = relative offset
        jsr au_check_end
        lda #MODE_ZPREL
        ldx #2
        rts

@ret_zp:
        lda #MODE_ZP            ; NOTE: Zone B assembler path treats this as REL
        ldx #1
        rts

; au_syntax_error is imported – provided by the assembler's error handler
; (or by dev/au_mode_test_stub.s for host-side testing)
