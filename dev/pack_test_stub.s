; pack_test_stub.s — Test harness for pack_name in symtab.s
;
; Entry: JSR pack_test_entry
;   sym_name (ZP ptr): points to PETSCII NUL-terminated string
;   On return: pack_buf (6 bytes BSS) contains packed name

        .export pack_test_entry
        .exportzp sym_name, sym_val, sym_wide

        .import _pack_name
        .import pack_buf

        .segment "ZEROPAGE"
sym_name:  .res 2
sym_val:   .res 2    ; unused but symtab.s imports it
sym_wide:  .res 1    ; unused but symtab.s imports it

        .segment "CODE"
; Re-export pack_buf so test Python can find its address
        .export pack_buf_addr
        .segment "RODATA"
pack_buf_addr: .word pack_buf

        .segment "CODE"
pack_test_entry:
        jsr _pack_name
        rts
