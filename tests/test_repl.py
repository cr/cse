"""
test_repl.py — REPL command tests for repl.s

Tests the REPL command loop (exec_line), screen I/O (read_line, show_prompt),
and all command handlers via table-driven tests on the py65 emulator.

Test binary: repl.s + cse_io.s + asm_vars.s + expr.s + symtab.s
             + dasm.s + dasm_tables.s + repl_test_stub.s
"""

import subprocess, pathlib, re, pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent
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
    SRC / "oplen_tbl.s",
    DEV / "repl_test_stub.s",
    CFG,
]


# ── Build ────────────────────────────────────────────────────────────────────

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

    # Module offsets
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

    # Exports
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


# ── Fixture ──────────────────────────────────────────────────────────────────

class ReplSymbols:
    """Resolved symbol addresses + binary loader for the repl test."""

    def __init__(self):
        if _needs_rebuild():
            _build()

        seg, mods, exp = _parse_map()

        # Entry points from exports
        self.exec_line   = exp['exec_line']
        self.read_line   = exp['read_line']
        self.show_prompt = exp['show_prompt']

        # BSS symbols from exports
        self.cur_addr    = exp['cur_addr']
        self.cur_device  = exp['cur_device']
        self.cur_project_name = exp['cur_project_name']
        self.line_buf    = exp['line_buf']
        self.last_cmd    = exp['last_cmd']
        self.block_size  = exp['block_size']

        self.bp_table     = exp['bp_table']
        self.dbg_reason   = exp['dbg_reason']
        self.userland_zp_buf = exp['userland_zp_buf']
        self.dbg_bp_hit   = exp['dbg_bp_hit']
        self.brk_pc       = exp['brk_pc']
        self.reg_a        = exp['reg_a']
        self.reg_x        = exp['reg_x']
        self.reg_y        = exp['reg_y']
        self.reg_sp       = exp['reg_sp']
        self.reg_p        = exp['reg_p']
        self.state        = exp['state']
        self.dasm_buf     = exp['dasm_buf']
        self.asm_cpu       = exp['asm_cpu']

        # Stub addresses — computed from module offsets
        # kplot_stub is at a known offset within the stub's CODE section.
        # Parse it from the stub module's CODE offset.
        stub_mod = 'repl_test_stub_repl.o'
        stub_code_offs = mods[stub_mod]['CODE']
        stub_bss_offs  = mods[stub_mod]['BSS']
        # kplot_stub is the last function in the stub CODE.
        # Use _newline export to find it — kplot is after _dbg_nmi_break.
        # Simpler: just use _nmi_pending + 2 for newline_count, and
        # compute kplot_stub from the known CODE layout.
        # The kplot_stub position relative to the stub code start:
        # repl_test_exec(6) + repl_test_read(3) + repl_test_prompt(3)
        # + _hex_val(~32) + _is_hex(~12) + _hex_val_to_char(~10) + ...
        # This is fragile. Instead, read the RODATA sym_refs table!
        rodata_offs = mods[stub_mod].get('RODATA', 0)
        rodata_base = seg['RODATA'] + rodata_offs
        # sym_refs table: 17 × 2-byte addresses at rodata_base
        # [0]=exec_line, [1]=read_line, [2]=show_prompt,
        # [3]=cur_addr, [4]=cur_device, [5]=cur_project_name,
        # [6]=line_buf, [7]=last_cmd, [8]=block_size,
        # [9]=newline_count, [10]=kplot_stub,
        # [11]=_save_addr, [12]=_save_size, [13]=_load_result,
        # [14]=_save_name, [15]=_load_name, [16]=_op_witness
        bin_data = BIN.read_bytes()
        def read_word(addr):
            """Read a 16-bit word from the binary file at the given memory address."""
            if addr >= _CODE_START:
                off = _ZP_SIZE + _SCRN_SIZE + (addr - _CODE_START)
            elif addr >= _SCRN_START:
                off = _ZP_SIZE + (addr - _SCRN_START)
            else:
                off = addr
            return bin_data[off] | (bin_data[off + 1] << 8)
        self.kplot_stub    = read_word(rodata_base + 10 * 2)
        self.newline_count = read_word(rodata_base + 9 * 2)
        self.save_addr     = read_word(rodata_base + 11 * 2)
        self.save_size     = read_word(rodata_base + 12 * 2)
        self.load_result   = read_word(rodata_base + 13 * 2)
        self.save_name     = read_word(rodata_base + 14 * 2)
        self.load_name     = read_word(rodata_base + 15 * 2)
        self.op_witness    = read_word(rodata_base + 16 * 2)

        # ZP
        self.expr_ptr = exp['expr_ptr']
        self.expr_val = exp['expr_val']
        self.sym_name = exp['sym_name']
        self.sym_val  = exp['sym_val']

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
    """Session-scoped repl test binary + symbol addresses."""
    return ReplSymbols()


