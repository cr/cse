"""
conftest.py – build test binaries and provide session-scoped fixtures.

Binaries are built once per session (cached in build/) and rebuilt
automatically whenever their source files are newer than the cached binary.
All test binaries are assembled with -g (debug symbols) and linked with
-Ln (VICE label file) so that ALL symbols — exported, internal, and
@local — are available at absolute addresses via SymbolTable.

Fixtures provided
-----------------
asm_syms        — asm_core bundle, -DCMOS_SUPPORT (65C02 production)
asm_6510_syms   — asm_core bundle, no CMOS_SUPPORT (6510 production)
asm_6502_syms   — asm_core bundle, -DUSE_MN6     (6502 production)
mn6_syms        — mn6 hash test binary  (test_mn_classify.py)
mn7_syms        — mn7 hash test binary  (test_mn_classify.py)
mem_syms        — zp + mem bundle       (test_mem.py)
dasm_syms       — dasm bundle           (test_dasm.py)

Test bundle architecture
------------------------
Interdependent modules are linked into a single "bundle" test binary
rather than per-module binaries with expanding stubs.  The asm_core
bundle links the full assembler pipeline; the mn6/mn7 binaries are
true leaf modules with zero cross-module imports.
"""

import re
import subprocess
import pathlib
import pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

# test.cfg constants (must match dev/test.cfg)
_ZP_START   = 0x0000
_CODE_START = 0x4000
_ZP_SIZE    = 0x0100

# version.inc — strings.s does `.include "version.inc"` and
# picks it up via `-I <build>`.  Tests build their own bundles
# so they need a version.inc under the root build/ dir.
BUILD.mkdir(exist_ok=True)
_VERSION_INC = BUILD / "version.inc"
_VERSION_INC_BODY = '.define VERSION_STRING "test"\n'
if not _VERSION_INC.exists() or _VERSION_INC.read_text() != _VERSION_INC_BODY:
    _VERSION_INC.write_text(_VERSION_INC_BODY)


# ── Shared harness helpers ───────────────────────────────────────────────────
#
# Every unit-tier test file that drives a bundle through py65 does the
# same three things: build a fresh MPU with the bundle loaded, push a
# fake JSR return address so the subroutine's RTS halts, and step the
# CPU until PC reaches that sentinel.  These helpers consolidate the
# pattern so each test file can focus on its own setup and output
# extraction.

def make_cpu(syms):
    """Return (cpu, mem) — a fresh py65 MPU with `syms` loaded via
    `.load_into(mem)`.  Caller is responsible for any further
    memory pre-seeding (source strings, ZP values, operand bytes)."""
    cpu = MPU()
    syms.load_into(cpu.memory)
    return cpu, cpu.memory


def push_rts_sentinel(cpu, sentinel=0x01F0):
    """Push `sentinel-1` to the stack as the JSR-style return address
    and stage a NOP at `sentinel` so nothing unexpected executes if
    the step loop races past the check.  Sets SP=$FD (matching a
    normal post-JSR state).  Returns `sentinel` for the caller to
    pass to `step_until_pc`."""
    mem = cpu.memory
    mem[sentinel] = 0xEA                        # NOP
    cpu.sp = 0xFF
    mem[0x01FF] = (sentinel - 1) >> 8
    mem[0x01FE] = (sentinel - 1) & 0xFF
    cpu.sp = 0xFD
    return sentinel


def step_until_pc(cpu, target_pc, *, max_steps=50_000, what="test"):
    """Step `cpu` until `cpu.pc == target_pc` or `max_steps` is
    exceeded.  Raises TimeoutError with the current PC on overflow."""
    for _ in range(max_steps):
        if cpu.pc == target_pc:
            return
        cpu.step()
    raise TimeoutError(
        f"{what}: did not reach ${target_pc:04X} after {max_steps} "
        f"steps (PC=${cpu.pc:04X})"
    )


def step_until_any_pc(cpu, targets, *, max_steps=50_000, what="test"):
    """Step `cpu` until `cpu.pc` reaches any address in `targets`
    (an iterable).  Returns the first-matched target.  Raises
    TimeoutError with the current PC on overflow.  Useful when a
    test needs to distinguish success return vs. error-exit paths."""
    target_set = set(targets)
    for _ in range(max_steps):
        if cpu.pc in target_set:
            return cpu.pc
        cpu.step()
    raise TimeoutError(
        f"{what}: did not reach any of " +
        ", ".join(f"${t:04X}" for t in sorted(target_set)) +
        f" after {max_steps} steps (PC=${cpu.pc:04X})"
    )


