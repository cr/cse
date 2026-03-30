; cse_io_test_stub.s — KERNAL PLOT stub for py65 test environment
;
; io_sync calls JSR $FFF0 (KERNAL PLOT).  In py65 there's no ROM,
; so we patch $FFF0 → JMP kplot_stub.  This stub uses the same
; scr_lo/scr_hi tables from cse_io.s.

        .export kplot_stub
        .export _nmi_pending
        .export _dbg_running
        .export _dbg_nmi_break
        .exportzp sp

        .import _io_sync

; Import the row address tables from cse_io.s
        .import scr_lo, scr_hi

.segment "ZEROPAGE"
sp:     .res 2          ; cc65 C stack pointer (needed by cse_popax)

.segment "BSS"
_nmi_pending:  .res 1   ; NMI flag (stub — not used in tests)
_dbg_running:  .res 1   ; debugger running flag (stub)

.segment "CODE"

; KERNAL PLOT replacement.
;   CLC, X=row, Y=col → set cursor position + line pointers.
;   SEC → get position: X=row, Y=col.
; Stub: debugger NMI break (never reached in tests)
_dbg_nmi_break:
        rti

kplot_stub:
        bcs @get
        ; SET
        stx $D6                 ; cursor row
        sty $D3                 ; cursor column
        lda scr_lo,x
        sta $D1
        sta $F3                 ; color lo = screen lo
        lda scr_hi,x
        sta $D2
        clc
        adc #$D4                ; $04xx → $D8xx
        sta $F4
        rts
@get:
        ldx $D6
        ldy $D3
        rts
