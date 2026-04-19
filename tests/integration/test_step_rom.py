"""
test_step_rom.py — Debugger step-into JSR with ROM target fallback.

Verifies that cmd_step ('t1') correctly falls back to step-over when
the JSR target is in KERNAL ROM ($E000-$FFFF), and steps into RAM
targets normally.  Uses C64Emu with the production PRG.

Replaces the xfailed TestStepIntoJSR_ROMFallback in test_repl.py.
"""

import pytest
from c64emu import C64Emu

USER_CODE = 0x3000   # address where we place the test JSR


def _run_step(cse_prg, target_lo, target_hi):
    """Set up a JSR at USER_CODE, run 't1' via exec_line, return the
    step_bp[0] address that cmd_step armed.

    Under the Phase-18 handler-resident model cmd_step rts's back up
    the jsr chain after arming step_bp; main_loop would then jmp to
    return_to_userland at top level.  In this test we stop at the exec_line
    rts (no main_loop) and observe step_bp[0] directly.
    """
    prg, map_path = cse_prg
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.init_cse()

    sb = emu.sym("step_bp")
    dr = emu.sym("dbg_reason")
    bh = emu.sym("dbg_bp_hit")

    # User code: JSR <target>
    emu.memory[USER_CODE]     = 0x20
    emu.memory[USER_CODE + 1] = target_lo
    emu.memory[USER_CODE + 2] = target_hi

    # Debugger state: stopped at USER_CODE (dbg_reason!=0 so cmd_step
    # treats brk_pc as authoritative and skips cur_addr init).
    emu.write_word(emu.sym("cur_addr"), USER_CODE)
    emu.write_word(emu.sym("brk_pc"), USER_CODE)
    emu.memory[dr] = 1
    emu.memory[bh] = 0xFF
    emu.write_word(emu.sym("block_size"), 0x0001)
    for i in range(8):
        emu.memory[sb + i] = 0

    # "t1" in line_buf (PETSCII: t=$54, 1=$31)
    lb = emu.sym("line_buf")
    emu.memory[lb]     = 0x54
    emu.memory[lb + 1] = 0x31
    emu.memory[lb + 2] = 0x00

    emu.jsr(emu.sym("exec_line"), max_cycles=200_000)
    return emu.memory[sb] | (emu.memory[sb + 1] << 8)


class TestStepIntoJSR_ROMFallback:
    """JSR step-into to KERNAL ROM falls back to step-over."""

    def test_jsr_into_ram_steps_into(self, cse_prg):
        assert _run_step(cse_prg, 0x10, 0x30) == 0x3010

    def test_jsr_into_kernal_steps_over(self, cse_prg):
        assert _run_step(cse_prg, 0xD2, 0xFF) == USER_CODE + 3

    def test_jsr_into_e000_boundary_steps_over(self, cse_prg):
        assert _run_step(cse_prg, 0x00, 0xE0) == USER_CODE + 3

    def test_jsr_into_ffff_boundary_steps_over(self, cse_prg):
        assert _run_step(cse_prg, 0xFF, 0xFF) == USER_CODE + 3

    def test_jsr_into_a000_steps_into(self, cse_prg):
        assert _run_step(cse_prg, 0x00, 0xA0) == 0xA000

    def test_jsr_into_bfff_steps_into(self, cse_prg):
        assert _run_step(cse_prg, 0xFF, 0xBF) == 0xBFFF

    def test_jsr_into_c000_steps_into(self, cse_prg):
        assert _run_step(cse_prg, 0x00, 0xC0) == 0xC000

    def test_jsr_into_dfff_steps_into(self, cse_prg):
        assert _run_step(cse_prg, 0xFF, 0xDF) == 0xDFFF
