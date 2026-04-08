# meminfo.s — Linker Symbol Shim

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/meminfo.s`](../../src/meminfo.s) | implementation |

## Interface

### cse_start
**In:** none
**Out:** A/X = start address of CSE code (`__MAIN_START__`)

### cse_end
**In:** none
**Out:** A/X = first address after CSE BSS
(`__BSS_RUN__ + __BSS_SIZE__`)

### cse_zp_end
**In:** none
**Out:** A = first free ZP byte (`__ZP_LAST__ + 1`); X = 0

**Depends on:** nothing (reads linker-generated symbols only)

### Memory

**RODATA (5 bytes):** `_start_val` (2), `_end_val` (2),
`_zp_end_val` (1) — captured at link time from the linker's
`__MAIN_START__` / `__BSS_RUN__` + `__BSS_SIZE__` / `__ZP_LAST__`
symbols.

## Design

CSE keeps the user informed of where the work area lives and how
much room is free.  Some of the relevant addresses are static
(known at link time), some dynamic (the gap buffer's `buf_base`
moves at runtime).  meminfo.s handles the static ones.

The ld65 linker defines segment boundaries as assembly-level
symbols (`__MAIN_START__`, `__BSS_RUN__`, `__BSS_SIZE__`,
`__ZP_LAST__`).  meminfo.s captures them in RODATA at link time
and exposes them as three accessor functions returning their
values in A (and X for the 16-bit ones).

Callers:
- `repl.s::cmd_info` (`i` command) — displays the memory map.
- `editor.s::ed_status_free` — computes free workspace bytes
  for the status bar.
- `editor.s::define_ws_syms` / `update_workend` — `workstart`
  is `cse_end()` rounded up to a page boundary.

Dynamic memory tracking (gap buffer growth, source/free
boundaries) lives in `editor.s`, not here.
