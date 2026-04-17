; debugger.s — Breakpoints, tracing, and execution control
;
; Breakpoint table: 8 slots × 4 bytes = 32 bytes BSS
;   Offset 0: addr lo
;   Offset 1: addr hi
;   Offset 2: saved byte (original opcode at addr)
;   Offset 3: flags (bit 0 = enabled)
;   addr=$0000 marks an empty slot.
;
; Step BRK table: same 4-byte format, 2 slots (lo/hi branch targets).
; Placed contiguously after bp_table so combined patch/unpatch can
; iterate all 10 slots in one loop.
; Caller fills addr+flags, dbg_enter patches/unpatches around user code.
; Invariant: all BRKs always unpatched before returning to REPL.
;
; Context switch: two-image stack swap.  dbg_enter jsr @tramp, which
; memcpy's CSE's stack page to cse_stack_buf (KBSS at $F000) and
; user_stack_buf (KBSS at $EF00) into the hardware stack page, then
; jmps to brk_pc.  Exit paths (BRK, NMI, clean-RTS trampoline) each
; capture user state then jmp swap_back to reverse the memcpy and
; rts back into dbg_enter.  See doc/modules/debugger.md § Context
; switch and doc/memory_design.md § Stack contract.
;
; The debugger is a consumer of the CSE BRK vector, not the owner.
; main.s installs cse_brk_handler permanently at $0316; it dispatches
; to dbg_brk_core when in_userland != 0.  dbg_enter does NOT touch
; $0316/$0317.
;
; See doc/modules/debugger.md for full design.

        .setcpu "6502"

        .export dbg_init
        .export dbg_bp_set, dbg_bp_del, dbg_bp_clear
        .export dbg_bp_count
        .export dbg_bp_find
        .export dbg_enter
        .export dbg_brk_core
        .export dbg_nmi_break
        .export bp_table, step_bp
        .export dbg_reason, brk_pc, dbg_bp_hit
        .export dbg_step_clear
        .export patch_all, unpatch_all

        .importzp rp_ptr          ; scratch pointer (main.s)
        .import reg_a, reg_x, reg_y, reg_sp, reg_p
        .import zp_save_buf, user_zp_buf
        .import in_userland       ; main.s (Phase-18 prep: was dbg_running)

; ── ZP save range — MUST match asm_line.s ──
; The buffer `zp_save_buf` is allocated by asm_line.s.  If these
; constants drift away from the asm_line.s definitions, dbg_enter
; will either overflow the buffer (HI too high) or fail to save the
; full CSE ZP (HI too low, corrupting CSE state on debug return).
; Covers the full user-accessible half ($00..$7F) — see the rationale
; in asm_line.s for why the range is the whole half, not just CSE's
; actually-used $02..$59.
ZP_SAVE_LO  = $00
ZP_SAVE_HI  = $7F
ZP_SAVE_LEN = ZP_SAVE_HI - ZP_SAVE_LO + 1     ; 128 bytes

; Reason codes
DBG_NONE = 0
DBG_BRK  = 1
DBG_NMI  = 2

BP_SLOTS    = 8
STEP_SLOTS  = 2
SLOT_SIZE   = 4         ; bytes per slot
TOTAL_SLOTS = BP_SLOTS + STEP_SLOTS     ; 10

; ── BSS ────────────────────────────────────────────────────────────────
.segment "BSS"

; bp_table and step_bp MUST be contiguous — combined patch/unpatch
; iterates offsets 0..(TOTAL_SLOTS*SLOT_SIZE-1) from bp_table.
bp_table:      .res BP_SLOTS * SLOT_SIZE     ; 32 bytes: 8 slots × 4
step_bp:       .res STEP_SLOTS * SLOT_SIZE   ; 8 bytes: 2 step slots × 4

; in_userland is owned by main.s as of Phase 18 prep (was dbg_running here).
dbg_reason:    .res 1          ; why we returned (0=none, 1=BRK, 2=NMI)
brk_pc:        .res 2          ; PC where break occurred / resume address
dbg_bp_hit:    .res 1          ; slot# of breakpoint that was hit ($FF = none)
cse_sp:        .res 1          ; CSE's SP at @tramp entry, recorded just
                                ; after `jsr @tramp` pushed its return addr.
                                ; Swap-back sequences `txs` this value to
                                ; restore CSE's stack pointer before rts.

