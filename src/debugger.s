; debugger.s — Breakpoints, tracing, and kernel↔userland gates
;                (Phase 18 — ISR-kernel model)
;
; Owns:
;   * `bp_table`: unified 10-slot breakpoint table.
;     Slots 0–7: user-visible breakpoints (managed by `b` command).
;     Slots 8–9: ad-hoc step BRKs (alias `step_bp`).  patch_all /
;                unpatch_all iterate all 10 slots.
;   * `save_userland_state` / `restore_userland_state`: the two
;     complementary gate primitives for kernel↔userland transitions.
;   * `return_to_userland`: wrapper that pushes a fresh brk_stub sentinel
;     before falling into `restore_userland_state`.  Used for fresh
;     execution starts (`j`, cold-init handoff).  Resumes (`c`, `t`,
;     `o`, handler chain) call `restore_userland_state` directly —
;     the existing sentinel from the prior fresh start is still valid.
;   * `step_next_pc` / `arm_step_bp`: step-chain helpers shared
;     between cmd_step (seed) and cse_brk_handler (chain).
;
; BRK/NMI dispatch itself (`cse_brk_handler`, `cse_nmi_handler`)
; lives in main.s; those handlers call `save_userland_state` after
; classification and either `restore_userland_state` (chain) or
; `handler_finalize` (longjmp to main_loop_top).
;
; References: doc/design_cse_as_kernel.md, doc/userland_contract.md,
;             doc/modules/debugger.md, doc/memory_design.md § Stack
;             contract.

        .setcpu "6502"
        .macpack longbranch

        .export dbg_init
        .export dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .export dbg_bp_count
        .export dbg_bp_find
        .export bp_table, step_bp
        .export brk_pc, dbg_bp_hit      ; dbg_reason → zp.s (Phase 21 Move 4)
        .export dbg_step_clear
        .export patch_all, unpatch_all

        .export save_userland_state, restore_userland_state
        .export return_to_userland
        .export brk_stub
        .export step_next_pc
        .export arm_step_bp
        .export step_state
        .export step_remaining
        .export step_next_lo, step_next_hi
        .export kernel_stack_budget

        .importzp rp_ptr, rp_ptr2
        .import reg_a, reg_x, reg_y, reg_sp, reg_p
        .import kernel_zp_buf, userland_zp_buf
        .importzp in_userland     ; zp.s (Phase 21 Move 4)
        .importzp dbg_reason      ; zp.s (Phase 21 Move 4)
        .import oplen_tbl
        .importzp asm_cpu
        .import save_userland_zp, restore_userland_zp
        .import save_kernel_zp, restore_kernel_zp

; Reason codes (DBG_NONE/DBG_BRK/DBG_NMI) are declared in main.s
; where cse_brk_handler / cse_nmi_handler actually assign dbg_reason.

BP_SLOTS    = 8
STEP_SLOTS  = 2
SLOT_SIZE   = 4
TOTAL_SLOTS = BP_SLOTS + STEP_SLOTS     ; 10
; Size of the BSS window that dbg_init zeros in one sweep: the
; 40-byte bp_table plus the 11 bytes of adjacent debug state
; (brk_pc, dbg_bp_hit, step_state, step_remaining,
;  step_next_lo, step_next_hi, step_save, _rtu_need_sentinel).
; dbg_reason moved to zp.s (Phase 21 Move 4) — zeroed explicitly.
DBG_STATE_SIZE = TOTAL_SLOTS * SLOT_SIZE + 11

; Step mode (stored in step_state)
STEP_NONE = 0
STEP_INTO = 1
STEP_OVER = 2

; User-side stack headroom contract (conservative-pending-empirical;
; see userland_contract.md § 4).  One-byte change here + a doc edit
; tightens the contract post-audit.
kernel_stack_budget = 64

; ── BSS ────────────────────────────────────────────────────────────────
.segment "BSS"

; Unified breakpoint table — 10 slots × 4 bytes = 40 bytes.
; patch_all / unpatch_all iterate all 10 in one loop.
; bp_set / bp_del / bp_clear / bp_count / bp_find address slots 0–7.
bp_table:      .res (BP_SLOTS + STEP_SLOTS) * SLOT_SIZE

; `step_bp` = slots 8–9 of bp_table; addressed directly by cmd_step
; and the handler chain logic (not by the `b` command).
step_bp       = bp_table + BP_SLOTS * SLOT_SIZE

