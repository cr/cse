; asm_src.s — Two-pass source assembler
; Owner: doc/modules/asm_src.md
;
; Reads source from the editor gap buffer (ed_read_line).
; Pass 0: collect labels/constants, compute instruction sizes.
; Pass 1: resolve references, emit bytes.
;
; Internal calling convention:
;   _as_ptr  — active parse pointer into current line
;   _as_wsize — word size (1/2) for emit_data_bytes; reused as scratch elsewhere
;   All emit_* helpers read from expr_ptr; set expr_ptr before calling them.

        .setcpu         "6502"
        .include "platform.inc"
        .macpack longbranch
        .include "macros.inc"

        .export         asm_assemble
        .export         asm_org, asm_size, asm_errors
        .export         seg_print_save

        .import         asm_line                            ; asm_line.s
        .import         asm_err_code, asm_pass              ; asm_err.s
        .import         expr_error_str, expr_eval           ; expr.s
        .import         sym_define, sym_clear, sym_stamp    ; symtab.s
        .import         expr_fwd                            ; expr.s
SYM_P0 = $40                    ; symtab.s pass-0 stamp (symtab.md § Pass stamp)
        .import         kernal_bank_out, kernal_bank_in     ; mem.s
        .importzp       kernal_out                          ; zp.s
        .import         io_puts, io_putc, io_putdec, io_puthex4, io_clear_eol, newline
        .import         io_utoa, dec_buf                    ; cse_io.s (newline: screen.s)
        .import         log_open, log_close, seg_line, puts_imm   ; log.s
        .importzp       rp_addr, rp_cnt, rp_save2                 ; zp.s
        .import         str_tag_org
        .import         define_ws_syms                             ; gap_buffer.s
        .import         ed_read_line, ed_read_rewind              ; gap_buffer.s
        .importzp       cur_project_name           ; zp.s
        .importzp       buf_base                ; zp.s — gap buffer low bound = workend+1
        .importzp       rp_ptr2                 ; zp.s — scratch pointer (repl/info_line)
        .importzp       asm_pc, asm_out, asm_len, asm_cpu, asm_tmp, asm_tmp2
        .importzp       expr_ptr, expr_val, expr_wide
        .importzp       sym_name, sym_val, sym_wide

        .importzp _as_ptr, _as_wsize

; ── Imports: strings.s ──────────────────────────────────────
        .import s_err_sep, s_bad_val, s_exp_name, s_sym_full
        .import s_exp_quot, s_bad_insn, s_fwd_ref, str_cpu_err
        .import s_save_s, s_save_q_sp, s_save_default, s_trunc
        .import s_too_long, str_range, err_overflow

; ── BSS (all reset by asm_assemble before each run) ─────────────────────
.segment "BSS"
asm_org:       .res 2          ; origin of the first segment
_def_org:      .res 2          ; default origin (A/X): every pass starts here
_cpu_save:     .res 1          ; caller's asm_cpu: each pass starts with it
asm_size:      .res 2          ; total bytes emitted
asm_errors:    .res 2          ; error count (pass 1 only)
_line_num:      .res 2
_line_buf:      .res 40
MAX_LABEL = 23                  ; label name chars (local: after the dot)
INSN_MAX  = 57                  ; _insn_buf text chars (+ NUL)
_scope_name:    .res MAX_LABEL+1        ; last global label (for .local expansion)
_full_label:    .res 2*MAX_LABEL+2      ; scratch: "scope.local"
_insn_out       = _full_label   ; asm_line output scratch (process_line)
_insn_buf:      .res INSN_MAX+1 ; instruction text for asm_line, locals expanded
_as_conv:       .res 1          ; emit_string convert-to-screen-code flag
_eb_idx:        .res 1          ; .bas string length
_ib_idx:        .res 1          ; write index into _insn_buf

; ── Segment tracking (streaming during pass 1) ──────────────────────────
_seg_pc:        .res 2          ; start address of current segment
_min_pc:        .res 2          ; global lowest origin
_max_pc:        .res 2          ; global highest byte (exclusive)
_seg_open:      .res 1          ; non-zero if a segment is open
_pc_wrap:       .res 1          ; non-zero once asm_pc wrapped past $FFFF
_oor:           .res 1          ; non-zero: this line dropped a byte (range)
_org_set:       .res 1          ; non-zero after first .org on pass 0

; ── RODATA ────────────────────────────────────────────────────────────────
.segment "RODATA"


; ═══════════════════════════════════════════════════════════════════════════
.segment "CODE"
; ═══════════════════════════════════════════════════════════════════════════

        .include "log.inc"      ; LOG_ERR / LOG_WARN / LOG_INFO

; ── emit_error ─────────────────────────────────────────────────────────────
; Print error on pass 1 and increment error count.
;   In: A/X = PETSCII message pointer
.proc emit_error
        pha                     ; save msg lo BEFORE pass check
        lda asm_pass
        beq @skip
        txa
        pha                     ; save msg hi
        inc asm_errors
        bne :+
        inc asm_errors+1
        ; Bank KERNAL in for screen output (newline → io_sync
        ; needs KERNAL PLOT at $FFF0).  Direct $01 manipulation
        ; because kernal_out flag makes bank_in a no-op.
:       jsr _bank_in_tmp
        ldy #LOG_ERR
        jsr log_open        ; ";?"
        lda _line_num
        ldx _line_num+1
        jsr io_putdec
        puts s_err_sep          ; ": "
        pla
        tax                     ; msg hi
        pla                     ; msg lo
        jsr io_puts             ; error message
        jsr log_close           ; clear_eol
        jmp _bank_out_tmp       ; tail call (bank out + rts)
@skip:  pla                     ; discard saved msg lo
        rts
.endproc

; ── _bank_in_tmp / _bank_out_tmp ───────────────────────────────────────────
; Temporarily bank KERNAL in (for screen I/O during an assembly pass)
; or back out.  Used by emit_error and segment logging.
;
; These bypass mem.s's kernal_bank_in/out on purpose: asm_assemble
; sets `kernal_out = 1` for the duration of the passes so that the
; flag-gated helpers no-op — but emit_error / seg logging need real
; banking to reach the screen.  No SEI/CLI is needed: the $FFFE RAM
; vector (cse_brk_handler_early) handles IRQs while KERNAL is banked
; out.
_bank_in_tmp:
        BANK_FORCE_IN
        rts
