; cse_io.s — Ultra-lean screen I/O library for CSE
;
; Screen I/O functions.  Single arg in A or A/X.
; Cursor position uses KERNAL's $D3 (column) and $D6 (row).
; Call io_sync after changing $D6 to update screen line pointers.
;
; INVARIANT: $CC must be 1 (KERNAL cursor disabled).  io_init
; enforces this.  All IRQ safety guarantees depend on it.
;
; Code: ~330 bytes.  RODATA: 76 bytes.  ZP: 4 bytes.  BSS: 2 bytes.

        .export io_init
        .export io_putc, io_repc, io_puts
        .export pet_to_scr, scr_to_pet
        .export io_puthex4, io_puthex2, io_putdec, io_putdec_pd
        .export io_utoa, dec_buf
        .export io_clear_eol
        .export io_getc, io_kbhit
        .export io_sync
        .export io_color
        .export io_blip
        .export scr_lo, scr_hi  ; shared row address tables (used by screen.s, disk.s)
        .export _io_scr_setup   ; shared row pointer setup (used by screen.s)

        .export dec_pow_lo, dec_pow_hi

COLS    = 40
ROWS    = 25
SCREEN  = $0400

; KERNAL ZP locations
CUR_COL = $D3           ; cursor column
CUR_ROW = $D6           ; cursor row
SCR_PTR = $D1           ; screen line pointer (lo/hi)
COL_PTR = $F3           ; color RAM line pointer (lo/hi)

; SID registers (only for io_blip)
SID_V1_FREQ_LO = $D400
SID_V1_FREQ_HI = $D401
SID_V1_CTRL    = $D404
SID_VOL        = $D418

        .importzp _io_tmp, _io_scr

; ── BSS ─────────────────────────────────────────────────────
.segment "BSS"
io_color: .res 1       ; text color for screen clears
dec_buf:  .res 6       ; io_utoa: 5-digit PETSCII decimal + NUL

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

; Powers of 10 (low→high): io_utoa indexes 4→0 via dex/bpl
dec_pow_lo:     .byte <1, <10, <100, <1000, <10000
dec_pow_hi:     .byte >1, >10, >100, >1000, >10000

; ── CODE ────────────────────────────────────────────────────
.segment "CODE"

; ── io_init — must be called once at startup ──────────────────────────
; Disables KERNAL cursor ($CC=1).  All cse_io IRQ safety depends on this.
io_init:
        lda #1
        sta $CC                 ; KERNAL cursor off — required invariant
        rts

; NMI handler lives in main.s (cse_nmi_handler); the Phase-18
; swallow-in-kernel model eliminated the nmi_pending flag that
; formerly lived here.

; ── _io_scr_setup — set _io_scr to screen line address for CUR_ROW ───
; Clobbers A, X.
_io_scr_setup:
        ldx CUR_ROW
        lda scr_lo,x
        sta _io_scr
        lda scr_hi,x
        sta _io_scr+1
        rts

; ── io_sync — update screen/color line pointers from cursor position ──
; Call after changing $D6 (io_cy) or $D3 (io_cx).
; Uses KERNAL PLOT to keep all internal state consistent,
; preventing the IRQ cursor blinker from corrupting pointers.
io_sync:
        ldx CUR_ROW
        ldy CUR_COL
        clc                     ; CLC = set position
        jmp $FFF0               ; KERNAL PLOT: sets $D1/$D2/$D3/$D6/$F3/$F4

