"""
test_dasm.py — Exhaustive disassembler tests (buffer-based).

Tests all 256 opcodes × 3 CPU modes (6502, 6510, 65C02).
The disassembler writes to dasm_buf (NUL-terminated PETSCII).
No screen RAM, no cursor state — reads the buffer directly.
"""

import sys
import pathlib
import pytest
from py65.devices.mpu6502 import MPU

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent / "dev"))
from instruction_set import OPCODES, MNEMONICS

# ── CPU modes ────────────────────────────────────────────────────
CPU_6502  = 0   # legal only
CPU_6510  = 1   # legal + illegal
CPU_65C02 = 2   # legal + CMOS

MODE_LEN = {
    'IMP': 1, 'ACC': 1, 'IMM': 2, 'ZP': 2, 'ZPX': 2, 'ZPY': 2,
    'ABS': 3, 'ABX': 3, 'ABY': 3, 'IND': 3, 'INX': 2, 'INY': 2,
    'REL': 2, 'ZPI': 2, 'AIX': 3, 'ZPREL': 3,
}

# ── Operand formatters ───────────────────────────────────────────
def fmt_operand(mode, operand_bytes, insn_addr):
    b = operand_bytes
    if mode == 'IMP':   return ''
    if mode == 'ACC':   return 'A'
    if mode == 'IMM':   return f'#${b[0]:02X}'
    if mode == 'ZP':    return f'${b[0]:02X}'
    if mode == 'ZPX':   return f'${b[0]:02X},X'
    if mode == 'ZPY':   return f'${b[0]:02X},Y'
    if mode == 'ABS':   return f'${b[1]:02X}{b[0]:02X}'
    if mode == 'ABX':   return f'${b[1]:02X}{b[0]:02X},X'
    if mode == 'ABY':   return f'${b[1]:02X}{b[0]:02X},Y'
    if mode == 'IND':   return f'(${b[1]:02X}{b[0]:02X})'
    if mode == 'INX':   return f'(${b[0]:02X},X)'
    if mode == 'INY':   return f'(${b[0]:02X}),Y'
    if mode == 'ZPI':   return f'(${b[0]:02X})'
    if mode == 'AIX':   return f'(${b[1]:02X}{b[0]:02X},X)'
    if mode == 'REL':
        off = b[0] if b[0] < 0x80 else b[0] - 0x100
        target = (insn_addr + 2 + off) & 0xFFFF
        return f'${target:04X}'
    if mode == 'ZPREL':
        off = b[1] if b[1] < 0x80 else b[1] - 0x100
        target = (insn_addr + 3 + off) & 0xFFFF
        return f'${b[0]:02X},${target:04X}'
    return ''

# ── 65C02 additions ──────────────────────────────────────────────
CMOS_ADDITIONS = {
    0x80: ('BRA', 'REL'),
    0x04: ('TSB', 'ZP'),  0x0C: ('TSB', 'ABS'),
    0x14: ('TRB', 'ZP'),  0x1C: ('TRB', 'ABS'),
    0x64: ('STZ', 'ZP'),  0x74: ('STZ', 'ZPX'),
    0x9C: ('STZ', 'ABS'), 0x9E: ('STZ', 'ABX'),
    0x34: ('BIT', 'ZPX'), 0x3C: ('BIT', 'ABX'), 0x89: ('BIT', 'IMM'),
    0x7C: ('JMP', 'AIX'),
    0x1A: ('INC', 'ACC'), 0x3A: ('DEC', 'ACC'),
    0x5A: ('PHY', 'IMP'), 0x7A: ('PLY', 'IMP'),
    0xDA: ('PHX', 'IMP'), 0xFA: ('PLX', 'IMP'),
    0x12: ('ORA', 'ZPI'), 0x32: ('AND', 'ZPI'),
    0x52: ('EOR', 'ZPI'), 0x72: ('ADC', 'ZPI'),
    0x92: ('STA', 'ZPI'), 0xB2: ('LDA', 'ZPI'),
    0xD2: ('CMP', 'ZPI'), 0xF2: ('SBC', 'ZPI'),
}
for d in range(8):
    CMOS_ADDITIONS[0x07 + d * 0x10] = (f'RMB{d}', 'ZP')
    CMOS_ADDITIONS[0x87 + d * 0x10] = (f'SMB{d}', 'ZP')
    CMOS_ADDITIONS[0x0F + d * 0x10] = (f'BBR{d}', 'ZPREL')
    CMOS_ADDITIONS[0x8F + d * 0x10] = (f'BBS{d}', 'ZPREL')


