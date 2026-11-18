"""test_c64emu_interrupts.py — C64Emu's interrupt vector fetch.

Owner: doc/build_system.md

Contract source: [doc/testing.md § C64Emu](../../doc/testing.md#c64emu--emulator-class).

The scheduler's contracts (the I flag, NMI, the pushed frame, cancel)
hold for both harnesses and are tested in test_emu_parity.py.  This
file keeps the C64-only case: the vector is fetched through
BankedMemory (the bank-out-stub path that Phase 18's
cse_brk_handler_early handles — the stress-test gap the testing.md
Principle 7 cautionary example calls for).
"""

from c64emu import C64Emu


# A tiny user program in RAM we can interrupt.
USER_CODE = 0x3000
IRQ_HANDLER = 0x3100
NMI_HANDLER = 0x3200

# A landing pad we can run-until after the handler completes.
DONE_ADDR = 0xDFE0     # in the I/O gap CSE never executes


def _setup_self_contained(emu):
    """Install bare IRQ/NMI vectors + a minimal user program that
    loops forever until an interrupt hits.

    The user loop sits at USER_CODE:  JMP USER_CODE (3 bytes).
    Each handler increments a witness counter then RTIs back.
    """
    # User program: infinite JMP self.
    emu.memory[USER_CODE]     = 0x4C      # JMP
    emu.memory[USER_CODE + 1] = USER_CODE & 0xFF
    emu.memory[USER_CODE + 2] = (USER_CODE >> 8) & 0xFF

    # IRQ handler: INC $2000 ; RTI
    emu.memory[IRQ_HANDLER]     = 0xEE    # INC abs
    emu.memory[IRQ_HANDLER + 1] = 0x00
    emu.memory[IRQ_HANDLER + 2] = 0x20
    emu.memory[IRQ_HANDLER + 3] = 0x4C    # JMP DONE
    emu.memory[IRQ_HANDLER + 4] = DONE_ADDR & 0xFF
    emu.memory[IRQ_HANDLER + 5] = (DONE_ADDR >> 8) & 0xFF

    # NMI handler: INC $2001 ; JMP DONE
    emu.memory[NMI_HANDLER]     = 0xEE    # INC abs
    emu.memory[NMI_HANDLER + 1] = 0x01
    emu.memory[NMI_HANDLER + 2] = 0x20
    emu.memory[NMI_HANDLER + 3] = 0x4C    # JMP DONE
    emu.memory[NMI_HANDLER + 4] = DONE_ADDR & 0xFF
    emu.memory[NMI_HANDLER + 5] = (DONE_ADDR >> 8) & 0xFF

    # Install vectors.  Writes pass through banking to RAM under
    # KERNAL, so we need to bank KERNAL out first... or write into
    # the RAM shadow by toggling HIRAM.  Easiest: temporarily bank
    # out, write, bank back in.
    emu.memory[0x01] = 0x34   # HIRAM=0
    emu.memory[0xFFFE] = IRQ_HANDLER & 0xFF
    emu.memory[0xFFFF] = (IRQ_HANDLER >> 8) & 0xFF
    emu.memory[0xFFFA] = NMI_HANDLER & 0xFF
    emu.memory[0xFFFB] = (NMI_HANDLER >> 8) & 0xFF
    emu.memory[0x01] = 0x36   # HIRAM=1 back

    # Clear witness counters.
    emu.memory[0x2000] = 0
    emu.memory[0x2001] = 0

    # Ensure banking is OUT when we run — so the vector fetch goes
    # to our RAM shadow, not KERNAL ROM.
    emu.memory[0x01] = 0x34


# ── Vector fetch respects banking ─────────────────────────────────

def test_vector_fetched_from_ram_when_kernal_banked_out():
    """IRQ fired with KERNAL banked out should read $FFFE from RAM
    (the CSE-style vector shadow), not from KERNAL ROM.

    This is the class of test that would have caught the Phase 18
    bank-out-stub bugs."""
    emu = C64Emu()
    _setup_self_contained(emu)
    emu._cpu.p &= ~emu._cpu.INTERRUPT
    # KERNAL banked out already per _setup.
    assert emu._mem.hiram is False, "precondition: KERNAL out"
    emu.schedule_irq(2)
    emu._cpu.pc = USER_CODE
    emu.run_until(DONE_ADDR, max_cycles=1000)
    assert emu.memory[0x2000] == 1       # IRQ landed on our RAM-shadow handler
