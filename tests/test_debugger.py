"""
test_debugger.py — Debugger breakpoint table contract tests (debugger.s)

Phase A: bp_set, bp_del, bp_clear, bp_count, dbg_init.
Phase B: bp_patch, bp_unpatch, bp_find.

Test binary: debugger.s + debugger_test_stub.s
Protocol: write command byte + args at $0B00, JSR dbg_test_entry.
"""

import subprocess, pathlib, pytest
from py65.devices.mpu6502 import MPU
from conftest import SymbolTable

ROOT  = pathlib.Path(__file__).parent.parent
BUILD = ROOT / "build"
SRC   = ROOT / "src"
DEV   = ROOT / "dev"

BIN = BUILD / "debugger_test.bin"
MAP = BUILD / "debugger_test.map"
LBL = BUILD / "debugger_test.lbl"

_ZP_START   = 0x0000
_CODE_START = 0x4000
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

_SOURCES = [SRC / "zp.s", SRC / "debugger.s", DEV / "debugger_test_stub.s"]

def _needs_rebuild():
    if not BIN.exists() or not LBL.exists(): return True
    t = BIN.stat().st_mtime
    return any(s.stat().st_mtime > t for s in _SOURCES + [DEV / "test.cfg"])

def _build():
    BUILD.mkdir(exist_ok=True)
    objs = []
    for src in _SOURCES:
        obj = BUILD / f"{src.stem}_dbg.o"
        subprocess.run(["ca65", "-g", "--cpu", "6502",
                        str(src), "-o", str(obj)], check=True)
        objs.append(str(obj))
    subprocess.run(["ld65", "-C", str(DEV / "test.cfg"),
                    *objs,
                    "-o", str(BIN), "-m", str(MAP),
                    "-Ln", str(LBL)], check=True)


# ── Fixture ──────────────────────────────────────────────────

class DbgSymbols:
    def __init__(self):
        if _needs_rebuild():
            _build()
        s = SymbolTable(LBL)

        self.entry       = s["dbg_test_entry"]

        # BSS symbols — previously required hardcoded offset dict
        self.bp_table    = s["bp_table"]
        self.step_bp     = s["step_bp"]
        self.dbg_running = s["dbg_running"]
        self.dbg_reason  = s["dbg_reason"]
        self.brk_pc      = s["brk_pc"]
        self.dbg_bp_hit  = s["dbg_bp_hit"]
        self.cse_sp      = s["cse_sp"]

        self.reg_a  = s.get("reg_a")
        self.reg_x  = s.get("reg_x")
        self.reg_y  = s.get("reg_y")
        self.reg_sp = s.get("reg_sp")
        self.reg_p  = s.get("reg_p")

        self.dbg_brk_core = s.get("dbg_brk_core")

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
    # Run dbg_init so the debugger state is in the post-cold-boot
    # shape production code assumes (reg_sp = $FD, sentinel at
    # user_stack_buf[$FE/$FF], etc.).  Tests that want dirtied state
    # can freely overwrite after this.
    cmd_init(mpu, dbg_syms)
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


# ── dbg_enter integration tests ─────────────────────────────────
#
# These exercise the full dbg_enter / dbg_brk_handler round-trip with
# a real py65-executed user program.  py65 has no C64 KERNAL, so we
# install a tiny "KERNAL IRQ entry" stub at $FFE0 that mimics what
# the real KERNAL does on BRK: pushes A/X/Y, then jumps through
# $0316.  The CPU IRQ vector at $FFFE is set to point at this stub.

def cmd_dbg_enter(mpu, syms):
    """Drive command $08 (dbg_enter) through the test stub."""
    mpu.memory[CMD] = 0x08
    call(mpu, syms.entry)


def _install_kernal_brk_stub(mem):
    """Install a minimal KERNAL IRQ entry at $FFE0 and point the
    CPU IRQ vector at it.  The real C64 $FF48 KERNAL entry pushes
    A, X, Y and then dispatches to ($0316) for BRK; we mimic the
    push behaviour and unconditionally jump through $0316 (we only
    use this for BRK in tests, never IRQ)."""
    # PHA / TXA / PHA / TYA / PHA / JMP ($0316)
    for off, b in enumerate([0x48, 0x8A, 0x48, 0x98, 0x48, 0x6C, 0x16, 0x03]):
        mem[0xFFE0 + off] = b
    mem[0xFFFE] = 0xE0
    mem[0xFFFF] = 0xFF


