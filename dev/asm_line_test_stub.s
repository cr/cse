; asm_line_test_stub.s — links against asm_line.o and dependencies for
; host-side testing via py65.
;
; asm_line.s provides asm_error, asm_syntax_error, and line_asm.
; The test runner (conftest.py) pre-sets _asm_saved_sp from Python
; so that asm_error can restore the SP on failure.
;
; This stub provides:
;   kernal_bank_out/in — no-op in test environment
; and forces line_asm + _asm_saved_sp into the ld65 exports list.

        .setcpu "6502"

        .export kernal_bank_out, kernal_bank_in

        .import line_asm
        .import _asm_saved_sp

        .segment "CODE"

kernal_bank_out:
kernal_bank_in:
        rts                     ; no-op in test environment

        ; Force symbols into ld65 exports list (consumed by conftest.py)
        .addr   line_asm
        .addr   _asm_saved_sp
