; dasm_test_stub.s — Test harness for the bit-slice disassembler
;
; Memory layout:
;   $0300-$030F: instruction bytes (placed by Python)
;   $F0:         al_cpu value (set by Python before call)
;
; Entry: JSR dasm_test_entry
;   Calls _dasm_insn with addr=$0300
;   Returns instruction length in A
;   Result string at _dasm_buf (NUL-terminated PETSCII)

        .export dasm_test_entry

        .import _dasm_insn

        .exportzp al_cpu

.segment "ZEROPAGE"
al_cpu:         .res 1          ; CPU mode: 0=6502 1=6510 2=65C02

.segment "CODE"

.proc dasm_test_entry
        ; Call _dasm_insn with addr = $0B00 (__fastcall__: A=lo, X=hi)
        lda #$00
        ldx #$0B
        jsr _dasm_insn
        ; A = instruction length, dasm_buf has the string
        rts
.endproc
