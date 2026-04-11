#!/usr/bin/env python3
"""
dev/size_report.py — Exhaustive size breakdown of cse.prg

Reads the ld65 map file and debug file to produce:
  1. C64 memory map (like the `i` command)
  2. Per-segment sizes
  3. Per-module breakdown within each segment
  4. Functional category breakdown
"""

import re
import sys
import os

ROOT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD = os.environ.get("BUILD", os.path.join(ROOT, "build", "6510"))
MAP   = os.path.join(BUILD, "cse.map")
DBG   = os.path.join(BUILD, "cse.dbg")
PRG   = os.path.join(BUILD, "cse.prg")

if not os.path.exists(MAP):
    print("ERROR: build/cse.map not found. Run: make clean && make", file=sys.stderr)
    sys.exit(1)

# ── Parse segments from debug file ───────────────────────────────
segments = {}
with open(DBG) as f:
    for line in f:
        m = re.match(r'seg\s+id=(\d+),name="(\w+)",start=(0x[0-9a-fA-F]+),size=(0x[0-9a-fA-F]+)', line)
        if m:
            segments[m.group(2)] = {
                'start': int(m.group(3), 16),
                'size':  int(m.group(4), 16),
            }

# ── Parse per-module contributions from map file ─────────────────
modules = {}  # module_name → {segment_name: size}
map_text = open(MAP).read()

# Module list section: each module has indented segment lines
in_modules = False
current_mod = None
for line in map_text.splitlines():
    if line.startswith("Modules list"):
        in_modules = True
        continue
    if in_modules:
        if line.startswith("Segment list") or line.startswith("Exports list"):
            break
        # Module header: "name.o:" or "/path/to/lib(name.o):"
        m = re.match(r"(?:.*/)?(\S+\.o)\)?:", line)
        if m:
            mod_name = m.group(1)
            # For library modules: lib(foo.o) → extract foo.o
            m2 = re.search(r'\((\w+\.o)\)', line)
            if m2:
                mod_name = m2.group(1)
            current_mod = mod_name
            if current_mod not in modules:
                modules[current_mod] = {}
            continue
        # Segment contribution: "    SEGNAME  Offs=XXXX  Size=XXXX"
        m = re.match(r"\s+(\w+)\s+Offs=([0-9a-fA-F]+)\s+Size=([0-9a-fA-F]+)", line)
        if m and current_mod:
            seg_name = m.group(1)
            size = int(m.group(3), 16)
            modules[current_mod][seg_name] = modules[current_mod].get(seg_name, 0) + size

# ── Categorize modules ───────────────────────────────────────────
CORE_MODULES = {'main.o', 'repl.o', 'editor.o', 'screen.o', 'disk.o', 'debugger.o'}
ASM_MODULES = {
    'asm_line.o', 'asm_vars.o', 'asm_src.o', 'mn_vars.o',
    'mn_classify.o', 'mn7.o', 'mn7_tables.o', 'mn6.o', 'mn6_tables.o',
    'mn_config.o', 'au_mode.o', 'mn_modes.o',
    'mn_asm_tables.o', 'opcode_lookup.o', 'expr.o', 'symtab.o',
}
DASM_MODULES = {'dasm.o', 'dasm_tables.o'}
IO_MODULES = {'cse_io.o', 'meminfo.o'}

def categorize(mod_name):
    if mod_name in CORE_MODULES:
        return 'core'
    if mod_name in ASM_MODULES:
        return 'assembler'
    if mod_name in DASM_MODULES:
        return 'disassembler'
    if mod_name in IO_MODULES:
        return 'cse-io'
    return 'other'

# ── PRG file size ────────────────────────────────────────────────
prg_size = os.path.getsize(PRG)
prg_blocks = (prg_size + 253) // 254

# ── Output ───────────────────────────────────────────────────────
W = 60

print("=" * W)
print(f"  CSE Size Report — {prg_size} bytes ({prg_blocks} blocks)")
print("=" * W)

# Memory map
print(f"\n{'─'*W}")
print("  C64 Memory Map")
print(f"{'─'*W}")

regions = []
for name, s in sorted(segments.items(), key=lambda x: x[1]['start']):
    if s['size'] == 0:
        continue
    end = s['start'] + s['size'] - 1
    regions.append((s['start'], end, name, s['size']))

# Add system regions
sys_regions = [
    (0x0000, 0x0001, 'cpu-port', 2),
    (0x0100, 0x01FF, '6502-stack', 256),
    (0x0400, 0x07E7, 'screen', 1000),
    (0xD000, 0xDFFF, 'i/o', 4096),
    (0xE000, 0xFFFF, 'kernal-rom', 8192),
]

all_regions = regions + sys_regions
all_regions.sort(key=lambda x: x[0])

# Find free gaps
covered = set()
for start, end, _, _ in all_regions:
    for a in range(start, end + 1):
        covered.add(a)