; ── KBSS: stack-page images (under KERNAL ROM, see memory_design.md) ──
; Writes always pass through to RAM; reads require KERNAL banked out.
user_stack_buf = $EF00          ; user's stack image while CSE runs
cse_stack_buf  = $F000          ; CSE's  stack image while user runs

; MEM_CONFIG values.
MEM_CFG_KERNAL_IN  = $36        ; bit 1 set  → KERNAL ROM visible
MEM_CFG_KERNAL_OUT = $34        ; bit 1 clear → RAM under KERNAL

; ── CODE ───────────────────────────────────────────────────────────────
.segment "CODE"

; ── dbg_init ──────────────────────────────────────────────────────────
; Zero breakpoint + step tables and all debugger state.
; Clobbers: A, X
;
dbg_init:
        ; Clear both tables (bp + step = 40 bytes contiguous)
        ldx #TOTAL_SLOTS * SLOT_SIZE - 1
        jsr clear_bp_x
        ; Clear remaining state (A = $00 from clear_bp_x above).
        ; reg_p is stored while A is still 0 so bit 5 is clear —
        ; emit_reg relies on the "reg_p bit 5 = 0" invariant and
        ; no longer has a '-'-guard to rescue a dirty cold state.
        sta in_userland
        sta dbg_reason
        sta brk_pc
        sta brk_pc+1
        sta reg_p

        ; ── User stack image: initial sentinel ──────────────
        ; Plant `clean_rts_trampoline - 1` at user_stack_buf[$FE/$FF]
        ; so the very first user program's top-level RTS lands cleanly
        ; in the trampoline.  RTS increments SP then reads PC, so the
        ; stored bytes are target-address − 1.  reg_sp = $FD means the
        ; user starts with SP just below the sentinel slot.
        lda #<(clean_rts_trampoline - 1)
        sta user_stack_buf + $FE
        lda #>(clean_rts_trampoline - 1)
        sta user_stack_buf + $FF
        lda #$FD
        sta reg_sp
        lda #$FF
        sta dbg_bp_hit
        rts

; ── dbg_bp_set ────────────────────────────────────────────────────────
; Set a breakpoint at the given address.
; In:  A = addr lo, X = addr hi
; Out: C=0 success, A = slot number (0–7)
;      C=1 table full (A undefined)
; Clobbers: A, X, Y
;
; Note: does not check for duplicate addresses.  Setting the same
; address twice uses two slots.  The caller (repl.s) can check if
; desired.
;
dbg_bp_set:
        ; Stash target address in rp_ptr (ZP scratch, not used by loop)
        sta rp_ptr
        stx rp_ptr+1

        ; Find first empty slot (addr lo | addr hi == 0)
        ldy #0                  ; slot index
        ldx #0                  ; table byte offset
@find:  lda bp_table,x
        ora bp_table+1,x
        beq @found              ; empty slot
        inx
        inx
        inx
        inx
        iny
        cpy #BP_SLOTS
        bne @find

        ; Table full
        lda #$FF
        sec
        rts

@found: lda rp_ptr
        sta bp_table,x         ; addr lo
        lda rp_ptr+1
        sta bp_table+1,x       ; addr hi
        lda #0
        sta bp_table+2,x       ; saved = 0 (not yet patched)
        lda #1
        sta bp_table+3,x       ; flags = enabled
        tya                     ; A = slot number
        clc
        rts

; ── dbg_bp_del ────────────────────────────────────────────────────────
; Delete a breakpoint by slot number.
; In:  A = slot number (0–7)
; Out: C=0 success, C=1 invalid slot
; Clobbers: A, X
;
dbg_bp_del:
        cmp #BP_SLOTS
        bcs @bad                ; slot >= 8 → invalid
        ; Compute table offset: slot × 4
        asl
        asl
        tax
        lda #0
        sta bp_table,x         ; addr lo = 0
        sta bp_table+1,x       ; addr hi = 0
        sta bp_table+2,x       ; saved = 0
        sta bp_table+3,x       ; flags = 0
        clc
        rts
@bad:   lda #$FF
        sec
        rts

; ── dbg_bp_clear ──────────────────────────────────────────────────────
; Delete all breakpoints (bp_table only, not step slots).
; Clobbers: A, X
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
; Count active breakpoints (non-empty slots).
; Out: A = count (0–8)
; Clobbers: X, Y
;
dbg_bp_count:
        lda #0                  ; count
        ldy #0                  ; table offset