_bank_out_tmp:
        BANK_FORCE_OUT
        rts

; ── skipws_ep ──────────────────────────────────────────────────────────────
; Advance expr_ptr past whitespace ($20/$A0).  A = first non-ws char on return.
.proc skipws_ep
        ldy #0
@lp:    lda (expr_ptr),y
        cmp #' '
        beq @eat
        cmp #$a0
        bne :+
@eat:   inc expr_ptr
        bne @lp
        inc expr_ptr+1
        jmp @lp
:       rts
.endproc


; ── skipws_as ──────────────────────────────────────────────────────────────
; Advance _as_ptr past whitespace ($20/$A0). A = first non-ws char on return.
.proc skipws_as
        ldy #0
@lp:    lda (_as_ptr),y
        cmp #' '
        beq @eat
        cmp #$a0
        bne :+
@eat:   inc _as_ptr
        bne @lp
        inc _as_ptr+1
        jmp @lp
:       rts
.endproc

; ── fold_char_a ────────────────────────────────────────────────────────────
; Fold PETSCII shifted uppercase $C1-$DA to plain uppercase $41-$5A.  In/out: A.
.proc fold_char_a
        cmp #$C1
        bcc :+
        cmp #$DB
        bcs :+
        sec
        sbc #$80
:       rts
.endproc

; ── is_ident ───────────────────────────────────────────────────────────────
; C=0 if A (after folding) is a valid identifier char (alpha/digit/dot).
.proc is_ident
        jsr fold_char_a
        cmp #$41
        bcc @chkd
        cmp #$5B
        bcc @yes
@chkd:  cmp #$30
        bcc @chkp
        cmp #$3A
        bcc @yes
@chkp:  cmp #$2E
        beq @yes
        sec
        rts
@yes:   clc
        rts
.endproc

; ── set_expr_off ───────────────────────────────────────────────────────────
; expr_ptr = _as_ptr + A  (skip A bytes of keyword)
.proc set_expr_off
        clc
        adc _as_ptr
        sta expr_ptr
        lda _as_ptr+1
        adc #0
        sta expr_ptr+1
        rts
.endproc

; ── inc_pc_size ────────────────────────────────────────────────────────────
; Increment asm_pc and asm_size by 1; an asm_pc wrap past $FFFF sets _pc_wrap.
inc_pc_size:
        inc asm_pc
        bne :+
        inc asm_pc+1
        bne :+
        inc _pc_wrap            ; $FFFF → $0000: later bytes are refused
:       inc asm_size
        bne :+
        inc asm_size+1
:       rts

; ── _emit_byte ────────────────────────────────────────────────────────────
; Emit byte in A to (asm_pc) on pass 1; advance asm_pc+asm_size always.
; The single gate for every output byte: only the workspace,
; WORKSTART <= asm_pc < buf_base (workstart..workend, as bp_range_check),
; and never after a wrap past $FFFF (_pc_wrap).  Otherwise the byte is
; dropped and _oor set — do_pass reports `range` once for the line.
; Preserves X.
_emit_byte:
        ldy asm_pass
        beq @skip
        ldy _pc_wrap
        bne @oor
        ldy asm_pc+1
        cpy #>WORKSTART
        bcc @oor                ; below $0800
        cpy buf_base+1
        bcc @ok
        bne @oor                ; at/above the source text
        ldy asm_pc
        cpy buf_base
        bcs @oor
@ok:    ldy #0
        FAR_STA asm_pc
@skip:  jmp inc_pc_size
@oor:   ldy #1
        sty _oor
        bne @skip               ; always

; ── _emit_word ────────────────────────────────────────────────────────────
; Emit 16-bit little-endian word from A (lo) / X (hi).
_emit_word:
        jsr _emit_byte          ; emit lo byte (A)
        txa
        jmp _emit_byte          ; emit hi byte

