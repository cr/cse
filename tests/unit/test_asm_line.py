"""test_asm_line.py — Tier-U unit tests for asm_line.s.

Contract source: [doc/modules/asm_line.md](../../doc/modules/asm_line.md).

Coverage of the documented contract
-----------------------------------
5 exported items:

  asm_line                  — test_assemble (~1260 parametrised cases
                               across MNEMONICS × MODE_EXAMPLES);
                               test_hex_mnemonic_ambiguity (7 cases)
  _asm_line_core            — exercised by test_assemble
  reg_a / reg_x / reg_y /
  reg_sp / reg_p (BSS)      — TestRegShadows (addressability +
                               distinctness + writability)

CPU-mode gate (asm_cpu × category matrix — see asm_line.md):
  TestCpuGateCmosBundle  — -DCMOS_SUPPORT build (matches 65C02 prod)
  TestCpuGate6510Bundle  — no-CMOS_SUPPORT build (matches 6510 prod,
                            the config where the CMOS-accept bug lived)
  TestAsmLine6502Bundle  — -DUSE_MN6 build (matches 6502 prod;
                            mn6 rejects CMOS/illegals at classify tier)

Adjacent modules in this bundle (their own test files):
  opcode_lookup.s → tests/unit/test_opcode_lookup.py (asm_validate_mode)
  addr_mode.s     → tests/unit/test_addr_mode.py (mode_parse, asm_skip_ws)
  expr.s          → tests/unit/test_expr.py
  symtab.s + mem.s→ tests/unit/{test_symtab,test_mem}.py
asm_opcode_lookup's opcode-byte correctness is proven by the
exhaustive test_assemble sweep below (every MNEMONICS[mne][mode]
byte is checked), so test_opcode_lookup.py focuses on
asm_validate_mode's standalone predicate contract.

Test generation
---------------
The main parametrised test is built from MODE_EXAMPLES × MNEMONICS as
described in the MODE_EXAMPLES docstring in instruction_set.py:

    for mne, (profile, cmos_bit, category) in MNEMONICS.items():
        for mode in mne_modes(profile, cmos_bit):
            for operand_src, operand_bytes in MODE_EXAMPLES[mode]:
                source   = f"{mne} {operand_src}".strip()
                expected = [OPCODES[mne][mode]] + operand_bytes

Cases are skipped when OPCODES[mne][mode] is None (Zone D/E
digit-encoded ops) or the operand uses lowercase forms mode_parse
doesn't accept.

asm_cpu selection: asm_cpu=1 for illegals, asm_cpu=2 for legal + CMOS.
Post-Escape-Analysis gate change — the gate now rejects illegals on
asm_cpu != 1 and CMOS on asm_cpu < 2, so the parametric sweep must
pick the right asm_cpu per category.
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

    Raises AssertionError if asm_error is reached, TimeoutError on runaway.
    """
    from conftest import make_cpu, push_rts_sentinel, step_until_pc

    cpu, mem = make_cpu(asm_syms)

    # PETSCII source → input buffer; point asm_ptr at it
    for i, b in enumerate(_sc(source)):
        mem[_IN_BUF + i] = b
    mem[asm_syms.asm_ptr]     = _IN_BUF & 0xFF
    mem[asm_syms.asm_ptr + 1] = (_IN_BUF >> 8) & 0xFF

    mem[asm_syms.asm_pc]      = _TEST_PC & 0xFF
    mem[asm_syms.asm_pc + 1]  = (_TEST_PC >> 8) & 0xFF
    mem[asm_syms.asm_out]     = _OUT_BUF & 0xFF
    mem[asm_syms.asm_out + 1] = (_OUT_BUF >> 8) & 0xFF
    mem[asm_syms.asm_cpu]     = asm_cpu

    sentinel = push_rts_sentinel(cpu, sentinel=0xFFFF)
    # asm_line's error path does `ldx _asm_saved_sp / txs / rts`,
    # so pre-seed _asm_saved_sp to match for symmetric success/error return.
    mem[asm_syms._asm_saved_sp] = cpu.sp

    cpu.pc = asm_syms._asm_line_core
    cpu.y  = 0
    step_until_pc(cpu, sentinel, max_steps=_MAX_STEPS, what=repr(source))

    n = mem[asm_syms.asm_len]
    if n == 0:
        raise AssertionError(f"asm_error reached while assembling {source!r}")
    return bytes(mem[_OUT_BUF : _OUT_BUF + n])


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


