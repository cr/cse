"""test_open_roms.py — the committed C64 Open ROMs are the pinned upstream files.

Owner: doc/build_system.md

Contract source: [rom/README.md § Open ROMs, C64 build](../../rom/README.md).

Tier U, static.  `rom/kernal_mega.bin`, `basic_mega.bin` and
`chargen_mega.bin` (the `ROMSET=mega` set) are the generic (C64)
build of github.com/MEGA65/open-roms — `bin/kernal_generic.rom` and
`bin/basic_generic.rom` at 5192c683, `bin/chargen_pxlfont_2.3.rom`
at b9661811.  The MEGA65 image, `rom/mega65_open.rom`, is pinned in
test_find_m65_rom.py.
"""

import hashlib
import pathlib

import pytest

ROM = pathlib.Path(__file__).resolve().parents[2] / "rom"

PINNED = {
    "kernal_mega.bin": "88e86ed3d0c710edab8f90ad146faa8de1ead11f43494b176c7b54724ca721c6",
    "basic_mega.bin": "54a1464b4b27c9dc61bbd62a818fdd12ec99af9089111005a5add0ad0e6bd5ec",
    "chargen_mega.bin": "bc5ed24e8e694543f0229800d050acff86d9674aec6dbd95055a26e824d8a395",
}


@pytest.mark.parametrize("name", sorted(PINNED))
def test_the_c64_open_rom_is_the_pinned_upstream_file(name):
    data = (ROM / name).read_bytes()
    assert hashlib.sha256(data).hexdigest() == PINNED[name]


def test_the_c64_open_kernal_is_a_c64_kernal():
    """Its hardware vectors are those of a C64 KERNAL at $E000: NMI,
    RESET and IRQ all point into the KERNAL's own 8 K."""
    data = (ROM / "kernal_mega.bin").read_bytes()
    vectors = [data[o] | data[o + 1] << 8 for o in (0x1FFA, 0x1FFC, 0x1FFE)]
    assert all(0xE000 <= v <= 0xFFFF for v in vectors), [hex(v) for v in vectors]
