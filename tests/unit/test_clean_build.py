"""test_clean_build.py — a fresh checkout builds with one `make`.

Owner: doc/build_system.md

Contract source: [build_system.md § Main build pipeline](../../doc/build_system.md#main-build-pipeline)
(Clean builds): on a tree without `build/`, a single `make release`
succeeds — no second run needed.  Builds a detached `git worktree` of
`HEAD` with this tree's Makefile copied in, ~1 minute.
"""

import pathlib
import shutil
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_fresh_worktree_builds_in_one_make(tmp_path):
    wt = tmp_path / "wt"
    subprocess.run(["git", "worktree", "add", "--detach", str(wt), "HEAD"],
                   cwd=ROOT, check=True, capture_output=True)
    try:
        # The Makefile under test is this tree's, committed or not.
        shutil.copy2(ROOT / "Makefile", wt / "Makefile")
        # PYTHON: the worktree's path would give pipenv a new virtualenv.
        r = subprocess.run(["make", "release", f"PYTHON={sys.executable}"],
                           cwd=wt, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]
        assert "No rule to make target" not in r.stderr
        for prg in ("6510/cse.prg", "6502/cse-6502.prg", "cmos/cse-cmos.prg"):
            assert (wt / "build/release" / prg).is_file()
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(wt)],
                       cwd=ROOT, capture_output=True)
