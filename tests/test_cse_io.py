"""
test_cse_io.py – unit tests for the cse_io.s screen I/O library.

Uses py65 to execute 6502 code in a simulated 64KB memory space.
Screen RAM at $0400, KERNAL cursor vars at $D1-$D6, $F3-$F4.
"""

import re
import subprocess
import pathlib
import pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

IO_BIN = BUILD / "cse_io_test.bin"
IO_MAP = BUILD / "cse_io_test.map"

SCREEN = 0x0400
COLS   = 40
ROWS   = 25


# ── Build ────────────────────────────────────────────────────────────────────

def _needs_rebuild():
    if not IO_BIN.exists() or not IO_MAP.exists():
        return True
    mtime = IO_BIN.stat().st_mtime
    sources = [
        SRC / "cse_io.s",
        DEV / "cse_io_test_stub.s",
        DEV / "test.cfg",
    ]
    return any(s.stat().st_mtime > mtime for s in sources)


IO_LST = BUILD / "cse_io.lst"

def _build():
    BUILD.mkdir(exist_ok=True)
    subprocess.run(
        ["ca65", "--cpu", "6502",
         "--listing", str(IO_LST),
         str(SRC / "cse_io.s"),
         "-o", str(BUILD / "cse_io.o")],
        check=True)
    subprocess.run(
        ["ca65", "--cpu", "6502", str(DEV / "cse_io_test_stub.s"),
         "-o", str(BUILD / "cse_io_test_stub.o")],
        check=True)
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         str(BUILD / "cse_io.o"),
         str(BUILD / "cse_io_test_stub.o"),
         "-o", str(IO_BIN),
         "-m", str(IO_MAP)],
        check=True)


def _parse_segments():
    """Parse segment starts from map file."""
    seg = {}
    in_seg = False
    for line in IO_MAP.read_text().splitlines():
        if line.startswith("Segment list"):
            in_seg = True
            continue
        if in_seg:
            m = re.match(r"(\w+)\s+([0-9a-fA-F]+)\s+", line)
            if m:
                seg[m.group(1)] = int(m.group(2), 16)
    return seg


def _parse_listing_syms():
    """Parse label → offset-within-segment from ca65 listing."""
    offsets = {}
    for line in IO_LST.read_text().splitlines():
        m = re.match(r"^([0-9a-fA-F]+)r\s+\d+\s.*?\b(_io_\w+):", line)
        if m:
            offsets[m.group(2)] = int(m.group(1), 16)
    return offsets


def _parse_exports():
    """Parse exported symbols from map file."""
    syms = {}
    in_exports = False
    for line in IO_MAP.read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            m = re.match(r"(\w+)\s+([0-9a-fA-F]+)", line)
            if m:
                syms[m.group(1)] = int(m.group(2), 16)
            elif line.strip() == "":
                break
    return syms


class IoSymbols:
    def __init__(self):
        if _needs_rebuild():
            _build()

        seg = _parse_segments()
        ofs = _parse_listing_syms()
        code = seg.get("CODE", 0x0200)

        self.io_sync      = code + ofs["_io_sync"]
        self.io_putc      = code + ofs["_io_putc"]
        self.io_puts      = code + ofs["_io_puts"]
        self.io_puthex4   = code + ofs["_io_puthex4"]
        self.io_puthex2   = code + ofs["_io_puthex2"]
        self.io_putdec    = code + ofs["_io_putdec"]
        self.io_clear_eol = code + ofs["_io_clear_eol"]
        self.io_kbhit     = code + ofs["_io_kbhit"]


        zp_start = seg.get("ZEROPAGE", 0)
        raw = IO_BIN.read_bytes()
        self._zp_start = zp_start
        self._code_start = code
        self._zp_size = 0x100
        self._raw = raw

    def load_into(self, memory):
        memory[self._zp_start:self._zp_start + self._zp_size] = \
            self._raw[:self._zp_size]
        code_blob = self._raw[self._zp_size:]
        memory[self._code_start:self._code_start + len(code_blob)] = code_blob


@pytest.fixture(scope="session")
def io_syms():
    return IoSymbols()


# ── CPU helper ───────────────────────────────────────────────────────────────

RTS_ADDR = 0x01F0  # place an RTS here for JSR returns

PLOT_STUB = 0xFE00  # place our PLOT stub at $FE00 (safe, high memory)

