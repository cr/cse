; help.s — the HELP popup (m65)
; Owner: doc/modules/help.md
;
; HELP opens a bordered window, 40 columns wide and the screen's full
; height (centred in 80 columns), over the REPL or the editor, showing
; the cheat sheet of help_text.s (generated from src/help.txt); the
; cursor keys scroll it, HELP / ESC / RUN/STOP close it and the screen
; is as it was.  m65 only (the Makefile builds it for PLATFORM=m65).
;
; The text is the HELP segment, in the reserve 3.C000 (the CSE map shows
; the interface ROM there), read through a far pointer (help.md § Where
; it lives); the code and the window's labels are CSE's window's.

        .setcpu "6502"
        .include "platform.inc"

        .export help_popup

        .import help_text                               ; help_text.s
        .importzp HELP_LINES                            ;   (a count: < 256)
        .import screen_stash, screen_unstash            ; screen.s
        .import io_getc, io_blip, scr_lo, scr_hi, scr_height, scr_bank
        .importzp scr_width, _io_scr, rp_ptr

WIDE    = 40                    ; the window's columns
TEXT    = 37                    ; its text columns, after a blank one
KEY_HELP = 132                  ; the keys as main.s's CH_* (decimal PETSCII)
KEY_ESC  = 27
KEY_STOP = 3
KEY_DOWN = 17
KEY_UP   = 145
KEY_HOME = 19
SC_TL   = $70                   ; the border: ┌ ┐ └ ┘ ─ │ (help.md § The window)
SC_TR   = $6E
SC_BL   = $6D
SC_BR   = $7D
SC_HL   = $40
SC_VL   = $5D
SC_SPACE = $20

.segment "BSS"
help_top:       .res 1          ; the first text line shown
help_max:       .res 1          ; the last value help_top may take
help_left:      .res 1          ; the window's first column
help_r:         .res 1          ; help_draw: the screen row
help_row:       .res WIDE       ; one window row, built before it is written

.segment "KCODE"                ; cold code (in the open on m65)

; ── help_popup — the window until a closing key (help.md § help_popup).
; Out: the screen as before; C = 1 when RUN/STOP closed it.
; Clobbers: A, X, Y, _io_scr, rp_ptr, the DMA job, DIR_BUF.
help_popup:
        jsr screen_stash        ; the screen to DIR_BUF
        lda scr_width
        sec
        sbc #WIDE
        lsr
        sta help_left           ; 0, or 20 in 80 columns
        lda scr_height
        sec
        sbc #2
        sta help_max            ; the text lines shown ...
        lda #<HELP_LINES
        sec
        sbc help_max            ; ... and the lines that do not fit
        bcs :+
        lda #0                  ; all fit: no scrolling
:       sta help_max
        lda #0
        sta help_top
help_redraw:
        jsr help_draw
help_wait:                      ; waiting for a key (the tests stop here)
        IO_KBHIT
        beq help_wait
        jsr io_getc
        cmp #KEY_DOWN
        bne @up
        lda help_top
        cmp help_max
        bcs @blip               ; the last line shown already
        inc help_top
        bcc help_redraw         ; always (C = 0 from the compare)
@up:    cmp #KEY_UP
        bne @home
        lda help_top
        beq @blip               ; the first line shown already
        dec help_top
        jmp help_redraw
@home:  cmp #KEY_HOME
        bne @close
        lda #0
        sta help_top
        beq help_redraw         ; always
@close: cmp #KEY_HELP
        beq @shut
        cmp #KEY_ESC
        beq @shut
        cmp #KEY_STOP
        bne help_wait           ; any other key: ignored
@shut:  pha
        jsr screen_unstash      ; the screen back
        pla
        cmp #KEY_STOP
        beq @stop
        clc
        rts
@stop:  sec
        rts
@blip:  jsr io_blip
        jmp help_wait

