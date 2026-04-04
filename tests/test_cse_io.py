"""
test_cse_io.py — exhaustive tests for cse_io.s against the API spec.

Tests the guarantees defined in doc/cse_io_api.md:
- PETSCII → screen code conversion (all used characters)
- Screen code → PETSCII round-trip via read_line logic
- Cursor advancement and clamping
- io_puts string output
- io_puthex2/4 hex output and round-trip
- io_putdec decimal output
- io_clear_eol
- io_kbhit
- io_sync (KERNAL PLOT)
- _io_tmp preservation across io_putc (safe for io_puts)
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
IO_LST = BUILD / "cse_io.lst"

SCREEN = 0x0400
COLS   = 40
ROWS   = 25

# ── Build ────────────────────────────────────────────────────────────────────

def _needs_rebuild():
    if not IO_BIN.exists() or not IO_MAP.exists():
        return True
    mtime = IO_BIN.stat().st_mtime
    sources = [SRC / "cse_io.s", DEV / "cse_io_test_stub.s", DEV / "test.cfg"]
    return any(s.stat().st_mtime > mtime for s in sources)


def _build():
    BUILD.mkdir(exist_ok=True)
    subprocess.run(["ca65", "--cpu", "6502", "--listing", str(IO_LST),
                    str(SRC / "cse_io.s"), "-o", str(BUILD / "cse_io.o")], check=True)
    subprocess.run(["ca65", "--cpu", "6502", "--listing", str(BUILD / "cse_io_test_stub.lst"),
                    str(DEV / "cse_io_test_stub.s"), "-o", str(BUILD / "cse_io_test_stub.o")], check=True)
    subprocess.run(["ld65", "-C", str(DEV / "test.cfg"),
                    str(BUILD / "cse_io.o"), str(BUILD / "cse_io_test_stub.o"),
                    "-o", str(IO_BIN), "-m", str(IO_MAP)], check=True)


def _parse_segments():
    seg = {}
    in_seg = False
    for line in IO_MAP.read_text().splitlines():
        if line.startswith("Segment list"):
            in_seg = True; continue
        if in_seg:
            m = re.match(r"(\w+)\s+([0-9a-fA-F]+)\s+", line)
            if m: seg[m.group(1)] = int(m.group(2), 16)
    return seg


def _parse_listing_syms():
    offsets = {}
    for line in IO_LST.read_text().splitlines():
        m = re.match(r"^([0-9a-fA-F]+)r\s+\d+\s.*?\b(_?io_\w+):", line)
        if m: offsets[m.group(2)] = int(m.group(1), 16)
    return offsets


class IoSymbols:
    def __init__(self):
        if _needs_rebuild(): _build()
        seg = _parse_segments()
        ofs = _parse_listing_syms()
        code = seg.get("CODE", 0x0200)
        self.io_init      = code + ofs["io_init"]
        self.io_sync      = code + ofs["io_sync"]
        self.io_putc      = code + ofs["io_putc"]
        self.io_puts      = code + ofs["io_puts"]
        self.io_puthex4   = code + ofs["io_puthex4"]
        self.io_puthex2   = code + ofs["io_puthex2"]
        self.io_putdec    = code + ofs["io_putdec"]
        self.io_clear_eol = code + ofs["io_clear_eol"]
        self.io_kbhit     = code + ofs["io_kbhit"]
        self._io_tmp      = ofs.get("_io_tmp", 0)  # ZP address
        raw = IO_BIN.read_bytes()
        self._zp_start = seg.get("ZEROPAGE", 0)
        self._code_start = code
        self._zp_size = 0x100
        self._raw = raw

    def load_into(self, memory):
        memory[self._zp_start:self._zp_start + self._zp_size] = self._raw[:self._zp_size]
        code_blob = self._raw[self._zp_size:]
        memory[self._code_start:self._code_start + len(code_blob)] = code_blob


@pytest.fixture(scope="session")
def io(self=None):
    return IoSymbols()


# ── CPU helpers ──────────────────────────────────────────────────────────────

RTS_ADDR = 0x01F0
PLOT_STUB = 0xFE00

SCR_ROW_LO = [(SCREEN + r * COLS) & 0xFF for r in range(ROWS)]
SCR_ROW_HI = [(SCREEN + r * COLS) >> 8 for r in range(ROWS)]


def make_cpu(io):
    cpu = MPU()
    mem = bytearray(0x10000)
    io.load_into(mem)
    mem[RTS_ADDR] = 0x60

    # Fill screen with spaces
    for i in range(1000):
        mem[SCREEN + i] = 0x20

    # KERNAL PLOT stub
    tbl = PLOT_STUB + 0x30
    stub = [
        0xB0, 0x16,             # BCS +22 (@get)
        0x86, 0xD6, 0x84, 0xD3,
        0xBD, tbl & 0xFF, tbl >> 8,
        0x85, 0xD1, 0x85, 0xF3,
        0xBD, (tbl+25) & 0xFF, (tbl+25) >> 8,
        0x85, 0xD2, 0x18, 0x69, 0xD4, 0x85, 0xF4,
        0x60,                   # RTS (SET path, 23 bytes)
        0xA6, 0xD6, 0xA4, 0xD3, 0x60,  # @get: LDX $D6, LDY $D3, RTS
    ]
    for i, b in enumerate(stub):
        mem[PLOT_STUB + i] = b
    for r in range(ROWS):
        mem[tbl + r] = SCR_ROW_LO[r]
        mem[tbl + 25 + r] = SCR_ROW_HI[r]
    mem[0xFFF0] = 0x4C
    mem[0xFFF1] = PLOT_STUB & 0xFF
    mem[0xFFF2] = PLOT_STUB >> 8

    cpu.memory = mem
    cpu.memory[0xD3] = 0
    cpu.memory[0xD6] = 0

    # io_sync to initialize
    jsr(cpu, io.io_sync)
    return cpu


def jsr(cpu, addr, a=0, x=0, y=0, max_steps=10000):
    cpu.a = a; cpu.x = x; cpu.y = y
    cpu.pc = addr; cpu.sp = 0xFF
    cpu.memory[0x01FF] = (RTS_ADDR - 1) >> 8
    cpu.memory[0x01FE] = (RTS_ADDR - 1) & 0xFF
    cpu.sp = 0xFD
    steps = 0
    while cpu.pc != RTS_ADDR and steps < max_steps:
        cpu.step(); steps += 1
    assert steps < max_steps, f"JSR ${addr:04X} hung after {max_steps} steps"


def read_line_py(cpu, row):
    """Python implementation of read_line: screen code → PETSCII."""
    buf = []
    for col in range(COLS):
        sc = cpu.memory[SCREEN + row * COLS + col] & 0x7F
        if sc < 0x20:
            buf.append(sc + 0x40)
        else:
            buf.append(sc)
    while buf and buf[-1] == 0x20:
        buf.pop()
    return buf


# ═══════════════════════════════════════════════════════════════════════════════
# §1  PETSCII → Screen Code Conversion (io_putc)
# ═══════════════════════════════════════════════════════════════════════════════

class TestPetsciiToScreencode:
    """Verify io_putc produces the correct screen code for each PETSCII range."""

    # $20-$3F: identity (space, digits, punctuation)
    @pytest.mark.parametrize("petscii", list(range(0x20, 0x40)))
    def test_identity_range(self, io, petscii):
        cpu = make_cpu(io)
        jsr(cpu, io.io_putc, a=petscii)
        assert cpu.memory[SCREEN] == petscii

    # $40-$5F: subtract $40 (uppercase letters, @, [, etc.)
    @pytest.mark.parametrize("petscii", list(range(0x40, 0x60)))
    def test_uppercase_range(self, io, petscii):
        cpu = make_cpu(io)
        jsr(cpu, io.io_putc, a=petscii)
        assert cpu.memory[SCREEN] == petscii - 0x40

    # $60-$7F: subtract $20 (lowercase letters)
    @pytest.mark.parametrize("petscii", list(range(0x60, 0x80)))
    def test_lowercase_range(self, io, petscii):
        cpu = make_cpu(io)
        jsr(cpu, io.io_putc, a=petscii)
        assert cpu.memory[SCREEN] == petscii - 0x20

    # $C0-$DF: subtract $80 (shifted letters)
    @pytest.mark.parametrize("petscii", list(range(0xC0, 0xE0)))
    def test_shifted_range(self, io, petscii):
        cpu = make_cpu(io)
        jsr(cpu, io.io_putc, a=petscii)
        assert cpu.memory[SCREEN] == petscii - 0x80


# ═══════════════════════════════════════════════════════════════════════════════
# §2  Screen Code → PETSCII Round-trip
# ═══════════════════════════════════════════════════════════════════════════════

class TestRoundTrip:
    """io_putc(petscii) → screen RAM → read_line_py → expected PETSCII."""

    # Characters that must round-trip exactly (the CSE-critical set)
    @pytest.mark.parametrize("petscii", [
        # digits
        0x30, 0x31, 0x32, 0x33, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39,
        # punctuation used by REPL
        0x21, 0x22, 0x23, 0x24, 0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D,
        0x2E, 0x2F, 0x3A, 0x3B, 0x3D, 0x3F,
        # letters ($41-$5A in cc65 = unshifted = what keyboard produces)
        0x41, 0x42, 0x43, 0x44, 0x45, 0x46,  # a-f (hex)
        0x47, 0x48, 0x49, 0x4A, 0x4B, 0x4C, 0x4D,  # g-m
        0x4E, 0x4F, 0x50, 0x51, 0x52, 0x53, 0x54,  # n-t
        0x55, 0x56, 0x57, 0x58, 0x59, 0x5A,  # u-z
        # @
        0x40,
    ])
    def test_exact_roundtrip(self, io, petscii):
        cpu = make_cpu(io)
        jsr(cpu, io.io_putc, a=petscii)
        result = read_line_py(cpu, 0)
        assert len(result) >= 1
        assert result[0] == petscii, \
            f"${petscii:02X} → scr ${cpu.memory[SCREEN]:02X} → readback ${result[0]:02X}"

    # Lowercase/shifted letters round-trip to their uppercase equivalent
    @pytest.mark.parametrize("petscii,expected", [
        (0x61, 0x41),  # lowercase a → uppercase a
        (0x6D, 0x4D),  # lowercase m → uppercase m
        (0x7A, 0x5A),  # lowercase z → uppercase z
        (0xC1, 0x41),  # shifted A → uppercase a
        (0xCD, 0x4D),  # shifted M → uppercase m
        (0xDA, 0x5A),  # shifted Z → uppercase z
    ])
    def test_case_folding_roundtrip(self, io, petscii, expected):
        cpu = make_cpu(io)
        jsr(cpu, io.io_putc, a=petscii)
        result = read_line_py(cpu, 0)
        assert result[0] == expected


# ═══════════════════════════════════════════════════════════════════════════════
# §3  Cursor Behavior
# ═══════════════════════════════════════════════════════════════════════════════

class TestCursor:
    def test_advance_by_one(self, io):
        cpu = make_cpu(io)
        cpu.memory[0xD3] = 0
        jsr(cpu, io.io_putc, a=0x41)
        assert cpu.memory[0xD3] == 1

    def test_advance_from_mid(self, io):
        cpu = make_cpu(io)
        cpu.memory[0xD3] = 20
        jsr(cpu, io.io_putc, a=0x41)
        assert cpu.memory[0xD3] == 21

    def test_clamp_at_39(self, io):
        cpu = make_cpu(io)
        cpu.memory[0xD3] = 39
        jsr(cpu, io.io_putc, a=0x41)
        assert cpu.memory[0xD3] == 39  # clamped, not 40

    def test_row_unchanged(self, io):
        cpu = make_cpu(io)
        cpu.memory[0xD6] = 5
        jsr(cpu, io.io_sync)
        jsr(cpu, io.io_putc, a=0x41)
        assert cpu.memory[0xD6] == 5  # row unchanged

    def test_writes_to_correct_row(self, io):
        cpu = make_cpu(io)
        cpu.memory[0xD6] = 3
        cpu.memory[0xD3] = 0
        jsr(cpu, io.io_sync)
        jsr(cpu, io.io_putc, a=0x41)
        # Row 3 starts at SCREEN + 3*40 = $0400 + 120 = $0478
        assert cpu.memory[SCREEN + 3 * COLS] == 0x01  # 'A' screencode
        assert cpu.memory[SCREEN] == 0x20  # row 0 untouched

    def test_io_tmp_preserved(self, io):
        """io_putc must not clobber _io_tmp (io_puts needs it)."""
        cpu = make_cpu(io)
        tmp_addr = io._io_tmp
        cpu.memory[tmp_addr] = 0xAA
        cpu.memory[tmp_addr + 1] = 0xBB
        jsr(cpu, io.io_putc, a=0x41)
        assert cpu.memory[tmp_addr] == 0xAA
        assert cpu.memory[tmp_addr + 1] == 0xBB


# ═══════════════════════════════════════════════════════════════════════════════
# §4  io_puts
# ═══════════════════════════════════════════════════════════════════════════════

class TestIoPuts:
    def test_empty(self, io):
        cpu = make_cpu(io)
        cpu.memory[0x1000] = 0x00
        jsr(cpu, io.io_puts, a=0x00, x=0x10)
        assert cpu.memory[0xD3] == 0

    def test_short_string(self, io):
        cpu = make_cpu(io)
        # "HI" = $48, $49
        cpu.memory[0x1000] = 0x48
        cpu.memory[0x1001] = 0x49
        cpu.memory[0x1002] = 0x00
        jsr(cpu, io.io_puts, a=0x00, x=0x10)
        assert cpu.memory[SCREEN] == 0x08      # H
        assert cpu.memory[SCREEN + 1] == 0x09  # I
        assert cpu.memory[0xD3] == 2

    def test_roundtrip(self, io):
        cpu = make_cpu(io)
        # "1000:" in PETSCII
        s = [0x31, 0x30, 0x30, 0x30, 0x3A, 0x00]
        for i, b in enumerate(s):
            cpu.memory[0x1000 + i] = b
        jsr(cpu, io.io_puts, a=0x00, x=0x10)
        result = read_line_py(cpu, 0)
        assert result == [0x31, 0x30, 0x30, 0x30, 0x3A]


# ═══════════════════════════════════════════════════════════════════════════════
# §5  io_puthex2 / io_puthex4
# ═══════════════════════════════════════════════════════════════════════════════

class TestHex:
    @pytest.mark.parametrize("val,scr0,scr1", [
        (0x00, 0x30, 0x30),  # "00"
        (0x09, 0x30, 0x39),  # "09"
        (0x0A, 0x30, 0x01),  # "0A" (hex_tab[10] = $01)
        (0x0F, 0x30, 0x06),  # "0F"
        (0x10, 0x31, 0x30),  # "10"
        (0x42, 0x34, 0x32),  # "42"
        (0xA9, 0x01, 0x39),  # "A9"
        (0xFF, 0x06, 0x06),  # "FF"
    ])
    def test_puthex2_screencodes(self, io, val, scr0, scr1):
        cpu = make_cpu(io)
        jsr(cpu, io.io_puthex2, a=val)
        assert cpu.memory[SCREEN] == scr0
        assert cpu.memory[SCREEN + 1] == scr1
        assert cpu.memory[0xD3] == 2

    @pytest.mark.parametrize("val,expected_petscii", [
        (0x00, [0x30, 0x30]),
        (0x0F, [0x30, 0x46]),
        (0x42, [0x34, 0x32]),
        (0xA9, [0x41, 0x39]),
        (0xFF, [0x46, 0x46]),
    ])
    def test_puthex2_roundtrip(self, io, val, expected_petscii):
        cpu = make_cpu(io)
        jsr(cpu, io.io_puthex2, a=val)
        result = read_line_py(cpu, 0)
        assert result[:2] == expected_petscii

    @pytest.mark.parametrize("val,expected_petscii", [
        (0x0000, [0x30, 0x30, 0x30, 0x30]),
        (0x1000, [0x31, 0x30, 0x30, 0x30]),
        (0x1234, [0x31, 0x32, 0x33, 0x34]),
        (0xABCD, [0x41, 0x42, 0x43, 0x44]),
        (0xFFFF, [0x46, 0x46, 0x46, 0x46]),
    ])
    def test_puthex4_roundtrip(self, io, val, expected_petscii):
        cpu = make_cpu(io)
        jsr(cpu, io.io_puthex4, a=val & 0xFF, x=val >> 8)
        result = read_line_py(cpu, 0)
        assert result[:4] == expected_petscii
        assert cpu.memory[0xD3] == 4


# ═══════════════════════════════════════════════════════════════════════════════
# §6  io_putdec
# ═══════════════════════════════════════════════════════════════════════════════

class TestDec:
    @pytest.mark.parametrize("val,expected_str", [
        (0, "0"), (1, "1"), (9, "9"), (10, "10"), (99, "99"),
        (100, "100"), (255, "255"), (999, "999"), (1000, "1000"),
        (9999, "9999"), (10000, "10000"), (65535, "65535"),
    ])
    def test_putdec(self, io, val, expected_str):
        cpu = make_cpu(io)
        jsr(cpu, io.io_putdec, a=val & 0xFF, x=val >> 8)
        # Read screen codes and convert digits to ASCII for comparison
        result = ""
        for i in range(len(expected_str)):
            sc = cpu.memory[SCREEN + i]
            result += chr(sc) if 0x30 <= sc <= 0x39 else f"[{sc:02X}]"
        assert result == expected_str
        assert cpu.memory[0xD3] == len(expected_str)


# ═══════════════════════════════════════════════════════════════════════════════
# §7  io_clear_eol
# ═══════════════════════════════════════════════════════════════════════════════

class TestClearEol:
    def test_from_col0(self, io):
        cpu = make_cpu(io)
        for i in range(COLS): cpu.memory[SCREEN + i] = 0x01
        cpu.memory[0xD3] = 0
        jsr(cpu, io.io_clear_eol)
        for i in range(COLS):
            assert cpu.memory[SCREEN + i] == 0x20

    def test_from_mid(self, io):
        cpu = make_cpu(io)
        for i in range(COLS): cpu.memory[SCREEN + i] = 0x01
        cpu.memory[0xD3] = 20
        jsr(cpu, io.io_clear_eol)
        for i in range(20):
            assert cpu.memory[SCREEN + i] == 0x01
        for i in range(20, COLS):
            assert cpu.memory[SCREEN + i] == 0x20

    def test_io_cx_unchanged(self, io):
        cpu = make_cpu(io)
        cpu.memory[0xD3] = 15
        jsr(cpu, io.io_clear_eol)
        assert cpu.memory[0xD3] == 15


# ═══════════════════════════════════════════════════════════════════════════════
# §8  io_kbhit
# ═══════════════════════════════════════════════════════════════════════════════

class TestKbhit:
    def test_empty(self, io):
        cpu = make_cpu(io)
        cpu.memory[0xC6] = 0
        jsr(cpu, io.io_kbhit)
        assert cpu.a == 0

    def test_pending(self, io):
        cpu = make_cpu(io)
        cpu.memory[0xC6] = 3
        jsr(cpu, io.io_kbhit)
        assert cpu.a == 3


# ═══════════════════════════════════════════════════════════════════════════════
# §9  io_sync
# ═══════════════════════════════════════════════════════════════════════════════

class TestSync:
    @pytest.mark.parametrize("row", [0, 1, 12, 24])
    def test_d1d2(self, io, row):
        cpu = make_cpu(io)
        cpu.memory[0xD6] = row
        jsr(cpu, io.io_sync)
        expected_lo = (SCREEN + row * COLS) & 0xFF
        expected_hi = (SCREEN + row * COLS) >> 8
        assert cpu.memory[0xD1] == expected_lo
        assert cpu.memory[0xD2] == expected_hi

    @pytest.mark.parametrize("row", [0, 1, 12, 24])
    def test_f3f4(self, io, row):
        cpu = make_cpu(io)
        cpu.memory[0xD6] = row
        jsr(cpu, io.io_sync)
        expected_lo = (SCREEN + row * COLS) & 0xFF
        expected_hi = ((SCREEN + row * COLS) >> 8) + 0xD4
        assert cpu.memory[0xF3] == expected_lo
        assert cpu.memory[0xF4] == expected_hi


# ═══════════════════════════════════════════════════════════════════════════════
# §10  Full REPL Command Simulation
# ═══════════════════════════════════════════════════════════════════════════════

class TestReplSimulation:
    """Simulate the exact sequence: show_prompt + user types command + read_line."""

    def test_prompt_1000_colon(self, io):
        """io_puthex4(0x1000) + io_putc(':') → read_line gives '1000:'"""
        cpu = make_cpu(io)
        jsr(cpu, io.io_puthex4, a=0x00, x=0x10)
        jsr(cpu, io.io_putc, a=0x3A)
        result = read_line_py(cpu, 0)
        assert result == [0x31, 0x30, 0x30, 0x30, 0x3A]

    def test_command_1000_m(self, io):
        """Prompt + 'm' → read_line gives '1000:m'"""
        cpu = make_cpu(io)
        jsr(cpu, io.io_puthex4, a=0x00, x=0x10)
        jsr(cpu, io.io_putc, a=0x3A)
        jsr(cpu, io.io_putc, a=0x4D)  # 'm'
        result = read_line_py(cpu, 0)
        assert result == [0x31, 0x30, 0x30, 0x30, 0x3A, 0x4D]

    def test_command_c000_d(self, io):
        """Prompt 'c000:d'"""
        cpu = make_cpu(io)
        jsr(cpu, io.io_puthex4, a=0x00, x=0xC0)
        jsr(cpu, io.io_putc, a=0x3A)
        jsr(cpu, io.io_putc, a=0x44)  # 'd'
        result = read_line_py(cpu, 0)
        assert result == [0x43, 0x30, 0x30, 0x30, 0x3A, 0x44]

    def test_command_with_args(self, io):
        """'1000:. lda #$00' simulation"""
        cpu = make_cpu(io)
        jsr(cpu, io.io_puthex4, a=0x00, x=0x10)
        jsr(cpu, io.io_putc, a=0x3A)   # ':'
        jsr(cpu, io.io_putc, a=0x2E)   # '.'
        jsr(cpu, io.io_putc, a=0x20)   # ' '
        for ch in [0x4C, 0x44, 0x41]:  # 'lda'
            jsr(cpu, io.io_putc, a=ch)
        result = read_line_py(cpu, 0)
        assert result == [0x31, 0x30, 0x30, 0x30, 0x3A, 0x2E, 0x20, 0x4C, 0x44, 0x41]

    def test_is_hex_on_readback(self, io):
        """Verify that hex digits from io_puthex4 pass is_hex after readback."""
        cpu = make_cpu(io)
        jsr(cpu, io.io_puthex4, a=0xCD, x=0xAB)  # "abcd"
        result = read_line_py(cpu, 0)
        for b in result[:4]:
            assert (0x30 <= b <= 0x39) or (0x41 <= b <= 0x46), \
                f"readback byte ${b:02X} would fail is_hex"


# ═══════════════════════════════════════════════════════════════════════════════
# §11  KERNAL Coexistence Guarantees
# ═══════════════════════════════════════════════════════════════════════════════

class TestKernalCoexistence:
    """Verify cse_io maintains KERNAL state consistency.

    The KERNAL IRQ at $EA31 reads $D1/$D2/$D3/$D6/$F3/$F4 during its
    cursor/screen editor code.  Even with cursor disabled ($CC=1), we
    must not leave these in an invalid state.
    """

    def test_d3_valid_after_putc(self, io):
        """$D3 must be 0–39 after io_putc."""
        cpu = make_cpu(io)
        for col in range(COLS):
            cpu.memory[0xD3] = col
            jsr(cpu, io.io_putc, a=0x41)
            assert 0 <= cpu.memory[0xD3] <= 39

    def test_d6_unchanged_by_putc(self, io):
        """io_putc must never modify $D6."""
        cpu = make_cpu(io)
        for row in [0, 12, 24]:
            cpu.memory[0xD6] = row
            cpu.memory[0xD3] = 0
            jsr(cpu, io.io_sync)
            jsr(cpu, io.io_putc, a=0x41)
            assert cpu.memory[0xD6] == row

    def test_d6_unchanged_by_puts(self, io):
        """io_puts must never modify $D6."""
        cpu = make_cpu(io)
        cpu.memory[0xD6] = 10
        cpu.memory[0xD3] = 0
        jsr(cpu, io.io_sync)
        cpu.memory[0x1000] = 0x48; cpu.memory[0x1001] = 0x49; cpu.memory[0x1002] = 0
        jsr(cpu, io.io_puts, a=0x00, x=0x10)
        assert cpu.memory[0xD6] == 10

    def test_d6_unchanged_by_puthex(self, io):
        """io_puthex4 must never modify $D6."""
        cpu = make_cpu(io)
        cpu.memory[0xD6] = 15
        jsr(cpu, io.io_sync)
        jsr(cpu, io.io_puthex4, a=0x34, x=0x12)
        assert cpu.memory[0xD6] == 15

    def test_d6_unchanged_by_putdec(self, io):
        """io_putdec must never modify $D6."""
        cpu = make_cpu(io)
        cpu.memory[0xD6] = 20
        jsr(cpu, io.io_sync)
        jsr(cpu, io.io_putdec, a=0xFF, x=0xFF)
        assert cpu.memory[0xD6] == 20

    def test_sync_after_row_change(self, io):
        """After changing $D6 + io_sync, $D1/$D2/$F3/$F4 must be consistent."""
        cpu = make_cpu(io)
        for row in range(ROWS):
            cpu.memory[0xD6] = row
            jsr(cpu, io.io_sync)
            exp_lo = (SCREEN + row * COLS) & 0xFF
            exp_hi = (SCREEN + row * COLS) >> 8
            assert cpu.memory[0xD1] == exp_lo, f"row {row}: $D1"
            assert cpu.memory[0xD2] == exp_hi, f"row {row}: $D2"
            assert cpu.memory[0xF3] == exp_lo, f"row {row}: $F3"
            assert cpu.memory[0xF4] == exp_hi + 0xD4, f"row {row}: $F4"

    def test_output_at_every_row(self, io):
        """io_putc must write to the correct screen address for every row."""
        cpu = make_cpu(io)
        for row in range(ROWS):
            cpu.memory[0xD6] = row
            cpu.memory[0xD3] = 0
            jsr(cpu, io.io_sync)
            jsr(cpu, io.io_putc, a=0x41)  # 'a' → screen $01
            addr = SCREEN + row * COLS
            assert cpu.memory[addr] == 0x01, \
                f"row {row}: expected $01 at ${addr:04X}, got ${cpu.memory[addr]:02X}"
            # verify other rows untouched
            for other_row in [0, 12, 24]:
                if other_row != row:
                    other_addr = SCREEN + other_row * COLS
                    assert cpu.memory[other_addr] == 0x20, \
                        f"row {row} write leaked to row {other_row}"
            # reset for next iteration
            cpu.memory[addr] = 0x20

    def test_io_init_sets_cc(self, io):
        """io_init must set $CC=1 (KERNAL cursor disabled)."""
        cpu = make_cpu(io)
        cpu.memory[0xCC] = 0  # pretend cursor enabled
        jsr(cpu, io.io_init)
        assert cpu.memory[0xCC] == 1

    def test_d3_equals_io_cx_after_sync(self, io):
        """After io_sync, $D3 must equal io_cx (they're the same location)."""
        cpu = make_cpu(io)
        cpu.memory[0xD3] = 15
        cpu.memory[0xD6] = 10
        jsr(cpu, io.io_sync)
        # KERNAL PLOT sets $D3 = Y, and we pass Y = $D3, so it's unchanged
        assert cpu.memory[0xD3] == 15
