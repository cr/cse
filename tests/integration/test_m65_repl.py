"""test_m65_repl.py — the cold start, the REPL and the debugger typed on the m65 PRG.

Owner: doc/modules/repl.md

Contract source: [doc/modules/repl.md](../../doc/modules/repl.md) (*By
width*, § Emitters, § `i` — Memory map, *On m65*),
[doc/modules/main.md § Layer 1](../../doc/modules/main.md#layer-1-_main-cold-init-one-time-setup)
(the m65 steps), [doc/modules/debugger.md § dbg_reason × command matrix](../../doc/modules/debugger.md#dbg_reason--command-matrix)
and § Break panel; [doc/platform_layer.md § Info map](../../doc/platform_layer.md#info-map).

The debug m65 PRG installed on each post-boot snapshot and started at
`_main`, as the loader leaves it.  `M65Session` is the C64 suites'
Session on M65Emu: a command is written after the 5-column prompt in
the mode's screen and RETURN goes through the hardware typing queue;
`idle()` runs until main_loop polls with no key waiting.  The screen
is read where the VIC-IV shows it.

- T7: the cold start reaches main_loop_top with no cse_brk_handler and
  no cse_recover on the way (Principle 16's watchers); the splash and
  the prompt at 80 x 25.
- T8: `?`, `m` (16 bytes a row in 80 columns, 8 in 40; edits past 8),
  `.`, `d`, `r` (one row in 80, two in 40, each re-executing), `i`
  (the m65 rows, `b.aaaa-bbbb`), an 80-column command line, ESC 4 / 5
  / 8 at the prompt, the break panel and `t`'s re-print in both widths.
- T9: `j`, `g`, `c`, `t`, `o`, `b`, `r`, `d` typed, and the
  dbg_reason x command matrix through the REPL.
(P2's T7-T9.)  P4: the cold start selects the 45GS02; `u` and `.cpu`
take the m65 set (T6); `d` / `.` rows have five byte columns, `.`
re-entry keeps a 16-bit branch's width (T8).
"""

import re

import pytest

from m65emu import M65Emu
from m65emu.harness import TEXT_MODES, CSE_BP, flat
from test_kernel_transition import _local_after, _scr

DBG_NONE, DBG_RTS, DBG_BRK = 0, 1, 2     # src/dbg_reason.inc
ESC, RETURN = 0x1B, 0x0D
USER = 0x3000                            # user code, bank 0


