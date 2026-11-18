"""test_disk.py — disk.s on the real PRG: with no drive, and on a drive.

Owner: doc/modules/disk.md

Contract source: [disk.md](../../doc/modules/disk.md) (Interface; Design:
no file left open).  Without a drive C64Emu models an empty serial bus,
so every KERNAL OPEN / LOAD on device 8 fails with "device not present"
— the paths a missing or switched-off drive takes.  With
`attach_drive()` a virtual 1541 answers
([testing.md § Virtual IEC drives](../../doc/testing.md#virtual-iec-drives)),
and the transfers run through the KERNAL for real.
"""

import pytest
from c64emu import C64Emu

LDTND = 0x98          # KERNAL: number of open logical files
NAME = 0x3000
RTS_STUB = 0x2F00     # callback for the SEQ calls (never reached)


@pytest.fixture
def emu(cse_prg):
    prg, map_path = cse_prg
    e = C64Emu()
    e.load_prg(prg, map_path)
    e.init_cse()
    e.memory[e.sym("cur_device")] = 8
    for i, c in enumerate(b"FOO\0"):
        e.memory[NAME + i] = c
    e.write_word(e.sym("disk_ptr"), NAME)
    e.memory[RTS_STUB] = 0x60
    return e


def _save_prg(e):
    e.write_word(e.sym("_io_tmp"), 0x4000)
    e.jsr(e.sym("disk_save_prg"), a=4, x=0)


def _save_seq(e):
    e.jsr(e.sym("disk_save_seq"), a=RTS_STUB & 0xFF, x=RTS_STUB >> 8)


def _load_seq(e):
    e.jsr(e.sym("disk_load_seq"), a=RTS_STUB & 0xFF, x=RTS_STUB >> 8)


def _load_prg(e):
    e.jsr(e.sym("disk_load_prg"), a=0, x=0x40)


@pytest.mark.parametrize("call,err_ax", [(_save_prg, (1, 0)), (_save_seq, (1, 0)),
                                         (_load_seq, (1, 0)), (_load_prg, (0, 0))],
                         ids=["save_prg", "save_seq", "load_seq", "load_prg"])
def test_failed_open_leaves_no_file_open(emu, call, err_ax):
    """Device not present: the call returns its error code and the
    KERNAL's file table is empty afterwards (OPEN keeps the entry when
    the device fails; disk.s must close it, on the file's own LFN)."""
    call(emu)
    assert (emu.a, emu.x) == err_ax
    assert emu.memory[LDTND] == 0


@pytest.mark.parametrize("call", [_save_prg, _save_seq, _load_seq],
                         ids=["save_prg", "save_seq", "load_seq"])
def test_second_attempt_fails_for_the_same_reason(emu, call):
    """After a failed call the next one reaches the drive again
    (ST = device not present), not a stale "file open" refusal."""
    call(emu)
    emu.memory[0x90] = 0
    call(emu)
    assert emu.memory[0x90] & 0x80
    assert emu.memory[LDTND] == 0


def test_status_with_no_drive_returns_an_empty_status(emu):
    """floppy_read_status must not hang when no drive answers: the
    KERNAL's CHKIN on a missing serial device waits forever in its
    talk turnaround, so the drive is probed first.  fl_buf is empty
    and no file is left open."""
    fl_buf = emu.sym("fl_buf")
    emu.memory[fl_buf] = 0x41                   # stale content
    emu.jsr(emu.sym("floppy_read_status"), max_cycles=200_000)
    assert emu.memory[fl_buf] == 0
    assert emu.memory[LDTND] == 0


# ── on a drive (testing.md § Virtual IEC drives) ─────────────────────

SAVE_FN = 0x2E00      # read_fn for disk_save_seq: bytes of SRC_BUF, then EOF
LOAD_FN = 0x2D00      # insert_fn for disk_load_seq: bytes into DST_BUF
SRC_BUF, SRC_IDX, SRC_LEN = 0x3100, 0x2EF0, 0x2EF1
DST_BUF, DST_IDX = 0x3400, 0x2DF0

