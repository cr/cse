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

; ── CSE's base page ──────────────────────────────────────────────────
BP_PAGE         = $00           ; the page CSE's zero page is in (BP_ABS)

; ── Terminal (§ Terminal) ────────────────────────────────────────────
IO_CX           = CUR_COL       ; the cursor cells
IO_CY           = CUR_ROW

; ── The CPU port and the user ZP ─────────────────────────────────────
CPU_DDR         = $00
CPU_PORT        = $01
DDR_SEED        = $2F           ; the DDR as the KERNAL sets it
PORT_SEED       = $36           ; the kernel's configuration: KERNAL in, BASIC out
BANK_IN         = PORT_SEED
ZP_BASE         = $00           ; the zero page's first byte
ZP_FILL_END     = $80           ; cold init fills the free ZP up to here
ZP_SAVE_LO      = $00           ; the user ZP swapped at every transition
ZP_SAVE_LEN     = 128           ;   … $00–$7F

; ── Vectors ──────────────────────────────────────────────────────────
IBRK_VEC        = $0316         ; page-3 BRK dispatch
INMI_VEC        = $0318         ; page-3 NMI dispatch
NMI_VEC_RAM     = $FFFA         ; RAM shadows, read while the KERNAL is out
IRQ_VEC_RAM     = $FFFE

; ── The interrupt frame ──────────────────────────────────────────────
FRAME_DEPTH     = 3             ; Y X A above the CPU's P PCL PCH

; ── The stack top (platform_layer.md § Stack) ────────────────────────
STACK_TOP       = $FF           ; the whole page

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
.ifdef PLATFORM_M65
; ═════════════════════════════════════════════════════════════════════
; The MEGA65 in MEGA65 mode, ROM 920413+ (doc/memory_design.md
; § Memory Map — m65).  Constants of a seam whose m65 contract is
; stated with a later milestone are absent until then.

        .include "m45_ops.inc"

; ── KERNAL jump-table entries CSE calls (book I-5/6) ─────────────────
GETIN           = $FFE4
PLOT            = $FFF0
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
VECTOR          = $FF8D             ; read / write the vector table
SETBNK          = $FF6B             ; A: the data's bank, X: the filename's
SCRORG          = $FFED
SYSFLAGS        = $FF47

; ── Hypervisor services (book Appendix N): lda #service · sta trap · clv
HYPPO_TRAP      = $D640
HYPPO_TRAP_ROM  = $D641
HYPPO_GETVERSION = $00              ; via HYPPO_TRAP; A.X Hyppo, Y.Z HDOS
HYPPO_ROM_WRITEENABLE = $02         ; via HYPPO_TRAP_ROM: banks 2-3 writable
HYPPO_RESET     = $7E               ; via HYPPO_TRAP: does not return

; ── CSE's base page, the resident stub ───────────────────────────────
CSE_BP          = $1F               ; B while kernel code runs: 0.1F00
BP_PAGE         = CSE_BP
STUB_BASE       = $1FB0             ; the resident stub, to 0.1FFF
ZP_BASE         = $00               ; the base page's first byte (offset)
ZP_FILL_END     = <STUB_BASE        ; cold init fills the free part to here

; ── The KERNAL's jump table: every entry CSE calls is in this page ───
KERNAL_JUMP_PAGE = $FF00

; ── The DMAgic: an enhanced job list at (bank, hi, lo); $D705 starts it
DMA_LIST_HI     = $D701
DMA_LIST_BANK   = $D702             ; bits 16-22; clears the megabyte
DMA_START_ENH   = $D705             ; bits 0-7, starts an enhanced list
DMA_OPT_F018B   = $0B               ; option: the F018B job format
DMA_COPY        = $00               ; job commands
DMA_FILL        = $03
DMA_CHAIN       = $04               ; another job follows

; ── The banks a far pointer names (§ Far memory) ─────────────────────
BANK_USER       = 0                 ; user memory, the screen (40/80 x 25)
BANK_SRC        = 2                 ; the source region
BANK_CSE        = 3                 ; CSE's code and data
BANK_SCREEN50   = 4                 ; the screen in 80 x 50

; ── The two maps: MAP's A X (MAPLO) and Y Z (MAPHI) ──────────────────
MAP_CSE_A       = $00               ; $2000-$BFFF -> 3.2000, KERNAL 3.E000
MAP_CSE_X       = $E3
MAP_CSE_Y       = $00
MAP_CSE_Z       = $B3
MAP_USER_A      = $00               ; $0000-$BFFF bank 0, KERNAL 3.E000
MAP_USER_X      = $E0
MAP_USER_Y      = $00
MAP_USER_Z      = $83

; ── The interrupt frame, the stack top ───────────────────────────────
FRAME_DEPTH     = 5                 ; B Z Y X A above the CPU's P PCL PCH
STACK_TOP       = $F1               ; a fresh start's SP is the premise's $EF

; ── Homes ────────────────────────────────────────────────────────────
BASIC_START     = $2001             ; BASIC 65's program start (the PRG)
PROG_LO         = $2000             ; the program region, bank 0
PROG_HI         = $BFFF
WORKSTART       = PROG_LO
ROM_BASE_HI     = $C0               ; the interface ROM at $C000 (user map)

.endif ; PLATFORM_M65

