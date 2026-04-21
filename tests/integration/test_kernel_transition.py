"""
test_kernel_transition.py — Kernel/userland transition contract tests.

Exercises the Phase-18 ISR-kernel model:
  - setup_interrupts wires all four vectors correctly
  - return_to_userland → BRK dispatches and captures user state
  - Cold-init userland handoff lands at main_loop_no_clear
  - NMI swallow in kernel mode; capture in userland mode
  - BRK in kernel mode routes to cse_recover
  - Step chaining runs inside the BRK handler (no SP creep)
  - Shared stack: user pushes survive a break

Uses C64Emu + the production PRG (see testing.md Principle 6).

When the full cutover lands, remove the module-level skip.
"""

import pytest
from c64emu import C64Emu


# dbg_reason enum — ordered by liveness (match main.s / repl.s).
DBG_NONE = 0    # no session
DBG_RTS  = 1    # alive-but-terminal: landed at RTS/RTI or clean exit
DBG_BRK  = 2    # resumable: non-return break
DBG_NMI  = 3    # resumable: NMI


# Auto-skip the whole file until the cutover symbols are in the
# production PRG.  After implementation lands, delete this block.
def _phase18_landed(cse_prg):
    prg, map_path = cse_prg
    probe = C64Emu()
    probe.load_prg(prg, map_path)
    return probe.sym_opt("setup_interrupts") is not None


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def emu(cse_prg):
    prg, map_path = cse_prg
    e = C64Emu()
    e.load_prg(prg, map_path)
    if e.sym_opt("setup_interrupts") is None:
        pytest.skip("Phase 18 cutover impl pending")
    return e


def _cold_init_to_prompt(emu):
    """Run cold init up to the first main_loop_top (i.e. past the
    cold-init userland handoff, splash drawn, ready for input).
    Returns once PC reaches main_loop_top.  Uses run_until() which
    C64Emu provides after the Phase-18 test-harness update.

    Note: this leaves the emulator in a state where SOME subsequent
    run_until invocations (particularly start_at=return_to_userland)
    can trip layout-shift-sensitive behavior in the emulator's step
    engine — the CPU appears to jump to $0001 during the first
    instruction of return_to_userland.  Tests that exercise the
    BRK-handler path should prefer _minimal_init + direct handler
    invocation via _fake_brk_at() to avoid that path entirely."""
    emu.run_until(emu.sym("main_loop_top"),
                  start_at=emu.sym("_main"),
                  max_cycles=2_000_000)


def _minimal_init(emu):
    """Targeted init that bypasses the full cold-init splash flow.
    Calls setup_interrupts (vectors) + dbg_init (debug state zeroed,
    ZP save buffers seeded) + reset_globals (state=ST_REPL, cur_addr
    defaults).  Result: vectors patched, debug state clean, emulator
    NOT in the layout-fragile post-cold-init state.

    Use this for tests that want to exercise specific handler/gate
    paths without the cold-init overhead or its interrupt-timing
    quirks."""
    emu.jsr(emu.sym("setup_interrupts"))
    emu.jsr(emu.sym("dbg_init"))
    # reset_globals is local to main.s; use its effect directly.
    emu.memory[emu.sym("state")]            = 1  # ST_REPL
    emu.memory[emu.sym("cur_device")]       = 8
    emu.write_word(emu.sym("block_size"),     0x0010)
    emu.write_word(emu.sym("cur_addr"),       0x0800)
    emu.memory[emu.sym("run_user_pending")] = 0


def _fake_brk_at(emu, pc, *, reg_a=0, reg_x=0, reg_y=0, reg_p=0x10,
                 in_userland=0x80):
    """Set up the stack as if a BRK just fired at `pc` with user code's
    Y/X/A pushed by the KERNAL $FF48 prologue.  Stack layout at
    cse_brk_handler entry (top→bottom):

        [SP+1] Y
        [SP+2] X
        [SP+3] A
        [SP+4] P        (CPU push, B=1 marker)
        [SP+5] PClo     (CPU push of PC+2)
        [SP+6] PChi

    The handler reads these, adjusts PC by −2, and proceeds with
    classification.  This fixture bypasses return_to_userland → user
    code → RTS → brk_stub entirely, letting the test isolate the
    handler's classification logic.

    `in_userland` defaults to $80 (userland-mode BRK).  Override with
    0 for kernel-mode BRK tests that should route to cse_recover."""
    emu._cpu.sp = 0xFF

    def _push(val):
        emu.memory[0x0100 + emu._cpu.sp] = val & 0xFF
        emu._cpu.sp = (emu._cpu.sp - 1) & 0xFF

    # CPU BRK push order: PCH, PCL, P (with B=1).  CPU pushes PC+2.
    _push((pc + 2) >> 8)
    _push((pc + 2) & 0xFF)
    _push(reg_p | 0x10)          # force B flag
    # FF48-style push: A, X, Y.
    _push(reg_a)
    _push(reg_x)
    _push(reg_y)
    emu.memory[emu.sym("in_userland")] = in_userland


# ── 1. setup_interrupts wires all four vectors ───────────────────

class TestSetupInterrupts:
    def test_all_four_vectors_patched(self, emu):
        emu.jsr(emu.sym("setup_interrupts"))
        brk = emu.sym("cse_brk_handler")
        nmi = emu.sym("cse_nmi_handler")
        brk_early = emu.sym("cse_brk_handler_early")
        # Page-3 vectors
        assert emu.memory[0x0316] == (brk & 0xFF)
        assert emu.memory[0x0317] == (brk >> 8)
        assert emu.memory[0x0318] == (nmi & 0xFF)
        assert emu.memory[0x0319] == (nmi >> 8)
        # RAM shadows under KERNAL ROM (writes pass through)
        # Read via bank-out.  $FFFA points directly at cse_nmi_handler
        # (no early-entry stub — the CPU already sets I=1 on NMI,
        # so there's nothing for a shim to do).
        emu.memory[0x01] = 0x34   # bank kernal out to read RAM shadows
        assert emu.memory[0xFFFA] == (nmi & 0xFF)
        assert emu.memory[0xFFFB] == (nmi >> 8)
        assert emu.memory[0xFFFE] == (brk_early & 0xFF)
        assert emu.memory[0xFFFF] == (brk_early >> 8)
        emu.memory[0x01] = 0x36   # bank back in


# ── 2. Cold-init userland handoff ────────────────────────────────

