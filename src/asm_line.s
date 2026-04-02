; asm_line.s — single-line assembler for the debugger's '.' command
;
; Assembles one instruction from a VICII-screen-code string and writes the
; resulting bytes to the output buffer.
;
; Format: MNEMONIC [OPERAND]
;   - MNEMONIC: 3 letters (upper or lower case ASCII; VICII $01–$1A for A–Z)
;   - OPERAND:  addressing-mode argument, same syntax as au_parse_mode accepts
;               Exception: Zone B (REL) accepts a 4-digit absolute target ($xxxx)
;               and computes the signed PC-relative offset automatically.
;   - No labels, symbols, directives, or expressions (stub: hex literals only).
;
; Entry:
;   au_ptr    — ZP word pointing to the instruction string (VICII screen codes,
;               null-terminated)
;   al_pc     — current PC (lo, hi); required for REL/ZPREL offset computation
;   al_out    — output buffer pointer (lo, hi)
;   al_cpu    — 0 = NMOS 6502, 1 = 65C02  (controls CMOS mode acceptance)
;   Y = 0
;
; Exit (success):
;   al_len  — number of bytes written to [al_out]
;   C = 0
;
; Error: jmp al_error (does not return)
;   Triggered for: unknown mnemonic, invalid mode for profile, out-of-range
;   REL offset, or any other structural assembler error.
;
; Design notes
; ------------
; Zone dispatch is driven entirely by the 5-bit profile index from the hash
; table.  No branch logic encodes mnemonic identity; every path is generic.
;
; Zone A (pidx=0)  IMP:    emit base opcode; no operand
; Zone B (pidx=1)  REL:    parse ABS target or ZP raw offset; emit opcode+offset
; Zone C (pidx=2)  IMM:    parse #$xx; emit opcode+byte
; Zone D (pidx=3)  ZP bit: parse digit + ZP addr (RMB/SMB) — not yet tested
; Zone E (pidx=4)  ZPREL:  parse digit + ZP addr + abs target (BBR/BBS) — stub
; Zone F (pidx=5)  ABS:    parse $xxxx; emit opcode+lo+hi  (JSR only)
; Zone G (pidx 6–15) / Zone H (pidx 16–29):
;                  call au_parse_mode; validate; opcode_lookup; emit

        .setcpu "6502"

        .export al_line_asm

        ; zero-page variables (asm_vars.s)
        .importzp al_pc, al_out, al_len
        .importzp al_slot, al_prof, al_pidx, al_base, al_bit, al_mode, al_cpu
        .importzp _al_tmp, _al_tmp2

        ; au_mode.s interface
        .importzp au_ptr, au_opr
        .import   au_parse_mode, au_skip_ws

        ; mnemonic classifier
        .importzp mn_c1, mn_c2, mn_c3
        .import   mn_classify
        .import   mn_base_op, mn_profile

        ; opcode tables and helpers (opcode_lookup.s)
        .import   _al_validate_mode, al_opcode_lookup

        ; error handler — provided by caller / test stub
        .import   al_error

; Mode index constants (mirror au_mode.s / ALL_MODES order)
MODE_IMP   = 0
MODE_ACC   = 1
MODE_IMM   = 2
MODE_ZP    = 3
MODE_ABS   = 6
MODE_REL   = 12

; Profile zone boundaries
ZONE_A_PIDX = 0         ; IMP
ZONE_B_PIDX = 1         ; REL
ZONE_C_PIDX = 2         ; IMM
ZONE_D_PIDX = 3         ; ZP  bit-op
ZONE_E_PIDX = 4         ; ZPREL bit-op
ZONE_F_PIDX = 5         ; ABS  (JSR)

.segment "RODATA"

; Operand byte count per mode (16 bytes, uncompressed for fast lookup).
; Mirrors MODE_OPERAND_BYTES from dev/instruction_set.py.
;   IMP ACC IMM ZP  ZPX ZPY ABS ABX ABY IND INX INY REL ZPI AIX ZPR
_al_oplen:
        .byte  0,  0,  1,  1,  1,  1,  2,  2,  2,  2,  1,  1,  1,  1,  2,  2

.segment "CODE"

; ── _al_skip_sp ───────────────────────────────────────────────────────────────
; Advance Y past SPACE characters only ($20).  Does NOT skip TAB ($09) because
; the VICII screencode for the letter 'I' is $09 — indistinguishable from
; ASCII TAB.  Used only before reading the mnemonic characters.
_al_skip_sp:
        lda (au_ptr),y
        cmp #$20
        bne :+
        iny
        bne _al_skip_sp         ; (Y wraps at 256 – safe for any sane line)
:       rts

