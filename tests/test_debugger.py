"""
test_debugger.py — Debugger breakpoint table contract tests (debugger.s)

Phase A: bp_set, bp_del, bp_clear, bp_count, dbg_init.
Phase B: bp_patch, bp_unpatch, bp_find.

Test binary: debugger.s + debugger_test_stub.s
Protocol: write command byte + args at $0B00, JSR dbg_test_entry.
"""

import subprocess, pathlib, re, pytest
from py65.devices.mpu6502 import MPU

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

BIN = BUILD / "debugger_test.bin"
MAP = BUILD / "debugger_test.map"

_ZP_START   = 0x0000
_CODE_START = 0x0200
_ZP_SIZE    = 0x0100
_RETURN     = 0x0F00

CMD   = 0x0B00
ARG1  = 0x0B01
ARG2  = 0x0B02
RFLAGS = 0x0B03
RVAL   = 0x0B04    # result value (slot#, count, etc.)

BP_SLOTS = 8
BP_SIZE  = 4

# ── Build ────────────────────────────────────────────────────

_SOURCES = [SRC / "debugger.s", DEV / "debugger_test_stub.s", DEV / "test.cfg"]

def _needs_rebuild():
    if not BIN.exists(): return True
    t = BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in _SOURCES)

def _build():
    BUILD.mkdir(exist_ok=True)
    for name, src in [("debugger", SRC / "debugger.s"),
                      ("debugger_test_stub", DEV / "debugger_test_stub.s")]:
        subprocess.run(["ca65", "--cpu", "6502", str(src),
                        "-o", str(BUILD / f"{name}.o")], check=True)
    subprocess.run(["ld65", "-C", str(DEV / "test.cfg"),
                    str(BUILD / "debugger.o"), str(BUILD / "debugger_test_stub.o"),
                    "-o", str(BIN), "-m", str(MAP)], check=True)

def _parse_map():
    """Parse segment starts, module offsets, and exports from the ld65 map file.

    Returns (segments, module_offsets, exports) where:
      segments = {'CODE': start, 'BSS': start, ...}
      module_offsets = {'debugger.o': {'CODE': offs, 'BSS': offs}, ...}
      exports = {'_dbg_init': addr, ...}
    """
    text = MAP.read_text()
    lines = text.splitlines()

    segments = {}
    module_offsets = {}
    exports = {}
    current_module = None

    # Parse segments from "Segment list" section
    for line in lines:
        m = re.match(r'^(CODE|BSS|RODATA|ZEROPAGE)\s+([0-9a-fA-F]+)\s+', line)
        if m:
            segments[m.group(1)] = int(m.group(2), 16)

    # Parse module offsets from "Modules list" section
    for line in lines:
        m = re.match(r'^(\w+\.o):', line)
        if m:
            current_module = m.group(1)
            module_offsets[current_module] = {}
            continue
        if current_module:
            m = re.match(r'\s+(CODE|BSS|RODATA)\s+Offs=([0-9a-fA-F]+)', line)
            if m:
                module_offsets[current_module][m.group(1)] = int(m.group(2), 16)
            elif not line.startswith(' ') and line.strip():
                current_module = None

    # Parse exports
    in_exp = False
    for line in lines:
        if "Exports list by name" in line:
            in_exp = True
            continue
        if in_exp:
            for m in re.finditer(r'(\w+)\s+([0-9a-fA-F]{6})\s+\w+', line):
                exports[m.group(1)] = int(m.group(2), 16)
            if line.strip() == "":
                break

    return segments, module_offsets, exports


# ── Fixture ──────────────────────────────────────────────────

# BSS layout of debugger.o (order matches .segment "BSS" in debugger.s):
#   _bp_table:     32 bytes (8 slots × 4)
#   _step_bp:       8 bytes (2 step slots × 4, contiguous with bp_table)
#   _dbg_running:   1 byte
#   _dbg_reason:    1 byte
#   _brk_pc:        2 bytes
#   _dbg_bp_hit:    1 byte

_BSS_OFFSETS = {
    '_bp_table':    0,
    '_step_bp':     32,
    '_dbg_running': 40,
    '_dbg_reason':  41,
    '_brk_pc':      42,
    '_dbg_bp_hit':  44,
}


