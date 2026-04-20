; dasm_test_stub.s — Test harness for the bit-slice disassembler
;
; Memory layout:
;   $0B00-$0B0F  instruction bytes (placed by Python before JSR)
;   asm_cpu      CPU mode (set by Python before call, from zp.s)
;
; Entry: JSR dasm_test_entry
;   Calls dasm_insn with addr = $0B00 (A=lo, X=hi).
;   Returns instruction length in A.
;   Result string at dasm_buf (NUL-terminated PETSCII).
;
; The dasm bundle links real mem.s, so dasm.s's kernal_bank_out /
; kernal_bank_in imports resolve against production code — no mock.
; This stub provides only linker scaffolding (the __CODE_RUN__ symbol
; required by mem.s) and the thin JSR-dasm_insn wrapper.

        .export dasm_test_entry
        .export __CODE_RUN__    : absolute = $4000

        .import dasm_insn

        .segment "CODE"

.proc dasm_test_entry
        lda #$00
        ldx #$0B
        jsr dasm_insn
        rts
.endproc
