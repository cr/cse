; main.s — CSE application shell: cold init, warm start, main loop
;
; Three-layer architecture:
;   cse_cold_init   — one-time setup (jumped to by loader.s)
;   cse_warm_start  — idempotent recovery (internal BRK fault)
;   cse_warm_screen — screen recovery tail (ESC/CLR, NMI-in-REPL)
;   main_loop       — event loop
;
; Interrupt handlers (permanent, never swapped):
;   cse_brk_handler  — $0316/$0317: BRK dispatch on dbg_running
;   cse_nmi_handler  — $0318/$0319: NMI dispatch on dbg_running
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
        .import io_init, io_putc, io_sync, io_blip
        .import io_getc, io_clear_eol
        .import reset_screen, restore_colors, newline, theme_init
        .import cursor_show, cursor_hide
        .import scr_lo, scr_hi
        .import kernal_init, define_ws_syms
        .import cse_zp_end, cse_start
        .import sym_clear
        .import dbg_init
        .import dbg_brk_core, dbg_nmi_break
        .import dbg_running
        .import ed_ensure_init
        .import exec_line, read_line, show_prompt, cmd_info
        .import log_line
        .importzp asm_cpu
        .import cur_addr, cur_device, block_size
        .import nmi_pending
        .import ed_handle_key, enter_editor, leave_editor

; ── Imports: strings.s ──────────────────────────────────────
        .import VERSION_STR, s_manual

; ── Constants ────────────────────────────────────────────────
SCREEN_WIDTH = 40
SCREEN_HEIGHT = 25
LOG_INFO     = ' '
MEM_CONFIG   = $01
KEY_REPEAT   = $028A
VIC_MEMCTL   = $D018

; KERNAL vectors and API
VEC_TABLE    = $0314          ; start of KERNAL vector table (32 bytes)
KERNAL_VECTOR = $FF8D         ; KERNAL VECTOR: C=1 read, C=0 write
KERNAL_RESTOR = $FF8A         ; KERNAL RESTOR: restore default vectors

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

TXTTAB       = $0801          ; BASIC program text start (stock C64)
WORKSTART    = TXTTAB - 1    ; first workspace byte ($0800)

; Cold-init snapshot location (KBSS, under KERNAL ROM).
; Reserved exclusively for main.s — see memory_design.md § Banked layout.
; Pure writes pass through to RAM regardless of $01 bit 1.
COLD_ZP      = $F8DA          ; 127 bytes: snapshot of $01-$7F

; VECTOR table size ($0314-$0333 = 32 bytes)
VEC_TBL_SIZE = 32

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

