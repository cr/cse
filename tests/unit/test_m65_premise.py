"""test_m65_premise.py — the run premise, as xmega65 recorded it per ROM.

Owner: doc/build_system.md

Contract source: [doc/memory_design.md § Memory Map — m65](../../doc/memory_design.md#memory-map--m65-mega65-mode)
and [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier U.  tests/fixtures/golden/m65_premise.json (dev/capture_m65_premise.py)
holds, per ROM, what a RUN-started PRG finds at its SYS entry and what
hyppo_getversion answers.  memory_design.md's run premise must hold on
every ROM recorded, the ROMs must agree on all of it but their own SYS
return path (the address in page 3, BASIC's frames), and M65Emu's
Hypervisor must give the recorded answer.
"""

import json
import pathlib

import pytest

from m65emu.devices import HYPPO_GETVERSION

GOLDEN = json.loads((pathlib.Path(__file__).resolve().parents[1] / "fixtures"
                     / "golden" / "m65_premise.json").read_text())
ENTRIES = GOLDEN["roms"]
IDS = [e["rom"] for e in ENTRIES]


def test_the_rom_floor_and_the_shipped_rom_are_recorded():
    assert {"V920413", "V920421"} <= set(IDS)


@pytest.mark.parametrize("e", ENTRIES, ids=IDS)
def test_registers_stack_and_map_are_the_premise(e):
    r = e["regs"]
    assert (r["a"], r["x"], r["y"], r["z"], r["b"]) == (0, 0, 0, 0, 0)
    assert r["p"] == 0x20                     # E = 1, I = 0, D = 0
    assert r["sp"] == 0x01EF
    assert (r["mapl"], r["maph"]) == (0xE000, 0x8300)   # the user map
    assert 0x0300 <= e["rts_target"] <= 0x03FF          # SYS's return in page 3
    # above the return address, the BASIC map SYS's return path restores
    assert e["stack_above_sp"].split()[2:6] == ["B3", "00", "E3", "00"]


@pytest.mark.parametrize("e", ENTRIES, ids=IDS)
def test_banking_screen_and_speed_are_the_premise(e):
    io = {int(k, 16): v for k, v in e["io"].items()}
    assert e["port"] == [0xFF, 0x85]
    assert io[0xD030] == 0x64
    assert io[0xD02F] == 0x53                 # the VIC-IV key's last byte
    assert io[0xD060] | io[0xD061] << 8 | io[0xD062] << 16 == 0x0800
    assert (io[0xD05E], io[0xD058] | io[0xD059] << 8, io[0xD07B] + 1) == (80, 80, 25)
    assert io[0xD031] & 0x40 and io[0xD054] & 0x40    # 40 MHz


@pytest.mark.parametrize("e", ENTRIES, ids=IDS)
def test_the_free_area_is_untouched(e):
    assert e["nonzero_1600_1EFF"] == 0


def test_the_roms_agree_on_all_of_it():
    """But for each ROM's own SYS return path: the address in page 3
    and BASIC's frames above it."""
    def premise(e):
        return {k: v for k, v in e.items()
                if k not in ("rom", "rts_target", "stack_above_sp")}
    assert all(premise(e) == premise(ENTRIES[0]) for e in ENTRIES)


@pytest.mark.parametrize("e", ENTRIES, ids=IDS)
def test_m65emu_answers_hyppo_getversion_as_recorded(e):
    assert tuple(e["hyppo_getversion"]) == HYPPO_GETVERSION