; ── _bad_val_err ──────────────────────────────────────────────────────────
; Shared "bad value" error tail for the directive handlers in this
; module.  Works equivalently when reached via JMP (tail-call: returns
; to the caller's caller via emit_error's rts) or JSR (returns to the
; caller after the jsr — emit_error's rts pops the saved return).
_bad_val_err:
        lda #<s_bad_val
        ldx #>s_bad_val
        jmp emit_error

; ── adv_pc_size ────────────────────────────────────────────────────────────
; asm_pc += _as_wsize;  asm_size += _as_wsize
.proc adv_pc_size
        lda _as_wsize
        clc
        adc asm_pc
        sta asm_pc
        bcc :+
        inc asm_pc+1
:       lda asm_size
        clc
        adc _as_wsize
        sta asm_size
        bcc :+
        inc asm_size+1
:       rts
.endproc

; ── fold_block ─────────────────────────────────────────────────────────────
; Fold shifted letters in (sym_name)[0..Y-1] to $41-$5A in place.
; Y preserved.  Clobbers A.
.proc fold_block
        tya
        pha                     ; save original Y
        dey
@lp:    lda (sym_name),y
        jsr fold_char_a
        sta (sym_name),y
        dey
        bpl @lp
        pla
        tay                     ; restore Y
        rts
.endproc

; ── emit_data_bytes ────────────────────────────────────────────────────────
; Emit comma-separated byte/word values from expression list.
;   In: expr_ptr = operand start; _as_wsize = 1 (byte) or 2 (word)
.proc emit_data_bytes
@loop:  jsr skipws_ep
        beq @rts
        cmp #';'
        bne :+
@rts:   rts
:       cmp #'"'
        bne @expr
        lda _as_wsize
        cmp #1
        bne @expr
        ; Quoted string (only in .db)
        inc expr_ptr
        bne @ql
        inc expr_ptr+1
@ql:    ldy #0
        lda (expr_ptr),y
        beq @done
        cmp #'"'
        beq @qc
        jsr _emit_byte
        inc expr_ptr
        bne @ql
        inc expr_ptr+1
        jmp @ql
@qc:    inc expr_ptr            ; skip closing '"'
        bne @comma
        inc expr_ptr+1
        bne @comma
@expr:  jsr expr_eval
        ; .db/.dw size is value-independent: every arg occupies
        ; exactly _as_wsize bytes whether the expression resolves
        ; or not.  Skip the rc check on pass 0; let _emit_byte's
        ; pass-aware advance handle size.  Pass 1 errors normally.
        ldy asm_pass
        beq @emit               ; pass 0: any rc → advance PC
        cmp #2
        bcc @emit               ; pass 1 success → emit
        jmp _bad_val_err
@emit:  lda _as_wsize
        cmp #2
        beq @word
        ldy asm_pass            ; .db on pass 1: the value must fit a
        beq @byte               ; byte, $00xx or -128..-1 ($FF80..)
        ldx expr_val+1
        beq @byte
        inx
        bne @ovfl
        bit expr_val
        bmi @byte
@ovfl:  lda #<err_overflow      ; reported; the low byte is still
        ldx #>err_overflow      ; emitted so the layout does not move
        jsr emit_error
@byte:  lda expr_val
        jsr _emit_byte
        jmp @comma
@word:  lda expr_val
        jsr _emit_byte
        lda expr_val+1
        jsr _emit_byte
@comma: jsr skipws_ep
        cmp #','
        bne @done
        inc expr_ptr
        bne :+
        inc expr_ptr+1
:       jmp @loop
@done:  rts
.endproc

; ── emit_string ────────────────────────────────────────────────────────────
; Emit PETSCII string, optionally converting to C64 screen codes.
;   In: expr_ptr = text start; A = 0 (raw) or 1 (screen codes)
.proc emit_string
        sta _as_conv
        jsr skipws_ep
        cmp #'"'
        beq :+
        lda #<s_exp_quot
        ldx #>s_exp_quot
        jmp emit_error
:       inc expr_ptr
        bne @lp
        inc expr_ptr+1
@lp:    ldy #0
        lda (expr_ptr),y
        beq @done
        cmp #'"'
        beq @close
        ; Screen code conversion (full PETSCII → screen code mapping)
        lda _as_conv
        beq @raw
        lda (expr_ptr),y
        cmp #$40
        bcc @raw_c              ; $00-$3F → identity
        cmp #$60
        bcc @sub40              ; $40-$5F → subtract $40
        cmp #$80
        bcc @sub20              ; $60-$7F → subtract $20
        cmp #$C0
        bcc @raw_c              ; $80-$BF → identity (reversed)
        cmp #$E0
        bcs @raw_c              ; $E0-$FF → identity
@sub80: sec
        sbc #$80                ; $C0-$DF → subtract $80
        bpl @ec                 ; always (result $40-$5F)
@sub40: sec
        sbc #$40                ; $40-$5F → subtract $40
        bpl @ec                 ; always (result $00-$1F)
@sub20: sec
        sbc #$20                ; $60-$7F → subtract $20
        bne @ec                 ; always (result $40-$5F)
@raw:   lda (expr_ptr),y
@raw_c:
@ec:    jsr _emit_byte
        inc expr_ptr
        bne @lp
        inc expr_ptr+1
        jmp @lp
@close: inc expr_ptr
        bne :+
        inc expr_ptr+1
:       jsr skipws_ep
        cmp #','
        bne @done
        inc expr_ptr
        bne :+
        inc expr_ptr+1
:       lda #1
        sta _as_wsize
        jsr emit_data_bytes     ; handle trailing bytes (e.g. ,0)
@done:  rts
.endproc

; ── _vocal_fwd_err ─────────────────────────────────────────────────────────
; Forward-reference error reporter for .res / .align — directives whose
; pass-0 size depends on the expression value and so cannot tolerate an
; unresolved symbol the way .db / .dw can.  Bypasses emit_error's
; silent-pass-0 guard by temporarily setting asm_pass=1 across the
; call.  Caller is expected to abort the directive after this returns.
.proc _vocal_fwd_err
        lda asm_pass
        pha
        lda #1
        sta asm_pass
        lda #<s_fwd_ref
        ldx #>s_fwd_ref
        jsr emit_error
        pla
        sta asm_pass
        rts
.endproc

; ── emit_reserve ───────────────────────────────────────────────────────────
; .res count [,fill]  In: expr_ptr = operand start
;
; The count expression must resolve on pass 0 — its value drives the
; directive's pass-0 size.  A forward ref there is reported (and
; counted) on pass 0 via _vocal_fwd_err and lays out nothing; on pass 1
; the symbol is defined, so the count is used — the assembly has
; already failed (asm_src.md § Design).  Other expression errors
; (parse, paren, overflow, divzero) follow the usual silent-pass-0 /
; vocal-pass-1 convention via emit_error.
.proc emit_reserve
        jsr expr_eval
        cmp #2
        bcc :+
        cmp #5                  ; ERR_UNDEFINED?
        bne @gen_err
        jsr _vocal_fwd_err      ; force vocal on both passes; rts to here
        rts                     ; abort the directive (no PC advance)
@gen_err:
        jmp _bad_val_err
:       lda expr_val
        sta _as_ptr             ; count lo
        lda expr_val+1
        sta _as_ptr+1           ; count hi
        lda #0
        sta _as_wsize           ; fill = 0 (default)
        jsr skipws_ep
        cmp #','
        bne @go
        inc expr_ptr
        bne :+
        inc expr_ptr+1
:       jsr expr_eval
        cmp #2
        bcc :+
        cmp #5                  ; ERR_UNDEFINED in fill expr?
        bne @gen_err2
        jsr _vocal_fwd_err
        rts
@gen_err2:
        jmp _bad_val_err
:       lda expr_val
        sta _as_wsize           ; fill byte
@go:    lda _as_ptr
        ora _as_ptr+1
        beq @done
@lp:    lda _as_wsize
        jsr _emit_byte
        lda _as_ptr
        bne :+
        dec _as_ptr+1
:       dec _as_ptr
        lda _as_ptr
        ora _as_ptr+1
        bne @lp
@done:  rts
.endproc

; ── emit_align ─────────────────────────────────────────────────────────────
; .align boundary   In: expr_ptr = operand start
;
; Like .res, the boundary value drives pass-0 size (padding count).
; A forward ref in the boundary is reported on pass 0 — see
; emit_reserve.
.proc emit_align
        jsr expr_eval
        cmp #2
        bcc :+
        cmp #5                  ; ERR_UNDEFINED?
        bne @gen_err
        jsr _vocal_fwd_err
        rts