@cnt:   ldx bp_table,y
        bne @hit
        ldx bp_table+1,y
        beq @skip               ; both zero → empty slot
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
; Find a breakpoint by address.
; In:  A = addr lo, X = addr hi
; Out: C=0 found, A = slot number (0–7)
;      C=1 not found, A = $FF
; Clobbers: A, X, Y
;
dbg_bp_find:
        sta rp_ptr                ; stash target in ZP scratch
        stx rp_ptr+1
        ldy #0                  ; slot index
        ldx #0                  ; table byte offset
@loop:  lda bp_table,x
        cmp rp_ptr
        bne @next
        lda bp_table+1,x
        cmp rp_ptr+1
        bne @next
        ; Found
        tya                     ; A = slot number
        clc
        rts
@next:  inx
        inx
        inx
        inx
        iny
        cpy #BP_SLOTS
        bne @loop
        ; Not found
        lda #$FF
        sec
        rts

; ── patch_all ──────────────────────────────────────────────────────────
; Patch all enabled slots (bp_table + step_bp): save original byte,
; write $00 (BRK).  Forward order: bp slots first, then step slots.
; Step may overwrite a BRK that bp_patch left — step_patch saves that
; BRK so unpatch_all can restore it in reverse order.
; Clobbers: A, X, Y, rp_ptr
;
patch_all:
        ldx #0
        ldy #0                  ; for (rp_ptr),y indirect indexed
@loop:  lda bp_table,x         ; addr lo
        ora bp_table+1,x       ; |= addr hi
        beq @next               ; empty slot → skip
        lda bp_table+3,x       ; flags
        beq @next               ; not enabled → skip
        ; Load target address into rp_ptr
        lda bp_table,x
        sta rp_ptr
        lda bp_table+1,x
        sta rp_ptr+1
        ; Save original byte
        lda (rp_ptr),y            ; read from target
        sta bp_table+2,x       ; saved byte
        ; Write BRK
        lda #$00
        sta (rp_ptr),y
@next:  inx
        inx
        inx
        inx
        cpx #TOTAL_SLOTS * SLOT_SIZE
        bne @loop
        rts

; ── unpatch_all ────────────────────────────────────────────────────────
; Restore all patched slots: write saved byte back.
; Reverse order: step slots first (offsets 36,32), then bp slots
; (28,24,...,0).  This ensures step unpatches the BRK that bp_patch
; wrote, then bp_unpatch restores the original byte.
; Clobbers: A, X, Y, rp_ptr
;
unpatch_all:
        ldx #(TOTAL_SLOTS - 1) * SLOT_SIZE      ; 36 = last slot offset
        ldy #0
@loop:  lda bp_table,x
        ora bp_table+1,x
        beq @next               ; empty slot
        lda bp_table+3,x
        beq @next               ; not enabled
        ; Load target address
        lda bp_table,x
        sta rp_ptr
        lda bp_table+1,x
        sta rp_ptr+1
        ; Restore original byte
        lda bp_table+2,x
        sta (rp_ptr),y
@next:  dex
        dex
        dex
        dex
        bpl @loop               ; X=$FC (negative) after offset 0 → exits
        rts

; ── dbg_step_clear ────────────────────────────────────────────────────
; Zero the step BRK table (2 slots × 4 bytes).
; Caller fills addr+flags before calling dbg_enter.
; Clobbers: A, X
;
dbg_step_clear:
        lda #0
        ldx #STEP_SLOTS * SLOT_SIZE - 1
@z:     sta step_bp,x
        dex
        bpl @z
        rts

; ═══════════════════════════════════════════════════════════════════════════
; Context switch — enter user code / return to REPL
; ═══════════════════════════════════════════════════════════════════════════

; ── dbg_enter ─────────────────────────────────────────────────────────
; void dbg_enter(void);
;
; Saves CSE ZP, patches breakpoints, then jsr @tramp to enter user
; code.  @tramp swaps the hardware stack page with user_stack_buf
; (KBSS), loads user A/X/Y/P from reg_*, and jmp (brk_pc).  One of
; three exit paths (BRK, NMI, or clean_rts_trampoline) captures
; user state then jmp swap_back, which memcpys CSE's image back
; into the stack page and rts'es to the "after jsr @tramp" point
; below — where we then unpatch BPs, restore CSE ZP, and return.
;
; Before calling: set brk_pc to target address, _reg_* to desired
; register state, step_bp slots for step targets.
;
dbg_enter:
        ; ── 1. Save CSE ZP → zp_save_buf ──
        ldx #ZP_SAVE_LEN - 1
