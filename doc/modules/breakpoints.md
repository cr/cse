# breakpoints.s — Breakpoint-Table CRUD + Patching

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/breakpoints.s`](../../src/breakpoints.s) | implementation |
| [`tests/unit/test_breakpoints.py`](../../tests/unit/test_breakpoints.py) | test contract |
| [`src/bp.inc`](../../src/bp.inc) | the slot layout: `SLOT_SIZE`, `BP_SAVED`, `BP_FLAGS` per platform (included by breakpoints.s, debugger.s, main.s, repl.s) |
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

**m65:** a slot holds a **flat address**, so a breakpoint belongs to
its physical byte whatever the map when it is hit (slice 3, F4):

| Offset | c64 (4 bytes) | m65 (6 bytes) |
|---|---|---|
| +0, +1 | address lo, hi | the flat address's offset lo, hi |
| +2 | saved byte | its bank |
| +3 | flags | its megabyte (0) |
| +4 | — | saved byte |
| +5 | — | flags |

`BP_SAVED` and `BP_FLAGS` name the two offsets on both platforms;
`SLOT_SIZE` is 4 / 6, so the table is 40 / 60 bytes.  A slot is empty
when its offset and bank are 0 (`0.0000` is no target).  On m65
`dbg_bp_set` and `dbg_bp_find` take a CPU address (A/X) and translate
it through the program's bank state (`far_user`) into `rp_ptr`, or —
`dbg_bp_set_flat` / `dbg_bp_find_flat` — take a flat address already in
`rp_ptr`; they compare all four bytes.  `patch_all` / `unpatch_all`
reach the slot's flat address itself: no translation, so a remap
between patch and break does not misplace the restore.  The BRK
handler matches the break's PC through the bank state the break
captured, so the hit test sees the byte the CPU executed.

## Table layout

10 slots × `SLOT_SIZE` bytes of BSS (`bp_table`): 10 × 4 = 40 bytes
on c64, 10 × 6 = 60 on m65.

| Slots | Role | Manipulated by |
|---|---|---|
| 0–7 | User-visible breakpoints | `b` command via `dbg_bp_set` / `dbg_bp_del` / `dbg_bp_clear` / `dbg_bp_find` / `dbg_bp_count` |
| 8–9 | Step-BP pair (alias `step_bp = bp_table + 8 × SLOT_SIZE`: `+ 32` on c64, `+ 48` on m65) | `debugger.s::arm_step_bp` (writes directly) + `dbg_step_clear` |

Slot format on c64 (4 bytes; m65's is § Purpose's table):

| Offset | Byte |
|---|---|
| +0 | address lo |
| +1 | address hi |
| +2 | saved byte (the opcode that was there before we patched BRK over it) |
| +3 | flags: bit 0 = enabled, bit 7 = patched (the `$00` is in memory now; set by `patch_all`, cleared by `unpatch_all`) |

A slot is empty when `addr_lo | addr_hi == 0` (on m65 the bank too).  A breakpoint at
`$0000` is therefore not representable — acceptable because `$0000`
is the CPU port (DDR), never a meaningful breakpoint target, and the
only caller that takes a user address (`repl.s::cmd_brk`) accepts
only `$0800 ≤ addr < buf_base` before it calls `dbg_bp_set` (on m65
only user memory, which starts at `0.2000`).

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
**Out:** `bp_table` zeroed (all 40 bytes; 60 on m65); `dbg_bp_hit = $FF`.
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
**Clobbers:** A, X; on m65 also `bp_tmp`.

Zero all `SLOT_SIZE` bytes of the indexed slot (4 / 6).  If the slot is the one
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

**On m65** (both routines): a slot holds a flat address, and each
slot's turn loads all four of its bytes — offset, bank, megabyte —
into `rp_ptr` (`SLOT_PTR`); the read and the write are `FAR_LDA` /
`FAR_STA` through it.  No bank state is consulted, so the byte patched
is the byte restored whatever the map did in between.  A target is
whatever `b` and the step gate admit: user memory in banks 0, 1, 4
or 5, or `brk_stub` ([debugger.md § `b`](debugger.md#b)).

### dbg_step_clear
**In:** none
**Out:** slots 8–9 (step pair) zeroed.  Slots 0–7 (user) untouched.
**Clobbers:** A, X.

Called by `debugger.s::arm_step_bp` before installing fresh step BPs
and by `repl.s::step_cleanup` when a step ends, is refused, or the
session ends.

### dbg_bp_set_flat / dbg_bp_find_flat (m65)
**In:** `rp_ptr` = a flat address (offset, bank, megabyte)
**Out, Clobbers:** as `dbg_bp_set` / `dbg_bp_find`, which translate
their CPU address A/X through the program's bank state (`FAR_USER`)
into `rp_ptr` and fall into these.  Caller: `repl.s::cmd_brk` calls
`dbg_bp_set_flat` for a flat literal (`b H.AAAA`).  `dbg_bp_find_flat`
is internal (not exported): `dbg_bp_set_flat` runs it first.

### dbg_step_find (m65)
**In:** A = addr lo, X = addr hi (a break's PC)
**Out:** C=0 when the address, translated through the program's bank
state, is one of the step slots' flat addresses; C=1 not.
**Clobbers:** A, X, Y, `rp_ptr`.

Caller: `main.s::cse_brk_handler`, to tell a step BRK from any other.

### step_bp_arm (m65)
**In:** A = addr lo, X = addr hi (a next PC); Y = the step slot's
offset in `step_bp` (0 or `SLOT_SIZE`)
**Out:** that slot = the address's flat address under the program's
bank state, saved 0, flags 1 (enabled, not patched).
**Clobbers:** A, X, Y, `rp_ptr`.

Caller: `debugger.s::arm_step_bp`.

### Memory

**BSS (41 bytes):** `bp_table` (40), `dbg_bp_hit` (1) on c64; 62 on
m65: `bp_table` (60), `dbg_bp_hit` (1), `bp_tmp` (1, `dbg_bp_del`'s
slot × 2).
**ZP (0 bytes owned; reads rp_ptr as scratch for address-indirect writes).**

**Depends on:** `zp` (for `rp_ptr`); on m65 also `mem` (`far_user`,
through `FAR_USER`: a CPU address's flat address).  Nothing else.
This is what makes the module bundle-testable at Tier U with a
minimal stub (c64).

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

The Tier-U bundle is the c64 table (4-byte slots).  The m65 table
(6-byte flat slots) is covered at Tier I on the m65 PRG:
`tests/integration/test_m65_repl.py` § flat breakpoints (`b H.AAAA`,
a CPU address listed as its physical byte, a breakpoint that belongs
to its physical byte across a remap, `;?range` outside user memory,
a breakpoint in far code hit by a far start) and
`tests/integration/test_m65_debugger.py` (the workspace gates, a hit
that restores its byte and resumes, the step chain).

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
