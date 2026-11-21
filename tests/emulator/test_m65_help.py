"""
test_m65_help.py — the HELP popup in xmega65 (Tier X)

Owner: doc/modules/help.md

Contract source: help.md § The window.  HELP typed into CSE in xmega65
draws the window M65Emu draws (the screens compared as text), and HELP
again gives the screen back.  The border's six screen codes are line
graphics in the font the VIC-IV shows: the lower/upper half of the
character ROM at $FF7E000 (M65Emu models no character ROM).
"""

import pathlib
import shutil
import sys

import pytest

from m65emu.harness import CSE_BP, load_snapshot
from xmega65 import CHIP_ROM, PER_ROM, XMega65, missing, snapshot_dir

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from test_m65_repl import M65Session                            # noqa: E402
from test_m65_boot import geometry_of, screen_text              # noqa: E402

WORK = ROOT / "build" / "m65_help"
HELP = 0x84
CHAR_ROM = 0xFF7E000
LOWER = 0x800                  # the lower/upper set: the second 2 K
ROWS = {0x40: "h", 0x5D: "v", 0x70: "tl", 0x6E: "tr", 0x6D: "bl", 0x7D: "br"}

_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))


@pytest.fixture(scope="module", **PER_ROM)
def helped(request, cse_m65_prg):
    d = snapshot_dir(request)
    snap = load_snapshot(d)
    prg, map_path = cse_m65_prg
    ref = M65Session((prg, map_path), snap)
    want_before = ref.rows()
    ref.e.inject_keys(bytes([HELP]))
    ref.e.run_until(ref.e.sym("help_wait"), max_cycles=3_000_000)
    want_open = ref.rows()
    s = ref.e.sym
    work = WORK / d.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rom = work / "rom.bin"
    rom.write_bytes(snap["chip"][CHIP_ROM])
    try:
        with XMega65(work / "run", rom=rom, prg=prg) as xm:
            xm.run_to_page(s("_main"), CSE_BP)
            xm.run_to(s("main_loop_top"))
            xm.run_to(s("main_loop"))
            geo = geometry_of(xm.read, s)
            before = screen_text(xm.read, *geo)
            xm.addkeys([HELP])
            xm.run_to(s("help_wait"))
            opened = screen_text(xm.read, *geo)
            xm.addkeys([HELP])
            xm.run_to(s("main_loop"))
            after = screen_text(xm.read, *geo)
            font = xm.read(CHAR_ROM + LOWER, 0x400)
            d018 = xm.read(0xFFD3018, 1)[0]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dict(want_before=want_before, want_open=want_open, before=before,
                opened=opened, after=after, font=font, d018=d018)


def test_help_draws_the_window_m65emu_draws(helped):
    assert helped["before"] == helped["want_before"]
    assert helped["opened"] == helped["want_open"]
    assert "cse help" in helped["opened"][0]


def test_help_again_gives_the_screen_back(helped):
    assert helped["after"] == helped["before"]


def test_cse_shows_the_lower_upper_set(helped):
    assert helped["d018"] & 0x02, "the character pointer's lower/upper half"


def test_the_border_codes_are_line_graphics(helped):
    """─ is a centred row band, │ a centred column band, the corners
    their halves joined — each glyph checked by its pixels."""
    font = helped["font"]
    glyph = {name: font[code * 8:code * 8 + 8] for code, name in ROWS.items()}
    band = glyph["h"]
    rows = [k for k in range(8) if band[k]]
    assert rows and all(band[k] == 0xFF for k in rows), band.hex()
    col = glyph["v"][0]
    assert col and all(b == col for b in glyph["v"]), glyph["v"].hex()
    high, low = 1 << (col.bit_length() - 1), col & -col
    right_half = (high << 1) - 1                    # the column and every pixel right of it
    left_half = 0xFF & ~(low - 1)                   # the column and every pixel left of it
    for name, horiz, top, bottom in (("tl", right_half, False, True),
                                     ("tr", left_half, False, True),
                                     ("bl", right_half, True, False),
                                     ("br", left_half, True, False)):
        g = glyph[name]
        for k in range(8):
            if k in rows:
                assert g[k] == horiz, (name, k, g.hex())
            elif k < rows[0]:
                assert g[k] == (col if top else 0), (name, k, g.hex())
            else:
                assert g[k] == (col if bottom else 0), (name, k, g.hex())
