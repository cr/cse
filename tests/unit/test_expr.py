"""test_expr.py — Tier-U unit tests for expr.s.

Contract source: [doc/modules/expr.md](../../doc/modules/expr.md).

Coverage of the documented contract
-----------------------------------
3 exported entry points:

  expr_eval          — test_positive (60+ cases) + test_negative (13
                        error cases) + test_negative_any (more errors)
                        covering: hex/decimal/binary literals, all
                        operators, width rules, label resolution,
                        `*` (PC), operator precedence
  expr_eval          — TestExprEvalBankContract (6 tests) pins the
  banking contract     documented $01-bit-1 / I-flag invariants across
                        all exit paths (ZP, ABS, error, sym_lookup hit,
                        undefined, complex)
  expr_error_str     — TestExprErrorStr (4 tests): all 7 last_err codes
                        resolve; codes 2..6 distinct; out-of-range (≥7)
                        clamps to slot 0; each pointer is NUL-terminated

Return codes (from expr.md):
  0 = RC_ZP         (valid, 8-bit / ZP-eligible)
  1 = RC_ABS        (valid, 16-bit / forced wide)
  2 = ERR_EXPECTED  (expected value)
  3 = ERR_OVERFLOW  (value too large)
  4 = ERR_PAREN     (mismatched parentheses)
  5 = ERR_UNDEFINED (undefined symbol)
  6 = ERR_DIVZERO   (division by zero)

Width rule: 3+ hex digits force ABS. Labels inherit width from definition.
< and > at expression start force ZP. Result > $FF forces ABS.

Out-of-scope (vocal skip)
-------------------------
  TestExprEvalNb::test_expr_eval_nb_contract — expr_eval_nb shares the
  evaluator body with expr_eval (only difference: no banking wrapper).
  Functional correctness is exhaustively covered via expr_eval's test
  sweep; no-banking variant exercised transitively through
  test_addr_mode.py::test_parse_ok (mode_parse → expr_eval_nb).

Symbol fixture (used by label-resolution tests):
  zero=$0000(zp), one=$0001(zp), page=$0100(abs), screen=$0400(abs),
  start=$0800(abs), table=$C000(abs), top=$FFFF(abs),
  loval=$0042(zp), zpaddr=$0042(abs — defined as $0042 with 4 digits),
  port=$D020(abs).

Bundle: asm_core (expr.s + symtab.s + mem.s + rest of asm pipeline).
"""

import pytest
from py65.devices.mpu6502 import MPU

_STR_BUF  = 0x1000   # must be above BSS end (sym_table ~768B + other)
_NAME_BUF = 0x1100
_RETURN   = 0x0F00

# Return codes (must match expr.s)
RC_ZP        = 0   # valid, 8-bit / ZP-eligible
RC_ABS       = 1   # valid, 16-bit / force ABS
ERR_EXPECTED = 2   # expected value
ERR_OVERFLOW = 3   # value too large
ERR_PAREN    = 4   # mismatched parens
ERR_UNDEFINED = 5  # undefined symbol
ERR_DIVZERO  = 6   # division by zero

# Symbols: (value, wide_flag)
# loval is defined with 2-digit hex ($42) → ZP
# zpaddr is defined with 4-digit hex ($0042) → ABS (same value, different width)
SYMBOLS = {
    "zero":    (0x0000, 0),  # $00 → ZP
    "one":     (0x0001, 0),  # $01 → ZP
    "page":    (0x0100, 1),  # $0100 → ABS
    "screen":  (0x0400, 1),  # $0400 → ABS
    "start":   (0x0800, 1),  # $0800 → ABS
    "table":   (0xC000, 1),  # $c000 → ABS
    "top":     (0xFFFF, 1),  # $ffff → ABS
    "loval":  (0x0042, 0),  # $42 → ZP
    "zpaddr": (0x0042, 1),  # $0042 → ABS (forced wide by 4-digit definition)
    "port":    (0xD020, 1),  # $d020 → ABS
}

