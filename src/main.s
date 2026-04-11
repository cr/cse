; main.s — hardware init, NMI intercept, mode switch, main loop
;
; Jumped to by loader.s after relocation and BSS zeroing.
; Provides the BASIC SYS stub (EXEHDR) and the main event loop.

        .setcpu "6502"
        .macpack longbranch
        .include "macros.inc"

; ── Exports ──────────────────────────────────────────────────
        .export _main
        .export state

; ── Runtime ZP ───────────────────────────────────────────────
        .exportzp rp_ptr, rp_ptr2, rp_tmp, rp_tmp2

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
        .import nmi_handler
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
NMI_VEC      = $0318          ; KERNAL NMI indirect vector
KEY_REPEAT   = $028A
VIC_MEMCTL   = $D018

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
s_manual:     .byte "manual: github.com/cr/cse", 0
s_zp_tag:     .byte "  zp ", 0
s_sys_tag:    .byte " sys ", 0
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
; Entry: jumped to by loader.s after relocation + BSS zero.
.segment "CODE"

; ── _main — entry point ──────────────────────────────────────
.proc _main
        ; All keys repeat
        lda KEY_REPEAT
        ora #$80
        sta KEY_REPEAT

        ; ── Memory / subsystem init (mem.s functions) ────────
        ; Unmap BASIC ROM ($37 → $36: RAM at $A000–$BFFF)
        lda MEM_CONFIG
        and #$FE
        sta MEM_CONFIG

        ; Install NMI trampoline under KERNAL
        jsr kernal_init

        ; Init editor buffer (sets buf_base for workend)
        jsr ed_ensure_init

        ; Init symbol table
        jsr sym_clear
        jsr define_ws_syms

        ; Init CPU mode for assembler/disassembler
.ifndef DEFAULT_CPU
  DEFAULT_CPU = 1               ; fallback: 6510
.endif
        lda #DEFAULT_CPU
        sta asm_cpu

        ; Init debugger
        jsr dbg_init

        ; Fill free ZP with $FF
        jsr cse_zp_end         ; A = first free ZP byte
        tax
        lda #$FF
@zp:    sta $00,x
        inx
        cpx #$80
        bcc @zp

        ; Fill free work area ($0800 to cse_start-1) with $FF
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

        ; Install NMI handler vector
        lda #<nmi_handler
        sta NMI_VEC
        lda #>nmi_handler
        sta NMI_VEC+1

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
        ; Apply build-time theme defaults to BSS before the first
        ; reset_screen call (which reads them via restore_colors).
        jsr theme_init
        jsr reset_screen

        ; Lowercase/uppercase charset
        lda VIC_MEMCTL
        ora #$02
        sta VIC_MEMCTL

        ; ── Splash screen ────────────────────────────────────
        ; cur_addr = $0800 (workstart)
        lda #$00
        sta cur_addr
        lda #$08
        sta cur_addr+1

        ; Version line (row 16)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 9
        sta CUR_ROW
        jsr io_sync
        puts VERSION_STR

        ; ZP free line (row 18): "  zp 0002-007f      126 free"
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 7
        sta CUR_ROW
        jsr io_sync
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

        ; sys free line (row 19): " sys 0200-03ff      512 free"
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 6
        sta CUR_ROW
        jsr io_sync
        puts s_sys_tag
        lda #<$0200
        ldx #>$0200
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
        lda #<($03FF - $0200 + 1)
        ldx #>($03FF - $0200 + 1)
        jsr io_putdec
        puts s_free

        ; work free line (row 20): "work 0800-XXXX  NNNNN free"
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 5
        sta CUR_ROW
        jsr io_sync
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

        ; Manual line (row 22)
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 3
        sta CUR_ROW
        jsr io_sync
        puts s_manual

        ; Prompt at bottom
        lda #0
        sta CUR_COL
        lda #SCREEN_HEIGHT - 1
        sta CUR_ROW
        jsr io_sync
        jsr io_clear_eol
        jsr show_prompt

        ; ── Main loop ────────────────────────────────────────
@reject:
        ; Audible feedback for refused REPL keys: cursor moves off
        ; the screen, backspace before the AAAA: prompt, printable
        ; at col 39, etc.  Falls through to @loop.
        jsr io_blip
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
        puts s_nmi_msg
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
        jmp @stop_debounce
@stop_edit:
        cmp #ST_EDIT
        bne @loop
        jsr leave_editor
@stop_debounce:
        ; Debounce: CSE enables key-repeat for all keys at startup
        ; (KEY_REPEAT |= $80), so holding RUN/STOP would otherwise
        ; queue several CH_STOPs and toggle the mode multiple times.
        ; Wait for the physical key release ($91 = $7F means STOP
        ; is currently held), then drain any repeats the KERNAL
        ; queued into the kbd buffer ($C6).
@deb_wait:
        lda $91
        cmp #$7F
        beq @deb_wait
@deb_drain:
        lda $C6                 ; kbd buffer count
        beq @loop               ; nothing queued → done
        jsr io_getc             ; consume one
        jmp @deb_drain
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
        jcc @reject             ; at or before prompt → reject
        jmp @del_shift
@del_min0:
        lda CUR_COL
        jeq @reject             ; col 0 → reject
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
        jeq @reject             ; row 0 → top of screen
        dec CUR_ROW
        jsr io_sync
        jmp @loop
@not_up:

        cmp #CH_CURS_DOWN
        bne @not_down
        lda CUR_ROW
        cmp #SCREEN_HEIGHT - 1
        jcs @reject             ; last row → bottom of screen
        inc CUR_ROW
        jsr io_sync
        jmp @loop
@not_down:

        cmp #CH_CURS_LEFT
        bne @not_left
        lda CUR_COL
        jeq @reject             ; col 0 → left wall
        dec CUR_COL
        jmp @loop
@not_left:

        cmp #CH_CURS_RIGHT
        bne @not_right
        lda CUR_COL
        cmp #SCREEN_WIDTH - 1
        jcs @reject             ; col 39 → right wall
        inc CUR_COL
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
        jcs @reject             ; at col 39 → right wall
        lda @key
        jsr io_putc
        jmp @loop

@exit:
        jmp $FCE2               ; KERNAL cold start

@key:   .byte 0
.endproc