; dbg_reason moved to zp.s (Phase 21 Move 4)
brk_pc:        .res 2          ; PC where break occurred / resume address
dbg_bp_hit:    .res 1          ; slot# of breakpoint hit ($FF = none)

; Handler-resident step-chain state.
step_state:    .res 1          ; STEP_NONE / STEP_INTO / STEP_OVER
step_remaining: .res 1         ; iterations left after current step

; step_next_pc output.
step_next_lo:  .res 2          ; first candidate next-PC (0 = stop)
step_next_hi:  .res 2          ; second candidate (branch alternative)
step_save:     .res 1          ; opcode/packed-oplen scratch

; Sentinel-push flag for the shared restore tail.  Set by
; return_to_userland (=1) or restore_userland_state (=0).
_rtu_need_sentinel: .res 1

; ── CODE ───────────────────────────────────────────────────────────────
.segment "CODE"

; ── dbg_init ──────────────────────────────────────────────────────────
; Zero breakpoint + step tables and all debugger state.
; Does NOT touch in_userland (owned by main.s).
; Clobbers: A, X.
;
dbg_init:
        ; Zero bp_table[0..50] in one sweep: 40 bytes of bp/step slots
        ; plus 11 bytes of debug state (brk_pc, dbg_bp_hit, step_state,
        ; step_remaining, step_next_lo/hi, step_save, _rtu_need_sentinel)
        ; laid out contiguously in BSS.  Then fix up the two bytes
        ; that need $FF, the cross-module reg_* bytes in asm_line.s BSS,
        ; and dbg_reason (which lives in zp.s after Phase 21 Move 4).
        ldx #DBG_STATE_SIZE - 1
        jsr clear_bp_x
        ; A = 0 from clear_bp_x — zero the reg_* bytes in asm_line.s BSS.
        sta reg_a
        sta reg_x
        sta reg_y
        sta reg_p
        sta dbg_reason          ; Phase 21: separate zero; lives in zp.s
        lda #$FF
        sta reg_sp              ; user's stack begins empty
        sta dbg_bp_hit

        ; Bootstrap seed for the CPU-port bytes in both ZP backup
        ; buffers.  See the "CPU-port aware ZP save/restore" note
        ; in mem.s for the full protocol.  Summary:
        ;
        ;   Without this seed, the first return_to_userland (which
        ;   restores userland_zp_buf → live ZP) writes $00=$00 to the
        ;   DDR register, setting all CPU-port pins to input.  Then
        ;   writes to $01 can't latch on bits 0-5 (banking, I/O),
        ;   the CPU port goes floating, and the next RTI/fetch sees
        ;   an undefined banking state — typically JAM at a random
        ;   stack-page address.  Same failure applies to the first
        ;   BRK handler's kernel-ZP restore if kernel_zp_buf is also
        ;   BSS-zero.
        ;
        ;   Seed both buffers with the CSE-kernel's default CPU port:
        ;     $00 = $2F (DDR: bits 0-5 output, 6-7 input — C64 default)
        ;     $01 = $36 (KERNAL in, BASIC out, I/O in — CSE state)
        ;
        ;   After the very first user-exit cycle, save_userland_zp
        ;   and save_kernel_zp (in mem.s) overwrite these seeds with
        ;   real captured values.
        lda #$2F
        sta userland_zp_buf + $00
        sta kernel_zp_buf + $00
        lda #$36
        sta userland_zp_buf + $01
        sta kernel_zp_buf + $01
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
        ; fall through

; ── clear_bp_x — zero bp_table[0..X] ─────────────────────
clear_bp_x:
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

; ═══════════════════════════════════════════════════════════════════════
; Gate primitive — userland → kernel.
; ═══════════════════════════════════════════════════════════════════════

