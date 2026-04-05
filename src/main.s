; main.s — hardware init, NMI intercept, mode switch, main loop
;
; This is the entry point for CSE.  No C runtime — provides its own
; BASIC SYS stub, BSS zeroing, and parameter stack init.

        .setcpu "6502"

; ── Exports ──────────────────────────────────────────────────
        .export state

; ── Runtime ZP ───────────────────────────────────────────────
        .exportzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2

; ── Imports ──────────────────────────────────────────────────
        .import io_init, io_putc, io_puts, io_sync
        .import io_puthex4, io_puthex2
        .import io_getc, io_clear_eol
        .import reset_screen, restore_colors, newline
        .import cursor_show, cursor_hide
        .import scr_lo, scr_hi
        .import kernal_init, kernal_bank_out, kernal_bank_in
        .import sym_set_heap, sym_clear
        .import define_ws_syms
        .import dbg_init
        .import nmi_handler
        .import cse_end, cse_zp_end
        .import exec_line, read_line, show_prompt
        .import cur_addr, cur_device, block_size
        .import nmi_pending
        .import ed_handle_key, enter_editor, leave_editor

        .import __BSS_RUN__, __BSS_SIZE__
        .import __KDATA_LOAD__, __KDATA_RUN__, __KDATA_SIZE__

; ── Constants ────────────────────────────────────────────────
SCREEN       = $0400
SCREEN_WIDTH = 40
SCREEN_HEIGHT = 25
MEM_CONFIG   = $01
NMI_VEC      = $0318          ; KERNAL NMI indirect vector
KEY_REPEAT   = $028A
VIC_MEMCTL   = $D018
BUF_END      = $C800

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

; ── Zero page (runtime) ─────────────────────────────────────
.segment "ZEROPAGE"

rp_ptr:   .res 2                  ; scratch pointer (repl.s, debugger.s)
rp_ptr2:   .res 2                  ; scratch pointer (repl.s)
rp_tmp:   .res 1                  ; scratch byte (repl.s)
rp_tmp2:   .res 1                  ; scratch byte (repl.s)

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

state:       .res 1              ; ST_STOP=0, ST_REPL=1, ST_EDIT=2

; ── RODATA ───────────────────────────────────────────────────
.segment "RODATA"

VERSION_STR:  .byte "cse v0.1 by cr", 0
s_manual:     .byte "manual:  github.com/cr/cse", 0
s_free_zp:    .byte "  free:  00", 0
s_zp_end:     .byte "-007f  zp", 0
s_indent:     .byte "         ", 0
s_work:       .byte "  work", 0
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

; ── STARTUP — BSS zeroing + stack init ───────────────────────
.segment "STARTUP"

startup:
        ; Zero BSS segment (page loop keeps A=0 throughout)
        lda #<__BSS_RUN__
        sta rp_ptr
        lda #>__BSS_RUN__
        sta rp_ptr+1
        lda #0
        ldy #0
        ; Full pages
        ldx #>__BSS_SIZE__
        beq @bss_partial
@bss_page:
        sta (rp_ptr),y
        iny
        bne @bss_page
        inc rp_ptr+1
        dex
        bne @bss_page
@bss_partial:
        ; Remaining bytes
        ldx #<__BSS_SIZE__
        beq @bss_done
@bss_rem:
        sta (rp_ptr),y
        iny
        dex
        bne @bss_rem
@bss_done:

        ; Copy KDATA tables from load address to KERNAL RAM ($E300+)
        ; Must bank out KERNAL to access the underlying RAM.
        jsr kernal_bank_out
        lda #<__KDATA_LOAD__
        sta rp_ptr
        lda #>__KDATA_LOAD__
        sta rp_ptr+1
        lda #<__KDATA_RUN__
        sta rp_ptr2
        lda #>__KDATA_RUN__
        sta rp_ptr2+1
        ldy #0
        ldx #>__KDATA_SIZE__
        beq @kd_partial
@kd_page:
        lda (rp_ptr),y
        sta (rp_ptr2),y
        iny
        bne @kd_page
        inc rp_ptr+1
        inc rp_ptr2+1
        dex
        bne @kd_page
@kd_partial:
        ldx #<__KDATA_SIZE__
        beq @kd_done
@kd_rem:
        lda (rp_ptr),y
        sta (rp_ptr2),y
        iny
        dex
        bne @kd_rem
@kd_done:
        jsr kernal_bank_in

        jmp _main

; ── CODE — main program ──────────────────────────────────────
.segment "CODE"

; ── fill_free_memory — fill free ZP and work area with $FF ───
.proc fill_free_memory
        ; Free ZP: cse_zp_end() to $7F
        jsr cse_zp_end         ; A = first free ZP byte
        tax                     ; X = start
        lda #$FF
@zp:    sta $00,x
        inx
        cpx #$80
        bcc @zp

        ; Free work area: cse_end() to $C7FF
        jsr cse_end            ; A/X = lo/hi
        sta rp_ptr
        stx rp_ptr+1
        lda #$FF
        ldy #0
@work:  sta (rp_ptr),y
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       ldx rp_ptr+1
        cpx #>BUF_END
        bcc @work
        rts
.endproc

