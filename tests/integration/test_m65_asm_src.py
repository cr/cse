"""test_m65_asm_src.py — the source assembler on the m65 PRG (P4 T5).

Owner: doc/modules/asm_src.md

Contract source: [asm_line.md § Branches](../../doc/modules/asm_line.md#branches-zone-b)
(the width rule), [symtab.md § Pass stamp](../../doc/modules/symtab.md#pass-stamp-mega_support);
[assembler_syntax.md § Directives](../../doc/assembler_syntax.md#directives)
and [asm_src.md § _emit_byte](../../doc/modules/asm_src.md#_emit_byte)
(the banks, slice 3 F5b).

The debug m65 PRG, cold-started as in test_m65_repl.py (M65Session,
asm_cpu = 4), its source typed into the editor's buffer and assembled
with `a`.  A backward branch out of reach takes REL16 and a forward one
REL, the same in both passes: every later address stays put, so pass 1
reports no error and the bytes are where pass 0 sized them.

The banks (F5b): a flat `.org` into banks 1, 4 and 5, the emit gate's
edges and the bank-end wrap, `.org`'s limits (28 bits; a negative one
is its low word), flat labels, the same-bank rule's refusals, `.dd`,
the segment and save lines, `.bas` back in bank 0, `a`'s default
origin at a flat address, `info_bank` left 0, no bank after `a`, and
a refused `.dw` / `.dd` value that still lays out its bytes.
"""

from m65emu.harness import flat
from test_m65_repl import M65Session

SOURCE = (b"\xa0.org $3000\r"
          b"start:\xa0nop\r"
          b"\xa0.res 200\r"
          b"\xa0bne start\r"            # backward, out of reach: REL16
          b"\xa0bne fwd\r"              # forward: REL
          b"fwd:\xa0ldq ($12),z\r"      # a 45GS02 form, the default CPU
          b"\xa0rts\r").upper()        # PETSCII's lowercase letters: $41-$5A


def test_far_and_forward_branches_are_pass_stable(cse_m65_prg, m65_snapshot):
    s = M65Session(cse_m65_prg, m65_snapshot)
    s.call("ed_ensure_init")
    for ch in SOURCE:
        s.call("gb_insert", a=ch)
    s.type("a", max_steps=6_000_000)
    assert s.w("asm_errors") == 0
    m = s.e.memory
    got = [m.read_flat(flat(0, 0x30C9 + k)) for k in range(10)]
    assert got == [0xD3, 0x35, 0xFF,               # $3000 - ($30C9 + 2)
                   0xD0, 0x00,                     # fwd: the next instruction
                   0x42, 0x42, 0xB2, 0x12,         # ldq ($12),z
                   0x60]


# ── the assembler's banks (slice 3, F5b: assembler_syntax.md § Directives,
#    asm_src.md § _emit_byte) ──────────────────────────────────────────

import re                                        # noqa: E402

import pytest                                    # noqa: E402

from test_m65_repl import fpeek, fpoke, prompt  # noqa: E402


@pytest.fixture
def s(cse_m65_prg, m65_snapshot):
    return M65Session(cse_m65_prg, m65_snapshot)


def assemble(s, text):
    """`text` (a tab indents) into the buffer, then `a`."""
    s.call("ed_ensure_init")
    for ch in text.replace("\t", "\xa0").encode("latin-1").upper():
        s.call("gb_insert", a=ch)
    s.type("a", max_steps=6_000_000)
    return s.w("asm_errors")


def rows(s):
    return [r.rstrip() for r in s.rows()]


@pytest.mark.parametrize("bank", [1, 4, 5])
def test_a_flat_org_assembles_into_the_bank(s, bank):
    fpoke(s, 0, 0x2000, [0xEA] * 3)
    assert assemble(s, f"\t.org {bank}.2000\rmain:\tlda #$5a\r\trts\r") == 0
    assert fpeek(s, bank, 0x2000, 3) == [0xA9, 0x5A, 0x60]
    assert fpeek(s, 0, 0x2000, 3) == [0xEA] * 3              # not bank 0
    assert f"; org  {bank}.2000-2002     3b" in rows(s)
    assert not any(':s "' in r for r in rows(s))             # bank 0 only
    assert prompt(s) == f"{bank}.2000:"                      # main, flat


