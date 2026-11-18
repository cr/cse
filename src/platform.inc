; platform.inc — the platform driver layer's constants and macros.
; Owner: doc/platform_layer.md
;
; Every platform fact of CSE — a KERNAL entry or cell, a register, a
; memory home, a size, a banking value — is a constant or a macro here,
; selected by the build's one platform define (PLATFORM_C64,
; PLATFORM_M65), or code inside a `.ifdef PLATFORM_*` block in the
; module that hosts a seam.  The contract of every name is
; doc/platform_layer.md § Seam contracts; each c64 expansion is the
; instruction sequence the C64 code has at that site, so the C64
; builds stay byte-identical (tests/fixtures/golden/c64_prg_sha256.json).

.ifndef PLATFORM_INC
PLATFORM_INC = 1

.ifndef PLATFORM_C64
  .ifndef PLATFORM_M65
    .error "platform.inc: no platform define (PLATFORM_C64 or PLATFORM_M65)"
  .endif
.endif

; ═════════════════════════════════════════════════════════════════════
.ifdef PLATFORM_C64
; ═════════════════════════════════════════════════════════════════════

; ── KERNAL jump-table entries CSE calls ──────────────────────────────
GETIN           = $FFE4
PLOT            = $FFF0
RESTOR          = $FF8A
CINT            = $FF81
SETLFS          = $FFBA
SETNAM          = $FFBD
OPEN            = $FFC0
CLOSE           = $FFC3
CHKIN           = $FFC6
CHKOUT          = $FFC9
CLRCHN          = $FFCC
CHRIN           = $FFCF
CHROUT          = $FFD2
LOAD            = $FFD5
READST          = $FFB7
LISTEN          = $FFB1
UNLSN           = $FFAE

