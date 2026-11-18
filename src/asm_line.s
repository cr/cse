; asm_line.s — single-line instruction assembler
; Owner: doc/modules/asm_line.md
;
; Assembles one instruction from a PETSCII string and writes the resulting
; bytes to the output buffer.
;
; Format: MNEMONIC [OPERAND]
;   - MNEMONIC: 3 letters (PETSCII $41–$5A, $61–$7A or $C1–$DA; AND #$5F
;               folds them, _asm_rd_upper maps them to 1–26 for the hash
;               classifier); whitespace, end of line or ';' must follow
;   - OPERAND:  addressing-mode argument, same syntax as mode_parse accepts
;               (expressions and symbols via expr_eval_nb).
;               Zone B (REL): the operand is the target (narrow or wide);
;               the signed PC-relative offset is computed.
;
; Public entry point: asm_line (A/X = PETSCII text pointer)
;   Manages KERNAL banking, error recovery, SP save/restore.
;   Calls _asm_line_core internally.
;
; Internal entry point: _asm_line_core (KERNAL banked out)
;   asm_ptr   — ZP word pointing to the instruction string (PETSCII, null-terminated)
;   asm_pc    — current PC (lo, hi); required for REL offset computation
;   asm_out   — output buffer pointer (lo, hi)
;   asm_cpu   — 0 = 6502, 1 = 6510, 2 = 65C02 (global enumeration)
;   (sets Y = 0 itself)
;
; Exit (success):
;   asm_len — number of bytes written to [asm_out]
;   C = 0
;
; Error: jmp asm_error / asm_expr_error / asm_cpu_error (asm_err.s; does
;   not return — unwinds to _asm_saved_sp).  See asm_line.md § Design.

        .setcpu "6502"
        .include "platform.inc"

        .export asm_line
        .export _asm_line_core
        .import asm_error, asm_cpu_error   ; asm_err.s
        .import asm_expr_error, last_err, expr_fwd           ; asm_err.s, expr.s
        .export reg_a, reg_x, reg_y, reg_sp, reg_p
.ifdef PLATFORM_M65
        .export reg_z, reg_b
.endif

        ; zero-page variables (zp.s)
        .importzp asm_pc, asm_out, asm_len
        .importzp asm_slot, asm_prof, asm_pidx, asm_base, asm_mode, asm_cpu
        .importzp asm_tmp

        ; addr_mode.s interface
        .importzp asm_ptr, asm_opr
        .import   mode_parse, asm_skip_ws
        .import   _au_no_acc            ; we set this before mode_parse

        ; mnemonic classifier
        .importzp mn_c1, mn_c2, mn_c3
        .import   mn_classify
        .import   mn_base_op, mn_profile

        ; opcode tables and helpers (opcode_lookup.s, mn_asm_tables.s)
        .import   asm_opcode_lookup
        .import   mn_modes_lo           ; ACC-bit test for IMP→ACC promotion
        .import   asm_oplen             ; operand bytes per mode (generated)
        .importzp ASM_ZONE_G            ; first multi-mode pidx (generated constant)

        ; banking
        .import kernal_bank_out, kernal_bank_in

; Mode index constants (mirror addr_mode.s / ALL_MODES order)
MODE_IMP   = 0
MODE_ACC   = 1
MODE_IMM   = 2
MODE_ZP    = 3
MODE_ABS   = 6
MODE_REL   = 12

        .importzp _asm_saved_sp

; ── BSS ───────────────────────────────────────────────────────────────────────
.segment "BSS"
; Saved user-code register state — populated by debugger.s on BRK/NMI
; entry, displayed by repl.s::show_regs, and reloaded into the CPU by
; debugger.s before continuing.
reg_a:         .res 1          ; saved A
reg_x:         .res 1          ; saved X
reg_y:         .res 1          ; saved Y
reg_sp:        .res 1          ; saved SP
reg_p:         .res 1          ; saved P (status flags)
_asm_sink:     .res 3          ; bytes past a $FFFF wrap land here (refused)
.ifdef PLATFORM_M65
reg_z:         .res 1          ; saved Z  } the KERNAL's frame carries them
reg_b:         .res 1          ; saved B  } on m65 (debugger.md § save_userland_state)
.endif

; (kernel_zp_buf and userland_zp_buf — the ZP save/restore buffers for
; the kernel↔userland transitions — live in mem.s alongside the
; save_userland_zp / restore_userland_zp / save_kernel_zp /
; restore_kernel_zp primitives that operate on them.)

.segment "CODE"

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
        ldy #0                  ; (_asm_line_core also resets Y itself)
        jsr _asm_line_core

        ; ── output wrapped past $FFFF with bytes to spare? _asm_emit
        ; parked them in _asm_sink: refuse as an expression overflow.
        lda asm_out
        sec
        sbc #<(_asm_sink+1)
        tax
        lda asm_out+1
        sbc #>(_asm_sink+1)
        bne @fits
        cpx #3                  ; asm_out in _asm_sink+1 .. +3 ?
        bcs @fits
        lda #3                  ; ERR_OVERFLOW (expr.md)
        sta last_err
        jmp asm_expr_error
