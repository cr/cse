; asm_core_test_stub.s — minimal stub for the asm_core test bundle
;
; The asm_core bundle links the full single-line assembler pipeline:
;   zp + opcode_lookup + asm_line + au_mode
;   + expr + symtab + mem
;   + mn_vars + mn7 + mn7_tables + mn_modes + mn_asm_tables + mn_classify
;
; This bundle is self-contained: mem.s provides real kernal_bank_out/in
; (toggles $01 bit 1, harmless in py65).  zp.s defines all ZP variables.
;
; This stub provides:
;   - __CODE_RUN__ linker symbol for mem.s
;   - asm_pass flag for au_mode.s forward-ref handling
;
; Symbol resolution uses .lbl files (debug build with -g), so no
; .addr forcing is needed to make symbols visible.
;
; Shared by: test_au_mode.py, test_asm_line.py

        .setcpu "6502"

        ; Linker symbols consumed by mem.s
        .export __CODE_RUN__    : absolute = $4000

        ; asm_pass flag (au_mode.s forward-ref handling)
        .export asm_pass

        .segment "BSS"

asm_pass:       .res 1          ; 0 = pass 0 (default for unit tests)
