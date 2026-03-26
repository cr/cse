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
        .export _pack_name, pack_buf

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
pack_buf:    .res 6                         ; packed name output (6 bytes)

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

; ═════════════════════════════════════════════════════════
; _pack_name — pack string at (sym_name) into 6 bytes at pack_buf
;
; 6-bit encoding: 0=end, 1-26=a-z, 27-36=0-9, 37=.
; First char: 5-bit (1-27). Bit 7 of byte 0 = ZP flag (cleared here).
; Case folds uppercase ($C1-$DA) to lowercase ($41-$5A).
; Max 8 chars; rest ignored. Short names zero-padded.
;
; Layout:
;   B0: [0  c1₄ c1₃ c1₂ c1₁ c1₀ c2₅ c2₄]  (bit7=ZP, cleared)
;   B1: [c2₃ c2₂ c2₁ c2₀ c3₅ c3₄ c3₃ c3₂]
;   B2: [c3₁ c3₀ c4₅ c4₄ c4₃ c4₂ c4₁ c4₀]
;   B3: [c5₅ c5₄ c5₃ c5₂ c5₁ c5₀ c6₅ c6₄]
;   B4: [c6₃ c6₂ c6₁ c6₀ c7₅ c7₄ c7₃ c7₂]
;   B5: [c7₁ c7₀ c8₅ c8₄ c8₃ c8₂ c8₁ c8₀]
;
; Clobbers: A, X, Y, _st_nptr (ZP scratch)
; ═════════════════════════════════════════════════════════
.proc _pack_name
        ; First: read up to 8 chars, encode to 6-bit codes in pack_buf
        ; (temporarily use pack_buf as 8 code bytes, then bit-pack in place)

        ; Clear pack_buf to 0
        lda #0
        ldx #5
@clr:   sta pack_buf,x
        dex
        bpl @clr

        ; Read and encode up to 8 chars into a temp area on the stack
        ; We'll use pack_buf[0..5] as scratch, but first collect codes
        ; in a different way: process char by char, shifting into pack_buf.
        ;
        ; Strategy: process pairs of 3 chars → 2 bytes, but the first
        ; group is special (5-bit first char).
        ;
        jmp @start_pack

        ; ── encode_char subroutine (called from pack code below) ──
@encode_char:
        ; Input: A = PETSCII char
        ; Output: A = 6-bit code (0 if end/invalid)
        beq @ec_zero            ; NUL → 0
        ; Lowercase a-z ($41-$5A) → 1-26
        cmp #$41
        bcc @ec_other
        cmp #$5B
        bcs @ec_upper
        sec
        sbc #$40                ; $41→1, $5A→26
        rts
@ec_upper:
        ; Uppercase A-Z ($C1-$DA) → fold to 1-26
        cmp #$C1
        bcc @ec_other
        cmp #$DB
        bcs @ec_zero
        sec
        sbc #$C0                ; $C1→1, $DA→26
        rts
@ec_other:
        ; Period ($2E) → 37 (check BEFORE digits since $2E < $30)
        cmp #$2E
        beq @ec_dot
        ; Digits 0-9 ($30-$39) → 27-36
        cmp #$30
        bcc @ec_zero
        cmp #$3A
        bcs @ec_zero
        sec
        sbc #$30
        clc
        adc #27                 ; $30→27, $39→36
        rts
@ec_dot:
        lda #37
        rts
@ec_zero:
        lda #0
        rts

@start_pack:
        ; Read chars 0-7 forward, encode, pack into pack_buf
        ; Use _st_nptr as a pointer to an 8-byte temp area.
        ; Actually, simplest: read and encode each char, then
        ; pack directly using shifts.

        ; Clear pack_buf
        lda #0
        sta pack_buf
        sta pack_buf+1
        sta pack_buf+2
        sta pack_buf+3
        sta pack_buf+4
        sta pack_buf+5

        ; Process char 1 (5 bits into byte 0, bits 6-2)
        ; First char: 1-26=a-z, 27=dot (5-bit encoding)
        ldy #0
        lda (sym_name),y
        jsr @encode_char
        cmp #37                 ; dot in 6-bit encoding?
        bne :+
        lda #27                 ; remap to 5-bit dot code
