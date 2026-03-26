"""
test_symtab.py — Symbol table tests (symtab.s)

Entry: hash(1) + value(2) + packed_name(6) = 9 bytes × 128 slots.
Names: 8 chars × 6 bits packed inline. No string pool.
Characters: a-z (1-26), 0-9 (27-36), . (37), 0 = end/padding.
Case insensitive: all names folded to lowercase.
Hash byte: 7-bit hash (bit 7 reserved for flags). 0 = empty slot.

Interface (ZP):
  sym_define(sym_name, sym_val): store name→value. C=1 if full.
  sym_lookup(sym_name):          find name→sym_val. C=1 if not found.
  sym_clear():                   wipe all slots.

sym_name points to a NUL-terminated PETSCII string.
The symtab internally packs and case-folds the name.
"""

import subprocess, pathlib, re, pytest
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
_NAME_BUF   = 0x0C00   # must be above CODE+RODATA+BSS
_RETURN     = 0x0F00

# ── Build ────────────────────────────────────────────────────

def _sources():
    return [SRC / "symtab.s", DEV / "symtab_test_stub.s", DEV / "test.cfg"]

def _needs_rebuild():
    if not BIN.exists(): return True
    t = BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in _sources())

def _build():
    BUILD.mkdir(exist_ok=True)
    for name, src in [("symtab", SRC / "symtab.s"),
                      ("symtab_test_stub", DEV / "symtab_test_stub.s")]:
        subprocess.run(["ca65", "--cpu", "6502", "-t", "c64", str(src),
                        "-o", str(BUILD / f"{name}.o")], check=True)
    subprocess.run(["ld65", "-C", str(DEV / "test.cfg"),
                    str(BUILD / "symtab.o"), str(BUILD / "symtab_test_stub.o"),
                    "-o", str(BIN), "-m", str(MAP)], check=True)

def _parse_exports():
    syms = {}
    in_exp = False
    for line in MAP.read_text().splitlines():
        if "Exports list by name" in line: in_exp = True; continue
        if in_exp:
            for m in re.finditer(r'(\w+)\s+([0-9a-fA-F]{6})\s+RL', line):
                syms[m.group(1)] = int(m.group(2), 16)
            if line.strip() == "": break
    return syms

def _parse_stub_offset():
    in_stub = False
    for line in MAP.read_text().splitlines():
        if 'symtab_test_stub.o:' in line: in_stub = True; continue
        if in_stub and 'CODE' in line:
            m = re.search(r'Offs=([0-9a-fA-F]+)', line)
            if m: return int(m.group(1), 16)
            break
        if in_stub and not line.startswith(' '): break
    return None

class SymtabSyms:
    def __init__(self):
        if _needs_rebuild(): _build()
        self.exports = _parse_exports()
        self._raw = BIN.read_bytes()
        stub_off = _parse_stub_offset()
        if stub_off is None:
            raise RuntimeError("Cannot find symtab_test_stub CODE offset")
        base = _CODE_START + stub_off
        self.sym_define = base       # JSR _sym_define / capture carry / RTS
        self.sym_lookup = base + 7   # JSR _sym_lookup / capture carry / RTS
        self.sym_clear  = base + 14  # JMP _sym_clear
        self.sym_name = self.exports["sym_name"]
        self.sym_val  = self.exports["sym_val"]

    def load_into(self, mem):
        mem[_ZP_START:_ZP_START + _ZP_SIZE] = self._raw[:_ZP_SIZE]
        code = self._raw[_ZP_SIZE:]
        mem[_CODE_START:_CODE_START + len(code)] = code

@pytest.fixture(scope="session")
def symt():
    return SymtabSyms()

# ── Helpers ──────────────────────────────────────────────────

_name_alloc_ptr = _NAME_BUF

