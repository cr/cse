; repl.s — REPL command line interface (hand-ported from repl.c)
;
; The screen IS the command buffer.  Press RETURN on any line
; to execute it.  AAAA:cmd [args] for addressed commands,
; cmd [args] for bare commands.  ';' ends parsing.

        .setcpu "6502"
        .macpack longbranch

; ── Exports ────────────────────────────────────────────────
        .export _exec_line, _read_line, _show_prompt
        .export _cur_addr, _cur_device, _cur_filename
        ; test harness visibility
        .export line_buf, last_cmd, block_size
        .export pushax

; ── Imports: cse_io.s ──────────────────────────────────────
        .import _io_putc, _io_puts
        .import _io_puthex4, _io_puthex2, _io_putdec
        .import _io_clear_eol
        .import _io_getc, _io_kbhit
        .import scr_lo, scr_hi

; ── Imports: screen.s ──────────────────────────────────────
        .import _newline, _restore_colors, _reset_screen
        .import _theme_border, _theme_bg, _theme_fg

; hex_val, is_hex, hex_val_to_char are now local (below)

; ── Imports: assembler / disassembler ──────────────────────
        .import _asm_line
        .import _dasm_insn, _dasm_buf
        .import _asm_assemble, _asm_org, _asm_size

; ── Imports: debugger ──────────────────────────────────────
        .import _dbg_enter, _dbg_step_clear
        .import _dbg_bp_set, _dbg_bp_del, _dbg_bp_clear
        .import _dbg_bp_count
        .import _bp_table, _step_bp
        .import _dbg_reason, _dbg_bp_hit
        .import _brk_pc
        .import _reg_a, _reg_x, _reg_y, _reg_sp, _reg_p

; ── Imports: expression parser ─────────────────────────────
        .import _expr_eval, _expr_error_str
        .importzp expr_ptr, expr_val

; ── Imports: symbol table ──────────────────────────────────
        .import _sym_lookup
        .importzp sym_name, sym_val

;── Imports: disk I/O ──────────────────────────────────────
        .import _floppy_status, _list_directory
        .import _disk_load_prg, _disk_save_prg

; ── Imports: editor ────────────────────────────────────────
        .import _ed_save_source, _ed_load_source
        .import _ed_save_bytes, _ed_save_lines
        .import _tab_width, _ed_ensure_init, _ed_new
        .import _ed_dirty

; ── Imports: memory info ───────────────────────────────────
        .import _cse_start, _cse_end, _cse_zp_end
        .import _src_top, _src_bot

; ── Imports: global state ──────────────────────────────────
        .import _state
        .importzp _al_cpu

; ── Imports: cc65 ZP / runtime ─────────────────────────────
        .importzp sp, ptr1, ptr2, tmp1, tmp2

; ── Constants ──────────────────────────────────────────────
SCREEN        = $0400
SCREEN_WIDTH  = 40
FILENAME_MAX  = 16
ST_STOP       = 0
CUR_COL       = $D3
CUR_ROW       = $D6

; ═══════════════════════════════════════════════════════════
; ZP: ptr1 = q (parse pointer into line_buf or args)
;     ptr2 = secondary pointer (output buffer, data src)
;     tmp1, tmp2 = scratch bytes
;
; BSS scratch:
;   rp_addr (2) — address argument (cur_addr copy for commands)
;   rp_save (1) — saved byte (olen, cols, etc.)
;   rp_save2(1) — secondary scratch
;   rp_cnt  (2) — 16-bit counter
;   rp_next_lo(2) — cmd_step next PC low
;   rp_next_hi(2) — cmd_step next PC high
; ═══════════════════════════════════════════════════════════

; ── DATA ───────────────────────────────────────────────────
.segment "DATA"

_cur_addr:      .word $1000
_cur_device:    .byte $08
last_cmd:       .byte $00
block_size:     .word $0010
_cur_filename:  .byte $00
                .res FILENAME_MAX, $00

; ── BSS ────────────────────────────────────────────────────
.segment "BSS"

line_buf:       .res 42
dot_asm_buf:    .res 24
rp_addr:        .res 2          ; working address
rp_save:        .res 1          ; general scratch byte
rp_save2:       .res 1          ; secondary scratch byte
rp_cnt:         .res 2          ; loop counter (16-bit)
rp_next_lo:     .res 2          ; cmd_step
rp_next_hi:     .res 2          ; cmd_step
rp_opc:         .res 1          ; cmd_step saved opcode
rp_dis_bp:      .res 1          ; cmd_step: disabled bp slot*4 ($FF=none)
rp_hexbuf:      .res 3          ; cmd_dot hex byte parse
fbuf:           .res 20         ; free_line / utoa buffer

; ── RODATA ─────────────────────────────────────────────────
.segment "RODATA"

dec_pow_lo:     .byte <10000, <1000, <100, <10, <1
dec_pow_hi:     .byte >10000, >1000, >100, >10, >1

flag_ch:        .byte "nv-bdizc"
bp_pfx:         .byte "; bp ", 0
str_3sp:        .byte "   ", 0
str_2sp:        .byte "  ", 0
str_brk:        .byte "; brk", 0
str_at:         .byte " at $", 0
str_nmi:        .byte "; nmi break at $", 0
str_bp_clr:     .byte "; breakpoints cleared", 0
str_deleted:    .byte " deleted", 0
str_slot18:     .byte ";?slot 1-8", 0
str_bp_full:    .byte ";?bp full", 0
str_err_b:      .byte ";?b", 0
str_err_cmd:    .byte ";?cmd", 0
str_err_asm:    .byte ";?asm", 0
str_err_name:   .byte ";?name", 0
str_err_range:  .byte ";?range", 0
str_err_load:   .byte ";?load ", 0
str_err_save:   .byte ";?save ", 0
str_err_expr:   .byte ";?", 0
str_r_pc:       .byte "r pc:", 0
str_a:          .byte " a:", 0
str_x:          .byte " x:", 0
str_y:          .byte " y:", 0
str_s:          .byte " s:", 0
str_semi_q:     .byte "; ", $22, 0        ; '; "'
str_qcolon:     .byte $22, ": ", 0        ; '": '
str_lines:      .byte " lines, ", 0
str_bytes:      .byte " bytes", 0
str_bytes_at:   .byte " bytes at $", 0
str_bytes_sp:   .byte " bytes ", 0
str_del_src:    .byte ";delete source. are you sure? y/n ", 0
str_unsaved:    .byte ";unsaved. y/n? ", 0
str_ok:         .byte "ok", 0
str_B_eq:       .byte ";B=", 0             ; note: PETSCII uppercase B
str_T_eq:       .byte ";t=", 0
str_color:      .byte ";color: ", 0
str_cpu:        .byte ";cpu: 6502", 0
.ifdef CPU_6510
str_6510:       .byte " 6510", 0
.endif
.ifdef CMOS_SUPPORT
str_65c02:      .byte " 65c02", 0
.endif
str_asm_ing:    .byte ";assembling...", 0
str_ok_colon:   .byte "; ok: ", 0
str_semi:       .byte "; ", 0
str_errors:     .byte " error(s)", 0
str_no_break:   .byte ";?no break", 0
str_quit:       .byte ";quit? y/n ", 0
str_dashes:     .byte "----", 0
str_colon_sp:   .byte ": ", 0
str_pct:        .byte "  %", 0
; info strings
str_ioport:     .byte "i/o port", 0
str_zp_saved:   .byte "cse (saved on j)", 0
str_kernal:     .byte "kernal", 0
str_stack:      .byte "6502 stack", 0
str_kern_work:  .byte "kernal work", 0
str_screen:     .byte "screen+sprites", 0
str_code_data:  .byte "code+data+bss", 0
str_bytes_free: .byte " bytes free", 0
str_source:     .byte "source code", 0
str_c_stack:    .byte "c stack", 0
str_vic:        .byte "vic/sid/cia", 0
str_kern_rom:   .byte "kernal rom", 0
str_main:       .byte "main", 0

; info_line tag strings
str_tag_cpu:    .byte "cpu", 0
str_tag_zp:     .byte "zp", 0
str_tag_stk:    .byte "stk", 0
str_tag_sys:    .byte "sys", 0
str_tag_scr:    .byte "scr", 0
str_tag_cse:    .byte "cse", 0
str_tag_work:   .byte "work", 0
str_tag_src:    .byte "src", 0
str_tag_cstk:   .byte "cstk", 0
str_tag_io:     .byte "io", 0
str_tag_kern:   .byte "kern", 0

; ── info tables: 8 bytes per row: tag(2) lo(2) hi(2) desc(2) ──
; Head: cpu only (before dynamic zp section)
info_tbl:
        .addr str_tag_cpu,  $0000, $0001, str_ioport        ; cpu  0000-0001
INFO_TBL_ROWS = (* - info_tbl) / 8

; Mid: static rows between zp-dynamic and cse-dynamic
info_tbl_mid:
        .addr str_tag_zp,   $0080, $00FF, str_kernal        ; zp   0080-00ff
        .addr str_tag_stk,  $0100, $01FF, str_stack          ; stk  0100-01ff
        .addr str_tag_sys,  $0200, $03FF, str_kern_work      ; sys  0200-03ff
        .addr str_tag_scr,  $0400, $07FF, str_screen         ; scr  0400-07ff
INFO_TBL_MID_ROWS = (* - info_tbl_mid) / 8

; Tail: after dynamic cse/free/src
info_tbl_tail:
        .addr str_tag_cstk, $C800, $CFFF, str_c_stack       ; cstk c800-cfff
        .addr str_tag_io,   $D000, $DFFF, str_vic            ; io   d000-dfff
        .addr str_tag_kern, $E000, $FFFF, str_kern_rom       ; kern e000-ffff
INFO_TBL_TAIL_ROWS = (* - info_tbl_tail) / 8


; ── CODE ───────────────────────────────────────────────────
.segment "CODE"

; ═══════════════════════════════════════════════════════════
; pushax — push A/X onto cc65 C stack
;   Used to pass first arg to __fastcall__ 2-arg functions
; ═══════════════════════════════════════════════════════════
.proc pushax
        ldy sp
        dey
        dey
        sty sp
        sta (sp),y
        iny
        txa
        sta (sp),y
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; Inline helpers
; ═══════════════════════════════════════════════════════════

; nl_clear — newline + clear_eol
nl_clear:
        jsr _newline
        jmp _io_clear_eol

; ───────────────────────────────────────────────────────────
; io_addr_cmd — print "XXXX:C" at column 0
;   rp_addr = address, A = command char
; ───────────────────────────────────────────────────────────
io_addr_cmd:
        pha
        lda #0
        sta CUR_COL
        lda rp_addr
        ldx rp_addr+1
        jsr _io_puthex4
        lda #':'
        jsr _io_putc
        pla
        jmp _io_putc

; ───────────────────────────────────────────────────────────
; err_msg — newline + print string + clear_eol
;   A/X = string ptr
; ───────────────────────────────────────────────────────────
err_msg:
        pha
        txa
        pha
        jsr _newline
        pla
        tax
        pla
        jsr _io_puts
        jmp _io_clear_eol

; ───────────────────────────────────────────────────────────
; check_unsaved — if ed_dirty, prompt ";unsaved. y/n? "
;   Returns: C=1 proceed (not dirty or user said y)
;            C=0 cancel (user said no)
; ───────────────────────────────────────────────────────────
check_unsaved:
        lda _ed_dirty
        beq @ok                 ; not dirty → proceed
        jsr _newline
        lda #<str_unsaved
        ldx #>str_unsaved
        jsr _io_puts
        jsr _io_getc
        cmp #'y'
        beq @ok
        jsr _io_clear_eol
        clc                     ; cancel
        rts
