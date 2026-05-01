"""Probe: where does CHROUT actually land output rows after the
LDTB1=$80 reset, vs after the canonical $84-$87 reset?

Reproduces the user's "output stuck in upper third" symptom in
py65 against the real KERNAL ROM.
"""
import sys, pathlib
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


def all_80(emu):
    """My fix's LDTB1 — all $80."""
    for r in range(25):
        emu.memory[0xD9 + r] = 0x80


def canonical(emu):
    """KERNAL CINT's LDTB1 — $80 | scr_hi[r]."""
    for r in range(25):
        scr_hi = (0x0400 + r * 40) >> 8
        emu.memory[0xD9 + r] = 0x80 | scr_hi


def home(emu):
    """Home cursor to (0, 0) via PLOT."""
    emu._cpu.x = 0
    emu._cpu.y = 0
    emu.carry = False
    emu.jsr(0xFFF0)


def chrout_str(emu, s):
    """Print a string via $FFD2."""
    for c in s:
        emu.jsr(0xFFD2, a=ord(c))


def report_screen(emu, label):
    print(f"\n{'─'*72}\n{label}\n{'─'*72}")
    print(f"  $D1/$D2 = ${emu.memory[0xD1]:02X}${emu.memory[0xD2]:02X}")
    print(f"  $D3 (col) = {emu.memory[0xD3]}")
    print(f"  $D6 (row) = {emu.memory[0xD6]}")
    # Show first non-space character on each row
    for r in range(25):
        addr = 0x0400 + r * 40
        chars = bytes(emu.memory[addr + c] for c in range(40))
        # Convert screen codes to ASCII for display
        ascii_chars = ""
        for c in chars:
            if 0x01 <= c <= 0x1A:
                ascii_chars += chr(c + ord('@'))
            elif c == 0x20:
                ascii_chars += ' '
            elif c == 0x00:
                ascii_chars += '@'  # NUL displays as @ in screen code
            else:
                ascii_chars += '.'
        ascii_chars = ascii_chars.rstrip()
        if ascii_chars:
            print(f"  row {r:2d}: '{ascii_chars}'")


def trace_one_line(label, ldtb1_setter):
    emu = setup()
    ldtb1_setter(emu)
    # Test row 10 (in page $05) — only canonical LDTB1 should resolve to $05xx.
    emu._cpu.x = 10
    emu._cpu.y = 0
    emu.carry = False
    emu.jsr(0xFFF0)  # PLOT
    print(f"\n{'─'*72}\n{label}")
    print(f"After PLOT(row=10, col=0):")
    print(f"  $D1/$D2 = ${emu.memory[0xD1]:02X}${emu.memory[0xD2]:02X} "
          f"(expect $0400+10*40=${0x0400+10*40:04X} → $D1=${(0x0400+10*40)&0xFF:02X} "
          f"$D2=${(0x0400+10*40)>>8:02X})")
    # Now print one char
    emu.jsr(0xFFD2, a=ord('A'))
    # Find where it landed
    for r in range(25):
        for c in range(40):
            v = emu.memory[0x0400 + r*40 + c]
            if v == 0x01:  # screen code 'A'
                print(f"  'A' landed at row={r}, col={c} "
                      f"(addr=$0400+{r*40+c}=${0x0400+r*40+c:04X})")


def main():
    trace_one_line("TEST 1: LDTB1 = all $80 (my fix's value)", all_80)
    trace_one_line("TEST 2: LDTB1 = $80 | scr_hi[r] (canonical)", canonical)


if __name__ == "__main__":
    main()
