#!/usr/bin/env python3
"""capture_m65_state.py — record M65Emu's post-boot snapshot from xmega65.

Owner: doc/build_system.md

Boots xmega65 to the BASIC 65 prompt, stops the CPU in trace mode and
reads, over uartmon, the state M65Emu starts from, into
build/m65_state/ (tests/m65emu/harness.py has the file list):

- chip RAM (the ROM image included), colour RAM, and the I/O page
  $D000-$D7FF in VIC-IV mode — not the CIAs, whose reads clear flags;
- the registers and MAP, the CPU port, $D030 and the I/O mode; the
  megabyte selectors cannot be read and are 0 after boot, as the
  post-boot state of m65_mem.json confirms;
- a reference run from that state — SEI, LDA #'A', JSR CHROUT — with
  its registers, step count and memory changes, which
  tests/integration/test_m65emu.py replays on M65Emu.

The snapshot holds the MEGA65 ROM, so it stays in build/ and is never
committed.  Run it by hand (about 20 s); pytest never starts xmega65.
Re-run it after an xmega65 or ROM update.

    python dev/capture_m65_state.py

Needs xmega65 and the user's configured MEGA65 SD image.
"""
import datetime
import hashlib
import json
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from m65emu.harness import STATE_DIR              # noqa: E402
from m65emu.memory import COLOUR, IO_KEYS, VIC4   # noqa: E402
from xmega65 import POST_BOOT_MAP, recording      # noqa: E402

WORK = ROOT / "build" / "m65_state_capture"
CODE = 0x1800
REFERENCE = [0x78, 0xA9, 0x41, 0x20, 0xD2, 0xFF]   # SEI; LDA #'A'; JSR CHROUT
IO_BYTES = 0x800                                  # $D000-$D7FF: no CIAs


def capture(xm):
    regs = xm.regs()
    assert (regs["mapl"], regs["maph"]) == POST_BOOT_MAP, regs
    ddr, port = xm.read_cpu(0x0000, 2)
    key, d030 = xm.read_cpu(0xD02F, 2)
    if key != IO_KEYS[VIC4][1]:
        raise RuntimeError(f"$D02F reads ${key:02X}: not BASIC 65's VIC-IV mode")
    chip = xm.read(0, 0x60000)
    files = {"chip.bin": chip,
             "colour.bin": xm.read(COLOUR, 0x8000),
             "io.bin": xm.read_cpu(0xD000, IO_BYTES)}
    state = dict(regs=regs, ddr=ddr, port=port, d030=d030, io_mode=VIC4,
                 xmega65=xm.version(),
                 captured=datetime.date.today().isoformat(),
                 rom_sha256=hashlib.sha256(chip[0x20000:0x40000]).hexdigest())
    return files, state, reference_run(xm, chip, files["colour.bin"])


def reference_run(xm, chip, colour):
    """Run REFERENCE at CODE from the captured state; record the
    registers after it, the steps it took and what it changed in
    chip RAM below $20000 and in colour RAM."""
    xm.write(CODE, REFERENCE)
    xm.cmd(f"g {CODE:x}")
    end, steps = CODE + len(REFERENCE), 0
    regs = xm.regs()
    while regs["pc"] != end:
        regs = xm.step()
        steps += 1
        if steps > 10_000:
            raise RuntimeError(f"reference run did not return: {regs}")
    after_chip = xm.read(0, 0x20000)
    after_colour = xm.read(COLOUR, 0x8000)
    code = range(CODE, end)
    return dict(code=" ".join(f"{b:02X}" for b in REFERENCE), at=CODE,
                steps=steps, after=regs,
                chip_changes={f"{a:05X}": after_chip[a] for a in range(0x20000)
                              if after_chip[a] != chip[a] and a not in code},
                colour_changes={f"{a:04X}": after_colour[a] for a in range(0x8000)
                                if after_colour[a] != colour[a]})


def main():
    with recording(WORK) as xm:
        files, state, reference = capture(xm)
    tmp = STATE_DIR.with_name(STATE_DIR.name + ".new")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    for name, data in files.items():
        (tmp / name).write_bytes(data)
    (tmp / "state.json").write_text(json.dumps(state, indent=1) + "\n")
    (tmp / "reference.json").write_text(json.dumps(reference, indent=1) + "\n")
    shutil.rmtree(STATE_DIR, ignore_errors=True)
    tmp.rename(STATE_DIR)                         # never a half snapshot
    print(f"wrote {STATE_DIR} (xmega65 {state['xmega65'].split()[2][:8]}, "
          f"reference run {reference['steps']} steps)")


if __name__ == "__main__":
    main()
