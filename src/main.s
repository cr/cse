; main.s — CSE application shell: cold init, warm start, main loop
;
; Three-layer architecture:
;   cse_cold_init   — one-time setup (jumped to by loader.s)
;   cse_warm_start  — idempotent recovery (hard fault, BASIC hook)
;   cse_warm_screen — screen recovery tail (ESC/CLR, NMI-in-REPL)
;   main_loop       — event loop
;
; Interrupt handlers (permanent, never swapped):
;   cse_brk_handler  — $0316/$0317: BRK dispatch on dbg_running
;   cse_nmi_handler  — $0318/$0319: NMI dispatch on dbg_running
;   cse_basic_warm_hook — $0302/$0303: BASIC warm-start intercept
;
; Exit: cse_exit_to_basic restores vectors, ZP, $01, jumps to BASIC.
;
; See doc/modules/main.md for full design.

        .setcpu "6502"
        .macpack longbranch
        .include "macros.inc"

; ── Exports ──────────────────────────────────────────────────
        .export _main
        .export state
        .export cse_warm_start, cse_warm_screen

; ── Runtime ZP ───────────────────────────────────────────────
        .importzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2

; ── Imports ──────────────────────────────────────────────────
        .import puts_imm
        .import io_init, io_putc, io_puts, io_sync, io_blip
        .import io_puthex4, io_puthex2, io_putdec
        .import io_getc, io_clear_eol
        .import reset_screen, restore_colors, newline, theme_init
        .import cursor_show, cursor_hide
        .import scr_lo, scr_hi
        .import kernal_init, define_ws_syms
        .import cse_end, cse_zp_end, cse_start
        .import sym_clear
        .import dbg_init
        .import dbg_brk_core, dbg_nmi_break
        .import dbg_running
        .import ed_ensure_init
        .import exec_line, read_line, show_prompt
        .importzp asm_cpu
        .import cur_addr, cur_device, block_size
        .import nmi_pending
        .import ed_handle_key, enter_editor, leave_editor


; ── Constants ────────────────────────────────────────────────
SCREEN       = $0400
SCREEN_WIDTH = 40
SCREEN_HEIGHT = 25
MEM_CONFIG   = $01
KEY_REPEAT   = $028A
VIC_MEMCTL   = $D018

; KERNAL page-3 vectors
VEC_IMAIN    = $0302          ; BASIC warm-start / main loop
VEC_IBRK     = $0316          ; BRK dispatch
VEC_INMIV    = $0318          ; NMI dispatch

; Run states
ST_STOP      = 0
ST_REPL      = 1
ST_EDIT      = 2

; Key codes
CH_ENTER     = 13
CH_STOP      = 3
CH_DEL       = 20
CH_INS       = 148
CH_CURS_UP   = 145
CH_CURS_DOWN = 17
CH_CURS_LEFT = 157
CH_CURS_RIGHT = 29
CH_HOME      = 19
CH_CLR       = 147
CH_ESC       = $1B

; KERNAL ZP
CUR_COL      = $D3
CUR_ROW      = $D6

; Cold-init snapshot locations (KBSS, under KERNAL ROM).
; Pure writes pass through to RAM regardless of $01 bit 1.
COLD_ZP      = $F8DA          ; 127 bytes: snapshot of $01-$7F
COLD_VEC     = $F959          ; 6 bytes: $0302-$0303, $0316-$0317, $0318-$0319

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

state:       .res 1              ; ST_STOP=0, ST_REPL=1, ST_EDIT=2

; ── RODATA ───────────────────────────────────────────────────
.segment "RODATA"

VERSION_STR:  .byte "cse v0.1 by cr", 0
s_manual:     .byte "manual: github.com/cr/cse", 0
s_zp_tag:     .byte "  zp ", 0
s_lo02_tag:   .byte "lo02 ", 0
s_lo03_tag:   .byte "lo03 ", 0
s_work_tag:   .byte "work ", 0
s_dash:       .byte "-", 0
s_free:       .byte "b free", 0
s_nmi_msg:    .byte "; run/stop+restore", 0

