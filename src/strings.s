; strings.s — centralised string constants for CSE
;
; Every user-facing string lives here.  Other modules import the
; labels they need.  Duplicates are resolved via aliases.
;
; ── User-facing string style convention ──
;
;   "; ..."        normal status / info  (note the space after ';')
;   ";!..."        warning (dirty buffer, etc.)
;   ";?tag"        terse error tag, BASIC-style  (no space after ';?')
;   ";?word ..."   long error explanation
;   "; ...? y/n "  yes/no confirmation prompt (trailing space for cursor)
;
; Always lowercase.  Always a single space after ';' for status
; lines (the BASIC-error style ';?' is the one exception, and is
; reserved exclusively for short error tags so the user can scan
; for "did anything go wrong?" by looking for "?" at col 1).

        ; ── repl strings ──
        .export str_flag_ch, str_bp_pfx, str_3sp, str_2sp, str_brk
        .export str_at, str_nmi, str_ok_at, str_bp_clr, str_deleted
        .export str_syntax, str_bad_val, str_full, str_cmd
        .export str_no_name, str_range, str_fail, str_too_big
        .export str_expr, str_no_ctx
        .export str_r_pc, str_a, str_x, str_y, str_s
        .export str_lines, str_bytes, str_bytes_sp, str_long
        .export str_del_src, str_unsaved, str_ok, str_blk_eq
        .export str_color, str_cpu
        .export str_asm_ing, str_load_pfx, str_save_pfx, str_dots
        .export str_errors, str_quit, str_dashes, str_colon_sp, str_pct
        .export str_ioport, str_stack, str_kernal, str_screen
        .export str_bytes_free, str_free, str_l, str_main
        .export str_tag_cpu, str_tag_zp, str_tag_stk, str_tag_sys
        .export str_tag_work, str_tag_src
        .export str_tag_lo02
        .export str_tag_rom
        .export str_banked

.ifdef CPU_6510
        .export str_6510
.endif
.ifdef CMOS_SUPPORT
        .export str_65c02
.endif

        ; ── mem strings ──
        .export s_workstart, s_workend

        ; ── main strings ──
        .export VERSION_STR, s_manual
        .export s_zp_tag, s_lo02_tag, s_work_tag
        .export s_free

        ; ── asm_src strings ──
        .export s_err_sep, s_bad_val, s_exp_name, s_sym_full
        .export s_exp_quot, s_bad_insn, s_seg_pfx
        .export s_save_s, s_save_q_sp, s_save_default, s_trunc

        ; ── disk strings ──
        .export str_dname, str_dir_brk, str_blk_free, str_blk_pre, str_blk_suf

        ; ── shared RODATA tables ──
        .export dec_pow_lo, dec_pow_hi

        ; ── expr strings + dispatch tables ──
        .export err_none, err_expected, err_overflow
        .export err_paren, err_undefined, err_divzero
        .export err_str_lo, err_str_hi

; ═════════════════════════════════════════════════════════════
.segment "RODATA"
; ═════════════════════════════════════════════════════════════

; ── repl strings ────────────────────────────────────────────

str_flag_ch:        .byte "nv-bdizc"
str_bp_pfx:         .byte "bp ", 0
str_3sp:        .byte "   ", 0
str_2sp:        .byte "  ", 0
str_brk:        .byte "brk", 0
str_at:         .byte " at $", 0
str_nmi:        .byte "nmi at $", 0
str_ok_at:      .byte "ok at $", 0
str_bp_clr:     .byte "bp clr", 0
str_deleted:    .byte " del", 0

; Error content strings (prefix-free — out_log prepends ";?")
str_syntax:     .byte "syntax", 0        ; shared: asm + b + au_mode
str_bad_val:    .byte "bad val", 0
str_full        = s_sym_full + 4         ; "full" is suffix of "sym full"
str_cmd:        .byte "cmd", 0
str_no_name:    .byte "no name", 0
str_range:      .byte "range", 0
str_fail:       .byte "fail", 0          ; shared: load + save
str_too_big:    .byte "too big", 0
str_expr:       .byte "expr ", 0         ; prefix for expr_error_str text
str_no_ctx:   .byte "no ctx", 0

str_r_pc:       .byte "r pc:", 0
str_a:          .byte " a:", 0
str_x:          .byte " x:", 0
str_y:          .byte " y:", 0
str_s:          .byte " s:", 0
str_lines:      .byte "l ", 0
str_bytes:      .byte "b", 0
str_bytes_sp:   .byte "b ", 0
str_long:       .byte "long L", 0

