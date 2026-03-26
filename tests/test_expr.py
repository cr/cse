"""
test_expr.py — Expression parser tests (expr.s + symtab.s)

All tests in two parametrized lists:
  POSITIVE — (expression, expected_value, needs_symbols, pc, description)
  NEGATIVE — (expression, expected_error, needs_symbols, description)

Symbol fixture preloads: zero=$0000, one=$0001, page=$0100, screen=$0400,
start=$0800, table=$C000, top=$FFFF, lo_val=$0042, port=$D020.
"""

import subprocess, pathlib, re, pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

EXPR_BIN = BUILD / "expr_test.bin"
EXPR_MAP = BUILD / "expr_test.map"

_STR_BUF  = 0x0A00
_NAME_BUF = 0x0B00
_RETURN   = 0x0F00

# Error codes (must match expr.s)
ERR_EXPECTED  = 1
ERR_OVERFLOW  = 2
ERR_PAREN     = 3
ERR_UNDEFINED = 4

SYMBOLS = {
    "zero": 0x0000, "one": 0x0001, "page": 0x0100, "screen": 0x0400,
    "start": 0x0800, "table": 0xC000, "top": 0xFFFF,
    "lo_val": 0x0042, "port": 0xD020,
}

# ═══════════════════════════════════════════════════════════════════
# Test data: (expr_string, expected_value, needs_symbols, pc, purpose)
# ═══════════════════════════════════════════════════════════════════
POSITIVE = [
    # ── hex literals ($) ──────────────────────────────────────────
    ("$0",              0x0000, False, 0x1000, "hex zero"),
    ("$f",              0x000F, False, 0x1000, "hex single digit"),
    ("$ff",             0x00FF, False, 0x1000, "hex 2 digits"),
    ("$0100",           0x0100, False, 0x1000, "hex 4 digits"),
    ("$abcd",           0xABCD, False, 0x1000, "hex letters"),
    ("$ffff",           0xFFFF, False, 0x1000, "hex max"),
    ("$0000",           0x0000, False, 0x1000, "hex explicit zero"),
    ("  $42",           0x0042, False, 0x1000, "hex leading spaces"),

    # ── decimal literals (bare digits) ────────────────────────────
    ("0",               0,      False, 0x1000, "decimal zero"),
    ("1",               1,      False, 0x1000, "decimal one"),
    ("10",              10,     False, 0x1000, "decimal ten"),
    ("100",             100,    False, 0x1000, "decimal hundred"),
    ("255",             255,    False, 0x1000, "decimal 255"),
    ("256",             256,    False, 0x1000, "decimal 256"),
    ("1000",            1000,   False, 0x1000, "decimal thousand"),
    ("65535",           65535,  False, 0x1000, "decimal max u16"),

    # ── binary literals (%) ───────────────────────────────────────
    ("%0",              0x00,   False, 0x1000, "binary zero"),
    ("%1",              0x01,   False, 0x1000, "binary one"),
    ("%10101010",       0xAA,   False, 0x1000, "binary alternating"),
    ("%11111111",       0xFF,   False, 0x1000, "binary 8-bit max"),
    ("%100000000",      0x100,  False, 0x1000, "binary 9-bit"),
    ("%1111111111111111", 0xFFFF, False, 0x1000, "binary 16-bit max"),

    # ── arithmetic (+/-) ─────────────────────────────────────────
    ("$1000+$10",       0x1010, False, 0x1000, "hex + hex"),
    ("$1000-$1",        0x0FFF, False, 0x1000, "hex - hex"),
    ("$10+$20+$30",     0x0060, False, 0x1000, "triple add"),
    ("$100-$10-$1",     0x00EF, False, 0x1000, "triple sub"),
    ("$ff+1",           0x0100, False, 0x1000, "hex + decimal"),
    ("0+0",             0x0000, False, 0x1000, "zero + zero"),
    ("$ffff+1",         0x0000, False, 0x1000, "16-bit wrap"),
    ("0-1",             0xFFFF, False, 0x1000, "underflow wraps"),
    ("$1000+16",        0x1010, False, 0x1000, "hex + decimal mixed"),
    ("$80+%10000000",   0x0100, False, 0x1000, "hex + binary mixed"),
    ("$10 + $20",       0x0030, False, 0x1000, "spaces around +"),
    ("$100-$10-$20-$30", 0x00A0, False, 0x1000, "long sub chain"),

    # ── lo/hi byte operators (<, >) ──────────────────────────────
    ("<$1234",          0x0034, False, 0x1000, "lo byte"),
    (">$1234",          0x0012, False, 0x1000, "hi byte"),
    ("<$ff",            0x00FF, False, 0x1000, "lo of 8-bit"),
    (">$ff",            0x0000, False, 0x1000, "hi of 8-bit"),
    ("<$0000",          0x0000, False, 0x1000, "lo of zero"),
    (">$0000",          0x0000, False, 0x1000, "hi of zero"),
    ("<$ffff",          0x00FF, False, 0x1000, "lo of max"),
    (">$ffff",          0x00FF, False, 0x1000, "hi of max"),
    ("<($1000+$234)",   0x0034, False, 0x1000, "lo of sum"),
    (">($1000+$234)",   0x0012, False, 0x1000, "hi of sum"),

    # ── parentheses ──────────────────────────────────────────────
    ("($10)",           0x0010, False, 0x1000, "simple parens"),
    ("($10+$20)",       0x0030, False, 0x1000, "add in parens"),
    ("($100-$10)+$5",   0x00F5, False, 0x1000, "parens + value"),
    ("$5+($100-$10)",   0x00F5, False, 0x1000, "value + parens"),
    ("(($10+$20)+$30)", 0x0060, False, 0x1000, "nested parens"),

    # ── program counter (*) ──────────────────────────────────────
    ("*",               0x1000, False, 0x1000, "star alone"),
    ("*+3",             0x2003, False, 0x2000, "star + offset"),
    ("*-$10",           0x2FF0, False, 0x3000, "star - offset"),
    ("*",               0xC000, False, 0xC000, "star at $C000"),

    # ── labels (require symbol table) ────────────────────────────
    ("start",           0x0800, True, 0x1000, "simple label"),
    ("start+$10",       0x0810, True, 0x1000, "label + hex"),
    ("table-$100",      0xBF00, True, 0x1000, "label - hex"),
    ("<port",           0x0020, True, 0x1000, "lo of label"),
    (">port",           0x00D0, True, 0x1000, "hi of label"),
    ("zero",            0x0000, True, 0x1000, "label value zero"),
    ("top",             0xFFFF, True, 0x1000, "label value ffff"),
    ("table-start",     0xB800, True, 0x1000, "label - label"),
    ("<(table+$42)",    0x0042, True, 0x1000, "lo of label+offset"),

    # ── mixed ────────────────────────────────────────────────────
    ("$10+16+%10000",   0x0030, False, 0x1000, "hex+dec+bin"),
    ("*+page",          0x1100, True, 0x1000, "star + label"),
    ("<($1200+$34)",    0x0034, False, 0x1000, "lo of hex sum"),
    (">($1200+$34)",    0x0012, False, 0x1000, "hi of hex sum"),
]

