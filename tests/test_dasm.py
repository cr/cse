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
    mem[dasm_syms.asm_cpu] = cpu

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


# ── GAP 3: Boundary operand tests ────────────────────────────────────────────
# Test with operands $00, $FF, $80 to catch sign extension and byte-order bugs.

BOUNDARY_OPERANDS = [
    ([0x00, 0x00], 'zero'),
    ([0xFF, 0xFF], 'all-ones'),
    ([0x80, 0x7F], 'sign-bit'),
]

def _boundary_expected(cpu, opc, operands):
    if opc not in CPU_MAPS[cpu]:
        return '...'
    mne, mode = CPU_MAPS[cpu][opc]
    op_str = fmt_operand(mode, operands, INSN_ADDR)
    if op_str:
        return f'{mne} {op_str}'
    return mne

_BOUNDARY_CASES = []
for operands, tag in BOUNDARY_OPERANDS:
    # Test a representative set of opcodes covering all addressing modes
    _REPR_OPCODES = [
        0xA9,  # LDA #imm
        0xA5,  # LDA zp
        0xB5,  # LDA zp,x
        0xAD,  # LDA abs
        0xBD,  # LDA abs,x
        0xB9,  # LDA abs,y
        0xA1,  # LDA (zp,x)
        0xB1,  # LDA (zp),y
        0x6C,  # JMP (abs)
        0x90,  # BCC rel (sign-sensitive!)
        0x4C,  # JMP abs
    ]
    for opc in _REPR_OPCODES:
        exp = _boundary_expected(CPU_6510, opc, operands)
        _BOUNDARY_CASES.append(
            pytest.param(opc, operands, exp, id=f'{tag}-${opc:02X}')
        )

@pytest.mark.parametrize("opc,operands,exp", _BOUNDARY_CASES)
def test_dasm_boundary_operands(dasm_syms, opc, operands, exp):
    """Disassemble with boundary operand values ($00, $FF, $80)."""
    mpu = MPU()
    mem = bytearray(0x10000)
    dasm_syms.load_into(mem)

    mem[INSN_ADDR]     = opc
    mem[INSN_ADDR + 1] = operands[0]
    mem[INSN_ADDR + 2] = operands[1]
    mem[dasm_syms.asm_cpu] = CPU_6510

    RETURN_ADDR = 0x0F00
    mem[RETURN_ADDR] = 0x00
    mpu.memory = mem
    mpu.sp = 0xFF
    mpu.sp -= 1; mem[0x01FF] = (RETURN_ADDR - 1) >> 8
    mpu.sp -= 1; mem[0x01FE] = (RETURN_ADDR - 1) & 0xFF

    mpu.pc = dasm_syms.dasm_test_entry
    for _ in range(10000):
        if mpu.pc == RETURN_ADDR: break
        mpu.step()
    else:
        pytest.fail(f"Timeout ${opc:02X}")

    buf = dasm_syms.dasm_buf
    result = ''
    for i in range(24):
        ch = mem[buf + i]
        if ch == 0: break
        result += chr(ch)

    assert result.upper().rstrip() == exp.upper(), \
        f'boundary ${opc:02X} ops={operands}: got {result!r}, expected {exp!r}'


# ── dasm_insn bank-state contract ───────────────────────────────────────────
#
# dasm_insn owns its KERNAL banking — callers (currently emit_dot in
# repl.s::cmd_disasm and cmd_dot::@call_asm) just call it.  These tests
# pin the contract:
#
#   - dasm_insn returns the correct length and writes the expected
#     mnemonic to dasm_buf
#   - $01 bit 1 is set on return (KERNAL banked back in)
#   - I flag is clear on return (interrupts re-enabled)
#
# In the test environment the dasm test stub provides the bank helpers
# (no real KERNAL ROM, but they still toggle $01 bit 1 / sei / cli so
# the witness is meaningful).  These tests would catch a regression in
# either the dasm_insn entry/exit pairing or the test stub itself.

