"""test_build_parity.py — test bundles use the production `-D` sets.

Owner: doc/build_system.md

Contract source: [doc/testing.md § Principle 10](../../doc/testing.md#principles)
and [doc/build_system.md § Builds and CPU sets](../../doc/build_system.md#builds-and-cpu-sets).

Every bundle variant is built with `conftest.PROD_DEFS[config]`; this
test pins that table to the Makefile's `_<cpu>_DEFS` (TAB_WIDTH, an
editor constant no bundled module reads, excluded), so a Makefile
change that the bundles do not follow fails here.
"""

import pathlib
import re

from conftest import PROD_DEFS

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Makefile variable prefix for each bundle config.
_MAKE_VAR = {"6502": "_6502_DEFS", "6510": "_6510_DEFS", "cmos": "_65c02_DEFS"}


def _makefile_defs(var):
    text = (ROOT / "Makefile").read_text()
    m = re.search(rf"^{re.escape(var)}\s*=\s*(.+)$", text, re.MULTILINE)
    assert m, f"{var} not found in Makefile"
    return [d for d in m.group(1).split() if not d.startswith("-DTAB_WIDTH")]


def test_prod_defs_cover_every_c64_build():
    assert set(PROD_DEFS) >= set(_MAKE_VAR)


def test_prod_defs_match_makefile():
    for config, var in _MAKE_VAR.items():
        assert PROD_DEFS[config] == _makefile_defs(var), config