_SAVE_FN_CODE = [0xAC, 0xF0, 0x2E,        # LDY SRC_IDX
                 0xCC, 0xF1, 0x2E,        # CPY SRC_LEN
                 0xB0, 0x09,              # BCS eof
                 0xB9, 0x00, 0x31,        # LDA SRC_BUF,Y
                 0xEE, 0xF0, 0x2E,        # INC SRC_IDX
                 0xA2, 0x00,              # LDX #0
                 0x60,                    # RTS
                 0xA9, 0xFF, 0xAA, 0x60]  # eof: LDA #$FF / TAX / RTS
_LOAD_FN_CODE = [0xAC, 0xF0, 0x2D,        # LDY DST_IDX
                 0x99, 0x00, 0x34,        # STA DST_BUF,Y
                 0xEE, 0xF0, 0x2D,        # INC DST_IDX
                 0x60]


@pytest.fixture
def drv(emu):
    """`emu` with a 1541 as device 8 and the SEQ callbacks in RAM."""
    emu.memory[SAVE_FN:SAVE_FN + len(_SAVE_FN_CODE)] = _SAVE_FN_CODE
    emu.memory[LOAD_FN:LOAD_FN + len(_LOAD_FN_CODE)] = _LOAD_FN_CODE
    emu.memory[SRC_IDX] = emu.memory[DST_IDX] = 0
    return emu, emu.attach_drive(8)


def _name(e, name):
    for i, c in enumerate(name + b"\0"):
        e.memory[NAME + i] = c
    e.write_word(e.sym("disk_ptr"), NAME)


def _fl_buf(e):
    out, a = bytearray(), e.sym("fl_buf")
    while e.memory[a + len(out)]:
        out.append(e.memory[a + len(out)])
    return bytes(out)


class TestLoadPrg:

    def test_to_the_header_address_returns_the_end(self, drv):
        e, d = drv
        d.put("FOO", b"\x00\xc0\x01\x02\x03")
        e.jsr(e.sym("disk_load_prg"), a=0, x=0)
        assert (e.a | e.x << 8) == 0xC003
        assert e.memory[0xC000:0xC003] == [1, 2, 3]
        assert e.memory[LDTND] == 0

    def test_to_the_given_address(self, drv):
        e, d = drv
        d.put("FOO", b"\x00\xc0\x01\x02\x03")
        e.jsr(e.sym("disk_load_prg"), a=0x00, x=0x50)
        assert (e.a | e.x << 8) == 0x5003
        assert e.memory[0x5000:0x5003] == [1, 2, 3]

    @pytest.mark.parametrize("addr,start", [(0, 0xC000), (0x5000, 0x5000)])
    def test_start_address_in_io_tmp(self, drv, addr, start):
        e, d = drv
        d.put("FOO", b"\x00\xc0\x01\x02\x03")
        e.jsr(e.sym("disk_load_prg"), a=addr & 0xFF, x=addr >> 8)
        assert e.read_word(e.sym("_io_tmp")) == start
        assert (e.a | e.x << 8) == start + 3
        assert e.memory[LDTND] == 0

    def test_header_only_file_is_an_error(self, drv):
        """Nothing to load after the address: an error, not a hang."""
        e, d = drv
        d.put("FOO", b"\x00\xc0")
        e.jsr(e.sym("disk_load_prg"), a=0, x=0, max_cycles=200_000)
        assert (e.a, e.x) == (0, 0) and e.memory[LDTND] == 0

    def test_missing_file_returns_0_and_the_drive_says_62(self, drv):
        e, d = drv
        _name(e, b"NOPE")
        e.jsr(e.sym("disk_load_prg"), a=0, x=0)
        assert (e.a, e.x) == (0, 0)
        assert e.memory[LDTND] == 0
        assert _fl_buf(e).startswith(b"62,")


