"""
test_m65_help.py — the HELP popup on the m65 PRG (Tier I)

Owner: doc/modules/help.md

Contract source: help.md § The window, § Keys, § Saving the screen;
main.md § Global keys (HELP).  The window is 40 columns wide and the
screen's full height, centred in 80 columns; its rows are compared
whole against the text `dev/help_text.py` encodes.  Closing it leaves
the screen byte for byte as it was, in the REPL and in the editor.
The glyphs of its border are Tier X's (M65Emu has no character ROM).
"""

import pathlib
import sys

import pytest

from m65emu.harness import TEXT_MODES as MODES, BANK_CSE, flat
from test_m65_repl import M65Session

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import help_text as H                            # noqa: E402

HELP, ESC, STOP, RETURN = 0x84, 0x1B, 0x03, 0x0D
CRSR_DN, CRSR_UP, HOME = 0x11, 0x91, 0x13
TL, TR, BL, BR, HL, VL = 0x70, 0x6E, 0x6D, 0x7D, 0x40, 0x5D
WIDE = 40                                        # the window's width
ST_REPL, ST_EDIT = 1, 2
REPL_SCREEN = 0xB000
LINES = H.load((pathlib.Path(H.__file__).parents[1] / "src" / "help.txt")
               .read_text(encoding="utf-8"))
TITLE, KEYS, MORE = " cse help ", " crsr scroll  help close ", " more "


@pytest.fixture
def s(cse_m65_prg, m65_snapshot):
    return M65Session(cse_m65_prg, m65_snapshot)


def in_mode(s, name):
    key, width, height, _ = MODES[name]
    if name != "80x25":
        s.mode(key)
    assert (s.width, s.height) == (width, height)


def screen(s):
    return [s.e.screen_row(r) for r in range(s.height)]


def settle(s, max_steps=3_000_000):
    """Run until the popup waits for a key with none queued."""
    e, cpu = s.e, s.e.cpu
    wait, key = e.sym("help_wait"), s.cell("io_key")
    end = e._steps + max_steps
    while not (cpu.pc == wait and not e.keyboard.queue and e.memory[key] == 0):
        if e._steps >= end:
            raise TimeoutError(f"help popup not waiting, pc=${cpu.pc:04X}")
        if cpu.pc == wait:
            e.run_steps(1)
        e.run_until(wait, max_cycles=max(1, end - e._steps))


def press(s, *keys):
    s.e.inject_keys(bytes(keys))
    settle(s)


def blips(s, fn):
    """How often io_blip ran during `fn`."""
    cpu, blip, n = s.e.cpu, s.e.sym("io_blip"), [0]
    step = cpu.step

    def watched():
        if cpu.pc == blip:
            n[0] += 1
        step()
    cpu.step = watched
    try:
        fn()
    finally:
        del cpu.step
    return n[0]


def bar(left_text, right_text, corner_l, corner_r):
    inner = H.encode(left_text) + bytes([HL] * (WIDE - 2 - len(left_text) - len(right_text)))
    return [corner_l] + list(inner) + list(H.encode(right_text) if right_text else b"") + [corner_r]


def window(top, height):
    """The window's rows (40 codes each) showing the text from line `top`."""
    shown = height - 2
    rows = [bar(TITLE, MORE if top > 0 else "", TL, TR)]
    for k in range(shown):
        n = top + k
        text = H.encode(LINES[n]) if n < len(LINES) else b""
        rows.append([VL, 0x20] + list(text) + [0x20] * (37 - len(text)) + [VL])
    rows.append(bar(KEYS, MORE if top + shown < len(LINES) else "", BL, BR))
    return rows


def check_window(s, before, top):
    """The window at its place, the rest of the screen `before` — with the
    cursor hidden, as main_loop hides it before handling a key."""
    left = (s.width - WIDE) // 2
    now = screen(s)
    before = [list(row) for row in before]
    cy, cx = s.v("io_cy"), s.v("io_cx")
    before[cy][cx] ^= 0x80
    want = window(top, s.height)
    for r in range(s.height):
        assert now[r][left:left + WIDE] == want[r], f"row {r}"
        assert now[r][:left] == before[r][:left], f"row {r} left of the window"
        assert now[r][left + WIDE:] == before[r][left + WIDE:], f"row {r} right of it"


# ── opening and closing ──────────────────────────────────────────────

