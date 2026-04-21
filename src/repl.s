; repl.s — REPL command line interface
;
; The screen IS the command buffer.  Press RETURN on any line
; to execute it.  AAAA:cmd [args] for addressed commands,
; cmd [args] for bare commands.  ';' ends parsing.

        .setcpu "6502"
        .macpack longbranch
        .include "macros.inc"

; ── Exports ────────────────────────────────────────────────
        .export exec_line, read_line, show_prompt, cmd_info
        .export cur_addr, block_size
        .export line_buf, last_cmd, rp_dis_bp

; ── Imports: log.s ─────────────────────────────────────────
        .import log_line, log_open, log_close
        .import log_err, log_warn, log_info
        ; log_err_eol / log_close_eol retired: callers use log_err /
        ; log_close directly (trailing io_clear_eol was redundant —
        ; show_prompt overwrites the new row; leading newline in the
        ; err variant wasted a visual row).
        .import seg_line, prg_line, free_line
        .import info_line, info_line_head, info_line_tail
        .import puts_imm

; ── Imports: zp.s ──────────────────────────────────────────
        .importzp rp_addr, rp_cnt, rp_save, rp_save2
        .importzp rp_next_lo, _info_mode
        .importzp cur_device, cur_project_name

; ── Imports: cse_io.s ──────────────────────────────────────
        .import io_putc, io_repc, io_puts, scr_to_pet
        .import io_puthex4, io_puthex2, io_putdec, io_putdec_pd
        .import io_utoa, dec_buf
        .import io_clear_eol
        .import io_getc, io_kbhit, io_sync
        .import cursor_show, cursor_hide
        .import scr_lo, scr_hi

; ── Imports: screen.s ──────────────────────────────────────
        .import newline, restore_colors, reset_screen, vic_reset
        .import theme_border, theme_bg, theme_fg

; hex_val, is_hex, hex_val_to_char are now local (below)

; ── Imports: assembler / disassembler ──────────────────────
        .import asm_line, asm_expr_err
        .import dasm_insn, dasm_buf
        .import asm_assemble, seg_print_save

; ── Imports: debugger ──────────────────────────────────────
        .import dbg_step_clear
        .import dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .import dbg_bp_count
        .import bp_table, step_bp
        .import __CODE_RUN__
        .importzp dbg_reason            ; Phase 21: moved to zp.s
        .import dbg_bp_hit
        .import brk_pc, brk_stub
        .import reg_a, reg_x, reg_y, reg_sp, reg_p
        .import userland_zp_buf
        .importzp ZP_SAVE_LO, ZP_SAVE_LEN       ; equates (zero-page range constants)
        .import kernal_bank_out, kernal_bank_in
        .import oplen_tbl
        .import step_state, step_remaining
        .import step_next_pc, arm_step_bp
        .import step_next_lo, step_next_hi

