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
- The user-ZP view (T7): $00/$01 are the captured CPU port, every
  other base-page address base page 0 itself, live.
- The transitions (T8): user code in bank 0 entered through
  return_to_userland / restore_userland_state; every break comes back
  through the KERNAL's interrupt entry and the resident stub, and the
  run stops at hygiene_after_userland (the first P2 body on the way
  back), or at cse_refresh / cse_recover.
- The bank state (T9): a program's MAP (megabytes too), CPU port and
  $D030 survive a break and a resume exactly; a fresh start gets the
  run premise's.
"""

import pytest

from m65emu import M65Emu
from m65emu.harness import CSE_BP, CSE_MAP, STACK_TOP, USER_MAP, flat

DBG_RTS, DBG_BRK, DBG_NMI = 1, 2, 3      # src/dbg_reason.inc
STEP_INTO, STEP_OVER = 1, 2              # src/debugger.s
ST_REPL = 1                              # src/main.s
USER = 0x3000                            # user code, bank 0 (flat)
PREMISE_PORT = (0xFF, 0x85)              # the run premise's DDR, port
PREMISE_D030 = 0x64


@pytest.fixture
def emu(cse_m65_prg, m65_snapshot):
    emu = M65Emu(m65_snapshot)
    emu.install_prg(*cse_m65_prg)
    return emu


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
    mem[emu.cell("asm_pass")] = 1
    mem[emu.cell("_pc_wrap")] = 0
    mem[emu.cell("_oor")] = 0
    pc = emu.cell("asm_pc")
    mem[pc], mem[pc + 1] = addr & 0xFF, addr >> 8
    before = mem.read_flat(addr)
    emu.jsr(emu.sym("_emit_byte"), a=before ^ 0xA5, b=CSE_BP)
    written = mem.read_flat(addr) == before ^ 0xA5
    assert written is inside
    assert (mem[emu.cell("_oor")] != 0) is (not inside)


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


# ── the debugger's setup, as _main leaves it ──────────────────────

def ready(emu):
    """setup_interrupts, dbg_init and the globals main_loop relies on."""
    emu.jsr(emu.sym("setup_interrupts"), b=CSE_BP)
    emu.jsr(emu.sym("dbg_init"), b=CSE_BP)
    mem = emu.memory
    mem[emu.cell("state")] = ST_REPL
    mem[emu.cell("run_user_pending")] = 0
    emu.write_word(emu.cell("cur_addr"), USER)


def user_code(emu, code, at=USER):
    emu.memory.load(at, bytes(code))          # flat bank 0: the user's


def word(emu, name):
    a = emu.cell(name)
    return emu.memory[a] | emu.memory[a + 1] << 8


def run_user(emu, entry, *, start="return_to_userland", stop="hygiene_after_userland",
             nmi_after=None, max_cycles=300_000):
    """Enter user code at `entry` the way main_loop does; run to `stop`."""
    emu.write_word(emu.cell("brk_pc"), entry)
    if nmi_after is not None:
        emu.schedule_nmi(nmi_after)
    emu.run_until(emu.sym(stop), start_at=emu.sym(start), max_cycles=max_cycles)


def resume(emu, **kw):
    """`c`: SP back at the user's, the session's sentinel in place."""
    emu.cpu.sp = 0x100 | emu.memory[emu.cell("reg_sp")]
    run_user(emu, word(emu, "brk_pc"), start="restore_userland_state", **kw)


def regs(emu):
    m = emu.memory
    return {r: m[emu.cell("reg_" + r)] for r in ("a", "x", "y", "z", "b", "p", "sp")}


def run_line(emu, text, stop):
    lb = emu.sym("line_buf")
    data = petscii(text) + [0]
    for k, b in enumerate(data):
        emu.memory[lb + k] = b
    emu.run_until(emu.sym(stop), start_at=emu.sym("exec_line"), max_cycles=200_000)


def test_r_sets_z_and_b(emu):
    """m65's `r` fields z: and b: (debugger.md § `r`), parsed from bank 3."""
    run_line(emu, "r z:12 b:16 x:05", "emit_reg")
    m = emu.memory
    assert (m[emu.sym("reg_z")], m[emu.sym("reg_b")], m[emu.sym("reg_x")]) == \
        (0x12, 0x16, 0x05)


def test_r_with_a_malformed_field_changes_nothing(emu):
    m = emu.memory
    m[emu.sym("reg_z")] = 0x77
    run_line(emu, "r z:12 b:1g", "_syntax_err")
    assert (m[emu.sym("reg_z")], m[emu.sym("reg_b")]) == (0x77, 0x00)