# Screen row addresses: $0400 + row*40
SCR_ROW_LO = [(SCREEN + r * COLS) & 0xFF for r in range(ROWS)]
SCR_ROW_HI = [(SCREEN + r * COLS) >> 8 for r in range(ROWS)]

def make_cpu(io_syms):
    """Create a py65 CPU with the IO binary loaded, cursor at (0,0)."""
    cpu = MPU()
    mem = bytearray(0x10000)
    io_syms.load_into(mem)
    mem[RTS_ADDR] = 0x60  # RTS instruction for return

    # Write a minimal KERNAL PLOT stub at PLOT_STUB.
    # It reads X=row, Y=col and sets $D1/$D2/$D3/$D6/$F3/$F4.
    # We write the scr_lo/scr_hi tables inline.
    # But simpler: just make $FFF0 an RTS and handle sync in Python.
    # Actually simplest: write the stub in machine code.
    #
    # PLOT stub:  BCS @get
    #             STX $D6 / STY $D3
    #             LDA scr_lo_tbl,X / STA $D1 / STA $F3
    #             LDA scr_hi_tbl,X / STA $D2
    #             CLC / ADC #$D4 / STA $F4
    #             RTS
    #  @get:      LDX $D6 / LDY $D3 / RTS
    #
    # Place row tables at PLOT_STUB + 0x30
    tbl = PLOT_STUB + 0x30
    stub = [
        0xB0, 0x16,             # BCS +22 (@get at offset 24)
        0x86, 0xD6,             # STX $D6
        0x84, 0xD3,             # STY $D3
        0xBD, tbl & 0xFF, tbl >> 8,       # LDA tbl_lo,X
        0x85, 0xD1,             # STA $D1
        0x85, 0xF3,             # STA $F3
        0xBD, (tbl+25) & 0xFF, (tbl+25) >> 8,  # LDA tbl_hi,X
        0x85, 0xD2,             # STA $D2
        0x18,                   # CLC
        0x69, 0xD4,             # ADC #$D4
        0x85, 0xF4,             # STA $F4
        0x60,                   # RTS
        # @get (offset 0x16 = 22):
        0xA6, 0xD6,             # LDX $D6
        0xA4, 0xD3,             # LDY $D3
        0x60,                   # RTS
    ]
    for i, b in enumerate(stub):
        mem[PLOT_STUB + i] = b
    # Row address tables
    for r in range(ROWS):
        mem[tbl + r] = SCR_ROW_LO[r]
        mem[tbl + 25 + r] = SCR_ROW_HI[r]

    # Patch $FFF0: JMP PLOT_STUB
    mem[0xFFF0] = 0x4C
    mem[0xFFF1] = PLOT_STUB & 0xFF
    mem[0xFFF2] = PLOT_STUB >> 8

    cpu.memory = mem

    # Init cursor to (0, 0)
    cpu.memory[0xD3] = 0   # column
    cpu.memory[0xD6] = 0   # row

    # Call io_sync to set up $D1/$D2/$F3/$F4
    cpu.pc = io_syms.io_sync
    cpu.sp = 0xFF
    # Push return address (RTS_ADDR - 1 because RTS adds 1)
    cpu.memory[0x01FF] = (RTS_ADDR - 1) >> 8
    cpu.memory[0x01FE] = (RTS_ADDR - 1) & 0xFF
    cpu.sp = 0xFD
    while cpu.pc != RTS_ADDR:
        cpu.step()

    return cpu


def jsr(cpu, addr, a=0, x=0, y=0, max_steps=5000):
    """JSR to addr with given registers. Returns when RTS reached."""
    cpu.a = a
    cpu.x = x
    cpu.y = y
    cpu.pc = addr
    cpu.sp = 0xFF
    cpu.memory[0x01FF] = (RTS_ADDR - 1) >> 8
    cpu.memory[0x01FE] = (RTS_ADDR - 1) & 0xFF
    cpu.sp = 0xFD
    steps = 0
    while cpu.pc != RTS_ADDR and steps < max_steps:
        cpu.step()
        steps += 1
    assert steps < max_steps, f"JSR to ${addr:04X} did not return in {max_steps} steps"


