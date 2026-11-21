"""test_m65_lens.py — the monitor's CPU lens: far_user through the bank state.

Owner: doc/modules/mem.md

Contract source: [mem.md § far_user](../../doc/modules/mem.md#far_user-far_user_w-m65-only)
(slice 3, F2); [testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

The oracle is the recording: for every banking state in
tests/fixtures/golden/m65_mem.json but the VIC-II personality's (26 of
29; CSE's runs keep the MEGA65 personality) the program's bank state is set in
CSE's base page (MAP's X A Z Y and the megabytes in `um_map`, DDR and
port in `userland_zp_buf`, `$D030` in `um_d030`), and `far_user` /
`far_user_w` must translate each probed CPU address to the flat
address xmega65's CPU read / wrote.  A write the CPU drops (a mapped
ROM bank) is one `far_user_w` points into banks 2-3, which the REPL's
write guard refuses.
"""

import json
import pathlib

import pytest

from m65emu.harness import CSE_BP
from test_m65_repl import M65Session

ROOT = pathlib.Path(__file__).resolve().parents[2]
GOLDEN = json.loads((ROOT / "tests" / "fixtures" / "golden" / "m65_mem.json").read_text())
COLOUR = 0xFF80000
IO_REGS = 0xFFD3000


@pytest.fixture(scope="module")
def s(cse_m65_prg, m65_snapshot):
    return M65Session(cse_m65_prg, m65_snapshot)


def set_bank_state(s, st):
    um = s.cell("um_map")
    for k, v in enumerate([st["mapl"] >> 8, st["mapl"] & 0xFF,
                           st["maph"] >> 8, st["maph"] & 0xFF,
                           st["mb_lo"], st["mb_hi"]]):
        s.e.memory[um + k] = v
    buf = s.cell("userland_zp_buf")
    s.e.memory[buf], s.e.memory[buf + 1] = st["ddr"], st["port"]
    s.e.memory[s.cell("um_d030")] = st["d030"]


def translate(s, routine, addr):
    p = s.cell("rp_ptr")
    s.e.memory[p], s.e.memory[p + 1] = addr & 0xFF, addr >> 8
    s.e.memory[p + 2] = s.e.memory[p + 3] = 0xEE
    s.call(routine, x=p - (CSE_BP << 8))
    b = [s.e.memory[p + k] for k in range(4)]
    return b[0] | b[1] << 8 | b[2] << 16 | (b[3] & 0x0F) << 24


def same_cell(ours, recorded):
    """The I/O page: CSE names a register by its MEGA65-personality
    window FFD.3xxx; the CPU reached the colour RAM there ($D800+)."""
    if ours == recorded:
        return True
    off = ours - IO_REGS
    return 0x800 <= off < 0x1000 and recorded == COLOUR + off - 0x800


STATES = [st for st in GOLDEN["states"] if st["setup"]["key"] != "vic2"]


@pytest.mark.parametrize("st", STATES, ids=[st["name"] for st in STATES])
def test_far_user_reads_where_the_cpu_reads(s, st):
    set_bank_state(s, st["setup"])
    for probe in st["probes"]:
        addr, want = int(probe["addr"], 16), int(probe["read"], 16)
        got = translate(s, "far_user", addr)
        assert same_cell(got, want), f"${addr:04X}: ${got:07X}, recorded ${want:07X}"


@pytest.mark.parametrize("st", STATES, ids=[st["name"] for st in STATES])
def test_far_user_w_writes_where_the_cpu_writes(s, st):
    set_bank_state(s, st["setup"])
    for probe in st["probes"]:
        addr = int(probe["addr"], 16)
        got = translate(s, "far_user_w", addr)
        if probe["write"] is None:               # dropped: a ROM bank
            assert 0x20000 <= got < 0x40000, f"${addr:04X}: ${got:07X}"
        else:
            want = int(probe["write"], 16)
            assert same_cell(got, want), f"${addr:04X}: ${got:07X}, recorded ${want:07X}"
