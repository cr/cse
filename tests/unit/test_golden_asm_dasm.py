"""test_golden_asm_dasm.py — Phase A gates 2 and 3 (TODO § M65).

Owner: doc/build_system.md

Contract source: [doc/TODO.md § M65](../../doc/TODO.md#m65--the-45gs02-assembler-and-disassembler-r7-slice-1),
*Acceptance gates*; [doc/testing.md § Principle 7](../../doc/testing.md#principles).

The golden files (tests/fixtures/golden/asm_dasm_<cpu set>.json) are
recorded by dev/capture_golden.py; each names the commit it was recorded
from (`source_rev`): the 6502 set's from before the generated table
formats, the 6510 set's, the CMOS mode's (65c02) and the m65 set's
(45gs02, its prefixed cases included) re-recorded at P4b.  For every
CPU set this test re-runs the same exhaustive sweeps on the current
source and asserts:

  * **Behaviour (gate 3)** — every case's output (dasm text + length;
    asm bytes or error code) equals the golden one, except the cases
    listed in BASELINE_DEFECTS: a golden output that disagrees with the
    instruction-set oracle is a defect of the old code, not a contract.
  * **Speed (gate 2)** — total cycles (py65's; on M65Emu, instructions)
    do not exceed the golden total, and no single case exceeds its
    golden cycles by more than 10 %.

Size (gate 1) is tests/integration/test_size_budget.py.  When the
golden files may be re-recorded: dev/capture_golden.py's docstring.
"""

import json

import pytest

import asm_dasm_runner as R
from conftest import AsmCoreSymbols, dasm_bundle

# Golden cases whose recorded output is a baseline defect (each entry:
# key → reason).  Filled when the refactor exposes one; every entry is
# also filed under TODO.md § Bugs.
BASELINE_DEFECTS = {
    "asm": {},
    "dasm": {},
}

SPEED_TOLERANCE = 1.10


def _golden(config):
    path = R.GOLDEN_DIR / f"asm_dasm_{config}.json"
    if not path.exists():
        pytest.skip(f"no golden file {path.name} — run dev/capture_golden.py "
                    f"on a known-good tree first")
    return json.loads(path.read_text())


def _current(kind, config):
    if kind == "dasm":
        return R.dasm_sweep(dasm_bundle(config), config)
    return R.asm_sweep(AsmCoreSymbols(config=config), config)


_CACHE = {}

def _pair(kind, config):
    if (kind, config) not in _CACHE:
        _CACHE[(kind, config)] = (_golden(config)[kind], _current(kind, config))
    return _CACHE[(kind, config)]


_PARAMS = [pytest.param(k, c, id=f"{k}-{c}")
           for c in R.CONFIG_CPUS for k in ("dasm", "asm")]


@pytest.mark.parametrize("kind,config", _PARAMS)
def test_behaviour_matches_golden(kind, config):
    gold, cur = _pair(kind, config)
    assert set(cur) == set(gold), "sweep case set changed"
    bad = []
    for key, g in gold.items():
        if key in BASELINE_DEFECTS[kind]:
            continue
        if cur[key][:-1] != g[:-1]:
            bad.append(f"{key!r}: golden {g[:-1]} now {cur[key][:-1]}")
    assert not bad, f"{len(bad)} {kind} case(s) differ:\n" + "\n".join(bad[:40])


@pytest.mark.parametrize("kind,config", _PARAMS)
def test_speed_within_golden(kind, config):
    gold, cur = _pair(kind, config)
    total_g = sum(g[-1] for g in gold.values())
    total_c = sum(cur[k][-1] for k in gold)
    slow = [f"{k!r}: {cur[k][-1]} > {g[-1]} × {SPEED_TOLERANCE}"
            for k, g in gold.items()
            if cur[k][-1] > g[-1] * SPEED_TOLERANCE]
    assert total_c <= total_g, f"{kind}/{config}: {total_c} cycles > golden {total_g}"
    assert not slow, f"{len(slow)} case(s) slower than tolerance:\n" + "\n".join(slow[:40])