# ── Build per-CPU maps ───────────────────────────────────────────
CMOS_ONLY_MODES = {'ZPI', 'AIX'}  # modes that exist only on 65C02

# Specific opcodes that are 65C02-only despite the mnemonic being "legal"
CMOS_ONLY_OPCODES = set(CMOS_ADDITIONS.keys())

def build_cpu_maps():
    maps = {CPU_6502: {}, CPU_6510: {}, CPU_65C02: {}}
    for mne, modes in OPCODES.items():
        cat = MNEMONICS[mne][2]
        for mode, opc in modes.items():
            if opc is None:
                continue
            is_cmos_only = mode in CMOS_ONLY_MODES or opc in CMOS_ONLY_OPCODES
            if cat == 'legal':
                if not is_cmos_only:
                    maps[CPU_6502][opc]  = (mne, mode)
                    maps[CPU_6510][opc]  = (mne, mode)
                maps[CPU_65C02][opc] = (mne, mode)
            elif cat == 'illegal':
                maps[CPU_6510][opc]  = (mne, mode)
            elif cat == 'cmos':
                maps[CPU_65C02][opc] = (mne, mode)
    for opc, (mne, mode) in CMOS_ADDITIONS.items():
        maps[CPU_65C02][opc] = (mne, mode)
    return maps

CPU_MAPS = build_cpu_maps()

INSN_ADDR = 0x0B00  # Must be above CODE+RODATA+BSS (ends ~$095E)
TEST_OPERANDS = [0x42, 0x34]  # arbitrary operand bytes


def expected_string(cpu, opc):
    if opc not in CPU_MAPS[cpu]:
        return '...'
    mne, mode = CPU_MAPS[cpu][opc]
    operand = fmt_operand(mode, TEST_OPERANDS, INSN_ADDR)
    if operand:
        return f'{mne} {operand}'
    return mne


# ── Parametrize ──────────────────────────────────────────────────
def gen_cases():
    cases = []
    for cpu in [CPU_6502, CPU_6510, CPU_65C02]:
        for opc in range(256):
            exp = expected_string(cpu, opc)
            tag = ['6502', '6510', '65C02'][cpu]
            cases.append(pytest.param(cpu, opc, exp, id=f'{tag}-${opc:02X}'))
    return cases


@pytest.mark.parametrize("cpu,opc,exp", gen_cases())
def test_dasm(dasm_syms, cpu, opc, exp):
    """Disassemble one opcode and compare with expected output."""
    mpu = MPU()
    mem = bytearray(0x10000)
    dasm_syms.load_into(mem)

    # Place instruction at $0300
    mem[INSN_ADDR]     = opc
    mem[INSN_ADDR + 1] = TEST_OPERANDS[0]
    mem[INSN_ADDR + 2] = TEST_OPERANDS[1]

    # Set CPU mode
    mem[dasm_syms.al_cpu] = cpu

    # Place a BRK at return address so we know when done.
    # Must be ABOVE all segments (CODE+RODATA+BSS can extend past $0A00).
    RETURN_ADDR = 0x0F00
    mem[RETURN_ADDR] = 0x00  # BRK

    mpu.memory = mem
    mpu.sp = 0xFF
    # Push return address - 1 for the stub's RTS
    mpu.sp -= 1
    mem[0x01FF] = (RETURN_ADDR - 1) >> 8
    mpu.sp -= 1
    mem[0x01FE] = (RETURN_ADDR - 1) & 0xFF

    mpu.pc = dasm_syms.dasm_test_entry

    # Execute until PC hits RETURN_ADDR (BRK)
    steps = 0
    while steps < 10000:
        if mpu.pc == RETURN_ADDR:
            break
        mpu.step()
        steps += 1
    else:
        pytest.fail(f"Didn't return after 10000 steps (PC=${mpu.pc:04X})")

    # Read dasm_buf
    buf = dasm_syms.dasm_buf
    result = ''
    for i in range(24):
        ch = mem[buf + i]
        if ch == 0:
            break
        result += chr(ch)

    # Compare (normalize to uppercase for PETSCII)
    assert result.upper().rstrip() == exp.upper(), \
        f'${opc:02X} cpu={cpu}: got {result!r}, expected {exp!r}'

    # Check instruction length
    if opc in CPU_MAPS[cpu]:
        _, mode = CPU_MAPS[cpu][opc]
        assert mpu.a == MODE_LEN[mode], \
            f'${opc:02X} cpu={cpu}: length={mpu.a}, expected {MODE_LEN[mode]}'
    else:
        assert mpu.a == 1, f'${opc:02X} cpu={cpu}: unknown should be length 1'
