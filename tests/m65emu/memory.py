"""memory.py — M65Memory, the MEGA65 memory layout of M65Emu (layer 2).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

The object MPU45GS02 reads and writes through (layer 1's memory
protocol): `memory[addr16]` is the CPU's view, `read_flat()` /
`write_flat()` the 28-bit space, `map_changed(cpu)` the hook the CPU
calls whenever a MAP register changes.  Checked against the
translations recorded in xmega65 (tests/fixtures/golden/m65_mem.json,
test_m65memory.py).

The flat store: chip RAM $00000-$5FFFF (the ROM image at
$20000-$3FFFF, write-protected while `rom_protect`), colour RAM
$FF80000-$FF87FFF (its first 2 KB is chip RAM $1F800-$1FFFF), and
everything else sparse (attic RAM at $8000000).

The CPU's view, per 4 KB page: MAP (per 8 KB block) first, then the
banking of the CPU port and $D030, else RAM.  A page-table entry is
the flat base the page's reads (`rd`) and writes (`wr`) go to, or _IO
for the I/O page.  The table is rebuilt only when a MAP register
changes or $00, $01, $D02F or (in VIC-III/IV mode) $D030 is written,
or `restore()` sets the banking from a snapshot; `rebuilds` counts the
rebuilds.

I/O registers a device claims (`attach()`) go to the device; every
other register is plain storage, and `io_log` counts the CPU's
accesses to those ("R $Dxxx" / "W $Dxxx").
"""

import collections

_M28 = (1 << 28) - 1
_OWN_REGISTERS = (0x02F, 0x030)   # modelled here, so not in io_log
COLOUR = 0xFF80000         # colour RAM, 32 KB
_SHARED = 0x1F800          # chip RAM $1F800-$1FFFF = colour RAM $000-$7FF
_IO = -1                   # page-table entry of the I/O page

# The I/O modes and the $D02F key (two successive writes) selecting
# each; any other pair selects VIC-II.
VIC2, VIC3, VIC4 = "vic2", "vic3", "vic4"
IO_KEYS = {VIC4: (0x47, 0x53), VIC3: (0xA5, 0x96), VIC2: (0x00, 0x00)}
_MODE_OF_KEY = {a << 8 | b: mode for mode, (a, b) in IO_KEYS.items()}

_D030_ROM = 0x08 | 0x10 | 0x20 | 0x80        # ROM at $8000 $A000 $C000 $E000
_D030_CRAM2K = 0x01                          # colour RAM at $DC00-$DFFF


class _Sparse(dict):
    def __missing__(self, key):
        return 0