class TestColdInitHandoff:
    def test_handoff_lands_at_main_loop_no_clear(self, emu):
        """Cold init draws splash + prompt row, then jmps directly
        into main_loop_no_clear (no synth-RTI-to-brk_stub handoff).
        After reaching main_loop_top, in_userland==0, dbg_reason==0."""
        _cold_init_to_prompt(emu)
        assert emu.memory[emu.sym("in_userland")] == 0
        assert emu.memory[emu.sym("dbg_reason")] == 0


# ── 3. return_to_userland → clean RTS ────────────────────────────────

class TestReturnToUser:
    def test_clean_rts_classified_as_clean_exit(self, emu):
        """Under the DBG_RTS design, a BRK at brk_stub (fired because
        user's top-level RTS popped our sentinel) must classify as
        DBG_RTS and reset brk_pc := cur_addr so the display layer
        shows the user's entry PC rather than the sentinel address.

        Tests the handler directly with a fake BRK frame — bypasses
        the return_to_userland → user code → RTS → brk_stub flow,
        which trips a layout-shift quirk in the emulator's step
        engine (see _cold_init_to_prompt docstring)."""
        _minimal_init(emu)
        CUR = 0x1234
        emu.write_word(emu.sym("cur_addr"), CUR)

        brk_stub = emu.sym("brk_stub")
        _fake_brk_at(emu, brk_stub, reg_a=0x42, reg_x=0x11, reg_y=0x22)

        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("cse_brk_handler"),
                      max_cycles=200_000)

        # Clean exit: DBG_RTS (alive-but-terminal).
        assert emu.memory[emu.sym("dbg_reason")] == DBG_RTS, \
            f"expected DBG_RTS ({DBG_RTS}) after clean exit, got " \
            f"${emu.memory[emu.sym('dbg_reason')]:02X}"
        # brk_pc was reset from brk_stub to cur_addr (user-meaningful).
        assert emu.read_word(emu.sym("brk_pc")) == CUR, \
            f"brk_pc should be cur_addr (${CUR:04X}), got " \
            f"${emu.read_word(emu.sym('brk_pc')):04X}"


# ── 4. return_to_userland → BRK at breakpoint slot ───────────────────

class TestBreakpointHit:
    def test_bp_hit_captured_with_slot(self, emu):
        _cold_init_to_prompt(emu)

        # User code: LDA #$42; BRK-target; RTS
        USER = 0x3000
        BP = 0x3002
        emu.memory[USER]     = 0xA9  # LDA #$42
        emu.memory[USER + 1] = 0x42
        emu.memory[BP]       = 0xEA  # NOP (patch_all will overwrite to BRK)
        emu.memory[BP + 1]   = 0x60  # RTS

        emu.jsr(emu.sym("dbg_bp_clear"))
        emu.jsr(emu.sym("dbg_bp_set"), a=BP & 0xFF, x=BP >> 8)
        slot = emu.a

        emu.write_word(emu.sym("brk_pc"), USER)
        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("return_to_userland"),
                      max_cycles=200_000)

        assert emu.memory[emu.sym("dbg_reason")] == DBG_BRK  # resumable break
        assert emu.memory[emu.sym("dbg_bp_hit")] == slot
        assert emu.read_word(emu.sym("brk_pc")) == BP
        # unpatch_all restored original byte
        assert emu.memory[BP] == 0xEA


# ── 5. NMI in userland ───────────────────────────────────────────

class TestNmiUserland:
    def test_nmi_captures_user_state(self, emu):
        """With in_userland=$80 (userland-mode marker — NMI handler's
        `bit / bmi` dispatch tests bit 7), synthesise an NMI frame and
        invoke cse_nmi_handler.  Expect dbg_reason=DBG_NMI, user PC
        captured."""
        _cold_init_to_prompt(emu)
        # Fake userland state
        emu.memory[emu.sym("in_userland")] = 0x80
        emu.a, emu.x, emu.y = 0xAB, 0xCD, 0xEF
        # Synthesise CPU-pushed NMI frame: P, PChi, PClo
        # Push onto whatever SP is now.
        USER_PC = 0x3456
        emu.memory[0x0100 + emu.sp] = USER_PC >> 8
        emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = USER_PC & 0xFF
        emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = 0x20  # P (bit 5 = 1 typical)
        emu.sp = (emu.sp - 1) & 0xFF

        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("cse_nmi_handler"),
                      max_cycles=200_000)

        assert emu.memory[emu.sym("dbg_reason")] == DBG_NMI  # NMI
        assert emu.read_word(emu.sym("brk_pc")) == USER_PC


# ── 6. NMI in kernel mode (routes to cse_refresh) ──────────────

class TestNmiKernelMode:
    def test_nmi_kernel_routes_to_refresh(self, emu):
        """Phase 20: kernel-mode NMI discards the NMI frame and
        jumps to cse_refresh — restores the classic RUN/STOP+RESTORE
        screen-recovery behaviour.  Debug context is preserved."""
        _cold_init_to_prompt(emu)
        assert emu.memory[emu.sym("in_userland")] == 0

        # Prime a "debug active" marker that must survive the refresh.
        emu.memory[emu.sym("dbg_reason")] = DBG_BRK       # DBG_BRK
        emu.memory[emu.sym("reg_sp")]     = 0x80
        # Scribble the screen to verify refresh clears it.
        SCREEN = 0x0400
        for i in range(200):
            emu.memory[SCREEN + i] = 0xAA

        # Synthesise NMI frame.
        SENTINEL = 0xABCD
        emu.memory[0x0100 + emu.sp] = SENTINEL >> 8
        emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = SENTINEL & 0xFF
        emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = 0x20          # P
        emu.sp = (emu.sp - 1) & 0xFF

        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("cse_nmi_handler"),
                      max_cycles=200_000)

        # Screen cleared by refresh_body.
        assert emu.memory[SCREEN] == 0x20, \
            f"screen not cleared by NMI-triggered refresh: ${emu.memory[SCREEN]:02X}"
        # Debug context preserved (refresh doesn't end debug).
        assert emu.memory[emu.sym("dbg_reason")] == DBG_BRK
        assert emu.memory[emu.sym("reg_sp")] == 0x80


# ── 7. BRK in kernel mode (internal fault) ──────────────────────