:       ; c1 in A (5-bit, 0-27)
        asl                     ; shift left 2 to position at bits 6-2
        asl
        sta pack_buf            ; B0 = [0 c1₄ c1₃ c1₂ c1₁ c1₀ 0 0]
        jmp @char2              ; skip trampoline

@to_pad:
        jmp @pad

        ; Process char 2
@char2: ; 6 bits: 2 into byte 0 bits 1-0, 4 into byte 1 bits 7-4
        ldy #1
        lda (sym_name),y
        beq @to_pad             ; NUL → done
        jsr @encode_char
        ; c2 in A (6-bit)
        pha
        lsr                     ; c2 >> 4 → top 2 bits
        lsr
        lsr
        lsr
        ora pack_buf            ; merge into B0 bits 1-0
        sta pack_buf
        pla
        asl                     ; c2 << 4 → bottom 4 bits into B1 top
        asl
        asl
        asl
        sta pack_buf+1          ; B1 = [c2₃ c2₂ c2₁ c2₀ 0 0 0 0]

        ; Process char 3 (6 bits: 4 into byte 1 bits 3-0, 2 into byte 2 bits 7-6)
        ldy #2
        lda (sym_name),y
        beq @pad
        jsr @encode_char
        pha
        lsr                     ; c3 >> 2 → top 4 bits
        lsr
        ora pack_buf+1
        sta pack_buf+1          ; B1 = [c2₃ c2₂ c2₁ c2₀ c3₅ c3₄ c3₃ c3₂]
        pla
        asl                     ; c3 << 6 → bottom 2 bits into B2 top
        asl
        asl
        asl
        asl
        asl
        sta pack_buf+2          ; B2 = [c3₁ c3₀ 0 0 0 0 0 0]

        ; Process char 4 (6 bits all into byte 2 bits 5-0)
        ldy #3
        lda (sym_name),y
        beq @pad
        jsr @encode_char
        ora pack_buf+2
        sta pack_buf+2          ; B2 = [c3₁ c3₀ c4₅ c4₄ c4₃ c4₂ c4₁ c4₀]

        ; Chars 5-8: same pattern as chars 1-4 but into bytes 3-5
        ; (except char 5 is 6 bits not 5, so it's like char 2 in position)
        ; Actually: bytes 3-5 pack c5-c8 identically to how bytes 0-2 pack c2-c4
        ; with c5 being a full 6-bit char (not 5-bit like c1).

        ; Process char 5 (6 bits: all 6 into byte 3 bits 7-2)
        ldy #4
        lda (sym_name),y
        beq @pad
        jsr @encode_char
        asl
        asl
        sta pack_buf+3          ; B3 = [c5₅ c5₄ c5₃ c5₂ c5₁ c5₀ 0 0]

        ; Process char 6 (6 bits: 2 into byte 3 bits 1-0, 4 into byte 4 bits 7-4)
        ldy #5
        lda (sym_name),y
        beq @pad
        jsr @encode_char
        pha
        lsr
        lsr
        lsr
        lsr
        ora pack_buf+3
        sta pack_buf+3
        pla
        asl
        asl
        asl
        asl
        sta pack_buf+4

        ; Process char 7 (6 bits: 4 into byte 4 bits 3-0, 2 into byte 5 bits 7-6)
        ldy #6
        lda (sym_name),y
        beq @pad
        jsr @encode_char
        pha
        lsr
        lsr
        ora pack_buf+4
        sta pack_buf+4
        pla
        asl
        asl
        asl
        asl
        asl
        asl
        sta pack_buf+5

        ; Process char 8 (6 bits all into byte 5 bits 5-0)
        ldy #7
        lda (sym_name),y
        beq @pad
        jsr @encode_char
        ora pack_buf+5
        sta pack_buf+5

@pad:   ; pack_buf already zero-padded from the initial clear
        rts
.endproc
