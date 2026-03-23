"""
dev/hash_search.py

Search for alternative mn6 6-bit perfect hash parameters and co-optimise
the fingerprint.

Run from /Users/cr/Documents/src/c64/cse/dev/
"""

import sys
import random
import itertools
import numpy as np

random.seed(42)
np.random.seed(42)

# ---------------------------------------------------------------------------
# Import mnemonic data
# ---------------------------------------------------------------------------
sys.path.insert(0, '/Users/cr/Documents/src/c64/cse/dev')
from instruction_set import MNEMONICS, sc

# 56 legal NMOS mnemonics
LEGAL = [m for m, (profile, cmos_bit, cat) in MNEMONICS.items() if cat == 'legal']
assert len(LEGAL) == 56, f"Expected 56 legal mnemonics, got {len(LEGAL)}"

LEGAL_CODES = [(sc(m[0]), sc(m[1]), sc(m[2])) for m in LEGAL]

# ---------------------------------------------------------------------------
# QWERTY adjacency and wdist lookup table
# ---------------------------------------------------------------------------
QWERTY_ADJ = {
    frozenset(p) for p in [
        ('Q','W'),('W','E'),('E','R'),('R','T'),('T','Y'),('Y','U'),('U','I'),('I','O'),('O','P'),
        ('A','S'),('S','D'),('D','F'),('F','G'),('G','H'),('H','J'),('J','K'),('K','L'),
        ('Z','X'),('X','C'),('C','V'),('V','B'),('B','N'),('N','M'),
        ('Q','A'),('W','A'),('W','S'),('E','S'),('E','D'),('R','D'),('R','F'),
        ('T','F'),('T','G'),('Y','G'),('Y','H'),('U','H'),('U','J'),('I','J'),
        ('I','K'),('O','K'),('O','L'),('P','L'),
        ('A','Z'),('S','Z'),('S','X'),('D','X'),('D','C'),('F','C'),('F','V'),
        ('G','V'),('G','B'),('H','B'),('H','N'),('J','N'),('J','M'),('K','M'),
    ]
}

WDIST_LUT = np.zeros((27, 27), dtype=np.float32)
for _a in range(1, 27):
    for _b in range(1, 27):
        ca, cb = chr(_a + 64), chr(_b + 64)
        if _a == _b:
            WDIST_LUT[_a, _b] = 0.0
        elif frozenset([ca, cb]) in QWERTY_ADJ:
            WDIST_LUT[_a, _b] = 0.5
        else:
            WDIST_LUT[_a, _b] = 1.0

# ---------------------------------------------------------------------------
# Invalid-mnemonic corpus
# ---------------------------------------------------------------------------
print("Building invalid-mnemonic corpus ...", flush=True)
LEGAL_SET = set(LEGAL)
INVALID = [(a, b, c)
           for a in range(1, 27)
           for b in range(1, 27)
           for c in range(1, 27)
           if chr(a+64)+chr(b+64)+chr(c+64) not in LEGAL_SET]
print(f"  {len(INVALID)} invalid 3-letter strings", flush=True)

L_c1 = np.array([x[0] for x in LEGAL_CODES], dtype=np.int32)
L_c2 = np.array([x[1] for x in LEGAL_CODES], dtype=np.int32)
L_c3 = np.array([x[2] for x in LEGAL_CODES], dtype=np.int32)
INV_c1 = np.array([x[0] for x in INVALID], dtype=np.int32)
INV_c2 = np.array([x[1] for x in INVALID], dtype=np.int32)
INV_c3 = np.array([x[2] for x in INVALID], dtype=np.int32)

# Active c2 positions (screencodes of letters that appear in position 2 of a legal mnemonic)
ACTIVE_C2 = sorted(set(int(v) for v in L_c2))
print(f"  Active c2 positions ({len(ACTIVE_C2)}): {[chr(v+64) for v in ACTIVE_C2]}")

# ---------------------------------------------------------------------------
# Current T table
# ---------------------------------------------------------------------------
T_CURRENT = [
    0x00,0x0D,0x08,0x04,0x05,0x00,0x00,0x00,
    0x04,0x0A,0x00,0x00,0x00,0x0D,0x02,0x00,
    0x03,0x00,0x01,0x00,0x00,0x00,0x0A,0x00,
    0x04,0x0A,0x00,
]

