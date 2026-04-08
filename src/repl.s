; repl.s — REPL command line interface (hand-ported from repl.c)
;
; The screen IS the command buffer.  Press RETURN on any line
; to execute it.  AAAA:cmd [args] for addressed commands,
; cmd [args] for bare commands.  ';' ends parsing.

        .setcpu "6502"
        .macpack longbranch

; ── Exports ────────────────────────────────────────────────
        .export exec_line, read_line, show_prompt
        .export cur_addr, cur_device, cur_filename
        ; test harness visibility
        .export line_buf, last_cmd, block_size

; ── Imports: cse_io.s ──────────────────────────────────────
        .import io_putc, io_puts
        .import io_puthex4, io_puthex2, io_putdec
        .import io_clear_eol
        .import io_getc, io_kbhit, io_sync
        .import cursor_show, cursor_hide
        .import scr_lo, scr_hi

; ── Imports: screen.s ──────────────────────────────────────
        .import newline, restore_colors, reset_screen
        .import theme_border, theme_bg, theme_fg

; hex_val, is_hex, hex_val_to_char are now local (below)

; ── Imports: assembler / disassembler ──────────────────────
        .import asm_line
        .import dasm_insn, dasm_buf
        .import asm_assemble, asm_org, asm_size

; ── Imports: debugger ──────────────────────────────────────
        .import dbg_enter, dbg_step_clear
        .import dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .import dbg_bp_count
        .import bp_table, step_bp
        .import dbg_reason, dbg_bp_hit
        .import brk_pc
        .import reg_a, reg_x, reg_y, reg_sp, reg_p
        .import kernal_bank_out, kernal_bank_in
        .import oplen_tbl

; ── Imports: expression parser ─────────────────────────────
        .import expr_eval, expr_error_str
        .importzp expr_ptr, expr_val

; ── Imports: symbol table ──────────────────────────────────
        .import sym_lookup
        .importzp sym_name, sym_val

;── Imports: disk I/O ──────────────────────────────────────
        .import floppy_status, list_directory
        .import disk_load_prg, disk_save_prg

; ── Imports: editor ────────────────────────────────────────
        .import ed_save_source, ed_load_source
        .import ed_load_split, ed_load_split_lines
        .import ed_save_bytes, ed_save_lines
        .import ed_ensure_init, ed_new
        .import ed_dirty, ed_total_lines

; ── Imports: memory info ───────────────────────────────────
        .import cse_start, cse_end, cse_zp_end
        .import src_top, src_bot

; ── Imports: global state ──────────────────────────────────
        .import state
        .importzp al_cpu

; ── Imports: runtime ZP ────────────────────────────────────
        .importzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2
        .importzp al_pc, al_out
        .importzp disk_ptr

; ── Constants ──────────────────────────────────────────────
SCREEN        = $0400
SCREEN_WIDTH  = 40
BUF_END       = $D000
FILENAME_MAX  = 16
ST_STOP       = 0
CUR_COL       = $D3
CUR_ROW       = $D6

; ═══════════════════════════════════════════════════════════
; ZP: rp_ptr = q (parse pointer into line_buf or args)
;     rp_ptr2 = secondary pointer (output buffer, data src)
;     rp_tmp, rp_tmp2 = scratch bytes
;
; BSS scratch:
;   rp_addr (2) — address argument (cur_addr copy for commands)
;   rp_save (1) — saved byte (olen, cols, etc.)
;   rp_save2(1) — secondary scratch
;   rp_cnt  (2) — 16-bit counter
;   rp_next_lo(2) — cmd_step next PC low
;   rp_next_hi(2) — cmd_step next PC high
; ═══════════════════════════════════════════════════════════

; ── BSS ────────────────────────────────────────────────────
; Variables formerly in DATA are now BSS; initialized by main.s
; startup or by first use.  BSS is zeroed at boot.
.segment "BSS"

cur_addr:      .res 2          ; current memory address (init by splash)
cur_device:    .res 1          ; floppy device number (init by main.s)
last_cmd:       .res 1          ; last command byte
block_size:     .res 2          ; block size for I/O (init by main.s)
cur_filename:  .res FILENAME_MAX + 1  ; current filename

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
str_split_pfx:  .byte ";   ! ", 0
str_split_sfx:  .byte " lines split: ", 0
str_split_more: .byte "...", 0
str_del_src:    .byte ";delete source. are you sure? y/n ", 0
str_unsaved:    .byte ";unsaved. y/n? ", 0
str_ok:         .byte "ok", 0
str_B_eq:       .byte ";B=", 0             ; note: PETSCII uppercase B
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
str_stack:      .byte "6502 stack", 0
str_kernal_zp:  .byte "kernal zp", 0
str_screen:     .byte "screen + sprites", 0
str_cse_rt:     .byte "cse runtime", 0
str_bytes_free: .byte " bytes free", 0
str_vic:        .byte "vic/sid/cia", 0
str_kern_rom:   .byte "kernal rom", 0
str_i_free:     .byte "free", 0
str_i_lines:    .byte " lines", 0
str_main:       .byte "main", 0

; info_line tag strings
str_tag_cpu:    .byte "cpu", 0
str_tag_zp:     .byte "zp", 0
str_tag_stk:    .byte "stk", 0
str_tag_sys:    .byte "sys", 0
str_tag_scr:    .byte "scr", 0
str_tag_cse:    .byte "cse", 0
str_tag_work:   .byte "work", 0
str_free_suf:   .byte "  free", 0
str_tag_src:    .byte "src", 0
str_tag_io:     .byte "io", 0
str_tag_kern:   .byte "kern", 0

; ── info tables: 8 bytes per row: tag(2) lo(2) hi(2) desc(2) ──
; Head row 1: cpu only
info_tbl_h1:
        .addr str_tag_cpu,  $0000, $0001, str_ioport         ; cpu  0000-0001
INFO_TBL_H1_ROWS = (* - info_tbl_h1) / 8

; Head rows 3-4: between zp-free and sys-free
info_tbl_h2:
        .addr str_tag_sys,  $0080, $00FF, str_kernal_zp       ; sys  0080-00ff  kernal zp
        .addr str_tag_stk,  $0100, $01FF, str_stack           ; stk  0100-01ff  6502 stack
INFO_TBL_H2_ROWS = (* - info_tbl_h2) / 8

; Head row 6: between sys-free and cse
info_tbl_h3:
        .addr str_tag_scr,  $0400, $07FF, str_screen          ; scr  0400-07ff  screen+sprites
INFO_TBL_H3_ROWS = (* - info_tbl_h3) / 8

; Tail: after dynamic cse/free/src
info_tbl_tail:
        .addr str_tag_io,   $D000, $DFFF, str_vic            ; io   d000-dfff
        .addr str_tag_kern, $E000, $FFFF, str_kern_rom       ; kern e000-ffff
INFO_TBL_TAIL_ROWS = (* - info_tbl_tail) / 8


; ── CODE ───────────────────────────────────────────────────
.segment "CODE"

; ═══════════════════════════════════════════════════════════
; Inline helpers
; ═══════════════════════════════════════════════════════════

; nl_clear — newline + clear_eol
nl_clear:
        jsr newline
        jmp io_clear_eol

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
        jsr io_puthex4
        lda #':'
        jsr io_putc
        pla
        jmp io_putc

; ───────────────────────────────────────────────────────────
; err_msg — newline + print string + clear_eol
;   A/X = string ptr
; ───────────────────────────────────────────────────────────
err_msg:
        pha
        txa
        pha
        jsr newline
        pla
        tax
        pla
        jsr io_puts
        jmp io_clear_eol

; ───────────────────────────────────────────────────────────
; confirm_yn — show cursor, wait for key, return Z=1 if 'y'
;   Clobbers A.  Preserves X, Y.
; ───────────────────────────────────────────────────────────
confirm_yn:
        jsr cursor_show
        jsr io_getc
        pha
        jsr cursor_hide
        pla
        cmp #'y'
        rts

; ───────────────────────────────────────────────────────────
; check_unsaved — if ed_dirty, prompt ";unsaved. y/n? "
;   Returns: C=1 proceed (not dirty or user said y)
;            C=0 cancel (user said no)
; ───────────────────────────────────────────────────────────
check_unsaved:
        lda ed_dirty
        beq @ok                 ; not dirty → proceed
        jsr newline
        lda #<str_unsaved
        ldx #>str_unsaved
        jsr io_puts
        jsr confirm_yn
        beq @ok
        jsr io_clear_eol
        clc                     ; cancel
        rts
@ok:    sec                     ; proceed
        rts

; ───────────────────────────────────────────────────────────
; skip_sp_ptr1 — skip spaces at (rp_ptr), advancing rp_ptr
; ───────────────────────────────────────────────────────────
skip_sp_ptr1:
        ldy #0
@lp:    lda (rp_ptr),y
        cmp #' '
        bne @done
        inc rp_ptr
        bne @lp
        inc rp_ptr+1
        bne @lp
@done:  rts

; ───────────────────────────────────────────────────────────
; is_eow_at_ptr1_y — is the byte at (rp_ptr),y an end-of-word?
;   EOW = space ($20), NUL ($00), or ';' (comment start).
;   Returns Z=1 on match, Z=0 otherwise.  Preserves X, Y.
;   Clobbers A.
; ───────────────────────────────────────────────────────────
is_eow_at_ptr1_y:
        lda (rp_ptr),y
        beq @r                  ; NUL → Z set
        cmp #' '
        beq @r                  ; SPC → Z set
        cmp #';'                ; ; → Z set; anything else → Z clear
