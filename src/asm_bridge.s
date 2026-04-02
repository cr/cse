; asm_bridge.s — C-callable wrapper for al_line_asm
;
; Provides:
;   _asm_line     C function: uint8_t asm_line(uint16_t addr, char *text)
;                 Assembles one instruction from the PETSCII text string,
;                 writes bytes to *addr, and returns the byte count (1–3).
;                 Returns 0 on error (unknown mnemonic, bad mode, etc.).
;
;   al_error      Error landing used by asm_line.s — restores the stack
;   au_syntax_error  Error landing used by au_mode.s / parse_hex.s
;
; The text string must be PETSCII (uppercase $41–$5A, digits $30–$39,
; punctuation as-is).  _al_rd_upper in asm_line.s handles the PETSCII→VICII
; conversion for mnemonic letters.  The operand parser in au_mode.s expects
; VICII screen codes for hex digits ($30–$39) and A–F ($01–$06).
; This wrapper converts the string in-place before calling al_line_asm.
;
; cc65 calling convention (__fastcall__, default):
;   First arg (addr)  pushed onto C stack (sp),0 / (sp),1
;   Last arg  (text)  in A/X  (A=lo, X=hi)  — passed in registers

        .setcpu "6502"

        .export _asm_line
        .export al_error, au_syntax_error
        .export _jsr_addr
        .export _reg_a, _reg_x, _reg_y, _reg_sp, _reg_p
        .export _zp_save_buf

        .import al_line_asm
        .importzp au_ptr, al_pc, al_out, al_cpu, al_len
        .import cse_popax         ; our C stack pop (in cse_io.s)

.segment "ZEROPAGE"
_ab_saved_sp:   .res 1          ; saved 6502 SP for error recovery
_jsr_vec:       .res 2          ; target address for _jsr_addr

.segment "BSS"
_asm_out_buf:   .res 3          ; output buffer (max 3 instruction bytes)
_reg_a:         .res 1          ; saved A  after jsr_addr
_reg_x:         .res 1          ; saved X
_reg_y:         .res 1          ; saved Y
_reg_sp:        .res 1          ; saved SP
_reg_p:         .res 1          ; saved P (status flags)

ZP_SAVE_LO = $02               ; first ZP byte used by CSE
ZP_SAVE_HI = $5E               ; last ZP byte — must cover all cc65 ZP (sp..regbank)
ZP_SAVE_LEN = ZP_SAVE_HI - ZP_SAVE_LO + 1  ; 93 bytes
_zp_save_buf:   .res ZP_SAVE_LEN ; buffer for ZP save/restore around jsr_addr

.segment "CODE"

; ── al_error / au_syntax_error ──────────────────────────────────────────────
; Jumped to (not called) by asm_line.s / au_mode.s on any assembler error.
; Restores the 6502 stack to the level saved before al_line_asm was called,
; then returns 0 to the C caller.
al_error:
au_syntax_error:
        ldx _ab_saved_sp
        txs                     ; restore SP (unwind nested JSRs)
        lda #0
        tax                     ; return 0 (uint8_t, A=lo, X=hi=0)
        jmp _ab_return

; ── _asm_line ───────────────────────────────────────────────────────────────
; uint8_t __cdecl__ asm_line(uint16_t addr, char *text);
;
; On entry (cc65 __cdecl__):
;   A/X = text pointer (lo/hi)  — last argument
;   C stack (sp),0/(sp),1 = addr (lo/hi)
;
_asm_line:
        ; ── save text pointer ───────────────────────────────────────────
        sta au_ptr
        stx au_ptr+1

        ; ── convert text buffer from PETSCII to VICII screen codes ──────
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

        ; ── pop addr from C stack ───────────────────────────────────────
        jsr cse_popax           ; A = lo, X = hi
        sta al_pc
        sta al_out              ; output → target address (assemble in place)
        stx al_pc+1
        stx al_out+1

        ; ── set CPU mode from build-time default ────────────────────────
.ifndef DEFAULT_CPU
  DEFAULT_CPU = 1               ; fallback: 6510
.endif
        lda #DEFAULT_CPU
        sta al_cpu

        ; ── save 6502 SP for error recovery ─────────────────────────────
        tsx
        stx _ab_saved_sp

        ; ── call assembler ──────────────────────────────────────────────
        ldy #0                  ; required by al_line_asm entry contract
        jsr al_line_asm

        ; ── success: return al_len ──────────────────────────────────────
        lda al_len
        ldx #0                  ; hi byte = 0 (uint8_t return)

_ab_return:
        rts

; ── _jsr_addr ─────────────────────────────────────────────────────────────────
; void jsr_addr(uint16_t addr);   /* __fastcall__: addr in A/X */
;
; JSR to the given address, then capture all CPU registers (A, X, Y, SP, P)
; into reg_a..reg_p so the C side can display them.
;
_jsr_addr:
        sta _jsr_vec            ; store target address lo
        stx _jsr_vec+1          ; store target address hi

        ; ── save CSE's ZP $02-$38 so user code can use all of ZP ──
        ldx #ZP_SAVE_LEN - 1
@save:  lda ZP_SAVE_LO,x
        sta _zp_save_buf,x
        dex
        bpl @save

        ; ── load user's register state before calling ──
        lda _reg_a
        ldx _reg_x
        ldy _reg_y

        jsr @trampoline         ; JSR → user code → RTS → back here

        ; ── capture registers immediately after user code returns ──
        sta _reg_a
        stx _reg_x
        sty _reg_y
        php
        pla
        sta _reg_p
        tsx
        stx _reg_sp

        ; ── restore CSE's ZP ──
        ldx #ZP_SAVE_LEN - 1
@rest:  lda _zp_save_buf,x
        sta ZP_SAVE_LO,x
        dex
        bpl @rest

        rts

@trampoline:
        jmp (_jsr_vec)          ; indirect JMP; the JSR above provides the
                                ; return address, so user's RTS comes back
                                ; to the sta _reg_a above
