#!/usr/bin/env python3
"""audit_platform_literals.py — no platform literal outside the seams.

Owner: doc/platform_layer.md

Contract source: [platform_layer.md § The rule](../doc/platform_layer.md#the-rule)
and § Gates.

A platform fact lives in `src/platform.inc` (a constant or a macro) or
inside a `.ifdef PLATFORM_<platform>` block.  This audit finds the
*address literals* that name one anywhere else in `src/*.s`,
`src/*.inc` and `src/*.cfg.in`:

  rom      $E000–$FFFF  ROM entries and internals, the banked homes,
                        the vector shadows
  io       $D000–$DFFF  VIC, SID, CIA, colour RAM, HIMEM
  screen   $0400–$07FF  screen RAM
  page23   $0200–$03FF  KERNAL variables and vectors in pages 2–3
  basic    $0800, $0801, $A000–$BFFF  workstart, the BASIC start, BASIC
  zpcell   $00, $01, $90, $91, $C6, $CC, $CE, $D1–$D6, $D8, $F3, $F4,
           $FB–$FE as a base-page operand or an equate's value (the CPU
           port and the KERNAL's cells); not as an immediate

A literal is a `$`-hex number.  Not counted: comments, `.byte` data,
2-digit immediates (`#$xx`, values, not addresses), the generated
table sources, `src/platform.inc`, `src/m45_ops.inc`, and a file named
for its platform (`c64_cse.cfg.in`, `m65_cse.cfg.in`): such a file is
itself a platform block.  A use of a name (`jsr CHROUT`) is not a
literal; the name's definition is.

While the C64 build moves onto the seams the audit is a ratchet:
`tests/fixtures/platform_literals_baseline.json` holds each file's
exact count, and test_platform_audit.py fails when a count differs —
higher (a new site) or lower (a moved site whose baseline was not
lowered).  When every count is zero the fixture is deleted.

    python3 dev/audit_platform_literals.py            # per-file counts
    python3 dev/audit_platform_literals.py --sites    # every site
    python3 dev/audit_platform_literals.py --write-baseline

Beside it, the base-page check: no absolute-mode access to a CSE
base-page symbol, nor a pointer to one, unless written BP_ABS(sym)
(platform_layer.md § Base page).  It asserts zero from the start.
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
BASELINE = ROOT / "tests" / "fixtures" / "platform_literals_baseline.json"

EXEMPT = {"platform.inc", "m45_ops.inc", "mn6_tables.s", "mn7_tables.s",
          "mn_asm_tables.s", "mn_modes.s", "oplen_tbl.s", "dasm_tables.s",
          "dasm_mne_idx.s"}
ZPCELLS = {0x00, 0x01, 0x90, 0x91, 0xC6, 0xCC, 0xCE, 0xD1, 0xD2, 0xD3,
           0xD4, 0xD5, 0xD6, 0xD8, 0xF3, 0xF4, 0xFB, 0xFC, 0xFD, 0xFE}

_HEX = re.compile(r"(#[<>]?)?\$([0-9A-Fa-f]+)\b")
_IFDEF = re.compile(r"^\s*\.ifn?def\s+(\w+)", re.I)
_IF = re.compile(r"^\s*\.if", re.I)
_ENDIF = re.compile(r"^\s*\.endif\b", re.I)
_BYTE = re.compile(r"^\s*(?:[@\w]+:)?\s*\.(byte|res)\b", re.I)
_EQUATE = re.compile(r"^\s*\w+\s*=\s*")


def strip_comment(line):
    """`line` without its `;` comment (a `;` inside quotes is text)."""
    out, quote = [], None
    for ch in line:
        if quote:
            out.append(ch)
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == ";":
            break
        else:
            out.append(ch)
    return "".join(out)


def classify(value, digits, immediate, equate):
    """The literal class of `$value` written with `digits` hex digits,
    or None."""
    if digits >= 4:
        if 0xE000 <= value <= 0xFFFF:
            return "rom"
        if 0xD000 <= value <= 0xDFFF:
            return "io"
        if 0x0400 <= value <= 0x07FF:
            return "screen"
        if 0x0200 <= value <= 0x03FF:
            return "page23"
        if value in (0x0800, 0x0801) or 0xA000 <= value <= 0xBFFF:
            return "basic"
        return None
    if digits <= 2 and not immediate and value in ZPCELLS:
        return "zpcell"
    return None


def sites(path):
    """[(line number, class, text)] of the platform literals in `path`
    outside `.ifdef PLATFORM_*` blocks."""
    out, stack = [], []                 # stack: True = a PLATFORM_ block
    is_cfg = path.name.endswith(".cfg.in")
    for n, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        line = raw.split("#", 1)[0] if is_cfg else strip_comment(raw)
        m = _IFDEF.match(line)
        if m:
            stack.append(m.group(1).upper().startswith("PLATFORM_"))
            continue
        if _IF.match(line):
            stack.append(False)
            continue
        if _ENDIF.match(line):
            if stack:
                stack.pop()
            continue
        if any(stack) or (not is_cfg and _BYTE.match(line)):
            continue
        equate = bool(_EQUATE.match(line))
        for hm in _HEX.finditer(line):
            digits = hm.group(2)
            cls = classify(int(digits, 16), len(digits), bool(hm.group(1)),
                           equate)
            if cls:
                out.append((n, cls, raw.strip()))
    return out


PLATFORM_PREFIXES = ("c64_", "m65_", "c128_")


def audited_files(src=SRC):
    files = sorted(list(src.glob("*.s")) + list(src.glob("*.inc"))
                   + list(src.glob("*.cfg.in")))
    return [f for f in files if f.name not in EXEMPT
            and not f.name.startswith(PLATFORM_PREFIXES)]


def counts(src=SRC):
    """{file name: number of sites}, files with sites only."""
    out = {}
    for f in audited_files(src):
        n = len(sites(f))
        if n:
            out[f.name] = n
    return out


# ── The base-page check (platform_layer.md § Base page) ──────────────
# An access to a CSE base-page symbol in an absolute mode, or a 16-bit
# pointer to one, is written BP_ABS(sym): on m65 CSE's zero page is the
# page CSE_BP, which an absolute address reaches only with that page.

_INSN = re.compile(r"^\s*(?:[@\w]+:)?\s*([A-Za-z]{3})\s+(.+?)\s*$")
_ALIAS = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*([A-Za-z_]\w*)\b")
_WORD = re.compile(r"^\s*(?:[@\w]+:)?\s*\.(?:word|addr)\s+(.*)$", re.I)
_ID = r"([A-Za-z_]\w*)"


def base_page_symbols(src=SRC):
    """zp.s's exported symbols and every module's aliases of them."""
    names = set()
    for line in (src / "zp.s").read_text().splitlines():
        m = re.match(r"\s*\.exportzp\s+(.*)", strip_comment(line))
        if m:
            names |= {n.strip() for n in m.group(1).split(",") if n.strip()}
    grew = True
    while grew:
        grew = False
        for f in src.glob("*.s"):
            for line in f.read_text(errors="replace").splitlines():
                m = _ALIAS.match(strip_comment(line))
                if m and m.group(2) in names and m.group(1) not in names:
                    names.add(m.group(1))
                    grew = True
    return names


def base_page_sites(path, names):
    """[(line number, text)] of absolute-mode uses of a base-page symbol
    not written BP_ABS(sym): `jmp (sym)`, `op sym,y` (no zero-page,y
    form except LDX / STX), `#<sym` / `#>sym`, `.word sym`."""
    out = []
    for n, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        line = strip_comment(raw)
        if "BP_ABS(" in line:
            continue
        hit = False
        m = _WORD.match(line)
        if m:
            hit = any(re.match(_ID, a.strip()) and
                      re.match(_ID, a.strip()).group(1) in names
                      for a in m.group(1).split(","))
        m = _INSN.match(line)
        if m and not hit:
            op, arg = m.group(1).lower(), m.group(2)
            for pat in (r"^#[<>]\s*" + _ID, r"^\(\s*" + _ID + r"[^,]*\)\s*$"):
                mm = re.match(pat, arg)
                if mm and mm.group(1) in names and (pat[1] == "#" or op == "jmp"):
                    hit = True
            mm = re.match(_ID + r"[^,(]*,\s*[yY]\s*$", arg)
            if mm and mm.group(1) in names and op not in ("ldx", "stx"):
                hit = True
        if hit:
            out.append((n, raw.strip()))
    return out


def base_page_count(src=SRC):
    names = base_page_symbols(src)
    return {f.name: len(s) for f in sorted(src.glob("*.s"))
            if f.name != "zp.s" and (s := base_page_sites(f, names))}


def main(argv):
    if "--write-baseline" in argv:
        BASELINE.write_text(json.dumps(
            {"comment": "The literal audit's ratchet: each file's exact count "
                        "of platform literals not yet moved onto the seams "
                        "(doc/platform_layer.md § Gates).  Lowered by every "
                        "seam's commit; deleted when empty.",
             "counts": counts()}, indent=1, sort_keys=True) + "\n")
        print(f"wrote {BASELINE.relative_to(ROOT)}")
        return 0
    total = 0
    for f in audited_files():
        found = sites(f)
        total += len(found)
        if found:
            print(f"{f.name:24s} {len(found):4d}")
            if "--sites" in argv:
                for n, cls, text in found:
                    print(f"    {n:5d} {cls:7s} {text[:70]}")
    print(f"{'total':24s} {total:4d}")
    names = base_page_symbols()
    for f in sorted(SRC.glob("*.s")):
        for n, text in ([] if f.name == "zp.s" else base_page_sites(f, names)):
            print(f"base page: {f.name}:{n}: {text[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
