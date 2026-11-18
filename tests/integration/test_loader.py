"""test_loader.py — loader.s relocates the PRG as the harness assumes.

Owner: doc/modules/loader.md

Contract source: [loader.md § Design](../../doc/modules/loader.md#design).

Every other Tier I test loads the PRG through `EmuBase.load_prg()`,
whose `_relocate_segments()` copies each segment in Python, "as the
loader does".  This test holds the two to each other: it puts the
unrelocated PRG in memory, runs the real `loader_entry` up to the
`jmp _main`, and compares every relocated segment with what
`_relocate_segments()` produces — and checks the BSS is zeroed.
"""

from c64emu import C64Emu


def _segments(emu):
    """(name, run, size) of every segment the loader copies."""
    s = emu.sym
    return [("CODE+RODATA", s("__CODE_RUN__"), s("__CODE_SIZE__") + s("__RODATA_SIZE__")),
            ("KDATA", s("__KDATA_RUN__"), s("__KDATA_SIZE__"))]


def test_loader_entry_matches_python_relocation(cse_prg_per_cpu):
    prg_path, map_path = cse_prg_per_cpu

    ref = C64Emu()
    ref.load_prg(prg_path, map_path)                 # Python relocation

    emu = C64Emu()
    load_addr, payload = emu._read_prg(prg_path)
    emu._ram[load_addr:load_addr + len(payload)] = payload
    emu._load_symbols(map_path)                      # symbols only, no copy
    bss, bss_size = emu.sym("__BSS_RUN__"), emu.sym("__BSS_SIZE__")
    emu._ram[bss:bss + bss_size] = [0xA5] * bss_size  # stale RAM
    emu.run_until(emu.sym("_main"), start_at=emu.sym("loader_entry"),
                  max_cycles=2_000_000)

    for name, run, size in _segments(emu):
        assert size > 0
        assert bytes(emu._ram[run:run + size]) == bytes(ref._ram[run:run + size]), \
            f"{name} at ${run:04X} differs from _relocate_segments()"
    assert not any(emu._ram[bss:bss + bss_size]), "BSS not zeroed"
    assert emu.sp == 0xFF


# ── m65: the gate and the install (T8 of TODO § M65 slice 2, P0) ────
# loader.md § Design (m65), memory_design.md § Memory Map — m65 (the
# installed machine), testing.md § The m65 PRG on M65Emu.  On each
# ROM's post-boot snapshot, entered with that ROM's run premise.

import pytest                                               # noqa: E402

from m65emu import M65Emu                                   # noqa: E402
from m65emu.harness import run_premise                      # noqa: E402

CSE_BP, STUB_BASE, STACK_TOP = 0x1F, 0x1FB0, 0xF1
CSE_MAP, USER_MAP = (0xE300, 0xB300), (0xE000, 0x8300)
BANK3 = 0x30000
JUMP_TABLE = 0x3FF00                     # $FF00 of the KERNAL, 3.FF00
REFUSAL = "cse needs mega65 rom 920413+ (hyppo 1.2+)"


def _at_sys_entry(snapshot, prg_path, map_path):
    """M65Emu at the PRG's SYS entry: the snapshot, the PRG in bank 0
    as LOAD put it, the ROM's run premise; the symbols only."""
    emu = M65Emu(snapshot)
    load_addr, payload = emu._read_prg(prg_path)
    emu._ram[load_addr:load_addr + len(payload)] = payload
    emu._load_symbols(map_path)
    premise = run_premise(snapshot["state"]["rom"])
    emu.enter_premise(premise)
    return emu, premise


def _flat(emu, lo, hi):
    return bytes(emu.memory.read_flat(a) for a in range(lo, hi))


def test_m65_loader_installs_the_machine(cse_m65_prg, m65_snapshot):
    prg_path, map_path = cse_m65_prg
    emu, _ = _at_sys_entry(m65_snapshot, prg_path, map_path)
    s = emu.sym
    bss, bss_size = BANK3 + s("__BSS_RUN__"), s("__BSS_SIZE__")
    assert any(_flat(emu, bss, bss + bss_size)), "the ROM's bytes, not zero"
    emu.run_until(s("_main"), start_at=s("loader_entry"), max_cycles=2_000_000)

    # the CSE map, B, SP, interrupts off
    assert (emu.cpu.mapl, emu.cpu.maph) == CSE_MAP
    assert emu.b == CSE_BP
    assert emu.sp == 0x0100 | STACK_TOP
    assert emu.cpu.p & 0x04, "I set"
    # the stub at 0.1FB0, its cold target _main; CSE's base page cleared
    stub = _flat(emu, s("__STUB_LOAD__"), s("__STUB_LOAD__") + s("__STUB_SIZE__"))
    stub_run = _flat(emu, STUB_BASE, STUB_BASE + s("__STUB_SIZE__"))
    tgt = s("stub_cold_target") - STUB_BASE
    assert stub_run[:tgt] == stub[:tgt] and stub_run[tgt + 2:] == stub[tgt + 2:]
    assert emu.memory.read_flat(s("stub_cold_target")) | \
        emu.memory.read_flat(s("stub_cold_target") + 1) << 8 == s("_main")
    assert not any(_flat(emu, CSE_BP << 8, STUB_BASE)), "base page not cleared"
    # CODE + RODATA and KDATA in bank 3, BSS cleared, banks 2-3 writable
    for name, load, run, size in [
            ("CODE+RODATA", s("__CODE_LOAD__"), s("__CODE_RUN__"),
             s("__CODE_SIZE__") + s("__RODATA_SIZE__")),
            ("KDATA", s("__KDATA_LOAD__"), s("__KDATA_RUN__"), s("__KDATA_SIZE__"))]:
        assert size > 0
        assert _flat(emu, BANK3 + run, BANK3 + run + size) == _flat(emu, load, load + size), name
    assert not any(_flat(emu, bss, bss + bss_size)), "BSS not cleared"
    assert not emu.memory.rom_protect


