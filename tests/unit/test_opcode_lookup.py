"""test_opcode_lookup.py — Tier-U unit tests for opcode_lookup.s.

Owner: doc/modules/opcode_lookup.md

Contract source: [doc/modules/opcode_lookup.md](../../doc/modules/opcode_lookup.md).

Coverage of the documented contract
-----------------------------------
1 exported entry point:

  asm_opcode_lookup   — TestAsmOpcodeLookup: for every (pidx, mode) of
                         each C64 CPU set, C=1 exactly where the profile
                         rejects the mode, and otherwise
                         A = asm_base ^ delta as the profile-row model
                         states.  End to end, test_asm_line.py::
                         test_assemble checks every mnemonic × mode
                         against dev/instruction_set.py.

Internal (not tested directly):
  _bit_tab            — 8-byte RODATA: the mode's bit within its mask
                         plane; covered by the exhaustive sweep.

Bundle: asm_core, one variant per CPU set (the same binaries as
test_asm_line.py).
"""

import functools
import pathlib
import sys

import pytest

from conftest import AsmCoreSymbols, make_cpu, push_rts_sentinel, step_until_pc

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import mnemonic_tables as MT                      # noqa: E402

N_CATALOGUE_MODES = 16      # mode_parse can return any C64 catalogue mode


@functools.lru_cache(maxsize=None)
def _bundle(cpu_set):
    return AsmCoreSymbols(config=cpu_set), MT.build_asm_model(cpu_set)


def _lookup(syms, pidx, mode, base):
    """Call asm_opcode_lookup; return (carry, A)."""
    cpu, mem = make_cpu(syms)
    mem[syms.asm_pidx] = pidx
    mem[syms.asm_mode] = mode
    mem[syms.asm_base] = base
    sentinel = push_rts_sentinel(cpu)
    cpu.pc = syms.asm_opcode_lookup
    step_until_pc(cpu, sentinel, max_steps=200, what="asm_opcode_lookup")
    return cpu.p & 0x01, cpu.a


@pytest.mark.parametrize("cpu_set", list(MT.CPU_SETS))
class TestAsmOpcodeLookup:
    """asm_opcode_lookup: C=1 for a rejected mode, else C=0 and
    A = asm_base ^ asm_delta[asm_row[pidx] + mode]."""

    def test_every_pidx_and_mode(self, cpu_set):
        syms, model = _bundle(cpu_set)
        bad = []
        for pidx in range(len(model.profiles)):
            for mode in range(N_CATALOGUE_MODES):
                accepted = (model.mask(pidx) >> mode) & 1
                for base in (0x00, 0xA5):
                    carry, a = _lookup(syms, pidx, mode, base)
                    if not accepted:
                        if carry != 1:
                            bad.append((pidx, mode, 'accepted a rejected mode'))
                        continue
                    want = base ^ model.rows[model.row_of[pidx]][mode]
                    if carry != 0 or a != want:
                        bad.append((pidx, mode, base, carry, a, want))
        assert not bad, bad[:10]
