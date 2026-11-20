"""test_dasm.py — Tier-U unit tests for dasm.s.

Owner: doc/modules/dasm.md

Contract source: [doc/modules/dasm.md](../../doc/modules/dasm.md).

Coverage of the documented contract
-----------------------------------
2 exported items:

  dasm_insn        — test_dasm (256 opcodes × every asm_cpu of every
                      C64 set and the CMOS mode: 6502 ×1, 6510 ×2,
                      65c02 ×2 = 1280 cases) against the oracle built from
                      instruction_set.instructions(variant);
                      test_dasm_boundary_operands (operand edge cases);
                      TestDasmBankContract (banking state post-call)
  dasm_buf (BSS)   — read directly by every test_dasm case (decoded
                      NUL-terminated PETSCII output)

The disassembler writes to dasm_buf (NUL-terminated PETSCII).  No
screen RAM, no cursor state — tests read the buffer directly.

CPU modes:
  0 = 6502    (legal opcodes only; others → "...")
  1 = 6510    (legal + NMOS illegals)
  2 = 65C02   (legal + CMOS extensions; the CMOS mode)

Bundles: dasm + dasm_tables + dasm_test_stub, one per C64 set and the
CMOS mode (`dasm_bundle(config)`, config ∈ 6502 / 6510 / 65c02, the
PROD_DEFS -D sets); the single-variant tests below use `dasm_syms`
(65c02, the CMOS mode).
"""

import pytest
from py65.devices.mpu6502 import MPU

import asm_dasm_runner as R
from asm_dasm_runner import run_dasm
from conftest import M65_CONFIGS, dasm_bundle

I = R.I

# asm_cpu values (build_system.md § Builds and CPU sets)
CPU_6502, CPU_6510, CPU_65C02 = (R.MT.ASM_CPU[v] for v in ('6502', '6510', '65c02'))

# Instruction length per mode = opcode byte + operand bytes.
MODE_LEN = {m: 1 + n for m, n in I.MODE_OPERAND_BYTES.items()}

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


# ── Per-CPU views, from the instruction set alone ────────────────
def _listing_rank():
    """Mnemonic → rank in the listing-name order: `OPCODES` order, then
    `OPCODES_4510_ADDED` order (dasm.md § Design, *Listing name*)."""
    order = list(I.OPCODES) + list(I.OPCODES_4510_ADDED)
    return {m: i for i, m in enumerate(order)}


def build_cpu_maps():
    """opcode → (listing name, mode) per asm_cpu.  Where several rows
    name one opcode (the 6510 aliases, NOP/EOM), the listing name is the
    row whose key ranks last in the listing-name order."""
    rank = _listing_rank()
    maps = {}
    for cpu, variant in R.CPU_VIEW.items():
        best = {}
        for r in I.instructions(variant):
            if r.prefix:
                continue
            cur = best.get(r.opcode)
            if cur is None or rank[r.key] >= rank[cur.key]:
                best[r.opcode] = r
        maps[cpu] = {op: (r.mnemonic, r.mode) for op, r in best.items()}
    return maps

CPU_MAPS = build_cpu_maps()

INSN_ADDR = R.DASM_INSN_ADDR
TEST_OPERANDS = list(R.DASM_OPERANDS)


def expected_string(cpu, opc, operands=TEST_OPERANDS):
    if opc not in CPU_MAPS[cpu]:
        return '...'
    mne, mode = CPU_MAPS[cpu][opc]
    operand = fmt_operand(mode, operands, INSN_ADDR)
    if operand:
        return f'{mne} {operand}'
    return mne


def expected_length(cpu, opc):
    if opc not in CPU_MAPS[cpu]:
        return 1
    return MODE_LEN[CPU_MAPS[cpu][opc][1]]


# ── Parametrize: every opcode × every CPU of every build ─────────
def gen_cases():
    cases = []
    for config, cpus in R.CONFIG_CPUS.items():
        if config in M65_CONFIGS:            # the m65 set: test_dasm_m65.py
            continue
        for cpu in cpus:
            tag = R.CPU_VIEW[cpu].upper()
            for opc in range(256):
                cases.append(pytest.param(config, cpu, opc,
                                          id=f'{config}-{tag}-${opc:02X}'))
    return cases


@pytest.mark.parametrize("config,cpu,opc", gen_cases())
def test_dasm(config, cpu, opc):
    """Disassemble one opcode on one build's CPU view and compare with
    the instruction-set oracle (text and length)."""
    text, length, _ = run_dasm(dasm_bundle(config), cpu,
                               [opc, *TEST_OPERANDS])
    exp = expected_string(cpu, opc)
    assert text.upper().rstrip() == exp.upper(), \
        f'{config} ${opc:02X} cpu={cpu}: got {text!r}, expected {exp!r}'
    assert length == expected_length(cpu, opc), \
        f'{config} ${opc:02X} cpu={cpu}: length={length}, ' \
        f'expected {expected_length(cpu, opc)}'


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
        exp = _boundary_expected(CPU_65C02, opc, operands)
        _BOUNDARY_CASES.append(
            pytest.param(opc, operands, exp, id=f'{tag}-${opc:02X}')
        )