@r:     rts

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
; is_hex_at_ptr1 — test if byte at (rp_ptr)+Y is hex
;   Returns: Z=0 if hex, Z=1 if not. Preserves Y.
; ───────────────────────────────────────────────────────────
is_hex_at_ptr1:
        lda (rp_ptr),y
        jmp _is_hex             ; tail call; Z flag set on return

; ───────────────────────────────────────────────────────────
; is_hex4_at_ptr1 — are rp_ptr[0..3] all hex digits?
;   Returns: Z=0 if all four are hex, Z=1 if any isn't.
;   On failure Y holds the first non-hex position (3..0).
;   On success Y=$FF, A=$01.  Callers that need Y afterwards
;   must set it themselves.
; ───────────────────────────────────────────────────────────
is_hex4_at_ptr1:
        ldy #3
@l:     jsr is_hex_at_ptr1
        beq @r                  ; Z=1 → fail, return Z=1
        dey
        bpl @l
        lda #1                  ; success: force Z=0
@r:     rts

; ───────────────────────────────────────────────────────────
; hex_val_at_ptr1 — get hex value of byte at (rp_ptr)+Y
;   Returns nibble in A (0-15). Preserves Y.
; ───────────────────────────────────────────────────────────
hex_val_at_ptr1:
        lda (rp_ptr),y
        jmp _hex_val

; ───────────────────────────────────────────────────────────
; parse_hex2_ptr1 — parse 2 hex digits at rp_ptr, advance rp_ptr
;   Returns byte in A.
; ───────────────────────────────────────────────────────────
parse_hex2_ptr1:
        ldy #0
        lda (rp_ptr),y
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta rp_tmp
        ldy #1
        lda (rp_ptr),y
        jsr _hex_val
        ora rp_tmp
        pha
        lda rp_ptr
        clc
        adc #2
        sta rp_ptr
        bcc :+
        inc rp_ptr+1
:       pla
        rts

; ───────────────────────────────────────────────────────────
; parse_hex4_ptr1 — parse 4 hex digits at rp_ptr, advance rp_ptr
;   Returns value in A (lo) / X (hi).
; ───────────────────────────────────────────────────────────
parse_hex4_ptr1:
        ldy #0
        lda (rp_ptr),y
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta rp_tmp2                ; hi nibble of high byte
        ldy #1
        lda (rp_ptr),y
        jsr _hex_val
        ora rp_tmp2
        sta rp_tmp2                ; high byte complete
        ldy #2
        lda (rp_ptr),y
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta rp_tmp
        ldy #3
        lda (rp_ptr),y
        jsr _hex_val
        ora rp_tmp                ; A = lo byte
        pha
        lda rp_ptr
        clc
        adc #4
        sta rp_ptr
        bcc :+
        inc rp_ptr+1
:       pla                     ; A = lo
        ldx rp_tmp2                ; X = hi
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
        stx rp_tmp
        lda #' '
        jsr io_putc
        ldx rp_tmp
        inx
        bne @digit
@force: lda #0
@emit:  clc
        adc #'0'
        stx rp_tmp
        jsr io_putc
        ldx rp_tmp
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
        sta rp_tmp                ; d
@sub:   lda rp_addr
        sec
        sbc dec_pow_lo,x
        tay
        lda rp_addr+1
        sbc dec_pow_hi,x
        bcc @chk
        sta rp_addr+1
        sty rp_addr
        inc rp_tmp
        bne @sub
@chk:   lda rp_tmp
        bne @emit
        lda rp_save2
        bne @emit
        cpx #4
        bne @next
@emit:  lda rp_tmp
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
; try_expr — evaluate expression at rp_ptr
;   C=1: success (result in expr_val, rp_ptr advanced)
;   C=0: empty or error (error printed)
; ═══════════════════════════════════════════════════════════
.proc try_expr
        jsr skip_sp_ptr1
        ldy #0
        lda (rp_ptr),y
        beq @empty
        cmp #';'
        beq @empty
        ; set expr_ptr = rp_ptr
        lda rp_ptr
        sta expr_ptr
        lda rp_ptr+1
        sta expr_ptr+1
        jsr expr_eval
        ; reload rp_ptr
        pha
        lda expr_ptr
        sta rp_ptr
        lda expr_ptr+1
        sta rp_ptr+1
        pla
        cmp #2
        bcs @error
        sec
        rts
@error:
        jsr newline
        lda #<str_err_expr
        ldx #>str_err_expr
        jsr io_puts
        jsr expr_error_str
        jsr io_puts
        jsr io_clear_eol
        clc
        rts
@empty: clc
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; read_line — read screen row at io_cy into line_buf
; ═══════════════════════════════════════════════════════════
.proc read_line
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_ptr
        lda scr_hi,x
        sta rp_ptr+1

        ldy #0
@loop:  lda (rp_ptr),y
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
; show_prompt — print "AAAA:" at cursor
; ═══════════════════════════════════════════════════════════
.proc show_prompt
        lda #0
        sta CUR_COL
        lda cur_addr
        ldx cur_addr+1
        jsr io_puthex4
        lda #':'
        jmp io_putc
.endproc

; ═══════════════════════════════════════════════════════════
; emit_hex_cols — print hex columns
;   rp_ptr2 = src, rp_save = count, rp_save2 = max
; ═══════════════════════════════════════════════════════════
.proc emit_hex_cols
        ldy #0
@loop:  cpy rp_save2
        bcs @done
        cpy rp_save
        bcs @pad
        lda #' '
        sty rp_tmp
        jsr io_putc
        ldy rp_tmp
        lda (rp_ptr2),y
        sty rp_tmp
        jsr io_puthex2
        ldy rp_tmp
        iny
        bne @loop
@pad:   lda #<str_3sp
        ldx #>str_3sp
        sty rp_tmp
        jsr io_puts
        ldy rp_tmp
        iny
        bne @loop
@done:  rts
.endproc

; ═══════════════════════════════════════════════════════════
; emit_dot — disassemble and display "ADDR:. XX XX XX  mne op"
;   rp_addr = address. Returns instruction length in A.
; ═══════════════════════════════════════════════════════════
.proc emit_dot
        ; dasm_insn owns its KERNAL banking — we just call it.
        lda rp_addr
        ldx rp_addr+1
        jsr dasm_insn
        pha                     ; save olen for later use

        lda #'.'
        jsr io_addr_cmd
        lda #' '
        jsr io_putc

        ; emit_hex_cols(addr, olen, 3)
        lda rp_addr
        sta rp_ptr2
        lda rp_addr+1
        sta rp_ptr2+1
        pla                     ; olen
        pha
        sta rp_save             ; count
        lda #3
        sta rp_save2            ; max
        jsr emit_hex_cols

        lda #<str_2sp
        ldx #>str_2sp
        jsr io_puts
        lda #<dasm_buf
        ldx #>dasm_buf
        jsr io_puts
        jsr io_clear_eol

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
        sta rp_ptr2
        lda rp_addr+1
        sta rp_ptr2+1
        lda rp_opc
        sta rp_save
        lda #8
        sta rp_save2
        jsr emit_hex_cols

        lda #' '
        jsr io_putc

        ldy #0
@asc:   cpy rp_opc
        bcs @adone
        lda (rp_ptr2),y
        cmp #$20
        bcc @dot
        cmp #$7F
        bcs @dot
        bcc @aput
@dot:   lda #'.'
@aput:  sty rp_tmp
        jsr io_putc
        ldy rp_tmp
        iny
        bne @asc
@adone: jmp io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; emit_reg — print register dump
; ═══════════════════════════════════════════════════════════
.proc emit_reg
        lda #0
        sta CUR_COL
        lda #<str_r_pc
        ldx #>str_r_pc
        jsr io_puts
        lda brk_pc
        ldx brk_pc+1
        jsr io_puthex4
        lda #<str_a
        ldx #>str_a
        jsr io_puts
        lda reg_a
        jsr io_puthex2
        lda #<str_x
        ldx #>str_x
        jsr io_puts
        lda reg_x
        jsr io_puthex2
        lda #<str_y
        ldx #>str_y
        jsr io_puts
        lda reg_y
        jsr io_puthex2
        lda #<str_s
        ldx #>str_s
        jsr io_puts
        lda reg_sp
        jsr io_puthex2
        lda #' '
        jsr io_putc

        lda reg_p
        sta rp_tmp2
        ldx #0
@fl:    asl rp_tmp2
        bcs @set
        lda #'.'
        bne @fp
@set:   lda flag_ch,x
@fp:    stx rp_tmp
        jsr io_putc
        ldx rp_tmp
        inx
        cpx #8
        bcc @fl
        jmp io_clear_eol
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
        jsr restore_colors

        lda dbg_reason
        cmp #1
        beq @brk
        cmp #2
        beq @nmi
        jmp @regs                ; normal completion — skip status line

@brk:   jsr newline
        lda #<str_brk
        ldx #>str_brk
        jsr io_puts
        lda dbg_bp_hit
        cmp #$FF
        beq @brk_at
        lda #' '
        jsr io_putc
        lda dbg_bp_hit
        clc
        adc #'1'
        jsr io_putc
@brk_at:
        lda #<str_at
        ldx #>str_at
        jsr io_puts
        lda brk_pc
        ldx brk_pc+1
        jsr io_puthex4
        jsr io_clear_eol
        jmp @regs

@nmi:   jsr newline
        lda #<str_nmi
        ldx #>str_nmi
        jsr io_puts
        lda brk_pc
        ldx brk_pc+1
        jsr io_puthex4
        jsr io_clear_eol

