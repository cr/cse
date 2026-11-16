; opcode_lookup.s — (profile, mode) → opcode byte for the line assembler
; Owner: doc/modules/opcode_lookup.md
;
; Two entry points:
;
;   asm_validate_mode
;       Check that asm_mode is legal for the effective profile asm_pidx.
;       Returns C=0 if valid, C=1 if invalid.  Does not call asm_error.
;
;   asm_opcode_lookup
;       opcode = asm_base ^ asm_delta[asm_row[asm_pidx] + asm_mode]
;       Precondition: asm_validate_mode accepted (asm_pidx, asm_mode).
;       No error exit — every accepted pair has a delta.
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

        .export asm_validate_mode, asm_opcode_lookup

        .importzp asm_pidx, asm_base, asm_mode
        .import   mn_modes_lo, mn_modes_hi
        .import   asm_row, asm_delta

; ── RODATA ────────────────────────────────────────────────────────────────────
.segment "RODATA"

; Bit masks for the mode's bit within its mask plane (mode & 7).
_bit_tab:
        .byte $01, $02, $04, $08, $10, $20, $40, $80

.segment "CODE"

; ── asm_validate_mode ────────────────────────────────────────────────────────
; Check asm_mode against the mask plane of asm_pidx.
; Returns: C=0 valid, C=1 invalid.
; Clobbers: A, X, Y
asm_validate_mode:
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
@hi:    and mn_modes_hi,x       ; modes 8–15: hi plane
        bne @ok
        rts                     ; C=1 preserved from bcs @hi (AND doesn't affect C)
@ok:    clc
        rts

; ── asm_opcode_lookup ────────────────────────────────────────────────────────
; A = asm_base ^ asm_delta[asm_row[asm_pidx] + asm_mode]
; Clobbers: A, X
asm_opcode_lookup:
        ldx asm_pidx
        lda asm_row,x           ; delta row's byte offset (row × ASM_N_MODES)
        clc
        adc asm_mode
        tax
        lda asm_delta,x
        eor asm_base
        rts
