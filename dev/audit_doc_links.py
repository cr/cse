"""Audit doc cross-references — Step 1A of the doc-audit plan.

Walks every Markdown file under doc/ + root-level README.md/background.md,
extracts every `[text](path)` and `<a href="path">` reference, and reports
the ones whose target doesn't resolve.  Resolves anchors (`#section`)
against GitHub-Flavoured-Markdown slug rules:

  - lowercased
  - non-alphanumeric → '-'
  - collapsed runs of '-'
  - trimmed leading/trailing '-'

Run:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \
        dev/audit_doc_links.py

Output: a structured report of suspect lines.  Exit non-zero if any
broken links found, so it can run in CI.
"""

import re
import sys
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent

DOC_GLOB_DIRS = [ROOT / "doc"]
ROOT_DOCS = [ROOT / "README.md", ROOT / "background.md"]

# Patterns:
#   [text](url)              — markdown inline link
#   <img src="url">          — inline image (we still verify these)
#   <a href="url">           — raw HTML anchor
LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
IMG_RE  = re.compile(r'<img\s+[^>]*src="([^"]+)"', re.IGNORECASE)
HREF_RE = re.compile(r'<a\s+[^>]*href="([^"]+)"', re.IGNORECASE)


def gh_slug(heading_text):
    """Approximate GitHub's anchor-slug for a heading.

    GitHub's algorithm (per github-slugger):
      1. Lowercase.
      2. Replace internal whitespace runs with single '-'.
         (Whitespace runs DO collapse, but trailing punctuation
         removal happens AFTER, leaving multiple '-'s adjacent
         when punctuation sat between spaces.)
      3. Drop characters that are not letters/digits/hyphen/underscore.

    Critically: GitHub does NOT collapse runs of hyphens.  A heading
    "Foo — Bar" becomes `foo--bar` (two hyphens because the em-dash
    sat between two spaces, both of which became hyphens, and the
    em-dash itself was stripped).
    """
    s = heading_text.lower()
    # Whitespace → hyphen FIRST (collapsing whitespace runs).
    s = re.sub(r"\s+", "-", s)
    # Drop everything except letters, digits, hyphen, underscore.
    s = re.sub(r"[^\w-]", "", s, flags=re.UNICODE)
    return s.strip("-")


def collect_anchors(file_path):
    """Return set of anchor slugs available in `file_path`.

    Handles GitHub's duplicate-disambiguation: a heading whose slug
    has appeared before gets `-1`, `-2`, etc. appended.  Skips lines
    inside fenced code blocks (``` … ```).
    """
    if not file_path.exists() or not file_path.is_file():
        return set()
    anchors = set()
    counts = {}
    try:
        text = file_path.read_text()
    except (OSError, UnicodeDecodeError):
        return set()
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            base = gh_slug(m.group(2))
            n = counts.get(base, 0)
            slug = base if n == 0 else f"{base}-{n}"
            anchors.add(slug)
            counts[base] = n + 1
        # explicit <a name="..."> or <a id="...">
        for am in re.finditer(
                r'<a\s+(?:name|id)="([^"]+)"', line, flags=re.IGNORECASE):
            anchors.add(am.group(1).lower())
    return anchors


def all_md_files():
    files = list(ROOT_DOCS)
    for d in DOC_GLOB_DIRS:
        if d.exists():
            files.extend(d.rglob("*.md"))
    # Skip worktrees and hidden dirs
    return [
        f for f in files
        if ".claude" not in f.parts
        and "build" not in f.parts
        and f.is_file()
    ]


def check_target(src_file, raw_url):
    """Return None on success, or a string describing the failure."""
    url = raw_url.strip()
    if url.startswith(("http://", "https://", "mailto:")):
        return None  # external — skip
    if url.startswith("#"):
        target_file = src_file
        anchor = url[1:]
    else:
        if "#" in url:
            path_part, anchor = url.split("#", 1)
        else:
            path_part, anchor = url, None
        target_file = (src_file.parent / path_part).resolve()
        if not target_file.exists():
            return f"missing file: {path_part}"
        if target_file.is_dir():
            return None  # link to a dir is OK
    if anchor:
        # Only check anchors in markdown files
        if target_file.suffix.lower() == ".md":
            anchors = collect_anchors(target_file)
            anchor_slug = anchor.lower()
            if anchor_slug not in anchors:
                return f"anchor not found: #{anchor}"
    return None


def main():
    files = all_md_files()
    findings = defaultdict(list)
    n_links = 0
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
            if in_fence:
                continue
            for pattern, kind in (
                    (LINK_RE, "md-link"),
                    (IMG_RE, "img"),
                    (HREF_RE, "html-a")):
                for m in pattern.finditer(line):
                    n_links += 1
                    url = m.group(2 if kind == "md-link" else 1)
                    err = check_target(f, url)
                    if err:
                        rel_f = f.relative_to(ROOT)
                        findings[str(rel_f)].append((lineno, kind, url, err))

    print(f"Scanned {len(files)} files, {n_links} links.")
    print()
    if not findings:
        print("✓ All references resolve.")
        return 0

    total = sum(len(v) for v in findings.values())
    print(f"✗ {total} suspect references in {len(findings)} files:")
    print()
    for fname in sorted(findings):
        print(f"── {fname}")
        for lineno, kind, url, err in findings[fname]:
            print(f"   line {lineno:4d} [{kind}] {url}")
            print(f"             → {err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
