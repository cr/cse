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
banks 2-3 writable.  (`Q` back to BASIC 65 joins with P2, when the
REPL first runs on m65; `_main` stops at its first pending body.)

Not collected by a plain `pytest` (testpaths); run it by path:

    pytest tests/emulator
"""

import pathlib
import shutil

import pytest

from conftest import _m65_prg
from m65emu import M65Emu
from m65emu.harness import CSE_BP, load_snapshot, snapshot_dirs
from xmega65 import SDIMG, XMEGA65, XMega65

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORK = ROOT / "build" / "m65_boot"
CSE_MAP = (0xE300, 0xB300)
BANK3 = 0x30000
RESERVE = 0x3C000                      # 3.C000-3.CFFF, CSE's unused reserve
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


pytestmark = pytest.mark.skipif(_missing() is not None, reason=str(_missing()))


@pytest.fixture(scope="module",
                params=_SNAPSHOTS or [None],
                ids=[d.name for d in _SNAPSHOTS] or ["no-snapshot"])
def booted(request):
    """(xmega65's machine at _main, M65Emu's install_prg() machine) on
    one ROM: the registers at the hit, and the regions compared."""
    if request.param is None:
        pytest.skip("no M65Emu snapshot (it holds the ROM): "
                    "python dev/capture_m65_state.py --rom PATH")
    snap = load_snapshot(request.param)
    prg, map_path = _m65_prg("debug")
    ref = M65Emu(snap)
    ref.install_prg(prg, map_path)
    s = ref.sym
    regions = {
        "CSE's page 0.1F00": (CSE_BP << 8, 0x100),
        "CODE + RODATA": (BANK3 + s("__CODE_RUN__"),
                          s("__CODE_SIZE__") + s("__RODATA_SIZE__")),
        "KDATA + BSS": (BANK3 + s("__KDATA_RUN__"),
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
    assert hit["sp"] == 0x01F1                       # STACK_TOP
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
