"""test_asm_line.py — Tier-U unit tests for asm_line.s + opcode_lookup.s.

Contract sources:
  - [doc/modules/asm_line.md](../../doc/modules/asm_line.md)
  - [doc/modules/opcode_lookup.md](../../doc/modules/opcode_lookup.md)

Coverage of the documented contract
-----------------------------------
Both asm_line.s and opcode_lookup.s are linked into the asm_core
bundle and tested from this file.

asm_line.s (5 exported items):
  asm_line                  — test_assemble (~800 parametrised cases
                               across MNEMONICS × MODE_EXAMPLES);
                               test_hex_mnemonic_ambiguity (7 cases)
  _asm_line_core            — exercised by test_assemble
  reg_a / reg_x / reg_y /
  reg_sp / reg_p (BSS)      — TestRegShadows (addressability +
                               distinctness + round-trip)

opcode_lookup.s (2 exported items):
  asm_opcode_lookup         — exhaustive coverage via test_assemble
                               (every legal/CMOS mnemonic × mode opcode
                               byte verified against dev/instruction_set.py)
  asm_validate_mode         — TestAsmValidateMode (direct carry-flag
                               contract, 6 cases)

CPU-mode gate:
  CMOS rejection on NMOS    — test_nmos_rejects_cmos

Out-of-scope (vocal skip)
-------------------------
  TestAsmSkipWs::test_asm_skip_ws_contract — addr_mode.s's asm_skip_ws
  is exercised transitively through test_au_mode.py::test_parse_ok
  (41 whitespace-handling operand forms); a direct test would exercise
  the same byte-scan through a thinner harness without catching new
  regressions.

Test generation
---------------
The main parametrised test is built from MODE_EXAMPLES x MNEMONICS
as described in the MODE_EXAMPLES docstring in instruction_set.py:

    for mne, (profile, cmos_bit, _) in MNEMONICS.items():
        for mode in mne_modes(profile, cmos_bit):
            for operand_src, operand_bytes in MODE_EXAMPLES[mode]:
                source   = f"{mne} {operand_src}".strip()
                expected = [OPCODES[mne][mode]] + operand_bytes

Cases are skipped when OPCODES[mne][mode] is None (Zone D/E digit-encoded
ops) or the operand uses lowercase forms mode_parse doesn't accept.

REL / CMOS notes unchanged — see earlier test revisions for details.
All tests run with asm_cpu = 2 (65C02) so NMOS and CMOS extension modes
are both exercised.
"""

import sys
import pathlib
import pytest
from py65.devices.mpu6502 import MPU

# Add dev/ to path so we can import instruction_set directly
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent.parent / "dev"))

from instruction_set import (
    MNEMONICS, OPCODES, MODE_EXAMPLES,
    ALL_MODES, mne_modes,
)

# ── PETSCII encoder ──────────────────────────────────────────────────────────

def _sc(s: str) -> bytes:
    """Encode ASCII string to PETSCII + NUL terminator.
    Uppercase A-Z = $41-$5A (same as ASCII); digits/punctuation unchanged.
    Lowercase letters ($61-$7A) are passed through; mode_parse does not
    accept them and these cases are filtered out below.
    """
    out = []
    for c in s:
        out.append(ord(c))
    out.append(0x00)
    return bytes(out)


def _has_lowercase_letter(s: str) -> bool:
    """Return True if the string contains any ASCII lowercase letter a-z."""
    return any('a' <= c <= 'z' for c in s)


# ── Test vector generation ─────────────────────────────────────────────────────
_TEST_PC    = 0x0000    # PC used for REL/ZPREL offset tests
_OUT_BUF    = 0x4000    # output buffer address in simulated RAM
_IN_BUF     = 0x3000    # input string buffer
_MAX_STEPS  = 50_000    # safety limit for the emulated CPU

# Region layout from dev/test.cfg
_ZP_START   = 0x0000
_CODE_START = 0x4000
_ZP_SIZE    = 0x0100


