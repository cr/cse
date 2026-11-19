"""test_m65_d81.py — the m65 PRG on a D81, through CBDOS, in xmega65 (Tier X, P3 T6).

Owner: doc/modules/disk.md

Contract source: [disk.md § On m65](../../doc/modules/disk.md#on-m65),
[build_system.md § The m65 builds](../../doc/build_system.md#the-m65-builds)
(the D81), [testing.md § The m65 PRG on M65Emu](../../doc/testing.md#the-m65-prg-on-m65emu)
(*The disk on m65*).

On each ROM that has an M65Emu snapshot, a D81 written by c1541 as
`make disk PLATFORM=m65` writes it (the debug PRG as "cse-m65") is
mounted on unit 8 — CBDOS's, which M65Emu does not model — and
xmega65 autoloads it.  Typed as test_m65_boot.py types (`addkeys()`,
one key, then on to main_loop):

- the D81 starts CSE to the prompt;
- `$` lists the disk as c1541 does — name, id, the file and its
  blocks, blocks free — and the drive's status; the screen keeps the
  VIC-IV's internal character set (CHARPTR $001800), so the directory
  in DIR_BUF (2.D000, the ROM's font C) does not reach the display;
- `s` of a PRG range and `l` back: the bytes equal, the file ("t1.",
  the REPL's PRG name) the header and the bytes; the source saved from
  the editor reads back from the D81 (c1541) as typed.

Not collected by a plain `pytest` (testpaths); run it by path:

    pytest tests/emulator
"""

import pathlib
import re
import shutil
import subprocess
import sys

import pytest

from emu_base import decode_screen_codes
from m65emu.harness import CSE_BP, load_snapshot, snapshot_dirs
from xmega65 import CHIP_ROM, XMega65, missing

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from test_m65_repl import M65Session                            # noqa: E402

WORK = ROOT / "build" / "m65_disk"
STOP = 0x03
OK = "; 00,ok,00,00"             # CBDOS's status: no space after the code (a 1541's has one)
DATA = bytes((k * 11 + 3) & 0xFF for k in range(32))

_SNAPSHOTS = snapshot_dirs()


_MISSING = missing("c1541")
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))


def c1541(*args):
    return subprocess.run(["c1541", *args], capture_output=True, text=True,
                          check=True).stdout


def screen(xm, width=80, height=25):
    raw = xm.read(0x0800, width * height)
    return [decode_screen_codes(raw[r * width:(r + 1) * width]) for r in range(height)]


@pytest.fixture(scope="module",
                params=_SNAPSHOTS or [None],
                ids=[d.name for d in _SNAPSHOTS] or ["no-snapshot"])
def run(request, cse_m65_prg):
    """One xmega65 session on the D81: what each step left."""
    if request.param is None:
        pytest.skip("no M65Emu snapshot (it holds the ROM): "
                    "python dev/capture_m65_state.py --rom PATH")
    snap = load_snapshot(request.param)
    prg, map_path = cse_m65_prg
    s = M65Session((prg, map_path), snap).e.sym
    work = WORK / request.param.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rom = work / "rom.bin"
    rom.write_bytes(snap["chip"][CHIP_ROM])
    d81 = work / "cse.d81"
    c1541("-format", "cse test,01", "d81", str(d81), "-write", str(prg), "cse-m65")
    listing = c1541("-attach", str(d81), "-list")
    out = {"c1541": listing}
    try:
        with XMega65(work / "run", rom=rom, d81=d81) as xm:
            xm.run_to_page(s("_main"), CSE_BP)
            xm.run_to(s("main_loop"), timeout=60)
            out["prompt"] = screen(xm)

            def typed(keys):
                for k in keys:
                    xm.addkeys([k])
                    xm.run_to(s("main_loop"), timeout=120)
                return screen(xm)

            out["dir"] = typed(b"$\r")
            out["charptr"] = list(xm.read_cpu(0xD068, 3))
            xm.write(0x3000, DATA)
            typed(b"@ $3000\r")
            out["save"] = typed(b'S "T1" $301F\r')
            xm.write(0x3000, bytes(len(DATA)))
            out["load"] = typed(b'L "T1" 0\r')
            out["loaded"] = xm.read(0x3000, len(DATA))
            typed(bytes([STOP]) + b"NOP\r" + bytes([STOP]))
            out["src"] = typed(b'S "SRC"\r')
            disk = xm.mounted_d81()
        out["after"] = c1541("-attach", str(disk), "-list")
        c1541("-attach", str(disk), "-read", "t1.", str(work / "t1.prg"))   # the PRG: "name."
        c1541("-attach", str(disk), "-read", "src,s", str(work / "src.seq"))
        out["t1_file"] = (work / "t1.prg").read_bytes()
        out["src_file"] = (work / "src.seq").read_bytes()
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out


def test_the_d81_starts_cse_to_the_prompt(run):
    rows = run["prompt"]
    assert any(r.startswith("; cse v") for r in rows)
    assert rows[24] == "2000:"


def test_dollar_lists_the_disk_as_c1541_does(run):
    """c1541: `0 "cse test        " 01 3d`, `90   "cse-m65"   prg`,
    `3070 blocks free.`"""
    text = run["c1541"]
    head = re.search(r'^0 (".*") (\S\S \S\S)', text, re.M)
    entry = re.search(r'^(\d+)\s+"(.*?)"\s+(\w)\w\w', text, re.M)
    free = re.search(r"^(\d+) blocks free", text, re.M)
    rows = run["dir"]
    k = next(i for i, r in enumerate(rows) if r.startswith('; "'))
    assert rows[k] == f"; {head.group(1)} {head.group(2)}"
    assert rows[k + 1] == f'l "{entry.group(2)},{entry.group(3)}"; {entry.group(1)} blocks'
    assert rows[k + 2] == f"; {free.group(1)} blocks free."
    assert rows[k + 3] == OK


def test_the_display_keeps_the_vic_ivs_own_font(run):
    """CHARPTR $001800: the internal set, not the ROM's font C at 2.D000,
    which DIR_BUF overwrites."""
    assert run["charptr"] == [0x00, 0x18, 0x00]


def test_a_prg_saved_and_loaded_back(run):
    assert run["t1_file"] == b"\x00\x30" + DATA
    assert run["loaded"] == DATA
    assert "; prg  0.3000-301f    32b" in run["save"]
    assert OK in run["load"]


def test_the_source_saved_from_the_editor(run):
    assert run["src_file"] == b"\xa0NOP\r\xa0"
    assert OK in run["src"]