class TestDbgEnterStepIntoJSR:
    """Regression: stepping into a JSR via dbg_enter must NOT execute
    the instruction after the JSR.

    The bug was: dbg_brk_handler did `tsx; txa; clc; adc #6; tax; txs;
    rts` to strip the BRK+KERNAL frame.  But if the user code pushed
    bytes BEFORE the BRK fired (e.g. a JSR pushing its return address),
    those bytes sat below the BRK frame and the rts after strip popped
    them as PC instead of the @tramp return address.

    For a step-into JSR, this meant the rts jumped to "JSR call site
    + 3" — i.e. the instruction after the JSR in user code — instead
    of returning to dbg_enter.  Symptom: t1 over a JSR "hangs" in user
    code, with screen corruption from whatever the runaway code wrote.

    Fix: dbg_brk_handler restores SP from sp_baseline (captured by
    @tramp right after the jsr @tramp's push), so the rts always pops
    the @tramp ret addr regardless of user pushes.
    """

    def test_step_into_jsr_does_not_run_past(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory

        _install_kernal_brk_stub(mem)

        # ── User code ────────────────────────────────────────────────
        # $2000: JSR $2010    ─ JSR pushes 2 bytes
        # $2003: LDA #$AA     ─ runaway sentinel: must NOT execute
        # $2005: STA $0BFE    ─ runaway sentinel: must NOT write
        # $2008: BRK          ─ catch-all if runaway happens
        mem[0x2000] = 0x20; mem[0x2001] = 0x10; mem[0x2002] = 0x20
        mem[0x2003] = 0xA9; mem[0x2004] = 0xAA
        mem[0x2005] = 0x8D; mem[0x2006] = 0xFE; mem[0x2007] = 0x0B
        mem[0x2008] = 0x00

        # Subroutine target — patch_all overwrites with BRK on entry
        mem[0x2010] = 0xEA          # NOP placeholder

        # Sentinel must start clear
        mem[0x0BFE] = 0x00

        # Arm step BP at $2010
        mem[dbg_syms.step_bp + 0] = 0x10
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 2] = 0
        mem[dbg_syms.step_bp + 3] = 1     # enabled

        # brk_pc = $2000 (where dbg_enter will jmp first)
        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20

        # Default user flags (bit 5 always set on real 6502)
        mem[dbg_syms.reg_p] = 0x20

        # $0316/$0317 placeholder (dbg_enter saves+restores)
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        # Drive dbg_enter via the stub.  If the bug is present, this
        # call will appear to "succeed" (returns) but the runaway
        # sentinel byte will be set, indicating the BRK handler rts'd
        # through the JSR's pushed return address.
        cmd_dbg_enter(mpu, dbg_syms)

        # 1. Sanity: dbg_enter actually returned.  (call() raises
        #    TimeoutError if we never reach _RETURN.)
        # 2. dbg_reason should be DBG_BRK = 1 (the step BP fired).
        assert mem[dbg_syms.dbg_reason] == 1, \
            f"dbg_reason should be 1 (BRK), got {mem[dbg_syms.dbg_reason]}"

        # 3. brk_pc should be $2010 (the step BP target, where BRK
        #    actually fired).  In the buggy code, brk_pc would still
        #    be $2010 too (the BRK handler captured it correctly), so
        #    this alone doesn't catch the bug.
        brk_pc = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert brk_pc == 0x2010, f"brk_pc should be $2010, got ${brk_pc:04X}"

        # 4. The KEY assertion: the runaway sentinel must remain 0.
        #    With the bug, the BRK handler's strip+rts would pop the
        #    JSR's pushed return address ($2002), rts'ing to $2003,
        #    where LDA #$AA / STA $0BFE would execute and clobber
        #    the sentinel.  With the fix, the BRK handler restores
        #    SP from sp_baseline, so its rts pops the @tramp ret
        #    addr instead, returning directly to dbg_enter and never
        #    touching $0BFE.
        assert mem[0x0BFE] == 0x00, (
            f"BRK handler returned to user code after JSR — sentinel "
            f"$0BFE = ${mem[0x0BFE]:02X} (should be $00).  This is "
            f"the t1-hangs-on-JSR bug."
        )

        # 5. dbg_running should be cleared on return.
        assert mem[dbg_syms.dbg_running] == 0, \
            f"dbg_running not cleared: ${mem[dbg_syms.dbg_running]:02X}"

    def test_dbg_enter_no_user_pushes(self, dbg_syms):
        """Sanity: a simple BRK at brk_pc with no user JSR also works.
        Verifies the fix didn't break the no-user-pushes path."""
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory

        _install_kernal_brk_stub(mem)

        # User code: just BRK at $2000.  No JSR, no user pushes.
        mem[0x2000] = 0xEA          # NOP placeholder, will be patched

        mem[dbg_syms.step_bp + 0] = 0x00
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 2] = 0
        mem[dbg_syms.step_bp + 3] = 1

        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        mem[dbg_syms.reg_p] = 0x20
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        cmd_dbg_enter(mpu, dbg_syms)

        assert mem[dbg_syms.dbg_reason] == 1
        brk_pc = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert brk_pc == 0x2000
        assert mem[dbg_syms.dbg_running] == 0

    def test_repeated_dbg_enter_into_jsr(self, dbg_syms):
        """Mirror the user's `t1 t1 t1 ...` sequence over a JSR.

        Each iteration: arm a step BP at the *next* user PC, call
        dbg_enter, verify it returned cleanly with brk_pc updated.
        Iteration 2 is the JSR step — the one that used to hang.
        """
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        # User program:
        #   $2000: NOP             (step 1 advances past this)
        #   $2001: JSR $2010       (step 2 — the JSR step)
        #   $2004: NOP             (we should land here after step 3)
        #   $2005: BRK             (catch-all if runaway happens)
        #
        #   $2010: NOP             (subroutine first instruction;
        #                            patched to BRK by step 2's patch_all)
        #   $2011: RTS
        mem[0x2000] = 0xEA                                              # NOP
        mem[0x2001] = 0x20; mem[0x2002] = 0x10; mem[0x2003] = 0x20      # JSR $2010
        mem[0x2004] = 0xEA                                              # NOP
        mem[0x2005] = 0x00                                              # BRK
        mem[0x2010] = 0xEA                                              # subroutine first
        mem[0x2011] = 0x60                                              # RTS

        mem[dbg_syms.reg_p] = 0x20
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        # ── Step 1: brk_pc=$2000 (NOP), next=$2001 ──
        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        mem[dbg_syms.step_bp + 0] = 0x01
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 2] = 0
        mem[dbg_syms.step_bp + 3] = 1
        cmd_dbg_enter(mpu, dbg_syms)
        assert mem[dbg_syms.dbg_reason] == 1, "step 1: BRK"
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert bp == 0x2001, f"step 1: brk_pc=${bp:04X} (want $2001)"

        # ── Step 2: brk_pc=$2001 (JSR $2010), next=$2010 (step into) ──
        mem[dbg_syms.brk_pc + 0] = 0x01
        mem[dbg_syms.brk_pc + 1] = 0x20
        mem[dbg_syms.step_bp + 0] = 0x10
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 2] = 0
        mem[dbg_syms.step_bp + 3] = 1
        cmd_dbg_enter(mpu, dbg_syms)
        assert mem[dbg_syms.dbg_reason] == 1, "step 2: BRK after JSR"
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert bp == 0x2010, f"step 2: brk_pc=${bp:04X} (want $2010, JSR target)"

        # ── Step 3: brk_pc=$2010 (NOP in subroutine), next=$2011 (RTS) ──
        # If the bug somehow made us think the user code "completed" at
        # the wrong time, this step would either re-fire at $2010 or
        # land somewhere outside the user program.
        mem[dbg_syms.brk_pc + 0] = 0x10
        mem[dbg_syms.brk_pc + 1] = 0x20
        mem[dbg_syms.step_bp + 0] = 0x11
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 2] = 0
        mem[dbg_syms.step_bp + 3] = 1
        cmd_dbg_enter(mpu, dbg_syms)
        assert mem[dbg_syms.dbg_reason] == 1, "step 3: BRK at subroutine NOP+1"
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert bp == 0x2011, f"step 3: brk_pc=${bp:04X} (want $2011, RTS)"