# ═══════════════════════════════════════════════════════════════════
# Error data: (expr_string, expected_error, needs_symbols, purpose)
# ═══════════════════════════════════════════════════════════════════
NEGATIVE = [
    # ── empty / missing value ────────────────────────────────────
    ("",                ERR_EXPECTED,  False, "empty string"),
    ("   ",             ERR_EXPECTED,  False, "spaces only"),
    ("$",               ERR_EXPECTED,  False, "bare $"),
    ("#",               ERR_EXPECTED,  False, "bare # (not a prefix)"),
    ("%",               ERR_EXPECTED,  False, "bare %"),

    # ── overflow ─────────────────────────────────────────────────
    ("$12345",          ERR_OVERFLOW,  False, "hex 5 digits"),
    ("65536",           ERR_OVERFLOW,  False, "decimal > 65535"),
    ("%11111111111111111", ERR_OVERFLOW, False, "binary 17 bits"),

    # ── parentheses ──────────────────────────────────────────────
    ("($10+$20",        ERR_PAREN,     False, "unclosed paren"),
    ("(($10)",          ERR_PAREN,     False, "double open"),

    # ── undefined symbols ────────────────────────────────────────
    ("nosuch",          ERR_UNDEFINED, True,  "undefined label"),
    ("start+nosuch",    ERR_UNDEFINED, True,  "undefined in expr"),

    # ── malformed ────────────────────────────────────────────────
    ("$10+",            ERR_EXPECTED,  False, "trailing +"),
    ("+$10",            ERR_EXPECTED,  False, "leading + (no anon labels)"),
    (")",               ERR_EXPECTED,  False, "bare close paren"),
]

