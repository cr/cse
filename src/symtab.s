; symtab.s — Symbol table: hash table with linear probing
;
; Entry: hash(1) + value(2) + name_ptr(2) + scope(1) = 6 bytes
;   hash:      8-bit, 0 = empty slot (valid hashes forced to 1+)
;   value:     16-bit symbol value
;   name_ptr:  points to PETSCII NUL-terminated string (source or snapshot)
;   scope:     bit 7 = ZP/ABS (0=ZP, 1=ABS)
;              bit 6 = is_local
;              bits 5-0 = parent slot if local
;
; Names compared case-insensitively (uppercase folded to lowercase).
;
; Interface (all via ZP):
;   sym_define:  in: sym_name (ptr), sym_val (16-bit), sym_wide (0=ZP, 1=ABS)
;                out: C=1 if table full
;   sym_lookup:  in: sym_name (ptr)
;                out: sym_val (16-bit), sym_wide, C=1 if not found
;   sym_clear:   (no args) — wipes all slots
;   sym_count:   return count in A

        .export _sym_define, _sym_lookup, _sym_clear, _sym_count

        .importzp sym_name, sym_val, sym_wide

; ── Constants ────────────────────────────────────────────
SYM_SLOTS  = 128
SYM_MASK   = SYM_SLOTS - 1
ENTRY_SIZE = 6              ; hash(1) + value(2) + name_ptr(2) + scope(1)

; ── ZP scratch ───────────────────────────────────────────
.segment "ZEROPAGE"
_st_hash:    .res 1         ; computed hash
_st_idx:     .res 1         ; current probe index
_st_ptr:     .res 2         ; pointer to current entry
_st_nptr:    .res 2         ; pointer for name comparison
_st_count:   .res 1         ; number of defined symbols

; ── BSS ──────────────────────────────────────────────────
.segment "BSS"
sym_table:   .res SYM_SLOTS * ENTRY_SIZE   ; 128 × 6 = 768 bytes

.segment "CODE"

; ═════════════════════════════════════════════════════════
; sym_clear — zero all slots, reset count
; ═════════════════════════════════════════════════════════
.proc _sym_clear
        lda #0
        sta _st_count
        tax
@clr:   sta sym_table,x
        sta sym_table+$100,x
        sta sym_table+$200,x
        inx
        bne @clr
        rts
.endproc

; ═════════════════════════════════════════════════════════
; _sym_count — return count in A
; ═════════════════════════════════════════════════════════
.proc _sym_count
        lda _st_count
        ldx #0
        rts
.endproc

; ═════════════════════════════════════════════════════════
; compute_hash — hash the name at (sym_name), case-insensitive
;   Result in _st_hash.  h = 0 forced to 1.
;   Clobbers A, Y.
; ═════════════════════════════════════════════════════════
.proc compute_hash
        lda #0
        sta _st_hash
        tay
@loop:  lda (sym_name),y
        beq @done
        ; fold uppercase to lowercase
        jsr fold_char
        ; hash = hash * 5 + char
        pha
        lda _st_hash
        asl
        asl
        clc
        adc _st_hash
        sta _st_hash
        pla
        clc
        adc _st_hash
        sta _st_hash
        iny
        bne @loop
@done:  lda _st_hash
        bne :+
        inc _st_hash
:       rts
.endproc

; ═════════════════════════════════════════════════════════
; fold_char — fold PETSCII uppercase ($C1-$DA) to lowercase ($41-$5A)
;   Input/output: A. Preserves Y.
; ═════════════════════════════════════════════════════════
.proc fold_char
        cmp #$C1
        bcc @done
        cmp #$DB
        bcs @done
        ; $C1-$DA → $41-$5A
        sec
        sbc #$80
@done:  rts
.endproc

; ═════════════════════════════════════════════════════════
; entry_ptr — compute pointer to sym_table[_st_idx]
;   Sets _st_ptr. Clobbers A.
;   entry address = sym_table + _st_idx * 6
; ═════════════════════════════════════════════════════════
.proc entry_ptr
        lda _st_idx
        asl                     ; × 2
        sta _st_ptr
        lda #0
        rol
        sta _st_ptr+1
        lda _st_ptr
        asl                     ; lo(×4)
        sta _st_nptr
        lda _st_ptr+1
        rol
        sta _st_nptr+1
        ; ×6 = ×4 + ×2
        lda _st_ptr
        clc
        adc _st_nptr
        sta _st_ptr
        lda _st_ptr+1
        adc _st_nptr+1
        sta _st_ptr+1
        ; add sym_table base
        lda _st_ptr
        clc
        adc #<sym_table
        sta _st_ptr
        lda _st_ptr+1
        adc #>sym_table
        sta _st_ptr+1
        rts