# ═══════════════════════════════════════════════════════════════════
# (expression, expected_value, expected_rc, needs_symbols, pc, purpose)
#   rc: RC_ZP=0, RC_ABS=1
# ═══════════════════════════════════════════════════════════════════
POSITIVE = [
    # ── hex: width from digit count ──────────────────────────────
    ("$0",              0x0000, RC_ZP,  False, 0x1000, "hex 1 digit → ZP"),
    ("$f",              0x000F, RC_ZP,  False, 0x1000, "hex 1 digit letter → ZP"),
    ("$ff",             0x00FF, RC_ZP,  False, 0x1000, "hex 2 digits → ZP"),
    ("$42",             0x0042, RC_ZP,  False, 0x1000, "hex 2 digits → ZP"),
    ("$0100",           0x0100, RC_ABS, False, 0x1000, "hex 4 digits → ABS"),
    ("$abcd",           0xABCD, RC_ABS, False, 0x1000, "hex 4 digits letters → ABS"),
    ("$ffff",           0xFFFF, RC_ABS, False, 0x1000, "hex 4 digits max → ABS"),
    ("$0000",           0x0000, RC_ABS, False, 0x1000, "hex 4 digits zero → ABS (forced)"),
    ("$0042",           0x0042, RC_ABS, False, 0x1000, "hex 4 digits ≤$FF → ABS (forced)"),
    ("$042",            0x0042, RC_ABS, False, 0x1000, "hex 3 digits → ABS (forced)"),
    ("  $42",           0x0042, RC_ZP,  False, 0x1000, "hex leading spaces → ZP"),
    ("\xa0$42",          0x0042, RC_ZP,  False, 0x1000, "hex leading tab → ZP"),
    ("\xa0 $42",         0x0042, RC_ZP,  False, 0x1000, "hex tab+space → ZP"),
    (" \xa0$42",         0x0042, RC_ZP,  False, 0x1000, "hex space+tab → ZP"),

    # ── decimal: width from value ────────────────────────────────
    ("0",               0,      RC_ZP,  False, 0x1000, "decimal 0 → ZP"),
    ("1",               1,      RC_ZP,  False, 0x1000, "decimal 1 → ZP"),
    ("255",             255,    RC_ZP,  False, 0x1000, "decimal 255 → ZP"),
    ("256",             256,    RC_ABS, False, 0x1000, "decimal 256 → ABS"),
    ("1000",            1000,   RC_ABS, False, 0x1000, "decimal 1000 → ABS"),
    ("65535",           65535,  RC_ABS, False, 0x1000, "decimal max → ABS"),
    ("10",              10,     RC_ZP,  False, 0x1000, "decimal 10 → ZP"),
    ("100",             100,    RC_ZP,  False, 0x1000, "decimal 100 → ZP"),

    # ── binary: width from value ─────────────────────────────────
    ("%0",              0x00,   RC_ZP,  False, 0x1000, "binary 0 → ZP"),
    ("%1",              0x01,   RC_ZP,  False, 0x1000, "binary 1 → ZP"),
    ("%10101010",       0xAA,   RC_ZP,  False, 0x1000, "binary $AA → ZP"),
    ("%11111111",       0xFF,   RC_ZP,  False, 0x1000, "binary $FF → ZP"),
    ("%100000000",      0x100,  RC_ABS, False, 0x1000, "binary 9-bit → ABS"),
    ("%1111111111111111", 0xFFFF, RC_ABS, False, 0x1000, "binary 16-bit → ABS"),

    # ── arithmetic: wide propagates ──────────────────────────────
    ("$10+$20",         0x0030, RC_ZP,  False, 0x1000, "ZP + ZP → ZP"),
    ("$1000+$10",       0x1010, RC_ABS, False, 0x1000, "ABS + ZP → ABS"),
    ("$ff+1",           0x0100, RC_ABS, False, 0x1000, "ZP+ZP but result>$FF → ABS"),
    ("$1000-$1",        0x0FFF, RC_ABS, False, 0x1000, "ABS - ZP → ABS"),
    ("$10+$20+$30",     0x0060, RC_ZP,  False, 0x1000, "triple ZP add → ZP"),
    ("$100-$10-$1",     0x00EF, RC_ABS, False, 0x1000, "ABS chain result ≤$FF → still ABS"),
    ("0+0",             0x0000, RC_ZP,  False, 0x1000, "zero + zero → ZP"),
    ("$ffff+1",         0x0000, RC_ABS, False, 0x1000, "16-bit wrap → ABS"),
    ("0-1",             0xFFFF, RC_ABS, False, 0x1000, "underflow → ABS"),
    ("$1000+16",        0x1010, RC_ABS, False, 0x1000, "ABS + decimal → ABS"),
    ("$80+%10000000",   0x0100, RC_ABS, False, 0x1000, "result > $FF → ABS"),
    ("$10 + $20",       0x0030, RC_ZP,  False, 0x1000, "spaces around + → ZP"),
    ("$10\xa0+\xa0$20",  0x0030, RC_ZP,  False, 0x1000, "tabs around + → ZP"),
    ("$10\xa0+ $20",     0x0030, RC_ZP,  False, 0x1000, "tab+space around + → ZP"),
    ("$100-$10-$20-$30", 0x00A0, RC_ABS, False, 0x1000, "ABS chain → ABS"),

    # ── lo/hi: always ZP ────────────────────────────────────────
    ("<$1234",          0x0034, RC_ZP,  False, 0x1000, "lo byte → ZP"),
    (">$1234",          0x0012, RC_ZP,  False, 0x1000, "hi byte → ZP"),
    ("<$ff",            0x00FF, RC_ZP,  False, 0x1000, "lo of ZP → ZP"),
    (">$ff",            0x0000, RC_ZP,  False, 0x1000, "hi of ZP → ZP"),
    ("<$0000",          0x0000, RC_ZP,  False, 0x1000, "lo of zero → ZP"),
    (">$0000",          0x0000, RC_ZP,  False, 0x1000, "hi of zero → ZP"),
    ("<$ffff",          0x00FF, RC_ZP,  False, 0x1000, "lo of max → ZP"),
    (">$ffff",          0x00FF, RC_ZP,  False, 0x1000, "hi of max → ZP"),
    ("<($1000+$234)",   0x0034, RC_ZP,  False, 0x1000, "lo of ABS sum → ZP"),
    (">($1000+$234)",   0x0012, RC_ZP,  False, 0x1000, "hi of ABS sum → ZP"),

    # ── parentheses: inherit width ───────────────────────────────
    ("($10)",           0x0010, RC_ZP,  False, 0x1000, "parens ZP → ZP"),
    ("($10+$20)",       0x0030, RC_ZP,  False, 0x1000, "parens ZP+ZP → ZP"),
    ("($0100-$10)+$5",  0x00F5, RC_ABS, False, 0x1000, "parens ABS+ZP → ABS"),
    ("$5+($100-$10)",   0x00F5, RC_ABS, False, 0x1000, "ZP+parens ABS → ABS"),
    ("(($10+$20)+$30)", 0x0060, RC_ZP,  False, 0x1000, "nested parens ZP → ZP"),

    # ── program counter: width from PC value ─────────────────────
    ("*",               0x1000, RC_ABS, False, 0x1000, "star $1000 → ABS"),
    ("*+3",             0x2003, RC_ABS, False, 0x2000, "star + offset → ABS"),
    ("*-$10",           0x2FF0, RC_ABS, False, 0x3000, "star - offset → ABS"),
    ("*",               0x0042, RC_ZP,  False, 0x0042, "star $42 → ZP"),

    # ── labels: inherit width from definition ────────────────────
    ("start",           0x0800, RC_ABS, True, 0x1000, "label ABS → ABS"),
    ("loval",          0x0042, RC_ZP,  True, 0x1000, "label ZP → ZP"),
    ("zpaddr",         0x0042, RC_ABS, True, 0x1000, "label forced ABS → ABS"),
    ("start+$10",       0x0810, RC_ABS, True, 0x1000, "ABS label + ZP → ABS"),
    ("table-$100",      0xBF00, RC_ABS, True, 0x1000, "ABS label - ABS → ABS"),
    ("<port",           0x0020, RC_ZP,  True, 0x1000, "lo of ABS label → ZP"),
    (">port",           0x00D0, RC_ZP,  True, 0x1000, "hi of ABS label → ZP"),
    ("zero",            0x0000, RC_ZP,  True, 0x1000, "ZP label value 0 → ZP"),
    ("top",             0xFFFF, RC_ABS, True, 0x1000, "ABS label $FFFF → ABS"),
    ("table-start",     0xB800, RC_ABS, True, 0x1000, "ABS - ABS → ABS"),
    ("<(table+$42)",    0x0042, RC_ZP,  True, 0x1000, "lo of ABS sum → ZP"),

    # ── multiply / divide ────────────────────────────────────────
    ("3*4",             12,     RC_ZP,  False, 0x1000, "3*4 = 12"),
    ("$10*$10",         0x0100, RC_ABS, False, 0x1000, "$10*$10 = $100"),
    ("$100/4",          0x0040, RC_ABS, False, 0x1000, "$100/4 = $40"),
    ("255/2",           127,    RC_ZP,  False, 0x1000, "255/2 = 127 (integer)"),
    ("10/3",            3,      RC_ZP,  False, 0x1000, "10/3 = 3 (truncated)"),
    ("0/1",             0,      RC_ZP,  False, 0x1000, "0/1 = 0"),
    ("7*0",             0,      RC_ZP,  False, 0x1000, "7*0 = 0"),
    ("1*1",             1,      RC_ZP,  False, 0x1000, "1*1 = 1"),

    # ── bit shifts ───────────────────────────────────────────────
    ("1<<4",            0x0010, RC_ZP,  False, 0x1000, "1<<4 = $10"),
    ("$ff<<8",          0xFF00, RC_ABS, False, 0x1000, "$ff<<8 = $ff00"),
    ("$8000>>8",        0x0080, RC_ABS, False, 0x1000, "$8000>>8 = $80"),
    ("$ff>>4",          0x000F, RC_ZP,  False, 0x1000, "$ff>>4 = $0f"),
    ("1<<0",            1,      RC_ZP,  False, 0x1000, "1<<0 = 1 (no shift)"),
    ("$80>>0",          0x0080, RC_ZP,  False, 0x1000, "$80>>0 = $80"),
    ("%10000000>>7",    1,      RC_ZP,  False, 0x1000, "bit 7 >> 7 = 1"),

    # ── boolean operations (£ = OR, ^ = XOR/↑, & = AND, ! = NOT) ──
    ("$ff&$0f",         0x000F, RC_ZP,  False, 0x1000, "AND ZP"),
    ("$f0\\$0f",         0x00FF, RC_ZP,  False, 0x1000, "OR ZP"),
    ("$ff^$0f",         0x00F0, RC_ZP,  False, 0x1000, "XOR ZP"),
    ("!$ff",            0xFF00, RC_ABS, False, 0x1000, "NOT $FF → $FF00"),
    ("!0",              0xFFFF, RC_ABS, False, 0x1000, "NOT 0 → $FFFF"),
    ("$abcd&$ff00",     0xAB00, RC_ABS, False, 0x1000, "AND ABS"),
    ("$1234\\$00ff",     0x12FF, RC_ABS, False, 0x1000, "OR ABS"),
    ("$1234^$ffff",     0xEDCB, RC_ABS, False, 0x1000, "XOR ABS"),
    ("!$0000",          0xFFFF, RC_ABS, False, 0x1000, "NOT ABS zero → $FFFF"),

    # ── unary minus (negate) ────────────────────────────────────────
    ("-1",              0xFFFF, RC_ABS, False, 0x1000, "negate 1 → $FFFF"),
    ("-0",              0x0000, RC_ZP,  False, 0x1000, "negate 0 → 0"),
    ("-$ff",            0xFF01, RC_ABS, False, 0x1000, "negate $FF → $FF01"),
    ("-$100",           0xFF00, RC_ABS, False, 0x1000, "negate $100 → $FF00"),
    ("-$ffff",          0x0001, RC_ABS, False, 0x1000, "negate $FFFF → 1 (still ABS)"),
    ("--1",             0x0001, RC_ABS, False, 0x1000, "double negate → 1 (ABS from intermediate)"),
    ("-1+2",            0x0001, RC_ABS, False, 0x1000, "negate then add: -1+2=1 (ABS from negate)"),
    ("10+-1",           0x0009, RC_ABS, False, 0x1000, "add negative: 10+(-1)=9 (ABS from -1)"),
    ("<-$1234",         0x00CC, RC_ZP,  False, 0x1000, "lo of negated ABS → ZP"),

    # ── precedence: mul/div/shift bind tighter than +/- ──────────
    ("2+4/2",           4,      RC_ZP,  False, 0x1000, "2+(4/2) = 4 not (2+4)/2=3"),
    ("2+3*4",           14,     RC_ZP,  False, 0x1000, "2+(3*4) = 14 not (2+3)*4=20"),
    ("$10-2*3",         10,     RC_ZP,  False, 0x1000, "$10-(2*3) = 10"),
    # shifts same precedence as mul/div: "1<<4+1" = "(1<<4)+1" = $11 = 17
    ("1<<4+1",          17,     RC_ZP,  False, 0x1000, "(1<<4)+1 = 17"),
    ("$100>>4+1",       0x0011, RC_ABS, False, 0x1000, "($100>>4)+1 = $11 (ABS from $100)"),

    # ── precedence: boolean binds LOOSEST ────────────────────────
    ("$ff&$0f+$10",     0x001F, RC_ZP,  False, 0x1000, "AND lower prec than +"),
    ("$0f\\$10+$20",     0x003F, RC_ZP,  False, 0x1000, "OR lower prec than +"),
    ("$ff^$10+$20",     0x00CF, RC_ZP,  False, 0x1000, "XOR lower prec than +"),
    ("$ff&3*4",         0x000C, RC_ZP,  False, 0x1000, "AND lower prec than *"),
    ("$0f\\1<<4",        0x001F, RC_ZP,  False, 0x1000, "OR lower prec than <<"),

    # ── compound expressions ─────────────────────────────────────
    ("(2+3)*4",         20,     RC_ZP,  False, 0x1000, "parens override prec"),
    ("$ff&($0f+$10)",   0x001F, RC_ZP,  False, 0x1000, "AND with parens"),
    ("!$ff&$ff",        0x0000, RC_ABS, False, 0x1000, "NOT then AND: (!$ff)&$ff = 0 (ABS from NOT)"),
    ("!($ff&$0f)",      0xFFF0, RC_ABS, False, 0x1000, "NOT of AND: !($0f) = $fff0"),
    ("1<<(4+4)",        0x0100, RC_ABS, False, 0x1000, "shift by expression"),
    (">($100*2)",       0x0002, RC_ZP,  False, 0x1000, "hi of mul result"),
    ("<($1234\\$ff00)",  0x0034, RC_ZP,  False, 0x1000, "lo of OR result"),
    ("start+$100/2",    0x0880, RC_ABS, True,  0x1000, "label + div"),

    # ── mixed ────────────────────────────────────────────────────
    ("$10+16+%10000",   0x0030, RC_ZP,  False, 0x1000, "hex+dec+bin ZP"),
    ("*+page",          0x1100, RC_ABS, True, 0x1000, "star + ABS label"),
    ("<($1200+$34)",    0x0034, RC_ZP,  False, 0x1000, "lo of hex sum"),
    (">($1200+$34)",    0x0012, RC_ZP,  False, 0x1000, "hi of hex sum"),
]