@gen_err:
        jmp _bad_val_err
:       lda expr_val
        ora expr_val+1
        bne :+
        jmp _bad_val_err
:       ; remainder = asm_pc % boundary (repeated subtraction; boundary in expr_val)
        lda asm_pc
        sta _as_ptr
        lda asm_pc+1
        sta _as_ptr+1
@mod:   lda _as_ptr+1
        cmp expr_val+1
        bcc @rem
        bne @sub
        lda _as_ptr
        cmp expr_val
        bcc @rem
@sub:   lda _as_ptr
        sec
        sbc expr_val
        sta _as_ptr
        lda _as_ptr+1
        sbc expr_val+1
        sta _as_ptr+1
        jmp @mod
@rem:   lda _as_ptr
        ora _as_ptr+1
        beq @done               ; already aligned (remainder = 0)
        ; pad = boundary - remainder; store pad in _as_ptr
        lda expr_val
        sec
        sbc _as_ptr
        sta _as_ptr
        lda expr_val+1
        sbc _as_ptr+1
        sta _as_ptr+1
@lp:    lda _as_ptr
        ora _as_ptr+1
        beq @done
        lda #0
        jsr _emit_byte
        lda _as_ptr
        bne :+
        dec _as_ptr+1
:       dec _as_ptr
        jmp @lp
@done:  rts
.endproc

; ── set_cpu ────────────────────────────────────────────────────────────────
; .cpu 6502 / 6510 / 65c02   In: expr_ptr = text after "cpu"
; (accepted on every build — no CPU-set check yet, TODO § M65)
.proc set_cpu
        jsr skipws_ep
        ldy #0
        lda (expr_ptr),y
        cmp #'6'
        bne @bad
        iny
        lda (expr_ptr),y
        cmp #'5'
        bne @bad
        iny
        lda (expr_ptr),y        ; [2]
        cmp #'0'
        bne @no6502
        iny
        lda (expr_ptr),y        ; [3]
        cmp #'2'
        bne @bad
        lda #0
        sta asm_cpu              ; 6502
        rts
@no6502:
        cmp #'1'
        bne @no6510
        iny
        lda (expr_ptr),y        ; [3]
        cmp #'0'
        bne @bad
        lda #1
        sta asm_cpu              ; 6510
        rts
@no6510:
        cmp #'c'                ; "65c02"
        bne @bad
        iny
        lda (expr_ptr),y        ; [3]
        cmp #'0'
        bne @bad
        iny
        lda (expr_ptr),y        ; [4]
        cmp #'2'
        bne @bad
        lda #2
        sta asm_cpu              ; 65c02
        rts
@bad:   jmp _bad_val_err
.endproc


; ── Segment logging (streaming during pass 1) ───────────────────────────
; Print segment info during pass 1 as .org/.bas directives are encountered.
; Temporarily banks KERNAL in for screen output (same as emit_error).
; Pass 0: tracking only, no I/O.
;
; _seg_log_close — close current segment: print "-BBBB  NNb", update _max_pc.
;   Suppresses empty segments (asm_pc == _seg_pc).
_seg_log_close:
        lda _seg_open
        bne :+
        rts                     ; not open → early out
:       ; Empty check: asm_pc == _seg_pc → suppress
        lda asm_pc
        cmp _seg_pc
        bne @nonempty
        lda asm_pc+1
        cmp _seg_pc+1
        bne @nonempty
        jmp @clear
@nonempty:
        ; Update _max_pc (exclusive end = asm_pc)
        lda asm_pc+1
        cmp _max_pc+1
        bcc @no_max
        bne @set_max
        lda asm_pc
        cmp _max_pc
        bcc @no_max
        beq @no_max
@set_max:
        lda asm_pc
        sta _max_pc
        lda asm_pc+1
        sta _max_pc+1
@no_max:
        ; Update _min_pc (only non-empty segments reach here)
        lda _seg_pc+1
        cmp _min_pc+1
        bcc @new_min
        bne @print
        lda _seg_pc
        cmp _min_pc
        bcs @print
@new_min:
        lda _seg_pc
        sta _min_pc
        lda _seg_pc+1
        sta _min_pc+1
@print:
        ; Print on pass 1 only
        lda asm_pass
        beq @clear
        ; Compute inclusive end = asm_pc - 1
        lda asm_pc
        sec
        sbc #1
        sta asm_tmp             ; end_lo
        lda asm_pc+1
        sbc #0
        sta asm_tmp2            ; end_hi
        jsr _bank_in_tmp
        ; Print "; org  AAAA-BBBB NNNNNb" via shared formatter
        lda #0
        sta rp_save2            ; no highlight
        lda #<str_tag_org
        sta rp_ptr2
        lda #>str_tag_org
        sta rp_ptr2+1
        lda _seg_pc
        sta rp_addr
        lda _seg_pc+1
        sta rp_addr+1
        lda asm_tmp             ; end_lo (asm_pc-1)
        sta rp_cnt
        lda asm_tmp2            ; end_hi
        sta rp_cnt+1
        jsr seg_line
        jsr _bank_out_tmp
@clear: lda #0
        sta _seg_open
@ret:   rts

; _seg_log_open — open a new segment at current asm_pc.
;   No screen I/O — segment line printed at close time.
_seg_log_open:
        lda asm_pc
        sta _seg_pc
        lda asm_pc+1
        sta _seg_pc+1
        lda #1
        sta _seg_open
        rts

; _org_set_pc — .org/.bas just set asm_pc: clear the wrap state, then
;   fall into _set_first_org.
_org_set_pc:
        lda #0
        sta _pc_wrap
; _set_first_org — set asm_org from asm_pc on pass 0, first time only.
;   Called by .org and .bas handlers after setting asm_pc.
_set_first_org:
        lda asm_pass
        bne @ret
        lda _org_set
        bne @ret
        inc _org_set
        lda asm_size            ; bytes before the first .org: the
        ora asm_size+1          ; default segment is the first one
        bne @ret
        lda asm_pc
        sta asm_org
        lda asm_pc+1
        sta asm_org+1
@ret:   rts

; _seg_init — reset segment logging state.
_seg_init:
        lda #0
        sta _seg_open
        sta _org_set
        sta _max_pc
        sta _max_pc+1
        lda #$FF
        sta _min_pc
        sta _min_pc+1
        rts

