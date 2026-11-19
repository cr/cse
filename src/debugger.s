; debugger.s — Step state machine + kernel↔userland gates (L4)
; Owner: doc/modules/debugger.md
;                (ISR-kernel model)
;
; Owns:
;   * Step state machine: `step_state`, `step_remaining` (16-bit), `step_next_*`,
;     step_save, step_next_pc, arm_step_bp.
;   * `brk_pc`: the PC where the last break occurred (resume address).
;   * `save_userland_state` / `restore_userland_state`: the two
;     complementary gate primitives for kernel↔userland transitions.
;   * `return_to_userland`: wrapper that pushes a fresh brk_stub sentinel
;     before falling into `restore_userland_state`.  Used for fresh
;     execution starts (MODE_JUMP: `j`/`g`, and the first `t`/`o`/`c`
;     after a cold preview).  Resumes (MODE_RESUME, handler chain)
;     use `restore_userland_state` directly — the existing sentinel
;     from the session's fresh start is still valid.
;   * `dbg_init`: cold-init / warm-recovery entry point.  Zeros the
;     step-state block, the reg_* shadows, dbg_reason, and seeds the
;     CPU-port bytes in the ZP save buffers.  Leaves bp_table alone
;     (main.s's cold init calls bp_init itself).
;
; Breakpoint-table CRUD + patching lives in breakpoints.s (L3) — a
; clean data-structure module that bundle-tests in isolation without
; needing any of the BRK/NMI/userland-transition machinery here.
; This module (L4) imports from breakpoints.s the entry points and
; BSS symbols it actually references.
;
; BRK/NMI dispatch itself (`cse_brk_handler`, `cse_nmi_handler`)
; lives in main.s; those handlers call `save_userland_state` after
; classification and either `restore_userland_state` (chain) or
; `handler_finalize` (longjmp to main_loop_top).
;
; References: doc/design_cse_as_kernel.md, doc/userland_contract.md,
;             doc/modules/debugger.md, doc/modules/breakpoints.md,
;             doc/memory_design.md § Stack contract.

        .setcpu "6502"
        .include "platform.inc"
        .macpack longbranch

        .export dbg_init
        .export brk_pc
        .export save_userland_state, restore_userland_state
        .export return_to_userland
.ifdef PLATFORM_C64
        .export brk_stub
.else
        .import brk_stub                ; mem.s's resident stub
.endif
        .export step_next_pc
        .export arm_step_bp
        .export step_state
        .export step_remaining
        .export step_next_lo, step_next_hi

        .importzp rp_ptr, rp_ptr2
        .import reg_a, reg_x, reg_y, reg_sp, reg_p
.ifdef PLATFORM_C64
        .import kernel_zp_buf, userland_zp_buf
.else
        .import reg_z, reg_b, stub_user
        .importzp userland_zp_buf, um_map, um_d030
.endif
        .importzp in_userland     ; zp.s
        .importzp dbg_reason      ; zp.s
        .import oplen_tbl
        .importzp asm_cpu
.ifdef PLATFORM_C64
        .import save_userland_zp, restore_userland_zp
        .import save_kernel_zp, restore_kernel_zp
.endif

        ; From breakpoints.s (L3, strictly-downward):
        .import patch_all
        .import step_bp
        .import dbg_step_clear

; Reason codes (DBG_NONE/DBG_RTS/DBG_BRK/DBG_NMI) are defined in
; dbg_reason.inc (included by main.s and repl.s, which assign and test
; dbg_reason); this module only zeroes it.

; Step mode (stored in step_state)
STEP_NONE = 0
STEP_INTO = 1
STEP_OVER = 2

; Size of the step-state BSS window zeroed by dbg_init (11 bytes:
; brk_pc, step_state, step_remaining, step_next_lo, step_next_hi,
; step_save, _rtu_need_sentinel — declared contiguously below).
STEP_STATE_SIZE = 11

; ── BSS ────────────────────────────────────────────────────────────────
.segment "BSS"

; Eleven bytes, declared contiguously so dbg_init can zero them in one
; sweep (brk_pc..._rtu_need_sentinel, total 11 bytes = STEP_STATE_SIZE).
brk_pc:        .res 2          ; PC where break occurred / resume address

; Handler-resident step-chain state.
step_state:    .res 1          ; STEP_NONE / STEP_INTO / STEP_OVER
step_remaining: .res 2         ; iterations left after current step (16-bit)

; step_next_pc output.
step_next_lo:  .res 2          ; first candidate next-PC (0 = stop)
step_next_hi:  .res 2          ; second candidate (branch alternative)
step_save:     .res 1          ; opcode/packed-oplen scratch

; Sentinel-push flag for the shared restore tail.  Set by
; return_to_userland (=1) or restore_userland_state (=0).
_rtu_need_sentinel: .res 1
.ifdef PLATFORM_M65
um_kmap:        .res 4          ; the program's KERNAL map record (P3) and
um_sysflags:    .res 1          ;   its SYSFLAGS (P2): its bank state
.endif

; ── CODE ───────────────────────────────────────────────────────────────
.segment "CODE"

; ── dbg_init ──────────────────────────────────────────────────────────
; Cold-init and warm-recovery entry point (_main, hw_reinit_body).
; Zero the step-state block here, zero reg_* shadows + dbg_reason, set
; reg_sp = $FF, seed CPU-port bytes in both ZP backup buffers.  The
; breakpoint table is NOT touched: _main zeroes it once (bp_init) and
; it survives cse_recover (memory_design.md § Breakpoint invariant).
; Clobbers: A, X.
;
dbg_init:
        ; Zero the 11-byte step-state block in one sweep.
        ldx #STEP_STATE_SIZE - 1
        lda #0
@z:     sta brk_pc,x
        dex
        bpl @z
        ; A = 0
        sta reg_a
        sta reg_x
        sta reg_y
        sta reg_p
.ifdef PLATFORM_M65
        sta reg_z
        sta reg_b
.endif
        sta dbg_reason
        lda #STACK_TOP
        sta reg_sp              ; user's stack begins empty

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
        ;
        ;   m65: reg_z / reg_b zeroed; the saved bank state seeded with
        ;   the run premise's (seed_bank_state); no kernel_zp_buf.
.ifdef PLATFORM_C64
        lda #DDR_SEED
        sta userland_zp_buf + CPU_DDR
        sta kernel_zp_buf + CPU_DDR
        lda #PORT_SEED
        sta userland_zp_buf + CPU_PORT
        sta kernel_zp_buf + CPU_PORT
        rts
.endif                          ; m65: fall through

.ifdef PLATFORM_M65
; ── seed_bank_state (m65) ───────────────────────────────────────────
; The saved bank state := the run premise's (platform_layer.md § User
; transitions): the user map, the port $FF/$85, $D030 = $64, the user
; map in the KERNAL's map record, SYSFLAGS 0 — after bank_state_swap
; has put CSE's in place (what it captures, the seed overwrites).
; um_map, userland_zp_buf and um_d030 are contiguous in CSE's base page
; (zp.s); um_kmap and um_sysflags in debugger.s's BSS.  Clobbers: A, X.
BANK_STATE_SIZE = 6 + ZP_SAVE_LEN + 1
seed_bank_state:
        jsr bank_state_swap     ; CSE's record and $D030 (the cold start's)
        ldx #BANK_STATE_SIZE - 1