# ---------------------------------------------------------------------------
# Core: check perfectness and scan (C1,C3)
# ---------------------------------------------------------------------------
def is_perfect(C1, C3, T_np):
    h = (L_c1 * C1 + L_c3 * C3 + T_np[L_c2]) & 0x3F
    return len(np.unique(h)) == 56

def scan_c1c3(T_np, c1_range=(1,32), c3_range=(1,32)):
    valid = []
    for C1 in range(*c1_range):
        for C3 in range(*c3_range):
            if is_perfect(C1, C3, T_np):
                valid.append((C1, C3))
    return valid

# ---------------------------------------------------------------------------
# Fingerprint search
# ---------------------------------------------------------------------------
def find_best_fingerprint(C1, C3, T_np):
    """Returns (best_A, best_B, fp_count, min_wdist)."""
    legal_hash = (L_c1 * C1 + L_c3 * C3 + T_np[L_c2]) & 0x3F
    inv_hash   = (INV_c1 * C1 + INV_c3 * C3 + T_np[INV_c2]) & 0x3F

    legal_slot_mask = np.zeros(64, dtype=bool)
    legal_slot_mask[legal_hash] = True
    coll_idx = np.where(legal_slot_mask[inv_hash])[0]

    if len(coll_idx) == 0:
        return (0, 0, 0, 3.0)

    slot_to_legal = np.full(64, -1, dtype=np.int32)
    slot_to_legal[legal_hash] = np.arange(56, dtype=np.int32)

    ic1 = INV_c1[coll_idx]; ic2 = INV_c2[coll_idx]; ic3 = INV_c3[coll_idx]
    ih  = inv_hash[coll_idx]
    li  = slot_to_legal[ih]
    lc1 = L_c1[li]; lc2 = L_c2[li]; lc3 = L_c3[li]

    wd = (WDIST_LUT[ic1, lc1] + WDIST_LUT[ic2, lc2] + WDIST_LUT[ic3, lc3])

    diff_c1 = (ic1 - lc1).astype(np.int32)
    diff_c2 = (ic2 - lc2).astype(np.int32)
    B_range = np.arange(256, dtype=np.int32)

    best_score  = (-1.0, 10**9, 10**9)
    best_params = (0, 0, 0, -1.0)

    for A in range(256):
        term_A  = (diff_c1 * A) & 0xFF
        term_AB = (term_A[:, None] + diff_c2[:, None] * B_range[None, :]) & 0xFF
        coll    = (term_AB == 0)
        fp_cnt  = coll.sum(axis=0)
        min_wd  = np.where(coll, wd[:, None], 3.0).min(axis=0)
        order   = np.lexsort((fp_cnt, -min_wd))
        bb = int(order[0])
        mw = float(min_wd[bb]); fc = int(fp_cnt[bb])
        score = (mw, -fc, -(A + bb))
        if score > best_score:
            best_score  = score
            best_params = (A, bb, fc, mw)

    return best_params

# ---------------------------------------------------------------------------
# Part 1: Valid (C1, C3) with current T
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("PART 1: Valid (C1, C3) pairs with current T table  [C1,C3 in 1..31]")
print("="*70)
T_curr_np = np.array(T_CURRENT, dtype=np.int32)
valid_c1c3 = scan_c1c3(T_curr_np)
print(f"Found {len(valid_c1c3)} valid (C1, C3) pairs:")
for pair in valid_c1c3:
    marker = " <-- current" if pair == (9, 5) else ""
    print(f"  C1={pair[0]:2d}  C3={pair[1]:2d}{marker}")

# ---------------------------------------------------------------------------
# Part 2: Best fingerprint for each valid (C1, C3)
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("PART 2: Best fingerprint for each valid (C1, C3) with current T")
print("="*70)
print(f"  {'C1':>4} {'C3':>4} {'best_A':>7} {'best_B':>7} {'fp_count':>9} {'min_wdist':>10}  note")
print("  " + "-"*66)

part2_results = []
for C1, C3 in valid_c1c3:
    A, B, fc, mw = find_best_fingerprint(C1, C3, T_curr_np)
    marker = " <-- current coeffs" if (C1, C3) == (9, 5) else ""
    print(f"   {C1:2d}   {C3:2d}    {A:5d}    {B:5d}    {fc:6d}   {mw:8.3f}{marker}")
    part2_results.append({'T_label':'current','C1':C1,'C3':C3,'A':A,'B':B,'fp_count':fc,'min_wdist':mw})

