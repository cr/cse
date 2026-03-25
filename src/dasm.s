; dasm.s — Bit-slice 6502/6510/65C02 disassembler
;
; Interface:
;   _dasm_insn (A/X = addr lo/hi, __fastcall__)
;     Output: NUL-terminated PETSCII string in dasm_buf
;     Returns instruction length in A (1-3)
;
; CPU mode: al_cpu  0=6502(legal only)  1=6510(+illegal)  2=65C02(+cmos)
;
; Design: aaabbbcc bit-slice decode.  No 256-entry tables.
;   cc=01: fully regular (8-entry mne + 8-entry mode)
;   cc=10: semi-regular (aaa→mne for odd bbb, per-CPU for even bbb)
;   cc=00: branches + implied + memory subgroups
;   cc=11: CPU-dependent (6502→???, 6510→illegals, 65C02→RMB/SMB/BBR/BBS)
;
; Mnemonic packing: 3 chars in 2 bytes (5 bits/char, A=1..Z=26, ?=27)
; Mode format byte: hi nybble=prefix+size, lo nybble=suffix
;   Instruction length derived from mode.

        .export _dasm_insn
        .export _dasm_buf

        .importzp al_cpu
        .import dasm_mne_str

; ── ZP usage ─────────────────────────────────────────────
.segment "ZEROPAGE"
_dasm_ptr:      .res 2          ; instruction address
_dasm_opc:      .res 1          ; saved opcode byte
_dasm_mne:      .res 2          ; packed mnemonic (2 bytes)
_dasm_wptr:     .res 1          ; write index into dasm_buf

; ── BSS ──────────────────────────────────────────────────
.segment "BSS"
_dasm_buf:      .res 24         ; output buffer (NUL-terminated PETSCII)

; ── CODE ─────────────────────────────────────────────────
.segment "CODE"

; ════════════════════════════════════════════════════════════
; Entry point: _dasm_insn
;   A = addr lo, X = addr hi (__fastcall__)
;   Returns length in A.  dasm_buf filled with PETSCII + NUL.
; ════════════════════════════════════════════════════════════
.proc _dasm_insn
        sta _dasm_ptr
        stx _dasm_ptr+1
        lda #0
        sta _dasm_wptr          ; reset buffer write position

        ; Read opcode
        ldy #0
        lda (_dasm_ptr),y
        sta _dasm_opc

        ; Extract cc = opcode & 3
        and #$03
        beq @cc00
        cmp #$01
        beq @cc01
        cmp #$02
        beq @cc10
        jmp decode_cc11         ; cc=3

@cc00:  jmp decode_cc00
@cc01:  jmp decode_cc01
@cc10:  jmp decode_cc10
.endproc

; ════════════════════════════════════════════════════════════
; emit_mne_mode — write mnemonic + operand to buffer
;   X = mnemonic index, Y = mode index
;   Returns instruction length in A.
; ════════════════════════════════════════════════════════════
.proc emit_mne_mode
        ; Load packed mnemonic string
        txa
        asl                     ; ×2 for table index
        tax
        lda dasm_mne_str,x
        sta _dasm_mne
        lda dasm_mne_str+1,x
        sta _dasm_mne+1

        ; Unpack char 1: bits 14-10 = hi >> 2
        lda _dasm_mne
        lsr
        lsr
        jsr emit_alpha

        ; Unpack char 2: ((hi & 3) << 3) | (lo >> 5)
        lda _dasm_mne+1
        pha                     ; save lo for char 3
        lsr
        lsr
        lsr
        lsr
        lsr                     ; lo >> 5
        sta _dasm_opc           ; borrow _dasm_opc as temp
        lda _dasm_mne
        and #$03
        asl
        asl
        asl                     ; (hi & 3) << 3
        ora _dasm_opc           ; combine
        jsr emit_alpha

        ; Unpack char 3: lo & $1F
        pla                     ; restore lo
        and #$1F
        jsr emit_alpha

        ; Space after mnemonic
        lda #$20                ; PETSCII space
        jsr buf_putc

        ; Restore opcode (was borrowed as temp)
        ldy #0
        lda (_dasm_ptr),y
        sta _dasm_opc

        ; Format operand based on mode (Y = mode index, set by caller)
        ; Caller left mode in Y before calling emit_mne_mode?
        ; Actually we need to pass mode. Let's use the stack.
        ; Rethink: caller pushes mode, we pop it.
        ; Simpler: store mode in _dasm_opc area... no, we need _dasm_opc.
        ; Let's have caller store mode in X before calling.
        ; Wait — we clobbered X for the mne lookup. Let's have the
        ; caller put mode on the stack or in a temp.
        ;
        ; NEW CONVENTION: caller stores mode in Y before call.
        ; We need to preserve Y across the mnemonic print.
        ; Save Y at entry, restore here.
        ;
        ; ACTUALLY: let's restructure. The caller sets _dasm_mode
        ; before calling, or we take X=mne, Y=mode and save Y first.

        ; This is getting tangled. Let me restructure.
        rts
