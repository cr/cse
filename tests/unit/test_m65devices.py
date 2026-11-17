"""test_m65devices.py — M65Emu's keyboard queue, CIA ports, VIC latch.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier U.  The keyboard queue follows xemu's source (the monitor cannot
type a key, so there is no recording); `inject_key()` queues one key.
The CIA1 matrix port reads the shared key matrix through port A's
column selection; the VIC interrupt latch ($D019) holds what the
jiffy tick raised until the KERNAL writes 1s back; the CIA2 interrupt
control register ($DD0D) holds RESTORE until read.  Also: claimed
registers leave the unmodelled-I/O log, and devices claim only their
own registers.  The matrix calls themselves are in
test_emu_parity.py; GETIN, STOP and RESTORE on the real KERNAL in
tests/integration/test_m65emu.py.
"""

import pytest

from m65emu import M65Emu
from m65emu.memory import VIC4


@pytest.fixture
def emu():
    emu = M65Emu()
    emu.memory.restore(ddr=0xFF, port=0x35, d030=0x00, io_mode=VIC4)
    return emu


def test_empty_queue(emu):
    mem = emu.memory
    assert (mem[0xD610], mem[0xD619], mem[0xD60A], mem[0xD611]) == (0, 0xFF, 0, 0)


def test_injected_keys_queue_in_order(emu):
    mem = emu.memory
    emu.inject_keys(b"A\r")
    assert (mem[0xD619], mem[0xD60A] & 0x80) == (0x41, 0x80)
    assert mem[0xD610] != 0                           # a key is waiting
    mem[0xD619] = 0                                   # dequeue
    assert mem[0xD619] == 0x0D
    mem[0xD610] = 0                                   # dequeue, too
    assert (mem[0xD610], mem[0xD619], mem[0xD60A]) == (0, 0xFF, 0)


def test_ascii_of_injected_petscii(emu):
    mem = emu.memory
    for petscii, ascii_ in [(0x41, ord("a")), (0xC1, ord("A")), (0x31, ord("1")),
                            (0x0D, 0x0D), (0x20, 0x20)]:
        emu.inject_keys([petscii])
        assert mem[0xD610] == ascii_, hex(petscii)
        mem[0xD610] = 0


def test_flush_only_with_bit_7_clear(emu):
    mem = emu.memory
    emu.inject_keys(b"AB")
    mem[0xD60A] = 0x80
    assert mem[0xD619] == 0x41
    mem[0xD60A] = 0x00
    assert mem[0xD619] == 0xFF


def test_inject_key_queues_one_key_without_a_limit(emu):
    mem = emu.memory
    for _ in range(20):
        emu.inject_key(0x41)
    count = 0
    while mem[0xD619] != 0xFF:
        mem[0xD619] = 0
        count += 1
    assert count == 20


def test_cia1_matrix_port_reads_the_key_matrix(emu):
    mem = emu.memory
    for sel in (0xFF, 0x00, 0xFE, 0x7F):
        mem[0xDC00] = sel
        assert mem[0xDC01] == 0xFF
    assert mem[0xDC00] == 0x7F                        # port A reads back
    emu.press_stop()                                  # row 7, column 7
    assert mem[0xDC01] == 0x7F
    mem[0xDC00] = 0xFF                                # no column selected
    assert mem[0xDC01] == 0xFF


def test_vic_latch_holds_the_tick_until_acknowledged(emu):
    mem = emu.memory
    assert mem[0xD019] & 0x8F == 0
    emu.vic_irq.raise_(0x01)                          # what the tick does
    assert mem[0xD019] & 0x8F == 0x81                 # raster + any
    mem[0xD019] = 0x02                                # not that bit
    assert mem[0xD019] & 0x8F == 0x81
    mem[0xD019] = mem[0xD019]                         # the KERNAL's TSB
    assert mem[0xD019] & 0x8F == 0


def test_jiffy_tick_raises_the_vic_latch_once(emu):
    mem = emu.memory
    mem.load(0x3000, bytes([0x4C, 0x00, 0x30]))      # JMP self, I set
    emu.pc = 0x3000
    emu.cpu.p |= emu.cpu.INTERRUPT
    emu.enable_jiffy_clock(interval=100)
    run_for(emu, 99)
    assert mem[0xD019] & 0x01 == 0
    run_for(emu, 1)
    assert mem[0xD019] & 0x81 == 0x81
    mem[0xD019] = 0x01                                # acknowledged while held
    run_for(emu, 50)
    assert mem[0xD019] & 0x01 == 0                    # not raised again


def run_for(emu, steps):
    with pytest.raises(TimeoutError):
        emu.run_until(0xDFE0, max_cycles=steps)


def test_cia2_icr_holds_restore_until_read(emu):
    mem = emu.memory
    assert mem[0xDD0D] == 0
    emu.press_restore()
    assert mem[0xDD0D] == 0x10
    assert mem[0xDD0D] == 0


def test_claimed_registers_leave_the_unmodelled_log(emu):
    mem = emu.memory
    mem.io_log.clear()
    _ = mem[0xD610], mem[0xD619], mem[0xD60A], mem[0xD611], mem[0xDC01]
    _ = mem[0xD019], mem[0xDD0D]
    mem[0xDC00] = 0xFE
    mem[0xD019] = 0x0F
    assert not mem.io_log
    _ = mem[0xD612], mem[0xDC02]                      # beside them: unclaimed
    assert set(mem.io_log) == {"R $D612", "R $DC02"}


def test_attach_refuses_an_overlap():
    emu = M65Emu()
    with pytest.raises(ValueError):
        emu.memory.attach(emu.memory.devices[0], 0x700, 0x701)
