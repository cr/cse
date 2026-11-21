"""
editor_cap.py — the line cap's contract matrix, shared by the c64 and m65 tests.

Owner: doc/modules/editor.md

Contract source: editor.md § Long lines and the overflow indicator —
the invariant (no key makes a line wider than the cap, no key puts the
cursor past it) and its table of entry points, each with the rule that
keeps it.  testing.md Principle 11 (invariants over state): every
mutator of a line's width or the cursor's column, a case that fits and
a case that would pass the cap, from states where one key changes the
width by more than one column (a tab stop).

Every case starts from a load (the text in the buffer, the cursor at
line 0 col 0, `ed_dirty` = 0), moves the cursor with `nav`, types
`keys`, and is checked whole by `check`: the buffer's bytes, the
cursor's line and column, the KERNAL cursor on the screen, `>` in the
last column of exactly the rows whose line is wider than the cap, and
a refusal's blip with the buffer and `ed_dirty` as before.  The runner
(`Ed`) is the platform's: C64Emu through `ed_handle_key`, M65Emu
through main_loop.
"""

from dataclasses import dataclass

TAB, HOME, INS, DEL, RETURN = 0xA0, 0x13, 0x94, 0x14, 0x0D
UP, DOWN, RIGHT = 0x91, 0x11, 0x1D
GT = 0x3E                                    # the overflow indicator '>'
TAB_WIDTH = 8