.endproc

; Let me restructure: separate mnemonic print from mode print.
; The top-level decode stores mne_idx and mode_idx in ZP,
; then calls print_mne, then format_operand.

.segment "ZEROPAGE"
_dasm_midx:     .res 1          ; mnemonic index
_dasm_mode:     .res 1          ; mode index

.segment "CODE"

; ════════════════════════════════════════════════════════════
; finish — print mnemonic + operand, return length
;   _dasm_midx = mnemonic index
;   _dasm_mode = mode index
;   Returns instruction length in A.
; ════════════════════════════════════════════════════════════
.proc finish
        jsr print_mne           ; 3 chars + space
        jsr format_operand      ; mode-driven operand output
        ; NUL-terminate
        ldx _dasm_wptr
        lda #0
        sta _dasm_buf,x
        ; Return instruction length from mode
        ldx _dasm_mode
        lda mode_len,x
        rts
.endproc

; ════════════════════════════════════════════════════════════
; print_mne — write 3-char mnemonic + space to buffer
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

        ; char 2: ((hi & 3) << 3) | (lo >> 5)
        lda _dasm_mne
        and #$03
        asl
        asl
        asl                     ; (hi & 3) << 3
        sta _dasm_opc           ; borrow as temp
        lda _dasm_mne+1
        lsr
        lsr
        lsr
        lsr
        lsr                     ; lo >> 5
        ora _dasm_opc           ; combine
        jsr emit_alpha

        ; char 3: lo & $1F
        lda _dasm_mne+1
        and #$1F
        jsr emit_alpha

        ; space
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
        lda (_dasm_ptr),y
        jsr buf_hex2
        jmp @suffix

@op16:  ; 16-bit operand (lo, hi)
        ldy #2
        lda (_dasm_ptr),y       ; hi byte
        jsr buf_hex2
        ldy #1
        lda (_dasm_ptr),y       ; lo byte
        jsr buf_hex2
        jmp @suffix

@acc:   ; Accumulator mode: print 'a'
        lda #$41                ; 'a' PETSCII
        jsr buf_putc
        pla                     ; discard format byte
        rts

@rel:   ; Relative branch: compute PC + 2 + signed offset
        ldy #1
        lda (_dasm_ptr),y       ; signed offset
        ; target = PC + 2 + signed_offset
        ; sign-extend: if offset negative, pre-decrement hi byte
        ldx _dasm_ptr+1
        tay                     ; save offset in Y
        bpl :+                  ; positive offset: skip
        dex                     ; negative: pre-decrement hi
:       tya                     ; restore offset
        clc
        adc _dasm_ptr           ; + PC lo
        bcc :+
        inx                     ; carry into hi
:       clc
        adc #2                  ; + 2
        bcc :+
        inx
:       ; now A = target lo, X = target hi
        pha                     ; save target lo
        txa
        pha                     ; save target hi
        lda #$24                ; '$'
        jsr buf_putc
        pla                     ; target hi
        jsr buf_hex2
        pla                     ; target lo
        jsr buf_hex2
        pla                     ; discard format byte from stack
        rts

@zprel: ; ZPREL: $XX,$XXXX (BBR/BBS)
        lda #$24                ; '$'
        jsr buf_putc
        ldy #1
        lda (_dasm_ptr),y       ; ZP byte
        jsr buf_hex2
        lda #$2C                ; ','
        jsr buf_putc
        ; Now relative branch from PC+3 (signed offset)
        ldy #2
        lda (_dasm_ptr),y       ; signed offset
        ldx _dasm_ptr+1
        tay
        bpl :+
        dex                     ; negative: pre-decrement hi
:       tya
        clc
        adc _dasm_ptr
        bcc :+
        inx
:       clc
        adc #3                  ; PC+3 for ZPREL
        bcc :+
        inx
:       pha                     ; save target lo
        txa
        pha                     ; save target hi
        lda #$24                ; '$'
        jsr buf_putc
        pla                     ; target hi
        jsr buf_hex2
        pla                     ; target lo
        jsr buf_hex2
        pla                     ; discard format byte
        rts

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
; Relative branch helper for signed offset
; (already handled inline in format_operand)
; ════════════════════════════════════════════════════════════

; ════════════════════════════════════════════════════════════
; Buffer write helpers
; ════════════════════════════════════════════════════════════

