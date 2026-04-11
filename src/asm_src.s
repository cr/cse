; asm_src.s — Two-pass source assembler
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

        .export         asm_assemble
        .export         asm_org, asm_size, asm_errors
        .export         asm_pass := _asm_pass   ; pass flag for au_mode.s fwd refs

        .import         asm_line               ; asm_line.s
        .import         expr_eval              ; expr.s
        .import         sym_define             ; symtab.s
        .import         sym_clear
        .import         kernal_bank_out, kernal_bank_in, kernal_out
        .import         io_puts, io_putdec, newline
        .import         out_log_open, out_close
        .import         define_ws_syms         ; mem.s
        .import         ed_read_line           ; editor.s
        .import         ed_read_rewind
        .importzp       buf_base                ; editor.s — gap buffer low bound
        .importzp       asm_pc, asm_out, asm_cpu
        .importzp       expr_ptr, expr_val, expr_wide
        .importzp       sym_name, sym_val, sym_wide

        .importzp _as_ptr, _as_wsize

; ── BSS (all reset by asm_assemble before each run) ─────────────────────
.segment "BSS"
asm_org:       .res 2          ; assembly origin address
asm_size:      .res 2          ; total bytes emitted
asm_errors:    .res 2          ; error count (pass 1 only)
_asm_pass:      .res 1          ; 0 = pass 0, 1 = pass 1
_line_num:      .res 2
_line_buf:      .res 80
_scope_name:    .res 24         ; last global label (for .local expansion)
_full_label:    .res 48         ; scratch: "scope.local"
_insn_buf:      .res 32         ; rebuilt instruction text for asm_line
_expr_buf:      .res 48         ; operand with local labels expanded
_as_conv:       .res 1          ; emit_string convert-to-screen-code flag
_eb_idx:        .res 1          ; write index into _expr_buf
_ib_idx:        .res 1          ; write index into _insn_buf

; ── RODATA ────────────────────────────────────────────────────────────────
.segment "RODATA"
s_err_sep:      .byte ": ", 0
s_bad_val:      .byte "bad val", 0
s_exp_name:     .byte "exp name", 0
s_sym_full:     .byte "sym full", 0
s_exp_quot:     .byte "exp quote", 0
s_bad_insn:     .byte "bad insn", 0

; ═══════════════════════════════════════════════════════════════════════════
.segment "CODE"
; ═══════════════════════════════════════════════════════════════════════════

; ── emit_error ─────────────────────────────────────────────────────────────
; Print error on pass 1 and increment error count.
;   In: A/X = PETSCII message pointer
LOG_ERR = '?'

.proc emit_error
        pha                     ; save msg lo BEFORE pass check
        lda _asm_pass
        beq @skip
        txa
        pha                     ; save msg hi
        inc asm_errors
        bne :+
        inc asm_errors+1
        ; Bank KERNAL in for screen output (newline → io_sync
        ; needs KERNAL PLOT at $FFF0).  Direct $01 manipulation
        ; because kernal_out flag makes bank_in a no-op.
:       lda $01
        ora #$02
        sta $01
        cli
        ldy #LOG_ERR
        jsr out_log_open        ; ";?"
        lda _line_num
        ldx _line_num+1
        jsr io_putdec
        lda #<s_err_sep
        ldx #>s_err_sep
        jsr io_puts             ; ": "
        pla
        tax                     ; msg hi
        pla                     ; msg lo
        jsr io_puts             ; error message
        jsr out_close           ; clear_eol
        ; Bank KERNAL back out for the rest of the pass
        sei
        lda $01
        and #$FD
        sta $01
        rts
@skip:  pla                     ; discard saved msg lo
        rts
.endproc

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

; ── adv_pc_size ────────────────────────────────────────────────────────────
; asm_pc += _as_wsize;  asm_size += _as_wsize
; inc_pc_size: increment asm_pc and asm_size by 1
inc_pc_size:
        inc asm_pc
        bne :+
        inc asm_pc+1
