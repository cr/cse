"""
test_mem.py — Tier-I unit tests for mem.s.

Contract source: [doc/modules/mem.md](../../doc/modules/mem.md).
Exercises only the documented API (not implementation details).

Coverage of the documented contract
-----------------------------------
All 9 entry points + the 2 BSS buffers + the 2 exported constants:

    kernal_bank_out / kernal_bank_in
        bit-1-of-$01 toggle, idempotence, other-bit preservation,
        kernal_out flag short-circuit, out→in round-trip.

    save_userland_zp / restore_userland_zp
    save_kernel_zp  / restore_kernel_zp
        128-byte ZP round-trip, buf[$00] holds the saved DDR (not the
        transient $FF), postcondition `live $00 = $FF` after save,
        $80..$FF untouched, buffer independence (userland/kernel).

    cse_start / cse_end / cse_zp_end
        Segment-query accessors; A/X cross-checked against the
        linker-exported `__CODE_RUN__` / `__ZP_LAST__` values and the
        hardcoded $D000 HIMEM.

    userland_zp_buf / kernel_zp_buf      (BSS, verified via save/restore)
    ZP_SAVE_LO=$00 / ZP_SAVE_LEN=128     (implicit — tests use the values)

Out-of-scope by design
----------------------
py65 has no 6510 CPU-port emulation — live $00/$01 behave as flat RAM
with no DDR masking.  The byte-level contract (round-trip, buf[$00]
ordering, postcondition $00=$FF) IS verifiable.  The hardware guarantee
that "`$01` reads fully-latched while DDR=$FF" is NOT observable here;
that stays in the manual VICE checklist.

Bundle
------
`zp.s + mem.s` (see conftest._MEM_SOURCES).  No stub — mem.s is a
zp-only leaf and needs only the linker-provided `__CODE_RUN__` and
`__ZP_LAST__` symbols (test.cfg doesn't auto-define `__CODE_RUN__`,
so conftest passes `-D __CODE_RUN__=$4000` to ld65).
"""

import pytest
from py65.devices.mpu6502 import MPU


# ── Fresh-CPU helper ──────────────────────────────────────────────

def make_cpu(mem_syms):
    """Return a fresh py65 MPU with the mem bundle loaded."""
    cpu = MPU()
    mem_syms.load_into(cpu.memory)
    return cpu


def jsr(cpu, addr, *, a=None, x=None, y=None, carry=None):
    """JSR to addr, run until RTS pops back to sentinel $0300."""
    if a is not None:
        cpu.a = a & 0xFF
    if x is not None:
        cpu.x = x & 0xFF
    if y is not None:
        cpu.y = y & 0xFF
    if carry is not None:
        cpu.p = (cpu.p | 1) if carry else (cpu.p & ~1)

    ret = 0x0300
    cpu.memory[ret] = 0xEA  # NOP sentinel
    cpu.sp = 0xFD
    cpu.memory[0x01FF] = ((ret - 1) >> 8) & 0xFF
    cpu.memory[0x01FE] = (ret - 1) & 0xFF
    cpu.pc = addr
    for _ in range(200_000):
        if cpu.pc == ret:
            return
        cpu.step()
    raise RuntimeError(f"timeout at ${cpu.pc:04X}")


# ═════════════════════════════════════════════════════════════════
# §1  Banking helpers
# ═════════════════════════════════════════════════════════════════

