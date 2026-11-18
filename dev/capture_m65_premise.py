#!/usr/bin/env python3
"""capture_m65_premise.py — record the run premise per ROM from xmega65.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../doc/testing.md#m65emu--the-m65-integration-harness)
and [doc/memory_design.md § Memory Map — m65](../doc/memory_design.md#memory-map--m65-mega65-mode).

On each MEGA65 ROM given, xmega65 RUNs a probe PRG — a BASIC 65 line
`10 SYS 8205` and, at $200D, a JMP to itself — and, parked there, the
script reads what a RUN-started PRG finds: the registers, MAP and P,
the stack bytes above SP and the address their RTS returns to, the
CPU port, $D030, the VIC-IV registers of the screen and the speed,
and how many bytes of 0.1600-0.1EFF and of CSE's page 0.1F00-0.1FFF
are not zero.  Then it calls hyppo_getversion and records A X Y Z,
and hyppo_get_mapping under five maps (the run premise's, the CSE
map, one with an Attic megabyte, one whose destination page is in a
mapped block, and the premise's again with interrupts enabled): the
six bytes, where they landed (flat bank 0 or the CPU view), the
registers after the trap and whether it touched the stack.
One entry per ROM goes into tests/fixtures/golden/m65_premise.json
(no ROM content, so it is committed; tests/unit/test_m65_premise.py
holds memory_design.md's premise to it).  The script refuses to record
when the ROM xmega65 booted differs from the one given.

    python dev/capture_m65_premise.py --rom 920413.bin --rom rom/mega65.rom

Without --rom it records rom/mega65.rom (found by `make m65-rom`).
Needs xmega65, mtools and the user's configured MEGA65 SD image; about
10 s per ROM.  Run by hand; pytest never starts xmega65.
"""
import argparse
import datetime
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from find_m65_rom import (TARGET, check_booted, check_native,  # noqa: E402
                          install, rom_version)
from xmega65 import XMega65, write_recording                  # noqa: E402

WORK = ROOT / "build" / "m65_premise_capture"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "m65_premise.json"
ENTRY = 0x200D                    # SYS 8205
PARK = 0x1E00                     # where the Hypervisor call parks
# The I/O registers recorded: $D02F (the I/O key), $D030 (ROM banking),
# the screen (mode $D011/$D016/$D031, base $D060-$D062, width $D05E,
# line step $D058-$D059, rows - 1 $D07B) and the speed ($D031 bit 6,
# $D054 bit 6).
IO = (0xD011, 0xD016, 0xD02F, 0xD030, 0xD031, 0xD054, 0xD058, 0xD059,
      0xD05E, 0xD060, 0xD061, 0xD062, 0xD07B)


def probe_prg():
    """10 SYS 8205, then JMP $200D at $200D."""
    line = [0x0B, 0x20, 0x0A, 0x00, 0x9E] + list(b"8205") + [0, 0, 0]
    assert 0x2001 + len(line) == ENTRY
    return bytes([0x01, 0x20] + line + [0x4C, ENTRY & 0xFF, ENTRY >> 8])


def capture(xm):
    # Parked at the SYS entry.  BASIC 65's own map puts its ROM code at
    # $2000-$7FFF, so a hit at $200D under that map is BASIC, not the PRG.
    for _ in range(50):
        regs = xm.run_to(ENTRY)
        if regs["pc"] == ENTRY and regs["mapl"] != 0xE300:
            break
    else:
        raise RuntimeError(f"the PRG's SYS entry was not reached: {regs}")
    sp = regs["sp"]
    above = xm.read(sp + 1, 0x200 - (sp + 1))
    entry = dict(
        regs={k: regs[k] for k in ("a", "x", "y", "z", "b", "p", "sp",
                                   "mapl", "maph")},
        stack_above_sp=above.hex(" ").upper(),
        rts_target=(above[0] | above[1] << 8) + 1,
        port=list(xm.read_cpu(0x0000, 2)),
        io={f"{a:04X}": xm.read_cpu(a, 1)[0] for a in IO},
        nonzero_1600_1EFF=sum(1 for b in xm.read(0x1600, 0x900) if b),
        nonzero_1F00_1FFF=sum(1 for b in xm.read(0x1F00, 0x100) if b))
    # hyppo_getversion: lda #0 · sta $D640 · clv, parked by a JMP to itself
    code = [0xA9, 0x00, 0x8D, 0x40, 0xD6, 0xB8,
            0x4C, PARK & 0xFF, PARK >> 8]
    xm.write(PARK - len(code) + 3, code)
    xm.cmd(f"g {PARK - len(code) + 3:x}")
    r = xm.run_to(PARK)
    entry["hyppo_getversion"] = [r["a"], r["x"], r["y"], r["z"]]
    entry["hyppo_get_mapping"] = [get_mapping(xm, *g) for g in GET_MAPPING]
    return entry


