"""
test_dasm.py — pytest tests for the 6502 disassembler (dasm.s)

Tests every opcode in the 6502/65C02/illegal instruction set by:
1. Placing known instruction bytes at a test address
2. Calling _dasm_insn to render the disassembly to screen RAM
3. Reading screen RAM and converting screen codes back to PETSCII
4. Verifying the mnemonic and operand format match expectations

Also includes round-trip tests: assemble an instruction with the line
assembler, disassemble the resulting bytes, verify the disassembled
output matches the expected canonical form.
"""

import sys
import pathlib
import pytest
from py65.devices.mpu6502 import MPU

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))

from instruction_set import OPCODES, MNEMONICS, MODE_EXAMPLES, ALL_MODES, mne_modes

# ---------------------------------------------------------------------------
# Addressing mode expected output format
# ---------------------------------------------------------------------------
MODE_FMT = {
    'IMP':   '',
    'ACC':   'a',
    'IMM':   '#$%02x',
    'ZP':    '$%02x',
    'ZPX':   '$%02x,x',
    'ZPY':   '$%02x,y',
    'ABS':   '$%04x',
    'ABX':   '$%04x,x',
    'ABY':   '$%04x,y',
    'IND':   '($%04x)',
    'INX':   '($%02x,x)',
    'INY':   '($%02x),y',
    'REL':   '$%04x',
    'ZPI':   '($%02x)',
    'AIX':   '($%04x,x)',
    'ZPREL': '$%02x,$%04x',
}

# Operand length per mode (excluding opcode byte)
MODE_OPLEN = {
    'IMP': 0, 'ACC': 0, 'IMM': 1, 'ZP': 1, 'ZPX': 1, 'ZPY': 1,
    'ABS': 2, 'ABX': 2, 'ABY': 2, 'IND': 2, 'INX': 1, 'INY': 1,
    'REL': 1, 'ZPI': 1, 'AIX': 2, 'ZPREL': 2,
}

# ---------------------------------------------------------------------------
# Test binary build
# ---------------------------------------------------------------------------
BUILD = ROOT / "build"
BIN   = BUILD / "dasm_test.bin"
MAP   = BUILD / "dasm_test.map"

OBJS = [
    ("dasm",            "src/dasm.s"),
    ("dasm_tables",     "src/dasm_tables.s"),
    ("cse_io",          "src/cse_io.s"),
]

def _needs_build():
    if not BIN.exists():
        return True
    bin_mtime = BIN.stat().st_mtime
    for _, src in OBJS:
        p = ROOT / src
        if p.stat().st_mtime > bin_mtime:
            return True
    return False

@pytest.fixture(scope="session")
def binary(tmp_path_factory):
    """Assemble and link the disassembler test binary."""
    import subprocess
    BUILD.mkdir(exist_ok=True)

    if not _needs_build():
        return BIN.read_bytes()

    ca65 = "ca65"
    ld65 = "ld65"
    obj_paths = []

    for name, src in OBJS:
        src_path = ROOT / src
        obj_path = BUILD / f"{name}_dtest.o"
        subprocess.check_call([
            ca65, "--cpu", "6502", str(src_path), "-o", str(obj_path)
        ])
        obj_paths.append(str(obj_path))

    cfg = ROOT / "dev" / "test.cfg"
    subprocess.check_call([
        ld65, "-C", str(cfg)] + obj_paths + [
        "-o", str(BIN), "-m", str(MAP)
    ])
    return BIN.read_bytes()


# ---------------------------------------------------------------------------
# CPU helper
# ---------------------------------------------------------------------------
ENTRY     = 0x0200   # test entry point (from test.cfg)
INSTR_BUF = 0x0300   # where we place instruction bytes
SCREEN    = 0x0400

def parse_map_symbols():
    """Parse ld65 map file for exported symbol addresses."""
    syms = {}
    if MAP.exists():
        for line in MAP.read_text().splitlines():
            # Format: "symbolname             00XXXX RLA"
            parts = line.split()
            if len(parts) >= 2:
                for i, p in enumerate(parts):
                    if len(p) == 6 and all(c in '0123456789ABCDEFabcdef' for c in p):
                        sym_name = parts[i-1] if i > 0 else None
                        if sym_name and not sym_name[0].isdigit():
                            syms[sym_name] = int(p, 16)
    return syms


