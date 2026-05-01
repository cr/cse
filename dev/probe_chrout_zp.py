"""Probe what KERNAL ZP bytes CHROUT actually mutates.

Investigation tool, NOT a test.  Run as:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \
        dev/probe_chrout_zp.py

Loads CSE in py65 via the C64Emu test harness, drives KERNAL CHROUT
($FFD2) with various character classes, and snapshots ZP $00-$FF
before / after to enumerate the bytes that get touched.

The output gives an authoritative answer to the rc2 jank-after-fix
question: which ZP bytes does CHROUT actually mutate that we need
to defend against mid-write NMI corruption?
"""

import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))

from c64emu import C64Emu


# ── Character classes to probe ─────────────────────────────────────────
# Format: (label, char_value, post_setup_action)
# post_setup_action is called after init_cse to put the cursor at a
# meaningful location for the test.
TEST_CHARS = [
    ("printable 'A'",                   0x41),
    ("printable mid-row at col 30",     0x42),  # set col=30 first
    ("printable wraps at col 39",       0x43),  # set col=39 first
    ("CR ($0D)",                        0x0D),
    ("cursor right ($1D)",              0x1D),
    ("cursor left ($9D)",               0x9D),
    ("cursor down ($11)",               0x11),
    ("cursor up ($91)",                 0x91),
    ("home ($13)",                      0x13),
    ("CLR ($93)",                       0x93),
    ("RVS ON ($12)",                    0x12),
    ("RVS OFF ($92)",                   0x92),
    ("colour codes ($1E green)",        0x1E),
    ("DEL ($14)",                       0x14),
    ("INS ($94)",                       0x94),
    ("quote (toggle qtsw)",             0x22),
    ("printable inside quote mode",     0x44),  # set $D4=1 first
]


def snap_zp(emu):
    """Snapshot ZP $00-$FF as a list of 256 byte values."""
    return [emu.memory[a] for a in range(256)]


def diff_zp(before, after):
    """Yield (addr, before_val, after_val) tuples for each changed byte."""
    for a in range(256):
        if before[a] != after[a]:
            yield a, before[a], after[a]


# Names for the ZP bytes that matter.  Anything not in the table is
# printed as "$xx ?".
NAMES = {
    0xC6: "NDX (kbd buffer count)",
    0xC7: "RVS (reverse-video flag)",
    0xC8: "INDX (end-of-input ptr)",
    0xCC: "BLNSW (cursor blink switch)",
    0xCD: "BLNCT (blink countdown)",
    0xCE: "GDBLN (char under blinker)",
    0xCF: "BLNON (blink phase)",
    0xD0: "CRSW (input-from-screen flag)",
    0xD1: "PNT lo (line ptr)",
    0xD2: "PNT hi",
    0xD3: "PNTR (cursor col)",
    0xD4: "QTSW (quote mode)",
    0xD5: "LNMX (logical line max)",
    0xD6: "TBLX (cursor row)",
    0xD7: "DATA (current char temp)",
    0xD8: "INSRT (insert pending)",
    0xF3: "USER lo (color ptr)",
    0xF4: "USER hi",
}
for r in range(25):
    NAMES[0xD9 + r] = f"LDTB1[{r}] (line link row {r})"


def name(addr):
    if addr in NAMES:
        return NAMES[addr]
    if 0x00 <= addr <= 0x01:
        return "CPU port DDR/data"
    if 0x02 <= addr <= 0x5A:
        return "CSE ZP (zp.s)"
    return "?"


def setup_cse(setup_fn=None):
    """Cold-init CSE; optionally apply a setup_fn(emu) before snapshotting."""
    prg = ROOT / "build" / "debug" / "cmos" / "cse-cmos.prg"
    map_path = ROOT / "build" / "debug" / "cmos" / "cse.map"
    emu = C64Emu()
    emu.load_prg(prg, map_path)
    emu.init_cse()
    if setup_fn:
        setup_fn(emu)
    return emu


def run_chrout(emu, ch):
    """Print one char via CSE's io_putc (which calls KERNAL CHROUT
    with the correct banking + colour-port setup).  Direct JSR to
    $FFD2 doesn't reproduce real CHROUT behaviour because the C64
    KERNAL CHROUT path needs $01 banking and $0286 colour set
    correctly — CSE's io_putc handles both."""
    emu.jsr(emu.sym("io_putc"), a=ch)


def probe(label, ch, setup_fn=None):
    """Snapshot ZP, run CHROUT with the given char, snapshot again, diff."""
    emu = setup_cse(setup_fn)
    before = snap_zp(emu)
    try:
        run_chrout(emu, ch)
    except Exception as e:
        return label, ch, [(None, None, f"ERROR: {e}")]
    after = snap_zp(emu)
    changes = list(diff_zp(before, after))
    return label, ch, changes


def fmt_change(c):
    a, b, x = c
    if a is None:
        return f"  {x}"
    return f"  ${a:02X} {b:02X}->{x:02X}  {name(a)}"


def main():
    print("=" * 72)
    print("KERNAL CHROUT ZP-mutation probe")
    print("=" * 72)
    print()

    # Build a setup function for "set col=30 before CHROUT"
    def at_col(c):
        def s(emu):
            emu.memory[0xD3] = c
        return s

    def in_quote_mode(emu):
        emu.memory[0xD4] = 0x01

    setups = {
        "printable mid-row at col 30":      at_col(30),
        "printable wraps at col 39":        at_col(39),
        "printable inside quote mode":      in_quote_mode,
    }

    union_addrs = set()
    by_class = []

    for label, ch in [(t[0], t[1]) for t in TEST_CHARS]:
        setup_fn = setups.get(label)
        _, _, changes = probe(label, ch, setup_fn)
        addrs = {a for a, _, _ in changes if a is not None}
        union_addrs |= addrs
        by_class.append((label, ch, changes))

    # Per-class report
    for label, ch, changes in by_class:
        print(f"── {label} (char ${ch:02X}) ──")
        if not changes:
            print("  (no ZP changes)")
        else:
            for c in changes:
                print(fmt_change(c))
        print()

    # Union summary
    print("=" * 72)
    print("UNION of all ZP addresses touched by CHROUT across char classes:")
    print("=" * 72)
    for a in sorted(union_addrs):
        print(f"  ${a:02X}  {name(a)}")
    print()
    print(f"Total: {len(union_addrs)} bytes")

    # Compare against my fix's coverage
    fix_set = {0xC6, 0xD4, 0xD5, 0xD8, 0xCE} | {0xD9 + r for r in range(25)}
    plot_set = {0xD1, 0xD2, 0xD3, 0xD6, 0xF3, 0xF4}
    covered = (fix_set | plot_set) & union_addrs
    missed  = union_addrs - fix_set - plot_set
    print()
    print("=" * 72)
    print("Coverage analysis:")
    print("=" * 72)
    print(f"  CHROUT touches {len(union_addrs)} ZP bytes")
    print(f"  Covered by kernal_screen_reset (rc2 fix): "
          f"{len(fix_set & union_addrs)}")
    print(f"  Covered by io_sync (KERNAL PLOT):          "
          f"{len(plot_set & union_addrs)}")
    print(f"  Total covered:                              {len(covered)}")
    print(f"  MISSED (CHROUT touches, fix doesn't reset): {len(missed)}")
    if missed:
        print()
        print("  Bytes my fix MISSES — candidates for the residual jank:")
        for a in sorted(missed):
            print(f"    ${a:02X}  {name(a)}")


if __name__ == "__main__":
    main()