@fits:

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
        FAR_STA asm_out
        ; advance output pointer
        inc asm_out
        bne :+
        inc asm_out+1
        beq @wrap               ; $FFFF → $0000: never write the CPU port
:       inc asm_len
        rts
@wrap:  ldy #<_asm_sink         ; park any further byte (asm_line refuses)
        sty asm_out
        ldy #>_asm_sink
        sty asm_out+1
        FAR_BANK asm_out, BANK_CSE
        inc asm_len
        rts

; ── _asm_rd_upper ────────────────────────────────────────────────────────────
; Read one key character from (asm_ptr),y, advance Y, return it as 1–26.
; Letters only: AND #$5F folds PETSCII lowercase $61–$7A, shifted $C1–$DA
; (and $E1–$FA) onto $41–$5A; anything else — digit, punctuation, NUL,
; screen code — is `;?syntax` here, so mn_classify only ever sees 1–26
; (asm_line.md § asm_line).
_asm_rd_upper:
        lda (asm_ptr),y
        iny
        and #$5F
        sec
        sbc #$41                ; 'A' → 0
        cmp #26
        bcs @bad                ; not a letter
        adc #1                  ; C=0: A = 1..26
        rts
@bad:   jmp asm_error

; ── _asm_imm_chk — an IMM operand must fit a byte ───────────────────────────
; $00xx, or -128..-1 ($FF80..$FFFF); else expression overflow (asm_line.md
; § Immediate range).  Skipped when the operand read an undefined symbol
; (pass 0 sizes it with a dummy value).  Preserves A, Y.
_asm_imm_chk:
        bit expr_fwd
        bmi @ok                 ; undefined: pass-0 dummy, not checked
        ldx asm_opr+1
        beq @ok
        inx
        bne @ovfl               ; hi neither $00 nor $FF
        bit asm_opr
        bmi @ok                 ; $FF80..$FFFF: -128..-1
@ovfl:  lda #3                  ; ERR_OVERFLOW (expr.md)
        sta last_err
        jmp asm_expr_error
@ok:    rts

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

        ; The key is one word: whitespace, end of line or ';' must follow
        ; (no C64 key takes a suffix — asm_line.md § Mnemonic word).
        lda (asm_ptr),y
        beq @word_ok
        cmp #' '
        beq @word_ok
        cmp #$A0
        beq @word_ok
        cmp #';'
        beq @word_ok
        jmp asm_error
@word_ok:
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
        and #$3F
        sta asm_pidx            ; raw profile index (bits 5:0; 7:6 = cat)

        ; ── CPU-mode gate ─────────────────────────────────────────────────
        ;
        ; Gate matrix (asm_prof bits 7:6 encode category):
        ;   cat=00 (legal NMOS)    — accept on any asm_cpu
        ;   cat=01 (legal + CMOS)  — accept; upgrade pidx on asm_cpu>=2 (CMOS_SUPPORT only)
        ;   cat=10 (illegal NMOS)  — accept on asm_cpu=1 only (6510)
        ;   cat=11 (pure CMOS)     — accept on asm_cpu>=2 (CMOS_SUPPORT only)
        ;
        ; See doc/modules/asm_line.md § asm_cpu × category matrix.
        ;
        ; Reject paths are compiled unconditionally — the 6510 build
        ; (no CMOS_SUPPORT) uses mn7, which recognises CMOS and
        ; illegal mnemonics, so the gate must filter them by asm_cpu
        ; even though CMOS extensions aren't supported here.  Only the
        ; CMOS accept-and-upgrade paths stay under .ifdef CMOS_SUPPORT
        ; because they reference the CMOS profile table, which is
        ; absent in non-CMOS builds.  On mn6 builds (6502, USE_MN6)
        ; cat=01/10/11 are never produced by the classifier, so the
        ; reject paths sit dormant without cost.

        lda asm_prof
        and #$C0
        beq @no_upgrade         ; cat=00 (legal NMOS) → accept
        cmp #$C0                ; cat=11 (pure CMOS)?
        bne @chk_illegal
.ifdef CMOS_SUPPORT
        lda asm_cpu
        cmp #2
        bcs @no_upgrade         ; 65C02 (+ CMOS_SUPPORT) → accept
.endif
        jmp asm_cpu_error       ; else reject — `;?cpu` (pure-CMOS on non-CMOS CPU)
@chk_illegal:
        cmp #$80                ; cat=10 (illegal NMOS)?
        bne @chk_ext
        lda asm_cpu
        cmp #1
        beq @no_upgrade         ; 6510 → accept
        jmp asm_cpu_error       ; 6502 / 65C02 → reject — `;?cpu` (illegal mnemonic on non-6510)
@chk_ext:
        ; Fell through — cat=01 (legal + CMOS extension).
.ifdef CMOS_SUPPORT
        lda asm_cpu
        cmp #2
        bcc @no_upgrade         ; 6502/6510 → no upgrade (use NMOS profile)
        inc asm_pidx            ; 65C02 → upgrade to CMOS profile
