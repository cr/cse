; symtab.s — Symbol table: hash table with linear probing
;
; Fixed 128-slot hash array in BSS.  Name strings stored in a
; separate pool (caller manages pool allocation).
;
; Interface (all via ZP):
;   sym_define:  in: sym_name (ptr), sym_val (16-bit), sym_wide (0=ZP, 1=ABS)
;                out: C=1 if table full
;   sym_lookup:  in: sym_name (ptr)
;                out: sym_val (16-bit), sym_wide (0/1), C=1 if not found
;   sym_clear:   (no args) — wipes all slots
;
; Hash: h = 0; for each char: h = h * 5 + char
; Slot = h & (SYM_SLOTS - 1).  Linear probe on collision.
; hash byte = 0 means empty slot.

        .export _sym_define, _sym_lookup, _sym_clear, _sym_count

        .importzp sym_name, sym_val, sym_wide

; ── Constants ────────────────────────────────────────────
SYM_SLOTS  = 128
SYM_MASK   = SYM_SLOTS - 1
ENTRY_SIZE = 6              ; hash(1) + value(2) + name_ptr(2) + wide(1)

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

; Name string pool: for this initial implementation, names are
; stored by the CALLER (in source buffer or line buffer).
; name_ptr in each slot points to the caller's string.
; This works for assembly (source is stable during both passes).
; Future: copy names into a managed pool.

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
        ; 128 × 6 = 768 = 3 × 256 — exactly 3 pages, done
        rts
.endproc

; ═════════════════════════════════════════════════════════
; _sym_count — return count in A (for C callers)
; ═════════════════════════════════════════════════════════
.proc _sym_count
        lda _st_count
        ldx #0
        rts
.endproc

; ═════════════════════════════════════════════════════════
; compute_hash — hash the string at (sym_name)
;   Result in _st_hash and A.  Clobbers Y.
;   Hash = 0; for each char: hash = hash * 5 + char
;   Final: if hash == 0, set hash = 1 (0 = empty marker)
; ═════════════════════════════════════════════════════════
.proc compute_hash
        lda #0
        tay                     ; Y = string index
@loop:  lda (sym_name),y
        beq @done               ; NUL terminator
        ; tmp = hash; hash = hash*4 + hash + char = hash*5 + char
        pha                     ; save char
        lda _st_hash
        asl
        asl                     ; *4
        clc
        adc _st_hash            ; *5
        sta _st_hash
        pla                     ; char
        clc
        adc _st_hash
        sta _st_hash
        iny
        bne @loop               ; always (names < 256 chars)
@done:  lda _st_hash
        bne :+
        inc _st_hash            ; hash 0 → 1 (0 = empty sentinel)
:       lda _st_hash
        rts
.endproc

; ═════════════════════════════════════════════════════════
; entry_ptr — compute pointer to sym_table[_st_idx]
;   Sets _st_ptr.  Clobbers A.
;   entry address = sym_table + _st_idx * 6
; ═════════════════════════════════════════════════════════
.proc entry_ptr
        ; _st_ptr = sym_table + _st_idx * 6
        ; idx * 6 = idx * 4 + idx * 2 (max 127 * 6 = 762 = $02FA)
        lda _st_idx
        asl                     ; × 2
        sta _st_ptr             ; save lo(×2)
        lda #0
        rol                     ; hi(×2)
        sta _st_ptr+1
        lda _st_ptr
        asl                     ; lo(×4)
        sta _st_nptr            ; temp lo(×4)
        lda _st_ptr+1
        rol                     ; hi(×4)
        sta _st_nptr+1          ; temp hi(×4)
        ; ×6 = ×4 + ×2
        lda _st_ptr
        clc
        adc _st_nptr
        sta _st_ptr
        lda _st_ptr+1
        adc _st_nptr+1
        sta _st_ptr+1
        ; Now add sym_table base address
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
; names_equal — compare string at (sym_name) with string
;   pointed to by entry's name_ptr field.
;   Entry: _st_ptr points to the entry.
;   Returns Z=1 if equal, Z=0 if not.  Clobbers A, Y.
; ═════════════════════════════════════════════════════════
.proc names_equal
        ; Load name_ptr from entry (offset 3-4)
        ldy #3
        lda (_st_ptr),y
        sta _st_nptr
        iny
        lda (_st_ptr),y
        sta _st_nptr+1

        ; Compare char by char
        ldy #0
@cmp:   lda (sym_name),y
        cmp (_st_nptr),y
        bne @ne                 ; mismatch
        cmp #0
        beq @eq                 ; both NUL → equal
        iny
        bne @cmp                ; always (< 256 chars)
@eq:    lda #0                  ; Z=1
        rts
@ne:    lda #1                  ; Z=0
        rts
.endproc

; ═════════════════════════════════════════════════════════
; sym_define — define or redefine a symbol
;   In:  sym_name (ZP ptr), sym_val (ZP 16-bit)
;   Out: C=0 ok, C=1 table full
; ═════════════════════════════════════════════════════════
.proc _sym_define
        lda #0
        sta _st_hash
        jsr compute_hash        ; _st_hash = hash of sym_name

        ; Start probing at slot = hash & mask
        lda _st_hash
        and #SYM_MASK
        sta _st_idx

        ldx #SYM_SLOTS          ; probe counter (max = all slots)
@probe:
        jsr entry_ptr           ; _st_ptr → current entry

        ; Check if slot is empty (hash byte = 0)
        ldy #0
        lda (_st_ptr),y
        beq @empty              ; empty slot → insert here

        ; Slot occupied — check if same hash
        cmp _st_hash
        bne @next               ; different hash → skip

        ; Same hash — compare names
        jsr names_equal
        bne @next               ; different name → collision, keep probing

        ; Same name → redefine (update value, don't increment count)
        jmp @store_val

@empty:
        ; Check if table is full
        lda _st_count
        cmp #SYM_SLOTS
        bcs @full

        ; Write hash byte
        lda _st_hash
        ldy #0
        sta (_st_ptr),y

        ; Write name pointer
        lda sym_name
        ldy #3
        sta (_st_ptr),y
        lda sym_name+1
        iny
        sta (_st_ptr),y

        inc _st_count

@store_val:
        ; Write value + wide flag
        lda sym_val
        ldy #1
        sta (_st_ptr),y
        lda sym_val+1
        iny
        sta (_st_ptr),y
        lda sym_wide
        ldy #5
        sta (_st_ptr),y

        clc                     ; success
        rts

@next:
        ; Linear probe: next slot
        inc _st_idx
        lda _st_idx
        and #SYM_MASK
        sta _st_idx
        dex
        bne @probe

@full:
        sec                     ; table full
        rts
.endproc

; ═════════════════════════════════════════════════════════
; sym_lookup — look up a symbol by name
;   In:  sym_name (ZP ptr)
;   Out: sym_val (ZP 16-bit), C=0 found, C=1 not found
; ═════════════════════════════════════════════════════════
.proc _sym_lookup
        lda #0
        sta _st_hash
        jsr compute_hash

        lda _st_hash
        and #SYM_MASK
        sta _st_idx

        ldx #SYM_SLOTS
@probe:
        jsr entry_ptr

        ; Empty slot → not found
        ldy #0
        lda (_st_ptr),y
        beq @notfound

        ; Check hash
        cmp _st_hash
        bne @next

        ; Check name
        jsr names_equal
        bne @next

        ; Found — read value + wide flag
        ldy #1
        lda (_st_ptr),y
        sta sym_val
        iny
        lda (_st_ptr),y
        sta sym_val+1
        ldy #5
        lda (_st_ptr),y
        sta sym_wide
        clc                     ; found
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
