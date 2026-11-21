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
re-entry keeps a 16-bit branch's width (T8).  Slice 3 (repl.md § Banks):
flat addresses, the map in `r` and `M`, far starts, flat breakpoints
(F1-F4); `?` in 32 bits and `;?expr range` (F5a); `g` far-starting a
flat `main`, `.` and the same-bank rule, RESTORE leaving no bank (F5b);
the address arguments of `@`, `j`, `b` and `m` as 32-bit expressions,
flat when their width is FAR (F5c).  `.` hands its line to asm_line:
the accumulator form (`asl a`), `*` as the instruction's address, an
undefined operand as `;?expr undef` (repl.md § The `.` command in
detail).
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
        """Write `cmd` after the prompt (where the cursor waits: `AAAA:`
        or a flat `H.AAAA:`) and queue RETURN."""
        r, c = self.v("io_cy"), self.v("io_cx")
        self.write_row(r, cmd, col=c)
        self.e.memory[self.cell("io_cx")] = c + len(cmd)
        self.e.inject_key(RETURN)

    def line(self, text, **kw):
        """Write `text` over the whole prompt row — a row with its own
        address prefix, as a recalled row is — and RETURN on it."""
        r = self.v("io_cy")
        self.write_row(r, text, col=0)
        self.e.memory[self.cell("io_cx")] = len(text)
        self.e.inject_key(RETURN)
        self.idle(**kw)

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
        r"z:([0-9a-f]{2}) b:([0-9a-f]{2}) s:[0-9a-f]{2} [nvbdizcNVBDIZC-]{8}" \
        r" ml:[0-9a-f]{4} mh:[0-9a-f]{4}$"            # the MAP (slice 3, F2)
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
    assert s.row(k + 1) == "r z:07 b:09 ml:e000 mh:8300"
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
    s.find(r"^; bp 1: 0\.3001$")              # a physical byte (slice 3, F4)
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


# ── the program's base page (userland_contract.md § 3 On m65: memory regions, Zero page) ──

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


# ── flat addresses (slice 3, F1: repl.md § Banks) ──────────────────

def fpeek(s, bank, addr, n=1):
    return [s.e.memory.read_flat(flat(bank, addr + k)) for k in range(n)]


def fpoke(s, bank, addr, data):
    for k, b in enumerate(data):
        s.e.memory.write_flat(flat(bank, addr + k), b)


def prompt(s):
    return s.row(s.v("io_cy")).rstrip()


def test_at_a_flat_literal_makes_the_prompt_flat(s):
    s.type("@ 4.2000")
    assert prompt(s) == "4.2000:"
    s.type("@ $2000")
    assert prompt(s) == "2000:"


def test_a_flat_prefix_edits_and_dumps_the_bank(s):
    s.line("4.2000:m 11 22")
    assert fpeek(s, 4, 0x2000, 2) == [0x11, 0x22]
    assert fpeek(s, 0, 0x2000, 2) != [0x11, 0x22]        # not bank 0
    fpoke(s, 4, 0x2002, range(0x41, 0x4F))
    s.line("4.2000:m")
    k, row = s.find(r"^4\.2000:m ")
    assert row == '4.2000:m 11 22 41 42 43 44 45 46 47 48 49 4a 4b 4c 4d 4e;."abcdefghijklmn'
    assert s.row(k + 1).rstrip() == "4.2010:"
    s.write_row(k, row.replace("11 22", "33 44", 1))
    s.enter_on(k)                                         # the row re-executes
    assert fpeek(s, 4, 0x2000, 2) == [0x33, 0x44]


def test_bank_1_is_reached_too(s):
    s.line("1.2000:m 5a")
    assert fpeek(s, 1, 0x2000) == [0x5A]


def test_dot_assembles_into_a_bank_at_the_low_word(s):
    s.type("@ 4.2000")
    s.type(". lda #$01")
    s.type(". bne $2000")                   # from $2004, the low word: -4
    assert fpeek(s, 4, 0x2000, 4) == [0xA9, 0x01, 0xD0, 0xFC]
    assert prompt(s) == "4.2004:"


def test_d_lists_a_bank_with_branches_in_the_low_word(s):
    fpoke(s, 4, 0x2000, [0xA9, 0x01, 0xD0, 0xFC])
    s.type("@ 4.2000")
    s.type("d")
    _, row = s.find(r"^4\.2002:\. ")
    assert row.split()[-2:] == ["bne", "$2000"]
    _, row = s.find(r"^4\.2000:\. ")
    assert row.split()[-2:] == ["lda", "#$01"]