@ok:    sec                     ; proceed
        rts

; ───────────────────────────────────────────────────────────
; skip_sp_ptr1 — skip spaces at (ptr1), advancing ptr1
; ───────────────────────────────────────────────────────────
skip_sp_ptr1:
        ldy #0
@lp:    lda (ptr1),y
        cmp #' '
        bne @done
        inc ptr1
        bne @lp
        inc ptr1+1
        bne @lp
@done:  rts

; ───────────────────────────────────────────────────────────
; _hex_val — PETSCII char in A → nibble (0-15), or $FF if not hex
;   Preserves Y.
; ───────────────────────────────────────────────────────────
_hex_val:
        cmp #'0'
        bcc @bad
        cmp #'9'+1
        bcc @digit
        ; PETSCII letters: a-f = $41-$46 (lowercase), A-F = $C1-$C6 (uppercase)
        cmp #'a'                ; $41
        bcc @bad
        cmp #'f'+1              ; $47
        bcc @alpha
        ; try uppercase shifted range $C1-$C6
        cmp #$C1
        bcc @bad
        cmp #$C7
        bcs @bad
        sbc #$C0-10             ; C=0 from bcs: A - ($C0-10) - 1 = A - $B7
        rts
@digit: sbc #'0'-1              ; C=1 from cmp: A - '0'
        rts
@alpha: sbc #'a'-10-1           ; C=1 from cmp: A - ($41-10) = A - $37
        rts
@bad:   lda #$FF
        rts

; ───────────────────────────────────────────────────────────
; _is_hex — PETSCII char in A → A=1 (Z=0) if hex, A=0 (Z=1) if not
;   Preserves Y.
; ───────────────────────────────────────────────────────────
_is_hex:
        jsr _hex_val
        cmp #$FF
        beq @no
        lda #1                  ; Z=0
        rts
@no:    lda #0                  ; Z=1
        rts

; ───────────────────────────────────────────────────────────
; _hex_val_to_char — nibble (0-15) in A → PETSCII hex char
;   Preserves Y.
; ───────────────────────────────────────────────────────────
_hex_val_to_char:
        cmp #10
        bcs @alpha
        adc #'0'                ; C=0 from bcs
        rts
@alpha: adc #'a'-10-1           ; C=1 from cmp: A + 'a' - 10
        rts

; ───────────────────────────────────────────────────────────
; is_hex_at_ptr1 — test if byte at (ptr1)+Y is hex
;   Returns: Z=0 if hex, Z=1 if not. Preserves Y.
; ───────────────────────────────────────────────────────────
is_hex_at_ptr1:
        lda (ptr1),y
        jmp _is_hex             ; tail call; Z flag set on return

; ───────────────────────────────────────────────────────────
; hex_val_at_ptr1 — get hex value of byte at (ptr1)+Y
;   Returns nibble in A (0-15). Preserves Y.
; ───────────────────────────────────────────────────────────
hex_val_at_ptr1:
        lda (ptr1),y
        jmp _hex_val

; ───────────────────────────────────────────────────────────
; parse_hex2_ptr1 — parse 2 hex digits at ptr1, advance ptr1
;   Returns byte in A.
; ───────────────────────────────────────────────────────────
parse_hex2_ptr1:
        ldy #0
        lda (ptr1),y
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta tmp1
        ldy #1
        lda (ptr1),y
        jsr _hex_val
        ora tmp1
        pha
        lda ptr1
        clc
        adc #2
        sta ptr1
        bcc :+
        inc ptr1+1
:       pla
        rts

; ───────────────────────────────────────────────────────────
; parse_hex4_ptr1 — parse 4 hex digits at ptr1, advance ptr1
;   Returns value in A (lo) / X (hi).
; ───────────────────────────────────────────────────────────
parse_hex4_ptr1:
        ldy #0
        lda (ptr1),y
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta tmp2                ; hi nibble of high byte
        ldy #1
        lda (ptr1),y
        jsr _hex_val
        ora tmp2
        sta tmp2                ; high byte complete
        ldy #2
        lda (ptr1),y
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta tmp1
        ldy #3
        lda (ptr1),y
        jsr _hex_val
        ora tmp1                ; A = lo byte
        pha
        lda ptr1
        clc
        adc #4
        sta ptr1
        bcc :+
        inc ptr1+1
:       pla                     ; A = lo
        ldx tmp2                ; X = hi
        rts

; ═══════════════════════════════════════════════════════════
; put_dec5_sp — print rp_addr as up to 5 decimal digits, space-padded
; ═══════════════════════════════════════════════════════════
.proc put_dec5_sp
        ldx #0                  ; digit index
        stx rp_save2            ; started flag
@digit: lda #0
        sta rp_save             ; d count
@sub:   lda rp_addr
        sec
        sbc dec_pow_lo,x
        tay
        lda rp_addr+1
        sbc dec_pow_hi,x
        bcc @emit_chk
        sta rp_addr+1
        sty rp_addr
        inc rp_save
        bne @sub
@emit_chk:
        lda rp_save
        bne @emit
        lda rp_save2
        bne @emit
        cpx #4
        beq @force
        stx tmp1
        lda #' '
        jsr _io_putc
        ldx tmp1
        inx
        bne @digit
@force: lda #0
@emit:  clc
        adc #'0'
        stx tmp1
        jsr _io_putc
        ldx tmp1
        lda #1
        sta rp_save2
        inx
        cpx #5
        bcc @digit
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; utoa_sub — convert rp_addr to decimal at fbuf
;   Returns length in A. NUL-terminated.
; ═══════════════════════════════════════════════════════════
.proc utoa_sub
        lda #0
        sta rp_save2            ; started flag
        sta rp_save             ; output pos
        ldx #0                  ; digit index
@digit: lda #0
        sta tmp1                ; d
@sub:   lda rp_addr
        sec
        sbc dec_pow_lo,x
        tay
        lda rp_addr+1
        sbc dec_pow_hi,x
        bcc @chk
        sta rp_addr+1
        sty rp_addr
        inc tmp1
        bne @sub
@chk:   lda tmp1
        bne @emit
        lda rp_save2
        bne @emit
        cpx #4
        bne @next
@emit:  lda tmp1
        clc
        adc #'0'
        ldy rp_save
        sta fbuf,y
        iny
        sty rp_save
        lda #1
        sta rp_save2
@next:  inx
        cpx #5
        bcc @digit
        ldy rp_save
        lda #0
        sta fbuf,y              ; NUL
        tya                     ; return length
        rts
.endproc


; ═══════════════════════════════════════════════════════════
; try_expr — evaluate expression at ptr1
;   C=1: success (result in expr_val, ptr1 advanced)
;   C=0: empty or error (error printed)
; ═══════════════════════════════════════════════════════════
.proc try_expr
        jsr skip_sp_ptr1
        ldy #0
        lda (ptr1),y
        beq @empty
        cmp #';'
        beq @empty
        ; set expr_ptr = ptr1
        lda ptr1
        sta expr_ptr
        lda ptr1+1
        sta expr_ptr+1
        jsr _expr_eval
        ; reload ptr1
        pha
        lda expr_ptr
        sta ptr1
        lda expr_ptr+1
        sta ptr1+1
        pla
        cmp #2
        bcs @error
        sec
        rts
@error:
        jsr _newline
        lda #<str_err_expr
        ldx #>str_err_expr
        jsr _io_puts
        jsr _expr_error_str
        jsr _io_puts
        jsr _io_clear_eol
        clc
        rts
@empty: clc
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; _read_line — read screen row at io_cy into line_buf
; ═══════════════════════════════════════════════════════════
.proc _read_line
        ldx CUR_ROW
        lda scr_lo,x
        sta ptr1
        lda scr_hi,x
        sta ptr1+1

        ldy #0
@loop:  lda (ptr1),y
        and #$7F
        cmp #$20
        bcc @lower
        cmp #$41
        bcc @store
        cmp #$5B
        bcs @store
        ; $41..$5A → +$80
        clc
        adc #$80
        bne @store              ; always
@lower: ; $00..$1F → +$40
        clc
        adc #$40
@store: sta line_buf,y
        iny
        cpy #SCREEN_WIDTH
        bcc @loop

        ; trim trailing spaces
        ldy #SCREEN_WIDTH
@trim:  dey
        bmi @zero
        lda line_buf,y
        cmp #' '
        beq @trim
        iny
@zero:  lda #0
        sta line_buf,y
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; _show_prompt — print "AAAA:" at cursor
; ═══════════════════════════════════════════════════════════
.proc _show_prompt
        lda #0
        sta CUR_COL
        lda _cur_addr
        ldx _cur_addr+1
        jsr _io_puthex4
        lda #':'
        jmp _io_putc
.endproc

; ═══════════════════════════════════════════════════════════
; emit_hex_cols — print hex columns
;   ptr2 = src, rp_save = count, rp_save2 = max
; ═══════════════════════════════════════════════════════════
.proc emit_hex_cols
        ldy #0
@loop:  cpy rp_save2
        bcs @done
        cpy rp_save
        bcs @pad
        lda #' '
        sty tmp1
        jsr _io_putc
        ldy tmp1
        lda (ptr2),y
        sty tmp1
        jsr _io_puthex2
        ldy tmp1
        iny
        bne @loop
@pad:   lda #<str_3sp
        ldx #>str_3sp
        sty tmp1
        jsr _io_puts
        ldy tmp1
        iny
        bne @loop
@done:  rts
.endproc

; ═══════════════════════════════════════════════════════════
; emit_dot — disassemble and display "ADDR:. XX XX XX  mne op"
;   rp_addr = address. Returns instruction length in A.
; ═══════════════════════════════════════════════════════════
.proc emit_dot
        lda rp_addr
        ldx rp_addr+1
        jsr _dasm_insn
        pha                     ; save olen

        lda #'.'
        jsr io_addr_cmd
        lda #' '
        jsr _io_putc

        ; emit_hex_cols(addr, olen, 3)
        lda rp_addr
        sta ptr2
        lda rp_addr+1
        sta ptr2+1
        pla                     ; olen
        pha
        sta rp_save             ; count
        lda #3
        sta rp_save2            ; max
        jsr emit_hex_cols

        lda #<str_2sp
        ldx #>str_2sp
        jsr _io_puts
        lda #<_dasm_buf
        ldx #>_dasm_buf
        jsr _io_puts
        jsr _io_clear_eol

        pla                     ; return olen
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; emit_mem — print memory dump line
;   rp_addr = address, A = cols (0→8, >8→8)
; ═══════════════════════════════════════════════════════════
.proc emit_mem
        cmp #0
        bne @n0
        lda #8
@n0:    cmp #9
        bcc @ok
        lda #8
@ok:    sta rp_opc              ; cols (borrowing rp_opc)

        lda #'m'
        jsr io_addr_cmd

        lda rp_addr
        sta ptr2
        lda rp_addr+1
        sta ptr2+1
        lda rp_opc
        sta rp_save
        lda #8
        sta rp_save2
        jsr emit_hex_cols

        lda #' '
        jsr _io_putc

        ldy #0
@asc:   cpy rp_opc
        bcs @adone
        lda (ptr2),y
        cmp #$20
        bcc @dot
        cmp #$7F
        bcs @dot
        bcc @aput
@dot:   lda #'.'
@aput:  sty tmp1
        jsr _io_putc
        ldy tmp1
        iny
        bne @asc
