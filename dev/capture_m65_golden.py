#!/usr/bin/env python3
"""capture_m65_golden.py — record the 45GS02 golden file in xmega65.

Owner: doc/build_system.md

Runs one short instruction sequence per case in xmega65 (headless,
single-stepped over its uartmon socket) and writes
tests/fixtures/golden/m65_cpu.json: per case the registers and the
memory differences before and after the instruction under test.
tests/unit/test_mpu45gs02.py replays every case on MPU45GS02
(tests/m65emu/golden.py has the file's format).

Each case runs in block 0 ($0000-$1FFF), which BASIC 65's post-boot
MAP leaves unmapped, so a CPU address there is its flat address and
uartmon's `s`/`m` (flat) see what the CPU sees.  The registers are set
by a preamble the CPU executes (uartmon cannot set them); the state
recorded as `before` is read after the preamble, so the preamble's
own semantics do not matter.  A prefixed instruction is several
xmega65 steps ($42 and $EA are real NEG/EOM steps); `steps` records
how many.

The case list is a function of the compendium fixture, so a re-record
on the same xmega65 gives the same file; the xmega65 version is
recorded.  Re-record only when xmega65 is updated or a case is added,
and review the diff: a changed `after` is a behaviour change of the
reference, which the commit must state.

    python dev/capture_m65_golden.py                 # all cases
    python dev/capture_m65_golden.py --only ADC      # cases named ADC*, printed

Needs xmega65 and the user's configured MEGA65 SD image (it is
cloned copy-on-write, never written).
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

from m65emu import golden as G                    # noqa: E402
from m65emu import isa                            # noqa: E402
from xmega65 import XMega65                       # noqa: E402

WORK = ROOT / "build" / "m65_golden"

CODE = 0x1800
BASE = 0x19                      # base page $1900
SP0 = 0x01F0
E, BF, D, I, Z, C, N, V = 0x20, 0x10, 0x08, 0x04, 0x02, 0x01, 0x80, 0x40
POST_BOOT_MAP = (0xE300, 0xB300)  # MAPL, MAPH after BASIC 65 boots

# Memory every case starts from, on top of the pattern: the pointers
# the indirect modes use.
POINTERS = {
    0x1920: 0x40, 0x1921: 0x1A,                       # ($20) → $1A40
    0x1924: 0x00, 0x1925: 0x00, 0x1926: 0x04, 0x1927: 0x00,   # [$24] → $40000
    0x1928: 0x80, 0x1929: 0x1A, 0x192A: 0x00, 0x192B: 0x00,   # [$28] → $1A80
    0x01F1: 0x19, 0x01F2: 0x1A, 0x01F3: 0x1A, 0x01F4: 0x1B,   # (d,SP) pointers
}

DEFAULT_REGS = dict(a=0x3C, x=0x04, y=0x05, z=0x06, p=E | I, sp=SP0)


# ── cases ─────────────────────────────────────────────────────────

def case(name, code, mem=None, **regs):
    r = dict(DEFAULT_REGS, **regs)
    return dict(name=name, code=list(code), mem=dict(mem or {}), regs=r)


def preamble(regs):
    sp = regs["sp"]
    out = [0x78, 0x03,                                 # SEI, SEE
           0xA9, BASE, 0x5B,                           # LDA #B, TAB
           0xA0, sp >> 8, 0x2B,                        # LDY #SPH, TYS
           0xA2, sp & 0xFF, 0x9A]                      # LDX #SPL, TXS
    if not regs["p"] & E:
        out += [0x02]                                  # CLE
    out += [0xA9, regs["p"] | BF, 0x48,                # LDA #P, PHA
            0xA2, regs["x"], 0xA0, regs["y"], 0xA3, regs["z"],
            0xA9, regs["a"], 0x28]                     # PLP
    return out


def preamble_steps(regs):
    return 15 if regs["p"] & E else 16


# The tail runs after an instruction that falls through: it ends any
# prefix or MAP latch the instruction left, so the next `g` (which
# drains them by stepping) has nothing to run.
TAIL = [0xEA, 0xA9, 0x00]


def operands(row):
    """Operand bytes and register overrides for a row's mode."""
    m, op = row.mode, row.key[-1]
    n = row.length - len(row.key)
    if m in ("implied", "accumulator", "Q Pseudo Register"):
        return [], {}
    if m == "immediate 8bit":
        return [0x5A if row.mnemonic != "RTS" else 0x02], {}
    if m == "immediate 16bit":
        return [0x34, 0x12], {}
    if m in ("base-page", "base-page quad"):
        return [0x10], {}
    if m in ("base-page,X", "base-page quad,X"):
        return [0xF8], {"x": 0x10}
    if m == "base-page,Y":
        return [0xF8], {"y": 0x10}
    if m in ("absolute", "absolute quad"):
        if row.mnemonic in ("JMP", "JSR"):
            return [0x30, 0x18], {}
        return [0x10, 0x1A], {}
    if m in ("absolute,X", "absolute quad,X"):
        return [0xF8, 0x1A], {"x": 0x10}
    if m == "absolute,Y":
        return [0xF8, 0x1A], {"y": 0x10}
    if m == "(indirect,X)":
        if n == 2:                                     # JMP/JSR ($nnnn,X)
            return [0x10, 0x1A], {"x": 0x04}
        return [0x1C], {"x": 0x04}
    if m == "(indirect),Y":
        return [0x20], {"y": 0x05}
    if m in ("(indirect),Z", "(indirect quad),Z"):
        return [0x20], {"z": 0x06}
    if m == "(indirect quad)":
        return [0x20], {}
    if m == "(immediate,SP),Y":
        return [0x02], {"y": 0x03}
    if m == "(indirect)":
        return [0x10, 0x1A], {}
    if m in ("[indirect],Z", "[indirect quad],Z"):
        return [0x24], {"z": 0x05}
    if m == "[indirect quad]":
        return [0x24], {}
    if m == "relative":
        return [0x10], {}
    if m == "16-bit relative":
        return [0x10, 0x00], {}
    if m == "base-page+rel":
        return [0x10, 0x10], {}
    raise ValueError(f"no operands for mode {m!r} ({row})")


