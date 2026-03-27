# meminfo.s — Linker Symbol Shim

## Interface

### _cse_start
**In:** none
**Out:** A/X = start address of CSE code (uint16)

### _cse_end
**In:** none
**Out:** A/X = first address after CSE BSS (uint16)

**Depends on:** nothing (reads linker-generated symbols)

## Design

CSE must keep the user informed with up-to-date values regarding its
memory usage so the user knows where their work area is. Some of the
addresses involved here are static, some dynamic. The dynamic ones
must be tracked at runtime.

cc65's linker defines segment boundaries as assembly-level address
symbols (`__MAIN_START__`, `__BSS_RUN__`, `__BSS_SIZE__`).  C code
can't reference these directly.  meminfo.s stores the computed values
in RODATA words and provides two accessor functions that return
them in A/X.

Used by asm_src.s to place the symbol table heap above BSS, and by
repl.c's `i` command to show the memory map. The editor also displays
the free working area in its status bar.
