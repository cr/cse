; au_mode_test_stub.s – links against au_mode.o for host-side testing
;
; Provides asm_syntax_error as a BRK so the test driver can detect parse errors
; by checking for opcode $00 at the current PC.
;
; Build:
;   ca65 --cpu 6502 src/au_mode.s      -o build/au_mode.o
;   ca65 --cpu 6502 dev/au_mode_test_stub.s -o build/au_mode_test_stub.o
;   ld65 -C dev/test.cfg build/au_mode.o build/au_mode_test_stub.o \
;        -o build/au_mode_test.bin --dbgfile build/au_mode_test.dbg

        .setcpu "6502"

        .export asm_syntax_error

        .segment "CODE"

asm_syntax_error:
        brk                     ; $00 – detected by test runner as parse error