@adone: jmp _io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; emit_reg — print register dump
; ═══════════════════════════════════════════════════════════
.proc emit_reg
        lda #0
        sta CUR_COL
        lda #<str_r_pc
        ldx #>str_r_pc
        jsr _io_puts
        lda _brk_pc
        ldx _brk_pc+1
        jsr _io_puthex4
        lda #<str_a
        ldx #>str_a
        jsr _io_puts
        lda _reg_a
        jsr _io_puthex2
        lda #<str_x
        ldx #>str_x
        jsr _io_puts
        lda _reg_x
        jsr _io_puthex2
        lda #<str_y
        ldx #>str_y
        jsr _io_puts
        lda _reg_y
        jsr _io_puthex2
        lda #<str_s
        ldx #>str_s
        jsr _io_puts
        lda _reg_sp
        jsr _io_puthex2
        lda #' '
        jsr _io_putc

        lda _reg_p
        sta tmp2
        ldx #0
@fl:    asl tmp2
        bcs @set
        lda #'.'
        bne @fp
@set:   lda flag_ch,x
@fp:    stx tmp1
        jsr _io_putc
        ldx tmp1
        inx
        cpx #8
        bcc @fl
        jmp _io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; show_break_result — restore colors, optional status msg, regs + disasm
;
; Unified return-to-REPL path after running user code.
; If dbg_reason=1 (BRK), prints "; brk [N] at $XXXX".
; If dbg_reason=2 (NMI), prints "; nmi break at $XXXX".
; Otherwise (normal step completion), skips the status line.
; Always: restore_colors, register dump, disassembly at brk_pc.
; ═══════════════════════════════════════════════════════════
.proc show_break_result
        jsr _restore_colors

        lda _dbg_reason
        cmp #1
        beq @brk
        cmp #2
        beq @nmi
        jmp @regs                ; normal completion — skip status line

@brk:   jsr _newline
        lda #<str_brk
        ldx #>str_brk
        jsr _io_puts
        lda _dbg_bp_hit
        cmp #$FF
        beq @brk_at
        lda #' '
        jsr _io_putc
        lda _dbg_bp_hit
        clc
        adc #'1'
        jsr _io_putc
@brk_at:
        lda #<str_at
        ldx #>str_at
        jsr _io_puts
        lda _brk_pc
        ldx _brk_pc+1
        jsr _io_puthex4
        jsr _io_clear_eol
        jmp @regs

@nmi:   jsr _newline
        lda #<str_nmi
        ldx #>str_nmi
        jsr _io_puts
        lda _brk_pc
        ldx _brk_pc+1
        jsr _io_puthex4
        jsr _io_clear_eol

@regs:  ; register dump + disassembly at brk_pc
        jsr _newline
        jsr emit_reg
        jsr _newline
        lda _brk_pc
        sta _cur_addr
        sta rp_addr
        lda _brk_pc+1
        sta _cur_addr+1
        sta rp_addr+1
        jsr emit_dot
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; dot_assemble — assemble with expression support
;   rp_addr = address, ptr1 = text. Returns nbytes in A.
; ═══════════════════════════════════════════════════════════
.proc dot_assemble
        lda #<dot_asm_buf
        sta ptr2
        lda #>dot_asm_buf
        sta ptr2+1

        ; Copy mnemonic (a-z)
        ldy #0
@mne:   lda (ptr1),y
        cmp #'a'
        bcc @md
        cmp #'z'+1
        bcs @md
        cpy #8
        bcs @md
        sta dot_asm_buf,y
        iny
        bne @mne
@md:    sty rp_save             ; buf write pos

        ; advance ptr1 past mnemonic
        tya
        clc
        adc ptr1
        sta ptr1
        bcc :+
        inc ptr1+1
:
        jsr skip_sp_ptr1

        ldy #0
        lda (ptr1),y
        jeq @implied
        cmp #';'
        jeq @implied

        ; append space
        ldy rp_save
        lda #' '
        sta dot_asm_buf,y
        iny
        sty rp_save

        ; prefix: # and/or (
        ldy #0
        lda (ptr1),y
        cmp #'#'
        bne @noh
        ldy rp_save
        sta dot_asm_buf,y
        iny
        sty rp_save
        inc ptr1
        bne :+
        inc ptr1+1
:       jsr skip_sp_ptr1
@noh:   ldy #0
        lda (ptr1),y
        cmp #'('
        bne @nop
        ldy rp_save
        sta dot_asm_buf,y
        iny
        sty rp_save
        inc ptr1
        bne :+
        inc ptr1+1
:       jsr skip_sp_ptr1
@nop:
        ; evaluate expression
        lda ptr1
        sta expr_ptr
        lda ptr1+1
        sta expr_ptr+1
        jsr _expr_eval
        cmp #2
        jcs @err
        pha                     ; save rc (0=ZP, 1=ABS)

        lda expr_ptr
        sta ptr1
        lda expr_ptr+1
        sta ptr1+1

        ; append '$'
        ldy rp_save
        lda #'$'
        sta dot_asm_buf,y
        iny
        sty rp_save

        pla                     ; rc
        cmp #1
        bne @lo

        ; ABS: 4 hex digits
        lda expr_val+1
        lsr
        lsr
        lsr
        lsr
        jsr _hex_val_to_char
        ldy rp_save
        sta dot_asm_buf,y
        iny
        lda expr_val+1
        and #$0F
        jsr _hex_val_to_char
        sta dot_asm_buf,y
        iny
        sty rp_save

@lo:    ; low byte: 2 hex digits
        lda expr_val
        lsr
        lsr
        lsr
        lsr
        jsr _hex_val_to_char
        ldy rp_save
        sta dot_asm_buf,y
        iny
        lda expr_val
        and #$0F
        jsr _hex_val_to_char
        sta dot_asm_buf,y
        iny
        sty rp_save

        ; copy suffix
        jsr skip_sp_ptr1
@sfx:   ldy #0
        lda (ptr1),y
        beq @done
        cmp #';'
        beq @done
        ldy rp_save
        cpy #22
        bcs @done
        sta dot_asm_buf,y
        iny
        sty rp_save
        inc ptr1
        bne @sfx
        inc ptr1+1
        bne @sfx

@done:  ; NUL-terminate and call asm_line
        ldy rp_save
        lda #0
        sta dot_asm_buf,y
        jmp @call_asm

@implied:
        ldy rp_save
        lda #0
        sta dot_asm_buf,y

@call_asm:
        ; asm_line(addr, buf) — __fastcall__: push addr, buf in A/X
        lda rp_addr
        ldx rp_addr+1
        jsr pushax
        lda #<dot_asm_buf
        ldx #>dot_asm_buf
        jmp _asm_line

@err:   lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_dot — '.' command: hex edit / assemble / disassemble
;   ptr1 = args
; ═══════════════════════════════════════════════════════════
.proc cmd_dot
        lda _cur_addr
        sta rp_addr
        lda _cur_addr+1
        sta rp_addr+1

        jsr skip_sp_ptr1

        ; Parse up to 3 hex byte pairs
        lda #0
        sta rp_cnt              ; nbytes

@hex_lp:
        lda rp_cnt
        cmp #3
        bcs @hex_done
        ldy #0
        jsr is_hex_at_ptr1
        beq @hex_done
        ldy #1
        jsr is_hex_at_ptr1
        beq @hex_done
        ; check ptr1[2] is space/NUL/;
        ldy #2
        lda (ptr1),y
        cmp #' '
        beq @parse_b
        cmp #0
        beq @parse_b
        cmp #';'
        bne @hex_done
@parse_b:
        jsr parse_hex2_ptr1
        ldx rp_cnt
        sta rp_hexbuf,x
        inx
        stx rp_cnt
        jsr skip_sp_ptr1
        jmp @hex_lp

@hex_done:
        lda rp_cnt
        jeq @try_mne

        ; Check if bytes changed vs memory
        ldy #0
        sty rp_save             ; changed flag
@cmp:   cpy rp_cnt
        bcs @cmp_done
        ; read mem at rp_addr+Y
        sty tmp1
        tya
        clc
        adc rp_addr
        sta ptr2
        lda #0
        adc rp_addr+1
        sta ptr2+1
        ldy #0
        lda (ptr2),y
        ldy tmp1
        cmp rp_hexbuf,y
        beq @cmatch
        lda #1
        sta rp_save
@cmatch:
        iny
        bne @cmp

@cmp_done:
        lda rp_save
        beq @try_asm_mne        ; not changed → try mnemonic

        ; Write changed bytes
        ldy #0
@write: cpy rp_cnt
        bcs @show
        sty tmp1
        lda rp_hexbuf,y
        pha
        tya
        clc
        adc rp_addr
        sta ptr2
        lda #0
        adc rp_addr+1
        sta ptr2+1
        pla
        ldy #0
        sta (ptr2),y
        ldy tmp1
        iny
        bne @write

@show:  ; emit_dot, advance cur_addr, newline
        ; if rp_cnt (nbytes) > 0, skip clear_eol
        jsr emit_dot
        clc
        adc rp_addr
        sta _cur_addr
        lda #0
        adc rp_addr+1
        sta _cur_addr+1
        jsr _newline
        lda rp_cnt
        bne @ret                ; nbytes > 0 → don't clear
        jmp _io_clear_eol
@ret:   rts

@try_asm_mne:
@try_mne:
        ; Try mnemonic assembly if (ptr1) starts with a-z
        jsr skip_sp_ptr1
        ldy #0
        lda (ptr1),y
        cmp #'a'
        bcc @show               ; no mnemonic → just show
        cmp #'z'+1
        bcs @show
        jsr dot_assemble
        cmp #0
        bne @show               ; success → show result
        lda #<str_err_asm
        ldx #>str_err_asm
        jsr err_msg
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_disasm — 'd' command
;   ptr1 = args (ignored)
; ═══════════════════════════════════════════════════════════
.proc cmd_disasm
        lda _cur_addr
        sta rp_addr
        lda _cur_addr+1
        sta rp_addr+1

        ; end = addr + block_size
        lda rp_addr
        clc
        adc block_size
        sta rp_cnt
        lda rp_addr+1
        adc block_size+1
        sta rp_cnt+1
        ; if overflow, end = $FFFF
        bcc @loop
        lda #$FF
        sta rp_cnt
        sta rp_cnt+1

@loop:  ; while addr < end
        lda rp_addr+1
        cmp rp_cnt+1
        bcc @ok
        bne @done
        lda rp_addr
        cmp rp_cnt
        bcs @done
@ok:
        jsr emit_dot            ; returns olen in A
        ; addr += olen
        clc
        adc rp_addr
        sta rp_addr
        bcc :+
        inc rp_addr+1
:       jsr _newline
        ; if addr wrapped to 0, break
        lda rp_addr
        ora rp_addr+1
        bne @loop

@done:  lda rp_addr
        sta _cur_addr
        lda rp_addr+1
        sta _cur_addr+1
        jmp _io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_mem — 'm' command: memory dump / edit
;   ptr1 = args
; ═══════════════════════════════════════════════════════════
.proc cmd_mem
        lda _cur_addr
        sta rp_addr
        lda _cur_addr+1
        sta rp_addr+1

        jsr skip_sp_ptr1

        ; Check for 4-digit hex address override
        ldy #0
        jsr is_hex_at_ptr1
        beq @no_addr
        ldy #1
        jsr is_hex_at_ptr1
        beq @no_addr
        ldy #2
        jsr is_hex_at_ptr1
        beq @no_addr
        ldy #3
        jsr is_hex_at_ptr1
        beq @no_addr
        ; check q[4] is space/NUL/;
        ldy #4
        lda (ptr1),y
        cmp #' '
        beq @addr_ok
        cmp #0
        beq @addr_ok
        cmp #';'
        beq @addr_ok
        jmp @no_addr
@addr_ok:
        jsr parse_hex4_ptr1
        sta rp_addr
        stx rp_addr+1
        jsr skip_sp_ptr1

