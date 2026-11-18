"""test_m65_debugger.py — the debugger on the m65 PRG (P1, Tier I).

Owner: doc/modules/debugger.md

Contract source: [doc/testing.md § The m65 PRG on M65Emu](../../doc/testing.md#the-m65-prg-on-m65emu),
[doc/platform_layer.md § Far memory](../../doc/platform_layer.md#far-memory).

Runs the debug m65 PRG, installed by M65Emu.install_prg(), on each
post-boot snapshot (the real KERNAL handles every BRK, NMI and MAP).
The REPL needs P2's display bodies, so the routines are driven
directly, as main_loop and the commands would drive them; what is
rendered is P2's (testing.md, D-P1-5).

- far_user (FAR_USER's m65 body): a user address becomes the far
  address the user map shows it at — the four rows and their edges;
  A, X, Y kept.
- The workspace bound (T5): b's gate, the step gate and the
  assembler's emit gate take $2000-$BFFF (and the step gate brk_stub),
  nothing else.
- The line parser reads line_buf in bank 3 (T6): exec_line's `r`
  applies the fields it parsed (stopped before emit_reg renders).
"""

import pytest

from m65emu import M65Emu
from m65emu.harness import CSE_BP, USER_MAP, flat


@pytest.fixture
def emu(cse_m65_prg, m65_snapshot):
    emu = M65Emu(m65_snapshot)
    emu.install_prg(*cse_m65_prg)
    return emu


def cell(emu, name):
    """The CPU address (under the CSE map) of a CSE variable: a
    base-page symbol is in 0.1F00, the rest in the data window."""
    v = emu.sym(name)
    return CSE_BP << 8 | v if v < 0x100 else v


def petscii(text):
    out = []
    for ch in text.encode("ascii"):
        if 0x61 <= ch <= 0x7A:
            ch -= 0x20
        out.append(ch)
    return out


def bp(emu, name):
    """The flat address of a CSE base-page symbol (B = CSE_BP)."""
    return flat(0, CSE_BP << 8 | emu.sym(name))


def far_bytes(emu, name):
    a = bp(emu, name)
    return [emu.memory.read_flat(a + k) for k in range(4)]


def set_far(emu, name, offset, bank=0x77, mb=0x77):
    a = bp(emu, name)
    for k, v in enumerate([offset & 0xFF, offset >> 8, bank, mb]):
        emu.memory.write_flat(a + k, v)


def user_view_flat(emu, addr):
    """Where the user map shows `addr`: (flat address, is I/O)."""
    cpu = emu.cpu
    saved = cpu.mapl, cpu.maph
    cpu.mapl, cpu.maph = USER_MAP
    try:
        return emu.memory.flat_of(addr)
    finally:
        cpu.mapl, cpu.maph = saved


# ── far_user: the four rows (platform_layer.md § Far memory) ───────

USER_ADDRS = [0x0000, 0x0001, 0x1F00, 0x2000, 0xBFFF,     # bank 0
              0xC000, 0xCFFF,                             # the interface ROM
              0xD000, 0xD020, 0xDFFF,                     # I/O
              0xE000, 0xFFFF]                             # the KERNAL


def far_of(b):
    return b[3] << 24 | b[2] << 16 | b[1] << 8 | b[0]


@pytest.mark.parametrize("addr", USER_ADDRS, ids=[f"${a:04X}" for a in USER_ADDRS])
def test_far_user_reaches_where_the_user_map_shows_the_address(emu, addr):
    set_far(emu, "rp_ptr", addr)
    emu.jsr(emu.sym("far_user"), a=0x5A, x=emu.sym("rp_ptr"), y=0xA5, b=CSE_BP)
    assert (emu.a, emu.x, emu.y) == (0x5A, emu.sym("rp_ptr"), 0xA5)
    target = far_of(far_bytes(emu, "rp_ptr"))
    view = user_view_flat(emu, addr)
    if 0xD000 <= addr < 0xE000:                    # I/O: no flat RAM behind it
        assert view is None
        assert target == 0xFFD3000 | addr & 0xFFF
    elif addr < 2:                                 # the port: the RAM beneath
        assert view is None                        # (the user-ZP view shows
        assert target == addr                      #  the captured port)
    else:
        assert target == view


def test_far_user_io_row_reaches_the_register_the_user_sees(emu):
    """$D020 through the pointer is the border colour register."""
    set_far(emu, "rp_ptr", 0xD020)
    emu.jsr(emu.sym("far_user"), x=emu.sym("rp_ptr"), b=CSE_BP)
    emu.memory[0xD020] = 0x0B                      # the CSE map shows I/O too
    assert emu.memory.read_flat(far_of(far_bytes(emu, "rp_ptr"))) == 0x0B


# ── the workspace bound (T5; platform_layer.md § Constants) ────────

WS = [(0x1FFF, False), (0x2000, True), (0xBFFF, True), (0xC000, False),
      (0x0800, False), (0xE000, False)]


@pytest.mark.parametrize("addr,inside", WS, ids=[f"${a:04X}" for a, _ in WS])
@pytest.mark.parametrize("gate", ["bp_range_check", "bp_range_check_step"])
def test_breakpoint_gates_take_the_program_region_only(emu, gate, addr, inside):
    emu.jsr(emu.sym(gate), a=addr & 0xFF, x=addr >> 8, b=CSE_BP)
    assert emu.carry is (not inside)


def test_step_gate_also_takes_brk_stub(emu):
    stub = emu.sym("brk_stub")
    emu.jsr(emu.sym("bp_range_check_step"), a=stub & 0xFF, x=stub >> 8, b=CSE_BP)
    assert emu.carry is False
    emu.jsr(emu.sym("bp_range_check"), a=stub & 0xFF, x=stub >> 8, b=CSE_BP)
    assert emu.carry is True


@pytest.mark.parametrize("addr,inside", WS, ids=[f"${a:04X}" for a, _ in WS])
def test_emit_gate_writes_the_program_region_only(emu, addr, inside):
    mem = emu.memory
    mem[cell(emu, "asm_pass")] = 1
    mem[cell(emu, "_pc_wrap")] = 0
    mem[cell(emu, "_oor")] = 0
    pc = cell(emu, "asm_pc")
    mem[pc], mem[pc + 1] = addr & 0xFF, addr >> 8
    before = mem.read_flat(addr)
    emu.jsr(emu.sym("_emit_byte"), a=before ^ 0xA5, b=CSE_BP)
    written = mem.read_flat(addr) == before ^ 0xA5
    assert written is inside
    assert (mem[cell(emu, "_oor")] != 0) is (not inside)


# ── the line parser in bank 3 (T6) ─────────────────────────────────

def test_exec_line_parses_r_fields_from_line_buf(emu):
    """`r x:05 a:3c` applies both fields; the line is read through
    rp_ptr in bank 3, where line_buf is.  Stopped at emit_reg: the
    echo is rendered through P2's display."""
    lb = emu.sym("line_buf")
    data = petscii("r x:05 a:3c") + [0]
    for k, b in enumerate(data):
        emu.memory[lb + k] = b
    emu.run_until(emu.sym("emit_reg"), start_at=emu.sym("exec_line"),
                  max_cycles=200_000)
    assert emu.memory[emu.sym("reg_x")] == 0x05
    assert emu.memory[emu.sym("reg_a")] == 0x3C
