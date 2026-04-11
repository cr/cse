"""
conftest.py – build test binaries and provide session-scoped fixtures.

Binaries are built once per session (cached in build/) and rebuilt
automatically whenever their source files are newer than the cached binary.

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


# ── asm_core bundle ──────────────────────────────────────────────────────────
#
# Links the full single-line assembler pipeline as one test binary.
# Shared by test_au_mode.py (mode_parse) and test_asm_line.py (line_asm).
# The stub is minimal: BRK error handler + linker symbols for mem.s.
# No per-module mocking — every import is satisfied by real code.

_AC_BIN = BUILD / "asm_core_test.bin"
_AC_MAP = BUILD / "asm_core_test.map"

_AC_SOURCES = [
    SRC / "asm_vars.s",
    SRC / "opcode_lookup.s",
    SRC / "asm_line.s",
    SRC / "au_mode.s",
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
    if not _AC_BIN.exists() or not _AC_MAP.exists():
        return True
    bin_mtime = _AC_BIN.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime
               for s in _AC_SOURCES + [DEV / "test.cfg"])


def _ac_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _AC_SOURCES:
        obj = BUILD / f"{src.stem}_ac.o"
        cmd = ["ca65", "--cpu", "6502", "-DCMOS_SUPPORT", str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_AC_BIN),
         "-m", str(_AC_MAP)],
        check=True,
    )


def _ac_parse_map_exports():
    """Return {symbol: address} for all exports in the asm_core map file."""
    syms = {}
    in_exports = False
    for line in _AC_MAP.read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            if line.strip() == "":
                break
            for name, addr in re.findall(r"(\w+)\s+([0-9a-fA-F]{6})\s+\w+", line):
                syms[name] = int(addr, 16)
    return syms


class AsmCoreSymbols:
    """Resolved symbol addresses + binary loader for the asm_core bundle.

    Provides addresses for both au_mode tests (mode_parse, asm_ptr, asm_opr)
    and asm_line tests (line_asm, asm_pc, asm_out, asm_cpu, etc.).
    """

    def __init__(self):
        if _ac_needs_rebuild():
            _ac_build()

        exports = _ac_parse_map_exports()

        # au_mode entry points
        self.mode_parse       = exports["mode_parse"]
        self.asm_skip_ws      = exports["asm_skip_ws"]
        self.asm_syntax_error = exports["asm_syntax_error"]

        # asm_line entry points
        self.line_asm         = exports["line_asm"]
        self.asm_error        = exports["asm_error"]

        # ZP variable addresses
        self.asm_ptr          = exports["asm_ptr"]
        self.asm_opr          = exports["asm_opr"]
        self.asm_pc           = exports["asm_pc"]
        self.asm_out          = exports["asm_out"]
        self.asm_len          = exports["asm_len"]
        self.asm_cpu          = exports["asm_cpu"]
        self._asm_saved_sp    = exports["_asm_saved_sp"]
        self.asm_pass         = exports["asm_pass"]

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
    'mn6': [SRC / "mn_vars.s", SRC / "mn6.s", SRC / "mn6_tables.s"],
    'mn7': [SRC / "mn_vars.s", SRC / "mn7.s", SRC / "mn7_tables.s"],
}
# Which source file contains the classify entry point label
_MN_CLASSIFY_SRC = {'mn6': SRC / "mn6.s", 'mn7': SRC / "mn7.s"}

_MN_BIN = {v: BUILD / f"{v}_test.bin" for v in ('mn6', 'mn7')}
_MN_MAP = {v: BUILD / f"{v}_test.map" for v in ('mn6', 'mn7')}
_MN_LST = {v: BUILD / f"{v}_classify.lst" for v in ('mn6', 'mn7')}

def _mn_needs_rebuild(variant):
    bin_path = _MN_BIN[variant]
    if not bin_path.exists():
        return True
    bin_mtime = bin_path.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime for s in _MN_SOURCES[variant])


def _mn_build(variant):
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _MN_SOURCES[variant]:
        obj = BUILD / (src.stem + f"_{variant}.o")
        cmd = ["ca65", "--cpu", "6502", str(src), "-o", str(obj)]
        # Generate listing for the classify source so we can find the label
        if src == _MN_CLASSIFY_SRC[variant]:
            cmd += ["--listing", str(_MN_LST[variant])]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_MN_BIN[variant]),
         "-m", str(_MN_MAP[variant])],
        check=True,
    )


def _mn_parse_map_exports(variant):
    """
    Return {symbol: address} for all exported ZP symbols in the map file.

    ld65 packs two entries per line in the exports section; use findall
    to capture both.  Only symbols with a 6-digit hex address are matched.
    """
    syms = {}
    in_exports = False
    for line in _MN_MAP[variant].read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            if line.strip() == "":
                break
            for name, addr in re.findall(r"(\w+)\s+([0-9a-fA-F]{6})\s+\w+", line):
                syms[name] = int(addr, 16)
    return syms


def _mn_parse_classify_addr(variant):
    """
    Return the absolute address of mnN_classify by parsing the ca65 listing.

    The listing encodes segment-relative offsets; add the CODE segment start.
    """
    label = f"{variant}_classify"
    for line in _MN_LST[variant].read_text().splitlines():
        m = re.match(r"^([0-9a-fA-F]+)r\s+\d+\s.*?\b" + re.escape(label) + r":", line)
        if m:
            return _CODE_START + int(m.group(1), 16)
    raise KeyError(f"{label} not found in listing {_MN_LST[variant]}")


class MnHashBinary:
    """Compiled mn6 or mn7 test binary with resolved symbol addresses."""

    def __init__(self, variant):
        if _mn_needs_rebuild(variant):
            _mn_build(variant)

        exports = _mn_parse_map_exports(variant)

        self.mn_c1    = exports['mn_c1']
        self.mn_c2    = exports['mn_c2']
        self.mn_c3    = exports['mn_c3']
        self.classify = _mn_parse_classify_addr(variant)

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
#   asm_vars + opcode_lookup + asm_line
#   + au_mode + mn_vars + mn7 + mn7_tables + mn_modes + mn_asm_tables
#   + mn_classify + expr + symtab + asm_src
#   + asm_src_test_stub  (provides ed_read_line, etc.)
#
# Linked with asm_src_test.cfg (adds DATA segment for asm_src.s).

_AS_BIN = BUILD / "asm_src_test.bin"
_AS_MAP = BUILD / "asm_src_test.map"
_AS_CFG = DEV / "asm_src_test.cfg"

_AS_SOURCES = [
    SRC / "asm_vars.s",
    SRC / "opcode_lookup.s",
    SRC / "asm_line.s",
    SRC / "au_mode.s",
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
    if not _AS_BIN.exists() or not _AS_MAP.exists():
        return True
    bin_mtime = _AS_BIN.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime for s in _AS_SOURCES + [_AS_CFG])


def _as_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _AS_SOURCES:
        obj = BUILD / f"{src.stem}_as.o"
        cmd = ["ca65", "--cpu", "6502", "-t", "c64", str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(_AS_CFG),
         *obj_files,
         "-o", str(_AS_BIN),
         "-m", str(_AS_MAP)],
        check=True,
    )


def _as_parse_map_exports():
    """Return {symbol: address} for all exports in the ld65 map file."""
    syms = {}
    in_exports = False
    for line in _AS_MAP.read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            if line.strip() == "":
                break
            for name, addr in re.findall(r"(\w+)\s+([0-9a-fA-F]{6})\s+\w+", line):
                syms[name] = int(addr, 16)
    return syms


def _as_parse_addrs():
    """Parse all needed absolute addresses from the asm_src test map file.

    Returns (asm_src_test_entry, test_src_buf, asm_org, asm_size, asm_errors,
             bank_witness).

    ld65 only includes a symbol in the "Exports list by name" if it is
    imported by at least one other module.  asm_src_test_entry,
    _test_src_buf, and _bank_witness are not imported by anyone, so we
    compute their addresses from segment-start + module-offset information
    in the map file:

      asm_src_test_entry = CODE_start + stub_CODE_offs  (first byte of stub CODE)
      _test_src_buf      = BSS_start  + stub_BSS_offs   + 0x0001
                           (after _src_done[1] in stub BSS)
      _bank_witness      = BSS_start  + stub_BSS_offs   + 0x0801
                           (after _src_done[1] + _test_src_buf[2048])

    asm_src.s's BSS vars (asm_org, asm_size, asm_errors) are not
    imported by anyone, so we compute from BSS_start + asm_src's offset:
      asm_org     = BSS_start + asm_src_bss_offs + 0
      asm_size    = BSS_start + asm_src_bss_offs + 2
      asm_errors  = BSS_start + asm_src_bss_offs + 4
    """
    text = _AS_MAP.read_text()
    lines = text.splitlines()

    # Segment starts (format: SEGNAME  start  end  size  align)
    seg = {}
    for line in lines:
        m = re.match(r"^(CODE|DATA|BSS)\s+([0-9a-fA-F]+)", line)
        if m:
            seg[m.group(1)] = int(m.group(2), 16)

    # Module offsets within CODE and BSS segments
    stub_code_offs = stub_bss_offs = None
    asm_src_bss_offs = None
    current_module = None
    for line in lines:
        if 'asm_src_test_stub_as.o:' in line:
            current_module = 'stub'
            continue
        if 'asm_src_as.o:' in line:
            current_module = 'asm_src'
            continue
        if current_module and not line.strip():
            current_module = None
            continue
        if current_module == 'stub':
            mc = re.match(r"\s+CODE\s+Offs=([0-9a-fA-F]+)", line)
            if mc:
                stub_code_offs = int(mc.group(1), 16)
            mb = re.match(r"\s+BSS\s+Offs=([0-9a-fA-F]+)", line)
            if mb:
                stub_bss_offs = int(mb.group(1), 16)
        if current_module == 'asm_src':
            mb = re.match(r"\s+BSS\s+Offs=([0-9a-fA-F]+)", line)
            if mb:
                asm_src_bss_offs = int(mb.group(1), 16)

    asm_src_test_entry = seg['CODE'] + stub_code_offs
    test_src_buf       = seg['BSS']  + stub_bss_offs + 0x0001
    bank_witness       = seg['BSS']  + stub_bss_offs + 0x0801
    asm_org            = seg['BSS']  + asm_src_bss_offs + 0
    asm_size           = seg['BSS']  + asm_src_bss_offs + 2
    asm_errors         = seg['BSS']  + asm_src_bss_offs + 4
    return (asm_src_test_entry, test_src_buf, asm_org, asm_size,
            asm_errors, bank_witness)


class AsmSrcSymbols:
    """Resolved symbol addresses + binary loader for the asm_src test."""

    def __init__(self):
        if _as_needs_rebuild():
            _as_build()

        (self.asm_src_test_entry,
         self.test_src_buf,
         self.asm_org,
         self.asm_size,
         self.asm_errors,
         self.bank_witness) = _as_parse_addrs()

        # Pull additional exports from the map (asm_line entry +
        # ZP locations needed for direct asm_line tests).
        exports = _as_parse_map_exports()
        self.asm_line   = exports['asm_line']
        self.asm_ptr    = exports['asm_ptr']
        self.asm_pc     = exports['asm_pc']
        self.asm_out    = exports['asm_out']
        self.asm_len    = exports['asm_len']
        self.kernal_out = exports['kernal_out']

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
# The stub provides asm_cpu (ZP) and exports dasm_test_entry.

_DASM_BIN = BUILD / "dasm_test.bin"
_DASM_MAP = BUILD / "dasm_test.map"

_DASM_SOURCES = [
    SRC / "dasm.s",
    SRC / "dasm_tables.s",
    DEV / "dasm_test_stub.s",
]


def _dasm_needs_rebuild():
    if not _DASM_BIN.exists():
        return True
    bin_mtime = _DASM_BIN.stat().st_mtime
    # Also check the include file
    extra = [SRC / "dasm_mne_idx.s"]
    return any(s.stat().st_mtime > bin_mtime
               for s in _DASM_SOURCES + extra if s.exists())


def _dasm_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _DASM_SOURCES:
        obj = BUILD / f"{src.stem}_dasm.o"
        cmd = ["ca65", "--cpu", "6502", "-DCMOS_SUPPORT",
               "-I", str(SRC), "-I", str(BUILD),
               str(src), "-o", str(obj)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_DASM_BIN),
         "-m", str(_DASM_MAP)],
        check=True,
    )


def _dasm_parse_map_exports():
    """Parse ALL exports — ld65 packs 2 per line."""
    syms = {}
    in_exports = False
    for line in _DASM_MAP.read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            if line.strip() == "" or line.startswith("---"):
                continue
            if line.startswith("Exports list by value") or line.startswith("Imports"):
                break
            for name, addr in re.findall(r"(\w+)\s+([0-9a-fA-F]{6})\s+\w+", line):
                syms[name] = int(addr, 16)
    return syms


class DasmSymbols:
    """Resolved symbol addresses + binary loader for the dasm test."""

    def __init__(self):
        if _dasm_needs_rebuild():
            _dasm_build()

        exports = _dasm_parse_map_exports()

        # dasm_test_entry might not be in exports (not imported by anyone).
        # Use _dasm_insn as fallback and compute stub entry from segment info.
        if "dasm_test_entry" in exports:
            self.dasm_test_entry = exports["dasm_test_entry"]
        else:
            # The stub is the last CODE contributor; its entry is at a known
            # offset from the segment end.  Parse from the map file.
            seg_info = {}
            for line in _DASM_MAP.read_text().splitlines():
                m = re.match(r"(\w+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)", line)
                if m and m.group(1) == 'CODE':
                    seg_info['start'] = int(m.group(2), 16)
                    seg_info['end']   = int(m.group(3), 16)
                    seg_info['size']  = int(m.group(4), 16)
            # Find stub offset from module list
            for line in _DASM_MAP.read_text().splitlines():
                m = re.match(r"\s+CODE\s+Offs=([0-9a-fA-F]+)\s+Size=", line)
                if m:
                    stub_offs = int(m.group(1), 16)
            self.dasm_test_entry = seg_info['start'] + stub_offs

        self.asm_cpu  = exports["asm_cpu"]
        # _dasm_buf is in BSS — first BSS symbol, not imported so not in exports.
        # Parse BSS segment start from the map.
        for line in _DASM_MAP.read_text().splitlines():
            m = re.match(r"BSS\s+([0-9a-fA-F]+)\s+", line)
            if m:
                self.dasm_buf = int(m.group(1), 16)
                break
        else:
            raise KeyError("BSS segment not found in map")

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
# These fixtures load the CMOS production PRG into C64Emu and provide
# symbol resolution via the .lbl file.  Used by test_editor_asm.py,
# test_screen_asm.py, test_step_rom.py, and future C64Emu-based tests.

import subprocess

_CMOS_PRG = ROOT / "build" / "cmos" / "cse-cmos.prg"
_CMOS_MAP = ROOT / "build" / "cmos" / "cse.map"


def _ensure_cmos_built():
    """Build the CMOS PRG if not present."""
    if not _CMOS_PRG.exists() or not _CMOS_MAP.exists():
        subprocess.run(["make", "CPU=65c02"], cwd=ROOT, check=True,
                       capture_output=True)


@pytest.fixture(scope="session")
def cse_prg():
    """Session-scoped: CMOS PRG path + map path, auto-built."""
    _ensure_cmos_built()
    return _CMOS_PRG, _CMOS_MAP
