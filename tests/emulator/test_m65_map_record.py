"""test_m65_map_record.py — JSRFAR keeps the KERNAL's map record in step (Tier X).

Owner: doc/platform_layer.md

Contract source: [userland_contract.md § 5.6](../../doc/userland_contract.md#56-on-m65-memory-maps-and-kernal-calls)
(rule 2); [platform_layer.md § User transitions](../../doc/platform_layer.md#user-transitions)
(the map record).

In xmega65 at the BASIC 65 prompt, on each ROM: code in bank 0 calls
`JSRFAR` for `4.2000`.  The code there copies the map record
`0.011C–011F`, opens and closes command channel 15 on unit 8 — a CBDOS
call, which leaves the map and reinstates the record's at `2.CBF6` —
sets a marker and copies the record again; back in bank 0 the caller
copies it a third time.  The record holds JSRFAR's map during the
call, the disk call returns into the far code, and the caller's map is
back afterwards.

Not collected by a plain `pytest` (testpaths); run it by path:

    pytest tests/emulator
"""

import pathlib
import shutil

import pytest

from m65emu.harness import load_snapshot
from xmega65 import CHIP_ROM, PER_ROM, missing, recording, snapshot_dir

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORK = ROOT / "build" / "m65_map_record"
_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

OUT = 0x1600                    # the copies: +0 in far code, +4 marker,
CALLER = 0x1700                 #   +8 after the disk call, +$10 after return
FAR = 0x42000                   # 4.2000


def copy_record(dst):
    """LDX #3 · LDA $011C,X · STA OUT+dst,X · DEX · BPL"""
    return [0xA2, 0x03, 0xBD, 0x1C, 0x01, 0x9D, (OUT + dst) & 0xFF, OUT >> 8,
            0xCA, 0x10, 0xF7]


FAR_CODE = (copy_record(0x00)
            + [0xA9, 0x00, 0x20, 0xBD, 0xFF,                        # SETNAM "" (length 0)
               0xA9, 0x0F, 0xA2, 0x08, 0xA0, 0x0F, 0x20, 0xBA, 0xFF,  # SETLFS 15,8,15
               0x20, 0xC0, 0xFF,                                    # OPEN
               0xA9, 0x0F, 0x20, 0xC3, 0xFF,                        # CLOSE 15
               0xA9, 0x5A, 0x8D, (OUT + 4) & 0xFF, OUT >> 8]        # the marker
            + copy_record(0x08) + [0x60])
CALL = ([0xA9, 0x04, 0x85, 0x02, 0xA9, 0x20, 0x85, 0x03, 0xA9, 0x00,  # bank 4, $2000
         0x85, 0x04, 0x85, 0x05, 0x85, 0x06, 0x85, 0x07, 0x85, 0x08, 0x85, 0x09,
         0x20, 0x6E, 0xFF]                                          # JSR JSRFAR
        + copy_record(0x10))
PARK = CALLER + len(CALL)
CALL += [0x4C, PARK & 0xFF, PARK >> 8]                              # JMP *

JSRFAR_BANK4 = [0x00, 0xE4, 0x00, 0x83]   # $2000-$7FFF -> 4.2000, KERNAL at $E000
BASIC_MAP = [0x00, 0xE3, 0x00, 0xB3]      # the prompt's: the caller's map


@pytest.fixture(scope="module", **PER_ROM)
def ran(request):
    d = snapshot_dir(request)
    work = WORK / d.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rom = work / "rom.bin"
    rom.write_bytes(load_snapshot(d)["chip"][CHIP_ROM])
    try:
        with recording(work / "run", rom=rom) as xm:
            xm.write(OUT, bytes(0x14))
            xm.write(FAR, bytes(FAR_CODE))
            xm.write(CALLER, bytes(CALL))
            xm.cmd(f"g {CALLER:x}")
            restore = xm.run_to(0xCBF6, timeout=30, at_hit=True)
            xm.run_to(PARK, timeout=30)
            out = list(xm.read(OUT, 0x14))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dict(restore=restore, out=out)


def test_jsrfar_writes_its_map_into_the_record(ran):
    assert ran["out"][0:4] == JSRFAR_BANK4


def test_a_cbdos_call_returns_into_the_far_code(ran):
    assert ran["out"][4] == 0x5A                       # the marker: back in 4.2000
    assert ran["out"][8:12] == JSRFAR_BANK4           # the record unchanged by it


def test_jsrfar_restores_the_callers_map(ran):
    assert ran["out"][0x10:0x14] == BASIC_MAP
