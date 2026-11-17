"""mpu45gs02.py — MPU45GS02, the 45GS02 CPU of M65Emu (layer 1).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

A py65 MPU subclass for its interface only — `memory`, `pc`, `a`, `x`,
`y`, `sp`, `p`, `step()`, `reset()`, `irq()`, `nmi()`,
`processorCycles` — with the whole 45GS02 behind it.  py65's own
instruction methods and helpers (`inst_0x..`, `op...`, `stPush`, ...)
are inherited but not used, and are wrong for this CPU (8-bit stack,
no base page): do not call them.

The instruction table is tests/fixtures/mega65_instruction_set.csv
(see isa.py); each row's mnemonic and mode select a semantic routine
`op(cpu, ea)` and an addressing routine returning the effective
address `ea`.  Semantics are checked against xmega65 by the golden
file tests/fixtures/golden/m65_cpu.json, not against this reading.

The 45GS02 prefixes are executed as the CPU does: `$42` is a NEG and
`$EA` an EOM, each one step, and they leave a prefix state the next
opcode reads — NEG NEG makes it a Q (32-bit AXYZ) operation, EOM
makes a `(zp),Z` operation flat (`[zp],Z`, a 28-bit pointer), both
make a flat Q operation.  An opcode without a row for the prefix
state runs as the plain opcode.  Interrupts wait while a prefix is
pending and between MAP and EOM.

Cycle counts are not part of the contract: `processorCycles` counts
steps.

Memory protocol: `memory[addr16]` is the CPU's 16-bit view;
`memory.read_flat(addr28)` / `memory.write_flat(addr28, value)` the
flat 28-bit space; `memory.map_changed(cpu)` is called whenever a MAP
register changes (MAP, reset, or an assignment to `mapl`, `maph`,
`map_lo_mb`, `map_hi_mb`), so the memory's view cannot go stale.  FlatRAM is the plain implementation (the CPU view
is the first 64 KB of the flat space); M65Memory (layer 2) translates
the CPU view through MAP, $01 and $D030.
"""

from typing import NamedTuple

from py65.devices import mpu6502

from .isa import RESERVED, decode_table, documented_6502

# processor flags; bit 5 is E (8-bit stack), the 6502's unused bit
N, V, E, B, D, I, Z, C = 0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01

FLAT = 1 << 28            # tag on an effective address: flat 28-bit space
_M28 = FLAT - 1
_REG = -1                 # effective address of the register operand:
#                           A, or Q for a 32-bit operation

# prefix states
P_NONE, P_NEG, P_NOP, P_NEGNEG, P_NEGNEGNOP = range(5)
_PREFIX_BYTES = {P_NONE: (), P_NEG: (), P_NOP: (0xEA,),
                 P_NEGNEG: (0x42, 0x42), P_NEGNEGNOP: (0x42, 0x42, 0xEA)}


class ReservedOpcode(Exception):
    """A row the compendium reserves (RESQ/RSVQ) was executed."""


class UndefinedPrefix(Exception):
    """A prefix combination the compendium does not define (NEG NEG NEG)."""


class UncleanOpcode(Exception):
    """Clean mode: an opcode outside the 6502's and the allowed set."""


class FlatRAM:
    """A flat 28-bit RAM; the CPU view is its first 64 KB."""

    def __init__(self):
        self.low = bytearray(0x60000)      # chip RAM: 384 KB
        self.high = {}                     # sparse: everything above

    def read_flat(self, a):
        a &= _M28
        return self.low[a] if a < len(self.low) else self.high.get(a, 0)

    def write_flat(self, a, v):
        a &= _M28
        if a < len(self.low):
            self.low[a] = v & 0xFF
        else:
            self.high[a] = v & 0xFF

    def __getitem__(self, a):
        return self.low[a & 0xFFFF]

    def __setitem__(self, a, v):
        self.low[a & 0xFFFF] = v & 0xFF

    def map_changed(self, cpu):       # the CPU view is fixed: no MAP
        pass