:       inc asm_size
        bne :+
        inc asm_size+1
:       rts

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
; Fold (sym_name)[0..Y-1] to lowercase in-place.  Y preserved.  Clobbers A.
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
        beq @done
        cmp #';'
        beq @done
        cmp #'"'
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
        lda _asm_pass
        beq @qa
        lda (expr_ptr),y
        sta (asm_pc),y
@qa:    jsr inc_pc_size
        inc expr_ptr
        bne @ql
        inc expr_ptr+1
        jmp @ql
@qc:    inc expr_ptr            ; skip closing '"'
        bne @comma
        inc expr_ptr+1
        bne @comma
@expr:  jsr expr_eval
        cmp #2
        bcc @emit
        lda #<s_bad_val
        ldx #>s_bad_val
        jmp emit_error          ; tail-call; emit_error returns to our caller
@emit:  lda _asm_pass
        beq @adv
        lda expr_val
        ldy #0
        sta (asm_pc),y
        lda _as_wsize
        cmp #2
        bne @adv
        lda expr_val+1
        ldy #1
        sta (asm_pc),y
@adv:   jsr adv_pc_size
@comma: jsr skipws_ep
        cmp #','
        bne @done
        inc expr_ptr
        bne @loop
        inc expr_ptr+1
        jmp @loop
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
@ec:    pha
        lda _asm_pass
        beq @sk
        ldy #0
        pla
        sta (asm_pc),y
        pha
@sk:    pla
        jsr inc_pc_size
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

; ── emit_reserve ───────────────────────────────────────────────────────────
; .res count [,fill]  In: expr_ptr = operand start
.proc emit_reserve
        jsr expr_eval
        cmp #2
        bcc :+
        lda #<s_bad_val
        ldx #>s_bad_val
        jmp emit_error
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
        lda #<s_bad_val
        ldx #>s_bad_val
        jmp emit_error
:       lda expr_val
        sta _as_wsize           ; fill byte
@go:    lda _as_ptr
        ora _as_ptr+1
        beq @done
@lp:    lda _asm_pass
        beq @av
        lda _as_wsize
        ldy #0
        sta (asm_pc),y
@av:    jsr inc_pc_size
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
.proc emit_align
        jsr expr_eval
        cmp #2
        bcc :+
        lda #<s_bad_val
        ldx #>s_bad_val
        jmp emit_error
:       lda expr_val
        ora expr_val+1
        bne :+
        lda #<s_bad_val
        ldx #>s_bad_val
        jmp emit_error
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
        lda _asm_pass
        beq @av
        lda #0
        ldy #0
        sta (asm_pc),y
@av:    jsr inc_pc_size
        lda _as_ptr
        bne :+
        dec _as_ptr+1
:       dec _as_ptr
        jmp @lp
@done:  rts
.endproc

; ── set_cpu ────────────────────────────────────────────────────────────────
; .cpu 6502 / 6510 / 65c02   In: expr_ptr = text after "cpu"
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
@bad:   lda #<s_bad_val
        ldx #>s_bad_val
        jmp emit_error
.endproc

; ── process_directive ──────────────────────────────────────────────────────
; _as_ptr = first char of keyword (after '.').
; Out: C=0 recognized; C=1 unknown (caller treats as local label).
.proc process_directive
        ldy #0
        lda (_as_ptr),y
        cmp #'a'
        bne @nb
        ; .align — check [4]='n' as rough disambiguator
        ldy #4
        lda (_as_ptr),y
        cmp #'n'
        beq :+
        jmp @unk
:       lda #5
        jsr set_expr_off
        jsr skipws_ep
        jsr emit_align
        clc
        rts
@nb:    cmp #'c'
        beq :+
        jmp @nd
:
        ldy #1
        lda (_as_ptr),y
        cmp #'p'
        bne @const
        ; .cpu
        lda #3
        jsr set_expr_off
        jsr set_cpu
        clc
        rts