def test_a_walk_carries_into_the_next_bank(s):
    s.type("@ 4.fff0")
    s.type("m")
    assert prompt(s) == "5.0000:"
    s.type("m")
    s.find(r"^5\.0000:m ")


@pytest.mark.parametrize("cmd", ["3.2000:m 00", "2.c000:m 00", "m e000 00",
                                 "3.2000:. 00"])
def test_writes_into_the_rom_banks_are_refused(s, cmd):
    before = [fpeek(s, 3, 0x2000), fpeek(s, 2, 0xC000), fpeek(s, 3, 0xE000)]
    (s.line if ":" in cmd else s.type)(cmd)
    s.find(r"^;\?range")
    assert [fpeek(s, 3, 0x2000), fpeek(s, 2, 0xC000), fpeek(s, 3, 0xE000)] == before


def test_a_flat_m_row_in_40_columns_has_no_ascii_column(s):
    s.mode("4")
    fpoke(s, 4, 0x2000, range(0x41, 0x49))
    s.line("4.2000:m")
    _, row = s.find(r"^4\.2000:m ")
    assert row.rstrip() == "4.2000:m 41 42 43 44 45 46 47 48"


def test_flat_zero_is_ram_the_cpu_view_is_the_programs_port(s):
    fpoke(s, 0, 0x0000, [0x5A])
    s.line("0.0000:m")
    _, row = s.find(r"^0\.0000:m ")
    assert row.split()[1] == "5a"
    s.line("0000:m")
    _, row = s.find(r"^0000:m ")
    assert row.split()[1] == "ff"                       # the run premise's port


# ── the program's map (slice 3, F2: repl.md § Banks, mem.md § far_user) ──

def test_r_shows_the_programs_map(s):
    s.type("r")
    _, row = s.find(r"^r pc:")
    assert row.rstrip().endswith(" ml:e000 mh:8300")


def test_r_shows_the_map_on_the_second_row_in_40_columns(s):
    s.mode("4")
    s.type("r")
    k, _ = s.find(r"^r pc:")
    assert s.row(k + 1).rstrip() == "r z:00 b:00 ml:e000 mh:8300"


def test_a_mapped_program_is_shown_what_it_sees(s):
    fpoke(s, 4, 0x2000, [0x5A, 0xA5])
    s.type("r ml:e400")                     # $2000-$7FFF -> 4.2000
    s.type("m 2000")
    _, row = s.find(r"^2000:m ")
    assert row.split()[1:3] == ["5a", "a5"]
    s.type("m 2000 66")                     # and an edit lands there
    assert fpeek(s, 4, 0x2000) == [0x66]
    assert fpeek(s, 0, 0x2000) != [0x66]


def test_a_row_across_a_page_edge_is_translated_again(s):
    fpoke(s, 0, 0xBFF8, range(0x30, 0x38))
    s.type("m bff8")
    _, row = s.find(r"^bff8:m ")
    want = list(range(0x30, 0x38)) + fpeek(s, 2, 0xC000, 8)   # the interface ROM
    assert row.split(";")[0].split()[1:17] == [f"{b:02x}" for b in want]


def test_a_write_beneath_the_interface_rom_reaches_the_ram(s):
    rom = fpeek(s, 2, 0xC000)
    s.type("m c000 77")
    assert fpeek(s, 0, 0xC000) == [0x77]
    assert fpeek(s, 2, 0xC000) == rom
    assert ";?range" not in s.screen()


STANDARD_MAP = ["; map  0000-1fff 0.0000",
                "; map  2000-7fff 0.2000 mapped",
                "; map  8000-bfff 0.8000",
                "; map  c000-cfff 2.c000 rom",
                "; map  d000-dfff ffd.3000 io",
                "; map  e000-ffff 3.e000 mapped"]


def test_M_lists_the_programs_map(s):
    s.type("M")
    k, _ = s.find(r"^; map  0000-")
    assert [r.rstrip() for r in s.rows()[k:k + 6]] == STANDARD_MAP
    assert s.row(k + 6).rstrip() == "M mb:0000 d030:64"