@regs:  ; register dump + disassembly at brk_pc
        jsr newline
        jsr emit_reg
        jsr newline
        lda brk_pc
        sta cur_addr
        sta rp_addr
        lda brk_pc+1
        sta cur_addr+1
        sta rp_addr+1
        jsr emit_dot
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; dot_assemble — assemble with expression support
;   rp_addr = address, rp_ptr = text. Returns nbytes in A.
; ═══════════════════════════════════════════════════════════
.proc dot_assemble
        lda #<dot_asm_buf
        sta rp_ptr2
        lda #>dot_asm_buf
        sta rp_ptr2+1

        ; Copy mnemonic (a-z)
        ldy #0
@mne:   lda (rp_ptr),y
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

        ; advance rp_ptr past mnemonic
        tya
        clc
        adc rp_ptr
        sta rp_ptr
        bcc :+
        inc rp_ptr+1
:
        jsr skip_sp_ptr1

        ldy #0
        lda (rp_ptr),y
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
        lda (rp_ptr),y
        cmp #'#'
        bne @noh
        ldy rp_save
        sta dot_asm_buf,y
        iny
        sty rp_save
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       jsr skip_sp_ptr1
@noh:   ldy #0
        lda (rp_ptr),y
        cmp #'('
        bne @nop
        ldy rp_save
        sta dot_asm_buf,y
        iny
        sty rp_save
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       jsr skip_sp_ptr1
@nop:
        ; evaluate expression
        lda rp_ptr
        sta expr_ptr
        lda rp_ptr+1
        sta expr_ptr+1
        jsr expr_eval
        cmp #2
        jcs @err
        pha                     ; save rc (0=ZP, 1=ABS)

        lda expr_ptr
        sta rp_ptr
        lda expr_ptr+1
        sta rp_ptr+1

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
        lda (rp_ptr),y
        beq @done
        cmp #';'
        beq @done
        ldy rp_save
        cpy #22
        bcs @done
        sta dot_asm_buf,y
        iny
        sty rp_save
        inc rp_ptr
        bne @sfx
        inc rp_ptr+1
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
        ; asm_line(buf) — caller sets al_pc/al_out, buf in A/X.
        ; asm_line owns its own KERNAL banking; we just call it.
        lda rp_addr
        sta al_pc
        sta al_out
        lda rp_addr+1
        sta al_pc+1
        sta al_out+1
        lda #<dot_asm_buf
        ldx #>dot_asm_buf
        jmp asm_line            ; tail call

@err:   lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_dot — '.' command: hex edit / assemble / disassemble
;   rp_ptr = args
; ═══════════════════════════════════════════════════════════
.proc cmd_dot
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
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
        ; check rp_ptr[2] is end-of-word (space/NUL/;)
        ldy #2
        jsr is_eow_at_ptr1_y
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
        sty rp_tmp
        tya
        clc
        adc rp_addr
        sta rp_ptr2
        lda #0
        adc rp_addr+1
        sta rp_ptr2+1
        ldy #0
        lda (rp_ptr2),y
        ldy rp_tmp
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
        sty rp_tmp
        lda rp_hexbuf,y
        pha
        tya
        clc
        adc rp_addr
        sta rp_ptr2
        lda #0
        adc rp_addr+1
        sta rp_ptr2+1
        pla
        ldy #0
        sta (rp_ptr2),y
        ldy rp_tmp
        iny
        bne @write

@show:  ; emit_dot, advance cur_addr, newline
        ; if rp_cnt (nbytes) > 0, skip clear_eol
        jsr emit_dot
        clc
        adc rp_addr
        sta cur_addr
        lda #0
        adc rp_addr+1
        sta cur_addr+1
        jsr newline
        lda rp_cnt
        bne @ret                ; nbytes > 0 → don't clear
        jmp io_clear_eol
@ret:   rts

@try_asm_mne:
@try_mne:
        ; Try mnemonic assembly if (rp_ptr) starts with a-z
        jsr skip_sp_ptr1
        ldy #0
        lda (rp_ptr),y
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
;   rp_ptr = args (ignored)
; ═══════════════════════════════════════════════════════════
.proc cmd_disasm
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
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
:       jsr newline
        ; if addr wrapped to 0, break
        lda rp_addr
        ora rp_addr+1
        bne @loop

@done:  lda rp_addr
        sta cur_addr
        lda rp_addr+1
        sta cur_addr+1
        jmp io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_mem — 'm' command: memory dump / edit
;   rp_ptr = args
; ═══════════════════════════════════════════════════════════
.proc cmd_mem
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
        sta rp_addr+1

        jsr skip_sp_ptr1

        ; Check for 4-digit hex address override
        jsr is_hex4_at_ptr1
        beq @no_addr
        ; check q[4] is end-of-word (space/NUL/;)
        ldy #4
        jsr is_eow_at_ptr1_y
        jne @no_addr
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
        jsr is_eow_at_ptr1_y
        jne @dump

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
        sta rp_ptr2
        lda #0
        adc rp_addr+1
        sta rp_ptr2+1
        pla
        ldy #0
        cmp (rp_ptr2),y
        beq @same
        sta (rp_ptr2),y
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
        sta cur_addr
        lda #0
        adc rp_addr+1
        sta cur_addr+1
        ; check wrap
        bcs @wrap_ed
        jmp @ed_nl
@wrap_ed:
        lda #0
        sta cur_addr
        sta cur_addr+1
@ed_nl: jmp newline

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
:       jsr newline
        ; check addr wrap (addr < cols means wrapped)
        lda rp_addr
        cmp rp_save
        lda rp_addr+1
        sbc #0
        bcc @d_done
        jmp @d_lp

@d_done:
        lda rp_addr
        sta cur_addr
        lda rp_addr+1
        sta cur_addr+1
        jmp io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; run_user — call dbg_enter, then restore screen state
;   Does NOT save/restore cursor: user code's CHROUT writes
;   visible output, and subsequent CSE output (show_break_result,
;   the next prompt) flows from wherever user code left the
;   cursor.  Restores VIC charset (in case user code touched
;   $D018) and resyncs KERNAL screen line pointers via PLOT.
;
;   The CALLER (cmd_jmp / cmd_step) is responsible for moving
;   the cursor to a fresh row BEFORE the first run_user call,
;   so user output never overwrites the typed command at col 0
;   of the prompt row.  cmd_step does this once before its
;   step loop so the per-iteration cost is zero newlines —
;   multi-step commands like `t10` don't bloat the display.
;
;   Must be used instead of bare dbg_enter from g/j/t/o.
; ═══════════════════════════════════════════════════════════
VIC_MEMCTL = $D018

.proc run_user
        jsr dbg_enter
        ; Restore VIC charset (lowercase/uppercase)
        lda VIC_MEMCTL
        ora #$02
        sta VIC_MEMCTL
        ; Resync KERNAL screen line pointers
        jmp io_sync
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_jmp — 'j' command helper (cur_addr already set)
; ═══════════════════════════════════════════════════════════
.proc cmd_jmp
        lda cur_addr
        sta brk_pc
        lda cur_addr+1
        sta brk_pc+1

        ; Newline + clreol BEFORE running user code so user
        ; CHROUT output starts on a fresh row instead of
        ; overwriting the typed command at col 0 of the prompt.
        jsr newline
        jsr io_clear_eol

        ; Always use run_user — enables NMI break even without bps.
        ; When no breakpoints, patch_all/unpatch_all are no-ops.
        jsr run_user
        lda dbg_reason
        bne @j_broke
        ; program completed via RTS — no break context
        jsr restore_colors
        jmp nl_clear
@j_broke:
        jmp show_break_result
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_step — 't'/'o' command
;   rp_ptr = args, A = is_next (0=step into, 1=step over)
; ═══════════════════════════════════════════════════════════
.proc cmd_step
        sta rp_save2            ; is_next

        ; Cold start check
        lda dbg_reason
        bne @has_ctx
        lda cur_addr
        sta brk_pc
        lda cur_addr+1
        sta brk_pc+1
        lda #1
        sta dbg_reason
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
        lda dbg_bp_hit
        cmp #$FF
        beq @newline_first      ; no bp hit → nothing to disable
        asl
        asl                     ; slot * 4
        tax
        stx rp_dis_bp           ; remember slot offset
        lda #0
        sta bp_table+3,x       ; clear enabled flag

@newline_first:
        ; Newline + clreol ONCE before the step loop so user
        ; CHROUT output starts on a fresh row instead of
        ; overwriting the typed command at col 0 of the prompt.
        ; Per-iteration newlines would bloat multi-step commands
        ; like `t10`, so we only do this once at the start.
        jsr newline
        jsr io_clear_eol

        ; for i = 0; i < count; i++
@loop:  lda rp_cnt
        ora rp_cnt+1
        jeq @normal_end

        ; opc = *(brk_pc)
        lda brk_pc
        sta rp_ptr2
        lda brk_pc+1
        sta rp_ptr2+1
        ldy #0
        lda (rp_ptr2),y
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
        lda al_cpu
        cmp #2
        bcc @not_7c
        ; next_lo = *(*(brk_pc+1) + reg_x)
        ldy #1
        lda (rp_ptr2),y
        clc
        adc reg_x
        sta rp_ptr
        iny
        lda (rp_ptr2),y
        adc #0
        sta rp_ptr+1
        ldy #0
        lda (rp_ptr),y
        sta rp_next_lo
        iny
        lda (rp_ptr),y
        sta rp_next_lo+1
        jmp @check_next

@not_7c:
        ; BRA ($80) — 65C02 unconditional
        lda rp_opc
        cmp #$80
        bne @not_bra
        lda al_cpu
        cmp #2
        bcc @not_bra
        ; next_lo = brk_pc + 2 + (signed)*(brk_pc+1)
        ldy #1
        lda (rp_ptr2),y            ; signed relative
        bpl @bra_pos
        ; negative offset
        clc
        adc brk_pc
        sta rp_next_lo
        lda brk_pc+1
        adc #$FF                ; sign extend
        sta rp_next_lo+1
        jmp @bra_add2
