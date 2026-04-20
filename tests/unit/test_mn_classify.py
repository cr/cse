"""
test_mn_classify.py — Tier-I unit tests for the mn_classify subsystem.

Covers the four source files that the mn_classify module groups together
([doc/modules/mn_classify.md](../../doc/modules/mn_classify.md)):

    src/mn_classify.s   build-time dispatcher forwarding to mn6/mn7
    src/mn7.s           7-bit-hash classifier (114 mnemonics, default)
    src/mn6.s           6-bit-hash classifier (56 legal NMOS, -D USE_MN6)
    src/mn_vars.s       shared ZP inputs (mn_c1/mn_c2/mn_c3)

Coverage of the documented contract
-----------------------------------
* classify entry point for both variants — full 26³ = 17 576 three-letter
  sweep against the Python reference in `dev/hashes.py`.  Asserts carry
  (recognised vs. rejected) and slot on every input.
* `mn_classify` dispatcher — forwards identically to the selected
  classifier under both build flavours (default mn7 / `-D USE_MN6`).
* `mn_base_op[slot]` / `mn_profile[slot]` — every recognised slot's
  table entries cross-checked against the Python generator
  (`dev/mnemonic_tables.py`).  The `mn_profile` byte's packed format
  (bits 7:6=cat, bit 5=dir, bits 4:0=profile) is verified bit-for-bit.
* Y-clobber contract — doc says both classifiers clobber Y; verified.
* Encoding-agnostic input — PETSCII-upper, PETSCII-lower, and VICII
  screencodes all `AND #$1F` to the same 1–26 value; the classifier's
  output is identical across all three normalisations.

Fixtures
--------
Both `mn6_syms` and `mn7_syms` bundles (see conftest.py) now also link
`mn_classify.s` so the dispatcher is reachable from test code.  The mn6
bundle is built with `-D USE_MN6` so the dispatcher forwards to
`mn6_classify`; the mn7 bundle uses the default (mn7).

Strategy
--------
One MPU instance per variant (loaded once), then per-test write the ZP
inputs and reset SP/PC for each call.  Keeps sweep runtime well under a
second.
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


# ─── Table-value coverage ────────────────────────────────────────────────────
#
# The sweep above proves the hash and fingerprint tables drive the
# correct recognise/reject decision, but it does NOT verify what the
# caller reads from mn_base_op[slot] / mn_profile[slot] after a hit.
# The tests below close that gap by cross-checking every slot against
# the Python authority in dev/mnemonic_tables.py.

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "dev"))
from mnemonic_tables import (  # noqa: E402 — import after sys.path tweak above
    _compute_base_opcode,
    _compute_cat,
    _compute_dir_bit,
)
from instruction_set import MNEMONICS    # noqa: E402


def _expected_profile_byte(mne):
    """Packed profile byte as generated by mnemonic_tables.py:
    bits 7:6 = cat, bit 5 = dir, bits 4:0 = profile index."""
    profile, _, _ = MNEMONICS[mne]
    cat = _compute_cat(mne)
    dir_flag = 1 if _compute_dir_bit(mne) else 0
    return (cat << 6) | (dir_flag << 5) | profile


def _run_once(cpu, mem, syms, c1, c2, c3, entry_addr):
    """Call `entry_addr` once with ZP primed."""
    mem[syms.mn_c1] = c1
    mem[syms.mn_c2] = c2
    mem[syms.mn_c3] = c3
    cpu.sp       = 0xFF
    mem[0x01FF]  = 0xFF
    mem[0x01FE]  = 0xFE
    cpu.sp       = 0xFD
    cpu.pc       = entry_addr
    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            return cpu.p & 0x01, cpu.a
        cpu.step()
    raise TimeoutError(f"timeout calling ${entry_addr:04X}")


def _table_check(cls, syms_fixture):
    """For every recognised mnemonic, assert mn_base_op[slot] and
    mn_profile[slot] match the Python authority."""
    cpu = MPU()
    mem = cpu.memory
    syms_fixture.load_into(mem)

    slot_mne = cls.build_slot_map()
    errors = []
    for slot, mne in slot_mne.items():
        # Pull the slot's table entries directly from RAM (the binary
        # loaded them into the RODATA block at load time).
        got_base = mem[syms_fixture.mn_base_op + slot]
        got_prof = mem[syms_fixture.mn_profile + slot]

        want_base = _compute_base_opcode(mne)
        if want_base is None:
            want_base = 0x00
        want_prof = _expected_profile_byte(mne)

        if got_base != want_base:
            errors.append(f"{mne} slot {slot}: base_op got ${got_base:02X}, "
                          f"want ${want_base:02X}")
        if got_prof != want_prof:
            errors.append(f"{mne} slot {slot}: profile got ${got_prof:02X}, "
                          f"want ${want_prof:02X}")

    assert not errors, \
        f"{len(errors)} table mismatches:\n" + "\n".join(errors[:20])


def test_mn7_table_values(mn7_syms):
    """Every recognised mn7 mnemonic maps to the correct (base_op, profile)
    at its hash slot."""
    _table_check(mn7, mn7_syms)


def test_mn6_table_values(mn6_syms):
    """Every recognised mn6 mnemonic maps to the correct (base_op, profile)
    at its hash slot."""
    _table_check(mn6, mn6_syms)


# ─── Internal tables: NOT tested for content (implementation detail) ─────────
#
# `mn*_fp` (fingerprint table) and `mn*_hash_t` (27-byte T perturbation
# table) are documented in mn_classify.md but are NOT exported across
# a module boundary — they are consumed only inside mn7.s / mn6.s.
# Their byte-level contents are an implementation detail of HOW the
# classifier decides match/miss; the CONTRACT is the classifier's
# observable (carry, slot) behaviour, which is verified exhaustively
# by the 17 576-input sweeps above.
#
# We deliberately do not pin the table bytes here: any regeneration
# of mn*_tables.s (which is allowed — it's a generated file) would
# break byte-level tests even though the classifier still behaves
# correctly.  The skipped tests below document this decision
# explicitly so future maintainers see why the gap exists.


@pytest.mark.skip(reason=(
    "mn*_fp fingerprint-table contents are implementation detail, "
    "not contract.  The classifier's observable behaviour (carry, "
    "slot) is verified exhaustively by test_mn[67]_full_sweep for "
    "all 17 576 three-letter inputs, which subsumes byte-level fp "
    "correctness.  Pinning fp bytes would break on any legitimate "
    "table regeneration (mn*_tables.s is GENERATED per mn_classify.md)."
))
def test_mn7_fingerprint_table_contents():
    pass


@pytest.mark.skip(reason=(
    "Same rationale as test_mn7_fingerprint_table_contents — mn6_fp "
    "is implementation detail; the sweep is authoritative."
))
def test_mn6_fingerprint_table_contents():
    pass


@pytest.mark.skip(reason=(
    "mn*_hash_t (T perturbation table) is implementation detail, not "
    "contract.  The 27-byte T table drives the hash formula "
    "`h = (c1*C1 + c3*C3 + T[c2]) & mask`; if any T byte were wrong, "
    "the corresponding letter-triple hashes would miss and the full "
    "sweep would catch it as a mismatch against the Python reference. "
    "Pinning T bytes would couple this test to the current generator "
    "choice — redundant with the sweep and brittle under regeneration."
))
def test_mn7_hash_t_contents():
    pass


@pytest.mark.skip(reason=(
    "Same rationale — mn6_hash_t is implementation detail, subsumed "
    "by test_mn6_full_sweep."
))
def test_mn6_hash_t_contents():
    pass


# ⚠  LOW-RISK L1 GAP (per coverage audit 2026-04-20):
#    The mn6 bundle must be built with `-D USE_MN6` (see
#    conftest._mn_build).  If a future maintainer copies the bundle
#    pattern for a new mn variant and forgets the flag, the new
#    "mn6-style" bundle would silently link against mn7 tables and
#    produce an mn7-build disguised as mn6.  This is a HARNESS
#    concern, not a contract gap in the assembly itself.
#
#    Current mitigation (load-bearing!): test_mn6_full_sweep asserts
#    exactly 72 carry=0 results (56 legal + 16 known FPs); a
#    silently-mn7 mn6 bundle would return 114 carry=0 results and
#    the count assertion would fail with a clear "Expected 72, got
#    114" message.  Keep that assertion — it's the guard against
#    this entire class of harness bug.


@pytest.mark.skip(reason=(
    "USE_MN6 build-flag propagation (harness-level, not module "
    "contract): no dedicated test — conftest passes -D USE_MN6 to "
    "ca65 for the mn6 variant, and test_mn6_full_sweep's count "
    "assertion (Expected 72 carry=0) is the de-facto guard.  A "
    "dedicated test that linked both bundles and verified "
    "`mn6_classify('WAI')` rejects (CMOS-only, not in mn6's 56) "
    "while `mn7_classify('WAI')` accepts would be a tighter guard. "
    "Not implemented because the count mismatch is reliable and "
    "this gap is low-probability (requires a future new-bundle "
    "mistake, not an existing regression vector)."
))
def test_use_mn6_flag_propagates():
    pass


# ─── Dispatcher forwarding (mn_classify → mn*_classify) ──────────────────────

def _pick_sample_mnemonic(cls):
    """Return a (mne, c1, c2, c3) sample drawn from the slot map."""
    slot_mne = cls.build_slot_map()
    # Prefer a stable legal mnemonic if present; otherwise pick the first.
    for mne in ('LDA', 'STA', 'JMP', 'NOP'):
        if mne in slot_mne.values():
            break
    else:
        mne = next(iter(slot_mne.values()))
    from instruction_set import sc
    return mne, sc(mne[0]), sc(mne[1]), sc(mne[2])


class TestDispatcherForwarding:
    """mn_classify forwards to mn*_classify per build-time USE_MN6 flag.
    Result must be identical to calling the underlying classifier directly.
    """

    def _compare(self, cls, syms):
        cpu = MPU()
        mem = cpu.memory
        syms.load_into(mem)
        slot_mne = cls.build_slot_map()
        for slot, mne in slot_mne.items():
            from instruction_set import sc
            c1, c2, c3 = sc(mne[0]), sc(mne[1]), sc(mne[2])
            c_direct, slot_direct = _run_once(cpu, mem, syms, c1, c2, c3,
                                              syms.classify)
            c_disp, slot_disp = _run_once(cpu, mem, syms, c1, c2, c3,
                                          syms.mn_classify)
            assert c_direct == c_disp == 0, f"{mne}: carry mismatch"
            assert slot_direct == slot_disp == slot, \
                f"{mne}: direct slot {slot_direct} / dispatched slot " \
                f"{slot_disp} / expected {slot}"

    def test_mn7_dispatcher(self, mn7_syms):
        self._compare(mn7, mn7_syms)

    def test_mn6_dispatcher(self, mn6_syms):
        self._compare(mn6, mn6_syms)

    def test_rejection_forwards(self, mn7_syms):
        """Rejection (carry=1) also forwards identically."""
        cpu = MPU()
        mem = cpu.memory
        mn7_syms.load_into(mem)
        # "XXX" is guaranteed not to be a valid mnemonic.
        from instruction_set import sc
        c1, c2, c3 = sc('X'), sc('X'), sc('X')
        c_direct, _ = _run_once(cpu, mem, mn7_syms, c1, c2, c3,
                                mn7_syms.classify)
        c_disp, _ = _run_once(cpu, mem, mn7_syms, c1, c2, c3,
                              mn7_syms.mn_classify)
        assert c_direct == c_disp == 1, \
            f"rejection should forward: direct={c_direct} disp={c_disp}"


# ─── Y-clobber contract ──────────────────────────────────────────────────────

class TestYClobber:
    """Doc: 'Both classifiers clobber Y.  Caller must ldy #0 after the call
    if Y is needed.'  Verify Y does in fact change across the call."""

    def test_mn7_clobbers_y(self, mn7_syms):
        cpu = MPU()
        mem = cpu.memory
        mn7_syms.load_into(mem)
        from instruction_set import sc
        cpu.y = 0x5A
        _run_once(cpu, mem, mn7_syms, sc('L'), sc('D'), sc('A'),
                  mn7_syms.classify)
        assert cpu.y != 0x5A, \
            "mn7_classify is documented as clobbering Y; Y was preserved"

    def test_mn6_clobbers_y(self, mn6_syms):
        cpu = MPU()
        mem = cpu.memory
        mn6_syms.load_into(mem)
        from instruction_set import sc
        cpu.y = 0x33
        _run_once(cpu, mem, mn6_syms, sc('L'), sc('D'), sc('A'),
                  mn6_syms.classify)
        assert cpu.y != 0x33