# ═══════════════════════════════════════════════════════════════════
# (expression, expected_error, needs_symbols, purpose)
# ═══════════════════════════════════════════════════════════════════
NEGATIVE = [
    ("",                ERR_EXPECTED,  False, "empty string"),
    ("   ",             ERR_EXPECTED,  False, "spaces only"),
    ("$",               ERR_EXPECTED,  False, "bare $"),
    ("#",               ERR_EXPECTED,  False, "bare # (not a prefix)"),
    ("%",               ERR_EXPECTED,  False, "bare %"),
    ("$12345",          ERR_OVERFLOW,  False, "hex 5 digits"),
    ("65536",           ERR_OVERFLOW,  False, "decimal > 65535"),
    ("%11111111111111111", ERR_OVERFLOW, False, "binary 17 bits"),
    ("($10+$20",        ERR_PAREN,     False, "unclosed paren"),
    ("(($10)",          ERR_PAREN,     False, "double open"),
    ("nosuch",          ERR_UNDEFINED, True,  "undefined label"),
    ("start+nosuch",    ERR_UNDEFINED, True,  "undefined in expr"),
    ("10/0",            ERR_DIVZERO,   False, "division by zero"),
    ("$10+",            ERR_EXPECTED,  False, "trailing +"),
    ("+$10",            ERR_EXPECTED,  False, "leading + (no anon labels)"),
    (")",               ERR_EXPECTED,  False, "bare close paren"),
]

