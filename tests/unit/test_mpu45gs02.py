"""test_mpu45gs02.py — MPU45GS02, M65Emu's 45GS02 CPU (layer 1).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier U: needs neither xmega65 nor the MEGA65 ROM.  Three parts:
  - the decoder agrees with the compendium fixture, row for row;
  - targeted cases pin the 45GS02-specific behaviour by name (base
    page, E-flag stack, 16-bit branches, BSR, RTS #n, word ops, MAP
    latch, flat and Q prefixes, clean mode);
  - every case of the golden file recorded in xmega65
    (tests/fixtures/golden/m65_cpu.json) replays to the same
    registers and memory.
"""

import pytest

from m65emu import (FlatRAM, MPU45GS02, ReservedOpcode, UncleanOpcode,
                    UndefinedPrefix)
from m65emu import golden as G
from m65emu import isa
from m65emu.mpu45gs02 import (B, C, D, E, I, N, V, Z,
                              P_NEGNEG, P_NEGNEGNOP, P_NONE, P_NOP)

TABLE = isa.decode_table()


def cpu_with(code, *, at=0x1800, steps=None, **regs):
    """An MPU with `code` at `at`, registers from `regs`, run `steps`."""
    mem = FlatRAM()
    for k, v in enumerate(code):
        mem[at + k] = v
    cpu = MPU45GS02(mem, pc=at)
    for name, v in regs.items():
        setattr(cpu, name, v)
    for _ in range(steps or 0):
        cpu.step()
    return cpu


# ── decoder ───────────────────────────────────────────────────────

def test_every_4510_opcode_decodes_as_the_compendium_lists():
    cpu = MPU45GS02()
    rows = [r for r in isa.rows() if r.cpu_set == "4510"]
    assert sorted(r.key[0] for r in rows) == list(range(256))
    for r in rows:
        key, entry = cpu.decode(r.key[0], prefix=P_NONE)
        assert (key, entry.row) == (r.key, r)


def test_every_45gs02_row_decodes_under_its_prefix():
    state = {(0xEA,): P_NOP, (0x42, 0x42): P_NEGNEG,
             (0x42, 0x42, 0xEA): P_NEGNEGNOP}
    cpu = MPU45GS02()
    seen = set()
    for r in isa.rows():
        if r.cpu_set != "45GS02":
            continue
        key, entry = cpu.decode(r.key[-1], prefix=state[r.key[:-1]])
        assert key == r.key
        if r.key in seen:      # a reserved encoding listed twice
            assert r.mnemonic in isa.RESERVED
            continue
        seen.add(r.key)
        assert entry.row == r


def test_documented_6502_set_is_the_151_nmos_opcodes():
    keys = isa.documented_6502()
    assert len(keys) == 151
    assert (0xEA,) in keys and (0x5C,) not in keys and (0x42,) not in keys


# ── base page, stack, flags ───────────────────────────────────────

def test_base_page_access_is_offset_by_b():
    cpu = cpu_with([0xA5, 0x10], b=0x19)
    cpu.memory[0x1910] = 0x77
    cpu.memory[0x0010] = 0x11
    cpu.step()
    assert cpu.a == 0x77


def test_base_page_indexing_wraps_inside_the_base_page():
    cpu = cpu_with([0xB5, 0xF8], b=0x19, x=0x10)
    cpu.memory[0x1908] = 0x42
    cpu.memory[0x1A08] = 0x99
    cpu.step()
    assert cpu.a == 0x42


@pytest.mark.parametrize("e, sp_after", [(E, 0x01FF), (0, 0x00FF)])
def test_push_wraps_in_the_page_only_with_e_set(e, sp_after):
    cpu = cpu_with([0x48], a=0x5A, sp=0x0100, p=e | I)
    cpu.step()
    assert cpu.memory[0x0100] == 0x5A
    assert cpu.sp == sp_after


def test_plp_loads_flags_but_never_e_and_php_pushes_b():
    cpu = cpu_with([0x08, 0x28], p=E | C, sp=0x01F0)
    cpu.step()
    assert cpu.memory[0x01F0] == E | B | C
    cpu.memory[0x01F0] = N | V | D | I | Z | C      # E clear on the stack
    cpu.step()
    assert cpu.p == N | V | E | D | I | Z | C       # E kept, B not loaded


# ── branches and calls (O1: 16-bit offsets) ───────────────────────

def test_16_bit_branch_is_relative_to_the_last_byte():
    cpu = cpu_with([0x83, 0x10, 0x00], steps=1)      # BRA $+$10 (16-bit)
    assert cpu.pc == 0x1802 + 0x10


