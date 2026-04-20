"""
test_repl.py — REPL command tests for repl.s.

Tests the REPL command loop (exec_line), screen I/O (read_line,
show_prompt), and all command handlers via table-driven tests on
C64Emu + the production CMOS PRG.

Tranche 4 migration: previously this test file used a custom
bare-MPU harness with dev/repl_test_stub.s.  It now uses the real
production binary through C64Emu so the tests exercise the same
code that runs on the C64.

Disk tests (TestSaveCommand, TestLoadCommand) still live in
test_repl_disk.py using the old stub-based harness; they migrate
back here once virtual IEC lands in C64Emu.
"""

import pytest
from c64emu import C64Emu


SCREEN = 0x0400
COLS   = 40
ROWS   = 25
CUR_COL = 0xD3
CUR_ROW = 0xD6


# ── Symbol bag + fresh-emulator fixture ──────────────────────────────────────

class ReplSymbols:
    """Production-PRG symbol addresses + a factory for fresh emulators.

    Backed by C64Emu + the production cse-cmos.prg.  Attribute names
    mirror the old bare-MPU harness so test bodies need no changes
    (rsyms.exec_line, rsyms.cur_addr, rsyms.line_buf, …).
    """

    _ATTRS = [
        # entry points
        "exec_line", "read_line", "show_prompt", "post_run_cleanup",
        # BSS
        "cur_addr", "cur_device", "cur_project_name", "line_buf",
        "last_cmd", "block_size", "bp_table", "dbg_reason",
        "userland_zp_buf", "dbg_bp_hit", "brk_pc",
        "reg_a", "reg_x", "reg_y", "reg_sp", "reg_p", "state",
        "dasm_buf", "asm_cpu",
        # ZP
        "expr_ptr", "expr_val", "sym_name", "sym_val",
    ]

    def __init__(self, cse_prg):
        self._prg, self._map = cse_prg
        # Resolve all symbols from one scratch emulator.
        probe = C64Emu()
        probe.load_prg(self._prg, self._map)
        for name in self._ATTRS:
            setattr(self, name, probe.sym(name))

    def new_emu(self):
        """Return a freshly-loaded emulator, CSE-initialised and with
        REPL-state defaults set (block_size=$0010, cur_device=8,
        cursor at row 5 col 0)."""
        emu = C64Emu()
        emu.load_prg(self._prg, self._map)
        emu.init_cse()
        emu.set_cursor(5, 0)
        # REPL state defaults that the full cold-init path would set.
        emu.write_word(self.block_size, 0x0010)
        emu.memory[self.cur_device] = 8
        emu.memory[self.asm_cpu] = 1   # 6510
        return emu


@pytest.fixture(scope="session")
def rsyms(cse_prg):
    """Session-scoped symbol table + PRG holder."""
    return ReplSymbols(cse_prg)


# ── CPU helper ───────────────────────────────────────────────────────────────

def make_cpu(rsyms):
    """Return a fresh C64Emu ready to exercise REPL commands."""
    return rsyms.new_emu()


