; asm_line.s — single-line instruction assembler
; Owner: doc/modules/asm_line.md
;
; Assembles one instruction from a PETSCII string and writes the resulting
; bytes to the output buffer.
;
; Format: MNEMONIC [OPERAND]
;   - MNEMONIC: 3 letters (PETSCII $41–$5A, $61–$7A or $C1–$DA; AND #$5F
;               folds them, _asm_rd_upper maps them to 1–26 for the hash
;               classifier), then a bit digit (RMB/SMB/BBR/BBS) or, on
;               m65, a `q` suffix (asm_line.md § Mnemonic word);
;               whitespace, end of line or ';' must follow
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
;   asm_cpu   — 0 = 6502, 1 = 6510, 2 = 65C02, 3 = 4510, 4 = 45GS02
;               (global enumeration; the build's CPU set)
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

; The digit zones D/E (RMB SMB BBR BBS) exist in the CMOS mode and the
; 4510 set; only they read a digit suffix (asm_line.md § Mnemonic word).
.ifdef CMOS_SUPPORT
  BIT_OPS = 1
.endif
.ifdef MEGA_SUPPORT
  BIT_OPS = 1
.endif
.ifdef BIT_OPS
        .importzp ASM_ZONE_D            ; zone D's pidx, E = D + 1 (generated)
        .importzp asm_tmp2              ; ZPREL's zero-page byte (mode_parse)
.endif

        ; banking
        .import kernal_bank_out, kernal_bank_in

; Mode index constants (mirror addr_mode.s / ALL_MODES order)
MODE_IMP   = 0
MODE_ACC   = 1
MODE_IMM   = 2
MODE_ZP    = 3
MODE_ABS   = 6
MODE_REL   = 12
MODE_ZPI   = 13
MODE_ZPREL = 15
.ifdef MEGA_SUPPORT
MODE_IMM16 = 16
MODE_REL16 = 17
MODE_ISPY  = 18
MODE_ZPIZ  = 19
PFX_Q      = %00000001      ; asm_pfx: emit $42 $42
PFX_FAR    = %00000010      ;          emit $EA
PFX_QSFX   = %01000000      ;          the word had the `q` suffix
PFX_W16    = %10000000      ;          the caller's REL16 request
        .importzp ASM_ZONE_Q, ASM_ZONE_H
        .import   mn7_c02, _au_far, _bit_tab
SINK_SIZE  = 4                  ; a 5-byte instruction may overrun by 4
.else
SINK_SIZE  = 3
.endif

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
.ifdef PLATFORM_M65
reg_z:         .res 1          ; saved Z  } the KERNAL's frame carries them on
reg_b:         .res 1          ; saved B  } m65; reg_a + 5 / + 6 for `r` (repl.s)
.endif
_asm_sink:     .res SINK_SIZE  ; bytes past a $FFFF wrap land here (refused)
.ifdef MEGA_SUPPORT
        .export asm_rel16
asm_pfx:       .res 1          ; this instruction's prefixes (PFX_*)
asm_rel16:     .res 1          ; caller: $80 = a branch takes REL16 (cleared here)
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
        cpx #SINK_SIZE          ; asm_out in _asm_sink+1 .. +SINK_SIZE ?
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

.ifndef MEGA_SUPPORT
; ── _asm_rel8 — an 8-bit branch offset ───────────────────────────────────────
; In: A = the instruction's length, asm_opr = the target, asm_pc.
; Out: X = target − (asm_pc + A), which must be −128..127, else
; asm_error (`;?syntax`).  Clobbers A, Y, asm_tmp.
_asm_rel8:
        sta asm_tmp             ; the length
        sec
        lda asm_opr
        sbc asm_pc
        tay
        lda asm_opr+1
        sbc asm_pc+1
        tax                     ; X:Y = target − asm_pc
        tya
        sec
        sbc asm_tmp
        bcs :+
        dex                     ; X:A = the offset, 16 bits
