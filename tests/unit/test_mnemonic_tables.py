"""test_mnemonic_tables.py — the profile-row model of dev/mnemonic_tables.py.

Owner: doc/build_system.md

Contract source: [doc/modules/opcode_lookup.md § Design](../../doc/modules/opcode_lookup.md#design),
[doc/build_system.md § Table generation](../../doc/build_system.md#table-generation).

Tier: generator (pure Python).  The emitted bytes are exercised through
the assembler bundles (test_asm_line, test_opcode_lookup,
test_golden_asm_dasm); these tests pin the model's placement and
merging rules.  That the tables reproduce every instruction-set row is
the generator's own derive-or-die (`validate_asm_model`, run by every
build_asm_model call) and, end to end, the assembler sweeps.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "dev"))
import mnemonic_tables as M                      # noqa: E402
from mnemonic_tables import Entry, Profile       # noqa: E402


@pytest.fixture(scope="module", params=list(M.CPU_SETS))
def model(request):
    return M.build_asm_model(request.param)


# ── the three C64 CPU sets ──────────────────────────────────────────────────

def test_no_empty_and_no_duplicate_profile(model):
    assert all(p.modes for p in model.profiles)
    assert len(set(model.profiles[model.zone_g:])) == len(model.profiles[model.zone_g:])


def test_extension_is_adjacent(model):
    """The CMOS upgrade is `inc asm_pidx`: a category-1 key's extension
    profile sits right after its NMOS profile, both multi-mode."""
    for key, prof in model.key_prof.items():
        if prof >> 6 == 1 and M.EXT_VIEW in M.CPU_SETS[model.cpu_set][1]:
            pidx = prof & 0x3F
            assert pidx >= model.zone_g, key
            assert model.effective_pidx(key, M.EXT_VIEW) == pidx + 1, key
            assert model.profiles[pidx].modes < model.profiles[pidx + 1].modes, key


def test_pidx_fits_six_bits_and_rows_fit_offset_byte(model):
    assert len(model.profiles) <= 64
    assert len(model.rows) * model.n_modes <= 256


def test_rows_are_as_wide_as_the_highest_used_mode(model):
    used = {M.ALL_MODES.index(m) for p in model.profiles for m in p.modes}
    assert model.n_modes == max(used) + 1


def test_row_count_is_minimal(model):
    """No colouring with one row fewer exists (brute force)."""
    conf = M._conflicts(model.profiles)
    k = len(model.rows) - 1
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
    assert k == 0 or not can(0)


def test_set_uses_only_its_own_modes(model):
    """A CPU set's profiles accept no mode its CPUs do not have."""
    _, views, _ = M.CPU_SETS[model.cpu_set]
    modes_in_set = {r.mode for v in views for r in M.I.instructions(v)}
    for p in model.profiles:
        assert p.modes <= modes_in_set, (model.cpu_set, p.modes - modes_in_set)


# ── placement rules, on synthetic entries ───────────────────────────────────

def _p(**deltas):
    return Profile(frozenset(deltas), tuple(sorted(deltas.items())))


def test_fixed_zones_are_a_prefix_in_zone_order():
    entries = {
        'JSR': Entry(0, 0x20, _p(ABS=0), zone='F'),
        'NOP': Entry(0, 0xEA, _p(IMP=0), zone='A'),
        'BNE': Entry(0, 0xD0, _p(REL=0), zone='B'),
        'LDA': Entry(0, 0xA5, _p(ZP=0, ABS=8)),
    }
    profiles, zone_g, pidx = M.place_profiles(entries)
    assert (pidx['NOP'], pidx['BNE'], pidx['JSR']) == (0, 1, 2)
    assert zone_g == 3 and pidx['LDA'] == 3


def test_zone_gap_is_refused():
    """Zone C present without zone F would shift asm_line's jump table."""
    entries = {
        'NOP': Entry(0, 0xEA, _p(IMP=0), zone='A'),
        'BNE': Entry(0, 0xD0, _p(REL=0), zone='B'),
        'ANC': Entry(2, 0x0B, _p(IMM=0), zone='C'),
    }
    with pytest.raises(M.ModelError):
        M.place_profiles(entries)


def test_two_profiles_in_one_fixed_zone_are_refused():
    entries = {
        'NOP': Entry(0, 0xEA, _p(IMP=0), zone='A'),
        'XXX': Entry(0, 0x00, _p(IMP=1), zone='A'),
    }
    with pytest.raises(M.ModelError):
        M.place_profiles(entries)


def test_multi_mode_key_never_shares_a_fixed_zone_profile():
    """A zero-page-only key that is no bit-digit key (the 4510's DEW/INW)
    encodes like zone D's profile but is parsed as a multi-mode key: it
    must get its own pidx at or above zone_g."""
    zp_only = _p(ZP=0)
    entries = {z: Entry(0, 0, _p(**{m: 0}), zone=z)
               for z, m in (('A', 'IMP'), ('B', 'REL'), ('F', 'ABS'), ('C', 'IMM'))}
    entries['RMB'] = Entry(3, 0x07, zp_only, zone='D')
    entries['DEW'] = Entry(3, 0xC3, zp_only)
    profiles, zone_g, pidx = M.place_profiles(entries)
    assert pidx['RMB'] < zone_g <= pidx['DEW']


def test_standalone_key_shares_a_pair_member():
    nmos, ext = _p(ZP=0, ABS=8), _p(ZP=0, ABS=8, IMM=0x6D)
    entries = {
        'BIT': Entry(1, 0x24, nmos, ext),
        'TRB': Entry(3, 0x14, nmos),
    }
    profiles, zone_g, pidx = M.place_profiles(entries)
    assert profiles == [nmos, ext] and pidx['TRB'] == pidx['BIT'] == 0
