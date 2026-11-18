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
BRK state machine that consumes it from L4 (`debugger.s`, `main.s`,
`repl.s`).

The table is a module of its own so the tier boundary is a
compile-time fact rather than a convention: everything that depends
on `breakpoints.s` is strictly one layer up, and `breakpoints.s`
cannot reach into the BRK/NMI machinery because that machinery lives
in a higher stratum.

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
| +3 | flags: bit 0 = enabled, bit 7 = patched (the `$00` is in memory now; set by `patch_all`, cleared by `unpatch_all`) |

A slot is empty when `addr_lo | addr_hi == 0`.  A breakpoint at
`$0000` is therefore not representable — acceptable because `$0000`
is the CPU port (DDR), never a meaningful breakpoint target, and the
only caller that takes a user address (`repl.s::cmd_brk`) accepts
only `$0800 ≤ addr < buf_base` before it calls `dbg_bp_set`.

`dbg_bp_hit` (1 byte) names the user slot (0–7) of the breakpoint the
last break stopped at, `$FF` for none.  Writers: `bp_init`,
`dbg_bp_del` (of that slot), `dbg_bp_clear`, and in `main.s` the BRK
handler (the slot `dbg_bp_find` matched, else `$FF`), the NMI handler
and `end_debug_body` (`$FF`).  Readers (`repl.s`): the break panel
(`; brk N at $PC`), `t`/`o` (disable that slot for the step), `c`
(delete that slot before resuming).

## Interface

### bp_init
**In:** none
**Out:** `bp_table` zeroed (all 40 bytes); `dbg_bp_hit = $FF`.
**Clobbers:** A, X.

