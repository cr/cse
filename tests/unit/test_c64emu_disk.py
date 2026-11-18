"""test_c64emu_disk.py — C64Emu's virtual IEC drive.

Owner: doc/build_system.md

Contract source: [testing.md § Virtual IEC drives](../../doc/testing.md#virtual-iec-drives).

Two layers: the `Drive1541` model on its own (the DOS as the bus sees
it: channels, commands, status, directory, the D64 reader), and the
drive on C64Emu's serial bus under the real C64 KERNAL (OPEN, CHKIN,
CHRIN, CHKOUT, CHROUT, CLOSE, LOAD, SAVE called in the ROM).
"""

import pathlib

import pytest

from c64emu import C64Emu, Drive1541, cbm_blocks, cbm_match

ROOT = pathlib.Path(__file__).resolve().parents[2]
ST = 0x90


def read_all(drive, ch):
    """Every byte the drive TALKs on `ch` until EOI (or nothing)."""
    out = bytearray()
    while True:
        got = drive.read(ch)
        if got is None:
            return bytes(out)
        out.append(got[0])
        if got[1]:
            return bytes(out)


def write_file(drive, ch, name, data):
    drive.open(ch, name)
    for b in data:
        drive.write(ch, b)
    drive.unlisten(ch)
    drive.close(ch)


# ── the model ────────────────────────────────────────────────────────

class TestStatus:

    def test_power_on_message(self):
        assert Drive1541().status == "73,CBM DOS V2.6 1541,00,00"

    def test_status_is_sent_with_cr_eoi_on_the_cr_then_clears(self):
        d = Drive1541()
        sent = []
        while True:
            byte, eoi = d.read(15)
            sent.append((byte, eoi))
            if eoi:
                break
        assert bytes(b for b, _ in sent) == b"73,CBM DOS V2.6 1541,00,00\r"
        assert [e for _, e in sent].count(True) == 1
        assert d.status == "00, OK,00,00"

    def test_ok_after_a_successful_open(self):
        d = Drive1541()
        d.put("FOO", b"x")
        d.open(2, b"FOO")
        assert d.status == "00, OK,00,00"


class TestRead:

    def test_bytes_in_order_eoi_on_the_last(self):
        d = Drive1541()
        d.put("FOO", b"ABC", "SEQ")
        d.open(2, b"FOO,S,R")
        assert [d.read(2) for _ in range(3)] == [(0x41, False), (0x42, False),
                                                (0x43, True)]
        assert d.read(2) is None, "read out: nothing more to send"

    def test_missing_file_62_and_nothing_to_send(self):
        d = Drive1541()
        d.open(2, b"NOPE,S,R")
        assert d.status == "62,FILE NOT FOUND,00,00"
        assert d.read(2) is None

    def test_type_given_must_match(self):
        d = Drive1541()
        d.put("FOO", b"x", "PRG")
        d.open(2, b"FOO,S,R")
        assert d.status.startswith("64,FILE TYPE MISMATCH")

    def test_no_type_reads_any_type_and_channel_0_reads(self):
        d = Drive1541()
        d.put("FOO", b"xy", "SEQ")
        d.open(0, b"FOO")
        assert read_all(d, 0) == b"xy"

    def test_wildcards_take_the_first_match(self):
        d = Drive1541()
        d.put("ALPHA", b"1")
        d.put("ABBA", b"2")
        d.open(2, b"A*")
        assert read_all(d, 2) == b"1"
        d.open(3, b"AB?A")
        assert read_all(d, 3) == b"2"

    def test_drive_prefix_is_skipped(self):
        d = Drive1541()
        d.put("FOO", b"z")
        d.open(2, b"0:FOO")
        assert read_all(d, 2) == b"z"