@pytest.mark.skip(reason=(
    "emit_reg's m65 line `r pc:XXXX a:XX x:XX y:XX z:XX b:XX s:XX nv-bdizc` "
    "(debugger.md § `r`, 80 columns) renders through io_putc, whose m65 row "
    "tables are P2's (D-P1-5); checked by P2's typed-command suite.  The "
    "40-column layout is a P2 item of its own (TODO § M65 slice 2, P2)."))
def test_r_shows_z_and_b_in_80_columns():
    pass


# ── T7: the user-ZP view ───────────────────────────────────────────

def test_user_zp_view_shows_the_captured_port_and_base_page_0(emu):
    ready(emu)
    mem = emu.memory
    buf = emu.cell("userland_zp_buf")
    mem[buf], mem[buf + 1] = 0x2F, 0x34
    for k in range(2, 8):
        mem.write_flat(k, 0x40 + k)                # base page 0 itself
    emu.write_word(emu.cell("rp_addr"), 0x0000)
    emu.jsr(emu.sym("zp_stage_prep_addr"), b=CSE_BP)
    stage = emu.cell("zp_stage_buf")
    assert [mem[stage + k] for k in range(8)] == [0x2F, 0x34] + [0x40 + k for k in range(2, 8)]


def test_zp_poke_lands_the_port_in_its_image_and_the_rest_live(emu):
    ready(emu)
    mem = emu.memory
    rp2 = emu.cell("rp_ptr2")
    mem[rp2], mem[rp2 + 1] = 0x00, 0x00
    emu.jsr(emu.sym("far_user"), x=emu.sym("rp_ptr2"), b=CSE_BP)
    emu.jsr(emu.sym("zp_poke"), a=0x37, y=1, b=CSE_BP)
    emu.jsr(emu.sym("zp_poke"), a=0x99, y=2, b=CSE_BP)
    assert mem[emu.cell("userland_zp_buf") + 1] == 0x37
    assert mem.read_flat(2) == 0x99
    assert mem.read_flat(1) != 0x37                # never the RAM beneath


def test_peek_user_reads_the_port_image(emu):
    ready(emu)
    mem = emu.memory
    mem[emu.cell("userland_zp_buf") + 1] = 0x34
    rp = emu.cell("rp_ptr")
    mem[rp], mem[rp + 1] = 0x01, 0x00
    emu.jsr(emu.sym("far_user"), x=emu.sym("rp_ptr"), b=CSE_BP)
    emu.jsr(emu.sym("peek_user"), b=CSE_BP)
    assert emu.a == 0x34


# ── T8: the transitions ────────────────────────────────────────────

def at_stop_in_cse(emu):
    assert (emu.cpu.mapl, emu.cpu.maph) == CSE_MAP
    assert emu.b == CSE_BP


def test_fresh_start_and_rts_is_a_clean_exit(emu):
    ready(emu)
    user_code(emu, [0x60])                         # RTS
    run_user(emu, USER)
    at_stop_in_cse(emu)
    assert emu.memory[emu.cell("dbg_reason")] == DBG_RTS
    assert word(emu, "brk_pc") == USER             # cur_addr
    assert emu.memory[emu.cell("reg_sp")] == STACK_TOP


def test_user_brk_captures_every_register(emu):
    ready(emu)
    user_code(emu, [0xA9, 0x16, 0x5B,              # LDA #$16 · TAB
                    0xA3, 0x44, 0xA0, 0x33,        # LDZ #$44 · LDY #$33
                    0xA2, 0x22, 0xA9, 0x11,        # LDX #$22 · LDA #$11
                    0x00, 0x00])                   # BRK
    run_user(emu, USER)
    at_stop_in_cse(emu)
    m = emu.memory
    assert m[emu.cell("dbg_reason")] == DBG_BRK
    assert word(emu, "brk_pc") == USER + 11
    r = regs(emu)
    assert (r["a"], r["x"], r["y"], r["z"], r["b"]) == (0x11, 0x22, 0x33, 0x44, 0x16)
    assert r["sp"] == STACK_TOP - 2                # below the sentinel