class M65Memory:
    def __init__(self, rom=None, rom_protect=True):
        self.chip = bytearray(0x60000)        # incl. the shared colour 2 KB
        self.colour = bytearray(0x8000)       # used from index $800 up
        self.sparse = _Sparse()
        if rom is not None:
            self.chip[0x20000:0x20000 + len(rom)] = rom
        self.rom_protect = rom_protect
        self.io = bytearray(0x1000)           # registers no device claims
        self.io_log = collections.Counter()
        self.devices = []
        self._claims = [None] * 0x1000        # I/O offset → device
        self.io_mode = VIC2
        self.key = 0                          # last byte written to $D02F
        self.d030 = 0                         # latched in VIC-III/IV mode
        self.ddr, self.port = 0xFF, 0x37      # the CPU port, $00 / $01
        self.map = (0, 0, 0, 0)               # MAPL, MAPH, lower/upper MB
        self.rebuilds = 0
        self._rebuild()

    # ── flat space ────────────────────────────────────────────────

    def _cell(self, a):
        """The container and index holding flat address `a`."""
        if a < 0x60000:
            return self.chip, a
        c = a - COLOUR
        if 0 <= c < 0x800:
            return self.chip, _SHARED + c
        if 0x800 <= c < 0x8000:
            return self.colour, c
        return self.sparse, a

    def read_flat(self, a):
        a &= _M28
        if a < 0x60000:
            return self.chip[a]
        store, i = self._cell(a)
        return store[i]

    def write_flat(self, a, v):
        a &= _M28
        if self.rom_protect and 0x20000 <= a < 0x40000:
            return
        store, i = self._cell(a)
        store[i] = v & 0xFF

    def load(self, a, data):
        """Put `data` at flat `a`, ignoring ROM protection (as the
        monitor and a ROM loader do)."""
        if a + len(data) <= 0x60000:                  # chip RAM: one slice
            self.chip[a:a + len(data)] = data
            return
        for k, v in enumerate(data):
            store, i = self._cell((a + k) & _M28)
            store[i] = v

    # ── the CPU's view ────────────────────────────────────────────

    def __getitem__(self, a):
        a &= 0xFFFF
        if a < 2 and self.port_visible:
            return self.port if a else self.ddr
        base = self.rd[a >> 12]
        if base < 0:
            return self.io_read(a & 0xFFF)
        a = base + (a & 0xFFF)
        return self.chip[a] if a < 0x60000 else self.read_flat(a)

    def __setitem__(self, a, v):
        a &= 0xFFFF
        v &= 0xFF
        if a < 2 and self.port_visible:
            if a:
                self.port = v
            else:
                self.ddr = v
            self._rebuild()
            return
        base = self.wr[a >> 12]
        if base < 0:
            self.io_write(a & 0xFFF, v)
            return
        a = base + (a & 0xFFF)
        if a < 0x20000:
            self.chip[a] = v
        else:
            self.write_flat(a, v)

    def attach(self, device, first, last=None):
        """Give I/O registers $D000+`first`..`last` to `device`, which
        has read(off) and write(off, value)."""
        last = first if last is None else last
        taken = [f"$D{o:03X}" for o in range(first, last + 1) if self._claims[o]]
        if taken:
            raise ValueError(f"I/O registers already claimed: {', '.join(taken)}")
        for off in range(first, last + 1):
            self._claims[off] = device
        if device not in self.devices:
            self.devices.append(device)

    def restore_io(self, io):
        """Set the I/O registers from a snapshot: storage, then each
        device's own state (load(io)), without side effects."""
        self.io[:len(io)] = io
        for device in self.devices:
            device.load(self.io)

    def restore(self, *, ddr, port, d030, io_mode):
        """Set the CPU port, `$D030` and the I/O mode directly, as a
        snapshot records them (no `$D02F` key sequence)."""
        self.ddr, self.port, self.d030, self.io_mode = ddr, port, d030, io_mode
        self._rebuild()

    def map_changed(self, cpu):
        self.map = (cpu.mapl, cpu.maph, cpu.map_lo_mb, cpu.map_hi_mb)
        self._rebuild()

    # ── the I/O page ──────────────────────────────────────────────

    def _colour_cell(self, off):
        """The colour RAM cell $D000+`off` shows, or None, and whether
        it is a 4-bit one: the base window ($D800-$DBFF) in VIC-II
        mode keeps and shows only the low nibble."""
        if 0x800 <= off < 0xC00:
            nibble = self.io_mode == VIC2
        elif off >= 0xC00 and self.d030 & _D030_CRAM2K:
            nibble = False
        else:
            return None, False
        return self._cell(COLOUR + off - 0x800), nibble

    def io_read(self, off):
        cell, nibble = self._colour_cell(off)
        if cell is None:
            device = self._claims[off]
            if device is not None:
                return device.read(off)
            if off not in _OWN_REGISTERS:
                self.io_log[f"R $D{off:03X}"] += 1
            return self.io[off]
        store, i = cell
        return store[i] | 0xF0 if nibble else store[i]

    def io_write(self, off, v):
        cell, nibble = self._colour_cell(off)
        if cell is not None:
            store, i = cell
            store[i] = v & 0x0F if nibble else v
            return
        device = self._claims[off]
        if device is not None:
            device.write(off, v)
            return
        self.io[off] = v
        if off not in _OWN_REGISTERS:
            self.io_log[f"W $D{off:03X}"] += 1
        if off == 0x02F:
            self.io_mode = _MODE_OF_KEY.get(self.key << 8 | v, VIC2)
            self.key = v
            self._rebuild()
        elif off == 0x030 and self.io_mode != VIC2:
            self.d030 = v
            self._rebuild()

    # ── the page table ────────────────────────────────────────────

    def _banked(self, page):
        """ram / rom / io for a page MAP leaves alone."""
        cfg = (self.port | ~self.ddr) & 7                 # the C64's table
        rom = self.d030 & _D030_ROM
        if page in (0x8, 0x9):
            return "rom" if rom & 0x08 else "ram"
        if page in (0xA, 0xB):
            return "rom" if rom & 0x10 or cfg & 3 == 3 else "ram"
        if page == 0xC:
            return "rom" if rom & 0x20 else "ram"
        if page == 0xD:
            return "io" if cfg > 4 else "rom" if cfg & 3 else "ram"
        if page in (0xE, 0xF):
            return "rom" if rom & 0x80 or cfg & 2 else "ram"
        return "ram"

    def _rebuild(self):
        self.rebuilds += 1
        mapl, maph, lo_mb, hi_mb = self.map
        self.rd, self.wr = [0] * 16, [0] * 16
        for page in range(16):
            addr = page << 12
            block = page >> 1
            reg, mb = (mapl, lo_mb) if block < 4 else (maph, hi_mb)
            if reg >> 12 >> (block & 3) & 1:              # MAP
                self.rd[page] = self.wr[page] = \
                    (mb << 20) + ((((reg & 0xFFF) << 8) + addr) & 0xFFFFF)
                continue
            kind = self._banked(page)
            if kind == "io":
                self.rd[page] = self.wr[page] = _IO
            else:
                self.rd[page] = addr + (0x20000 if kind == "rom" else 0)
                self.wr[page] = addr                      # the RAM under ROM
        # the CPU port sits in the unmapped zero page only
        self.port_visible = not mapl >> 12 & 1
