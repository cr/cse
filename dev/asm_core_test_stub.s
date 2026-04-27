; asm_core_test_stub.s — minimal stub for the asm_core test bundle
;
; The asm_core bundle links the full single-line assembler pipeline:
;   zp + opcode_lookup + asm_line + asm_err + addr_mode
;   + expr + symtab + mem
;   + mn_vars + mn7 + mn7_tables + mn_modes + mn_asm_tables + mn_classify
;
; This bundle is self-contained: mem.s provides real kernal_bank_out/in
; (toggles $01 bit 1, harmless in py65).  zp.s defines all ZP variables.
; asm_err.s provides the asm_pass flag + error unwind.
;
; This stub provides only:
;   - __CODE_RUN__ linker symbol for mem.s
;
; Symbol resolution uses .lbl files (debug build with -g), so no
; .addr forcing is needed to make symbols visible.
;
; Shared by: test_asm_line.py, test_addr_mode.py, test_opcode_lookup.py,
;            test_expr.py, test_asm_err.py (all use the same asm_core bundle).

        .setcpu "6502"

        ; Linker symbols consumed by mem.s
        .export __CODE_RUN__    : absolute = $4000

        ; Stub log_warn — addr_mode.s imports log_warn for the
        ; ACC label-shadow emission.  The asm_core bundle doesn't
        ; link the real log.s; this stub increments _warn_witness
        ; on each call so tests can assert emission count.
        ; (s_a_shadow lives in strings.s, already in the bundle.)
        .export log_warn
        .export _warn_witness

.segment "BSS"
_warn_witness:  .res 1          ; incremented on each log_warn call

.segment "CODE"
log_warn:
        inc _warn_witness
        rts
