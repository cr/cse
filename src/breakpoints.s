; breakpoints.s — Breakpoint-table CRUD and patching (L3)
;
; Pure data-structure operations on a fixed-size 10-slot breakpoint
; table.  No KERNAL calls, no vectors, no banking, no stack frames —
; just table manipulation and memory byte poking via indirect
; (rp_ptr) indexing.  This makes it bundle-testable at Tier U
; independently of the step / BRK / userland-transition state machine
; that lives one layer up in debugger.s.
;
; Owns:
;   * `bp_table`: unified 10-slot breakpoint table.
;     Slots 0–7: user-visible breakpoints (managed by the `b` command
;                via dbg_bp_set / dbg_bp_del / dbg_bp_clear / dbg_bp_find
;                / dbg_bp_count).
;     Slots 8–9: ad-hoc step BRKs (alias `step_bp`).  patch_all /
;                unpatch_all iterate all 10 slots.
;     Slot format (4 bytes): [addr_lo, addr_hi, saved_byte, enabled].
;   * `dbg_bp_hit`: slot number of the last breakpoint that fired
;     ($FF when none).  Written by the BRK handler in main.s after
;     classification; read by `c` / `r` display helpers.  Lives here
;     because its semantics index into bp_table.
;   * `bp_init`: zeros the table and sets dbg_bp_hit = $FF.  Called
;     from dbg_init at cold boot.
;   * `patch_all` / `unpatch_all`: iterate all 10 slots, save the
;     original byte and overwrite with $00 (BRK opcode) — or restore.
;     The shared 10-slot iteration is why the step slots live
;     physically in this table.
;   * `dbg_step_clear`: zero just slots 8–9 (the step-BP pair).
;
; Layer: L3 (core engines), same as addr_mode / expr / opcode_lookup /
; asm_line / dasm — no KERNAL dependency, bundle-testable.
;
; Split from debugger.s at session 2026-04-20 (structural refactor,
; zero behavioural change).  debugger.s keeps the L4 parts: BRK/NMI
; dispatch state, step state machine, userland-transition gates.

        .setcpu "6502"

        .export bp_init
        .export bp_table, step_bp
        .export dbg_bp_hit
        .export dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .export dbg_bp_count
        .export dbg_bp_find
        .export patch_all, unpatch_all
        .export dbg_step_clear

        .importzp rp_ptr

BP_SLOTS    = 8
STEP_SLOTS  = 2
SLOT_SIZE   = 4
TOTAL_SLOTS = BP_SLOTS + STEP_SLOTS     ; 10

; ── BSS ────────────────────────────────────────────────────────────────
.segment "BSS"

; Unified breakpoint table — 10 slots × 4 bytes = 40 bytes.
; patch_all / unpatch_all iterate all 10 in one loop.
; bp_set / bp_del / bp_clear / bp_count / bp_find address slots 0–7.
bp_table:      .res (BP_SLOTS + STEP_SLOTS) * SLOT_SIZE

; `step_bp` = slots 8–9 of bp_table; addressed directly by cmd_step
; and the handler chain logic (not by the `b` command).
step_bp       = bp_table + BP_SLOTS * SLOT_SIZE

dbg_bp_hit:    .res 1          ; slot# of breakpoint hit ($FF = none)

; ── CODE ───────────────────────────────────────────────────────────────
.segment "CODE"

; ── bp_init ──────────────────────────────────────────────────────────
; Zero the full breakpoint table (40 bytes); set dbg_bp_hit = $FF.
; Called from dbg_init at cold boot.  debugger.s's dbg_init handles
; the step-state and ZP-buffer seed after this returns.
; Clobbers: A, X.
;
bp_init:
        ldx #TOTAL_SLOTS * SLOT_SIZE - 1       ; 39
        lda #0
@z:     sta bp_table,x
        dex
        bpl @z
        lda #$FF
        sta dbg_bp_hit
        rts

; ── dbg_bp_set ────────────────────────────────────────────────────────
; Set a breakpoint at the given address (user-visible slots 0–7).
; In:  A = addr lo, X = addr hi
; Out: C=0 success, A = slot number (0–7); C=1 table full (A=$FF).
; Clobbers: A, X, Y.
;
dbg_bp_set:
        sta rp_ptr
        stx rp_ptr+1

        ldy #0
        ldx #0
