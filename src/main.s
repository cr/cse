; main.s — hardware init, NMI intercept, mode switch, main loop
;
; This is the entry point for CSE.  No C runtime — provides its own
; BASIC SYS stub, BSS zeroing, and parameter stack init.

        .setcpu "6502"

; ── Exports (consumed by other modules) ──────────────────────
        .export _state, _SCREEN, _src_top, _src_bot, _nmi_pending

; ── Runtime ZP (replaces cc65 zeropage.o) ────────────────────
        .exportzp sp, ptr1, ptr2, tmp1, tmp2

; ── Imports ──────────────────────────────────────────────────
        .import _io_init, _io_putc, _io_puts, _io_sync
        .import _io_puthex4, _io_puthex2
        .import _io_getc, _io_clear_eol
        .import _reset_screen, _restore_colors, _newline
        .import _cursor_show, _cursor_hide
        .import scr_lo, scr_hi
        .import _kernal_init
        .import _sym_set_heap, _sym_clear
        .import _define_ws_syms
        .import _dbg_init
        .import _nmi_handler
        .import _cse_end, _cse_zp_end
        .import _exec_line, _read_line, _show_prompt
        .import _cur_addr
        .import _ed_handle_key, _enter_editor, _leave_editor

        .import __BSS_RUN__, __BSS_SIZE__
        .import __HIMEM__, __STACKSIZE__

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

sp:     .res 2                  ; parameter stack pointer
ptr1:   .res 2                  ; scratch pointer (repl.s, debugger.s)
ptr2:   .res 2                  ; scratch pointer (repl.s)
tmp1:   .res 1                  ; scratch byte (repl.s)
tmp2:   .res 1                  ; scratch byte (repl.s)

; ── DATA (initialized globals) ───────────────────────────────
.segment "DATA"

_state:       .byte ST_REPL
_nmi_pending: .byte 0

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

_src_top:     .res 2
_src_bot:     .res 2

; ── RODATA ───────────────────────────────────────────────────
.segment "RODATA"

; SCREEN is a constant — export as a label, not a pointer variable
_SCREEN = SCREEN

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
        ; Zero BSS segment
        lda #<__BSS_RUN__
        sta ptr1
        lda #>__BSS_RUN__
        sta ptr1+1
        lda #<__BSS_SIZE__
        sta ptr2
        lda #>__BSS_SIZE__
        sta ptr2+1
        ; Size == 0? Skip
        ora ptr2
        beq @bss_done
        lda #0
        ldy #0
@bss_loop:
        sta (ptr1),y
        inc ptr1
        bne :+
        inc ptr1+1
:       ; Decrement size
        lda ptr2
        bne :+
        dec ptr2+1
:       dec ptr2
        lda ptr2
        ora ptr2+1
        bne @bss_loop
@bss_done:

        ; Init parameter stack pointer
        lda #<(__HIMEM__ - __STACKSIZE__)
        sta sp
        lda #>(__HIMEM__ - __STACKSIZE__)
        sta sp+1

        ; Fall through to main code (STARTUP placed before CODE in cfg)
        jmp _main

; ── CODE — main program ──────────────────────────────────────
.segment "CODE"

; ── fill_free_memory — fill free ZP and work area with $FF ───
.proc fill_free_memory
        ; Free ZP: cse_zp_end() to $7F
        jsr _cse_zp_end         ; A = first free ZP byte
        tax                     ; X = start
        lda #$FF
@zp:    sta $00,x
        inx
        cpx #$80
        bcc @zp

        ; Free work area: cse_end() to $C7FF
        jsr _cse_end            ; A/X = lo/hi
        sta ptr1
        stx ptr1+1
        lda #$FF
        ldy #0
@work:  sta (ptr1),y
        inc ptr1
        bne :+
        inc ptr1+1
:       ldx ptr1+1
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

        ; Init I/O (disables KERNAL cursor)
        jsr _io_init
        jsr _reset_screen

        ; Lowercase/uppercase charset
        lda VIC_MEMCTL
        ora #$02
        sta VIC_MEMCTL

        ; Install NMI trampoline under KERNAL
        jsr _kernal_init

        ; Init symbol table heap
        jsr _cse_end            ; A/X = heap start
        jsr _sym_set_heap
        jsr _sym_clear
        jsr _define_ws_syms

        ; Init debugger
        jsr _dbg_init

        ; Fill free memory with $FF
        jsr fill_free_memory

        ; Install NMI handler
        lda #<_nmi_handler
        sta NMI_VEC
        lda #>_nmi_handler
        sta NMI_VEC+1

        ; ── Splash screen ────────────────────────────────────
        ; cur_addr = (cse_end + $FF) & $FF00
        jsr _cse_end            ; A = lo, X = hi
        clc
        adc #$FF
        txa
        adc #0
        sta _cur_addr+1
        lda #0
        sta _cur_addr

        ; Version line (row 17)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 8
        sta CUR_ROW
        jsr _io_sync
        lda #<VERSION_STR
        ldx #>VERSION_STR
        jsr _io_puts

        ; Manual line (row 19)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 6
        sta CUR_ROW
        jsr _io_sync
        lda #<s_manual
        ldx #>s_manual
        jsr _io_puts

        ; Free ZP line (row 20)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 5
        sta CUR_ROW
        jsr _io_sync
        lda #<s_free_zp
        ldx #>s_free_zp
        jsr _io_puts
        jsr _cse_zp_end
        jsr _io_puthex2
        lda #<s_zp_end
        ldx #>s_zp_end
        jsr _io_puts

        ; Free work line (row 21)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 4
        sta CUR_ROW
        jsr _io_sync
        lda #<s_indent
        ldx #>s_indent
        jsr _io_puts
        jsr _cse_end            ; A/X = lo/hi of work start
        jsr _io_puthex4
        lda #'-'
        jsr _io_putc
        lda #<(BUF_END - 1)
        ldx #>(BUF_END - 1)
        jsr _io_puthex4
        lda #<s_work
        ldx #>s_work
        jsr _io_puts

        ; Prompt at bottom
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 1
        sta CUR_ROW
        jsr _io_sync
        jsr _io_clear_eol
        jsr _show_prompt

        ; ── Main loop ────────────────────────────────────────