:       cpx #0                  ; in reach iff X is A's sign extension
        beq @pos
        inx
        bne @range              ; X neither $00 nor $FF
        cmp #$80
        bcs @ok                 ; −128..−1
@range: jmp asm_error
@pos:   cmp #$80
        bcs @range              ; above 127
@ok:    tax
        rts

.else
; ── _asm_c02 — the key's mn7_c02 bit ──────────────────────────────────────────
; Out: A ≠ 0 (and Z = 0) when the 65C02 has the key (cat 11) or its
; extension (cat 01) (mn_classify.md), else 0.  Clobbers X, Y.
_asm_c02:
        lda asm_slot
        and #7
        tay
        lda asm_slot
        lsr
        lsr
        lsr
        tax
        lda _bit_tab,y
        and mn7_c02,x
        rts

; ── _asm_reld — a branch offset, 16 bits ──────────────────────────────────────
; In: A = the instruction's length, asm_opr = the target, asm_pc.
; Out: asm_opr = d = target − (asm_pc + A); C = 0 when d fits a byte
; (−128..127; REL16 counts from the same last byte).  Clobbers A, X,
; asm_tmp.
_asm_reld:
        clc
        adc asm_pc
        sta asm_tmp
        lda asm_pc+1
        adc #0
        tax                     ; X:asm_tmp = asm_pc + A
        sec
        lda asm_opr
        sbc asm_tmp
        sta asm_opr
        stx asm_tmp
        lda asm_opr+1
        sbc asm_tmp
        sta asm_opr+1
        ; fall through
; ── _asm_fits8 — C = 0 when asm_opr (16 bits) is −128..127 ────────────────────
_asm_fits8:
        clc
        lda asm_opr
        adc #$80                ; C = 1 from $80..$FF
        lda asm_opr+1
        adc #0                  ; 0 exactly for $FF80..$007F
        cmp #1
        rts

; ── _asm_m65_mode — the m65 rules on a parsed mode ────────────────────────────
; In: asm_mode.  Out: asm_mode, A = it; asm_pfx gains PFX_FAR.
; Far ([e], [e],z) on the 45GS02 only (;?cpu); on the 65C02 `(e,sp),y` is
; ;?cpu, a written `,z` ;?syntax and `(e)` the 4510's ZPIZ where the
; profile has no ZPI; `#e` on a profile without IMM but with IMM16 is
; IMM16 (asm_line.md § Prefixes, § IMM16 promotion, § gate matrix).
_asm_m65_mode:
        lda _au_far
        beq @not_far
        lda asm_cpu
        cmp #4
        bne @cpu
        lda asm_pfx
        ora #PFX_FAR
        sta asm_pfx
@not_far:
        lda asm_cpu
        cmp #2
        bne @imm16
        lda asm_mode
        cmp #MODE_ISPY
        beq @cpu
        cmp #MODE_ZPIZ
        beq @syntax
        cmp #MODE_ZPI
        bne @imm16
        jsr asm_opcode_lookup   ; C = 0: the profile has ZPI itself
        bcc @imm16
        lda #MODE_ZPIZ
        sta asm_mode
@imm16: lda asm_mode
        cmp #MODE_IMM
        bne @done
        jsr asm_opcode_lookup   ; C = 0: IMM
        bcc @done
        lda #MODE_IMM16
        sta asm_mode
@done:  lda asm_mode
        rts
@cpu:   jmp asm_cpu_error
@syntax:
        jmp asm_error

; ── _asm_prefixes — emit the instruction's prefixes; A kept ──────────────────
_asm_prefixes:
        pha
        lda asm_pfx
        and #PFX_Q
        beq :+
        lda #$42
        jsr _asm_emit
        lda #$42
        jsr _asm_emit
:       lda asm_pfx
        and #PFX_FAR
        beq :+
        lda #$EA
        jsr _asm_emit
:       pla
        rts
