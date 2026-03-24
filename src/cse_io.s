; cse_io.s — Ultra-lean screen I/O library for CSE
;
; Replaces cc65 conio.h entirely.  All functions __fastcall__.
; Cursor position uses KERNAL's $D3 (column) and $D6 (row).
; Call io_sync after changing $D6 to update screen line pointers.
;
; Code: ~250 bytes.  RODATA: 76 bytes.  ZP: 2 bytes.  BSS: 1 byte.

        .export _io_putc, _io_puts
        .export _io_puthex4, _io_puthex2, _io_putdec
        .export _io_clear_eol
        .export _io_getc, _io_kbhit
        .export _io_sync
        .export _io_color

COLS    = 40
ROWS    = 25
SCREEN  = $0400

; KERNAL ZP locations
CUR_COL = $D3           ; cursor column
CUR_ROW = $D6           ; cursor row
SCR_PTR = $D1           ; screen line pointer (lo/hi)
COL_PTR = $F3           ; color RAM line pointer (lo/hi)

; ── ZP scratch ──────────────────────────────────────────────
.segment "ZEROPAGE"
_io_tmp:  .res 2        ; scratch: string pointer / putdec dividend

; ── BSS ─────────────────────────────────────────────────────
.segment "BSS"
_io_color: .res 1       ; text color for screen clears

; ── RODATA ──────────────────────────────────────────────────
.segment "RODATA"

scr_lo:                 ; screen row address, lo bytes
        .byte <(SCREEN+ 0*40), <(SCREEN+ 1*40), <(SCREEN+ 2*40)
        .byte <(SCREEN+ 3*40), <(SCREEN+ 4*40), <(SCREEN+ 5*40)
        .byte <(SCREEN+ 6*40), <(SCREEN+ 7*40), <(SCREEN+ 8*40)
        .byte <(SCREEN+ 9*40), <(SCREEN+10*40), <(SCREEN+11*40)
        .byte <(SCREEN+12*40), <(SCREEN+13*40), <(SCREEN+14*40)
        .byte <(SCREEN+15*40), <(SCREEN+16*40), <(SCREEN+17*40)
        .byte <(SCREEN+18*40), <(SCREEN+19*40), <(SCREEN+20*40)
        .byte <(SCREEN+21*40), <(SCREEN+22*40), <(SCREEN+23*40)
        .byte <(SCREEN+24*40)

scr_hi:                 ; screen row address, hi bytes
        .byte >(SCREEN+ 0*40), >(SCREEN+ 1*40), >(SCREEN+ 2*40)
        .byte >(SCREEN+ 3*40), >(SCREEN+ 4*40), >(SCREEN+ 5*40)
        .byte >(SCREEN+ 6*40), >(SCREEN+ 7*40), >(SCREEN+ 8*40)
        .byte >(SCREEN+ 9*40), >(SCREEN+10*40), >(SCREEN+11*40)
        .byte >(SCREEN+12*40), >(SCREEN+13*40), >(SCREEN+14*40)
        .byte >(SCREEN+15*40), >(SCREEN+16*40), >(SCREEN+17*40)
        .byte >(SCREEN+18*40), >(SCREEN+19*40), >(SCREEN+20*40)
        .byte >(SCREEN+21*40), >(SCREEN+22*40), >(SCREEN+23*40)
        .byte >(SCREEN+24*40)

hex_tab:                ; screen codes for hex digits 0-9, a-f
        .byte $30,$31,$32,$33,$34,$35,$36,$37
        .byte $38,$39,$01,$02,$03,$04,$05,$06

dec_lo:                 ; powers of 10, lo bytes
        .byte <10000, <1000, <100, <10, <1
dec_hi:                 ; powers of 10, hi bytes
        .byte >10000, >1000, >100, >10, >1

; ── CODE ────────────────────────────────────────────────────
.segment "CODE"

; ── io_sync — update $D1/$D2/$F3/$F4 from cursor row ───────
; Call after changing $D6 (io_cy).
_io_sync:
        ldx CUR_ROW
        lda scr_lo,x
        sta SCR_PTR
        sta COL_PTR             ; lo byte same for screen + color RAM
        lda scr_hi,x
        sta SCR_PTR+1
        clc
        adc #$D4                ; $04xx → $D8xx (screen → color RAM)
        sta COL_PTR+1
        rts

