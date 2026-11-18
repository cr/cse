"""check_deps.py — mechanical layer checker for src/*.s.

Owner: doc/build_system.md

Contract source: doc/architecture.md § Dependency Rules, rule 1:
every `.import` / `.importzp` resolves to a module in the same or a
strictly lower layer.  This script parses every `src/*.s` import,
maps each imported symbol to the module(s) that export it, and
refuses any import from a module in a HIGHER layer than the
importer.

Layers are read from doc/architecture.md, never hard-coded:

  * the `## Modules` table (`| main.s | 5 | ...`; a cell such as
    `mn7.s / mn6.s` names several modules);
  * the `Generated files` table that follows it — generated sources
    are pure data, so they take layer 0 (the diagram's "L0 ... pure
    data" row lists `*_tables`, `oplen_tbl`, `dasm_mne_idx`).

Symbols no src file exports (linker-defined `__CODE_RUN__` and
friends) are ignored.  A module with imports but no layer is a
finding too (the table must cover every module).

Run:

    python3 dev/check_deps.py          # exit 1 on any finding
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _directive_syms(text, kinds):
    """Symbols named on `.<kind>` lines of an assembly source (line
    comments stripped; `sym: absolute = 1` and `sym := x` forms
    reduce to `sym`)."""
    pat = re.compile(r"^\s*\.(%s)\s+(.+)$" % "|".join(kinds), re.I)
    out = set()
    for line in text.splitlines():
        m = pat.match(line.split(";", 1)[0])
        if not m:
            continue
        for part in m.group(2).split(","):
            name = re.match(r"\s*([A-Za-z_]\w*)", part)
            if name:
                out.add(name.group(1))
    return out


def imports_of(text):
    return _directive_syms(text, ["import", "importzp", "global", "globalzp"])


def exports_of(text):
    return _directive_syms(text, ["export", "exportzp", "global", "globalzp"])


def scan(src_dir):
    """{module: (imports, exports)} for every src/*.s."""
    return {p.stem: (imports_of(p.read_text()), exports_of(p.read_text()))
            for p in sorted(pathlib.Path(src_dir).glob("*.s"))}


def providers(mods):
    """{symbol: {modules exporting it}} (mn6/mn7 both export theirs)."""
    prov = {}
    for mod, (_, exps) in mods.items():
        for s in exps:
            prov.setdefault(s, set()).add(mod)
    return prov


def module_edges(mods):
    """{importer: {provider module: sorted symbols}}, self-edges dropped."""
    prov = providers(mods)
    edges = {}
    for mod, (imps, _) in mods.items():
        for s in sorted(imps):
            for p in prov.get(s, ()):
                if p != mod:
                    edges.setdefault(mod, {}).setdefault(p, []).append(s)
    return edges


def _section(text, heading):
    m = re.search(r"^## %s\s*$" % re.escape(heading), text, re.M)
    if not m:
        return ""
    rest = text[m.end():]
    nxt = re.search(r"^## ", rest, re.M)
    return rest[:nxt.start()] if nxt else rest


def parse_layers(arch_text):
    """{module: layer} from architecture.md's Modules section."""
    sec = _section(arch_text, "Modules")
    layers = {}
    for line in sec.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        files = re.findall(r"([A-Za-z_]\w*)\.s\b", cells[0])
        if not files:
            continue
        if re.fullmatch(r"\d+", cells[1]):          # Modules table
            for f in files:
                layers[f] = int(cells[1])
        elif "generator" in sec.lower() and "dev/" in cells[1]:
            for f in files:                         # Generated files table
                layers.setdefault(f, 0)
    return layers


def check(src_dir, arch_path):
    """Findings: list of strings, empty when clean."""
    mods = scan(src_dir)
    layers = parse_layers(pathlib.Path(arch_path).read_text())
    findings = []
    for mod, deps in sorted(module_edges(mods).items()):
        if mod not in layers:
            findings.append(f"{mod}.s: no layer in architecture.md § Modules")
            continue
        for dep, syms in sorted(deps.items()):
            if dep not in layers:
                findings.append(f"{dep}.s: no layer in architecture.md § Modules "
                                f"(imported by {mod}.s)")
            elif layers[dep] > layers[mod]:
                findings.append(
                    f"{mod}.s (L{layers[mod]}) imports from {dep}.s "
                    f"(L{layers[dep]}): {', '.join(syms)}")
    return findings


def main():
    findings = check(ROOT / "src", ROOT / "doc" / "architecture.md")
    if not findings:
        print("✓ Every import resolves to the same or a lower layer.")
        return 0
    print(f"✗ {len(findings)} layer findings:")
    for f in findings:
        print("   " + f)
    return 1


if __name__ == "__main__":
    sys.exit(main())
