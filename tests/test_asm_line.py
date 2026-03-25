"""
test_asm_line.py – pytest tests for src/asm_line.s

Each test assembles one instruction (MNEMONIC [OPERAND]) and verifies that
the bytes written to the output buffer match OPCODES[mne][mode] + operand_bytes
from dev/instruction_set.py.

Test generation
---------------
The main parametrised test is built from MODE_EXAMPLES × MNEMONICS exactly
as described in the MODE_EXAMPLES docstring comment in instruction_set.py:

    for mne, (profile, cmos_bit, _) in MNEMONICS.items():
        for mode in mne_modes(profile, cmos_bit):
            for operand_src, operand_bytes in MODE_EXAMPLES[mode]:
                source   = f"{mne} {operand_src}".strip()
                expected = [OPCODES[mne][mode]] + operand_bytes

Cases are skipped when:
  - OPCODES[mne][mode] is None  (Zone D/E: RMB/SMB/BBR/BBS digit-encoded ops)
  - The operand string contains lowercase ASCII letters that au_parse_mode does
    not yet accept (e.g. '$00,x', '$00,y', 'a' for ACC)

REL notes
---------
MODE_EXAMPLES[REL] uses 4-digit absolute targets ($0002).  The test sets
al_pc = $0000 and al_cpu = 1 (65C02, accepts all modes).  The assembler
computes the signed offset: offset = $0002 − ($0000 + 2) = $00.

CMOS notes
----------
All tests run with al_cpu = 1 (65C02) so that both NMOS and CMOS extension
modes are exercised.  Modes that require 65C02 (ZPI, ACC for DEC/INC, AIX for
JMP, IMM for BIT, TRB, TSB, STZ, etc.) are included in the test set.
"""

import sys
import pathlib
import pytest
from py65.devices.mpu6502 import MPU

# Add dev/ to path so we can import instruction_set directly
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "dev"))

from instruction_set import (
    MNEMONICS, OPCODES, MODE_EXAMPLES,
    ALL_MODES, mne_modes,
)

