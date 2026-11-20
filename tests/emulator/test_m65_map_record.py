"""test_m65_map_record.py — JSRFAR keeps the KERNAL's map record in step (Tier X).

Owner: doc/platform_layer.md

Contract source: [userland_contract.md § 5.6](../../doc/userland_contract.md#56-on-m65-memory-maps-and-kernal-calls)
(rule 2); [platform_layer.md § User transitions](../../doc/platform_layer.md#user-transitions)
(the map record).

In xmega65 at the BASIC 65 prompt, on each ROM and for each bank a far
start uses (1, 4, 5): code in bank 0 calls `JSRFAR` for `B.2000`.  The code there copies the map record
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
BANKS = [1, 4, 5]               # the far starts' banks (repl.md § Far starts)


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
def call_code(bank):
    code = ([0xA9, bank, 0x85, 0x02, 0xA9, 0x20, 0x85, 0x03, 0xA9, 0x00,  # bank, $2000
             0x85, 0x04, 0x85, 0x05, 0x85, 0x06, 0x85, 0x07, 0x85, 0x08, 0x85, 0x09,
             0x20, 0x6E, 0xFF]                                          # JSR JSRFAR
            + copy_record(0x10))
    park = CALLER + len(code)
    return code + [0x4C, park & 0xFF, park >> 8], park                 # JMP *


def jsrfar_map(bank):
    """$2000-$7FFF -> bank.2000, the KERNAL at $E000: A X Y Z."""
    return [0x00, 0xE0 | bank, 0x00, 0x83]


BASIC_MAP = [0x00, 0xE3, 0x00, 0xB3]      # the prompt's: the caller's map


@pytest.fixture(scope="module", params=BANKS, ids=[f"bank{b}" for b in BANKS])
def bank(request):
    return request.param


@pytest.fixture(scope="module", **PER_ROM)
def ran(request, bank):
    d = snapshot_dir(request)
    work = WORK / f"{d.name}-{bank}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rom = work / "rom.bin"
    rom.write_bytes(load_snapshot(d)["chip"][CHIP_ROM])
    try:
        with recording(work / "run", rom=rom) as xm:
            call, park = call_code(bank)
            xm.write(OUT, bytes(0x14))
            xm.write(bank << 16 | 0x2000, bytes(FAR_CODE))
            xm.write(CALLER, bytes(call))
            xm.cmd(f"g {CALLER:x}")
            restore = xm.run_to(0xCBF6, timeout=30, at_hit=True)
            xm.run_to(park, timeout=30)
            out = list(xm.read(OUT, 0x14))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dict(restore=restore, out=out)


def test_jsrfar_writes_its_map_into_the_record(ran, bank):
    assert ran["out"][0:4] == jsrfar_map(bank)


def test_a_cbdos_call_returns_into_the_far_code(ran, bank):
    assert ran["out"][4] == 0x5A                       # the marker: back in the bank
    assert ran["out"][8:12] == jsrfar_map(bank)       # the record unchanged by it


def test_jsrfar_restores_the_callers_map(ran):
    assert ran["out"][0x10:0x14] == BASIC_MAP
