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
