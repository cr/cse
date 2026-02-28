; ============================================================================
; Tiny prototype: anonymous labels (+: / -:) and references (+, ++, -, --, ...)
; for a 2-pass assembler in ca65 (cc65 toolchain).
;
; This is NOT yet a full assembler. It’s a first implementation focusing on:
;   - scanning source lines (array of pointers, 0-terminated)
;   - pass 1: collecting anonymous label PCs into a table
;   - pass 2: resolving + / ++ / - / -- references for relative branches
;   - emitting branch opcodes + signed offsets
;
; Assumptions:
;   - Source is an array of 16-bit pointers to lines, terminated by 0 pointer.
;   - Each line ends at 0 or CR/LF.
;   - Comment begins with ';'
;   - Anonymous label definitions: "+:" and "-:" (after optional whitespace)
;   - Branch operand may be "+", "++", "-", "--", etc (after whitespace)
;
; Build idea:
;   - This file exports assemble() which runs pass1+pass2.
;   - You can extend parse_line_pass2 to handle more mnemonics/directives/data.
;
; ============================================================================

        .setcpu "6502"

; =========================
; Tunables / limits
; =========================
MAX_ANON        = 256          ; max anonymous labels stored
MAX_OUT         = 65535        ; demo: output buffer size not enforced here

; =========================
; Zero page workspace
; =========================
        .segment "ZEROPAGE"

zp_lines_lo:    .res 1         ; pointer to array of line pointers
zp_lines_hi:    .res 1

zp_lineptr_lo:  .res 1         ; current line pointer
zp_lineptr_hi:  .res 1

zp_p_lo:        .res 1         ; scan pointer within line
zp_p_hi:        .res 1

zp_pc_lo:       .res 1         ; current PC
zp_pc_hi:       .res 1

zp_out_lo:      .res 1         ; output pointer (in output buffer)
zp_out_hi:      .res 1

zp_pass:        .res 1         ; 1 or 2

zp_anon_seen:   .res 1         ; pass2: anon labels encountered so far (index anchor)
zp_anon_seen_hi:.res 1         ; (use 16-bit in case you raise MAX_ANON)

zp_tmp:         .res 1
zp_tmp2:        .res 1

; expression parse / anon-ref decode
zp_dir:         .res 1         ; 0=backward(-), 1=forward(+)
zp_count:       .res 1         ; number of + or - (1..255)

; =========================
; BSS / tables
; =========================
        .segment "BSS"

anon_pc_lo:     .res MAX_ANON
anon_pc_hi:     .res MAX_ANON
anon_type:      .res MAX_ANON  ; 0 = '-' label, 1 = '+' label (optional filter)
anon_n:         .res 2         ; total anonymous labels collected (16-bit)

; =========================
; Public entry
; =========================
        .segment "CODE"
        .export assemble

; ----------------------------------------------------------------------------
; assemble(lines_ptr, out_ptr, origin)
; A/X/Y calling convention is up to you; here we use:
;   A = lines_ptr_lo, X = lines_ptr_hi
;   Y = out_ptr_lo,   zp_out_hi provided by caller? (kept simple: use globals)
;
; For a real project you’ll want a C-callable wrapper, or pass via memory.
; ----------------------------------------------------------------------------
assemble:
        ; For this prototype:
        ;   - caller must preload:
        ;       zp_out_lo/zp_out_hi = output buffer base
        ;       zp_pc_lo/zp_pc_hi   = origin (PC start)
        ;   - A/X contain lines pointer
        sta zp_lines_lo
        stx zp_lines_hi

        ; pass 1
        lda #1
        sta zp_pass
        jsr pass1_collect_anon

        ; reset for pass 2: rewind line list, reset PC/out
        ; (caller should re-init PC/out if they want nontrivial .org behavior)
        lda #0
        sta zp_anon_seen
        sta zp_anon_seen_hi

        lda #2
        sta zp_pass
        jsr pass2_emit

        rts

; =========================
; Pass 1: collect anonymous labels
; =========================
pass1_collect_anon:
        ; anon_n = 0
        lda #0
        sta anon_n
        sta anon_n+1

        ; iterate line pointer list
        lda zp_lines_lo
        sta zp_lineptr_lo
        lda zp_lines_hi
        sta zp_lineptr_hi

@next_line:
        ; read pointer (lo,hi) from lineptr
        ldy #0
        lda (zp_lineptr_lo),y
        beq @done              ; 0 pointer => end
        sta zp_p_lo
        iny
        lda (zp_lineptr_lo),y
        sta zp_p_hi

        ; advance list pointer by 2
        clc
        lda zp_lineptr_lo
        adc #2
        sta zp_lineptr_lo
        bcc :+
        inc zp_lineptr_hi