@s:     lda bank_premise,x
        sta um_map,x
        dex
        bpl @s
        ldx #4                  ; the record: the user map; SYSFLAGS 0
@k:     lda kmap_user,x
        sta um_kmap,x
        dex
        bpl @k
        rts
        .assert userland_zp_buf = um_map + 6 && um_d030 = userland_zp_buf + ZP_SAVE_LEN, error, "the bank state is one block"
        .assert um_sysflags = um_kmap + 4, error, "kmap_user's last byte is um_sysflags'"

.segment "RODATA"
bank_premise:
        .byte MAP_USER_X, MAP_USER_A, MAP_USER_Z, MAP_USER_Y, 0, 0
        .byte DDR_SEED, PORT_SEED
        .byte D030_SEED
kmap_user:                      ; um_kmap, um_sysflags
        .byte MAP_USER_A, MAP_USER_X, MAP_USER_Y, MAP_USER_Z, 0
kmap_cse_rec:
        .byte MAP_CSE_A, MAP_CSE_X, MAP_CSE_Y, MAP_CSE_Z
.segment "CODE"

.endif

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
; The frame offsets derive from FRAME_DEPTH (platform_layer.md
; § Interrupt frame): the stacked P sits FRAME_DEPTH bytes above the
; frame's top, which is just past this routine's 2-byte return
; address; A X Y are 1 2 3 below P on every platform (m65's Z and B
; lie above them).
_SUS_RET  = 2                           ; jsr return address
_SUS_P    = $0100 + 1 + _SUS_RET + FRAME_DEPTH  ; stacked P, indexed by SP

