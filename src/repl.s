; repl.s — REPL command line interface
; Owner: doc/modules/repl.md
;
; The screen IS the command buffer.  Press RETURN on any line
; to execute it.  AAAA:cmd [args] for addressed commands,
; cmd [args] for bare commands.  ';' ends parsing.

        .setcpu "6502"
        .include "platform.inc"
        .include "bp.inc"               ; the breakpoint slot's layout
        .macpack longbranch
        .include "macros.inc"

; ── Exports ────────────────────────────────────────────────
        .export exec_line, read_line, show_prompt, cmd_info
        .export cur_addr, block_size
.ifdef PLATFORM_M65
        .export cur_flat
.endif
        .export line_buf, last_cmd, cold_preview_done
        .export step_cleanup

; ── Imports: log.s ─────────────────────────────────────────
        .import log_open, log_close
        .import log_err, log_warn, log_info
        .import prg_line, free_line
        .import info_line, info_line_head, info_line_tail
        .import puts_imm

; ── Imports: zp.s ──────────────────────────────────────────
        .importzp rp_addr, rp_cnt, rp_save, rp_save2
        .importzp rp_next_lo, _info_mode
        .importzp cur_device
.ifdef PLATFORM_C64
        .importzp cur_project_name
.else
        .import cur_project_name        ; zp.s's BSS (zp.md)
.endif

; ── Imports: cse_io.s ──────────────────────────────────────
        .import io_putc, io_repc, io_puts, scr_to_pet
        .import io_puthex4, io_puthex2, io_putdec, io_putdec_pd
        .import io_clear_eol
        .import io_getc, io_sync
        .import cursor_show, cursor_hide
        .import scr_lo, scr_hi

; ── Imports: screen.s ──────────────────────────────────────
        .import newline, restore_colors, reset_screen, vic_reset
        .import kernal_screen_reset
        .import theme_border, theme_bg, theme_fg

; _hex_val, _is_hex, _hex_val_to_char are local (below)

; ── Imports: assembler / disassembler ──────────────────────
        .import asm_line, asm_err_code, asm_pass
        .import dasm_insn_pre, _dasm_in, dasm_buf
        .importzp _dasm_ptr
        .include "cpu_set.inc"  ; INSN_MAX (hex pairs / columns), MODE_*,
                                ; the set's HAS_ZONE_D
.ifdef MEGA_SUPPORT
        .import asm_rel16
        .importzp _dasm_mode
.endif
        .import asm_assemble, seg_print_save

; ── Imports: debugger ──────────────────────────────────────
        .import dbg_step_clear
        .import dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .import bp_table
.ifdef PLATFORM_M65
        .import dbg_bp_set_flat         ; breakpoints.s: a flat slot
.endif
        .importzp dbg_reason
        .import dbg_bp_hit
        .import brk_pc, brk_stub
        .import reg_a, reg_x, reg_y, reg_sp, reg_p
.ifdef PLATFORM_M65
        .import reg_z, reg_b, str_z, str_b
.endif
.ifdef PLATFORM_C64
        .import userland_zp_buf
.else
        .importzp userland_zp_buf       ; zp.s: the CPU port's image
.endif
        .import step_state, step_remaining
        .import step_next_pc, arm_step_bp
        .import step_next_lo, step_next_hi

; ── Imports: main.s (kernel→userland dispatch) ───────────────
        .import run_user_pending, stop_cooldown
        .import cse_refresh, cse_end_debug
        .import end_debug_body
        .importzp warm_cont
        ; MODE_NONE, MODE_JUMP, MODE_RESUME constants are defined in
        ; main.s; redefine here (ca65 doesn't import equates).
MODE_NONE   = 0
MODE_JUMP   = 1
MODE_RESUME = 2

        ; dbg_reason enum — one definition, shared with main.s.
        .include "dbg_reason.inc"

; ── Imports: debugger step modes (match debugger.s values) ───
STEP_NONE = 0
STEP_INTO = 1
STEP_OVER = 2

; ── Exports: post-run cleanup (called from main_loop_top) ────
        .export post_run_cleanup
        .export step_targets_check
        .export hygiene_after_userland

; ── Imports: expression parser ─────────────────────────────
        .import expr_eval, expr_error_str
.ifdef PLATFORM_M65
        .import expr_eval32, expr_bank, asm_def_bank, last_err
        .importzp expr_wide
ERR_RANGE = 7                   ; expr.s's rc 7
.endif
        .importzp expr_ptr, expr_val

; ── Imports: symbol table ──────────────────────────────────
        .import sym_lookup
        .importzp sym_name, sym_val

;── Imports: disk I/O ──────────────────────────────────────
        .import floppy_read_status, fl_buf
        .import list_directory
        .import disk_load_prg, disk_save_prg

; ── Imports: editor ────────────────────────────────────────
        .import ed_save_source, ed_load_source
        .import ed_save_bytes, ed_save_lines
        .import ed_ensure_init, ed_new
        .importzp ed_dirty
        .import ed_total_lines
        .import ed_read_rewind, ed_read_byte
        .importzp buf_base

; ── Imports: memory info ───────────────────────────────────
        .import cse_start, cse_end
        .import src_top, src_bot
.ifdef PLATFORM_M65
        .import far_user, far_user_w, far_write_ok, lens_kind ; mem.s
        .import run_bank, seed_bank_state       ; debugger.s (far starts)
        .importzp lens_ptr, um_map, um_d030     ; zp.s (the CPU lens)
.endif

; ── Imports: global state ──────────────────────────────────
        .importzp state
        .importzp asm_cpu

; ── Imports: strings.s ────────────────────────────────────
        .import str_flag_ch, str_bp_pfx, str_3sp, str_2sp, str_brk
        .import str_at, str_nmi, str_bp_clr, str_deleted
        .import str_rts, str_stk_warn, str_debug, str_qynq, str_dbg
        .import str_syntax, str_cpu_err, str_bad_val, str_full, str_cmd
        .import str_range, str_fail, str_too_big
        .import str_expr, str_no_ctx
        .import str_r_pc, str_a, str_x, str_y, str_s
        .import str_lines, str_bytes, str_long
        .import str_unsaved, str_ok, str_blk_eq
        .import str_del_src, str_quit, str_load
        .import str_init, str_asm, str_go
        .import str_color, str_cpu
        .import str_asm_ing, str_load_pfx, str_save_pfx, str_dots
        .import s_save_default
        .import str_errors, str_dashes, str_colon_sp, str_pct
        .import str_main
        .import str_tag_cse, str_tag_work
        .import str_tag_src, str_tag_low, str_tag_zp
.ifdef PLATFORM_C64
        .import str_ioport, str_stack, str_kernal, str_screen
        .import str_cse_rt, str_io
        .import str_tag_cpu, str_tag_stk, str_tag_sys
        .import str_tag_scr, str_tag_io
        .import str_tag_rom, str_banked
.else
        .import str_tag_ext, str_base, str_code, str_data
        .import info_bank
.endif
        .import cpu_names, cpu_lookup   ; asm_src.s: the build's CPU set

; ── Imports: runtime ZP ────────────────────────────────────
        .importzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2
        .importzp asm_pc, asm_out
        .importzp disk_ptr, _io_tmp

; ── Constants ──────────────────────────────────────────────
FILENAME_MAX  = 16
ST_STOP       = 0

; ═══════════════════════════════════════════════════════════
; ZP: rp_ptr = q (parse pointer into line_buf or args)
;     rp_ptr2 = secondary pointer (output buffer, data src)
;     rp_tmp, rp_tmp2 = scratch bytes
;
; More scratch (zp.s unless noted):
;   rp_addr (2) — address argument (cur_addr copy for commands)
;   rp_save (1) — saved byte (olen, cols, etc.)
;   rp_save2(1) — secondary scratch
;   rp_cnt  (2) — 16-bit counter
;   rp_next_lo (zp.s) / rp_next_hi (BSS below) (2+2) — secondary
;                          16-bit scratch pair; save/load use them
;                          for name pointers and addresses
; ═══════════════════════════════════════════════════════════

; ── BSS ────────────────────────────────────────────────────
; Initialized by main.s (reset_globals) or by first use.  BSS is
; zeroed at boot.
.segment "BSS"

cur_addr:      .res 2          ; current memory address (init by main.s)
.ifdef PLATFORM_M65
; The address spaces (repl.md § Banks): the current address's and the
; command's (rp_addr's).  A flag is $80 for a flat address (bit 7: bit /
; bmi keep A), 0 for a CPU address; a bank word is a flat address's
; bits 16-27 (bank, megabyte).  SPC_CUR / SPC_RP index the block.
spc:
cur_flat:       .res 1
cur_bank:       .res 2
rp_flat:        .res 1
rp_bank:        .res 2
tmp_flat:       .res 1          ; `M`'s rows: a flat address to print
tmp_bank:       .res 2
SPC_CUR = cur_flat - spc
SPC_RP  = rp_flat - spc
SPC_TMP = tmp_flat - spc
map_start:      .res 1          ; `M`: the run's first and last 4 K page,
map_end:        .res 1
map_kind:       .res 1          ;   its kind (lens_kind)
map_flat:       .res 3          ;   its flat bytes 1-3 at the first page
map_next:       .res 3          ;   and those the next page continues
SPC_FLAT = $80
fl_acc:         .res 2          ; parse_flat_ptr1: the digits before the dot
fl_y:           .res 1          ;   and the offset's first digit
ta_flat:        .res 1          ; bit 7: the next try_expr reads an address
ta_mode:        .res 1          ;   (try_addr_or_err); this call's copy
.endif
last_cmd:       .res 1          ; last command byte
cur_save:       .res 2          ; `j` / `g`: cur_addr before the start
.ifdef PLATFORM_M65
cur_save_spc:   .res 3          ;   and its space (cur_flat, cur_bank)
.endif
block_size:     .res 2          ; block size for I/O (init by main.s)
disk_name_buf:     .res FILENAME_MAX + 2   ; composed disk name (stem + optional ".")
_verbatim_type:    .res 1          ; 0 / 's' / 'p' from strip_and_classify
_arg_count:        .res 1          ; 0, 1, or 2 — numeric args in last parse

line_buf:       .res 2 + SCREEN_WIDTH_MAX
rp_next_hi:     .res 2          ; 16-bit scratch pair (rp_next_lo lives in zp.s)
rp_opc:         .res 1          ; saved opcode (cmd_dot / emit_hex_cols)
rp_dis_bp:      .res 1          ; cmd_step: disabled bp slot*SLOT_SIZE ($FF=none)
rp_hexbuf:      .res INSN_MAX    ; cmd_dot hex byte parse
cold_preview_done: .res 1       ; cold-preview marker.  Set by
                                ; cmd_step's cold-preview branch
                                ; (alongside dbg_reason promotion to
                                ; DBG_BRK), consumed and cleared by
                                ; set_run_mode (the next t/o/c) to
                                ; force MODE_JUMP — the first real run
                                ; after a cold preview must push a
                                ; fresh sentinel (the preview itself
                                ; never crossed the gate).  Cleared
                                ; by main.s's end_debug_body too.

zp_stage_buf:   .res MEM_ROW_MAX ; staging buffer for the user-ZP
                                ; read redirect — `m` dump (a row) and
                                ; `.` disasm (INSN_MAX B).  See repl.md
                                ; § User-ZP view.

; ── RODATA ─────────────────────────────────────────────────
.segment "RODATA"

; r command field labels: reg_a / reg_x / reg_y / reg_sp order, then pc
reg_labels:      .byte "axysp"      ; reg_a + index; 'p' is pc:
.ifdef PLATFORM_M65
                 .byte "zb"         ; m65: reg_z, reg_b (asm_line.s order)
REG_LABEL_LAST = 6
.else
REG_LABEL_LAST = 4
.endif

; ── info tables: 8 bytes per row: tag(2) lo(2) hi(2) desc(2) ──
; These stay in repl.s because INFO_TBL_*_ROWS are compile-time
; constants computed from segment arithmetic (can't be imported).
; One data block per platform (doc/platform_layer.md § Info map):
; the fixed rows and the bounds of the fixed free holes.

.ifdef PLATFORM_C64
INFO_ZP_LO      = $02           ; zp   0002-007f  free (the user ZP)
INFO_ZP_HI      = $7F
INFO_LOW1_LO    = $02A7         ; low  02a7-02ff  free
INFO_LOW1_HI    = $02FF
INFO_LOW2_LO    = $0334         ; low  0334-03ff  free
INFO_LOW2_HI    = $03FF

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
.else
; m65: memory_design.md § Memory Map — m65's bank table, each row with
; its bank.  9 bytes per row: tag(2) lo(2) hi(2) desc(2; 0 = a free
; row, its size computed) bank(1).  Part A is banks 0 and 1, part B
; the rest; the bank-4 row is left out in 80 × 50, whose screen is
; there (4.0800-4.179F).
INFO_M65_ROW    = 9
info_m65:
        .addr str_tag_zp,   $000A,   $008F,   0         ; BASIC 65's base page
        .byte BANK_USER
        .addr str_tag_zp,   $00FB,   $00FF,   0         ; the free top of it
        .byte BANK_USER
        .addr str_tag_low,  $1600,   $1EFF,   0         ; free for programs
        .byte BANK_USER
        .addr str_tag_cse,  CSE_BP << 8, $1FFF, str_base  ; base page + stub
        .byte BANK_USER
        .addr str_tag_work, PROG_LO, PROG_HI, 0         ; the program region
        .byte BANK_USER
        .addr str_tag_ext,  $2000,   $F6FF,   0         ; above the DOS buffers
        .byte 1
INFO_M65_A = * - info_m65
        .addr str_tag_cse,  $2000,   $7FFF,   str_code  ; CODE + RODATA
        .byte BANK_CSE
        .addr str_tag_cse,  $8000,   $BFFF,   str_data  ; KDATA, BSS, homes
        .byte BANK_CSE
INFO_M65_BANK4 = * - info_m65
        .addr str_tag_ext,  $0000,   $FFFF,   0
        .byte 4
INFO_M65_BANK5 = * - info_m65
        .addr str_tag_ext,  $0000,   $FFFF,   0
        .byte 5
INFO_M65_END = * - info_m65
.endif

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
        sta IO_CX
.ifdef PLATFORM_M65
        ldx #SPC_RP
        jsr put_bank
.endif
        lda rp_addr
        ldx rp_addr+1
        jsr io_puthex4
        lda #':'
        jsr io_putc
        pla
        jmp io_putc

; Logging API (log_open / log_close / log_line / log_err / log_warn /
; log_info) lives in log.s; repl.s imports them.  log.inc provides
; the LOG_ERR/WARN/INFO level constants.
.include "log.inc"

; ── The address spaces (m65; repl.md § Banks) ─────────────────────────
; SPACE_CPU: the current and the command address are CPU addresses —
; at every site that sets them from a CPU source.  A kept.
.macro SPACE_CPU
  .ifdef PLATFORM_M65
        jsr space_cpu
  .endif
.endmacro

; FAR_CUR name: the pointer's offset holds rp_addr's low word; set its
; bank and megabyte for the command's space (platform_layer.md § Far
; memory).  c64: empty, as FAR_USER.
.macro FAR_CUR name
  .ifdef PLATFORM_M65
        ldx #name
        jsr far_cur
  .endif
.endmacro

; FAR_CUR_W name: the same for a write — in CPU space where the program's
; CPU would write (far_user_w: the RAM beneath a ROM it sees).
.macro FAR_CUR_W name
  .ifdef PLATFORM_M65
        ldx #name
        jsr far_cur_w
  .endif
.endmacro

; RP_CARRY: rp_addr's low word wrapped — a flat address carries into its
; bank.  Clobbers A, N/Z.
.macro RP_CARRY
  .ifdef PLATFORM_M65
        jsr rp_carry
  .endif
