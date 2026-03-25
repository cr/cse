# CSE Memory Design

## Design Principles

1. **CSE stays out of the developer's way.** The developer's mental
   model: "my program lives at $1000 and up." CSE lives high.

2. **ROM-ready architecture.** All code and rodata must be separable
   from mutable state. No self-modifying code. Minimal BSS/DATA.
   Use `const` (cc65 `RODATA` segment) wherever possible. The same
   source must build as both PRG (RAM at $8000) and CRT (ROM at $8000).

3. **Mutable state is small and relocatable.** CSE's runtime variables,
   C stack, screen buffers — all grouped into one region that can move
   between configurations (PRG vs CRT, different RAM layouts).

4. **One screen, memcpy save/restore.** Both REPL and editor use the
   same screen RAM at $0400. On mode switch, the REPL screen content
   (1000 bytes) is saved to / restored from a buffer in CSE's BSS.
   Cost: 1000 bytes BSS, ~1ms per switch. The editor view is always
   reconstructable from the source buffer; the REPL screen is not
   (it contains command history and output), hence only the REPL
   screen needs saving.

5. **Source and developer code share the big region.** Source text grows
   downward, assembled output grows upward, classic C64 model (like
   BASIC programs vs strings). The `i` command shows remaining space.

## Memory Map — PRG Target (development)

Build loads to $0801 (standard BASIC start) for easy `RUN` during
development. Future production builds relocate to $8000.

    $0000-$00FF  Zero page
      $02-$7F    CSE runtime ZP (~30 bytes, cc65 + assembler)
    $0100-$01FF  6502 hardware stack
    $0200-$03FF  KERNAL/BASIC work area
    $0400-$07E7  Screen RAM (VIC bank 0, default)
    $07E8-$07FF  Sprite pointers (unused by CSE)
    $0800-$0FFF  CSE code (current PRG load point)
      ...        (code + rodata + data + bss, ~14KB)
    $????-$CFFF  Free (developer + source, see future layout)
    $D000-$DFFF  I/O (VIC/SID/CIA)
    $E000-$FFFF  KERNAL ROM

Note: BASIC ROM ($A000-$BFFF) is unmapped at startup. The RAM
underneath is available.

## Memory Map — PRG Target (production, relocated)

    $0000-$03FF  System (ZP, stack, KERNAL work)
    $0400-$07E7  Screen RAM (shared REPL / editor, VIC bank 0)
    $0800-$7FFF  Developer's program ↑ / source ↓  (30KB)
    $8000-$BFFF  CSE runtime (code+rodata+data+bss+cstk)
    $C000-$CFFF  Free for developer (popular target address)
    $D000-$DFFF  I/O
    $E000-$FFFF  KERNAL ROM

    Developer workspace: $0800-$7FFF = 30KB (source + output)
    CSE footprint:       $8000-$BFFF = 16KB
    Bonus developer:     $C000-$CFFF =  4KB

## Memory Map — CRT Target (cartridge)

    $0000-$03FF  System (ZP, stack, KERNAL work)
    $0400-$07E7  Screen RAM (shared REPL / editor, VIC bank 0)
    $0800-$7FFF  Developer's program ↑ / source ↓  (30KB)
    $8000-$BFFF  CSE cartridge ROM (code + rodata, 16KB)
    $C000-$CFFF  CSE mutable state (BSS + DATA + C stack)
    $D000-$DFFF  I/O
    $E000-$FFFF  KERNAL ROM

    Developer workspace: $0800-$7FFF = 30KB (source + output)
    CSE ROM:             $8000-$BFFF = 16KB (zero RAM cost)
    CSE RAM:             $C000-$CFFF =  4KB (state + stack)

Note: In the CRT layout, $C000-$CFFF is used by CSE's mutable state.
In the PRG layout it's free for the developer since CSE's mutable
state lives within the $8000-$BFFF region alongside the code.

## Source Code Storage

Source text lives at $C7FF growing downward. It shares the $1000-$C7FF
region with the developer's assembled output (which grows up from
$1000). This is the classic C64 model: programs and strings growing
toward each other.

    $1000  ──→  assembled output (grows up)
                  ... free gap ...
    $C7FF  ←──  source text (grows down)

The gap between them is free memory. The `i` command reports the gap
size. The 2-pass assembler reads source from the top-down region and
writes output to the bottom-up region. As long as they don't collide,
everything works.

For large programs where source + output exceed the available space:
save source to disk, assemble, then the full region is available for
the binary.

## Screen Switching

Both REPL and editor use the same screen RAM at $0400.  On mode
switch, the REPL screen content (1000 bytes) is saved to / restored
from a buffer in CSE's BSS.

    static uint8_t repl_screen_buf[1000];

    /* REPL → editor */
    memcpy(repl_screen_buf, SCREEN, 1000);  /* save REPL */
    clrscr();                                /* render editor view */

    /* editor → REPL */
    memcpy(SCREEN, repl_screen_buf, 1000);  /* restore REPL */

Cost: 1000 bytes BSS, ~1ms per switch.  No VIC bank switching, no
special screen addresses, identical code for PRG and CRT.  The editor
view is always reconstructable from the source buffer; the REPL screen
is not (it contains command history and output), hence only the REPL
screen needs saving.

## Build Targets

The same source builds for both targets via linker config:

    make              → build/cse.prg   (PRG, loads at $0801)

Linker config:
- `src/c64_cse.cfg`     — PRG target (current)
- CRT target is a future goal using the same source with a different
  linker config.

## Coding Guidelines for ROM Compatibility

- **Use `const` for all lookup tables.** cc65 places `const` data in
  `RODATA`, which lives in ROM on the CRT target.
- **No self-modifying code.** All assembly routines work from ROM.
  Runtime values live in ZP or BSS, never in patched inline code.
- **Minimize initialized data.** Prefer runtime initialization over
  static initializers. Static `= 0` is free (BSS), static `= nonzero`
  costs ROM + RAM (DATA segment gets copied to RAM at startup).
- **Keep BSS small.** Every byte of BSS is a byte of RAM that can't be
  used for source code or developer programs.
- **C stack budget: 2KB max.** Avoid deep recursion or large local
  arrays. The C stack lives in RAM and must be bounded.