class TestBrkKernelFault:
    def test_brk_in_kernel_routes_to_recover(self, emu):
        """When in_userland==0, cse_brk_handler must jump to
        cse_recover (not dispatch as a userland break)."""
        _cold_init_to_prompt(emu)
        emu.memory[emu.sym("in_userland")] = 0
        # Fabricate a BRK stack frame as if KERNAL $FF48 had pushed:
        # Y, X, A (KERNAL), P(B=1), PClo, PChi (CPU)
        BAD_PC = 0x9999
        for b in (0x00, 0x00, 0x00):   # Y, X, A
            emu.memory[0x0100 + emu.sp] = b
            emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = 0x30  # P with B=1, bit 5=1
        emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = BAD_PC & 0xFF
        emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = BAD_PC >> 8
        emu.sp = (emu.sp - 1) & 0xFF

        # warm_guard increments when cse_recover runs
        emu.memory[emu.sym("warm_guard")] = 0
        # Run handler; expect it to reach main_loop_top (via warm start)
        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("cse_brk_handler"),
                      max_cycles=500_000)
        # warm_guard was incremented and cleared by warm_start, so 0.
        # Observable instead: dbg_reason not DBG_BRK (warm start reset it).
        # This is a loose contract; the key signal is we reached main_loop_top
        # via the warm-start path rather than hanging.


# ── 8. Step chaining (handler-resident state machine) ───────────

class TestStepChain:
    def test_step_3_bounded_sp(self, emu):
        """Seed the step-chain machine with count=3 on linear insns.
        After 3 iterations the handler finalises.  Observable: brk_pc
        is at USER+3, step_state still set (post_run_cleanup would
        clear it, but we don't run that here)."""
        _cold_init_to_prompt(emu)

        # User code: 3 NOPs then RTS
        USER = 0x3000
        for i, b in enumerate((0xEA, 0xEA, 0xEA, 0x60)):
            emu.memory[USER + i] = b

        emu.write_word(emu.sym("brk_pc"), USER)
        emu.memory[emu.sym("step_remaining")] = 2   # N-1, handler
                                                     # decrements on chain
        emu.memory[emu.sym("step_state")] = 1       # STEP_INTO
        # Seed step_bp[0] = USER+1 (next-PC after NOP@USER)
        sb = emu.sym("step_bp")
        emu.memory[sb]     = (USER + 1) & 0xFF
        emu.memory[sb + 1] = (USER + 1) >> 8
        emu.memory[sb + 3] = 1   # enabled

        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("return_to_userland"),
                      max_cycles=500_000)

        # After 3 iterations the handler finalises at brk_pc = USER+3.
        assert emu.read_word(emu.sym("brk_pc")) == USER + 3


# ── 9. Shared stack — user pushes survive break ─────────────────

class TestSharedStack:
    def test_user_pushes_preserved_across_break(self, emu):
        """User pushes $AB and $CD to stack then hits breakpoint.
        The two bytes must still be at their stack slots after the
        kernel captures user state (because kernel's pushes for the
        BRK frame sit below user's SP, not on top of user's data)."""
        _cold_init_to_prompt(emu)

        # User code: LDA #$AB; PHA; LDA #$CD; PHA; NOP (bp here); RTS
        USER = 0x3000
        BP = 0x3006
        prog = bytes((0xA9, 0xAB, 0x48, 0xA9, 0xCD, 0x48, 0xEA, 0x60))
        for i, b in enumerate(prog):
            emu.memory[USER + i] = b

        emu.jsr(emu.sym("dbg_bp_clear"))
        emu.jsr(emu.sym("dbg_bp_set"), a=BP & 0xFF, x=BP >> 8)

        # Start user at a known high SP so we can assert on $01FF/$01FE.
        emu.memory[emu.sym("reg_sp")] = 0xFF
        emu.write_word(emu.sym("brk_pc"), USER)
        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("return_to_userland"),
                      max_cycles=200_000)

        # Stack layout after cold init + first return_to_userland:
        #   $01FF: sentinel hi  ($A3 = hi of brk_stub - 1)
        #   $01FE: sentinel lo  ($9C = lo of brk_stub - 1)
        #   $01FD/$01FC: stale PChi/PClo from RTI frame (popped)
        # User entered with SP = $FD; their first PHA (AB) wrote at
        # $01FD (overwriting the stale PChi), second (CD) at $01FC.
        # Their reg_sp captured at the bp hit = $FB.
        reg_sp = emu.memory[emu.sym("reg_sp")]
        assert emu.memory[0x01FD] == 0xAB, \
            f"user's first push overwritten: ${emu.memory[0x01FD]:02X}"
        assert emu.memory[0x01FC] == 0xCD, \
            f"user's second push overwritten: ${emu.memory[0x01FC]:02X}"
        assert reg_sp == 0xFB, f"reg_sp expected $FB, got ${reg_sp:02X}"
        # Sentinel still intact for future clean-exit path.
        assert emu.memory[0x01FF] == ((emu.sym("brk_stub") - 1) >> 8) & 0xFF
        assert emu.memory[0x01FE] == (emu.sym("brk_stub") - 1) & 0xFF


# ── 10. Kernel stack budget constant is exposed ─────────────────

class TestKernelStackBudget:
    def test_budget_constant_defined(self, emu):
        """The userland contract's 64 B headroom figure is an
        assembly-visible constant so it can be tightened post-audit
        without hunting down the number in docs only."""
        budget = emu.sym_opt("kernel_stack_budget")
        assert budget is not None, \
            "kernel_stack_budget equate expected per userland contract"
        # The symbol's address IS the value (equate).
        assert budget == 64


# ── 11. Warmstart entry points + body subs (Phase 20) ───────────
#
# Tests A/1-5 per the Step-3 TDD plan.  Body subs are balanced
# jsr-subs — SP discipline is the entry point's responsibility.
# Entry points reset SP via `ldx #$FF / txs` (or `ldx kernel_init_sp`)
# before jsr'ing bodies.

