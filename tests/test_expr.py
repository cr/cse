"""
test_expr.py — Exhaustive tests for the expression parser (expr.s)

Interface (ZP-based, no C stack):
    expr_ptr ($F0/$F1):  in: pointer to PETSCII input string
                         out: advanced past consumed input
    expr_val ($F2/$F3):  out: 16-bit result (valid on success)
    asm_pc   ($F4/$F5):  in: current PC (for '*' operator)
    al_cpu   ($F6):      in: CPU mode (for future use)

    _expr_eval:  entry point
                 Returns: C=0 success, C=1 error
                 On error: A = error code

Error codes:
    ERR_NONE       = 0   success
    ERR_EXPECTED   = 1   expected value (empty input, bare operator)
    ERR_OVERFLOW   = 2   value too large
    ERR_PAREN      = 3   mismatched parentheses
    ERR_UNDEFINED  = 4   undefined symbol (only in pass 2)

Symbol table fixture:
    Before running expression tests that use labels, we preload:
      zero   = $0000
      one    = $0001
      page   = $0100
      screen = $0400
      start  = $0800
      table  = $C000
      top    = $FFFF
      lo_val = $0042
      port   = $D020
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

# ZP addresses — read from map file at fixture init time
# These are set dynamically by ExprFixture.__init__
EXPR_PTR = None
EXPR_VAL = None
ASM_PC   = None

# Data placement (above CODE+BSS — see py65 test harness rules)
_STR_BUF    = 0x0A00
_NAME_BUF   = 0x0B00   # for symbol names
_RETURN     = 0x0F00

# Error codes
ERR_NONE      = 0
ERR_EXPECTED  = 1
ERR_OVERFLOW  = 2
ERR_PAREN     = 3
ERR_UNDEFINED = 4

# Symbol fixtures
SYMBOLS = {
    "zero":   0x0000,
    "one":    0x0001,
    "page":   0x0100,
    "screen": 0x0400,
    "start":  0x0800,
    "table":  0xC000,
    "top":    0xFFFF,
    "lo_val": 0x0042,
    "port":   0xD020,
}


def _needs_rebuild():
    if not EXPR_BIN.exists():
        return True
    t = EXPR_BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in [
        SRC / "expr.s", SRC / "symtab.s", DEV / "expr_test_stub.s",
        DEV / "test.cfg",
    ])


def _build():
    BUILD.mkdir(exist_ok=True)
    modules = [
        ("expr",           SRC / "expr.s"),
        ("symtab",         SRC / "symtab.s"),
        ("expr_test_stub", DEV / "expr_test_stub.s"),
    ]
    for name, src in modules:
        subprocess.run(
            ["ca65", "--cpu", "6502", "-t", "c64", str(src), "-o", str(BUILD / f"{name}.o")],
            check=True,
        )
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         str(BUILD / "expr.o"), str(BUILD / "symtab.o"),
         str(BUILD / "expr_test_stub.o"),
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
            # Format: "name  HHHHHH RLA/RLZ" — 6-digit hex followed by type code
            for m in re.finditer(r'(\w+)\s+([0-9a-fA-F]{6})\s+RL', line):
                syms[m.group(1)] = int(m.group(2), 16)
            if line.strip() == "":
                break
    return syms


def _parse_stub_offset():
    """Find the CODE offset of expr_test_stub.o in the map file."""
    in_stub = False
    for line in EXPR_MAP.read_text().splitlines():
        if 'expr_test_stub.o:' in line:
            in_stub = True
            continue
        if in_stub and 'CODE' in line:
            m = re.search(r'Offs=([0-9a-fA-F]+)', line)
            if m:
                return int(m.group(1), 16)
            break
        if in_stub and not line.startswith(' '):
            break
    return None


class ExprFixture:
    def __init__(self):
        if _needs_rebuild():
            _build()
        self.exports = _parse_exports()
        self._raw = EXPR_BIN.read_bytes()
        # Compute stub entry points from CODE offset
        stub_off = _parse_stub_offset()
        if stub_off is None:
            raise RuntimeError("Cannot find expr_test_stub CODE offset in map")
        base = 0x0200 + stub_off
        self.eval_entry = base        # JSR _expr_eval / RTS
        self.define_entry = base + 4  # JSR _sym_define / RTS
        self.clear_entry = base + 8   # JSR _sym_clear / RTS
        # ZP addresses from linker
        self.expr_ptr = self.exports["expr_ptr"]
        self.expr_val = self.exports["expr_val"]
        self.asm_pc = self.exports["al_pc"]
        self.sym_name = self.exports["sym_name"]
        self.sym_val = self.exports["sym_val"]

    def load_into(self, mem):
        mem[0:0x100] = self._raw[:0x100]
        code = self._raw[0x100:]
        mem[0x200:0x200 + len(code)] = code


@pytest.fixture(scope="session")
def expr():
    return ExprFixture()


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
    out.append(0)
    return bytes(out)


def _call(mpu, mem, entry):
    """Call a subroutine and wait for return."""
    mem[_RETURN] = 0x00
    mpu.sp = 0xFF
    mpu.sp -= 1; mem[0x01FF] = (_RETURN - 1) >> 8
    mpu.sp -= 1; mem[0x01FE] = (_RETURN - 1) & 0xFF
    mpu.pc = entry
    for _ in range(100000):
        if mpu.pc == _RETURN:
            return
        mpu.step()
    raise RuntimeError(f"Timeout at ${mpu.pc:04X}")


def _setup(expr_fix):
    """Create fresh CPU+mem with binary loaded."""
    mpu = MPU()
    mem = bytearray(0x10000)
    expr_fix.load_into(mem)
    mpu.memory = mem
    return mpu, mem


def _define_symbols(expr_fix, mpu, mem):
    """Populate symbol table with test fixtures."""
    _call(mpu, mem, expr_fix.clear_entry)
    name_addr = _NAME_BUF
    sn = expr_fix.sym_name
    sv = expr_fix.sym_val
    for name, value in SYMBOLS.items():
        encoded = _petscii(name)
        for i, b in enumerate(encoded):
            mem[name_addr + i] = b
        mem[sn] = name_addr & 0xFF
        mem[sn + 1] = (name_addr >> 8) & 0xFF
        mem[sv] = value & 0xFF
        mem[sv + 1] = (value >> 8) & 0xFF
        _call(mpu, mem, expr_fix.define_entry)
        name_addr += len(encoded)


def _eval(expr_fix, mpu, mem, input_str, pc=0x1000):
    """Evaluate expression. Returns (ok: bool, value: int, consumed: int, err_code: int)."""
    ep = expr_fix.expr_ptr
    ev = expr_fix.expr_val
    ap = expr_fix.asm_pc

    encoded = _petscii(input_str)
    for i, b in enumerate(encoded):
        mem[_STR_BUF + i] = b
    # Set expr_ptr
    mem[ep] = _STR_BUF & 0xFF
    mem[ep + 1] = (_STR_BUF >> 8) & 0xFF
    # Set asm_pc
    mem[ap] = pc & 0xFF
    mem[ap + 1] = (pc >> 8) & 0xFF

    _call(mpu, mem, expr_fix.eval_entry)

    carry = mpu.p & 1
    ok = carry == 0
    value = mem[ev] | (mem[ev + 1] << 8)
    updated_ptr = mem[ep] | (mem[ep + 1] << 8)
    consumed = updated_ptr - _STR_BUF
    err_code = mpu.a if not ok else 0
    return ok, value, consumed, err_code


# ═══════════════════════════════════════════════════════════════════
# POSITIVE TESTS — expressions that must parse successfully
# ═══════════════════════════════════════════════════════════════════

class TestHexLiterals:
    """Hex values: $hhhh or bare hhhh."""

    @pytest.mark.parametrize("input_str,expected", [
        ("$0",      0x0),
        ("$f",      0xF),
        ("$ff",     0xFF),
        ("$0100",   0x0100),
        ("$abcd",   0xABCD),
        ("$ffff",   0xFFFF),
        ("$0000",   0x0000),
    ])
    def test_hex(self, expr, input_str, expected):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, input_str)
        assert ok, f"{input_str!r} should succeed"
        assert val == expected, f"{input_str!r}: expected ${expected:04X}, got ${val:04X}"

    def test_leading_spaces(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "  $42")
        assert ok and val == 0x42

    def test_stops_at_non_hex(self, expr):
        """Bare hex digits (starting with 0-9) stop at non-hex."""
        mpu, mem = _setup(expr)
        ok, val, consumed, _ = _eval(expr, mpu, mem, "$ff,x")
        assert ok and val == 0xFF
        assert consumed == 3  # "$ff"

    def test_stops_at_space(self, expr):
        mpu, mem = _setup(expr)
        ok, val, consumed, _ = _eval(expr, mpu, mem, "$42 rest")
        assert ok and val == 0x42
        # Parser skips trailing space when looking for +/- operator
        assert consumed == 4  # "$42 " (space consumed by operator check)


class TestDecimalLiterals:
    """Decimal values: bare digits (no prefix)."""

    @pytest.mark.parametrize("input_str,expected", [
        ("0",       0),
        ("1",       1),
        ("255",     255),
        ("256",     256),
        ("1000",    1000),
        ("65535",   65535),
        ("10",      10),
        ("100",     100),
    ])
    def test_decimal(self, expr, input_str, expected):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, input_str)
        assert ok, f"{input_str!r} should succeed"
        assert val == expected, f"{input_str!r}: expected {expected}, got {val}"


class TestBinaryLiterals:
    """Binary values: %bbbbbbbb."""

    @pytest.mark.parametrize("input_str,expected", [
        ("%0",              0x00),
        ("%1",              0x01),
        ("%10101010",       0xAA),
        ("%11111111",       0xFF),
        ("%100000000",      0x100),
        ("%1111111111111111", 0xFFFF),
    ])
    def test_binary(self, expr, input_str, expected):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, input_str)
        assert ok, f"{input_str!r} should succeed"
        assert val == expected, f"{input_str!r}: expected ${expected:04X}, got ${val:04X}"


class TestArithmetic:
    """Addition and subtraction."""

    @pytest.mark.parametrize("input_str,expected", [
        ("$1000+$10",     0x1010),
        ("$1000-$1",      0x0FFF),
        ("$10+$20+$30",   0x60),
        ("$100-$10-$1",   0xEF),
        ("$ff+1",         0x100),
        ("0+0",           0),
        ("$ffff+1",       0x0000),   # 16-bit wrap
        ("0-1",           0xFFFF),   # 16-bit underflow wraps
        ("$1000+16",      0x1010),   # hex + decimal
        ("$80+%10000000", 0x100),    # hex + binary
    ])
    def test_arithmetic(self, expr, input_str, expected):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, input_str)
        assert ok, f"{input_str!r} should succeed"
        assert val == expected, f"{input_str!r}: expected ${expected:04X}, got ${val:04X}"

    def test_spaces_around_operator(self, expr):
        """Spaces around +/- should be tolerated."""
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "$10 + $20")
        assert ok and val == 0x30

    def test_subtraction_chain(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "$100-$10-$20-$30")
        assert ok and val == 0xA0


class TestLoHiOperators:
    """< (lo byte) and > (hi byte) unary operators."""

    @pytest.mark.parametrize("input_str,expected", [
        ("<$1234",    0x34),
        (">$1234",    0x12),
        ("<$ff",      0xFF),
        (">$ff",      0x00),
        ("<$0000",    0x00),
        (">$0000",    0x00),
        ("<$ffff",    0xFF),
        (">$ffff",    0xFF),
    ])
    def test_lo_hi(self, expr, input_str, expected):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, input_str)
        assert ok, f"{input_str!r} should succeed"
        assert val == expected, f"{input_str!r}: expected ${expected:04X}, got ${val:04X}"

    def test_lo_in_expression(self, expr):
        """< applied to a subexpression result."""
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "<($1000+$234)")
        assert ok and val == 0x34

    def test_hi_in_expression(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, ">($1000+$234)")
        assert ok and val == 0x12


class TestParentheses:
    """Grouping with parentheses."""

    @pytest.mark.parametrize("input_str,expected", [
        ("($10)",           0x10),
        ("($10+$20)",       0x30),
        ("($100-$10)+$5",   0xF5),
        ("$5+($100-$10)",   0xF5),
    ])
    def test_parens(self, expr, input_str, expected):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, input_str)
        assert ok, f"{input_str!r} should succeed"
        assert val == expected, f"{input_str!r}: expected ${expected:04X}, got ${val:04X}"

    def test_nested_parens(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "(($10+$20)+$30)")
        assert ok and val == 0x60


class TestProgramCounter:
    """* = current PC value."""

    def test_star_alone(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "*", pc=0x1000)
        assert ok and val == 0x1000

    def test_star_plus_offset(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "*+3", pc=0x2000)
        assert ok and val == 0x2003

    def test_star_minus_offset(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "*-$10", pc=0x3000)
        assert ok and val == 0x2FF0

    def test_star_different_pc(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "*", pc=0xC000)
        assert ok and val == 0xC000


class TestLabels:
    """Symbol table lookups in expressions."""

    def test_simple_label(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "start")
        assert ok and val == 0x0800

    def test_label_plus_offset(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "start+$10")
        assert ok and val == 0x0810

    def test_label_minus_offset(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "table-$100")
        assert ok and val == 0xBF00

    def test_lo_label(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "<port")
        assert ok and val == 0x20

    def test_hi_label(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, ">port")
        assert ok and val == 0xD0

    def test_label_zero_value(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "zero")
        assert ok and val == 0x0000

    def test_label_ffff_value(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "top")
        assert ok and val == 0xFFFF

    def test_two_labels(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "table-start")
        assert ok and val == 0xB800

    def test_label_in_parens(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "<(table+$42)")
        assert ok and val == 0x42


class TestMixedExpressions:
    """Combinations of all factor types."""

    def test_hex_dec_binary(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "$10+16+%10000")
        assert ok and val == 0x30  # $10 + 16 + 16

    def test_star_plus_label(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, val, _, _ = _eval(expr, mpu, mem, "*+page", pc=0x1000)
        assert ok and val == 0x1100

    def test_lo_of_sum(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, "<($1200+$34)")
        assert ok and val == 0x34

    def test_hi_of_sum(self, expr):
        mpu, mem = _setup(expr)
        ok, val, _, _ = _eval(expr, mpu, mem, ">($1200+$34)")
        assert ok and val == 0x12


class TestPointerAdvancement:
    """expr_ptr must advance past consumed input and stop at the right place."""

    def test_stops_at_comma(self, expr):
        mpu, mem = _setup(expr)
        ok, val, consumed, _ = _eval(expr, mpu, mem, "$42,x")
        assert ok and val == 0x42
        assert consumed == 3  # "$42"

    def test_stops_at_nul(self, expr):
        mpu, mem = _setup(expr)
        ok, val, consumed, _ = _eval(expr, mpu, mem, "$42")
        assert ok and val == 0x42
        assert consumed == 3

    def test_stops_at_semicolon(self, expr):
        mpu, mem = _setup(expr)
        ok, val, consumed, _ = _eval(expr, mpu, mem, "$42;comment")
        assert ok and val == 0x42
        assert consumed == 3

    def test_stops_at_close_paren(self, expr):
        """Bare close paren is a terminator (not part of our expression)."""
        mpu, mem = _setup(expr)
        ok, val, consumed, _ = _eval(expr, mpu, mem, "$42)")
        assert ok and val == 0x42
        assert consumed == 3  # "$42", ')' is not consumed


# ═══════════════════════════════════════════════════════════════════
# NEGATIVE TESTS — expressions that must produce specific errors
# ═══════════════════════════════════════════════════════════════════

class TestErrorEmpty:
    """Empty or whitespace-only input."""

    def test_empty_string(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "")
        assert not ok and err == ERR_EXPECTED

    def test_spaces_only(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "   ")
        assert not ok and err == ERR_EXPECTED

    def test_bare_dollar(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "$")
        assert not ok and err == ERR_EXPECTED

    def test_bare_hash(self, expr):
        """# alone is not a valid expression (no decimal prefix anymore)."""
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "#")
        assert not ok and err == ERR_EXPECTED

    def test_bare_percent(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "%")
        assert not ok and err == ERR_EXPECTED


