"""test_opcode_lookup.py — Tier-U unit tests for opcode_lookup.s.

Contract source: [doc/modules/opcode_lookup.md](../../doc/modules/opcode_lookup.md).

Coverage of the documented contract
-----------------------------------
2 exported entry points:

  asm_opcode_lookup   — TestAsmOpcodeLookup: every accepted
                         (pidx, mode) of the bundle's CPU set yields
                         base ^ delta as the profile-row model states;
                         end to end, test_asm_line.py::test_assemble
                         checks every mnemonic × mode against
                         dev/instruction_set.py.
  asm_validate_mode   — TestAsmValidateMode below.  Direct tests of
                         the carry-flag predicate contract
                         (C=0 valid, C=1 invalid) that the asm_line
                         sweep exercises only indirectly through
                         asm_opcode_lookup.

Internal (not tested directly):
  _bit_tab            — 8-byte RODATA: the mode's bit within its mask
                         plane; covered by the exhaustive validate sweep.

Bundle: asm_core (links opcode_lookup.s + asm_line.s + deps).  Same
fixture as test_asm_line.py — the two modules test from the same
bundle because they share the asm_core test-binary build.
"""

import functools
import pathlib
import sys

import pytest

from conftest import make_cpu, push_rts_sentinel, step_until_pc

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import mnemonic_tables as _MT                     # noqa: E402


@functools.lru_cache(maxsize=None)
def _MODEL():
    """The profile-row model of the asm_syms bundle's CPU set (65C02)."""
    return _MT.build_asm_model('65c02')


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

    def test_lda_profile_accepts_exactly_its_modes(self, asm_syms):
        """The LDA key's NMOS profile (pidx from the generated model)."""
        m = _MODEL()
        pidx = m.key_prof['LDA'] & 0x3F
        for mode in range(m.n_modes):
            want = 0 if (m.mask(pidx) >> mode) & 1 else 1
            assert _run_validate_mode(asm_syms, pidx, mode) == want, mode

    def test_every_pidx_mode_matches_the_model(self, asm_syms):
        """Exhaustive: C equals the model's mask bit for every (pidx, mode)."""
        m = _MODEL()
        bad = [(p, mode) for p in range(len(m.profiles))
               for mode in range(m.n_modes)
               if _run_validate_mode(asm_syms, p, mode)
               != (0 if (m.mask(p) >> mode) & 1 else 1)]
        assert not bad, bad[:10]


class TestAsmOpcodeLookup:
    """asm_opcode_lookup: A = asm_base ^ asm_delta[asm_row[pidx] + mode]."""

    def test_every_accepted_pair(self, asm_syms):
        m = _MODEL()
        bad = []
        for p in range(len(m.profiles)):
            for mode in range(m.n_modes):
                if not (m.mask(p) >> mode) & 1:
                    continue
                for base in (0x00, 0xA5):
                    cpu, mem = make_cpu(asm_syms)
                    mem[asm_syms.asm_pidx] = p
                    mem[asm_syms.asm_mode] = mode
                    mem[asm_syms.asm_base] = base
                    sentinel = push_rts_sentinel(cpu)
                    cpu.pc = asm_syms.asm_opcode_lookup
                    step_until_pc(cpu, sentinel, max_steps=200, what="lookup")
                    want = base ^ m.rows[m.row_of[p]][mode]
                    if cpu.a != want:
                        bad.append((p, mode, base, cpu.a, want))
        assert not bad, bad[:10]
