"""
test_symtab.py — TDD test suite for the symbol table (symtab.s)

Tests the consumer-facing guarantees:
  sym_define(name, value) → C=1 if full
  sym_lookup(name)        → sym_val + C=1 if not found
  sym_clear()             → wipes all symbols

Written BEFORE the implementation (TDD). All tests should fail
until symtab.s is implemented.
"""

import subprocess
import pathlib
import re
import pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

BIN = BUILD / "symtab_test.bin"
MAP = BUILD / "symtab_test.map"

_ZP_START   = 0x0000
_CODE_START = 0x0200
_ZP_SIZE    = 0x0100
_NAME_BUF   = 0x0A00      # where we place name strings (must be above CODE+RODATA+BSS)
_RETURN     = 0x0F00       # sentinel address for RTS detection

# ── Build infrastructure ─────────────────────────────────────────

def _sources():
    return [SRC / "symtab.s", DEV / "symtab_test_stub.s", DEV / "test.cfg"]

def _needs_rebuild():
    if not BIN.exists():
        return True
    t = BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in _sources())

def _build():
    BUILD.mkdir(exist_ok=True)
    for name, src in [("symtab", SRC / "symtab.s"),
                      ("symtab_test_stub", DEV / "symtab_test_stub.s")]:
        subprocess.run(
            ["ca65", "--cpu", "6502", str(src), "-o", str(BUILD / f"{name}.o")],
            check=True,
        )
    subprocess.run(
        ["ld65", "-C", str(DEV / "test.cfg"),
         str(BUILD / "symtab.o"), str(BUILD / "symtab_test_stub.o"),
         "-o", str(BIN), "-m", str(MAP)],
        check=True,
    )

def _parse_exports():
    syms = {}
    in_exports = False
    for line in MAP.read_text().splitlines():
        if "Exports list by name" in line:
            in_exports = True
            continue
        if in_exports:
            # exports can have multiple entries per line
            for m in re.finditer(r'(\w+)\s+([0-9a-fA-F]+)', line):
                syms[m.group(1)] = int(m.group(2), 16)
            if line.strip() == "":
                break
    return syms

def _find_entry(name, exports):
    """Find symbol address — check exports first, then compute from map."""
    if name in exports:
        return exports[name]
    # Try parsing module offsets (for symbols not in exports list)
    in_stub = False
    for line in MAP.read_text().splitlines():
        if 'symtab_test_stub.o' in line and ':' in line:
            in_stub = True
            continue
        if in_stub and 'CODE' in line:
            m = re.search(r'Offs=([0-9a-fA-F]+)', line)
            if m:
                return _CODE_START + int(m.group(1), 16)
            break
    return None


class SymtabSyms:
    def __init__(self):
        if _needs_rebuild():
            _build()
        exp = _parse_exports()
        # Use the asm functions directly (wrapper stubs aren't in exports)
        self.sym_define = exp.get("_sym_define")
        self.sym_lookup = exp.get("_sym_lookup")
        self.sym_clear  = exp.get("_sym_clear")
        self.sym_name   = exp.get("sym_name")     # ZP address
        self.sym_val    = exp.get("sym_val")       # ZP address
        assert self.sym_define, "Can't find _sym_define"
        assert self.sym_lookup, "Can't find _sym_lookup"
        assert self.sym_clear,  "Can't find _sym_clear"
        self._raw = BIN.read_bytes()

    def load_into(self, mem):
        mem[_ZP_START:_ZP_START + _ZP_SIZE] = self._raw[:_ZP_SIZE]
        code = self._raw[_ZP_SIZE:]
        mem[_CODE_START:_CODE_START + len(code)] = code


@pytest.fixture(scope="session")
def symt():
    return SymtabSyms()


# ── Helpers ──────────────────────────────────────────────────────

_name_alloc_ptr = _NAME_BUF

def _place_name(mem, name, addr=None):
    """Write PETSCII name string at next free address, NUL-terminated."""
    global _name_alloc_ptr
    if addr is None:
        addr = _name_alloc_ptr
        _name_alloc_ptr += len(name) + 1
    SPECIAL = {'_': 0xA4, '.': 0x2E}
    for i, ch in enumerate(name):
        if ch in SPECIAL:
            c = SPECIAL[ch]
        elif ord('a') <= ord(ch) <= ord('z'):
            c = ord(ch) - ord('a') + 0x41  # PETSCII lowercase
        elif ord('A') <= ord(ch) <= ord('Z'):
            c = ord(ch) - ord('A') + 0xC1  # PETSCII uppercase (shifted)
        else:
            c = ord(ch)
        mem[addr + i] = c
    mem[addr + len(name)] = 0
    return addr