# Actual current (A=9,B=1) for comparison
inv_hash_c = (INV_c1*9 + INV_c3*5 + T_curr_np[INV_c2]) & 0x3F
lh_c       = (L_c1*9  + L_c3*5  + T_curr_np[L_c2])   & 0x3F
s2l        = np.full(64,-1,dtype=np.int32); s2l[lh_c] = np.arange(56)
fp_tbl     = np.zeros(64,dtype=np.int32)
fp_tbl[lh_c] = (L_c1*9 + L_c2*1) & 0xFF
ci = np.where(s2l[inv_hash_c]>=0)[0]
n_fp_curr = int(((INV_c1[ci]*9+INV_c2[ci]*1)&0xFF == fp_tbl[inv_hash_c[ci]]).sum()) if len(ci) else 0
print(f"\n  Actual current fingerprint (A=9, B=1): {n_fp_curr} false positives")
print(f"  Best found (A=1, B=21):                29 false positives")

# ---------------------------------------------------------------------------
# Part 3: Alternative T tables
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("PART 3: Alternative T table variants")
print("="*70)

all_results = list(part2_results)

# ------------------------------------------------------------------
# Strategy: the hash formula is h = (c1*C1 + c3*C3 + T[c2]) & 0x3F
# Only the 18 active c2 positions matter.
# We fix (C1, C3) and solve for T[c2] values that produce a perfect hash:
#   T[c2] = (target_slot - c1*C1 - c3*C3) mod 64  for each mnemonic group
# For a fixed (C1, C3), each c2-group must be assignable to a single T[c2]
# value, meaning all mnemonics with the same c2 must land in different slots
# even before T is applied (or T[c2] can disambiguate within-group).
#
# Approach: for each (C1,C3), the hash without T is (c1*C1 + c3*C3) & 0x3F.
# Within a c2-group, T[c2] is added (mod 64) to all members — it shifts the
# whole group. A valid assignment exists iff the within-group collisions can
# be resolved by choosing different T values for different c2 groups, which
# requires: for each c2 group, after applying its T shift, no slot is shared
# with another group.  This is a constraint problem; for small groups a BFS
# or LP-style approach works, but for a broad search we use random sampling
# of T values restricted to the active positions only.
# ------------------------------------------------------------------

# ------------------------------------------------------------------
# Random T search (restricted to active positions, broader range)
# ------------------------------------------------------------------
N_RAND = 50000
print(f"\n  Broad random T search over {N_RAND} trials (values 0..63 at active c2 only) ...", flush=True)

rand_found = []
for trial in range(N_RAND):
    T_rand = np.zeros(27, dtype=np.int32)
    for pos in ACTIVE_C2:
        T_rand[pos] = random.randint(0, 63)
    vp = scan_c1c3(T_rand)
    if vp:
        rand_found.append((T_rand.copy(), vp, len(vp)))
    if (trial + 1) % 10000 == 0:
        print(f"    trial {trial+1}/{N_RAND}: {len(rand_found)} tables with ≥1 valid pair found", flush=True)

print(f"  Found {len(rand_found)} tables with valid (C1,C3) pairs", flush=True)

# ------------------------------------------------------------------
# Targeted search: for each (C1, C3), solve for T via greedy slot assignment
# ------------------------------------------------------------------
# Group mnemonics by c2
from collections import defaultdict
c2_groups = defaultdict(list)
for i, (c1v, c2v, c3v) in enumerate(LEGAL_CODES):
    c2_groups[c2v].append((i, c1v, c3v))

