#!/usr/bin/env python3
"""find_m65_rom.py — copy the MEGA65 ROM from xmega65's data into rom/.

Owner: doc/build_system.md

The m65 counterpart of copying the C64 ROMs from VICE: looks in
xmega65's data directory (tests/xmega65.py's xemu_dir()) for
MEGA65.ROM, then hdos/MEGA65.ROM, accepts only a 128 KB image with a
C65/MEGA65 KERNAL, and copies it to rom/mega65.rom (gitignored: the
ROM cannot be redistributed), replacing a stale copy
([build_system.md § MEGA65 ROM](../doc/build_system.md#mega65-rom)).

    python dev/find_m65_rom.py          # or: make m65-rom

dev/capture_m65_state.py runs install() before recording and
check_booted() on the ROM xmega65 booted.  rom/mega65_open.rom, the
committed MEGA65 Open ROMs build, is pinned here (OPEN_ROM_SHA256;
its source is in rom/README.md); it has no native mode, so
check_native() refuses it.
"""
import hashlib
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from xmega65 import xemu_dir                      # noqa: E402

TARGET = ROOT / "rom" / "mega65.rom"
OPEN_ROM = ROOT / "rom" / "mega65_open.rom"
OPEN_ROM_SHA256 = "430e64de736d590b26c3314a65627e5ea366a5bf596f2d935e7a041828784422"

ROM_SIZE = 0x20000
NAMES = ("MEGA65.ROM", "hdos/MEGA65.ROM")
_C65_VECTORS = slice(0x1FFFA, 0x20000)          # $3FFFA-$3FFFF, bank 3


class RomNotFound(FileNotFoundError):
    """No acceptable MEGA65 ROM in xmega65's data directory."""


class NotAMega65Rom(ValueError):
    """An image that is not a full MEGA65 ROM."""


class RomMismatch(RuntimeError):
    """xmega65 booted a different ROM than rom/mega65.rom."""


def rom_version(data):
    """The version string: `V9xxxxx` at $16 (MEGA65 ROMs) or
    `Oyymmddhh` at $10 (Open ROMs); "unknown" otherwise."""
    for off, pattern in ((0x16, rb"V9\d{5}"), (0x10, rb"O\d{8}")):
        m = re.match(pattern, data[off:off + 16])
        if m:
            return m.group().decode()
    return "unknown"


def describe(data):
    return f"{rom_version(data)} (sha256 {hashlib.sha256(data).hexdigest()[:12]})"


def check_native(data):
    """Refuse anything but a 128 KB image with a C65/MEGA65 KERNAL."""
    if len(data) != ROM_SIZE:
        raise NotAMega65Rom(f"{len(data)} bytes, not {ROM_SIZE}")
    if not any(data[_C65_VECTORS]):
        raise NotAMega65Rom("no C65/MEGA65 KERNAL (the vectors at $3FFFA are zero)")


def find(directory):
    """The first acceptable ROM in xmega65's data `directory`:
    (path, data)."""
    searched = []
    for name in NAMES:
        path = pathlib.Path(directory) / name
        if not path.is_file():
            searched.append(f"  {path}: absent")
            continue
        data = path.read_bytes()
        try:
            check_native(data)
        except NotAMega65Rom as e:
            searched.append(f"  {path}: {e}")
            continue
        return path, data
    raise RomNotFound("no MEGA65 ROM found; searched:\n" + "\n".join(searched)
                      + "\nInstall xmega65 and its MEGA65 ROM, or set "
                        "XEMU_MEGA65_DIR to the directory that holds MEGA65.ROM.")


def install(target=TARGET, directory=None):
    """Copy the ROM found to `target` unless it is there already:
    (source, data, whether `target` changed)."""
    source, data = find(xemu_dir() if directory is None else directory)
    target = pathlib.Path(target)
    if target.is_file() and target.read_bytes() == data:
        return source, data, False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return source, data, True


def check_booted(rom, target=TARGET):
    """Refuse a booted ROM image that is not `target`."""
    want = pathlib.Path(target).read_bytes()
    if rom != want:
        raise RomMismatch(
            f"xmega65 booted ROM {describe(rom)}, but {target} is "
            f"{describe(want)}: the SD image's MEGA65.ROM differs from "
            "the one in xmega65's data directory")


def main():
    try:
        source, data, changed = install()
    except RomNotFound as e:
        print(e, file=sys.stderr)
        return 1
    print(f"MEGA65 ROM {describe(data)} from {source}, "
          f"{'copied to' if changed else 'already in'} {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