; ── Base page (§ Base page) ──────────────────────────────────────────
; The 16-bit address of a CSE base-page symbol, for an access in an
; absolute mode (`jmp (sym)`, `sta sym,y` with no zero-page form) and
; for a pointer to one.  c64: the symbol itself.  The leading unary +
; keeps `BP_ABS(sym),y` absolute-indexed: an operand that opens with
; `(` would parse as `(zp),y`.
.define BP_ABS(sym) +((sym) + BP_PAGE * 256)

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
  .else
        pha                     ; the jump table needs B = 0 (book I-3)
        lda #0
        M45_TAB
        pla
        jsr entry
        pha
        lda #CSE_BP             ; back to CSE's base page
        M45_TAB
        pla
  .endif
.endmacro

.macro KJMP entry
  .ifdef PLATFORM_C64
        jmp entry
  .else
        KCALL entry
        rts
  .endif
.endmacro

; ── Terminal (§ Terminal) ────────────────────────────────────────────
; The inline keyboard sites outside cse_io.s.  m65: stated with P2.

; A ← the STOP row; Z set while STOP is held (main_loop's test).
.macro IO_STOP_DOWN
  .ifdef PLATFORM_C64
        lda STKEY
        cmp #$7F
  .else
        PLAT_PENDING 2
  .endif
.endmacro

; A ← the count of typed keys waiting; Z set when none.
.macro IO_KBHIT
  .ifdef PLATFORM_C64
        lda NDX
  .else
        PLAT_PENDING 2
  .endif
.endmacro

; Drop the typed keys waiting.  In: A = 0.
.macro IO_KBD_FLUSH
  .ifdef PLATFORM_C64
        sta NDX
  .else
        PLAT_PENDING 2
  .endif
.endmacro

; ── Display (§ Display) ──────────────────────────────────────────────
; repl.s's hygiene_after_userland: the KERNAL's blink off, the charset
; toggle locked, SID voices 1–3 gated off.  m65: stated with P2.
.macro PLAT_HYGIENE
  .ifdef PLATFORM_C64
        lda #1
        sta BLNSW               ; KERNAL cursor off (cse_io invariant)
        lda #$80
        sta CHARSET_LOCK        ; lock SHIFT+C= charset toggle
        lda #0                  ; SID voices 1–3: waveform + gate off
        sta SID_V1_CTRL         ;   (write-only registers: no RMW)
        sta SID_V2_CTRL
        sta SID_V3_CTRL
  .else
        PLAT_PENDING 2
  .endif
.endmacro

; ── Cold start and exit (§ Cold start and exit) ──────────────────────
; Restart the machine when recovery is impossible.
.macro PLAT_COLD_START
  .ifdef PLATFORM_C64
        jmp KERNAL_COLD
  .else
        HYPPO HYPPO_RESET, HYPPO_TRAP
  .endif
.endmacro

; ── Hypervisor services (§ Constants) ────────────────────────────────
; One trap: A <- service, the store traps, CLV follows it.  m65 only.
.macro HYPPO service, trap
        lda #service
        sta trap
        clv
.endmacro

; ── Disk bank (§ Disk bank) ──────────────────────────────────────────
; Precedes each OPEN and LOAD (before LOAD's register arguments): the
; banks of the data and of the filename.  c64: empty.  m65: clobbers
; A, X.
.macro PLAT_SETBNK
  .ifdef PLATFORM_M65
        lda #BANK_USER
        ldx #BANK_CSE
        KCALL SETBNK
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

; ── Far memory (§ Far memory) ────────────────────────────────────────
; A far pointer may reach memory outside the kernel's 16-bit view;
; zp.md lists which.  c64: the 2-byte pointer as it is.

.ifdef PLATFORM_C64
FAR_SIZE        = 2
.else
FAR_SIZE        = 4                 ; offset lo, hi, bank, megabyte 0
.endif

; Reserve a far pointer (zp.s).
.macro FAR_PTR name
name:   .res FAR_SIZE
.endmacro

; Set the pointer's bank wherever the pointer is set.  c64: empty.
; m65: A kept; clobbers N/Z.
.macro FAR_BANK name, bank
  .ifdef PLATFORM_M65
        pha
        lda #bank
        sta name+2
        pla
  .endif
.endmacro

; m65: Z <- Y for the flat [zp],Z access; A kept.
.macro _FAR_Z
        M45_PHY
        M45_PLZ
.endmacro

; A ← the byte at the pointer + Y.  m65: clobbers Z.
.macro FAR_LDA name
  .ifdef PLATFORM_C64
        lda (name),y
  .else
        _FAR_Z
        M45_FAR_LDA name
  .endif
.endmacro

; A → the byte at the pointer + Y.  m65: clobbers Z, N/Z.
.macro FAR_STA name
  .ifdef PLATFORM_C64
        sta (name),y
  .else
        _FAR_Z
        M45_FAR_STA name
  .endif
.endmacro

; A ← A | the byte at the pointer + Y.  m65: clobbers Z.
.macro FAR_ORA name
  .ifdef PLATFORM_C64
        ora (name),y
  .else
        _FAR_Z
        M45_FAR_ORA name
  .endif
.endmacro

; ── Pending bodies (§ Pending bodies) ────────────────────────────────
; The m65 body of a seam stated with milestone P<n> but not yet
; written: BRK and the signature byte n.  Never an expansion on c64.
.macro PLAT_PENDING n
  .ifdef PLATFORM_C64
        .error "PLAT_PENDING is an m65 body only"
  .else
        brk
        .byte n
  .endif
.endmacro

.endif ; PLATFORM_INC
