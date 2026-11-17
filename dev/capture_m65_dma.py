#!/usr/bin/env python3
"""capture_m65_dma.py — record DMA jobs as xmega65 runs them.

Owner: doc/build_system.md

Plants a job list at $1C00 and fills the memory regions with a known
pattern, then runs code in block 0 that sets the DMA registers and
starts the list ($D700, or $D705 for an enhanced list).  A job runs to
its end within the step of that store (checked by the 2026-11-17
probe), so the memory read afterwards is the job's whole effect.  The
differences per region go into tests/fixtures/golden/m65_dma.json;
tests/unit/test_m65dma.py replays every case on M65Emu's DMA
controller.

The ROM region is never written by the recorder (it is protected);
its differences show whether a DMA write into ROM lands, and the
replay starts it from zeros.

    python dev/capture_m65_dma.py                  # all cases
    python dev/capture_m65_dma.py --only enhanced  # cases named so, printed

Needs xmega65 and the user's configured MEGA65 SD image.
"""
import argparse
import datetime
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from m65emu.golden import pattern                 # noqa: E402
from xmega65 import recording, retrying, write_recording   # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "m65_dma.json"
WORK = ROOT / "build" / "m65_dma"
CODE = 0x1800
LIST = 0x1C00

REGIONS = (                       # written with the pattern before each case
    (0x01A00, 0x200),             # sources and targets in bank 0
    (0x40000, 0x100),             # a chip RAM bank outside the CPU view
    (0x8000000, 0x100),           # attic RAM (megabyte $80)
    (0xFF80000, 0x100),           # colour RAM
)
ROM = (0x3E000, 0x40)             # protected: read, never written


# ── job lists ─────────────────────────────────────────────────────

def addr24(a, *, hold=False, mod=False, dec=False, io=False):
    """A job's 24-bit address field: F018A keeps hold/mod/dec/io in
    bits 20-23; for F018B only bit 23 (I/O) is used there."""
    v = a | hold << 20 | mod << 21 | dec << 22 | io << 23
    return [v & 0xFF, v >> 8 & 0xFF, v >> 16 & 0xFF]


def job_a(cmd, length, src, dst, *, chain=False):
    """An F018A job (11 bytes): cmd, length, source, target, modulo."""
    return [cmd | chain << 2, length & 0xFF, length >> 8] + src + dst + [0, 0]


def job_b(cmd, length, src, dst, sub=0, *, chain=False):
    """An F018B job (12 bytes): the sub-command byte after the target.
    F018B steps down by command bits 4/5 (source/target) and holds by
    sub-command bits 1/3."""
    return [cmd | chain << 2, length & 0xFF, length >> 8] + src + dst + [sub, 0, 0]


COPY, MIX, SWAP, FILL = 0, 1, 2, 3


def fill_src(byte):
    return [byte, 0, 0]           # FILL: the source's low byte is the value


def case(name, job, *, rev=0, enhanced=False, mb=0):
    return dict(name=name, list=job, rev=rev, enhanced=enhanced, mb=mb)


