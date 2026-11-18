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

# The Makefile names each C64 build's -D set `_<cpu set>_DEFS`.
_MAKE_VAR = {c: f"_{c}_DEFS" for c in ("6502", "6510", "65c02")}


def _makefile_defs(var):
    text = (ROOT / "Makefile").read_text()
    m = re.search(rf"^{re.escape(var)}\s*=\s*(.+)$", text, re.MULTILINE)
    assert m, f"{var} not found in Makefile"
    return [d for d in m.group(1).split() if not d.startswith("-DTAB_WIDTH")]


def test_prod_defs_cover_exactly_the_c64_builds():
    assert set(PROD_DEFS) == set(_MAKE_VAR)


def test_prod_defs_match_makefile():
    for config, var in _MAKE_VAR.items():
        assert PROD_DEFS[config] == _makefile_defs(var), config


def test_platform_defs_match_makefile():
    """Every bundle is assembled with the platform define the Makefile
    gives the same platform's builds."""
    from conftest import PLATFORM_DEFS
    text = (ROOT / "Makefile").read_text()
    for platform, defs in PLATFORM_DEFS.items():
        m = re.search(rf"^_{platform}_PDEFS\s*=\s*(.+)$", text, re.MULTILINE)
        assert m, f"_{platform}_PDEFS not found in Makefile"
        assert defs == m.group(1).split(), platform