@pytest.mark.parametrize("opc,operands,exp", _BOUNDARY_CASES)
def test_dasm_boundary_operands(dasm_syms, opc, operands, exp):
    """Disassemble with boundary operand values ($00, $FF, $80)."""
    text, _length, _ = run_dasm(dasm_syms, CPU_65C02, [opc, *operands])   # dasm_syms: the CMOS mode
    assert text.upper().rstrip() == exp.upper(), \
        f'boundary ${opc:02X} ops={operands}: got {text!r}, expected {exp!r}'


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
        mem[dasm_syms.asm_cpu] = CPU_65C02      # dasm_syms: the CMOS mode

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


# ── No mutable bytes in CODE (dasm.md § Memory; memory_design.md § Design
#    Principles 2: "No self-modifying code") ──────────────────────────────

class TestCodeIsReadOnly:
    """Disassembling must not write into the bundle's CODE/RODATA image
    (a ROM/CRT build cannot).  _compute_branch_target used to stash its
    PC adjustment in a byte inside CODE (`@adj`)."""

    @pytest.mark.parametrize("insn", [[0xD0, 0xFE], [0x10, 0x05],
                                      [0x0F, 0x42, 0x80]],     # BNE, BPL, BBR0
                             ids=["bne", "bpl", "bbr0"])
    def test_image_unchanged(self, dasm_syms, insn):
        from asm_dasm_runner import DASM_INSN_ADDR, DASM_RETURN
        from conftest import _CODE_START
        mpu = MPU()
        mem = bytearray(0x10000)
        dasm_syms.load_into(mem)
        image = bytes(dasm_syms._code_blob)
        for n, b in enumerate(insn):
            mem[DASM_INSN_ADDR + n] = b
        mem[dasm_syms.asm_cpu] = CPU_65C02
        mpu.memory = mem
        mpu.sp = 0xFD
        mem[0x01FF] = (DASM_RETURN - 1) >> 8
        mem[0x01FE] = (DASM_RETURN - 1) & 0xFF
        mpu.pc = dasm_syms.dasm_test_entry
        for _ in range(10000):
            if mpu.pc == DASM_RETURN:
                break
            mpu.step()
        # the CODE segment's extent, from the bundle's map
        import re
        from conftest import _DASM
        mapf = _DASM[dasm_syms.config].ensure().bin.with_suffix(".map")
        m = re.search(r"^CODE\s+([0-9A-F]{6})\s+([0-9A-F]{6})",
                      mapf.read_text(), re.M)
        lo, hi = int(m.group(1), 16), int(m.group(2), 16)
        changed = [a for a in range(lo, hi + 1)
                   if mem[a] != image[a - _CODE_START]]
        assert not changed, f"dasm wrote into CODE at ${changed[0]:04X}"


# ── the round trip (dasm.md § Owned files; TODO A5, P5 T2) ───────────────────
#
# Every row of every view of the C64 sets and the CMOS mode: its bytes
# listed at DASM_INSN_ADDR, the listing assembled there again, give the
# same bytes, and the listed length is the row's.  (The m65 set's is
# test_dasm_m65.py's.)

def _round_trip_bad(config):
    from conftest import AsmCoreSymbols, dasm_bundle
    dsyms, asyms = dasm_bundle(config), AsmCoreSymbols(config=config)
    bad = []
    for view in R.MT.CPU_SETS[config][1]:
        cpu = R.MT.ASM_CPU[view]
        for r in I.instructions(view):
            if r.mode == 'REL':
                b = [0x10]
            elif r.mode == 'ZPREL':
                b = [0x12, 0x10]
            else:
                b = [0x12, 0x34][:I.MODE_OPERAND_BYTES[r.mode]]
            raw = [r.opcode] + b
            listed, n = R.run_dasm(dsyms, cpu, raw + [0] * (3 - len(raw)))[:2]
            again = R.run_asm(asyms, listed.strip(), cpu, pc=R.DASM_INSN_ADDR)[0]
            if n != len(raw) or again != bytes(raw):
                bad.append((view, r.key, r.mode, bytes(raw).hex(), listed, n, again))
    return bad


@pytest.mark.parametrize("config", ["6502", "6510", "65c02"])
def test_round_trip_over_every_row(config):
    bad = _round_trip_bad(config)
    assert not bad, f"{len(bad)} rows:\n" + "\n".join(map(str, bad[:20]))
