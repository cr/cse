"""test_xmega65.py — the xmega65 driver's pure parts (Tier U).

Owner: doc/build_system.md

Contract source: [doc/testing.md § Tier X](../../doc/testing.md#tier-x--xmega65-m65-automated).

A wanted ROM goes onto the SD clone's FAT partition: its byte offset
comes from the clone's MBR.  Starting xmega65 itself is Tier X.
"""

import struct

import pytest

from xmega65 import fat_partition_offset, start_args


def mbr(*parts):
    """An MBR with (type, first LBA) entries."""
    data = bytearray(512)
    for i, (kind, lba) in enumerate(parts):
        entry = 0x1BE + 16 * i
        data[entry + 4] = kind
        data[entry + 8:entry + 12] = struct.pack("<I", lba)
    data[510:512] = b"\x55\xAA"
    return bytes(data)


def test_the_fat_partition_is_found_by_its_type():
    assert fat_partition_offset(mbr((0x0C, 2048), (0x41, 4196352))) == 2048 * 512
    assert fat_partition_offset(mbr((0x41, 8), (0x0B, 64))) == 64 * 512


def test_no_fat_partition_is_refused():
    with pytest.raises(ValueError, match="FAT"):
        fat_partition_offset(mbr((0x41, 8)))
    with pytest.raises(ValueError, match="MBR"):
        fat_partition_offset(bytes(512))


def test_start_args_are_headless_with_the_rom_and_prg_options():
    base = start_args()
    assert "-headless" in base and "-romfromsd" not in base
    assert start_args(rom=True)[-1] == "-romfromsd"
    assert start_args(prg="p.prg")[-4:] == ["-prg", "p.prg", "-prgmode", "65"]
    assert start_args(d81="d.d81")[-3:] == ["-8", "d.d81", "-autoload"]


def test_the_addkey_driver_keeps_the_registers_and_returns():
    from xmega65 import addkey_driver
    code = addkey_driver(b"AB", 0x1234)
    assert code[:10] == [0x08, 0x48, 0xDA, 0x5A, 0xDB, 0x7B, 0x48, 0xA9, 0x00, 0x5B]
    assert code[10:20] == [0xA9, 0x41, 0x20, 0x4A, 0xFF, 0xA9, 0x42, 0x20, 0x4A, 0xFF]
    assert code[-3:] == [0x4C, 0x34, 0x12]


class _FakeMonitor:
    """The monitor socket: each line sent gets the next canned reply."""

    def __init__(self, replies):
        self.replies, self.sent = list(replies), []

    def sendall(self, data):
        self.sent.append(data)

    def recv(self, n):
        return self.replies.pop(0)


_HEAD = (b"\r\nPC   A  X  Y  Z  B  SP   MAPH MAPL LAST-OP In     P  P-FLAGS"
         b"   RGP uS IO ws h RECA8LHC\r\n")


def _dump(pc, b):
    return _HEAD + (f"{pc:04X} 1F E3 00 B3 {b:02X} 01F1 B300 E300 00       24 ..E..I.. "
                    f"\r\n").encode()


def test_run_to_at_hit_returns_the_registers_of_the_hit_report():
    """The CPU runs one more instruction after the hit (here: a BRK),
    so `at_hit` reads the registers the hit reported."""
    from xmega65 import XMega65, _PROMPT
    xm = XMega65.__new__(XMega65)
    xm.sock = _FakeMonitor([b"\r\n.\r\n",                       # b 2000
                            _dump(0x2000, 0x1F),                # the hit
                            _dump(0xE1C0, 0x00) + _PROMPT,      # t1
                            _dump(0xE1C0, 0x00) + _PROMPT])     # r
    r = xm.run_to(0x2000, at_hit=True)
    assert (r["pc"], r["b"], r["sp"], r["mapl"], r["maph"]) == \
        (0x2000, 0x1F, 0x01F1, 0xE300, 0xB300)
