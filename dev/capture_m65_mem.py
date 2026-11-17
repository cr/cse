#!/usr/bin/env python3
"""capture_m65_mem.py — record the MEGA65's CPU-view translation in xmega65.

Owner: doc/build_system.md

Sets up banking states in xmega65 and records, per state and 4 KB
page, the flat address a CPU read comes from and where a CPU write
lands (or that it is dropped), into tests/fixtures/golden/m65_mem.json.
tests/unit/test_m65memory.py replays every state on M65Memory.

A state is set up in this order, so each step can reach what it
writes: MAP off (code run in block 0, which no state maps), the CPU
port to I/O, the `$D02F` key for VIC-IV, `$D030`, the `$D02F` key for
the state's I/O mode, MAP (megabytes, then offsets), the state's CPU
port.  `$00`, `$01`, `$D02F` and `$D030` are written through uartmon's
CPU-view addresses (`777xxxx`).

Per page one probe address (`$x100`; `$D900` in the I/O page, the
colour window): unique 16-byte signatures are planted at every flat
address the read could come from — the RAM under the address, the
MAP targets, colour RAM — and a ROM candidate is matched by its own
content (never recorded).  A read that matches no candidate stops the
recording: the model behind the candidate list is wrong.  A write
(16 fresh bytes through the CPU view) is found the same way; no
candidate changed means it was dropped.  I/O registers other than the
colour window are never written.

    python dev/capture_m65_mem.py              # all states
    python dev/capture_m65_mem.py --only MAP   # states named MAP*, printed

No state maps a megabyte xmega65 does not decode (MB $08 crashes it),
and the upper attic state uses MB $81: in xmega65 0870689e flat
$8008100 reads the same bytes as $8100, which would make MB $80
ambiguous.

Needs xmega65 and the user's configured MEGA65 SD image.
"""
import argparse
import datetime
import json
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))

from xmega65 import Interrupted, XMega65          # noqa: E402

GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "m65_mem.json"
WORK = ROOT / "build" / "m65_mem"
CODE = 0x1800
COLOUR = 0xFF80000
KEYS = {"vic4": (0x47, 0x53), "vic3": (0xA5, 0x96), "vic2": (0x00, 0x00)}


# ── states ────────────────────────────────────────────────────────

def state(name, *, ddr=0xFF, port=0x35, key="vic4", d030=0x00,
          mapl=0x0000, maph=0x0000, mb_lo=0, mb_hi=0):
    return dict(name=name, ddr=ddr, port=port, key=key, d030=d030,
                mapl=mapl, maph=maph, mb_lo=mb_lo, mb_hi=mb_hi)


def states():
    out = [state("post-boot", port=0x85, d030=0x64,
                 mapl=0xE300, maph=0xB300)]
    out += [state(f"port {p} MAP off", port=0x30 | p) for p in range(8)]
    out += [state("ddr 00 (all input) port 30", ddr=0x00, port=0x30)]
    out += [state(f"D030 {b:02X}", d030=b) for b in (0x08, 0x10, 0x20, 0x80, 0x01)]
    out += [state("D030 A8 port 30 (all RAM)", d030=0xA8, port=0x30)]
    out += [state("VIC-III D030 20", key="vic3", d030=0x20),
            state("VIC-II D030 20 latched", key="vic2", d030=0x20),
            state("VIC-II colour window", key="vic2", port=0x35)]
    out += [state("MAP lower blocks 1-3 to $40000", mapl=0xE400),
            state("MAP upper blocks 4-7 to $40000", maph=0xF400, port=0x30),
            state("MAP upper offset wraps in the megabyte", maph=0xFFF0, port=0x30),
            state("MAP lower megabyte $80 (attic)", mapl=0xE000, mb_lo=0x80),
            state("MAP upper megabyte $81 (attic)", maph=0xF000, mb_hi=0x81,
                  port=0x30),
            state("MAP over banking", maph=0xF400, port=0x37, d030=0xA8),
            state("MAP block 6 hides I/O", maph=0x4400, port=0x35),
            state("MAP onto ROM", mapl=0xE300, maph=0xB300, port=0x30)]
    return out


# ── candidates ────────────────────────────────────────────────────

def probe_addr(page):
    return 0xD900 if page == 0xD else page << 12 | 0x100


def map_target(st, addr):
    """Where MAP would put `addr`, or None (the model under test)."""
    lower = addr < 0x8000
    mask = (st["mapl"] if lower else st["maph"]) >> 12
    if not mask >> ((addr >> 13) & 3) & 1:
        return None
    off = ((st["mapl"] if lower else st["maph"]) & 0xFFF) << 8
    mb = (st["mb_lo"] if lower else st["mb_hi"]) << 20
    return mb + ((off + addr) & 0xFFFFF)


def candidates(st, addr):
    """Flat addresses the CPU's `addr` could read from or write to."""
    cands = [addr, 0x20000 + addr]
    t = map_target(st, addr)
    if t is not None:
        cands.append(t)
    if 0xD800 <= addr < 0xDC00:
        cands.append(COLOUR + addr - 0xD800)
    return list(dict.fromkeys(cands))


def protected(a):
    return 0x20000 <= a < 0x40000


def signature(a, salt):
    return bytes((a * 0x9E3779B1 >> 13 ^ a >> 3 ^ salt * 0x5B ^ k * 0x2F) & 0xFF
                 for k in range(16))


# ── recording ─────────────────────────────────────────────────────

def map_code(a, x, y, z):
    return [[0xA9, a], [0xA2, x], [0xA0, y], [0xA3, z], [0x5C], [0xEA],
            [0xA9, 0x00]]