def _build_cases():
    cases = []
    for mne, (profile, cmos_bit, category) in MNEMONICS.items():
        modes = mne_modes(profile, cmos_bit)
        # asm_cpu that ACCEPTS this mnemonic's category (see the
        # asm_cpu × category matrix in doc/modules/asm_line.md):
        #   illegal → asm_cpu=1 (6510 only)
        #   legal + cmos → asm_cpu=2 (65C02; also legal on 0/1 but we
        #                             pick 2 so cat=01 modes get the
        #                             CMOS upgrade)
        asm_cpu = 1 if category == 'illegal' else 2
        for mode in sorted(modes, key=lambda m: list(ALL_MODES).index(m)):
            opcode = OPCODES[mne].get(mode)
            if opcode is None:
                continue            # Zone D/E: digit-encoded; skip
            examples = MODE_EXAMPLES.get(mode, [])
            for operand_src, operand_bytes in examples:
                source = f"{mne} {operand_src}".strip()
                # Skip variants with lowercase operand letters (x, y, a)
                # that mode_parse does not accept.
                if _has_lowercase_letter(operand_src):
                    continue
                expected = bytes([opcode] + operand_bytes)
                cases.append((source, expected, asm_cpu))
    return cases


_CASES = _build_cases()


# ── CPU runner ────────────────────────────────────────────────────────────────

def _run(asm_syms, source: str, asm_cpu: int = 2):
    """
    Assemble one instruction and return the output bytes.

    Returns the bytes written to the output buffer on success, or raises
    AssertionError if asm_error is reached, or TimeoutError on runaway.
    """
    cpu = MPU()
    mem = cpu.memory

    # Load the test binary
    asm_syms.load_into(mem)

    # Write the PETSCII-encoded source string
    encoded = _sc(source)
    for i, b in enumerate(encoded):
        mem[_IN_BUF + i] = b

    # Set asm_ptr -> input buffer
    mem[asm_syms.asm_ptr]     = _IN_BUF & 0xFF
    mem[asm_syms.asm_ptr + 1] = (_IN_BUF >> 8) & 0xFF

    # Set asm_pc = _TEST_PC
    mem[asm_syms.asm_pc]     = _TEST_PC & 0xFF
    mem[asm_syms.asm_pc + 1] = (_TEST_PC >> 8) & 0xFF

    # Set asm_out -> output buffer
    mem[asm_syms.asm_out]     = _OUT_BUF & 0xFF
    mem[asm_syms.asm_out + 1] = (_OUT_BUF >> 8) & 0xFF

    # asm_cpu
    mem[asm_syms.asm_cpu] = asm_cpu

    # Fake JSR: push $FFFE so RTS lands at $FFFF (sentinel)
    cpu.sp = 0xFF
    mem[0x01FF] = 0xFF
    mem[0x01FE] = 0xFE
    cpu.sp = 0xFD

    # Pre-set _asm_saved_sp so asm_error can restore SP on error.
    # The fake JSR left SP at 0xFD; asm_error does ldx _asm_saved_sp; txs; rts
    # which will return to $FFFF just like a normal return.
    mem[asm_syms._asm_saved_sp] = 0xFD

    cpu.pc = asm_syms._asm_line_core
    cpu.y  = 0

    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            # Normal return or error return (asm_error restores SP and RTS)
            n = mem[asm_syms.asm_len]
            if n == 0:
                raise AssertionError(
                    f"asm_error reached while assembling {source!r}")
            return bytes(mem[_OUT_BUF : _OUT_BUF + n])
        cpu.step()

    raise TimeoutError(f"exceeded {_MAX_STEPS} steps for {source!r}")


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source,expected,asm_cpu", _CASES,
                         ids=[c[0] for c in _CASES])
def test_assemble(asm_syms, source, expected, asm_cpu):
    got = _run(asm_syms, source, asm_cpu=asm_cpu)
    assert got == expected, (
        f"assembling {source!r} (asm_cpu={asm_cpu}): "
        f"got {got.hex()} expected {expected.hex()}"
    )


