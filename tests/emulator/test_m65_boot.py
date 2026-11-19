"""test_m65_boot.py — the m65 PRG boots to `_main` in xmega65 (Tier X).

Owner: doc/build_system.md

Contract source: [doc/testing.md § The m65 PRG on M65Emu](../../doc/testing.md#the-m65-prg-on-m65emu)
(*Tier X, boot and quit*) and [doc/memory_design.md § Memory Map — m65](../../doc/memory_design.md#memory-map--m65-mega65-mode)
(*The installed machine*); T10 of TODO § M65 slice 2, P0.

On each ROM that has an M65Emu snapshot (the snapshot holds the ROM
image, so the ROM is taken from it), xmega65 boots that ROM from the
SD clone and RUNs the debug m65 PRG (`-prg`, `-prgmode 65`).  A
breakpoint on `_main`'s address stops it there — the hit with
`B = CSE_BP`, because under the CSE map (BASIC 65's own) that address
is BASIC's code until the loader replaces it.  The machine must be
the one M65Emu's install_prg() makes from the same ROM, which
test_loader.py holds to the real loader: the CSE map, `B`, SP, the
resident stub and CSE's base page, the images in bank 3, BSS cleared,
banks 2-3 writable.

P2 (T11): the PRG runs on to the prompt, and commands typed in
xmega65 — one key at a time, put into the KERNAL's buffer by `ADDKEY`
from a driver in bank 0 that returns to where main_loop stopped —
leave the screen M65Emu's M65Session leaves after the same keys (the
splash, `?`, `i`, `m`, `r`, `.`, `d`, the editor and back, 80 x 50 and
back), compared as text.  `Q` and `y` end in BASIC 65 at READY, banks
2-3 the ROM's again.

Not collected by a plain `pytest` (testpaths); run it by path:

    pytest tests/emulator
"""

import pathlib
import shutil
import sys
import time

import pytest

from emu_base import decode_screen_codes
from m65emu import M65Emu
from m65emu.harness import (BANK_CSE, CSE_BP, CSE_MAP, STACK_TOP, flat,
                            load_snapshot, snapshot_dirs)
from xmega65 import SDIMG, XMEGA65, XMega65

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tests" / "integration"))
from test_m65_repl import M65Session                            # noqa: E402
WORK = ROOT / "build" / "m65_boot"
RESERVE = flat(BANK_CSE, 0xC000)       # 3.C000-3.CFFF, CSE's unused reserve
# The ROM's parts CSE does not take (memory_design.md § Memory Map —
# m65): CBDOS, the interface ROM, the monitor, character set B and the
# KERNAL.  The loader overwrites CSE's own regions of banks 2-3.
ROM_KEPT = ((0x20000, 0x24000), (0x2C000, 0x2D000), (0x30000, 0x32000),
            (0x3D000, 0x40000))

_SNAPSHOTS = snapshot_dirs()


def _missing():
    if not pathlib.Path(XMEGA65).exists():
        return f"no xmega65 at {XMEGA65} (set $XMEGA65)"
    if not SDIMG.exists():
        return f"no configured MEGA65 SD image at {SDIMG}"
    if shutil.which("mcopy") is None:
        return "no mcopy (mtools) to put the ROM onto the SD clone"
    return None


_MISSING = _missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))


@pytest.fixture(scope="module",
                params=_SNAPSHOTS or [None],
                ids=[d.name for d in _SNAPSHOTS] or ["no-snapshot"])