def make_cpu(binary_data):
    """Create a py65 MPU with the test binary loaded and KERNAL PLOT patched."""
    cpu = MPU()
    # test.cfg layout: ZP at $0000 (256 bytes), RAM at $0200 (rest)
    # Load ZP portion (first 256 bytes → address $0000)
    for i in range(min(256, len(binary_data))):
        cpu.memory[i] = binary_data[i]
    # Load RAM portion (offset 256 → address $0200)
    for i in range(256, len(binary_data)):
        cpu.memory[0x0200 + (i - 256)] = binary_data[i]

    # Parse symbols from map file
    syms = parse_map_symbols()

    # Store key addresses
    cpu._dasm_insn = syms.get('_dasm_insn', 0x0200)

    return cpu

def run_disasm(cpu, instr_bytes):
    """Place instruction bytes and call the disassembler.
    Returns (length, screen_text)."""
    # Place instruction bytes at INSTR_BUF
    for i, b in enumerate(instr_bytes):
        cpu.memory[INSTR_BUF + i] = b
    # Pad with 0 to avoid reading garbage
    for i in range(len(instr_bytes), 4):
        cpu.memory[INSTR_BUF + i] = 0

    # Set pointer at $F0/$F1
    cpu.memory[0xF0] = INSTR_BUF & 0xFF
    cpu.memory[0xF1] = (INSTR_BUF >> 8) & 0xFF

    # Clear screen row 0
    for i in range(40):
        cpu.memory[SCREEN + i] = 0x20

    # Reset CPU state
    cpu.sp = 0xFF
    cpu.pc = ENTRY
    cpu.p = 0  # clear flags

    # Reset cursor to row 0, col 0
    # io_putc uses scr_lo/scr_hi[CUR_ROW] directly, no PLOT needed
    cpu.memory[0xD3] = 0   # CUR_COL
    cpu.memory[0xD6] = 0   # CUR_ROW

    # Call _dasm_insn(__fastcall__): addr in A/X (lo/hi)
    # Push return address to a BRK landing pad at $01F0
    cpu.memory[0x01F0] = 0x00  # BRK
    cpu.sp = 0xFD
    cpu.memory[0x01FF] = 0x01          # hi byte of $01EF
    cpu.memory[0x01FE] = 0xEF          # lo byte of $01EF
    cpu.a = INSTR_BUF & 0xFF           # addr lo
    cpu.x = (INSTR_BUF >> 8) & 0xFF   # addr hi
    cpu.pc = cpu._dasm_insn
    cpu.p = 0

    steps = 0
    max_steps = 100000
    while steps < max_steps:
        cpu.step()
        steps += 1
        if cpu.pc == 0x01F0:
            break

    # Read screen row 0, convert screen codes to PETSCII
    text = []
    for i in range(40):
        sc = cpu.memory[SCREEN + i]
        if sc == 0x20:  # space
            text.append(' ')
        elif sc >= 0x01 and sc <= 0x1A:  # letters A-Z
            text.append(chr(sc + 0x60))  # lowercase ASCII
        elif sc >= 0x30 and sc <= 0x39:  # digits
            text.append(chr(sc))
        elif sc == 0x24:  # '$'
            text.append('$')
        elif sc == 0x28:  # '('
            text.append('(')
        elif sc == 0x29:  # ')'
            text.append(')')
        elif sc == 0x2C:  # ','
            text.append(',')
        elif sc == 0x23:  # '#'
            text.append('#')
        elif sc == 0x2E:  # '.'
            text.append('.')
        elif sc == 0x3F:  # '?'
            text.append('?')
        else:
            text.append(f'[{sc:02x}]')

    return ''.join(text).rstrip()