def _petscii(s):
    """Convert ASCII string to PETSCII bytes (NUL-terminated)."""
    SPECIAL = {'.': 0x2E}
    out = []
    for c in s:
        if c in SPECIAL: out.append(SPECIAL[c])
        elif 'a' <= c <= 'z': out.append(ord(c) - ord('a') + 0x41)
        elif 'A' <= c <= 'Z': out.append(ord(c) - ord('A') + 0xC1)
        else: out.append(ord(c))
    out.append(0)
    return bytes(out)

def _place_name(mem, name):
    """Write PETSCII name at next free address."""
    global _name_alloc_ptr
    addr = _name_alloc_ptr
    enc = _petscii(name)
    for i, b in enumerate(enc): mem[addr + i] = b
    _name_alloc_ptr += len(enc)
    return addr

def _setup_cpu(symt):
    global _name_alloc_ptr
    _name_alloc_ptr = _NAME_BUF
    mpu = MPU()
    mem = bytearray(0x10000)
    symt.load_into(mem)
    mpu.memory = mem
    return mpu, mem

def _call(mpu, mem, entry):
    mem[_RETURN] = 0x00
    mpu.sp = 0xFF
    mpu.sp -= 1; mem[0x01FF] = (_RETURN - 1) >> 8
    mpu.sp -= 1; mem[0x01FE] = (_RETURN - 1) & 0xFF
    mpu.pc = entry
    for _ in range(50000):
        if mpu.pc == _RETURN: return
        mpu.step()
    pytest.fail(f"Timeout at PC=${mpu.pc:04X}")

def _define(symt, mpu, mem, name, value):
    addr = _place_name(mem, name)
    mem[symt.sym_name] = addr & 0xFF
    mem[symt.sym_name + 1] = (addr >> 8) & 0xFF
    mem[symt.sym_val] = value & 0xFF
    mem[symt.sym_val + 1] = (value >> 8) & 0xFF
    _call(mpu, mem, symt.sym_define)
    return not (mpu.p & 0x01)

def _lookup(symt, mpu, mem, name):
    addr = _place_name(mem, name)
    mem[symt.sym_name] = addr & 0xFF
    mem[symt.sym_name + 1] = (addr >> 8) & 0xFF
    _call(mpu, mem, symt.sym_lookup)
    found = not (mpu.p & 0x01)
    value = mem[symt.sym_val] | (mem[symt.sym_val + 1] << 8)
    return found, value

def _clear(symt, mpu, mem):
    _call(mpu, mem, symt.sym_clear)

# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════

class TestBasicOperations:
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
        assert found and val == 0x1000

    def test_define_multiple(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "alpha", 0x0800)
        _define(symt, mpu, mem, "beta",  0x0900)
        _define(symt, mpu, mem, "gamma", 0x0A00)
        found, val = _lookup(symt, mpu, mem, "beta")
        assert found and val == 0x0900

    def test_redefine_updates_value(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "ptr", 0x00FB)
        _define(symt, mpu, mem, "ptr", 0x00FD)
        found, val = _lookup(symt, mpu, mem, "ptr")
        assert found and val == 0x00FD

    def test_clear_wipes_all(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "test", 0x1234)
        _clear(symt, mpu, mem)
        found, _ = _lookup(symt, mpu, mem, "test")
        assert not found


class TestCaseInsensitive:
    """All names are case-folded to lowercase internally."""

    def test_define_upper_lookup_lower(self, symt):
        """Define as 'LOOP', lookup as 'loop' → found."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "LOOP", 0x1000)
        found, val = _lookup(symt, mpu, mem, "loop")
        assert found and val == 0x1000

    def test_define_lower_lookup_upper(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "start", 0x0800)
        found, val = _lookup(symt, mpu, mem, "START")
        assert found and val == 0x0800

    def test_define_mixed_lookup_lower(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "MyFunc", 0x2000)
        found, val = _lookup(symt, mpu, mem, "myfunc")
        assert found and val == 0x2000

    def test_redefine_different_case(self, symt):
        """Redefine same name in different case → updates value."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "ptr", 0x00FB)
        _define(symt, mpu, mem, "PTR", 0x00FD)
        found, val = _lookup(symt, mpu, mem, "ptr")
        assert found and val == 0x00FD


