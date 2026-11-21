"""
editor_clip.py — the clipboard's and the line moves' contract matrix,
shared by the c64 and m65 tests.

Owner: doc/modules/editor.md

Contract source: editor.md § Clipboard and line moves — the keys C= (MEGA)
+ B mark, + X cut, + C copy, + V paste, + K / + J swap with the line
above / below; whole lines; the mark kept by the cursor keys and
cleared by the other keys; paste above the cursor's line; swaps
exchanging line contents with the CRs in place.

Every case starts from a load (editor_cap.Ed.load: the text, the
cursor at line 0 col 0, `ed_dirty` = 0), moves the cursor with `nav`,
types `keys`, and is checked whole by `check`: the buffer, the
cursor's line and column, `ed_total_lines`, `ed_dirty`, the blips, the
view (`ed_top_line`, the cursor's screen row), and the first rows of
the screen and the cursor's against the buffer's lines from the top
line — inverted, the whole row, where a line is selected (`sel`, the
selection's first and last line while a mark is set).

The view cases (§ Clipboard and line moves, the view: it moves as
little as it can) run on FORTY lines with the 22 rows both platforms'
tested modes show: a move that leaves the cursor's line in view keeps
it, one below it scrolls the line onto the bottom row, one above onto
the top row.
"""

from dataclasses import dataclass

from editor_cap import TAB, HOME, DOWN, UP, RIGHT

MARK, CUT, COPY, PASTE, SWAP_UP, SWAP_DOWN = 0xBF, 0xBD, 0xBC, 0xBE, 0xA1, 0xB5


@dataclass
class Clip:
    name: str
    text: bytes
    nav: bytes
    keys: bytes
    want: bytes
    line: int
    col: int
    blip: bool = False
    dirty: int = 1
    sel: tuple = None           # (first, last) selected line while a mark is set
    top: int = 0                # ed_top_line after


def k(*codes):
    return bytes(codes)


ABC = b"AA\rBB\rCC"
ABCDE = b"AA\rBB\rCC\rDD\rEE"
ROWS = 22                                    # the source rows (c64; m65 80x25, 40x25)
FORTY = [b"L%02d" % i for i in range(40)]


def text(lines):
    return b"\r".join(lines)


def moved(lines, *edits):
    """FORTY with `edits` applied: (index, slice-replacement lines) in order."""
    out = list(lines)
    for at, new, drop in edits:
        out[at:at + drop] = new
    return text(out)

