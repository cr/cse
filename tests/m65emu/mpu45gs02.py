"""mpu45gs02.py — MPU45GS02, the 45GS02 CPU of M65Emu (layer 1).

Owner: doc/build_system.md

A py65 MPU subclass: py65's register names, `memory`, `step()`,
`reset()`, `irq()`, `nmi()` and `processorCycles`, with the whole
45GS02 behind them.  The instruction table is
tests/fixtures/mega65_instruction_set.csv (see isa.py); each row's
mnemonic and mode select a semantic routine and an addressing routine
here.  Semantics are checked against xmega65 by the golden file
tests/fixtures/golden/m65_cpu.json, not against this reading.

The 45GS02 prefixes are executed as the CPU does: `$42` is a NEG and
`$EA` an EOM, each one step, and they leave a prefix state the next
opcode reads — NEG NEG makes it a Q (32-bit AXYZ) operation, EOM
makes a `(zp),Z` operation flat (`[zp],Z`, a 28-bit pointer), both
make a flat Q operation.  An opcode without a row for the prefix
state runs as the plain opcode.  Interrupts wait while a prefix is
pending and between MAP and EOM.

Cycle counts are not part of the contract: `processorCycles` grows
by a nominal amount per step.

Memory protocol: `memory[addr16]` is the CPU's 16-bit view;
`memory.read_flat(addr28)` / `memory.write_flat(addr28, value)` the
flat 28-bit space.  FlatRAM is the plain implementation (the CPU view
is the first 64 KB of the flat space); M65Memory (layer 2) translates
the CPU view through MAP, $01 and $D030.
"""

from py65.devices import mpu6502

from .isa import RESERVED, decode_table, documented_6502

FLAT = 1 << 28            # tag on an effective address: flat 28-bit space
_M28 = (1 << 28) - 1
_ACC = -1                 # effective address of the accumulator
_QREG = -2                # effective address of the Q pseudo register

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

    def __init__(self, fill=None):
        self.low = bytearray(0x60000)      # chip RAM: 384 KB
        self.high = {}                     # sparse: everything above
        if fill is not None:
            for a in range(len(self.low)):
                self.low[a] = fill(a)
        self.fill = fill

    def read_flat(self, a):
        a &= _M28
        if a < len(self.low):
            return self.low[a]
        if a in self.high:
            return self.high[a]
        return self.fill(a) if self.fill else 0

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

    def __len__(self):
        return 0x10000


_TABLE = decode_table()
_DOCUMENTED = documented_6502()


