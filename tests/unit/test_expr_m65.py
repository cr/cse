"""test_expr_m65.py — the expression evaluator and the symbol table in 32 bits (m65).

Owner: doc/modules/expr.md

Contract source: [expr.md § 32-bit values (m65)](../../doc/modules/expr.md#32-bit-values-m65),
[§ expr_eval32 (m65)](../../doc/modules/expr.md#expr_eval32-m65), the
return-code table (rc 7 `range`); [symtab.md § Design](../../doc/modules/symtab.md#design)
(the m65 entry: 8 bytes, SYM_TABLE 3.9F00-3.A6FF).  Slice 3, F5a.

The m65-45gs02 asm_core bundle on M65Emu (asm_dasm_runner.M65Bundle).
Three layers:

- every 16-bit vector of test_expr.py through `expr_eval` gives the
  c64's low word and return code — but a value outside -$FFFF..$FFFF
  is rc 7 (`range`), never a truncation: `$ffff+1`, `1<<16`, and the
  literals the c64 refuses as `ovfl` (`$12345`, `65536`, 17 binary
  digits) are values on m65, out of a 16-bit consumer's range;
- `expr_eval32`: the 32-bit values themselves — the literals to
  $FFFFFFFF, the flat literal `H.AAAA`, every operator in 32 bits, the
  FAR width, labels holding 32 bits, the errors;
- the symbol table: 4-byte values round-trip through all 256 slots
  of 8 bytes, and `sym_clear` covers exactly $9F00-$A6FF.
"""

import pytest

import asm_dasm_runner as R
from conftest import AsmCoreSymbols
from test_expr import (POSITIVE, NEGATIVE, NEGATIVE_ANY, SYMBOLS, _petscii,
                       RC_ZP, RC_ABS, ERR_EXPECTED, ERR_OVERFLOW, ERR_PAREN,
                       ERR_UNDEFINED, ERR_DIVZERO)

ERR_RANGE = 7
FAR = 3                       # expr_wide: bit 1 marks FAR, FAR implies ABS

STR_BUF = 0x3000
NAME_BUF = 0x3200
SYM_TABLE, SYM_HEAP = 0x9F00, 0xA700


@pytest.fixture(scope="module")
def syms():
    return AsmCoreSymbols("45gs02")


def bundle(syms):
    """An M65Bundle with RAM under $A000-$BFFF (port $35), as the data
    window gives CSE the table and the heap there."""
    m = R.M65Bundle(syms)
    m.mem[1] = 0x35
    return m


class Expr:
    """One M65Bundle; symbols defined through sym_define."""

    def __init__(self, syms):
        self.syms = syms
        self.m = bundle(syms)
        self.m.call(syms.sym_clear)

    def define(self, name, value, wide=1):
        s, m = self.syms, self.m
        enc = _petscii(name)
        m.poke(NAME_BUF, *enc)
        m.poke(s.sym_name, NAME_BUF & 0xFF, NAME_BUF >> 8)
        m.poke(s.sym_val, *value.to_bytes(4, "little"))
        m.poke(s.sym_wide, wide)
        m.call(s.sym_define)
        return m.emu.cpu.p & 1          # C: full

    def lookup(self, name):
        s, m = self.syms, self.m
        m.poke(NAME_BUF, *_petscii(name))
        m.poke(s.sym_name, NAME_BUF & 0xFF, NAME_BUF >> 8)
        m.call(s.sym_lookup)
        if m.emu.cpu.p & 1:
            return None
        return int.from_bytes(m.peek(s.sym_val, 4), "little"), m.peek(s.sym_wide)[0]

    def eval(self, text, far=False, pc=0x1000):
        """(rc, 32-bit value, expr_wide, characters consumed)."""
        s, m = self.syms, self.m
        m.poke(STR_BUF, *_petscii(text))
        m.poke(s.expr_ptr, STR_BUF & 0xFF, STR_BUF >> 8)
        m.poke(s.asm_pc, pc & 0xFF, pc >> 8, 0, 0)
        m.call(s.symbols["expr_eval32"] if far else s.expr_eval)
        rc = m.emu.a
        val = int.from_bytes(m.peek(s.expr_val, 4), "little")
        p = m.peek(s.expr_ptr, 2)
        return rc, val, m.peek(s.expr_wide)[0], (p[0] | p[1] << 8) - STR_BUF


