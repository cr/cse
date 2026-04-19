; loader.s — Discardable bootstrap for PRG builds
;
; Runs once at startup from the LOADER segment ($080D).
; Copies CODE+RODATA from their load position to the runtime
; position in high memory, zeros BSS, copies KDATA to $F100+
; under KERNAL, then jumps to _main (now at its runtime address).
; After the jump, the loader's memory is reclaimed as workspace.
;
; Copy direction: **top-down** (backward memcpy — highest byte
; first).  CSE always has dst > src for both copies (payload lives
; low, runtime lives high; KDATA load is below $F100 run), so
; backward copy is always safe and the old payload-end sanity gate
; is gone.  See doc/build_system.md § Copy direction.

        .setcpu "6502"

; ── Imports ──────────────────────────────────────────────────
        .import _main

        .import __CODE_LOAD__, __CODE_RUN__, __CODE_SIZE__
        .import __RODATA_SIZE__
        .import __BSS_RUN__, __BSS_SIZE__
        .import __KDATA_LOAD__, __KDATA_RUN__, __KDATA_SIZE__

; ── ZP (borrowed — only used during loader, before _main) ────
; Same addresses as main's rp_ptr/rp_ptr2/rp_tmp, but the
; loader runs before _main so there is no conflict.
ptr1     = $02                  ; 2 bytes — source pointer
ptr2     = $04                  ; 2 bytes — destination pointer

; ── LOADER segment (discardable, load = run = $080D) ─────────
.segment "LOADER"

loader_entry:
        ; ── 1. Reset the 6502 hardware stack ─────────────────
        ldx #$FF
        txs

        ; ── 2. Copy CODE+RODATA to runtime address ──────────
        lda #<__CODE_LOAD__
        sta ptr1
        lda #>__CODE_LOAD__
        sta ptr1+1
        lda #<__CODE_RUN__
        sta ptr2
        lda #>__CODE_RUN__
        sta ptr2+1
        ldx #>(__CODE_SIZE__ + __RODATA_SIZE__)
        lda #<(__CODE_SIZE__ + __RODATA_SIZE__)
        jsr copy_pages_back

        ; ── 3. Zero BSS ─────────────────────────────────────
        lda #<__BSS_RUN__
        sta ptr1
        lda #>__BSS_RUN__
        sta ptr1+1
        ldx #>__BSS_SIZE__
        lda #<__BSS_SIZE__
        jsr zero_pages

        ; ── 4. Copy KDATA to $F100+ ─────────────────────────
        ; Pure writer: stores under KERNAL pass through to RAM
        ; regardless of $01 bit 1, so no banking is needed.
        lda #<__KDATA_LOAD__
        sta ptr1
        lda #>__KDATA_LOAD__
        sta ptr1+1
        lda #<__KDATA_RUN__
        sta ptr2
        lda #>__KDATA_RUN__
        sta ptr2+1
        ldx #>__KDATA_SIZE__
        lda #<__KDATA_SIZE__
        jsr copy_pages_back

        ; ── 5. Jump to _main (now at runtime address) ────────
        jmp _main

; ── copy_pages_back — backward copy A + X*256 bytes ──────────
; Copies from (ptr1 .. ptr1+size-1) to (ptr2 .. ptr2+size-1)
; in reverse — highest byte first.  Safe whenever dst >= src,
; which is always true for CSE's two copies.
; In:  ptr1 = src base, ptr2 = dst base,
;      X = page count (hi), A = remainder (lo).
; Handles size = 0 (A=0 and X=0) as a no-op.
copy_pages_back:
        tay                     ; Y = remainder (A preserved in Y)
        txa                     ; advance ptr1/ptr2 hi by X pages
        clc
        adc ptr1+1
        sta ptr1+1
        txa
        clc
        adc ptr2+1
        sta ptr2+1
        cpy #0                  ; remainder == 0?
        beq @pages
@rlp:   dey
        lda (ptr1),y
        sta (ptr2),y
        tya
        bne @rlp                ; falls through with Y=0
@pages: cpx #0
        beq @done
@p:     dec ptr1+1              ; step back to the next page below
        dec ptr2+1
@pl:    dey                     ; Y=0 → $FF (top of page)
        lda (ptr1),y
        sta (ptr2),y
        tya
        bne @pl                 ; exits with Y=0, ready for next page
        dex
        bne @p
@done:  rts

; ── zero_pages — fill A + X*256 bytes at ptr1 with $00 ───────
; In:  ptr1 = dst, X = page count (hi), A = remainder (lo).
; Out: ptr1 advanced past the filled region, Y = 0, A = 0.
zero_pages:
        pha                     ; save remainder
        ldy #0
        tya                     ; A = 0 — the fill value
        cpx #0
        beq @rem
@page:  sta (ptr1),y
        iny
        bne @page
        inc ptr1+1
        dex
        bne @page
@rem:   pla
        cmp #0
        beq @done
        tax
        lda #0
@rlp:   sta (ptr1),y
        iny
        dex
        bne @rlp
@done:  rts