; seg_print_save — print executable save command.
;   Called by repl @h_a after successful assembly (KERNAL banked in).
;   Format: AAAA:s "project" $BBBB
;
;   Project name is a clean stem (no `,s`/`,p` suffix, no trailing
;   dot — parse_ls_args normalises before storing).  The presence of
;   the `$BBBB` address argument alone tells the `s` command to save
;   as PRG (derived name = stem + ".").
seg_print_save:
        ; Skip if no segments (_min_pc still $FFFF sentinel)
        lda _min_pc
        and _min_pc+1
        cmp #$FF
        beq @ret                ; @ret is a few bytes below — short branch fits
        lda _min_pc
        ldx _min_pc+1
        jsr io_puthex4
        lda #':'
        jsr io_putc
        puts s_save_s           ; "s ""
        ; Filename: cur_project_name if non-empty, else "out"
        lda cur_project_name
        bne @have_name
        puts s_save_default     ; "out"
        jmp @name_done
@have_name:
        lda #<BP_ABS(cur_project_name)
        ldx #>BP_ABS(cur_project_name)
        jsr io_puts
@name_done:
        puts s_save_q_sp        ; "" $"
        ; _max_pc is the first byte PAST the assembled range (exclusive
        ; end).  The `s` command uses the INCLUSIVE-end convention for
        ; its address argument, matching the `; TAG AAAA-BBBB NNNb`
        ; segment summary lines, so print _max_pc - 1.
        lda _max_pc
        sec
        sbc #1
        pha
        lda _max_pc+1
        sbc #0
        tax
        pla
        jsr io_puthex4
        jsr io_clear_eol
        jmp newline             ; advance so prompt goes on next row
@ret:   rts

; ── emit_bas ──────────────────────────────────────────────────────────────
; Emit a single-line BASIC SYS stub at asm_pc.
; expr_ptr points past the ".bas" keyword.
;
; Without string: `0 SYS NNNNN`
; With string:    `0 SYS NNNNN:REM TEXT`
;
; Layout: link(2) + linenum 0(2) + SYS(1) + 5 digits
;         + [':' + REM + ' ' + string(len)] + NUL(1) + end(2)
; Total:  13 bytes (no string) or 16 + len (with string).
;
; Uses asm_tmp/asm_tmp2 for SYS address, _eb_idx for string length.
BASIC_SYS = $9E
BASIC_REM = $8F

.proc emit_bas
        ; ── Parse optional string argument ─────────────────────────────
        jsr skipws_ep           ; expr_ptr is past "bas" (process_directive)
        lda #0
        sta _eb_idx             ; string length = 0 (no REM)
        ldy #0
        lda (expr_ptr),y
        cmp #'"'
        bne @no_str
        iny
@slen:  lda (expr_ptr),y
        beq @slen_done
        cmp #'"'
        beq @slen_done
        iny
        bne @slen
@slen_done:
        dey
        sty _eb_idx
        inc expr_ptr            ; skip opening quote
        bne :+
        inc expr_ptr+1
:
@no_str:
        ; ── Compute SYS address ────────────────────────────────────────
        ; Always 5 digits.  No string: 13 bytes.  With string: 16 + len
        ; (13 + ':' + REM_tok + ' ' + len).
        lda _eb_idx
        beq @no_rem
        clc
        adc #16
        bne @calc               ; always taken
@no_rem:
        lda #13
@calc:  clc
        adc asm_pc
        sta asm_tmp             ; SYS addr lo
        lda asm_pc+1
        adc #0
        sta asm_tmp2            ; SYS addr hi

        ; ── Emit single BASIC line ────────────────────────────────────
        ; Link → end marker = SYS_addr - 2
        lda asm_tmp
        sec
        sbc #2
        pha
        lda asm_tmp2
        sbc #0
        tax
        pla
        jsr _emit_word          ; link pointer

        lda #0
        tax
        jsr _emit_word          ; line number 0

        lda #BASIC_SYS
        jsr _emit_byte          ; SYS token

        ; 5-digit decimal SYS address (space-padded)
        lda asm_tmp
        ldx asm_tmp2
        sec                     ; padded — leading spaces OK for BASIC
        jsr io_utoa
        ldx #0
@sys:   lda dec_buf,x
        jsr _emit_byte
        inx
        cpx #5
        bne @sys

        ; Optional :REM string
        lda _eb_idx
        beq @no_tail
        lda #':'
        jsr _emit_byte
        lda #BASIC_REM
        jsr _emit_byte
        lda #' '                ; space after REM for readable LIST
        jsr _emit_byte
        ; Copy string bytes
        ldx #0
@str:   cpx _eb_idx
        beq @no_tail
        txa
        tay
        lda (expr_ptr),y
        jsr _emit_byte
        inx
        bne @str                ; always (len < 256)
@no_tail:

        lda #0
        jsr _emit_byte          ; NUL terminator
        lda #0
        tax
        jmp _emit_word          ; end of BASIC ($0000), tail call
.endproc


; ── process_directive ──────────────────────────────────────────────────────
; _as_ptr = first char of keyword (after '.').
; The word must be one of _dir_names exactly, ending at whitespace, ';'
; or NUL (assembler_syntax.md § Directives).  expr_ptr is set past it and
; the handler entered through _dir_lo/_dir_hi (RTS dispatch).
; Out: C=0 recognized (handled); C=1 unknown word.
.proc process_directive
        ldx #0                  ; offset into _dir_names
        stx asm_tmp             ; directive index
@name:  ldy #0
@cmp:   lda _dir_names,x
        beq @end                ; table name complete
        cmp (_as_ptr),y
        bne @next
        inx
        iny
        bne @cmp
@end:   lda (_as_ptr),y         ; the word must end here
        beq @hit
        cmp #' '
        beq @hit
        cmp #$a0
        beq @hit
        cmp #';'
        beq @hit
@next:  lda _dir_names,x        ; skip the rest of this name + NUL
        inx
        cmp #0
        bne @next
        inc asm_tmp
        lda _dir_names,x
        bpl @name               ; $FF ends the table
        sec                     ; unknown directive
        rts