save_userland_state:
        ; 1. Extract CPU + KERNAL push frame.
        ; Called via jsr — 2 extra bytes (return addr) sit on top of
        ; the interrupt frame.  tsx gives SP at function entry (after
        ; the jsr push); on c64 the frame is at SP+3..SP+8.
        tsx
        lda _SUS_P - 3,x
        sta reg_y
        lda _SUS_P - 2,x
        sta reg_x
        lda _SUS_P - 1,x
        sta reg_a
        lda _SUS_P,x
        sta reg_p
        lda _SUS_P + 1,x
        sta brk_pc
        lda _SUS_P + 2,x
        sta brk_pc+1
.ifdef PLATFORM_M65
        lda _SUS_P - 4,x        ; the KERNAL's frame: B Z above Y X A
        sta reg_z
        lda _SUS_P - 5,x
        sta reg_b
.endif

        ; 2. reg_sp = user's pre-interrupt SP = current SP + the jsr
        ;    return address + the frame + the CPU's P PCL PCH (c64: 8).
        txa
        clc
        adc #_SUS_RET + FRAME_DEPTH + 3
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
        ;
        ; m65: no swap — the transitions switch B (§ Base page).  The
        ; stub captured the port and the map; the rest of the bank
        ; state is the kernel's to swap (bank_state_swap, below).
.ifdef PLATFORM_C64
        jsr save_userland_zp
        jmp restore_kernel_zp       ; tail call (rts via restore_kernel_zp)
.else
        ; fall through

