; editor.s — gap-buffer source editor
; Owner: doc/modules/editor.md
;
; Screen layout:
;   Rows 0 .. ED_LAST   Source text (ED_ROWS lines: 22 on c64; m65 height − 3)
;   Row  ED_STATUS_ROW  Status bar
;   The two rows below  Last 2 lines preserved from REPL

        .include "platform.inc"
        .macpack longbranch

        ; Exports owned by editor.s (L4 — rendering + input + disk):
        .export enter_editor, leave_editor
        .export ed_handle_key
        .export ed_new
        ; ed_init is internal only; called by ed_new and ed_load_source.
        .export ed_save_source, ed_load_source
        .export ed_save_bytes, ed_save_lines

        ; Gap-buffer symbols (ed_insert_string, ed_read_*,
        ; ed_ensure_init, ed_total_lines, src_top, src_bot,
        ; define_ws_syms) are gap_buffer.s (L3) exports; consumers
        ; (main.s, repl.s, asm_src.s) import them from there.

        ; From gap_buffer.s (L3, strictly-downward):
        .import gb_init
        .import ed_ensure_init
        .import gb_insert, gb_backspace
        .import gb_cursor_left, gb_cursor_right, gb_home
        .import gb_clip_copy, gb_delete, gb_clip_put, gb_rev, clip_base
        .import check_buf_end
        .import ed_total_lines
        .import update_workend

        .import io_sync, io_blip
.ifdef PLATFORM_M65
        .import screen_save, screen_restore
.endif
        .import kernal_bank_out, kernal_bank_in
        .import disk_save_seq, disk_load_seq
        .import disk_seq_bytes, disk_seq_lines
        .importzp state, ed_dirty                     ; zp.s
.ifdef PLATFORM_C64
        .importzp cur_project_name                    ; zp.s
.else
        .import cur_project_name                      ; zp.s's BSS (zp.md)
.endif
        .import scr_lo, scr_hi
        .importzp disk_ptr