.endmacro

; CUR_FROM_RP: the command's space becomes the current address's (an
; advance: the offset is stored by the site).  Clobbers A, X.
.macro CUR_FROM_RP
  .ifdef PLATFORM_M65
        jsr cur_from_rp
  .endif
.endmacro

.ifdef PLATFORM_M65
.segment "KCODE"                        ; m65 code in the data window
; The bodies of SPACE_CPU (A kept), RP_CARRY (A) and CUR_FROM_RP (A, X
; clobbered); every one keeps C.
space_cpu:
        pha
        lda #0
        sta cur_flat
        sta rp_flat
        pla
        rts
rp_carry:
        bit rp_flat
        bpl @r
        inc rp_bank
        bne @r
        inc rp_bank+1
@r:     rts
cur_from_rp:
        ldx #2
@cp:    lda rp_flat,x
        sta cur_flat,x
        dex
        bpl @cp
        rts

; ───────────────────────────────────────────────────────────
; far_cur — FAR_CUR's body.  In: X = the pointer's base-page offset.
; Flat space: bank and megabyte from rp_bank; CPU space: far_user.
; Preserves A, Y, P.
; ───────────────────────────────────────────────────────────
far_cur_w:
        bit rp_flat
        bmi far_flat
        jmp far_user_w
far_cur:
        bit rp_flat
        bmi far_flat
        jmp far_user
far_flat:
        php
        pha
        lda rp_bank
        sta 2,x
        lda rp_bank+1
        sta 3,x
        pla
        plp
        rts

; ───────────────────────────────────────────────────────────
; cur_write_ok — may the command write at rp_addr?  C=0 yes; C=1 the
; byte the program's CPU would write there (or the flat byte) is in
; the ROM banks 2-3 (far_write_ok).  Clobbers A, X.
; ───────────────────────────────────────────────────────────
cur_write_ok:
        lda rp_addr
        sta lens_ptr
        lda rp_addr+1
        sta lens_ptr+1
        ldx #lens_ptr
        jsr far_cur_w
        jmp far_write_ok

; run_write_ok — cur_write_ok for a run of A bytes (1-16) from
; rp_addr: its first and its last byte (a flat run carrying into the
; next bank, a CPU run wrapping at $FFFF) — a run crosses at most one
; bank or 4 K page edge.  C=1: refuse the whole run.  Clobbers A, X.
run_write_ok:
        pha
        jsr cur_write_ok        ; the first byte
        pla
        bcs @r
        tax
        dex                     ; n - 1
        txa
        clc
        adc rp_addr
        sta lens_ptr
        lda rp_addr+1
        adc #0
        sta lens_ptr+1
        php                     ; C: carried past $FFFF
        ldx #lens_ptr
        jsr far_cur_w           ; flat: rp_bank; CPU: the lens
        plp
        bcc @chk
        bit rp_flat
        bpl @chk                ; a CPU address wraps within 64 K
        inc lens_ptr+2          ; a flat one: the next bank
        bne @chk
        inc lens_ptr+3
@chk:   ldx #lens_ptr
        jmp far_write_ok
@r:     rts

; ───────────────────────────────────────────────────────────
; lens_stage — a CPU-space row through the CPU's lens (mem.md
; § far_user): every byte rp_addr + Y (16-bit, wrapping) of
; MEM_ROW_MAX translated on its own — the user-ZP view at $00/$01 —
; into zp_stage_buf; rp_ptr2 points there (BANK_CSE).
; Clobbers: A, X, Y.
; ───────────────────────────────────────────────────────────
lens_stage:
        ldy #0
@lp:    jsr lens_at_y           ; C=1: X = the port image's index
        bcc @far
        lda userland_zp_buf,x
        bcs @st                 ; always
@far:   ldx #lens_ptr
        jsr far_user
        sty rp_tmp
        ldy #0
        FAR_LDA lens_ptr
        ldy rp_tmp
@st:    sta zp_stage_buf,y
        iny
        cpy #MEM_ROW_MAX
        bcc @lp
        lda #<zp_stage_buf
        sta rp_ptr2
        lda #>zp_stage_buf
        sta rp_ptr2+1
        FAR_BANK rp_ptr2, BANK_CSE
        rts

; lens_poke — zp_poke in CPU space: A to rp_addr + Y where the
; program's CPU would write it (the user-ZP image at $00/$01); a byte
; that would land in banks 2-3 is not written.  Preserves A, Y.
lens_poke:
        pha
        jsr lens_at_y
        bcc @far
        pla
        sta userland_zp_buf,x
        rts
@far:   ldx #lens_ptr
        jsr far_user_w
        jsr far_write_ok
        pla
        bcs @r
        sty rp_tmp
        ldy #0
        FAR_STA lens_ptr
        ldy rp_tmp
@r:     rts

; lens_at_y — lens_ptr := rp_addr + Y (16-bit, untranslated); C=1
; when that is the port ($00/$01: X = its index), else C=0.  Preserves Y.
lens_at_y:
        tya
        clc
        adc rp_addr
        sta lens_ptr
        lda rp_addr+1
        adc #0
        sta lens_ptr+1
        bne @no                 ; C=0 from the add (no wrap past $FFFF
        ldx lens_ptr            ;   leaves page 0 with C=1: page $00
        cpx #ZP_SAVE_LEN        ;   after a wrap is the port too)
        bcc @port
@no:    clc
        rts
@port:  sec
        rts

; dot_range — `;?range`: a write into the ROM banks (repl.md § Banks),
; refused before any byte; the `.` re-entry's width request dropped.
dot_range:
        lda #0
        sta asm_rel16
        lda #<str_range
        ldx #>str_range
        jmp log_err

; ───────────────────────────────────────────────────────────
; put_bank — the flat prefix `H.` of an address, if it is flat.
; In: X = SPC_CUR or SPC_RP.  Prints the bank word's digits (one to
; three: the megabyte nibble when nonzero, then the bank — one digit
; below $10) and the dot; nothing for a CPU address.
; Clobbers: A, X, Y.
; ───────────────────────────────────────────────────────────
.proc put_bank
        lda spc,x
        bpl @r
        lda spc+2,x
        and #$0F
        beq @no_mb
        stx rp_tmp
        jsr _hex_val_to_char
        jsr io_putc
        ldx rp_tmp
        lda spc+1,x
        jsr io_puthex2
        jmp @dot
@no_mb: lda spc+1,x
        cmp #$10
        bcc @one
        jsr io_puthex2
        jmp @dot
@one:   jsr _hex_val_to_char
        jsr io_putc
@dot:   lda #'.'
        jmp io_putc
@r:     rts
.endproc

; ───────────────────────────────────────────────────────────
; parse_flat_ptr1 — a flat literal at rp_ptr: one to four hex digits
; (a value up to $FFF: the bank word), a dot, four hex digits.  Not
; advanced.  Out: C=0, Y = its length, rp_addr = the offset, rp_bank =
; the bank word; C=1: no flat literal there (rp_addr, rp_bank kept).
; (An argument's flat literal is the expression evaluator's, F5c:
; try_addr_or_err.)  Clobbers: A, X, Y, rp_tmp2.
; ───────────────────────────────────────────────────────────
parse_flat_ptr1:
        ldy #0
        sty fl_acc
        sty fl_acc+1
@dig:   jsr hex_val_at_ptr1     ; A = the nibble, $FF if none
        cmp #$10
        bcs @dot
        ldx #4
@sh:    asl fl_acc
        rol fl_acc+1
        dex
        bne @sh
        ora fl_acc
        sta fl_acc
        iny
        cpy #5
        bcc @dig
        bcs flat_no             ; five digits
@dot:   cpy #0
        beq flat_no
        lda fl_acc+1
        cmp #$10
        bcs flat_no             ; above $FFF
        FAR_LDA rp_ptr
        cmp #'.'
        bne flat_no
        iny
        sty fl_y
        ldx #4
@h4:    jsr is_hex_at_ptr1
        beq flat_no
        iny
        dex
        bne @h4
        jsr is_hex_at_ptr1      ; a fifth digit: not this shape
        bne flat_no
        lda rp_ptr              ; parse the offset where it begins
        pha
        lda rp_ptr+1
        pha
        lda fl_y
        jsr adv_ptr1
        jsr parse_hex4_ptr1     ; A = lo, X = hi
        sta rp_addr
        stx rp_addr+1
        pla
        sta rp_ptr+1
        pla
        sta rp_ptr
        lda fl_acc
        sta rp_bank
        lda fl_acc+1
        sta rp_bank+1
        lda fl_y
        clc
        adc #4
        tay                     ; C=0 from the add
        rts
flat_no:
        sec
        rts

; ───────────────────────────────────────────────────────────
; start_bank — a fresh start at the current address (repl.md § Far
; starts): run_bank := its bank when flat — 1, 4 or 5, the offset in
; $2000-$7FFF — or 0 (a CPU address, or bank 0: the plain start).
; C=1: a flat address outside the window (`;?range`).  Clobbers A.
; ───────────────────────────────────────────────────────────
start_bank:
        lda #0
        bit cur_flat
        bpl @set                ; a CPU address: the plain start
        lda cur_bank+1          ; a megabyte: no
        bne @no
        lda cur_bank
        beq @set                ; bank 0: the plain start
        cmp #1
        beq @win
        cmp #4
        beq @win
        cmp #5
        bne @no
@win:   ldx cur_addr+1          ; $2000-$7FFF: JSRFAR's window
        cpx #$20
        bcc @no
        cpx #$80
        bcs @no
@set:   sta run_bank
        clc
        rts
@no:    sec
        rts

; ───────────────────────────────────────────────────────────
; Breakpoints (slice 3, F4: debugger.md § b, breakpoints.md).
; slot_offset — A := slot A × SLOT_SIZE (6).  Clobbers nothing else.
slot_offset:
        asl
        sta fl_y
        asl
        adc fl_y                ; C=0: slot < 8
        rts

; bp_cpu_ok — bp_range_check's m65 body: the CPU address A/X through
; the program's bank state into lens_ptr, then bp_flat_ok.
bp_cpu_ok:
        sta lens_ptr
        stx lens_ptr+1
        ldx #lens_ptr
        jsr far_user
        jmp bp_flat_ok

; bp_flat_arg — lens_ptr := the flat address try_addr_or_err read
; (rp_addr, rp_bank), then bp_flat_ok.
bp_flat_arg:
        lda rp_addr
        sta lens_ptr
        lda rp_addr+1
        sta lens_ptr+1
        lda rp_bank
        sta lens_ptr+2
        lda rp_bank+1
        sta lens_ptr+3
; bp_flat_ok — is lens_ptr user memory a breakpoint may patch
; (userland_contract.md § 3 On m65): 0.2000-0.BFFF, 1.2000-1.F6FF,
; 4.0000-5.FFFF?  C=0 yes, C=1 no.  Clobbers A.
bp_flat_ok:
        lda lens_ptr+3          ; a megabyte: no
        bne @no
        lda lens_ptr+2
        beq @b0
        cmp #1
        beq @b1
        cmp #4
        beq @yes
        cmp #5
        beq @yes
@no:    sec
        rts
@b0:    lda lens_ptr+1
        cmp #$20
        bcc @no
        cmp #$C0
        bcs @no
@yes:   clc
        rts
@b1:    lda lens_ptr+1
        cmp #$20
        bcc @no
        cmp #$F7
        bcs @no
        bcc @yes

; put_rp_flat — rp_ptr's flat address as `H.AAAA`.  Clobbers A, X, Y.
put_rp_flat:
        lda rp_ptr+2
        ldy rp_ptr+3
        ldx rp_ptr
        stx fl_acc
        ldx rp_ptr+1
put_flat_axy:                   ; bank A, megabyte Y, offset fl_acc / X
        stx fl_acc+1
        sta tmp_bank
        sty tmp_bank+1
        lda #SPC_FLAT
        sta tmp_flat
        ldx #SPC_TMP
        jsr put_bank
        lda fl_acc
        ldx fl_acc+1
        jmp io_puthex4

; list_slot_flat — slot at offset X: C=1 empty; else its flat address
; printed, C=0.  Clobbers A, X, Y.
list_slot_flat:
        lda bp_table,x
        ora bp_table+1,x
        ora bp_table+2,x
        bne :+
        sec
        rts
:       lda bp_table,x
        sta fl_acc
        lda bp_table+2,x
        ldy bp_table+3,x
        pha
        lda bp_table+1,x
        tax
        pla
        jsr put_flat_axy
        clc
        rts

; ───────────────────────────────────────────────────────────
; parse_hexn — X hex digits at rp_ptr + Y into fl_acc (16-bit).
; Out: C=0, Y past them; C=1 a digit is not hex.  Clobbers A, X.
; ───────────────────────────────────────────────────────────
parse_hexn:
        lda #0
        sta fl_acc
        sta fl_acc+1
@d:     jsr hex_val_at_ptr1
        cmp #$10
        bcs @r
        pha
        lda #4
@sh:    asl fl_acc
        rol fl_acc+1
        sec
        sbc #1
        bne @sh
        pla
        ora fl_acc
        sta fl_acc
        iny
        dex
        bne @d
        clc
@r:     rts

; ───────────────────────────────────────────────────────────
; put_map_regs — " ml:XXXX mh:XXXX": the program's MAPLO (X, A) and
; MAPHI (Z, Y), as `r` shows them.  Clobbers A, X, Y.
; ───────────────────────────────────────────────────────────
put_map_regs:
        puts str_ml
        lda um_map              ; X
        jsr io_puthex2
        lda um_map+1            ; A
        jsr io_puthex2
        puts str_mh
        lda um_map+2            ; Z
        jsr io_puthex2
        lda um_map+3            ; Y
        jmp io_puthex2

; ───────────────────────────────────────────────────────────
; map_reg_field — `r`'s `ml:XXXX` / `mh:XXXX` at rp_ptr (Y = 0, the
; `m`); C=1 malformed.  rp_save2 != 0: into um_map (ml: X A, mh: Z Y).
; Clobbers A, X, Y, rp_save.
; ───────────────────────────────────────────────────────────
map_reg_field:
        ldy #1
        FAR_LDA rp_ptr
        ldx #0
        cmp #'l'
        beq :+
        ldx #2
        cmp #'h'
        bne @err
:       stx rp_save
        iny
        FAR_LDA rp_ptr
        cmp #':'
        bne @err
        iny
        ldx #4
        jsr parse_hexn
        bcs @err
        jsr is_eow_at_ptr1_y
        bne @err
        tya
        jsr adv_ptr1
        lda rp_save2
        beq @ok
        ldx rp_save
        lda fl_acc+1
        sta um_map,x
        lda fl_acc
        sta um_map+1,x
@ok:    clc
        rts
@err:   sec
        rts