class TestSavePrg:

    def test_header_then_payload_as_a_prg(self, drv):
        e, d = drv
        e.memory[0x4000:0x4004] = [0xA9, 0x01, 0xEA, 0x60]
        _save_prg(e)
        assert d.get("FOO") == b"\x00\x40\xa9\x01\xea\x60"
        assert d.find("FOO").type == "PRG"
        assert (e.a, e.x) == (0, 0) and e.memory[LDTND] == 0

    def test_replaces_an_existing_file(self, drv):
        e, d = drv
        d.put("FOO", b"old", "PRG")
        _save_prg(e)
        assert d.names() == [b"FOO"] and d.get("FOO")[:2] == b"\x00\x40"

    def test_sent_as_at_name_p_w(self, drv):
        e, d = drv
        _save_prg(e)
        ob = e.sym("open_buf")
        assert bytes(e.memory[ob:ob + 9]) == b"@:FOO,P,W"


class TestSeq:

    def test_save_writes_a_seq_and_counts(self, drv):
        e, d = drv
        text = b"\xa0NOP\r\xa0RTS\r"
        e.memory[SRC_BUF:SRC_BUF + len(text)] = list(text)
        e.memory[SRC_LEN] = len(text)
        e.jsr(e.sym("disk_save_seq"), a=SAVE_FN & 0xFF, x=SAVE_FN >> 8)
        assert (e.a, e.x) == (0, 0)
        assert d.get("FOO") == text and d.find("FOO").type == "SEQ"
        assert e.read_word(e.sym("disk_seq_bytes")) == len(text)
        assert e.read_word(e.sym("disk_seq_lines")) == 3
        assert e.memory[LDTND] == 0

    def test_load_reads_every_byte_and_counts(self, drv):
        e, d = drv
        text = b"\xa0NOP\r\xa0RTS"
        d.put("FOO", text, "SEQ")
        e.jsr(e.sym("disk_load_seq"), a=LOAD_FN & 0xFF, x=LOAD_FN >> 8)
        assert (e.a, e.x) == (0, 0)
        assert bytes(e.memory[DST_BUF:DST_BUF + len(text)]) == text
        assert e.memory[DST_IDX] == len(text)
        assert e.read_word(e.sym("disk_seq_bytes")) == len(text)
        assert e.read_word(e.sym("disk_seq_lines")) == 2
        assert e.memory[LDTND] == 0

    def test_load_of_a_missing_file_is_an_error(self, drv):
        e, d = drv
        _name(e, b"NOPE")
        e.jsr(e.sym("disk_load_seq"), a=LOAD_FN & 0xFF, x=LOAD_FN >> 8)
        assert (e.a, e.x) == (1, 0)
        assert _fl_buf(e).startswith(b"62,") and e.memory[LDTND] == 0

    def test_load_of_an_empty_file_is_an_error(self, drv):
        e, d = drv
        d.put("FOO", b"", "SEQ")
        e.jsr(e.sym("disk_load_seq"), a=LOAD_FN & 0xFF, x=LOAD_FN >> 8)
        assert (e.a, e.x) == (1, 0)


class TestFloppyStatus:

    def test_read_status_fills_fl_buf_without_the_cr(self, drv):
        e, d = drv
        e.jsr(e.sym("floppy_read_status"))
        assert _fl_buf(e) == b"73,CBM DOS V2.6 1541,00,00"
        e.jsr(e.sym("floppy_read_status"))
        assert _fl_buf(e) == b"00, OK,00,00"
        assert e.memory[LDTND] == 0

    def test_floppy_status_prints_it(self, drv):
        e, d = drv
        e.set_cursor(3, 0)
        e.jsr(e.sym("floppy_status"))
        assert e.screen_text(3) == "; 73,cbm dos v2.6 1541,00,00"


