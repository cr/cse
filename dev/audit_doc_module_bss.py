"""Audit module-doc BSS claims — extends the doc-numerical audit
to catch per-module BSS byte-count drift like the dasm.md "BSS
(24 bytes)" miss after the rc5 _dasm_in addition.

For each `doc/modules/*.md`:
  - Find `**BSS (N bytes)**` claim.
  - Look up the corresponding `<module>.o` BSS size in the linker
    map (build/debug/cmos/cse.map).
  - Report mismatch.

Linker-map source-of-truth handles `.res EXPR` cases that simple
parsing of src/*.s cannot evaluate (e.g. `.res FILENAME_MAX + 2`
or `.res (BP_SLOTS + STEP_SLOTS) * SLOT_SIZE`).

Run:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \
        dev/audit_doc_module_bss.py
"""

import re
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent

MODULES_DIR = ROOT / "doc" / "modules"
MAP_PATH = ROOT / "build" / "debug" / "cmos" / "cse.map"

# Match `**BSS (N bytes)**` or `**BSS (N B)**` etc.
BSS_CLAIM_RE = re.compile(
    r"\*\*BSS\s*\((\d+)\s*(?:bytes?|B)\)[:*]+", re.IGNORECASE)


def parse_module_bss_sizes():
    """Parse cse.map's "Modules list" section for per-object BSS sizes.

    Returns dict { module_name: bss_size_in_bytes }.

    The map format is:

        modulename.o:
            CODE              Offs=NNNNNN  Size=NNNNNN  Align=N  Fill=NN
            BSS               Offs=NNNNNN  Size=NNNNNN  ...
            ...
    """
    if not MAP_PATH.exists():
        return None
    sizes = {}
    cur = None
    in_modules = False
    for line in MAP_PATH.read_text().splitlines():
        if line.startswith("Modules list:"):
            in_modules = True
            continue
        if not in_modules:
            continue
        if line and not line.startswith((" ", "\t")) and line.endswith(":"):
            # New module header.
            cur = line[:-1].rstrip()
            if cur.endswith(".o"):
                cur = cur[:-2]
            continue
        if cur is None:
            continue
        m = re.match(
            r"\s+(\w+)\s+Offs=([0-9A-Fa-f]+)\s+Size=([0-9A-Fa-f]+)", line)
        if m and m.group(1) == "BSS":
            sizes[cur] = int(m.group(3), 16)
    return sizes


def main():
    if not MODULES_DIR.exists():
        print(f"Error: {MODULES_DIR} not found")
        return 2

    sizes = parse_module_bss_sizes()
    if sizes is None:
        print(f"Error: {MAP_PATH} not found — run `make debug` first")
        return 2

    findings = []
    audited = 0
    for doc in sorted(MODULES_DIR.glob("*.md")):
        try:
            text = doc.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        match = BSS_CLAIM_RE.search(text)
        if not match:
            continue
        module = doc.stem
        if module not in sizes:
            continue
        audited += 1
        lineno = text[:match.start()].count("\n") + 1
        claimed = int(match.group(1))
        actual = sizes[module]
        if claimed != actual:
            findings.append({
                "doc": str(doc.relative_to(ROOT)),
                "line": lineno,
                "module": module,
                "claimed": claimed,
                "actual": actual,
            })

    print(f"Audited {audited} module docs with BSS claims "
          f"(against {MAP_PATH.relative_to(ROOT)}).")
    print()
    if not findings:
        print("✓ All BSS byte counts match the linker map.")
        return 0

    findings.sort(key=lambda f: -abs(f["claimed"] - f["actual"]))
    print(f"✗ {len(findings)} BSS drift findings:")
    print()
    for f in findings:
        print(f"── {f['doc']}:{f['line']}  [{f['module']}]")
        print(f"   claimed: {f['claimed']} bytes")
        print(f"   actual:  {f['actual']} bytes  (linker map)")
        print()
    return 1


if __name__ == "__main__":
    sys.exit(main())
