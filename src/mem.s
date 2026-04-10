; mem.s — Memory manager: banking, segment queries, workspace symbols
;
; Permanent module that consolidates all runtime memory services.
;
; Exports:
;   kernal_bank_out  SEI + clear $01 bit 1 (honours kernal_out)
;   kernal_bank_in   set $01 bit 1 + CLI (honours kernal_out)
;   kernal_init      install NMI trampoline at $FF00
;   kernal_out       BSS flag (nonzero = KERNAL held banked out)
;   cse_start        returns runtime start (XXXX) in A/X
;   cse_end          returns $D000 in A/X
;   cse_zp_end       returns first free ZP byte in A
;   define_ws_syms   define workstart/workend in symbol table

        .setcpu "6502"

; ── Exports ──────────────────────────────────────────────────
        .export kernal_bank_out, kernal_bank_in, kernal_init
        .export kernal_out
        .export cse_start, cse_end, cse_zp_end
        .export define_ws_syms

; ── Imports ──────────────────────────────────────────────────
        .importzp buf_base
        .importzp sym_name, sym_val, sym_wide
        .import sym_define
        .import __ZP_LAST__

; ── Constants ────────────────────────────────────────────────
CPU_PORT     = $01
NMI_TRAMP    = $FF00
NMI_VEC_RAM  = $FFFA
KERNAL_NMIV  = $0318          ; KERNAL indirect NMI vector (RAM)
WORKSTART    = $0800
HIMEM        = $D000

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

kernal_out:     .res 1          ; nonzero = KERNAL banked out (skip bank_in)

; ── RODATA ───────────────────────────────────────────────────
.segment "RODATA"

; NMI trampoline code (10 bytes, copied to $FF00 by kernal_init)
_nmi_tramp_code:
        ; lda $01 / ora #$02 / sta $01 / sei / jmp ($0318)
        .byte $A5, $01          ; LDA $01
        .byte $09, $02          ; ORA #$02
        .byte $85, $01          ; STA $01
        .byte $78               ; SEI
        .byte $6C               ; JMP (abs)
        .byte <KERNAL_NMIV, >KERNAL_NMIV
NMI_TRAMP_SIZE = * - _nmi_tramp_code

.import __CODE_RUN__

_zp_end_val:    .byte <(__ZP_LAST__ + 1)

s_workstart:    .byte "workstart", 0
s_workend:      .byte "workend", 0

; ── CODE ─────────────────────────────────────────────────────
.segment "CODE"

; ── Banking helpers ──────────────────────────────────────────
; kernal_bank_out: sei + clear $01 bit 1 → KERNAL ROM hidden
; kernal_bank_in:  set $01 bit 1 → KERNAL ROM visible + cli
;
; Both helpers honour the kernal_out flag: when non-zero, the
; caller is managing banking explicitly across a long batch
; (e.g. asm_assemble holds KERNAL out for both passes), so the
; helpers become no-ops.
;
; ── ORDERING RULE FOR BATCH CALLERS ──
; Because BOTH helpers short-circuit on kernal_out, a batch caller
; must do the real bank operation BEFORE setting/clearing the flag:
;
;     ; ENTER batch                  ; LEAVE batch
;     jsr kernal_bank_out             lda #0
;     lda #1                          sta kernal_out
;     sta kernal_out                  jsr kernal_bank_in
;
; Pure writers under KERNAL ($E000–$FFFF) do NOT need either
; helper: stores pass through to the underlying RAM regardless of
; $01 bit 1.
kernal_bank_out:
        lda kernal_out
        bne @skip               ; flag set → already banked out
        sei
        lda CPU_PORT
        and #$FD                ; clear bit 1 → RAM under KERNAL
        sta CPU_PORT
@skip:  rts

kernal_bank_in:
        lda kernal_out
        bne @skip               ; flag set → stay banked out (caller manages)
        lda CPU_PORT
        ora #$02                ; set bit 1 → KERNAL ROM restored
        sta CPU_PORT
        cli
@skip:  rts

; ═════════════════════════════════════════════════════════════
; kernal_init — install NMI trampoline in banked RAM
;   Must be called once at startup.
;   Pure writer: stores under KERNAL pass through to RAM
;   regardless of $01 bit 1, so no banking is required.
;   Clobbers A, X.
; ═════════════════════════════════════════════════════════════
.proc kernal_init
        ; Copy trampoline code to $FF00
        ldx #NMI_TRAMP_SIZE - 1
@copy:  lda _nmi_tramp_code,x
        sta NMI_TRAMP,x
        dex
        bpl @copy

        ; Set RAM NMI vector → $FF00
        lda #<NMI_TRAMP
        sta NMI_VEC_RAM
        lda #>NMI_TRAMP
        sta NMI_VEC_RAM + 1
        rts
.endproc

; ═════════════════════════════════════════════════════════════
; cse_start — return runtime start address in A/X
; ═════════════════════════════════════════════════════════════
cse_start:
        lda #<__CODE_RUN__
        ldx #>__CODE_RUN__
        rts

; ═════════════════════════════════════════════════════════════
; cse_end — return first byte past runtime in A/X
;   Always $D000 (BSS ends just before I/O).
; ═════════════════════════════════════════════════════════════
cse_end:
        lda #<HIMEM
        ldx #>HIMEM
        rts

; ═════════════════════════════════════════════════════════════
; cse_zp_end — return first free ZP byte in A
; ═════════════════════════════════════════════════════════════
cse_zp_end:
        lda _zp_end_val
        ldx #0
        rts

; ═════════════════════════════════════════════════════════════
; define_ws_syms — define workstart/workend in symbol table
;   workstart = $0800 (fixed)
;   workend   = buf_base - 1 (inclusive)
; ═════════════════════════════════════════════════════════════
.proc define_ws_syms
        ; ── workstart ($0800, fixed) ──
        lda #<WORKSTART
        sta sym_val
        lda #>WORKSTART
        sta sym_val+1
        lda #<s_workstart
        sta sym_name
        lda #>s_workstart
        sta sym_name+1
        lda #1
        sta sym_wide            ; ABS
        jsr sym_define

        ; ── workend (inclusive: buf_base - 1) ──
        lda buf_base
        sec
        sbc #1
        sta sym_val
        lda buf_base+1
        sbc #0
        sta sym_val+1
        lda #<s_workend
        sta sym_name
        lda #>s_workend
        sta sym_name+1
        lda #1
        sta sym_wide            ; ABS
        jmp sym_define         ; tail call
.endproc

