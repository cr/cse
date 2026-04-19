; ─────────────────────────────────────────────────────────────────────────────
; asm_err.s — Assembler error state + longjmp unwind (Phase 21 Move 2)
;
; Owns the error-signalling contract for the single-line assembler
; pipeline: asm_line -> addr_mode -> _au_read_val -> expr_eval.  Any
; error anywhere in that chain lands here; the handler unwinds the
; 6502 SP to the snapshot taken at asm_line entry and returns 0 to
; asm_line's caller in one step (longjmp-style).
;
;   asm_syntax_error / asm_error
;       Generic entry (syntax error, unknown mnemonic, invalid mode).
;       Clears asm_expr_err; shared tail runs the SP restore + bank_in.
;
;   asm_expr_error
;       Expression-eval error entry.  Sets asm_expr_err=1 first, then
;       falls into the shared tail via a BIT-abs skip (the lda #0 at
;       asm_error is consumed as a BIT operand, preserving A=1).
;
; The three entry points share the same body; only the asm_expr_err
; value differs.  Callers distinguish "syntax vs expression" error
; types by testing asm_expr_err after a zero return from asm_line.
;
; Moved here from asm_line.s in Phase 21 Move 2 so the error handler
; is not defined inside the module that calls it — that was the
; asm_line↔addr_mode mutual-recursion + opcode_lookup→asm_line
; back-edges which the refactor eliminates.
;
;   _asm_saved_sp (ZP, owned by zp.s) — SP snapshot taken by asm_line
;                                       at entry.  Read by the unwind.
;   asm_expr_err  (BSS)  — set by asm_expr_error; cleared by asm_error.
;   asm_pass      (BSS)  — 0 = pass 0 (sizing), 1 = pass 1 (emit).
;                          Read by addr_mode (_au_read_val forward-ref
;                          handling); written by asm_src at each pass.
; ─────────────────────────────────────────────────────────────────────────────

        .setcpu "6502"

        .export asm_error, asm_syntax_error, asm_expr_error
        .export asm_expr_err, asm_pass

        .importzp _asm_saved_sp
        .import kernal_bank_in

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

asm_expr_err:   .res 1          ; nonzero if last asm_error was expr eval
asm_pass:       .res 1          ; 0 = pass 0, 1 = pass 1

; ── CODE ─────────────────────────────────────────────────────
.segment "CODE"

; ── asm_error / asm_syntax_error / asm_expr_error ─────────────
; Jumped to (not called) by _asm_line_core / mode_parse / expr_eval
; on any assembler error.  Restores the 6502 stack to the snapshot
; saved at asm_line entry, banks the KERNAL back in, returns 0.
;
; asm_expr_error sets asm_expr_err = 1; the other two clear it.
asm_expr_error:
        lda #1
        .byte $2C               ; BIT abs — skip the next lda #0
asm_error:
asm_syntax_error:
        lda #0
        sta asm_expr_err
        ldx _asm_saved_sp
        txs                     ; restore SP (unwind nested jsrs)
        jsr kernal_bank_in      ; pair the bank_out from asm_line entry
        lda #0
        tax                     ; return 0 (A=lo, X=hi=0)
        rts
