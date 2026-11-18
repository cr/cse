; symtab.s — Symbol table: hash table with linear probing + name heap
; Owner: doc/modules/symtab.md
;
; Entry: hash(1) + value(2) + name_ptr(2) + scope(1) = 6 bytes
;   hash:      full 8-bit hash (all 256 values valid)
;   value:     16-bit symbol value
;   name_ptr:  pointer to name in heap ($0000 = empty slot)
;   scope:     bit 7 = ZP/ABS (0=ZP, 1=ABS)
;              bit 6 = pass stamp (sym_stamp at the define; sym_fwd)
;              bits 5-0 = reserved
;
; Names: PETSCII NUL-terminated strings copied into a heap on define.
; Compared case-insensitively (uppercase folded to lowercase).
; The heap persists until sym_clear — survives editing between assemblies.
;
; Interface (all via ZP):
;   sym_define:  in: sym_name (ptr), sym_val (16-bit), sym_wide (0=ZP, 1=ABS)
;                out: C=1 if table full or heap overflow
;   sym_lookup:  in: sym_name (ptr)
;                out: sym_val (16-bit), sym_wide (0/1), C=1 if not found
;   sym_clear:   (no args) — wipes all slots, resets heap

        .export sym_define, sym_lookup, sym_clear
        .export sym_stamp, sym_fwd

        .import kernal_bank_out
        .importzp kernal_out            ; zp.s

        .importzp sym_name, sym_val, sym_wide

; ── Constants ────────────────────────────────────────────
SYM_SLOTS  = 256
SYM_MASK   = SYM_SLOTS - 1         ; $FF
ENTRY_SIZE = 6              ; hash(1) + value(2) + name_ptr(2) + scope(1)

; Capacity = 256.  All slots are real entries: the empty marker is
; the value name_ptr=$0000 (unreachable since the heap lives at $E600+).
; Probe-wrap detection in sym_define / sym_lookup catches a full table.

; ── ZP scratch ───────────────────────────────────────────
.importzp _st_hash, _st_idx, _st_ptr, _st_nptr, _st_heap, _st_heap_base

; ── Banked RAM layout under KERNAL ROM ($E000–$FFFF) ─────
; $E000–$E5FF  sym_table   (256 slots × 6B = 1536 bytes)
; $E600–$EEFF  sym_heap    (2304 bytes, name heap)
; $EF00–$EFFF  earmarked for user stack snapshot (256B, unallocated)
; $F000–$F0FF  free (256B)
; $F100–$F4F1  KDATA tables (1010B)
; $F4F2–$F8D9  REPL screen save (1000B, editor.s)
; $F8DA–$FEFF  free (1574B)
; $FF00–$FF09  NMI trampoline (10 bytes)
; $FFFA–$FFFF  HW vectors (6B, fixed)
;
; Used: 5860 / 8192 bytes (71%).  Free: 2070 bytes (earmarked: 256).
SYM_P0       = $40              ; pass-0 stamp (scope bit 6)

.segment "BSS"
sym_stamp:   .res 1             ; in: stamp sym_define writes (asm_src)
sym_fwd:     .res 1             ; out of sym_lookup: entry stamp <> sym_stamp

sym_table    = $E000
SYM_HEAP     = $E600
SYM_HEAP_END = $EF00

.segment "CODE"

; ═════════════════════════════════════════════════════════
; sym_clear — zero all 256 slots (6 pages), reset heap
;   Pure writer: stores under KERNAL pass through to RAM,
;   so no banking is required.
; ═════════════════════════════════════════════════════════
.proc sym_clear
        lda #0
        tax
@clr:   sta sym_table,x
        sta sym_table+$100,x
        sta sym_table+$200,x
        sta sym_table+$300,x
        sta sym_table+$400,x
        sta sym_table+$500,x
        inx
        bne @clr
        ; Reset heap pointer to fixed base
        lda #<SYM_HEAP
        sta _st_heap
        sta _st_heap_base
        lda #>SYM_HEAP
        sta _st_heap+1
        sta _st_heap_base+1
        rts
.endproc

