; breakpoints.s — Breakpoint-table CRUD and patching (L3)
; Owner: doc/modules/breakpoints.md
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
;     Slot format (bp.inc): c64 4 bytes [addr_lo, addr_hi, saved_byte,
;     flags]; m65 6 bytes, a flat address [offset lo, hi, bank,
;     megabyte, saved_byte, flags].  flags bit 0 = enabled, bit 7 =
;     patched (set by patch_all, cleared by unpatch_all).
;   * `dbg_bp_hit`: slot number of the last breakpoint that fired
;     ($FF when none).  Written by the BRK/NMI handlers and
;     end_debug_body in main.s, and by dbg_bp_del / dbg_bp_clear
;     here; read by repl.s (break panel, `t`/`o`, `c`).  Lives here
;     because its semantics index into bp_table.
;   * `bp_init`: zeros the table and sets dbg_bp_hit = $FF.  Called
;     once by _main at cold init (the table survives warmstarts).
;   * `patch_all` / `unpatch_all`: iterate all 10 slots, save the
;     original byte and overwrite with $00 (BRK opcode) — or restore.
;     The shared 10-slot iteration is why the step slots live
;     physically in this table.
;   * `dbg_step_clear`: zero just slots 8–9 (the step-BP pair).
;
; Layer: L3 (core engines), same as addr_mode / expr / opcode_lookup /
; asm_line / dasm — no KERNAL dependency, bundle-testable.
; debugger.s (L4) holds the step state machine and the
; userland-transition gates that drive this table.

        .setcpu "6502"
        .include "platform.inc"
        .include "bp.inc"

        .export bp_init
        .export bp_table, step_bp
        .export dbg_bp_hit
        .export dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .export dbg_bp_count
        .export dbg_bp_find
        .export patch_all, unpatch_all
        .export dbg_step_clear
.ifdef PLATFORM_M65
        .export dbg_bp_set_flat, dbg_bp_find_flat, dbg_step_find, step_bp_arm
.endif

        .importzp rp_ptr

BP_SLOTS    = 8
STEP_SLOTS  = 2
TOTAL_SLOTS = BP_SLOTS + STEP_SLOTS     ; 10
PATCHED     = $80                       ; flags bit 7: $00 is in memory

; ── BSS ────────────────────────────────────────────────────────────────
.segment "BSS"

; Unified breakpoint table — 10 slots × SLOT_SIZE (40 / 60 bytes).
; patch_all / unpatch_all iterate all 10 in one loop.
; bp_set / bp_del / bp_clear / bp_count / bp_find address slots 0–7.
bp_table:      .res (BP_SLOTS + STEP_SLOTS) * SLOT_SIZE

; `step_bp` = slots 8–9 of bp_table; addressed directly by cmd_step
; and the handler chain logic (not by the `b` command).
step_bp       = bp_table + BP_SLOTS * SLOT_SIZE

dbg_bp_hit:    .res 1          ; slot# of breakpoint hit ($FF = none)
.ifdef PLATFORM_M65
bp_tmp:        .res 1          ; dbg_bp_del: slot × 2
.endif

; ── the slot walks (SLOT_SIZE bytes a slot) ─────────────────────────
.macro NEXT_SLOT_X
  .repeat SLOT_SIZE
        inx
  .endrepeat
.endmacro
.macro PREV_SLOT_X
  .repeat SLOT_SIZE
        dex
  .endrepeat
.endmacro
.macro NEXT_SLOT_Y
  .repeat SLOT_SIZE
        iny
  .endrepeat
.endmacro
; SLOT_PTR: rp_ptr := slot X's address — c64 its two bytes; m65 its flat
; address, all four (a breakpoint is its physical byte: no translation,
; so a remap since the patch cannot misplace the restore).
.macro SLOT_PTR
        lda bp_table,x
        sta rp_ptr
        lda bp_table+1,x
        sta rp_ptr+1
  .ifdef PLATFORM_M65
        lda bp_table+2,x
        sta rp_ptr+2
        lda bp_table+3,x
        sta rp_ptr+3
  .endif
.endmacro
; A := the slot's address bytes ORed (0: an empty slot).  m65: the bank
; too (0.0000 is no target).
.macro SLOT_OR_X
        lda bp_table,x
        ora bp_table+1,x
  .ifdef PLATFORM_M65
        ora bp_table+2,x
  .endif
.endmacro

; ── CODE ───────────────────────────────────────────────────────────────
.segment "CODE"