def test_breakpoint_hit_restores_the_byte_and_resumes(emu):
    ready(emu)
    user_code(emu, [0xA9, 0x42, 0xEA, 0x60])       # LDA #$42 · NOP · RTS
    emu.jsr(emu.sym("dbg_bp_set"), a=(USER + 2) & 0xFF, x=(USER + 2) >> 8, b=CSE_BP)
    slot = emu.a
    run_user(emu, USER)
    m = emu.memory
    assert m[emu.cell("dbg_reason")] == DBG_BRK
    assert m[emu.cell("dbg_bp_hit")] == slot
    assert word(emu, "brk_pc") == USER + 2
    assert m.read_flat(USER + 2) == 0xEA           # unpatched
    assert regs(emu)["a"] == 0x42
    emu.jsr(emu.sym("dbg_bp_del"), a=slot, b=CSE_BP)
    resume(emu)
    assert m[emu.cell("dbg_reason")] == DBG_RTS


def test_nmi_in_user_code_breaks_at_its_pc(emu):
    ready(emu)
    user_code(emu, [0x4C, USER & 0xFF, USER >> 8])  # JMP *
    run_user(emu, USER, nmi_after=2000)            # well past the transition
    assert emu.memory[emu.cell("dbg_reason")] == DBG_NMI
    assert word(emu, "brk_pc") == USER
    at_stop_in_cse(emu)


@pytest.mark.parametrize("kind,stop", [("nmi", "cse_refresh"), ("brk", "cse_recover")])
def test_kernel_mode_break_keeps_a_sessions_bank_state(emu, kind, stop):
    ready(emu)
    m = emu.memory
    state = [emu.cell("um_map") + k for k in range(6)] + \
        [emu.cell("userland_zp_buf"), emu.cell("userland_zp_buf") + 1, emu.cell("um_d030")]
    for k, a in enumerate(state):
        m[a] = 0x50 + k
    park = 0x1E00                                  # bank 0: kernel code here
    if kind == "nmi":
        user_code(emu, [0x4C, park & 0xFF, park >> 8], at=park)
        emu.schedule_nmi(5)
    else:
        user_code(emu, [0x00, 0x00], at=park)
    m[emu.cell("in_userland")] = 0
    emu.run_until(emu.sym(stop), start_at=park, max_cycles=100_000)
    assert [m[a] for a in state] == [0x50 + k for k in range(len(state))]
    at_stop_in_cse(emu)


def test_step_into_chain_runs_inside_the_handler(emu):
    ready(emu)
    #   $3000 LDX #3 · $3002 JSR $3010 · $3005 RTS ; $3010 INX · $3011 RTS
    user_code(emu, [0xA2, 0x03, 0x20, 0x10, 0x30, 0x60])
    user_code(emu, [0xE8, 0x60], at=USER + 0x10)
    m = emu.memory
    emu.write_word(emu.cell("brk_pc"), USER)
    m[emu.cell("step_state")] = STEP_INTO
    emu.jsr(emu.sym("step_next_pc"), b=CSE_BP)
    emu.jsr(emu.sym("arm_step_bp"), b=CSE_BP)
    emu.write_word(emu.cell("step_remaining"), 3)  # `t 4`: count - 1
    run_user(emu, USER)
    assert m[emu.cell("dbg_reason")] == DBG_BRK
    assert word(emu, "brk_pc") == USER + 5          # LDX, JSR, INX, RTS: back after the JSR
    assert regs(emu)["x"] == 4
    assert all(m.read_flat(a) == b for a, b in
               [(USER, 0xA2), (USER + 2, 0x20), (USER + 0x10, 0xE8), (USER + 0x11, 0x60)])


def test_user_pushes_survive_a_break_and_a_resume(emu):
    ready(emu)
    #   LDA #$5A · PHA · LDA #$A5 · PHA · BRK · PLA · STA $3100 · PLA · STA $3101 · RTS
    user_code(emu, [0xA9, 0x5A, 0x48, 0xA9, 0xA5, 0x48, 0x00, 0x00,
                    0x68, 0x8D, 0x00, 0x31, 0x68, 0x8D, 0x01, 0x31, 0x60])
    run_user(emu, USER)
    assert regs(emu)["sp"] == STACK_TOP - 4         # sentinel, two pushes
    emu.write_word(emu.cell("brk_pc"), USER + 8)   # past BRK + signature
    resume(emu)
    m = emu.memory
    assert m[emu.cell("dbg_reason")] == DBG_RTS
    assert (m.read_flat(0x3100), m.read_flat(0x3101)) == (0xA5, 0x5A)