str_del_src:    .byte "del src? y/n ", 0
str_unsaved:    .byte "unsaved ok? y/n ", 0
str_ok:         .byte "ok", 0
str_blk_eq:       .byte "blk=", 0               ; note: PETSCII uppercase B
str_color:      .byte "color: ", 0
str_cpu:        .byte "cpu: 6502", 0
.ifdef CPU_6510
str_6510:       .byte " 6510", 0
.endif
.ifdef CMOS_SUPPORT
str_65c02:      .byte " 65c02", 0
.endif
str_asm_ing:    .byte "asm...", 0          ; no trailing space: "asm...ok:"
str_load_pfx:   .byte "load ", 0
str_save_pfx:   .byte "save ", 0
str_dots        = str_asm_ing + 3        ; "..." is suffix of "asm..."
str_errors:     .byte " err", 0
str_quit:       .byte "quit? y/n ", 0
str_dashes:     .byte "$----", 0
str_colon_sp:   .byte ": ", 0
str_pct:        .byte "  %", 0

; info display strings
str_ioport:     .byte "port", 0
str_stack:      .byte "stack", 0
str_kernal:     .byte "kernal", 0
str_screen:     .byte "scr", 0
str_bytes_free: .byte "b free", 0
str_free:     .byte "free", 0
str_l:    .byte "l", 0
str_main:       .byte "main", 0

; info_line tag strings
str_tag_cpu:    .byte "cpu", 0
str_tag_zp:     .byte "zp", 0
str_tag_stk:    .byte "stk", 0
str_tag_sys:    .byte "sys", 0
str_tag_work:   .byte "work", 0
str_tag_src:    .byte "src", 0
str_tag_lo02:   .byte "low", 0
str_tag_rom:    .byte "rom", 0
str_banked:     .byte "banked", 0

; ── duplicate aliases (resolved here, one copy of data) ─────

str_cse_rt      = str_tag_cse           ; both "cse"
str_tag_scr     = str_screen            ; both "scr"
str_tag_cse:    .byte "cse", 0          ; canonical copy
str_tag_io      = str_io               ; both "io"
str_io:        .byte "io", 0           ; canonical copy
str_free_suf    = str_bytes_free        ; both "b free"
s_free          = str_bytes_free        ; main.s alias
s_bad_val       = str_bad_val           ; asm_src.s alias
s_err_sep       = str_colon_sp          ; asm_src.s alias, both ": "

        .export str_cse_rt, str_tag_scr, str_tag_cse
        .export str_tag_io, str_io
        .export str_free_suf

; ── disk strings ────────────────────────────────────────────

str_dname       = str_dashes            ; "$" is prefix of "$----"
str_dir_brk:    .byte "break", 0
str_blk_free:   .byte " blocks free.", 0
str_blk_pre:    .byte "; ", 0
str_blk_suf:    .byte " blocks", 0

; ── mem strings ─────────────────────────────────────────────

s_workstart:    .byte "workstart", 0
s_workend:      .byte "workend", 0

; ── main strings ────────────────────────────────────────────

VERSION_STR:    .byte "cse v0.1 by cr", 0
s_manual:       .byte "man: github.com/cr/cse", 0
s_zp_tag:       .byte "  zp ", 0
s_lo02_tag:     .byte "low  ", 0
s_work_tag:     .byte "work ", 0

; ── asm_src strings ─────────────────────────────────────────
; s_err_sep = str_colon_sp (alias, above)
; s_bad_val = str_bad_val  (alias, above)

s_exp_name:     .byte "exp id", 0
s_sym_full:     .byte "sym full", 0
s_exp_quot:     .byte "exp ", $22, 0
s_bad_insn:     .byte "bad insn", 0
s_seg_pfx:      .byte "org  ", 0
s_save_s:       .byte "s ", $22, 0
s_save_q_sp:    .byte $22, " $", 0
s_save_default: .byte "out,p", 0
s_trunc:        .byte ": truncated", 0

; ── shared tables ───────────────────────────────────────────

; Powers of 10 (low→high): all decimal routines index 4→0 via dex/bpl
dec_pow_lo:     .byte <1, <10, <100, <1000, <10000
dec_pow_hi:     .byte >1, >10, >100, >1000, >10000

; ── expr error strings + dispatch tables ────────────────────

err_str_lo:
        .byte <err_none, <err_none             ; 0=ZP, 1=ABS (not errors)
        .byte <err_expected, <err_overflow
        .byte <err_paren, <err_undefined
        .byte <err_divzero
err_str_hi:
        .byte >err_none, >err_none
        .byte >err_expected, >err_overflow
        .byte >err_paren, >err_undefined
        .byte >err_divzero

err_none:      .byte 0
err_expected:  .byte "exp val", 0
err_overflow:  .byte "ovfl", 0
err_paren:     .byte "exp )", 0
err_undefined: .byte "undef", 0
err_divzero:   .byte "div0", 0