@pytest.fixture
def ex(syms):
    e = Expr(syms)
    for name, (value, wide) in SYMBOLS.items():
        e.define(name, value, wide)
    e.define("far", 0x42005, 1)
    e.define("big", 100000, 1)
    return e


# ── the 16-bit consumers: the c64's answers, or `range` ──────────────────────

LEAVES_16 = {"$ffff+1", "1<<16"}               # 32-bit values above $FFFF


@pytest.mark.parametrize("text, want, rc, _sym, pc, purpose", POSITIVE,
                         ids=[t[5] for t in POSITIVE])
def test_a_16_bit_vector_keeps_its_low_word_and_rc(ex, text, want, rc, _sym, pc, purpose):
    got_rc, val, _, _ = ex.eval(text, pc=pc)
    if text in LEAVES_16:
        assert got_rc == ERR_RANGE, f"{purpose}: above $FFFF is range, not a wrap"
        return
    assert (got_rc, val & 0xFFFF) == (rc, want), purpose


RANGE_ON_M65 = {"$12345", "65536", "%11111111111111111"}


@pytest.mark.parametrize("text, err, _sym, purpose", NEGATIVE, ids=[t[3] for t in NEGATIVE])
def test_a_16_bit_error_vector(ex, text, err, _sym, purpose):
    rc = ex.eval(text)[0]
    assert rc == (ERR_RANGE if text in RANGE_ON_M65 else err), purpose


@pytest.mark.parametrize("text, _sym, purpose", NEGATIVE_ANY, ids=[t[2] for t in NEGATIVE_ANY])
def test_a_16_bit_error_vector_any(ex, text, _sym, purpose):
    assert ex.eval(text)[0] >= 2, purpose


@pytest.mark.parametrize("text, low", [
    ("-1", 0xFFFF), ("-$ffff", 0x0001), ("0-1", 0xFFFF), ("!0", 0xFFFF),
    ("$1000-$2000", 0xF000), ("0.2000", 0x2000), ("$0ffff", 0xFFFF),
    ("far-4.0000", 0x2005), ("far>>4", 0x4200),
])
def test_a_value_within_minus_ffff_to_ffff_passes_as_its_low_word(ex, text, low):
    rc, val, _, _ = ex.eval(text)
    assert rc == RC_ABS and val & 0xFFFF == low


@pytest.mark.parametrize("text", ["$10000", "4.2000", "-$10000", "$ffff0000",
                                  "far", "big", "$7fffffff", "-65536", "1<<31"])
def test_a_value_outside_minus_ffff_to_ffff_is_range(ex, text):
    assert ex.eval(text)[0] == ERR_RANGE


def test_range_has_its_error_text(ex):
    ex.eval("$12345")
    m, s = ex.m, ex.syms
    m.call(s.expr_error_str)
    ptr = m.emu.a | m.emu.x << 8
    assert m.peek(ptr, 6) == b"range\0"
    assert m.peek(s.last_err)[0] == ERR_RANGE


def test_the_opt_in_lasts_one_evaluation(ex):
    assert ex.eval("$12345", far=True)[0] == RC_ABS
    assert ex.eval("$12345")[0] == ERR_RANGE
    assert ex.eval("$12345", far=True)[0] == RC_ABS
    assert ex.eval("nosuch", far=True)[0] == ERR_UNDEFINED      # an error ends it too
    assert ex.eval("$12345")[0] == ERR_RANGE


# ── expr_eval32: the 32-bit values ──────────────────────────────────────────

