"""Audit doc numerical claims — Step 1D of the doc-audit plan.

Scrapes byte/size claims from doc/ + root README.md and compares
against current build artifacts:

  - "N bytes ($XX-$YY)"  ZP   →  src/zp.s + linker map
  - "N tests passing"          →  pytest collect-only
  - "PRG size N bytes"         →  build/release/*/cse*.prg

Reports lines where the claimed number disagrees with the
current ground truth.

Run:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \
        dev/audit_doc_numbers.py

Output: structured report.  Exit non-zero if drift detected so it
can run in CI.
"""

import re
import sys
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent

# ── Sources of truth ────────────────────────────────────────────────────

def zp_size_from_lbl():
    """Read __ZP_LAST__ from the linker map.  This is the FIRST FREE
    byte after CSE's ZP.  CSE ZP runs $02..__ZP_LAST__-1."""
    lbl = ROOT / "build" / "debug" / "cmos" / "cse.lbl"
    if not lbl.exists():
        return None
    try:
        for line in lbl.read_text().splitlines():
            m = re.match(r"al\s+([0-9A-F]+)\s+\.__ZP_LAST__\s*$", line)
            if m:
                return int(m.group(1), 16)
    except (OSError, UnicodeDecodeError):
        return None
    return None


def zp_used_bytes():
    """CSE ZP byte count: __ZP_LAST__ - 2 (CSE starts at $02)."""
    last = zp_size_from_lbl()
    return None if last is None else last - 0x02


def zp_free_bytes():
    """Bytes free in the user range $00–$7F: $80 - __ZP_LAST__.
    KERNAL owns $80-$FF; CSE leaves $00-$01 to the CPU port."""
    last = zp_size_from_lbl()
    return None if last is None else 0x80 - last


def prg_size(variant):
    p = ROOT / "build" / "release" / variant / (
        "cse.prg" if variant == "6510" else f"cse-{variant}.prg")
    return p.stat().st_size if p.exists() else None


def test_count():
    """Number of test items collected by pytest."""
    out = subprocess.run(
        ["/Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/pytest",
         "tests/", "--collect-only", "-q"],
        cwd=ROOT, capture_output=True, text=True, check=False)
    # Last line of stdout is "N tests collected" or similar.
    for line in reversed(out.stdout.splitlines()):
        m = re.search(r"(\d+)\s+tests?\s+collected", line)
        if m:
            return int(m.group(1))
    return None


# ── Doc patterns to scrape ──────────────────────────────────────────────

# (pattern, extractor → claimed_value, ground_truth_fn, label)
# Each pattern returns the line for context; the extractor pulls the
# numeric claim; the ground_truth_fn returns the expected value
# (or None if not currently knowable).

CHECKS = [
    # ZP module-design overview "N bytes ($02–$XX)"
    {
        "name": "ZP used bytes",
        "regex": re.compile(
            r"(\d+)\s+bytes\s+\(\$02[–-]\$([0-9A-Fa-f]{2})\)"),
        "claimed": lambda m: int(m.group(1)),
        "expected": lambda m: zp_used_bytes(),
        "context": "ZP overview header",
    },
    # ZP "N bytes free ($XX–$7F)"
    {
        "name": "ZP free bytes",
        "regex": re.compile(
            r"(\d+)\s+bytes\s+free\s+\(\$([0-9A-Fa-f]{2})[–-]\$7F\)"),
        "claimed": lambda m: int(m.group(1)),
        "expected": lambda m: zp_free_bytes(),
        "context": "ZP free header",
    },
    # PRG sizes ("21077B", "21000 bytes", etc.) — only check if 4-5 digit
    # with explicit variant context on the same line
    {
        "name": "PRG size 6510",
        "regex": re.compile(
            r"6510(?:[^\n]{0,80}?)(\d{5})\s*(?:B|bytes)\b", re.IGNORECASE),
        "claimed": lambda m: int(m.group(1)),
        "expected": lambda m: prg_size("6510"),
        "context": "6510 PRG size",
        "tolerance": 200,  # exomizer compression varies
    },
    {
        "name": "PRG size 6502",
        "regex": re.compile(
            r"\b6502(?:[^\n]{0,80}?)(\d{5})\s*(?:B|bytes)\b", re.IGNORECASE),
        "claimed": lambda m: int(m.group(1)),
        "expected": lambda m: prg_size("6502"),
        "context": "6502 PRG size",
        "tolerance": 200,
    },
    {
        "name": "PRG size cmos / 65C02",
        "regex": re.compile(
            r"(?:65[Cc]02|cmos)(?:[^\n]{0,80}?)(\d{5})\s*(?:B|bytes)\b",
            re.IGNORECASE),
        "claimed": lambda m: int(m.group(1)),
        "expected": lambda m: prg_size("cmos"),
        "context": "65C02 PRG size",
        "tolerance": 200,
    },
    # Test-count claims "N tests passing", "N passing"
    # Tolerance ~25 covers (a) the ~18 currently-skipped tests, since
    # the doc may say "passing" while collect-only counts everything,
    # and (b) small churn in the time between commit and audit run.
    {
        "name": "Test count",
        "regex": re.compile(
            r"(\d{3,5})\s+(?:tests?\s+)?passing\b", re.IGNORECASE),
        "claimed": lambda m: int(m.group(1)),
        "expected": lambda m: test_count(),
        "context": "Test suite size",
        "tolerance": 25,
    },
]


def all_md_files():
    files = [ROOT / "README.md", ROOT / "background.md"]
    files.extend((ROOT / "doc").rglob("*.md"))
    return [
        f for f in files
        if f.is_file()
        and ".claude" not in f.parts
        and "build" not in f.parts
    ]


def main():
    files = all_md_files()
    findings = []
    for f in files:
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            # Don't penalise code-fence content (build commands etc.).
            if in_fence:
                continue
            # Don't penalise stricken-through text (~~...~~) — those are
            # historical entries deliberately preserved.
            if "~~" in line:
                continue
            for check in CHECKS:
                for m in check["regex"].finditer(line):
                    claimed = check["claimed"](m)
                    expected = check["expected"](m)
                    if expected is None:
                        continue
                    diff = abs(claimed - expected)
                    tol = check.get("tolerance", 0)
                    if diff > tol:
                        findings.append({
                            "file": str(f.relative_to(ROOT)),
                            "line": lineno,
                            "name": check["name"],
                            "claimed": claimed,
                            "expected": expected,
                            "diff": diff,
                            "context": line.strip()[:80],
                        })

    print(f"Scanned {len(files)} files.")
    print(f"Source-of-truth values:")
    print(f"  ZP used bytes:  {zp_used_bytes()}")
    print(f"  ZP free bytes:  {zp_free_bytes()}")
    print(f"  PRG 6510:       {prg_size('6510')} B")
    print(f"  PRG 6502:       {prg_size('6502')} B")
    print(f"  PRG cmos:       {prg_size('cmos')} B")
    print(f"  Test count:     {test_count()}")
    print()

    if not findings:
        print("✓ No numerical drift detected.")
        return 0

    findings.sort(key=lambda f: -f["diff"])
    print(f"✗ {len(findings)} drift findings (sorted by diff size):")
    print()
    for fnd in findings:
        print(f"── {fnd['file']}:{fnd['line']}  [{fnd['name']}]")
        print(f"   claimed={fnd['claimed']}  expected={fnd['expected']}  "
              f"diff={fnd['diff']}")
        print(f"   {fnd['context']}")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