; emit_alpha: A = 5-bit char code (1-26=A-Z, 27='?'), write PETSCII
.proc emit_alpha
        cmp #27
        beq @qmark
        clc
        adc #$40                ; 1→$41='A', etc. (PETSCII uppercase)
        jmp buf_putc
@qmark: lda #$3F                ; '?'
        jmp buf_putc
.endproc

; buf_putc: write A to dasm_buf at current position, advance
.proc buf_putc
        ldx _dasm_wptr
        sta _dasm_buf,x
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

; ════════════════════════════════════════════════════════════
; GROUP DECODERS
; ════════════════════════════════════════════════════════════

; ── cc=01: fully regular ─────────────────────────────────
.proc decode_cc01
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        lda g1_mne,x
        sta _dasm_midx

        lda _dasm_opc
        lsr
        lsr
        and #$07                ; bbb
        tax
        lda g1_mode,x
        sta _dasm_mode

        ; Exception: $89 = BIT #imm on 65C02, ??? on NMOS
        lda _dasm_opc
        cmp #$89
        bne @go
        lda al_cpu
        cmp #2
        bne @unk89
        lda #MNE_BIT
        sta _dasm_midx
        jmp finish
@unk89: lda #MNE_UNK
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
@go:    jmp finish
.endproc

; ── cc=10: semi-regular ──────────────────────────────────
.proc decode_cc10
        lda _dasm_opc
        lsr
        lsr
        and #$07                ; bbb
        cmp #$01
        beq @bbb1
        cmp #$03
        beq @bbb3
        cmp #$05
        beq @bbb5
        cmp #$07
        beq @bbb7

        ; Even bbb (0,2,4,6) — irregular, handle per-CPU
        jmp decode_cc10_even

@bbb1:  ; ZP mode
        lda #MODE_ZP
        jmp @regular
@bbb3:  ; ABS mode
        lda #MODE_ABS
        jmp @regular
@bbb5:  ; ZPX (or ZPY for STX/LDX)
        lda _dasm_opc
        and #$E0
        cmp #$80                ; aaa=4 (STX)?
        beq @zpy
        cmp #$A0                ; aaa=5 (LDX)?
        beq @zpy
        lda #MODE_ZPX
        jmp @regular
@zpy:   lda #MODE_ZPY
        jmp @regular
@bbb7:  ; ABX (or ABY for LDX, SXA on NMOS)
        lda _dasm_opc
        and #$E0
        cmp #$A0                ; aaa=5 (LDX)?
        beq @aby7
        ; Check $9E: SXA/SHX on 6510, STZ ABX on 65C02, ??? on 6502
        lda _dasm_opc
        cmp #$9E
        bne @abx7
        lda al_cpu
        cmp #1
        bne :+
        ; 6510: SXA ABY
        lda #MNE_SXA
        sta _dasm_midx
        lda #MODE_ABY
        sta _dasm_mode
        jmp finish
:       cmp #2
        bne @to_unk             ; 6502: ???
        ; 65C02: STZ ABX
        lda #MNE_STZ
        sta _dasm_midx
        lda #MODE_ABX
        sta _dasm_mode
        jmp finish
@to_unk:
        lda #MNE_UNK
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish
@aby7:  lda #MODE_ABY
        jmp @regular
@abx7:  lda #MODE_ABX

@regular:
        sta _dasm_mode
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        lda g2_mne,x
        sta _dasm_midx
        jmp finish
.endproc

; ── cc=10 even bbb (0,2,4,6) ────────────────────────────
.proc decode_cc10_even
        lda _dasm_opc
        lsr
        lsr
        and #$07                ; bbb
        cmp #$02
        beq @bbb2
        cmp #$04
        bne :+
        jmp @bbb4
:       cmp #$06
        bne :+
        jmp @bbb6
:

        ; bbb=0: almost all unknown
        ; Only $A2 = LDX #imm (legal), $02 = KIL (6510)
        lda _dasm_opc
        cmp #$A2
        beq @ldx_imm
        ; 6510: $02 = KIL
        lda al_cpu
        cmp #1
        beq :+
        jmp @unk
:       lda _dasm_opc
        cmp #$02
        beq :+
        jmp @unk
:       lda #MNE_KIL
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish

@ldx_imm:
        lda #MNE_LDX
        sta _dasm_midx
        lda #MODE_IMM
        sta _dasm_mode
        jmp finish

@bbb2:  ; Accumulator / implied column
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        lda g2b2_mne,x
        sta _dasm_midx
        lda g2b2_mode,x
        sta _dasm_mode
        ; 65C02 overrides: $1A=INC A, $3A=DEC A
        lda al_cpu
        cmp #2
        bne @b2go
        lda _dasm_opc
        cmp #$1A
        bne :+
        lda #MNE_INC
        sta _dasm_midx
        lda #MODE_ACC
        sta _dasm_mode