def label(row):
    return f"{row.mnemonic} {row.mode} [{' '.join('%02X' % b for b in row.key)}]"


def cases():
    out = []
    table = isa.decode_table()
    for key, row in sorted(table.items(), key=lambda kv: (len(kv[0]), kv[0])):
        if row.mnemonic in isa.RESERVED or key == (0x00,):
            continue
        ops, regs = operands(row)
        out.append(case(label(row), list(key) + ops, **regs))
        # both outcomes of every conditional branch
        if row.mode in ("relative", "16-bit relative") and row.mnemonic != "BRA":
            for p in (E | I, E | I | N | V | Z | C):
                out.append(case(label(row) + f" p={p:02X}", list(key) + ops, p=p))
        if row.mode == "base-page+rel":
            for v in (0x00, 0xFF):
                out.append(case(label(row) + f" m={v:02X}", list(key) + ops,
                                mem={0x1910: v}))
    out += sweeps()
    return out


def sweeps():
    """Edge cases beyond one per row: flags, wraps, stacks, prefixes."""
    out = []
    add = out.append
    for a, m, p in [(0x50, 0x50, 0), (0xFF, 0x01, 0), (0x7F, 0x00, C),
                    (0x80, 0xFF, 0), (0x19, 0x01, D), (0x99, 0x01, D),
                    (0x50, 0x50, D | C), (0x0F, 0x01, D), (0x9A, 0x00, D)]:
        add(case(f"ADC # a={a:02X} m={m:02X} p={p:02X}", [0x69, m], a=a, p=E | I | p))
        add(case(f"SBC # a={a:02X} m={m:02X} p={p:02X}", [0xE9, m], a=a, p=E | I | p | C))
        add(case(f"SBC # a={a:02X} m={m:02X} p={p:02X} borrow", [0xE9, m], a=a,
                 p=E | I | (p & ~C)))
    for op, reg in [(0xC9, "a"), (0xE0, "x"), (0xC0, "y"), (0xC2, "z")]:
        for r, m in [(0x40, 0x40), (0x40, 0x41), (0x41, 0x40), (0x00, 0x80)]:
            add(case(f"compare {op:02X} r={r:02X} m={m:02X}", [op, m], **{reg: r}))
    for a, m in [(0x00, 0xC0), (0xFF, 0x40), (0x0F, 0xF0)]:
        add(case(f"BIT # a={a:02X} m={m:02X}", [0x89, m], a=a))
    for op in (0x0A, 0x4A, 0x2A, 0x6A, 0x43, 0x42, 0x1A, 0x3A):
        for a, p in [(0x80, 0), (0x01, C), (0x00, C), (0xFF, 0)]:
            add(case(f"A-op {op:02X} a={a:02X} p={p:02X}", [op], a=a, p=E | I | p))
    # stacks: E set wraps in the page, E clear moves SPH
    for p in (E | I, I):
        tag = "E" if p & E else "16"
        add(case(f"PHA SP=0100 {tag}", [0x48], sp=0x0100, p=p))
        add(case(f"PLA SP=01FF {tag}", [0x68], sp=0x01FF, p=p))
        add(case(f"JSR SP=0101 {tag}", [0x20, 0x30, 0x18], sp=0x0101, p=p))
        add(case(f"RTS #3 SP=01FD {tag}", [0x62, 0x03], sp=0x01FD, p=p))
        add(case(f"PHP {tag}", [0x08], p=p | C | N))
        add(case(f"TSX {tag}", [0xBA], sp=0x01F0, p=p))
        add(case(f"LDA (d,SP),Y SP=01FF {tag}", [0xE2, 0x01], sp=0x01FF, y=0x01, p=p,
                 mem={0x0100: 0x50, 0x0101: 0x1A, 0x0200: 0x60, 0x0201: 0x1A}))
    add(case("PLP E clear on stack", [0x28], mem={0x01F1: 0xC3}))
    add(case("PLP all set on stack", [0x28], mem={0x01F1: 0xFF}))
    add(case("RTI", [0x40], mem={0x01F1: 0xC3, 0x01F2: 0x40, 0x01F3: 0x18}))
    add(case("RTS", [0x60], mem={0x01F1: 0x3F, 0x01F2: 0x18}))
    add(case("TYS Y=02", [0x2B], y=0x02))
    add(case("TSY", [0x0B], sp=0x0280))
    add(case("BRA16 backwards", [0x83, 0xF0, 0xFF]))
    add(case("BSR backwards", [0x63, 0xF0, 0xFF]))
    add(case("INW $FF wraps in the base page", [0xE3, 0xFF],
             mem={0x19FF: 0xFF, 0x1900: 0x12}))
    add(case("DEW $10 borrow", [0xC3, 0x10], mem={0x1910: 0x00, 0x1911: 0x80}))
    add(case("ASW across a page", [0xCB, 0xFF, 0x1A], mem={0x1AFF: 0x87, 0x1B00: 0xA9}))
    add(case("ROW C in", [0xEB, 0x10, 0x1A], p=E | I | C,
             mem={0x1A10: 0x00, 0x1A11: 0x80}))
    add(case("LDQ $FE across the base page", [0x42, 0x42, 0xA5, 0xFE]))
    add(case("LDA [$FE],Z pointer wraps in the base page", [0xEA, 0xB2, 0xFE],
             z=0x01, mem={0x19FE: 0x00, 0x19FF: 0x1A, 0x1900: 0x00, 0x1901: 0x00}))
    add(case("LDA [$28],Z Z=FF", [0xEA, 0xB2, 0x28], z=0xFF))
    add(case("STA [$24],Z", [0xEA, 0x92, 0x24], z=0x07, a=0xA5))
    add(case("LDQ [$24],Z", [0x42, 0x42, 0xEA, 0xB2, 0x24], z=0x02))
    add(case("LDQ ($20),Z Z=03", [0x42, 0x42, 0xB2, 0x20], z=0x03))
    add(case("ADCQ carry out", [0x42, 0x42, 0x65, 0x10], a=0xFF, x=0xFF, y=0xFF,
             z=0xFF, mem={0x1910: 1, 0x1911: 0, 0x1912: 0, 0x1913: 0}))
    add(case("SBCQ borrow", [0x42, 0x42, 0xE5, 0x10], a=0, x=0, y=0, z=0,
             p=E | I | C, mem={0x1910: 1, 0x1911: 0, 0x1912: 0, 0x1913: 0}))
    add(case("CMPQ equal", [0x42, 0x42, 0xC5, 0x10], a=1, x=2, y=3, z=4,
             mem={0x1910: 1, 0x1911: 2, 0x1912: 3, 0x1913: 4}))
    add(case("NEG NEG then a row-less opcode", [0x42, 0x42, 0xA9, 0x05]))
    add(case("EOM then a row-less opcode", [0xEA, 0xA9, 0x05]))
    add(case("EOM then (zp),Y stays 16-bit", [0xEA, 0xB1, 0x20]))
    add(case("MAP post-boot values", [0x5C], a=0x00, x=0xE3, y=0x00, z=0xB3))
    add(case("MAP block 1 offset", [0x5C], a=0x12, x=0x23, y=0x34, z=0xB5))
    add(case("MAP X=0F megabyte", [0x5C], a=0x80, x=0x0F, y=0x00, z=0xB3))
    add(case("MAP Z=0F megabyte", [0x5C], a=0x00, x=0xE3, y=0x80, z=0x0F))
    return out


