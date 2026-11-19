"""test_m65emu.py — M65Emu on the real MEGA65 KERNAL (Tier I).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Runs on each post-boot snapshot dev/capture_m65_state.py records in
xmega65, one per ROM (build/m65_state/<ROM version>/, never
committed), through the m65_snapshot fixture; skipped, with the
command that makes one, when there is none.  The snapshot's reference runs are
replayed in the order they were recorded — "chrout" (one character)
and "scroll" (30 RETURNs: the KERNAL scrolls by DMA) — and must leave
the registers and memory xmega65 left.  GETIN reads keys injected into
the keyboard queue.  The parity calls reach the real KERNAL as on the
C64: a jiffy tick runs the IRQ handler's frame work (the STOP scan
into $91) and is acknowledged, press_stop() makes STOP ($FFE1) report
the key, press_restore() enters the NMI handler, which reads $DD0D,
and set_cursor() moves the cursor where PLOT reads it back.  An NMI
reaches INMI ($0318) through the KERNAL's entry with the five-byte
frame the debugger's handlers read, and MAP holds it until EOM (the
debugger's map switches rely on both: platform_layer.md § Interrupt
frame, § User transitions).  A virtual drive on an IEC unit (10)
serves the KERNAL's own OPEN / CHKIN / CHRIN / LOAD, with READSS
reporting EOI; with no drive on the unit OPEN fails as "device not
present" — $D012 advances, so the KERNAL's IEC delays end
(testing.md § The m65 PRG on M65Emu, *The disk on m65*).
"""

import pytest

from m65emu import M65Emu

REGS = ("pc", "a", "x", "y", "z", "b", "sp", "p", "mapl", "maph")
RUNS = ("chrout", "scroll")             # capture_m65_state.py's, in order


@pytest.fixture
def emu(m65_snapshot):
    emu = M65Emu(m65_snapshot)
    emu.reference = m65_snapshot["reference"]["runs"]
    return emu


def replay(emu, run):
    """Run a reference run's code as it was planted; the step count."""
    emu.memory.load(run["at"], bytes.fromhex(run["code"]))
    return emu.run_until(run["end"], start_at=run["at"], max_cycles=1_000_000)


def replay_up_to(emu, name):
    for run in emu.reference:
        if run["name"] == name:
            return run
        replay(emu, run)
    raise KeyError(name)


@pytest.mark.parametrize("name", RUNS)
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
    replay(emu, emu.reference[0])
    after = [emu.screen_text(r) for r in range(25)]
    changed = [(before[r], after[r]) for r in range(25) if before[r] != after[r]]
    assert changed == [("", "a")]                    # screen code $01


def test_scrolling_uses_only_modelled_io(emu):
    replay_up_to(emu, "scroll")
    emu.memory.io_log.clear()
    replay(emu, emu.reference[1])
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


NMI_TARGET = 0x1E40                      # a JMP-self loop the test points INMI at


def park_inmi(emu):
    emu.memory.load(NMI_TARGET, bytes([0x4C, NMI_TARGET & 0xFF, NMI_TARGET >> 8]))
    emu.write_word(0x0318, NMI_TARGET)


def frame(emu):
    """The eight bytes above SP: B Z Y X A, then the CPU's P PCL PCH."""
    return [emu.memory[0x100 | (emu.cpu.sp + k) & 0xFF] for k in range(1, 9)]


def test_nmi_reaches_inmi_with_the_kernals_five_byte_frame(emu):
    """The KERNAL's NMI entry pushes A X Y Z B, sets B = 0, keeps the
    map and jumps through INMI — the frame cse_nmi_handler finds."""
    idle(emu, cli=False)
    park_inmi(emu)
    cpu = emu.cpu
    cpu.a, cpu.x, cpu.y, cpu.z, cpu.b = 0x11, 0x22, 0x33, 0x44, 0x16
    p, sp, maps = cpu.p, cpu.sp, (cpu.mapl, cpu.maph)
    emu.schedule_nmi(1)
    emu.run_steps(300)
    assert emu.pc == NMI_TARGET
    assert frame(emu) == [0x16, 0x44, 0x33, 0x22, 0x11, p & ~cpu.BREAK,
                          LOOP & 0xFF, LOOP >> 8]
    assert cpu.sp == sp - 8                          # 16-bit SP, page 1
    assert cpu.b == 0
    assert (cpu.mapl, cpu.maph) == maps