:       lda _dasm_opc
        cmp #$3A
        bne @b2go
        lda #MNE_DEC
        sta _dasm_midx
        lda #MODE_ACC
        sta _dasm_mode
@b2go:  jmp finish

@bbb4:  ; 65C02: ZPI. 6510: $D2=CIM
        lda al_cpu
        cmp #2
        beq @bbb4_cmos
        ; 6510: check for $D2=CIM
        cmp #1
        bne @unk
        lda _dasm_opc
        cmp #$D2
        bne @unk
        lda #MNE_CIM
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish
@bbb4_cmos:
        ; aaa selects same mnemonic as cc=01 (ORA,AND,EOR,ADC,STA,LDA,CMP,SBC)
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        lda g1_mne,x            ; reuse cc=01 table!
        sta _dasm_midx
        lda #MODE_ZPI
        sta _dasm_mode
        ; Exception: $D2 on some 65C02s is CMP(zp), but our table
        ; has it right since g1_mne[6]=CMP
        jmp finish

@bbb6:  ; Per-CPU implied column
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        ; Check al_cpu for CMOS extras
        lda al_cpu
        cmp #2
        beq @b6_cmos
        ; NMOS/6502: only TXS($9A) and TSX($BA) are legal
        lda g2b6_mne_nmos,x
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        ; Check if this CPU supports it
        lda al_cpu
        bne @b6go               ; 6510: all entries valid
        ; 6502: check if ??? (illegal NOP variants)
        lda _dasm_midx
        cmp #MNE_UNK
        bne @b6go
        jmp finish
@b6go:  jmp finish

@b6_cmos:
        lda g2b6_mne_cmos,x
        sta _dasm_midx
        ; INC/DEC use ACC mode, rest use IMP
        cmp #MNE_INC
        beq @b6_acc
        cmp #MNE_DEC
        beq @b6_acc
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish
@b6_acc:
        lda #MODE_ACC
        sta _dasm_mode
        jmp finish

@unk:   lda #MNE_UNK
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish
.endproc

; ── cc=00: branches + implied + memory ───────────────────
.proc decode_cc00
        ; Check for branch: (opcode & $1F) == $10
        lda _dasm_opc
        and #$1F
        cmp #$10
        beq @branch

        ; Extract bbb
        lda _dasm_opc
        lsr
        lsr
        and #$07
        cmp #$02
        beq @impl2
        cmp #$06
        beq @impl6

        ; Memory operations (bbb=0,1,3,5,7)
        jmp decode_cc00_mem

@branch:
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        lda g0_br_mne,x
        sta _dasm_midx
        lda #MODE_REL
        sta _dasm_mode
        ; Exception: $80 = BRA on 65C02, SKB on 6510
        lda _dasm_opc
        cmp #$80
        bne @brgo
        lda al_cpu
        cmp #2
        beq @bra
        cmp #1
        bne :+
        ; 6510: $80 = SKB #imm
        lda #MNE_SKB
        sta _dasm_midx
        lda #MODE_IMM
        sta _dasm_mode
        jmp finish
:
        ; 6502: ??? (not a valid branch)
        lda #MNE_UNK
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
@brgo:  jmp finish

@bra:   lda #MNE_BRA
        sta _dasm_midx
        jmp finish

@impl2:
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        lda g0_i2_mne,x
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish

@impl6:
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        lda g0_i6_mne,x
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish
.endproc

; ── cc=00 memory operations (bbb=0,1,3,5,7) ─────────────
.proc decode_cc00_mem
        lda _dasm_opc
        lsr
        lsr
        and #$07                ; bbb
        sta _dasm_mode           ; temp: bbb

        ; aaa
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr
        tax                     ; X = aaa

        ; aaa >= 4: regular family (STY/LDY/CPY/CPX)
        cpx #4
        bcs @family

        ; aaa 0-3: specials per bbb
        lda _dasm_mode          ; bbb
        cmp #0
        bne :+
        jmp @bbb0_low
:
        cmp #1
        bne :+
        jmp @bbb1_low
:       cmp #3
        bne :+
        jmp @bbb3_low
:       ; bbb=5 or 7, aaa<4: check CPU-specific opcodes
        jmp @bbb57_low