@pytest.mark.parametrize("org", ["1.2000", "1.f6fe", "4.0000", "4.fffe", "5.0000", "5.fffe"])
def test_the_gate_admits_the_user_memory_of_banks_1_4_5(s, org):
    bank, addr = int(org.split(".")[0], 16), int(org.split(".")[1], 16)
    assert assemble(s, f"\t.org {org}\r\tnop\r\tnop\r") == 0
    assert fpeek(s, bank, addr, 2) == [0xEA, 0xEA]


@pytest.mark.parametrize("org", ["1.1fff", "1.f700", "2.4000", "3.2000", "6.0000", "10.0000"])
def test_the_gate_refuses_other_banks_and_writes_nothing(s, org):
    bank, addr = int(org.split(".")[0], 16), int(org.split(".")[1], 16)
    fpoke(s, bank, addr, [0x00])
    assert assemble(s, f"\t.org {org}\r\tnop\r") == 1
    assert ";?2: range" in rows(s)
    assert fpeek(s, bank, addr) == [0x00]


def test_a_flat_segment_wraps_at_its_banks_end_not_into_the_next(s):
    fpoke(s, 5, 0x0000, [0x00])
    fpoke(s, 6, 0x0000, [0x00])
    assert assemble(s, "\t.org 5.ffff\r\tnop\r\tnop\r") == 1
    assert ";?3: range" in rows(s)
    assert fpeek(s, 5, 0xFFFF) == [0xEA]
    assert fpeek(s, 5, 0x0000) == [0x00] and fpeek(s, 6, 0x0000) == [0x00]


def test_org_above_28_bits_is_bad_val(s):
    assert assemble(s, "\t.org $10000000\r\tnop\r") >= 1
    assert ";?1: bad val" in rows(s)


def test_org_in_bank_0_is_a_cpu_origin(s):
    assert assemble(s, "\t.org 0.3000\rmain:\tnop\r") == 0
    assert fpeek(s, 0, 0x3000) == [0xEA]
    assert '3000:s "out" $3000' in rows(s)
    assert prompt(s) == "3000:"


def test_a_label_in_a_bank_is_flat_and_its_own_bank_takes_its_low_word(s):
    src = ("\t.org 4.2000\r"
           "loop:\tnop\r"
           "\tbne loop\r"
           "\tjmp loop\r"
           "\t.dw loop\r"
           "\tlda #<loop\r"
           "\tlda #<(loop>>16)\r")
    assert assemble(s, src) == 0
    assert fpeek(s, 4, 0x2000, 12) == [0xEA, 0xD0, 0xFD, 0x4C, 0x00, 0x20,
                                       0x00, 0x20, 0xA9, 0x00, 0xA9, 0x04]
    s.type("? loop")
    s.find(r"^; \$00042000  270336$")


def test_another_banks_value_is_refused_where_16_bits_are_taken(s):
    src = ("\t.const far 4.2000\r"         # 1
           "\t.org $3000\r"                # 2
           "\tjsr far\r"                   # 3: bank 0 takes no bank-4 value
           "\t.dw far\r"                   # 4
           "\t.org 5.2000\r"               # 5
           "\tjmp far\r"                   # 6: nor bank 5
           "\tjmp 5.2000\r"                # 7: its own bank: the low word
           "\t.db >far\r"                  # 8
           "\t.org $3100\r"                # 9: back in bank 0
           "\tlda 5.2000\r")               # 10
    assert assemble(s, src) == 4
    r = rows(s)
    assert [x for x in r if x.startswith(";?")] == [
        ";?3: range", ";?4: bad val", ";?6: range", ";?10: range"]
    assert fpeek(s, 5, 0x2000, 4) == [0x4C, 0x00, 0x20, 0x20]


