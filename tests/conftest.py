"""
conftest.py – build test binaries and provide session-scoped fixtures.

Binaries are built once per session (cached in build/) and rebuilt
automatically whenever their source files are newer than the cached binary.
All test binaries are assembled with -g (debug symbols) and linked with
-Ln (VICE label file) so that ALL symbols — exported, internal, and
@local — are available at absolute addresses via SymbolTable.

Fixtures provided
-----------------
syms        — asm_core test binary symbols (for test_au_mode.py)
asm_syms    — asm_core test binary symbols (for test_asm_line.py)
mn6_syms    — mn6 hash test binary  (for test_mnhash.py)
mn7_syms    — mn7 hash test binary  (for test_mnhash.py)

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
# Shared by test_au_mode.py (mode_parse) and test_asm_line.py (_asm_line_core).
# The stub is minimal: BRK error handler + linker symbols for mem.s.
# No per-module mocking — every import is satisfied by real code.

_AC_BIN = BUILD / "asm_core_test.bin"
_AC_MAP = BUILD / "asm_core_test.map"
_AC_LBL = BUILD / "asm_core_test.lbl"

_AC_SOURCES = [
    SRC / "zp.s",
    SRC / "strings.s",
    SRC / "opcode_lookup.s",
    SRC / "asm_line.s",
    SRC / "addr_mode.s",
    SRC / "expr.s",
    SRC / "symtab.s",
    SRC / "mem.s",
    SRC / "mn_vars.s",
    SRC / "mn7.s",
    SRC / "mn7_tables.s",
    SRC / "mn_modes.s",
    SRC / "mn_asm_tables.s",
    SRC / "mn_classify.s",
    DEV / "asm_core_test_stub.s",
]


def _ac_needs_rebuild():
    if not _AC_BIN.exists() or not _AC_LBL.exists():
        return True
    bin_mtime = _AC_BIN.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime
               for s in _AC_SOURCES + [DEV / "test.cfg"])


def _ac_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _AC_SOURCES:
        obj = BUILD / f"{src.stem}_ac.o"
        cmd = ["ca65", "-g", "--cpu", "6502", "-DCMOS_SUPPORT",
               "-I", str(BUILD),
               str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_AC_BIN),
         "-m", str(_AC_MAP),
         "-Ln", str(_AC_LBL)],
        check=True,
    )


class AsmCoreSymbols:
    """Resolved symbol addresses + binary loader for the asm_core bundle.

    Provides addresses for both addr_mode tests (mode_parse, asm_ptr, asm_opr)
    and asm_line tests (_asm_line_core, asm_pc, asm_out, asm_cpu, etc.).
    All symbols resolved from .lbl file (debug build).
    """

    def __init__(self):
        if _ac_needs_rebuild():
            _ac_build()

        s = SymbolTable(_AC_LBL)

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

        raw = _AC_BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        """Write the test binary into a 64 KB memory bytearray."""
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]   = self._code_blob


@pytest.fixture(scope="session")
def syms():
    """Session-scoped asm_core binary — used by test_au_mode.py."""
    return AsmCoreSymbols()


@pytest.fixture(scope="session")
def asm_syms():
    """Session-scoped asm_core binary — used by test_asm_line.py."""
    return AsmCoreSymbols()


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
    'mn6': [SRC / "zp.s", SRC / "mn_vars.s", SRC / "mn6.s", SRC / "mn6_tables.s"],
    'mn7': [SRC / "zp.s", SRC / "mn_vars.s", SRC / "mn7.s", SRC / "mn7_tables.s"],
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

        self.mn_c1    = s['mn_c1']
        self.mn_c2    = s['mn_c2']
        self.mn_c3    = s['mn_c3']
        self.classify = s[f'{variant}_classify']

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
