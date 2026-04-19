"""
test_mnhash.py – pytest tests verifying that the mn6 and mn7 assembly
implementations match the Python reference in dev/hashes.py.

Strategy
--------
A single helper runs the assembled classify routine via the py65 6502
emulator for a given (c1, c2, c3) input and returns (carry, slot).  Two
test functions then perform an exhaustive sweep over all 17,576 three-letter
strings, asserting that the ASM result matches the Python reference for
every string — including the 16 known mn6 false positives.

The sweep reuses one MPU instance per variant (load binary once, then just
write ZP inputs and reset SP/PC for each call) to keep the run time short.
"""

import sys
import pathlib
import pytest
from py65.devices.mpu6502 import MPU

# Make dev/ importable
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "dev"))
from hashes import mn6, mn7
from instruction_set import sc

# ── Constants ────────────────────────────────────────────────────────────────

_LETTERS   = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
_MAX_STEPS = 200   # generous safety limit for the ~20-instruction routines


# ── Core runner ──────────────────────────────────────────────────────────────

def _run_classify(cpu, mem, syms, c1, c2, c3):
    """
    Write c1/c2/c3 into ZP, call the classify routine, return (carry, slot).

    Reuses the same MPU and memory image — only the ZP inputs, SP, and PC
    are touched between calls, keeping per-call overhead minimal.
    """
    mem[syms.mn_c1] = c1
    mem[syms.mn_c2] = c2
    mem[syms.mn_c3] = c3

    # Fake JSR: push $FFFE so RTS lands at $FFFF
    cpu.sp         = 0xFF
    mem[0x01FF]    = 0xFF
    mem[0x01FE]    = 0xFE
    cpu.sp         = 0xFD
    cpu.pc         = syms.classify

    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            carry = cpu.p & 0x01
            slot  = cpu.a
            return carry, slot
        cpu.step()

    raise TimeoutError(
        f"classify timed out for c1={c1} c2={c2} c3={c3}"
        f" after {_MAX_STEPS} steps"
    )


# ── Python reference ─────────────────────────────────────────────────────────

def _py_classify(cls, c1, c2, c3):
    """
    Python reference: return (carry, slot) matching the ASM calling convention.

    carry=0 (valid) iff the string hashes to an occupied slot AND the
    fingerprint matches.  slot is always the raw hash value (meaningful
    only when carry=0).
    """
    mask     = cls._mask()
    slot_mne = cls.build_slot_map()
    fp_table = cls.fingerprint_table()

    h = (c1 * cls.C1 + c3 * cls.C3 + cls.T[c2]) & mask
    if h in slot_mne and fp_table[h] == cls.fingerprint(c1, c2, c3):
        return 0, h   # carry clear → valid
    return 1, h       # carry set → invalid


# ── Sweep helper ─────────────────────────────────────────────────────────────

def _full_sweep(cls, syms_fixture):
    """
    Run every 3-letter string through both ASM and Python, assert they agree.

    Returns (n_valid, n_invalid) counts for informational purposes.
    """
    cpu = MPU()
    mem = cpu.memory
    syms_fixture.load_into(mem)

    # Cache Python slot map and fp table once (avoid recomputing 17576×)
    mask     = cls._mask()
    slot_mne = cls.build_slot_map()
    fp_table = cls.fingerprint_table()

    n_valid = n_invalid = 0
    mismatches = []

    for a in _LETTERS:
        for b in _LETTERS:
            for c in _LETTERS:
                c1v, c2v, c3v = sc(a), sc(b), sc(c)

                # Python expected result
                h = (c1v * cls.C1 + c3v * cls.C3 + cls.T[c2v]) & mask
                py_valid = (h in slot_mne
                            and fp_table[h] == cls.fingerprint(c1v, c2v, c3v))
                py_carry = 0 if py_valid else 1

                # ASM actual result
                asm_carry, asm_slot = _run_classify(
                    cpu, mem, syms_fixture, c1v, c2v, c3v
                )

                if asm_carry != py_carry:
                    mismatches.append(
                        f"{a+b+c}: py_carry={py_carry} asm_carry={asm_carry}"
                    )
                elif py_valid and asm_slot != h:
                    mismatches.append(
                        f"{a+b+c}: carry=0 but asm_slot={asm_slot:#04x}"
                        f" != py_slot={h:#04x}"
                    )

                if py_valid:
                    n_valid += 1
                else:
                    n_invalid += 1

    assert not mismatches, (
        f"{len(mismatches)} mismatch(es):\n" + "\n".join(mismatches[:20])
    )
    return n_valid, n_invalid


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_mn6_full_sweep(mn6_syms):
    """
    Exhaustive sweep: all 17,576 three-letter strings through mn6_classify.

    Verified properties
    -------------------
    • All 56 legal NMOS mnemonics → carry=0, correct slot.
    • All 16 known false positives → carry=0, correct slot  (fingerprint
      collision by design; they are not legal mnemonics but pass the check).
    • All remaining strings → carry=1.
    • ASM and Python agree exactly on every string.
    """
    n_valid, n_invalid = _full_sweep(mn6, mn6_syms)
    # 56 legal + 16 false positives = 72 strings return carry=0
    assert n_valid   == 56 + 16, f"Expected 72 carry=0, got {n_valid}"
    assert n_invalid == 17576 - 72


def test_mn7_full_sweep(mn7_syms):
    """
    Exhaustive sweep: all 17,576 three-letter strings through mn7_classify.

    Verified properties
    -------------------
    • All 114 mnemonics (legal + illegal + CMOS) → carry=0, correct slot.
    • Zero false positives: every other string → carry=1.
    • ASM and Python agree exactly on every string.
    """
    n_valid, n_invalid = _full_sweep(mn7, mn7_syms)
    assert n_valid   == 114,          f"Expected 114 carry=0, got {n_valid}"
    assert n_invalid == 17576 - 114
