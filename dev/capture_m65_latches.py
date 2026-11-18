#!/usr/bin/env python3
"""capture_m65_latches.py — record the two interrupt latches M65Emu models.

Owner: doc/build_system.md

What M65Emu's parity devices rest on, as far as the monitor can show
it (the monitor can raise no interrupt and press no key): code in
block 0, interrupts off, exercises the VIC interrupt latch ($D019:
acknowledging, the raster bit with $D01A's raster mask on and off,
writing 0 bits) and the CIA2 interrupt control register ($DD0D: a
timer A underflow, its sources masked, read twice), storing each
value read at $1900; the code ends parked by a JMP to itself and runs
at full speed to it.  The values go into
tests/fixtures/golden/m65_latches.json; tests/unit/test_m65devices.py
holds VICInterruptLatch and CIA2InterruptControl to them.

    python dev/capture_m65_latches.py

Needs xmega65 and the user's configured MEGA65 SD image.
"""
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from xmega65 import recording                     # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "m65_latches.json"
WORK = ROOT / "build" / "m65_latches"
CODE, OUT = 0x1800, 0x1900

READS = (                                       # what each stored byte is
    "D01A as booted",
    "D019 after writing $0F",
    "D019 with the raster bit latched, raster mask on",
    "D019 with the raster bit latched, raster mask off",
    "D019 after writing $01 (mask off)",
    "D019 after writing $00 with the raster bit latched (mask off)",
    "DD0D at the first read after a timer A underflow (sources masked)",
    "DD0D at the read after that",
)


def lda(a):
    return [0xAD, a & 0xFF, a >> 8]


def sta(a):
    return [0x8D, a & 0xFF, a >> 8]


def imm(v):
    return [0xA9, v]


def code():
    """The probe; returns the bytes and the address it parks at."""
    out = []

    def store(k):
        out.extend(sta(OUT + k))

    def wait_raster():                          # LDA $D019 / AND #1 / BEQ
        out.extend(lda(0xD019) + [0x29, 0x01, 0xF0, 0xF9])

    out += [0x78]                                               # SEI
    out += lda(0xD01A); store(0)
    out += imm(0x0F) + sta(0xD019) + lda(0xD019); store(1)
    out += imm(0x01) + sta(0xD01A)
    wait_raster()
    out += lda(0xD019); store(2)
    out += imm(0x00) + sta(0xD01A) + lda(0xD019); store(3)
    out += imm(0x01) + sta(0xD019) + lda(0xD019); store(4)
    wait_raster()
    out += imm(0x00) + sta(0xD019) + lda(0xD019); store(5)
    out += lda(OUT) + sta(0xD01A)                               # mask back
    out += imm(0x7F) + sta(0xDD0D) + lda(0xDD0D)                # mask off, clear
    out += imm(0x10) + sta(0xDD04) + imm(0x00) + sta(0xDD05)
    out += imm(0x19) + sta(0xDD0E)                              # load, one-shot, go
    out += lda(0xDD0D) + [0xF0, 0xFB]                           # wait: BEQ
    store(6)
    out += lda(0xDD0D); store(7)
    end = CODE + len(out)
    return out + [0x4C, end & 0xFF, end >> 8], end


def main():
    probe, end = code()
    with recording(WORK) as xm:
        version = xm.version()
        xm.write(CODE, probe)
        xm.cmd(f"g {CODE:x}")
        xm.run_to(end)
        values = xm.read(OUT, len(READS))
    reads = {name: v for name, v in zip(READS, values)}
    GOLDEN.write_text(json.dumps(dict(
        source=dict(xmega65=version, recorded=datetime.date.today().isoformat()),
        code=bytes(probe).hex(" ").upper(), reads=reads), indent=1) + "\n")
    for name, v in reads.items():
        print(f"  ${v:02X}  {name}")
    print(f"wrote {GOLDEN}")


if __name__ == "__main__":
    main()
