#!/usr/bin/env python3
"""capture_golden.py — record the asm_line / dasm_insn golden files.

Owner: doc/build_system.md

Runs the exhaustive sweeps of tests/asm_dasm_runner.py against the
current source, once per CPU set (the m65 set on M65Emu), and writes
tests/fixtures/golden/asm_dasm_<cpu set>.json: per case the output and
the cycle count (py65's; on M65Emu, instructions).  tests/unit/test_golden_asm_dasm.py holds later
code to the recorded output and cycles.

When to re-record (doc/build_system.md § Golden files): only in a
commit that deliberately changes what a build assembles or lists,
or what it costs — never to make a refactor pass.  That commit states
the reason and the measured cycle change.  `source_rev` is the commit
the files were recorded from, with `-dirty` when the tree had
uncommitted source changes.

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
    if subprocess.run(["git", "status", "--porcelain", "--", "src", "dev"], cwd=ROOT,
                      capture_output=True, text=True).stdout.strip():
        rev += "-dirty"
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