def run_at(cpu, addr):
    """JSR to addr, return when RTS pops back to the sentinel."""
    return cpu.jsr(addr)


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

    # ── Trailing-garbage rejection for `@` (Escape Analysis class-wide) ──
    #
    # Same bug class as `?` (fixed in 591e4a1): `@` takes exactly one
    # complete expression and nothing else, but pre-fix silently
    # accepted trailing content because try_expr didn't enforce EOI.

    SEEK_GARBAGE = [
        "@1x",
        "@$2000xx",
        "@$20+$10 foo",
        "@$100,X",    # address-mode syntax in a seek makes no sense
    ]

    @pytest.mark.parametrize("cmd", SEEK_GARBAGE, ids=SEEK_GARBAGE)
    def test_seek_rejects_trailing_garbage(self, rsyms, cmd):
        """`@` must reject trailing non-whitespace/non-comment content.

        Pre-fix: silently took the value prefix and set cur_addr — the
        canonical `@1x` → cur_addr=$0001 footgun.
        """
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        # Expect ';?' error row somewhere.
        found_error = False
        for row in range(ROWS):
            base = SCREEN + row * COLS
            if cpu.memory[base] == 0x3B and cpu.memory[base + 1] == 0x3F:
                found_error = True
                break
        assert found_error, \
            f"{cmd!r} silently accepted (no ';?' error row)"
        # cur_addr must be unchanged when the command errored.
        assert get_cur_addr(cpu, rsyms) == 0x1000, \
            f"{cmd!r} modified cur_addr despite trailing garbage"

    def test_seek_accepts_trailing_whitespace_and_comment(self, rsyms):
        """Trailing whitespace / comment is valid (matches `?` contract)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, "@$2000 ; seek")
        run_at(cpu, rsyms.exec_line)
        assert get_cur_addr(cpu, rsyms) == 0x2000
        # No ';?' error should have been emitted.
        for row in range(ROWS):
            base = SCREEN + row * COLS
            assert not (cpu.memory[base] == 0x3B and
                        cpu.memory[base + 1] == 0x3F), \
                f"unexpected ';?' row {row}"


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
        # Prime userland_zp_buf with a distinctive pattern.  Don't
        # touch live ZP — $00/$01 are the CPU-port/DDR registers and
        # zeroing them would unbank KERNAL and break CHROUT during
        # the m-command output.  The redirect is unconditional
        # (`zp_stage_prep` always substitutes userland_zp_buf for
        # page-0 reads), so we only need the snapshot primed.
        for i in range(16):
            cpu.memory[rsyms.userland_zp_buf + i] = 0xA0 | i
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


# ── F''. Stack headroom warning (B3) ─────────────────────────
#
# post_run_cleanup emits ";!stk N" when reg_sp at break is below the
# 64-byte kernel re-entry budget.  See userland_contract.md §
# Kernel stack budget.

class TestStackHeadroomWarning:
    """B3: the stack-headroom warning fires iff reg_sp < 64."""

    def _run_post(self, rsyms, reg_sp_value):
        cpu = make_cpu(rsyms)
        cpu.memory[rsyms.reg_sp] = reg_sp_value
        # Minimal state so post_run_cleanup's other branches are harmless:
        # clear step_state / dbg_reason so we exit via @not_step → show_break_result.
        # (show_break_result will print a line too, but it lands on a
        # different row — we only scan the row where the warning goes.)
        run_at(cpu, rsyms.post_run_cleanup)
        return [read_screen_row(cpu, r) for r in range(5, 8)]

    def test_warn_when_sp_below_budget(self, rsyms):
        """reg_sp = $20 → 32 bytes headroom → warning fires."""
        rows = self._run_post(rsyms, 0x20)
        text = " ".join(rows).lower()
        assert "stk" in text, f"expected 'stk' warning, got: {rows!r}"
        # Decimal form: "32"
        assert "32" in text, f"expected '32' in warning, got: {rows!r}"

    def test_no_warn_at_budget(self, rsyms):
        """reg_sp = 64 ($40) is exactly at the budget — no warning."""
        rows = self._run_post(rsyms, 0x40)
        text = " ".join(rows).lower()
        assert "stk" not in text, f"unexpected 'stk' warning: {rows!r}"

    def test_no_warn_when_sp_healthy(self, rsyms):
        """reg_sp = $F0 → 240 bytes headroom → no warning."""
        rows = self._run_post(rsyms, 0xF0)
        text = " ".join(rows).lower()
        assert "stk" not in text, f"unexpected 'stk' warning: {rows!r}"


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

    # ── Trailing-garbage rejection (Escape Analysis 2026-04-20) ──
    #
    # Bug (pre-fix): "? 1x" was accepted as value $01 because expr_eval
    # stops at the first non-digit and returns success, leaving the 'x'
    # in expr_ptr.  The ? command never checked that the expression
    # fully consumed the line, so the trailing 'x' was silently ignored.
    #
    # Fix: ? now verifies expr_ptr reaches end-of-input (NUL, ';', or
    # whitespace-then-NUL/';') after expr_eval success; otherwise
    # reports an error line.
    #
    # Each case feeds input that parses to a value but has trailing
    # non-whitespace, non-comment content.  After exec_line, we scan
    # the screen for the error-line marker (";?") vs. the info-line
    # marker (";  ").  A value output would contain "01" or "$" near
    # the start of its row; an error line starts with ";?".

    GARBAGE_CASES = [
        "?1x",          # the original escape: "? 1x" (bare decimal + letter)
        "?$10x",        # hex + letter
        "?%10abc",      # binary + letters
        "?1+2foo",      # sub-expression parses, trailing word
        "?$10 xx",      # whitespace then garbage
        "?1,2",         # second value (no comma operator)
    ]

    @pytest.mark.parametrize("cmd", GARBAGE_CASES, ids=GARBAGE_CASES)
    def test_calc_rejects_trailing_garbage(self, rsyms, cmd):
        """? must reject trailing non-whitespace/non-comment content.

        Covered contract clauses:
          - repl.md § Commands — Info / Utility ('?' row)
          - expr.md § Caveats (parser stops at first unparsed char;
            caller responsible for end-of-input check).
        """
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)

        # Scan screen for an error-line marker: ";?" at column 0 of
        # any row.  Screen codes: ';' = $3B, '?' = $3F.
        found_error = False
        found_value = False
        for row in range(ROWS):
            base = SCREEN + row * COLS
            if cpu.memory[base] == 0x3B and cpu.memory[base + 1] == 0x3F:
                found_error = True
            elif cpu.memory[base] == 0x3B and cpu.memory[base + 1] == 0x20:
                # ";  " info line — would indicate the buggy silent accept
                # IF it also contains hex/decimal value content.  Scan
                # for '$' ($24) or a digit ($30-$39) later in the row.
                for c in range(2, COLS):
                    b = cpu.memory[base + c]
                    if b == 0x24 or (0x30 <= b <= 0x39):
                        found_value = True
                        break
        assert found_error, \
            f"{cmd!r} accepted silently (no ';?' error row); " \
            f"found info line with value={found_value}"
        assert not found_value, \
            f"{cmd!r} displayed a value despite trailing garbage"

    def test_calc_preserves_prompt_row(self, rsyms):
        """Regression: `?` must emit its output on a FRESH row below
        the prompt, not overwrite the prompt row itself.

        The earlier "enter anywhere" Escape Analysis (commit 2fec584)
        relied on log_open's auto-advance when CUR_COL != 0.  But
        main.s's RETURN handler was homing CUR_COL=0 before exec_line,
        so log_open saw "already at col 0 — don't advance" and
        overwrote the prompt line.  Fix: main.s no longer homes
        CUR_COL; cursor remains wherever the user was when RETURN
        fired (typically mid-line), letting log_open's auto-advance
        actually fire.  Display emitters (`.`, `m`, `d`) still
        overwrite via io_addr_cmd's own explicit CUR_COL=0.
        """
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        # Simulate the "typed command, cursor at end of input"
        # state that RETURN produces in practice.
        cpu.memory[CUR_ROW] = 5
        cpu.memory[CUR_COL] = 11     # end of "1000:? $42"
        # Pre-populate row 5 with a distinct pattern so we can tell
        # whether it was overwritten.  Screen code $7F is a marker.
        base = SCREEN + 5 * COLS
        for i in range(COLS):
            cpu.memory[base + i] = 0x7F
        set_line_buf(cpu, rsyms, "? $42")
        run_at(cpu, rsyms.exec_line)
        # Row 5 (the prompt row) must still contain its marker
        # pattern at col 0 — not a ';' (log-line start) or value.
        assert cpu.memory[base] == 0x7F, \
            f"prompt row overwritten: row 5 col 0 = ${cpu.memory[base]:02X}, " \
            f"expected $7F (marker untouched)"
        # Row 6 (the fresh row) should contain the ';  $42...' output.
        next_base = SCREEN + 6 * COLS
        assert cpu.memory[next_base] == 0x3B, \
            f"expected ';' (log-info) on row 6 col 0, got " \
            f"${cpu.memory[next_base]:02X}"

    def test_calc_accepts_trailing_whitespace(self, rsyms):
        """Whitespace after the expression is fine (no trailing-garbage error)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, "?$10   ")
        run_at(cpu, rsyms.exec_line)
        # Expect NO ";?" error row; expect at least one ";  " info row.
        for row in range(ROWS):
            base = SCREEN + row * COLS
            assert not (cpu.memory[base] == 0x3B and
                        cpu.memory[base + 1] == 0x3F), \
                f"row {row} unexpectedly contains ';?' error prefix"

    def test_calc_accepts_trailing_comment(self, rsyms):
        """';' comment after expression is fine (not garbage)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x1000)
        set_line_buf(cpu, rsyms, "?$10 ; comment")
        run_at(cpu, rsyms.exec_line)
        # The first ';' in the output is the log-line prefix; scan for
        # a ';?' error prefix specifically.
        for row in range(ROWS):
            base = SCREEN + row * COLS
            assert not (cpu.memory[base] == 0x3B and
                        cpu.memory[base + 1] == 0x3F), \
                f"row {row} unexpectedly contains ';?' error prefix"


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

    # ── Trailing-garbage rejection for `B` (Escape Analysis class-wide) ──

    BLOCK_GARBAGE = ["B1x", "B$20xx", "B$10+$10 junk"]

    @pytest.mark.parametrize("cmd", BLOCK_GARBAGE, ids=BLOCK_GARBAGE)
    def test_block_rejects_trailing_garbage(self, rsyms, cmd):
        """`B` must reject trailing non-whitespace/non-comment content."""
        cpu = make_cpu(rsyms)
        # Prime block_size to a distinct value so we detect if the
        # error path silently set it from the value-prefix parse.
        set_word(cpu, rsyms.block_size, 0x0010)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        found_error = False
        for row in range(ROWS):
            base = SCREEN + row * COLS
            if cpu.memory[base] == 0x3B and cpu.memory[base + 1] == 0x3F:
                found_error = True
                break
        assert found_error, \
            f"{cmd!r} silently accepted (no ';?' error row)"
        assert get_word(cpu, rsyms.block_size) == 0x0010, \
            f"{cmd!r} modified block_size despite trailing garbage"


# ── K2. Color command trailing-garbage (Escape Analysis class-wide) ──

class TestColorCommand:
    """'C' command sets theme colors or displays when called bare.
    Added as part of the trailing-garbage Escape Analysis sweep."""

    COLOR_GARBAGE = [
        "C0x",       # one hex digit + non-hex trailing
        "C0e6z",     # three hex digits + non-hex trailing
        "C 0 x",     # hex digit + whitespace + non-hex
    ]

    @pytest.mark.parametrize("cmd", COLOR_GARBAGE, ids=COLOR_GARBAGE)
    def test_color_rejects_trailing_garbage(self, rsyms, cmd):
        """`C` must reject non-hex content following its 1–3 hex digits."""
        cpu = make_cpu(rsyms)
        # Snapshot theme_fg as the canary — if `C 0x` silently applies
        # fg=$0, theme_fg flips to 0.
        fg_before = cpu.memory[rsyms.reg_a]  # not ideal, see below
        # (reg_a isn't theme_fg — we'll check via the error-row marker
        # instead, which is the more robust signal anyway.)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        found_error = False
        for row in range(ROWS):
            base = SCREEN + row * COLS
            if cpu.memory[base] == 0x3B and cpu.memory[base + 1] == 0x3F:
                found_error = True
                break
        assert found_error, \
            f"{cmd!r} silently accepted (no ';?' error row)"


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

    # ── Dot-command input-shape matrix (Escape Analysis 2026-04-20) ──
    #
    # `.` command inputs split into three valid shapes plus a
    # garbage-reject cell:
    #   empty / comment     → silent redisplay (no assemble, no error)
    #   hex-pair(s)         → hex poke (test_dot_hex_poke / test_dot_multi_hex)
    #   letter-start        → mnemonic assemble (test_dot_multi_hex and friends)
    #   OTHER (non-letter)  → SYNTAX ERROR (was: silent fallthrough)
    #
    # Pre-fix bug: inputs like `. .`, `. ,`, `. $`, `. 123` were not
    # hex (two hex digits) and not letter-start, so the @try_mne gate
    # in cmd_dot fell through to @show (display-only refresh) without
    # reporting an error.  User got no feedback.  Contract was silent
    # on this cell of the input-shape matrix → Principle 11.

    GARBAGE_CASES = [
        ". .",     # dot after space
        ". ,",     # comma
        ". $",     # bare '$'
        ". 123",   # digits-only (not a valid mnemonic or hex pair)
        ". ?",     # question mark
        ". /",     # slash
    ]

    @pytest.mark.parametrize("cmd", GARBAGE_CASES, ids=GARBAGE_CASES)
    def test_dot_rejects_non_letter_garbage(self, rsyms, cmd):
        """`.` must reject non-letter, non-hex input after the command
        character as a syntax error — not silently redisplay.  Covered
        contract: doc/modules/repl.md § `.` command input-shape matrix."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x3000)
        set_line_buf(cpu, rsyms, cmd)
        run_at(cpu, rsyms.exec_line)
        # Scan screen for ';?' (log_err prefix: ';' + '?' as screen
        # codes $3B, $3F).
        found_error = False
        for row in range(ROWS):
            base = SCREEN + row * COLS
            if cpu.memory[base] == 0x3B and cpu.memory[base + 1] == 0x3F:
                found_error = True
                break
        assert found_error, \
            f"{cmd!r} silently accepted (no ';?' error row emitted)"

    def test_dot_empty_is_silent_redisplay(self, rsyms):
        """Bare `.` with nothing after it is silent redisplay (valid,
        not an error).  Distinguishes this cell from the garbage cell
        above — the test also pins Principle 11's 'empty' matrix cell."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x3000)
        set_line_buf(cpu, rsyms, ".")
        run_at(cpu, rsyms.exec_line)
        # No ';?' error row should appear.
        for row in range(ROWS):
            base = SCREEN + row * COLS
            assert not (cpu.memory[base] == 0x3B and
                        cpu.memory[base + 1] == 0x3F), \
                f"bare '.' produced unexpected error at row {row}"

    def test_dot_comment_is_silent_redisplay(self, rsyms):
        """`. ; note` is silent redisplay (valid — comment after dot)."""
        cpu = make_cpu(rsyms)
        set_cur_addr(cpu, rsyms, 0x3000)
        set_line_buf(cpu, rsyms, ". ; note")
        run_at(cpu, rsyms.exec_line)
        for row in range(ROWS):
            base = SCREEN + row * COLS
            assert not (cpu.memory[base] == 0x3B and
                        cpu.memory[base + 1] == 0x3F), \
                f"'. ; note' produced unexpected error at row {row}"


# ── R. Load/Save command tests ─────────────────────────────────────
#
# Moved to test_repl_disk.py — those tests still need the repl_test_stub.s
# witness variables to capture disk-op arguments.  They migrate back
# here when the virtual IEC lands in C64Emu.



# ── Q. Step into JSR — ROM target falls back to step-over ───────
#
# Moved to tests/test_step_rom.py (C64Emu-based, no layout fragility).
# The old tests were xfail'd because step_witness was computed from
# a hardcoded BSS offset that broke on any code size change.