class M65Session:
    """Cold start from `_main`, then commands typed on the prompt row."""

    def __init__(self, prg, snapshot):
        prg_path, map_path = prg
        e = self.e = M65Emu(snapshot)
        e.install_prg(prg_path, map_path)
        self.WAIT = _local_after(map_path, "main_loop", "@wait")
        self.cold_hits = e.run_until_with_watch(
            e.sym("main_loop_top"), [e.sym("cse_brk_handler"), e.sym("cse_recover")],
            max_cycles=5_000_000)
        self.idle()

    # ── CSE's cells (under the CSE map) ──
    def cell(self, name):
        return self.e.cell(name)

    def v(self, name):
        return self.e.memory[self.cell(name)]

    def w(self, name):
        a = self.cell(name)
        return self.e.memory[a] | self.e.memory[a + 1] << 8

    def call(self, name, **regs):
        """jsr a CSE routine from the idle main_loop (B = CSE_BP), then
        put PC and SP back."""
        cpu = self.e.cpu
        pc, sp = cpu.pc, cpu.sp
        self.e.jsr(self.e.sym(name), b=CSE_BP, **regs)
        cpu.pc, cpu.sp = pc, sp

    # ── the user's memory (bank 0) ──
    def poke(self, addr, data):
        for k, b in enumerate(data):
            self.e.memory.write_flat(flat(0, addr + k), b)

    def peek(self, addr, n=1):
        return [self.e.memory.read_flat(flat(0, addr + k)) for k in range(n)]

    # ── the screen ──
    @property
    def width(self):
        return self.v("scr_width")

    @property
    def height(self):
        return self.v("scr_height")

    def row(self, r):
        return self.e.screen_text(r)

    def rows(self):
        return [self.row(r) for r in range(self.height)]

    def screen(self):
        return "\n".join(self.rows())

    def write_row(self, r, text, col=0):
        base = flat(self.v("scr_bank"), 0x0800 + r * self.width)
        for k in range(col, self.width):
            self.e.memory.write_flat(base + k, 0x20)
        for k, ch in enumerate(text):
            self.e.memory.write_flat(base + col + k, _scr(ch))

    # ── driving main_loop ──
    def idle(self, max_steps=3_000_000):
        """Run until main_loop polls with no key waiting — through the
        harness's run loop, so its traps (the virtual drive's) serve."""
        e, cpu = self.e, self.e.cpu
        key = self.cell("io_key")
        end = e._steps + max_steps
        while not (cpu.pc == self.WAIT and not e.keyboard.queue and e.memory[key] == 0):
            if e._steps >= end:
                raise TimeoutError(f"main_loop not idle, pc=${cpu.pc:04X}")
            if cpu.pc == self.WAIT:
                e.run_steps(1)                  # on past the poll
            try:
                e.run_until(self.WAIT, max_cycles=max(1, end - e._steps))
            except TimeoutError:
                raise TimeoutError(f"main_loop not idle, pc=${cpu.pc:04X}") from None

    def keys(self, data, **kw):
        self.e.inject_keys(data)
        self.idle(**kw)

    def start(self, cmd):
        """Write `cmd` after the prompt and queue RETURN."""
        r = self.v("io_cy")
        self.write_row(r, cmd, col=5)
        self.e.memory[self.cell("io_cx")] = 5 + len(cmd)
        self.e.inject_key(RETURN)

    def type(self, cmd, **kw):
        self.start(cmd)
        self.idle(**kw)

    def enter_on(self, r):
        """RETURN on screen row `r` (a row recalled by cursor-up)."""
        self.e.memory[self.cell("io_cy")] = r
        self.e.memory[self.cell("io_cx")] = 0
        self.keys(bytes([RETURN]))

    def mode(self, key):
        self.keys(bytes([ESC, ord(key)]))

    def find(self, pattern):
        """The last row matching `pattern` (a regex), as (index, text)."""
        hits = [(k, t) for k, t in enumerate(self.rows()) if re.search(pattern, t)]
        assert hits, f"no row matches {pattern!r}:\n{self.screen()}"
        return hits[-1]


@pytest.fixture
def s(cse_m65_prg, m65_snapshot):
    return M65Session(cse_m65_prg, m65_snapshot)


def mode40(s):
    s.mode("4")
    assert s.width == 40


# ── T7: the cold start ─────────────────────────────────────────────

def test_cold_start_reaches_the_prompt_without_recovery(s):
    assert s.cold_hits == [], "cold start went through cse_brk_handler / cse_recover"
    assert (s.width, s.height) == (80, 25)


SPLASH_FREE = ["; zp   0.000a-008f   134b free",
               "; zp   0.00fb-00ff     5b free",
               "; low  0.1600-1eff  2304b free",
               "; work 0.2000-bfff 40960b free",
               "; ext  1.2000-f6ff 55040b free",
               "; ext  4.0000-ffff 65536b free",
               "; ext  5.0000-ffff 65536b free"]


def test_splash_and_prompt_at_80x25(s):
    rows = s.rows()
    assert rows[13].startswith("; cse v")
    assert rows[15:22] == SPLASH_FREE
    assert rows[23].startswith("; man: ")
    assert rows[24] == "2000:"
    assert (s.v("io_cy"), s.v("io_cx")) == (24, 5)


# ── T8: the REPL typed ─────────────────────────────────────────────

def test_print_expression(s):
    s.type("? 1+2")
    s.find(r"^;   \$03      3  %00000011  \+3$")


def test_m_row_is_16_bytes_in_80_columns(s):
    s.poke(0x2000, range(0x30, 0x40))
    s.type("m")
    k, row = s.find(r"^2000:m")
    assert row == "2000:m " + " ".join(f"{b:02x}" for b in range(0x30, 0x40)) \
        + ";0123456789:;<=>?"
    assert s.row(k + 1) == "2010:"
    assert s.w("cur_addr") == 0x2010


