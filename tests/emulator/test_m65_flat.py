"""test_m65_flat.py — flat addresses in the REPL, in xmega65 (Tier X).

Owner: doc/modules/repl.md

Contract source: [repl.md § Banks](../../doc/modules/repl.md#banks-m65);
slice 3's F1 (TODO § Slice 3 — banks).

As test_m65_boot.py types keys, a session makes the current address
flat (`@ 4.2000`), edits bank 4 with `m`, assembles into it with `.`,
lists it with `d` and is refused a write into bank 3: the bytes land
at flat `4.2000` in xmega65 as in M65Emu, every screen on the way is
M65Emu's, and bank 3 is untouched.

Not collected by a plain `pytest` (testpaths); run it by path:

    pytest tests/emulator
"""

import pathlib
import sys

import pytest

from xmega65 import PER_ROM, missing, snapshot_dir

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
sys.path.insert(0, str(ROOT / "tests" / "emulator"))
from test_m65_boot import typed_run                              # noqa: E402

WORK = ROOT / "build" / "m65_flat"
_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

SCRIPT = [b"@ 4.2000\r", b"M 11 22 33\r", b". LDA #$01\r", b". BNE $2000\r",
          b"@ 4.2000\r", b"D\r",
          b"@ 3.2000\r", b"M 00\r",                     # refused: ;?range
          b"@ $2000\r"]
BANK4, BANK3 = 0x42000, 0x32000
WANT4 = [0x11, 0x22, 0x33, 0xA9, 0x01, 0xD0, 0xF9]    # BNE at $2005 to $2000: -7


@pytest.fixture(scope="module", **PER_ROM)
def ran(request, cse_m65_prg):
    d = snapshot_dir(request)
    return typed_run(d, cse_m65_prg, SCRIPT, WORK / d.name,
                     peek=[(BANK4, len(WANT4)), (BANK3, 1)])


def test_the_bytes_land_in_bank_4(ran):
    assert ran["got_peek"][0] == WANT4
    assert ran["want_peek"][0] == WANT4


def test_bank_3_is_not_written(ran):
    assert ran["got_peek"][1] == ran["want_peek"][1] != [0x00]


@pytest.mark.parametrize("step", range(len(SCRIPT) + 1),
                         ids=["splash"] + [k.decode("latin-1").strip() for k in SCRIPT])
def test_the_screen_is_m65emus(ran, step):
    assert ran["got"][step] == ran["want"][step]


def test_the_prompt_and_rows_are_flat(ran):
    rows = ran["want"][6]                               # after `D`
    assert any(r.startswith("4.2003:.  a9 01") for r in rows)
    assert any(r.rstrip() == ";?range" for r in ran["want"][8])