# asm_validate_mode and asm_skip_ws tests retired from this file.
# They now live with their owning modules per the one-file-per-module
# principle:
#   - TestAsmValidateMode  → tests/unit/test_opcode_lookup.py
#   - TestAsmSkipWs        → tests/unit/test_addr_mode.py


# ═════════════════════════════════════════════════════════════════════════
# ACC vs label disambiguation (addr_mode.md § ACC vs label disambiguation,
# asm_line.md § ACC mode handling)
# ═════════════════════════════════════════════════════════════════════════
#
# Six mnemonics accept ACC mode (profile 11): ASL, LSR, ROL, ROR (always);
# INC, DEC (CMOS only).  Per the contract:
#
#   - bare mnemonic         → ACC opcode (IMP→ACC promotion in zone G/H)
#   - explicit `<mne> A`    → ACC opcode (mode_parse SC_A path)
#   - `<mne> A` with `A` defined → ACC opcode + shadow flag set
#   - non-ACC profile + `A` → label resolution (the original bug class)
#
# These four cells together pin Principle 11's matrix for the ambiguity.


# ── helpers for the new test classes ──────────────────────────────────────

_NAME_BUF = 0x3500   # scratch buffer for symbol names (above _IN_BUF)


def _define_sym(asm_syms, mem, mpu, name, value, wide):
    """Define one symbol via sym_define.  Caller must have already cleared
    the table (sym_clear) at least once before the first call."""
    from conftest import push_rts_sentinel, step_until_pc
    enc = name.encode('ascii') + b'\x00'  # ASCII upper = PETSCII upper
    for i, b in enumerate(enc):
        mem[_NAME_BUF + i] = b
    mem[asm_syms.sym_name]     = _NAME_BUF & 0xFF
    mem[asm_syms.sym_name + 1] = (_NAME_BUF >> 8) & 0xFF
    mem[asm_syms.sym_val]      = value & 0xFF
    mem[asm_syms.sym_val + 1]  = (value >> 8) & 0xFF
    mem[asm_syms.sym_wide]     = wide
    push_rts_sentinel(mpu, sentinel=0xFFFE)
    mpu.pc = asm_syms.sym_define
    step_until_pc(mpu, 0xFFFE, max_steps=_MAX_STEPS, what=f"define {name}")


def _clear_syms(asm_syms, mem, mpu):
    from conftest import push_rts_sentinel, step_until_pc
    push_rts_sentinel(mpu, sentinel=0xFFFE)
    mpu.pc = asm_syms.sym_clear
    step_until_pc(mpu, 0xFFFE, max_steps=_MAX_STEPS, what="sym_clear")


def _run_with_pass(asm_syms, source, asm_cpu=2, asm_pass=1, syms=None):
    """Variant of _run that lets a test set asm_pass and pre-define symbols.

    Returns (output_bytes, warn_count) so callers can assert both the
    emitted bytes and whether the label-shadow warning was emitted.
    `warn_count` is the asm_core stub's `_warn_witness` byte
    (incremented on each `log_warn` call by the bundle's stub).
    """
    from conftest import make_cpu, push_rts_sentinel, step_until_pc

    cpu, mem = make_cpu(asm_syms)

    # Symbols, if requested.  sym_clear must run BEFORE asm_pass is set —
    # sym_clear writes to ZP/heap, unaffected by asm_pass; the pass byte
    # is only consulted by mode_parse.
    if syms:
        _clear_syms(asm_syms, mem, cpu)
        for name, (value, wide) in syms.items():
            _define_sym(asm_syms, mem, cpu, name, value, wide)

    mem[asm_syms.asm_pass]      = asm_pass
    mem[asm_syms._warn_witness] = 0   # reset stub log_warn counter

    for i, b in enumerate(_sc(source)):
        mem[_IN_BUF + i] = b
    mem[asm_syms.asm_ptr]     = _IN_BUF & 0xFF
    mem[asm_syms.asm_ptr + 1] = (_IN_BUF >> 8) & 0xFF

    mem[asm_syms.asm_pc]      = _TEST_PC & 0xFF
    mem[asm_syms.asm_pc + 1]  = (_TEST_PC >> 8) & 0xFF
    mem[asm_syms.asm_out]     = _OUT_BUF & 0xFF
    mem[asm_syms.asm_out + 1] = (_OUT_BUF >> 8) & 0xFF
    mem[asm_syms.asm_cpu]     = asm_cpu

    sentinel = push_rts_sentinel(cpu, sentinel=0xFFFF)
    mem[asm_syms._asm_saved_sp] = cpu.sp

    cpu.pc = asm_syms._asm_line_core
    cpu.y  = 0
    step_until_pc(cpu, sentinel, max_steps=_MAX_STEPS, what=repr(source))

    n = mem[asm_syms.asm_len]
    if n == 0:
        raise AssertionError(f"asm_error reached while assembling {source!r}")
    return (bytes(mem[_OUT_BUF : _OUT_BUF + n]),
            mem[asm_syms._warn_witness])


