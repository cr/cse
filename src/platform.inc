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
; the gap buffer's bounds: the runtime start (the linker's) and the
; source-growth floor (compute_layout.py's), both linker symbols
        .import __CODE_RUN__
        .import __BUF_FLOOR__
.define BUF_END   __CODE_RUN__
.define BUF_FLOOR __BUF_FLOOR__
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
SCREEN_WIDTH_MAX = SCREEN_WIDTH ; the widest mode (line_buf)
MEM_ROW_MAX     = 8             ; the most bytes an `m` row shows or edits
LINE_MAX        = 39            ; a source line's length (the assembler's read,
                                ; warn_long_lines); the editor's cap is LAST_COL
; the geometry's operand defines (§ Display): immediates here, cells on m65
.define WIDTH           #SCREEN_WIDTH
.define LAST_COL        #SCREEN_WIDTH - 1
.define HEIGHT          #SCREEN_HEIGHT
.define LAST_ROW        #SCREEN_HEIGHT - 1
.define ED_ROWS         #SCREEN_HEIGHT - 3
.define ED_STATUS_ROW   #SCREEN_HEIGHT - 3
.define ED_LAST         #SCREEN_HEIGHT - 4

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
; ── list_directory's buffer: the workspace from BASIC's start ───────
DIR_BUF         = BASIC_START

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
SCANSTOPKEY     = $FFEA             ; A = $7F while STOP is held (A1)
VIC4_SCREEN_BANK = $D062            ; the screen pointer's bank (4 in 80 x 50)
VIC_BASE        = $D000             ; the VIC-IV registers (vic_reset's table)
VIC_SP_EN       = $D015
VIC_BRD         = $D020
VIC_BG          = $D021
COLOUR_RAM_BANK = $08               ; colour RAM: FF8.0000 — bank $08 of
COLOUR_RAM_MB   = $FF               ;   megabyte $FF (the modes' offset is 0, A1)
DMA_OPT_DST_MB  = $81               ; DMA option: the destination's megabyte
SYSFLAGS_CSE    = $A0               ; bit 5 raw function keys, bit 7 Mega+Shift
                                    ;   locked: CSE's, while it reads keys
ADDKEY          = $FF4A

; ── Hypervisor services (book Appendix N): lda #service · sta trap · clv
HYPPO_TRAP      = $D640
HYPPO_TRAP_ROM  = $D641
HYPPO_GETVERSION = $00              ; via HYPPO_TRAP; A.X Hyppo, Y.Z HDOS
HYPPO_ROM_WRITEENABLE = $02         ; via HYPPO_TRAP_ROM: banks 2-3 writable
HYPPO_RESET     = $7E               ; via HYPPO_TRAP: does not return
HYPPO_GET_MAPPING = $74             ; via HYPPO_TRAP; Y = the page: MAP's
                                    ;   X A Z Y operands, the two megabytes

; ── The bank state (§ User transitions): the CPU port, $D030, MAP ────
CPU_DDR         = $00
CPU_PORT        = $01
DDR_SEED        = $FF               ; the run premise's port: the kernel's
PORT_SEED       = $85               ;   while CSE runs, and a fresh start's
D030_ROMBANK    = $D030             ; VIC-III ROM banking
D030_SEED       = $64               ; the run premise's
ZP_SAVE_LO      = $00               ; the user-ZP view's image: the CPU
ZP_SAVE_LEN     = 2                 ;   port, $00-$01 (userland_zp_buf)
MAP_MB          = $0F               ; MAP's X / Z for the megabyte form

; ── The KERNAL's vector table, through VECTOR (book I-79/80) ─────────
VEC_SIZE        = 56
VEC_IBRK        = 2                 ; offsets: IIRQ 0, IBRK 2, INMI 4
VEC_INMI        = 4

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
; The user map's rows above bank 0 (FAR_USER, mem.s far_user):
BANK_IROM       = 2                 ; $C000-$CFFF: the interface ROM, 2.C000
BANK_KERNAL     = 3                 ; $E000-$FFFF: the KERNAL, 3.E000
BANK_IO         = $FD               ; $D000-$DFFF: FFD.3000, the MEGA65
MB_IO           = $0F               ;   personality's I/O registers
IO_FLAT_HI      = $30               ;   at offset $3000-$3FFF

; ── The two maps: MAP's A X (MAPLO) and Y Z (MAPHI) ──────────────────
MAP_CSE_A       = $00               ; $2000-$BFFF -> 3.2000, KERNAL 3.E000
MAP_CSE_X       = $E3
MAP_CSE_Y       = $00
MAP_CSE_Z       = $B3
MAP_USER_A      = $00               ; $0000-$BFFF bank 0, KERNAL 3.E000
MAP_USER_X      = $E0
MAP_USER_Y      = $00
MAP_USER_Z      = $83
KMAP_REC        = $011C             ; the KERNAL's map record, 0.011C-011F:
                                    ;   A X Y Z, what its far calls MAP back

; ── The interrupt frame, the stack top ───────────────────────────────
FRAME_DEPTH     = 5                 ; B Z Y X A above the CPU's P PCL PCH
STACK_TOP       = $F1               ; a fresh start's SP is the premise's $EF

; ── Homes ────────────────────────────────────────────────────────────
BASIC_START     = $2001             ; BASIC 65's program start (the PRG)
PROG_LO         = $2000             ; the program region, bank 0
PROG_HI         = $BFFF
HIMEM           = PROG_HI + 1       ; cse_start / cse_end
WORKSTART       = PROG_LO
ROM_BASE_HI     = $C0               ; the interface ROM at $C000 (user map)
BUF_FLOOR       = $4000             ; the source region 2.4000-2.BFFF: the
BUF_END         = $C000             ;   gap buffer's offsets in BANK_SRC
; the data window's fixed homes, above KDATA + BSS (CSE map, bank 3)
SYM_TABLE       = $A100             ; the symbol table, 256 x 6 bytes
SYM_HEAP        = $A700             ;   the name heap …
SYM_HEAP_END    = $B000             ;   … up to here (exclusive)
REPL_SCREEN     = $B000             ; the REPL screen save, 80 x 50
        .assert SYM_HEAP - SYM_TABLE = 256 * 6, error, "SYM_TABLE size"
        .assert REPL_SCREEN + 80 * 50 <= $C000, error, "REPL_SCREEN overflows the data window"

; ── SID ──────────────────────────────────────────────────────────────
SID_V1_FREQ_LO  = $D400
SID_V1_FREQ_HI  = $D401
SID_V1_CTRL     = $D404
SID_V2_CTRL     = $D40B
SID_V3_CTRL     = $D412
SID_VOL         = $D418

; ── list_directory's buffer: CSE's 12 K reserve 2.D000-2.FFFF, not the
; user's memory (a full D81 directory is under 10 K; disk.md § On m65)
DIR_BUF         = $D000
DIR_BANK        = BANK_SRC

SCREEN_WIDTH_MAX = 80               ; the widest mode (line_buf)
MEM_ROW_MAX     = 16                ; an `m` row: 16 bytes in 80 columns (8 in 40),
                                    ; an edit up to 16 in either (repl.md, By width)
LINE_MAX        = 79                ; a source line's length (D-P2-5): 80 columns' last

; ── The terminal's cells and the geometry (§ Terminal, § Display) ────
; CSE's base-page cells (zp.s), named at inline sites through these
; defines; an operand define is the immediate on c64 and the cell here.
  .ifndef ZP_S                  ; the hot cells: CSE's base page (zp.s)
        .importzp io_cx, io_cy, io_key, scr_width, scr_last_col, disk_local_ptr
  .endif
  .ifndef CSE_IO_S              ; the rest of the geometry: cse_io.s's BSS
        .import scr_height, scr_last_row, scr_ed_rows, scr_ed_last, scr_bank, scr_size
  .endif
.define IO_CX           io_cx
.define IO_CY           io_cy
.define WIDTH           scr_width
.define LAST_COL        scr_last_col
.define HEIGHT          scr_height
.define LAST_ROW        scr_last_row
.define ED_ROWS         scr_ed_rows
.define ED_STATUS_ROW   scr_ed_rows
.define ED_LAST         scr_ed_last
.define DISK_LOCAL_PTR  disk_local_ptr  ; disk.s's filename pointer (a plain one)

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

; ── The kernel -> user transition (§ User transitions) ──────────────
; The tail of debugger.s's _rtu_body: the RTI frame (PC, P) is on the
; stack.  c64: the registers from the snapshot, RTI (in_userland set
; before).  m65: a MAP of the CSE map onto itself first — MAP holds
; IRQ and NMI off until stub_user's EOM, so nothing breaks in before
; the user's map is in place; then in_userland; $D030 and the CPU
; port back to the user's while the kernel's code is still mapped;
; the registers and the second MAP's operands (offsets, masks) pushed
; for stub_user, the megabyte operands in A X Y Z; into the stub.
.macro PLAT_TO_USER
  .ifdef PLATFORM_C64
        ldx reg_x
        ldy reg_y
        lda reg_a
        rti
  .else
        lda #MAP_CSE_A              ; the hold: the CSE map onto itself
        ldx #MAP_CSE_X
        ldy #MAP_CSE_Y
        M45_LDZ_IMM MAP_CSE_Z
        M45_MAP
        lda #$80
        sta in_userland
        lda um_d030
        sta D030_ROMBANK
        lda userland_zp_buf + CPU_DDR
        sta a:CPU_DDR
        lda userland_zp_buf + CPU_PORT
        sta a:CPU_PORT
        lda reg_a
        pha
        lda reg_x
        pha
        lda reg_y
        pha
        lda reg_z
        pha
        lda reg_b
        pha
        lda um_map + 1              ; MAPLO's A
        pha
        lda um_map + 0              ;   X
        pha
        lda um_map + 3              ; MAPHI's Y
        pha
        lda um_map + 2              ;   Z
        pha
        lda um_map + 4              ; MAPLO's megabyte
        ldx #MAP_MB
        ldy um_map + 5              ; MAPHI's megabyte
        M45_LDZ_IMM MAP_MB
        jmp stub_user
  .endif
.endmacro

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

; A conditional branch across KCALLs: `op target` on c64; on m65,
; where a KCALL is 14 bytes, `inverse` over a JMP.  KC_BRANCH bmi, bpl, @t
.macro KC_BRANCH op, inverse, target
  .ifdef PLATFORM_C64
        op target
  .else
        inverse :+
        jmp target
:
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
        KCALL SCANSTOPKEY       ; A = $7F while STOP is held (A1)
        cmp #$7F
  .endif
.endmacro

; A ← the count of typed keys waiting (m65: the key itself); Z set
; when none.
.macro IO_KBHIT
  .ifdef PLATFORM_C64
        lda NDX
  .else
    .ifndef io_kbhit
        .import io_kbhit
    .endif
        jsr io_kbhit            ; the one-key lookahead (cse_io.s)
  .endif
.endmacro

; Drop the typed keys waiting.  In: A = 0.  Out: A = 0.
.macro IO_KBD_FLUSH
  .ifdef PLATFORM_C64
        sta NDX
  .else
    .ifndef io_kbd_flush
        .import io_kbd_flush
    .endif
        jsr io_kbd_flush        ; GETIN until 0, the lookahead emptied
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
    .ifndef io_cse_keys
        .import io_cse_keys
    .endif
        jsr io_cse_keys         ; SYSFLAGS: CSE's bits (the program's are
                                ;   in its bank state)
        lda #0                  ; SID voices 1–3: waveform + gate off
        sta SID_V1_CTRL
        sta SID_V2_CTRL
        sta SID_V3_CTRL
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
.macro PLAT_SETBNK bank
  .ifdef PLATFORM_M65
    .ifblank bank
        lda #BANK_USER              ; the data: the user's bank 0
    .else
        lda #bank
    .endif
        ldx #BANK_CSE               ; the filename: CSE's view
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
.macro FAR_BANK name, bank          ; m65: clobbers A (no site needs it kept)
  .ifdef PLATFORM_M65
        lda #bank
        sta name+2
    .if .not .xmatch({bank}, BANK_USER) ; by token: a bank constant is not
        lda #0                      ; yet constant inside a .proc (ca65)
    .endif
        sta name+3                  ; the megabyte: only FAR_USER's I/O row sets it
  .endif
.endmacro

; A screen pointer: its bank is the current mode's (scr_bank, 4 in
; 80 x 50), set wherever the pointer is set (§ Display).  c64: empty.
; m65: clobbers A (no site needs it kept).
.macro FAR_BANK_SCREEN name
  .ifdef PLATFORM_M65
        lda scr_bank
        sta name+2
        lda #0
        sta name+3
  .endif
.endmacro

; The pointer's offset is a user address: set its bank (and megabyte)
; to where the user map shows it — platform_layer.md § Far memory.
; Once per set: the I/O row rewrites the offset's high byte.
; c64: empty.  m65: clobbers X, N/Z.
.macro FAR_USER name
  .ifdef PLATFORM_M65
    .ifndef far_user
        .import far_user
    .endif
        ldx #name
        jsr far_user
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