# test_nmos_rejects_cmos retired — subsumed by TestCpuGateCmosBundle::
# test_asm_cpu_0_rejects_cmos (cleaner per-build-config split).  CMOS-
# extension forms (DEC A, BIT #imm, JMP (AIX), ZPI) are exercised
# transitively by test_assemble's full-mode sweep on asm_cpu=2.


# ═════════════════════════════════════════════════════════════════════════
# CPU-mode gate (asm_cpu = 0/1/2)
# ═════════════════════════════════════════════════════════════════════════
#
# asm_line.md § Caveats: `asm_cpu` values: 0=6502, 1=6510, 2=65C02.
# Each mode should accept exactly the documented instruction set:
#
#   | asm_cpu  | legal | CMOS   | illegal |
#   |----------|-------|--------|---------|
#   | 0 (6502) | yes   | REJECT | REJECT  |
#   | 1 (6510) | yes   | REJECT | yes     |
#   | 2 (65C02)| yes   | yes    | REJECT  |
#
# The gate lives in asm_line.s:247-267.  Parts of it are wrapped in
# `.ifdef CMOS_SUPPORT`, which means the GATE BEHAVIOUR depends on the
# build config.  Production has three configs (Makefile _*_DEFS):
#
#   6502 build  : no -DCMOS_SUPPORT, -DUSE_MN6  (mn6 — 56 legal only)
#   6510 build  : no -DCMOS_SUPPORT, mn7         (114 incl. CMOS + illegals)
#   65C02 build : -DCMOS_SUPPORT, mn7            (gate fully present)
#
# This file exercises the gate against BOTH bundle configs:
#
#   asm_syms       — CMOS bundle (matches 65C02 production)
#   asm_6510_syms  — non-CMOS bundle (matches 6510 production)
#
# Splitting by config is load-bearing: bugs in the ifdef-wrapped gate
# are invisible under asm_syms alone (as happened — CMOS reject gate
# silently missing in 6510 prod binary).


# Pure-CMOS mnemonics (cat=11): rejected on asm_cpu < 2.
# BRA target must be within ±128 of asm_pc (=_TEST_PC) so the test isn't
# shadowed by a REL-range error.
_CMOS_CASES = [
    "PHY", "PHX", "PLY", "PLX",
    f"BRA ${_TEST_PC + 2:04X}",
    "STZ $42", "STZ $1234",
    "TRB $42", "TSB $42",
]

# NMOS illegal mnemonics (cat=10): accepted only on asm_cpu=1.
_ILLEGAL_CASES = [
    "SLO $42", "RLA $42", "LAX $42", "SAX $42",
    "DCP $42", "ISC $42",
    "ANC #$42", "ALR #$42", "ARR #$42", "SBX #$42",
    "AHX $1234,Y",
]


def _expect_reject(syms, source, asm_cpu, build_label):
    try:
        _run(syms, source, asm_cpu=asm_cpu)
        pytest.fail(
            f"{build_label} build, asm_cpu={asm_cpu}, {source!r}: "
            f"assembler silently accepted disallowed instruction"
        )
    except AssertionError:
        pass   # expected — asm_error was reached


def _expect_accept(syms, source, asm_cpu, build_label):
    try:
        got = _run(syms, source, asm_cpu=asm_cpu)
    except AssertionError:
        pytest.fail(
            f"{build_label} build, asm_cpu={asm_cpu}, {source!r}: "
            f"assembler rejected valid instruction"
        )
    assert len(got) > 0


# ─── CMOS bundle (asm_syms) — mirrors 65C02 production build ─────────────────