class TestListDirectory:

    def _list(self, e, dev=8):
        e.set_cursor(2, 0)
        e.jsr(e.sym("list_directory"), a=dev, max_cycles=2_000_000)
        return [e.screen_text(r) for r in range(2, 25) if e.screen_text(r)]

    def test_header_files_and_blocks_free(self, drv):
        e, d = drv
        d.put("FOO", bytes(254 * 12), "PRG")
        d.put("SRC", b"x", "SEQ")
        assert self._list(e) == ['; "cse test        " 01 2a',
                                 'l "foo,p"; 12 blocks',
                                 'l "src,s"; 1 blocks',
                                 '; 651 blocks free.']

    def test_header_is_reversed_from_its_quote(self, drv):
        e, d = drv
        self._list(e)
        row = e.screen_row(2)
        assert [c & 0x80 for c in row[:2]] == [0, 0]       # "; "
        assert all(c & 0x80 for c in row[2:2 + 18])        # "name"
        assert row[3:11] == [0x83, 0x93, 0x85, 0xA0, 0x94, 0x85, 0x93, 0x94]

    def test_empty_disk(self, drv):
        e, d = drv
        assert self._list(e)[1:] == ['; 664 blocks free.']

    def test_other_device(self, drv):
        e, _ = drv
        e.attach_drive(9).put("NINE", b"x")
        assert self._list(e, 9)[1] == 'l "nine,p"; 1 blocks'

    def test_d64_image(self, drv, tmp_path):
        import pathlib
        from c64emu import Drive1541
        e, _ = drv
        e.attach_drive(10, Drive1541.from_d64(
            pathlib.Path(__file__).resolve().parents[2] / "dev" / "test.d64"))
        rows = self._list(e, 10)
        assert rows[0] == '; "testprg         " 23 2a'
        assert rows[1] == 'l "t-count,s"; 1 blocks' and len(rows) == 11

    def test_stop_breaks_the_listing(self, drv):
        """STOP waiting in the keyboard buffer ends the listing after
        the entry in progress, with the break message."""
        e, d = drv
        for i in range(5):
            d.put(f"F{i}", b"x")
        e.inject_key(3)                           # STOP queued
        assert self._list(e) == ['; "cse test        " 01 2a', "break"]
        assert e.memory[0xC6] == 0, "the key was taken"

    def test_another_key_is_dropped_and_the_listing_goes_on(self, drv):
        e, d = drv
        for i in range(5):
            d.put(f"F{i}", b"x")
        e.inject_key(0x41)
        rows = self._list(e)
        assert len(rows) == 7 and rows[-1] == "; 659 blocks free."
        assert e.memory[0xC6] == 0

    def test_no_drive_lists_nothing(self, emu):
        emu.set_cursor(2, 0)
        emu.jsr(emu.sym("list_directory"), a=8)
        assert all(not emu.screen_text(r) for r in range(2, 25))


class TestDriveStatusAfterTransfer:
    """Each transfer leaves the drive's status in fl_buf; a save the
    drive refuses (status code not 0x) is an error."""

    def _save_seq(self, e, text=b"X\r"):
        e.memory[SRC_BUF:SRC_BUF + len(text)] = list(text)
        e.memory[SRC_LEN] = len(text)
        e.jsr(e.sym("disk_save_seq"), a=SAVE_FN & 0xFF, x=SAVE_FN >> 8)

    @pytest.mark.parametrize("save", ["prg", "seq"])
    def test_write_protected_save_is_an_error(self, drv, save):
        e, d = drv
        d.write_protect = True
        _save_prg(e) if save == "prg" else self._save_seq(e)
        assert (e.a, e.x) == (1, 0)
        assert _fl_buf(e) == b"26,WRITE PROTECT ON,00,00"
        assert d.files == [] and e.memory[LDTND] == 0

    def test_disk_full_save_is_an_error(self, drv):
        e, d = drv
        d.put("BIG", bytes(254 * 664))
        self._save_seq(e)
        assert (e.a, e.x) == (1, 0)
        assert _fl_buf(e) == b"72,DISK FULL,00,00"

    @pytest.mark.parametrize("save", ["prg", "seq"])
    def test_saved_status_is_ok(self, drv, save):
        e, d = drv
        _save_prg(e) if save == "prg" else self._save_seq(e)
        assert (e.a, e.x) == (0, 0)
        assert _fl_buf(e) == b"00, OK,00,00"

    def test_load_prg_leaves_the_status(self, drv):
        e, d = drv
        _name(e, b"NOPE")
        e.jsr(e.sym("disk_load_prg"), a=0, x=0)
        assert _fl_buf(e) == b"62,FILE NOT FOUND,00,00"
        d.put("NOPE", b"\x00\xc0\x01")
        e.jsr(e.sym("disk_load_prg"), a=0, x=0)
        assert (e.a | e.x << 8) == 0xC001
        assert _fl_buf(e) == b"00, OK,00,00"

    def test_load_seq_leaves_the_status(self, drv):
        e, d = drv
        _name(e, b"NOPE")
        e.jsr(e.sym("disk_load_seq"), a=LOAD_FN & 0xFF, x=LOAD_FN >> 8)
        assert _fl_buf(e) == b"62,FILE NOT FOUND,00,00"

    def test_no_drive_leaves_it_empty(self, emu):
        fl = emu.sym("fl_buf")
        emu.memory[fl] = 0x41
        _save_prg(emu)
        assert emu.memory[fl] == 0