; ── bp_init ──────────────────────────────────────────────────────────
; Zero the full breakpoint table (40 bytes); set dbg_bp_hit = $FF.
; Called once by _main at cold init, before dbg_init (which handles
; the step state and the ZP-buffer seed).
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
; Set a breakpoint at the given address (user-visible slots 0–7).  An
; address that already has a breakpoint keeps its slot (no duplicate).
; In:  A = addr lo, X = addr hi
; Out: C=0 success, A = slot number (0–7); C=1 table full (A=$FF).
; Clobbers: A, X, Y, rp_ptr.
;
dbg_bp_set:
.ifdef PLATFORM_M65
        jsr bp_to_flat          ; rp_ptr := the CPU address, translated
; dbg_bp_set_flat — the same with the flat address already in rp_ptr.
dbg_bp_set_flat:
        jsr dbg_bp_find_flat
.else
        jsr dbg_bp_find         ; leaves the address in rp_ptr
.endif
        bcs @new
        rts                     ; already set: A = its slot, C = 0
@new:   ldy #0
        ldx #0
@find:  SLOT_OR_X
        beq @found
        NEXT_SLOT_X
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
.ifdef PLATFORM_M65
        lda rp_ptr+2
        sta bp_table+2,x
        lda rp_ptr+3
        sta bp_table+3,x
.endif
        lda #0
        sta bp_table+BP_SAVED,x
        lda #1
        sta bp_table+BP_FLAGS,x
        tya
        clc
        rts

; ── dbg_bp_del ────────────────────────────────────────────────────────
; Delete a breakpoint by slot number.  Deleting the slot dbg_bp_hit
; names sets dbg_bp_hit = $FF (the hit breakpoint is gone).
; In:  A = slot number (0–7)
; Out: C=0 success, C=1 invalid slot.
; Clobbers: A, X.
;
dbg_bp_del:
        cmp #BP_SLOTS
        bcs @bad
        cmp dbg_bp_hit
        bne @keep
        ldx #$FF
        stx dbg_bp_hit
@keep:
.ifdef PLATFORM_M65
        asl
        sta bp_tmp
        asl
        adc bp_tmp              ; slot × 6 (C=0: slot < 8)
        tax
        lda #0
        sta bp_table,x
        sta bp_table+1,x
        sta bp_table+2,x
        sta bp_table+3,x
        sta bp_table+4,x
        sta bp_table+5,x
.else
        asl
        asl
        tax
        lda #0
        sta bp_table,x
        sta bp_table+1,x
        sta bp_table+2,x
        sta bp_table+3,x
.endif
        clc
        rts
@bad:   lda #$FF
        sec
        rts

; ── dbg_bp_clear ──────────────────────────────────────────────────────
; Delete all user-visible breakpoints (slots 0–7), dbg_bp_hit = $FF.
; Step slots untouched.
; Clobbers: A, X.
;
dbg_bp_clear:
        lda #$FF
        sta dbg_bp_hit
        ldx #BP_SLOTS * SLOT_SIZE - 1
        lda #0
@z:     sta bp_table,x
        dex
        bpl @z
        rts

; ── dbg_bp_count ──────────────────────────────────────────────────────
; Count non-empty user-visible slots.
; Out: A = count (0–8).
; Clobbers: A, X, Y.
;
dbg_bp_count:
        lda #0
        ldy #0
@cnt:   ldx bp_table,y
        bne @hit
.ifdef PLATFORM_M65
        ldx bp_table+2,y        ; the bank
        bne @hit
.endif
        ldx bp_table+1,y
        beq @skip
@hit:   clc
        adc #1
@skip:  NEXT_SLOT_Y
        cpy #BP_SLOTS * SLOT_SIZE
        bne @cnt
        rts

; ── dbg_bp_find ───────────────────────────────────────────────────────
; Search user-visible slots 0–7 for a matching address.
; In:  A = addr lo, X = addr hi
; Out: C=0 found (A = slot 0–7); C=1 not found (A=$FF).
;      rp_ptr = the address.  $0000 matches the first empty slot.
; Clobbers: A, X, Y, rp_ptr.
;
dbg_bp_find:
.ifdef PLATFORM_M65
        jsr bp_to_flat          ; rp_ptr := the CPU address, translated
; dbg_bp_find_flat — the same with the flat address already in rp_ptr.
dbg_bp_find_flat:
.else
        sta rp_ptr
        stx rp_ptr+1