@hit:   tya
        jsr set_expr_off        ; expr_ptr = past the name
        ldx asm_tmp
        lda _dir_hi,x
        pha
        lda _dir_lo,x
        pha
        rts

d_align:
        jsr skipws_ep
        jsr emit_align
        clc
        rts
d_bas:
        ; .bas is an implicit .org $0801
        jsr _seg_log_close      ; close previous segment
        lda #$01
        sta asm_pc
        lda #$08
        sta asm_pc+1
        jsr _org_set_pc
        jsr _seg_log_open           ; open .bas segment at $0801
        jsr emit_bas
        clc
        rts
d_cpu:
        jsr set_cpu
        clc
        rts
d_const:
        jsr skipws_ep           ; skip spaces; A = first char of name
        jsr is_ident
        bcc :+
        jmp @const_noname
:
        ; sym_name = expr_ptr (name start); asm_tmp/2 keep it across
        ; expr_eval, whose label lookups repoint sym_name
        lda expr_ptr
        sta sym_name
        sta asm_tmp
        lda expr_ptr+1
        sta sym_name+1
        sta asm_tmp2
        ; Scan name length into Y
        ldy #0
@cscan: lda (sym_name),y
        jsr is_ident
        bcs @cend
        iny
        bne @cscan
@cend:  cpy #0
        bne :+
        jmp @const_noname
:       lda (sym_name),y        ; name ends the line → no value
        bne :+                  ; (and nothing past the NUL to read)
        jsr _bad_val_err
        clc
        rts
:
        ; Fold name in-place, save length, NUL-terminate temporarily
        jsr fold_block          ; fold (sym_name)[0..Y-1]; Y preserved
        sty _as_wsize           ; save name length
        lda (sym_name),y        ; char after name
        pha                     ; save displaced char
        lda #0
        sta (sym_name),y        ; NUL-terminate
        jsr _name_ok            ; global-label grammar (no 5, no a.b)
        bcc @cname_ok
        ldy _as_wsize           ; restore the displaced char
        pla
        sta (sym_name),y
        jmp @const_noname
@cname_ok:
        ; Advance expr_ptr past name+NUL, skip remaining spaces to expression
        ; (+1 to step over the NUL we placed at the space position)
        lda _as_wsize
        clc
        adc #1
        adc expr_ptr
        sta expr_ptr
        lda expr_ptr+1
        adc #0
        sta expr_ptr+1
        jsr skipws_ep           ; expr_ptr now at expression
        jsr expr_eval          ; evaluate; rc in A
        sta _as_ptr             ; save rc (lo byte of _as_ptr used as scratch)
        lda asm_tmp             ; the name again (a symbol in the value
        sta sym_name            ; expression moved sym_name)
        lda asm_tmp2
        sta sym_name+1
        ; Check eval result
        lda _as_ptr
        cmp #2
        bcc @cok
        ; Restore displaced char before error return
        ldy _as_wsize
        pla
        sta (sym_name),y
        jsr _bad_val_err
        clc
        rts
@cok:   lda asm_pass
        beq @cdef               ; define on both passes (pass 1 re-stamps)
        lda expr_fwd            ; pass 1: read a later-defined symbol?
        bne @cfwd               ; → undefined on pass 0: fwd ref
@cdef:  lda expr_val
        sta sym_val
        lda expr_val+1
        sta sym_val+1
        lda expr_wide
        sta sym_wide
        jsr sym_define         ; name is still NUL-terminated here
        ; Restore displaced char
        ldy _as_wsize
        pla
        sta (sym_name),y
        bcc @cret
        lda #<s_sym_full
        ldx #>s_sym_full
        jsr emit_error
        clc
        rts
@cfwd:  ldy _as_wsize            ; restore displaced char
        pla
        sta (sym_name),y
        lda #<s_fwd_ref
        ldx #>s_fwd_ref
        jsr emit_error
@cret:  clc
        rts
@const_noname:
        jsr _exp_name_err
        clc
        rts
d_db:   lda #1
        .byte $2C               ; BIT abs: skip lda #2
d_dw:  lda #2
        sta _as_wsize
        jsr emit_data_bytes
        clc
        rts
d_org:
        jsr skipws_ep
        jsr expr_eval
        cmp #2
        bcc :+
        jsr _bad_val_err
        clc
        rts
:       ; Save new origin on stack — _seg_log_close clobbers asm_tmp
        lda expr_val+1
        pha
        lda expr_val
        pha
        ; Close previous segment (uses old asm_pc, clobbers asm_tmp)
        jsr _seg_log_close
        ; Set new origin from stack
        pla
        sta asm_pc
        pla
        sta asm_pc+1
        jsr _org_set_pc
        ; Open new segment (uses new asm_pc)
        jsr _seg_log_open
        clc
        rts
d_res:
        jsr skipws_ep
        jsr emit_reserve
        clc
        rts
d_str: lda #0                  ; no screen-code conversion
        .byte $2C               ; BIT abs: skip lda #1
d_scr: lda #1                  ; convert to screen codes
        jsr emit_string
        clc
        rts

; Name table and handlers, in the same order.
.segment "RODATA"
_dir_names:
        .byte "align", 0, "bas", 0, "cpu", 0, "const", 0, "db", 0
        .byte "dw", 0, "org", 0, "res", 0, "str", 0, "scr", 0, $FF
_dir_lo:
        .lobytes d_align-1, d_bas-1, d_cpu-1, d_const-1, d_db-1
        .lobytes d_dw-1, d_org-1, d_res-1, d_str-1, d_scr-1
_dir_hi:
        .hibytes d_align-1, d_bas-1, d_cpu-1, d_const-1, d_db-1
        .hibytes d_dw-1, d_org-1, d_res-1, d_str-1, d_scr-1
.segment "CODE"
.endproc

; ── _name_ok ───────────────────────────────────────────────────────────────
; C=0 iff (sym_name) is a valid label: a letter then letters/digits
; (global), or '.' then one or more letters/digits (local).  The name is
; already folded to $41-$5A.  Clobbers A, Y.
.proc _name_ok
        ldy #0
        lda (sym_name),y
        cmp #'.'
        bne @glob
        iny                     ; local: the part after the dot
        lda (sym_name),y
        bne @lp                 ; "." alone → bad
        beq @bad