def _setup_cpu(symt):
    """Create a fresh CPU with the test binary loaded."""
    global _name_alloc_ptr
    _name_alloc_ptr = _NAME_BUF  # reset name allocator
    mpu = MPU()
    mem = bytearray(0x10000)
    symt.load_into(mem)
    mpu.memory = mem
    return mpu, mem

def _call(mpu, mem, entry):
    """JSR to entry, run until RTS returns to _RETURN."""
    mem[_RETURN] = 0x00  # BRK sentinel
    mpu.sp = 0xFF
    mpu.sp -= 1; mem[0x01FF] = (_RETURN - 1) >> 8
    mpu.sp -= 1; mem[0x01FE] = (_RETURN - 1) & 0xFF
    mpu.pc = entry
    for _ in range(50000):
        if mpu.pc == _RETURN:
            return
        mpu.step()
    pytest.fail(f"Timeout at PC=${mpu.pc:04X}")

def _define(symt, mpu, mem, name, value):
    """Call sym_define(name, value). Returns True if ok, False if full."""
    addr = _place_name(mem, name)
    mem[symt.sym_name]     = addr & 0xFF
    mem[symt.sym_name + 1] = (addr >> 8) & 0xFF
    mem[symt.sym_val]      = value & 0xFF
    mem[symt.sym_val + 1]  = (value >> 8) & 0xFF
    _call(mpu, mem, symt.sym_define)
    # Carry flag: bit 0 of processor status
    return not (mpu.p & 0x01)  # C=0 → ok, C=1 → full

def _lookup(symt, mpu, mem, name):
    """Call sym_lookup(name). Returns (found, value)."""
    addr = _place_name(mem, name)
    mem[symt.sym_name]     = addr & 0xFF
    mem[symt.sym_name + 1] = (addr >> 8) & 0xFF
    _call(mpu, mem, symt.sym_lookup)
    found = not (mpu.p & 0x01)  # C=0 → found
    value = mem[symt.sym_val] | (mem[symt.sym_val + 1] << 8)
    return found, value

def _clear(symt, mpu, mem):
    """Call sym_clear()."""
    _call(mpu, mem, symt.sym_clear)


# ── Core Tests ───────────────────────────────────────────────────

