"""memory.py — M65Memory, the MEGA65 memory layout of M65Emu (layer 2).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

The object MPU45GS02 reads and writes through (layer 1's memory
protocol): `memory[addr16]` is the CPU's view, `read_flat()` /
`write_flat()` the 28-bit space, `map_changed(cpu)` the MAP hook.
Checked against the translations recorded in xmega65
(tests/fixtures/golden/m65_mem.json, test_m65memory.py).

The flat store: chip RAM $00000-$5FFFF (the ROM image at
$20000-$3FFFF, write-protected while `rom_protect`), colour RAM
$FF80000-$FF87FFF (its first 2 KB is chip RAM $1F800-$1FFFF), and
everything else sparse (attic RAM at $8000000).

The CPU's view, per 4 KB page: MAP (per 8 KB block) first, then the
banking of the CPU port and $D030, else RAM.  A page-table entry is
the flat base its reads and its writes go to, or IO for the I/O page.
The table is rebuilt only by MAP and by writes to $00, $01, $D02F and
$D030; `rebuilds` counts the rebuilds.
"""

_M28 = (1 << 28) - 1
COLOUR = 0xFF80000
_SHARED = 0x1F800          # chip RAM $1F800-$1FFFF = colour RAM $000-$7FF
IO = None                  # page-table entry of the I/O page

VIC2, VIC3, VIC4 = "vic2", "vic3", "vic4"
_KEYS = {0xA596: VIC3, 0x4753: VIC4}         # every other key: VIC-II
_D030_ROM = 0x08 | 0x10 | 0x20 | 0x80        # ROM8, ROMA, ROMC, ROME


class M65Memory:
    def __init__(self, rom=None, rom_protect=True):
        self.chip = bytearray(0x60000)
        self.colour = bytearray(0x8000)
        self.sparse = {}
        if rom is not None:
            self.chip[0x20000:0x20000 + len(rom)] = rom
        self.rom_protect = rom_protect
        self.io = {VIC2: bytearray(0x1000), VIC3: bytearray(0x1000),
                   VIC4: bytearray(0x1000)}  # registers no device claims
        self.io_mode = VIC2
        self.key = 0                          # last byte written to $D02F
        self.d030 = 0                         # latched in VIC-III/IV mode
        self.ddr, self.port = 0xFF, 0x37      # the CPU port, $00 / $01
        self.map = (0, 0, 0, 0)               # MAPL, MAPH, lower/upper MB
        self.rebuilds = 0
        self._rebuild()

    # ── flat space ────────────────────────────────────────────────

    def read_flat(self, a):
        a &= _M28
        if _SHARED <= a < 0x20000:
            return self.colour[a - _SHARED]
        if a < 0x60000:
            return self.chip[a]
        if COLOUR <= a < COLOUR + 0x8000:
            return self.colour[a - COLOUR]
        return self.sparse.get(a, 0)

    def write_flat(self, a, v):
        a &= _M28
        if self.rom_protect and 0x20000 <= a < 0x40000:
            return
        self.load(a, bytes([v & 0xFF]))

    def load(self, a, data):
        """Put `data` at flat `a`, ignoring ROM protection (as the
        monitor and a ROM loader do)."""
        for k, v in enumerate(data):
            b = (a + k) & _M28
            if _SHARED <= b < 0x20000:
                self.colour[b - _SHARED] = v
            elif b < 0x60000:
                self.chip[b] = v
            elif COLOUR <= b < COLOUR + 0x8000:
                self.colour[b - COLOUR] = v
            else:
                self.sparse[b] = v

    def dump(self):
        """Everything the store holds, for before/after comparisons."""
        return (bytes(self.chip), bytes(self.colour), dict(self.sparse),
                {m: bytes(r) for m, r in self.io.items()})

    # ── the CPU's view ────────────────────────────────────────────

    def __getitem__(self, a):
        a &= 0xFFFF
        if a < 2 and self.port_visible:
            return self.port if a else self.ddr
        base = self.rd[a >> 12]
        if base is IO:
            return self._io_read(a & 0xFFF)
        return self.read_flat(base + (a & 0xFFF))

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
        if base is IO:
            self._io_write(a & 0xFFF, v)
        else:
            self.write_flat(base + (a & 0xFFF), v)

    def map_changed(self, cpu):
        self.map = (cpu.mapl, cpu.maph, cpu.map_lo_mb, cpu.map_hi_mb)
        self._rebuild()

    # ── the I/O page ──────────────────────────────────────────────

    def _colour_index(self, off):
        """The colour RAM index $Dxxx shows, or None."""
        if 0x800 <= off < 0xC00 or (off >= 0xC00 and self.d030 & 1):
            return off - 0x800
        return None

    def _io_read(self, off):
        c = self._colour_index(off)
        if c is not None:
            v = self.colour[c]
            return v | 0xF0 if self.io_mode == VIC2 else v
        return self.io[self.io_mode][off]

    def _io_write(self, off, v):
        c = self._colour_index(off)
        if c is not None:
            self.colour[c] = v & 0x0F if self.io_mode == VIC2 else v
            return
        self.io[self.io_mode][off] = v
        if off == 0x02F:
            self.io_mode = _KEYS.get(self.key << 8 | v, VIC2)
            self.key = v
            self._rebuild()
        elif off == 0x030 and self.io_mode != VIC2:
            self.d030 = v
            self._rebuild()

    # ── the page table ────────────────────────────────────────────

    def _rebuild(self):
        self.rebuilds += 1
        mapl, maph, lo_mb, hi_mb = self.map
        cfg = (self.port | ~self.ddr) & 7
        rom = self.d030 & _D030_ROM
        self.rd, self.wr = [0] * 16, [0] * 16
        for page in range(16):
            addr = page << 12
            block = page >> 1
            reg, mb = (mapl, lo_mb) if block < 4 else (maph, hi_mb)
            if reg >> 12 >> (block & 3) & 1:                       # MAP
                t = (mb << 20) + ((((reg & 0xFFF) << 8) + addr) & 0xFFFFF)
                self.rd[page] = self.wr[page] = t
                continue
            if page in (0x8, 0x9):
                kind = "rom" if rom & 0x08 else "ram"
            elif page in (0xA, 0xB):
                kind = "rom" if rom & 0x10 or cfg & 3 == 3 else "ram"
            elif page == 0xC:
                kind = "rom" if rom & 0x20 else "ram"
            elif page == 0xD:
                kind = "io" if cfg > 4 else ("ram" if cfg & 3 == 0 else "rom")
            elif page in (0xE, 0xF):
                kind = "rom" if rom & 0x80 or cfg & 2 else "ram"
            else:
                kind = "ram"
            if kind == "io":
                self.rd[page] = self.wr[page] = IO
            else:
                self.rd[page] = addr + (0x20000 if kind == "rom" else 0)
                self.wr[page] = addr
        mapped0 = mapl >> 12 & 1
        self.port_visible = not mapped0
