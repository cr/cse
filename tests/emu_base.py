"""emu_base.py — what the C64 and MEGA65 test harnesses share.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../doc/testing.md#m65emu--the-m65-integration-harness).

`EmuBase` holds a CPU (`_cpu`) and its memory (`_mem`) and gives both
harnesses the same surface: the registers and flags, the run loops
(`jsr`, `run_until`, `run_until_with_watch`), word access, symbols
from the `.lbl` file beside a PRG, and the screen-code decoding behind
`screen_text()`.  A subclass supplies `SENTINEL`, `_push_return()`
(how `jsr` makes the routine's RTS land on the sentinel) and,
optionally, `_after_step()` (C64Emu's interrupt scheduling).
"""

import pathlib


def decode_screen_codes(codes):
    """Screen codes as text, in the lowercase/uppercase charset (CSE's
    runtime mode): $00 '@', $01-$1A 'a'-'z', $20-$3F as is, $41-$5A
    'A'-'Z', anything else '?'.  Bit 7 (reverse) is ignored; trailing
    blanks are stripped."""
    chars = []
    for sc in codes:
        sc &= 0x7F
        if sc == 0x00:
            chars.append("@")
        elif 0x01 <= sc <= 0x1A:
            chars.append(chr(sc + 0x60))
        elif 0x20 <= sc <= 0x3F:
            chars.append(chr(sc))
        elif 0x41 <= sc <= 0x5A:
            chars.append(chr(sc))
        else:
            chars.append("?")
    return "".join(chars).rstrip()


class EmuBase:
    NAME = "Emu"
    SENTINEL = None             # where jsr()'s RTS lands; the run stops there
    JSR_REGS = ("a", "x", "y")  # registers jsr() may set

    def __init__(self, cpu, mem):
        self._cpu = cpu
        self._mem = mem
        self._syms = {}

    # ── registers ─────────────────────────────────────────────────

    def _reg(name, mask):
        def get(self):
            return getattr(self._cpu, name)

        def put(self, val):
            setattr(self._cpu, name, val & mask)
        return property(get, put)

    a = _reg("a", 0xFF)
    x = _reg("x", 0xFF)
    y = _reg("y", 0xFF)
    pc = _reg("pc", 0xFFFF)
    p = _reg("p", 0xFF)
    del _reg

    @property
    def carry(self):
        return bool(self._cpu.p & self._cpu.CARRY)

    @carry.setter
    def carry(self, val):
        if val:
            self._cpu.p |= self._cpu.CARRY
        else:
            self._cpu.p &= ~self._cpu.CARRY

    @property
    def zero(self):
        return bool(self._cpu.p & self._cpu.ZERO)

    @property
    def negative(self):
        return bool(self._cpu.p & self._cpu.NEGATIVE)

    @property
    def overflow(self):
        return bool(self._cpu.p & self._cpu.OVERFLOW)

    @property
    def cpu(self):
        return self._cpu

    @property
    def memory(self):
        return self._mem

    # ── running ───────────────────────────────────────────────────

    def _push_return(self, ret):
        """Arrange the stack so the routine's RTS goes to `ret` + 1."""
        raise NotImplementedError

    def _after_step(self):
        """Called after every CPU step (interrupt scheduling)."""

    def _run(self, stop, max_cycles, watch=None, what="run"):
        """Step until PC == `stop`; return the step count — or, given
        `watch` addresses, the (pc, step) visits to them in order."""
        watched = set(watch or ())
        hits = []
        cpu = self._cpu
        for n in range(max_cycles):
            pc = cpu.pc
            if pc == stop:
                return n if watch is None else hits
            if pc in watched:
                hits.append((pc, n))
            cpu.step()
            self._after_step()
        raise TimeoutError(f"{self.NAME}: {what} timeout after {max_cycles} "
                           f"cycles at ${self._cpu.pc:04X}")

    def jsr(self, addr, *, carry=None, max_cycles=500_000, **regs):
        """Call the routine at `addr` as JSR would and run it until its
        RTS; return the step count.  Keyword registers (`JSR_REGS`)
        and `carry` are set first.  TimeoutError after `max_cycles`."""
        unknown = set(regs) - set(self.JSR_REGS)
        if unknown:
            raise TypeError(f"jsr() sets {self.JSR_REGS}, not {sorted(unknown)}")
        self._push_return((self.SENTINEL - 1) & 0xFFFF)
        for name, val in regs.items():
            if val is not None:
                setattr(self, name, val)
        if carry is not None:
            self.carry = carry
        self._cpu.pc = addr
        return self._run(self.SENTINEL, max_cycles, what=f"jsr(${addr:04X})")

    def run_until(self, stop_addr, *, start_at=None, max_cycles=500_000):
        """Step until PC == `stop_addr`; return the step count.  The
        caller arranges how control gets there (no sentinel)."""
        if start_at is not None:
            self._cpu.pc = start_at
        return self._run(stop_addr, max_cycles,
                         what=f"run_until(${stop_addr:04X})")

    def run_until_with_watch(self, stop_addr, watch_addrs, *,
                             start_at=None, max_cycles=500_000):
        """Like run_until, but return the (pc, step) visits to
        `watch_addrs` in order — to assert a path is (not) entered."""
        if start_at is not None:
            self._cpu.pc = start_at
        return self._run(stop_addr, max_cycles, watch=list(watch_addrs),
                         what=f"run_until_with_watch(${stop_addr:04X})")

    # ── memory and symbols ────────────────────────────────────────

    def read_word(self, addr):
        return self._mem[addr] | (self._mem[addr + 1] << 8)

    def write_word(self, addr, val):
        self._mem[addr] = val & 0xFF
        self._mem[addr + 1] = (val >> 8) & 0xFF

    @staticmethod
    def _read_prg(prg_path):
        """(load address, payload) of a .prg file."""
        data = pathlib.Path(prg_path).read_bytes()
        return data[0] | data[1] << 8, data[2:]

    def _load_symbols(self, map_path):
        """Symbols from the .lbl file (VICE label format) beside the
        ld65 map, through conftest.SymbolTable."""
        from conftest import SymbolTable
        lbl_path = pathlib.Path(map_path).with_suffix(".lbl")
        if lbl_path.exists():
            st = SymbolTable(lbl_path)
            for name in st.keys():
                self._syms[name] = st[name]

    def sym(self, name):
        try:
            return self._syms[name]
        except KeyError:
            raise KeyError(f"Symbol {name!r} not found. Available: "
                           f"{', '.join(sorted(self._syms)[:20])}...") from None

    def sym_opt(self, name):
        """A symbol's address, or None (for feature-gated tests)."""
        return self._syms.get(name)