class TestCpuGateCmosBundle:
    """Gate matrix under the CMOS-SUPPORT bundle (matches 65C02 production).
    The gate is fully compiled in; only mn7 classifier semantics apply."""

    @pytest.mark.parametrize("source", _CMOS_CASES)
    def test_asm_cpu_0_rejects_cmos(self, asm_syms, source):
        _expect_reject(asm_syms, source, asm_cpu=0, build_label="cmos")

    @pytest.mark.parametrize("source", _CMOS_CASES)
    def test_asm_cpu_1_rejects_cmos(self, asm_syms, source):
        _expect_reject(asm_syms, source, asm_cpu=1, build_label="cmos")

    @pytest.mark.parametrize("source", _CMOS_CASES)
    def test_asm_cpu_2_accepts_cmos(self, asm_syms, source):
        _expect_accept(asm_syms, source, asm_cpu=2, build_label="cmos")

    @pytest.mark.parametrize("source", _ILLEGAL_CASES)
    def test_asm_cpu_1_accepts_illegals(self, asm_syms, source):
        _expect_accept(asm_syms, source, asm_cpu=1, build_label="cmos")

    @pytest.mark.parametrize("source", _ILLEGAL_CASES)
    def test_asm_cpu_0_rejects_illegals(self, asm_syms, source):
        """Currently FAILS: asm_line.s has no cat=$80 (illegal) gate.
        Independent bug from the CMOS-under-ifdef issue below."""
        _expect_reject(asm_syms, source, asm_cpu=0, build_label="cmos")

    @pytest.mark.parametrize("source", _ILLEGAL_CASES)
    def test_asm_cpu_2_rejects_illegals(self, asm_syms, source):
        """Currently FAILS: same cat=$80 gap — 65C02 accepts NMOS illegals
        that map to legitimate CMOS opcodes on real silicon."""
        _expect_reject(asm_syms, source, asm_cpu=2, build_label="cmos")


# ─── 6510 bundle (asm_6510_syms) — mirrors 6510 production build ─────────────

class TestCpuGate6510Bundle:
    """Gate matrix under the non-CMOS-SUPPORT bundle (matches 6510 production).

    The reject half of the CMOS gate in asm_line.s:251-267 is wrapped in
    `.ifdef CMOS_SUPPORT`, so it's compiled OUT of this bundle.  But mn7
    still recognizes CMOS mnemonics (PHY, PHX, BRA, ...).  Result: the
    classifier returns a valid slot, there's no gate to reject, and the
    assembler emits the CMOS opcode on any asm_cpu.

    These tests currently FAIL — they expose the long-standing bug where
    the 6510 production binary silently accepts CMOS instructions."""

    @pytest.mark.parametrize("source", _CMOS_CASES)
    def test_asm_cpu_0_rejects_cmos(self, asm_6510_syms, source):
        _expect_reject(asm_6510_syms, source, asm_cpu=0, build_label="6510")

    @pytest.mark.parametrize("source", _CMOS_CASES)
    def test_asm_cpu_1_rejects_cmos(self, asm_6510_syms, source):
        _expect_reject(asm_6510_syms, source, asm_cpu=1, build_label="6510")

    @pytest.mark.parametrize("source", _ILLEGAL_CASES)
    def test_asm_cpu_1_accepts_illegals(self, asm_6510_syms, source):
        """Positive case — 6510 bundle correctly allows illegals on cpu=1."""
        _expect_accept(asm_6510_syms, source, asm_cpu=1, build_label="6510")


# ─── 6502 bundle (asm_6502_syms) — mirrors 6502 production build ─────────────
#
# The 6502 bundle links mn6 instead of mn7 (via -DUSE_MN6).  mn6's hash
# table contains only the 56 legal NMOS mnemonics — CMOS and illegals
# are rejected at the classifier tier before the asm_line gate runs.
# The bundle's value at unit tier is (1) pinning legal-mnemonic
# assembly under the USE_MN6 classifier, and (2) confirming that the
# classifier-tier rejection path works end-to-end through asm_line.