class MPU45GS02(mpu6502.MPU):
    EXTEND = 0x20         # E: 8-bit stack (the 6502's unused bit)

    def __init__(self, memory=None, pc=0x0000, *, clean=False,
                 allow=frozenset()):
        self.clean = clean
        self.allowed = _DOCUMENTED | frozenset(allow)
        mpu6502.MPU.__init__(self, FlatRAM() if memory is None else memory,
                             pc)
        self.name = "45GS02"

    def reset(self):
        mpu6502.MPU.reset(self)
        self.p = self.EXTEND | self.INTERRUPT
        self.sp = 0x01FF          # SPH:SPL
        self.z = 0
        self.b = 0
        self.mapl = 0             # MAP lower half: X<<8 | A
        self.maph = 0             # MAP upper half: Z<<8 | Y
        self.map_lo_mb = 0        # megabyte selectors (MAP with X/Z = $0F)
        self.map_hi_mb = 0
        self.map_latch = False    # MAP → EOM: interrupts blocked
        self.prefix = P_NONE

    # ── state views ───────────────────────────────────────────────

    @property
    def q(self):
        return self.a | self.x << 8 | self.y << 16 | self.z << 24

    @q.setter
    def q(self, v):
        self.a, self.x = v & 0xFF, v >> 8 & 0xFF
        self.y, self.z = v >> 16 & 0xFF, v >> 24 & 0xFF

    @property
    def map_state(self):
        return dict(mapl=self.mapl, maph=self.maph,
                    lo_mb=self.map_lo_mb, hi_mb=self.map_hi_mb,
                    latch=self.map_latch)

    def reprformat(self):
        return ("%s PC   AC XR YR ZR BR SP   NV-BDIZC\n"
                "%s: %04x %02x %02x %02x %02x %02x %04x %s")

    def __repr__(self):
        flags = format(self.p, "08b")
        return self.reprformat() % (" " * (len(self.name) + 2), self.name,
                                    self.pc, self.a, self.x, self.y, self.z,
                                    self.b, self.sp, flags)

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

    def _rdq(self, ea):
        return sum(self._rd(self._add(ea, k)) << 8 * k for k in range(4))

    def _wrq(self, ea, v):
        for k in range(4):
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
        if self.p & self.EXTEND:
            self.sp = (self.sp & 0xFF00) | ((self.sp + d) & 0xFF)
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
        top = 1 << (bits - 1)
        self._flag(self.NEGATIVE, v & top)
        self._flag(self.ZERO, not v & ((top << 1) - 1))

    def _set_p(self, v):              # PLP / RTI: E and B are not loaded
        keep = self.p & self.EXTEND
        self.p = (v & ~(self.EXTEND | self.BREAK) & 0xFF) | keep

    # ── interrupts ────────────────────────────────────────────────

    def _interruptible(self):
        return not self.map_latch and self.prefix == P_NONE

    def irq(self):
        if self.p & self.INTERRUPT or not self._interruptible():
            return False
        self._interrupt(0xFFFE)
        return True

    def nmi(self):
        if not self._interruptible():
            return False
        self._interrupt(0xFFFA)
        return True

    def _interrupt(self, vector):
        self._push_word(self.pc)
        self._push(self.p & ~self.BREAK)
        self.p = (self.p | self.INTERRUPT) & ~self.DECIMAL & 0xFF
        self.pc = self.memory[vector] | self.memory[(vector + 1) & 0xFFFF] << 8
        self.processorCycles += 7

    # ── decode / step ─────────────────────────────────────────────

    def decode(self, op, prefix=None):
        """The decode key and row `op` runs as in prefix state `prefix`."""
        prefix = self.prefix if prefix is None else prefix
        key = _PREFIX_BYTES[prefix] + (op,)
        row = _TABLE.get(key)
        if row is None:
            if prefix == P_NEGNEG and op == 0x42:
                raise UndefinedPrefix("NEG NEG NEG (NEGQ) has no compendium row")
            key = (op,)
            row = _TABLE[key]
        return key, row

    def step(self):
        start = self.pc
        op = self.memory[start]
        key, row = self.decode(op)
        if row.mnemonic in RESERVED:
            raise ReservedOpcode(f"${start:04X}: {row.mnemonic} "
                                 f"{' '.join('%02X' % b for b in key)}")
        if self.clean and key not in self.allowed:
            raise UncleanOpcode(f"${start:04X}: {row.mnemonic} ({row.mode}) "
                                f"{' '.join('%02X' % b for b in key)}")
        self.pc = (start + 1) & 0xFFFF
        mode_fn, op_fn = _DISPATCH[key]
        prefix = self.prefix
        self.prefix = P_NONE
        op_fn(self, mode_fn, prefix)
        self.processorCycles += 1 + len(key)
        return self

    # ── addressing modes: each returns an effective address ───────

    def m_imp(self):
        return None

    def m_acc(self):
        return _ACC

    def m_q(self):
        return _QREG

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

    def _bp_ptr(self, n):
        return self._rd(self._bp(n)) | self._rd(self._bp(n + 1)) << 8

    def m_izx(self):
        return self._bp_ptr(self._fetch() + self.x)

    def m_izy(self):
        return (self._bp_ptr(self._fetch()) + self.y) & 0xFFFF

    def m_izz(self):
        return (self._bp_ptr(self._fetch()) + self.z) & 0xFFFF

    def m_iz(self):                    # (zp) quad: no index
        return self._bp_ptr(self._fetch())

    def m_isy(self):                   # (d,SP),Y
        d = self._fetch()
        t = (self.sp & 0xFF) + d
        if self.p & self.EXTEND:
            lo = (self.sp & 0xFF00) + (t & 0xFF)
            hi = (self.sp & 0xFF00) + ((t + 1) & 0xFF)
        else:
            lo = (self.sp & 0xFF00) + t
            hi = lo + 1
        ptr = self._rd(lo & 0xFFFF) | self._rd(hi & 0xFFFF) << 8
        return (ptr + self.y) & 0xFFFF

    def m_ind(self):                   # JMP/JSR ($nnnn)
        a = self._fetch16()
        return self._rd(a) | self._rd((a + 1) & 0xFFFF) << 8

    def m_iax(self):                   # JMP/JSR ($nnnn,X)
        a = (self._fetch16() + self.x) & 0xFFFF
        return self._rd(a) | self._rd((a + 1) & 0xFFFF) << 8

    def _flat_ptr(self, index):
        n = self._fetch()
        ptr = sum(self._rd(self._bp(n + k)) << 8 * k for k in range(4))
        return FLAT | ((ptr + index) & _M28)

    def m_flz(self):                   # [zp],Z
        return self._flat_ptr(self.z)

    def m_fl(self):                    # [zp] quad: no index
        return self._flat_ptr(0)

    def m_rel(self):
        off = self._fetch()
        return (self.pc + off - (0x100 if off & 0x80 else 0)) & 0xFFFF

    def m_rel16(self):
        off = self._fetch16()
        # relative to the instruction's last byte (TODO O1)
        return (self.pc - 1 + off - (0x10000 if off & 0x8000 else 0)) & 0xFFFF

    def m_bprel(self):
        ea = self._bp(self._fetch())
        return ea, self.m_rel()


