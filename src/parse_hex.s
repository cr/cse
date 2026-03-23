; parse_hex.s — hex-literal reader for Zone D/E custom operand paths
;
; Provides the same hex-digit primitives as au_mode.s's private routines,
; exported so asm_line.s can parse Zone D/E operands without calling
; au_parse_mode (which cannot handle the $nn,$xxxx ZPREL absolute-target
; format or the leading bit-digit).
;
; Calling convention: identical to au_mode.s internals.
;   au_ptr (ZP word) – pointer to input string (shared with au_mode.s)
;   Y               – current offset into the string
;   On bad input: jmp au_syntax_error
;
; Exports
; -------
;   ph_rd_nib   read 1 hex digit from (au_ptr),y → A (0–15); advance Y
;   ph_rd_byte  read 2 hex digits → A;  advance Y by 2
;   ph_rd_word  read 4 hex digits → au_opr[1]:au_opr[0] little-endian;
;               advance Y by 4
;   ph_is_hex   peek (au_ptr),y without consuming; C=1 if hex digit

        .setcpu "6502"

        .export ph_rd_nib, ph_rd_byte, ph_rd_word, ph_is_hex

        .importzp au_ptr, au_opr    ; from au_mode.s
        .import   au_syntax_error   ; error handler (same as au_mode.s)

.segment "ZEROPAGE"
_ph_tmp:        .res 1

.segment "CODE"

; ── ph_rd_nib ─────────────────────────────────────────────────────────────────
; Read one hex digit from (au_ptr),y.
; Returns nibble value 0–15 in A.  Advances Y by 1.
; Jumps to au_syntax_error on non-hex character.
ph_rd_nib:
        lda (au_ptr),y
        iny
        cmp #$01                ; VICII screencodes: A–F = $01–$06
        bcc @bad
        cmp #$07
        bcc @alpha
        cmp #$30                ; digits 0–9 = $30–$39 (same as ASCII)
        bcc @bad
        cmp #$3A
        bcs @bad
        sec
        sbc #$30                ; '0'–'9' → 0–9
        rts
@alpha: clc
        adc #9                  ; $01→10 ($A) … $06→15 ($F)
        rts
@bad:   jmp au_syntax_error

; ── ph_rd_byte ────────────────────────────────────────────────────────────────
; Read exactly two hex digits from (au_ptr),y → A.  Advances Y by 2.
ph_rd_byte:
        jsr ph_rd_nib           ; high nibble
        asl
        asl
        asl
        asl
        sta _ph_tmp
        jsr ph_rd_nib           ; low nibble
        ora _ph_tmp
        rts

; ── ph_rd_word ────────────────────────────────────────────────────────────────
; Read exactly four hex digits from (au_ptr),y.
; Stores result little-endian: au_opr[0] = lo byte, au_opr[1] = hi byte.
; Advances Y by 4.
ph_rd_word:
        jsr ph_rd_byte          ; reads the high byte (first two digits)
        pha
        jsr ph_rd_byte          ; reads the low byte (last two digits)
        sta au_opr              ; au_opr[0] = lo
        pla
        sta au_opr+1            ; au_opr[1] = hi
        rts

; ── ph_is_hex ─────────────────────────────────────────────────────────────────
; Peek at (au_ptr),y without consuming.
; C=1 if next char is a valid hex digit, C=0 otherwise.
; Preserves A and Y.
ph_is_hex:
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
