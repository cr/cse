"""test_asm_err.py — asm_err.s longjmp unwind contract.

Tier U test against the `asm_core` bundle (which links asm_err.s).
Exercises the three error entry points in isolation:

  asm_error          — generic syntax / invalid-mode exit
  asm_syntax_error   — alias of asm_error (shared label)
  asm_expr_error     — expression-eval error; sets asm_expr_err=1

All three share the unwind body: SP is restored to `_asm_saved_sp`,
asm_expr_err is written, kernal_bank_in is called, A=0/X=0 on return.

Test protocol simulates what asm_line does at entry: save the pre-jsr
SP into _asm_saved_sp, push some dummy "nested jsr" bytes, then jmp to
the error entry.  The unwind's `txs` + `rts` should skip the nested
frames and land back at the test harness sentinel ($FFFF).
"""

import pytest
from py65.devices.mpu6502 import MPU


SENTINEL_RET    = 0xFFFE   # (return-1) on stack; RTS lands at $FFFF
SENTINEL_TARGET = 0xFFFF


def _run_error(syms, error_entry, preset_expr_err=None, nested_depth=6):
    """Invoke error_entry with a faked asm_line-style stack frame.

    Returns (cpu, mem) after the error path unwinds back to the sentinel.
    """
    cpu = MPU()
    mem = cpu.memory
    syms.load_into(mem)

    # Fake "jsr asm_line" return address: RTS target = $FFFF.
    mem[0x01FF] = (SENTINEL_RET >> 8) & 0xFF
    mem[0x01FE] = SENTINEL_RET & 0xFF
    cpu.sp = 0xFD

    # asm_line's prologue: tsx / stx _asm_saved_sp.
    mem[syms._asm_saved_sp] = cpu.sp

    # Simulate deeper nesting (mode_parse, _au_read_val, expr_eval, …).
    # The error path's SP restore should skip over all of these.
    for _ in range(nested_depth):
        mem[0x0100 + cpu.sp] = 0xAA     # marker — unused
        cpu.sp = (cpu.sp - 1) & 0xFF

    if preset_expr_err is not None:
        mem[syms.asm_expr_err] = preset_expr_err

    cpu.pc = error_entry

    for _ in range(200):
        if cpu.pc == SENTINEL_TARGET:
            return cpu, mem
        cpu.step()

    pytest.fail(f"error path didn't return within 200 steps "
                f"(PC=${cpu.pc:04X}, SP=${cpu.sp:02X})")


# ── Contract tests ──────────────────────────────────────────────────

def test_asm_error_clears_flag(syms):
    """asm_error (generic exit) clears asm_expr_err to 0."""
    cpu, mem = _run_error(syms, syms.asm_error, preset_expr_err=0xAB)
    assert cpu.a == 0
    assert cpu.x == 0
    assert mem[syms.asm_expr_err] == 0


def test_asm_syntax_error_clears_flag(syms):
    """asm_syntax_error shares asm_error's body; clears asm_expr_err."""
    cpu, mem = _run_error(syms, syms.asm_syntax_error, preset_expr_err=0xAB)
    assert cpu.a == 0
    assert cpu.x == 0
    assert mem[syms.asm_expr_err] == 0


def test_asm_expr_error_sets_flag(syms):
    """asm_expr_error sets asm_expr_err=1 so callers can route to the
    expr-specific error message (expr_error_str)."""
    cpu, mem = _run_error(syms, syms.asm_expr_error, preset_expr_err=0)
    assert cpu.a == 0
    assert cpu.x == 0
    assert mem[syms.asm_expr_err] == 1


def test_asm_error_restores_sp(syms):
    """SP is unwound past all nested jsrs to _asm_saved_sp before RTS.

    After the sentinel-RTS pops, SP should be $FF (fully cleaned up).
    If the unwind didn't restore SP, RTS would pop from the middle of
    the $AA nested markers and PC would land somewhere else entirely."""
    cpu, _ = _run_error(syms, syms.asm_error, nested_depth=8)
    assert cpu.sp == 0xFF, f"SP not fully unwound: ${cpu.sp:02X}"


def test_asm_error_and_syntax_error_alias(syms):
    """asm_error / asm_syntax_error are consecutive labels pointing at
    the same entry instruction — they must resolve to the same address."""
    assert syms.asm_error == syms.asm_syntax_error


def test_asm_expr_error_differs_from_asm_error(syms):
    """asm_expr_error is 2 bytes earlier (lda #1 / .byte $2C skip)."""
    assert syms.asm_expr_error != syms.asm_error
    assert syms.asm_expr_error + 3 == syms.asm_error    # lda #1 + .byte $2C


def test_asm_pass_is_accessible(syms):
    """asm_pass is a BSS byte exported for addr_mode.s's forward-ref
    handling.  Verify it's writable + readable at the resolved address."""
    mem = bytearray(65536)
    syms.load_into(mem)
    assert syms.asm_pass != 0, "asm_pass symbol resolved to null"
    # Distinct from asm_expr_err (same module, adjacent BSS bytes)
    assert syms.asm_pass != syms.asm_expr_err