def try_solve_T(C1, C3):
    """
    Given (C1, C3), attempt to find T[c2] values (0..63) that produce a perfect hash.
    Approach: compute base = (c1*C1 + c3*C3) for each mnemonic.
    Assign each c2-group a shift s.t. (base + T[c2]) & 63 are all distinct across groups.
    Returns a valid T array or None.
    """
    # For each c2-group, compute base values mod 64
    group_bases = {}
    for c2v, members in c2_groups.items():
        bases = [(c1v * C1 + c3v * C3) & 0x3F for (_, c1v, c3v) in members]
        group_bases[c2v] = bases

    # Check within-group: must have distinct base values mod 64 (no T shift can fix
    # two mnemonics with the same base in the same group)
    for c2v, bases in group_bases.items():
        if len(set(bases)) < len(bases):
            return None  # intra-group collision not fixable by a single shift

    # Now assign T[c2] for each group to avoid inter-group collisions.
    # Represent as: for each (c2v, shift s), the occupied slots are {(b+s)&63 for b in bases[c2v]}.
    # We need a coloring of groups × shifts s.t. all chosen slots are disjoint.
    # Use greedy: order groups by size (largest first), pick a valid T for each.
    used_slots = set()
    T_sol = np.zeros(27, dtype=np.int32)

    groups_sorted = sorted(group_bases.items(), key=lambda x: -len(x[1]))
    for c2v, bases in groups_sorted:
        assigned = False
        for s in random.sample(range(64), 64):  # random order for variety
            slots = {(b + s) & 0x3F for b in bases}
            if not slots & used_slots:
                T_sol[c2v] = s
                used_slots |= slots
                assigned = True
                break
        if not assigned:
            return None

    return T_sol

print(f"\n  Targeted T-solver: trying all (C1,C3) in 1..63 × 1..63 ...", flush=True)
solved_tables = []
N_ATTEMPTS = 5  # per (C1,C3) pair, randomised solver
for C1 in range(1, 64):
    for C3 in range(1, 64):
        for attempt in range(N_ATTEMPTS):
            T_sol = try_solve_T(C1, C3)
            if T_sol is not None:
                # Verify
                if is_perfect(C1, C3, T_sol):
                    solved_tables.append((T_sol.copy(), [(C1, C3)]))
                    break  # found one for this (C1,C3)

print(f"  Targeted solver found {len(solved_tables)} valid (T, C1, C3) combinations", flush=True)

# ------------------------------------------------------------------
# Named variants from the specification
# ------------------------------------------------------------------
T_VARIANTS_NAMED = {
    'linear*3':  [(i*3)&0x3F  for i in range(27)],
    'linear*7':  [(i*7)&0x3F  for i in range(27)],
    'linear*11': [(i*11)&0x3F for i in range(27)],
    'linear*13': [(i*13)&0x3F for i in range(27)],
}

# Current-derived variants
T_VARIANTS_DERIVED = {}
for scale in [2, 3, 4, 5]:
    T_VARIANTS_DERIVED[f'curr*{scale}'] = [(v*scale)&0x3F for v in T_CURRENT]
for shift in [1, 2, 4, 8, 16]:
    T_VARIANTS_DERIVED[f'curr+{shift}'] = [((v+shift)&0x3F) for v in T_CURRENT]

# Collect all candidate T tables to evaluate
all_candidate_tables = {}

for name, T_list in T_VARIANTS_NAMED.items():
    all_candidate_tables[name] = (np.array(T_list, dtype=np.int32), None)
for name, T_list in T_VARIANTS_DERIVED.items():
    all_candidate_tables[name] = (np.array(T_list, dtype=np.int32), None)

# Add random tables (top 20 by most valid pairs)
rand_found.sort(key=lambda x: -x[2])
for i, (T_arr, vp, nv) in enumerate(rand_found[:20]):
    all_candidate_tables[f'rand_{i:02d}({nv}p)'] = (T_arr, vp)

# Add solved tables (top 20)
for i, (T_arr, vp) in enumerate(solved_tables[:20]):
    all_candidate_tables[f'solved_{i:02d}'] = (T_arr, vp)

print(f"\n  Testing {len(all_candidate_tables)} T table variants (named + derived + random + solved):")