# ── Symbol resolution ───────────────────────────────────────────────────────
#
# All test bundles are assembled with ca65 -g and linked with ld65 -Ln.
# The .lbl file (VICE label format) contains every label — exported,
# module-internal, and @local — at its absolute address.
#
# SymbolTable encapsulates the file format so test code never touches
# paths, regexes, or file formats directly.

class SymbolTable:
    """Resolved symbol addresses from a debug-built .lbl file.

    Test code accesses symbols by name; the file format and location
    are encapsulated.  Usage::

        syms = SymbolTable(lbl_path)
        addr = syms["mode_parse"]    # __getitem__
        addr = syms.get("foo", 0)    # .get() with default
        "bar" in syms                # __contains__
    """

    def __init__(self, lbl_path):
        self._syms = {}
        for line in pathlib.Path(lbl_path).read_text().splitlines():
            m = re.match(r"al\s+([0-9a-fA-F]+)\s+\.(\S+)", line)
            if m:
                self._syms[m.group(2)] = int(m.group(1), 16)

    def __getitem__(self, name):
        try:
            return self._syms[name]
        except KeyError:
            avail = ", ".join(sorted(self._syms)[:20])
            raise KeyError(
                f"Symbol {name!r} not found. "
                f"Available: {avail}..."
            ) from None

    def __contains__(self, name):
        return name in self._syms

    def get(self, name, default=None):
        return self._syms.get(name, default)

    def __len__(self):
        return len(self._syms)

    def keys(self):
        return self._syms.keys()


# ── asm_core bundle ──────────────────────────────────────────────────────────
#
# Links the full single-line assembler pipeline as one test binary.
# Shared by test_asm_line.py, test_addr_mode.py, test_opcode_lookup.py,
# test_expr.py, and test_asm_err.py.
# The stub is minimal: BRK error handler + linker symbols for mem.s.
# No per-module mocking — every import is satisfied by real code.

# Three build configs mirror the three production builds (see
# Makefile _*_DEFS):
#
#   "cmos"  — -DCMOS_SUPPORT + mn7   (mirrors 65C02 production).
#             Default for most asm_core tests.
#   "6510"  — no -DCMOS_SUPPORT + mn7 (mirrors 6510 production).
#             Used for asm_cpu gate tests: the 6510 build still uses
#             mn7 (which recognizes CMOS mnemonics), but the CMOS
#             reject gate inside asm_line.s is `.ifdef CMOS_SUPPORT`-
#             wrapped — so only this bundle exposes regressions in the
#             gate's compile-time path.
#   "6502"  — -DUSE_MN6 + mn6         (mirrors 6502 production).
#             mn6 only recognizes the 56 legal NMOS mnemonics; CMOS
#             and illegals are rejected at the classifier tier before
#             the gate is even reached.  Used to exercise any
#             `.ifdef USE_MN6` code path that differs from the mn7
#             configs.  The source list swaps mn7.s/mn7_tables.s for
#             mn6.s/mn6_tables.s.

# Common sources across all three asm_core bundle configs.
_AC_COMMON_SOURCES = [
    SRC / "zp.s",
    SRC / "strings.s",
    SRC / "opcode_lookup.s",
    SRC / "asm_line.s",
    SRC / "asm_err.s",
    SRC / "addr_mode.s",
    SRC / "expr.s",
    SRC / "symtab.s",
    SRC / "mem.s",
    SRC / "mn_vars.s",
    SRC / "mn_modes.s",
    SRC / "mn_asm_tables.s",
    SRC / "mn_classify.s",
    DEV / "asm_core_test_stub.s",
]

# Per-config additions: the classifier (mn7 or mn6) + its tables.
_AC_CLASSIFIER_SOURCES = {
    "cmos": [SRC / "mn7.s", SRC / "mn7_tables.s"],
    "6510": [SRC / "mn7.s", SRC / "mn7_tables.s"],
    "6502": [SRC / "mn6.s", SRC / "mn6_tables.s"],
}


def _ac_sources(config):
    return _AC_COMMON_SOURCES + _AC_CLASSIFIER_SOURCES[config]


_AC_BIN = {
    "cmos": BUILD / "asm_core_test.bin",
    "6510": BUILD / "asm_core_6510_test.bin",
    "6502": BUILD / "asm_core_6502_test.bin",
}
_AC_MAP = {
    "cmos": BUILD / "asm_core_test.map",
    "6510": BUILD / "asm_core_6510_test.map",
    "6502": BUILD / "asm_core_6502_test.map",
}
_AC_LBL = {
    "cmos": BUILD / "asm_core_test.lbl",
    "6510": BUILD / "asm_core_6510_test.lbl",
    "6502": BUILD / "asm_core_6502_test.lbl",
}
_AC_FLAGS = {
    "cmos": ["-DCMOS_SUPPORT"],
    "6510": [],
    "6502": ["-DUSE_MN6"],
}