# ── CPU helper ───────────────────────────────────────────────────────────────

def make_cpu(rsyms):
    """Create a fresh MPU with the test binary loaded and hardware initialized."""
    cpu = MPU()
    rsyms.load_into(cpu.memory)

    # KERNAL PLOT vector → stub
    kplot = rsyms.kplot_stub
    cpu.memory[KERNAL_PLOT]     = 0x4C  # JMP
    cpu.memory[KERNAL_PLOT + 1] = kplot & 0xFF
    cpu.memory[KERNAL_PLOT + 2] = (kplot >> 8) & 0xFF

    # Init cursor position to row 5, col 0
    cpu.memory[CUR_ROW] = 5
    cpu.memory[CUR_COL] = 0

    # Init screen line pointers for current row
    row = 5
    screen_addr = SCREEN + row * COLS
    cpu.memory[0xD1] = screen_addr & 0xFF
    cpu.memory[0xD2] = (screen_addr >> 8) & 0xFF
    color_addr = 0xD800 + row * COLS
    cpu.memory[0xF3] = color_addr & 0xFF
    cpu.memory[0xF4] = (color_addr >> 8) & 0xFF

    # Clear screen
    for i in range(COLS * ROWS):
        cpu.memory[SCREEN + i] = 0x20  # space screen code

    # Init CPU mode
    cpu.memory[rsyms.asm_cpu] = 1  # 6510

    # Init BSS defaults (formerly DATA segment init values)
    set_word(cpu, rsyms.block_size, 0x0010)
    cpu.memory[rsyms.cur_device] = 8

    return cpu


MAX_CYCLES = 500_000

def run_at(cpu, addr):
    """JSR to addr, return when RTS pops back to sentinel."""
    ret = _RETURN
    # Place a NOP sentinel at the return address
    cpu.memory[ret] = 0xEA  # NOP — we detect arrival by PC == ret
    # Simulate JSR: push (ret-1) in hi/lo order, set PC
    cpu.sp = 0xFD
    cpu.memory[0x01FF] = ((ret - 1) >> 8) & 0xFF  # hi byte first (pushed first)
    cpu.memory[0x01FE] = (ret - 1) & 0xFF          # lo byte second
    cpu.pc = addr
    cycles = 0
    while cycles < MAX_CYCLES:
        if cpu.pc == ret:
            return cycles
        cpu.step()
        cycles += 1
    raise RuntimeError(f"Timeout after {MAX_CYCLES} cycles at ${cpu.pc:04X}")


# ── Screen helpers ───────────────────────────────────────────────────────────

# PETSCII → screen code mapping (for writing test input to screen)
def petscii_to_screencode(ch):
    """Convert a PETSCII byte to a C64 screen code."""
    if 0x41 <= ch <= 0x5A:      # uppercase A-Z → screen $01-$1A
        return ch - 0x40
    if 0xC1 <= ch <= 0xDA:      # shifted uppercase → screen $41-$5A
        return ch - 0x80
    if 0x20 <= ch <= 0x3F:      # space, digits, punctuation
        return ch
    return ch


def write_screen_row(cpu, row, text):
    """Write an ASCII/PETSCII string to a screen row as screen codes."""
    base = SCREEN + row * COLS
    for i in range(COLS):
        cpu.memory[base + i] = 0x20  # clear row first
    for i, ch in enumerate(text.encode('ascii') if isinstance(text, str) else text):
        if i >= COLS:
            break
        cpu.memory[base + i] = petscii_to_screencode(ch)