# ---------------------------------------------------------------------------
# Build the expected disassembly for each opcode
# ---------------------------------------------------------------------------
def build_opcode_expectations():
    """For each opcode 0-255, build (mnemonic, mode, expected_text, instr_bytes)."""
    # Invert OPCODES: opcode_byte → (mne, mode)
    opc_map = {}
    for mne, modes in OPCODES.items():
        for mode, opc in modes.items():
            opc_map[opc] = (mne.lower(), mode)

    results = []
    for opc in range(256):
        if opc not in opc_map:
            # Unknown/undefined opcode
            instr = [opc]
            results.append((opc, '???', 'IMP', '???', instr))
            continue

        mne, mode = opc_map[opc]
        oplen = MODE_OPLEN[mode]

        # Choose representative operand bytes
        if oplen == 0:
            op_bytes = []
        elif oplen == 1:
            if mode == 'REL':
                op_bytes = [0x10]  # +16 offset
            elif mode == 'ZPREL':
                op_bytes = [0x42, 0x10]  # ZP=$42, offset=+16
            else:
                op_bytes = [0x42]
        elif oplen == 2:
            if mode == 'ZPREL':
                op_bytes = [0x42, 0x10]
            else:
                op_bytes = [0x34, 0x12]  # $1234 little-endian

        instr = [opc] + op_bytes

        # Build expected operand string
        if mode == 'IMP':
            expected_op = ''
        elif mode == 'ACC':
            expected_op = 'a'
        elif mode == 'REL':
            # PC is at INSTR_BUF ($0300), offset is signed
            # Target = PC + 2 + signed_offset
            offset = op_bytes[0]
            if offset >= 0x80:
                offset -= 256
            target = (INSTR_BUF + 2 + offset) & 0xFFFF
            expected_op = '$%04x' % target
        elif mode == 'ZPREL':
            zp_val = op_bytes[0]
            offset = op_bytes[1]
            if offset >= 0x80:
                offset -= 256
            target = (INSTR_BUF + 3 + offset) & 0xFFFF
            expected_op = '$%02x,$%04x' % (zp_val, target)
        elif oplen == 1:
            expected_op = MODE_FMT[mode] % op_bytes[0]
        elif oplen == 2:
            val16 = op_bytes[0] | (op_bytes[1] << 8)
            expected_op = MODE_FMT[mode] % val16

        if expected_op:
            expected = f'{mne} {expected_op}'
        else:
            expected = mne

        results.append((opc, mne, mode, expected, instr))

    return results

EXPECTATIONS = build_opcode_expectations()


# ---------------------------------------------------------------------------
# Parametrized test: one test per opcode
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def cpu(binary):
    return make_cpu(binary)


@pytest.mark.parametrize(
    "opc,mne,mode,expected,instr_bytes",
    [(e[0], e[1], e[2], e[3], e[4]) for e in EXPECTATIONS],
    ids=[f"${e[0]:02X}_{e[1]}_{e[2]}" for e in EXPECTATIONS]
)
def test_disasm(cpu, opc, mne, mode, expected, instr_bytes):
    """Test that disassembling the given opcode produces the expected text."""
    text = run_disasm(cpu, instr_bytes)

    # Verify full disassembly (mnemonic + operand)
    assert text == expected, f"${opc:02X}: '{text}' != '{expected}'"


# ---------------------------------------------------------------------------
# Round-trip tests: assemble → disassemble → verify
#
# For each (mnemonic, mode), assemble the canonical operand form, then
# disassemble the resulting bytes and verify the output matches what the
# disassembler should produce for those bytes.
# ---------------------------------------------------------------------------

# Reuse the assembler runner from test_asm_line
from test_asm_line import _run as asm_run, _sc

# Canonical operand per mode: the FIRST entry in MODE_EXAMPLES with
# uppercase letters (what the assembler expects).
# We use specific non-zero operand values so the disassembler output is
# visually distinctive: ZP=$42, ABS=$1234, IMM=$42, REL→target=$0012.
_CANONICAL_ASM = {
    'IMP':   ('',              []),
    'ACC':   ('A',             []),
    'IMM':   ('#$42',          [0x42]),
    'ZP':    ('$42',           [0x42]),
    'ZPX':   ('$42,X',         [0x42]),
    'ZPY':   ('$42,Y',         [0x42]),
    'ABS':   ('$1234',         [0x34, 0x12]),
    'ABX':   ('$1234,X',       [0x34, 0x12]),
    'ABY':   ('$1234,Y',       [0x34, 0x12]),
    'IND':   ('($1234)',       [0x34, 0x12]),
    'INX':   ('($42,X)',       [0x42]),
    'INY':   ('($42),Y',       [0x42]),
    'REL':   ('$0012',         [0x10]),   # PC=$0000, offset=$10 → target=$0012
    'ZPI':   ('($42)',         [0x42]),
    'AIX':   ('($1234,X)',     [0x34, 0x12]),
    'ZPREL': ('$42,$0013',     [0x42, 0x10]),  # PC=$0000, offset=$10 → target=$0013
}

