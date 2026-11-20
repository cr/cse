"""test_m65_base_page.py — the program's base-page cells survive CSE (Tier X).

Owner: doc/platform_layer.md

Contract source: [userland_contract.md § 3 On m65](../../doc/userland_contract.md#on-m65)
(*Zero page*): base page 0's `$0A–$8F` and `$FB–$FF` are the
program's; neither CSE nor the KERNAL writes them.

A pattern is written into both stretches, then a session is typed into
xmega65 and into M65Emu alike (as test_m65_boot.py types keys): `i`,
`m`, a program assembled with `.` that prints through `BSOUT`, stepped
with `t` and run on with `c`, and the 80 × 50 switch and back.  After it
the pattern is unchanged in both machines.  (The disk calls are
test_m65_disk.py's, on M65Emu's virtual drive.)

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

WORK = ROOT / "build" / "m65_base_page"
_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

USER = [(0x0A, 0x8F), (0xFB, 0xFF)]                 # the program's cells
PATTERN = [(a, [(k * 37 + 0x5B) & 0xFF for k in range(lo, hi + 1)])
           for a, (lo, hi) in zip((lo for lo, _ in USER), USER)]
SCRIPT = [b"I\r", b"M 2000\r",
          b"@ $3000\r", b". LDA #$48\r", b". JSR $FFD2\r", b". RTS\r",
          b"@ $3000\r", b"T\r", b"T\r", b"T\r",     # the preview, LDA, over the JSR
          b"C\r",                                    # on through its RTS
          b"\x1b5", b"I\r", b"\x1b8"]
STEPPED, RAN = 10, 11                               # screens after the last T, after C


@pytest.fixture(scope="module", **PER_ROM)
def ran(request, cse_m65_prg):
    d = snapshot_dir(request)
    return typed_run(d, cse_m65_prg, SCRIPT, WORK / d.name, poke=PATTERN,
                     peek=[(a, len(data)) for a, data in PATTERN])


def test_xmega65_keeps_the_programs_base_page(ran):
    assert ran["got_peek"] == [data for _, data in PATTERN]


def test_m65emu_keeps_the_programs_base_page(ran):
    assert ran["want_peek"] == [data for _, data in PATTERN]


def test_the_session_ran(ran):
    """The script did what it says: the program printed `H`, the
    steps stopped, `i` listed the zp rows — on both machines alike."""
    assert ran["got"][-1] == ran["want"][-1]
    for shot in (ran["got"], ran["want"]):
        assert any(r.rstrip() == "; brk at $3005" for r in shot[STEPPED])
        assert any(r.rstrip() == "; rts" for r in shot[RAN])
        assert any(r.startswith("; zp   0.000a-008f") for r in shot[-2])
