; asm_src_test_stub.s — test harness for asm_src.s + full assembler pipeline
;
; Provides:
;   ed_read_line, ed_read_rewind — mock editor reading _test_src_buf
;   io_puts, io_putdec, newline — no-ops (suppress error output)
;   cse_end — returns HEAP_START ($4000)
;
; Source buffer layout: _test_src_buf (BSS, 2048 bytes)
;   Lines NUL-terminated; EOF marker is a $FF sentinel byte.
;   Blank lines are a lone NUL ($00) and work correctly.
;   Python calls asm_src_test_entry after writing source.
;
; Entry point: asm_src_test_entry
;   — initialises source reader, calls asm_assemble
;   — returns A/X = error count

        .setcpu "6502"

        .export asm_src_test_entry
        .export _test_src_buf           ; Python writes source text here
        .export _bank_witness           ; OR-accumulator of $01 values seen
                                        ; by ed_read_line during assembly


        .export ed_read_line
        .export ed_read_rewind
        .export io_puts
        .export io_putdec
        .export io_utoa, dec_buf
        .export io_putc, io_clear_eol
        .export io_puthex4
        .export newline
        .export out_log_open
        .export out_close
        .export puts_imm
        .export cur_filename
        .export __CODE_RUN__    : absolute = $4000

        .import asm_assemble
        .import _min_pc, _max_pc
        .importzp buf_base, rp_ptr, rp_ptr2, rp_tmp

HEAP_START = $4000          ; symbol-table heap (above all code/BSS)
CPU_PORT   = $01

; ── Zero page (stub-private; must be ZP for indirect addressing) ─────────────
.segment "ZEROPAGE"
_src_ptr:   .res 2          ; current read position in _test_src_buf
_buf_ptr:   .res 2          ; destination buffer for ed_read_line (scratch)

; ── BSS ───────────────────────────────────────────────────────────────────────
.segment "BSS"
_src_done:      .res 1      ; non-zero = EOF
_test_src_buf:  .res 2048   ; source: NUL-terminated lines, $FF = EOF
_bank_witness:  .res 1      ; OR of $01 at every ed_read_line call
                            ; (placed last so test_src_buf offset is unchanged)
cur_filename:   .res 17     ; mock current filename (16 + NUL)

; ── CODE ──────────────────────────────────────────────────────────────────────
.segment "CODE"

; ── asm_src_test_entry ────────────────────────────────────────────────────────
; Initialises source reader and bank witness, calls asm_assemble.
; Returns A/X = error count (pass through from asm_assemble).
asm_src_test_entry:
        lda #<_test_src_buf
        sta _src_ptr
        lda #>_test_src_buf
        sta _src_ptr+1
        lda #0
        sta _src_done
        sta _bank_witness       ; reset witness to 0
        lda #<$0800             ; default origin
        ldx #>$0800
        jsr asm_assemble        ; A/X = error count
        rts

; ── ed_read_rewind ───────────────────────────────────────────────────────────
ed_read_rewind:
        lda #<_test_src_buf
        sta _src_ptr
        lda #>_test_src_buf
        sta _src_ptr+1
        lda #0
        sta _src_done
        rts

; ── ed_read_line ─────────────────────────────────────────────────────────────
; Input: A/X = buf pointer. Maxlen hardcoded to 40.
; Returns: A/X = line length (≥0), or $FF/$FF = -1 on EOF.
;
; Source encoding (written by the Python test harness):
;   - lines are NUL-terminated
;   - blank lines are represented as a lone NUL
;   - EOF is a single $FF sentinel byte
;   - $FF cannot appear in legitimate assembly source
;     (it's a C64 graphic glyph, not typeable as syntax)
; Using $FF as EOF — instead of the old "double-NUL = EOF" rule —
; means source text with blank lines works correctly.  The old
; encoding conflated "empty line" with "no more lines".
;
; Side effect: OR's the live $01 register into _bank_witness.  After
; assembly, the test inspects _bank_witness to verify that during the
; passes the KERNAL was actually banked OUT (bit 1 = 0).  If asm_assemble
; ever forgets to bank out, every call here will see bit 1 = 1 and the
; witness will retain it.  In a correct run, every ed_read_line call
; happens with KERNAL banked out, so witness bit 1 stays 0.
ed_read_line:
        sta _buf_ptr
        stx _buf_ptr+1
        lda CPU_PORT
        ora _bank_witness
        sta _bank_witness
        lda _src_done
        bne @eof
        ; Check for $FF EOF sentinel at the current read position
        ldy #0
        lda (_src_ptr),y
        cmp #$FF
        beq @hit_eof
        ; Copy up to 39 chars from _src_ptr to _buf_ptr
        ; (Y already 0 from the sentinel check.)
@cp:    lda (_src_ptr),y
        beq @eol                ; NUL = end of line
        sta (_buf_ptr),y
        iny
        cpy #39
        bcc @cp
@eol:   ; NUL-terminate dest buf
        lda #0
        sta (_buf_ptr),y
        ; Advance _src_ptr past line content + NUL separator
        tya
        clc
        adc _src_ptr
        sta _src_ptr
        bcc :+
        inc _src_ptr+1
:       inc _src_ptr            ; skip the NUL separator
        bne :+
        inc _src_ptr+1
:       tya                     ; A = line length
        ldx #0
        rts
@hit_eof:
        lda #1
        sta _src_done           ; mark EOF for next call
@eof:   lda #$FF
        tax                     ; A=$FF, X=$FF → -1 signed
        rts

; ── I/O no-ops ────────────────────────────────────────────────────────────────
; io_puts(A/X = string ptr), io_putdec(A/X = value), newline(): all no-ops.
io_puts:
io_putdec:
io_putc:
io_puthex4:
io_clear_eol:
newline:
out_log_open:
out_close:
        rts

        .importzp _io_tmp
; dec_pow tables (normally in cse_io.s, inlined here for test bundle)
.segment "RODATA"
dec_pow_lo:     .byte <1, <10, <100, <1000, <10000
dec_pow_hi:     .byte >1, >10, >100, >1000, >10000
.segment "CODE"

; Minimal io_utoa stub: fills dec_buf with 5-digit PETSCII + NUL.
; SEC/CLC wrapper behaviour not needed for test — just produce digits.
io_utoa:
        sta _io_tmp
        stx _io_tmp+1
        ldx #4                 ; power index
        ldy #0                 ; buf pos
@pow:   sty dec_buf+5          ; save buf pos
        ldy #0                 ; digit
@sub:   lda _io_tmp
        sec
        sbc dec_pow_lo,x
        pha
        lda _io_tmp+1
        sbc dec_pow_hi,x
        bcc @dd
        sta _io_tmp+1
        pla
        sta _io_tmp
        iny
        bne @sub
@dd:    pla
        tya
        ora #'0'
        ldy dec_buf+5
        sta dec_buf,y
        iny
        dex
        bpl @pow
        lda #0
        sta dec_buf,y
        rts

.segment "BSS"
dec_buf: .res 6
.segment "CODE"

; puts_imm — stub: skip the inline .word argument and return
;   The puts macro does: jsr puts_imm / .word str
;   We need to advance the return address by 2 to skip the .word.
puts_imm:
        pla
        clc
        adc #2
        tay
        pla
        adc #0
        pha
        tya
        pha
        rts

; Symbol resolution uses .lbl files (debug build with -g), so no
; .addr forcing is needed to make symbols visible.

