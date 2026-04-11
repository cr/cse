; asm_core_test_stub.s — minimal stub for the asm_core test bundle
;
; The asm_core bundle links the full single-line assembler pipeline:
;   asm_vars + opcode_lookup + asm_line + au_mode
;   + expr + symtab + mem
;   + mn_vars + mn7 + mn7_tables + mn_modes + mn_asm_tables + mn_classify
;
; This bundle is self-contained: mem.s provides real kernal_bank_out/in
; (toggles $01 bit 1, harmless in py65).  The only external symbols
; needed are __CODE_RUN__ and __ZP_LAST__ (consumed by mem.s).
;
; This stub provides:
;   - BRK error handlers (asm_syntax_error detected by test runner)
;   - .addr words to force key symbols into ld65 exports list
;   - __CODE_RUN__ / __ZP_LAST__ linker symbols for mem.s
;
; Shared by: test_au_mode.py, test_asm_line.py

        .setcpu "6502"

        ; Linker symbols consumed by mem.s
        .export __CODE_RUN__    : absolute = $4000
        .export __ZP_LAST__     : absolute = $0020

        ; ZP exports consumed by mem.s
        .exportzp buf_base

        ; asm_pass flag (au_mode.s forward-ref handling)
        .export asm_pass

        ; Force symbols into ld65 exports list (consumed by conftest.py)
        .import _asm_line_core
        .importzp _asm_saved_sp
        .import mode_parse
        .import asm_skip_ws

        .segment "ZEROPAGE"

buf_base:       .res 2          ; editor gap buffer base (consumed by mem.s)

        .segment "BSS"

asm_pass:       .res 1          ; 0 = pass 0 (default for unit tests)

        .segment "CODE"

        ; Unreachable data — forces symbols into the map's Exports list
        .addr   _asm_line_core
        .addr   _asm_saved_sp
        .addr   mode_parse
        .addr   asm_skip_ws
