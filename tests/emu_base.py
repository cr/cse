"""emu_base.py — what the C64 and MEGA65 test harnesses share.

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../doc/testing.md#m65emu--the-m65-integration-harness).

`EmuBase` holds a CPU (`_cpu`) and its memory (`_mem`) and gives both
harnesses the same surface: the registers and flags, the run loops
(`jsr`, `run_until`, `run_until_with_watch`), word access, symbols
from the `.lbl` file beside a PRG, the screen-code decoding behind
`screen_text()`, the interrupt scheduler and the jiffy tick, the
keyboard matrix (`KeyMatrix`) with STOP and RESTORE, key injection,
`load_prg()` with segment relocation, `set_cursor()` and `init_cse()`.

A subclass supplies `SENTINEL`, `screen_row()`, the attributes `_keys`
(its `KeyMatrix`) and `_ram` (the 64 KB load_prg() writes), and:

    _push_return(ret)             make the routine's RTS land on `ret` + 1
    _enter_irq() / _enter_nmi()   take the interrupt now, or False
    _jiffy_tick()                 what a tick does before its IRQ
    _latch_restore()              what RESTORE latches before its NMI
    _queue_key(petscii)           where one injected key goes
"""

import pathlib
import re


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


# ── the keyboard matrix (PETSCII → (row, col)) ─────────────────
#
# The C64's 8×8 matrix, scanned through CIA1: a 0 bit in $DC00 selects
# a column, $DC01 reads a 0 in the row of each held key there.  The
# MEGA65 keeps the same matrix for the C64's keys.  The table covers
# the keys tests use: letters, digits, common punctuation, RETURN,
# SPACE, STOP; lowercase and shifted letters map to the plain cell.
_KEY_MATRIX = {
    # Control keys
    0x0D: (0, 1),    # RETURN
    0x20: (7, 4),    # SPACE
    0x03: (7, 7),    # STOP
    # Digits (row 7 alternates 1/2, then row 1 for 3/4 etc.)
    0x31: (7, 0), 0x32: (7, 3), 0x33: (1, 0), 0x34: (1, 3),
    0x35: (2, 0), 0x36: (2, 3), 0x37: (3, 0), 0x38: (3, 3),
    0x39: (4, 0), 0x30: (4, 3),
    # Letters
    0x41: (1, 2), 0x42: (3, 4), 0x43: (2, 4), 0x44: (2, 2),
    0x45: (1, 6), 0x46: (2, 5), 0x47: (3, 2), 0x48: (3, 5),
    0x49: (4, 1), 0x4A: (4, 2), 0x4B: (4, 5), 0x4C: (5, 2),
    0x4D: (4, 4), 0x4E: (4, 7), 0x4F: (4, 6), 0x50: (5, 1),
    0x51: (7, 6), 0x52: (2, 1), 0x53: (1, 5), 0x54: (2, 6),
    0x55: (3, 6), 0x56: (3, 7), 0x57: (1, 1), 0x58: (2, 7),
    0x59: (3, 1), 0x5A: (1, 4),
    # Common punctuation
    0x2C: (5, 7), 0x2E: (5, 4), 0x2F: (6, 7), 0x3A: (5, 5),
    0x3B: (6, 2), 0x3D: (6, 5), 0x2B: (5, 0), 0x2D: (5, 3),
    0x2A: (6, 1), 0x40: (5, 6),
}
STOP = 0x03                     # the PETSCII of the STOP key


def petscii_to_matrix(ch):
    """Resolve a PETSCII char (int or 1-char str) to (row, col)."""
    if isinstance(ch, str):
        if len(ch) != 1:
            raise ValueError(f"press/release_key expects single char, got {ch!r}")
        ch = ord(ch)
    if 0x61 <= ch <= 0x7A:            # lowercase → uppercase
        ch -= 0x20
    if 0xC1 <= ch <= 0xDA:            # shifted uppercase → plain
        ch -= 0x80
    if ch not in _KEY_MATRIX:
        raise KeyError(f"no matrix mapping for PETSCII ${ch:02X}")
    return _KEY_MATRIX[ch]


def register(name, mask):
    """A harness property for the CPU register `name`, `mask` wide."""
    def get(self):
        return getattr(self._cpu, name)

    def put(self, val):
        setattr(self._cpu, name, val & mask)
    return property(get, put)


class KeyMatrix:
    """The held keys of the keyboard matrix, as (row, col) cells."""

    def __init__(self):
        self.pressed = set()

    def rows(self, col_mask):
        """$DC01 for the columns `col_mask` ($DC00) selects: a held
        key's row bit 0 when its column is selected (0)."""
        rows = 0xFF
        for r, c in self.pressed:
            if not (col_mask >> c) & 1:
                rows &= ~(1 << r) & 0xFF
        return rows