def test_base_page_0_is_untouched_by_a_break(emu):
    ready(emu)
    m = emu.memory
    m.load(0, bytes((k * 37 + 11) & 0xFF for k in range(0x100)))
    # a fresh start writes the premise's SYSFLAGS ($00) through the
    # KERNAL, into its own cell here: the program's state, not a
    # clobber — so the snapshot is taken with it already $00
    emu.jsr(0xFF47, b=0, a=0x00, carry=False)
    emu.cpu.b = CSE_BP                             # kernel code runs with its own
    pattern = bytes(m.read_flat(k) for k in range(0x100))
    user_code(emu, [0x00, 0x00])
    run_user(emu, USER)
    assert bytes(m.read_flat(k) for k in range(0x100)) == pattern


# ── T9: the bank state ─────────────────────────────────────────────

CODE = 0x1800        # the program's own code in block 0, never mapped


def program(*, mapl=None, mb_lo=0, port=None, d030=None):
    """Bank as asked, BRK, then store what it reads back at $1700-$1707:
    the port (DDR, value), $D030, and $4000 as its map shows it."""
    c = []
    if mapl is not None:
        c += [0xA9, mb_lo, 0xA2, 0x0F, 0xA0, 0x00, 0xA3, 0x0F, 0x5C,   # megabytes
              0xA9, mapl & 0xFF, 0xA2, mapl >> 8, 0xA0, 0x00, 0xA3, 0x83, 0x5C, 0xEA]
    if d030 is not None:
        c += [0xA9, d030, 0x8D, 0x30, 0xD0]
    if port is not None:
        c += [0xA9, port, 0x85, 0x01]
    c += [0x00, 0x00]                                                    # BRK
    c += [0xA5, 0x00, 0x8D, 0x00, 0x17, 0xA5, 0x01, 0x8D, 0x01, 0x17]
    if port is not None:
        c += [0xA9, 0x35, 0x85, 0x01]                                    # I/O back in
    c += [0xAD, 0x30, 0xD0, 0x8D, 0x02, 0x17,
          0xAD, 0x00, 0x40, 0x8D, 0x03, 0x17, 0x60]
    return c


BANKINGS = {
    "own window": dict(mapl=0x4400),                    # block 2 -> 4.4000
    "attic megabyte": dict(mapl=0x4400, mb_lo=0x80),    # block 2 -> 804.4000
    "I/O banked out": dict(port=0x34),
    "D030": dict(d030=0x00),
    "all three": dict(mapl=0x4400, port=0x34, d030=0x00),
}


@pytest.mark.parametrize("name", BANKINGS)
def test_a_programs_bank_state_survives_a_break(emu, name):
    ready(emu)
    m = emu.memory
    b = BANKINGS[name]
    user_code(emu, program(**b), at=CODE)
    window = (b.get("mb_lo", 0) << 20) + 0x44000 if "mapl" in b else 0x4000
    m.write_flat(window, 0xC7)
    m.write_flat(0x4000, 0x3B)
    run_user(emu, CODE)
    assert m[emu.cell("dbg_reason")] == DBG_BRK
    at_stop_in_cse(emu)
    emu.write_word(emu.cell("brk_pc"), word(emu, "brk_pc") + 2)
    resume(emu)
    assert m[emu.cell("dbg_reason")] == DBG_RTS
    got = [m.read_flat(0x1700 + k) for k in range(4)]
    assert got[0:2] == [0xFF, b.get("port", PREMISE_PORT[1])]
    assert got[2] == b.get("d030", PREMISE_D030)
    assert got[3] == (0xC7 if "mapl" in b else 0x3B)


def test_a_fresh_start_takes_the_run_premises_bank_state(emu):
    ready(emu)
    m = emu.memory
    b = BANKINGS["all three"]
    user_code(emu, program(**b), at=CODE)
    run_user(emu, CODE)                            # breaks with the program's state
    user_code(emu, [0xA5, 0x01, 0x8D, 0x00, 0x17, 0xAD, 0x30, 0xD0, 0x8D, 0x01, 0x17,
                    0x00, 0x00])
    emu.cpu.sp = 0x100 | STACK_TOP
    run_user(emu, USER)                            # `j`: a fresh start
    assert (m.read_flat(0x1700), m.read_flat(0x1701)) == (PREMISE_PORT[1], PREMISE_D030)
    assert (emu.memory[emu.cell("um_map") + 0], emu.memory[emu.cell("um_map") + 2]) == \
        (USER_MAP[0] >> 8, USER_MAP[1] >> 8)