@no_addr:
        ; Check for 2-digit hex edit bytes
        ldy #0
        jsr is_hex_at_ptr1
        jeq @dump
        ldy #1
        jsr is_hex_at_ptr1
        beq @dump
        ldy #2
        lda (ptr1),y
        cmp #' '
        beq @edit
        cmp #0
        beq @edit
        cmp #';'
        beq @edit
        jmp @dump

@edit:  ; Parse and write edit bytes
        lda #0
        sta rp_cnt              ; nbytes
@ed_lp: lda rp_cnt
        cmp #8
        bcs @ed_done
        ldy #0
        jsr is_hex_at_ptr1
        beq @ed_done
        ldy #1
        jsr is_hex_at_ptr1
        beq @ed_done
        jsr parse_hex2_ptr1
        ; write to addr+nbytes if different
        pha
        lda rp_cnt
        clc
        adc rp_addr
        sta ptr2
        lda #0
        adc rp_addr+1
        sta ptr2+1
        pla
        ldy #0
        cmp (ptr2),y
        beq @same
        sta (ptr2),y
@same:  inc rp_cnt
        jsr skip_sp_ptr1
        jmp @ed_lp

@ed_done:
        lda rp_cnt
        sta rp_save             ; nbytes for emit
        jsr emit_mem
        ; cur_addr = addr + nbytes
        lda rp_cnt
        clc
        adc rp_addr
        sta _cur_addr
        lda #0
        adc rp_addr+1
        sta _cur_addr+1
        ; check wrap
        bcs @wrap_ed
        jmp @ed_nl
@wrap_ed:
        lda #0
        sta _cur_addr
        sta _cur_addr+1
@ed_nl: jmp _newline

@dump:  ; Dump block_size bytes in 8-col rows
        lda block_size
        sta rp_cnt
        lda block_size+1
        sta rp_cnt+1

@d_lp:  lda rp_cnt
        ora rp_cnt+1
        beq @d_done
        ; cols = min(remaining, 8)
        lda rp_cnt+1
        bne @full
        lda rp_cnt
        cmp #8
        bcc @partial
@full:  lda #8
@partial:
        sta rp_save             ; cols
        jsr emit_mem
        ; addr += cols
        lda rp_save
        clc
        adc rp_addr
        sta rp_addr
        bcc :+
        inc rp_addr+1
:       ; remaining -= cols
        lda rp_cnt
        sec
        sbc rp_save
        sta rp_cnt
        bcs :+
        dec rp_cnt+1
:       jsr _newline
        ; check addr wrap (addr < cols means wrapped)
        lda rp_addr
        cmp rp_save
        lda rp_addr+1
        sbc #0
        bcc @d_done
        jmp @d_lp

@d_done:
        lda rp_addr
        sta _cur_addr
        lda rp_addr+1
        sta _cur_addr+1
        jmp _io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_jmp — 'j' command helper (cur_addr already set)
; ═══════════════════════════════════════════════════════════
.proc cmd_jmp
        lda _cur_addr
        sta _brk_pc
        lda _cur_addr+1
        sta _brk_pc+1

        ; Always use dbg_enter — enables NMI break even without bps.
        ; When no breakpoints, patch_all/unpatch_all are no-ops.
        jsr _dbg_enter
        lda _dbg_reason
        bne @j_broke
        ; program completed via RTS — no break context
        jsr _restore_colors
        jmp nl_clear
@j_broke:
        jmp show_break_result
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_step — 't'/'o' command
;   ptr1 = args, A = is_next (0=step into, 1=step over)
; ═══════════════════════════════════════════════════════════
.proc cmd_step
        sta rp_save2            ; is_next

        ; Cold start check
        lda _dbg_reason
        bne @has_ctx
        lda _cur_addr
        sta _brk_pc
        lda _cur_addr+1
        sta _brk_pc+1
        lda #1
        sta _dbg_reason
@has_ctx:

        ; Parse count via try_expr; empty → use block_size
        jsr try_expr
        bcc @def_count
        lda expr_val
        ora expr_val+1
        beq @def_count          ; zero → use default
        lda expr_val
        sta rp_cnt
        lda expr_val+1
        sta rp_cnt+1
        jmp @got_cnt

@def_count:
        lda block_size
        sta rp_cnt
        lda block_size+1
        sta rp_cnt+1

@got_cnt:
        lda #0
        sta rp_opc

        ; If we're sitting on a user bp, temporarily disable it so the
        ; first step can execute the instruction there instead of
        ; immediately re-triggering the bp.
        lda #$FF
        sta rp_dis_bp           ; $FF = no bp disabled
        lda _dbg_bp_hit
        cmp #$FF
        beq @loop               ; no bp hit → nothing to disable
        asl
        asl                     ; slot * 4
        tax
        stx rp_dis_bp           ; remember slot offset
        lda #0
        sta _bp_table+3,x       ; clear enabled flag

        ; for i = 0; i < count; i++
@loop:  lda rp_cnt
        ora rp_cnt+1
        jeq @normal_end

        ; opc = *(brk_pc)
        lda _brk_pc
        sta ptr2
        lda _brk_pc+1
        sta ptr2+1
        ldy #0
        lda (ptr2),y
        sta rp_opc

        ; next_lo = next_hi = 0
        lda #0
        sta rp_next_lo
        sta rp_next_lo+1
        sta rp_next_hi
        sta rp_next_hi+1

        ; ── Compute next-PC ──
        lda rp_opc

        ; BRK ($00)
        jeq @stop

        ; JSR abs ($20)
        cmp #$20
        jeq @jsr

        ; RTS ($60) / RTI ($40)
        cmp #$60
        jeq @stop
        cmp #$40
        jeq @stop

        ; JMP abs ($4C)
        cmp #$4C
        jeq @jmp_abs

        ; JMP (ind) ($6C)
        cmp #$6C
        jeq @jmp_ind

.ifdef CMOS_SUPPORT
        ; JMP (abs,x) ($7C) — 65C02 only
        cmp #$7C
        bne @not_7c
        lda _al_cpu
        cmp #2
        bcc @not_7c
        ; next_lo = *(*(brk_pc+1) + reg_x)
        ldy #1
        lda (ptr2),y
        clc
        adc _reg_x
        sta ptr1
        iny
        lda (ptr2),y
        adc #0
        sta ptr1+1
        ldy #0
        lda (ptr1),y
        sta rp_next_lo
        iny
        lda (ptr1),y
        sta rp_next_lo+1
        jmp @check_next

@not_7c:
        ; BRA ($80) — 65C02 unconditional
        lda rp_opc
        cmp #$80
        bne @not_bra
        lda _al_cpu
        cmp #2
        bcc @not_bra
        ; next_lo = brk_pc + 2 + (signed)*(brk_pc+1)
        ldy #1
        lda (ptr2),y            ; signed relative
        bpl @bra_pos
        ; negative offset
        clc
        adc _brk_pc
        sta rp_next_lo
        lda _brk_pc+1
        adc #$FF                ; sign extend
        sta rp_next_lo+1
        jmp @bra_add2
@bra_pos:
        clc
        adc _brk_pc
        sta rp_next_lo
        lda _brk_pc+1
        adc #0
        sta rp_next_lo+1
@bra_add2:
        lda rp_next_lo
        clc
        adc #2
        sta rp_next_lo
        bcc :+
        inc rp_next_lo+1
:       jmp @check_next

@not_bra:
.endif
        ; Conditional branch: (opc & $1F) == $10
        lda rp_opc
        and #$1F
        cmp #$10
        bne @linear

        ; Branch: taken = brk_pc + 2 + rel, not-taken = brk_pc + 2
        ldy #1
        lda (ptr2),y            ; signed relative
        bpl @br_pos
        clc
        adc _brk_pc
        sta rp_next_lo
        lda _brk_pc+1
        adc #$FF
        sta rp_next_lo+1
        jmp @br_add2
@br_pos:
        clc
        adc _brk_pc
        sta rp_next_lo
        lda _brk_pc+1
        adc #0
        sta rp_next_lo+1
@br_add2:
        lda rp_next_lo
        clc
        adc #2
        sta rp_next_lo
        bcc :+
        inc rp_next_lo+1
:       ; not-taken = brk_pc + 2
        lda _brk_pc
        clc
        adc #2
        sta rp_next_hi
        lda _brk_pc+1
        adc #0
        sta rp_next_hi+1
        jmp @check_next

@linear:
        ; Linear: next = brk_pc + dasm_insn(brk_pc)
        lda _brk_pc
        ldx _brk_pc+1
        jsr _dasm_insn          ; returns len in A
        clc
        adc _brk_pc
        sta rp_next_lo
        lda #0
        adc _brk_pc+1
        sta rp_next_lo+1
        jmp @check_next

@jsr:   ; JSR abs
        lda rp_save2            ; is_next
        beq @jsr_into
        ; step over: next = brk_pc + 3
        lda _brk_pc
        clc
        adc #3
        sta rp_next_lo
        lda _brk_pc+1
        adc #0
        sta rp_next_lo+1
        jmp @check_next
@jsr_into:
        ; step into: next = *(brk_pc+1)
        ldy #1
        lda (ptr2),y
        sta rp_next_lo
        iny
        lda (ptr2),y
        sta rp_next_lo+1
        jmp @check_next

@jmp_abs:
        ; JMP abs: next = *(brk_pc+1)
        ldy #1
        lda (ptr2),y
        sta rp_next_lo
        iny
        lda (ptr2),y
        sta rp_next_lo+1
        jmp @check_next

@jmp_ind:
        ; JMP (ind): next = **(brk_pc+1)
        ldy #1
        lda (ptr2),y
        sta ptr1
        iny
        lda (ptr2),y
        sta ptr1+1
        ldy #0
        lda (ptr1),y
        sta rp_next_lo
        iny
        lda (ptr1),y
        sta rp_next_lo+1
        jmp @check_next

@stop:  ; BRK / RTS / RTI — stop before executing
        jmp @normal_end

@check_next:
        ; if next_lo == 0, stop
        lda rp_next_lo
        ora rp_next_lo+1
        beq @normal_end

        ; Arm step BRKs
        jsr _dbg_step_clear
        lda rp_next_lo
        sta _step_bp
        lda rp_next_lo+1
        sta _step_bp+1
        lda #0
        sta _step_bp+2          ; saved byte (cleared)
        lda #1
        sta _step_bp+3          ; enabled

        ; second target if present
        lda rp_next_hi
        ora rp_next_hi+1
        beq @enter
        lda rp_next_hi
        sta _step_bp+4
        lda rp_next_hi+1
        sta _step_bp+5
        lda #0
        sta _step_bp+6
        lda #1
        sta _step_bp+7

@enter: jsr _dbg_enter

        ; Check for NMI, breakpoint hit, or RTS completion
        lda _dbg_reason
        beq @normal_end         ; 0 = user code returned via RTS
        cmp #2
        beq @interrupted
        lda _dbg_bp_hit
        cmp #$FF
        bne @interrupted

        ; Decrement count, continue
        lda rp_cnt
        sec
        sbc #1
        sta rp_cnt
        jcs @loop
        dec rp_cnt+1
        jmp @loop

@interrupted:
        jsr _dbg_step_clear
        jsr @re_enable_bp
        jmp show_break_result

@normal_end:
        jsr _dbg_step_clear
        jsr @re_enable_bp
        jsr show_break_result
        ; RTS/RTI: clear last_cmd so RETURN doesn't repeat
        lda rp_opc
        cmp #$60
        beq @clr_last
        cmp #$40
        bne @step_rts
@clr_last:
        lda #0
        sta last_cmd
@step_rts:
        rts

; Re-enable the bp that was temporarily disabled at loop start
@re_enable_bp:
        ldx rp_dis_bp
        cpx #$FF
        beq @re_rts             ; nothing was disabled
        lda #1
        sta _bp_table+3,x       ; restore enabled flag