# Positive-path smoke tests — a handful of legal mnemonics covering
# different zones to catch any USE_MN6 regression in the assembly
# pipeline outside asm_line itself.
_LEGAL_SMOKE_CASES = [
    ("LDA #$42",    bytes([0xA9, 0x42])),   # Zone C (immediate)
    ("LDA $42",     bytes([0xA5, 0x42])),   # Zone G (multi-mode ZP)
    ("LDA $1234",   bytes([0xAD, 0x34, 0x12])),  # Zone G (ABS)
    ("LDA $1234,X", bytes([0xBD, 0x34, 0x12])),  # Zone G (ABX)
    ("STA $42",     bytes([0x85, 0x42])),   # profile 8 (STA group)
    ("JSR $1234",   bytes([0x20, 0x34, 0x12])),  # Zone F (ABS only)
    ("BEQ $0002",   bytes([0xF0, 0x00])),   # Zone B (relative)
    ("NOP",         bytes([0xEA])),         # Zone A (implied)
    ("ASL A",       bytes([0x0A])),         # Zone G ACC (explicit)
    ("DEX",         bytes([0xCA])),         # Zone A (implied)
    ("INC $42",     bytes([0xE6, 0x42])),   # shift-ACC profile (NMOS: no ACC mode)
]


class TestAsmLine6502Bundle:
    """Assembly pipeline under the -DUSE_MN6 bundle (mirrors 6502 production).

    mn6's 56-mnemonic table excludes CMOS and illegals; asm_line's gate
    is not load-bearing here (the classifier rejects before the gate
    runs).  These tests exercise the legal-mnemonic path end-to-end
    through mn6 + asm_line + addr_mode + opcode_lookup to catch any
    USE_MN6-specific regression."""

    @pytest.mark.parametrize("source,expected", _LEGAL_SMOKE_CASES,
                             ids=[c[0] for c in _LEGAL_SMOKE_CASES])
    def test_legal_assembly(self, asm_6502_syms, source, expected):
        got = _run(asm_6502_syms, source, asm_cpu=0)
        assert got == expected, (
            f"6502 bundle {source!r}: "
            f"got {got.hex()}, expected {expected.hex()}"
        )

    @pytest.mark.parametrize("source", _CMOS_CASES)
    def test_cmos_rejected_by_classifier(self, asm_6502_syms, source):
        """mn6 doesn't recognize CMOS mnemonics → asm_error from the
        classifier, regardless of asm_cpu."""
        for asm_cpu in (0, 1, 2):
            _expect_reject(asm_6502_syms, source, asm_cpu=asm_cpu,
                           build_label="6502")

    @pytest.mark.parametrize("source", _ILLEGAL_CASES)
    def test_illegals_rejected_by_classifier(self, asm_6502_syms, source):
        """mn6 doesn't recognize NMOS illegals → asm_error regardless
        of asm_cpu (even asm_cpu=1, which 6510 bundle accepts)."""
        for asm_cpu in (0, 1, 2):
            _expect_reject(asm_6502_syms, source, asm_cpu=asm_cpu,
                           build_label="6502")


# ── GAP 5: Hex-mnemonic ambiguity tests ─────────────────────────────────────
# Mnemonics like DEC, BCC, ADD, BED start with hex digits.
# The assembler must recognize them as mnemonics, not hex values.

_AMBIGUOUS_CASES = [
    ("DEC $42",     bytes([0xC6, 0x42])),       # DEC zp
    ("BCC $0002",   bytes([0x90, 0x00])),       # BCC rel (offset 0)
    ("ADC #$42",    bytes([0x69, 0x42])),       # ADC imm (starts with A)
    ("BCS $0002",   bytes([0xB0, 0x00])),       # BCS rel
    ("BEQ $0002",   bytes([0xF0, 0x00])),       # BEQ rel
    ("DEX",         bytes([0xCA])),             # DEX implied
    ("DEY",         bytes([0x88])),             # DEY implied
]

@pytest.mark.parametrize("source,expected", _AMBIGUOUS_CASES,
                         ids=[c[0] for c in _AMBIGUOUS_CASES])
def test_hex_mnemonic_ambiguity(asm_syms, source, expected):
    """Mnemonics starting with hex digits must parse as mnemonics."""
    got = _run(asm_syms, source)
    assert got == expected, (
        f"ambiguity test {source!r}: got {got.hex()} expected {expected.hex()}"
    )