; ═════════════════════════════════════════════════════════
; compute_hash — hash the name at (sym_name), case-insensitive
;   Result in _st_hash. Full 8-bit range (0 is valid).
;   Clobbers A, Y.
; ═════════════════════════════════════════════════════════
.proc compute_hash
        lda #0
        sta _st_hash
        tay
@loop:  lda (sym_name),y
        beq @done
        jsr fold_char
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
@done:  rts                     ; hash 0 is valid — no forcing
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
        sec
        sbc #$80
@done:  rts
.endproc

; ═════════════════════════════════════════════════════════
; entry_ptr — compute pointer to sym_table[_st_idx]
;   Sets _st_ptr. Clobbers A.
; ═════════════════════════════════════════════════════════
.proc entry_ptr
        lda _st_idx
        asl                     ; A = lo(×2)
        tax                     ; X = lo(×2)
        lda #0
        rol                     ; A = hi(×2)
        sta _st_ptr+1
        txa                     ; A = lo(×2)
        asl                     ; A = lo(×4), C = carry
        sta _st_nptr
        lda _st_ptr+1           ; A = hi(×2)
        rol                     ; A = hi(×4)
        sta _st_nptr+1
        ; ×6 = ×2 + ×4 + sym_table base (lo base = $00)
        clc
        txa                     ; A = lo(×2)
        adc _st_nptr            ; A = lo(×6)
        sta _st_ptr
        lda _st_ptr+1           ; A = hi(×2)
        adc _st_nptr+1          ; + hi(×4) + carry
        adc #>sym_table         ; + base hi
        sta _st_ptr+1
        rts
.endproc

; ═════════════════════════════════════════════════════════
; is_empty — check if current entry is empty
;   Returns Z=1 if name_ptr == $0000 (empty slot).
;   Clobbers A, Y.
; ═════════════════════════════════════════════════════════
.proc is_empty
        ldy #3
        lda (_st_ptr),y
        iny
        ora (_st_ptr),y
        rts                     ; Z=1 if both bytes zero
.endproc

; ═════════════════════════════════════════════════════════
; names_equal — compare (sym_name) with entry's name_ptr
;   Case-insensitive.  Returns Z=1 if equal.
;   Clobbers A, Y, _st_nptr.
; ═════════════════════════════════════════════════════════
.proc names_equal
        ldy #3
        lda (_st_ptr),y
        sta _st_nptr
        iny
        lda (_st_ptr),y
        sta _st_nptr+1
        ldy #0
@loop:  lda (_st_nptr),y
        jsr fold_char
        pha
        lda (sym_name),y
        jsr fold_char
        tsx
        cmp $0101,x
        bne @diff_pop
        pla
        lda (sym_name),y
        beq @equal
        iny
        bne @loop
@equal: lda #0
        rts
@diff_pop:
        pla
        lda #1
        rts
.endproc

; ═════════════════════════════════════════════════════════
; heap_copy_name — copy string at (sym_name) into heap
;   Measures the name first: if name + NUL would end past
;   SYM_HEAP_END, returns C=1 having written nothing and left
;   _st_heap unchanged.  Otherwise copies it, returns its heap
;   address in _st_nptr, advances _st_heap past the NUL, C=0.
;   Heap is under KERNAL — caller must have it banked out.
;   Clobbers A, X, Y.
; ═════════════════════════════════════════════════════════
.assert <SYM_HEAP_END <> $FF, error, "heap_copy_name bound compare"
.proc heap_copy_name
        ldy #0
@len:   lda (sym_name),y
        beq @fit
        iny
        bne @len
@fit:   ; new end = _st_heap + Y + 1 (exclusive) must be <= SYM_HEAP_END
        tya
        sec                     ; +1 for the NUL byte
        adc _st_heap
        tax                     ; X = new end lo
        lda _st_heap+1
        adc #0                  ; A = new end hi
        cmp #>SYM_HEAP_END
        bcc @ok                 ; hi < limit → fits
        bne @overflow           ; hi > limit → refuse
        cpx #<SYM_HEAP_END+1
        bcs @overflow           ; lo > limit lo → refuse
