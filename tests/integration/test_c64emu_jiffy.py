"""test_c64emu_jiffy.py — the jiffy tick on the C64 KERNAL.

Owner: doc/build_system.md

Contract source: [doc/testing.md § C64Emu](../../doc/testing.md#c64emu--emulator-class).

The tick's contracts (interval, re-scheduling, the I flag, disable,
the default interval) hold for both harnesses and are tested in
test_emu_parity.py.  This file keeps the C64 end-to-end case: with
the CSE build loaded and I=0, the real KERNAL IRQ handler ticks
$A0-$A2.
"""

from c64emu import C64Emu


USER_LOOP = 0x3000


def _install_user_loop(emu, loop_addr=USER_LOOP):
    """JMP self — CPU spins here indefinitely; IRQ interrupts it."""
    emu.memory[loop_addr]     = 0x4C       # JMP
    emu.memory[loop_addr + 1] = loop_addr & 0xFF
    emu.memory[loop_addr + 2] = (loop_addr >> 8) & 0xFF


# ── End-to-end via real KERNAL tick ──────────────────────────────

def test_jiffy_increments_kernal_clock(cse_prg):
    """With the real PRG loaded and its IRQ path active, jiffy IRQs
    should cause the KERNAL's $EA31 handler to tick the jiffy
    counter at $A0-$A2.

    CSE's $0316/$FFFE vectors route through cse_brk_handler — which
    classifies IRQs (B=0) and delegates to the KERNAL's $EA31 path
    via bank_out_stub.  This test exercises that whole chain."""
    prg, map_path = cse_prg
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.init_cse()
    # Jiffy counter bytes (KERNAL ZP).
    for i in range(3):
        emu.memory[0xA0 + i] = 0

    emu.enable_jiffy_clock(interval=2000)
    # Run a userland loop.
    _install_user_loop(emu)
    emu._cpu.p &= ~emu._cpu.INTERRUPT
    emu._cpu.pc = USER_LOOP
    emu.run_steps(20000)

    # 24-bit jiffy counter should have advanced.
    jiffy = (
        emu.memory[0xA0] << 16
        | emu.memory[0xA1] << 8
        | emu.memory[0xA2]
    )
    assert jiffy > 0, f"jiffy counter didn't advance (${jiffy:06X})"
