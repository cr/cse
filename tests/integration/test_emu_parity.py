"""test_emu_parity.py — what C64Emu and M65Emu share, tested on both.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu, Interface](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier I.  Every test runs on a blank C64Emu (the C64 KERNAL, the
synthesised state) and a blank M65Emu (no ROM, no snapshot): the
interrupt scheduler and the jiffy tick, the keyboard matrix with STOP
and RESTORE, key injection, load_prg() with segment relocation,
set_cursor() and init_cse().  The same `$01` value banks the RAM
vectors in on both.  C64-only cases stay in test_c64emu_*.py; the
MEGA65 KERNAL's side (the tick's frame work, STOP, RESTORE, PLOT) is
in test_m65emu.py.
"""

import pytest

from c64emu import C64Emu
from emu_base import EmuBase
from m65emu import M65Emu

USER_CODE = 0x3000
IRQ_HANDLER = 0x3100
NMI_HANDLER = 0x3200
DONE = 0xDFE0                  # run_until stops before fetching here
IRQ_COUNT, NMI_COUNT = 0x2000, 0x2001
RAM_VECTORS = 0x34             # $01: KERNAL out on both, RAM at $E000-$FFFF


def _queued_c64(emu):
    n = emu.memory[0xC6]
    return [emu.memory[0x0277 + k] for k in range(n)]


def _queued_m65(emu):
    mem, got = emu.memory, []
    while mem[0xD619] != 0xFF:
        got.append(mem[0xD619])
        mem[0xD619] = 0                       # dequeue
    return got


HARNESSES = {"c64": (C64Emu, _queued_c64), "m65": (M65Emu, _queued_m65)}


@pytest.fixture(params=sorted(HARNESSES))
def harness(request):
    return HARNESSES[request.param]


@pytest.fixture
def emu(harness):
    return harness[0]()


def poke(emu, addr, data):
    for k, v in enumerate(data):
        emu.memory[addr + k] = v


def install(emu):
    """A `JMP self` user loop, IRQ and NMI handlers that count and
    jump to DONE, their vectors in RAM, and the KERNAL banked out."""
    poke(emu, USER_CODE, [0x4C, USER_CODE & 0xFF, USER_CODE >> 8])
    for handler, count in ((IRQ_HANDLER, IRQ_COUNT), (NMI_HANDLER, NMI_COUNT)):
        poke(emu, handler, [0xEE, count & 0xFF, count >> 8,        # INC count
                            0x4C, DONE & 0xFF, DONE >> 8])         # JMP DONE
    emu.memory[0x01] = RAM_VECTORS
    emu.write_word(0xFFFE, IRQ_HANDLER)
    emu.write_word(0xFFFA, NMI_HANDLER)
    emu.memory[IRQ_COUNT] = emu.memory[NMI_COUNT] = 0
    emu.pc = USER_CODE


def install_ticker(emu):
    """The user loop and an IRQ handler that counts and returns (RTI)."""
    install(emu)
    poke(emu, IRQ_HANDLER, [0xEE, IRQ_COUNT & 0xFF, IRQ_COUNT >> 8, 0x40])


def irq_on(emu, on=True):
    if on:
        emu.cpu.p &= ~emu.cpu.INTERRUPT
    else:
        emu.cpu.p |= emu.cpu.INTERRUPT


# ── scheduled interrupts ──────────────────────────────────────────

def test_nmi_fires_when_due(emu):
    install(emu)
    emu.schedule_nmi(10)
    assert emu.run_until(DONE, max_cycles=1000) >= 10
    assert (emu.memory[NMI_COUNT], emu.memory[IRQ_COUNT]) == (1, 0)


def test_nmi_ignores_the_i_flag(emu):
    install(emu)
    irq_on(emu, False)
    emu.schedule_nmi(5)
    emu.run_until(DONE, max_cycles=1000)
    assert emu.memory[NMI_COUNT] == 1


def test_each_nmi_fires_once(emu):
    install(emu)
    emu.schedule_nmi(5)
    emu.schedule_nmi(10)
    emu.run_until(DONE, max_cycles=1000)
    assert emu.memory[NMI_COUNT] == 1


def test_irq_fires_when_i_is_clear(emu):
    install(emu)
    irq_on(emu)
    emu.schedule_irq(5)
    emu.run_until(DONE, max_cycles=1000)
    assert emu.memory[IRQ_COUNT] == 1


def test_each_irq_fires_once_also_when_due_together(emu):
    install_ticker(emu)
    irq_on(emu)
    emu.schedule_irq(5)
    emu.schedule_irq(5)
    emu.schedule_irq(400)
    emu.run_steps(100)
    assert emu.memory[IRQ_COUNT] == 2                            # not the late one yet
    emu.run_steps(400)
    assert emu.memory[IRQ_COUNT] == 3