# ─── Encoding-agnostic input ─────────────────────────────────────────────────
#
# mn_classify.md guarantees that the three common encodings of the same
# letter collapse to identical 1–26 values under `AND #$1F`:
#   PETSCII uppercase   $C1–$DA  (ca65 '-t c64' char literals, GETIN)
#   PETSCII lowercase   $41–$5A
#   VICII screen codes  $01–$1A  (already 1–26)
#
# The property is a numeric fact of the AND mask, but the test also
# runs the classifier on each normalised value to show the classifier
# behaves identically — the documented "encoding-agnostic" contract.


class TestEncodingAgnostic:
    def test_and_mask_collapses_three_encodings(self):
        """For each letter, PETSCII-upper, PETSCII-lower, and screencode
        all mask to the same 1–26 value."""
        for letter in range(26):
            pet_upper = 0xC1 + letter     # $C1 = 'A' (shifted PETSCII)
            pet_lower = 0x41 + letter     # $41 = 'a' (PETSCII)
            screencode = 0x01 + letter    # $01 = A (screen)
            assert pet_upper & 0x1F == letter + 1
            assert pet_lower & 0x1F == letter + 1
            assert screencode & 0x1F == letter + 1

    def test_classifier_same_result_across_encodings(self, mn7_syms):
        """Classifier output is identical whether c1/c2/c3 were produced
        by `AND #$1F` on a PETSCII-upper, PETSCII-lower, or screencode
        byte.  (Trivially true since they produce the same 1–26 value,
        but the end-to-end check is what matters for the contract.)"""
        cpu = MPU()
        mem = cpu.memory
        mn7_syms.load_into(mem)
        from instruction_set import sc

        mne = 'LDA'
        enc_upper  = [(0xC0 + ord(c.upper()) - 64) & 0x1F for c in mne]
        enc_lower  = [(0x40 + ord(c.upper()) - 64) & 0x1F for c in mne]
        enc_screen = [(0x00 + ord(c.upper()) - 64) & 0x1F for c in mne]
        want       = [sc(c) for c in mne]

        assert enc_upper == want == enc_lower == enc_screen

        # Classifier result must be the same for each normalised triple.
        results = []
        for (c1, c2, c3) in (enc_upper, enc_lower, enc_screen):
            carry, slot = _run_once(cpu, mem, mn7_syms, c1, c2, c3,
                                    mn7_syms.classify)
            results.append((carry, slot))
        assert results[0] == results[1] == results[2], \
            f"encoding-dependent result: {results}"
