; dasm.s — table-driven disassembler (6502 / 6510 / 65C02)
; Owner: doc/modules/dasm.md
;
; Interface:
;   dasm_insn (A/X = addr lo/hi)
;     Output: NUL-terminated PETSCII string in dasm_buf
;     Returns instruction length in A (1-3)
;
; CPU view: asm_cpu (build_system.md § Builds and CPU sets) selects one of
; the build's CPU views.  Every opcode fact comes from the generated
; dasm_tables.s (one block per CPU set); this file holds none:
;
;   dasm_cpu_map_lo/hi[asm_cpu]  → the view's map block:
;       +0    256 B  mnemonic index per opcode (0 = MNE_UNK, "...")
;       +256  128 B  mode per opcode, two 4-bit modes per byte (even = low)
;   dasm_cpu_bm[asm_cpu] = 1     → the view is the subset bitmap
;       dasm_view_bm over that map (DASM_SUBSET sets only); an opcode
;       outside it lists as "..."
;   dasm_mode_len / dasm_mode_fmt[mode]  → length and operand format
;   dasm_mne_str[index]          → 3 chars packed into 2 bytes (5 bits/char)
;
; A bit-digit key (MNE_DIGIT_LO..HI) is listed with the opcode's bits 6:4
; as its digit (RMB3).

        .include "platform.inc"
        .include "dasm_mne_idx.s"   ; MNE_UNK, MNE_DIGIT_*, DASM_SUBSET

        .export dasm_insn, dasm_insn_pre, _dasm_in
        .export dasm_buf

        .importzp asm_cpu
        .import dasm_mne_str, dasm_mode_len, dasm_mode_fmt
        .import dasm_cpu_map_lo, dasm_cpu_map_hi
.ifdef DASM_SUBSET
        .import dasm_cpu_bm, dasm_view_bm
.endif
        .import kernal_bank_out, kernal_bank_in

; ── ZP usage ─────────────────────────────────────────────
.importzp _dasm_ptr, _dasm_opc, _dasm_mne, _dasm_wptr, _dasm_midx, _dasm_mode

; ── BSS ──────────────────────────────────────────────────
.segment "BSS"
dasm_buf:      .res 24         ; output buffer (NUL-terminated PETSCII)
_dasm_in:      .res 3          ; input snapshot (3 bytes max-insn) read from
                               ; the user's address with the caller's bank
                               ; state still in force, so KERNAL ROM at
                               ; $E000+ is captured BEFORE dasm_insn banks
                               ; out for its internal table reads.  See the
                               ; rationale in dasm_insn's docstring.

; ── CODE ─────────────────────────────────────────────────
.segment "CODE"

; ════════════════════════════════════════════════════════════
; Entry point: dasm_insn
;   A = addr lo, X = addr hi
;   Returns length in A.  dasm_buf filled with PETSCII + NUL.
;
; dasm_insn owns its own KERNAL banking — callers don't manage
; it.  dasm_mne_str lives under KERNAL ROM (KDATA), so the decoder
; runs with KERNAL banked out.  Inside an asm_assemble batch
; (kernal_out=1) the bank helpers short-circuit, so this wrapper
; costs only the flag check on each call from inside the batch.
;
; KERNAL-ROM read fix: snapshot the 3 max-insn bytes from the
; user's address into _dasm_in BEFORE banking out — otherwise
; disassembly of `$E000+` would read the RAM under KERNAL (mostly
; $00 / $FF) and produce a stream of "brk" / "..." instead of the
; real KERNAL instructions.  The snapshot uses whatever bank state
; the caller had in force: at the REPL prompt that's KERNAL-in
; (so `d $E000` gets ROM); inside an asm_assemble batch that's
; KERNAL-out (so user RAM under KERNAL is what the user wrote).
; Either way, the user's "current view" of memory is what gets
; disassembled.
;
; The decoder has one exit (finish); its length survives the
; bank_in through pha / pla.
; ════════════════════════════════════════════════════════════
.proc dasm_insn
        sta _dasm_ptr
        stx _dasm_ptr+1
        ; Snapshot 3 bytes from the user address while the caller's
        ; bank state is still in force.  _dasm_ptr stays pointing at
        ; the user address — it's used by branch-target arithmetic in
        ; format_operand to compute PC-relative destinations.
        ldy #2
