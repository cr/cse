"""
test_dasm_rom.py — dasm_insn against KERNAL ROM ($E000-$FFFF).

Pre-fix bug: dasm_insn banks KERNAL out before reading any byte
from the user's address (so its internal tables under KERNAL ROM
are accessible).  When the user disassembles `$E000+`, the read
falls through to the RAM under KERNAL — typically all $00 ($FF
near reset) — so every instruction comes out as "BRK" or "...".

Fix (commit landing this test): dasm_insn snapshots 3 bytes from
the user's address into a local buffer BEFORE banking out, using
whatever bank state the caller had in force.  At the REPL prompt
that's KERNAL-in (so `d $E000` sees ROM); inside an asm_assemble
batch that's KERNAL-out (so user RAM under KERNAL is what the
user wrote) — either way, the user's "current view" of memory
is what gets disassembled.

Uses C64Emu with the real C64 KERNAL ROM at $E000-$FFFF.
"""

import pytest
from c64emu import C64Emu


def _emu(cse_prg):
    prg, map_path = cse_prg
    e = C64Emu()
    e.load_prg(prg, map_path)
    e.init_cse()
    return e


def _disassemble(emu, addr):
    """Run dasm_insn at `addr`, return (length, mnemonic-string)."""
    emu.jsr(emu.sym("dasm_insn"), a=addr & 0xFF, x=addr >> 8)
    length = emu.a
    buf = emu.sym("dasm_buf")
    out = []
    for i in range(24):
        b = emu.memory[buf + i]
        if b == 0:
            break
        out.append(b)
    text = bytes(out).decode("latin-1")
    return length, text


# Known KERNAL ROM bytes at well-defined entry points.  These are
# stable across all stock C64 KERNAL revisions.
ROM_CASES = [
    # (addr, expected_first_byte, must-not-disassemble-as)
    (0xE000, 0x85, "BRK"),    # KERNAL start: STA $56 (zp store)
    (0xFF8A, 0x4C, "BRK"),    # RESTOR vector: JMP $FD15
    (0xFFD2, 0x6C, "BRK"),    # CHROUT (BSOUT) vector: JMP ($0326)
    (0xFFE4, 0x6C, "BRK"),    # GETIN vector: JMP ($032A)
    (0xFFFC, 0x00, None),     # RESET vector low byte (0xFC = $FCE2 lo) —
                              # actually a data byte; skip mnemonic check
                              # here, only verify non-zero bytes were read.
]


class TestDasmKernalRom:
    """dasm_insn must read from the user's view of memory.  At the
    REPL prompt the user's view of $E000+ is KERNAL ROM, so
    disassembly must match the ROM contents — not the underlying
    RAM (which is typically $00, producing endless "BRK")."""

    @pytest.mark.parametrize("addr,first_byte,must_not_be",
                             [c for c in ROM_CASES if c[2] is not None],
                             ids=[f"${c[0]:04X}" for c in ROM_CASES
                                  if c[2] is not None])
    def test_kernal_rom_disassembles_to_real_instructions(
            self, cse_prg, addr, first_byte, must_not_be):
        emu = _emu(cse_prg)

        # Sanity: confirm the ROM byte is what we expect (this is
        # really a stability check on the test's reference values
        # against the loaded KERNAL ROM image).
        assert emu.memory[addr] == first_byte, \
            f"KERNAL ROM at ${addr:04X} = " \
            f"${emu.memory[addr]:02X}, expected ${first_byte:02X}"

        length, text = _disassemble(emu, addr)
        assert length >= 1, f"zero-length disassembly at ${addr:04X}"
        # Pre-fix all of these would come back as "BRK ".
        assert not text.startswith(must_not_be), \
            f"dasm at ${addr:04X} produced '{text}' — looks like the " \
            f"pre-fix RAM-under-KERNAL bug (all $00 → BRK)"

    def test_e000_specific_mnemonic(self, cse_prg):
        """$E000 starts with $85 (sta zp $56) on stock C64 KERNAL.
        Pin the exact disassembly so any future regression in the
        ROM-read fix is obvious in the failure message."""
        emu = _emu(cse_prg)
        length, text = _disassemble(emu, 0xE000)
        assert length == 2, f"length {length}, expected 2"
        assert text == "STA $56", f"got '{text}', expected 'STA $56'"

    def test_ffd2_chrout_indirect_jump(self, cse_prg):
        """$FFD2 is the BSOUT/CHROUT vector: JMP ($0326).  Confirms
        the snapshot covers all 3 bytes, not just the opcode."""
        emu = _emu(cse_prg)
        length, text = _disassemble(emu, 0xFFD2)
        assert length == 3, f"length {length}, expected 3"
        assert text == "JMP ($0326)", f"got '{text}', expected 'JMP ($0326)'"

    def test_ram_under_kernal_still_works(self, cse_prg):
        """Sanity: disassembly of plain RAM (e.g. $3000) still works
        — the fix didn't break the non-ROM path."""
        emu = _emu(cse_prg)
        # Place LDA #$42 (2 bytes: $A9 $42) at $3000.
        emu.memory[0x3000] = 0xA9
        emu.memory[0x3001] = 0x42
        length, text = _disassemble(emu, 0x3000)
        assert length == 2
        assert text == "LDA #$42", f"got '{text}'"