class TestMultiStepInfiniteLoop:
    """Regression: user reports `t1` works repeatedly but `t` (multi-step
    with block_size = 16) ends with a BRK at a seemingly random address.
    Reproduces the exact scenario they described:

        $080e: inc $d020
        $0811: inc $d021
        $0814: jmp $080e
    """

    def test_t16_over_inc_inc_jmp_loop(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        # User's infinite-loop program
        mem[0x080e] = 0xEE; mem[0x080f] = 0x20; mem[0x0810] = 0xD0  # inc $d020
        mem[0x0811] = 0xEE; mem[0x0812] = 0x21; mem[0x0813] = 0xD0  # inc $d021
        mem[0x0814] = 0x4C; mem[0x0815] = 0x0e; mem[0x0816] = 0x08  # jmp $080e

        mem[dbg_syms.reg_p] = 0x00
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        # Arm step-into sequence: first BRK at $0811 (next-PC after $080e's
        # 3-byte INC).  This mimics cmd_step iteration 1.
        mem[dbg_syms.brk_pc + 0] = 0x0e
        mem[dbg_syms.brk_pc + 1] = 0x08
        mem[dbg_syms.step_bp + 0] = 0x11
        mem[dbg_syms.step_bp + 1] = 0x08
        mem[dbg_syms.step_bp + 3] = 1

        # Perform 16 iterations of { arm next-PC, cmd_dbg_enter, check brk_pc }
        expected_cycle = [0x0811, 0x0814, 0x080e]  # post-step PCs
        targets = [0x0811, 0x0814, 0x080e]          # next-PC for each iter
        for i in range(16):
            cmd_dbg_enter(mpu, dbg_syms)
            assert mem[dbg_syms.dbg_reason] == 1, \
                f"iter {i+1}: dbg_reason should be 1 (BRK), got {mem[dbg_syms.dbg_reason]}"
            bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
            expected_pc = expected_cycle[i % 3]
            assert bp == expected_pc, \
                f"iter {i+1}: brk_pc=${bp:04X} (want ${expected_pc:04X}). " \
                f"Multi-step round-trip is corrupting state."
            # Arm next iter's step_bp (cmd_step does this before each run)
            for j in range(8): mem[dbg_syms.step_bp + j] = 0
            next_target = targets[(i + 1) % 3]
            mem[dbg_syms.step_bp + 0] = next_target & 0xFF
            mem[dbg_syms.step_bp + 1] = next_target >> 8
            mem[dbg_syms.step_bp + 3] = 1


class TestContinueAfterStepIntoJSR:
    """Regression: step into a JSR, then continue — the subroutine's
    RTS must pop the user's own JSR-pushed return address and resume
    at `JSR + 3`, not garbage from CSE's own stack activity.

    This is the canonical bug that the two-image stack swap
    (user_stack_buf / cse_stack_buf) fixes.  Before the swap, the
    txs sp_baseline / rts exit from dbg_brk_core erased the user's
    $1002 pushed return address as it collapsed the KERNAL/hw
    frame; continuing meant the sub's RTS popped unrelated bytes.
    With the swap, user's stack page is saved on every exit and
    restored on every entry, so the JSR return slot survives.
    """

    def test_continue_resumes_at_jsr_return(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        # User program:
        #   $2000: JSR $2100   ; user pushes $2002 onto user's stack
        #   $2003: BRK         ; ← where sub's RTS should land us
        #   $2100: NOP         ; ← step_bp planted here
        #   $2101: NOP
        #   $2102: RTS         ; pops user's $2002, resumes at $2003
        mem[0x2000] = 0x20; mem[0x2001] = 0x00; mem[0x2002] = 0x21
        mem[0x2003] = 0x00
        mem[0x2100] = 0xEA
        mem[0x2101] = 0xEA
        mem[0x2102] = 0x60

        mem[dbg_syms.reg_p] = 0x20
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        # ── Step 1: step into the JSR → breaks at $2100 ──
        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        mem[dbg_syms.step_bp + 0] = 0x00   # step BP at $2100 (sub entry)
        mem[dbg_syms.step_bp + 1] = 0x21
        mem[dbg_syms.step_bp + 3] = 1
        cmd_dbg_enter(mpu, dbg_syms)
        assert mem[dbg_syms.dbg_reason] == 1, "step 1: BRK expected"
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert bp == 0x2100, f"step 1: brk_pc=${bp:04X} (want $2100)"

        # ── Step 2: continue, no step_bp — sub must RTS to $2003 ──
        for i in range(8): mem[dbg_syms.step_bp + i] = 0
        cmd_dbg_enter(mpu, dbg_syms)
        assert mem[dbg_syms.dbg_reason] == 1, "continue: BRK expected"
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert bp == 0x2003, (
            f"continue: brk_pc=${bp:04X} (want $2003). "
            f"Sub's RTS didn't land at JSR+3 — the user-stack "
            f"preservation across the swap boundary has regressed."
        )


class TestDbgEnterBranchStep:
    """Verify that stepping over a taken branch follows the branch.

    User code:
      $2000: LDX #$03         ; X=3, Z=0
      $2002: DEX               ; X=2, Z=0
      $2003: BNE $2002         ; taken → back to DEX

    Step sequence:
      1. brk_pc=$2000, step BP at $2002 (LDX is 2 bytes)
         → BRK at $2002, brk_pc=$2002
      2. brk_pc=$2002, step BP at $2003 (DEX is 1 byte)
         → BRK at $2003, brk_pc=$2003
      3. brk_pc=$2003, step BPs at $2002 (taken) and $2005 (fall-through)
         → BNE should be taken (Z=0 from DEX), brk_pc=$2002

    The bug: brk_pc ends up at $2005 (fall-through) instead of $2002.
    """

    def test_taken_branch_follows_target(self, dbg_syms):
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        # User code
        mem[0x2000] = 0xA2; mem[0x2001] = 0x03  # LDX #$03
        mem[0x2002] = 0xCA                        # DEX
        mem[0x2003] = 0xD0; mem[0x2004] = 0xFD   # BNE $2002
        mem[0x2005] = 0x00                        # BRK (fall-through sentinel)

        mem[dbg_syms.reg_p] = 0x20
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        # ── Step 1: LDX #$03 → advance to $2002 ──
        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        mem[dbg_syms.step_bp + 0] = 0x02  # target: $2002
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 2] = 0
        mem[dbg_syms.step_bp + 3] = 1
        cmd_dbg_enter(mpu, dbg_syms)
        assert mem[dbg_syms.dbg_reason] == 1
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert bp == 0x2002, f"step 1: brk_pc=${bp:04X} (want $2002)"

        # ── Step 2: DEX → advance to $2003 ──
        mem[dbg_syms.step_bp + 0] = 0x03
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 2] = 0
        mem[dbg_syms.step_bp + 3] = 1
        # Clear second step slot
        mem[dbg_syms.step_bp + 4] = 0
        mem[dbg_syms.step_bp + 5] = 0
        mem[dbg_syms.step_bp + 6] = 0
        mem[dbg_syms.step_bp + 7] = 0
        cmd_dbg_enter(mpu, dbg_syms)
        assert mem[dbg_syms.dbg_reason] == 1
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert bp == 0x2003, f"step 2: brk_pc=${bp:04X} (want $2003)"
        # reg_p should have Z=0 (X went from 3 to 2, not zero)
        p = mem[dbg_syms.reg_p]
        assert (p & 0x02) == 0, f"step 2: Z should be 0 (X=2), reg_p=${p:02X}"

        # ── Step 3: BNE $2002 — should take the branch (Z=0) ──
        # Arm both targets: taken=$2002, fall-through=$2005
        mem[dbg_syms.step_bp + 0] = 0x02  # taken target
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 2] = 0
        mem[dbg_syms.step_bp + 3] = 1
        mem[dbg_syms.step_bp + 4] = 0x05  # fall-through
        mem[dbg_syms.step_bp + 5] = 0x20
        mem[dbg_syms.step_bp + 6] = 0
        mem[dbg_syms.step_bp + 7] = 1
        cmd_dbg_enter(mpu, dbg_syms)
        assert mem[dbg_syms.dbg_reason] == 1
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc + 1] << 8)
        assert bp == 0x2002, (
            f"step 3: BNE should be TAKEN (Z=0), brk_pc=${bp:04X} "
            f"(want $2002, got fall-through $2005 if Z wrong)"
        )

    def test_branch_step_mimics_cmd_step(self, dbg_syms):
        """Mimic the exact cmd_step flow: three separate dbg_enter
        calls with step_bp re-arm between them.  Each call is
        independent (ZP saved/restored, patches applied/removed).

        User program at $2000:
          LDX #$05     ; 2 bytes
          DEX          ; 1 byte
          BNE $2002    ; 2 bytes (offset $FD = -3)
          RTS          ; 1 byte

        Step 1: brk_pc=$2000, step at $2002 → LDX, brk at $2002
        Step 2: brk_pc=$2002, step at $2003 → DEX (X:5→4), brk at $2003
        Step 3: brk_pc=$2003, step at $2002+$2005 → BNE, should brk at $2002
        """
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        mem[0x2000] = 0xA2; mem[0x2001] = 0x05  # LDX #$05
        mem[0x2002] = 0xCA                        # DEX
        mem[0x2003] = 0xD0; mem[0x2004] = 0xFD   # BNE $2002
        mem[0x2005] = 0x60                        # RTS

        mem[dbg_syms.reg_a] = 0
        mem[dbg_syms.reg_x] = 0
        mem[dbg_syms.reg_y] = 0
        mem[dbg_syms.reg_p] = 0x20
        mem[dbg_syms.reg_sp] = 0xFF
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        # ── Step 1: LDX #$05 ──
        mem[dbg_syms.brk_pc] = 0x00; mem[dbg_syms.brk_pc+1] = 0x20
        # Clear and arm step_bp
        for i in range(8): mem[dbg_syms.step_bp + i] = 0
        mem[dbg_syms.step_bp + 0] = 0x02  # target $2002
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 3] = 1     # enabled
        cmd_dbg_enter(mpu, dbg_syms)
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc+1] << 8)
        assert bp == 0x2002, f"step 1: ${bp:04X}"
        assert mem[dbg_syms.reg_x] == 5

        # ── Step 2: DEX ──
        for i in range(8): mem[dbg_syms.step_bp + i] = 0
        mem[dbg_syms.step_bp + 0] = 0x03
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 3] = 1
        cmd_dbg_enter(mpu, dbg_syms)
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc+1] << 8)
        assert bp == 0x2003, f"step 2: ${bp:04X}"
        assert mem[dbg_syms.reg_x] == 4
        p = mem[dbg_syms.reg_p]
        assert (p & 0x02) == 0, f"Z should be 0, reg_p=${p:02X}"

        # ── Step 3: BNE — should take branch to $2002 ──
        for i in range(8): mem[dbg_syms.step_bp + i] = 0
        mem[dbg_syms.step_bp + 0] = 0x02  # taken
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 3] = 1
        mem[dbg_syms.step_bp + 4] = 0x05  # fall-through
        mem[dbg_syms.step_bp + 5] = 0x20
        mem[dbg_syms.step_bp + 7] = 1
        cmd_dbg_enter(mpu, dbg_syms)
        bp = mem[dbg_syms.brk_pc] | (mem[dbg_syms.brk_pc+1] << 8)
        x_val = mem[dbg_syms.reg_x]
        assert bp == 0x2002, (
            f"step 3: BNE should stop at $2002 (taken), got ${bp:04X}. "
            f"X={x_val} (4=one BNE, 0=loop ran to completion)"
        )