.endif

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
.ifdef MEGA_SUPPORT
        lda asm_rel16           ; the caller's width request starts asm_pfx;
        sta asm_pfx             ;   cleared now, so no exit leaves it set
        lda #0
        sta asm_rel16
.else
        lda #0
.endif
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

.ifdef BIT_OPS
        ; An optional digit suffix 0-7: asm_tmp = bit << 4 | 1, else 0
        ; (bit 0 is set in every digit-zone opcode, so `ora` keeps it).
        ldx #0
        lda (asm_ptr),y
        sec
        sbc #$30                ; '0'
        cmp #8
        bcs :+
        asl
        asl
        asl
        asl
        ora #1
        tax
        iny
:       stx asm_tmp
.endif
.ifdef MEGA_SUPPORT
        ; Or the `q` suffix: the Q form of a quad stem (judged after the gate).
        txa
        bne @no_q               ; a digit already
        lda (asm_ptr),y
        and #$5F
        cmp #$51                ; 'Q'
        bne @no_q
        iny
        lda asm_pfx
        ora #PFX_QSFX
        sta asm_pfx
@no_q:
.endif

        ; The word ends here: whitespace, end of line or ';' must follow
        ; (asm_line.md § Mnemonic word).
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
        ; asm_prof bits 7:6 are the key's category; a set holds only its
        ; own keys, so each set's gate sees only its own categories
        ; (asm_line.md § asm_cpu × category gate matrix):
        ;   c64-6502      cat 00 only — no gate
        ;   c64-6510      00 accept; 10 (illegal) on the 6510 only
        ;   the CMOS mode 00 accept; 01 the CMOS profile on the 65C02,
        ;                 the NMOS one on the 6502; 11 on the 65C02 only
        ;   m65           below

.ifdef MEGA_SUPPORT
        ; m65 (asm_line.md § gate matrix, m65 table): cat 00 accept; 01
        ; the extension on 4510 / 45GS02, and on the 65C02 where mn7_c02
        ; says so; 10 a Q name, 45GS02 only (its Q prefix); 11 on 4510 /
        ; 45GS02, and on the 65C02 where mn7_c02 says so.
        lda asm_prof
        and #$C0
        beq @no_upgrade         ; cat 00
        ldx asm_cpu
        beq @cpu_err            ; the 6502: only cat 00 / cat 01's NMOS
        cmp #$80
        beq @qname
        cpx #2
        bne @m_4510             ; 4510, 45GS02
        pha
        jsr _asm_c02            ; A ≠ 0: the 65C02 has it
        tax
        pla
        cpx #0
        beq @cpu_err
@m_4510:
        cmp #$40
        bne @no_upgrade         ; cat 11: accept
        inc asm_pidx            ; cat 01: the extension profile
        bne @no_upgrade         ; (always)
@cpu_err:
        cmp #$40                ; (A = cat) cat 01: its NMOS profile
        beq @no_upgrade
        jmp asm_cpu_error
@qname: cpx #4
        bne @cpu_err
        lda asm_pfx
        ora #PFX_Q
        sta asm_pfx
.elseif .defined(CMOS_SUPPORT)
        lda asm_prof
        and #$C0
        beq @no_upgrade         ; cat 00
        ldx asm_cpu
        beq @c_6502
        cmp #$40
        bne @no_upgrade         ; cat 11 on the 65C02: accept
        inc asm_pidx            ; cat 01: the CMOS profile
        bne @no_upgrade         ; (always)
@c_6502:
        cmp #$40
        beq @no_upgrade         ; cat 01 on the 6502: its NMOS profile
        jmp asm_cpu_error       ; cat 11: `;?cpu`
.elseif .defined(CPU_6510)
        lda asm_prof
        and #$C0
        beq @no_upgrade         ; cat 00
        lda asm_cpu             ; cat 10 (illegal): the 6510 only
        cmp #1
        beq @no_upgrade
        jmp asm_cpu_error
