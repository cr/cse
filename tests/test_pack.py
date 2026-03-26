"""
test_pack.py — Tests for symbol name packing (pack_name in symtab.s)

6-bit encoding: 0=end, 1-26=a-z, 27-36=0-9, 37=.
First char: 5-bit (1-27, letters+dot), bit 7 of byte 0 = ZP flag.
8 chars max, padded with 0.

Layout (48 bits = 6 bytes):
  Byte 0: [ZP c1₄ c1₃ c1₂ c1₁ c1₀ c2₅ c2₄]
  Byte 1: [c2₃ c2₂ c2₁ c2₀ c3₅ c3₄ c3₃ c3₂]
  Byte 2: [c3₁ c3₀ c4₅ c4₄ c4₃ c4₂ c4₁ c4₀]
  Byte 3: [c5₅ c5₄ c5₃ c5₂ c5₁ c5₀ c6₅ c6₄]
  Byte 4: [c6₃ c6₂ c6₁ c6₀ c7₅ c7₄ c7₃ c7₂]
  Byte 5: [c7₁ c7₀ c8₅ c8₄ c8₃ c8₂ c8₁ c8₀]

Interface:
  sym_name (ZP ptr): points to PETSCII NUL-terminated string
  pack_name: packs into 6 bytes at pack_buf (BSS)
             case-folds to lowercase
             returns packed bytes at fixed address
"""

import subprocess, pathlib, re, pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

BIN = BUILD / "pack_test.bin"
MAP = BUILD / "pack_test.map"

_STR_BUF = 0x0C00
_RETURN  = 0x0F00


def _petscii(s):
    """Convert ASCII to PETSCII."""
    SPECIAL = {'.': 0x2E}
    out = []
    for c in s:
        if c in SPECIAL: out.append(SPECIAL[c])
        elif 'a' <= c <= 'z': out.append(ord(c) - ord('a') + 0x41)
        elif 'A' <= c <= 'Z': out.append(ord(c) - ord('A') + 0xC1)
        elif '0' <= c <= '9': out.append(ord(c))
        else: out.append(ord(c))
    out.append(0)
    return bytes(out)


def _encode_char(c, is_first=False):
    """Python-side encoding. First char: 5-bit (1-26=a-z, 27=dot).
    Other chars: 6-bit (1-26=a-z, 27-36=0-9, 37=dot)."""
    if 'a' <= c <= 'z': return ord(c) - ord('a') + 1
    if 'A' <= c <= 'Z': return ord(c) - ord('A') + 1  # case fold
    if c == '.' and is_first: return 27  # 5-bit dot
    if '0' <= c <= '9': return ord(c) - ord('0') + 27
    if c == '.': return 37  # 6-bit dot
    return 0


def _pack_expected(name, zp=0):
    """Compute expected 6 packed bytes for a name (Python reference)."""
    codes = []
    for i, c in enumerate(name[:8]):
        codes.append(_encode_char(c, is_first=(i == 0)))
    while len(codes) < 8:
        codes.append(0)

    # First char is 5-bit (codes[0]), rest are 6-bit
    c1 = codes[0] & 0x1F
    c2, c3, c4, c5, c6, c7, c8 = codes[1], codes[2], codes[3], codes[4], codes[5], codes[6], codes[7]

    b0 = ((zp & 1) << 7) | (c1 << 2) | (c2 >> 4)
    b1 = ((c2 & 0xF) << 4) | (c3 >> 2)
    b2 = ((c3 & 0x3) << 6) | c4
    b3 = (c5 << 2) | (c6 >> 4)
    b4 = ((c6 & 0xF) << 4) | (c7 >> 2)
    b5 = ((c7 & 0x3) << 6) | c8

    return bytes([b0 & 0xFF, b1 & 0xFF, b2 & 0xFF, b3 & 0xFF, b4 & 0xFF, b5 & 0xFF])


# ── Build infrastructure ─────────────────────────────────

def _needs_rebuild():
    if not BIN.exists(): return True
    t = BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in [
        SRC / "symtab.s", DEV / "pack_test_stub.s", DEV / "test.cfg"])

