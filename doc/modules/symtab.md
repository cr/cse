# symtab.s — Symbol Table

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/symtab.s`](../../src/symtab.s) | implementation |
| [`tests/test_symtab.py`](../../tests/test_symtab.py) | test contract |

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

**Depends on:** nothing (leaf module)

### Memory

**ZP (11 bytes):** `_st_hash` (1), `_st_idx` (1), `_st_ptr` (2), `_st_nptr` (2), `_st_count` (1), `_st_heap` (2), `_st_heap_base` (2).

Probe state for linear probing.  `_st_heap`/`_st_heap_base` track
the name heap (fixed at $E600 under KERNAL).

## Design

### Entry layout (6 bytes × 256 slots = 1536 bytes at $E000)

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

### KERNAL banking

`sym_table` lives at $E000–$E5FF in RAM underneath the KERNAL ROM.
The name heap follows at $E600–$EEFF (2304 bytes).  An NMI trampoline
at $FF00 ensures safe NMI handling while the KERNAL is banked
out.  This saves ~3.8 KB of main RAM (1536B table + 2304B heap).
Accessing the table and heap requires banking out the KERNAL by
clearing bit 1 of the
CPU I/O port ($01).  Since the IRQ vector and KERNAL interrupt
handler live in the banked-out region, interrupts must be disabled
for the duration of the access.

The banking guard sequence used by `_sym_define`, `_sym_lookup`, and
`_sym_clear`:

```
sei                 ; disable interrupts
lda $01
and #$FD           ; clear bit 1 → KERNAL RAM visible
sta $01
  ... table access ...
lda $01
ora #$02           ; set bit 1 → KERNAL ROM restored
sta $01
cli                 ; re-enable interrupts
```

Functions that do not access `sym_table` directly (`_sym_count`)
do not need banking guards.  Internal subroutines (`compute_hash`,
`fold_char`) that operate only on ZP variables and the name string
(which is in main RAM) are called with the KERNAL already banked
out by their caller.

Both the 1536-byte hash table and the 2304-byte name heap are
under the KERNAL.  `heap_copy_name` writes to the heap while the
KERNAL is banked out by `sym_define`.

### NMI safety

`sei` only masks IRQ, not NMI.  If NMI fires while the KERNAL is
banked out, the CPU reads the NMI vector from RAM at $FFFA/$FFFB
instead of ROM.  `_kernal_init` (called once at startup) installs
a 10-byte trampoline at $FF00 in banked RAM and sets the RAM NMI
vector to point to it.  The trampoline re-banks the KERNAL and
then jumps through the KERNAL's indirect NMI vector at $0318
(which CSE sets to its own `nmi_handler` in `cse_io.s`).

### Hash function

```
h = 0
for each char in name:
    fold char (PETSCII $C1-$DA → $41-$5A)
    h = h * 5 + char       (8-bit, wraps naturally)
```

Hash 0 is valid — no forcing to 1.  Slot index = `h & $FF`.
Linear probing on collision (up to 256 probes, wraparound detection).

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

The heap starts at fixed address $E600.  `_sym_clear` resets the
heap pointer to the base.

The heap persists between assemblies — the REPL's `?` command can
resolve labels without re-assembling.

### Local labels

Local labels are handled by `asm_src.s`, not by `symtab.s`.  The
assembler concatenates the scope prefix: `.loop` under `main:` is
stored as `main.loop` in the symbol table.  From symtab's perspective,
it's just a longer name — no special scoping logic.

The scope byte's bits 6-0 are reserved but unused.

### Probing

`_sym_define`: compute hash, probe from `h & $FF`.  For each slot:
if empty (name_ptr=0) → new entry (check count < 255 and heap space).
If hash matches and name matches (case-insensitive) → update value.
Otherwise → next slot.  If probe wraps to start → C=1 (full).

`_sym_lookup`: same probe sequence.  Empty slot → C=1 (not found).
Wraparound to start index → C=1 (not found, table full).

## Caveats

- 256 slots, 255 usable (8-bit count).  No dynamic resizing.  When
  full (or heap overflow), `_sym_define` returns C=1.
- `_sym_clear` zeros 1536 bytes (6 pages) — takes ~8ms at 1 MHz.
  Interrupts are disabled for the duration.
- `names_equal` uses a stack peek trick (`tsx; cmp $0101,x`) to
  compare without popping.  Works because the 6502 stack is at $0100.
- `heap_copy_name` copies until NUL.  The caller must ensure
  `sym_name` points to a properly NUL-terminated string.
- Banking overhead: ~20 cycles per sei/bank-out/bank-in/cli pair.
  Negligible compared to the ~300-cycle hash + probe cost of a
  typical lookup.  Worst case: `_sym_clear` holds interrupts off
  for ~8ms (6-page zero loop); acceptable because the C64 IRQ
  period is ~16ms (60 Hz).
- Name heap overflow: `heap_copy_name` checks `_st_heap` against
  `SYM_HEAP_END` ($EF00) after each copy.  Returns C=1 on overflow.