.endif
@no_upgrade:

.ifdef MEGA_SUPPORT
        ; ── the `q` suffix: a quad stem's Q form, on the 45GS02 ────────────
        ; Accepted iff the key is no Q name and its effective profile lies in
        ; zone Q; the Q profile is the next.  Else ;?cpu for a quad stem off
        ; the 45GS02, ;?syntax for any other key (asm_line.md § gate matrix).
        bit asm_pfx
        bvc @q_done             ; no `q`
        lda asm_prof
        and #$C0
        cmp #$80
        beq @q_bad              ; a Q name takes no suffix
        lda asm_pidx
        cmp #ASM_ZONE_Q
        bcc @q_bad
        cmp #ASM_ZONE_H
        bcs @q_bad              ; no quad stem
        ldx asm_cpu
        cpx #4
        beq :+
        jmp asm_cpu_error
:       inc asm_pidx            ; the Q profile
        lda asm_pfx
        ora #PFX_Q
        sta asm_pfx
        bne @q_done             ; (always)
@q_bad: jmp asm_error
@q_done:
.endif

.ifdef BIT_OPS
        ; ── the digit suffix: exactly on the digit zones D/E ──────────────
        lda asm_pidx
        sec
        sbc #ASM_ZONE_D
        cmp #2                  ; C = 0: zone D or E
        lda asm_tmp             ; Z = 1: no digit (C kept)
        bcs @no_dz
        bne @digit_ok           ; a digit zone with its digit
        jmp asm_error
@no_dz:
        beq @digit_ok           ; no digit on another key
        jmp asm_error
@digit_ok:
.endif

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
.ifdef MEGA_SUPPORT
        lda asm_pfx             ; after a Q form `a` is a label: bare only
        and #PFX_Q              ;   (asm_line.md § Mnemonic word)
        beq :+
        sta _au_no_acc
:
.endif

        ; ── reset Y=0 before zone dispatch ────────────────────────────────────
        ; mn7_classify clobbers Y (sets Y=mn_c2 for the hash table lookup).
        ; All zone paths that call mode_parse require Y=0 on entry.
        ldy #0

        ; ── zone dispatch ─────────────────────────────────────────────────────
        ; pidx < ASM_ZONE_G is a fixed zone; the generator numbers them
        ; A B F C D E and gives a CPU set only the zones it has, so the
        ; table below is indexed by pidx directly (on m65 zone B is
        ; three profiles, REL, REL + REL16, REL16: pidx 1-3).
        lda asm_pidx
        cmp #ASM_ZONE_G
        bcc :+
        jmp @zone_gh            ; multi-mode G/H
:       tax
        lda @ztbl_hi,x
        pha
        lda @ztbl_lo,x
        pha
        rts                     ; RTS trick → dispatches to (addr+1)

@ztbl_lo:
        .byte <(@zone_a-1), <(@zone_b-1)
.ifdef MEGA_SUPPORT
        .byte <(@zone_b-1), <(@zone_b-1)
.endif
        .byte <(@zone_f-1)
        .byte <(@zone_c-1), <(@zone_d-1), <(@zone_e-1)
@ztbl_hi:
        .byte >(@zone_a-1), >(@zone_b-1)
.ifdef MEGA_SUPPORT
        .byte >(@zone_b-1), >(@zone_b-1)
.endif
        .byte >(@zone_f-1)
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
.ifdef MEGA_SUPPORT
        ; asm_opr := d = target − (asm_pc + 2), 16 bits: REL's offset if
        ; it fits a byte, REL16's in any case (from the last byte).
        lda #2
        jsr _asm_reld
        ; The width (asm_line.md § Branches): the caller's REL16 request
        ; where the profile has REL16; else REL for a forward target or
        ; one in reach; else REL16; else out of range.
        bit asm_pfx
        bpl @b_auto
        jsr @b_try16
        bcc @b_emit16
