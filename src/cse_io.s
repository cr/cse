; cse_io.s — Ultra-lean screen I/O library for CSE
;
; Replaces cc65 conio.h entirely.  All functions __fastcall__.
; Cursor position uses KERNAL's $D3 (column) and $D6 (row).
; Call io_sync after changing $D6 to update screen line pointers.
;
; INVARIANT: $CC must be 1 (KERNAL cursor disabled).  io_init
; enforces this.  All IRQ safety guarantees depend on it.
;
; Code: ~330 bytes.  RODATA: 76 bytes.  ZP: 4 bytes.  BSS: 2 bytes.

        .export _io_init
        .export _io_putc, _io_puts
        .export _io_puthex4, _io_puthex2, _io_putdec
        .export _io_clear_eol
        .export _io_getc, _io_kbhit
        .export _io_sync
        .export _io_color
        .export scr_lo, scr_hi  ; shared row address tables (used by screen.s, disk.s)

        ; Parameter stack helpers
        .export cse_popax

        ; NMI handler — pure asm, no C prologue.
        .export _nmi_handler
        .export _nmi_pending

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
_io_scr:  .res 2        ; screen row pointer for io_putc

; ── BSS ─────────────────────────────────────────────────────
.segment "BSS"
_io_color: .res 1       ; text color for screen clears
dec_start_col: .res 1   ; io_putdec: saved start column (ROM-safe)
_nmi_pending: .res 1    ; NMI flag — set by nmi_handler, read by main loop

; ── RODATA ──────────────────────────────────────────────────
.segment "RODATA"

scr_lo:
        .repeat 25, i
        .byte <(SCREEN + i * 40)
        .endrepeat
scr_hi:
        .repeat 25, i
        .byte >(SCREEN + i * 40)
        .endrepeat

hex_tab:                ; screen codes for hex digits 0-9, a-f
        .byte $30,$31,$32,$33,$34,$35,$36,$37
        .byte $38,$39,$01,$02,$03,$04,$05,$06

dec_lo:                 ; powers of 10, lo bytes
        .byte <10000, <1000, <100, <10, <1
dec_hi:                 ; powers of 10, hi bytes
        .byte >10000, >1000, >100, >10, >1

; ── CODE ────────────────────────────────────────────────────
.segment "CODE"

; ═════════════════════════════════════════════════════════════════
; C stack helpers — drop-in replacements for cc65's popax/popa.
; Parameter stack helpers — push/pop 16-bit values via the
; shared `sp` ZP pointer (exported by main.s).
; ═════════════════════════════════════════════════════════════════

        .importzp sp

; cse_popax: pop 16-bit value from C stack → A (lo), X (hi)
.proc cse_popax
        ldy #1
        lda (sp),y              ; hi byte
        tax
        dey
        lda (sp),y              ; lo byte
        pha                     ; save lo
        clc
        lda sp
        adc #2
        sta sp
        bcc :+
        inc sp+1
:       pla                     ; restore lo → A
        rts
.endproc

; ── io_init — must be called once at startup ──────────────────────────
; Disables KERNAL cursor ($CC=1).  All cse_io IRQ safety depends on this.
_io_init:
        lda #1
        sta $CC                 ; KERNAL cursor off — required invariant
        rts

; ── NMI handler — pure asm, no C prologue ────────────────────────────
; The KERNAL NMI entry ($FE43) does SEI + JMP ($0318).  It does NOT
; push A/X/Y — only the CPU's automatic PC + SR are on the stack.
;
; Two-path check: if debugger is running user code (_dbg_running bit 7),
; break into the debugger.  Otherwise, set the nmi_pending flag as before.
;
        .import _dbg_running
        .import _dbg_nmi_break

_nmi_handler:
        bit _dbg_running        ; bit 7 → N flag
        bmi @break_user         ; user code active → debugger break
        ; Normal NMI (REPL/editor): set flag, RTI
        pha
        lda #1
        sta _nmi_pending
        pla
        rti

@break_user:
        ; A/X/Y are live user values — don't clobber them here.
        ; The debugger handler saves them.
        jmp _dbg_nmi_break

; ── io_sync — update screen/color line pointers from cursor position ──
; Call after changing $D6 (io_cy) or $D3 (io_cx).
; Uses KERNAL PLOT to keep all internal state consistent,
; preventing the IRQ cursor blinker from corrupting pointers.
_io_sync:
        ldx CUR_ROW
        ldy CUR_COL
        clc                     ; CLC = set position
        jmp $FFF0               ; KERNAL PLOT: sets $D1/$D2/$D3/$D6/$F3/$F4

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
        ; Write directly to SCREEN + row*40 + col using the row table.
        ; Uses _io_scr (not _io_tmp which io_puts needs for the string ptr).
        pha                     ; save screen code
        ldx CUR_ROW
        lda scr_lo,x
        sta _io_scr
        lda scr_hi,x
        sta _io_scr+1
        pla
        ldy CUR_COL
        sta (_io_scr),y
        iny
        cpy #COLS
        bcc :+
        ldy #COLS-1
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
        ; setup screen row pointer
        ldx CUR_ROW
        lda scr_lo,x
        sta _io_scr
        lda scr_hi,x
        sta _io_scr+1
        pla
        pha                     ; save byte again
        lsr                     ; shift hi nibble down
        lsr
        lsr
        lsr
        tax
        lda hex_tab,x           ; screen code for hi nibble
        ldy CUR_COL
        sta (_io_scr),y
        iny
        pla                     ; recover byte
        and #$0F
        tax
        lda hex_tab,x           ; screen code for lo nibble
        sta (_io_scr),y
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
        ; setup screen row pointer
        ldy CUR_ROW
        lda scr_lo,y
        sta _io_scr
        lda scr_hi,y
        sta _io_scr+1
        lda CUR_COL
        sta dec_start_col          ; remember starting column for leading-zero check
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
        cmp dec_start_col
        beq @next               ; no digits printed yet: skip leading zero
@force: tya                     ; A = digit (might be 0)
@print: tay
        lda hex_tab,y           ; screen code for digit
        ldy CUR_COL
        sta (_io_scr),y
        iny
        sty CUR_COL
@next:  inx
        cpx #5
        bne @pow
        rts
        ; dec_start_col moved to BSS (ROM-safe)

; ── io_clear_eol — fill spaces from cursor to end of row ────
_io_clear_eol:
        ldx CUR_ROW
        lda scr_lo,x
        sta _io_scr
        lda scr_hi,x
        sta _io_scr+1
        ldy CUR_COL
@loop:  cpy #COLS
        bcs @done
        lda #$20                ; space screen code
        sta (_io_scr),y
        iny
        bne @loop               ; always (Y < 256)
@done:  rts

; ── io_getc — blocking keyboard read ────────────────────────
_io_getc:
        jsr $FFE4               ; KERNAL GETIN
        beq _io_getc            ; loop until key pressed
        ldx #0
        rts

; ── io_kbhit — non-blocking keyboard check ──────────────────
_io_kbhit:
        lda $C6                 ; keyboard buffer count
        ldx #0
        rts