@const:
        cmp #'o'
        beq :+
        jmp @unk
:
        ; .const name expr
        lda #5
        jsr set_expr_off        ; expr_ptr = _as_ptr + 5 (past "const")
        jsr skipws_ep           ; skip spaces; A = first char of name
        jsr is_ident
        bcs @const_noname
        ; sym_name = expr_ptr (name start)
        lda expr_ptr
        sta sym_name
        lda expr_ptr+1
        sta sym_name+1
        ; Scan name length into Y
        ldy #0
@cscan: lda (sym_name),y
        jsr is_ident
        bcs @cend
        iny
        bne @cscan
@cend:  cpy #0
        beq @const_noname
        ; Fold name in-place, save length, NUL-terminate temporarily
        jsr fold_block          ; fold (sym_name)[0..Y-1]; Y preserved
        sty _as_wsize           ; save name length
        lda (sym_name),y        ; char after name
        pha                     ; save displaced char
        lda #0
        sta (sym_name),y        ; NUL-terminate
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
        ; Check eval result
        lda _as_ptr
        cmp #2
        bcc @cok
        ; Restore displaced char before error return
        ldy _as_wsize
        pla
        sta (sym_name),y
        lda #<s_bad_val
        ldx #>s_bad_val
        jsr emit_error
        clc
        rts
@cok:   lda _asm_pass
        bne @cret_restore       ; only define in pass 0
        lda expr_val
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
@cret_restore:
        ; Restore displaced char (pass 1 skip path)
        ldy _as_wsize
        pla
        sta (sym_name),y
@cret:  clc
        rts
@const_noname:
        lda #<s_exp_name
        ldx #>s_exp_name
        jsr emit_error
        clc
        rts
@nd:    cmp #'d'
        bne @no
        ldy #1
        lda (_as_ptr),y
        cmp #'b'
        bne @dw
        ; .db
        lda #1
        sta _as_wsize
        lda #2
        jsr set_expr_off
        jsr emit_data_bytes
        clc
        rts
@dw:    cmp #'w'
        bne @unk
        ; .dw
        lda #2
        sta _as_wsize
        lda #2
        jsr set_expr_off
        jsr emit_data_bytes
        clc
        rts
@no:    cmp #'o'
        bne @nr
        ; .org
        lda #3
        jsr set_expr_off
        jsr skipws_ep
        jsr expr_eval
        cmp #2
        bcc :+
        lda #<s_bad_val
        ldx #>s_bad_val
        jsr emit_error
        clc
        rts
:       lda expr_val
        sta asm_pc
        lda expr_val+1
        sta asm_pc+1
        lda _asm_pass
        bne @org_done
        lda expr_val
        sta asm_org
        lda expr_val+1
        sta asm_org+1
@org_done:
        clc
        rts
@nr:    cmp #'r'
        bne @ns
        ; .res
        lda #3
        jsr set_expr_off
        jsr skipws_ep
        jsr emit_reserve
        clc
        rts
@ns:    cmp #'s'
        bne @unk
        ldy #1
        lda (_as_ptr),y
        cmp #'t'
        bne @scr
        ; .str
        lda #3
        jsr set_expr_off
        lda #0                  ; no screen-code conversion
        jsr emit_string
        clc
        rts
@scr:   cmp #'c'
        bne @unk
        ; .scr
        lda #3
        jsr set_expr_off
        lda #1                  ; convert to screen codes
        jsr emit_string
        clc
        rts
@unk:   sec                     ; unrecognized: might be local label
        rts
.endproc

; ── define_label ───────────────────────────────────────────────────────────
; sym_name = NUL-terminated label name (caller replaced ':' with NUL).
; Stores label address in symbol table (pass 0 only).
.proc define_label
        ldy #0
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
        bne @gs
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
        lda _asm_pass
        bne @done
        jsr sym_define
        bcc @done
        lda #<s_sym_full
        ldx #>s_sym_full
        jsr emit_error
