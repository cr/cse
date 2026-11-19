#!/usr/bin/env python3
"""capture_m65_editor.py — record the MEGA65 screen editor's API in xmega65 (A1).

Owner: doc/build_system.md

Contract source: [doc/platform_layer.md § Terminal](../doc/platform_layer.md#terminal),
§ Display; analysis task A1 of [doc/TODO.md § M65 slice 2](../doc/TODO.md#m65-slice-2--the-mega65-platform-r7-platform-layer).

On each MEGA65 ROM given, xmega65 RUNs the premise recorder's probe
PRG (`10 SYS 8205`, parked by a JMP to itself) and, from that parked
program — the run premise: the SYS map, B = 0 — calls the documented
screen-editor entries the m65 terminal and display bodies would use,
and records what they do:

- the jump table: the opcode at each entry CSE may call (a missing
  entry is not a JMP);
- SCRORG in 80 x 25, 80 x 50, 40 x 25 and under a window (ESC T / B);
- the VIC-IV register set the KERNAL leaves for each text mode (P2:
  vic_reset writes it back);
  PLOT relative to the window, its error, and HOME HOME leaving it;
- logical lines: a RETURN after printing past the right margin, after
  the rows were then overwritten directly in screen RAM, and after
  ESC O; a print at the bottom row after the rows were moved up
  directly (as CSE scrolls);
- an interrupted BSOUT (a scrolling one, stopped after k steps as an
  NMI-to-cse_refresh abandons it, at points spread over its whole
  length), then ESC O + PLOT, or PLOT alone, and a print: where the
  print lands, and where the next RETURN puts the cursor;
- quote and insert mode left on, and what cancels them (a fresh machine per case);
- SYSFLAGS as the premise has it; GETIN with empty queues; ADDKEY then
  GETIN; the colour a BSOUT colour code gives the next character;
- the base-page-0 cells each call writes (the userland contract's
  clobbered list).

One entry per ROM goes into tests/fixtures/golden/m65_editor.json (no
ROM content, so it is committed).

    python dev/capture_m65_editor.py --rom 920413.bin --rom rom/mega65.rom

Needs xmega65, mtools and the user's configured MEGA65 SD image; about
3 minutes per ROM (the interrupted BSOUT is stepped through the
monitor).  Run by hand; pytest never starts xmega65.
"""
import argparse
import contextlib
import datetime
import pathlib
import shutil
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "dev"))

from capture_m65_premise import ENTRY, PARK, probe_prg     # noqa: E402
from find_m65_rom import (TARGET, check_booted, check_native,  # noqa: E402
                          install, rom_version)
from xmega65 import XMega65, write_recording               # noqa: E402

WORK = ROOT / "build" / "m65_editor_capture"
GOLDEN = ROOT / "tests" / "fixtures" / "golden" / "m65_editor.json"
OUT = 0x1600                     # results the probe code stores (0.1600-0.16FF)
SCREEN = 0x0800                  # 80 x 25 and 40 x 25 (memory_design.md)
COLOUR = 0xFF80000               # colour RAM
ESC, CR, HOME = 0x1B, 0x0D, 0x13

ENTRIES = {"BSOUT": 0xFFD2, "BASIN": 0xFFCF, "GETIN": 0xFFE4,
           "PLOT": 0xFFF0, "SCRORG": 0xFFED, "STOP": 0xFFE1,
           "ScanStopKey": 0xFFEA, "SYSFLAGS": 0xFF47, "ADDKEY": 0xFF4A,
           "CURSOR": 0xFF35, "PRIMM": 0xFF7D, "VECTOR": 0xFF8D,
           "SETBNK": 0xFF6B, "READSS": 0xFFB7}


# ── code ──────────────────────────────────────────────────────────

def jsr(a):
    return [0x20, a & 0xFF, a >> 8]


def bsout(*chars):
    out = []
    for c in chars:
        out += [0xA9, c] + jsr(0xFFD2)
    return out


def plot_set(row, col):
    return [0xA2, row, 0xA0, col, 0x18] + jsr(0xFFF0)


def plot_read(out):
    """PLOT read; X (row) to out, Y (column) to out + 1."""
    return [0x38] + jsr(0xFFF0) + [0x8E, out & 0xFF, out >> 8,
                                   0x8C, (out + 1) & 0xFF, (out + 1) >> 8]