# Expected disassembler output per mode (lowercase, matching dasm output)
_CANONICAL_DASM = {
    'IMP':   '',
    'ACC':   'a',
    'IMM':   '#$42',
    'ZP':    '$42',
    'ZPX':   '$42,x',
    'ZPY':   '$42,y',
    'ABS':   '$1234',
    'ABX':   '$1234,x',
    'ABY':   '$1234,y',
    'IND':   '($1234)',
    'INX':   '($42,x)',
    'INY':   '($42),y',
    'REL':   '$0012',           # target = INSTR_BUF + 2 + $10 = $0312
    'ZPI':   '($42)',
    'AIX':   '($1234,x)',
    'ZPREL': '$42,$0313',       # target = INSTR_BUF + 3 + $10 = $0313
}


def _build_safe_opcodes():
    """Opcodes with identical interpretation in NMOS+illegal and CMOS views."""
    nmos, cmos = {}, {}
    for mne, modes in OPCODES.items():
        _, _, cat = MNEMONICS[mne]
        for mode, opc in modes.items():
            if cat in ('legal', 'illegal'):
                nmos[opc] = (mne, mode)
            if cat in ('legal', 'cmos'):
                cmos[opc] = (mne, mode)
    return {opc for opc in range(256) if nmos.get(opc) and nmos.get(opc) == cmos.get(opc)}

_SAFE_OPCODES = _build_safe_opcodes()


def _build_roundtrip_cases():
    """Build (source, mne, mode, expected_dasm) for each valid mnemonic+mode.
    Only includes opcodes that are unambiguous between NMOS and 65C02."""
    cases = []
    for mne, (profile, cmos_bit, cat) in MNEMONICS.items():
        if cat not in ('legal',):   # only legal for now (safe round-trip)
            continue
        modes = mne_modes(profile, cmos_bit)
        for mode in sorted(modes, key=lambda m: list(ALL_MODES).index(m)):
            opcode = OPCODES[mne].get(mode)
            if opcode is None:
                continue    # Zone D/E digit-encoded
            if opcode not in _SAFE_OPCODES:
                continue    # differs between NMOS and CMOS
            if mode not in _CANONICAL_ASM:
                continue

            asm_src, op_bytes = _CANONICAL_ASM[mode]
            source = f"{mne} {asm_src}".strip()

            # Expected disasm output
            dasm_op = _CANONICAL_DASM[mode]
            # REL/ZPREL targets depend on INSTR_BUF position in disasm test
            if mode == 'REL':
                # Assembled with PC=$0000 → offset=$10 → target=$0012
                # Disassembled from INSTR_BUF=$0300 → target=$0300+2+$10=$0312
                dasm_op = '$0312'
            elif mode == 'ZPREL':
                dasm_op = '$42,$0313'

            expected_mne = mne.lower()
            if dasm_op:
                expected = f'{expected_mne} {dasm_op}'
            else:
                expected = expected_mne

            cases.append((source, opcode, expected_mne, mode, expected, op_bytes))
    return cases

_RT_CASES = _build_roundtrip_cases()


@pytest.mark.parametrize(
    "source,opcode,mne,mode,expected,op_bytes",
    _RT_CASES,
    ids=[f"RT_{c[0]}" for c in _RT_CASES]
)
def test_roundtrip(al_syms, cpu, source, opcode, mne, mode, expected, op_bytes):
    """Assemble an instruction, then disassemble and verify the output."""
    # Step 1: assemble
    assembled = asm_run(al_syms, source, al_cpu=1)
    assert assembled[0] == opcode, (
        f"assembled opcode ${assembled[0]:02X} != expected ${opcode:02X} for '{source}'"
    )

    # Step 2: disassemble the assembled bytes
    text = run_disasm(cpu, list(assembled))

    # Step 3: verify
    assert text == expected, (
        f"round-trip '{source}' → bytes={assembled.hex()} → '{text}' "
        f"(expected '{expected}')"
    )
