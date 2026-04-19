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

import subprocess
import pathlib
import pytest
from py65.devices.mpu6502 import MPU
from conftest import SymbolTable

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

IO_BIN = BUILD / "cse_io_test.bin"
IO_MAP = BUILD / "cse_io_test.map"
IO_LBL = BUILD / "cse_io_test.lbl"

SCREEN = 0x0400
COLS   = 40
ROWS   = 25

_ZP_SIZE    = 0x100
_CODE_START = 0x4000

# ── Build ────────────────────────────────────────────────────────────────────

_SOURCES = [SRC / "zp.s", SRC / "strings.s", SRC / "cse_io.s", DEV / "cse_io_test_stub.s"]

def _needs_rebuild():
    if not IO_BIN.exists() or not IO_LBL.exists():
        return True
    mtime = IO_BIN.stat().st_mtime
    return any(s.stat().st_mtime > mtime for s in _SOURCES + [DEV / "test.cfg"])


def _build():
    BUILD.mkdir(exist_ok=True)
    objs = []
    for src in _SOURCES:
        obj = BUILD / f"{src.stem}_io.o"
        subprocess.run(["ca65", "-g", "--cpu", "6502",
                        "-I", str(BUILD),
                        str(src), "-o", str(obj)], check=True)
        objs.append(str(obj))
    subprocess.run(["ld65", "-C", str(DEV / "test.cfg"),
                    *objs,
                    "-o", str(IO_BIN), "-m", str(IO_MAP),
                    "-Ln", str(IO_LBL)], check=True)


class IoSymbols:
    def __init__(self):
        if _needs_rebuild(): _build()
        s = SymbolTable(IO_LBL)
        self.io_init      = s["io_init"]
        self.io_sync      = s["io_sync"]
        self.io_putc      = s["io_putc"]
        self.pet_to_scr   = s["pet_to_scr"]
        self.scr_to_pet   = s["scr_to_pet"]
        self.io_puts      = s["io_puts"]
        self.io_puthex4   = s["io_puthex4"]
        self.io_puthex2   = s["io_puthex2"]
        self.io_putdec    = s["io_putdec"]
        self.io_clear_eol = s["io_clear_eol"]
        self.io_kbhit     = s["io_kbhit"]
        self._io_tmp      = s.get("_io_tmp", 0)
        self._raw = IO_BIN.read_bytes()

    def load_into(self, memory):
        memory[0:_ZP_SIZE] = self._raw[:_ZP_SIZE]
        code_blob = self._raw[_ZP_SIZE:]
        memory[_CODE_START:_CODE_START + len(code_blob)] = code_blob


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
# §1  PETSCII ↔ Screen Code Codec (pet_to_scr, scr_to_pet)
# ═══════════════════════════════════════════════════════════════════════════════

# Reference tables — the 32-byte-chunk mapping from cse_io.md.
# One entry per byte value; generated from the documented rules.

def _build_pet_to_scr():
    """Build 256-byte PETSCII → screencode reference table."""
    t = bytearray(256)
    for p in range(256):
        if   p < 0x20: t[p] = p | 0x80        # $00-$1F → $80-$9F
        elif p < 0x40: t[p] = p                # $20-$3F → identity
        elif p < 0x60: t[p] = p - 0x40         # $40-$5F → $00-$1F
        elif p < 0x80: t[p] = p - 0x20         # $60-$7F → $40-$5F
        elif p < 0xA0: t[p] = p                # $80-$9F → identity
        elif p < 0xC0: t[p] = p - 0x40         # $A0-$BF → $60-$7F
        else:          t[p] = p - 0x80         # $C0-$FF → $40-$7F
    return bytes(t)

def _build_scr_to_pet():
    """Build 128-byte screencode → PETSCII reference table."""
    t = bytearray(128)
    for sc in range(128):
        if   sc < 0x20: t[sc] = sc + 0x40     # $00-$1F → $40-$5F (lowercase)
        elif sc < 0x40: t[sc] = sc             # $20-$3F → identity (digits/punct)
        elif sc < 0x60: t[sc] = sc | 0x80      # $40-$5F → $C0-$DF (uppercase)
        else:           t[sc] = sc             # $60-$7F → identity (graphics)
    return bytes(t)

PET_TO_SCR = _build_pet_to_scr()
SCR_TO_PET = _build_scr_to_pet()


class TestPetToScr:
    """Verify pet_to_scr against the reference table for all 256 values."""

    def test_full_range(self, io):
        cpu = make_cpu(io)
        errors = []
        for val in range(256):
            cpu2 = make_cpu(io)
            jsr(cpu2, io.pet_to_scr, a=val)
            if cpu2.a != PET_TO_SCR[val]:
                errors.append(f"${val:02X}: got ${cpu2.a:02X}, expected ${PET_TO_SCR[val]:02X}")
        assert not errors, f"pet_to_scr failures:\n" + "\n".join(errors)


class TestScrToPet:
    """Verify scr_to_pet against the reference table for all 128 values."""

    def test_full_range(self, io):
        errors = []
        for val in range(128):
            cpu = make_cpu(io)
            jsr(cpu, io.scr_to_pet, a=val)
            if cpu.a != SCR_TO_PET[val]:
                errors.append(f"${val:02X}: got ${cpu.a:02X}, expected ${SCR_TO_PET[val]:02X}")
        assert not errors, f"scr_to_pet failures:\n" + "\n".join(errors)


class TestCodecRoundTrip:
    """Verify lossy round-trip: pet_to_scr → strip bit 7 → scr_to_pet."""

    def test_full_range(self, io):
        errors = []
        for val in range(256):
            cpu = make_cpu(io)
            jsr(cpu, io.pet_to_scr, a=val)
            sc = cpu.a & 0x7F
            jsr(cpu, io.scr_to_pet, a=sc)
            expected = SCR_TO_PET[PET_TO_SCR[val] & 0x7F]
            if cpu.a != expected:
                errors.append(f"${val:02X}: scr=${sc:02X}, got ${cpu.a:02X}, expected ${expected:02X}")
        assert not errors, f"round-trip failures:\n" + "\n".join(errors)


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
