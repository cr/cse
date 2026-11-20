; dasm.s — table-driven disassembler (6502 / 6510 / 4510 / 45GS02; the
; CMOS mode's 65C02)
; Owner: doc/modules/dasm.md
;
; Interface:
;   dasm_insn (A/X = addr lo/hi)
;     Output: NUL-terminated PETSCII string in dasm_buf
;     Returns instruction length in A (1 to INSN_MAX: 3, m65 5)
;
; CPU view: asm_cpu (build_system.md § Builds and CPU sets) selects one of
; the build's CPU views.  Every opcode fact comes from the generated
; dasm_tables.s (one block per CPU set); this file holds none:
;
;   dasm_cpu_map_lo/hi[asm_cpu]  → the view's map block:
;       +0    256 B  mnemonic index per opcode (0 = MNE_UNK, "...")
;       +256  128 B  mode per opcode, two 4-bit modes per byte (even = low;
;                    m65: one byte per opcode, 256 B — DASM_BYTE_MODES)
;   DASM_SUBSET_CPU              → the asm_cpu whose view is the subset
;       bitmap dasm_view_bm over its map (sets with one only); an opcode
;       outside it lists as "..."
;   dasm_mode_len / dasm_mode_fmt[mode]  → length and operand format
;   dasm_mne_str[index]          → 3 chars packed into 2 bytes (5 bits/char)
;
; A bit-digit key (MNE_DIGIT_LO..HI) is listed with the opcode's bits 6:4
; as its digit (RMB3).

        .include "platform.inc"
        .include "dasm_mne_idx.s"   ; MNE_UNK, MNE_DIGIT_*, DASM_SUBSET_CPU,
                                    ; DASM_BYTE_MODES, MNE_QSFX_*, MNE_QNAME_*
        .include "cpu_set.inc"      ; MODE_*, ASM_CPU_*, INSN_MAX

        .export dasm_insn, dasm_insn_pre, _dasm_in
.ifdef MEGA_SUPPORT
        .export _dasm_pfx               ; the debugger's step reads it
.endif
        .export dasm_buf

        .importzp asm_cpu
        .import dasm_mne_str, dasm_mode_len, dasm_mode_fmt
        .import dasm_cpu_map_lo, dasm_cpu_map_hi
.ifdef DASM_SUBSET_CPU
        .import dasm_view_bm
.endif
.ifdef MEGA_SUPPORT
        .import dasm_q_map
PFX_Q     = %00000001           ; _dasm_pfx: $42 $42 peeled
PFX_FAR   = %00000010           ;            $EA peeled: [ ] for ( )
PFX_ASZPI = %00000100           ;            ZPIZ printed ($nn): a Q-map 2 form
.endif
        .import kernal_bank_out, kernal_bank_in

; ── ZP usage ─────────────────────────────────────────────
.importzp _dasm_ptr, _dasm_mne, _dasm_wptr, _dasm_midx, _dasm_mode

; ── BSS ──────────────────────────────────────────────────
.segment "BSS"
dasm_buf:      .res 24         ; output buffer (NUL-terminated PETSCII)
_dasm_in:      .res INSN_MAX ; input snapshot (the longest insn) read from
                               ; the user's address with the caller's bank
                               ; state still in force, so KERNAL ROM at
                               ; $E000+ is captured BEFORE dasm_insn banks
                               ; out for its internal table reads.  See the
                               ; rationale in dasm_insn's docstring.
.ifdef MEGA_SUPPORT
_dasm_pfx:     .res 1          ; the peeled prefixes (PFX_*), dasm.md § Prefix peel
.endif

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
; KERNAL-ROM read fix: snapshot the longest instruction's bytes
; (INSN_MAX) from the user's address into _dasm_in BEFORE banking out — otherwise
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
.ifdef MEGA_SUPPORT
        pha                     ; FAR_USER may rewrite the offset (the
        txa                     ; I/O row): keep the user address
        pha
        FAR_USER _dasm_ptr
.endif
        ; Snapshot the bytes from the user address while the caller's
        ; bank state is still in force.
        ldy #INSN_MAX - 1
@cp:    FAR_LDA _dasm_ptr
        sta _dasm_in,y
        dey
        bpl @cp
.ifdef MEGA_SUPPORT
        pla                     ; _dasm_ptr = the user address again:
        sta _dasm_ptr+1         ; format_operand's branch targets
        pla
        sta _dasm_ptr
.endif
; dasm_insn_pre — entry for a caller that has filled _dasm_in (INSN_MAX B)
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
.ifdef MEGA_SUPPORT
        lda #0
        sta _dasm_pfx
        cpx #ASM_CPU_45GS02     ; peel its prefixes
        bne :+
        jsr _dasm_peel
        ldx asm_cpu
:
.endif
        ldy _dasm_in            ; the opcode (after the peel)

.ifdef DASM_SUBSET_CPU
        ; The subset view: an opcode outside its bitmap lists as "...".
        cpx #DASM_SUBSET_CPU
        bne @mapped
        tya
        lsr
        lsr
        lsr
        tax                     ; X = opcode >> 3
        tya
        and #$07
        tay
        lda _bit_tab,y
        and dasm_view_bm,x
        bne @in_view
        lda #MNE_UNK
        sta _dasm_midx
        sta _dasm_mode          ; MODE_IMP = 0: length 1, no operand
        jmp finish
@in_view:
        ldy _dasm_in
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
.ifdef MEGA_SUPPORT
        lda _dasm_pfx           ; + the prefixes' length: Q 2, far 1
        and #PFX_Q | PFX_FAR
        tay
        lda dasm_mode_len,x
        clc
        adc @pfx_len,y
        rts
@pfx_len: .byte 0, 2, 1, 3
.else
        lda dasm_mode_len,x
        rts
.endif
.endproc

; ════════════════════════════════════════════════════════════
; print_mne — write the mnemonic (+ bit digit) + space to buffer
; ════════════════════════════════════════════════════════════
.proc print_mne
        lda _dasm_midx
.ifdef MEGA_SUPPORT
        ; Under a Q prefix a Q-name stem (LDA STA ORA DEC INC) lists by the
        ; name after it (ldq) — dasm.md § Design, *Mnemonic strings*.
        tay
        lda _dasm_pfx
        and #PFX_Q
        beq :+
        cpy #MNE_QNAME_LO
        bcc :+
        cpy #MNE_QNAME_HI + 1
        bcs :+
        iny
:       tya
.endif
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
        lda _dasm_in
        lsr
        lsr
        lsr
        lsr
        and #$07
        ora #$30                ; '0'..'7'
        jsr buf_putc
@space:
.endif
.ifdef MEGA_SUPPORT
        ; Under a Q prefix a Q-suffix stem lists with its `q` (adcq).
        lda _dasm_pfx
        and #PFX_Q
        beq @sp
        lda _dasm_midx
        cmp #MNE_QSFX_LO
        bcc @sp
        cmp #MNE_QSFX_HI + 1
        bcs @sp
        lda #$51                ; 'Q'
        jsr buf_putc
@sp:
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
.ifdef MEGA_SUPPORT
        cpx #$0A
        beq @rel16
        cpx #$09
        beq @hash               ; IMM16: '#$' and 16 bits
.endif

        ; Regular prefixed operand
        ; Emit prefix chars based on hi nybble
        cpx #$04                ; ($+8bit or ($+16bit?
        bcs @paren_prefix
        cpx #$03                ; #$+8bit?
        bcc @dollar
@hash:  ; #$ prefix
        lda #$23                ; '#'
        jsr buf_putc
@dollar:
        lda #$24                ; '$'
        jsr buf_putc
        jmp @operand

@paren_prefix:
.ifdef MEGA_SUPPORT
        jsr _dasm_open          ; '(' or, far, '['
.else
        lda #$28                ; '('
        jsr buf_putc
.endif
        lda #$24                ; '$'
        jsr buf_putc

@operand:
        ; Is operand 16-bit? Hi nybble 2 or 5 (m65 also 9, IMM16)
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
.ifdef MEGA_SUPPORT
        cmp #$09
        beq @op16
.endif

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

@acc:   ; Accumulator mode: print 'a' (m65: bare — after a Q form `a`
        ; would read back as a label; asm_line.md § Mnemonic word)
.ifndef MEGA_SUPPORT
        lda #$41                ; 'a' PETSCII
        jsr buf_putc
.endif
        pla                     ; discard format byte
        rts

@rel:   ; Relative branch: target = PC + 2 + signed offset at op+1.
        ldy #1
        jsr _compute_branch_target
        jmp _emit_target

.ifdef MEGA_SUPPORT
@rel16: ; REL16: target = the instruction's last byte (PC + 2) + offset16
        clc
        lda _dasm_ptr
        adc _dasm_in+1
        tay
        lda _dasm_ptr+1
        adc _dasm_in+2
        tax
        tya
        clc
        adc #2
        bcc :+
        inx
:       jmp _emit_target
.endif

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
.ifdef MEGA_SUPPORT
        cmp #$06
        beq @paren_z
        cmp #$07                ; 7: ,sp),y
        bne :+
        lda #$2C                ; ','
        jsr buf_putc
        lda #$53                ; 's'
        jsr buf_putc
        lda #$50                ; 'p'
        jsr buf_putc
:
.endif
        ; 5 (m65 also 7): ),y
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
.ifdef MEGA_SUPPORT
        jmp _dasm_close         ; ')' or, far, ']'