@pytest.mark.parametrize("mode", ["80x25", "40x25", "80x50"])
def test_help_opens_the_window_and_closes_to_the_same_screen(s, mode):
    in_mode(s, mode)
    s.type("? 1")
    before, cursor = screen(s), (s.v("io_cx"), s.v("io_cy"))
    press(s, HELP)
    check_window(s, before, 0)
    s.keys(bytes([HELP]))
    assert screen(s) == before
    assert (s.v("io_cx"), s.v("io_cy")) == cursor
    assert s.v("state") == ST_REPL


@pytest.mark.parametrize("close", [HELP, ESC, STOP])
def test_help_esc_and_stop_close(s, close):
    before = screen(s)
    press(s, HELP)
    s.keys(bytes([close]))
    assert screen(s) == before
    assert s.v("state") == ST_REPL and s.v("esc_armed") == 0


def test_esc_that_closes_arms_no_mode_switch(s):
    press(s, HELP)
    s.keys(bytes([ESC, ord("4")]))
    assert (s.width, s.height) == (80, 25)


@pytest.mark.parametrize("close, carry", [(STOP, 1), (HELP, 0), (ESC, 0)])
def test_help_popup_returns_c_for_stop(s, close, carry):
    s.e.inject_keys(bytes([close]))
    s.call("help_popup")
    assert s.e.carry == carry


def test_stop_that_closes_sets_stop_cooldown(s):
    s.e.inject_keys(bytes([HELP, STOP]))
    s.e.run_until(s.e.sym("help_popup"), max_cycles=1_000_000)
    s.e.run_until(s.e.sym("main_loop"), max_cycles=3_000_000)
    assert s.v("stop_cooldown") == 1


def test_other_keys_are_ignored(s):
    before = screen(s)
    press(s, HELP)
    press(s, ord("a"), RETURN, ord("4"), ord("Q"))
    check_window(s, before, 0)
    s.keys(bytes([HELP]))
    assert screen(s) == before


# ── scrolling ────────────────────────────────────────────────────────

def test_crsr_scrolls_a_line_and_blips_at_the_ends(s):
    before = screen(s)
    last = len(LINES) - (s.height - 2)
    assert last > 0, "the text fits 80 x 25: nothing to scroll"
    press(s, HELP)
    assert blips(s, lambda: press(s, CRSR_UP)) == 1
    check_window(s, before, 0)
    assert blips(s, lambda: press(s, CRSR_DN)) == 0
    check_window(s, before, 1)
    for _ in range(last - 1):
        press(s, CRSR_DN)
    check_window(s, before, last)
    assert blips(s, lambda: press(s, CRSR_DN)) == 1
    check_window(s, before, last)
    press(s, CRSR_UP)
    check_window(s, before, last - 1)


def test_home_goes_to_the_top_and_it_reopens_there(s):
    before = screen(s)
    press(s, HELP, CRSR_DN, CRSR_DN, CRSR_DN)
    check_window(s, before, 3)
    press(s, HOME)
    check_window(s, before, 0)
    press(s, CRSR_DN)
    s.keys(bytes([HELP]))
    press(s, HELP)
    check_window(s, before, 0)


def test_80x50_scrolls_what_48_lines_do_not_show(s):
    in_mode(s, "80x50")
    before = screen(s)
    press(s, HELP, CRSR_DN)
    check_window(s, before, min(1, max(0, len(LINES) - 48)))


# ── in the editor, and RESTORE ───────────────────────────────────────

def test_help_over_the_editor_restores_it(s):
    s.type("? 1")
    s.keys(bytes([STOP]))
    assert s.v("state") == ST_EDIT
    s.keys(b"LDA #1\r")
    before = screen(s)
    size = s.v("scr_width") * s.v("scr_height")
    repl = [s.e.memory.read_flat(flat(BANK_CSE, REPL_SCREEN + k)) for k in range(size)]
    gap = (s.w("gap_lo"), s.w("gap_hi"))
    press(s, HELP)
    check_window(s, before, 0)
    press(s, CRSR_DN)
    s.keys(bytes([ESC]))
    assert screen(s) == before
    assert s.v("state") == ST_EDIT
    assert (s.w("gap_lo"), s.w("gap_hi")) == gap
    assert [s.e.memory.read_flat(flat(BANK_CSE, REPL_SCREEN + k)) for k in range(size)] == repl


def test_restore_while_open_redraws_the_repl(s):
    press(s, HELP)
    s.e.press_restore()
    s.idle(max_steps=6_000_000)
    assert s.v("state") == ST_REPL
    s.find(r"^[0-9a-f]{4}:$")
    assert not any(row[(s.width - WIDE) // 2] == TL for row in screen(s))
