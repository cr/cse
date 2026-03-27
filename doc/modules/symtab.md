# symtab.s — Symbol Table

## Interface

### _sym_define
**In:** `sym_name` (ZP, pointer to NUL-terminated name),
`sym_val` (ZP, 16-bit value), `sym_wide` (ZP, 0=ZP 1=ABS)
**Out:** C=0 success, C=1 table full
**Clobbers:** A, X, Y, all _st_* ZP vars

If the name already exists, updates the value and width.
If new, copies the name to the heap and creates a new entry.

### _sym_lookup
**In:** `sym_name` (ZP, pointer to NUL-terminated name)
**Out:** `sym_val` (ZP, 16-bit), `sym_wide` (ZP, 0=ZP 1=ABS).
C=0 found, C=1 not found.
**Clobbers:** A, X, Y, all _st_* ZP vars

### _sym_clear
**In:** none
**Out:** all slots zeroed, count reset, heap pointer reset to base
**Clobbers:** A, X

### _sym_count
**In:** none
**Out:** A = number of defined symbols
**Clobbers:** X (set to 0)

### _sym_set_heap
**In:** A/X = heap base address (lo/hi)
**Out:** heap base and current pointer set
Must be called before the first `_sym_define`.

**Depends on:** nothing (leaf module)

## Design

### Entry layout (6 bytes × 128 slots = 768 bytes BSS)

```
Offset  Size  Field
  0       1   hash       full 8-bit hash (all 256 values valid)
  1       2   value      16-bit symbol value (lo, hi)
  3       2   name_ptr   pointer to name in heap ($0000 = empty slot)
  5       1   scope      bit 7 = ZP/ABS (0=ZP, $80=ABS)
                          bits 6-0 = reserved
```

**Empty slot detection:** `name_ptr == $0000`.  Hash value 0 is valid
and does not indicate an empty slot.

### Hash function

```
h = 0
for each char in name:
    fold char (PETSCII $C1-$DA → $41-$5A)
    h = h * 5 + char       (8-bit, wraps naturally)
```

Hash 0 is valid — no forcing to 1.  Slot index = `h & $7F`.
Linear probing on collision (up to 128 probes).

### Case folding

Folding happens during hash computation and name comparison, not
during storage.  Names are stored verbatim as received.  `fold_char`
converts PETSCII shifted uppercase ($C1–$DA) to plain uppercase
($41–$5A).  Plain uppercase passes through unchanged.

This means `SCREEN` typed in shifted mode ($C1..) and `SCREEN` in
normal mode ($41..) resolve to the same symbol.

### Name heap

Names are copied to a persistent heap on every `_sym_define` call.
`name_ptr` always points into the heap, never into source buffers.

`_sym_set_heap` sets the base address.  The heap grows upward.
`_sym_clear` resets the heap pointer to the base.

The heap persists between assemblies — the REPL's `?` command can
resolve labels without re-assembling.

### Local labels

Local labels are handled by `asm_src.s`, not by `symtab.s`.  The
assembler concatenates the scope prefix: `.loop` under `main:` is
stored as `main.loop` in the symbol table.  From symtab's perspective,
it's just a longer name — no special scoping logic.

The scope byte's bits 6-0 are reserved but unused.

### Probing

`_sym_define`: compute hash, probe from `h & $7F`.  For each slot:
if empty (name_ptr=0) → new entry.  If hash matches and name matches
(case-insensitive) → update value.  Otherwise → next slot (wrapping).
If all 128 slots probed → C=1 (full).

`_sym_lookup`: same probe sequence.  Empty slot → C=1 (not found).

## Caveats

- 128 fixed slots.  No dynamic resizing.  When full, `_sym_define`
  returns C=1 and the caller reports the error.
- `_sym_clear` zeros 768 bytes (3 pages) — takes ~4ms at 1 MHz.
- `names_equal` uses a stack peek trick (`tsx; cmp $0101,x`) to
  compare without popping.  Works because the 6502 stack is at $0100.
- `heap_copy_name` copies until NUL.  The caller must ensure
  `sym_name` points to a properly NUL-terminated string.