def read_screen_row(cpu, row):
    """Read a screen row back as a Python string (screen codes → ASCII)."""
    base = SCREEN + row * COLS
    chars = []
    for i in range(COLS):
        sc = cpu.memory[base + i] & 0x7F
        if sc == 0x20:
            chars.append(' ')
        elif 0x01 <= sc <= 0x1A:
            chars.append(chr(sc + 0x40))  # lowercase
        elif 0x30 <= sc <= 0x39:
            chars.append(chr(sc))         # digits
        elif 0x41 <= sc <= 0x5A:
            chars.append(chr(sc + 0x80 - 0x80))  # uppercase → keep as uppercase? no
            # screen $41-$5A are uppercase in C64
            chars.append('')
            chars[-2] = chr(sc - 0x40 + 0x60)  # not right either
        else:
            # Map common screen codes
            sc_map = {
                0x00: '@', 0x1B: '[', 0x1C: '\\', 0x1D: ']',
                0x2A: '*', 0x2B: '+', 0x2D: '-', 0x2E: '.',
                0x2F: '/', 0x3A: ':', 0x3B: ';', 0x3C: '<',
                0x3D: '=', 0x3E: '>', 0x3F: '?',
            }
            chars.append(sc_map.get(sc, '?'))
    return ''.join(chars).rstrip()


def read_screen_row_raw(cpu, row):
    """Read raw screen codes from a row."""
    base = SCREEN + row * COLS
    return bytes(cpu.memory[base + i] for i in range(COLS))


def screencode_str(cpu, row):
    """Read a screen row as a string, using the same mapping as read_line.
    This is what _read_line produces in line_buf: PETSCII bytes."""
    base = SCREEN + row * COLS
    result = []
    for i in range(COLS):
        sc = cpu.memory[base + i] & 0x7F
        if sc < 0x20:
            result.append(sc + 0x40)        # → lowercase PETSCII
        elif 0x41 <= sc <= 0x5A:
            result.append(sc + 0x80)        # → uppercase PETSCII
        else:
            result.append(sc)
    # trim trailing spaces
    while result and result[-1] == 0x20:
        result.pop()
    return bytes(result)


def ascii_to_petscii(ch):
    """Convert an ASCII byte to PETSCII (matching what read_line produces)."""
    if 0x61 <= ch <= 0x7A:    # ASCII lowercase a-z → PETSCII $41-$5A
        return ch - 0x20
    if 0x41 <= ch <= 0x5A:    # ASCII uppercase A-Z → PETSCII $C1-$DA
        return ch + 0x80
    return ch                  # digits, punctuation, space stay the same


def set_line_buf(cpu, rsyms, text):
    """Write a NUL-terminated PETSCII string into line_buf.
    Converts ASCII text to PETSCII encoding (matching read_line output)."""
    if isinstance(text, str):
        data = text.encode('ascii')
    else:
        data = text
    for i, b in enumerate(data):
        cpu.memory[rsyms.line_buf + i] = ascii_to_petscii(b)
    cpu.memory[rsyms.line_buf + len(data)] = 0


def set_cur_addr(cpu, rsyms, addr):
    """Set cur_addr to a 16-bit value."""
    cpu.memory[rsyms.cur_addr]     = addr & 0xFF
    cpu.memory[rsyms.cur_addr + 1] = (addr >> 8) & 0xFF


def get_cur_addr(cpu, rsyms):
    """Read cur_addr as a 16-bit value."""
    return cpu.memory[rsyms.cur_addr] | (cpu.memory[rsyms.cur_addr + 1] << 8)


def get_word(cpu, addr):
    return cpu.memory[addr] | (cpu.memory[addr + 1] << 8)


def set_word(cpu, addr, val):
    cpu.memory[addr] = val & 0xFF
    cpu.memory[addr + 1] = (val >> 8) & 0xFF


# ═══════════════════════════════════════════════════════════════
# TESTS
# ═══════════════════════════════════════════════════════════════

# ── A. show_prompt ────────────────────────────────────────────

class TestShowPrompt:
    """show_prompt writes "AAAA:" at column 0."""

    CASES = [
        (0x1000, "1000:"),
        (0x0000, "0000:"),
        (0xFFFF, "ffff:"),
        (0x0400, "0400:"),
        (0xC000, "c000:"),
    ]

    @pytest.mark.parametrize("addr,expected", CASES,
                             ids=[f"${a:04X}" for a, _ in CASES])
    def test_prompt(self, rsyms, addr, expected):
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, addr)
        cpu.memory[CUR_ROW] = 10
        cpu.memory[CUR_COL] = 0
        row_addr = SCREEN + 10 * COLS
        cpu.memory[0xD1] = row_addr & 0xFF
        cpu.memory[0xD2] = (row_addr >> 8) & 0xFF
        run_at(cpu, rsyms.show_prompt)
        # Read screen codes at row 10
        row_bytes = read_screen_row_raw(cpu, 10)
        # Check "AAAA:" — screen codes for hex digits + colon
        result = screencode_to_ascii(row_bytes[:len(expected)])
        assert result == expected

    @pytest.mark.parametrize("addr,expected", CASES,
                             ids=[f"${a:04X}" for a, _ in CASES])
    def test_prompt_sets_cx(self, rsyms, addr, expected):
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, addr)
        run_at(cpu, rsyms.show_prompt)
        assert cpu.memory[CUR_COL] == len(expected)


