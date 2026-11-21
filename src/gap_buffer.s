; gap_buffer.s — Gap-buffer primitives (L3)
; Owner: doc/modules/gap_buffer.md
;
; Pure data-structure operations on the editor's gap buffer: insert,
; delete, cursor navigation within the buffer, buffer-growth, and the
; sequential reader that the source assembler walks.  No KERNAL
; calls, no VIC registers, no screen RAM, no BRK vectors — just
; byte-level memory manipulation via indirect (gap_lo) / (gap_hi) /
; (read_ptr) indexing.
;
; Owns:
;   * BSS gap-buffer state: ed_total_lines (line counter, bumped on
;     CR insert/delete), src_top / src_bot (buffer bounds for the
;     `i` info command).
;   * gb_init / ed_ensure_init: cold-init + lazy-init entry points.
;   * gb_insert / gb_backspace / gb_cursor_right / gb_cursor_left /
;     gb_home / gb_ensure_room: the six primitives that manipulate
;     the gap.
;   * ed_insert_string: test-only export — insert a NUL-terminated
;     string at the cursor; ignores gb_insert's carry (gap_buffer.md).
;   * ed_read_rewind / ed_read_byte / ed_read_line: sequential
;     reader (transparent gap skip, EOF reporting).
;   * define_ws_syms / update_workend: register workstart/workend
;     symbols (called from main.s cold-init and
;     asm_src::asm_assemble after sym_clear).
;
; Layer: L3 (core engines), same stratum as addr_mode / expr /
; opcode_lookup / asm_line / dasm / breakpoints — bundle-testable.
;
; editor.s holds the L4 parts: keystroke dispatch, screen rendering,
; scroll drivers, enter_editor/leave_editor, disk I/O.  See editor.md
; for the L4 responsibilities and gap_buffer.md for the L3 contract.

        .setcpu "6502"
        .include "platform.inc"
        .macpack longbranch

        .export gb_init
        .export ed_ensure_init
        .export gb_insert, gb_backspace
        .export gb_cursor_left, gb_cursor_right, gb_home
        .export gb_ensure_room
        .export gb_clip_copy, gb_delete, gb_clip_put, gb_clip_drop, gb_rev
        .export clip_base
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

        ; The buffer's ceiling BUF_END (exclusive) and floor BUF_FLOOR
        ; are platform.inc's: the c64 runtime start and growth limit
        ; (linker symbols), the m65 source region's offsets.