class TestBasicOperations:
    """Define, lookup, clear — the fundamental contract."""

    def test_lookup_undefined_fails(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        found, _ = _lookup(symt, mpu, mem, "foo")
        assert not found

    def test_define_then_lookup(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        ok = _define(symt, mpu, mem, "start", 0x1000)
        assert ok
        found, val = _lookup(symt, mpu, mem, "start")
        assert found
        assert val == 0x1000

    def test_define_multiple(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "alpha", 0x0800)
        _define(symt, mpu, mem, "beta",  0x0900)
        _define(symt, mpu, mem, "gamma", 0x0A00)
        found, val = _lookup(symt, mpu, mem, "beta")
        assert found and val == 0x0900
        found, val = _lookup(symt, mpu, mem, "gamma")
        assert found and val == 0x0A00
        found, val = _lookup(symt, mpu, mem, "alpha")
        assert found and val == 0x0800

    def test_redefine_updates_value(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "ptr", 0x1000)
        _define(symt, mpu, mem, "ptr", 0x2000)
        found, val = _lookup(symt, mpu, mem, "ptr")
        assert found and val == 0x2000

    def test_clear_wipes_all(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "x", 0x1234)
        _define(symt, mpu, mem, "y", 0x5678)
        _clear(symt, mpu, mem)
        found, _ = _lookup(symt, mpu, mem, "x")
        assert not found
        found, _ = _lookup(symt, mpu, mem, "y")
        assert not found


class TestNameMatching:
    """Name comparison must be exact — no prefix matching, case sensitive."""

    def test_no_prefix_match(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "foo", 0x1000)
        found, _ = _lookup(symt, mpu, mem, "foobar")
        assert not found

    def test_no_suffix_match(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "foobar", 0x1000)
        found, _ = _lookup(symt, mpu, mem, "foo")
        assert not found

    def test_case_sensitive(self, symt):
        """PETSCII: 'a' ($41) != 'A' ($C1)."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "loop", 0x1000)   # lowercase
        found, _ = _lookup(symt, mpu, mem, "Loop")  # uppercase L
        assert not found
        found, val = _lookup(symt, mpu, mem, "loop")
        assert found and val == 0x1000

    def test_single_char_name(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "x", 0x00FF)
        found, val = _lookup(symt, mpu, mem, "x")
        assert found and val == 0x00FF

    def test_long_name(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        name = "verylonglabel"  # 13 chars
        _define(symt, mpu, mem, name, 0xBEEF)
        found, val = _lookup(symt, mpu, mem, name)
        assert found and val == 0xBEEF


class TestCollisions:
    """Hash collisions must resolve via linear probing."""

    def test_collision_both_found(self, symt):
        """Define two names that might collide, both must be found."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        # These short names are likely to have different hashes,
        # but we test many pairs to catch collision handling.
        names = ["aa", "ab", "ba", "bb", "ca", "cb", "da", "db",
                 "ea", "eb", "fa", "fb", "ga", "gb", "ha", "hb"]
        for i, n in enumerate(names):
            ok = _define(symt, mpu, mem, n, 0x1000 + i)
            assert ok, f"define {n} failed"
        for i, n in enumerate(names):
            found, val = _lookup(symt, mpu, mem, n)
            assert found, f"lookup {n} not found"
            assert val == 0x1000 + i, f"lookup {n}: got ${val:04X}, expected ${0x1000+i:04X}"

    def test_similar_names(self, symt):
        """Names that differ only in the last char."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "loopa", 0x1000)
        _define(symt, mpu, mem, "loopb", 0x2000)
        _define(symt, mpu, mem, "loopc", 0x3000)
        found, val = _lookup(symt, mpu, mem, "loopb")
        assert found and val == 0x2000


class TestCapacity:
    """Table must handle load up to 128 entries, then report full."""

    def test_fill_to_capacity(self, symt):
        """Define 96 symbols (75% of 128). All must be found."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(96):
            name = f"s{i:03d}"
            ok = _define(symt, mpu, mem, name, 0x1000 + i)
            assert ok, f"define #{i} ({name}) failed"
        # Verify a sample
        for i in [0, 47, 95]:
            name = f"s{i:03d}"
            found, val = _lookup(symt, mpu, mem, name)
            assert found, f"lookup {name} failed"
            assert val == 0x1000 + i

    def test_full_table_returns_error(self, symt):
        """After 128 defines, the next must fail with C=1."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(128):
            name = f"f{i:03d}"
            ok = _define(symt, mpu, mem, name, i)
            assert ok, f"define #{i} failed (table full too early)"
        # 129th should fail
        ok = _define(symt, mpu, mem, "overflow", 0xFFFF)
        assert not ok, "129th define should fail"

    def test_redefine_doesnt_consume_slot(self, symt):
        """Redefining an existing name must not use a new slot."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(128):
            _define(symt, mpu, mem, f"r{i:03d}", i)
        # Table is full. Redefine an existing one — must succeed.
        ok = _define(symt, mpu, mem, "r050", 0xAAAA)
        assert ok, "redefine of existing symbol should succeed even when full"
        found, val = _lookup(symt, mpu, mem, "r050")
        assert found and val == 0xAAAA


class TestEdgeCases:
    """Boundary values and special inputs."""

    def test_value_zero(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "zero", 0x0000)
        found, val = _lookup(symt, mpu, mem, "zero")
        assert found and val == 0x0000

    def test_value_ffff(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "top", 0xFFFF)
        found, val = _lookup(symt, mpu, mem, "top")
        assert found and val == 0xFFFF

    def test_define_after_clear(self, symt):
        """Clear then reuse — table must be fully functional."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "first", 0x1111)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "second", 0x2222)
        found, _ = _lookup(symt, mpu, mem, "first")
        assert not found
        found, val = _lookup(symt, mpu, mem, "second")
        assert found and val == 0x2222

    def test_names_with_digits(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "var1", 0x0001)
        _define(symt, mpu, mem, "var2", 0x0002)
        found, val = _lookup(symt, mpu, mem, "var1")
        assert found and val == 0x0001
        found, val = _lookup(symt, mpu, mem, "var2")
        assert found and val == 0x0002

    def test_name_with_underscore(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "my_var", 0x1234)
        found, val = _lookup(symt, mpu, mem, "my_var")
        assert found and val == 0x1234

    def test_name_with_dot_prefix(self, symt):
        """Local labels use . prefix — must work in the symbol table."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, ".loop", 0x4000)
        found, val = _lookup(symt, mpu, mem, ".loop")
        assert found and val == 0x4000
        found, _ = _lookup(symt, mpu, mem, "loop")
        assert not found  # "loop" != ".loop"
