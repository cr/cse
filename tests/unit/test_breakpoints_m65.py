"""
test_breakpoints_m65.py — breakpoints.s on m65: the flat-address table (Tier U)

Owner: doc/modules/breakpoints.md

Contract source: breakpoints.md (the m65 slot of 6 bytes: a flat
address [offset lo, hi, bank, megabyte], the saved byte, the flags;
`dbg_bp_set` / `dbg_bp_find` translating the CPU address through the
program's bank state; `dbg_bp_set_flat`; `dbg_step_find`;
`step_bp_arm`).  The c64's 4-byte table is test_breakpoints.py's.

Test binary: zp.s + mem.s (`far_user`) + breakpoints.s, assembled for
m65 and linked by dev/m65_test.cfg (testing.md § m65 bundles), run on
M65Emu as kernel code runs (B = CSE_BP).  No stub: the routines are
called with their registers set.  The bank state is `um_map` in the
base page; zero (the bundle's) maps nothing, so a CPU address in
$0000-$BFFF is bank 0's.
"""

import pytest

import asm_dasm_runner as R
from conftest import (Bundle, PROD_DEFS, SRC, DEV, SymbolTable, _BundleImage,
                      _bundle_layout)

BP_SLOTS, STEP_SLOTS, SLOT = 8, 2, 6
SAVED, FLAGS = 4, 5
PATCHED = 0x80

_PLATFORM, _CFG, _ = _bundle_layout("45gs02")
_BUNDLE = Bundle("breakpoints_45gs02_test",
                 [SRC / "zp.s", SRC / "mem.s", SRC / "breakpoints.s"],
                 PROD_DEFS["45gs02"], tag="bp_45gs02", platform=_PLATFORM, cfg=_CFG)


class BpM65(_BundleImage):
    def __init__(self):
        bundle = _BUNDLE.ensure()
        self._split(bundle, "45gs02")
        self.s = SymbolTable(bundle.lbl)

    def __getattr__(self, name):
        return self.s[name]


@pytest.fixture(scope="module")
def syms():
    return BpM65()


class Table:
    """One bundle with bp_init run; the routines called by name."""

    def __init__(self, syms):
        self.syms = syms
        self.m = R.M65Bundle(syms)
        self.mem = self.m.mem
        self.call("bp_init")

    def call(self, name, a=0, x=0, y=0):
        cpu = self.m.emu.cpu
        cpu.a, cpu.x = a, x
        self.m.call(self.syms.s[name], y=y)
        return cpu.a, bool(cpu.p & 1)

    def set(self, addr):
        return self.call("dbg_bp_set", addr & 0xFF, addr >> 8)

    def set_flat(self, flat):
        self.m.poke(self.syms.rp_ptr, *flat.to_bytes(4, "little"))
        return self.call("dbg_bp_set_flat")

    def find(self, addr):
        return self.call("dbg_bp_find", addr & 0xFF, addr >> 8)

    def slot(self, k):
        return list(self.m.peek(self.syms.bp_table + k * SLOT, SLOT))

    def far_map(self, bank):
        """The program's map: $2000-$7FFF to bank.2000 (a far start's)."""
        self.m.poke(self.syms.um_map, 0xE0 | bank, 0, 0, 0, 0, 0)


@pytest.fixture
def t(syms):
    return Table(syms)


def test_bp_init_zeroes_ten_six_byte_slots(syms):
    t = Table(syms)
    t.m.poke(syms.bp_table, *[0xA5] * (BP_SLOTS + STEP_SLOTS) * SLOT)
    t.m.poke(syms.bp_table + (BP_SLOTS + STEP_SLOTS) * SLOT, 0x5A)   # the byte after
    t.call("bp_init")
    assert not any(t.m.peek(syms.bp_table, (BP_SLOTS + STEP_SLOTS) * SLOT))
    assert t.m.peek(syms.dbg_bp_hit)[0] == 0xFF
    assert syms.step_bp == syms.bp_table + BP_SLOTS * SLOT


def test_set_stores_the_flat_address_in_six_bytes(t):
    assert t.set(0x3000) == (0, False)
    assert t.set(0x3456) == (1, False)
    assert t.slot(0) == [0x00, 0x30, 0, 0, 0, 1]
    assert t.slot(1) == [0x56, 0x34, 0, 0, 0, 1]


def test_set_translates_through_the_programs_map(t):
    t.far_map(4)
    assert t.set(0x3000) == (0, False)
    assert t.slot(0)[:4] == [0x00, 0x30, 0x04, 0x00]
    t.far_map(0)
    assert t.find(0x3000) == (0xFF, True)        # 0.3000 is another byte
    t.far_map(4)
    assert t.find(0x3000) == (0, False)