@done:  rts
.endproc

; ── process_line ───────────────────────────────────────────────────────────
; Parse and assemble one source line.
;   In: _as_ptr = NUL-terminated line text
.proc process_line

; ── 1. Label loop ──────────────────────────────────────────────────────────
@lbl:   ; Skip whitespace ($20/$A0)
        ldy #0
@sp:    lda (_as_ptr),y
        cmp #' '
        beq @sp_eat
        cmp #$a0
        bne @nsp
@sp_eat:
        inc _as_ptr
        bne @sp
        inc _as_ptr+1
        jmp @sp
@nsp:   bne :+
        rts                     ; NUL = blank line
:       cmp #';'
        bne :+
        rts                     ; comment
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
@wend:  ; Y = word length
        cpy #0
        bne :+
        rts                     ; empty word (should not happen after skip)
:

        ; Check last char for ':'
        dey                     ; Y = last char index
        lda (_as_ptr),y
        iny                     ; Y = word length
        cmp #':'
        bne @dispatch

        ; It's a label.  Define without the ':'.
        dey                     ; Y = name length (index of ':')
        cpy #0
        beq @adv_lbl            ; zero-length: skip
        ; sym_name = _as_ptr (name pointer)
        lda _as_ptr
        sta sym_name
        lda _as_ptr+1
        sta sym_name+1
        ; Fold name in-place
        jsr fold_block          ; fold [0..Y-1]; Y preserved
        ; NUL-terminate (replace ':' at offset Y)
        lda (_as_ptr),y         ; char at Y (the ':')
        pha                     ; save it
        lda #0
        sta (_as_ptr),y
        tya
        pha                     ; save Y (index of ':')
        jsr define_label
        pla                     ; restore Y (index of ':')
        tay
        ; Restore ':'
        pla
        sta (_as_ptr),y
        iny                     ; Y = word length (including ':')
@adv_lbl:
        ; Advance _as_ptr past label+colon (Y = word length including ':')
        tya
        clc
        adc _as_ptr
        sta _as_ptr
        bcc :+
        inc _as_ptr+1
:       jmp @lbl

; ── 2. Dispatch ────────────────────────────────────────────────────────────
@dispatch:
        ; _as_ptr = start of first non-label word
        ldy #0
        lda (_as_ptr),y

        cmp #'.'
        bne @notdot
        ; Directive: _as_ptr+1 is keyword start
        inc _as_ptr
        bne :+
        inc _as_ptr+1
:       jsr process_directive
        bcs @handle_local
        rts                     ; recognized directive: done
@handle_local:
        ; Not a known directive — assume local label by itself on a line
        ; (e.g. ".loop:" — but wait: we already consumed labels above.
        ;  If we get here, '.' keyword was unrecognized — emit error.)
        lda #<s_bad_insn
        ldx #>s_bad_insn
        jmp emit_error          ; tail call

@notdot:
; ── 3. Instruction ─────────────────────────────────────────────────────────
@insn:
        ; Copy mnemonic to _insn_buf (max 8 chars, stop at space/NUL)
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
        stx _ib_idx             ; save mnemonic end index
        ; Advance _as_ptr by mnemonic length (Y)
        tya
        clc
        adc _as_ptr
        sta _as_ptr
        bcc :+
        inc _as_ptr+1
:
        ; Skip whitespace between mnemonic and operand
        ldy #0
@msp:   lda (_as_ptr),y
        cmp #' '
        beq @msp_eat
        cmp #$a0
        bne @msp_done
@msp_eat:
        inc _as_ptr
        bne @msp
        inc _as_ptr+1
        jmp @msp
@msp_done:
        cmp #0                  ; re-test A: flags clobbered by cmp #$a0 above
        beq @msp_nooper         ; NUL = no operand
        cmp #';'
        beq @msp_nooper         ; ';' = comment, no operand
        jmp @msp_hasoper
