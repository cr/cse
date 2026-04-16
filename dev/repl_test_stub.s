; repl_test_stub.s — test harness for repl.s
;
; Provides stubs for all repl.s imports not satisfied by linked modules
; (cse_io.s, expr.s, symtab.s, dasm.s, dasm_tables.s, asm pipeline).
;
; Protocol: Python writes command into line_buf (via exported label),
; sets cur_addr/cur_device, then JSRs to repl_test_entry.
;
; Test entry points:
;   repl_test_exec   — calls exec_line
;   repl_test_read   — calls read_line
;   repl_test_prompt — calls show_prompt
;
; Captures:
;   Screen memory at $0400 (40×25) — written by real cse_io.s
;   newline_count — how many times newline was called

        .setcpu "6502"

; ── Exports: test entry points ────────────────────────────────
        .export repl_test_exec
        .export repl_test_read
        .export repl_test_prompt

; ── Exports: screen module ────────────────────────────────────
        .export newline, restore_colors, reset_screen
        .export cursor_show, cursor_hide
        .export theme_border, theme_bg, theme_fg

; ── Exports: assembler / execution stubs ──────────────────────
        .export asm_line, asm_expr_err
        .export asm_assemble, asm_org, asm_size, seg_print_save

; ── Exports: debugger stubs ───────────────────────────────────
        .export dbg_enter, dbg_step_clear
        .export dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .export dbg_bp_count
        .export bp_table, step_bp
        .export dbg_reason, dbg_bp_hit
        .export brk_pc
        .export step_witness
        .export reg_a, reg_x, reg_y, reg_sp, reg_p
        .export user_zp_buf

; ── Exports: disk stubs ───────────────────────────────────────
        .export floppy_status, floppy_read_status, fl_buf
        .export list_directory
        .export disk_load_prg, disk_save_prg
        .export _save_addr, _save_size, _load_result
        .export _save_name, _load_name
        .export _op_witness
        .importzp disk_ptr, rp_tmp, buf_base, _io_tmp

; ── Exports: editor stubs ─────────────────────────────────────
        .export ed_save_source, ed_load_source
        .export ed_save_bytes, ed_save_lines, ed_total_lines
        .export ed_ensure_init, ed_new, ed_dirty
        .export ed_read_rewind, ed_read_byte

; ── Exports: meminfo stubs (cse_start/end/zp_end now in mem.s) ──
        .export src_top, src_bot
        .export __CODE_RUN__    : absolute = $4000

; ── Exports: global state ─────────────────────────────────────
        .export state

; ── Exports: NMI stubs (for cse_io.s) ─────────────────────────
        .export dbg_running, dbg_nmi_break
        .export kplot_stub

; ── Exports: test instrumentation ─────────────────────────────
        .export newline_count

; ── Import repl.s entry points ────────────────────────────────
        .import exec_line, read_line, show_prompt
        .import cur_addr, cur_device, cur_project_name
        .import line_buf, last_cmd, block_size

; ── Import cse_io row tables (for KERNAL PLOT stub) ───────────
        .import scr_lo, scr_hi

; ── Force linker to resolve imports (make them visible in map) ──
.segment "RODATA"
sym_refs:
        .addr exec_line, read_line, show_prompt
        .addr cur_addr, cur_device, cur_project_name
        .addr line_buf, last_cmd, block_size
        .addr newline_count, kplot_stub
        .addr _save_addr, _save_size, _load_result
        .addr _save_name, _load_name, _op_witness

; ═══════════════════════════════════════════════════════════════
; BSS — test state + stubs (ZP provided by zp.s)
; ═══════════════════════════════════════════════════════════════
.segment "BSS"

; Debugger state
bp_table:      .res 32         ; 8 × 4
step_bp:       .res 8          ; 2 × 4
dbg_running:   .res 1
dbg_reason:    .res 1
brk_pc:        .res 2
dbg_bp_hit:    .res 1
step_witness:  .res 4          ; snapshot of step_bp[0..3] at dbg_enter
                                 ; entry — lets tests inspect what
                                 ; cmd_step armed before the cleanup
                                 ; path zero'd it

; Registers
reg_a:         .res 1
reg_x:         .res 1
reg_y:         .res 1
reg_sp:        .res 1
reg_p:         .res 1

; User ZP snapshot (mirrors asm_line.s::user_zp_buf)
user_zp_buf:   .res 88

; Editor state
ed_save_bytes: .res 2
ed_save_lines: .res 2
ed_total_lines: .res 2
ed_dirty:      .res 1

