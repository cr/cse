# loader — Discardable cold-boot bootstrap

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/loader.s`](../../src/loader.s) | implementation |

## Interface

### loader_entry
**In:** machine reset state — BASIC has just `SYS`-jumped here from
the PRG header at `$080D`.  Stack is in unknown state.
**Out:** does not return.  Tail-jumps to `_main` after relocation.
**Clobbers:** the 6502 stack pointer (reset to $FF), the entire $02–$05
ZP scratch window (reused as `ptr1`/`ptr2`), and the LOADER segment's
own memory once `_main` reclaims it as workspace.

**State:** none — the loader runs once and is overwritten.
**Depends on:** `_main` (entry point), and the linker-supplied symbols
`__CODE_LOAD__`, `__CODE_RUN__`, `__CODE_SIZE__`, `__RODATA_SIZE__`,
`__BSS_RUN__`, `__BSS_SIZE__`, `__KDATA_LOAD__`, `__KDATA_RUN__`,
`__KDATA_SIZE__`.

## Design

The loader is a discardable bootstrap stage that runs once at PRG
startup and is never re-entered.  Its memory is reclaimed as user
workspace immediately after `_main` takes over.

Sequence (LOADER segment, load = run = $080D):

1. Reset the 6502 stack pointer to $FF.
2. Copy CODE + RODATA from their load position (low memory) to their
   runtime position (high memory) — backward memcpy, top-down.
3. Zero the BSS region.
4. Copy KDATA from its load position to its runtime position
   (≥ $F100, under the KERNAL bank) — backward memcpy, top-down.
5. `jmp _main` — control transfers to the runtime image.

**Copy direction.**  Both copies are top-down (highest byte first)
because CSE always has `dst > src` for both regions (payload lives
low, runtime lives high; KDATA load is below `$F100` run).  Backward
copy is always safe under this layout.  See
[build_system.md § The ld65 load/run split](../build_system.md#the-ld65-loadrun-split).

**ZP usage.**  The loader borrows `$02–$05` as two 16-bit pointers
(`ptr1` = source, `ptr2` = destination).  Same addresses as
`main.s::rp_ptr` / `rp_ptr2`, but the loader runs strictly before
`_main` so there is no temporal conflict.

**Test coverage.**  No dedicated test file — the loader is exercised
implicitly by every integration test that loads the production PRG
through `C64Emu`.  See
[testing.md § Tier I](../testing.md) and the L6 entry in
[architecture.md § Layer Diagram](../architecture.md#layer-diagram).
This is Pattern A coverage per [testing.md § Principle 9](../testing.md):
the bootstrap path is observable only as part of a full PRG load
cycle, so unit-tier isolation would require synthesising the
linker-supplied symbols and is not productive.

## Caveats

- The loader runs in its own address space ($080D–$08xx) and **must
  not call any code outside the LOADER segment** until the relocation
  is complete.  After `jmp _main`, the LOADER memory becomes
  user workspace.
- The KDATA copy targets a region under the KERNAL bank — the loader
  banks ROM out for the KDATA copy and back in afterward, since
  KDATA's runtime address ($F100+) is shadowed by KERNAL by default.
- Only assembled with `.setcpu "6502"` — never use illegal or CMOS
  opcodes here.  The loader runs on every CSE target regardless of
  build profile.
