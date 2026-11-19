"""test_build_freshness.py — no test runs against a stale binary.

Owner: doc/build_system.md

Contract source: [build_system.md § Main build pipeline](../../doc/build_system.md#main-build-pipeline)
(incremental builds) and [§ How it works](../../doc/build_system.md#how-it-works):
the PRG fixtures run `make` once per session whatever is on disk; an
object's prerequisites include every file it `.include`s; a conftest
bundle rebuilds when a shared include file changed.
"""

import os
import pathlib
import subprocess

import conftest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def test_prg_fixture_runs_make_although_the_prg_exists(monkeypatch):
    """An existing PRG may be older than its sources: the fixture
    always asks make (which is incremental) to bring it up to date."""
    calls = []
    monkeypatch.setattr(conftest.subprocess, "run",
                        lambda cmd, **kw: calls.append(cmd))
    monkeypatch.setattr(conftest, "_MADE", set(), raising=False)
    conftest._ensure_debug_built()
    conftest._ensure_debug_built()
    conftest._make("debug", "m65")                 # another platform: its own run
    assert calls == [["make", "debug", "PLATFORM=c64"],
                     ["make", "debug", "PLATFORM=m65"]]


def test_makefile_rebuilds_the_includers_of_an_inc_file():
    """`make -W src/macros.inc` (what if macros.inc were new) rebuilds
    the objects that include it, and only those."""
    subprocess.run(["make", "debug"], cwd=ROOT, check=True, capture_output=True)
    out = subprocess.run(
        ["make", "-n", "-W", str(SRC / "macros.inc"), "--no-print-directory",
         "_one", "CPU=6510", "_PROFILE=debug"],
        cwd=ROOT, check=True, capture_output=True, text=True).stdout
    rebuilt = {pathlib.Path(w).stem for line in out.splitlines()
               if line.startswith("ca65") for w in line.split() if w.endswith(".o")}
    assert {"repl", "disk", "log", "main", "asm_src"} <= rebuilt
    assert "zp" not in rebuilt and "editor" not in rebuilt


def test_bundle_is_stale_when_an_inc_file_is_newer(tmp_path):
    """A bundle whose own sources and config are older than the binary
    still rebuilds when a shared `src/*.inc` changed after it."""
    cfg = tmp_path / "t.cfg"
    cfg.write_text("")
    b = conftest.Bundle("freshness_probe", [], [], tag="fp", cfg=cfg)
    b.bin, b.lbl = tmp_path / "x.bin", tmp_path / "x.lbl"
    for f in (b.bin, b.lbl, b.bin.with_suffix(".flags")):
        f.write_text("")
    os.utime(cfg, (0, 0))
    os.utime(b.bin, (1, 1))       # older than every real src/*.inc
    assert b._stale()
