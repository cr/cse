"""devices.py — M65Emu's devices (layer 3): DMA, keyboard queue, CIA ports,
the VIC interrupt latch.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Each device claims I/O registers in M65Memory (`attach()`), answers
read(off) / write(off, value) for them, and load(io) restores its
state from a snapshot's I/O page without side effects.  The DMA
controller is checked against jobs recorded in xmega65
(tests/fixtures/golden/m65_dma.json); the keyboard queue follows
xemu's source (the monitor cannot type a key).  The CIA1 port reads
the key matrix C64Emu reads (emu_base.KeyMatrix); the VIC latch and
the CIA2 interrupt register hold what the jiffy tick and RESTORE raise
— no raster timing, no CIA timers, as in C64Emu.
"""

import collections

_M28 = (1 << 28) - 1
COPY, MIX, SWAP, FILL = range(4)


class DMANotModelled(Exception):
    """A DMA mode M65Emu does not model: line drawing, modulo, lists
    read through the CPU's view ($D706, $D707)."""


class _Channel:
    """One side of a DMA job: a fixed-point address (8 fraction bits)
    within a megabyte `base`, stepping by `step`."""

    def __init__(self, field, mb, revision, step, frac):
        self.base = ((mb << 20) + (field & 0x700000 if revision else 0)) & 0xFF00000
        self.addr = ((field & 0xFFFFF) << 8) + frac
        self.step = step
        self.io = bool(field & 0x800000)

    def at(self):
        return ((self.addr >> 8) & 0xFFFFF) + self.base

    def advance(self, mb_cross):
        self.addr += self.step
        if mb_cross and not 0 <= self.addr <= 0xFFFFFFF:
            self.addr &= 0xFFFFFFF
            self.base = (self.base + (0x100000 if self.step >= 0 else -0x100000)) & _M28


class DMAController:
    """The F018A/B DMA controller at $D700-$D70F (claimed by M65Emu).
    A job list runs to its end when it is started."""

    def __init__(self, mem):
        self.mem = mem
        self.regs = bytearray(16)
        self.list_addr = 0
        self.revision = 0             # default list format: 0 F018A, 1 F018B
        self.mb_cross = False

    def load(self, io):
        r = self.regs
        r[:] = io[0x700:0x710]
        self.list_addr = r[0] | r[1] << 8 | (r[2] & 0x7F) << 16 | r[4] << 20
        self.revision, self.mb_cross = r[3] & 1, bool(r[3] & 2)

    def read(self, off):
        return self.regs[off & 0xF]

    def write(self, off, v):
        reg = off & 0xF
        self.regs[reg] = v
        a = self.list_addr
        if reg == 0x1:
            self.list_addr = (a & 0xFFF00FF) | v << 8
        elif reg == 0x2:              # bits 16-22; clears the megabyte
            self.list_addr = (a & 0xFFFF) | (v & 0x7F) << 16
        elif reg == 0x3:
            self.revision, self.mb_cross = v & 1, bool(v & 2)
        elif reg == 0x4:
            self.list_addr = (a & 0xFFFFF) | v << 20
        elif reg == 0xE:              # bits 0-7 without starting
            self.list_addr = (a & 0xFFFFF00) | v
        elif reg == 0x0:              # start, in the default format
            self.list_addr = (a & 0xFFFF00) | v
            self._run(enhanced=False)
        elif reg == 0x5:              # start an enhanced list
            self.list_addr = (a & 0xFFFFF00) | v
            self._run(enhanced=True)
        elif reg in (0x6, 0x7):
            raise DMANotModelled(f"DMA list read through the CPU's view (${0xD700 + reg:04X})")

    # ── a session: one started list, its chained jobs ─────────────

    def _next(self):
        v = self.mem.read_flat(self.list_addr)
        self.list_addr = (self.list_addr + 1) & _M28
        return v

    def _run(self, enhanced):
        s = dict(revision=self.revision, mb_cross=self.mb_cross,
                 transparency=0x100,      # bit 8 set: off; else the byte skipped
                 src_mb=0, dst_mb=0, src_int=1, src_frac=0, dst_int=1,
                 dst_frac=0, src_init=0, dst_init=0, len3=0)
        while True:
            if enhanced:
                self._options(s)
            if not self._job(s):
                return

    def _options(self, s):
        """An enhanced option list; its settings stay for the rest of
        the session, chained jobs included (as recorded)."""
        while True:
            opt = self._next()
            if opt == 0x00:
                return
            val = self._next() if opt & 0x80 else None
            if opt == 0x01:
                s["mb_cross"] = True
            elif opt == 0x06:
                s["transparency"] |= 0x100
            elif opt == 0x07:
                s["transparency"] &= 0xFF
            elif opt in (0x0A, 0x0B):
                s["revision"] = opt & 1
            elif opt == 0x86:
                s["transparency"] = (s["transparency"] & 0x100) | val
            elif opt in _OPTION_FIELDS:
                s[_OPTION_FIELDS[opt]] = val
            elif 0x87 <= opt <= 0x8F or 0x97 <= opt <= 0x9F:
                raise DMANotModelled(f"DMA line drawing (option ${opt:02X})")
            # any other option is ignored, as xemu ignores it

    def _job(self, s):
        """Fetch and run one job; return whether one is chained."""
        n = self._next
        cmd, length = n(), n() | n() << 8 | s["len3"] << 16
        src = n() | n() << 8 | n() << 16
        dst = n() | n() << 8 | n() << 16
        sub = n() if s["revision"] else 0
        n(), n()                                          # modulo
        op = cmd & 3
        if s["revision"]:                                 # F018B
            hold_s, dec_s, mod_s = sub & 2, cmd & 16, sub & 1
            hold_d, dec_d, mod_d = sub & 8, cmd & 32, sub & 4
            minterms = sub >> 4
        else:                                             # F018A
            hold_s, dec_s, mod_s = src & 0x100000, src & 0x400000, src & 0x200000
            hold_d, dec_d, mod_d = dst & 0x100000, dst & 0x400000, dst & 0x200000
            minterms = cmd >> 4
        if mod_s or mod_d:
            raise DMANotModelled("DMA modulo mode")

        def step(hold, dec, integer, frac):
            if hold:
                return 0
            v = integer << 8 | frac
            return -v if dec else v
        source = _Channel(src, s["src_mb"], s["revision"],
                          step(hold_s, dec_s, s["src_int"], s["src_frac"]), s["src_init"])
        target = _Channel(dst, s["dst_mb"], s["revision"],
                          step(hold_d, dec_d, s["dst_int"], s["dst_frac"]), s["dst_init"])
        fill = src & 0xFF
        for _ in range(length or 0x10000):
            if op == FILL:
                self._put(target, fill, s)
            elif op == COPY:
                self._put(target, self._get(source), s)
            elif op == SWAP:
                a, b = self._get(source), self._get(target)
                self._put(source, b, s)
                self._put(target, a, s)
            else:                                         # MIX
                a, b = self._get(source), self._get(target)
                v = 0
                for k, mask in enumerate((~a & ~b, ~a & b, a & ~b, a & b)):
                    if minterms >> k & 1:
                        v |= mask
                self._put(target, v & 0xFF, s)
            if op != FILL:
                source.advance(s["mb_cross"])
            target.advance(s["mb_cross"])
        return bool(cmd & 4)

    def _get(self, ch):
        a = ch.at()
        if ch.io and a & 0xF000 == 0xD000:
            return self.mem._io_read(a & 0xFFF)
        return self.mem.read_flat(a)

    def _put(self, ch, v, s):
        if v == s["transparency"]:
            return
        a = ch.at()
        if ch.io and a & 0xF000 == 0xD000:
            self.mem._io_write(a & 0xFFF, v)
        else:
            self.mem.write_flat(a, v)