def _ac_needs_rebuild(config):
    if not _AC_BIN[config].exists() or not _AC_LBL[config].exists():
        return True
    bin_mtime = _AC_BIN[config].stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime
               for s in _ac_sources(config) + [DEV / "test.cfg"])


def _ac_build(config):
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _ac_sources(config):
        obj = BUILD / f"{src.stem}_ac_{config}.o"
        cmd = ["ca65", "-g", "--cpu", "6502",
               *_AC_FLAGS[config],
               "-I", str(BUILD),
               str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_AC_BIN[config]),
         "-m", str(_AC_MAP[config]),
         "-Ln", str(_AC_LBL[config])],
        check=True,
    )


class AsmCoreSymbols:
    """Resolved symbol addresses + binary loader for the asm_core bundle.

    Provides addresses for both addr_mode tests (mode_parse, asm_ptr, asm_opr)
    and asm_line tests (_asm_line_core, asm_pc, asm_out, asm_cpu, etc.).
    All symbols resolved from .lbl file (debug build).

    Parameter `config`:
      "cmos" — bundle built with -DCMOS_SUPPORT (matches 65C02 prod
               build config).  Default for all existing tests.
      "6510" — bundle built without -DCMOS_SUPPORT (matches 6510 prod
               build config).  Used by asm_cpu gate tests where the
               CMOS reject gate is ifdef-wrapped and thus config-sensitive.
    """

    def __init__(self, config="cmos"):
        self.config = config
        if _ac_needs_rebuild(config):
            _ac_build(config)

        s = SymbolTable(_AC_LBL[config])

        # addr_mode entry points
        self.mode_parse       = s["mode_parse"]
        self.asm_skip_ws      = s["asm_skip_ws"]
        self.asm_syntax_error = s["asm_syntax_error"]
        self.asm_expr_error   = s["asm_expr_error"]

        # asm_line entry points
        self._asm_line_core   = s["_asm_line_core"]
        self.asm_error        = s["asm_error"]

        # ZP variable addresses
        self.asm_ptr          = s["asm_ptr"]
        self.asm_opr          = s["asm_opr"]
        self.asm_pc           = s["asm_pc"]
        self.asm_out          = s["asm_out"]
        self.asm_len          = s["asm_len"]
        self.asm_cpu          = s["asm_cpu"]
        self._asm_saved_sp    = s["_asm_saved_sp"]
        self.asm_pass         = s["asm_pass"]
        self.asm_expr_err     = s["asm_expr_err"]

        # expr.s + symtab.s entry points (linked into asm_core; used
        # by test_expr.py after Tranche 3 folded it into this bundle).
        self.expr_eval        = s["expr_eval"]
        self.expr_eval_nb     = s["expr_eval_nb"]
        self.expr_error_str   = s["expr_error_str"]
        self.expr_ptr         = s["expr_ptr"]
        self.expr_val         = s["expr_val"]
        self.expr_wide        = s["expr_wide"]
        self.last_err         = s["last_err"]
        self.sym_define       = s["sym_define"]
        self.sym_lookup       = s["sym_lookup"]
        self.sym_clear        = s["sym_clear"]
        self.sym_name         = s["sym_name"]
        self.sym_val          = s["sym_val"]
        self.sym_wide         = s["sym_wide"]

        # asm_line.s: user-register BSS shadows (asm_line.md § Memory)
        self.reg_a            = s["reg_a"]
        self.reg_x            = s["reg_x"]
        self.reg_y            = s["reg_y"]
        self.reg_sp           = s["reg_sp"]
        self.reg_p            = s["reg_p"]

        # opcode_lookup.s entry points (linked into asm_core)
        self.asm_validate_mode = s["asm_validate_mode"]
        self.asm_opcode_lookup = s["asm_opcode_lookup"]
        self.asm_mode         = s["asm_mode"]
        self.asm_pidx         = s["asm_pidx"]

        # addr_mode.s extra entry point for isolated testing
        self.asm_skip_ws      = s["asm_skip_ws"]

        raw = _AC_BIN[config].read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        """Write the test binary into a 64 KB memory bytearray."""
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]   = self._code_blob


@pytest.fixture(scope="session")
def asm_syms():
    """Session-scoped asm_core binary (config='cmos', -DCMOS_SUPPORT)."""
    return AsmCoreSymbols()


