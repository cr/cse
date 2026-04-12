"""test_asm_src.py — Two-pass source assembler integration tests.

Tests the full pipeline: source text → _test_src_buf → _asm_assemble → memory.

The test binary links asm_src.s with the complete assembler core (asm_line,
expr, symtab, mn7, etc.).  asm_src_test_stub.s provides mock
implementations of ed_read_line, io_puts, cse_end, pushax, cse_popax.

Source text is written as PETSCII: ASCII uppercase = C64 uppercase PETSCII.
Lines are NUL-terminated; a $FF sentinel marks EOF for the mock reader.
Blank lines (lone NUL) are preserved correctly.
"""

import re
from pathlib import Path

import pytest
from py65.devices.mpu6502 import MPU

BUILD = Path(__file__).resolve().parent.parent / "build"


_MAX_STEPS  = 1_000_000  # safety limit for two-pass assembly
_ZP_START   = 0x0000
_CODE_START = 0x4000
_ZP_SIZE    = 0x0100


# ── PETSCII encoding ──────────────────────────────────────────────────────────

def _petscii(text: str) -> bytes:
    """Encode Python ASCII source text to C64 PETSCII uppercase.

    Lowercase a-z → uppercase $41-$5A (same as ASCII A-Z).
    Everything else passes through unchanged.
    Line separator: NUL ($00).  Blank lines are a lone NUL.
    EOF marker: $FF (cannot appear in legitimate assembly source —
    it's a C64 graphic glyph, not a syntax character).  See
    asm_src_test_stub.s::ed_read_line for the matching decoder.
    """
    result = bytearray()
    for ch in text:
        if ch == '\n':
            result.append(0x00)     # line separator for ed_read_line mock
        elif 'a' <= ch <= 'z':
            result.append(ord(ch) - 0x20)   # lowercase → uppercase PETSCII
        else:
            result.append(ord(ch))
    result.append(0x00)     # terminate the final line
    result.append(0xFF)     # EOF sentinel
    return bytes(result)


# ── py65 runner ───────────────────────────────────────────────────────────────

def _run(as_syms, source: str):
    """Run the two-pass assembler over source and return (org, bytes, errors).

    Returns:
        org    — assembled origin address (uint16)
        data   — bytes list read from memory at org
        errors — error count (uint16)
    """
    cpu = MPU()
    mem = cpu.memory

    as_syms.load_into(mem)

    # Write source text to _test_src_buf
    encoded = _petscii(source)
    for i, b in enumerate(encoded):
        mem[as_syms.test_src_buf + i] = b

    # Fake JSR: push sentinel return address $FFFE so RTS lands at $FFFF
    cpu.sp = 0xFF
    mem[0x01FF] = 0xFF
    mem[0x01FE] = 0xFE
    cpu.sp = 0xFD

    cpu.pc = as_syms.asm_src_test_entry

    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            break
        cpu.step()
    else:
        raise TimeoutError(f"exceeded {_MAX_STEPS} steps")

    org    = mem[as_syms.asm_org] | (mem[as_syms.asm_org + 1] << 8)
    size   = mem[as_syms.asm_size] | (mem[as_syms.asm_size + 1] << 8)
    errors = mem[as_syms.asm_errors] | (mem[as_syms.asm_errors + 1] << 8)
    data   = list(mem[org : org + size])
    return org, data, errors


# ── Test cases ────────────────────────────────────────────────────────────────

