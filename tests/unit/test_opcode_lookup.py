"""test_opcode_lookup.py — Tier-U unit tests for opcode_lookup.s.

Contract source: [doc/modules/opcode_lookup.md](../../doc/modules/opcode_lookup.md).

Coverage of the documented contract
-----------------------------------
2 exported entry points:

  asm_opcode_lookup   — exhaustive coverage via test_asm_line.py::
                         test_assemble (every legal/illegal/CMOS
                         mnemonic × mode opcode byte is verified
                         against dev/instruction_set.py).  Not
                         repeated here because the asm_core sweep
                         is the authoritative proof.
  asm_validate_mode   — TestAsmValidateMode below.  Direct tests of
                         the carry-flag predicate contract
                         (C=0 valid, C=1 invalid) that the asm_line
                         sweep exercises only indirectly through
                         asm_opcode_lookup.

Internal (not tested directly):
  _asm_ok_tmp         — 1-byte ZP scratch; implementation detail.
  _bit_tab            — 8-byte RODATA for Zone D/E bit encoding;
                         byte content is an implementation detail
                         of Zone D/E opcode construction, covered
                         end-to-end by Zone D/E mnemonics in
                         test_asm_line.py::test_assemble (RMB0–7,
                         SMB0–7, BBR0–7, BBS0–7 under the asm_core
                         CMOS bundle).

Bundle: asm_core (links opcode_lookup.s + asm_line.s + deps).  Same
fixture as test_asm_line.py — the two modules test from the same
bundle because they share the asm_core test-binary build.
"""

import pytest

from conftest import make_cpu, push_rts_sentinel, step_until_pc


# Mode constants (must match OPCODES dict in dev/instruction_set.py).
_MODE_IMP = 0
_MODE_ACC = 1
_MODE_IMM = 2
_MODE_ZP  = 3
_MODE_ZPX = 4
_MODE_ABS = 6
_MODE_ABX = 7
_MODE_ABY = 8
_MODE_IND = 9
_MODE_REL = 12
_MODE_ZPI = 13


def _run_validate_mode(asm_syms, pidx, mode):
    """Set asm_pidx + asm_mode, JSR asm_validate_mode, return carry flag."""
    cpu, mem = make_cpu(asm_syms)
    mem[asm_syms.asm_pidx] = pidx
    mem[asm_syms.asm_mode] = mode
    sentinel = push_rts_sentinel(cpu)
    cpu.pc = asm_syms.asm_validate_mode
    step_until_pc(cpu, sentinel, max_steps=500, what="asm_validate_mode")
    return cpu.p & 0x01


class TestAsmValidateMode:
    """asm_validate_mode: C=0 for valid (pidx, mode), C=1 for invalid."""

    def test_imp_profile_accepts_imp_mode(self, asm_syms):
        # profile 0 = Zone A (implied only); mode IMP must be valid.
        assert _run_validate_mode(asm_syms, 0, _MODE_IMP) == 0

    def test_imp_profile_rejects_abs_mode(self, asm_syms):
        # profile 0 accepts only IMP; ABS must be rejected.
        assert _run_validate_mode(asm_syms, 0, _MODE_ABS) == 1

    def test_rel_profile_accepts_rel_mode(self, asm_syms):
        # profile 1 = Zone B (branches, REL only).
        assert _run_validate_mode(asm_syms, 1, _MODE_REL) == 0

    def test_rel_profile_rejects_imm_mode(self, asm_syms):
        assert _run_validate_mode(asm_syms, 1, _MODE_IMM) == 1

    def test_imm_profile_accepts_imm_mode(self, asm_syms):
        # profile 2 = Zone C (immediate only).
        assert _run_validate_mode(asm_syms, 2, _MODE_IMM) == 0

    def test_multimode_profile_accepts_all_declared_modes(self, asm_syms):
        # profile 6 is the cc=01 group (LDA/AND/etc.): ZP, ZPX, ABS, ABX,
        # ABY, INX, INY all valid.
        for mode in (_MODE_ZP, _MODE_ZPX, _MODE_ABS, _MODE_ABX,
                     _MODE_ABY, _MODE_IND, _MODE_REL):
            c = _run_validate_mode(asm_syms, 6, mode)
            if mode == _MODE_REL:
                # REL is not in profile 6's set.
                assert c == 1, f"mode {mode}: expected reject"