@szp:   lda ZP_SAVE_LO,x
        sta zp_save_buf,x
        dex
        bpl @szp

        ; ── 2. Patch all breakpoints + step BRKs ──
        jsr patch_all

        ; ── 3. Clear stale break state ──
        ; (in_userland is set inside @tramp, after cse_sp is captured —
        ; so there's no window in which the NMI handler could see
        ; in_userland set but cse_sp stale.)
        lda #0
        sta dbg_reason         ; 0 = no break (set by handler if BRK fires)
        lda #$FF
        sta dbg_bp_hit         ; $FF = no bp hit (set by handler if BRK fires)

        ; ── 4. Enter user code via the trampoline ──
        ; jsr @tramp pushes the dbg_enter continuation return addr
        ; onto CSE's stack.  @tramp stashes cse_sp, swaps stacks
        ; (CSE's stack → cse_stack_buf, user_stack_buf → page 1),
        ; loads user regs, and jmps to brk_pc.
        ;
        ; We arrive here after one of the three exit paths has
        ; captured user state (reg_*, brk_pc, dbg_reason, ...) and
        ; run the shared swap-back tail (swap_back) — which rts's
        ; off CSE's restored stack, landing exactly here.  ALL three
        ; paths — dbg_brk_core, dbg_nmi_break, clean_rts_trampoline —
        ; already did the capture, so dbg_enter does no register
        ; capture of its own.
        jsr @tramp

        ; ── 5. Unpatch all breakpoints ──
        jsr unpatch_all

        ; ── 6. Restore CSE ZP ──
        ldx #ZP_SAVE_LEN - 1
@rzp:   lda zp_save_buf,x
        sta ZP_SAVE_LO,x
        dex
        bpl @rzp

        ; ── 7. Re-enable interrupts ──
        ; BRK/NMI handler leaves I=1 (SEI by hardware).
        ; Must restore before returning to REPL or io_getc hangs.
        cli
        rts

; ── @tramp ─────────────────────────────────────────────────────────
; Context switch CSE → user.  Full two-image stack swap: saves CSE's
; current stack page to cse_stack_buf, loads user_stack_buf into the
; hardware stack page, switches SP to reg_sp, installs user A/X/Y/P,
; jmps to brk_pc.  See memory_design.md § Stack contract.
;
; ─── Invariants ─────────────────────────────────────────────────────
;   * SEI first.  CSE enters @tramp with I=0; the IRQ vector at
;     $FFFE reads RAM → our $FF04 trampoline when KERNAL is out.
;     A timer IRQ during the bank-out window would have the
;     trampoline bank KERNAL back in, RTI, and leave $01 = $36 —
;     our memcpy's subsequent reads would then hit KERNAL ROM
;     instead of user_stack_buf.  PLP below restores user's I.
;   * Linear swap-out — no JSR between here and txs reg_sp.  A
;     JSR's push would land in whichever stack image is mounted at
;     that moment and corrupt it.
;   * Between txs reg_sp and jmp (brk_pc), a PHA/PLP dance installs
;     user P.  The PHA writes at slot (reg_sp); PLP immediately
;     pulls it.  Net SP unchanged; user's live data (slots above
;     reg_sp) untouched.
;   * PLP is the last flag-touching instruction before JMP.  JMP
;     (abs) never sets flags, so PLP → JMP is safe.
@tramp:
        tsx
        stx cse_sp              ; stash CSE's SP for the swap-back
        sei                     ; mask IRQ across the bank-toggle window
        lda #$80
        sta in_userland

        ; ── Save CSE's stack image → cse_stack_buf ─────────
        ; Pure writes to KBSS; bank-agnostic.  Loop exits with X=0.
        ldx #0
@s_cse: lda $0100,x
        sta cse_stack_buf,x
        inx
        bne @s_cse

        ; ── Load user's stack image → hardware stack page ──
        ; KBSS read requires KERNAL banked out.  X = 0 from above.
        lda #MEM_CFG_KERNAL_OUT
        sta $01
