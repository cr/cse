"""test_dasm_m65.py — the disassembler on the m65 set (P4 T7).

Owner: doc/modules/dasm.md

Contract source: [dasm.md § Design](../../doc/modules/dasm.md#design),
[§ Prefix peel](../../doc/modules/dasm.md#prefix-peel);
[asm_line.md § Mnemonic word](../../doc/modules/asm_line.md#mnemonic-word)
(the accepted spellings, *Listed by the disassembler as*).

The m65-45gs02 dasm bundle on M65Emu (asm_dasm_runner's m65 path, clean
mode).  The oracle is dev/instruction_set.py:
- every opcode at asm_cpu 0, 2, 3 and 4 lists as its view's row (the
  listing-name rule, `$EA` as `eom` in every view — D3 — the 65C02's
  (zp) as `($nn)`; an opcode outside the view as `...`, length 1);
- at asm_cpu 4 every prefixed row — Q, far, both — lists by its own
  mnemonic and spelling, with the prefixes in its length; below 4 no
  prefix is peeled;
- the formats: `#$1234`, a 16-bit branch target from the last byte,
  `,sp),y`, `),z`, `[ ]`, the bare accumulator;
- round trip: every row of the 45GS02 view assembled, listed, and
  assembled again gives the same bytes.
"""

import pytest

import asm_dasm_runner as R
from conftest import AsmCoreSymbols, dasm_bundle

I = R.I
CPUS = {"6502": 0, "65c02": 2, "4510": 3, "45gs02": 4}
AT = R.DASM_INSN_ADDR
OPR = list(R.DASM_OPERANDS)                     # $42 $34
RANK = {k: i for i, k in enumerate(list(I.OPCODES) + list(I.OPCODES_4510_ADDED))}


@pytest.fixture(scope="module")
def dsyms():
    return dasm_bundle("45gs02")


def operand(mode, b, at=AT, far=False):
    o, c = ("[", "]") if far else ("(", ")")
    b = list(b) + [0, 0]                       # every format is built below
    w = f"${b[1]:02X}{b[0]:02X}"
    z = f"${b[0]:02X}"
    sx = lambda v: v - 0x100 if v >= 0x80 else v
    return {
        "IMP": "", "ACC": "", "IMM": f"#{z}", "ZP": z, "ZPX": f"{z},X", "ZPY": f"{z},Y",
        "ABS": w, "ABX": f"{w},X", "ABY": f"{w},Y", "IND": f"({w})", "INX": f"({z},X)",
        "INY": f"({z}),Y", "ZPI": f"{o}{z}{c}", "AIX": f"({w},X)",
        "REL": f"${(at + 2 + sx(b[0])) & 0xFFFF:04X}",
        "ZPREL": f"{z},${(at + 3 + sx(b[1])) & 0xFFFF:04X}",
        "IMM16": f"#{w}", "REL16": f"${(at + 2 + (b[0] | b[1] << 8)) & 0xFFFF:04X}",
        "ISPY": f"({z},SP),Y", "ZPIZ": f"{o}{z}{c},Z",
    }[mode]


def view_rows(view):
    best = {}
    for r in I.instructions(view):
        if not r.prefix and (r.opcode not in best or RANK[r.key] >= RANK[best[r.opcode].key]):
            best[r.opcode] = r
    return best


def text(mne, mode, b, far=False):
    o = operand(mode, b, far=far)
    return f"{mne} {o}" if o else f"{mne} "


@pytest.mark.parametrize("view", list(CPUS))
def test_every_opcode_lists_as_its_view(dsyms, view):
    rows, cpu, bad = view_rows(view), CPUS[view], []
    for op in range(256):
        got = R.run_dasm(dsyms, cpu, [op, *OPR, 0, 0])[:2]
        r = rows.get(op)
        if r is None:
            want = ("... ", 1)
        else:
            mne = "EOM" if op == 0xEA else r.mnemonic
            want = (text(mne, r.mode, OPR), 1 + I.MODE_OPERAND_BYTES[r.mode])
        if got != want:
            bad.append((hex(op), got, want))
    assert not bad, bad[:10]


def _prefixed():
    for r in I.instructions("45gs02"):
        if r.prefix:
            n = I.MODE_OPERAND_BYTES[r.mode]
            b = [0x12, 0x34][:n]
            yield r, list(r.prefix) + [r.opcode] + b, b


def test_every_prefixed_row_lists_at_the_45gs02(dsyms):
    bad = []
    for r, raw, b in _prefixed():
        got = R.run_dasm(dsyms, 4, raw + [0] * (5 - len(raw)))[:2]
        want = (text(r.mnemonic, r.mode, b, far=I.PREFIX_FAR in r.prefix), len(raw))
        if got != want:
            bad.append((bytes(raw).hex(), got, want))
    assert not bad, bad[:10]


@pytest.mark.parametrize("cpu", [0, 2, 3])
def test_no_peel_below_the_45gs02(dsyms, cpu):
    assert R.run_dasm(dsyms, cpu, [0x42, 0x42, 0x65, 0x12, 0])[:2] == \
        ("... ", 1) if cpu in (0, 2) else ("NEG ", 1)
    got = R.run_dasm(dsyms, cpu, [0xEA, 0xB2, 0x12, 0, 0])[:2]
    assert got == ("EOM ", 1)


def test_a_lone_prefix_byte_is_its_own_instruction(dsyms):
    assert R.run_dasm(dsyms, 4, [0x42, 0xA9, 0x01, 0, 0])[:2] == ("NEG ", 1)
    assert R.run_dasm(dsyms, 4, [0x42, 0x42, 0xA9, 0x01, 0])[:2] == ("NEG ", 1)
    assert R.run_dasm(dsyms, 4, [0xEA, 0xA9, 0x01, 0, 0])[:2] == ("EOM ", 1)


def test_round_trip_over_the_45gs02_view(dsyms):
    """Assemble each row, list the bytes, assemble the listing: the same
    bytes (asm at the listing's address, so branch targets agree)."""
    asyms = AsmCoreSymbols("45gs02")
    bad = []
    for r in I.instructions("45gs02"):
        if r.mode in ("REL", "ZPREL", "REL16"):
            b = {"REL": [0x10], "ZPREL": [0x12, 0x10], "REL16": [0x00, 0x10]}[r.mode]
        else:
            b = [0x12, 0x34][:I.MODE_OPERAND_BYTES[r.mode]]
        raw = list(r.prefix) + [r.opcode] + b
        listed, n = R.run_dasm(dsyms, 4, raw + [0] * (5 - len(raw)))[:2]
        again = R.run_asm(asyms, listed.strip(), 4, pc=AT)[0]
        if again != bytes(raw[:n]):
            bad.append((bytes(raw).hex(), listed, again))
    assert not bad, bad[:10]
