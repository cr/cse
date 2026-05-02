"""Audit module-doc Owned-files coverage — Step 3.

Two-way coverage check:

  (a) For each `doc/modules/foo.md`, read the "Owned files" table
      and verify every linked path resolves.

  (b) For each `src/foo.s`, verify there's a `doc/modules/foo.md`
      that LISTS that path in its Owned files (catches the case
      where a new source file was added but the corresponding doc
      wasn't updated to claim it).

  (c) For each `src/foo.s`, verify a `doc/modules/foo.md` exists
      at all (catches new modules added without corresponding
      doc).

The Owned-files table is recognised by markdown's standard table
syntax following an `## Owned files` heading.  Path columns use
the `[`label`](`path`)` link form.

Run:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \\
        dev/audit_doc_owned_files.py
"""

import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT / "doc" / "modules"
SRC_DIR = ROOT / "src"

# Some src/*.s files are not modules in their own right — they're
# generated tables, glue, or stubs for other modules.  These
# legitimately don't have their own doc/modules/*.md.
NO_MODULE_DOC_EXPECTED = {
    # Generated tables consumed by other modules.
    "dasm_tables", "dasm_mne_idx",
    "mn7_tables", "mn6_tables",
    "mn_modes", "mn_asm_tables", "mn_models",
    "oplen_tbl",
    # Helper bundles documented as part of their parent module.
    "mn_vars",         # documented in mn_classify.md
    # Loader: tiny relocator, documented inline.
    # (Comment out if loader.md exists — verify per build.)
}


def find_owned_files_block(text):
    """Return list of (label, path) pairs from the Owned files table."""
    # Locate the "## Owned files" heading.
    m = re.search(r"^##\s+Owned files\s*$", text, re.MULTILINE)
    if not m:
        return []
    # Walk lines until next "## " heading.
    after = text[m.end():]
    next_h = re.search(r"^##\s", after, re.MULTILINE)
    block = after[:next_h.start()] if next_h else after
    # Extract every `[label](path)` link.
    return [
        (lab.strip(), path.strip())
        for lab, path in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", block)
        if not path.startswith(("http://", "https://"))
    ]


def main():
    findings = {
        "missing_path": [],          # (a)
        "src_not_listed": [],        # (b)
        "src_no_doc": [],            # (c)
    }

    # Load all module docs and the paths they claim ownership of.
    docs_seen = {}  # module_name -> set of relative paths it owns
    for doc in sorted(MODULES_DIR.glob("*.md")):
        try:
            text = doc.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        owned = find_owned_files_block(text)
        # Normalize paths (resolve relative to doc location).
        owned_resolved = set()
        for label, raw_path in owned:
            # Strip backticks and trim.
            raw_path = raw_path.strip("`").strip()
            try:
                target = (doc.parent / raw_path).resolve()
            except (OSError, ValueError):
                continue
            owned_resolved.add(target)
            if not target.exists():
                findings["missing_path"].append({
                    "doc": str(doc.relative_to(ROOT)),
                    "label": label,
                    "path": raw_path,
                    "resolved": str(target),
                })
        docs_seen[doc.stem] = owned_resolved

    # (b) and (c): every src/foo.s should be claimed in SOME module
    # doc's Owned files table.  Some src files (mn6/mn7) are
    # documented as part of a parent module (mn_classify.md) rather
    # than having their own doc — that's fine, the doc just needs
    # to list them as owned.
    for src in sorted(SRC_DIR.glob("*.s")):
        stem = src.stem
        if stem in NO_MODULE_DOC_EXPECTED:
            continue
        target = src.resolve()
        owners = [d for d, paths in docs_seen.items() if target in paths]
        if not owners:
            # Not claimed anywhere.  Either there's no doc (c), or
            # the existing same-name doc fails to claim its own src (b).
            if (MODULES_DIR / f"{stem}.md").exists():
                findings["src_not_listed"].append({
                    "src": str(src.relative_to(ROOT)),
                    "doc": f"doc/modules/{stem}.md",
                })
            else:
                findings["src_no_doc"].append({
                    "src": str(src.relative_to(ROOT)),
                    "expected_doc": f"doc/modules/{stem}.md",
                })

    audited = len(docs_seen)
    src_count = len(list(SRC_DIR.glob("*.s")))
    print(f"Audited {audited} module docs, {src_count} src/*.s files.")
    print()

    n = sum(len(v) for v in findings.values())
    if n == 0:
        print("✓ All module docs claim only existing paths, and every "
              "non-generated src file is covered by its module doc.")
        return 0

    print(f"✗ {n} findings:")
    print()

    if findings["missing_path"]:
        print(f"── (a) Owned-file path not found "
              f"({len(findings['missing_path'])})")
        for f in findings["missing_path"]:
            print(f"   {f['doc']}  '{f['label']}' → {f['path']}")
        print()

    if findings["src_not_listed"]:
        print(f"── (b) src file exists but its module doc doesn't "
              f"claim it in Owned files ({len(findings['src_not_listed'])})")
        for f in findings["src_not_listed"]:
            extra = (f"  (also owned by: {f['owned_by_other']})"
                     if f['owned_by_other'] else "")
            print(f"   {f['src']}  expected in {f['doc']}{extra}")
        print()

    if findings["src_no_doc"]:
        print(f"── (c) src file has no module doc at all "
              f"({len(findings['src_no_doc'])})")
        for f in findings["src_no_doc"]:
            print(f"   {f['src']}  (no {f['expected_doc']})")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
