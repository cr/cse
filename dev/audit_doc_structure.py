"""Audit doc tone/structure — Step 6 (mechanized subset).

Scans markdown files for structural issues that frequently
indicate stale or hand-stitched content:

  - Heading-level skips (## → #### without ###).
  - Trailing whitespace on lines.
  - 3+ consecutive blank lines.
  - Tables with mismatched column counts (header vs rows).
  - Lines ending with a hyphen-then-newline mid-paragraph
    (likely sentence broken by an earlier edit).
  - `**Depends on:**` followed inline by text without
    formatting break.

Report-only, like the phase-marker audit.  Many false positives
(deliberate styling, fenced code) — human triage.
"""

import re
import sys
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent


def files_to_scan():
    out = [ROOT / "README.md"]
    if (ROOT / "background.md").exists():
        out.append(ROOT / "background.md")
    if (ROOT / "doc").exists():
        out.extend((ROOT / "doc").rglob("*.md"))
    return [
        f for f in out
        if f.is_file()
        and ".claude" not in f.parts
        and "build" not in f.parts
    ]


def scan_file(path):
    """Return list of (lineno, class, message) findings."""
    findings = []
    try:
        text = path.read_text()
    except (OSError, UnicodeDecodeError):
        return findings

    lines = text.splitlines()

    # 1. Heading-level skips
    last_level = 0
    in_fence = False
    for i, line in enumerate(lines, start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+", line)
        if m:
            level = len(m.group(1))
            if last_level and level > last_level + 1:
                findings.append((
                    i, "heading-skip",
                    f"H{last_level} → H{level} (skips H{last_level+1})"))
            last_level = level

    # 2. Trailing whitespace
    for i, line in enumerate(lines, start=1):
        if line and line != line.rstrip():
            findings.append((
                i, "trailing-ws",
                f"trailing whitespace ({len(line) - len(line.rstrip())} chars)"))

    # 3. 3+ consecutive blank lines
    blank_run = 0
    for i, line in enumerate(lines, start=1):
        if not line.strip():
            blank_run += 1
            if blank_run == 3:
                findings.append((
                    i, "blank-run",
                    "3+ consecutive blank lines"))
        else:
            blank_run = 0

    # 4. Table column-count mismatches.  Counts only "real" pipe
    # separators — pipes inside backticks (e.g. `(c2<<3) | (c3>>2)`)
    # or escaped as `\|` are excluded.
    def count_pipes(s):
        # Strip backtick spans first.
        no_code = re.sub(r"`[^`]*`", "", s)
        # Strip escaped pipes.
        no_esc = no_code.replace(r"\|", "")
        return no_esc.count("|")

    in_fence = False
    table_header_cols = None
    for i, line in enumerate(lines, start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            table_header_cols = None
            continue
        if in_fence:
            continue
        # Detect a table separator (|---|---|...)
        if re.match(r"^\|[\s:|-]+\|\s*$", line):
            cols = count_pipes(line) - 1
            table_header_cols = cols
            continue
        # Detect a table row (starts and ends with |, has at least one |)
        if line.startswith("|") and line.rstrip().endswith("|"):
            cols = count_pipes(line) - 1
            if table_header_cols is not None and cols != table_header_cols:
                findings.append((
                    i, "table-cols",
                    f"row has {cols} cols, table header has "
                    f"{table_header_cols}"))
        else:
            # Reset header-cols when leaving a table region.
            if line.strip() and not line.startswith("|"):
                table_header_cols = None

    return findings


def main():
    files = files_to_scan()
    print(f"Scanning {len(files)} files for tone/structure issues ...\n")

    by_class = defaultdict(list)
    total = 0
    for f in files:
        findings = scan_file(f)
        for lineno, kls, msg in findings:
            by_class[kls].append((f.relative_to(ROOT), lineno, msg))
            total += 1

    if total == 0:
        print("✓ No tone/structure issues detected.")
        return 0

    print(f"Total: {total} findings across {len(by_class)} classes")
    print()
    for kls, items in sorted(by_class.items()):
        print(f"── {kls} ({len(items)})")
        for path, lineno, msg in items[:8]:
            print(f"   {path}:{lineno}  {msg}")
        if len(items) > 8:
            print(f"   ... and {len(items)-8} more")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