def test_bsr_pushes_its_last_byte_and_rts_returns_after_it():
    cpu = cpu_with([0x63, 0x0D, 0x00], sp=0x01F0, p=E | I, steps=1)
    assert cpu.pc == 0x1802 + 0x0D
    assert cpu.sp == 0x01EE
    assert (cpu.memory[0x01F0], cpu.memory[0x01EF]) == (0x18, 0x02)
    cpu.memory[cpu.pc] = 0x60
    cpu.step()
    assert cpu.pc == 0x1803


def test_rts_immediate_drops_its_argument_bytes():
    cpu = cpu_with([0x62, 0x03], sp=0x01EC, p=E | I)
    cpu.memory[0x01ED], cpu.memory[0x01EE] = 0x40, 0x12
    cpu.step()
    assert cpu.pc == 0x1241
    assert cpu.sp == 0x01EE + 3


def test_phw_pushes_low_byte_first():
    cpu = cpu_with([0xF4, 0x34, 0x12], sp=0x01F0, p=E | I, steps=1)
    assert (cpu.memory[0x01F0], cpu.memory[0x01EF]) == (0x34, 0x12)
    assert cpu.sp == 0x01EE


# ── 4510 operations ───────────────────────────────────────────────

def test_word_operations():
    cpu = cpu_with([0xE3, 0x10, 0xC3, 0x12, 0xCB, 0x00, 0x1A,
                    0xEB, 0x02, 0x1A], b=0x19, p=E | I | C)
    m = cpu.memory
    m[0x1910], m[0x1911] = 0xFF, 0x7F                 # INW → $8000
    m[0x1912], m[0x1913] = 0x01, 0x00                 # DEW → $0000
    m[0x1A00], m[0x1A01] = 0x87, 0xA9                 # ASW (compendium)
    m[0x1A02], m[0x1A03] = 0x00, 0x80                 # ROW, C in from ASW
    cpu.step()
    assert (m[0x1910], m[0x1911], cpu.p & (N | Z)) == (0x00, 0x80, N)
    cpu.step()
    assert (m[0x1912], m[0x1913], cpu.p & (N | Z)) == (0, 0, Z)
    cpu.step()
    assert (m[0x1A00], m[0x1A01], cpu.p & C) == (0x0E, 0x53, C)
    cpu.step()
    assert (m[0x1A02], m[0x1A03], cpu.p & (C | Z)) == (0x01, 0x00, C)


def test_neg_asr_and_stz_stores_z():
    cpu = cpu_with([0x42, 0xEA, 0x43, 0x64, 0x20], a=0x01, z=0x5C, b=0x19)
    cpu.step()
    assert cpu.a == 0xFF and cpu.p & N
    cpu.step()                                        # EOM: ends the prefix
    cpu.step()
    assert cpu.a == 0xFF and cpu.p & C                # ASR keeps bit 7
    cpu.step()
    assert cpu.memory[0x1920] == 0x5C


def test_register_transfers_of_b_and_sph():
    cpu = cpu_with([0x5B, 0x7B, 0x2B, 0x0B], a=0x19, y=0x02, sp=0x01F0)
    cpu.step()
    assert cpu.b == 0x19
    cpu.a = 0
    cpu.step()
    assert cpu.a == 0x19
    cpu.step()
    assert cpu.sp == 0x02F0
    cpu.y = 0
    cpu.step()
    assert cpu.y == 0x02


# ── MAP / EOM ─────────────────────────────────────────────────────

def test_map_sets_both_halves_and_latches_interrupts_until_eom():
    cpu = cpu_with([0x5C, 0xEA, 0xA9, 0x00], a=0x00, x=0xE3, y=0x00,
                   z=0xB3, p=E, sp=0x01F0)
    cpu.memory[0xFFFE], cpu.memory[0xFFFF] = 0x00, 0x20
    cpu.step()                                        # MAP
    assert (cpu.mapl, cpu.maph, cpu.map_latch) == (0xE300, 0xB300, True)
    assert not cpu.irq() and not cpu.nmi()
    cpu.step()                                        # EOM: latch released,
    assert not cpu.map_latch                          # but a NOP prefix
    assert not cpu.irq()                              # is now pending
    cpu.step()                                        # LDA #: prefix ends
    assert cpu.irq() and cpu.pc == 0x2000


def test_map_with_0f_selects_the_megabyte_and_keeps_the_offset():
    cpu = cpu_with([0x5C], a=0x80, x=0x0F, y=0x12, z=0x0F, steps=1)
    assert (cpu.map_lo_mb, cpu.map_hi_mb) == (0x80, 0x12)
    assert (cpu.mapl, cpu.maph) == (0, 0)