def test_M_follows_an_edited_map(s):
    s.type("r ml:e400")
    s.type("M")
    s.find(r"^; map  2000-7fff 4\.2000 mapped")


def test_M_edits_the_megabytes_and_d030(s):
    s.type("M mb:0000 d030:20")
    assert s.v("um_d030") == 0x20


# ── far starts (slice 3, F3: repl.md § Far starts) ─────────────────

FAR_PROG = [0xA9, 0x48, 0x20, 0xD2, 0xFF,   # $2000 LDA #'H' · JSR BSOUT
            0xA9, 0x5A, 0x60]               # $2005 LDA #$5A · RTS


def far_prog(s, bank=4):
    fpoke(s, bank, 0x2000, FAR_PROG)
    fpoke(s, 0, 0x2000, [0xEA] * 8)         # bank 0: other bytes at $2000


def ran_to_rts(s):
    k, _ = s.find(r"^; rts")
    return s.row(k + 1)


@pytest.mark.parametrize("bank", [1, 4, 5])
def test_j_at_a_flat_address_starts_the_bank(s, bank):
    far_prog(s, bank)
    s.type(f"j {bank}.2000")
    row = ran_to_rts(s)
    assert re.search(rf" a:5a .* ml:e{bank}00 mh:8300", row), row


def test_a_bare_j_at_a_flat_prompt_starts_the_bank(s):
    far_prog(s)
    s.type("@ 4.2000")
    s.type("j")
    assert " a:5a " in ran_to_rts(s)


def test_a_cold_t_previews_and_steps_in_the_bank(s):
    far_prog(s)
    s.type("@ 4.2000")
    s.type("t")
    s.find(r"^; dbg at \$2000")
    s.find(r"^2000:\.  a9 48 .* lda #\$48")
    _, row = s.find(r"^r pc:")
    assert row.rstrip().endswith("ml:e400 mh:8300")
    s.type("t")
    s.find(r"at \$2002")
    s.type("o")                                 # over the JSR into the KERNAL
    s.find(r"at \$2005")
    s.type("c")
    s.find(r"^; rts")
    assert fpeek(s, 4, 0x2000, len(FAR_PROG)) == FAR_PROG   # no BRK left behind
    assert fpeek(s, 0, 0x2000, 8) == [0xEA] * 8             # bank 0 untouched


def test_a_breakpoint_in_far_code_is_hit(s):
    far_prog(s)
    s.type("b 4.2005")                     # bank 4's byte (F4: physical)
    s.type("j 4.2000")
    s.find(r"at \$2005")
    assert fpeek(s, 4, 0x2005) == [0xA9]                    # unpatched
    assert fpeek(s, 0, 0x2005, 1) == [0xEA]


@pytest.mark.parametrize("addr", ["2.2000", "3.2000", "4.8000", "4.1000", "100.2000"])
def test_a_far_start_outside_the_window_is_refused(s, addr):
    s.type(f"j {addr}")
    s.find(r"^;\?range")


def test_j_in_bank_0_is_the_plain_start(s):
    s.poke(0x3000, [0xA9, 0x77, 0x60])
    s.type("j 0.3000")
    row = ran_to_rts(s)
    assert " a:77 " in row and row.rstrip().endswith("ml:e000 mh:8300")


# ── flat breakpoints (slice 3, F4: debugger.md § b, breakpoints.md) ──

def test_b_takes_a_flat_address_and_a_far_start_hits_it(s):
    far_prog(s)
    s.type("b 4.2005")
    s.find(r"^; bp 1: 4\.2005$")
    s.type("j 4.2000")
    s.find(r"at \$2005")
    assert fpeek(s, 4, 0x2005) == [0xA9]                    # unpatched
    s.type("b")
    s.find(r"^; bp 1: 4\.2005$")


def test_a_cpu_address_breakpoint_lists_its_physical_byte(s):
    s.type("b $2005")
    s.find(r"^; bp 1: 0\.2005$")


def test_a_breakpoint_belongs_to_its_physical_byte(s):
    """A breakpoint set at $2005 in the standard map is 0.2005: a far
    start that runs bank 4 at $2005 does not stop there, and bank 0's
    byte is back when the run ends; bank 4 never held a BRK."""
    far_prog(s)
    s.type("b $2005")
    s.type("j 4.2000")
    row = ran_to_rts(s)
    assert " a:5a " in row
    assert fpeek(s, 0, 0x2005) == [0xEA]
    assert fpeek(s, 4, 0x2000, len(FAR_PROG)) == FAR_PROG


