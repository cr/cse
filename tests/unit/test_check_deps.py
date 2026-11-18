"""test_check_deps.py — the layer checker (dev/check_deps.py) and the
reverse Depends-on audit (dev/audit_doc_depends_on.py, check (c)).

Owner: doc/build_system.md

Contract source: [architecture.md § Dependency Rules](../../doc/architecture.md#dependency-rules)
(rule 1: imports go to the same or a lower layer, layers read from
the Modules table) and [README.md § CDD Maintenance](../../doc/README.md)
(every imported-from module is named in the importer's Depends-on).

Tier U, on small trees in tmp_path, plus one run over the real tree.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import check_deps as C                              # noqa: E402
import audit_doc_depends_on as A                    # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]

ARCH = """# Architecture

## Modules

| Module | Layer | Purpose | Doc |
|--------|-------|---------|-----|
| top.s | 3 | top | x |
| mid.s / alt.s | 2 | mid | x |
| low.s | 1 | low | x |

Generated files (do not edit):

| File | Generator | Owning doc |
|------|-----------|------------|
| gen_tables.s | [`dev/gen.py`](../dev/gen.py) | x |

## Dependency Graph
| low.s | 9 | not the Modules table | x |
"""


def tree(tmp_path, srcs, docs=None):
    (tmp_path / "src").mkdir()
    (tmp_path / "doc" / "modules").mkdir(parents=True)
    (tmp_path / "doc" / "architecture.md").write_text(ARCH)
    for name, text in srcs.items():
        (tmp_path / "src" / f"{name}.s").write_text(text)
    for name, text in (docs or {}).items():
        (tmp_path / "doc" / "modules" / f"{name}.md").write_text(text)
    return tmp_path


def run(tmp_path):
    return C.check(tmp_path / "src", tmp_path / "doc" / "architecture.md")


# ── check_deps ───────────────────────────────────────────────────────

def test_layers_parsed_from_both_tables():
    layers = C.parse_layers(ARCH)
    assert layers == {"top": 3, "mid": 2, "alt": 2, "low": 1, "gen_tables": 0}


def test_downward_and_same_layer_imports_are_clean(tmp_path):
    tree(tmp_path, {
        "top": "  .import m1, l1\n",
        "mid": "  .export m1\n  .import a1 ; same layer\n",
        "alt": "  .export a1\n  .importzp g1\n",
        "low": "  .export l1\n",
        "gen_tables": "  .exportzp g1\n",
    })
    assert run(tmp_path) == []


def test_upward_import_is_refused(tmp_path):
    tree(tmp_path, {
        "top": "  .export t1, t2\n",
        "low": "  .import t1, t2, unknown_linker_sym\n",
    })
    assert run(tmp_path) == ["low.s (L1) imports from top.s (L3): t1, t2"]


def test_comment_and_absolute_export_forms(tmp_path):
    tree(tmp_path, {
        "top": "  .export k : absolute = 3 ; .import nothing\n",
        "low": "  .import k\n  ; .import gone\n",
    })
    assert run(tmp_path) == ["low.s (L1) imports from top.s (L3): k"]


def test_module_without_a_layer_is_a_finding(tmp_path):
    tree(tmp_path, {"stray": "  .import l1\n", "low": "  .export l1\n"})
    assert run(tmp_path) == ["stray.s: no layer in architecture.md § Modules"]


def test_real_tree_is_clean():
    assert C.check(ROOT / "src", ROOT / "doc" / "architecture.md") == []


# ── audit_doc_depends_on (c): import → doc ───────────────────────────

def test_unlisted_import_module_is_reported(tmp_path):
    tree(tmp_path,
         {"top": "  .import m1, l1\n", "mid": "  .export m1\n",
          "low": "  .export l1\n"},
         {"top": "# top\n\n**Depends on:** mid (m1, low)\n\n## Next\n"})
    found = A.reverse_findings(tmp_path / "doc" / "modules", tmp_path / "src")
    assert [(m, d, s) for _, m, d, s in found] == [("top", "low", ["l1"])]


def test_listed_modules_and_or_forms_are_clean(tmp_path):
    tree(tmp_path,
         {"top": "  .import m1, a1\n", "mid": "  .export m1\n",
          "alt": "  .export a1\n"},
         {"top": "**Depends on:** `mid` or alt (GENERATED)\n"})
    assert A.reverse_findings(tmp_path / "doc" / "modules", tmp_path / "src") == []


def test_missing_depends_block_is_reported(tmp_path):
    tree(tmp_path, {"top": "  .import l1\n", "low": "  .export l1\n"},
         {"top": "# top\n\nNo dependency line.\n"})
    found = A.reverse_findings(tmp_path / "doc" / "modules", tmp_path / "src")
    assert [(m, d) for _, m, d, _ in found] == [("top", None)]