class TestAccBareForm:
    """Bare mnemonic = ACC for ACC-accepting profiles (profile 11).

    The IMP→ACC promotion in asm_line zone G/H produces the same opcode
    as the explicit `<mne> A` form.  Today (before the fix) bare forms
    fail with `;?bad insn` because mode_parse returns IMP and validate
    rejects (IMP not in profile 11's mode set).
    """

    # (source, expected_bytes, asm_cpu)
    NMOS_BARE_CASES = [
        ("ASL", bytes([0x0A]), 2),
        ("LSR", bytes([0x4A]), 2),
        ("ROL", bytes([0x2A]), 2),
        ("ROR", bytes([0x6A]), 2),
    ]
    CMOS_BARE_CASES = [
        ("INC", bytes([0x1A]), 2),
        ("DEC", bytes([0x3A]), 2),
    ]

    @pytest.mark.parametrize("source,expected,asm_cpu", NMOS_BARE_CASES,
                             ids=[c[0] for c in NMOS_BARE_CASES])
    def test_bare_nmos_shifts(self, asm_syms, source, expected, asm_cpu):
        got, _warn = _run_with_pass(asm_syms, source, asm_cpu=asm_cpu)
        assert got == expected

    @pytest.mark.parametrize("source,expected,asm_cpu", CMOS_BARE_CASES,
                             ids=[c[0] for c in CMOS_BARE_CASES])
    def test_bare_cmos_inc_dec(self, asm_syms, source, expected, asm_cpu):
        """CMOS-only bare INC/DEC promote to ACC.  On NMOS, the same
        bare forms must error (profile 10's mode set has no ACC and no
        IMP) — covered by `test_bare_inc_dec_rejected_on_nmos` below."""
        got, _warn = _run_with_pass(asm_syms, source, asm_cpu=asm_cpu)
        assert got == expected

    def test_bare_inc_dec_rejected_on_nmos(self, asm_syms):
        """Bare INC / DEC on asm_cpu < 2 (NMOS): profile 10 has neither
        IMP nor ACC, so the IMP→ACC promotion's mode-bit check fails
        and validate_mode then rejects.  This is the documented
        cmos-only nature of bare INC/DEC."""
        for source in ("INC", "DEC"):
            with pytest.raises(AssertionError):
                _run_with_pass(asm_syms, source, asm_cpu=0)