; ── PRG load address ─────────────────────────────────────────
.segment "LOADADDR"

        .word $0801             ; PRG file load address

; ── EXEHDR — BASIC stub "SYS 2061" ──────────────────────────
.segment "EXEHDR"

        .word @next             ; pointer to next BASIC line
        .word 2026              ; line number
        .byte $9E               ; SYS token
        .byte "2061", 0         ; SYS address (decimal, $080D)
@next:  .word 0                 ; end of BASIC program

; ── CODE — main program ──────────────────────────────────────
.segment "CODE"

; ═════════════════════════════════════════════════════════════
; Layer 1: cse_cold_init — one-time setup
; Entry: jumped to by loader.s after relocation + BSS zero.
; ═════════════════════════════════════════════════════════════
.proc _main                     ; entry point label for loader.s

        ; ── 1. All keys repeat ──
        lda KEY_REPEAT
        ora #$80
        sta KEY_REPEAT

        ; ── 2. Save $01-$7F to KBSS cold snapshot ──
        ; Pure write: stores under KERNAL pass through to RAM.
        ldx #0
@save_zp:
        lda $01,x
        sta COLD_ZP,x
        inx
        cpx #$7F               ; $01..$7F = 127 bytes
        bne @save_zp

        ; ── 3. Unmap BASIC ROM ($37 → $36: RAM at $A000–$BFFF) ──
        lda MEM_CONFIG
        and #$FE
        sta MEM_CONFIG

        ; ── 4. Install NMI trampoline under KERNAL ──
        jsr kernal_init

        ; ── 5. Init editor buffer (sets buf_base for workend) ──
        jsr ed_ensure_init

        ; ── 6. Init symbol table ──
        jsr sym_clear
        jsr define_ws_syms

        ; ── 7. Init CPU mode for assembler/disassembler ──
.ifndef DEFAULT_CPU
  DEFAULT_CPU = 1               ; fallback: 6510
.endif
        lda #DEFAULT_CPU
        sta asm_cpu

        ; ── 8. Init debugger ──
        jsr dbg_init

        ; ── 9. Fill free ZP with $FF ──
        jsr cse_zp_end         ; A = first free ZP byte
        tax
        lda #$FF
@zp:    sta $00,x
        inx
        cpx #$80
        bcc @zp

        ; ── 10. Fill free work area ($0800 to cse_start-1) with $FF ──
        lda #<$0800
        sta rp_ptr
        lda #>$0800
        sta rp_ptr+1
        jsr cse_start          ; A/X = runtime start hi in X
        lda #$FF
        ldy #0