def screencode_to_ascii(raw):
    """Convert screen code bytes to ASCII string."""
    result = []
    for sc in raw:
        sc &= 0x7F
        if sc == 0x3A:
            result.append(':')
        elif sc == 0x20:
            result.append(' ')
        elif 0x30 <= sc <= 0x39:
            result.append(chr(sc))
        elif 0x01 <= sc <= 0x1A:
            result.append(chr(sc + 0x60))  # screen $01-$1A → 'a'-'z'
        elif 0x21 <= sc <= 0x3F:
            result.append(chr(sc))         # punctuation
        else:
            result.append(f'[{sc:02x}]')
    return ''.join(result)


# ── B. read_line (screen → line_buf) ─────────────────────────

class TestReadLine:
    """read_line converts screen codes to PETSCII in line_buf."""

    CASES = [
        # (screen_text, expected_line_buf_bytes)
        # Lowercase letters (screen $01-$1A → PETSCII $41-$5A)
        ("abcd", b"abcd"),
        # Digits stay as-is
        ("1234", b"1234"),
        # Colon
        ("1000:", b"1000:"),
        # Mixed
        ("1000:m", b"1000:m"),
        # Trailing spaces trimmed
        ("abc   ", b"abc"),
        # Hex address command
        ("1000:d", b"1000:d"),
    ]

    @pytest.mark.parametrize("screen_text,expected", CASES,
                             ids=[t[0] or "empty" for t in CASES])
    def test_read(self, rsyms, screen_text, expected):
        cpu = make_cpu(rsyms)
        row = cpu.memory[CUR_ROW]
        write_screen_row(cpu, row, screen_text)
        run_at(cpu, rsyms.read_line)
        # Read line_buf until NUL
        buf = []
        for i in range(42):
            b = cpu.memory[rsyms.line_buf + i]
            if b == 0:
                break
            buf.append(b)
        result = bytes(buf)
        assert result == expected


# ── C. Address commands (@, +, -) ─────────────────────────────

class TestAddressCommands:
    """@ sets cur_addr; + increments; - decrements."""

    CASES = [
        # (initial_addr, command_string, expected_addr)
        # @ with hex literal
        (0x1000, "@$2000",      0x2000),
        (0x1000, "@$c000",      0xC000),
        (0x1000, "@$ff",        0x00FF),
        # @ with expression
        (0x1000, "@$1000+$100", 0x1100),
        # + with value
        (0x1000, "+$10",        0x1010),
        # + bare (uses block_size = $10)
        (0x1000, "+",           0x1010),
        # - with value
        (0x1000, "-$10",        0x0FF0),
        # - bare
        (0x1000, "-",           0x0FF0),
        # + with expression
        (0x2000, "+$80",        0x2080),
    ]

    @pytest.mark.parametrize("init,cmd,expected", CASES,
                             ids=[c[1] for c in CASES])
    def test_addr_cmd(self, rsyms, init, cmd, expected):
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, init)
        # block_size defaults to $0010
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        assert get_cur_addr(cpu, rsyms) == expected, \
            f"Expected ${expected:04X}, got ${get_cur_addr(cpu, rsyms):04X}"


# ── D. Address prefix parsing ────────────────────────────────

class TestAddressPrefix:
    """exec_line parses AAAA: prefix and updates cur_addr."""

    CASES = [
        # (command, expected_cur_addr, desc)
        ("2000:;",      0x2000, "bare prefix + semicolon"),
        ("c000:;",      0xC000, "high address prefix"),
        ("0400:;",      0x0400, "screen address"),
    ]

    @pytest.mark.parametrize("cmd,expected,desc", CASES,
                             ids=[c[2] for c in CASES])
    def test_prefix(self, rsyms, cmd, expected, desc):
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        assert get_cur_addr(cpu, rsyms) == expected


# ── E. Memory display (m command) ────────────────────────────