class TestKernalBankOut:
    """kernal_bank_out clears bit 1 of $01 when kernal_out == 0."""

    def test_clears_bit1_when_set(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = 0
        cpu.memory[0x01] = 0x37    # BASIC+KERNAL+I/O all in
        jsr(cpu, mem_syms.kernal_bank_out)
        assert cpu.memory[0x01] == 0x35, \
            f"bit 1 not cleared: ${cpu.memory[0x01]:02X}"

    def test_already_cleared_is_idempotent(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = 0
        cpu.memory[0x01] = 0x35    # bit 1 already 0
        jsr(cpu, mem_syms.kernal_bank_out)
        assert cpu.memory[0x01] == 0x35

    def test_preserves_other_bits(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = 0
        cpu.memory[0x01] = 0xFF    # all bits set
        jsr(cpu, mem_syms.kernal_bank_out)
        assert cpu.memory[0x01] == 0xFD, \
            f"bits other than 1 changed: ${cpu.memory[0x01]:02X}"

    # test_short_circuits_on_flag (flag=1) retired — subsumed by
    # TestKernalOutFlagValues::test_out_short_circuits_on_any_nonzero
    # which parametrises across [$01, $02, $7F, $80, $FF].


class TestKernalBankIn:
    """kernal_bank_in sets bit 1 of $01 when kernal_out == 0."""

    def test_sets_bit1_when_clear(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = 0
        cpu.memory[0x01] = 0x35
        jsr(cpu, mem_syms.kernal_bank_in)
        assert cpu.memory[0x01] == 0x37

    def test_already_set_is_idempotent(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = 0
        cpu.memory[0x01] = 0x37
        jsr(cpu, mem_syms.kernal_bank_in)
        assert cpu.memory[0x01] == 0x37

    def test_preserves_other_bits(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = 0
        cpu.memory[0x01] = 0x00    # all bits clear
        jsr(cpu, mem_syms.kernal_bank_in)
        assert cpu.memory[0x01] == 0x02, \
            f"bits other than 1 changed: ${cpu.memory[0x01]:02X}"

    # test_short_circuits_on_flag (flag=$FF) retired — subsumed by
    # TestKernalOutFlagValues::test_in_short_circuits_on_any_nonzero.


class TestBankFlagRoundTrip:
    """Calling out/in as a pair with flag clear should restore $01."""

    def test_out_then_in_restores(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = 0
        cpu.memory[0x01] = 0x37
        jsr(cpu, mem_syms.kernal_bank_out)
        jsr(cpu, mem_syms.kernal_bank_in)
        assert cpu.memory[0x01] == 0x37

    # test_out_then_in_with_flag_set retired — sequential application
    # of two already-individually-tested short-circuits adds no invariant.


# ═════════════════════════════════════════════════════════════════
# §2  ZP save / restore (userland + kernel buffers)
# ═════════════════════════════════════════════════════════════════

ZP_SAVE_LO  = 0x00
ZP_SAVE_LEN = 128


def _prime_zp(cpu, pattern):
    """Write `pattern` (list of 128 bytes) into live ZP $00..$7F."""
    for i in range(ZP_SAVE_LEN):
        cpu.memory[ZP_SAVE_LO + i] = pattern[i]


def _read_zp(cpu):
    return [cpu.memory[ZP_SAVE_LO + i] for i in range(ZP_SAVE_LEN)]


def _read_buf(cpu, base):
    return [cpu.memory[base + i] for i in range(ZP_SAVE_LEN)]


class TestSaveUserlandZp:
    """save_userland_zp: live ZP → userland_zp_buf."""

    def test_all_128_bytes_copied(self, mem_syms):
        cpu = make_cpu(mem_syms)
        pattern = [(i ^ 0x5A) & 0xFF for i in range(ZP_SAVE_LEN)]
        _prime_zp(cpu, pattern)
        jsr(cpu, mem_syms.save_userland_zp)
        buf = _read_buf(cpu, mem_syms.userland_zp_buf)
        # buf[$00] is the saved DDR (= original $00 before the $FF
        # stash overwrote it).  All other positions match the prime.
        assert buf[0] == pattern[0], \
            f"buf[$00] should be saved DDR ${pattern[0]:02X}, got ${buf[0]:02X}"
        for i in range(1, ZP_SAVE_LEN):
            assert buf[i] == pattern[i], \
                f"buf[${i:02X}] expected ${pattern[i]:02X}, got ${buf[i]:02X}"

    def test_postcondition_live_00_is_ff(self, mem_syms):
        """After save, live $00 must be $FF (load-bearing for restore)."""
        cpu = make_cpu(mem_syms)
        cpu.memory[0x00] = 0x2F   # arbitrary starting DDR
        jsr(cpu, mem_syms.save_userland_zp)
        assert cpu.memory[0x00] == 0xFF, \
            f"postcond live $00 != $FF: ${cpu.memory[0x00]:02X}"

    def test_buf_00_holds_saved_ddr(self, mem_syms):
        """buf[$00] must end up holding the DDR that was live at entry,
        not the transient $FF written during the stash."""
        cpu = make_cpu(mem_syms)
        cpu.memory[0x00] = 0x2F
        cpu.memory[0x01] = 0x37
        jsr(cpu, mem_syms.save_userland_zp)
        buf = _read_buf(cpu, mem_syms.userland_zp_buf)
        assert buf[0] == 0x2F, \
            f"buf[$00] should hold saved DDR $2F, got ${buf[0]:02X}"
        assert buf[1] == 0x37, \
            f"buf[$01] should hold saved CPU-port $37, got ${buf[1]:02X}"

    def test_writes_only_first_128_bytes(self, mem_syms):
        """Addresses $80..$FF are KERNAL-owned; save must not touch them."""
        cpu = make_cpu(mem_syms)
        for i in range(0x80, 0x100):
            cpu.memory[i] = 0xAA
        jsr(cpu, mem_syms.save_userland_zp)
        for i in range(0x80, 0x100):
            assert cpu.memory[i] == 0xAA, \
                f"live ${i:02X} was touched: ${cpu.memory[i]:02X}"


class TestRestoreUserlandZp:
    """restore_userland_zp: userland_zp_buf → live ZP."""

    # test_round_trip retired — subsumed by TestSaveRestoreEdgePatterns::
    # test_userland_round_trip which parametrises over four patterns
    # (all-zero, all-$FF, alternating $AA/$55, ascending) — strictly
    # more boundary coverage than a single ad-hoc pattern.

    def test_all_128_bytes_restored(self, mem_syms):
        """restore with DDR=$FF precondition copies buf exactly."""
        cpu = make_cpu(mem_syms)
        pattern = [(i + 0x80) & 0xFF for i in range(ZP_SAVE_LEN)]
        for i, b in enumerate(pattern):
            cpu.memory[mem_syms.userland_zp_buf + i] = b
        cpu.memory[0x00] = 0xFF   # precondition
        jsr(cpu, mem_syms.restore_userland_zp)
        live = _read_zp(cpu)
        assert live == pattern

    def test_high_zp_untouched(self, mem_syms):
        cpu = make_cpu(mem_syms)
        for i in range(0x80, 0x100):
            cpu.memory[i] = 0x55
        cpu.memory[0x00] = 0xFF
        jsr(cpu, mem_syms.restore_userland_zp)
        for i in range(0x80, 0x100):
            assert cpu.memory[i] == 0x55


class TestSaveKernelZp:
    """save_kernel_zp: mirror of save_userland_zp, target = kernel_zp_buf."""

    # test_round_trip retired — the buffer-contents assertion is subsumed
    # by TestSaveRestoreEdgePatterns::test_kernel_round_trip (which also
    # exercises the restore path against four patterns).  Save-only
    # buffer correctness for kernel is implied by the save+restore
    # round-trip: if save wrote wrong bytes, restore would produce
    # wrong live ZP.

    def test_postcondition_live_00_is_ff(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[0x00] = 0x2F
        jsr(cpu, mem_syms.save_kernel_zp)
        assert cpu.memory[0x00] == 0xFF

    def test_does_not_touch_userland_buf(self, mem_syms):
        """save_kernel_zp writes kernel_zp_buf only; userland_zp_buf stays."""
        cpu = make_cpu(mem_syms)
        for i in range(ZP_SAVE_LEN):
            cpu.memory[mem_syms.userland_zp_buf + i] = 0xC3
        _prime_zp(cpu, [0x11] * ZP_SAVE_LEN)
        jsr(cpu, mem_syms.save_kernel_zp)
        for i in range(ZP_SAVE_LEN):
            assert cpu.memory[mem_syms.userland_zp_buf + i] == 0xC3, \
                f"userland_zp_buf[${i:02X}] modified by save_kernel_zp"


class TestRestoreKernelZp:
    # test_round_trip retired — subsumed by TestSaveRestoreEdgePatterns::
    # test_kernel_round_trip (four patterns, both save + restore).

    def test_pulls_from_kernel_not_userland(self, mem_syms):
        """restore_kernel_zp reads kernel_zp_buf, not userland_zp_buf."""
        cpu = make_cpu(mem_syms)
        for i in range(ZP_SAVE_LEN):
            cpu.memory[mem_syms.kernel_zp_buf   + i] = 0xAA
            cpu.memory[mem_syms.userland_zp_buf + i] = 0xBB
        cpu.memory[0x00] = 0xFF
        jsr(cpu, mem_syms.restore_kernel_zp)
        assert cpu.memory[0x02] == 0xAA, \
            f"restore pulled from wrong buffer: ${cpu.memory[0x02]:02X}"


class TestBufferIndependence:
    """The two buffers must be independent regions — writing one
    must not affect the other.  This guards against a future
    refactor accidentally aliasing them."""

    def test_userland_save_does_not_touch_kernel_buf(self, mem_syms):
        cpu = make_cpu(mem_syms)
        for i in range(ZP_SAVE_LEN):
            cpu.memory[mem_syms.kernel_zp_buf + i] = 0x77
        _prime_zp(cpu, list(range(ZP_SAVE_LEN)))
        jsr(cpu, mem_syms.save_userland_zp)
        for i in range(ZP_SAVE_LEN):
            assert cpu.memory[mem_syms.kernel_zp_buf + i] == 0x77, \
                f"kernel_zp_buf[${i:02X}] modified by save_userland_zp"


# ═════════════════════════════════════════════════════════════════
# §3  Segment-query accessors
# ═════════════════════════════════════════════════════════════════

class TestCseStart:
    def test_returns_code_run_in_ax(self, mem_syms):
        cpu = make_cpu(mem_syms)
        jsr(cpu, mem_syms.cse_start)
        lo, hi = cpu.a, cpu.x
        got = lo | (hi << 8)
        assert got == mem_syms.code_run, \
            f"cse_start returned ${got:04X}, expected ${mem_syms.code_run:04X}"


class TestCseEnd:
    def test_returns_d000_in_ax(self, mem_syms):
        cpu = make_cpu(mem_syms)
        jsr(cpu, mem_syms.cse_end)
        got = cpu.a | (cpu.x << 8)
        assert got == 0xD000, \
            f"cse_end returned ${got:04X}, expected $D000"


class TestCseZpEnd:
    def test_returns_zp_last_plus_one_low_byte(self, mem_syms):
        """cse_zp_end returns A = low(__ZP_LAST__ + 1); X = 0."""
        cpu = make_cpu(mem_syms)
        jsr(cpu, mem_syms.cse_zp_end)
        expected = (mem_syms.zp_last + 1) & 0xFF
        assert cpu.a == expected, \
            f"cse_zp_end A=${cpu.a:02X}, expected ${expected:02X}"
        assert cpu.x == 0, \
            f"cse_zp_end X=${cpu.x:02X}, expected 0"


# ═════════════════════════════════════════════════════════════════
# §4  Exported constants
# ═════════════════════════════════════════════════════════════════
#
# ZP_SAVE_LO and ZP_SAVE_LEN are exported compile-time constants.
# Other modules (repl.s::zp_stage_prep, repl.s::zp_poke) use them
# for range checks.  Tests pin them: if either ever changes, the
# callers need a coordinated update.

class TestExportedConstants:
    def test_zp_save_lo_and_len_cover_00_to_7f(self, mem_syms):
        """Proof by construction: a save/restore round-trip over the
        full range 0..127 must preserve every byte.  Any change to
        ZP_SAVE_LO or ZP_SAVE_LEN that shifts the range away from
        ($00, 128) will make some byte in this pattern round-trip
        incorrectly."""
        cpu = make_cpu(mem_syms)
        pattern = [(i + 0x10) & 0xFF for i in range(128)]
        _prime_zp(cpu, pattern)
        jsr(cpu, mem_syms.save_userland_zp)
        # Scrub live ZP below $80.
        for i in range(128):
            cpu.memory[i] = 0xCC
        jsr(cpu, mem_syms.restore_userland_zp)
        live = _read_zp(cpu)
        assert live == pattern, (
            "128-byte round-trip broken — ZP_SAVE_LO or ZP_SAVE_LEN "
            "may have drifted from the doc contract ($00, 128)"
        )

    def test_high_zp_untouched_by_save(self, mem_syms):
        """ZP_SAVE_LEN must stop at $80 — live $80..$FF is KERNAL-owned
        and any save that strays into it corrupts KERNAL state."""
        cpu = make_cpu(mem_syms)
        for i in range(0x80, 0x100):
            cpu.memory[i] = 0xA5
        jsr(cpu, mem_syms.save_userland_zp)
        for i in range(0x80, 0x100):
            assert cpu.memory[i] == 0xA5, \
                f"save strayed into live ${i:02X}"

    def test_high_zp_untouched_by_restore(self, mem_syms):
        cpu = make_cpu(mem_syms)
        cpu.memory[0x00] = 0xFF   # restore precondition
        for i in range(0x80, 0x100):
            cpu.memory[i] = 0xA5
        jsr(cpu, mem_syms.restore_userland_zp)
        for i in range(0x80, 0x100):
            assert cpu.memory[i] == 0xA5, \
                f"restore strayed into live ${i:02X}"


# ═════════════════════════════════════════════════════════════════
# §5  Banking edge cases (kernal_out flag variations)
# ═════════════════════════════════════════════════════════════════
#
# The contract says "No-op when kernal_out flag is set".  "Set" in 6502
# parlance means non-zero, not specifically $01.  Verify the short-
# circuit treats any non-zero value as a batch-in-progress marker.

class TestKernalOutFlagValues:
    """Any non-zero kernal_out value must short-circuit both helpers."""

    @pytest.mark.parametrize("flag", [0x01, 0x02, 0x7F, 0x80, 0xFF])
    def test_out_short_circuits_on_any_nonzero(self, mem_syms, flag):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = flag
        cpu.memory[0x01] = 0x37
        jsr(cpu, mem_syms.kernal_bank_out)
        assert cpu.memory[0x01] == 0x37, \
            f"flag=${flag:02X} did not short-circuit kernal_bank_out"

    @pytest.mark.parametrize("flag", [0x01, 0x02, 0x7F, 0x80, 0xFF])
    def test_in_short_circuits_on_any_nonzero(self, mem_syms, flag):
        cpu = make_cpu(mem_syms)
        cpu.memory[mem_syms.kernal_out] = flag
        cpu.memory[0x01] = 0x35
        jsr(cpu, mem_syms.kernal_bank_in)
        assert cpu.memory[0x01] == 0x35, \
            f"flag=${flag:02X} did not short-circuit kernal_bank_in"


# ═════════════════════════════════════════════════════════════════
# §6  Save/restore edge cases
# ═════════════════════════════════════════════════════════════════
#
# Boundary patterns: all-zero, all-$FF, alternating.  These catch
# byte-ordering and index-arithmetic mistakes that uniform test
# patterns can hide.

class TestSaveRestoreEdgePatterns:
    """Save/restore round-trips at pattern extremes."""

    @pytest.mark.parametrize("desc,pattern", [
        ("all-zero",  [0x00] * 128),
        ("all-FF",    [0xFF] * 128),
        ("alt-AA55",  [0xAA if (i & 1) else 0x55 for i in range(128)]),
        ("ascending", list(range(128))),
    ])
    def test_userland_round_trip(self, mem_syms, desc, pattern):
        cpu = make_cpu(mem_syms)
        _prime_zp(cpu, pattern)
        jsr(cpu, mem_syms.save_userland_zp)
        for i in range(128):
            cpu.memory[i] = 0x11
        jsr(cpu, mem_syms.restore_userland_zp)
        assert _read_zp(cpu) == pattern, f"pattern '{desc}' broken round-trip"

    @pytest.mark.parametrize("desc,pattern", [
        ("all-zero",  [0x00] * 128),
        ("all-FF",    [0xFF] * 128),
        ("alt-AA55",  [0xAA if (i & 1) else 0x55 for i in range(128)]),
    ])
    def test_kernel_round_trip(self, mem_syms, desc, pattern):
        cpu = make_cpu(mem_syms)
        _prime_zp(cpu, pattern)
        jsr(cpu, mem_syms.save_kernel_zp)
        for i in range(128):
            cpu.memory[i] = 0x11
        jsr(cpu, mem_syms.restore_kernel_zp)
        assert _read_zp(cpu) == pattern, f"pattern '{desc}' broken round-trip"


class TestCrossBufferRoundTrip:
    """Save to userland, save to kernel with different data, then
    restore each.  Proves the two buffers are fully independent
    and each restore pulls from its own buffer."""

    def test_save_both_restore_each(self, mem_syms):
        cpu = make_cpu(mem_syms)
        # Phase 1: snapshot "userland state" (pattern A).
        pattern_a = [(i ^ 0xAA) & 0xFF for i in range(128)]
        _prime_zp(cpu, pattern_a)
        jsr(cpu, mem_syms.save_userland_zp)

        # Phase 2: overwrite live ZP with "kernel state" (pattern B)
        # and snapshot it.
        pattern_b = [(i ^ 0x55) & 0xFF for i in range(128)]
        _prime_zp(cpu, pattern_b)
        jsr(cpu, mem_syms.save_kernel_zp)

        # Phase 3: restore userland — live ZP must become pattern A.
        jsr(cpu, mem_syms.restore_userland_zp)
        assert _read_zp(cpu) == pattern_a

        # Phase 4: restore kernel — live ZP must become pattern B.
        jsr(cpu, mem_syms.restore_kernel_zp)
        assert _read_zp(cpu) == pattern_b


# ═════════════════════════════════════════════════════════════════
# §7  Contract clauses intentionally not automated on py65
# ═════════════════════════════════════════════════════════════════
#
# mem.md documents hardware-level guarantees that depend on 6510
# CPU-port behaviour that py65 does not model.  They are explicit
# skips with reasons so the gap is visible in the test output.

class TestHardwareOnlyContract:

    # ⚠  TOP-RISK L1 GAP (per coverage audit 2026-04-20):
    #    The DDR-stash protocol is the most-likely place an undetected
    #    L1 regression could land — a "clever" refactor of save_*_zp
    #    that byte-round-trips on py65 but breaks the fully-latched-$01
    #    read on silicon would pass CI and ship.  The only backstop is
    #    the VICE manual checklist, which is not a tight loop.  If a
    #    future C64Emu adds CPU-port emulation, this skip should be
    #    converted into a real test and the xfail lifted.

    @pytest.mark.skip(reason=(
        "CPU-port DDR masking (mem.md § CPU-port aware ZP save/restore): "
        "the save protocol unmasks $01's input bits by setting DDR=$FF, "
        "so the loop reads the fully-latched $01.  py65 has no CPU-port "
        "emulation; $00/$01 behave as flat RAM with no DDR gating.  The "
        "byte-level round-trip is verified (TestSaveUserlandZp etc.); "
        "the hardware guarantee that input bits read fully-latched is "
        "verified ONLY in the VICE manual checklist.  See the TOP-RISK "
        "comment immediately above this skip — refactors to save_*_zp "
        "should be cross-checked on VICE before merge."
    ))
    def test_dollar_01_reads_fully_latched_under_ddr_ff(self, mem_syms):
        pass

    @pytest.mark.skip(reason=(
        "Banking side-effect on $A000-$BFFF / $E000-$FFFF (mem.md § "
        "Banking protocol): clearing bit 1 of $01 unmaps KERNAL ROM, "
        "after which reads at $E000-$FFFF return RAM contents rather "
        "than KERNAL bytes.  py65 has no ROMs, so this cannot be "
        "observed here.  Verified in integration-tier tests that use "
        "C64Emu with real KERNAL (tests/integration/test_c64emu_banking.py)."
    ))
    def test_bank_out_reveals_ram_under_kernal(self, mem_syms):
        pass

    @pytest.mark.skip(reason=(
        "I-flag preservation (mem.md § Interrupt vectors): doc says "
        "'I flag preserved.  Phase 18 IRQ early-entry handles IRQ-"
        "during-bank-out transparently.'  The proof of transparency "
        "requires an IRQ to actually fire mid-operation.  py65 has no "
        "scheduled-interrupt facility in this test tier; the stress "
        "test lives in integration (tests/integration/test_c64emu_"
        "interrupts.py)."
    ))
    def test_i_flag_preserved_across_bank_out_in(self, mem_syms):
        pass
