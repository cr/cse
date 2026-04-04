; repl_test_stub.s — test harness for repl.s
;
; Provides stubs for all repl.s imports not satisfied by linked modules
; (cse_io.s, expr.s, symtab.s, dasm.s, dasm_tables.s, asm pipeline).
;
; Protocol: Python writes command into line_buf (via exported label),
; sets cur_addr/cur_device, then JSRs to repl_test_entry.
;
; Test entry points:
;   repl_test_exec   — calls _exec_line
;   repl_test_read   — calls _read_line
;   repl_test_prompt — calls _show_prompt
;
; Captures:
;   Screen memory at $0400 (40×25) — written by real cse_io.s
;   newline_count — how many times _newline was called

        .setcpu "6502"

; ── Exports: test entry points ────────────────────────────────
        .export repl_test_exec
        .export repl_test_read
        .export repl_test_prompt

; ── Exports: satisfy repl.s imports from main.c ──────────────
        .export _hex_val, _is_hex, _hex_val_to_char

; ── Exports: screen module ────────────────────────────────────
        .export _newline, _restore_colors, _reset_screen
        .export _theme_border, _theme_bg, _theme_fg

; ── Exports: assembler / execution stubs ──────────────────────
        .export _asm_line
        .export _asm_assemble, _asm_org, _asm_size

; ── Exports: debugger stubs ───────────────────────────────────
        .export _dbg_enter, _dbg_step_clear
        .export _dbg_bp_set, _dbg_bp_del, _dbg_bp_clear
        .export _dbg_bp_count
        .export _bp_table, _step_bp
        .export _dbg_reason, _dbg_bp_hit
        .export _brk_pc
        .export _reg_a, _reg_x, _reg_y, _reg_sp, _reg_p

; ── Exports: disk stubs ───────────────────────────────────────
        .export _floppy_status, _list_directory
        .export _disk_load_prg, _disk_save_prg

; ── Exports: editor stubs ─────────────────────────────────────
        .export _ed_save_source, _ed_load_source
        .export _ed_save_bytes, _ed_save_lines
        .export _tab_width, _ed_ensure_init, _ed_new, _ed_dirty

; ── Exports: meminfo stubs ────────────────────────────────────
        .export _cse_start, _cse_end, _cse_zp_end
        .export _src_top, _src_bot

; ── Exports: global state ─────────────────────────────────────
        .export _state

; ── Exports: cc65 ZP / runtime ────────────────────────────────
        .exportzp sp, ptr1, ptr2, tmp1, tmp2

; ── Exports: NMI stubs (for cse_io.s) ─────────────────────────
        .export _dbg_running, _dbg_nmi_break
        .export kplot_stub

; ── Exports: test instrumentation ─────────────────────────────
        .export newline_count

; ── Import repl.s entry points ────────────────────────────────
        .import _exec_line, _read_line, _show_prompt
        .import _cur_addr, _cur_device, _cur_filename
        .import line_buf, last_cmd, block_size

; ── Import cse_io row tables (for KERNAL PLOT stub) ───────────
        .import scr_lo, scr_hi

; ── Force linker to resolve imports (make them visible in map) ──
.segment "RODATA"
sym_refs:
        .addr _exec_line, _read_line, _show_prompt
        .addr _cur_addr, _cur_device, _cur_filename
        .addr line_buf, last_cmd, block_size
        .addr newline_count, kplot_stub

; ═══════════════════════════════════════════════════════════════
; ZEROPAGE
; ═══════════════════════════════════════════════════════════════
.segment "ZEROPAGE"

sp:     .res 2          ; cc65 C stack pointer
ptr1:   .res 2          ; scratch pointers
ptr2:   .res 2
tmp1:   .res 1          ; scratch bytes
tmp2:   .res 1

; ═══════════════════════════════════════════════════════════════
; BSS — test state + stubs
; ═══════════════════════════════════════════════════════════════
.segment "BSS"

; Debugger state
_bp_table:      .res 32         ; 8 × 4
_step_bp:       .res 8          ; 2 × 4
_dbg_running:   .res 1
_dbg_reason:    .res 1
_brk_pc:        .res 2
_dbg_bp_hit:    .res 1

; Registers
_reg_a:         .res 1
_reg_x:         .res 1
_reg_y:         .res 1
_reg_sp:        .res 1
_reg_p:         .res 1

; Editor state
_ed_save_bytes: .res 2
_ed_save_lines: .res 2
_tab_width:     .res 1
_ed_dirty:      .res 1

; Assembler state
_asm_org:       .res 2
_asm_size:      .res 2

; Theme
_theme_border:  .res 1
_theme_bg:      .res 1
_theme_fg:      .res 1

; Meminfo
_src_top:       .res 2
_src_bot:       .res 2

; Global
_state:         .res 1

; Test instrumentation
newline_count:  .res 1          ; count _newline calls

; C stack area — pushax/popax use sp ZP
c_stack:        .res 256

; ═══════════════════════════════════════════════════════════════
; CODE
; ═══════════════════════════════════════════════════════════════
.segment "CODE"

; ── Test entry points ─────────────────────────────────────────

repl_test_exec:
        lda #0
        sta newline_count
        jmp _exec_line

repl_test_read:
        jmp _read_line

repl_test_prompt:
        jmp _show_prompt