MANUAL_TESTS = [
    {
        "name": "basic instructions",
        "source": ".org $c000\n  lda #0\n  sta $d020\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0x8D, 0x20, 0xD0, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "constants",
        "source": ".const border $d020\n.org $c000\n  lda #0\n  sta border\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0x8D, 0x20, 0xD0, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "global labels",
        "source": ".org $c000\nstart:\n  lda #0\n  jmp start",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0x4C, 0x00, 0xC0],
        "expect_errors": 0,
    },
    {
        "name": "forward label reference",
        "source": ".org $c000\n  jmp done\n  nop\ndone:\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0x4C, 0x04, 0xC0, 0xEA, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "branch forward",
        "source": ".org $c000\n  lda #0\n  beq skip\n  nop\nskip:\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0xF0, 0x01, 0xEA, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "branch backward",
        "source": ".org $c000\nloop:\n  inc $d020\n  jmp loop",
        "expect_org": 0xC000,
        "expect_bytes": [0xEE, 0x20, 0xD0, 0x4C, 0x00, 0xC0],
        "expect_errors": 0,
    },
    {
        "name": "local labels",
        "source": ".org $c000\nmain:\n  lda #0\n.loop:\n  sta $d020\n  beq .loop\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0x8D, 0x20, 0xD0, 0xF0, 0xFB, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "label on same line as instruction",
        "source": ".org $c000\nstart: lda #$ff\n       rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0xFF, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "decimal immediate",
        "source": ".org $c000\n  lda #42\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x2A, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "expression in operand",
        "source": ".const base $d000\n.org $c000\n  lda base+$20\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xAD, 0x20, 0xD0, 0x60],
        "expect_errors": 0,
    },
    {
        "name": ".db directive",
        "source": ".org $c000\n.db $41, $42, $43, 0",
        "expect_org": 0xC000,
        "expect_bytes": [0x41, 0x42, 0x43, 0x00],
        "expect_errors": 0,
    },
    {
        "name": ".dw directive",
        "source": ".org $c000\n.dw $1234, $5678",
        "expect_org": 0xC000,
        "expect_bytes": [0x34, 0x12, 0x78, 0x56],
        "expect_errors": 0,
    },
    {
        "name": ".res directive",
        "source": ".org $c000\n.res 4, $ea\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xEA, 0xEA, 0xEA, 0xEA, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "zp vs abs from constant width",
        "source": ".const zpvar $42\n.const absvar $0042\n.org $c000\n  lda zpvar\n  lda absvar",
        "expect_org": 0xC000,
        "expect_bytes": [0xA5, 0x42, 0xAD, 0x42, 0x00],
        "expect_errors": 0,
    },
    {
        "name": "comment only lines",
        "source": "; this is a comment\n.org $c000\n  ; another comment\n  nop ; inline comment\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xEA, 0x60],
        "expect_errors": 0,
    },
    # ── $A0 tab whitespace ──────────────────────────────────────────
    {
        "name": "tab-indented instruction",
        "source": ".org $c000\n\xa0lda #0\n\xa0rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "tab between mnemonic and operand",
        "source": ".org $c000\n  lda\xa0#0\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "tab after hash prefix",
        "source": ".org $c000\n  lda #\xa0$42\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x42, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "tab after open paren",
        "source": ".org $c000\n  lda (\xa0$42),y\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xB1, 0x42, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "tab in .const directive",
        "source": ".const\xa0border\xa0$d020\n.org $c000\n  lda border\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xAD, 0x20, 0xD0, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "tab in expression spaces",
        "source": ".org $c000\n  lda #$10\xa0+\xa0$20\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x30, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "tab before label definition",
        "source": ".org $c000\n\xa0start:\n\xa0lda #0\n\xa0rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "mixed spaces and tabs",
        "source": ".org $c000\n \xa0 lda\xa0 #0\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x00, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "local label after branch",
        "source": ".org $8000\nmain: ldx #20\n.l: dex\n  bne .l\n.b: lda #$55\n  rts",
        "expect_org": 0x8000,
        "expect_bytes": [0xA2, 0x14, 0xCA, 0xD0, 0xFD, 0xA9, 0x55, 0x60],
        "expect_errors": 0,
    },
    # ── Blank lines (regression: old stub treated \n\n as EOF) ──
    {
        "name": "single blank line between sections",
        "source": ".org $c000\n  lda #$42\n\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x42, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "multiple consecutive blank lines",
        "source": ".org $c000\n  lda #$42\n\n\n\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x42, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "blank line before .org",
        "source": "\n.org $c000\n  rts",
        "expect_org": 0xC000,
        "expect_bytes": [0x60],
        "expect_errors": 0,
    },
    {
        "name": "blank lines around label block",
        "source": ".org $c000\n\nmain:\n\n  lda #$42\n\n  rts\n\nend:",
        "expect_org": 0xC000,
        "expect_bytes": [0xA9, 0x42, 0x60],
        "expect_errors": 0,
    },
    {
        "name": "hello-world style (blank between sections)",
        "source": (
            ".cpu 6510\n"
            ".const chrout $ffd2\n"
            ".org $6000\n"
            "\n"
            "main:\n"
            "  ldx #0\n"
            ".lp:\n"
            "  lda msg,x\n"
            "  beq .done\n"
            "  jsr chrout\n"
            "  inx\n"
            "  bne .lp\n"
            ".done:\n"
            "  rts\n"
            "\n"
            "msg:\n"
            '  .str "hello"\n'
            "  .db $00"
        ),
        "expect_org": 0x6000,
        "expect_bytes": [
            0xA2, 0x00,             # ldx #0
            0xBD, 0x0E, 0x60,       # lda msg,x
            0xF0, 0x06,             # beq .done
            0x20, 0xD2, 0xFF,       # jsr chrout
            0xE8,                   # inx
            0xD0, 0xF5,             # bne .lp
            0x60,                   # rts
            0x48, 0x45, 0x4C, 0x4C, 0x4F,  # "hello"
            0x00,                   # NUL terminator
        ],
        "expect_errors": 0,
    },
    {
        "name": ".bas SYS only",
        "source": ".org $0801\n.bas\n  nop",
        "expect_org": 0x0801,
        # Layout: link(2) + linenum 1(2) + SYS($9E) + "2062"(4) + NUL + $0000(2)
        # = 12 bytes.  SYS address = $0801 + 12 = $080D = 2061... let's compute:
        # base=8, addr=$0801+8+D.  D=4 → addr=$080D=2061 (4 digits, consistent).
        # link → $080D - 2 = $080B
        "expect_bytes": [
            0x0B, 0x08,             # link pointer → $080B
            0x01, 0x00,             # line number 1
            0x9E,                   # SYS token
            0x32, 0x30, 0x36, 0x31, # "2061"
            0x00,                   # line terminator
            0x00, 0x00,             # end of BASIC
            0xEA,                   # nop (user code starts here at $080D)
        ],
        "expect_errors": 0,
    },
    {
        "name": ".bas with REM",
        "source": '.org $0801\n.bas "HI"\n  nop',
        "expect_org": 0x0801,
        # REM line: link(2) + linenum 0(2) + REM($8F) + "HI"(2) + NUL = 8 bytes
        # SYS line: link(2) + linenum 1(2) + SYS($9E) + digits + NUL = 6+D
        # end: $0000 = 2 bytes
        # total = 8 + 6 + D + 2 = 16 + D
        # base=14+2=16, addr=$0801+16+D.  D=4 → addr=$0815=2069 (4 digits, ok)
        # Wait: 14+len+D = 14+2+4 = 20.  addr = $0801+20 = $0815 = 2069.
        # REM link → line 1 = $0801 + 6 + 2 = $0809
        # SYS link → end marker = $0815 - 2 = $0813
        "expect_bytes": [
            0x09, 0x08,             # REM link → $0809
            0x00, 0x00,             # line number 0
            0x8F,                   # REM token
            0x48, 0x49,             # "HI" (PETSCII uppercase H=$48, I=$49)
            0x00,                   # line terminator
            0x13, 0x08,             # SYS link → $0813
            0x01, 0x00,             # line number 1
            0x9E,                   # SYS token
            0x32, 0x30, 0x36, 0x39, # "2069"
            0x00,                   # line terminator
            0x00, 0x00,             # end of BASIC
            0xEA,                   # nop (user code starts at $0815)
        ],
        "expect_errors": 0,
    },
]