@msp_nooper:
        jmp @asm_insn

        ; ── Expand operand with local label resolution, pass to asm_line ──
@msp_hasoper:
        ; Expand operand into _expr_buf (resolves .local → scope.local)
        lda #0
        sta _eb_idx
@exp:   ldy #0
        lda (_as_ptr),y
        beq @exp_done
        cmp #';'
        beq @exp_done
        ; Local label expansion: '.' followed by ident char
        cmp #'.'
        bne @ecp
        ldy #1
        lda (_as_ptr),y
        jsr is_ident
        bcs @ecp                ; not ident: just copy the '.'
        ; Prepend scope name
        ldx _eb_idx
        ldy #0
@sc2:   lda _scope_name,y
        beq @sc2_done
        sta _expr_buf,x
        inx
        iny
        bne @sc2
@sc2_done:
        stx _eb_idx
@ecp:   ldy #0
        lda (_as_ptr),y
        ldx _eb_idx
        sta _expr_buf,x
        inc _eb_idx
        inc _as_ptr
        bne @exp
        inc _as_ptr+1
        jmp @exp
@exp_done:
        ldx _eb_idx
        lda #0
        sta _expr_buf,x         ; NUL-terminate

        ; Append space + expanded operand to _insn_buf
        ldx _ib_idx
        lda #' '
        sta _insn_buf,x
        inx
        ldy #0
@cpy:   lda _expr_buf,y
        beq @cpy_done
        sta _insn_buf,x
        inx
        iny
        bne @cpy
@cpy_done:
        stx _ib_idx

; ── 4. Assemble instruction ─────────────────────────────────────────────────
@asm_insn:
        ldx _ib_idx
        lda #0
        sta _insn_buf,x         ; NUL-terminate
        ; Call asm_line(_insn_buf) — asm_pc already set; set asm_out = asm_pc
        lda asm_pc
        sta asm_out
        lda asm_pc+1
        sta asm_out+1
        lda #<_insn_buf
        ldx #>_insn_buf
        jsr asm_line           ; A = byte count (0 = error)
        tax                     ; save count in X
        bne @insn_ok
        lda #<s_bad_insn
        ldx #>s_bad_insn
        jmp emit_error          ; tail call
@insn_ok:
        ; Advance asm_pc and asm_size by A (byte count); A still valid from asm_line
        clc
        adc asm_pc
        sta asm_pc
        bcc :+
        inc asm_pc+1
:       txa
        clc
        adc asm_size
        sta asm_size
        bcc :+
        inc asm_size+1
:
@done:  rts

.endproc

; ── do_pass ────────────────────────────────────────────────────────────────
; Run one assembly pass over the editor source.
.proc do_pass
        jsr ed_read_rewind
        lda #0
        sta _line_num
        sta _line_num+1
        lda asm_org
        sta asm_pc
        lda asm_org+1
        sta asm_pc+1
@loop:  ; Call ed_read_line(_line_buf)
        lda #<_line_buf
        ldx #>_line_buf
        jsr ed_read_line       ; A=lo, X=hi of signed int return
        ; Negative return = EOF
        txa
        bmi @done
        inc _line_num
        bne :+
        inc _line_num+1
:       lda #<_line_buf
        sta _as_ptr
        lda #>_line_buf
        sta _as_ptr+1
        jsr process_line
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
        lda #0
        sta asm_errors
        sta asm_errors+1
        sta asm_size
        sta asm_size+1
        sta _scope_name
        ; Clear symbol table (heap at fixed $E600 under KERNAL)
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
        sta _asm_pass
        jsr do_pass
        ; Pass 1: emit code
        lda #1
        sta _asm_pass
        lda #0
        sta asm_size
        sta asm_size+1
        sta _scope_name
        jsr do_pass

        ; Bank in KERNAL — clear flag FIRST so the bank_in actually fires.
        lda #0
        sta kernal_out
        jsr kernal_bank_in

        lda asm_errors
        ldx asm_errors+1
        rts
.endproc