@find:  lda bp_table,x
        ora bp_table+1,x
        beq @found
        inx
        inx
        inx
        inx
        iny
        cpy #BP_SLOTS
        bne @find

        lda #$FF
        sec
        rts

@found: lda rp_ptr
        sta bp_table,x
        lda rp_ptr+1
        sta bp_table+1,x
        lda #0
        sta bp_table+2,x
        lda #1
        sta bp_table+3,x
        tya
        clc
        rts

; ── dbg_bp_del ────────────────────────────────────────────────────────
; Delete a breakpoint by slot number.
; In:  A = slot number (0–7)
; Out: C=0 success, C=1 invalid slot.
;
dbg_bp_del:
        cmp #BP_SLOTS
        bcs @bad
        asl
        asl
        tax
        lda #0
        sta bp_table,x
        sta bp_table+1,x
        sta bp_table+2,x
        sta bp_table+3,x
        clc
        rts
@bad:   lda #$FF
        sec
        rts

; ── dbg_bp_clear ──────────────────────────────────────────────────────
; Delete all user-visible breakpoints (slots 0–7).  Step slots untouched.
;
dbg_bp_clear:
        ldx #BP_SLOTS * SLOT_SIZE - 1
        lda #0
@z:     sta bp_table,x
        dex
        bpl @z
        rts

; ── dbg_bp_count ──────────────────────────────────────────────────────
; Count non-empty user-visible slots.
; Out: A = count (0–8).
;
dbg_bp_count:
        lda #0
        ldy #0
@cnt:   ldx bp_table,y
        bne @hit
        ldx bp_table+1,y
        beq @skip
@hit:   clc
        adc #1
@skip:  iny
        iny
        iny
        iny
        cpy #BP_SLOTS * SLOT_SIZE
        bne @cnt
        rts

; ── dbg_bp_find ───────────────────────────────────────────────────────
; Search user-visible slots 0–7 for a matching address.
; In:  A = addr lo, X = addr hi
; Out: C=0 found (A = slot 0–7); C=1 not found (A=$FF).
;
dbg_bp_find:
        sta rp_ptr
        stx rp_ptr+1
        ldy #0
        ldx #0
@loop:  lda bp_table,x
        cmp rp_ptr
        bne @next
        lda bp_table+1,x
        cmp rp_ptr+1
        bne @next
        tya
        clc
        rts
@next:  inx
        inx
        inx
        inx
        iny
        cpy #BP_SLOTS
        bne @loop
        lda #$FF
        sec
        rts

; ── patch_all ──────────────────────────────────────────────────────────
; Patch every enabled slot (bp + step): save original byte, write $00.
; Forward order: bp first, step last (so if a step slot overlaps a bp,
; unpatch's reverse order restores correctly).
; Clobbers: A, X, Y, rp_ptr.
;
patch_all:
        ldx #0
        ldy #0
@loop:  lda bp_table,x
        ora bp_table+1,x
        beq @next               ; empty slot
        lda bp_table+3,x
        beq @next               ; disabled
        lda bp_table,x
        sta rp_ptr
        lda bp_table+1,x
        sta rp_ptr+1
        lda (rp_ptr),y
        sta bp_table+2,x
        lda #$00
        sta (rp_ptr),y
@next:  inx
        inx
        inx
        inx
        cpx #(BP_SLOTS + STEP_SLOTS) * SLOT_SIZE
        bne @loop
        rts

; ── unpatch_all ────────────────────────────────────────────────────────
; Restore every patched slot: write saved byte back.  Reverse order.
;
unpatch_all:
        ldx #(BP_SLOTS + STEP_SLOTS - 1) * SLOT_SIZE    ; last slot offset
        ldy #0
@loop:  lda bp_table,x
        ora bp_table+1,x
        beq @next
        lda bp_table+3,x
        beq @next
        lda bp_table,x
        sta rp_ptr
        lda bp_table+1,x
        sta rp_ptr+1
        lda bp_table+2,x
        sta (rp_ptr),y
@next:  dex
        dex
        dex
        dex
        bpl @loop
        rts

; ── dbg_step_clear ────────────────────────────────────────────────────
; Zero both step slots (last 8 bytes of bp_table).
;
dbg_step_clear:
        lda #0
        ldx #STEP_SLOTS * SLOT_SIZE - 1
@z:     sta step_bp,x
        dex
        bpl @z
        rts