@l_usr: lda user_stack_buf,x
        sta $0100,x
        inx
        bne @l_usr
        lda #MEM_CFG_KERNAL_IN
        sta $01

        ; ── Switch to user SP, install user regs, hand off ──
        ldx reg_sp
        txs
        lda reg_p
        pha
        lda reg_a
        ldx reg_x
        ldy reg_y
        plp                     ; ← last flag-touching insn before jmp
        jmp (brk_pc)

; ── swap_back ───────────────────────────────────────────────────────
; Shared tail for dbg_brk_core / dbg_nmi_break / clean_rts_trampoline.
; Saves the current (user) stack image to user_stack_buf, loads
; cse_stack_buf back into the hardware stack page, and switches SP
; to cse_sp.  Caller then rts's to land in dbg_enter's continuation.
;
; INVARIANTS
;   * I=1 on entry — protects the bank-toggle window the same way
;     @tramp's leading SEI does.  All three callers satisfy this:
;       - dbg_brk_core   : BRK hardware set I=1.
;       - dbg_nmi_break  : KERNAL $FE43 did SEI before JMP ($0318).
;       - clean_rts_trampoline : SEI as its first instruction.
;     dbg_enter's subsequent CLI re-enables IRQs at the right time.
;   * Linear sequence — no JSR between entry and the final rts.
;
; Entry: caller has already captured A/X/Y/P/PC/SP and any derived
;        fields (reg_*, brk_pc, dbg_reason, dbg_bp_hit).
; Clobbers: A, X.
swap_back:
        ; Save user's stack image → user_stack_buf (pure writes).
        ; Loop exits with X=0, reused below.
        ldx #0
@s_usr: lda $0100,x
        sta user_stack_buf,x
        inx
        bne @s_usr

        ; Load CSE's stack image back → hardware page (KBSS read).
        lda #MEM_CFG_KERNAL_OUT
        sta $01
@l_cse: lda cse_stack_buf,x
        sta $0100,x
        inx
        bne @l_cse
        lda #MEM_CFG_KERNAL_IN
        sta $01

        ; Switch to CSE's SP and return to caller (which rts's to
        ; dbg_enter's post-@tramp continuation).
        ldx cse_sp
        txs
        rts

; ── clean_rts_trampoline ────────────────────────────────────────────
; Reached when user code's top-level RTS pops the sentinel planted at
; user_stack_buf[$FE/$FF] by dbg_init — i.e., the user has cleanly
; RTSed out of all their frames.
;
; Runs on user's stack with user's banking (which may or may not have
; KERNAL banked in).  A/X/Y are user's live values; P is user's live
; state.  We snapshot them, then run the swap-back tail.
clean_rts_trampoline:
        sei                     ; match BRK/NMI invariant: I=1 during swap
        sta reg_a
        stx reg_x
        sty reg_y
        php
        pla
        and #%11001111          ; clear bits 5,4 (PHP forces them; no BRK)
        sta reg_p
        lda #DBG_NONE
        sta dbg_reason
        sta in_userland
        jsr snap_user_zp
        ; reg_sp: user's SP just after popping the sentinel (= $FF).
        ; Stash it so the next user entry resets cleanly.
        tsx
        stx reg_sp
        jmp swap_back           ; tail-jump; swap_back's rts returns to
                                ; dbg_enter continuation on CSE's stack