CASES = [
    # the mark
    Clip("the mark is set and its line inverted", ABC, k(DOWN), k(MARK), ABC, 1, 0, dirty=0,
         sel=(1, 1)),
    Clip("the selection runs down to the cursor", ABCDE, k(DOWN), k(MARK, DOWN, DOWN), ABCDE,
         3, 0, dirty=0, sel=(1, 3)),
    Clip("the selection runs up to the cursor", ABCDE, k(DOWN, DOWN, DOWN), k(MARK, UP, UP),
         ABCDE, 1, 0, dirty=0, sel=(1, 3)),
    Clip("moving back shrinks the selection", ABCDE, k(DOWN), k(MARK, DOWN, DOWN, UP), ABCDE,
         2, 0, dirty=0, sel=(1, 2)),
    Clip("the mark key on the marked line clears it", ABC, k(DOWN), k(MARK, MARK), ABC, 1, 0,
         dirty=0),
    Clip("cursor keys keep the mark", ABC, k(DOWN), k(MARK, DOWN, UP, RIGHT, HOME), ABC, 1, 0,
         dirty=0, sel=(1, 1)),
    Clip("another key clears the mark", ABC, k(DOWN), k(MARK) + b"Q", b"AA\rQBB\rCC", 1, 1),
    # cut
    Clip("cut the cursor's line", ABC, k(DOWN), k(CUT), b"AA\rCC", 1, 0),
    Clip("cut from a mark above", ABCDE, k(DOWN), k(MARK, DOWN, DOWN, CUT), b"AA\rEE", 1, 0),
    Clip("cut to a mark below", ABCDE, k(DOWN, DOWN, DOWN), k(MARK, UP, UP, CUT),
         b"AA\rEE", 1, 0),
    Clip("cut the last line takes the CR before it", ABC, k(DOWN, DOWN), k(CUT),
         b"AA\rBB", 1, 0),
    Clip("cut the only line", b"AA", b"", k(CUT), b"", 0, 0),
    Clip("cut, then paste puts it back", ABC, k(DOWN), k(CUT, PASTE), ABC, 2, 0),
    Clip("cut a block, then paste it two lines down", ABCDE, k(DOWN),
         k(MARK, DOWN, CUT, DOWN, PASTE), b"AA\rDD\rBB\rCC\rEE", 4, 0),
    # copy and paste
    Clip("copy leaves the text and the cursor", ABC, k(DOWN, RIGHT), k(COPY), ABC, 1, 1,
         dirty=0),
    Clip("copy, then paste twice", ABC, k(DOWN), k(COPY, PASTE, PASTE),
         b"AA\rBB\rBB\rBB\rCC", 3, 0),
    Clip("copy a block, paste below it", ABC, b"", k(MARK, DOWN, COPY, DOWN, PASTE),
         b"AA\rBB\rAA\rBB\rCC", 4, 0),
    Clip("copy the last line adds its CR", b"AA\rBB", k(DOWN), k(COPY, UP, PASTE),
         b"BB\rAA\rBB", 1, 0),
    Clip("the copy clears the mark", ABC, b"", k(MARK, COPY), ABC, 0, 0, dirty=0),
    Clip("paste with an empty clipboard is refused", ABC, b"", k(PASTE), ABC, 0, 0,
         blip=True, dirty=0),
    # swaps
    Clip("swap up", ABC, k(DOWN, RIGHT), k(SWAP_UP), b"BB\rAA\rCC", 0, 1),
    Clip("swap down", ABC, k(DOWN, RIGHT), k(SWAP_DOWN), b"AA\rCC\rBB", 2, 1),
    Clip("swap up on line 1 is refused", ABC, b"", k(SWAP_UP), ABC, 0, 0, blip=True, dirty=0),
    Clip("swap down on the last line is refused", ABC, k(DOWN, DOWN), k(SWAP_DOWN), ABC, 2, 0,
         blip=True, dirty=0),
    Clip("swap down into the last line (no CR)", b"AA\rBBB", b"", k(SWAP_DOWN),
         b"BBB\rAA", 1, 0),
    Clip("swap keeps the column on a longer line", b"A\rBBBBBB", k(DOWN) + k(RIGHT) * 4,
         k(SWAP_UP), b"BBBBBB\rA", 0, 4),
    Clip("swap moves tabs with their line", bytes([TAB]) + b"X\rYY", k(DOWN), k(SWAP_UP),
         b"YY\r" + bytes([TAB]) + b"X", 0, 0),
    Clip("two swaps restore", ABC, k(DOWN), k(SWAP_DOWN, SWAP_UP), ABC, 1, 0),
    # swaps with a clipboard present
    Clip("copy, then swap up", ABC, k(DOWN), k(COPY, SWAP_UP), b"BB\rAA\rCC", 0, 0),
    Clip("copy, then swap down", ABC, k(DOWN), k(COPY, SWAP_DOWN), b"AA\rCC\rBB", 2, 0),
    Clip("paste, then swaps across the pasted lines", ABCDE, k(DOWN),
         k(MARK, DOWN, COPY, DOWN, DOWN, PASTE, SWAP_UP, SWAP_UP, SWAP_UP, SWAP_DOWN),
         b"AA\rBB\rCC\rDD\rEE\rBB\rCC", 4, 0),
    # the view
    Clip("paste on the bottom row scrolls by its lines", text(FORTY),
         k(MARK, DOWN, DOWN, COPY) + k(DOWN) * 19, k(PASTE),
         moved(FORTY, (21, FORTY[0:3], 0)), 24, 0, top=24 - (ROWS - 1)),
    Clip("swap down on the bottom row scrolls by one", text(FORTY), k(DOWN) * 21,
         k(SWAP_DOWN), moved(FORTY, (21, [FORTY[22], FORTY[21]], 2)), 22, 0, top=1),
    Clip("swap down on the bottom row of a scrolled view", text(FORTY), k(DOWN) * 25,
         k(SWAP_DOWN), moved(FORTY, (25, [FORTY[26], FORTY[25]], 2)), 26, 0, top=5),
    Clip("swap up on the top row scrolls back by one", text(FORTY),
         k(DOWN) * 22 + k(UP) * 21, k(SWAP_UP), moved(FORTY, (0, [FORTY[1], FORTY[0]], 2)),
         0, 0, top=0),
    Clip("swap in view keeps the view", text(FORTY), k(DOWN) * 25 + k(UP) * 10,
         k(SWAP_DOWN), moved(FORTY, (15, [FORTY[16], FORTY[15]], 2)), 16, 0, top=4),
    Clip("cut with the mark above the view puts its line on top", text(FORTY),
         k(DOWN, MARK) + k(DOWN) * 24, k(CUT), moved(FORTY, (1, [], 25)), 1, 0, top=1),
    Clip("copy on the bottom row keeps the view", text(FORTY), k(DOWN) * 20 + k(MARK, DOWN),
         k(COPY), text(FORTY), 21, 0, dirty=0),
]


def screen_line(line, width):
    """The screen codes a short line of capitals, digits and tabs renders as."""
    out, col = [], 0
    for b in line:
        if b == TAB:
            pad = 8 - col % 8
            out += [0x20] * pad
            col += pad
        else:
            out.append(b - 0x40 if 0x41 <= b <= 0x5A else b)
            col += 1
    return out + [0x20] * (width - len(out))


def check(ed, case):
    ed.load(case.text)
    ed.press(case.nav)
    blips = ed.press(case.keys)
    got = ed.buffer()
    assert got == case.want, f"{case.name}: buffer {got!r}"
    assert (ed.cell("ed_cur_line"), ed.cell("ed_cur_col")) == (case.line, case.col), \
        f"{case.name}: line/col"
    assert ed.cell("ed_total_lines") == got.count(b"\r") + 1, f"{case.name}: ed_total_lines"
    assert ed.cell("ed_dirty") == case.dirty, f"{case.name}: ed_dirty"
    assert (blips > 0) == case.blip, f"{case.name}: {blips} blips"
    assert ed.cell("ed_top_line") == case.top, f"{case.name}: ed_top_line"
    row, col = ed.cursor()
    assert row == case.line - case.top, f"{case.name}: cursor row {row}"
    width = len(ed.row(0))
    lines = got.split(b"\r")
    for r in sorted({*range(5), row}):
        if case.top + r >= len(lines):
            continue
        line = lines[case.top + r]
        shown = list(ed.row(r))
        want = screen_line(line, width)
        if case.sel and case.sel[0] <= case.top + r <= case.sel[1]:
            want = [c | 0x80 for c in want]      # the selection: the whole row inverted
        if r == row:                             # the cursor shown on it (m65's main_loop)
            shown[col] &= 0x7F
            want[col] &= 0x7F
        assert shown == want, f"{case.name}: row {r}"
