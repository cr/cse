; editor.s — gap-buffer source editor
;
; Screen layout:
;   Row  0-21  Source text (22 lines)
;   Row 22     Status bar
;   Row 23-24  Last 2 lines preserved from REPL

        .macpack longbranch

        .export enter_editor, leave_editor
        .export ed_handle_key
        .export ed_ensure_init, ed_new
        .export ed_save_source, ed_load_source
        .export ed_read_rewind, ed_read_byte, ed_read_line
        .export ed_insert_string
        .export ed_save_bytes, ed_save_lines     ; ed_dirty → zp.s (Phase 21)
        .export ed_total_lines
        .export src_top, src_bot
        .export define_ws_syms          ; Phase 21 Move 1 — moved from mem.s

        .import io_sync, io_blip
        .import kernal_bank_out, kernal_bank_in
        .import disk_save_seq, disk_load_seq
        .import disk_seq_bytes, disk_seq_lines
        .import cse_start
        .import cur_project_name
        .importzp state, ed_dirty         ; zp.s (Phase 21 Move 4)
        .import scr_lo, scr_hi
        .import sym_define
        .importzp disk_ptr
        .importzp sym_name, sym_val, sym_wide
        .import s_workstart, s_workend

; ── Constants ────────────────────────────────────────────────
SCREEN       = $0400
SCREEN_WIDTH = 40
ED_LINES     = 22            ; visible source lines
ED_STATUS    = 22            ; status bar row
.import __CODE_RUN__
.import __BUF_FLOOR__
.define BUF_END __CODE_RUN__   ; exclusive end of buffer (= runtime start)
.define BUF_FLOOR __BUF_FLOOR__ ; source growth limit (compute_layout.py)
REPL_SCREEN  = $F4F2         ; banked RAM under KERNAL

; ── Tab width (build-time constant) ──────────────────────────
; TAB_WIDTH is set via `-DTAB_WIDTH=N` in the Makefile (default 8).
; Power-of-two values collapse `col mod TAB_WIDTH` to a single
; `and #TAB_MASK`, so the default 8 (matching every C64-era
; toolchain convention) is the fast path.  Any value outside
; 1..32 is a build error.  See doc/modules/editor.md.
.ifndef TAB_WIDTH
TAB_WIDTH = 8
.endif
.if TAB_WIDTH < 1 .or TAB_WIDTH > 32
.error "TAB_WIDTH must be in 1..32"
.endif
TAB_MASK = TAB_WIDTH - 1

; KERNAL locations
CUR_COL      = $D3           ; io_cx
CUR_ROW      = $D6           ; io_cy

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
ed_cur_col:     .res 1          ; cursor visual column (0-based)
ed_top_line:    .res 2          ; line number at screen row 0
ed_total_lines: .res 2          ; total line count in buffer
; ed_dirty moved to zp.s (Phase 21 Move 4)
ed_save_bytes: .res 2          ; bytes from last file op
ed_save_lines: .res 2          ; lines from last file op
_load_overflow: .res 1         ; sticky: set if any insert during load
                                ; failed because the gap buffer is full
                                ; (file > workspace).  Read by
                                ; ed_load_source after the disk loop.
save_phase:     .res 1          ; 0=pre-gap, 1=post-gap
repl_cur_x:     .res 1          ; saved REPL cursor X
repl_cur_y:     .res 1          ; saved REPL cursor Y
; (ws_buf removed — smart indent uses inline $A0 insert, no buffer)
src_top:       .res 2          ; buffer upper bound (for REPL i command)
src_bot:       .res 2          ; buffer lower bound (for REPL i command)

; ── RODATA ───────────────────────────────────────────────────
.segment "RODATA"

