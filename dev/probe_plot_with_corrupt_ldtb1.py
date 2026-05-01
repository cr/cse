"""Probe: does KERNAL PLOT misbehave with a corrupt line-link table?

Confirms the working hypothesis: the rc1 jank is *not* "CSE was
mid-CHROUT when NMI fired" (CSE bypasses KERNAL CHROUT for screen
output via io_putc).  It's "USERLAND was mid-CHROUT when NMI fired,
and KERNAL screen-edit ZP retained mid-update state across the
@userland_nmi → hygiene_after_userland → main_loop_top path,
because hygiene_after_userland never touched LDTB1 / $D5 / $D8 etc."

This script:
  1. Initialises CSE.
  2. Sets cursor at row 10, col 5 via PLOT.
  3. Captures the resulting $D1/$D2/$F3/$F4 (the "clean" reference).
  4. Corrupts LDTB1 to simulate mid-CHROUT state (some rows marked
     as logical-line continuations, low bits non-pristine).
  5. Calls PLOT again with the same row/col.
  6. Reports any drift in $D1/$D2/$F3/$F4 — that drift IS the jank.
"""

import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from c64emu import C64Emu


def setup():
    prg = ROOT / "build" / "debug" / "cmos" / "cse-cmos.prg"
    map_path = ROOT / "build" / "debug" / "cmos" / "cse.map"
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.init_cse()
    return emu


def plot(emu, row, col):
    """KERNAL PLOT (CLC = set position) — mirrors what io_sync does."""
    emu._cpu.x = row
    emu._cpu.y = col
    emu.carry = False
    emu.jsr(0xFFF0)


def snap_screen_ptrs(emu):
    return {
        "D1/D2 PNT":  (emu.memory[0xD1], emu.memory[0xD2]),
        "D3 col":     emu.memory[0xD3],
        "D5 LNMX":    emu.memory[0xD5],
        "D6 row":     emu.memory[0xD6],
        "F3/F4 USER": (emu.memory[0xF3], emu.memory[0xF4]),
    }


def fmt_ptrs(name, p):
    print(f"  {name}:")
    for k, v in p.items():
        if isinstance(v, tuple):
            print(f"    {k}: ${v[0]:02X}${v[1]:02X}")
        else:
            print(f"    {k}: ${v:02X}")


def main():
    emu = setup()
    print("─" * 72)
    print("CASE A: clean LDTB1 (all rows = $80, single-row logical lines)")
    print("─" * 72)
    # Force clean state
    for r in range(25):
        emu.memory[0xD9 + r] = 0x80
    emu.memory[0xD5] = 39
    plot(emu, row=10, col=5)
    clean = snap_screen_ptrs(emu)
    fmt_ptrs("after PLOT(10,5) with clean LDTB1", clean)

    # Reset and corrupt
    emu = setup()
    print()
    print("─" * 72)
    print("CASE B: LDTB1 says rows 9-10 are part of a 2-row logical line")
    print("─" * 72)
    print("(simulates userland CHROUT having wrapped a long line "
          "before NMI fired)")
    for r in range(25):
        emu.memory[0xD9 + r] = 0x80
    # Row 10 is a continuation of a 2-row logical line starting at row 9
    emu.memory[0xD9 + 10] = 0x00            # row 10 is continuation
    emu.memory[0xD5] = 79                   # 2-row LNMX
    plot(emu, row=10, col=5)
    corrupt = snap_screen_ptrs(emu)
    fmt_ptrs("after PLOT(10,5) with corrupt LDTB1", corrupt)

    print()
    print("─" * 72)
    print("DIFF (clean -> corrupt):")
    print("─" * 72)
    drift = False
    for k in clean:
        if clean[k] != corrupt[k]:
            print(f"  {k}: {clean[k]} → {corrupt[k]}  ◄ JANK SOURCE")
            drift = True
    if not drift:
        print("  (no drift — corrupt LDTB1 doesn't affect PLOT for this case)")


if __name__ == "__main__":
    main()