@cp:    FAR_LDA _dasm_ptr
        sta _dasm_in,y
        dey
        bpl @cp
; dasm_insn_pre — entry for a caller that has filled _dasm_in (3 B)
; and _dasm_ptr (the bytes' real PC, for branch targets) itself:
; the REPL's user-ZP staged view.  A label only, so the decoder's
; layout and cycle counts are unchanged.
::dasm_insn_pre:
        jsr kernal_bank_out
        jsr dasm_decode         ; A = length on return
        pha                     ; save length before bank_in clobbers A
        jsr kernal_bank_in
        pla
        rts
.endproc

; ── dasm_decode — map lookup, runs with KERNAL banked out ────
; Returns the instruction length in A (via finish).
.proc dasm_decode
        lda #0
        sta _dasm_wptr          ; reset buffer write position

        ; The view's map block → _dasm_mne (free until print_mne).
        ldx asm_cpu
        lda dasm_cpu_map_lo,x
        sta _dasm_mne
        lda dasm_cpu_map_hi,x
        sta _dasm_mne+1
        ldy _dasm_in            ; opcode
        sty _dasm_opc

.ifdef DASM_SUBSET
        ; Subset view: an opcode outside the bitmap lists as "...".
        lda dasm_cpu_bm,x       ; 0, or 1 + the view's bitmap offset
        beq @mapped
        tya
        lsr
        lsr
        lsr
.ifdef DASM_BYTE_MODES          ; m65: two bitmaps, back to back
        clc
        adc dasm_cpu_bm,x
        tax                     ; X = (opcode >> 3) + 1 + the offset
        tya
        and #$07
        tay
        lda _bit_tab,y
        and dasm_view_bm-1,x
.else
        tax                     ; X = opcode >> 3
        tya
        and #$07
        tay
        lda _bit_tab,y
        and dasm_view_bm,x
.endif
        bne @in_view
        lda #MNE_UNK
        sta _dasm_midx
        sta _dasm_mode          ; MODE_IMP = 0: length 1, no operand
        jmp finish
@in_view:
        ldy _dasm_opc
@mapped:
.endif
        lda (_dasm_mne),y       ; mnemonic index
        sta _dasm_midx
.ifdef DASM_BYTE_MODES
        inc _dasm_mne+1         ; → the mode bytes (block + 256)
        lda (_dasm_mne),y
.else
        inc _dasm_mne+1         ; → the mode nibbles (block + 256)
        tya
        lsr                     ; C = opcode bit 0
        tay
        lda (_dasm_mne),y
        bcc @even
        lsr
        lsr
        lsr
        lsr
@even:  and #$0F
.endif
        sta _dasm_mode
        ; fall through
.endproc

; ════════════════════════════════════════════════════════════
; finish — print mnemonic + operand, return length
;   _dasm_midx = mnemonic index
;   _dasm_mode = mode index
;   Returns instruction length in A.
; ════════════════════════════════════════════════════════════
.proc finish
        jsr print_mne           ; name (+ digit) + space
        jsr format_operand      ; mode-driven operand output
        ; NUL-terminate
        ldx _dasm_wptr
        lda #0
        sta dasm_buf,x
        ; Return instruction length from mode
        ldx _dasm_mode
        lda dasm_mode_len,x
        rts
.endproc

; ════════════════════════════════════════════════════════════
; print_mne — write the mnemonic (+ bit digit) + space to buffer
; ════════════════════════════════════════════════════════════
.proc print_mne
        lda _dasm_midx
        asl                     ; ×2
        tax
        lda dasm_mne_str,x
        sta _dasm_mne
        lda dasm_mne_str+1,x
        sta _dasm_mne+1

        ; char 1: hi >> 2
        lda _dasm_mne
        lsr
        lsr
        jsr emit_alpha

        ; char 2: ((hi & 3) << 3) | (lo >> 5); hi is dead after char 1,
        ; so it holds the high part.
        lda _dasm_mne
        and #$03
        asl
        asl
        asl                     ; (hi & 3) << 3
        sta _dasm_mne
        lda _dasm_mne+1
        lsr
        lsr
        lsr
        lsr
        lsr                     ; lo >> 5
        ora _dasm_mne
        jsr emit_alpha

        ; char 3: lo & $1F
        lda _dasm_mne+1
        and #$1F
        jsr emit_alpha

.ifdef MNE_DIGIT_LO
        ; bit-digit key: append the opcode's bits 6:4 (RMB3, BBS7)
        lda _dasm_midx
        cmp #MNE_DIGIT_LO
        bcc @space
        cmp #MNE_DIGIT_HI+1
        bcs @space
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        and #$07
        ora #$30                ; '0'..'7'
        jsr buf_putc
@space:
.endif
        lda #$20
        jmp buf_putc
.endproc

; ════════════════════════════════════════════════════════════
; format_operand — write operand based on _dasm_mode
; ════════════════════════════════════════════════════════════
.proc format_operand
        ldx _dasm_mode
        lda dasm_mode_fmt,x
        bne :+
        rts                     ; mode 0 = IMP → nothing
:

        ; Save format byte
        pha

        ; Decode hi nybble (prefix + operand type)
        lsr
        lsr
        lsr
        lsr
        tax                     ; X = hi nybble

        ; Dispatch on hi nybble
        cpx #$06
        beq @acc
        cpx #$07
        beq @rel
        cpx #$08
        beq @zprel

        ; Regular prefixed operand
        ; Emit prefix chars based on hi nybble
        cpx #$04                ; ($+8bit or ($+16bit?
        bcs @paren_prefix
        cpx #$03                ; #$+8bit?
        bcc @dollar
        ; #$ prefix
        lda #$23                ; '#'
        jsr buf_putc
@dollar:
        lda #$24                ; '$'
        jsr buf_putc
        jmp @operand

@paren_prefix:
        lda #$28                ; '('
        jsr buf_putc
        lda #$24                ; '$'
        jsr buf_putc

@operand:
        ; Is operand 16-bit? Hi nybble 2 or 5 = 16-bit
        pla                     ; restore format byte
        pha
        lsr
        lsr
        lsr
        lsr                     ; hi nybble again
        cmp #$02
        beq @op16
        cmp #$05
        beq @op16

        ; 8-bit operand
        ldy #1
        lda _dasm_in,y
        jsr buf_hex2
        jmp @suffix

@op16:  ; 16-bit operand (lo, hi)
        ldy #2
        lda _dasm_in,y          ; hi byte
        jsr buf_hex2
        ldy #1
        lda _dasm_in,y          ; lo byte
        jsr buf_hex2
        jmp @suffix

@acc:   ; Accumulator mode: print 'a'
        lda #$41                ; 'a' PETSCII
        jsr buf_putc
        pla                     ; discard format byte
        rts

@rel:   ; Relative branch: target = PC + 2 + signed offset at op+1.
        ldy #1
        jsr _compute_branch_target
        jmp _emit_target

@zprel: ; ZPREL: $XX,$XXXX (BBR/BBS)
        ; Emit "$XX," for the ZP byte first, then the branch target
        ; from PC+3 + signed offset at op+2.
        lda #$24                ; '$'
        jsr buf_putc
        ldy #1
        lda _dasm_in,y
        jsr buf_hex2
        lda #$2C                ; ','
        jsr buf_putc
        ldy #2
        jsr _compute_branch_target
        jmp _emit_target

@suffix:
        ; Lo nybble of format byte → suffix
        pla                     ; format byte
        and #$0F
        beq @done               ; 0 = no suffix
        cmp #$01
        beq @comma_x
        cmp #$02
        beq @comma_y
        cmp #$03
        beq @close_paren
        cmp #$04
        beq @comma_x_paren
        ; must be 5: ),y
        lda #$29                ; ')'
        jsr buf_putc
        lda #$2C                ; ','
        jsr buf_putc
        lda #$59                ; 'y' PETSCII
        jmp buf_putc

