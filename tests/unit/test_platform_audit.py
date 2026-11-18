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


# ── the literal audit (platform_layer.md § The rule) ──

import importlib.util as _ilu

_spec = _ilu.spec_from_file_location(
    "audit_platform_literals", ROOT / "dev" / "audit_platform_literals.py")
AUDIT = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(AUDIT)


def test_no_platform_literal_outside_the_seams():
    """No ROM address, KERNAL cell, I/O register, screen base or BASIC
    address outside platform.inc and the `.ifdef PLATFORM_*` blocks."""
    assert AUDIT.counts() == {}


def _audit_source(tmp_path, name, text):
    (tmp_path / name).write_text(text)
    return [(cls, n) for n, cls, _ in AUDIT.sites(tmp_path / name)]


@pytest.mark.parametrize("line,cls", [
    ("        jsr $FFD2", "rom"),
    ("CHROUT = $FFD2", "rom"),
    ("        sta $D020", "io"),
    ("        lda #<$0400", "screen"),
    ("        sta $0291", "page23"),
    ("        .addr $0801", "basic"),
    ("        lda $C6", "zpcell"),
    ("CUR_COL = $D3", "zpcell"),
    ("        lda $01,x", "zpcell"),
])
def test_audit_flags_a_platform_literal(tmp_path, line, cls):
    assert _audit_source(tmp_path, "m.s", line + "\n") == [(cls, 1)]


@pytest.mark.parametrize("text", [
    "        lda #$C6\n",                       # an immediate value
    "        .byte $D3, $FF, $0400\n",          # data
    "        nop                     ; jsr $FFD2\n",  # a comment
    "        jsr CHROUT              ; $FFD2\n",  # a name; the comment
    "        lda $7A\n",                         # CSE's own ZP
    ".ifdef PLATFORM_C64\n        jsr $FFD2\n.endif\n",
    ".ifdef PLATFORM_M65\n  .ifdef DEBUG\n        sta $D020\n  .endif\n.endif\n",
])
def test_audit_passes_what_is_not_a_platform_literal(tmp_path, text):
    assert _audit_source(tmp_path, "m.s", text) == []


def test_audit_skips_platform_files_and_platform_inc(tmp_path):
    for name in ("platform.inc", "c64_cse.cfg.in", "m65_cse.cfg.in"):
        (tmp_path / name).write_text("X = $FFD2\n")
    (tmp_path / "m.s").write_text("X = $FFD2\n")
    assert [f.name for f in AUDIT.audited_files(tmp_path)] == ["m.s"]


def test_a_non_platform_ifdef_does_not_shelter(tmp_path):
    assert _audit_source(tmp_path, "m.s",
                         ".ifdef DEBUG\n        sta $D020\n.endif\n") == [("io", 2)]


# ── the base-page check (platform_layer.md § Base page) ──

def test_no_base_page_symbol_in_an_absolute_mode():
    """An absolute-mode access to a CSE base-page symbol, or a pointer
    to one, is written BP_ABS(sym) — on m65 CSE's zero page is the
    page CSE_BP, which a bare `$00xx` misses."""
    assert AUDIT.base_page_count() == {}


@pytest.mark.parametrize("line,flagged", [
    ("        jmp (bp_ptr)", True),
    ("        sta bp_buf,y", True),
    ("        lda bp_buf+1,y", True),
    ("        lda #<bp_buf", True),
    ("        ldx #>bp_buf", True),
    ("        .word bp_buf", True),
    ("        sta alias,y", True),            # an alias of a base-page symbol
    ("        jmp (BP_ABS(bp_ptr))", False),
    ("        sta BP_ABS(bp_buf),y", False),
    ("        lda #<BP_ABS(bp_buf)", False),
    ("        lda (bp_ptr),y", False),         # zero-page indirect: B applies
    ("        lda bp_buf,x", False),           # zero-page,x
    ("        ldx bp_buf,y", False),           # LDX has zero-page,y
    ("        lda bp_buf", False),
    ("        sta other,y", False),            # not a base-page symbol
    ("        lda #bp_len", False),            # a value, not an address
])
def test_base_page_check(tmp_path, line, flagged):
    (tmp_path / "zp.s").write_text(
        "        .exportzp bp_ptr, bp_buf\n")
    (tmp_path / "m.s").write_text("alias = bp_buf\n" + line + "\n")
    names = AUDIT.base_page_symbols(tmp_path)
    assert bool(AUDIT.base_page_sites(tmp_path / "m.s", names)) == flagged
