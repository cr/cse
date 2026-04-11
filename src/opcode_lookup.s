; opcode_lookup.s — (slot, mode) → opcode byte for the line assembler
;
; Two entry points:
;
;   asm_validate_mode
;       Check that asm_mode is legal for the current effective profile asm_pidx.
;       Returns C=0 if valid, C=1 if invalid.  Does not call asm_error.
;
;   asm_opcode_lookup
;       Compute the opcode byte for the current instruction.
;       Returns opcode in A on success.
;       Jumps to asm_error if the mode is structurally invalid (should not
;       happen after asm_validate_mode passes, but guards against bugs).
;
;       Dispatch order:
;         1. dir_bit=1  → direct_opcodes[asm_mode]            (STZ, profile 28)
;         2. cat=11     → pidx=29 special path                (TRB / TSB)
;         3. cat=01     → CMOS exception pre-check            (ZPI, ACC, IND, AIX, BIT IMM)
;         4. zone=3 ABY → inline bbb dispatch (bbb=6 vs bbb=7)
;         5. otherwise  → mode_offset[zone*16 + mode] formula
;
;       Zone=3/ABY note:
;         mode_offset[cc=11][ABY] is $FF (genuine bbb conflict: profiles
;         25/27 need bbb=6, profiles 18/24 need bbb=7).  All zone=3/ABY
;         mnemonics are dispatched at step 4 before @formula_table is reached.
;         The $FF sentinel acts as a safety net: any future zone=3/ABY mnemonic
;         that bypasses the inline check will trigger asm_error instead of
;         silently producing a wrong opcode.
;
; Inputs (from asm_vars.s):
;   asm_pidx    effective profile index (after CMOS upgrade if applicable)
;   asm_prof    raw packed profile byte (bits 7:6 = cat, bit 5 = dir_bit)
;   asm_base    base opcode from mn7_base_op[asm_slot]
;   asm_mode    addressing-mode index (0–15; mirror of ALL_MODES order)
;
; Imports (tables):
;   mn_modes_lo, mn_modes_hi   — mode bitmasks per profile (from mn_modes.s)
;   mode_offset                — bbb<<2 table (from mn_asm_tables.s)
;   direct_opcodes             — per-mode opcode table for STZ (profile 28)
;   FIRST_DIR_PROFILE          — = 28 (from mn_asm_tables.s)
;
; Mode constants (mirror au_mode.s)
MODE_IMP  = 0
MODE_ACC  = 1
MODE_IMM  = 2
MODE_ZP   = 3
MODE_ZPX  = 4
MODE_ZPY  = 5
MODE_ABS  = 6
MODE_ABX  = 7
MODE_ABY  = 8
MODE_IND  = 9
MODE_INX  = 10
MODE_INY  = 11
MODE_REL  = 12
MODE_ZPI  = 13
MODE_AIX  = 14
MODE_ZPREL= 15

        .setcpu "6502"

        .export asm_validate_mode, asm_opcode_lookup

        .importzp asm_pidx, asm_prof, asm_base, asm_mode
        .import   mn_modes_lo, mn_modes_hi
        .import   mode_offset, direct_opcodes, FIRST_DIR_PROFILE
        .import   asm_error

.segment "ZEROPAGE"
_asm_ok_tmp:        .res 1          ; scratch for opcode_lookup

.segment "RODATA"

; One-hot bitmask for each bit position 0–7
_bit_tab:
        .byte $01, $02, $04, $08, $10, $20, $40, $80

.segment "CODE"

; ── asm_validate_mode ─────────────────────────────────────────────────────────
; Check asm_mode against mn_modes_lo/hi[asm_pidx].
; Returns C=0 valid, C=1 invalid.  Clobbers A, X.
asm_validate_mode:
        lda asm_mode
        and #$07                ; bit position within the byte
        tax
        lda _bit_tab,x          ; bit mask
        ldx asm_pidx
        ldy asm_mode
        cpy #8
        bcs @hi
        and mn_modes_lo,x       ; modes 0–7: check lo byte
        bne @ok
        sec
        rts
@hi:    and mn_modes_hi,x       ; modes 8–15: check hi byte
        bne @ok
        sec
        rts
@ok:    clc
        rts

; ── asm_opcode_lookup ──────────────────────────────────────────────────────────
; Compute opcode byte.  Returns opcode in A.  Jumps to asm_error on failure.
asm_opcode_lookup:
        ; Cache cat bits (7:6) once for the two comparisons below.
        ; _asm_ok_tmp is repurposed later in @formula_table for zone*16; lifetimes
        ; do not overlap (both cat reads complete before @formula_table is reached).
        lda asm_prof
        and #$C0
        sta _asm_ok_tmp             ; cat bits: $00=legal, $40=+CMOS, $80=illegal, $C0=CMOS-only

        ; ── dir_bit=1: STZ (profile 28) → direct_opcodes table ───────────────
        lda asm_prof
        and #$20                ; bit 5 = dir_bit
        beq @no_dir
        ; index = (asm_pidx - FIRST_DIR_PROFILE) * 16 + asm_mode
        ; Currently only profile 28 (STZ); (28-28)*16 = 0 so index = asm_mode.
        ldx asm_mode
        lda direct_opcodes,x
        bne :+
        jmp asm_error            ; $00 = unused mode slot for STZ
