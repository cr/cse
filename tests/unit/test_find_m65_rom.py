"""test_find_m65_rom.py — the MEGA65 ROM discovery and the Open ROM pin.

Owner: doc/build_system.md

Contract source: [doc/build_system.md § MEGA65 ROM](../../doc/build_system.md#mega65-rom),
[rom/README.md § MEGA65 ROMs](../../rom/README.md#mega65-roms).

Tier U: dev/find_m65_rom.py searches xmega65's data directory in a
fixed order, accepts only a 128 KB image with a C65/MEGA65 KERNAL,
copies it to rom/mega65.rom and keeps that copy current; the
snapshot recorder refuses a booted ROM that differs from it.  The
committed Open ROM is the pinned upstream build, and has no native
mode.  All on temporary directories: the user's xemu data is never
read.
"""

import hashlib
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import find_m65_rom as F                           # noqa: E402
from xmega65 import xemu_dir                       # noqa: E402

ROM_SIZE = 0x20000


def native_rom(version=b"V920421", fill=0x11):
    """A minimal acceptable image: a version at $16, C65 KERNAL vectors."""
    d = bytearray([fill]) * ROM_SIZE
    d[0x16:0x16 + len(version) + 1] = version + b"\x00"
    d[0x1FFFA:0x20000] = bytes([0xC1, 0xFA, 0x1A, 0xFB, 0xCE, 0xFA])
    return bytes(d)


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ── where xmega65 keeps its data ──────────────────────────────────

def test_the_environment_override_wins(tmp_path):
    assert xemu_dir({"XEMU_MEGA65_DIR": str(tmp_path)}, tmp_path / "home",
                    "darwin") == tmp_path


def test_macos_data_directory(tmp_path):
    assert xemu_dir({}, tmp_path, "darwin") == \
        tmp_path / "Library/Application Support/xemu-lgb/mega65"


def test_linux_data_directory(tmp_path):
    assert xemu_dir({}, tmp_path, "linux") == \
        tmp_path / ".local/share/xemu-lgb/mega65"
    assert xemu_dir({"XDG_DATA_HOME": str(tmp_path / "xdg")}, tmp_path,
                    "linux") == tmp_path / "xdg/xemu-lgb/mega65"


# ── finding and accepting a ROM ───────────────────────────────────

def test_top_level_rom_before_the_hdos_copy(tmp_path):
    put(tmp_path / "hdos/MEGA65.ROM", native_rom(fill=0x22))
    top = put(tmp_path / "MEGA65.ROM", native_rom(fill=0x33))
    assert F.find(tmp_path)[0] == top


def test_the_hdos_copy_when_there_is_no_top_level_rom(tmp_path):
    hdos = put(tmp_path / "hdos/MEGA65.ROM", native_rom())
    assert F.find(tmp_path) == (hdos, native_rom())


def test_an_unacceptable_rom_is_skipped_and_reported(tmp_path):
    put(tmp_path / "MEGA65.ROM", native_rom()[:0x10000])
    hdos = put(tmp_path / "hdos/MEGA65.ROM", native_rom())
    assert F.find(tmp_path)[0] == hdos
    (tmp_path / "hdos/MEGA65.ROM").unlink()
    with pytest.raises(F.RomNotFound, match="65536 bytes"):
        F.find(tmp_path)


def test_a_rom_without_a_native_kernal_is_refused():
    d = bytearray(native_rom())
    d[0x1FFFA:0x20000] = bytes(6)
    with pytest.raises(F.NotAMega65Rom, match="C65/MEGA65 KERNAL"):
        F.check_native(bytes(d))


def test_no_rom_names_every_place_searched(tmp_path):
    with pytest.raises(F.RomNotFound) as e:
        F.find(tmp_path)
    for p in ("MEGA65.ROM", "hdos/MEGA65.ROM"):
        assert str(tmp_path / p) in str(e.value)


def test_version():
    assert F.rom_version(native_rom(b"V920421")) == "V920421"
    assert F.rom_version(bytes(ROM_SIZE)) == "unknown"


# ── the copy in rom/ ──────────────────────────────────────────────

def test_install_copies_once_and_replaces_a_stale_copy(tmp_path):
    src = put(tmp_path / "xemu/MEGA65.ROM", native_rom(fill=0x44))
    target = tmp_path / "rom/mega65.rom"
    assert F.install(target, tmp_path / "xemu") == (src, native_rom(fill=0x44), True)
    assert target.read_bytes() == native_rom(fill=0x44)
    assert F.install(target, tmp_path / "xemu")[2] is False
    put(src, native_rom(fill=0x55))
    assert F.install(target, tmp_path / "xemu")[2] is True
    assert target.read_bytes() == native_rom(fill=0x55)


def test_the_booted_rom_must_be_the_copy(tmp_path):
    target = put(tmp_path / "mega65.rom", native_rom())
    F.check_booted(native_rom(), target)
    with pytest.raises(F.RomMismatch, match="V920422"):
        F.check_booted(native_rom(b"V920422"), target)


def test_main_reports_a_missing_rom(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XEMU_MEGA65_DIR", str(tmp_path))
    assert F.main() == 1                             # nothing found: no write
    assert "XEMU_MEGA65_DIR" in capsys.readouterr().err


# ── the committed Open ROM ────────────────────────────────────────

def test_the_open_rom_is_the_pinned_build():
    data = F.OPEN_ROM.read_bytes()
    assert hashlib.sha256(data).hexdigest() == F.OPEN_ROM_SHA256
    assert F.rom_version(data) == "O21082420"


def test_the_open_rom_has_no_native_mode():
    with pytest.raises(F.NotAMega65Rom):
        F.check_native(F.OPEN_ROM.read_bytes())