def test_irq_waits_while_i_is_set(emu):
    install(emu)
    irq_on(emu, False)
    emu.schedule_irq(5)
    emu.run_steps(500)
    assert emu.memory[IRQ_COUNT] == 0


def test_irq_fires_after_cli(emu):
    install(emu)
    poke(emu, USER_CODE, [0x78, 0x58, 0x4C, (USER_CODE + 2) & 0xFF,
                          (USER_CODE + 2) >> 8])                 # SEI; CLI; JMP *
    emu.schedule_irq(1)
    emu.run_until(DONE, max_cycles=1000)
    assert emu.memory[IRQ_COUNT] == 1


def test_irq_pushes_pc_and_p_without_b(emu):
    install(emu)
    irq_on(emu)
    emu.sp = emu.sp | 0xFF
    emu.schedule_irq(1)
    emu.run_until(DONE, max_cycles=1000)
    assert emu.sp & 0xFF == 0xFC
    assert emu.memory[0x01FD] & 0x10 == 0                        # B clear
    assert emu.read_word(0x01FE) == USER_CODE


def test_cancel_drops_every_pending_interrupt(emu):
    install(emu)
    emu.schedule_irq(5)
    emu.schedule_nmi(10)
    emu.cancel_pending_interrupts()
    irq_on(emu)
    emu.run_steps(500)
    assert (emu.memory[IRQ_COUNT], emu.memory[NMI_COUNT]) == (0, 0)


# ── the jiffy tick ────────────────────────────────────────────────

def test_jiffy_ticks_once_per_interval(emu):
    install_ticker(emu)
    irq_on(emu)
    emu.enable_jiffy_clock(interval=1000)
    emu.run_steps(5000)
    assert 4 <= emu.memory[IRQ_COUNT] <= 6


def test_jiffy_waits_while_i_is_set(emu):
    install_ticker(emu)
    irq_on(emu, False)
    emu.enable_jiffy_clock(interval=200)
    emu.run_steps(2000)
    assert emu.memory[IRQ_COUNT] == 0


def test_a_tick_due_while_i_is_set_fires_once_i_clears(emu):
    install_ticker(emu)
    irq_on(emu, False)
    emu.enable_jiffy_clock(interval=100)
    emu.run_steps(150)
    irq_on(emu)
    emu.run_steps(10)
    assert emu.memory[IRQ_COUNT] == 1                            # it waited
    emu.run_steps(100)
    assert emu.memory[IRQ_COUNT] == 2                            # the next: from then


def test_disable_stops_the_ticks(emu):
    install_ticker(emu)
    irq_on(emu)
    emu.enable_jiffy_clock(interval=500)
    emu.run_steps(1200)
    ticks = emu.memory[IRQ_COUNT]
    assert ticks >= 1
    emu.disable_jiffy_clock()
    emu.run_steps(2000)
    assert emu.memory[IRQ_COUNT] == ticks


def test_default_interval_is_the_c64_kernals(emu):
    assert EmuBase.JIFFY_INTERVAL == type(emu).JIFFY_INTERVAL == 16421
    install_ticker(emu)
    irq_on(emu)
    emu.enable_jiffy_clock()
    emu.run_steps(16420)
    assert emu.memory[IRQ_COUNT] == 0
    emu.run_steps(10)
    assert emu.memory[IRQ_COUNT] == 1


# ── the keyboard matrix ───────────────────────────────────────────

def scan(emu, col=None):
    """$DC01 with one column selected (a 0 bit in $DC00), or all."""
    emu.memory[0xDC00] = 0x00 if col is None else ~(1 << col) & 0xFF
    return emu.memory[0xDC01]


def test_no_key_reads_all_ones(emu):
    assert scan(emu) == 0xFF


def test_a_key_clears_its_row_in_its_column_only(emu):
    emu.press_key("A")                                           # row 1, col 2
    assert scan(emu, 2) == 0xFD
    assert scan(emu, 3) == 0xFF
    assert scan(emu) == 0xFD


def test_keys_in_one_column_and_in_two(emu):
    emu.press_key("A")                                           # row 1, col 2
    emu.press_key("D")                                           # row 2, col 2
    emu.press_key("B")                                           # row 3, col 4
    assert scan(emu, 2) == 0xF9
    assert scan(emu, 4) == 0xF7
    assert scan(emu) == 0xF1


def test_release_one_and_release_all(emu):
    emu.press_key("A")
    emu.press_key("B")
    emu.release_key("A")
    assert scan(emu) == 0xF7
    emu.release_all_keys()
    assert scan(emu) == 0xFF


def test_stop_is_row_7_column_7(emu):
    emu.press_stop()
    assert scan(emu, 7) == 0x7F
    emu.release_stop()
    assert scan(emu, 7) == 0xFF


@pytest.mark.parametrize("key", ["a", 0x41, 0xC1])
def test_key_spellings_reach_the_same_cell(emu, key):
    emu.press_key(key)
    assert scan(emu, 2) == 0xFD


