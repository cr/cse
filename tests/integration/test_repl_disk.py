"""
test_repl_disk.py — Save/Load command tests (disk ops) for repl.s.

Covers the `s` and `l` commands: argument parsing, verbatim vs derived
naming, project-name reuse, SEQ vs PRG routing.  These tests still use
the bare-MPU + repl_test_stub.s harness because they assert on stub
witness variables that capture what args were passed to KERNAL disk
primitives — a proper virtual IEC is still deferred.

When the virtual IEC lands, these tests migrate to C64Emu and this
file folds back into test_repl.py.  Until then, they live here
unchanged.

Test binary: repl.s + cse_io.s + expr.s + symtab.s + dasm.s
             + repl_test_stub.s
"""

import subprocess, pathlib, re, pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

BIN = BUILD / "repl_test.bin"
MAP = BUILD / "repl_test.map"
CFG = DEV / "repl_test.cfg"

SCREEN = 0x0400
COLS   = 40
ROWS   = 25
CUR_COL = 0xD3
CUR_ROW = 0xD6
KERNAL_PLOT = 0xFFF0

_ZP_START   = 0x0000
_SCRN_START = 0x0200
_SCRN_SIZE  = 0x0600
_CODE_START = 0x4000
_ZP_SIZE    = 0x0100
_RETURN     = 0x0300          # in SCRN gap, unused — RTS sentinel

_SOURCES = [
    SRC / "zp.s",
    SRC / "strings.s",
    SRC / "repl.s",
    SRC / "cse_io.s",
    SRC / "expr.s",
    SRC / "symtab.s",
    SRC / "mem.s",
    SRC / "dasm.s",
    SRC / "dasm_tables.s",
    SRC / "log.s",
    SRC / "oplen_tbl.s",
    DEV / "repl_test_stub.s",
    CFG,
]


def _needs_rebuild():
    if not BIN.exists() or not MAP.exists():
        return True
    t = BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in _SOURCES)


def _build():
    BUILD.mkdir(exist_ok=True)
    src_files = [s for s in _SOURCES if s.suffix == '.s']
    obj_files = []
    for src in src_files:
        stem = src.stem
        obj = BUILD / f"{stem}_repl.o"
        subprocess.run(
            ["ca65", "-t", "c64", "--cpu", "6502", "-DCMOS_SUPPORT", "-DCPU_CEIL=2",
             "-I", str(BUILD),
             str(src), "-o", str(obj)],
            check=True,
        )
        obj_files.append(str(obj))
    subprocess.run(
        ["ld65", "-C", str(CFG),
         *obj_files,
         "-o", str(BIN), "-m", str(MAP)],
        check=True,
    )


def _parse_map():
    """Parse segments, module offsets, and exports from the ld65 map file."""
    text = MAP.read_text()
    lines = text.splitlines()

    segments = {}
    for line in lines:
        m = re.match(r'^(CODE|BSS|RODATA|ZEROPAGE|DATA)\s+([0-9a-fA-F]+)\s+', line)
        if m:
            segments[m.group(1)] = int(m.group(2), 16)

    modules = {}
    cur_mod = None
    for line in lines:
        m = re.match(r'^(\w+\.o):', line)
        if m:
            cur_mod = m.group(1)
            modules[cur_mod] = {}
            continue
        if cur_mod:
            m = re.match(r'\s+(CODE|BSS|RODATA|ZEROPAGE)\s+Offs=([0-9a-fA-F]+)', line)
            if m:
                modules[cur_mod][m.group(1)] = int(m.group(2), 16)
            elif not line.startswith(' ') and line.strip():
                cur_mod = None

    exports = {}
    in_exp = False
    for line in lines:
        if "Exports list by name" in line:
            in_exp = True
            continue
        if in_exp:
            for m in re.finditer(r'(\w+)\s+([0-9a-fA-F]{6})\s+\w+', line):
                exports[m.group(1)] = int(m.group(2), 16)
            if line.strip() == "" or "Exports list by value" in line:
                break

    return segments, modules, exports