; Assembler state
asm_org:       .res 2
asm_size:      .res 2
asm_expr_err:  .res 1
fl_buf:        .res 32

; Disk I/O witnesses (test instrumentation)
_save_addr:    .res 2          ; addr passed to disk_save_prg
_save_size:    .res 2          ; size passed to disk_save_prg
_load_result:  .res 2          ; size returned by disk_load_prg
_save_name:    .res 17         ; name passed to disk_save_prg/ed_save_source
_load_name:    .res 17         ; name passed to disk_load_prg/ed_load_source
_op_witness:   .res 1          ; 0=no op, 1=PRG save, 2=SEQ save,
                                 ; 3=PRG load, 4=SEQ load

; Theme
theme_border:  .res 1
theme_bg:      .res 1
theme_fg:      .res 1

; Meminfo
src_top:       .res 2
src_bot:       .res 2

; Global
state:         .res 1

; Test instrumentation
newline_count:  .res 1          ; count newline calls


; ═══════════════════════════════════════════════════════════════
; CODE
; ═══════════════════════════════════════════════════════════════
.segment "CODE"

; ── Test entry points ─────────────────────────────────────────

repl_test_exec:
        lda #0
        sta newline_count
        jmp exec_line

repl_test_read:
        jmp read_line

repl_test_prompt:
        jmp show_prompt

; ═══════════════════════════════════════════════════════════════
; ═══════════════════════════════════════════════════════════════
; Screen stubs
; ═══════════════════════════════════════════════════════════════

COLS = 40

; newline — advance cursor row, track count
.proc newline
        inc newline_count
        inc $D6                 ; CUR_ROW
        lda $D6
        cmp #25
        bcc @ok
        lda #24                 ; clamp to last row
        sta $D6
@ok:    lda #0
        sta $D3                 ; CUR_COL = 0
        ; update screen line pointer
        ldx $D6
        lda scr_lo,x
        sta $D1
        lda scr_hi,x
        sta $D2
        clc
        adc #$D4                ; color RAM
        sta $F4
        lda scr_lo,x
        sta $F3
        rts
.endproc

; restore_colors — no-op in tests
restore_colors:
        rts

; cursor_show / cursor_hide — no-op in tests
cursor_show:
cursor_hide:
        rts

; reset_screen — clear screen + reset cursor
.proc reset_screen
        ldx #0
        lda #$20                ; space screen code
@clr:   sta $0400,x
        sta $0500,x
        sta $0600,x
        sta $0700,x
        inx
        bne @clr
        lda #0
        sta $D3
        sta $D6
        rts
.endproc

; ═══════════════════════════════════════════════════════════════
; Assembler stubs
; ═══════════════════════════════════════════════════════════════

; asm_line(buf) — A/X = text, caller sets asm_pc/asm_out
; Returns 0 (error) always in stub mode.
asm_line:
        lda #0
        tax
        rts

; asm_assemble — stub: stores A/X as asm_org, returns 0 errors
.proc asm_assemble
        sta asm_org
        stx asm_org+1
        lda #0
        sta asm_size
        sta asm_size+1
        tax
        rts
.endproc

; seg_print_save — stub: no-op
seg_print_save:
        rts

; ═══════════════════════════════════════════════════════════════
; Debugger stubs
; ═══════════════════════════════════════════════════════════════

dbg_enter:
        ; Snapshot step_bp[0..3] for tests, then return immediately.
        lda step_bp
        sta step_witness
        lda step_bp+1
        sta step_witness+1
        lda step_bp+2
        sta step_witness+2
        lda step_bp+3
        sta step_witness+3
        ; Pretend the step completed normally so cmd_step takes
        ; the @normal_end → show_break_result path: clear reason
        ; and bp_hit so the loop drops out cleanly.
        lda #0
        sta dbg_reason
        lda #$FF
        sta dbg_bp_hit
        rts

dbg_step_clear:
        ldx #7
        lda #0
@clr:   sta step_bp,x
        dex
        bpl @clr
        rts

; dbg_bp_set(addr) — __fastcall__: A/X = addr
; Returns slot in A, C=0 ok, C=1 full
.proc dbg_bp_set
        sta brk_pc             ; reuse as scratch
        stx brk_pc+1
        ; find first empty slot
        ldx #0
@scan:  lda bp_table,x
        ora bp_table+1,x
        beq @found
        txa
        clc
        adc #4
        tax
        cpx #32
        bcc @scan
        ; full
        lda #$FF
        sec
        rts
