"""test_platform_audit.py — the platform layer's gates.

Owner: doc/platform_layer.md

Contract source: [platform_layer.md § Gates](../../doc/platform_layer.md#gates).

Tier U, static.  The C64 release PRGs are the recorded ones: moving the
C64 build onto the platform layer, and every m65 change, leaves them
byte-identical.  The fixture is re-recorded only by a commit that
deliberately changes what a C64 build contains, and that commit says
why (the regime of the golden files).
"""

import hashlib
import json
import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
HASHES = json.loads((ROOT / "tests" / "fixtures" / "golden"
                     / "c64_prg_sha256.json").read_text())["prgs"]


@pytest.fixture(scope="module")
def release_built():
    """Bring the release builds up to date (make is incremental)."""
    subprocess.run(["make", "release"], cwd=ROOT, check=True,
                   capture_output=True)


@pytest.mark.parametrize("prg", sorted(HASHES))
def test_c64_prgs_are_the_recorded_ones(release_built, prg):
    data = (ROOT / prg).read_bytes()
    assert hashlib.sha256(data).hexdigest() == HASHES[prg], (
        f"{prg} differs from the recorded build: a C64 change must be "
        "deliberate and re-record tests/fixtures/golden/c64_prg_sha256.json")
