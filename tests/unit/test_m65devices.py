"""test_m65devices.py — M65Emu's keyboard queue and CIA1 matrix port.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier U.  The keyboard queue follows xemu's source (the monitor cannot
type a key, so there is no recording); the CIA1 matrix port reads "no
key held".  Also: claimed registers leave the unmodelled-I/O log, and
devices claim only their own registers.  GETIN on the real KERNAL is
in tests/integration/test_m65emu.py.
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


def test_cia1_matrix_reads_no_key_held(emu):
    mem = emu.memory
    for row in (0xFF, 0x00, 0xFE, 0x7F):
        mem[0xDC00] = row
        assert mem[0xDC01] == 0xFF
    assert mem[0xDC00] == 0x7F                        # port A reads back


def test_claimed_registers_leave_the_unmodelled_log(emu):
    mem = emu.memory
    mem.io_log.clear()
    _ = mem[0xD610], mem[0xD619], mem[0xD60A], mem[0xD611], mem[0xDC01]
    mem[0xDC00] = 0xFE
    assert not mem.io_log
    _ = mem[0xD612], mem[0xDC02]                      # beside them: unclaimed
    assert set(mem.io_log) == {"R $D612", "R $DC02"}


def test_attach_refuses_an_overlap():
    emu = M65Emu()
    with pytest.raises(ValueError):
        emu.memory.attach(emu.memory.devices[0], 0x700, 0x701)