class DbgSymbols:
    def __init__(self):
        if _needs_rebuild():
            _build()
        segments, mod_offs, exports = _parse_map()

        # Entry point: CODE start + stub's CODE offset
        stub_code_offs = mod_offs['debugger_test_stub.o']['CODE']
        self.entry = segments['CODE'] + stub_code_offs

        # BSS symbols: BSS start + debugger.o's BSS offset + field offset
        bss_base = segments['BSS'] + mod_offs['debugger.o']['BSS']
        self.bp_table    = bss_base + _BSS_OFFSETS['_bp_table']
        self.dbg_running = bss_base + _BSS_OFFSETS['_dbg_running']
        self.dbg_reason  = bss_base + _BSS_OFFSETS['_dbg_reason']
        self.brk_pc      = bss_base + _BSS_OFFSETS['_brk_pc']
        self.dbg_bp_hit  = bss_base + _BSS_OFFSETS['_dbg_bp_hit']

        raw = BIN.read_bytes()
        self._zp_blob   = raw[:_ZP_SIZE]
        self._code_blob = raw[_ZP_SIZE:]

    def load_into(self, memory):
        memory[_ZP_START   : _ZP_START   + _ZP_SIZE]              = self._zp_blob
        memory[_CODE_START : _CODE_START + len(self._code_blob)]   = self._code_blob


@pytest.fixture(scope="session")
def dbg_syms():
    return DbgSymbols()


# ── Helpers ──────────────────────────────────────────────────

def make_cpu(dbg_syms):
    mpu = MPU()
    mem = bytearray(0x10000)
    dbg_syms.load_into(mem)
    # Place RTS at return address
    mem[_RETURN] = 0x60
    mpu.memory = mem
    return mpu

def call(mpu, addr):
    """JSR to addr and run until RTS returns to _RETURN."""
    # Push return address - 1 (as JSR does)
    ret = _RETURN - 1
    mpu.sp = 0xFD
    mpu.memory[0x01FE] = ret & 0xFF
    mpu.memory[0x01FF] = (ret >> 8) & 0xFF
    mpu.pc = addr
    cycles = 0
    while cycles < 50000:
        mpu.step()
        cycles += 1
        if mpu.pc == _RETURN:
            return
    raise TimeoutError(f"CPU did not reach ${_RETURN:04X} within 50000 cycles")

def cmd_init(mpu, syms):
    mpu.memory[CMD] = 0x00
    call(mpu, syms.entry)

def cmd_bp_set(mpu, syms, addr_lo, addr_hi):
    mpu.memory[CMD] = 0x01
    mpu.memory[ARG1] = addr_lo
    mpu.memory[ARG2] = addr_hi
    call(mpu, syms.entry)
    flags = mpu.memory[RFLAGS]
    slot = mpu.memory[RVAL]
    return (flags == 0), slot  # (success?, slot#)

def cmd_bp_del(mpu, syms, slot):
    mpu.memory[CMD] = 0x02
    mpu.memory[ARG1] = slot
    call(mpu, syms.entry)
    return mpu.memory[RFLAGS] == 0  # success?

def cmd_bp_clear(mpu, syms):
    mpu.memory[CMD] = 0x03
    call(mpu, syms.entry)

def cmd_bp_count(mpu, syms):
    mpu.memory[CMD] = 0x04
    call(mpu, syms.entry)
    return mpu.memory[RVAL]

def read_bp_slot(mpu, syms, slot):
    """Read a breakpoint slot: (addr_lo, addr_hi, saved, flags)."""
    base = syms.bp_table + slot * BP_SIZE
    return (mpu.memory[base], mpu.memory[base+1],
            mpu.memory[base+2], mpu.memory[base+3])


# ── Tests ────────────────────────────────────────────────────