class TestSingleLetterLabelResolution:
    """Non-ACC profiles must accept single-letter `A` as a label.

    Before the fix: mode_parse classified bare `A` as MODE_ACC
    unconditionally; profiles that don't accept ACC (JMP, JSR, LDA,
    branches, …) then errored with `;?bad insn` even when the symbol
    `A` was defined.  This class is the original-bug regression
    witness for `a: jmp a` and the broader matrix of
    `<non-acc-mne> A`.
    """

    # (source, expected_bytes, asm_cpu)
    # Symbol A defined as $0042 (ZP) and B as $1234 (ABS) below.
    LABEL_CASES_ZP_A = [
        ("LDA A",       bytes([0xA5, 0x42]), 2),    # ZP load
        ("STA A",       bytes([0x85, 0x42]), 2),    # ZP store
        ("BIT A",       bytes([0x24, 0x42]), 2),    # BIT zp
        ("CMP A",       bytes([0xC5, 0x42]), 2),    # CMP zp
    ]
    LABEL_CASES_ABS_B = [
        ("JMP B",       bytes([0x4C, 0x34, 0x12]), 2),
        ("JSR B",       bytes([0x20, 0x34, 0x12]), 2),
        ("LDA B",       bytes([0xAD, 0x34, 0x12]), 2),
        ("STA B",       bytes([0x8D, 0x34, 0x12]), 2),
    ]

    @pytest.mark.parametrize("source,expected,asm_cpu", LABEL_CASES_ZP_A,
                             ids=[c[0] for c in LABEL_CASES_ZP_A])
    def test_zp_label_a(self, asm_syms, source, expected, asm_cpu):
        """`<non-acc-mne> A` resolves the symbol `A` at $0042 (ZP)."""
        syms = {"A": (0x0042, 0)}    # wide=0 → ZP-eligible
        got, _warn = _run_with_pass(asm_syms, source, asm_cpu=asm_cpu, syms=syms)
        assert got == expected

    @pytest.mark.parametrize("source,expected,asm_cpu", LABEL_CASES_ABS_B,
                             ids=[c[0] for c in LABEL_CASES_ABS_B])
    def test_abs_label_b(self, asm_syms, source, expected, asm_cpu):
        """`<non-acc-mne> B` resolves the symbol `B` at $1234 (ABS)."""
        syms = {"B": (0x1234, 1)}    # wide=1 → ABS
        got, _warn = _run_with_pass(asm_syms, source, asm_cpu=asm_cpu, syms=syms)
        assert got == expected

    def test_jmp_a_undefined_errors(self, asm_syms):
        """`JMP A` with no symbol defined → expr-undef error on pass 1.
        (Pass 0 substitutes asm_pc+2 for sizing per addr_mode.md §
        Forward-reference handling.)"""
        with pytest.raises(AssertionError):
            _run_with_pass(asm_syms, "JMP A", asm_cpu=2, asm_pass=1)


class TestAccLabelShadow:
    """When the explicit `<acc-mne> A` form runs against a defined
    label `A`, accumulator mode wins (textual disambiguation per the
    contract — see addr_mode.md § ACC vs label disambiguation).

    mode_parse emits `;!a shadow` directly via `log_warn` on pass 1.
    Under the asm_core test bundle, `log_warn` is stubbed to increment
    `_warn_witness` (see dev/asm_core_test_stub.s).  These tests pin
    both the opcode (ACC wins) and the warning emission count.
    """

    def test_asl_a_acc_wins_with_warning(self, asm_syms):
        syms = {"A": (0x1234, 1)}
        got, warn = _run_with_pass(asm_syms, "ASL A", asm_cpu=2, syms=syms)
        assert got == bytes([0x0A]), "ACC must win over the defined label"
        assert warn == 1, "log_warn must be called exactly once"

    def test_lsr_a_shadow(self, asm_syms):
        syms = {"A": (0x0042, 0)}
        got, warn = _run_with_pass(asm_syms, "LSR A", asm_cpu=2, syms=syms)
        assert got == bytes([0x4A])
        assert warn == 1

    def test_no_shadow_when_undefined(self, asm_syms):
        """`ASL A` with no symbol `A` defined: ACC wins (same opcode),
        no warning emitted."""
        got, warn = _run_with_pass(asm_syms, "ASL A", asm_cpu=2)
        assert got == bytes([0x0A])
        assert warn == 0

    def test_no_shadow_for_bare_form(self, asm_syms):
        """Bare `ASL` doesn't even consult symtab — the SC_A path is
        not entered.  No warning regardless of symbol definition."""
        syms = {"A": (0x1234, 1)}
        got, warn = _run_with_pass(asm_syms, "ASL", asm_cpu=2, syms=syms)
        assert got == bytes([0x0A])
        assert warn == 0

    def test_no_shadow_when_explicit_address(self, asm_syms):
        """`ASL $42` is unambiguous memory mode — no SC_A path, no
        warning, even if symbol `A` happens to be defined."""
        syms = {"A": (0x1234, 1)}
        got, warn = _run_with_pass(asm_syms, "ASL $42", asm_cpu=2, syms=syms)
        assert got == bytes([0x06, 0x42])
        assert warn == 0

    def test_pass_0_suppresses_warning(self, asm_syms):
        """Pass 0 (sizing) must not emit the warning — the source
        assembler runs two passes; we want exactly one warning per
        shadow site, emitted on pass 1."""
        syms = {"A": (0x1234, 1)}
        got, warn = _run_with_pass(asm_syms, "ASL A", asm_cpu=2,
                                   asm_pass=0, syms=syms)
        assert got == bytes([0x0A])
        assert warn == 0, "pass-0 must not emit shadow warning"

    def test_two_letter_label_no_shadow(self, asm_syms):
        """`ASL AB` is a label parse, not the SC_A peek-ahead — never
        triggers the shadow path."""
        syms = {"AB": (0x0050, 0)}
        got, warn = _run_with_pass(asm_syms, "ASL AB", asm_cpu=2, syms=syms)
        assert got == bytes([0x06, 0x50])
        assert warn == 0


