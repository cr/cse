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
        .import s_workstart, s_workend

; ── Constants ────────────────────────────────────────────────
CPU_PORT     = $01
NMI_TRAMP    = $FF00
IRQ_TRAMP    = $FF04
NMI_VEC_RAM  = $FFFA
IRQ_VEC_RAM  = $FFFE
KERNAL_NMIV  = $0318          ; KERNAL indirect NMI vector (RAM)
KERNAL_IRQ   = $FF48          ; KERNAL IRQ entry (ROM)
WORKSTART    = $0800
HIMEM        = $D000

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

kernal_out:     .res 1          ; nonzero = KERNAL banked out (skip bank_in)

; ── RODATA ───────────────────────────────────────────────────
.segment "RODATA"

; NMI trampoline (4 bytes, copied to $FF00 by kernal_init)
;
; When KERNAL is banked out, ($FFFA) reads from RAM → $FF00.
; The handler chain (cse_nmi_handler → dbg_nmi_break) runs
; entirely in main-RAM CODE — no KERNAL ROM access needed.
; So the trampoline just does SEI + JMP ($0318), matching
; what the KERNAL's own $FE43 entry does when KERNAL is mapped.
;
; Previous design banked KERNAL in (ORA #$02 / STA $01) which
; permanently corrupted $01 — after RTI the caller's banking
; state was wrong, causing reads of KERNAL ROM instead of RAM.
_nmi_tramp_code:
        sei
        jmp (KERNAL_NMIV)
NMI_TRAMP_SIZE = * - _nmi_tramp_code

; IRQ/BRK trampoline (10 bytes, copied to $FF04 by kernal_init)
;
; Defensive: if a BRK fires while KERNAL is banked out (user code
; contract violation, or CSE internal fault), ($FFFE) reads from
; RAM → $FF04.  Banks KERNAL in so $FF48 can run its IRQ entry.
; Saves/restores A around the banking so the KERNAL's PHA at $FF48
; captures the correct user A.
_irq_tramp_code:
        pha                   ; save user A
        lda $01
        ora #$02              ; bank KERNAL in
        sta $01
        pla                   ;restore user A
        jmp KERNAL_IRQ
IRQ_TRAMP_SIZE = * - _irq_tramp_code

.import __CODE_RUN__

_zp_end_val:    .byte <(__ZP_LAST__ + 1)


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
; kernal_init — install NMI + IRQ/BRK trampolines in banked RAM
;   Must be called once at startup.
;   Pure writer: stores under KERNAL pass through to RAM
;   regardless of $01 bit 1, so no banking is required.
;   Clobbers A, X.
; ═════════════════════════════════════════════════════════════
.proc kernal_init
        ; Copy NMI trampoline to $FF00 (4 bytes)
        ldx #NMI_TRAMP_SIZE - 1
@nmi:   lda _nmi_tramp_code,x
        sta NMI_TRAMP,x
        dex
        bpl @nmi

        ; Copy IRQ/BRK trampoline to $FF04 (10 bytes)
        ldx #IRQ_TRAMP_SIZE - 1
@irq:   lda _irq_tramp_code,x
        sta IRQ_TRAMP,x
        dex
        bpl @irq

        ; Set RAM vectors (pure write, no banking needed)
        lda #<NMI_TRAMP
        sta NMI_VEC_RAM
        lda #>NMI_TRAMP
        sta NMI_VEC_RAM + 1
        lda #<IRQ_TRAMP
        sta IRQ_VEC_RAM
        lda #>IRQ_TRAMP
        sta IRQ_VEC_RAM + 1
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
        lda #1
        sta sym_wide            ; ABS — set once (sym_define preserves it)

        ; ── workstart ($0800, fixed) ──
        lda #<WORKSTART
        sta sym_val
        lda #>WORKSTART
        sta sym_val+1
        lda #<s_workstart
        sta sym_name
        lda #>s_workstart
        sta sym_name+1
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
        jmp sym_define         ; tail call
.endproc