def booted(request, cse_m65_prg):
    """(xmega65's machine at _main, M65Emu's install_prg() machine) on
    one ROM: the registers at the hit, and the regions compared."""
    if request.param is None:
        pytest.skip("no M65Emu snapshot (it holds the ROM): "
                    "python dev/capture_m65_state.py --rom PATH")
    snap = load_snapshot(request.param)
    prg, map_path = cse_m65_prg
    ref = M65Emu(snap)
    ref.install_prg(prg, map_path)
    s = ref.sym
    regions = {
        "CSE's page 0.1F00": (CSE_BP << 8, 0x100),
        "CODE + RODATA": (flat(BANK_CSE, s("__CODE_RUN__")),
                          s("__CODE_SIZE__") + s("__RODATA_SIZE__")),
        "KDATA + BSS": (flat(BANK_CSE, s("__KDATA_RUN__")),
                        s("__KDATA_SIZE__") + s("__BSS_SIZE__")),
    }
    work = WORK / request.param.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rom = work / "rom.bin"
    rom.write_bytes(snap["chip"][0x20000:0x40000])
    try:
        with XMega65(work / "run", rom=rom, prg=prg) as xm:
            for _ in range(50):
                hit = xm.run_to(s("_main"), at_hit=True)
                if hit["b"] == CSE_BP:
                    break
            else:
                pytest.fail(f"_main not reached with B = CSE_BP: {hit}")
            got = {name: xm.read(lo, n) for name, (lo, n) in regions.items()}
            old = xm.read(RESERVE, 1)[0]
            xm.write(RESERVE, [old ^ 0xFF])
            writable = xm.read(RESERVE, 1)[0] == old ^ 0xFF
            xm.write(RESERVE, [old])
            kept = [xm.read(lo, hi - lo) for lo, hi in ROM_KEPT]
    finally:
        shutil.rmtree(work, ignore_errors=True)
    want = {name: bytes(ref.memory.read_flat(a) for a in range(lo, lo + n))
            for name, (lo, n) in regions.items()}
    rom_kept = [snap["chip"][lo:hi] for lo, hi in ROM_KEPT]
    return dict(hit=hit, got=got, want=want, writable=writable,
                rom_ok=kept == rom_kept)


def test_the_rom_booted_is_the_one_given(booted):
    """Where CSE leaves it: CBDOS, the interface ROM, the monitor, the
    character set and the KERNAL are the given ROM's."""
    assert booted["rom_ok"]


def test_main_is_entered_under_the_cse_map_with_cses_base_page(booted):
    hit = booted["hit"]
    assert (hit["mapl"], hit["maph"]) == CSE_MAP
    assert hit["b"] == CSE_BP
    assert hit["sp"] == 0x0100 | STACK_TOP
    assert hit["p"] & 0x04, "interrupts off"


@pytest.mark.parametrize("region", ["CSE's page 0.1F00", "CODE + RODATA",
                                    "KDATA + BSS"])
def test_the_installed_machine_is_install_prgs(booted, region):
    got, want = booted["got"][region], booted["want"][region]
    diff = next((k for k in range(len(want)) if got[k] != want[k]), None)
    assert diff is None, (f"{region} +${diff:04X}: xmega65 ${got[diff]:02X}, "
                          f"M65Emu ${want[diff]:02X}")


def test_banks_2_3_are_writable(booted):
    assert booted["writable"]


# ── T11: the prompt, typed commands, Q (P2) ───────────────────────

DRIVER = 0x1E00                    # bank 0: visible in the CSE map
ADDKEY = 0xFF4A
STOP, ESC = 0x03, 0x1B
SCRIPT = [b"? 1+2\r", b"I\r", b"M\r", b"R\r", b". LDA #1\r", b"@ $2000\r",
          b"D\r", bytes([STOP]) + b"NOP\r" + bytes([STOP]),
          bytes([ESC]) + b"5" + b"? 3\r", bytes([ESC]) + b"8"]
QUIT = bytes([0xD1, 0x0D]) + b"Y"     # `Q` is shifted: PETSCII $D1