def test_set_flat_takes_the_address_as_it_is(t):
    assert t.set_flat(0x0051234) == (0, False)
    assert t.slot(0) == [0x34, 0x12, 0x05, 0x00, 0, 1]
    assert t.set_flat(0x0051234) == (0, False)    # no duplicate
    assert t.set_flat(0x0061234) == (1, False)    # another bank, another slot


def test_a_bank_with_offset_zero_is_a_breakpoint(t):
    """dbg_bp_count / set's empty-slot test read the bank: 1.0000 is not
    an empty slot."""
    t.set_flat(0x0010000)
    assert t.call("dbg_bp_count")[0] == 1
    assert t.set(0x3000) == (1, False)
    assert t.call("dbg_bp_count")[0] == 2


def test_table_full_after_eight(t):
    for k in range(BP_SLOTS):
        assert t.set(0x3000 + k) == (k, False)
    assert t.set(0x4000) == (0xFF, True)
    assert t.call("dbg_bp_count")[0] == BP_SLOTS


@pytest.mark.parametrize("k", range(BP_SLOTS))
def test_del_zeroes_exactly_its_six_bytes(t, k):
    for j in range(BP_SLOTS):
        t.set_flat(0x0040000 | 0x3000 + j)
    assert t.call("dbg_bp_del", k)[1] is False
    for j in range(BP_SLOTS + STEP_SLOTS):
        empty = j == k or j >= BP_SLOTS
        assert (t.slot(j) == [0] * SLOT) == empty, (j, t.slot(j))
    assert t.call("dbg_bp_count")[0] == BP_SLOTS - 1


def test_del_bad_slot_and_the_hit(t):
    t.set(0x3000)
    t.m.poke(t.syms.dbg_bp_hit, 0)
    assert t.call("dbg_bp_del", BP_SLOTS)[1]
    assert t.call("dbg_bp_del", 0)[1] is False
    assert t.m.peek(t.syms.dbg_bp_hit)[0] == 0xFF


def test_clear_keeps_the_step_slots(t):
    t.set(0x3000)
    t.call("step_bp_arm", 0x00, 0x31, y=0)
    t.call("dbg_bp_clear")
    assert t.call("dbg_bp_count")[0] == 0
    assert t.slot(BP_SLOTS)[:4] == [0x00, 0x31, 0, 0]


def test_patch_and_unpatch_the_physical_byte_in_another_bank(t):
    mem = t.mem
    mem.write_flat(0x43000, 0xA9)                 # 4.3000
    mem.write_flat(0x03000, 0xEA)                 # 0.3000, untouched
    t.far_map(4)
    t.set(0x3000)
    t.call("patch_all")
    assert mem.read_flat(0x43000) == 0x00 and mem.read_flat(0x03000) == 0xEA
    assert t.slot(0)[SAVED] == 0xA9 and t.slot(0)[FLAGS] == 1 | PATCHED
    t.far_map(0)                                  # remapped since: the slot's byte still
    t.call("unpatch_all")
    assert mem.read_flat(0x43000) == 0xA9 and mem.read_flat(0x03000) == 0xEA
    assert t.slot(0)[FLAGS] == 1


@pytest.mark.parametrize("y, k", [(0, 0), (SLOT, 1)])
def test_step_bp_arm_fills_step_slot_y(t, y, k):
    t.far_map(5)
    t.call("step_bp_arm", 0x10, 0x30, y=y)
    assert t.slot(BP_SLOTS + k) == [0x10, 0x30, 0x05, 0x00, 0, 1]
    assert t.slot(BP_SLOTS + 1 - k) == [0] * SLOT
    assert t.call("dbg_bp_count")[0] == 0         # not a user breakpoint


def test_step_find_matches_either_step_slot_only(t):
    t.far_map(4)
    t.call("step_bp_arm", 0x00, 0x30, y=0)
    t.call("step_bp_arm", 0x08, 0x30, y=SLOT)
    t.set(0x3020)                                 # a user breakpoint: not a step slot
    assert t.call("dbg_step_find", 0x00, 0x30)[1] is False
    assert t.call("dbg_step_find", 0x08, 0x30)[1] is False
    assert t.call("dbg_step_find", 0x20, 0x30)[1] is True
    t.far_map(0)                                  # the same CPU address, bank 0
    assert t.call("dbg_step_find", 0x00, 0x30)[1] is True


def test_step_clear_zeroes_only_the_step_slots(t):
    t.set(0x3000)
    t.call("step_bp_arm", 0x00, 0x31, y=0)
    t.call("step_bp_arm", 0x00, 0x32, y=SLOT)
    t.call("dbg_step_clear")
    assert t.slot(BP_SLOTS) == t.slot(BP_SLOTS + 1) == [0] * SLOT
    assert t.slot(0) == [0x00, 0x30, 0, 0, 0, 1]