Cold-init entry for the table.  Called once at boot by `main.s`'s
`_main`, never on a warmstart: the table survives `cse_recover`
([memory_design.md § Breakpoint invariant](../memory_design.md#breakpoint-invariant)).
`debugger.s::dbg_init` handles step-state zeroing and ZP-buffer
seeding separately.

### dbg_bp_set
**In:** A = addr lo, X = addr hi
**Out:** C=0 success (A = slot 0–7); C=1 table full (A=$FF)
**Clobbers:** A, X, Y, `rp_ptr` (holds the address).

If a user-visible slot already holds `addr`, return that slot (C=0)
and change nothing — an address has at most one breakpoint, so `c`
past it never re-breaks at the same place.  Otherwise find the first
empty user-visible slot and install `(addr, saved=0, flags=1)`
(enabled, not patched).  Search is linear over slots 0–7.

`addr = $0000` matches the first empty slot as an "existing"
breakpoint: the call returns C=0 with that slot in A and stores
nothing (C=1 only when all eight slots are in use).

### dbg_bp_del
**In:** A = slot number (0–7)
**Out:** C=0 success; C=1 invalid slot (A=$FF)
**Clobbers:** A, X.

Zero all four bytes of the indexed slot.  If the slot is the one
`dbg_bp_hit` names, `dbg_bp_hit` becomes `$FF`: the hit breakpoint is
gone, so `c` must not delete whatever is set in that slot later.

### dbg_bp_clear
**In:** none
**Out:** slots 0–7 zeroed, `dbg_bp_hit = $FF`.  Slots 8–9 (step)
untouched.
**Clobbers:** A, X.

### dbg_bp_count
**In:** none
**Out:** A = count of non-empty user-visible slots (0–8).
**Clobbers:** A, X, Y.

### dbg_bp_find
**In:** A = addr lo, X = addr hi
**Out:** C=0 found (A = slot 0–7); C=1 not found (A=$FF); `rp_ptr`
= the address searched for.
**Clobbers:** A, X, Y, `rp_ptr`.

Linear scan over slots 0–7.  The first exact address match wins
(`$0000` matches the first empty slot).

### patch_all
**In:** none
**Out:** every enabled slot (all 10) that is not already patched has
its target byte saved into the slot's `saved` field, replaced with
`$00` (BRK opcode), and its patched bit set.  A second `patch_all`
without an `unpatch_all` in between changes nothing (the saved byte
stays the user's opcode, never `$00`).
**Clobbers:** A, X, Y, `rp_ptr`.

Iteration order: slot 0 → slot 9 (forward).  The forward order pairs
with `unpatch_all`'s reverse order so that if a step slot overlaps a
user breakpoint, the user's saved byte survives round-trip correctly.

### unpatch_all
**In:** none
**Out:** every patched slot's `saved` byte restored at its address and
its patched bit cleared.  A slot that was never patched — set by `b`
but not yet run, or disabled — is left alone, so ending a session
never writes a stale `saved` byte into the user's code.
**Clobbers:** A, X, Y, `rp_ptr`.

Iteration order: slot 9 → slot 0 (reverse).  See `patch_all` for the
overlap rationale.

### dbg_step_clear
**In:** none
**Out:** slots 8–9 (step pair) zeroed.  Slots 0–7 (user) untouched.
**Clobbers:** A, X.

Called by `debugger.s::arm_step_bp` before installing fresh step BPs
and by `repl.s::step_cleanup` when a step ends, is refused, or the
session ends.

### Memory

**BSS (41 bytes):** `bp_table` (40), `dbg_bp_hit` (1).
**ZP (0 bytes owned; reads rp_ptr as scratch for address-indirect writes).**

**Depends on:** `zp` (for `rp_ptr`).  Nothing else.  This is what
makes the module bundle-testable at Tier U with a minimal stub.

## Test contract

`tests/unit/test_breakpoints.py`.  Tier U via
`breakpoints + zp + breakpoints_test_stub` bundle.  35 tests covering:

- `TestBpInit` — table zeroing + `dbg_bp_hit = $FF` seed.
- `TestBpSet` / `TestBpDel` / `TestBpClear` / `TestBpFind` — full
  CRUD matrix including table-full, invalid-slot, not-found edges.
- `TestBpSetDuplicate` — a second `dbg_bp_set` of the same address
  returns the existing slot.
- `TestBpHitInvalidation` — deleting the hit slot, or clearing the
  table, sets `dbg_bp_hit = $FF`.
- `TestBpCount` — 0/1/many cases.
- `TestBpPatch` / `TestBpUnpatch` / `TestBpPatchedFlag` — round-trip
  invariant (patch → unpatch → original bytes restored), the
  patched bit.
- `TestStepSlots` / `TestStepClear` — slots 8–9 (`step_bp`): patched
  and restored with the rest, invisible to the user-slot operations;
  `dbg_step_clear` zeroes exactly them.
- `TestOverlap` — a step slot on a breakpoint's address, and both
  step slots on one address: the user's byte survives.

The step/BRK/userland-transition state machine that drives the table
([debugger.md](debugger.md)) is covered at integration tier by
`tests/integration/test_kernel_transition.py` and
`tests/integration/test_step_rom.py`.

## Design

**Why the step slots live in the same table as user breakpoints.**
A single `patch_all` pass covers both.  If user-visible slots lived
in a separate table, every userland exit would need two patch loops
and (worse) a way to prevent the step patch from clobbering a user
BP that shares the same address.  Unified table + forward-patch /
reverse-unpatch order solves both.

**Why `dbg_bp_hit` is here and not in `debugger.s`.**  Its semantics
are "which slot of `bp_table` was the one that fired."  The BRK
handler sets it after classification, but its meaning indexes into
this module's table — and the table operations that remove a slot
(`dbg_bp_del`, `dbg_bp_clear`) must invalidate it, so `c` never
deletes an unrelated breakpoint that later took the hit slot.
Ownership follows semantics, not write site.

**What does NOT belong here.**  Anything that transitions between
kernel and userland, dispatches interrupts, or manipulates CPU
stack frames lives in `debugger.s` (L4).  Specifically:
`brk_pc`, `step_state`, `step_remaining`, `step_next_*`,
`save_userland_state`, `restore_userland_state`, `return_to_userland`,
`brk_stub`, `step_next_pc`, `arm_step_bp`, `dbg_init` itself.