; ── io_putc — write PETSCII char at cursor, advance ─────────
; __fastcall__: A = PETSCII char
_io_putc:
        ; PETSCII → screen code conversion
        cmp #$40
        bcc @write              ; $00-$3F: identity (space, digits, punct)
        cmp #$60
        bcc @sub40              ; $40-$5F: uppercase letters → $00-$1F
        cmp #$80
        bcc @sub20              ; $60-$7F: lowercase letters → $40-$5F
        cmp #$C0
        bcc @write              ; $80-$BF: pass through
        ; $C0-$FF: shifted → subtract $80
        sbc #$80                ; C=1 from cmp: exact
        bne @write              ; always taken
@sub40: sbc #$3F                ; C=0 from cmp #$60: A - $3F - 1 = A - $40
        bpl @write              ; always taken
@sub20: sbc #$1F                ; C=0 from cmp #$80: A - $1F - 1 = A - $20
@write:
        ldy CUR_COL
        sta (SCR_PTR),y
        iny
        cpy #COLS
        bcc :+
        ldy #COLS-1             ; clamp at column 39
:       sty CUR_COL
        rts

; ── io_puts — write NUL-terminated PETSCII string ───────────
; __fastcall__: A/X = string pointer (A=lo, X=hi)
_io_puts:
        sta _io_tmp
        stx _io_tmp+1
@loop:  ldy #0
        lda (_io_tmp),y
        beq @done
        jsr _io_putc
        inc _io_tmp
        bne @loop
        inc _io_tmp+1
        bne @loop               ; always taken
@done:  rts

; ── io_puthex4 — write 4 hex digits ─────────────────────────
; __fastcall__: A=lo, X=hi (uint16_t)
_io_puthex4:
        pha                     ; save lo byte
        txa                     ; A = hi byte
        jsr _io_puthex2         ; print hi byte as 2 digits
        pla                     ; A = lo byte
        ; fall through to puthex2

; ── io_puthex2 — write 2 hex digits ─────────────────────────
; __fastcall__: A = byte value
_io_puthex2:
        pha                     ; save byte
        lsr                     ; shift hi nibble down
        lsr
        lsr
        lsr
        tax
        lda hex_tab,x           ; screen code for hi nibble
        ldy CUR_COL
        sta (SCR_PTR),y
        iny
        pla                     ; recover byte
        and #$0F
        tax
        lda hex_tab,x           ; screen code for lo nibble
        sta (SCR_PTR),y
        iny
        cpy #COLS
        bcc :+
        ldy #COLS-1
:       sty CUR_COL
        rts

; ── io_putdec — write 16-bit unsigned decimal ────────────────
; __fastcall__: A=lo, X=hi (uint16_t)
; Subtraction method — no division.  Suppresses leading zeros.
_io_putdec:
        sta _io_tmp             ; dividend lo
        stx _io_tmp+1           ; dividend hi
        lda CUR_COL
        sta @start_col          ; remember starting column for leading-zero check
        ldx #0                  ; power-of-10 index (0..4)
@pow:   ldy #0                  ; digit counter
@sub:   lda _io_tmp
        sec
        sbc dec_lo,x
        pha                     ; tentative lo
        lda _io_tmp+1
        sbc dec_hi,x
        bcc @done_digit         ; borrow: went too far
        sta _io_tmp+1           ; commit hi
        pla
        sta _io_tmp             ; commit lo
        iny                     ; digit++
        bne @sub                ; always (digit <= 9)
@done_digit:
        pla                     ; discard tentative lo
        tya                     ; A = digit (0..9)
        bne @print              ; nonzero: print
        cpx #4                  ; ones place?
        beq @force              ; always print ones digit
        lda CUR_COL             ; check if we've printed anything
        cmp @start_col
        beq @next               ; no digits printed yet: skip leading zero
@force: tya                     ; A = digit (might be 0)
@print: tay
        lda hex_tab,y           ; screen code for digit
        ldy CUR_COL
        sta (SCR_PTR),y
        iny
        sty CUR_COL
@next:  inx
        cpx #5
        bne @pow
        rts
@start_col: .byte 0             ; self-storage for start column

; ── io_clear_eol — fill spaces from cursor to end of row ────
_io_clear_eol:
        ldy CUR_COL
        lda #$20                ; space screen code
@loop:  cpy #COLS
        bcs @done
        sta (SCR_PTR),y
        iny
        bne @loop               ; always (Y < 256)
@done:  rts

; ── io_getc — blocking keyboard read ────────────────────────
_io_getc:
        jsr $FFE4               ; KERNAL GETIN
        beq _io_getc            ; loop until key pressed
        ldx #0                  ; hi byte = 0 for uint8_t return
        rts

; ── io_kbhit — non-blocking keyboard check ──────────────────
_io_kbhit:
        lda $C6                 ; keyboard buffer count
        ldx #0
        rts