@work:  sta (rp_ptr),y
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       cpx rp_ptr+1            ; done when hi byte reaches cse_start hi
        bne @work

        ; ── 11. Save original vectors to KBSS ──
        ; Pure write: stores under KERNAL pass through.
        lda VEC_IMAIN
        sta COLD_VEC
        lda VEC_IMAIN+1
        sta COLD_VEC+1
        lda VEC_IBRK
        sta COLD_VEC+2
        lda VEC_IBRK+1
        sta COLD_VEC+3
        lda VEC_INMIV
        sta COLD_VEC+4
        lda VEC_INMIV+1
        sta COLD_VEC+5

        ; ── 12. Install permanent hooks ──
        jsr install_hooks

        ; ── 13. I/O and screen for splash ──
        jsr io_init
        jsr theme_init
        jsr reset_screen
        jsr set_charset

        ; ── 14. Init global state ──
        jsr reset_globals

        ; ── 15. Splash screen ────────────────────────────────
        ; Version line (row 16)
        lda #SCREEN_HEIGHT - 9
        jsr splash_row
        puts VERSION_STR

        ; ZP free line (row 18): "  zp 0002-007f      126b free"
        lda #SCREEN_HEIGHT - 7
        jsr splash_row
        puts s_zp_tag
        lda #<$0002
        ldx #>$0002
        jsr io_puthex4
        puts s_dash
        lda #<$007F
        ldx #>$007F
        jsr io_puthex4
        lda #' '
        jsr io_putc
        jsr io_putc
        jsr io_putc
        jsr io_putc
        lda #<($7F - $02 + 1)
        ldx #>($7F - $02 + 1)
        jsr io_putdec
        puts s_free

        ; lo02 free line (row 19): "lo02 02a7-02ff       89b free"
        lda #SCREEN_HEIGHT - 6
        jsr splash_row
        puts s_lo02_tag
        lda #<$02A7
        ldx #>$02A7
        jsr io_puthex4
        puts s_dash
        lda #<$02FF
        ldx #>$02FF
        jsr io_puthex4
        lda #' '
        jsr io_putc
        jsr io_putc
        jsr io_putc
        jsr io_putc
        jsr io_putc
        lda #<($02FF - $02A7 + 1)
        ldx #>($02FF - $02A7 + 1)
        jsr io_putdec
        puts s_free

        ; lo03 free line (row 20): "lo03 0334-03ff      204b free"
        lda #SCREEN_HEIGHT - 5
        jsr splash_row
        puts s_lo03_tag
        lda #<$0334
        ldx #>$0334
        jsr io_puthex4
        puts s_dash
        lda #<$03FF
        ldx #>$03FF
        jsr io_puthex4
        lda #' '
        jsr io_putc
        jsr io_putc
        jsr io_putc
        jsr io_putc
        lda #<($03FF - $0334 + 1)
        ldx #>($03FF - $0334 + 1)
        jsr io_putdec
        puts s_free

        ; work free line (row 21): "work 0800-XXXX  NNNNNb free"
        lda #SCREEN_HEIGHT - 4
        jsr splash_row
        puts s_work_tag
        lda #<$0800
        ldx #>$0800
        jsr io_puthex4
        puts s_dash
        jsr cse_start          ; A/X = runtime start
        sec
        sbc #1
        pha                     ; save lo of cse_start-1
        txa
        sbc #0
        tax                     ; X = hi of cse_start-1
        pla                     ; A = lo of cse_start-1
        jsr io_puthex4
        lda #' '
        jsr io_putc
        jsr io_putc
        ; byte count = cse_start - $0800
        jsr cse_start
        sec
        sbc #<$0800
        pha
        txa
        sbc #>$0800
        tax
        pla
        jsr io_putdec
        puts s_free

        ; Manual line (row 23)
        lda #SCREEN_HEIGHT - 2
        jsr splash_row
        puts s_manual

        ; Prompt at bottom
        lda #SCREEN_HEIGHT - 1
        jsr splash_row
        jsr io_clear_eol
        jsr show_prompt

        ; Skip cse_warm_start/cse_warm_screen — splash is on screen
        jmp main_loop
.endproc

; ═════════════════════════════════════════════════════════════
; Layer 3: main_loop — event loop
; ═════════════════════════════════════════════════════════════
main_loop:
        lda state
        bne :+
        jmp cse_exit_to_basic
:
        jsr cursor_show
        jsr io_getc
        sta @key
        jsr cursor_hide

        ; NMI check (priority over keypress)
        lda nmi_pending
        beq @no_nmi
        lda #0
        sta nmi_pending
        lda state
        cmp #ST_EDIT
        bne @nmi_repl
        jsr leave_editor
@nmi_repl:
        lda #ST_REPL
        sta state
        jsr restore_colors
        jsr set_charset
        jsr newline
        puts s_nmi_msg
        jsr io_clear_eol
        jsr newline
        jsr io_clear_eol
        jsr show_prompt
        jmp main_loop

