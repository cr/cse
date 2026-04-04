"""
conftest.py – build test binaries and provide session-scoped fixtures.

Binaries are built once per session (cached in build/) and rebuilt
automatically whenever their source files are newer than the cached binary.

Fixtures provided
-----------------
syms        — au_mode test binary symbols (for test_au_mode.py)
mn6_syms    — mn6 hash test binary  (for test_mnhash.py)
mn7_syms    — mn7 hash test binary  (for test_mnhash.py)
al_syms     — asm_line test binary symbols (for test_asm_line.py)
"""

import re
import subprocess
import pathlib
import pytest

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

BIN   = BUILD / "au_mode_test.bin"
MAP   = BUILD / "au_mode_test.map"
LST   = BUILD / "au_mode_test.lst"


# ── build helpers ─────────────────────────────────────────────────────────────

def _needs_rebuild():
    if not BIN.exists() or not LST.exists() or not MAP.exists():
        return True
    bin_mtime = BIN.stat().st_mtime
    sources = [
        SRC / "au_mode.s",
        DEV / "au_mode_test_stub.s",
        DEV / "test.cfg",
    ]
    return any(s.stat().st_mtime > bin_mtime for s in sources)


def _build():
    BUILD.mkdir(exist_ok=True)
    subprocess.run(
        ["ca65", "--cpu", "6502",
         "--listing", str(LST),
         str(SRC / "au_mode.s"),
         "-o", str(BUILD / "au_mode.o")],
        check=True,
    )
    subprocess.run(
        ["ca65", "--cpu", "6502",
         str(DEV / "au_mode_test_stub.s"),
         "-o", str(BUILD / "au_mode_test_stub.o")],
        check=True,
    )
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         str(BUILD / "au_mode.o"),
         str(BUILD / "au_mode_test_stub.o"),
         "-o", str(BIN),
         "-m", str(MAP)],
        check=True,
    )


def _parse_segment_starts():
    """Return dict of segment_name -> start_address from the ld65 map file."""
    starts = {}
    in_seg = False
    for line in MAP.read_text().splitlines():
        if line.startswith("Segment list"):
            in_seg = True
            continue
        if in_seg:
            m = re.match(r"(\w+)\s+([0-9a-fA-F]+)\s+", line)
            if m:
                starts[m.group(1)] = int(m.group(2), 16)
    return starts


def _parse_sym_offsets():
    """
    Return dict of label -> offset-within-segment, parsed from the ca65
    listing.  Listing lines look like:
        000099r 1               au_parse_mode:
    The hex prefix is the offset; 'r' = relocatable (segment-relative).
    """
    offsets = {}
    for line in LST.read_text().splitlines():
        m = re.match(r"^([0-9a-fA-F]+)r\s+\d+\s.*?\b(\w+):", line)
        if m:
            offsets[m.group(2)] = int(m.group(1), 16)
    return offsets


def _parse_exported_syms():
    """
    Return dict of name -> absolute_address from the 'Exports list by name'
    section of the ld65 map file (covers stub-provided symbols).
    """
    syms = {}
    in_exports = False
    for line in MAP.read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            m = re.match(r"(\w+)\s+([0-9a-fA-F]+)", line)
            if m:
                syms[m.group(1)] = int(m.group(2), 16)
            elif line.strip() == "":
                break
    return syms


class Symbols:
    """Absolute addresses of the key symbols in the test binary."""

    def __init__(self):
        if _needs_rebuild():
            _build()

        seg  = _parse_segment_starts()
        ofs  = _parse_sym_offsets()
        exp  = _parse_exported_syms()

        zp   = seg["ZEROPAGE"]
        code = seg["CODE"]

        self.au_parse_mode   = code + ofs["au_parse_mode"]
        self.au_ptr          = zp   + ofs["au_ptr"]
        self.au_opr          = zp   + ofs["au_opr"]
        self.au_syntax_error = exp["au_syntax_error"]

        # The flat binary maps two non-contiguous memory regions:
        #   file[0 .. ZP_SIZE-1]         → mem[ZP_START .. ZP_START+ZP_SIZE-1]
        #   file[ZP_SIZE .. end]          → mem[CODE_REGION_START .. ...]
        zp_size       = seg.get("ZP_SIZE", 0x100)   # always $100 per test.cfg
        self._zp_start    = zp
        self._code_start  = code
        self._zp_size     = zp_size
        self._raw         = BIN.read_bytes()

    def load_into(self, memory):
        """Write the test binary into a 64 KB memory bytearray."""
        # ZP region: first zp_size bytes of the flat binary
        memory[self._zp_start : self._zp_start + self._zp_size] = \
            self._raw[: self._zp_size]
        # CODE region: remainder of the flat binary
        code_blob = self._raw[self._zp_size :]
        memory[self._code_start : self._code_start + len(code_blob)] = code_blob


@pytest.fixture(scope="session")
def syms():
    """Session-scoped symbol table + binary loader."""
    return Symbols()


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

# test.cfg constants (fixed layout, no need to parse)
_ZP_START   = 0x0000
_CODE_START = 0x0200
_ZP_SIZE    = 0x0100


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


# ── asm_line test binary ───────────────────────────────────────────────────────
#
# Links the full single-line assembler pipeline:
#   asm_vars + parse_hex + opcode_lookup + asm_line
#   + au_mode + mn_vars + mn7 + mn7_tables + mn_modes + mn_asm_tables + mn_classify
#   + asm_line_test_stub  (provides al_error and au_syntax_error)
#
# The listing of asm_line.s is used to resolve al_line_asm.
# All ZP exports (au_ptr, al_pc, al_out, al_len, al_cpu, al_error) are read
# from the ld65 map file.

