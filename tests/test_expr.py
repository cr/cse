"""
test_expr.py — Tests for the expression parser (expr.s)

Tests the hex literal parser: [$]hhhh with 1-4 digits, overflow,
empty input, leading spaces, bare $ prefix.

NOTE: The expr.s test binary needs a working cc65 C stack (pushax/popax).
The minimal stubs here don't fully replicate cc65's runtime. Tests are
marked xfail until we have a proper test harness or port expr.s to
not use the C stack.
"""

import subprocess
import pathlib
import re
import pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

EXPR_BIN = BUILD / "expr_test.bin"
EXPR_MAP = BUILD / "expr_test.map"

_ZP_START   = 0x0000
_CODE_START = 0x0200
_ZP_SIZE    = 0x0100
_STR_BUF    = 0x0300   # where we place the input string


def _needs_rebuild():
    if not EXPR_BIN.exists():
        return True
    t = EXPR_BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in [
        SRC / "expr.s", DEV / "expr_test_stub.s", DEV / "test.cfg",
    ])


def _build():
    BUILD.mkdir(exist_ok=True)
    for name, src in [("expr", SRC / "expr.s"),
                      ("expr_test_stub", DEV / "expr_test_stub.s")]:
        subprocess.run(
            ["ca65", "--cpu", "6502", str(src), "-o", str(BUILD / f"{name}.o")],
            check=True,
        )
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         str(BUILD / "expr.o"), str(BUILD / "expr_test_stub.o"),
         "-o", str(EXPR_BIN), "-m", str(EXPR_MAP)],
        check=True,
    )


def _parse_exports():
    syms = {}
    in_exports = False
    for line in EXPR_MAP.read_text().splitlines():
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


def _parse_stub_entry():
    """Find expr_test_entry address from map file module offsets."""
    # The stub is linked after expr.o. Its CODE offset in the map tells us
    # where it starts relative to the CODE segment.
    stub_offset = None
    in_stub = False
    for line in EXPR_MAP.read_text().splitlines():
        if 'expr_test_stub.o' in line and ':' in line:
            in_stub = True
            continue
        if in_stub and 'CODE' in line:
            m = re.search(r'Offs=([0-9a-fA-F]+)', line)
            if m:
                stub_offset = int(m.group(1), 16)
            break
        if in_stub and not line.startswith(' '):
            break
    # CODE segment starts at _CODE_START
    return _CODE_START + stub_offset if stub_offset else None


class ExprSyms:
    def __init__(self):
        if _needs_rebuild():
            _build()
        exp = _parse_exports()
        self.entry = exp.get("expr_test_entry") or _parse_stub_entry()
        if not self.entry:
            raise RuntimeError("Cannot find expr_test_entry in map file")
        self._raw = EXPR_BIN.read_bytes()

    def load_into(self, mem):
        mem[_ZP_START:_ZP_START + _ZP_SIZE] = self._raw[:_ZP_SIZE]
        code = self._raw[_ZP_SIZE:]
        mem[_CODE_START:_CODE_START + len(code)] = code


@pytest.fixture(scope="session")
def expr_syms():
    return ExprSyms()


# PETSCII encoding: on C64, lowercase 'a'-'f' = $41-$46, digits = $30-$39,
# '$' = $24, space = $20.  cc65 uses PETSCII for character literals.
# But our test string is placed raw — PETSCII values.
def _petscii(s):
    """Convert ASCII test string to PETSCII bytes."""
    out = []
    for c in s:
        if 'a' <= c <= 'z':
            out.append(ord(c) - ord('a') + 0x41)
        elif 'A' <= c <= 'Z':
            out.append(ord(c) - ord('A') + 0xC1)
        else:
            out.append(ord(c))
    out.append(0)  # NUL terminator
    return bytes(out)