def _map_register(name):
    """A MAP register: assigning it tells the memory to remap."""
    def get(self):
        return self._map[name]

    def put(self, value):
        self._map[name] = value
        self.memory.map_changed(self)
    return property(get, put)


class MPU45GS02(mpu6502.MPU):
    mapl = _map_register("mapl")              # MAP lower half: X<<8 | A
    maph = _map_register("maph")              # MAP upper half: Z<<8 | Y
    map_lo_mb = _map_register("map_lo_mb")    # megabyte selectors
    map_hi_mb = _map_register("map_hi_mb")    #   (MAP with X/Z = $0F)

    def __init__(self, memory=None, pc=0x0000, *, clean=False,
                 allow=frozenset()):
        self.clean = clean
        self.allowed = _DOCUMENTED | frozenset(allow)
        mpu6502.MPU.__init__(self, FlatRAM() if memory is None else memory,
                             pc)
        self.name = "45GS02"

    def reset(self):
        mpu6502.MPU.reset(self)
        self.p = E | I
        self.sp = 0x01FF          # SPH:SPL
        self.z = 0
        self.b = 0
        self._map = dict(mapl=0, maph=0, map_lo_mb=0, map_hi_mb=0)
        self.memory.map_changed(self)
        self.map_latch = False    # MAP → EOM: interrupts blocked
        self.prefix = P_NONE

    # ── register views ────────────────────────────────────────────

    @property
    def q(self):
        return self.a | self.x << 8 | self.y << 16 | self.z << 24

    @q.setter
    def q(self, v):
        self.a, self.x = v & 0xFF, v >> 8 & 0xFF
        self.y, self.z = v >> 16 & 0xFF, v >> 24 & 0xFF

    @property
    def spl(self):
        return self.sp & 0xFF

    @spl.setter
    def spl(self, v):
        self.sp = (self.sp & 0xFF00) | v

    @property
    def sph(self):
        return self.sp >> 8

    @sph.setter
    def sph(self, v):
        self.sp = v << 8 | (self.sp & 0xFF)

    def __repr__(self):
        return ("%s: PC=%04x A=%02x X=%02x Y=%02x Z=%02x B=%02x SP=%04x "
                "NVEBDIZC=%s" % (self.name, self.pc, self.a, self.x, self.y,
                                 self.z, self.b, self.sp,
                                 format(self.p, "08b")))

    # ── memory ────────────────────────────────────────────────────

    def _rd(self, ea):
        if ea & FLAT:
            return self.memory.read_flat(ea & _M28)
        return self.memory[ea & 0xFFFF]

    def _wr(self, ea, v):
        if ea & FLAT:
            self.memory.write_flat(ea & _M28, v & 0xFF)
        else:
            self.memory[ea & 0xFFFF] = v & 0xFF

    @staticmethod
    def _add(ea, k):
        if ea & FLAT:
            return FLAT | ((ea + k) & _M28)
        return (ea + k) & 0xFFFF

    def _get(self, ea, bits=8):
        """The `bits`-wide little-endian operand at `ea` (or A / Q)."""
        if ea == _REG:
            return self.q if bits == 32 else self.a
        if bits == 8:
            return self._rd(ea)
        return sum(self._rd(self._add(ea, k)) << 8 * k
                   for k in range(bits // 8))

    def _put(self, ea, v, bits=8):
        if ea == _REG:
            if bits == 32:
                self.q = v
            else:
                self.a = v & 0xFF
        else:
            for k in range(bits // 8):
                self._wr(self._add(ea, k), v >> 8 * k)

    def _fetch(self):
        v = self.memory[self.pc]
        self.pc = (self.pc + 1) & 0xFFFF
        return v

    def _fetch16(self):
        lo = self._fetch()
        return lo | self._fetch() << 8

    def _bp(self, n):
        return self.b << 8 | n & 0xFF

    # ── stack ─────────────────────────────────────────────────────

    def _sp_step(self, d):
        if self.p & E:
            self.spl = (self.sp + d) & 0xFF
        else:
            self.sp = (self.sp + d) & 0xFFFF

    def _push(self, v):
        self._wr(self.sp, v)
        self._sp_step(-1)

    def _pull(self):
        self._sp_step(1)
        return self._rd(self.sp)

    def _push_word(self, w):          # high byte first (JSR order)
        self._push(w >> 8)
        self._push(w)

    def _pull_word(self):
        lo = self._pull()
        return lo | self._pull() << 8

    # ── flags ─────────────────────────────────────────────────────

    def _flag(self, bit, cond):
        self.p = (self.p | bit) if cond else (self.p & ~bit & 0xFF)

    def _nz(self, v, bits=8):
        self._flag(N, v >> (bits - 1) & 1)
        self._flag(Z, not v & ((1 << bits) - 1))

    def _set_p(self, v):              # PLP / RTI: E and B are not loaded
        self.p = (v & ~(E | B) & 0xFF) | (self.p & E)

    # ── interrupts ────────────────────────────────────────────────

    def _interruptible(self):
        return not self.map_latch and self.prefix == P_NONE

    def irq(self):
        if self.p & I or not self._interruptible():
            return False
        self._interrupt(0xFFFE)
        return True

    def nmi(self):
        if not self._interruptible():
            return False
        self._interrupt(0xFFFA)
        return True

    def _interrupt(self, vector, brk=0):
        self._push_word(self.pc)
        self._push((self.p & ~B) | brk)
        self.p = (self.p | I) & ~D & 0xFF
        self.pc = self._get(vector, 16)

    # ── decode / step ─────────────────────────────────────────────

    def decode(self, op, prefix=None):
        """The decode key and table entry `op` runs as in a prefix state."""
        prefix = self.prefix if prefix is None else prefix
        key = _PREFIX_BYTES[prefix] + (op,)
        if key not in _TABLE:
            if prefix == P_NEGNEG and op == 0x42:
                raise UndefinedPrefix("NEG NEG NEG (NEGQ) has no compendium row")
            key = (op,)
        return key, _TABLE[key]

    def step(self):
        start = self.pc
        key, entry = self.decode(self.memory[start])
        if entry.op is None or (self.clean and key not in self.allowed):
            row = entry.row
            kind = ReservedOpcode if entry.op is None else UncleanOpcode
            raise kind(f"${start:04X}: {row.mnemonic} ({row.mode}) "
                       f"{' '.join('%02X' % b for b in key)}")
        self.pc = (start + 1) & 0xFFFF
        entry.op(self, entry.mode(self))
        if not entry.sets_prefix:
            self.prefix = P_NONE
        self.processorCycles += 1
        return self

    # ── addressing modes: each returns an effective address ───────

    def m_imp(self):
        return None

    def m_reg(self):
        return _REG

    def m_imm(self):
        ea = self.pc
        self.pc = (self.pc + 1) & 0xFFFF
        return ea

    def m_imm16(self):
        ea = self.pc
        self.pc = (self.pc + 2) & 0xFFFF
        return ea

    def m_bp(self):
        return self._bp(self._fetch())

    def m_bpx(self):
        return self._bp(self._fetch() + self.x)

    def m_bpy(self):
        return self._bp(self._fetch() + self.y)

    def m_abs(self):
        return self._fetch16()

    def m_absx(self):
        return (self._fetch16() + self.x) & 0xFFFF

    def m_absy(self):
        return (self._fetch16() + self.y) & 0xFFFF

    def _bp_ptr(self, n):             # the pointer wraps in the base page
        return self._rd(self._bp(n)) | self._rd(self._bp(n + 1)) << 8

    def m_izx(self):
        return self._bp_ptr(self._fetch() + self.x)

    def m_izy(self):
        return (self._bp_ptr(self._fetch()) + self.y) & 0xFFFF

    def m_izz(self):
        return (self._bp_ptr(self._fetch()) + self.z) & 0xFFFF

    def m_iz(self):                   # (zp) quad: no index
        return self._bp_ptr(self._fetch())

    def m_isy(self):                  # (d,SP),Y
        t = self.spl + self._fetch()
        wrap = 0xFF if self.p & E else 0xFFFF
        page = self.sp & 0xFF00
        ptr = (self._rd(page + (t & wrap))
               | self._rd(page + ((t + 1) & wrap)) << 8)
        return (ptr + self.y) & 0xFFFF

    def m_ind(self):                  # JMP/JSR ($nnnn)
        return self._get(self._fetch16(), 16)

    def m_iax(self):                  # JMP/JSR ($nnnn,X)
        return self._get((self._fetch16() + self.x) & 0xFFFF, 16)

    def _flat_ptr(self, index):       # the pointer wraps in the base page
        n = self._fetch()
        ptr = sum(self._rd(self._bp(n + k)) << 8 * k for k in range(4))
        return FLAT | ((ptr + index) & _M28)

    def m_flz(self):                  # [zp],Z
        return self._flat_ptr(self.z)

    def m_fl(self):                   # [zp] quad: no index
        return self._flat_ptr(0)

    def m_rel(self):
        off = self._fetch()
        return (self.pc + off - (0x100 if off & 0x80 else 0)) & 0xFFFF

    def m_rel16(self):                # from the instruction's last byte
        off = self._fetch16()         # (xmega65; the hardware: TODO O1)
        return (self.pc - 1 + off - (0x10000 if off & 0x8000 else 0)) & 0xFFFF

    def m_bprel(self):                # BBRn/BBSn: (tested byte, target)
        ea = self._bp(self._fetch())
        return ea, self.m_rel()


_MODES = {
    "implied": "m_imp", "accumulator": "m_reg", "Q Pseudo Register": "m_reg",
    "immediate 8bit": "m_imm", "immediate 16bit": "m_imm16",
    "base-page": "m_bp", "base-page,X": "m_bpx", "base-page,Y": "m_bpy",
    "absolute": "m_abs", "absolute,X": "m_absx", "absolute,Y": "m_absy",
    "(indirect),Y": "m_izy", "(indirect),Z": "m_izz",
    "(immediate,SP),Y": "m_isy", "(indirect)": "m_ind",
    "relative": "m_rel", "16-bit relative": "m_rel16",
    "base-page+rel": "m_bprel", "[indirect],Z": "m_flz",
    "base-page quad": "m_bp", "absolute quad": "m_abs",
    "base-page quad,X": "m_bpx", "absolute quad,X": "m_absx",
    "(indirect quad)": "m_iz", "(indirect quad),Z": "m_izz",
    "[indirect quad]": "m_fl", "[indirect quad],Z": "m_flz",
}


def _mode_fn(row):
    if row.mode == "(indirect,X)":    # one name for ($nn,X) and ($nnnn,X)
        return MPU45GS02.m_izx if row.length - len(row.key) == 1 \
            else MPU45GS02.m_iax
    return getattr(MPU45GS02, _MODES[row.mode])


# ── semantic routines: op(cpu, ea) ────────────────────────────────
#
# `reg` names the register (a property for Q, SPL, SPH), `bits` the
# operand width: 8, 16 (ASW, ROW) or 32 (the Q operations).

def _load(reg, bits=8):
    def op(c, ea):
        v = c._get(ea, bits)
        setattr(c, reg, v)
        c._nz(v, bits)
    return op


def _store(reg, bits=8):
    def op(c, ea):
        c._put(ea, getattr(c, reg), bits)
    return op


def _transfer(src, dst, flags=True):
    def op(c, ea):
        v = getattr(c, src)
        setattr(c, dst, v)
        if flags:
            c._nz(v)
    return op


def _logic(fn, reg="a", bits=8):
    def op(c, ea):
        v = fn(getattr(c, reg), c._get(ea, bits))
        setattr(c, reg, v)
        c._nz(v, bits)
    return op


def _compare(reg, bits=8):
    def op(c, ea):
        r, m = getattr(c, reg), c._get(ea, bits)
        c._flag(C, r >= m)
        c._nz(r - m, bits)
    return op


def _bit(reg="a", bits=8):
    def op(c, ea):
        m = c._get(ea, bits)
        c._flag(N, m >> (bits - 1) & 1)   # BIT # too (xmega65; golden file)
        c._flag(V, m >> (bits - 2) & 1)
        c._flag(Z, not getattr(c, reg) & m)
    return op


def _adc(reg="a", bits=8):
    top = 1 << (bits - 1)

    def op(c, ea):
        r, m, carry = getattr(c, reg), c._get(ea, bits), c.p & C
        if bits == 8 and c.p & D:
            return _adc_bcd(c, r, m, carry)
        t = r + m + carry
        c._flag(C, t >> bits)
        c._flag(V, ~(r ^ m) & (r ^ t) & top)
        setattr(c, reg, t & (2 * top - 1))
        c._nz(t, bits)
    return op


def _adc_bcd(c, a, m, carry):
    """8-bit decimal ADC, NMOS-style: as xmega65 does it (golden file)."""
    t = (a & 0x0F) + (m & 0x0F) + carry
    if t > 9:
        t += 6
    t = (t & 0x0F) + (a & 0xF0) + (m & 0xF0) + (0x10 if t > 0x0F else 0)
    c._flag(Z, not (a + m + carry) & 0xFF)
    c._flag(N, t & 0x80)
    c._flag(V, ~(a ^ m) & (a ^ t) & 0x80)
    if (t & 0x1F0) > 0x90:
        t += 0x60
    c._flag(C, (t & 0xFF0) > 0xF0)
    c.a = t & 0xFF


def _sbc(reg="a", bits=8):
    top = 1 << (bits - 1)

    def op(c, ea):
        r, m, borrow = getattr(c, reg), c._get(ea, bits), ~c.p & C
        t = r - m - borrow              # the flags are the binary result's,
        c._flag(C, t >= 0)              # in decimal mode too (NMOS-style)
        c._flag(V, (r ^ t) & (r ^ m) & top)
        c._nz(t, bits)
        if bits == 8 and c.p & D:
            t = _sbc_bcd(r, m, borrow)
        setattr(c, reg, t & (2 * top - 1))
    return op


def _sbc_bcd(a, m, borrow):
    """The 8-bit decimal SBC result, NMOS-style (golden file)."""
    lo = (a & 0x0F) - (m & 0x0F) - borrow
    hi = (a & 0xF0) - (m & 0xF0)
    if lo < 0:
        lo, hi = lo - 6, hi - 0x10
    if hi < 0:
        hi -= 0x60
    return (lo & 0x0F) | (hi & 0xF0)


# shift kind → (carry out, result) from the value, carry in, top bit
_SHIFTS = {
    "asl": lambda v, cin, top: (v & top, v << 1),
    "rol": lambda v, cin, top: (v & top, v << 1 | cin),
    "lsr": lambda v, cin, top: (v & 1, v >> 1),
    "asr": lambda v, cin, top: (v & 1, v >> 1 | v & top),
    "ror": lambda v, cin, top: (v & 1, v >> 1 | (top if cin else 0)),
}


def _shift(kind, bits=8):
    fn, top = _SHIFTS[kind], 1 << (bits - 1)

    def op(c, ea):
        cout, v = fn(c._get(ea, bits), c.p & C, top)
        v &= 2 * top - 1
        c._flag(C, cout)
        c._nz(v, bits)
        c._put(ea, v, bits)
    return op


def _step(d, bits=8):                  # INC / DEC of memory, A or Q
    def op(c, ea):
        v = (c._get(ea, bits) + d) & ((1 << bits) - 1)
        c._nz(v, bits)
        c._put(ea, v, bits)
    return op


def _incdec(reg, d):                   # INX, DEY, ...
    def op(c, ea):
        v = (getattr(c, reg) + d) & 0xFF
        setattr(c, reg, v)
        c._nz(v)
    return op


def _word_bp(d):                       # INW / DEW: the word wraps in the
    def op(c, lo):                     # base page, unlike the Q operands
        hi = (lo & 0xFF00) | ((lo + 1) & 0xFF)
        v = (c._rd(lo) | c._rd(hi) << 8) + d & 0xFFFF
        c._nz(v, 16)
        c._wr(lo, v)
        c._wr(hi, v >> 8)
    return op


def _test_bits(keep):                  # TSB / TRB
    def op(c, ea):
        m = c._rd(ea)
        c._flag(Z, not m & c.a)
        c._wr(ea, m | c.a if keep else m & ~c.a)
    return op


def _bitop(bit, setbit):               # SMBn / RMBn
    def op(c, ea):
        m = c._rd(ea)
        c._wr(ea, m | 1 << bit if setbit else m & ~(1 << bit))
    return op


def _bbx(bit, setbit):                 # BBSn / BBRn
    def op(c, ea_target):
        ea, target = ea_target
        if c._rd(ea) >> bit & 1 == setbit:
            c.pc = target
    return op


def _branch(cond):
    def op(c, target):
        if cond(c):
            c.pc = target
    return op


def _flag_op(bit, value):
    def op(c, ea):
        c._flag(bit, value)
    return op


def _neg(c, ea):
    c.a = -c.a & 0xFF
    c._nz(c.a)
    c.prefix = P_NEGNEG if c.prefix == P_NEG else P_NEG


def _eom(c, ea):
    c.map_latch = False
    c.prefix = P_NEGNEGNOP if c.prefix == P_NEGNEG else P_NOP


def _map(c, ea):
    c.map_latch = True
    if c.x == 0x0F:
        c.map_lo_mb = c.a
    else:
        c.mapl = c.x << 8 | c.a
    if c.z == 0x0F:
        c.map_hi_mb = c.y
    else:
        c.maph = c.z << 8 | c.y


def _jmp(c, target):
    c.pc = target


def _call(c, target):                  # JSR / BSR: push the last byte's
    c._push_word((c.pc - 1) & 0xFFFF)  # address, as the 6502's JSR does
    c.pc = target


def _rts(c, ea):                       # RTS / RTS #n
    n = 0 if ea is None else c._rd(ea)
    c.pc = (c._pull_word() + 1) & 0xFFFF
    c._sp_step(n)


def _rti(c, ea):
    c._set_p(c._pull())
    c.pc = c._pull_word()


def _brk(c, ea):
    c.pc = (c.pc + 1) & 0xFFFF         # the byte after BRK is skipped
    c._interrupt(0xFFFE, brk=B)


def _push_reg(reg, extra=0):
    def op(c, ea):
        c._push(getattr(c, reg) | extra)
    return op


def _pull_reg(reg):
    def op(c, ea):
        v = c._pull()
        setattr(c, reg, v)
        c._nz(v)
    return op


def _plp(c, ea):
    c._set_p(c._pull())


def _phw(c, ea):                       # the operand word (#) or the word
    w = c._get(ea, 16)                 # at $nnnn; low byte first, unlike JSR
    c._push(w)
    c._push(w >> 8)


_OPS = {
    "LDA": _load("a"), "LDX": _load("x"), "LDY": _load("y"),
    "LDZ": _load("z"), "LDQ": _load("q", 32),
    "STA": _store("a"), "STX": _store("x"), "STY": _store("y"),
    "STZ": _store("z"), "STQ": _store("q", 32),
    "TAX": _transfer("a", "x"), "TAY": _transfer("a", "y"),
    "TAZ": _transfer("a", "z"), "TXA": _transfer("x", "a"),
    "TYA": _transfer("y", "a"), "TZA": _transfer("z", "a"),
    "TBA": _transfer("b", "a"), "TAB": _transfer("a", "b", flags=False),
    "TSX": _transfer("spl", "x"), "TXS": _transfer("x", "spl", flags=False),
    "TSY": _transfer("sph", "y"), "TYS": _transfer("y", "sph", flags=False),
    "AND": _logic(int.__and__), "ANDQ": _logic(int.__and__, "q", 32),
    "ORA": _logic(int.__or__), "ORQ": _logic(int.__or__, "q", 32),
    "EOR": _logic(int.__xor__), "EORQ": _logic(int.__xor__, "q", 32),
    "CMP": _compare("a"), "CPX": _compare("x"), "CPY": _compare("y"),
    "CPZ": _compare("z"), "CMPQ": _compare("q", 32),
    "BIT": _bit(), "BITQ": _bit("q", 32),
    "ADC": _adc(), "ADCQ": _adc("q", 32),
    "SBC": _sbc(), "SBCQ": _sbc("q", 32),
    "ASL": _shift("asl"), "ASLQ": _shift("asl", 32), "ASW": _shift("asl", 16),
    "ROL": _shift("rol"), "ROLQ": _shift("rol", 32), "ROW": _shift("rol", 16),
    "LSR": _shift("lsr"), "LSRQ": _shift("lsr", 32),
    "ASR": _shift("asr"), "ASRQ": _shift("asr", 32),
    "ROR": _shift("ror"), "RORQ": _shift("ror", 32),
    "INC": _step(1), "INQ": _step(1, 32),
    "DEC": _step(-1), "DEQ": _step(-1, 32),
    "INX": _incdec("x", 1), "INY": _incdec("y", 1), "INZ": _incdec("z", 1),
    "DEX": _incdec("x", -1), "DEY": _incdec("y", -1),
    "DEZ": _incdec("z", -1),
    "INW": _word_bp(1), "DEW": _word_bp(-1),
    "TSB": _test_bits(True), "TRB": _test_bits(False),
    "NEG": _neg, "EOM": _eom, "MAP": _map,
    "CLC": _flag_op(C, False), "SEC": _flag_op(C, True),
    "CLI": _flag_op(I, False), "SEI": _flag_op(I, True),
    "CLD": _flag_op(D, False), "SED": _flag_op(D, True),
    "CLE": _flag_op(E, False), "SEE": _flag_op(E, True),
    "CLV": _flag_op(V, False),
    "PHA": _push_reg("a"), "PHX": _push_reg("x"), "PHY": _push_reg("y"),
    "PHZ": _push_reg("z"), "PHP": _push_reg("p", B), "PHW": _phw,
    "PLA": _pull_reg("a"), "PLX": _pull_reg("x"), "PLY": _pull_reg("y"),
    "PLZ": _pull_reg("z"), "PLP": _plp,
    "JMP": _jmp, "JSR": _call, "BSR": _call, "RTS": _rts, "RTI": _rti,
    "BRK": _brk,
    "BCC": _branch(lambda c: not c.p & C), "BCS": _branch(lambda c: c.p & C),
    "BNE": _branch(lambda c: not c.p & Z), "BEQ": _branch(lambda c: c.p & Z),
    "BPL": _branch(lambda c: not c.p & N), "BMI": _branch(lambda c: c.p & N),
    "BVC": _branch(lambda c: not c.p & V), "BVS": _branch(lambda c: c.p & V),
    "BRA": _branch(lambda c: True),
}
for _n in range(8):
    _OPS[f"RMB{_n}"] = _bitop(_n, False)
    _OPS[f"SMB{_n}"] = _bitop(_n, True)
    _OPS[f"BBR{_n}"] = _bbx(_n, False)
    _OPS[f"BBS{_n}"] = _bbx(_n, True)


class Entry(NamedTuple):
    row: tuple            # the fixture row (isa.Row)
    mode: object          # addressing routine; None for a reserved row
    op: object            # semantic routine; None for a reserved row
    sets_prefix: bool     # NEG, EOM: the op leaves the next prefix state


def _entry(row):
    if row.mnemonic in RESERVED:
        return Entry(row, None, None, False)
    op = _OPS[row.mnemonic]
    return Entry(row, _mode_fn(row), op, op in (_neg, _eom))


_TABLE = {key: _entry(row) for key, row in decode_table().items()}
_DOCUMENTED = documented_6502()