@pytest.fixture(scope="session")
def asm_6510_syms():
    """Session-scoped asm_core binary built WITHOUT -DCMOS_SUPPORT,
    mirroring the 6510 production build config.  Used by
    test_asm_line.py's asm_cpu gate tests to catch regressions that
    only manifest when the CMOS reject path is ifdef'd out."""
    return AsmCoreSymbols(config="6510")


@pytest.fixture(scope="session")
def asm_6502_syms():
    """Session-scoped asm_core binary built with -DUSE_MN6, mirroring
    the 6502 production build config.  mn6 is linked instead of mn7 —
    only 56 legal NMOS mnemonics are recognized.  CMOS and illegal
    inputs are rejected by the classifier (the asm_line gate is never
    reached for them).  Used to exercise code paths guarded by
    `.ifdef USE_MN6`."""
    return AsmCoreSymbols(config="6502")


# ── mn6 / mn7 hash test binaries ──────────────────────────────────────────────
#
# Each binary is built from:
#   mn6:  src/mn_vars.s  src/mn6.s  src/mn6_tables.s
#   mn7:  src/mn_vars.s  src/mn7.s  src/mn7_tables.s
#
# Linked with dev/test.cfg (ZP at $0000, CODE/RODATA at $0200).
# All exported symbols (mn_c1/c2/c3, mn6_classify, mn7_classify …) appear
# in the "Exports list by name" section of the ld65 map file.

_MN_SOURCES = {
    'mn6': [SRC / "zp.s", SRC / "mn_vars.s", SRC / "mn6.s", SRC / "mn6_tables.s",
            SRC / "mn_classify.s"],
    'mn7': [SRC / "zp.s", SRC / "mn_vars.s", SRC / "mn7.s", SRC / "mn7_tables.s",
            SRC / "mn_classify.s"],
}

_MN_BIN = {v: BUILD / f"{v}_test.bin" for v in ('mn6', 'mn7')}
_MN_MAP = {v: BUILD / f"{v}_test.map" for v in ('mn6', 'mn7')}
_MN_LBL = {v: BUILD / f"{v}_test.lbl" for v in ('mn6', 'mn7')}

def _mn_needs_rebuild(variant):
    bin_path = _MN_BIN[variant]
    if not bin_path.exists() or not _MN_LBL[variant].exists():
        return True
    bin_mtime = bin_path.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime for s in _MN_SOURCES[variant])


def _mn_build(variant):
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _MN_SOURCES[variant]:
        obj = BUILD / (src.stem + f"_{variant}.o")
        cmd = ["ca65", "-g", "--cpu", "6502",
               "-I", str(BUILD),
               str(src), "-o", str(obj)]
        # mn_classify.s branches on USE_MN6 at build time.
        if variant == 'mn6':
            cmd += ["-D", "USE_MN6"]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_MN_BIN[variant]),
         "-m", str(_MN_MAP[variant]),
         "-Ln", str(_MN_LBL[variant])],
        check=True,
    )


class MnHashBinary:
    """Compiled mn6 or mn7 test binary with resolved symbol addresses."""

    def __init__(self, variant):
        if _mn_needs_rebuild(variant):
            _mn_build(variant)

        s = SymbolTable(_MN_LBL[variant])

        self.variant  = variant
        self.mn_c1    = s['mn_c1']
        self.mn_c2    = s['mn_c2']
        self.mn_c3    = s['mn_c3']
        self.classify    = s[f'{variant}_classify']
        self.mn_classify = s['mn_classify']
        # Table re-exports (mn_classify aliases them to the selected variant).
        self.mn_base_op = s['mn_base_op']
        self.mn_profile = s['mn_profile']
        # Internal tables — documented in mn_classify.md, exposed via @local
        # labels in the debug-build .lbl file.
        self.fp_table   = s[f'{variant}_fp']
        self.hash_t     = s[f'{variant}_hash_t']

        raw = _MN_BIN[variant].read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        """Write the test binary into a 64 KB memory bytearray."""
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]   = self._code_blob


@pytest.fixture(scope="session")
def mn6_syms():
    """Session-scoped mn6 hash binary + symbol addresses."""
    return MnHashBinary('mn6')


@pytest.fixture(scope="session")
def mn7_syms():
    """Session-scoped mn7 hash binary + symbol addresses."""
    return MnHashBinary('mn7')


# ── asm_src test binary ───────────────────────────────────────────────────────
#
# Links the full two-pass assembler pipeline:
#   zp + opcode_lookup + asm_line
#   + addr_mode + mn_vars + mn7 + mn7_tables + mn_modes + mn_asm_tables
#   + mn_classify + expr + symtab + asm_src
#   + asm_src_test_stub  (provides ed_read_line, etc.)
#
# Linked with asm_src_test.cfg (adds DATA segment for asm_src.s).