# KERNAL I/O vectors (the jump table at $FFC0.. goes through them).
IOPEN, ICLOSE, ICKOUT, ICLRCH, IBSOUT = 0x031A, 0x031C, 0x0320, 0x0322, 0x0326
STUB_OK = 0x2F10        # clc / rts — OPEN and CHKOUT succeed
STUB_OUT = 0x2F20       # CHROUT: append A to OUT_BUF, keep X / Y
OUT_BUF, OUT_IDX = 0x2E00, 0x2DFF


def test_save_prg_payload_leaves_code_read_only(emu, cse_prg):
    """memory_design.md § Design Principles (no self-modifying code):
    a PRG save that reaches its payload loop writes no byte of disk.s's
    CODE.  OPEN / CHKOUT / CHROUT are redirected through the KERNAL
    vectors, so the save runs to completion on the empty serial bus."""
    import re, pathlib
    e = emu
    for i, b in enumerate((0x18, 0x60)):
        e.memory[STUB_OK + i] = b
    # stx $2DFE / ldx OUT_IDX / sta OUT_BUF,x / inc OUT_IDX / ldx $2DFE / clc / rts
    stub = [0x8E, 0xFE, 0x2D, 0xAE, 0xFF, 0x2D, 0x9D, 0x00, 0x2E,
            0xEE, 0xFF, 0x2D, 0xAE, 0xFE, 0x2D, 0x18, 0x60]
    for i, b in enumerate(stub):
        e.memory[STUB_OUT + i] = b
    e.memory[OUT_IDX] = 0
    for vec, tgt in ((IOPEN, STUB_OK), (ICKOUT, STUB_OK), (IBSOUT, STUB_OUT),
                     (ICLOSE, RTS_STUB), (ICLRCH, RTS_STUB)):
        e.write_word(vec, tgt)
    for i in range(0x102):
        e.memory[0x4000 + i] = (i * 7) & 0xFF
    text = pathlib.Path(cse_prg[1]).read_text()
    m = re.search(r"^disk\.o:\n\s+CODE\s+Offs=([0-9A-F]+)\s+Size=([0-9A-F]+)",
                  text, re.M)
    start = e.sym("__CODE_RUN__") + int(m.group(1), 16)
    size = int(m.group(2), 16)
    before = bytes(e.memory[start + i] for i in range(size))
    e.write_word(e.sym("_io_tmp"), 0x4000)
    e.jsr(e.sym("disk_save_prg"), a=0x02, x=0x01)      # $0102 bytes
    assert e.a == 0
    after = bytes(e.memory[start + i] for i in range(size))
    diff = [hex(start + i) for i in range(size) if before[i] != after[i]]
    assert diff == [], f"disk.s CODE written at {diff}"
    # 2 header + $102 payload bytes; the 256-byte capture ring wraps,
    # so its first 4 slots hold stream bytes 256..259 = payload 254..257.
    stream = bytes((0x00, 0x40)) + bytes((i * 7) & 0xFF for i in range(0x102))
    out = bytes(e.memory[OUT_BUF + i] for i in range(256))
    assert e.memory[OUT_IDX] == len(stream) & 0xFF
    assert out == stream[256:] + stream[len(stream) - 256:256]