@no_nmi:
        lda @key
        cmp #CH_STOP
        bne @not_stop
        lda state
        cmp #ST_REPL
        bne @stop_edit
        jsr enter_editor
        jmp @stop_debounce
@stop_edit:
        cmp #ST_EDIT
        bne main_loop
        jsr leave_editor
@stop_debounce:
@deb_wait:
        lda $91
        cmp #$7F
        beq @deb_wait
@deb_drain:
        lda $C6
        beq main_loop
        jsr io_getc
        jmp @deb_drain
@not_stop:

        lda state
        cmp #ST_EDIT
        bne @repl_mode
        lda @key
        jsr ed_handle_key
        jmp main_loop

@repl_mode:
        lda @key

        cmp #CH_ENTER
        bne @not_enter
        jsr read_line
        lda #0
        sta CUR_COL
        jsr exec_line
        jsr show_prompt
        jmp main_loop
@not_enter:

        cmp #CH_DEL
        bne @not_del
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_ptr
        lda scr_hi,x
        sta rp_ptr+1
        ldy #4
        lda (rp_ptr),y
        cmp #$3A
        bne @del_min0
        lda CUR_COL
        cmp #6
        jcc @reject
        jmp @del_shift
@del_min0:
        lda CUR_COL
        jeq @reject
@del_shift:
        dec CUR_COL
        ldy CUR_COL
@del_loop:
        iny
        lda (rp_ptr),y
        dey
        sta (rp_ptr),y
        iny
        cpy #SCREEN_WIDTH - 1
        bcc @del_loop
        lda #$20
        ldy #SCREEN_WIDTH - 1
        sta (rp_ptr),y
        jmp main_loop
@not_del:

        cmp #CH_INS
        bne @not_ins
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_ptr
        lda scr_hi,x
        sta rp_ptr+1
        ldy #SCREEN_WIDTH - 2
@ins_loop:
        cpy CUR_COL
        beq @ins_done_shift
        bcc @ins_done_shift
        lda (rp_ptr),y
        iny
        sta (rp_ptr),y
        dey
        dey
        jmp @ins_loop
@ins_done_shift:
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        bcs @ins_pad
        tay
        lda #$20
        sta (rp_ptr),y
@ins_pad:
        lda #$20
        ldy #SCREEN_WIDTH - 1
        sta (rp_ptr),y
        jmp main_loop
@not_ins:

        cmp #CH_CURS_UP
        bne @not_up
        lda CUR_ROW
        jeq @reject
        dec CUR_ROW
        jsr io_sync
        jmp main_loop
@not_up:

        cmp #CH_CURS_DOWN
        bne @not_down
        lda CUR_ROW
        cmp #SCREEN_HEIGHT - 1
        jcs @reject
        inc CUR_ROW
        jsr io_sync
        jmp main_loop
@not_down:

        cmp #CH_CURS_LEFT
        bne @not_left
        lda CUR_COL
        jeq @reject
        dec CUR_COL
        jmp main_loop
@not_left:

        cmp #CH_CURS_RIGHT
        bne @not_right
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        jcs @reject
        inc CUR_COL
        jmp main_loop
@not_right:

        cmp #CH_HOME
        bne @not_home
        lda #0
        sta CUR_COL
        jmp main_loop
@not_home:

        cmp #CH_CLR
        beq @do_clr
        cmp #CH_ESC
        bne @default
@do_clr:
        jmp cse_warm_screen
@default:
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        jcs @reject
        lda @key
        jsr io_putc
        jmp main_loop

@reject:
        jsr io_blip
        jmp main_loop

@key:   .byte 0

; ═════════════════════════════════════════════════════════════
; install_hooks — write all three permanent vectors
; ═════════════════════════════════════════════════════════════
install_hooks:
        lda #<cse_basic_warm_hook
        sta VEC_IMAIN
        lda #>cse_basic_warm_hook
        sta VEC_IMAIN+1
        lda #<cse_brk_handler
        sta VEC_IBRK
        lda #>cse_brk_handler
        sta VEC_IBRK+1
        lda #<cse_nmi_handler
        sta VEC_INMIV
        lda #>cse_nmi_handler
        sta VEC_INMIV+1
        rts

