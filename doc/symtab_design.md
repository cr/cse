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

### After assembly (snapshot)

A single pass copies all name strings from the gap buffer into a compact
**snapshot heap** in the free memory region. `name_ptr` entries are updated
to point into the snapshot. The source can then be edited freely.

The snapshot heap lives between the symbol table and the gap buffer:

```
sym_table (768B) | snapshot heap (~1-2KB) | ... free ... | gap buffer
```

The snapshot is rebuilt on each successful assembly. The REPL's expression
parser (`? label+$10`) uses the snapshot between assemblies.

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

Stored with the local name only (no parent prefix concatenation).
The `scope` byte's `parent_id` (bits 5-0) identifies the enclosing
global label by its slot index.

On lookup, `.name` resolves using the current scope (ZP variable
`current_scope` = slot index of the last global label defined).

Hash for locals incorporates the parent_id:
`hash = hash_name("loop") ^ parent_id`

This ensures `.loop` under `main` and `.loop` under `draw` hash to
different slots.

### ZP/ABS width
Stored in bit 7 of the `scope` byte. Set during `sym_define` based on
`expr_wide` (the expression parser's width tracking). Retrieved during
`sym_lookup` and propagated back to `expr_wide`.

At the REFERENCE site, the first-letter case convention can override:
uppercase first letter forces ABS. This is handled by the expression
parser, not the symbol table.

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
