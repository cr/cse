# Memory Design — Memory maps, ZP layout, calling convention

**Template:** [subsystem](templates/subsystem.md)

## Design Principles

1. **CSE stays out of the developer's way.** The developer's mental
   model: "my program lives at `workstart` and up."  CSE code lives
   above the workspace.

2. **ROM-ready architecture.** Code and RODATA are separable from
   mutable state.  No self-modifying code.  Constants in RODATA,
   runtime state in BSS.  The same source must build as both PRG
   (RAM) and CRT (ROM at $8000).

3. **Mutable state is small and relocatable.** All runtime variables
   live in BSS (zeroed at boot) or ZP.  No initialized DATA segment.

4. **One screen, save/restore.** Both REPL and editor use screen RAM
   at $0400.  On mode switch, the REPL screen (1000 bytes) is saved
   to / restored from banked RAM under KERNAL ($F4F2).  The editor
   view is always reconstructable from the gap buffer; only the REPL
   screen needs saving.

5. **Source and output share the workspace.** Source text grows down
   from the CSE runtime start (`__CODE_RUN__`), assembled output
   grows up from `workstart`.  The `i` command shows the gap
   between them.

## Calling Convention

All modules are pure 6502 assembly.  One consistent convention:

### Register arguments

| Args | Convention |
|------|-----------|
| 0 | — |
| 1 (8-bit) | A |
| 1 (16-bit) | A/X (lo/hi) |
| 2+ | Earlier args in named ZP variables; last in A/X |

### Return values

| Type | Convention |
|------|-----------|
| 8-bit value | A |
| 16-bit value | A/X (lo/hi) |
| Success/failure | C flag: C=0 success, C=1 failure (or vice versa per function doc) |
| Void | — |

### Shared state (ZP interface)

Several subsystems pass data through named ZP variables rather than
registers.  This is preferred for multi-field I/O:

| ZP group | Owner | Fields | Used by |
|----------|-------|--------|---------|
| Assembler I/O | zp | `asm_pc`, `asm_out`, `asm_cpu`, `asm_len`, `asm_mode` | asm_line, asm_src |
| Symbol I/O | zp | `sym_name` (ptr), `sym_val`, `sym_wide` | symtab, asm_src, expr, repl |
| Expression I/O | zp | `expr_ptr` (ptr), `expr_val`, `expr_wide` | expr, asm_src, repl |
| Mnemonic chars | mn_vars | `mn_c1`, `mn_c2`, `mn_c3` | mn_classify, mn7/mn6, asm_line |

Callers set the input fields, call the function, read the output
fields.  The function may modify any field in its group.

### Register clobbering

Functions clobber A, X, Y unless documented otherwise.  ZP variables
outside the function's own group are preserved.  The hardware stack
is balanced (no net push/pop across a call).

### Multi-argument calls

Functions with 2+ arguments use named ZP variables for the first
arguments and A/X for the last.  Examples:

- `disk_load_prg`: `disk_ptr` = name, A/X = addr
- `asm_line`: `asm_pc`/`asm_out` set by caller, A/X = text
- `ed_read_line`: A/X = buf pointer (maxlen hardcoded)

No software parameter stack.  All arguments pass through registers
or ZP variables.

## Glossary

| Term | Meaning |
|------|---------|
| **CODE** | Executable code in main RAM (XXXX–$CFFF) |
| **RODATA** | Read-only constants in main RAM (follows CODE) |
| **BSS** | Uninitialized runtime state in main RAM (follows RODATA, zeroed at startup, no PRG space) |
| **KDATA** | Read-only tables under KERNAL ROM ($E000–$FFFF), copied from PRG payload at startup |
| **KBSS** | Uninitialized structures under KERNAL ROM, zeroed at startup (no PRG space) |

## Target Compatibility

CSE targets:
- Stock C64 KERNAL ROM
- Stock C128 KERNAL ROM (C64 mode)
- OpenROMs on C64/C128 hardware (excluding MEMORY_MODEL_60K)