def set_map(xm, mapl, maph, mb_lo=0, mb_hi=0):
    seq = ([[0x78]]                                    # SEI
           + map_code(mb_lo, 0x0F, mb_hi, 0x0F)
           + map_code(mapl & 0xFF, mapl >> 8, maph & 0xFF, maph >> 8))
    for _ in range(3):
        try:
            return xm.run(CODE, seq)
        except Interrupted:
            continue
    raise RuntimeError("MAP sequence kept being interrupted")


def cpu_write(xm, addr, *values):
    for v in values:
        xm.write(0x7770000 | addr, bytes([v]))


def set_state(xm, st):
    set_map(xm, 0, 0)
    cpu_write(xm, 0x0000, 0xFF)
    cpu_write(xm, 0x0001, 0x35)
    cpu_write(xm, 0xD02F, *KEYS["vic4"])
    cpu_write(xm, 0xD030, st["d030"])
    cpu_write(xm, 0xD02F, *KEYS[st["key"]])
    r = set_map(xm, st["mapl"], st["maph"], st["mb_lo"], st["mb_hi"])
    assert (r["mapl"], r["maph"]) == (st["mapl"], st["maph"]), (st, r)
    cpu_write(xm, 0x0000, st["ddr"])
    cpu_write(xm, 0x0001, st["port"])


def find(xm, cands, data, mask=0):
    """The one candidate whose 16 bytes (| mask) equal `data`, or None.
    Two matches mean two candidates show the same memory (an alias),
    and the record would be a guess: stop."""
    hits = [c for c in cands
            if bytes(b | mask for b in xm.read(c, 16)) == data]
    if len(hits) > 1:
        raise RuntimeError(f"ambiguous: {[hex(c) for c in hits]} all hold {data.hex()}")
    return hits[0] if hits else None


def probe_page(xm, st, page):
    addr = probe_addr(page)
    cands = candidates(st, addr)
    for salt, c in enumerate(cands):
        if not protected(c):
            xm.write(c, signature(c, salt))
    seen = xm.read_cpu(addr, 16)
    entry = {"page": page, "addr": f"{addr:04X}"}
    src = find(xm, cands, seen)
    if src is None and page == 0xD:                    # VIC-II colour nibble
        src = find(xm, cands, seen, mask=0xF0)
        if src is not None:
            entry["read_or"] = 0xF0
    if src is None:
        raise RuntimeError(f"{st['name']}: ${addr:04X} reads {seen.hex()}, "
                           f"from none of {[hex(c) for c in cands]}")
    entry["read"] = f"{src:07X}"
    fresh = signature(addr, 0xA5)
    xm.write(0x7770000 | addr, fresh)
    dst = find(xm, cands, fresh) or find(xm, cands, bytes(b & 0x0F for b in fresh))
    if dst is not None and xm.read(dst, 16) != fresh:
        entry["write_and"] = 0x0F
    entry["write"] = None if dst is None else f"{dst:07X}"
    return entry


def flat_rom_write(xm):
    """A flat STA [zp],Z into ROM: is it dropped?"""
    target = 0x3E123
    before = xm.read(target, 1)[0]
    xm.write(0x1980, bytes([target & 0xFF, target >> 8 & 0xFF, target >> 16, 0]))
    seq = [[0x78], [0xA9, 0x19], [0x5B], [0xA3, 0x00],    # SEI, B=$19, Z=0
           [0xA9, before ^ 0xFF], [0xEA], [0x92, 0x80],   # STA [$80],Z
           [0xA9, 0x00], [0x5B]]                          # B=0
    xm.run(CODE, seq)
    return dict(target=f"{target:07X}", dropped=xm.read(target, 1)[0] == before)


def record(xm, st):
    set_state(xm, st)
    return dict(name=st["name"],
                setup={k: st[k] for k in ("ddr", "port", "key", "d030",
                                          "mapl", "maph", "mb_lo", "mb_hi")},
                pages=[probe_page(xm, st, p) for p in range(16)])


def boot(xm):
    deadline = time.time() + 60
    while time.time() < deadline:
        r = xm.regs()
        if (r["mapl"], r["maph"]) == (0xE300, 0xB300) and r["pc"] >= 0x8000:
            return
        time.sleep(0.5)
    raise RuntimeError("xmega65 did not reach BASIC 65")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="record only states whose name starts so; print, do not write")
    ap.add_argument("--out", type=pathlib.Path, default=GOLDEN)
    args = ap.parse_args()
    todo = [s for s in states() if not args.only or s["name"].startswith(args.only)]
    recorded = []
    try:
        with XMega65(WORK) as xm:
            boot(xm)
            version = xm.version()
            xm.cmd("t1")
            post = xm.read_cpu(0, 2) + xm.read_cpu(0xD030, 1)
            for st in todo:
                recorded.append(record(xm, st))
                if args.only:
                    print(json.dumps(recorded[-1]))
            rom = flat_rom_write(xm)
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    if args.only:
        print("post-boot $00 $01 $D030:", post.hex(), "flat ROM write:", rom)
        return
    source = dict(xmega65=version, recorded=datetime.date.today().isoformat(),
                  post_boot={"00": post[0], "01": post[1], "D030": post[2]})
    args.out.write_text(
        '{"source": ' + json.dumps(source) + ",\n"
        ' "flat_rom_write": ' + json.dumps(rom) + ",\n"
        ' "states": [\n  '
        + ",\n  ".join(json.dumps(s) for s in recorded)
        + "\n ]}\n")
    print(f"wrote {args.out} ({len(recorded)} states)")


if __name__ == "__main__":
    main()