@ok:    pha                     ; new end hi
        lda _st_heap
        sta _st_nptr            ; name address = old heap top
        lda _st_heap+1
        sta _st_nptr+1
        stx _st_heap
        pla
        sta _st_heap+1
        ldy #0
@copy:  lda (sym_name),y
        sta (_st_nptr),y
        beq @done               ; copied the NUL
        iny
        bne @copy
@done:  clc
        rts
@overflow:
        sec
        rts
.endproc

; ═════════════════════════════════════════════════════════
; sym_define
;   In:  sym_name (ptr), sym_val (16-bit), sym_wide (0/1)
;   Out: C=1 if table full
; ═════════════════════════════════════════════════════════
.proc sym_define
        jsr compute_hash

        lda _st_hash
        sta _st_idx             ; SYM_MASK=$FF: no masking needed for 8-bit ZP

        lda $01                 ; nesting guard: keep the caller's banking
        pha                     ; (restored on every exit, never bank_in)
        jsr kernal_bank_out

        ; Probe loop: linear probe, stop on empty or name match.
        ; Probe-wrap detection (@next) catches a fully populated table.
@probe: jsr entry_ptr
        jsr is_empty
        beq @empty

        ; Slot occupied — check hash then name
        ldy #0
        lda (_st_ptr),y
        cmp _st_hash
        bne @next
        jsr names_equal
        bne @next

        ; Same name — update value + scope (don't re-copy name)
        jmp @store_val

@empty:
        ; Empty slot found — copy name to heap (heap overflow → @full)
        jsr heap_copy_name
        bcs @full

        ; Store hash byte
        lda _st_hash
        ldy #0
        sta (_st_ptr),y

        ; Store name_ptr (from heap copy)
        lda _st_nptr
        ldy #3
        sta (_st_ptr),y
        lda _st_nptr+1
        iny
        sta (_st_ptr),y

@store_val:
        lda sym_val
        ldy #1
        sta (_st_ptr),y
        lda sym_val+1
        iny
        sta (_st_ptr),y

        ; Store scope byte (bit 7 = ZP/ABS, bit 6 = pass stamp)
        lda sym_wide
        beq :+
        lda #$80
:       ora sym_stamp
        ldy #5
        sta (_st_ptr),y

        clc
        bcc @exit               ; always

@next:
        inc _st_idx             ; wraps 255→0 naturally (8-bit ZP)
        lda _st_idx
        cmp _st_hash
        bne @probe              ; haven't wrapped → keep probing

@full:  sec
@exit:  pla
        sta $01                 ; caller's banking (C kept)
        rts
.endproc

; ═════════════════════════════════════════════════════════
; sym_lookup
;   In:  sym_name (ptr)
;   Out: sym_val (16-bit), sym_wide (0/1), C=0 found, C=1 not found
; ═════════════════════════════════════════════════════════
.proc sym_lookup
        jsr compute_hash

        lda _st_hash
        sta _st_idx             ; SYM_MASK=$FF: no masking needed for 8-bit ZP

        lda $01                 ; nesting guard (see sym_define)
        pha
        jsr kernal_bank_out

@probe: jsr entry_ptr
        jsr is_empty
        beq @notfound

        ; Check hash
        ldy #0
        lda (_st_ptr),y
        cmp _st_hash
        bne @next

        ; Check name
        jsr names_equal
        bne @next

        ; Found — read value
        ldy #1
        lda (_st_ptr),y
        sta sym_val
        iny
        lda (_st_ptr),y
        sta sym_val+1

        ; Read scope → sym_fwd (stamp differs), sym_wide (bit 7 → 0 or 1)
        ldy #5
        lda (_st_ptr),y
        and #SYM_P0
        eor sym_stamp
        sta sym_fwd
        lda (_st_ptr),y
        asl
        lda #0
        rol
        sta sym_wide

        clc
        bcc @exit               ; always

@next:
        inc _st_idx             ; wraps 255→0 naturally (8-bit ZP)
        lda _st_idx
        cmp _st_hash
        bne @probe              ; haven't wrapped → keep probing

@notfound:
        sec
@exit:  pla
        sta $01                 ; caller's banking (C kept)
        rts
.endproc
