; mem.s — Memory manager: banking, ZP save/restore, segment queries,
;         workspace symbols.
;
; Permanent module that consolidates low-level state-preservation
; primitives paired by contract:
;
;   KERNAL ROM banking:
;     kernal_bank_out    clear $01 bit 1 (honours kernal_out)
;     kernal_bank_in     set   $01 bit 1 (honours kernal_out)
;     kernal_out         BSS flag (nonzero = KERNAL held banked out)
;
;   CPU-port aware ZP save/restore (kernel↔userland gates):
;     save_userland_zp   live ZP → userland_zp_buf  (DDR-stash single pass)
;     restore_userland_zp userland_zp_buf → live ZP  (DDR=$FF + backwards)
;     save_kernel_zp     live ZP → kernel_zp_buf (mirror of above)
;     restore_kernel_zp  kernel_zp_buf → live ZP (mirror of above)
;     userland_zp_buf        BSS (128 B): user's ZP snapshot
;     kernel_zp_buf      BSS (128 B): kernel's ZP snapshot
;
;   Misc queries:
;     cse_start          returns runtime start (XXXX) in A/X
;     cse_end            returns $D000 in A/X
;     cse_zp_end         returns first free ZP byte in A
;     define_ws_syms     define workstart/workend in symbol table

        .setcpu "6502"

; ── ZP save/restore range ────────────────────────────────────
; The save buffers (kernel_zp_buf / userland_zp_buf) mirror live
; ZP addresses [ZP_SAVE_LO, ZP_SAVE_LO + ZP_SAVE_LEN).  Any code
; that wants to read or write "user ZP" rather than "live ZP"
; must use these constants to decide its range and index
; `userland_zp_buf - ZP_SAVE_LO` for the offset arithmetic.
ZP_SAVE_LO  = $00
ZP_SAVE_LEN = 128

; ── Exports ──────────────────────────────────────────────────
        .export kernal_bank_out, kernal_bank_in
        .export kernal_out
        .export cse_start, cse_end, cse_zp_end
        .export define_ws_syms
        .export save_userland_zp, restore_userland_zp
        .export save_kernel_zp, restore_kernel_zp
        .export userland_zp_buf, kernel_zp_buf
        .export ZP_SAVE_LO, ZP_SAVE_LEN

; ── Imports ──────────────────────────────────────────────────
        .importzp buf_base
        .importzp sym_name, sym_val, sym_wide
        .import sym_define
        .import __ZP_LAST__
        .import s_workstart, s_workend

; ── Constants ────────────────────────────────────────────────
CPU_PORT     = $01
WORKSTART    = $0800
HIMEM        = $D000

; ── BSS ──────────────────────────────────────────────────────
.segment "BSS"

kernal_out:     .res 1          ; nonzero = KERNAL banked out (skip bank_in)

; ── ZP save/restore buffers ─────────────────────────────────
; Cover the full user-accessible page-zero range $00..$7F.  CSE
; only allocates $02..$59 for its own variables, but the full
; lower half is snapshotted so:
;   1. The `m` and `.` commands render a uniform user-ZP view
;      across the entire range.
;   2. The $00/$01 CPU-port pair round-trips via these buffers
;      (see the CPU-port protocol note below the bank helpers).
; Upper half $80..$FF stays KERNAL-owned and is never touched.
kernel_zp_buf:  .res ZP_SAVE_LEN  ; kernel's ZP snapshot (exit capture)
userland_zp_buf:    .res ZP_SAVE_LEN  ; user's ZP snapshot (exit capture,
                                   ; restored on re-entry)

; ── RODATA ───────────────────────────────────────────────────
.segment "RODATA"

.import __CODE_RUN__

_zp_end_val:    .byte <(__ZP_LAST__ + 1)


; ── CODE ─────────────────────────────────────────────────────
.segment "CODE"

; ── Banking helpers ──────────────────────────────────────────
; kernal_bank_out: clear $01 bit 1 → KERNAL ROM hidden
; kernal_bank_in:  set   $01 bit 1 → KERNAL ROM restored
;
; No SEI/CLI guards are needed here: Phase 18's $FFFE RAM-shadow
; points at cse_brk_handler_early, which transparently handles an
; IRQ that fires while KERNAL is banked out (insert bank_out_stub
; frame, bank KERNAL in, delegate to $EA31, KERNAL's RTI lands at
; bank_out_stub which banks out again and RTIs the original frame).
; The CPU's I flag is therefore irrelevant to banking correctness.
;
; Both helpers honour the kernal_out flag: when non-zero, the caller
; is managing banking across a long batch (e.g. asm_assemble holds
; KERNAL out for both passes), so the helpers become no-ops.
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
; Pure writers under KERNAL ($E000–$FFFF) do NOT need either helper:
; stores pass through to the underlying RAM regardless of $01 bit 1.
kernal_bank_out:
        lda kernal_out
        bne @skip               ; flag set → already banked out
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
@skip:  rts

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

