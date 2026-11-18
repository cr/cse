#!/usr/bin/env python3
"""capture_m65_state.py — record M65Emu's post-boot snapshot from xmega65.

Owner: doc/build_system.md

Boots xmega65, on each MEGA65 ROM given, to the BASIC 65 prompt, stops
the CPU in trace mode and reads, over uartmon, the state M65Emu starts
from, into build/m65_state/<ROM version>/ (tests/m65emu/harness.py has
the file list):

- chip RAM (the ROM image included), colour RAM, and the I/O page
  $D000-$D7FF in VIC-IV mode — not the CIAs, whose reads clear flags;
- the registers and MAP, the CPU port, $D030 and the I/O mode; the
  megabyte selectors cannot be read and are 0 after boot, as the
  post-boot state of m65_mem.json confirms;
- reference runs, one after the other from that state, each with its
  code as planted, the registers it ends with and its memory changes,
  which
  tests/integration/test_m65emu.py replays on M65Emu in the same
  order: "chrout" (SEI, LDA #'A', JSR CHROUT; single-stepped, so its
  step count is recorded too) and "scroll" (30 RETURNs and an 'A'
  through CHROUT: the screen scrolls by DMA; about 140k steps, so it
  runs at full speed to a breakpoint, interrupts off, parked there by
  a JMP to itself).

Each ROM reaches xmega65 on the session's SD clone (tests/xmega65.py,
rom=); the script refuses to record when the booted ROM differs from
the one given.  Without --rom it records rom/mega65.rom, which it
first copies from xmega65's data directory (dev/find_m65_rom.py,
`make m65-rom`).  A snapshot holds the MEGA65 ROM, so it stays in
build/ and is never committed.  Run it by hand (about 25 s per ROM);
pytest never starts xmega65.  Re-run it after an xmega65 or ROM
update.

    python dev/capture_m65_state.py                       # rom/mega65.rom
    python dev/capture_m65_state.py --rom 920413.bin --rom rom/mega65.rom

Needs xmega65 and the user's configured MEGA65 SD image.
"""
import argparse
import datetime
import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from find_m65_rom import (TARGET, check_booted, check_native,  # noqa: E402
                          install, rom_version)
from m65emu.harness import FORMAT, STATE_DIR, snapshot_name  # noqa: E402
from m65emu.memory import COLOUR, IO_KEYS, VIC4   # noqa: E402
from xmega65 import POST_BOOT_MAP, recording      # noqa: E402

WORK = ROOT / "build" / "m65_state_capture"
CODE = 0x1800
IO_BYTES = 0x800                                  # $D000-$D7FF: no CIAs
CHROUT = [0x20, 0xD2, 0xFF]
RUNS = (                                          # (name, code, single-step?)
    ("chrout", [0x78, 0xA9, 0x41] + CHROUT, True),
    ("scroll", [0x78] + ([0xA9, 0x0D] + CHROUT) * 30 + [0xA9, 0x41] + CHROUT,
     False),
)


def capture(xm, rom_path):
    regs = xm.regs()
    assert (regs["mapl"], regs["maph"]) == POST_BOOT_MAP, regs
    ddr, port = xm.read_cpu(0x0000, 2)
    key, d030 = xm.read_cpu(0xD02F, 2)
    if key != IO_KEYS[VIC4][1]:
        raise RuntimeError(f"$D02F reads ${key:02X}: not BASIC 65's VIC-IV mode")
    chip = xm.read(0, 0x60000)
    check_booted(chip[0x20000:0x40000], target=rom_path)
    files = {"chip.bin": chip,
             "colour.bin": xm.read(COLOUR, 0x8000),
             "io.bin": xm.read_cpu(0xD000, IO_BYTES)}
    state = dict(format=FORMAT, regs=regs, ddr=ddr, port=port, d030=d030,
                 io_mode=VIC4,
                 xmega65=xm.version(),
                 rom=rom_version(chip[0x20000:0x40000]),
                 captured=datetime.date.today().isoformat(),
                 rom_sha256=hashlib.sha256(chip[0x20000:0x40000]).hexdigest())
    runs, before = [], (chip[:0x20000], files["colour.bin"])
    for name, code, single_step in RUNS:
        run, before = reference_run(xm, name, code, single_step, *before)
        runs.append(run)
    return files, state, dict(runs=runs)


def reference_run(xm, name, code, single_step, chip, colour):
    """Run `code` at CODE, parked at its end by a JMP to itself;
    record the code as planted, the registers after it, its steps
    (single-stepped runs only) and what it changed in chip RAM below
    $20000 and in colour RAM, outside the planted code."""
    end = CODE + len(code)
    planted = code + [0x4C, end & 0xFF, end >> 8]
    xm.write(CODE, planted)
    xm.cmd(f"g {CODE:x}")
    steps = None
    if single_step:
        steps, regs = 0, xm.regs()
        while regs["pc"] != end:
            regs = xm.step()
            steps += 1
            if steps > 10_000:
                raise RuntimeError(f"{name}: did not return: {regs}")
    else:
        regs = xm.run_to(end)
    after_chip, after_colour = xm.read(0, 0x20000), xm.read(COLOUR, 0x8000)
    own = range(CODE, CODE + len(planted))
    run = dict(name=name, code=bytes(planted).hex(" ").upper(), at=CODE,
               end=end, steps=steps, after=regs,
               chip_changes={f"{a:05X}": after_chip[a] for a in range(0x20000)
                             if after_chip[a] != chip[a] and a not in own},
               colour_changes={f"{a:04X}": after_colour[a] for a in range(0x8000)
                               if after_colour[a] != colour[a]})
    return run, (after_chip, after_colour)


def record(rom_path):
    """Boot `rom_path`, capture, and write build/m65_state/<version>/."""
    data = pathlib.Path(rom_path).read_bytes()
    check_native(data)
    out = STATE_DIR / snapshot_name(data)
    with recording(WORK, rom=rom_path) as xm:
        files, state, reference = capture(xm, rom_path)
    tmp = out.with_name(out.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, blob in files.items():
        (tmp / name).write_bytes(blob)
    (tmp / "state.json").write_text(json.dumps(state, indent=1) + "\n")
    (tmp / "reference.json").write_text(json.dumps(reference, indent=1) + "\n")
    shutil.rmtree(out, ignore_errors=True)
    tmp.rename(out)                               # never a half snapshot
    print(f"wrote {out} ({state['rom']}, xmega65 "
          f"{state['xmega65'].split()[2][:8]}, reference runs: "
          f"{', '.join(r['name'] for r in reference['runs'])})")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rom", action="append", type=pathlib.Path,
                    help="a MEGA65 ROM image (repeatable; default "
                         "rom/mega65.rom, found by `make m65-rom`)")
    roms = ap.parse_args(argv).rom
    if not roms:
        install()
        roms = [TARGET]
    for name in ("chip.bin", "colour.bin", "io.bin", "state.json",
                 "reference.json"):                # a format-2 flat snapshot
        (STATE_DIR / name).unlink(missing_ok=True)
    for rom in roms:
        record(rom)


if __name__ == "__main__":
    main()
