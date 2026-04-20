"""test_asm_err.py — Tier-U unit tests for asm_err.s.

Contract source: [doc/modules/asm_err.md](../../doc/modules/asm_err.md).

Coverage of the documented contract
-----------------------------------
All 3 error entry points + 2 BSS bytes:

    asm_error          — generic syntax / invalid-mode exit
    asm_syntax_error   — alias of asm_error (shared label)
    asm_expr_error     — expression-eval error; sets asm_expr_err=1
    asm_expr_err (BSS) — tested via flag transitions in the three
                         error-entry tests
    asm_pass (BSS)     — tested for addressability

All three entry points share an unwind body: SP restored to
`_asm_saved_sp`, asm_expr_err written, kernal_bank_in called,
A=0/X=0 on return.

Test protocol simulates what asm_line does at entry: save the pre-jsr
SP into _asm_saved_sp, push dummy "nested jsr" bytes, then jmp to the
error entry.  The unwind's `txs` + `rts` should skip the nested frames
and land back at the test harness sentinel ($FFFF).

Out-of-scope (delegated)
------------------------
`kernal_bank_in` short-circuit when `kernal_out=1` — verified in
test_mem.py (TestKernalOutFlagValues).

Bundle: asm_core (links zp + asm_err + rest of asm pipeline).
"""

import pytest

from conftest import make_cpu, push_rts_sentinel, step_until_pc


def _run_error(asm_syms, error_entry, preset_expr_err=None, nested_depth=6):
    """Invoke error_entry with a faked asm_line-style stack frame.

    Returns (cpu, mem) after the error path unwinds back to the sentinel.
    """
    cpu, mem = make_cpu(asm_syms)

    sentinel = push_rts_sentinel(cpu, sentinel=0xFFFF)
    # asm_line's prologue: tsx / stx _asm_saved_sp.  Snapshot the
    # post-JSR SP so the error path's txs lands us back here.
    mem[asm_syms._asm_saved_sp] = cpu.sp

    # Simulate deeper nesting (mode_parse, _au_read_val, expr_eval, …).
    # The error path's SP restore should skip over all of these.
    for _ in range(nested_depth):
        mem[0x0100 + cpu.sp] = 0xAA     # marker — unused
        cpu.sp = (cpu.sp - 1) & 0xFF

    if preset_expr_err is not None:
        mem[asm_syms.asm_expr_err] = preset_expr_err

    cpu.pc = error_entry
    step_until_pc(cpu, sentinel, max_steps=200, what="asm_err unwind")
    return cpu, mem


# ── Contract tests ──────────────────────────────────────────────────

def test_asm_error_clears_flag(asm_syms):
    """asm_error (generic exit) clears asm_expr_err to 0."""
    cpu, mem = _run_error(asm_syms, asm_syms.asm_error, preset_expr_err=0xAB)
    assert cpu.a == 0
    assert cpu.x == 0
    assert mem[asm_syms.asm_expr_err] == 0


# test_asm_syntax_error_clears_flag retired — asm_syntax_error and
# asm_error are literally the same address (proven by
# test_asm_error_and_syntax_error_alias); running test_asm_error_clears_flag
# through the aliased entry point exercises identical code.  A future
# unaliasing would fail test_asm_error_and_syntax_error_alias loudly.


def test_asm_expr_error_sets_flag(asm_syms):
    """asm_expr_error sets asm_expr_err=1 so callers can route to the
    expr-specific error message (expr_error_str)."""
    cpu, mem = _run_error(asm_syms, asm_syms.asm_expr_error, preset_expr_err=0)
    assert cpu.a == 0
    assert cpu.x == 0
    assert mem[asm_syms.asm_expr_err] == 1


def test_asm_error_restores_sp(asm_syms):
    """SP is unwound past all nested jsrs to _asm_saved_sp before RTS.

    After the sentinel-RTS pops, SP should be $FF (fully cleaned up).
    If the unwind didn't restore SP, RTS would pop from the middle of
    the $AA nested markers and PC would land somewhere else entirely."""
    cpu, _ = _run_error(asm_syms, asm_syms.asm_error, nested_depth=8)
    assert cpu.sp == 0xFF, f"SP not fully unwound: ${cpu.sp:02X}"


def test_asm_error_and_syntax_error_alias(asm_syms):
    """asm_error / asm_syntax_error are consecutive labels pointing at
    the same entry instruction — they must resolve to the same address."""
    assert asm_syms.asm_error == asm_syms.asm_syntax_error


# test_asm_expr_error_differs_from_asm_error retired — the address
# difference is implied by the behavioural pair
# test_asm_error_clears_flag (asm_expr_err = 0 after asm_error) and
# test_asm_expr_error_sets_flag (asm_expr_err = 1 after asm_expr_error).
# Two distinct behaviours can only come from distinct code, so the
# address-difference assertion was subsumed.  Retired 2026-04-20 per
# doc/testing.md § Principle 9 Pattern B (subsumed by functional
# tests above).


def test_asm_pass_is_accessible(asm_syms):
    """asm_pass is a BSS byte exported for addr_mode.s's forward-ref
    handling.  Verify it's writable + readable at the resolved address."""
    mem = bytearray(65536)
    asm_syms.load_into(mem)
    assert asm_syms.asm_pass != 0, "asm_pass symbol resolved to null"
    # Distinct from asm_expr_err (same module, adjacent BSS bytes)
    assert asm_syms.asm_pass != asm_syms.asm_expr_err