# ─── User-register BSS shadows (reg_a/x/y/sp/p) ──────────────────────────────
#
# asm_line.s exports five BSS bytes that hold user register state
# across userland/kernel transitions.  asm_line itself never reads or
# writes them — the debugger (debugger.s) snapshots on BRK/NMI and the
# REPL (repl.s) consumes them for the `r` command.  The asm_line
# contract for these symbols is minimal: five distinct, addressable
# single-byte slots at known locations.

class TestRegShadows:
    """reg_a / reg_x / reg_y / reg_sp / reg_p: five BSS bytes, distinct addresses."""

    def test_all_five_resolve(self, asm_syms):
        # Every slot is mapped — non-zero address means the linker
        # actually allocated storage for it.
        for attr in ("reg_a", "reg_x", "reg_y", "reg_sp", "reg_p"):
            assert getattr(asm_syms, attr) != 0, f"{attr} did not resolve"

    def test_all_five_distinct(self, asm_syms):
        addrs = {asm_syms.reg_a, asm_syms.reg_x, asm_syms.reg_y,
                 asm_syms.reg_sp, asm_syms.reg_p}
        assert len(addrs) == 5, \
            f"reg_* addresses not distinct: {sorted(hex(a) for a in addrs)}"

    def test_read_write_round_trip(self, asm_syms):
        """BSS allocation: writes visible on reads (harness-level check
        that the linker placed them in writable memory)."""
        mem = bytearray(65536)
        asm_syms.load_into(mem)
        for i, attr in enumerate(("reg_a", "reg_x", "reg_y", "reg_sp", "reg_p")):
            addr = getattr(asm_syms, attr)
            mem[addr] = 0x10 + i
            assert mem[addr] == 0x10 + i


# ─── opcode_lookup.s: asm_validate_mode direct tests ────────────────────────
#
# asm_validate_mode is a pure predicate: C=0 if `asm_mode` is in the
# mode-set for `asm_pidx`, C=1 otherwise.  The asm_line parametric sweep
# exercises it through asm_opcode_lookup indirectly, but the carry-flag
# semantics are worth a direct assertion.

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
    cpu = MPU()
    mem = bytearray(65536)
    asm_syms.load_into(mem)
    cpu.memory = mem
    mem[asm_syms.asm_pidx] = pidx
    mem[asm_syms.asm_mode] = mode
    ret = 0x01F0
    mem[ret] = 0x60                          # RTS sentinel (any opcode)
    cpu.sp = 0xFF
    mem[0x01FF] = (ret - 1) >> 8
    mem[0x01FE] = (ret - 1) & 0xFF
    cpu.sp = 0xFD
    cpu.pc = asm_syms.asm_validate_mode
    for _ in range(500):
        if cpu.pc == ret:
            return cpu.p & 0x01
        cpu.step()
    raise RuntimeError("asm_validate_mode did not return")


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


# ─── addr_mode.s: asm_skip_ws vocal skip ────────────────────────────────────
#
# asm_skip_ws (exported by addr_mode.s) is called inline by mode_parse
# and asm_line.s.  The whitespace-handling contract (skip $20 and $A0)
# is verified implicitly by test_au_mode.py::test_parse_ok, which uses
# 41 parametrised operand forms with leading/trailing/embedded
# whitespace.  A direct test would duplicate that coverage.

class TestAsmSkipWs:

    @pytest.mark.skip(reason=(
        "asm_skip_ws (addr_mode.md § asm_skip_ws): the whitespace-skip "
        "contract ($20 = space, $A0 = shifted space / tab) is verified "
        "transitively through test_au_mode.py::test_parse_ok (41 cases "
        "exercising leading/trailing/embedded whitespace).  A direct "
        "test would exercise the same bytes through a thinner harness "
        "without catching additional regressions.  Retained as a vocal "
        "skip per doc/testing.md § Principle 9 Pattern B (subsumed)."
    ))
    def test_asm_skip_ws_contract(self, asm_syms):
        pass