@re_rts:
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_brk — 'b' command: breakpoints
;   ptr1 = args
; ═══════════════════════════════════════════════════════════
.proc cmd_brk
        jsr skip_sp_ptr1

        ldy #0
        lda (ptr1),y
        bne @not_empty

        ; b — list all breakpoints
        jsr _newline
        ldx #0                  ; slot index
@list:  cpx #8
        bcs @list_done
        stx rp_save
        lda #<bp_pfx
        ldx #>bp_pfx
        jsr _io_puts
        ldx rp_save
        txa
        clc
        adc #'1'
        jsr _io_putc
        lda #<str_colon_sp
        ldx #>str_colon_sp
        jsr _io_puts
        ; bp_table[slot*4].addr
        ldx rp_save
        txa
        asl
        asl
        tay
        lda _bp_table,y
        sta rp_addr
        lda _bp_table+1,y
        sta rp_addr+1
        ora rp_addr
        beq @empty_slot
        lda #'$'
        jsr _io_putc
        lda rp_addr
        ldx rp_addr+1
        jsr _io_puthex4
        jmp @slot_done
@empty_slot:
        lda #<str_dashes
        ldx #>str_dashes
        jsr _io_puts
@slot_done:
        jsr _io_clear_eol
        jsr _newline
        ldx rp_save
        inx
        jmp @list
@list_done:
        jmp _io_clear_eol

@not_empty:
        cmp #'*'
        bne @not_star
        ; b * — delete all
        jsr _dbg_bp_clear
        jsr _newline
        lda #<str_bp_clr
        ldx #>str_bp_clr
        jsr _io_puts
        jsr _io_clear_eol
        jmp nl_clear

@not_star:
        cmp #'-'
        bne @set_bp
        ; b -N — delete
        ldy #1
        lda (ptr1),y
        cmp #'1'
        bcc @bad_slot
        cmp #'9'
        bcs @bad_slot
        sec
        sbc #'1'
        jsr _dbg_bp_del
        jsr _newline
        lda #<bp_pfx
        ldx #>bp_pfx
        jsr _io_puts
        ldy #1
        lda (ptr1),y
        jsr _io_putc
        lda #<str_deleted
        ldx #>str_deleted
        jsr _io_puts
        jsr _io_clear_eol
        jmp nl_clear

@bad_slot:
        lda #<str_slot18
        ldx #>str_slot18
        jsr err_msg
        jmp nl_clear

@set_bp:
        ; b ADDR — set breakpoint
        jsr try_expr
        bcc @err_b
        ; result in expr_val
        lda expr_val
        ldx expr_val+1
        jsr _dbg_bp_set         ; returns slot in A ($FF=full)
        cmp #$FF
        beq @full
        ; success
        pha
        jsr _newline
        lda #<bp_pfx
        ldx #>bp_pfx
        jsr _io_puts
        pla
        clc
        adc #'1'
        jsr _io_putc
        lda #<str_colon_sp
        ldx #>str_colon_sp
        jsr _io_puts
        lda #'$'
        jsr _io_putc
        lda expr_val
        ldx expr_val+1
        jsr _io_puthex4
        jsr _io_clear_eol
        jmp nl_clear

@full:  jsr _newline
        lda #<str_bp_full
        ldx #>str_bp_full
        jsr _io_puts
        jsr _io_clear_eol
        jmp nl_clear

@err_b: lda #<str_err_b
        ldx #>str_err_b
        jsr err_msg
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; parse_regval — skip 2 chars (label:), parse 2 hex at ptr1
;   Advances ptr1 by 4. Returns byte in A.
; ═══════════════════════════════════════════════════════════
.proc parse_regval
        lda ptr1
        clc
        adc #2
        sta ptr1
        bcc :+
        inc ptr1+1
:       jmp parse_hex2_ptr1
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_reg — 'r' command
;   ptr1 = args
; ═══════════════════════════════════════════════════════════
.proc cmd_reg
        jsr skip_sp_ptr1
        ldy #0
        lda (ptr1),y
        beq @show

        ; Parse: a:XX x:XX y:XX s:XX flags
        jsr parse_regval
        sta _reg_a
        jsr skip_sp_ptr1
        jsr parse_regval
        sta _reg_x
        jsr skip_sp_ptr1
        jsr parse_regval
        sta _reg_y
        jsr skip_sp_ptr1
        jsr parse_regval
        sta _reg_sp
        jsr skip_sp_ptr1

        ; Parse flags: 8 chars, set bit if matches flag_ch[i]
        lda #0
        sta tmp2                ; p accumulator
        ldx #0
@pflag: cpx #8
        bcs @pflags_done
        asl tmp2                ; shift left to make room
        ldy #0
        lda (ptr1),y
        cmp flag_ch,x
        bne @pnot
        lda tmp2
        ora #1
        sta tmp2
@pnot:  ; advance ptr1 if not NUL
        ldy #0
        lda (ptr1),y
        beq @pskip
        inc ptr1
        bne @pskip
        inc ptr1+1
@pskip: inx
        jmp @pflag
@pflags_done:
        lda tmp2
        sta _reg_p

@show:  jsr _newline
        jsr emit_reg
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; is_seq_file — check if name ends with ",s" or ",S"
;   ptr1 = name pointer. Returns A=1 if seq, A=0 if not.
; ═══════════════════════════════════════════════════════════
.proc is_seq_file
        ; find length
        ldy #0
@len:   lda (ptr1),y
        beq @got_len
        iny
        bne @len
@got_len:
        ; need at least 2 chars
        cpy #2
        bcc @no
        dey
        lda (ptr1),y            ; last char
        cmp #'s'
        beq @chk_comma
        cmp #$D3                ; PETSCII uppercase S
        bne @no
@chk_comma:
        dey
        lda (ptr1),y
        cmp #','
        bne @no
        lda #1
        rts
@no:    lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_filename — parse quoted or space-delimited name
;   ptr1 = input. Returns: ptr2 = name, ptr1 advanced.
;   A=0 if no name (error). A=1 if name found.
; ═══════════════════════════════════════════════════════════
.proc parse_filename
        jsr skip_sp_ptr1

        ldy #0
        lda (ptr1),y
        cmp #$22                ; quote char
        bne @unquoted

        ; quoted: skip opening quote
        inc ptr1
        bne :+
        inc ptr1+1
:       lda ptr1
        sta ptr2
        lda ptr1+1
        sta ptr2+1
        ; scan for closing quote or NUL
        ldy #0
@qscan: lda (ptr1),y
        beq @qdone
        cmp #$22
        beq @qclose
        iny
        bne @qscan
@qclose:
        ; NUL-terminate in place: store 0 at closing quote
        lda #0
        sta (ptr1),y
        ; advance ptr1 past closing quote
        iny
        tya
        clc
        adc ptr1
        sta ptr1
        bcc @qdone
        inc ptr1+1
@qdone: jsr skip_sp_ptr1
        jmp @check_empty

@unquoted:
        lda ptr1
        sta ptr2
        lda ptr1+1
        sta ptr2+1
        ; scan for space or NUL
        ldy #0
@uscan: lda (ptr1),y
        beq @udone
        cmp #' '
        beq @uclose
        iny
        bne @uscan
@uclose:
        ; NUL-terminate
        lda #0
        sta (ptr1),y
        iny
        tya
        clc
        adc ptr1
        sta ptr1
        bcc :+
        inc ptr1+1
:       jsr skip_sp_ptr1
        jmp @check_empty

@udone: ; ptr1 already at NUL, which is fine
        tya
        clc
        adc ptr1
        sta ptr1
        bcc @check_empty
        inc ptr1+1

@check_empty:
        ; check if name is empty
        ldy #0
        lda (ptr2),y
        beq @fail
        lda #1
        rts
@fail:  lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; get_filename — parse and remember filename
;   ptr1 = input. Returns: ptr2 = name, A=0 if no name.
;   Copies to _cur_filename if new name found.
; ═══════════════════════════════════════════════════════════
.proc get_filename
        jsr parse_filename
        bne @got_name

        ; no name in args — try cur_filename
        lda _cur_filename
        beq @fail
        lda #<_cur_filename
        sta ptr2
        lda #>_cur_filename
        sta ptr2+1
        lda #1
        rts

@got_name:
        ; copy name to cur_filename (ptr2 = source)
        ldy #0
@copy:  lda (ptr2),y
        sta _cur_filename,y
        beq @copy_done
        iny
        cpy #FILENAME_MAX
        bcc @copy
        ; max reached, NUL-terminate
        lda #0
        sta _cur_filename,y
@copy_done:
        lda #1
        rts

@fail:  lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; io_quoted_name — print '; "name": '
;   ptr2 = name
; ═══════════════════════════════════════════════════════════
.proc io_quoted_name
        lda #<str_semi_q
        ldx #>str_semi_q
        jsr _io_puts
        lda ptr2
        ldx ptr2+1
        jsr _io_puts
        lda #<str_qcolon
        ldx #>str_qcolon
        jmp _io_puts
.endproc

; ═══════════════════════════════════════════════════════════
; print_seq_stats — print "name: N lines, M bytes"
;   ptr2 = name
; ═══════════════════════════════════════════════════════════
.proc print_seq_stats
        jsr io_quoted_name
        lda _ed_save_lines
        ldx _ed_save_lines+1
        jsr _io_putdec
        lda #<str_lines
        ldx #>str_lines
        jsr _io_puts
        lda _ed_save_bytes
        ldx _ed_save_bytes+1
        jsr _io_putdec
        lda #<str_bytes
        ldx #>str_bytes
        jmp _io_puts
.endproc

; ═══════════════════════════════════════════════════════════
; io_err_load / io_err_save — print error with name
;   ptr2 = name
; ═══════════════════════════════════════════════════════════
io_err_load:
        lda #<str_err_load
        ldx #>str_err_load
        jsr _io_puts
        lda ptr2
        ldx ptr2+1
        jmp _io_puts

io_err_save:
        lda #<str_err_save
        ldx #>str_err_save
        jsr _io_puts
        lda ptr2
        ldx ptr2+1
        jmp _io_puts

; ───────────────────────────────────────────────────────────
; restore_name_ptr — reload ptr2 from saved name pointer
; ───────────────────────────────────────────────────────────
restore_name_ptr:
        lda rp_next_lo
        sta ptr2
        lda rp_next_lo+1
        sta ptr2+1
        rts

; ═══════════════════════════════════════════════════════════
; disk_done — clear_eol, newline, floppy_status, nl_clear
; ═══════════════════════════════════════════════════════════
disk_done:
        jsr _io_clear_eol
        jsr _newline
        jsr _floppy_status
        jsr _io_clear_eol
        jmp nl_clear

; ═══════════════════════════════════════════════════════════
; cmd_load — 'l' command
;   ptr1 = args
; ═══════════════════════════════════════════════════════════
.proc cmd_load
        lda _cur_addr
        sta rp_addr
        lda _cur_addr+1
        sta rp_addr+1

        jsr get_filename
        bne @have_name
        lda #<str_err_name
        ldx #>str_err_name
        jsr err_msg
        jmp nl_clear

@have_name:
        ; ptr2 = name
        jsr _newline

        ; save ptr2 (name) since calls will clobber it
        lda ptr2
        sta rp_next_lo          ; borrow for name ptr save
        lda ptr2+1
        sta rp_next_lo+1

        ; check seq file
        lda ptr2
        sta ptr1
        lda ptr2+1
        sta ptr1+1
        jsr is_seq_file
        cmp #1
        bne @load_prg

        ; SEQ: guard unsaved before overwriting source
        jsr check_unsaved
        bcc @l_cancel

        ; SEQ: ed_load_source(name)
        lda rp_next_lo
        ldx rp_next_lo+1
        jsr _ed_load_source     ; A=error
        cmp #0
        beq @seq_ok
        ; error
        jsr restore_name_ptr
        jsr io_err_load
        jmp @done
