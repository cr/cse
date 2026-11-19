; screen.s — Screen management (scroll, newline, cursor, color)
; Owner: doc/modules/screen.md
;
; Requires $CC=1 (KERNAL cursor disabled).

        .include "platform.inc"
        .export restore_colors, reset_screen
        .export scroll_up, newline
        .export cursor_show, cursor_hide
        .export theme_border, theme_bg, theme_fg
        .export theme_init
        .export vic_reset
        .export kernal_screen_reset
.ifdef PLATFORM_M65
        .export screen_mode_set, screen_save, screen_restore
        .import io_geometry
.endif
        .import io_sync
        .import scr_lo, scr_hi
        .import _io_scr_setup
        .importzp _io_scr, scr_src

; ── ZP pointers (CSE's own ZP — never the user's $80–$FF) ─
; dst_ptr reuses cse_io's _io_scr: it is transient (every reader
; re-derives it via _io_scr_setup right before use), and scroll_up's
; only caller, newline, moves the cursor anyway.
src_ptr = scr_src       ; 2 bytes (zp.s)
dst_ptr = _io_scr       ; 2 bytes (zp.s, cse_io)


; ── Screen geometry ──────────────────────────────────────
.ifdef PLATFORM_C64                     ; m65: the geometry is run-time state
SCR_W     = SCREEN_WIDTH
SCR_H     = SCREEN_HEIGHT
.endif

; ── Theme (BSS — defaults applied by theme_init at startup) ─
; Build-time selection: -DTHEME_BOR=x -DTHEME_BG=x -DTHEME_FG=x
; where x is a C64 color index 0-F.  The Makefile always passes them
; (default THEME=GREENLAND, d5d); the fallback below (RADIOACTIVITY,
; cb5) applies only to a build without the flags.
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

.ifdef PLATFORM_M65
; The display's DMA job (F018B with the destination's megabyte): one
; at a time — a fill or a copy of the screen, a fill of the colour RAM.
scr_job:
sj_opt:   .res 4                ; DMA_OPT_F018B, DMA_OPT_DST_MB, MB, end
sj_cmd:   .res 1
sj_count: .res 2
sj_src:   .res 3                ; a fill's byte in sj_src
sj_dst:   .res 3
sj_sub:   .res 1
sj_mod:   .res 2
sj_tmp:   .res 1                ; vic_reset's table offset, the loops' index

        .segment "RODATA"
; theme colour index -> the PETSCII code BSOUT takes for it
pet_colour:
        .byte $90, $05, $1C, $9F, $9C, $1E, $1F, $9E
        .byte $81, $95, $96, $97, $98, $99, $9A, $9B
; vic_reset: the VIC-IV register set the KERNAL leaves for each text
; mode (recorded on 920413 and 920421: m65_editor.json, vic_modes —
; test_m65_display.py holds this table to it).  Written last to first:
; the hot registers ($D011 $D016 $D018 $D031, which re-derive the rest)
; first, then the derived ones.
vic_regs:
        .byte $1A, $54, $58, $59, $5A, $5B, $5C, $5D, $5E
        .byte $60, $61, $62, $63, $64, $65, $7B
        .byte $11, $16, $18, $31
VIC_SET = * - vic_regs
vic_sets:                       ; 80 x 25, 80 x 50, 40 x 25
        .byte $E1, $40, $50, $00, $78, $01, $50, $C0, $50
        .byte $00, $08, $00, $00, $00, $00, $18
        .byte $1B, $C9, $24, $E0
        .byte $E1, $40, $50, $00, $78, $01, $50, $C0, $50
        .byte $00, $08, $04, $00, $00, $00, $31
        .byte $1B, $C9, $24, $E8
        .byte $E1, $40, $28, $00, $78, $01, $50, $C0, $28
        .byte $00, $08, $00, $00, $00, $00, $18
        .byte $1B, $C8, $24, $60
; kernal_screen_reset: ESC O (quote and insert mode off), HOME HOME
ksr_seq:  .byte $1B, $4F, $13, $13     ; numeric: 'O' under -t c64 is $CF
KSR_LEN = * - ksr_seq
.endif

        .segment "CODE"

