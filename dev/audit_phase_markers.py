"""Audit historical phase markers — Step 1E of the doc-audit plan.

Per Phase-25 DDD Log amendment **A3** (Stale historical markers as
a DDD Maintenance audit item): grep the corpus (doc + src
comments) for time-anchored phrases that often outlive their
context.

The script can't decide load-bearing vs stale automatically — the
output is a structured report grouped by marker class for human
triage.  But it makes triage tractable by showing all hits at once
with file:line context.

Marker classes (per A3):
  - Phase numbers       :  /Phase\\s+\\d+/i
  - Move numbers        :  /Move\\s+\\d+/
  - Code-relocation     :  /moved to|moved from|relocated/i
  - Refactor history    :  /previously|was formerly|originally/i
  - In-line TODOs       :  /TODO:|FIXME:|XXX:|HACK:/

Run:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \\
        dev/audit_phase_markers.py

Output: per-class report sorted by frequency.  No exit code
gating — this is a triage aid, not a CI check.  (Many markers
are legitimately load-bearing; the script can't tell.)
"""

import re
import sys
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent

# (class_label, regex_pattern, comment)
MARKERS = [
    ("Phase number",
     re.compile(r"\bPhase\s+\d+\b", re.IGNORECASE),
     "Phase X — likely-stale marker if X is several behind current"),
    ("Move number",
     re.compile(r"\bMove\s+\d+\b"),
     "Move N — internal phase-substep marker; usually stale post-phase"),
    ("Code relocation",
     re.compile(r"\b(moved\s+to|moved\s+from|relocated|extracted\s+from)\b",
                re.IGNORECASE),
     "moved-to / moved-from — relocation comments outlive their refactor"),
    ("Refactor history",
     re.compile(r"\b(previously|was\s+formerly|originally\s+(was|named|in))\b",
                re.IGNORECASE),
     "previously / was formerly — historical recap, usually retire-able"),
    ("Inline TODO",
     re.compile(r"\b(TODO|FIXME|XXX|HACK):"),
     "TODO/FIXME/XXX/HACK — direct in-line task markers"),
]

# Files to scan
def files_to_scan():
    out = []
    out.append(ROOT / "README.md")
    out.append(ROOT / "background.md")
    if (ROOT / "doc").exists():
        out.extend((ROOT / "doc").rglob("*.md"))
    if (ROOT / "src").exists():
        out.extend((ROOT / "src").rglob("*.s"))
        out.extend((ROOT / "src").rglob("*.inc"))
    return [
        f for f in out
        if f.is_file()
        and ".claude" not in f.parts
        and "build" not in f.parts
    ]


def main():
    files = files_to_scan()
    print(f"Scanning {len(files)} files (doc/ + src/) ...\n")

    # findings[class_label] = list of (path, lineno, line_text)
    findings = {label: [] for label, _, _ in MARKERS}

    for f in files:
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for label, pattern, _ in MARKERS:
                if pattern.search(line):
                    findings[label].append(
                        (f.relative_to(ROOT), lineno, line.strip()[:100]))

    # Closed/struck-through items in TODO.md are intentional
    # historical record — filter them.  Same for retrospective
    # files (ddd_log.md, project_phase*_complete.md).
    def is_intentionally_historical(path, line):
        rel = path.as_posix()
        if "ddd_log.md" in rel:
            return True
        if "project_phase" in rel and "_complete.md" in rel:
            return True
        if "~~" in line:
            return True
        return False

    total_raw = sum(len(v) for v in findings.values())
    filtered = {
        label: [
            f for f in fs
            if not is_intentionally_historical(f[0], f[2])
        ]
        for label, fs in findings.items()
    }
    total_filt = sum(len(v) for v in filtered.values())

    print(f"Raw hits:      {total_raw}")
    print(f"After filter:  {total_filt}  "
          f"(excluded ddd_log.md, project_phase*_complete.md, "
          f"and ~~struck-through~~ lines)")
    print()

    for label, _, comment in MARKERS:
        hits = filtered[label]
        if not hits:
            continue
        # Group by file
        by_file = defaultdict(list)
        for path, lineno, line in hits:
            by_file[str(path)].append((lineno, line))
        print(f"── {label} ({len(hits)} hits in {len(by_file)} files)")
        print(f"   {comment}")
        # Show top 5 most-affected files
        ranked = sorted(by_file.items(), key=lambda kv: -len(kv[1]))
        for fname, items in ranked[:8]:
            head = items[:3]
            rest = len(items) - len(head)
            print(f"   {fname}  ({len(items)} hit{'s' if len(items)>1 else ''})")
            for lineno, line in head:
                print(f"     {lineno:4d}: {line}")
            if rest:
                print(f"     ... and {rest} more in this file")
        if len(ranked) > 8:
            extra = sum(len(v) for _, v in ranked[8:])
            print(f"   ... and {extra} hits in {len(ranked)-8} other files")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