.endif ; CMOS_SUPPORT
@no_upgrade:

        ; ── ACC-vs-label disambiguation flag ──────────────────────────────────
        ; Tell mode_parse whether the literal `A` operand is the ACC token
        ; (profile accepts ACC → flag = 0) or a single-letter label
        ; (profile rejects ACC → flag nonzero).  See
        ; doc/modules/asm_line.md § ACC mode handling.
        ldx asm_pidx
        lda mn_modes_lo,x
        and #$02                ; isolate MODE_ACC bit: $02 if accepted, $00 if not
        eor #$02                ; invert: $00 if accepted, $02 if not
        sta _au_no_acc

        ; ── reset Y=0 before zone dispatch ────────────────────────────────────
        ; mn7_classify clobbers Y (sets Y=mn_c2 for the hash table lookup).
        ; All zone paths that call mode_parse require Y=0 on entry.
        ldy #0

        ; ── zone dispatch ─────────────────────────────────────────────────────
        ; pidx < ASM_ZONE_G is a fixed zone; the generator numbers them
        ; A B F C D E and gives a CPU set only the zones it has, so the
        ; table below is indexed by pidx directly.
        lda asm_pidx
        cmp #ASM_ZONE_G
        bcc :+
        jmp @zone_gh            ; multi-mode G/H
:
        tax
        lda @ztbl_hi,x
        pha
        lda @ztbl_lo,x
        pha
        rts                     ; RTS trick → dispatches to (addr+1)

@ztbl_lo:
        .byte <(@zone_a-1), <(@zone_b-1), <(@zone_f-1)
        .byte <(@zone_c-1), <(@zone_d-1), <(@zone_e-1)
@ztbl_hi:
        .byte >(@zone_a-1), >(@zone_b-1), >(@zone_f-1)
        .byte >(@zone_c-1), >(@zone_d-1), >(@zone_e-1)

; ── Zone A: implied — the operand must be empty ──────────────────────────────
; End of line, ';' or '//' comment (whitespace already skipped, Y=0).
@zone_a:
        lda (asm_ptr),y
        beq @a_ok
        cmp #';'
        beq @a_ok
        cmp #'/'
        bne @a_bad
        iny
        cmp (asm_ptr),y         ; '//'?
        bne @a_bad
@a_ok:  lda asm_base
        clc
        jmp _asm_emit           ; tail-call; _asm_emit preserves C
@a_bad: jmp asm_error

; ── Zone B: REL — branch target ──────────────────────────────────────────────
@zone_b:
        jsr mode_parse
        ; The operand is the target, wide (MODE_ABS) or narrow (MODE_ZP —
        ; a zero-page target; asm_opr[1] is already 0 for a narrow value).
        cmp #MODE_ABS
        beq @rel_abs
        cmp #MODE_ZP
        beq @rel_abs
        jmp asm_error           ; neither ABS nor ZP

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
        jsr _asm_imm_chk
        clc
        jmp _asm_emit_base_opr  ; tail-call; _asm_emit preserves C

; ── Zone D/E: bit-ops (RMB, SMB, BBR, BBS) — not assembled yet ───────────────
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

; ── Zone G/H: multi-mode (pidx >= ASM_ZONE_G) ────────────────────────────────
@zone_gh:
        ; Parse the addressing-mode argument.
        jsr mode_parse
        sta asm_mode
        cmp #MODE_IMM
        bne :+
        jsr _asm_imm_chk        ; A = MODE_IMM kept (≠ 0)
:
        ; ── IMP → ACC promotion for ACC-accepting profiles ────────────────
        ; A bare mnemonic on an ACC-accepting profile (ASL, LSR, ROL,
        ; ROR; CMOS DEC, INC) means accumulator mode.  mode_parse
        ; returns MODE_IMP for an empty operand; promote to MODE_ACC here
        ; when the profile accepts ACC.  We reuse `_au_no_acc` (set above
        ; from the same `mn_modes_lo[asm_pidx] & MODE_ACC_BIT` test that
        ; gates the SC_A path in mode_parse) instead of re-reading the
        ; table — same signal, half the bytes.  Profiles that reject ACC
        ; keep MODE_IMP and fall to asm_opcode_lookup, which rejects (the
        ; documented "bare implied is invalid for non-ACC multi-mode"
        ; path).  See doc/modules/asm_line.md § ACC mode handling.
        cmp #0                  ; MODE_IMP = 0
        bne @lookup
        lda _au_no_acc
        bne @lookup             ; nonzero → ACC rejected → keep IMP
        lda #MODE_ACC
        sta asm_mode
@lookup:
        ; Validate the mode against the effective profile and compute the
        ; opcode: base ^ delta[row[pidx] + mode] (opcode_lookup.s).
        jsr asm_opcode_lookup   ; C=0: A = opcode; C=1: mode not accepted
        bcc @mode_ok
@err_mode:
        jmp asm_error
@mode_ok:
        jsr _asm_emit           ; emit opcode byte

        ; Emit operand bytes: 0, 1, or 2 depending on the mode.
        ldx asm_mode
        lda asm_oplen,x         ; operand byte count for this mode
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