NEGATIVE_ANY = [
    ("$10++$20",        False, "double operator"),
    ("()",              False, "empty parens"),
]

# ═══════════════════════════════════════════════════════════════════
# Infrastructure
#
# Tranche 3 (Phase 21.1 follow-up): expr_eval / sym_define / sym_clear
# are now called directly through the asm_core `asm_syms` fixture — no
# separate binary, no per-entry trampolines, no dev/expr_test_stub.s.
# ═══════════════════════════════════════════════════════════════════

def _petscii(s):
    """Convert ASCII test string to PETSCII bytes.
    Operators: # ($23), & ($26), ^ ($5E=↑), ! ($21) are same in ASCII/PETSCII.
    << and >> use < ($3C) and > ($3E) which are also same."""
    SPECIAL = {'\\': 0x5C}  # backslash in test string → £ ($5C) in PETSCII
    out = []
    for c in s:
        if c in SPECIAL: out.append(SPECIAL[c])
        elif 'a' <= c <= 'z': out.append(ord(c) - ord('a') + 0x41)
        elif 'A' <= c <= 'Z': out.append(ord(c) - ord('A') + 0xC1)
        else: out.append(ord(c))
    out.append(0)
    return bytes(out)


from conftest import make_cpu, push_rts_sentinel, step_until_pc