def call(xm, body):
    """Run `body` from the parked program, then park; the registers."""
    code = list(body) + [0x4C, PARK & 0xFF, PARK >> 8]
    start = PARK - len(code) + 3
    assert start >= OUT + 0x100, "probe code too long"
    xm.write(start, code)
    xm.cmd(f"g {start:x}")
    return xm.run_to(PARK)


def regs(r, *names):
    return {k: r[k] for k in names}


def base_page_diff(xm, body):
    """Run body from a fixed state (80 x 25 cleared, the cursor at
    12,40); the base-page-0 cells it changed.  A change, not a write:
    a write of the value already there is invisible to a program, and
    the fixed start makes the answer the same on every machine."""
    call(xm, bsout(ESC, ord("8")) + plot_set(12, 40))
    before = xm.read(0x0000, 0x100)
    call(xm, body)
    after = xm.read(0x0000, 0x100)
    return [f"{a:02X}" for a in range(2, 0x100) if before[a] != after[a]]


def screen_row(xm, row, width=80, base=SCREEN):
    return xm.read(base + row * width, width)


# ── probes ────────────────────────────────────────────────────────

def jump_table(xm):
    return {name: f"{xm.read_cpu(a, 1)[0]:02X}" for name, a in ENTRIES.items()}


def scrorg(xm):
    """SCRORG's answers per mode, under a window, and after HOME HOME."""
    def ask():
        r = call(xm, jsr(0xFFED))
        return dict(regs(r, "a", "x", "y", "z"), c=r["p"] & 1)
    out = {"80x25": ask()}
    call(xm, bsout(ESC, ord("5")))
    out["80x50"] = ask()
    out["80x50 D060-D063"] = list(xm.read_cpu(0xD060, 4))
    call(xm, bsout(ESC, ord("4")))
    out["40x25"] = ask()
    call(xm, bsout(ESC, ord("8")))
    out["80x25 again"] = ask()
    # a window from (2,3) to (10,40): ESC T at its top left, ESC B at
    # its bottom right
    call(xm, plot_set(2, 3) + bsout(ESC, ord("T")) + plot_set(10, 40)
         + bsout(ESC, ord("B")))
    out["window 2,3-10,40"] = ask()
    r = call(xm, plot_set(0, 0) + bsout(ord("X")) + plot_read(OUT))
    out["window: PLOT 0,0 then X"] = dict(
        plot_read=list(xm.read(OUT, 2)),
        screen_row2=screen_row(xm, 2)[:8].hex(" "))
    r = call(xm, plot_set(20, 70))
    out["window: PLOT 20,70 outside"] = dict(c=r["p"] & 1)
    call(xm, bsout(HOME, HOME))
    out["after HOME HOME"] = ask()
    return out


# The VIC-IV registers a text mode consists of (book Q): control,
# memory pointers, the IRQ mask, the speed and H640/V400 bits, the line
# step, character count, the screen and colour-RAM pointers, the rows.
VIC_REGS = (0x11, 0x16, 0x18, 0x1A, 0x31, 0x54, 0x58, 0x59, 0x5A, 0x5B,
            0x5C, 0x5D, 0x5E, 0x60, 0x61, 0x62, 0x63, 0x64, 0x65, 0x7B)


def vic_modes(xm):
    """The VIC-IV register set the KERNAL leaves after ESC 8, ESC 5 and
    ESC 4 — what vic_reset writes back for each mode."""
    out = {}
    for mode, key in (("80x25", "8"), ("80x50", "5"), ("40x25", "4")):
        call(xm, bsout(ESC, ord(key)))
        out[mode] = {f"D0{r:02X}": xm.read_cpu(0xD000 + r, 1)[0] for r in VIC_REGS}
    call(xm, bsout(ESC, ord("8")))
    return out