; ───────────────────────────────────────────────────────────
; cmd_map — `M` (repl.md § Banks, *The map in r and M*): fields
; `mb:LLUU` (the megabyte selectors) and `d030:XX` set the program's
; bank state first (checked, then applied, as `r`'s); then one row per
; run of 4 K pages with one translation and kind, and the editable row
; `M mb:LLUU d030:XX`.
; ───────────────────────────────────────────────────────────
cmd_map:
        jsr skip_peek_ptr1
        beq @list
        cmp #';'
        beq @list
        lda rp_ptr
        sta rp_addr
        lda rp_ptr+1
        sta rp_addr+1
        lda #0
        sta rp_save2            ; pass 1: check only
        jsr map_fields
        bcc :+
        jmp _syntax_err
:       lda rp_addr
        sta rp_ptr
        lda rp_addr+1
        sta rp_ptr+1
        inc rp_save2            ; pass 2: apply
        jsr map_fields
@list:  lda #0                  ; log_open moves past the command row
        sta map_start
@pg:    tax                     ; A = the page
        asl
        asl
        asl
        asl
        sta lens_ptr+1
        lda #0
        sta lens_ptr
        txa
        pha
        ldx #lens_ptr
        jsr far_user
        pla
        tax
        cpx map_start
        beq @new                ; page 0: the first run
        lda lens_kind
        cmp map_kind
        bne @flush
        ldy #2
@cmp:   lda BP_ABS(lens_ptr+1),y
        cmp map_next,y
        bne @flush
        dey
        bpl @cmp
        stx map_end             ; continues the run
        jmp @adv
@flush: txa
        pha
        jsr map_row
        pla
        tax
        stx map_start
@new:   stx map_end
        lda lens_kind
        sta map_kind
        ldy #2
@cp:    lda BP_ABS(lens_ptr+1),y
        sta map_flat,y
        sta map_next,y
        dey
        bpl @cp
@adv:   lda map_next            ; the next page continues at +$1000
        clc
        adc #$10
        sta map_next
        bcc :+
        inc map_next+1
        bne :+
        inc map_next+2
:       inx
        txa
        cmp #16
        bcc @pg
        jsr map_row
        lda #0                  ; the editable row: "M mb:LLUU d030:XX"
        sta IO_CX
        lda #$CD                ; M
        jsr io_putc
        puts str_mb
        lda um_map+4
        jsr io_puthex2
        lda um_map+5
        jsr io_puthex2
        puts str_d030
        lda um_d030
        jsr io_puthex2
        jmp nl_clear

; map_row — "; map  AAAA-BBBB H.AAAA kind" for the run in map_*.
map_row:
        ldy #LOG_INFO
        jsr log_open
        puts str_map
        lda map_start
        asl
        asl
        asl
        asl
        tax
        lda #0
        jsr io_puthex4
        lda #'-'
        jsr io_putc
        lda map_end
        asl
        asl
        asl
        asl
        ora #$0F
        tax
        lda #$FF
        jsr io_puthex4
        lda #' '
        jsr io_putc
        lda #SPC_FLAT
        sta tmp_flat
        lda map_flat+1
        sta tmp_bank
        lda map_flat+2
        sta tmp_bank+1
        ldx #SPC_TMP
        jsr put_bank
        lda map_flat
        jsr io_puthex2
        lda #0
        jsr io_puthex2
        ldy map_kind            ; " mapped" / " rom" / " io"; RAM: none
        beq :+
        lda map_kind_lo,y
        ldx map_kind_hi,y
        jsr io_puts
:       jmp log_close

; map_fields — one pass over `M`'s fields (rp_save2: 0 check, 1 apply).
; C=1 a field is malformed.
map_fields:
@next:  jsr skip_peek_ptr1
        beq @ok
        cmp #';'
        beq @ok
        cmp #'m'
        beq @mb
        cmp #'d'
        bne @err
        ldx #3                  ; "d030:"
@d:     iny
        FAR_LDA rp_ptr
        cmp str_d030_tail,y
        bne @err
        dex
        bpl @d
        iny
        ldx #2
        jsr parse_hexn
        bcs @err
        jsr is_eow_at_ptr1_y
        bne @err
        tya
        jsr adv_ptr1
        lda rp_save2
        beq @next
        lda fl_acc
        sta um_d030
        jmp @next
@mb:    iny
        FAR_LDA rp_ptr
        cmp #'b'
        bne @err
        iny
        FAR_LDA rp_ptr
        cmp #':'
        bne @err
        iny
        ldx #4
        jsr parse_hexn
        bcs @err
        jsr is_eow_at_ptr1_y
        bne @err
        tya
        jsr adv_ptr1
        lda rp_save2
        beq @next
        lda fl_acc+1
        sta um_map+4
        lda fl_acc
        sta um_map+5
        jmp @next
@ok:    clc
        rts
@err:   sec
        rts

; ───────────────────────────────────────────────────────────
; addr_flat — the address argument in expr_val / expr_wide (repl.md §
; Banks, F5c): rp_addr := its low word; flat (rp_flat = SPC_FLAT,
; rp_bank its bits 16-27) when the width is FAR and it fits 28 bits;
; -$FFFF..-1 the CPU address of its low word; else C=1, last_err :=
; range.  Clobbers A.
; ───────────────────────────────────────────────────────────
addr_flat:
        lda expr_val
        sta rp_addr
        lda expr_val+1
        sta rp_addr+1
        lda #0
        sta rp_flat
        lda expr_val+2
        sta rp_bank
        lda expr_val+3
        sta rp_bank+1
        and rp_bank
        cmp #$FF
        bne @pos
        lda rp_addr             ; -$FFFF..-1: a CPU address
        ora rp_addr+1
        beq @range
        lda #0
        sta rp_bank
        sta rp_bank+1
        clc
        rts
@pos:   lda expr_wide
        and #2
        beq @ok                 ; ZP / ABS: a CPU address
        lda rp_bank+1
        cmp #$10
        bcs @range              ; above 28 bits
        lda #SPC_FLAT
        sta rp_flat
@ok:    clc
        rts
@range: lda #ERR_RANGE
        sta last_err
        sec
        rts

; ───────────────────────────────────────────────────────────
; dot_bank — expr_bank := the current address's bank when it is flat,
; else 0: `.` takes its own bank's values as low words (the same-bank
; rule, assembler_syntax.md § Directives).  Clobbers A, X.
; ───────────────────────────────────────────────────────────
dot_bank:
        jsr cur_bank_ax
        sta expr_bank
        stx expr_bank+1
        rts

; a_bank — asm_def_bank := the current address's bank (0: a CPU
; address): `a`'s default origin is the current address, flat too.
a_bank:
        jsr cur_bank_ax
        sta asm_def_bank
        stx asm_def_bank+1
        rts

; cur_bank_ax — A/X := the current address's bank when it is flat, else 0.
cur_bank_ax:
        lda #0
        tax
        bit cur_flat
        bpl :+
        lda cur_bank
        ldx cur_bank+1
:       rts

; ───────────────────────────────────────────────────────────
; calc_32 — `?`'s row for a value outside 16 bits (repl.md § Banks):
; `$` and eight hex digits, two spaces, the unsigned decimal; then
; the log line closed.  Destroys expr_val.  Clobbers A, X, Y.
; ───────────────────────────────────────────────────────────
calc_32:
        lda #'$'
        jsr io_putc
        lda expr_val+2
        ldx expr_val+3
        jsr io_puthex4
        lda expr_val
        ldx expr_val+1
        jsr io_puthex4
        puts str_2sp
        lda #0
        sta rp_tmp2             ; the digits pushed
@div:   lda #0                  ; expr_val /= 10, rp_tmp = the remainder
        sta rp_tmp
        ldx #32
@bit:   asl expr_val
        rol expr_val+1
        rol expr_val+2
        rol expr_val+3
        rol rp_tmp
        lda rp_tmp
        cmp #10
        bcc :+
        sbc #10
        sta rp_tmp
        inc expr_val            ; a quotient bit
:       dex
        bne @bit
        lda rp_tmp
        pha                     ; a digit, the lowest first
        inc rp_tmp2
        lda expr_val
        ora expr_val+1
        ora expr_val+2
        ora expr_val+3
        bne @div
@put:   pla
        ora #'0'
        jsr io_putc
        dec rp_tmp2
        bne @put
        jmp log_close

.segment "KDATA"
str_ml:         .byte " ml:", 0
str_mh:         .byte " mh:", 0
str_mb:         .byte " mb:", 0
str_d030:       .byte " "
str_d030_tail:  .byte "d030:", 0
str_map:        .byte "map  ", 0
str_k_mapped:   .byte " mapped", 0
str_k_rom:      .byte " rom", 0
str_k_io:       .byte " io", 0
map_kind_lo:    .byte 0, <str_k_mapped, <str_k_rom, <str_k_io  ; lens_kind
map_kind_hi:    .byte 0, >str_k_mapped, >str_k_rom, >str_k_io
.segment "CODE"
.endif

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
; Prints ";!<stem>? y/n" at LOG_WARN, then waits for y/n.  The
; "? y/n" trailer is shared (str_qynq) so each action string is
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
@lp:    FAR_LDA rp_ptr
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
        FAR_LDA rp_ptr
        rts

; ───────────────────────────────────────────────────────────
; load_curaddr — copy cur_addr to rp_addr
; ───────────────────────────────────────────────────────────
load_curaddr:
.ifdef PLATFORM_M65
        lda cur_flat
        sta rp_flat
        lda cur_bank
        sta rp_bank
        lda cur_bank+1
        sta rp_bank+1
.endif
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
        FAR_LDA rp_ptr
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
        FAR_LDA rp_ptr
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
        FAR_LDA rp_ptr
        jmp _hex_val

; ───────────────────────────────────────────────────────────
; parse_hex2_ptr1 — parse 2 hex digits at rp_ptr, advance rp_ptr
;   Returns byte in A.
; ───────────────────────────────────────────────────────────
parse_hex2_ptr1:
        ldy #0
        FAR_LDA rp_ptr
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta rp_tmp
        ldy #1
        FAR_LDA rp_ptr
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
        FAR_LDA rp_ptr
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta rp_tmp2                ; hi nibble of high byte
        ldy #1
        FAR_LDA rp_ptr
        jsr _hex_val
        ora rp_tmp2
        sta rp_tmp2                ; high byte complete
        ldy #2
        FAR_LDA rp_ptr
        jsr _hex_val
        asl
        asl
        asl
        asl
        sta rp_tmp
        ldy #3
        FAR_LDA rp_ptr
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
; (? @ B C j t o + - b d m).  See
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
@lp:    FAR_LDA rp_ptr
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
        ; fall through to _syntax_err

; ═══════════════════════════════════════════════════════════
; _syntax_err — shared `;?syntax` tail.  Works as both a tail-jmp
; (jmp _syntax_err — log_err's rts pops the caller's caller's
; frame, same as direct `jmp log_err`) and a jsr target (returns
; to the call site after the saved return is popped).  Pairs
; naturally with _require_eoi_or_err's pop-trick, which falls
; through here.
; ═══════════════════════════════════════════════════════════
_syntax_err:
        lda #<str_syntax
        ldx #>str_syntax
        jmp log_err

; ═══════════════════════════════════════════════════════════
; try_expr_or_err — try_expr + on-success EOI garbage check
;
; The common pattern for "take exactly one expression, nothing
; else" commands: parse, then require clean EOI.  This wrapper
; folds both calls into one, saving 5 B per migrated call site
; (no inline `ldy #0 / jsr _require_eoi_or_err` after a success).
;
; Returns: same as try_expr (C=1 success, C=0 empty or error) on
;          the non-garbage paths.  On success-with-garbage, tail-
;          calls _require_eoi_or_err which pops the CALLER'S OF
;          try_expr_or_err return address via the pop-trick — so
;          control escapes two levels up (matching optimization.md
;          § 36 contract, because the helper's `jmp` preserves the
;          same stack depth as a direct `jsr _require_eoi_or_err`
;          from the outer caller).
;
; Stack contract: inherits _require_eoi_or_err's — the caller of
; try_expr_or_err must be exactly one jsr deep from the desired
; escape point (top-of-handler-chain).
; ═══════════════════════════════════════════════════════════
.ifdef PLATFORM_M65
; try_addr_or_err — try_expr_or_err for an address argument (repl.md §
; Banks): the expression in 32 bits; on success rp_addr is its low
; word and rp_flat / rp_bank its space (addr_flat).  A jmp, so the
; pop-trick's depth holds.
try_addr_or_err:
        lda #$80
        sta ta_flat
        ; fall through
.endif
.proc try_expr_or_err
        jsr try_expr
        bcc @r                  ; empty/error — return as-is
        ldy #0
        jmp _require_eoi_or_err ; tail-call (preserves stack contract)
@r:     rts
.endproc

; ═══════════════════════════════════════════════════════════
; try_expr — evaluate expression at rp_ptr
;   C=1: success (result in expr_val, rp_ptr advanced)
;   C=0, Z=1: empty (NUL or ';')
;   C=0, Z=0: expression error (`;?expr …` already printed)
; ═══════════════════════════════════════════════════════════
.proc try_expr
.ifdef PLATFORM_M65
        lda ta_flat             ; this call's mode; the flag is one-shot
        sta ta_mode
        lda #0
        sta ta_flat
.endif
        jsr skip_peek_ptr1
        beq @empty
        cmp #';'
        beq @empty
        ; set expr_ptr = rp_ptr
        lda rp_ptr
        sta expr_ptr
        lda rp_ptr+1
        sta expr_ptr+1
.ifdef PLATFORM_M65
        bit ta_mode
        bmi :+
        jsr expr_eval
        jmp @ev
:       jsr expr_eval32         ; an address: 32 bits, addr_flat judges
@ev:
.else
        jsr expr_eval
.endif
        ; reload rp_ptr
        pha
        lda expr_ptr
        sta rp_ptr
        lda expr_ptr+1
        sta rp_ptr+1
        pla
        cmp #2
        bcs @error
.ifdef PLATFORM_M65
        bit ta_mode
        bpl :+
        jsr addr_flat           ; rp_addr, rp_flat, rp_bank; C=1 range
        bcs @error
:
.endif
        sec
        rts
@error:
        ldy #LOG_ERR
        jsr log_open        ; ";?"
        puts str_expr
        jsr expr_error_str
        jsr io_puts             ; "undef main" etc.
        jsr log_close
        lda #1                  ; Z=0: error, not empty
        clc
        rts
@empty: lda #0                  ; Z=1: empty
        clc
        rts
.endproc

; ───────────────────────────────────────────────────────────
; bp_range_check / bp_range_check_step — address-write gates.
;
; bp_range_check: addr must be in [workstart, workend].
;   workstart = WORKSTART (fixed); the upper bound is the workspace's
;   (platform_layer.md § Constants): c64 buf_base (dynamic, workend =
;   buf_base - 1).  Equivalently:  WORKSTART <= addr < the bound.
;   m65: the address must be at least WORKSTART, then bp_cpu_ok takes
;   it through the program's bank state to its physical byte, which
;   must be user memory (0.2000-0.BFFF, 1.2000-1.F6FF, banks 4-5);
;   it also clobbers X and lens_ptr.
;   Used by cmd_brk (managed bp creation) — strict gate, errors
;   on out-of-range.
;
; bp_range_check_step: same as bp_range_check but additionally
;   treats brk_stub as in-range.  Used by cmd_step's step BRK
;   arming gate: stepping across the user's top-level RTS lands
;   at brk_stub (step_next_pc's @rts peeks the user stack and
;   returns (brk_stub-1)+1 = brk_stub).  brk_stub lives in CSE's
;   CODE segment, above the user workspace
;   — so the strict gate would refuse, leaving the user unable
;   to step past the top-level rts.  Step BRK arming at brk_stub
;   is a harmless no-op patch ($00 over $00); the handler's
;   brk_stub check supersedes the step_bp match anyway and
;   classifies as DBG_RTS clean exit.  cmd_brk stays strict
;   (no exemption — `b $brk_stub` is pointless).
;
; bp_range_check_step is laid out IMMEDIATELY before bp_range_check
; so its mismatch path falls through (no jmp).  Saves 3 B.
;
; Without the gate, step BRK arming or user bp creation could
; write the patched $00 byte to ROM-shadowed RAM ($A000-$BFFF
; under BASIC, $E000+ under KERNAL), to IO ($D000-$DFFF — VIC,
; SID, CIA, color RAM), or to KDATA at $F100+.  Patches are
; transient (unpatch_all restores), but the brief window of
; corruption can change colors, raster behaviour, or our own
; KDATA tables.
;
; In:  A = addr lo, X = addr hi.
; Out: C=0 in range, C=1 out of range.
; Clobbers: A.
; ───────────────────────────────────────────────────────────
.proc bp_range_check_step
        cpx #>brk_stub
        bne bp_range_check      ; mismatch → fall to strict gate
        cmp #<brk_stub
        bne bp_range_check
        clc                     ; brk_stub — accept
        rts