class TestDbgInit:
    def test_init_clears_table(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        # Dirty the table first
        for i in range(BP_SLOTS * BP_SIZE):
            mpu.memory[dbg_syms.bp_table + i] = 0xFF
        mpu.memory[dbg_syms.dbg_running] = 0x80
        mpu.memory[dbg_syms.dbg_reason] = 0x03
        cmd_init(mpu, dbg_syms)
        # All slots zero
        for i in range(BP_SLOTS * BP_SIZE):
            assert mpu.memory[dbg_syms.bp_table + i] == 0
        assert mpu.memory[dbg_syms.dbg_running] == 0
        assert mpu.memory[dbg_syms.dbg_reason] == 0
        assert mpu.memory[dbg_syms.brk_pc] == 0
        assert mpu.memory[dbg_syms.brk_pc + 1] == 0
        assert mpu.memory[dbg_syms.dbg_bp_hit] == 0xFF


class TestBpSet:
    def test_set_one(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        ok, slot = cmd_bp_set(mpu, dbg_syms, 0x20, 0x10)  # $1020
        assert ok
        assert slot == 0
        lo, hi, saved, flags = read_bp_slot(mpu, dbg_syms, 0)
        assert lo == 0x20
        assert hi == 0x10
        assert saved == 0
        assert flags == 1

    def test_set_fills_sequentially(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        for i in range(BP_SLOTS):
            ok, slot = cmd_bp_set(mpu, dbg_syms, i, 0x10)
            assert ok
            assert slot == i

    def test_set_table_full(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        # Fill all 8 slots
        for i in range(BP_SLOTS):
            ok, _ = cmd_bp_set(mpu, dbg_syms, i + 1, 0x10)
            assert ok
        # 9th should fail
        ok, _ = cmd_bp_set(mpu, dbg_syms, 0xFF, 0x20)
        assert not ok

    def test_set_reuses_deleted_slot(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        # Set slots 0, 1, 2
        cmd_bp_set(mpu, dbg_syms, 0x00, 0x10)
        cmd_bp_set(mpu, dbg_syms, 0x01, 0x10)
        cmd_bp_set(mpu, dbg_syms, 0x02, 0x10)
        # Delete slot 1
        cmd_bp_del(mpu, dbg_syms, 1)
        # Next set should reuse slot 1
        ok, slot = cmd_bp_set(mpu, dbg_syms, 0xFF, 0x20)
        assert ok
        assert slot == 1
        lo, hi, _, _ = read_bp_slot(mpu, dbg_syms, 1)
        assert lo == 0xFF
        assert hi == 0x20


class TestBpDel:
    def test_del_valid(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        cmd_bp_set(mpu, dbg_syms, 0x00, 0x10)
        ok = cmd_bp_del(mpu, dbg_syms, 0)
        assert ok
        lo, hi, saved, flags = read_bp_slot(mpu, dbg_syms, 0)
        assert lo == 0 and hi == 0 and saved == 0 and flags == 0

    def test_del_invalid_slot(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        ok = cmd_bp_del(mpu, dbg_syms, 8)  # out of range
        assert not ok
        ok = cmd_bp_del(mpu, dbg_syms, 255)
        assert not ok


class TestBpClear:
    def test_clear_all(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        # Set several
        for i in range(5):
            cmd_bp_set(mpu, dbg_syms, i + 1, 0x10)
        cmd_bp_clear(mpu, dbg_syms)
        for i in range(BP_SLOTS):
            lo, hi, saved, flags = read_bp_slot(mpu, dbg_syms, i)
            assert lo == 0 and hi == 0 and saved == 0 and flags == 0


class TestBpCount:
    def test_count_empty(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        assert cmd_bp_count(mpu, dbg_syms) == 0

    def test_count_after_set(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        cmd_bp_set(mpu, dbg_syms, 0x00, 0x10)
        cmd_bp_set(mpu, dbg_syms, 0x01, 0x10)
        cmd_bp_set(mpu, dbg_syms, 0x02, 0x10)
        assert cmd_bp_count(mpu, dbg_syms) == 3

    def test_count_after_del(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        cmd_bp_set(mpu, dbg_syms, 0x00, 0x10)
        cmd_bp_set(mpu, dbg_syms, 0x01, 0x10)
        cmd_bp_del(mpu, dbg_syms, 0)
        assert cmd_bp_count(mpu, dbg_syms) == 1

    def test_count_full(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        for i in range(BP_SLOTS):
            cmd_bp_set(mpu, dbg_syms, i + 1, 0x10)
        assert cmd_bp_count(mpu, dbg_syms) == 8

    def test_count_after_clear(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        for i in range(3):
            cmd_bp_set(mpu, dbg_syms, i + 1, 0x10)
        cmd_bp_clear(mpu, dbg_syms)
        assert cmd_bp_count(mpu, dbg_syms) == 0


# ── Phase B helpers ──────────────────────────────────────────

def cmd_bp_patch(mpu, syms):
    mpu.memory[CMD] = 0x05
    call(mpu, syms.entry)

def cmd_bp_unpatch(mpu, syms):
    mpu.memory[CMD] = 0x06
    call(mpu, syms.entry)

def cmd_bp_find(mpu, syms, addr_lo, addr_hi):
    mpu.memory[CMD] = 0x07
    mpu.memory[ARG1] = addr_lo
    mpu.memory[ARG2] = addr_hi
    call(mpu, syms.entry)
    flags = mpu.memory[RFLAGS]
    slot = mpu.memory[RVAL]
    return (flags == 0), slot  # (found?, slot#)


# ── Phase B tests ────────────────────────────────────────────

# Target addresses for patch/unpatch tests — use high memory area
# that doesn't overlap CODE or BSS.  $3000+ is safe.
TARGET1 = 0x3000
TARGET2 = 0x3010
TARGET3 = 0x3020


class TestBpPatch:
    def test_patch_writes_brk(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        # Place known opcodes at target addresses
        mpu.memory[TARGET1] = 0xA9  # LDA #imm
        mpu.memory[TARGET2] = 0x8D  # STA abs
        # Set breakpoints
        cmd_bp_set(mpu, dbg_syms, TARGET1 & 0xFF, TARGET1 >> 8)
        cmd_bp_set(mpu, dbg_syms, TARGET2 & 0xFF, TARGET2 >> 8)
        # Patch
        cmd_bp_patch(mpu, dbg_syms)
        # Targets should now be $00 (BRK)
        assert mpu.memory[TARGET1] == 0x00
        assert mpu.memory[TARGET2] == 0x00
        # Saved bytes should have original opcodes
        _, _, saved1, _ = read_bp_slot(mpu, dbg_syms, 0)
        _, _, saved2, _ = read_bp_slot(mpu, dbg_syms, 1)
        assert saved1 == 0xA9
        assert saved2 == 0x8D

    def test_patch_skips_empty_slots(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        mpu.memory[TARGET1] = 0xA9
        mpu.memory[TARGET2] = 0x8D
        # Only set one breakpoint
        cmd_bp_set(mpu, dbg_syms, TARGET1 & 0xFF, TARGET1 >> 8)
        cmd_bp_patch(mpu, dbg_syms)
        assert mpu.memory[TARGET1] == 0x00  # patched
        assert mpu.memory[TARGET2] == 0x8D  # untouched


class TestBpUnpatch:
    def test_unpatch_restores_originals(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        mpu.memory[TARGET1] = 0xA9
        mpu.memory[TARGET2] = 0x8D
        cmd_bp_set(mpu, dbg_syms, TARGET1 & 0xFF, TARGET1 >> 8)
        cmd_bp_set(mpu, dbg_syms, TARGET2 & 0xFF, TARGET2 >> 8)
        cmd_bp_patch(mpu, dbg_syms)
        # Verify patched
        assert mpu.memory[TARGET1] == 0x00
        assert mpu.memory[TARGET2] == 0x00
        # Unpatch
        cmd_bp_unpatch(mpu, dbg_syms)
        assert mpu.memory[TARGET1] == 0xA9
        assert mpu.memory[TARGET2] == 0x8D

    def test_patch_unpatch_roundtrip(self, dbg_syms):
        """Patch + unpatch is idempotent — memory restored exactly."""
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        # Set up 3 breakpoints with different opcodes
        targets = [TARGET1, TARGET2, TARGET3]
        opcodes = [0xA9, 0x8D, 0x4C]
        for addr, opc in zip(targets, opcodes):
            mpu.memory[addr] = opc
            cmd_bp_set(mpu, dbg_syms, addr & 0xFF, addr >> 8)
        cmd_bp_patch(mpu, dbg_syms)
        cmd_bp_unpatch(mpu, dbg_syms)
        for addr, opc in zip(targets, opcodes):
            assert mpu.memory[addr] == opc


class TestBpFind:
    def test_find_existing(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        cmd_bp_set(mpu, dbg_syms, 0x20, 0x10)  # $1020
        cmd_bp_set(mpu, dbg_syms, 0x50, 0x20)  # $2050
        found, slot = cmd_bp_find(mpu, dbg_syms, 0x50, 0x20)
        assert found
        assert slot == 1

    def test_find_first(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        cmd_bp_set(mpu, dbg_syms, 0x20, 0x10)
        found, slot = cmd_bp_find(mpu, dbg_syms, 0x20, 0x10)
        assert found
        assert slot == 0

    def test_find_not_found(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        cmd_bp_set(mpu, dbg_syms, 0x20, 0x10)
        found, slot = cmd_bp_find(mpu, dbg_syms, 0xFF, 0xFF)
        assert not found
        assert slot == 0xFF

    def test_find_empty_table(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        cmd_init(mpu, dbg_syms)
        found, _ = cmd_bp_find(mpu, dbg_syms, 0x20, 0x10)
        assert not found
