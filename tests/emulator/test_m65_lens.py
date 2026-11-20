"""test_m65_lens.py — the monitor reads through the program's map, in xmega65 (Tier X).

Owner: doc/modules/mem.md

Contract source: [mem.md § far_user](../../doc/modules/mem.md#far_user-far_user_w-m65-only),
[repl.md § Banks](../../doc/modules/repl.md#banks-m65) (*The map in `r` and
`M`*); slice 3's F2.

As test_m65_boot.py types keys: `r ml:e400` gives the program's map
$2000-$7FFF -> 4.2000; `m 2000` then shows bank 4, `m 2000 66` edits
bank 4, a row across $BFF8 shows the RAM and then the interface ROM,
and `M` lists the map — the bytes and every screen M65Emu's.

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

WORK = ROOT / "build" / "m65_lens"
_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

BANK4 = 0x42000
PATTERN = [0x5A, 0xA5, 0x3C, 0xC3]
SCRIPT = [b"R ML:E400\r", b"M 2000\r", b"M 2000 66\r", b"M BFF8\r",
          b"\xcd\r",                                    # M: the map
          b"R ML:E000\r"]


@pytest.fixture(scope="module", **PER_ROM)
def ran(request, cse_m65_prg):
    d = snapshot_dir(request)
    return typed_run(d, cse_m65_prg, SCRIPT, WORK / d.name,
                     poke=[(BANK4, PATTERN)], peek=[(BANK4, len(PATTERN)), (0x2000, 1)])


def test_the_edit_lands_in_bank_4(ran):
    assert ran["got_peek"][0] == [0x66] + PATTERN[1:]
    assert ran["want_peek"][0] == [0x66] + PATTERN[1:]
    assert ran["got_peek"][1] == ran["want_peek"][1] != [0x66]


@pytest.mark.parametrize("step", range(len(SCRIPT) + 1),
                         ids=["splash"] + [k.decode("latin-1").strip() for k in SCRIPT])
def test_the_screen_is_m65emus(ran, step):
    assert ran["got"][step] == ran["want"][step]


def test_m_showed_bank_4_and_M_the_map(ran):
    assert any(r.startswith("2000:m 5a a5 3c c3") for r in ran["want"][2])
    assert any(r.startswith("; map  2000-7fff 4.2000 mapped") for r in ran["want"][5])