_AS_BIN = BUILD / "asm_src_test.bin"
_AS_MAP = BUILD / "asm_src_test.map"
_AS_LBL = BUILD / "asm_src_test.lbl"
_AS_CFG = DEV / "asm_src_test.cfg"

_AS_SOURCES = [
    SRC / "zp.s",
    SRC / "strings.s",
    SRC / "opcode_lookup.s",
    SRC / "asm_line.s",
    SRC / "asm_err.s",
    SRC / "addr_mode.s",
    SRC / "mn_vars.s",
    SRC / "mn7.s",
    SRC / "mn7_tables.s",
    SRC / "mn_modes.s",
    SRC / "mn_asm_tables.s",
    SRC / "mn_classify.s",
    SRC / "expr.s",
    SRC / "symtab.s",
    SRC / "mem.s",
    SRC / "asm_src.s",
    DEV / "asm_src_test_stub.s",
]


def _as_needs_rebuild():
    if not _AS_BIN.exists() or not _AS_LBL.exists():
        return True
    bin_mtime = _AS_BIN.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime for s in _AS_SOURCES + [_AS_CFG])


def _as_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _AS_SOURCES:
        obj = BUILD / f"{src.stem}_as.o"
        cmd = ["ca65", "-g", "--cpu", "6502", "-t", "c64",
               "-I", str(BUILD),
               str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(_AS_CFG),
         *obj_files,
         "-o", str(_AS_BIN),
         "-m", str(_AS_MAP),
         "-Ln", str(_AS_LBL)],
        check=True,
    )


class AsmSrcSymbols:
    """Resolved symbol addresses + binary loader for the asm_src test.

    All symbols resolved from .lbl file (debug build) — no more BSS
    offset arithmetic or module-offset parsing from the map file.
    """

    def __init__(self):
        if _as_needs_rebuild():
            _as_build()

        s = SymbolTable(_AS_LBL)

        # Stub entry points and BSS vars (previously required fragile
        # segment-offset computation from the map file)
        self.asm_src_test_entry = s['asm_src_test_entry']
        self.test_src_buf       = s['_test_src_buf']
        self.bank_witness       = s['_bank_witness']

        # asm_src BSS vars (previously required BSS offset calculation)
        self.asm_org    = s['asm_org']
        self.asm_size   = s['asm_size']
        self.asm_errors = s['asm_errors']

        # Exported symbols (previously from map exports)
        self.asm_line   = s['asm_line']
        self.asm_ptr    = s['asm_ptr']
        self.asm_pc     = s['asm_pc']
        self.asm_out    = s['asm_out']
        self.asm_len    = s['asm_len']
        self.kernal_out = s['kernal_out']
        self.min_pc     = s['_min_pc']
        self.max_pc     = s['_max_pc']

        raw = _AS_BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]   = self._code_blob


@pytest.fixture(scope="session")
def as_syms():
    """Session-scoped asm_src test binary + symbol addresses."""
    return AsmSrcSymbols()


# ── dasm test binary ─────────────────────────────────────────────────────────
#
# Links: dasm.s + dasm_tables.s + dasm_test_stub.s
# The stub provides banking helpers; ZP comes from zp.s.

_DASM_BIN = BUILD / "dasm_test.bin"
_DASM_MAP = BUILD / "dasm_test.map"
_DASM_LBL = BUILD / "dasm_test.lbl"

_DASM_SOURCES = [
    SRC / "zp.s",
    SRC / "dasm.s",
    SRC / "dasm_tables.s",
    SRC / "mem.s",                 # provides real kernal_bank_out/in
    DEV / "dasm_test_stub.s",
]


def _dasm_needs_rebuild():
    if not _DASM_BIN.exists() or not _DASM_LBL.exists():
        return True
    bin_mtime = _DASM_BIN.stat().st_mtime
    extra = [SRC / "dasm_mne_idx.s"]
    return any(s.stat().st_mtime > bin_mtime
               for s in _DASM_SOURCES + extra if s.exists())


def _dasm_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _DASM_SOURCES:
        obj = BUILD / f"{src.stem}_dasm.o"
        cmd = ["ca65", "-g", "--cpu", "6502", "-DCMOS_SUPPORT",
               "-I", str(SRC), "-I", str(BUILD),
               str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_DASM_BIN),
         "-m", str(_DASM_MAP),
         "-Ln", str(_DASM_LBL)],
        check=True,
    )


