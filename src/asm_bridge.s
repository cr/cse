; asm_bridge.s — Calling convention bridge for al_line_asm
;
; Provides:
;   asm_line      Assembles one instruction from a PETSCII text string,
;                 writes bytes to *addr, and returns the byte count (1–3).
;                 Returns 0 on error (unknown mnemonic, bad mode, etc.).
;
;   al_error      Error landing used by asm_line.s — restores the stack
;   au_syntax_error  Error landing used by au_mode.s
;
; The text string must be PETSCII (uppercase $41–$5A, digits $30–$39,
; punctuation as-is).  _al_rd_upper in asm_line.s handles the PETSCII→VICII
; conversion for mnemonic letters.  The operand parser in au_mode.s expects
; VICII screen codes for hex digits ($30–$39) and A–F ($01–$06).
; This wrapper converts the string in-place before calling al_line_asm.
;
; Calling convention:
;   Caller sets al_pc and al_out before calling.
;   A/X = text pointer (lo/hi)

        .setcpu "6502"

        .export asm_line
        .export al_error, au_syntax_error
        .export reg_a, reg_x, reg_y, reg_sp, reg_p
        .export zp_save_buf
        .export user_zp_buf

        .import al_line_asm
        .import kernal_bank_out, kernal_bank_in
        .importzp au_ptr, al_pc, al_out, al_cpu, al_len

.segment "ZEROPAGE"
_ab_saved_sp:   .res 1          ; saved 6502 SP for error recovery

.segment "BSS"
_asm_out_buf:   .res 3          ; output buffer (max 3 instruction bytes)
; Saved user-code register state — populated by debugger.s on BRK/NMI
; entry, displayed by repl.s::show_regs, and reloaded into the CPU by
; debugger.s before continuing.
reg_a:         .res 1          ; saved A
reg_x:         .res 1          ; saved X
reg_y:         .res 1          ; saved Y
reg_sp:        .res 1          ; saved SP
reg_p:         .res 1          ; saved P (status flags)

; ── ZP save range ──
; CSE uses ZP $02..$59 (editor.o is the last allocation per the
; linker map).  $02 is the first byte; $59 is the last.  Both
; bounds must agree across all callers (asm_bridge.s and
; debugger.s) — see debugger.s::ZP_SAVE_LO/HI which mirror these
; constants exactly.  A regression where the bounds drift would
; cause dbg_enter to overflow zp_save_buf (or save too few bytes,
; corrupting CSE state on debug return).
ZP_SAVE_LO = $02
ZP_SAVE_HI = $59
ZP_SAVE_LEN = ZP_SAVE_HI - ZP_SAVE_LO + 1  ; 88 bytes
zp_save_buf:   .res ZP_SAVE_LEN ; buffer for ZP save/restore

; ── User ZP snapshot ──
; When a user program is interrupted (BRK / NMI) or RTSes back
; to the REPL, the live ZP is the user's working state — but
; dbg_enter step 8 immediately restores CSE's ZP from
; zp_save_buf, overwriting it.  Without a snapshot, the user
; can't inspect their ZP via the m or . commands afterward
; (they'd see CSE's variables, not what their code wrote).
;
; user_zp_buf holds a copy of the user's ZP $02..$59 captured
; AT THE MOMENT user code is interrupted, before any CSE code
; clobbers it.  cmd_mem reads from user_zp_buf for addresses
; in $02..$59 when dbg_reason != 0.
user_zp_buf:   .res ZP_SAVE_LEN ; user ZP snapshot ($02..$59)

.segment "CODE"

; ── al_error / au_syntax_error ──────────────────────────────────────────────
; Jumped to (not called) by asm_line.s / au_mode.s on any assembler error.
; Restores the 6502 stack to the level saved before al_line_asm was called,
; banks the KERNAL back in, and returns 0.
al_error:
au_syntax_error:
        ldx _ab_saved_sp
        txs                     ; restore SP (unwind nested JSRs)
        jsr kernal_bank_in      ; pair the bank_out from asm_line entry
        lda #0
        tax                     ; return 0 (uint8_t, A=lo, X=hi=0)
        rts

; ── asm_line ───────────────────────────────────────────────────────────────
; asm_line(text)
;
; Single shared entry point for both call paths:
;   - asm_src.s::process_line (inside asm_assemble's batched bank-out;
;     the inner bank helpers below short-circuit because kernal_out=1)
;   - repl.s::dot_assemble (single-line REPL `.` command; the inner
;     bank helpers do the actual KERNAL bank for KDATA-table reads)
;
; KDATA tables (mn7/mn6, mode_offset, mn_modes, dasm_mne_str) live under
; KERNAL ROM, so al_line_asm and its callees must run with the KERNAL
; banked out.  asm_line owns that banking — callers don't manage it.
;
; On entry:
;   A/X = text pointer (lo/hi)
;   Caller has already set al_pc and al_out.
;
asm_line:
        ; ── save text pointer ───────────────────────────────────────────
        sta au_ptr
        stx au_ptr+1

        ; ── convert text buffer from PETSCII to VICII screen codes ──────
        ; The buffer is in main RAM (not under KERNAL), so this loop
        ; runs before the bank-out.
        ; Letters $41–$5A → $01–$1A (and $C1–$DA → $01–$1A)
        ; Digits $30–$39 stay as-is; space $20 stays; NUL $00 terminates.
        ldy #0
@cvt:   lda (au_ptr),y
        beq @cvt_done           ; NUL terminator
        cmp #$41
        bcc @cvt_next           ; $00–$40: keep (digits, space, #, $, etc.)
        cmp #$5B
        bcc @cvt_alpha          ; $41–$5A: uppercase PETSCII
        cmp #$C1
        bcc @cvt_next           ; $5B–$C0: keep
        cmp #$DB
        bcs @cvt_next           ; $DB–$FF: keep
@cvt_alpha:
        and #$1F                ; $41–$5A → $01–$1A, $C1–$DA → $01–$1A
        sta (au_ptr),y
@cvt_next:
        iny
        bne @cvt                ; max 255 chars
@cvt_done:

        ; al_pc and al_out already set by caller

        ; ── set CPU mode from build-time default ────────────────────────
.ifndef DEFAULT_CPU
  DEFAULT_CPU = 1               ; fallback: 6510
.endif
        lda #DEFAULT_CPU
        sta al_cpu

        ; ── save 6502 SP for error recovery ─────────────────────────────
        tsx
        stx _ab_saved_sp

        ; ── bank out KERNAL for KDATA reads (no-op inside an asm_assemble
        ; batch — kernal_out=1 short-circuits both bank helpers)
        jsr kernal_bank_out

        ; ── call assembler ──────────────────────────────────────────────
        ldy #0                  ; required by al_line_asm entry contract
        jsr al_line_asm

        ; ── bank back in.  bank_in clobbers A, so reload al_len after.
        jsr kernal_bank_in
        lda al_len              ; success: return byte count
        ldx #0                  ; hi byte = 0 (uint8_t return)
        rts