_MODES = {
    "implied": "m_imp", "accumulator": "m_acc", "Q Pseudo Register": "m_q",
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
    if row.mode == "(indirect,X)":
        return MPU45GS02.m_izx if row.length - len(row.key) == 1 \
            else MPU45GS02.m_iax
    return getattr(MPU45GS02, _MODES[row.mode])


# ── semantic routines: op(cpu, mode_fn, prefix_before) ─────────────

def _val(c, ea):
    if ea == _ACC:
        return c.a
    return c._rd(ea)


def _put(c, ea, v):
    if ea == _ACC:
        c.a = v & 0xFF
    else:
        c._wr(ea, v)


def _adc(c, m):
    carry = c.p & c.CARRY
    a = c.a
    if c.p & c.DECIMAL:          # NMOS-style BCD (as xmega65; golden file)
        t = (a & 0x0F) + (m & 0x0F) + carry
        if t > 9:
            t += 6
        if t <= 0x0F:
            t = (t & 0x0F) + (a & 0xF0) + (m & 0xF0)
        else:
            t = (t & 0x0F) + (a & 0xF0) + (m & 0xF0) + 0x10
        c._flag(c.ZERO, not (a + m + carry) & 0xFF)
        c._flag(c.NEGATIVE, t & 0x80)
        c._flag(c.OVERFLOW, (a ^ t) & 0x80 and not (a ^ m) & 0x80)
        if (t & 0x1F0) > 0x90:
            t += 0x60
        c._flag(c.CARRY, (t & 0xFF0) > 0xF0)
        c.a = t & 0xFF
        return
    t = a + m + carry
    c._flag(c.CARRY, t > 0xFF)
    c._flag(c.OVERFLOW, not (a ^ m) & 0x80 and (a ^ t) & 0x80)
    c.a = t & 0xFF
    c._nz(c.a)


def _sbc(c, m):
    borrow = 0 if c.p & c.CARRY else 1
    a = c.a
    t = (a - m - borrow) & 0xFFFF            # flags come from the binary result
    c._flag(c.CARRY, t < 0x100)
    c._flag(c.OVERFLOW, (a ^ t) & 0x80 and (a ^ m) & 0x80)
    c._nz(t & 0xFF)
    if c.p & c.DECIMAL:          # NMOS-style BCD (as xmega65; golden file)
        lo = (a & 0x0F) - (m & 0x0F) - borrow
        if lo & 0x10:
            r = ((lo - 6) & 0x0F) | ((a & 0xF0) - (m & 0xF0) - 0x10)
        else:
            r = (lo & 0x0F) | ((a & 0xF0) - (m & 0xF0))
        if r & 0x100:
            r -= 0x60
        c.a = r & 0xFF
    else:
        c.a = t & 0xFF


def _cmp(c, reg, m):
    t = (reg - m) & 0xFFFF
    c._flag(c.CARRY, t < 0x100)
    c._nz(t & 0xFF)


def _branch(cond):
    def op(c, mode, _):
        target = mode(c)
        if cond(c):
            c.pc = target
    return op


def _flag_op(bit, value):
    def op(c, mode, _):
        c._flag(bit, value)
    return op


def _load(reg):
    def op(c, mode, _):
        v = c._rd(mode(c))
        setattr(c, reg, v)
        c._nz(v)
    return op


def _store(reg):
    def op(c, mode, _):
        c._wr(mode(c), getattr(c, reg))
    return op


def _transfer(src, dst, flags=True):
    def op(c, mode, _):
        v = getattr(c, src)
        setattr(c, dst, v)
        if flags:
            c._nz(v)
    return op


def _incdec(reg, d):
    def op(c, mode, _):
        v = (getattr(c, reg) + d) & 0xFF
        setattr(c, reg, v)
        c._nz(v)
    return op


def _rmw(fn):
    """Read-modify-write on memory or A: fn(c, value) → new value."""
    def op(c, mode, _):
        ea = mode(c)
        _put(c, ea, fn(c, _val(c, ea)))
    return op


def _asl(c, v):
    c._flag(c.CARRY, v & 0x80)
    v = v << 1 & 0xFF
    c._nz(v)
    return v


def _lsr(c, v):
    c._flag(c.CARRY, v & 1)
    v >>= 1
    c._nz(v)
    return v


def _asr(c, v):
    c._flag(c.CARRY, v & 1)
    v = v >> 1 | v & 0x80
    c._nz(v)
    return v


def _rol(c, v):
    v = v << 1 | (c.p & c.CARRY)
    c._flag(c.CARRY, v & 0x100)
    v &= 0xFF
    c._nz(v)
    return v


def _ror(c, v):
    v |= (c.p & c.CARRY) << 8
    c._flag(c.CARRY, v & 1)
    v >>= 1
    c._nz(v)
    return v


def _inc(c, v):
    v = (v + 1) & 0xFF
    c._nz(v)
    return v


def _dec(c, v):
    v = (v - 1) & 0xFF
    c._nz(v)
    return v


def _logic(fn):
    def op(c, mode, _):
        c.a = fn(c.a, c._rd(mode(c))) & 0xFF
        c._nz(c.a)
    return op


def _bit(c, mode, _):
    ea = mode(c)
    m = c._rd(ea)
    c._flag(c.NEGATIVE, m & 0x80)    # BIT # too (xmega65; golden file)
    c._flag(c.OVERFLOW, m & 0x40)
    c._flag(c.ZERO, not c.a & m)


def _tsb(c, mode, _):
    ea = mode(c)
    m = c._rd(ea)
    c._flag(c.ZERO, not m & c.a)
    c._wr(ea, m | c.a)


def _trb(c, mode, _):
    ea = mode(c)
    m = c._rd(ea)
    c._flag(c.ZERO, not m & c.a)
    c._wr(ea, m & ~c.a)


def _bitop(bit, setbit):
    def op(c, mode, _):
        ea = mode(c)
        m = c._rd(ea)
        c._wr(ea, m | 1 << bit if setbit else m & ~(1 << bit))
    return op


def _bbx(bit, setbit):
    def op(c, mode, _):
        ea, target = mode(c)
        if bool(c._rd(ea) >> bit & 1) == setbit:
            c.pc = target
    return op


def _word_bp(d):                       # INW / DEW: base-page word
    def op(c, mode, _):
        lo = mode(c)
        hi = (lo & 0xFF00) | ((lo + 1) & 0xFF)
        v = (c._rd(lo) | c._rd(hi) << 8) + d & 0xFFFF
        c._nz(v, 16)
        c._wr(lo, v)
        c._wr(hi, v >> 8)
    return op


def _asw(c, mode, _):
    a = mode(c)
    v = c._rd(a) | c._rd((a + 1) & 0xFFFF) << 8
    c._flag(c.CARRY, v & 0x8000)
    v = v << 1 & 0xFFFF
    c._nz(v, 16)
    c._wr(a, v)
    c._wr((a + 1) & 0xFFFF, v >> 8)


def _row(c, mode, _):
    a = mode(c)
    v = (c._rd(a) | c._rd((a + 1) & 0xFFFF) << 8) << 1 | (c.p & c.CARRY)
    c._flag(c.CARRY, v & 0x10000)
    v &= 0xFFFF
    c._nz(v, 16)
    c._wr(a, v)
    c._wr((a + 1) & 0xFFFF, v >> 8)


def _neg(c, mode, prefix):
    c.a = -c.a & 0xFF
    c._nz(c.a)
    c.prefix = P_NEGNEG if prefix == P_NEG else P_NEG


def _eom(c, mode, prefix):
    c.map_latch = False
    c.prefix = P_NEGNEGNOP if prefix == P_NEGNEG else P_NOP


def _map(c, mode, _):
    c.map_latch = True
    if c.x == 0x0F:
        c.map_lo_mb = c.a
    else:
        c.mapl = c.x << 8 | c.a
    if c.z == 0x0F:
        c.map_hi_mb = c.y
    else:
        c.maph = c.z << 8 | c.y


def _jmp(c, mode, _):
    c.pc = mode(c)


def _jsr(c, mode, _):
    ret = (c.pc + 1) & 0xFFFF          # the instruction's last byte
    target = mode(c)
    c._push_word(ret)
    c.pc = target


def _bsr(c, mode, _):
    ret = (c.pc + 1) & 0xFFFF
    target = mode(c)
    c._push_word(ret)
    c.pc = target


def _rts(c, mode, _):
    ea = mode(c)
    n = 0 if ea is None else c._rd(ea)
    c.pc = (c._pull_word() + 1) & 0xFFFF
    if n:
        if c.p & c.EXTEND:
            c.sp = (c.sp & 0xFF00) | ((c.sp + n) & 0xFF)
        else:
            c.sp = (c.sp + n) & 0xFFFF


def _rti(c, mode, _):
    c._set_p(c._pull())
    c.pc = c._pull_word()


def _brk(c, mode, _):
    c._push_word((c.pc + 1) & 0xFFFF)
    c._push(c.p | c.BREAK)
    c.p = (c.p | c.INTERRUPT) & ~c.DECIMAL & 0xFF
    c.pc = c._rd(0xFFFE) | c._rd(0xFFFF) << 8


def _push_reg(reg, extra=0):
    def op(c, mode, _):
        c._push(getattr(c, reg) | extra)
    return op


def _pull_reg(reg):
    def op(c, mode, _):
        v = c._pull()
        setattr(c, reg, v)
        c._nz(v)
    return op


def _plp(c, mode, _):
    c._set_p(c._pull())


def _phw(c, mode, _):
    ea = mode(c)                       # PHW #$nnnn: the operand word;
    w = c._rd(ea) | c._rd((ea + 1) & 0xFFFF) << 8   # PHW $nnnn: the word there
    c._push(w)                         # low byte first (unlike JSR)
    c._push(w >> 8)


def _txs(c, mode, _):
    c.sp = (c.sp & 0xFF00) | c.x


def _tsx(c, mode, _):
    c.x = c.sp & 0xFF
    c._nz(c.x)


def _tys(c, mode, _):
    c.sp = c.y << 8 | (c.sp & 0xFF)


def _tsy(c, mode, _):
    c.y = c.sp >> 8
    c._nz(c.y)


def _tab(c, mode, _):
    c.b = c.a


def _tba(c, mode, _):
    c.a = c.b
    c._nz(c.a)


# ── Q (32-bit AXYZ) operations ────────────────────────────────────

def _qval(c, ea):
    return c.q if ea == _QREG else c._rdq(ea)


def _qput(c, ea, v):
    v &= 0xFFFFFFFF
    if ea == _QREG:
        c.q = v
    else:
        c._wrq(ea, v)


def _q_load(c, mode, _):
    c.q = c._rdq(mode(c))
    c._nz(c.q, 32)


def _q_store(c, mode, _):
    c._wrq(mode(c), c.q)


def _q_logic(fn):
    def op(c, mode, _):
        c.q = fn(c.q, c._rdq(mode(c))) & 0xFFFFFFFF
        c._nz(c.q, 32)
    return op


def _q_adc(c, mode, _):
    q, m = c.q, c._rdq(mode(c))
    r = q + m + (c.p & c.CARRY)
    c._flag(c.CARRY, r > 0xFFFFFFFF)
    r &= 0xFFFFFFFF
    c._flag(c.OVERFLOW, (r ^ q) & 0x80000000 and not (q ^ m) & 0x80000000)
    c.q = r
    c._nz(r, 32)


def _q_sbc(c, mode, _):
    q, m = c.q, c._rdq(mode(c))
    r = q - m - 1 + (c.p & c.CARRY)
    c._flag(c.CARRY, r >= 0)
    r &= 0xFFFFFFFF
    c._flag(c.OVERFLOW, (r ^ q) & 0x80000000 and (q ^ m) & 0x80000000)
    c.q = r
    c._nz(r, 32)


def _q_cmp(c, mode, _):
    r = c.q - c._rdq(mode(c))
    c._flag(c.CARRY, r >= 0)
    c._nz(r & 0xFFFFFFFF, 32)


def _q_bit(c, mode, _):
    m = c._rdq(mode(c))
    c._flag(c.NEGATIVE, m & 0x80000000)
    c._flag(c.OVERFLOW, m & 0x40000000)
    c._flag(c.ZERO, not c.q & m)


def _q_rmw(fn):
    def op(c, mode, _):
        ea = mode(c)
        v = fn(c, _qval(c, ea)) & 0xFFFFFFFF
        c._nz(v, 32)
        _qput(c, ea, v)
    return op


def _q_asl(c, v):
    c._flag(c.CARRY, v & 0x80000000)
    return v << 1


def _q_lsr(c, v):
    c._flag(c.CARRY, v & 1)
    return v >> 1


def _q_asr(c, v):
    c._flag(c.CARRY, v & 1)
    return v >> 1 | v & 0x80000000


def _q_rol(c, v):
    r = v << 1 | (c.p & c.CARRY)
    c._flag(c.CARRY, v & 0x80000000)
    return r


def _q_ror(c, v):
    r = v >> 1 | (0x80000000 if c.p & c.CARRY else 0)
    c._flag(c.CARRY, v & 1)
    return r


_OPS = {
    "ADC": lambda c, mode, _: _adc(c, c._rd(mode(c))),
    "SBC": lambda c, mode, _: _sbc(c, c._rd(mode(c))),
    "AND": _logic(lambda a, m: a & m),
    "ORA": _logic(lambda a, m: a | m),
    "EOR": _logic(lambda a, m: a ^ m),
    "CMP": lambda c, mode, _: _cmp(c, c.a, c._rd(mode(c))),
    "CPX": lambda c, mode, _: _cmp(c, c.x, c._rd(mode(c))),
    "CPY": lambda c, mode, _: _cmp(c, c.y, c._rd(mode(c))),
    "CPZ": lambda c, mode, _: _cmp(c, c.z, c._rd(mode(c))),
    "BIT": _bit, "TSB": _tsb, "TRB": _trb,
    "LDA": _load("a"), "LDX": _load("x"), "LDY": _load("y"),
    "LDZ": _load("z"),
    "STA": _store("a"), "STX": _store("x"), "STY": _store("y"),
    "STZ": _store("z"),
    "ASL": _rmw(_asl), "LSR": _rmw(_lsr), "ASR": _rmw(_asr),
    "ROL": _rmw(_rol), "ROR": _rmw(_ror),
    "INC": _rmw(_inc), "DEC": _rmw(_dec),
    "INX": _incdec("x", 1), "INY": _incdec("y", 1), "INZ": _incdec("z", 1),
    "DEX": _incdec("x", -1), "DEY": _incdec("y", -1),
    "DEZ": _incdec("z", -1),
    "INW": _word_bp(1), "DEW": _word_bp(-1), "ASW": _asw, "ROW": _row,
    "NEG": _neg, "EOM": _eom, "MAP": _map,
    "TAX": _transfer("a", "x"), "TAY": _transfer("a", "y"),
    "TAZ": _transfer("a", "z"), "TXA": _transfer("x", "a"),
    "TYA": _transfer("y", "a"), "TZA": _transfer("z", "a"),
    "TAB": _tab, "TBA": _tba, "TXS": _txs, "TSX": _tsx,
    "TYS": _tys, "TSY": _tsy,
    "CLC": _flag_op(0x01, False), "SEC": _flag_op(0x01, True),
    "CLI": _flag_op(0x04, False), "SEI": _flag_op(0x04, True),
    "CLD": _flag_op(0x08, False), "SED": _flag_op(0x08, True),
    "CLV": _flag_op(0x40, False),
    "CLE": _flag_op(0x20, False), "SEE": _flag_op(0x20, True),
    "PHA": _push_reg("a"), "PHX": _push_reg("x"), "PHY": _push_reg("y"),
    "PHZ": _push_reg("z"), "PHP": _push_reg("p", 0x10),
    "PLA": _pull_reg("a"), "PLX": _pull_reg("x"), "PLY": _pull_reg("y"),
    "PLZ": _pull_reg("z"), "PLP": _plp, "PHW": _phw,
    "JMP": _jmp, "JSR": _jsr, "BSR": _bsr, "RTS": _rts, "RTI": _rti,
    "BRK": _brk,
    "BCC": _branch(lambda c: not c.p & c.CARRY),
    "BCS": _branch(lambda c: c.p & c.CARRY),
    "BNE": _branch(lambda c: not c.p & c.ZERO),
    "BEQ": _branch(lambda c: c.p & c.ZERO),
    "BPL": _branch(lambda c: not c.p & c.NEGATIVE),
    "BMI": _branch(lambda c: c.p & c.NEGATIVE),
    "BVC": _branch(lambda c: not c.p & c.OVERFLOW),
    "BVS": _branch(lambda c: c.p & c.OVERFLOW),
    "BRA": _branch(lambda c: True),
    "LDQ": _q_load, "STQ": _q_store,
    "ANDQ": _q_logic(lambda q, m: q & m),
    "ORQ": _q_logic(lambda q, m: q | m),
    "EORQ": _q_logic(lambda q, m: q ^ m),
    "ADCQ": _q_adc, "SBCQ": _q_sbc, "CMPQ": _q_cmp, "BITQ": _q_bit,
    "ASLQ": _q_rmw(_q_asl), "LSRQ": _q_rmw(_q_lsr), "ASRQ": _q_rmw(_q_asr),
    "ROLQ": _q_rmw(_q_rol), "RORQ": _q_rmw(_q_ror),
    "INQ": _q_rmw(lambda c, v: v + 1), "DEQ": _q_rmw(lambda c, v: v - 1),
}
for _n in range(8):
    _OPS[f"RMB{_n}"] = _bitop(_n, False)
    _OPS[f"SMB{_n}"] = _bitop(_n, True)
    _OPS[f"BBR{_n}"] = _bbx(_n, False)
    _OPS[f"BBS{_n}"] = _bbx(_n, True)


def _reserved(c, mode, _):             # never reached: step() raises first
    raise ReservedOpcode


_DISPATCH = {
    key: (_mode_fn(row) if row.mnemonic not in RESERVED else None,
          _OPS[row.mnemonic] if row.mnemonic not in RESERVED else _reserved)
    for key, row in _TABLE.items()
}