; save_ptr aliases read_ptr — the sequential reader and the insert
; helpers share the same ZP word (they're never live simultaneously).
save_ptr = read_ptr

; ── BSS ──────────────────────────────────────────────────────────────
.segment "BSS"

ed_total_lines: .res 2          ; total line count in buffer
src_top:        .res 2          ; buffer upper bound (for REPL i command)
src_bot:        .res 2          ; buffer lower bound (for REPL i command)
clip_base:      .res 2          ; the clipboard's start: [clip_base, buf_base),
                                ;   below the text (gap_buffer.md)
cb_cnt:         .res 2          ; _xfer / gb_clip_put: a byte count
cb_crs:         .res 2          ; _xfer: the CRs it passed
cb_len:         .res 2          ; gb_clip_put: the clipboard's length

; ── CODE ─────────────────────────────────────────────────────────────
.segment "CODE"

; ── gb_init — reset gap-buffer state ──────────────────────────
; Pure leaf — no symbol-table contact.  Callers:
;   * ed_ensure_init (cold init via main.s, lazy init elsewhere)
;   * editor.s::ed_init (full reset on ed_new / disk load —
;     publishes workend via update_workend afterwards).
.proc gb_init
        lda #<BUF_END
        sta gap_lo
        sta gap_hi
        sta buf_base
        sta clip_base
        sta ed_top_ptr
        sta src_top
        sta src_bot
        lda #>BUF_END
        sta gap_lo+1
        sta gap_hi+1
        sta buf_base+1
        sta clip_base+1
        sta ed_top_ptr+1
        sta src_top+1
        sta src_bot+1
.ifdef PLATFORM_M65
        lda #BANK_SRC           ; the four live in the source region: their
        sta gap_lo+2            ; banks are set here only, every other site
        sta gap_hi+2            ; rewrites their offsets (gap_buffer.md)
        sta buf_base+2
        sta ed_top_ptr+2
.endif
        lda #0
        sta ed_dirty
        sta ed_total_lines+1
.ifdef PLATFORM_M65
        sta gap_lo+3            ; their megabyte
        sta gap_hi+3
        sta buf_base+3
        sta ed_top_ptr+3
.endif
        lda #1
        sta ed_total_lines
        rts                     ; leaf — caller publishes workend
.endproc

; ── ed_ensure_init — lazy init guard ─────────────────────────
; Called by the sequential reader, ed_insert_string, and editor.s's
; enter_editor to ensure the buffer is initialised on first use.
; Gap-state only (calls gb_init) — the L4 rendering state is
; BSS-zero at cold boot and doesn't need touching on lazy init.
; ed_new (in editor.s) handles the full reset via ed_init instead
; when the user explicitly asks for a fresh buffer.
.proc ed_ensure_init
        lda ed_total_lines
        ora ed_total_lines+1
        bne @done
        jsr gb_init
@done:  rts
.endproc

; ── define_ws_syms — register both workspace symbols ─────────
; workstart = $0800 (fixed), workend = buf_base - 1 (dynamic).
; Called from main.s cold-init and asm_src.s::asm_assemble after
; sym_clear.  Falls through into update_workend for the workend
; half — saves bytes vs. two independent procs.
.proc define_ws_syms
        ; workstart ($0800, fixed)
.ifdef PLATFORM_M65
        lda #0                  ; 32-bit values: a zero upper word
        sta sym_val+2
        sta sym_val+3
.endif
        lda #<WORKSTART
        sta sym_val
        lda #>WORKSTART
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
.ifdef PLATFORM_C64
        lda clip_base           ; below the text and its clipboard
        sec
        sbc #1
        sta sym_val
        lda clip_base+1
        sbc #0
        sta sym_val+1
.else
        lda #<PROG_HI           ; the program region's end: the source
        sta sym_val             ; is not in bank 0
        lda #>PROG_HI
        sta sym_val+1
        lda #0                  ; a zero upper word
        sta sym_val+2
        sta sym_val+3
.endif
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
@grow:  ; Check clip_base - 256 >= BUF_FLOOR (the clipboard below the
        ; text moves down with it).  BUF_FLOOR is page-aligned, so the
        ; hi-byte check is sufficient
        lda clip_base+1
        cmp #>(BUF_FLOOR) + 1   ; clip_base.hi > BUF_FLOOR.hi?
        jcc @no_room
        ; pre_size = gap_lo - clip_base: the clipboard and the pre-gap text
        lda gap_lo
        sec
        sbc clip_base
        sta ed_tmp              ; pre_size lo
        lda gap_lo+1
        sbc clip_base+1
        sta ed_tmp+1            ; pre_size hi

        ; both bases down a page
        dec clip_base+1
        dec buf_base+1

        ; Copy pre-gap text from old_base to new_base (ascending copy)
        ; pre_size in ed_tmp/ed_tmp+1
        ; Source: buf_base + $0100 (the old buf_base)
        ; Dest:   buf_base (the new buf_base)
        lda ed_tmp
        ora ed_tmp+1
        beq @no_copy            ; pre_size = 0, skip copy

        ; Setup copy: src = clip_base+$100 (old base), dst = clip_base (new)
        ; We need to copy ed_tmp bytes ascending
        ; Use save_ptr as src, ed_scr as dst (both are scratch-safe here)
        lda clip_base
        sta ed_scr              ; dst lo (new_base)
        sta save_ptr            ; src lo = same base
        lda clip_base+1
        sta ed_scr+1            ; dst hi
        clc
        adc #1
        sta save_ptr+1          ; src hi = buf_base+1 + 1
.ifdef PLATFORM_M65
        lda #BANK_SRC
        sta ed_scr+2
        sta save_ptr+2
        lda #0
        sta ed_scr+3
        sta save_ptr+3
.endif

        ; Copy ed_tmp bytes ascending (src → dst)
        ; pre_size could be > 256, use page loop
        ldx ed_tmp+1            ; full pages
        ldy #0
        ; Copy full pages
        cpx #0
        beq @partial
@page:  FAR_LDA save_ptr
        FAR_STA ed_scr
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
@rem:   FAR_LDA save_ptr
        FAR_STA ed_scr
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
        ; Update gap_lo = new clip_base + pre_size
        lda clip_base
        clc
        adc ed_tmp              ; pre_size lo
        sta gap_lo
        lda clip_base+1
        adc ed_tmp+1
        sta gap_lo+1

        ; gap_hi stays: the gap grew by 256 below (it was empty, so gap_hi
        ; = the old gap_lo = the new gap_lo + 256)

        jsr _src_bot            ; src_bot + workend symbol

@have_room:
        sec                     ; success
        rts
@no_room:                       ; the document wins: a clipboard dropped,
        lda clip_base           ;   then grow again
        cmp buf_base
        bne @drop
        lda clip_base+1
        cmp buf_base+1
        beq @full
@drop:  jsr gb_clip_drop
        jmp @grow
@full:  clc                     ; failure
        rts
.endproc

; ── The clipboard below the text (gap_buffer.md § The clipboard below
; the text): [clip_base, buf_base); the growth carries it.

.macro SRC_BANKS                ; save_ptr and ed_scr into the source bank
        FAR_BANK save_ptr, BANK_SRC
        FAR_BANK ed_scr, BANK_SRC
.endmacro

.segment "BSS"
cb_cr:  .res 1                  ; gb_clip_copy: 1 = add a CR
.segment "CODE"

; ── _src_bot — src_bot = clip_base, the workend symbol republished.
_src_bot:
        lda clip_base
        sta src_bot
        lda clip_base+1
        sta src_bot+1
        jmp update_workend

; ── gb_clip_drop — the clipboard emptied: clip_base = buf_base.
gb_clip_drop:
        lda buf_base
        sta clip_base
        lda buf_base+1
        sta clip_base+1
        jmp _src_bot

; ── _back_n — save_ptr = gap_lo - ed_tmp: the n bytes before the cursor;
; both pointers' banks the source bank.  Clobbers A.
_back_n:
        lda gap_lo
        sec
        sbc ed_tmp
        sta save_ptr
        lda gap_lo+1
        sbc ed_tmp+1
        sta save_ptr+1
        SRC_BANKS
        rts

; ── _xfer — ed_tmp bytes from (save_ptr) to (ed_scr), ascending;
; cb_crs = the CRs among them.  Clobbers A, Y, save_ptr, ed_scr, cb_cnt.
.proc _xfer
        lda ed_tmp
        sta cb_cnt
        lda ed_tmp+1
        sta cb_cnt+1
        lda #0
        sta cb_crs
        sta cb_crs+1
@lp:    lda cb_cnt
        ora cb_cnt+1
        beq @r
        ldy #0
        FAR_LDA save_ptr
        FAR_STA ed_scr
        cmp #$0D
        bne :+
        inc cb_crs
        bne :+
        inc cb_crs+1
:       inc save_ptr
        bne :+
        inc save_ptr+1
:       inc ed_scr
        bne :+
        inc ed_scr+1
:       lda cb_cnt
        bne :+
        dec cb_cnt+1
:       dec cb_cnt
        jmp @lp
@r:     rts
.endproc

; ── gb_clip_copy — In: ed_tmp = n, C=1: add a CR.  C=1 out: the n bytes
; before the cursor (and the CR) are the clipboard, below buf_base; C=0:
; it would reach below BUF_FLOOR, nothing changed.
.proc gb_clip_copy
        lda #0
        rol
        sta cb_cr
        lda buf_base            ; the new clip_base: buf_base - n - cr
        sec
        sbc ed_tmp
        tay
        lda buf_base+1
        sbc ed_tmp+1
        tax
        bcc @no                 ; n > buf_base
        tya
        sec
        sbc cb_cr
        bcs :+
        dex
:       cpx #>BUF_FLOOR
        bcc @no                 ; below the floor (page-aligned)
        sta clip_base
        sta ed_scr
        stx clip_base+1
        stx ed_scr+1
        jsr _back_n
        jsr _xfer
        lda cb_cr
        beq :+
        lda #$0D
        ldy #0
        FAR_STA ed_scr
:       jsr _src_bot
        sec
        rts
@no:    clc
        rts
.endproc

; ── gb_delete — In: ed_tmp = n.  The n bytes before the cursor deleted,
; ed_total_lines less their CRs, ed_dirty set.
.proc gb_delete
        jsr _back_n
        lda save_ptr            ; gap_lo back; the bytes counted in place
        sta gap_lo
        sta ed_scr
        lda save_ptr+1
        sta gap_lo+1
        sta ed_scr+1
        jsr _xfer
        lda ed_total_lines
        sec
        sbc cb_crs
        sta ed_total_lines
        lda ed_total_lines+1
        sbc cb_crs+1
        sta ed_total_lines+1
        lda #1
        sta ed_dirty
        rts
.endproc

; ── gb_clip_put — C=1: the clipboard's bytes inserted at the cursor (one
; gb_insert each; the growth may move the clipboard, so its pointer is
; taken afresh per byte), the clipboard kept; C=0: empty, or the gap and
; the growth left cannot hold it — nothing changed.
.proc gb_clip_put
        lda buf_base            ; cb_len = the clipboard's length
        sec
        sbc clip_base
        sta cb_len
        lda buf_base+1
        sbc clip_base+1
        sta cb_len+1
        ora cb_len
        beq @no
        lda gap_hi              ; room = the gap + the pages it can grow
        sec
        sbc gap_lo
        tax
        lda gap_hi+1
        sbc gap_lo+1
        clc
        adc clip_base+1
        bcs @fits               ; past 64 K: room enough
        sec
        sbc #>BUF_FLOOR
        cmp cb_len+1
        bne :+
        cpx cb_len