@pytest.mark.parametrize("addr", ["3.2000", "2.c000", "$e000", "$d020", "1.1000", "0.1000"])
def test_a_breakpoint_outside_user_memory_is_refused(s, addr):
    s.type(f"b {addr}")
    s.find(r"^;\?range")
    s.type("b")
    assert all(r.rstrip().endswith("$----") or not r.startswith("; bp")
               for r in s.rows()), s.screen()


# ── 32-bit values (slice 3, F5a: expr.md § 32-bit values, repl.md § Banks) ──

@pytest.mark.parametrize("expr,row", [
    ("$12345", "$00012345  74565"),
    ("4.2000", "$00042000  270336"),
    ("4.2000+$10>>4", "$00042001  270337"),
    ("-1", "$ffffffff  4294967295"),
    ("$ffffffff", "$ffffffff  4294967295"),
    ("1<<31", "$80000000  2147483648"),
    ("100000*3", "$000493e0  300000"),
])
def test_q_shows_a_value_outside_16_bits_in_32(s, expr, row):
    s.type(f"? {expr}")
    s.find("^; " + re.escape(row) + "$")


@pytest.mark.parametrize("expr,row", [
    ("$ffff", "$ffff  65535"),
    ("4.2000>>16", "$04      4  %00000100  +4"),
    ("$10000-1", "$ffff  65535"),
])
def test_q_keeps_the_16_bit_form_within_16_bits(s, expr, row):
    s.type(f"? {expr}")
    s.find(r"^; *" + re.escape(row) + "$")


@pytest.mark.parametrize("cmd", ["t $10000", "B -$10000", "B 4.2000"])   # 16 bits only (F5c)
def test_an_argument_outside_16_bits_is_expr_range(s, cmd):
    s.type(cmd)
    s.find(r"^;\?expr range$")


def test_a_far_constant_holds_32_bits_and_a_16_bit_use_is_refused(s):
    from test_m65_source_editor import put_source
    put_source(s, b" .CONST FAR 4.2000\r .CONST BIG 100000\r .ORG $3000\r"
                  b" LDA FAR\r .DW BIG\r LDA #<FAR\r .DB >(FAR>>16)\r .DB -1\r")
    s.type("a")
    s.find(r"^;\?4: range$")
    s.find(r"^;\?5: bad val$")
    assert s.w("asm_errors") == 2
    s.type("? far")
    s.find(r"^; \$00042000  270336$")
    s.type("? big>>16")
    s.find(r"^; *\$01      1  %00000001  \+1$")


# ── `a`, `g` and `.` in a bank (slice 3, F5b: repl.md § Banks) ──────

def _assemble(s, text):
    from test_m65_asm_src import assemble
    return assemble(s, text)


def test_g_far_starts_main_in_a_bank(s):
    assert _assemble(s, "\t.org 4.2000\rmain:\tlda #$5a\r\trts\r") == 0
    assert prompt(s) == "4.2000:"
    s.type("g")
    row = ran_to_rts(s)
    assert re.search(r" a:5a .* ml:e400 mh:8300", row), row


def test_g_with_main_outside_the_far_window_is_range(s):
    assert _assemble(s, "\t.org 1.9000\rmain:\trts\r") == 0
    s.type("g")
    s.find(r"^;\?range$")


def test_dot_at_a_flat_address_takes_its_own_banks_values(s):
    s.type("@ 4.2000")
    s.type(". jmp 4.2010")
    assert fpeek(s, 4, 0x2000, 3) == [0x4C, 0x10, 0x20]
    fpoke(s, 4, 0x2003, [0x00])
    s.type(". jmp 5.0000")                 # another bank: refused
    k, _ = s.find(r"^;\?expr range$")
    assert ". jmp 5.0000" in s.row(k - 1)
    assert fpeek(s, 4, 0x2003) == [0x00]
    s.type("B $40010")                     # the bank does not outlive `.`
    k, _ = s.find(r"^;\?expr range$")
    assert "B $40010" in s.row(k - 1)


