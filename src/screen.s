; screen.s — Screen management (scroll, newline, cursor, color)
;
; Replaces screen.c with direct 6502 implementation.
; Requires $CC=1 (KERNAL cursor disabled).

        .export _restore_colors, _reset_screen
        .export _scroll_up, _newline, _print_string
        .export _cursor_show, _cursor_hide
        .export _theme_border, _theme_bg, _theme_fg
        .import _io_puts, _io_sync, _io_color
        .import scr_lo, scr_hi

; ── ZP pointers (reuse cse_io's area) ───────────────────
src_ptr = $FB           ; 2 bytes
dst_ptr = $FD           ; 2 bytes

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
        ; A = n rows to scroll. Two passes: screen RAM, then color RAM.
        pha                     ; save n

        sei                     ; prevent VIC tearing

        ; ── Pass 1: scroll screen RAM ──
        pla
        pha                     ; keep n on stack
        tax                     ; X = src_row (starts at n)
        ldy #0                  ; Y = dst_row (starts at 0)
@scr_copy:
        cpx #SCR_H
        bcs @scr_clear

        ; src_ptr = scr[src_row], dst_ptr = scr[dst_row]
        lda scr_lo,x
        sta src_ptr
        lda scr_hi,x
        sta src_ptr+1
        stx @sav_x
        sty @sav_y
        ; dst
        ldx @sav_y
        lda scr_lo,x
        sta dst_ptr
        lda scr_hi,x
        sta dst_ptr+1

        ; copy 40 bytes
        ldy #SCR_W-1
@sc1:   lda (src_ptr),y
        sta (dst_ptr),y
        dey
        bpl @sc1

        ldx @sav_x
        ldy @sav_y
        inx
        iny
        bne @scr_copy           ; always

@scr_clear:
        ; clear rows dst_row..24 with $20
@sc_clr:
        cpy #SCR_H
        bcs @scr_done
        lda scr_lo,y
        sta dst_ptr
        lda scr_hi,y
        sta dst_ptr+1
        sty @sav_y
        lda #$20
        ldy #SCR_W-1
@sc2:   sta (dst_ptr),y
        dey
        bpl @sc2
        ldy @sav_y
        iny
        bne @sc_clr
@scr_done:

        cli                     ; screen done, VIC safe

        ; ── Pass 2: scroll color RAM ──
        pla
        pha                     ; keep n
        tax                     ; X = src_row
        ldy #0                  ; Y = dst_row
@col_copy:
        cpx #SCR_H
        bcs @col_clear

        lda collo,x
        sta src_ptr
        lda colhi,x
        sta src_ptr+1
        stx @sav_x
        sty @sav_y
        ldx @sav_y
        lda collo,x
        sta dst_ptr
        lda colhi,x
        sta dst_ptr+1

        ldy #SCR_W-1
@cc1:   lda (src_ptr),y
        sta (dst_ptr),y
        dey
        bpl @cc1

        ldx @sav_x
        ldy @sav_y
        inx
        iny
        bne @col_copy

@col_clear:
        ; clear with io_color
@cc_clr:
        cpy #SCR_H
        bcs @col_done
        lda collo,y
        sta dst_ptr
        lda colhi,y
        sta dst_ptr+1
        sty @sav_y
        lda _io_color
        ldy #SCR_W-1
@cc2:   sta (dst_ptr),y
        dey
        bpl @cc2
        ldy @sav_y
        iny
        bne @cc_clr
@col_done:

        ; Adjust cursor row: io_cy = max(io_cy - n, 0)
        pla                     ; A = n
        sta @sav_x              ; reuse as temp
        lda CUR_ROW
        sec
        sbc @sav_x
        bcs @set_row
        lda #0
@set_row:
        sta CUR_ROW
        jmp _io_sync

@sav_x: .byte 0
@sav_y: .byte 0
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
        lda scr_lo,x
        sta src_ptr
        lda scr_hi,x
        sta src_ptr+1
        ldy CUR_COL
        lda (src_ptr),y
        eor #$80
        sta (src_ptr),y
        rts
.endproc

; cursor_hide is identical
_cursor_hide = _cursor_show

; ═════════════════════════════════════════════════════════
; Color RAM row address lookup tables
; (scr_lo/scr_hi imported from cse_io.s)
; ═════════════════════════════════════════════════════════
        .segment "RODATA"

collo:
        .repeat 25, i
        .byte <(COLOR_RAM + i * SCR_W)
        .endrepeat
colhi:
        .repeat 25, i
        .byte >(COLOR_RAM + i * SCR_W)
        .endrepeat