class DasmSymbols:
    """Resolved symbol addresses + binary loader for the dasm test.

    All symbols resolved from .lbl file (debug build) — no more BSS
    segment parsing or stub-offset fallback logic.
    """

    def __init__(self):
        if _dasm_needs_rebuild():
            _dasm_build()

        s = SymbolTable(_DASM_LBL)

        self.dasm_test_entry = s["dasm_test_entry"]
        self.asm_cpu         = s["asm_cpu"]
        self.dasm_buf        = s["dasm_buf"]

        raw = _DASM_BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]   = self._code_blob


@pytest.fixture(scope="session")
def dasm_syms():
    """Session-scoped dasm test binary + symbol addresses."""
    return DasmSymbols()


# ── mem test binary ──────────────────────────────────────────────────────────
#
# Links: zp.s + mem.s.  No stub needed — mem.s has no external code
# dependencies (just the linker-provided __ZP_LAST__ and __CODE_RUN__
# symbols plus the `kernal_out` ZP byte from zp.s).

_MEM_BIN = BUILD / "mem_test.bin"
_MEM_MAP = BUILD / "mem_test.map"
_MEM_LBL = BUILD / "mem_test.lbl"

_MEM_SOURCES = [
    SRC / "zp.s",
    SRC / "mem.s",
]


def _mem_needs_rebuild():
    if not _MEM_BIN.exists() or not _MEM_LBL.exists():
        return True
    bin_mtime = _MEM_BIN.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime
               for s in _MEM_SOURCES + [DEV / "test.cfg"])


def _mem_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _MEM_SOURCES:
        obj = BUILD / f"{src.stem}_mem.o"
        cmd = ["ca65", "-g", "--cpu", "6502",
               "-I", str(BUILD),
               str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         # mem.s imports __CODE_RUN__ from the production link
         # config; test.cfg doesn't generate it, so synthesise
         # a placeholder for cse_start to return.
         "-D", "__CODE_RUN__=$4000",
         *obj_files,
         "-o", str(_MEM_BIN),
         "-m", str(_MEM_MAP),
         "-Ln", str(_MEM_LBL)],
        check=True,
    )


class MemSymbols:
    """Resolved symbol addresses + binary loader for the mem.s test bundle."""

    def __init__(self):
        if _mem_needs_rebuild():
            _mem_build()

        s = SymbolTable(_MEM_LBL)

        # Entry points
        self.kernal_bank_out     = s["kernal_bank_out"]
        self.kernal_bank_in      = s["kernal_bank_in"]
        self.save_userland_zp    = s["save_userland_zp"]
        self.restore_userland_zp = s["restore_userland_zp"]
        self.save_kernel_zp      = s["save_kernel_zp"]
        self.restore_kernel_zp   = s["restore_kernel_zp"]
        self.cse_start           = s["cse_start"]
        self.cse_end             = s["cse_end"]
        self.cse_zp_end          = s["cse_zp_end"]

        # BSS
        self.userland_zp_buf = s["userland_zp_buf"]
        self.kernel_zp_buf   = s["kernel_zp_buf"]

        # ZP flag from zp.s
        self.kernal_out = s["kernal_out"]

        # Linker-defined segments (for assertions about cse_start/end)
        self.code_run = s["__CODE_RUN__"]
        self.zp_last  = s["__ZP_LAST__"]

        # _zp_end_val is a local RODATA byte but we can read it via the
        # lbl file (debug build exports @local labels too).
        self._zp_end_val = s.get("_zp_end_val")

        raw = _MEM_BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]  = self._code_blob


@pytest.fixture(scope="session")
def mem_syms():
    """Session-scoped mem.s test binary + symbol addresses."""
    return MemSymbols()


# ── log test bundle ──────────────────────────────────────────────────────────
#
# Links: zp + strings + cse_io + screen + log + cse_io_test_stub.
# The stub provides the shared `kplot_stub` symbol (KERNAL PLOT
# replacement using cse_io's own scr_lo/scr_hi tables).  The bundle
# is a downward slice through the L2 DAG: log (L2) uses screen (L2)
# and cse_io (L1); cse_io's one KERNAL dependency is PLOT, which the
# shared stub handles.  No behavioural mocks beyond PLOT.

_LOG_BIN = BUILD / "log_test.bin"
_LOG_MAP = BUILD / "log_test.map"
_LOG_LBL = BUILD / "log_test.lbl"

_LOG_SOURCES = [
    SRC / "zp.s",
    SRC / "strings.s",
    SRC / "cse_io.s",
    SRC / "screen.s",
    SRC / "log.s",
    DEV / "cse_io_test_stub.s",     # shared kplot_stub
]


def _log_needs_rebuild():
    if not _LOG_BIN.exists() or not _LOG_LBL.exists():
        return True
    bin_mtime = _LOG_BIN.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime
               for s in _LOG_SOURCES + [DEV / "test.cfg"])


