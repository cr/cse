; asm_line.s — single-line instruction assembler
;
; Assembles one instruction from a PETSCII string and writes the resulting
; bytes to the output buffer.
;
; Format: MNEMONIC [OPERAND]
;   - MNEMONIC: 3 letters (PETSCII uppercase $41–$5A or lowercase $61–$7A;
;               AND #$1F normalizes both to 1–26 for the hash classifier)
;   - OPERAND:  addressing-mode argument, same syntax as mode_parse accepts
;               Exception: Zone B (REL) accepts a 4-digit absolute target ($xxxx)
;               and computes the signed PC-relative offset automatically.
;   - No labels, symbols, directives, or expressions (stub: hex literals only).
;
; Public entry point: asm_line (A/X = PETSCII text pointer)
;   Manages KERNAL banking, error recovery, SP save/restore.
;   Calls _asm_line_core internally.
;
; Internal entry point: _asm_line_core
;   asm_ptr   — ZP word pointing to the instruction string (PETSCII, null-terminated)
;   asm_pc    — current PC (lo, hi); required for REL/ZPREL offset computation
;   asm_out   — output buffer pointer (lo, hi)
;   asm_cpu   — 0 = 6502, 1 = 6510, 2 = 65C02
;   Y = 0
;
; Exit (success):
;   asm_len — number of bytes written to [asm_out]
;   C = 0
;
; Error: jmp asm_error (does not return)
;   Triggered for: unknown mnemonic, invalid mode for profile, out-of-range
;   REL offset, or any other structural assembler error.

        .setcpu "6502"

        .export asm_line
        .export _asm_line_core
        .export asm_error, asm_syntax_error, asm_expr_error, asm_expr_err
        .export reg_a, reg_x, reg_y, reg_sp, reg_p

        ; zero-page variables (zp.s)
        .importzp asm_pc, asm_out, asm_len
        .importzp asm_slot, asm_prof, asm_pidx, asm_base, asm_bit, asm_mode, asm_cpu
        .importzp asm_tmp, asm_tmp2

        ; addr_mode.s interface
        .importzp asm_ptr, asm_opr
        .import   mode_parse, asm_skip_ws

        ; mnemonic classifier
        .importzp mn_c1, mn_c2, mn_c3
        .import   mn_classify
        .import   mn_base_op, mn_profile

        ; opcode tables and helpers (opcode_lookup.s)
        .import   asm_validate_mode, asm_opcode_lookup

        ; banking
        .import kernal_bank_out, kernal_bank_in

; Mode index constants (mirror addr_mode.s / ALL_MODES order)
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

        .importzp _asm_saved_sp

; ── BSS ───────────────────────────────────────────────────────────────────────
.segment "BSS"
; Saved user-code register state — populated by debugger.s on BRK/NMI
; entry, displayed by repl.s::show_regs, and reloaded into the CPU by
; debugger.s before continuing.
asm_expr_err:  .res 1          ; nonzero if last asm_error was expr eval
reg_a:         .res 1          ; saved A
reg_x:         .res 1          ; saved X
reg_y:         .res 1          ; saved Y
reg_sp:        .res 1          ; saved SP
reg_p:         .res 1          ; saved P (status flags)

; (kernel_zp_buf and userland_zp_buf — the ZP save/restore buffers for
; the kernel↔userland transitions — live in mem.s alongside the
; save_userland_zp / restore_userland_zp / save_kernel_zp /
; restore_kernel_zp primitives that operate on them.)

; ── RODATA ────────────────────────────────────────────────────────────────────
.segment "RODATA"

; Operand byte count per mode (16 bytes, uncompressed for fast lookup).
; Mirrors MODE_OPERAND_BYTES from dev/instruction_set.py.
;   IMP ACC IMM ZP  ZPX ZPY ABS ABX ABY IND INX INY REL ZPI AIX ZPR
_asm_oplen:
        .byte  0,  0,  1,  1,  1,  1,  2,  2,  2,  2,  1,  1,  1,  1,  2,  2

.segment "CODE"

; ── asm_error / asm_syntax_error ─────────────────────────────────────────────
; Jumped to (not called) by _asm_line_core / mode_parse on any assembler error.
; Restores the 6502 stack to the level saved before _asm_line_core was called,
; banks the KERNAL back in, and returns 0.
; ── asm_expr_error — expression-specific error path ──────────────────────────
; Called by _au_read_val when expr_eval returns an error.
; Sets asm_expr_err=1, then falls into asm_error's shared tail.
asm_expr_error:
        lda #1
        .byte $2C               ; BIT abs — skip the next lda #0
asm_error:
asm_syntax_error:
        lda #0
        sta asm_expr_err
        ldx _asm_saved_sp
        txs                     ; restore SP (unwind nested JSRs)
        jsr kernal_bank_in      ; pair the bank_out from asm_line entry
        lda #0
        tax                     ; return 0 (A=lo, X=hi=0)
        rts

; ── asm_line ─────────────────────────────────────────────────────────────────
; asm_line(text)
;
; Single shared entry point for both call paths:
;   - asm_src.s::process_line (inside asm_assemble's batched bank-out;
;     the inner bank helpers below short-circuit because kernal_out=1)
;   - repl.s::dot_assemble (single-line REPL `.` command; the inner
;     bank helpers do the actual KERNAL bank for KDATA-table reads)
;
; Input is PETSCII.  No encoding conversion.
;
; On entry:
;   A/X = text pointer (lo/hi, PETSCII)
;   Caller has already set asm_pc and asm_out.
;
asm_line:
        ; ── save text pointer ───────────────────────────────────────────
        sta asm_ptr
        stx asm_ptr+1

        ; ── save 6502 SP for error recovery ─────────────────────────────
        ; asm_cpu is set by the caller (main.s init, repl.s `u`, asm_src.s `.cpu`)
        tsx
        stx _asm_saved_sp

        ; ── bank out KERNAL for KDATA reads (no-op inside an asm_assemble
        ; batch — kernal_out=1 short-circuits both bank helpers)
        jsr kernal_bank_out

        ; ── call assembler ──────────────────────────────────────────────
        ldy #0                  ; required by _asm_line_core entry contract
        jsr _asm_line_core

        ; ── bank back in.  bank_in clobbers A, so reload asm_len after.
        jsr kernal_bank_in
        lda asm_len             ; success: return byte count
        ldx #0                  ; hi byte = 0
        rts

; ── _asm_skip_sp ─────────────────────────────────────────────────────────────
; Advance Y past SPACE characters only ($20).
; Used before reading the mnemonic characters (where only plain space is
; expected as leading whitespace; tab $A0 is not expected before a mnemonic).
_asm_skip_sp:
        lda (asm_ptr),y
        cmp #$20
        bne :+
        iny
        bne _asm_skip_sp        ; (Y wraps at 256 – safe for any sane line)
:       rts

; ── _asm_adv ─────────────────────────────────────────────────────────────────
; Advance asm_ptr by Y bytes; reset Y to 0.
; Used to commit consumed characters from the mnemonic + whitespace scan.
_asm_adv:
        tya
        beq @done               ; nothing to advance
        clc
        adc asm_ptr
        sta asm_ptr
        bcc :+
        inc asm_ptr+1
:
@done:  ldy #0
        rts

; ── _asm_emit ────────────────────────────────────────────────────────────────
; Write A to [asm_out]; advance asm_out; increment asm_len.
_asm_emit:
        ldy #0
        sta (asm_out),y
        ; advance output pointer
        inc asm_out
        bne :+
        inc asm_out+1
:       inc asm_len
        rts

; ── _asm_rd_upper ────────────────────────────────────────────────────────────
; Read one character from (asm_ptr),y, normalize to 1–26 for letters,
; advance Y, and return the value in A.
; Handles:  PETSCII uppercase $41–$5A  (AND #$1F → $01–$1A)
;           PETSCII lowercase $61–$7A  (AND #$1F → $01–$1A)
;           VICII screen codes $01–$1A (pass-through, below $41)
; Non-letter characters are passed through unchanged (validated later by
; mn_classify).
_asm_rd_upper:
        lda (asm_ptr),y
        iny
        cmp #$41                ; below $41 → already normalized (or non-letter)
        bcc :+
        and #$1F                ; map $41–$5A and $61–$7A to $01–$1A
:       rts

; ── _asm_emit_base_opr — emit asm_base then asm_opr[0] ──────────────────────
_asm_emit_base_opr:
        lda asm_base
        jsr _asm_emit
        lda asm_opr
        jmp _asm_emit           ; tail call

; ═════════════════════════════════════════════════════════════════════════════
; _asm_line_core  —  assembler core
; ═════════════════════════════════════════════════════════════════════════════
_asm_line_core:
        lda #0
        sta asm_len             ; initialise byte counter

        ldy #0
        jsr _asm_skip_sp        ; Y = first non-space position

        ; ── read 3 mnemonic characters → mn_c1, mn_c2, mn_c3 ─────────────────
        jsr _asm_rd_upper
        sta mn_c1
        jsr _asm_rd_upper
        sta mn_c2
        jsr _asm_rd_upper
        sta mn_c3

        ; Advance asm_ptr past the mnemonic (Y bytes consumed so far).
        jsr _asm_adv            ; asm_ptr += Y; Y = 0

        ; Skip whitespace between mnemonic and operand.
        jsr asm_skip_ws         ; Y = offset of first operand character

        ; Advance asm_ptr to the start of the operand; reset Y=0 for mode_parse.
        jsr _asm_adv            ; asm_ptr += Y; Y = 0

        ; ── classify mnemonic ─────────────────────────────────────────────────
        jsr mn_classify
        bcc @found
        jmp asm_error           ; unknown mnemonic
@found:
        sta asm_slot
        tax
        lda mn_base_op,x
        sta asm_base
        lda mn_profile,x
        sta asm_prof
        and #$1F
        sta asm_pidx            ; raw profile index

        ; ── CMOS gate / upgrade ───────────────────────────────────────────
        ; On non-CMOS builds (mn6), cat=11 and cat=01 mnemonics are not
        ; in the hash table, so this code is never reached.  The ifdef
        ; excludes it from the binary to save bytes.
.ifdef CMOS_SUPPORT
        lda asm_prof
        and #$C0
        cmp #$C0                ; cat=11 (pure CMOS mnemonic)?
        bne @not_cmos_only
        lda asm_cpu
        cmp #2
        bcs @no_upgrade         ; 65C02 → allow, no pidx upgrade needed
        jmp asm_error           ; 6502/6510 → reject
@not_cmos_only:
        cmp #$40                ; cat=01 (legal + CMOS extension)?
        bne @no_upgrade
        lda asm_cpu
        cmp #2
        bcc @no_upgrade         ; 6502/6510 → no CMOS upgrade
        inc asm_pidx            ; use the CMOS profile for mode validation
.endif ; CMOS_SUPPORT
@no_upgrade:

        ; ── reset Y=0 before zone dispatch ────────────────────────────────────
        ; mn7_classify clobbers Y (sets Y=mn_c2 for the hash table lookup).
        ; All zone paths that call mode_parse require Y=0 on entry.
        ldy #0

        ; ── zone dispatch ─────────────────────────────────────────────────────
        lda asm_pidx
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
        lda asm_base
        clc
        jmp _asm_emit           ; tail-call; _asm_emit preserves C

; ── Zone B: REL — branch target (absolute or raw offset) ─────────────────────
@zone_b:
        jsr mode_parse
        ; mode_parse returns MODE_ABS for a 4-digit $xxxx target, or
        ; MODE_ZP for a 2-digit $xx raw offset.
        cmp #MODE_ABS
        beq @rel_abs
        cmp #MODE_ZP
        beq :+
        jmp asm_error           ; neither ABS nor ZP
:       ; ZP: asm_opr[0] is the raw signed offset byte
        clc
        jmp _asm_emit_base_opr  ; tail-call; _asm_emit preserves C

@rel_abs:
        ; Compute signed offset = target − (asm_pc + 2)
        ; target = asm_opr[1]:asm_opr[0] (16-bit, little-endian)
        sec
        lda asm_opr             ; target lo
        sbc asm_pc              ; − pc lo
        sta asm_tmp
        lda asm_opr+1           ; target hi
        sbc asm_pc+1            ; − pc hi
        tax                     ; X = high byte of (target − pc)
        lda asm_tmp
        sec
        sbc #2                  ; − 2 (instruction size)
        bcs :+
        dex                     ; borrow propagated to hi byte
:       sta asm_tmp             ; asm_tmp = offset byte
        ; Validate: hi byte must be $00 (offset 0..+127) or $FF (−128..−1)
        cpx #$00
        beq @chk_pos
        cpx #$FF
        bne @err_range          ; hi neither $00 nor $FF → out of ±128 range
        lda asm_tmp
        cmp #$80                ; negative offset must be ≥ $80
        bcc @err_range
        bcs @emit_rel           ; always taken (C=1 from cmp)
@chk_pos:
        lda asm_tmp
        cmp #$80                ; positive offset must be < $80
        bcs @err_range
@emit_rel:
        lda asm_base
        jsr _asm_emit
        lda asm_tmp
        clc
        jmp _asm_emit           ; tail-call; _asm_emit preserves C
@err_range:
        jmp asm_error

; ── Zone C: IMM — immediate byte ─────────────────────────────────────────────
@zone_c:
        jsr mode_parse
        cmp #MODE_IMM
        bne @err_mode
        clc
        jmp _asm_emit_base_opr  ; tail-call; _asm_emit preserves C

; ── Zone D/E: bit-ops (RMB, SMB, BBR, BBS) — not yet tested ──────────────────
@zone_d:
@zone_e:
        jmp asm_error

; ── Zone F: ABS — JSR only ───────────────────────────────────────────────────
@zone_f:
        jsr mode_parse
        cmp #MODE_ABS
        bne @err_mode
        jsr _asm_emit_base_opr  ; emit base + lo byte
        lda asm_opr+1           ; hi
        clc
        jmp _asm_emit           ; tail-call; _asm_emit preserves C

; ── Zone G/H: multi-mode (profiles 6–29) ─────────────────────────────────────
@zone_gh:
        ; Parse the addressing-mode argument.
        jsr mode_parse
        sta asm_mode

        ; Validate mode against the effective profile's mode set.
        jsr asm_validate_mode
        bcc @mode_ok
@err_mode:
        jmp asm_error
@mode_ok:

        ; Compute opcode via the category/dir/profile dispatch in opcode_lookup.
        jsr asm_opcode_lookup   ; → A = opcode, or jmps asm_error
        jsr _asm_emit           ; emit opcode byte

        ; Emit operand bytes: 0, 1, or 2 depending on the mode.
        ldx asm_mode
        lda _asm_oplen,x        ; operand byte count for this mode
        beq @gh_done            ; 0 bytes → done
        tax                     ; X = oplen (1 or 2)

        ; Emit asm_opr[0]  (always present for 1- and 2-byte operands)
        lda asm_opr
        jsr _asm_emit           ; clobbers A, Y — X preserved

        dex
        beq @gh_done            ; oplen was 1 → done

        ; Emit asm_opr[1]  (hi byte for 2-byte operands)
        lda asm_opr+1
        clc
        jmp _asm_emit           ; tail-call; _asm_emit preserves C

@gh_done:
        clc
        rts