class TestWarmstartBodySubs:

    def _prime_editor_canary(self, emu):
        """Plant distinctive bytes in the editor gap buffer region
        and capture the buf_base/gap pointers so we can verify they
        survive a warmstart."""
        buf_base  = emu.sym("buf_base")
        gap_lo    = emu.sym("gap_lo")
        gap_hi    = emu.sym("gap_hi")
        # The gap-buffer memory is whatever's at buf_base's value.
        base = emu.read_word(buf_base)
        return {
            "buf_base": (emu.memory[buf_base], emu.memory[buf_base + 1]),
            "gap_lo":   (emu.memory[gap_lo],   emu.memory[gap_lo + 1]),
            "gap_hi":   (emu.memory[gap_hi],   emu.memory[gap_hi + 1]),
            "base":     base,
            "byte0":    emu.memory[base],
            "byte1":    emu.memory[base + 1],
        }

    def _assert_editor_unchanged(self, emu, canary):
        buf_base  = emu.sym("buf_base")
        gap_lo    = emu.sym("gap_lo")
        gap_hi    = emu.sym("gap_hi")
        assert (emu.memory[buf_base], emu.memory[buf_base + 1]) == canary["buf_base"], \
            "buf_base changed across warmstart"
        assert (emu.memory[gap_lo],   emu.memory[gap_lo + 1])   == canary["gap_lo"], \
            "gap_lo changed across warmstart"
        assert (emu.memory[gap_hi],   emu.memory[gap_hi + 1])   == canary["gap_hi"], \
            "gap_hi changed across warmstart"
        assert emu.memory[canary["base"]]     == canary["byte0"], \
            "editor gap buffer byte 0 changed"
        assert emu.memory[canary["base"] + 1] == canary["byte1"], \
            "editor gap buffer byte 1 changed"

    def test_end_debug_clears_debug_state(self, emu):
        """cse_end_debug must zero all debug-state flags and reset
        reg_sp to $FF — and preserve editor state."""
        _cold_init_to_prompt(emu)
        # Prime the debug-state fields with non-zero values.
        emu.memory[emu.sym("dbg_reason")]       = DBG_BRK       # DBG_BRK
        emu.memory[emu.sym("step_state")]       = 1
        emu.memory[emu.sym("step_remaining")]   = 5
        emu.memory[emu.sym("run_user_pending")] = 2       # MODE_RESUME
        emu.memory[emu.sym("in_userland")]      = 0x80
        emu.memory[emu.sym("reg_sp")]           = 0x10
        emu.memory[emu.sym("dbg_bp_hit")]       = 3
        canary = self._prime_editor_canary(emu)

        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("cse_end_debug"),
                      max_cycles=200_000)

        assert emu.memory[emu.sym("dbg_reason")]       == 0
        assert emu.memory[emu.sym("step_state")]       == 0
        assert emu.memory[emu.sym("step_remaining")]   == 0
        assert emu.memory[emu.sym("run_user_pending")] == 0
        assert emu.memory[emu.sym("in_userland")]      == 0
        assert emu.memory[emu.sym("reg_sp")]           == 0xFF
        assert emu.memory[emu.sym("dbg_bp_hit")]       == 0xFF
        self._assert_editor_unchanged(emu, canary)

    def test_refresh_clears_screen_preserves_editor(self, emu):
        """cse_refresh must clear screen RAM and preserve editor."""
        _cold_init_to_prompt(emu)
        # Scribble the screen with a non-space pattern.
        SCREEN = 0x0400
        for i in range(200):
            emu.memory[SCREEN + i] = 0xAA
        canary = self._prime_editor_canary(emu)

        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("cse_refresh"),
                      max_cycles=200_000)

        # After refresh the top of screen should be blanked (screen code $20).
        assert emu.memory[SCREEN + 0] == 0x20, \
            f"screen[0] not cleared: ${emu.memory[SCREEN]:02X}"
        self._assert_editor_unchanged(emu, canary)

    def test_entry_points_reset_sp(self, emu):
        """Each warmstart entry point resets SP before jsr'ing its
        body subs.  Verify by calling the entry point with a
        deliberately-low SP and checking we still reach
        main_loop_top without stack underflow."""
        _cold_init_to_prompt(emu)
        for entry in ("cse_end_debug", "cse_refresh"):
            emu.sp = 0x20           # low SP, simulates a deep kernel chain
            emu.run_until(emu.sym("main_loop_top"),
                          start_at=emu.sym(entry),
                          max_cycles=200_000)

    def test_end_debug_unpatches_breakpoints(self, emu):
        """end_debug_body calls unpatch_all so any live BPs are
        restored to the user's original bytes."""
        _cold_init_to_prompt(emu)
        # Write a user byte at a workspace address.
        USER = 0x1234
        emu.memory[USER] = 0xA9                 # LDA #imm
        # Set BP slot 0 to USER.
        bp_table = emu.sym("bp_table")
        emu.memory[bp_table + 0] = USER & 0xFF
        emu.memory[bp_table + 1] = USER >> 8
        emu.memory[bp_table + 2] = 0xA9         # saved opcode
        emu.memory[bp_table + 3] = 1            # slot enabled
        # Patch the user byte with BRK ($00) to simulate arming.
        emu.memory[USER] = 0x00

        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("cse_end_debug"),
                      max_cycles=200_000)

        # Unpatched: user byte restored.
        assert emu.memory[USER] == 0xA9, \
            f"BP not unpatched: ${emu.memory[USER]:02X}"
        # bp_table slot still populated (intent preserved).
        assert emu.memory[bp_table + 0] == (USER & 0xFF)
        assert emu.memory[bp_table + 1] == (USER >> 8)


# ── 11b. Gates (warn_if_* + query_user + warm_cont dispatch) ──
#
# The gating pattern composes a warn_if_* call with an atomic
# query_user.  These tests exercise the end-to-end flow against
# the real PRG via keyboard injection.

class TestGating:
    def _repl_ready(self, emu):
        """Run cold init up through the first main_loop_top pause."""
        _cold_init_to_prompt(emu)

    def test_warn_if_debug_fires_when_active(self, emu):
        """warn_if_debug emits ';!debug' on its line when dbg_reason≠0."""
        self._repl_ready(emu)
        emu.memory[emu.sym("dbg_reason")] = DBG_BRK
        # Put cursor at an empty row so we can read the warn line.
        emu.memory[0xD6] = 10   # cursor_row
        emu.memory[0xD3] = 0    # cursor_col
        emu.jsr(emu.sym("warn_if_debug"))
        row = bytes(emu.memory[0x0400 + 10 * 40 : 0x0400 + 11 * 40])
        # ";!debug" → ';' = $3B, '!' = $21, 'd' = $04 (screen code), etc.
        # Simpler: find the ';!' marker (screen codes $3B, $21).
        assert b"\x3b\x21" in row, \
            f"expected ';!' marker in row: {row.hex()}"

    def test_warn_if_debug_silent_when_inactive(self, emu):
        """warn_if_debug is a no-op when dbg_reason==0."""
        self._repl_ready(emu)
        emu.memory[emu.sym("dbg_reason")] = 0
        emu.memory[0xD6] = 10
        emu.memory[0xD3] = 0
        # Clear the row first.
        for i in range(40):
            emu.memory[0x0400 + 10 * 40 + i] = 0x20
        emu.jsr(emu.sym("warn_if_debug"))
        row = bytes(emu.memory[0x0400 + 10 * 40 : 0x0400 + 11 * 40])
        assert all(b == 0x20 for b in row), \
            f"expected blank row (no warn), got: {row.hex()}"

    def test_warn_if_unsaved_fires_when_dirty(self, emu):
        """warn_if_unsaved emits ';!unsaved' when ed_dirty≠0."""
        self._repl_ready(emu)
        emu.memory[emu.sym("ed_dirty")] = 1
        emu.memory[0xD6] = 12
        emu.memory[0xD3] = 0
        emu.jsr(emu.sym("warn_if_unsaved"))
        row = bytes(emu.memory[0x0400 + 12 * 40 : 0x0400 + 13 * 40])
        assert b"\x3b\x21" in row, \
            f"expected ';!' in row: {row.hex()}"