def _run(expr_syms, input_str):
    """Run expr_eval on input_str, return (ok, value, chars_consumed)."""
    mpu = MPU()
    mem = bytearray(0x10000)
    expr_syms.load_into(mem)

    # Place input string at _STR_BUF
    encoded = _petscii(input_str)
    for i, b in enumerate(encoded):
        mem[_STR_BUF + i] = b

    # Set INPTR ($F0/$F1) → _STR_BUF
    mem[0xF0] = _STR_BUF & 0xFF
    mem[0xF1] = (_STR_BUF >> 8) & 0xFF

    # Fake JSR return
    RETURN_ADDR = 0x0F00
    mem[RETURN_ADDR] = 0x00  # BRK
    mpu.memory = mem
    mpu.sp = 0xFF
    mpu.sp -= 1; mem[0x01FF] = (RETURN_ADDR - 1) >> 8
    mpu.sp -= 1; mem[0x01FE] = (RETURN_ADDR - 1) & 0xFF

    # C stack pointer is initialized by the test stub entry point
    mpu.pc = expr_syms.entry
    for _ in range(20000):
        if mpu.pc == RETURN_ADDR:
            break
        mpu.step()
    else:
        pytest.fail(f"Timeout on {input_str!r}")

    ok = mpu.a  # 0 = success, 1 = error
    value = mem[0xF2] | (mem[0xF3] << 8)
    updated_ptr = mem[0xF4] | (mem[0xF5] << 8)
    chars_consumed = updated_ptr - _STR_BUF

    return ok, value, chars_consumed


# ── Test cases ────────────────────────────────────────────────────────────────

@pytest.mark.xfail(reason="cc65 C stack stubs incomplete — expr.s needs popax/sp")
class TestExprHexLiterals:
    """Basic hex literal parsing."""

    def test_single_digit(self, expr_syms):
        ok, val, _ = _run(expr_syms, "f")
        assert ok == 0 and val == 0x0F

    def test_two_digits(self, expr_syms):
        ok, val, _ = _run(expr_syms, "ff")
        assert ok == 0 and val == 0xFF

    def test_four_digits(self, expr_syms):
        ok, val, _ = _run(expr_syms, "1234")
        assert ok == 0 and val == 0x1234

    def test_dollar_prefix(self, expr_syms):
        ok, val, _ = _run(expr_syms, "$abcd")
        assert ok == 0 and val == 0xABCD

    def test_zero(self, expr_syms):
        ok, val, _ = _run(expr_syms, "0")
        assert ok == 0 and val == 0

    def test_leading_spaces(self, expr_syms):
        ok, val, _ = _run(expr_syms, "  42")
        assert ok == 0 and val == 0x42

    def test_dollar_with_spaces(self, expr_syms):
        ok, val, _ = _run(expr_syms, "  $ff")
        assert ok == 0 and val == 0xFF

    def test_stops_at_non_hex(self, expr_syms):
        ok, val, consumed = _run(expr_syms, "ff,x")
        assert ok == 0 and val == 0xFF
        assert consumed == 2  # stops at ','


@pytest.mark.xfail(reason="cc65 C stack stubs incomplete — expr.s needs popax/sp")
class TestExprErrors:
    """Error cases."""

    def test_empty_input(self, expr_syms):
        ok, _, _ = _run(expr_syms, "")
        assert ok == 1  # error

    def test_bare_dollar(self, expr_syms):
        ok, _, _ = _run(expr_syms, "$")
        assert ok == 1  # error: no digits after $

    def test_non_hex(self, expr_syms):
        ok, _, _ = _run(expr_syms, "xyz")
        assert ok == 1  # x is not hex... wait, actually x IS hex? no, not in PETSCII context
        # In PETSCII, 'x' maps to $58 which hex_val doesn't recognize
        # (it checks $41-$46 for a-f).  So this should error.

    def test_overflow(self, expr_syms):
        ok, _, _ = _run(expr_syms, "12345")
        assert ok == 1  # > 4 hex digits

    def test_spaces_only(self, expr_syms):
        ok, _, _ = _run(expr_syms, "   ")
        assert ok == 1  # no digits