# ── recording ─────────────────────────────────────────────────────

def snapshot(xm):
    mem = {}
    for start, length in G.REGIONS:
        for k, v in enumerate(xm.read(start, length)):
            mem[start + k] = v
    return mem


def restore_map(xm):
    code = [0xA9, 0x00, 0xA2, 0x0F, 0xA0, 0x00, 0xA3, 0x0F, 0x5C, 0xEA,
            0xA9, POST_BOOT_MAP[0] & 0xFF, 0xA2, POST_BOOT_MAP[0] >> 8,
            0xA0, POST_BOOT_MAP[1] & 0xFF, 0xA3, POST_BOOT_MAP[1] >> 8,
            0x5C, 0xEA, 0xA9, 0x00]
    xm.write(CODE, code)
    xm.cmd(f"g {CODE:x}")
    for _ in range(13):
        xm.step()
    r = xm.regs()
    assert (r["mapl"], r["maph"]) == POST_BOOT_MAP, r


def record(xm, c):
    regs = c["regs"]
    pre = preamble(regs)
    start = CODE + len(pre)
    code = pre + c["code"] + TAIL
    init = {a: G.pattern(a) for a in G.region_addrs()}
    init.update(POINTERS)
    init.update(c["mem"])
    for k, v in enumerate(code):
        init[CODE + k] = v
    for rs, rl in G.REGIONS:
        xm.write(rs, bytes(init[a] for a in range(rs, rs + rl)))
    xm.cmd(f"g {CODE:x}")
    for _ in range(preamble_steps(regs)):
        r = xm.step()
    if r["pc"] != start:
        return None                                  # an interrupt got in
    before = xm.regs()
    mem_before = snapshot(xm)
    end = start + len(c["code"])
    steps = 0
    while True:
        r = xm.step()
        steps += 1
        if not start < r["pc"] < end or steps > 4:
            break
    after = r
    mem_after = snapshot(xm)
    if after["pc"] == end:
        for _ in range(2):
            xm.step()                                # TAIL: end prefix / latch
    if c["code"][0] == 0x5C or (after["mapl"], after["maph"]) != POST_BOOT_MAP:
        restore_map(xm)
    return dict(
        name=c["name"],
        code=" ".join(f"{b:02X}" for b in c["code"]),
        before=before,
        mem={f"{a:05X}": v for a, v in sorted(mem_before.items())
             if v != G.pattern(a)},
        steps=steps,
        after=after,
        mem_after={f"{a:05X}": v for a, v in sorted(mem_after.items())
                   if v != mem_before[a]},
    )


