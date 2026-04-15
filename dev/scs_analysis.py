#!/usr/bin/env python3
"""
Phase 16 feasibility study: Shortest Common Superstring (SCS) analysis.

Parses dev/strings.txt catalog, eliminates substrings, and reports
compaction potential.
"""

import re
import sys
from pathlib import Path
from dataclasses import dataclass


@dataclass
class StringEntry:
    id: str
    seg: str        # R=RODATA, C=CODE
    nbytes: int
    source: str
    content: str    # raw content (Python string, no quotes)
    no_nul: bool    # True if string has no NUL terminator


def parse_strings(path: Path) -> list[StringEntry]:
    """Parse dev/strings.txt into a list of StringEntry."""
    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            parts = line.split('|')
            if len(parts) < 5:
                continue

            sid = parts[0].strip()
            seg = parts[1].strip()
            nbytes = int(parts[2].strip())
            source = parts[3].strip()
            raw_content = parts[4].strip()

            # Detect flags
            no_nul = '[no NUL]' in raw_content
            has_hex = '[has $22' in raw_content

            # Extract the quoted string content
            m = re.match(r'"(.*?)"', raw_content)
            if not m:
                # Try unquoted (shouldn't happen with our format)
                continue

            content = m.group(1)
            # Process escape sequences
            content = content.replace('\\0', '')    # strip NUL markers
            content = content.replace('\\x22', '"') # $22 = PETSCII quote

            entries.append(StringEntry(
                id=sid,
                seg=seg,
                nbytes=nbytes,
                source=source,
                content=content,
                no_nul=no_nul,
            ))
    return entries


def eliminate_substrings(entries: list[StringEntry]) -> tuple[list[StringEntry], list[tuple[StringEntry, StringEntry]]]:
    """Remove entries whose content is a substring of another entry's content.

    Returns (survivors, eliminated) where eliminated is list of
    (removed_entry, containing_entry) pairs.
    """
    # Sort by content length descending so we check shorter against longer
    by_length = sorted(entries, key=lambda e: len(e.content), reverse=True)

    eliminated = []
    survivors = []

    for i, entry in enumerate(by_length):
        contained_in = None
        for j, other in enumerate(by_length):
            if i == j:
                continue
            if len(other.content) <= len(entry.content) and other.content != entry.content:
                continue
            if entry.content in other.content and entry is not other:
                contained_in = other
                break
        if contained_in is not None:
            eliminated.append((entry, contained_in))
        else:
            survivors.append(entry)

    return survivors, eliminated


def main():
    script_dir = Path(__file__).parent
    catalog_path = script_dir / 'strings.txt'

    entries = parse_strings(catalog_path)
    print(f"Parsed {len(entries)} string entries, {sum(e.nbytes for e in entries)} bytes total")
    print()

    # Deduplicate exact duplicates first (keep first occurrence)
    seen_content = {}
    unique = []
    dupes = []
    for e in entries:
        if e.content in seen_content:
            dupes.append((e, seen_content[e.content]))
        else:
            seen_content[e.content] = e
            unique.append(e)

    if dupes:
        print(f"── Exact duplicates: {len(dupes)} entries removed ──")
        for removed, kept in dupes:
            print(f"  {removed.id:20s} = {kept.id} ({repr(removed.content)})")
        print(f"  Unique: {len(unique)} entries, {sum(e.nbytes for e in unique)} bytes")
        print()

    # Substring elimination
    survivors, eliminated = eliminate_substrings(unique)

    if eliminated:
        print(f"── Substring elimination: {len(eliminated)} entries absorbed ──")
        for removed, container in eliminated:
            print(f"  {removed.id:20s} ({repr(removed.content):20s} {removed.nbytes:2d}B)"
                  f"  ⊂  {container.id} ({repr(container.content)})")
        print()

    # Final stats
    surv_bytes = sum(len(e.content) for e in survivors)
    orig_bytes = sum(e.nbytes for e in entries)

    print(f"══ RESULT ══")
    print(f"  Original:    {len(entries):3d} strings, {orig_bytes:4d} bytes (with NUL terminators)")
    print(f"  After dedup: {len(unique):3d} strings, {sum(e.nbytes for e in unique):4d} bytes")
    print(f"  After substr:{len(survivors):3d} strings, {surv_bytes:4d} bytes (content only, no NUL)")
    print()
    print(f"── Survivors ──")
    for e in sorted(survivors, key=lambda e: (-len(e.content), e.id)):
        print(f"  {e.id:20s} {e.seg} {len(e.content):3d}  {repr(e.content)}")


if __name__ == '__main__':
    main()