; ── bank_state_swap (m65) ───────────────────────────────────────────
; The bank state the kernel holds (platform_layer.md § User
; transitions): the program's into um_kmap, um_d030 and um_sysflags,
; CSE's in place — the CSE map into the KERNAL's map record first, so
; a KERNAL far call (CBDOS's disk calls) MAPs back to CSE, then the
; premise's $D030 before the kernel uses the interface ROM.  CSE's
; SYSFLAGS bits come with the hygiene.  At every break, and first in
; seed_bank_state (the cold start's).  Clobbers: A, X.
bank_state_swap:
        ldx #3
@k:     lda KMAP_REC,x
        sta um_kmap,x
        lda kmap_cse_rec,x
        sta KMAP_REC,x
        dex
        bpl @k
        lda D030_ROMBANK
        sta um_d030
        lda #D030_SEED
        sta D030_ROMBANK
        sec
        KCALL SYSFLAGS
        sta um_sysflags
        rts
.endif

; ═══════════════════════════════════════════════════════════════════════
; Gate primitive — kernel → userland.
; ═══════════════════════════════════════════════════════════════════════

; ── return_to_userland ──────────────────────────────────────────────────
; Wrapper that pushes a fresh (brk_stub - 1) sentinel for the user's
; top-level RTS clean-exit path, then falls through to
; restore_userland_state.  Used for fresh execution starts
; (run_user_pending = MODE_JUMP):
;   * `j` / `g` commands (user begins at new PC).
;   * the first `t` / `o` / `c` after a cold preview (no sentinel
;     on the user stack yet).
;
; Do NOT call from resume paths (MODE_RESUME, step-chain): the
; existing sentinel from the prior fresh start is still valid, and
; pushing another would creep the stack by 2 bytes per resume.
; Resume paths jump to restore_userland_state directly.
return_to_userland:
.ifdef PLATFORM_M65
        jsr seed_bank_state     ; a fresh start begins as RUN does
.endif
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
.ifdef PLATFORM_M65
        lda um_sysflags         ; the program's SYSFLAGS back (P2), here:
        clc                     ;   a KERNAL call cannot run inside
        KCALL SYSFLAGS          ;   PLAT_TO_USER's MAP hold
.endif

        ; Swap ZP: kernel's live → kernel_zp_buf, then user's
        ; userland_zp_buf → live.  Both helpers are CPU-port aware
        ; (see mem.s § CPU-port aware ZP save/restore).
        ; m65: no swap — the transitions switch B (§ Base page).
.ifdef PLATFORM_C64
        jsr save_kernel_zp
        jsr restore_userland_zp
.endif

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
        ; m65: set inside PLAT_TO_USER, once MAP holds the NMI off.
.ifdef PLATFORM_C64
        lda #$80
        sta in_userland
.endif

        PLAT_TO_USER            ; platform_layer.md § User transitions

; ── brk_stub ────────────────────────────────────────────────────────
; Fixed code address where user's top-level RTS lands after popping
; the sentinel pushed by return_to_userland.  BRK + 1 signature byte.
; m65: in the resident stub (mem.s), which the user map shows.
.ifdef PLATFORM_C64
brk_stub:
        brk
        .byte $42               ; signature (arbitrary non-$00)
.endif

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
;   JMP (ind):       step_next_lo = peek16(operand), read through the
;                    user's ZP image for $00-$7F; JMP ($xxFF) takes
;                    its high byte from $xx00 (NMOS wrap) unless
;                    asm_cpu = 65C02
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
        FAR_USER rp_ptr2        ; brk_pc is a user address

        ldy #0
        FAR_LDA rp_ptr2
        sta step_save           ; opcode

        jeq @stop               ; BRK $00

        cmp #$20
        jeq @jsr

        cmp #$60
        jeq @rts                ; RTS — peek user stack
        cmp #$40
        jeq @rti                ; RTI — peek user stack

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
        FAR_LDA rp_ptr2
        clc
        adc reg_x
        sta rp_ptr
        iny
        FAR_LDA rp_ptr2
        adc #0
        sta rp_ptr+1
        jmp @vec                ; asm_cpu = 65C02 here: no page wrap
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
        FAR_LDA rp_ptr2
        cmp #ROM_BASE_HI
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
        FAR_LDA rp_ptr2
        sta step_next_lo
        iny
        FAR_LDA rp_ptr2
        sta step_next_lo+1
        rts

@jmp_abs:
        ldy #1
        FAR_LDA rp_ptr2
        sta step_next_lo
        iny
        FAR_LDA rp_ptr2
        sta step_next_lo+1
        rts

@jmp_ind:
        ldy #1
        FAR_LDA rp_ptr2
        sta rp_ptr
        iny
        FAR_LDA rp_ptr2
        sta rp_ptr+1
@vec:   FAR_USER rp_ptr         ; the vector's address is a user address
        ; Read the vector at rp_ptr as the CPU will: through the user's
        ; ZP image for $00-$7F (peek_user).  High byte: the NMOS CPU
        ; only increments the low byte of the vector address, so
        ; JMP ($xxFF) reads its high byte from $xx00.  The 65C02
        ; carries into the page.
        jsr peek_user
        sta step_next_lo
        inc rp_ptr
.ifdef CMOS_SUPPORT
        bne @ind_hi
        lda asm_cpu
        cmp #2
        bcc @ind_hi             ; NMOS: page wrap
        inc rp_ptr+1            ; 65C02: no wrap
.endif
@ind_hi:
        jsr peek_user
        sta step_next_lo+1
        rts

; ── @rts — RTS lookahead via user-stack peek ────────────────────
; User SP at trap is in reg_sp.  RTS pops 2 bytes (return_lo at
; $0100 + reg_sp + 1, return_hi at $0100 + reg_sp + 2), then sets
; PC := (return_hi:return_lo) + 1.  We compute that lookahead and
; arm a step BRK there, so step-INTO can follow returns naturally
; instead of getting stuck at the rts.  RAM stack is accessible
; regardless of $01 banking.
@rts:
        ldx reg_sp
        inx                     ; SP+1 (return_lo)
        lda $0100,x
        clc
        adc #1
        sta step_next_lo
        inx                     ; SP+2 (return_hi)
        lda $0100,x
        adc #0
        sta step_next_lo+1
        rts

; ── @rti — RTI lookahead via user-stack peek ────────────────────
; RTI pops 3 bytes (P at SP+1, PCL at SP+2, PCH at SP+3), then
; sets PC := (PCH:PCL) (NO +1, unlike RTS).  Same banking as @rts.
@rti:
        ldx reg_sp
        inx
        inx                     ; SP+2 (PCL)
        lda $0100,x
        sta step_next_lo
        inx                     ; SP+3 (PCH)
        lda $0100,x
        sta step_next_lo+1
        rts

@stop:
        rts
.endproc

; ── peek_user ───────────────────────────────────────────────────────
; A := the byte at rp_ptr as user code sees it: $00-$7F come from the
; user's ZP image (userland_zp_buf — the live ZP is the kernel's while
; CSE runs), everything else is read live.  Clobbers: Y.
;
; m65: the image is the CPU port's two bytes (platform_layer.md
; § Base page); the rest of base page 0 is read live.
peek_user:
        ldy #0
        lda rp_ptr+1
        bne @live
        lda rp_ptr
.if ZP_SAVE_LEN = $80
        bmi @live               ; $80-$FF: not in the save range
.else
        cmp #ZP_SAVE_LO + ZP_SAVE_LEN
        bcs @live               ; m65: past the port's image
.endif
        tay
        lda BP_ABS(userland_zp_buf),y
        rts
@live:  FAR_LDA rp_ptr
        rts

; ── compute_rel_target ──────────────────────────────────────────────
; step_next_lo = brk_pc + 2 + sign_extend(byte_at(rp_ptr2+1)).
; Shared between branch and BRA paths.
;
.proc compute_rel_target
        ldy #1
        FAR_LDA rp_ptr2
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
