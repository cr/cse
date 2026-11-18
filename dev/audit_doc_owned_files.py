"""audit_doc_owned_files.py — the ownership audit (CDD Maintenance item 2).

Owner: doc/build_system.md

Contract source: [doc/README.md § Ownership](../doc/README.md#ownership).

The implementation of [doc/README.md § Ownership](../doc/README.md#ownership)
over every Owned files table in doc/ (doc/templates/ excepted):

  - missing path: a row links a path that does not exist;
  - completeness: every file under CDD regime — the git-tracked files
    of src/, tests/, dev/, rom/ and the Makefile — is claimed, by its
    own row or a directory row;
  - uniqueness: no file is claimed by two documents;
  - back-links: a claimed text file names its owning document in an
    `Owner:` line near its top, unless its row's Role carries
    `back-link-exempt (<reason>)`; a binary file needs that exemption;
  - exempt-file walk: each exempt file is listed with its owner and
    reason, for the Maintenance Report (informational).

A row whose path is not a link (`rom/kernal_cbm.bin`) names a local
file kept out of git: it is neither required to exist nor in the
regime.

    python dev/audit_doc_owned_files.py
"""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
REGIME = ("src", "tests", "dev", "rom", "Makefile")
_LINK = re.compile(r"\[([^\]]+)\]\(([^)#\s]+)\)")
_EXEMPT = re.compile(r"back-link-exempt \(([^)]*)\)")
_OWNER = re.compile(r"Owner:\**\s*\[?([^\s\]\)]+\.md)")
_HEAD = 40                                        # back-link: within these lines


def owned_rows(doc):
    """(paths relative to the repository, role) per row of `doc`'s
    Owned files table; only linked paths."""
    text = doc.read_text()
    m = re.search(r"^##\s+Owned files\s*$", text, re.M)
    if not m:
        return []
    block = text[m.end():]
    end = re.search(r"^#{1,2}\s", block, re.M)
    rows = []
    for line in (block[:end.start()] if end else block).splitlines():
        cells = line.split("|")
        if len(cells) < 4 or set(cells[1].strip()) <= set("-: "):
            continue
        links = [p for _, p in _LINK.findall(cells[1])]
        role = "|".join(cells[2:-1]).strip()
        rows.append(([(doc.parent / p).resolve() for p in links], role))
    return rows


def _owner_named(path):
    """The document an `Owner:` back-link near the top of `path` names
    (relative to the repository), '' for none, None for a binary."""
    try:
        head = "\n".join(path.read_text().splitlines()[:_HEAD])
    except UnicodeDecodeError:
        return None
    m = _OWNER.search(head)
    return re.sub(r"^(\.\./|\./)+", "", m.group(1)) if m else ""


def audit(root, regime):
    """The findings for the repository at `root` and its files under
    CDD regime (paths relative to `root`)."""
    root = pathlib.Path(root).resolve()
    findings = dict(missing_path=[], unclaimed=[], collisions=[],
                    no_back_link=[], wrong_back_link=[], binary_not_exempt=[],
                    exempt=[])
    claims = {}                                   # path -> {doc: exemption or None}
    for doc in sorted((root / "doc").rglob("*.md")):
        rel_doc = doc.relative_to(root).as_posix()
        if rel_doc.startswith("doc/templates/"):
            continue
        for paths, role in owned_rows(doc):
            m = _EXEMPT.search(role)
            for p in paths:
                if not p.exists():
                    findings["missing_path"].append((rel_doc, p.relative_to(root).as_posix()))
                claims.setdefault(p, {})[rel_doc] = m.group(1) if m else None
    dirs = [(p, owners) for p, owners in claims.items() if p.is_dir()]
    for rel in regime:
        path = (root / rel).resolve()
        owners = dict(claims.get(path, {}))
        if not owners:
            for d, dir_owners in dirs:
                if path.is_relative_to(d):
                    owners.update(dir_owners)
        if not owners:
            findings["unclaimed"].append(rel)
            continue
        if len(owners) > 1:
            findings["collisions"].append((rel, sorted(owners)))
            continue
        (owner, exemption), = owners.items()
        if exemption is not None:
            findings["exempt"].append((rel, owner, exemption))
            continue
        named = _owner_named(path)
        if named is None:
            findings["binary_not_exempt"].append(rel)
        elif not named:
            findings["no_back_link"].append(rel)
        elif named != owner:
            findings["wrong_back_link"].append((rel, named, owner))
    return findings


def regime_files(root=ROOT):
    out = subprocess.run(["git", "ls-files", *REGIME], cwd=root,
                         capture_output=True, text=True, check=True).stdout
    return out.split()


_TITLES = dict(
    missing_path="Owned-files row links a path that does not exist",
    unclaimed="file under CDD regime claimed by no document",
    collisions="file claimed by more than one document",
    no_back_link="claimed text file without an Owner: back-link",
    wrong_back_link="Owner: back-link names another document than the owner",
    binary_not_exempt="binary file whose row is not back-link-exempt",
)


def main():
    regime = regime_files()
    f = audit(ROOT, regime)
    print(f"Audited {len(regime)} files under CDD regime against every "
          "Owned files table.\n")
    n = sum(len(f[k]) for k in _TITLES)
    for key, title in _TITLES.items():
        if f[key]:
            print(f"── {title} ({len(f[key])})")
            for item in f[key]:
                print("   " + (" | ".join(map(str, item)) if isinstance(item, tuple) else item))
            print()
    print(f"── exempt-file walk ({len(f['exempt'])} files; check each for "
          "changes the owner should reflect)")
    for rel, owner, reason in f["exempt"]:
        print(f"   {rel}  ({owner}: {reason})")
    print()
    if n == 0:
        print("✓ Every file under CDD regime has exactly one owner, and every "
              "non-exempt one links back to it.")
        return 0
    print(f"✗ {n} findings.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
