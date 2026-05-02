"""Audit module-doc "Depends on:" claims — Step 4 (focused subset).

For each `doc/modules/foo.md` with a `**Depends on:**` block,
extract the listed module names and the parenthesised symbol
hints, then verify against the actual `.import` directives in
the corresponding `src/foo.s`.

Two checks per claim:

  (a) Module name claimed → for each named module (e.g.
      "addr_mode"), verify the corresponding src file actually
      contributes some `.import`ed symbol to `src/foo.s`.

  (b) Symbol-hint claimed → for each parenthesised symbol
      (e.g. "addr_mode (mode_parse, asm_skip_ws, _au_no_acc)"),
      verify the symbol appears in `src/foo.s`'s `.import` lines.

Run:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \\
        dev/audit_doc_depends_on.py
"""

import re
import sys
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
MODULES_DIR = ROOT / "doc" / "modules"
SRC_DIR = ROOT / "src"

# Module names that are NOT 1:1 with a src file but are still
# legitimate dependency claims.
NON_FILE_MODULES = {
    "KERNAL",       # KERNAL ROM, $E000-$FFFF
    "zp",           # zp.s, but ZP vars are usually .importzp not .import
    "memory",       # generic memory
    "mn7_tables", "mn6_tables", "dasm_tables",  # generated tables
    "mn_modes", "mn_asm_tables",
    "GENERATED",    # marker word
}


def read_imports(src_file):
    """Return set of imported symbol names from `.import` /
    `.importzp` directives in src_file."""
    syms = set()
    if not src_file.exists():
        return syms
    try:
        text = src_file.read_text()
    except (OSError, UnicodeDecodeError):
        return syms
    in_block_comment = False
    for line in text.splitlines():
        # Strip line comments
        code = line.split(";", 1)[0]
        m = re.match(
            r"\s*\.(?:import|importzp|global|globalzp)\s+(.+)$",
            code, re.IGNORECASE)
        if m:
            for tok in re.findall(r"\b[A-Za-z_]\w*", m.group(1)):
                syms.add(tok)
    return syms


def extract_depends_block(text):
    """Find the `**Depends on:**` paragraph (may span multiple lines)
    and return the raw text up to the next blank line."""
    m = re.search(r"^\*\*Depends on:\*\*\s*(.+)", text, re.MULTILINE)
    if not m:
        return None
    start = m.start()
    after = text[start:]
    blank = re.search(r"\n\s*\n", after)
    block = after[:blank.start()] if blank else after
    # Drop the leading "**Depends on:**" prefix.
    return block[len("**Depends on:**"):].strip()


def parse_depends(block):
    """Parse the depends block into a list of (module_name, [symbols]).

    Pattern: comma-separated entries, each is either "name" or
    "name (sym1, sym2, ...)".  The block may span multiple lines.
    """
    # Flatten newlines/whitespace.
    flat = re.sub(r"\s+", " ", block)
    # Drop trailing punctuation.
    flat = flat.rstrip(".").strip()
    # If the block is "nothing (leaf module, ...)", return empty.
    if re.match(r"^nothing\b", flat, re.IGNORECASE):
        return []
    # Tokenise: split on commas at the top level (depth=0 wrt parens).
    items = []
    depth = 0
    cur = []
    for ch in flat:
        if ch == "(":
            depth += 1
            cur.append(ch)
        elif ch == ")":
            depth -= 1
            cur.append(ch)
        elif ch == "," and depth == 0:
            items.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        items.append("".join(cur).strip())

    out = []
    for item in items:
        if not item:
            continue
        # Strip backticks.
        item = item.replace("`", "")
        m = re.match(
            r"^([A-Za-z_]\w*)\s*(?:\(([^)]*)\))?\s*$", item)
        if not m:
            continue
        name = m.group(1)
        syms = []
        if m.group(2):
            syms = [
                s.strip().strip("`")
                for s in re.findall(
                    r"\b[A-Za-z_]\w*\b", m.group(2))]
        out.append((name, syms))
    return out


def main():
    findings = {
        "missing_module": [],   # module name claimed but no src/foo.s imported from
        "missing_symbol": [],   # symbol claimed but not actually .import'd
    }

    audited = 0
    for doc in sorted(MODULES_DIR.glob("*.md")):
        try:
            text = doc.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        block = extract_depends_block(text)
        if block is None:
            continue
        module = doc.stem
        src = SRC_DIR / f"{module}.s"
        if not src.exists():
            continue
        audited += 1
        imports = read_imports(src)

        deps = parse_depends(block)
        for dep_name, syms in deps:
            if dep_name in NON_FILE_MODULES:
                continue
            # (a) Verify any symbol from this module is imported.
            # Heuristic: for any symbol from src/<dep_name>.s's
            # .export list, check it appears in imports.
            dep_src = SRC_DIR / f"{dep_name}.s"
            module_provides = set()
            if dep_src.exists():
                try:
                    dep_text = dep_src.read_text()
                except (OSError, UnicodeDecodeError):
                    dep_text = ""
                for line in dep_text.splitlines():
                    code = line.split(";", 1)[0]
                    m = re.match(
                        r"\s*\.(?:export|exportzp|global|globalzp)\s+(.+)$",
                        code, re.IGNORECASE)
                    if m:
                        for tok in re.findall(r"\b[A-Za-z_]\w*", m.group(1)):
                            module_provides.add(tok)

            if module_provides and not (imports & module_provides):
                findings["missing_module"].append({
                    "doc": str(doc.relative_to(ROOT)),
                    "module": module,
                    "claimed_dep": dep_name,
                    "note": (f"src/{module}.s imports nothing from "
                             f"src/{dep_name}.s"),
                })

            # (b) Verify each named symbol is in the import list.
            for sym in syms:
                if sym not in imports:
                    # Some hints are not symbols but English words or
                    # ZP names imported via .importzp.  Skip if the
                    # symbol looks like an English word (no underscore
                    # AND not in the dep_src exports).
                    if module_provides and sym not in module_provides:
                        # Likely English description, e.g. "ZP save"
                        continue
                    findings["missing_symbol"].append({
                        "doc": str(doc.relative_to(ROOT)),
                        "module": module,
                        "claimed_dep": dep_name,
                        "claimed_symbol": sym,
                        "note": (f"`{sym}` not in src/{module}.s "
                                 f"`.import` list"),
                    })

    print(f"Audited {audited} module docs with `**Depends on:**` blocks.")
    print()
    n = sum(len(v) for v in findings.values())
    if n == 0:
        print("✓ All module-doc dependency claims match the source's "
              "`.import` directives.")
        return 0

    print(f"✗ {n} findings:")
    print()
    if findings["missing_module"]:
        print(f"── (a) Module claimed as a dependency but src/<self>.s "
              f"imports nothing from it ({len(findings['missing_module'])})")
        for f in findings["missing_module"]:
            print(f"   {f['doc']}  claims {f['claimed_dep']}")
            print(f"      {f['note']}")
        print()
    if findings["missing_symbol"]:
        print(f"── (b) Symbol claimed in dependency hint but not actually "
              f"imported ({len(findings['missing_symbol'])})")
        for f in findings["missing_symbol"]:
            print(f"   {f['doc']}  claims `{f['claimed_symbol']}` "
                  f"from {f['claimed_dep']}")
            print(f"      {f['note']}")
        print()

    return 1


if __name__ == "__main__":
    sys.exit(main())
