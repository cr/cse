"""test_m65_asm_src.py — the source assembler on the m65 PRG (P4 T5).

Owner: doc/modules/asm_src.md

Contract source: [asm_line.md § Branches](../../doc/modules/asm_line.md#branches-zone-b)
(the width rule), [symtab.md § Pass stamp](../../doc/modules/symtab.md#pass-stamp-mega_support).

The debug m65 PRG, cold-started as in test_m65_repl.py (M65Session,
asm_cpu = 4), its source typed into the editor's buffer and assembled
with `a`.  A backward branch out of reach takes REL16 and a forward one
REL, the same in both passes: every later address stays put, so pass 1
reports no error and the bytes are where pass 0 sized them.
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
