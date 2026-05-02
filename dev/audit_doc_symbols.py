"""Audit backticked symbols in docs against the binary — Step 1B.

For each `\\w+` in backticks across doc/, root README.md, root
background.md, check whether it looks like a CSE source symbol
(identifier with at least one underscore, not a standard 6502/CPU
token).  If so, verify it's defined somewhere — either as a
project source symbol (in `cse.lbl`) or as a project source
identifier (defined via `.export` / `.exportzp` / `:= ` / `= ` in
`src/**/*.s`, including `.proc` labels and standalone `name:`).

The "underscore" filter is the heuristic for "this is almost
certainly a project-specific code symbol, not an English word."
It catches `kernal_bank_in`, `_dasm_buf`, `cmd_jmp`, etc., while
correctly skipping `BRK`, `JMP`, English prose, hex values, and
filenames.

Run:

    /Users/cr/.local/share/virtualenvs/cse-rXGMsE9U/bin/python \\
        dev/audit_doc_symbols.py

Output: list of (file:line, claimed-symbol) for symbols not found.
"""

import re
import sys
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent

LBL_PATH = ROOT / "build" / "debug" / "cmos" / "cse.lbl"
SRC_DIR  = ROOT / "src"

# Backticked single-token candidates.  We require at least one
# underscore as the heuristic for "looks like a code symbol."
BACKTICK_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")

# Tokens we never flag even if they have underscores — these are
# context-dependent (Python module names, build-system identifiers,
# C macro names that aren't in the binary, etc.).
ALLOWLIST_NEVER_FLAG = {
    # Python module names that show up in test prose
    "py65", "pytest", "pytest_param",
    # Build-system / make variables
    "MAKEFLAGS", "ASM_SRCS", "C_SRCS", "TABLE_OUTS",
    # Doc-side symbolic references we use as labels
    "this_module", "module_name",
    # Standard CSE constants whose names are checked elsewhere
    "ZP_SAVE_LO", "ZP_SAVE_LEN",
    # KERNAL ROM symbols / well-known C64 system labels.  CSE
    # references but does not define these — they're an ABI we use,
    # not a corpus we own.
    "KERNAL_VECTOR", "KERNAL_RESTOR",
    # Conceptual handler names (doc-shorthand).  REPL command
    # handlers live as local labels (`@h_g`, `@h_c`, etc.) inside
    # the cmd_chars dispatch table; the docs sensibly refer to
    # them by conceptual name.  Not strictly verifiable by symbol
    # lookup but the audit shouldn't flag them.
    "cmd_continue", "cmd_quit", "cmd_reset",
    "cmd_load", "cmd_save", "cmd_dir",
    "cmd_inspect", "cmd_memory", "cmd_dasm",
    "cmd_calc", "cmd_block", "cmd_blip",
    "cmd_ks", "cmd_kill", "cmd_color",
    # Cold-init entry conceptually called cse_cold_init, actual
    # symbol is `_main` (a layered procedure inside _main).
    "cse_cold_init",
}


def load_binary_symbols():
    """Read cse.lbl, return set of symbol names (without leading '.')."""
    if not LBL_PATH.exists():
        return None
    syms = set()
    for line in LBL_PATH.read_text().splitlines():
        # Format:  al 00ABCD .symbol_name
        m = re.match(r"al\s+[0-9A-Fa-f]+\s+\.(\S+)\s*$", line)
        if m:
            syms.add(m.group(1))
            # Some symbols include scope: outer.inner — admit both.
            parts = m.group(1).split(".")
            for p in parts:
                if p:
                    syms.add(p)
    return syms


def load_source_identifiers():
    """Identifiers visible to ca65 in src/ but not necessarily exported.

    Picks up:
      - .proc NAME
      - NAME:  (label at column 1)
      - NAME = expr / NAME := expr
      - .export NAME, .exportzp NAME, .import NAME, .importzp NAME,
        .global NAME
      - .define NAME ...

    Walks both `*.s` and `*.inc` files in src/ and dev/.
    """
    ids = set()
    for d in (SRC_DIR, ROOT / "dev"):
        if not d.exists():
            continue
        for ext in ("*.s", "*.inc"):
            for f in d.rglob(ext):
                try:
                    text = f.read_text()
                except (OSError, UnicodeDecodeError):
                    continue
                for line in text.splitlines():
                    stripped = line.strip()
                    code = stripped.split(";", 1)[0].strip()
                    if not code:
                        continue
                    # .proc NAME
                    m = re.match(r"\.proc\s+(\w+)", code, re.IGNORECASE)
                    if m:
                        ids.add(m.group(1))
                        continue
                    # .define NAME ...
                    m = re.match(r"\.define\s+(\w+)", code, re.IGNORECASE)
                    if m:
                        ids.add(m.group(1))
                        continue
                    # .export / .exportzp / .import / .importzp / .global
                    m = re.match(
                        r"\.(?:export|import|global)(?:zp)?\s+(.+)$",
                        code, re.IGNORECASE)
                    if m:
                        for tok in re.findall(r"\b[A-Za-z_]\w*", m.group(1)):
                            ids.add(tok)
                        continue
                    # NAME: at start
                    m = re.match(r"([A-Za-z_]\w*)\s*:", code)
                    if m:
                        ids.add(m.group(1))
                    # NAME = expr  or  NAME := expr
                    m = re.match(r"([A-Za-z_]\w*)\s*:?=", code)
                    if m:
                        ids.add(m.group(1))
    return ids