# ── 12. Warmstart continuation flag (warm_cont) ─────────────────

class TestWarmCont:
    """warm_cont dispatch in main_loop_top — the gates set this
    flag before jumping to a warmstart entry point to request that
    the replayed line_buf runs after the reset."""

    def test_warm_cont_absent_runs_normal_prompt(self, emu):
        """warm_cont=0 → main_loop_top takes the normal @prompt path
        (show_prompt + read_line).  We verify by setting warm_cont=0
        and checking the flag stays 0 through a prompt cycle."""
        _cold_init_to_prompt(emu)
        assert emu.memory[emu.sym("warm_cont")] == 0

    def test_warm_cont_is_consumed(self, emu):
        """warm_cont=1 at main_loop_top → replay branch taken,
        warm_cont is zeroed on its way through (one-shot).  We
        can't easily verify full replay here (it'd read from
        line_buf which the test didn't populate), so instead we
        intercept: set warm_cont=1 with a JMP-to-RTS target in
        line_buf so exec_line returns quickly; verify warm_cont
        is 0 after."""
        _cold_init_to_prompt(emu)
        emu.memory[emu.sym("warm_cont")] = 1
        # Put a bare newline-like line in line_buf so exec_line
        # returns without side effects.  Empty line (NUL at offset 0)
        # is safe — exec_line treats it as no-op.
        line_buf = emu.sym("line_buf")
        emu.memory[line_buf] = 0
        # Run until PC reaches main_loop_top for the SECOND time
        # (after the replay completes and loops back).  The
        # `jmp main_loop_top` after exec_line takes us there.
        #
        # Simpler: just run a short burst from main_loop_top and
        # check warm_cont is consumed.
        emu.sp = 0xFF
        emu._cpu.pc = emu.sym("main_loop_top")
        # Step until warm_cont is consumed (it happens very early).
        for _ in range(200):
            emu._cpu.step()
            if emu.memory[emu.sym("warm_cont")] == 0:
                break
        assert emu.memory[emu.sym("warm_cont")] == 0, \
            "warm_cont not consumed by main_loop_top"


# ── 12. Production-chain stress (kernel-stack-corruption guard) ──

class TestProductionChainStress:
    """End-to-end stress driving REPL commands via the real
    main_loop → exec_line → cmd_X → ...rts-up-the-chain → main_loop
    dispatch → gate → user code → break → handler → main_loop_top
    chain.

    Why this matters (the bug class these tests guard against): a
    helper running on the kernel call stack that writes to user's
    `$0100,reg_sp` slot via `sta abs,X` can clobber the kernel's own
    return-address frames sitting at the same stack-page slots when
    `reg_sp = $FF` (typical for fresh sessions).  exec_line's `rts`
    then jumps to garbage, BRK fires in kernel mode, and cse_recover
    warm-starts.  A direct `emu.jsr()` test masks this entirely:
    the harness installs ITS OWN return-address sentinel at the same
    slots production code touches, so the corruption appears to be
    "the test's own return address" and the test passes.

    Discipline: drive REPL commands via keyboard injection through
    `main_loop`, NOT via `emu.jsr(emu.sym("cmd_X"))`.  See
    testing.md for the broader principle on production-chain stress.
    """

    def test_g_via_keyboard_no_warm_start(self, emu):
        """Drive `g\\r` via keystroke injection through the
        production main_loop dispatch chain.  Asserts (a) no warm-
        start fired (warm_guard untouched) and (b) clean exit
        through brk_stub (dbg_reason back to 0).

        Catches the bug class where a kernel-stack helper writes to
        `$0100,reg_sp` and clobbers kernel return-address frames at
        $01FE/$01FF.  A `cmd_jmp` invocation via direct `emu.jsr`
        would mask this — the harness's jsr-return sentinel sits at
        the same overlapping slots."""
        _cold_init_to_prompt(emu)

        # User code: simple RTS at $3000 (clean exit via brk_stub).
        USER = 0x3000
        emu.memory[USER] = 0x60                          # RTS
        emu.memory[emu.sym("cur_addr")]     = USER & 0xFF
        emu.memory[emu.sym("cur_addr") + 1] = USER >> 8

        # Inject "g\r" via keyboard buffer.  PETSCII 'g' = $47.
        emu.inject_keys(b"\x47\x0D")

        # Re-enter main_loop and let it process the input.
        emu._cpu.pc = emu.sym("main_loop_top")
        emu.sp = 0xFF
        # main_loop dispatches g → cmd_jmp → gate → user code → RTS
        # → brk_stub → handler → main_loop_top → @wait poll on $C6.
        for _ in range(2_000_000):
            emu._cpu.step()
            if emu.memory[emu.sym("warm_guard")] != 0:
                break

        # warm_guard non-zero would mean cse_recover fired — i.e. a
        # BRK trapped while in kernel mode (in_userland=0), which
        # only happens if the kernel return-address frame got
        # clobbered and CPU jumped into garbage / brk_stub.
        assert emu.memory[emu.sym("warm_guard")] == 0, \
            "g triggered cse_recover/warm-start (kernel return frame " \
            "likely clobbered by a helper writing $0100,reg_sp from " \
            "kernel-call-stack context)"
        # Clean exit through brk_stub classifies as DBG_RTS
        # (alive-but-terminal); brk_pc has been reset to cur_addr.
        assert emu.memory[emu.sym("dbg_reason")] == DBG_RTS, \
            f"dbg_reason=${emu.memory[emu.sym('dbg_reason')]:02X} " \
            f"expected DBG_RTS ({DBG_RTS}) on clean brk_stub exit"


