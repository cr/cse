"""test_m65emu.py — M65Emu on the real MEGA65 KERNAL (Tier I).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Runs from the post-boot snapshot dev/capture_m65_state.py records in
xmega65 (build/m65_state/, never committed); skipped, with the command
that makes it, when it is absent.  The first test replays the
snapshot's reference run — SEI, LDA #'A', JSR CHROUT — and must match
what xmega65 did, step for step and byte for byte.
"""

import pytest

from m65emu import M65Emu, SnapshotMissing
from m65emu.harness import load_snapshot

try:
    SNAPSHOT = load_snapshot()
except SnapshotMissing as e:
    pytestmark = pytest.mark.skip(reason=str(e))
    SNAPSHOT = None

REGS = ("pc", "a", "x", "y", "z", "b", "sp", "p", "mapl", "maph")


@pytest.fixture
def emu():
    return M65Emu(SNAPSHOT)


def run_reference(emu):
    ref = SNAPSHOT["reference"]
    code = bytes.fromhex(ref["code"])
    emu.memory.load(ref["at"], code)
    emu.pc = ref["at"]
    return ref, code, emu.run_until(ref["at"] + len(code))


def test_chrout_matches_the_xmega65_reference_run(emu):
    ref, code, steps = run_reference(emu)
    assert steps == ref["steps"]
    assert {r: getattr(emu.cpu, r) for r in REGS} == ref["after"]
    want = bytearray(SNAPSHOT["chip"][:0x20000])
    want[ref["at"]:ref["at"] + len(code)] = code
    for a, v in ref["chip_changes"].items():
        want[int(a, 16)] = v
    got = emu.memory.chip[:0x20000]
    assert got == want, {f"{a:05X}": (got[a], want[a])
                         for a in range(0x20000) if got[a] != want[a]}
    colour = bytearray(SNAPSHOT["colour"])
    for a, v in ref["colour_changes"].items():
        colour[int(a, 16)] = v
    assert all(emu.memory.read_flat(0xFF80000 + a) == colour[a]
               for a in range(0x8000))


def test_chrout_shows_on_the_screen(emu):
    before = [emu.screen_text(r) for r in range(25)]
    run_reference(emu)
    after = [emu.screen_text(r) for r in range(25)]
    changed = [(r, before[r], after[r]) for r in range(25) if before[r] != after[r]]
    assert len(changed) == 1
    row, old, new = changed[0]
    assert (old, new) == ("", "a")                   # screen code $01


def test_chrout_touches_only_the_screen_pointer(emu):
    emu.memory.io_log.clear()
    run_reference(emu)
    log = dict(emu.memory.io_log)
    assert log and all(k.startswith("R $D06") for k in log), log