def logical_lines(xm):
    """Does the editor keep hidden logical-line state?"""
    out = {}
    call(xm, bsout(ESC, ord("8")))                       # clear, 80 x 25
    long = [0x41] * 100                                  # past the margin
    call(xm, plot_set(3, 0) + bsout(*long))
    call(xm, plot_set(3, 0) + bsout(CR) + plot_read(OUT))
    out["printed past margin, RETURN at 3,0 -> row"] = xm.read(OUT, 1)[0]
    # the rows overwritten directly, as CSE's io_putc does
    xm.write(SCREEN + 3 * 80, b"\x20" * 160)
    call(xm, plot_set(3, 0) + bsout(CR) + plot_read(OUT))
    out["rows rewritten directly, RETURN at 3,0 -> row"] = xm.read(OUT, 1)[0]
    call(xm, plot_set(3, 0) + bsout(ESC, ord("O"), CR) + plot_read(OUT))
    out["then ESC O, RETURN at 3,0 -> row"] = xm.read(OUT, 1)[0]
    # CSE's own scroll: every row moved up one directly, the last cleared
    call(xm, bsout(ESC, ord("8")))
    call(xm, plot_set(23, 0) + bsout(*long))             # rows 23-24 linked?
    scr = bytearray(xm.read(SCREEN, 2000))
    scr[0:1920], scr[1920:2000] = scr[80:2000], b"\x20" * 80
    xm.write(SCREEN, bytes(scr))
    call(xm, plot_set(24, 0) + bsout(*[0x42] * 90) + plot_read(OUT))
    out["after a direct scroll: 90 chars from 24,0 -> cursor"] = list(xm.read(OUT, 2))
    out["after a direct scroll: rows 22-24 first chars"] = [
        f"{screen_row(xm, r)[0]:02X}" for r in (22, 23, 24)]
    return out


def scrolling_bsout_length(xm):
    """The steps a BSOUT at the bottom right corner (it scrolls) takes."""
    call(xm, bsout(ESC, ord("8")))
    call(xm, plot_set(24, 79))
    start = OUT + 0x80
    xm.write(start, [0xA9, ord("Z")] + jsr(0xFFD2) + [0x4C, PARK & 0xFF, PARK >> 8])
    xm.cmd(f"g {start:x}")
    xm.regs()
    n = 0
    while xm.step()["pc"] != PARK:
        n += 1
        if n > 20000:
            raise RuntimeError("BSOUT did not return")
    return n


def spread(xm, points=48):
    """k across the whole scrolling BSOUT, its last steps included."""
    n = scrolling_bsout_length(xm)
    ks = sorted({round(i * n / points) for i in range(points + 1)} | {n - 1, n - 2})
    return [k for k in ks if 0 <= k <= n]


def interrupted_bsout(xm, steps):
    """A scrolling BSOUT stopped after k steps, then a recovery — ESC O
    and PLOT, or PLOT alone — and a print: where the print lands and
    where RETURN goes.  `stepped` is how far the BSOUT got (it ends at
    PARK: k past its length runs it to completion)."""
    out = []
    for recovery in ("ESC O + PLOT", "PLOT"):
        for k in steps(xm):
            call(xm, bsout(ESC, ord("8")))
            call(xm, plot_set(24, 79))
            start = OUT + 0x80
            xm.write(start, [0xA9, ord("Z")] + jsr(0xFFD2)
                     + [0x4C, PARK & 0xFF, PARK >> 8])
            xm.cmd(f"g {start:x}")
            xm.regs()
            stepped = 0
            while stepped < k:
                r = xm.step()
                stepped += 1
                if r["pc"] == PARK:
                    break
            fix = bsout(ESC, ord("O")) if recovery == "ESC O + PLOT" else []
            call(xm, fix + plot_set(10, 0) + bsout(ord("H"), ord("I"))
                 + plot_read(OUT) + bsout(CR) + plot_read(OUT + 2))
            out.append(dict(recovery=recovery, k=k, stepped=stepped,
                            hi_at_10_0=screen_row(xm, 10)[:2].hex(" "),
                            after_hi=list(xm.read(OUT, 2)),
                            after_return=list(xm.read(OUT + 2, 2))))
    return out


MODE_FIXES = (("none", []), ("ESC O", [ESC, ord("O")]), ("RETURN", [CR]),
              ("HOME HOME RETURN", [HOME, HOME, CR]), ("quote", [0x22]),
              ("shifted RETURN", [0x8D]))
MODE_SETUPS = (("plain", []), ("quote", [0x22]), ("insert", [0x94] * 3))


