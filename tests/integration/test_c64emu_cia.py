"""test_c64emu_cia.py — CIA1 keyboard matrix + CIA2 RESTORE NMI.

Verifies:
  * $DC00 column mask + $DC01 row read model the C64 8×8 matrix.
  * PETSCII press_key / release_key / release_all_keys / press_stop.
  * press_restore() latches CIA2 $DD0D bit 4 + schedules NMI;
    reading $DD0D clears the latch.
  * Matrix reads pass through banking: with CHAREN=0 (I/O hidden by
    CHARGEN overlay), $DC01 reads from CHARGEN ROM, not the matrix.
"""

import pytest
from c64emu import C64Emu


def _scan_all_cols(emu):
    """Write $DC00 = $00 (all columns selected) and read $DC01."""
    emu.memory[0xDC00] = 0x00
    return emu.memory[0xDC01]


def _scan_col(emu, col):
    """Select a single column via $DC00 (write 0 in that bit) and
    read $DC01 row-bit vector."""
    emu.memory[0xDC00] = (~(1 << col)) & 0xFF
    return emu.memory[0xDC01]


# ── Matrix scan basics ───────────────────────────────────────────

def test_empty_matrix_reads_all_ones():
    emu = C64Emu()
    assert _scan_all_cols(emu) == 0xFF


def test_pressed_key_clears_row_bit_in_selected_column():
    emu = C64Emu()
    emu.press_key('A')                # (row 1, col 2)
    # Select col 2: row 1 bit clear, others set.
    val = _scan_col(emu, 2)
    assert (val & 0x02) == 0, f"row 1 bit should be 0, got ${val:02X}"
    assert val == 0xFD                # 1111 1101


def test_pressed_key_does_not_show_in_other_columns():
    emu = C64Emu()
    emu.press_key('A')                # col 2
    val = _scan_col(emu, 5)           # scan col 5 instead
    assert val == 0xFF


def test_multiple_keys_same_column():
    emu = C64Emu()
    emu.press_key('A')                # (1, 2)
    emu.press_key('D')                # (2, 2)
    val = _scan_col(emu, 2)
    # Rows 1 and 2 both cleared → $FF & ~$02 & ~$04 = $F9
    assert val == 0xF9


def test_multiple_keys_different_columns():
    """Scanning both columns selected: both keys visible."""
    emu = C64Emu()
    emu.press_key('A')                # (1, 2)
    emu.press_key('J')                # (4, 2)
    # Wait both are col 2.  Let me use Z and J: Z=(1,4), J=(4,2)
    emu.release_all_keys()
    emu.press_key('Z')                # (1, 4)
    emu.press_key('J')                # (4, 2)
    # Select both cols 2 and 4 (mask = ~(1<<2|1<<4) = ~$14 = $EB)
    emu.memory[0xDC00] = 0xEB
    val = emu.memory[0xDC01]
    # Row 1 (Z) + row 4 (J) cleared → $FF & ~$02 & ~$10 = $ED
    assert val == 0xED


# ── release / release_all ────────────────────────────────────────

def test_release_key_clears_individual():
    emu = C64Emu()
    emu.press_key('A')
    emu.press_key('B')
    emu.release_key('A')
    # B remains.  A's row bit would be set again in col 2.
    val = _scan_col(emu, 2)
    assert val == 0xFF                # no one in col 2


def test_release_all_clears_matrix():
    emu = C64Emu()
    emu.press_key('A')
    emu.press_key('Z')
    emu.release_all_keys()
    assert _scan_all_cols(emu) == 0xFF


# ── STOP key ─────────────────────────────────────────────────────

def test_press_stop_is_row7_col7():
    emu = C64Emu()
    emu.press_stop()
    val = _scan_col(emu, 7)
    assert (val & 0x80) == 0           # row 7 bit cleared


def test_release_stop():
    emu = C64Emu()
    emu.press_stop()
    emu.release_stop()
    assert _scan_col(emu, 7) == 0xFF


# ── PETSCII input forms ──────────────────────────────────────────

def test_lowercase_maps_to_same_cell_as_uppercase():
    emu_a = C64Emu()
    emu_a.press_key('A')
    emu_b = C64Emu()
    emu_b.press_key('a')
    assert emu_a._mem.keyboard_pressed == emu_b._mem.keyboard_pressed


def test_int_petscii_accepted():
    emu = C64Emu()
    emu.press_key(0x41)                # 'A'
    val = _scan_col(emu, 2)
    assert val == 0xFD


def test_unknown_key_raises():
    emu = C64Emu()
    with pytest.raises(KeyError):
        emu.press_key('~')             # not in our partial table


# ── RESTORE → NMI + $DD0D latch ──────────────────────────────────

def test_press_restore_schedules_nmi():
    emu = C64Emu()
    # Before press, queue is empty.
    assert emu._pending == []
    emu.press_restore()
    # An NMI is now pending.
    kinds = [k for _, k in emu._pending]
    assert 'nmi' in kinds


def test_press_restore_latches_cia2_icr():
    emu = C64Emu()
    emu.press_restore()
    # Reading $DD0D returns the latch value then clears it.
    val = emu.memory[0xDD0D]
    assert (val & 0x10) == 0x10
    # Subsequent read returns 0 (latch cleared).
    assert emu.memory[0xDD0D] == 0


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