def test_m_row_is_8_bytes_in_40_columns(s):
    mode40(s)
    s.poke(0x2000, range(0x30, 0x40))
    s.type("m")
    k, _ = s.find(r"^2000:m")
    assert s.row(k) == "2000:m 30 31 32 33 34 35 36 37;01234567"
    assert s.row(k + 1) == "2008:m 38 39 3a 3b 3c 3d 3e 3f;89:;<=>?"


def test_m_edit_takes_16_bytes_in_80_columns(s):
    data = list(range(1, 17))
    s.type("m " + " ".join(f"{b:02x}" for b in data))
    assert s.peek(0x2000, 16) == data
    assert s.w("cur_addr") == 0x2010


def test_m_edit_takes_more_than_8_bytes_in_40_columns(s):
    mode40(s)
    data = list(range(1, 12))                      # 11 bytes: the row's 40 columns
    s.type("m " + " ".join(f"{b:02x}" for b in data))
    assert s.peek(0x2000, 11) == data
    assert s.w("cur_addr") == 0x200B


def test_an_80_column_m_row_re_executes(s):
    """read_line takes all 80 columns into line_buf: the 16th byte,
    at columns 52-53, is written back."""
    s.type("m")
    k, row = s.find(r"^2000:m")
    s.write_row(k, row[:52] + "ff" + row[54:])
    s.enter_on(k)
    assert s.peek(0x200F) == [0xFF]


def test_dot_assembles_and_d_disassembles(s):
    s.type(". lda #$01")
    assert s.peek(0x2000, 2) == [0xA9, 0x01]
    s.find(r"^2000:\.  a9 01           lda #\$01$")
    s.type("@ $2000")
    s.type("d")
    s.find(r"^2000:\.  a9 01           lda #\$01$")


REG80 = r"^r pc:[0-9a-f]{4} a:[0-9a-f]{2} x:[0-9a-f]{2} y:[0-9a-f]{2} " \
        r"z:([0-9a-f]{2}) b:([0-9a-f]{2}) s:[0-9a-f]{2} [nvbdizcNVBDIZC-]{8}$"
REG40 = r"^r pc:[0-9a-f]{4} a:[0-9a-f]{2} x:[0-9a-f]{2} y:[0-9a-f]{2} " \
        r"s:[0-9a-f]{2} [nvbdizcNVBDIZC-]{8}$"


def test_r_is_one_row_in_80_columns_and_re_executes(s):
    s.type("r a:05 z:07 b:09")
    k, row = s.find(REG80)
    assert re.match(REG80, row).groups() == ("07", "09")
    assert (s.v("reg_a"), s.v("reg_z"), s.v("reg_b")) == (5, 7, 9)
    s.write_row(k, row.replace("z:07", "z:11"))
    s.enter_on(k)
    assert s.v("reg_z") == 0x11


def test_r_is_two_rows_in_40_columns_each_re_executing(s):
    mode40(s)
    s.type("r z:07 b:09")
    k, _ = s.find(REG40)
    assert s.row(k + 1) == "r z:07 b:09"
    s.write_row(k + 1, "r z:21 b:22")
    s.enter_on(k + 1)
    assert (s.v("reg_z"), s.v("reg_b")) == (0x21, 0x22)
    k, row = s.find(REG40)
    s.write_row(k, re.sub(r"a:..", "a:33", row))
    s.enter_on(k)
    assert s.v("reg_a") == 0x33


INFO = ["; zp   0.000a-008f   134b free",
        "; zp   0.00fb-00ff     5b free",
        "; low  0.1600-1eff  2304b free",
        "; cse  0.1f00-1fff base",
        "; work 0.2000-bfff 40960b free",
        "; ext  1.2000-f6ff 55040b free",
        "; cse  3.2000-7fff code",
        "; cse  3.8000-bfff data",
        "; ext  4.0000-ffff 65536b free",
        "; ext  5.0000-ffff 65536b free"]


def test_i_prints_the_m65_rows_with_their_banks(s):
    s.type("i")
    k, _ = s.find(r"^; zp   0\.000a")
    assert s.rows()[k:k + len(INFO)] == INFO
    assert s.row(k + len(INFO)) == "2000:"


