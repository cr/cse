"""test_disk.py — disk.s error paths on a C64 with no drive.

Owner: doc/modules/disk.md

Contract source: [disk.md § Design](../../doc/modules/disk.md#design)
(no file left open).  C64Emu models an empty serial bus
([testing.md § C64Emu](../../doc/testing.md#c64emu--emulator-class)), so
every KERNAL OPEN / LOAD on device 8 fails with "device not present" —
the paths a missing or switched-off drive takes.  Successful transfers
need a virtual IEC disk (TODO § C64Emu extension roadmap) and stay
manual (VICE).
"""

import pytest
from c64emu import C64Emu

LDTND = 0x98          # KERNAL: number of open logical files
NAME = 0x3000
RTS_STUB = 0x2F00     # callback for the SEQ calls (never reached)


@pytest.fixture
def emu(cse_prg):
    prg, map_path = cse_prg
    e = C64Emu()
    e.load_prg(prg, map_path)
    e.init_cse()
    e.memory[e.sym("cur_device")] = 8
    for i, c in enumerate(b"FOO\0"):
        e.memory[NAME + i] = c
    e.write_word(e.sym("disk_ptr"), NAME)
    e.memory[RTS_STUB] = 0x60
    return e


def _save_prg(e):
    e.write_word(e.sym("_io_tmp"), 0x4000)
    e.jsr(e.sym("disk_save_prg"), a=4, x=0)


def _save_seq(e):
    e.jsr(e.sym("disk_save_seq"), a=RTS_STUB & 0xFF, x=RTS_STUB >> 8)


def _load_seq(e):
    e.jsr(e.sym("disk_load_seq"), a=RTS_STUB & 0xFF, x=RTS_STUB >> 8)


def _load_prg(e):
    e.jsr(e.sym("disk_load_prg"), a=0, x=0x40)


@pytest.mark.parametrize("call,err_ax", [(_save_prg, (1, 0)), (_save_seq, (1, 0)),
                                         (_load_seq, (1, 0)), (_load_prg, (0, 0))],
                         ids=["save_prg", "save_seq", "load_seq", "load_prg"])
def test_failed_open_leaves_no_file_open(emu, call, err_ax):
    """Device not present: the call returns its error code and the
    KERNAL's file table is empty afterwards (OPEN keeps the entry when
    the device fails; disk.s must close it, on the file's own LFN)."""
    call(emu)
    assert (emu.a, emu.x) == err_ax
    assert emu.memory[LDTND] == 0


@pytest.mark.parametrize("call", [_save_prg, _save_seq, _load_seq],
                         ids=["save_prg", "save_seq", "load_seq"])
def test_second_attempt_fails_for_the_same_reason(emu, call):
    """After a failed call the next one reaches the drive again
    (ST = device not present), not a stale "file open" refusal."""
    call(emu)
    emu.memory[0x90] = 0
    call(emu)
    assert emu.memory[0x90] & 0x80
    assert emu.memory[LDTND] == 0


def test_status_with_no_drive_returns_an_empty_status(emu):
    """floppy_read_status must not hang when no drive answers: the
    KERNAL's CHKIN on a missing serial device waits forever in its
    talk turnaround, so the drive is probed first.  fl_buf is empty
    and no file is left open."""
    fl_buf = emu.sym("fl_buf")
    emu.memory[fl_buf] = 0x41                   # stale content
    emu.jsr(emu.sym("floppy_read_status"), max_cycles=200_000)
    assert emu.memory[fl_buf] == 0
    assert emu.memory[LDTND] == 0