; ── Constants ────────────────────────────────────────────────
; The rows (platform.inc's operand defines; m65 run-time cells):
; ED_ROWS source rows (0 .. ED_LAST), the status bar on ED_STATUS_ROW,
; the two context rows below it.
; BUF_END (exclusive) and BUF_FLOOR: platform.inc's

; ── Tab width (build-time constant) ──────────────────────────
; TAB_WIDTH is set via `-DTAB_WIDTH=N` in the Makefile (default 8,
; matching every C64-era toolchain convention).  `col mod TAB_WIDTH`
; is computed as `and #TAB_MASK`, so TAB_WIDTH must be a power of
; two in 1..32; anything else is a build error.  See
; doc/modules/editor.md.
.ifndef TAB_WIDTH
TAB_WIDTH = 8
.endif
.if TAB_WIDTH < 1 .or TAB_WIDTH > 32 .or (TAB_WIDTH & (TAB_WIDTH - 1)) <> 0
.error "TAB_WIDTH must be 1, 2, 4, 8, 16 or 32"
.endif
TAB_MASK = TAB_WIDTH - 1

; State constants
ST_REPL      = 1
ST_EDIT      = 2

; Filename
FILENAME_MAX_LEN = 16

; Key codes
CH_ENTER     = 13
CH_DEL       = 20
CH_INS       = 148
CH_CURS_UP   = 145
CH_CURS_DOWN = 17
CH_CURS_LEFT = 157
CH_CURS_RIGHT = 29
CH_HOME      = 19

; ── Zero page ────────────────────────────────────────────────
.importzp gap_lo, gap_hi, buf_base, ed_top_ptr, read_ptr, ed_tmp, ed_scr
save_ptr = read_ptr

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

ed_cur_line:    .res 2          ; cursor line (0-based)
ed_mark1:       .res 2          ; the mark's line + 1 (0: no mark; BSS-zero) —
                                ;   right after ed_cur_line: _sel_redraw's loop
ed_cur_col:     .res 1          ; cursor visual column (0-based)
ed_top_line:    .res 2          ; line number at screen row 0
; ed_total_lines lives in gap_buffer.s (L3) — line count is
; gap-buffer state, updated on CR insert/delete.  ed_dirty lives in zp.s.
ed_save_bytes: .res 2          ; bytes from last file op
ed_save_lines: .res 2          ; lines from last file op
_load_overflow: .res 1         ; sticky: set if any insert during load
                                ; failed because the gap buffer is full
                                ; (file > workspace).  Read by
                                ; ed_load_source after the disk loop.
save_phase:     .res 1          ; 0=pre-gap, 1=post-gap
repl_cur_x:     .res 1          ; saved REPL cursor X
repl_cur_y:     .res 1          ; saved REPL cursor Y
rl_row:         .res 1          ; ed_render_line: its row
sel_lo:         .res 2          ; the selected lines (_select): the first
sel_hi:         .res 2          ;   and the last
sel_l0:         .res 2          ; ed_handle_key: ed_cur_line at its start
sel_m0:         .res 2          ;   and ed_mark1 (the same order)
; src_top / src_bot live in gap_buffer.s (L3) — they describe the
; buffer bounds and move with gb_ensure_room's allocation.

; ── RODATA ───────────────────────────────────────────────────
.segment "RODATA"

; Hex digit table for status bar (screen codes, OR'd with $80 for reverse)
st_hx:  .byte $30,$31,$32,$33,$34,$35,$36,$37
        .byte $38,$39,$01,$02,$03,$04,$05,$06

; The keys the mark survives (the first 8: _mark_policy) and, from the
; 6th, the clipboard keys C= (MEGA) + B X C V K J in ed_clip_key's order
; (editor.md § Clipboard and line moves).
ed_keys:
        .byte CH_CURS_UP, CH_CURS_DOWN, CH_CURS_LEFT, CH_CURS_RIGHT, CH_HOME
clip_keys:
        .byte $BF, $BD, $BC, $BE, $A1, $B5

; ── CODE ─────────────────────────────────────────────────────
.segment "CODE"

; ── Shared internal helpers ──────────────────────────────────

; _ed_scr_row — set ed_scr = screen address for row X
_ed_scr_row:
        lda scr_lo,x
        sta ed_scr
        lda scr_hi,x
        sta ed_scr+1
        FAR_BANK_SCREEN ed_scr  ; m65: the screen's bank
        rts

; ed_scr is a screen pointer (_ed_scr_row) or a buffer pointer (the
; three below, m65: BANK_SRC); a routine that walks it from there
; rewrites the offset only (gap_buffer.md, On m65).

; _ed_scr_top — set ed_scr = ed_top_ptr
_ed_scr_top:
        lda ed_top_ptr
        sta ed_scr
        lda ed_top_ptr+1
.ifdef PLATFORM_C64
        sta ed_scr+1
        rts
.else
        jmp _ed_scr_src
.endif

; _ed_scr_ghi — set ed_scr = gap_hi
_ed_scr_ghi:
        lda gap_hi
        sta ed_scr
        lda gap_hi+1
.ifdef PLATFORM_C64
        sta ed_scr+1
        rts
.else
        jmp _ed_scr_src
.endif

; _ed_scr_glo — set ed_scr = gap_lo
_ed_scr_glo:
        lda gap_lo
        sta ed_scr
        lda gap_lo+1
.ifdef PLATFORM_C64
        sta ed_scr+1
        rts
.else
_ed_scr_src:                    ; A = the offset's high byte
        sta ed_scr+1
        FAR_BANK ed_scr, BANK_SRC
        rts

; _ed_status_right — ed_scr = the status row + (width − 40), so the
; c64 bar's columns 19–39 (free: and LLLL,CC) are anchored to the
; right edge (editor.md, On m65).  Clobbers A, X.
_ed_status_right:
        ldx ED_STATUS_ROW
        jsr _ed_scr_row
        lda scr_width
        sec
        sbc #40
        clc
        adc ed_scr
        sta ed_scr
        bcc :+
        inc ed_scr+1
:       rts
.endif

; _ed_cur_row — A = ed_cur_line - ed_top_line (screen row)
; Leaves carry from the low-byte subtraction intact for callers that
; immediately SBC the high bytes.
_ed_cur_row:
        lda ed_cur_line
        sec
        sbc ed_top_line
        rts

; ── ed_init — reset full editor state ────────────────────────
; Wrapper that calls gb_init (L3 — resets gap-buffer state), zeros
; the rendering state owned by editor.s (L4 — cursor position, top-
; line scroll anchor), then republishes the `workend` symbol via
; update_workend.  Called by ed_new (k command) and ed_load_source
; (disk load).  Cold init does NOT call ed_init — it goes through
; ed_ensure_init → gb_init directly, with main.s publishing
; workstart/workend explicitly via define_ws_syms.
.proc ed_init
        jsr gb_init
        lda #0
        sta ed_cur_line
        sta ed_cur_line+1
        sta ed_cur_col
        sta ed_top_line
        sta ed_top_line+1
        sta ed_mark1
        sta ed_mark1+1
        jmp update_workend      ; publish workend; tail-call
.endproc

; ── ed_new — clear editor (new file) ─────────────────────────
.proc ed_new
        jsr ed_init
        lda #0
        sta cur_project_name
        rts
.endproc

; ── Rendering + status bar ───────────────────────────────────

; ── char_width — visual width of a byte at given column ───────
; Input: A = byte, X = vcol
; Output: A = width (1 for normal, 1..TAB_WIDTH for tab)
; Clobbers: A, ed_tmp (tab case uses ed_tmp as scratch)
;
; CAVEAT: callers must NOT save state in ed_tmp before calling
; char_width — the tab path clobbers it.
.proc char_width
        cmp #$A0
        bne @one
        ; Tab: width = TAB_WIDTH - (vcol mod TAB_WIDTH)
        txa                     ; A = vcol
        and #TAB_MASK           ; A = vcol mod TAB_WIDTH
        sta ed_tmp              ; save remainder
        lda #TAB_WIDTH
        sec
        sbc ed_tmp              ; TAB_WIDTH - remainder
        rts
@one:   lda #1
        rts
.endproc

; ── skip_gap_scr — if ed_scr == gap_lo, set ed_scr = gap_hi ───
; Uses ed_scr as the pointer (in/out)
; Clobbers: A
.proc skip_gap_scr
        lda ed_scr
        cmp gap_lo
        bne @done
        lda ed_scr+1
        cmp gap_lo+1
        bne @done
        jsr _ed_scr_ghi
@done:  rts
.endproc

; check_buf_end (ed_scr >= BUF_END → C=1) is gap_buffer.s's.

; ── blank_row — fill screen row X with spaces ─────────────────
; Clobbers: A, Y, ed_tmp
.proc blank_row
        lda scr_lo,x
        sta ed_tmp
        lda scr_hi,x
        sta ed_tmp+1
        FAR_BANK_SCREEN ed_tmp
        lda #$20
        ldy LAST_COL
@blank: FAR_STA ed_tmp
        dey
        bpl @blank
        rts
.endproc

; ── ed_sync_cursor — push editor cursor to KERNAL cursor ─────
; Off-screen cursor rows are ignored.
.proc ed_sync_cursor
        jsr _ed_cur_row
        cmp ED_ROWS
        bcs @done
        sta IO_CY
        lda ed_cur_col
        sta IO_CX
        jsr io_sync
@done:  rts
.endproc

; ── ed_render_line — render one line to screen row ────────────
; Input: X = screen row, ed_scr = buffer position (in/out, advances past CR)
; Output: A = 1 if more text, 0 if EOF. ed_scr updated.
; Clobbers: A, X, Y
.proc ed_render_line
        stx rl_row              ; the row, for the selection's inversion
        ; Setup screen pointer in ed_tmp
        lda scr_lo,x
        sta ed_tmp
        lda scr_hi,x
        sta ed_tmp+1
        FAR_BANK_SCREEN ed_tmp
        ldy #0                  ; col = 0

@char_loop:
        cpy WIDTH
        bcc :+
        ; Line overflows screen — show > indicator in the last column.
        ; Skip remaining content until CR or EOF.
        lda #$3E                ; '>' (normal, not reversed)
        ldy LAST_COL
        FAR_STA ed_tmp
        jmp @skip_rest
:
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @pad
        ; Read byte
        sty @save_col           ; save col (Y)
        ldy #0
        FAR_LDA ed_scr
        ldy @save_col           ; restore col

        ; Check CR
        cmp #$0D
        beq @cr

        ; Check tab ($A0)
        cmp #$A0
        beq @tab

        ; PETSCII → screencode conversion
        ; $41-$5A → $01-$1A (lowercase)
        cmp #$41
        bcc @no_conv
        cmp #$5B
        bcc @lower
        ; $C1-$DA → $41-$5A (uppercase)
        cmp #$C1
        bcc @no_conv
        cmp #$DB
        bcs @no_conv
        sec
        sbc #$80                ; $C1→$41
        jmp @store
@lower:
        sec
        sbc #$40                ; $41→$01
        jmp @store
@no_conv:
@store:
        FAR_STA ed_tmp          ; scr[col] = sc
        iny                     ; ++col
        ; ++ed_scr
        inc ed_scr
        bne @char_loop
        inc ed_scr+1
        jmp @char_loop

@tab:
        ; Expand tab: fill spaces up to next TAB_WIDTH boundary.
        ; width = TAB_WIDTH - (col mod TAB_WIDTH)
        tya                     ; col
        and #TAB_MASK           ; col mod TAB_WIDTH
        sta @tw_save
        lda #TAB_WIDTH
        sec
        sbc @tw_save            ; width = TAB_WIDTH - (col mod TAB_WIDTH)
        tax                     ; X = width counter
@tab_fill:
        cpy WIDTH
        bcs @tab_advance
        lda #$20
        FAR_STA ed_tmp
        iny
        dex
        bne @tab_fill
@tab_advance:
        ; ++ed_scr
        inc ed_scr
        bne :+
        inc ed_scr+1
:       jmp @char_loop

@cr:
        ; Advance past CR
        inc ed_scr
        bne @pad
        inc ed_scr+1
@pad:
        ; Pad rest of row with spaces
        cpy WIDTH
        bcs @pad_done
        lda #$20
        FAR_STA ed_tmp
        iny
        bne @pad                ; Y never wraps to 0 within 40 iterations

@skip_rest:
        ; Advance ed_scr past remaining content until CR or EOF.
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @pad_done
        ldy #0
        FAR_LDA ed_scr
        inc ed_scr
        bne :+
        inc ed_scr+1
:       cmp #$0D
        bne @skip_rest
@pad_done:
        jsr _sel_row            ; a selected line: the row inverted
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @ret_eof
        lda #1
        rts
@ret_eof:
        lda #0
        rts

        .segment "BSS"      ; CODE stays read-only
@save_col: .res 1
@tw_save:  .res 1
        .segment "CODE"
.endproc

; ── skip_one_line — advance ed_scr past one line ─────────────
; Input/Output: ed_scr (advances to start of next line)
; Clobbers: A, Y
.proc skip_one_line
@loop:
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @done
@read:  ldy #0
        FAR_LDA ed_scr
        inc ed_scr
        bne :+
        inc ed_scr+1
:       cmp #$0D
        bne @loop
@done:  rts
.endproc

; ── prev_line_start — retreat ed_scr to start of previous line ─
; Input/Output: ed_scr
; Clobbers: A, Y
.proc prev_line_start
        FAR_BANK ed_tmp, BANK_SRC       ; ed_tmp walks the buffer here
        ; If ed_scr == gap_hi → set to gap_lo
        lda ed_scr
        cmp gap_hi
        bne @not_gap1
        lda ed_scr+1
        cmp gap_hi+1
        bne @not_gap1
        jsr _ed_scr_glo
@not_gap1:
        ; If ed_scr <= buf_base → return buf_base
        lda ed_scr+1
        cmp buf_base+1
        bcc @at_base
        bne @step_back
        lda ed_scr
        cmp buf_base
        bcc @at_base
        beq @at_base
@step_back:
        ; --ed_scr (step back over $0D of current line end)
        lda ed_scr
        bne :+
        dec ed_scr+1
:       dec ed_scr
        ; Skip gap backwards
        lda ed_scr
        cmp gap_hi
        bne @scan_back
        lda ed_scr+1
        cmp gap_hi+1
        bne @scan_back
        jsr _ed_scr_glo
@scan_back:
        ; Scan backwards to previous $0D or buf_base
@bloop:
        ; Check ed_scr > buf_base
        lda ed_scr+1
        cmp buf_base+1
        bcc @at_base
        bne @check_prev
        lda ed_scr
        cmp buf_base
        bcc @at_base
        beq @done               ; at buf_base → this is the start
@check_prev:
        ; Look at byte before ed_scr
        ; prev = ed_scr - 1
        lda ed_scr
        sec
        sbc #1
        sta ed_tmp
        lda ed_scr+1
        sbc #0
        sta ed_tmp+1
        ; Skip gap for prev
        lda ed_tmp
        cmp gap_hi
        bne @no_gap_prev
        lda ed_tmp+1
        cmp gap_hi+1
        bne @no_gap_prev
        lda gap_lo
        sta ed_tmp
        lda gap_lo+1
        sta ed_tmp+1
@no_gap_prev:
        ; Check prev < buf_base
        lda ed_tmp+1
        cmp buf_base+1
        bcc @done               ; prev < buf_base → stop
        bne @check_cr
        lda ed_tmp
        cmp buf_base
        bcc @done
@check_cr:
        ; Check if *prev == $0D
        ldy #0
        FAR_LDA ed_tmp
        cmp #$0D
        beq @done               ; found previous line's CR
        ; ed_scr = prev
        lda ed_tmp
        sta ed_scr
        lda ed_tmp+1
        sta ed_scr+1
        jmp @bloop

@at_base:
        lda buf_base
        sta ed_scr
        lda buf_base+1
        sta ed_scr+1
@done:  rts
.endproc

; ── st_hex4 — write 4 reversed hex digits to screen ──────────
; Input: ed_scr = screen destination, ed_tmp = 16-bit value
; Clobbers: A, X, Y
.proc st_hex4
        lda ed_tmp+1
        lsr
        lsr
        lsr
        lsr
        tax
        lda st_hx,x
        ora #$80
        ldy #0
        FAR_STA ed_scr

        lda ed_tmp+1
        and #$0F
        tax
        lda st_hx,x
        ora #$80
        iny
        FAR_STA ed_scr

        lda ed_tmp
        lsr
        lsr
        lsr
        lsr
        tax
        lda st_hx,x
        ora #$80
        iny
        FAR_STA ed_scr

        lda ed_tmp
        and #$0F
        tax
        lda st_hx,x
        ora #$80
        iny
        FAR_STA ed_scr
        rts
.endproc

; ── div10 — divide 16-bit value by 10 ────────────────────────
; Input: ed_tmp = dividend (16-bit)
; Output: ed_tmp = quotient, A = remainder
; Clobbers: X
.proc div10
        ; 16-bit divide: ed_tmp / 10 → ed_tmp = quotient, A = remainder
        ; Uses local @rem — must NOT clobber ed_scr (callers use it as screen ptr)
        lda #0
        sta @rem
        ldx #16
@loop:  asl ed_tmp
        rol ed_tmp+1
        rol @rem
        lda @rem
        sec
        sbc #10
        bcc @no_sub
        sta @rem
        inc ed_tmp              ; set quotient bit
@no_sub:
        dex
        bne @loop
        lda @rem                ; remainder in A
        rts
        .segment "BSS"      ; CODE stays read-only
@rem:   .res 1
        .segment "CODE"
.endproc

; ── ed_status_pos — update cursor position (cols 33-39; m65: from
; the right edge, _ed_status_right) ──────────────────────────────
.proc ed_status_pos
        ; Screen pointer to status row
.ifdef PLATFORM_C64
        ldx ED_STATUS_ROW
        jsr _ed_scr_row
.else
        jsr _ed_status_right
.endif

        ; Column: 2 digits (1-based)
        lda ed_cur_col
        clc
        adc #1
        sta ed_tmp
        lda #0
        sta ed_tmp+1
        jsr div10               ; A = ones, ed_tmp = tens
        clc
        adc #$30
        ora #$80
        ldy #39
        FAR_STA ed_scr          ; ones digit

        lda ed_tmp              ; tens
        clc
        adc #$30
        ora #$80
        dey                     ; Y=38
        FAR_STA ed_scr

        lda #($2C | $80)        ; comma, reversed
        dey                     ; Y=37
        FAR_STA ed_scr

        ; Line (1-based): up to 4 digits right-aligned in cols 33-36,
        ; blank-padded (col 33 is the separator below line 1000),
        ; clamped at 9999.
        lda ed_cur_line
        clc
        adc #1
        sta ed_tmp
        lda ed_cur_line+1
        adc #0
        sta ed_tmp+1
        cmp #>10000
        bcc @lconv
        bne @lclamp
        lda ed_tmp
        cmp #<10000
        bcc @lconv
@lclamp:
        lda #<9999
        sta ed_tmp
        lda #>9999
        sta ed_tmp+1
@lconv: ldy #36
@ldig:  jsr div10               ; A = next digit, ed_tmp = rest (keeps Y)
        ora #($30 | $80)
        FAR_STA ed_scr
        dey
        lda ed_tmp
        ora ed_tmp+1
        bne @ldig
        lda #$A0                ; reversed space
@lpad:  cpy #33
        bcc @ldone
        FAR_STA ed_scr
        dey
        bne @lpad               ; always (Y >= 32)
@ldone: rts
.endproc

; ── ed_status_free — update upper free address (cols 29-32; m65:
; from the right edge, and fixed: PROG_HI) ───────────────────────
.proc ed_status_free
.ifdef PLATFORM_C64
        ldx ED_STATUS_ROW
        lda scr_lo,x
        clc
        adc #29
        sta ed_scr
        lda scr_hi,x
        adc #0
        sta ed_scr+1
        ; val = clip_base - 1 (workend: below the text and its clipboard)
        lda clip_base
        sec
        sbc #1
        sta ed_tmp
        lda clip_base+1
        sbc #0
        sta ed_tmp+1
.else
        jsr _ed_status_right
        lda ed_scr
        clc
        adc #29
        sta ed_scr
        bcc :+
        inc ed_scr+1
:       lda #<PROG_HI           ; workend: the program region's, fixed
        sta ed_tmp
        lda #>PROG_HI
        sta ed_tmp+1
.endif
        jmp st_hex4
.endproc

; ── ed_render_status — full status bar rebuild ────────────────
.proc ed_render_status
        ; Get screen pointer to status row
        ldx ED_STATUS_ROW
        jsr _ed_scr_row

        ; Fill with reversed spaces
        lda #$A0
        ldy LAST_COL
@fill:  FAR_STA ed_scr
        dey
        bpl @fill

        ; Dirty flag (col 0)
        lda ed_dirty
        beq @clean
        lda #($2A | $80)        ; '*' reversed
        jmp @dirty_done
@clean: lda #$A0
@dirty_done:
        ldy #0
        FAR_STA ed_scr

        ; Filename (cols 1-17)
        lda cur_project_name
        beq @no_name
        ; Find length of cur_project_name.  X indexes the filename so
        ; on c64 the ZP cur_project_name resolves to zp,X (2 B; LDA
        ; cur_project_name,Y would force abs,Y); m65: BSS, abs,X.
        ldx #0
@flen:  lda cur_project_name,x
        beq @flen_done
        inx
        cpx #FILENAME_MAX_LEN
        bcc @flen
@flen_done:
        stx @fn_len
        ; Strip ",s" suffix if present
        cpx #2
        bcc @fn_copy
        dex
        dex
        lda cur_project_name,x
        cmp #','
        bne @fn_copy
        stx @fn_len             ; stripped 2 chars
@fn_copy:
        ldx #0                  ; filename index
        ldy #1                  ; screen col = 1
@fn_loop:
        cpx @fn_len
        bcs @no_name
        cpy #18
        bcs @no_name
        lda cur_project_name,x
        ; PETSCII→screencode for filename
        cmp #$41
        bcc @fn_noconv
        cmp #$5B
        bcs @fn_noconv
        sec
        sbc #$40
@fn_noconv:
        ora #$80                ; reversed
        FAR_STA ed_scr
        inx
        iny
        bne @fn_loop            ; Y never wraps here
@no_name:
.ifdef PLATFORM_M65
        jsr _ed_status_right    ; the fields below anchored right
.endif

        ; "free:" label (cols 19-23)
        ldy #19
        lda #($06 | $80)        ; 'f' reversed screencode
        FAR_STA ed_scr
        iny
        lda #($12 | $80)        ; 'r'
        FAR_STA ed_scr
        iny
        lda #($05 | $80)        ; 'e'
        FAR_STA ed_scr
        iny
        lda #($05 | $80)        ; 'e'
        FAR_STA ed_scr
        iny
        lda #($3A | $80)        ; ':'
        FAR_STA ed_scr

        ; Lower free address (cols 24-27)
        lda ed_scr
        pha
        lda ed_scr+1
        pha
        lda #<WORKSTART             ; workstart (lower free bound)
        ldx #>WORKSTART
        sta ed_tmp
        stx ed_tmp+1
        pla
        sta ed_scr+1
        pla
        clc
        adc #24
        sta ed_scr
        lda ed_scr+1
        adc #0
        sta ed_scr+1
        jsr st_hex4

        ; '-' (col 28)
        ; ed_scr is now at col 24, need col 28 = +4
        lda #($2D | $80)        ; '-' reversed
        ldy #4
        FAR_STA ed_scr

        ; Upper free + cursor pos via partial updaters
        jsr ed_status_free
        jmp ed_status_pos       ; tail call

        .segment "BSS"      ; CODE stays read-only
@fn_len:  .res 1
        .segment "CODE"
.endproc

; ── ed_render_range — render screen rows from..to ─────────────
; Input: X = from_row, Y = to_row (exclusive)
; Clobbers: A, X, Y
.proc ed_render_range
        stx @from
        sty @to

        ; Start ed_scr at ed_top_ptr
        jsr _ed_scr_top

        ; Advance to from_row by skipping lines
        ldx #0
@skip:  cpx @from
        bcs @render
        jsr skip_one_line
        inx
        jmp @skip

@render:
        cpx @to
        bcs @done
        cpx ED_ROWS
        bcs @done

        ; Skip gap
        jsr skip_gap_scr
        jsr check_buf_end
        bcc @render_line

        ; Past EOF — blank the row
        stx @save_x
        jsr blank_row
        ldx @save_x
        inx
        jmp @render

@render_line:
        stx @save_x
        ; X = row for ed_render_line
        jsr ed_render_line
        ldx @save_x
        inx
        jmp @render

@done:  rts

        .segment "BSS"      ; CODE stays read-only
@from:   .res 1
@to:     .res 1
@save_x: .res 1
        .segment "CODE"
.endproc

; ── ed_render — full redraw (ED_ROWS lines + status) ─────────
.proc ed_render
        ldx #0
        ldy ED_ROWS
        jsr ed_render_range
        jmp ed_render_status
.endproc

; ── ed_render_rows — render range + status ────────────────────
; Input: X = from_row, Y = to_row (exclusive)
.proc ed_render_rows
        jsr ed_render_range
        jmp ed_render_status
.endproc

; ── ed_scroll_up — scroll screen up, render new bottom line ───
.proc ed_scroll_up
        ; Advance ed_top_ptr by one line
        jsr _ed_scr_top
        jsr skip_one_line
        lda ed_scr
        sta ed_top_ptr
        lda ed_scr+1
        sta ed_top_ptr+1
        ; ++ed_top_line
        inc ed_top_line
        bne :+
        inc ed_top_line+1
:
        ; Shift screen rows 1..ED_LAST → 0..ED_LAST-1, a row at a time.
        ; Row-by-row ascending copy: at iter k, dst = row k, src = row k+1.
        ; Safe because src row and dst row never overlap.
        FAR_BANK_SCREEN save_ptr
        ldx #0                  ; X = dst row; src row = X + 1
@row:   jsr _ed_scr_row
        inx                     ; X = src row
        lda scr_lo,x
        sta save_ptr
        lda scr_hi,x
        sta save_ptr+1
        ldy LAST_COL
@byte:  FAR_LDA save_ptr
        FAR_STA ed_scr
        dey
        bpl @byte
        cpx ED_LAST             ; just copied from the last row? → done
        bne @row

        ; Render the new bottom line (ED_LAST)
        ; Find position: advance from ed_top_ptr by ED_LAST lines
        jsr _ed_scr_top
        ldx #0
@skip:  cpx ED_LAST             ; skip ED_LAST lines
        bcs @got_pos
        jsr skip_one_line
        inx
        jmp @skip
@got_pos:
        jsr skip_gap_scr
        jsr check_buf_end
        bcc @render_bottom

        ; Past EOF — blank the last row
        ldx ED_LAST
        jsr blank_row
        jmp ed_status_pos

@render_bottom:
        ldx ED_LAST
        jsr ed_render_line
        jmp ed_status_pos
.endproc

; ── ed_scroll_down — scroll screen down, render new top line ──
.proc ed_scroll_down
        ; Retreat ed_top_ptr by one line
        jsr _ed_scr_top
        jsr prev_line_start
        lda ed_scr
        sta ed_top_ptr
        lda ed_scr+1
        sta ed_top_ptr+1
        ; --ed_top_line
        lda ed_top_line
        bne :+
        dec ed_top_line+1
:       dec ed_top_line

        ; Shift screen rows 0..ED_LAST-1 → 1..ED_LAST, a row at a time.
        ; Row-by-row descending copy so each src row is read before it
        ; gets overwritten by the row being shifted into it.
        FAR_BANK_SCREEN save_ptr
        ldx ED_LAST             ; X = dst row (ED_LAST); src row = X - 1
@row:   jsr _ed_scr_row
        dex                     ; X = src row
        lda scr_lo,x
        sta save_ptr
        lda scr_hi,x
        sta save_ptr+1
        ldy LAST_COL
@byte:  FAR_LDA save_ptr
        FAR_STA ed_scr
        dey
        bpl @byte
        cpx #0                  ; just copied from row 0? → done
        bne @row

        ; Render the new top line (row 0)
        jsr _ed_scr_top
        jsr skip_gap_scr
        jsr check_buf_end
        bcc @render_top

        ; Past EOF — blank row 0
        ldx #0
        jsr blank_row
        jmp ed_status_pos

@render_top:
        ldx #0
        jsr ed_render_line
        jmp ed_status_pos
.endproc

; ── Cursor helpers + key handler + mode switch ───────────────

; ── visual_col — recompute visual column from line start ──────
; Output: A = visual column
; Clobbers: X, Y
.proc visual_col
        ; Walk back from gap_lo to start of line.
        jsr find_line_start
        ; ed_scr = start of current line.
        ; Now scan forward to gap_lo, accumulating visual column.
        ldx #0                  ; vcol
@fwd:
        ; Check ed_scr == gap_lo
        lda ed_scr
        cmp gap_lo
        bne @fwd_read
        lda ed_scr+1
        cmp gap_lo+1
        beq @done               ; reached gap_lo → done
@fwd_read:
        ldy #0
        FAR_LDA ed_scr
        cmp #$A0                ; tab?
        beq @fwd_tab
        ; Non-tab: width = 1
        inx
        jmp @fwd_advance
@fwd_tab:
        stx @vc_save            ; save vcol (NOT ed_tmp — char_width clobbers it)
        jsr char_width          ; A = width for tab
        clc
        adc @vc_save
        tax
@fwd_advance:
        inc ed_scr
        bne @fwd
        inc ed_scr+1
        jmp @fwd
@done:
        txa
        rts

        .segment "BSS"      ; CODE stays read-only
@vc_save: .res 1
        .segment "CODE"
.endproc

; ── line_vwidth — visual width of a line ───────────────────────
; Input: ed_scr = pointer to start of line (buf_base, or just past
;        a CR, or any buffer position known to be at line start)
; Output: A = visual width (0..254 for normal lines; $FF sentinel
;         if the line somehow overflows 8-bit accumulation)
; Clobbers: A, X, Y, ed_scr, ed_tmp
;
; Walks forward from ed_scr, summing char_width for each byte
; until CR, EOF, or 8-bit overflow.  Transparent over the gap.
; Used via cursor_line_vwidth by the INS / TAB / printable cap
; checks (the renderer clips on its own column count).
.proc line_vwidth
        ldx #0                  ; X = accumulating vcol
@loop:
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @done
        ; Read byte
        ldy #0
        FAR_LDA ed_scr
        cmp #$0D
        beq @done               ; CR → end of line
        cmp #$A0
        beq @tab
        ; Non-tab: width = 1
        inx
        beq @overflow           ; X wrapped 255→0
        jmp @advance
@tab:
        stx @vw_save            ; save vcol (NOT ed_tmp — char_width clobbers it)
        jsr char_width          ; A = tab width at current col
        clc
        adc @vw_save            ; A = new vcol
        bcs @overflow
        tax                     ; X = new vcol
@advance:
        inc ed_scr
        bne @loop
        inc ed_scr+1
        jmp @loop
@overflow:
        ldx #$FF
@done:
        txa
        rts

        .segment "BSS"      ; CODE stays read-only
@vw_save: .res 1
        .segment "CODE"
.endproc

; ── find_line_start — walk gap_lo back to the line start ──────
; Sets ed_scr to the start of the cursor's line (just past the
; preceding $0D, or buf_base at the top of the buffer).  Does
; NOT move the gap.  Shared by visual_col and copy_leading_ws.
; Clobbers: A, Y, ed_tmp.  Preserves X.
.proc find_line_start
        jsr _ed_scr_glo
        FAR_BANK ed_tmp, BANK_SRC       ; ed_tmp walks the buffer here
@back:
        lda ed_scr+1
        cmp buf_base+1
        bcc @done
        bne @check_lo
        lda ed_scr
        cmp buf_base
        bcc @done
        beq @done
@check_lo:
        ; Look at byte before ed_scr
        lda ed_scr
        sec
        sbc #1
        sta ed_tmp
        lda ed_scr+1
        sbc #0
        sta ed_tmp+1
        ldy #0
        FAR_LDA ed_tmp
        cmp #$0D
        beq @done               ; CR found → ed_scr is line start
        lda ed_tmp
        sta ed_scr
        lda ed_tmp+1
        sta ed_scr+1
        jmp @back
@done:  rts
.endproc

; ── _ins_capped — gb_insert A, taken back when the cursor's line is
; then wider than LAST_COL: a byte typed before a tab moves the tab to
; the next stop, so the width is measured after the insert (editor.md
; § Long lines and the overflow indicator).
; Out: C=1 inserted; C=0 refused — the buffer full, or over the cap
; (the buffer and ed_dirty as before).
; Clobbers: A, X, Y, ed_tmp, ed_scr, and what gb_insert clobbers.
.proc _ins_capped
        ldx ed_dirty
        stx @dirty
        jsr gb_insert
        bcc @r                  ; the buffer full: C=0
        jsr cursor_line_vwidth
        cmp WIDTH
        bcs @over               ; wider than LAST_COL
        sec                     ; kept: C=1
@r:     rts
@over:  jsr gb_backspace        ; take it back
        lda @dirty
        sta ed_dirty
        clc
        rts
        .segment "BSS"
@dirty: .res 1
        .segment "CODE"
.endproc

; ── cursor_line_vwidth — visual width of the cursor's line ──────
; Walks back to the line start (without moving the gap), then
; calls line_vwidth from there.  Used by insert/tab cap checks.
; Output: A = visual width (0..254) or $FF on overflow
; Clobbers: A, X, Y, ed_scr, ed_tmp
.proc cursor_line_vwidth
        jsr find_line_start
        jmp line_vwidth
.endproc

; ── _strip_label_tab — strip leading $A0 if line is a label ────
; Scans the line for ';'.  If found (comment), skips the strip.
; Otherwise calls _strip_leading_tab.
; Clobbers: A, Y, ed_scr
.proc _strip_label_tab
        jsr find_line_start     ; ed_scr = line start
@scan:  lda ed_scr
        cmp gap_lo
        bne @peek
        lda ed_scr+1
        cmp gap_lo+1
        beq @ok                 ; reached cursor → no semicolon
@peek:  ldy #0
        FAR_LDA ed_scr
        cmp #';'
        beq @skip               ; comment → don't strip
        inc ed_scr
        bne @scan
        inc ed_scr+1
        jmp @scan
@ok:    jsr _strip_leading_tab
@skip:  rts
.endproc

; ── _strip_leading_tab — remove first $A0 from current line ────
; If the current line starts with $A0, delete it by shifting
; content left and shrinking gap_lo.  Adjusts ed_cur_col.
; Clobbers: A, Y, ed_scr
.proc _strip_leading_tab
        jsr find_line_start     ; ed_scr = start of current line
        ldy #0
        FAR_LDA ed_scr
        cmp #$A0
        bne @done               ; no leading tab → nothing to do
        ; Shift content left by 1, overwriting the $A0
        lda gap_lo
        bne :+
        dec gap_lo+1
:       dec gap_lo              ; expand gap by 1
        ; while ed_scr < gap_lo: [ed_scr] = [ed_scr+1]; ed_scr++
@shift:
        lda ed_scr
        cmp gap_lo
        bne @do_shift
        lda ed_scr+1
        cmp gap_lo+1
        beq @shifted
@do_shift:
        ldy #1
        FAR_LDA ed_scr
        dey
        FAR_STA ed_scr
        inc ed_scr
        bne @shift
        inc ed_scr+1
        jmp @shift
@shifted:
        ; Adjust visual column (lost TAB_WIDTH columns)
        lda ed_cur_col
        sec
        sbc #TAB_WIDTH
        bcs :+
        lda #0                  ; clamp to 0
:       sta ed_cur_col
@done:  rts
.endproc


; ── advance_to_vcol — move cursor right to target column ──────
; Input: A = target visual column
; Clobbers: A, X, Y
.proc advance_to_vcol
        sta @target
@loop:
        ; Check gap_hi < BUF_END
        lda gap_hi+1
        cmp #>BUF_END
        bcc @in_buf
        bne @done
        lda gap_hi
        cmp #<BUF_END
        bcs @done
@in_buf:
        ; Check *gap_hi != $0D
        ldy #0
        FAR_LDA gap_hi
        cmp #$0D
        beq @done

        ; w = char_width(*gap_hi, ed_cur_col)
        ldx ed_cur_col
        jsr char_width          ; A = width
        ; Check if ed_cur_col + w > target
        clc
        adc ed_cur_col
        cmp @target
        beq @move               ; equal → move (adc result == target means exact)
        bcs @done               ; would overshoot
@move:
        pha                     ; save new col
        jsr gb_cursor_right
        pla
        sta ed_cur_col
        jmp @loop
@done:  rts

        .segment "BSS"      ; CODE stays read-only
@target: .res 1
        .segment "CODE"
.endproc

; ── ed_cursor_up ──────────────────────────────────────────────
; Output: C=1 if cursor moved, C=0 if no-op (already at line 0).
.proc ed_cursor_up
        ; if ed_cur_line == 0 → return refused
        lda ed_cur_line
        ora ed_cur_line+1
        beq @noop

        lda ed_cur_col
        sta @target

        jsr gb_home
        lda #0
        sta ed_cur_col

        ; if gap_lo > buf_base → cursor_left (step over CR)
        lda gap_lo
        cmp buf_base
        bne @do_left
        lda gap_lo+1
        cmp buf_base+1
        beq @advance
@do_left:
        jsr gb_cursor_left
        ; --ed_cur_line
        lda ed_cur_line
        bne :+
        dec ed_cur_line+1
:       dec ed_cur_line

        jsr gb_home
        lda #0
        sta ed_cur_col

@advance:
        lda @target
        jsr advance_to_vcol
        sec                     ; moved
        rts
@noop:  clc                     ; refused
        rts

        .segment "BSS"      ; CODE stays read-only
@target: .res 1
        .segment "CODE"
.endproc

; ── ed_cursor_down ────────────────────────────────────────────
; Output: C=1 if cursor moved, C=0 if no-op (already on last line).
.proc ed_cursor_down
        ; if ed_cur_line + 1 >= ed_total_lines → return refused
        lda ed_cur_line
        clc
        adc #1
        sta ed_tmp
        lda ed_cur_line+1
        adc #0
        sta ed_tmp+1
        ; Compare ed_tmp >= ed_total_lines
        lda ed_tmp+1
        cmp ed_total_lines+1
        bcc @ok
        bne @noop               ; ed_tmp > total → refused
        lda ed_tmp
        cmp ed_total_lines
        bcs @noop               ; ed_tmp >= total → refused
@ok:
        lda ed_cur_col
        sta @target

        ; Advance past current line's CR
@skip:  ; while gap_hi < BUF_END && *gap_hi != $0D → cursor_right
        lda gap_hi+1
        cmp #>BUF_END
        bcc @in_buf
        bne @past_cr
        lda gap_hi
        cmp #<BUF_END
        bcs @past_cr
@in_buf:
        ldy #0
        FAR_LDA gap_hi
        cmp #$0D
        beq @found_cr
        jsr gb_cursor_right
        jmp @skip
@found_cr:
        ; Step over CR
        lda gap_hi+1
        cmp #>BUF_END
        bcc @step_cr
        bne @past_cr
        lda gap_hi
        cmp #<BUF_END
        bcs @past_cr
@step_cr:
        jsr gb_cursor_right
        inc ed_cur_line
        bne :+
        inc ed_cur_line+1
:       lda #0
        sta ed_cur_col
@past_cr:
        lda @target
        jsr advance_to_vcol
        sec                     ; moved
        rts
@noop:  clc                     ; refused
        rts

        .segment "BSS"      ; CODE stays read-only
@target: .res 1
        .segment "CODE"
.endproc

; ── ed_mark_edited — set dirty flag, update status ────────────
; Draws the dirty marker on every edit: gb_insert / gb_backspace set
; ed_dirty before this runs, and not every edit path re-renders the
; status bar (ed_scroll_up does not).
.proc ed_mark_edited
        lda #1
        sta ed_dirty
        ldx ED_STATUS_ROW
        jsr _ed_scr_row
        lda #($2A | $80)        ; '*' reversed, col 0
        ldy #0
        FAR_STA ed_scr
.ifdef PLATFORM_C64
        jsr ed_status_free      ; m65: the free field is fixed
.endif
        jmp ed_status_pos
.endproc

; ── render_current_row — render cursor row, mark edited ──────
; Common tail used by the @printable and @tab insert paths in
; ed_handle_key.  Computes scr_row = cur_line - top_line and
; calls ed_render_rows with from=row, to=row+1, then falls
; through to ed_mark_edited.
; Clobbers: A, X, Y.
.proc render_current_row
        jsr _ed_cur_row
        tax                     ; from_row
        inx                     ; to = from + 1
        txa
        tay
        dex                     ; restore from
        jsr ed_render_rows
        jmp ed_mark_edited
.endproc

; ── The clipboard and the line moves (editor.md § Clipboard and line
; moves) ─────────────────────────────────────────────────────────────

.segment "BSS"
cb_line:   .res 2               ; _to_line's target / the line count before a paste
cb_sl:     .res 2               ; copy: the cursor's line to return to
cb_col:    .res 1               ; a saved ed_cur_col / _view_fix: rows to walk back
cb_s:      .res 2               ; a start in the text
cb_eof:    .res 1               ; the selection ends the text (no CR after it)
cb_t:      .res 2               ; _sel_row: the row's line; _select: the mark's
.segment "CODE"

; ── _sel_row — the row just drawn (rl_row; ed_tmp its screen start)
; inverted when its line, ed_top_line + rl_row, is selected (sel_lo ..
; sel_hi while a mark is set).  Clobbers A, Y.
.proc _sel_row
        lda ed_mark1
        ora ed_mark1+1
        beq @r
        lda ed_top_line
        clc
        adc rl_row
        sta cb_t
        lda ed_top_line+1
        adc #0
        sta cb_t+1
        lda cb_t                ; line < sel_lo → not selected
        cmp sel_lo
        lda cb_t+1
        sbc sel_lo+1
        bcc @r
        lda sel_hi              ; sel_hi < line → not selected
        cmp cb_t
        lda sel_hi+1
        sbc cb_t+1
        bcc @r
        ldy LAST_COL
@lp:    FAR_LDA ed_tmp
        ora #$80
        FAR_STA ed_tmp
        dey
        bpl @lp
@r:     rts
.endproc

; ── _select — sel_lo / sel_hi: the mark's line to the cursor's, either
; order, or the cursor's line without a mark.  Clobbers A.
.proc _select
        ldx #1                  ; sel_lo = sel_hi = the cursor's line
@c:     lda ed_cur_line,x
        sta sel_lo,x
        sta sel_hi,x
        dex
        bpl @c
        lda ed_mark1
        ora ed_mark1+1
        beq @r
        lda ed_mark1            ; cb_t = the mark's line
        sec
        sbc #1
        sta cb_t
        lda ed_mark1+1
        sbc #0
        sta cb_t+1
        lda cb_t                ; the mark ≥ the cursor's: the last, else the first
        cmp ed_cur_line
        lda cb_t+1
        sbc ed_cur_line+1
        ldx #sel_hi - sel_lo
        bcs :+
        ldx #0
:       lda cb_t
        sta sel_lo,x
        lda cb_t+1
        sta sel_lo+1,x
@r:     rts
.endproc

; ── _mark_policy — A = the key: unless it is one of ed_keys' first 8
; (the cursor keys, HOME, and mark, cut, copy, which use the mark), the
; mark is cleared.  Clobbers X.
.proc _mark_policy
        ldx #7
@kk:    cmp ed_keys,x
        beq @r
        dex
        bpl @kk
        bmi _mark_clear         ; always
@r:     rts
.endproc
; ── _mark_clear — no mark (the redraw at the key's end shows it).
_mark_clear:
        ldx #0
        stx ed_mark1
        stx ed_mark1+1
        rts

; ── _sel_redraw — the selection's bounds; the view redrawn when the key
; changed the mark, or moved the cursor to another line while a mark is
; set (the inverted selection follows).  Clobbers A, X, Y, ed_scr, ed_tmp.
.proc _sel_redraw
        jsr _select
        ldx #3                  ; the line or the mark changed?
@cmp:   lda ed_cur_line,x
        cmp sel_l0,x
        bne @diff
        dex
        bpl @cmp
@r:     rts
@diff:  lda ed_mark1            ; a mark now or before: redraw
        ora ed_mark1+1
        ora sel_m0
        ora sel_m0+1
        beq @r
        jmp ed_render
.endproc

; ── _to_line — the cursor to col 0 of line A/X (cb_line), or of the
; last line when there are fewer.  Clobbers A, X, Y, ed_tmp, ed_scr.
.proc _to_line
        sta cb_line
        stx cb_line+1
        jsr gb_home
        lda #0
        sta ed_cur_col
@up:    lda cb_line             ; target < cur → up
        cmp ed_cur_line
        lda cb_line+1
        sbc ed_cur_line+1
        bcs @down
        jsr ed_cursor_up
        jmp @up
@down:  lda ed_cur_line         ; cur < target → down, while there is one
        cmp cb_line
        lda ed_cur_line+1
        sbc cb_line+1
        bcs @r
        jsr ed_cursor_down
        bcs @down
@r:     rts
.endproc

; ── _line_end — the cursor right to its line's end (a CR or the text's
; end).  Clobbers A, Y.
.proc _line_end
@lp:    ldy #0
        lda gap_hi+1
        cmp #>BUF_END
        bne :+
        lda gap_hi
        cmp #<BUF_END
        beq @r                  ; the text's end
:       FAR_LDA gap_hi
        cmp #$0D
        beq @r
        jsr gb_cursor_right
        jmp @lp
@r:     rts
.endproc

; ── _here / _goto — the cursor's place kept (cb_sl, cb_col) / gone back
; to (cb_sl's line, cb_col's column).  _goto clobbers A, X, Y, ed_tmp,
; ed_scr.
_here:  lda ed_cur_line
        sta cb_sl
        lda ed_cur_line+1
        sta cb_sl+1
        lda ed_cur_col
        sta cb_col
        rts
_goto:  lda cb_sl
        ldx cb_sl+1
        jsr _to_line
        lda cb_col
        jmp advance_to_vcol

; ── _view_fix — the view after a move of lines, moved as little as it
; can (editor.md § Clipboard and line moves): kept when the cursor's
; line is still in it, else scrolled until that line is on the top row
; (above) or the bottom row (below); ed_top_ptr walked back from the
; cursor's line.  The full redraw comes
; at the key's end (sel_m0 made to differ).  C=1.
; Clobbers A, X, Y, ed_tmp, ed_scr.
.proc _view_fix
        lda #$FF                ; the key's end redraws (_sel_redraw)
        sta sel_m0+1
        jsr _ed_cur_row         ; A = cur - top (low), C from it
        tax
        lda ed_cur_line+1
        sbc ed_top_line+1
        bcc @above              ; cur < top
        bne @below              ; 256 or more rows below
        cpx ED_ROWS
        bcc @walk               ; in view: the top kept
@below: ldx ED_ROWS             ; below: onto the bottom row
        dex
        bne @move               ; (always: ED_ROWS > 1)
@above: ldx #0                  ; above: onto the top row
@move:  stx cb_col              ; top = cur - its row
        lda ed_cur_line
        sec
        sbc cb_col
        sta ed_top_line
        lda ed_cur_line+1
        sbc #0
        sta ed_top_line+1
@walk:  stx cb_col              ; rows to walk back
        jsr find_line_start     ; ed_scr = the cursor's line's start
@back:  lda cb_col
        beq @set
        jsr prev_line_start
        dec cb_col
        jmp @back
@set:   lda ed_scr
        sta ed_top_ptr
        lda ed_scr+1
        sta ed_top_ptr+1
        sec                     ; done (ed_clip_key's C)
        rts
.endproc

; ── _sel_bytes — the selected lines as the bytes before the cursor: the
; cursor to the start of the line after them (or to the text's end:
; cb_eof = 1), cb_s their start, ed_tmp their count; the mark cleared.
.proc _sel_bytes
        jsr _select
        jsr _mark_clear
        lda sel_lo
        ldx sel_lo+1
        jsr _to_line
        lda gap_lo
        sta cb_s
        lda gap_lo+1
        sta cb_s+1
        lda sel_hi              ; the line after the last
        ldx sel_hi+1
        clc
        adc #1
        bcc :+
        inx
:       jsr _to_line
        lda #0
        sta cb_eof
        lda ed_cur_line         ; not there: the last line, to its end
        cmp cb_line
        bne :+
        lda ed_cur_line+1
        cmp cb_line+1
        beq @n
:       jsr _line_end
        inc cb_eof
@n:     lda gap_lo              ; ed_tmp = gap_lo - cb_s
        sec
        sbc cb_s
        sta ed_tmp
        lda gap_lo+1
        sbc cb_s+1
        sta ed_tmp+1
        rts
.endproc

.ifdef PLATFORM_M65
.segment "KCODE"                ; cold code (in the open on m65)
.endif
; ── ed_clip_key — X = the key's index in clip_keys.  C=1 done, C=0
; refused (ed_handle_key blips).
.proc ed_clip_key
        lda @hi,x
        pha
        lda @lo,x
        pha
        rts
@lo:    .lobytes @mark-1, @cut-1, @copy-1, @paste-1, @up-1, @down-1
@hi:    .hibytes @mark-1, @cut-1, @copy-1, @paste-1, @up-1, @down-1

        ; ── C=+B: the mark on the cursor's line, or cleared there
@mark:  lda ed_cur_line
        clc
        adc #1
        tax
        lda ed_cur_line+1
        adc #0
        cpx ed_mark1
        bne @set
        cmp ed_mark1+1
        bne @set
        lda #0                  ; on the marked line: clear
        tax
@set:   stx ed_mark1
        sta ed_mark1+1
        sec
        rts

        ; ── C=+X: cut — copied, then deleted
@cut:   jsr _sel_bytes
        lsr cb_eof              ; C = at the end: add the CR
        php
        jsr gb_clip_copy
        bcs :+
        plp                     ; no room: refused
        clc
        rts
:       jsr gb_delete           ; ed_tmp still the count
        lda sel_lo
        sta ed_cur_line
        lda sel_lo+1
        sta ed_cur_line+1
        plp
        bcc @col0
        lda sel_lo              ; at the end: the CR before them goes
        ora sel_lo+1
        beq @col0
        jsr gb_backspace
        jsr @prev
        jsr gb_home
@col0:  lda #0
        sta ed_cur_col
        jmp _view_fix

        ; ── C=+C: copy; the cursor returns
@copy:  jsr _here               ; cb_sl / cb_col = the cursor's place
        jsr _sel_bytes
        lsr cb_eof
        jsr gb_clip_copy
        php
        jsr _goto               ; back there
        jsr _view_fix           ; the gap went there and back
        plp
        rts

        ; ── C=+V: paste above the cursor's line
@paste: jsr _here
        jsr gb_home
        lda ed_total_lines
        sta cb_line
        lda ed_total_lines+1
        sta cb_line+1
        jsr gb_clip_put
        bcc @undo
        lda ed_cur_line         ; its line moved down by the pasted lines
        clc
        adc ed_total_lines
        tax
        lda ed_cur_line+1
        adc ed_total_lines+1
        tay
        txa
        sec
        sbc cb_line
        sta ed_cur_line
        tya
        sbc cb_line+1
        sta ed_cur_line+1
        jmp @col0
@undo:  jsr _goto               ; refused: the cursor back
@no:    clc
        rts

        ; ── C=+K / C=+J: swap with the line above / below (the CRs stay);
        ; the cursor then goes to its line's new place, its column kept
@up:    lda ed_cur_line
        ora ed_cur_line+1
        beq @no                 ; line 1
        jsr _here
        jsr @dec_sl             ; its line's new place: one up
        jmp @swap
@down:  lda ed_cur_line         ; the last line?
        clc
        adc #1
        tax
        lda ed_cur_line+1
        adc #0
        cpx ed_total_lines
        sbc ed_total_lines+1
        bcs @no
        jsr _here
        inc cb_sl               ; one down, and the cursor onto that line
        bne :+
        inc cb_sl+1
:       jsr _line_end
        jsr gb_cursor_right
        inc ed_cur_line
        bne @swap
        inc ed_cur_line+1
@swap:  jsr _line_end           ; the lower line L's end; ed_cur_line is L's
        jsr find_line_start     ; cb_t = L's start
        lda ed_scr
        sta cb_t
        lda ed_scr+1
        sta cb_t+1
        jsr prev_line_start     ; cb_s = U's start (the line above L)
        lda ed_scr
        sta cb_s
        lda ed_scr+1
        sta cb_s+1
        jsr @from_s             ; U reversed (up to its CR),
        lda cb_t
        ldx cb_t+1
        sec
        sbc #1
        bcs :+
        dex
:       jsr gb_rev
        lda cb_t                ; L reversed,
        sta save_ptr
        lda cb_t+1
        sta save_ptr+1
        jsr @to_gap
        jsr @from_s             ; then U CR L reversed: L CR U
        jsr @to_gap
        lda #1                  ; an edit (gb_rev leaves ed_dirty alone)
        sta ed_dirty
        jsr _goto
        jmp _view_fix

@to_gap:                        ; gb_rev up to the cursor
        lda gap_lo
        ldx gap_lo+1
        jmp gb_rev
@from_s:                        ; save_ptr = cb_s
        lda cb_s
        sta save_ptr
        lda cb_s+1
        sta save_ptr+1
        rts
@dec_sl:
        lda cb_sl
        bne :+
        dec cb_sl+1
:       dec cb_sl
        rts
@prev:  lda ed_cur_line         ; ed_cur_line - 1
        bne :+
        dec ed_cur_line+1
:       dec ed_cur_line
        rts
.endproc
.segment "CODE"

; ── ed_handle_key — main keystroke dispatcher ─────────────────
; Input: A = PETSCII key code
.proc ed_handle_key
        ; Save key
        sta @key
        ldx #3                  ; the cursor's line and the mark before the
@sv:    lda ed_cur_line,x       ;   key (_sel_redraw)
        sta sel_l0,x
        dex
        bpl @sv
        lda @key
        jsr _mark_policy        ; other keys than the cursor keys clear the mark
                                ;   (A kept)

        ; ── CH_CURS_LEFT ──────────────────────────
        cmp #CH_CURS_LEFT
        bne @not_left
        ; if ed_cur_col > 0 && gap_lo > buf_base
        lda ed_cur_col
        jeq @reject             ; col 0 → left wall
        lda gap_lo
        cmp buf_base
        bne @do_left
        lda gap_lo+1
        cmp buf_base+1
        jeq @reject             ; at buf_base → start of buffer
@do_left:
        jsr gb_cursor_left
        jsr visual_col
        sta ed_cur_col
        jmp @status_repos

        ; ── CH_CURS_RIGHT ─────────────────────────
@not_left:
        cmp #CH_CURS_RIGHT
        bne @not_right
        ; if gap_hi < BUF_END && *gap_hi != $0D
        lda gap_hi+1
        cmp #>BUF_END
        bcc @right_check
        jne @reject             ; past EOF
        lda gap_hi
        cmp #<BUF_END
        jcs @reject             ; past EOF
@right_check:
        ldy #0
        FAR_LDA gap_hi
        cmp #$0D
        jeq @reject             ; end of line
        ; Refuse a step that ends past the last column: the column after
        ; it is ed_cur_col + the byte's width there (a tab crosses up to
        ; TAB_WIDTH columns at once: editor.md § Long lines)
        ldx ed_cur_col
        jsr char_width
        clc
        adc ed_cur_col
        cmp WIDTH               ; > LAST_COL → refuse
        jcs @reject
        jsr gb_cursor_right
        jsr visual_col
        sta ed_cur_col
        jmp @status_repos

        ; ── CH_CURS_UP ────────────────────────────
@not_right:
        cmp #CH_CURS_UP
        bne @not_up
        jsr ed_cursor_up
        jcc @reject             ; no-op → top of buffer
        ; if ed_cur_line < ed_top_line → scroll down
        lda ed_cur_line+1
        cmp ed_top_line+1
        bcc @do_scroll_down
        bne @up_no_scroll
        lda ed_cur_line
        cmp ed_top_line
        bcc @do_scroll_down
@up_no_scroll:
        jmp @status_repos
@do_scroll_down:
        jsr ed_scroll_down
        jmp @repos

        ; ── CH_CURS_DOWN ──────────────────────────
@not_up:
        cmp #CH_CURS_DOWN
        bne @not_down
        jsr ed_cursor_down
        jcc @reject             ; no-op → bottom of buffer
        ; if ed_cur_line >= ed_top_line + ED_ROWS → scroll up
        jsr _ed_cur_row
        sta ed_tmp
        lda ed_cur_line+1
        sbc ed_top_line+1
        bne @do_scroll_up       ; hi byte nonzero → definitely >= ED_ROWS
        lda ed_tmp
        cmp ED_ROWS
        bcs @do_scroll_up
        jmp @status_repos
@do_scroll_up:
        jsr ed_scroll_up
        jmp @repos

        ; ── CH_HOME ───────────────────────────────
@not_down:
        cmp #CH_HOME
        bne @not_home
        jsr gb_home
        lda #0
        sta ed_cur_col
        jmp @status_repos

        ; ── CH_DEL ────────────────────────────────
@not_home:
        cmp #CH_DEL
        jne @not_del
@is_del:
        lda ed_cur_col
        bne @del_mid            ; col > 0 → simple backspace
        ; col == 0 → check if we can join with previous line
        lda ed_cur_line
        ora ed_cur_line+1
        bne @del_join
        jmp @reject             ; line 0, col 0 → left wall, blip + ignore
                                ; (do NOT mark dirty: nothing changed)
@del_mid:
        jsr gb_backspace
        jsr visual_col
        sta ed_cur_col
        ; Re-render from current row to bottom
        jsr _ed_cur_row
        tax                     ; from_row
        ldy ED_ROWS
        jsr ed_render_rows
        jsr ed_mark_edited
        jmp @repos

@del_join:
        ; Delete at col 0, line > 0 → join with previous line.
        jsr gb_backspace
        ; --ed_cur_line
        lda ed_cur_line
        bne :+
        dec ed_cur_line+1
:       dec ed_cur_line
        jsr visual_col
        sta ed_cur_col
        sta @join_col

        ; Restore the cursor to the join point.
        jsr gb_home
        lda #0
        sta ed_cur_col
        lda @join_col           ; at most the last column (a wider
        cmp WIDTH               ;   previous line: editor.md § Long lines)
        bcc :+
        lda LAST_COL
:       jsr advance_to_vcol
        ; Adjust the viewport if the cursor moved above it.  For
        ; a single DEL at col 0 this can only happen when the
        ; user was on the topmost visible line (ed_cur_line was
        ; == ed_top_line before the DEL); after dec ed_cur_line
        ; it's exactly one line above the top.  We must pull
        ; ed_top_line down AND recompute ed_top_ptr — the old
        ; cached pointer is either stale (inside the gap) or
        ; points into the middle of what is now the joined
        ; line.  find_line_start walks back from gap_lo to the
        ; start of the cursor's line without moving the gap.
        lda ed_cur_line+1
        cmp ed_top_line+1
        bcc @adj_top
        bne @del_render
        lda ed_cur_line
        cmp ed_top_line
        bcs @del_render
@adj_top:
        jsr find_line_start     ; ed_scr = start of cursor's line
        lda ed_scr
        sta ed_top_ptr
        lda ed_scr+1
        sta ed_top_ptr+1
        lda ed_cur_line
        sta ed_top_line
        lda ed_cur_line+1
        sta ed_top_line+1
@del_render:
        jsr _ed_cur_row
        tax                     ; from_row
        ldy ED_ROWS
        jsr ed_render_rows
@del_edited:
        jmp @edited_repos

        ; ── CH_ENTER ──────────────────────────────
@not_del:
        cmp #CH_ENTER
        jne @not_enter
@is_enter:
        ; Smart indent:
        ;   1. If at BOL (col 0): insert CR, done.
        ;   2. Strip all $A0 tabs left and right of cursor.
        ;   3. If byte left of cursor is ':', strip leading $A0 from line.
        ;   4. Insert CR + $A0 tab.

        ; Step 1: BOL early-out
        lda ed_cur_col
        jeq @bol_cr

        ; Step 2: strip $A0 tabs left of cursor
@strip_left:
        ; Peek gap_lo - 1
        lda gap_lo
        cmp buf_base
        bne @peek_l
        lda gap_lo+1
        cmp buf_base+1
        beq @strip_right        ; at buf_base → nothing left
@peek_l:
        lda gap_lo
        bne :+
        dec gap_lo+1
:       dec gap_lo
        ldy #0
        FAR_LDA gap_lo
        cmp #$A0
        beq @strip_left         ; $A0 → absorbed into gap, loop
        ; Not $A0 — restore gap_lo (undo the dec)
        inc gap_lo
        bne @strip_right
        inc gap_lo+1

        ; Step 2b: strip $A0 tabs right of cursor
@strip_right:
        lda gap_hi+1
        cmp #>BUF_END
        bcc @peek_r
        bne @step3              ; past EOF
        lda gap_hi
        cmp #<BUF_END
        bcs @step3              ; at EOF
@peek_r:
        ldy #0
        FAR_LDA gap_hi
        cmp #$A0
        bne @step3
        ; $A0 → advance gap_hi (absorb into gap)
        inc gap_hi
        bne @strip_right
        inc gap_hi+1
        jmp @strip_right

        ; Step 3: if byte left of cursor is ':', strip leading $A0
@step3:
        ; Peek byte left of cursor (gap_lo - 1)
        lda gap_lo
        cmp buf_base
        bne @peek_colon
        lda gap_lo+1
        cmp buf_base+1
        beq @step4              ; at buf_base → no byte to check
@peek_colon:
        lda gap_lo
        bne :+
        dec gap_lo+1
:       dec gap_lo
        ldy #0
        FAR_LDA gap_lo
        ; restore gap_lo
        inc gap_lo
        bne :+
        inc gap_lo+1
:       cmp #':'
        bne @step4
        ; Colon found — strip leading $A0 unless line has ';'
        jsr _strip_label_tab

        ; Step 4: insert CR + $A0
@step4:
        lda #$0D
        jsr gb_insert
        jcc @reject             ; full buffer → refuse newline (no col/line drift)
        inc ed_cur_line
        bne :+
        inc ed_cur_line+1
:       lda #$A0
        jsr _ins_capped         ; refused on the very last byte of
                                ; capacity, or when the rest of the line
                                ; would pass the cap: the CR stays, the
        lda #TAB_WIDTH          ; line opens without its indent (col 0)
        bcs :+
        lda #0
:       sta ed_cur_col
        jmp @enter_render

        ; Step 1 (BOL path): just insert CR
@bol_cr:
        lda #$0D
        jsr gb_insert
        jcc @reject             ; full → refuse
        inc ed_cur_line
        bne :+
        inc ed_cur_line+1
:       lda #0
        sta ed_cur_col
@enter_render:

        ; Scroll or re-render
        ; if ed_cur_line >= ed_top_line + ED_ROWS → scroll up
        jsr _ed_cur_row
        sta ed_tmp
        lda ed_cur_line+1
        sbc ed_top_line+1
        bne @enter_scroll       ; hi nonzero → scroll
        lda ed_tmp
        cmp ED_ROWS
        bcs @enter_scroll
        ; No scroll — re-render from previous row
        tax                     ; scr_row = ed_cur_line - ed_top_line
        beq @enter_full         ; scr_row == 0 → full render
        dex                     ; from scr_row - 1
        ldy ED_ROWS
        jsr ed_render_rows
        jmp @edited_repos
@enter_full:
        jsr ed_render
        jmp @edited_repos
@enter_scroll:
        jsr ed_scroll_up
        jmp @edited_repos

        ; ── CH_INS — insert space at cursor, cursor stays ──
@not_enter:
        cmp #CH_INS
        bne @not_ins
        lda #$20
        jsr _ins_capped
        jcc @reject             ; over the cap or the buffer full → refuse
        jsr gb_cursor_left      ; cursor back onto the space
        jsr render_current_row
        jmp @edited_repos
@not_ins:

        ; ── TAB ($A0) — always enabled under TAB_WIDTH ──
        cmp #$A0
        bne @not_tab
        ; Compute the new ed_cur_col: ed_cur_col + char_width(TAB, ed_cur_col).
        lda #$A0
        ldx ed_cur_col
        jsr char_width
        clc
        adc ed_cur_col
        sta @new_col
        lda #$A0
        jsr _ins_capped
        jcc @reject             ; over the cap or the buffer full → refuse TAB
        lda @new_col
        sta ed_cur_col
        jsr render_current_row
        jmp @repos

        ; ── Default: printable character ──────────
@not_tab:
        lda @key
        ldx #5                  ; a clipboard key?
@ck:    cmp clip_keys,x
        beq @clip
        dex
        bpl @ck
        ; Check printable: $20-$7E or $C1-$DA
        cmp #$20
        bcc @repos_jmp          ; control char → ignore
        cmp #$7F
        bcc @printable          ; $20-$7E → printable
        cmp #$C1
        bcc @repos_jmp          ; $7F-$C0 → ignore
        cmp #$DB
        bcs @repos_jmp          ; $DB+ → ignore
@printable:
        lda @key
        jsr _ins_capped
        jcc @reject             ; over the cap or the buffer full → refuse char
        inc ed_cur_col
        ; Smart colon: typing ':' at EOL strips leading $A0
        lda @key
        cmp #':'
        bne @print_done
        ; Only at EOL (gap_hi is EOF or $0D)
        lda gap_hi+1
        cmp #>BUF_END
        bcc @peek_eol
        bne @do_smart_colon
        lda gap_hi
        cmp #<BUF_END
        bcs @do_smart_colon
@peek_eol:
        ldy #0
        FAR_LDA gap_hi
        cmp #$0D
        bne @print_done
@do_smart_colon:
        jsr _strip_label_tab
@print_done:       jsr render_current_row
        jmp @repos              ; skip over @reject — no blip on success

@status_repos:
        jsr ed_status_pos
        jmp @repos

@edited_repos:
        jsr ed_mark_edited
        jmp @repos

@clip:  jsr ed_clip_key           ; X = the key's index
        bcs @repos
@reject:
        ; Audible feedback for refused input (left-wall
        ; backspace, etc.).  Falls through to @repos so the cursor
        ; still gets re-synced after the rejection.
        jsr io_blip
@repos_jmp:
        ; Trampoline for branches that can't reach @repos directly.
        ; Falling through to @repos is equivalent to `jmp @repos`
        ; and saves 3 B.  Branches keep targeting @repos_jmp — the
        ; label is an alias for the first byte of @repos.
@repos:
        jsr _sel_redraw         ; the inverted selection follows
        jmp ed_sync_cursor

        .segment "BSS"      ; CODE stays read-only
@key:          .res 1
@new_col:      .res 1
@join_col: .res 1
        .segment "CODE"
.endproc

; ── Mode switching ───────────────────────────────────────────

.ifdef PLATFORM_C64                     ; m65: screen_save / screen_restore
; ── copy_1000 — copy 1000 bytes from (save_ptr) to (ed_scr) ──
; Ascending copy: 3 pages + 232 bytes
.proc copy_1000
        ldx #3
        ldy #0
@page:  FAR_LDA save_ptr
        FAR_STA ed_scr
        iny
        bne @page
        inc save_ptr+1
        inc ed_scr+1
        dex
        bne @page
        ldx #232
@rem:   FAR_LDA save_ptr
        FAR_STA ed_scr
        iny
        dex
        bne @rem
        rts
.endproc
.endif

; ── enter_editor — switch from REPL to editor ─────────────────
.proc enter_editor
        ; Save REPL cursor position
        lda IO_CX
        sta repl_cur_x
        lda IO_CY
        sta repl_cur_y

.ifdef PLATFORM_C64
        ; Save REPL screen RAM to banked RAM at REPL_SCREEN.
        ; Pure writer to the under-KERNAL region — stores pass through
        ; to RAM regardless of $01 bit 1, so no banking is required.
        ; Source SCREEN ($0400) is in main RAM and is also unbanked.
        lda #<SCREEN
        sta save_ptr
        lda #>SCREEN
        sta save_ptr+1
        lda #<REPL_SCREEN
        sta ed_scr
        lda #>REPL_SCREEN
        sta ed_scr+1
        jsr copy_1000
.else
        jsr screen_save         ; the mode's width x height to REPL_SCREEN
.endif

        ; Init gap buffer if needed
        jsr ed_ensure_init

        ; Smart indent: if buffer is truly empty, seed first line
        ; with a tab.  Truly empty needs BOTH halves of the gap-buffer
        ; envelope at their init positions: gap_lo == buf_base AND
        ; gap_hi == BUF_END.  Checking only gap_lo is wrong — after
        ; ed_load_source the cursor is rewound to the start, so
        ; gap_lo == buf_base holds even though loaded content fills
        ; [gap_hi, BUF_END).  See doc/modules/editor.md § Mode switching,
        ; enter_editor step 4.
        lda gap_lo
        cmp buf_base
        bne @has_content
        lda gap_lo+1
        cmp buf_base+1
        bne @has_content
        lda gap_hi
        cmp #<BUF_END
        bne @has_content
        lda gap_hi+1
        cmp #>BUF_END
        bne @has_content
        lda #$A0
        jsr gb_insert
        lda #TAB_WIDTH
        sta ed_cur_col
        lda #0
        sta ed_dirty            ; seed is not a user edit
@has_content:

.ifdef PLATFORM_M65
        ; The mode may have changed since the last visit: the cursor back
        ; on the screen — past the last column to its line's start, below
        ; the last row with its line as the top (editor.md, On m65).
        lda LAST_COL
        cmp ed_cur_col
        bcs :+                  ; col ≤ the last
        jsr gb_home
        lda #0
        sta ed_cur_col
:       jsr _ed_cur_row
        tax                     ; the row (low byte)
        lda ed_cur_line+1
        sbc ed_top_line+1
        bne @top
        cpx ED_ROWS
        bcc @in_view
@top:   jsr find_line_start     ; ed_scr = the cursor line's start
        lda ed_scr
        sta ed_top_ptr
        lda ed_scr+1
        sta ed_top_ptr+1
        lda ed_cur_line
        sta ed_top_line
        lda ed_cur_line+1
        sta ed_top_line+1
@in_view:
.endif

.ifdef PLATFORM_C64
        ; Clear editor area (rows 0-21) with spaces
        lda #<SCREEN
        sta ed_scr
        lda #>SCREEN
        sta ed_scr+1
        ; 22 * 40 = 880 bytes
        ldx #3                  ; 3 pages
        lda #$20
        ldy #0
@clr_pg:
        FAR_STA ed_scr
        iny
        bne @clr_pg
        inc ed_scr+1
        dex
        bne @clr_pg
        ; 880 - 768 = 112 remaining
        ldx #112
@clr_rem:
        FAR_STA ed_scr
        iny
        dex
        bne @clr_rem

        ; Copy 2 REPL lines above prompt to rows 23-24
        ; prompt_row = repl_cur_y
        ; src_row = max(0, prompt_row - 2)
        lda repl_cur_y
        sec
        sbc #2
        bcs @have_src_row
        lda #0                  ; clamp to 0
@have_src_row:
        ; A = src_row in REPL screen
        ; Compute offset: src_row * 40
        ; Use scr_lo/scr_hi tables but for REPL_SCREEN base
        tax                     ; X = src_row
        lda scr_lo,x
        sec
        sbc #<SCREEN
        sta save_ptr            ; low offset from SCREEN base
        lda scr_hi,x
        sbc #>SCREEN
        sta save_ptr+1          ; high offset
        ; Add REPL_SCREEN base
        lda save_ptr
        clc
        adc #<REPL_SCREEN
        sta save_ptr
        lda save_ptr+1
        adc #>REPL_SCREEN
        sta save_ptr+1

        ; Dest: SCREEN + 23*40 = SCREEN + 920
        lda #<(SCREEN + 920)
        sta ed_scr
        lda #>(SCREEN + 920)
        sta ed_scr+1

        ; Copy 80 bytes (2 rows)
        jsr kernal_bank_out
        ldy #79
@ctx:   FAR_LDA save_ptr
        FAR_STA ed_scr
        dey
        bpl @ctx
        jsr kernal_bank_in
.else
        ; ed_render draws every source row and the bar; the context rows
        ; (height − 2, − 1) are the REPL rows max(0, cy − 2) and the next,
        ; from the saved screen
        lda repl_cur_y
        sec
        sbc #2
        bcs :+
        lda #0
:       tax
        lda scr_lo,x            ; the row's offset in the save
        sec
        sbc scr_lo
        sta save_ptr
        lda scr_hi,x
        sbc scr_hi
        sta save_ptr+1
        lda save_ptr
        clc
        adc #<REPL_SCREEN
        sta save_ptr
        lda save_ptr+1
        adc #>REPL_SCREEN
        sta save_ptr+1
        FAR_BANK save_ptr, BANK_CSE
        ldx LAST_ROW
        dex
        jsr _ed_scr_row         ; ed_scr = row height − 2
        lda scr_width
        asl
        sta ed_tmp              ; two rows: the count
        ldy #0
@ctx:   FAR_LDA save_ptr
        FAR_STA ed_scr
        iny
        cpy ed_tmp
        bne @ctx
.endif

        ; Full render
        jsr ed_render

        ; Restore editor cursor position
        jsr ed_sync_cursor

        lda #ST_EDIT
        sta state
        rts
.endproc

; ── leave_editor — switch from editor to REPL ─────────────────
.proc leave_editor
.ifdef PLATFORM_C64
        ; Restore REPL screen from banked RAM
        jsr kernal_bank_out
        lda #<REPL_SCREEN
        sta save_ptr
        lda #>REPL_SCREEN
        sta save_ptr+1
        lda #<SCREEN
        sta ed_scr
        lda #>SCREEN
        sta ed_scr+1
        jsr copy_1000
        jsr kernal_bank_in
.else
        jsr screen_restore      ; REPL_SCREEN to the mode's screen
.endif

        ; Restore REPL cursor position
        lda repl_cur_x
        sta IO_CX
        lda repl_cur_y
        sta IO_CY
        jsr io_sync

        lda #ST_REPL
        sta state
        rts
.endproc

; ── File I/O ─────────────────────────────────────────────────

; ── save_read_fn — callback for disk_save_seq ─────────────────
; Returns: A = byte, X = 0 (data) OR A = $FF, X = $FF (EOF)
.proc save_read_fn
        lda save_phase
        bne @post_gap
        ; Pre-gap: save_ptr < gap_lo?
        lda save_ptr+1
        cmp gap_lo+1
        bcc @read_byte
        bne @switch
        lda save_ptr
        cmp gap_lo
        bcc @read_byte
@switch:
        lda #1
        sta save_phase
        lda gap_hi
        sta save_ptr
        lda gap_hi+1
        sta save_ptr+1
@post_gap:
        ; Post-gap: save_ptr < BUF_END?
        lda save_ptr+1
        cmp #>BUF_END
        bcc @read_byte
        lda #$FF
        tax
        rts
@read_byte:
        ldy #0
        FAR_LDA save_ptr        ; byte in A; survives the inc-pair below (no A-touch)
        inc save_ptr
        bne :+
        inc save_ptr+1
:       ldx #0
        rts
.endproc

; ── ed_save_source — save source as SEQ file ──────────────────
; Input: A/X = name pointer
; Returns: A = 0 on success, nonzero on error; X = 0, Z set from A
.proc ed_save_source
        ; Store name for disk_save_seq
        sta disk_ptr
        stx disk_ptr+1

        ; Ensure init
        jsr ed_ensure_init

        ; Setup save state
        lda buf_base
        sta save_ptr
        lda buf_base+1
        sta save_ptr+1
        FAR_BANK save_ptr, BANK_SRC
        lda #0
        sta save_phase

        ; Call disk_save_seq(name, save_read_fn)
        ; name in disk_ptr (stored above), read_fn in A/X
        lda #<save_read_fn
        ldx #>save_read_fn
        jsr disk_save_seq      ; A = error, X = 0 (Z is X's: test A)
        cmp #0
        bne @err

        ; Success
        lda #0
        sta ed_dirty
        lda disk_seq_bytes
        sta ed_save_bytes
        lda disk_seq_bytes+1
        sta ed_save_bytes+1
        lda disk_seq_lines
        sta ed_save_lines
        lda disk_seq_lines+1
        sta ed_save_lines+1
        lda #0
        tax
        rts
@err:   rts                     ; A = error code (Z=0), X = 0
.endproc

; ── load_insert — insert callback for ed_load_source ─────────
; Called by disk_load_seq once per byte read from the SEQ file.
; No width enforcement — bytes are stored as-is.
; Input: A = byte from SEQ file
; Clobbers: A, X
.proc load_insert
        ldx _load_overflow
        bne @noop
        jsr gb_insert
        bcs @noop               ; C=1 → success
        lda #1
        sta _load_overflow
@noop:  rts
.endproc

; ── ed_load_source — load SEQ file into buffer ────────────────
; Input: A/X = name pointer
; Returns: A = 0 success, 1 disk error / empty file, 2 too large;
;          X = 0, Z set from A.
;
; No line-width enforcement — lines are stored as-is.
.proc ed_load_source
        ; Store name for disk_load_seq
        sta disk_ptr
        stx disk_ptr+1

        ; Reset buffer
        jsr ed_init

        lda #0
        sta _load_overflow
        lda #<load_insert
        ldx #>load_insert
        jsr disk_load_seq      ; A = error
        pha                     ; save error

        ; Check for buffer overflow first — if the file ran out of
        ; gap-buffer room mid-load, we have a partial buffer that's
        ; useless to the user.  Wipe it and report a distinct error.
        lda _load_overflow
        beq @no_overflow
        pla                     ; discard disk error
        jsr ed_init             ; reset buffer
        ldx #0
        lda #2                  ; error: file too large (Z=0)
        rts
@no_overflow:

        ; Check for error or empty file
        pla
        bne @fail
        lda disk_seq_bytes
        ora disk_seq_bytes+1
        beq @empty              ; 0 bytes → empty/fail

        ; Move cursor to start of buffer
@rewind:
        lda gap_lo
        cmp buf_base
        bne @do_left
        lda gap_lo+1
        cmp buf_base+1
        beq @at_start
@do_left:
        jsr gb_cursor_left
        jmp @rewind

@at_start:
        lda #0
        sta ed_cur_line
        sta ed_cur_line+1
        sta ed_cur_col
        sta ed_top_line
        sta ed_top_line+1
        sta ed_dirty
        lda buf_base
        sta ed_top_ptr
        lda buf_base+1
        sta ed_top_ptr+1

        lda disk_seq_bytes
        sta ed_save_bytes
        lda disk_seq_bytes+1
        sta ed_save_bytes+1
        lda disk_seq_lines
        sta ed_save_lines
        lda disk_seq_lines+1
        sta ed_save_lines+1

        lda #0
        tax
        rts

@empty:
        jsr ed_init
        ldx #0
        lda #1                  ; error: empty file (Z=0)
        rts

@fail:
        pha
        jsr ed_init
        ldx #0
        pla                     ; error code (Z=0)
        rts
.endproc