.endif
        ldy #0
        ldx #0
@loop:  lda bp_table,x
        cmp rp_ptr
        bne @next
        lda bp_table+1,x
        cmp rp_ptr+1
        bne @next
.ifdef PLATFORM_M65
        lda bp_table+2,x
        cmp rp_ptr+2
        bne @next
        lda bp_table+3,x
        cmp rp_ptr+3
        bne @next
.endif
        tya
        clc
        rts
@next:  NEXT_SLOT_X
        iny
        cpy #BP_SLOTS
        bne @loop
        lda #$FF
        sec
        rts

; ── patch_all ──────────────────────────────────────────────────────────
; Patch every enabled, not-yet-patched slot (bp + step): save original
; byte, write $00, set the slot's patched bit (flags bit 7).
; Forward order: bp first, step last (so if a step slot overlaps a bp,
; unpatch's reverse order restores correctly).
; Clobbers: A, X, Y, rp_ptr.
;
patch_all:
        ldx #0
        ldy #0
@loop:  SLOT_OR_X
        beq @next               ; empty slot
        lda bp_table+BP_FLAGS,x
        beq @next               ; disabled
        bmi @next               ; already patched — keep its saved byte
        ora #PATCHED
        sta bp_table+BP_FLAGS,x
        SLOT_PTR                ; rp_ptr := the slot's address
        FAR_LDA rp_ptr
        sta bp_table+BP_SAVED,x
        lda #$00
        FAR_STA rp_ptr
@next:  NEXT_SLOT_X
        cpx #(BP_SLOTS + STEP_SLOTS) * SLOT_SIZE
        bne @loop
        rts

; ── unpatch_all ────────────────────────────────────────────────────────
; Restore every patched slot (flags bit 7): write the saved byte back
; and clear the bit.  A slot that was never patched (set but not yet
; run, or disabled) is left alone.  Reverse order.
; Clobbers: A, X, Y, rp_ptr.
;
unpatch_all:
        ldx #(BP_SLOTS + STEP_SLOTS - 1) * SLOT_SIZE    ; last slot offset
        ldy #0
@loop:  lda bp_table+BP_FLAGS,x
        bpl @next               ; not patched
        and #<~PATCHED
        sta bp_table+BP_FLAGS,x
        SLOT_PTR                ; rp_ptr := the slot's address
        lda bp_table+BP_SAVED,x
        FAR_STA rp_ptr
@next:  PREV_SLOT_X
        bpl @loop
        rts


.ifdef PLATFORM_M65
; ── bp_to_flat — rp_ptr := the CPU address A/X through the program's
; bank state (mem.md § far_user).  Clobbers X.
bp_to_flat:
        sta rp_ptr
        stx rp_ptr+1
        FAR_USER rp_ptr
        rts

; ── dbg_step_find — is the CPU address A/X (a break's PC) one of the
; step slots' physical bytes?  C=0 yes.  Clobbers A, X, Y, rp_ptr.
dbg_step_find:
        jsr bp_to_flat
        ldx #BP_SLOTS * SLOT_SIZE
        ldy #STEP_SLOTS
@lp:    lda bp_table,x
        cmp rp_ptr
        bne @no
        lda bp_table+1,x
        cmp rp_ptr+1
        bne @no
        lda bp_table+2,x
        cmp rp_ptr+2
        bne @no
        lda bp_table+3,x
        cmp rp_ptr+3
        bne @no
        clc
        rts
@no:    NEXT_SLOT_X
        dey
        bne @lp
        sec
        rts

; ── step_bp_arm — arm step slot Y (0 or SLOT_SIZE) at the CPU address
; A/X: its physical byte under the program's bank state, enabled.
; Clobbers A, X, rp_ptr.
step_bp_arm:
        jsr bp_to_flat
        ldx #0
@cp:    lda rp_ptr,x
        sta step_bp,y
        iny
        inx
        cpx #4
        bne @cp
        lda #1
        sta step_bp+1,y         ; Y = slot + 4: the flags at slot + 5
        rts
.endif

; ── dbg_step_clear ────────────────────────────────────────────────────
; Zero both step slots (the last STEP_SLOTS × SLOT_SIZE bytes).
; Clobbers: A, X.
;
dbg_step_clear:
        lda #0
        ldx #STEP_SLOTS * SLOT_SIZE - 1
@z:     sta step_bp,x
        dex
        bpl @z
        rts