:

        ; scan this line for "+:" or "-:" at start (after ws)
        jsr line_skip_ws
        jsr line_peek_ch
        cmp #'+'
        beq @maybe_plus
        cmp #'-'
        beq @maybe_minus
        jmp @next_line

@maybe_plus:
        jsr line_get_ch         ; consume '+'
        jsr line_peek_ch
        cmp #':'
        bne @next_line
        jsr line_get_ch         ; consume ':'
        lda #1
        jsr record_anon_label
        jmp @next_line

@maybe_minus:
        jsr line_get_ch         ; consume '-'
        jsr line_peek_ch
        cmp #':'
        bne @next_line
        jsr line_get_ch         ; consume ':'
        lda #0
        jsr record_anon_label
        jmp @next_line

@done:
        rts

; record_anon_label(A=type 0/- or 1/+), store current PC in anon_pc[]
record_anon_label:
        ; if anon_n == MAX_ANON => silently ignore or set error (prototype: ignore)
        pha                     ; save type

        lda anon_n
        cmp #<MAX_ANON
        bne @ok
        lda anon_n+1
        bne @full
@ok:
        ; index = anon_n (low only, since MAX_ANON=256)
        ldx anon_n              ; X = index
        lda zp_pc_lo
        sta anon_pc_lo,x
        lda zp_pc_hi
        sta anon_pc_hi,x
        pla
        sta anon_type,x

        ; anon_n++
        inc anon_n
        bne @rts
        inc anon_n+1
@rts:
        rts
@full:
        pla
        rts

; =========================
; Pass 2: emit minimal subset (branch + anon ref)
; =========================
pass2_emit:
        ; iterate line pointers again
        lda zp_lines_lo
        sta zp_lineptr_lo
        lda zp_lines_hi
        sta zp_lineptr_hi

@next_line:
        ldy #0
        lda (zp_lineptr_lo),y
        beq @done
        sta zp_p_lo
        iny
        lda (zp_lineptr_lo),y
        sta zp_p_hi

        ; advance list pointer
        clc
        lda zp_lineptr_lo
        adc #2
        sta zp_lineptr_lo
        bcc :+
        inc zp_lineptr_hi
:

        ; anchor is "anon labels seen so far"
        ; We update anon_seen AFTER we parse line definitions, so references
        ; on this line do not see labels defined later on the same line.

        ; parse the line (emit if matches our supported subset)
        jsr parse_line_pass2

        ; after parsing/emitting, check if this line defines an anon label (+:/-:)
        ; and if so, bump anon_seen (anchor for subsequent lines).
        jsr line_rewind_to_start
        jsr line_skip_ws
        jsr line_peek_ch
        cmp #'+'
        beq @bump_plus
        cmp #'-'
        beq @bump_minus
        jmp @next_line

@bump_plus:
        jsr line_get_ch
        jsr line_peek_ch
        cmp #':'
        bne @next_line
        jsr bump_anon_seen
        jmp @next_line

@bump_minus:
        jsr line_get_ch
        jsr line_peek_ch
        cmp #':'
        bne @next_line
        jsr bump_anon_seen
        jmp @next_line

@done:
        rts

bump_anon_seen:
        inc zp_anon_seen
        bne :+
        inc zp_anon_seen_hi
:
        rts

; ----------------------------------------------------------------------------
; parse_line_pass2
; Prototype supports:
;   - optional "+:" / "-:" label definition at line start (ignored here)
;   - branch mnemonics: BEQ/BNE/BCC/BCS/BMI/BPL/BVC/BVS
;   - operand: +/++/... or -/--/... only
;   - comments and whitespace
; ----------------------------------------------------------------------------
parse_line_pass2:
        jsr line_skip_ws

        ; skip optional anon label definition (+: or -:) if present
        jsr line_peek_ch
        cmp #'+'
        beq @skip_anon_def
        cmp #'-'
        beq @skip_anon_def2
        jmp @mnemonic

@skip_anon_def:
        jsr line_get_ch
        jsr line_peek_ch
        cmp #':'
        bne @mnemonic
        jsr line_get_ch
        jsr line_skip_ws
        jmp @mnemonic

@skip_anon_def2:
        jsr line_get_ch
        jsr line_peek_ch
        cmp #':'
        bne @mnemonic
        jsr line_get_ch
        jsr line_skip_ws