@bra_pos:
        clc
        adc brk_pc
        sta rp_next_lo
        lda brk_pc+1
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
        lda (rp_ptr2),y            ; signed relative
        bpl @br_pos
        clc
        adc brk_pc
        sta rp_next_lo
        lda brk_pc+1
        adc #$FF
        sta rp_next_lo+1
        jmp @br_add2
@br_pos:
        clc
        adc brk_pc
        sta rp_next_lo
        lda brk_pc+1
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
        lda brk_pc
        clc
        adc #2
        sta rp_next_hi
        lda brk_pc+1
        adc #0
        sta rp_next_hi+1
        jmp @check_next

@linear:
        ; Linear: next = brk_pc + opcode_length(rp_opc)
        ; Packed table: 2 bits per opcode, 4 per byte.
        ; byte = opc >> 2, position = opc & 3.
        ; pos 0 = bits 1:0, pos 1 = 3:2, pos 2 = 5:4, pos 3 = 7:6.
        lda rp_opc
        lsr
        lsr                     ; byte index = opc >> 2
        tax
        lda oplen_tbl,x         ; packed byte
        sta rp_save             ; save packed byte
        lda rp_opc
        and #$03                ; position (0-3)
        beq @len_done           ; pos 0: bits 1:0, no shift
        tax
@len_shift:
        lsr rp_save             ; shift right 2 bits
        lsr rp_save
        dex
        bne @len_shift
@len_done:
        lda rp_save
        and #$03                ; length (1, 2, or 3)
        clc
        adc brk_pc
        sta rp_next_lo
        lda #0
        adc brk_pc+1
        sta rp_next_lo+1
        jmp @check_next

@jsr:   ; JSR abs
        lda rp_save2            ; is_next
        bne @jsr_over
        ; ── Step into, but only if the target is RAM-writable.
        ; CSE unmaps BASIC ROM at startup, so $A000–$BFFF is the
        ; user workspace (RAM).  KERNAL ROM remains mapped at
        ; $E000–$FFFF — patching a BRK there writes to the RAM
        ; underneath but the CPU fetches from ROM and never sees
        ; the BRK.  The step-into would run forever in ROM (e.g.
        ; JSR $FFD2 → CHROUT → garbage after returning).  Treat
        ; KERNAL JSR targets as step-over instead.
        ldy #2
        lda (rp_ptr2),y         ; target hi
        cmp #$E0
        bcc @jsr_into            ; <$E000 → RAM/IO/workspace
                                  ; $E000–$FFFF → KERNAL ROM, step-over
@jsr_over:
        ; step over: next = brk_pc + 3
        lda brk_pc
        clc
        adc #3
        sta rp_next_lo
        lda brk_pc+1
        adc #0
        sta rp_next_lo+1
        jmp @check_next
@jsr_into:
        ; step into: next = *(brk_pc+1)
        ldy #1
        lda (rp_ptr2),y
        sta rp_next_lo
        iny
        lda (rp_ptr2),y
        sta rp_next_lo+1
        jmp @check_next

@jmp_abs:
        ; JMP abs: next = *(brk_pc+1)
        ldy #1
        lda (rp_ptr2),y
        sta rp_next_lo
        iny
        lda (rp_ptr2),y
        sta rp_next_lo+1
        jmp @check_next

@jmp_ind:
        ; JMP (ind): next = **(brk_pc+1)
        ldy #1
        lda (rp_ptr2),y
        sta rp_ptr
        iny
        lda (rp_ptr2),y
        sta rp_ptr+1
        ldy #0
        lda (rp_ptr),y
        sta rp_next_lo
        iny
        lda (rp_ptr),y
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
        jsr dbg_step_clear
        lda rp_next_lo
        sta step_bp
        lda rp_next_lo+1
        sta step_bp+1
        lda #0
        sta step_bp+2          ; saved byte (cleared)
        lda #1
        sta step_bp+3          ; enabled

        ; second target if present
        lda rp_next_hi
        ora rp_next_hi+1
        beq @enter
        lda rp_next_hi
        sta step_bp+4
        lda rp_next_hi+1
        sta step_bp+5
        lda #0
        sta step_bp+6
        lda #1
        sta step_bp+7

@enter: jsr run_user

        ; Check for NMI, breakpoint hit, or RTS completion
        lda dbg_reason
        beq @normal_end         ; 0 = user code returned via RTS
        cmp #2
        beq @interrupted
        lda dbg_bp_hit
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
        jsr dbg_step_clear
        jsr @re_enable_bp
        jmp show_break_result

@normal_end:
        jsr dbg_step_clear
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
        sta bp_table+3,x       ; restore enabled flag
@re_rts:
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_brk — 'b' command: breakpoints
;   rp_ptr = args
; ═══════════════════════════════════════════════════════════
.proc cmd_brk
        jsr skip_sp_ptr1

        ldy #0
        lda (rp_ptr),y
        bne @not_empty

        ; b — list all breakpoints
        jsr newline
        ldx #0                  ; slot index
@list:  cpx #8
        bcs @list_done
        stx rp_save
        lda #<bp_pfx
        ldx #>bp_pfx
        jsr io_puts
        ldx rp_save
        txa
        clc
        adc #'1'
        jsr io_putc
        lda #<str_colon_sp
        ldx #>str_colon_sp
        jsr io_puts
        ; bp_table[slot*4].addr
        ldx rp_save
        txa
        asl
        asl
        tay
        lda bp_table,y
        sta rp_addr
        lda bp_table+1,y
        sta rp_addr+1
        ora rp_addr
        beq @empty_slot
        lda #'$'
        jsr io_putc
        lda rp_addr
        ldx rp_addr+1
        jsr io_puthex4
        jmp @slot_done
@empty_slot:
        lda #<str_dashes
        ldx #>str_dashes
        jsr io_puts
@slot_done:
        jsr io_clear_eol
        jsr newline
        ldx rp_save
        inx
        jmp @list
@list_done:
        jmp io_clear_eol

@not_empty:
        cmp #'*'
        bne @not_star
        ; b * — delete all
        jsr dbg_bp_clear
        jsr newline
        lda #<str_bp_clr
        ldx #>str_bp_clr
        jsr io_puts
        jsr io_clear_eol
        jmp nl_clear

@not_star:
        cmp #'-'
        bne @set_bp
        ; b -N — delete
        ldy #1
        lda (rp_ptr),y
        cmp #'1'
        bcc @bad_slot
        cmp #'9'
        bcs @bad_slot
        sec
        sbc #'1'
        jsr dbg_bp_del
        jsr newline
        lda #<bp_pfx
        ldx #>bp_pfx
        jsr io_puts
        ldy #1
        lda (rp_ptr),y
        jsr io_putc
        lda #<str_deleted
        ldx #>str_deleted
        jsr io_puts
        jsr io_clear_eol
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
        jsr dbg_bp_set         ; returns slot in A ($FF=full)
        cmp #$FF
        beq @full
        ; success
        pha
        jsr newline
        lda #<bp_pfx
        ldx #>bp_pfx
        jsr io_puts
        pla
        clc
        adc #'1'
        jsr io_putc
        lda #<str_colon_sp
        ldx #>str_colon_sp
        jsr io_puts
        lda #'$'
        jsr io_putc
        lda expr_val
        ldx expr_val+1
        jsr io_puthex4
        jsr io_clear_eol
        jmp nl_clear

@full:  jsr newline
        lda #<str_bp_full
        ldx #>str_bp_full
        jsr io_puts
        jsr io_clear_eol
        jmp nl_clear

@err_b: lda #<str_err_b
        ldx #>str_err_b
        jsr err_msg
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; parse_regval — skip 2 chars (label:), parse 2 hex at rp_ptr
;   Advances rp_ptr by 4. Returns byte in A.
; ═══════════════════════════════════════════════════════════
.proc parse_regval
        lda rp_ptr
        clc
        adc #2
        sta rp_ptr
        bcc :+
        inc rp_ptr+1
:       jmp parse_hex2_ptr1
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_reg — 'r' command
;   rp_ptr = args
; ═══════════════════════════════════════════════════════════
.proc cmd_reg
        jsr skip_sp_ptr1
        ldy #0
        lda (rp_ptr),y
        beq @show

        ; Parse: a:XX x:XX y:XX s:XX flags
        jsr parse_regval
        sta reg_a
        jsr skip_sp_ptr1
        jsr parse_regval
        sta reg_x
        jsr skip_sp_ptr1
        jsr parse_regval
        sta reg_y
        jsr skip_sp_ptr1
        jsr parse_regval
        sta reg_sp
        jsr skip_sp_ptr1

        ; Parse flags: 8 chars, set bit if matches flag_ch[i]
        lda #0
        sta rp_tmp2                ; p accumulator
        ldx #0
@pflag: cpx #8
        bcs @pflags_done
        asl rp_tmp2                ; shift left to make room
        ldy #0
        lda (rp_ptr),y
        cmp flag_ch,x
        bne @pnot
        lda rp_tmp2
        ora #1
        sta rp_tmp2
@pnot:  ; advance rp_ptr if not NUL
        ldy #0
        lda (rp_ptr),y
        beq @pskip
        inc rp_ptr
        bne @pskip
        inc rp_ptr+1
@pskip: inx
        jmp @pflag
@pflags_done:
        lda rp_tmp2
        sta reg_p