ERROR_TESTS = [
    {
        "name": "undefined symbol",
        "source": ".org $c000\n  lda nowhere",
        "expect_min_errors": 1,
    },
    {
        "name": "bad directive",
        "source": ".org $c000\n.bogus",
        "expect_min_errors": 1,
    },
]


# ── Parametrised tests ────────────────────────────────────────────────────────

@pytest.mark.parametrize("tc", MANUAL_TESTS, ids=lambda t: t["name"])
def test_assemble(as_syms, tc):
    org, data, errors = _run(as_syms, tc["source"])
    assert errors == tc["expect_errors"], (
        f"error count: got {errors}, expected {tc['expect_errors']}"
    )
    assert org == tc["expect_org"], (
        f"org: got ${org:04X}, expected ${tc['expect_org']:04X}"
    )
    n = len(tc["expect_bytes"])
    assert data[:n] == tc["expect_bytes"], (
        f"bytes: got {bytes(data[:n]).hex()} expected {bytes(tc['expect_bytes']).hex()}"
    )


@pytest.mark.parametrize("tc", ERROR_TESTS, ids=lambda t: t["name"])
def test_errors(as_syms, tc):
    _, _, errors = _run(as_syms, tc["source"])
    assert errors >= tc["expect_min_errors"], (
        f"expected >= {tc['expect_min_errors']} errors, got {errors}"
    )


