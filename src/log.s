; ─────────────────────────────────────────────────────────────────────────────
; log.s — Standardised logging API (Phase 21 Move 3)
;
; Owns the logging primitives used across the corpus:
;
;   log_open(Y = level)   — emit ";<level>" at cursor
;   log_close()           — clear rest of line, newline
;   log_line(Y, A/X)      — log_open + io_puts(content) + log_close
;   log_err / log_warn / log_info   — convenience wrappers
;   puts_imm              — inline-string print target for the `puts` macro
;
; Three levels (constants in log.inc):
;   LOG_ERR  = '?'   →  ";?"   error
;   LOG_WARN = '!'   →  ";!"   warning
;   LOG_INFO = ' '   →  "; "   info
;
; Caller owns cursor positioning (typically `jsr newline` at handler entry
; to leave the prompt line intact).  `log_close` does `io_clear_eol +
; newline` so output flows line by line without callers adding explicit
; newlines.
;
; All logging primitives live here.  disk.s / editor.s / asm_src.s /
; main.s / repl.s import from this module; no module above Layer 2
; reaches sideways for log-type output.
; ─────────────────────────────────────────────────────────────────────────────

        .setcpu "6502"

        .export log_line, log_open, log_close
        .export log_err, log_warn, log_info
        .export log_err_eol, log_close_eol
        .export puts_imm
        .export seg_line, prg_line, free_line
        .export info_line, info_line_head, info_line_tail

        .import io_putc, io_puts, io_puthex4, io_putdec_pd, io_repc
        .import io_clear_eol, newline
        .import scr_lo, scr_hi
        .importzp rp_tmp, rp_ptr, rp_ptr2
        .importzp rp_addr, rp_cnt, rp_save, rp_save2
        .importzp rp_next_lo, _info_mode
        .import str_free_suf, str_tag_prg

.include "log.inc"
.include "macros.inc"           ; `puts` macro (calls puts_imm below)

; C64 screen editor registers (matches repl.s definitions)
CUR_COL      = $D3
CUR_ROW      = $D6
SCREEN_WIDTH = 40

.segment "CODE"

; ── Convenience entry points ─────────────────────────────
; Avoid `ldy #LOG_*` at every call site.  A/X = content ptr.
log_err:
        ldy #LOG_ERR
        jmp log_line
log_warn:
        ldy #LOG_WARN
        jmp log_line
log_info:
        ldy #LOG_INFO
        ; fall through to log_line

; ═══════════════════════════════════════════════════════════
; log_line — complete log line
;   Y = level char, A/X = content string ptr
;   Clobbers: A, X, Y, rp_tmp / rp_tmp+1
;     (log_open itself is rp_tmp-safe; log_line parks the content
;      pointer there across the log_open call.)
; ═══════════════════════════════════════════════════════════
.proc log_line
        sta rp_tmp
        stx rp_tmp+1
        jsr log_open
        lda rp_tmp
        ldx rp_tmp+1
        jsr io_puts
        jmp log_close
.endproc

; ── log_open — open a log line at current cursor ─────────
; Y = level char
; Clobbers: A
log_open:
        tya
        pha
        lda #';'
        jsr io_putc
        pla
        jmp io_putc

; ── log_close — close an open log line ───────────────────
; Clears to end of line, then advances to next row.
log_close:
        jsr io_clear_eol
        jmp newline

; ═══════════════════════════════════════════════════════════
; puts_imm — print an inline RODATA string pointer.
;
; Called by the `puts str` macro:
;     jsr puts_imm
;     .word str_label
;
; Reads the str pointer from the two bytes immediately after
; the jsr, advances the stacked return address past them, and
; tail-calls io_puts.
;
; ⚠ FOOTGUN: Clobbers rp_tmp (plus A, X, Y).  Callers that
;   need to preserve a pointer across a `puts` should park it
;   on the 6502 stack (pha/pla), NOT in rp_tmp — and NOT in
;   rp_tmp2, which is only 1 byte wide.
; ═══════════════════════════════════════════════════════════
puts_imm:
        ; Stack on entry: [ret_lo][ret_hi] where ret = (.word) - 1
        ; (JSR pushes PC-1, and PC after `jsr puts_imm` points at .word.)
        pla
        sta rp_tmp
        pla
        sta rp_tmp+1            ; rp_tmp = ret = (.word) - 1
        ; Bump rp_tmp by 2 so it points at (.word) + 1 = str_hi byte.
        ; That address, re-pushed, makes RTS return to (.word) + 2 =
        ; the instruction after the .word argument.
        clc
        lda rp_tmp
        adc #2
        sta rp_tmp
        bcc :+
        inc rp_tmp+1
:       lda rp_tmp+1
        pha                     ; push adjusted ret_hi first ...
        lda rp_tmp
        pha                     ; ... then ret_lo (top of stack)
        ; rp_tmp = (.word) + 1 — the str_hi byte.
        ldy #0
        lda (rp_tmp),y          ; A = str_hi
        tax                     ; X = str_hi
        ; Step rp_tmp back by 1 to reach (.word) = str_lo byte.
        lda rp_tmp
        bne :+
        dec rp_tmp+1