:       bcc @no
@fits:  lda #0
        sta cb_cnt
        sta cb_cnt+1
@lp:    lda clip_base
        clc
        adc cb_cnt
        sta ed_scr
        lda clip_base+1
        adc cb_cnt+1
        sta ed_scr+1
        FAR_BANK ed_scr, BANK_SRC
        ldy #0
        FAR_LDA ed_scr
        jsr gb_insert
        inc cb_cnt
        bne :+
        inc cb_cnt+1
:       lda cb_cnt
        cmp cb_len
        bne @lp
        lda cb_cnt+1
        cmp cb_len+1
        bne @lp
        sec
        rts
@no:    clc
        rts
.endproc

; ── gb_rev — In: save_ptr = the first byte (the text before the gap),
; A/X = the end (exclusive).  The bytes between reversed in place.
; Clobbers A, Y, ed_scr, save_ptr.
.proc gb_rev
        sta ed_scr              ; ed_scr = the last byte
        stx ed_scr+1
        lda ed_scr
        bne :+
        dec ed_scr+1
:       dec ed_scr
        SRC_BANKS
@lp:    lda save_ptr+1          ; while save_ptr < ed_scr
        cmp ed_scr+1
        bcc @swap
        bne @r
        lda save_ptr
        cmp ed_scr
        bcs @r
