"""test_platform_m65.py — the m65 bodies of platform.inc's macros (T7).

Owner: doc/platform_layer.md

Contract source: [doc/platform_layer.md § Seam contracts](../../doc/platform_layer.md#seam-contracts).

Tier U.  dev/m65_macros_test.s, assembled with -DPLATFORM_M65, runs on
a blank M65Emu in clean mode — the 6502's opcodes and src/m45_ops.inc's
only — with B = CSE_BP, as kernel code runs:

- KCALL / KJMP: the entry runs with B = 0; A, X, Y and C pass through
  in both directions; B is CSE_BP again afterwards.
- FAR_LDA / FAR_STA / FAR_ORA reach the pointer's bank + offset + Y
  in banks 0, 2, 3 and 4; FAR_BANK sets the bank, clears the
  megabyte and keeps A; an access past a row's end reaches the next
  flat bytes of the pointer's bank (D-P1-2).
- PLAT_SETBNK calls SETBNK with the data's bank BANK_USER and the
  filename's BANK_CSE.
- IO_STOP_DOWN answers Z set exactly when ScanStopKey reports STOP
  held ($7F), with B = 0 for the KERNAL.
"""

import pytest

from conftest import BUILD, DEV, Bundle, SymbolTable
from m65emu import M65Emu, m45_ops
from m65emu.harness import (BANK_CSE, BANK_SCREEN50, BANK_SRC, BANK_USER,
                            CSE_BP)

_BUNDLE = Bundle("m65_macros_test", [DEV / "m65_macros_test.s"], [],
                 tag="m65m", cfg=DEV / "m65_test.cfg", platform="m65")
_BP_SIZE = 0xB0
_CODE = 0x4000
_TBA = (0x7B,)                       # fake_entry's, test code only


@pytest.fixture(scope="module")
def syms():
    return SymbolTable(_BUNDLE.ensure().lbl)


@pytest.fixture
def emu(syms):
    emu = M65Emu()
    raw = _BUNDLE.bin.read_bytes()
    emu.memory.load(CSE_BP << 8, raw[:_BP_SIZE])
    emu.memory.load(_CODE, raw[_BP_SIZE:])
    emu.memory.rom_protect = False          # banks 2-3 writable, as installed
    cpu = emu.cpu
    cpu.clean = True
    cpu.allowed = cpu.allowed | m45_ops.allowed_keys() | {_TBA}
    return emu


def bp(syms, name):
    """The flat address of a base-page symbol (B = CSE_BP)."""
    return (CSE_BP << 8) + syms[name]


def set_ptr(emu, syms, bank, offset):
    a = bp(syms, "fp")
    for k, v in enumerate([offset & 0xFF, offset >> 8, bank, 0]):
        emu.memory.write_flat(a + k, v)


# ── KCALL / KJMP ──────────────────────────────────────────────────

@pytest.mark.parametrize("entry", ["t_kcall", "t_kjmp"])
def test_kernal_call_runs_with_b_0_and_passes_registers_through(emu, syms, entry):
    emu.jsr(syms[entry], a=0x11, x=0x22, y=0x33, b=CSE_BP, carry=False)
    seen = [emu.memory.read_flat(syms["seen"] + k) for k in range(5)]
    assert seen[:3] == [0x11, 0x22, 0x33]
    assert seen[3] & 0x01 == 0                     # C in
    assert seen[4] == 0                            # B = 0 for the KERNAL
    assert (emu.a, emu.x, emu.y, emu.carry) == (0x5A, 0xA5, 0x3C, True)
    assert emu.b == CSE_BP


# ── far memory ────────────────────────────────────────────────────

@pytest.mark.parametrize("bank", [BANK_USER, BANK_SRC, BANK_CSE, BANK_SCREEN50])
def test_far_load_store_or_reach_bank_offset_plus_y(emu, syms, bank):
    offset, y = 0x5F80, 0x91
    flat = (bank << 16) + offset + y
    set_ptr(emu, syms, bank, offset)
    emu.memory.write_flat(flat, 0x3C)
    emu.jsr(syms["t_far_lda"], y=y, b=CSE_BP)
    assert emu.a == 0x3C
    emu.jsr(syms["t_far_ora"], a=0x41, y=y, b=CSE_BP)
    assert emu.a == 0x7D
    emu.jsr(syms["t_far_sta"], a=0xE7, y=y, b=CSE_BP)
    assert emu.memory.read_flat(flat) == 0xE7
    assert emu.a == 0xE7 and emu.y == y
    for other in {BANK_USER, BANK_SRC, BANK_CSE, BANK_SCREEN50} - {bank}:
        assert emu.memory.read_flat((other << 16) + offset + y) == 0


def test_far_bank_sets_the_bank_and_keeps_a(emu, syms):
    set_ptr(emu, syms, BANK_USER, 0x1234)
    emu.memory.write_flat(bp(syms, "fp") + 3, 0x0F)  # as FAR_USER's I/O row
    emu.jsr(syms["t_far_bank"], a=0x77, b=CSE_BP)
    assert emu.a == 0x77
    a = bp(syms, "fp")
    assert [emu.memory.read_flat(a + k) for k in range(4)] == [0x34, 0x12, BANK_SRC, 0]


def test_far_access_past_a_rows_end_reaches_the_next_flat_bytes(emu, syms):
    """D-P1-2: the translation is the pointer's; $BFFC + Y = 4 in bank
    0 is 0.C000, not the interface ROM the user map shows there."""
    set_ptr(emu, syms, BANK_USER, 0xBFFC)
    emu.memory.write_flat(0x0C000, 0x99)
    emu.jsr(syms["t_far_lda"], y=4, b=CSE_BP)
    assert emu.a == 0x99


# ── PLAT_SETBNK ───────────────────────────────────────────────────

def test_setbnk_names_the_user_data_bank_and_cses_filename_bank(emu, syms):
    # a stand-in SETBNK at $FF6B (the KERNAL ROM page): A, X to $4F00
    emu.memory.load(0x2FF6B, bytes([0x8D, 0x00, 0x4F, 0x8E, 0x01, 0x4F, 0x60]))
    emu.jsr(syms["t_setbnk"], b=CSE_BP)
    assert (emu.memory.read_flat(0x4F00), emu.memory.read_flat(0x4F01)) == \
        (BANK_USER, BANK_CSE)
    assert emu.b == CSE_BP


# ── IO_STOP_DOWN (platform_layer.md § Terminal) ───────────────────

@pytest.mark.parametrize("answer,held", [(0x7F, True), (0xFF, False)])
def test_io_stop_down_is_scanstopkey(emu, syms, answer, held):
    # a stand-in ScanStopKey at $FFEA (the KERNAL ROM page): lda #answer, rts
    emu.memory.load(0x2FFEA, bytes([0xA9, answer, 0x60]))
    emu.jsr(syms["t_stop_down"], b=CSE_BP)
    assert bool(emu.a & 0x02) is held          # the pushed P's Z
    assert emu.b == CSE_BP