.endproc

; ═════════════════════════════════════════════════════════
; names_equal — compare (sym_name) with entry's name_ptr
;   Case-insensitive.  Returns Z=1 if equal.
;   Clobbers A, Y, _st_nptr.
; ═════════════════════════════════════════════════════════
.proc names_equal
        ; Load name_ptr from entry (offset 3-4)
        ldy #3
        lda (_st_ptr),y
        sta _st_nptr
        iny
        lda (_st_ptr),y
        sta _st_nptr+1
        ; Compare strings byte by byte, case-insensitive
        ldy #0
@loop:  lda (_st_nptr),y
        jsr fold_char
        pha                     ; save folded entry char
        lda (sym_name),y
        jsr fold_char
        tsx
        cmp $0101,x             ; compare with stacked entry char
        bne @diff_pop
        ; Chars matched — pop stacked byte
        pla
        ; If both NUL, strings are equal
        lda (sym_name),y
        beq @equal
        iny
        bne @loop
@equal: lda #0                  ; Z=1
        rts
@diff_pop:
        pla                     ; clean stacked byte
        lda #1                  ; Z=0
        rts
.endproc

; ═════════════════════════════════════════════════════════
; _sym_define
;   In:  sym_name (ptr), sym_val (16-bit), sym_wide (0/1)
;   Out: C=1 if table full
; ═════════════════════════════════════════════════════════
.proc _sym_define
        jsr compute_hash

        lda _st_hash
        and #SYM_MASK
        sta _st_idx
        ldx #SYM_SLOTS          ; probe counter

@probe: jsr entry_ptr
        ; Check if slot is empty (hash byte = 0)
        ldy #0
        lda (_st_ptr),y
        beq @empty

        ; Slot occupied — check if same name (redefine)
        cmp _st_hash
        bne @next
        jsr names_equal
        bne @next

        ; Same name — update value + scope
        jmp @store_val

@empty:
        ; Check capacity
        lda _st_count
        cmp #SYM_SLOTS
        bcs @full

        ; Store hash byte
        lda _st_hash
        ldy #0
        sta (_st_ptr),y

        ; Store name_ptr
        lda sym_name
        ldy #3
        sta (_st_ptr),y
        lda sym_name+1
        iny
        sta (_st_ptr),y

        inc _st_count

@store_val:
        ; Store value
        lda sym_val
        ldy #1
        sta (_st_ptr),y
        lda sym_val+1
        iny
        sta (_st_ptr),y

        ; Store scope byte (bit 7 = ZP/ABS from sym_wide)
        lda sym_wide
        beq :+
        lda #$80                ; ABS flag
:       ldy #5
        sta (_st_ptr),y

        clc
        rts

@next:
        inc _st_idx
        lda _st_idx
        and #SYM_MASK
        sta _st_idx
        dex
        bne @probe

@full:  sec
        rts
.endproc

; ═════════════════════════════════════════════════════════
; _sym_lookup
;   In:  sym_name (ptr)
;   Out: sym_val (16-bit), sym_wide, C=0 found, C=1 not found
; ═════════════════════════════════════════════════════════
.proc _sym_lookup
        jsr compute_hash

        lda _st_hash
        and #SYM_MASK
        sta _st_idx
        ldx #SYM_SLOTS

@probe: jsr entry_ptr
        ldy #0
        lda (_st_ptr),y
        beq @notfound

        cmp _st_hash
        bne @next

        jsr names_equal
        bne @next

        ; Found — read value
        ldy #1
        lda (_st_ptr),y
        sta sym_val
        iny
        lda (_st_ptr),y
        sta sym_val+1

        ; Read scope byte → sym_wide (bit 7 → 0 or 1)
        ldy #5
        lda (_st_ptr),y
        asl                     ; bit 7 → carry
        lda #0
        rol                     ; carry → bit 0
        sta sym_wide            ; 0=ZP, 1=ABS

        clc
        rts

@next:
        inc _st_idx
        lda _st_idx
        and #SYM_MASK
        sta _st_idx
        dex
        bne @probe

@notfound:
        sec
        rts
.endproc
