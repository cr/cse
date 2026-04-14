#!/usr/bin/env python3
"""od65_syms.py – extract symbols from ca65 object files via od65.

Usage (standalone):
    python dev/od65_syms.py build/cmos-dbg/src/        # all .o in dir
    python dev/od65_syms.py build/cmos-dbg/src/zp.o    # single file
    python dev/od65_syms.py --json build/cmos-dbg/src/  # JSON output

Usage (library):
    from dev.od65_syms import extract_all_symbols
    syms = extract_all_symbols("build/cmos-dbg/src/")
    # syms = {name: {type, addrsize, module, size, kind}, ...}

Requires: ca65 toolchain (od65 binary in PATH).
Object files should be assembled with -g for full debug symbol coverage.
Without -g, only exported symbols are available.
"""

import re
import subprocess
import sys
from pathlib import Path


def _run_od65(obj_path, section):
    """Run od65 with the given dump flag and return stdout."""
    flag = f"--dump-{section}"
    result = subprocess.run(
        ["od65", flag, str(obj_path)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"od65 {flag} {obj_path}: {result.stderr.strip()}")
    return result.stdout


def _parse_symbol_block(text, kind, module):
    """Parse an od65 exports or dbgsyms block into a list of symbol dicts."""
    syms = []
    current = {}
    for line in text.splitlines():
        line = line.strip()

        m = re.match(r'Name:\s+"(.+)"', line)
        if m:
            current["name"] = m.group(1)
            continue

        m = re.match(r"Address size:\s+0x\w+\s+\((\w+)\)", line)
        if m:
            current["addrsize"] = m.group(1)
            continue

        m = re.match(r"Size:\s+0x([0-9a-fA-F]+)\s+\((\d+)\)", line)
        if m:
            current["size"] = int(m.group(1), 16)
            continue

        m = re.match(r"Type:\s+0x\w+\s+\((.+)\)", line)
        if m:
            current["type"] = m.group(1)
            continue

        # New Index line → flush previous
        if re.match(r"Index:\s+\d+", line):
            if "name" in current:
                current.setdefault("kind", kind)
                current.setdefault("module", module)
                current.setdefault("size", 0)
                syms.append(current)
            current = {}

    # Flush last
    if "name" in current:
        current.setdefault("kind", kind)
        current.setdefault("module", module)
        current.setdefault("size", 0)
        syms.append(current)

    return syms


def extract_symbols(obj_path):
    """Extract exports and debug symbols from a single .o file.

    Returns a list of dicts: [{name, type, addrsize, module, size, kind}, ...]
    kind is 'export' or 'dbgsym'.
    """
    obj_path = Path(obj_path)
    module = obj_path.stem

    exports_text = _run_od65(obj_path, "exports")
    dbgsyms_text = _run_od65(obj_path, "dbgsyms")

    exports = _parse_symbol_block(exports_text, "export", module)
    dbgsyms = _parse_symbol_block(dbgsyms_text, "dbgsym", module)

    return exports + dbgsyms


def extract_all_symbols(path):
    """Extract symbols from all .o files in a directory (or a single .o file).

    Returns {name: {type, addrsize, module, size, kind}, ...}.
    Exports take priority over dbgsyms for the same name.
    """
    path = Path(path)
    if path.is_file():
        obj_files = [path]
    elif path.is_dir():
        obj_files = sorted(path.glob("*.o"))
    else:
        raise FileNotFoundError(f"Not a file or directory: {path}")

    result = {}
    for obj in obj_files:
        for sym in extract_symbols(obj):
            name = sym["name"]
            # Exports win over dbgsyms
            if name not in result or sym["kind"] == "export":
                result[name] = sym

    return result


def main():
    import json

    args = sys.argv[1:]
    json_mode = False
    if "--json" in args:
        json_mode = True
        args.remove("--json")

    if not args:
        print(__doc__)
        sys.exit(1)

    path = Path(args[0])
    syms = extract_all_symbols(path)

    if json_mode:
        json.dump(syms, sys.stdout, indent=2)
        print()
    else:
        # Group by module
        by_module = {}
        for name, info in sorted(syms.items()):
            mod = info["module"]
            by_module.setdefault(mod, []).append((name, info))

        total = 0
        for mod in sorted(by_module):
            entries = by_module[mod]
            total += len(entries)
            print(f"\n── {mod} ({len(entries)} symbols) ──")
            for name, info in entries:
                kind = "EXP" if info["kind"] == "export" else "dbg"
                addr = info["addrsize"][:3]
                size = f"[{info['size']}]" if info["size"] else ""
                print(f"  {kind}  {addr}  {name} {size}")

        print(f"\nTotal: {total} symbols from {len(by_module)} modules")


if __name__ == "__main__":
    main()
