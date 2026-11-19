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
import instruction_set as I                      # noqa: E402
from mnemonic_tables import Entry, Profile       # noqa: E402


@pytest.fixture(scope="module", params=list(M.CPU_SETS))
def model(request):
    return M.build_asm_model(request.param)


# ── the three C64 CPU sets ──────────────────────────────────────────────────

def test_no_empty_and_no_duplicate_profile(model):
    assert all(p.modes for p in model.profiles)
    if model.zones:                 # m65: zone H unique; G pairs and Q groups repeat
        h = model.profiles[model.zones['H']:]
        assert len(set(h)) == len(h)
    else:
        assert len(set(model.profiles[model.zone_g:])) == len(model.profiles[model.zone_g:])


def test_extension_is_adjacent(model):
    """The CMOS upgrade is `inc asm_pidx`: a category-1 key's extension
    profile sits right after its NMOS profile, both multi-mode."""
    if model.zones:
        return                      # m65: test_m65_extension_is_adjacent
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


# ── oplen_tbl: one length per opcode, conflicts refused ─────────────────────

def test_oplen_length_conflict_is_refused():
    """Two OPCODES rows giving one opcode different lengths (neither a
    crash opcode) stop the generator instead of keeping the last row."""
    opcodes = dict(M.OPCODES, XXX={M.I.ABS: 0xEA})      # NOP is 1 byte
    with pytest.raises(M.ModelError, match=r"\$EA"):
        M.oplen_lengths(opcodes)


def test_oplen_crash_opcode_yields_to_the_real_instruction():
    """$D2 is CMP (zp) on the 65C02 (2 B) and the CIM crash on the 6510:
    the crash halts the CPU whatever its length, so the real
    instruction's length wins."""
    assert M.oplen_lengths()[0xD2] == 2


def test_oplen_same_length_coincidence_is_accepted():
    """6510 illegals and 65C02 opcodes sharing a byte with one length
    (e.g. $07 SLO zp / RMB0 zp) are not a conflict."""
    assert M.oplen_lengths()[0x07] == 2


# ── oplen_tbl oracle: the assembled table against instruction_set.py ────────

_CRASH = {'CIM', 'HLT', 'JAM', 'KIL'}     # halt the CPU; their length is moot


def test_oplen_tbl_in_each_prg_matches_instruction_set(cse_prg_per_cpu):
    """The debugger steps with the `oplen_tbl` linked into each C64
    PRG.  Read it from the PRG and hold every opcode to
    dev/instruction_set.py, the independent source: each non-crash
    OPCODES row has length 1 + its mode's operand bytes; an opcode no
    row names has length 1."""
    from conftest import SymbolTable
    prg_path, map_path = cse_prg_per_cpu
    data = prg_path.read_bytes()
    load = data[0] | data[1] << 8
    s = SymbolTable(map_path.with_suffix(".lbl"))
    # oplen_tbl is RODATA: in the PRG at its load position.
    off = s["oplen_tbl"] - s["__RODATA_RUN__"] + s["__RODATA_LOAD__"] - load + 2
    tbl = data[off:off + 64]
    length = [(tbl[op >> 2] >> ((op & 3) * 2)) & 3 for op in range(256)]

    named = set()
    for mne, modes in M.I.OPCODES.items():
        for mode, op in modes.items():
            if op is None:
                continue
            named.add(op)
            if mne not in _CRASH:
                assert length[op] == 1 + M.I.MODE_OPERAND_BYTES[mode], \
                    f"${op:02X} {mne} {mode}: oplen {length[op]}"
    for op in set(range(256)) - named:
        assert length[op] == 1, f"${op:02X} (no instruction): oplen {length[op]}"



# ── the m65 set (opcode_lookup.md § Design, mn_classify.md; D-P4-10) ───────

@pytest.fixture(scope="module")
def m65():
    return M.build_asm_model('45gs02')


def test_m65_three_mask_planes(m65):
    assert m65.n_modes == 20 and len(m65.rows) * m65.n_modes <= 256