@show:  jsr newline
        jsr emit_reg
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; is_seq_file — check if name ends with ",s" or ",S"
;   rp_ptr = name pointer. Returns A=1 if seq, A=0 if not.
; ═══════════════════════════════════════════════════════════
.proc is_seq_file
        ; find length
        ldy #0
@len:   lda (rp_ptr),y
        beq @got_len
        iny
        bne @len
@got_len:
        ; need at least 2 chars
        cpy #2
        bcc @no
        dey
        lda (rp_ptr),y            ; last char
        cmp #'s'
        beq @chk_comma
        cmp #$D3                ; PETSCII uppercase S
        bne @no
@chk_comma:
        dey
        lda (rp_ptr),y
        cmp #','
        bne @no
        lda #1
        rts
@no:    lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; parse_filename — parse quoted or space-delimited name
;   rp_ptr = input. Returns: rp_ptr2 = name, rp_ptr advanced.
;   A=0 if no name (error). A=1 if name found.
; ═══════════════════════════════════════════════════════════
.proc parse_filename
        jsr skip_sp_ptr1

        ldy #0
        lda (rp_ptr),y
        cmp #$22                ; quote char
        bne @unquoted

        ; quoted: skip opening quote
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       lda rp_ptr
        sta rp_ptr2
        lda rp_ptr+1
        sta rp_ptr2+1
        ; scan for closing quote or NUL
        ldy #0
@qscan: lda (rp_ptr),y
        beq @qdone
        cmp #$22
        beq @qclose
        iny
        bne @qscan
@qclose:
        ; NUL-terminate in place: store 0 at closing quote
        lda #0
        sta (rp_ptr),y
        ; advance rp_ptr past closing quote
        iny
        tya
        clc
        adc rp_ptr
        sta rp_ptr
        bcc @qdone
        inc rp_ptr+1
@qdone: jsr skip_sp_ptr1
        jmp @check_empty

@unquoted:
        lda rp_ptr
        sta rp_ptr2
        lda rp_ptr+1
        sta rp_ptr2+1
        ; scan for space or NUL
        ldy #0
@uscan: lda (rp_ptr),y
        beq @udone
        cmp #' '
        beq @uclose
        iny
        bne @uscan
@uclose:
        ; NUL-terminate
        lda #0
        sta (rp_ptr),y
        iny
        tya
        clc
        adc rp_ptr
        sta rp_ptr
        bcc :+
        inc rp_ptr+1
:       jsr skip_sp_ptr1
        jmp @check_empty

@udone: ; rp_ptr already at NUL, which is fine
        tya
        clc
        adc rp_ptr
        sta rp_ptr
        bcc @check_empty
        inc rp_ptr+1

@check_empty:
        ; check if name is empty
        ldy #0
        lda (rp_ptr2),y
        beq @fail
        lda #1
        rts
@fail:  lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; get_filename — parse and remember filename
;   rp_ptr = input. Returns: rp_ptr2 = name, A=0 if no name.
;   Copies to cur_filename if new name found.
; ═══════════════════════════════════════════════════════════
.proc get_filename
        jsr parse_filename
        bne @got_name

        ; no name in args — try cur_filename
        lda cur_filename
        beq @fail
        lda #<cur_filename
        sta rp_ptr2
        lda #>cur_filename
        sta rp_ptr2+1
        lda #1
        rts

@got_name:
        ; copy name to cur_filename (rp_ptr2 = source)
        ldy #0
@copy:  lda (rp_ptr2),y
        sta cur_filename,y
        beq @copy_done
        iny
        cpy #FILENAME_MAX
        bcc @copy
        ; max reached, NUL-terminate
        lda #0
        sta cur_filename,y
@copy_done:
        lda #1
        rts

@fail:  lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; io_quoted_name — print '; "name": '
;   rp_ptr2 = name
; ═══════════════════════════════════════════════════════════
.proc io_quoted_name
        lda #<str_semi_q
        ldx #>str_semi_q
        jsr io_puts
        lda rp_ptr2
        ldx rp_ptr2+1
        jsr io_puts
        lda #<str_qcolon
        ldx #>str_qcolon
        jmp io_puts
.endproc

; ═══════════════════════════════════════════════════════════
; print_seq_stats — print "name: N lines, M bytes"
;   rp_ptr2 = name
; ═══════════════════════════════════════════════════════════
.proc print_seq_stats
        jsr io_quoted_name
        lda ed_save_lines
        ldx ed_save_lines+1
        jsr io_putdec
        lda #<str_lines
        ldx #>str_lines
        jsr io_puts
        lda ed_save_bytes
        ldx ed_save_bytes+1
        jsr io_putdec
        lda #<str_bytes
        ldx #>str_bytes
        jmp io_puts
.endproc

; ═══════════════════════════════════════════════════════════
; print_load_split_warning — print split warning if any lines
; were split during the last ed_load_source.
;
; Output format (when ed_load_split > 0):
;   ;   ! 3 lines split: 15, 23, 40
; or if more than 8 splits:
;   ;   ! 12 lines split: 15, 23, 40, 51, 64, 72, 85, 97...
;
; Line numbers are 1-based (editor lines are 0-based internally).
; Only the first min(8, ed_load_split) numbers are printed; if
; ed_load_split > 8, the list is followed by "..." to indicate
; more.
; ═══════════════════════════════════════════════════════════
.proc print_load_split_warning
        lda ed_load_split
        beq @done               ; no splits → nothing to print
        jsr newline
        lda #<str_split_pfx
        ldx #>str_split_pfx
        jsr io_puts
        lda ed_load_split
        ldx #0
        jsr io_putdec
        lda #<str_split_sfx
        ldx #>str_split_sfx
        jsr io_puts

        ; Print up to 8 line numbers (1-based, comma-separated)
        lda ed_load_split
        cmp #9
        bcc @count_ok
        lda #8
@count_ok:
        sta @count              ; count of numbers to print
        ldx #0
        stx @idx
@num_loop:
        lda @idx
        cmp @count
        bcs @nums_done
        ; Separator (comma + space) if not first
        lda @idx
        beq @no_sep
        lda #','
        jsr io_putc
        lda #' '
        jsr io_putc
@no_sep:
        ; Load the 16-bit line number from ed_load_split_lines[idx*2]
        lda @idx
        asl                     ; idx*2
        tax
        lda ed_load_split_lines,x
        clc
        adc #1                  ; 1-based
        sta rp_tmp              ; lo
        lda ed_load_split_lines+1,x
        adc #0
        tax                     ; hi
        lda rp_tmp              ; lo
        jsr io_putdec
        inc @idx
        jmp @num_loop
@nums_done:
        ; If more than 8 splits, append "..."
        lda ed_load_split
        cmp #9
        bcc @clear_eol
        lda #<str_split_more
        ldx #>str_split_more
        jsr io_puts
@clear_eol:
        jsr io_clear_eol
@done:  rts

@count:  .byte 0
@idx:    .byte 0
.endproc

; ═══════════════════════════════════════════════════════════
; io_err_load / io_err_save — print error with name
;   rp_ptr2 = name
; ═══════════════════════════════════════════════════════════
io_err_load:
        lda #<str_err_load
        ldx #>str_err_load
        jsr io_puts
        lda rp_ptr2
        ldx rp_ptr2+1
        jmp io_puts

io_err_save:
        lda #<str_err_save
        ldx #>str_err_save
        jsr io_puts
        lda rp_ptr2
        ldx rp_ptr2+1
        jmp io_puts

; ───────────────────────────────────────────────────────────
; restore_name_ptr — reload rp_ptr2 from saved name pointer
; ───────────────────────────────────────────────────────────
restore_name_ptr:
        lda rp_next_lo
        sta rp_ptr2
        lda rp_next_lo+1
        sta rp_ptr2+1
        rts

; ═══════════════════════════════════════════════════════════
; disk_done — clear_eol, newline, floppy_status, nl_clear
; ═══════════════════════════════════════════════════════════
disk_done:
        jsr io_clear_eol
        jsr newline
        jsr floppy_status
        jsr io_clear_eol
        jmp nl_clear

; ═══════════════════════════════════════════════════════════
; cmd_load — 'l' command
;   rp_ptr = args
; ═══════════════════════════════════════════════════════════
.proc cmd_load
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
        sta rp_addr+1

        jsr get_filename
        bne @have_name
        lda #<str_err_name
        ldx #>str_err_name
        jsr err_msg
        jmp nl_clear

@have_name:
        ; rp_ptr2 = name
        jsr newline

        ; save rp_ptr2 (name) since calls will clobber it
        lda rp_ptr2
        sta rp_next_lo          ; borrow for name ptr save
        lda rp_ptr2+1
        sta rp_next_lo+1

        ; check seq file
        lda rp_ptr2
        sta rp_ptr
        lda rp_ptr2+1
        sta rp_ptr+1
        jsr is_seq_file
        cmp #1
        bne @load_prg

        ; SEQ: guard unsaved before overwriting source
        jsr check_unsaved
        bcc @l_cancel

        ; SEQ: ed_load_source(name)
        lda rp_next_lo
        ldx rp_next_lo+1
        jsr ed_load_source     ; A=error
        cmp #0
        beq @seq_ok
        ; error
        jsr restore_name_ptr
        jsr io_err_load
        jmp @done
@seq_ok:
        jsr restore_name_ptr
        jsr print_seq_stats
        jsr print_load_split_warning
        jmp @done

@load_prg:
        ; PRG: disk_load_prg(name, addr) — name in disk_ptr, A/X=addr
        lda rp_next_lo
        sta disk_ptr
        lda rp_next_lo+1
        sta disk_ptr+1
        lda rp_addr
        ldx rp_addr+1
        jsr disk_load_prg      ; A/X = result (0=error, else bytes)
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
        jsr io_putdec
        lda #<str_bytes_at
        ldx #>str_bytes_at
        jsr io_puts
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
        jsr io_puthex4