.endproc

.proc bp_range_check
        ; Lower bound: addr >= WORKSTART (page-aligned).
        cpx #>WORKSTART
        bcc @oor
.ifdef PLATFORM_M65
        ; m65: the byte the address reaches through the program's bank
        ; state must be user memory (debugger.md § b; slice 3, F4).
        jmp bp_cpu_ok
.else
        ; Upper bound: addr < buf_base.
        cpx buf_base+1
        bcc @ok                 ; hi < buf_base.hi → in range
        bne @oor                ; hi > buf_base.hi → out
        cmp buf_base            ; hi == buf_base.hi → check lo
        bcc @ok
.endif
@oor:   sec
        rts
.ifndef PLATFORM_M65
@ok:    clc
        rts
.endif
.endproc
        .assert <WORKSTART = 0 && <HIMEM = 0, error, "the workspace gates compare high bytes"


; ───────────────────────────────────────────────────────────
; step_targets_check — the step-arming gate: every non-zero
; step_next slot (as set by step_next_pc) must pass
; bp_range_check_step.  Shared by cmd_step (first step) and
; main.s's handler step chain (every further step of t/o N).
; Out: C=0 all slots armable, C=1 a slot is out of range.
; Clobbers: A, X.
; ───────────────────────────────────────────────────────────
.proc step_targets_check
        lda step_next_lo
        ora step_next_lo+1
        beq @hi
        lda step_next_lo
        ldx step_next_lo+1
        jsr bp_range_check_step
        bcs @r
@hi:    lda step_next_hi
        ora step_next_hi+1
        beq @ok
        lda step_next_hi
        ldx step_next_hi+1
        jmp bp_range_check_step ; tail-call: its C is ours
@ok:    clc
@r:     rts
.endproc

; ───────────────────────────────────────────────────────────
; brk_skip_user — advance brk_pc past a user BRK opcode.
;
; "Lazy debug" workflow: user puts a `brk` (+ signature byte
; via `.db $XX`) somewhere in their code as a quick stop point.
; When the BRK fires, the handler captures brk_pc pointing AT
; the $00 opcode itself (handler already adjusted PC -= 2 from
; the CPU-stacked PC+2).  Resuming from there would re-trap
; immediately — we'd never make progress.
;
; This helper checks the opcode at brk_pc; if it's $00 (user
; BRK), advances brk_pc by 2 (past BRK + signature byte —
; matches the CPU's own RTI semantics).  Used by:
;   * cmd_step on STEP_OVER (`o`) — skip BRK, then step the
;     instruction after.  cmd_step on STEP_INTO (`t`) does NOT
;     call this — `t` deliberately hangs at user BRK so the
;     return-step workflow stops there for inspection.
;   * cmd_continue (`c`) — skip BRK, then resume.
;
; Note: we never execute the BRK opcode itself — the IRQ is
; bypassed entirely.  The handler's IRQ vector is not invoked.
;
; Clobbers: A, Y, rp_ptr; on m65 also X (FAR_USER).
; ───────────────────────────────────────────────────────────
.proc brk_skip_user
        lda brk_pc
        sta rp_ptr
        lda brk_pc+1
        sta rp_ptr+1
        FAR_USER rp_ptr
        ldy #0
        FAR_LDA rp_ptr
        bne @done               ; not $00 — not a user BRK
        lda brk_pc
        clc
        adc #2
        sta brk_pc
        bcc @done
        inc brk_pc+1
@done:  rts
.endproc

; ───────────────────────────────────────────────────────────
; expr_or_blocksize — expr_val := expression or block_size if empty/zero
;   Returns with expr_val populated.  On an expression error (already
;   printed) it does not return: it drops its caller's frame (the
;   `+`/`-` handler, one jsr deep from exec_line — the pop-trick of
;   _require_eoi_or_err) so the command does nothing.
; ───────────────────────────────────────────────────────────
.proc expr_or_blocksize
        jsr try_expr
        bcc @none
        lda expr_val
        ora expr_val+1
        bne @r
@blk:   lda block_size
        sta expr_val
        lda block_size+1
        sta expr_val+1
@r:     rts
@none:  beq @blk                ; empty → block_size
        pla                     ; error: abandon the + / - handler
        pla
        rts
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
.ifdef PLATFORM_M65
        lda sym_val+2           ; a flat value: a flat current address
        sta cur_bank            ; (`a` / `g` in main's bank, F5b)
        lda sym_val+3
        sta cur_bank+1
        ora cur_bank
        beq @cpu
        lda #SPC_FLAT
        sta cur_flat            ; C=0 from sym_lookup
        rts
@cpu:
.endif
        SPACE_CPU
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
;   IO_CY   = screen row to read
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
        ldx IO_CY
        lda scr_lo,x
        sta rp_ptr
        lda scr_hi,x
        sta rp_ptr+1
        FAR_BANK_SCREEN rp_ptr

        ldy #0
@loop:  FAR_LDA rp_ptr
        and #$7F                ; strip reverse-video bit
        jsr scr_to_pet          ; screen code → PETSCII
        sta line_buf,y
        iny
        cpy WIDTH
        bcc @loop

        ; trim trailing spaces, then NUL-terminate
        ldy WIDTH
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
        sta IO_CX
.ifdef PLATFORM_M65
        ldx #SPC_CUR
        jsr put_bank
.endif
        lda cur_addr
        ldx cur_addr+1
        jsr io_puthex4
        lda #':'
        jmp io_putc
.endproc

; ═══════════════════════════════════════════════════════════
; zp_stage_prep — user-ZP read redirect for m/. displays.
;
; Stages MEM_ROW_MAX bytes from (rp_ptr2) into zp_stage_buf, substituting
; userland_zp_buf[addr - ZP_SAVE_LO] for any offset whose
; effective address (rp_ptr2 + Y, 16-bit, wrapping past $FFFF to
; $00xx as (rp_ptr2),y does) falls in [ZP_SAVE_LO,
; ZP_SAVE_LO + ZP_SAVE_LEN).  Bytes outside that range fall
; through to live (rp_ptr2),y reads.  On completion, rp_ptr2 is
; repointed at zp_stage_buf so downstream consumers ((rp_ptr2),y
; loads by emit_hex_cols, DOT_DASM, the compare loop in cmd_dot)
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
;      source was in page $00 or $FF.  Callers that branch on
;      page-0-ness must inspect rp_ptr2+1 themselves.
; Clobbers: A, X, Y.
zp_stage_prep_addr:                     ; convenience entry: load
.ifdef PLATFORM_M65
.ifndef INTROSPECT
        bit rp_flat                     ; a CPU-space row: every byte
        bmi :+                          ;   through the CPU's lens
        jmp lens_stage
:
.endif
.endif
        lda rp_addr                     ; rp_ptr2 from rp_addr then
        sta rp_ptr2                     ; fall through into the
        lda rp_addr+1                   ; main zp_stage_prep body.
        sta rp_ptr2+1
        FAR_CUR rp_ptr2                 ; rp_addr: the command's space
        ; fall through
.proc zp_stage_prep
.ifdef INTROSPECT
        ; Introspection build: no redirect.  rp_ptr2 already points
        ; at the live address; downstream consumers read live ZP.
        rts
.else                                   ; m65: the save range is the port
.ifdef PLATFORM_M65
        bit rp_flat                     ; a flat address: no user-ZP
        bmi @done                       ;   view, the bytes themselves
.endif
        ldx rp_ptr2+1                   ; only a page-$00 or page-$FF
        inx                             ; base can reach the save range
        cpx #2                          ; (a row's run from $FFF9+
        bcs @done                       ; wraps to $00xx)
        ldy #0
@lp:    tya
        clc
        adc rp_ptr2
        tax                             ; effective lo
        lda rp_ptr2+1
        adc #0                          ; effective hi ($00 also after
        bne @live                       ; a wrap past $FFFF)
        cpx #<(ZP_SAVE_LO + ZP_SAVE_LEN)
        bcs @live                       ; addr ≥ save end → live
        lda userland_zp_buf - ZP_SAVE_LO,x
        bcc @stg                        ; C=0 here (bcs-not-taken)
@live:  FAR_LDA rp_ptr2
@stg:   sta zp_stage_buf,y
        iny
        cpy #MEM_ROW_MAX
        bcc @lp
        lda #<zp_stage_buf
        sta rp_ptr2
        lda #>zp_stage_buf
        sta rp_ptr2+1
        FAR_BANK rp_ptr2, BANK_CSE
@done:  rts
.endif
.endproc

; ═══════════════════════════════════════════════════════════
; zp_poke — user-ZP write redirect for m/. edits.
;
; Writes A to the effective address (rp_ptr2 + Y, 16-bit, wrapping
; past $FFFF to $00xx as (rp_ptr2),y does), substituting
; userland_zp_buf[addr - ZP_SAVE_LO] when the effective address
; is in [ZP_SAVE_LO, ZP_SAVE_LO + ZP_SAVE_LEN).  Otherwise stores
; through (rp_ptr2),y as normal.  An edit run from $FFFC on thus
; never reaches the live CPU port or CSE's own ZP.  Unconditional — user-ZP edits
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
        FAR_STA rp_ptr2
        rts
.else                                   ; m65: the save range is the port
.ifdef PLATFORM_M65
        bit rp_flat                     ; a flat address: the byte itself
        bmi @live
        jmp lens_poke                   ; CPU space: the CPU's lens
.endif
        pha
        tya
        clc
        adc rp_ptr2
        tax                             ; effective lo
        lda rp_ptr2+1
        adc #0                          ; effective hi ($00 also after
        bne @pop                        ; a wrap past $FFFF)
        cpx #<(ZP_SAVE_LO + ZP_SAVE_LEN)
        bcs @pop                        ; addr ≥ save end → live
        pla
        sta userland_zp_buf - ZP_SAVE_LO,x
        rts
@pop:   pla
@live:  FAR_STA rp_ptr2
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
        FAR_LDA rp_ptr2
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

; DOT_DASM — disassemble the instruction at rp_addr as the user sees it:
;   rp_ptr2 → the staged image (zp_stage_buf for a page-0 base, else
;   the user address), dasm_buf filled, A = the length.  Inline in
;   emit_dot on the C64; on m65 the proc dot_dasm, which cmd_dot's
;   width check shares.
.macro DOT_DASM
        jsr zp_stage_prep_addr
        ; dasm_insn_pre owns its KERNAL banking — we hand it the
        ; (possibly staged) bytes and the real PC for branch targets.
        ldy #INSN_MAX - 1
:       FAR_LDA rp_ptr2
        sta _dasm_in,y
        dey
        bpl :-
        lda rp_addr
        sta _dasm_ptr
        lda rp_addr+1
        sta _dasm_ptr+1
        jsr dasm_insn_pre
.endmacro

.ifdef MEGA_SUPPORT
.proc dot_dasm
        DOT_DASM
        rts
.endproc
.endif

; ═══════════════════════════════════════════════════════════
; emit_dot — disassemble and display "ADDR:. XX XX XX  mne op"
;   (INSN_MAX byte columns: 3, m65 5).  rp_addr = address.  Returns
;   the instruction length in A.
; ═══════════════════════════════════════════════════════════
.proc emit_dot
.ifdef MEGA_SUPPORT
        jsr dot_dasm
.else
        DOT_DASM