@seq_ok:
        jsr restore_name_ptr
        jsr print_seq_stats
        jmp @done

@load_prg:
        ; PRG: disk_load_prg(name, addr) — push name, A/X=addr
        lda rp_next_lo
        ldx rp_next_lo+1
        jsr pushax              ; push name
        lda rp_addr
        ldx rp_addr+1
        jsr _disk_load_prg      ; A/X = result (0=error, else bytes)
        sta rp_cnt              ; save result lo
        stx rp_cnt+1            ; save result hi
        ora rp_cnt+1
        bne @prg_ok
        ; error
        jsr restore_name_ptr
        jsr io_err_load
        jmp @done

@prg_ok:
        jsr restore_name_ptr
        jsr io_quoted_name
        lda rp_cnt
        ldx rp_cnt+1
        jsr _io_putdec
        lda #<str_bytes_at
        ldx #>str_bytes_at
        jsr _io_puts
        ; print address: if addr was 0, print result, else print addr
        lda rp_addr
        ora rp_addr+1
        bne @use_addr
        lda rp_cnt
        ldx rp_cnt+1
        jmp @print_addr
@use_addr:
        lda rp_addr
        ldx rp_addr+1
@print_addr:
        jsr _io_puthex4

@l_cancel:
        jmp nl_clear
@done:  jmp disk_done
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_write — 's' command (save/write)
;   ptr1 = args
; ═══════════════════════════════════════════════════════════
.proc cmd_write
        lda _cur_addr
        sta rp_addr
        lda _cur_addr+1
        sta rp_addr+1

        jsr get_filename
        bne @have_name
        lda #<str_err_name
        ldx #>str_err_name
        jsr err_msg
        jmp nl_clear

@have_name:
        jsr _newline

        ; save name ptr
        lda ptr2
        sta rp_next_lo
        lda ptr2+1
        sta rp_next_lo+1

        ; check seq file
        lda ptr2
        sta ptr1
        lda ptr2+1
        sta ptr1+1
        jsr is_seq_file
        cmp #1
        bne @save_prg

        ; SEQ: ed_ensure_init, ed_save_source(name)
        jsr _ed_ensure_init
        lda rp_next_lo
        ldx rp_next_lo+1
        jsr _ed_save_source     ; A=error
        cmp #0
        beq @seq_ok
        jsr restore_name_ptr
        jsr io_err_save
        jmp @done
@seq_ok:
        jsr restore_name_ptr
        jsr print_seq_stats
        jmp @done

@save_prg:
        ; PRG: parse optional end address
        ; ptr1 still points into line_buf after get_filename
        jsr skip_sp_ptr1
        ldy #0
        lda (ptr1),y
        beq @no_end_arg
        cmp #';'
        beq @no_end_arg

        ; has_arg = true, parse end via try_expr
        lda #1
        sta rp_save             ; has_arg flag
        jsr try_expr
        bcs @got_end
        ; error from try_expr already printed
        jmp nl_clear
@got_end:
        lda expr_val
        sta rp_cnt              ; end lo
        lda expr_val+1
        sta rp_cnt+1            ; end hi
        jmp @check_end

@no_end_arg:
        lda #0
        sta rp_save             ; has_arg = false
        ; end = 0 initially
        sta rp_cnt
        sta rp_cnt+1

@check_end:
        ; if end == 0, end = addr + block_size
        lda rp_cnt
        ora rp_cnt+1
        bne @have_end
        lda rp_addr
        clc
        adc block_size
        sta rp_cnt
        lda rp_addr+1
        adc block_size+1
        sta rp_cnt+1
@have_end:
        ; if end <= addr, error
        lda rp_cnt+1
        cmp rp_addr+1
        jcc @range_err
        bne @end_ok
        lda rp_cnt
        cmp rp_addr
        jeq @range_err
        jcc @range_err
@end_ok:
        ; size = end - addr
        lda rp_cnt
        sec
        sbc rp_addr
        sta rp_next_hi          ; size lo (borrow rp_next_hi)
        lda rp_cnt+1
        sbc rp_addr+1
        sta rp_next_hi+1        ; size hi

        ; disk_save_prg(name, addr, size) — push name, push addr, A/X=size
        lda rp_next_lo
        ldx rp_next_lo+1
        jsr pushax              ; push name
        lda rp_addr
        ldx rp_addr+1
        jsr pushax              ; push addr
        lda rp_next_hi
        ldx rp_next_hi+1
        jsr _disk_save_prg      ; A=error
        cmp #0
        beq @prg_ok

        ; error
        jsr restore_name_ptr
        jsr io_err_save
        jmp @done

@prg_ok:
        jsr restore_name_ptr
        jsr io_quoted_name
        lda rp_next_hi
        ldx rp_next_hi+1
        jsr _io_putdec
        lda #<str_bytes_sp
        ldx #>str_bytes_sp
        jsr _io_puts
        lda rp_addr
        ldx rp_addr+1
        jsr _io_puthex4
        lda #'-'
        jsr _io_putc
        ; end - 1 → A=lo, X=hi for _io_puthex4
        lda rp_cnt
        sec
        sbc #1
        pha
        lda rp_cnt+1
        sbc #0
        tax
        pla
        jsr _io_puthex4
        jmp @done

@range_err:
        lda #<str_err_range
        ldx #>str_err_range
        jsr err_msg
        jmp nl_clear

@done:  jmp disk_done
.endproc

; ═══════════════════════════════════════════════════════════
; info_line — print ";tag  AAAA-BBBB description"
;   Stack frame: rp_save2 = inv flag
;   ptr2 = tag string, rp_addr = lo, rp_cnt = hi
;   ptr1 = desc string
;   (Caller sets these before calling)
;
;   Actually, to simplify, pass:
;     A = inv flag
;     Store tag addr, lo, hi, desc in BSS before calling.
; We use a register-based interface:
;   Call setup: rp_save2=inv, rp_addr=lo, rp_cnt=hi
;               ptr2=tag, ptr1=desc
; ═══════════════════════════════════════════════════════════
.proc info_line
        ; rp_save2 = inv, ptr2 = tag, rp_addr = lo, rp_cnt = hi, ptr1 = desc
        ; save io_cy screen addr into rp_next_lo for invert pass later
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_next_lo
        lda scr_hi,x
        sta rp_next_lo+1

        lda #0
        sta CUR_COL
        lda #';'
        jsr _io_putc

        ; print tag
        lda ptr2
        ldx ptr2+1
        jsr _io_puts

        ; pad tag to 4 chars: compute strlen of tag
        ; (tag is always 2-4 chars, pad with spaces)
        ldy #0
@tlen:  lda (ptr2),y
        beq @tpad
        iny
        cpy #4
        bcc @tlen
@tpad:  ; pad with spaces until we've printed 4 chars total
        cpy #4
        bcs @tsp
        lda #' '
        sty tmp1
        jsr _io_putc
        ldy tmp1
        iny
        bne @tpad
@tsp:   lda #' '
        jsr _io_putc

        ; print lo-hi
        lda rp_addr
        ldx rp_addr+1
        jsr _io_puthex4
        lda #'-'
        jsr _io_putc
        lda rp_cnt
        ldx rp_cnt+1
        jsr _io_puthex4
        lda #' '
        jsr _io_putc

        ; print desc
        lda ptr1
        ldx ptr1+1
        jsr _io_puts

        ; save col position
        lda CUR_COL
        sta rp_save             ; col

        ; copy screen pointer to ZP ptr1 for indirect access
        lda rp_next_lo
        sta ptr1
        lda rp_next_lo+1
        sta ptr1+1

        ; inv or normal pad
        lda rp_save2
        beq @normal_pad

        ; inv: set bit 7 on all chars from 0..col-1
        ldy #0
@inv_lp:
        cpy rp_save
        bcs @inv_pad
        lda (ptr1),y
        ora #$80
        sta (ptr1),y
        iny
        bne @inv_lp
@inv_pad:
        ; fill rest with $A0 (reverse space)
        cpy #SCREEN_WIDTH
        bcs @done
        lda #$A0
        sta (ptr1),y
        iny
        bne @inv_pad

@normal_pad:
        ; fill rest with $20 (space)
        ldy rp_save
@npad:  cpy #SCREEN_WIDTH
        bcs @done
        lda #$20
        sta (ptr1),y
        iny
        bne @npad

@done:  jmp _newline
.endproc

; ═══════════════════════════════════════════════════════════
; ===============================================================
; free_line -- print "N bytes free" info line with inv=1
;   rp_addr = lo, rp_cnt = hi (address range)
; ===============================================================
free_line:
        ; Compute size = hi - lo + 1 into rp_opc/rp_save (tmp)
        lda rp_cnt
        sec
        sbc rp_addr
        sta rp_opc
        lda rp_cnt+1
        sbc rp_addr+1
        sta rp_save
        inc rp_opc
        bne :+
        inc rp_save
:
        ; Save lo/hi, set rp_addr = size for utoa_sub
        lda rp_addr
        pha
        lda rp_addr+1
        pha
        lda rp_opc
        sta rp_addr
        lda rp_save
        sta rp_addr+1

        jsr utoa_sub            ; decimal to fbuf, returns len in A

        ; Append " bytes free" to fbuf
        tax
        ldy #0
@cpfree:lda str_bytes_free,y
        sta fbuf,x
        beq @cpf_done
        inx
        iny
        bne @cpfree
@cpf_done:

        ; Restore lo into rp_addr (hi stays in rp_cnt)
        pla
        sta rp_addr+1
        pla
        sta rp_addr

        ; info_line: inv=1, tag="work", desc=fbuf
        lda #1
        sta rp_save2
        lda #<str_tag_work
        sta ptr2
        lda #>str_tag_work
        sta ptr2+1
        lda #<fbuf
        sta ptr1
        lda #>fbuf
        sta ptr1+1
        jmp info_line

; ═══════════════════════════════════════════════════════════
; cmd_info — 'i' command: memory map
; ═══════════════════════════════════════════════════════════
; Helper: set up and call info_line
;   Macro-like pattern: set rp_save2, ptr2, rp_addr, rp_cnt, ptr1
;   then jsr info_line.
; We define a helper that takes parameters from a "call frame" pattern.

; ───────────────────────────────────────────────────────────
; info_emit_rows — emit N rows from info table
;   A/X = table ptr, Y = row count
;   Each row: tag(2), lo(2), hi(2), desc(2) = 8 bytes
; ───────────────────────────────────────────────────────────
.proc info_emit_rows
        sta rp_next_hi
        stx rp_next_hi+1
        sty rp_opc              ; row counter
@lp:    lda rp_next_hi
        sta ptr1
        lda rp_next_hi+1
        sta ptr1+1
        ldy #0
        lda (ptr1),y
        sta ptr2
        iny
        lda (ptr1),y
        sta ptr2+1
        iny
        lda (ptr1),y
        sta rp_addr
        iny
        lda (ptr1),y
        sta rp_addr+1
        iny
        lda (ptr1),y
        sta rp_cnt
        iny
        lda (ptr1),y
        sta rp_cnt+1
        iny
        lda (ptr1),y
        pha
        iny
        lda (ptr1),y
        sta tmp2
        lda rp_next_hi
        clc
        adc #8
        sta rp_next_hi
        bcc :+
        inc rp_next_hi+1
:       pla
        sta ptr1
        lda tmp2
        sta ptr1+1
        lda #0
        sta rp_save2
        jsr info_line
        dec rp_opc
        bne @lp
        rts
