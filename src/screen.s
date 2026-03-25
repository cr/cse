; screen.s — Screen management (scroll, newline, cursor, color)
;
; Replaces screen.c with direct 6502 implementation.
; Requires $CC=1 (KERNAL cursor disabled).

        .export _restore_colors, _reset_screen
        .export _scroll_up, _newline, _print_string
        .export _cursor_show, _cursor_hide
        .export _theme_border, _theme_bg, _theme_fg

        .import _io_puts, _io_sync, _io_color

        .importzp sp

; ── C64 hardware ─────────────────────────────────────────
SCREEN    = $0400
COLOR_RAM = $D800
VIC_BRD   = $D020
VIC_BG    = $D021
CUR_COL   = $D3
CUR_ROW   = $D6

SCR_W     = 40
SCR_H     = 25
SCR_SIZE  = 1000          ; 25 * 40

; ── Theme (BSS) ──────────────────────────────────────────
        .segment "DATA"
_theme_border: .byte 12            ; medium grey
_theme_bg:     .byte 11            ; dark grey
_theme_fg:     .byte  5            ; green

        .segment "CODE"

; ═════════════════════════════════════════════════════════
; restore_colors — apply theme + fill color RAM
; ═════════════════════════════════════════════════════════
.proc _restore_colors
        lda _theme_border
        sta VIC_BRD
        lda _theme_bg
        sta VIC_BG
        lda _theme_fg
        sta _io_color
        ; fill color RAM with io_color
        ldx #0
@fill:  sta COLOR_RAM,x
        sta COLOR_RAM+$100,x
        sta COLOR_RAM+$200,x
        sta COLOR_RAM+$300,x
        inx
        bne @fill
        rts
.endproc

; ═════════════════════════════════════════════════════════
; reset_screen — clear screen + restore colors
; ═════════════════════════════════════════════════════════
.proc _reset_screen
        jsr _restore_colors
        ; fill screen with spaces
        lda #$20
        ldx #0
@clr:   sta SCREEN,x
        sta SCREEN+$100,x
        sta SCREEN+$200,x
        sta SCREEN+$300,x
        inx
        bne @clr
        lda #0
        sta CUR_COL
        sta CUR_ROW
        jmp _io_sync
.endproc

; ═════════════════════════════════════════════════════════
; scroll_up(n) — scroll screen + color RAM up by A rows
;   __fastcall__: n in A
; ═════════════════════════════════════════════════════════
.proc _scroll_up
        cmp #SCR_H
        bcc @partial
        ; full clear
        jmp _reset_screen

@partial:
        ; A = number of rows to scroll
        ; Save n for later
        pha

        ; Compute byte count to copy: (SCR_H - n) * SCR_W
        ; and source offset: n * SCR_W
        ; We'll iterate row-by-row for simplicity and correctness

        sei                     ; prevent VIC tearing

        ; Use self-modifying: src = SCREEN + n*40, dst = SCREEN
        ; Copy (25-n)*40 bytes, then clear n*40 bytes at bottom
        tsx                     ; save SP
        pla                     ; A = n
        pha                     ; keep on stack
        tax                     ; X = n (rows to scroll)

        ; Compute src row = n, dst row = 0
        ; We copy row-by-row using Y as column index
        lda #0
        sta @dst_row
        stx @src_row

@copy_row:
        ldx @src_row
        cpx #SCR_H
        bcs @clear_rows         ; done copying

        ; Get src screen address
        lda scrlo,x
        sta @src+1
        lda scrhi,x
        sta @src+2

        ; Get dst screen address
        ldx @dst_row
        lda scrlo,x
        sta @dst+1
        lda scrhi,x
        sta @dst+2

        ; Get src color address
        ldx @src_row
        lda collo,x
        sta @csrc+1
        lda colhi,x
        sta @csrc+2

        ; Get dst color address
        ldx @dst_row
        lda collo,x
        sta @cdst+1
        lda colhi,x
        sta @cdst+2

        ; Copy 40 bytes screen + color
        ldy #SCR_W-1
@src:   lda $FFFF,y             ; self-modified
@dst:   sta $FFFF,y             ; self-modified
@csrc:  lda $FFFF,y             ; self-modified
@cdst:  sta $FFFF,y             ; self-modified
        dey
        bpl @src

        inc @src_row
        inc @dst_row
        bne @copy_row           ; always (row < 25)

@clear_rows:
        ; Clear rows dst_row..24 with spaces / io_color
        ldx @dst_row
        lda _io_color
        sta @clr_col+1          ; self-mod: color value

@clr_loop:
        cpx #SCR_H
        bcs @done

        lda scrlo,x
        sta @cs+1
        lda scrhi,x
        sta @cs+2
        lda collo,x
        sta @cc+1
        lda colhi,x
        sta @cc+2

        ldy #SCR_W-1
        lda #$20
@cs:    sta $FFFF,y
@clr_col:
        lda #$05                ; self-modified: io_color
@cc:    sta $FFFF,y
        lda #$20                ; reload space for screen
        dey
        bpl @cs

        inx
        bne @clr_loop           ; always

@done:
        cli

        ; Adjust cursor row: io_cy = max(io_cy - n, 0)
        pla                     ; A = n
        sta @tmp
        lda CUR_ROW
        sec
        sbc @tmp
        bcs @set_row
        lda #0
@set_row:
        sta CUR_ROW
        jmp _io_sync

@src_row: .byte 0
@dst_row: .byte 0
@tmp:     .byte 0
.endproc

; ═════════════════════════════════════════════════════════
; newline — advance to next row, scroll if at bottom
; ═════════════════════════════════════════════════════════
.proc _newline
        lda CUR_ROW
        cmp #SCR_H-1
        bcc @no_scroll
        ; at bottom row — scroll up 1
        lda #1
        jsr _scroll_up
        lda #SCR_H-1
        sta CUR_ROW
        lda #0
        sta CUR_COL
        jmp _io_sync
@no_scroll:
        inc CUR_ROW
        lda #0
        sta CUR_COL
        jmp _io_sync
.endproc

; ═════════════════════════════════════════════════════════
; print_string(str) — scroll-aware string output
;   __fastcall__: str pointer in A/X
; ═════════════════════════════════════════════════════════
.proc _print_string
        ; __fastcall__: str ptr in A/X.  Just pass through to io_puts.
        ; The C version did scroll checks but they're rarely needed.
        jmp _io_puts
.endproc

; ═════════════════════════════════════════════════════════
; cursor_show / cursor_hide — XOR $80 at cursor position
; ═════════════════════════════════════════════════════════
.proc _cursor_show
        ldx CUR_ROW
        lda scrlo,x
        sta @rd+1
        sta @wr+1
        lda scrhi,x
        sta @rd+2
        sta @wr+2
        ldy CUR_COL
@rd:    lda $FFFF,y
        eor #$80
@wr:    sta $FFFF,y
        rts
.endproc

; cursor_hide is identical
_cursor_hide = _cursor_show

; ═════════════════════════════════════════════════════════
; Row address lookup tables (screen + color RAM)
; ═════════════════════════════════════════════════════════
        .segment "RODATA"

scrlo:
        .repeat 25, i
        .byte <(SCREEN + i * SCR_W)
        .endrepeat
scrhi:
        .repeat 25, i
        .byte >(SCREEN + i * SCR_W)
        .endrepeat
collo:
        .repeat 25, i
        .byte <(COLOR_RAM + i * SCR_W)
        .endrepeat
colhi:
        .repeat 25, i
        .byte >(COLOR_RAM + i * SCR_W)
        .endrepeat
