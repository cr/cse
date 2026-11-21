"""test_release_bundle.py — the release bundle as `make bundle` builds it.

Owner: doc/build_system.md

Contract source: [build_system.md § The release bundle](../../doc/build_system.md#the-release-bundle):
`make bundle` leaves exactly the seven release files in build/bundle/,
named `cse-<platform>[-<cpu>[-exo]].prg` (a platform's default CPU
without its part) and `cse-<platform>.d64` / `.d81`; each PRG is its
release build byte for byte; the D64 holds the c64's exomizer builds,
the default one (6510) as `cse` and the 6502's as `cse-6502`, the D81
the m65 PRG as `cse`; each disk is named `cse <VERSION>`, id `01`.
c1541 (VICE's disk tool) writes and reads the images; without it the
module is skipped, saying so.
"""

import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
OUT = ROOT / "build" / "bundle"
REL = ROOT / "build" / "release"
C1541 = shutil.which("c1541")

pytestmark = pytest.mark.skipif(C1541 is None, reason="no c1541 on PATH (VICE's disk "
                                "tool): the bundle's disk images cannot be written")

PRGS = {
    "cse-c64.prg":          REL / "6510" / "cse.prg",
    "cse-c64-exo.prg":      REL / "6510" / "cse-exo.prg",
    "cse-c64-6502.prg":     REL / "6502" / "cse-6502.prg",
    "cse-c64-6502-exo.prg": REL / "6502" / "cse-6502-exo.prg",
    "cse-m65.prg":          REL / "m65" / "cse-m65.prg",
}
DISKS = {
    "cse-c64.d64": {"cse": REL / "6510" / "cse-exo.prg",
                    "cse-6502": REL / "6502" / "cse-6502-exo.prg"},
    "cse-m65.d81": {"cse": REL / "m65" / "cse-m65.prg"},
}


def version():
    return re.search(r"^VERSION\s*\?=\s*(\S+)", (ROOT / "Makefile").read_text(), re.M).group(1)


@pytest.fixture(scope="module")
def bundle():
    r = subprocess.run(["make", "bundle"], cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return OUT


def listing(image):
    """(disk name, id, [file names]) as `c1541 -list` shows them."""
    out = subprocess.run([C1541, "-attach", str(image), "-list"],
                         capture_output=True, text=True).stdout
    head = re.search(r'^0 "(.*?)\s*" (\S\S)', out, re.M)
    return head.group(1), head.group(2), re.findall(r'^\d+\s+"(.*?)"\s+prg', out, re.M)


def test_the_bundle_is_the_seven_release_files(bundle):
    assert sorted(p.name for p in bundle.iterdir()) == sorted([*PRGS, *DISKS])


@pytest.mark.parametrize("name", list(PRGS))
def test_each_prg_is_its_release_build(bundle, name):
    assert (bundle / name).read_bytes() == PRGS[name].read_bytes()


@pytest.mark.parametrize("image", list(DISKS))
def test_each_disk_holds_its_platforms_builds_without_the_platform(bundle, image, tmp_path):
    name, disk_id, files = listing(bundle / image)
    assert (name, disk_id) == (f"cse {version()}", "01")
    assert files == list(DISKS[image])
    for file, build in DISKS[image].items():
        out = tmp_path / f"{file}.prg"
        subprocess.run([C1541, "-attach", str(bundle / image), "-read", file, str(out)],
                       check=True, capture_output=True)
        assert out.read_bytes() == build.read_bytes(), file
