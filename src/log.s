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
; Moved here from repl.s in Phase 21 Move 3 so that disk.s / editor.s /
; asm_src.s / main.s stop reaching up into repl.s for logging primitives.
; repl.s still owns its prompt-row-specific wrappers (log_err_eol,
; log_close_eol) and the range-line formatter family (seg_line /
; prg_line / free_line) — those have deep coupling with REPL scratch
; BSS.
; ─────────────────────────────────────────────────────────────────────────────

        .setcpu "6502"

        .export log_line, log_open, log_close
        .export log_err, log_warn, log_info
        .export puts_imm

        .import io_putc, io_puts, io_clear_eol, newline
        .importzp rp_tmp

.include "log.inc"

.segment "CODE"

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
        jmp log_line

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
