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
        ldy #0
        ldx #>(__CODE_SIZE__ + __RODATA_SIZE__)
        beq @cr_partial
@cr_page:
        lda (ptr1),y
        sta (ptr2),y
        iny
        bne @cr_page
        inc ptr1+1
        inc ptr2+1
        dex
        bne @cr_page
@cr_partial:
        ldx #<(__CODE_SIZE__ + __RODATA_SIZE__)
        beq @cr_done
@cr_rem:
        lda (ptr1),y
        sta (ptr2),y
        iny
        dex
        bne @cr_rem
@cr_done:

        ; ── 3. Zero BSS ─────────────────────────────────────
        lda #<__BSS_RUN__
        sta ptr1
        lda #>__BSS_RUN__
        sta ptr1+1
        lda #0
        ldy #0
        ldx #>__BSS_SIZE__
        beq @bss_partial
@bss_page:
        sta (ptr1),y
        iny
        bne @bss_page
        inc ptr1+1
        dex
        bne @bss_page
@bss_partial:
        ldx #<__BSS_SIZE__
        beq @bss_done
@bss_rem:
        sta (ptr1),y
        iny
        dex
        bne @bss_rem
@bss_done:

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
        ldy #0
        ldx #>__KDATA_SIZE__
        beq @kd_partial
@kd_page:
        lda (ptr1),y
        sta (ptr2),y
        iny
        bne @kd_page
        inc ptr1+1
        inc ptr2+1
        dex
        bne @kd_page
@kd_partial:
        ldx #<__KDATA_SIZE__
        beq @kd_done
@kd_rem:
        lda (ptr1),y
        sta (ptr2),y
        iny
        dex
        bne @kd_rem
@kd_done:

        ; ── 5. Jump to _main (now at runtime address) ────────
        jmp _main
