; asm_src_test_stub.s — test harness for asm_src.s + full assembler pipeline
;
; Provides:
;   sp, pushax, cse_popax — C stack (cc65 convention)
;   ed_read_line, ed_read_rewind — mock editor reading _test_src_buf
;   io_puts, io_putdec, newline — no-ops (suppress error output)
;   cse_end — returns HEAP_START ($4000)
;
; Source buffer layout: _test_src_buf (BSS, 2048 bytes)
;   Lines NUL-separated; double-NUL = EOF.
;   Python calls asm_src_test_entry after writing source.
;
; Entry point: asm_src_test_entry
;   — initialises C stack and source reader, calls asm_assemble
;   — returns A/X = error count

        .setcpu "6502"

        .export asm_src_test_entry
        .export _test_src_buf           ; Python writes source text here

        .exportzp sp                    ; parameter stack pointer
        .export pushax                  ; push A/X onto C stack
        .export cse_popax               ; pop 16-bit value → A/X

        .export ed_read_line
        .export ed_read_rewind
        .export io_puts
        .export io_putdec
        .export newline
        .export cse_end
        .exportzp buf_base

        .import asm_assemble

HEAP_START = $4000          ; symbol-table heap (above all code/BSS)

; ── Zero page ─────────────────────────────────────────────────────────────────
.segment "ZEROPAGE"
sp:         .res 2          ; C stack pointer
_src_ptr:   .res 2          ; current read position in _test_src_buf
_buf_ptr:   .res 2          ; destination buffer for ed_read_line (scratch)
buf_base:   .res 2          ; mock: gap buffer base (for workend symbol)

; ── BSS ───────────────────────────────────────────────────────────────────────
.segment "BSS"
_c_stack:       .res 256    ; parameter stack space (grows down from _c_stack+256)
_src_done:      .res 1      ; non-zero = EOF
_test_src_buf:  .res 2048   ; source lines NUL-separated, double-NUL = EOF

; ── CODE ──────────────────────────────────────────────────────────────────────
.segment "CODE"

; ── asm_src_test_entry ────────────────────────────────────────────────────────
; Initialises C stack and source reader, calls asm_assemble.
; Returns A/X = error count (pass through from asm_assemble).
asm_src_test_entry:
        lda #<(_c_stack + 256)
        sta sp
        lda #>(_c_stack + 256)
        sta sp+1
        lda #<_test_src_buf
        sta _src_ptr
        lda #>_test_src_buf
        sta _src_ptr+1
        lda #0
        sta _src_done
        jsr asm_assemble       ; A/X = error count
        rts

; ── pushax ────────────────────────────────────────────────────────────────────
; Push A/X (lo/hi) onto parameter stack.  sp -= 2; store lo at (sp), hi at (sp)+1.
; Matches cse_popax which reads lo at (sp), hi at (sp)+1.
pushax:
        pha                     ; save A (lo byte)
        lda sp
        sec
        sbc #2
        sta sp
        bcs :+
        dec sp+1
:       pla                     ; restore lo → A
        ldy #0
        sta (sp),y              ; store lo at (sp)
        txa
        ldy #1
        sta (sp),y              ; store hi at (sp)+1
        rts

; ── cse_popax ─────────────────────────────────────────────────────────────────
; Pop 16-bit value from parameter stack → A (lo), X (hi).  sp += 2.
cse_popax:
        ldy #0
        lda (sp),y              ; lo byte
        pha
        ldy #1
        lda (sp),y              ; hi byte
        tax
        clc
        lda sp
        adc #2
        sta sp
        bcc :+
        inc sp+1
:       pla                     ; lo → A
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
; int ed_read_line(char *buf, int maxlen)   [cc65 __cdecl__]
; On entry: A = maxlen (last arg, ignored), C stack = buf ptr (first arg).
; Returns: A/X = line length (≥0), or $FF/$FF = -1 on EOF.
ed_read_line:
        pha                     ; save maxlen (unused)
        jsr cse_popax           ; A=buf_lo, X=buf_hi
        sta _buf_ptr
        stx _buf_ptr+1
        pla                     ; discard maxlen
        lda _src_done
        bne @eof
        ; Copy up to 79 chars from _src_ptr to _buf_ptr
        ldy #0
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
:       ; Check if next char is NUL (double-NUL = EOF)
        ldy #0
        lda (_src_ptr),y
        bne :+
        lda #1
        sta _src_done           ; mark EOF for next call
:       tya                     ; A = line length
        ldx #0
        rts
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