def width(line):
    """Visual width of a line's bytes (a tab ends at the next stop)."""
    col = 0
    for b in line:
        col = (col // TAB_WIDTH + 1) * TAB_WIDTH if b == TAB else col + 1
    return col


@dataclass
class Case:
    name: str
    text: bytes                 # the loaded buffer
    nav: bytes                  # keys that place the cursor (not under test)
    keys: bytes                 # the keys under test
    want: bytes                 # the buffer after
    line: int                   # ed_cur_line after
    col: int                    # ed_cur_col after
    blip: bool                  # a key refused (io_blip ran)
    dirty: int                  # ed_dirty after


def cases(cap):
    """The matrix for a cap (39, or 79 on m65 in 80 columns)."""
    S = cap // TAB_WIDTH * TAB_WIDTH         # a tab starting below S ends at S at most
    t, sp = bytes([TAB]), b" "
    X = lambda n: b"X" * n                   # noqa: E731
    long = b"Y" * (cap + 6)
    to_end = bytes([RIGHT]) * (cap + 10)     # RIGHT until refused (nav: its blips not counted)
    return [
        # printable, INS, TAB: measured after the insert
        Case("printable before a tab, fits", sp * (S - 2) + t, b"", b"X",
             b"X" + sp * (S - 2) + t, 0, 1, False, 1),
        Case("printable before a tab, would pass", sp * (S - 1) + t, b"", b"X",
             sp * (S - 1) + t, 0, 0, True, 0),
        Case("INS before a tab, fits", sp * (S - 2) + t, b"", bytes([INS]),
             sp * (S - 1) + t, 0, 0, False, 1),
        Case("INS before a tab, would pass", sp * (S - 1) + t, b"", bytes([INS]),
             sp * (S - 1) + t, 0, 0, True, 0),
        Case("TAB before text, fits", X(cap - 8), b"", t,
             t + X(cap - 8), 0, 8, False, 1),
        Case("TAB before text, would pass", X(cap - 7), b"", t,
             X(cap - 7), 0, 0, True, 0),
        Case("printable at the end, fits", t + X(cap - 9), to_end, b"X",
             t + X(cap - 8), 0, cap, False, 1),
        Case("printable at the end, would pass", t + X(cap - 8), to_end, b"X",
             t + X(cap - 8), 0, cap, True, 0),
        Case("TAB at the end, fits", t + X(S - 9), to_end, t,
             t + X(S - 9) + t, 0, S, False, 1),
        Case("TAB at the end, would pass", t + X(S - 7), to_end, t,
             t + X(S - 7), 0, S + 1, True, 0),
        Case("printable before a mid-line tab", b"AB" + t + b"C" * (cap - 8),
             bytes([RIGHT]), b"X" * 6, b"A" + X(5) + b"B" + t + b"C" * (cap - 8),
             0, 6, True, 1),
        # RETURN
        Case("RETURN at col 0", X(cap), b"", bytes([RETURN]),
             b"\r" + X(cap), 1, 0, False, 1),
        Case("RETURN mid-line keeps its tab", X(cap), bytes([RIGHT]) * 8, bytes([RETURN]),
             X(8) + b"\r" + t + X(cap - 8), 1, 8, False, 1),
        Case("RETURN mid-line drops a tab that would pass", X(cap), bytes([RIGHT]) * 7,
             bytes([RETURN]), X(7) + b"\r" + X(cap - 7), 1, 0, False, 1),
        # the smart colon
        Case("the smart colon narrows", t + b"L" * (cap - 9), to_end, b":",
             b"L" * (cap - 9) + b":", 0, cap - 8, False, 1),
        Case("the smart colon's key on a full line is refused", t + b"L" * (cap - 8), to_end,
             b":", t + b"L" * (cap - 8), 0, cap, True, 0),
        # DEL
        Case("DEL before a tab narrows", b"ABCDEFGH" + t + b"C" * (cap - 16),
             bytes([RIGHT]) * 8, bytes([DEL]) * 3,
             b"ABCDE" + t + b"C" * (cap - 16), 0, 5, False, 1),
        Case("DEL join of short lines", b"AB\rCD", bytes([DOWN]), bytes([DEL]),
             b"ABCD", 0, 2, False, 1),
        Case("DEL join under a long line", long + b"\rZ", bytes([DOWN]), bytes([DEL]),
             long + b"Z", 0, cap, False, 1),
        # the cursor
        Case("RIGHT crosses a tab that ends at the cap", sp * (S - 1) + t + b"Z",
             b"", bytes([RIGHT]) * S, sp * (S - 1) + t + b"Z", 0, S, False, 0),
        Case("RIGHT refuses a tab that would end past the cap", sp * S + t + b"Z",
             b"", bytes([RIGHT]) * (S + 1), sp * S + t + b"Z", 0, S, True, 0),
        Case("DOWN onto a long line", t + X(cap - 8) + b"\r" + long, to_end,
             bytes([DOWN]), t + X(cap - 8) + b"\r" + long, 1, cap, False, 0),
        Case("UP onto a long line", long + b"\r" + t + X(cap - 8),
             bytes([DOWN]) + to_end, bytes([UP]), long + b"\r" + t + X(cap - 8),
             0, cap, False, 0),
        Case("HOME on a long line", long, to_end, bytes([HOME]), long, 0, 0, False, 0),
        # a long line cannot grow
        Case("a long line refuses a printable", long, b"", b"X", long, 0, 0, True, 0),
        Case("a long line refuses INS", long, b"", bytes([INS]), long, 0, 0, True, 0),
        Case("a long line refuses TAB", long, b"", t, long, 0, 0, True, 0),
    ]


def matrix(cap):
    return cases(cap)


class Ed:
    """A platform's editor, driven by keys.  Subclasses: load, press,
    buffer, cell, row, cursor."""

    cap = 39
    last_col = 39

    def run(self, case):
        self.load(case.text)
        self.press(case.nav)
        blips = self.press(case.keys)
        return blips

    def check(self, case):
        blips = self.run(case)
        got = self.buffer()
        assert got == case.want, f"{case.name}: buffer {got!r}"
        assert (self.cell("ed_cur_line"), self.cell("ed_cur_col")) == (case.line, case.col), \
            f"{case.name}: line/col"
        assert (blips > 0) == case.blip, f"{case.name}: {blips} blips"
        assert self.cell("ed_dirty") == case.dirty, f"{case.name}: ed_dirty"
        row, col = self.cursor()
        assert col <= self.last_col and row == case.line, f"{case.name}: cursor {row},{col}"
        for r, line in enumerate(got.split(b"\r")[:3]):
            cell = self.row(r)[self.last_col]
            if (r, self.last_col) == (row, col):
                cell &= 0x7F                     # the cursor shown on it (m65's main_loop)
            marked = cell == GT
            assert marked == (width(line) > self.cap), f"{case.name}: row {r} '>'"
