; loader.s — Discardable bootstrap for PRG builds
;
; Runs once at startup from the LOADER segment ($080D).
; Copies CODE+RODATA from their load position to the runtime
; position in high memory, zeros BSS, copies KDATA to $F100+
; under KERNAL, then jumps to _main (now at its runtime address).
; After the jump, the loader's memory is reclaimed as workspace.
;
; Forward copy is safe: the payload in the load image ends well
; below the runtime start address for any binary under ~25 KB.
; compute_layout.py verifies this at build time.

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
        jsr copy_pages

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
        jsr copy_pages

        ; ── 5. Jump to _main (now at runtime address) ────────
        jmp _main

; ── copy_pages — copy A + X*256 bytes from ptr1 to ptr2 ──────
; In:  ptr1 = src, ptr2 = dst, X = page count (hi), A = remainder (lo).
; Out: ptr1 / ptr2 advanced past the copied region, Y = 0.
; Handles size = 0 (both components zero) as a no-op.
copy_pages:
        ldy #0
        cpx #0
        beq @rem
        pha                     ; save remainder
@page:  lda (ptr1),y
        sta (ptr2),y
        iny
        bne @page
        inc ptr1+1
        inc ptr2+1
        dex
        bne @page
        pla
@rem:   cmp #0
        beq @done
        tax
@rlp:   lda (ptr1),y
        sta (ptr2),y
        iny
        dex
        bne @rlp
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