# Also test these produce an error but don't require a specific code:
NEGATIVE_ANY = [
    ("$10++$20",        False, "double operator"),
    ("()",              False, "empty parens"),
]

# ═══════════════════════════════════════════════════════════════════
# Infrastructure
# ═══════════════════════════════════════════════════════════════════

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
    for name, src in [("expr", SRC/"expr.s"), ("symtab", SRC/"symtab.s"),
                      ("expr_test_stub", DEV/"expr_test_stub.s")]:
        subprocess.run(["ca65", "--cpu", "6502", "-t", "c64", str(src),
                        "-o", str(BUILD/f"{name}.o")], check=True)
    subprocess.run(["ld65", "-C", str(DEV/"test.cfg"),
                    str(BUILD/"expr.o"), str(BUILD/"symtab.o"),
                    str(BUILD/"expr_test_stub.o"),
                    "-o", str(EXPR_BIN), "-m", str(EXPR_MAP)], check=True)

def _parse_exports():
    syms = {}
    in_exp = False
    for line in EXPR_MAP.read_text().splitlines():
        if "Exports list by name" in line: in_exp = True; continue
        if in_exp:
            for m in re.finditer(r'(\w+)\s+([0-9a-fA-F]{6})\s+RL', line):
                syms[m.group(1)] = int(m.group(2), 16)
            if line.strip() == "": break
    return syms

def _parse_stub_offset():
    in_stub = False
    for line in EXPR_MAP.read_text().splitlines():
        if 'expr_test_stub.o:' in line: in_stub = True; continue
        if in_stub and 'CODE' in line:
            m = re.search(r'Offs=([0-9a-fA-F]+)', line)
            if m: return int(m.group(1), 16)
            break
        if in_stub and not line.startswith(' '): break
    return None

def _petscii(s):
    out = []
    for c in s:
        if 'a' <= c <= 'z': out.append(ord(c) - ord('a') + 0x41)
        elif 'A' <= c <= 'Z': out.append(ord(c) - ord('A') + 0xC1)
        else: out.append(ord(c))
    out.append(0)
    return bytes(out)

class ExprFixture:
    def __init__(self):
        if _needs_rebuild(): _build()
        self.exports = _parse_exports()
        self._raw = EXPR_BIN.read_bytes()
        stub_off = _parse_stub_offset()
        if stub_off is None:
            raise RuntimeError("Cannot find expr_test_stub CODE offset")
        base = 0x0200 + stub_off
        self.eval_entry = base
        self.define_entry = base + 4
        self.clear_entry = base + 8
        self.expr_ptr = self.exports["expr_ptr"]
        self.expr_val = self.exports["expr_val"]
        self.asm_pc = self.exports["al_pc"]
        self.sym_name = self.exports["sym_name"]
        self.sym_val = self.exports["sym_val"]

    def load_into(self, mem):
        mem[0:0x100] = self._raw[:0x100]
        code = self._raw[0x100:]
        mem[0x200:0x200+len(code)] = code