@swap:  ldy #0
        FAR_LDA save_ptr
        pha
        FAR_LDA ed_scr
        FAR_STA save_ptr
        pla
        FAR_STA ed_scr
        inc save_ptr
        bne :+
        inc save_ptr+1
:       lda ed_scr
        bne :+
        dec ed_scr+1
:       dec ed_scr
        jmp @lp
@r:     rts
.endproc

; ══════════════════════════════════════════════════════════
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
        FAR_STA gap_lo
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
        FAR_LDA gap_lo
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
        FAR_LDA gap_hi          ; byte at gap_hi
        FAR_STA gap_lo          ; copy to gap_lo
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
        FAR_LDA gap_lo
        FAR_STA gap_hi
@done:  rts
.endproc

; ══════════════════════════════════════════════════════════
; ══════════════════════════════════════════════════════════
; ── ed_insert_string — insert PETSCII string at cursor ────────
; Input: A/X = text pointer
;
; Protects the text pointer across each gb_insert call: gb_insert
; may trigger gb_ensure_room, which uses save_ptr as scratch during
; its pre-gap block-copy.  For inputs ≤ 256 bytes the first growth
; has pre_size = 0 and skips the copy entirely, so save_ptr is
; untouched — which is why this stack-save dance only matters for
; > 256-byte strings.  Test-only: no production caller (keystrokes
; and load_insert call gb_insert directly).  gb_insert's carry is
; ignored — on a full buffer the rest of the string is dropped.
; Pinned by TestGbEnsureRoom::test_growth_preserves_content.
.proc ed_insert_string
        sta save_ptr            ; reuse save_ptr as text pointer
        stx save_ptr+1
        jsr ed_ensure_init
