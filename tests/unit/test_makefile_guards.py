"""test_makefile_guards.py — the Makefile builds what it can, refuses the rest.

Owner: doc/build_system.md

Contract source: [build_system.md § Builds and CPU sets](../../doc/build_system.md#builds-and-cpu-sets)
and [§ The m65 builds](../../doc/build_system.md#the-m65-builds) (T4 of
TODO § M65 slice 2, P0): `make release` / `make debug` with
`PLATFORM=m65` build the m65-6502 PRG into build/<profile>/m65/ through
src/m65_cse.cfg; `disk`, `run` and `size` with `PLATFORM=m65` are
refused until P3, and an unknown platform is refused for every PRG
target — neither silently builds the C64 PRGs.  Each region of the m65
config is bounded as stated, so an overflow fails the link.
[build_system.md § Introspection builds](../../doc/build_system.md#introspection-builds-introspect1):
only `INTROSPECT=1` passes `-DINTROSPECT`.
"""

import pathlib
import re
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
M65_CFG = ROOT / "src" / "m65_cse.cfg"


def _make_n(*args):
    return subprocess.run(["make", "-n", "-B", "--no-print-directory", *args],
                          cwd=ROOT, capture_output=True, text=True)


# ── PLATFORM=m65 ──────────────────────────────────────────────────

@pytest.mark.parametrize("target, profile", [("release", "release"),
                                             ("debug", "debug"),
                                             ("all", "release"),
                                             (None, "release")])
def test_m65_prg_targets_build_the_m65_6502_prg(target, profile):
    r = _make_n(*([target] if target else []), "PLATFORM=m65")
    assert r.returncode == 0, r.stderr
    ca65 = [ln for ln in r.stdout.splitlines() if ln.startswith("ca65 ")]
    assert ca65 and all("-DPLATFORM_M65" in ln and "-DCPU_6502" in ln
                        and "-DUSE_MN6" in ln and "-DCPU_CEIL=0" in ln
                        and "-DPLATFORM_C64" not in ln for ln in ca65)
    assert all((" -g " in ln) == (profile == "debug") for ln in ca65)
    ld65 = [ln for ln in r.stdout.splitlines() if ln.startswith("ld65 ")]
    assert len(ld65) == 1, "one link, no trial pass"
    assert f"-C {M65_CFG}" in ld65[0]
    assert f"build/{profile}/m65/cse-m65.prg" in ld65[0]
    for tool in ("exomizer", "c1541", "compute_layout"):
        assert tool not in r.stdout


def test_m65_ignores_cpu():
    r = _make_n("release", "PLATFORM=m65", "CPU=65c02")
    assert r.returncode == 0, r.stderr
    assert "-DCPU_65C02" not in r.stdout and "-DCPU_6502" in r.stdout


@pytest.mark.parametrize("target", ["disk", "run", "size"])
def test_m65_targets_without_a_d81_are_refused(target):
    r = _make_n(target, "PLATFORM=m65")
    assert r.returncode != 0
    assert "PLATFORM=m65" in r.stderr
    assert "ca65" not in r.stdout


@pytest.mark.parametrize("target", ["release", "debug", "all", "disk", "run", "size"])
def test_unknown_platform_prg_targets_are_refused(target):
    r = _make_n(target, "PLATFORM=c128")
    assert r.returncode != 0
    assert "PLATFORM=c128" in r.stderr
    assert "ca65" not in r.stdout


@pytest.mark.parametrize("platform", ["m65", "c128"])
@pytest.mark.parametrize("target", ["help", "themes", "clean"])
def test_non_prg_targets_work_on_every_platform(target, platform):
    assert _make_n(target, f"PLATFORM={platform}").returncode == 0


def test_c64_platform_builds():
    r = _make_n("debug", "PLATFORM=c64")
    assert r.returncode == 0
    assert "-DPLATFORM_C64" in r.stdout and "-DPLATFORM_M65" not in r.stdout


# ── src/m65_cse.cfg: each region bounded ──────────────────────────

# memory area → (start, size): build_system.md § The m65 builds
M65_AREAS = {
    "ZP":      (0x0000, 0x00AD),        # CSE's base page, below BP_PENDING ($AD, P2)
    "STUB":    (0x1FB0, 0x0050),        # 0.1FB0-0.1FFF
    "CODEWIN": (0x2000, 0x6000),        # 3.2000-3.7FFF
    "DATAWIN": (0x8000, 0x2100),        # 3.8000, below SYM_TABLE
}


def _areas(text):
    out = {}
    for m in re.finditer(r"^\s*(\w+):[^;]*?start\s*=\s*\$([0-9A-Fa-f]+)\s*,"
                         r"\s*size\s*=\s*\$([0-9A-Fa-f]+)\s*;", text, re.M):
        out[m.group(1)] = (int(m.group(2), 16), int(m.group(3), 16))
    return out


def test_m65_config_bounds_each_region():
    areas = _areas(M65_CFG.read_text())
    assert {k: areas.get(k) for k in M65_AREAS} == M65_AREAS


@pytest.fixture(scope="module")
def m65_objects():
    """The m65 release objects, in the Makefile's link order."""
    subprocess.run(["make", "release", "PLATFORM=m65"], cwd=ROOT,
                   check=True, capture_output=True)
    ld65 = next(ln for ln in _make_n("release", "PLATFORM=m65").stdout.splitlines()
                if ln.startswith("ld65 "))
    return [w for w in ld65.split() if w.endswith(".o")]


@pytest.mark.parametrize("area", list(M65_AREAS))
def test_an_m65_region_overflow_fails_the_link(m65_objects, tmp_path, area):
    """The config shrunk by one byte below what that region holds."""
    ok = subprocess.run(["ld65", "-C", str(M65_CFG), "-o", str(tmp_path / "ok.prg"),
                         "-m", str(tmp_path / "ok.map"), *m65_objects],
                        capture_output=True, text=True)
    assert ok.returncode == 0, ok.stderr
    used = _used(tmp_path / "ok.map", area)
    start, _ = M65_AREAS[area]
    cfg = tmp_path / "small.cfg"
    cfg.write_text(re.sub(rf"(^\s*{area}:[^;]*?size\s*=\s*)\$[0-9A-Fa-f]+",
                          rf"\g<1>${used - 1:04X}", M65_CFG.read_text(), flags=re.M))
    r = subprocess.run(["ld65", "-C", str(cfg), "-o", str(tmp_path / "x.prg"),
                        *m65_objects], capture_output=True, text=True)
    assert r.returncode != 0 and "overflow" in r.stderr, r.stderr


def _used(map_path, area):
    """The bytes the map's segments occupy in `area` (from its start)."""
    run_segs = {"ZP": ["ZEROPAGE"], "STUB": ["STUB"],
                "CODEWIN": ["CODE", "RODATA"], "DATAWIN": ["KDATA", "BSS"]}[area]
    text = map_path.read_text()
    ends = [int(m.group(1), 16) for seg in run_segs
            for m in [re.search(rf"^{seg}\s+[0-9A-F]+\s+([0-9A-F]+)\s", text, re.M)]]
    return max(ends) + 1 - M65_AREAS[area][0]


# ── INTROSPECT ────────────────────────────────────────────────────

@pytest.mark.parametrize("value, on", [("1", True), ("0", False), ("", False),
                                       ("yes", False)])
def test_introspect_only_when_1(value, on):
    r = _make_n("-B", "debug", f"INTROSPECT={value}")
    assert r.returncode == 0, r.stderr
    assert ("-DINTROSPECT" in r.stdout) == on
