"""test_c64emu_jiffy.py — repeating jiffy-clock IRQ contracts.

Verifies that enable_jiffy_clock() schedules a repeating IRQ that:
  * fires at the requested interval (first fire after N cycles);
  * re-schedules itself after each fire;
  * respects the I flag (deferred while masked);
  * stops firing after disable_jiffy_clock().

With the default CSE builds loaded + I=0, a real KERNAL IRQ handler
would tick $A0-$A2.  We verify that end-to-end too.
"""

import pytest
from c64emu import C64Emu


USER_LOOP = 0x3000
IRQ_HANDLER = 0x3100
TICK_ADDR = 0x2000   # witness byte the test handler increments


def _install_tick_handler(emu, irq_handler=IRQ_HANDLER, witness=TICK_ADDR):
    """A tiny IRQ handler that bumps a witness byte and RTIs."""
    emu.memory[irq_handler]     = 0xEE     # INC abs
    emu.memory[irq_handler + 1] = witness & 0xFF
    emu.memory[irq_handler + 2] = (witness >> 8) & 0xFF
    emu.memory[irq_handler + 3] = 0x40     # RTI
    # Install $FFFE vector.  Bank out KERNAL to hit the RAM shadow.
    emu.memory[0x01] = 0x34
    emu.memory[0xFFFE] = irq_handler & 0xFF
    emu.memory[0xFFFF] = (irq_handler >> 8) & 0xFF
    emu.memory[0x01] = 0x34                # stay out so vector reads RAM


def _install_user_loop(emu, loop_addr=USER_LOOP):
    """JMP self — CPU spins here indefinitely; IRQ interrupts it."""
    emu.memory[loop_addr]     = 0x4C       # JMP
    emu.memory[loop_addr + 1] = loop_addr & 0xFF
    emu.memory[loop_addr + 2] = (loop_addr >> 8) & 0xFF


# ── Jiffy timer basics ──────────────────────────────────────────

def test_jiffy_fires_once_per_interval():
    emu = C64Emu()
    _install_tick_handler(emu)
    _install_user_loop(emu)
    emu._cpu.p &= ~emu._cpu.INTERRUPT

    emu.enable_jiffy_clock(interval=1000)
    emu._cpu.pc = USER_LOOP
    emu.memory[TICK_ADDR] = 0

    # Run for 5000 cycles — expect ~5 ticks.
    try:
        emu.run_until(0xDFE0, max_cycles=5000)
    except TimeoutError:
        pass

    ticks = emu.memory[TICK_ADDR]
    assert 4 <= ticks <= 6, \
        f"expected ~5 ticks in 5000 cycles @ 1000-cycle interval, got {ticks}"


def test_jiffy_reschedules_automatically():
    """A repeating IRQ, not a one-shot: after first fire, next fire
    is scheduled `interval` cycles later, not "one step later"."""
    emu = C64Emu()
    _install_tick_handler(emu)
    _install_user_loop(emu)
    emu._cpu.p &= ~emu._cpu.INTERRUPT

    emu.enable_jiffy_clock(interval=500)
    emu._cpu.pc = USER_LOOP
    emu.memory[TICK_ADDR] = 0
    try:
        emu.run_until(0xDFE0, max_cycles=2500)
    except TimeoutError:
        pass
    # 2500 / 500 = 5 expected firings.
    ticks = emu.memory[TICK_ADDR]
    assert 4 <= ticks <= 6, f"expected ~5 ticks, got {ticks}"


def test_jiffy_respects_i_flag():
    emu = C64Emu()
    _install_tick_handler(emu)
    _install_user_loop(emu)
    emu._cpu.p |= emu._cpu.INTERRUPT       # I=1 — mask IRQs

    emu.enable_jiffy_clock(interval=200)
    emu._cpu.pc = USER_LOOP
    emu.memory[TICK_ADDR] = 0
    try:
        emu.run_until(0xDFE0, max_cycles=2000)
    except TimeoutError:
        pass
    # No ticks while I=1.
    assert emu.memory[TICK_ADDR] == 0


def test_disable_stops_ticks():
    emu = C64Emu()
    _install_tick_handler(emu)
    _install_user_loop(emu)
    emu._cpu.p &= ~emu._cpu.INTERRUPT

    emu.enable_jiffy_clock(interval=500)
    emu._cpu.pc = USER_LOOP
    emu.memory[TICK_ADDR] = 0
    try:
        emu.run_until(0xDFE0, max_cycles=1200)
    except TimeoutError:
        pass
    ticks_before = emu.memory[TICK_ADDR]
    assert ticks_before >= 1

    emu.disable_jiffy_clock()
    # Run another 2000 cycles — no more ticks.
    try:
        emu.run_until(0xDFE0, max_cycles=2000)
    except TimeoutError:
        pass
    ticks_after = emu.memory[TICK_ADDR]
    assert ticks_after == ticks_before, \
        f"ticks bumped after disable: {ticks_before} → {ticks_after}"


def test_default_interval_matches_kernal():
    """Default interval is KERNAL's CIA1 Timer A RAM-init value."""
    emu = C64Emu()
    emu.enable_jiffy_clock()       # no arg → default
    assert emu._jiffy_interval == C64Emu.JIFFY_INTERVAL
    assert C64Emu.JIFFY_INTERVAL == 16421


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
    try:
        emu.run_until(0xDFE0, max_cycles=20000)
    except TimeoutError:
        pass

    # 24-bit jiffy counter should have advanced.
    jiffy = (
        emu.memory[0xA0] << 16
        | emu.memory[0xA1] << 8
        | emu.memory[0xA2]
    )
    assert jiffy > 0, f"jiffy counter didn't advance (${jiffy:06X})"