; ── Imports: main.s (kernel→userland dispatch) ───────────────
        .import run_user_pending, stop_cooldown
        .import cse_refresh, cse_end_debug
        .import end_debug_body
        .importzp warm_cont             ; Phase 21: moved to zp.s
        ; MODE_NONE, MODE_JUMP, MODE_RESUME constants are defined in
        ; main.s; redefine here (ca65 doesn't import equates).
MODE_NONE   = 0
MODE_JUMP   = 1
MODE_RESUME = 2

; ── Imports: debugger step modes (match debugger.s values) ───
STEP_NONE = 0
STEP_INTO = 1
STEP_OVER = 2

; ── Exports: post-run cleanup (called from main_loop_top) ────
        .export post_run_cleanup
        .export hygiene_after_userland

; ── Imports: expression parser ─────────────────────────────
        .import expr_eval, expr_error_str
        .importzp expr_ptr, expr_val

; ── Imports: symbol table ──────────────────────────────────
        .import sym_lookup
        .importzp sym_name, sym_val

;── Imports: disk I/O ──────────────────────────────────────
        .import floppy_status, floppy_read_status, fl_buf
        .import list_directory
        .import disk_load_prg, disk_save_prg

; ── Imports: editor ────────────────────────────────────────
        .import ed_save_source, ed_load_source
        .import ed_save_bytes, ed_save_lines
        .import ed_ensure_init, ed_new
        .importzp ed_dirty              ; Phase 21: moved to zp.s
        .import ed_total_lines
        .import ed_read_rewind, ed_read_byte
        .importzp buf_base

; ── Imports: memory info ───────────────────────────────────
        .import cse_start, cse_end, cse_zp_end
        .import src_top, src_bot

; ── Imports: global state ──────────────────────────────────
        .importzp state                 ; Phase 21: moved to zp.s
        .importzp asm_cpu

; ── Imports: strings.s ────────────────────────────────────
        .import str_flag_ch, str_bp_pfx, str_3sp, str_2sp, str_brk
        .import str_at, str_nmi, str_bp_clr, str_deleted
        .import str_rts, str_stk_warn, str_debug, str_qynq
        .import str_syntax, str_bad_val, str_full, str_cmd
        .import str_no_name, str_range, str_fail, str_too_big
        .import str_expr, str_no_ctx
        .import str_r_pc, str_a, str_x, str_y, str_s
        .import str_lines, str_bytes, str_long
        .import str_unsaved, str_ok, str_blk_eq
        .import str_del_src, str_quit, str_load
        .import str_init, str_end_dbg, str_asm
        .import str_color, str_cpu
        .import str_asm_ing, str_load_pfx, str_save_pfx, str_dots
        .import s_save_default
        .import str_errors, str_dashes, str_colon_sp, str_pct
        .import str_ioport, str_stack, str_kernal, str_screen
        .import str_cse_rt, str_io, str_main
        .import str_tag_cpu, str_tag_zp, str_tag_stk, str_tag_sys
        .import str_tag_scr, str_tag_cse, str_tag_work, str_free_suf, str_tag_prg
        .import str_tag_src, str_tag_low, str_tag_io
        .import str_tag_rom, str_banked
        .import dec_pow_lo, dec_pow_hi
.ifdef CPU_6510
        .import str_6510
.endif
.ifdef CMOS_SUPPORT
        .import str_65c02
.endif

; ── Imports: runtime ZP ────────────────────────────────────
        .importzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2
        .importzp asm_pc, asm_out
        .importzp disk_ptr, _io_tmp

; ── Constants ──────────────────────────────────────────────
SCREEN        = $0400
SCREEN_WIDTH  = 40
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
;   rp_next_lo/hi (2+2) — secondary 16-bit scratch pair; save/load
;                          use them for name pointers and addresses
; ═══════════════════════════════════════════════════════════

; ── BSS ────────────────────────────────────────────────────
; Variables formerly in DATA are now BSS; initialized by main.s
; startup or by first use.  BSS is zeroed at boot.
.segment "BSS"

cur_addr:      .res 2          ; current memory address (init by splash)
; cur_device moved to zp.s (Phase 21 Move 4)
last_cmd:       .res 1          ; last command byte
block_size:     .res 2          ; block size for I/O (init by main.s)
; cur_project_name moved to zp.s (Phase 21.1 Move 6a)
disk_name_buf:     .res FILENAME_MAX + 2   ; composed disk name (stem + optional ".")
_verbatim_type:    .res 1          ; 0 / 's' / 'p' from strip_and_classify
_arg_count:        .res 1          ; 0, 1, or 2 — numeric args in last parse

line_buf:       .res 42
dot_asm_buf:    .res 24
; rp_addr / rp_cnt / rp_save / rp_save2 / rp_next_lo moved to zp.s
; (Phase 21.1 Move 3B).
rp_next_hi:     .res 2          ; 16-bit scratch pair (rp_next_hi: BSS only)
rp_opc:         .res 1          ; saved opcode (cmd_dot / emit_hex_cols)
rp_dis_bp:      .res 1          ; cmd_step: disabled bp slot*4 ($FF=none)
rp_hexbuf:      .res 3          ; cmd_dot hex byte parse

zp_stage_buf:   .res 8          ; staging buffer for the user-ZP
                                ; read redirect — `m` dump (8 B) and
                                ; `.` disasm (3 B).  See repl.md
                                ; § User-ZP view.

; ── RODATA ─────────────────────────────────────────────────
.segment "RODATA"

; cpu parse helpers: pair chars after "65" -> cpu id
cpu_pair_tbl:    .byte '0','2',0,  '1','0',1,  'c','0',2
cpu_mask_bits:   .byte 1,2,4

; ── info tables: 8 bytes per row: tag(2) lo(2) hi(2) desc(2) ──
; These stay in repl.s because INFO_TBL_*_ROWS are compile-time
; constants computed from segment arithmetic (can't be imported).

info_tbl_h1:
        .addr str_tag_cpu,  $0000, $0001, str_ioport         ; cpu  0000-0001
INFO_TBL_H1_ROWS = (* - info_tbl_h1) / 8

info_tbl_h2:
        .addr str_tag_sys,  $0080, $00FF, str_kernal       ; sys  0080-00ff  kernal zp
        .addr str_tag_stk,  $0100, $01FF, str_stack           ; stk  0100-01ff  6502 stack
INFO_TBL_H2_ROWS = (* - info_tbl_h2) / 8

info_tbl_lo:
        .addr str_tag_sys,  $0200, $02A6, str_kernal         ; sys  0200-02a6  kernal
INFO_TBL_LO_ROWS = (* - info_tbl_lo) / 8

info_tbl_lo2:
        .addr str_tag_sys,  $0300, $0333, str_kernal         ; sys  0300-0333  kernal
INFO_TBL_LO2_ROWS = (* - info_tbl_lo2) / 8

info_tbl_h3:
        .addr str_tag_scr,  $0400, $07FF, str_screen          ; scr  0400-07ff  screen+sprites
INFO_TBL_H3_ROWS = (* - info_tbl_h3) / 8

info_tbl_tail:
        .addr str_tag_io,   $D000, $DFFF, str_io            ; io   d000-dfff  io
        .addr str_tag_cse,  $E000, $F8D9, str_banked         ; cse  e000-f8d9  banked
        .addr str_tag_rom,  $F8DA, $FFFF, str_kernal         ; rom  f8da-ffff  kernal
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


; puts_imm moved to log.s (Phase 21 Move 3).

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

; Logging API (log_open / log_close / log_line / log_err / log_warn /
; log_info) moved to log.s in Phase 21 Move 3.  repl.s imports them.
; log.inc still provides the LOG_ERR/WARN/INFO level constants.
.include "log.inc"

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
; query_user — prompt the user before a destructive action.
;   In:  A/X = action stem string (e.g. "del src")
;   Out: A = keypress byte; C=1 yes, C=0 cancelled
;
; Prints ";!<stem>? y/n " at LOG_WARN, then waits for y/n.  The
; "? y/n " trailer is shared (str_qynq) so each action string is
; just the verb stem.  Any state-based warnings (unsaved, debug)
; are the caller's job and must be emitted BEFORE calling
; query_user (see warn_if_* helpers).
; ───────────────────────────────────────────────────────────
query_user:
        pha                     ; save caller's stem ptr lo
        txa                     ; across log_open (clobbers A/X)
        pha
        ; No leading newline: caller is responsible for cursor row.
        ; After warn_if_*, log_close has already advanced cursor to
        ; a fresh row; for direct calls from handler entry, the
        ; KERNAL's RETURN-induced newline already did that.  Adding
        ; a newline here would leave a blank row between the warning
        ; and the query prompt.
        ldy #LOG_WARN
        jsr log_open
        pla                     ; hi
        tax
        pla                     ; lo
        jsr io_puts
        puts str_qynq           ; shared "? y/n " trailer
        jsr confirm_yn
        beq @yes
        jsr io_clear_eol
        clc
        rts
@yes:   sec
        rts

; ───────────────────────────────────────────────────────────
; warn_if_unsaved — emit ";!unsaved" at LOG_WARN when editor has
; uncommitted edits.  No-op when ed_dirty == 0.
;   Clobbers A, X, Y.
; ───────────────────────────────────────────────────────────
warn_if_unsaved:
        lda ed_dirty
        beq @done
        lda #<str_unsaved
        ldx #>str_unsaved
        jmp log_warn            ; tail-call
@done:  rts

; ───────────────────────────────────────────────────────────
; warn_if_debug — emit ";!debug" at LOG_WARN when a debug session
; is active.  No-op when dbg_reason == 0.
;   Clobbers A, X, Y.
; ───────────────────────────────────────────────────────────
warn_if_debug:
        lda dbg_reason
        beq @done
        lda #<str_debug
        ldx #>str_debug
        jmp log_warn            ; tail-call
@done:  rts

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
; skip_peek_ptr1 — skip spaces then load first non-space char
;   Returns: A = first non-space byte at (rp_ptr), Y = 0.
; ───────────────────────────────────────────────────────────
skip_peek_ptr1:
        jsr skip_sp_ptr1
        ldy #0
        lda (rp_ptr),y
        rts

; ───────────────────────────────────────────────────────────
; load_curaddr — copy cur_addr to rp_addr
; ───────────────────────────────────────────────────────────
load_curaddr:
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
        sta rp_addr+1
        rts

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
        cmp #$10                ; valid nibbles are 0..15, invalid is $FF
        lda #0
        adc #0                  ; A=1 if invalid, A=0 if valid
        eor #1                  ; A=1 if valid, A=0 if invalid; Z follows A
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
; _require_eoi_or_err — reject trailing garbage after a parse
;
; Checks the region starting at (rp_ptr),Y for EOI: only whitespace
; (space $20 / shifted-space $A0), then NUL or ';' is acceptable.
; Anything else is a trailing-garbage syntax error.
;
; On clean EOI: normal RTS (rp_ptr, Y unchanged on return).
; On garbage:   POPS the caller's return address from the stack and
;               tail-calls log_err with str_syntax — control flows
;               back to exec_line's caller, skipping the remainder
;               of the caller's command handler body.
;
; This is the "pop-trick error escape" pattern catalogued in
; optimization.md § 36.  It saves ~2 B per call site (no `bcs
; <abort>` branch needed at the caller) but imposes a strict
; stack-shape contract on callers — see below.
;
; Used by commands that take "exactly one argument and nothing else"
; (? @ B C, t/o, and any future one-shot).  See
; doc/modules/repl.md § Single-expression command contract.
;
; Stack contract: the caller must be exactly one jsr deep from
; exec_line's invocation point — i.e. dispatched directly via
; exec_line's `jmp (rp_ptr2)` or via a tail-jmp trampoline that
; preserves the same stack shape (e.g. `lda #0 / jmp cmd_step`
; from @h_t).  The pla/pla discards ONE return address and relies
; on log_err's RTS popping exec_line's caller.  A NESTED sub-proc
; (caller of caller of exec_line) MUST NOT call this helper —
; would discard the wrong frame.
; ═══════════════════════════════════════════════════════════
_require_eoi_or_err:
@lp:    lda (rp_ptr),y
        beq @ok
        cmp #';'
        beq @ok
        cmp #' '
        beq @adv
        cmp #$a0                ; shifted space / tab
        bne @err
@adv:   iny
        bne @lp
@ok:    rts
@err:   pla                     ; discard caller return lo
        pla                     ; discard caller return hi
        lda #<str_syntax
        ldx #>str_syntax
        jmp log_err

; ═══════════════════════════════════════════════════════════
; try_expr — evaluate expression at rp_ptr
;   C=1: success (result in expr_val, rp_ptr advanced)
;   C=0: empty or error (error printed)
; ═══════════════════════════════════════════════════════════
.proc try_expr
        jsr skip_peek_ptr1
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
        ldy #LOG_ERR
        jsr log_open        ; ";?"
        puts str_expr
        jsr expr_error_str
        jsr io_puts             ; "undef main" etc.
        jsr log_close
        clc
        rts
@empty: clc
        rts
.endproc

; ───────────────────────────────────────────────────────────
; expr_set_curaddr — try_expr, and on success copy expr_val to cur_addr
;   Returns C=1 on success, C=0 on empty/error.
; ───────────────────────────────────────────────────────────
.proc expr_set_curaddr
        jsr try_expr
        bcc @r
        lda expr_val
        sta cur_addr
        lda expr_val+1
        sta cur_addr+1
@r:     rts
.endproc

; ───────────────────────────────────────────────────────────
; expr_or_blocksize — expr_val := expression or block_size if empty/zero
;   Returns with expr_val populated.
; ───────────────────────────────────────────────────────────
.proc expr_or_blocksize
        jsr try_expr
        bcc @blk
        lda expr_val
        ora expr_val+1
        bne @r
@blk:   lda block_size
        sta expr_val
        lda block_size+1
        sta expr_val+1
@r:     rts
.endproc

; ───────────────────────────────────────────────────────────
; show_block_size — emit current B=XXXX setting
; ───────────────────────────────────────────────────────────
.proc show_block_size
        ldy #LOG_INFO
        jsr log_open
        puts str_blk_eq
        lda block_size
        ldx block_size+1
        jsr io_puthex4
        jmp log_close
.endproc

; ───────────────────────────────────────────────────────────
; bp_open_slot — open "; bp N" log prefix for slot A (0-based)
; ───────────────────────────────────────────────────────────
.proc bp_open_slot
        clc
        adc #'1'
        pha
        ldy #LOG_INFO
        jsr log_open
        puts str_bp_pfx
        pla
        jmp io_putc
.endproc

; ───────────────────────────────────────────────────────────
; sym_set_curaddr — sym_lookup(sym_name), copy sym_val to cur_addr on hit
;   Returns C=0 if symbol found and cur_addr updated, C=1 otherwise.
; ───────────────────────────────────────────────────────────
.proc sym_set_curaddr
        jsr sym_lookup
        bcs @r
        lda sym_val
        sta cur_addr
        lda sym_val+1
        sta cur_addr+1
@r:     rts
.endproc

; ───────────────────────────────────────────────────────────
; show_theme_colors — emit current border/bg/fg color triplet
; ───────────────────────────────────────────────────────────
.proc show_theme_colors
        ldy #LOG_INFO
        jsr log_open
        puts str_color
        lda theme_border
        jsr _hex_val_to_char
        jsr io_putc
        lda theme_bg
        jsr _hex_val_to_char
        jsr io_putc
        lda theme_fg
        jsr _hex_val_to_char
        jsr io_putc
        jmp log_close
.endproc

; ───────────────────────────────────────────────────────────
; calc_put_u8_hex — print small-value form "  $XX" from expr_val
; ───────────────────────────────────────────────────────────
.proc calc_put_u8_hex
        puts str_2sp
        lda #'$'
        jsr io_putc
        lda expr_val
        jmp io_puthex2
.endproc

; ═══════════════════════════════════════════════════════════
; read_line — read current screen row into line_buf
;
; In:
;   CUR_ROW   = screen row to read
;
; Out:
;   line_buf  = NUL-terminated text, trailing spaces trimmed
;
; Notes:
; - Reverse-video bit is stripped.
; - CSE uses the lower/upper character set:
;     $00-$1F = lowercase/symbol block
;     $20-$3F = space, digits, punctuation
;     $40-$5F = uppercase/symbol block
;     $60-$7F = special-character / graphics block
; - For line-buffer text we normalize only the first block:
;     screen $00-$1F -> text $40-$5F
;   Everything else is kept as-is after stripping bit 7.
; ═══════════════════════════════════════════════════════════
.proc read_line
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_ptr
        lda scr_hi,x
        sta rp_ptr+1

        ldy #0
@loop:  lda (rp_ptr),y
        and #$7F                ; strip reverse-video bit
        jsr scr_to_pet          ; screen code → PETSCII
        sta line_buf,y
        iny
        cpy #SCREEN_WIDTH
        bcc @loop

        ; trim trailing spaces, then NUL-terminate
        ldy #SCREEN_WIDTH
@trim:  dey
        bmi @zero               ; line was all spaces
        lda line_buf,y
        cmp #' '
        beq @trim
        iny                     ; point past last non-space
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
; zp_stage_prep — user-ZP read redirect for m/. displays.
;
; Stages 8 bytes from (rp_ptr2) into zp_stage_buf, substituting
; userland_zp_buf[addr - ZP_SAVE_LO] for any offset whose
; effective address (rp_ptr2 + Y) falls in [ZP_SAVE_LO,
; ZP_SAVE_LO + ZP_SAVE_LEN).  Bytes outside that range fall
; through to live (rp_ptr2),y reads.  On completion, rp_ptr2 is
; repointed at zp_stage_buf so downstream consumers ((rp_ptr2),y
; loads by emit_hex_cols, dasm_insn, the compare loop in cmd_dot)
; see the staged image transparently.
;
; The redirect is unconditional — `m $10` always means "user ZP
; $10", never CSE's live $10.  userland_zp_buf is always valid:
; seeded by dbg_init at cold boot ($00=$2F, $01=$36, rest zero),
; refreshed on every userland → kernel transition.  CSE's own
; live ZP within the save range is an implementation detail that
; must not leak through the inspection tool.
;
; Range gating assumes the save range lies entirely within page 0
; (ZP_SAVE_LO + ZP_SAVE_LEN ≤ $100).  The lower-bound test is
; omitted because ZP_SAVE_LO = 0 today; if that ever changes, add
; a `cmp #ZP_SAVE_LO / bcc @live` before the upper-bound check.
;
; In:  rp_ptr2 = source base address.
; Out: zp_stage_buf populated; rp_ptr2 := zp_stage_buf when the
;      source was in page 0 (hi = 0).  Callers that branch on
;      page-0-ness must inspect rp_ptr2+1 themselves.
; Clobbers: A, X, Y.
zp_stage_prep_addr:                     ; convenience entry: load
        lda rp_addr                     ; rp_ptr2 from rp_addr then
        sta rp_ptr2                     ; fall through into the
        lda rp_addr+1                   ; main zp_stage_prep body.
        sta rp_ptr2+1
        ; fall through
.proc zp_stage_prep
.ifdef INTROSPECT
        ; Introspection build: no redirect.  rp_ptr2 already points
        ; at the live address; downstream consumers read live ZP.
        rts
.else
        lda rp_ptr2+1                   ; hi != 0 → whole 8-byte
        bne @done                       ; range is outside page 0
        ldy #0
@lp:    tya
        clc
        adc rp_ptr2                     ; effective.lo
        bcs @live                       ; wrap past $FF → live
        cmp #<(ZP_SAVE_LO + ZP_SAVE_LEN)
        bcs @live                       ; addr ≥ save end → live
        tax
        lda userland_zp_buf - ZP_SAVE_LO,x
        bcc @stg                        ; C=0 here (bcs-not-taken)
@live:  lda (rp_ptr2),y
@stg:   sta zp_stage_buf,y
        iny
        cpy #8
        bcc @lp
        lda #<zp_stage_buf
        sta rp_ptr2
        lda #>zp_stage_buf
        sta rp_ptr2+1
@done:  rts
.endif
.endproc

; ═══════════════════════════════════════════════════════════
; zp_poke — user-ZP write redirect for m/. edits.
;
; Writes A to the effective address (rp_ptr2 + Y), substituting
; userland_zp_buf[addr - ZP_SAVE_LO] when the effective address
; is in [ZP_SAVE_LO, ZP_SAVE_LO + ZP_SAVE_LEN).  Otherwise stores
; through (rp_ptr2),y as normal.  Unconditional — user-ZP edits
; always land in userland_zp_buf so they're the image `c` restores
; on the next userland entry.  See repl.md § User-ZP view.
;
; Same range assumptions as zp_stage_prep: save range in page 0,
; ZP_SAVE_LO = 0 (lower-bound check omitted).
;
; In:  A = byte, rp_ptr2 = base, Y = offset.
; Clobbers: X (A, Y, rp_ptr2 preserved).
.proc zp_poke
.ifdef INTROSPECT
        ; Introspection build: no redirect.  Direct live write.
        sta (rp_ptr2),y
        rts
.else
        pha
        lda rp_ptr2+1
        bne @pop
        tya
        clc
        adc rp_ptr2
        bcs @pop                        ; wrap past $FF
        cmp #<(ZP_SAVE_LO + ZP_SAVE_LEN)
        bcs @pop                        ; addr ≥ save end → live
        tax
        pla
        sta userland_zp_buf - ZP_SAVE_LO,x
        rts
@pop:   pla
        sta (rp_ptr2),y
        rts
.endif
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
        ; Stage bytes through the user-ZP redirect (no-op outside
        ; a break context).  rp_ptr2 ends up pointing at either
        ; zp_stage_buf or rp_addr — dasm_insn and emit_hex_cols
        ; both read from rp_ptr2 uniformly.
        jsr zp_stage_prep_addr

        ; dasm_insn owns its KERNAL banking — we just call it.
        lda rp_ptr2
        ldx rp_ptr2+1
        jsr dasm_insn
        pha                     ; save olen for later use

        lda #'.'
        jsr io_addr_cmd
        lda #' '
        jsr io_putc

        ; emit_hex_cols(rp_ptr2 already set, olen, 3)
        pla                     ; olen
        pha
        sta rp_save             ; count
        lda #3
        sta rp_save2            ; max
        jsr emit_hex_cols

        puts str_2sp
        puts dasm_buf
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

        jsr zp_stage_prep_addr  ; user-ZP redirect (see repl.md)

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
        puts str_r_pc
        lda brk_pc
        ldx brk_pc+1
        jsr io_puthex4
        puts str_a
        lda reg_a
        jsr io_puthex2
        puts str_x
        lda reg_x
        jsr io_puthex2
        puts str_y
        lda reg_y
        jsr io_puthex2
        puts str_s
        lda reg_sp
        jsr io_puthex2
        lda #' '
        jsr io_putc

        lda reg_p
        sta rp_tmp2
        ldx #0
@fl:    lda str_flag_ch,x       ; lowercase PETSCII ("nv-bdizc")
        asl rp_tmp2
        bcc @fp                 ; bit=0 → print as-is (lowercase)
        ora #$80                ; bit=1 → uppercase ($C0-$DF canonical)
                                ; No '-' guard needed: cse_brk_handler's
                                ; P mask (#$DF) and cse_nmi_handler's
                                ; (#$CF) both clear bit 5 of reg_p, so
                                ; slot 2's carry-in here is always 0
                                ; and this path is unreachable for the
                                ; '-' slot.
@fp:    stx rp_tmp
        jsr io_putc
        ldx rp_tmp
        inx
        cpx #8
        bcc @fl
        jmp io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; show_break_result — status msg header + regs + disasm
;
; Unified return-to-REPL path after running user code.  Prints one
; line of the form "; TAG[ N] at $PC" followed by the register dump
; and a disassembly at brk_pc.  TAG depends on dbg_reason and, for
; clean exits, an opcode peek at brk_pc:
;
;   dbg_reason=DBG_NMI → "; nmi at $PC"
;   dbg_reason=DBG_BRK → "; brk at $PC"          (unplanned / step end)
;                        "; brk N at $PC"        (user bp slot N+1 hit)
;   dbg_reason=0       → "; brk at $PC"          (opcode at PC is $00)
;                        "; rts at $PC"          (PC == brk_stub, or
;                                                 opcode is $60 RTS /
;                                                 $40 RTI, or default)
;
; Separator newline above the header only if the cursor isn't
; already at column 0 (user CHROUT may have left the row padded).
;
; Colours/VIC state are already restored by hygiene_after_userland
; in handler_finalize (called before main_loop_top → post_run_cleanup
; → here), so no restore_colors at entry.
; ═══════════════════════════════════════════════════════════

; ── peek_brk_opcode — read the opcode byte at brk_pc into A ───
; Used by show_break_result's classification (brk vs rts) and by
; post_run_cleanup's last_cmd-clear-on-RTS/RTI check.
; Clobbers: A, Y, rp_ptr.
peek_brk_opcode:
        lda brk_pc
        sta rp_ptr
        lda brk_pc+1
        sta rp_ptr+1
        ldy #0
        lda (rp_ptr),y
        rts

.proc show_break_result
        ; log_open auto-advances if cursor is mid-line (userland
        ; return may leave it anywhere); no manual newline needed.

        ; Special case: clean RTS through our brk_stub sentinel
        ; (dbg_reason=0 and brk_pc == brk_stub).  The break PC is
        ; the sentinel itself — not a user-meaningful address — so
        ; print just "; rts" and reset brk_pc to cur_addr (the
        ; pre-j entry point, untouched during the run).  emit_reg
        ; then shows PC at the entry, and the follow-up disasm
        ; sits on the user's code, not on brk_stub.
        lda dbg_reason
        bne @tag_select
        lda brk_pc
        cmp #<brk_stub
        bne @tag_select
        lda brk_pc+1
        cmp #>brk_stub
        bne @tag_select
        ; Reset brk_pc to cur_addr.
        lda cur_addr
        sta brk_pc
        lda cur_addr+1
        sta brk_pc+1
        ldy #' '
        jsr log_open
        puts str_rts
        jsr io_clear_eol
        jmp @regs_keep_addr

@tag_select:
        ; Decide tag string (rp_ptr2 = ptr to zero-terminated tag).
        lda dbg_reason
        cmp #2
        bne @not_nmi
        lda #<str_nmi
        ldx #>str_nmi
        jmp @have_tag
@not_nmi:
        cmp #1
        beq @is_brk
        ; dbg_reason = 0 (clean): classify by opcode at brk_pc.
        ; $00 BRK → brk; otherwise ($60 RTS, $40 RTI, default) → rts.
        jsr peek_brk_opcode
        cmp #$00
        beq @is_brk
        lda #<str_rts
        ldx #>str_rts
        jmp @have_tag
@is_brk:
        lda #<str_brk
        ldx #>str_brk

@have_tag:
        sta rp_ptr2
        stx rp_ptr2+1

        ; "; " + tag
        ldy #' '
        jsr log_open
        lda rp_ptr2
        ldx rp_ptr2+1
        jsr io_puts

        ; Append " N" if this is a user bp-slot hit.
        lda dbg_reason
        cmp #1
        bne @no_slot
        lda dbg_bp_hit
        cmp #$FF
        beq @no_slot
        lda #' '
        jsr io_putc
        lda dbg_bp_hit
        clc
        adc #'1'
        jsr io_putc
@no_slot:

        ; " at $PC"
        puts str_at
        lda brk_pc
        ldx brk_pc+1
        jsr io_puthex4
        jsr io_clear_eol

        ; Regs + disasm at brk_pc (also updates cur_addr).
        jsr newline
        jsr emit_reg
        jsr newline
        lda brk_pc
        sta cur_addr
        lda brk_pc+1
        sta cur_addr+1
        jmp @disasm

@regs_keep_addr:
        ; Regs + disasm at cur_addr (unchanged — user's entry PC).
        jsr newline
        jsr emit_reg
        jsr newline

@disasm:
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
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
        ; asm_line(buf) — caller sets asm_pc/asm_out, buf in A/X.
        ; asm_line owns its own KERNAL banking; we just call it.
        lda rp_addr
        sta asm_pc
        sta asm_out
        lda rp_addr+1
        sta asm_pc+1
        sta asm_out+1
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
        jsr load_curaddr

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

        ; Stage bytes through the user-ZP redirect so the compare
        ; reflects what the user would see (userland_zp_buf image
        ; when a break is active, live memory otherwise).
        jsr zp_stage_prep_addr

        ; Check if bytes changed vs the staged image
        ldy #0
        sty rp_save             ; changed flag
@cmp:   cpy rp_cnt
        bcs @cmp_done
        lda (rp_ptr2),y
        cmp rp_hexbuf,y
        beq @cmatch
        lda #1
        sta rp_save
@cmatch:
        iny
        bne @cmp

@cmp_done:
        lda rp_save
        beq @try_mne            ; not changed → try mnemonic

        ; Write changed bytes (user-ZP aware).  rp_stage_prep above
        ; may have repointed rp_ptr2 at zp_stage_buf; reset to
        ; rp_addr so zp_poke's redirect check sees the real address.
        lda rp_addr
        sta rp_ptr2
        lda rp_addr+1
        sta rp_ptr2+1
        ldy #0
@write: cpy rp_cnt
        bcs @show
        lda rp_hexbuf,y
        jsr zp_poke             ; Y=offset, A=byte, rp_ptr2=base
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
        jeq io_clear_eol        ; nbytes == 0 → clear; else skip
        rts

@try_mne:
        ; Input-shape gate (Escape Analysis 2026-04-20):
        ;   empty / comment → silent redisplay (@show, valid)
        ;   a-z letter      → dot_assemble path
        ;   anything else   → syntax error
        ; Pre-fix, both "empty" and "other" fell through to @show,
        ; silently swallowing garbage like `. .`, `. ,`, `. $`.
        jsr skip_peek_ptr1
        beq @show               ; NUL after skip — bare `.`, redisplay
        cmp #';'
        beq @show               ; comment — redisplay
        cmp #'a'
        bcc @syn_err            ; non-letter garbage → syntax error
        cmp #'z'+1
        bcs @syn_err            ; above 'z' → syntax error
        jsr dot_assemble
        cmp #0
        bne @show               ; success → show result
        ; Check if expr error → print "expr <detail>"
        lda asm_expr_err
        beq @syn_err
        jsr expr_error_str      ; A/X = error string
        ; Stack-park the pointer — puts_imm below clobbers rp_tmp,
        ; and rp_tmp2 is only 1 byte wide (see query_user).
        pha                     ; lo
        txa
        pha                     ; hi
        ldy #LOG_ERR
        jsr log_open
        puts str_expr
        pla                     ; hi
        tax
        pla                     ; lo
        jsr io_puts
        jmp log_close
@syn_err:
        lda #<str_syntax
        ldx #>str_syntax
        jmp log_err   
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_disasm — 'd' command
;   rp_ptr = args (ignored)
; ═══════════════════════════════════════════════════════════
.proc cmd_disasm
        ; cmd_disasm takes no inline args; reject garbage at entry
        ; (pop-trick).  Addressed form `1000:l` sets cur_addr via
        ; exec_line before this proc runs — rp_ptr on entry points
        ; at what follows the `l` key.
        jsr skip_sp_ptr1
        ldy #0
        jsr _require_eoi_or_err

        jsr load_curaddr

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
        jsr load_curaddr

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

@edit:  ; Parse and write edit bytes.  rp_ptr2 := rp_addr once;
        ; zp_poke uses rp_ptr2+Y as the effective address so each
        ; iteration only needs Y = rp_cnt.
        lda rp_addr
        sta rp_ptr2
        lda rp_addr+1
        sta rp_ptr2+1
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
        ldy rp_cnt
        jsr zp_poke
        inc rp_cnt
        jsr skip_sp_ptr1
        jmp @ed_lp

@ed_done:
        ; Final-arg garbage check: reject non-EOW after the last HH
        ; (pop-trick).  Must precede emit_mem / cur_addr update so
        ; bad trailing input leaves state untouched.
        ldy #0
        jsr _require_eoi_or_err
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
        jcc @ed_nl
        lda #0
        sta cur_addr
        sta cur_addr+1
@ed_nl: jmp newline

@dump:  ; Reject trailing garbage after the optional ADDR (pop-trick).
        ; rp_ptr is already skipped past whitespace and past any hex4
        ; ADDR we parsed.  Legit EOLs (NUL, ';', spaces-then-those)
        ; pass; anything else is garbage and aborts the dump.
        ldy #0
        jsr _require_eoi_or_err

        ; Dump block_size bytes in 8-col rows
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
        bcs @d_lp

@d_done:
        lda rp_addr
        sta cur_addr
        lda rp_addr+1
        sta cur_addr+1
        jmp io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; Kernel → userland command gates.
;
; j/g/c/t/o commands stage user state into reg_* / brk_pc / step_*,
; then set `run_user_pending` and rts NORMALLY up the jsr chain.
; `main_loop` (the only caller level without a parent jsr) checks
; the flag after `jsr exec_line` returns and does the actual
; `jmp return_to_userland` or `jmp restore_userland_state`.  This
; avoids RTI-from-within-a-jsr-frame — the gate primitives run at
; top level where the SP is naturally at kernel_init_sp-equivalent.
;
; `post_run_cleanup` is the inverse: called by `main_loop_top` after
; a break has longjmped back.  Shows break result, re-enables any
; temporarily-disabled bp, clears step state, restores KERNAL-ZP
; hygiene and VIC/color state.
; ═══════════════════════════════════════════════════════════

; ── hygiene_after_userland — restore KERNAL/VIC state post-user-run ──
; User code can leave the machine in any state: VIC blanked or in
; bitmap/multicolor/extended-color mode, charset pointer moved,
; sprites covering the text layer, raster IRQ armed, color RAM
; painted over, stuck keys in $C6, KERNAL cursor re-enabled.
; Clobbers: A, X, Y (via vic_reset + restore_colors + io_sync).
hygiene_after_userland:
        lda #1
        sta $CC                 ; KERNAL cursor off (cse_io invariant)
        lda #$80
        sta $0291               ; lock SHIFT+C= charset toggle (userland
                                ;   may have cleared this to 0; KERNAL
                                ;   honours the combo when it's 0)
        ; SID silence: zero the voice-1/2/3 control registers to release
        ; any gates left on by userland.  SID registers are write-only
        ; so a read-modify-write to clear just bit 0 isn't possible;
        ; clobbering waveform + gate is the practical silence primitive.
        lda #0
        sta $D404
        sta $D40B
        sta $D412
        jsr vic_reset           ; $D011/$D015/$D016/$D018/$D019/$D01A
        jsr restore_colors      ; border/bg/fg + color RAM + CHROUT colour

        ; If the break was an NMI (canonical trigger: RUN/STOP+
        ; RESTORE), arm stop_cooldown so main_loop's edge-filter
        ; swallows any STOPs still in flight from the held key.
        ; The cooldown clears automatically once KERNAL STOP
        ; ($FFE1) reports the key released.
        lda dbg_reason
        cmp #2                  ; DBG_NMI
        bne @drain
        lda #1
        sta stop_cooldown
@drain:
        lda #0
        sta $C6                 ; drain any buffered keystrokes
        jmp io_sync             ; tail-call

; ═══════════════════════════════════════════════════════════
; cmd_jmp — 'j'/'g' command.  Stages reg_* / brk_pc (already in
; cur_addr by caller), drains kbd buffer, requests a fresh-start
; run (MODE_JUMP = push sentinel).
; ═══════════════════════════════════════════════════════════
.proc cmd_jmp
        lda cur_addr
        sta brk_pc
        lda cur_addr+1
        sta brk_pc+1
        jsr pre_userland_run
        lda #MODE_JUMP
        sta run_user_pending
        rts
.endproc

; ── pre_userland_run — shared pre-flight for j/g/t/o ────────────────
; Newline + clreol so user CHROUT starts on a fresh row, plus a
; keyboard-buffer drain so user's first GETIN/CHRIN doesn't see
; keys the user typed while issuing the command.
; Clobbers: A, X, Y.
pre_userland_run:
        jsr newline
        jsr io_clear_eol
        lda #0
        sta $C6
        rts

; ═══════════════════════════════════════════════════════════
; cmd_step — 't' (step-into) / 'o' (step-over) command.
;
; Seed-only under the Phase-18 handler-resident state machine:
;   1. Parse count (N), default 1.  On expression success, reject
;      trailing garbage via the pop-trick _require_eoi_or_err —
;      `t10xyz` logs ";?syntax" and aborts before any state write.
;   2. Set step_state (STEP_INTO or STEP_OVER).
;   3. If no prior break, initialise brk_pc from cur_addr.
;   4. Temporarily disable any bp at brk_pc (so the first step can
;      execute the instruction there without immediately re-hitting
;      its own bp).
;   5. Compute first next-PC(s) via debugger.s::step_next_pc.
;      If both slots are zero (opcode is RTS/RTI/BRK), stop before
;      executing: reuse post_run_cleanup for the step finish-up,
;      clear dbg_reason, return with run_user_pending=0.
;   6. Arm step_bp slots (arm_step_bp).
;   7. step_remaining := N - 1 (the first iteration runs via our
;      return; the handler chain handles iterations 2..N).
;   8. Set run_user_pending.  MODE_JUMP if no prior break context
;      (fresh entry — sentinel needed), MODE_RESUME otherwise
;      (reuse existing sentinel).
;   9. RTS up to main_loop, which dispatches to the gate.
;
; In: rp_ptr = args, A = is_next (0=into, 1=over)
; ═══════════════════════════════════════════════════════════
.proc cmd_step
        sta rp_save2            ; is_next (0=into, 1=over)

        ; Cold-start: no prior break → init brk_pc from cur_addr.
        lda dbg_reason
        bne @has_ctx
        lda cur_addr
        sta brk_pc
        lda cur_addr+1
        sta brk_pc+1
@has_ctx:

        ; Parse count: via try_expr, or default to 1 (single step).
        ; t/o are single-step commands by default; an expression arg
        ; overrides for multi-step (e.g. `t10` = step 10 instructions).
        ; On try_expr success, reject trailing garbage via the pop-
        ; trick helper (never returns on garbage — see optimization.md
        ; § Pop-trick error escape).  No state has been written yet,
        ; so an early escape is clean.
        jsr try_expr
        bcc @def_count
        ldy #0
        jsr _require_eoi_or_err
        lda expr_val
        ora expr_val+1
        beq @def_count          ; zero → default
        lda expr_val
        sta rp_cnt
        lda expr_val+1
        sta rp_cnt+1
        jmp @got_cnt
@def_count:
        lda #1
        sta rp_cnt
        lda #0
        sta rp_cnt+1
@got_cnt:

        ; step_state = STEP_OVER if is_next else STEP_INTO.
        lda rp_save2
        beq @into
        lda #STEP_OVER
        .byte $2C               ; BIT abs — skip next 2 bytes
@into:  lda #STEP_INTO
        sta step_state

        ; Temporarily disable any user-visible bp at brk_pc.
        lda #$FF
        sta rp_dis_bp
        lda dbg_bp_hit
        cmp #$FF
        beq @no_disable
        asl
        asl                     ; slot × 4
        tax
        stx rp_dis_bp
        lda #0
        sta bp_table+3,x        ; disable flag
@no_disable:

        ; Compute first next-PC.  step_next_pc reads opcode at brk_pc.
        jsr step_next_pc

        ; If both slots zero (opcode is RTS/RTI/BRK), stop without
        ; entering user code.  post_run_cleanup already knows how to
        ; finish a step (clear step_state, re-enable disabled bp,
        ; show_break_result, clear last_cmd on RTS/RTI) — call it
        ; with step_state still set so it takes the step branch.
        ;
        ; Clear dbg_reason BEFORE post_run_cleanup so show_break_result
        ; takes the opcode-based fallback ("; rts" for $60/$40, "; brk"
        ; for $00) — the user-meaningful tag for "tried to step but
        ; couldn't, next instruction would have been a return op".
        ; The first-time-landing case (real BRK trap on the RTS
        ; instruction) sees dbg_reason = DBG_BRK and gets "; brk" via
        ; the trap path through main_loop_top → post_run_cleanup; only
        ; the cmd_step early-stop sets dbg_reason = 0 here.  Without
        ; this re-order, the second t/o on the same RTS would still
        ; show "; brk" (bug: "rts needs to be stepped on twice before
        ; it registers as rts").
        lda step_next_lo
        ora step_next_lo+1
        ora step_next_hi
        ora step_next_hi+1
        bne @arm
        lda #0
        sta dbg_reason
        jmp post_run_cleanup    ; tail-call

@arm:
        jsr arm_step_bp

        ; step_remaining = count - 1 (first iteration runs below via
        ; return_to_userland / restore_userland_state; N-1 via handler chain).
        lda rp_cnt
        sec
        sbc #1
        sta step_remaining

        jsr pre_userland_run

        ; Mode: fresh (sentinel) if no prior break, resume otherwise.
        lda dbg_reason
        beq @fresh
        lda #MODE_RESUME
        .byte $2C
@fresh: lda #MODE_JUMP
        sta run_user_pending
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
        bne :+
        jmp @list_all
:       cmp #'*'
        bne :+
        jmp @clear_all
:       cmp #'-'
        bne :+
        jmp @delete_one
:

        ; b ADDR — set breakpoint
        jsr try_expr
        bcs :+
        jmp @err_b
:
        ; Reject trailing garbage (pop-trick).  Must happen BEFORE
        ; dbg_bp_set so a bad "b ADDR garbage" doesn't install the bp.
        ldy #0
        jsr _require_eoi_or_err
        ; Range-check: bp must be in workspace [$0800, __CODE_RUN__)
        lda expr_val+1
        cmp #>$0800
        jcc @bp_range
        lda expr_val+1
        cmp #>__CODE_RUN__
        bcc @bp_ok
        jne @bp_range
        lda expr_val
        cmp #<__CODE_RUN__
        jcs @bp_range
@bp_ok:
        lda expr_val
        ldx expr_val+1
        jsr dbg_bp_set         ; returns slot in A ($FF=full)
        cmp #$FF
        bne :+
        jmp @full
:
        jsr bp_open_slot
        puts str_colon_sp
        lda #'$'
        jsr io_putc
        lda expr_val
        ldx expr_val+1
        jsr io_puthex4
        jmp log_close   

@list_all:
        ldx #0                  ; slot index
@list:
        cpx #8
        bcc :+
        jmp @done
:
        stx rp_save
        txa
        jsr bp_open_slot
        puts str_colon_sp
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
        puts str_dashes
@slot_done:
        jsr log_close
        ldx rp_save
        inx
        bne @list

@clear_all:
        jsr dbg_bp_clear
        lda #<str_bp_clr
        ldx #>str_bp_clr
        jsr log_info
        jmp io_clear_eol

@delete_one:
        iny
        lda (rp_ptr),y
        cmp #'1'
        bcc @bad_slot
        cmp #'9'
        bcs @bad_slot
        sec
        sbc #'1'
        pha
        jsr dbg_bp_del
        pla
        jsr bp_open_slot
        puts str_deleted
        jmp log_close   

@bad_slot:
        lda #<str_bad_val
        ldx #>str_bad_val
        jmp log_err   

@full:  lda #<str_full
        ldx #>str_full
        jmp log_err   

@bp_range:
        lda #<str_range
        ldx #>str_range
        jmp log_err   

@err_b: lda #<str_syntax
        ldx #>str_syntax
        jmp log_err   
@done:  jmp io_clear_eol
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
        jsr skip_peek_ptr1
        beq @show

        ; Optional "pc:XXXX" — matches emit_reg's display, so the
        ; user can cursor-up onto the echoed register line, edit any
        ; field (including PC), and have it committed on RETURN.
        cmp #'p'
        bne @no_pc
        ; skip "pc:" (3 chars), parse 4 hex → brk_pc
        lda rp_ptr
        clc
        adc #3
        sta rp_ptr
        bcc :+
        inc rp_ptr+1
:       jsr parse_hex4_ptr1     ; A = lo, X = hi
        sta brk_pc
        stx brk_pc+1
        jsr skip_sp_ptr1
@no_pc:

        ; Parse a:XX x:XX y:XX s:XX into reg_a..reg_sp (contiguous
        ; in BSS — defined in that order in asm_line.s).  Each
        ; iteration: parse_regval eats "X:YY", skip_sp_ptr1 eats
        ; the delimiting space before the next field (or leading
        ; space of the flags block on the last iteration).
        ldx #0
@rlp:   jsr parse_regval
        sta reg_a,x
        jsr skip_sp_ptr1
        inx
        cpx #4
        bcc @rlp

        ; Parse flags: 8 chars, bit=1 if typed char is uppercase form
        ; of str_flag_ch[x] (PETSCII $C0-$DF, i.e. lowercase + $80).
        ; Lowercase, '-', or anything else → bit=0.
        ; rp_tmp2 accumulates from the right; the 8 asl's below shift
        ; any initial garbage entirely out, so no zero-init needed.
        ldy #0                  ; input offset
        ldx #0                  ; flag slot
@pflag: asl rp_tmp2             ; make room; low bit defaults 0
        lda (rp_ptr),y
        beq @pdone              ; end of input → remaining bits stay 0
        cmp #';'
        beq @pdone
        iny                     ; consume this char
        eor str_flag_ch,x       ; match iff typed == reference ^ $80 (uppercase)
        cmp #$80                ; $80 means: matches reference, with bit 7 set
        bne @pnext              ; not a "set" marker → bit=0
        inc rp_tmp2             ; flip low bit 0→1
@pnext: inx
        cpx #8
        bcc @pflag
        beq @pstore             ; got 8 bits, store directly
@pdone: ; pad remaining slots with 0
@ppad:  cpx #8
        bcs @pstore
        asl rp_tmp2
        inx
        bne @ppad
@pstore:
        ; rp_ptr advance past consumed flag chars used to be here but
        ; nothing reads rp_ptr after cmd_reg returns (@show just
        ; emit_reg + nl_clear) — dead code, removed.
        lda rp_tmp2
        and #%11011111          ; keep bit 5 = 0 invariant (matches
                                ; the capture-time mask in debugger.s);
                                ; lets emit_reg skip its '-' guard.
        sta reg_p

@show:  ; emit_reg already sets CUR_COL=0, so it overwrites the
        ; current row — the edited `r …` line is replaced in place
        ; with the authoritative formatted register state.  nl_clear
        ; then advances to a fresh row for the next prompt.
        jsr emit_reg
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; ═══════════════════════════════════════════════════════════
; strip_and_classify — detect trailing ",m" type suffix on a
;   NUL-terminated name at rp_ptr2 and optionally truncate.
;
;   In:  rp_ptr2 = name pointer (typically rp_ptr2 from parse_filename).
;   Out: A = 0 (no suffix), 's' (verbatim SEQ), 'p' (verbatim PRG).
;        If a suffix is detected, the comma is overwritten with NUL
;        in place so the name pointer now points at the bare stem.
;        Case-folded: ',S'/',s' → 's'; ',P'/',p' → 'p'.
;   Clobbers: A, X, Y
; ═══════════════════════════════════════════════════════════
.proc strip_and_classify
        ldy #0
@len:   lda (rp_ptr2),y
        beq @got_len
        iny
        bne @len
@got_len:
        cpy #2
        bcc @none               ; too short for ",m" suffix
        dey
        lda (rp_ptr2),y         ; last char
        ; Accept both 'p'/'s' ($50/$53, our default lowercase) and
        ; 'P'/'S' ($D0/$D3, canonical uppercase).  Fold uppercase
        ; → lowercase by clearing bit 7.
        and #$7F
        cmp #'s'
        beq @got
        cmp #'p'
        bne @none
@got:   tax                     ; X = classified char ('s' or 'p')
        dey
        lda (rp_ptr2),y         ; char before letter
        cmp #','
        bne @none
        lda #0                  ; truncate at comma
        sta (rp_ptr2),y
        txa                     ; return classified char in A
        rts
@none:  lda #0
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; copy_stem_to_project — copy NUL-terminated name from rp_ptr2
;   to cur_project_name, with trailing-dot stripping.
;   Dots at the END of the name are not stored (prevents dot
;   accumulation when the user re-types the PRG-derived name).
;   Internal dots (e.g. "foo.bar") are preserved.
;   Empty source overwrites project name with empty string.
;   Clobbers: A, X, Y
; ═══════════════════════════════════════════════════════════
.proc copy_stem_to_project
        ldy #0
@cp:    lda (rp_ptr2),y
        sta cur_project_name,y
        beq @strip              ; copy hit NUL → start trailing-dot strip
        iny
        cpy #FILENAME_MAX
        bcc @cp
        lda #0
        sta cur_project_name,y  ; force NUL at max
@strip: ; back up over any trailing dots, replacing with NUL
@sl:    dey
        bmi @done               ; string was entirely dots (or empty)
        lda cur_project_name,y
        cmp #'.'
        bne @done
        lda #0
        sta cur_project_name,y
        jmp @sl
@done:  rts
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
        bne @fail               ; no quote → no filename
        ; skip opening quote
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       lda rp_ptr
        sta rp_ptr2
        lda rp_ptr+1
        sta rp_ptr2+1
        ; scan for closing quote or NUL
        ldy #0
@scan:  lda (rp_ptr),y
        beq @done
        cmp #$22
        beq @close
        iny
        bne @scan
@close: ; NUL-terminate at closing quote, advance past it
        lda #0
        sta (rp_ptr),y
        iny
        tya
        clc
        adc rp_ptr
        sta rp_ptr
        bcc @done
        inc rp_ptr+1
@done:  jsr skip_sp_ptr1
        ; check if name is empty (e.g. "")
        ldy #0
        lda (rp_ptr2),y
        beq @fail
        lda #1                  ; A=1, Z=0: name found
        rts
@fail:  lda #0                  ; A=0, Z=1: no name
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; get_filename — parse quoted name and store into project name.
;
;   In:  rp_ptr = input line ptr.
;   Out: rp_ptr2 = pointer to stripped name (in line_buf for quoted
;           input, or cur_project_name for reuse).
;        _verbatim_type = 0 / 's' / 'p' from strip_and_classify.
;        cur_project_name updated (stripped stem, trailing dots removed)
;           if a quoted name was supplied.
;        A = 0 / Z=1 if no name at all (neither typed nor remembered
;          nor default-able — only happens if default "out" logic
;          is disabled, which currently it isn't; so always A=1 here).
;   Uses: parse_filename, strip_and_classify, copy_stem_to_project.
; ═══════════════════════════════════════════════════════════
.proc get_filename
        jsr parse_filename      ; A=0 if no name (→ @reuse); else A=1
        beq @reuse

        ; quoted name present; rp_ptr2 → typed name in line_buf
        jsr strip_and_classify   ; returns A = 0/'s'/'p'; truncates suffix
        sta _verbatim_type
        beq @from_typed         ; non-verbatim → derive from stem below
        ; verbatim: rp_ptr2 is the typed name (already truncated at
        ; the ",m" by strip_and_classify).  Trailing dot is kept.
        ; Still update cur_project_name so bare reuse works next time.
        jsr copy_stem_to_project
        lda #1
        rts
@from_typed:
        ; non-verbatim: store stem, then return rp_ptr2 = cur_project_name
        jsr copy_stem_to_project
        jmp @ok

@reuse:
        ; no quoted name — A=0 here; also clear the verbatim flag so a
        ; previous verbatim call doesn't leak across invocations.
        sta _verbatim_type
        ; reuse cur_project_name (or s_save_default if empty)
        lda cur_project_name
        bne @ok
        ; fill cur_project_name from s_save_default (e.g. "out\0")
        ldx #3
@fd:    lda s_save_default,x
        sta cur_project_name,x
        dex
        bpl @fd
@ok:
        lda #<cur_project_name
        sta rp_ptr2
        lda #>cur_project_name
        sta rp_ptr2+1
        lda #1
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; print_seq_stats — print "N lines, M bytes"
; Caller opens the line via log_open first.
; ═══════════════════════════════════════════════════════════
.proc print_seq_stats
        lda ed_save_lines
        ldx ed_save_lines+1
        jsr io_putdec
        puts str_lines
        lda ed_save_bytes
        ldx ed_save_bytes+1
        jsr io_putdec
        lda #<str_bytes
        ldx #>str_bytes
        jmp io_puts
.endproc

; ═══════════════════════════════════════════════════════════
.ifndef TAB_WIDTH
TAB_WIDTH = 8
.endif
TAB_MASK_WL = TAB_WIDTH - 1

; warn_long_lines — print ";!long LNN" for each line > 39 vcols
;
; Walks the buffer via ed_read_byte, computing visual width per
; line.  Prints one warning per overflowing line.  TAB_WIDTH is
; hardcoded to match the build-time constant (default 8).
; ═══════════════════════════════════════════════════════════
.proc warn_long_lines
        jsr ed_read_rewind
        lda #0
        sta @vcol
        sta @line
        sta @line+1

@byte:  jsr ed_read_byte
        cpx #$FF
        beq @check_last         ; EOF

        cmp #$0D
        beq @eol

        ; Compute visual width of byte
        cmp #$A0                ; tab?
        beq @tab
        ; Non-tab: width = 1
        inc @vcol
        jmp @byte

@tab:   ; width = TAB_WIDTH - (vcol & TAB_MASK)
        lda @vcol
        and #TAB_MASK_WL
        sta @tw
        lda #TAB_WIDTH
        sec
        sbc @tw                 ; A = tab expansion width
        clc
        adc @vcol
        sta @vcol
        jmp @byte

@eol:   ; End of line — check if vcol > 39
        jsr @check_vcol
        ; Advance line counter, reset vcol
        inc @line
        bne :+
        inc @line+1
:       lda #0
        sta @vcol
        jmp @byte

@check_last:
        ; EOF — check the last line if it had any content
        lda @vcol
        beq @done
        jsr @check_vcol
@done:  rts

@check_vcol:
        lda @vcol
        cmp #40                 ; > 39 ?
        bcc @ok
        ; Print ";!long LNN" (1-based line number)
        ldy #LOG_WARN
        jsr log_open
        puts str_long
        lda @line
        clc
        adc #1
        sta rp_tmp
        lda @line+1
        adc #0
        tax
        lda rp_tmp
        jsr io_putdec
        jsr log_close
@ok:    rts

@vcol:  .byte 0
@line:  .res 2
@tw:    .byte 0
.endproc

; ═══════════════════════════════════════════════════════════
; io_err_load / io_err_save — emit ";?fail" and tail-jump
; to disk_done (drive status + clear prompt row).  Callers
; branch here on disk error; no need for an explicit
; disk_done after.
; ═══════════════════════════════════════════════════════════
io_err_load:
io_err_save:
        lda #<str_fail
        ldx #>str_fail
        jsr log_err
        jmp disk_done

; ═══════════════════════════════════════════════════════════
; disk_done — shared exit for l/s: drive status + clear prompt row.
; Callers must leave the cursor on a fresh row (prg_line, log_err,
; etc. all end with a newline already).
; ═══════════════════════════════════════════════════════════
disk_done:
        jsr floppy_status
        jmp io_clear_eol

; ═══════════════════════════════════════════════════════════
; parse_ls_args — shared l/s entry point.
;
;   Parses (in order):
;     1. Optional "quoted name" — see get_filename.
;     2. Up to two numeric args via try_expr (stops at first failure,
;        ';' or end of input).
;
;   Resolves:
;     rp_addr, rp_cnt (16-bit each):
;       args=0 → start=cur_addr, end=0
;       args=1 → start=cur_addr, end=arg1
;       args=2 → start=arg1, end=arg2
;     rp_next_lo = ptr to the "name for DOS" (verbatim typed name or
;       cur_project_name stem, per get_filename).
;     _arg_count = 0, 1, or 2.
;     _verbatim_type = 0 / 's' / 'p' (set by get_filename).
;
;   Classifies the operation mode:
;     _verbatim_type='s'/'S' → SEQ (verbatim)
;     _verbatim_type='p'/'P' → PRG (verbatim)
;     else if _arg_count > 0 → PRG (derived)
;     else                   → SEQ (derived)
;
;   Out: A = 2 SEQ / 1 PRG (Z always 0 — "no name" no longer fails
;        because we default-fill project name to "out" on empty).
; ═══════════════════════════════════════════════════════════
parse_ls_args:
        jsr load_curaddr         ; rp_addr = cur_addr (tentative start)
        jsr get_filename         ; sets _verbatim_type, rp_ptr2 = name ptr

        ; rp_ptr2 (ZP) carries the name pointer through to compose_disk_name —
        ; try_expr and skip_sp_ptr1 don't touch it.

        ; parse up to two numeric args
        lda #0                   ; A=0 used for all zero-inits below
        sta _arg_count
        sta rp_cnt
        sta rp_cnt+1

        jsr @peek_args
        beq @classify            ; no first arg

        jsr try_expr
        bcc @classify            ; expression failed → treat as 0 args
        inc _arg_count
        ; first arg lands in rp_cnt (as tentative end).  If a second
        ; arg follows, we'll promote it to start and use arg2 as end.
        lda expr_val
        sta rp_cnt
        lda expr_val+1
        sta rp_cnt+1

        jsr @peek_args
        beq @classify
        ; second-arg candidate present; try to parse it before we
        ; disturb rp_addr, so a parse failure leaves 1-arg semantics.
        jsr try_expr
        bcc @classify
        inc _arg_count
        ; promote: rp_cnt (arg1) → rp_addr (start); expr_val (arg2) → rp_cnt (end)
        lda rp_cnt
        sta rp_addr
        lda rp_cnt+1
        sta rp_addr+1
        lda expr_val
        sta rp_cnt
        lda expr_val+1
        sta rp_cnt+1

@classify:
        ; Mode: verbatim wins; else args>0 → PRG; else SEQ.
        ; _verbatim_type is 'p' / 's' / 0 (set by strip_and_classify).
        lda _verbatim_type
        beq @no_verb
        cmp #'p'
        beq @prg
        bne @seq
@no_verb:
        lda _arg_count
        bne @prg
@seq:   lda #2                  ; SEQ code for cmd_load/cmd_write
        rts
@prg:   lda #1                  ; PRG code
        rts

        ; @peek_args: check if another numeric arg follows.
        ; Returns Z=1 on terminator (NUL / ';'), Z=0 otherwise.
@peek_args:
        jsr skip_peek_ptr1      ; A = first non-space byte; Y = 0
        beq @term               ; NUL → Z=1
        cmp #';'                ; ';' → Z=1; else Z=0
@term:  rts

; ═══════════════════════════════════════════════════════════
; compose_disk_name — build the CBM DOS filename into disk_name_buf.
;
;   In:  A = mode (1 PRG, 2 SEQ — as returned by parse_ls_args).
;        _verbatim_type: 0 (derive) or 's'/'p' (verbatim, no derive).
;        rp_ptr2 = source name pointer (set by parse_ls_args via
;          get_filename; try_expr + skip_sp_ptr1 don't touch it).
;   Out: disk_name_buf filled with NUL-terminated name.  For PRG
;        derived, a `.` is appended.  Otherwise the source name is
;        copied verbatim.  rp_next_lo points at disk_name_buf.
;        A is preserved (returns mode unchanged for caller).
;   Clobbers: X, Y
; ═══════════════════════════════════════════════════════════
.proc compose_disk_name
        pha                     ; keep mode on stack across body
        ldy #0
@cp:    lda (rp_ptr2),y
        sta disk_name_buf,y
        beq @end
        iny
        cpy #FILENAME_MAX
        bcc @cp
        lda #0
        sta disk_name_buf,y
@end:   ; Y = NUL index; peek mode without consuming
        pla
        pha                     ; (stack still holds mode for final pla)
        lsr                     ; 1 → 0 (PRG), 2 → 1 (SEQ)
        bne @finish             ; SEQ → done
        ; PRG: if non-verbatim, append '.'
        lda _verbatim_type
        bne @finish
        lda #'.'
        sta disk_name_buf,y
        iny
        lda #0
        sta disk_name_buf,y
@finish:
        ; publish the composed buffer as the DOS-facing name pointer
        lda #<disk_name_buf
        sta rp_next_lo
        lda #>disk_name_buf
        sta rp_next_lo+1
        pla                     ; restore mode for caller
        rts
.endproc

; ═══════════════════════════════════════════════════════════
; print_op_name — print "; verb "name"..." log line (stays open).
;   In: A/X = verb string ptr.  Uses rp_next_lo for name.
; ═══════════════════════════════════════════════════════════
print_op_name:
        sta rp_tmp
        stx rp_tmp+1
        ldy #LOG_INFO
        jsr log_open
        lda rp_tmp
        ldx rp_tmp+1
        jsr io_puts
        lda #$22
        jsr io_putc
        lda rp_next_lo
        ldx rp_next_lo+1
        jsr io_puts
        lda #$22
        jsr io_putc
        puts str_dots
        jmp io_clear_eol

; ═══════════════════════════════════════════════════════════
; cmd_load — 'l' command
;   rp_ptr = args
;
;   parse_ls_args has already set:
;     rp_addr, rp_cnt per the 0/1/2-arg table:
;       0 args → start=cur_addr, end=0
;       1 arg  → start=cur_addr, end=arg1
;       2 args → start=arg1,     end=arg2
;     rp_next_lo = name ptr (either verbatim line_buf or
;                  cur_project_name, depending on _verbatim_type).
;     A on return = 2 SEQ / 1 PRG.
;
;   Load interpretation:
;     SEQ: addr/end ignored — ed_load_source(name).
;     PRG: end == 0 → load to PRG header address (SA=1 path).
;          end != 0 → load to `end` (SA=0 path).  `start` is unused.
; ═══════════════════════════════════════════════════════════
.proc cmd_load
        jsr parse_ls_args       ; A = 2 SEQ / 1 PRG
        jsr compose_disk_name   ; preserves A
        lsr                     ; 1 → 0 (PRG), 2 → 1 (SEQ)
        beq @load_prg

        ; ── SEQ load ──
        ; Gate: warn + prompt when either dirty or debugging.  If
        ; debug was active on yes, replay via warm_cont + end_debug.
        ; Otherwise (clean state or dirty-only) proceed.
        lda dbg_reason
        ora ed_dirty
        beq @do_load
        jsr warn_if_unsaved     ; stack order: unsaved before debug
        jsr warn_if_debug
        lda #<str_load
        ldx #>str_load
        jsr query_user
        jcc @l_cancel
        lda dbg_reason
        beq @do_load            ; clean-debug yes → load directly
        lda #1
        sta warm_cont           ; replay line_buf after end-debug
        jmp cse_end_debug
@do_load:

        lda #<str_load_pfx
        ldx #>str_load_pfx
        jsr print_op_name

        lda rp_next_lo
        ldx rp_next_lo+1
        jsr ed_load_source     ; A=error: 0=ok, 1=disk/empty, 2=too large
        beq seq_ok_done         ; A already reflects status (Z)
        cmp #2
        beq @seq_too_large
        jmp io_err_load         ; tail-jumps to disk_done
@seq_too_large:
        lda #<str_too_big
        ldx #>str_too_big
        jsr log_err
        jmp disk_done

@load_prg:
        lda #<str_load_pfx
        ldx #>str_load_pfx
        jsr print_op_name

        ; PRG: target address = rp_cnt (end slot from parse_ls_args).
        ; rp_cnt==0 → let disk_load_prg use the PRG header address.
        lda rp_next_lo
        sta disk_ptr
        lda rp_next_lo+1
        sta disk_ptr+1
        lda rp_cnt
        ldx rp_cnt+1
        jsr disk_load_prg       ; A/X = end addr (0/0 on error)
        sta rp_cnt              ; end lo
        stx rp_cnt+1            ; end hi
        ora rp_cnt+1
        bne prg_ok_done
        jmp io_err_load         ; tail-jumps to disk_done

@l_cancel:
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; Shared success tails for cmd_load / cmd_write.
; Both end by jumping to disk_done.
; ═══════════════════════════════════════════════════════════

; seq_ok_done — print "; N lines, M bytes", long-line warnings, done.
seq_ok_done:
        ldy #LOG_INFO
        jsr log_open
        jsr print_seq_stats
        jsr log_close
        jsr warn_long_lines
        jmp disk_done

; prg_ok_done — print "; prg AAAA-BBBB  NNNb", done.
prg_ok_done:
        jsr prg_line
        jmp disk_done

; ═══════════════════════════════════════════════════════════
; cmd_write — 's' command (save/write)
;   rp_ptr = args
;
;   parse_ls_args already produced rp_addr/rp_cnt per the table
;   (see cmd_load) and classified mode (A = 2 SEQ / 1 PRG).
;
;   Save-only end-address fallback (PRG):
;     end == 0    → end = start + block_size
;     end <= start → end = start + end      (length fallback)
; ═══════════════════════════════════════════════════════════
.proc cmd_write
        jsr parse_ls_args       ; A = 2 SEQ / 1 PRG
        jsr compose_disk_name   ; preserves A
        pha                     ; save mode across print_op_name
        lda #<str_save_pfx
        ldx #>str_save_pfx
        jsr print_op_name       ; common prefix "; s "name"..." for both
        pla
        lsr                     ; 1 → 0 (PRG), 2 → 1 (SEQ)
        beq @save_prg

        ; ── SEQ save ──
        jsr ed_ensure_init
        lda rp_next_lo
        ldx rp_next_lo+1
        jsr ed_save_source     ; A=error
        beq seq_ok_done
        jmp io_err_save         ; tail-jumps to disk_done

@save_prg:
        ; ── end argument semantics ─────────────────────────
        ;   end == 0      → size = block_size              (bare `s`)
        ;   end <= start  → size = end                     (length fallback)
        ;   end > start   → size = end - start + 1         (INCLUSIVE
        ;                   absolute end — matches the `AAAA-BBBB`
        ;                   display in seg_line and prg_line).
        ; Result: rp_next_hi holds the size.
        lda rp_cnt
        ora rp_cnt+1
        bne @end_nonzero
        lda block_size
        sta rp_next_hi
        lda block_size+1
        sta rp_next_hi+1
        jmp @validate

@end_nonzero:
        sec
        lda rp_addr
        sbc rp_cnt
        lda rp_addr+1
        sbc rp_cnt+1
        bcc @abs_end            ; start < end → absolute inclusive
        ; start >= end — end-as-length fallback; size = end as-is
        lda rp_cnt
        sta rp_next_hi
        lda rp_cnt+1
        sta rp_next_hi+1
        jmp @validate

@abs_end:
        ; size = end - start + 1
        lda rp_cnt
        sec
        sbc rp_addr
        sta rp_next_hi
        lda rp_cnt+1
        sbc rp_addr+1
        sta rp_next_hi+1
        inc rp_next_hi
        bne @validate
        inc rp_next_hi+1

@validate:
        ; size must be > 0
        lda rp_next_hi
        ora rp_next_hi+1
        beq @range_err

        ; disk_save_prg(name, addr, size)
        lda rp_next_lo
        sta disk_ptr
        lda rp_next_lo+1
        sta disk_ptr+1
        lda rp_addr
        sta _io_tmp             ; start addr lo
        lda rp_addr+1
        sta _io_tmp+1           ; start addr hi
        lda rp_next_hi
        ldx rp_next_hi+1
        jsr disk_save_prg       ; A=error
        bne @save_err
        ; Set rp_cnt = rp_addr + size (exclusive end) for prg_line's
        ; display pass (it decrements to inclusive internally).
        lda rp_addr
        clc
        adc rp_next_hi
        sta rp_cnt
        lda rp_addr+1
        adc rp_next_hi+1
        sta rp_cnt+1
        jmp prg_ok_done
@save_err:
        jmp io_err_save         ; tail-jumps to disk_done

@range_err:
        lda #<str_range
        ldx #>str_range
        jmp log_err   
.endproc

; ───────────────────────────────────────────────────────────
; info_emit_rows — emit N rows from info table
;   A/X = table ptr, Y = row count
;   Each row: tag(2), lo(2), hi(2), desc(2) = 8 bytes
;   No-op when _info_mode != 0 (splash mode skips all tables).
; ───────────────────────────────────────────────────────────
.proc info_emit_rows
        sta rp_next_hi
        stx rp_next_hi+1
        sty rp_opc              ; row counter
        lda _info_mode
        bne @exit               ; splash mode: skip
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
        pha                     ; desc lo
        iny
        lda (rp_ptr),y
        pha                     ; desc hi
        lda rp_next_hi
        clc
        adc #8
        sta rp_next_hi
        bcc :+
        inc rp_next_hi+1
:       pla
        sta rp_ptr+1            ; desc hi
        pla
        sta rp_ptr              ; desc lo
        lda #0
        sta rp_save2
        jsr info_line
        dec rp_opc
        bne @lp
@exit:  rts
.endproc

; ── cmd_info — memory map display ─────────────────────────
; In:  C=0 full mode (i command), C=1 splash mode (free only)
; Splash mode: only free sections, no highlight, no newline
; Full mode:   all sections, highlighted free, caller does newline
.proc cmd_info
        ; capture carry → _info_mode (0=full, 1=splash).
        ; Dedicated BSS byte avoids ZP entirely — many puts below.
        lda #0
        adc #0
        sta _info_mode

        ; ── cpu ──
        lda #<info_tbl_h1
        ldx #>info_tbl_h1
        ldy #INFO_TBL_H1_ROWS
        jsr info_emit_rows

        ; ── zp 0002-007f  free ──
        lda #<str_tag_zp
        sta rp_ptr2
        lda #>str_tag_zp
        sta rp_ptr2+1
        lda #0
        sta rp_addr+1
        sta rp_cnt+1
        lda #$02
        sta rp_addr
        lda #$7F
        sta rp_cnt
        jsr free_line

        ; ── sys(kernal zp), stk ──
        lda #<info_tbl_h2
        ldx #>info_tbl_h2
        ldy #INFO_TBL_H2_ROWS
        jsr info_emit_rows

        ; ── sys 0200-02a6  kernal ──
        lda #<info_tbl_lo
        ldx #>info_tbl_lo
        ldy #INFO_TBL_LO_ROWS
        jsr info_emit_rows

        ; ── low 02a7-02ff  free ──
        lda #<str_tag_low
        sta rp_ptr2
        lda #>str_tag_low
        sta rp_ptr2+1
        lda #<$02A7
        sta rp_addr
        lda #>$02A7
        sta rp_addr+1
        lda #<$02FF
        sta rp_cnt
        lda #>$02FF
        sta rp_cnt+1
        jsr free_line

        ; ── sys 0300-0333  kernal ──
        lda #<info_tbl_lo2
        ldx #>info_tbl_lo2
        ldy #INFO_TBL_LO2_ROWS
        jsr info_emit_rows

        ; ── low 0334-03ff  free ──
        lda #<str_tag_low
        sta rp_ptr2
        lda #>str_tag_low
        sta rp_ptr2+1
        lda #<$0334
        sta rp_addr
        lda #>$0334
        sta rp_addr+1
        lda #<$03FF
        sta rp_cnt
        lda #>$03FF
        sta rp_cnt+1
        jsr free_line

        ; ── scr ──
        lda #<info_tbl_h3
        ldx #>info_tbl_h3
        ldy #INFO_TBL_H3_ROWS
        jsr info_emit_rows

        ; ── Dynamic: free workspace ──
        ; Free = $0800 to buf_base-1 (gap between output and source)
        lda #<str_tag_work
        sta rp_ptr2
        lda #>str_tag_work
        sta rp_ptr2+1
        lda #<$0800
        sta rp_addr
        lda #>$0800
        sta rp_addr+1
        lda buf_base
        sec
        sbc #1
        sta rp_cnt
        lda buf_base+1
        sbc #0
        sta rp_cnt+1
        jsr free_line

        ; ── sections below are full-mode only ──
        lda _info_mode
        jne @done

        ; ── Dynamic: source (skip if empty: src_bot == src_top) ──
        lda src_bot
        cmp src_top
        bne @has_src
        lda src_bot+1
        cmp src_top+1
        beq @no_src
@has_src:
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
        ; Stream "; src  AAAA-BBBB Nl Nb" directly
        lda ed_total_lines
        sta ed_save_lines
        lda ed_total_lines+1
        sta ed_save_lines+1
        lda src_top
        sec
        sbc src_bot
        sta ed_save_bytes
        lda src_top+1
        sbc src_bot+1
        sta ed_save_bytes+1
        lda #0
        sta rp_save2
        jsr info_line_head      ; "; src  AAAA-BBBB "
        jsr print_seq_stats     ; "Nl Nb" streamed
        jsr info_line_tail
@no_src:

        ; ── Dynamic: cse XXXX-CFFF  cse runtime ──
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

        ; ── Tail: io, kern ──
        lda #<info_tbl_tail
        ldx #>info_tbl_tail
        ldy #INFO_TBL_TAIL_ROWS
        jsr info_emit_rows

@done:  jmp io_clear_eol
.endproc

.segment "BSS"
; _info_mode moved to zp.s (Phase 21.1 Move 3B)
.segment "CODE"

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
        jsr load_curaddr
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
        lda #<str_cmd
        ldx #>str_cmd
        jmp log_err   

; ── Handlers ──────────────────────────────────────────────
@h_dot: jmp cmd_dot
@h_d:   jmp cmd_disasm
@h_m:   jmp cmd_mem
@h_b:   jmp cmd_brk
@h_r:   jmp cmd_reg
@h_l:   jmp cmd_load
@h_s:   jmp cmd_write
@h_i:   clc                     ; C=0 = full mode
        jmp cmd_info

@h_at:  ; @ — set address.  Parse → EOI check → apply.
        ; Can't delegate to expr_set_curaddr: it applies cur_addr
        ; before we can check EOI.  Inline the apply after the EOI
        ; check so garbage input leaves cur_addr untouched.
        jsr try_expr
        bcc @at_done            ; empty/error → skip apply and EOI
                                ; (try_expr emits its own error)
        ldy #0
        jsr _require_eoi_or_err
        lda expr_val
        sta cur_addr
        lda expr_val+1
        sta cur_addr+1
@at_done:
        jmp nl_clear

@h_plus:; + — advance address
        jsr expr_or_blocksize
        ldy #0
        jsr _require_eoi_or_err ; reject trailing garbage (pop-trick)
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
        jsr expr_or_blocksize
        ldy #0
        jsr _require_eoi_or_err ; reject trailing garbage (pop-trick)
        lda cur_addr
        sec
        sbc expr_val
        sta cur_addr
        lda cur_addr+1
        sbc expr_val+1
        sta cur_addr+1
        jmp nl_clear

@h_j:   ; j — jump/execute
        ; Class-wide Escape Analysis fix: same pattern as @h_at — parse,
        ; EOI check, apply.  On bare `j` or expr-error, preserve the
        ; existing behaviour of jumping with whatever cur_addr holds
        ; (try_expr already emitted its own error if there was one).
        jsr try_expr
        bcc @j_run              ; empty/error → jump with current cur_addr
        ldy #0
        jsr _require_eoi_or_err ; trailing garbage → abort, don't jump
        lda expr_val
        sta cur_addr
        lda expr_val+1
        sta cur_addr+1
@j_run:
        jmp cmd_jmp

@h_g:   ; g — go (sym_lookup "main")
        lda #<str_main
        sta sym_name
        lda #>str_main
        sta sym_name+1
        jsr sym_set_curaddr
        jmp cmd_jmp

@h_t:   ; t — step into
        lda #0
        jmp cmd_step

@h_o:   ; o — step over
        lda #1
        jmp cmd_step

@h_k:   ; k — delete source (warn + confirm)
        jsr warn_if_unsaved
        lda #<str_del_src
        ldx #>str_del_src
        jsr query_user
        bcc @k_cancel
        jsr ed_new
@k_cancel:
        jmp nl_clear

@h_blk: ; B (PETSCII $C2) — block size
        jsr try_expr
        bcc @B_show             ; empty or error → show current
        ; Success path: reject trailing garbage before applying value
        ; (Escape Analysis class-wide via shared helper).
        ldy #0
        jsr _require_eoi_or_err
        lda expr_val
        ora expr_val+1
        beq @B_show
        lda expr_val
        sta block_size
        lda expr_val+1
        sta block_size+1
@B_show:
        jsr show_block_size
        jmp io_clear_eol

@h_col: ; C (PETSCII $C3) — color
        jsr skip_sp_ptr1
        ldx #0
@C_count:
        txa
        tay
        jsr is_hex_at_ptr1
        beq @C_eoi
        inx
        cpx #3
        bcc @C_count
@C_eoi:
        ; Reject trailing garbage BEFORE any color is applied (Escape
        ; Analysis class-wide via shared helper).  X = digit count;
        ; check the region from rp_ptr+X onward for NUL/';' (with
        ; optional whitespace).  Non-whitespace after the digits is
        ; a syntax error — discards the command without touching theme.
        stx rp_save
        txa
        tay
        jsr _require_eoi_or_err
        ldx rp_save             ; restore digit count for apply dispatch
@C_apply:
        cpx #1
        beq @C_one
        cpx #2
        beq @C_two
        cpx #3
        bne @C_show
        ; three digits: border bg fg
        ldy #0
        jsr hex_val_at_ptr1
        sta theme_border
        iny
        jsr hex_val_at_ptr1
        sta theme_bg
        iny
        jsr hex_val_at_ptr1
        sta theme_fg
        jsr restore_colors
        jmp @C_show
@C_two:
        ldy #0
        jsr hex_val_at_ptr1
        sta theme_bg
        iny
        jsr hex_val_at_ptr1
        sta theme_fg
        jsr restore_colors
        jmp @C_show
@C_one:
        ldy #0
        jsr hex_val_at_ptr1
        sta theme_fg
        jsr restore_colors
@C_show:
        jsr show_theme_colors
        jmp io_clear_eol

@h_u:   ; u — cpu mode
        jsr skip_peek_ptr1
        cmp #'6'
        bne @u_show
        iny
        lda (rp_ptr),y
        cmp #'5'
        bne @u_show
        iny
        lda (rp_ptr),y
        sta rp_tmp
        iny
        lda (rp_ptr),y
        sta rp_tmp2
        ldx #0
@u_scan:
        lda cpu_pair_tbl,x
        cmp rp_tmp
        bne @u_next
        lda cpu_pair_tbl+1,x
        cmp rp_tmp2
        bne @u_next
        lda cpu_pair_tbl+2,x
        tay
        lda cpu_mask_bits,y
.ifdef CMOS_SUPPORT
        and #5
.elseif .defined(CPU_6510)
        and #3
.else
        and #1
.endif
        beq @u_show
        tya
        sta asm_cpu
        jmp @u_show
@u_next:
        txa
        clc
        adc #3
        tax
        cpx #9
        bcc @u_scan

@u_show:
        ldy #LOG_INFO
        jsr log_open
        puts str_cpu
        lda asm_cpu
        bne @u_no_star0
        lda #'*'
        jmp @u_p0
@u_no_star0:
        lda #' '
@u_p0:  jsr io_putc
.ifdef CPU_6510
        puts str_6510
        lda asm_cpu
        cmp #1
        bne @u_no_star1
        lda #'*'
        jmp @u_p1
@u_no_star1:
        lda #' '
@u_p1:  jsr io_putc
.endif
.ifdef CMOS_SUPPORT
        puts str_65c02
        lda asm_cpu
        cmp #2
        bne @u_no_star2
        lda #'*'
        jmp @u_p2
@u_no_star2:
        lda #' '
@u_p2:  jsr io_putc
.endif
        jmp log_close   
@h_a:   ; a — assemble source.  With an active debug session this
        ; path is stack-heavy (measured ~130 B for nested exprs); gate
        ; by ending the debug session + replaying the command.
        lda dbg_reason
        beq @a_run
        jsr warn_if_debug
        lda #<str_asm
        ldx #>str_asm
        jsr query_user
        bcc @a_cancel
        lda #1
        sta warm_cont           ; replay line_buf after end-debug
        jmp cse_end_debug
@a_cancel:
        jmp nl_clear
@a_run:
        ldy #LOG_INFO
        jsr log_open        ; "; "
        puts str_asm_ing        ; "asm..."
        jsr log_close           ; close line, advance to next row
        lda cur_addr
        ldx cur_addr+1
        jsr asm_assemble       ; A/X = error count
        sta rp_cnt
        stx rp_cnt+1
        ora rp_cnt+1
        bne @a_errors
        ; success — segments already printed during pass 1
        lda #0
        sta dbg_reason
        ; Print "; ok" on its own line
        ldy #' '                ; LOG_INFO
        jsr log_open
        puts str_ok
        jsr log_close
        ; Print executable save command (handles its own newline)
        jsr seg_print_save
        ; sym_lookup("main") — ZP interface
        lda #<str_main
        sta sym_name
        lda #>str_main
        sta sym_name+1
        jsr sym_set_curaddr
        jmp @a_tail
@a_errors:
        ldy #LOG_INFO
        jsr log_open
        lda rp_cnt
        ldx rp_cnt+1
        jsr io_putdec
        puts str_errors
        jsr log_close
@a_tail:
        jmp io_clear_eol
@h_calc:; ? — calculator
        lda rp_ptr
        sta expr_ptr
        lda rp_ptr+1
        sta expr_ptr+1
        jsr expr_eval
        sta rp_save             ; rc
        cmp #2
        jcs @calc_err

        ; Single-expression command — reject trailing garbage
        ; (Escape Analysis class-wide, via shared helper).
        ; expr_eval advanced expr_ptr, not rp_ptr — sync first.
        lda expr_ptr
        sta rp_ptr
        lda expr_ptr+1
        sta rp_ptr+1
        ldy #0
        jsr _require_eoi_or_err

        ; hex display
        ldy #LOG_INFO
        jsr log_open
        lda expr_val+1
        bne @calc_16bit
        jsr calc_put_u8_hex
        jmp @calc_dec
@calc_16bit:
        lda expr_val
        bne @calc_16bit_real
        jsr calc_put_u8_hex
        jmp @calc_dec
@calc_16bit_real:
        lda #'$'
        jsr io_putc
        lda expr_val
        ldx expr_val+1
        jsr io_puthex4

@calc_dec:
        ; decimal: "  " then 5-digit space-padded
        puts str_2sp
        lda expr_val
        ldx expr_val+1
        sec                     ; padded
        jsr io_putdec_pd

        ; 8-bit extras if val < 256
        lda expr_val+1
        jne @calc_done
        ; binary
        puts str_pct
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
        ldx #2
        jsr io_repc
        lda expr_val
        bpl @sign_pos
        ; negative
        lda #'-'
        jsr io_putc
        lda #0
        sec
        sbc expr_val
        jmp @do_signed
@sign_pos:
        lda #'+'
        jsr io_putc
        lda expr_val
@do_signed:
        ldx #0                  ; hi = 0 (8-bit value)
        jsr io_putdec

@calc_done:
        jmp log_close   

@calc_err:
        ldy #LOG_ERR
        jsr log_open
        puts str_expr
        jsr expr_error_str
        jsr io_puts
        jmp log_close   
@h_quit:; Q (PETSCII $D1) — quit (warn + confirm)
        jsr warn_if_unsaved
        lda #<str_quit
        ldx #>str_quit
        jsr query_user
        bcc @q_cancel
        lda #ST_STOP
        sta state
        rts
@q_cancel:
        jmp nl_clear
@h_reset:
        ; R — warmstart (uppercase).  Always prompts.  With an
        ; active debug session: ";!debug" + "end debug? y/n".
        ; Without: "init? y/n".  On yes: end_debug_body (if active)
        ; + jmp cse_refresh.  No continuation (warm_cont stays 0).
        lda dbg_reason
        beq @reset_init
        ; active debug path
        jsr warn_if_debug
        lda #<str_end_dbg
        ldx #>str_end_dbg
        jsr query_user
        bcc @r_cancel
        jsr end_debug_body
        jmp cse_refresh
@reset_init:
        lda #<str_init
        ldx #>str_init
        jsr query_user
        bcc @r_cancel
        jmp cse_refresh
@r_cancel:
        jmp nl_clear
@h_dir: ; $ — directory
        jsr skip_peek_ptr1
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
        ; Print drive status on the trailing blank line
        jsr floppy_read_status
        lda #';'
        jsr io_putc
        lda #' '
        jsr io_putc
        puts fl_buf
        jsr io_clear_eol
        jmp nl_clear
@h_x:   ; x — clear screen
        jsr reset_screen
        jmp io_clear_eol

@h_c:   ; c — continue debugger
        lda dbg_reason
        bne @c_has_ctx
        lda #<str_no_ctx
        ldx #>str_no_ctx
        jmp log_err   
@c_has_ctx:
        ; delete hit breakpoint before continuing
        lda dbg_bp_hit
        cmp #$FF
        beq @c_enter
        jsr dbg_bp_del
@c_enter:
        ; Drain KERNAL keyboard buffer.
        lda #0
        sta $C6
        ; Resume (reuse existing sentinel from the prior fresh start).
        lda #MODE_RESUME
        sta run_user_pending
        rts

; ── Command dispatch table (parallel arrays) ──
@cmd_chars:
        .byte '.', 'd', 'm', 'b', 'r', 'l', 's', 'i'
        .byte '@', '+', '-', 'j', 'g', 't', 'o', 'k'
        .byte $C2, $C3, 'u', 'a', '?', $D1, '$', 'x'
        .byte 'c', $D2
        .byte 0                 ; sentinel
@cmd_lo:
        .byte <@h_dot, <@h_d, <@h_m, <@h_b, <@h_r, <@h_l, <@h_s, <@h_i
        .byte <@h_at, <@h_plus, <@h_minus, <@h_j, <@h_g, <@h_t, <@h_o, <@h_k
        .byte <@h_blk, <@h_col, <@h_u, <@h_a, <@h_calc, <@h_quit, <@h_dir, <@h_x
        .byte <@h_c, <@h_reset
@cmd_hi:
        .byte >@h_dot, >@h_d, >@h_m, >@h_b, >@h_r, >@h_l, >@h_s, >@h_i
        .byte >@h_at, >@h_plus, >@h_minus, >@h_j, >@h_g, >@h_t, >@h_o, >@h_k
        .byte >@h_blk, >@h_col, >@h_u, >@h_a, >@h_calc, >@h_quit, >@h_dir, >@h_x
        .byte >@h_c, >@h_reset
.endproc

; ═══════════════════════════════════════════════════════════
; post_run_cleanup — called from main_loop_top after a userland
; break has longjmped back (dbg_reason != 0, step_state != 0, or
; run_user_pending != 0).
;
; Note: KERNAL/VIC hygiene (`hygiene_after_userland`) runs
; unconditionally in `handler_finalize` on EVERY return from
; userland, so colour/VIC state is always restored.  This routine
; only handles break-result display and step cleanup.
;
; Responsibilities:
;   * If we were stepping: clear step_state / step_remaining, zero
;     step_bp slots, re-enable any bp cmd_step disabled, show
;     break result.  If stopping opcode is RTS/RTI, clear last_cmd
;     (so RETURN doesn't repeat the step).
;   * Else show break result (dbg_reason picks the tag;
;     show_break_result handles the rts-through-sentinel case).
; ═══════════════════════════════════════════════════════════
; Stack headroom budget — must match main.s::kernel_stack_budget.
; See userland_contract.md § Kernel stack budget.  Kept as a local
; literal rather than an import so the repl-only test harness (which
; doesn't link main.s) can build unchanged.
KSTK_MIN = 64

.proc post_run_cleanup
        ; B3: stack headroom warning.  If user's SP at break is below
        ; the documented kernel-reentry budget, log ";!stk N" where N
        ; is the remaining headroom (reg_sp as decimal).
        lda reg_sp
        cmp #KSTK_MIN
        bcs @stk_ok
        ldy #LOG_WARN
        jsr log_open
        puts str_stk_warn
        lda reg_sp
        ldx #0
        jsr io_putdec
        jsr log_close
@stk_ok:
        lda step_state
        beq @not_step

        ; Stepping just finished.
        lda #STEP_NONE
        sta step_state
        sta step_remaining
        jsr dbg_step_clear
        ; Re-enable any bp cmd_step disabled.
        ldx rp_dis_bp
        cpx #$FF
        beq :+
        lda #1
        sta bp_table+3,x
:       lda #$FF
        sta rp_dis_bp
        ; Always show full break result.
        jsr show_break_result
        ; Clear last_cmd if stopped on RTS/RTI (prevents RETURN repeat).
        jsr peek_brk_opcode
        cmp #$60
        beq @clr_last
        cmp #$40
        bne @done
@clr_last:
        lda #0
        sta last_cmd
@done:  rts

@not_step:
        jmp show_break_result
.endproc