; ═══════════════════════════════════════════════════════════════
; hex_val / is_hex / hex_val_to_char — pure asm replacements
; These replace the C versions in main.c. __fastcall__: arg in A.
; ═══════════════════════════════════════════════════════════════

; hex_val(ch): A → digit value (0-15) or $FF
.proc _hex_val
        cmp #'0'
        bcc @bad
        cmp #'9'+1
        bcc @digit
        cmp #'a'
        bcc @upper
        cmp #'f'+1
        bcc @lower
        ; fall through to @upper check
@upper: cmp #'A'
        bcc @bad
        cmp #'F'+1
        bcs @bad
        sec
        sbc #'A'-10
        rts
@digit: sec
        sbc #'0'
        rts
@lower: sec
        sbc #'a'-10
        rts
@bad:   lda #$FF
        rts
.endproc

; is_hex(ch): A → 1 if hex, 0 if not
.proc _is_hex
        jsr _hex_val
        cmp #$FF
        beq @no
        lda #1
        rts
@no:    lda #0
        rts
.endproc

; hex_val_to_char(v): A (0-15) → ASCII char
.proc _hex_val_to_char
        cmp #10
        bcs @alpha
        clc
        adc #'0'
        rts
@alpha: clc
        adc #'a'-10
        rts
.endproc

; ═══════════════════════════════════════════════════════════════
; Screen stubs
; ═══════════════════════════════════════════════════════════════

COLS = 40

; _newline — advance cursor row, track count
.proc _newline
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

; _restore_colors — no-op in tests
_restore_colors:
        rts

; _reset_screen — clear screen + reset cursor
.proc _reset_screen
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

; _asm_line(addr, buf) — __fastcall__, 2 args via C stack
; Returns 0 (error) always in stub mode.
; Real tests should link the full asm pipeline instead.
_asm_line:
        lda #0
        tax
        rts

; _asm_assemble — stub: sets asm_org=$1000, asm_size=0, returns 0 errors
.proc _asm_assemble
        lda #0
        sta _asm_size
        sta _asm_size+1
        tax
        rts
.endproc

; ═══════════════════════════════════════════════════════════════
; Debugger stubs
; ═══════════════════════════════════════════════════════════════

_dbg_enter:
        rts

_dbg_step_clear:
        ldx #7
        lda #0
@clr:   sta _step_bp,x
        dex
        bpl @clr
        rts

; _dbg_bp_set(addr) — __fastcall__: A/X = addr
; Returns slot in A, C=0 ok, C=1 full
.proc _dbg_bp_set
        sta _brk_pc             ; reuse as scratch
        stx _brk_pc+1
        ; find first empty slot
        ldx #0
@scan:  lda _bp_table,x
        ora _bp_table+1,x
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
@found: lda _brk_pc
        sta _bp_table,x
        lda _brk_pc+1
        sta _bp_table+1,x
        lda #1
        sta _bp_table+3,x       ; enabled
        txa
        lsr
        lsr                     ; slot = x/4
        clc
        rts
.endproc

; _dbg_bp_del(slot) — __fastcall__: A = slot
_dbg_bp_del:
        asl
        asl
        tax
        lda #0
        sta _bp_table,x
        sta _bp_table+1,x
        sta _bp_table+2,x
        sta _bp_table+3,x
        rts

; _dbg_bp_clear
.proc _dbg_bp_clear
        ldx #31
        lda #0
@clr:   sta _bp_table,x
        dex
        bpl @clr
        rts
.endproc

; _dbg_bp_count — returns count in A
.proc _dbg_bp_count
        ldx #0
        lda #0
        stx tmp1                ; count
@lp:    lda _bp_table,x
        ora _bp_table+1,x
        beq @next
        inc tmp1
@next:  txa
        clc
        adc #4
        tax
        cpx #32
        bcc @lp
        lda tmp1
        rts
.endproc

; ═══════════════════════════════════════════════════════════════
; Disk stubs — all no-ops, return success
; ═══════════════════════════════════════════════════════════════

_floppy_status:
        rts

_list_directory:
        rts

; disk_load_prg(name, addr) — returns loaded size in A/X (0 = error)
_disk_load_prg:
        lda #0
        tax
        rts

; disk_save_prg(name, addr, size) — returns 0 (ok)
_disk_save_prg:
        lda #0
        rts

; ═══════════════════════════════════════════════════════════════
; Editor stubs
; ═══════════════════════════════════════════════════════════════

_ed_save_source:
        lda #0
        rts

_ed_load_source:
        lda #0
        rts

_ed_ensure_init:
        rts

_ed_new:
        rts

; ═══════════════════════════════════════════════════════════════
; Meminfo stubs — return fixed addresses
; ═══════════════════════════════════════════════════════════════

; cse_start() → $0800
.proc _cse_start
        lda #$00
        ldx #$08
        rts
.endproc

; cse_end() → $4000
.proc _cse_end
        lda #$00
        ldx #$40
        rts
.endproc

; cse_zp_end() → $20
.proc _cse_zp_end
        lda #$20
        rts
.endproc

; ═══════════════════════════════════════════════════════════════
; KERNAL PLOT stub (for io_sync)
; ═══════════════════════════════════════════════════════════════

_dbg_nmi_break:
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