class ReplSymbols:
    """Resolved symbol addresses + binary loader for the repl test."""

    def __init__(self):
        if _needs_rebuild():
            _build()

        seg, mods, exp = _parse_map()

        self.exec_line   = exp['exec_line']
        self.cur_addr    = exp['cur_addr']
        self.cur_device  = exp['cur_device']
        self.cur_project_name = exp['cur_project_name']
        self.line_buf    = exp['line_buf']
        self.block_size  = exp['block_size']
        self.asm_cpu     = exp['asm_cpu']

        # Stub-only addresses from rodata sym_refs table
        stub_mod = 'repl_test_stub_repl.o'
        rodata_offs = mods[stub_mod].get('RODATA', 0)
        rodata_base = seg['RODATA'] + rodata_offs
        bin_data = BIN.read_bytes()
        def read_word(addr):
            if addr >= _CODE_START:
                off = _ZP_SIZE + _SCRN_SIZE + (addr - _CODE_START)
            elif addr >= _SCRN_START:
                off = _ZP_SIZE + (addr - _SCRN_START)
            else:
                off = addr
            return bin_data[off] | (bin_data[off + 1] << 8)
        self.kplot_stub    = read_word(rodata_base + 10 * 2)
        self.save_addr     = read_word(rodata_base + 11 * 2)
        self.save_size     = read_word(rodata_base + 12 * 2)
        self.load_result   = read_word(rodata_base + 13 * 2)
        self.save_name     = read_word(rodata_base + 14 * 2)
        self.load_name     = read_word(rodata_base + 15 * 2)
        self.op_witness    = read_word(rodata_base + 16 * 2)

        raw = BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._scrn_blob = raw[_ZP_SIZE:_ZP_SIZE + _SCRN_SIZE]
        self._code_blob = raw[_ZP_SIZE + _SCRN_SIZE:]

    def load_into(self, memory):
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE] = self._zp_blob
        memory[_SCRN_START : _SCRN_START + _SCRN_SIZE] = self._scrn_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)] = self._code_blob


@pytest.fixture(scope="session")
def rsyms():
    return ReplSymbols()


def make_cpu(rsyms):
    cpu = MPU()
    rsyms.load_into(cpu.memory)

    kplot = rsyms.kplot_stub
    cpu.memory[KERNAL_PLOT]     = 0x4C
    cpu.memory[KERNAL_PLOT + 1] = kplot & 0xFF
    cpu.memory[KERNAL_PLOT + 2] = (kplot >> 8) & 0xFF

    cpu.memory[CUR_ROW] = 5
    cpu.memory[CUR_COL] = 0
    row = 5
    screen_addr = SCREEN + row * COLS
    cpu.memory[0xD1] = screen_addr & 0xFF
    cpu.memory[0xD2] = (screen_addr >> 8) & 0xFF
    color_addr = 0xD800 + row * COLS
    cpu.memory[0xF3] = color_addr & 0xFF
    cpu.memory[0xF4] = (color_addr >> 8) & 0xFF

    for i in range(COLS * ROWS):
        cpu.memory[SCREEN + i] = 0x20

    cpu.memory[rsyms.asm_cpu] = 1
    set_word(cpu, rsyms.block_size, 0x0010)
    cpu.memory[rsyms.cur_device] = 8
    return cpu


MAX_CYCLES = 500_000


def run_at(cpu, addr):
    ret = _RETURN
    cpu.memory[ret] = 0xEA
    cpu.sp = 0xFD
    cpu.memory[0x01FF] = ((ret - 1) >> 8) & 0xFF
    cpu.memory[0x01FE] = (ret - 1) & 0xFF
    cpu.pc = addr
    cycles = 0
    while cycles < MAX_CYCLES:
        if cpu.pc == ret:
            return cycles
        cpu.step()
        cycles += 1
    raise RuntimeError(f"Timeout after {MAX_CYCLES} cycles at ${cpu.pc:04X}")