@family:
        ; aaa 4-7 → STY(4), LDY(5), CPY(6), CPX(7)
        lda g0_fam_mne-4,x     ; table indexed from aaa=4
        sta _dasm_midx

        ; Mode from bbb: 0→IMM, 1→ZP, 3→ABS, 5→ZPX, 7→ABX
        lda _dasm_mode          ; bbb
        tax
        lda g0_fam_mode,x       ; bbb→mode (8-entry, 2/4/6 unused)
        sta _dasm_mode

        ; Validity checks for cc=00 family modes
        lda _dasm_mode
        cmp #MODE_ZPX
        beq @fam_zpx
        cmp #MODE_ABX
        beq @fam_abx
        ; IMM/ZP/ABS: STY has no IMM.
        ; $80 (aaa=4, bbb=0, IMM slot) = SKB(6510) / BRA(65C02) / ???(6502)
        lda _dasm_midx
        cmp #MNE_STY
        bne @famgo
        lda _dasm_mode
        cmp #MODE_IMM
        bne @famgo
        lda al_cpu
        cmp #2
        bne :+
        lda #MNE_BRA
        sta _dasm_midx
        lda #MODE_REL
        sta _dasm_mode
        jmp finish
:       cmp #1
        bne :+
        lda #MNE_SKB
        sta _dasm_midx
        jmp finish              ; keep IMM mode
:       jmp @unk

@fam_zpx:
        ; ZPX valid only for STY and LDY
        lda _dasm_midx
        cmp #MNE_STY
        beq @famgo
        cmp #MNE_LDY
        beq @famgo
        jmp @unk                ; CPY/CPX have no ZPX

@fam_abx:
        ; ABX: only LDY has it. STY→??? or CPU override.
        ; $9C (aaa=4, bbb=7): STY ABX slot
        ; $BC (aaa=5, bbb=7): LDY ABX — valid
        lda _dasm_midx
        cmp #MNE_LDY
        beq @famgo
        cmp #MNE_STY
        bne @fam_abx_unk
        ; $9C: STZ ABS on 65C02, SYA ABX on 6510
        lda al_cpu
        cmp #2
        bne :+
        lda #MNE_STZ
        sta _dasm_midx
        lda #MODE_ABS           ; STZ ABS (not ABX)
        sta _dasm_mode
        jmp finish
:       cmp #1
        bne @fam_abx_unk
        lda #MNE_SYA
        sta _dasm_midx
        ; keep ABX mode
        jmp finish
@fam_abx_unk:
        jmp @unk                ; CPY/CPX have no ABX

@famgo: jmp finish

@bbb0_low:
        ; aaa 0-3: BRK($00), JSR($20), RTI($40), RTS($60)
        lda g0b0_mne,x
        sta _dasm_midx
        lda g0b0_mode,x
        sta _dasm_mode
        jmp finish

@bbb1_low:
        ; aaa 0-3: varies by CPU
        ; NMOS: IGN($04), BIT($24), ???($44), ???($64)
        ; 6510: IGN($04), BIT($24), IGN($44), ???($64)
        ; CMOS: TSB($04), BIT($24), ???($44), STZ($64)
        lda al_cpu
        cmp #2
        beq @b1_cmos
        ; NMOS/6502
        cpx #1                  ; aaa=1: BIT
        beq @bit_zp
        lda al_cpu
        cmp #1
        beq :+
        jmp @unk
:
        ; 6510: $04=IGN only
        cpx #0
        beq @ign_zp
        jmp @unk

@b1_cmos:
        cpx #0                  ; TSB
        beq @tsb_zp
        cpx #1                  ; BIT
        beq @bit_zp
        cpx #3                  ; STZ
        beq @stz_zp
        jmp @unk

@bit_zp:
        lda #MNE_BIT
        sta _dasm_midx
        lda #MODE_ZP
        sta _dasm_mode
        jmp finish
@ign_zp:
        lda #MNE_IGN
        sta _dasm_midx
        lda #MODE_ZP
        sta _dasm_mode
        jmp finish
@tsb_zp:
        lda #MNE_TSB
        sta _dasm_midx
        lda #MODE_ZP
        sta _dasm_mode
        jmp finish
@stz_zp:
        lda #MNE_STZ
        sta _dasm_midx
        lda #MODE_ZP
        sta _dasm_mode
        jmp finish

@bbb3_low:
        ; aaa 0-1: TOP/TSB ABS, BIT ABS
        ; aaa 2: JMP ABS ($4C)
        ; aaa 3: JMP IND ($6C) or JMP AIX ($7C on 65C02)
        cpx #2
        beq @jmp_abs
        cpx #3
        beq @jmp_ind
        cpx #1
        beq @bit_abs
        ; aaa=0: TOP(nmos) or TSB(cmos)
        lda al_cpu
        cmp #2
        bne :+
        jmp @tsb_abs
:
        cmp #1
        beq :+
        jmp @unk
:       ; 6510: TOP
        lda #MNE_TOP
        sta _dasm_midx
        lda #MODE_ABS
        sta _dasm_mode
        jmp finish