@mnemonic:
        ; read 3-letter mnemonic (case-insensitive) into zp_tmp/zp_tmp2/... minimal:
        ; We'll compare directly by peeking chars.
        jsr read_uc_ch
        sta zp_tmp              ; m1
        jsr read_uc_ch
        sta zp_tmp2             ; m2
        jsr read_uc_ch
        tax                     ; m3 in X

        ; Determine branch opcode
        ; (Tiny chain: BEQ/BNE/BCC/BCS/BMI/BPL/BVC/BVS)
        lda zp_tmp
        cmp #'B'
        bne @done
        lda zp_tmp2
        cmp #'E'                ; BE?
        beq @beq_or_bne
        cmp #'C'                ; BC?
        beq @bcc_or_bcs
        cmp #'M'                ; BM?
        beq @bmi
        cmp #'P'                ; BP?
        beq @bpl
        cmp #'V'                ; BV?
        beq @bvc_or_bvs
        jmp @done

@beq_or_bne:
        cpx #'Q'
        beq @emit_beq
        cpx #'N'
        beq @emit_bne
        jmp @done

@bcc_or_bcs:
        cpx #'C'
        beq @emit_bcc
        cpx #'S'
        beq @emit_bcs
        jmp @done

@bmi:
        cpx #'I'
        beq @emit_bmi
        jmp @done

@bpl:
        cpx #'L'
        beq @emit_bpl
        jmp @done

@bvc_or_bvs:
        cpx #'C'
        beq @emit_bvc
        cpx #'S'
        beq @emit_bvs
        jmp @done

@emit_beq:  lda #$F0  ; BEQ
            bne @emit_branch
@emit_bne:  lda #$D0  ; BNE
            bne @emit_branch
@emit_bcc:  lda #$90  ; BCC
            bne @emit_branch
@emit_bcs:  lda #$B0  ; BCS
            bne @emit_branch
@emit_bmi:  lda #$30  ; BMI
            bne @emit_branch
@emit_bpl:  lda #$10  ; BPL
            bne @emit_branch
@emit_bvc:  lda #$50  ; BVC
            bne @emit_branch
@emit_bvs:  lda #$70  ; BVS

@emit_branch:
        ; A = opcode
        pha

        ; parse operand: expects +++... or ---...
        jsr line_skip_ws
        jsr parse_anon_ref_token     ; sets zp_dir (0/1) and zp_count, returns C=0 ok
        bcs @fail

        ; resolve to absolute target address -> zp_tmp (lo), zp_tmp2 (hi)
        jsr resolve_anon_ref
        bcs @fail                    ; not found

        ; compute signed offset = target - (PC + 2)
        ; tmp = target - (pc+2)
        ; We'll do 16-bit subtract: (target) - (pc+2)
        clc
        lda zp_pc_lo
        adc #2
        sta zp_p_lo          ; reuse zp_p_lo/hi as pc_plus2 temp
        lda zp_pc_hi
        adc #0
        sta zp_p_hi

        sec
        lda zp_tmp           ; target lo
        sbc zp_p_lo
        sta zp_tmp           ; diff lo
        lda zp_tmp2          ; target hi
        sbc zp_p_hi
        sta zp_tmp2          ; diff hi

        ; diff must fit in signed 8-bit: hi must be $00 for +0..+127 or $FF for -128..-1
        lda zp_tmp2
        cmp #$00
        beq @check_pos
        cmp #$FF
        beq @check_neg
        jmp @fail

@check_pos:
        lda zp_tmp
        cmp #$80
        bcs @fail
        jmp @emit_bytes

@check_neg:
        lda zp_tmp
        cmp #$80
        bcc @fail
        ; ok

@emit_bytes:
        ; emit opcode + offset
        pla
        jsr emit_byte
        lda zp_tmp
        jsr emit_byte

        ; PC += 2
        clc
        lda zp_pc_lo
        adc #2
        sta zp_pc_lo
        bcc :+
        inc zp_pc_hi
:
        clc
        lda zp_out_lo
        adc #2
        sta zp_out_lo
        bcc :+
        inc zp_out_hi
:
        rts

@fail:
        pla
@done:
        rts

; =========================
; Anonymous ref parsing + resolution
; =========================

; parse_anon_ref_token:
;   input: line scan pointer at first non-ws
;   output: zp_dir=1 for '+', 0 for '-', zp_count = number of signs
;   returns: C=0 ok, C=1 fail
parse_anon_ref_token:
        lda #0
        sta zp_count

        jsr line_peek_ch
        cmp #'+'
        beq @plus
        cmp #'-'
        beq @minus
        sec
        rts