@comma_x:
        lda #$2C
        jsr buf_putc
        lda #$58                ; 'x' PETSCII
        jmp buf_putc

@comma_y:
        lda #$2C
        jsr buf_putc
        lda #$59                ; 'y'
        jmp buf_putc

@close_paren:
        lda #$29                ; ')'
        jmp buf_putc

@comma_x_paren:
        lda #$2C
        jsr buf_putc
        lda #$58                ; 'x'
        jsr buf_putc
        lda #$29                ; ')'
        jmp buf_putc

@done:  rts
.endproc

; ════════════════════════════════════════════════════════════
; Branch-target helpers — shared between format_operand's
; @rel and @zprel paths.  Both compute target = PC + adj +
; signed_offset, where adj = 2 for REL (one-byte operand) or
; 3 for ZPREL (two-byte operand).  Adjustment = Y + 1, so
; callers just pass Y = 1 or 2.
; ════════════════════════════════════════════════════════════

; _emit_target — print "$XXXX" and discard the stacked format byte.
; In: A = target lo, X = target hi.
_emit_target:
        pha
        txa
        pha
        lda #$24                ; '$'
        jsr buf_putc
        pla
        jsr buf_hex2            ; hi
        pla
        jsr buf_hex2            ; lo
        pla                     ; format byte pushed by caller
        rts