; ── _main — entry point ──────────────────────────────────────
.proc _main
        ; All keys repeat
        lda KEY_REPEAT
        ora #$80
        sta KEY_REPEAT

        ; Unmap BASIC ROM
        lda MEM_CONFIG
        and #$DF
        sta MEM_CONFIG

        ; Init global state
        lda #ST_REPL
        sta state
        lda #8
        sta cur_device
        lda #$10
        sta block_size
        lda #0
        sta block_size+1

        ; Init I/O (disables KERNAL cursor)
        jsr io_init
        jsr reset_screen

        ; Lowercase/uppercase charset
        lda VIC_MEMCTL
        ora #$02
        sta VIC_MEMCTL

        ; Install NMI trampoline under KERNAL
        jsr kernal_init

        ; Init symbol table heap
        jsr cse_end            ; A/X = heap start
        jsr sym_set_heap
        jsr sym_clear
        jsr define_ws_syms

        ; Init debugger
        jsr dbg_init

        ; Fill free memory with $FF
        jsr fill_free_memory

        ; Install NMI handler
        lda #<nmi_handler
        sta NMI_VEC
        lda #>nmi_handler
        sta NMI_VEC+1

        ; ── Splash screen ────────────────────────────────────
        ; cur_addr = (cse_end + $FF) & $FF00
        jsr cse_end            ; A = lo, X = hi
        clc
        adc #$FF
        txa
        adc #0
        sta cur_addr+1
        lda #0
        sta cur_addr

        ; Version line (row 17)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 8
        sta CUR_ROW
        jsr io_sync
        lda #<VERSION_STR
        ldx #>VERSION_STR
        jsr io_puts

        ; Manual line (row 19)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 6
        sta CUR_ROW
        jsr io_sync
        lda #<s_manual
        ldx #>s_manual
        jsr io_puts

        ; Free ZP line (row 20)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 5
        sta CUR_ROW
        jsr io_sync
        lda #<s_free_zp
        ldx #>s_free_zp
        jsr io_puts
        jsr cse_zp_end
        jsr io_puthex2
        lda #<s_zp_end
        ldx #>s_zp_end
        jsr io_puts

        ; Free work line (row 21)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 4
        sta CUR_ROW
        jsr io_sync
        lda #<s_indent
        ldx #>s_indent
        jsr io_puts
        jsr cse_end            ; A/X = lo/hi of work start
        jsr io_puthex4
        lda #'-'
        jsr io_putc
        lda #<(BUF_END - 1)
        ldx #>(BUF_END - 1)
        jsr io_puthex4
        lda #<s_work
        ldx #>s_work
        jsr io_puts

        ; Prompt at bottom
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 1
        sta CUR_ROW
        jsr io_sync
        jsr io_clear_eol
        jsr show_prompt

        ; ── Main loop ────────────────────────────────────────
@loop:
        lda state
        bne :+
        jmp @exit               ; ST_STOP → exit
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
        lda VIC_MEMCTL
        ora #$02
        sta VIC_MEMCTL
        jsr newline
        lda #<s_nmi_msg
        ldx #>s_nmi_msg
        jsr io_puts
        jsr io_clear_eol
        jsr newline
        jsr io_clear_eol
        jsr show_prompt
        jmp @loop

@no_nmi:
        ; RUN/STOP toggles REPL ↔ editor
        lda @key
        cmp #CH_STOP
        bne @not_stop
        lda state
        cmp #ST_REPL
        bne @stop_edit
        jsr enter_editor
        jmp @loop
@stop_edit:
        cmp #ST_EDIT
        bne @loop
        jsr leave_editor
        jmp @loop
@not_stop:

        ; Editor mode → ed_handle_key
        lda state
        cmp #ST_EDIT
        bne @repl_mode
        lda @key
        jsr ed_handle_key
        jmp @loop

        ; ── REPL key dispatch ────────────────────────────────
@repl_mode:
        lda @key

        cmp #CH_ENTER
        bne @not_enter
        jsr read_line
        lda #0
        sta CUR_COL
        jsr exec_line
        jsr show_prompt
        jmp @loop
@not_enter:

        cmp #CH_DEL
        bne @not_del
        ; Backspace: shift row left from cursor
        ldx CUR_ROW
        lda scr_lo,x
        sta rp_ptr
        lda scr_hi,x
        sta rp_ptr+1
        ; Check mincol: if row[4] == ':' ($3A screen), mincol=5
        ldy #4
        lda (rp_ptr),y
        cmp #$3A                ; ':' screencode
        bne @del_min0
        lda CUR_COL
        cmp #6                  ; > 5?
        bcc @del_done           ; at or before prompt → no delete
        jmp @del_shift
@del_min0:
        lda CUR_COL
        beq @del_done           ; col 0 → nothing
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
@del_done:
        jmp @loop
@not_del:

        cmp #CH_INS
        bne @not_ins
        ; Insert: shift row right from cursor
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
        jmp @loop
@not_ins:

        cmp #CH_CURS_UP
        bne @not_up
        lda CUR_ROW
        beq @k_done
        dec CUR_ROW
        jsr io_sync
@k_done:
        jmp @loop
@not_up:

        cmp #CH_CURS_DOWN
        bne @not_down
        lda CUR_ROW
        cmp #SCREEN_HEIGHT - 1
        bcs @k_done2
        inc CUR_ROW
        jsr io_sync
@k_done2:
        jmp @loop
@not_down:

        cmp #CH_CURS_LEFT
        bne @not_left
        lda CUR_COL
        beq @k_done3
        dec CUR_COL
@k_done3:
        jmp @loop
@not_left:

        cmp #CH_CURS_RIGHT
        bne @not_right
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        bcs @k_done4
        inc CUR_COL
@k_done4:
        jmp @loop
@not_right:

        cmp #CH_HOME
        bne @not_home
        lda #0
        sta CUR_COL
        jmp @loop
@not_home:

        cmp #CH_CLR
        beq @do_clr
        cmp #CH_ESC
        bne @default
@do_clr:
        jsr reset_screen
        jsr io_clear_eol
        jsr show_prompt
        jmp @loop

@default:
        ; Printable character
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        bcs @skip_print
        lda @key
        jsr io_putc
@skip_print:
        jmp @loop

@exit:
        jmp $FCE2               ; KERNAL cold start

@key:   .byte 0
.endproc
