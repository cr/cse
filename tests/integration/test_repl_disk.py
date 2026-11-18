"""
test_repl_disk.py — the REPL's disk commands `s`, `l` and `$` on a drive.

Owner: doc/modules/repl.md

Contract source: [repl.md § Commands — Load / Save](../../doc/modules/repl.md)
(argument table, mode classification, disk filename, end-address and
load semantics) and `$`'s device argument.  The commands run through
`exec_line` on C64Emu + the production PRG, against a virtual 1541 on
the serial bus ([testing.md § Virtual IEC drives](../../doc/testing.md#virtual-iec-drives)):
what a command did is read off the drive — the file's name, type and
bytes — and off memory, the editor buffer and the screen.
"""

import pytest
from c64emu import C64Emu

SCREEN_ROW = 5                 # where each command starts printing


# ── fixture and helpers ─────────────────────────────────────────────

@pytest.fixture
def emu(cse_prg):
    """CSE-initialised C64Emu with a 1541 as device 8 (cur_device),
    block size $0010, cursor on row 5."""
    prg, map_path = cse_prg
    e = C64Emu()
    e.load_prg(prg, map_path)
    e.init_cse()
    e.set_cursor(SCREEN_ROW, 0)
    e.write_word(e.sym("block_size"), 0x0010)
    e.memory[e.sym("cur_device")] = 8
    e.memory[e.sym("asm_cpu")] = 1
    e.attach_drive(8)
    return e


def petscii(text):
    out = []
    for ch in text.encode("ascii"):
        if 0x61 <= ch <= 0x7A:
            ch -= 0x20
        elif 0x41 <= ch <= 0x5A:
            ch += 0x80
        out.append(ch)
    return out


def run(e, line):
    lb = e.sym("line_buf")
    data = petscii(line)
    e.memory[lb:lb + len(data) + 1] = data + [0]
    e.jsr(e.sym("exec_line"), max_cycles=3_000_000)


def set_cur_addr(e, addr):
    e.write_word(e.sym("cur_addr"), addr)


def project_name(e):
    base, out = e.sym("cur_project_name"), bytearray()
    while e.memory[base + len(out)]:
        out.append(e.memory[base + len(out)])
    return bytes(out)


def set_project_name(e, name):
    base = e.sym("cur_project_name")
    e.memory[base:base + len(name) + 1] = list(name) + [0]


def fill(e, start, size):
    """A recognisable pattern at start..start+size-1; return it."""
    data = bytes((start + i * 7) & 0xFF for i in range(size))
    e.memory[start:start + size] = list(data)
    return data


def editor_text(e):
    e.jsr(e.sym("ed_read_rewind"))
    out = bytearray()
    for _ in range(10000):
        e.jsr(e.sym("ed_read_byte"))
        if e.a == 0xFF and e.x == 0xFF:
            break
        out.append(e.a)
    return bytes(out)


def insert_text(e, text):
    buf = 0x3000
    e.memory[buf:buf + len(text) + 1] = list(text) + [0]
    e.jsr(e.sym("ed_insert_string"), a=buf & 0xFF, x=buf >> 8)


def rows(e, first=SCREEN_ROW):
    return [e.screen_text(r) for r in range(first, 25) if e.screen_text(r)]


# ── s ───────────────────────────────────────────────────────────────