class TestMemoryDisplay:
    """'m' command displays memory at cur_addr."""

    def test_m_shows_hex_bytes(self, rsyms):
        """m command outputs hex dump on screen."""
        cpu = make_cpu(rsyms)
        addr = 0x1000          # within workspace, below code at $4000
        set_cur_addr(cpu, rsyms, addr)
        # Write known pattern to target memory
        for i in range(8):
            cpu.memory[addr + i] = 0x41 + i  # A, B, C, ...

        set_line_buf(cpu, rsyms, "m")
        row_before = cpu.memory[CUR_ROW]
        run_at(cpu, rsyms.exec_line)

        # After m, cur_addr should have advanced
        new_addr = get_cur_addr(cpu, rsyms)
        assert new_addr > addr

    def test_m_with_address(self, rsyms):
        """m with AAAA: prefix uses that address."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, "2000:m")
        run_at(cpu, rsyms.exec_line)
        # cur_addr should be near $2000 + block_size
        new_addr = get_cur_addr(cpu, rsyms)
        assert new_addr >= 0x2000


# ── F. Memory edit (m with hex bytes) ────────────────────────

class TestMemoryEdit:
    """'m' with hex args writes bytes to memory."""

    CASES = [
        # (addr, args, expected_bytes) — addr must be outside code region
        (0x1000, "m 41 42 43", [0x41, 0x42, 0x43]),
        (0x1000, "m ff",       [0xFF]),
        (0x1000, "m 00 01 02 03 04 05 06 07", [0, 1, 2, 3, 4, 5, 6, 7]),
    ]

    @pytest.mark.parametrize("addr,cmd,expected", CASES,
                             ids=[c[1].strip() for c in CASES])
    def test_mem_edit(self, rsyms, addr, cmd, expected):
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, addr)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        for i, val in enumerate(expected):
            assert cpu.memory[addr + i] == val, \
                f"Byte {i}: expected ${val:02X}, got ${cpu.memory[addr + i]:02X}"


# ── F'. User-ZP redirect (m/. on $00..$7F) ───
#
# `m` and `.` always read from and write to userland_zp_buf for
# addresses $00..$7F — CSE's own live ZP is never shown to the
# REPL user.  See doc/modules/repl.md § User-ZP view.

class TestUserZpRedirect:
    ZP_ADDR = 0x0010

    def test_m_edit_writes_to_userland_buf(self, rsyms):
        """`m 42` at $0010 updates userland_zp_buf, not live."""
        cpu = make_cpu(rsyms)
        cpu.memory[rsyms.userland_zp_buf + self.ZP_ADDR] = 0x00
        cpu.memory[self.ZP_ADDR] = 0xFF
        set_cur_addr(cpu, rsyms, self.ZP_ADDR)
        set_line_buf(cpu, rsyms, "m 42")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.userland_zp_buf + self.ZP_ADDR] == 0x42
        assert cpu.memory[self.ZP_ADDR] == 0xFF   # live untouched

    def test_dot_hex_poke_writes_to_userland_buf(self, rsyms):
        """`. a9` at $0010 updates userland_zp_buf, not live."""
        cpu = make_cpu(rsyms)
        cpu.memory[rsyms.userland_zp_buf + self.ZP_ADDR] = 0x00
        cpu.memory[self.ZP_ADDR] = 0xFF
        set_cur_addr(cpu, rsyms, self.ZP_ADDR)
        set_line_buf(cpu, rsyms, ". a9")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.userland_zp_buf + self.ZP_ADDR] == 0xA9
        assert cpu.memory[self.ZP_ADDR] == 0xFF   # live untouched

    def test_m_edit_above_7f_hits_live(self, rsyms):
        """Redirect gates on addr < $80.  `m 42` at $0080 writes live."""
        cpu = make_cpu(rsyms)
        cpu.memory[rsyms.userland_zp_buf + 0x80] = 0x55  # outside valid range
        cpu.memory[0x0080] = 0x00
        set_cur_addr(cpu, rsyms, 0x0080)
        set_line_buf(cpu, rsyms, "m 42")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[0x0080] == 0x42

    def test_m_dump_shows_userland_buf(self, rsyms):
        """`m` display shows userland_zp_buf, not live."""
        cpu = make_cpu(rsyms)
        # Prime userland_zp_buf with a distinctive pattern, live with zeros.
        for i in range(16):
            cpu.memory[rsyms.userland_zp_buf + i] = 0xA0 | i
            cpu.memory[i] = 0x00
        set_cur_addr(cpu, rsyms, 0x0000)
        set_line_buf(cpu, rsyms, "m")
        run_at(cpu, rsyms.exec_line)
        row = read_screen_row(cpu, 5).strip()
        assert "A0" in row.upper(), \
            f"Expected A0 (from userland_zp_buf) in dump, got: {row!r}"

    def test_m_dump_above_7f_shows_live(self, rsyms):
        """Redirect stops at $80.  `m $0080` shows live memory."""
        cpu = make_cpu(rsyms)
        for i in range(16):
            cpu.memory[rsyms.userland_zp_buf + 0x80 + i] = 0xA0 | i
            cpu.memory[0x0080 + i] = 0x50 | i
        set_cur_addr(cpu, rsyms, 0x0080)
        set_line_buf(cpu, rsyms, "m")
        run_at(cpu, rsyms.exec_line)
        row = read_screen_row(cpu, 5).strip()
        assert "50" in row.upper(), \
            f"Expected 50 (live) in dump, got: {row!r}"


# ── G. Disassemble (d command) ───────────────────────────────

class TestDisassemble:
    """'d' command disassembles instructions and advances cur_addr."""

    def test_d_advances(self, rsyms):
        """d with known opcodes advances cur_addr."""
        cpu = make_cpu(rsyms)
        addr = 0x3000
        set_cur_addr(cpu, rsyms, addr)
        # Write some known opcodes: NOP NOP NOP (each 1 byte)
        cpu.memory[addr]     = 0xEA  # NOP
        cpu.memory[addr + 1] = 0xEA
        cpu.memory[addr + 2] = 0xEA
        set_line_buf(cpu, rsyms, "d")
        run_at(cpu, rsyms.exec_line)
        new_addr = get_cur_addr(cpu, rsyms)
        assert new_addr > addr


# ── H. Calculator (? command) ────────────────────────────────

class TestCalculator:
    """'?' command evaluates expressions and displays results."""

    CASES = [
        # (expr_str, expected_addr_unchanged)
        # The ? command doesn't change cur_addr, just prints
        ("?$10+$20",  True),
        ("?$ff",      True),
        ("?$1000",    True),
    ]

    @pytest.mark.parametrize("cmd,unchanged", CASES,
                             ids=[c[0] for c in CASES])
    def test_calc_preserves_addr(self, rsyms, cmd, unchanged):
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        if unchanged:
            assert get_cur_addr(cpu, rsyms) == 0x1000


# ── I. Register display (r command) ──────────────────────────

class TestRegisterDisplay:
    """'r' command displays register dump."""

    def test_r_bare(self, rsyms):
        """Bare 'r' displays current registers."""
        cpu = make_cpu(rsyms)
        # Set known register values
        cpu.memory[rsyms.reg_a]  = 0x42
        cpu.memory[rsyms.reg_x]  = 0x10
        cpu.memory[rsyms.reg_y]  = 0x20
        cpu.memory[rsyms.reg_sp] = 0xFF
        cpu.memory[rsyms.reg_p]  = 0b10110000  # NV set
        set_line_buf(cpu, rsyms, "r")
        run_at(cpu, rsyms.exec_line)
        # Just verify it didn't crash; real output goes to screen


# ── J. Register set (r with args) ────────────────────────────

class TestRegisterSet:
    """'r' with register values sets them."""

    CASES = [
        # (args, expected_a, expected_x, expected_y, expected_sp)
        ("r a:ff x:10 y:20 s:fd nv..i...", 0xFF, 0x10, 0x20, 0xFD),
        ("r a:00 x:00 y:00 s:ff ........", 0x00, 0x00, 0x00, 0xFF),
    ]

    @pytest.mark.parametrize("cmd,ea,ex,ey,es", CASES,
                             ids=[f"a={c[1]:02x}" for c in CASES])
    def test_reg_set(self, rsyms, cmd, ea, ex, ey, es):
        cpu = make_cpu(rsyms)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.reg_a]  == ea
        assert cpu.memory[rsyms.reg_x]  == ex
        assert cpu.memory[rsyms.reg_y]  == ey
        assert cpu.memory[rsyms.reg_sp] == es

    def test_reg_set_pc(self, rsyms):
        """`r pc:XXXX a:.. x:.. y:.. s:.. flags` also edits brk_pc."""
        cpu = make_cpu(rsyms)
        set_word(cpu, rsyms.brk_pc, 0x0000)
        set_line_buf(cpu, rsyms, "r pc:c010 a:42 x:00 y:00 s:ff ........")
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.brk_pc) == 0xC010
        assert cpu.memory[rsyms.reg_a] == 0x42


# ── K. Block size (B command) ────────────────────────────────

class TestBlockSize:
    """'B' command sets/displays block_size."""

    CASES = [
        ("B1",     0x01),
        ("B$20",   0x20),
        ("B$100",  0x100),
        ("B$ff",   0xFF),
        ("B$10+$10", 0x20),   # expression support
    ]

    @pytest.mark.parametrize("cmd,expected", CASES,
                             ids=[c[0] for c in CASES])
    def test_set_block(self, rsyms, cmd, expected):
        cpu = make_cpu(rsyms)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        got = get_word(cpu, rsyms.block_size)
        assert got == expected, f"Expected ${expected:04X}, got ${got:04X}"


# ── L. Repeat empty line ─────────────────────────────────────

class TestRepeat:
    """Empty line repeats last paging command."""

    def test_m_then_empty_repeats(self, rsyms):
        """After 'm', empty line repeats memory dump."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x3000)
        # First: issue 'm'
        set_line_buf(cpu, rsyms, "m")
        run_at(cpu, rsyms.exec_line)
        addr1 = get_cur_addr(cpu, rsyms)
        assert addr1 > 0x3000
        # Second: empty line (repeat)
        set_line_buf(cpu, rsyms, "")
        run_at(cpu, rsyms.exec_line)
        addr2 = get_cur_addr(cpu, rsyms)
        assert addr2 > addr1


