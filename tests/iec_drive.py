"""iec_drive.py — the virtual IEC drive shared by C64Emu and M65Emu.

Owner: doc/build_system.md

Contract source: [doc/testing.md § Virtual IEC drives](../doc/testing.md#virtual-iec-drives).

A Drive1541 (an in-memory 1541: files, channels, the DOS status) on an
IECBus that traps the KERNAL's serial routines.  EmuBase.attach_drive()
puts one on a unit; the status byte is the KERNAL's ST, $90 on both
machines (on the MEGA65 in base page 0, where READSS reads it).
"""

import pathlib

ST = 0x90                       # KERNAL I/O status byte
ST_TIMEOUT_READ = 0x02
ST_EOI = 0x40

BLOCKS_TOTAL = 664              # a formatted 1541 disk
DIR_LOAD_ADDR = 0x0401          # the "$" file's load address

_DOS_MESSAGES = {
    0: " OK", 1: "FILES SCRATCHED", 26: "WRITE PROTECT ON",
    30: "SYNTAX ERROR", 31: "SYNTAX ERROR", 33: "SYNTAX ERROR",
    34: "SYNTAX ERROR", 61: "FILE NOT OPEN", 62: "FILE NOT FOUND",
    63: "FILE EXISTS", 64: "FILE TYPE MISMATCH", 72: "DISK FULL",
    73: "CBM DOS V2.6 1541",
}
_TYPE_LETTERS = {0x53: "SEQ", 0x50: "PRG", 0x55: "USR", 0x4C: "REL"}
_MODE_LETTERS = {0x52: "R", 0x57: "W", 0x41: "A", 0x4D: "M"}
_D64_TYPES = {0: "DEL", 1: "SEQ", 2: "PRG", 3: "USR", 4: "REL"}


def _name_bytes(name):
    """A file name as PETSCII bytes (a str is taken byte for byte)."""
    return name.encode("latin-1") if isinstance(name, str) else bytes(name)


