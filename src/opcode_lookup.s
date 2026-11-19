; opcode_lookup.s — (profile, mode) → opcode byte for the line assembler
; Owner: doc/modules/opcode_lookup.md
;
;   asm_opcode_lookup
;       Check asm_mode against the effective profile asm_pidx and compute
;       the opcode.
;       C=0: A = asm_base ^ asm_delta[asm_row[asm_pidx] + asm_mode]
;       C=1: the profile does not accept the mode (A undefined)
;
; Every encoding fact lives in the generated tables (mn_modes.s,
; mn_asm_tables.s), one block per CPU set; this file holds none.
;
; Inputs (ZP):
;   asm_pidx    effective profile index (after the CPU-gate upgrade)
;   asm_base    the key's base opcode (its own ZP opcode, else ABS, else
;               its lowest mode's)
;   asm_mode    mode index (catalogue order, opcode_lookup.md § Design)

        .setcpu "6502"

        .export asm_opcode_lookup

        .importzp asm_pidx, asm_base, asm_mode
        .import   mn_modes_lo, mn_modes_hi
.ifdef MEGA_SUPPORT
        .import   mn_modes_x            ; modes 16-19 (m65)
.endif
        .import   asm_row, asm_delta

; ── RODATA ────────────────────────────────────────────────────────────────────
.segment "RODATA"

; Bit masks for the mode's bit within its mask plane (mode & 7).
_bit_tab:
        .byte $01, $02, $04, $08, $10, $20, $40, $80

.segment "CODE"

; ── asm_opcode_lookup ────────────────────────────────────────────────────────
; Clobbers: A, X, Y
asm_opcode_lookup:
        lda asm_mode
        and #$07                ; bit position within the plane
        tax
        lda _bit_tab,x          ; bit mask
        ldx asm_pidx
        ldy asm_mode
        cpy #8
        bcs @hi
        and mn_modes_lo,x       ; modes 0–7: lo plane
        bne @ok
        sec
        rts
@hi:
.ifdef MEGA_SUPPORT
        cpy #16
        bcs @x
        sec                     ; (the cpy cleared C: a rejection returns C = 1)
.endif
        and mn_modes_hi,x       ; modes 8–15: hi plane
        beq @done               ; rejected: C=1 from the bcs above
@ok:    tya                     ; asm_mode
        clc
        adc asm_row,x           ; + the delta row's byte offset (< 256: C=0)
        tax
        lda asm_delta,x
        eor asm_base
@done:  rts
.ifdef MEGA_SUPPORT
@x:     and mn_modes_x,x        ; modes 16–19: the third plane
        beq @done               ; rejected: C=1 from the cpy
        bne @ok
.endif