def _run_and_lookup(as_syms, source, sym):
    """Run assembly, then call sym_lookup on sym.  Returns (data, sym_val)."""
    cpu = MPU()
    mem = cpu.memory
    as_syms.load_into(mem)
    encoded = _petscii(source)
    for i, b in enumerate(encoded):
        mem[as_syms.test_src_buf + i] = b
    cpu.sp = 0xFF
    mem[0x01FF] = 0xFF
    mem[0x01FE] = 0xFE
    cpu.sp = 0xFD
    cpu.pc = as_syms.asm_src_test_entry
    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            break
        cpu.step()
    else:
        raise TimeoutError("assembly exceeded step limit")
    org = mem[as_syms.asm_org] | (mem[as_syms.asm_org + 1] << 8)
    size = mem[as_syms.asm_size] | (mem[as_syms.asm_size + 1] << 8)
    data = list(mem[org: org + size])

    # Look up symbol addresses from map file
    exports = {}
    in_exports = False
    for line in (BUILD / "asm_src_test.map").read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            if line.strip() == "":
                break
            for name, addr in re.findall(r"(\w+)\s+([0-9a-fA-F]{6})\s+\w+", line):
                exports[name] = int(addr, 16)

    sym_lookup_addr = exports["sym_lookup"]
    sym_name_zp = exports["sym_name"]
    sym_val_zp = exports["sym_val"]

    # Write symbol name as PETSCII NUL-terminated string at a scratch area
    scratch = 0x0300  # safe scratch area
    sym_pet = _petscii(sym)  # includes trailing NUL
    for i, b in enumerate(sym_pet):
        mem[scratch + i] = b

    # Set sym_name ZP pointer
    mem[sym_name_zp] = scratch & 0xFF
    mem[sym_name_zp + 1] = scratch >> 8

    # Call _sym_lookup: returns C=0 found (val in sym_val), C=1 not found
    cpu.sp = 0xFF
    mem[0x01FF] = 0xFF
    mem[0x01FE] = 0xFE
    cpu.sp = 0xFD
    cpu.pc = sym_lookup_addr
    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            break
        cpu.step()
    else:
        raise TimeoutError("sym_lookup exceeded step limit")
    found = not (cpu.p & 1)  # C flag: 0 = found
    val = mem[sym_val_zp] | (mem[sym_val_zp + 1] << 8) if found else None
    return data, val


def test_local_label_value_after_branch(as_syms):
    """Regression: main.b must be at $8005, not $8004 (off-by-one in pass 0).

    Source layout:
      $8000: A2 14    ldx #20     (main:)
      $8002: CA       dex         (.l:)
      $8003: D0 FD    bne .l
      $8005: A9 55    lda #$55    (.b:)  ← must be $8005
      $8007: 60       rts
    """
    source = ".org $8000\nmain: ldx #20\n.l: dex\n  bne .l\n.b: lda #$55\n  rts"
    data, sym_val = _run_and_lookup(as_syms, source, "main.b")
    assert data == [0xA2, 0x14, 0xCA, 0xD0, 0xFD, 0xA9, 0x55, 0x60]
    assert sym_val == 0x8005, f"main.b should be $8005, got ${sym_val:04X}"


def test_label_after_imm(as_syms):
    """Check: is ldx #20 (2 bytes) causing the off-by-one?"""
    source = ".org $8000\nmain: ldx #20\n.b: rts"
    data, sym_val = _run_and_lookup(as_syms, source, "main.b")
    assert data == [0xA2, 0x14, 0x60]
    assert sym_val == 0x8002, f"main.b should be $8002, got ${sym_val:04X}"


def test_label_after_branch(as_syms):
    """Regression: define_label clobbered Y, corrupting line buffer.

    When a label and instruction share a line (.l: dex), the ':'
    restore after define_label wrote at the wrong Y offset on pass 0,
    overwriting the first chars of the mnemonic.  This caused wrong
    instruction sizes and wrong symbol values for subsequent labels.
    """
    source = ".org $8000\nmain: nop\n.l: dex\n  bne .l\n.b: rts"
    # $8000: EA nop, $8001: CA dex, $8002: D0 FD bne, $8004: 60 rts
    data, sym_val = _run_and_lookup(as_syms, source, "main.b")
    assert data == [0xEA, 0xCA, 0xD0, 0xFD, 0x60]
    _, sym_l = _run_and_lookup(as_syms, source, "main.l")
    assert sym_l == 0x8001, f"main.l should be $8001, got ${sym_l:04X}"
    assert sym_val == 0x8004, f"main.b should be $8004, got ${sym_val:04X}"