def boot(xm):
    deadline = time.time() + 60
    while time.time() < deadline:
        r = xm.regs()
        if (r["mapl"], r["maph"]) == POST_BOOT_MAP and r["pc"] >= 0x8000:
            time.sleep(2)                            # let BASIC 65 settle
            return
        time.sleep(0.5)
    raise RuntimeError("xmega65 did not reach BASIC 65")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", help="record only cases whose name starts so; print, do not write")
    ap.add_argument("--out", type=pathlib.Path, default=G.GOLDEN)
    args = ap.parse_args()
    out_path = args.out.resolve()
    todo = [c for c in cases() if not args.only or c["name"].startswith(args.only)]
    xm = XMega65(WORK)
    try:
        boot(xm)
        xm_version = xm.version()
        xm.cmd("t1")
        recorded = []
        for n, c in enumerate(todo):
            for _attempt in range(3):
                got = record(xm, c)
                if got:
                    break
            else:
                raise RuntimeError(f"case {c['name']!r}: preamble never completed")
            recorded.append(got)
            if args.only:
                print(json.dumps(got))
            elif n % 50 == 0:
                print(f"{n}/{len(todo)} {c['name']}", file=sys.stderr)
    finally:
        xm.close()
        shutil.rmtree(WORK, ignore_errors=True)
    if args.only:
        return
    source = dict(xmega65=xm_version, recorded=datetime.date.today().isoformat(),
                  fixture=isa.FIXTURE.name)
    # one case per line, so a re-record's diff reads case by case
    lines = ['{"source": ' + json.dumps(source) + ",",
             ' "regions": ' + json.dumps([[s, n] for s, n in G.REGIONS]) + ",",
             ' "cases": [']
    lines += ["  " + json.dumps(c) + "," for c in recorded]
    lines[-1] = lines[-1][:-1]
    lines += [" ]}"]
    out_path.write_text("\n".join(lines) + "\n")
    print(f"wrote {out_path} ({len(recorded)} cases)")


if __name__ == "__main__":
    main()
