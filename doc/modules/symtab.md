# symtab.s — Symbol Table

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/symtab.s`](../../src/symtab.s) | implementation |
| [`tests/unit/test_symtab.py`](../../tests/unit/test_symtab.py) | test contract |

## Interface

### sym_define
**In:** `sym_name` (ZP, pointer to NUL-terminated name in main RAM),
`sym_val` (ZP, 16-bit value; m65 32-bit), `sym_wide` (ZP, 0=ZP 1=ABS),
`sym_stamp` (BSS, the stamp to write)
**Out:** C=0 success; C=1 table full (probe wrapped) or name heap full
(nothing written).  `$01` is the caller's on return.
**Clobbers:** A, X, Y, `_st_hash`, `_st_idx`, `_st_ptr`, `_st_nptr`;
`_st_heap` advances when a new name is stored.

If the name already exists, updates the value, width and stamp.  If
new, copies the name to the heap and creates a new entry.  The scope
byte gets bit 7 = width and bit 6 = `sym_stamp`
([§ Pass stamp](#pass-stamp)).

### sym_lookup
**In:** `sym_name` (ZP, pointer to NUL-terminated name in main RAM),
`sym_stamp` (BSS)
**Out:** C=0 found, C=1 not found.  When found: `sym_val` (ZP,
16-bit; m65 32-bit), `sym_wide` (ZP, 0=ZP 1=ABS), `sym_fwd` (BSS): nonzero iff the
entry's stamp differs from `sym_stamp` — the symbol was defined in an
earlier pass only, so this read is a forward reference in the current
pass.  When not found, `sym_val`, `sym_wide` and `sym_fwd` are
unchanged.  `$01` is the caller's on return.
**Clobbers:** A, X, Y, `_st_hash`, `_st_idx`, `_st_ptr`, `_st_nptr`

### sym_clear
**In:** none
**Out:** all 256 slots zeroed, `_st_heap` and `_st_heap_base` =
`SYM_HEAP` ($E600; m65 $A700)
**Clobbers:** A, X.  Does not bank (pure writer).

### sym_stamp, sym_fwd
Exported BSS bytes.  `sym_stamp` (1) — input of `sym_define` /
`sym_lookup`: the current pass's stamp, `SYM_P0` ($40) during pass 0
of an assembly, 0 during pass 1 and outside an assembly; written only
by asm_src (`asm_assemble`).  `sym_fwd` (1) — output of `sym_lookup`.

### Memory

**ZP (10 bytes):** `_st_hash` (1), `_st_idx` (1), `_st_ptr` (2), `_st_nptr` (2), `_st_heap` (2), `_st_heap_base` (2).

Probe state for linear probing.  `_st_heap`/`_st_heap_base` track
the name heap (fixed at $E600 under KERNAL).

**BSS (2 bytes, exported):** `sym_stamp`, `sym_fwd` (above).

**Banked RAM:** `sym_table` $E000–$E5FF and the name heap
$E600–$EEFF (`SYM_HEAP_END` = $EF00, exclusive), in RAM under the
KERNAL ROM.  m65: `sym_table` 3.9F00–3.A6FF, the heap 3.A700–3.AFFF,
in the data window.  The layout of the whole banked area is owned by
[memory_design.md § Banked layout](../memory_design.md#banked-layout-e000ffff).

**Depends on:** mem (`kernal_bank_out`), zp (`sym_name`, `sym_val`,
`sym_wide`, `_st_*`).

### Callers of `sym_define`

`sym_define` is the generic "register a name → value" entry point.
Direct callers:

| Caller | Name | Purpose |
|---|---|---|
| `gap_buffer.s::define_ws_syms` | `workstart` | fixed $0800; called at cold init (main.s) and by `asm_assemble` before each pass |
| `gap_buffer.s::update_workend` | `workend` | `buf_base - 1`; falls in from `define_ws_syms`, and called after every buffer-base change |
| `asm_src.s::define_label` and the `.const` handler (`d_const`) | user symbols | per `main:` / `.loop:` / `.const` in source, on both passes (pass 1 re-stamps) |

## Design

**On m65 a value is 32 bits** (slice 3, F5a): an entry is 8 bytes —
`sym_val` is 4 bytes in the base page — so the table is 2048 bytes and
a slot's offset is `slot × 8` (three shifts).  It sits at
`3.9F00–3.A6FF` (`SYM_TABLE`; the name heap `3.A700–3.AFFF`), and the
CSE window's CODE / RODATA / KDATA / KCODE / BSS area ends at `$9F00` (O-F-4;
[memory_design.md](../memory_design.md)).  Bytes 0–5 are the c64's
(hash, value bytes 0–1, name_ptr, scope); bytes 6–7 are the value's
upper word.  Every writer of `sym_val` sets all four bytes: `.const`
the expression's 32 bits ([expr.md § 32-bit
values](expr.md#32-bit-values-m65)), a label `asm_pc`'s four bytes
(the upper word is its segment's bank: 0, or a flat segment's), the
workspace symbols their 16-bit address with a zero upper word.  Test contract:
`tests/unit/test_expr_m65.py` (the round trip through all 256 slots,
`sym_clear`'s extent).  The c64 layout below does not change.

### Entry layout (6 bytes × 256 slots = 1536 bytes at $E000)

```
Offset  Size  Field
  0       1   hash       full 8-bit hash (all 256 values valid)
  1       2   value      16-bit symbol value (lo, hi)
  3       2   name_ptr   pointer to name in heap ($0000 = empty slot)
  5       1   scope      bit 7 = ZP/ABS (0=ZP, $80=ABS)
                          bit 6 = pass stamp (`sym_stamp` at the define)
                          bits 5-0 = reserved
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