def ascii_to_petscii(ch):
    if 0x61 <= ch <= 0x7A:
        return ch - 0x20
    if 0x41 <= ch <= 0x5A:
        return ch + 0x80
    return ch


def set_line_buf(cpu, rsyms, text):
    if isinstance(text, str):
        data = text.encode('ascii')
    else:
        data = text
    for i, b in enumerate(data):
        cpu.memory[rsyms.line_buf + i] = ascii_to_petscii(b)
    cpu.memory[rsyms.line_buf + len(data)] = 0


def set_cur_addr(cpu, rsyms, addr):
    cpu.memory[rsyms.cur_addr]     = addr & 0xFF
    cpu.memory[rsyms.cur_addr + 1] = (addr >> 8) & 0xFF


def get_word(cpu, addr):
    return cpu.memory[addr] | (cpu.memory[addr + 1] << 8)


def set_word(cpu, addr, val):
    cpu.memory[addr] = val & 0xFF
    cpu.memory[addr + 1] = (val >> 8) & 0xFF


def get_cur_project_name(cpu, rsyms):
    chars = []
    for i in range(17):
        b = cpu.memory[rsyms.cur_project_name + i]
        if b == 0:
            break
        chars.append(chr(b) if 0x20 <= b < 0x80 else '?')
    return ''.join(chars)


OP_NONE     = 0
OP_PRG_SAVE = 1
OP_SEQ_SAVE = 2
OP_PRG_LOAD = 3
OP_SEQ_LOAD = 4


def get_name(cpu, base, maxlen=17):
    chars = []
    for i in range(maxlen):
        b = cpu.memory[base + i]
        if b == 0:
            break
        chars.append(chr(b) if 0x20 <= b < 0x80 else '?')
    return ''.join(chars)


def clear_witness(cpu, rsyms):
    cpu.memory[rsyms.op_witness] = OP_NONE
    set_word(cpu, rsyms.save_addr, 0xFFFF)
    set_word(cpu, rsyms.save_size, 0xFFFF)
    for i in range(17):
        cpu.memory[rsyms.save_name + i] = 0
        cpu.memory[rsyms.load_name + i] = 0