prev_end = -1
output_regions = []
for start, end, name, size in all_regions:
    if start > prev_end + 1 and prev_end >= 0:
        gap_start = prev_end + 1
        gap_size = start - gap_start
        if gap_size > 0 and gap_start >= 0x0002:
            output_regions.append((gap_start, start - 1, '** FREE **', gap_size, True))
    output_regions.append((start, end, name, size, False))
    prev_end = max(prev_end, end)

for start, end, name, size, is_free in output_regions:
    marker = '>>>' if is_free else '   '
    print(f"  {marker} ${start:04X}-${end:04X}  {size:5d}  {name}")

# Segment summary
print(f"\n{'─'*W}")
print("  Segment Summary")
print(f"{'─'*W}")
print(f"  {'Segment':<12s} {'Start':>6s} {'End':>6s} {'Size':>6s} {'Bytes':>6s}")
print(f"  {'─'*12} {'─'*6} {'─'*6} {'─'*6} {'─'*6}")
total_rom = 0
total_ram = 0
for name in ['LOADADDR','EXEHDR','STARTUP','CODE','RODATA','DATA','INIT','ONCE','BSS','ZEROPAGE']:
    if name not in segments:
        continue
    s = segments[name]
    if s['size'] == 0:
        continue
    end = s['start'] + s['size'] - 1
    kind = 'ram' if name in ('BSS', 'ZEROPAGE') else 'rom'
    if kind == 'rom':
        total_rom += s['size']
    else:
        total_ram += s['size']
    print(f"  {name:<12s} ${s['start']:04X}   ${end:04X}   {s['size']:#06x} {s['size']:5d}")
print(f"  {'─'*12} {'─'*6} {'─'*6} {'─'*6} {'─'*6}")
print(f"  {'PRG (rom)':<12s} {'':>6s} {'':>6s} {total_rom:#06x} {total_rom:5d}")
print(f"  {'RAM (bss+zp)':<12s} {'':>6s} {'':>6s} {total_ram:#06x} {total_ram:5d}")

# Per-module breakdown
print(f"\n{'─'*W}")
print("  Per-Module Breakdown (CODE + RODATA)")
print(f"{'─'*W}")
print(f"  {'Module':<28s} {'CODE':>6s} {'RODATA':>6s} {'Total':>6s}")
print(f"  {'─'*28} {'─'*6} {'─'*6} {'─'*6}")

cat_totals = {}
mod_list = []
for mod_name, segs in sorted(modules.items()):
    code  = segs.get('CODE', 0)
    rdata = segs.get('RODATA', 0)
    total = code + rdata
    if total == 0:
        continue
    cat = categorize(mod_name)
    cat_totals.setdefault(cat, {'CODE': 0, 'RODATA': 0})
    cat_totals[cat]['CODE'] += code
    cat_totals[cat]['RODATA'] += rdata
    mod_list.append((cat, mod_name, code, rdata, total))

# Sort by category then size
mod_list.sort(key=lambda x: (x[0], -x[4]))

current_cat = None
for cat, mod_name, code, rdata, total in mod_list:
    if cat != current_cat:
        current_cat = cat
        print(f"\n  [{cat}]")
    print(f"    {mod_name:<26s} {code:5d}  {rdata:5d}  {total:5d}")

print(f"\n{'─'*W}")
print("  Category Totals (CODE + RODATA)")
print(f"{'─'*W}")
print(f"  {'Category':<20s} {'CODE':>6s} {'RODATA':>6s} {'Total':>6s} {'%':>5s}")
print(f"  {'─'*20} {'─'*6} {'─'*6} {'─'*6} {'─'*5}")
grand = total_rom
for cat in ['core', 'assembler', 'disassembler', 'cse-io', 'other']:
    if cat not in cat_totals:
        continue
    t = cat_totals[cat]
    total = t['CODE'] + t['RODATA']
    pct = total * 100.0 / grand if grand else 0
    print(f"  {cat:<20s} {t['CODE']:5d}  {t['RODATA']:5d}  {total:5d}  {pct:4.1f}%")
print(f"  {'─'*20} {'─'*6} {'─'*6} {'─'*6} {'─'*5}")
print(f"  {'TOTAL':<20s} {'':>6s} {'':>6s} {grand:5d}  100%")

# BSS/ZP breakdown
print(f"\n{'─'*W}")
print("  RAM Usage (BSS + ZEROPAGE)")
print(f"{'─'*W}")
for mod_name, segs in sorted(modules.items()):
    bss = segs.get('BSS', 0)
    zp  = segs.get('ZEROPAGE', 0)
    if bss + zp == 0:
        continue
    print(f"    {mod_name:<26s} BSS={bss:4d}  ZP={zp:2d}")

print(f"\n{'='*W}")