def test_restore_during_a_leaves_no_bank_and_no_32_bit_opt_in(s):
    """RESTORE in an assembly's flat segment abandons it (main.md §
    refresh_body); the 16-bit arguments after it keep their range."""
    from test_m65_asm_src import rows                    # noqa: F401
    s.call("ed_ensure_init")
    src = "\t.org 4.2000\r" + "\tnop\r" * 300
    for ch in src.replace("\t", "\xa0").encode("latin-1").upper():
        s.call("gb_insert", a=ch)
    s.start("a")
    bank = s.cell("expr_bank")
    for _ in range(4000):                                 # into the flat segment
        s.e.run_steps(500)
        if s.e.memory[bank] == 4:
            break
    assert s.e.memory[bank] == 4
    s.e.memory[s.cell("_ex_far")] = 0x80                  # as if inside a `?`
    s.e.press_restore()
    s.idle(max_steps=6_000_000)
    s.type("B $40010")
    s.find(r"^;\?expr range$")
    assert s.e.memory[bank] == 0 and s.e.memory[s.cell("_ex_far")] == 0


# ── address arguments as expressions (slice 3, F5c: repl.md § Banks) ──

@pytest.mark.parametrize("expr,shown", [
    ("4.2000+$10", "4.2010"), ("0.2000", "0.2000"), ("$12345", "1.2345"),
    ("$2000", "2000"), ("-1", "ffff"), ("$fffff", "f.ffff"),
    ("$8000000", "800.0000"), ("$12345-$12000", "0.0345"),
])
def test_at_takes_an_expression_flat_when_its_width_is_far(s, expr, shown):
    s.type(f"@ {expr}")
    assert prompt(s) == f"{shown}:"


@pytest.mark.parametrize("expr", ["$10000000", "-$10000", "$ffff0000"])
def test_an_address_outside_28_bits_is_expr_range(s, expr):
    s.type(f"@ {expr}")
    s.find(r"^;\?expr range$")
    assert prompt(s) == "2000:"


def test_at_j_and_b_follow_a_flat_label(s):
    assert _assemble(s, "\t.org 4.2000\rmain:\tlda #$5a\rloop:\trts\r") == 0
    s.type("@ $3000")
    s.type("@ main+3")
    assert prompt(s) == "4.2003:"
    s.type("b loop")
    s.find(r"^; bp 1: 4\.2002$")
    s.type("j main")                       # a far start, stopped at loop
    k, _ = s.find(r"^; brk 1 at \$2002$")
    assert re.search(r" a:5a .* ml:e400 mh:8300", s.row(k + 1)), s.row(k + 1)


@pytest.mark.parametrize("arg,row", [
    ("main", r"^4\.2000:m "), ("$2000", r"^2000:m "), ("2000", r"^2000:m "),
    ("buf+$10", r"^3010:m "), ("(cafe)", r"^3000:m "), ("4.2000", r"^4\.2000:m "),
])
def test_m_takes_an_expression_and_keeps_its_hex_word(s, arg, row):
    assert _assemble(s, "\t.const buf $3000\r\t.const cafe $3000\r"
                        "\t.org 4.2000\rmain:\trts\r") == 0
    s.type("@ $5000")                      # not where the argument points
    s.type(f"m {arg}")
    s.find(row)


def test_m_after_an_expression_edits_there(s):
    assert _assemble(s, "\t.org 4.2000\rmain:\trts\r") == 0
    s.type("m main+1 11 22")
    assert fpeek(s, 4, 0x2001, 2) == [0x11, 0x22]
    s.type("@ $3000")
    s.type("m 33 44")                      # two hex digits: the edit bytes
    assert s.peek(0x3000, 2) == [0x33, 0x44]


@pytest.mark.parametrize("cmd", ["j nosuch", "m nosuch", "@ nosuch", "b nosuch"])
def test_an_undefined_address_is_expr_undef(s, cmd):
    s.type(cmd)
    s.find(r"^;\?expr undef$")


# ── `.` hands its line to asm_line (TODO § Bugs › Both platforms) ──

@pytest.mark.parametrize("text,op", [("asl a", 0x0A), ("rol a", 0x2A), ("lsr a", 0x4A),
                                     ("ror a", 0x6A), ("inc a", 0x1A), ("dec a", 0x3A)])
def test_dot_takes_the_accumulator_form(s, text, op):
    s.poke(0x3000, [0x00])
    s.type("@ $3000")
    s.type(f". {text}")
    assert s.peek(0x3000) == [op], s.screen()