state:       .res 1              ; ST_STOP=0, ST_REPL=1, ST_EDIT=2
warm_guard:  .res 1              ; nonzero = warm start in progress

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

        ; ── 1. All keys repeat, disable SHIFT+C= charset switch ──
        lda KEY_REPEAT
        ora #$80
        sta KEY_REPEAT
        lda #$80
        sta $0291               ; MODE: $80 = disable SHIFT+C=

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

        ; ── 10. Fill free work area ($0800 to cse_start-1) with $00 ──
        ; $00 so BASIC sees an empty program at $0801 after exit
        ; (link pointer $0000 = end of program).
        ; Hi-byte-only termination is safe: cse_start (__CODE_RUN__)
        ; is page-aligned by compute_layout.py (& $FF00).
        lda #<WORKSTART
        sta rp_ptr
        lda #>WORKSTART
        sta rp_ptr+1
        jsr cse_start          ; A/X = runtime start hi in X
        ldy #0
        tya                     ; A = 0 (1 byte vs lda #$00 = 2)
@work:  sta (rp_ptr),y
        inc rp_ptr
        bne :+
        inc rp_ptr+1
:       cpx rp_ptr+1            ; done when hi byte reaches cse_start hi
        bne @work

        ; ── 11. Install permanent hooks via KERNAL VECTOR ──
        jsr install_hooks

        ; ── 12. I/O and screen for splash ──
        jsr io_init
        jsr theme_init
        jsr reset_screen
        jsr set_charset

        ; ── 13. Init global state ──
        jsr reset_globals

        ; ── 14. Splash screen ─────────────────────────────────
        ; Position cursor for splash output (log_line prints at
        ; cursor position, then advances via log_close)
        lda #SCREEN_HEIGHT - 10
        jsr splash_row

        ; Version line
        ldy #LOG_INFO
        lda #<VERSION_STR
        ldx #>VERSION_STR
        jsr log_line

        ; Blank line between version and memory info
        jsr newline

        ; Free memory lines (splash mode: free only, no highlight)
        sec                     ; C=1 = splash mode
        jsr cmd_info

        ; Blank line between version and memory info
        jsr newline

        ; Manual line
        ldy #LOG_INFO
        lda #<s_manual
        ldx #>s_manual
        jsr log_line

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
        jmp cse_warm_screen

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
; install_hooks — install BRK + NMI vectors via KERNAL VECTOR
; ═════════════════════════════════════════════════════════════
install_hooks:
        sei
        ; Read-modify-write $0314-$0333 via KERNAL VECTOR.
        ; Only BRK ($0316) and NMI ($0318) are modified.
        ; Allocate 32-byte stack frame
        tsx
        stx rp_tmp              ; save SP
        txa
        sec
        sbc #VEC_TBL_SIZE
        tax
        txs
        ; Read current vector table → stack frame
        tsx
        inx                     ; X = buffer lo (SP+1)
        ldy #$01                ; Y = buffer hi ($01xx)
        sec                     ; C=1 → read $0314-$0333 → buffer
        jsr KERNAL_VECTOR
        ; Modify BRK (offset 2,3) and NMI (offset 4,5)
        tsx
        lda #<cse_brk_handler
        sta $0103,x             ; buffer[2] = BRK lo
        lda #>cse_brk_handler
        sta $0104,x             ; buffer[3] = BRK hi
        lda #<cse_nmi_handler
        sta $0105,x             ; buffer[4] = NMI lo
        lda #>cse_nmi_handler
        sta $0106,x             ; buffer[5] = NMI hi
        ; Write modified table back — atomic, all vectors at once
        inx
        ldy #$01
        clc                     ; C=0 → buffer → $0314-$0333
        jsr KERNAL_VECTOR
        ; Deallocate stack frame
        ldx rp_tmp
        txs
        cli
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
;
; No register save needed here:
;   User path: KERNAL $FF48 already pushed A/X/Y to the stack
;     before JMP ($0316).  dbg_brk_core reads them at fixed
;     stack offsets.  Our `lda` clobbers A but not the stack copy.
;   Warm-start path: resets SP to $FF — all state discarded.
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
; Layer 2: cse_warm_start — idempotent recovery
; ═════════════════════════════════════════════════════════════
cse_warm_start:
        ; Re-entry guard: if warm start itself BRKs, don't loop —
        ; fall through to KERNAL cold start as last resort.
        lda warm_guard
        bne @hard_fail
        inc warm_guard

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

        lda #0
        sta warm_guard
        ; Fall through to cse_warm_screen
        jmp cse_warm_screen

@hard_fail:
        jmp $FCE2               ; KERNAL cold start — last resort

; ═════════════════════════════════════════════════════════════
; cse_warm_screen — screen recovery tail
; ═════════════════════════════════════════════════════════════
cse_warm_screen:
        jsr reset_screen
        lda #SCREEN_HEIGHT - 1
        jsr splash_row
        jsr io_clear_eol
        jsr show_prompt
        jmp main_loop

; ═════════════════════════════════════════════════════════════
; cse_exit_to_basic — clean exit to BASIC warm start
;
; Order: sei → RESTOR → bank out KERNAL (to read KBSS) →
; restore $02-$7F → restore $01 (re-banks KERNAL+BASIC) → cli →
; CINT → jmp ($A002).  $01 must be restored LAST because it
; controls banking: KERNAL must stay out while reading KBSS.
; ═════════════════════════════════════════════════════════════
cse_exit_to_basic:
        sei
        ; Re-enable SHIFT+C= charset switch
        lda #$00
        sta $0291
        ; Restore $0314-$0333 to KERNAL defaults (one call)
        jsr KERNAL_RESTOR
        ; Bank out KERNAL to read KBSS ZP snapshot
        lda MEM_CONFIG
        and #$FD
        sta MEM_CONFIG
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
        ; TXTTAB-1 must be $00 for BASIC's LINKPRG.
        lda #0
        sta TXTTAB - 1
        ; Reinit screen I/O (clear screen, default colors, uppercase)
        jsr $FF81               ; KERNAL CINT
        ; BASIC warm start — READY prompt + input loop
        jmp ($A002)