@glob:  cmp #$41
        bcc @bad                ; must start with a letter
        cmp #$5B
        bcs @bad
@lp:    lda (sym_name),y
        beq @good
        cmp #$30
        bcc @bad
        cmp #$3A
        bcc @next               ; digit
        cmp #$41
        bcc @bad
        cmp #$5B
        bcs @bad                ; not a letter
@next:  iny
        bne @lp
@bad:   sec
        rts
@good:  clc
        rts
.endproc

; ── define_label ───────────────────────────────────────────────────────────
; sym_name = NUL-terminated label name (caller replaced ':' with NUL).
; Stores the label address in the symbol table (both passes; pass 1
; re-stamps).
.proc define_label
        jsr _name_ok            ; grammar (assembler_syntax.md § Labels)
        bcc :+
        jmp _exp_name_err       ; a_b:, 5x:, a.b:, .: → exp id
:       ldy #0
        lda (sym_name),y
        cmp #'.'
        bne @global
        ; Local label: build "scope.name" in _full_label
        ldx #0
        ldy #0
@sc:    lda _scope_name,y
        beq @sc_done
        sta _full_label,x
        inx
        iny
        bne @sc
@sc_done:
        lda #'.'
        sta _full_label,x
        inx
        ldy #1                  ; skip the '.' prefix in sym_name
@lc:    lda (sym_name),y
        beq @lc_done
        cpy #MAX_LABEL+1        ; Y = 1-based index into the local name
        beq @long               ; 24th char → too long, define nothing
        sta _full_label,x
        inx
        iny
        bne @lc
@lc_done:
        lda #0
        sta _full_label,x
        lda #<_full_label
        sta sym_name
        lda #>_full_label
        sta sym_name+1
        jmp @set_val
@global:
        ; Update scope (copy sym_name → _scope_name)
        ldy #0
@gs:    lda (sym_name),y
        sta _scope_name,y
        beq @set_val
        iny
        cpy #MAX_LABEL+1
        bne @gs
        lda #0                  ; 24th char copied → too long:
        sta _scope_name         ; drop the scope, define nothing
@long:  jmp _too_long_err
@set_val:
        lda asm_pc
        sta sym_val
        lda asm_pc+1
        sta sym_val+1
        lda #0
        ldx asm_pc+1
        beq :+
        lda #1
:       sta sym_wide
        jsr sym_define          ; both passes: pass 1 re-stamps
        bcc @done
        lda #<s_sym_full
        ldx #>s_sym_full
        jsr emit_error
@done:  rts
.endproc

; ── _exp_name_err ──────────────────────────────────────────────────────────
; Shared "exp id" error tail: `.const` without a name, and a ':' with no
; label name in front of it (process_line).  Tail-calls emit_error.
_exp_name_err:
        lda #<s_exp_name
        ldx #>s_exp_name
        jmp emit_error

; ── _too_long_err ──────────────────────────────────────────────────────────
; Shared "too long" error tail: a label over MAX_LABEL characters
; (define_label) or instruction text over INSN_MAX (process_line @put).
_too_long_err:
        lda #<s_too_long
        ldx #>s_too_long
        jmp emit_error

; ── process_line ───────────────────────────────────────────────────────────
; Parse and assemble one source line.
;   In: _as_ptr = NUL-terminated line text
.proc process_line

; ── 1. Label loop ──────────────────────────────────────────────────────────
@lbl:   jsr skipws_as
        bne :+
        jmp @done               ; NUL = blank line
:
        cmp #';'
        bne :+
        jmp @done               ; comment
:

        ; Scan word (stop at whitespace/NUL/';')
        ldy #0
@wscan: lda (_as_ptr),y
        beq @wend
        cmp #' '
        beq @wend
        cmp #$a0
        beq @wend
        cmp #';'
        beq @wend
        iny
        bne @wscan
@wend:  ; Y = word length (Z flag from cmp, NOT from Y — must test Y explicitly)
        cpy #0
        bne :+
        jmp @done               ; empty word (should not happen after skip)
:

        ; Check last char for ':'
        dey                     ; Y = last char index
        lda (_as_ptr),y
        iny                     ; Y = word length
        cmp #':'
        bne @dispatch

        ; It's a label.  Define without the ':'.
        dey                     ; Y = name length (index of ':')
        beq _exp_name_err       ; zero-length (lone ':') → exp id, line done
        lda _as_ptr
        sta sym_name
        lda _as_ptr+1
        sta sym_name+1
        jsr fold_block
        lda (_as_ptr),y
        pha
        lda #0
        sta (_as_ptr),y
        tya
        pha
        jsr define_label
        pla
        tay
        pla
        sta (_as_ptr),y
        iny
@adv_lbl:
        tya
        clc
        adc _as_ptr
        sta _as_ptr
        bcc :+
        inc _as_ptr+1
:       jmp @lbl

; ── 2. Dispatch ────────────────────────────────────────────────────────────
@dispatch:
        ldy #0
        lda (_as_ptr),y
        cmp #'.'
        bne @insn
        inc _as_ptr
        bne :+
        inc _as_ptr+1
:       jsr process_directive
        bcc :+
        jmp @bad_syn            ; unknown directive → bad insn
:
        rts

; ── 3. Instruction ─────────────────────────────────────────────────────────
@insn:
        ldx #0
@insn2: ldy #0
@mne2:  lda (_as_ptr),y
        beq @mne_done
        cmp #' '
        beq @mne_done
        cmp #$a0
        beq @mne_done
        cmp #';'
        beq @mne_done
        cpx #8
        beq @mne_done
        sta _insn_buf,x
        inx
        iny
        bne @mne2
@mne_done:
        stx _ib_idx
        tya
        clc
        adc _as_ptr
        sta _as_ptr
        bcc :+
        inc _as_ptr+1
:
        jsr skipws_as
        beq @asm_insn
        cmp #';'
        beq @asm_insn

        ; Operand: copy into _insn_buf after a space, expanding each
        ; local reference `.name` to `scope.name`.  @put bounds every
        ; byte (INSN_MAX) — a longer text is `too long`.
        lda #' '
        jsr @put