.endproc

.proc cmd_info
        jsr _newline

        ; ── Head: cpu ──
        lda #<info_tbl
        ldx #>info_tbl
        ldy #INFO_TBL_ROWS
        jsr info_emit_rows

        ; ── Dynamic: zp 0002-XX cse (saved on j) ──
        lda #0
        sta rp_save2
        lda #<str_tag_zp
        sta ptr2
        lda #>str_tag_zp
        sta ptr2+1
        lda #$02
        sta rp_addr
        lda #$00
        sta rp_addr+1
        jsr _cse_zp_end
        sec
        sbc #1
        sta rp_cnt
        lda #$00
        sta rp_cnt+1
        lda #<str_zp_saved
        sta ptr1
        lda #>str_zp_saved
        sta ptr1+1
        jsr info_line

        ; free_line(cse_zp_end, $007f)
        jsr _cse_zp_end
        sta rp_addr
        lda #$00
        sta rp_addr+1
        lda #$7F
        sta rp_cnt
        lda #$00
        sta rp_cnt+1
        jsr free_line

        ; ── Mid: zp(kernal), stk, sys, scr ──
        lda #<info_tbl_mid
        ldx #>info_tbl_mid
        ldy #INFO_TBL_MID_ROWS
        jsr info_emit_rows

        ; ── Dynamic: cse code+data+bss ──
        lda #0
        sta rp_save2
        lda #<str_tag_cse
        sta ptr2
        lda #>str_tag_cse
        sta ptr2+1
        jsr _cse_start
        sta rp_addr
        stx rp_addr+1
        jsr _cse_end
        sec
        sbc #1
        sta rp_cnt
        txa
        sbc #0
        sta rp_cnt+1
        lda #<str_code_data
        sta ptr1
        lda #>str_code_data
        sta ptr1+1
        jsr info_line

        ; ── Dynamic: free region ──
        jsr _cse_end
        sta rp_addr
        stx rp_addr+1
        lda #$FF
        sta rp_cnt
        lda #$C7
        sta rp_cnt+1
        lda _src_bot
        ora _src_bot+1
        beq @no_src_adj
        lda _src_bot
        sec
        sbc #1
        sta rp_cnt
        lda _src_bot+1
        sbc #0
        sta rp_cnt+1
@no_src_adj:
        lda rp_addr+1
        cmp rp_cnt+1
        bcc @show_free
        bne @skip_free
        lda rp_addr
        cmp rp_cnt
        beq @show_free
        bcs @skip_free
@show_free:
        jsr free_line
@skip_free:

        ; ── Dynamic: source ──
        lda _src_bot
        ora _src_bot+1
        beq @no_src
        lda #0
        sta rp_save2
        lda #<str_tag_src
        sta ptr2
        lda #>str_tag_src
        sta ptr2+1
        lda _src_bot
        sta rp_addr
        lda _src_bot+1
        sta rp_addr+1
        lda _src_top
        sec
        sbc #1
        sta rp_cnt
        lda _src_top+1
        sbc #0
        sta rp_cnt+1
        lda #<str_source
        sta ptr1
        lda #>str_source
        sta ptr1+1
        jsr info_line
@no_src:

        ; ── Tail: cstk, io, kern ──
        lda #<info_tbl_tail
        ldx #>info_tbl_tail
        ldy #INFO_TBL_TAIL_ROWS
        jsr info_emit_rows

        jmp _io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; _exec_line — parse line_buf and execute command
; ═══════════════════════════════════════════════════════════
.proc _exec_line
        lda #<line_buf
        sta ptr1
        lda #>line_buf
        sta ptr1+1

        jsr skip_sp_ptr1

        ; ── Parse optional AAAA: prefix → sets cur_addr ──
        ldy #0
        jsr is_hex_at_ptr1
        beq @no_prefix
        ldy #1
        jsr is_hex_at_ptr1
        beq @no_prefix
        ldy #2
        jsr is_hex_at_ptr1
        beq @no_prefix
        ldy #3
        jsr is_hex_at_ptr1
        beq @no_prefix
        ldy #4
        lda (ptr1),y
        cmp #':'
        bne @no_prefix
        ; parse 4 hex digits
        jsr parse_hex4_ptr1
        sta _cur_addr
        stx _cur_addr+1
        ; skip ':'
        inc ptr1
        bne :+
        inc ptr1+1
:
@no_prefix:
        jsr skip_sp_ptr1

        ; read command char
        ldy #0
        lda (ptr1),y
        sta rp_opc              ; save cmd char

        ; ── Empty / semicolon ──
        beq @empty
        cmp #';'
        beq @semicolon
        jmp @have_cmd

@empty:
        ; empty line: if last_cmd, repeat it
        lda last_cmd
        beq @clear_last
        sta rp_opc              ; cmd = last_cmd
        ; ptr1 = "" (empty args)
        ; show "ADDR:cmd" header
        lda _cur_addr
        sta rp_addr
        lda _cur_addr+1
        sta rp_addr+1
        lda rp_opc
        jsr io_addr_cmd
        jsr _io_clear_eol
        jmp @dispatch

@semicolon:
@clear_last:
        lda #0
        sta last_cmd
        jmp nl_clear

@have_cmd:
        ; skip command letter
        inc ptr1
        bne :+
        inc ptr1+1
:       ; skip optional space after command
        ldy #0
        lda (ptr1),y
        cmp #' '
        bne @save_repeat
        inc ptr1
        bne @save_repeat
        inc ptr1+1

@save_repeat:
        ; save for repeat (paging + step commands)
        lda rp_opc
        cmp #'m'
        beq @set_repeat
        cmp #'d'
        beq @set_repeat
        cmp #'.'
        beq @set_repeat
        cmp #'t'
        beq @set_repeat
        cmp #'o'
        beq @set_repeat
        jmp @dispatch
@set_repeat:
        sta last_cmd

@dispatch:
        ; ── Dispatch ──
        lda rp_opc

        cmp #'.'
        bne @n_dot
        jmp cmd_dot
@n_dot:
        cmp #'d'
        bne @n_d
        jmp cmd_disasm
@n_d:
        cmp #'m'
        bne @n_m
        jmp cmd_mem
@n_m:
        ; @ — set address
        cmp #'@'
        bne @n_at
        jsr try_expr
        bcc @at_done
        lda expr_val
        sta _cur_addr
        lda expr_val+1
        sta _cur_addr+1
@at_done:
        jmp nl_clear
@n_at:
        ; + — advance address
        cmp #'+'
        bne @n_plus
        jsr try_expr
        bcc @plus_def
        lda expr_val
        ora expr_val+1
        bne @plus_use
@plus_def:
        lda block_size
        sta expr_val
        lda block_size+1
        sta expr_val+1
@plus_use:
        lda _cur_addr
        clc
        adc expr_val
        sta _cur_addr
        lda _cur_addr+1
        adc expr_val+1
        sta _cur_addr+1
        jmp nl_clear
@n_plus:
        ; - — retreat address
        cmp #'-'
        bne @n_minus
        jsr try_expr
        bcc @minus_def
        lda expr_val
        ora expr_val+1
        bne @minus_use
@minus_def:
        lda block_size
        sta expr_val
        lda block_size+1
        sta expr_val+1
@minus_use:
        lda _cur_addr
        sec
        sbc expr_val
        sta _cur_addr
        lda _cur_addr+1
        sbc expr_val+1
        sta _cur_addr+1
        jmp nl_clear
@n_minus:
        ; j — jump/execute
        cmp #'j'
        bne @n_j
        jsr try_expr
        bcc @j_no_addr
        lda expr_val
        sta _cur_addr
        lda expr_val+1
        sta _cur_addr+1
@j_no_addr:
        jmp cmd_jmp
@n_j:
        ; g — go (sym_lookup "main")
        cmp #'g'
        bne @n_g
        ; sym_lookup("main") — ZP interface
        lda #<str_main
        sta sym_name
        lda #>str_main
        sta sym_name+1
        jsr _sym_lookup         ; C=0 found, result in sym_val
        bcs @g_no_main
        lda sym_val
        sta _cur_addr
        lda sym_val+1
        sta _cur_addr+1
@g_no_main:
        jmp cmd_jmp
@n_g:
        ; t — step
        cmp #'t'
        bne @n_t
        lda #0                  ; is_next = 0
        jmp cmd_step
@n_t:
        ; o — step over
        cmp #'o'
        bne @n_o
        lda #1                  ; is_next = 1
        jmp cmd_step
@n_o:
        ; b — breakpoints
        cmp #'b'
        bne @n_b
        jmp cmd_brk
@n_b:
        ; r — registers
        cmp #'r'
        bne @n_r
        jmp cmd_reg
@n_r:
        ; l — load
        cmp #'l'
        bne @n_l
        jmp cmd_load
@n_l:
        ; s — save/write
        cmp #'s'
        bne @n_s
        jmp cmd_write
@n_s:
        ; k — delete source (guard unsaved)
        cmp #'k'
        bne @n_k
        jsr check_unsaved
        bcc @k_cancel
        jsr _newline
        lda #<str_del_src
        ldx #>str_del_src
        jsr _io_puts
        jsr _io_getc
        cmp #'y'
        bne @k_no
        jsr _ed_new
        lda #<str_ok
        ldx #>str_ok
        jsr _io_puts
@k_no:  jsr _io_clear_eol
@k_cancel:
        jmp nl_clear
@n_k:
        ; i — info
        cmp #'i'
        bne @n_i
        jmp cmd_info
@n_i:
        ; B (PETSCII $C2) — block size
        cmp #$C2
        bne @n_B
        jsr try_expr
        bcc @B_show             ; empty or error → just show
        ; if non-zero, set block_size
        lda expr_val
        ora expr_val+1
        beq @B_show
        lda expr_val
        sta block_size
        lda expr_val+1
        sta block_size+1
@B_show:
        jsr _newline
        lda #<str_B_eq
        ldx #>str_B_eq
        jsr _io_puts
        lda block_size
        ldx block_size+1
        jsr _io_puthex4
        jsr _io_clear_eol
        jmp nl_clear
@n_B:
        ; T (PETSCII $D4) — tab width
        cmp #$D4
        bne @n_T
        jsr try_expr
        bcc @T_show             ; empty or error → just show
        lda expr_val
        cmp #33                 ; <= 32
        bcs @T_show
        cmp _tab_width
        beq @T_show
        sta _tab_width
@T_show:
        jsr _newline
        lda #<str_T_eq
        ldx #>str_T_eq
        jsr _io_puts
        lda _tab_width
        jsr _io_puthex2
        jsr _io_clear_eol
        jmp nl_clear
@n_T:
        ; C (PETSCII $C3) — color
        cmp #$C3
        jne @n_C
        jsr skip_sp_ptr1
        ldy #0
        jsr is_hex_at_ptr1
        beq @C_show
        ; check how many hex digits
        ldy #1
        jsr is_hex_at_ptr1
        beq @C_one
        ldy #2
        jsr is_hex_at_ptr1
        beq @C_two
        ; three digits: border bg fg
        ldy #0
        jsr hex_val_at_ptr1
        sta _theme_border
        ldy #1
        jsr hex_val_at_ptr1
        sta _theme_bg
        ldy #2
        jsr hex_val_at_ptr1
        sta _theme_fg
        jsr _restore_colors
        jmp @C_show
@C_two: ; two digits: bg fg
        ldy #0
        jsr hex_val_at_ptr1
        sta _theme_bg
        ldy #1
        jsr hex_val_at_ptr1
        sta _theme_fg
        jsr _restore_colors
        jmp @C_show
@C_one: ; one digit: fg only
        ldy #0
        jsr hex_val_at_ptr1
        sta _theme_fg
        jsr _restore_colors