; ── _al_adv ───────────────────────────────────────────────────────────────────
; Advance au_ptr by Y bytes; reset Y to 0.
; Used to commit consumed characters from the mnemonic + whitespace scan.
_al_adv:
        tya
        beq @done               ; nothing to advance
        clc
        adc au_ptr
        sta au_ptr
        bcc :+
        inc au_ptr+1
:
@done:  ldy #0
        rts

; ── _al_emit ──────────────────────────────────────────────────────────────────
; Write A to [al_out]; advance al_out; increment al_len.
_al_emit:
        ldy #0
        sta (al_out),y
        ; advance output pointer
        inc al_out
        bne :+
        inc al_out+1
:       inc al_len
        rts

; ── _al_rd_upper ──────────────────────────────────────────────────────────────
; Read one character from (au_ptr),y, convert to VICII uppercase (1–26),
; advance Y, and return the screencode in A.
; Handles:  VICII uppercase $01–$1A (pass-through)
;           ASCII  uppercase $41–$5A (mask with $1F → $01–$1A)
;           ASCII  lowercase $61–$7A (mask with $1F → $01–$1A)
; Non-letter characters are passed through unchanged (validated later by
; mn_classify).
_al_rd_upper:
        lda (au_ptr),y
        iny
        cmp #$41                ; below $41 → already a VICII screencode
        bcc :+
        and #$1F                ; map $41–$5A and $61–$7A to $01–$1A
:       rts

; ── _al_emit_base_opr — emit al_base then au_opr[0] ─────────────────────────
_al_emit_base_opr:
        lda al_base
        jsr _al_emit
        lda au_opr
        jmp _al_emit            ; tail call

; ═════════════════════════════════════════════════════════════════════════════
; al_line_asm  —  main entry point
; ═════════════════════════════════════════════════════════════════════════════
al_line_asm:
        lda #0
        sta al_len              ; initialise byte counter

        ldy #0
        jsr _al_skip_sp         ; Y = first non-space position
                                ;   (uses space-only skip: VICII 'I' = $09 = ASCII TAB,
                                ;    so au_skip_ws must not be used here)

        ; ── read 3 mnemonic characters → mn_c1, mn_c2, mn_c3 ─────────────────
        jsr _al_rd_upper
        sta mn_c1
        jsr _al_rd_upper
        sta mn_c2
        jsr _al_rd_upper
        sta mn_c3

        ; Advance au_ptr past the mnemonic (Y bytes consumed so far).
        jsr _al_adv             ; au_ptr += Y; Y = 0

        ; Skip whitespace between mnemonic and operand.
        jsr au_skip_ws          ; Y = offset of first operand character

        ; Advance au_ptr to the start of the operand; reset Y=0 for au_parse_mode.
        jsr _al_adv             ; au_ptr += Y; Y = 0

        ; ── classify mnemonic ─────────────────────────────────────────────────
        jsr mn_classify
        bcc @found
        jmp al_error            ; unknown mnemonic
@found:
        sta al_slot
        tax
        lda mn_base_op,x
        sta al_base
        lda mn_profile,x
        sta al_prof
        and #$1F
        sta al_pidx             ; raw profile index

        ; ── CMOS gate / upgrade ───────────────────────────────────────────
        ; On non-CMOS builds (mn6), cat=11 and cat=01 mnemonics are not
        ; in the hash table, so this code is never reached.  The ifdef
        ; excludes it from the binary to save bytes.
.ifdef CMOS_SUPPORT
        lda al_prof
        and #$C0
        cmp #$C0                ; cat=11 (pure CMOS mnemonic)?
        bne @not_cmos_only
        lda al_cpu
        bne @no_upgrade         ; 65C02 → allow, no pidx upgrade needed
        jmp al_error            ; NMOS → reject
@not_cmos_only:
        cmp #$40                ; cat=01 (legal + CMOS extension)?
        bne @no_upgrade
        lda al_cpu
        beq @no_upgrade
        inc al_pidx             ; use the CMOS profile for mode validation
.endif ; CMOS_SUPPORT
@no_upgrade:

        ; ── reset Y=0 before zone dispatch ────────────────────────────────────
        ; mn7_classify clobbers Y (sets Y=mn_c2 for the hash table lookup).
        ; All zone paths that call au_parse_mode require Y=0 on entry.
        ldy #0

        ; ── zone dispatch ─────────────────────────────────────────────────────
        lda al_pidx
        cmp #6
        bcc :+
        jmp @zone_gh            ; pidx >= 6 → multi-mode G/H
:
        tax
        lda @ztbl_hi,x
        pha
        lda @ztbl_lo,x
        pha
        rts                     ; RTS trick → dispatches to (addr+1)

@ztbl_lo:
        .byte <(@zone_a-1), <(@zone_b-1), <(@zone_c-1)
        .byte <(@zone_d-1), <(@zone_e-1), <(@zone_f-1)