class TestDasmBankContract:
    """dasm_insn must restore $01 bit 1 = 1 and clear I after every call."""

    def _run(self, dasm_syms, opc, operands=(0x00, 0x00)):
        mpu = MPU()
        mem = bytearray(0x10000)
        dasm_syms.load_into(mem)

        mem[INSN_ADDR]     = opc
        mem[INSN_ADDR + 1] = operands[0]
        mem[INSN_ADDR + 2] = operands[1]
        mem[dasm_syms.asm_cpu] = CPU_6510

        # Pre-condition: $01 bit 1 = 1 (KERNAL mapped), I = 0 (interrupts on).
        mem[0x01] = 0x37
        mpu.memory = mem
        mpu.p &= ~0x04                  # clear I

        RETURN_ADDR = 0x0F00
        mem[RETURN_ADDR] = 0x00         # BRK as halt
        mpu.sp = 0xFF
        mpu.sp -= 1; mem[0x01FF] = (RETURN_ADDR - 1) >> 8
        mpu.sp -= 1; mem[0x01FE] = (RETURN_ADDR - 1) & 0xFF

        mpu.pc = dasm_syms.dasm_test_entry
        for _ in range(10000):
            if mpu.pc == RETURN_ADDR:
                break
            mpu.step()
        else:
            pytest.fail(f"Timeout ${opc:02X}")

        return mpu, mem

    def test_legal_lda_imm(self, dasm_syms):
        """LDA #$00 — 2-byte instruction, finish path."""
        mpu, mem = self._run(dasm_syms, 0xA9)
        assert mpu.a == 2, f"length {mpu.a}, expected 2"
        assert (mem[0x01] & 0x02) == 0x02, \
            f"$01 bit 1 not set after dasm_insn: ${mem[0x01]:02X}"
        assert (mpu.p & 0x04) == 0, \
            f"I flag still set after dasm_insn: ${mpu.p:02X}"

    def test_legal_implied(self, dasm_syms):
        """RTS — 1-byte implied instruction, finish path."""
        mpu, mem = self._run(dasm_syms, 0x60)
        assert mpu.a == 1
        assert (mem[0x01] & 0x02) == 0x02
        assert (mpu.p & 0x04) == 0

    def test_legal_absolute(self, dasm_syms):
        """JMP $0000 — 3-byte absolute, finish path."""
        mpu, mem = self._run(dasm_syms, 0x4C)
        assert mpu.a == 3
        assert (mem[0x01] & 0x02) == 0x02
        assert (mpu.p & 0x04) == 0

    def test_unknown_opcode(self, dasm_syms):
        """6502 illegal $02 — unknown path through _dasm_finish_unk
        → _dasm_finish_imp → finish.  Must still pair bank_in."""
        mpu = MPU()
        mem = bytearray(0x10000)
        dasm_syms.load_into(mem)
        mem[INSN_ADDR] = 0x02
        mem[dasm_syms.asm_cpu] = CPU_6502
        mem[0x01] = 0x37
        mpu.memory = mem
        mpu.p &= ~0x04
        RETURN_ADDR = 0x0F00
        mem[RETURN_ADDR] = 0x00
        mpu.sp = 0xFF
        mpu.sp -= 1; mem[0x01FF] = (RETURN_ADDR - 1) >> 8
        mpu.sp -= 1; mem[0x01FE] = (RETURN_ADDR - 1) & 0xFF
        mpu.pc = dasm_syms.dasm_test_entry
        for _ in range(10000):
            if mpu.pc == RETURN_ADDR:
                break
            mpu.step()
        assert mpu.a == 1, f"unknown should be length 1, got {mpu.a}"
        assert (mem[0x01] & 0x02) == 0x02, \
            f"$01 bit 1 not set after unknown opcode: ${mem[0x01]:02X}"
        assert (mpu.p & 0x04) == 0, \
            f"I flag still set after unknown opcode: ${mpu.p:02X}"

    def test_cmos_rmb(self, dasm_syms):
        """RMB0 $00 — cc=11 path that bypasses finish (its own rts).
        Must still pair bank_in even though it doesn't go through finish."""
        mpu = MPU()
        mem = bytearray(0x10000)
        dasm_syms.load_into(mem)
        mem[INSN_ADDR]     = 0x07          # RMB0 zp
        mem[INSN_ADDR + 1] = 0x00
        mem[dasm_syms.asm_cpu] = CPU_65C02
        mem[0x01] = 0x37
        mpu.memory = mem
        mpu.p &= ~0x04
        RETURN_ADDR = 0x0F00
        mem[RETURN_ADDR] = 0x00
        mpu.sp = 0xFF
        mpu.sp -= 1; mem[0x01FF] = (RETURN_ADDR - 1) >> 8
        mpu.sp -= 1; mem[0x01FE] = (RETURN_ADDR - 1) & 0xFF
        mpu.pc = dasm_syms.dasm_test_entry
        for _ in range(10000):
            if mpu.pc == RETURN_ADDR:
                break
            mpu.step()
        assert mpu.a == 2, f"RMB0 should be length 2, got {mpu.a}"
        assert (mem[0x01] & 0x02) == 0x02, \
            f"$01 bit 1 not set after RMB0: ${mem[0x01]:02X}"
        assert (mpu.p & 0x04) == 0, \
            f"I flag still set after RMB0: ${mpu.p:02X}"

    def test_cmos_bbr(self, dasm_syms):
        """BBR0 $00,$0300 — cc=11 ZPREL path with its own rts.
        Three-byte instruction, must still pair bank_in."""
        mpu = MPU()
        mem = bytearray(0x10000)
        dasm_syms.load_into(mem)
        mem[INSN_ADDR]     = 0x0F          # BBR0 zp,rel
        mem[INSN_ADDR + 1] = 0x00
        mem[INSN_ADDR + 2] = 0x00
        mem[dasm_syms.asm_cpu] = CPU_65C02
        mem[0x01] = 0x37
        mpu.memory = mem
        mpu.p &= ~0x04
        RETURN_ADDR = 0x0F00
        mem[RETURN_ADDR] = 0x00
        mpu.sp = 0xFF
        mpu.sp -= 1; mem[0x01FF] = (RETURN_ADDR - 1) >> 8
        mpu.sp -= 1; mem[0x01FE] = (RETURN_ADDR - 1) & 0xFF
        mpu.pc = dasm_syms.dasm_test_entry
        for _ in range(10000):
            if mpu.pc == RETURN_ADDR:
                break
            mpu.step()
        assert mpu.a == 3, f"BBR0 should be length 3, got {mpu.a}"
        assert (mem[0x01] & 0x02) == 0x02, \
            f"$01 bit 1 not set after BBR0: ${mem[0x01]:02X}"
        assert (mpu.p & 0x04) == 0, \
            f"I flag still set after BBR0: ${mpu.p:02X}"