class TestSaveCommand:
    """`s`: name derivation, SEQ vs PRG routing, the end-address table
    (repl.md § Commands — Load / Save)."""

    # ── derivation (bare name → SEQ) ──

    def test_save_seq_bare(self, emu):
        """s "foo" → the editor source as SEQ "foo"; project = "foo"."""
        emu.init_cse(editor=True)
        insert_text(emu, b"\xa0NOP\r")
        run(emu, 's "foo"')
        d = emu.drive(8)
        assert d.find("FOO").type == "SEQ" and d.get("FOO") == b"\xa0NOP\r"
        assert project_name(emu) == b"FOO"

    def test_save_prg_derived(self, emu):
        """s "foo" $0900 → PRG "foo." = header + $0800-$0900 inclusive."""
        set_cur_addr(emu, 0x0800)
        data = fill(emu, 0x0800, 0x101)
        run(emu, 's "foo" $0900')
        d = emu.drive(8)
        assert d.names() == [b"FOO."] and d.find("FOO.").type == "PRG"
        assert d.get("FOO.") == b"\x00\x08" + data
        assert project_name(emu) == b"FOO"

    def test_save_strip_trailing_dot(self, emu):
        """s "foo." → project "foo"; SEQ saved under the project name."""
        run(emu, 's "foo."')
        assert project_name(emu) == b"FOO"
        assert emu.drive(8).names() == [b"FOO"]

    def test_save_prints_the_operation_range_and_status(self, emu):
        set_cur_addr(emu, 0x0800)
        run(emu, 's "foo" $0900')
        assert rows(emu) == ['; save "foo."...', "; prg  0800-0900   257b",
                             "; 00, ok,00,00"]

    # ── verbatim forms (,s / ,p disable derivation) ──

    def test_save_verbatim_seq(self, emu):
        run(emu, 's "foo,s"')
        d = emu.drive(8)
        assert d.names() == [b"FOO"] and d.find("FOO").type == "SEQ"
        assert project_name(emu) == b"FOO"

    def test_save_verbatim_prg(self, emu):
        """s "foo,p" → PRG "foo" (no dot), block_size bytes from cur_addr."""
        set_cur_addr(emu, 0x0800)
        data = fill(emu, 0x0800, 0x10)
        run(emu, 's "foo,p"')
        d = emu.drive(8)
        assert d.names() == [b"FOO"] and d.find("FOO").type == "PRG"
        assert d.get("FOO") == b"\x00\x08" + data
        assert project_name(emu) == b"FOO"

    def test_save_verbatim_prg_with_dot(self, emu):
        set_cur_addr(emu, 0x0800)
        run(emu, 's "foo.,p"')
        assert emu.drive(8).names() == [b"FOO."]
        assert emu.drive(8).find("FOO.").type == "PRG"
        assert project_name(emu) == b"FOO"

    # ── end-address table ──

    def test_save_end_blocksize_fallback(self, emu):
        """No end → block_size bytes."""
        set_cur_addr(emu, 0x0800)
        run(emu, 's "foo,p"')
        assert len(emu.drive(8).get("FOO")) == 2 + 0x10

    def test_save_two_args(self, emu):
        """start, end (inclusive)."""
        data = fill(emu, 0x1000, 0x1001)
        run(emu, 's "foo" $1000 $2000')
        assert emu.drive(8).get("FOO.") == b"\x00\x10" + data

    def test_save_end_length_fallback(self, emu):
        """end <= start → end is a length."""
        data = fill(emu, 0x1000, 0x100)
        run(emu, 's "foo" $1000 $100')
        assert emu.drive(8).get("FOO.") == b"\x00\x10" + data

    def test_save_addr_prefix(self, emu):
        """0801:s "test" $2004 — the AAAA: prefix sets the start."""
        data = fill(emu, 0x0801, 0x2004 - 0x0801 + 1)
        run(emu, '0801:s "test" $2004')
        assert emu.drive(8).get("TEST.") == b"\x01\x08" + data

    # ── project-name reuse ──

    def test_save_no_name_defaults_to_out(self, emu):
        set_cur_addr(emu, 0x0800)
        run(emu, "s")
        d = emu.drive(8)
        assert d.names() == [b"OUT"] and d.find("OUT").type == "SEQ"

    def test_save_reuse_prev_name(self, emu):
        run(emu, 's "foo"')
        emu.drive(8).files.clear()
        run(emu, "s")
        assert emu.drive(8).names() == [b"FOO"]

    def test_save_unquoted_is_expr(self, emu):
        """s $0900 — the arg is the inclusive end; args force PRG."""
        set_cur_addr(emu, 0x0800)
        set_project_name(emu, b"PREV")
        data = fill(emu, 0x0800, 0x101)
        run(emu, "s $0900")
        assert emu.drive(8).get("PREV.") == b"\x00\x08" + data

    def test_save_refused_by_the_drive_fails_with_its_status(self, emu):
        """A write-protected disk: `;?fail` and the drive's own message
        (read once, by the save), nothing on the disk."""
        emu.drive(8).write_protect = True
        set_cur_addr(emu, 0x0800)
        run(emu, 's "foo" $0900')
        assert rows(emu) == ['; save "foo."...', ";?fail",
                             "; 26,write protect on,00,00"]
        assert emu.drive(8).files == []

    def test_save_replaces_the_file_on_disk(self, emu):
        emu.drive(8).put("FOO.", b"old", "PRG")
        set_cur_addr(emu, 0x0800)
        run(emu, 's "foo" $0801')
        assert emu.drive(8).get("FOO.") == bytes([0x00, 0x08,
                                                  emu.memory[0x0800],
                                                  emu.memory[0x0801]])


# ── l ───────────────────────────────────────────────────────────────