def screen_str(cpu, row, col, length):
    """Read screen codes from screen RAM, convert to readable ASCII."""
    result = []
    for i in range(length):
        sc = cpu.memory[SCREEN + row * COLS + col + i]
        # Reverse conversion: screencode → ASCII for comparison
        if sc >= 0x01 and sc <= 0x1A:
            result.append(chr(sc + 0x40))  # A-Z
        elif sc >= 0x41 and sc <= 0x5A:
            result.append(chr(sc + 0x20))  # a-z (lowercase)
        elif sc >= 0x30 and sc <= 0x39:
            result.append(chr(sc))  # 0-9
        elif sc == 0x20:
            result.append(' ')
        elif sc == 0x2E:
            result.append('.')
        elif sc == 0x3A:
            result.append(':')
        elif sc == 0x2D:
            result.append('-')
        elif sc == 0x2C:
            result.append(',')
        elif sc == 0x28:
            result.append('(')
        elif sc == 0x29:
            result.append(')')
        elif sc == 0x21:
            result.append('!')
        elif sc == 0x3F:
            result.append('?')
        elif sc == 0x22:
            result.append('"')
        elif sc == 0x2A:
            result.append('*')
        elif sc == 0x24:
            result.append('$')
        elif sc == 0x23:
            result.append('#')
        else:
            result.append(f'[{sc:02X}]')
    return ''.join(result)


# ── Tests ────────────────────────────────────────────────────────────────────

class TestIoSync:
    def test_row_0(self, io_syms):
        cpu = make_cpu(io_syms)
        cpu.memory[0xD6] = 0
        jsr(cpu, io_syms.io_sync)
        assert cpu.memory[0xD1] == 0x00  # lo byte of $0400
        assert cpu.memory[0xD2] == 0x04  # hi byte of $0400

    def test_row_1(self, io_syms):
        cpu = make_cpu(io_syms)
        cpu.memory[0xD6] = 1
        jsr(cpu, io_syms.io_sync)
        assert cpu.memory[0xD1] == 0x28  # lo of $0428
        assert cpu.memory[0xD2] == 0x04

    def test_row_24(self, io_syms):
        cpu = make_cpu(io_syms)
        cpu.memory[0xD6] = 24
        jsr(cpu, io_syms.io_sync)
        # $0400 + 24*40 = $0400 + $3C0 = $07C0
        assert cpu.memory[0xD1] == 0xC0
        assert cpu.memory[0xD2] == 0x07

    def test_color_ptr(self, io_syms):
        cpu = make_cpu(io_syms)
        cpu.memory[0xD6] = 0
        jsr(cpu, io_syms.io_sync)
        assert cpu.memory[0xF3] == 0x00  # lo of $D800
        assert cpu.memory[0xF4] == 0xD8  # hi of $D800


class TestIoPutc:
    def test_space(self, io_syms):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_putc, a=0x20)  # space
        assert cpu.memory[SCREEN] == 0x20
        assert cpu.memory[0xD3] == 1  # cursor advanced

    def test_digit(self, io_syms):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_putc, a=0x31)  # '1'
        assert cpu.memory[SCREEN] == 0x31

    def test_uppercase_a(self, io_syms):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_putc, a=0x41)  # 'A' (PETSCII)
        assert cpu.memory[SCREEN] == 0x01  # screen code for A

    def test_uppercase_z(self, io_syms):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_putc, a=0x5A)  # 'Z'
        assert cpu.memory[SCREEN] == 0x1A

    def test_shifted_a(self, io_syms):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_putc, a=0xC1)  # shifted A
        assert cpu.memory[SCREEN] == 0x41  # lowercase 'a' screencode

    def test_colon(self, io_syms):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_putc, a=0x3A)  # ':'
        assert cpu.memory[SCREEN] == 0x3A

    def test_cursor_clamp_at_39(self, io_syms):
        cpu = make_cpu(io_syms)
        cpu.memory[0xD3] = 39  # col 39
        jsr(cpu, io_syms.io_putc, a=0x20)
        assert cpu.memory[0xD3] == 39  # stays at 39, doesn't wrap

    def test_cursor_advance(self, io_syms):
        cpu = make_cpu(io_syms)
        cpu.memory[0xD3] = 5
        jsr(cpu, io_syms.io_putc, a=0x41)
        assert cpu.memory[0xD3] == 6
        assert cpu.memory[SCREEN + 5] == 0x01


