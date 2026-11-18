"""test_m65emu.py — M65Emu on the real MEGA65 KERNAL (Tier I).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Runs from the post-boot snapshot dev/capture_m65_state.py records in
xmega65 (build/m65_state/, never committed); skipped, with the command
that makes it, when it is absent.  The snapshot's reference runs are
replayed in the order they were recorded — "chrout" (one character)
and "scroll" (30 RETURNs: the KERNAL scrolls by DMA) — and must leave
the registers and memory xmega65 left.  GETIN reads keys injected into
the keyboard queue.  The parity calls reach the real KERNAL as on the
C64: a jiffy tick runs the IRQ handler's frame work (the STOP scan
into $91) and is acknowledged, press_stop() makes STOP ($FFE1) report
the key, press_restore() enters the NMI handler, which reads $DD0D,
and set_cursor() moves the cursor where PLOT reads it back.
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
    """Run a reference run's code as it was planted; the step count."""
    emu.memory.load(run["at"], bytes.fromhex(run["code"]))
    return emu.run_until(run["end"], start_at=run["at"], max_cycles=1_000_000)


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
    code_end = run["at"] + len(bytes.fromhex(run["code"]))
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


LOOP = 0x1800


def idle(emu, *, cli):
    """Park the CPU in a `JMP self` loop at LOOP, interrupts on or off."""
    emu.memory.load(LOOP, bytes([0x4C, LOOP & 0xFF, LOOP >> 8]))
    emu.pc = LOOP
    if cli:
        emu.cpu.p &= ~emu.cpu.INTERRUPT
    else:
        emu.cpu.p |= emu.cpu.INTERRUPT


def test_jiffy_tick_runs_the_kernals_frame_work(emu):
    idle(emu, cli=True)
    emu.memory[0x91] = 0x00
    handler = emu.read_word(0x0314)
    emu.enable_jiffy_clock(interval=2000)
    hits = emu.run_steps(5000, watch={handler})
    assert len(hits) == 2
    assert emu.memory[0x91] == 0xFF                  # STOP scanned: up
    assert emu.memory[0xD019] & 0x0F == 0            # acknowledged


@pytest.mark.parametrize("held", [False, True])
def test_stop_reaches_the_kernal_through_the_matrix(emu, held):
    idle(emu, cli=True)
    if held:
        emu.press_stop()
    emu.enable_jiffy_clock(interval=500)
    emu.run_steps(1000)
    emu.disable_jiffy_clock()
    emu.jsr(0xFFE1)                                  # STOP
    assert emu.zero == held


def test_restore_enters_the_kernals_nmi_handler(emu):
    idle(emu, cli=False)
    handler = emu.read_word(0xFFFA)
    emu.press_restore()
    hits = [pc for pc, _ in emu.run_steps(200, watch={handler, LOOP})]
    assert hits[:2] == [LOOP, handler]
    assert emu.pc == LOOP                            # back in the loop
    assert emu.memory[0xDD0D] == 0                   # the handler read it


def test_set_cursor_moves_the_cursor_plot_reads(emu):
    emu.set_cursor(5, 10)
    emu.jsr(0xFFF0, carry=True)                      # PLOT: read
    assert (emu.x, emu.y) == (5, 10)
