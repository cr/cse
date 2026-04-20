"""test_symtab.py — Tier-U unit tests for symtab.s.

Contract source: [doc/modules/symtab.md](../../doc/modules/symtab.md).

Coverage of the documented contract
-----------------------------------
All 3 API entry points + table layout + design guarantees:

    sym_define(sym_name, sym_val, sym_wide) → C=0 ok / C=1 full
        TestBasicOperations, TestCapacity, TestCollisions
    sym_lookup(sym_name) → sym_val, sym_wide, C=0 found / C=1 not
        TestBasicOperations, TestCaseInsensitive
    sym_clear()
        TestBasicOperations::test_clear_wipes_all + TestCapacity

Plus contract invariants:
    Case folding ($C1-$DA → $41-$5A)      — TestCaseInsensitive (4)
    Exact name matching (no prefix/suffix) — TestNameMatching (7)
    256-slot capacity + probe-wrap         — TestCapacity (6)
    ZP/ABS width flag (scope byte bit 7)   — TestWidthFlag (4)
    Hash 0 is valid (not empty sentinel)   — TestDesignGuarantees
    Name heap isolation from source buffer — TestDesignGuarantees

Out-of-scope (vocal skip — see TestHeapOverflow)
------------------------------------------------
Name-heap overflow detection (`heap_copy_name` vs SYM_HEAP_END) is
documented but too fragile to drive at unit tier.  Enforcement is
code-review + grep.  See the ⚠ MID-RISK L2 GAP preamble on that skip.

Bundle: zp + strings + symtab + mem + symtab_test_stub.s
        (mem is pulled in for kernal_bank_out/in used during probe).
"""

import subprocess, pathlib, pytest
from py65.devices.mpu6502 import MPU
from conftest import SymbolTable

ROOT  = pathlib.Path(__file__).parent.parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

BIN = BUILD / "symtab_test.bin"
MAP = BUILD / "symtab_test.map"
LBL = BUILD / "symtab_test.lbl"

_ZP_START   = 0x0000
_CODE_START = 0x4000
_ZP_SIZE    = 0x0100
_NAME_BUF   = 0x1000   # must be above CODE+RODATA+BSS, with room for ~200 names
_RETURN     = 0x0F00

# ── Build ────────────────────────────────────────────────────

_SOURCES = [SRC / "zp.s", SRC / "strings.s", SRC / "symtab.s", SRC / "mem.s",
            DEV / "symtab_test_stub.s"]

def _needs_rebuild():
    if not BIN.exists() or not LBL.exists(): return True
    t = BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in _SOURCES + [DEV / "test.cfg"])

def _build():
    BUILD.mkdir(exist_ok=True)
    objs = []
    for src in _SOURCES:
        obj = BUILD / f"{src.stem}_st.o"
        subprocess.run(["ca65", "-g", "--cpu", "6502", "-t", "c64",
                        "-I", str(BUILD),
                        str(src), "-o", str(obj)], check=True)
        objs.append(str(obj))
    subprocess.run(["ld65", "-C", str(DEV / "test.cfg"),
                    *objs,
                    "-o", str(BIN), "-m", str(MAP),
                    "-Ln", str(LBL)], check=True)

class SymtabSyms:
    def __init__(self):
        if _needs_rebuild(): _build()
        s = SymbolTable(LBL)
        self._raw = BIN.read_bytes()
        # Entry points — previously required hardcoded base+12/base+24
        self.sym_define = s["test_define"]
        self.sym_lookup = s["test_lookup"]
        self.sym_clear  = s["test_clear"]
        self.sym_name   = s["sym_name"]
        self.sym_val    = s["sym_val"]
        self.sym_wide   = s.get("sym_wide")

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
    sw = symt.sym_wide
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
    sw = symt.sym_wide
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
    # test_fill_to_96 retired — a 37.5%-load sanity check is subsumed
    # by test_full_table_lookup_all, which fills ALL 256 slots and
    # verifies every one round-trips.  If 256 works, 96 trivially works.

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

    # test_redefine_doesnt_consume_slot retired — the name was broader
    # than the body: asserting "three redefines yield the latest value"
    # is covered by TestBasicOperations::test_redefine_updates_value.
    # The stronger "no slot consumed" claim (redefine at full capacity
    # succeeds) is in test_full_table_redefine_succeeds above.


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
        sw = symt.sym_wide
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


# ═══════════════════════════════════════════════════════════════════
# Contract clauses intentionally not automated (vocal skips)
# ═══════════════════════════════════════════════════════════════════
#
# Skip policy per doc/testing.md § Principle 9.

# ⚠  MID-RISK L2 GAP (per coverage audit 2026-04-20):
#    The name heap lives at fixed $E600–$EEFF (2304 bytes) under
#    KERNAL ROM.  `heap_copy_name` checks `_st_heap` against
#    `SYM_HEAP_END` after each byte copy and returns C=1 on
#    overflow — but at unit tier, the test bundle's heap is
#    relocated by `dev/symtab_test_stub.s` and driving it to
#    overflow would require injecting ~2000+ long names (fragile,
#    ZP-pointer-dependent).  The overflow branch is not exercised
#    today.  A regression (e.g. missing boundary check, off-by-one
#    on `SYM_HEAP_END`) would manifest only after sustained source
#    assembly with many long labels — hard to reproduce in CI.

class TestHeapOverflow:

    @pytest.mark.skip(reason=(
        "Name-heap overflow detection (symtab.md § Name heap): "
        "`heap_copy_name` compares `_st_heap` against `SYM_HEAP_END` "
        "($EF00) after each byte copy and returns C=1 on overflow. "
        "Exercising this at unit tier requires a contrived ~2304-byte "
        "sequence of long names or a manipulated `_st_heap` starting "
        "value — both fragile and implementation-coupled.  Enforcement "
        "today: code review of `heap_copy_name` in src/symtab.s + "
        "grep for SYM_HEAP_END references (currently only "
        "heap_copy_name).  A manual VICE workflow that defines labels "
        "until overflow would confirm behaviour; not scripted."
    ))
    def test_sym_define_returns_carry_set_on_heap_overflow(self, symt):
        pass