@b_auto:
        lda #MODE_REL
        sta asm_mode
        jsr asm_opcode_lookup   ; C = 1: no REL (BSR)
        bcs @b_16
        pha                     ; the REL opcode
        jsr _asm_fits8          ; C = 0: in reach
        lda expr_fwd
        bne @b_8                ; a forward target takes REL
        bcc @b_8
        pla
@b_16:  jsr @b_try16
        bcs @b_err
@b_emit16:
        jsr _asm_emit
        lda asm_opr
        jsr _asm_emit
        lda asm_opr+1
        clc
        jmp _asm_emit
@b_8:   pla                     ; (keeps C)
        bcs @b_err              ; a forward REL out of reach
        jsr _asm_emit
        lda asm_opr
        clc
        jmp _asm_emit
@b_try16:                       ; C = 0, A = the REL16 opcode; the 65C02 has none
        lda asm_cpu
        cmp #2
        sec
        beq :+
        lda #MODE_REL16
        sta asm_mode
        jmp asm_opcode_lookup
:       rts
@b_err: jmp asm_error
.else
        lda #2                  ; the instruction's length
        jsr _asm_rel8           ; X = offset
        lda asm_base
        jsr _asm_emit           ; preserves X
        txa
        clc
        jmp _asm_emit           ; tail-call; _asm_emit preserves C
.endif

; ── Zone C: IMM — immediate byte ─────────────────────────────────────────────
@zone_c:
        jsr mode_parse
        cmp #MODE_IMM
        bne @err_mode
        jsr _asm_imm_chk
        clc
        jmp _asm_emit_base_opr  ; tail-call; _asm_emit preserves C

; ── Zone D/E: bit-ops — the digit (asm_tmp) is the bit ────────────────────────
.ifdef BIT_OPS
@zone_d:                        ; RMB / SMB zp
        jsr mode_parse
        cmp #MODE_ZP
        bne @err_mode
        lda asm_base
        ora asm_tmp
        jsr _asm_emit
        lda asm_opr
        clc
        jmp _asm_emit           ; tail-call; _asm_emit preserves C
@zone_e:                        ; BBR / BBS zp,target
        jsr mode_parse          ; ZPREL: asm_opr = target, asm_tmp2 = zp
        cmp #MODE_ZPREL
        bne @err_mode
        lda asm_base
        ora asm_tmp             ; the opcode, before the offset takes asm_tmp
        pha
        lda #3                  ; the instruction's length
.ifdef MEGA_SUPPORT
        jsr _asm_reld
        bcs @b_err
        ldx asm_opr             ; X = offset
.else
        jsr _asm_rel8           ; X = offset
.endif
        pla
        jsr _asm_emit           ; preserves X
        lda asm_tmp2
        jsr _asm_emit
        txa
        clc
        jmp _asm_emit
.else
@zone_d:                        ; (no digit zone in this CPU set)
@zone_e:
.endif

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
.ifdef MEGA_SUPPORT
        jsr _asm_m65_mode       ; far, the 65C02's forms, IMM16; A = asm_mode
.endif
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
.ifndef MEGA_SUPPORT
        lda _au_no_acc
        bne @lookup             ; nonzero → ACC rejected → keep IMP
.endif                          ; m65: ACC always — after a Q form `a` is a
        lda #MODE_ACC           ;   label, but bare is ACC; no multi-mode
        sta asm_mode            ;   profile takes IMP, so the lookup judges
@lookup:
        ; Validate the mode against the effective profile and compute the
        ; opcode: base ^ delta[row[pidx] + mode] (opcode_lookup.s).
        jsr asm_opcode_lookup   ; C=0: A = opcode; C=1: mode not accepted
        bcc @mode_ok
@err_mode:
        jmp asm_error
@mode_ok:
.ifdef MEGA_SUPPORT
        jsr _asm_prefixes       ; $42 $42 if Q, $EA if far (A kept)
.endif
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