def test_m65_install_prg_is_the_loaders_install(cse_m65_prg, m65_snapshot):
    """M65Emu.install_prg() leaves the machine the real loader leaves:
    chip RAM (banks 0-5), the registers that matter, the protection."""
    prg_path, map_path = cse_m65_prg
    emu, _ = _at_sys_entry(m65_snapshot, prg_path, map_path)
    emu.run_until(emu.sym("_main"), start_at=emu.sym("loader_entry"),
                  max_cycles=2_000_000)
    ref, _ = _at_sys_entry(m65_snapshot, prg_path, map_path)
    ref.install_prg(prg_path, map_path)

    for lo in range(0, 0x60000, 0x10000):
        a, b = _flat(emu, lo, lo + 0x10000), _flat(ref, lo, lo + 0x10000)
        diff = next((k for k in range(0x10000) if a[k] != b[k]), None)
        assert diff is None, f"${lo + diff:05X}: loader ${a[diff]:02X}, install_prg ${b[diff]:02X}"
    for r in ("pc", "a", "x", "y", "z", "b", "sp"):
        assert getattr(ref.cpu, r) == getattr(emu.cpu, r), r
    assert (ref.cpu.mapl, ref.cpu.maph) == (emu.cpu.mapl, emu.cpu.maph)
    assert ref.cpu.p & 0x04 == emu.cpu.p & 0x04
    assert ref.memory.rom_protect == emu.memory.rom_protect


def _refused(emu, premise):
    """Run the loader to the premise's SYS return; the gate refused."""
    before = {name: _flat(emu, lo, hi) for name, lo, hi in [
        ("CSE's page 0.1F00", CSE_BP << 8, 0x2000),
        ("bank 3's CSE regions", BANK3 + 0x2000, BANK3 + 0xC000)]}
    emu.run_until(premise["rts_target"], start_at=emu.sym("loader_entry"),
                  max_cycles=2_000_000)
    for name, (lo, hi) in {"CSE's page 0.1F00": (CSE_BP << 8, 0x2000),
                           "bank 3's CSE regions": (BANK3 + 0x2000, BANK3 + 0xC000)}.items():
        assert _flat(emu, lo, hi) == before[name], f"{name} written"
    assert emu.memory.rom_protect, "banks 2-3 made writable"
    assert (emu.cpu.mapl, emu.cpu.maph) == USER_MAP and emu.b == 0
    screen = " ".join(emu.screen_text(r) for r in range(25)).lower()
    assert REFUSAL in screen


@pytest.mark.parametrize("version", [(1, 1), (0, 9)], ids=["1.1", "0.9"])
def test_m65_loader_refuses_hyppo_below_1_2(cse_m65_prg, m65_snapshot, version):
    emu, premise = _at_sys_entry(m65_snapshot, *cse_m65_prg)
    emu.hypervisor.version = (*version, 1, 3)
    _refused(emu, premise)


@pytest.mark.parametrize("entry", [0xFFE4, 0xFF6B, 0xFF47],
                         ids=["GETIN", "SETBNK", "SYSFLAGS"])
def test_m65_loader_refuses_a_jump_table_entry_that_is_not_a_jmp(
        cse_m65_prg, m65_snapshot, entry):
    emu, premise = _at_sys_entry(m65_snapshot, *cse_m65_prg)
    emu.memory.rom_protect = False
    emu.memory.write_flat(JUMP_TABLE | entry & 0xFF, 0x60)   # RTS
    emu.memory.rom_protect = True
    _refused(emu, premise)


def test_m65_loader_accepts_hyppo_2(cse_m65_prg, m65_snapshot):
    emu, _ = _at_sys_entry(m65_snapshot, *cse_m65_prg)
    emu.hypervisor.version = (2, 0, 1, 3)
    emu.run_until(emu.sym("_main"), start_at=emu.sym("loader_entry"),
                  max_cycles=2_000_000)
    assert emu.b == CSE_BP
