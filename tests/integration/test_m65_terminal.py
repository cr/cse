"""test_m65_terminal.py — the terminal on the m65 PRG: geometry, output, keys (P2 T3 T4).

Owner: doc/modules/cse_io.md

Contract source: [doc/modules/cse_io.md § Interface](../../doc/modules/cse_io.md#interface)
(*On m65*, io_geometry, io_kbhit / io_getc on m65) and
[doc/platform_layer.md § Terminal](../../doc/platform_layer.md#terminal),
§ Display (*The geometry*).

The debug m65 PRG installed on each post-boot snapshot (the real
KERNAL; the screen editor as test_m65_editor.py holds it to xmega65).
A mode is switched as the KERNAL does it — ESC 8 / 4 / 5 through BSOUT
— and cse_io's routines are called with B = CSE_BP.

- io_geometry per mode, and under a program's window (it leaves it).
- io_putc / io_puthex2 / io_clear_eol land in the mode's screen (bank
  4 in 80 x 50) and clamp at its last column; io_sync puts the
  KERNAL's cursor at CSE's.
- io_kbhit / io_getc / io_kbd_flush over the hardware queue and the
  KERNAL buffer (ADDKEY), through the one-key lookahead.
"""

import pytest

from m65emu import M65Emu
from m65emu.harness import CSE_BP, TEXT_MODES as MODES, flat

BSOUT, ADDKEY = 0xFFD2, 0xFF4A
ESC = 0x1B
@pytest.fixture
def emu(cse_m65_prg, m65_snapshot):
    emu = M65Emu(m65_snapshot)
    emu.install_prg(*cse_m65_prg)
    return emu


def kernal(emu, entry, **regs):
    emu.jsr(entry, b=0, **regs)


def mode(emu, name):
    key = MODES[name][0]
    kernal(emu, BSOUT, a=ESC)
    kernal(emu, BSOUT, a=ord(key))
    emu.jsr(emu.sym("io_geometry"), b=CSE_BP)


def cell(emu, row, col, name="80x25"):
    _, width, _, bank = MODES[name]
    return emu.memory.read_flat(flat(bank, 0x0800 + row * width + col))


def set_cursor(emu, row, col):
    emu.memory[emu.cell("io_cy")], emu.memory[emu.cell("io_cx")] = row, col


# ── T3: the geometry ───────────────────────────────────────────────

@pytest.mark.parametrize("name", list(MODES))
def test_io_geometry_per_mode(emu, name):
    _, width, height, bank = MODES[name]
    mode(emu, name)
    m = emu.memory
    assert (m[emu.cell("scr_width")], m[emu.cell("scr_height")]) == (width, height)
    assert (m[emu.cell("scr_last_col")], m[emu.cell("scr_last_row")]) == (width - 1, height - 1)
    assert m[emu.cell("scr_ed_rows")] == height - 3
    assert m[emu.cell("scr_bank")] == bank
    size = m[emu.cell("scr_size")] | m[emu.cell("scr_size") + 1] << 8
    assert size == width * height
    lo, hi = emu.sym("scr_lo"), emu.sym("scr_hi")
    for row in range(height):
        assert m[lo + row] | m[hi + row] << 8 == 0x0800 + row * width, row


def test_io_geometry_leaves_a_programs_window(emu):
    """ESC T / ESC B set a window from (2,3) to (10,40); io_geometry
    sends HOME HOME first, so the geometry is the full screen's."""
    for row, col, key in ((2, 3, "T"), (10, 40, "B")):
        emu.jsr(0xFFF0, b=0, x=row, y=col, carry=False)
        kernal(emu, BSOUT, a=ESC)
        kernal(emu, BSOUT, a=ord(key))
    emu.jsr(emu.sym("io_geometry"), b=CSE_BP)
    m = emu.memory
    assert (m[emu.cell("scr_width")], m[emu.cell("scr_height")]) == (80, 25)


# ── T4: output ────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(MODES))
def test_io_putc_lands_in_the_modes_screen_and_clamps(emu, name):
    _, width, height, _ = MODES[name]
    mode(emu, name)
    row = height - 1
    set_cursor(emu, row, width - 2)
    emu.jsr(emu.sym("io_putc"), a=ord("A"), b=CSE_BP)
    emu.jsr(emu.sym("io_putc"), a=ord("B"), b=CSE_BP)
    emu.jsr(emu.sym("io_putc"), a=ord("C"), b=CSE_BP)        # clamped: overwrites B
    assert cell(emu, row, width - 2, name) == 0x01            # 'A' screen code
    assert cell(emu, row, width - 1, name) == 0x03            # 'C'
    assert emu.memory[emu.cell("io_cx")] == width - 1


@pytest.mark.parametrize("name", list(MODES))
def test_io_puthex2_and_clear_eol_in_the_mode(emu, name):
    _, width, _, _ = MODES[name]
    mode(emu, name)
    set_cursor(emu, 3, 10)
    emu.jsr(emu.sym("io_puthex2"), a=0xA5, b=CSE_BP)
    assert (cell(emu, 3, 10, name), cell(emu, 3, 11, name)) == (0x01, 0x35)
    for col in range(12, width):
        emu.memory.write_flat(flat(MODES[name][3], 0x0800 + 3 * width + col), 0x2A)
    set_cursor(emu, 3, 12)
    emu.jsr(emu.sym("io_clear_eol"), b=CSE_BP)
    assert all(cell(emu, 3, c, name) == 0x20 for c in range(12, width))


def test_io_sync_puts_the_kernals_cursor_at_cses(emu):
    mode(emu, "80x25")
    set_cursor(emu, 7, 33)
    emu.jsr(emu.sym("io_sync"), b=CSE_BP)
    kernal(emu, BSOUT, a=ord("Z"))
    assert cell(emu, 7, 33) == 0x1A


# ── T4: keys ──────────────────────────────────────────────────────

def test_io_kbhit_peeks_without_consuming_and_io_getc_takes(emu):
    emu.inject_key(ord("Q"))
    emu.jsr(emu.sym("io_kbhit"), b=CSE_BP)
    assert emu.a == ord("Q")
    emu.jsr(emu.sym("io_kbhit"), b=CSE_BP)
    assert emu.a == ord("Q")                                  # still there
    emu.jsr(emu.sym("io_getc"), b=CSE_BP)
    assert (emu.a, emu.x) == (ord("Q"), 0)
    emu.jsr(emu.sym("io_kbhit"), b=CSE_BP)
    assert emu.a == 0


def test_io_kbhit_sees_a_key_addkey_queued(emu):
    """The KERNAL buffer ADDKEY feeds, which no register shows."""
    kernal(emu, ADDKEY, a=ord("W"))
    emu.jsr(emu.sym("io_kbhit"), b=CSE_BP)
    assert emu.a == ord("W")


def test_io_kbd_flush_drains_the_lookahead_and_both_queues(emu):
    emu.inject_keys(b"AB")
    kernal(emu, ADDKEY, a=ord("C"))
    emu.jsr(emu.sym("io_kbhit"), b=CSE_BP)                    # one in the lookahead
    emu.jsr(emu.sym("io_kbd_flush"), b=CSE_BP)
    assert emu.a == 0
    emu.jsr(emu.sym("io_kbhit"), b=CSE_BP)
    assert emu.a == 0
