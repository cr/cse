"""asm_dasm_runner.py — run asm_line / dasm_insn on py65, singly or as sweeps.

Owner: doc/build_system.md

The one place that knows how to drive the two entry points under py65.
Used by the unit tests (test_dasm, test_asm_line), by
`dev/capture_golden.py` (records the golden files) and by
`tests/unit/test_golden_asm_dasm.py` (holds the current build to them).

Golden sweep cases are keyed by strings so the files stay diffable:

    dasm  "<asm_cpu>:<opcode hex>"      → [text, length, cycles]
    asm   "<asm_cpu>:<source>"          → [hex bytes | "E<code>", cycles]
"""

import pathlib
import sys

from py65.devices.mpu6502 import MPU

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "dev"))
import instruction_set as I                     # noqa: E402
import mnemonic_tables as MT                    # noqa: E402

# CPU set → the asm_cpu values of its CPUs, from the generator's registry
# (build_system.md § Builds and CPU sets).  Bundle configs, golden files
# and the size budget are all keyed by the CPU-set name.
CONFIG_CPUS = {c: tuple(MT.ASM_CPU[v] for v in views)
               for c, (_define, views, _cls) in MT.CPU_SETS.items()}
CPU_VIEW = {n: v for v, n in MT.ASM_CPU.items()}       # asm_cpu → view name

GOLDEN_DIR = ROOT / "tests" / "fixtures" / "golden"

# ── dasm ─────────────────────────────────────────────────────────────────────
DASM_INSN_ADDR = 0x0B00     # above the bundle's CODE+RODATA+BSS
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
    mpu.sp = 0xFD
    mem[0x01FF] = (DASM_RETURN - 1) >> 8
    mem[0x01FE] = (DASM_RETURN - 1) & 0xFF
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
ASM_PC       = 0x0000       # asm_pc for REL/ZPREL offsets
ASM_OUT_BUF  = 0x4000
ASM_IN_BUF   = 0x3000
ASM_SENTINEL = 0xFFFF


def examples():
    """(mnemonic, mode, operand source, operand bytes) for every mode of
    every C64 key, one per MODE_EXAMPLES spelling (uppercase ones only —
    mode_parse takes register letters as PETSCII uppercase)."""
    for mne, (profile, cmos_bit, _cat) in I.MNEMONICS.items():
        modes = I.mne_modes(profile, cmos_bit)
        for mode in I.ALL_MODES:
            if mode not in modes:
                continue
            for operand_src, operand_bytes in I.MODE_EXAMPLES.get(mode, []):
                if not any('a' <= c <= 'z' for c in operand_src):
                    yield mne, mode, operand_src, operand_bytes


def asm_sources():
    """Every distinct source line of examples(), in order, then each
    digit-zone key (`RMB` `SMB` `BBR` `BBS`) with each bit number — the
    examples give those keys without the digit their row needs."""
    lines = [f"{mne} {src}".strip() for mne, _, src, _ in examples()]
    for mne, mode, src, _ in examples():
        if I.OPCODES[mne].get(mode) is None:        # digit-encoded row
            lines += [f"{mne}{bit} {src}" for bit in range(8)]
    return list(dict.fromkeys(lines))


def run_asm(syms, source, cpu):
    """Assemble `source` with asm_cpu=`cpu` through _asm_line_core.
    Returns (bytes or None, asm_err_code, cycles); None means asm_len = 0,
    i.e. an error exit."""
    mpu = MPU()
    mem = mpu.memory
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
    mem[0x01FF] = (ASM_SENTINEL - 1) >> 8
    mem[0x01FE] = (ASM_SENTINEL - 1) & 0xFF
    mpu.sp = 0xFD
    # asm_error unwinds with `ldx _asm_saved_sp / txs / rts`.
    mem[syms._asm_saved_sp] = mpu.sp
    mpu.pc = syms._asm_line_core
    mpu.y = 0
    start = mpu.processorCycles
    for _ in range(50_000):
        if mpu.pc == ASM_SENTINEL:
            break
        mpu.step()
    else:
        raise TimeoutError(f"asm_line did not return for {source!r}")
    n = mem[syms.asm_len]
    got = bytes(mem[ASM_OUT_BUF:ASM_OUT_BUF + n]) if n else None
    return got, mem[syms.asm_err_code], mpu.processorCycles - start


def asm_sweep(syms, config):
    out = {}
    for cpu in CONFIG_CPUS[config]:
        for src in asm_sources():
            got, err, cyc = run_asm(syms, src, cpu)
            out[f"{cpu}:{src}"] = [got.hex() if got is not None else f"E{err}", cyc]
    return out