; Hex digit table for status bar (screen codes, OR'd with $80 for reverse)
st_hx:  .byte $30,$31,$32,$33,$34,$35,$36,$37
        .byte $38,$39,$01,$02,$03,$04,$05,$06

; ── CODE ─────────────────────────────────────────────────────
.segment "CODE"

; ── Shared internal helpers ──────────────────────────────────

; _ed_scr_row — set ed_scr = screen address for row X
_ed_scr_row:
        lda scr_lo,x
        sta ed_scr
        lda scr_hi,x
        sta ed_scr+1
        rts

; _ed_scr_top — set ed_scr = ed_top_ptr
_ed_scr_top:
        lda ed_top_ptr
        sta ed_scr
        lda ed_top_ptr+1
        sta ed_scr+1
        rts

; _ed_scr_ghi — set ed_scr = gap_hi
_ed_scr_ghi:
        lda gap_hi
        sta ed_scr
        lda gap_hi+1
        sta ed_scr+1
        rts

; _ed_scr_glo — set ed_scr = gap_lo
_ed_scr_glo:
        lda gap_lo
        sta ed_scr
        lda gap_lo+1
        sta ed_scr+1
        rts

; _ed_cur_row — A = ed_cur_line - ed_top_line (screen row)
; Leaves carry from the low-byte subtraction intact for callers that
; immediately SBC the high bytes.
_ed_cur_row:
        lda ed_cur_line
        sec
        sbc ed_top_line
        rts

; ── Gap buffer core + sequential reader ──────────────────────

; ── ed_init — reset all buffer state ──────────────────────────
.proc ed_init
        lda #<BUF_END
        sta gap_lo
        sta gap_hi
        sta buf_base
        sta ed_top_ptr
        sta src_top
        sta src_bot
        lda #>BUF_END
        sta gap_lo+1
        sta gap_hi+1
        sta buf_base+1
        sta ed_top_ptr+1
        sta src_top+1
        sta src_bot+1
        lda #0
        sta ed_cur_line
        sta ed_cur_line+1
        sta ed_cur_col
        sta ed_top_line
        sta ed_top_line+1
        sta ed_dirty
        sta ed_total_lines+1
        lda #1
        sta ed_total_lines
        jmp update_workend      ; tail call
.endproc

; ── define_ws_syms — register both workspace symbols ─────────
; workstart = $0800 (fixed), workend = buf_base - 1 (dynamic).
; Called from main.s cold-init and asm_src.s::asm_assemble after
; sym_clear.  Falls through into update_workend for the workend
; half — saves bytes vs. two independent procs.  Moved from mem.s
; in Phase 21 Move 1 so mem.s can stay a zp-only leaf.
.proc define_ws_syms
        ; workstart ($0800, fixed)
        lda #<$0800
        sta sym_val
        lda #>$0800
        sta sym_val+1
        lda #<s_workstart
        sta sym_name
        lda #>s_workstart
        sta sym_name+1
        lda #1
        sta sym_wide
        jsr sym_define
        ; fall through to update_workend for the dynamic half
.endproc

; ── update_workend — redefine workend symbol from buf_base ────
; Called after any buf_base change (ed_init, gb_ensure_room) and
; also falls-into from define_ws_syms above.
.proc update_workend
        lda buf_base
        sec
        sbc #1
        sta sym_val
        lda buf_base+1
        sbc #0
        sta sym_val+1
        lda #<s_workend
        sta sym_name
        lda #>s_workend
        sta sym_name+1
        lda #1
        sta sym_wide
        jmp sym_define         ; tail call
.endproc

; ── gb_ensure_room — grow buffer if gap exhausted ─────────────
; Returns: C=1 ok, C=0 fail (out of memory)
.proc gb_ensure_room
        ; Check gap_hi - gap_lo > 0
        lda gap_hi
        sec
        sbc gap_lo
        sta ed_tmp
        lda gap_hi+1
        sbc gap_lo+1
        ora ed_tmp
        beq :+                  ; gap == 0, need to grow
        jmp @have_room          ; gap > 0
:
        ; Check buf_base - 256 >= BUF_FLOOR
        ; BUF_FLOOR is page-aligned, so hi-byte check is sufficient
        lda buf_base+1
        cmp #>(BUF_FLOOR) + 1   ; #$49
        jcc @no_room
@can_grow:
        ; pre_size = gap_lo - buf_base
        lda gap_lo
        sec
        sbc buf_base
        sta ed_tmp              ; pre_size lo
        lda gap_lo+1
        sbc buf_base+1
        sta ed_tmp+1            ; pre_size hi

        ; new_base = buf_base - 256 (subtract $0100)
        ; Just decrement buf_base hi byte
        dec buf_base+1

        ; Copy pre-gap text from old_base to new_base (ascending copy)
        ; pre_size in ed_tmp/ed_tmp+1
        ; Source: buf_base + $0100 (the old buf_base)
        ; Dest:   buf_base (the new buf_base)
        lda ed_tmp
        ora ed_tmp+1
        beq @no_copy            ; pre_size = 0, skip copy

        ; Setup copy: src = buf_base+$100 (old base), dst = buf_base (new base)
        ; We need to copy ed_tmp bytes ascending
        ; Use save_ptr as src, ed_scr as dst (both are scratch-safe here)
        lda buf_base
        sta ed_scr              ; dst lo (new_base)
        sta save_ptr            ; src lo = same base
        lda buf_base+1
        sta ed_scr+1            ; dst hi
        clc
        adc #1
        sta save_ptr+1          ; src hi = buf_base+1 + 1

        ; Copy ed_tmp bytes ascending (src → dst)
        ; pre_size could be > 256, use page loop
        ldx ed_tmp+1            ; full pages
        ldy #0
        ; Copy full pages
        cpx #0
        beq @partial
@page:  lda (save_ptr),y
        sta (ed_scr),y
        iny
        bne @page
        inc save_ptr+1
        inc ed_scr+1
        dex
        bne @page
@partial:
        ; Copy remaining ed_tmp (lo) bytes
        ldx ed_tmp              ; remaining bytes
        beq @copy_done
        ldy #0
@rem:   lda (save_ptr),y
        sta (ed_scr),y
        iny
        dex
        bne @rem
@copy_done:
@no_copy:
        ; Adjust ed_top_ptr if in old pre-gap region
        ; old_base.hi = buf_base.hi + 1 (buf_base already decremented)
        lda ed_top_ptr+1
        cmp buf_base+1
        beq @no_adjust          ; same as new base → below old region
        bcc @no_adjust          ; below new base
        ; ed_top_ptr.hi > buf_base.hi → check <= gap_lo
        lda gap_lo+1
        cmp ed_top_ptr+1
        bcc @no_adjust          ; gap_lo < ed_top_ptr → post-gap
        bne @shift              ; gap_lo > ed_top_ptr → in pre-gap
        lda gap_lo
        cmp ed_top_ptr
        bcc @no_adjust          ; gap_lo < ed_top_ptr
@shift: dec ed_top_ptr+1
@no_adjust:
        ; Update gap_lo = new_base + pre_size
        lda buf_base
        clc
        adc ed_tmp              ; pre_size lo
        sta gap_lo
        lda buf_base+1
        adc ed_tmp+1
        sta gap_lo+1

        ; gap_hi = gap_lo + 256
        lda gap_lo
        sta gap_hi
        lda gap_lo+1
        clc
        adc #1
        sta gap_hi+1

        ; Update src_bot + workend symbol
        lda buf_base
        sta src_bot
        lda buf_base+1
        sta src_bot+1
        jsr update_workend

@have_room:
        sec                     ; success
        rts
@no_room:
        clc                     ; failure
        rts
.endproc

; ── gb_insert — insert byte at gap ────────────────────────────
; Input: A = byte to insert
; Output: C=1 success, C=0 failure (buffer full, byte discarded)
; Clobbers: A, Y
.proc gb_insert
        pha                     ; save byte
        jsr gb_ensure_room
        bcc @full               ; no room
        pla
        ldy #0
        sta (gap_lo),y
        ; bump gap_lo
        inc gap_lo
        bne :+
        inc gap_lo+1
:       cmp #$0D
        bne @not_cr
        inc ed_total_lines
        bne :+
        inc ed_total_lines+1
:
@not_cr:
        lda #1
        sta ed_dirty
        sec                     ; success
        rts
@full:
        pla                     ; discard byte
        clc                     ; failure
        rts
.endproc

; ── gb_backspace — delete before gap ──────────────────────────
.proc gb_backspace
        ; if gap_lo == buf_base → nothing
        lda gap_lo
        cmp buf_base
        bne @ok
        lda gap_lo+1
        cmp buf_base+1
        beq @done
@ok:
        ; --gap_lo
        lda gap_lo
        bne :+
        dec gap_lo+1
:       dec gap_lo
        ; check if deleted byte is $0D
        ldy #0
        lda (gap_lo),y
        cmp #$0D
        bne @not_cr
        ; --ed_total_lines
        lda ed_total_lines
        bne :+
        dec ed_total_lines+1
:       dec ed_total_lines
@not_cr:
        lda #1
        sta ed_dirty
@done:  rts
.endproc

; ── gb_cursor_right — move gap right one byte ─────────────────
; Clobbers: A, Y
.proc gb_cursor_right
        ; if gap_hi >= BUF_END → done
        lda gap_hi+1
        cmp #>BUF_END
        bcc @ok
        lda gap_hi
        cmp #<BUF_END
        bcs @done
@ok:
        ldy #0
        lda (gap_hi),y          ; byte at gap_hi
        sta (gap_lo),y          ; copy to gap_lo
        ; ++gap_lo
        inc gap_lo
        bne :+
        inc gap_lo+1
:       ; ++gap_hi
        inc gap_hi
        bne :+
        inc gap_hi+1
:
@done:  rts
.endproc

; ── gb_cursor_left — move gap left one byte ───────────────────
; Clobbers: A, Y
.proc gb_cursor_left
        ; if gap_lo == buf_base → done
        lda gap_lo
        cmp buf_base
        bne @ok
        lda gap_lo+1
        cmp buf_base+1
        beq @done
@ok:
        ; --gap_hi
        lda gap_hi
        bne :+
        dec gap_hi+1
:       dec gap_hi
        ; --gap_lo
        lda gap_lo
        bne :+
        dec gap_lo+1
:       dec gap_lo
        ; copy byte from gap_lo to gap_hi
        ldy #0
        lda (gap_lo),y
        sta (gap_hi),y
@done:  rts
.endproc

; ── ed_ensure_init — allocate gap buffer if needed ────────────
.proc ed_ensure_init
        lda ed_total_lines
        ora ed_total_lines+1
        bne @done
        jsr ed_init
@done:  rts
.endproc

; ── ed_new — clear editor (new file) ─────────────────────────
.proc ed_new
        jsr ed_init
        lda #0
        sta cur_project_name
        rts
.endproc

; ── ed_insert_string — insert PETSCII string at cursor ────────
; Input: A/X = text pointer
.proc ed_insert_string
        sta save_ptr            ; reuse save_ptr as text pointer
        stx save_ptr+1
        jsr ed_ensure_init
@loop:
        ldy #0
        lda (save_ptr),y
        beq @done               ; NUL terminator
        jsr gb_insert
        ; advance pointer
        inc save_ptr
        bne @loop
        inc save_ptr+1
        jmp @loop
@done:  rts
.endproc

; ── Sequential reader — for source assembler ─────────────────

; ── ed_read_rewind — reset read pointer to start ──────────────
.proc ed_read_rewind
        jsr ed_ensure_init
        lda buf_base
        sta read_ptr
        lda buf_base+1
        sta read_ptr+1
        rts
.endproc

; ── ed_read_byte — read next byte from source ─────────────────
; Returns: A/X = byte (X=0), or A=$FF/X=$FF at EOF
.proc ed_read_byte
        ; Skip gap
        lda read_ptr
        cmp gap_lo
        bne @no_gap
        lda read_ptr+1
        cmp gap_lo+1
        bne @no_gap
        ; read_ptr == gap_lo → skip to gap_hi
        lda gap_hi
        sta read_ptr
        lda gap_hi+1
        sta read_ptr+1
@no_gap:
        ; Check EOF: read_ptr >= BUF_END
        lda read_ptr+1
        cmp #>BUF_END
        bcc @ok
        bne @eof
        lda read_ptr
        cmp #<BUF_END
        bcs @eof
@ok:
        ldy #0
        lda (read_ptr),y
        pha                     ; save byte
        inc read_ptr
        bne :+
        inc read_ptr+1
:       pla                     ; byte in A
        ldx #0
        rts
@eof:
        lda #$FF
        tax                     ; A=$FF, X=$FF → -1
        rts
.endproc

; ── ed_read_line — read one line into buffer ──────────────────
; Input: A/X = buf pointer. Maxlen hardcoded to 40.
; Returns: A/X = length, or A=$FF/X=$FF at EOF
.proc ed_read_line
        sta ed_scr              ; buf lo
        stx ed_scr+1            ; buf hi
        lda #40
        sta ed_tmp+1            ; maxlen
        lda #0
        sta ed_tmp              ; len = 0
@loop:
        jsr ed_read_byte
        cpx #$FF
        beq @eof_check          ; got EOF from read_byte
        ; Got a byte in A
        cmp #$0D
        beq @eol                ; end of line
        ; Store if room: len < maxlen - 1
        ldx ed_tmp              ; current len
        inx                     ; len + 1
        cpx ed_tmp+1            ; compare with maxlen
        bcs @loop               ; len+1 >= maxlen → truncate (don't store)
        ; Store byte
        ldy ed_tmp
        sta (ed_scr),y
        inc ed_tmp              ; ++len
        jmp @loop
@eol:
        ; NUL-terminate
        ldy ed_tmp
        lda #0
        sta (ed_scr),y
        lda ed_tmp              ; return len
        ldx #0
        rts
@eof_check:
        ; EOF — return what we have, or -1 if nothing
        lda ed_tmp
        beq @eof_empty
        ; NUL-terminate and return len
        ldy ed_tmp
        lda #0
        sta (ed_scr),y
        lda ed_tmp
        ldx #0
        rts
@eof_empty:
        lda #$FF
        tax                     ; -1
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

; ── check_buf_end — check if ed_scr >= BUF_END ───────────────
; Returns: C=1 if >= BUF_END (past end), C=0 if still in buffer
.proc check_buf_end
        lda ed_scr+1
        cmp #>BUF_END
        bcc @in                 ; hi < BUF_END.hi → in buffer
        bne @past               ; hi > BUF_END.hi → past end
        lda ed_scr
        cmp #<BUF_END
        rts                     ; C=1 if >= BUF_END, C=0 if <
@in:    clc
        rts
@past:  sec
        rts
.endproc


; ── blank_row — fill screen row X with spaces ─────────────────
; Clobbers: A, Y, ed_tmp
.proc blank_row
        lda scr_lo,x
        sta ed_tmp
        lda scr_hi,x
        sta ed_tmp+1
        lda #$20
        ldy #SCREEN_WIDTH - 1
@blank: sta (ed_tmp),y
        dey
        bpl @blank
        rts
.endproc

; ── ed_sync_cursor — push editor cursor to KERNAL cursor ─────
; Off-screen cursor rows are ignored.
.proc ed_sync_cursor
        jsr _ed_cur_row
        cmp #ED_LINES
        bcs @done
        sta CUR_ROW
        lda ed_cur_col
        sta CUR_COL
        jsr io_sync
@done:  rts
.endproc

; ── ed_render_line — render one line to screen row ────────────
; Input: X = screen row, ed_scr = buffer position (in/out, advances past CR)
; Output: A = 1 if more text, 0 if EOF. ed_scr updated.
; Clobbers: A, X, Y
.proc ed_render_line
        ; Setup screen pointer in ed_tmp
        lda scr_lo,x
        sta ed_tmp
        lda scr_hi,x
        sta ed_tmp+1
        ldy #0                  ; col = 0

@char_loop:
        cpy #SCREEN_WIDTH
        bcc :+
        ; Line overflows screen — show > indicator in col 39.
        ; Skip remaining content until CR or EOF.
        lda #$3E                ; '>' (normal, not reversed)
        ldy #SCREEN_WIDTH - 1
        sta (ed_tmp),y
        jmp @skip_rest
:
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @pad
        ; Read byte
        sty @save_col           ; save col (Y)
        ldy #0
        lda (ed_scr),y
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
        sta (ed_tmp),y          ; scr[col] = sc
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
        cpy #SCREEN_WIDTH
        bcs @tab_advance
        lda #$20
        sta (ed_tmp),y
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
        cpy #SCREEN_WIDTH
        bcs @pad_done
        lda #$20
        sta (ed_tmp),y
        iny
        bne @pad                ; Y never wraps to 0 within 40 iterations

@skip_rest:
        ; Advance ed_scr past remaining content until CR or EOF.
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @pad_done
        ldy #0
        lda (ed_scr),y
        inc ed_scr
        bne :+
        inc ed_scr+1
:       cmp #$0D
        bne @skip_rest
@pad_done:
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @ret_eof
        lda #1
        rts
@ret_eof:
        lda #0
        rts

@save_col: .byte 0
@tw_save:  .byte 0
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
        lda (ed_scr),y
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
        lda (ed_tmp),y
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
        sta (ed_scr),y

        lda ed_tmp+1
        and #$0F
        tax
        lda st_hx,x
        ora #$80
        iny
        sta (ed_scr),y

        lda ed_tmp
        lsr
        lsr
        lsr
        lsr
        tax
        lda st_hx,x
        ora #$80
        iny
        sta (ed_scr),y

        lda ed_tmp
        and #$0F
        tax
        lda st_hx,x
        ora #$80
        iny
        sta (ed_scr),y
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
@rem:   .byte 0
.endproc

; ── ed_status_pos — update cursor position (cols 34-39) ───────
.proc ed_status_pos
        ; Screen pointer to status row
        ldx #ED_STATUS
        jsr _ed_scr_row

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
        sta (ed_scr),y          ; ones digit

        lda ed_tmp              ; tens
        clc
        adc #$30
        ora #$80
        dey                     ; Y=38
        sta (ed_scr),y

        lda #($2C | $80)        ; comma, reversed
        dey                     ; Y=37
        sta (ed_scr),y

        ; Line: 3 digits (1-based)
        lda ed_cur_line
        clc
        adc #1
        sta ed_tmp
        lda ed_cur_line+1
        adc #0
        sta ed_tmp+1
        jsr div10               ; A = d0 (ones), ed_tmp = rest
        clc
        adc #$30
        ora #$80
        ldy #36
        sta (ed_scr),y          ; ones

        jsr div10               ; A = d1 (tens), ed_tmp = d2 (hundreds)
        pha                     ; save d1
        lda ed_tmp              ; d2 (hundreds)
        sta @d2

        pla                     ; d1
        ; d1: show if d2 or d1 nonzero, else space
        ldx @d2
        bne @show_d1
        cmp #0
        beq @blank_d1
@show_d1:
        clc
        adc #$30
        ora #$80
        ldy #35
        sta (ed_scr),y
        jmp @do_d2
@blank_d1:
        lda #$A0                ; reversed space
        ldy #35
        sta (ed_scr),y
@do_d2:
        lda @d2
        beq @blank_d2
        clc
        adc #$30
        ora #$80
        ldy #34
        sta (ed_scr),y
        rts
@blank_d2:
        lda #$A0
        ldy #34
        sta (ed_scr),y
        rts

@d2:    .byte 0
.endproc

; ── ed_status_dirty — update dirty flag (col 0) ──────────────
.proc ed_status_dirty
        ldx #ED_STATUS
        jsr _ed_scr_row
        lda ed_dirty
        beq @clean
        lda #($2A | $80)        ; '*' reversed
        jmp @store
@clean: lda #$A0                ; space reversed
@store: ldy #0
        sta (ed_scr),y
        rts
.endproc

; ── ed_status_free — update upper free address (cols 29-32) ───
.proc ed_status_free
        ldx #ED_STATUS
        lda scr_lo,x
        clc
        adc #29
        sta ed_scr
        lda scr_hi,x
        adc #0
        sta ed_scr+1
        ; val = buf_base - 1
        lda buf_base
        sec
        sbc #1
        sta ed_tmp
        lda buf_base+1
        sbc #0
        sta ed_tmp+1
        jmp st_hex4
.endproc

; ── ed_render_status — full status bar rebuild ────────────────
.proc ed_render_status
        ; Get screen pointer to status row
        ldx #ED_STATUS
        jsr _ed_scr_row

        ; Fill with reversed spaces
        lda #$A0
        ldy #SCREEN_WIDTH - 1
@fill:  sta (ed_scr),y
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
        sta (ed_scr),y

        ; Filename (cols 1-17)
        lda cur_project_name
        beq @no_name
        ; Find length of cur_project_name
        ldy #0
@flen:  lda cur_project_name,y
        beq @flen_done
        iny
        cpy #FILENAME_MAX_LEN
        bcc @flen
@flen_done:
        sty @fn_len
        ; Strip ",s" suffix if present
        cpy #2
        bcc @fn_copy
        dey
        dey
        lda cur_project_name,y
        cmp #','
        bne @fn_copy
        sty @fn_len             ; stripped 2 chars
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
        sta (ed_scr),y
        inx
        iny
        bne @fn_loop            ; Y never wraps here
@no_name:

        ; "free:" label (cols 19-23)
        ldy #19
        lda #($06 | $80)        ; 'f' reversed screencode
        sta (ed_scr),y
        iny
        lda #($12 | $80)        ; 'r'
        sta (ed_scr),y
        iny
        lda #($05 | $80)        ; 'e'
        sta (ed_scr),y
        iny
        lda #($05 | $80)        ; 'e'
        sta (ed_scr),y
        iny
        lda #($3A | $80)        ; ':'
        sta (ed_scr),y

        ; Lower free address (cols 24-27)
        lda ed_scr
        pha
        lda ed_scr+1
        pha
        lda #<$0800             ; workstart (lower free bound)
        ldx #>$0800
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
        sta (ed_scr),y

        ; Upper free + cursor pos via partial updaters
        jsr ed_status_free
        jmp ed_status_pos       ; tail call

@fn_len:  .byte 0
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
        cpx #ED_LINES
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

@from:   .byte 0
@to:     .byte 0
@save_x: .byte 0
.endproc

; ── ed_render — full redraw (22 lines + status) ──────────────
.proc ed_render
        ldx #0
        ldy #ED_LINES
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
        ; Shift screen rows 1..21 → 0..20 (21 rows × 40 bytes = 840 B).
        ; Row-by-row ascending copy: at iter k, dst = row k, src = row k+1.
        ; Safe because src row and dst row never overlap.
        ldx #0                  ; X = dst row; src row = X + 1
@row:   jsr _ed_scr_row
        inx                     ; X = src row
        lda scr_lo,x
        sta save_ptr
        lda scr_hi,x
        sta save_ptr+1
        ldy #SCREEN_WIDTH - 1
@byte:  lda (save_ptr),y
        sta (ed_scr),y
        dey
        bpl @byte
        cpx #ED_LINES - 1       ; just copied from row 21? → done
        bne @row

        ; Render the new bottom line (row 21)
        ; Find position: advance from ed_top_ptr by 21 lines
        jsr _ed_scr_top
        ldx #0
@skip:  cpx #ED_LINES - 1      ; skip 21 lines
        bcs @got_pos
        jsr skip_one_line
        inx
        jmp @skip
@got_pos:
        jsr skip_gap_scr
        jsr check_buf_end
        bcc @render_bottom

        ; Past EOF — blank row 21
        ldx #ED_LINES - 1
        jsr blank_row
        jmp ed_status_pos

@render_bottom:
        ldx #ED_LINES - 1
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

        ; Shift screen rows 0..20 → 1..21 (21 rows × 40 bytes = 840 B).
        ; Row-by-row descending copy so each src row is read before it
        ; gets overwritten by the row being shifted into it.
        ldx #ED_LINES - 1       ; X = dst row (21); src row = X - 1
@row:   jsr _ed_scr_row
        dex                     ; X = src row
        lda scr_lo,x
        sta save_ptr
        lda scr_hi,x
        sta save_ptr+1
        ldy #SCREEN_WIDTH - 1
@byte:  lda (save_ptr),y
        sta (ed_scr),y
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
        lda (ed_scr),y
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

@vc_save: .byte 0
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
; Used by the renderer to detect lines wider than 39 columns.
.proc line_vwidth
        ldx #0                  ; X = accumulating vcol
@loop:
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @done
        ; Read byte
        ldy #0
        lda (ed_scr),y
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

@vw_save: .byte 0
.endproc

; ── find_line_start — walk gap_lo back to the line start ──────
; Sets ed_scr to the start of the cursor's line (just past the
; preceding $0D, or buf_base at the top of the buffer).  Does
; NOT move the gap.  Shared by visual_col and copy_leading_ws.
; Clobbers: A, Y, ed_tmp.  Preserves X.
.proc find_line_start
        jsr _ed_scr_glo
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
        lda (ed_tmp),y
        cmp #$0D
        beq @done               ; CR found → ed_scr is line start
        lda ed_tmp
        sta ed_scr
        lda ed_tmp+1
        sta ed_scr+1
        jmp @back
@done:  rts
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
        lda (ed_scr),y
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
        lda (ed_scr),y
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
        lda (ed_scr),y
        dey
        sta (ed_scr),y
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

; ── gb_home — move gap to start of current line ──────────────
.proc gb_home
@loop:
        ; Check gap_lo > buf_base
        lda gap_lo
        cmp buf_base
        bne @not_base
        lda gap_lo+1
        cmp buf_base+1
        beq @done               ; at buf_base → done
@not_base:
        ; Check byte before gap_lo: if $0D, done
        lda gap_lo
        sec
        sbc #1
        sta ed_tmp
        lda gap_lo+1
        sbc #0
        sta ed_tmp+1
        ldy #0
        lda (ed_tmp),y
        cmp #$0D
        beq @done
        jsr gb_cursor_left
        jmp @loop
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
        lda (gap_hi),y
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

@target: .byte 0
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

@target: .byte 0
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
        lda (gap_hi),y
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

@target: .byte 0
.endproc

; ── ed_mark_edited — set dirty flag, update status ────────────
.proc ed_mark_edited
        lda ed_dirty
        bne @already
        lda #1
        sta ed_dirty
        jsr ed_status_dirty
@already:
        jsr ed_status_free
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

; ── ed_handle_key — main keystroke dispatcher ─────────────────
; Input: A = PETSCII key code
.proc ed_handle_key
        ; Save key
        sta @key

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
        ; Refuse if cursor is already at col 39 (screen edge)
        lda ed_cur_col
        cmp #SCREEN_WIDTH - 1
        jcs @reject
        ldy #0
        lda (gap_hi),y
        cmp #$0D
        jeq @reject             ; end of line
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
        ; if ed_cur_line >= ed_top_line + ED_LINES → scroll up
        jsr _ed_cur_row
        sta ed_tmp
        lda ed_cur_line+1
        sbc ed_top_line+1
        bne @do_scroll_up       ; hi byte nonzero → definitely >= 22
        lda ed_tmp
        cmp #ED_LINES
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
        ldy #ED_LINES
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
        lda @join_col
        jsr advance_to_vcol
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
        ldy #ED_LINES
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
        lda (gap_lo),y
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
        lda (gap_hi),y
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
        lda (gap_lo),y
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
        inc ed_cur_line
        bne :+
        inc ed_cur_line+1
:       lda #$A0
        jsr gb_insert
        lda #TAB_WIDTH
        sta ed_cur_col
        jmp @enter_render

        ; Step 1 (BOL path): just insert CR
@bol_cr:
        lda #$0D
        jsr gb_insert
        inc ed_cur_line
        bne :+
        inc ed_cur_line+1
:       lda #0
        sta ed_cur_col
@enter_render:

        ; Scroll or re-render
        ; if ed_cur_line >= ed_top_line + ED_LINES → scroll up
        jsr _ed_cur_row
        sta ed_tmp
        lda ed_cur_line+1
        sbc ed_top_line+1
        bne @enter_scroll       ; hi nonzero → scroll
        lda ed_tmp
        cmp #ED_LINES
        bcs @enter_scroll
        ; No scroll — re-render from previous row
        tax                     ; scr_row = ed_cur_line - ed_top_line
        beq @enter_full         ; scr_row == 0 → full render
        dex                     ; from scr_row - 1
        ldy #ED_LINES
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
        jsr cursor_line_vwidth
        cmp #SCREEN_WIDTH - 1   ; line full → refuse
        jcs @reject
        lda #$20
        jsr gb_insert
        jsr gb_cursor_left      ; cursor back onto the space
        jsr render_current_row
        jmp @edited_repos
@not_ins:

        ; ── TAB ($A0) — always enabled under TAB_WIDTH ──
        cmp #$A0
        bne @not_tab
        ; Cap check: refuse if line_vwidth + char_width(TAB, line_vwidth) > 39.
        jsr cursor_line_vwidth
        tax
        lda #$A0
        jsr char_width
        sta @new_col
        txa
        clc
        adc @new_col
        cmp #SCREEN_WIDTH       ; > 39 → refuse
        jcs @reject
        ; Compute the new ed_cur_col: ed_cur_col + char_width(TAB, ed_cur_col).
        lda #$A0
        ldx ed_cur_col
        jsr char_width
        clc
        adc ed_cur_col
        sta @new_col
        lda #$A0
        jsr gb_insert
        lda @new_col
        sta ed_cur_col
        jsr render_current_row
        jmp @repos

        ; ── Default: printable character ──────────
@not_tab:
        lda @key
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
        ; Refuse if the line is already at the 39-col cap.
        jsr cursor_line_vwidth
        cmp #SCREEN_WIDTH - 1   ; line_vwidth ≥ 39 → refuse
        bcs @reject
        lda @key
        jsr gb_insert
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
        lda (gap_hi),y
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
        jmp ed_sync_cursor

@key:          .byte 0
@new_col:      .byte 0
@join_col: .byte 0
.endproc

; ── Mode switching ───────────────────────────────────────────

; ── copy_1000 — copy 1000 bytes from (save_ptr) to (ed_scr) ──
; Ascending copy: 3 pages + 232 bytes
.proc copy_1000
        ldx #3
        ldy #0
@page:  lda (save_ptr),y
        sta (ed_scr),y
        iny
        bne @page
        inc save_ptr+1
        inc ed_scr+1
        dex
        bne @page
        ldx #232
@rem:   lda (save_ptr),y
        sta (ed_scr),y
        iny
        dex
        bne @rem
        rts
.endproc

; ── enter_editor — switch from REPL to editor ─────────────────
.proc enter_editor
        ; Save REPL cursor position
        lda CUR_COL
        sta repl_cur_x
        lda CUR_ROW
        sta repl_cur_y

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

        ; Init gap buffer if needed
        jsr ed_ensure_init

        ; Smart indent: if buffer is empty, seed first line with a tab.
        ; Empty = gap_lo == buf_base (nothing before the gap).
        lda gap_lo
        cmp buf_base
        bne @has_content
        lda gap_lo+1
        cmp buf_base+1
        bne @has_content
        lda #$A0
        jsr gb_insert
        lda #TAB_WIDTH
        sta ed_cur_col
        lda #0
        sta ed_dirty            ; seed is not a user edit
@has_content:

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
        sta (ed_scr),y
        iny
        bne @clr_pg
        inc ed_scr+1
        dex
        bne @clr_pg
        ; 880 - 768 = 112 remaining
        ldx #112
@clr_rem:
        sta (ed_scr),y
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
@ctx:   lda (save_ptr),y
        sta (ed_scr),y
        dey
        bpl @ctx
        jsr kernal_bank_in

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

        ; Restore REPL cursor position
        lda repl_cur_x
        sta CUR_COL
        lda repl_cur_y
        sta CUR_ROW
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
        lda (save_ptr),y
        pha
        inc save_ptr
        bne :+
        inc save_ptr+1
:       pla
        ldx #0
        rts
.endproc

; ── ed_save_source — save source as SEQ file ──────────────────
; Input: A/X = name pointer
; Returns: A = 0 on success, nonzero on error
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
        lda #0
        sta save_phase

        ; Call disk_save_seq(name, save_read_fn)
        ; name is on parameter stack, read_fn in A/X
        lda #<save_read_fn
        ldx #>save_read_fn
        jsr disk_save_seq      ; A = error (lda sets Z)
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
@err:
        ; Return error code
        ldx #0
        rts
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
; Returns: A = 0 on success, nonzero on error
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
        lda #2                  ; error: file too large
        ldx #0
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
        lda #1                  ; error: empty file
        ldx #0
        rts

@fail:
        pha
        jsr ed_init
        pla                     ; error code
        ldx #0
        rts
.endproc
