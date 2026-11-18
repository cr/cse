"""test_size_budget.py — the C64 builds never grow (TODO § M65, gate 1).

Owner: doc/build_system.md

Contract source: [doc/TODO.md § M65](../../doc/TODO.md#m65--the-45gs02-assembler-and-disassembler-r7-slice-1),
*Hard constraint* and *Acceptance gates*: no change made for the m65
target may make any C64 build bigger.

BUDGET is each C64 build's unpacked release PRG size.  It is a ratchet:
a commit that shrinks a build lowers its budget to the new size, so the
saving cannot silently erode.  A deliberate C64 feature that grows a
build raises the budget in its own commit, with its reason.
(Baseline before the m65 work, 910d96d: 20 790 / 21 232 / 21 688 B.)
"""

import pathlib
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

# CPU set → (release PRG, byte budget)
BUDGET = {
    "6502":  (ROOT / "build/release/6502/cse-6502.prg", 20_255),
    "6510":  (ROOT / "build/release/6510/cse.prg",      20_598),
    "65c02": (ROOT / "build/release/cmos/cse-cmos.prg", 21_179),
}


@pytest.fixture(scope="module")
def release_built():
    """Bring the release builds up to date (make is incremental)."""
    subprocess.run(["make", "release"], cwd=ROOT, check=True,
                   capture_output=True)


@pytest.mark.parametrize("cpu_set", list(BUDGET))
def test_c64_release_prg_within_budget(release_built, cpu_set):
    prg, budget = BUDGET[cpu_set]
    size = prg.stat().st_size
    assert size <= budget, f"c64-{cpu_set}: {size} B > budget {budget} B (+{size - budget})"