ZP, ABS = 0, 1
VALUES = [
    # literals
    ("$12345",          0x00012345, FAR, "hex 5 digits"),
    ("$00001",          0x00000001, FAR, "hex 5 digits, by digits"),
    ("$12345678",       0x12345678, FAR, "hex 8 digits"),
    ("$ffffffff",       0xFFFFFFFF, FAR, "hex 8 digits max"),
    ("$1234",           0x00001234, ABS, "hex 4 digits"),
    ("$12",             0x00000012, ZP,  "hex 2 digits"),
    ("65536",           0x00010000, FAR, "decimal past 16 bits"),
    ("4294967295",      0xFFFFFFFF, FAR, "decimal max"),
    ("65535",           0x0000FFFF, ABS, "decimal 16 bits"),
    ("%1" + "0" * 16,   0x00010000, FAR, "binary 17 digits"),
    ("%" + "1" * 32,    0xFFFFFFFF, FAR, "binary 32 digits"),
    # the flat literal
    ("4.2000",          0x00042000, FAR, "flat literal"),
    ("0.2000",          0x00002000, FAR, "flat literal, bank 0"),
    ("1.f6ff",          0x0001F6FF, FAR, "flat literal, hex offset"),
    ("0ffd.3000",       0x0FFD3000, FAR, "flat literal, three bank digits"),
    ("0fff.ffff",       0x0FFFFFFF, FAR, "flat literal, the top"),
    ("800.0000",        0x08000000, FAR, "flat literal, a megabyte"),
    ("4.2000+5",        0x00042005, FAR, "flat literal in an expression"),
    ("(4.2000)",        0x00042000, FAR, "flat literal in parens"),
    # operators
    ("$12345+1",        0x00012346, FAR, "add"),
    ("$ffff+1",         0x00010000, FAR, "add past 16 bits"),
    ("$ffffffff+1",     0x00000000, FAR, "add wraps at 32 bits"),
    ("$10000-1",        0x0000FFFF, FAR, "sub: FAR from the operand"),
    ("0-1",             0xFFFFFFFF, FAR, "sub below 0"),
    ("$12345-$12345",   0x00000000, FAR, "sub to 0 keeps FAR"),
    ("-1",              0xFFFFFFFF, FAR, "negate"),
    ("-$12345",         0xFFFEDCBB, FAR, "negate FAR"),
    ("--$12345",        0x00012345, FAR, "double negate"),
    ("!0",              0xFFFFFFFF, FAR, "NOT"),
    ("!$ffff0000",      0x0000FFFF, FAR, "NOT keeps FAR from the factor"),
    ("$12345678&$ff00ff00", 0x12005600, FAR, "AND"),
    ("$12340000\\$5678", 0x12345678, FAR, "OR"),
    ("$12345678^$ffffffff", 0xEDCBA987, FAR, "XOR"),
    ("$1234*$10000",    0x12340000, FAR, "multiply"),
    ("$10000*$10000",   0x00000000, FAR, "multiply wraps at 32 bits"),
    ("$ffff*$ffff",     0xFFFE0001, FAR, "multiply 16 x 16"),
    ("100000*3",        300000,     FAR, "multiply decimal"),
    ("$12345678/$100",  0x00123456, FAR, "divide"),
    ("4294967295/10",   429496729,  FAR, "divide 32 bits by 10"),
    ("$12345678/$12345678", 1,      FAR, "divide to 1"),
    ("$42000/$10000",   4,          FAR, "divide to the bank"),
    ("1<<16",           0x00010000, FAR, "shift left past 16"),
    ("1<<31",           0x80000000, FAR, "shift left to bit 31"),
    ("1<<32",           0x00000000, ZP,  "shift left 32: all out (narrow, as 1<<16 on the c64)"),
    ("$80000000>>31",   1,          FAR, "shift right from bit 31"),
    ("$ffffffff>>32",   0,          FAR, "shift right 32: all out"),
    ("4.2000>>16",      4,          FAR, "the bank by a shift"),
    ("1<<$10000",       0,          FAR, "shift count above 16 bits"),
    # byte selectors
    ("<4.2005",         0x05,       ZP,  "byte 0"),
    (">4.2005",         0x20,       ZP,  "byte 1"),
    ("<(4.2005>>16)",   0x04,       ZP,  "byte 2"),
    (">(4.2005>>16)",   0x00,       ZP,  "byte 3"),
    (">($12345678>>16)", 0x12,      ZP,  "byte 3 nonzero"),
    # labels
    ("far",             0x00042005, FAR, "a label holding 32 bits"),
    ("far+1",           0x00042006, FAR, "a far label plus"),
    ("<far",            0x05,       ZP,  "lo of a far label"),
    ("far>>16",         0x04,       FAR, "bank of a far label"),
    ("big",             100000,     FAR, "a decimal constant"),
    ("start",           0x0800,     ABS, "a 16-bit label is unchanged"),
    ("loval",           0x42,       ZP,  "a ZP label is unchanged"),
    ("*",               0x1000,     ABS, "star is asm_pc's low word"),
]