def trap_at_park(xm, body):
    """Run `body` (bytes) followed by a JMP to PARK, which parks; the
    registers there."""
    code = list(body) + [0x4C, PARK & 0xFF, PARK >> 8]
    start = PARK - len(code) + 3
    xm.write(start, code)
    xm.cmd(f"g {start:x}")
    return xm.run_to(PARK)


# (name, MAPL, MAPH, lower MB, upper MB, destination page, CLI first)
GET_MAPPING = (
    ("user map", 0xE000, 0x8300, 0x00, 0x00, 0x1F, False),
    ("CSE map", 0xE300, 0xB300, 0x00, 0x00, 0x1F, False),
    ("lower megabyte $80", 0x2400, 0x8300, 0x80, 0x00, 0x1F, False),
    ("destination in a mapped block", 0xE400, 0x8300, 0x00, 0x00, 0x40, False),
    ("user map, interrupts on", 0xE000, 0x8300, 0x00, 0x00, 0x1F, True),
)


def get_mapping(xm, name, mapl, maph, mb_lo, mb_hi, page, cli):
    """hyppo_get_mapping (lda #$74 · sta $D640 · clv, Y = page) under a
    map set by code in block 0 with interrupts off."""
    xm.set_map(PARK - 0x100, mapl, maph, mb_lo, mb_hi)
    before = xm.regs()
    sp = 0x100 | before["sp"] & 0xFF
    below = bytes((0xC3 + 7 * k) & 0xFF for k in range(32))
    xm.write(sp - 31, below)
    dest = page << 8
    blocks = (mapl if dest < 0x8000 else maph) >> 12
    mapped = blocks >> (dest >> 13 & 3) & 1
    cpu_flat = (((mb_lo << 20) + ((((mapl & 0xFFF) << 8) + dest) & 0xFFFFF))
                if mapped else dest)
    for a in {dest, cpu_flat}:
        xm.write(a, bytes([0xEE] * 8))
    r = trap_at_park(xm, ([0x58] if cli else [])
                     + [0xA0, page, 0xA9, 0x74, 0x8D, 0x40, 0xD6, 0xB8])
    return dict(name=name, mapl=mapl, maph=maph, mb_lo=mb_lo, mb_hi=mb_hi,
                page=page, cli=cli,
                bank0=list(xm.read(dest, 8)),
                cpu_view=list(xm.read(cpu_flat, 8)),
                cpu_view_flat=f"{cpu_flat:07X}",
                regs_before={k: before[k] for k in ("a", "x", "y", "z", "b", "p", "sp")},
                regs_after={k: r[k] for k in ("a", "x", "y", "z", "b", "p", "sp",
                                              "mapl", "maph")},
                stack_below_sp_kept=xm.read(sp - 31, 32) == below)


def record(rom_path):
    data = pathlib.Path(rom_path).read_bytes()
    check_native(data)
    WORK.mkdir(parents=True, exist_ok=True)
    prg = WORK / "probe.prg"
    prg.write_bytes(probe_prg())
    run = WORK / "run"
    try:
        with XMega65(run, rom=rom_path, prg=prg) as xm:
            entry = capture(xm)
            check_booted(xm.booted_rom(), target=rom_path)
            version = xm.version()
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print(f"{rom_version(data)}: SP ${entry['regs']['sp']:04X}, RTS to "
          f"${entry['rts_target']:04X}, hyppo {entry['hyppo_getversion']}")
    return dict(rom=rom_version(data), **entry), version


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rom", action="append", type=pathlib.Path,
                    help="a MEGA65 ROM image (repeatable; default "
                         "rom/mega65.rom, found by `make m65-rom`)")
    roms = ap.parse_args(argv).rom
    if not roms:
        install()
        roms = [TARGET]
    entries, versions = [], set()
    for rom in roms:
        entry, version = record(rom)
        entries.append(entry)
        versions.add(version)
    header = dict(xmega65=" / ".join(sorted(versions)),
                  captured=datetime.date.today().isoformat())
    write_recording(GOLDEN, header, "roms",
                    sorted(entries, key=lambda e: e["rom"]))
    print(f"wrote {GOLDEN.relative_to(ROOT)} ({len(entries)} ROMs)")


if __name__ == "__main__":
    main()