class TestDbgEnterCleanRtsFlags:
    """Regression: on the clean-RTS return path, dbg_enter must capture
    the user's P flags exactly as they were at RTS time — not flags
    clobbered by dbg_enter's own bookkeeping (e.g. `lda dbg_reason`).

    The original bug: dbg_enter's post-@tramp capture block did
    `pha / lda dbg_reason / bne … / pla / sta reg_a / stx reg_x /
     sty reg_y / php / pla / sta reg_p`.  The `lda dbg_reason`
    and `pla` instructions set N/Z from their operands, so the
    `php` many instructions later captured whatever the last flag-
    touching insn had left — never the user's actual flags.

    The fix: PHP must be the VERY FIRST instruction after control
    returns from userland, before anything else can disturb N/V/Z/C.

    Additionally, PHP unconditionally sets P bit 4 (B) on the pushed
    byte — that's a hardware quirk of the software-push path, not
    a real user flag.  The clean-RTS capture must mask B=0 before
    storing into reg_p so the userland state backup doesn't carry
    a phantom "you're in a BRK break" signal.  (BRK / NMI handlers
    capture P from the hardware-pushed frame and preserve the real
    B bit — tested separately below.)
    """

    def test_lda_zero_rts_captures_Z_set(self, dbg_syms):
        """User code `LDA #$00 / RTS` → reg_p has Z=1, B=0 (no BRK)."""
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        # User code — no step BP, no regular BP → clean RTS path.
        mem[0x2000] = 0xA9; mem[0x2001] = 0x00   # LDA #$00
        mem[0x2002] = 0x60                         # RTS

        # Pre-seed reg_p with B=1 (0x30) so we can prove the clean-RTS
        # path STRIPS the phantom B left by PHP — no BRK happened.
        mem[dbg_syms.reg_p]  = 0x30              # bit 5 + B, Z=0
        mem[dbg_syms.reg_a]  = 0xFF              # non-zero sentinel
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        # No step_bp armed → clean RTS path (dbg_reason stays 0)
        for i in range(8): mem[dbg_syms.step_bp + i] = 0

        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        cmd_dbg_enter(mpu, dbg_syms)

        # Clean RTS — dbg_reason must stay 0
        assert mem[dbg_syms.dbg_reason] == 0, "clean-RTS: dbg_reason should be 0"
        # A must be captured as 0
        assert mem[dbg_syms.reg_a] == 0x00, \
            f"reg_a=${mem[dbg_syms.reg_a]:02X} (want $00)"
        # Z flag (P bit 1) must be 1
        p = mem[dbg_syms.reg_p]
        assert (p & 0x02) == 0x02, \
            f"reg_p=${p:02X}: Z bit should be 1 after LDA #0"
        # Bits 5, 4 must both be 0 — clean-RTS capture strips the
        # PHP transport artefact (bit 5 always 1, bit 4 always 1).
        assert (p & 0x30) == 0x00, \
            f"reg_p=${p:02X}: bits 5,4 must be 0 on clean RTS"

    def test_lda_one_rts_captures_Z_clear(self, dbg_syms):
        """User code `LDA #$01 / RTS` must leave reg_p with Z=0."""
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        mem[0x2000] = 0xA9; mem[0x2001] = 0x01   # LDA #$01
        mem[0x2002] = 0x60                         # RTS

        # Start with reg_p Z=1 so we'd detect mis-capture.
        mem[dbg_syms.reg_p]  = 0x22              # bit 5 + Z set
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        for i in range(8): mem[dbg_syms.step_bp + i] = 0
        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        cmd_dbg_enter(mpu, dbg_syms)

        assert mem[dbg_syms.dbg_reason] == 0
        assert mem[dbg_syms.reg_a] == 0x01
        p = mem[dbg_syms.reg_p]
        assert (p & 0x02) == 0x00, \
            f"reg_p=${p:02X}: Z bit should be 0 after LDA #1"

    def test_brk_path_preserves_B_bit(self, dbg_syms):
        """BRK hardware-pushed P has B=1; reg_p must keep it.

        The B bit in reg_p is user-visible state when the stop is a
        BRK: it's the hardware signal that this was a BRK event, not
        a clean RTS.  The clean-RTS PHP-mask must not leak into the
        BRK capture path."""
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        # Step BP at $2001 forces a BRK at that address.
        mem[0x2000] = 0xEA                         # NOP
        mem[0x2001] = 0xEA                         # NOP (patched → BRK)

        mem[dbg_syms.reg_p]  = 0x20              # B=0 before
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        for i in range(8): mem[dbg_syms.step_bp + i] = 0
        mem[dbg_syms.step_bp + 0] = 0x01
        mem[dbg_syms.step_bp + 1] = 0x20
        mem[dbg_syms.step_bp + 3] = 1

        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        cmd_dbg_enter(mpu, dbg_syms)

        assert mem[dbg_syms.dbg_reason] == 1, "step BRK fired"
        p = mem[dbg_syms.reg_p]
        assert (p & 0x10) == 0x10, \
            f"reg_p=${p:02X}: BRK must leave B=1 in reg_p"
        # Bit 5 (hardware "unused=1") must be stripped — it's not
        # semantic status and we store the byte as a clean flag view.
        assert (p & 0x20) == 0x00, \
            f"reg_p=${p:02X}: bit 5 must be 0 after BRK capture"

    def test_j_into_raw_brk_keeps_B_bit(self, dbg_syms):
        """`j $2000` into a naked BRK opcode — the stock user-visible
        scenario from running `0800:j` on a zeroed workspace.  The
        user should see `nv-Bdizc` in the flag display, i.e. B=1."""
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        mem[0x2000] = 0x00                         # raw BRK instruction

        mem[dbg_syms.reg_p]  = 0x20
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        for i in range(8): mem[dbg_syms.step_bp + i] = 0
        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        cmd_dbg_enter(mpu, dbg_syms)

        assert mem[dbg_syms.dbg_reason] == 1
        p = mem[dbg_syms.reg_p]
        assert (p & 0x10) == 0x10, \
            f"reg_p=${p:02X}: naked BRK must leave B=1 in reg_p"
        assert (p & 0x20) == 0x00, \
            f"reg_p=${p:02X}: bit 5 must be 0 after BRK capture"

    def test_carry_set_preserved_through_rts(self, dbg_syms):
        """`SEC / LDA #$00 / RTS` must leave reg_p with Z=1 and C=1.

        This is the subtle case where N/Z are determined by the A value
        but C is determined by an EARLIER instruction.  A flag capture
        that relies on PLA-setting-Z (as the buggy code accidentally
        did for the `lda #0` case) would get Z right but drop C,
        because the intervening PHA/LDA/PLA sequence clobbers C as
        part of its side-effects.
        """
        mpu = make_cpu(dbg_syms)
        mem = mpu.memory
        _install_kernal_brk_stub(mem)

        mem[0x2000] = 0x38                         # SEC
        mem[0x2001] = 0xA9; mem[0x2002] = 0x00    # LDA #$00
        mem[0x2003] = 0x60                         # RTS

        mem[dbg_syms.reg_p]  = 0x20              # C=0, Z=0
        mem[0x0316] = dbg_syms.dbg_brk_core & 0xFF
        mem[0x0317] = dbg_syms.dbg_brk_core >> 8

        for i in range(8): mem[dbg_syms.step_bp + i] = 0
        mem[dbg_syms.brk_pc + 0] = 0x00
        mem[dbg_syms.brk_pc + 1] = 0x20
        cmd_dbg_enter(mpu, dbg_syms)

        assert mem[dbg_syms.dbg_reason] == 0
        p = mem[dbg_syms.reg_p]
        assert (p & 0x02) == 0x02, f"reg_p=${p:02X}: Z should be 1"
        assert (p & 0x01) == 0x01, f"reg_p=${p:02X}: C should be 1"