def cbm_blocks(size):
    """Blocks a file of `size` bytes takes (254 data bytes each; an
    empty file still takes one)."""
    return max(1, -(-size // 254))


def cbm_match(pattern, name):
    """CBM DOS name matching: `?` matches any one byte, `*` the rest."""
    for i, c in enumerate(pattern):
        if c == 0x2A:
            return True
        if i >= len(name) or (c != 0x3F and c != name[i]):
            return False
    return len(pattern) == len(name)


class DiskFile:
    """One directory entry: name (PETSCII bytes), type, data."""

    def __init__(self, name, data=b"", type="PRG", locked=False):
        self.name = _name_bytes(name)
        self.data = bytes(data)
        self.type = type
        self.locked = locked

    @property
    def blocks(self):
        return cbm_blocks(len(self.data))


class _Channel:
    """An open data channel: a read cursor or a write buffer."""

    def __init__(self, mode, data=b"", name=None, type=None, replace=None):
        self.mode = mode            # "R" or "W"
        self.data = bytearray(data)
        self.pos = 0
        self.name = name            # W: the file to commit on close
        self.type = type
        self.replace = replace      # W: the entry it replaces, or None


class Drive1541:
    """An in-memory 1541: a directory of named files and the DOS seen
    from the bus — channels 0-14 for files, 15 for commands and the
    status.  No disk geometry, no timing."""

    def __init__(self, disk_name=b"CSE TEST", disk_id=b"01"):
        self.disk_name = _name_bytes(disk_name)
        self.disk_id = _name_bytes(disk_id)
        self.files = []             # DiskFile, in directory order
        self.write_protect = False
        self._channels = {}
        self._cmd = bytearray()
        self.set_status(73)         # the power-on message

    # ── the host side (what a test sets up and checks) ──

    def put(self, name, data, type="PRG"):
        """Write a file straight onto the disk (replacing one of the
        same name); return its entry."""
        entry = DiskFile(name, data, type)
        old = self.find(entry.name)
        if old is not None:
            self.files[self.files.index(old)] = entry
        else:
            self.files.append(entry)
        return entry

    def find(self, name):
        """The first entry matching `name` (CBM wildcards), or None."""
        name = _name_bytes(name)
        return next((f for f in self.files if cbm_match(name, f.name)), None)

    def get(self, name):
        """The data of file `name`; KeyError if the disk has none."""
        entry = self.find(name)
        if entry is None:
            raise KeyError(f"no file {name!r} on the disk")
        return entry.data

    def names(self):
        return [f.name for f in self.files]

    @property
    def blocks_free(self):
        return BLOCKS_TOTAL - sum(f.blocks for f in self.files)

    @property
    def status(self):
        """The error channel's message, as the drive would send it."""
        return self._status.decode("latin-1")

    def set_status(self, code, track=0, sector=0):
        self._status = (f"{code:02d},{_DOS_MESSAGES[code]},"
                        f"{track:02d},{sector:02d}").encode("latin-1")
        self._status_pos = 0

    # ── the DOS (what the bus calls) ──

    def open(self, ch, name):
        """OPEN on channel `ch` with the name sent under it."""
        name = bytes(name)
        if ch == 15:
            if name:
                self._command(name)
            return
        self._channels.pop(ch, None)
        if name[:1] == b"$":
            self._channels[ch] = _Channel("R", self.directory(name[1:]))
            self.set_status(0)
            return
        replace = name[:1] == b"@"
        if replace:
            name = name[1:]
        if b":" in name:
            drv, _, rest = name.partition(b":")
            if drv.isdigit() or not drv:
                name = rest
        fname, *params = name.split(b",")
        ftype = mode = None
        for p in params:
            if p[:1] and p[0] in _TYPE_LETTERS and ftype is None and mode is None:
                ftype = _TYPE_LETTERS[p[0]]
            elif p[:1] and p[0] in _MODE_LETTERS:
                mode = _MODE_LETTERS[p[0]]
            else:
                return self.set_status(30)
        if mode is None:
            mode = "W" if ch == 1 else "R"
        if not fname:
            return self.set_status(34)
        if mode == "R":
            entry = self.find(fname)
            if entry is None:
                return self.set_status(62)
            if ftype is not None and entry.type != ftype:
                return self.set_status(64)
            self._channels[ch] = _Channel("R", entry.data)
            return self.set_status(0)
        if mode not in ("W", "A"):
            return self.set_status(31)
        if b"*" in fname or b"?" in fname:
            return self.set_status(33)
        if self.write_protect:
            return self.set_status(26)
        entry = self.find(fname)
        if mode == "A":
            if entry is None:
                return self.set_status(62)
            self._channels[ch] = _Channel("W", entry.data, entry.name,
                                          entry.type, entry)
            return self.set_status(0)
        if entry is not None and not replace:
            return self.set_status(63)
        ftype = ftype or ("PRG" if ch == 1 else "SEQ")
        self._channels[ch] = _Channel("W", b"", fname, ftype, entry)
        self.set_status(0)

    def close(self, ch):
        """CLOSE: a written file is committed now.  Closing channel 15
        closes every channel."""
        for c in (list(self._channels) if ch == 15 else [ch]):
            chan = self._channels.pop(c, None)
            if chan is None or chan.mode != "W":
                continue
            entry = DiskFile(chan.name, chan.data, chan.type)
            used = sum(f.blocks for f in self.files if f is not chan.replace)
            if used + entry.blocks > BLOCKS_TOTAL:
                self.set_status(72)
                continue
            if chan.replace in self.files:
                self.files[self.files.index(chan.replace)] = entry
            else:
                self.files.append(entry)

    def write(self, ch, byte):
        """One byte LISTENed to channel `ch`."""
        if ch == 15:
            self._cmd.append(byte)
            return
        chan = self._channels.get(ch)
        if chan is not None and chan.mode == "W":
            chan.data.append(byte)

    def unlisten(self, ch):
        """The end of a LISTEN to `ch`: a command on 15 runs now."""
        if ch == 15 and self._cmd:
            cmd, self._cmd = bytes(self._cmd), bytearray()
            self._command(cmd)

    def read(self, ch):
        """The next byte TALKed from channel `ch` as (byte, eoi), or
        None when the channel has nothing to send."""
        if ch == 15:
            msg = self._status + b"\r"
            byte = msg[self._status_pos]
            self._status_pos += 1
            if self._status_pos < len(msg):
                return byte, False
            self.set_status(0)          # read out: the error clears
            return byte, True
        chan = self._channels.get(ch)
        if chan is None or chan.mode != "R" or chan.pos >= len(chan.data):
            return None
        byte = chan.data[chan.pos]
        chan.pos += 1
        return byte, chan.pos == len(chan.data)

    def _command(self, cmd):
        cmd = cmd.rstrip(b"\r")
        op = cmd[:1]
        arg = cmd.partition(b":")[2]
        if op == b"S":
            if self.write_protect:
                return self.set_status(26)
            pats = [p for p in arg.split(b",") if p]
            if not pats:
                return self.set_status(34)
            gone = [f for f in self.files if not f.locked
                    and any(cbm_match(p, f.name) for p in pats)]
            self.files = [f for f in self.files if f not in gone]
            return self.set_status(1, len(gone))
        if op == b"R":
            new, _, old = arg.partition(b"=")
            old = old.partition(b":")[2] if b":" in old else old
            if not new or not old:
                return self.set_status(34)
            if self.write_protect:
                return self.set_status(26)
            if self.find(new) is not None:
                return self.set_status(63)
            entry = self.find(old)
            if entry is None:
                return self.set_status(62)
            entry.name = bytes(new)
            return self.set_status(0)
        if op == b"N":
            if self.write_protect:
                return self.set_status(26)
            dname, _, did = arg.partition(b",")
            if not dname:
                return self.set_status(34)
            self.disk_name = dname
            if did:
                self.disk_id = did[:2]
            self.files = []
            return self.set_status(0)
        if op in (b"I", b"V"):
            return self.set_status(0)
        if cmd in (b"UJ", b"U:"):
            self._channels.clear()
            return self.set_status(73)
        return self.set_status(31)

    # ── the directory, as the "$" file ──

    def directory(self, spec=b""):
        """The "$" file, as a 1541 sends it: a BASIC program loading at
        $0401 — the header line (drive 0: the disk name in reverse,
        padded with shifted spaces, the ID and "2A"), one line per file
        (blocks; name in quotes; type, `<` if locked),
        and "BLOCKS FREE.".  `spec` (after the "$"): an optional drive
        digit and ":pattern"."""
        pattern = spec.partition(b":")[2] if b":" in spec else b"*"
        out = bytearray(DIR_LOAD_ADDR.to_bytes(2, "little"))

        def line(number, text):
            out.extend(b"\x01\x01" + number.to_bytes(2, "little") + text + b"\x00")

        name16 = self.disk_name[:16].ljust(16, b"\xa0")
        line(0, b"\x12\"" + name16 + b"\" " + self.disk_id[:2].ljust(2, b"\xa0")
             + b"\xa02A")
        for f in self.files:
            if not cbm_match(pattern, f.name):
                continue
            b = f.blocks
            lead = b" " * (3 if b < 10 else 2 if b < 100 else 1 if b < 1000 else 0)
            text = (lead + b"\"" + f.name + b"\"" + b" " * (16 - len(f.name))
                    + b" " + f.type.encode() + (b"<" if f.locked else b" "))
            line(b, text.ljust(27, b" "))
        line(max(self.blocks_free, 0), b"BLOCKS FREE.".ljust(25, b" "))
        out.extend(b"\x00\x00")
        return bytes(out)

    # ── a D64 image ──

    @classmethod
    def from_d64(cls, path):
        """A drive holding the files of a 35-track .d64 image (read
        once; nothing is written back)."""
        img = pathlib.Path(path).read_bytes()

        def sector(t, s):
            spt = [21] * 17 + [19] * 7 + [18] * 6 + [17] * 5
            off = (sum(spt[:t - 1]) + s) * 256
            return img[off:off + 256]

        bam = sector(18, 0)
        drive = cls(bam[0x90:0xA0].rstrip(b"\xa0"), bam[0xA2:0xA4])
        t, s, seen = 18, 1, set()
        while t and (t, s) not in seen:
            seen.add((t, s))
            sec = sector(t, s)
            for i in range(8):
                e = sec[i * 32:i * 32 + 32]
                kind = e[2] & 0x07
                if not e[2] & 0x80 or kind not in _D64_TYPES or kind == 0:
                    continue            # empty, unclosed or deleted
                data, ft, fs, chain = bytearray(), e[3], e[4], set()
                while ft and (ft, fs) not in chain:
                    chain.add((ft, fs))
                    blk = sector(ft, fs)
                    ft, fs = blk[0], blk[1]
                    data += blk[2:fs + 1] if ft == 0 else blk[2:]
                entry = DiskFile(e[5:21].rstrip(b"\xa0"), data, _D64_TYPES[kind],
                                 locked=bool(e[2] & 0x40))
                drive.files.append(entry)
            t, s = sec[0], sec[1]
        return drive


class IECBus:
    """The serial bus with drives on it.  Traps on the KERNAL's own
    serial routines (TALK, LISTEN, SECOND, TKSA, CIOUT, ACPTR, UNTLK,
    UNLSN — where the KERNAL's jump table leads, directly or through a
    vector) carry each byte to and from the addressed drive, so OPEN,
    CLOSE, CHKIN, CHKOUT, CHRIN, CHROUT, CLRCHN, LOAD and SAVE run the
    KERNAL's own code above them.  A device with no drive is not
    served: the KERNAL's routine runs against the empty bus (C64Emu's
    $DD00, M65Emu's), exactly as on a machine without that drive.
    The emulator supplies `_kernal_byte(addr)` (the KERNAL as the jump
    table sees it), `_rts()` (a return through its stack) and
    `_iec_slow_device()` (what its KERNAL's own LISTEN / TALK would
    note of a 1541 on the bus — nothing on the C64)."""

    _JUMP_TABLE = {"talk": 0xFFB4, "listen": 0xFFB1, "second": 0xFF93,
                   "tksa": 0xFF96, "ciout": 0xFFA8, "acptr": 0xFFA5,
                   "untlk": 0xFFAB, "unlsn": 0xFFAE}

    def __init__(self, emu):
        self.emu = emu
        self.drives = {}
        self._listener = self._talker = None
        self._listen_ch = self._talk_ch = None
        self._opening = False
        self._name = bytearray()
        self._addrs = []
        for routine, entry in self._JUMP_TABLE.items():
            addr = self._routine(emu, entry)
            handler = getattr(self, "_" + routine)
            emu.add_trap(addr, lambda e, h=handler: self._serve(h))
            self._addrs.append(addr)

    @staticmethod
    def _routine(emu, entry):
        """Where the jump-table `entry` leads: the C64 KERNAL's `JMP
        addr`, or the MEGA65's `JMP (vector)` through its page-3 RAM
        vector (both ROMs, recorded; the KERNAL's own calls go through
        the entry too, so a trap at the routine catches them)."""
        op, lo, hi = (emu._kernal_byte(entry + k) for k in range(3))
        target = lo | hi << 8
        if op == 0x4C:
            return target
        assert op == 0x6C, f"no JMP at ${entry:04X}"
        return emu.memory[target] | emu.memory[target + 1] << 8

    def remove(self):
        for addr in self._addrs:
            self.emu.remove_trap(addr)

    def _serve(self, handler):
        """Run `handler`; if it served the call (a drive is addressed),
        return from the routine as it would (carry clear, X/Y kept);
        else leave PC, so the KERNAL's own routine runs."""
        if handler(self.emu):
            self.emu.carry = False
            self.emu._rts()

    def _st(self, bits):
        self.emu.memory[ST] = self.emu.memory[ST] | bits

    def _talk(self, emu):
        self._talker = self.drives.get(emu.a & 0x1F)
        self._talk_ch = None
        if self._talker is not None:
            emu._iec_slow_device()
        return self._talker is not None

    def _listen(self, emu):
        self._listener = self.drives.get(emu.a & 0x1F)
        self._listen_ch = None
        self._opening = False
        if self._listener is not None:
            emu._iec_slow_device()
        return self._listener is not None

    def _second(self, emu):
        if self._listener is None:
            return False
        cmd, ch = emu.a & 0xF0, emu.a & 0x0F
        self._listen_ch = ch
        self._opening = cmd == 0xF0
        self._name = bytearray()
        if cmd == 0xE0:
            self._listener.close(ch)
            self._listen_ch = None
        return True

    def _tksa(self, emu):
        if self._talker is None:
            return False
        self._talk_ch = emu.a & 0x0F
        return True

    def _ciout(self, emu):
        if self._listener is None:
            return False
        if self._listen_ch is None:
            pass
        elif self._opening:
            self._name.append(emu.a)
        else:
            self._listener.write(self._listen_ch, emu.a)
        return True

    def _unlsn(self, emu):
        drive, ch = self._listener, self._listen_ch
        if drive is None:
            return False
        if ch is not None:
            if self._opening:
                drive.open(ch, self._name)
            else:
                drive.unlisten(ch)
        self._listener = self._listen_ch = None
        self._opening = False
        return True

    def _acptr(self, emu):
        if self._talker is None:
            return False
        got = None if self._talk_ch is None else self._talker.read(self._talk_ch)
        if got is None:                 # nothing to send: the read times out
            byte = 0x0D
            self._st(ST_EOI | ST_TIMEOUT_READ)
        else:
            byte, eoi = got
            if eoi:
                self._st(ST_EOI)
        emu.a = byte
        p = emu.p & ~(emu.cpu.ZERO | emu.cpu.NEGATIVE)
        emu.p = p | (emu.cpu.ZERO if byte == 0 else 0) | (byte & 0x80)
        return True

    def _untlk(self, emu):
        if self._talker is None:
            return False
        self._talker = self._talk_ch = None
        return True
