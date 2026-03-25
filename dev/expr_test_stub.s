; expr_test_stub.s — Test harness for expr.s
;
; Entry: JSR expr_test_entry
;   $F0/$F1 = pointer to input string (PETSCII, NUL-terminated)
;   On return: A = result (0=ok, 1=error)
;              $F2/$F3 = result value (16-bit)
;              $F4/$F5 = updated string pointer (advanced past parsed input)

        .export expr_test_entry
        .export popax, pushax
        .exportzp sp

        .import _expr_eval

; We simulate the C calling convention:
;   expr_eval(uint8_t **pp, uint16_t *result)
;   __fastcall__: result_ptr in A/X, pp on C stack

INPTR   = $F0           ; 2 bytes: pointer to input string
RESULT  = $F2           ; 2 bytes: result value
UPDPTR  = $F4           ; 2 bytes: updated input pointer

.segment "ZEROPAGE"
sp:     .res 2          ; cc65 software stack pointer
pp:     .res 2          ; pointer-to-pointer for expr_eval

.segment "BSS"
cstack: .res 32         ; mini C stack for pushax/popax

.segment "CODE"

; ── Minimal cc65 runtime stubs ─────────────────────────────
; pushax: push A/X onto C stack at (sp)
.proc pushax
        ldy sp
        dey
        dey
        sty sp
        sta (sp),y      ; lo byte
        pha
        txa
        iny
        sta (sp),y      ; hi byte
        pla
        rts
.endproc

; popax: pop A/X from C stack at (sp)
.proc popax
        ldy #0
        lda (sp),y      ; lo
        tax
        iny
        lda (sp),y      ; hi
        pha              ; save hi
        ; bump sp by 2
        lda sp
        clc
        adc #2
        sta sp
        bcc :+
        inc sp+1
:       pla              ; hi → X, lo → A
        tay              ; save hi in Y temporarily
        txa              ; lo → A
        sty @tmp         ; hi
        ldx @tmp         ; hi → X
        rts
@tmp:   .byte 0
.endproc

; ── Test entry point ───────────────────────────────────────
.proc expr_test_entry
        ; Init C stack pointer → cstack + 32 (grows down)
        lda #<(cstack + 32)
        sta sp
        lda #>(cstack + 32)
        sta sp+1

        ; Set up pp → INPTR
        lda #<INPTR
        sta pp
        lda #>INPTR
        sta pp+1

        ; Push pp (first arg)
        lda pp
        ldx pp+1
        jsr pushax

        ; Pass &RESULT (second arg, __fastcall__)
        lda #<RESULT
        ldx #>RESULT
        jsr _expr_eval

        ; Copy INPTR → UPDPTR for easy reading
        pha
        lda INPTR
        sta UPDPTR
        lda INPTR+1
        sta UPDPTR+1
        pla
        rts
.endproc
