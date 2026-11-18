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


# ── the stack-top check (platform_layer.md § Stack) ──

def test_no_literal_stack_top():
    """A stack reset and `reg_sp`'s seeds use STACK_TOP — `$F1` on m65,
    where a literal `$FF` would hand the program the wrong SP."""
    assert AUDIT.stack_top_count() == {}


@pytest.mark.parametrize("text,flagged", [
    ("        ldx #$FF\n        txs\n", True),
    ("        ldx #$ff        ; top\n        txs\n", True),
    ("        lda #$FF\n        sta reg_sp\n", True),
    ("        ldx #$FF\n\n; c\n        stx reg_sp\n", True),
    ("        ldx #STACK_TOP\n        txs\n", False),
    ("        lda #STACK_TOP\n        sta reg_sp\n", False),
    ("        ldx reg_sp\n        txs\n", False),
    ("        ldx #$FF\n        stx dbg_bp_hit\n", False),
    ("        ldx #$FF\n        inx\n        txs\n", False),
])
def test_stack_top_check(tmp_path, text, flagged):
    (tmp_path / "m.s").write_text(text)
    assert bool(AUDIT.stack_top_sites(tmp_path / "m.s")) == flagged


# ── the raw-byte audit (platform_layer.md § Raw-byte instructions) ──

def test_no_raw_45gs02_opcode_outside_m45_ops():
    """Every `.byte` in an opcode position starts with a literal 6502
    opcode; 45GS02-only instructions come from src/m45_ops.inc."""
    assert AUDIT.raw_byte_count() == {}


@pytest.mark.parametrize("text,flagged", [
    ("        lda #1\n        .byte $2C       ; BIT skip\n", False),
    ("        lda #1\n        .byte $5C\n", True),          # MAP
    ("        lda #1\n@x:     .byte $5C\n", True),          # a label: falls in
    ("        lda #1\n@x:\n; c\n        .byte $5C\n", True),
    ("        bne @x\n        .byte $D2\n", True),          # a branch falls through
    ("        lda #1\n        .byte <tbl\n", True),         # not a literal
    ("        lda #1\n.ifdef A\n        .byte $5C\n.endif\n", True),
    ("        brk\n        .byte $42       ; signature\n", False),
    ("        rts\ntbl:    .byte $5C, $D2\n", False),       # data
    ("        jmp @x\n        .byte $5C\n", False),
    ("        rti\n        .byte $5C\n", False),
    ("        rts\ntbl:    .byte 1\n        .byte $5C\n", False),
    ("        .byte $5C\n", False),                         # no statement before
    ("        lda #1\n.segment \"RODATA\"\n        .byte $5C\n", False),
    (".macro M\n        lda #1\n        .byte $5C\n.endmacro\n", True),
    (".macro P n\n        brk\n        .byte n\n.endmacro\n", False),
])
def test_raw_byte_audit(tmp_path, text, flagged):
    (tmp_path / "m.s").write_text(text)
    assert bool(AUDIT.raw_byte_sites(tmp_path / "m.s")) == flagged


def test_raw_byte_audit_skips_m45_ops(tmp_path):
    for name in ("m45_ops.inc", "m.inc", "m.s"):
        (tmp_path / name).write_text("        lda #1\n        .byte $5C\n")
    assert sorted(AUDIT.raw_byte_count(tmp_path)) == ["m.inc", "m.s"]


# ── the pending-body count (platform_layer.md § Pending bodies) ──

# The PLAT_PENDING sites per milestone, recorded; a commit that writes
# an m65 body lowers its number here.  Every number is 0 when P3 closes.
PENDING_RECORDED = {1: 4, 2: 13}


def test_pending_bodies_are_the_recorded_count():
    """Equal, not just below: a commit that writes a body records it,
    so the number here is the state of the m65 build."""
    counts = AUDIT.pending_counts()
    assert {n: c for n, c in counts.items() if c} == \
        {n: c for n, c in PENDING_RECORDED.items() if c}


def test_pending_count_counts_sites_not_mentions(tmp_path):
    (tmp_path / "m.s").write_text(
        "        PLAT_PENDING 1\n"
        "@x:     PLAT_PENDING 2      ; c\n"
        "; PLAT_PENDING 2 in a comment\n"
        ".macro PLAT_PENDING n\n")
    assert AUDIT.pending_counts(tmp_path) == {1: 1, 2: 1}