class TestWrite:

    def test_committed_on_close_seq_by_default(self):
        d = Drive1541()
        d.open(2, b"OUT,W")
        d.write(2, 0x41)
        assert d.find("OUT") is None, "not on the disk before CLOSE"
        d.close(2)
        assert d.get("OUT") == b"A" and d.find("OUT").type == "SEQ"

    def test_channel_1_writes_a_prg(self):
        d = Drive1541()
        write_file(d, 1, b"PROG", b"\x00\xc0\xea")
        assert d.find("PROG").type == "PRG"

    def test_existing_without_at_is_63_and_untouched(self):
        d = Drive1541()
        d.put("FOO", b"old", "SEQ")
        write_file(d, 2, b"FOO,S,W", b"new")
        assert d.status.startswith("63,FILE EXISTS")
        assert d.get("FOO") == b"old"

    def test_at_replaces_in_its_directory_slot(self):
        d = Drive1541()
        d.put("A", b"1")
        d.put("FOO", b"old", "SEQ")
        d.put("B", b"2")
        write_file(d, 2, b"@:FOO,S,W", b"new")
        assert d.names() == [b"A", b"FOO", b"B"]
        assert d.get("FOO") == b"new"

    def test_append(self):
        d = Drive1541()
        d.put("LOG", b"ab", "SEQ")
        write_file(d, 2, b"LOG,S,A", b"cd")
        assert d.get("LOG") == b"abcd"

    def test_write_protect_is_26_and_nothing_written(self):
        d = Drive1541()
        d.write_protect = True
        write_file(d, 2, b"OUT,S,W", b"x")
        assert d.status.startswith("26,WRITE PROTECT ON")
        assert d.files == []

    def test_wildcard_in_a_written_name_is_33(self):
        d = Drive1541()
        d.open(2, b"OU*,S,W")
        assert d.status.startswith("33,SYNTAX ERROR")

    def test_no_name_is_34(self):
        d = Drive1541()
        d.open(2, b",S,W")
        assert d.status.startswith("34,SYNTAX ERROR")

    def test_disk_full_is_72_and_the_file_dropped(self):
        d = Drive1541()
        d.put("BIG", bytes(254 * 660))
        write_file(d, 2, b"MORE,W", bytes(254 * 5))
        assert d.status.startswith("72,DISK FULL")
        assert d.find("MORE") is None

    def test_closing_15_closes_every_channel(self):
        d = Drive1541()
        d.open(2, b"OUT,S,W")
        d.write(2, 0x41)
        d.close(15)
        assert d.get("OUT") == b"A"
        d.write(2, 0x42)                        # channel 2 is closed now
        assert d.get("OUT") == b"A"


class TestCommands:

    def _cmd(self, d, text, via_open=False):
        if via_open:
            d.open(15, text)
        else:
            for b in text + b"\r":
                d.write(15, b)
            d.unlisten(15)

    @pytest.mark.parametrize("via_open", [False, True])
    def test_scratch_with_wildcards_counts_and_spares_locked(self, via_open):
        d = Drive1541()
        for n in ("FOO", "FOX", "BAR"):
            d.put(n, b"x")
        d.find("FOX").locked = True
        self._cmd(d, b"S0:FO*,BAR", via_open)
        assert d.status == "01,FILES SCRATCHED,02,00"
        assert d.names() == [b"FOX"]

    def test_scratch_nothing_matched(self):
        d = Drive1541()
        self._cmd(d, b"S:NONE")
        assert d.status == "01,FILES SCRATCHED,00,00"

    def test_scratch_write_protected(self):
        d = Drive1541()
        d.put("FOO", b"x")
        d.write_protect = True
        self._cmd(d, b"S:FOO")
        assert d.status.startswith("26,") and d.names() == [b"FOO"]

    def test_rename(self):
        d = Drive1541()
        d.put("OLD", b"x")
        d.put("TAKEN", b"y")
        self._cmd(d, b"R:NEW=OLD")
        assert d.status.startswith("00,") and d.names() == [b"NEW", b"TAKEN"]
        self._cmd(d, b"R:TAKEN=NEW")
        assert d.status.startswith("63,")
        self._cmd(d, b"R:X=GONE")
        assert d.status.startswith("62,")

    def test_new_empties_the_disk_and_sets_name_and_id(self):
        d = Drive1541()
        d.put("FOO", b"x")
        self._cmd(d, b"N:WORK,77")
        assert d.files == [] and d.disk_name == b"WORK" and d.disk_id == b"77"

    def test_initialize_ok_unknown_31_reset_73(self):
        d = Drive1541()
        self._cmd(d, b"I0")
        assert d.status.startswith("00,")
        self._cmd(d, b"Z")
        assert d.status.startswith("31,SYNTAX ERROR")
        self._cmd(d, b"UJ")
        assert d.status.startswith("73,")