class TestLoadCommand:
    """`l`: SEQ into the editor, PRG to its header or a given address."""

    def test_load_seq_bare(self, emu):
        """l "foo" → SEQ "foo" into the editor; project = "foo"."""
        emu.drive(8).put("FOO", b"\xa0NOP\r\xa0RTS\r", "SEQ")
        run(emu, 'l "foo"')
        assert editor_text(emu) == b"\xa0NOP\r\xa0RTS\r"
        assert project_name(emu) == b"FOO"
        assert rows(emu) == ['; load "foo"...', "; 3l 10b",
                             "; 00, ok,00,00"]

    def test_load_verbatim_seq(self, emu):
        emu.drive(8).put("FOO", b"\xa0NOP\r", "SEQ")
        run(emu, 'l "foo,s"')
        assert editor_text(emu) == b"\xa0NOP\r"

    def test_load_prg_header_addr(self, emu):
        """l "foo" 0 → PRG "foo." at its header address."""
        emu.drive(8).put("FOO.", b"\x00\xc0\x01\x02\x03")
        run(emu, 'l "foo" 0')
        assert emu.memory[0xC000:0xC003] == [1, 2, 3]
        assert project_name(emu) == b"FOO"

    def test_load_prg_with_addr(self, emu):
        """l "foo" $c000 → PRG "foo." to $c000, whatever its header."""
        emu.drive(8).put("FOO.", b"\x00\x50\x01\x02\x03")
        run(emu, 'l "foo" $c000')
        assert emu.memory[0xC000:0xC003] == [1, 2, 3]
        assert emu.memory[0x5000] != 1 or emu.memory[0x5001] != 2

    def test_load_verbatim_prg(self, emu):
        """l "foo,p" → PRG "foo" (no dot) at its header."""
        emu.drive(8).put("FOO", b"\x00\xc0\x09")
        run(emu, 'l "foo,p"')
        assert emu.memory[0xC000] == 9

    def test_load_verbatim_prg_with_dot(self, emu):
        emu.drive(8).put("FOO.", b"\x00\xc0\x0a")
        run(emu, 'l "foo.,p"')
        assert emu.memory[0xC000] == 0x0A
        assert project_name(emu) == b"FOO"

    @pytest.mark.parametrize("cmd,start", [('l "foo" 0', 0xC000),
                                           ('l "foo" $5000', 0x5000)],
                             ids=["header", "given"])
    def test_load_prg_prints_where_it_landed(self, emu, cmd, start):
        """The range line shows the load's own start and size, not
        cur_addr (here 0)."""
        set_cur_addr(emu, 0)
        emu.drive(8).put("FOO.", b"\x00\xc0\x01\x02\x03")
        run(emu, cmd)
        assert rows(emu) == ['; load "foo."...',
                             f"; prg  {start:04x}-{start + 2:04x}     3b",
                             "; 00, ok,00,00"]

    def test_load_prg_missing_fails_with_the_drive_status(self, emu):
        run(emu, 'l "nope" 0')
        assert rows(emu) == ['; load "nope."...', ";?fail",
                             "; 62,file not found,00,00"]

    @pytest.mark.parametrize("setup,status", [
        (lambda d: None, "; 62,file not found,00,00"),
        (lambda d: d.put("FOO", b"", "SEQ"), "; 00, ok,00,00")],
        ids=["missing", "empty"])
    def test_load_seq_that_fails_reports_fail(self, emu, setup, status):
        """A failed SEQ load is `;?fail`, never a "0l 0b" success line."""
        setup(emu.drive(8))
        run(emu, 'l "foo"')
        assert rows(emu) == ['; load "foo"...', ";?fail", status]

    def test_load_save_symmetry(self, emu):
        """l "foo" then bare s saves SEQ "foo" back."""
        emu.drive(8).put("FOO", b"\xa0NOP\r", "SEQ")
        run(emu, 'l "foo"')
        emu.drive(8).files.clear()
        run(emu, "s")
        assert emu.drive(8).get("FOO") == b"\xa0NOP\r"


# ── unterminated quote ──────────────────────────────────────────────

class TestUnterminatedQuote:
    """repl.md § Argument parsing: an unterminated string is `;?syntax`
    and no disk operation — the drive sees nothing (its power-on status
    is never even read)."""

    @pytest.mark.parametrize("cmd", ['l "foo', 's "foo'])
    def test_no_disk_operation(self, emu, cmd):
        emu.drive(8).put("FOO", b"x", "SEQ")
        run(emu, cmd)
        d = emu.drive(8)
        assert d.status.startswith("73,"), "the drive was addressed"
        assert d.names() == [b"FOO"]

    def test_unterminated_quote_does_not_corrupt_project_name(self, emu):
        set_project_name(emu, b"BAR")
        run(emu, 'l "foo')
        assert project_name(emu) == b"BAR"


# ── $ ───────────────────────────────────────────────────────────────

class TestDirDevice:
    """repl.md § `$`: `$ N` with a decimal N in 4-30 selects device N
    (cur_device) before listing; other numbers keep the current one."""

    @pytest.mark.parametrize("cmd,dev", [("$", 8), ("$ 9", 9), ("$ 30", 30),
                                         ("$ 4", 4), ("$ 3", 8), ("$ 31", 8),
                                         ("$ 255", 8), ("$ 260", 8),
                                         ("$ 1009", 8)])
    def test_device_parse(self, emu, cmd, dev):
        emu.attach_drive(9)
        run(emu, cmd)
        assert emu.memory[emu.sym("cur_device")] == dev

    def test_lists_the_selected_drive_then_its_status(self, emu):
        emu.drive(8).put("EIGHT", b"x")
        emu.attach_drive(9).put("NINE", b"x", "SEQ")
        run(emu, "$ 9")
        assert rows(emu) == ['; "cse test        " 01 2a',
                             'l "nine,s"; 1 blocks',
                             "; 663 blocks free.",
                             "; 00, ok,00,00"]

    def test_device_with_no_drive_lists_nothing(self, emu):
        run(emu, "$ 10")
        assert rows(emu) == [";"]