def test_i_in_80x50_has_no_bank_4_row(s):
    """Bank 4 holds the 80 x 50 screen (4.0800-4.179F); bank 5 stays
    free — measured: the KERNAL's 80 x 50 writes nothing else there."""
    s.mode("5")
    s.type("i")
    k, _ = s.find(r"^; zp   0\.000a")
    assert s.rows()[k:k + 9] == INFO[:8] + INFO[9:]
    assert s.row(k + 9) == "2000:"


def test_i_shows_a_loaded_source_in_bank_2(s):
    s.call("ed_ensure_init")
    for ch in b" nop\r":
        s.call("gb_insert", a=ch)
    lo, hi = s.w("src_bot"), s.w("src_top")
    assert 0x4000 <= lo < hi <= 0xC000           # the source region's offsets
    s.type("i")
    k, _ = s.find(rf"^; src  2\.{lo:04x}-{hi - 1:04x} ")
    assert s.row(k - 1) == INFO[5] and s.row(k + 1) == INFO[6]   # in bank order


@pytest.mark.parametrize("key,width,height", [("4", 40, 25), ("5", 80, 50), ("8", 80, 25)])
def test_esc_mode_at_the_prompt_clears_and_prompts(s, key, width, height):
    s.type("? 1")
    s.mode(key)
    assert (s.width, s.height) == (width, height)
    rows = s.rows()
    assert rows[height - 1] == "2000:"
    assert all(t == "" for t in rows[:height - 1])
    s.type("? 2")                                  # the REPL goes on in the mode
    s.find(r"^;   \$02")


def test_esc_alone_still_refreshes(s):
    s.type("? 1")
    s.keys(bytes([ESC]))
    assert s.rows()[24] == "2000:"
    s.type("? 2")
    s.find(r"^;   \$02")


@pytest.mark.parametrize("key,panel", [("8", 3), ("4", 4)])
def test_break_panel_and_t_re_print(s, key, panel):
    """The panel is tag, `r` (one row in 80 columns, two in 40) and
    disassembly; `t` moves up by the panel's height, so the pre-step
    row overwrites the tag row and nothing of the old panel stays."""
    if key != "8":
        s.mode(key)
    s.poke(USER, [0xEA, 0xEA, 0xE8, 0xEA, 0x60])   # NOP NOP INX NOP RTS
    s.type("b $3001")
    s.type("j $3000")
    rows = s.rows()
    h = s.height
    assert rows[h - 1] == "3001:"
    assert rows[h - 2 - panel] .startswith("2000:j $3000")
    assert rows[h - 1 - panel] == "; brk 1 at $3001"
    assert rows[h - 2] == "3001:.  ea              eom"
    s.type("t")
    rows = s.rows()
    assert rows[h - 1] == "3002:"
    assert rows[h - 2 - panel] == "3001:.  ea              eom"   # the pre-step row
    assert rows[h - 3 - panel].startswith("2000:j $3000")
    assert rows[h - 1 - panel] == "; brk at $3002"
    assert rows[h - 2] == "3002:.  e8              inx"


# ── T9: the debugger typed, the matrix through the REPL ───────────

def test_j_runs_to_rts(s):
    s.poke(USER, [0xE8, 0x60])                      # INX RTS
    s.type("j $3000")
    assert s.v("dbg_reason") == DBG_RTS and s.v("reg_x") == 1
    s.find(r"^; rts$")


def test_g_runs_at_cur_addr_without_main(s):
    s.poke(USER, [0xC8, 0x60])                      # INY RTS
    s.type("@ $3000")
    s.type("g")
    assert s.v("dbg_reason") == DBG_RTS and s.v("reg_y") == 1


def test_user_brk_panel_and_c_skips_it(s):
    s.poke(USER, [0xEA, 0x00, 0x42, 0xE8, 0x60])    # NOP BRK $42 INX RTS
    s.type("j $3000")
    assert s.v("dbg_reason") == DBG_BRK and s.w("brk_pc") == 0x3001
    s.find(r"^; brk at \$3001$")
    s.find(REG80)
    s.type("c")
    assert s.v("dbg_reason") == DBG_RTS and s.v("reg_x") == 1


