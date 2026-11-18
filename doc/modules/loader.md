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
**Clobbers:** A, X, Y; SP (reset to `STACK_TOP`); ZP `$02–$05` (`ptr1`,
`ptr2`); the LOADER segment's own memory once `_main` reclaims it as
workspace.

`loader_entry` is not exported: it is reached by its fixed address,
not by name.

**On m65** (one entry, its body by `.ifdef PLATFORM_M65`;
[platform_layer.md § Loader](../platform_layer.md#loader)):
**In:** the run premise: the `SYS` line at `$2001` (`SYS 8205`) has
just entered here, `$200D`
([memory_design.md § Memory Map — m65](../memory_design.md#memory-map--m65-mega65-mode)).
**Out:** on a machine without what CSE uses (§ Design, step 1):
prints `cse needs MEGA65 ROM 920413+ (Hyppo 1.2+)` through `CHROUT`
and returns to BASIC with nothing changed.  Otherwise does not
return: the machine is installed — memory_design.md § Memory Map —
m65, *The installed machine* — and control is in `_main`, reached
through the resident stub's cold entry.
**Clobbers:** A, X, Y, Z, B; SP (reset to `STACK_TOP`); the DMA registers;
the LOADER segment's memory, which `_main` clears with the rest of
the program region.

**State:** none — the loader runs once and is overwritten.
**Depends on:** main (`_main`) — the loader's final `jmp` target after
relocation is complete (on m65: the address it writes into the
stub's cold target); on m65 also mem (the `STUB` segment's image,
which it copies to `STUB_BASE`, and `stub_cold`), the Hypervisor's
`hyppo_getversion` and `hyppo_rom_writeenable`
([platform_layer.md § Constants](../platform_layer.md#constants)),
the KERNAL's `CHROUT`, and `src/m45_ops.inc`; plus the
linker-supplied symbols
`__CODE_LOAD__`, `__CODE_RUN__`, `__CODE_SIZE__`, `__RODATA_SIZE__`,
`__BSS_RUN__`, `__BSS_SIZE__`, `__KDATA_LOAD__`, `__KDATA_RUN__`,
`__KDATA_SIZE__`.

## Test contract

- **c64.**  Tier I, `test_loader.py`: the unrelocated PRG of each C64
  build is put in memory and the real `loader_entry` runs up to its
  `jmp _main`; every relocated segment must equal what
  `EmuBase._relocate_segments()` (the Python relocation every other
  Tier I test loads through) produces, and the BSS must be zeroed.
  Unit-tier isolation would need synthesised linker symbols and is
  not productive ([testing.md § Principle 9](../testing.md), Pattern A).
- **m65.**  The same test file on the m65 PRG, entered with the run
  premise, checked against the installed machine; and the gate's
  refusal — [testing.md § The m65 PRG on M65Emu](../testing.md#the-m65-prg-on-m65emu).

## Design

The loader is a discardable bootstrap stage that runs once at PRG
startup and is never re-entered.  Its memory is reclaimed as user
workspace after `_main` takes over (cold init fills the workspace
from `$0800` with `$00`).

Sequence (LOADER segment, load = run = $080D):

1. Reset the 6502 stack pointer to `STACK_TOP`.
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

**The m65 sequence** (LOADER at `$200D`, load = run, inside the PRG
image in bank 0):

1. The gate, before anything is written: `hyppo_getversion` reports
   Hyppo 1.2 or later, and every jump-table entry CSE calls
   ([platform_layer.md § Constants](../platform_layer.md#constants))
   holds `$4C` or `$6C`.  Otherwise the message through `CHROUT`, and
   `rts` to BASIC.  The gate checks capabilities, not a ROM version
   number (ROM 920413, the floor, has no `VERSIONQ`).
2. `sei`; reset the stack pointer to `STACK_TOP`.
3. Copy the `STUB` image to `STUB_BASE`; clear CSE's base page;
   write `_main`'s address into the stub's cold target.
4. `hyppo_rom_writeenable`: banks 2–3 writable.
5. One DMA job list: CODE + RODATA image → `3.2000`, KDATA image →
   the data window, BSS → zero.  The job list is data in the LOADER
   segment.
6. `jmp stub_cold`, which `MAP`s the CSE map, sets `B = CSE_BP` and
   jumps to `_main` (its `EOM` leaves the I flag as `sei` left it;
   `_main` enables interrupts).  The loader does not execute the `MAP`
   itself: it runs in the `$2000–$7FFF` window the CSE map replaces.

The m65 body does the C64 body's work (relocate, clear BSS, place
KDATA) with the platform's means; the two share the entry, the
contract shape and this document.  The cartridge bootstrap is the
same body assembled with `PLAT_CRT`, reading its images from the
cartridge's bank instead of the PRG (*stated with P3*).

## Caveats

- The loader runs in its own address space ($080D–$08xx; `$200D`+ on
  m65) and **must not call any code outside the LOADER segment** —
  the KERNAL's jump table excepted — until the relocation is
  complete.  After `jmp _main`, the LOADER memory becomes
  user workspace.
- `_main` snapshots `$01–$7F` for the exit to BASIC after the loader
  ran, so the BASIC-side values of `$02–$05` are the loader's pointer
  leftovers, not BASIC's.
- Only assembled with `.setcpu "6502"` — never use illegal or CMOS
  opcodes here.  The loader runs on every CSE target regardless of
  build profile.  The m65 body's 45GS02-only instructions come from
  `src/m45_ops.inc` ([platform_layer.md § Raw-byte instructions](../platform_layer.md#raw-byte-instructions)).
- On m65 nothing the loader writes overlaps the PRG image it reads
  from: the DMA jobs write only bank 3, the stub copy and the
  base-page clear only CSE's page `0.1F00–0.1FFF`, below the image at
  `$2001`.