; ── help_draw — the window, its text from line help_top.
; Clobbers A, X, Y, _io_scr, rp_ptr.
help_draw:
        lda #<help_text         ; rp_ptr := line help_top (walk the lengths),
        sta rp_ptr              ;   a far pointer into the reserve
        lda #>help_text
        sta rp_ptr+1
        FAR_BANK rp_ptr, BANK_CSE
        ldx help_top
        beq @top
@walk:  jsr next_line
        dex
        bne @walk
@top:   lda #SC_TL              ; the top border
        ldx #SC_TR
        ldy #title - labels
        jsr bar
        lda help_top            ; " more " while lines are hidden above
        beq :+
        jsr bar_more
:       ldx #0
        jsr put_row
        ldx #1                  ; the text: rows 1 .. height - 2
        stx help_r
@row:   lda #SC_SPACE           ; │, a blank column, the line, spaces, │
        ldx #WIDE - 2
@sp:    sta help_row,x
        dex
        bne @sp
        lda #SC_VL
        sta help_row
        sta help_row + WIDE - 1
        lda help_r
        clc
        adc help_top            ; the line's number + 1
        cmp #<HELP_LINES + 1
        bcs @put                ; past the last line: a blank row
        ldy #0
        FAR_LDA rp_ptr          ; its length
        tax
        beq @adv
@ch:    iny
        FAR_LDA rp_ptr
        sta help_row + 1,y      ; from column 2
        dex
        bne @ch
@adv:   jsr next_line
@put:   ldx help_r
        jsr put_row
        inc help_r
        ldx help_r
        inx
        cpx scr_height          ; while help_r < height - 1
        bcc @row
        lda #SC_BL              ; the bottom border, row height - 1
        ldx #SC_BR
        ldy #keys - labels
        jsr bar
        lda help_top            ; " more " while lines are hidden below
        cmp help_max
        bcs :+
        jsr bar_more
:       ldx help_r
        ; fall through

; ── put_row — help_row to screen row X at help_left.  Clobbers A, Y.
put_row:
        lda scr_lo,x
        clc
        adc help_left
        sta _io_scr
        lda scr_hi,x
        adc #0
        sta _io_scr+1
        FAR_BANK_SCREEN _io_scr
        ldy #WIDE - 1
@w:     lda help_row,y
        FAR_STA _io_scr
        dey
        bpl @w
        rts

; ── next_line — rp_ptr past the line it points at.  Clobbers A, Y.
next_line:
        ldy #0
        FAR_LDA rp_ptr
        sec                     ; the length byte too
        adc rp_ptr
        sta rp_ptr
        bcc :+
        inc rp_ptr+1
:       rts

; ── bar — help_row := corner A, the label at labels + Y (NUL-ended),
; then ─ up to corner X.  Clobbers A, X, Y.
bar:
        sta help_row
        stx help_row + WIDE - 1
        lda #SC_HL
        ldx #WIDE - 2
@hl:    sta help_row,x
        dex
        bne @hl
        ldx #1
@lb:    lda labels,y
        beq @r
        sta help_row,x
        iny
        inx
        bne @lb                 ; always
@r:     rts

; ── bar_more — " more " ending one column before the right corner.
; Clobbers A, X.
bar_more:
        ldx #MORE_LEN - 1
@m:     lda more,x
        sta help_row + WIDE - 1 - MORE_LEN,x
        dex
        bpl @m
        rts

.segment "KDATA"
; The labels as screen codes (the lower/upper set), NUL-ended.
labels:
title:  .byte $20, $03, $13, $05, $20, $08, $05, $0C, $10, $20, 0        ; " cse help "
keys:   .byte $20, $03, $12, $13, $12, $20, $13, $03, $12, $0F, $0C, $0C ; " crsr scroll
        .byte $20, $20, $08, $05, $0C, $10, $20, $03, $0C, $0F, $13, $05 ;   help close "
        .byte $20, 0
more:   .byte $20, $0D, $0F, $12, $05, $20                              ; " more "
MORE_LEN = * - more
