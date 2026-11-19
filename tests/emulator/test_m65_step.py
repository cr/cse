"""test_m65_step.py — the 45GS02 step in xmega65 (Tier X, P4 T9).

Owner: doc/modules/debugger.md

Contract source: [debugger.md § Next-PC](../../doc/modules/debugger.md#next-pc)
(*On m65*); T9 of TODO § M65 slice 2, P4.

As test_m65_boot.py types commands (one key at a time through
`ADDKEY`, compared as screen text with M65Emu's M65Session after the
same keys), a program is typed with `.` and stepped with `t` from a
cold preview: a Q instruction, a far one, a 16-bit `BRA`, and
`JMP ($30FF)`, whose vector's high byte is at $3100 on the 45GS02 (no
page wrap) — $3000 would send it to $4200, where a BRK waits.  Each
step stops where M65Emu's stops, with the same registers: the real
CPU's lengths, targets and wrap answer.

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

WORK = ROOT / "build" / "m65_step"
_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

SETUP = [b"@ $30FF\r", b". 00 34 00 00 00\r",   # $3100: the vector's high byte, Q's bytes
         b"@ $12\r", b". 00 31 00 00\r",        # ($12): $00003100
         b"@ $4200\r", b". 00\r",               # the wrap's target: a BRK
         b"@ $3000\r",
         b". LDQ ($12),Z\r",                    # $3000: 42 42 B2 12
         b". LDA [$12],Z\r",                    # $3004: EA B2 12
         b". BRA $3200\r",                      # $3007: 83 F7 01
         b"@ $3200\r", b". JMP ($30FF)\r",
         b"@ $3400\r", b". INZ\r", b". RTS\r",
         b"@ $3000\r"]
STEPS = [b"T\r"] * 7          # the preview, then $3004 $3007 $3200 $3400 $3401, rts
SCRIPT = SETUP + STEPS


@pytest.fixture(scope="module", **PER_ROM)
def stepped(request, cse_m65_prg):
    """The screens after each step of SCRIPT in xmega65 and in M65Emu."""
    d = snapshot_dir(request)
    return typed_run(d, cse_m65_prg, SCRIPT, WORK / d.name)


@pytest.mark.parametrize("step", range(len(SCRIPT) + 1),
                         ids=["splash"] + [k.decode("latin-1").strip() for k in SCRIPT])
def test_the_screen_is_m65emus(stepped, step):
    assert stepped["got"][step] == stepped["want"][step]        # 0: the splash


TAGS = ["; dbg at $3000", "; brk at $3004", "; brk at $3007", "; brk at $3200",
        "; brk at $3400", "; brk at $3401", "; rts"]


@pytest.mark.parametrize("k", range(len(STEPS)), ids=TAGS)
def test_m65emu_steps_the_documented_path(stepped, k):
    """The reference itself: each step's tag row, so a shared wrong
    answer cannot pass (the wrap would stop at $4200)."""
    rows = stepped["want"][1 + len(SETUP) + k]
    assert any(r.rstrip() == TAGS[k] for r in rows), "\n".join(rows)