def test_dot_star_is_this_instructions_address(s):
    s.type("@ $3000")
    s.type(". bne *")
    assert s.peek(0x3000, 2) == [0xD0, 0xFE]


def test_dot_an_undefined_operand_is_expr_undef(s):
    s.type("@ $3000")
    s.type(". jmp nosuch")
    s.find(r"^;\?expr undef$")


# ── the write guard covers the whole run (TODO § Bugs › m65, fixed
#    2026-11-21): nothing is written when any byte would land in 2-3 ──

@pytest.mark.parametrize("line", ["1.fffe:m 11 22 33 44", "1.fffe:. ea ea ea"])
def test_a_flat_run_reaching_bank_2_is_refused_whole(s, line):
    fpoke(s, 1, 0xFFFE, [0xAA, 0xAA])
    before = fpeek(s, 2, 0x0000, 2)
    s.line(line)
    s.find(r"^;\?range$")
    assert fpeek(s, 1, 0xFFFE, 2) == [0xAA, 0xAA]
    assert fpeek(s, 2, 0x0000, 2) == before


def test_a_cpu_run_into_a_rom_page_is_refused_whole(s):
    before = fpeek(s, 3, 0xE000, 2)
    s.type("m dffe 11 22 33 44")
    s.find(r"^;\?range$")
    assert fpeek(s, 3, 0xE000, 2) == before
    assert prompt(s) == "2000:"                 # the address did not move


def test_m_with_trailing_garbage_writes_nothing(s):
    s.poke(0x3000, [0, 0])
    s.type("@ $3000")
    s.type("m 11 22 zz")
    s.find(r"^;\?syntax$")
    assert s.peek(0x3000, 2) == [0, 0]


def test_an_m_edit_that_carries_into_the_next_bank_lands_after_it(s):
    s.line("4.fffc:m 01 02 03 04 05 06 07 08")
    assert fpeek(s, 5, 0x0000, 4) == [5, 6, 7, 8]
    assert prompt(s) == "5.0004:"


# ── a refused or cancelled `j` / `g` moves nothing (TODO § Bugs › Both
#    platforms, fixed 2026-11-21) ─────────────────────────────────────

def test_a_refused_far_start_leaves_the_current_address(s):
    s.type("@ $3000")
    s.type("j 4.8000")
    s.find(r"^;\?range$")
    assert prompt(s) == "3000:"


@pytest.mark.parametrize("cmd", ["j $1234", "g"])
def test_a_cancelled_start_leaves_the_current_address(s, cmd):
    _assemble(s, "\t.org $3100\rmain:\trts\r")
    s.poke(USER, [0xEA, 0x00, 0x00, 0x60])
    s.type("j $3000")                               # a session at $3001
    assert s.v("dbg_reason") == DBG_BRK
    before = prompt(s)
    s.start(cmd)
    s.keys(b"N")
    s.find(r"^;!go\? y/n")
    assert prompt(s) == before


# ── `d` at the top of memory (TODO § Bugs › Both platforms, fixed
#    2026-11-21) ────────────────────────────────────────────────────────

def test_d_lists_the_last_byte_of_a_bank_and_carries(s):
    fpoke(s, 4, 0xFFFF, [0xEA])
    s.line("4.ffff:d")
    s.find(r"^4\.ffff:\.  ea +eom$")
    assert prompt(s) == "5.0000:"


@pytest.mark.parametrize("cmd", ["b -12", "b -1x", "b *xyz", "b * 1"])
def test_b_delete_and_clear_take_no_trailing_garbage(s, cmd):
    """TODO § Bugs (fixed 2026-11-21): ;?syntax, and every slot stays."""
    s.type("b $3000")
    s.type(cmd)
    s.find(r"^;\?syntax$")
    s.type("b")
    s.find(r"^; bp 1: 0\.3000$")


def test_dot_refuses_more_pairs_than_the_longest_instruction(s):
    """TODO § Bugs (fixed 2026-11-21): a sixth pair is ;?syntax, and
    nothing is written (it used to write five and drop the sixth)."""
    s.poke(0x3000, [0] * 6)
    s.type("@ $3000")
    s.type(". a9 42 ea ea ea ea")
    s.find(r"^;\?syntax$")
    assert s.peek(0x3000, 6) == [0] * 6


