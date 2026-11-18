"""test_size_budget.py — the C64 builds never grow (TODO § M65, gate 1);
the m65 build is held to its budget too.

Owner: doc/build_system.md

Contract source: [doc/TODO.md § M65](../../doc/TODO.md#m65--the-45gs02-assembler-and-disassembler-r7-slice-1),
*Hard constraint* and *Acceptance gates*: no change made for the m65
target may make any C64 build bigger.

BUDGET is each C64 build's unpacked release PRG size.  It is a ratchet:
a commit that shrinks a build lowers its budget to the new size, so the
saving cannot silently erode.  A deliberate C64 feature that grows a
build raises the budget in its own commit, with its reason.
(Baseline before the m65 work, 910d96d: 20 790 / 21 232 / 21 688 B.)
The m65 build joined BUDGET with its first link (P0 step (5),
[build_system.md § Size gate](../../doc/build_system.md#size-gate)).
"""

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# build → (release PRG, byte budget)
BUDGET = {
    "c64-6502":  (ROOT / "build/release/6502/cse-6502.prg", 20_886),
    "c64-6510":  (ROOT / "build/release/6510/cse.prg",      21_229),
    "c64-65c02": (ROOT / "build/release/cmos/cse-cmos.prg", 21_809),
    "m65-6502":  (ROOT / "build/release/m65/cse-m65.prg",   21_064),
}


@pytest.fixture(scope="module")
def release_built():
    """Bring the release builds of both platforms up to date (make is
    incremental)."""
    for platform in ("c64", "m65"):
        subprocess.run(["make", "release", f"PLATFORM={platform}"],
                       cwd=ROOT, check=True, capture_output=True)


@pytest.mark.parametrize("build", list(BUDGET))
def test_release_prg_within_budget(release_built, build):
    prg, budget = BUDGET[build]
    size = prg.stat().st_size
    assert size <= budget, f"{build}: {size} B > budget {budget} B (+{size - budget})"
