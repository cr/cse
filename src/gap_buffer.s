; gap_buffer.s — Gap-buffer primitives (L3)
;
; Pure data-structure operations on the editor's gap buffer: insert,
; delete, cursor navigation within the buffer, buffer-growth, and the
; sequential reader that the source assembler walks.  No KERNAL
; calls, no VIC registers, no screen RAM, no BRK vectors — just
; byte-level memory manipulation via indirect (gap_lo) / (gap_hi) /
; (read_ptr) indexing.
;
; Owns:
;   * `bp_table`-style BSS: ed_total_lines (line counter, bumped on
;     CR insert/delete), src_top / src_bot (buffer bounds for the
;     `i` info command).
;   * gb_init / gb_ensure_init: cold-init + lazy-init entry points.
;   * gb_insert / gb_backspace / gb_cursor_right / gb_cursor_left /
;     gb_home / gb_ensure_room: the six primitives that manipulate
;     the gap.
;   * ed_insert_string: public wrapper — insert a NUL-terminated
;     string at the cursor.
;   * ed_read_rewind / ed_read_byte / ed_read_line: sequential
;     reader (transparent gap skip, EOF reporting).
;   * define_ws_syms / update_workend: register workstart/workend
;     symbols (called from main.s cold-init and
;     asm_src::asm_assemble after sym_clear).
;
; Layer: L3 (core engines), same stratum as addr_mode / expr /
; opcode_lookup / asm_line / dasm / breakpoints — bundle-testable.
;
; Split from editor.s at session 2026-04-20.  editor.s keeps the L4
; parts: keystroke dispatch, screen rendering, scroll drivers,
; enter_editor/leave_editor, disk I/O.  See editor.md for the L4
; responsibilities and gap_buffer.md for the L3 contract.

        .setcpu "6502"
        .macpack longbranch

        .export gb_init
        .export ed_ensure_init
        .export gb_insert, gb_backspace
        .export gb_cursor_left, gb_cursor_right, gb_home
        .export gb_ensure_room
        .export ed_insert_string
        .export ed_read_rewind, ed_read_byte, ed_read_line
        .export check_buf_end
        .export ed_total_lines
        .export src_top, src_bot
        .export define_ws_syms, update_workend

        ; ZP vars (declared in zp.s)
        .importzp gap_lo, gap_hi, buf_base, ed_top_ptr
        .importzp read_ptr, ed_tmp, ed_scr, ed_dirty

        ; Strings (L0 RODATA)
        .import s_workstart, s_workend

        ; Symtab (L2, strictly-downward)
        .import sym_define
        .importzp sym_name, sym_val, sym_wide

        ; Linker-provided workspace ceiling (= runtime code start)
        ; and floor (source-growth limit from compute_layout.py).
        .import __CODE_RUN__
        .import __BUF_FLOOR__
        .define BUF_END   __CODE_RUN__    ; exclusive end of buffer
        .define BUF_FLOOR __BUF_FLOOR__   ; source-growth limit

; save_ptr aliases read_ptr — the sequential reader and the insert
; helpers share the same ZP word (they're never live simultaneously).
save_ptr = read_ptr

; ── BSS ──────────────────────────────────────────────────────────────
.segment "BSS"

ed_total_lines: .res 2          ; total line count in buffer
src_top:        .res 2          ; buffer upper bound (for REPL i command)
src_bot:        .res 2          ; buffer lower bound (for REPL i command)

; ── CODE ─────────────────────────────────────────────────────────────
.segment "CODE"

; ── gb_init — reset gap-buffer state ──────────────────────────
; Called by editor.s::ed_init at cold init and on ed_new / disk load.
; editor.s handles the additional rendering-state reset (ed_cur_line,
; ed_cur_col, ed_top_line) after calling back.
.proc gb_init
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
        sta ed_dirty
        sta ed_total_lines+1
        lda #1
        sta ed_total_lines
        jmp update_workend      ; tail call
.endproc

; ── ed_ensure_init — lazy init guard ─────────────────────────
; Called by the sequential reader, ed_insert_string, and editor.s's
; enter_editor to ensure the buffer is initialised on first use.
; Gap-state only (calls gb_init) — the L4 rendering state is
; BSS-zero at cold boot and doesn't need touching on lazy init.
; ed_new (in editor.s) handles the full reset via ed_init instead
; when the user explicitly asks for a fresh buffer.
; Name kept as ed_ensure_init for consumer-compat across the
; 2026-04-20 gap_buffer split.
.proc ed_ensure_init
        lda ed_total_lines
        ora ed_total_lines+1
        bne @done
        jsr gb_init
@done:  rts
.endproc

; ══════════════════════════════════════════════════════════
; Moved from editor.s 188..208  (define_ws_syms)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 210..228  (update_workend)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 230..356  (gb_ensure_room)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 358..388  (gb_insert)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 390..419  (gb_backspace)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 422..445  (gb_cursor_right)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 448..473  (gb_cursor_left)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 492..509  (ed_insert_string)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 511..521  (ed_read_rewind)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 524..561  (ed_read_byte)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 565..613  (ed_read_line)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 654..667  (check_buf_end)
; ══════════════════════════════════════════════════════════
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

; ══════════════════════════════════════════════════════════
; Moved from editor.s 1639..1665  (gb_home)
; ══════════════════════════════════════════════════════════
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