def _log_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _LOG_SOURCES:
        obj = BUILD / f"{src.stem}_log.o"
        # -t c64 enables PETSCII char-literal translation, matching
        # the production build (Makefile AFLAGS).  Without it, ca65
        # encodes 'b' as ASCII $62 instead of PETSCII $42, which
        # breaks pet_to_scr's screen-code output for log.s's 'b'
        # byte-size suffix literal.
        cmd = ["ca65", "-g", "-t", "c64", "--cpu", "6502",
               "-I", str(BUILD),
               str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_LOG_BIN),
         "-m", str(_LOG_MAP),
         "-Ln", str(_LOG_LBL)],
        check=True,
    )


class LogSymbols:
    """Resolved symbols + binary loader for the log test bundle.

    Pre-resolves the documented log.s entry points and the ZP state
    that test cases prime before calling the range-line formatters.
    Access to RODATA strings and sibling exports (io_sync, scr_lo/hi,
    newline, str_*) is via `.s[name]` — the bundled SymbolTable.
    """

    def __init__(self):
        if _log_needs_rebuild():
            _log_build()

        self.s = SymbolTable(_LOG_LBL)
        s = self.s

        # log.s entry points
        self.log_open        = s["log_open"]
        self.log_close       = s["log_close"]
        self.log_line        = s["log_line"]
        self.log_err         = s["log_err"]
        self.log_warn        = s["log_warn"]
        self.log_info        = s["log_info"]
        self.puts_imm        = s["puts_imm"]
        self.seg_line        = s["seg_line"]
        self.prg_line        = s["prg_line"]
        self.free_line       = s["free_line"]
        self.info_line       = s["info_line"]
        self.info_line_head  = s["info_line_head"]
        self.info_line_tail  = s["info_line_tail"]

        # ZP inputs consumed by range-line formatters (zp.s)
        self.rp_ptr2         = s["rp_ptr2"]
        self.rp_addr         = s["rp_addr"]
        self.rp_cnt          = s["rp_cnt"]
        self.rp_save2        = s["rp_save2"]
        self._info_mode      = s["_info_mode"]

        # Sibling hooks used by setup helpers
        self.io_sync         = s["io_sync"]
        self.io_init         = s["io_init"]
        self.newline         = s["newline"]
        self.kplot_stub      = s["kplot_stub"]

        raw = _LOG_BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]  = self._code_blob


@pytest.fixture(scope="session")
def log_syms():
    """Session-scoped log test binary + symbol addresses."""
    return LogSymbols()


# ── gap_buffer test bundle ──────────────────────────────────────────────────
#
# Links: zp + strings + mem + symtab + gap_buffer.  No stub file —
# the bundle is pure source + linker-provided __CODE_RUN__ /
# __BUF_FLOOR__ (passed via ld65 -D).  gap_buffer.s is a pure
# L3 data-structure module (no KERNAL calls, no screen RAM, no
# BRK vectors); the mem + symtab modules come along because
# gap_buffer's `define_ws_syms` / `update_workend` call
# `sym_define`, which calls `kernal_bank_out/in` from mem.
# sym_table at $E000 is writable RAM in the bare-py65 harness,
# so the real symtab code runs without any mocking.

_GB_BIN = BUILD / "gap_buffer_test.bin"
_GB_MAP = BUILD / "gap_buffer_test.map"
_GB_LBL = BUILD / "gap_buffer_test.lbl"

_GB_SOURCES = [
    SRC / "zp.s",
    SRC / "strings.s",
    SRC / "mem.s",
    SRC / "symtab.s",
    SRC / "gap_buffer.s",
]


def _gb_needs_rebuild():
    if not _GB_BIN.exists() or not _GB_LBL.exists():
        return True
    bin_mtime = _GB_BIN.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime
               for s in _GB_SOURCES + [DEV / "test.cfg"])


def _gb_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _GB_SOURCES:
        obj = BUILD / f"{src.stem}_gb.o"
        cmd = ["ca65", "-g", "-t", "c64", "--cpu", "6502",
               "-I", str(BUILD),
               str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         # gap_buffer.s defines BUF_END := __CODE_RUN__ and
         # BUF_FLOOR := __BUF_FLOOR__.  The test bundle picks
         # production-representative values: CODE_RUN high in the
         # $4000-region test code area (leaving $1500..$3FFF as
         # workspace) and BUF_FLOOR at the same $1500 mark.
         "-D", "__CODE_RUN__=$4000",
         "-D", "__BUF_FLOOR__=$1500",
         *obj_files,
         "-o", str(_GB_BIN),
         "-m", str(_GB_MAP),
         "-Ln", str(_GB_LBL)],
        check=True,
    )


