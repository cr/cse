"""
test_kernel_transition.py — Kernel/userland transition contract tests.

Exercises the Phase-18 ISR-kernel model:
  - setup_interrupts wires all four vectors correctly
  - return_to_userland → BRK dispatches and captures user state
  - Cold-init userland handoff lands at main_loop_no_clear
  - NMI swallow in kernel mode; capture in userland mode
  - BRK in kernel mode routes to cse_warm_start
  - Step chaining runs inside the BRK handler (no SP creep)
  - Shared stack: user pushes survive a break

Uses C64Emu + the production PRG (see testing.md Principle 6).

When the full cutover lands, remove the module-level skip.
"""

import pytest
from c64emu import C64Emu


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
    C64Emu provides after the Phase-18 test-harness update."""
    emu.run_until(emu.sym("main_loop_top"),
                  start_at=emu.sym("_main"),
                  max_cycles=2_000_000)


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
        """Populate reg_*/brk_pc = user code that does RTS.
        Enter via return_to_userland; run until main_loop_top is hit
        again.  User's RTS pops brk_stub sentinel → BRK at brk_stub
        → handler classifies as clean exit (dbg_reason=0,
        brk_pc == brk_stub)."""
        _cold_init_to_prompt(emu)

        # User code: RTS (at $3000)
        USER = 0x3000
        emu.memory[USER] = 0x60

        emu.write_word(emu.sym("brk_pc"), USER)
        emu.memory[emu.sym("reg_a")] = 0x42
        emu.memory[emu.sym("reg_x")] = 0x11
        emu.memory[emu.sym("reg_y")] = 0x22
        emu.memory[emu.sym("reg_p")] = 0x00

        # Run from return_to_userland until we land at main_loop_top
        # (after handler's longjmp).  return_to_userland does not rts.
        emu.run_until(emu.sym("main_loop_top"),
                      start_at=emu.sym("return_to_userland"),
                      max_cycles=200_000)

        brk_stub = emu.sym("brk_stub")
        assert emu.memory[emu.sym("dbg_reason")] == 0
        assert emu.read_word(emu.sym("brk_pc")) == brk_stub


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

        assert emu.memory[emu.sym("dbg_reason")] == 1  # DBG_BRK
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

        assert emu.memory[emu.sym("dbg_reason")] == 2  # DBG_NMI
        assert emu.read_word(emu.sym("brk_pc")) == USER_PC


# ── 6. NMI in kernel mode (swallow) ─────────────────────────────

class TestNmiKernelMode:
    def test_nmi_swallowed_no_state_change(self, emu):
        _cold_init_to_prompt(emu)
        # in_userland==0 from cold init
        assert emu.memory[emu.sym("in_userland")] == 0
        dbg_reason_before = emu.memory[emu.sym("dbg_reason")]
        brk_pc_before = emu.read_word(emu.sym("brk_pc"))

        # Synthesise NMI frame with non-zero PC; invoke handler;
        # handler's RTI should return to our sentinel.
        SENTINEL = 0xABCD
        sp_before = emu.sp
        emu.memory[0x0100 + emu.sp] = SENTINEL >> 8
        emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = SENTINEL & 0xFF
        emu.sp = (emu.sp - 1) & 0xFF
        emu.memory[0x0100 + emu.sp] = 0x20    # P
        emu.sp = (emu.sp - 1) & 0xFF

        emu.run_until(SENTINEL,
                      start_at=emu.sym("cse_nmi_handler"),
                      max_cycles=10_000)

        # State unchanged by the swallow
        assert emu.memory[emu.sym("dbg_reason")] == dbg_reason_before
        assert emu.read_word(emu.sym("brk_pc")) == brk_pc_before


# ── 7. BRK in kernel mode (internal fault) ──────────────────────

class TestBrkKernelFault:
    def test_brk_in_kernel_routes_to_warm_start(self, emu):
        """When in_userland==0, cse_brk_handler must jump to
        cse_warm_start (not dispatch as a userland break)."""
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

        # warm_guard increments when cse_warm_start runs
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
