# Symbol Table Design

## Overview

The symbol table maps names to 17-bit values (16-bit address + ZP/ABS flag).
It handles both labels (`main:`) and constants (`SCREEN = $0400`) through
the same backend.

## Entry Layout: 6 bytes × N slots

```
hash(1) + value(2) + name_ptr(2) + scope(1) = 6 bytes

hash:      8-bit hash of the (folded) name. 0 = empty slot.
value:     16-bit symbol value (lo, hi).
name_ptr:  16-bit pointer to NUL-terminated name string.
           During assembly: points into source (gap buffer).
           After assembly: points into snapshot heap.
scope:     bit 7 = ZP/ABS (0=ZP-eligible, 1=force ABS)
           bit 6 = is_local (0=global, 1=local label)
           bits 5-0 = parent slot index (0-63) if local
```

Initial size: 128 slots = 768 bytes. Growable by doubling (ask user).

## Name Storage: Two-Phase Heap

### During assembly (pass 1 + pass 2)

`name_ptr` points directly into the source text (gap buffer). The source
is stable during both passes — the editor is not active. Zero-copy: no
string duplication during assembly.

### After assembly (snapshot) — PLANNED

**Status: Not yet implemented.** Currently `name_ptr` becomes invalid
when the source is edited after assembly.

Planned: A single pass copies all name strings from the gap buffer
into a compact snapshot heap. `name_ptr` entries are updated to point
into the snapshot. The REPL's expression parser uses the snapshot
between assemblies.

## Name Conventions

### Character set
- a-z (case insensitive — uppercase folded to lowercase)
- 0-9 (not as first character of globals)
- `.` (dot — for local label prefix)
- No underscore (not typeable on C64 keyboard)

### Case insensitivity
All names are folded to lowercase before hashing and comparison.
`SCREEN`, `Screen`, `screen` all resolve to the same symbol.

### Local labels
Dot-prefixed: `.loop`, `.done`, `.skip`.

**Status: PLANNED.** The scope byte infrastructure exists (bit 6 = is_local,
bits 5-0 = parent_id) but local label scoping is not yet implemented.
Currently `.loop` is stored as a global with the literal name `.loop`.

Planned implementation:
- Store local name only (no parent prefix concatenation)
- `scope` byte's `parent_id` identifies the enclosing global label
- `current_scope` ZP variable tracks the last global label defined
- Hash for locals: `hash = hash_name("loop") ^ parent_id`

### ZP/ABS width
Stored in bit 7 of the `scope` byte. Set during `sym_define` from
`sym_wide` ZP variable. Retrieved during `sym_lookup` and returned
as `sym_wide` (normalized to 0=ZP, 1=ABS).

**Planned:** First-letter case convention at reference site (uppercase
forces ABS). Not yet implemented.

## Hash Function

```
h = 0
for each char in folded name:
    h = h * 5 + char
if h == 0: h = 1     (0 = empty sentinel)
```

Slot index = `h & (N_SLOTS - 1)`. Linear probing on collision.

## Operations

### sym_define
1. Fold name to lowercase (during comparison)
2. Compute hash
3. Probe: if slot empty → store entry. If name matches → update value.
4. Store: hash, value, name_ptr (pointing to source text), scope byte.
5. If table at capacity → return C=1.

### sym_lookup
1. Fold name to lowercase (during comparison)
2. Compute hash
3. Probe: compare hash byte (fast reject), then compare name strings.
4. On match: copy value to sym_val, copy ZP/ABS to scope, return C=0.
5. On empty slot: return C=1 (not found).

### sym_clear
Zero all slots. Reset count.

### sym_snapshot (called after successful assembly)
Walk all occupied slots. For each name_ptr pointing into the gap buffer
range, copy the string to the snapshot heap and update name_ptr.

## Capacity

128 slots at 75% load = 96 symbols. If full, prompt user to double
(256 slots = 1536 bytes). The snapshot heap grows proportionally.

Typical C64 program: 50-100 constants + 20-50 labels + 30-60 locals
= 100-210 symbols. May need 256 slots for larger programs.

## Built-in Symbols (Future)

Common C64 hardware addresses (VIC, SID, CIA, KERNAL vectors) can be
predefined, saving 30-50 user symbol slots. These would live in a
separate read-only table in RODATA, checked before the user table.

## Memory Budget

| Component | 128 slots | 256 slots |
|-----------|-----------|-----------|
| Hash table | 768 B | 1536 B |
| Snapshot heap (typical) | ~800 B | ~1600 B |
| **Total** | **~1568 B** | **~3136 B** |