<a id="pass-stamp-mega_support"></a>

### Pass stamp

An operand's size must be decided identically in both passes:
on the C64 a symbol read before its definition is sized ABS on pass 0
(it is undefined there), so pass 1 must size it ABS too even when its
value turns out to be ZP; the 4510's two branch widths need the same
([asm_line.md § Branches](asm_line.md#branches-zone-b), the m65
build).  The stamp tells a reader whether a symbol is defined *so far in the
current pass*: `sym_define` stamps every entry it writes with
`sym_stamp`, and asm_src gives each pass its own stamp — `SYM_P0`
for pass 0, 0 for pass 1 and outside an assembly — refreshing the
built-in symbols after each change.  During pass 1 an entry still
carrying `SYM_P0` was defined only in pass 0, i.e. later in the
source: `sym_lookup` reports it with `sym_fwd`.  During pass 0 such a
symbol is simply not found.  Outside an assembly every entry carries
0, so no read is forward.

### KERNAL banking

`sym_table` lives at $E000–$E5FF in RAM underneath the kernal ROM.
The name heap follows at $E600–$EEFF (2304 bytes).  This saves
~3.8 KB of main RAM (1536 B table + 2304 B heap).  Interrupts stay
safe while the KERNAL is banked out through the RAM vectors at
$FFFA/$FFFE that main.s installs ([§ NMI safety](#nmi-safety)).

**Reads** under KERNAL ($E000–$FFFF) require the KERNAL to be
banked out.  **Writes always pass through** to the underlying RAM
regardless of `$01` bit 1, so pure-writer functions need no banking
at all.

`sym_lookup` and `sym_define` both read existing entries (probe
scan, name compare) and therefore must bank out before access.
`sym_clear` is a pure writer (zeros 1536 bytes) and does not bank.

The banking guard used by `sym_define` and `sym_lookup` **nests**: it
saves `$01` on entry, banks out through `kernal_bank_out`, and on
every exit restores the saved `$01` — it never banks *in* on its own:

```
lda $01
pha                 ; caller's banking
jsr kernal_bank_out ; KERNAL RAM visible (no-op inside a batch)
  ... table access ...
pla
sta $01             ; back to exactly the caller's state
```

So a caller that has itself banked out without the `kernal_out` batch
flag — `asm_line` on the REPL `.` path, which reads its KDATA tables
after a symbol operand is resolved — keeps the KERNAL banked out
across the lookup; a guard that banked in on exit would hand such a
caller the ROM in place of its tables.

The kernal banking functions (`kernal_bank_out`, `kernal_bank_in`)
and the `kernal_out` flag are in `mem.s` / zp.s; symtab.s imports
`kernal_bank_out` only.

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

`compute_hash` (and its `fold_char`) reads only the name string at
`sym_name`, which is in main RAM; `sym_define` and `sym_lookup` call
it *before* the bank-out.  `names_equal` reads the stored name in the
heap and runs after it.

`heap_copy_name` writes to the heap while the KERNAL is banked
out by `sym_define`.  The write itself doesn't need the bank-out,
but `sym_define`'s probing did.

### NMI safety

`sei` only masks IRQ, not NMI.  If NMI fires while the kernal is
banked out, the CPU reads the NMI vector from RAM at $FFFA/$FFFB
instead of ROM; `setup_interrupts` (main.s, at cold init, before any
bank-out) points it at `cse_nmi_handler`, and the IRQ/BRK vector at
$FFFE likewise.  The handler contracts are owned by
[main.md](main.md).

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
maps a shifted letter ($C1–$DA) to the unshifted one ($41–$5A); every
other byte passes through unchanged.

This means `screen` typed with SHIFT ($D3 $C3 …) and without
($53 $43 …) resolve to the same symbol.

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

The scope byte's bits 5-0 are reserved but unused.

### Probing

`sym_define`: compute hash, probe from `h & $FF`.  For each slot:
if empty (name_ptr=0) → new entry (check heap space).  If hash
matches and name matches (case-insensitive) → update value.
Otherwise → next slot.  If probe wraps to start → C=1 (full).

`sym_lookup`: same probe sequence.  Empty slot → C=1 (not found).
Wraparound to start index → C=1 (not found, table full).

## Caveats

- 256 slots, all usable.  No dynamic resizing.  When full (or heap
  overflow), `sym_define` returns C=1 (asm_src reports `;?N: sym full`).
- `sym_clear` zeros 1536 bytes (6 pages; m65 2048 bytes, 8 pages, of
  8-byte entries) — about 8 ms at 1 MHz.
  No banking is required (pure writer), so interrupts stay enabled
  during the loop.
- `names_equal` uses a stack peek trick (`tsx; cmp $0101,x`) to
  compare without popping.  Works because the 6502 stack is at $0100.
- `heap_copy_name` copies until NUL.  The caller must ensure
  `sym_name` points to a properly NUL-terminated string.
- Banking overhead: the guard is `lda $01 / pha / jsr kernal_bank_out`
  … `pla / sta $01`, a few dozen cycles; no SEI/CLI (the RAM IRQ
  vector handles an IRQ during bank-out — memory_design.md).
  Negligible compared to the ~300-cycle hash + probe cost of a
  typical lookup.  Inside an `asm_assemble` batch (kernal_out=1)
  `kernal_bank_out` is a no-op.
- Name heap overflow: `heap_copy_name` measures the name first and
  refuses it (C=1, `sym_define` reports full) when name + NUL would
  end past `SYM_HEAP_END` ($EF00).  Nothing is written and `_st_heap`
  does not move, so the bytes at $EF00+ (user-stack window, KDATA)
  are never touched, and a shorter name may still fit afterwards.
  On m65 the end is $B000 (3.B000), where `REPL_SCREEN` begins; the
  same refusal leaves it untouched (test_symtab.py `TestHeapOverflow`
  on c64, test_m65_repl.py `test_name_heap_stops_below_the_repl_screen`).