_AL_BIN = BUILD / "asm_line_test.bin"
_AL_MAP = BUILD / "asm_line_test.map"
_AL_LST = BUILD / "asm_line_test.lst"

_AL_SOURCES = [
    SRC / "asm_vars.s",
    SRC / "parse_hex.s",
    SRC / "opcode_lookup.s",
    SRC / "asm_line.s",
    SRC / "au_mode.s",
    SRC / "mn_vars.s",
    SRC / "mn7.s",
    SRC / "mn7_tables.s",
    SRC / "mn_modes.s",
    SRC / "mn_asm_tables.s",
    SRC / "mn_classify.s",
    DEV / "asm_line_test_stub.s",
]


def _al_needs_rebuild():
    if not _AL_BIN.exists() or not _AL_MAP.exists() or not _AL_LST.exists():
        return True
    bin_mtime = _AL_BIN.stat().st_mtime
    return any(s.stat().st_mtime > bin_mtime for s in _AL_SOURCES)


def _al_build():
    BUILD.mkdir(exist_ok=True)
    obj_files = []
    for src in _AL_SOURCES:
        obj = BUILD / f"{src.stem}_al.o"
        cmd = ["ca65", "--cpu", "6502", "-DCMOS_SUPPORT", str(src), "-o", str(obj)]
        if src.name == "asm_line.s":
            cmd += ["--listing", str(_AL_LST)]
        subprocess.run(cmd, check=True)
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         *obj_files,
         "-o", str(_AL_BIN),
         "-m", str(_AL_MAP)],
        check=True,
    )


def _al_parse_map_exports():
    """Return {symbol: address} for all exports in the ld65 map file."""
    syms = {}
    in_exports = False
    for line in _AL_MAP.read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            if line.strip() == "":
                break
            for name, addr in re.findall(r"(\w+)\s+([0-9a-fA-F]{6})\s+\w+", line):
                syms[name] = int(addr, 16)
    return syms


def _al_parse_map_entry(label):
    """Return the absolute address of a CODE label from the ld65 map file.

    asm_line.s exports al_line_asm, and the test stub imports it so that
    ld65 includes it in the 'Exports list by name' section.  This is more
    reliable than adding the listing offset to _CODE_START because several
    other object files contribute CODE before asm_line.s.
    """
    exports = _al_parse_map_exports()
    if label in exports:
        return exports[label]
    raise KeyError(f"{label!r} not found in map exports {_AL_MAP}")


class AsmLineSymbols:
    """Resolved symbol addresses + binary loader for the asm_line test."""

    def __init__(self):
        if _al_needs_rebuild():
            _al_build()

        exports = _al_parse_map_exports()

        # ZP variable addresses (from exports)
        self.au_ptr      = exports["au_ptr"]
        self.al_pc       = exports["al_pc"]
        self.al_out      = exports["al_out"]
        self.al_len      = exports["al_len"]
        self.al_cpu      = exports["al_cpu"]
        self.al_error    = exports["al_error"]

        # Code entry point (from map exports — stub imports al_line_asm to
        # force ld65 to include it in the Exports list by name section)
        self.al_line_asm = _al_parse_map_entry("al_line_asm")

        raw = _AL_BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        """Write the test binary into a 64 KB memory bytearray."""
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]   = self._code_blob


@pytest.fixture(scope="session")
def al_syms():
    """Session-scoped asm_line test binary + symbol addresses."""
    return AsmLineSymbols()


# ── asm_src test binary ───────────────────────────────────────────────────────
#
# Links the full two-pass assembler pipeline:
#   asm_vars + parse_hex + opcode_lookup + asm_line + asm_bridge
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
    SRC / "parse_hex.s",
    SRC / "opcode_lookup.s",
    SRC / "asm_line.s",
    SRC / "asm_bridge.s",
    SRC / "au_mode.s",
    SRC / "mn_vars.s",
    SRC / "mn7.s",
    SRC / "mn7_tables.s",
    SRC / "mn_modes.s",
    SRC / "mn_asm_tables.s",
    SRC / "mn_classify.s",
    SRC / "expr.s",
    SRC / "symtab.s",
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

    Returns (asm_src_test_entry, test_src_buf, asm_org, asm_size, asm_errors).

    ld65 only includes a symbol in the "Exports list by name" if it is
    imported by at least one other module.  asm_src_test_entry and
    _test_src_buf are not imported by anyone, so we compute their addresses
    from segment-start + module-offset information in the map file:

      asm_src_test_entry = CODE_start + stub_CODE_offs  (first byte of stub CODE)
      _test_src_buf      = BSS_start  + stub_BSS_offs   + 0x0001
                           (after _src_done[1] in stub BSS)

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
    asm_org            = seg['BSS']  + asm_src_bss_offs + 0
    asm_size           = seg['BSS']  + asm_src_bss_offs + 2
    asm_errors         = seg['BSS']  + asm_src_bss_offs + 4
    return asm_src_test_entry, test_src_buf, asm_org, asm_size, asm_errors


class AsmSrcSymbols:
    """Resolved symbol addresses + binary loader for the asm_src test."""

    def __init__(self):
        if _as_needs_rebuild():
            _as_build()

        (self.asm_src_test_entry,
         self.test_src_buf,
         self.asm_org,
         self.asm_size,
         self.asm_errors) = _as_parse_addrs()

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
# The stub provides al_cpu (ZP) and exports dasm_test_entry.

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

        self.al_cpu   = exports["al_cpu"]
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
