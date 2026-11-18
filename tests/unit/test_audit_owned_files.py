"""test_audit_owned_files.py — the ownership audit (dev/audit_doc_owned_files.py).

Owner: doc/build_system.md

Contract source: [doc/README.md § Ownership](../../doc/README.md#ownership).

Tier U, on small trees in tmp_path: every Owned files table of the
corpus is read (module docs and the others); a file under CDD regime
is claimed by exactly one document, directly or through a directory
row; a claimed text file names its owner in an `Owner:` back-link
unless its row is `back-link-exempt (<reason>)`; exempt rows are
listed for the exempt-file walk; and a linked path must exist.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import audit_doc_owned_files as A                  # noqa: E402

TABLE = "# {title}\n\n## Owned files\n\n| File | Role |\n|------|------|\n{rows}\n## Next\n"


def tree(tmp_path, files, docs):
    """Write `files` {path: text|bytes} and `docs` {doc: [rows]}; the
    regime is every file written outside doc/."""
    for path, data in files.items():
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        (p.write_bytes if isinstance(data, bytes) else p.write_text)(data)
    for doc, rows in docs.items():
        p = tmp_path / doc
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(TABLE.format(title=doc, rows="\n".join(rows)))
    return A.audit(tmp_path, sorted(files))


def row(doc, path, role="implementation"):
    up = "../" * (doc.count("/"))
    return f"| [`{path}`]({up}{path}) | {role} |"


def test_a_claimed_file_with_its_back_link_is_clean(tmp_path):
    f = tree(tmp_path, {"dev/x.py": '"""x.py\n\nOwner: doc/a.md\n"""\n'},
             {"doc/a.md": [row("doc/a.md", "dev/x.py")]})
    assert not any(f.values()), f


def test_an_unclaimed_file_is_a_gap(tmp_path):
    f = tree(tmp_path, {"dev/x.py": "# Owner: doc/a.md\n", "dev/y.py": "\n"},
             {"doc/a.md": [row("doc/a.md", "dev/x.py")]})
    assert f["unclaimed"] == ["dev/y.py"]


def test_two_owners_collide(tmp_path):
    f = tree(tmp_path, {"src/z.s": "; z.s\n; Owner: doc/modules/z.md\n"},
             {"doc/modules/z.md": [row("doc/modules/z.md", "src/z.s")],
              "doc/modules/w.md": [row("doc/modules/w.md", "src/z.s")]})
    assert f["collisions"] == [("src/z.s", ["doc/modules/w.md", "doc/modules/z.md"])]


def test_a_directory_row_claims_what_is_under_it(tmp_path):
    f = tree(tmp_path, {"tests/pkg/a.py": '"""a\n\nOwner: doc/a.md\n"""\n'},
             {"doc/a.md": ["| [`tests/pkg/`](../tests/pkg/) | implementation |"]})
    assert not any(f.values()), f


def test_back_link_missing_or_naming_another_doc(tmp_path):
    f = tree(tmp_path, {"dev/x.py": "# no back-link\n", "dev/y.py": "# Owner: doc/b.md\n"},
             {"doc/a.md": [row("doc/a.md", "dev/x.py"), row("doc/a.md", "dev/y.py")]})
    assert f["no_back_link"] == ["dev/x.py"]
    assert f["wrong_back_link"] == [("dev/y.py", "doc/b.md", "doc/a.md")]


def test_relative_and_linked_back_links_resolve(tmp_path):
    files = {"tests/t.py": '"""t\n\nOwner: [doc/a.md](../doc/a.md)\n"""\n',
             "rom/README.md": "# ROMs\n\n**Owner:** [doc/a.md](../doc/a.md)\n"}
    f = tree(tmp_path, files, {"doc/a.md": [row("doc/a.md", p) for p in files]})
    assert not any(f.values()), f


def test_an_exempt_row_needs_no_back_link_and_is_walked(tmp_path):
    f = tree(tmp_path, {"rom/k.bin": bytes(range(256)), "src/t.s": "; generated\n"},
             {"doc/a.md": [row("doc/a.md", "rom/k.bin", "dependency; back-link-exempt (binary)"),
                           row("doc/a.md", "src/t.s", "generated; back-link-exempt (generated)")]})
    assert not any(v for k, v in f.items() if k != "exempt"), f
    assert f["exempt"] == [("rom/k.bin", "doc/a.md", "binary"), ("src/t.s", "doc/a.md", "generated")]


def test_a_binary_without_exemption_is_reported(tmp_path):
    f = tree(tmp_path, {"rom/k.bin": bytes(range(256))},
             {"doc/a.md": [row("doc/a.md", "rom/k.bin", "dependency")]})
    assert f["binary_not_exempt"] == ["rom/k.bin"]


def test_a_linked_path_must_exist(tmp_path):
    f = tree(tmp_path, {}, {"doc/a.md": [row("doc/a.md", "dev/gone.py")]})
    assert f["missing_path"] == [("doc/a.md", "dev/gone.py")]


def test_an_unlinked_row_names_a_local_file(tmp_path):
    """`rom/kernal_cbm.bin`-style rows (no link) name files kept out
    of git: neither required to exist nor in the regime."""
    f = tree(tmp_path, {}, {"doc/a.md": ["| `rom/local.bin` | dependency (not committed) |"]})
    assert not any(f.values()), f


def test_templates_are_not_owners(tmp_path):
    f = tree(tmp_path, {"dev/x.py": "# Owner: doc/a.md\n"},
             {"doc/a.md": [row("doc/a.md", "dev/x.py")],
              "doc/templates/module.md": [row("doc/templates/module.md", "dev/x.py")]})
    assert not any(f.values()), f