def _call(mpu, mem, entry):
    """JSR-like: push sentinel to stack, set PC=entry, step to return."""
    push_rts_sentinel(mpu, sentinel=_RETURN)
    mpu.pc = entry
    step_until_pc(mpu, _RETURN, max_steps=100_000, what=f"call ${entry:04X}")


def _setup(asm_syms):
    """Fresh MPU with the asm_core bundle loaded."""
    return make_cpu(asm_syms)


def _define_symbols(asm_syms, mpu, mem):
    """Define all test symbols with their wide flags."""
    _call(mpu, mem, asm_syms.sym_clear)
    addr = _NAME_BUF
    for name, (value, wide) in SYMBOLS.items():
        enc = _petscii(name)
        for i, b in enumerate(enc): mem[addr+i] = b
        mem[asm_syms.sym_name]     = addr & 0xFF
        mem[asm_syms.sym_name + 1] = (addr >> 8) & 0xFF
        mem[asm_syms.sym_val]      = value & 0xFF
        mem[asm_syms.sym_val + 1]  = (value >> 8) & 0xFF
        mem[asm_syms.sym_wide]     = wide
        _call(mpu, mem, asm_syms.sym_define)
        addr += len(enc)


def _eval(asm_syms, mpu, mem, input_str, pc=0x1000):
    """Evaluate expression. Returns (rc, value).
    rc: 0=ZP, 1=ABS, 2+=error code."""
    enc = _petscii(input_str)
    for i, b in enumerate(enc): mem[_STR_BUF + i] = b
    mem[asm_syms.expr_ptr]     = _STR_BUF & 0xFF
    mem[asm_syms.expr_ptr + 1] = (_STR_BUF >> 8) & 0xFF
    mem[asm_syms.asm_pc]       = pc & 0xFF
    mem[asm_syms.asm_pc + 1]   = (pc >> 8) & 0xFF
    _call(mpu, mem, asm_syms.expr_eval)
    rc = mpu.a   # 0=ZP, 1=ABS, 2+=error
    val = mem[asm_syms.expr_val] | (mem[asm_syms.expr_val + 1] << 8)
    return rc, val

