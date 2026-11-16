"""test_size_budget.py — the C64 builds never grow (Phase A gate 1).

Owner: doc/build_system.md

Contract source: [doc/TODO.md § M65](../../doc/TODO.md#m65--the-45gs02-assembler-and-disassembler-r7-slice-1),
*Hard constraint* and *Acceptance gates*: no change made for the m65
target may make any C64 build bigger.  The budget is the unpacked
release PRG size of each C64 build at the baseline (910d96d,
2026-11-16).  A deliberate C64 feature that grows a build lowers no
bar silently: it edits BUDGET here with its reason, in its own commit.
"""

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# build → (release PRG path, byte budget)
BUDGET = {
    "c64-6502":  (ROOT / "build/release/6502/cse-6502.prg", 20_790),
    "c64-6510":  (ROOT / "build/release/6510/cse.prg",      21_232),
    "c64-65c02": (ROOT / "build/release/cmos/cse-cmos.prg", 21_688),
}


@pytest.fixture(scope="module")
def release_built():
    """Bring the release builds up to date (make is incremental)."""
    subprocess.run(["make", "release"], cwd=ROOT, check=True,
                   capture_output=True)


@pytest.mark.parametrize("build", list(BUDGET))
def test_c64_release_prg_within_budget(release_built, build):
    prg, budget = BUDGET[build]
    size = prg.stat().st_size
    assert size <= budget, f"{build}: {size} B > budget {budget} B (+{size - budget})"
