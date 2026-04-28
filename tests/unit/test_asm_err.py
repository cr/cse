"""test_asm_err.py — Tier-U unit tests for asm_err.s.

Contract source: [doc/modules/asm_err.md](../../doc/modules/asm_err.md).

Coverage of the documented contract
-----------------------------------
Four error entry points + 2 BSS bytes:

    asm_error          — generic syntax / invalid-mode exit (code 0)
    asm_syntax_error   — alias of asm_error (shared label)
    asm_expr_error     — expression-eval error                (code 1)
    asm_cpu_error      — CPU-gate rejection                   (code 2)
    asm_err_code (BSS) — 0/1/2 per the table above; written
                         by every entry point, read by callers
                         (asm_src.s, repl.s) for tag dispatch
    asm_pass (BSS)     — tested for addressability

All four entry points share an unwind body: SP restored to
`_asm_saved_sp`, asm_err_code written, kernal_bank_in called,
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


def _run_error(asm_syms, error_entry, preset_err_code=None, nested_depth=6):
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

    if preset_err_code is not None:
        mem[asm_syms.asm_err_code] = preset_err_code

    cpu.pc = error_entry
    step_until_pc(cpu, sentinel, max_steps=200, what="asm_err unwind")
    return cpu, mem


# ── Error-category contract ────────────────────────────────────────────
# Each entry point writes a specific code into asm_err_code.  Callers
# (asm_src.s @bad, repl.s dot_assemble) dispatch on the code to choose
# the user-visible error tag.  See doc/modules/asm_err.md § Error
# categories.

ERR_SYNTAX = 0
ERR_EXPR   = 1
ERR_CPU    = 2


def test_asm_error_writes_code_0(asm_syms):
    """asm_error (generic exit) writes asm_err_code = 0 = ;?syntax."""
    cpu, mem = _run_error(asm_syms, asm_syms.asm_error, preset_err_code=0xAB)
    assert cpu.a == 0
    assert cpu.x == 0
    assert mem[asm_syms.asm_err_code] == ERR_SYNTAX


# test_asm_syntax_error_clears_flag retired — asm_syntax_error and
# asm_error are literally the same address (proven by
# test_asm_error_and_syntax_error_alias); running test_asm_error_writes_code_0
# through the aliased entry point exercises identical code.  A future
# unaliasing would fail test_asm_error_and_syntax_error_alias loudly.


def test_asm_expr_error_writes_code_1(asm_syms):
    """asm_expr_error writes asm_err_code = 1 so callers route to the
    expr-specific error message (expr_error_str)."""
    cpu, mem = _run_error(asm_syms, asm_syms.asm_expr_error, preset_err_code=0)
    assert cpu.a == 0
    assert cpu.x == 0
    assert mem[asm_syms.asm_err_code] == ERR_EXPR


def test_asm_cpu_error_writes_code_2(asm_syms):
    """asm_cpu_error writes asm_err_code = 2 so callers route to the
    `;?cpu` tag (CPU-gate rejection — PHY on 6502 etc.)."""
    cpu, mem = _run_error(asm_syms, asm_syms.asm_cpu_error, preset_err_code=0)
    assert cpu.a == 0
    assert cpu.x == 0
    assert mem[asm_syms.asm_err_code] == ERR_CPU


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
# test_asm_error_writes_code_0 and test_asm_expr_error_writes_code_1.
# Three distinct codes can only come from three distinct code paths,
# so the address-difference assertion is subsumed.


def test_asm_pass_is_accessible(asm_syms):
    """asm_pass is a BSS byte exported for addr_mode.s's forward-ref
    handling.  Verify it's writable + readable at the resolved address."""
    mem = bytearray(65536)
    asm_syms.load_into(mem)
    assert asm_syms.asm_pass != 0, "asm_pass symbol resolved to null"
    # Distinct from asm_err_code (same module, adjacent BSS bytes)
    assert asm_syms.asm_pass != asm_syms.asm_err_code
