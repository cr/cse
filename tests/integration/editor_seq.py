"""
editor_seq.py — random key sequences against a line model, shared by the
c64 and m65 tests.

Owner: doc/modules/editor.md

Contract source: editor.md § Clipboard and line moves (mark, cut, copy,
paste, the swaps, the view after them) and § Key handling (UP, DOWN,
HOME, RETURN, a printable).  testing.md Principle 22 (model-based
sequences): the matrices (editor_cap.py, editor_clip.py) pin each key
from a load; this drives seeded random sequences, where the state one
key leaves — a clipboard, a mark, a scrolled view — is the next key's
start, and checks after every key, against `Model`:

- the buffer's bytes, `ed_cur_line`, `ed_total_lines`;
- a refusal's blip, and none otherwise;
- the view: kept while the cursor's line is in it, else scrolled until
  that line is on the top or the bottom row (the least move).

The column is read from the editor (the model trusts it, for the next
printable); RETURN is typed at col 0 (after HOME: no smart indent), and
a printable only on a line short of the cap.  The seeds are fixed: a
failure names its seed, its step and the keys before it.
"""

import random

from editor_cap import UP, DOWN, HOME, RETURN
from editor_clip import MARK, CUT, COPY, PASTE, SWAP_UP, SWAP_DOWN

X = ord("X")
KEYS = [UP, DOWN, DOWN, UP, MARK, CUT, COPY, PASTE, PASTE, SWAP_UP, SWAP_DOWN,
        SWAP_UP, SWAP_DOWN, HOME, RETURN, X]
KEEP_MARK = (UP, DOWN, HOME, MARK, CUT, COPY)


class Model:
    """The text as lines, the cursor's line, the mark, the clipboard."""

    def __init__(self, lines):
        self.lines, self.cur, self.mark, self.clip = list(lines), 0, None, []

    def text(self):
        return b"\r".join(self.lines)

    def key(self, k, col):
        """Apply key `k` (the cursor at `col`); True when it is refused."""
        L = self.lines
        if k not in KEEP_MARK:
            self.mark = None
        if k == UP:
            if self.cur == 0:
                return True
            self.cur -= 1
        elif k == DOWN:
            if self.cur == len(L) - 1:
                return True
            self.cur += 1
        elif k == MARK:
            self.mark = None if self.mark == self.cur else self.cur
        elif k in (CUT, COPY):
            lo, hi = sorted((self.cur, self.cur if self.mark is None else self.mark))
            self.mark, self.clip = None, L[lo:hi + 1]
            if k == CUT:
                del L[lo:hi + 1]
                L[:] = L or [b""]
                self.cur = min(lo, len(L) - 1)
        elif k == PASTE:
            if not self.clip:
                return True
            L[self.cur:self.cur] = self.clip
            self.cur += len(self.clip)
        elif k == SWAP_UP:
            if self.cur == 0:
                return True
            L[self.cur - 1], L[self.cur] = L[self.cur], L[self.cur - 1]
            self.cur -= 1
        elif k == SWAP_DOWN:
            if self.cur == len(L) - 1:
                return True
            L[self.cur], L[self.cur + 1] = L[self.cur + 1], L[self.cur]
            self.cur += 1
        elif k == RETURN:                        # at col 0
            L.insert(self.cur, b"")
            self.cur += 1
        elif k == X:
            L[self.cur] = L[self.cur][:col] + b"X" + L[self.cur][col:]
        return False


def run(ed, seed, n_lines, steps, rows):
    """`steps` random keys from `seed` on `n_lines` short lines; `rows`:
    the source rows the mode shows.  `ed` is the platform's Ed with
    `word(name)` (a 16-bit cell)."""
    rnd = random.Random(seed)
    m = Model([b"L%02d" % i + b"Q" * rnd.randrange(4) for i in range(n_lines)])
    ed.load(m.text())
    keys = []
    for step in range(steps):
        k = rnd.choice(KEYS)
        if k == X and len(m.lines[m.cur]) > 25:
            continue
        top0 = ed.word("ed_top_line")
        refused = m.key(k, ed.cell("ed_cur_col"))
        blips = ed.press(bytes([HOME, k]) if k == RETURN else bytes([k]))
        keys.append(f"${k:02X}")
        at = f"seed {seed} step {step} after {' '.join(keys[-12:])}"
        assert ed.buffer() == m.text(), f"{at}: buffer"
        assert ed.word("ed_cur_line") == m.cur, f"{at}: ed_cur_line"
        assert ed.word("ed_total_lines") == len(m.lines), f"{at}: ed_total_lines"
        assert (blips > 0) == refused, f"{at}: {blips} blips"
        want = (top0 if top0 <= m.cur < top0 + rows
                else m.cur if m.cur < top0 else m.cur - (rows - 1))
        assert ed.word("ed_top_line") == want, f"{at}: ed_top_line"