# ── prefixes: flat and Q ──────────────────────────────────────────

def test_flat_load_and_store_through_a_28_bit_pointer():
    cpu = cpu_with([0xEA, 0xB2, 0x20, 0xEA, 0x92, 0x24], b=0x19, z=0x05)
    m = cpu.memory
    for k, v in enumerate([0x00, 0x00, 0x04, 0x00, 0x00, 0x00, 0x05, 0x00]):
        m[0x1920 + k] = v
    m.write_flat(0x40005, 0xAB)
    cpu.step()
    cpu.step()
    assert cpu.a == 0xAB and cpu.pc == 0x1803
    cpu.step()
    cpu.step()
    assert m.read_flat(0x50005) == 0xAB


def test_q_operations_use_axyz_and_neg_neg_restores_a():
    code = [0x42, 0x42, 0xA5, 0x10,                   # LDQ $10
            0x42, 0x42, 0x0A,                         # ASLQ Q
            0x42, 0x42, 0x85, 0x14]                   # STQ $14
    cpu = cpu_with(code, b=0x19, a=0x33, p=E | I)
    m = cpu.memory
    for k, v in enumerate([0x01, 0x00, 0x00, 0x80]):
        m[0x1910 + k] = v
    cpu.step()
    assert cpu.a == (-0x33 & 0xFF)
    cpu.step()
    assert cpu.a == 0x33
    cpu.step()
    assert cpu.q == 0x80000001 and cpu.p & N
    for _ in range(3):
        cpu.step()
    assert cpu.q == 0x00000002 and cpu.p & C
    for _ in range(3):
        cpu.step()
    assert [m[0x1914 + k] for k in range(4)] == [2, 0, 0, 0]


def test_a_prefix_without_a_row_runs_the_plain_opcode():
    cpu = cpu_with([0x42, 0x42, 0xA9, 0x05], a=0x10, steps=3)
    assert (cpu.a, cpu.x, cpu.pc) == (0x05, 0x00, 0x1804)


def test_reserved_q_rows_and_neg_neg_neg_are_refused():
    cpu = cpu_with([0x42, 0x42, 0x81, 0x00], steps=2)
    with pytest.raises(ReservedOpcode):
        cpu.step()
    cpu = cpu_with([0x42, 0x42, 0x42], steps=2)
    with pytest.raises(UndefinedPrefix):
        cpu.step()


# ── clean mode ────────────────────────────────────────────────────

def test_clean_mode_admits_6502_opcodes_and_the_allowed_set_only():
    mem = FlatRAM()
    for k, v in enumerate([0xA9, 0x01, 0x5C, 0xEA, 0xB2, 0x20, 0xA3, 0x00]):
        mem[0x1800 + k] = v
    cpu = MPU45GS02(mem, pc=0x1800, clean=True,
                    allow={(0x5C,), (0xEA, 0xB2)})
    cpu.step()                                        # LDA #: 6502
    cpu.step()                                        # MAP: allowed
    cpu.step()                                        # EOM: 6502 NOP
    cpu.step()                                        # LDA [zp],Z: allowed
    with pytest.raises(UncleanOpcode):
        cpu.step()                                    # LDZ #: refused
    assert cpu.pc == 0x1806


# ── golden file (recorded in xmega65) ─────────────────────────────

GOLDEN = G.load()


def test_golden_file_has_a_case_for_every_row():
    def key_of(code):          # the longest prefix of the code that is a key
        return next(code[:n] for n in (4, 3, 2, 1) if code[:n] in TABLE)
    covered = {key_of(tuple(bytes.fromhex(case["code"])))
               for case in GOLDEN["cases"]}
    missing = {k for k, r in TABLE.items()
               if r.mnemonic not in isa.RESERVED} - covered
    assert not missing, sorted(missing)


@pytest.mark.parametrize("case", GOLDEN["cases"],
                         ids=[c["name"] for c in GOLDEN["cases"]])
def test_golden_case(case):
    start = G.start_memory(GOLDEN, case)
    mem = FlatRAM()
    for a, v in start.items():
        mem.write_flat(a, v)
    for a, v in G.addrs(case.get("cpu_view", {})).items():
        mem[a] = v
    cpu = MPU45GS02(mem)
    for name in G.REG_NAMES:
        setattr(cpu, name, case["before"][name])
    for _ in range(case["steps"]):
        cpu.step()
    assert {name: getattr(cpu, name) for name in G.REG_NAMES} == case["after"]
    want = start | G.addrs(case["mem_after"])
    diff = {f"{a:05X}": (mem.read_flat(a), v) for a, v in want.items()
            if mem.read_flat(a) != v}
    assert not diff, diff