:       rts

@no_dir:
        ; ── cat=11 (CMOS-only) at pidx=29: TRB / TSB ─────────────────────────
        lda _asm_ok_tmp             ; cat bits cached at entry
        cmp #$C0                ; cat=11?
        bne @not_cat3
        lda asm_pidx
        cmp #29
        bne @err                ; defensive: no other cat=11 profile exists yet;
                                ;   a future one added here without updating this
                                ;   function would silently produce garbage opcodes
        ; pidx=29: ZP → base_op, ABS → base_op | $08
        lda asm_mode
        cmp #MODE_ZP
        beq @trb_zp
        cmp #MODE_ABS
        bne @err
        lda asm_base
        ora #$08
        rts
@trb_zp:
        lda asm_base
        rts

@not_cat3:
        ; ── cat=01 (legal + CMOS extension) ──────────────────────────────────
        ; Certain CMOS modes don't follow the bbb formula; handle them before
        ; consulting mode_offset (the $FF sentinel alone misses BIT IMM and
        ; ACC for DEC/INC because those (zone,mode) slots are already filled
        ; with valid bbb values from other mnemonics).
        lda _asm_ok_tmp             ; cat bits cached at entry
        cmp #$40                ; cat=01?
        bne @formula
        ; cat=01 explicit exception pre-check
        lda asm_mode
        cmp #MODE_ZPI
        beq @cmos_exc           ; ZPI: always exception (cc=01 group)
        cmp #MODE_ACC
        beq @cmos_exc           ; ACC: always exception (DEC/INC cc=10)
        cmp #MODE_IND
        beq @cmos_exc           ; IND: always exception (JMP cc=00)
        cmp #MODE_AIX
        beq @cmos_exc           ; AIX: always exception (JMP cc=00)
        cmp #MODE_IMM
        bne @formula
        lda asm_pidx
        cmp #12
        bcs @cmos_exc           ; IMM + pidx≥12: BIT IMM = $89 (exception)
        ; IMM + pidx<12: standard formula mode (ADC,LDA,etc.)

@formula:
        ; ── zone=3 ABY: genuine bbb conflict ($18 vs $1C) ───────────────────
        ; mode_offset[cc=11][ABY] = $FF (conflict sentinel); ALL zone=3 ABY
        ; mnemonics are handled here instead of by @formula_table.
        ;   bbb=6 ($18): profiles 25 (TAS/SHS/XAS/LAS/LAR) and 27 (ASO-family)
        ;   bbb=7 ($1C): pidx 18 (LAX) and pidx 24 (SHA/AXA)
        ; AHX (pidx=25, base=$9F) takes the bbb=6 path: $9F|$18=$9F is correct
        ; because the pre-set bbb=7 bits in $9F absorb the OR.
        lda asm_mode
        cmp #MODE_ABY
        bne @formula_table
        lda asm_base
        and #$03
        cmp #$03                ; zone=3 (cc=11)?
        bne @formula_table
        lda #$18                ; default bbb=6 (majority)
        ldx asm_pidx
        cpx #18
        beq @zone3_bbb7        ; LAX
        cpx #24
        bne @zone3_or           ; all others: keep bbb=6
@zone3_bbb7:
        lda #$1C                ; bbb=7 for LAX / SHA / AXA
@zone3_or:
        ora asm_base
        rts
@formula_table:
        ; opcode = asm_base | mode_offset[zone * 16 + asm_mode]
        ; zone = asm_base & $03  (cc bits)
        lda asm_base
        and #$03                ; zone = cc bits
        asl
        asl
        asl
        asl                     ; zone * 16
        sta _asm_ok_tmp             ; zone*16  (repurposes _asm_ok_tmp; cat cache no longer needed)
        lda asm_mode
        ora _asm_ok_tmp             ; zone*16 + mode_idx
        tax
        lda mode_offset,x
        cmp #$FF
        beq @err                ; $FF = invalid/unhandled (should not reach here
                                ;       after explicit exception checks above)
        ora asm_base             ; opcode = base | bbb
        rts

@err:   jmp asm_error

; ── @cmos_exc: CMOS exception dispatch ───────────────────────────────────────
; Triggered for cat=01 mnemonics when the mode doesn't follow the bbb formula.
; Inputs: asm_mode (which exception), asm_base (NMOS base opcode), asm_pidx.
@cmos_exc:
        lda asm_mode
        cmp #MODE_ZPI
        bne :+
        ; ZPI for cc=01 group: opcode = (base | $04) ^ $17
        ; Verified: ADC/AND/CMP/EOR/LDA/ORA/SBC/STA ZPI all match.
        lda asm_base
        ora #$04
        eor #$17
        rts
:       cmp #MODE_ACC
        bne :+
        ; ACC for DEC/INC: opcode = base ^ $F8
        lda asm_base
        eor #$F8
        rts
:       cmp #MODE_IND
        bne :+
        ; IND for JMP: opcode = base | $20
        lda asm_base
        ora #$20
        rts
:       cmp #MODE_AIX
        bne :+
        ; AIX for JMP: opcode = base | $30
        lda asm_base
        ora #$30
        rts
:       ; MODE_IMM with asm_pidx >= 12: BIT IMM = $89
        lda #$89
        rts