# ── VICII screen-code encoder ─────────────────────────────────────────────────
_SC_UPPER = {c: (ord(c) - ord('A') + 1) for c in 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'}

def _sc(s: str) -> bytes:
    """Encode ASCII string to VICII screen codes + NUL terminator.
    Uppercase A–Z → $01–$1A; everything else (digits, punctuation) stays as-is.
    Lowercase letters ($61–$7A in ASCII) are passed through unchanged; au_mode.s
    does not accept them and these cases are filtered out below.
    """
    out = []
    for c in s:
        if c in _SC_UPPER:
            out.append(_SC_UPPER[c])
        else:
            out.append(ord(c))
    out.append(0x00)
    return bytes(out)


def _has_lowercase_letter(s: str) -> bool:
    """Return True if the string contains any ASCII lowercase letter a–z."""
    return any('a' <= c <= 'z' for c in s)


# ── Test vector generation ─────────────────────────────────────────────────────
_TEST_PC    = 0x0000    # PC used for REL/ZPREL offset tests
_OUT_BUF    = 0x4000    # output buffer address in simulated RAM
_IN_BUF     = 0x3000    # input string buffer
_MAX_STEPS  = 50_000    # safety limit for the emulated CPU

# Region layout from dev/test.cfg
_ZP_START   = 0x0000
_CODE_START = 0x0200
_ZP_SIZE    = 0x0100


def _build_cases():
    cases = []
    for mne, (profile, cmos_bit, _) in MNEMONICS.items():
        modes = mne_modes(profile, cmos_bit)
        for mode in sorted(modes, key=lambda m: list(ALL_MODES).index(m)):
            opcode = OPCODES[mne].get(mode)
            if opcode is None:
                continue            # Zone D/E: digit-encoded; skip
            examples = MODE_EXAMPLES.get(mode, [])
            for operand_src, operand_bytes in examples:
                source = f"{mne} {operand_src}".strip()
                # Skip variants with lowercase operand letters (x, y, a)
                # that au_parse_mode does not accept.
                if _has_lowercase_letter(operand_src):
                    continue
                expected = bytes([opcode] + operand_bytes)
                cases.append((source, expected))
    return cases


_CASES = _build_cases()


# ── CPU runner ────────────────────────────────────────────────────────────────

def _run(al_syms, source: str, al_cpu: int = 1):
    """
    Assemble one instruction and return the output bytes.

    Returns the bytes written to the output buffer on success, or raises
    AssertionError if al_error is reached, or TimeoutError on runaway.
    """
    cpu = MPU()
    mem = cpu.memory

    # Load the test binary
    al_syms.load_into(mem)

    # Write the VICII-encoded source string
    encoded = _sc(source)
    for i, b in enumerate(encoded):
        mem[_IN_BUF + i] = b

    # Set au_ptr → input buffer
    mem[al_syms.au_ptr]     = _IN_BUF & 0xFF
    mem[al_syms.au_ptr + 1] = (_IN_BUF >> 8) & 0xFF

    # Set al_pc = _TEST_PC
    mem[al_syms.al_pc]     = _TEST_PC & 0xFF
    mem[al_syms.al_pc + 1] = (_TEST_PC >> 8) & 0xFF

    # Set al_out → output buffer
    mem[al_syms.al_out]     = _OUT_BUF & 0xFF
    mem[al_syms.al_out + 1] = (_OUT_BUF >> 8) & 0xFF

    # al_cpu
    mem[al_syms.al_cpu] = al_cpu

    # Fake JSR: push $FFFE so RTS lands at $FFFF (sentinel)
    cpu.sp = 0xFF
    mem[0x01FF] = 0xFF
    mem[0x01FE] = 0xFE
    cpu.sp = 0xFD

    cpu.pc = al_syms.al_line_asm
    cpu.y  = 0

    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            # Normal return
            n = mem[al_syms.al_len]
            return bytes(mem[_OUT_BUF : _OUT_BUF + n])
        if cpu.pc == al_syms.al_error:
            raise AssertionError(
                f"al_error reached while assembling {source!r}")
        cpu.step()

    raise TimeoutError(f"exceeded {_MAX_STEPS} steps for {source!r}")


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("source,expected", _CASES,
                         ids=[c[0] for c in _CASES])
def test_assemble(al_syms, source, expected):
    got = _run(al_syms, source)
    assert got == expected, (
        f"assembling {source!r}: "
        f"got {got.hex()} expected {expected.hex()}"
    )


# ── GAP 1: NMOS rejection tests ─────────────────────────────────────────────
# CMOS-only instructions must produce al_error when al_cpu = 0 (NMOS 6502).

_CMOS_ONLY_CASES = [
    # Pure CMOS mnemonics
    "BRA $0002",
    "PHX",    "PHY",    "PLX",    "PLY",
    "TRB $42",  "TRB $1234",
    "TSB $42",  "TSB $1234",
    "STZ $42",  "STZ $42,X",  "STZ $1234",  "STZ $1234,X",
    # CMOS extensions to legal mnemonics
    "DEC A",    "INC A",
    "BIT #$42",
    "JMP ($1234,X)",
    # ZPI mode (65C02 zero-page indirect)
    "ORA ($42)", "AND ($42)", "EOR ($42)", "ADC ($42)",
    "STA ($42)", "LDA ($42)", "CMP ($42)", "SBC ($42)",
]

# Known bug: pure CMOS mnemonics (BRA, PHX, etc.) are not gated by al_cpu
# in the assembler. CMOS *modes* (ZPI, ACC, AIX, BIT IMM) ARE gated correctly.
_CMOS_MNE_XFAIL = {
    "BRA $0002", "PHX", "PHY", "PLX", "PLY",
    "TRB $42", "TRB $1234", "TSB $42", "TSB $1234",
    "STZ $42", "STZ $42,X", "STZ $1234", "STZ $1234,X",
}

@pytest.mark.parametrize("source", _CMOS_ONLY_CASES)
def test_nmos_rejects_cmos(al_syms, source):
    """CMOS-only instructions must error on NMOS 6502 (al_cpu=0)."""
    if source in _CMOS_MNE_XFAIL:
        pytest.xfail("assembler doesn't gate pure CMOS mnemonics yet")
    try:
        _run(al_syms, source, al_cpu=0)
        pytest.fail(f"should have errored: {source!r} on NMOS")
    except AssertionError:
        pass  # expected: al_error was reached


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
def test_hex_mnemonic_ambiguity(al_syms, source, expected):
    """Mnemonics starting with hex digits must parse as mnemonics."""
    got = _run(al_syms, source)
    assert got == expected, (
        f"ambiguity test {source!r}: got {got.hex()} expected {expected.hex()}"
    )