def test_b_list_and_bp_hit_then_c_deletes_it(s):
    s.poke(USER, [0xEA, 0xE8, 0x60])                # NOP INX RTS
    s.type("b $3001")
    s.find(r"^; bp 1: \$3001$")
    s.type("j $3000")
    assert s.w("brk_pc") == 0x3001
    s.type("c")
    assert s.v("dbg_reason") == DBG_RTS and s.v("reg_x") == 1
    assert s.peek(0x3001) == [0xE8]


def test_b_outside_the_program_region_is_range(s):
    s.type("b $1800")
    s.find(r"^;\?range$")


def test_o_steps_over_a_jsr(s):
    s.poke(USER, [0x20, 0x10, 0x30, 0xE8, 0x60])    # JSR $3010; INX; RTS
    s.poke(0x3010, [0xC8, 0x60])                    # INY; RTS
    s.type("b $3000")
    s.type("j $3000")
    s.type("o")
    assert s.v("dbg_reason") == DBG_BRK and s.w("brk_pc") == 0x3003
    assert s.v("reg_y") == 1


def test_t_steps_into_a_jsr(s):
    s.poke(USER, [0x20, 0x10, 0x30, 0xE8, 0x60])
    s.poke(0x3010, [0xC8, 0x60])
    s.type("b $3000")
    s.type("j $3000")
    s.type("t")
    assert s.w("brk_pc") == 0x3010


def test_r_set_reaches_the_program(s):
    s.poke(USER, [0x8D, 0x00, 0x31, 0x60])          # STA $3100; RTS
    s.type("r a:5a")
    s.type("j $3000")
    assert s.peek(0x3100) == [0x5A]


def test_d_after_a_break_shows_the_users_bytes(s):
    s.poke(USER, [0xA9, 0x07, 0x00, 0x00])          # LDA #$07; BRK
    s.type("j $3000")
    s.type("@ $3000")
    s.type("d")
    s.find(r"^3000:\.  a9 07           lda #\$07$")


# the matrix (debugger.md § dbg_reason x command matrix)

def test_c_without_a_session_is_no_ctx(s):
    s.type("c")
    s.find(r"^;\?no ctx$")
    assert s.v("dbg_reason") == DBG_NONE


def test_c_after_rts_is_no_ctx(s):
    s.poke(USER, [0x60])
    s.type("j $3000")
    s.type("c")
    s.find(r"^;\?no ctx$")


def test_t_without_a_session_is_a_cold_preview(s):
    s.poke(USER, [0xE8, 0x60])
    s.type("@ $3000")
    s.type("t")
    assert s.v("dbg_reason") == DBG_BRK
    s.find(r"^; dbg at \$3000$")
    s.type("c")                                     # a fresh start
    assert s.v("dbg_reason") == DBG_RTS and s.v("reg_x") == 1


def test_t_after_rts_is_no_ctx(s):
    s.poke(USER, [0x60])
    s.type("j $3000")
    s.type("t")
    s.find(r"^;\?no ctx$")


@pytest.mark.parametrize("cmd", ["j $3000", "g"])
def test_j_g_in_a_session_ask(s, cmd):
    s.poke(USER, [0xEA, 0x00, 0x00, 0x60])
    s.type("j $3000")
    assert s.v("dbg_reason") == DBG_BRK
    s.start(cmd)                                    # the query waits for its key
    s.keys(b"N")
    s.find(r"^;!go\? y/n")
    assert s.v("dbg_reason") == DBG_BRK and s.w("brk_pc") == 0x3001


def test_j_in_a_session_y_ends_it_and_runs(s):
    s.poke(USER, [0xEA, 0x00, 0x00, 0x60])
    s.poke(0x3010, [0xE8, 0x60])
    s.type("j $3000")
    s.start("j $3010")
    s.keys(b"Y")
    assert s.v("dbg_reason") == DBG_RTS and s.v("reg_x") == 1


# ── P4 T4: the m65-45gs02 build starts as a 45GS02 ─────────────────

def test_the_cold_start_selects_the_45gs02(s):
    """DEFAULT_CPU = 4 (build_system.md § Builds and CPU sets)."""
    assert s.v("asm_cpu") == 4


# ── P4 T6, P4b T3: `.cpu` and `u` on m65 — the set {6502, 4510, 45gs02} ──

import asm_dasm_runner as _R
M65_SET = list(_R.MT.CPU_SETS["45gs02"][1])