class TestSaveCommand:
    """Save via 's' command — argument parsing + disk stub witness.

    New semantics (project-name-centric):
      bare `s "name"`           → SEQ save, disk name = "name"
      `s "name" $end`           → PRG save, disk name = "name."
      `s "name,s"`              → verbatim SEQ, disk name = "name"
      `s "name,p"`              → verbatim PRG, disk name = "name"
      cur_project_name stores the stripped stem (no suffix, no trailing dot)
    """

    # ── Derivation (bare name → SEQ) ──────────────────────────────────

    def test_save_seq_bare(self, rsyms):
        """s "foo" → SEQ save; disk name = "foo"; project = "foo"."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo"')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_SAVE
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        assert get_name(cpu, rsyms.save_name) == "FOO"

    def test_save_prg_derived(self, rsyms):
        """s "foo" $0900 → PRG save; disk name = "foo."; project = "foo"."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo" $0900')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_SAVE
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        assert get_name(cpu, rsyms.save_name) == "FOO."
        assert get_word(cpu, rsyms.save_addr) == 0x0800
        assert get_word(cpu, rsyms.save_size) == 0x0101

    def test_save_strip_trailing_dot(self, rsyms):
        """s "foo." → project_name = "foo" (trailing dot stripped)."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo."')
        run_at(cpu, rsyms.exec_line)
        assert get_cur_project_name(cpu, rsyms) == "FOO"

    # ── Verbatim forms (,s/,p suffix disables derivation) ─────────────

    def test_save_verbatim_seq(self, rsyms):
        """s "foo,s" → verbatim SEQ; disk name = "foo"; project = "foo"."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo,s"')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_SAVE
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        assert get_name(cpu, rsyms.save_name) == "FOO"

    def test_save_verbatim_prg(self, rsyms):
        """s "foo,p" → verbatim PRG; disk name = "foo" (no dot appended)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo,p"')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_SAVE
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        assert get_name(cpu, rsyms.save_name) == "FOO"

    def test_save_verbatim_prg_with_dot(self, rsyms):
        """s "foo.,p" → verbatim PRG keeps user's dot; project = "foo"."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo.,p"')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_SAVE
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        assert get_name(cpu, rsyms.save_name) == "FOO."

    # ── End-address table (save PRG) ──────────────────────────────────

    def test_save_end_blocksize_fallback(self, rsyms):
        """End=0 (no arg) → end = start + block_size."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo,p"')
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.save_addr) == 0x0800
        assert get_word(cpu, rsyms.save_size) == 0x0010

    def test_save_end_from_arg(self, rsyms):
        """1 arg → start = cur_addr, end = arg (INCLUSIVE)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo" $0900')
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.save_addr) == 0x0800
        assert get_word(cpu, rsyms.save_size) == 0x0101

    def test_save_two_args(self, rsyms):
        """2 args → start = arg1, end = arg2 (INCLUSIVE)."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo" $1000 $2000')
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.save_addr) == 0x1000
        assert get_word(cpu, rsyms.save_size) == 0x1001

    def test_save_end_length_fallback(self, rsyms):
        """2 args, end <= start → end = length."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo" $1000 $100')
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.save_addr) == 0x1000
        assert get_word(cpu, rsyms.save_size) == 0x0100

    # ── Project-name reuse ────────────────────────────────────────────

    def test_save_no_name_defaults_to_out(self, rsyms):
        """Empty cur_project_name + bare `s` → defaults to "out"."""
        cpu = make_cpu(rsyms)
        cpu.memory[rsyms.cur_project_name] = 0
        set_cur_addr(cpu, rsyms, 0x0800)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, "s")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_SAVE
        assert get_name(cpu, rsyms.save_name) == "OUT"

    def test_save_reuse_prev_name(self, rsyms):
        """s "foo" then bare s → reuses "foo"."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        set_line_buf(cpu, rsyms, 's "foo"')
        run_at(cpu, rsyms.exec_line)
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, "s")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_SAVE
        assert get_name(cpu, rsyms.save_name) == "FOO"

    def test_save_unquoted_is_expr(self, rsyms):
        """s $0900 — unquoted arg is inclusive end (args force PRG)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        for i, ch in enumerate(b"prev"):
            cpu.memory[rsyms.cur_project_name + i] = ascii_to_petscii(ch)
        cpu.memory[rsyms.cur_project_name + 4] = 0
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, "s $0900")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_SAVE
        assert get_name(cpu, rsyms.save_name) == "PREV."
        assert get_word(cpu, rsyms.save_addr) == 0x0800
        assert get_word(cpu, rsyms.save_size) == 0x0101

    def test_save_addr_prefix(self, rsyms):
        """0801:s "test" $2004 — AAAA: prefix sets cur_addr (start)."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, '0801:s "test" $2004')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_SAVE
        assert get_name(cpu, rsyms.save_name) == "TEST."
        assert get_word(cpu, rsyms.save_addr) == 0x0801
        assert get_word(cpu, rsyms.save_size) == 0x2004 - 0x0801 + 1


class TestLoadCommand:
    """Load via 'l' command — argument parsing + disk stub witness.

    New semantics:
      bare `l "name"`           → SEQ load (ed_load_source)
      `l "name" $addr`          → PRG load, target = $addr
      `l "name" 0`              → PRG load, target = PRG header addr
      `l "name,s"`              → verbatim SEQ
      `l "name,p"`              → verbatim PRG (no args needed)
    """

    # ── SEQ loads ─────────────────────────────────────────────────────

    def test_load_seq_bare(self, rsyms):
        """l "foo" → SEQ load; project = "foo"."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 'l "foo"')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_LOAD
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        assert get_name(cpu, rsyms.load_name) == "FOO"

    def test_load_verbatim_seq(self, rsyms):
        """l "foo,s" → verbatim SEQ."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 'l "foo,s"')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_LOAD
        assert get_name(cpu, rsyms.load_name) == "FOO"

    # ── PRG loads ─────────────────────────────────────────────────────

    def test_load_prg_header_addr(self, rsyms):
        """l "foo" 0 → PRG load at header address (end=0 triggers SA=1)."""
        cpu = make_cpu(rsyms)
        set_word(cpu, rsyms.load_result, 0x0900)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 'l "foo" 0')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_LOAD
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        assert get_name(cpu, rsyms.load_name) == "FOO."

    def test_load_prg_with_addr(self, rsyms):
        """l "foo" $c000 → PRG load to $c000."""
        cpu = make_cpu(rsyms)
        set_word(cpu, rsyms.load_result, 0xC010)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 'l "foo" $c000')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_LOAD
        assert get_name(cpu, rsyms.load_name) == "FOO."

    def test_load_verbatim_prg(self, rsyms):
        """l "foo,p" → verbatim PRG load, disk name = "foo" (no dot)."""
        cpu = make_cpu(rsyms)
        set_word(cpu, rsyms.load_result, 0x0900)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 'l "foo,p"')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_LOAD
        assert get_name(cpu, rsyms.load_name) == "FOO"

    def test_load_verbatim_prg_with_dot(self, rsyms):
        """l "foo.,p" → verbatim PRG, disk name keeps dot."""
        cpu = make_cpu(rsyms)
        set_word(cpu, rsyms.load_result, 0x0900)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 'l "foo.,p"')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_LOAD
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        assert get_name(cpu, rsyms.load_name) == "FOO."

    # ── Symmetry: round-trip project name ─────────────────────────────

    def test_load_save_symmetry(self, rsyms):
        """l "foo" then s (bare) saves as SEQ "foo"."""
        cpu = make_cpu(rsyms)
        set_line_buf(cpu, rsyms, 'l "foo"')
        run_at(cpu, rsyms.exec_line)
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, "s")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_SAVE
        assert get_name(cpu, rsyms.save_name) == "FOO"


class TestUnterminatedQuote:
    """Unterminated quoted name (opening `"` without closing) is a
    syntax error that aborts the command before any disk I/O.

    Pre-fix bug (TODO.md): `l "foo` (no closing quote) reported
    `;?expr undef` and *still* loaded the file `foo` from disk.
    Two issues conflated:
      (a) the parse error didn't abort — a load fired anyway;
      (b) the error class was `expr undef`, not `syntax`, because
          the unterminated name's bytes were re-parsed by the
          numeric-arg path as a label expression.

    Contract (per repl.md § Argument parsing): unterminated
    string → `;?syntax` and no disk operation.
    """

    def test_load_unterminated_quote_aborts(self, rsyms):
        """`l "foo` (unterminated) → no load."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 'l "foo')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_NONE, \
            "load fired despite unterminated quote"

    def test_save_unterminated_quote_aborts(self, rsyms):
        """`s "foo` (unterminated) → no save."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo')
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_NONE, \
            "save fired despite unterminated quote"

    def test_unterminated_quote_does_not_corrupt_project_name(self, rsyms):
        """The aborted command must not have updated cur_project_name
        with the partial token.  Pre-existing project name (or empty)
        stays untouched."""
        cpu = make_cpu(rsyms)
        # Pre-set cur_project_name = "BAR"
        for i, c in enumerate("BAR"):
            cpu.memory[rsyms.cur_project_name + i] = ord(c)
        cpu.memory[rsyms.cur_project_name + 3] = 0
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 'l "foo')
        run_at(cpu, rsyms.exec_line)
        # Project name must NOT have been changed to "FOO"
        assert get_cur_project_name(cpu, rsyms) != "FOO", \
            "cur_project_name was modified by aborted parse"