@ztbl_hi:
        .byte >(@zone_a-1), >(@zone_b-1), >(@zone_c-1)
        .byte >(@zone_d-1), >(@zone_e-1), >(@zone_f-1)

; ── Zone A: implied — no operand ─────────────────────────────────────────────
@zone_a:
        lda al_base
        jsr _al_emit
        clc
        rts

; ── Zone B: REL — branch target (absolute or raw offset) ─────────────────────
@zone_b:
        jsr au_parse_mode
        ; au_parse_mode returns MODE_ABS for a 4-digit $xxxx target, or
        ; MODE_ZP for a 2-digit $xx raw offset.
        cmp #MODE_ABS
        beq @rel_abs
        cmp #MODE_ZP
        beq :+
        jmp al_error            ; neither ABS nor ZP
:       ; ZP: au_opr[0] is the raw signed offset byte
        jsr _al_emit_base_opr
        clc
        rts

@rel_abs:
        ; Compute signed offset = target − (al_pc + 2)
        ; target = au_opr[1]:au_opr[0] (16-bit, little-endian)
        sec
        lda au_opr              ; target lo
        sbc al_pc               ; − pc lo
        sta _al_tmp
        lda au_opr+1            ; target hi
        sbc al_pc+1             ; − pc hi
        tax                     ; X = high byte of (target − pc)
        lda _al_tmp
        sec
        sbc #2                  ; − 2 (instruction size)
        bcs :+
        dex                     ; borrow propagated to hi byte
:       sta _al_tmp             ; _al_tmp = offset byte
        ; Validate: hi byte must be $00 (offset 0..+127) or $FF (−128..−1)
        cpx #$00
        beq @chk_pos
        cpx #$FF
        bne @err_range          ; hi neither $00 nor $FF → out of ±128 range
        lda _al_tmp
        cmp #$80                ; negative offset must be ≥ $80
        bcc @err_range
        jmp @emit_rel
@chk_pos:
        lda _al_tmp
        cmp #$80                ; positive offset must be < $80
        bcs @err_range
@emit_rel:
        lda al_base
        jsr _al_emit
        lda _al_tmp
        jsr _al_emit
        clc
        rts
@err_range:
        jmp al_error

; ── Zone C: IMM — immediate byte ─────────────────────────────────────────────
@zone_c:
        jsr au_parse_mode
        cmp #MODE_IMM
        bne @err_mode
        jsr _al_emit_base_opr
        clc
        rts

; ── Zone D: ZP bit-op (RMB, SMB) — not yet tested; OPCODES entry is None ─────
@zone_d:
        ; Syntax: <digit 0–7> [,] $xx
        ; The digit is ORed into the opcode as (digit<<4).
        ; Since OPCODES['RMB']['ZP'] = None, these are skipped by the test
        ; framework.  Stub: fall through to al_error for now.
        jmp al_error

; ── Zone E: ZPREL bit-op (BBR, BBS) — not yet tested; OPCODES entry is None ──
@zone_e:
        ; Syntax: <digit 0–7> $xx , $xxxx  (ZP addr, absolute target)
        ; Since OPCODES['BBR']['ZPREL'] = None, skipped by the test framework.
        jmp al_error

; ── Zone F: ABS — JSR only ───────────────────────────────────────────────────
@zone_f:
        jsr au_parse_mode
        cmp #MODE_ABS
        bne @err_mode
        jsr _al_emit_base_opr   ; emit base + lo byte
        lda au_opr+1            ; hi
        jsr _al_emit
        clc
        rts

; ── Zone G/H: multi-mode (profiles 6–29) ─────────────────────────────────────
@zone_gh:
        ; Parse the addressing-mode argument.
        jsr au_parse_mode
        sta al_mode

        ; Validate mode against the effective profile's mode set.
        jsr _al_validate_mode
        bcc @mode_ok
@err_mode:
        jmp al_error
@mode_ok:

        ; Compute opcode via the category/dir/profile dispatch in opcode_lookup.
        jsr al_opcode_lookup    ; → A = opcode, or jmps al_error
        jsr _al_emit            ; emit opcode byte

        ; Emit operand bytes: 0, 1, or 2 depending on the mode.
        ldx al_mode
        lda _al_oplen,x         ; operand byte count for this mode
        beq @gh_done            ; 0 bytes → done

        ; Emit au_opr[0]  (always present for 1- and 2-byte operands)
        lda au_opr
        jsr _al_emit            ; clobbers A, Y — X (= al_mode) preserved

        lda _al_oplen,x         ; reload count using still-valid X
        cmp #2
        bne @gh_done

        ; Emit au_opr[1]  (hi byte for 2-byte operands)
        lda au_opr+1
        jsr _al_emit

@gh_done:
        clc
        rts