@l_cancel:
        jmp nl_clear
@done:  jmp disk_done
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_write — 's' command (save/write)
;   rp_ptr = args
; ═══════════════════════════════════════════════════════════
.proc cmd_write
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
        sta rp_addr+1

        jsr get_filename
        bne @have_name
        lda #<str_err_name
        ldx #>str_err_name
        jsr err_msg
        jmp nl_clear

@have_name:
        jsr newline

        ; save name ptr
        lda rp_ptr2
        sta rp_next_lo
        lda rp_ptr2+1
        sta rp_next_lo+1

        ; check seq file
        lda rp_ptr2
        sta rp_ptr
        lda rp_ptr2+1
        sta rp_ptr+1
        jsr is_seq_file
        cmp #1
        bne @save_prg

        ; SEQ: ed_ensure_init, ed_save_source(name)
        jsr ed_ensure_init
        lda rp_next_lo
        ldx rp_next_lo+1
        jsr ed_save_source     ; A=error
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
        ; rp_ptr still points into line_buf after get_filename
        jsr skip_sp_ptr1
        ldy #0
        lda (rp_ptr),y
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

        ; disk_save_prg(name, addr, size) — name in disk_ptr, addr in _io_tmp, A/X=size
        lda rp_next_lo
        sta disk_ptr
        lda rp_next_lo+1
        sta disk_ptr+1
        lda rp_addr
        sta $FB                 ; _io_tmp lo
        lda rp_addr+1
        sta $FC                 ; _io_tmp hi
        lda rp_next_hi
        ldx rp_next_hi+1
        jsr disk_save_prg      ; A=error
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
        jsr io_putdec
        lda #<str_bytes_sp
        ldx #>str_bytes_sp
        jsr io_puts
        lda rp_addr
        ldx rp_addr+1
        jsr io_puthex4
        lda #'-'
        jsr io_putc
        ; end - 1 → A=lo, X=hi for io_puthex4
        lda rp_cnt
        sec
        sbc #1
        pha
        lda rp_cnt+1
        sbc #0
        tax
        pla
        jsr io_puthex4
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
;   rp_ptr2 = tag string, rp_addr = lo, rp_cnt = hi
;   rp_ptr = desc string
;   (Caller sets these before calling)
;
;   Actually, to simplify, pass:
;     A = inv flag
;     Store tag addr, lo, hi, desc in BSS before calling.
; We use a register-based interface:
;   Call setup: rp_save2=inv, rp_addr=lo, rp_cnt=hi
;               rp_ptr2=tag, rp_ptr=desc
; ═══════════════════════════════════════════════════════════
.proc info_line
        ; rp_save2 = inv, rp_ptr2 = tag, rp_addr = lo, rp_cnt = hi, rp_ptr = desc
        ; save io_cy screen addr into rp_next_lo for invert pass later
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_next_lo
        lda scr_hi,x
        sta rp_next_lo+1

        lda #0
        sta CUR_COL
        lda #';'
        jsr io_putc

        ; print tag
        lda rp_ptr2
        ldx rp_ptr2+1
        jsr io_puts

        ; pad tag to 4 chars: compute strlen of tag
        ; (tag is always 2-4 chars, pad with spaces)
        ldy #0
@tlen:  lda (rp_ptr2),y
        beq @tpad
        iny
        cpy #4
        bcc @tlen
@tpad:  ; pad with spaces until we've printed 4 chars total
        cpy #4
        bcs @tsp
        lda #' '
        sty rp_tmp
        jsr io_putc
        ldy rp_tmp
        iny
        bne @tpad
@tsp:   lda #' '
        jsr io_putc

        ; print lo-hi
        lda rp_addr
        ldx rp_addr+1
        jsr io_puthex4
        lda #'-'
        jsr io_putc
        lda rp_cnt
        ldx rp_cnt+1
        jsr io_puthex4
        lda #' '
        jsr io_putc

        ; print desc
        lda rp_ptr
        ldx rp_ptr+1
        jsr io_puts

        ; save col position
        lda CUR_COL
        sta rp_save             ; col

        ; copy screen pointer to ZP rp_ptr for indirect access
        lda rp_next_lo
        sta rp_ptr
        lda rp_next_lo+1
        sta rp_ptr+1

        ; inv or normal pad
        lda rp_save2
        beq @normal_pad

        ; inv: set bit 7 on AAAA-BBBB only (cols 6-14)
        ldy #6                  ; col 6 = start of address
@inv_lp:
        cpy #15                 ; col 15 = past end of BBBB
        bcs @inv_done
        lda (rp_ptr),y
        ora #$80
        sta (rp_ptr),y
        iny
        bne @inv_lp
@inv_done:

@normal_pad:
        ; fill rest with $20 (space)
        ldy rp_save
@npad:  cpy #SCREEN_WIDTH
        bcs @done
        lda #$20
        sta (rp_ptr),y
        iny
        bne @npad

@done:  jmp newline
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

        ; Append "  free" to fbuf
        tax
        ldy #0
@cpfree:lda str_free_suf,y
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
        sta rp_ptr2
        lda #>str_tag_work
        sta rp_ptr2+1
        lda #<fbuf
        sta rp_ptr
        lda #>fbuf
        sta rp_ptr+1
        jmp info_line

; ═══════════════════════════════════════════════════════════
; cmd_info — 'i' command: memory map
; ═══════════════════════════════════════════════════════════
; Helper: set up and call info_line
;   Macro-like pattern: set rp_save2, rp_ptr2, rp_addr, rp_cnt, rp_ptr
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
        sta rp_ptr
        lda rp_next_hi+1
        sta rp_ptr+1
        ldy #0
        lda (rp_ptr),y
        sta rp_ptr2
        iny
        lda (rp_ptr),y
        sta rp_ptr2+1
        iny
        lda (rp_ptr),y
        sta rp_addr
        iny
        lda (rp_ptr),y
        sta rp_addr+1
        iny
        lda (rp_ptr),y
        sta rp_cnt
        iny
        lda (rp_ptr),y
        sta rp_cnt+1
        iny
        lda (rp_ptr),y
        pha
        iny
        lda (rp_ptr),y
        sta rp_tmp2
        lda rp_next_hi
        clc
        adc #8
        sta rp_next_hi
        bcc :+
        inc rp_next_hi+1
:       pla
        sta rp_ptr
        lda rp_tmp2
        sta rp_ptr+1
        lda #0
        sta rp_save2
        jsr info_line
        dec rp_opc
        bne @lp
        rts
.endproc

.proc cmd_info
        jsr newline

        ; ── cpu ──
        lda #<info_tbl_h1
        ldx #>info_tbl_h1
        ldy #INFO_TBL_H1_ROWS
        jsr info_emit_rows

        ; ── zp 0002-007f  free (highlighted) ──
        lda #1
        sta rp_save2
        lda #<str_tag_zp
        sta rp_ptr2
        lda #>str_tag_zp
        sta rp_ptr2+1
        lda #$02
        sta rp_addr
        lda #$00
        sta rp_addr+1
        lda #$7F
        sta rp_cnt
        lda #$00
        sta rp_cnt+1
        lda #<str_i_free
        sta rp_ptr
        lda #>str_i_free
        sta rp_ptr+1
        jsr info_line

        ; ── sys(kernal zp), stk ──
        lda #<info_tbl_h2
        ldx #>info_tbl_h2
        ldy #INFO_TBL_H2_ROWS
        jsr info_emit_rows

        ; ── sys 0200-03ff  free (highlighted) ──
        lda #1
        sta rp_save2
        lda #<str_tag_sys
        sta rp_ptr2
        lda #>str_tag_sys
        sta rp_ptr2+1
        lda #<$0200
        sta rp_addr
        lda #>$0200
        sta rp_addr+1
        lda #<$03FF
        sta rp_cnt
        lda #>$03FF
        sta rp_cnt+1
        lda #<str_i_free
        sta rp_ptr
        lda #>str_i_free
        sta rp_ptr+1
        jsr info_line

        ; ── scr ──
        lda #<info_tbl_h3
        ldx #>info_tbl_h3
        ldy #INFO_TBL_H3_ROWS
        jsr info_emit_rows

        ; ── Dynamic: cse 0800-XXXX  cse runtime ──
        lda #0
        sta rp_save2
        lda #<str_tag_cse
        sta rp_ptr2
        lda #>str_tag_cse
        sta rp_ptr2+1
        jsr cse_start
        sta rp_addr
        stx rp_addr+1
        jsr cse_end
        sec
        sbc #1
        sta rp_cnt
        txa
        sbc #0
        sta rp_cnt+1
        lda #<str_cse_rt
        sta rp_ptr
        lda #>str_cse_rt
        sta rp_ptr+1
        jsr info_line

        ; ── Dynamic: free region ──
        ; free = cse_end to (src_bot-1 or BUF_END-1 if no source)
        jsr cse_end
        sta rp_addr
        stx rp_addr+1
        lda #<(BUF_END - 1)
        sta rp_cnt
        lda #>(BUF_END - 1)
        sta rp_cnt+1
        lda src_bot
        ora src_bot+1
        beq @no_src_adj
        lda src_bot
        sec
        sbc #1
        sta rp_cnt
        lda src_bot+1
        sbc #0
        sta rp_cnt+1
@no_src_adj:
        ; Skip free line if start > end
        lda rp_addr+1
        cmp rp_cnt+1
        bcc @show_free
        bne @skip_free
        lda rp_addr
        cmp rp_cnt
        bcc @show_free
        beq @show_free
        bcs @skip_free
@show_free:
        jsr free_line
