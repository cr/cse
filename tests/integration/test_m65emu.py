"""test_m65emu.py — M65Emu on the real MEGA65 KERNAL (Tier I).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Runs from the post-boot snapshot dev/capture_m65_state.py records in
xmega65 (build/m65_state/, never committed); skipped, with the command
that makes it, when it is absent.  The snapshot's reference runs are
replayed in the order they were recorded — "chrout" (one character)
and "scroll" (30 RETURNs: the KERNAL scrolls by DMA) — and must leave
the registers and memory xmega65 left.  GETIN reads keys injected into
the keyboard queue.
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


def runs():
    return SNAPSHOT["reference"]["runs"] if SNAPSHOT else []


@pytest.fixture
def emu():
    return M65Emu(SNAPSHOT)


def replay(emu, run):
    """Run a reference run's code, parked at its end as recorded."""
    code = bytes.fromhex(run["code"])
    end = run["at"] + len(code)
    emu.memory.load(run["at"], code + bytes([0x4C, end & 0xFF, end >> 8]))
    emu.pc = run["at"]
    return emu.run_until(end, max_cycles=1_000_000)


def replay_up_to(emu, name):
    for run in runs():
        if run["name"] == name:
            return run
        replay(emu, run)
    raise KeyError(name)


@pytest.mark.parametrize("name", [r["name"] for r in runs()])
def test_reference_run_matches_xmega65(emu, name):
    run = replay_up_to(emu, name)
    chip = bytearray(emu.memory.chip[:0x20000])
    colour = bytes(emu.memory.read_flat(0xFF80000 + a) for a in range(0x8000))
    steps = replay(emu, run)
    if run["steps"] is not None:
        assert steps == run["steps"]
    assert {r: getattr(emu.cpu, r) for r in REGS} == run["after"]
    code_end = run["at"] + len(bytes.fromhex(run["code"])) + 3
    for a, v in run["chip_changes"].items():
        chip[int(a, 16)] = v
    got = emu.memory.chip[:0x20000]
    diff = {f"{a:05X}": (got[a], chip[a]) for a in range(0x20000)
            if got[a] != chip[a] and not run["at"] <= a < code_end}
    assert not diff, diff
    want_colour = bytearray(colour)
    for a, v in run["colour_changes"].items():
        want_colour[int(a, 16)] = v
    got_colour = bytes(emu.memory.read_flat(0xFF80000 + a) for a in range(0x8000))
    assert got_colour == want_colour


def test_chrout_shows_on_the_screen(emu):
    before = [emu.screen_text(r) for r in range(25)]
    replay(emu, runs()[0])
    after = [emu.screen_text(r) for r in range(25)]
    changed = [(before[r], after[r]) for r in range(25) if before[r] != after[r]]
    assert changed == [("", "a")]                    # screen code $01


def test_scrolling_uses_only_modelled_io(emu):
    replay_up_to(emu, "scroll")
    emu.memory.io_log.clear()
    replay(emu, runs()[1])
    assert all(k.startswith("R $D06") for k in emu.memory.io_log), \
        dict(emu.memory.io_log)


def test_getin_reads_injected_keys(emu):
    code = [0x78, 0x20, 0xE4, 0xFF]                  # SEI; JSR GETIN
    emu.memory.load(0x1800, bytes(code))
    emu.inject_keys(b"HI")
    got = []
    for _ in range(3):
        emu.pc = 0x1800
        emu.run_until(0x1804)
        got.append(emu.a)
    assert got == [0x48, 0x49, 0x00]