# ── M. Semicolon stops parsing ───────────────────────────────

class TestSemicolon:
    """';' at start of line is a no-op (comment)."""

    def test_semicolon_noop(self, rsyms):
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, ";this is a comment")
        run_at(cpu, rsyms.exec_line)
        assert get_cur_addr(cpu, rsyms) == 0x1000


# ── N. Unknown command ───────────────────────────────────────

class TestUnknownCommand:
    """Unknown command letter prints error, doesn't crash."""

    def test_unknown(self, rsyms):
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, "z")
        run_at(cpu, rsyms.exec_line)
        # Should not crash; cur_addr unchanged
        assert get_cur_addr(cpu, rsyms) == 0x1000


# ── O. Settings: color (C), cpu (u) ──────────

# Note: tab width is now a build-time constant (TAB_WIDTH, default 8);
# the `T` command no longer exists.  See doc/modules/repl.md and
# doc/modules/editor.md.


class TestCpuSelect:
    """'u' command sets asm_cpu."""

    CASES = [
        ("u6502",  0),
        ("u65c02", 2),
    ]

    @pytest.mark.parametrize("cmd,expected", CASES,
                             ids=[c[0] for c in CASES])
    def test_cpu(self, rsyms, cmd, expected):
        cpu = make_cpu(rsyms)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.asm_cpu] == expected