class TestDirectory:

    def test_format_as_the_1541_sends_it(self):
        d = Drive1541(b"MY DISK", b"ID")
        d.put("FOO", bytes(300), "SEQ")
        d.find("FOO").locked = True
        d.open(0, b"$")
        data = read_all(d, 0)
        hdr = b"\x12\"MY DISK" + b"\xa0" * 9 + b"\" ID\xa02A"
        foo = (b"   \"FOO\"" + b" " * 13 + b" SEQ<").ljust(27, b" ")
        free = b"BLOCKS FREE.".ljust(25, b" ")
        assert data == (b"\x01\x04"
                        + b"\x01\x01\x00\x00" + hdr + b"\x00"
                        + b"\x01\x01\x02\x00" + foo + b"\x00"
                        + b"\x01\x01" + (664 - 2).to_bytes(2, "little") + free + b"\x00"
                        + b"\x00\x00")

    @pytest.mark.parametrize("blocks,lead", [(1, 3), (10, 2), (100, 1)])
    def test_leading_spaces_align_the_names(self, blocks, lead):
        d = Drive1541()
        d.put("F", bytes(254 * blocks))
        text = d.directory().split(b"\x00\x01\x01")[1]
        assert int.from_bytes(text[:2], "little") == blocks
        assert text[2:].startswith(b" " * lead + b"\"F\"")

    def test_pattern(self):
        d = Drive1541()
        d.put("ABC", b"1")
        d.put("XYZ", b"2")
        listing = d.directory(b":A*")
        assert b"\"ABC\"" in listing and b"XYZ" not in listing

    def test_blocks(self):
        assert [cbm_blocks(n) for n in (0, 1, 254, 255, 508)] == [1, 1, 1, 2, 2]

    @pytest.mark.parametrize("pat,name,hit", [
        (b"FOO", b"FOO", True), (b"FOO", b"FOOD", False), (b"FO?", b"FOX", True),
        (b"F*", b"FANCY", True), (b"*", b"X", True), (b"FOO*", b"FO", False)])
    def test_cbm_match(self, pat, name, hit):
        assert cbm_match(pat, name) is hit


class TestD64:

    def test_reads_the_name_id_and_files_of_test_d64(self):
        d = Drive1541.from_d64(ROOT / "dev" / "test.d64")
        assert (d.disk_name, d.disk_id) == (b"TESTPRG", b"23")
        assert d.names() == [b"T-COUNT", b"T-LEGAL", b"T-CMOS", b"T-ILLEGAL",
                             b"T-DIR", b"T-EXPR", b"T-CHK", b"T-HELLO", b"T-ORG"]
        assert {f.type for f in d.files} == {"SEQ"}
        assert [f.blocks for f in d.files] == [1, 8, 2, 7, 3, 3, 13, 4, 1]

    def test_a_file_reads_to_its_last_byte(self):
        d = Drive1541.from_d64(ROOT / "dev" / "test.d64")
        data = d.get("T-HELLO")
        assert data and data.endswith(b"\r") and 0 not in data


# ── on the bus, under the real KERNAL ────────────────────────────────

SETLFS, SETNAM, OPEN, CLOSE = 0xFFBA, 0xFFBD, 0xFFC0, 0xFFC3
CHKIN, CHKOUT, CLRCHN, CHRIN, CHROUT = 0xFFC6, 0xFFC9, 0xFFCC, 0xFFCF, 0xFFD2
LOAD, SAVE = 0xFFD5, 0xFFD8
NAME = 0x0340


class Kernal:
    """The KERNAL's file calls, one jsr() each."""

    def __init__(self, emu):
        self.e = emu

    def setnam(self, name):
        for i, c in enumerate(name):
            self.e.memory[NAME + i] = c
        self.e.jsr(SETNAM, a=len(name), x=NAME & 0xFF, y=NAME >> 8)

    def open(self, lfn, dev, sa, name=b""):
        self.e.memory[ST] = 0
        self.setnam(name)
        self.e.jsr(SETLFS, a=lfn, x=dev, y=sa)
        self.e.jsr(OPEN)
        return self.e.carry

    def load(self, name, dev, sa, addr=0):
        self.e.memory[ST] = 0
        self.setnam(name)
        self.e.jsr(SETLFS, a=1, x=dev, y=sa)
        self.e.jsr(LOAD, a=0, x=addr & 0xFF, y=addr >> 8)
        return self.e.carry, self.e.a, self.e.x | self.e.y << 8

    def read_channel(self, lfn):
        self.e.jsr(CHKIN, x=lfn)
        out = bytearray()
        while not self.e.memory[ST]:
            self.e.jsr(CHRIN)
            out.append(self.e.a)
        st = self.e.memory[ST]
        self.e.jsr(CLRCHN)
        return bytes(out), st

    def write_channel(self, lfn, data):
        self.e.jsr(CHKOUT, x=lfn)
        for b in data:
            self.e.jsr(CHROUT, a=b)
        self.e.jsr(CLRCHN)


@pytest.fixture
def emu():
    return C64Emu()


