# loader — Discardable cold-boot bootstrap

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/loader.s`](../../src/loader.s) | implementation |
| [`tests/integration/test_loader.py`](../../tests/integration/test_loader.py) | test contract — `loader_entry` on the unrelocated PRG equals `EmuBase._relocate_segments()`, BSS zeroed |

## Interface

### loader_entry
**In:** BASIC has just `SYS 2061`-jumped here (the `EXEHDR` stub in
`main.s` at `$0801`; `loader_entry` is the first byte of the LOADER
segment at `$080D`).  Registers, stack and `$01` are whatever BASIC
left.
**Out:** does not return.  Tail-jumps to `_main` after relocation:
CODE + RODATA at their runtime addresses, BSS zeroed, KDATA at its
runtime address under the KERNAL.  `$01` is unchanged.
**Clobbers:** A, X, Y; SP (reset to `$FF`); ZP `$02–$05` (`ptr1`,
`ptr2`); the LOADER segment's own memory once `_main` reclaims it as
workspace.

`loader_entry` is not exported: it is reached by its fixed address,
not by name.

**State:** none — the loader runs once and is overwritten.
**Depends on:** `_main` — the loader's final `jmp` target after
relocation is complete; plus the linker-supplied symbols
`__CODE_LOAD__`, `__CODE_RUN__`, `__CODE_SIZE__`, `__RODATA_SIZE__`,
`__BSS_RUN__`, `__BSS_SIZE__`, `__KDATA_LOAD__`, `__KDATA_RUN__`,
`__KDATA_SIZE__`.

## Design

The loader is a discardable bootstrap stage that runs once at PRG
startup and is never re-entered.  Its memory is reclaimed as user
workspace after `_main` takes over (cold init fills the workspace
from `$0800` with `$00`).

Sequence (LOADER segment, load = run = $080D):

1. Reset the 6502 stack pointer to $FF.
2. Copy CODE + RODATA from their load position (low memory) to their
   runtime position (high memory) — backward memcpy, top-down.
3. Zero the BSS region.
4. Copy KDATA from its load position to its runtime position
   (≥ $F100, under the KERNAL bank) — backward memcpy, top-down.
   Pure stores under the KERNAL reach the RAM beneath it whatever
   `$01` says, so the copy needs no banking.
5. `jmp _main` — control transfers to the runtime image.

Only BSS is zeroed.  The rest of the banked RAM under the KERNAL
(symbol table, REPL screen save, `main.s`'s `COLD_ZP` snapshot) is
not touched by the loader; see
[memory_design.md § Banked layout](../memory_design.md#banked-layout-e000ffff).

**Copy direction.**  Both copies are top-down (highest byte first)
because CSE always has `dst > src` for both regions (payload lives
low, runtime lives high; KDATA load is below `$F100` run).  Backward
copy is always safe under this layout.  See
[build_system.md § The ld65 load/run split](../build_system.md#the-ld65-loadrun-split).

**ZP usage.**  The loader borrows `$02–$05` as two 16-bit pointers
(`ptr1` = source, `ptr2` = destination).  Same addresses as
`zp.s`'s `rp_ptr` / `rp_ptr2`, but the loader runs strictly before
`_main` so there is no temporal conflict.

**Test coverage.**  Tier I, `test_loader.py`: the unrelocated PRG
of each C64 build is put in memory and the real `loader_entry` runs
up to its `jmp _main`; every relocated segment must equal what
`EmuBase._relocate_segments()` (the Python relocation every other
Tier I test loads through) produces, and the BSS must be zeroed.
Unit-tier isolation would need synthesised linker symbols and is not
productive ([testing.md § Principle 9](../testing.md), Pattern A).

## Caveats

- The loader runs in its own address space ($080D–$08xx) and **must
  not call any code outside the LOADER segment** until the relocation
  is complete.  After `jmp _main`, the LOADER memory becomes
  user workspace.
- `_main` snapshots `$01–$7F` for the exit to BASIC after the loader
  ran, so the BASIC-side values of `$02–$05` are the loader's pointer
  leftovers, not BASIC's.
- Only assembled with `.setcpu "6502"` — never use illegal or CMOS
  opcodes here.  The loader runs on every CSE target regardless of
  build profile.
