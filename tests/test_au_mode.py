"""
test_au_mode.py – pytest tests for src/au_mode.s

Each test calls mode_parse with a PETSCII-encoded argument string and checks:
  A  = mode index (0=IMP .. 15=ZPREL)
  X  = operand byte count (0, 1, or 2)
  asm_opr[0]  = first / lo operand byte
  asm_opr[1]  = second / hi operand byte  (ABS hi, or ZPREL relative offset)
"""

import pytest
from py65.devices.mpu6502 import MPU

# ── PETSCII encoder ──────────────────────────────────────────────────────────
# PETSCII uppercase A-Z = $41-$5A (same as ASCII uppercase).
# Digits 0-9 = $30-$39, punctuation: same as ASCII.

def sc(s: str) -> bytes:
    """Encode an ASCII argument string to PETSCII + NUL terminator.

    Uppercase ASCII maps directly to PETSCII uppercase ($41-$5A).
    """
    out = []
    for c in s:
        out.append(ord(c))   # ASCII uppercase = PETSCII uppercase
    out.append(0x00)
    return bytes(out)


# ── Mode index constants (mirror au_mode.s) ───────────────────────────────────
IMP   = 0
ACC   = 1
IMM   = 2
ZP    = 3
ZPX   = 4
ZPY   = 5
ABS   = 6
ABX   = 7
ABY   = 8
IND   = 9
INX   = 10
INY   = 11
REL   = 12   # syntactically identical to ZP; Zone B path remaps
ZPI   = 13
AIX   = 14
ZPREL = 15


# ── Test vectors ──────────────────────────────────────────────────────────────
# Format: (arg_string, mode, x, opr0, opr1)
# arg_string uses ASCII; sc() converts to PETSCII before the call.
CASES = [
    # ── IMP ──────────────────────────────────────────────────────────────────
    ("",               IMP,   0, 0x00, 0x00),  # empty
    ("   ",            IMP,   0, 0x00, 0x00),  # whitespace only
    ("; comment",      IMP,   0, 0x00, 0x00),  # semicolon comment
    ("// comment",     IMP,   0, 0x00, 0x00),  # double-slash comment
    ("#",              IMP,   0, 0x00, 0x00),  # bare '#' → IMP (not IMM)
    # "# $FF" has '#' then space then '$FF': asm_skip_ws after '#'
    # brings us to '$FF', so this IS IMM — tested below.

    # ── ACC ──────────────────────────────────────────────────────────────────
    ("A",              ACC,   0, 0x00, 0x00),
    ("A ; comment",    ACC,   0, 0x00, 0x00),
    ("A // end",       ACC,   0, 0x00, 0x00),
    ("A #ann",         ACC,   0, 0x00, 0x00),  # trailing '#' = end

    # ── IMM ──────────────────────────────────────────────────────────────────
    ("#$00",           IMM,   1, 0x00, 0x00),
    ("#$FF",           IMM,   1, 0xFF, 0x00),
    ("#$42",           IMM,   1, 0x42, 0x00),
    ("# $A0",          IMM,   1, 0xA0, 0x00),  # space tolerated after '#'
    ("#$A0 ; note",    IMM,   1, 0xA0, 0x00),  # trailing comment

    # ── ZP ───────────────────────────────────────────────────────────────────
    ("$00",            ZP,    1, 0x00, 0x00),
    ("$FF",            ZP,    1, 0xFF, 0x00),
    ("$42",            ZP,    1, 0x42, 0x00),
    ("$42 ; ok",       ZP,    1, 0x42, 0x00),

    # ── ZPX / ZPY ────────────────────────────────────────────────────────────
    ("$42,X",          ZPX,   1, 0x42, 0x00),
    ("$42 , X",        ZPX,   1, 0x42, 0x00),  # spaces around ','
    ("$00,X",          ZPX,   1, 0x00, 0x00),
    ("$42,Y",          ZPY,   1, 0x42, 0x00),
    ("$FF,Y",          ZPY,   1, 0xFF, 0x00),

    # ── ABS ──────────────────────────────────────────────────────────────────
    ("$0000",          ABS,   2, 0x00, 0x00),
    ("$1234",          ABS,   2, 0x34, 0x12),  # little-endian: lo=$34, hi=$12
    ("$FFFF",          ABS,   2, 0xFF, 0xFF),
    ("$C000",          ABS,   2, 0x00, 0xC0),
    ("$1234 ; ok",     ABS,   2, 0x34, 0x12),

    # ── ABX / ABY ────────────────────────────────────────────────────────────
    ("$1234,X",        ABX,   2, 0x34, 0x12),
    ("$1234 , X",      ABX,   2, 0x34, 0x12),
    ("$1234,Y",        ABY,   2, 0x34, 0x12),
    ("$0000,X",        ABX,   2, 0x00, 0x00),

    # ── IND ($nnnn) ──────────────────────────────────────────────────────────
    ("($1234)",        IND,   2, 0x34, 0x12),
    ("( $1234 )",      IND,   2, 0x34, 0x12),  # spaces inside parens
    ("($FFFE)",        IND,   2, 0xFE, 0xFF),

    # ── AIX ($nnnn,X) ────────────────────────────────────────────────────────
    ("($1234,X)",      AIX,   2, 0x34, 0x12),
    ("( $1234 , X )",  AIX,   2, 0x34, 0x12),

    # ── INX ($nn,X) ──────────────────────────────────────────────────────────
    ("($42,X)",        INX,   1, 0x42, 0x00),
    ("( $42 , X )",    INX,   1, 0x42, 0x00),
    ("($00,X)",        INX,   1, 0x00, 0x00),

    # ── INY ($nn),Y ──────────────────────────────────────────────────────────
    ("($42),Y",        INY,   1, 0x42, 0x00),
    ("( $42 ) , Y",    INY,   1, 0x42, 0x00),
    ("($FF),Y",        INY,   1, 0xFF, 0x00),

    # ── ZPI ($nn) ────────────────────────────────────────────────────────────
    ("($42)",          ZPI,   1, 0x42, 0x00),
    ("( $42 )",        ZPI,   1, 0x42, 0x00),

    # ── ZPREL $nn,$rr ────────────────────────────────────────────────────────
    ("$42,$10",        ZPREL, 2, 0x42, 0x10),
    ("$00,$00",        ZPREL, 2, 0x00, 0x00),
    ("$FF,$80",        ZPREL, 2, 0xFF, 0x80),

    # ── Expression operands (expr_eval integration) ──────────────────────
    ("#42",            IMM,   1, 0x2A, 0x00),  # bare decimal
    ("#%11111111",     IMM,   1, 0xFF, 0x00),  # binary
    ("#$40+2",         IMM,   1, 0x42, 0x00),  # arithmetic
    ("$40+2",          ZP,    1, 0x42, 0x00),  # ZP via expression
    ("$40+2,X",        ZPX,   1, 0x42, 0x00),  # ZPX via expression
    ("$C000+$20",      ABS,   2, 0x20, 0xC0),  # ABS via expression
    ("$C000+$20,X",    ABX,   2, 0x20, 0xC0),  # ABX via expression
    ("($40+2,X)",      INX,   1, 0x42, 0x00),  # INX via expression
    ("($40+2),Y",      INY,   1, 0x42, 0x00),  # INY via expression
    ("($C000+$34)",    IND,   2, 0x34, 0xC0),  # IND via expression
]


