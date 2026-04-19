"""test_c64emu_banking.py — BankedMemory contracts: $01 banking + DDR.

Sanity checks for the C64Emu full-$01 banking model.  Verifies:
  * LORAM (bit 0) overlay for BASIC ROM at $A000-$BFFF
  * HIRAM (bit 1) overlay for KERNAL ROM at $E000-$FFFF (existing)
  * CHAREN (bit 2) overlay for CHARGEN ROM at $D000-$DFFF
  * $01 read goes through DDR gating (output bits latched,
    input bits driven by external pin state)
  * BankedMemory latches (loram/hiram/charen) follow $01 writes
"""

import pathlib
import pytest
from c64emu import C64Emu


def _rom(name):
    """Read a ROM image into a bytes object (or None if missing)."""
    p = pathlib.Path(__file__).parent.parent.parent / "rom" / name
    return p.read_bytes() if p.exists() else None


# ── HIRAM (KERNAL) ────────────────────────────────────────────────────

class TestKernalBanking:
    def test_kernal_mapped_by_default(self):
        emu = C64Emu()
        # CSE default $36 has HIRAM=1; reading $E000+ returns KERNAL bytes.
        kernal = _rom("kernal_cbm.bin")
        assert kernal is not None
        assert emu.memory[0xE000] == kernal[0]
        assert emu.memory[0xFFFA] == kernal[0x1FFA]

    def test_kernal_banked_out(self):
        emu = C64Emu()
        # Pre-seed a marker into the RAM under KERNAL.
        emu._mem.ram[0xE000] = 0xA5
        emu.memory[0x01] = 0x34      # clear HIRAM
        assert emu.memory[0xE000] == 0xA5    # RAM visible now
        emu.memory[0x01] = 0x36      # HIRAM back in
        assert emu.memory[0xE000] != 0xA5    # KERNAL ROM again


# ── LORAM (BASIC) ─────────────────────────────────────────────────────

class TestBasicBanking:
    def test_basic_banked_out_by_default(self):
        emu = C64Emu()
        # CSE default ($36) has LORAM=0; $A000-$BFFF is RAM.
        emu._mem.ram[0xA000] = 0x5A
        assert emu.memory[0xA000] == 0x5A

    def test_basic_mapped_when_loram_set(self):
        basic = _rom("basic_cbm.bin")
        if basic is None:
            pytest.skip("basic_cbm.bin not present")
        emu = C64Emu()
        emu.memory[0x01] = 0x37      # LORAM + HIRAM + CHAREN all on
        assert emu.memory[0xA000] == basic[0]
        assert emu.memory[0xBFFF] == basic[0x1FFF]

    def test_basic_needs_hiram_too(self):
        """LORAM alone doesn't enable BASIC — HIRAM is also required."""
        basic = _rom("basic_cbm.bin")
        if basic is None:
            pytest.skip("basic_cbm.bin not present")
        emu = C64Emu()
        emu._mem.ram[0xA000] = 0x42
        emu.memory[0x01] = 0x35      # LORAM=1, HIRAM=0, CHAREN=1
        assert emu.memory[0xA000] == 0x42    # RAM, not BASIC


# ── CHAREN (character ROM) ────────────────────────────────────────────

class TestChargenBanking:
    def test_io_visible_by_default(self):
        emu = C64Emu()
        # CSE default ($36) has CHAREN=1; $D000-$DFFF is I/O (RAM
        # in the emulator, since we don't model VIC/SID/CIA registers
        # as overlays — just passive RAM).
        emu._mem.ram[0xD020] = 0x77
        assert emu.memory[0xD020] == 0x77

    def test_chargen_mapped_when_charen_clear(self):
        chargen = _rom("chargen_cbm.bin")
        if chargen is None:
            pytest.skip("chargen_cbm.bin not present")
        emu = C64Emu()
        emu.memory[0x01] = 0x32      # HIRAM=1, CHAREN=0, LORAM=0
        assert emu.memory[0xD000] == chargen[0]
        assert emu.memory[0xDFFF] == chargen[0x0FFF]

    def test_chargen_needs_hiram(self):
        chargen = _rom("chargen_cbm.bin")
        if chargen is None:
            pytest.skip("chargen_cbm.bin not present")
        emu = C64Emu()
        emu._mem.ram[0xD000] = 0x99
        emu.memory[0x01] = 0x30      # HIRAM=0, CHAREN=0
        assert emu.memory[0xD000] == 0x99    # RAM, not CHARGEN


# ── DDR gating on $00/$01 ─────────────────────────────────────────────

class TestCpuPortDdr:
    def test_ddr_latched_read(self):
        """$00 reads return the latched DDR (no gating on $00 itself)."""
        emu = C64Emu()
        emu.memory[0x00] = 0xAB
        assert emu.memory[0x00] == 0xAB

    def test_output_bit_read_returns_latched(self):
        """Bits configured as output (DDR=1) return the latched $01 value."""
        emu = C64Emu()
        emu.memory[0x00] = 0xFF          # all output
        emu.memory[0x01] = 0x5A
        assert emu.memory[0x01] == 0x5A

    def test_input_bit_read_returns_external(self):
        """Bits configured as input (DDR=0) return external pin state."""
        emu = C64Emu()
        emu.memory[0x00] = 0x00          # all input
        emu.memory[0x01] = 0x00          # latched doesn't matter
        assert emu.memory[0x01] == BankedMemory_DEFAULT_EXTERNAL()

    def test_mixed_ddr(self):
        """Typical C64 DDR ($2F): bits 0-3, 5 output, bits 4, 6, 7 input."""
        emu = C64Emu()
        emu.memory[0x00] = 0x2F
        emu.memory[0x01] = 0x00          # all latched bits zero
        # output bits (0-3, 5) → 0; input bits (4, 6, 7) → external
        # Default external = $17 = bits 0, 1, 2, 4.  Only bit 4 is an input.
        # So result bits: 0-3 from latched (0), 4 from external (1),
        # 5 from latched (0), 6-7 from external (0, 0).
        # Expected: bit 4 = 1 → $10.
        assert emu.memory[0x01] == 0x10


# ── BankedMemory latches follow $01 writes ──────────────────────────

class TestBankingLatches:
    def test_latches_update_on_write(self):
        emu = C64Emu()
        emu.memory[0x01] = 0x37
        assert emu._mem.loram  is True
        assert emu._mem.hiram  is True
        assert emu._mem.charen is True

        emu.memory[0x01] = 0x30
        assert emu._mem.loram  is False
        assert emu._mem.hiram  is False
        assert emu._mem.charen is False


def BankedMemory_DEFAULT_EXTERNAL():
    """Import-time hoist so the test stays terse."""
    from c64emu import BankedMemory
    return BankedMemory.DEFAULT_EXTERNAL_01
