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

BUILD = Path(__file__).resolve().parent.parent.parent / "build"


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
        # Regression for the .dw forward-ref PC-advance bug:
        # On pass 0, a `.dw forward_label` operand was undefined →
        # emit_data_bytes tail-jumped to emit_error → silent on pass 0
        # but skipping _emit_word, so asm_pc was NOT advanced.  Any
        # label defined AFTER the .dw got the wrong (low) address;
        # pass 1 then emitted that wrong address into the .dw bytes
        # AND landed jumps/branches at the wrong PC.
        "name": ".dw with forward-ref label (PC advance)",
        "source": ".org $c000\n.dw target\ntarget:\n  rts",
        "expect_org": 0xC000,
        # .dw at $C000 (2 bytes) → target at $C002 → bytes are $02 $C0,
        # then RTS at $C002.
        "expect_bytes": [0x02, 0xC0, 0x60],
        "expect_errors": 0,
    },
    {
        "name": ".db with forward-ref label (PC advance)",
        "source": ".org $c000\n.db <target\ntarget:\n  rts",
        "expect_org": 0xC000,
        # .db at $C000 (1 byte) → target at $C001 → byte is $01 (lo of $C001),
        # then RTS at $C001.
        "expect_bytes": [0x01, 0x60],
        "expect_errors": 0,
    },
    {
        "name": ".dw forward + jmp across (PC advance)",
        "source": ".org $c000\n.dw target\n  jmp target\ntarget:\n  rts",
        "expect_org": 0xC000,
        # Layout: .dw (2) + jmp abs (3) + rts (1).  target = $C005.
        # .dw bytes: $05 $C0; jmp: $4C $05 $C0; rts: $60.
        "expect_bytes": [0x05, 0xC0, 0x4C, 0x05, 0xC0, 0x60],
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
        # Always 5 decimal digits.  Stub = 13 bytes (8 + 5).
        # SYS address = $0801 + 13 = $080E = 2062.
        # link → $080E - 2 = $080C.
        "expect_bytes": [
            0x0C, 0x08,             # link pointer → $080C
            0x00, 0x00,             # line number 0
            0x9E,                   # SYS token
            0x30, 0x32, 0x30, 0x36, 0x32,  # "02062" (5 digits)
            0x00,                   # NUL terminator
            0x00, 0x00,             # end of BASIC
            0xEA,                   # nop (user code starts at $080E)
        ],
        "expect_errors": 0,
    },
    {
        "name": ".bas with REM",
        "source": '.org $0801\n.bas "HI"\n  nop',
        "expect_org": 0x0801,
        # Single-line: `0 SYS NNNNN:REM HI`
        # Stub = 16 + 2 (len "HI") = 18 bytes.
        # SYS address = $0801 + 18 = $0813 = 2067.
        # Link → end marker = $0813 - 2 = $0811.
        "expect_bytes": [
            0x11, 0x08,             # link → $0811
            0x00, 0x00,             # line number 0
            0x9E,                   # SYS token
            0x30, 0x32, 0x30, 0x36, 0x37,  # "02067" (5 digits)
            0x3A,                   # ':'
            0x8F,                   # REM token
            0x20,                   # ' ' (space after REM)
            0x48, 0x49,             # "HI" (PETSCII H=$48, I=$49)
            0x00,                   # NUL terminator
            0x00, 0x00,             # end of BASIC
            0xEA,                   # nop (user code starts at $0813)
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
    {
        # .res's count drives pass-0 size, so a forward-ref count is
        # rejected vocally on BOTH passes (not silent on pass 0 like
        # other expression errors).  Without this rule, pass 0 sizes
        # the directive as 0 bytes and any label defined after it
        # drifts; the user's binary is silently wrong.  See
        # asm_src.s::emit_reserve and _vocal_fwd_err.
        "name": ".res with forward-ref count rejects vocally",
        "source": ".org $c000\n.res N\ntarget:\n  rts\n.const N $04",
        # Both passes emit ";? : fwd ref" → asm_errors >= 2 (one per
        # pass); the strict count isn't important — we just need the
        # error to be VISIBLE (silent pass-0 drift is the bug).
        "expect_min_errors": 1,
    },
    {
        "name": ".align with forward-ref boundary rejects vocally",
        "source": ".org $c000\n.align M\ntarget:\n  rts\n.const M $04",
        "expect_min_errors": 1,
    },
    {
        "name": ".res fill expr with forward-ref rejects vocally",
        "source": ".org $c000\n.res 4, FILL\n.const FILL $42",
        "expect_min_errors": 1,
    },
]


# ── Parametrised tests ────────────────────────────────────────────────────────

@pytest.mark.parametrize("tc", MANUAL_TESTS, ids=lambda t: t["name"])
def test_assemble(as_syms, tc):
    if "xfail" in tc:
        pytest.xfail(tc["xfail"])
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


# ── Segment tracking tests ───────────────────────────────────────────────────

def _run_segs(as_syms, source: str):
    """Run assembly and return (org, data, errors, seg_info).

    seg_info is a dict with min_pc and max_pc (exclusive).
    """
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
        raise TimeoutError(f"exceeded {_MAX_STEPS} steps")

    org    = mem[as_syms.asm_org] | (mem[as_syms.asm_org + 1] << 8)
    size   = mem[as_syms.asm_size] | (mem[as_syms.asm_size + 1] << 8)
    errors = mem[as_syms.asm_errors] | (mem[as_syms.asm_errors + 1] << 8)
    data   = list(mem[org : org + size])

    min_pc = mem[as_syms.min_pc] | (mem[as_syms.min_pc + 1] << 8)
    max_pc = mem[as_syms.max_pc] | (mem[as_syms.max_pc + 1] << 8)

    seg_info = {"min_pc": min_pc, "max_pc": max_pc}
    return org, data, errors, seg_info


class TestSegmentTracking:
    """Verify min_pc, max_pc, asm_org after assembly."""

    def test_single_org(self, as_syms):
        """Single .org block: min/max bracket the segment."""
        _, _, errors, seg = _run_segs(as_syms, ".org $c000\n  nop\n  rts")
        assert errors == 0
        assert seg["min_pc"] == 0xC000
        assert seg["max_pc"] == 0xC002

    def test_two_orgs(self, as_syms):
        """Two .org blocks: min = lowest, max = highest."""
        source = ".org $c000\n  nop\n.org $d000\n  lda #$42\n  rts"
        _, _, errors, seg = _run_segs(as_syms, source)
        assert errors == 0
        assert seg["min_pc"] == 0xC000
        assert seg["max_pc"] == 0xD003

    def test_asm_org_not_clobbered(self, as_syms):
        """asm_org reflects the first .org, not the last."""
        source = ".org $c000\n  nop\n.org $d000\n  rts"
        org, _, errors, _ = _run_segs(as_syms, source)
        assert errors == 0
        assert org == 0xC000, f"asm_org should be $C000, got ${org:04X}"

    def test_bas_implicit_org(self, as_syms):
        """'.bas' opens a segment at $0801."""
        source = ".bas\n  nop"
        _, _, errors, seg = _run_segs(as_syms, source)
        assert errors == 0
        assert seg["min_pc"] == 0x0801

    def test_t_org_scenario(self, as_syms):
        """.bas + two .org blocks — the t-org,s test case."""
        source = '.bas "hello"\n.org $1000\nmain:\n  lda #$55\n  rts\n.org $2000\ndata:\n  .db 1,2,3,4'
        _, _, errors, seg = _run_segs(as_syms, source)
        assert errors == 0
        assert seg["min_pc"] == 0x0801
        assert seg["max_pc"] == 0x2004

    def test_empty_org_suppressed(self, as_syms):
        """Consecutive .org with no code — min/max from non-empty segment."""
        source = ".org $c000\n.org $d000\n  nop"
        _, _, errors, seg = _run_segs(as_syms, source)
        assert errors == 0
        assert seg["min_pc"] == 0xD000
        assert seg["max_pc"] == 0xD001


# ── Kernel stack-depth measurement (B2) ────────────────────────
#
# The assembler pipeline (asm_src → asm_line → mode_parse →
# expr_eval → recursive descent) is documented as the deepest
# kernel call chain in the system; see userland_contract.md §
# Kernel stack budget.  The user contract is 64 bytes of
# headroom.  These tests fill the stack with a sentinel byte,
# run the worst-case assembly paths we can construct, then
# measure how deep the kernel actually pushed.  The watermark
# feeds the B3 runtime warning threshold and flags any future
# refactor that grows the chain past the contract.

SENTINEL = 0xA5


def _stack_watermark(cpu) -> int:
    """Return lowest stack address ($0100..$01FF) with a non-sentinel byte.

    The watermark represents the deepest point the stack reached
    during the run.  Higher = more headroom used.  (Addresses
    below watermark are untouched sentinel.)
    """
    for addr in range(0x0100, 0x0200):
        if cpu.memory[addr] != SENTINEL:
            return addr
    return 0x0200   # whole stack untouched


def _run_with_watermark(as_syms, source: str):
    """Run the two-pass assembler; return (errors, kernel_depth_bytes)."""
    cpu = MPU()
    mem = cpu.memory
    as_syms.load_into(mem)
    encoded = _petscii(source)
    for i, b in enumerate(encoded):
        mem[as_syms.test_src_buf + i] = b

    # Fresh SP = $FF; fill entire stack page with sentinel except the
    # two bytes we're about to use for the fake return address.
    for addr in range(0x0100, 0x0200):
        mem[addr] = SENTINEL
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

    errors = mem[as_syms.asm_errors] | (mem[as_syms.asm_errors + 1] << 8)
    watermark = _stack_watermark(cpu)
    # Initial entry frame: 2 bytes for fake return address at $01FE/$01FF.
    # kernel_depth counts from the top of stack ($0200) down to watermark.
    kernel_depth = 0x0200 - watermark
    return errors, kernel_depth


class TestKernelStackDepth:
    """B2: characterise the assembler pipeline's stack usage and
    guard against future depth regressions.  These numbers are the
    stack eaten by asm_src → asm_line → mode_parse → expr_eval
    (recursive descent) — the deepest documented kernel path — when
    invoked from a fresh SP.  They DO NOT directly reflect the
    reg_sp-based user contract (userland_contract.md § Kernel stack
    budget), which measures kernel re-entry depth starting from
    main_loop's SP, not top-of-stack.

    The ceilings here are deliberately generous: the goal is to
    catch unbounded-growth regressions, not to pin exact numbers.
    Current worst case is ~130 B at 12 levels of paren nesting.
    """

    # Regression ceilings — tuned to current worst case + ~30 B margin.
    CEILING_TYPICAL = 80    # simple/realistic programs
    CEILING_DEEP    = 160   # degenerate nested expressions

    def test_trivial_source(self, as_syms):
        """Baseline: minimum-content assembly."""
        errors, depth = _run_with_watermark(as_syms, ".org $c000\n  rts")
        assert errors == 0
        assert depth < self.CEILING_TYPICAL, \
            f"trivial depth {depth} exceeds ceiling {self.CEILING_TYPICAL}"

    def test_realistic_program(self, as_syms):
        """A representative short program — typical user workload."""
        source = (
            ".cpu 6510\n"
            ".const chrout $ffd2\n"
            ".const border $d020\n"
            ".org $c000\n"
            "main:\n"
            "  lda #$07\n"
            "  sta border\n"
            "  ldx #0\n"
            ".lp:\n"
            "  lda msg,x\n"
            "  beq .done\n"
            "  jsr chrout\n"
            "  inx\n"
            "  bne .lp\n"
            ".done:\n"
            "  rts\n"
            "msg:\n"
            '  .str "hello, world!", 0\n'
        )
        errors, depth = _run_with_watermark(as_syms, source)
        assert errors == 0
        assert depth < self.CEILING_TYPICAL, \
            f"realistic depth {depth} exceeds ceiling {self.CEILING_TYPICAL}"

    def test_deep_nested_parens(self, as_syms):
        """Degenerate: plain 8-level paren nesting.  Exercises
        parse_expr → parse_primary recursion down to the literal."""
        expr = "(" * 8 + "42" + ")" * 8
        src  = f".org $c000\n  lda #<{expr}\n  rts"
        errors, depth = _run_with_watermark(as_syms, src)
        assert errors == 0, f"unexpected errors: {errors}"
        assert depth < self.CEILING_DEEP, \
            f"8-paren depth {depth} exceeds ceiling {self.CEILING_DEEP}"

    @pytest.mark.parametrize("levels", [1, 3, 5, 8])
    def test_depth_scales_with_nesting(self, as_syms, levels):
        """Characterise: deeper nesting uses proportionally more
        stack.  Bounded by CEILING_DEEP for regression protection."""
        expr = "(" * levels + "42" + ")" * levels
        src  = f".org $c000\n  lda #<{expr}\n  rts"
        errors, depth = _run_with_watermark(as_syms, src)
        assert errors == 0
        assert depth < self.CEILING_DEEP, \
            f"levels={levels} depth={depth} exceeds ceiling {self.CEILING_DEEP}"


# ── Truncation warning regression ─────────────────────────────────────────
#
# Source lines are capped at 39 chars by ed_read_line (one less than the
# 40-col cap so the truncation tag fits a final byte).  Lines at exactly
# 39 chars are flagged with `;<line>: truncated` on pass 1.  Pre-fix
# (asm_src.s do_pass), `txa` clobbered A with X (=0 for non-EOF) BEFORE
# the saved-for-truncation `pha`, so the `cmp #39` always saw 0 and the
# warning was never emitted.  The fix saves `pha` first, with a
# `@done_pop` trampoline pulling the pushed length on the EOF exit.
#
# Witness: dev/asm_src_test_stub.s::log_open increments _warn_witness on
# every `log_open(LOG_WARN)` call.  Truncation is the only path that
# emits LOG_WARN inside asm_src; we can compare counts directly.

class TestTruncationWarning:
    """Regression for the silent-truncation bug fixed 2026-04-28."""

    def _assemble(self, as_syms, source):
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
            raise TimeoutError(f"exceeded {_MAX_STEPS} steps")
        return mem[as_syms.warn_witness]

    def test_38_char_line_no_warning(self, as_syms):
        """A 38-char source line stays under the cap → no warning."""
        # ".org $c000\n" + 38-char comment line (";xxx..." 38 total)
        line = ";" + "x" * 37        # 38 chars total
        src = ".org $c000\n" + line + "\n  rts"
        warn_count = self._assemble(as_syms, src)
        assert warn_count == 0, \
            f"38-char line should not trigger truncation; got {warn_count}"

    def test_39_char_line_emits_warning(self, as_syms):
        """A 39-char source line hits ed_read_line's cap → exactly one
        ;<line>: truncated warning.  Pre-fix this was 0 (silent bug)."""
        line = ";" + "x" * 38        # 39 chars total
        src = ".org $c000\n" + line + "\n  rts"
        warn_count = self._assemble(as_syms, src)
        assert warn_count == 1, \
            f"39-char line should emit one truncation warning; got {warn_count}"

    def test_two_long_lines_two_warnings(self, as_syms):
        """Two 39-char lines should each fire."""
        line = ";" + "x" * 38
        src = ".org $c000\n" + line + "\n" + line + "\n  rts"
        warn_count = self._assemble(as_syms, src)
        assert warn_count == 2, \
            f"two 39-char lines should emit two warnings; got {warn_count}"