@found: lda brk_pc
        sta bp_table,x
        lda brk_pc+1
        sta bp_table+1,x
        lda #1
        sta bp_table+3,x       ; enabled
        txa
        lsr
        lsr                     ; slot = x/4
        clc
        rts
.endproc

; dbg_bp_del(slot) — __fastcall__: A = slot
dbg_bp_del:
        asl
        asl
        tax
        lda #0
        sta bp_table,x
        sta bp_table+1,x
        sta bp_table+2,x
        sta bp_table+3,x
        rts

; dbg_bp_clear
.proc dbg_bp_clear
        ldx #31
        lda #0
@clr:   sta bp_table,x
        dex
        bpl @clr
        rts
.endproc

; dbg_bp_count — returns count in A
.proc dbg_bp_count
        ldx #0
        lda #0
        stx rp_tmp                ; count
@lp:    lda bp_table,x
        ora bp_table+1,x
        beq @next
        inc rp_tmp
@next:  txa
        clc
        adc #4
        tax
        cpx #32
        bcc @lp
        lda rp_tmp
        rts
.endproc

; ═══════════════════════════════════════════════════════════════
; Disk stubs — all no-ops, return success
; ═══════════════════════════════════════════════════════════════

floppy_status:
floppy_read_status:
        rts

list_directory:
        rts

; disk_load_prg(name, addr) — A/X = addr arg; name at disk_ptr.
; Captures name into _load_name and sets _op_witness = 3 (PRG load).
; Returns end address from _load_result (0/0 = error).
disk_load_prg:
        pha
        lda #3
        sta _op_witness
        ; copy name (via disk_ptr) to _load_name
        ldy #0
@cp:    lda (disk_ptr),y
        sta _load_name,y
        beq @end
        iny
        cpy #16
        bcc @cp
        lda #0
        sta _load_name,y
@end:   pla
        lda _load_result
        ldx _load_result+1
        rts

; disk_save_prg(name, addr, size) — A/X = size; addr in _io_tmp;
; name at disk_ptr.
; Captures name into _save_name and sets _op_witness = 1 (PRG save).
; Returns 0 (success).
disk_save_prg:
        sta _save_size
        stx _save_size+1
        lda _io_tmp
        sta _save_addr
        lda _io_tmp+1
        sta _save_addr+1
        lda #1
        sta _op_witness
        ; copy name (via disk_ptr) to _save_name
        ldy #0
@cp:    lda (disk_ptr),y
        sta _save_name,y
        beq @end
        iny
        cpy #16
        bcc @cp
        lda #0
        sta _save_name,y
@end:   lda #0
        rts

; ═══════════════════════════════════════════════════════════════
; Editor stubs
; ═══════════════════════════════════════════════════════════════

; ed_save_source(name) — A/X = name ptr.  Captures into _save_name
; and sets _op_witness = 2 (SEQ save).  Returns 0 (success).
ed_save_source:
        sta rp_tmp
        stx rp_tmp+1
        lda #2
        sta _op_witness
        ldy #0
@cp:    lda (rp_tmp),y
        sta _save_name,y
        beq @end
        iny
        cpy #16
        bcc @cp
        lda #0
        sta _save_name,y
@end:   lda #0
        rts

; ed_load_source(name) — A/X = name ptr.  Captures into _load_name
; and sets _op_witness = 4 (SEQ load).  Returns 0 (success).
ed_load_source:
        sta rp_tmp
        stx rp_tmp+1
        lda #4
        sta _op_witness
        ldy #0
@cp:    lda (rp_tmp),y
        sta _load_name,y
        beq @end
        iny
        cpy #16
        bcc @cp
        lda #0
        sta _load_name,y
@end:   lda #0
        rts

ed_ensure_init:
        rts

ed_new:
        rts

; ed_read_rewind — no-op (no buffer in REPL test)
ed_read_rewind:
        rts

; ed_read_byte — return EOF ($FF/$FF)
ed_read_byte:
        lda #$FF
        tax
        rts

; (cse_start/cse_end/cse_zp_end now provided by mem.s)

; ═══════════════════════════════════════════════════════════════
; KERNAL PLOT stub (for io_sync)
; ═══════════════════════════════════════════════════════════════

dbg_nmi_break:
        rti

kplot_stub:
        bcs @get
        ; SET
        stx $D6                 ; cursor row
        sty $D3                 ; cursor column
        lda scr_lo,x
        sta $D1
        sta $F3
        lda scr_hi,x
        sta $D2
        clc
        adc #$D4
        sta $F4
        rts
@get:
        ldx $D6
        ldy $D3
        rts