; ── KERNAL internals called directly ─────────────────────────────────
KERNAL_IRQ_BODY = $EA31         ; the IRQ body (the early entry's target)
KERNAL_COLD     = $FCE2         ; cold start (PLAT_COLD_START)
BASIC_WARM      = $A002         ; BASIC's warm-start vector (jmp (BASIC_WARM))

; ── KERNAL cells ─────────────────────────────────────────────────────
ST              = $90           ; I/O status
STKEY           = $91           ; the STOP row of the last scan ($7F = STOP down)
NDX             = $C6           ; keyboard buffer count
BLNSW           = $CC           ; cursor blink switch (0 = blinking)
GDBLN           = $CE           ; the character under the cursor
CUR_COL         = $D3           ; cursor column (PNTR)
QTSW            = $D4           ; quote mode
LNMX            = $D5           ; logical line length - 1
CUR_ROW         = $D6           ; cursor row (TBLX)
INSRT           = $D8           ; insert count
LDTB1           = $D9           ; the screen line-link table ($D9–$F1)
CHRCOLOR        = $0286         ; the colour CHROUT writes
KEY_REPEAT      = $028A         ; RPTFLG
CHARSET_LOCK    = $0291         ; MODE: $80 locks SHIFT+C= charset switching

; ── The CPU port and the user ZP ─────────────────────────────────────
CPU_DDR         = $00
CPU_PORT        = $01
DDR_SEED        = $2F           ; the DDR as the KERNAL sets it
PORT_SEED       = $36           ; the kernel's configuration: KERNAL in, BASIC out
BANK_IN         = PORT_SEED
ZP_BASE         = $00           ; the zero page's first byte
ZP_SAVE_LO      = $00           ; the user ZP swapped at every transition
ZP_SAVE_LEN     = 128           ;   … $00–$7F

; ── Vectors ──────────────────────────────────────────────────────────
IBRK_VEC        = $0316         ; page-3 BRK dispatch
INMI_VEC        = $0318         ; page-3 NMI dispatch
NMI_VEC_RAM     = $FFFA         ; RAM shadows, read while the KERNAL is out
IRQ_VEC_RAM     = $FFFE

; ── The interrupt frame ──────────────────────────────────────────────
FRAME_DEPTH     = 3             ; Y X A above the CPU's P PCL PCH

; ── Homes ────────────────────────────────────────────────────────────
HIMEM           = $D000         ; first byte past the runtime image
BASIC_START     = $0801         ; BASIC's program start (TXTTAB)
WORKSTART       = $0800         ; the workspace's first byte
SYM_TABLE       = $E000         ; under the KERNAL: the symbol table
SYM_HEAP        = $E600         ;   the name heap …
SYM_HEAP_END    = $EF00         ;   … up to here (exclusive)
REPL_SCREEN     = $F4F2         ;   the REPL screen save
COLD_ZP         = $F8DA         ;   the cold-init ZP snapshot
ROM_BASE_HI     = $E0           ; the debugger does not step into ROM

; ── Screen ───────────────────────────────────────────────────────────
SCREEN          = $0400
COLOR_RAM       = $D800
SCREEN_WIDTH    = 40
SCREEN_HEIGHT   = 25

; ── VIC-II ───────────────────────────────────────────────────────────
VIC_CR1         = $D011         ; DEN/BMM/ECM/RSEL/YSCROLL
VIC_SP_EN       = $D015         ; sprite enable mask
VIC_CR2         = $D016         ; RES/MCM/CSEL/XSCROLL
VIC_MEMCTL      = $D018         ; screen + charset base
VIC_IRR         = $D019         ; interrupt latch (write to ack)
VIC_IMR         = $D01A         ; interrupt mask
VIC_BRD         = $D020
VIC_BG          = $D021

; ── SID ──────────────────────────────────────────────────────────────
SID_V1_FREQ_LO  = $D400
SID_V1_FREQ_HI  = $D401
SID_V1_CTRL     = $D404
SID_V2_CTRL     = $D40B
SID_V3_CTRL     = $D412
SID_VOL         = $D418

; ── disk.s's private pointer (in the KERNAL half; TODO § Bugs) ───────
DISK_LOCAL_PTR  = $FD

.endif ; PLATFORM_C64

; ═════════════════════════════════════════════════════════════════════
; Macros — one contract each (doc/platform_layer.md § Seam contracts),
; a body per platform.
; ═════════════════════════════════════════════════════════════════════

; ── KERNAL calls (§ KERNAL calls) ────────────────────────────────────
; Call / tail-jump to a KERNAL jump-table entry under the KERNAL's
; prerequisites.  A, X, Y and C pass through in both directions.
.macro KCALL entry
  .ifdef PLATFORM_C64
        jsr entry
  .endif
.endmacro

.macro KJMP entry
  .ifdef PLATFORM_C64
        jmp entry
  .endif
.endmacro

; ── Banking (§ Banking) ──────────────────────────────────────────────
; For the sites whose banking does not fit kernal_bank_out / _in's
; batch protocol.  They compose: BANK_PUSH · BANK_IN_A … BANK_POP.
; m65: empty — nothing of CSE's is under the KERNAL.

; A ← the caller's configuration, pushed.
.macro BANK_PUSH
  .ifdef PLATFORM_C64
        lda CPU_PORT
        pha
  .endif
.endmacro

; The pushed configuration back; C kept.
.macro BANK_POP
  .ifdef PLATFORM_C64
        pla
        sta CPU_PORT
  .endif
.endmacro

; Bank the KERNAL in from the configuration in A.
.macro BANK_IN_A
  .ifdef PLATFORM_C64
        ora #$02
        sta CPU_PORT
  .endif
.endmacro

; Bank the KERNAL in / out regardless of kernal_out.
.macro BANK_FORCE_IN
  .ifdef PLATFORM_C64
        lda CPU_PORT
        ora #$02
        sta CPU_PORT
  .endif
.endmacro

.macro BANK_FORCE_OUT
  .ifdef PLATFORM_C64
        lda CPU_PORT
        and #$FD
        sta CPU_PORT
  .endif
.endmacro

; The kernel's configuration: KERNAL in, BASIC out.
.macro BANK_KERNEL
  .ifdef PLATFORM_C64
        lda #BANK_IN
        sta CPU_PORT
  .endif
.endmacro

.endif ; PLATFORM_INC
