"""test_m65_asm_run.py — a CSE-assembled 45GS02 program runs in xmega65 (Tier X, P4 T10).

Owner: doc/modules/asm_line.md

Contract source: [asm_line.md § Prefixes](../../doc/modules/asm_line.md#prefixes-45gs02),
[§ Branches](../../doc/modules/asm_line.md#branches-zone-b),
[§ IMM16 promotion](../../doc/modules/asm_line.md#imm16-promotion-mega_support);
T10 of TODO § M65 slice 2, P4.

The program is typed with `.` (the REPL's line assembler, `asm_cpu` 4,
as test_m65_boot.py types keys) and run with `j`: `PHW #`, a Q load
and store, a far load, and a 16-bit conditional branch.  The bytes it
stores are what the instruction set predicts — `PHW` pushes the low
byte first (recorded in m65_cpu.json), `LDQ` / `STQ` move A X Y Z, the
far pointer reaches $00003100 — in xmega65 and in M65Emu alike, and
every screen on the way is M65Emu's.

Not collected by a plain `pytest` (testpaths); run it by path:

    pytest tests/emulator
"""

import pathlib
import sys

import pytest

from m65emu.harness import snapshot_dirs
from xmega65 import missing

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
sys.path.insert(0, str(ROOT / "tests" / "emulator"))
from test_m65_boot import typed_run                              # noqa: E402

WORK = ROOT / "build" / "m65_asm_run"
_SNAPSHOTS = snapshot_dirs()
_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

OUT = 0x3300
SCRIPT = [b"@ $3100\r", b". 34 56 78 9A\r",    # Q's bytes
          b"@ $319A\r", b". C3\r",               # the far byte: $3100 + Z
          b"@ $12\r", b". 00 31 00 00\r",       # ($12): $00003100
          b"@ $3000\r",
          b". PHW #$1234\r",                    # $3000: F4 34 12
          b". PLA\r", b". STA $3300\r",         # the byte pushed last
          b". PLA\r", b". STA $3301\r",
          b". LDQ ($12),Z\r",                   # $300B: 42 42 B2 12
          b". STQ $3302\r",                     # $300F: 42 42 8D 02 33
          b". LDA [$12],Z\r",                   # $3014: EA B2 12 (Z = $9A)
          b". STA $3306\r",
          b". LDX #$00\r",
          b". BEQ $3400\r",                     # $301C: F3 E2 03, taken
          b". BRK\r",
          b"@ $3400\r", b". LDA #$5A\r", b". STA $3307\r", b". RTS\r",
          b"J $3000\r"]
# $3300: PHW's high byte, then its low; $3302: Q (A X Y Z); $3306: the
# far byte at $3100 + Z; $3307: the 16-bit branch's target ran.
WANT = [0x12, 0x34, 0x34, 0x56, 0x78, 0x9A, 0xC3, 0x5A]


@pytest.fixture(scope="module",
                params=_SNAPSHOTS or [None],
                ids=[d.name for d in _SNAPSHOTS] or ["no-snapshot"])
def ran(request, cse_m65_prg):
    if request.param is None:
        pytest.skip("no M65Emu snapshot (it holds the ROM): "
                    "python dev/capture_m65_state.py --rom PATH")
    return typed_run(request.param, cse_m65_prg, SCRIPT,
                     WORK / request.param.name, peek=[(OUT, len(WANT)), (0x3000, 0x20)])


def test_the_program_stores_what_the_instruction_set_predicts(ran):
    assert ran["got_peek"][0] == WANT
    assert ran["want_peek"][0] == WANT


def test_the_bytes_assembled_are_m65emus(ran):
    assert ran["got_peek"][1] == ran["want_peek"][1]
    assert ran["got_peek"][1][0x1C:0x1F] == [0xF3, 0xE2, 0x03]      # REL16


@pytest.mark.parametrize("step", range(len(SCRIPT)),
                         ids=[k.decode("latin-1").strip() for k in SCRIPT])
def test_the_screen_is_m65emus(ran, step):
    assert ran["got"][step] == ran["want"][step]
