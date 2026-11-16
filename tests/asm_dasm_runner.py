"""asm_dasm_runner.py — exhaustive asm_line / dasm_insn sweeps on py65.

Owner: doc/build_system.md

Shared by `dev/capture_golden.py` (records the golden files from a
known-good build) and `tests/unit/test_golden_asm_dasm.py` (compares
the current build against them: output identity and the cycle gate).

A sweep case is identified by a string key so golden files stay
readable and diffable:

    dasm  "<asm_cpu>:<opcode hex>"      → [text, length, cycles]
    asm   "<asm_cpu>:<source>"          → [hex bytes | "E<code>", cycles]
"""

import pathlib
import sys

from py65.devices.mpu6502 import MPU

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))
import instruction_set as I                     # noqa: E402

# Each bundle config → the asm_cpu values of its CPU set
# (build_system.md § Builds and CPU sets).
CONFIG_CPUS = {
    "6502": (0,),
    "6510": (0, 1),
    "cmos": (0, 1, 2),
}

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"

# ── dasm ─────────────────────────────────────────────────────────────────────
DASM_INSN_ADDR = 0x0B00
DASM_RETURN    = 0x0F00
DASM_OPERANDS  = (0x42, 0x34)


def run_dasm(syms, cpu, insn_bytes):
    """Disassemble `insn_bytes` at DASM_INSN_ADDR with asm_cpu=`cpu`.
    Returns (text, length, cycles)."""
    mpu = MPU()
    mem = bytearray(0x10000)
    syms.load_into(mem)
    for n, b in enumerate(insn_bytes):
        mem[DASM_INSN_ADDR + n] = b
    mem[syms.asm_cpu] = cpu
    mem[DASM_RETURN] = 0x00  # BRK
    mpu.memory = mem
    mpu.sp = 0xFF
    mpu.sp -= 1; mem[0x01FF] = (DASM_RETURN - 1) >> 8
    mpu.sp -= 1; mem[0x01FE] = (DASM_RETURN - 1) & 0xFF
    mpu.pc = syms.dasm_test_entry
    start = mpu.processorCycles
    for _ in range(10000):
        if mpu.pc == DASM_RETURN:
            break
        mpu.step()
    else:
        raise TimeoutError(f"dasm did not return (PC=${mpu.pc:04X})")
    text = ''
    for n in range(24):
        ch = mem[syms.dasm_buf + n]
        if ch == 0:
            break
        text += chr(ch)
    return text, mpu.a, mpu.processorCycles - start


def dasm_sweep(syms, config):
    out = {}
    for cpu in CONFIG_CPUS[config]:
        for opc in range(256):
            text, length, cyc = run_dasm(syms, cpu, [opc, *DASM_OPERANDS])
            out[f"{cpu}:{opc:02X}"] = [text, length, cyc]
    return out


# ── asm ──────────────────────────────────────────────────────────────────────
ASM_PC      = 0x0000
ASM_OUT_BUF = 0x4000
ASM_IN_BUF  = 0x3000
ASM_SENTINEL = 0xFFFF


def asm_sources():
    """Every (mnemonic, mode) of every C64 key, rendered with each
    MODE_EXAMPLES operand — including rows the current code may refuse
    (the golden file records refusals too)."""
    srcs = []
    for mne, (profile, cmos_bit, _cat) in I.MNEMONICS.items():
        modes = I.mne_modes(profile, cmos_bit)
        for mode in I.ALL_MODES:
            if mode not in modes:
                continue
            for operand_src, _ in I.MODE_EXAMPLES.get(mode, []):
                if any('a' <= c <= 'z' for c in operand_src):
                    continue
                srcs.append(f"{mne} {operand_src}".strip())
    return list(dict.fromkeys(srcs))


def run_asm(syms, source, cpu):
    """Assemble `source` with asm_cpu=`cpu`.
    Returns (bytes or None, asm_err_code, cycles)."""
    cpu_ = MPU()
    mem = cpu_.memory
    syms.load_into(mem)
    for n, b in enumerate(source.encode('ascii') + b'\x00'):
        mem[ASM_IN_BUF + n] = b
    mem[syms.asm_ptr]     = ASM_IN_BUF & 0xFF
    mem[syms.asm_ptr + 1] = ASM_IN_BUF >> 8
    mem[syms.asm_pc]      = ASM_PC & 0xFF
    mem[syms.asm_pc + 1]  = ASM_PC >> 8
    mem[syms.asm_out]     = ASM_OUT_BUF & 0xFF
    mem[syms.asm_out + 1] = ASM_OUT_BUF >> 8
    mem[syms.asm_cpu]     = cpu
    mem[syms.asm_err_code] = 0
    cpu_.sp = 0xFF
    mem[0x01FF] = (ASM_SENTINEL - 1) >> 8
    mem[0x01FE] = (ASM_SENTINEL - 1) & 0xFF
    cpu_.sp = 0xFD
    mem[syms._asm_saved_sp] = cpu_.sp
    cpu_.pc = syms._asm_line_core
    cpu_.y = 0
    start = cpu_.processorCycles
    for _ in range(50_000):
        if cpu_.pc == ASM_SENTINEL:
            break
        cpu_.step()
    else:
        raise TimeoutError(f"asm_line did not return for {source!r}")
    n = mem[syms.asm_len]
    got = bytes(mem[ASM_OUT_BUF:ASM_OUT_BUF + n]) if n else None
    return got, mem[syms.asm_err_code], cpu_.processorCycles - start


def asm_sweep(syms, config):
    out = {}
    for cpu in CONFIG_CPUS[config]:
        for src in asm_sources():
            got, err, cyc = run_asm(syms, src, cpu)
            out[f"{cpu}:{src}"] = [got.hex() if got is not None else f"E{err}", cyc]
    return out
