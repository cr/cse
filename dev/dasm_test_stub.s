; dasm_test_stub.s — Test harness for the bit-slice disassembler
;
; Memory layout:
;   $0300-$030F: instruction bytes (placed by Python)
;   $F0:         al_cpu value (set by Python before call)
;
; Entry: JSR dasm_test_entry
;   Calls dasm_insn with addr=$0300
;   Returns instruction length in A
;   Result string at dasm_buf (NUL-terminated PETSCII)

        .export dasm_test_entry
        .export kernal_bank_out, kernal_bank_in

        .import dasm_insn

        .exportzp al_cpu

.segment "ZEROPAGE"
al_cpu:         .res 1          ; CPU mode: 0=6502 1=6510 2=65C02

.segment "CODE"

.proc dasm_test_entry
        ; Call dasm_insn with addr = $0B00 (__fastcall__: A=lo, X=hi)
        lda #$00
        ldx #$0B
        jsr dasm_insn
        ; A = instruction length, dasm_buf has the string
        rts
.endproc

; ── Bank helpers — mirror the symtab.s versions ──
; In py65 there is no actual KERNAL ROM gating, but we still
; toggle $01 bit 1 so tests can witness the bank state after
; dasm_insn returns.  No kernal_out flag here — the dasm path
; never participates in a batch.
kernal_bank_out:
        sei
        lda $01
        and #$FD                ; clear bit 1
        sta $01
        rts

kernal_bank_in:
        lda $01
        ora #$02                ; set bit 1
        sta $01
        cli
        rts