# ── P. Dot command (. with hex edit) ─────────────────────────

class TestDotHexEdit:
    """'.' with hex bytes pokes them at cur_addr."""

    def test_dot_hex_poke(self, rsyms):
        """'. ea' at $3000 writes NOP."""
        cpu = make_cpu(rsyms)
        addr = 0x3000
        set_cur_addr(cpu, rsyms, addr)
        cpu.memory[addr] = 0x00  # start with 0
        set_line_buf(cpu, rsyms, ". ea")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[addr] == 0xEA

    def test_dot_multi_hex(self, rsyms):
        """'. a9 42' writes LDA #$42."""
        cpu = make_cpu(rsyms)
        addr = 0x3000
        set_cur_addr(cpu, rsyms, addr)
        set_line_buf(cpu, rsyms, ". a9 42")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[addr] == 0xA9
        assert cpu.memory[addr + 1] == 0x42


# ── R. Load/Save command tests ─────────────────────────────────────

def get_cur_project_name(cpu, rsyms):
    """Read cur_project_name as a Python string."""
    chars = []
    for i in range(17):
        b = cpu.memory[rsyms.cur_project_name + i]
        if b == 0:
            break
        chars.append(chr(b) if 0x20 <= b < 0x80 else '?')
    return ''.join(chars)