@jmp_abs:
        lda #MNE_JMP
        sta _dasm_midx
        lda #MODE_ABS
        sta _dasm_mode
        jmp finish
@jmp_ind:
        lda #MNE_JMP
        sta _dasm_midx
        lda #MODE_IND
        sta _dasm_mode
        jmp finish
@bit_abs:
        lda #MNE_BIT
        sta _dasm_midx
        lda #MODE_ABS
        sta _dasm_mode
        jmp finish
@tsb_abs:
        lda #MNE_TSB
        sta _dasm_midx
        lda #MODE_ABS
        sta _dasm_mode
        jmp finish

; ── cc=00 bbb=5/7, aaa<4: CPU-specific opcodes ──────────
@bbb57_low:
        ; X = aaa (0-3), _dasm_mode has bbb (5 or 7)
        lda al_cpu
        cmp #2
        bne :+
        jmp @b57_cmos
:       cmp #1
        beq @b57_nmos
        jmp @unk                ; 6502 legal: all ???

@b57_nmos:
        lda _dasm_mode          ; bbb
        cmp #5
        bne @b57n_7
        cpx #0                  ; $14=IGN ZPX
        beq :+
        jmp @unk
:       lda #MNE_IGN
        sta _dasm_midx
        lda #MODE_ZPX
        sta _dasm_mode
        jmp finish
@b57n_7:
        cpx #0                  ; $1C=TOP ABX
        bne @unk
        lda #MNE_TOP
        sta _dasm_midx
        lda #MODE_ABX
        sta _dasm_mode
        jmp finish

@b57_cmos:
        lda _dasm_mode          ; bbb
        cmp #5
        bne @b57c_7
        ; bbb=5 (ZPX): aaa 0=TRB, 1=BIT, 3=STZ
        cpx #0
        beq @trb_zpc
        cpx #1
        beq @bit_zpx
        cpx #3
        beq @stz_zpx
        jmp @unk
@b57c_7:
        ; bbb=7: aaa 0=TRB ABS, 1=BIT ABX, 3=JMP AIX
        cpx #0
        beq @trb_absc
        cpx #1
        beq @bit_abx
        cpx #3
        beq @jmp_aix
        jmp @unk

@trb_zpc:
        lda #MNE_TRB
        sta _dasm_midx
        lda #MODE_ZP
        sta _dasm_mode
        jmp finish
@bit_zpx:
        lda #MNE_BIT
        sta _dasm_midx
        lda #MODE_ZPX
        sta _dasm_mode
        jmp finish
@stz_zpx:
        lda #MNE_STZ
        sta _dasm_midx
        lda #MODE_ZPX
        sta _dasm_mode
        jmp finish
@trb_absc:
        lda #MNE_TRB
        sta _dasm_midx
        lda #MODE_ABS
        sta _dasm_mode
        jmp finish
@bit_abx:
        lda #MNE_BIT
        sta _dasm_midx
        lda #MODE_ABX
        sta _dasm_mode
        jmp finish
@jmp_aix:
        lda #MNE_JMP
        sta _dasm_midx
        lda #MODE_AIX
        sta _dasm_mode
        jmp finish

@unk:   lda #MNE_UNK
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish
.endproc

; ── cc=11: CPU-dependent ─────────────────────────────────
.proc decode_cc11
        lda al_cpu
        cmp #1
        beq @nmos
        cmp #2
        beq @cmos

        ; al_cpu=0 (6502): all ???
        lda #MNE_UNK
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish

@nmos:  ; 6510: illegal opcodes
        ; Regular: aaa→mne from g3_mne, bbb→mode from g1_mode
        lda _dasm_opc
        lsr
        lsr
        lsr
        lsr
        lsr                     ; aaa
        tax
        lda g3_mne_nmos,x
        sta _dasm_midx

        lda _dasm_opc
        lsr
        lsr
        and #$07                ; bbb
        tax
        lda g1_mode,x           ; reuse cc=01 mode table!
        sta _dasm_mode

        ; Check exceptions (IMM column + aaa=4,5 irregulars)
        ldx #0
@exc_loop:
        lda g3_exc_nmos,x
        beq @exc_done           ; end sentinel
        cmp _dasm_opc
        beq @exc_hit
        inx
        inx
        inx
        jmp @exc_loop
@exc_hit:
        lda g3_exc_nmos+1,x
        sta _dasm_midx
        lda g3_exc_nmos+2,x
        sta _dasm_mode
@exc_done:
        jmp finish

