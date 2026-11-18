"""test_m65emu_harness.py — the M65Emu harness itself, without a snapshot.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Tier U: a bare M65Emu (blank memory, no ROM) is enough to pin the
harness surface — jsr() on the current stack with a sentinel never
written, run_until(), registers, load_prg() into bank 0,
screen_text() through the VIC-IV screen pointer, the I/O access log,
M65Memory.restore(), and load_snapshot() refusing a missing or an
outdated snapshot.  The real-KERNAL tests (Tier I) are in
tests/integration/test_m65emu.py.
"""

import json

import pytest

from m65emu import M65Emu, SnapshotMissing, load_snapshot
from m65emu.harness import FORMAT
from m65emu.memory import VIC2, VIC4

E, I = 0x20, 0x04


def emu_with(code, at=0x1800):
    emu = M65Emu()
    for k, b in enumerate(code):
        emu.memory[at + k] = b
    return emu


def test_jsr_runs_on_the_current_stack_and_returns():
    emu = emu_with([0xA9, 0x42, 0x60])                 # LDA #$42; RTS
    emu.sp = 0x01EE
    steps = emu.jsr(0x1800)
    assert (emu.a, steps, emu.sp) == (0x42, 2, 0x01EE)
    assert emu.memory[emu.SENTINEL] == 0                # never written


def test_jsr_sets_the_45gs02_registers():
    emu = emu_with([0x60])
    emu.jsr(0x1800, a=1, x=2, y=3, z=4, b=0x19, carry=True)
    assert (emu.a, emu.x, emu.y, emu.z, emu.b, emu.carry) == (1, 2, 3, 4, 0x19, True)
    with pytest.raises(TypeError):
        emu.jsr(0x1800, sp=0)


def test_jsr_times_out():
    emu = emu_with([0x4C, 0x00, 0x18])                 # JMP *
    with pytest.raises(TimeoutError, match="M65Emu"):
        emu.jsr(0x1800, max_cycles=100)


def test_run_until_and_watch():
    emu = emu_with([0xEA, 0xEA, 0xEA, 0xEA])
    assert emu.run_until(0x1803, start_at=0x1800) == 3
    emu.pc = 0x1800
    assert emu.run_until_with_watch(0x1803, [0x1801, 0x1802]) == \
        [(0x1801, 1), (0x1802, 2)]
    emu.pc = 0x1800
    assert emu.run_until_with_watch(0x1803, []) == []


def test_sp_is_16_bit():
    emu = M65Emu()
    emu.sp = 0x02F0
    assert (emu.sp, emu.cpu.sp) == (0x02F0, 0x02F0)


def test_load_prg_writes_bank_0_whatever_is_mapped(tmp_path):
    """(What load_prg() shares with C64Emu: test_emu_parity.py.)"""
    prg = tmp_path / "t.prg"
    prg.write_bytes(bytes([0x01, 0x20, 0xA9, 0x07, 0x60]))   # $2001: LDA #7; RTS
    emu = M65Emu()
    emu.cpu.mapl = 0xE400                              # MAP $2000 → $42000
    assert emu.load_prg(prg) == 0x2001
    assert emu.memory.read_flat(0x2001) == 0xA9        # bank 0, as LOAD does
    assert emu.memory[0x2001] == 0x00                  # the CPU sees $42001


def test_screen_text_follows_the_vic_iv_screen_pointer():
    emu = M65Emu()
    io = emu.memory.io
    io[0x58], io[0x59] = 80, 0                         # line step 80
    io[0x5E] = 80                                      # 80 characters
    io[0x60], io[0x61], io[0x62], io[0x63] = 0x00, 0x08, 0x00, 0x00   # $0800
    row = 0x0800 + 3 * 80
    emu.memory.load(row, bytes([0x08, 0x09, 0x20, 0x41]) + b" " * 76)  # "hi A"
    assert emu.screen_text(3) == "hi A"
    assert len(emu.screen_row(3)) == 80


def test_io_log_counts_unmodelled_registers_only():
    emu = M65Emu()
    mem = emu.memory
    mem[0x0001] = 0x35                                 # I/O in
    mem.io_log.clear()
    _ = mem[0xD061]
    mem[0xD020] = 1
    _ = mem[0xD800]                                    # colour window
    mem[0xD02F] = 0x47                                 # the key register
    _ = mem[0xD02F], mem[0xD030]                       # modelled by the memory
    assert dict(mem.io_log) == {"R $D061": 1, "W $D020": 1}


def test_restore_sets_banking_without_the_key_dance():
    emu = M65Emu()
    mem = emu.memory
    n = mem.rebuilds
    mem.restore(ddr=0xFF, port=0x35, d030=0x20, io_mode=VIC4)
    assert (mem.ddr, mem.port, mem.d030, mem.io_mode) == (0xFF, 0x35, 0x20, VIC4)
    assert mem.rebuilds == n + 1
    assert mem.rd[0xC] == 0x2C000                      # $D030 ROM at $C000
    mem.restore(ddr=0xFF, port=0x30, d030=0x00, io_mode=VIC2)
    assert mem.rd[0xD] == 0xD000                       # all RAM


def test_load_snapshot_refuses_a_missing_or_an_outdated_snapshot(tmp_path):
    with pytest.raises(SnapshotMissing, match="capture_m65_state.py"):
        load_snapshot(tmp_path)
    for name in ("chip.bin", "colour.bin", "io.bin"):
        (tmp_path / name).write_bytes(b"\x00")
    (tmp_path / "reference.json").write_text('{"runs": []}')
    (tmp_path / "state.json").write_text(json.dumps({"format": FORMAT - 1}))
    with pytest.raises(SnapshotMissing, match="older format"):
        load_snapshot(tmp_path)
    (tmp_path / "state.json").write_text(json.dumps({"format": FORMAT}))
    assert load_snapshot(tmp_path)["reference"] == {"runs": []}