class TestKernalOnTheBus:

    def test_load_to_the_header_address(self, emu):
        d = emu.attach_drive(8)
        d.put("HELLO", b"\x00\xc0\x01\x02\x03")
        carry, _, end = Kernal(emu).load(b"HELLO", 8, 1)
        assert not carry and end == 0xC003
        assert emu.memory[0xC000:0xC003] == [1, 2, 3]

    def test_load_to_the_given_address(self, emu):
        emu.attach_drive(8).put("HELLO", b"\x00\xc0\x07\x08")
        carry, _, end = Kernal(emu).load(b"HELLO", 8, 0, 0x2000)
        assert not carry and end == 0x2002
        assert emu.memory[0x2000:0x2002] == [7, 8]

    def test_load_of_a_missing_file_is_error_4(self, emu):
        d = emu.attach_drive(8)
        carry, err, _ = Kernal(emu).load(b"NOPE", 8, 1)
        assert carry and err == 4
        assert emu.memory[ST] & 0x02
        assert d.status.startswith("62,")

    def test_a_device_with_no_drive_is_not_present(self, emu):
        emu.attach_drive(8)
        carry, err, _ = Kernal(emu).load(b"X", 9, 1)
        assert carry and err == 5 and emu.memory[ST] == 0x80

    def test_load_directory(self, emu):
        d = emu.attach_drive(8)
        d.put("FOO", b"\x01\x08x")
        carry, _, end = Kernal(emu).load(b"$", 8, 0, 0x0801)
        assert not carry
        assert bytes(emu.memory[0x0801:end]) == d.directory()[2:]

    def test_save_writes_a_prg_with_its_header(self, emu):
        d = emu.attach_drive(8)
        k = Kernal(emu)
        for i, b in enumerate(b"\xa9\x01\x60"):
            emu.memory[0xC000 + i] = b
        k.setnam(b"PROG")
        emu.jsr(SETLFS, a=1, x=8, y=1)
        emu.write_word(0xFB, 0xC000)
        emu.jsr(SAVE, a=0xFB, x=0x03, y=0xC0)
        assert not emu.carry
        assert d.get("PROG") == b"\x00\xc0\xa9\x01\x60"
        assert d.find("PROG").type == "PRG"

    def test_seq_write_then_read_through_channels(self, emu):
        d = emu.attach_drive(8)
        k = Kernal(emu)
        assert not k.open(2, 8, 2, b"NOTES,S,W")
        k.write_channel(2, b"HI\rTHERE\r")
        emu.jsr(CLOSE, a=2)
        assert d.get("NOTES") == b"HI\rTHERE\r"
        assert not k.open(3, 8, 3, b"NOTES,S,R")
        data, st = k.read_channel(3)
        emu.jsr(CLOSE, a=3)
        assert data == b"HI\rTHERE\r" and st == 0x40
        assert emu.memory[0x98] == 0, "no file left open"

    def test_chrin_from_a_missing_file_returns_cr_with_st_42(self, emu):
        emu.attach_drive(8)
        k = Kernal(emu)
        k.open(2, 8, 2, b"NOPE,S,R")
        data, st = k.read_channel(2)
        assert data == b"\r" and st == 0x42

    def test_command_and_status_through_channel_15(self, emu):
        d = emu.attach_drive(8)
        d.put("FOO", b"x")
        k = Kernal(emu)
        k.open(15, 8, 15, b"S:FOO")
        status, _ = k.read_channel(15)
        emu.jsr(CLOSE, a=15)
        assert status == b"01,FILES SCRATCHED,01,00\r"
        assert d.names() == []

    def test_command_printed_to_channel_15(self, emu):
        d = emu.attach_drive(8)
        d.put("OLD", b"x")
        k = Kernal(emu)
        k.open(15, 8, 15)
        k.write_channel(15, b"R:NEW=OLD\r")
        emu.jsr(CLOSE, a=15)
        assert d.names() == [b"NEW"]

    def test_devices_8_to_11_each_their_own_disk(self, emu):
        for dev in (8, 11):
            emu.attach_drive(dev).put("WHO", bytes([0, 0xC0, dev]))
        for dev in (8, 11):
            Kernal(emu).load(b"WHO", dev, 1)
            assert emu.memory[0xC000] == dev
        with pytest.raises(ValueError):
            emu.attach_drive(12)

    def test_detach_leaves_the_empty_bus(self, emu):
        emu.attach_drive(8)
        emu.detach_drive(8)
        carry, err, _ = Kernal(emu).load(b"X", 8, 1)
        assert carry and err == 5 and emu.memory[ST] == 0x80
        assert emu._traps == {}


class TestTraps:
    """EmuBase.add_trap: the hook the bus is built on."""

    def test_a_trap_that_leaves_pc_lets_the_instruction_run(self, emu):
        emu.memory[0x2000:0x2003] = [0xA9, 0x42, 0x60]      # LDA #$42 / RTS
        seen = []
        emu.add_trap(0x2000, lambda e: seen.append(e.a))
        emu.jsr(0x2000, a=7)
        assert seen == [7] and emu.a == 0x42

    def test_a_trap_that_moves_pc_replaces_the_routine(self, emu):
        emu.memory[0x2000:0x2003] = [0xA9, 0x42, 0x60]

        def stand_in(e):
            e.a = 0x99
            e._rts()
        emu.add_trap(0x2000, stand_in)
        emu.jsr(0x2000)
        assert emu.a == 0x99
        emu.remove_trap(0x2000)
        emu.jsr(0x2000)
        assert emu.a == 0x42
