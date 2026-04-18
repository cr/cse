# symtab.s — Symbol Table

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/symtab.s`](../../src/symtab.s) | implementation |
| [`tests/test_symtab.py`](../../tests/test_symtab.py) | test contract |

## Interface

### sym_define
**In:** `sym_name` (ZP, pointer to NUL-terminated name),
`sym_val` (ZP, 16-bit value), `sym_wide` (ZP, 0=ZP 1=ABS)
**Out:** C=0 success, C=1 table full
**Clobbers:** A, X, Y, all _st_* ZP vars

If the name already exists, updates the value and width.
If new, copies the name to the heap and creates a new entry.

### sym_lookup
**In:** `sym_name` (ZP, pointer to NUL-terminated name)
**Out:** `sym_val` (ZP, 16-bit), `sym_wide` (ZP, 0=ZP 1=ABS).
C=0 found, C=1 not found.
**Clobbers:** A, X, Y, all _st_* ZP vars

### sym_clear
**In:** none
**Out:** all slots zeroed, heap pointer reset to base
**Clobbers:** A, X

### Memory

**ZP (10 bytes):** `_st_hash` (1), `_st_idx` (1), `_st_ptr` (2), `_st_nptr` (2), `_st_heap` (2), `_st_heap_base` (2).

Probe state for linear probing.  `_st_heap`/`_st_heap_base` track
the name heap (fixed at $E600 under KERNAL).

**Depends on:** nothing (leaf module)

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

**Capacity is 256 — all slots are addressable.** The empty marker
is the *value* `name_ptr == $0000`, not a reserved slot.  Since the
heap lives at $E600+, no real entry can have `name_ptr == 0`, so
the value is unambiguous.

Hash value 0 is valid and does not indicate an empty slot.

A fully populated table is detected by **probe-wrap**: `sym_define`
walks the linear probe chain and returns C=1 (full) if `_st_idx`
returns to its starting hash without finding either an empty slot
or a name match.  No separate count is maintained.

### KERNAL banking

`sym_table` lives at $E000–$E5FF in RAM underneath the kernal ROM.
The name heap follows at $E600–$EEFF (2304 bytes).  The NMI shadow
at $FFFA/$FFFB (installed by `setup_interrupts` in main.s) routes
NMI directly to `cse_nmi_handler` so NMI is safe even while the
kernal is banked out.  This saves ~3.8 KB of main RAM (1536B table
+ 2304B heap).

**Reads** under KERNAL ($E000–$FFFF) require the KERNAL to be
banked out.  **Writes always pass through** to the underlying RAM
regardless of `$01` bit 1, so pure-writer functions need no banking
at all.

`sym_lookup` and `sym_define` both read existing entries (probe
scan, name compare) and therefore must bank out before access.
`sym_clear` is a pure writer (zeros 1536 bytes) and does not bank.

The banking guard sequence used by `sym_define` and `sym_lookup`:

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

The kernal banking functions (`kernal_bank_out`, `kernal_bank_in`,
`kernal_out`) live in `mem.s`.  symtab.s imports them.

Both `kernal_bank_out` and `kernal_bank_in` honour the
`kernal_out` flag — when set, they become no-ops.  The flag lets
`asm_assemble` hold the KERNAL banked out across both passes
(see `asm_src.s`); inner `sym_define`/`sym_lookup` calls inside
the batch then short-circuit instead of issuing a redundant
`$01` write on every label reference.

**Ordering rule for outer batches:** the real `kernal_bank_out`
must run BEFORE `kernal_out := 1`, and `kernal_out := 0` must
run BEFORE the real `kernal_bank_in`.  Otherwise the very call
that is supposed to do the bank operation short-circuits because
the flag is already set.  See `asm_src.s::asm_assemble`.

Internal subroutines (`compute_hash`, `fold_char`) that operate
only on ZP variables and the name string (which is in main RAM)
are called with the KERNAL already banked out by their caller.

`heap_copy_name` writes to the heap while the KERNAL is banked
out by `sym_define`.  The write itself doesn't need the bank-out,
but `sym_define`'s probing did.

### NMI safety

`sei` only masks IRQ, not NMI.  If NMI fires while the kernal is
banked out, the CPU reads the NMI vector from RAM at $FFFA/$FFFB
instead of ROM.  `setup_interrupts` (in main.s, called once during
cold init before any bank-out) writes the early-entry label of
`cse_nmi_handler` into the $FFFA/$FFFB shadow.  The handler's
early-entry prologue banks the kernal back in if necessary and
runs the standard NMI dispatch.

See [main.md](main.md) § cse_nmi_handler for the full handler
contract.

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

Names are copied to a persistent heap on every `sym_define` call.
`name_ptr` always points into the heap, never into source buffers.

The heap starts at fixed address $E600.  `sym_clear` resets the
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

`sym_define`: compute hash, probe from `h & $FF`.  For each slot:
if empty (name_ptr=0) → new entry (check heap space).  If hash
matches and name matches (case-insensitive) → update value.
Otherwise → next slot.  If probe wraps to start → C=1 (full).

`sym_lookup`: same probe sequence.  Empty slot → C=1 (not found).
Wraparound to start index → C=1 (not found, table full).

## Caveats

- 256 slots, all usable.  No dynamic resizing.  When full (or heap
  overflow), `sym_define` returns C=1.
- `sym_clear` zeros 1536 bytes (6 pages) — takes ~8ms at 1 MHz.
  No banking is required (pure writer), so interrupts stay enabled
  during the loop.
- `names_equal` uses a stack peek trick (`tsx; cmp $0101,x`) to
  compare without popping.  Works because the 6502 stack is at $0100.
- `heap_copy_name` copies until NUL.  The caller must ensure
  `sym_name` points to a properly NUL-terminated string.
- Banking overhead: ~12 cycles per bank-out/bank-in pair (two
  `lda $01 / ora-or-and / sta $01` sequences; no SEI/CLI since
  Phase 18's IRQ early-entry handles IRQ-during-bank-out).
  Negligible compared to the ~300-cycle hash + probe cost of a
  typical lookup.  Inside an `asm_assemble` batch (kernal_out=1),
  the inner bank helpers are no-ops, so the only banking cost
  is the single outer pair.
- Name heap overflow: `heap_copy_name` checks `_st_heap` against
  `SYM_HEAP_END` ($EF00) after each copy.  Returns C=1 on overflow.
