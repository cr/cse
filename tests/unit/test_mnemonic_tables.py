"""test_mnemonic_tables.py — the profile-row model of dev/mnemonic_tables.py.

Owner: doc/build_system.md

Contract source: [doc/modules/opcode_lookup.md § Design](../../doc/modules/opcode_lookup.md#design),
[doc/build_system.md § Table generation](../../doc/build_system.md#table-generation).

Tier: generator (pure Python).  The emitted bytes are exercised through
the assembler bundles (test_asm_line, test_golden_asm_dasm); these
tests pin the model's own contract against the instruction-set oracle
— never against the generator's output.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import instruction_set as I                      # noqa: E402
import mnemonic_tables as M                      # noqa: E402

CPU_SETS = list(M.CPU_SETS)


@pytest.fixture(scope="module", params=CPU_SETS)
def model(request):
    return M.build_asm_model(request.param)


def test_every_row_of_every_view_reproduces(model):
    """base ^ delta (| digit) equals each row's opcode; masks admit exactly
    the rows (validate_asm_model is derive-or-die; this re-checks it
    independently over instructions(view))."""
    _, views, _ = M.CPU_SETS[model.cpu_set]
    for view in views:
        rows = {}
        for r in I.instructions(view):
            if not r.prefix:
                rows.setdefault((r.key, r.mode), set()).add((r.opcode, int(r.suffix or 0)))
        for (key, mode), opcodes in rows.items():
            if key not in model.key_prof:
                continue
            cat = model.key_prof[key] >> 6
            ext = view == '65c02' and key in model.key_ext
            if M._CAT_SRC[cat] != view and not ext:
                continue
            for opcode, digit in opcodes:
                assert M.model_opcode(model, key, mode, ext, digit) == opcode, (view, key, mode)


def test_fixed_zones_at_pidx_0_to_5(model):
    assert [model.zone_first[z] for z in M.FIXED_ZONES] == list(range(6))


def test_extension_is_adjacent(model):
    """The CMOS upgrade is `inc asm_pidx` (asm_line.md § gate matrix)."""
    for key, ext in model.key_ext.items():
        assert ext == (model.key_prof[key] & 0x3F) + 1, key
        assert model.zone_first['G'] <= ext - 1 < model.zone_first['H'], key


def test_pidx_fits_six_bits_and_rows_fit_offset_byte(model):
    assert len(model.profiles) <= 64
    assert len(model.rows) * model.n_modes <= 256


def test_row_count_is_minimal(model):
    """No colouring with one row fewer exists (the conflict graph's
    chromatic number), checked by brute force over the merged rows."""
    conf = M._conflicts(model.profiles)
    k = len(model.rows) - 1
    if k == 0:
        return
    n = len(model.profiles)
    order = sorted(range(n), key=lambda i: -sum(conf[i]))
    col = [None] * n

    def can(idx):
        if idx == n:
            return True
        v = order[idx]
        for c in range(k):
            if all(col[u] != c for u in range(n) if conf[v][u]):
                col[v] = c
                if can(idx + 1):
                    return True
                col[v] = None
        return False
    assert not can(0)


def test_no_foreign_profiles(model):
    """A CPU set's profiles carry no mode or encoding of a CPU outside it."""
    _, views, _ = M.CPU_SETS[model.cpu_set]
    allowed = {(r.key, r.mode) for v in views for r in I.instructions(v)}
    modes_in_set = {m for (_, m) in allowed}
    for p in model.profiles:
        assert p.modes <= modes_in_set, (model.cpu_set, p.modes - modes_in_set)


def test_zone_overflow_is_refused(monkeypatch):
    """Two distinct implied-only profiles cannot share zone A."""
    real = M._profile

    def fake(opcodes, base):
        p = real(opcodes, base)
        if p.modes == {'IMP'} and base == 0xEA:      # NOP: give it a foreign delta
            return M.Profile(p.modes, (('IMP', 1),))
        return p
    monkeypatch.setattr(M, '_profile', fake)
    with pytest.raises(M.ModelError):
        M.build_asm_model('6502')
