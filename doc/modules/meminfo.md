# meminfo.s — DELETED

**Absorbed into [`mem.s`](../../src/mem.s)** (Session 10, memory management refactor).

The `cse_start`, `cse_end`, and `cse_zp_end` functions now live in
`mem.s` alongside the KERNAL banking helpers and workspace symbol
management.  See [memory_design.md § Memory Manager Module](../memory_design.md).