@skip_free:

        ; ── Dynamic: source (skip if empty: src_bot == src_top) ──
        lda src_bot
        cmp src_top
        bne @has_src
        lda src_bot+1
        cmp src_top+1
        beq @no_src
@has_src:
        lda #0
        sta rp_save2
        lda #<str_tag_src
        sta rp_ptr2
        lda #>str_tag_src
        sta rp_ptr2+1
        lda src_bot
        sta rp_addr
        lda src_bot+1
        sta rp_addr+1
        lda src_top
        sec
        sbc #1
        sta rp_cnt
        lda src_top+1
        sbc #0
        sta rp_cnt+1
        ; Build desc: "N lines" in fbuf
        lda ed_total_lines
        ldx ed_total_lines+1
        sta rp_addr+1           ; temp save
        stx rp_save             ; temp save
        ; Save src range
        lda rp_addr
        pha
        lda rp_cnt
        pha
        lda rp_cnt+1
        pha
        ; Convert line count to decimal
        lda rp_addr+1           ; restore lo
        ldx rp_save             ; restore hi
        sta rp_addr
        stx rp_addr+1
        jsr utoa_sub            ; returns len in A
        ; Append " lines"
        tax
        ldy #0
@cp_ln: lda str_i_lines,y
        sta fbuf,x
        beq @cp_done
        inx
        iny
        bne @cp_ln
@cp_done:
        ; Restore src range
        pla
        sta rp_cnt+1
        pla
        sta rp_cnt
        pla
        sta rp_addr
        lda src_bot+1
        sta rp_addr+1
        ; Print with fbuf as desc
        lda #<fbuf
        sta rp_ptr
        lda #>fbuf
        sta rp_ptr+1
        jsr info_line
@no_src:

        ; ── Tail: io, kern ──
        lda #<info_tbl_tail
        ldx #>info_tbl_tail
        ldy #INFO_TBL_TAIL_ROWS
        jsr info_emit_rows

        jmp io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; exec_line — parse line_buf and execute command
; ═══════════════════════════════════════════════════════════
.proc exec_line
        lda #<line_buf
        sta rp_ptr
        lda #>line_buf
        sta rp_ptr+1

        jsr skip_sp_ptr1

        ; ── Parse optional AAAA: prefix → sets cur_addr ──
        jsr is_hex4_at_ptr1
        beq @no_prefix
        ldy #4
        lda (rp_ptr),y
        cmp #':'
        bne @no_prefix
        ; parse 4 hex digits
        jsr parse_hex4_ptr1
        sta cur_addr
        stx cur_addr+1
        ; skip ':'
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:
@no_prefix:
        jsr skip_sp_ptr1

        ; read command char
        ldy #0
        lda (rp_ptr),y
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
        ; rp_ptr = "" (empty args)
        ; show "ADDR:cmd" header
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
        sta rp_addr+1
        lda rp_opc
        jsr io_addr_cmd
        jsr io_clear_eol
        jmp @dispatch

@semicolon:
@clear_last:
        lda #0
        sta last_cmd
        jmp nl_clear

@have_cmd:
        ; skip command letter
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       ; skip optional space after command
        ldy #0
        lda (rp_ptr),y
        cmp #' '
        bne @save_repeat
        inc rp_ptr
        bne @save_repeat
        inc rp_ptr+1

@save_repeat:
        ; save for repeat (paging + step commands): m d . t o
        ldx #4
@sr_lp: lda @rep_chars,x
        cmp rp_opc
        beq @set_repeat
        dex
        bpl @sr_lp
        bmi @dispatch           ; not in list
@rep_chars: .byte '.', 'd', 'm', 't', 'o'
@set_repeat:
        lda rp_opc
        sta last_cmd

@dispatch:
        ; ── Table-driven dispatch ──
        ldy #0
@scan:  lda @cmd_chars,y
        beq @unknown
        cmp rp_opc
        beq @found
        iny
        bne @scan
@found: lda @cmd_lo,y
        sta rp_ptr2
        lda @cmd_hi,y
        sta rp_ptr2+1
        jmp (rp_ptr2)
@unknown:
        lda #<str_err_cmd
        ldx #>str_err_cmd
        jsr err_msg
        jmp nl_clear

; ── Handlers ──────────────────────────────────────────────
@h_dot: jmp cmd_dot
@h_d:   jmp cmd_disasm
@h_m:   jmp cmd_mem
@h_b:   jmp cmd_brk
@h_r:   jmp cmd_reg
@h_l:   jmp cmd_load
@h_s:   jmp cmd_write
@h_i:   jmp cmd_info

@h_at:  ; @ — set address
        jsr try_expr
        bcc @at_done
        lda expr_val
        sta cur_addr
        lda expr_val+1
        sta cur_addr+1
@at_done:
        jmp nl_clear

@h_plus:; + — advance address
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
        lda cur_addr
        clc
        adc expr_val
        sta cur_addr
        lda cur_addr+1
        adc expr_val+1
        sta cur_addr+1
        jmp nl_clear

@h_minus:
        ; - — retreat address
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
        lda cur_addr
        sec
        sbc expr_val
        sta cur_addr
        lda cur_addr+1
        sbc expr_val+1
        sta cur_addr+1
        jmp nl_clear

@h_j:   ; j — jump/execute
        jsr try_expr
        bcc @j_no_addr
        lda expr_val
        sta cur_addr
        lda expr_val+1
        sta cur_addr+1
@j_no_addr:
        jmp cmd_jmp

@h_g:   ; g — go (sym_lookup "main")
        lda #<str_main
        sta sym_name
        lda #>str_main
        sta sym_name+1
        jsr sym_lookup         ; C=0 found, result in sym_val
        bcs @g_no_main
        lda sym_val
        sta cur_addr
        lda sym_val+1
        sta cur_addr+1
@g_no_main:
        jmp cmd_jmp

@h_t:   ; t — step into
        lda #0
        jmp cmd_step

@h_o:   ; o — step over
        lda #1
        jmp cmd_step

@h_k:   ; k — delete source (guard unsaved)
        jsr check_unsaved
        bcc @k_cancel
        jsr newline
        lda #<str_del_src
        ldx #>str_del_src
        jsr io_puts
        jsr confirm_yn
        bne @k_no
        jsr ed_new
        lda #<str_ok
        ldx #>str_ok
        jsr io_puts
@k_no:  jsr io_clear_eol
@k_cancel:
        jmp nl_clear

@h_blk: ; B (PETSCII $C2) — block size
        jsr try_expr
        bcc @B_show             ; empty or error → just show
        lda expr_val
        ora expr_val+1
        beq @B_show
        lda expr_val
        sta block_size
        lda expr_val+1
        sta block_size+1
@B_show:
        jsr newline
        lda #<str_B_eq
        ldx #>str_B_eq
        jsr io_puts
        lda block_size
        ldx block_size+1
        jsr io_puthex4
        jsr io_clear_eol
        jmp nl_clear

@h_col: ; C (PETSCII $C3) — color
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
        sta theme_border
        ldy #1
        jsr hex_val_at_ptr1
        sta theme_bg
        ldy #2
        jsr hex_val_at_ptr1
        sta theme_fg
        jsr restore_colors
        jmp @C_show
@C_two: ; two digits: bg fg
        ldy #0
        jsr hex_val_at_ptr1
        sta theme_bg
        ldy #1
        jsr hex_val_at_ptr1
        sta theme_fg
        jsr restore_colors
        jmp @C_show
@C_one: ; one digit: fg only
        ldy #0
        jsr hex_val_at_ptr1
        sta theme_fg
        jsr restore_colors
@C_show:
        jsr newline
        lda #<str_color
        ldx #>str_color
        jsr io_puts
        lda theme_border
        jsr _hex_val_to_char
        jsr io_putc
        lda theme_bg
        jsr _hex_val_to_char
        jsr io_putc
        lda theme_fg
        jsr _hex_val_to_char
        jsr io_putc
        jsr io_clear_eol
        jmp nl_clear
@h_u:   ; u — cpu mode
        jsr skip_sp_ptr1
        ldy #0
        lda (rp_ptr),y
        cmp #'6'
        bne @u_show
        ; check q[1..3] for cpu type
        ldy #1
        lda (rp_ptr),y
        cmp #'5'
        bne @u_show
        ldy #2
        lda (rp_ptr),y
        sta rp_tmp                ; save q[2]
        ldy #3
        lda (rp_ptr),y
        sta rp_tmp2                ; save q[3]
        ; 6502: q[2]='0', q[3]='2'
        lda rp_tmp
        cmp #'0'
        bne @u_chk_10
        lda rp_tmp2
        cmp #'2'
        bne @u_show
        ; v = 0 (6502)
        lda #0
        jmp @u_try_set
@u_chk_10:
        ; 6510: q[2]='1', q[3]='0'
        cmp #'1'
        bne @u_chk_c02
        lda rp_tmp2
        cmp #'0'
        bne @u_show
        lda #1
        jmp @u_try_set
@u_chk_c02:
        ; 65c02: q[2]='c', q[3]='0'
        cmp #'c'
        bne @u_show
        lda rp_tmp2
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
        sta al_cpu
.elseif .defined(CPU_6510)
        ; CPU_CEIL=1: accept 0 or 1
        cmp #2
        bcs @u_show
        sta al_cpu
.else
        ; CPU_CEIL=0: accept 0 only
        bne @u_show
        sta al_cpu
.endif

@u_show:
        jsr newline
        lda #<str_cpu
        ldx #>str_cpu
        jsr io_puts
        lda al_cpu
        bne @u_no_star0
        lda #'*'
        jmp @u_p0
@u_no_star0:
        lda #' '