def test_label_after_two_imms(as_syms):
    """Check: two immediates before the label."""
    source = ".org $8000\nmain: ldx #20\n  lda #$55\n.b: rts"
    # $8000: A2 14, $8002: A9 55, $8004: 60
    data, sym_val = _run_and_lookup(as_syms, source, "main.b")
    assert data == [0xA2, 0x14, 0xA9, 0x55, 0x60]
    assert sym_val == 0x8004, f"main.b should be $8004, got ${sym_val:04X}"


# ── Direct asm_line calls (single-line REPL `.` command path) ───────────────
#
# asm_line owns its own KERNAL banking.  asm_assemble holds the KERNAL
# banked out across the source-pass batch (kernal_out=1), in which case
# asm_line's inner bank helpers short-circuit; the cases above all
# exercise that path.  These tests drive asm_line *directly* with
# kernal_out=0, exercising the bracketed bank path used by the REPL `.`
# command (repl.s::dot_assemble).
#
# Verifies the asm_line bridge's invariants:
#   - returns the correct byte count
#   - writes the correct bytes to *asm_out
#   - leaves $01 bit 1 = 1 (KERNAL banked back in)
#   - leaves I flag clear (interrupts re-enabled)
#   - leaves kernal_out untouched (still 0)


_AL_TEXT_BUF = 0x2400       # PETSCII text buffer (above test BSS, below heap)
_AL_OUT_BUF  = 0x3000       # output bytes land here
_AL_PC       = 0xC000       # pretend assembled PC


def _direct_asm_line(as_syms, text: str):
    """Call asm_line(text) directly.  Returns (n_bytes, output_bytes, p_after, port01_after, kernal_out_after)."""
    cpu = MPU()
    mem = cpu.memory
    as_syms.load_into(mem)

    # Write PETSCII text into a buffer in main RAM.
    encoded = _petscii(text).rstrip(b'\x00') + b'\x00'  # NUL-terminated, no extras
    for i, b in enumerate(encoded):
        mem[_AL_TEXT_BUF + i] = b

    # Set ZP: asm_pc, asm_out
    mem[as_syms.asm_pc]     = _AL_PC & 0xFF
    mem[as_syms.asm_pc + 1] = (_AL_PC >> 8) & 0xFF
    mem[as_syms.asm_out]    = _AL_OUT_BUF & 0xFF
    mem[as_syms.asm_out + 1] = (_AL_OUT_BUF >> 8) & 0xFF

    # Pre-condition: kernal_out flag = 0 (single-line path, NOT a batch)
    mem[as_syms.kernal_out] = 0

    # Pre-condition: $01 bit 1 = 1 (KERNAL banked in), I flag = 0 (interrupts on)
    mem[0x01] = 0x37        # default 6510 port: KERNAL+BASIC+IO mapped
    cpu.p &= ~0x04          # clear I flag

    # Fake JSR: push sentinel return address
    cpu.sp = 0xFF
    mem[0x01FF] = 0xFF
    mem[0x01FE] = 0xFE
    cpu.sp = 0xFD

    # Set A/X = text pointer, then call asm_line
    cpu.a = _AL_TEXT_BUF & 0xFF
    cpu.x = (_AL_TEXT_BUF >> 8) & 0xFF
    cpu.pc = as_syms.asm_line

    for _ in range(_MAX_STEPS):
        if cpu.pc == 0xFFFF:
            break
        cpu.step()
    else:
        raise TimeoutError(f"asm_line direct call exceeded {_MAX_STEPS} steps")

    n = mem[as_syms.asm_len]
    out = bytes(mem[_AL_OUT_BUF : _AL_OUT_BUF + n])
    return n, out, cpu.p, mem[0x01], mem[as_syms.kernal_out]