; ── snap_user_zp ─────────────────────────────────────────────────────
; Copy live ZP $00..$7F → user_zp_buf.  Runs while the live ZP
; is still the user's working state — before any handler code
; that uses ZP scratch clobbers it.
;
; Callers:
;   dbg_brk_core       — first thing (KERNAL push + handler code
;                        don't touch ZP until the later dbg_bp_find,
;                        but snap-early is simplest).
;   dbg_nmi_break      — after the reg_a/x/y stores (abs writes
;                        don't touch ZP), before the stack-frame
;                        reads.
;   dbg_enter step 4   — on the clean-RTS branch, before unpatch_all.
;
; Critical: this proc must NOT use any ZP scratch byte itself
; (those bytes ARE the user state we're snapshotting).
; Clobbers A, X.  Y is untouched by the loop.
.proc snap_user_zp
        ldx #ZP_SAVE_LEN - 1
@l:     lda ZP_SAVE_LO,x
        sta user_zp_buf,x
        dex
        bpl @l
        rts
.endproc

; ── dbg_brk_core ─────────────────────────────────────────────────────
; Called from cse_brk_handler (main.s) when user BRK fires
; (in_userland != 0).
;
; Stack at entry (SP+1 upward):
;   Y  X  A  P(B=1)  PClo(brk+2)  PChi
;   ─── KERNAL pushed ───  ─── CPU pushed ───
;
; The KERNAL's IRQ entry at $FF48 pushes A/X/Y and checks B flag.
; BRK dispatch occurs BEFORE any IRQ servicing.
;
dbg_brk_core:
        ; ── 0. Snapshot user ZP before doing anything else.
        ; The handler about to follow uses ZP scratch (e.g.
        ; dbg_bp_find), so the live user ZP must be captured
        ; first or it's gone.
        jsr snap_user_zp
        ; ── 1. Extract user registers from stack ──
        tsx
        lda $0101,x             ; Y (KERNAL pushed last)
        sta reg_y
        lda $0102,x             ; X
        sta reg_x
        lda $0103,x             ; A
        sta reg_a
        ; P (CPU pushed).  Bit 5 is the hardware "unused = 1" — strip
        ; it so reg_p cleanly represents the semantic flag state.
        ; Bit 4 (B) is kept: hardware set it to 1 for BRK dispatch
        ; (what we're in right now) and to 0 for plain IRQ, and we
        ; want reg_p to reflect that distinction.
        lda $0104,x
        and #%11011111          ; clear bit 5 only; keep B
        sta reg_p
        ; PC: CPU pushed brk_addr+2 — adjust back
        lda $0105,x             ; PClo
        sec
        sbc #2
        sta brk_pc
        lda $0106,x             ; PChi
        sbc #0
        sta brk_pc+1

        ; ── 2. Compute user's pre-BRK SP ──
        ; CPU pushed 3 (P, PClo, PChi), KERNAL pushed 3 (A, X, Y) = 6
        txa
        clc
        adc #6
        sta reg_sp

        ; ── 3. Set reason = BRK, find which bp ──
        lda #DBG_BRK
        sta dbg_reason
        lda brk_pc
        ldx brk_pc+1
        jsr dbg_bp_find
        sta dbg_bp_hit         ; slot# or $FF

        ; ── 4. Clear running flag ──
        lda #0
        sta in_userland

        ; ── 5. Swap user stack → user_stack_buf, CSE stack back in,
        ;       then rts to dbg_enter continuation.
        jmp swap_back

; ── dbg_nmi_break ────────────────────────────────────────────────────
; Entered from main.s cse_nmi_handler when in_userland bit 7 is set.
;
; At entry: A/X/Y have user's live values (NMI doesn't push them).
; Stack: P  PClo  PChi  (3 bytes, CPU pushed)
; KERNAL NMI entry ($FE43) does SEI + JMP ($0318) — no register pushes.
;
dbg_nmi_break:
        ; ── 1. Save user registers (live in CPU regs, NMI didn't
        ;        push them).  Must happen BEFORE snap_user_zp so
        ;        we don't need snap to preserve A/X/Y.
        sta reg_a
        stx reg_x
        sty reg_y
        ; ── 0. Snapshot user ZP now — nothing above touched ZP
        ;        (reg_* are abs/BSS), so the user's live ZP is still
        ;        intact.  Must run before any ZP-using handler work.
        jsr snap_user_zp

        ; ── 2. Extract P and PC from stack ──
        tsx
        ; P (CPU pushed).  NMI hardware push puts bit 5=1, bit 4=0.
        ; Strip both: bit 5 is a meaningless transport artefact, and
        ; bit 4 cleanly stays 0 (NMI is never "a BRK").
        lda $0101,x
        and #%11001111          ; clear bits 5, 4
        sta reg_p
        lda $0102,x             ; PClo (exact address, no +2)
        sta brk_pc
        lda $0103,x             ; PChi
        sta brk_pc+1

        ; ── 3. Compute user's pre-NMI SP ──
        txa
        clc
        adc #3                  ; CPU pushed 3 bytes
        sta reg_sp

        ; ── 4. Set reason = NMI, no bp hit ──
        lda #DBG_NMI
        sta dbg_reason
        lda #$FF
        sta dbg_bp_hit

        ; ── 5. Clear running flag, swap stacks back, return ──
        lda #0
        sta in_userland
        jmp swap_back