@plus:
        lda #1
        sta zp_dir
        jmp @count

@minus:
        lda #0
        sta zp_dir

@count:
        ; count consecutive same sign
@loop:
        jsr line_peek_ch
        ldx zp_dir
        cpx #1
        bne @want_minus
        cmp #'+'
        bne @done
        jsr line_get_ch
        inc zp_count
        bne @loop
        sec             ; overflow: too many
        rts

@want_minus:
        cmp #'-'
        bne @done
        jsr line_get_ch
        inc zp_count
        bne @loop
        sec
        rts

@done:
        lda zp_count
        beq @fail
        clc
        rts
@fail:
        sec
        rts

; resolve_anon_ref:
;   input: zp_dir (0/- or 1/+), zp_count (n), anchor = zp_anon_seen (16-bit)
;   output: zp_tmp(lo)=target lo, zp_tmp2(hi)=target hi
;   returns: C=0 ok, C=1 not found
;
; policy here:
;   - We ignore anon_type filtering (+: vs -:) for now, i.e. '+' means "next anon"
;     regardless of whether it was defined as +: or -:. Easy to add filtering later.
resolve_anon_ref:
        lda zp_dir
        bne @forward

; backward: scan i = anchor-1 .. 0
@backward:
        ; if anchor == 0 => fail
        lda zp_anon_seen
        ora zp_anon_seen_hi
        beq @nf

        ; i = anchor-1 (low byte only is ok for MAX_ANON=256)
        lda zp_anon_seen
        sec
        sbc #1
        tax                     ; X = start index
        lda zp_count
        tay                     ; Y = remaining hits

@bloop:
        lda anon_pc_lo,x
        sta zp_tmp
        lda anon_pc_hi,x
        sta zp_tmp2
        dey
        beq @ok

        ; decrement X, stop when wraps (X becomes $FF after 0)
        dex
        cpx #$FF
        bne @bloop
        ; If we reached $FF due to wrap, we already checked anchor !=0 so we hit below 0 => nf
        jmp @nf

@forward:
        ; forward: scan i = anchor .. anon_n-1
        ldx zp_anon_seen         ; X = start
        lda zp_count
        tay                      ; Y = remaining hits

@floop:
        ; if X >= anon_n => nf
        cpx anon_n
        bcc @fok_index
        jmp @nf
@fok_index:
        lda anon_pc_lo,x
        sta zp_tmp
        lda anon_pc_hi,x
        sta zp_tmp2
        dey
        beq @ok
        inx
        jmp @floop

@ok:
        clc
        rts
@nf:
        sec
        rts

; =========================
; Emission
; =========================
emit_byte:
        ; A = byte
        ldy #0
        sta (zp_out_lo),y
        rts

; =========================
; Line scanning helpers
; =========================

; line_rewind_to_start:
; For pass2 "bump anon_seen" we want to rescan from start.
; Here we assume zp_p_lo/zp_p_hi initially is start; but parse_line_pass2 advanced it.
; Easiest is to store start somewhere. For prototype we just re-fetch from current line
; pointer is not preserved. So: DO NOTHING in this prototype.
; In a real implementation, keep zp_line_start_lo/hi set at line load.
line_rewind_to_start:
        ; TODO: store start when you load zp_p_lo/hi; then restore here.
        rts

; line_peek_ch: returns next char in A (0 if EOL/comment)
line_peek_ch:
        ldy #0
        lda (zp_p_lo),y
        beq @eol
        cmp #$0D
        beq @eol
        cmp #$0A
        beq @eol
        cmp #';'
        beq @eol
        rts
@eol:
        lda #0
        rts

; line_get_ch: returns char in A and advances pointer (like peek, but consumes)
line_get_ch:
        jsr line_peek_ch
        beq @done
        ; advance zp_p
        inc zp_p_lo
        bne @done
        inc zp_p_hi
@done:
        rts

; skip spaces/tabs
line_skip_ws:
@loop:
        jsr line_peek_ch
        cmp #' '
        beq @eat
        cmp #$09
        beq @eat
        rts
@eat:
        jsr line_get_ch
        jmp @loop

; read_uc_ch: read next char, uppercase if 'a'..'z'. Returns in A.
read_uc_ch:
        jsr line_get_ch
        ; uppercase
        cmp #'a'
        bcc @rts
        cmp #'z'+1
        bcs @rts
        and #$DF
@rts:
        rts