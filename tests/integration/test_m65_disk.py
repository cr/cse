"""test_m65_disk.py — disk.s and the REPL's disk commands on the m65 PRG (P3 T2 T3).

Owner: doc/modules/disk.md

Contract source: [disk.md § On m65](../../doc/modules/disk.md#on-m65) and
the Interface it keeps; [testing.md § The m65 PRG on M65Emu](../../doc/testing.md#the-m65-prg-on-m65emu)
(*The disk on m65*).

The debug m65 PRG, cold-started as in test_m65_repl.py (M65Session).
M65Emu models no floppy controller, so the tests use an IEC unit, 10,
where the virtual drive answers behind the KERNAL's jump table;
units 8 and 9 (CBDOS's) are Tier X.  test_disk.py's contract, on m65:

- without a drive: the error codes, no file left open (the KERNAL's
  LDTND, base page 0's $98 as on the C64), an empty status, no hang;
- with one: PRG load to its header address and to a given one (in
  bank 0), PRG save of the user's bytes from bank 0, SEQ save and load
  with their counts, the status line;
- `$`: the listing, into DIR_BUF (2.D000), the program region
  0.2000-0.BFFF untouched, the header reversed in the screen's bank in
  each mode; STOP breaks it;
- the REPL over it: `$ 10` selects the unit, `s` / `l` of a PRG range
  (the range row with its bank) and of the source (back in bank 2).
"""

import pytest

from m65emu.harness import flat
from test_m65_repl import M65Session

UNIT = 10
LDTND = 0x98                       # the KERNAL's open-file count (both ROMs)
SAVE_FN, LOAD_FN = 0x1700, 0x1740  # the SEQ callbacks, bank 0
SRC_BUF, SRC_IDX, SRC_LEN = 0x1800, 0x17F0, 0x17F1
DST_BUF, DST_IDX = 0x1900, 0x17F2
DIR_BUF = flat(2, 0xD000)

_SAVE_FN_CODE = [0xAC, SRC_IDX & 0xFF, SRC_IDX >> 8,     # LDY SRC_IDX
                 0xCC, SRC_LEN & 0xFF, SRC_LEN >> 8,     # CPY SRC_LEN
                 0xB0, 0x09,                             # BCS eof
                 0xB9, SRC_BUF & 0xFF, SRC_BUF >> 8,     # LDA SRC_BUF,Y
                 0xEE, SRC_IDX & 0xFF, SRC_IDX >> 8,     # INC SRC_IDX
                 0xA2, 0x00, 0x60,                       # LDX #0 · RTS
                 0xA9, 0xFF, 0xAA, 0x60]                 # eof: LDA #$FF · TAX · RTS
_LOAD_FN_CODE = [0xAC, DST_IDX & 0xFF, DST_IDX >> 8,     # LDY DST_IDX
                 0x99, DST_BUF & 0xFF, DST_BUF >> 8,     # STA DST_BUF,Y
                 0xEE, DST_IDX & 0xFF, DST_IDX >> 8,     # INC DST_IDX
                 0x60]


@pytest.fixture
def s(cse_m65_prg, m65_snapshot):
    s = M65Session(cse_m65_prg, m65_snapshot)
    s.e.memory[s.cell("cur_device")] = UNIT
    name(s, b"FOO")
    s.poke(SAVE_FN, _SAVE_FN_CODE)
    s.poke(LOAD_FN, _LOAD_FN_CODE)
    s.poke(SRC_IDX, [0, 0, 0])
    return s


@pytest.fixture
def drv(s):
    return s, s.e.attach_drive(UNIT)


def name(s, text):
    """A filename where CSE keeps its names, in its own view (bank 3:
    SETBNK's filename bank), and disk_ptr at it."""
    buf = s.cell("disk_name_buf")
    for k, c in enumerate(text + b"\0"):
        s.e.memory[buf + k] = c
    p = s.cell("disk_ptr")
    s.e.memory[p], s.e.memory[p + 1] = buf & 0xFF, buf >> 8


def fl_buf(s):
    a, out = s.cell("fl_buf"), bytearray()
    while s.e.memory[a + len(out)]:
        out.append(s.e.memory[a + len(out)])
    return bytes(out)


def open_files(s):
    return s.e.memory.read_flat(LDTND)


def ax(s):
    return s.e.a, s.e.x