; ── reset_globals — init state, device, block size, cur_addr ──
; Shared by cse_cold_init and cse_warm_start.
; Clobbers: A
reset_globals:
        lda #ST_REPL
        sta state
        lda #8
        sta cur_device
        lda #$10
        sta block_size
        lda #0
        sta block_size+1
        sta cur_addr
        lda #$08
        sta cur_addr+1
        rts

; ── set_charset — lowercase/uppercase VIC charset ──
; Clobbers: A
set_charset:
        lda VIC_MEMCTL
        ora #$02
        sta VIC_MEMCTL
        rts

; ── splash_row — position cursor at col 0, row A, sync ──
; In: A = row number.  Clobbers: A.
splash_row:
        sta CUR_ROW
        lda #0
        sta CUR_COL
        jmp io_sync             ; tail call

; ═════════════════════════════════════════════════════════════
; cse_brk_handler — permanent BRK dispatcher ($0316)
; ═════════════════════════════════════════════════════════════
cse_brk_handler:
        lda dbg_running
        bne @user
        jmp cse_warm_start
@user:  jmp dbg_brk_core

; ═════════════════════════════════════════════════════════════
; cse_nmi_handler — permanent NMI dispatcher ($0318)
; ═════════════════════════════════════════════════════════════
cse_nmi_handler:
        bit dbg_running
        bmi @break_user
        pha
        lda #1
        sta nmi_pending
        pla
        rti
@break_user:
        jmp dbg_nmi_break

; ═════════════════════════════════════════════════════════════
; cse_basic_warm_hook — BASIC warm-start intercept ($0302)
; Falls through to cse_warm_start.
; ═════════════════════════════════════════════════════════════
cse_basic_warm_hook:
        ; fall through

; ═════════════════════════════════════════════════════════════
; Layer 2: cse_warm_start — idempotent recovery
; ═════════════════════════════════════════════════════════════
cse_warm_start:
        ldx #$FF
        txs
        lda #$36
        sta MEM_CONFIG
        jsr install_hooks
        jsr dbg_init
        jsr reset_globals
        jsr io_init
        jsr theme_init
        jsr restore_colors
        jsr set_charset
        ; Fall through to cse_warm_screen

; ═════════════════════════════════════════════════════════════
; cse_warm_screen — screen recovery tail
; ═════════════════════════════════════════════════════════════
cse_warm_screen:
        jsr reset_screen
        jsr io_clear_eol
        jsr show_prompt
        ; Fall through to main_loop

; ═════════════════════════════════════════════════════════════
; cse_exit_to_basic — clean exit to BASIC warm start
; ═════════════════════════════════════════════════════════════
cse_exit_to_basic:
        sei
        ; Bank out KERNAL to read KBSS snapshots
        lda MEM_CONFIG
        and #$FD
        sta MEM_CONFIG
        ; Restore vectors
        lda COLD_VEC
        sta VEC_IMAIN
        lda COLD_VEC+1
        sta VEC_IMAIN+1
        lda COLD_VEC+2
        sta VEC_IBRK
        lda COLD_VEC+3
        sta VEC_IBRK+1
        lda COLD_VEC+4
        sta VEC_INMIV
        lda COLD_VEC+5
        sta VEC_INMIV+1
        ; Restore $02-$7F (skip $01 — it controls banking)
        ldx #1                  ; offset 1 = $02
@rzp:   lda COLD_ZP,x
        sta $01,x
        inx
        cpx #$7F
        bne @rzp
        ; Restore $01 last (re-banks KERNAL + BASIC)
        lda COLD_ZP
        sta MEM_CONFIG
        cli
        jmp (VEC_IMAIN)
