; loader.s — Discardable bootstrap for PRG builds
; Owner: doc/modules/loader.md
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
; backward copy is always safe.  See doc/build_system.md § The ld65
; load/run split.

        .setcpu "6502"
        .include "platform.inc"

; One entry, a body per platform (doc/platform_layer.md § Loader):
; the C64's copy loop below; the m65's gate and install
; (doc/modules/loader.md § Design).
.ifdef PLATFORM_C64

; ── Imports ──────────────────────────────────────────────────
        .import _main

        .import __CODE_LOAD__, __CODE_RUN__, __CODE_SIZE__
        .import __RODATA_SIZE__
        .import __BSS_RUN__, __BSS_SIZE__
        .import __KDATA_LOAD__, __KDATA_RUN__, __KDATA_SIZE__

; ── ZP (borrowed — only used during loader, before _main) ────
; Same addresses as zp.s's rp_ptr/rp_ptr2, but the
; loader runs before _main so there is no conflict.
ptr1     = $02                  ; 2 bytes — source pointer
ptr2     = $04                  ; 2 bytes — destination pointer

; ── LOADER segment (discardable, load = run = $080D) ─────────
.segment "LOADER"

loader_entry:
        ; ── 1. Reset the 6502 hardware stack ─────────────────
        ldx #STACK_TOP
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

.endif ; PLATFORM_C64

; ═════════════════════════════════════════════════════════════
; m65 — the gate and the install (doc/modules/loader.md § Design,
; *The m65 sequence*).  Entered by `10 SYS 8205` with the run premise:
; the user map, B = 0, interrupts on.  Nothing is written before the
; gate has passed, so a refusal returns to BASIC with nothing changed.
; ═════════════════════════════════════════════════════════════
.ifdef PLATFORM_M65

        .import _main
        .import stub_cold, stub_cold_target
        .import __STUB_LOAD__, __STUB_RUN__, __STUB_SIZE__
        .import __CODE_LOAD__, __CODE_RUN__, __CODE_SIZE__
        .import __RODATA_SIZE__
        .import __KDATA_LOAD__, __KDATA_RUN__, __KDATA_SIZE__
        .import __BSS_RUN__, __BSS_SIZE__

.segment "LOADER"

loader_entry:
        ; ── 1. The gate: Hyppo 1.2+, and every jump-table entry CSE
        ;       calls is a JMP or JMP () — no store before it passes
        HYPPO HYPPO_GETVERSION, HYPPO_TRAP      ; A.X = Hyppo major.minor
        cmp #1
        bcc @refuse
        bne @entries                            ; 2.x or later
        cpx #2
        bcc @refuse
@entries:
        ldy #entries_end - entries - 1
@entry: ldx entries,y
        lda KERNAL_JUMP_PAGE,x
        cmp #$4C                                ; JMP abs
        beq @next
        cmp #$6C                                ; JMP (abs)
        bne @refuse
@next:  dey
        bpl @entry

        ; ── 2. Interrupts off; the stack from its top ──
        sei
        ldx #STACK_TOP
        txs

        ; ── 3. The stub to STUB_BASE, CSE's base page cleared, the
        ;       stub's cold target = _main
        ldx #<__STUB_SIZE__
@stub:  lda __STUB_LOAD__ - 1,x
        sta __STUB_RUN__ - 1,x
        dex
        bne @stub
        lda #0
        ldx #ZP_FILL_END
@bp:    sta CSE_BP * 256 - 1,x
        dex
        bne @bp
        lda #<_main
        sta stub_cold_target
        lda #>_main
        sta stub_cold_target + 1

        ; ── 4. Banks 2-3 writable ──
        HYPPO HYPPO_ROM_WRITEENABLE, HYPPO_TRAP_ROM

        ; ── 5. The images to bank 3, BSS cleared: one job list ──
        lda #BANK_USER
        sta DMA_LIST_BANK
        lda #>install_jobs
        sta DMA_LIST_HI
        lda #<install_jobs
        sta DMA_START_ENH

        ; ── 6. Into _main through the stub, which MAPs the CSE map ──
        jmp stub_cold

@refuse:
        ldy #0
@msg:   lda refusal,y
        beq @done
        jsr CHROUT                              ; B = 0 here: no KCALL
        iny
        bne @msg
@done:  rts

; The low bytes of the jump-table entries CSE calls ($FFxx).
entries:
        .byte <GETIN, <PLOT, <SETLFS, <SETNAM, <OPEN, <CLOSE, <CHKIN
        .byte <CHKOUT, <CLRCHN, <CHRIN, <CHROUT, <LOAD, <READST
        .byte <LISTEN, <UNLSN, <VECTOR, <SETBNK, <SCRORG, <SYSFLAGS
entries_end:

refusal:
        .byte "cse needs MEGA65 ROM 920413+ (Hyppo 1.2+)", $0D, 0

; The install: CODE + RODATA and KDATA from the PRG image (bank 0) to
; bank 3, then BSS cleared — three chained F018B jobs.
install_jobs:
        .byte DMA_OPT_F018B, $00
        .byte DMA_COPY | DMA_CHAIN
        .word __CODE_SIZE__ + __RODATA_SIZE__
        .word __CODE_LOAD__
        .byte BANK_USER
        .word __CODE_RUN__
        .byte BANK_CSE
        .byte $00
        .word 0
        .byte $00                               ; options: none
        .byte DMA_COPY | DMA_CHAIN
        .word __KDATA_SIZE__
        .word __KDATA_LOAD__
        .byte BANK_USER
        .word __KDATA_RUN__
        .byte BANK_CSE
        .byte $00
        .word 0
        .byte $00
        .byte DMA_FILL
        .word __BSS_SIZE__
        .byte $00, $00, $00                     ; the fill byte
        .word __BSS_RUN__
        .byte BANK_CSE
        .byte $00
        .word 0

        .assert >GETIN = >KERNAL_JUMP_PAGE, error, "a jump-table entry outside $FFxx"
        .assert >SETBNK = >KERNAL_JUMP_PAGE, error, "a jump-table entry outside $FFxx"
        .assert >SYSFLAGS = >KERNAL_JUMP_PAGE, error, "a jump-table entry outside $FFxx"

.endif ; PLATFORM_M65