; ═════════════════════════════════════════════════════════
; theme_init — apply build-time theme defaults to BSS
; Called from main.s cold init and hw_reinit_body (cse_recover),
; before restore_colors.
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
.ifdef PLATFORM_C64
        lda theme_border
        sta VIC_BRD
        lda theme_bg
        sta VIC_BG
        lda theme_fg
        ; Also update the KERNAL's text-colour variable at
        ; $0286 (CHRCOLOR — page-2 RAM, part of the KERNAL
        ; work area, NOT zero page).  KERNAL CHROUT ($FFD2)
        ; uses this byte as the colour it writes into colour
        ; RAM alongside each screen-code.  Without this, user
        ; code that calls $FFD2 (e.g. t-hello's 'jsr chrout')
        ; paints its output in whatever colour BASIC left
        ; behind, and the wrong colour persists until CSE next
        ; calls restore_colors after the user code returns.
        sta CHRCOLOR
        ; fill color RAM with theme_fg
        ldx #0
@fill:  sta COLOR_RAM,x
        sta COLOR_RAM+$100,x
        sta COLOR_RAM+$200,x
        sta COLOR_RAM+$300,x
        inx
        bne @fill
        rts
.else
        lda theme_border
        sta VIC_BRD
        lda theme_bg
        sta VIC_BG
        ldx theme_fg
        lda pet_colour,x        ; the KERNAL's text colour: a colour code
        KCALL CHROUT            ;   through BSOUT (A1)
        lda theme_fg            ; the colour RAM: width x height cells from
        sta sj_src              ;   offset 0 (the modes' colour pointer)
        lda #0
        sta sj_dst
        sta sj_dst+1
        lda #COLOUR_RAM_BANK
        sta sj_dst+2
        lda scr_size
        sta sj_count
        lda scr_size+1
        sta sj_count+1
        ldx #DMA_FILL
        ldy #COLOUR_RAM_MB
        jmp scr_dma
.endif
.endproc

.ifdef PLATFORM_M65
; ── scr_dma — run scr_job (m65) ──────────────────────────────────────
; In: X = the command (DMA_FILL / DMA_COPY), Y = the destination's
; megabyte; sj_count, sj_src, sj_dst set.  The source's megabyte is 0
; (a new list starts with both 0).  Clobbers A.
scr_dma:
        stx sj_cmd
        sty sj_opt+2
        lda #DMA_OPT_F018B
        sta sj_opt
        lda #DMA_OPT_DST_MB
        sta sj_opt+1
        lda #0
        sta sj_opt+3            ; the options' end
        sta sj_sub
        sta sj_mod
        sta sj_mod+1
        lda #BANK_CSE           ; the job is BSS: the data window, bank 3
        sta DMA_LIST_BANK
        lda #>scr_job
        sta DMA_LIST_HI
        lda #<scr_job
        sta DMA_START_ENH       ; runs to its end before the next instruction
        rts

; ── rows_from — sj_dst = row X of the screen, sj_count = the bytes
; from there to the screen's end (m65).  Clobbers A.
rows_from:
        lda scr_lo,x
        sta sj_dst
        sec
        sbc scr_lo              ; the row's offset from row 0
        sta sj_count
        lda scr_hi,x
        sta sj_dst+1
        sbc scr_hi
        sta sj_count+1
        lda scr_size            ; the size less the offset
        sec
        sbc sj_count
        sta sj_count
        lda scr_size+1
        sbc sj_count+1
        sta sj_count+1
        lda scr_bank
        sta sj_dst+2
        rts

; ── fill_rows_from — rows X to the last filled with A (m65).
; Clobbers A, X, Y.
fill_rows_from:
        pha
        jsr rows_from
        pla
        sta sj_src
        ldx #DMA_FILL
        ldy #0
        jmp scr_dma

; ── screen_save / screen_restore — the screen (width x height, the
; mode's bank) to / from REPL_SCREEN (3.B000) by one DMA copy (m65;
; platform_layer.md § Screen save).  Clobbers A, X, Y.
screen_save:
        ldx #0
        jsr rows_from           ; sj_dst = the screen, sj_count = its size
        ldx #2
@mv:    lda sj_dst,x            ; the screen is the source
        sta sj_src,x
        dex
        bpl @mv
        lda #<REPL_SCREEN
        sta sj_dst
        lda #>REPL_SCREEN
        sta sj_dst+1
        lda #BANK_CSE
        sta sj_dst+2
        bne _scr_copy           ; always
screen_restore:
        ldx #0
        jsr rows_from
        lda #<REPL_SCREEN
        sta sj_src
        lda #>REPL_SCREEN
        sta sj_src+1
        lda #BANK_CSE
        sta sj_src+2
_scr_copy:
        ldx #DMA_COPY
        ldy #0
        jmp scr_dma
.endif

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
.ifdef PLATFORM_C64
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
.else
        ; the mode's set: 80 x 25 (0), 80 x 50 (1), 40 x 25 (2)
        lda #0
        ldx scr_height
        cpx #50
        bne :+
        lda #VIC_SET
:       ldx scr_width
        cpx #40
        bne :+
        lda #2 * VIC_SET
:       sta sj_tmp
        ldy #VIC_SET - 1        ; last to first: the hot registers first
@reg:   tya
        clc
        adc sj_tmp
        tax
        lda vic_sets,x
        ldx vic_regs,y
        sta VIC_BASE,x
        dey
        bpl @reg
        lda #0
        sta VIC_SP_EN           ; sprites off
        lda #$0E                ; the lower/upper-case set: $D018's hot
        KJMP CHROUT             ;   write reset the character pointer
.endif
.endproc

; ═════════════════════════════════════════════════════════
; reset_screen — clear screen + restore colors
; ═════════════════════════════════════════════════════════
.proc reset_screen
.ifdef PLATFORM_C64
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
        sta IO_CX
        sta IO_CY
        jmp io_sync
.else
        jsr restore_colors
        lda #$20                ; the whole screen, one DMA fill
        ldx #0
        jsr fill_rows_from
        lda #0
        sta IO_CX
        sta IO_CY
        jmp io_sync
.endif
.endproc

.ifdef PLATFORM_M65
; ═════════════════════════════════════════════════════════
; screen_mode_set — ESC A through BSOUT (A = '4' 40 x 25, '5' 80 x 50,
; '8' 80 x 25: the KERNAL switches and clears), then the geometry, the
; VIC set, the colours, the cursor home (screen.md; m65 only).
; Clobbers A, X, Y.
; ═════════════════════════════════════════════════════════
screen_mode_set:
        pha
        lda #$1B                ; ESC
        KCALL CHROUT
        pla
        KCALL CHROUT
        jsr io_geometry
        jsr vic_reset
        jsr restore_colors
        lda #0
        sta IO_CX
        sta IO_CY
        jmp io_sync
.endif

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
; CALL SITE — exactly one: `hygiene_after_userland` in repl.s, run
; on every return from user code (main.s handler_finalize).  NOT
; called from reset_screen (cold init, the `x` command, cse_refresh,
; scroll_up's full clear) — those paths have no mid-CHROUT KERNAL
; state to recover from, and resetting LDTB1 / $D5 there would wipe
; the line-link state that matches the displayed content and that
; later userland CHROUT positions against.
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
; are set by the io_sync (KERNAL PLOT) tail call that follows in
; hygiene_after_userland.
; Clobbers: A, X.
; ═════════════════════════════════════════════════════════
.proc kernal_screen_reset
.ifdef PLATFORM_C64
        ; LDTB1 ($D9-$F1, 25 bytes): KERNAL stores the row's
        ; screen-address page in the low 7 bits, with bit 7 set to
        ; mark a logical-line start.  E.g. row 0 (addr $0400) →
        ; $80 | $04 = $84;  row 10 ($0590) → $80 | $05 = $85.
        ;
        ; A flat $80 fill puts the page at $00 (effectively $04 via
        ; KERNAL's internal screen-base addition), sending every
        ; row's CHROUT writes back into page $04 — the "first 256
        ; chars only" symptom in user code post-NMI-recovery.  Use
        ; CSE's existing scr_hi[r] table to get the correct per-row
        ; page byte.
        ;
        ; Loop range: ldx #25; lda scr_hi-1,x; sta $D8,x; dex; bne @l
        ; covers x=25..1 → reads scr_hi[24..0], writes LDTB1[24..0]
        ; ($F1..$D9).  Exits with X=0 so we can reuse `stx` for the
        ; four zero-store targets ($C6/$CE/$D4/$D8).
        ldx #SCR_H              ; 25
@l:     lda scr_hi-1,x          ; scr_hi[x-1]
        ora #$80                ; mark logical-line start
        sta LDTB1-1,x           ; LDTB1[x-1]  ($D8+x = $D9..$F1)
        dex
        bne @l                  ; exits with X=0
        ; X=0 — reuse for every byte that resets to zero.
        stx NDX                 ; NDX (key buffer count)
        stx GDBLN               ; GDBLN (char-under-cursor)
        stx QTSW                ; QTSW (quote mode)
        stx INSRT               ; INSRT (loop skipped this slot)
        lda #SCR_W - 1          ; 39
        sta LNMX                ; LNMX
        rts
.else
        ; A1: ESC O (quote and insert mode off — first, so what follows
        ; is obeyed), HOME HOME (out of a program's window); the caller's
        ; io_sync then tells the KERNAL CSE's cursor.  No line links.
        ldx #0
@seq:   stx sj_tmp
        lda ksr_seq,x
        KCALL CHROUT
        ldx sj_tmp
        inx
        cpx #KSR_LEN
        bcc @seq
        rts
.endif
.endproc

; ═════════════════════════════════════════════════════════
; scroll_up(n) — scroll screen RAM up by A rows
; Color RAM is static (initialized once, never scrolled).
;   A = n
; ═════════════════════════════════════════════════════════
.proc scroll_up
        cmp HEIGHT
        bcc @partial
        ; full clear
        jmp reset_screen

@partial:
        ; A = n rows to scroll (screen RAM only; color RAM is static).
        ; Stack usage: [n] [src_row] [dst_row] — all saved/restored via PHA/PLA.
        pha                     ; save n on stack
.ifdef PLATFORM_M65
        ; one DMA copy of rows n.. to row 0, one fill of the last n rows
        tax
        jsr rows_from           ; sj_dst = row n, sj_count = the bytes from it
        ldx #2
@src:   lda sj_dst,x
        sta sj_src,x
        dex
        bpl @src
        lda scr_lo
        sta sj_dst
        lda scr_hi
        sta sj_dst+1
        ldx #DMA_COPY
        ldy #0
        jsr scr_dma             ; ascending: the overlap is safe
        pla
        pha
        eor #$FF                ; the first row to clear: height - n
        sec
        adc scr_height
        tax
        lda #$20
        jsr fill_rows_from
.else

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
.endif

        ; Adjust cursor row: io_cy = max(io_cy - n, 0)
        pla                     ; A = n (saved at entry)
        eor #$FF
        sec
        adc IO_CY               ; A = io_cy - n (via two's complement add)
        bcs @set_row
        lda #0
@set_row:
        sta IO_CY
        jmp io_sync
.endproc

; ═════════════════════════════════════════════════════════
; newline — advance to next row, scroll if at bottom
; ═════════════════════════════════════════════════════════
.proc newline
        lda IO_CY
        cmp LAST_ROW
        bcc @no_scroll
        ; at bottom row — scroll up 1
        lda #1
        jsr scroll_up
        lda LAST_ROW
        sta IO_CY
        bne @col0               ; always taken (SCR_H-1 = 24 ≠ 0)
@no_scroll:
        inc IO_CY
@col0:  lda #0
        sta IO_CX
        jmp io_sync
.endproc

; ═════════════════════════════════════════════════════════
; ═════════════════════════════════════════════════════════
; cursor_show / cursor_hide — XOR $80 at cursor position
; ═════════════════════════════════════════════════════════
.proc cursor_show
        jsr _io_scr_setup       ; _io_scr ← screen row for IO_CY
        ldy IO_CX
        FAR_LDA _io_scr
        eor #$80
        FAR_STA _io_scr
        rts
.endproc

; cursor_hide is identical
cursor_hide = cursor_show

; Color RAM is static: restore_colors fills it, nothing scrolls it.
