"""test_m65_far_start.py — `j 4.2000` starts a bank as JSRFAR would, in xmega65 (Tier X).

Owner: doc/modules/repl.md

Contract source: [repl.md § Far starts](../../doc/modules/repl.md#far-starts),
[userland_contract.md § 5.6](../../doc/userland_contract.md#56-on-m65-memory-maps-and-kernal-calls)
(rule 2); slice 3's F3.

A program is typed into bank 4 with `.` at the flat prompt `4.2000:`
and started with `j 4.2000`.  Its first instructions copy the KERNAL's
map record to 0.1600; it then opens and closes command channel 15 on
unit 8 — a CBDOS call, whose return path reinstates the record's map —
sets a marker and returns.  In xmega65 on each ROM: the record held the
far map (`00 e4 00 83`) from the first instruction, the program came
back from the disk call into bank 4 and ran to its RTS, and `r` shows
`ml:e400`.  xmega65 alone: M65Emu models no floppy controller for unit 8.

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

WORK = ROOT / "build" / "m65_far_start"
_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

OUT = 0x1600
SCRIPT = [b"@ 4.2000\r",
          b". LDX #$03\r", b". LDA $011C,X\r", b". STA $1600,X\r",   # the record
          b". DEX\r", b". BPL $2002\r",
          b". LDA #$00\r", b". JSR $FFBD\r",                         # SETNAM ""
          b". LDA #$0F\r", b". LDX #$08\r", b". LDY #$0F\r", b". JSR $FFBA\r",
          b". JSR $FFC0\r",                                          # OPEN 15,8,15
          b". LDA #$0F\r", b". JSR $FFC3\r",                         # CLOSE 15
          b". LDA #$5A\r", b". STA $1604\r", b". RTS\r",
          b"J 4.2000\r"]


@pytest.fixture(scope="module", **PER_ROM)
def ran(request, cse_m65_prg):
    d = snapshot_dir(request)
    return typed_run(d, cse_m65_prg, SCRIPT, WORK / d.name, reference=False,
                     poke=[(OUT, [0] * 5)], peek=[(OUT, 5)])


def test_the_record_held_the_far_map(ran):
    assert ran["got_peek"][0][:4] == [0x00, 0xE4, 0x00, 0x83]


def test_the_disk_call_returned_into_bank_4(ran):
    assert ran["got_peek"][0][4] == 0x5A


def test_the_program_ran_to_its_rts_in_the_far_map(ran):
    rows = ran["got"][-1]
    k = next(i for i, r in enumerate(rows) if r.rstrip() == "; rts")
    assert rows[k + 1].rstrip().endswith("ml:e400 mh:8300")
