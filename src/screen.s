; screen.s — Screen management (scroll, newline, cursor, color)
;
; Replaces screen.c with direct 6502 implementation.
; Requires $CC=1 (KERNAL cursor disabled).

        .export restore_colors, reset_screen
        .export scroll_up, newline
        .export cursor_show, cursor_hide
        .export theme_border, theme_bg, theme_fg
        .export theme_init
        .import io_puts, io_sync, io_color
        .import scr_lo, scr_hi

; NOTE: No runtime ZP dependencies (no sp, popax, etc.)

; ── ZP pointers (reuse cse_io's area) ───────────────────
src_ptr = $FB           ; 2 bytes
dst_ptr = $FD           ; 2 bytes


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

; ── Theme (BSS — defaults applied by theme_init at startup) ─
; Build-time selection: -DTHEME_BOR=x -DTHEME_BG=x -DTHEME_FG=x
; where x is a C64 color index 0-F.
; Default: RADIOACTIVITY (cb5)
;
; BSS (not RODATA) because the `c BFS` REPL command rewrites
; these at runtime — on the planned CRT target RODATA lives in
; ROM.
.ifndef THEME_BOR
  THEME_BOR = 12
.endif
.ifndef THEME_BG
  THEME_BG = 11
.endif
.ifndef THEME_FG
  THEME_FG = 5
.endif

        .segment "BSS"
theme_border: .res 1
theme_bg:     .res 1
theme_fg:     .res 1

        .segment "CODE"

; ═════════════════════════════════════════════════════════
; theme_init — apply build-time theme defaults to BSS
; Called once from main.s startup, before restore_colors.
; ═════════════════════════════════════════════════════════
.proc theme_init
        lda #THEME_BOR
        sta theme_border
        lda #THEME_BG
        sta theme_bg
        lda #THEME_FG
        sta theme_fg
        rts
.endproc

; ═════════════════════════════════════════════════════════
; restore_colors — apply theme + fill color RAM
; ═════════════════════════════════════════════════════════
.proc restore_colors
        lda theme_border
        sta VIC_BRD
        lda theme_bg
        sta VIC_BG
        lda theme_fg
        sta io_color
        ; Also update the KERNAL's text-colour variable at
        ; $0286 (CHRCOLOR — page-2 RAM, part of the KERNAL
        ; work area, NOT zero page).  KERNAL CHROUT ($FFD2)
        ; uses this byte as the colour it writes into colour
        ; RAM alongside each screen-code.  Without this, user
        ; code that calls $FFD2 (e.g. t-hello's 'jsr chrout')
        ; paints its output in whatever colour BASIC left
        ; behind, and the wrong colour persists until CSE next
        ; calls restore_colors after the user code returns.
        sta $0286
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
.proc reset_screen
        jsr restore_colors
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
        jmp io_sync
.endproc

; ═════════════════════════════════════════════════════════
; scroll_up(n) — scroll screen RAM up by A rows
; Color RAM is static (initialized once, never scrolled).
;   A = n
; ═════════════════════════════════════════════════════════
.proc scroll_up
        cmp #SCR_H
        bcc @partial
        ; full clear
        jmp reset_screen

@partial:
        ; A = n rows to scroll (screen RAM only; color RAM is static).
        ; Stack usage: [n] [src_row] [dst_row] — all saved/restored via PHA/PLA.
        pha                     ; save n on stack

        sei                     ; prevent VIC tearing

        ; ── scroll screen RAM ──
        pla
        pha                     ; keep n on stack
        tax                     ; X = src_row (starts at n)
        ldy #0                  ; Y = dst_row (starts at 0)
@scr_copy:
        cpx #SCR_H
        bcs @scr_clear

        ; src_ptr = scr[src_row]
        lda scr_lo,x
        sta src_ptr
        lda scr_hi,x
        sta src_ptr+1
        ; save src_row, dst_row on stack
        txa
        pha                     ; push src_row
        tya
        pha                     ; push dst_row
        ; dst_ptr = scr[dst_row]
        tax
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

        pla                     ; restore dst_row → Y
        tay
        pla                     ; restore src_row → X
        tax
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
        tya
        pha                     ; save row index
        lda #$20
        ldy #SCR_W-1
@sc2:   sta (dst_ptr),y
        dey
        bpl @sc2
        pla                     ; restore row index → Y
        tay
        iny
        bne @sc_clr
@scr_done:

        cli                     ; screen done, VIC safe

        ; Adjust cursor row: io_cy = max(io_cy - n, 0)
        pla                     ; A = n (saved at entry)
        eor #$FF
        sec
        adc CUR_ROW             ; A = io_cy - n (via two's complement add)
        bcs @set_row
        lda #0
@set_row:
        sta CUR_ROW
        jmp io_sync
.endproc

; ═════════════════════════════════════════════════════════
; newline — advance to next row, scroll if at bottom
; ═════════════════════════════════════════════════════════
.proc newline
        lda CUR_ROW
        cmp #SCR_H-1
        bcc @no_scroll
        ; at bottom row — scroll up 1
        lda #1
        jsr scroll_up
        lda #SCR_H-1
        sta CUR_ROW
        lda #0
        sta CUR_COL
        jmp io_sync
@no_scroll:
        inc CUR_ROW
        lda #0
        sta CUR_COL
        jmp io_sync
.endproc

; ═════════════════════════════════════════════════════════
; ═════════════════════════════════════════════════════════
; cursor_show / cursor_hide — XOR $80 at cursor position
; ═════════════════════════════════════════════════════════
.proc cursor_show
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
cursor_hide = cursor_show

; Color RAM tables removed — color RAM is static (set once at init).