def test_flat_walks_wrap_at_28_bits(s):
    """TODO § Bugs › m65 (fixed 2026-11-21): the flat space is 28 bits."""
    s.type("@ 0.0010")
    s.type("- $20")
    assert prompt(s) == "fff.fff0:"
    assert s.w("cur_bank") == 0x0FFF
    s.line("0fff.fff8:m")
    assert prompt(s) == "0.0008:"
    assert s.w("cur_bank") == 0x0000


# ── dbg_init's state (TODO § Bugs › m65, fixed 2026-11-21) ──────────

def test_hw_reinit_after_a_far_start_seeds_the_run_premise(s):
    """cse_recover runs hw_reinit_body → dbg_init: the bank state is the
    run premise's again, not the last far start's (run_bank cleared)."""
    premise = [s.e.memory[s.cell("um_map") + k] for k in range(6)]
    far_prog(s, 4)
    s.type("j 4.2000")
    assert s.v("run_bank") == 4
    s.call("hw_reinit_body")
    assert s.v("run_bank") == 0
    assert [s.e.memory[s.cell("um_map") + k] for k in range(6)] == premise


def test_dbg_init_zeroes_the_whole_step_state_block(s):
    for name in ("step_len", "_rtu_need_sentinel"):
        s.e.memory[s.cell(name)] = 0xA5
    s.call("dbg_init")
    assert s.v("step_len") == 0 and s.v("_rtu_need_sentinel") == 0


# ── the break-path stack budget (TODO § Test gaps, 2026-11-21) ───────

def test_break_path_stays_within_64_bytes(s):
    """userland_contract.md § Kernel stack budget: the break (its 8-byte
    frame) and the REPL commands typed at it stay within the 64 bytes
    below the user's SP — measured from `reg_sp`."""
    from test_kernel_transition import AT_A_BREAK, LOW_SP, lowest_sp
    s.poke(USER, [0xA2, LOW_SP, 0x9A] + [0xEA] * 8)   # LDX #$A0 · TXS · NOPs
    s.type("b $3003")

    def at_a_break():
        s.type("j $3000")
        assert s.v("reg_sp") == LOW_SP
        for cmd in AT_A_BREAK:
            s.type(cmd)
    depth = LOW_SP - lowest_sp(s.e.cpu, at_a_break)
    print(f"m65 break-path depth: {depth} B")
    assert s.v("reg_sp") == LOW_SP
    assert not any(r.startswith(";?") for r in s.rows())
    assert depth <= 64


# ── the name heap's bound on m65 (TODO § Test gaps, 2026-11-21) ──────

SYM_HEAP, SYM_HEAP_END = 0xA700, 0xB000     # platform.inc (m65), CSE map
NAME_AT = 0xBF00                            # a name's scratch: REPL_SCREEN's tail


def test_name_heap_stops_below_the_repl_screen(s):
    """symtab.md § Caveats on m65: the heap ends at SYM_HEAP_END = $B000,
    where REPL_SCREEN begins — a name that does not fit is refused (C=1)
    with nothing written at $B000+, and the names before it are found."""
    mem = s.e.memory
    s.call("sym_clear")
    for a in range(SYM_HEAP_END, SYM_HEAP_END + 0x100):
        mem[a] = 0xA5

    def at(name):
        for k, ch in enumerate(name.encode() + b"\0"):
            mem[NAME_AT + k] = ch
        mem[s.cell("sym_name")], mem[s.cell("sym_name") + 1] = NAME_AT & 0xFF, NAME_AT >> 8

    names = []
    for i in range(100):
        name = f"n{i:03d}" + "x" * 34          # 38 characters + NUL
        at(name)
        for k, b in enumerate(i.to_bytes(4, "little")):
            mem[s.cell("sym_val") + k] = b
        mem[s.cell("sym_wide")] = 1
        s.call("sym_define")
        if s.e.carry:
            break
        names.append(name)
    assert len(names) == (SYM_HEAP_END - SYM_HEAP) // 39
    assert all(mem[a] == 0xA5 for a in range(SYM_HEAP_END, SYM_HEAP_END + 0x100))
    assert s.w("_st_heap") <= SYM_HEAP_END
    for i, name in enumerate(names):
        at(name)
        s.call("sym_lookup")
        assert not s.e.carry and s.w("sym_val") == i, name