@loop:
        lda _state
        bne :+
        jmp @exit               ; ST_STOP → exit
:

        jsr _cursor_show
        jsr _io_getc
        sta @key
        jsr _cursor_hide

        ; NMI check (priority over keypress)
        lda _nmi_pending
        beq @no_nmi
        lda #0
        sta _nmi_pending
        lda _state
        cmp #ST_EDIT
        bne @nmi_repl
        jsr _leave_editor
@nmi_repl:
        lda #ST_REPL
        sta _state
        jsr _restore_colors
        lda VIC_MEMCTL
        ora #$02
        sta VIC_MEMCTL
        jsr _newline
        lda #<s_nmi_msg
        ldx #>s_nmi_msg
        jsr _io_puts
        jsr _io_clear_eol
        jsr _newline
        jsr _io_clear_eol
        jsr _show_prompt
        jmp @loop

@no_nmi:
        ; RUN/STOP toggles REPL ↔ editor
        lda @key
        cmp #CH_STOP
        bne @not_stop
        lda _state
        cmp #ST_REPL
        bne @stop_edit
        jsr _enter_editor
        jmp @loop
@stop_edit:
        cmp #ST_EDIT
        bne @loop
        jsr _leave_editor
        jmp @loop
@not_stop:

        ; Editor mode → ed_handle_key
        lda _state
        cmp #ST_EDIT
        bne @repl_mode
        lda @key
        jsr _ed_handle_key
        jmp @loop

        ; ── REPL key dispatch ────────────────────────────────
@repl_mode:
        lda @key

        cmp #CH_ENTER
        bne @not_enter
        jsr _read_line
        lda #0
        sta CUR_COL
        jsr _exec_line
        jsr _show_prompt
        jmp @loop
@not_enter:

        cmp #CH_DEL
        bne @not_del
        ; Backspace: shift row left from cursor
        ldx CUR_ROW
        lda scr_lo,x
        sta ptr1
        lda scr_hi,x
        sta ptr1+1
        ; Check mincol: if row[4] == ':' ($3A screen), mincol=5
        ldy #4
        lda (ptr1),y
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
        lda (ptr1),y
        dey
        sta (ptr1),y
        iny
        cpy #SCREEN_WIDTH - 1
        bcc @del_loop
        lda #$20
        ldy #SCREEN_WIDTH - 1
        sta (ptr1),y
@del_done:
        jmp @loop
@not_del:

        cmp #CH_INS
        bne @not_ins
        ; Insert: shift row right from cursor
        ldx CUR_ROW
        lda scr_lo,x
        sta ptr1
        lda scr_hi,x
        sta ptr1+1
        ldy #SCREEN_WIDTH - 2
@ins_loop:
        cpy CUR_COL
        beq @ins_done_shift
        bcc @ins_done_shift
        lda (ptr1),y
        iny
        sta (ptr1),y
        dey
        dey
        jmp @ins_loop
@ins_done_shift:
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        bcs @ins_pad
        tay
        lda #$20
        sta (ptr1),y
@ins_pad:
        lda #$20
        ldy #SCREEN_WIDTH - 1
        sta (ptr1),y
        jmp @loop
@not_ins:

        cmp #CH_CURS_UP
        bne @not_up
        lda CUR_ROW
        beq @k_done
        dec CUR_ROW
        jsr _io_sync
@k_done:
        jmp @loop
@not_up:

        cmp #CH_CURS_DOWN
        bne @not_down
        lda CUR_ROW
        cmp #SCREEN_HEIGHT - 1
        bcs @k_done2
        inc CUR_ROW
        jsr _io_sync
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
        jsr _reset_screen
        jsr _io_clear_eol
        jsr _show_prompt
        jmp @loop

@default:
        ; Printable character
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        bcs @skip_print
        lda @key
        jsr _io_putc
@skip_print:
        jmp @loop

@exit:
        jmp $FCE2               ; KERNAL cold start

@key:   .byte 0
.endproc