# ═══════════════════════════════════════════════════════════════════
# Parametrized tests
# ═══════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "input_str, expected, exp_rc, needs_sym, pc, purpose",
    POSITIVE,
    ids=[t[5] for t in POSITIVE],
)
def test_positive(asm_syms, input_str, expected, exp_rc, needs_sym, pc, purpose):
    mpu, mem = _setup(asm_syms)
    if needs_sym:
        _define_symbols(asm_syms, mpu, mem)
    rc, val = _eval(asm_syms, mpu, mem, input_str, pc=pc)
    assert rc <= 1, f"{purpose}: '{input_str}' should succeed, got error {rc}"
    assert val == expected, f"{purpose}: '{input_str}' expected ${expected:04X}, got ${val:04X}"
    assert rc == exp_rc, f"{purpose}: '{input_str}' expected rc={exp_rc} ({'ZP' if exp_rc==0 else 'ABS'}), got rc={rc}"


@pytest.mark.parametrize(
    "input_str, err_code, needs_sym, purpose",
    NEGATIVE,
    ids=[t[3] for t in NEGATIVE],
)
def test_negative(asm_syms, input_str, err_code, needs_sym, purpose):
    mpu, mem = _setup(asm_syms)
    if needs_sym:
        _define_symbols(asm_syms, mpu, mem)
    rc, _ = _eval(asm_syms, mpu, mem, input_str)
    assert rc >= 2, f"{purpose}: '{input_str}' should fail, got rc={rc}"
    assert rc == err_code, f"{purpose}: '{input_str}' expected err={err_code}, got err={rc}"


@pytest.mark.parametrize(
    "input_str, needs_sym, purpose",
    NEGATIVE_ANY,
    ids=[t[2] for t in NEGATIVE_ANY],
)
def test_negative_any(asm_syms, input_str, needs_sym, purpose):
    mpu, mem = _setup(asm_syms)
    if needs_sym:
        _define_symbols(asm_syms, mpu, mem)
    rc, _ = _eval(asm_syms, mpu, mem, input_str)
    assert rc >= 2, f"{purpose}: '{input_str}' should fail, got rc={rc}"