# Operation witness codes (mirrors dev/repl_test_stub.s _op_witness)
OP_NONE     = 0
OP_PRG_SAVE = 1
OP_SEQ_SAVE = 2
OP_PRG_LOAD = 3
OP_SEQ_LOAD = 4


def get_name(cpu, base, maxlen=17):
    """Read a NUL-terminated PETSCII name at `base` as a Python string."""
    chars = []
    for i in range(maxlen):
        b = cpu.memory[base + i]
        if b == 0:
            break
        chars.append(chr(b) if 0x20 <= b < 0x80 else '?')
    return ''.join(chars)


def clear_witness(cpu, rsyms):
    """Reset disk/editor witnesses to detect stub invocation."""
    cpu.memory[rsyms.op_witness] = OP_NONE
    set_word(cpu, rsyms.save_addr, 0xFFFF)
    set_word(cpu, rsyms.save_size, 0xFFFF)
    # wipe name buffers
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
        # Inclusive end: bytes $0800..$0900 → size = $0101.
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
        set_line_buf(cpu, rsyms, 's "foo,p"')      # verbatim PRG, 0 args
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.save_addr) == 0x0800
        assert get_word(cpu, rsyms.save_size) == 0x0010   # block_size

    def test_save_end_from_arg(self, rsyms):
        """1 arg → start = cur_addr, end = arg (INCLUSIVE)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo" $0900')
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.save_addr) == 0x0800
        # Inclusive end: save bytes $0800..$0900 → size = $0101.
        assert get_word(cpu, rsyms.save_size) == 0x0101

    def test_save_two_args(self, rsyms):
        """2 args → start = arg1, end = arg2 (INCLUSIVE)."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo" $1000 $2000')
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.save_addr) == 0x1000
        # Inclusive end: save bytes $1000..$2000 → size = $1001.
        assert get_word(cpu, rsyms.save_size) == 0x1001

    def test_save_end_length_fallback(self, rsyms):
        """2 args, end <= start → end = length."""
        cpu = make_cpu(rsyms)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, 's "foo" $1000 $100')
        run_at(cpu, rsyms.exec_line)
        assert get_word(cpu, rsyms.save_addr) == 0x1000
        assert get_word(cpu, rsyms.save_size) == 0x0100   # arg2 as length

    # ── Project-name reuse ────────────────────────────────────────────

    def test_save_no_name_defaults_to_out(self, rsyms):
        """Empty cur_project_name + bare `s` → defaults to "out"."""
        cpu = make_cpu(rsyms)
        cpu.memory[rsyms.cur_project_name] = 0
        set_cur_addr(cpu, rsyms, 0x0800)
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, "s")
        run_at(cpu, rsyms.exec_line)
        # "out" derives SEQ (no address args)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_SAVE
        assert get_name(cpu, rsyms.save_name) == "OUT"

    def test_save_reuse_prev_name(self, rsyms):
        """s "foo" then bare s → reuses "foo"."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        set_line_buf(cpu, rsyms, 's "foo"')
        run_at(cpu, rsyms.exec_line)
        assert get_cur_project_name(cpu, rsyms) == "FOO"
        # Second invocation: no name → reuse
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, "s")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_SEQ_SAVE
        assert get_name(cpu, rsyms.save_name) == "FOO"

    def test_save_unquoted_is_expr(self, rsyms):
        """s $0900 — unquoted arg is inclusive end (args force PRG)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x0800)
        # pre-seed project name
        for i, ch in enumerate(b"prev"):
            cpu.memory[rsyms.cur_project_name + i] = ascii_to_petscii(ch)
        cpu.memory[rsyms.cur_project_name + 4] = 0
        clear_witness(cpu, rsyms)
        set_line_buf(cpu, rsyms, "s $0900")
        run_at(cpu, rsyms.exec_line)
        assert cpu.memory[rsyms.op_witness] == OP_PRG_SAVE
        assert get_name(cpu, rsyms.save_name) == "PREV."
        assert get_word(cpu, rsyms.save_addr) == 0x0800
        # Inclusive: bytes $0800..$0900 = $0101.
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
        # Inclusive end: $2004 - $0801 + 1.
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
        set_word(cpu, rsyms.load_result, 0x0900)  # simulated end addr
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


# ── Q. Step into JSR — ROM target falls back to step-over ───────
#
# Moved to tests/test_step_rom.py (C64Emu-based, no layout fragility).
# The old tests were xfail'd because step_witness was computed from
# a hardcoded BSS offset that broke on any code size change.
