; screen.s — Screen management (scroll, newline, cursor, color)
;
; Replaces screen.c with direct 6502 implementation.
; Requires $CC=1 (KERNAL cursor disabled).

        .export restore_colors, reset_screen
        .export scroll_up, newline
        .export cursor_show, cursor_hide
        .export theme_border, theme_bg, theme_fg
        .export theme_init
        .export vic_reset
        .export kernal_screen_reset
        .import io_puts, io_sync, io_color
        .import scr_lo, scr_hi
        .import _io_scr_setup
        .importzp _io_scr

; NOTE: No runtime ZP dependencies (no sp, popax, etc.)

; ── ZP pointers (reuse cse_io's area) ───────────────────
src_ptr = $FB           ; 2 bytes
dst_ptr = $FD           ; 2 bytes


; ── C64 hardware ─────────────────────────────────────────
SCREEN    = $0400
COLOR_RAM = $D800
VIC_CR1    = $D011        ; DEN/BMM/ECM/RSEL/YSCROLL
VIC_SP_EN  = $D015        ; sprite enable mask
VIC_CR2    = $D016        ; RES/MCM/CSEL/XSCROLL
VIC_MEMCTL = $D018        ; screen + charset base
VIC_IRR    = $D019        ; interrupt latch (write to ack)
VIC_IMR    = $D01A        ; interrupt mask
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
; vic_reset — force VIC into a known-readable text-mode state.
; Called on every userland → kernel transition so user code
; that left VIC in bitmap/multicolor/extended-color mode, with
; the display blanked, sprites on, the screen pointer moved,
; or a raster IRQ firing doesn't leave the REPL unreadable.
; Color RAM and CHROUT colour are (re)applied by restore_colors;
; this routine only handles the mode registers.
; Clobbers: A.
; ═════════════════════════════════════════════════════════
.proc vic_reset
        lda #$1B
        sta VIC_CR1             ; DEN=1, RSEL=25, text, no ECM/BMM, YSCROLL=3
        lda #$C8
        sta VIC_CR2             ; CSEL=40, no MCM, XSCROLL=0
        lda #$16
        sta VIC_MEMCTL          ; VM=$0400, CB=011 → charset $1800 in VIC
                                ;   bank 0 = char ROM $D800 = lowercase/
                                ;   uppercase font.  $14/$15 would select
                                ;   $D000 = uppercase/graphics — not what
                                ;   CSE wants.
        lda #0
        sta VIC_SP_EN           ; sprites off
        sta VIC_IMR             ; no raster/collision IRQs
        lda #$0F
        sta VIC_IRR             ; ack any latched IRQ flags
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
; kernal_screen_reset — restore KERNAL screen-edit ZP to a
; pristine post-init state.  Defends against NMI-during-CHROUT
; corruption (RESTORE pressed mid-`$FFD2` loop): KERNAL CHROUT
; transiently mutates several ZP bytes that PLOT does not touch,
; and an interrupting NMI captures those bytes mid-update.  Left
; uncorrected, the corrupted line-link table / `$D5` / quote &
; insert flags leak into subsequent CHROUT and KERNAL line-input
; ops, producing erratic cursor movement in both the editor (one
; eaten keystroke + a double-jump on the next) and the REPL
; (cursor drifts off-screen, line-wrap math wrong).
;
; CALL SITE — exactly one: `refresh_body` in main.s, on the
; cse_refresh path (kernel-mode NMI dispatch).  NOT called from
; cold-init's reset_screen, the `x` (clear screen) command, or
; scroll_up's full-clear path — those callers own the screen
; transition and do not have a transiently-mid-CHROUT KERNAL
; state to recover from.  Reseting LDTB1 / $D5 wholesale on those
; paths regressed userland CHROUT positioning (rc1-rc2 finding):
; KERNAL line-link state established by prior REPL output is the
; correct context for subsequent userland CHROUT, and wiping it
; on every reset_screen left the screen-editor in a state that
; disagreed with the displayed content.
;
; Reset (post-init values from CINT/$E544):
;   $C6        NDX     ← 0     drain key buffer (in-flight keys
;                              typed during the interrupted op
;                              are no longer routed to the right
;                              consumer; safest to discard).
;   $D4        QTSW    ← 0     quote mode off.
;   $D5        LNMX    ← 39    current logical-line max column
;                              (single-physical-line logical).
;   $D8        INSRT   ← 0     no insert-mode pending.
;   $CE        GDBLN   ← 0     no char-under-cursor cached.
;   $D9..$F1   LDTB1   ← $80   line-link table: every row is the
;             (25 B)           start of its own logical line
;                              (matches the just-cleared screen).
;
; Bytes deliberately NOT reset: $D1/$D2/$D3/$D6/$F3/$F4 — these
; are set by the io_sync (KERNAL PLOT) call that follows in
; refresh_body's reset_screen.
; Clobbers: A, X.
; ═════════════════════════════════════════════════════════
.proc kernal_screen_reset
        ; Fill LDTB1 ($D9-$F1, 25 bytes) with $80 ("each row is the
        ; start of its own logical line"), exiting with X=0 so the
        ; same X can drive the four zero-stores below — saves a
        ; separate `lda #0`.
        ;
        ; sta $D8,x with X=25..1 writes $D8+25=$F1 down to $D8+1=$D9
        ; — exactly the LDTB1 range.  $D8 itself is NOT written by
        ; the loop (bne exits before X reaches 0), which is what we
        ; want: $D8 (INSRT) is one of the zero-store targets below.
        lda #$80
        ldx #SCR_H              ; 25
@l:     sta $D8,x
        dex
        bne @l                  ; exits with X=0 (NOT $FF — bne, not bpl)
        ; X=0 — reuse for every byte that resets to zero.
        stx $C6                 ; NDX (key buffer count)
        stx $CE                 ; GDBLN (char-under-cursor)
        stx $D4                 ; QTSW (quote mode)
        stx $D8                 ; INSRT (loop skipped this slot)
        lda #SCR_W - 1          ; 39
        sta $D5                 ; LNMX
        rts
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
        bne @col0               ; always taken (SCR_H-1 = 24 ≠ 0)
@no_scroll:
        inc CUR_ROW
@col0:  lda #0
        sta CUR_COL
        jmp io_sync
.endproc

; ═════════════════════════════════════════════════════════
; ═════════════════════════════════════════════════════════
; cursor_show / cursor_hide — XOR $80 at cursor position
; ═════════════════════════════════════════════════════════
.proc cursor_show
        jsr _io_scr_setup       ; _io_scr ← screen row for CUR_ROW
        ldy CUR_COL
        lda (_io_scr),y
        eor #$80
        sta (_io_scr),y
        rts
.endproc

; cursor_hide is identical
cursor_hide = cursor_show

; Color RAM tables removed — color RAM is static (set once at init).