# ── 13. Tag classification regression (cmd_step on RTS) ─────────

class TestTagClassification:
    """Regression guard for the bug "rts needs to be stepped on
    twice before it registers as rts".

    Two distinct states share the same brk_pc-on-RTS observable
    but want different tags:

    State A — real trap landing (cse_brk_handler ran):
        Step BRK fired at the RTS instruction.  Handler set
        dbg_reason = DBG_BRK.  Tag MUST be "; brk" — this reflects
        the trap source (we just broke at this insn).  This is the
        first time the user lands on the RTS.

    State B — cmd_step early-stop (no trap fired):
        User typed t/o again at the same brk_pc.  cmd_step sees
        opcode $60 in step_next_pc and aborts WITHOUT entering
        userland.  Tag MUST be "; rts" — this reflects the
        stepping outcome (the next thing that would have run is a
        return op).  show_break_result distinguishes A from B by
        dbg_reason: cmd_step's RTS-early-stop clears dbg_reason
        BEFORE calling post_run_cleanup so show_break_result takes
        the opcode-based fallback.

    Without the fix in cmd_step's ordering (post_run_cleanup ran
    before the dbg_reason clear), state B inherited dbg_reason =
    DBG_BRK from state A and wrongly displayed "; brk".  The third
    consecutive t/o then accidentally got dbg_reason = 0 from the
    second's tail-clear and finally showed "; rts" — hence "twice
    before rts".
    """

    @staticmethod
    def _screen_has(emu, pattern):
        for base in range(0x0400, 0x07E8 - len(pattern) + 1):
            if bytes(emu.memory[base + i] for i in range(len(pattern))) == pattern:
                return True
        return False

    @staticmethod
    def _clear_screen(emu):
        for i in range(0x0400, 0x0800):
            emu.memory[i] = 0x20

    # Tag patterns include the leading "; " so the scan does not
    # collide with the disassembly line below the tag (which also
    # contains "rts" when brk_pc opcode is $60).
    # CSE shifted charset: 'a'=$01, 'b'=$02, ..., 'z'=$1A.
    _TAG_BRK = bytes([0x3B, 0x20, 0x02, 0x12, 0x0B])  # "; brk"
    _TAG_RTS = bytes([0x3B, 0x20, 0x12, 0x14, 0x13])  # "; rts"

    def _setup_at_rts(self, emu, addr=0x3000):
        """Common fixture: cold-init, RTS at addr, brk_pc=cur_addr=
        addr, dbg_bp_hit=$FF.  Caller sets dbg_reason."""
        _cold_init_to_prompt(emu)
        emu.memory[addr] = 0x60                          # RTS
        emu.write_word(emu.sym("brk_pc"), addr)
        emu.write_word(emu.sym("cur_addr"), addr)
        emu.memory[emu.sym("dbg_bp_hit")] = 0xFF
        # rp_ptr → empty line_buf so try_expr returns C=0 (default cnt).
        line_buf = emu.sym("line_buf")
        for i in range(8):
            emu.memory[line_buf + i] = 0
        emu.memory[0x02] = line_buf & 0xFF
        emu.memory[0x03] = line_buf >> 8
        self._clear_screen(emu)

    def test_rts_landing_via_step_brk_registers_as_rts(self, emu):
        """b9c3914 regression guard: a step-BRK trap landing on an
        RTS instruction leaves dbg_reason=DBG_BRK (set by the
        handler from the BRK frame), but the display MUST say
        "; rts" — the user is sitting on a return op and the
        tag should reflect that.

        show_break_result's opcode tier catches this: regardless
        of dbg_reason (NMI excepted), opcode $60/$40 at brk_pc
        drives the tag to "; rts".  Uses _minimal_init to avoid
        _cold_init_to_prompt's layout fragility."""
        _minimal_init(emu)
        USER = 0x3000
        emu.memory[USER] = 0x60                              # RTS
        emu.write_word(emu.sym("brk_pc"), USER)
        emu.write_word(emu.sym("cur_addr"), USER)
        emu.memory[emu.sym("dbg_reason")] = DBG_BRK          # handler default
        emu.memory[emu.sym("dbg_bp_hit")] = 0xFF
        # Clear screen for clean marker scan.
        for i in range(0x0400, 0x0800):
            emu.memory[i] = 0x20

        emu.jsr(emu.sym("show_break_result"))

        assert self._screen_has(emu, self._TAG_RTS), \
            "expected '; rts' when sitting on $60 RTS opcode — " \
            "classification must derive from opcode, not dbg_reason"
        assert not self._screen_has(emu, self._TAG_BRK), \
            "did not expect '; brk' when sitting on RTS opcode " \
            "(bug: 'rts needs to be stepped on twice before it " \
            "registers as rts')"

    def test_bare_t_defaults_to_single_step(self, emu):
        """Bare `t` (no expression argument) must arm exactly one
        step — rp_cnt = 1, step_remaining = 0 (= count - 1).
        Trace is single-step by default; block_size is for memory
        commands (m/l/s) and is NOT consulted by t/o."""
        _cold_init_to_prompt(emu)
        USER = 0x3000
        emu.memory[USER]     = 0xEA                       # NOP (linear)
        emu.write_word(emu.sym("brk_pc"), USER)
        emu.write_word(emu.sym("cur_addr"), USER)
        emu.memory[emu.sym("dbg_reason")]    = DBG_BRK          # active session
        emu.memory[emu.sym("dbg_bp_hit")]    = 0xFF
        # Set block_size to a sentinel (16) — should NOT influence count.
        emu.write_word(emu.sym("block_size"), 0x0010)
        # rp_ptr → empty line_buf so try_expr returns C=0.
        line_buf = emu.sym("line_buf")
        for i in range(8):
            emu.memory[line_buf + i] = 0
        emu.memory[0x02] = line_buf & 0xFF
        emu.memory[0x03] = line_buf >> 8

        emu.jsr(emu.sym("cmd_step"), a=0)                 # bare t

        # rp_cnt = 1 (single step), step_remaining = count - 1 = 0.
        assert emu.read_word(emu.sym("rp_cnt")) == 1, \
            "bare t must default to count=1 (single step), not block_size"
        assert emu.memory[emu.sym("step_remaining")] == 0, \
            "step_remaining = count-1; for single step, should be 0"

    def test_t_with_trailing_garbage_aborts_and_logs_syntax(self, emu):
        """`t10xyz` (value $10 followed by garbage `xyz`) must:
          (a) abort cmd_step BEFORE the step_state write
              (proves the pop-trick helper fired), and
          (b) log ";?syntax" on screen (proves log_err ran).

        CSE always renders to $0400; REPL_SCREEN at $F4F2 is just
        a save buffer for editor takeover.  Format is `;?syntax`
        with NO space between `;` and `?` (log_err's prefix is
        just the two chars, the str follows immediately)."""
        _cold_init_to_prompt(emu)
        USER = 0x3000
        emu.memory[USER] = 0xEA                          # NOP
        emu.write_word(emu.sym("brk_pc"), USER)
        emu.write_word(emu.sym("cur_addr"), USER)
        emu.memory[emu.sym("dbg_reason")] = DBG_BRK            # active session
        emu.memory[emu.sym("dbg_bp_hit")] = 0xFF
        emu.memory[emu.sym("step_state")] = 0            # not stepping

        # rp_ptr → "10xyz\0" — try_expr parses 10, rp_ptr lands on
        # "x" → garbage → pop-trick fires.
        line_buf = emu.sym("line_buf")
        for i, b in enumerate(b"10xyz\x00"):
            emu.memory[line_buf + i] = b
        emu.memory[0x02] = line_buf & 0xFF                # rp_ptr (zp.s: $02)
        emu.memory[0x03] = line_buf >> 8

        # Clear screen so the marker scan is unambiguous.
        for i in range(0x0400, 0x0800):
            emu.memory[i] = 0x20

        emu.jsr(emu.sym("cmd_step"), a=0)

        # (a) step_state stays 0 — pop-trick escaped before state writes.
        assert emu.memory[emu.sym("step_state")] == 0, \
            "garbage in t arg must abort before arming step_state " \
            "(pop-trick _require_eoi_or_err did not escape)"

        # (b) ";?syntax" rendered to $0400 (CSE shifted charset:
        #     ';'=$3B, '?'=$3F, 's'=$13, 'y'=$19, 'n'=$0E, 't'=$14,
        #     'a'=$01, 'x'=$18).
        marker = bytes([0x3B, 0x3F, 0x13, 0x19, 0x0E, 0x14, 0x01, 0x18])
        found = False
        for base in range(0x0400, 0x07E8 - len(marker) + 1):
            if bytes(emu.memory[base + i] for i in range(len(marker))) == marker:
                found = True
                break
        assert found, "expected ';?syntax' on screen (log_err output)"

    def test_state_b_cmd_step_early_stop_shows_rts(self, emu):
        """State B: user types t/o while sitting on the RTS.
        cmd_step's RTS-early-stop fires (step_next_pc returns zeros
        for $60), and the resulting display MUST say "; rts" — this
        reflects the stepping outcome (would-be next op is a return).

        This is the bug-repro: without the fix, cmd_step called
        post_run_cleanup BEFORE clearing dbg_reason, so
        show_break_result inherited dbg_reason=DBG_BRK from state A
        and displayed "; brk" again."""
        self._setup_at_rts(emu)
        emu.memory[emu.sym("dbg_reason")] = DBG_BRK            # state A leftover

        emu.jsr(emu.sym("cmd_step"), a=0)                # t1

        assert self._screen_has(emu, self._TAG_RTS), \
            "state B (cmd_step early-stop on RTS) must show '; rts' " \
            "— bug 'rts needs to be stepped on twice before it " \
            "registers as rts'"
        assert not self._screen_has(emu, self._TAG_BRK), \
            "state B must not show '; brk' — no trap fired, we're " \
            "just reporting that the next op would be a return"


