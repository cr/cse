"""test_c64emu_cia.py — C64Emu's keyboard matrix under the banking.

Owner: doc/build_system.md

Contract source: [doc/testing.md § C64Emu](../../doc/testing.md#c64emu--emulator-class).

The matrix, STOP and RESTORE hold for both harnesses and are tested in
test_emu_parity.py.  This file keeps the C64-only case: with CHAREN=0
(I/O hidden by the CHARGEN overlay) $DC01 reads the character ROM, not
the matrix.
"""

import pytest
from c64emu import C64Emu


# ── Matrix read gated by banking ─────────────────────────────────

def test_matrix_hidden_when_charen_clear_chargen_available():
    """With CHAREN=0 and HIRAM=1, CHARGEN overlays $D000-$DFFF —
    matrix reads at $DC01 return CHARGEN byte instead."""
    emu = C64Emu()
    if emu._mem.rom_chargen is None:
        pytest.skip("chargen_cbm.bin not present")
    emu.press_key('A')
    emu.memory[0x01] = 0x32           # HIRAM=1, CHAREN=0
    # $DC01 is now CHARGEN $0C01 byte, not keyboard
    assert emu.memory[0xDC01] == emu._mem.rom_chargen[0x0C01]
