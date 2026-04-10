"""
test_symtab.py — Symbol table contract tests (symtab.s)

Entry: hash(1) + value(2) + name_ptr(2) + scope(1) = 6 bytes × 128 slots.
Names stored as NUL-terminated PETSCII strings (pointer in entry).
Case insensitive: names compared with uppercase folded to lowercase.
Characters: a-z, 0-9, dot. No underscore (not on C64 keyboard).
Empty slot: name_ptr == $0000 (hash 0 is valid, not a sentinel).

Interface (ZP):
  sym_define(sym_name, sym_val, sym_wide): store. C=1 if full.
  sym_lookup(sym_name): find → sym_val, sym_wide. C=1 if not found.
  sym_clear(): wipe all slots.
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
_CODE_START = 0x4000
_ZP_SIZE    = 0x0100
_NAME_BUF   = 0x1000   # must be above CODE+RODATA+BSS, with room for ~200 names
_RETURN     = 0x0F00

# ── Build ────────────────────────────────────────────────────

def _sources():
    return [SRC / "symtab.s", SRC / "mem.s",
            DEV / "symtab_test_stub.s", DEV / "test.cfg"]

def _needs_rebuild():
    if not BIN.exists(): return True
    t = BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in _sources())

def _build():
    BUILD.mkdir(exist_ok=True)
    for name, src in [("symtab", SRC / "symtab.s"),
                      ("mem", SRC / "mem.s"),
                      ("symtab_test_stub", DEV / "symtab_test_stub.s")]:
        subprocess.run(["ca65", "--cpu", "6502", "-t", "c64", str(src),
                        "-o", str(BUILD / f"{name}.o")], check=True)
    subprocess.run(["ld65", "-C", str(DEV / "test.cfg"),
                    str(BUILD / "symtab.o"), str(BUILD / "mem.o"),
                    str(BUILD / "symtab_test_stub.o"),
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
        # Each handler: JSR(3) + LDA(2) + BCC(2) + LDA(2) + STA_ZP(2) + RTS(1) = 12 bytes
        self.sym_define = base          # test_define
        self.sym_lookup = base + 12     # test_lookup
        self.sym_clear  = base + 24     # test_clear (JMP)
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

def _define(symt, mpu, mem, name, value, wide=0):
    addr = _place_name(mem, name)
    mem[symt.sym_name] = addr & 0xFF
    mem[symt.sym_name + 1] = (addr >> 8) & 0xFF
    mem[symt.sym_val] = value & 0xFF
    mem[symt.sym_val + 1] = (value >> 8) & 0xFF
    sw = symt.exports.get("sym_wide")
    if sw is not None:
        mem[sw] = wide
    _call(mpu, mem, symt.sym_define)
    return not (mpu.p & 0x01)

def _lookup(symt, mpu, mem, name):
    addr = _place_name(mem, name)
    mem[symt.sym_name] = addr & 0xFF
    mem[symt.sym_name + 1] = (addr >> 8) & 0xFF
    _call(mpu, mem, symt.sym_lookup)
    found = not (mpu.p & 0x01)
    value = mem[symt.sym_val] | (mem[symt.sym_val + 1] << 8)
    sw = symt.exports.get("sym_wide")
    wide = mem[sw] if sw is not None else 0
    return found, value, wide

def _clear(symt, mpu, mem):
    _call(mpu, mem, symt.sym_clear)

# ═══════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════

class TestBasicOperations:
    def test_lookup_undefined_fails(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        found, _, _ = _lookup(symt, mpu, mem, "foo")
        assert not found

    def test_define_then_lookup(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        ok = _define(symt, mpu, mem, "start", 0x1000)
        assert ok
        found, val, _ = _lookup(symt, mpu, mem, "start")
        assert found and val == 0x1000

    def test_define_multiple(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "alpha", 0x0800)
        _define(symt, mpu, mem, "beta",  0x0900)
        _define(symt, mpu, mem, "gamma", 0x0A00)
        found, val, _ = _lookup(symt, mpu, mem, "beta")
        assert found and val == 0x0900

    def test_redefine_updates_value(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "ptr", 0x00FB)
        _define(symt, mpu, mem, "ptr", 0x00FD)
        found, val, _ = _lookup(symt, mpu, mem, "ptr")
        assert found and val == 0x00FD

    def test_clear_wipes_all(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "test", 0x1234)
        _clear(symt, mpu, mem)
        found, _, _ = _lookup(symt, mpu, mem, "test")
        assert not found


class TestCaseInsensitive:
    """All names are case-folded to lowercase internally."""

    def test_define_upper_lookup_lower(self, symt):
        """Define as 'LOOP', lookup as 'loop' → found."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "LOOP", 0x1000)
        found, val, _ = _lookup(symt, mpu, mem, "loop")
        assert found and val == 0x1000

    def test_define_lower_lookup_upper(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "start", 0x0800)
        found, val, _ = _lookup(symt, mpu, mem, "START")
        assert found and val == 0x0800

    def test_define_mixed_lookup_lower(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "MyFunc", 0x2000)
        found, val, _ = _lookup(symt, mpu, mem, "myfunc")
        assert found and val == 0x2000

    def test_redefine_different_case(self, symt):
        """Redefine same name in different case → updates value."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "ptr", 0x00FB)
        _define(symt, mpu, mem, "PTR", 0x00FD)
        found, val, _ = _lookup(symt, mpu, mem, "ptr")
        assert found and val == 0x00FD


class TestNameMatching:
    def test_no_prefix_match(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "foobar", 0x1000)
        found, _, _ = _lookup(symt, mpu, mem, "foo")
        assert not found

    def test_no_suffix_match(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "foo", 0x1000)
        found, _, _ = _lookup(symt, mpu, mem, "foobar")
        assert not found

    def test_single_char_name(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "x", 0x42)
        found, val, _ = _lookup(symt, mpu, mem, "x")
        assert found and val == 0x42

    def test_8_char_name(self, symt):
        """8-character name — no length limit."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "colorram", 0xD800)
        found, val, _ = _lookup(symt, mpu, mem, "colorram")
        assert found and val == 0xD800

    def test_long_names_distinct(self, symt):
        """Names are compared in full — no truncation."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "colorrama", 0xD800)
        _define(symt, mpu, mem, "colorramb", 0xD900)
        found, val, _ = _lookup(symt, mpu, mem, "colorrama")
        assert found and val == 0xD800
        found, val, _ = _lookup(symt, mpu, mem, "colorramb")
        assert found and val == 0xD900

    def test_name_with_digits(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "sprite0", 0x0380)
        found, val, _ = _lookup(symt, mpu, mem, "sprite0")
        assert found and val == 0x0380

    def test_name_with_dot_prefix(self, symt):
        """Local label convention: .loop"""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, ".loop", 0x1020)
        found, val, _ = _lookup(symt, mpu, mem, ".loop")
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
            found, val, _ = _lookup(symt, mpu, mem, n)
            assert found and val == 0x1000 + i

    def test_similar_names(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "loop1", 0x1000)
        _define(symt, mpu, mem, "loop2", 0x2000)
        _define(symt, mpu, mem, "loop3", 0x3000)
        found, val, _ = _lookup(symt, mpu, mem, "loop2")
        assert found and val == 0x2000


class TestCapacity:
    def test_fill_to_96(self, symt):
        """37.5% load factor — 96 out of 256 slots."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(96):
            name = f"s{i:03d}"
            ok = _define(symt, mpu, mem, name, 0x1000 + i)
            assert ok, f"define #{i} ({name}) failed"
        # Verify all
        for i in range(96):
            name = f"s{i:03d}"
            found, val, _ = _lookup(symt, mpu, mem, name)
            assert found, f"lookup {name} failed"
            assert val == 0x1000 + i

    def test_full_table_returns_error(self, symt):
        # Capacity is 256: empty marker is name_ptr=$0000, which never
        # collides with a real heap pointer (heap lives at $E600+).
        # Probe-wrap detection in sym_define catches the 257th insert.
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(256):
            name = f"f{i:03d}"
            ok = _define(symt, mpu, mem, name, i)
            assert ok, f"define #{i} failed (table full too early)"
        ok = _define(symt, mpu, mem, "over", 0xFFFF)
        assert not ok, "257th define should fail (256 max)"

    def test_full_table_lookup_all(self, symt):
        """All 256 entries must remain reachable after a full fill."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(256):
            name = f"f{i:03d}"
            assert _define(symt, mpu, mem, name, i)
        for i in range(256):
            name = f"f{i:03d}"
            found, val, _ = _lookup(symt, mpu, mem, name)
            assert found, f"lookup {name} failed after full fill"
            assert val == i

    def test_full_table_redefine_succeeds(self, symt):
        """Redefining an existing key at full capacity must succeed
        (it does not consume a slot)."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(256):
            assert _define(symt, mpu, mem, f"f{i:03d}", i)
        # Update an existing key — must NOT report full
        ok = _define(symt, mpu, mem, "f000", 0xBEEF)
        assert ok, "redefine at full capacity should succeed"
        found, val, _ = _lookup(symt, mpu, mem, "f000")
        assert found and val == 0xBEEF

    def test_clear_releases_full_table(self, symt):
        """After sym_clear, a previously-full table accepts 256 new entries."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        for i in range(256):
            assert _define(symt, mpu, mem, f"f{i:03d}", i)
        _clear(symt, mpu, mem)
        for i in range(256):
            assert _define(symt, mpu, mem, f"g{i:03d}", i + 1000), \
                f"post-clear define #{i} failed"
        # Old keys must be gone
        found, _, _ = _lookup(symt, mpu, mem, "f000")
        assert not found

    def test_redefine_doesnt_consume_slot(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "x", 1)
        _define(symt, mpu, mem, "x", 2)
        _define(symt, mpu, mem, "x", 3)
        found, val, _ = _lookup(symt, mpu, mem, "x")
        assert found and val == 3


class TestEdgeCases:
    def test_value_zero(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "null", 0)
        found, val, _ = _lookup(symt, mpu, mem, "null")
        assert found and val == 0

    def test_value_ffff(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "top", 0xFFFF)
        found, val, _ = _lookup(symt, mpu, mem, "top")
        assert found and val == 0xFFFF

    def test_define_after_clear(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "a", 1)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "b", 2)
        found, _, _ = _lookup(symt, mpu, mem, "a")
        assert not found
        found, val, _ = _lookup(symt, mpu, mem, "b")
        assert found and val == 2


class TestWidthFlag:
    """sym_wide (ZP/ABS) stored in scope byte bit 7, returned as 0 or 1."""

    def test_define_zp_lookup_zp(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "ptr", 0x00FB, wide=0)
        found, val, wide = _lookup(symt, mpu, mem, "ptr")
        assert found and val == 0x00FB
        assert wide == 0, f"expected wide=0 (ZP), got {wide}"

    def test_define_abs_lookup_abs(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "screen", 0x0400, wide=1)
        found, val, wide = _lookup(symt, mpu, mem, "screen")
        assert found and val == 0x0400
        assert wide == 1, f"expected wide=1 (ABS), got {wide}"

    def test_redefine_changes_width(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "val", 0x0042, wide=0)
        _define(symt, mpu, mem, "val", 0x0042, wide=1)
        found, _, wide = _lookup(symt, mpu, mem, "val")
        assert found and wide == 1

    def test_different_widths_coexist(self, symt):
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "zpvar", 0x00FB, wide=0)
        _define(symt, mpu, mem, "absvar", 0x0400, wide=1)
        _, _, w1 = _lookup(symt, mpu, mem, "zpvar")
        _, _, w2 = _lookup(symt, mpu, mem, "absvar")
        assert w1 == 0 and w2 == 1


class TestDesignGuarantees:
    """Tests that pin down documented design decisions."""

    def test_hash_zero_is_valid(self, symt):
        """'uw' hashes to 0.  Must round-trip — hash 0 is not a sentinel."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        ok = _define(symt, mpu, mem, "uw", 0xBEEF)
        assert ok
        found, val, _ = _lookup(symt, mpu, mem, "uw")
        assert found and val == 0xBEEF

    def test_heap_isolation(self, symt):
        """After define, overwriting the source buffer must not affect lookup."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        addr = _place_name(mem, "victim")
        mem[symt.sym_name] = addr & 0xFF
        mem[symt.sym_name + 1] = (addr >> 8) & 0xFF
        mem[symt.sym_val] = 0x42
        mem[symt.sym_val + 1] = 0x00
        sw = symt.exports.get("sym_wide")
        if sw is not None: mem[sw] = 0
        _call(mpu, mem, symt.sym_define)
        # Overwrite the source buffer where the name was
        for i in range(7):
            mem[addr + i] = 0xFF
        # Lookup must still find it (name lives in heap, not source)
        found, val, _ = _lookup(symt, mpu, mem, "victim")
        assert found, "name should be in heap, not source buffer"
        assert val == 0x42

    def test_dot_in_middle(self, symt):
        """Local label path 'main.loop' — dot in the middle, not just prefix."""
        mpu, mem = _setup_cpu(symt)
        _clear(symt, mpu, mem)
        _define(symt, mpu, mem, "main.loop", 0xC010)
        _define(symt, mpu, mem, "main.done", 0xC020)
        found, val, _ = _lookup(symt, mpu, mem, "main.loop")
        assert found and val == 0xC010
        found, val, _ = _lookup(symt, mpu, mem, "main.done")
        assert found and val == 0xC020
        # Must not confuse with just "main" or ".loop"
        found, _, _ = _lookup(symt, mpu, mem, "main")
        assert not found
        found, _, _ = _lookup(symt, mpu, mem, ".loop")
        assert not found