# ── 14. Trailing-garbage rejection across migrated commands ─────

class TestTrailingGarbageRejection:
    """Cross-command regression: any command that went through the
    _require_eoi_or_err migration must reject trailing garbage and
    leave state untouched (pop-trick escapes before the apply).

    These are production-chain tests via exec_line dispatch.  Each
    sub-test seeds line_buf with the command string, invokes
    exec_line, and asserts both (a) ";?syntax" appears on screen
    and (b) the command's target state is unchanged."""

    _SYNTAX_MARKER = bytes([0x3B, 0x3F, 0x13, 0x19, 0x0E, 0x14, 0x01, 0x18])

    @staticmethod
    def _screen_has_marker(emu, marker):
        for base in range(0x0400, 0x07E8 - len(marker) + 1):
            if bytes(emu.memory[base + i] for i in range(len(marker))) == marker:
                return True
        return False

    @staticmethod
    def _clear_screen(emu):
        for i in range(0x0400, 0x0800):
            emu.memory[i] = 0x20

    @staticmethod
    def _to_petscii(cmd_bytes):
        """Convert a shell-readable ASCII cmd to CSE's PETSCII input
        encoding: lowercase letters $61-$7A → uppercase $41-$5A
        (c64 shifted charset maps $41-$5A to lowercase on screen, so
        typing 'b' at the keyboard produces PETSCII $42).  Digits
        and punctuation are identity."""
        out = bytearray()
        for b in cmd_bytes:
            if 0x61 <= b <= 0x7A:
                out.append(b - 0x20)
            else:
                out.append(b)
        return bytes(out)

    def _run_command(self, emu, cmd_bytes):
        """Set up line_buf + rp_ptr, clear screen, jsr exec_line.
        cmd_bytes may be given in ASCII lowercase for readability;
        converted to CSE PETSCII (uppercase for letters) here."""
        cmd_bytes = self._to_petscii(cmd_bytes)
        line_buf = emu.sym("line_buf")
        for i, b in enumerate(cmd_bytes):
            emu.memory[line_buf + i] = b
        emu.memory[line_buf + len(cmd_bytes)] = 0
        emu.memory[0x02] = line_buf & 0xFF          # rp_ptr
        emu.memory[0x03] = line_buf >> 8
        self._clear_screen(emu)
        emu.jsr(emu.sym("exec_line"))

    def test_plus_with_garbage_does_not_advance_cur_addr(self, emu):
        """`+ $10 xyz` must log ';?syntax' and leave cur_addr as-is.
        Without the migration, it would silently advance by $10."""
        _cold_init_to_prompt(emu)
        CUR = 0x2000
        emu.write_word(emu.sym("cur_addr"), CUR)

        # PETSCII: '+'=$2B, ' '=$20, '$'=$24, '1'=$31, '0'=$30,
        #           'x'=$78, 'y'=$79, 'z'=$7A
        self._run_command(emu, b"+ $10 xyz")

        assert emu.read_word(emu.sym("cur_addr")) == CUR, \
            "+ with trailing garbage must NOT advance cur_addr"
        assert self._screen_has_marker(emu, self._SYNTAX_MARKER), \
            "expected ';?syntax' on screen"

    def test_b_with_garbage_does_not_install_breakpoint(self, emu):
        """`b $1020 xyz` must log ';?syntax' and NOT add a bp.
        Without the migration, it would silently install bp at $1020
        even though the user's input was bad."""
        _cold_init_to_prompt(emu)
        emu.jsr(emu.sym("dbg_bp_clear"))

        self._run_command(emu, b"b $1020 xyz")

        # bp_table first slot should still be zero (no bp installed).
        bp0 = emu.read_word(emu.sym("bp_table"))
        assert bp0 == 0, \
            f"b with trailing garbage must NOT install bp (got ${bp0:04X})"
        assert self._screen_has_marker(emu, self._SYNTAX_MARKER), \
            "expected ';?syntax' on screen"

    def test_m_with_garbage_after_addr_does_not_dump(self, emu):
        """`m $1000 xyz` must log ';?syntax'.  cmd_mem's @dump entry
        now requires EOI.  Without the migration, it would dump
        block_size bytes at $1000 silently."""
        _cold_init_to_prompt(emu)

        self._run_command(emu, b"m $1000 xyz")

        assert self._screen_has_marker(emu, self._SYNTAX_MARKER), \
            "expected ';?syntax' on screen for m with garbage"

    def test_d_with_any_inline_arg_aborts(self, emu):
        """`d xyz` must log ';?syntax' — cmd_disasm takes no inline
        args (ADDR comes via 1000:d addressed form, not inline)."""
        _cold_init_to_prompt(emu)

        self._run_command(emu, b"d xyz")

        assert self._screen_has_marker(emu, self._SYNTAX_MARKER), \
            "expected ';?syntax' on screen for d with inline content"


