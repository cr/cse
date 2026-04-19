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

    # The loader uses a backward memcpy (highest byte first), so
    # any dst > src is safe regardless of payload/runtime overlap.
    # CSE always has dst > src (payload low, runtime high; KDATA
    # load low, KDATA run at $F100), so no payload-end check is
    # needed.  See doc/build_system.md § Copy direction and
    # src/loader.s header.

    # Generate config from template
    with open(template_path) as f:
        template = f.read()

    bss_start = runtime_start + code_size + rodata_size + data_size

    # BUF_FLOOR: optimal source/output split point.
    #
    # Workspace ($0800–runtime_start) is shared between assembled
    # output (grows up) and source text (grows down).  For N lines:
    #   output ≈ N × 1.5 bytes  (avg instruction mix + non-code lines)
    #   source ≈ N × 12  bytes  (indent + mnemonic + operand + CR)
    # Ratio source:output = 8:1.  Output occupies 1/9 of workspace.
    #
    # BUF_FLOOR = WORKSTART + workspace/9, page-aligned down.
    # At full capacity both regions meet at BUF_FLOOR simultaneously.
    workspace = runtime_start - 0x0800
    buf_floor = (0x0800 + workspace // 9) & 0xFF00  # page-align down

    output = template.replace("@@RUNTIME_START@@", f"${runtime_start:04X}")
    output = output.replace("@@BSS_START@@", f"${bss_start:04X}")
    output = output.replace("@@BUF_FLOOR@@", f"${buf_floor:04X}")
    sys.stdout.write(output)

    # Summary to stderr
    max_lines = workspace // (12 + 1)  # approx: 12B src + 1.5B out ≈ 13
    print(f"  layout: RUNTIME=${runtime_start:04X} BSS=${bss_start:04X} "
          f"FLOOR=${buf_floor:04X} workspace={workspace} "
          f"(~{max_lines} lines)",
          file=sys.stderr)


if __name__ == "__main__":
    main()
