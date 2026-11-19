"""test_asm_m65.py — the line assembler on the m65 set (P4 T5).

Owner: doc/modules/asm_line.md

Contract source: [asm_line.md § Mnemonic word](../../doc/modules/asm_line.md#mnemonic-word),
[§ asm_cpu × category gate matrix](../../doc/modules/asm_line.md#asm_cpu--category-gate-matrix),
[§ Branches](../../doc/modules/asm_line.md#branches-zone-b),
[§ Prefixes](../../doc/modules/asm_line.md#prefixes-45gs02),
[§ IMM16 promotion](../../doc/modules/asm_line.md#imm16-promotion-mega_support);
[addr_mode.md § Design](../../doc/modules/addr_mode.md#design) (the m65 forms).

The m65-45gs02 asm_core bundle on M65Emu (asm_dasm_runner's m65 path,
clean mode).  The oracle is dev/instruction_set.py: every row of the
6502, 65C02, 4510 and 45GS02 views — prefixed rows too — assembled at
its CPU gives the row's bytes.  Then the rules a sweep of valid rows
cannot show: the gate matrix cell by cell (the 65C02 row by mn7_c02),
the suffixes, the Z rule, the far and stack-relative forms, IMM16,
the branch width with the width request, and the $FFFF edge.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import instruction_set as I                      # noqa: E402

import asm_dasm_runner as R                      # noqa: E402
from conftest import AsmCoreSymbols              # noqa: E402

SYNTAX, EXPR, CPU = R.SYNTAX, R.EXPR, R.CPU
CPUS = {v: R.MT.ASM_CPU[v] for v in ("6502", "65c02", "4510", "45gs02")}

# An operand per mode and its bytes at asm_pc = 0 (asm_dasm_runner.ASM_PC).
OPERAND = {
    "IMP": ("", []), "ACC": ("", []), "IMM": ("#$12", [0x12]),
    "ZP": ("$12", [0x12]), "ZPX": ("$12,X", [0x12]), "ZPY": ("$12,Y", [0x12]),
    "ABS": ("$1234", [0x34, 0x12]), "ABX": ("$1234,X", [0x34, 0x12]),
    "ABY": ("$1234,Y", [0x34, 0x12]), "IND": ("($1234)", [0x34, 0x12]),
    "INX": ("($12,X)", [0x12]), "INY": ("($12),Y", [0x12]),
    "REL": ("$0012", [0x10]), "ZPI": ("($12)", [0x12]),
    "AIX": ("($1234,X)", [0x34, 0x12]), "ZPREL": ("$12,$0013", [0x12, 0x10]),
    "IMM16": ("#$1234", [0x34, 0x12]), "REL16": ("$1234", [0x32, 0x12]),
    "ISPY": ("($12,SP),Y", [0x12]), "ZPIZ": ("($12),Z", [0x12]),
}
FAR = {"ZPI": "[$12]", "ZPIZ": "[$12],Z"}


@pytest.fixture(scope="module")
def syms():
    return AsmCoreSymbols("45gs02")


def asm(syms, source, cpu=4, **kw):
    return R.asm_result(syms, source, cpu, **kw)


def _rows(view):
    out = []
    for r in I.instructions(view):
        src, opr = OPERAND[r.mode]
        if I.PREFIX_FAR in r.prefix:
            src = FAR[r.mode]
        out.append((f"{r.mnemonic} {src}".strip(), bytes(r.prefix) + bytes([r.opcode] + opr)))
    return out


@pytest.mark.parametrize("view", list(CPUS))
def test_every_row_assembles_at_its_cpu(syms, view):
    bad = [(src, want.hex(), asm(syms, src, CPUS[view]))
           for src, want in _rows(view) if asm(syms, src, CPUS[view]) != want]
    assert not bad, bad[:10]


@pytest.mark.parametrize("lower,upper", [("6502", "65c02"), ("65c02", "4510"),
                                         ("6502", "4510"), ("4510", "45gs02")])
def test_a_row_the_lower_cpu_lacks_is_refused_there(syms, lower, upper):
    """Every source of the upper view that the lower view has no row for
    is refused at the lower CPU (;?cpu or ;?syntax), not assembled."""
    have = {src for src, _ in _rows(lower)}
    bad = [(src, got) for src, _ in _rows(upper) if src not in have
           for got in [asm(syms, src, CPUS[lower])] if not isinstance(got, tuple)]
    assert not bad, bad[:10]


# ── the gate matrix, m65 table: one key per (cat, c02) cell ───────────────────

@pytest.mark.parametrize("source,want", [
    ("LDX #$12",     {0: "ok", 2: "ok", 3: "ok", 4: "ok"}),           # cat 00
    ("LDA ($12)",    {0: SYNTAX, 2: "ok", 3: SYNTAX, 4: SYNTAX}),     # cat 01, c02: ZPI on the 65C02 only
    ("LDA ($12),Z",  {0: SYNTAX, 2: SYNTAX, 3: "ok", 4: "ok"}),
    ("JSR ($1234)",  {0: SYNTAX, 2: SYNTAX, 3: "ok", 4: "ok"}),       # cat 01, no c02
    ("STX $1234,Y",  {0: SYNTAX, 2: SYNTAX, 3: "ok", 4: "ok"}),
    ("LDQ $12",      {0: CPU, 2: CPU, 3: CPU, 4: "ok"}),              # cat 10
    ("STZ $12",      {0: CPU, 2: "ok", 3: "ok", 4: "ok"}),            # cat 11, c02
    ("TAZ",          {0: CPU, 2: CPU, 3: "ok", 4: "ok"}),             # cat 11, no c02
])
def test_gate_matrix(syms, source, want):
    for cpu, w in want.items():
        got = asm(syms, source, cpu)
        assert (got if isinstance(got, tuple) else "ok") == (w if w == "ok" else ("E", w)), cpu


# ── the mnemonic word ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("source,cpu,want", [
    ("ADCQ $12", 4, b"\x42\x42\x65\x12"),
    ("ADCQ $12", 3, ("E", CPU)), ("ADCQ $12", 2, ("E", CPU)), ("ADCQ $12", 0, ("E", CPU)),
    ("LDXQ $12", 4, ("E", SYNTAX)),         # no Q form
    ("LDQQ $12", 4, ("E", SYNTAX)),         # a Q name takes no suffix
    ("STAQ $1234", 4, b"\x42\x42\x8d\x34\x12"),
    ("STQ $1234", 4, b"\x42\x42\x8d\x34\x12"),
    ("NOP", 4, b"\xea"), ("EOM", 4, b"\xea"), ("NOP", 0, b"\xea"),
    ("ASLQ", 4, b"\x42\x42\x0a"),           # bare is the accumulator
    ("ADCQX $12", 4, ("E", SYNTAX)),
])
def test_mnemonic_word(syms, source, cpu, want):
    assert asm(syms, source, cpu) == want


# ── the Z rule, far, stack-relative ───────────────────────────────────────────

@pytest.mark.parametrize("source,cpu,want", [
    ("LDA ($12)", 4, ("E", SYNTAX)),        # Z is added: (e) misstates the CPU
    ("ADCQ ($12),Z", 4, ("E", SYNTAX)),     # the Q form adds no Z
    ("ADCQ ($12)", 4, b"\x42\x42\x72\x12"),
    ("LDQ ($12)", 4, ("E", SYNTAX)), ("LDQ ($12),Z", 4, b"\x42\x42\xb2\x12"),
    ("LDA [$12],Z", 4, b"\xea\xb2\x12"),
    ("LDA [$12],Z", 3, ("E", CPU)), ("LDA [$12],Z", 2, ("E", CPU)),
    ("LDQ [$12],Z", 4, b"\x42\x42\xea\xb2\x12"),   # the order: $42 $42, $EA, opcode
    ("LDA [$1234],Z", 4, ("E", SYNTAX)),    # narrow only
    ("LDA [$12],Y", 4, ("E", SYNTAX)),
    ("LDA ($12,SP),Y", 4, b"\xe2\x12"), ("LDA ($12,S),Y", 4, b"\xe2\x12"),
    ("LDA ($12,SP),Y", 2, ("E", CPU)),
    ("LDA ($1234),Z", 4, ("E", SYNTAX)),
])
def test_indirect_forms(syms, source, cpu, want):
    assert asm(syms, source, cpu) == want


def test_imm16_promotion(syms):
    assert asm(syms, "PHW #$1234") == b"\xf4\x34\x12"
    assert asm(syms, "LDA #$1234") == ("E", EXPR)     # IMM stays a byte


# ── branch width (asm_line.md § Branches) ─────────────────────────────────────

@pytest.mark.parametrize("source,cpu,want", [
    ("BNE $0081", 4, b"\xd0\x7f"),          # in reach: REL
    ("BNE $0082", 4, b"\xd3\x80\x00"),      # out of reach: REL16
    ("BNE $0082", 2, ("E", SYNTAX)),        # the 65C02 has no REL16
    ("BRA $0010", 4, b"\x80\x0e"), ("BRA $1000", 4, b"\x83\xfe\x0f"),
    ("BSR $0010", 4, b"\x63\x0e\x00"),      # REL16 only
    ("BBS7 $12,$0010", 4, b"\xff\x12\x0d"),
])
def test_branch_width(syms, source, cpu, want):
    assert asm(syms, source, cpu) == want


def test_a_forward_target_takes_rel(syms):
    """Pass 0, an undefined target: expr_fwd set, REL (pass-stable)."""
    assert asm(syms, "BNE LATER", 4, asm_pass=0) == b"\xd0\x00"


def test_the_width_request_takes_rel16_and_is_cleared(syms):
    got, err, _, m = R.run_asm(syms, "BNE $0010", 4, rel16=True, keep=True)
    assert got == b"\xd3\x0e\x00"
    assert m.peek(syms.asm_rel16)[0] == 0
    assert asm(syms, "BNE $0010", 2, rel16=True) == b"\xd0\x0e"     # 65C02: REL
    assert asm(syms, "LDA #$01", 4, rel16=True) == b"\xa9\x01"      # no branch


# ── the $FFFF edge: a 5-byte instruction ──────────────────────────────────────

def test_five_bytes_ending_at_ffff_are_accepted(syms):
    got, err, _ = R.run_asm(syms, "LDQ [$12],Z", 4, pc=0xFFFB, out=0xFFFB)
    assert (got, err) == (b"\x42\x42\xea\xb2\x12", 0)


def test_one_byte_more_is_refused_and_writes_nothing_at_0(syms):
    got, err, _, m = R.run_asm(syms, "LDQ [$12],Z", 4, pc=0xFFFC, out=0xFFFC, keep=True)
    assert err == EXPR
    assert [m.mem.read_flat(k) for k in (0, 1)] == [0, 0]