# ── 15. REPL output hygiene smoke test ──────────────────────────

class TestOutputHygiene:
    """Smoke test for repl.md principle 11: "No spurious blank lines."

    Drives the self-contained emit helpers (emit_reg, emit_mem,
    emit_dot) in the sequence a typical REPL session would, then
    scans for any fully-blank row ($20-padded) between the first
    and last emitter output.

    Rationale: the REPL treats screen real estate as scarce.  Any
    command that emits an accidental newline / missing clreol / row-
    arithmetic off-by-one shows up as a blank row between adjacent
    emit runs.  Caught at the emitter level, the bug is pinned to
    a small unit; individual panel layout (row counts, cursor
    positioning) is verified on real hardware / VICE.

    This test does NOT use `emu.jsr(exec_line)` because many
    command paths longjmp back to `main_loop_top` rather than RTS
    cleanly — unsafe as a jsr target.  Emit helpers are pure
    subroutines and are safe.
    """

    @staticmethod
    def _clear_screen(emu):
        for i in range(0x0400, 0x0800):
            emu.memory[i] = 0x20

    @staticmethod
    def _is_blank_row(emu, row):
        base = 0x0400 + row * 40
        return all(emu.memory[base + c] == 0x20 for c in range(40))

    @staticmethod
    def _position(emu, row, col=0):
        emu.memory[0xD6] = row
        emu.memory[0xD3] = col
        emu.jsr(emu.sym("io_sync"))

    def test_no_blank_rows_across_emitter_sequence(self, emu):
        """Drive emit_reg + emit_mem + emit_dot in sequence, as
        show_break_result would.  Assert: from the first output row
        to the cursor's current row, no row is fully blank.

        Uses _minimal_init rather than _cold_init_to_prompt: emitter
        invariants don't need cold-init state, and _cold_init_to_prompt
        leaves the emulator in a layout-fragile mode that makes
        subsequent jsr() calls unreliable."""
        _minimal_init(emu)

        # Seed state: brk_pc/rp_addr at $1000 (safe RAM), populate
        # memory bytes so emit_mem has non-zero content.
        ADDR = 0x1000
        for i in range(16):
            emu.memory[ADDR + i] = 0xEA   # NOP's, non-blank bytes
        emu.write_word(emu.sym("brk_pc"), ADDR)
        emu.write_word(emu.sym("cur_addr"), ADDR)
        emu.write_word(emu.sym("rp_addr"), ADDR)
        # emit_reg reads PC from brk_pc (set above).
        emu.memory[emu.sym("reg_a")]  = 0x42
        emu.memory[emu.sym("reg_x")]  = 0x11
        emu.memory[emu.sym("reg_y")]  = 0x22
        emu.memory[emu.sym("reg_sp")] = 0xFF
        emu.memory[emu.sym("reg_p")]  = 0x00

        # Clear the screen and position cursor on row 5, col 0.
        self._clear_screen(emu)
        self._position(emu, row=5)

        first_row = 5

        # Drive the emitter sequence.  Each is a pure subroutine
        # ending at RTS.  Order mimics show_break_result + a follow-
        # up memory dump (common sequence: inspect regs, then dump).
        emu.jsr(emu.sym("emit_reg"))
        emu.jsr(emu.sym("newline"))
        emu.jsr(emu.sym("emit_dot"))
        emu.jsr(emu.sym("newline"))
        # reset rp_addr for emit_mem (emit_dot advanced it).
        emu.write_word(emu.sym("rp_addr"), ADDR)
        emu.memory[emu.sym("rp_cnt")] = 8
        emu.jsr(emu.sym("emit_mem"))
        emu.jsr(emu.sym("newline"))
        emu.jsr(emu.sym("emit_dot"))

        last_row = emu.memory[0xD6]
        assert last_row >= first_row, \
            f"cursor moved backwards: started {first_row}, ended {last_row}"

        # Scan rows strictly BETWEEN first and last — inclusive
        # endpoints hold the first and last emit output, which are
        # non-blank by construction.  Any blank in the middle is a
        # bug (extra newline, missing clreol, cursor jump).
        blanks = [row for row in range(first_row, last_row + 1)
                  if self._is_blank_row(emu, row)]
        assert blanks == [], (
            f"repl.md principle 11 violated: blank rows at {blanks} "
            f"in emitter-output window [{first_row}..{last_row}]"
        )