:       dec rp_tmp
        lda (rp_tmp),y          ; A = str_lo
        jmp io_puts             ; tail call; rts returns to caller+5

; ═══════════════════════════════════════════════════════════
; log_err_eol — newline + error line + clear prompt row
; Used for error-only exits from command handlers.
; ═══════════════════════════════════════════════════════════
log_err_eol:
        jsr newline
        jsr log_err
        jmp io_clear_eol

; ═══════════════════════════════════════════════════════════
; log_close_eol — close log line + clear prompt row
; ═══════════════════════════════════════════════════════════
log_close_eol:
        jsr log_close
        jmp io_clear_eol

; ═══════════════════════════════════════════════════════════
; Range info line family — "; TAG  AAAA-BBBB NNNNNb [free]"
;
;   info_line       complete "; TAG  AAAA-BBBB desc" line
;                     rp_save2=inv, rp_ptr2=tag, rp_addr=lo,
;                     rp_cnt=hi, rp_ptr=desc
;   info_line_head  prefix "; TAG  AAAA-BBBB " + screen-row snapshot
;   info_line_tail  pad + optional highlight + newline
;   free_line       "; TAG  AAAA-BBBB NNNNNb free"  (cmd_info rows,
;                     highlight flag from _info_mode)
;   prg_line        "; prg  AAAA-BBBB NNNNNb"       (exclusive end
;                     convention; decrements rp_cnt then falls into
;                     seg_line)
;   seg_line        "; TAG  AAAA-BBBB NNNNNb"       (inclusive end;
;                     caller pre-loads rp_ptr2=tag)
;
; Moved from repl.s in Phase 21.1 Move 3B alongside the scratch-pool
; ZP promotion.  asm_src.s's single `jsr seg_line` now resolves here.
; ═══════════════════════════════════════════════════════════

info_line:
        jsr info_line_head
        lda rp_ptr
        ldx rp_ptr+1
        jsr io_puts
        jmp info_line_tail

info_line_head:
        ; save screen addr for invert pass later
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_next_lo
        lda scr_hi,x
        sta rp_next_lo+1

        lda #0
        sta CUR_COL
        lda #';'
        jsr io_putc
        lda #' '
        jsr io_putc

        ; print tag
        lda rp_ptr2
        ldx rp_ptr2+1
        jsr io_puts

        ; pad tag to 5 cols (4 chars + 1 space separator)
        ldy #0
@tlen:  lda (rp_ptr2),y
        beq @tpad
        iny
        cpy #4
        bcc @tlen
@tpad:  tya
        eor #$FF
        clc
        adc #5+1                ; X = 5 - len
        tax
        lda #' '
        jsr io_repc

        ; print lo-hi + space
        lda rp_addr
        ldx rp_addr+1
        jsr io_puthex4
        lda #'-'
        jsr io_putc
        lda rp_cnt
        ldx rp_cnt+1
        jsr io_puthex4
        lda #' '
        jmp io_putc

free_line:
        ; compute rp_save2 from _info_mode (0=highlight, 1=no highlight)
        lda _info_mode
        eor #1
        sta rp_save2
        jsr _range_core         ; head + "NNNNNb"
        puts str_free_suf       ; " free"
        jmp info_line_tail

prg_line:
        lda #<str_tag_prg
        sta rp_ptr2
        lda #>str_tag_prg
        sta rp_ptr2+1
        lda #0
        sta rp_save2
        ; convert exclusive end → inclusive
        lda rp_cnt
        bne :+
        dec rp_cnt+1
:       dec rp_cnt
        ; fall through to seg_line

seg_line:
        jsr _range_core
        ; fall through to info_line_tail

info_line_tail:
        ; save col position
        lda CUR_COL
        sta rp_save

        ; copy screen pointer to ZP rp_ptr for indirect access
        lda rp_next_lo
        sta rp_ptr
        lda rp_next_lo+1
        sta rp_ptr+1

        ; inv or normal pad
        lda rp_save2
        beq @normal_pad

        ; inv: set bit 7 on AAAA-BBBB only (cols 7-15)
        ldy #7
@inv_lp:
        cpy #16
        bcs @inv_done
        lda (rp_ptr),y
        ora #$80
        sta (rp_ptr),y
        iny
        bne @inv_lp
@inv_done:

@normal_pad:
        ; fill rest with $20 (space)
        ldy rp_save
@npad:  cpy #SCREEN_WIDTH
        bcs @done
        lda #$20
        sta (rp_ptr),y
        iny
        bne @npad

@done:  jmp newline

; ── _range_core — info_line_head + right-aligned size + 'b' ──
_range_core:
        jsr info_line_head
        ; size = hi - lo + 1
        lda rp_cnt
        sec
        sbc rp_addr
        pha
        lda rp_cnt+1
        sbc rp_addr+1
        tax
        pla
        clc
        adc #1
        bcc :+
        inx
:       sec                     ; right-aligned
        jsr io_putdec_pd
        lda #'b'
        jmp io_putc