; ═══════════════════════════════════════════════════════════════════════════
; CPU-port aware ZP save/restore — kernel↔userland ZP swap primitives
;
; ZP addresses $00 and $01 are the 6510/8500's on-chip CPU I/O port:
;   $00 — DDR (data direction).  Bits configured as OUTPUT (1) are
;         CPU-driven.  Bits configured as INPUT (0) float to external
;         state; a read returns external logic level, NOT the value
;         the CPU last wrote.  C64 default: $2F (bits 0-5 output,
;         6-7 input).
;   $01 — data.  Writes always latch internally for all bits;
;         pins driven to the bus reflect only the output bits.
;         Bits 0-2 = LORAM/HIRAM/CHAREN (memory banking);
;         bit 3 = cassette write; bits 4-5 = cassette sense / key;
;         bits 6-7 = input pins (cassette).  CSE-kernel default:
;         $36 (BASIC out, KERNAL in, I/O in).
;
; Failure modes the protocol defends against:
;
;   * Naive `sta $00,x` of a BSS-zero buffer byte sets DDR=all-input.
;     Subsequent writes to $01 don't latch on bits configured as
;     input; banking goes floating; the next fetch JAMs.
;
;   * Naive `lda $01` with the user's DDR returns a mix of latched
;     bits (outputs) and external bits (inputs).  Saving that value
;     and later restoring it feeds external garbage back into $01
;     as if it were the user's intended value.
;
; Save protocol (single-pass DDR stash):
;
;     ldy $00              ; snapshot current DDR into Y
;     lda #$FF / sta $00   ; DDR := all-output (unmask $01's input bits)
;     ldx #$7F
;   @loop: lda $00,x / sta buf,x / dex / bpl @loop
;     sty buf              ; overwrite buf[$00] (transient $FF) with saved DDR
;
;   During the loop, the x=$01 iteration reads $01 with all bits
;   CPU-driven (because DDR=$FF), so buf[$01] gets the fully
;   latched byte — every bit the CPU last wrote.  The loop's
;   x=$00 iteration captures the transient $FF into buf[$00]; the
;   post-loop `sty` overwrites that with the snapshot of the real
;   DDR from Y.
;
;   Postcondition: live $00 = $FF.  This is load-bearing for the
;   restore functions below, which rely on it rather than re-asserting
;   DDR=$FF themselves (a redundant write would only mask broken code
;   if the postcondition ever regressed).
;
; Restore protocol (backwards copy, DDR=$FF inherited from prior save):
;
;     ldx #$7F
;   @loop: lda buf,x / sta $00,x / dex / bpl @loop
;
;   Precondition: live $00 = $FF (postcondition of save_userland_zp
;   or save_kernel_zp, which is the only legitimate predecessor).
;   Backwards iteration order ($7F → $00) places:
;     x=$01: writes buf[$01] to live $01 while DDR is still $FF,
;            so every bit fully latches.
;     x=$00: writes buf[$00] to live $00 LAST, re-applying the
;            target DDR mask after data bits are already set.
;
; Bootstrap: dbg_init pre-seeds both userland_zp_buf and kernel_zp_buf
; with [$00]=$2F and [$01]=$36 so the very first transition doesn't
; restore zeros into the live CPU port.  After the first exit cycle,
; save_userland_zp and save_kernel_zp overwrite those seeds with
; captured live values.
; ═══════════════════════════════════════════════════════════════════════════

; ── save_userland_zp ───────────────────────────────────────────
; Single-pass save: live ZP ($00..$7F) → userland_zp_buf with DDR
; stash/restore so $01 is captured fully-latched.
; Postcondition: live $00 = $FF.  Clobbers A, X, Y.
.proc save_userland_zp
        ldy ZP_SAVE_LO           ; Y := current DDR
        lda #$FF
        sta ZP_SAVE_LO           ; $00 := $FF (unmask $01)
        ldx #ZP_SAVE_LEN - 1
@l:     lda ZP_SAVE_LO,x         ; x=$01 reads fully-latched $01;
        sta userland_zp_buf,x        ; x=$00 captures transient $FF
        dex                      ;        (overwritten below).
        bpl @l
        sty userland_zp_buf          ; buf[$00] := saved DDR
        rts
.endproc

; ── restore_userland_zp ────────────────────────────────────────
; Backwards copy: userland_zp_buf → live ZP.  Writes $01 (fully-latching,
; while DDR=$FF) before $00 (re-applies user's DDR).
; Precondition: live $00 = $FF (from save_kernel_zp's postcondition —
; every kernel-flow call path enters here via save_kernel_zp).
; Clobbers A, X.
.proc restore_userland_zp
        ldx #ZP_SAVE_LEN - 1
@l:     lda userland_zp_buf,x
        sta ZP_SAVE_LO,x         ; x=$01 latches; x=$00 re-DDRs
        dex
        bpl @l
        rts
.endproc

; ── save_kernel_zp ─────────────────────────────────────────────
; Mirror of save_userland_zp, target = kernel_zp_buf.
; Postcondition: live $00 = $FF.  Clobbers A, X, Y.
.proc save_kernel_zp
        ldy ZP_SAVE_LO
        lda #$FF
        sta ZP_SAVE_LO
        ldx #ZP_SAVE_LEN - 1
@l:     lda ZP_SAVE_LO,x
        sta kernel_zp_buf,x
        dex
        bpl @l
        sty kernel_zp_buf
        rts
.endproc

; ── restore_kernel_zp ──────────────────────────────────────────
; Mirror of restore_userland_zp, source = kernel_zp_buf.
; Precondition: live $00 = $FF (from save_userland_zp's postcondition —
; every kernel-flow call path enters here via save_userland_zp).
; Clobbers A, X.
.proc restore_kernel_zp
        ldx #ZP_SAVE_LEN - 1
@l:     lda kernel_zp_buf,x
        sta ZP_SAVE_LO,x
        dex
        bpl @l
        rts
.endproc