class TestErrorOverflow:
    """Values that exceed 16 bits."""

    def test_hex_5_digits(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "$12345")
        assert not ok and err == ERR_OVERFLOW

    def test_decimal_over_65535(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "65536")
        assert not ok and err == ERR_OVERFLOW

    def test_binary_17_bits(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "%11111111111111111")
        assert not ok and err == ERR_OVERFLOW


class TestErrorParens:
    """Mismatched parentheses."""

    def test_unclosed_paren(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "($10+$20")
        assert not ok and err == ERR_PAREN

    def test_empty_parens(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "()")
        assert not ok  # expected value inside parens

    def test_double_open(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, err = _eval(expr, mpu, mem, "(($10)")
        assert not ok and err == ERR_PAREN


class TestErrorUndefined:
    """Undefined symbol references."""

    def test_undefined_label(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, _, _, err = _eval(expr, mpu, mem, "nosuch")
        assert not ok and err == ERR_UNDEFINED

    def test_undefined_in_expression(self, expr):
        mpu, mem = _setup(expr)
        _define_symbols(expr, mpu, mem)
        ok, _, _, err = _eval(expr, mpu, mem, "start+nosuch")
        assert not ok and err == ERR_UNDEFINED


class TestErrorMalformed:
    """Syntactically broken expressions."""

    def test_double_operator(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, _ = _eval(expr, mpu, mem, "$10++$20")
        assert not ok  # second + has no left operand... actually +$20 could be anon label
        # For now, bare + after operator is an error

    def test_trailing_operator(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, _ = _eval(expr, mpu, mem, "$10+")
        assert not ok  # expected value after +

    def test_leading_operator(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, _ = _eval(expr, mpu, mem, "+$10")
        # + in unary position = anonymous forward label
        # Without anonymous labels defined, this should error
        assert not ok

    def test_just_close_paren(self, expr):
        mpu, mem = _setup(expr)
        ok, _, _, _ = _eval(expr, mpu, mem, ")")
        assert not ok