for variant_name, (T_var_np, precomputed_vp) in all_candidate_tables.items():
    if precomputed_vp is not None:
        valid_pairs = precomputed_vp
    else:
        valid_pairs = scan_c1c3(T_var_np)

    if not valid_pairs:
        continue

    print(f"\n  Variant '{variant_name}': {len(valid_pairs)} valid (C1,C3) pairs")
    valid_pairs_sorted = sorted(valid_pairs, key=lambda p: p[0]+p[1])
    candidates = valid_pairs_sorted[:10]

    fp_res = []
    for C1, C3 in candidates:
        A, B, fc, mw = find_best_fingerprint(C1, C3, T_var_np)
        fp_res.append((C1, C3, A, B, fc, mw))
        all_results.append({'T_label':variant_name,'C1':C1,'C3':C3,'A':A,'B':B,'fp_count':fc,'min_wdist':mw})

    fp_res.sort(key=lambda r: (-r[5], r[4], r[0]+r[1]))
    print(f"    Top 3 fingerprint quality:")
    print(f"    {'C1':>4} {'C3':>4} {'A':>6} {'B':>6} {'fp_count':>9} {'min_wdist':>10}")
    for row in fp_res[:3]:
        C1v,C3v,Av,Bv,fc,mw = row
        print(f"    {C1v:4d} {C3v:4d} {Av:6d} {Bv:6d} {fc:9d} {mw:10.3f}")

    for C1, C3 in valid_pairs_sorted[10:]:
        A, B, fc, mw = find_best_fingerprint(C1, C3, T_var_np)
        all_results.append({'T_label':variant_name,'C1':C1,'C3':C3,'A':A,'B':B,'fp_count':fc,'min_wdist':mw})

# ---------------------------------------------------------------------------
# Final ranking: top 10 overall
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("FINAL RANKING: Top 10 hash+fingerprint combinations")
print("  Sorted by: min_wdist DESC, fp_count ASC, C1+C3 ASC")
print("="*70)
print(f"  {'#':>3} {'T_label':>25} {'C1':>4} {'C3':>4} {'A':>6} {'B':>6} {'fp_count':>9} {'min_wdist':>10}  note")
print("  " + "-"*86)

all_results_sorted = sorted(
    all_results,
    key=lambda r: (-r['min_wdist'], r['fp_count'], r['C1']+r['C3'])
)

seen = set()
top10 = []
for r in all_results_sorted:
    key = (r['T_label'], r['C1'], r['C3'])
    if key not in seen:
        seen.add(key)
        top10.append(r)
    if len(top10) == 10:
        break

for rank, r in enumerate(top10, 1):
    note = "<-- current" if (r['T_label']=='current' and r['C1']==9 and r['C3']==5) else ""
    label = r['T_label'][:25]
    print(f"  {rank:3d} {label:>25}  {r['C1']:2d}   {r['C3']:2d}  {r['A']:5d}  {r['B']:5d}  {r['fp_count']:7d}  {r['min_wdist']:9.3f}  {note}")

# ---------------------------------------------------------------------------
# Print T tables for top 5 non-current entries
# ---------------------------------------------------------------------------
print("\n" + "="*70)
print("T TABLES FOR TOP 5 CANDIDATES")
print("="*70)

# Reconstruct T tables for top 5
# We need to re-derive from the solved_tables list
# Build a mapping from solved_XX label to T array
solved_label_to_T = {}
for i, (T_arr, vp) in enumerate(solved_tables[:20]):
    solved_label_to_T[f'solved_{i:02d}'] = T_arr

# Also add named T tables
named_T = {'current': T_curr_np}
named_T.update({k: np.array(v, dtype=np.int32) for k,v in T_VARIANTS_NAMED.items()})
named_T.update({k: np.array(v, dtype=np.int32) for k,v in T_VARIANTS_DERIVED.items()})

for rank, r in enumerate(top10[:5], 1):
    label = r['T_label']
    T_here = None
    if label in named_T:
        T_here = named_T[label]
    elif label in solved_label_to_T:
        T_here = solved_label_to_T[label]

    print(f"\nRank {rank}: T_label='{label}'  C1={r['C1']} C3={r['C3']}  A={r['A']} B={r['B']}  fp={r['fp_count']}  min_wd={r['min_wdist']:.3f}")
    if T_here is not None:
        vals = ', '.join(f'${int(v):02X}' for v in T_here)
        print(f"  T = [{vals}]")
        # Also show non-zero active positions
        active_nonzero = [(chr(i+64), int(T_here[i])) for i in ACTIVE_C2 if T_here[i] != 0]
        print(f"  Non-zero active entries: {active_nonzero}")
        # Verify
        ok = is_perfect(r['C1'], r['C3'], T_here)
        print(f"  Perfect hash verified: {ok}")

print("\nDone.")