.endif
        pha                     ; save olen for later use

        lda #'.'
        jsr io_addr_cmd
        lda #' '
        jsr io_putc

        ; emit_hex_cols(rp_ptr2 already set, olen, INSN_MAX)
        pla                     ; olen
        pha
        sta rp_save             ; count
        lda #INSN_MAX
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
;   rp_addr = address, A = cols (0 → a full row; capped at the row:
;   8, m65 mem_row's 8 or 16)
; ═══════════════════════════════════════════════════════════
.proc emit_mem
.ifdef PLATFORM_C64
        cmp #0
        bne @n0
        lda #8
@n0:    cmp #9
        bcc @ok
        lda #8
@ok:    sta rp_opc              ; cols (borrowing rp_opc)
.else
        sta rp_opc              ; cols (borrowing rp_opc)
        jsr mem_row             ; A = the row's bytes in this width
        ldx rp_opc
        beq @row                ; 0 → a full row
        cmp rp_opc
        bcs @ok                 ; cols ≤ the row
@row:   sta rp_opc
@ok:
.endif

        lda #'m'
        jsr io_addr_cmd

        jsr zp_stage_prep_addr  ; user-ZP redirect (see repl.md)

        lda rp_opc
        sta rp_save
.ifdef PLATFORM_C64
        lda #8
.else
        jsr mem_row
.endif
        sta rp_save2
        jsr emit_hex_cols
.ifdef PLATFORM_M65
        bit rp_flat             ; a flat row in 40 columns: no ASCII
        bpl :+                  ; column — the prefix took its room
        lda scr_width           ; (repl.md § Banks)
        cmp #80
        bcs :+
        jmp io_clear_eol
:
.endif

        ; Separator between hex bytes and ASCII column.  Use `;`
        ; so that re-executing the line (cursor-up + RETURN on a
        ; dump row) treats the trailing ASCII as a comment — the
        ; `m` edit path's _require_eoi_or_err recognises `;` as
        ; valid EOI.  Without this, `m XX XX ... XX XX ASCII`
        ; would syntax-err on the ASCII column.  Same width as
        ; the previous space — the row still fits its width.
        lda #';'
        jsr io_putc

        ldy #0
@asc:   cpy rp_opc
        bcs @adone
        FAR_LDA rp_ptr2
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

.ifdef PLATFORM_M65
; ── mem_row — A = an `m` row's bytes: 16 in 80 columns, 8 in 40 ──
; (repl.md, By width).  Clobbers A.
mem_row:
        lda scr_width
        and #$E0                ; 80 → $40, 40 → $20
        lsr
        lsr
        rts
.endif

; ═══════════════════════════════════════════════════════════
; emit_reg — print register dump
; ═══════════════════════════════════════════════════════════
.proc emit_reg
        lda #0
        sta IO_CX
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
.ifdef PLATFORM_M65
        bit scr_width           ; V = bit 6: 80 ($50) set, 40 ($28) clear
        bvc :+                  ; 40 columns: z and b on a row of their own
        jsr @zb
:
.endif
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
.ifdef PLATFORM_M65
        bit scr_width
        bvs @eol
        jsr io_clear_eol        ; 40 columns: "r z:xx b:xx ml:… mh:…" below
        jsr newline
        lda #'r'
        jsr io_putc
        jsr @zb
@eol:   jsr put_map_regs        ; " ml:XXXX mh:XXXX" (repl.md § Banks)
.endif
        jmp io_clear_eol
.ifdef PLATFORM_M65
@zb:    puts str_z              ; " z:xx b:xx"
        lda reg_z
        jsr io_puthex2
        puts str_b
        lda reg_b
        jmp io_puthex2
.endif
.endproc

; ═══════════════════════════════════════════════════════════
; show_break_result — status msg header + regs + disasm
;
; Unified return-to-REPL path after running user code.  Emits the
; break panel: tag info line, regs row, and (for non-RTS variants)
; a lookahead disassembly.  See doc/modules/debugger.md § Break
; panel for the panel anatomy.
;
; Tag classification — one-tier from dbg_reason (NO opcode peek):
;
;   DBG_NMI → "; nmi at $PC"
;   DBG_RTS → "; rts"               (no address — handler retconned
;                                    brk_pc := cur_addr for clean
;                                    exit, so the displayed value
;                                    would be the j-target, not the
;                                    rts location.  See debugger.md
;                                    § Break panel.)
;   DBG_BRK → "; brk at $PC"        (default — step trap, user BP,
;                                    or unplanned user BRK).  If
;                                    dbg_bp_hit != $FF, appends the
;                                    slot number: "; brk N at $PC".
;   DBG_NONE → "; brk at $PC"       (defensive; not normally reached
;                                    via this path — DBG_NONE means
;                                    no session, panel shouldn't fire).
;
; DBG_RTS variant additionally suppresses the lookahead disas (the
; program ended; nothing to step to) and ends with nl_clear (newline
; + clreol) so show_prompt lands on a fresh row.
;
; Colours/VIC state are already restored by hygiene_after_userland
; in handler_finalize (called before main_loop_top → post_run_cleanup
; → here), so no restore_colors at entry.
; ═══════════════════════════════════════════════════════════

; ═══════════════════════════════════════════════════════════
; show_cold_preview — first t/o with no resumable session.
;
; Emits "; dbg at $PC" + regs + disas at brk_pc.  No user code
; runs.  Caller (cmd_step) sets dbg_reason := DBG_BRK and
; cold_preview_done := 1 so the next real step pushes a fresh
; sentinel via MODE_JUMP.
;
; The "dbg" tag is intentionally distinct from "; brk"/"; rts"
; — the user wants to know this is a *preview*, not the result
; of an instruction having executed.
; ═══════════════════════════════════════════════════════════
.proc show_cold_preview
        ldy #' '
        jsr log_open            ; "; "
        lda #<str_dbg
        ldx #>str_dbg
        jsr io_puts             ; "dbg"
        puts str_at             ; " at $"
        lda brk_pc
        ldx brk_pc+1
        jsr io_puthex4
        jsr io_clear_eol
        jsr newline
        jsr emit_reg
        jsr newline
        ; Disas at brk_pc (also updates cur_addr).
        lda brk_pc
        sta cur_addr
        sta rp_addr
        lda brk_pc+1
        sta cur_addr+1
        sta rp_addr+1
        SPACE_CPU
        jsr emit_dot
        jmp nl_clear
.endproc

.proc show_break_result
        ; log_open auto-advances if cursor is mid-line (userland
        ; return may leave it anywhere); no manual newline needed.

        ; Tag classification by dbg_reason ONLY:
        ;   DBG_NMI → "; nmi"
        ;   DBG_RTS → "; rts"  (handler-classified clean exit via
        ;                       brk_stub — user's top-level RTS popped
        ;                       the sentinel; brk_pc already reset to
        ;                       cur_addr by the handler)
        ;   DBG_BRK / DBG_NONE → "; brk"  (any other trap, including
        ;                                  step landing AT an rts/rti
        ;                                  opcode — we trapped there,
        ;                                  haven't executed the rts
        ;                                  yet, so "brk" is correct)
        ;
        ; Step-INTO can follow rts/rti naturally now (step_next_pc
        ; @rts/@rti peek user stack), so the user reaches the post-
        ; rts location on their next t — "; rts" is reserved for
        ; the clean-exit case where the program actually returned.
        lda dbg_reason
        cmp #DBG_NMI
        bne @not_nmi
        lda #<str_nmi
        ldx #>str_nmi
        jmp @have_tag
@not_nmi:
        cmp #DBG_RTS
        beq @is_rts
        ; DBG_BRK or DBG_NONE → "; brk"
        lda #<str_brk
        ldx #>str_brk
        jmp @have_tag
@is_rts:
        lda #<str_rts
        ldx #>str_rts

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
        cmp #DBG_BRK
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

        ; " at $PC" — but NOT for DBG_RTS.  After clean exit the
        ; handler reset brk_pc := cur_addr (j-target), so the address
        ; would be the j-target, NOT the actual rts location — bogus.
        ; A pure "; rts" is the clearest signal that the program
        ; returned; the user's regs row below shows the final state.
        lda dbg_reason
        cmp #DBG_RTS
        beq @no_at
        puts str_at
        lda brk_pc
        ldx brk_pc+1
        jsr io_puthex4
@no_at:
        jsr io_clear_eol

        ; Regs.  Update cur_addr := brk_pc regardless of variant.
        jsr newline
        jsr emit_reg
        lda brk_pc
        sta cur_addr
        lda brk_pc+1
        sta cur_addr+1
        SPACE_CPU

        ; DBG_RTS: skip the lookahead disas — the program's done
        ; (clean exit via brk_stub).  Newline + clreol so show_prompt
        ; lands on a fresh row instead of overwriting the regs row
        ; (show_prompt only resets IO_CX, doesn't advance IO_CY).
        lda dbg_reason
        cmp #DBG_RTS
        bne @disas
        jmp nl_clear

@disas:
        ; Lookahead disas at brk_pc.
        jsr newline
        lda cur_addr
        sta rp_addr
        lda cur_addr+1
        sta rp_addr+1
        jsr emit_dot
        jmp nl_clear
.endproc

; ═══════════════════════════════════════════════════════════
; dot_assemble — assemble the instruction at rp_ptr (its mnemonic) to
; rp_addr.  asm_line reads it where it stands in line_buf, to the end,
; a `;` or `//`, and evaluates the operand itself — as the source
; assembler's lines are read — so `*` is this address, `asl a` the
; accumulator form (an `a` label warned of), an expression error its
; own tag (repl.md § Error tag dispatch).  asm_pass = 1: one pass, an
; undefined symbol an error (pass 0 would size it with a stand-in).
;   Returns nbytes in A (0: refused, asm_err_code set).
; ═══════════════════════════════════════════════════════════
.proc dot_assemble
        lda #1
        sta asm_pass
        lda rp_addr
        sta asm_pc
        sta asm_out
        lda rp_addr+1
        sta asm_pc+1
        sta asm_out+1
        FAR_CUR_W asm_out       ; `.` writes straight into user memory
.ifdef PLATFORM_C64
        ; At $00-$7F the bytes go to the user's image, as `m`'s do
        ; (userland_contract.md § 3): asm_line assembles into rp_hexbuf,
        ; then zp_poke writes each byte (the image below $80, live from
        ; $80).  No wrap past $FFFF can start there.
        lda rp_addr+1
        bne @direct
        lda rp_addr
        cmp #ZP_SAVE_LO + ZP_SAVE_LEN
        bcs @direct
        lda #<rp_hexbuf
        sta asm_out
        lda #>rp_hexbuf
        sta asm_out+1
        lda rp_ptr
        ldx rp_ptr+1
        jsr asm_line            ; A = the length (0: refused)
        sta rp_tmp2
        tax                     ; (asm_line's Z is its ldx #0's)
        beq @r
        lda rp_addr
        sta rp_ptr2
        lda #0
        sta rp_ptr2+1
        tay
@cp:    lda rp_hexbuf,y
        jsr zp_poke             ; (keeps Y)
        iny
        cpy rp_tmp2
        bne @cp
        lda rp_tmp2
@r:     rts
@direct:
.endif
        lda rp_ptr
        ldx rp_ptr+1
        jmp asm_line            ; tail call
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_dot — '.' command: hex edit / assemble / disassemble
;   rp_ptr = args
; ═══════════════════════════════════════════════════════════
.proc cmd_dot
        jsr load_curaddr

        jsr skip_sp_ptr1

        ; Parse up to INSN_MAX hex byte pairs (the longest instruction)
        lda #0
        sta rp_cnt              ; nbytes

@hex_lp:
        lda rp_cnt
        cmp #INSN_MAX
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
        ; reflects what the user sees (the userland_zp_buf image for
        ; $00-$7F, memory elsewhere).
        jsr zp_stage_prep_addr

        ; Check if bytes changed vs the staged image
        ldy #0
        sty rp_save             ; changed flag
@cmp:   cpy rp_cnt
        bcs @cmp_done
        FAR_LDA rp_ptr2
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

        ; Write changed bytes (user-ZP aware).  zp_stage_prep above
        ; may have repointed rp_ptr2 at zp_stage_buf; reset to
        ; rp_addr so zp_poke's redirect check sees the real address.
        lda rp_addr
        sta rp_ptr2
        lda rp_addr+1
        sta rp_ptr2+1
        FAR_CUR rp_ptr2
.ifdef PLATFORM_M65
        lda rp_cnt              ; the whole run: not into the ROM banks
        jsr run_write_ok        ; (repl.md § Banks)
        bcc :+
        jmp dot_range
:
.endif
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
.ifdef PLATFORM_M65
        bcc :+
        RP_CARRY                ; a flat address carries into its bank
:       CUR_FROM_RP
.endif
        jsr newline
        lda rp_cnt
        jeq io_clear_eol        ; nbytes == 0 → clear; else skip
        rts

@try_mne:
        ; Input-shape gate (repl.md § `.` command input-shape matrix):
        ;   empty / comment → silent redisplay (@show, valid)
        ;   a-z letter      → dot_assemble path
        ;   anything else   → syntax error (`. .`, `. ,`, `. $`)
        jsr skip_peek_ptr1
        beq @show               ; NUL after skip — bare `.`, redisplay
        cmp #';'
        beq @show               ; comment — redisplay
        cmp #'a'
        bcc @syn_err            ; non-letter garbage → syntax error
        cmp #'z'+1
        bcs @syn_err            ; above 'z' → syntax error
.ifdef MEGA_SUPPORT
        ; Re-entered over matching bytes (mode 2): keep the width — a
        ; 16-bit branch lists like an 8-bit one, so ask asm_line for
        ; REL16 when the bytes are one (repl.md § The `.` command).
        lda rp_cnt
        beq :+
        jsr dot_dasm
        lda _dasm_mode
        cmp #MODE_REL16
        bne :+
        lda #$80
        sta asm_rel16
:
.endif
.ifdef PLATFORM_M65
        jsr cur_write_ok        ; not into the ROM banks (repl.md § Banks)
        bcc :+
        jmp dot_range
:
.endif
.ifdef PLATFORM_M65
        jsr dot_bank            ; the same-bank rule at a flat address:
        jsr dot_assemble        ; its operand evaluations and asm_line's
        ldy #0
        sty expr_bank           ; the bank does not outlive `.`
        sty expr_bank+1
.else
        jsr dot_assemble
.endif
        cmp #0
        bne @show               ; success → show result
.ifdef MEGA_SUPPORT
        sta asm_rel16           ; A = 0: a refusal before asm_line ran
                                ; leaves the width request — drop it
.endif
        ; Dispatch error category (asm_err.s § asm_err_code):
        ;   0 = syntax  → ;?syntax
        ;   1 = expr    → ;?expr <detail>
        ;   2 = cpu     → ;?cpu
        lda asm_err_code
        beq @syn_err
        cmp #2
        beq @cpu_err
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
        jmp _syntax_err
@cpu_err:
        lda #<str_cpu_err
        ldx #>str_cpu_err
        jmp log_err
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_disasm — 'd' command
;   rp_ptr = args (ignored)
; ═══════════════════════════════════════════════════════════
.proc cmd_disasm
        ; cmd_disasm takes no inline args; reject garbage at entry
        ; (pop-trick).  Addressed form `1000:d` sets cur_addr via
        ; exec_line before this proc runs — rp_ptr on entry points
        ; at what follows the `d` key.
        jsr skip_sp_ptr1
        ldy #0
        jsr _require_eoi_or_err

        jsr load_curaddr

        ; block_size bytes from addr: count them down (an instruction
        ; may end past the count); stop after one that wraps past $FFFF
        lda block_size
        sta rp_cnt
        lda block_size+1
        sta rp_cnt+1
@loop:  lda rp_cnt
        ora rp_cnt+1
        beq @done
        jsr emit_dot            ; returns olen in A
        sta rp_tmp2
        clc                     ; addr += olen
        adc rp_addr
        sta rp_addr
        lda rp_addr+1
        adc #0
        sta rp_addr+1
        php                     ; C: wrapped past $FFFF
        jsr newline
        lda rp_cnt              ; count -= olen, at least 0
        sec
        sbc rp_tmp2
        sta rp_cnt
        lda rp_cnt+1
        sbc #0
        sta rp_cnt+1
        bcs :+
        lda #0
        sta rp_cnt
        sta rp_cnt+1
:       plp
        bcc @loop
.ifdef PLATFORM_M65
        RP_CARRY                ; wrapped: a flat address carries into its bank
.endif

@done:
.ifdef PLATFORM_M65
        CUR_FROM_RP
.endif
        lda rp_addr
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

.ifdef PLATFORM_M65
        ; The first word (repl.md § Banks): four hex digits a CPU
        ; address, two the edit bytes, anything else an expression
        jsr is_hex4_at_ptr1
        beq @m_two
        ldy #4
        jsr is_eow_at_ptr1_y
        beq @addr_ok
@m_two: ldy #0
        jsr is_hex_at_ptr1
        beq @m_expr
        ldy #1
        jsr is_hex_at_ptr1
        beq @m_expr
        ldy #2
        jsr is_eow_at_ptr1_y
        jeq @no_addr            ; the edit bytes at the current address
@m_expr:
        lda #$80
        sta ta_flat             ; an address: rp_addr / rp_flat / rp_bank
        jsr try_expr
        bcs :+
        jeq @no_addr            ; empty: the current address
        rts                     ; an error, printed
:       jsr skip_sp_ptr1
        jmp @no_addr
.else
        ; Check for 4-digit hex address override
        jsr is_hex4_at_ptr1
        beq @no_addr
        ; check q[4] is end-of-word (space/NUL/;)
        ldy #4
        jsr is_eow_at_ptr1_y
        jne @no_addr
.endif
@addr_ok:
        jsr parse_hex4_ptr1
        sta rp_addr
        stx rp_addr+1
.ifdef PLATFORM_M65
        lda #0
        sta rp_flat             ; a CPU address
.endif
        jsr skip_sp_ptr1

@no_addr:
        ; Check for 2-digit hex edit bytes
        ldy #0
        jsr is_hex_at_ptr1
        jeq @dump
        ldy #1
        jsr is_hex_at_ptr1
.ifdef PLATFORM_M65
        jeq @dump
.else
        beq @dump
.endif
        ldy #2
        jsr is_eow_at_ptr1_y
        jne @dump

@edit:  ; Parse every edit byte into zp_stage_buf first, check the
        ; line's end, then (m65) the whole run, then write: a refused
        ; line writes nothing.
        lda #0
        sta rp_cnt              ; nbytes
@ed_lp: lda rp_cnt
        cmp #MEM_ROW_MAX
        bcs @ed_done
        ldy #0
        jsr is_hex_at_ptr1
        beq @ed_done
        ldy #1
        jsr is_hex_at_ptr1
        beq @ed_done
        jsr parse_hex2_ptr1
        ldy rp_cnt
        sta zp_stage_buf,y
        inc rp_cnt
        jsr skip_sp_ptr1
        jmp @ed_lp

@ed_done:
        ; Final-arg garbage check: reject non-EOW after the last HH
        ; (pop-trick), before any byte is written.
        ldy #0
        jsr _require_eoi_or_err
        ; rp_ptr2 := rp_addr; zp_poke writes rp_ptr2+Y
        lda rp_addr
        sta rp_ptr2
        lda rp_addr+1
        sta rp_ptr2+1
        FAR_CUR rp_ptr2
.ifdef PLATFORM_M65
        lda rp_cnt              ; the whole run: not into the ROM banks
        jsr run_write_ok        ; (repl.md § Banks)
        bcc :+
        jmp dot_range
:
.endif
        ldy #0
@ed_wr: lda zp_stage_buf,y
        jsr zp_poke             ; (keeps Y)
        iny
        cpy rp_cnt
        bne @ed_wr
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
        sta cur_addr+1          ; (a wrap past $FFFF: the sum's low word)
.ifdef PLATFORM_M65
        bcc @ed_nl
        RP_CARRY                ; a flat address carries into its bank
@ed_nl:
.endif
        CUR_FROM_RP
        jmp newline

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
        ; cols = min(remaining, the row)
.ifdef PLATFORM_C64
        lda rp_cnt+1
        bne @full
        lda rp_cnt
        cmp #8
        bcc @partial
@full:  lda #8
@partial:
.else
        jsr mem_row
        ldx rp_cnt+1
        bne @partial            ; ≥ 256 left: a full row
        cmp rp_cnt
        bcc @partial            ; more than a row left
        lda rp_cnt
@partial:
.endif
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
        RP_CARRY                ; wrapped: a flat address carries

@d_done:
        lda rp_addr
        sta cur_addr
        lda rp_addr+1
        sta cur_addr+1
        CUR_FROM_RP
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
; temporarily-disabled bp, clears step state.  KERNAL-ZP / VIC /
; colour hygiene is `hygiene_after_userland`, run earlier by
; main.s's handler_finalize.
; ═══════════════════════════════════════════════════════════

; ── hygiene_after_userland — restore KERNAL/VIC state post-user-run ──
; User code can leave the machine in any state: VIC blanked or in
; bitmap/multicolor/extended-color mode, charset pointer moved,
; sprites covering the text layer, raster IRQ armed, color RAM
; painted over, stuck keys in $C6, KERNAL cursor re-enabled, KERNAL
; screen-edit ZP mid-CHROUT (RESTORE pressed inside a tight `$FFD2`
; loop in user code → NMI hit at e.g. PC=$E9D6 mid-write).  Clean
; everything before returning control to the REPL/editor.
;
; KERNAL screen-edit ZP defence: kernal_screen_reset wipes
; $C6/$D4/$D5/$D8/$CE/$D9-$F1 to pristine post-init values, and the
; tail-called io_sync (KERNAL PLOT) sets $D1/$D2/$D3/$D6/$F3/$F4
; against that clean state.  Without the helper, a corrupt LDTB1
; ("rows 9-10 are a single 2-row logical line", left over from
; user's wrapped CHROUT) makes PLOT compute wrong $D1/$D2 / $D3
; on the very next REPL or editor cursor move — that's the rc1 jank.
;
; Clobbers: A, X, Y (via vic_reset + restore_colors +
; kernal_screen_reset + io_sync).
hygiene_after_userland:
        ; The KERNAL's blink off (the cse_io invariant); the SHIFT+C=
        ; charset toggle locked (userland may have cleared the lock; the
        ; KERNAL honours the combo when it is 0); SID voices 1–3 silenced
        ; (their control registers zeroed to release any gates left on
        ; — write-only registers, so no read-modify-write of bit 0).
        PLAT_HYGIENE
        jsr vic_reset           ; $D011/$D015/$D016/$D018/$D019/$D01A
        jsr restore_colors      ; border/bg/fg + color RAM + CHROUT colour

        ; If the break was an NMI (canonical trigger: RUN/STOP+
        ; RESTORE), arm stop_cooldown so main_loop's edge-filter
        ; swallows any STOPs still in flight from the held key.
        ; The cooldown clears automatically once KERNAL STOP
        ; ($FFE1) reports the key released.
        lda dbg_reason
        cmp #DBG_NMI
        bne @drain
        lda #1
        sta stop_cooldown
@drain:
        ; kernal_screen_reset includes draining $C6 — no separate
        ; sta NDX needed.  Must run BEFORE io_sync so PLOT walks a
        ; clean LDTB1 to compute $D1/$D2/$F3/$F4.
        jsr kernal_screen_reset
        jmp io_sync             ; tail-call

; ═══════════════════════════════════════════════════════════
; cmd_jmp — 'j'/'g' command.  Stages reg_* / brk_pc (already in
; cur_addr by caller), drains kbd buffer, requests a fresh-start
; run (MODE_JUMP = push sentinel).
;
; Debug-session gate: if dbg_reason indicates an active
; resumable session (DBG_BRK / DBG_NMI), warn ";!debug" + ask
; "go? y/n".  On yes: end the debug session and replay the
; command via warm_cont (mirrors the `a` command pattern).
; On cancel: nl_clear and return to repl.  On DBG_NONE / DBG_RTS
; the gate is transparent — j/g proceed immediately.
;
; Per debugger.md § dbg_reason × command matrix.
; ═══════════════════════════════════════════════════════════
.proc cmd_jmp
        lda dbg_reason
        cmp #DBG_BRK
        bcc @run                ; DBG_NONE / DBG_RTS — no gate
        ; Active resumable session — warn + ask + end-debug-replay.
        jsr warn_if_debug
        lda #<str_go
        ldx #>str_go
        jsr query_user
        bcc @cancel
        lda #1
        sta warm_cont           ; replay line_buf after end-debug
        jmp cse_end_debug
@cancel:
        jsr cur_unstash         ; nothing changes (repl.md § `j`)
        jmp nl_clear
@run:
.ifdef PLATFORM_M65
        jsr start_bank          ; run_bank: a flat address's, or 0
        bcc :+
        jsr cur_unstash         ; refused: nothing changes
        jmp dot_range
:
.endif
        lda cur_addr
        sta brk_pc
        lda cur_addr+1
        sta brk_pc+1
        jsr pre_userland_run
        lda #MODE_JUMP
        sta run_user_pending
        rts
.endproc

; ── cur_stash / cur_unstash — the current address (and on m65 its
; space) saved by `j` / `g` before they set it, restored when cmd_jmp
; cancels or refuses the start.  Clobbers A (and X on m65).
cur_stash:
        lda cur_addr
        sta cur_save
        lda cur_addr+1
        sta cur_save+1
.ifdef PLATFORM_M65
        ldx #2
@s:     lda cur_flat,x
        sta cur_save_spc,x
        dex
        bpl @s
.endif
        rts
cur_unstash:
        lda cur_save
        sta cur_addr
        lda cur_save+1
        sta cur_addr+1
.ifdef PLATFORM_M65
        ldx #2
@u:     lda cur_save_spc,x
        sta cur_flat,x
        dex
        bpl @u
.endif
        rts

; ── pre_userland_run — shared pre-flight for j/g/t/o ────────────────
; Newline + clreol so user CHROUT starts on a fresh row, plus a
; keyboard-buffer drain so user's first GETIN/CHRIN doesn't see
; keys the user typed while issuing the command.
; Clobbers: A, X, Y.
pre_userland_run:
        jsr newline
        jsr io_clear_eol
        lda #0
        IO_KBD_FLUSH
        rts

; ═══════════════════════════════════════════════════════════
; cmd_step — 't' (step-into) / 'o' (step-over) command.
;
; Seeds the handler-resident step state machine; does not loop.
; Per debugger.md § dbg_reason × command matrix, gates by reason:
;
;   DBG_NONE  → cold preview (init brk_pc := cur_addr, emit
;               "; dbg" panel, promote to DBG_BRK + arm
;               cold_preview_done; rts to repl without
;               entering userland).
;   DBG_RTS   → reject (";?no ctx") — terminal session.
;   DBG_BRK   → step (real run).
;   DBG_NMI   → step (real run).
;
; Real-step path (DBG_BRK / DBG_NMI):
;   1. Set step_state (STEP_INTO / STEP_OVER).
;   2. Disable any user bp at brk_pc (so the first step doesn't
;      immediately re-hit its own bp).
;   3. step_next_pc → lookahead address(es).  Both zero (BRK
;      opcode) → early-stop via post_run_cleanup.
;   4. Workspace gate: bp_range_check on each non-zero arm slot;
;      out-of-range → ";!range" warn, no step.
;   5. Warm-step "up 3 lines" + emit pre-step disas (single-step
;      only — multi-step skips to avoid screen flood).
;   6. arm_step_bp + step_remaining := N-1 + pre_userland_run.
;   7. MODE selection: cold_preview_done set → MODE_JUMP (push
;      sentinel for first real step after cold preview, consume
;      flag); else MODE_RESUME.
;   8. RTS up to main_loop, which dispatches via run_user_pending.
;
; Argument parsing: try_expr_or_err parses the count + rejects
; trailing garbage via the pop-trick (so `t10xyz` aborts cleanly
; with ";?syntax" before any state is written).  Default count 1;
; an expression error (try_expr Z=0) returns at once, like `j`.
;
; In: rp_ptr = args, A = is_next (0=into, 1=over)
; ═══════════════════════════════════════════════════════════
.proc cmd_step
        sta rp_save2            ; is_next (0=into, 1=over)

        ; Parse count: via try_expr_or_err (parse + reject trailing
        ; garbage via the pop-trick helper), or default to 1 (single
        ; step).  t/o are single-step by default; an expression arg
        ; overrides (e.g. `t10` = step 10 instructions).  No state
        ; has been written yet, so a garbage-escape is clean.
        jsr try_expr_or_err
        bcc @no_arg
        lda expr_val
        ora expr_val+1
        beq @def_count          ; zero → default
        lda expr_val
        sta rp_cnt
        lda expr_val+1
        sta rp_cnt+1
        jmp @got_cnt
@no_arg:
        bne @ret                ; Z=0: expression error — no step
@def_count:
        lda #1
        sta rp_cnt
        lda #0
        sta rp_cnt+1
@got_cnt:

        ; Step gate by dbg_reason:
        ;   DBG_BRK / DBG_NMI → step (resumable session).
        ;   DBG_NONE          → cold preview (fresh state — emit
        ;                       "; dbg" panel, promote to DBG_BRK,
        ;                       next t/o steps for real).
        ;   DBG_RTS           → reject ("; ?no ctx") — terminal
        ;                       session, user must j/g to restart.
        ;                       Mirrors `c`'s gate behaviour.
        ;                       Without this, t after a clean exit
        ;                       would re-trigger cold preview each
        ;                       time, looping rts/dbg/rts/dbg.
        lda dbg_reason
        cmp #DBG_BRK
        bcs @do_step
        cmp #DBG_RTS
        beq @no_ctx
        ; DBG_NONE — cold preview path
.ifdef PLATFORM_M65
        jsr start_bank          ; a flat address: a far start's preview —
        bcc :+                  ;   the bank state seeded first, so the
        jmp dot_range           ;   panel sees the bank (debugger.md)
:       jsr seed_bank_state
.endif
        lda cur_addr
        sta brk_pc
        lda cur_addr+1
        sta brk_pc+1
        jsr show_cold_preview
        lda #DBG_BRK
        sta dbg_reason
        lda #1
        sta cold_preview_done
@ret:   rts
@no_ctx:
        lda #<str_no_ctx
        ldx #>str_no_ctx
        jmp log_err
@do_step:

        ; step_state = STEP_OVER if is_next else STEP_INTO.
        lda rp_save2
        beq @into
        lda #STEP_OVER
        .byte $2C               ; BIT abs — skip next 2 bytes
@into:  lda #STEP_INTO
        sta step_state

        ; User BRK skip: o (STEP_OVER) advances past a user BRK
        ; opcode at brk_pc (advances brk_pc by 2 — past BRK +
        ; signature byte).  t (STEP_INTO) does NOT skip — the user
        ; specifically wants to "hang" at user BRK to interrupt
        ; the return-step workflow for inspection.  See
        ; brk_skip_user docstring + debugger.md § user BRK workflow.
        lda step_state
        cmp #STEP_OVER
        bne @no_brk_skip
        jsr brk_skip_user
@no_brk_skip:

        ; Temporarily disable any user-visible bp at brk_pc.
        lda #$FF
        sta rp_dis_bp
        lda dbg_bp_hit
        cmp #$FF
        beq @no_disable
.ifdef PLATFORM_M65
        jsr slot_offset         ; slot × SLOT_SIZE
.else
        asl
        asl                     ; slot × 4
.endif
        tax
        stx rp_dis_bp
        lda #0
        sta bp_table+BP_FLAGS,x ; disable flag
@no_disable:

        ; Compute first next-PC.  step_next_pc reads opcode at brk_pc.
        jsr step_next_pc

        ; If both slots zero, opcode at brk_pc is BRK ($00) —
        ; step_next_pc's @rts/@rti handle the return ops by
        ; peeking the user stack, so they DO return non-zero
        ; lookahead and proceed normally to @arm.  Only $00
        ; falls through to "no slots".  Stop without entering
        ; userland: post_run_cleanup finishes the step (clear
        ; step_state, re-enable disabled bp, show panel) with
        ; dbg_reason left as the handler set it (DBG_BRK on
        ; the prior trap landing — show_break_result tags it
        ; "; brk", which is correct: we trapped at a BRK opcode).
        lda step_next_lo
        ora step_next_lo+1
        ora step_next_hi
        ora step_next_hi+1
        bne @arm
        jmp post_run_cleanup    ; tail-call

@arm:
        ; Workspace gate: any non-zero step BRK arm slot must
        ; land in [workstart, workend] (or be brk_stub — see
        ; bp_range_check_step header).  Stepping into ROM/IO/
        ; KDATA would patch transient $00 bytes there (writes
        ; pass through under ROM, hit IO regs in $D000 page);
        ; refuse and warn ";!range" instead.
        ; The handler's step chain (t/o N > 1) takes the same gate.
        jsr step_targets_check
        bcs @oor_warn

        ; Warm-step "up 3 lines" mechanic (single-step only).
        ;
        ; Cursor at exec_line entry sits on the prompt row mid-line
        ; (after user's typed "t" + RETURN — main.s comment "Cursor
        ; intentionally NOT homed").  The previous panel above is
        ; 3 rows tall: info / regs / disas.  Going up 3 lands at
        ; the info row; the pre-step disas overwrites it, becoming
        ; the audit-trail entry of "what just ran" once the step
        ; completes.  show_break_result then emits the new
        ; info/regs/disas in the rows below (overwriting the prior
        ; panel's regs/disas/prompt), and show_prompt appends a
        ; fresh prompt one row further down.  Net: panel slides
        ; down by 1, leaving 1 row of history per step.
        ;
        ; Multi-step (rp_cnt > 1) skips this — would flood screen.
        lda rp_cnt+1
        bne @skip_log
        lda rp_cnt
        cmp #2
        bcs @skip_log
        ; IO_CY := max(IO_CY - panel height, 0)
.ifdef PLATFORM_C64
        lda IO_CY
        sec
        sbc #3
.else
        lda scr_width
        cmp #80                 ; C = 0 in 40 columns: the panel's `r`
        lda IO_CY               ; is two rows there, so − 4
        sbc #3
.endif
        bcs @set_row
        lda #0
@set_row:
        sta IO_CY
        lda #0
        sta IO_CX
        jsr io_sync
        ; Emit pre-step disas at brk_pc.  No closing newline —
        ; pre_userland_run's newline advances cursor to the row
        ; below for the post-step show_break_result emission.
        ; io_clear_eol wipes any leftover chars from the prior
        ; (possibly longer) info-row content.
        lda brk_pc
        sta rp_addr
        lda brk_pc+1
        sta rp_addr+1
        jsr emit_dot
        jsr io_clear_eol
@skip_log:

        jsr arm_step_bp

        ; step_remaining = count - 1 (first iteration runs below via
        ; return_to_userland / restore_userland_state; N-1 via handler chain).
        lda rp_cnt
        sec
        sbc #1
        sta step_remaining
        lda rp_cnt+1
        sbc #0
        sta step_remaining+1

        jsr pre_userland_run
        jmp set_run_mode        ; tail-call

@oor_warn:
        ; Step BRK arm slot is outside [workstart, workend].
        ; Warn and refuse the step — user keeps their session
        ; (dbg_reason and brk_pc unchanged), can `c` to run past
        ; the offending region or `r pc:XXXX` to relocate.
        ; Undo the step set-up above (step_state, disabled bp).
        jsr step_cleanup
        lda #<str_range
        ldx #>str_range
        jmp log_warn
.endproc

; ── set_run_mode — run_user_pending for a step / `c` ──────────────────
; MODE_JUMP if a cold preview established the session (no user code
; has run, so no sentinel is on the user stack yet — this transition
; must push one), consuming cold_preview_done; else MODE_RESUME (the
; sentinel from the session's fresh start is still in place).
; Clobbers: A.
set_run_mode:
        lda cold_preview_done
        beq @resume
        lda #0
        sta cold_preview_done
        lda #MODE_JUMP
        .byte $2C
@resume: lda #MODE_RESUME
        sta run_user_pending
        rts

; ═══════════════════════════════════════════════════════════
; cmd_brk — 'b' command: breakpoints
;   rp_ptr = args
; ═══════════════════════════════════════════════════════════
.proc cmd_brk
        jsr skip_sp_ptr1

        ldy #0
        FAR_LDA rp_ptr
        bne :+
        jmp @list_all
:       cmp #'*'
        bne :+
        jmp @clear_all
:       cmp #'-'
        bne :+
        jmp @delete_one
:

        ; b ADDR — set breakpoint.  try_expr_or_err parses AND
        ; rejects trailing garbage via the pop-trick — so a bad
        ; "b ADDR xyz" never installs the bp.  An expression error
        ; (Z=0) was reported by try_expr: stop there; only the
        ; empty case (`b ;…`) is a syntax error.
.ifdef PLATFORM_M65
        jsr try_addr_or_err     ; flat (`b 4.2005`, `b loop`) or CPU
        bcs :+
        bne @ret                ; an error, printed
        jmp _syntax_err         ; empty
:       bit rp_flat
        bpl @set                ; a CPU address: expr_val's low word
        jsr bp_flat_arg         ; lens_ptr := it; C=1 not user memory
        jcs @bp_range
        ldx #3                  ; rp_ptr := the flat address
@fc:    lda lens_ptr,x
        sta rp_ptr,x
        dex
        bpl @fc
        jsr dbg_bp_set_flat
        jmp @echo
.else
        jsr try_expr_or_err
        bcs @set
        bne @ret
        jmp _syntax_err
.endif
@ret:   rts
@set:
        ; Range-check: bp must land in [workstart, workend] —
        ; the user-code workspace.  bp_range_check enforces this
        ; against the dynamic buf_base (editor source area starts
        ; just above workend).
        lda expr_val
        ldx expr_val+1
        jsr bp_range_check
        jcs @bp_range
        lda expr_val
        ldx expr_val+1
        jsr dbg_bp_set         ; returns slot in A ($FF=full)
.ifdef PLATFORM_M65
@echo:  cmp #$FF                ; rp_ptr: the slot's flat address
        bne :+
        jmp @full
:       jsr bp_open_slot
        puts str_colon_sp
        jsr put_rp_flat
        jmp log_close
.else
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
.endif

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
.ifdef PLATFORM_M65
        jsr slot_offset
        tax
        jsr list_slot_flat      ; C=1 empty
        bcs @empty_slot
        jmp @slot_done
.else
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
.endif
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
        FAR_LDA rp_ptr
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

@done:  jmp io_clear_eol
.endproc

; ═══════════════════════════════════════════════════════════
; cmd_reg — 'r' command
;   rp_ptr = args
;
; Bare `r` shows the registers.  Otherwise the fields are matched by
; label, in any order, any subset (debugger.md § `r`):
;   a:XX x:XX y:XX s:XX   reg_a / reg_x / reg_y / reg_sp
;   pc:XXXX               brk_pc
;   8 flag characters     reg_p (nv-bdizc; uppercase = set, lowercase,
;                         '-' or '.' = clear; bit 5 forced 0)
; Each field ends at a space, ';' or NUL.  The line is checked in full
; first (reg_fields with rp_save2 = 0) and applied only when every
; field is valid (second pass, rp_save2 = 1) — a bad field is
; `;?syntax` and changes nothing.
; ═══════════════════════════════════════════════════════════
.proc cmd_reg
        jsr skip_peek_ptr1
        beq @show
        lda rp_ptr
        sta rp_addr             ; start of the fields, for pass 2
        lda rp_ptr+1
        sta rp_addr+1
        lda #0
        sta rp_save2            ; pass 1: check only
        jsr reg_fields
        bcs @syntax
        lda rp_addr
        sta rp_ptr
        lda rp_addr+1
        sta rp_ptr+1
        inc rp_save2            ; pass 2: apply
        jsr reg_fields
@show:  ; emit_reg already sets IO_CX=0, so it overwrites the
        ; current row — the edited `r …` line is replaced in place
        ; with the authoritative formatted register state.  nl_clear
        ; then advances to a fresh row for the next prompt.
        jsr emit_reg
        jmp nl_clear
@syntax:
        jmp _syntax_err
.endproc

; ── reg_fields — one pass over cmd_reg's fields ─────────────────────
; In:  rp_ptr = first field, rp_save2 = 0 check only / 1 apply.
; Out: C=0 all fields valid (applied when rp_save2 != 0); C=1 a field
;      is invalid.  rp_ptr advanced.
; Clobbers: A, X, Y, rp_tmp, rp_tmp2, rp_save.
.proc reg_fields
@next:  jsr skip_peek_ptr1      ; A = char, Y = 0
        beq @ok
        cmp #';'
        beq @ok
.ifdef PLATFORM_M65
        cmp #'m'                ; `ml:XXXX` / `mh:XXXX`: the program's MAP
        bne :+
        jsr map_reg_field
        bcs @err
        jmp @next
:
.endif
        ldx #REG_LABEL_LAST     ; 0-3 = a x y s, 4 = pc; m65 5-6 = z b
@lbl:   cmp reg_labels,x
        beq @label
        dex
        bpl @lbl
        ; No label: the 8-character flags field, then end of field.
@fl:    FAR_LDA rp_ptr
        eor str_flag_ch,y
        beq @f0                 ; lowercase reference → clear
        cmp #$80
        beq @f1                 ; uppercase reference → set (C=1)
        FAR_LDA rp_ptr
        cmp #'-'
        beq @f0
        cmp #'.'
        bne @err
@f0:    clc
@f1:    rol rp_tmp
        iny
        cpy #8
        bcc @fl
        jsr is_eow_at_ptr1_y    ; Y = 8
        bne @err
        tya
        jsr adv_ptr1
        lda rp_tmp
        and #%11011111          ; keep bit 5 = 0 invariant (matches
                                ; the capture-time mask in main.s);
                                ; lets emit_reg skip its '-' guard.
        ldx #4                  ; reg_a + 4 = reg_p (asm_line.s order)
        bne @store              ; always

@err:   sec
        rts
@ok:    clc
        rts

@label: ; "L:XX" (L = a/x/y/s) or "pc:XXXX"
        iny
        cpx #4
        bne @colon
        FAR_LDA rp_ptr
        cmp #'c'
        bne @err
        iny
@colon: FAR_LDA rp_ptr
        cmp #':'
        bne @err
        iny
        tya
        jsr adv_ptr1            ; past the label
        ; Digits: 2, or 4 for pc; then end of field.
        lda #0
        sta rp_tmp
        sta rp_tmp2
        tay
@dig:   FAR_LDA rp_ptr
        jsr _hex_val
        cmp #$10
        bcs @err
        sta rp_save
        lda rp_tmp
        asl
        asl
        asl
        asl
        ora rp_save
        sta rp_tmp              ; pc: the high byte is ready after
        iny                     ; two digits — move it up
        cpy #2
        bne :+
        cpx #4
        bne @digend
        sta rp_tmp2
:       cpy #4
        bcc @dig
@digend:
        jsr is_eow_at_ptr1_y
        bne @err
        tya
        jsr adv_ptr1
        lda rp_tmp
        cpx #4
.ifdef PLATFORM_M65
        beq @pc                 ; 5-6 are z b, stored as the others
.else
        bcs @pc
.endif
@store: ldy rp_save2            ; pass 1: check only
        beq @to_next
        sta reg_a,x
@to_next:
        jmp @next
@pc:    ldy rp_save2
        beq @to_next
        sta brk_pc
        lda rp_tmp2
        sta brk_pc+1
        bcs @to_next            ; always (C=1 from cpx #4)
.endproc

; ── adv_ptr1 — rp_ptr += A.  Clobbers A. ───────────────────────────
adv_ptr1:
        clc
        adc rp_ptr
        sta rp_ptr
        bcc :+
        inc rp_ptr+1
:       rts

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
@len:   FAR_LDA rp_ptr2
        beq @got_len
        iny
        bne @len
@got_len:
        cpy #2
        bcc @none               ; too short for ",m" suffix
        dey
        FAR_LDA rp_ptr2         ; last char
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
        FAR_LDA rp_ptr2         ; char before letter
        cmp #','
        bne @none
        lda #0                  ; truncate at comma
        FAR_STA rp_ptr2
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
@cp:    FAR_LDA rp_ptr2
        sta cur_project_name,y
        beq @strip              ; copy hit NUL → start trailing-dot strip
        iny
        cpy #FILENAME_MAX
        bcc @cp
        lda #0
        sta cur_project_name,y ; force NUL at max
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
        FAR_LDA rp_ptr
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
        FAR_BANK rp_ptr2, BANK_CSE      ; the typed name, in line_buf
        ; scan for closing quote.  NUL before a closing quote is an
        ; unterminated-string syntax error — see @unterm.
        ldy #0
@scan:  FAR_LDA rp_ptr
        beq @unterm
        cmp #$22
        beq @close
        iny
        bne @scan
@close: ; NUL-terminate at closing quote, advance past it
        lda #0
        FAR_STA rp_ptr
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
        FAR_LDA rp_ptr2
        beq @fail
        lda #1                  ; A=1, Z=0: name found
        rts
@fail:  lda #0                  ; A=0, Z=1: no name
        rts
        ; ─── unterminated-string abort ──────────────────────────────
        ; `l "foo` / `s "foo` (no closing quote) is a syntax error.
        ; Use the multi-level pop-trick (extension of optimization.md
        ; § 36) to escape the entire l/s command without leaving
        ; partial state for callers to act on.  Stack at entry:
        ;   bottom → [main_loop ret][cmd_l/s ret][parse_ls_args ret]
        ;            [get_filename ret] ← top
        ; Pop the top three frames; log_err's rts pops main_loop's ret.
        ; cmd_load / cmd_write are dispatched via @h_l / @h_s as `jmp`
        ; (no extra frame), so the stack shape matches every time.
@unterm:
        pla                     ; discard get_filename ret lo
        pla                     ; discard get_filename ret hi
        pla                     ; discard parse_ls_args ret lo
        pla                     ; discard parse_ls_args ret hi
        pla                     ; discard cmd_l/s ret lo
        pla                     ; discard cmd_l/s ret hi
        jmp _syntax_err
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
        FAR_BANK rp_ptr2, BANK_CSE      ; CSE's datum (m65: zp.s's BSS)
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

; warn_long_lines — print ";!long LNN" for each line > LINE_MAX vcols
;
; Walks the buffer via ed_read_byte, computing visual width per
; line.  Prints one warning per overflowing line.  TAB_WIDTH is
; hardcoded to match the build-time constant (default 8).
; ═══════════════════════════════════════════════════════════
.proc warn_long_lines
        jsr ed_read_rewind
        lda #0
        sta wl_vcol
        sta wl_line
        sta wl_line+1

@byte:  jsr ed_read_byte
        cpx #$FF
        beq @check_last         ; EOF

        cmp #$0D
        beq @eol

        ; Compute visual width of byte
        cmp #$A0                ; tab?
        beq @tab
        ; Non-tab: width = 1
        inc wl_vcol
        jmp @byte

@tab:   ; next tab stop: vcol + TAB_WIDTH - (vcol & TAB_MASK)
        ;                  = (vcol | TAB_MASK) + 1
        lda wl_vcol
        ora #TAB_MASK_WL
        clc
        adc #1
        sta wl_vcol
        jmp @byte

@eol:   ; End of line — check if vcol > LINE_MAX
        jsr @check_vcol
        ; Advance line counter, reset vcol
        inc wl_line
        bne :+
        inc wl_line+1
:       lda #0
        sta wl_vcol
        jmp @byte

@check_last:
        ; EOF — check the last line if it had any content
        lda wl_vcol
        beq @done
        jsr @check_vcol
@done:  rts

@check_vcol:
        lda wl_vcol
        cmp #LINE_MAX + 1       ; > LINE_MAX ?
        bcc @ok
        ; Print ";!long LNN" (1-based line number)
        ldy #LOG_WARN
        jsr log_open
        puts str_long
        lda wl_line
        clc
        adc #1
        sta rp_tmp
        lda wl_line+1
        adc #0
        tax
        lda rp_tmp
        jsr io_putdec
        jsr log_close
@ok:    rts

.segment "BSS"
wl_vcol: .res 1                 ; visual column of the current line
wl_line: .res 2                 ; 0-based line number
.segment "CODE"
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
; Prints the status the transfer itself read into fl_buf (every
; disk.s transfer leaves it there; reading it again would show
; "00, ok" — the drive clears its message once read).
; Callers must leave the cursor on a fresh row (prg_line, log_err,
; etc. all end with a newline already).
; ═══════════════════════════════════════════════════════════
disk_done:
        lda #<fl_buf
        ldx #>fl_buf
        jsr log_info
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
@cp:    FAR_LDA rp_ptr2
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
        ; Gate: warn + prompt only when editor is dirty.  Per
        ; debugger.md § dbg_reason × command matrix, l/s have NO
        ; debug gating — loading new source under an active debug
        ; session is the user's call (breakpoints may invalidate;
        ; they own that decision).  Unsaved-edits gate stays.
        lda ed_dirty
        beq @do_load
        jsr warn_if_unsaved
        lda #<str_load
        ldx #>str_load
        jsr query_user
        bcs @do_load
        jmp nl_clear

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
        lda _io_tmp             ; start: where the file landed
        sta rp_addr
        lda _io_tmp+1
        sta rp_addr+1
        lda rp_cnt
        ora rp_cnt+1
        bne prg_ok_done
        jmp io_err_load         ; tail-jumps to disk_done
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

.ifdef PLATFORM_C64                     ; m65: info_m65_rows
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
        FAR_LDA rp_ptr
        sta rp_ptr2
        iny
        FAR_LDA rp_ptr
        sta rp_ptr2+1
        iny
        FAR_LDA rp_ptr
        sta rp_addr
        iny
        FAR_LDA rp_ptr
        sta rp_addr+1
        iny
        FAR_LDA rp_ptr
        sta rp_cnt
        iny
        FAR_LDA rp_ptr
        sta rp_cnt+1
        iny
        FAR_LDA rp_ptr
        pha                     ; desc lo
        iny
        FAR_LDA rp_ptr
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
.endif

; ── cmd_info — memory map display ─────────────────────────
; In:  C=0 full mode (i command), C=1 splash mode (free only)
; Splash mode: only free sections, no highlight, no newline
; Full mode:   all sections, highlighted free, caller does newline
.proc cmd_info
        ; capture carry → _info_mode (zp.s; 0=full, 1=splash),
        ; read by info_emit_rows and log.s's info_line family.
        lda #0
        adc #0
        sta _info_mode
.ifdef PLATFORM_C64

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
        lda #INFO_ZP_LO
        sta rp_addr
        lda #INFO_ZP_HI
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
        lda #<INFO_LOW1_LO
        sta rp_addr
        lda #>INFO_LOW1_LO
        sta rp_addr+1
        lda #<INFO_LOW1_HI
        sta rp_cnt
        lda #>INFO_LOW1_HI
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
        lda #<INFO_LOW2_LO
        sta rp_addr
        lda #>INFO_LOW2_LO
        sta rp_addr+1
        lda #<INFO_LOW2_HI
        sta rp_cnt
        lda #>INFO_LOW2_HI
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
        lda #<WORKSTART
        sta rp_addr
        lda #>WORKSTART
        sta rp_addr+1
        lda buf_base
        sec
        sbc #1
        sta rp_cnt
        lda buf_base+1
        sbc #0
        sta rp_cnt+1
        jsr free_line
.else
        FAR_BANK rp_ptr2, BANK_CSE      ; the tags are RODATA
        ldx #0
        ldy #INFO_M65_A
        jsr info_m65_rows               ; banks 0 and 1
.endif

        ; ── sections below are full-mode only ──
        lda _info_mode
.ifdef PLATFORM_C64
        jne @done
.else
        bne @rows_b                     ; splash: the rest's free rows
.endif

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
.ifdef PLATFORM_M65
        lda #BANK_SRC
        sta info_bank
.endif
        jsr info_line_head      ; "; src  AAAA-BBBB "
        jsr print_seq_stats     ; "Nl Nb" streamed
        jsr info_line_tail
@no_src:
.ifdef PLATFORM_C64

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
.else
@rows_b:
        ldx #INFO_M65_A
        ldy #INFO_M65_END
        lda scr_height
        cmp #50
        bcc :+
        ldy #INFO_M65_BANK4             ; 80 × 50: bank 4 holds the screen,
        jsr info_m65_rows               ;   so up to bank 3, then bank 5
        ldx #INFO_M65_BANK5
        ldy #INFO_M65_END
:       jsr info_m65_rows
        lda #0
        sta info_bank                   ; the other range rows: bank 0
.endif

@done:  jmp io_clear_eol
.endproc

.ifdef PLATFORM_M65
; ═══════════════════════════════════════════════════════════
; info_m65_rows — cmd_info's rows of info_m65 from offset X up to
; offset Y: a free row (desc 0) by free_line, the others by info_line
; in full mode only.  rp_ptr2's bank is BANK_CSE.
; Clobbers: A, X, Y, rp_opc, the info_line cells, info_bank.
; ═══════════════════════════════════════════════════════════
.proc info_m65_rows
        sty rp_opc              ; the end
@lp:    cpx rp_opc
        bcs @rts
        lda info_m65+0,x
        sta rp_ptr2
        lda info_m65+1,x
        sta rp_ptr2+1
        lda info_m65+2,x
        sta rp_addr
        lda info_m65+3,x
        sta rp_addr+1
        lda info_m65+4,x
        sta rp_cnt
        lda info_m65+5,x
        sta rp_cnt+1
        lda info_m65+6,x
        sta rp_ptr
        lda info_m65+8,x
        sta info_bank
        txa
        clc
        adc #INFO_M65_ROW
        pha                     ; the next row
        lda info_m65+7,x
        sta rp_ptr+1
        beq @free               ; desc 0: a free row
        lda _info_mode
        bne @next               ; splash: free rows only
        sta rp_save2            ; no highlight
        jsr info_line
        jmp @next
@free:  jsr free_line
@next:  pla
        tax
        bne @lp                 ; always (offset > 0)
@rts:   rts
.endproc
.endif


; ═══════════════════════════════════════════════════════════
; exec_line — parse line_buf and execute command
; ═══════════════════════════════════════════════════════════
.proc exec_line
        lda #<line_buf
        sta rp_ptr
        lda #>line_buf
        sta rp_ptr+1
        FAR_BANK rp_ptr, BANK_CSE       ; the parser's root: its walks and
                                        ; restores keep this bank (zp.md)

        jsr skip_sp_ptr1

.ifdef PLATFORM_M65
        ; A command's address is a CPU one unless load_curaddr or an
        ; argument makes it flat (repl.md § Banks).
        lda #0
        sta rp_flat
        ; ── An H.AAAA: prefix → a flat current address ──
        jsr parse_flat_ptr1
        bcs @cpu_prefix
        FAR_LDA rp_ptr          ; Y = the literal's length
        cmp #':'
        bne @cpu_prefix
        iny
        tya
        jsr adv_ptr1            ; past the prefix and its ':'
        lda rp_addr
        sta cur_addr
        lda rp_addr+1
        sta cur_addr+1
        lda #SPC_FLAT
        sta rp_flat
        CUR_FROM_RP
        lda #0
        sta rp_flat             ; load_curaddr sets it again
        jmp @no_prefix
@cpu_prefix:
.endif
        ; ── Parse optional AAAA: prefix → sets cur_addr ──
        jsr is_hex4_at_ptr1
        beq @no_prefix
        ldy #4
        FAR_LDA rp_ptr
        cmp #':'
        bne @no_prefix
        ; parse 4 hex digits
        jsr parse_hex4_ptr1
        sta cur_addr
        stx cur_addr+1
.ifdef PLATFORM_M65
        lda #0
        sta cur_flat            ; a CPU address
.endif
        ; skip ':'
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:
@no_prefix:
        jsr skip_sp_ptr1

        ; read command char
        ldy #0
        FAR_LDA rp_ptr
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
        FAR_LDA rp_ptr
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
        jmp (BP_ABS(rp_ptr2))
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
.ifdef PLATFORM_M65
@h_map: jmp cmd_map
.endif

@h_at:  ; @ — set address.  Parse+EOI-check → apply.
        ; Apply only after the EOI check so garbage input leaves
        ; cur_addr untouched.
.ifdef PLATFORM_M65
        jsr try_addr_or_err     ; an expression, flat or CPU (repl.md § Banks)
        bcc @at_done            ; empty/error → skip apply
        lda rp_addr
        sta cur_addr
        lda rp_addr+1
        sta cur_addr+1
        CUR_FROM_RP
        jmp @at_done
.endif
        jsr try_expr_or_err     ; parse + reject garbage (pop-trick)
        bcc @at_done            ; empty/error → skip apply
        lda expr_val
        sta cur_addr
        lda expr_val+1
        sta cur_addr+1
        SPACE_CPU
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
.ifdef PLATFORM_M65
        bcc @plus_done          ; a flat address carries into its bank
        bit cur_flat
        bpl @plus_done
        inc cur_bank
        bne @plus_done
        inc cur_bank+1
@plus_done:
.endif
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
.ifdef PLATFORM_M65
        bcs @minus_done         ; a flat address borrows from its bank
        bit cur_flat
        bpl @minus_done
        lda cur_bank
        bne :+
        dec cur_bank+1
:       dec cur_bank
@minus_done:
.endif
        jmp nl_clear

@h_j:   ; j — jump/execute
        ; Same pattern as @h_at: parse+EOI-check, then apply.  Bare
        ; `j` jumps to cur_addr; an expression error (already printed
        ; by try_expr) runs nothing.  cur_stash: a start cmd_jmp
        ; cancels or refuses leaves the current address as it was.
        jsr cur_stash
.ifdef PLATFORM_M65
        jsr try_addr_or_err     ; flat: a far start (repl.md § Far starts)
        bcc @j_none
        lda rp_addr
        sta cur_addr
        lda rp_addr+1
        sta cur_addr+1
        CUR_FROM_RP
        jmp cmd_jmp
.endif
        jsr try_expr_or_err     ; parse + reject garbage (pop-trick)
        bcc @j_none
        lda expr_val
        sta cur_addr
        lda expr_val+1
        sta cur_addr+1
        SPACE_CPU
@j_run:
        jmp cmd_jmp
@j_none:
        beq @j_run              ; empty → jump with current cur_addr
        rts                     ; error → no run

@h_g:   ; g — go (sym_lookup "main")
        jsr cur_stash           ; (as `j`)
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
        jsr try_expr_or_err     ; parse + reject garbage (pop-trick)
        bcc @B_show             ; empty or error → show current
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

@h_u:   ; u — cpu mode: a member of the build's CPU set, or just the list
        jsr skip_peek_ptr1      ; rp_ptr at the word (CSE's own line_buf)
        lda rp_ptr
        sta expr_ptr
        lda rp_ptr+1
        sta expr_ptr+1
        jsr cpu_lookup
        bcs @u_show             ; not a member: ignored
        sta asm_cpu
@u_show:
        ldy #LOG_INFO
        jsr log_open
        puts str_cpu            ; "cpu:"
        ldx #0
@u_ent: lda cpu_names,x         ; asm_cpu value, $FF = end
        bmi @u_end
        pha
        stx rp_tmp
        lda #' '
@u_ch:  jsr io_putc
        inc rp_tmp
        ldx rp_tmp
        lda cpu_names,x
        bne @u_ch
        pla
        cmp asm_cpu
        bne @u_next
        lda #'*'
        jsr io_putc
@u_next:
        ldx rp_tmp
        inx
        bne @u_ent
@u_end: jmp log_close
@h_a:   ; a — assemble source.  Per debugger.md § dbg_reason ×
        ; command matrix: warn + ask + end-debug-replay only for
        ; resumable sessions (DBG_BRK / DBG_NMI).  DBG_NONE / DBG_RTS
        ; pass through unchanged — assemble proceeds.  (Stack-heavy
        ; under an active session, ~130 B for nested exprs, hence
        ; the end-debug pattern rather than running concurrently.)
        lda dbg_reason
        cmp #DBG_BRK
        bcc @a_run
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
.ifdef PLATFORM_M65
        jsr a_bank              ; the default origin's bank
.endif
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
.ifdef PLATFORM_M65
        jsr expr_eval32         ; `?` takes 32 bits (expr.md § 32-bit values)
.else
        jsr expr_eval
.endif
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
.ifdef PLATFORM_M65
        lda expr_val+2
        ora expr_val+3
        jne calc_32             ; outside 16 bits: the 32-bit row
.endif
        lda expr_val+1
        bne @calc_16bit         ; >= 256: $xxxx, whatever the low byte
        jsr calc_put_u8_hex
        jmp @calc_dec
@calc_16bit:
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
        ; R — warmstart (uppercase).  Always prompts "init? y/n";
        ; on yes, end_debug_body (no-op if no session) + cse_refresh.
        ; Per debugger.md § dbg_reason × command matrix, R has NO
        ; debug gating — the reset action implicitly ends any debug
        ; session as a side effect; no separate "; ! debug" warn.
        lda #<str_init
        ldx #>str_init
        jsr query_user
        bcc @r_cancel
        jsr end_debug_body      ; idempotent — safe when no session
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
        FAR_LDA rp_ptr
        cmp #'0'
        bcc @dev_done
        cmp #'9'+1
        bcs @dev_done
        sec
        sbc #'0'
        pha
        ; dev = dev * 10 + digit.  dev >= 4 before another digit means
        ; >= 40 (out of range): pin it at $FF instead of letting the
        ; 8-bit product wrap back into 4-30 (`$ 260` would be 4).
        lda rp_tmp2
        cmp #4
        bcc @dev_mul
        pla
        lda #$FF
        bne @dev_set            ; always
@dev_mul:
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
@dev_set:
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

@h_c:   ; c — continue debugger.  Only resumable sessions (DBG_BRK
        ; and DBG_NMI) accept continue; DBG_NONE (never started) and
        ; DBG_RTS (terminal — ran off the top) are rejected.
        lda dbg_reason
        cmp #DBG_BRK
        bcs @c_has_ctx
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
        ; User BRK skip: if brk_pc points at a $00 opcode (lazy-debug
        ; user BRK), advance brk_pc by 2 (past BRK + signature byte)
        ; before resuming.  Without this, c would re-trap on the same
        ; BRK forever.  See brk_skip_user docstring + debugger.md
        ; § user BRK workflow.
        jsr brk_skip_user
        ; Drain KERNAL keyboard buffer.
        lda #0
        IO_KBD_FLUSH
        ; Resume (reuse the sentinel from the session's fresh start),
        ; or a fresh start if a cold preview set the session up.
        jmp set_run_mode

; ── Command dispatch table (parallel arrays) ──
@cmd_chars:
        .byte '.', 'd', 'm', 'b', 'r', 'l', 's', 'i'
        .byte '@', '+', '-', 'j', 'g', 't', 'o', 'k'
        .byte $C2, $C3, 'u', 'a', '?', $D1, '$', 'x'
        .byte 'c', $D2
.ifdef PLATFORM_M65
        .byte $CD               ; M: the program's map (repl.md § Banks)
.endif
        .byte 0                 ; sentinel
@cmd_lo:
        .byte <@h_dot, <@h_d, <@h_m, <@h_b, <@h_r, <@h_l, <@h_s, <@h_i
        .byte <@h_at, <@h_plus, <@h_minus, <@h_j, <@h_g, <@h_t, <@h_o, <@h_k
        .byte <@h_blk, <@h_col, <@h_u, <@h_a, <@h_calc, <@h_quit, <@h_dir, <@h_x
        .byte <@h_c, <@h_reset
.ifdef PLATFORM_M65
        .byte <@h_map
.endif
@cmd_hi:
        .byte >@h_dot, >@h_d, >@h_m, >@h_b, >@h_r, >@h_l, >@h_s, >@h_i
        .byte >@h_at, >@h_plus, >@h_minus, >@h_j, >@h_g, >@h_t, >@h_o, >@h_k
        .byte >@h_blk, >@h_col, >@h_u, >@h_a, >@h_calc, >@h_quit, >@h_dir, >@h_x
        .byte >@h_c, >@h_reset
.ifdef PLATFORM_M65
        .byte >@h_map
.endif
.endproc

; ── step_cleanup — end a step: no step state, step slots zeroed, the
; breakpoint cmd_step disabled (rp_dis_bp = slot × SLOT_SIZE) enabled again,
; rp_dis_bp := $FF.  Shared by post_run_cleanup (step landed), cmd_step
; (step refused) and main.s's end_debug_body (session ended).
; Clobbers: A, X.
step_cleanup:
        lda #STEP_NONE
        sta step_state
        sta step_remaining
        sta step_remaining+1
        jsr dbg_step_clear
        ldx rp_dis_bp
        cpx #$FF
        beq :+
        lda #1
        sta bp_table+BP_FLAGS,x
:       lda #$FF
        sta rp_dis_bp
        rts

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
;   * If we were stepping: clear step_state / step_remaining,
;     zero step_bp slots, re-enable any bp cmd_step disabled,
;     show break result.  For DBG_RTS landings clear last_cmd
;     so RETURN doesn't re-trigger cold preview after a clean
;     exit (terminal session — user must type a fresh command).
;   * Else just show break result (NMI / external BRK paths).
; ═══════════════════════════════════════════════════════════
; User-side stack headroom contract (conservative-pending-empirical;
; see userland_contract.md § 4) — its one definition; post_run_cleanup
; is its only reader.  One-byte change here + a doc edit tightens the
; contract post-audit.  Exported for the test harness's label lookup.
        .export kernel_stack_budget
kernel_stack_budget = 64

.proc post_run_cleanup
        ; Stack headroom warning.  If user's SP at break is below
        ; the documented kernel-reentry budget, log ";!stk N" where N
        ; is the remaining headroom (reg_sp as decimal).
        lda reg_sp
        cmp #kernel_stack_budget
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

        ; Stepping just finished.  step_state bit 7 = a chained step
        ; was refused by the range gate (main.s @chain_oor): the
        ; session stays at the instruction it would have run.
        bpl @in_range
        lda #<str_range
        ldx #>str_range
        jsr log_warn
@in_range:
        jsr step_cleanup

        ; Per spec: every brk emits info+regs+lookahead.  All step
        ; landings — including landings on rts/rti opcodes — go
        ; through show_break_result the same way; last_cmd stays
        ; intact so RETURN repeats t/o (with step_next_pc's @rts/@rti
        ; peeking the user stack, the next step naturally follows
        ; the return instead of getting stuck).
        ;
        ; DBG_RTS (clean exit via brk_stub) is the exception: the
        ; session is terminal and RETURN-repeating-t would just
        ; trigger another cold preview.  Clear last_cmd so RETURN
        ; goes back to "do nothing" instead.
        jsr show_break_result
        lda dbg_reason
        cmp #DBG_RTS
        bne @ret
        lda #0
        sta last_cmd
@ret:   rts

@not_step:
        jmp show_break_result
.endproc
