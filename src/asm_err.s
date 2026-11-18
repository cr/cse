; ─────────────────────────────────────────────────────────────────────────────
; Owner: doc/modules/asm_err.md
; asm_err.s — Assembler error state + longjmp unwind
;
; Owns the error-signalling contract for the single-line assembler
; pipeline: asm_line -> addr_mode -> _au_read_val -> expr_eval.  Any
; error anywhere in that chain lands here; the handler unwinds the
; 6502 SP to the snapshot taken at asm_line entry and returns 0 to
; asm_line's caller in one step (longjmp-style).
;
; Three error categories are represented by a single byte
; (asm_err_code) so callers can dispatch the right user-visible tag.
;
;     code | entry point          | meaning             | repl tag
;     -----+----------------------+---------------------+-----------
;     0    | asm_error            | generic syntax /    | ;?syntax
;          | asm_syntax_error     | invalid mode /      |
;          |                      | unknown mnemonic    |
;     1    | asm_expr_error       | expression eval     | ;?expr <detail>
;          |                      | (undefined symbol,  |
;          |                      | overflow, paren, …) |
;     2    | asm_cpu_error        | CPU-gate rejection  | ;?cpu
;          |                      | (PHY on 6502, …)    |
;
; All three entry points share one body: load the code (0/1/2) into
; A, store to asm_err_code, restore SP, bank KERNAL back in, return
; 0.  The BIT-abs trick lets the three entries share the store and
; the unwind tail.
;
; The handler lives in its own module, not in asm_line.s, so that
; addr_mode (which asm_line calls) can reach it without a back-edge
; to asm_line.
;
;   _asm_saved_sp (ZP, owned by zp.s) — SP snapshot taken by asm_line
;                                       at entry.  Read by the unwind.
;   asm_err_code  (BSS)  — 0/1/2 per the table above.  Written by
;                          every entry point; read by asm_src.s and
;                          repl.s for tag dispatch.
;   asm_pass      (BSS)  — 0 = pass 0 (sizing), 1 = pass 1 (emit).
;                          Read by addr_mode (_au_read_val forward-ref
;                          handling, shadow warning) and asm_src;
;                          written by asm_src at each pass.
; ─────────────────────────────────────────────────────────────────────────────

        .setcpu "6502"

        .export asm_error, asm_syntax_error
        .export asm_expr_error, asm_cpu_error
        .export asm_err_code, asm_pass

        .importzp _asm_saved_sp
        .import kernal_bank_in

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

asm_err_code:   .res 1          ; 0=syntax, 1=expr, 2=cpu (see header)
asm_pass:       .res 1          ; 0 = pass 0, 1 = pass 1

; ── CODE ─────────────────────────────────────────────────────
.segment "CODE"

; ── asm_*_error entry points ─────────────────────────────────
; Jumped to (not called) on any assembler error.  Loads the
; category code (0/1/2) into A via a BIT-abs skip cascade, stores
; to asm_err_code, restores SP, banks KERNAL in, returns 0.
asm_cpu_error:
        lda #2
        .byte $2C               ; BIT abs — skip the next lda #1
asm_expr_error:
        lda #1
        .byte $2C               ; BIT abs — skip the next lda #0
asm_error:
asm_syntax_error:
        lda #0
        sta asm_err_code
        ldx _asm_saved_sp
        txs                     ; restore SP (unwind nested jsrs)
        jsr kernal_bank_in      ; pair the bank_out from asm_line entry
        lda #0
        tax                     ; return 0 (A=lo, X=hi=0)
        rts
