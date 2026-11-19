; m45_ops.inc — the 45GS02-only instructions as raw-byte macros.
;
; Owner: doc/platform_layer.md
;
; Contract source: [platform_layer.md § Raw-byte instructions](../doc/platform_layer.md#raw-byte-instructions)
;
; All CSE code is assembled as 6502 code (ca65 --cpu 6502), so an
; instruction the 6502 lacks is written here as the bytes the MEGA65
; compendium gives it, and nowhere else: the raw-byte audit
; (dev/audit_platform_literals.py) refuses such a byte in any other
; file, and M65Emu's clean mode admits, inside CSE's code, only the
; 6502's opcodes and these macros' (tests/m65emu/m45_ops.py assembles
; them; tests/unit/test_m45_ops.py pins each against the compendium).
; Only the m65 platform bodies use them.

.ifndef M45_OPS_INC
M45_OPS_INC = 1

; ── MAP and EOM ──────────────────────────────────────────────────────
; MAP takes MAPLO from A (offset bits) and X (block mask, offset high
; nibble), MAPHI from Y and Z, and holds interrupts off until EOM.
.macro M45_MAP
        .byte $5C               ; MAP
.endmacro

.macro M45_EOM
        nop                     ; EOM: the 6502's NOP; releases MAP's hold
.endmacro

; ── the Z and B registers, the 65C02 stack ops the 6502 lacks ────────
.macro M45_LDZ_IMM value
        .byte $A3, value        ; LDZ #value
.endmacro

.macro M45_TAB
        .byte $5B               ; TAB: B = A (the base page)
.endmacro

.macro M45_TZA
        .byte $6B               ; TZA: A = Z (SCRORG's address high byte)
.endmacro

.macro M45_PHY
        .byte $5A               ; PHY
.endmacro

.macro M45_PLY
        .byte $7A               ; PLY
.endmacro

.macro M45_PLX
        .byte $FA               ; PLX
.endmacro

.macro M45_PLZ
        .byte $FB               ; PLZ
.endmacro

; ── the 65C02's indexed indirect jump (the stub's dispatch) ──────────
.macro M45_JMP_IND_X addr
        .byte $7C               ; JMP (addr,X)
        .word addr
.endmacro

; ── flat access: the EOM prefix before (zp),Z — a 32-bit pointer ─────
.macro M45_FAR_LDA zp
        .byte $EA, $B2, zp      ; LDA [zp],Z
.endmacro

.macro M45_FAR_STA zp
        .byte $EA, $92, zp      ; STA [zp],Z
.endmacro

.macro M45_FAR_ORA zp
        .byte $EA, $12, zp      ; ORA [zp],Z
.endmacro

.endif ; M45_OPS_INC