@loop:
        FAR_BANK save_ptr, BANK_CSE     ; the text, in CSE's view (again
                                        ; after gb_insert's growth used it)
        ldy #0
        FAR_LDA save_ptr
        beq @done               ; NUL terminator
        tax                     ; byte to insert → X (gb_insert takes A)
        lda save_ptr+1
        pha
        lda save_ptr
        pha                     ; stash text ptr on stack
        txa
        jsr gb_insert
        pla
        sta save_ptr
        pla
        sta save_ptr+1          ; restore text ptr
        inc save_ptr
        bne @loop
        inc save_ptr+1
        jmp @loop
@done:  rts
.endproc

; ══════════════════════════════════════════════════════════
; ══════════════════════════════════════════════════════════
; ── Sequential reader — for source assembler ─────────────────

; ── ed_read_rewind — reset read pointer to start ──────────────
.proc ed_read_rewind
        jsr ed_ensure_init
        lda buf_base
        sta read_ptr
        lda buf_base+1
        sta read_ptr+1
        FAR_BANK read_ptr, BANK_SRC
        rts
.endproc

; ══════════════════════════════════════════════════════════
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
        FAR_LDA read_ptr        ; byte in A; survives the inc-pair below (no A-touch)
        inc read_ptr
        bne :+
        inc read_ptr+1
:       ldx #0
        rts
@eof:
        lda #$FF
        tax                     ; A=$FF, X=$FF → -1
        rts
.endproc

; ══════════════════════════════════════════════════════════
; ══════════════════════════════════════════════════════════
; ed_read_line — copy the next line (up to CR or EOF) into A/X.
; The buffer is LINE_MAX + 1 bytes: at most LINE_MAX characters, then
; the NUL.  Returns: A = length (0–LINE_MAX), X = 0 when the line fit
;          whole, X = LINE_MAX (non-zero, positive) when characters
;          past the LINE_MAX-th were dropped; A = X = $FF at EOF.
.proc ed_read_line
        sta ed_scr              ; buf lo
        stx ed_scr+1            ; buf hi
        FAR_BANK ed_scr, BANK_CSE       ; the caller's line buffer
        lda #0
        sta ed_tmp              ; len = 0
        sta ed_tmp+1            ; dropped = 0
@loop:
        jsr ed_read_byte
        cpx #$FF
        beq @eof_check          ; got EOF from read_byte
        ; Got a byte in A
        cmp #$0D
        beq @eol                ; end of line
        ldy ed_tmp              ; current len
        cpy #LINE_MAX
        bcs @drop               ; buffer full: drop the byte
        FAR_STA ed_scr
        inc ed_tmp              ; ++len (1..LINE_MAX, never 0)
        bne @loop
@drop:  sty ed_tmp+1            ; Y = LINE_MAX: "dropped"
        bcs @loop               ; always (C=1)
@eof_check:
        ; EOF — return what we have, or -1 if nothing
        lda ed_tmp
        beq @eof_empty
@eol:
        ; NUL-terminate, return len and the dropped flag
        ldy ed_tmp
        lda #0
        FAR_STA ed_scr
        lda ed_tmp
        ldx ed_tmp+1
        rts
@eof_empty:
        lda #$FF
        tax                     ; -1
        rts
.endproc

; ══════════════════════════════════════════════════════════
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
; ══════════════════════════════════════════════════════════
; ── gb_home — move gap to start of current line ──────────────
.proc gb_home
        FAR_BANK ed_tmp, BANK_SRC       ; ed_tmp walks the buffer here
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
        FAR_LDA ed_tmp
        cmp #$0D
        beq @done
        jsr gb_cursor_left
        jmp @loop
@done:  rts
.endproc