@paren_z:                       ; ),z — or ($nn) for a Q-map 2 form
        jsr _dasm_close         ;   (dasm.md § Design)
        lda _dasm_pfx
        and #PFX_ASZPI
        bne @done
        lda #$2C                ; ','
        jsr buf_putc
        lda #$5A                ; 'z'
        jmp buf_putc
.else
        lda #$29                ; ')'
        jmp buf_putc
.endif

@comma_x_paren:
        lda #$2C
        jsr buf_putc
        lda #$58                ; 'x'
        jsr buf_putc
        lda #$29                ; ')'
        jmp buf_putc

@done:  rts
.endproc

.ifdef MEGA_SUPPORT
; ════════════════════════════════════════════════════════════
; _dasm_peel — the 45GS02's prefixes (dasm.md § Prefix peel), asm_cpu 4:
;   $42 $42 op      Q, when op has a Q form
;   $42 $42 $EA op  Q + far, when op is far-capable with a Q form
;   $EA op          far, when op is far-capable (its mode ZPIZ)
; The snapshot is shifted left by the prefixes' length; _dasm_pfx says
; which.  In: _dasm_mne = the map block.  Clobbers A, X, Y.
; ════════════════════════════════════════════════════════════
.proc _dasm_peel
        lda _dasm_in
        cmp #$EA
        beq @far
        cmp #$42
        bne @none
        cmp _dasm_in+1
        bne @none
        ldy _dasm_in+2
        cpy #$EA
        bne @q
        ldy _dasm_in+3          ; $42 $42 $EA op
        jsr @farcap
        bne @none
        jsr @qform
        beq @none
        cmp #2
        lda #PFX_Q | PFX_FAR
        ldx #3
        bne @qpfx
