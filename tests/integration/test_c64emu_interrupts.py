"""test_c64emu_interrupts.py — scheduled-IRQ / scheduled-NMI contracts.

Verifies that C64Emu.schedule_irq / schedule_nmi behave like real
6502 interrupts:

  * IRQ respects the I flag (deferred until CLI).
  * NMI fires unconditionally (edge-triggered).
  * Vector fetch goes through BankedMemory (the bank-out-stub path
    that Phase 18's cse_brk_handler_early handles — testing it here
    is exactly the stress-test gap the testing.md Principle 7
    cautionary example calls for).
  * Pushed frame: PCH, PCL, P (B=0), in that order.
"""

import pytest
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


# ── NMI edge-triggered ────────────────────────────────────────────

def test_nmi_fires_immediately():
    emu = C64Emu()
    _setup_self_contained(emu)
    emu.schedule_nmi(10)       # fire after 10 steps
    emu._cpu.pc = USER_CODE
    emu.run_until(DONE_ADDR, max_cycles=1000)
    assert emu.memory[0x2001] == 1       # NMI handler ran
    assert emu.memory[0x2000] == 0       # IRQ did not


def test_nmi_ignores_i_flag():
    """NMI fires even with I=1."""
    emu = C64Emu()
    _setup_self_contained(emu)
    emu._cpu.p |= emu._cpu.INTERRUPT     # set I
    emu.schedule_nmi(5)
    emu._cpu.pc = USER_CODE
    emu.run_until(DONE_ADDR, max_cycles=1000)
    assert emu.memory[0x2001] == 1


def test_nmi_one_shot():
    """Each schedule_nmi fires exactly once."""
    emu = C64Emu()
    _setup_self_contained(emu)
    emu.schedule_nmi(5)
    emu.schedule_nmi(10)       # second NMI queued
    emu._cpu.pc = USER_CODE
    emu.run_until(DONE_ADDR, max_cycles=1000)
    # First NMI handler ran; the second is still pending but user
    # code never reaches a CLI/RTI point before run_until exits.
    assert emu.memory[0x2001] == 1


# ── IRQ respects I flag ───────────────────────────────────────────

def test_irq_fires_when_i_clear():
    emu = C64Emu()
    _setup_self_contained(emu)
    emu._cpu.p &= ~emu._cpu.INTERRUPT    # clear I
    emu.schedule_irq(5)
    emu._cpu.pc = USER_CODE
    emu.run_until(DONE_ADDR, max_cycles=1000)
    assert emu.memory[0x2000] == 1       # IRQ handler ran


def test_irq_deferred_while_i_set():
    """IRQ pending with I=1 doesn't fire.  The loop runs to
    timeout without the handler ever executing."""
    emu = C64Emu()
    _setup_self_contained(emu)
    emu._cpu.p |= emu._cpu.INTERRUPT     # set I
    emu.schedule_irq(5)
    emu._cpu.pc = USER_CODE
    with pytest.raises(TimeoutError):
        emu.run_until(DONE_ADDR, max_cycles=500)
    assert emu.memory[0x2000] == 0       # handler never ran


def test_irq_fires_when_cli_clears_i():
    """Program does CLI after IRQ was scheduled; IRQ then fires."""
    # User code: SEI ; CLI ; JMP self
    cli_code = USER_CODE
    emu = C64Emu()
    _setup_self_contained(emu)
    emu.memory[cli_code]     = 0x78    # SEI
    emu.memory[cli_code + 1] = 0x58    # CLI
    emu.memory[cli_code + 2] = 0x4C    # JMP cli_code+2
    emu.memory[cli_code + 3] = (cli_code + 2) & 0xFF
    emu.memory[cli_code + 4] = ((cli_code + 2) >> 8) & 0xFF
    emu._cpu.pc = cli_code
    emu.schedule_irq(1)                # arms before CLI executes
    emu.run_until(DONE_ADDR, max_cycles=1000)
    assert emu.memory[0x2000] == 1


# ── Frame push shape ──────────────────────────────────────────────

def test_irq_push_frame_shape():
    """Verify PCH, PCL, P (B=0) are pushed on the stack."""
    emu = C64Emu()
    _setup_self_contained(emu)
    emu._cpu.p &= ~emu._cpu.INTERRUPT
    # Pre-set a known SP so we can read back the frame.
    emu._cpu.sp = 0xFF
    emu.schedule_irq(1)
    emu._cpu.pc = USER_CODE
    emu.run_until(DONE_ADDR, max_cycles=1000)
    # After handler's RTI (no, actually INC/JMP — no RTI.  Handler
    # leaves frame on stack.  SP should now be $FC: three bytes pushed.)
    assert emu._cpu.sp == 0xFC
    # Read frame: top-of-stack = P (B=0, I=1 from mask)
    p = emu.memory[0x0100 + 0xFD]
    assert (p & 0x10) == 0           # B clear
    # PCL, PCH = USER_CODE (the JMP self address).
    pcl = emu.memory[0x0100 + 0xFE]
    pch = emu.memory[0x0100 + 0xFF]
    pushed_pc = (pch << 8) | pcl
    assert pushed_pc == USER_CODE


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


# ── Cancel + reset ────────────────────────────────────────────────

def test_cancel_pending_drops_all():
    emu = C64Emu()
    _setup_self_contained(emu)
    emu.schedule_irq(5)
    emu.schedule_nmi(10)
    emu.cancel_pending_interrupts()
    emu._cpu.p &= ~emu._cpu.INTERRUPT
    emu._cpu.pc = USER_CODE
    with pytest.raises(TimeoutError):
        emu.run_until(DONE_ADDR, max_cycles=500)
    assert emu.memory[0x2000] == 0
    assert emu.memory[0x2001] == 0