def save_prg(s, size=4):
    io_tmp = s.cell("_io_tmp")
    s.e.memory[io_tmp], s.e.memory[io_tmp + 1] = 0x00, 0x40
    s.call("disk_save_prg", a=size & 0xFF, x=size >> 8)


def save_seq(s, text=b"X\r"):
    s.poke(SRC_BUF, text)
    s.poke(SRC_LEN, [len(text)])
    s.poke(SRC_IDX, [0])
    s.call("disk_save_seq", a=SAVE_FN & 0xFF, x=SAVE_FN >> 8)


def load_seq(s):
    s.call("disk_load_seq", a=LOAD_FN & 0xFF, x=LOAD_FN >> 8)


def load_prg(s, addr=0x4000):
    s.call("disk_load_prg", a=addr & 0xFF, x=addr >> 8)


# ── without a drive ───────────────────────────────────────────────

@pytest.mark.parametrize("call,err", [(save_prg, (1, 0)), (save_seq, (1, 0)),
                                      (load_seq, (1, 0)), (load_prg, (0, 0))],
                         ids=["save_prg", "save_seq", "load_seq", "load_prg"])
def test_failed_open_leaves_no_file_open(s, call, err):
    call(s)
    assert ax(s) == err
    assert open_files(s) == 0


def test_status_with_no_drive_is_empty_and_does_not_hang(s):
    s.e.memory[s.cell("fl_buf")] = 0x41
    s.call("floppy_read_status")
    assert fl_buf(s) == b"" and open_files(s) == 0


# ── on a drive ────────────────────────────────────────────────────

class TestLoadPrg:

    def test_to_the_header_address(self, drv):
        s, d = drv
        d.put("FOO", b"\x00\x50\x01\x02\x03")
        load_prg(s, 0)
        assert ax(s) == (0x03, 0x50)
        assert s.peek(0x5000, 3) == [1, 2, 3]
        assert open_files(s) == 0

    def test_to_the_given_address(self, drv):
        s, d = drv
        d.put("FOO", b"\x00\x50\x01\x02\x03")
        load_prg(s, 0x6000)
        assert ax(s) == (0x03, 0x60)
        assert s.peek(0x6000, 3) == [1, 2, 3]

    def test_missing_file_is_an_error_with_the_drives_status(self, drv):
        s, d = drv
        name(s, b"NOPE")
        load_prg(s, 0)
        assert ax(s) == (0, 0)
        assert fl_buf(s).startswith(b"62,") and open_files(s) == 0


class TestSavePrg:

    def test_the_users_bytes_from_bank_0(self, drv):
        s, d = drv
        s.poke(0x4000, [0xA9, 0x01, 0xEA, 0x60])
        save_prg(s)
        assert d.get("FOO") == b"\x00\x40\xa9\x01\xea\x60"
        assert d.find("FOO").type == "PRG"
        assert ax(s) == (0, 0) and open_files(s) == 0

    def test_replaces_an_existing_file(self, drv):
        s, d = drv
        d.put("FOO", b"old")
        save_prg(s)
        assert d.names() == [b"FOO"] and d.get("FOO")[:2] == b"\x00\x40"


class TestSeq:

    def test_save_writes_a_seq_and_counts(self, drv):
        s, d = drv
        text = b"\xa0NOP\r\xa0RTS\r"
        save_seq(s, text)
        assert ax(s) == (0, 0)
        assert d.get("FOO") == text and d.find("FOO").type == "SEQ"
        assert s.w("disk_seq_bytes") == len(text) and s.w("disk_seq_lines") == 3

    def test_load_reads_every_byte_and_counts(self, drv):
        s, d = drv
        text = b"\xa0NOP\r\xa0RTS"
        d.put("FOO", text, "SEQ")
        load_seq(s)
        assert ax(s) == (0, 0)
        assert bytes(s.peek(DST_BUF, len(text))) == text
        assert s.w("disk_seq_bytes") == len(text) and s.w("disk_seq_lines") == 2
        assert open_files(s) == 0


def test_read_status(drv):
    s, d = drv
    s.call("floppy_read_status")
    assert fl_buf(s) == b"73,CBM DOS V2.6 1541,00,00"
    s.call("floppy_read_status")
    assert fl_buf(s) == b"00, OK,00,00"
    assert open_files(s) == 0


