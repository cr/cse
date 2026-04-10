#!/usr/bin/env python3
"""Compute runtime start address and generate production linker config.

Two-pass build:
  1. Trial link with c64_trial.cfg → trial.map (measures segment sizes)
  2. This script reads sizes, computes RUNTIME_START, writes production cfg

Usage: compute_layout.py <trial.map> <cfg_template> > <output.cfg>
"""
import re
import sys


def parse_segment_sizes(map_path):
    """Read total segment sizes from the ld65 'Segment list' section."""
    sizes = {}
    in_segments = False
    with open(map_path) as f:
        for line in f:
            if line.strip().startswith("Segment list:"):
                in_segments = True
                continue
            if in_segments:
                if line.startswith("Name") or line.startswith("---"):
                    continue
                if not line.strip():
                    break
                parts = line.split()
                if len(parts) >= 4:
                    name, size = parts[0], int(parts[3], 16)
                    sizes[name] = size
    return sizes


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <trial.map> <cfg_template>",
              file=sys.stderr)
        sys.exit(1)

    map_path, template_path = sys.argv[1], sys.argv[2]

    sizes = parse_segment_sizes(map_path)
    code_size = sizes.get("CODE", 0)
    rodata_size = sizes.get("RODATA", 0)
    data_size = sizes.get("DATA", 0)
    bss_size = sizes.get("BSS", 0)

    runtime_total = code_size + rodata_size + data_size + bss_size
    runtime_start_raw = 0xD000 - runtime_total
    # Page-align downward: editor.s has hi-byte-only BUF_END checks
    # that assume BUF_END (= __CODE_RUN__) is page-aligned.
    runtime_start = runtime_start_raw & 0xFF00

    # Sanity checks
    if runtime_start < 0x0900:
        print(f"ERROR: runtime too large ({runtime_total} bytes), "
              f"RUNTIME_START=${runtime_start:04X} overlaps workspace",
              file=sys.stderr)
        sys.exit(1)

    # Verify forward copy is safe: payload end < runtime start.
    # Payload in file starts after EXEHDR ($080D) + LOADER.
    loader_size = sizes.get("LOADER", 0)
    payload_start = 0x080D + loader_size
    kdata_size = sizes.get("KDATA", 0)
    payload_end = payload_start + code_size + rodata_size + kdata_size
    if payload_end > runtime_start:
        print(f"ERROR: payload end ${payload_end:04X} > "
              f"RUNTIME_START ${runtime_start:04X} — "
              f"forward copy unsafe, binary too large",
              file=sys.stderr)
        sys.exit(1)

    # Generate config from template
    with open(template_path) as f:
        template = f.read()

    bss_start = runtime_start + code_size + rodata_size + data_size

    output = template.replace("@@RUNTIME_START@@", f"${runtime_start:04X}")
    output = output.replace("@@BSS_START@@", f"${bss_start:04X}")
    sys.stdout.write(output)

    # Summary to stderr
    print(f"  layout: CODE={code_size} RODATA={rodata_size} "
          f"BSS={bss_size} → RUNTIME=${runtime_start:04X} "
          f"BSS=${bss_start:04X} workspace={runtime_start - 0x0800}",
          file=sys.stderr)


if __name__ == "__main__":
    main()