def _broken_program(cse_m65_prg, m65_snapshot):
    """A fresh machine with the "all three" program stopped at its BRK,
    set up for `c` (SP at the user's, brk_pc past the BRK)."""
    emu = M65Emu(m65_snapshot)
    emu.install_prg(*cse_m65_prg)
    ready(emu)
    emu.memory.write_flat(0x44000, 0xC7)
    user_code(emu, program(**BANKINGS["all three"]), at=CODE)
    run_user(emu, CODE)
    emu.write_word(emu.cell("brk_pc"), word(emu, "brk_pc") + 2)
    emu.cpu.sp = 0x100 | emu.memory[emu.cell("reg_sp")]
    return emu


def _transition_steps(emu):
    """The steps from restore_userland_state to the program's first
    instruction, and the first of them that runs with in_userland set
    (PLAT_TO_USER's first instruction)."""
    flag, target = emu.cell("in_userland"), word(emu, "brk_pc")
    emu.pc = emu.sym("restore_userland_state")
    first, k = None, 0
    while not (emu.pc == target and (emu.cpu.mapl, emu.cpu.maph) != CSE_MAP):
        if first is None and emu.memory[flag] & 0x80:
            first = k
        emu.cpu.step()
        k += 1
    return first, k


def test_an_nmi_anywhere_in_the_transition_is_resumable(cse_m65_prg, m65_snapshot):
    """Principle 7: an NMI at each instruction of the kernel -> user
    transition, from PLAT_TO_USER to stub_user's RTI, breaks; `c` then
    runs the program on as if nothing happened (platform_layer.md
    § User transitions)."""
    first, last = _transition_steps(_broken_program(cse_m65_prg, m65_snapshot))
    assert first is not None and last - first > 20
    for k in range(first, last + 1):
        emu = _broken_program(cse_m65_prg, m65_snapshot)
        m = emu.memory
        emu.schedule_nmi(k)
        emu.run_until(emu.sym("hygiene_after_userland"),
                      start_at=emu.sym("restore_userland_state"), max_cycles=300_000)
        if m[emu.cell("dbg_reason")] == DBG_NMI:
            resume(emu)                            # `c` after the NMI break
        assert m[emu.cell("dbg_reason")] == DBG_RTS, f"NMI at step {k}"
        got = [m.read_flat(0x1700 + i) for i in range(4)]
        assert got == [0xFF, 0x34, 0x00, 0xC7], f"NMI at step {k}: {got}"


# ── T6 (P2): the program's SYSFLAGS travel with its bank state ─────

SYSFLAGS = 0xFF47


def test_a_programs_sysflags_survive_a_break(emu):
    """The program sets SYSFLAGS $50 (No Scroll locked, GO64 locked),
    breaks, CSE runs with its own bits (raw F-keys, Mega+Shift
    locked), and after `c` the program reads its $50 back."""
    ready(emu)
    m = emu.memory
    #   LDA #$50 · CLC · JSR SYSFLAGS · BRK · SEC · JSR SYSFLAGS · STA $1700 · RTS
    user_code(emu, [0xA9, 0x50, 0x18, 0x20, 0x47, 0xFF, 0x00, 0x00,
                    0x38, 0x20, 0x47, 0xFF, 0x8D, 0x00, 0x17, 0x60], at=CODE)
    run_user(emu, CODE)
    assert m[emu.cell("dbg_reason")] == DBG_BRK
    assert m[emu.cell("um_sysflags")] == 0x50
    emu.jsr(emu.sym("hygiene_after_userland"), b=CSE_BP)
    emu.jsr(SYSFLAGS, b=0, carry=True)
    assert emu.a & 0xA0 == 0xA0                    # CSE's, while it reads keys
    emu.write_word(emu.cell("brk_pc"), word(emu, "brk_pc") + 2)
    resume(emu)
    assert m[emu.cell("dbg_reason")] == DBG_RTS
    assert m.read_flat(0x1700) == 0x50


def test_a_fresh_start_gets_the_premises_sysflags(emu):
    ready(emu)
    emu.jsr(SYSFLAGS, b=0, a=0xF0, carry=False)    # whatever CSE had
    emu.cpu.b = CSE_BP
    #   SEC · JSR SYSFLAGS · STA $1700 · RTS
    user_code(emu, [0x38, 0x20, 0x47, 0xFF, 0x8D, 0x00, 0x17, 0x60], at=CODE)
    run_user(emu, CODE)
    assert emu.memory.read_flat(0x1700) == 0x00
