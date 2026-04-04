# meminfo.s — Linker Symbol Shim

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/meminfo.s`](../../src/meminfo.s) | implementation |

## Interface

### _cse_start
**In:** none
**Out:** A/X = start address of CSE code (uint16)

### _cse_end
**In:** none
**Out:** A/X = first address after CSE BSS (uint16)

### _cse_zp_end
**In:** none
**Out:** A = first free ZP byte (uint8)

**Depends on:** nothing (reads linker-generated symbols)

## Design

CSE must keep the user informed with up-to-date values regarding its
memory usage so the user knows where their work area is. Some of the
addresses involved here are static, some dynamic. The dynamic ones
must be tracked at runtime.

The ld65 linker defines segment boundaries as assembly-level symbols
(`__MAIN_START__`, `__BSS_RUN__`, `__BSS_SIZE__`).  meminfo.s stores
the computed values in RODATA and provides three accessor functions.
`_cse_zp_end` uses `__ZP_LAST__` to report the first free ZP byte.

Used by asm_src.s to place the symbol table heap above BSS, and by
repl.s's `i` command to show the memory map.  The editor also displays
the free working area in its status bar.
