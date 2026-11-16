#!/usr/bin/env python3
"""capture_golden.py — record the asm_line / dasm_insn golden files.

Owner: doc/build_system.md

Runs the exhaustive sweeps of tests/asm_dasm_runner.py against the
current source, once per C64 bundle config, and writes
tests/fixtures/golden/asm_dasm_<config>.json: per case the output and
the py65 cycle count.  Run it on a known-good tree *before* a refactor
of the assembler or disassembler; tests/unit/test_golden_asm_dasm.py
then holds the refactored code to the recorded output and cycles.

    python dev/capture_golden.py            # all configs
    python dev/capture_golden.py cmos       # one config
"""
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tests"), str(ROOT / "dev")]

import conftest                                   # noqa: E402
import asm_dasm_runner as R                       # noqa: E402


def capture(config):
    dsyms = conftest.dasm_bundle(config)
    asyms = conftest.AsmCoreSymbols(config=config)
    rev = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                         capture_output=True, text=True).stdout.strip()
    data = {
        "config": config,
        "source_rev": rev,
        "dasm": R.dasm_sweep(dsyms, config),
        "asm": R.asm_sweep(asyms, config),
    }
    R.GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    path = R.GOLDEN_DIR / f"asm_dasm_{config}.json"
    path.write_text(json.dumps(data, indent=0, sort_keys=True) + "\n")
    return path, len(data["dasm"]), len(data["asm"])


if __name__ == "__main__":
    configs = sys.argv[1:] or list(R.CONFIG_CPUS)
    for c in configs:
        path, nd, na = capture(c)
        print(f"wrote {path.relative_to(ROOT)}: {nd} dasm + {na} asm cases")