class EmuBase:
    NAME = "Emu"
    SENTINEL = None             # where jsr()'s RTS lands; the run stops there
    JSR_REGS = ("a", "x", "y")  # registers jsr() may set
    JIFFY_INTERVAL = 16421      # the C64 KERNAL's CIA1 timer A value, in steps
    PLOT = 0xFFF0               # the KERNAL's PLOT
    INIT_ROUTINES = ("theme_init", "restore_colors", "setup_interrupts",
                     "dbg_init", "sym_clear")

    def __init__(self, cpu, mem):
        self._cpu = cpu
        self._mem = mem
        self._syms = {}
        # The interrupt scheduler: a step counter, pending (step, kind)
        # entries — kind 'irq', 'nmi', 'jiffy' (a tick not yet raised)
        # or 'held' (a raised tick waiting for its IRQ) — and the tick
        # interval (0: off).
        self._steps = 0
        self._pending = []
        self._jiffy_interval = 0

    # ── registers ─────────────────────────────────────────────────

    a = register("a", 0xFF)
    x = register("x", 0xFF)
    y = register("y", 0xFF)
    pc = register("pc", 0xFFFF)
    p = register("p", 0xFF)

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

    def _run(self, stop, max_cycles, watch=(), what="run"):
        """Step until PC == `stop`; return the step count and the
        (pc, step) visits to `watch`.  With `stop` None, run exactly
        `max_cycles` steps; else TimeoutError after them."""
        watched = set(watch)
        hits = []
        cpu = self._cpu
        for n in range(max_cycles):
            pc = cpu.pc
            if pc == stop:
                return n, hits
            if pc in watched:
                hits.append((pc, n))
            cpu.step()
            self._steps += 1
            if self._pending:
                self._dispatch_pending()
        if stop is None:
            return max_cycles, hits
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
        return self._run(self.SENTINEL, max_cycles, what=f"jsr(${addr:04X})")[0]

    def run_until(self, stop_addr, *, start_at=None, max_cycles=500_000):
        """Step until PC == `stop_addr`; return the step count.  The
        caller arranges how control gets there (no sentinel)."""
        if start_at is not None:
            self._cpu.pc = start_at
        return self._run(stop_addr, max_cycles,
                         what=f"run_until(${stop_addr:04X})")[0]

    def run_until_with_watch(self, stop_addr, watch_addrs, *,
                             start_at=None, max_cycles=500_000):
        """Like run_until, but return the (pc, step) visits to
        `watch_addrs` in order — to assert a path is (not) entered."""
        if start_at is not None:
            self._cpu.pc = start_at
        return self._run(stop_addr, max_cycles, watch=watch_addrs,
                         what=f"run_until_with_watch(${stop_addr:04X})")[1]

    def run_steps(self, steps, watch=()):
        """Run exactly `steps` steps — for code that never ends, such
        as a loop waiting for interrupts; return the (pc, step) visits
        to `watch`."""
        return self._run(None, steps, watch=watch)[1]

    # ── scheduled interrupts ──────────────────────────────────────
    #
    # The run loop consults the pending queue after every step; an
    # entry fires once the step counter reaches it.  An IRQ waits while
    # the CPU refuses it (I set, or a 45GS02 prefix pending); an NMI is
    # edge-triggered and fires once per schedule.  The vector is
    # fetched through the memory's banking.

    def schedule_irq(self, steps_from_now):
        """An IRQ `steps_from_now` steps from now.  IRQs due together
        fire one after another, one per step the CPU takes them."""
        self._schedule(steps_from_now, "irq")

    def schedule_nmi(self, steps_from_now):
        """An NMI `steps_from_now` steps from now (fires once)."""
        self._schedule(steps_from_now, "nmi")

    def cancel_pending_interrupts(self):
        """Drop every scheduled IRQ/NMI (the jiffy clock stays on)."""
        self._pending.clear()

    def enable_jiffy_clock(self, interval=None):
        """A repeating IRQ every `interval` steps (JIFFY_INTERVAL by
        default), each scheduled from the step the last one fired."""
        self._jiffy_interval = self.JIFFY_INTERVAL if interval is None else interval
        self._schedule(self._jiffy_interval, "jiffy")

    def disable_jiffy_clock(self):
        """Stop the ticks; other scheduled interrupts stay."""
        self._jiffy_interval = 0
        self._pending = [(w, k) for w, k in self._pending
                         if k not in ("jiffy", "held")]

    def _schedule(self, steps, kind):
        self._pending.append((self._steps + max(steps, 0), kind))
        self._pending.sort()

    def _dispatch_pending(self):
        """Fire what is due: an NMI first (due NMIs fire once); else
        one IRQ, if the CPU takes it, which also serves a due tick.
        Whatever stays due is polled again next step."""
        now = self._steps
        if self._pending[0][0] > now:             # sorted: nothing due
            return
        due = [k for w, k in self._pending if w <= now]
        later = [(w, k) for w, k in self._pending if w > now]
        if "jiffy" in due:                        # the tick happens now
            self._jiffy_tick()
        nmi = "nmi" in due
        irqs = due.count("irq")
        tick = "jiffy" in due or "held" in due    # a raised tick waiting
        if nmi and self._enter_nmi():
            nmi = False                           # taken; the IRQs wait
        elif not nmi and (irqs or tick) and self._enter_irq():
            irqs = max(irqs - 1, 0)
            if tick:
                tick = False
                if self._jiffy_interval:          # the next from now
                    later.append((now + self._jiffy_interval, "jiffy"))
        waiting = ["irq"] * irqs
        if tick:
            waiting.append("held")
        if nmi:
            waiting.append("nmi")
        self._pending = sorted(later + [(now + 1, k) for k in waiting])

    def _enter_irq(self):
        raise NotImplementedError

    def _enter_nmi(self):
        raise NotImplementedError

    def _jiffy_tick(self):
        """What a tick does before its IRQ (nothing on the C64)."""

    # ── the keyboard ──────────────────────────────────────────────

    def press_key(self, ch):
        """Hold a key in the matrix (PETSCII int or 1-char str)."""
        self._keys.pressed.add(petscii_to_matrix(ch))

    def release_key(self, ch):
        self._keys.pressed.discard(petscii_to_matrix(ch))

    def release_all_keys(self):
        self._keys.pressed.clear()

    def press_stop(self):
        self.press_key(STOP)

    def release_stop(self):
        self.release_key(STOP)

    def press_restore(self):
        """RESTORE: latch CIA2 $DD0D bit 4 and raise an NMI (the key
        is wired to the NMI line, not to the matrix)."""
        self._latch_restore()
        self.schedule_nmi(0)

    def inject_key(self, petscii):
        """Queue one PETSCII byte as typed."""
        self._queue_key(petscii & 0xFF)

    def inject_keys(self, data):
        for b in data:
            self.inject_key(b)

    # ── memory, PRG loading and symbols ───────────────────────────

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

    def load_prg(self, prg_path, map_path=None):
        """Put the payload at its load address, load the symbols of
        the .lbl beside the map (default: the PRG's .map), and copy
        each segment whose load and run addresses differ to its run
        address, as the loader does; return the load address."""
        prg_path = pathlib.Path(prg_path)
        load_addr, payload = self._read_prg(prg_path)
        self._ram[load_addr:load_addr + len(payload)] = payload
        self._load_symbols(map_path or prg_path.with_suffix(".map"))
        self._relocate_segments()
        return load_addr

    def _relocate_segments(self):
        """Segments with __<SEG>_LOAD__/_RUN__/_SIZE__ symbols (ld65's
        define=yes): copied from load to run (the same place for a
        segment that is not relocated)."""
        syms, ram = self._syms, self._ram
        for sym, load in list(syms.items()):
            m = re.fullmatch(r"__(\w+)_LOAD__", sym)
            if not m:
                continue
            run = syms.get(f"__{m.group(1)}_RUN__")
            size = syms.get(f"__{m.group(1)}_SIZE__")
            if run is not None and size:
                ram[run:run + size] = ram[load:load + size]

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

    # ── the screen and the KERNAL ─────────────────────────────────

    def screen_row(self, row):
        """One row's screen codes."""
        raise NotImplementedError

    def screen_text(self, row):
        """One screen row as text (decode_screen_codes)."""
        return decode_screen_codes(self.screen_row(row))

    def set_cursor(self, row, col):
        """Move the cursor through the KERNAL's PLOT (carry clear)."""
        self.jsr(self.PLOT, carry=False, x=row, y=col)

    def init_cse(self, *, editor=False):
        """Run CSE's cold-init routines by symbol; call after
        load_prg().  `sym_clear` is mandatory: update_workend (editor
        init, asm_assemble) writes the symbol heap through sym_define,
        whose pointer is $0000 (BSS) until sym_clear sets it.  With
        `editor`, ed_ensure_init too."""
        for name in self.INIT_ROUTINES + (("ed_ensure_init",) if editor else ()):
            self.jsr(self.sym(name))