; ── pet_to_scr — PETSCII → screen code (pure function) ──────
; In:  A = PETSCII byte
; Out: A = screen code
; Clobbers: flags only
;
; CSE display mapping (lower/upper charset), 32-byte chunks:
;   $00-$1F -> $80-$9F    (ORA #$80)
;   $20-$3F -> $20-$3F    (identity)
;   $40-$5F -> $00-$1F    (A - $40)
;   $60-$7F -> $40-$5F    (A - $20)
;   $80-$9F -> $80-$9F    (identity)
;   $A0-$BF -> $60-$7F    (A - $40)
;   $C0-$FF -> $40-$7F    (A - $80)
pet_to_scr:
        cmp #$80
        bcs @ge80
        cmp #$40
        bcs @ge40
        cmp #$20
        bcc @or80              ; $00-$1F -> $80-$9F
                               ; $20-$3F unchanged
        rts

@or80:  ora #$80
        rts

@ge40:  cmp #$60
        bcc @sub40c            ; $40-$5F -> $00-$1F, C=0
        sbc #$20               ; $60-$7F -> $40-$5F, C=1
        rts

@sub40c:
        sbc #$3F               ; C=0 => A-$40
        rts

@ge80:  cmp #$A0
        bcc @done              ; $80-$9F unchanged
        cmp #$C0
        bcc @sub40s            ; $A0-$BF -> $60-$7F
        sbc #$80               ; $C0-$FF -> $40-$7F, C=1
        rts

@sub40s:
        sbc #$3F               ; C=0 => A-$3F-1 = A-$40
@done:  rts

; ── scr_to_pet — screen code → PETSCII (pure function) ──────
; In:  A = screen code (bit 7 must be stripped by caller)
; Out: A = PETSCII byte
; Clobbers: flags only
;
; Mapping (32-byte chunks):
;   $00-$1F -> $40-$5F    (ORA #$40, lowercase a-z)
;   $20-$3F -> $20-$3F    (identity, digits/punctuation)
;   $40-$5F -> $C0-$DF    (ORA #$80, uppercase A-Z)
;   $60-$7F -> $60-$7F    (identity, graphics)
scr_to_pet:
        cmp #$40
        bcs @ge40
        cmp #$20
        bcs @done              ; $20-$3F identity
        ora #$40               ; $00-$1F -> $40-$5F
@done:  rts
@ge40:  cmp #$60
        bcs @done              ; $60-$7F identity
        ora #$80               ; $40-$5F -> $C0-$DF
        rts

; ── io_putc — write PETSCII char at cursor, advance ─────────
; A = PETSCII char
io_putc:
        jsr pet_to_scr         ; A = screen code
        tay
        jsr _io_scr_setup      ; preserves Y
        tya
        ldy CUR_COL
        sta (_io_scr),y
        iny
        ; fall through to _col_clamp

; ── _col_clamp — clamp Y to COLS-1 and store to CUR_COL ─────
_col_clamp:
        cpy #COLS
        bcc :+
        ldy #COLS-1
:       sty CUR_COL
        rts

; ── io_repc — repeat PETSCII char at cursor, advance  ─────────
; A = PETSCII char, X = number of repetitions
; clobbers X, Y, _io_tmp
io_repc:
        cpx #0
        beq :+
        stx _io_tmp
@lp:    pha
        jsr io_putc
        pla
        dec _io_tmp
        bne @lp
:       rts

; ── io_puts — write NUL-terminated PETSCII string ───────────
; A/X = string pointer (A=lo, X=hi)
io_puts:
        sta _io_tmp
        stx _io_tmp+1
@loop:  ldy #0
        lda (_io_tmp),y
        beq @done
        jsr io_putc
        inc _io_tmp
        bne @loop
        inc _io_tmp+1
        bne @loop               ; always taken
@done:  rts

; ── io_puthex4 — write 4 hex digits ─────────────────────────
; A=lo, X=hi
io_puthex4:
        pha                     ; save lo byte
        txa                     ; A = hi byte
        jsr io_puthex2         ; print hi byte as 2 digits
        pla                     ; A = lo byte
        ; fall through to puthex2

; ── io_puthex2 — write 2 hex digits ─────────────────────────
; A = byte value
io_puthex2:
        pha                     ; save byte
        jsr _io_scr_setup
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
        jmp _col_clamp

; ── io_utoa — 16-bit unsigned to PETSCII decimal in dec_buf ──
;
; In:  A=lo, X=hi.  Call with:
;        CLC → skip leading zeros, return offset in A
;        SEC → pad leading zeros with spaces, return 0 in A
;
; Out: dec_buf = NUL-terminated PETSCII string
;      A = offset into dec_buf (0..4)
;
; Clobbers: X,Y,flags

io_putdec:
        clc
io_putdec_pd:
        jsr io_utoa            ; A = offset
        clc
        adc #<dec_buf
        pha
        lda #>dec_buf
        adc #0
        tax
        pla
        jmp io_puts

io_utoa:
        php                    ; save C flag for wrapper
        sta _io_tmp            ; dividend lo
        stx _io_tmp+1          ; dividend hi

        ; ── core: 5-digit conversion into dec_buf[0..4] ──
        ; Outer: X counts buf position 0..4
        ; Inner: Y counts digit value for each power of 10
        ; Power index = 4-X (X=0→10000, X=4→1)
        ldx #4                 ; power-of-10 index (4=10000..0=1)
        ldy #0                 ; buf position
@pow:   sty dec_buf+5          ; save buf pos (reuse NUL slot as temp)
        ldy #0                 ; digit counter
@sub:   lda _io_tmp
        sec
        sbc dec_pow_lo,x
        pha                    ; tentative lo
        lda _io_tmp+1
        sbc dec_pow_hi,x
        bcc @done_digit        ; borrow → digit complete
        sta _io_tmp+1          ; commit hi
        pla
        sta _io_tmp            ; commit lo
        iny                    ; digit++
        bne @sub               ; always (digit ≤ 9)

@done_digit:
        pla                    ; discard tentative lo
        tya
        ora #'0'               ; A = PETSCII digit
        ldy dec_buf+5          ; Y = buf position
        sta dec_buf,y          ; store digit
        iny                    ; next buf pos
        dex                    ; next power
        bpl @pow

        lda #0
        sta dec_buf,y          ; NUL terminator at [5]

        ; ── shared post-pass: replace leading '0' with ' ' ──
        ; X ends as first significant offset (or 4 for zero)
        ldx #$ff
@scan:  inx
        lda dec_buf,x
        cmp #'0'
        bne @found
        cpx #4
        beq @found
        lda #' '
        sta dec_buf,x
        bne @scan              ; always

@found: plp
        bcc @retx              ; CLC: return offset
        ldx #0                 ; SEC: padded → offset 0
@retx:  txa
        rts

; ── io_clear_eol — fill spaces from cursor to end of row ────
io_clear_eol:
        jsr _io_scr_setup
        ldy CUR_COL
@loop:  cpy #COLS
        bcs @done
        lda #$20                ; space screen code
        sta (_io_scr),y
        iny
        bne @loop               ; always (Y < 256)
@done:  rts

; ── io_getc — blocking keyboard read ────────────────────────
io_getc:
        jsr $FFE4               ; KERNAL GETIN
        beq io_getc            ; loop until key pressed
        ldx #0
        rts

; ── io_kbhit — non-blocking keyboard check ──────────────────
io_kbhit:
        lda $C6                 ; keyboard buffer count
        ldx #0
        rts

; ── io_blip — short audible reject blip ────────────────────
;
; Plays a brief triangle pulse on SID voice 1 as audible
; feedback for refused input (line cap, backspace into the
; left wall, refused commands).  Originally implemented as
; click_sound() in the project's very first commit (28fb2dd),
; where it fired on backspace at column 0.
;
; The volume register stays set to 10 after the first call
; (the SID's amp/filter byte at $D418).  This is intentional:
; later blips skip the re-init cost.  User code that wants
; its own SID setup will reinitialize.
;
; Clobbers: A, X.  Preserves Y.
.proc io_blip
        lda #$00
        sta SID_V1_FREQ_LO
        lda #$80                ; freq hi → ~2200 Hz
        sta SID_V1_FREQ_HI
        lda #10
        sta SID_VOL
        lda #$11                ; gate=1, triangle=1
        sta SID_V1_CTRL
        ; Brief busy-wait (~200 cycles ≈ 0.2 ms)
        ldx #200
@wait:  dex
        bne @wait
        lda #$00                ; gate=0
        sta SID_V1_CTRL
        rts
.endproc