@pytest.fixture(scope="session")
def expr():
    return ExprFixture()

def _call(mpu, mem, entry):
    mem[_RETURN] = 0x00
    mpu.sp = 0xFF
    mpu.sp -= 1; mem[0x01FF] = (_RETURN - 1) >> 8
    mpu.sp -= 1; mem[0x01FE] = (_RETURN - 1) & 0xFF
    mpu.pc = entry
    for _ in range(100000):
        if mpu.pc == _RETURN: return
        mpu.step()
    raise RuntimeError(f"Timeout at ${mpu.pc:04X}")

def _setup(fix):
    mpu = MPU()
    mem = bytearray(0x10000)
    fix.load_into(mem)
    mpu.memory = mem
    return mpu, mem

def _define_symbols(fix, mpu, mem):
    _call(mpu, mem, fix.clear_entry)
    addr = _NAME_BUF
    for name, value in SYMBOLS.items():
        enc = _petscii(name)
        for i, b in enumerate(enc): mem[addr+i] = b
        mem[fix.sym_name] = addr & 0xFF; mem[fix.sym_name+1] = (addr>>8) & 0xFF
        mem[fix.sym_val] = value & 0xFF; mem[fix.sym_val+1] = (value>>8) & 0xFF
        _call(mpu, mem, fix.define_entry)
        addr += len(enc)

def _eval(fix, mpu, mem, input_str, pc=0x1000):
    ep, ev, ap = fix.expr_ptr, fix.expr_val, fix.asm_pc
    enc = _petscii(input_str)
    for i, b in enumerate(enc): mem[_STR_BUF+i] = b
    mem[ep] = _STR_BUF & 0xFF; mem[ep+1] = (_STR_BUF>>8) & 0xFF
    mem[ap] = pc & 0xFF; mem[ap+1] = (pc>>8) & 0xFF
    _call(mpu, mem, fix.eval_entry)
    carry = mpu.p & 1
    ok = carry == 0
    val = mem[ev] | (mem[ev+1] << 8)
    err = mpu.a if not ok else 0
    return ok, val, err

# ═══════════════════════════════════════════════════════════════════
# Parametrized tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "input_str, expected, needs_sym, pc, purpose",
    POSITIVE,
    ids=[t[4] for t in POSITIVE],
)
def test_positive(expr, input_str, expected, needs_sym, pc, purpose):
    mpu, mem = _setup(expr)
    if needs_sym:
        _define_symbols(expr, mpu, mem)
    ok, val, _ = _eval(expr, mpu, mem, input_str, pc=pc)
    assert ok, f"{purpose}: '{input_str}' should succeed"
    assert val == expected, f"{purpose}: '{input_str}' expected ${expected:04X}, got ${val:04X}"


@pytest.mark.parametrize(
    "input_str, err_code, needs_sym, purpose",
    NEGATIVE,
    ids=[t[3] for t in NEGATIVE],
)
def test_negative(expr, input_str, err_code, needs_sym, purpose):
    mpu, mem = _setup(expr)
    if needs_sym:
        _define_symbols(expr, mpu, mem)
    ok, _, err = _eval(expr, mpu, mem, input_str)
    assert not ok, f"{purpose}: '{input_str}' should fail"
    assert err == err_code, f"{purpose}: '{input_str}' expected err={err_code}, got err={err}"


@pytest.mark.parametrize(
    "input_str, needs_sym, purpose",
    NEGATIVE_ANY,
    ids=[t[2] for t in NEGATIVE_ANY],
)
def test_negative_any(expr, input_str, needs_sym, purpose):
    """Error expected, but specific code not guaranteed."""
    mpu, mem = _setup(expr)
    if needs_sym:
        _define_symbols(expr, mpu, mem)
    ok, _, _ = _eval(expr, mpu, mem, input_str)
    assert not ok, f"{purpose}: '{input_str}' should fail"