@C_show:
        jsr _newline
        lda #<str_color
        ldx #>str_color
        jsr _io_puts
        lda _theme_border
        jsr _hex_val_to_char
        jsr _io_putc
        lda _theme_bg
        jsr _hex_val_to_char
        jsr _io_putc
        lda _theme_fg
        jsr _hex_val_to_char
        jsr _io_putc
        jsr _io_clear_eol
        jmp nl_clear
@n_C:
        ; u — cpu mode
        cmp #'u'
        jne @n_u
        jsr skip_sp_ptr1
        ldy #0
        lda (ptr1),y
        cmp #'6'
        bne @u_show
        ; check q[1..3] for cpu type
        ldy #1
        lda (ptr1),y
        cmp #'5'
        bne @u_show
        ldy #2
        lda (ptr1),y
        sta tmp1                ; save q[2]
        ldy #3
        lda (ptr1),y
        sta tmp2                ; save q[3]
        ; 6502: q[2]='0', q[3]='2'
        lda tmp1
        cmp #'0'
        bne @u_chk_10
        lda tmp2
        cmp #'2'
        bne @u_show
        ; v = 0 (6502)
        lda #0
        jmp @u_try_set
@u_chk_10:
        ; 6510: q[2]='1', q[3]='0'
        cmp #'1'
        bne @u_chk_c02
        lda tmp2
        cmp #'0'
        bne @u_show
        lda #1
        jmp @u_try_set
@u_chk_c02:
        ; 65c02: q[2]='c', q[3]='0'
        cmp #'c'
        bne @u_show
        lda tmp2
        cmp #'0'
        bne @u_show
        lda #2
@u_try_set:
        ; A = v; check v <= CPU_CEIL
.ifdef CMOS_SUPPORT
        ; CPU_CEIL=2: accept 0 or 2 only
        cmp #3
        bcs @u_show
        cmp #1
        beq @u_show
        sta _al_cpu
.elseif .defined(CPU_6510)
        ; CPU_CEIL=1: accept 0 or 1
        cmp #2
        bcs @u_show
        sta _al_cpu
.else
        ; CPU_CEIL=0: accept 0 only
        bne @u_show
        sta _al_cpu
.endif

@u_show:
        jsr _newline
        lda #<str_cpu
        ldx #>str_cpu
        jsr _io_puts
        lda _al_cpu
        bne @u_no_star0
        lda #'*'
        jmp @u_p0
@u_no_star0:
        lda #' '
@u_p0:  jsr _io_putc
.ifdef CPU_6510
        lda #<str_6510
        ldx #>str_6510
        jsr _io_puts
        lda _al_cpu
        cmp #1
        bne @u_no_star1
        lda #'*'
        jmp @u_p1
@u_no_star1:
        lda #' '
@u_p1:  jsr _io_putc
.endif
.ifdef CMOS_SUPPORT
        lda #<str_65c02
        ldx #>str_65c02
        jsr _io_puts
        lda _al_cpu
        cmp #2
        bne @u_no_star2
        lda #'*'
        jmp @u_p2
@u_no_star2:
        lda #' '
@u_p2:  jsr _io_putc
.endif
        jsr _io_clear_eol
        jmp nl_clear
@n_u:
        ; a — assemble source
        cmp #'a'
        bne @n_a
        jsr _newline
        lda #<str_asm_ing
        ldx #>str_asm_ing
        jsr _io_puts
        jsr _newline
        jsr _asm_assemble       ; A/X = error count
        sta rp_cnt
        stx rp_cnt+1
        ora rp_cnt+1
        bne @a_errors
        ; success
        lda #<str_ok_colon
        ldx #>str_ok_colon
        jsr _io_puts
        lda _asm_size
        ldx _asm_size+1
        jsr _io_putdec
        lda #<str_bytes_at
        ldx #>str_bytes_at
        jsr _io_puts
        lda _asm_org
        ldx _asm_org+1
        jsr _io_puthex4
        ; sym_lookup("main") — ZP interface
        lda #<str_main
        sta sym_name
        lda #>str_main
        sta sym_name+1
        jsr _sym_lookup         ; C=0 found, result in sym_val
        bcs @a_tail
        lda sym_val
        sta _cur_addr
        lda sym_val+1
        sta _cur_addr+1
@a_errors:
        lda #<str_semi
        ldx #>str_semi
        jsr _io_puts
        lda rp_cnt
        ldx rp_cnt+1
        jsr _io_putdec
        lda #<str_errors
        ldx #>str_errors
        jsr _io_puts
@a_tail:
        jsr _io_clear_eol
        jmp nl_clear
@n_a:
        ; ? — calculator
        cmp #'?'
        jne @n_q_mark
        ; set expr_ptr = ptr1
        lda ptr1
        sta expr_ptr
        lda ptr1+1
        sta expr_ptr+1
        jsr _expr_eval
        sta rp_save             ; rc
        cmp #2
        jcs @calc_err

        jsr _newline
        ; hex display
        lda #<str_semi
        ldx #>str_semi
        jsr _io_puts
        lda expr_val+1
        bne @calc_16bit
        lda expr_val
        beq @calc_16bit         ; show 0 as 16-bit style? No, 0 < 256.
        ; Actually: if val < 256, show "  $XX"
        ; if val == 0, it's < 256 so show "  $00"
        lda #' '
        jsr _io_putc
        lda #' '
        jsr _io_putc
        lda #'$'
        jsr _io_putc
        lda expr_val
        jsr _io_puthex2
        jmp @calc_dec
@calc_16bit:
        ; "$XXXX" (or $0000)
        lda expr_val+1
        bne @calc_16bit_real
        ; val is 0, show "  $00"
        lda #' '
        jsr _io_putc
        lda #' '
        jsr _io_putc
        lda #'$'
        jsr _io_putc
        lda expr_val
        jsr _io_puthex2
        jmp @calc_dec
@calc_16bit_real:
        lda #'$'
        jsr _io_putc
        lda expr_val
        ldx expr_val+1
        jsr _io_puthex4

@calc_dec:
        ; decimal: "  " then 5-digit space-padded
        lda #<str_2sp
        ldx #>str_2sp
        jsr _io_puts
        lda expr_val
        sta rp_addr
        lda expr_val+1
        sta rp_addr+1
        jsr put_dec5_sp

        ; 8-bit extras if val < 256
        lda expr_val+1
        jne @calc_done
        ; binary
        lda #<str_pct
        ldx #>str_pct
        jsr _io_puts
        lda expr_val
        sta tmp2
        ldx #0
@bin_lp:
        asl tmp2
        bcs @bin_1
        lda #'0'
        bne @bin_p
@bin_1: lda #'1'
@bin_p: stx tmp1
        jsr _io_putc
        ldx tmp1
        inx
        cpx #8
        bcc @bin_lp

        ; signed decimal: "  +/-NNN"
        lda #' '
        jsr _io_putc
        lda #' '
        jsr _io_putc
        lda expr_val
        bpl @sign_pos
        ; negative
        lda #'-'
        jsr _io_putc
        ; negate: av = 256 - val
        lda #0
        sec
        sbc expr_val
        jmp @print_signed
@sign_pos:
        lda #'+'
        jsr _io_putc
        lda expr_val
@print_signed:
        ; A = absolute value (0-128)
        sta tmp2                ; av
        ; hundreds
        lda tmp2
        cmp #100
        bcc @tens
        lda #0
        sta tmp1                ; digit
@hun_lp:
        lda tmp2
        sec
        sbc #100
        bcc @hun_done
        sta tmp2
        inc tmp1
        jmp @hun_lp
@hun_done:
        lda tmp1
        clc
        adc #'0'
        jsr _io_putc
@tens:  lda tmp2
        cmp #10
        bcc @ones
        lda #0
        sta tmp1
@ten_lp:
        lda tmp2
        sec
        sbc #10
        bcc @ten_done
        sta tmp2
        inc tmp1
        jmp @ten_lp
@ten_done:
        lda tmp1
        clc
        adc #'0'
        jsr _io_putc
@ones:  lda tmp2
        clc
        adc #'0'
        jsr _io_putc

@calc_done:
        jsr _io_clear_eol
        jmp nl_clear

@calc_err:
        jsr _newline
        lda #<str_err_expr
        ldx #>str_err_expr
        jsr _io_puts
        jsr _expr_error_str
        jsr _io_puts
        jsr _io_clear_eol
        jmp nl_clear
@n_q_mark:
        ; Q (PETSCII $D1) — quit (guard unsaved)
        cmp #$D1
        bne @n_q
        jsr check_unsaved
        bcc @q_cancel
        jsr _newline
        lda #<str_quit
        ldx #>str_quit
        jsr _io_puts
        ; flush keyboard buffer
@q_flush:
        jsr _io_kbhit
        cmp #0
        beq @q_wait
        jsr _io_getc
        jmp @q_flush
@q_wait:
        jsr _io_getc
        cmp #'y'
        bne @q_no
        lda #ST_STOP
        sta _state
@q_no:  jsr _newline
        lda _state
        cmp #ST_STOP
        beq @q_ret
        jsr _io_clear_eol
@q_ret: rts
@q_cancel:
        jmp nl_clear
@n_q:
        ; $ — directory
        cmp #'$'
        bne @n_dollar
        jsr skip_sp_ptr1
        ldy #0
        lda (ptr1),y
        cmp #'0'
        bcc @dir_go
        cmp #'9'+1
        bcs @dir_go
        ; parse decimal device number
        lda #0
        sta tmp2                ; dev
@dev_lp:
        ldy #0
        lda (ptr1),y
        cmp #'0'
        bcc @dev_done
        cmp #'9'+1
        bcs @dev_done
        sec
        sbc #'0'
        pha
        ; dev = dev * 10 + digit
        lda tmp2
        asl                     ; *2
        sta tmp1
        asl                     ; *4
        asl                     ; *8
        clc
        adc tmp1                ; *10
        sta tmp2
        pla
        clc
        adc tmp2
        sta tmp2
        inc ptr1
        bne @dev_lp
        inc ptr1+1
        jmp @dev_lp
@dev_done:
        ; validate: 4-30
        lda tmp2
        cmp #4
        bcc @dir_go
        cmp #31
        bcs @dir_go
        sta _cur_device
@dir_go:
        jsr _newline
        lda _cur_device
        jsr _list_directory
        jmp nl_clear
@n_dollar:
        ; c — continue / cls
        cmp #'c'
        bne @n_c
        ; check for "lr" or "ls" after c
        ldy #0
        lda (ptr1),y
        cmp #'l'
        bne @c_not_cls
        ldy #1
        lda (ptr1),y
        cmp #'r'
        beq @c_cls
        cmp #'s'
        beq @c_cls
@c_not_cls:
        ; continue debugger
        lda _dbg_reason
        bne @c_has_ctx
        lda #<str_no_break
        ldx #>str_no_break
        jsr err_msg
        jmp nl_clear
@c_has_ctx:
        ; delete hit breakpoint before continuing
        lda _dbg_bp_hit
        cmp #$FF
        beq @c_enter
        jsr _dbg_bp_del
@c_enter:
        jsr _dbg_enter
        ; If dbg_reason=0, user code returned via RTS (no BRK fired)
        lda _dbg_reason
        bne @c_broke
        ; Normal completion — clear debug context
        lda #0
        sta last_cmd            ; no repeat
        jsr _restore_colors
        jmp nl_clear
@c_broke:
        jmp show_break_result

@c_cls: jsr _reset_screen
        jmp _io_clear_eol
@n_c:
        ; default: error
        lda #<str_err_cmd
        ldx #>str_err_cmd
        jsr err_msg
        jmp nl_clear
.endproc