@cmos:  ; 65C02: RMB/SMB/BBR/BBS + other CMOS additions
        ; RMB/SMB: low nybble = $7 (bbb=1, cc=11)
        ; BBR/BBS: low nybble = $F (bbb=3, cc=11)
        lda _dasm_opc
        and #$0F
        cmp #$07
        beq @rmb_smb
        cmp #$0F
        beq @bbr_bbs

        ; Other cc=11 on 65C02: all NOP/???
        lda #MNE_UNK
        sta _dasm_midx
        lda #MODE_IMP
        sta _dasm_mode
        jmp finish

@rmb_smb:
        ; Bit number = (opcode >> 4) & 7
        ; RMB if bit 7 clear, SMB if bit 7 set
        lda _dasm_opc
        bmi @smb
        lda #MNE_RMB
        .byte $2C               ; BIT abs — skip next 2 bytes
@smb:   lda #MNE_SMB
        sta _dasm_midx
        lda #MODE_ZP
        sta _dasm_mode
        ; Append digit to mnemonic
        jsr print_mne           ; print "RMB " or "SMB "
        ; Back up 1 position (overwrite the space with digit)
        dec _dasm_wptr
        ; Re-read opcode (print_mne clobbers _dasm_opc)
        ldy #0
        lda (_dasm_ptr),y
        lsr
        lsr
        lsr
        lsr
        and #$07
        clc
        adc #$30                ; '0'..'7'
        jsr buf_putc
        lda #$20                ; space
        jsr buf_putc
        jsr format_operand
        ; NUL-terminate and return length
        ldx _dasm_wptr
        lda #0
        sta _dasm_buf,x
        lda #2                  ; ZP mode = 2 bytes
        rts

@bbr_bbs:
        lda _dasm_opc
        bmi @bbs
        lda #MNE_BBR
        .byte $2C               ; BIT abs — skip
@bbs:   lda #MNE_BBS
        sta _dasm_midx
        lda #MODE_ZPREL
        sta _dasm_mode
        ; Append digit
        jsr print_mne
        dec _dasm_wptr
        ldy #0
        lda (_dasm_ptr),y       ; re-read opcode (print_mne clobbers _dasm_opc)
        lsr
        lsr
        lsr
        lsr
        and #$07
        clc
        adc #$30
        jsr buf_putc
        lda #$20
        jsr buf_putc
        jsr format_operand
        ldx _dasm_wptr
        lda #0
        sta _dasm_buf,x
        lda #3                  ; ZPREL = 3 bytes
        rts
.endproc

; ════════════════════════════════════════════════════════════
; RODATA — tables
; ════════════════════════════════════════════════════════════
.segment "RODATA"

; ── Mnemonic index constants ─────────────────────────────
; (These values must match dasm_mne_str order — generated by
;  dasm_tables.py.  We define a few here for inline use.)
.include "dasm_mne_idx.s"

; ── Mode length table (derived from mode format hi nybble) ─
; mode → instruction length (1, 2, or 3)
mode_len:
        .byte 1                 ; 0  IMP
        .byte 1                 ; 1  ACC
        .byte 2                 ; 2  IMM
        .byte 2                 ; 3  ZP
        .byte 2                 ; 4  ZPX
        .byte 2                 ; 5  ZPY
        .byte 3                 ; 6  ABS
        .byte 3                 ; 7  ABX
        .byte 3                 ; 8  ABY
        .byte 3                 ; 9  IND
        .byte 2                 ; 10 INX
        .byte 2                 ; 11 INY
        .byte 2                 ; 12 REL
        .byte 2                 ; 13 ZPI
        .byte 3                 ; 14 AIX
        .byte 3                 ; 15 ZPREL

; ── Mode format descriptors ──────────────────────────────
dasm_mode_fmt:
        .byte $00,$60,$30,$10,$11,$12,$20,$21
        .byte $22,$53,$44,$45,$70,$43,$54,$80

; ── cc=01 tables (shared, perfectly regular) ─────────────
; aaa → mnemonic index
g1_mne: ; ORA AND EOR ADC STA LDA CMP SBC
        .byte MNE_ORA,MNE_AND,MNE_EOR,MNE_ADC
        .byte MNE_STA,MNE_LDA,MNE_CMP,MNE_SBC

; bbb → mode index
g1_mode:
        .byte MODE_INX,MODE_ZP,MODE_IMM,MODE_ABS
        .byte MODE_INY,MODE_ZPX,MODE_ABY,MODE_ABX

; ── cc=10 mnemonic (shared, from bbb=1 ZP column) ───────
g2_mne: ; ASL ROL LSR ROR STX LDX DEC INC
        .byte MNE_ASL,MNE_ROL,MNE_LSR,MNE_ROR
        .byte MNE_STX,MNE_LDX,MNE_DEC,MNE_INC