@pytest.mark.parametrize("name,value", [("6502", 0), ("4510", 3), ("45gs02", 4),
                                        ("6510", None), ("65c02", None)])
def test_u_selects_the_m65_set(s, name, value):
    """From the cold default 4: a member selects itself, the 6510 and the
    65C02 are refused and 4 stays; the listing marks the active one."""
    s.type(f"u {name}")
    active = 4 if value is None else value
    assert s.v("asm_cpu") == active
    mark = M65_SET[[0, 3, 4].index(active)]
    rows = [r for r in s.rows() if r.startswith("; cpu:")]
    assert rows[-1].rstrip() == "; cpu: " + " ".join(n + "*" * (n == mark) for n in M65_SET)


def test_u_lists_the_set_with_the_active_one_marked(s):
    s.type("u")
    s.find(r"^; cpu: 6502 4510 45gs02\*$")


@pytest.mark.parametrize("name,errors", [("6502", 3), ("4510", 1), ("45gs02", 0),
                                         ("6510", 1), ("65c02", 1)])
def test_cpu_directive_on_m65(s, name, errors):
    """`.cpu` governs the lines after it: `stz` and `taz` from the 4510,
    `ldq` on the 45GS02 only; the 6510 and the 65C02 are one error each
    and the assembly stays at 45gs02."""
    s.call("ed_ensure_init")
    src = f"\xa0.cpu {name}\r\xa0.org $3000\r\xa0stz $12\r\xa0taz\r\xa0ldq $12\r"
    for ch in src.upper().encode("latin-1"):
        s.call("gb_insert", a=ch)
    s.type("a", max_steps=6_000_000)
    assert s.w("asm_errors") == errors
    assert s.v("asm_cpu") == 4                     # the REPL's CPU is kept
    if errors == 0:
        assert s.peek(USER, 7) == [0x64, 0x12, 0x4B, 0x42, 0x42, 0xA5, 0x12]


# ── P4 T8: the REPL's rows on m65 — five byte columns (D-P4-1, D-P4-2) ──

@pytest.mark.parametrize("name", list(TEXT_MODES))
def test_d_rows_have_five_columns_and_fit_40(s, name):
    key = TEXT_MODES[name][0]
    if name != "80x25":
        s.mode(key)
    s.poke(USER, [0xE2, 0x12, 0x42, 0x42, 0xEA, 0xB2, 0x10])   # lda ($12,sp),y; ldq [$10],z
    s.type("@ $3000")
    s.type("d")
    k, row = s.find(r"^3000:\.  e2 12           lda \(\$12,sp\),y$")
    assert len(row) == 38 and row.index("lda") == 24      # 24 + `lda ($12,sp),y` (14)
    assert s.row(k + 1) == "3002:.  42 42 ea b2 10  ldq [$10],z"


def test_dot_pokes_five_bytes(s):
    s.type("@ $3000")
    s.type(". 42 42 ea b2 10")
    assert s.peek(0x3000, 5) == [0x42, 0x42, 0xEA, 0xB2, 0x10]
    s.find(r"^3000:\.  42 42 ea b2 10  ldq \[\$10\],z$")


@pytest.mark.parametrize("raw", [
    [0xD3, 0x02, 0x00],                 # bne, 16 bits, target in reach
    [0x83, 0x05, 0x00],                 # bra, 16 bits
    [0x42, 0x42, 0xEA, 0xB2, 0x10],     # ldq [$10],z
    [0x42, 0x42, 0x72, 0x12],           # adcq ($12)
    [0xE2, 0x12], [0xF4, 0x34, 0x12], [0x37, 0x12], [0xFF, 0x12, 0x02],
    [0x1A], [0x42, 0x42, 0x0A],         # inc (bare), aslq
])
def test_return_on_an_unchanged_d_row_writes_the_same_bytes(s, raw):
    s.poke(USER, raw + [0xEA] * 5)
    s.type("@ $3000")
    s.type("d")
    k, row = s.find(r"^3000:\.")
    s.enter_on(k)                       # the bytes match: mode 2 re-assembles
    assert s.peek(USER, len(raw) + 1) == raw + [0xEA]
    assert s.w("cur_addr") == USER + len(raw)    # and it ran: the next row