def load_build_time_macros():
    """Constants defined via -D flags in the Makefile (CMOS_SUPPORT,
    CPU_CEIL, THEME_*, USE_MN6, etc.).  Conservative: any token that
    appears after `-D` in any Makefile assignment."""
    macros = set()
    mk = ROOT / "Makefile"
    if not mk.exists():
        return macros
    try:
        for line in mk.read_text().splitlines():
            for m in re.finditer(r"-D\s*([A-Za-z_]\w*)", line):
                macros.add(m.group(1))
    except (OSError, UnicodeDecodeError):
        pass
    # Conventional build-time constants always considered known.
    macros |= {
        "CMOS_SUPPORT", "CPU_6502", "CPU_6510", "CPU_65C02",
        "CPU_CEIL", "USE_MN6",
        "THEME_BOR", "THEME_BG", "THEME_FG",
        "DEBUG", "NDEBUG", "RELEASE",
    }
    return macros


def load_module_filenames():
    """Names of source modules (asm_src, asm_line, etc.).  Doc text
    legitimately refers to these as `asm_src` to mean "the module"
    even when there's no symbol of that name in the binary."""
    names = set()
    for f in SRC_DIR.rglob("*.s"):
        names.add(f.stem)
    for f in (ROOT / "doc" / "modules").glob("*.md"):
        names.add(f.stem)
    return names


def all_md_files():
    files = [ROOT / "README.md", ROOT / "background.md"]
    files.extend((ROOT / "doc").rglob("*.md"))
    return [
        f for f in files
        if f.is_file() and ".claude" not in f.parts and "build" not in f.parts
    ]


# Files where every backticked symbol must be currently defined.
# Other docs (ddd_log, optimization, TODO, glossary, project) include
# historical references, proposed names, retired terminology — the
# audit can't distinguish those from genuine drift, so we exclude them.
STRICT_SPEC_GLOB = ("README.md", "doc/modules/*.md")


def is_strict_spec(path):
    rel = path.relative_to(ROOT).as_posix()
    if rel == "README.md":
        return True
    if rel.startswith("doc/modules/") and rel.endswith(".md"):
        return True
    return False


def load_python_names():
    """Pick up Python def / class names from tests/, dev/.  Some
    docs reference test helpers like `_cold_init_to_prompt`."""
    names = set()
    for d in (ROOT / "tests", ROOT / "dev"):
        if not d.exists():
            continue
        for f in d.rglob("*.py"):
            try:
                text = f.read_text()
            except (OSError, UnicodeDecodeError):
                continue
            for m in re.finditer(
                    r"^(?:def|class)\s+([A-Za-z_]\w*)",
                    text, re.MULTILINE):
                names.add(m.group(1))
    return names


def is_likely_code_symbol(token):
    """True if `token` looks like a CSE code symbol (not English)."""
    if "_" not in token:
        return False
    if token in ALLOWLIST_NEVER_FLAG:
        return False
    # Drop very common English-with-underscore: e.g. "kernel_init_"...
    # actually those ARE code symbols.  Don't filter on common stems.
    return True


def main():
    bin_syms = load_binary_symbols()
    if bin_syms is None:
        print(f"Error: {LBL_PATH} not found — run `make debug` first")
        return 2
    src_ids = load_source_identifiers()
    macros = load_build_time_macros()
    modules = load_module_filenames()
    py_names = load_python_names()
    all_known = bin_syms | src_ids | macros | modules | py_names

    print(f"Loaded {len(bin_syms)} binary symbols, "
          f"{len(src_ids)} source identifiers, "
          f"{len(macros)} build macros, "
          f"{len(modules)} module names, "
          f"{len(py_names)} python defs; "
          f"{len(all_known)} unique known names.")
    print()

    files = [f for f in all_md_files() if is_strict_spec(f)]
    findings_by_token = defaultdict(list)
    n_candidates = 0
    for f in files:
        try:
            text = f.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        in_fence = False
        for lineno, line in enumerate(text.splitlines(), start=1):
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            for m in BACKTICK_RE.finditer(line):
                token = m.group(1)
                if not is_likely_code_symbol(token):
                    continue
                n_candidates += 1
                if token not in all_known:
                    findings_by_token[token].append(
                        (f.relative_to(ROOT), lineno))

    print(f"Scanned {len(files)} strict-spec files "
          f"(README.md + doc/modules/*.md), "
          f"{n_candidates} backticked candidates with `_`.")
    print()

    if not findings_by_token:
        print("✓ All backticked code-symbol candidates resolve.")
        return 0

    print(f"✗ {len(findings_by_token)} unique names not found, "
          f"{sum(len(v) for v in findings_by_token.values())} sites:")
    print()
    # Sort by usage count descending (most-mentioned first).
    by_count = sorted(findings_by_token.items(),
                      key=lambda kv: (-len(kv[1]), kv[0]))
    for token, sites in by_count:
        # Show first 3 sites, summarize the rest.
        head = sites[:3]
        rest = len(sites) - len(head)
        print(f"   `{token}`  ({len(sites)} site{'s' if len(sites)>1 else ''})")
        for f, ln in head:
            print(f"     {f}:{ln}")
        if rest:
            print(f"     ... and {rest} more")
    return 1


if __name__ == "__main__":
    sys.exit(main())