def test_dd_emits_32_bit_words(s):
    src = ("\t.org $3000\r"
           "\t.dd $12345678, 4.2000, -1\r"
           "after:\tnop\r"
           "\t.dd fwd\r"
           "fwd:\tnop\r")
    assert assemble(s, src) == 0
    assert fpeek(s, 0, 0x3000, 18) == [0x78, 0x56, 0x34, 0x12, 0x00, 0x20, 0x04, 0x00,
                                       0xFF, 0xFF, 0xFF, 0xFF, 0xEA,
                                       0x11, 0x30, 0x00, 0x00, 0xEA]


def test_segment_lines_name_their_bank_and_the_save_line_bank_0(s):
    src = "\t.org $3000\rmain:\tnop\r\t.org 4.2000\r\tnop\r\tnop\r"
    assert assemble(s, src) == 0
    r = rows(s)
    assert "; org  0.3000-3000     1b" in r
    assert "; org  4.2000-2001     2b" in r
    assert '3000:s "out" $3000' in r


def test_an_assembly_leaves_no_bank_to_the_repl(s):
    assemble(s, "\t.org 4.2000\rmain:\tnop\r")
    s.type("B $40010")
    s.find(r"^;\?expr range$")


# ── review fixes (2026-11-20): the bank at `.bas`, the default origin,
#    info_bank, a negative `.org` ─────────────────────────────────────

def test_bas_after_a_flat_org_is_bank_0s(s):
    fpoke(s, 4, 0x2001, [0x00] * 8)
    src = "\t.org 4.2000\r\tnop\r\t.bas\r\tnop\r\tlda 4.0010\r"
    assert assemble(s, src) == 1
    assert ";?5: range" in rows(s)                       # no bank after .bas
    assert fpeek(s, 0, 0x2005) == [0x9E]                 # SYS, in bank 0
    assert fpeek(s, 4, 0x2001, 8) == [0x00] * 8


def test_a_at_a_flat_address_assembles_there_without_an_org(s):
    fpoke(s, 0, 0x2000, [0x00, 0x00])
    s.type("@ 4.2000")
    assert assemble(s, "main:\tnop\r\trts\r") == 0
    assert fpeek(s, 4, 0x2000, 2) == [0xEA, 0x60]
    assert fpeek(s, 0, 0x2000, 2) == [0x00, 0x00]
    assert "; org  4.2000-2001     2b" in rows(s)
    assert prompt(s) == "4.2000:"


def test_a_flat_segment_line_leaves_info_bank_0(s):
    assert assemble(s, "\t.org 4.2000\r\tnop\r") == 0
    assert s.v("info_bank") == 0                         # prg_line reads it


def test_a_negative_org_is_its_low_word(s):
    assert assemble(s, "\t.org $3000-$10000\r\tnop\r") == 0
    assert fpeek(s, 0, 0x3000) == [0xEA]


def test_refused_data_values_keep_the_layout(s):
    """TODO § Bugs › Both platforms (fixed 2026-11-20): `.dw` of another
    bank's value and an undefined `.dd` are reported and still lay out
    their bytes, so `after` stays where pass 0 put it."""
    src = ("\t.org $3000\r\tjmp after\r\t.dw 4.2000\r\t.dd nosuch\r"
           "after:\trts\r")
    assert assemble(s, src) == 2
    assert fpeek(s, 0, 0x3000, 3) == [0x4C, 0x09, 0x30]
    assert fpeek(s, 0, 0x3009) == [0x60]


@pytest.mark.parametrize("insn,code", [
    ("lda (ptr),y", [0xB1, 0xFB]), ("lda (ptr),z", [0xB2, 0xFB]),
    ("lda [ptr],z", [0xEA, 0xB2, 0xFB]), ("lda (ptr,sp),y", [0xE2, 0xFB]),
    ("bbr0 ptr,*", [0x0F, 0xFB, 0xFD])])
def test_a_forward_zero_page_pointer_takes_its_form(s, insn, code):
    """TODO § Bugs (fixed 2026-11-21): a forward reference in a
    zero-page-only form is sized narrow on both passes."""
    assert assemble(s, f"\t.org $3000\r\t{insn}\r\trts\r\t.const ptr $fb\r") == 0
    assert fpeek(s, 0, 0x3000, len(code) + 1) == code + [0x60]
