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
        .export newline
        .export cse_end
        .exportzp buf_base

        .import asm_assemble

HEAP_START = $4000          ; symbol-table heap (above all code/BSS)
CPU_PORT   = $01

; ── Zero page ─────────────────────────────────────────────────────────────────
.segment "ZEROPAGE"
_src_ptr:   .res 2          ; current read position in _test_src_buf
_buf_ptr:   .res 2          ; destination buffer for ed_read_line (scratch)
buf_base:   .res 2          ; mock: gap buffer base (for workend symbol)

; ── BSS ───────────────────────────────────────────────────────────────────────
.segment "BSS"
_src_done:      .res 1      ; non-zero = EOF
_test_src_buf:  .res 2048   ; source: NUL-terminated lines, $FF = EOF
_bank_witness:  .res 1      ; OR of $01 at every ed_read_line call
                            ; (placed last so test_src_buf offset is unchanged)

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
; Input: A/X = buf pointer. Maxlen hardcoded to 80.
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
        ; Copy up to 79 chars from _src_ptr to _buf_ptr
        ; (Y already 0 from the sentinel check.)
@cp:    lda (_src_ptr),y
        beq @eol                ; NUL = end of line
        sta (_buf_ptr),y
        iny
        cpy #79
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
newline:
        rts

; ── cse_end ──────────────────────────────────────────────────────────────────
; Returns heap start address in A/X (used by asm_assemble for sym table).
cse_end:
        lda #<HEAP_START
        ldx #>HEAP_START
        rts
