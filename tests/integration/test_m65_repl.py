"""test_m65_repl.py — the cold start, the REPL and the debugger typed on the m65 PRG (P2 T7 T8 T9).

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
"""

import re

import pytest

from m65emu import M65Emu
from m65emu.harness import CSE_BP, flat
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


SPLASH_FREE = ["; low  0.1600-1eff  2304b free",
               "; work 0.2000-bfff 40960b free",
               "; ext  1.2000-f6ff 55040b free",
               "; ext  4.0000-ffff 65536b free",
               "; ext  5.0000-ffff 65536b free"]


def test_splash_and_prompt_at_80x25(s):
    rows = s.rows()
    assert rows[15].startswith("; cse v")
    assert rows[17:22] == SPLASH_FREE
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
    s.find(r"^2000:\.  a9 01     lda #\$01$")
    s.type("@ $2000")
    s.type("d")
    s.find(r"^2000:\.  a9 01     lda #\$01$")


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


INFO = ["; low  0.1600-1eff  2304b free",
        "; cse  0.1f00-1fff page",
        "; work 0.2000-bfff 40960b free",
        "; ext  1.2000-f6ff 55040b free",
        "; cse  3.2000-7fff code",
        "; cse  3.8000-bfff data",
        "; ext  4.0000-ffff 65536b free",
        "; ext  5.0000-ffff 65536b free"]


def test_i_prints_the_m65_rows_with_their_banks(s):
    s.type("i")
    k, _ = s.find(r"^; low  0\.1600")
    assert s.rows()[k:k + len(INFO)] == INFO
    assert s.row(k + len(INFO)) == "2000:"


def test_i_in_80x50_has_no_bank_4_row(s):
    """Bank 4 holds the 80 x 50 screen (4.0800-4.179F); bank 5 stays
    free — measured: the KERNAL's 80 x 50 writes nothing else there."""
    s.mode("5")
    s.type("i")
    k, _ = s.find(r"^; low  0\.1600")
    assert s.rows()[k:k + 7] == INFO[:6] + INFO[7:]
    assert s.row(k + 7) == "2000:"


def test_i_shows_a_loaded_source_in_bank_2(s):
    s.call("ed_ensure_init")
    for ch in b" nop\r":
        s.call("gb_insert", a=ch)
    lo, hi = s.w("src_bot"), s.w("src_top")
    assert 0x4000 <= lo < hi <= 0xC000           # the source region's offsets
    s.type("i")
    k, _ = s.find(rf"^; src  2\.{lo:04x}-{hi - 1:04x} ")
    assert s.row(k - 1) == INFO[3] and s.row(k + 1) == INFO[4]   # in bank order


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
    assert rows[h - 2] == "3001:.  ea        eom"
    s.type("t")
    rows = s.rows()
    assert rows[h - 1] == "3002:"
    assert rows[h - 2 - panel] == "3001:.  ea        eom"   # the pre-step row
    assert rows[h - 3 - panel].startswith("2000:j $3000")
    assert rows[h - 1 - panel] == "; brk at $3002"
    assert rows[h - 2] == "3002:.  e8        inx"


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
    s.find(r"^3000:\.  a9 07     lda #\$07$")


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
