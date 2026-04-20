# breakpoints.s — Breakpoint-Table CRUD + Patching

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/breakpoints.s`](../../src/breakpoints.s) | implementation |
| [`tests/unit/test_breakpoints.py`](../../tests/unit/test_breakpoints.py) | test contract |
| [`dev/breakpoints_test_stub.s`](../../dev/breakpoints_test_stub.s) | Tier-U bundle stub (linker scaffolding only) |

## Purpose

L3 module that owns the 10-slot breakpoint table and the operations
that manipulate it.  Pure data-structure work: no KERNAL calls, no
vectors, no interrupt dispatch, no stack-frame synthesis.  This is
what makes it bundle-testable at Tier U independently of the step /
BRK state machine that consumes it from L4 (`debugger.s`).

Split from `debugger.s` at the 2026-04-20 structural refactor so the
tier boundary becomes a compile-time fact rather than a disciplined
convention: anything that depends on `breakpoints.s` is strictly one
layer up, and `breakpoints.s` itself can't reach into BRK/NMI
machinery because that machinery lives in a higher stratum.

## Table layout

10 slots × 4 bytes = 40 bytes of BSS (`bp_table`).

| Slots | Role | Manipulated by |
|---|---|---|
| 0–7 | User-visible breakpoints | `b` command via `dbg_bp_set` / `dbg_bp_del` / `dbg_bp_clear` / `dbg_bp_find` / `dbg_bp_count` |
| 8–9 | Step-BP pair (alias `step_bp = bp_table + 32`) | `debugger.s::arm_step_bp` (writes directly) + `dbg_step_clear` |

Slot format (4 bytes):

| Offset | Byte |
|---|---|
| +0 | address lo |
| +1 | address hi |
| +2 | saved byte (the opcode that was there before we patched BRK over it) |
| +3 | enabled flag (0 = disabled, 1 = enabled) |

A slot is empty when `addr_lo | addr_hi == 0`.  Slot 0 at address
`$0000` is therefore not representable — acceptable because `$0000`
is the CPU port (DDR), never a meaningful breakpoint target.

## Interface

### bp_init
**In:** none
**Out:** `bp_table` zeroed (all 40 bytes); `dbg_bp_hit = $FF`.
**Clobbers:** A, X.

Cold-init entry for the table.  Called once at boot by
`debugger.s::dbg_init`.  `dbg_init` then handles step-state zeroing
and ZP-buffer seeding separately.

### dbg_bp_set
**In:** A = addr lo, X = addr hi
**Out:** C=0 success (A = slot 0–7); C=1 table full (A=$FF)
**Clobbers:** A, X, Y.

Find the first empty user-visible slot and install
`(addr, saved=0, enabled=1)`.  Search is linear over slots 0–7.

### dbg_bp_del
**In:** A = slot number (0–7)
**Out:** C=0 success; C=1 invalid slot (A=$FF)
**Clobbers:** A, X.

Zero all four bytes of the indexed slot.

### dbg_bp_clear
**In:** none
**Out:** slots 0–7 zeroed.  Slots 8–9 (step) untouched.
**Clobbers:** A, X.

### dbg_bp_count
**In:** none
**Out:** A = count of non-empty user-visible slots (0–8).
**Clobbers:** A, X, Y.

### dbg_bp_find
**In:** A = addr lo, X = addr hi
**Out:** C=0 found (A = slot 0–7); C=1 not found (A=$FF)
**Clobbers:** A, X, Y.

Linear scan over slots 0–7.  The first exact address match wins.

### patch_all
**In:** none
**Out:** every enabled slot (all 10) has its target byte saved into
the slot's `saved` field and replaced with `$00` (BRK opcode).
**Clobbers:** A, X, Y, `rp_ptr`.

Iteration order: slot 0 → slot 9 (forward).  The forward order pairs
with `unpatch_all`'s reverse order so that if a step slot overlaps a
user breakpoint, the user's saved byte survives round-trip correctly.

### unpatch_all
**In:** none
**Out:** every enabled slot's `saved` byte restored at its address.
**Clobbers:** A, X, Y, `rp_ptr`.

Iteration order: slot 9 → slot 0 (reverse).  See `patch_all` for the
overlap rationale.

### dbg_step_clear
**In:** none
**Out:** slots 8–9 (step pair) zeroed.  Slots 0–7 (user) untouched.
**Clobbers:** A, X.

Called by `debugger.s::arm_step_bp` before installing fresh step BPs.

### Memory

**BSS (41 bytes):** `bp_table` (40), `dbg_bp_hit` (1).
**ZP (0 bytes owned; reads rp_ptr as scratch for address-indirect writes).**

**Depends on:** `zp` (for `rp_ptr`).  Nothing else.  This is what
makes the module bundle-testable at Tier U with a minimal stub.

## Test contract

`tests/unit/test_breakpoints.py`.  Tier U via
`breakpoints + zp + breakpoints_test_stub` bundle.  21 tests covering:

- `TestBpInit` — table zeroing + `dbg_bp_hit = $FF` seed.
- `TestBpSet` / `TestBpDel` / `TestBpClear` / `TestBpFind` — full
  CRUD matrix including table-full, invalid-slot, not-found edges.
- `TestBpCount` — 0/1/many cases.
- `TestPatchUnpatch` — round-trip invariant (patch → unpatch →
  original bytes restored), overlap handling via iteration order.

The step/BRK/userland-transition state machine (the remainder of the
old `debugger.s`) is covered at integration tier by
`tests/integration/test_kernel_transition.py` and
`tests/integration/test_step_rom.py`.

## Design notes

**Why the step slots live in the same table as user breakpoints.**
A single `patch_all` pass covers both.  If user-visible slots lived
in a separate table, every userland exit would need two patch loops
and (worse) a way to prevent the step patch from clobbering a user
BP that shares the same address.  Unified table + forward-patch /
reverse-unpatch order solves both.

**Why `dbg_bp_hit` is here and not in `debugger.s`.**  Its semantics
are "which slot of `bp_table` was the one that fired."  The byte is
WRITTEN by the L4 BRK handler (after classification), but its
MEANING indexes into this module's table.  Ownership follows
semantics, not write site.

**What does NOT belong here.**  Anything that transitions between
kernel and userland, dispatches interrupts, or manipulates CPU
stack frames lives in `debugger.s` (L4).  Specifically:
`brk_pc`, `step_state`, `step_remaining`, `step_next_*`,
`save_userland_state`, `restore_userland_state`, `return_to_userland`,
`brk_stub`, `step_next_pc`, `arm_step_bp`, `dbg_init` itself.
