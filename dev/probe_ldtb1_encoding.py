"""Probe: what does KERNAL actually put in LDTB1 after CINT/init?

If LDTB1[r] is just "$80 = logical-line start", my fix is right.
If LDTB1[r] = $80 | scr_hi[r] (i.e., the page of the row's screen
address with bit 7 set), my fix is wrong — every row would be
treated as living in page $04, sending CHROUT output exclusively
to $0400-$04FF.
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


def main():
    # Approach: invoke KERNAL CINT ($FF5B) — that's the canonical
    # "init screen editor" entry which (re)builds LDTB1 from scratch.
    # We need to bank KERNAL in for this; init_cse already has it in.
    emu = setup()
    # Run KERNAL's screen-init via CHROUT($93, "CLR") which clears
    # screen + (re)inits the line link table.
    emu.jsr(0xFFD2, a=0x93)  # may or may not work depending on banking
    print("LDTB1 after CHROUT(CLR):")
    for r in range(25):
        scr_addr = 0x0400 + r * 40
        expected_84_with_page = 0x80 | (scr_addr >> 8)
        expected_just_80 = 0x80
        actual = emu.memory[0xD9 + r]
        flag_addr = "✓" if actual == expected_84_with_page else " "
        flag_just = "✓" if actual == expected_just_80 else " "
        print(f"  row {r:2d}: scr=${scr_addr:04X} hi=${scr_addr>>8:02X}  "
              f"LDTB1=${actual:02X}   "
              f"page-encoded(${expected_84_with_page:02X}){flag_addr}  "
              f"plain(${expected_just_80:02X}){flag_just}")


if __name__ == "__main__":
    main()
