"""test_m65memory.py — M65Memory, M65Emu's memory layout (layer 2).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier U: needs neither xmega65 nor the MEGA65 ROM (a synthetic ROM
image stands in).  Every banking state recorded in xmega65
(tests/fixtures/golden/m65_mem.json, dev/capture_m65_mem.py) is set
up on M65Memory through the CPU's view, as the recorder set it up, and
each probed address must read from and write to the recorded flat
address; the recording's three extra observations (a flat write into
ROM, an I/O register across modes, the CPU port under a mapped block
0) are replayed too.  Targeted tests pin the shared colour RAM, flat
access, the CPU port, the page-table triggers, and that the memory
follows the CPU's MAP registers however they change.
"""

import json
import pathlib

import pytest

from m65emu import M65Memory, MPU45GS02
from m65emu.memory import IO_KEYS

GOLDEN = json.loads((pathlib.Path(__file__).resolve().parents[1]
                     / "fixtures" / "golden" / "m65_mem.json").read_text())
ROM = bytes((a * 7 + (a >> 8) * 13) & 0xFF for a in range(0x20000))


def machine(**kwargs):
    """A CPU on a fresh M65Memory."""
    return MPU45GS02(M65Memory(**kwargs))


def set_state(cpu, st):
    """The recorder's set-up order, through the CPU's view."""
    mem = cpu.memory
    cpu.mapl = cpu.maph = cpu.map_lo_mb = cpu.map_hi_mb = 0
    mem[0x0000], mem[0x0001] = 0xFF, 0x35
    mem[0xD02F], mem[0xD02F] = IO_KEYS["vic4"]
    mem[0xD030] = st["d030"]
    mem[0xD02F], mem[0xD02F] = IO_KEYS[st["key"]]
    cpu.map_lo_mb, cpu.map_hi_mb = st["mb_lo"], st["mb_hi"]
    cpu.mapl, cpu.maph = st["mapl"], st["maph"]
    mem[0x0000], mem[0x0001] = st["ddr"], st["port"]


def everything(mem):
    return bytes(mem.chip), bytes(mem.colour), dict(mem.sparse), bytes(mem.io)


@pytest.mark.parametrize("st", GOLDEN["states"],
                         ids=[s["name"] for s in GOLDEN["states"]])
def test_recorded_state(st):
    cpu = machine(rom=ROM)
    mem = cpu.memory
    set_state(cpu, st["setup"])
    for probe in st["probes"]:
        addr = int(probe["addr"], 16)
        src = int(probe["read"], 16)
        marker = bytes((src * 31 + k * 17 + 5) & 0xFF for k in range(16))
        mem.load(src, marker)
        seen = bytes(mem[addr + k] for k in range(16))
        assert seen == bytes(b | probe.get("read_or", 0) for b in marker), \
            f"${addr:04X} should read ${src:07X}"
        fresh = bytes(b ^ 0x5A for b in marker)
        before = everything(mem) if probe["write"] is None else None
        for k, b in enumerate(fresh):
            mem[addr + k] = b
        if probe["write"] is None:
            assert everything(mem) == before, f"${addr:04X}: write not dropped"
        else:
            dst = int(probe["write"], 16)
            mask = probe.get("write_and", 0xFF)
            assert bytes(mem.read_flat(dst + k) for k in range(16)) == \
                bytes(b & mask for b in fresh), f"${addr:04X} should write ${dst:07X}"


def test_flat_write_into_rom_is_dropped_as_recorded():
    rec = GOLDEN["flat_rom_write"]
    mem = M65Memory(rom=ROM)
    a = int(rec["target"], 16)
    v = mem.read_flat(a)
    mem.write_flat(a, v ^ 0xFF)
    assert (mem.read_flat(a) == v) == rec["dropped"]


def test_rom_protection_off_lets_rom_be_written():
    mem = M65Memory(rom=ROM, rom_protect=False)
    mem.write_flat(0x3E123, 0x99)
    assert mem.read_flat(0x3E123) == 0x99