# ── Syntax-error vectors ──────────────────────────────────────────────────────
ERROR_CASES = [
    "(",           # '(' not followed by a valid expression
    "($42,Z)",     # unknown register
    "($42)Z",      # garbage after ZPI
    "($1234)Y",    # missing comma before Y in indirect
    "$42,Z",       # unknown register
    "$1234,Z",     # unknown register
    "$GG",         # bad hex digit
]


# ── CPU runner ────────────────────────────────────────────────────────────────
_TEST_BUF = 0x3000   # scratch address for encoded argument strings
_MAX_STEPS = 20_000  # safety limit


def _run(syms, arg: str):
    """
    Set up a fresh CPU, write the encoded argument to RAM, point asm_ptr at it,
    call mode_parse, and return (mode, x, opr0, opr1) on success or raise
    on syntax error.
    """
    cpu = MPU()
    mem = cpu.memory

    # Load the test binary
    syms.load_into(mem)

    # Write encoded argument string
    encoded = sc(arg)
    for i, b in enumerate(encoded):
        mem[_TEST_BUF + i] = b

    # Set asm_ptr
    mem[syms.asm_ptr]     = _TEST_BUF & 0xFF
    mem[syms.asm_ptr + 1] = (_TEST_BUF >> 8) & 0xFF

    # Set asm_pass = 1 so undefined symbols are errors (not forward refs)
    mem[syms.asm_pass] = 1

    # Fake JSR: push return-minus-one ($FFFE) so RTS lands at $FFFF
    cpu.sp = 0xFF
    mem[0x01FF] = 0xFF   # hi byte of return address
    mem[0x01FE] = 0xFE   # lo byte  → RTS increments to $FFFF
    cpu.sp = 0xFD

    cpu.pc = syms.mode_parse
    cpu.y  = 0

    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            # clean return
            return (cpu.a, cpu.x, mem[syms.asm_opr], mem[syms.asm_opr + 1])
        if cpu.pc == syms.asm_syntax_error:
            raise SyntaxError(f"asm_syntax_error reached for {arg!r}")
        cpu.step()

    raise TimeoutError(f"exceeded {_MAX_STEPS} steps for {arg!r}")


# ── Tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("arg,mode,x,opr0,opr1", CASES,
                         ids=[c[0] or "(empty)" for c in CASES])
def test_parse_ok(syms, arg, mode, x, opr0, opr1):
    got_mode, got_x, got_opr0, got_opr1 = _run(syms, arg)
    assert got_mode == mode,  f"mode: got {got_mode}, expected {mode}"
    assert got_x    == x,     f"byte count: got {got_x}, expected {x}"
    assert got_opr0 == opr0,  f"opr[0]: got ${got_opr0:02X}, expected ${opr0:02X}"
    assert got_opr1 == opr1,  f"opr[1]: got ${got_opr1:02X}, expected ${opr1:02X}"


@pytest.mark.parametrize("arg", ERROR_CASES, ids=ERROR_CASES)
def test_parse_error(syms, arg):
    with pytest.raises(SyntaxError):
        _run(syms, arg)