@u_p0:  jsr io_putc
.ifdef CPU_6510
        lda #<str_6510
        ldx #>str_6510
        jsr io_puts
        lda al_cpu
        cmp #1
        bne @u_no_star1
        lda #'*'
        jmp @u_p1
@u_no_star1:
        lda #' '
@u_p1:  jsr io_putc
.endif
.ifdef CMOS_SUPPORT
        lda #<str_65c02
        ldx #>str_65c02
        jsr io_puts
        lda al_cpu
        cmp #2
        bne @u_no_star2
        lda #'*'
        jmp @u_p2
@u_no_star2:
        lda #' '
@u_p2:  jsr io_putc
.endif
        jsr io_clear_eol
        jmp nl_clear
@h_a:   ; a — assemble source
        jsr newline
        lda #<str_asm_ing
        ldx #>str_asm_ing
        jsr io_puts
        jsr newline
        jsr asm_assemble       ; A/X = error count
        sta rp_cnt
        stx rp_cnt+1
        ora rp_cnt+1
        bne @a_errors
        ; success — clear stale debug context so next t/o/c cold-starts
        lda #0
        sta dbg_reason
        lda #<str_ok_colon
        ldx #>str_ok_colon
        jsr io_puts
        lda asm_size
        ldx asm_size+1
        jsr io_putdec
        lda #<str_bytes_at
        ldx #>str_bytes_at
        jsr io_puts
        lda asm_org
        ldx asm_org+1
        jsr io_puthex4
        ; sym_lookup("main") — ZP interface
        lda #<str_main
        sta sym_name
        lda #>str_main
        sta sym_name+1
        jsr sym_lookup         ; C=0 found, result in sym_val
        bcs @a_tail
        lda sym_val
        sta cur_addr
        lda sym_val+1
        sta cur_addr+1
@a_errors:
        lda #<str_semi
        ldx #>str_semi
        jsr io_puts
        lda rp_cnt
        ldx rp_cnt+1
        jsr io_putdec
        lda #<str_errors
        ldx #>str_errors
        jsr io_puts
@a_tail:
        jsr io_clear_eol
        jmp nl_clear
@h_calc:; ? — calculator
        lda rp_ptr
        sta expr_ptr
        lda rp_ptr+1
        sta expr_ptr+1
        jsr expr_eval
        sta rp_save             ; rc
        cmp #2
        jcs @calc_err

        jsr newline
        ; hex display
        lda #<str_semi
        ldx #>str_semi
        jsr io_puts
        lda expr_val+1
        bne @calc_16bit
        lda expr_val
        beq @calc_16bit         ; show 0 as 16-bit style? No, 0 < 256.
        ; Actually: if val < 256, show "  $XX"
        ; if val == 0, it's < 256 so show "  $00"
        lda #' '
        jsr io_putc
        lda #' '
        jsr io_putc
        lda #'$'
        jsr io_putc
        lda expr_val
        jsr io_puthex2
        jmp @calc_dec
@calc_16bit:
        ; "$XXXX" (or $0000)
        lda expr_val+1
        bne @calc_16bit_real
        ; val is 0, show "  $00"
        lda #' '
        jsr io_putc
        lda #' '
        jsr io_putc
        lda #'$'
        jsr io_putc
        lda expr_val
        jsr io_puthex2
        jmp @calc_dec
@calc_16bit_real:
        lda #'$'
        jsr io_putc
        lda expr_val
        ldx expr_val+1
        jsr io_puthex4

@calc_dec:
        ; decimal: "  " then 5-digit space-padded
        lda #<str_2sp
        ldx #>str_2sp
        jsr io_puts
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
        jsr io_puts
        lda expr_val
        sta rp_tmp2
        ldx #0
@bin_lp:
        asl rp_tmp2
        bcs @bin_1
        lda #'0'
        bne @bin_p
@bin_1: lda #'1'
@bin_p: stx rp_tmp
        jsr io_putc
        ldx rp_tmp
        inx
        cpx #8
        bcc @bin_lp

        ; signed decimal: "  +/-NNN"
        lda #' '
        jsr io_putc
        lda #' '
        jsr io_putc
        lda expr_val
        bpl @sign_pos
        ; negative
        lda #'-'
        jsr io_putc
        ; negate: av = 256 - val
        lda #0
        sec
        sbc expr_val
        jmp @print_signed
@sign_pos:
        lda #'+'
        jsr io_putc
        lda expr_val
@print_signed:
        ; A = absolute value (0-128)
        sta rp_tmp2                ; av
        ; hundreds
        lda rp_tmp2
        cmp #100
        bcc @tens
        lda #0
        sta rp_tmp                ; digit
@hun_lp:
        lda rp_tmp2
        sec
        sbc #100
        bcc @hun_done
        sta rp_tmp2
        inc rp_tmp
        jmp @hun_lp
@hun_done:
        lda rp_tmp
        clc
        adc #'0'
        jsr io_putc
@tens:  lda rp_tmp2
        cmp #10
        bcc @ones
        lda #0
        sta rp_tmp
@ten_lp:
        lda rp_tmp2
        sec
        sbc #10
        bcc @ten_done
        sta rp_tmp2
        inc rp_tmp
        jmp @ten_lp
@ten_done:
        lda rp_tmp
        clc
        adc #'0'
        jsr io_putc
@ones:  lda rp_tmp2
        clc
        adc #'0'
        jsr io_putc

@calc_done:
        jsr io_clear_eol
        jmp nl_clear

@calc_err:
        jsr newline
        lda #<str_err_expr
        ldx #>str_err_expr
        jsr io_puts
        jsr expr_error_str
        jsr io_puts
        jsr io_clear_eol
        jmp nl_clear
@h_quit:; Q (PETSCII $D1) — quit (guard unsaved)
        jsr check_unsaved
        bcc @q_cancel
        jsr newline
        lda #<str_quit
        ldx #>str_quit
        jsr io_puts
        ; flush keyboard buffer
@q_flush:
        jsr io_kbhit            ; Z set by lda $C6 inside
        beq @q_wait
        jsr io_getc
        jmp @q_flush
@q_wait:
        jsr confirm_yn
        bne @q_no
        lda #ST_STOP
        sta state
@q_no:  jsr newline
        lda state
        cmp #ST_STOP
        beq @q_ret
        jsr io_clear_eol
@q_ret: rts
@q_cancel:
        jmp nl_clear
@h_dir: ; $ — directory
        jsr skip_sp_ptr1
        ldy #0
        lda (rp_ptr),y
        cmp #'0'
        bcc @dir_go
        cmp #'9'+1
        bcs @dir_go
        ; parse decimal device number
        lda #0
        sta rp_tmp2                ; dev
@dev_lp:
        ldy #0
        lda (rp_ptr),y
        cmp #'0'
        bcc @dev_done
        cmp #'9'+1
        bcs @dev_done
        sec
        sbc #'0'
        pha
        ; dev = dev * 10 + digit
        lda rp_tmp2
        asl                     ; *2
        sta rp_tmp
        asl                     ; *4
        asl                     ; *8
        clc
        adc rp_tmp                ; *10
        sta rp_tmp2
        pla
        clc
        adc rp_tmp2
        sta rp_tmp2
        inc rp_ptr
        bne @dev_lp
        inc rp_ptr+1
        jmp @dev_lp
@dev_done:
        ; validate: 4-30
        lda rp_tmp2
        cmp #4
        bcc @dir_go
        cmp #31
        bcs @dir_go
        sta cur_device
@dir_go:
        jsr newline
        lda cur_device
        jsr list_directory
        jmp nl_clear
@h_x:   ; x — clear screen
        jsr reset_screen
        jmp io_clear_eol

@h_c:   ; c — continue debugger
        lda dbg_reason
        bne @c_has_ctx
        lda #<str_no_break
        ldx #>str_no_break
        jsr err_msg
        jmp nl_clear
@c_has_ctx:
        ; delete hit breakpoint before continuing
        lda dbg_bp_hit
        cmp #$FF
        beq @c_enter
        jsr dbg_bp_del
@c_enter:
        jsr run_user
        ; If dbg_reason=0, user code returned via RTS (no BRK fired)
        lda dbg_reason
        bne @c_broke
        ; Normal completion — clear debug context
        lda #0
        sta last_cmd            ; no repeat
        jsr restore_colors
        jmp nl_clear
@c_broke:
        jmp show_break_result

; ── Command dispatch table (parallel arrays) ──
@cmd_chars:
        .byte '.', 'd', 'm', 'b', 'r', 'l', 's', 'i'
        .byte '@', '+', '-', 'j', 'g', 't', 'o', 'k'
        .byte $C2, $C3, 'u', 'a', '?', $D1, '$', 'x'
        .byte 'c'
        .byte 0                 ; sentinel
@cmd_lo:
        .byte <@h_dot, <@h_d, <@h_m, <@h_b, <@h_r, <@h_l, <@h_s, <@h_i
        .byte <@h_at, <@h_plus, <@h_minus, <@h_j, <@h_g, <@h_t, <@h_o, <@h_k
        .byte <@h_blk, <@h_col, <@h_u, <@h_a, <@h_calc, <@h_quit, <@h_dir, <@h_x
        .byte <@h_c
@cmd_hi:
        .byte >@h_dot, >@h_d, >@h_m, >@h_b, >@h_r, >@h_l, >@h_s, >@h_i
        .byte >@h_at, >@h_plus, >@h_minus, >@h_j, >@h_g, >@h_t, >@h_o, >@h_k
        .byte >@h_blk, >@h_col, >@h_u, >@h_a, >@h_calc, >@h_quit, >@h_dir, >@h_x
        .byte >@h_c
.endproc
