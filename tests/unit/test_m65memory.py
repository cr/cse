"""test_m65memory.py — M65Memory, M65Emu's memory layout (layer 2).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier U: needs neither xmega65 nor the MEGA65 ROM (a synthetic ROM
image stands in).  Every banking state recorded in xmega65
(tests/fixtures/golden/m65_mem.json, dev/capture_m65_mem.py) is set
up on M65Memory through the CPU's view, as the recorder set it up, and
each page must read from and write to the recorded flat address.
Targeted tests pin the shared colour RAM, ROM protection, flat access,
the CPU port and the page-table triggers; one runs MAP on MPU45GS02.
"""

import json
import pathlib

import pytest

from m65emu import M65Memory, MPU45GS02

GOLDEN = json.loads((pathlib.Path(__file__).resolve().parents[1]
                     / "fixtures" / "golden" / "m65_mem.json").read_text())
ROM = bytes((a * 7 + (a >> 8) * 13) & 0xFF for a in range(0x20000))
KEYS = {"vic4": (0x47, 0x53), "vic3": (0xA5, 0x96), "vic2": (0x00, 0x00)}


def set_map(mem, mapl, maph, mb_lo=0, mb_hi=0):
    cpu = MPU45GS02(mem)
    cpu.mapl, cpu.maph, cpu.map_lo_mb, cpu.map_hi_mb = mapl, maph, mb_lo, mb_hi
    mem.map_changed(cpu)


def set_state(mem, st):
    """The recorder's set-up order, through the CPU's view."""
    set_map(mem, 0, 0)
    mem[0x0000], mem[0x0001] = 0xFF, 0x35
    mem[0xD02F], mem[0xD02F] = KEYS["vic4"]
    mem[0xD030] = st["d030"]
    mem[0xD02F], mem[0xD02F] = KEYS[st["key"]]
    set_map(mem, st["mapl"], st["maph"], st["mb_lo"], st["mb_hi"])
    mem[0x0000], mem[0x0001] = st["ddr"], st["port"]


def snapshot(mem):
    return mem.dump()


@pytest.mark.parametrize("st", GOLDEN["states"],
                         ids=[s["name"] for s in GOLDEN["states"]])
def test_recorded_state(st):
    mem = M65Memory(rom=ROM)
    set_state(mem, st["setup"])
    for page in st["pages"]:
        addr = int(page["addr"], 16)
        src = int(page["read"], 16)
        marker = bytes((src * 31 + k * 17 + 5) & 0xFF for k in range(16))
        mem.load(src, marker)
        seen = bytes(mem[addr + k] for k in range(16))
        assert seen == bytes(b | page.get("read_or", 0) for b in marker), \
            f"${addr:04X} should read ${src:07X}"
        fresh = bytes((b ^ 0x5A) for b in marker)
        before = snapshot(mem)
        for k, b in enumerate(fresh):
            mem[addr + k] = b
        if page["write"] is None:
            assert snapshot(mem) == before, f"${addr:04X}: write not dropped"
        else:
            dst = int(page["write"], 16)
            mask = page.get("write_and", 0xFF)
            assert bytes(mem.read_flat(dst + k) for k in range(16)) == \
                bytes(b & mask for b in fresh), f"${addr:04X} should write ${dst:07X}"


def test_flat_write_into_rom_is_dropped():
    rec = GOLDEN["flat_rom_write"]
    assert rec["dropped"]
    mem = M65Memory(rom=ROM)
    a = int(rec["target"], 16)
    v = mem.read_flat(a)
    mem.write_flat(a, v ^ 0xFF)
    assert mem.read_flat(a) == v == ROM[a - 0x20000]


def test_rom_protection_off_lets_rom_be_written():
    mem = M65Memory(rom=ROM, rom_protect=False)
    mem.write_flat(0x3E123, 0x99)
    assert mem.read_flat(0x3E123) == 0x99


def test_colour_ram_shares_its_first_2k_with_chip_ram():
    mem = M65Memory()
    mem.write_flat(0x1F805, 0x11)
    assert mem.read_flat(0xFF80005) == 0x11
    mem.write_flat(0xFF807FF, 0x22)
    assert mem.read_flat(0x1FFFF) == 0x22
    mem.write_flat(0xFF80800, 0x33)                  # beyond the shared 2 KB
    assert mem.read_flat(0xFF80800) == 0x33
    assert mem.read_flat(0x1F800) == 0x00


def test_flat_access_reaches_attic_and_ignores_the_map():
    mem = M65Memory()
    set_map(mem, 0xE000, 0, mb_lo=0x80)
    mem.write_flat(0x2100, 0x44)
    mem.write_flat(0x8002100, 0x55)
    assert mem[0x2100] == 0x55
    assert mem.read_flat(0x2100) == 0x44


def test_cpu_port_lives_only_in_the_cpu_view():
    mem = M65Memory()
    mem[0x0000], mem[0x0001] = 0x2F, 0x37
    assert (mem[0x0000], mem[0x0001]) == (0x2F, 0x37)
    assert (mem.read_flat(0), mem.read_flat(1)) == (0, 0)
    mem.write_flat(1, 0x99)
    assert mem[0x0001] == 0x37


def test_page_table_is_rebuilt_only_by_its_triggers():
    mem = M65Memory()
    mem[0x0001] = 0x35                               # I/O in
    mem[0xD02F], mem[0xD02F] = KEYS["vic4"]
    n = mem.rebuilds
    for a in (0x0002, 0x1234, 0x8000, 0xD020, 0xD800, 0xFFFF):
        mem[a] = 0x12
        _ = mem[a]
    mem.write_flat(0x40000, 1)
    assert mem.rebuilds == n
    triggers = [lambda: mem.__setitem__(0x0000, 0xFF),
                lambda: mem.__setitem__(0x0001, 0x35),
                lambda: mem.__setitem__(0xD030, 0x00),     # VIC-IV: banks
                lambda: mem.__setitem__(0xD02F, 0x00),     # → VIC-II
                lambda: set_map(mem, 0, 0)]
    for k, trigger in enumerate(triggers, 1):
        trigger()
        assert mem.rebuilds == n + k
    mem[0xD030] = 0x20               # VIC-II: $D030 is another register
    assert mem.rebuilds == n + len(triggers) and mem.d030 == 0x00


def test_map_on_the_cpu_remaps_the_next_fetch():
    mem = M65Memory()
    code = [0xA9, 0x00, 0xA2, 0xE4, 0xA0, 0x00, 0xA3, 0x00,   # A=00 X=E4 Y=00 Z=00
            0x5C, 0xEA,                                       # MAP, EOM
            0xAD, 0x00, 0x21]                                 # LDA $2100
    for k, b in enumerate(code):
        mem[0x1800 + k] = b
    mem.write_flat(0x02100, 0x11)
    mem.write_flat(0x42100, 0x22)
    cpu = MPU45GS02(mem, pc=0x1800)
    for _ in range(7):
        cpu.step()
    assert cpu.a == 0x22 and cpu.mapl == 0xE400