.proc _compute_branch_target
        ; In: Y = offset byte index (1 for REL, 2 for ZPREL).
        ; Out: A/X = target = PC + (Y + 1) + sign-extended offset.
        ; No scratch byte: CODE stays read-only (ROM/CRT-ready).
        ldx _dasm_ptr+1         ; user PC hi
        lda _dasm_in,y          ; signed offset (from snapshot)
        bpl :+
        dex                     ; negative: pre-decrement hi
:       tya
        sec                     ; + 1: PC past this insn = Y + 1
        adc _dasm_ptr
        bcc :+
        inx
:       clc
        adc _dasm_in,y          ; + offset
        bcc :+
        inx
:       rts
.endproc

; ════════════════════════════════════════════════════════════
; Buffer write helpers
; ════════════════════════════════════════════════════════════

; emit_alpha: A = 5-bit char code (1-26=A-Z, 27='.'), write PETSCII
.proc emit_alpha
        cmp #27
        beq @dot
        clc
        adc #$40                ; 1→$41='A', etc. (PETSCII uppercase)
        jmp buf_putc
@dot:   lda #$2E                ; '.'
        jmp buf_putc
.endproc

; buf_putc: write A to dasm_buf at current position, advance
.proc buf_putc
        ldx _dasm_wptr
        sta dasm_buf,x
        inc _dasm_wptr
        rts
.endproc

; buf_hex2: write A as 2 hex digits to buffer
.proc buf_hex2
        pha
        lsr
        lsr
        lsr
        lsr
        jsr @nybble
        pla
        and #$0F
@nybble:
        cmp #$0A
        bcc @digit
        adc #$06                ; carry set from bcc: A + 7 = $41+'a'-10
@digit: adc #$30                ; '0'
        jmp buf_putc
.endproc


.segment "RODATA"

.ifdef DASM_SUBSET
; Bit masks for an opcode's bit within its bitmap byte (opcode & 7).
_bit_tab:
        .byte $01, $02, $04, $08, $10, $20, $40, $80
.endif
