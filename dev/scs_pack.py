#!/usr/bin/env python3
"""
Phase 16 feasibility study: SCS packer for CSE string tables.

Reads dev/strings.txt, computes the shortest common superstring via
beam search + local improvement, and reports compaction potential.

Adapted from generic SCS packer for CSE's catalog format.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional
import random
import time
import sys
from pathlib import Path

# ── reuse the catalog parser from scs_analysis ──────────────────────────
from scs_analysis import parse_strings, StringEntry


# ── SCS core ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ContainedInfo:
    host_id: str
    host_text: str
    offset_in_host: int


@dataclass
class State:
    path: Tuple[int, ...]
    used_mask: int
    score: int
    last: int


@dataclass
class Solution:
    order: List[int]
    superstring: str
    score: int
    offsets: Dict[int, Tuple[int, int]]


def overlap(a: str, b: str) -> int:
    maxk = min(len(a), len(b))
    for k in range(maxk, 0, -1):
        if a[-k:] == b[:k]:
            return k
    return 0


def compute_overlap_matrix(strings: List[str]) -> List[List[int]]:
    n = len(strings)
    ov = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(n):
            if i != j:
                ov[i][j] = overlap(strings[i], strings[j])
    return ov


def best_possible_future(last: int, unused: List[int], ov: List[List[int]]) -> int:
    if not unused:
        return 0
    total = 0
    if last != -1:
        total += max((ov[last][j] for j in unused), default=0)
    for i in unused:
        total += max((ov[i][j] for j in unused if j != i), default=0)
    return total


def beam_search_order(
    strings: List[str], ov: List[List[int]],
    beam_width: int = 128, seed: int = 0,
    time_limit_s: float = 5.0, start_candidates: Optional[int] = None,
) -> List[int]:
    random.seed(seed)
    n = len(strings)
    if n == 0:
        return []

    sum_out = [sum(ov[i]) for i in range(n)]
    starts = sorted(range(n), key=lambda i: (sum_out[i], len(strings[i])), reverse=True)
    if start_candidates is None:
        start_candidates = min(n, beam_width)

    beam: List[State] = [
        State(path=(i,), used_mask=(1 << i), score=0, last=i)
        for i in starts[:start_candidates]
    ]
    start_time = time.time()

    for depth in range(1, n):
        if time.time() - start_time > time_limit_s:
            break
        candidates: List[Tuple[int, int, State]] = []
        for st in beam:
            remaining = [j for j in range(n) if not (st.used_mask & (1 << j))]
            remaining.sort(key=lambda j: (ov[st.last][j], sum_out[j], len(strings[j])), reverse=True)
            branch_cap = min(len(remaining), max(8, beam_width // 4))
            top = remaining[:branch_cap]
            grouped: Dict[int, List[int]] = {}
            for j in top:
                grouped.setdefault(ov[st.last][j], []).append(j)
            shuffled: List[int] = []
            for sc in sorted(grouped, reverse=True):
                bucket = grouped[sc][:]
                random.shuffle(bucket)
                shuffled.extend(bucket)
            for j in shuffled:
                new_score = st.score + ov[st.last][j]
                new_mask = st.used_mask | (1 << j)
                new_path = st.path + (j,)
                if depth + 1 == n:
                    bound = 0
                else:
                    unused = [k for k in range(n) if not (new_mask & (1 << k))]
                    bound = best_possible_future(j, unused, ov)
                new_state = State(path=new_path, used_mask=new_mask, score=new_score, last=j)
                candidates.append((new_score, new_score + bound, new_state))

        best_by_sig: Dict[Tuple[int, int], Tuple[int, int, State]] = {}
        for item in candidates:
            _, priority, st = item
            sig = (st.used_mask, st.last)
            prev = best_by_sig.get(sig)
            if prev is None or priority > prev[1]:
                best_by_sig[sig] = item
        reduced = sorted(best_by_sig.values(), key=lambda x: (x[1], x[0]), reverse=True)
        beam = [st for _, _, st in reduced[:beam_width]]
        if not beam:
            break

    complete = [st for st in beam if len(st.path) == n]
    if complete:
        return list(max(complete, key=lambda st: st.score).path)
    if not beam:
        return starts
    best = max(beam, key=lambda st: st.score)
    order = list(best.path)
    used = best.used_mask
    while len(order) < n:
        last = order[-1]
        remaining = [j for j in range(n) if not (used & (1 << j))]
        j = max(remaining, key=lambda x: (ov[last][x], sum_out[x], len(strings[x])))
        order.append(j)
        used |= 1 << j
    return order


def score_order(order: List[int], ov: List[List[int]]) -> int:
    return sum(ov[order[i]][order[i + 1]] for i in range(len(order) - 1))


def relocate_delta(order: List[int], i: int, j: int, ov: List[List[int]]) -> int:
    if i == j or i + 1 == j:
        return 0
    n = len(order)
    x = order[i]
    def edge(a, b):
        return ov[a][b] if a is not None and b is not None else 0
    a = order[i - 1] if i > 0 else None
    b = order[i + 1] if i + 1 < n else None
    old = edge(a, x) + edge(x, b)
    new = edge(a, b)
    temp = order[:i] + order[i + 1:]
    jj = j if j < i else j - 1
    p = temp[jj - 1] if jj > 0 else None
    q = temp[jj] if jj < len(temp) else None
    old += edge(p, q)
    new += edge(p, x) + edge(x, q)
    return new - old


def apply_relocate(order: List[int], i: int, j: int) -> List[int]:
    if i == j or i + 1 == j:
        return order[:]
    x = order[i]
    temp = order[:i] + order[i + 1:]
    jj = j if j < i else j - 1
    return temp[:jj] + [x] + temp[jj:]


def swap_delta(order: List[int], i: int, j: int, ov: List[List[int]]) -> int:
    if i == j:
        return 0
    if i > j:
        i, j = j, i
    n = len(order)
    def edge(a, b):
        return ov[a][b] if a is not None and b is not None else 0
    affected = set()
    for k in (i - 1, i, i + 1, j - 1, j, j + 1):
        if 0 <= k < n:
            affected.add(k)
    old_score = sum(edge(order[k], order[k + 1]) for k in affected if k + 1 < n)
    new_order = order[:]
    new_order[i], new_order[j] = new_order[j], new_order[i]
    new_score = sum(edge(new_order[k], new_order[k + 1]) for k in affected if k + 1 < n)
    return new_score - old_score


def local_improve(order: List[int], ov: List[List[int]], time_limit_s: float = 2.0) -> List[int]:
    start = time.time()
    current = order[:]
    n = len(current)
    improved = True
    while improved and (time.time() - start <= time_limit_s):
        improved = False
        best_delta, best_move = 0, None
        for i in range(n):
            for j in range(n + 1):
                if time.time() - start > time_limit_s:
                    break
                d = relocate_delta(current, i, j, ov)
                if d > best_delta:
                    best_delta, best_move = d, ("relocate", i, j)
            if time.time() - start > time_limit_s:
                break
        if best_move:
            current = apply_relocate(current, best_move[1], best_move[2])
            improved = True
            continue
        best_delta, best_move = 0, None
        for i in range(n):
            for j in range(i + 1, n):
                if time.time() - start > time_limit_s:
                    break
                d = swap_delta(current, i, j, ov)
                if d > best_delta:
                    best_delta, best_move = d, ("swap", i, j)
            if time.time() - start > time_limit_s:
                break
        if best_move:
            current[best_move[1]], current[best_move[2]] = current[best_move[2]], current[best_move[1]]
            improved = True
    return current


def build_superstring(order: List[int], strings: List[str], ov: List[List[int]]) -> Solution:
    if not order:
        return Solution(order=[], superstring="", score=0, offsets={})
    s = strings[order[0]]
    offsets: Dict[int, Tuple[int, int]] = {order[0]: (0, len(strings[order[0]]))}
    for prev, cur in zip(order, order[1:]):
        ovl = ov[prev][cur]
        pos = len(s) - ovl
        s += strings[cur][ovl:]
        offsets[cur] = (pos, len(strings[cur]))
    return Solution(order=order[:], superstring=s, score=score_order(order, ov), offsets=offsets)


# ── CSE-specific front end ───────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="SCS packer for CSE string tables.")
    ap.add_argument("--min-length", type=int, default=3,
                    help="Strings shorter than this are kept separate (default: 3)")
    ap.add_argument("--beam-width", type=int, default=128)
    ap.add_argument("--beam-seconds", type=float, default=5.0)
    ap.add_argument("--improve-seconds", type=float, default=2.0)
    ap.add_argument("--restarts", type=int, default=16)
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    catalog_path = Path(__file__).parent / 'strings.txt'
    all_entries = parse_strings(catalog_path)

    # ── dedup (keep first occurrence) ────────────────────────────────────
    seen: Dict[str, StringEntry] = {}
    unique: List[StringEntry] = []
    dupes: List[Tuple[StringEntry, StringEntry]] = []
    for e in all_entries:
        if e.content in seen:
            dupes.append((e, seen[e.content]))
        else:
            seen[e.content] = e
            unique.append(e)

    # ── split by min_length ──────────────────────────────────────────────
    short = [e for e in unique if len(e.content) < args.min_length]
    long  = [e for e in unique if len(e.content) >= args.min_length]

    # ── containment removal ──────────────────────────────────────────────
    texts = [e.content for e in long]
    n = len(texts)
    order_by_len = sorted(range(n), key=lambda i: (-len(texts[i]), i))

    removed = set()
    contained: Dict[int, ContainedInfo] = {}
    for pos, i in enumerate(order_by_len):
        if i in removed:
            continue
        for j in order_by_len[pos + 1:]:
            if j in removed:
                continue
            off = texts[i].find(texts[j])
            if off != -1:
                removed.add(j)
                contained[j] = ContainedInfo(
                    host_id=long[i].id, host_text=texts[i], offset_in_host=off)

    active_idx = [i for i in range(n) if i not in removed]
    active_texts = [texts[i] for i in active_idx]

    # ── SCS computation ─────────────────────────────────────────────────
    ov = compute_overlap_matrix(active_texts)

    best_order: List[int] = []
    best_score = -1
    beam_slice = args.beam_seconds / max(args.restarts, 1)
    improve_slice = args.improve_seconds / max(args.restarts, 1)

    for r in range(args.restarts):
        order = beam_search_order(
            active_texts, ov, beam_width=args.beam_width,
            seed=args.seed + r, time_limit_s=beam_slice)
        order = local_improve(order, ov, time_limit_s=improve_slice)
        sc = score_order(order, ov)
        if sc > best_score:
            best_score, best_order = sc, order

    sol = build_superstring(best_order, active_texts, ov)

    # ── map everything back to original entries ──────────────────────────
    # active survivors: direct from solution offsets
    mapping: Dict[str, Tuple[int, int, str]] = {}  # id -> (offset, length, source)
    for ai, (off, ln) in sol.offsets.items():
        orig_i = active_idx[ai]
        e = long[orig_i]
        mapping[e.id] = (off, ln, 'scs')

    # contained: find in superstring
    for orig_i, info in contained.items():
        e = long[orig_i]
        off = sol.superstring.find(e.content)
        assert off != -1, f"contained string {e.content!r} not in superstring"
        mapping[e.id] = (off, len(e.content), f'contained in {info.host_id}')

    # duplicates: point to the same mapping as their kept twin
    for removed_e, kept_e in dupes:
        if kept_e.id in mapping:
            off, ln, src = mapping[kept_e.id]
            mapping[removed_e.id] = (off, ln, f'dup of {kept_e.id}')
        # if kept_e was itself short/excluded, the dup stays separate too

    # ── report ───────────────────────────────────────────────────────────
    orig_bytes = sum(e.nbytes for e in all_entries)
    short_bytes = sum(len(e.content) + (0 if e.no_nul else 1) for e in short)
    scs_bytes = len(sol.superstring)
    # index table: 1B offset + 1B length per mapped string (if superstring < 256)
    # or 2B offset + 1B length if >= 256
    offset_width = 2 if scs_bytes >= 256 else 1
    n_mapped = len(mapping)
    index_bytes = n_mapped * (offset_width + 1)

    print("=" * 65)
    print("CSE String Compaction — SCS Feasibility Report")
    print("=" * 65)
    print()
    print(f"Input")
    print(f"  Catalog entries:     {len(all_entries):4d}")
    print(f"  Total bytes (w/NUL): {orig_bytes:4d}")
    print()
    print(f"Deduplication")
    print(f"  Exact duplicates:    {len(dupes):4d}")
    print(f"  Unique strings:      {len(unique):4d}")
    print()
    print(f"Length filter (min_length={args.min_length})")
    print(f"  Short (separate):    {len(short):4d}  ({short_bytes:3d} bytes w/NUL)")
    print(f"  Long (SCS input):    {len(long):4d}")
    print()
    print(f"Containment removal")
    print(f"  Absorbed:            {len(contained):4d}")
    print(f"  Active (SCS core):   {len(active_texts):4d}  ({sum(len(t) for t in active_texts):3d} bytes content)")
    print()
    print(f"SCS result")
    print(f"  Superstring length:  {scs_bytes:4d} bytes")
    print(f"  Total overlap:       {best_score:4d} bytes")
    print()
    print(f"Cost accounting")
    print(f"  Superstring blob:    {scs_bytes:4d}")
    print(f"  Index table:         {index_bytes:4d}  ({n_mapped} entries x {offset_width+1}B)")
    print(f"  Short strings:       {short_bytes:4d}  ({len(short)} strings, kept as-is)")
    print(f"  ─────────────────────────")
    total = scs_bytes + index_bytes + short_bytes
    print(f"  Total:               {total:4d}")
    print(f"  Original:            {orig_bytes:4d}")
    print(f"  Savings:             {orig_bytes - total:4d}  ({100*(orig_bytes-total)/orig_bytes:.1f}%)")
    print()

    print(f"Superstring ({scs_bytes} chars):")
    # print in 60-char rows with offset ruler
    for i in range(0, scs_bytes, 60):
        chunk = sol.superstring[i:i+60]
        print(f"  {i:3d} | {chunk}")
    print()

    print(f"Index ({n_mapped} entries):")
    for e in all_entries:
        if e.id in mapping:
            off, ln, src = mapping[e.id]
            print(f"  {e.id:20s}  off={off:3d} len={ln:2d}  {repr(e.content):24s}  ({src})")

    if short:
        print()
        print(f"Short strings kept separate ({len(short)}):")
        for e in short:
            print(f"  {e.id:20s}  {len(e.content):2d}  {repr(e.content)}")


if __name__ == '__main__':
    main()