class TestAsmLineDirect:
    """Drive asm_line directly with kernal_out=0 — REPL `.` command path."""

    def test_direct_lda_imm(self, as_syms):
        n, out, p, port01, kout = _direct_asm_line(as_syms, "lda #$42")
        assert n == 2
        assert out == bytes([0xA9, 0x42])
        # Bank state restored
        assert (port01 & 0x02) == 0x02, \
            f"$01 bit 1 not set after asm_line: ${port01:02X}"
        # Interrupts re-enabled
        assert (p & 0x04) == 0, \
            f"I flag still set after asm_line: ${p:02X}"
        # kernal_out flag untouched
        assert kout == 0, f"kernal_out clobbered: {kout}"

    def test_direct_sta_abs(self, as_syms):
        n, out, p, port01, kout = _direct_asm_line(as_syms, "sta $d020")
        assert n == 3
        assert out == bytes([0x8D, 0x20, 0xD0])
        assert (port01 & 0x02) == 0x02
        assert (p & 0x04) == 0
        assert kout == 0

    def test_direct_implied(self, as_syms):
        n, out, p, port01, kout = _direct_asm_line(as_syms, "rts")
        assert n == 1
        assert out == bytes([0x60])
        assert (port01 & 0x02) == 0x02
        assert (p & 0x04) == 0
        assert kout == 0

    def test_direct_error_restores_bank(self, as_syms):
        # Garbage mnemonic — asm_line should jmp asm_error, which must
        # also bank the KERNAL back in and re-enable interrupts.
        n, _out, p, port01, kout = _direct_asm_line(as_syms, "xyz")
        assert n == 0, "garbage mnemonic should error"
        assert (port01 & 0x02) == 0x02, \
            f"$01 bit 1 not set after asm_error: ${port01:02X}"
        assert (p & 0x04) == 0, \
            f"I flag still set after asm_error: ${p:02X}"
        assert kout == 0


# ── asm_assemble bank-state regression test ────────────────────────────────
#
# Regression: a previous attempt at asm_assemble's bank-out batch did
#
#     lda #1
#     sta kernal_out
#     jsr kernal_bank_out      ; ← short-circuited because kernal_out=1
#
# After kernal_bank_out was made symmetric (honours kernal_out like
# kernal_bank_in does), the call became a no-op when the flag was set
# first.  KERNAL stayed banked IN for both passes, every KDATA read
# returned ROM bytes, and source assembly produced "bad insn" for
# every line.  py65 didn't catch it because banking has no semantic
# effect there — KDATA tables sit at the same RAM addresses regardless
# of $01 bit 1.
#
# The witness: the test stub's ed_read_line OR's the live $01 into
# _bank_witness on every entry.  In a correct run, KERNAL is banked
# out for the duration of both passes, so every ed_read_line call
# sees $01 bit 1 = 0 and the witness retains 0 in bit 1.  If the
# bug regresses, every call sees $01 bit 1 = 1 and the witness OR's
# it in.

class TestAsmAssembleBankState:
    """Verify asm_assemble actually banks KERNAL out for the source passes."""

    def test_passes_run_banked_out(self, as_syms):
        cpu = MPU()
        mem = cpu.memory
        as_syms.load_into(mem)

        # Pre-set $01 to KERNAL-mapped state ($35 = the C64 default with
        # KERNAL+BASIC+IO).  asm_assemble must clear bit 1 before do_pass
        # runs; ed_read_line then witnesses bit 1 = 0 on every call.
        mem[0x01] = 0x35

        # Tiny source — three instructions are enough to call ed_read_line
        # several times across both passes.
        encoded = _petscii(".org $c000\n  lda #$42\n  sta $d020\n  rts")
        for i, b in enumerate(encoded):
            mem[as_syms.test_src_buf + i] = b

        cpu.sp = 0xFF
        mem[0x01FF] = 0xFF
        mem[0x01FE] = 0xFE
        cpu.sp = 0xFD
        cpu.pc = as_syms.asm_src_test_entry

        for _ in range(_MAX_STEPS):
            if cpu.pc == 0xFFFF:
                break
            cpu.step()
        else:
            raise TimeoutError("asm_assemble exceeded step limit")

        # Sanity: assembly succeeded.
        errors = mem[as_syms.asm_errors] | (mem[as_syms.asm_errors + 1] << 8)
        assert errors == 0, f"asm_assemble reported {errors} errors"

        # Bank witness: $01 at every ed_read_line call OR'd together.
        # If asm_assemble banked out correctly, bit 1 was 0 on every call,
        # so the witness has bit 1 = 0.  If it forgot to bank out, the
        # witness has bit 1 = 1.
        witness = mem[as_syms.bank_witness]
        assert (witness & 0x02) == 0, (
            f"asm_assemble did not bank KERNAL out during passes: "
            f"witness=${witness:02X} (bit 1 should be 0)"
        )

        # And after asm_assemble returns, $01 bit 1 must be set again.
        assert (mem[0x01] & 0x02) == 0x02, (
            f"asm_assemble did not bank KERNAL back in: "
            f"$01=${mem[0x01]:02X}"
        )

        # And kernal_out flag must be cleared on exit.
        assert mem[as_syms.kernal_out] == 0, \
            f"kernal_out flag not cleared on exit: {mem[as_syms.kernal_out]}"
