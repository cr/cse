; symtab.s — Symbol table: hash table with linear probing + name heap
;
; Entry: hash(1) + value(2) + name_ptr(2) + scope(1) = 6 bytes
;   hash:      full 8-bit hash (all 256 values valid)
;   value:     16-bit symbol value
;   name_ptr:  pointer to name in heap ($0000 = empty slot)
;   scope:     bit 7 = ZP/ABS (0=ZP, 1=ABS)
;              bit 6 = is_local (reserved, not yet implemented)
;              bits 5-0 = parent slot if local (reserved)
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
        .export kernal_bank_out, kernal_bank_in, kernal_init
        .export kernal_out

        .importzp sym_name, sym_val, sym_wide

; ── Constants ────────────────────────────────────────────
SYM_SLOTS  = 256
SYM_MASK   = SYM_SLOTS - 1         ; $FF
ENTRY_SIZE = 6              ; hash(1) + value(2) + name_ptr(2) + scope(1)

; Capacity = 256.  All slots are real entries: the empty marker is
; the value name_ptr=$0000 (unreachable since the heap lives at $E600+).
; Probe-wrap detection in sym_define / sym_lookup catches a full table.

; ── ZP scratch ───────────────────────────────────────────
.segment "ZEROPAGE"
_st_hash:    .res 1         ; computed hash
_st_idx:     .res 1         ; current probe index
_st_ptr:     .res 2         ; pointer to current entry
_st_nptr:    .res 2         ; pointer for name comparison
_st_heap:    .res 2         ; current heap write pointer
_st_heap_base: .res 2       ; heap base (fixed at SYM_HEAP)

; ── Banked RAM layout under KERNAL ROM ($E000–$FFFF) ─────
; $E000–$E5FF  sym_table   (256 slots × 6B = 1536 bytes)
; $E600–$EEFF  sym_heap    (2304 bytes, name heap)
; $EF00–$F0FF  free (512 bytes)
; $F100–$F4F1  KDATA tables (1010B)
; $F4F2–$F8D9  REPL screen save (1000B, editor.s)
; $F8DA–$FEFF  free (1574B)
; $FF00–$FF09  NMI trampoline (10 bytes)
; $FFFA–$FFFF  HW vectors (6B, fixed)
;
; Used: 5860 / 8192 bytes (71%).  Free: 2326 bytes.
sym_table    = $E000
SYM_HEAP     = $E600
SYM_HEAP_END = $EF00

CPU_PORT = $01

.segment "BSS"
kernal_out:     .res 1          ; nonzero = KERNAL banked out (skip bank_in)

.segment "CODE"

; ── Banking helpers ──────────────────────────────────────
; kernal_bank_out: sei + clear $01 bit 1 → KERNAL ROM hidden
; kernal_bank_in:  set $01 bit 1 → KERNAL ROM visible + cli
;
; Both helpers honour the kernal_out flag: when non-zero, the
; caller is managing banking explicitly across a long batch
; (e.g. asm_assemble holds KERNAL out for both passes), so the
; helpers become no-ops.  This eliminates redundant sei/$01
; writes on every inner sym_define / sym_lookup / asm_line /
; dasm_insn call inside the batch.
;
; ── ORDERING RULE FOR BATCH CALLERS ──
; Because BOTH helpers short-circuit on kernal_out, a batch caller
; must do the real bank operation BEFORE setting/clearing the flag:
;
;     ; ENTER batch                  ; LEAVE batch
;     jsr kernal_bank_out             lda #0
;     lda #1                          sta kernal_out
;     sta kernal_out                  jsr kernal_bank_in
;
; Setting kernal_out=1 BEFORE bank_out makes bank_out a no-op
; (because the flag is already set), so KERNAL stays mapped IN
; for the duration of the "batch" — every KDATA read returns ROM
; bytes instead of the real tables.  This was the asm_assemble
; bug fixed in commit a4cbd5d.  The bank-witness test in
; tests/test_asm_src.py::TestAsmAssembleBankState pins this rule.
;
; Pure writers under KERNAL ($E000–$FFFF) do NOT need either
; helper: stores pass through to the underlying RAM regardless of
; $01 bit 1.  See sym_clear, kernal_init, the KDATA-copy in
; main::startup, and enter_editor's screen save side.
kernal_bank_out:
_st_bank_out:
        lda kernal_out
        bne @skip               ; flag set → already banked out
        sei
        lda CPU_PORT
        and #$FD                ; clear bit 1 → RAM under KERNAL
        sta CPU_PORT
@skip:  rts