def _driver(keys, back):
    """ADDKEY each of `keys` with B = 0, every register and P kept,
    then on at `back` (where main_loop stopped)."""
    code = [0x08, 0x48, 0xDA, 0x5A, 0xDB, 0x7B, 0x48,   # php pha phx phy phz tba pha
            0xA9, 0x00, 0x5B]                           # lda #0, tab
    for k in keys:
        code += [0xA9, k, 0x20, ADDKEY & 0xFF, ADDKEY >> 8]
    return code + [0x68, 0x5B, 0xFB, 0x7A, 0xFA, 0x68, 0x28,   # pla tab plz ply plx pla plp
                   0x4C, back & 0xFF, back >> 8]


def _screen_text(read, width, height, bank):
    raw = read(flat(bank, 0x0800), width * height)
    return [decode_screen_codes(raw[r * width:(r + 1) * width]) for r in range(height)]


@pytest.fixture(scope="module",
                params=_SNAPSHOTS or [None],
                ids=[d.name for d in _SNAPSHOTS] or ["no-snapshot"])
def typed(request, cse_m65_prg):
    """The screens after each step of SCRIPT in xmega65 and in M65Emu,
    and BASIC 65 after QUIT."""
    if request.param is None:
        pytest.skip("no M65Emu snapshot (it holds the ROM): "
                    "python dev/capture_m65_state.py --rom PATH")
    snap = load_snapshot(request.param)
    prg, map_path = cse_m65_prg
    ref = M65Session((prg, map_path), snap)
    s = ref.e.sym
    want = [ref.rows()]
    for keys in SCRIPT:
        ref.keys(keys)
        want.append(ref.rows())

    def geometry(read):
        cell = lambda n: read(flat(BANK_CSE, s(n)), 1)[0]        # BSS
        width = read(CSE_BP << 8 | s("scr_width"), 1)[0]
        return width, cell("scr_height"), cell("scr_bank")

    work = WORK / ("typed-" + request.param.name)
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rom = work / "rom.bin"
    rom.write_bytes(snap["chip"][0x20000:0x40000])
    try:
        with XMega65(work / "run", rom=rom, prg=prg) as xm:
            for _ in range(50):
                if xm.run_to(s("_main"), at_hit=True)["b"] == CSE_BP:
                    break
            cold = xm.run_to(s("main_loop_top"), at_hit=True)
            xm.run_to(s("main_loop"))
            got = [_screen_text(xm.read, *geometry(xm.read))]

            def type_in(keys):
                back = xm.regs()["pc"]
                xm.write(DRIVER, _driver(keys, back))
                xm.cmd(f"g {DRIVER:x}")

            def key(k):
                type_in([k])
                return xm.run_to(s("main_loop"))

            for keys in SCRIPT:
                for k in keys:
                    key(k)
                got.append(_screen_text(xm.read, *geometry(xm.read)))
            key(QUIT[0])
            type_in(QUIT[1:])           # RETURN, then y for the query's io_getc
            xm.cmd("b 0")               # the breakpoint off main_loop (PC never 0)
            xm.cmd("t0")                # run on
            # BASIC 65's map is CSE's, so wait_for_basic cannot tell
            # them apart: wait for READY on the screen instead
            deadline = time.time() + 60
            while True:
                ready = decode_screen_codes(xm.read(0x0800, 80 * 25))
                if "ready." in ready or time.time() > deadline:
                    break
                time.sleep(0.5)
            banks = xm.read(0x20000, 0x20000)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dict(cold=cold, got=got, want=want, ready=ready,
                banks_ok=banks == snap["chip"][0x20000:0x40000])


def test_the_cold_start_reaches_the_prompt(typed):
    assert (typed["cold"]["mapl"], typed["cold"]["maph"]) == CSE_MAP
    assert typed["got"][0][24] == "2000:"


@pytest.mark.parametrize("step", range(len(SCRIPT) + 1),
                         ids=["splash"] + [k.decode("latin-1").strip() or "key"
                                           for k in SCRIPT])
def test_the_screen_is_m65emus(typed, step):
    assert typed["got"][step] == typed["want"][step]


def test_q_ends_in_basic_65_with_banks_2_3_reloaded(typed):
    assert "ready." in typed["ready"]
    assert typed["banks_ok"]
