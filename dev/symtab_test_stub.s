; symtab_test_stub.s — Test harness for symtab.s
;
; Memory layout:
;   $0300-$033F: name string buffer (placed by Python)
;   $F0/$F1:     sym_name pointer (set by Python)
;   $F2/$F3:     sym_val (input for define, output for lookup)
;   $F4:         result: 0=ok, 1=error (carry flag captured)
;
; Entry points:
;   test_define:   JSR sym_define, capture carry → $F4
;   test_lookup:   JSR sym_lookup, capture carry → $F4, copy sym_val → $F2/$F3
;   test_clear:    JSR sym_clear

        .export test_define, test_lookup, test_clear
        .exportzp sym_name, sym_val
        .exportzp sp

        .import _sym_define, _sym_lookup, _sym_clear

; ── ZP ───────────────────────────────────────────────────
.segment "ZEROPAGE"
sp:        .res 2      ; cc65 C stack pointer (needed by cse_popax if used)
sym_name:  .res 2      ; pointer to NUL-terminated name string
sym_val:   .res 2      ; value (16-bit)

.segment "CODE"

; ── test_define: set sym_name + sym_val, call sym_define ──
.proc test_define
        jsr _sym_define
        lda #0
        bcc :+
        lda #1          ; C=1 → table full
:       sta $F4
        rts
.endproc

; ── test_lookup: set sym_name, call sym_lookup ────────────
.proc test_lookup
        jsr _sym_lookup
        lda #0
        bcc :+
        lda #1          ; C=1 → not found
:       sta $F4
        ; sym_val already updated by sym_lookup
        rts
.endproc

; ── test_clear ────────────────────────────────────────────
.proc test_clear
        jmp _sym_clear
.endproc
