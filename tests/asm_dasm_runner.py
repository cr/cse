"""asm_dasm_runner.py — run asm_line / dasm_insn, singly or as sweeps.

Owner: doc/build_system.md

The one place that knows how to drive the two entry points: on py65
for the C64 bundles, on M65Emu for the m65 ones (`M65Bundle`, which
other m65 bundle tests use for their own entry points too).  Used by
the unit tests (test_dasm, test_asm_line, test_asm_m65, test_dasm_m65), by
`dev/capture_golden.py` (records the golden files) and by
`tests/unit/test_golden_asm_dasm.py` (holds the current build to them).

Golden sweep cases are keyed by strings so the files stay diffable:

    dasm  "<asm_cpu>:<opcode hex>"      → [text, length, cycles]
    asm   "<asm_cpu>:<source>"          → [hex bytes | "E<code>", cycles]

A set with the 45GS02 (m65) adds prefixed dasm cases, keyed by the
prefix bytes before the opcode ("4:4242A5", "4:EAB2", "4:4242EAB2"),
and the asm sources of its 4510 and 45GS02 rows (m65_sources).  On
M65Emu a "cycle" is an instruction (MPU45GS02 counts one per
instruction): the m65 speed gate counts instructions.
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


# ── the m65 bundles: M65Emu, CSE's base page at 0.1F00 ─────────────────────

class M65Bundle:
    """An m65 bundle loaded into an M65Emu, run as kernel code runs (B =
    CSE_BP).  `poke` / `peek` take a bundle symbol's address: below $100 a
    base-page offset, else a bank-0 address."""

    def __init__(self, syms):
        from m65emu import M65Emu
        from m65emu.harness import CSE_BP
        self.bp = CSE_BP << 8
        from m65emu import m45_ops
        self.emu = M65Emu()
        syms.load_into_emu(self.emu)
        self.mem = self.emu.memory
        cpu = self.emu.cpu                  # clean mode (testing.md § m65 bundles):
        cpu.clean = True                    # the 6502's opcodes and m45_ops.inc's
        cpu.allowed = cpu.allowed | m45_ops.allowed_keys()

    def _flat(self, a):
        return self.bp | a if a < 0x100 else a

    def poke(self, a, *vals):
        for k, v in enumerate(vals):
            self.mem.write_flat(self._flat(a) + k, v)

    def peek(self, a, n=1):
        return bytes(self.mem.read_flat(self._flat(a) + k) for k in range(n))

    def call(self, entry, ret=None, *, sp=0xFD, y=0):
        """Run from `entry` until PC = `ret` (the RTS of a frame whose return
        address, ret - 1, sits at $01FE/$01FF; DASM_RETURN by default);
        return the cycle count."""
        from m65emu.harness import CSE_BP
        ret = DASM_RETURN if ret is None else ret
        cpu = self.emu.cpu
        self.mem.write_flat(0x01FF, (ret - 1) >> 8)
        self.mem.write_flat(0x01FE, (ret - 1) & 0xFF)
        cpu.sp = (cpu.sp & 0xFF00) | sp
        cpu.b, cpu.y, cpu.pc = CSE_BP, y, entry
        start = cpu.processorCycles
        self.emu.run_until(ret, max_cycles=200_000)
        return cpu.processorCycles - start


def _run_dasm_m65(syms, cpu, insn_bytes):
    m = M65Bundle(syms)
    m.poke(DASM_INSN_ADDR, *insn_bytes)
    m.poke(syms.asm_cpu, cpu)
    cyc = m.call(syms.dasm_test_entry, DASM_RETURN)
    buf = m.peek(syms.dasm_buf, 24)
    return buf.split(b"\0")[0].decode("latin-1"), m.emu.a, cyc


def run_dasm(syms, cpu, insn_bytes):
    """Disassemble `insn_bytes` at DASM_INSN_ADDR with asm_cpu=`cpu`.
    Returns (text, length, cycles)."""
    if getattr(syms, "platform", "c64") == "m65":
        return _run_dasm_m65(syms, cpu, insn_bytes)
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


def dasm_cases(config):
    """(key, asm_cpu, bytes): every opcode in every view of the set, and
    with the 45GS02 each opcode behind each prefix (5 bytes at most)."""
    for cpu in CONFIG_CPUS[config]:
        for opc in range(256):
            yield f"{cpu}:{opc:02X}", cpu, [opc, *DASM_OPERANDS]
    if "45gs02" in MT.CPU_SETS[config][1]:
        cpu = MT.ASM_CPU["45gs02"]
        for pfx in (I.PREFIX_Q, I.PREFIX_FAR, I.PREFIX_Q + I.PREFIX_FAR):
            for opc in range(256):
                yield (f"{cpu}:{pfx.hex().upper()}{opc:02X}", cpu,
                       (list(pfx) + [opc, *DASM_OPERANDS])[:5])


def dasm_sweep(syms, config):
    out = {}
    for key, cpu, insn in dasm_cases(config):
        out[key] = list(run_dasm(syms, cpu, insn))
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


def _run_asm_m65(syms, source, cpu, *, pc=ASM_PC, out=ASM_OUT_BUF, asm_pass=None,
                 rel16=False, keep=False):
    """As run_asm; `pc` / `out` place the instruction, `asm_pass` sets the
    pass, `rel16` the caller's width request (asm_rel16).  With `out` or
    `rel16` given, asm_line itself runs (its $FFFF refusal, the request's
    clearing); else _asm_line_core.  `keep` also returns the machine."""
    m = M65Bundle(syms)
    m.poke(ASM_IN_BUF, *source.encode('ascii'), 0)
    m.poke(syms.asm_ptr, ASM_IN_BUF & 0xFF, ASM_IN_BUF >> 8)
    m.poke(syms.asm_pc, pc & 0xFF, pc >> 8, 0, 0)          # far pointers:
    m.poke(syms.asm_out, out & 0xFF, out >> 8, 0, 0)       # bank 0
    m.poke(syms.asm_cpu, cpu)
    m.poke(syms.asm_err_code, 0)
    if asm_pass is not None:
        m.poke(syms.asm_pass, asm_pass)
    if rel16:
        m.poke(syms.asm_rel16, 0x80)
    if out != ASM_OUT_BUF or rel16:
        m.emu.a, m.emu.x = ASM_IN_BUF & 0xFF, ASM_IN_BUF >> 8
        cyc = m.call(syms.asm_line, ASM_SENTINEL)
    else:
        m.poke(syms._asm_saved_sp, 0xFD)        # asm_error unwinds to the frame
        cyc = m.call(syms._asm_line_core, ASM_SENTINEL)
    n = m.peek(syms.asm_len)[0]
    err = m.peek(syms.asm_err_code)[0]
    got = None if (n == 0 or err) else bytes(m.mem.read_flat(out + k) for k in range(n))
    return (got, err, cyc, m) if keep else (got, err, cyc)


def run_asm(syms, source, cpu, **m65):
    """Assemble `source` with asm_cpu=`cpu` through _asm_line_core.
    Returns (bytes or None, asm_err_code, cycles); None means asm_len = 0,
    i.e. an error exit.  The m65 path takes _run_asm_m65's options."""
    if getattr(syms, "platform", "c64") == "m65":
        return _run_asm_m65(syms, source, cpu, **m65)
    if m65:
        raise TypeError(f"run_asm: {sorted(m65)} are the m65 path's options")
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