def _build():
    BUILD.mkdir(exist_ok=True)
    for name, src in [("symtab", SRC / "symtab.s"),
                      ("pack_test_stub", DEV / "pack_test_stub.s")]:
        subprocess.run(["ca65", "--cpu", "6502", "-t", "c64", str(src),
                        "-o", str(BUILD / f"{name}.o")], check=True)
    subprocess.run(["ld65", "-C", str(DEV / "test.cfg"),
                    str(BUILD / "symtab.o"), str(BUILD / "pack_test_stub.o"),
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
        if 'pack_test_stub.o:' in line: in_stub = True; continue
        if in_stub and 'CODE' in line:
            m = re.search(r'Offs=([0-9a-fA-F]+)', line)
            if m: return int(m.group(1), 16)
            break
        if in_stub and not line.startswith(' '): break
    return None


class PackFixture:
    def __init__(self):
        if _needs_rebuild(): _build()
        self.exports = _parse_exports()
        self._raw = BIN.read_bytes()
        stub_off = _parse_stub_offset()
        if stub_off is None:
            raise RuntimeError("Cannot find pack_test_stub CODE offset")
        self.pack_entry = 0x0200 + stub_off
        self.sym_name = self.exports["sym_name"]
        self.pack_buf = self.exports.get("pack_buf")
        if self.pack_buf is None:
            # Fallback: read from pack_buf_addr in RODATA
            pba = self.exports.get("pack_buf_addr")
            if pba:
                off = pba - 0x0200 + 0x100  # absolute→file offset
                self.pack_buf = self._raw[off] | (self._raw[off+1] << 8)
        if self.pack_buf is None:
            raise RuntimeError("Cannot find pack_buf address")

    def load_into(self, mem):
        mem[0:0x100] = self._raw[:0x100]
        code = self._raw[0x100:]
        mem[0x200:0x200 + len(code)] = code


@pytest.fixture(scope="session")
def pack():
    return PackFixture()


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


def _run_pack(pack_fix, name):
    """Pack a name string. Returns 6 bytes from pack_buf."""
    mpu = MPU()
    mem = bytearray(0x10000)
    pack_fix.load_into(mem)
    mpu.memory = mem

    enc = _petscii(name)
    for i, b in enumerate(enc):
        mem[_STR_BUF + i] = b
    mem[pack_fix.sym_name] = _STR_BUF & 0xFF
    mem[pack_fix.sym_name + 1] = (_STR_BUF >> 8) & 0xFF

    _call(mpu, mem, pack_fix.pack_entry)

    pb = pack_fix.pack_buf
    return bytes([mem[pb + i] for i in range(6)])


# ═══════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════

class TestPackBasic:
    """Verify packed bytes match the Python reference implementation."""

    @pytest.mark.parametrize("name", [
        "a",
        "z",
        "abc",
        "start",
        "loop",
        "screen",
        "colorram",   # 8 chars — max
        ".loop",      # dot prefix
        "sp0",        # letters + digit
        "x",          # single char
    ], ids=lambda n: n)
    def test_pack_matches_reference(self, pack, name):
        result = _run_pack(pack, name)
        expected = _pack_expected(name)
        assert result == expected, (
            f"pack({name!r}): got {result.hex()}, expected {expected.hex()}")


class TestPackCaseFolding:
    """Uppercase input should produce same packed bytes as lowercase."""

    @pytest.mark.parametrize("upper,lower", [
        ("ABC", "abc"),
        ("START", "start"),
        ("Loop", "loop"),
        ("COLORRAM", "colorram"),
    ], ids=lambda x: x if isinstance(x, str) else None)
    def test_case_insensitive(self, pack, upper, lower):
        r_upper = _run_pack(pack, upper)
        r_lower = _run_pack(pack, lower)
        # Mask bit 7 of byte 0 (ZP flag) for comparison
        assert (r_upper[0] & 0x7F) == (r_lower[0] & 0x7F)
        assert r_upper[1:] == r_lower[1:]


class TestPackTruncation:
    """Names > 8 chars: only first 8 packed, rest ignored."""

    def test_9_chars_same_as_8(self, pack):
        r8 = _run_pack(pack, "colorram")
        r9 = _run_pack(pack, "colorrama")
        assert r8 == r9

    def test_12_chars_same_as_8(self, pack):
        r8 = _run_pack(pack, "colorram")
        r12 = _run_pack(pack, "colorramextr")
        assert r8 == r12


class TestPackPadding:
    """Short names are zero-padded."""

    def test_single_char_padded(self, pack):
        result = _run_pack(pack, "a")
        expected = _pack_expected("a")
        assert result == expected
        # Bytes 3-5 should be zero (chars 5-8 are all 0)
        assert result[3] == 0
        assert result[4] == 0
        assert result[5] == 0

    def test_empty_is_all_zero(self, pack):
        """Empty name packs to all zeros (the empty sentinel)."""
        result = _run_pack(pack, "")
        assert result == bytes(6)


class TestPackSpecialChars:
    """Digits and dot encode correctly."""

    def test_digit_encoding(self, pack):
        result = _run_pack(pack, "s0")
        expected = _pack_expected("s0")
        assert result == expected

    def test_all_digits_suffix(self, pack):
        result = _run_pack(pack, "a1234567")
        expected = _pack_expected("a1234567")
        assert result == expected

    def test_dot_prefix(self, pack):
        result = _run_pack(pack, ".loop")
        expected = _pack_expected(".loop")
        assert result == expected

    def test_dot_in_middle(self, pack):
        result = _run_pack(pack, "sys.init")
        expected = _pack_expected("sys.init")
        assert result == expected


class TestPackDistinct:
    """Different names must produce different packed bytes."""

    def test_similar_names_differ(self, pack):
        r1 = _run_pack(pack, "loop1")
        r2 = _run_pack(pack, "loop2")
        assert r1 != r2

    def test_prefix_differ(self, pack):
        r1 = _run_pack(pack, "foo")
        r2 = _run_pack(pack, "foobar")
        assert r1 != r2

    def test_suffix_differ(self, pack):
        r1 = _run_pack(pack, "bar")
        r2 = _run_pack(pack, "foobar")
        assert r1 != r2