class TestNoAccFlagSetByAsmLine:
    """asm_line.s writes `_au_no_acc` based on profile before
    mode_parse; mode_parse reads the flag in its SC_A branch.

    These tests exercise that handshake by leaving a "poison" value
    in `_au_no_acc` before the call and asserting asm_line overwrites
    it correctly.  This is what makes single-letter labels work for
    non-ACC profiles: the flag arrives nonzero so mode_parse falls
    through to label parse.
    """

    def test_flag_nonzero_for_non_acc_profile(self, asm_syms):
        """After assembling a non-ACC instruction, `_au_no_acc`
        should be nonzero (set by asm_line based on profile)."""
        from conftest import make_cpu, push_rts_sentinel, step_until_pc
        cpu, mem = make_cpu(asm_syms)
        for i, b in enumerate(_sc("LDA #$00")):
            mem[_IN_BUF + i] = b
        mem[asm_syms.asm_ptr]     = _IN_BUF & 0xFF
        mem[asm_syms.asm_ptr + 1] = (_IN_BUF >> 8) & 0xFF
        mem[asm_syms.asm_pc]      = 0
        mem[asm_syms.asm_pc + 1]  = 0
        mem[asm_syms.asm_out]     = _OUT_BUF & 0xFF
        mem[asm_syms.asm_out + 1] = (_OUT_BUF >> 8) & 0xFF
        mem[asm_syms.asm_cpu]     = 2
        mem[asm_syms._au_no_acc]  = 0   # poison
        sentinel = push_rts_sentinel(cpu, sentinel=0xFFFF)
        mem[asm_syms._asm_saved_sp] = cpu.sp
        cpu.pc = asm_syms._asm_line_core
        cpu.y  = 0
        step_until_pc(cpu, sentinel, max_steps=_MAX_STEPS, what="LDA #$00")
        # LDA profile (6) does not include ACC → flag must be nonzero
        assert mem[asm_syms._au_no_acc] != 0, \
            f"_au_no_acc=${mem[asm_syms._au_no_acc]:02X}; " \
            f"expected nonzero for LDA (profile 6, no ACC bit)"

    def test_flag_zero_for_acc_profile(self, asm_syms):
        """After assembling an ASL (profile 11), `_au_no_acc` should
        be zero — the profile accepts ACC."""
        from conftest import make_cpu, push_rts_sentinel, step_until_pc
        cpu, mem = make_cpu(asm_syms)
        for i, b in enumerate(_sc("ASL $42")):
            mem[_IN_BUF + i] = b
        mem[asm_syms.asm_ptr]     = _IN_BUF & 0xFF
        mem[asm_syms.asm_ptr + 1] = (_IN_BUF >> 8) & 0xFF
        mem[asm_syms.asm_pc]      = 0
        mem[asm_syms.asm_pc + 1]  = 0
        mem[asm_syms.asm_out]     = _OUT_BUF & 0xFF
        mem[asm_syms.asm_out + 1] = (_OUT_BUF >> 8) & 0xFF
        mem[asm_syms.asm_cpu]     = 2
        mem[asm_syms._au_no_acc]  = 0xFF   # poison
        sentinel = push_rts_sentinel(cpu, sentinel=0xFFFF)
        mem[asm_syms._asm_saved_sp] = cpu.sp
        cpu.pc = asm_syms._asm_line_core
        cpu.y  = 0
        step_until_pc(cpu, sentinel, max_steps=_MAX_STEPS, what="ASL $42")
        assert mem[asm_syms._au_no_acc] == 0, \
            f"_au_no_acc=${mem[asm_syms._au_no_acc]:02X}; " \
            f"expected 0 for ASL (profile 11, has ACC bit)"