def editor_modes(fresh):
    """Quote and insert mode, left on as a program can leave them: what
    cancels them through BSOUT?  Each case on a fresh machine — a mode
    left on survives into the next probe (ESC 8 is then printed, not
    obeyed); `fresh()` is a context manager giving a parked machine.
    After setup and fix, row 12 is cleared directly in screen RAM, the
    cursor put at (12,5), and a cursor-right ($1D) sent: it moves the
    cursor over a blank (the mode is off) or prints a reverse glyph
    there (still on).  "plain" checks the probe itself."""
    out = {}
    for name, setup in MODE_SETUPS:
        for fix_name, fix in MODE_FIXES:
            if name == "plain" and fix_name != "none":
                continue
            with fresh() as xm:
                call(xm, plot_set(6, 0) + bsout(ord("X")) + bsout(*setup)
                     + bsout(*fix))
                xm.write(SCREEN + 12 * 80, b"\x20" * 80)
                call(xm, plot_set(12, 5) + bsout(0x1D) + plot_read(OUT))
                cell, col = screen_row(xm, 12)[5], xm.read(OUT + 1, 1)[0]
            out[f"{name}, {fix_name}"] = (
                "off" if (cell, col) == (0x20, 6) else f"on (cell {cell:02X})")
    return out


def keyboard_and_flags(xm):
    out = {}
    r = call(xm, [0x38] + jsr(0xFF47))
    out["SYSFLAGS"] = f"{r['a']:02X}"
    r = call(xm, jsr(0xFFE4))
    out["GETIN empty"] = dict(a=r["a"], c=r["p"] & 1)
    call(xm, [0xA9, ord("Q")] + jsr(0xFF4A))
    r1 = call(xm, jsr(0xFFE4))
    r2 = call(xm, jsr(0xFFE4))
    out["ADDKEY Q, GETIN, GETIN"] = [r1["a"], r2["a"]]
    r = call(xm, jsr(0xFFEA))
    out["ScanStopKey idle"] = dict(a=f"{r['a']:02X}", n=r["p"] >> 7 & 1)
    call(xm, bsout(ESC, ord("8")) + plot_set(5, 0) + bsout(0x1E, ord("C")))
    out["colour after code $1E (green)"] = xm.read(COLOUR + 5 * 80, 1)[0] & 0x0F
    return out


def clobbers(xm):
    return {
        "BSOUT 'A'": base_page_diff(xm, bsout(0x41)),
        "BSOUT CR": base_page_diff(xm, bsout(CR)),
        "PLOT set": base_page_diff(xm, plot_set(7, 9)),
        "PLOT read": base_page_diff(xm, [0x38] + jsr(0xFFF0)),
        "SCRORG": base_page_diff(xm, jsr(0xFFED)),
        "GETIN": base_page_diff(xm, jsr(0xFFE4)),
        "ScanStopKey": base_page_diff(xm, jsr(0xFFEA)),
        "SYSFLAGS read": base_page_diff(xm, [0x38] + jsr(0xFF47)),
        "ESC O": base_page_diff(xm, bsout(ESC, ord("O"))),
    }


# ── one ROM ───────────────────────────────────────────────────────

def park(xm):
    """Wait for the probe PRG's SYS entry; park the program there."""
    for _ in range(50):
        regs_ = xm.run_to(ENTRY)
        if regs_["pc"] == ENTRY and regs_["mapl"] != 0xE300:
            break
    else:
        raise RuntimeError(f"the PRG's SYS entry was not reached: {regs_}")
    xm.write(PARK, [0x4C, PARK & 0xFF, PARK >> 8])


def capture(xm):
    park(xm)
    return dict(jump_table=jump_table(xm), clobbers=clobbers(xm),
                scrorg=scrorg(xm), vic_modes=vic_modes(xm),
                logical_lines=logical_lines(xm),
                keyboard_and_flags=keyboard_and_flags(xm),
                interrupted_bsout=interrupted_bsout(xm, spread))


@contextlib.contextmanager
def _parked(rom_path, prg):
    with XMega65(WORK / "modes", rom=rom_path, prg=prg) as xm:
        park(xm)
        yield xm


def record(rom_path):
    data = pathlib.Path(rom_path).read_bytes()
    check_native(data)
    WORK.mkdir(parents=True, exist_ok=True)
    prg = WORK / "probe.prg"
    prg.write_bytes(probe_prg())
    try:
        with XMega65(WORK / "run", rom=rom_path, prg=prg) as xm:
            entry = capture(xm)
            check_booted(xm.booted_rom(), target=rom_path)
            version = xm.version()
        entry["editor_modes"] = editor_modes(lambda: _parked(rom_path, prg))
    finally:
        shutil.rmtree(WORK, ignore_errors=True)
    print(f"{rom_version(data)}: recorded")
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
    write_recording(GOLDEN, header, "roms", sorted(entries, key=lambda e: e["rom"]))
    print(f"wrote {GOLDEN.relative_to(ROOT)} ({len(entries)} ROMs)")


if __name__ == "__main__":
    main()