# ── expr_eval bank-state contract ───────────────────────────────────────────
#
# expr_eval owns its KERNAL banking — same wrapper structure as
# asm_line and dasm_insn.  These tests pin the contract:
#
#   - $01 bit 1 set (KERNAL banked back in) on every exit path
#   - I flag clear on every exit path
#
# Exit paths covered:
#   - success ZP (rc=0)
#   - success ABS (rc=1)
#   - error (rc>=2)
#   - symbol lookup (touches sym_table/sym_heap under KERNAL)
#
# In the expr test environment, sym_table lives in regular RAM
# (not under $E000), so banking has no semantic effect on the
# data — but $01 bit 1 toggling is observable.

def _eval_with_bank_witness(asm_syms, mpu, mem, input_str, pc=0x1000):
    """Like _eval, but also captures $01 and the I flag at exit."""
    enc = _petscii(input_str)
    for i, b in enumerate(enc):
        mem[_STR_BUF + i] = b
    mem[asm_syms.expr_ptr]     = _STR_BUF & 0xFF
    mem[asm_syms.expr_ptr + 1] = (_STR_BUF >> 8) & 0xFF
    mem[asm_syms.asm_pc]       = pc & 0xFF
    mem[asm_syms.asm_pc + 1]   = (pc >> 8) & 0xFF
    # Pre-condition: $01 bit 1 = 1, I = 0
    mem[0x01] = 0x37
    mpu.p &= ~0x04
    _call(mpu, mem, asm_syms.expr_eval)
    rc = mpu.a
    val = mem[asm_syms.expr_val] | (mem[asm_syms.expr_val + 1] << 8)
    return rc, val, mem[0x01], mpu.p


class TestExprEvalBankContract:
    """expr_eval must restore $01 bit 1 = 1 and clear I after every call."""

    def test_bank_restored_simple_zp(self, asm_syms):
        mpu, mem = _setup(asm_syms)
        rc, val, port01, p = _eval_with_bank_witness(asm_syms, mpu, mem, "$10")
        assert rc == 0 and val == 0x10
        assert (port01 & 0x02) == 0x02, \
            f"$01 bit 1 not set after expr_eval: ${port01:02X}"
        assert (p & 0x04) == 0, \
            f"I flag still set after expr_eval: ${p:02X}"

    def test_bank_restored_abs(self, asm_syms):
        mpu, mem = _setup(asm_syms)
        rc, val, port01, p = _eval_with_bank_witness(asm_syms, mpu, mem, "$1234")
        assert rc == 1 and val == 0x1234
        assert (port01 & 0x02) == 0x02
        assert (p & 0x04) == 0

    def test_bank_restored_error(self, asm_syms):
        mpu, mem = _setup(asm_syms)
        rc, _, port01, p = _eval_with_bank_witness(asm_syms, mpu, mem, ")")
        assert rc >= 2
        assert (port01 & 0x02) == 0x02, \
            f"$01 bit 1 not set after expr_eval error: ${port01:02X}"
        assert (p & 0x04) == 0

    def test_bank_restored_after_sym_lookup(self, asm_syms):
        """The interesting case: expr_eval calls sym_lookup, which
        does its own banking internally.  expr_eval must still leave
        the bank state correct on return."""
        mpu, mem = _setup(asm_syms)
        _define_symbols(asm_syms, mpu, mem)
        rc, val, port01, p = _eval_with_bank_witness(asm_syms, mpu, mem, "screen")
        assert rc < 2, f"sym lookup failed: rc={rc}"
        assert val == 0x0400
        assert (port01 & 0x02) == 0x02
        assert (p & 0x04) == 0

    def test_bank_restored_after_complex_expr(self, asm_syms):
        """Multi-symbol expression — exercises sym_lookup multiple times."""
        mpu, mem = _setup(asm_syms)
        _define_symbols(asm_syms, mpu, mem)
        rc, val, port01, p = _eval_with_bank_witness(
            asm_syms, mpu, mem, "screen+page-one")
        assert rc < 2, f"complex expr failed: rc={rc}"
        assert val == 0x0400 + 0x0100 - 1
        assert (port01 & 0x02) == 0x02
        assert (p & 0x04) == 0

    def test_bank_restored_after_undefined_sym(self, asm_syms):
        """sym_lookup miss — expr_eval returns ERR_UNDEFINED via the
        same exit path that handles other errors."""
        mpu, mem = _setup(asm_syms)
        _define_symbols(asm_syms, mpu, mem)
        rc, _, port01, p = _eval_with_bank_witness(
            asm_syms, mpu, mem, "no_such_label_xyz")
        assert rc >= 2
        assert (port01 & 0x02) == 0x02
        assert (p & 0x04) == 0