def test_m65_branch_zone_is_a_range(m65):
    b = m65.zones['B']
    assert [m65.profiles[b + i].modes for i in range(3)] == \
        [{'REL'}, {'REL', 'REL16'}, {'REL16'}]
    assert m65.zones['F'] == b + 3
    assert m65.key_prof['BNE'] & 0x3F == b and m65.key_prof['BNE'] >> 6 == 1
    assert m65.key_prof['BRA'] & 0x3F == b + 1
    assert m65.key_prof['BSR'] & 0x3F == b + 2


def test_m65_extension_is_adjacent(m65):
    for key, prof in m65.key_prof.items():
        if prof >> 6 == 1:
            pidx = prof & 0x3F
            assert m65.effective_pidx(key, '4510') == pidx + 1, key
            assert m65.profiles[pidx].modes < m65.profiles[pidx + 1].modes, key


def test_m65_q_profile_follows_the_effective_one(m65):
    q0, q1 = m65.zones['Q'], m65.zones['H']
    for key in I.QUAD_STEMS:
        eff = m65.effective_pidx(key, '45gs02')
        assert q0 <= eff < q1, key
        assert eff + 1 < q1
    for qname, stem in I.Q_NAMES.items():
        assert m65.key_prof[qname] >> 6 == 2
        assert m65.key_prof[qname] & 0x3F == m65.effective_pidx(stem, '45gs02') + 1


def test_m65_no_other_key_in_the_quad_zone(m65):
    """The `q` suffix is admitted by zone Q: no other key may land there."""
    q0, q1 = m65.zones['Q'], m65.zones['H']
    for key in m65.key_prof:
        if key in I.QUAD_STEMS or key in I.Q_NAMES:
            continue
        for view in ('6502', '65c02', '4510', '45gs02'):
            eff = m65.effective_pidx(key, view)
            assert eff is None or not q0 <= eff < q1, (key, view)


@pytest.mark.parametrize("key,cat", [("NOP", 0), ("LDX", 0), ("LDA", 1), ("BNE", 1),
                                     ("JSR", 1), ("LDQ", 2), ("TAZ", 3), ("STZ", 3)])
def test_m65_categories(m65, key, cat):
    assert m65.key_prof[key] >> 6 == cat


def test_m65_c02_marks_what_the_65c02_has(m65):
    """mn_classify.md: the keys and extensions the 65C02 has."""
    want = {'ADC', 'AND', 'CMP', 'EOR', 'LDA', 'ORA', 'SBC', 'STA', 'BIT', 'DEC',
            'INC', 'JMP', 'BRA', 'PHX', 'PHY', 'PLX', 'PLY', 'STZ', 'TRB', 'TSB',
            'RMB', 'SMB', 'BBR', 'BBS'}
    assert {k for k, c in m65.key_c02.items() if c} == want


def test_m65_classifier_t_is_the_search_and_exact():
    M.mn7gs.verify()
    assert M.mn7gs.verify_fingerprint() == []


def test_m65_oplen_is_the_4510s():
    lengths = M.m65_oplen_lengths()
    for r in I.instructions('4510'):
        assert lengths[r.opcode] == 1 + I.MODE_OPERAND_BYTES[r.mode], hex(r.opcode)


def test_generation_does_not_depend_on_the_hash_seed(tmp_path):
    """Python randomises str hashes per process: a model built by iterating
    a set would number its profiles differently from run to run.  Both
    generators, under two seeds, write the same files."""
    import os
    import subprocess
    dev = pathlib.Path(__file__).resolve().parents[2] / "dev"
    outs = []
    for seed in ("1", "2"):
        out = tmp_path / seed
        env = dict(os.environ, PYTHONHASHSEED=seed)
        for gen in ("mnemonic_tables.py", "dasm_tables.py"):
            subprocess.run([sys.executable, gen, "--out", str(out)], cwd=dev, env=env,
                           check=True, capture_output=True)
        outs.append({p.name: p.read_bytes() for p in sorted(out.iterdir())})
    assert outs[0] == outs[1]