_OPTION_FIELDS = {0x80: "src_mb", 0x81: "dst_mb", 0x82: "src_frac",
                  0x83: "src_int", 0x84: "dst_frac", 0x85: "dst_int",
                  0x90: "len3", 0x91: "src_init", 0x92: "dst_init"}


def _petscii_to_ascii(p):
    """What the MEGA65 keyboard scanner reports for a key typed as the
    PETSCII byte `p`: unshifted letters lower case, shifted upper."""
    if 0x41 <= p <= 0x5A:
        return p + 0x20
    if 0xC1 <= p <= 0xDA:
        return p - 0x80
    return p


class KeyboardQueue:
    """The hardware keyboard scanner's queue: $D610 (ASCII), $D619
    (PETSCII), $D60A (modifiers), $D611 (keys held now)."""

    REGISTERS = (0x60A, 0x610, 0x611, 0x619)

    def __init__(self):
        self.queue = collections.deque()      # (ascii, petscii, modifiers)

    def load(self, io):
        self.queue.clear()                    # a snapshot's queue is empty

    def push(self, petscii, modifiers=0):
        self.queue.append((_petscii_to_ascii(petscii), petscii, modifiers))

    def read(self, off):
        head = self.queue[0] if self.queue else None
        if off == 0x610:
            return head[0] if head else 0x00
        if off == 0x619:
            return head[1] if head else 0xFF
        if off == 0x60A:
            return (head[2] & 0x7F) | 0x80 if head else 0x00
        return 0x00                           # $D611: no key held

    def write(self, off, v):
        if off in (0x610, 0x619):
            if self.queue:
                self.queue.popleft()
        elif off == 0x60A and not v & 0x80:
            self.queue.clear()


class CIA1Ports:
    """CIA1's keyboard matrix ports: port A ($DC00) selects columns and
    reads back; port B ($DC01) reads the held keys of `keys` (a
    KeyMatrix) in the selected columns."""

    def __init__(self, keys):
        self.keys = keys
        self.port_a = 0xFF

    def load(self, io):
        pass                                  # the CIAs are not captured

    def read(self, off):
        return self.port_a if off == 0xC00 else self.keys.rows(self.port_a)

    def write(self, off, v):
        if off == 0xC00:
            self.port_a = v


class CIA2InterruptControl:
    """CIA2's interrupt control register ($DD0D), as far as RESTORE
    goes: bit 4 latched by `latch()`, returned and cleared by a read."""

    def __init__(self):
        self.latched = 0

    def load(self, io):
        self.latched = 0                      # the CIAs are not captured

    def latch(self, bits):
        self.latched |= bits

    def read(self, off):
        v, self.latched = self.latched, 0
        return v

    def write(self, off, v):
        pass                                  # the mask: no timers to mask


class VICInterruptLatch:
    """The VIC's interrupt latch ($D019): bits 0-3 raised by `raise_()`
    (the jiffy tick raises bit 0, the raster interrupt), bit 7 set
    while any is; writing 1s clears those bits.  Bits 4-6 read as the
    snapshot left them."""

    def __init__(self):
        self.latched = 0
        self.rest = 0

    def load(self, io):
        self.latched, self.rest = io[0x019] & 0x0F, io[0x019] & 0x70

    def raise_(self, bits):
        self.latched |= bits & 0x0F

    def read(self, off):
        return self.rest | self.latched | (0x80 if self.latched else 0)

    def write(self, off, v):
        self.latched &= ~v & 0x0F