# ── $ — the directory ─────────────────────────────────────────────

HEADER = '; "cse test        " 01 2a'


def listing(s, cmd="$ 10"):
    s.type(cmd, max_steps=6_000_000)
    k, _ = s.find(r'^; "cse test')
    return [t for t in s.rows()[k:] if t]


def test_dollar_lists_the_unit(drv):
    s, d = drv
    d.put("FOO", bytes(254 * 12))
    d.put("SRC", b"x", "SEQ")
    assert listing(s)[:5] == [HEADER, 'l "foo,p"; 12 blocks', 'l "src,s"; 1 blocks',
                              "; 651 blocks free.", "; 00, ok,00,00"]
    assert s.v("cur_device") == UNIT


def test_dollar_leaves_the_program_region_alone(drv):
    """The directory goes to DIR_BUF (2.D000), not to BASIC_START."""
    s, d = drv
    for i in range(20):
        d.put(f"F{i}", b"x")
    pattern = [(k * 13 + 7) & 0xFF for k in range(0x200)]
    s.poke(0x2000, pattern)
    listing(s)
    assert s.peek(0x2000, 0x200) == pattern
    assert s.e.memory.read_flat(DIR_BUF + 4) != 0      # the header line's text is there


@pytest.mark.parametrize("key,width,bank", [("8", 80, 0), ("4", 40, 0), ("5", 80, 4)])
def test_the_header_is_reversed_in_the_screens_bank(drv, key, width, bank):
    s, d = drv
    if key != "8":
        s.mode(key)
    listing(s)
    k, _ = s.find(r'^; "cse test')
    base = flat(bank, 0x0800 + k * width)
    row = [s.e.memory.read_flat(base + c) for c in range(len(HEADER))]
    assert [c & 0x80 for c in row[:2]] == [0, 0]               # "; "
    assert all(c & 0x80 for c in row[2:2 + 18])                # from the quote


def test_stop_breaks_the_listing(drv):
    s, d = drv
    for i in range(5):
        d.put(f"F{i}", b"x")
    s.start("$ 10")
    s.e.inject_key(0x03)                                        # STOP queued
    s.idle(max_steps=6_000_000)
    k, _ = s.find(r'^; "cse test')
    assert s.row(k + 1) == "break"


# ── the REPL's s / l (T3) ─────────────────────────────────────────

def test_s_and_l_of_a_prg_range(drv):
    s, d = drv
    s.type("$ 10")
    data = [(k * 5) & 0xFF for k in range(0x101)]
    s.poke(0x3000, data)
    s.type("@ $3000")
    s.type('s "foo" $3100', max_steps=6_000_000)
    assert d.get("FOO.") == b"\x00\x30" + bytes(data)
    s.find(r"^; prg  0\.3000-3100   257b$")                    # the range with its bank
    s.poke(0x3000, [0] * 0x101)
    s.type('l "foo" 0', max_steps=6_000_000)
    assert s.peek(0x3000, 0x101) == data


def test_s_and_l_of_the_source(drv):
    s, d = drv
    s.type("$ 10")
    s.call("ed_ensure_init")
    for ch in b"\xa0NOP\r\xa0RTS\r":
        s.call("gb_insert", a=ch)
    s.type('s "src"', max_steps=6_000_000)
    assert d.get("SRC") == b"\xa0NOP\r\xa0RTS\r"
    d.put("SRC", b"\xa0INX\r", "SEQ")
    s.type('l "src"', max_steps=6_000_000)
    s.find(r"^; 2l 5b$")
    lo, hi = s.w("gap_hi"), 0xC000
    assert bytes(s.e.memory.read_flat(flat(2, a)) for a in range(lo, hi)) == b"\xa0INX\r"


def test_the_disk_commands_leave_the_programs_base_page_alone(drv):
    """`s`, `$` and `l` call the KERNAL's file and disk routines, which
    write their own cells ($90-$FA) only: the program's $0A-$8F and
    $FB-$FF keep their bytes (userland_contract.md § 3 On m65)."""
    from test_m65_repl import fill_user_bp, user_bp
    s, _ = drv
    pat = fill_user_bp(s)
    s.poke(0x3000, list(range(16)))
    for cmd in ['s "bp" $3000 $3010', "$", 'l "bp" 0']:
        s.type(cmd)
    assert user_bp(s) == pat