The 60K exclusion means $02A7-$02FF remains usable (the 60K model
repurposes this range).  Low memory ($0000-$03FF) is assumed to be
"C64-shaped" across all targets.

## CSE ↔ KERNAL Contract

CSE is a KERNAL-compatible application that replaces BASIC
interaction while active.

**CSE preserves:**
- $80-$FF (KERNAL zero page)
- $0100-$01FF (hardware stack — shared, balanced)
- Live KERNAL/editor low-memory state ($0200-$02A6, $0300-$0333)

**CSE owns (modifies on init, restores on exit):**
- $01 (CPU I/O port — unmaps BASIC ROM)
- $02-$7F (CSE zero page — saved on cold init, restored on exit)
- $0316/$0317 (IBRK — BRK dispatch)
- $0318/$0319 (INMIV — NMI dispatch)
- $FFFA/$FFFB (NMI vector RAM shadow — read by CPU when kernal banked out)
- $FFFE/$FFFF (IRQ/BRK vector RAM shadow — read by CPU when kernal banked out)

**Exit obligation:** `cse_exit_to_basic` calls kernal RESTOR
($FF8A) to restore $0314-$0333 to defaults, restores $01-$7F
from cold-init snapshot, writes $00 to `($2B)-1` (byte before
TXTTAB, stabilises BASIC's program link chain), calls CINT
($FF81) to reinit screen, and enters BASIC warm start via
`JMP ($A002)`.

**Hook installation** is performed once during cold init by
`setup_interrupts` (main.s):

- $0316/$0317 and $0318/$0319 patched via direct stores to point
  at `cse_brk_handler` and `cse_nmi_handler` respectively.
- $FFFA/$FFFB and $FFFE/$FFFF (RAM shadows under kernal ROM) patched
  to point at the corresponding handler's **early-entry** label.
  These early-entry paths execute only when the CPU read the
  vector from RAM — i.e. when the kernal was banked out — and so
  reaching the early-entry label is itself the signal that the
  handler must bank the kernal back out before its final RTI.
- `setup_interrupts` runs **before any bank-out** in cold init, so
  the trampoline-executed-with-stale-vector window cannot exist.

There are **no separate trampolines** at $FF00 / $FF04.  Handlers
live in CODE at their link-time addresses; the early-entry
prologues are part of the handler code, not a relocated stub
region.

**Cold-init snapshot** stored in KBSS under kernal ROM (pure
write, no banking needed on save):
- `_cold_zp` (127 B) — $01-$7F at cold-init entry

## User Code Contract

The full contract is documented in
[userland_contract.md](userland_contract.md).  This section
summarises the key obligations for orientation.

User code is any program executed via `j`, `g`, `t`, `o`, or `c`.
It runs in CSE's execution context via `return_to_userland` (debugger.s),
sharing the 6502 hardware stack and the kernal environment.

**User code may clobber:**
- $00-$7F (CSE saves/restores across user execution; includes the
  CPU port byte at $01 — CSE re-installs its banking configuration
  on return)
- $0100-$01FF (user owns the stack page within their SP budget —
  see § Stack contract)
- $02A7-$02FF (89 bytes, free on all supported targets)
- $0334-$03FF (204 bytes, includes tape buffer at $033C-$03FB)
- $0800-workend (workspace — user's own assembled output)

**User code must preserve:**
- $80-$FF (kernal zero page)
- $0200-$02A6 (kernal editor state, input buffer)
- $0300-$0333 (kernal vectors — CSE hooks are installed here)
- CSE runtime (XXXX-$CFFF — overwriting CSE code/data is fatal)

User code shares the hardware stack page with CSE — there is no
two-image swap.  User code may push freely within its 240-byte
budget; CSE never reads bytes below the user's SP.  See § Stack
contract.

**Tape buffer caveat:** $033C-$03FB is the kernal tape I/O buffer.
User code may freely use these 192 bytes, but must restore them
if the user's own program needs tape or serial I/O through kernal
routines that use this buffer.

**Screen and I/O:** User code may use kernal CHROUT ($FFD2) for
screen output, integrated with REPL display — see
[userland_contract.md § 6 (KERNAL-as-terminal)](userland_contract.md#6-kernal-as-terminal-affordance).
CSE does not save/restore screen RAM across user execution.  On
return, CSE forces VIC into a known-good text-mode state via
`vic_reset` (display on, charset standard, sprites off, raster
IRQ off), restores $01 banking, kernal cursor state ($CC=1), and
clears stuck SID voice gates.  If user code clears or repaints the
screen, ESC or CLR from the REPL restores the CSE display.
Colors changed by user code are restored on return.

**Memory config ($01):** $01 is part of the ZP save range ($00–$7F),
so it round-trips via `userland_zp_buf` across every user-code run.
User code may freely change $01 (e.g. to bank in BASIC ROM or
access I/O directly), but must not combine $01 changes with
$FFFE/$FFFA vector changes that route to non-CSE handlers — see
[userland_contract.md § 5.3](userland_contract.md#53-rom-banking-01).

**Vector changes:** User code that overwrites $0316/$0318 (or
$FFFE/$FFFA) breaks debugger breakpoints and/or RUN/STOP+RESTORE
recovery.  See [userland_contract.md § 5](userland_contract.md#5-interrupt-vector-and-banking-hazards).

## Memory Map — Runtime (all targets)

    $0000-$00FF  Zero page (see § Zero Page Layout)
      $00-$01    CPU I/O port
      $02-$56    CSE ZP variables (85 bytes, 13 modules)
      $57-$7F    Free (41 bytes, available for user programs)
      $80-$FF    KERNAL work area
    $0100-$01FF  6502 hardware stack (shared CSE + user code)
    $0200-$02A6  KERNAL editor state, input buffer (reserved)
    $02A7-$02FF  Free (89 bytes, user code may use)
    $0300-$0333  KERNAL vectors (CSE hooks at $0316, $0318)
    $0334-$03FF  Free (204 bytes, user code may use)
    $0400-$07E7  Screen RAM (40×25, VIC bank 0)
    $07E8-$07FF  Sprite pointers (unused by CSE)
    $0800        workstart — first free workspace byte
      ...        Assembled output ↑ (grows up)
      ...        Free workspace
      ...        Source text ↓ (grows down)
    XXXX-1       workend — last free workspace byte
    XXXX         CSE CODE (position determined by build size)
      ...        CSE RODATA
      ...        CSE BSS
    $CFFF        CSE runtime end (contiguous, no gaps)
    $D000-$DFFF  I/O (VIC-II, SID, CIA1, CIA2)
    $E000-$FFFF  Banked data under KERNAL ROM (see § Banked layout)

The runtime start address XXXX is not fixed — it floats based on
the combined size of CODE + RODATA + BSS:

    XXXX = $D000 - sizeof(CODE + RODATA + BSS)

This maximizes the workspace automatically.  With the current 6510
build (~21 KB code + rodata, ~800 B BSS), XXXX ≈ $7D00, giving
~29 KB of workspace ($0800–$7CFF).  As the codebase grows or
shrinks, workend adjusts and the user sees it via `i`.

BASIC ROM ($A000-$BFFF) is unmapped at startup.  The RAM underneath
is part of the CSE runtime (code spans across $A000 freely).

KERNAL ROM ($E000-$FFFF) remains mapped.  The RAM underneath is
**read** by clearing bit 1 of $01.  No SEI is needed around the
toggle: the $FFFE RAM shadow holds `cse_brk_handler_early`, which
transparently services an IRQ that fires while KERNAL is banked
out (insert a bank_out_stub frame, bank KERNAL in, delegate to
$EA31, let KERNAL's RTI land at bank_out_stub which banks out
again and RTIs the original frame).  The $FFFA RAM shadow points
directly at `cse_nmi_handler` — no shim is needed because the
6502 sets I=1 as part of the NMI vector sequence.  **Writes
always pass through** to the underlying RAM regardless of $01
bit 1, so pure-writer code (`sym_clear`, `setup_interrupts`, the
SCREEN→`repl_screen` save in `enter_editor`) does not bank —
only readers do.

The `kernal_out` flag in BSS lets long-running batches (e.g.
`asm_assemble` over both passes) hold the KERNAL banked out across
many inner calls without paying a `$01` write per call: when set,
`kernal_bank_out` and `kernal_bank_in` both short-circuit to `rts`.

### Banked layout ($E000–$FFFF)

All data under the KERNAL ROM is initialized by the loader at
startup.  KDATA regions are copied from the PRG payload; KBSS
regions are zeroed (no PRG space required).

    $E000-$E5FF  KBSS: symbol table (1536 B, 256 slots × 6B)
    $E600-$EEFF  KBSS: symbol name heap (2304 B)
    $EF00-$F0FF  Free (512 B — reclaimed after Phase 18 dropped two-image stack swap)
    $F100-$F4F1  KDATA: asm/dasm lookup tables (1010 B)
    $F4F2-$F8D9  KBSS: REPL screen save buffer (1000 B)
    $F8DA-$F958  KBSS: cold-init ZP snapshot (127 B, $01-$7F)
    $F959-$FFF9  Free (1697 B)
    $FFFA-$FFFB  NMI vector → cse_nmi_handler (direct — the 6502 sets
                 I=1 as part of the NMI vector sequence, so no SEI
                 shim is needed)
    $FFFC-$FFFD  Reset vector (untouched — ROM value)
    $FFFE-$FFFF  IRQ/BRK vector → cse_brk_handler_early

    KDATA total:  1010 B (in PRG payload — vectors only, no trampolines)
    KBSS total:   4967 B (zeroed, no PRG space)
    Free:         2209 B

## Stack contract

CSE and user code **share** the single 6502 hardware stack page at
`$0100–$01FF`.  Transitions between kernel and userland are flat
RTI/RTS-driven and cost ~20 cycles each direction.

The kernel is structured as an interrupt service routine
(see [design_cse_as_kernel.md](design_cse_as_kernel.md)).  It
inherits whatever SP the previous transition left it with, runs
with balanced JSR/RTS discipline within that envelope, and never
reads bytes below the current user SP.

### Invariants

1. **Cold init starts at SP=$FF** and the kernel preserves the
   "main_loop top has SP=$FF" convention through every iteration.
2. **The kernel never pushes below the user's SP.**  All kernel
   pushes happen above user's SP at the moment of break; bytes the
   user had at-or-below SP are preserved.
3. **The user must leave at least 64 bytes of stack headroom** for
   kernel re-entry on break (BRK frame + handler chain + safety
   margin).  See [userland_contract.md § 4](userland_contract.md#4-stack-contract).
4. **`in_userland` flag tracks mode**, not SP layout.  The flag is
   the single source of truth for "kernel or user code currently
   running" and drives NMI dispatch.

### Entry (kernel → user): `return_to_userland`

```
return_to_userland:
  1. lda reg_p            ; user's saved P
  2. ora #$04             ; ensure I=0 from user's view? no — preserve user's I
                          ; (in practice, kernel masks P transport bits and
                          ; user-set bits are honoured)
  3. ; push brk_stub-1 high/low onto stack — user's top-level RTS sentinel
     lda #>(brk_stub - 1) ; pha
     lda #<(brk_stub - 1) ; pha
  4. ; build RTI frame: P, PChi, PClo (in that push order)
     lda reg_p   ; pha
     lda reg_pc_hi ; pha
     lda reg_pc_lo ; pha
  5. lda #1
     sta in_userland       ; mark mode
  6. ldx reg_x
     ldy reg_y
     lda reg_a
  7. rti                    ; CPU pops PClo/PChi/P, jumps to user PC
```

After step 7, user code is running.  Below SP are: PClo, PChi, P
(consumed by the RTI), then `brk_stub-1 lo`, `brk_stub-1 hi`, then
the kernel's pre-call state.  When user code performs its top-level
RTS, the CPU pops `brk_stub-1` and lands at `brk_stub`, which BRKs
immediately.

### Exit (user → kernel): three paths into `cse_brk_handler`

All three converge on `cse_brk_handler` (main.s):

- **BRK at debugger breakpoint** — opcode at user PC was overwritten
  with $00.  Handler classifies via `dbg_bp_find` on (pushed_PC − 2)
  → known slot.
- **BRK at step-BRK slot** — temporary breakpoint placed by
  `cmd_step` for `t`/`o` single-step.
- **BRK at `brk_stub`** — user's top-level RTS popped the sentinel.
  Handler classifies (PC − 2 == brk_stub address) → clean exit,
  `dbg_reason = 0`.
- **NMI in userland** — `cse_nmi_handler` reads `in_userland`,
  routes to the BRK-style entry path so the same capture logic runs.
  `dbg_reason = DBG_NMI`.
- **Unplanned BRK** — opcode $00 in user code at an address that's
  not a slot and not `brk_stub`.  Reported as user BRK.

The handler:

```
cse_brk_handler:
  1. ; entered with B-flag dispatch already done at $FF48
  2. clear in_userland
  3. ; capture user state: A/X/Y from KERNAL pushes, P/PC from CPU pushes
  4. ; mask P transport bits (#%11011111 — clear bit 5, keep B=1)
  5. ; classify; populate dbg_reason / dbg_bp_hit / brk_pc / reg_*
  6. ; longjmp back to main_loop top
     ldx kernel_init_sp ; or ldx #$FF
     txs
     jmp main_loop_top
```

The longjmp at step 6 discards every byte on the stack between the
BRK frame and the kernel's main_loop entry SP.  Anything the kernel
had pushed before `return_to_userland` is *not used* on the return path:
the BRK handler does not return to "after return_to_userland" — it
restarts the REPL loop afresh, displays the break result, and
prompts again.

This is structurally a `setjmp`/`longjmp` with the setjmp implicit
at main_loop top and the longjmp inside the BRK handler.

### IRQ-safety

Bank-toggle windows (any code path that clears $01 bit 1 to read
under-kernal RAM) must run with `I=1`.  This was already true under
the old two-image design and remains true: any IRQ fired while
kernal is banked out routes to `cse_brk_handler`'s **early-entry**
label (the $FFFE RAM shadow), which detects the banked-out state by
the very fact of being reached and banks the kernal back in via
stack surgery before its final RTI.

The early-entry path is reached only from RAM-resident vectors —
i.e. only when kernal is banked out.  Reaching it is itself the
signal that the kernal must be banked out before the final RTI.

### Cold-start sentinel

Cold init synthesises the very first userland frame:

```
cold_init_userland_handoff:
  ldx #$FE
  txs                       ; SP = $FE
  lda #>(brk_stub - 1)
  sta $01FF
  lda #<(brk_stub - 1)
  sta $01FE                 ; sentinel below the upcoming RTI frame
  ldx #$FB
  txs                       ; reserve room for RTI frame
  lda #$00 / pha            ; PClo for RTI
  lda #...   / pha          ; PChi for RTI
  lda #%00100000 / pha      ; P (clean: I=0, B=0, bit 5 set as RTI restores it)
  lda #1
  sta in_userland
  rti                       ; → BRK handler via brk_stub immediately
```

(Details vary by implementation; the contract is "RTI to brk_stub,
sentinel below.")  The BRK fires, classification matches "PC ==
brk_stub", `dbg_reason = 0`, handler longjmps to the warm-start tail
at the late-entry label that skips the screen clear (the splash is
already drawn).  REPL runs normally.

This shares cold init's post-init code path with userland recovery
— the same code that handles a clean `j`-then-RTS handles cold boot.

### Kernel stack budget

The kernel's worst-case stack consumption is bounded by two paths:

- **Forward path** (main_loop top → return_to_userland):
  `main_loop → exec_line → cmd_X → [helper chain] → return_to_userland`.
  Currently ~10 B for execution commands.
- **BRK-return path** (BRK hardware/KERNAL push + handler chain
  before longjmp / step-chain): currently ~8 B above user's SP.

The deeper of the two — and the one the user must accommodate — is
the BRK-return path, because it consumes user's stack page above
user's pre-break SP.  The forward path runs in kernel-owned space
($FF down) and never touches user's region.

The userland contract states **64 bytes** as the required headroom,
deliberately conservative pending empirical measurement (see
[TODO.md § Phase 18](TODO.md)).  The 64 B reserves room for:

- Current BRK + handler chain (~14 B).
- Future debugger features (conditional BPs, trace BPs that call
  io_puts/screen.s, watchpoints) that may invoke deeper kernel
  paths from the handler tail — bounded by the deepest kernel
  chain in the system, which today is the assembler pipeline
  (`asm_src` → `asm_line` → `expr_eval` recursive descent).
- Safety margin.

**Pending implementation:** an audit measurement of `asm_src`'s
peak depth + worst-case BRK-handler tail.  Once known, the contract
tightens to the measured-plus-margin figure and CSE adds a runtime
re-entry warning (`;!stk N` log when user's SP is below the budget
at BRK-handler entry).  See [userland_contract.md § 4](userland_contract.md#4-stack-contract).

### User stack budget

User code sees ~240 bytes of free stack on first entry (256 −
kernel chain at return_to_userland − sentinel − RTI frame).  User code
that resets SP to $FF and provides its own top-level return path
gets the full 256 bytes; the brk_stub sentinel is then overwritten
and the user's RTS must land somewhere meaningful explicitly.

### Cost

Per user-entry:    ~20 cycles (push sentinel, push RTI frame, RTI)
Per user-exit:     ~20 cycles (BRK hardware + KERNAL push + handler entry)

No memcpy, no bank toggles around stack swap.  Negligible.

## Memory Map — PRG Load Image

The PRG file loads at $0801 via `LOAD "CSE",8,1 : RUN`.  At load
time, the file is a flat image:

    $07FF-$0800  PRG load address (2 bytes, file header)
    $0801-$080C  BASIC stub "SYS 2061"
    $080D        Loader code (discardable bootstrap)
      ...        CODE + RODATA payload
      ...        KDATA payload (copied to $F100+ under kernal;
                   KBSS regions are not in file)
    end of file

The loader is the first code to run.  It relocates the payload to
its final position (see § Loader module), then becomes part of the
workspace.  The PRG contains no filler — the file is exactly as
large as the loader + payload.

For D64 distribution, the entire PRG is wrapped with exomizer SFX
compression (~38% smaller, faster disk load).  The SFX stub
decompresses to $0801, then the BASIC stub and loader run normally.
`make run` uses the uncompressed PRG (no decrunch delay).

## Memory Map — Cartridge (CRT)

    $0000-$03FF  System
    $0400-$07E7  Screen RAM
    $0800-XXXX   Workspace (output ↑ / source ↓)
    XXXX-$BFFF   CSE ROM (code + rodata, zero RAM cost)
    $C000-$CFFF  CSE RAM (BSS, 4 KB max)
    $D000-$DFFF  I/O
    $E000-$FFFF  KERNAL ROM + banked data (as above)

The CRT build has no loader — CODE + RODATA live in ROM at their
final address.  Only BSS zeroing, KDATA copy, and KBSS zeroing
are needed at startup.  The CRT init code performs these steps
then jumps to `_main`.

## Loader Module (loader.s)

The loader is a **discardable bootstrap** linked into the PRG
build only.  It runs once at startup, then its memory is
reclaimed as workspace.  Analogous to an ELF loader that maps
segments and jumps to the entry point.

**Responsibilities:**
1. Reset the 6502 hardware stack (`ldx #$FF / txs`)
2. Copy CODE + RODATA from the load position to the runtime
   position (XXXX–XXXX+sizeof(CODE+RODATA)-1)
3. Zero BSS (XXXX+sizeof(CODE+RODATA) through $CFFF)
4. Initialize banked region under kernal (pure writer, no
   banking needed): copy KDATA to $F100+, zero KBSS areas
   (sym_table, heap, screen save).  Vector setup ($FFFA/$FFFE
   shadows) is deferred to `setup_interrupts` in main.s, which
   runs as part of cold init.
5. Jump to `_main` (now at its runtime address)

The loader lives in the LOADER segment, placed at $080D (right
after the BASIC stub).  After step 5, nothing references the
loader — the entire $0800–XXXX range becomes workspace.

Compression uses exomizer SFX wrapping (the entire PRG is wrapped
as a self-extracting binary).  The loader itself is always
uncompressed — the SFX decompresses to $0801 before the loader runs.

**CRT builds** do not link the loader.  The CRT init code
performs only steps 1, 3–5 (stack reset, BSS zero, banked init,
jump to `_main`), since CODE + RODATA are already in ROM.

**C128 consideration:** The loader architecture does not assume
a specific memory banking model.  A future C128-native loader
could copy code to a different bank or address range without
changing the permanent runtime.

## Memory Manager Module (mem.s)

The memory manager is a **permanent module** that consolidates
all runtime memory services.  It consolidates memory management
code formerly scattered across main.s (fill_free_memory),
symtab.s (kernal banking), meminfo.s (segment queries), and
asm_src.s (workspace symbols).

**Exports:**

| Function | Purpose |
|----------|---------|
| `kernal_bank_out` | Clear $01 bit 1 (honours `kernal_out` flag) |
| `kernal_bank_in` | Set $01 bit 1 (honours `kernal_out` flag) |
| `kernal_out` | BSS flag: nonzero = kernal held banked out |
| `cse_start` | Returns runtime start address (XXXX) in A/X |
| `cse_end` | Returns first byte past runtime ($D000) in A/X |
| `cse_zp_end` | Returns first free ZP byte in A |

(Interrupt vector setup moved to `setup_interrupts` in main.s as
of Phase 18; `kernal_init` retired.)

After the loader (or CRT init) jumps to `_main`, the main loop
calls mem.s functions for one-time setup (BASIC unmap, NMI
trampoline, workspace symbols, free memory fill).

The KERNAL banking functions move from symtab.s to mem.s.
symtab.s imports them like any other module.  The ordering rule
for batch callers (bank before flag, flag before unbank) is
unchanged — see the inline documentation.

## Source Code Storage

Source text lives in a gap buffer at the top of the workspace,
growing downward from the CSE runtime start:

    $0800          workstart (fixed)
      ...          assembled output (grows up)
                     ... free gap ...
    buf_base  ←──  source text (grows down toward $0800)
    XXXX           workend + 1 = CSE runtime start

The `workstart` and `workend` symbols are pre-defined in the symbol
table by `_main` (via `define_ws_syms`), usable in assembly (`.org workstart`) and REPL
expressions (`@ workend`, `j workstart`).  `workstart` is always
$0800.  `workend` adjusts when the editor resizes the gap buffer
(`update_workend` in editor.s).

## Zero Page Layout

### Overview

85 bytes ($02–$56), all defined in `src/zp.s` (single source of truth).
41 bytes free ($57–$7F) for user programs.

### Module allocation (6510 build)

| Range | Bytes | Consumer | Variables |
|-------|-------|----------|-----------|
| $02–$07 | 6 | main | `rp_ptr` (2), `rp_ptr2` (2), `rp_tmp` (1), `rp_tmp2` (1) |
| $08 | 1 | asm_line | `_asm_saved_sp` (1) |
| $09–$20 | 24 | assembler | `asm_pc`..`expr_wide` (see § Shared state) |
| $21–$23 | 3 | asm_src | `_as_ptr` (2), `_as_wsize` (1) |
| $24–$26 | 3 | mn_vars | `mn_c1` (1), `mn_c2` (1), `mn_c3` (1) |
| $27 | 1 | mn7/mn6 | `mn7_h_tmp` / `mn6_h_tmp` (1, aliased) |
| $28–$2B | 4 | au_mode | `asm_ptr` (2), `asm_opr` (2) |
| $2C | 1 | opcode_lookup | `_asm_ok_tmp` (1) |
| $2D–$30 | 4 | cse_io | `_io_tmp` (2), `_io_scr` (2) |
| $31–$32 | 2 | disk | `disk_ptr` (2) |
| $33–$36 | 4 | expr | `_ex_tmp` (2), `_ex_digits` (1), `_ex_wide_tmp` (1) |
| $37–$40 | 10 | symtab | hash/probe state, heap pointers |
| $41–$48 | 8 | dasm | decode state, output pointer |
| $49–$56 | 14 | editor | gap pointers, screen scratch |

### Non-concurrent groups

Several module groups never execute simultaneously.  Their scratch
variables could share addresses:

| Group | Modules | ZP | BSS | Active when |
|-------|---------|-----|------|-------------|
| **Assembler** | asm_src, asm_line, opcode_lookup, au_mode, mn7, mn_vars | 41 | 253 | `a` command |
| **Editor** | editor | 14 | 59 | ST_EDIT mode |
| **Disassembler** | dasm | 8 | 24 | `d`/`t`/`o` |
| **Disk I/O** | disk | — | 67 | `l`/`s`/`$` |
| **Always active** | main, cse_io, symtab, expr, repl | 27 | 116 | any time |

Assembler and editor are fully non-concurrent.  Assembler and
disassembler are also non-concurrent.  Expression evaluation
(`expr`) is called from both REPL and assembler — cannot overlap.

### Optimization opportunities

**ZP overlap** — investigated 2026-04-08, both candidates
unsafe, dropped:

| Overlap | Why unsafe |
|---------|------------|
| Editor scratch ↔ assembler scratch | `asm_src.s` calls `ed_read_line` (`asm_src.s:1204`), which uses `ed_scr`/`ed_tmp` from the editor's ZP block.  Editor ZP is therefore live during the `a` command. |
| Dasm ↔ assembler scratch | `repl.s::cmd_dot` calls `dasm_insn` (`repl.s:765`) inside the `.` command path that *also* runs `asm_line` for verification.  Both modules' ZP are concurrently live. |

The earlier estimate of ~12 B savings was a paper analysis
that didn't trace the actual call graph.  Both overlaps are
blocked by cross-module calls.  No code change.

**BSS overlap** (not yet implemented):

| Buffer A | Size | Buffer B | Size | Saving | Constraint |
|----------|------|----------|------|--------|------------|
| asm_src `_line_buf` | 40 | repl `line_buf` | 42 | 40 | Assembler doesn't run from REPL line buffer |
| asm_src `_full_label` | 48 | editor `ws_buf` | 39 | 39 | Editor not active during assembly |
| dasm `_dasm_buf` | 24 | repl `dot_asm_buf` | 24 | 24 | Disasm output consumed before `.` command |
| **Total BSS reclaimable** | | | | **~105 B** | |

**Completed optimizations:**
- `_kernel_zp_buf` trimmed: $5E → $5A (4B BSS saved)
- Parameter stack eliminated: `pushax`/`cse_popax`/`sp` removed,
  all multi-arg calls use ZP variables
- Symbol table doubled: 128 → 256 slots, moved to $E000 under KERNAL
- Name heap moved under KERNAL at $E600 (2304B), frees main RAM
- BUF_END raised: $C800 → $D000 (+2KB workspace)
- KDATA tables under KERNAL: 1010B of lookup tables at $F100+
- Packed opcode→length table: 64B, replaces dasm_insn in cmd_step
  (5× faster stepping)

### KERNAL ZP locations (read/written directly)

| Address | Name | Purpose |
|---------|------|---------|
| $00–$01 | CPU I/O port | Memory banking ($01 bit 1 = KERNAL) |
| $C6 | KEY_COUNT | Keyboard buffer count (read by `io_kbhit`) |
| $CC | CURS_FLAG | Set to 1 at startup (disables KERNAL cursor) |
| $D1–$D2 | Screen line ptr | Updated by `io_sync` via KERNAL PLOT |
| $D3 | CUR_COL | Cursor column (0–39) |
| $D6 | CUR_ROW | Cursor row (0–24) |
| $F3–$F4 | Color line ptr | Updated by `io_sync` via KERNAL PLOT |