# ─── expr_error_str — error-message pointer accessor ────────────────────────
#
# expr_error_str returns A/X = pointer to the NUL-terminated error
# message matching last_err (set by the preceding expr_eval call).
# Out-of-range last_err values (≥7) clamp to slot 0.

def _run_error_str(asm_syms, last_err_value):
    """Set last_err, call expr_error_str, return (A, X) = pointer."""
    cpu, mem = make_cpu(asm_syms)
    mem[asm_syms.last_err] = last_err_value
    sentinel = push_rts_sentinel(cpu)
    cpu.pc = asm_syms.expr_error_str
    step_until_pc(cpu, sentinel, max_steps=100, what="expr_error_str")
    return cpu.a, cpu.x


class TestExprErrorStr:
    """expr_error_str: returns A/X = pointer to err_str[last_err]."""

    def test_all_valid_codes_return_nonzero_pointer(self, asm_syms):
        """Codes 0..6 each map to a valid error-string pointer."""
        for code in range(7):
            lo, hi = _run_error_str(asm_syms, code)
            addr = lo | (hi << 8)
            assert addr != 0, \
                f"code {code}: expected non-zero pointer, got $0000"

    def test_error_codes_return_distinct_pointers(self, asm_syms):
        """Each ERROR code (2..6) maps to a distinct message slot.
        Codes 0 (RC_ZP) and 1 (RC_ABS) are success returns; they may
        legitimately alias each other (no error text needed)."""
        ptrs = []
        for code in range(2, 7):   # ERR_EXPECTED .. ERR_DIVZERO
            lo, hi = _run_error_str(asm_syms, code)
            ptrs.append(lo | (hi << 8))
        assert len(set(ptrs)) == 5, \
            f"error-string pointers collide: {[hex(p) for p in ptrs]}"

    def test_out_of_range_clamps_to_zero(self, asm_syms):
        """last_err ≥ 7 clamps to slot 0 (doc § expr_error_str)."""
        lo0, hi0 = _run_error_str(asm_syms, 0)
        lo_over, hi_over = _run_error_str(asm_syms, 0xFF)
        assert (lo_over, hi_over) == (lo0, hi0), \
            f"out-of-range didn't clamp: got ${hi_over:02X}${lo_over:02X}, " \
            f"expected ${hi0:02X}${lo0:02X}"

    def test_points_at_nul_terminated_string(self, asm_syms):
        """The returned pointer dereferences to PETSCII with a NUL
        terminator somewhere in the first 64 bytes."""
        mem = bytearray(65536)
        asm_syms.load_into(mem)
        for code in range(7):
            mem[asm_syms.last_err] = code
            lo, hi = _run_error_str(asm_syms, code)
            addr = lo | (hi << 8)
            # Find NUL within reasonable bound.
            found_nul = any(mem[addr + i] == 0 for i in range(64))
            assert found_nul, f"code {code}: no NUL within 64 bytes at ${addr:04X}"


# ─── expr_eval_nb — no-banking variant (subsumption vocal skip) ─────────────

class TestExprEvalNb:

    @pytest.mark.skip(reason=(
        "expr_eval_nb (expr.md § expr_eval): the 'no-banking' variant "
        "shares the evaluator body with expr_eval; the only difference "
        "is that expr_eval brackets the call with kernal_bank_out/in "
        "and expr_eval_nb does not.  Functional correctness is verified "
        "exhaustively by test_positive / test_negative / test_negative_any "
        "(60+ cases through expr_eval).  The no-banking entry is exercised "
        "transitively by test_addr_mode.py::test_parse_ok (41 operand forms "
        "via mode_parse → expr_eval_nb).  The only expr_eval-specific "
        "contract (banking state) is tested in TestExprEvalBankContract "
        "above; the no-banking variant by definition does NOT restore "
        "banking, so a symmetric test would be testing an absent contract. "
        "Vocal skip per doc/testing.md § Principle 9 Pattern B (subsumed)."
    ))
    def test_expr_eval_nb_contract(self, asm_syms):
        pass
