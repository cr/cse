"""test_m65_break.py — a break in user code on the m65 PRG in xmega65 (Tier X).

Owner: doc/modules/debugger.md

Contract source: [doc/testing.md § The m65 PRG on M65Emu](../../doc/testing.md#the-m65-prg-on-m65emu)
(*Tier X, a break in user code*); T10 of TODO § M65 slice 2, P1.

On each ROM that has an M65Emu snapshot, xmega65 RUNs the debug m65
PRG and stops at `_main` (as test_m65_boot.py does).  A driver planted
in bank 0 (visible in the CSE map) then does what `_main` and
`main_loop` would — setup_interrupts, dbg_init, the globals — and
enters user code through return_to_userland; resumes go through
restore_userland_state.  Each break stops at hygiene_after_userland,
the first P2 body on the way back.

- A user BRK with every register set: the snapshot, the bank state,
  the map and B at the stop equal M65Emu's for the same run.
- A program that maps its own window, banks the I/O out and changes
  $D030, then breaks: resumed, it reads back what it set.

Not collected by a plain `pytest` (testpaths); run it by path:

    pytest tests/emulator
"""

import pathlib
import shutil
import sys

import pytest

from m65emu import M65Emu
from m65emu.harness import (BANK_CSE, CSE_BP, CSE_MAP, flat, load_snapshot,
                            snapshot_dirs)
from xmega65 import CHIP_ROM, DRIVER, XMega65, missing

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "integration"))
import test_m65_debugger as T                                   # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
WORK = ROOT / "build" / "m65_break"
WINDOW = 0x44000                 # what the program maps at $4000

_SNAPSHOTS = snapshot_dirs()


_MISSING = missing()
pytestmark = pytest.mark.skipif(_MISSING is not None, reason=str(_MISSING))

# The user BRK: every register non-zero (as test_m65_debugger's T8).
BRK_PROGRAM = [0xA9, 0x16, 0x5B, 0xA3, 0x44, 0xA0, 0x33,
               0xA2, 0x22, 0xA9, 0x11, 0x00, 0x00]
# The bank state: map block 2 to 4.4000, I/O out, $D030 = 0, BRK; then
# store the port, $D030 and $4000 at $1700 and return (test_m65_debugger's).
BANKED = T.BANKINGS["all three"]


def _flat_of(ref, name):
    """A CSE cell's flat address: the base page in 0.1F00, the rest in
    bank 3 behind the CSE map's windows."""
    v = ref.sym(name)
    return CSE_BP << 8 | v if v < 0x100 else flat(BANK_CSE, v)


def _abs(op, addr):
    return [op, addr & 0xFF, addr >> 8]


def _start_driver(ref, entry):
    """setup_interrupts, dbg_init, the globals, brk_pc = entry,
    return_to_userland (B = CSE_BP and the CSE map, as at _main)."""
    s, c = ref.sym, ref.cell
    code = _abs(0x20, s("setup_interrupts")) + _abs(0x20, s("dbg_init"))
    code += [0xA9, T.ST_REPL] + _abs(0x8D, c("state"))
    code += [0xA9, 0x00] + _abs(0x8D, c("run_user_pending"))
    for name in ("brk_pc", "cur_addr"):
        code += [0xA9, entry & 0xFF] + _abs(0x8D, c(name))
        code += [0xA9, entry >> 8] + _abs(0x8D, c(name) + 1)
    return code + _abs(0x4C, s("return_to_userland"))


def _resume_driver(ref):
    """`c`: SP back at the user's, then restore_userland_state."""
    return _abs(0xAE, ref.cell("reg_sp")) + [0x9A] + \
        _abs(0x4C, ref.sym("restore_userland_state"))


SNAPSHOT_CELLS = ("reg_a", "reg_x", "reg_y", "reg_z", "reg_b", "reg_p",
                  "reg_sp", "brk_pc", "dbg_reason")


def _snapshot(read, ref):
    out = {n: read(_flat_of(ref, n), 1)[0] for n in SNAPSHOT_CELLS}
    out["brk_pc"] |= read(_flat_of(ref, "brk_pc") + 1, 1)[0] << 8
    out["bank state"] = list(read(_flat_of(ref, "um_map"), 9))
    return out


@pytest.fixture(scope="module",
                params=_SNAPSHOTS or [None],
                ids=[d.name for d in _SNAPSHOTS] or ["no-snapshot"])
def runs(request, cse_m65_prg):
    """xmega65's two runs on one ROM, and M65Emu's for the first."""
    if request.param is None:
        pytest.skip("no M65Emu snapshot (it holds the ROM): "
                    "python dev/capture_m65_state.py --rom PATH")
    snap = load_snapshot(request.param)
    prg, map_path = cse_m65_prg
    ref = M65Emu(snap)
    ref.install_prg(prg, map_path)
    s = ref.sym
    stop = s("hygiene_after_userland")

    # M65Emu: the user BRK
    T.ready(ref)
    T.user_code(ref, BRK_PROGRAM)
    T.run_user(ref, T.USER)
    want = _snapshot(lambda a, n: bytes(ref.memory.read_flat(a + k) for k in range(n)), ref)
    want["map"], want["b"] = (ref.cpu.mapl, ref.cpu.maph), ref.b

    work = WORK / request.param.name
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    rom = work / "rom.bin"
    rom.write_bytes(snap["chip"][CHIP_ROM])
    try:
        with XMega65(work / "run", rom=rom, prg=prg) as xm:
            xm.run_to_page(s("_main"), CSE_BP)

            def to_stop():
                return xm.run_to_page(stop, CSE_BP)

            # 1. the user BRK
            xm.write(T.USER, BRK_PROGRAM)
            xm.write(DRIVER, _start_driver(ref, T.USER))
            xm.cmd(f"g {DRIVER:x}")
            hit1 = to_stop()
            got = _snapshot(xm.read, ref)
            got["map"], got["b"] = (hit1["mapl"], hit1["maph"]), hit1["b"]

            # 2. the bank state round trip
            prog = T.program(**BANKED)
            xm.write(T.CODE, prog)
            xm.write(WINDOW, [0xC7])
            xm.write(0x1700, [0] * 4)
            xm.write(DRIVER, _start_driver(ref, T.CODE))
            xm.cmd(f"g {DRIVER:x}")
            to_stop()
            reason_break = xm.read(_flat_of(ref, "dbg_reason"), 1)[0]
            pc = xm.read(_flat_of(ref, "brk_pc"), 2)
            pc = (pc[0] | pc[1] << 8) + 2                 # past BRK + signature
            xm.write(_flat_of(ref, "brk_pc"), [pc & 0xFF, pc >> 8])
            xm.write(DRIVER, _resume_driver(ref))
            xm.cmd(f"g {DRIVER:x}")
            to_stop()
            reason_end = xm.read(_flat_of(ref, "dbg_reason"), 1)[0]
            readback = list(xm.read(0x1700, 4))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dict(want=want, got=got, reason_break=reason_break,
                reason_end=reason_end, readback=readback)


def test_a_user_brk_stops_with_the_snapshot_m65emu_has(runs):
    got, want = runs["got"], runs["want"]
    assert got["map"] == CSE_MAP and got["b"] == CSE_BP
    assert got == want


def test_a_programs_bank_state_survives_a_break_and_a_resume(runs):
    assert runs["reason_break"] == T.DBG_BRK
    assert runs["reason_end"] == T.DBG_RTS
    assert runs["readback"] == [0xFF, BANKED["port"], BANKED["d030"], 0xC7]
