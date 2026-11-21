"""
test_help_text.py — the help popup's text and its generator (Tier U)

Owner: doc/modules/help.md

Contract source: help.md § The text.  `src/help.txt` is the cheat sheet
as the user reads it: at most 37 characters a line, four sections
(repl, keys, directives, expressions).  `dev/help_text.py` writes
`src/help_text.s`: `HELP_LINES` and `help_text`, each line a length
byte and its screen codes in the lower/upper set; a line too long or a
character without a glyph stops it.  The text covers every REPL
command of repl.md and every directive of assembler_syntax.md.
"""

import pathlib
import re
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "dev"))
import help_text as H                            # noqa: E402

TEXT = (ROOT / "src" / "help.txt").read_text(encoding="utf-8")
SECTIONS = ("repl", "keys", "directives", "expressions")
CMD_COLUMN = 18                 # a line's command column: its first 18 characters


def sections():
    """{name: [lines]} — a section is its header line and the lines up to
    the next blank one."""
    out, name = {}, None
    for line in TEXT.split("\n"):
        if not line:
            name = None
        elif name is None:
            name = line.split()[0]
            out[name] = []
        else:
            out[name].append(line)
    return out


def doc_commands():
    """The command keys of repl.md's `### Commands — …` tables."""
    keys, inside = set(), False
    for line in (ROOT / "doc" / "modules" / "repl.md").read_text().split("\n"):
        if line.startswith("### "):
            inside = line.startswith("### Commands — ")
        elif inside:
            m = re.match(r"\| `([^`]+)` +\|", line)
            if m:
                keys.add(m.group(1))
    return keys


def doc_directives():
    """The directives of assembler_syntax.md § Directives › Summary."""
    text = (ROOT / "doc" / "assembler_syntax.md").read_text()
    summary = text[text.index("### Summary"):text.index("### `.org`")]
    return set(re.findall(r"^\| `(\.[a-z]+)` \|", summary, re.M))


# ── the text ─────────────────────────────────────────────────────────

def test_lines_fit_the_window_and_end_clean():
    for n, line in enumerate(TEXT.rstrip("\n").split("\n"), 1):
        assert len(line) <= H.MAX_COL == 37, (n, line)
        assert line == line.rstrip(), (n, line)


def test_the_four_sections_in_order():
    assert tuple(sections()) == SECTIONS


def test_every_repl_command_has_its_line():
    cmds = doc_commands()
    assert {"m", ".", "d", "a", "j", "g", "c", "r", "M", "b", "t", "o", "@",
            "+", "-", "l", "s", "$", "i", "?", "k", "B", "C", "u", "Q", "R",
            "x", ";"} <= cmds
    listed = {tok for line in sections()["repl"] for tok in line[:CMD_COLUMN].split()}
    assert cmds - listed == set()


def test_every_directive_has_its_line():
    dirs = doc_directives()
    assert {".org", ".const", ".cpu", ".db", ".dw", ".dd", ".str", ".scr",
            ".res", ".align", ".bas"} <= dirs
    listed = {line.split()[0] for line in sections()["directives"]}
    assert dirs - listed == set()


def test_the_keys_section_names_help():
    assert any(line.split()[0] == "help" for line in sections()["keys"])


# ── the generator ────────────────────────────────────────────────────

@pytest.mark.parametrize("ch, code", [
    ("a", 0x01), ("z", 0x1A), ("A", 0x41), ("Z", 0x5A), ("@", 0x00),
    ("[", 0x1B), ("£", 0x1C), ("]", 0x1D), ("^", 0x1E), (" ", 0x20),
    ("!", 0x21), ("0", 0x30), ("9", 0x39), ("$", 0x24), ("?", 0x3F),
    (".", 0x2E), ('"', 0x22), (";", 0x3B), ("<", 0x3C), (">", 0x3E),
])
def test_encode_maps_to_the_lower_upper_set(ch, code):
    assert H.encode(ch) == bytes([code])


@pytest.mark.parametrize("ch", list("|\\{}~`_") + ["\t", "é"])
def test_encode_refuses_a_character_without_a_glyph(ch):
    with pytest.raises(H.HelpTextError):
        H.encode("ab" + ch)


def test_load_refuses_a_line_too_long():
    H.load("x" * 37 + "\n")
    with pytest.raises(H.HelpTextError, match="2"):
        H.load("ok\n" + "x" * 38 + "\n")


def test_load_refuses_a_bad_character_naming_its_line():
    with pytest.raises(H.HelpTextError, match="3"):
        H.load("a\nb\nc|d\n")


def test_load_keeps_blank_lines_and_drops_the_final_newline():
    assert H.load("a\n\nb\n") == ["a", "", "b"]


def _rows(source):
    """(HELP_LINES, [bytes of each .byte row]) of a rendered file."""
    count = int(re.search(r"^HELP_LINES\s*=\s*(\d+)", source, re.M).group(1))
    rows = [bytes(int(v.strip().lstrip("$"), 16 if v.strip().startswith("$") else 10)
                  for v in m.group(1).split(";")[0].split(","))
            for m in re.finditer(r"^\s*\.byte\s+(.*)$", source, re.M)]
    return count, rows


def test_render_is_a_length_byte_then_the_codes_per_line():
    lines = ["ab", "", "Q $"]
    source = H.render(lines)
    assert 'segment "KDATA"' in source and re.search(r"^help_text:", source, re.M)
    assert re.search(r"\.export\s+help_text", source)
    count, rows = _rows(source)
    assert count == 3
    assert rows == [bytes([2, 0x01, 0x02]), bytes([0]), bytes([3, 0x51, 0x20, 0x24])]


def test_the_generated_file_is_current():
    assert (ROOT / "src" / "help_text.s").read_text() == H.render(H.load(TEXT))


def test_the_generated_file_holds_the_whole_text():
    count, rows = _rows((ROOT / "src" / "help_text.s").read_text())
    lines = H.load(TEXT)
    assert count == len(lines) == len(rows)
    assert rows == [bytes([len(l)]) + H.encode(l) for l in lines]