; ── cc=10 bbb=2 (accumulator/implied) ───────────────────
g2b2_mne:
        .byte MNE_ASL,MNE_ROL,MNE_LSR,MNE_ROR
        .byte MNE_TXA,MNE_TAX,MNE_DEX,MNE_NOP
g2b2_mode:
        .byte MODE_ACC,MODE_ACC,MODE_ACC,MODE_ACC
        .byte MODE_IMP,MODE_IMP,MODE_IMP,MODE_IMP

; ── cc=10 bbb=6 (NMOS implied) ──────────────────────────
g2b6_mne_nmos:
        .byte MNE_UNK,MNE_UNK,MNE_UNK,MNE_UNK
        .byte MNE_TXS,MNE_TSX,MNE_UNK,MNE_UNK
g2b6_mne_cmos:
        .byte MNE_INC,MNE_DEC,MNE_PHY,MNE_PLY
        .byte MNE_TXS,MNE_TSX,MNE_PHX,MNE_PLX

; ── cc=00 branch mnemonics ───────────────────────────────
g0_br_mne:
        .byte MNE_BPL,MNE_BMI,MNE_BVC,MNE_BVS
        .byte MNE_BCC,MNE_BCS,MNE_BNE,MNE_BEQ

; ── cc=00 implied bbb=2 ─────────────────────────────────
g0_i2_mne:
        .byte MNE_PHP,MNE_PLP,MNE_PHA,MNE_PLA
        .byte MNE_DEY,MNE_TAY,MNE_INY,MNE_INX

; ── cc=00 implied bbb=6 ─────────────────────────────────
g0_i6_mne:
        .byte MNE_CLC,MNE_SEC,MNE_CLI,MNE_SEI
        .byte MNE_TYA,MNE_CLV,MNE_CLD,MNE_SED

; ── cc=00 family (aaa=4-7): STY LDY CPY CPX ─────────────
g0_fam_mne:
        .byte MNE_STY,MNE_LDY,MNE_CPY,MNE_CPX

; bbb → mode for cc=00 family
g0_fam_mode:
        .byte MODE_IMM          ; bbb=0
        .byte MODE_ZP           ; bbb=1
        .byte MODE_IMP          ; bbb=2 (unused, implied handled separately)
        .byte MODE_ABS          ; bbb=3
        .byte MODE_REL          ; bbb=4 (unused, branches handled separately)
        .byte MODE_ZPX          ; bbb=5
        .byte MODE_IMP          ; bbb=6 (unused)
        .byte MODE_ABX          ; bbb=7

; ── cc=00 bbb=0 aaa=0-3: BRK JSR RTI RTS ────────────────
g0b0_mne:
        .byte MNE_BRK,MNE_JSR,MNE_RTI,MNE_RTS
g0b0_mode:
        .byte MODE_IMP,MODE_ABS,MODE_IMP,MODE_IMP

; ── cc=11 NMOS illegal mnemonic (aaa→mne) ────────────────
g3_mne_nmos:
        .byte MNE_SLO,MNE_RLA,MNE_SRE,MNE_RRA
        .byte MNE_SAX,MNE_LAX,MNE_DCP,MNE_ISC

; ── cc=11 NMOS exceptions (opc, mne_idx, mode_idx) ───────
; Terminated by $00 sentinel.
g3_exc_nmos:
        .byte $0B, MNE_ANC, MODE_IMM
        .byte $2B, MNE_AAC, MODE_IMM
        .byte $4B, MNE_ASR, MODE_IMM
        .byte $6B, MNE_ARR, MODE_IMM
        .byte $8B, MNE_XAA, MODE_IMM
        .byte $93, MNE_SHA, MODE_INY
        .byte $97, MNE_SAX, MODE_ZPY
        .byte $9B, MNE_XAS, MODE_ABY
        .byte $9F, MNE_SHA, MODE_ABY
        .byte $AB, MNE_LXA, MODE_IMM
        .byte $B7, MNE_LAX, MODE_ZPY
        .byte $BB, MNE_LAS, MODE_ABY
        .byte $BF, MNE_LAX, MODE_ABY
        .byte $CB, MNE_SBX, MODE_IMM
        .byte $EB, MNE_USB, MODE_IMM
        .byte $00                       ; sentinel

; Mode index constants (must match MODE_NAMES order)
MODE_IMP   = 0
MODE_ACC   = 1
MODE_IMM   = 2
MODE_ZP    = 3
MODE_ZPX   = 4
MODE_ZPY   = 5
MODE_ABS   = 6
MODE_ABX   = 7
MODE_ABY   = 8
MODE_IND   = 9
MODE_INX   = 10
MODE_INY   = 11
MODE_REL   = 12
MODE_ZPI   = 13
MODE_AIX   = 14
MODE_ZPREL = 15
