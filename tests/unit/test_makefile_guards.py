"""test_makefile_guards.py — the Makefile refuses what it cannot build.

Owner: doc/build_system.md

Contract source: [build_system.md § Builds and CPU sets](../../doc/build_system.md#builds-and-cpu-sets):
`PLATFORM=m65` with a PRG target is refused until R7 slice 2 (the
platform layer) lands — it must not silently build the C64 PRGs.
[build_system.md § Introspection builds](../../doc/build_system.md#introspection-builds-introspect1):
only `INTROSPECT=1` passes `-DINTROSPECT`.
"""

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _make_n(*args):
    return subprocess.run(["make", "-n", "--no-print-directory", *args],
                          cwd=ROOT, capture_output=True, text=True)


@pytest.mark.parametrize("target", ["release", "debug", "all", "disk", "run", "size"])
def test_m65_prg_targets_are_refused(target):
    r = _make_n(target, "PLATFORM=m65")
    assert r.returncode != 0
    assert "PLATFORM=m65" in r.stderr
    assert "ca65" not in r.stdout


def test_default_target_is_refused_on_m65():
    r = _make_n("PLATFORM=m65")
    assert r.returncode != 0 and "PLATFORM=m65" in r.stderr


@pytest.mark.parametrize("target", ["help", "themes", "clean"])
def test_m65_non_prg_targets_still_work(target):
    assert _make_n(target, "PLATFORM=m65").returncode == 0


def test_c64_platform_builds():
    assert _make_n("debug", "PLATFORM=c64").returncode == 0


@pytest.mark.parametrize("value, on", [("1", True), ("0", False), ("", False),
                                       ("yes", False)])
def test_introspect_only_when_1(value, on):
    r = _make_n("-B", "debug", f"INTROSPECT={value}")
    assert r.returncode == 0, r.stderr
    assert ("-DINTROSPECT" in r.stdout) == on