; ── save_userland_state ─────────────────────────────────────────────
; Invoked from cse_brk_handler and (after stack normalization) from
; cse_nmi_handler, once classification has decided the event is a
; userland-mode break.  Stack at entry (by convention — NMI path
; pre-pushes A/X/Y to match):
;   SP+1: Y    (KERNAL $FF48 push, or NMI handler normalization)
;   SP+2: X
;   SP+3: A
;   SP+4: P    (CPU push)
;   SP+5: PClo (CPU push)
;   SP+6: PChi (CPU push)
;
; Effects:
;   * reg_y/reg_x/reg_a/reg_p populated from stack bytes (raw — caller
;     applies the P mask appropriate to BRK vs NMI).
;   * brk_pc populated with the raw stacked PC (caller adjusts −2
;     for BRK; leaves as-is for NMI).
;   * reg_sp = user's pre-interrupt SP = current SP + 6.
;   * userland_zp_buf snapshot of live ZP (user's).
;   * kernel ZP restored from kernel_zp_buf (zone is now kernel-usable).
;
; Clobbers: A, X, Y.  Stack contents preserved (caller may still need
; to reference them via tsx; save_userland_state only reads).
;
save_userland_state:
        ; 1. Extract CPU + KERNAL push frame.
        ; Called via jsr — 2 extra bytes (return addr) sit on top of
        ; the interrupt frame.  tsx gives SP at function entry (after
        ; the jsr push); the frame is at SP+3..SP+8 (not SP+1..SP+6).
        tsx
        lda $0103,x
        sta reg_y
        lda $0104,x
        sta reg_x
        lda $0105,x
        sta reg_a
        lda $0106,x
        sta reg_p
        lda $0107,x
        sta brk_pc
        lda $0108,x
        sta brk_pc+1

        ; 2. reg_sp = user's pre-interrupt SP = current SP + 8
        ;    (2 jsr ret addr + 6 interrupt frame).
        txa
        clc
        adc #8
        sta reg_sp

        ; 3. Swap ZP: user's live → userland_zp_buf, then kernel's
        ;    kernel_zp_buf → live.  Both helpers are CPU-port aware
        ;    (see mem.s § CPU-port aware ZP save/restore).
        ;
        ; COUPLING: the chain save_userland_zp → restore_kernel_zp
        ; relies on DDR=$FF for restore_kernel_zp's `sta $01` to latch
        ; every bit.  save_userland_zp's postcondition is exactly that
        ; (live $00=$FF after the save loop), and restore_kernel_zp is
        ; only ever reached via that save — so it trusts the invariant
        ; rather than re-asserting `lda #$FF / sta $00` at entry.  If
        ; you ever add a new caller of restore_kernel_zp that doesn't
        ; come through save_userland_zp first, it MUST establish the
        ; DDR=$FF precondition itself.
        ;
        ; Post-exit invariant: live $00=$2F, $01=$36 (from
        ; kernel_zp_buf's [0]/[1], seeded by dbg_init and maintained
        ; by save_kernel_zp on every k→u transition).
        jsr save_userland_zp
        jmp restore_kernel_zp       ; tail call (rts via restore_kernel_zp)

; ═══════════════════════════════════════════════════════════════════════
; Gate primitive — kernel → userland.
; ═══════════════════════════════════════════════════════════════════════

; ── return_to_userland ──────────────────────────────────────────────────
; Wrapper that pushes a fresh (brk_stub - 1) sentinel for the user's
; top-level RTS clean-exit path, then falls through to
; restore_userland_state.  Used for fresh execution starts:
;   * `j` / `g` commands (user begins at new PC).
;   * cold-init userland handoff (first ever transition).
;
; Do NOT call from resume paths (`c`, `t`, `o`, step-chain): the
; existing sentinel from the prior fresh start is still valid, and
; pushing another would creep the stack by 2 bytes per resume.
; Resume paths jump to restore_userland_state directly.
return_to_userland:
        lda #1
        sta _rtu_need_sentinel
        jmp _rtu_body

; ── restore_userland_state ──────────────────────────────────────────
; Complement of save_userland_state.  Complete userland reinstall:
;   * patch_all (breakpoints active while user runs).
;   * Save kernel ZP → kernel_zp_buf (kernel ZP will be inaccessible
;     from RTI until the next save_userland_state).
;   * Restore user ZP ← userland_zp_buf.
;   * Switch SP to user's reg_sp.  This is a no-op on the normal
;     main_loop path (SP already equals reg_sp by invariant —
;     handler_finalize longjmps SP to reg_sp before jumping to
;     main_loop_top, and main_loop's stack use is balanced).  It
;     fires as a correction on:
;       (a) the step-chain path (SP was BRK-frame-deep);
;       (b) after the user edited reg_sp via `r sp:XX`.
;   * Push RTI frame (P, PChi, PClo).
;   * Set in_userland = $80 (bit 7 set — cse_nmi_handler tests
;     it via `bit / bmi`, which is A-independent).
;   * Load user A/X/Y from reg_*.
;   * RTI — CPU pops P/PClo/PChi, control transfers to user code.
;
; Called directly from main_loop (resume paths) and from the
; cse_brk_handler step-chain body.  Does NOT return.
restore_userland_state:
        lda #0
        sta _rtu_need_sentinel
        ; fall through to _rtu_body

_rtu_body:
        jsr patch_all

        ; Swap ZP: kernel's live → kernel_zp_buf, then user's
        ; userland_zp_buf → live.  Both helpers are CPU-port aware
        ; (see mem.s § CPU-port aware ZP save/restore).
        jsr save_kernel_zp
        jsr restore_userland_zp

        ; Switch SP to user's reg_sp (see header).
        ldx reg_sp
        txs

        ; Optional sentinel push (fresh start only).
        lda _rtu_need_sentinel
        beq @no_sent
        lda #>(brk_stub - 1)
        pha
        lda #<(brk_stub - 1)
        pha
@no_sent:

        ; Push RTI frame — RTI pops in order (P, PClo, PChi), so the
        ; push order must be the reverse: PChi first, PClo second, P
        ; last.  That lays the stack bytes out (bottom → top): PChi,
        ; PClo, P — which is exactly what RTI's pull sequence expects.
        lda brk_pc+1
        pha
        lda brk_pc
        pha
        lda reg_p
        pha

        ; in_userland uses the $80/0 convention so cse_nmi_handler
        ; can test it via `bit / bmi` (N flag = bit 7 of operand,
        ; independent of A).  At NMI entry A holds the user's live
        ; value and we can't reliably clobber it with `lda`.
        lda #$80
        sta in_userland

        ldx reg_x
        ldy reg_y
        lda reg_a
        rti

; ── brk_stub ────────────────────────────────────────────────────────
; Fixed code address where user's top-level RTS lands after popping
; the sentinel pushed by return_to_userland.  BRK + 1 signature byte.
brk_stub:
        brk
        .byte $42               ; signature (arbitrary non-$00)

; ═══════════════════════════════════════════════════════════════════════
; Step-chain helpers (shared between cmd_step seed and handler chain).
; ═══════════════════════════════════════════════════════════════════════

; ── step_next_pc ────────────────────────────────────────────────────
; From the opcode at brk_pc, compute the next-PC(s) for stepping.
; Writes step_next_lo / step_next_hi (0 = unused).
;
; Opcode dispatch:
;   Linear:          step_next_lo = brk_pc + length (via oplen_tbl)
;   Cond branch:     STEP_INTO — step_next_lo = taken,
;                                 step_next_hi = fall-through
;                    STEP_OVER — step_next_lo = fall-through only
;   JMP abs:         step_next_lo = operand
;   JMP (ind):       step_next_lo = peek16(operand)
;   JMP (abs,x):     65C02 only — peek16(operand + x)
;   BRA:             65C02 only — branch target
;   JSR abs:         STEP_INTO + RAM target (<$E000) — step_next_lo = target
;                    otherwise — step_next_lo = brk_pc + 3 (over)
;   RTS/RTI/BRK:     both slots left 0 (caller stops)
;
; In:  brk_pc, step_state.  Out: step_next_lo, step_next_hi.
; Clobbers: A, X, Y, rp_ptr, rp_ptr2, step_save.
;
.proc step_next_pc
        lda #0
        sta step_next_lo
        sta step_next_lo+1
        sta step_next_hi
        sta step_next_hi+1

        lda brk_pc
        sta rp_ptr2
        lda brk_pc+1
        sta rp_ptr2+1

        ldy #0
        lda (rp_ptr2),y
        sta step_save           ; opcode

        jeq @stop               ; BRK $00

        cmp #$20
        jeq @jsr

        cmp #$60
        jeq @stop               ; RTS
        cmp #$40
        jeq @stop               ; RTI

        cmp #$4C
        jeq @jmp_abs

        cmp #$6C
        jeq @jmp_ind

.ifdef CMOS_SUPPORT
        cmp #$7C
        bne @not_7c
        lda asm_cpu
        cmp #2
        bcc @not_7c
        ; JMP (abs,x)
        ldy #1
        lda (rp_ptr2),y
        clc
        adc reg_x
        sta rp_ptr
        iny
        lda (rp_ptr2),y
        adc #0
        sta rp_ptr+1
        ldy #0
        lda (rp_ptr),y
        sta step_next_lo
        iny
        lda (rp_ptr),y
        sta step_next_lo+1
        rts
@not_7c:
        lda step_save
        cmp #$80
        bne @not_bra
        lda asm_cpu
        cmp #2
        bcc @not_bra
        jsr compute_rel_target
        rts
@not_bra:
.endif

        ; Conditional branch: (opc & $1F) == $10
        lda step_save
        and #$1F
        cmp #$10
        bne @linear

        ; Branch: INTO arms both; OVER arms fall-through only.
        lda step_state
        cmp #STEP_OVER
        beq @branch_over
        jsr compute_rel_target
        lda brk_pc
        clc
        adc #2
        sta step_next_hi
        lda brk_pc+1
        adc #0
        sta step_next_hi+1
        rts
@branch_over:
        lda brk_pc
        clc
        adc #2
        sta step_next_lo
        lda brk_pc+1
        adc #0
        sta step_next_lo+1
        rts

@linear:
        ; Linear insn: next = brk_pc + oplen(opc).
        ; Packed oplen_tbl: 2 bits/opcode, 4 opcodes/byte.
        lda step_save
        and #$03                ; position 0–3
        tay
        lda step_save
        lsr
        lsr
        tax
        lda oplen_tbl,x
        cpy #0
        beq @len_done
@len_shift:
        lsr
        lsr
        dey
        bne @len_shift
@len_done:
        and #$03
        clc
        adc brk_pc
        sta step_next_lo
        lda #0
        adc brk_pc+1
        sta step_next_lo+1
        rts

@jsr:
        lda step_state
        cmp #STEP_OVER
        beq @jsr_over
        ; INTO: step into only if target is RAM (<$E000).  KERNAL ROM
        ; can't be BRK-patched.
        ldy #2
        lda (rp_ptr2),y
        cmp #$E0
        bcc @jsr_into
@jsr_over:
        lda brk_pc
        clc
        adc #3
        sta step_next_lo
        lda brk_pc+1
        adc #0
        sta step_next_lo+1
        rts
@jsr_into:
        ldy #1
        lda (rp_ptr2),y
        sta step_next_lo
        iny
        lda (rp_ptr2),y
        sta step_next_lo+1
        rts

@jmp_abs:
        ldy #1
        lda (rp_ptr2),y
        sta step_next_lo
        iny
        lda (rp_ptr2),y
        sta step_next_lo+1
        rts

@jmp_ind:
        ldy #1
        lda (rp_ptr2),y
        sta rp_ptr
        iny
        lda (rp_ptr2),y
        sta rp_ptr+1
        ldy #0
        lda (rp_ptr),y
        sta step_next_lo
        iny
        lda (rp_ptr),y
        sta step_next_lo+1
        rts

@stop:
        rts
.endproc

; ── compute_rel_target ──────────────────────────────────────────────
; step_next_lo = brk_pc + 2 + sign_extend(byte_at(rp_ptr2+1)).
; Shared between branch and BRA paths.
;
.proc compute_rel_target
        ldy #1
        lda (rp_ptr2),y
        bpl @pos
        ldy #$FF
        .byte $2C               ; BIT abs — skip next 2 bytes
@pos:   ldy #0
        clc
        adc brk_pc
        sta step_next_lo
        tya
        adc brk_pc+1
        sta step_next_lo+1
        lda step_next_lo
        clc
        adc #2
        sta step_next_lo
        bcc :+
        inc step_next_lo+1
:       rts
.endproc

; ── arm_step_bp ─────────────────────────────────────────────────────
; Install step_next_lo / step_next_hi into the two step_bp slots.
; Zero entries (no target) leave slots un-armed.
; Clobbers: A, X.
;
arm_step_bp:
        jsr dbg_step_clear
        lda step_next_lo
        ora step_next_lo+1
        beq @try_hi
        lda step_next_lo
        sta step_bp
        lda step_next_lo+1
        sta step_bp+1
        lda #1
        sta step_bp+3
@try_hi:
        lda step_next_hi
        ora step_next_hi+1
        beq @done
        lda step_next_hi
        sta step_bp+4
        lda step_next_hi+1
        sta step_bp+5
        lda #1
        sta step_bp+7
@done:  rts

; CPU-port aware ZP save/restore primitives — save_userland_zp /
; restore_userland_zp / save_kernel_zp / restore_kernel_zp — live
; in mem.s.  See the technical note above them there for the full
; design rationale (DDR masking, single-pass DDR-stash, backwards
; copy with DDR=$FF).
