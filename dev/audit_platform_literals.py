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

test_platform_audit.py asserts that no file has a site.  (While the
C64 build moved onto the seams it was a ratchet against a recorded
baseline; the last seam emptied it.)

    python3 dev/audit_platform_literals.py            # per-file counts
    python3 dev/audit_platform_literals.py --sites    # every site

Beside it, the base-page check: no absolute-mode access to a CSE
base-page symbol, nor a pointer to one, unless written BP_ABS(sym)
(platform_layer.md § Base page).  It asserts zero from the start.

The raw-byte audit: outside src/m45_ops.inc, every `.byte` in an
opcode position starts with a literal 6502 opcode
(platform_layer.md § Raw-byte instructions).  Zero from the start.

The KERNAL-call check: no bare `jsr` / `jmp` to a KERNAL jump-table
entry outside platform.inc and loader.s — every call is a KCALL / KJMP
(platform_layer.md § KERNAL calls).  Zero from the start.

The pending-body count: the PLAT_PENDING sites per milestone (platform_layer.md § Pending bodies), held by the test
to a recorded count that only goes down.

And the stack-top check: no literal `#$FF` put in SP or `reg_sp`; the
stack top is STACK_TOP (platform_layer.md § Stack).  Zero from the
start.
"""
import functools
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

EXEMPT = {"platform.inc", "m45_ops.inc", "mn6_tables.s", "mn7_tables.s",
          "mn_asm_tables.s", "mn_modes.s", "oplen_tbl.s", "dasm_tables.s",
          "dasm_mne_idx.s", "cpu_set.inc"}
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


def classify(value, digits, immediate):
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
        for hm in _HEX.finditer(line):
            digits = hm.group(2)
            cls = classify(int(digits, 16), len(digits), bool(hm.group(1)))
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


_OP = re.compile(r"^\s*(?:[@\w]+:)?\s*([A-Za-z]{3})\b\s*(.*?)\s*$")


def stack_top_sites(path):
    """[(line number, text)] of a literal `#$FF` loaded and then put in
    SP (`txs`) or stored to `reg_sp` by the next instruction — the
    stack top is STACK_TOP (platform_layer.md § Stack)."""
    out, prev = [], None
    for n, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        m = _OP.match(strip_comment(raw))
        if not m or raw.lstrip().startswith("."):
            continue
        op, arg = m.group(1).lower(), m.group(2)
        if prev and (op == "txs" and prev[1] == "x" or
                     op[:2] == "st" and op[2] == prev[1] and arg == "reg_sp"):
            out.append(prev[0])
        prev = None
        if op[:2] == "ld" and op[2] in "axy" and arg.upper() == "#$FF":
            prev = ((n, raw.strip()), op[2])
    return out


def stack_top_count(src=SRC):
    return {f.name: len(s) for f in sorted(src.glob("*.s"))
            if (s := stack_top_sites(f))}


# ── the raw-byte audit (platform_layer.md § Raw-byte instructions) ──

_EXEC_SEGMENTS = {None, "CODE", "LOADER", "STUB"}
_SEG_DIRECTIVES = {".code": "CODE", ".rodata": "RODATA", ".data": "DATA",
                   ".bss": "BSS", ".zeropage": "ZEROPAGE"}
_DATA = {".byte", ".byt", ".word", ".addr", ".dbyt", ".dword", ".faraddr",
         ".res", ".asciiz", ".lobytes", ".hibytes", ".bankbytes", ".incbin"}
_TRANSFERS = {"rts": "stop", "rti": "stop", "jmp": "stop", "brk": "sig"}
_LABEL = re.compile(r"^\s*@?\w+:")


@functools.lru_cache(maxsize=None)
def opcodes_6502():
    """The 6502's opcodes, from dev/instruction_set.py's 6502 rows."""
    sys.path.insert(0, str(ROOT / "dev"))
    try:
        import instruction_set
    finally:
        sys.path.pop(0)
    return frozenset(r.opcode for r in instruction_set.instructions("6502"))


def _literal(text):
    """The value of a literal byte expression, or None for any other."""
    text = text.strip()
    for pat, conv in ((r"\$([0-9A-Fa-f]+)", lambda m: int(m, 16)),
                      (r"%([01]+)", lambda m: int(m, 2)),
                      (r"([0-9]+)", int),
                      (r"'(.)'", ord)):
        m = re.fullmatch(pat, text)
        if m:
            return conv(m.group(1))
    return None


def raw_byte_sites(path):
    """[(line number, text)] of a `.byte` in an opcode position whose
    first value is not a literal 6502 opcode.  An opcode position is a
    `.byte` in an executable segment or a macro body right after an
    instruction that can fall through (labels between do not count);
    after `brk` it is a signature byte, after a transfer or data it is
    data.  A macro defined above in the file counts as what its body
    ends with (data for a table-building macro); any other macro as an
    instruction that falls through."""
    out, seg, saved, prev = [], None, None, None
    macros, defining = {}, None
    ops = opcodes_6502()
    for n, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        line = strip_comment(raw)
        while _LABEL.match(line):
            line = _LABEL.sub("", line, count=1)
        line = line.strip()
        if not line or _EQUATE.match(line):
            continue
        word = line.split(None, 1)[0].lower()
        rest = line[len(word):].strip()
        if word == ".segment":
            seg, prev = rest.strip('"'), None
        elif word in _SEG_DIRECTIVES:
            seg, prev = _SEG_DIRECTIVES[word], None
        elif word in (".macro", ".mac"):
            saved, seg, prev = seg, None, None
            defining = rest.split()[0].lower() if rest else None
        elif word in (".endmacro", ".endmac"):
            if defining:
                macros[defining] = prev
            seg, prev, defining = saved, None, None
        elif word in _DATA:
            if word in (".byte", ".byt") and prev == "fall" and seg in _EXEC_SEGMENTS:
                if _literal(rest.split(",")[0]) not in ops:
                    out.append((n, raw.strip()))
            prev = "data"
        elif word.startswith("."):
            continue                        # .if, .proc, .export, ...: transparent
        elif word in macros:
            prev = macros[word] or "fall"
        else:
            prev = _TRANSFERS.get(word, "fall")
    return out


def raw_byte_count(src=SRC):
    files = sorted(list(src.glob("*.s")) + list(src.glob("*.inc")))
    return {f.name: len(s) for f in files
            if f.name != "m45_ops.inc" and (s := raw_byte_sites(f))}


# ── the KERNAL-call check (platform_layer.md § KERNAL calls) ────────
# Every call of a KERNAL jump-table entry is a KCALL / KJMP: a bare
# `jsr` or `jmp` to one would run the entry with B = CSE_BP on m65.
# The entries are the $FFxx names platform.inc defines (every platform
# block; the page base itself has low byte 0 and is not an entry).
# loader.s is exempt: both its bodies run before CSE's base page
# exists, with B = 0.

_KERNAL_ENTRY = re.compile(r"^\s*(\w+)\s*=\s*\$(FF[0-9A-Fa-f]{2})\b")
KERNAL_CALL_EXEMPT = {"platform.inc", "loader.s"}


def kernal_entries(src=SRC):
    """The names of the KERNAL jump-table entries platform.inc defines."""
    names = set()
    for line in (src / "platform.inc").read_text().splitlines():
        m = _KERNAL_ENTRY.match(strip_comment(line))
        if m and int(m.group(2), 16) & 0xFF:
            names.add(m.group(1))
    return names


def kernal_call_sites(path, entries):
    """[(line number, text)] of a bare `jsr` / `jmp` to a KERNAL entry."""
    pat = re.compile(r"^\s*(?:[@\w]+:)?\s*(?:jsr|jmp)\s+(\w+)\s*$", re.I)
    out = []
    for n, raw in enumerate(path.read_text(errors="replace").splitlines(), 1):
        m = pat.match(strip_comment(raw))
        if m and m.group(1) in entries:
            out.append((n, raw.strip()))
    return out


def kernal_call_count(src=SRC):
    entries = kernal_entries(src)
    return {f.name: len(s) for f in sorted(src.glob("*.s"))
            if f.name not in KERNAL_CALL_EXEMPT
            and (s := kernal_call_sites(f, entries))}


# ── the pending-body count (platform_layer.md § Pending bodies) ─────

_PENDING = re.compile(r"^\s*(?:[@\w]+:)?\s*PLAT_PENDING\s+(\d+)\s*$")


def pending_counts(src=SRC):
    """{milestone: the number of PLAT_PENDING sites}, over src/*.s and src/*.inc (a site in a macro body counts
    once)."""
    counts = {}
    for f in sorted(list(src.glob("*.s")) + list(src.glob("*.inc"))):
        for raw in f.read_text(errors="replace").splitlines():
            m = _PENDING.match(strip_comment(raw))
            if m:
                n = int(m.group(1))
                counts[n] = counts.get(n, 0) + 1
    return counts


def main(argv):
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
        for n, text in stack_top_sites(f):
            print(f"stack top: {f.name}:{n}: {text[:60]}")
    for name in kernal_call_count():
        for n, text in kernal_call_sites(SRC / name, kernal_entries()):
            print(f"bare KERNAL call: {name}:{n}: {text[:60]}")
    for n, c in sorted(pending_counts().items()):
        print(f"pending P{n}: {c}")
    for name in raw_byte_count():
        for n, text in raw_byte_sites(SRC / name):
            print(f"raw byte: {name}:{n}: {text[:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