@q:     jsr @qform              ; $42 $42 op
        beq @none
        cmp #2                  ; C = 1: Q map 2, its ZPIZ written ($nn)
        lda #PFX_Q
        ldx #2
@qpfx:  bcc @shift
        ora #PFX_ASZPI
        bne @shift
@far:   ldy _dasm_in+1          ; $EA op
        jsr @farcap
        bne @none
        lda #PFX_FAR
        ldx #1
@shift: sta _dasm_pfx
        ldy #0
:       lda _dasm_in,x
        sta _dasm_in,y
        iny
        inx
        cpx #INSN_MAX
        bcc :-
@none:  rts

; @qform — A = the Q-map value of opcode Y (0 none, 1, 2); Z = 1: none.
@qform: tya
        lsr
        lsr
        tax
        tya
        and #3
        tay
        lda dasm_q_map,x
:       dey
        bmi :+
        lsr
        lsr
        bpl :-                  ; (always)
:       and #3
        rts

; @farcap — Z = 1 when opcode Y's mode in the map is ZPIZ (far-capable).
@farcap:
        inc _dasm_mne+1         ; the mode bytes (block + 256)
        lda (_dasm_mne),y
        dec _dasm_mne+1
        cmp #MODE_ZPIZ
        rts
.endproc

; _dasm_open / _dasm_close — '(' / ')', or '[' / ']' under a far prefix
_dasm_open:
        lda _dasm_pfx
        and #PFX_FAR
        beq :+
        lda #$5B                ; '['
        jmp buf_putc
:       lda #$28                ; '('
        jmp buf_putc
_dasm_close:
        lda _dasm_pfx
        and #PFX_FAR
        beq :+
        lda #$5D                ; ']'
        jmp buf_putc
:       lda #$29                ; ')'
        jmp buf_putc
.endif

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

.ifdef DASM_SUBSET_CPU
; Bit masks for an opcode's bit within its bitmap byte (opcode & 7).
_bit_tab:
        .byte $01, $02, $04, $08, $10, $20, $40, $80
.endif