def test_a_typed_branch_takes_the_usual_width(s):
    s.type("@ $3000")
    s.type(". bne $3004")
    assert s.peek(USER, 2) == [0xD0, 0x02]


def test_an_edited_16_bit_row_keeps_its_width(s):
    """The bytes still match, so the edited text is assembled as REL16
    (repl.md § The `.` command, mode 2), even in reach."""
    s.poke(USER, [0xD3, 0x02, 0x00])
    s.type("@ $3000")
    s.type(". d3 02 00 bne $3010")
    assert s.peek(USER, 3) == [0xD3, 0x0E, 0x00]          # $3010 - ($3000 + 2)


def test_a_refused_re_entry_drops_the_width_request(s):
    """An operand refused before asm_line runs leaves no REL16 request
    behind for the next line."""
    s.poke(USER, [0xD3, 0x02, 0x00])
    s.type("@ $3000")
    s.type(". d3 02 00 bne nosuchlabel")
    s.type("@ $3100")
    s.type(". bne $3104")
    assert s.peek(0x3100, 2) == [0xD0, 0x02]


@pytest.mark.parametrize("text,raw", [
    (". rmb3 $12", [0x37, 0x12]),
    (". ldq ($12),z", [0x42, 0x42, 0xB2, 0x12]),
    (". staq $1234", [0x42, 0x42, 0x8D, 0x34, 0x12]),
    (". lda [$12],z", [0xEA, 0xB2, 0x12]),
    (". lda ($12,sp),y", [0xE2, 0x12]),
])
def test_dot_assembles_the_m65_forms(s, text, raw):
    s.type("@ $3000")
    s.type(text)
    assert s.peek(USER, len(raw)) == raw


# ── the program's base page (userland_contract.md § 3 On m65, Zero page) ──

USER_BP = [*range(0x0A, 0x90), *range(0xFB, 0x100)]   # $0A-$8F, $FB-$FF


def fill_user_bp(s):
    """A pattern in the program's base-page cells; returns it."""
    pat = {a: (a * 37 + 0x5B) & 0xFF for a in USER_BP}
    for a, v in pat.items():
        s.poke(a, [v])
    return pat


def user_bp(s):
    return {a: s.peek(a)[0] for a in USER_BP}


def test_a_session_leaves_the_programs_base_page_alone(s):
    """$0A-$8F and $FB-$FF are the program's: through output, `i`, `m`,
    `d`, `.`, a run that calls BSOUT, steps, the 80 x 50 switch and the
    editor, neither CSE nor the KERNAL writes them."""
    pat = fill_user_bp(s)
    s.poke(USER, [0xA9, 0x48, 0x20, 0xD2, 0xFF, 0x60])   # LDA #'H' · JSR BSOUT · RTS
    for cmd in ["i", "m 2000", "? 1+2", "@ $2000", ". lda #1",
                f"@ ${USER:x}", "d", f"@ ${USER:x}", "t", "t", "t"]:
        s.type(cmd)
    s.find(rf"^; brk at \${USER + 5:04x}")                 # stepped over the JSR
    s.type("c")
    k, _ = s.find(r"^; rts")                              # and ran through BSOUT
    assert re.match(r"r pc:.... a:48 ", s.row(k + 1))      # to its RTS
    s.mode("5")
    s.type("i")
    s.mode("8")
    s.keys(bytes([0x03]))                                 # into the editor
    s.keys(b"AB\r")
    s.keys(bytes([0x03]))                                 # and out
    assert user_bp(s) == pat


# ── `a`'s save line names the project (slice 3 F0's Escape Analysis) ──

def test_assembly_save_line_names_the_project(s):
    """The save line `a` prints carries the project name.  On m65 the
    name was read in bank 3 at its base-page address (3.1F90, the
    monitor ROM): the row filled with garbage."""
    from test_m65_source_editor import put_source
    put_source(s, b" .ORG $3000\r NOP\r")
    name = s.cell("cur_project_name")     # as `l "proj"` leaves it
    for k, c in enumerate(b"PROJ\0"):
        s.e.memory[name + k] = c
    s.type("a")
    k, row = s.find(r"^3000:s ")
    assert row.rstrip() == '3000:s "proj" $3000'