@exp:   ldy #0
        lda (_as_ptr),y
        beq @asm_insn
        cmp #';'
        beq @asm_insn
        cmp #'.'
        bne @ecp
        ldx _ib_idx             ; a dot inside a name (main.loop) is
        lda _insn_buf-1,x       ; qualified: no scope prefix
        jsr is_ident
        bcc @ecp
        iny
        lda (_as_ptr),y
        jsr is_ident
        bcs @ecp
        ldy #0
@sc2:   lda _scope_name,y
        beq @ecp
        jsr @put
        iny
        bne @sc2
@ecp:   ldy #0
        lda (_as_ptr),y
        jsr @put
        inc _as_ptr
        bne @exp
        inc _as_ptr+1
        jmp @exp

; @put — append A to _insn_buf; on overflow drop the return address and
; report `too long` (ends the line).  Preserves Y.  Clobbers X.
@put:   ldx _ib_idx
        cpx #INSN_MAX
        bcs @long
        sta _insn_buf,x
        inc _ib_idx
        rts
@long:  pla
        pla
        jmp _too_long_err

; ── 4. Assemble instruction ─────────────────────────────────────────────────
@asm_insn:
        ldx _ib_idx
        lda #0
        sta _insn_buf,x
        lda #<_insn_out         ; assemble into scratch; _emit_byte
        sta asm_out             ; places the bytes (both passes)
        lda #>_insn_out
        sta asm_out+1
        lda #<_insn_buf
        ldx #>_insn_buf
        jsr asm_line
        tax
        beq @bad
        ldx #0
@emit:  lda _insn_out,x
        jsr _emit_byte          ; preserves X
        inx
        cpx asm_len
        bne @emit
@done:  rts
@bad:   ; Dispatch error tag from asm_err_code (asm_err.s):
        ;   0 = ;?<line>: bad insn   (syntax)
        ;   1 = ;?<line>: <detail>   (expr_error_str text, no prefix)
        ;   2 = ;?<line>: cpu        (CPU gate rejected mnemonic)
        lda asm_err_code
        beq @bad_syn
        cmp #2
        beq @bad_cpu
        jsr expr_error_str      ; A/X = expr error string
        jmp emit_error
@bad_syn:
        lda #<s_bad_insn
        ldx #>s_bad_insn
        jmp emit_error
@bad_cpu:
        lda #<str_cpu_err
        ldx #>str_cpu_err
        jmp emit_error
.endproc

; ── do_pass ────────────────────────────────────────────────────────────────
; Run one assembly pass over the editor source.
.proc do_pass
        jsr ed_read_rewind
        lda #0
        sta _line_num
        sta _line_num+1
        sta _pc_wrap
        lda _cpu_save           ; lines above a .cpu use the start CPU
        sta asm_cpu
        lda _def_org
        sta asm_pc
        lda _def_org+1
        sta asm_pc+1
        jsr _seg_log_open       ; open the default segment
@loop:  ; Call ed_read_line(_line_buf)
        lda #<_line_buf
        ldx #>_line_buf
        jsr ed_read_line       ; A = length, X = 0 / dropped / $FF EOF
        txa
        bmi @done               ; EOF
        inc _line_num
        bne :+
        inc _line_num+1
        ; Characters past the 39th were dropped (X != 0)?  A line of
        ; exactly 39 fits whole and is not truncated.
:       txa
        beq @no_trunc
        lda asm_pass
        beq @no_trunc
        jsr _bank_in_tmp
        ldy #'!'                ; LOG_WARN
        jsr log_open
        lda _line_num
        ldx _line_num+1
        jsr io_putdec
        puts s_trunc
        jsr log_close
        jsr _bank_out_tmp
@no_trunc:
        lda #<_line_buf
        sta _as_ptr
        lda #>_line_buf
        sta _as_ptr+1
        jsr process_line
        lda _oor                ; a byte of this line was dropped?
        beq @loop
        lda #0
        sta _oor
        lda #<str_range
        ldx #>str_range
        jsr emit_error
        jmp @loop
@done:  rts
.endproc

; ── asm_assemble ──────────────────────────────────────────────────────────
; Run two-pass assembly of editor source.
;   In:  A/X = default origin (used if source has no .org)
;   Out: A/X = error count (uint16_t)
.proc asm_assemble
        sta asm_org
        stx asm_org+1
        sta _def_org
        stx _def_org+1
        lda asm_cpu
        sta _cpu_save           ; .cpu scope: restored per pass and after
        lda #0
        sta asm_errors
        sta asm_errors+1
        sta asm_size
        sta asm_size+1
        sta _scope_name
        jsr _seg_init           ; reset segment logging state
        ; Clear symbol table (heap at fixed $E600 under KERNAL)
        lda #SYM_P0
        sta sym_stamp           ; pass-0 stamp for every define below
        jsr sym_clear
        jsr define_ws_syms     ; pre-define workstart/workend

        ; Bank out KERNAL for both passes — KDATA tables and sym_table
        ; are both in RAM under KERNAL.  Order matters: do the actual
        ; bank_out FIRST, THEN set kernal_out=1.  Setting the flag
        ; first would make the bank_out call short-circuit (it now
        ; honours the flag like bank_in does), leaving KERNAL mapped
        ; in and the assembly passes reading garbage from ROM.
        ; With the flag set after, the inner sym_define / sym_lookup /
        ; asm_line bank helpers all become no-ops for the duration.
        jsr kernal_bank_out
        lda #1
        sta kernal_out

        ; Pass 0: collect labels/constants
        lda #0
        sta asm_pass
        jsr do_pass                 ; starts at _def_org, default segment open
        jsr _seg_log_close          ; close final segment from pass 0

        ; Pass 1: emit code — reset seg table so pass 1 re-records
        lda #1
        sta asm_pass
        lda #0
        sta asm_size
        sta asm_size+1
        sta _scope_name
        sta _seg_open
        sta sym_stamp           ; pass-1 stamp (also the stamp after)
        jsr define_ws_syms      ; re-stamp the built-ins
        jsr do_pass                 ; starts at _def_org, default segment open
        jsr _seg_log_close          ; close final segment from pass 1

        ; Bank in KERNAL — clear flag FIRST so the bank_in actually fires.
        lda #0
        sta kernal_out
        jsr kernal_bank_in

        lda _cpu_save           ; .cpu never leaks out of the assembly
        sta asm_cpu
        lda asm_errors
        ldx asm_errors+1
        rts
.endproc