@pytest.mark.parametrize("text, want, width, purpose", VALUES, ids=[v[3] for v in VALUES])
def test_a_32_bit_value(ex, text, want, width, purpose):
    rc, val, wide, used = ex.eval(text, far=True)
    assert rc == (RC_ZP if width == ZP else RC_ABS), purpose
    assert val == want, f"{purpose}: ${val:08X}"
    assert (wide & 3) == width, f"{purpose}: expr_wide ${wide:02X}"
    assert used == len(text), f"{purpose}: stopped after {used}"


@pytest.mark.parametrize("text, used, want", [
    ("4.200", 1, 4),                  # three offset digits: decimal 4, stops at the dot
    ("4.20000", 1, 4),                # five offset digits
    ("1000.0000", 4, 1000),           # a bank word above $FFF
    ("12345.0000", 5, 12345),         # five bank digits
    ("4.", 1, 4),
])
def test_a_dotted_number_not_in_the_flat_shape_is_decimal(ex, text, used, want):
    rc, val, _, n = ex.eval(text, far=True)
    assert rc <= 1 and val == want and n == used


@pytest.mark.parametrize("text, err", [
    ("$123456789",      ERR_OVERFLOW),     # a ninth hex digit
    ("4294967296",      ERR_OVERFLOW),     # decimal past 32 bits
    ("99999999999",     ERR_OVERFLOW),
    ("%1" + "0" * 32,   ERR_OVERFLOW),     # 33 binary digits
    ("$12345/0",        ERR_DIVZERO),
    ("$12345/($ffffffff+1)", ERR_DIVZERO),            # 0 after the wrap
    ("4.2000+nosuch",   ERR_UNDEFINED),
    ("(4.2000",         ERR_PAREN),
    ("4.2000+",         ERR_EXPECTED),
])
def test_a_32_bit_error(ex, text, err):
    assert ex.eval(text, far=True)[0] == err


def test_a_divide_by_a_far_zero_is_div0(ex):
    assert ex.eval("1/($10000-$10000)", far=True)[0] == ERR_DIVZERO


def test_ten_nested_levels_still_parse_and_eleven_overflow(ex):
    assert ex.eval("(" * 10 + "4.2000" + ")" * 10, far=True)[:2] == (RC_ABS, 0x42000)
    assert ex.eval("(" * 11 + "1" + ")" * 11, far=True)[0] == ERR_OVERFLOW


def test_deep_pending_operands_keep_all_four_bytes(ex):
    text = "$11111111+($22222222*(1+($10000&(4.2000-(0.1000\\1)))))"
    want = (0x11111111 + 0x22222222 * (1 + (0x10000 & (0x42000 - (0x1000 | 1))))) & 0xFFFFFFFF
    assert ex.eval(text, far=True)[:2] == (RC_ABS, want)


# ── the symbol table: 4-byte values, 8-byte entries ─────────────────────────

def test_a_symbol_keeps_four_bytes(syms):
    e = Expr(syms)
    e.define("x", 0x12345678)
    e.define("y", 0x0000ABCD, 1)
    e.define("z", 0x42, 0)
    assert e.lookup("x") == (0x12345678, 1)
    assert e.lookup("y") == (0x0000ABCD, 1)
    assert e.lookup("z") == (0x42, 0)
    e.define("x", 0xFEDCBA98)                     # redefine: the value replaced
    assert e.lookup("x") == (0xFEDCBA98, 1)


def test_256_symbols_fill_the_table_and_each_keeps_its_value(syms):
    e = Expr(syms)
    names = [f"s{k}" for k in range(256)]
    for k, n in enumerate(names):
        assert not e.define(n, 0x01010101 * (k & 0xFF) ^ (k << 12)), n
    assert e.define("over", 1)                    # the 257th: full
    for k, n in enumerate(names):
        assert e.lookup(n) == (0x01010101 * (k & 0xFF) ^ (k << 12), 1), n


def test_sym_clear_covers_the_table_at_9f00_and_nothing_else(syms):
    m = bundle(syms)
    for a in range(SYM_TABLE - 0x10, SYM_HEAP + 0x10):
        m.mem.write_flat(a, 0xAA)
    m.call(syms.sym_clear)
    got = bytes(m.mem.read_flat(a) for a in range(SYM_TABLE - 0x10, SYM_HEAP + 0x10))
    assert got[:0x10] == b"\xaa" * 0x10                  # below $9F00: kept
    assert got[0x10:-0x10] == bytes(SYM_HEAP - SYM_TABLE)  # 2048 bytes zeroed
    assert got[-0x10:] == b"\xaa" * 0x10                 # the heap: kept