def test_unknown_key_raises(emu):
    with pytest.raises(KeyError):
        emu.press_key("~")


# ── RESTORE ───────────────────────────────────────────────────────

def test_restore_raises_an_nmi(emu):
    install(emu)
    irq_on(emu, False)
    emu.press_restore()
    emu.run_until(DONE, max_cycles=100)
    assert emu.memory[NMI_COUNT] == 1


def test_restore_latches_cia2_icr_until_read(emu):
    emu.press_restore()
    assert emu.memory[0xDD0D] & 0x10
    assert emu.memory[0xDD0D] == 0


# ── key injection ─────────────────────────────────────────────────

def test_inject_key_and_inject_keys_queue_alike(harness):
    cls, queued = harness
    one, many = cls(), cls()
    for b in b"HI\r":
        one.inject_key(b)
    many.inject_keys(b"HI\r")
    assert queued(one) == queued(many) == [0x48, 0x49, 0x0D]


# ── load_prg ──────────────────────────────────────────────────────

def test_load_prg_puts_the_payload_at_its_address(emu, tmp_path):
    prg = tmp_path / "t.prg"
    prg.write_bytes(bytes([0x00, 0x20, 0xA9, 0x42, 0x60]))        # LDA #$42; RTS
    assert emu.load_prg(prg) == 0x2000
    emu.jsr(0x2000)
    assert emu.a == 0x42


def test_load_prg_reads_the_symbols_beside_the_map(emu, tmp_path):
    (tmp_path / "t.prg").write_bytes(bytes([0x00, 0x20, 0x60]))
    (tmp_path / "t.lbl").write_text("al 002000 .my_func\n")
    emu.load_prg(tmp_path / "t.prg", tmp_path / "t.map")
    assert emu.sym("my_func") == 0x2000


def test_load_prg_copies_a_relocated_segment_to_its_run_address(emu, tmp_path):
    (tmp_path / "t.prg").write_bytes(bytes([0x00, 0x20, 0x11, 0x22, 0x33, 0x44]))
    (tmp_path / "t.lbl").write_text(
        "al 002002 .__HIGH_LOAD__\nal 004000 .__HIGH_RUN__\nal 000002 .__HIGH_SIZE__\n"
        "al 002000 .__LOW_LOAD__\nal 002000 .__LOW_RUN__\nal 000002 .__LOW_SIZE__\n")
    emu.load_prg(tmp_path / "t.prg")
    assert [emu.memory[a] for a in (0x4000, 0x4001, 0x4002)] == [0x33, 0x44, 0x00]
    assert [emu.memory[a] for a in (0x2000, 0x2001)] == [0x11, 0x22]


# ── set_cursor and init_cse ───────────────────────────────────────

def test_set_cursor_calls_plot_with_carry_clear(emu):
    """PLOT ($FFF0) replaced, in RAM, by a routine that records its
    row (X), column (Y) and flags."""
    emu.memory[0x01] = RAM_VECTORS
    poke(emu, 0xFFF0, [0x4C, 0x00, 0x33])                        # JMP $3300
    poke(emu, 0x3300, [0x8E, 0x00, 0x21, 0x8C, 0x01, 0x21,       # STX/STY
                       0x08, 0x68, 0x8D, 0x02, 0x21, 0x60])      # PHP PLA STA RTS
    emu.carry = True
    emu.set_cursor(12, 34)
    assert (emu.memory[0x2100], emu.memory[0x2101]) == (12, 34)
    assert emu.memory[0x2102] & 0x01 == 0                        # carry clear


INIT_ROUTINES = ("theme_init", "restore_colors", "setup_interrupts",
                 "dbg_init", "sym_clear", "ed_ensure_init")


@pytest.mark.parametrize("editor", [False, True])
def test_init_cse_calls_the_cold_init_routines_in_order(emu, tmp_path, editor):
    """Each routine appends its number to a log at $2100 ($20F0
    counts) and returns."""
    code, lbl = [], []
    for k, name in enumerate(INIT_ROUTINES):
        lbl.append(f"al {0x3400 + len(code):06X} .{name}\n")
        code += [0xAE, 0xF0, 0x20, 0xA9, k, 0x9D, 0x00, 0x21,     # LDX; LDA #k; STA,X
                 0xEE, 0xF0, 0x20, 0x60]                         # INC; RTS
    (tmp_path / "t.prg").write_bytes(bytes([0x00, 0x34] + code))
    (tmp_path / "t.lbl").write_text("".join(lbl))
    emu.load_prg(tmp_path / "t.prg")
    emu.memory[0x20F0] = 0
    emu.init_cse(editor=editor)
    n = emu.memory[0x20F0]
    assert [emu.memory[0x2100 + k] for k in range(n)] == \
        list(range(6 if editor else 5))