def cases():
    a, b = 0x1A00, 0x1B00
    out = [
        case("A fill 16", job_a(FILL, 16, fill_src(0x5A), addr24(a))),
        case("A copy 32", job_a(COPY, 32, addr24(a + 0x80), addr24(b))),
        case("A copy overlapping forward",
             job_a(COPY, 32, addr24(a), addr24(a + 8))),
        case("A copy decrementing",
             job_a(COPY, 16, addr24(a + 0x8F, dec=True), addr24(b + 0x1F, dec=True))),
        case("A copy source held",
             job_a(COPY, 16, addr24(a + 0x40, hold=True), addr24(b))),
        case("A copy target held",
             job_a(COPY, 16, addr24(a + 0x40), addr24(b, hold=True))),
        case("A swap 16", job_a(SWAP, 16, addr24(a), addr24(b))),
        case("A mix, minterms AB|~AB", job_a(MIX | 0xC0, 16, addr24(a), addr24(b))),
        case("A chained fill then copy",
             job_a(FILL, 8, fill_src(0x11), addr24(a), chain=True)
             + job_a(COPY, 8, addr24(a), addr24(b))),
        case("A copy to $40000", job_a(COPY, 32, addr24(a), addr24(0x40010))),
        case("A copy into ROM", job_a(COPY, 16, addr24(a), addr24(0x3E010))),
        case("A fill colour RAM through I/O",
             job_a(FILL, 16, fill_src(0x07), addr24(0xD810, io=True))),
        case("A copy from I/O colour window",
             job_a(COPY, 8, addr24(0xD800, io=True), addr24(b))),
        case("B fill 16", job_b(FILL, 16, fill_src(0xA5), addr24(a)), rev=1),
        case("B copy 32", job_b(COPY, 32, addr24(a + 0x80), addr24(b)), rev=1),
        case("B copy decrementing (command bits 4, 5)",
             job_b(COPY | 0x30, 16, addr24(a + 0x8F), addr24(b + 0x1F)), rev=1),
        case("B copy source held (sub-command)",
             job_b(COPY, 16, addr24(a + 0x40), addr24(b), sub=0x02), rev=1),
        case("B copy target held (sub-command)",
             job_b(COPY, 16, addr24(a + 0x40), addr24(b), sub=0x08), rev=1),
    ]
    enh = [
        ("enhanced F018A", [0x0A, 0x00] + job_a(FILL, 16, fill_src(0x66), addr24(a))),
        ("enhanced F018B", [0x0B, 0x00] + job_b(FILL, 16, fill_src(0x77), addr24(a))),
        ("enhanced target megabyte $80",
         [0x0B, 0x81, 0x80, 0x00] + job_b(COPY, 32, addr24(a), addr24(0x10))),
        ("enhanced source megabyte $80",
         [0x0B, 0x80, 0x80, 0x00] + job_b(COPY, 32, addr24(0x20), addr24(b))),
        ("enhanced source step 2",
         [0x0B, 0x83, 0x02, 0x00] + job_b(COPY, 16, addr24(a), addr24(b))),
        ("enhanced target step 2",
         [0x0B, 0x85, 0x02, 0x00] + job_b(COPY, 16, addr24(a), addr24(b))),
        ("enhanced source step 0.5",
         [0x0B, 0x83, 0x00, 0x82, 0x80, 0x00] + job_b(COPY, 16, addr24(a), addr24(b))),
        ("enhanced transparency",
         [0x0B, 0x07, 0x86, pattern(a + 3), 0x00]
         + job_b(COPY, 16, addr24(a), addr24(b))),
        ("enhanced transparency off again",
         [0x0B, 0x07, 0x86, pattern(a + 3), 0x06, 0x00]
         + job_b(COPY, 16, addr24(a), addr24(b))),
        ("enhanced chained, each job its own options",
         [0x0B, 0x85, 0x02, 0x00] + job_b(COPY, 8, addr24(a), addr24(b), chain=True)
         + [0x00] + job_b(COPY, 8, addr24(a), addr24(b + 0x40))),
    ]
    out += [case(name, job, enhanced=True) for name, job in enh]
    return out


# ── recording ─────────────────────────────────────────────────────

def snapshot(xm):
    mem = {}
    for start, n in REGIONS + (ROM,):
        mem.update(zip(range(start, start + n), xm.read(start, n)))
    return mem


def trigger(c):
    """The code that sets the DMA registers and starts the list."""
    start = 0x05 if c["enhanced"] else 0x00
    return [[0x78],                                       # SEI
            [0xA9, c["rev"]], [0x8D, 0x03, 0xD7],         # revision
            [0xA9, c["mb"]], [0x8D, 0x04, 0xD7],          # list megabyte
            [0xA9, LIST >> 16 & 0x7F], [0x8D, 0x02, 0xD7],
            [0xA9, LIST >> 8 & 0xFF], [0x8D, 0x01, 0xD7],
            [0xA9, LIST & 0xFF], [0x8D, start, 0xD7]]     # go


def record(xm, c):
    for start, n in REGIONS:
        xm.write(start, bytes(pattern(a) for a in range(start, start + n)))
    xm.write(LIST, bytes(c["list"]))
    before = snapshot(xm)
    retrying(lambda: xm.run(CODE, trigger(c)))
    after = snapshot(xm)
    return dict(name=c["name"], list=bytes(c["list"]).hex(" ").upper(),
                rev=c["rev"], enhanced=c["enhanced"], mb=c["mb"],
                changes={f"{a:07X}": v for a, v in sorted(after.items())
                         if v != before[a]})


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="record only cases whose name starts so; print, do not write")
    ap.add_argument("--out", type=pathlib.Path, default=GOLDEN)
    args = ap.parse_args()
    todo = [c for c in cases() if not args.only or c["name"].startswith(args.only)]
    recorded = []
    with recording(WORK) as xm:
        version = xm.version()
        xm.write(0x7770001, b"\x35")                       # I/O in, MAP as booted
        for c in todo:
            recorded.append(record(xm, c))
            if args.only:
                print(json.dumps(recorded[-1]))
    if args.only:
        return
    source = dict(xmega65=version, recorded=datetime.date.today().isoformat())
    write_recording(args.out, dict(source=source, regions=REGIONS, rom=ROM,
                                   list_at=LIST),
                    "cases", recorded)
    print(f"wrote {args.out} ({len(recorded)} cases)")


if __name__ == "__main__":
    main()