class GapBufferSymbols:
    """Resolved symbols + binary loader for the gap_buffer bundle.

    Pre-resolves gap_buffer.s's public entry points and the BSS / ZP
    state tests inspect (ed_total_lines, read_ptr, ed_dirty,
    buf_base, gap_lo, gap_hi).
    """

    def __init__(self):
        if _gb_needs_rebuild():
            _gb_build()

        self.s = SymbolTable(_GB_LBL)
        s = self.s

        # gap_buffer.s entry points
        self.gb_init            = s["gb_init"]
        self.ed_ensure_init     = s["ed_ensure_init"]
        self.gb_insert          = s["gb_insert"]
        self.gb_backspace       = s["gb_backspace"]
        self.gb_cursor_left     = s["gb_cursor_left"]
        self.gb_cursor_right    = s["gb_cursor_right"]
        self.gb_home            = s["gb_home"]
        self.gb_ensure_room     = s["gb_ensure_room"]
        self.ed_insert_string   = s["ed_insert_string"]
        self.ed_read_rewind     = s["ed_read_rewind"]
        self.ed_read_byte       = s["ed_read_byte"]
        self.ed_read_line       = s["ed_read_line"]
        self.check_buf_end      = s["check_buf_end"]

        # BSS owned by gap_buffer.s
        self.ed_total_lines     = s["ed_total_lines"]
        self.src_top            = s["src_top"]
        self.src_bot            = s["src_bot"]

        # ZP state tests inspect
        self.read_ptr           = s["read_ptr"]
        self.ed_dirty           = s["ed_dirty"]
        self.gap_lo             = s["gap_lo"]
        self.gap_hi             = s["gap_hi"]
        self.buf_base           = s["buf_base"]
        self.ed_top_ptr         = s["ed_top_ptr"]

        # Linker-provided workspace bounds
        self.BUF_END   = s["__CODE_RUN__"]
        self.BUF_FLOOR = s["__BUF_FLOOR__"]

        raw = _GB_BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]  = self._code_blob


@pytest.fixture(scope="session")
def gb_syms():
    """Session-scoped gap_buffer test binary + symbol addresses."""
    return GapBufferSymbols()


# ── C64Emu-based fixtures (Phase 9) ──────────────────────────────────────────
#
# These fixtures load the CMOS PRG into C64Emu and provide symbol
# resolution via the .map/.lbl file.  Two profiles are available:
#
#   cse_prg         — debug build (full .lbl with all symbols)
#   cse_release_prg — release build (for E2E integration tests)
#
# Most tests should use cse_prg (debug).  The richer symbol table
# (~1800 symbols vs ~230) makes debugging test failures much easier.

import subprocess

# Debug CMOS PRG (default for most tests)
_CMOS_DBG_PRG = ROOT / "build" / "debug" / "cmos" / "cse-cmos.prg"
_CMOS_DBG_MAP = ROOT / "build" / "debug" / "cmos" / "cse.map"

# Release CMOS PRG (for E2E integration tests)
_CMOS_REL_PRG = ROOT / "build" / "release" / "cmos" / "cse-cmos.prg"
_CMOS_REL_MAP = ROOT / "build" / "release" / "cmos" / "cse.map"


def _ensure_debug_built():
    """Build the debug CMOS PRG if not present."""
    if not _CMOS_DBG_PRG.exists() or not _CMOS_DBG_MAP.exists():
        subprocess.run(["make", "debug"], cwd=ROOT, check=True,
                       capture_output=True)


def _ensure_release_built():
    """Build the release CMOS PRG if not present."""
    if not _CMOS_REL_PRG.exists() or not _CMOS_REL_MAP.exists():
        subprocess.run(["make", "release"], cwd=ROOT, check=True,
                       capture_output=True)


@pytest.fixture(scope="session")
def cse_prg():
    """Session-scoped: debug CMOS PRG — used by most C64Emu tests."""
    _ensure_debug_built()
    return _CMOS_DBG_PRG, _CMOS_DBG_MAP


@pytest.fixture(scope="session")
def cse_release_prg():
    """Session-scoped: release CMOS PRG — for E2E integration tests."""
    _ensure_release_built()
    return _CMOS_REL_PRG, _CMOS_REL_MAP


# (Per-CPU-build PRG fixtures were introduced for integration-tier
# gate tests but retired once the gate tests moved to unit tier via
# the `asm_6510_syms` bundle in the asm_core family above.  Re-add
# here if a future integration-tier test needs the 6510/6502 PRGs.)