def test_io_register_reads_back_in_every_mode_as_recorded():
    rec = GOLDEN["io_register"]
    mem = machine().memory
    addr = int(rec["addr"], 16)
    mem[0x0001] = 0x35
    mem[0xD02F], mem[0xD02F] = IO_KEYS["vic4"]
    mem[addr] = rec["written"]
    for mode, value in rec["reads"].items():
        mem[0xD02F], mem[0xD02F] = IO_KEYS[mode]
        assert mem[addr] == value, mode


def test_cpu_port_under_a_mapped_block_0_as_recorded():
    rec = GOLDEN["port_under_map"]
    cpu = machine()
    mem = cpu.memory
    mem[0x0000], mem[0x0001] = rec["ddr"], rec["port"]
    mem.load(0, bytes(rec["ram"]))
    cpu.mapl = rec["mapl"]
    assert [mem[0], mem[1]] == rec["cpu_reads"]
    for a, v in rec["written"].items():
        mem[int(a, 16)] = v
    assert [mem.read_flat(0), mem.read_flat(1)] == rec["ram_after"]
    cpu.mapl = 0
    assert [mem[0], mem[1]] == rec["port_after_unmap"]


def test_cpu_port_lives_only_in_the_cpu_view():
    mem = M65Memory()
    mem[0x0000], mem[0x0001] = 0x2F, 0x37
    assert (mem[0x0000], mem[0x0001]) == (0x2F, 0x37)
    assert (mem.read_flat(0), mem.read_flat(1)) == (0, 0)
    mem.write_flat(1, 0x99)
    assert mem[0x0001] == 0x37


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
    cpu = machine()
    mem = cpu.memory
    cpu.map_lo_mb, cpu.mapl = 0x80, 0xE000
    mem.write_flat(0x2100, 0x44)
    mem.write_flat(0x8002100, 0x55)
    assert mem[0x2100] == 0x55
    assert mem.read_flat(0x2100) == 0x44


def test_memory_follows_the_map_registers_however_they_change():
    cpu = machine()
    mem = cpu.memory
    mem.write_flat(0x02100, 0x11)
    mem.write_flat(0x42100, 0x22)
    cpu.mapl = 0xE400                                # an assignment
    assert mem[0x2100] == 0x22
    cpu.reset()                                      # a reset
    assert (cpu.mapl, mem[0x2100]) == (0, 0x11)
    for k, b in enumerate([0xA9, 0x00, 0xA2, 0xE4, 0xA0, 0x00, 0xA3, 0x00,
                           0x5C, 0xEA, 0xAD, 0x00, 0x21]):   # MAP, EOM, LDA $2100
        mem[0x1800 + k] = b
    cpu.pc = 0x1800
    for _ in range(7):                               # the MAP instruction
        cpu.step()
    assert (cpu.mapl, cpu.a) == (0xE400, 0x22)
    MPU45GS02(mem)                                   # a new CPU: unmapped
    assert mem[0x2100] == 0x11


def test_page_table_is_rebuilt_only_by_its_triggers():
    cpu = machine()
    mem = cpu.memory
    mem[0x0001] = 0x35                               # I/O in
    mem[0xD02F], mem[0xD02F] = IO_KEYS["vic4"]
    n = mem.rebuilds
    for a in (0x0002, 0x1234, 0x8000, 0xD020, 0xD800, 0xFFFF):
        mem[a] = 0x12
        assert mem[a] is not None
    mem.write_flat(0x40000, 1)
    assert mem.rebuilds == n

    def after(action):
        nonlocal n
        action()
        assert mem.rebuilds == n + 1
        n += 1
    after(lambda: mem.__setitem__(0x0000, 0xFF))
    after(lambda: mem.__setitem__(0x0001, 0x35))
    after(lambda: mem.__setitem__(0xD030, 0x00))     # VIC-IV: banks
    after(lambda: mem.__setitem__(0xD02F, 0x00))     # → VIC-II
    after(lambda: setattr(cpu, "maph", 0))
    mem[0xD030] = 0x20               # VIC-II: $D030 is another register
    assert (mem.rebuilds, mem.d030) == (n, 0x00)
