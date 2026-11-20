"""test_m65_roms.py — the MEGA65 ROMs the m65 build is verified on (P5 T1).

Owner: doc/build_system.md

Contract source: [build_system.md § MEGA65 ROM](../../doc/build_system.md#mega65-rom)
(*The verified ROMs*), [testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness)
(*Starting state*).

The m65 tiers run on every M65Emu snapshot present (`snapshot_dirs()`).
With any snapshot there, every verified ROM must have one, of the
current format — else a run on a partial set would report green on
half the matrix.  With none, the m65 tests skip and so does this.
"""

import json
import pathlib
import re

import pytest

from m65emu.harness import CAPTURE, FORMAT, STATE_DIR, VERIFIED_ROMS, verified_rom_gaps

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_the_list_is_build_systems():
    """build_system.md names the verified ROMs in bold; the harness's
    list is the same."""
    doc = (ROOT / "doc" / "build_system.md").read_text()
    para = doc[doc.index("**The verified ROMs.**"):]
    para = para[:para.index("\n\n")]
    assert tuple(re.findall(r"\*\*(9\d{5})\*\*", para)) == VERIFIED_ROMS


def test_every_verified_rom_has_a_current_snapshot():
    if not any(STATE_DIR.glob("*/state.json")):
        pytest.skip(f"no M65Emu snapshot; run: {CAPTURE}")
    assert verified_rom_gaps() == []


def _snapshot(root, rom, fmt=FORMAT):
    d = root / rom
    d.mkdir(parents=True)
    (d / "state.json").write_text(json.dumps({"format": fmt, "rom": f"V{rom}"}))


def test_a_missing_rom_is_named(tmp_path):
    _snapshot(tmp_path, VERIFIED_ROMS[0])
    gaps = verified_rom_gaps(tmp_path)
    assert gaps and all(r in " ".join(gaps) for r in VERIFIED_ROMS[1:])
    assert CAPTURE.split()[1] in " ".join(gaps)


def test_a_stale_format_is_named(tmp_path):
    for rom in VERIFIED_ROMS:
        _snapshot(tmp_path, rom, fmt=FORMAT - 1)
    assert len(verified_rom_gaps(tmp_path)) == len(VERIFIED_ROMS)


def test_an_empty_state_dir_has_no_gaps(tmp_path):
    assert verified_rom_gaps(tmp_path) == []