kernal_bank_in:
_st_bank_in:
        lda kernal_out
        bne @skip               ; flag set → stay banked out (caller manages)
        lda CPU_PORT
        ora #$02                ; set bit 1 → KERNAL ROM restored
        sta CPU_PORT
        cli
@skip:  rts

; ── NMI trampoline (written to RAM at $FF00 by kernal_init) ──
; If NMI fires while KERNAL is banked out, the CPU reads the
; NMI vector from RAM at $FFFA/$FFFB → $FF00.  This stub
; re-banks the KERNAL and then does what the KERNAL NMI entry
; would have done: SEI + JMP ($0318).  $0318 is the KERNAL's
; indirect NMI vector in RAM, which CSE sets to nmi_handler.
NMI_TRAMP    = $FF00
NMI_VEC_RAM  = $FFFA
KERNAL_NMIV  = $0318            ; KERNAL indirect NMI vector (RAM)

.segment "RODATA"
_nmi_tramp_code:
        ; 10 bytes: lda $01 / ora #$02 / sta $01 / sei / jmp ($0318)
        .byte $A5, $01          ; LDA $01
        .byte $09, $02          ; ORA #$02
        .byte $85, $01          ; STA $01
        .byte $78               ; SEI
        .byte $6C               ; JMP (abs)
        .byte <KERNAL_NMIV, >KERNAL_NMIV
NMI_TRAMP_SIZE = * - _nmi_tramp_code

.segment "CODE"

; ═════════════════════════════════════════════════════════
; kernal_init — install NMI trampoline in banked RAM
;   Must be called once at startup.
;   Pure writer: stores under KERNAL pass through to RAM
;   regardless of $01 bit 1, so no banking is required.
;   Clobbers A, X.
; ═════════════════════════════════════════════════════════
.proc kernal_init
        ; Copy trampoline code to $FF00
        ldx #NMI_TRAMP_SIZE - 1
@copy:  lda _nmi_tramp_code,x
        sta NMI_TRAMP,x
        dex
        bpl @copy

        ; Set RAM NMI vector → $FF00
        lda #<NMI_TRAMP
        sta NMI_VEC_RAM
        lda #>NMI_TRAMP
        sta NMI_VEC_RAM + 1
        rts
.endproc

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
;   Returns heap address of the copy in _st_nptr.
;   Advances _st_heap past the copied string + NUL.
;   Returns C=1 if heap would overflow SYM_HEAP_END.
;   Heap is under KERNAL — caller must have it banked out.
;   Clobbers A, Y.
; ═════════════════════════════════════════════════════════
.proc heap_copy_name
        ; Save current heap position as the name address
        lda _st_heap
        sta _st_nptr
        lda _st_heap+1
        sta _st_nptr+1
        ; Copy bytes
        ldy #0
@loop:  lda (sym_name),y
        sta (_st_heap),y
        beq @done               ; copied the NUL
        iny
        bne @loop
@done:  ; Advance heap pointer past the NUL
        tya
        sec                     ; +1 for the NUL byte
        adc _st_heap
        sta _st_heap
        bcc :+
        inc _st_heap+1
:       ; Check heap overflow
        lda _st_heap+1
        cmp #>SYM_HEAP_END
        bcc @ok                 ; hi < limit → safe
        bne @overflow           ; hi > limit → overflow
        lda _st_heap
        cmp #<SYM_HEAP_END
        bcc @ok                 ; lo < limit → safe
@overflow:
        sec
        rts
@ok:    clc
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
        and #SYM_MASK
        sta _st_idx

        jsr _st_bank_out

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

        ; Store scope byte (bit 7 = ZP/ABS)
        lda sym_wide
        beq :+
        lda #$80
:       ldy #5
        sta (_st_ptr),y

        jsr _st_bank_in
        clc
        rts

@next:
        inc _st_idx
        lda _st_idx
        and #SYM_MASK
        sta _st_idx
        ; Check if we've wrapped around to the start
        cmp _st_hash
        bne @probe              ; haven't wrapped → keep probing

@full:  jsr _st_bank_in
        sec
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
        and #SYM_MASK
        sta _st_idx

        jsr _st_bank_out

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

        ; Read scope → sym_wide (bit 7 → 0 or 1)
        ldy #5
        lda (_st_ptr),y
        asl
        lda #0
        rol
        sta sym_wide

        jsr _st_bank_in
        clc
        rts

@next:
        inc _st_idx
        lda _st_idx
        and #SYM_MASK
        sta _st_idx
        ; Check if we've wrapped around to the start
        cmp _st_hash
        bne @probe              ; haven't wrapped → keep probing

@notfound:
        jsr _st_bank_in
        sec
        rts
.endproc