class TestIoPuts:
    def test_empty_string(self, io_syms):
        cpu = make_cpu(io_syms)
        # Place NUL-terminated empty string at $1000
        cpu.memory[0x1000] = 0x00
        jsr(cpu, io_syms.io_puts, a=0x00, x=0x10)  # ptr = $1000
        assert cpu.memory[0xD3] == 0  # cursor didn't move

    def test_hello(self, io_syms):
        cpu = make_cpu(io_syms)
        # "HI" in PETSCII: H=$48, I=$49
        cpu.memory[0x1000] = 0x48
        cpu.memory[0x1001] = 0x49
        cpu.memory[0x1002] = 0x00
        jsr(cpu, io_syms.io_puts, a=0x00, x=0x10)
        assert cpu.memory[SCREEN + 0] == 0x08  # H
        assert cpu.memory[SCREEN + 1] == 0x09  # I
        assert cpu.memory[0xD3] == 2

    def test_digits(self, io_syms):
        cpu = make_cpu(io_syms)
        # "123" in PETSCII
        cpu.memory[0x1000] = 0x31
        cpu.memory[0x1001] = 0x32
        cpu.memory[0x1002] = 0x33
        cpu.memory[0x1003] = 0x00
        jsr(cpu, io_syms.io_puts, a=0x00, x=0x10)
        assert screen_str(cpu, 0, 0, 3) == '123'


class TestIoPuthex2:
    @pytest.mark.parametrize("val,expected", [
        (0x00, "00"),
        (0x0F, "0F"),
        (0x42, "42"),
        (0xA9, "A9"),
        (0xFF, "FF"),
    ])
    def test_hex2(self, io_syms, val, expected):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_puthex2, a=val)
        assert screen_str(cpu, 0, 0, 2) == expected
        assert cpu.memory[0xD3] == 2


class TestIoPuthex4:
    @pytest.mark.parametrize("val,expected", [
        (0x0000, "0000"),
        (0x1234, "1234"),
        (0xABCD, "ABCD"),
        (0xFFFF, "FFFF"),
    ])
    def test_hex4(self, io_syms, val, expected):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_puthex4, a=val & 0xFF, x=val >> 8)
        assert screen_str(cpu, 0, 0, 4) == expected
        assert cpu.memory[0xD3] == 4


class TestIoPutdec:
    @pytest.mark.parametrize("val,expected", [
        (0, "0"),
        (1, "1"),
        (9, "9"),
        (10, "10"),
        (99, "99"),
        (100, "100"),
        (255, "255"),
        (1000, "1000"),
        (9999, "9999"),
        (10000, "10000"),
        (65535, "65535"),
    ])
    def test_dec(self, io_syms, val, expected):
        cpu = make_cpu(io_syms)
        jsr(cpu, io_syms.io_putdec, a=val & 0xFF, x=val >> 8)
        result = screen_str(cpu, 0, 0, len(expected))
        assert result == expected
        assert cpu.memory[0xD3] == len(expected)


class TestIoClearEol:
    def test_from_col_0(self, io_syms):
        cpu = make_cpu(io_syms)
        # Fill screen row with 'X' first
        for i in range(COLS):
            cpu.memory[SCREEN + i] = 0x18  # 'X' screencode
        cpu.memory[0xD3] = 0
        jsr(cpu, io_syms.io_clear_eol)
        for i in range(COLS):
            assert cpu.memory[SCREEN + i] == 0x20

    def test_from_mid_row(self, io_syms):
        cpu = make_cpu(io_syms)
        for i in range(COLS):
            cpu.memory[SCREEN + i] = 0x18
        cpu.memory[0xD3] = 20
        jsr(cpu, io_syms.io_clear_eol)
        for i in range(20):
            assert cpu.memory[SCREEN + i] == 0x18  # untouched
        for i in range(20, COLS):
            assert cpu.memory[SCREEN + i] == 0x20  # cleared


class TestIoKbhit:
    def test_no_key(self, io_syms):
        cpu = make_cpu(io_syms)
        cpu.memory[0xC6] = 0
        jsr(cpu, io_syms.io_kbhit)
        assert cpu.a == 0

    def test_key_pending(self, io_syms):
        cpu = make_cpu(io_syms)
        cpu.memory[0xC6] = 3
        jsr(cpu, io_syms.io_kbhit)
        assert cpu.a == 3