# The m65 modes' spellings (MODE_EXAMPLES holds the C64 ones), and the
# far forms'.  REL16's targets: in reach of an 8-bit branch at asm_pc 0,
# forward out of it, backward out of it.
M65_EXAMPLES = {"IMM16": ["#$1234", "#$00FF"], "REL16": ["$0002", "$1234", "$FF00"],
                "ISPY": ["($12,SP),Y", "($12,S),Y", "( $12 , SP ) , Y"],
                "ZPIZ": ["($12),Z", "( $12 ) , Z"]}
FAR_EXAMPLES = {"ZPI": ["[$12]", "[ $12 ]"], "ZPIZ": ["[$12],Z", "[ $12 ] , Z"]}


def m65_sources(config):
    """Every row of the set's 4510 and 45GS02 views with each spelling of
    its mode (none for a C64 set): the Q names and suffixes, the far
    forms, REL16 targets out of an 8-bit branch's reach."""
    lines = []
    for view in MT.CPU_SETS[config][1]:
        if view not in ("4510", "45gs02"):
            continue
        for r in I.instructions(view):
            if I.PREFIX_FAR in r.prefix:
                srcs = FAR_EXAMPLES[r.mode]
            else:
                srcs = M65_EXAMPLES.get(r.mode) or [
                    s for s, _ in I.MODE_EXAMPLES.get(r.mode, [])
                    if not any("a" <= c <= "z" for c in s)]
            lines += [f"{r.mnemonic} {s}".strip() for s in srcs]
    return lines


# asm_err_code (asm_err.md): a refusal's category
SYNTAX, EXPR, CPU = 0, 1, 2


def asm_result(syms, source, cpu, **kw):
    """run_asm's bytes, or ("E", asm_err_code) for a refusal."""
    got, err, _ = run_asm(syms, source, cpu, **kw)
    return got if got is not None else ("E", err)


def asm_sweep(syms, config):
    sources = list(dict.fromkeys(asm_sources() + m65_sources(config)))
    out = {}
    for cpu in CONFIG_CPUS[config]:
        for src in sources:
            got, err, cyc = run_asm(syms, src, cpu)
            out[f"{cpu}:{src}"] = [got.hex() if got is not None else f"E{err}", cyc]
    return out