class TestNameMatching:
    def test_no_prefix_match(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "foobar", 0x1000)
        found, _ = _lookup(symt, mpu, mem, "foo")
        assert not found

    def test_no_suffix_match(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "foo", 0x1000)
        found, _ = _lookup(symt, mpu, mem, "foobar")
        assert not found

    def test_single_char_name(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "x", 0x42)
        found, val = _lookup(symt, mpu, mem, "x")
        assert found and val == 0x42

    def test_8_char_name(self, symt):
        """Maximum packed name length: 8 characters."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "colorram", 0xD800)
        found, val = _lookup(symt, mpu, mem, "colorram")
        assert found and val == 0xD800

    def test_9th_char_ignored(self, symt):
        """Names longer than 8 chars: only first 8 matter."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "colorrama", 0xD800)
        found, val = _lookup(symt, mpu, mem, "colorramb")
        assert found and val == 0xD800  # first 8 chars match

    def test_name_with_digits(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "sprite0", 0x0380)
        found, val = _lookup(symt, mpu, mem, "sprite0")
        assert found and val == 0x0380

    def test_name_with_dot_prefix(self, symt):
        """Local label convention: .loop"""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, ".loop", 0x1020)
        found, val = _lookup(symt, mpu, mem, ".loop")
        assert found and val == 0x1020


class TestCollisions:
    """Names that might hash to the same slot."""

    def test_collision_both_found(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        names = ["aa", "bb", "cc", "dd", "ee", "ff",
                 "ab", "ba", "ac", "ca", "ad", "da",
                 "xyz", "zyx", "abc", "cba"]
        for i, n in enumerate(names):
            ok = _define(symt, mpu, mem, n, 0x1000 + i)
            assert ok
        for i, n in enumerate(names):
            found, val = _lookup(symt, mpu, mem, n)
            assert found and val == 0x1000 + i

    def test_similar_names(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "loop1", 0x1000)
        _define(symt, mpu, mem, "loop2", 0x2000)
        _define(symt, mpu, mem, "loop3", 0x3000)
        found, val = _lookup(symt, mpu, mem, "loop2")
        assert found and val == 0x2000


class TestCapacity:
    def test_fill_to_96(self, symt):
        """75% load factor — 96 out of 128 slots."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(96):
            name = f"s{i:03d}"
            ok = _define(symt, mpu, mem, name, 0x1000 + i)
            assert ok, f"define #{i} ({name}) failed"
        # Verify all
        for i in range(96):
            name = f"s{i:03d}"
            found, val = _lookup(symt, mpu, mem, name)
            assert found, f"lookup {name} failed"
            assert val == 0x1000 + i

    def test_full_table_returns_error(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(128):
            name = f"f{i:03d}"
            ok = _define(symt, mpu, mem, name, i)
            assert ok, f"define #{i} failed (table full too early)"
        ok = _define(symt, mpu, mem, "over", 0xFFFF)
        assert not ok, "129th define should fail"

    def test_redefine_doesnt_consume_slot(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "x", 1)
        _define(symt, mpu, mem, "x", 2)
        _define(symt, mpu, mem, "x", 3)
        found, val = _lookup(symt, mpu, mem, "x")
        assert found and val == 3


class TestEdgeCases:
    def test_value_zero(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "null", 0)
        found, val = _lookup(symt, mpu, mem, "null")
        assert found and val == 0

    def test_value_ffff(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "top", 0xFFFF)
        found, val = _lookup(symt, mpu, mem, "top")
        assert found and val == 0xFFFF

    def test_define_after_clear(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "a", 1)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "b", 2)
        found, _ = _lookup(symt, mpu, mem, "a")
        assert not found
        found, val = _lookup(symt, mpu, mem, "b")
        assert found and val == 2
