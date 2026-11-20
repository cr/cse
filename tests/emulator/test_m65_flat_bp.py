"""test_m65_flat_bp.py — a breakpoint on a physical byte, in xmega65 (Tier X).

Owner: doc/modules/debugger.md

Contract source: [debugger.md § `b`](../../doc/modules/debugger.md#b),
[breakpoints.md](../../doc/modules/breakpoints.md) (*the flat slots*);
slice 3's F4.

As test_m65_boot.py types keys: a program typed into bank 4 with `.`,
`b 4.2005` and `b $2005` set (listed `4.2005` and `0.2005`), `j 4.2000`
started: the bank-4 breakpoint is hit, the bank-0 one is not, and after
`c` both banks hold their bytes again — every screen M65Emu's.

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

WORK = ROOT / "build" / "m65_flat_bp"
_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

PROG = [0xA9, 0x48, 0x20, 0xD2, 0xFF, 0xA9, 0x5A, 0x60]   # 4.2000
BANK0 = [0xEA] * 8                                          # 0.2000
SCRIPT = [b"B 4.2005\r", b"B $2005\r", b"B\r", b"J 4.2000\r", b"C\r"]
LISTED, BROKE, RAN = 3, 4, 5


@pytest.fixture(scope="module", **PER_ROM)
def ran(request, cse_m65_prg):
    d = snapshot_dir(request)
    return typed_run(d, cse_m65_prg, SCRIPT, WORK / d.name,
                     poke=[(0x42000, PROG), (0x2000, BANK0)],
                     peek=[(0x42000, len(PROG)), (0x2000, len(BANK0))])


def test_both_banks_hold_their_bytes_again(ran):
    assert ran["got_peek"] == ran["want_peek"] == [PROG, BANK0]


@pytest.mark.parametrize("step", range(len(SCRIPT) + 1),
                         ids=["splash"] + [k.decode("latin-1").strip() for k in SCRIPT])
def test_the_screen_is_m65emus(ran, step):
    assert ran["got"][step] == ran["want"][step]


def test_listed_flat_and_only_the_bank_4_byte_hit(ran):
    rows = [r.rstrip() for r in ran["want"][LISTED]]
    assert "; bp 1: 4.2005" in rows and "; bp 2: 0.2005" in rows
    assert any("at $2005" in r for r in ran["want"][BROKE])
    assert any(r == "; rts" for r in ran["want"][RAN])