def test_map_holds_an_nmi_until_eom(emu):
    """An NMI due right after MAP is taken only once EOM has run: the
    stacked PC is the instruction after EOM (book 14-23, K-7/8)."""
    code = 0x1E00
    cpu = emu.cpu
    body = [0x5C, 0xE8, 0xE8, 0xEA]                   # MAP · INX · INX · EOM
    park = code + len(body)
    emu.memory.load(code, bytes(body + [0x4C, park & 0xFF, park >> 8]))
    park_inmi(emu)
    cpu.p |= cpu.INTERRUPT
    cpu.a, cpu.x = cpu.mapl & 0xFF, cpu.mapl >> 8      # MAP onto the same map
    cpu.y, cpu.z = cpu.maph & 0xFF, cpu.maph >> 8
    emu.pc = code
    emu.schedule_nmi(1)
    emu.run_steps(300)
    assert emu.pc == NMI_TARGET
    assert frame(emu)[6:] == [park & 0xFF, park >> 8]


def test_set_cursor_moves_the_cursor_plot_reads(emu):
    emu.set_cursor(5, 10)
    emu.jsr(0xFFF0, carry=True)                      # PLOT: read
    assert (emu.x, emu.y) == (5, 10)


# ── the virtual drive on an IEC unit (P3 T1) ──────────────────────

UNIT = 10                               # not CBDOS's (8 / 9)
SETNAM, SETLFS, SETBNK, OPEN, CLOSE = 0xFFBD, 0xFFBA, 0xFF6B, 0xFFC0, 0xFFC3
CHKIN, CHRIN, CLRCHN, READST, LOAD = 0xFFC6, 0xFFCF, 0xFFCC, 0xFFB7, 0xFFD5
SETMSG = 0xFF90
NAME = 0x1600                           # bank 0, free for programs


def kernal(emu, entry, **regs):
    emu.jsr(entry, b=0, **regs)


def open_file(emu, name, lfn=2, sa=2):
    emu.memory.load(NAME, name)
    kernal(emu, SETNAM, a=len(name), x=NAME & 0xFF, y=NAME >> 8)
    kernal(emu, SETBNK, a=0, x=0)
    kernal(emu, SETLFS, a=lfn, x=UNIT, y=sa)
    kernal(emu, OPEN)


def test_a_drive_on_an_iec_unit_serves_the_kernals_open_and_chrin(emu):
    drive = emu.attach_drive(UNIT)
    drive.put("HELLO", b"ABC", type="SEQ")
    open_file(emu, b"HELLO,S,R")
    assert not emu.carry
    kernal(emu, CHKIN, x=2)
    got = []
    for _ in range(3):
        kernal(emu, CHRIN)
        got.append(emu.a)
        kernal(emu, READST)
        status = emu.a
    assert bytes(got) == b"ABC"
    assert status & 0x40                       # EOI with the last byte
    kernal(emu, CLRCHN)
    kernal(emu, CLOSE, a=2)


def test_a_drive_on_an_iec_unit_serves_load(emu):
    """The KERNAL's messages off, as for a RUN-started program (the
    snapshot is BASIC's direct mode, where LOAD prints LOADING)."""
    kernal(emu, SETMSG, a=0)
    emu.attach_drive(UNIT).put("PROG", bytes([0x00, 0x30, 1, 2, 3]))
    emu.memory.load(NAME, b"PROG")
    kernal(emu, SETNAM, a=4, x=NAME & 0xFF, y=NAME >> 8)
    kernal(emu, SETBNK, a=0, x=0)
    kernal(emu, SETLFS, a=1, x=UNIT, y=1)
    kernal(emu, LOAD, a=0)
    assert not emu.carry
    assert [emu.memory.read_flat(0x3000 + k) for k in range(3)] == [1, 2, 3]


def test_an_absent_iec_unit_fails_instead_of_hanging(emu):
    open_file(emu, b"NOTHING,S,R")
    kernal(emu, READST)
    assert emu.a & 0x80                        # device not present
