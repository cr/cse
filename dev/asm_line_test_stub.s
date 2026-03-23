; asm_line_test_stub.s — links against asm_line.o and dependencies for
; host-side testing via py65.
;
; Provides al_error and au_syntax_error as BRK (opcode $00) so the
; test runner can detect errors by checking the CPU halted at a BRK address.
;
; Build (see Makefile test-bins target):
;   ca65 --cpu 6502  src/asm_vars.s     -o build/asm_vars.o
;   ca65 --cpu 6502  src/parse_hex.s    -o build/parse_hex.o
;   ca65 --cpu 6502  src/opcode_lookup.s -o build/opcode_lookup.o
;   ca65 --cpu 6502  src/asm_line.s     -o build/asm_line.o
;   ca65 --cpu 6502  src/au_mode.s      -o build/au_mode.o  (reuse existing)
;   ca65 --cpu 6502  src/mn_vars.s      -o build/mn_vars.o
;   ca65 --cpu 6502  src/mn7.s          -o build/mn7.o
;   ca65 --cpu 6502  src/mn7_tables.s   -o build/mn7_tables.o
;   ca65 --cpu 6502  src/mn_modes.s     -o build/mn_modes.o
;   ca65 --cpu 6502  src/mn_asm_tables.s -o build/mn_asm_tables.o
;   ca65 --cpu 6502  src/mn_classify.s  -o build/mn_classify.o
;   ca65 --cpu 6502  dev/asm_line_test_stub.s -o build/asm_line_test_stub.o
;   ld65 -C dev/test.cfg  build/asm_vars.o build/parse_hex.o \
;        build/opcode_lookup.o build/asm_line.o build/au_mode.o \
;        build/mn_vars.o build/mn7.o build/mn7_tables.o \
;        build/mn_modes.o build/mn_asm_tables.o build/mn_classify.o \
;        build/asm_line_test_stub.o \
;        -o build/asm_line_test.bin -m build/asm_line_test.map

        .setcpu "6502"

        .export al_error
        .export au_syntax_error     ; also needed by au_mode.s

        ; Import al_line_asm so ld65 lists it in the map "Exports list by
        ; name" section.  The address word is emitted as data so ca65 keeps
        ; the reference; the test runner reads it from the map file.
        .import al_line_asm

        .segment "CODE"

al_error:
au_syntax_error:
        brk                     ; $00 — detected by test runner as error

        ; ── al_line_asm address word (for map-file export resolution) ──────
        ; Unreachable at run-time; consumed by conftest.py via the map file.
        .addr   al_line_asm     ; forces al_line_asm into the exports list
