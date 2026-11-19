"""test_m65_editor.py — M65Emu answers the screen editor as xmega65 does (P2 T1).

Owner: doc/build_system.md

Contract source: [doc/testing.md § The m65 PRG on M65Emu](../../doc/testing.md#the-m65-prg-on-m65emu)
(*M65Emu against the editor recording*); A1 and T1 of TODO § M65 slice 2, P2.

dev/capture_m65_editor.py recorded the MEGA65 screen editor's API in
xmega65 on each ROM (tests/fixtures/golden/m65_editor.json).  Here the
recorder's own probe functions run unchanged on M65Emu — with each
snapshot's ROM, entered at that ROM's run premise — through `Machine`,
which offers the calls the probes make of tests/xmega65.py's XMega65
(read, write, the CPU view, `g`, run_to, step).  Every probe must
answer as the recording does, so the REPL suites of P2 rest on a
harness that behaves as the MEGA65 KERNAL does on xmega65.
"""

import contextlib
import json
import pathlib
import re
import sys

import pytest

from m65emu import M65Emu
from m65emu.harness import run_premise

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dev"))
import capture_m65_editor as E                                  # noqa: E402

GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "golden"
                     / "m65_editor.json").read_text())
REGS = ("pc", "a", "x", "y", "z", "b", "sp", "maph", "mapl", "p")


class Machine:
    """M65Emu with XMega65's probe interface: `read` / `write` are the
    flat space (as uartmon's), `read_cpu` the CPU view, `cmd("g a")`
    sets PC, `run_to` runs to an address, `step` one instruction."""

    def __init__(self, snapshot):
        self.emu = M65Emu(snapshot)
        self.emu.enter_premise(run_premise(snapshot["state"]["rom"]))
        self.emu.memory.load(E.PARK, bytes([0x4C, E.PARK & 0xFF, E.PARK >> 8]))
        self.emu.pc = E.PARK

    def read(self, addr, length):
        mem = self.emu.memory
        return bytes(mem.read_flat(addr + k) for k in range(length))

    def read_cpu(self, addr, length):
        return bytes(self.emu.memory[addr + k] for k in range(length))

    def write(self, addr, data):
        self.emu.memory.load(addr, bytes(data))

    def cmd(self, line):
        m = re.fullmatch(r"g ([0-9a-f]+)", line)
        assert m, f"Machine knows only `g`, not {line!r}"
        self.emu.pc = int(m.group(1), 16)
        return ""

    def regs(self):
        cpu = self.emu.cpu
        return {"pc": cpu.pc, "a": cpu.a, "x": cpu.x, "y": cpu.y, "z": cpu.z,
                "b": cpu.b, "sp": cpu.sp, "maph": cpu.maph, "mapl": cpu.mapl,
                "p": cpu.p}

    def step(self):
        self.emu.cpu.step()
        return self.regs()

    def run_to(self, addr, timeout=None, at_hit=False):
        self.emu.run_until(addr, max_cycles=5_000_000)
        return self.regs()


def recorded(rom):
    for entry in GOLDEN["roms"]:
        if entry["rom"] == rom:
            return entry
    pytest.skip(f"no editor recording for {rom}: python dev/capture_m65_editor.py --rom PATH")


@pytest.fixture
def machine(m65_snapshot):
    return Machine(m65_snapshot), recorded(m65_snapshot["state"]["rom"])


@pytest.mark.parametrize("probe", ["jump_table", "clobbers", "scrorg",
                                   "vic_modes", "logical_lines",
                                   "keyboard_and_flags"])
def test_probe_answers_as_xmega65(machine, probe):
    m, rec = machine
    assert getattr(E, probe)(m) == rec[probe]


def test_an_interrupted_bsout_recovers_as_recorded(machine):
    """A sample of the recorded interruption points (the full sweep is
    the recorder's)."""
    m, rec = machine
    sample = [e for e in rec["interrupted_bsout"] if e["k"] % 4 == 0][::6]
    ks = sorted({e["k"] for e in sample})
    got = E.interrupted_bsout(m, lambda _: ks)
    want = [e for e in rec["interrupted_bsout"] if e["k"] in ks]
    assert got == want


def test_editor_modes_as_recorded(m65_snapshot):
    """Quote and insert mode, each case on a fresh machine."""
    rec = recorded(m65_snapshot["state"]["rom"])
    got = E.editor_modes(lambda: contextlib.nullcontext(Machine(m65_snapshot)))
    assert got == rec["editor_modes"]


# ── T2: the MEGA65's keys (tests/fixtures/m65_keys.json) ──────────

KEYS = json.loads((ROOT / "tests" / "fixtures" / "m65_keys.json").read_text())
RAW = ["TAB", "HELP", "ESC", "F9", "F10", "F11", "F12", "F13", "F14",
       "F1", "F3", "F5", "F7"]


def getin_after(m, code, raw):
    """SYSFLAGS bit 5 (function-key macros off) set or clear, one key
    in the typing queue, then GETIN: what it answers."""
    flags = [0x38] + E.jsr(0xFF47) + ([0x09, 0x20] if raw else [0x29, 0xDF]) \
        + [0x18] + E.jsr(0xFF47)
    E.call(m, flags)
    m.emu.inject_key(code)
    return E.call(m, E.jsr(0xFFE4))["a"]


@pytest.mark.parametrize("key", RAW)
def test_getin_passes_a_key_through_with_macros_off(m65_snapshot, key):
    """With SYSFLAGS bit 5 set, as CSE reads keys (D-P2-3), GETIN
    answers the hardware's PETSCII for every key CSE may see."""
    code = KEYS["petscii"][key]
    assert getin_after(Machine(m65_snapshot), code, raw=True) == code


def test_function_keys_are_macros_with_macros_on(m65_snapshot):
    """At the run premise ($00) the KERNAL expands F1 into its BASIC
    macro: GETIN does not answer the key's own code — why CSE turns the
    macros off while it reads keys."""
    code = KEYS["petscii"]["F1"]
    assert getin_after(Machine(m65_snapshot), code, raw=False) != code
