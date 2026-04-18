# mem — Memory manager: banking, ZP save/restore, segment queries, workspace symbols

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/mem.s`](../../src/mem.s) | implementation |

## Interface

### kernal_bank_out
**In:** none
**Out:** KERNAL ROM hidden (bit 1 of $01 cleared).  I flag preserved
(Phase 18 IRQ early-entry handles IRQ-during-bank-out transparently).
**Clobbers:** A

No-op when `kernal_out` flag is set (batch caller managing banking).

### kernal_bank_in
**In:** none
**Out:** KERNAL ROM restored (bit 1 of $01 set).  I flag preserved.
**Clobbers:** A

No-op when `kernal_out` flag is set.

### save_userland_zp / restore_userland_zp / save_kernel_zp / restore_kernel_zp
**In:** none
**Out:** matching 128-byte ZP buffer mirrors live $00..$7F (save
variants) or vice versa (restore variants).  save variants leave
live $00=$FF as a postcondition (documented side effect of the
single-pass DDR-stash pattern).
**Clobbers:** A, X (save variants also clobber Y).

Four CPU-port-aware primitives that swap live ZP against
`userland_zp_buf` / `kernel_zp_buf`.  See the CPU-port protocol
note at the top of the save/restore procs in `mem.s` for the
full rationale (DDR masking, single-pass save with Y-stash,
backwards restore with DDR=$FF).

Called by `debugger.s`:
- `save_userland_state` invokes `save_userland_zp` +
  `restore_kernel_zp` (exit: capture user ZP, restore kernel ZP).
- `_rtu_body` (shared by `return_to_userland` and
  `restore_userland_state`) invokes `save_kernel_zp` +
  `restore_userland_zp` (entry: capture kernel ZP, restore user ZP).

### cse_start
**In:** none
**Out:** A/X = `__CODE_RUN__` (runtime start address)

### cse_end
**In:** none
**Out:** A/X = $D000 (HIMEM, first byte past runtime)

### cse_zp_end
**In:** none
**Out:** A = first free ZP byte (`__ZP_LAST__ + 1`)

### define_ws_syms
**In:** none (reads `buf_base` from editor ZP)
**Out:** defines `workstart` ($0800) and `workend` (`buf_base - 1`)
in the symbol table via `sym_define`
**Clobbers:** A, X, Y, sym_name, sym_val, sym_wide

**State:**

| Variable | Size | Segment | Purpose |
|----------|------|---------|---------|
| `kernal_out` | 1 | BSS | Nonzero = KERNAL held banked out (batch mode) |
| `userland_zp_buf` | 128 | BSS | User's $00..$7F snapshot (captured on userland exit) |
| `kernel_zp_buf` | 128 | BSS | Kernel's $00..$7F snapshot (captured on userland entry) |

**Depends on:** zp (buf_base), symtab (sym_define, sym_name, sym_val, sym_wide),
strings (s_workstart, s_workend)

## Design

### Banking protocol

Both `kernal_bank_out` and `kernal_bank_in` short-circuit when
`kernal_out` is nonzero.  Batch callers (e.g. `asm_assemble`) must
perform the real bank operation BEFORE setting/clearing the flag:

    ; enter batch          ; leave batch
    jsr kernal_bank_out    lda #0
    lda #1                 sta kernal_out
    sta kernal_out         jsr kernal_bank_in

### Interrupt vectors (Phase 18: trampolines retired)

mem.s no longer owns interrupt setup.  The `setup_interrupts`
routine in main.s patches all four vectors directly during cold
init:

- $0316/$0317 (IBRK)  → `cse_brk_handler` (kernal-in entry)
- $0318/$0319 (INMIV) → `cse_nmi_handler` (kernal-in entry)
- $FFFA/$FFFB (NMI shadow under kernal ROM)     → `cse_nmi_handler` (direct)
- $FFFE/$FFFF (IRQ/BRK shadow under kernal ROM) → `cse_brk_handler_early`

There are no separate trampolines at $FF00 / $FF04.  The BRK
early-entry prologue is part of the handler body in main.s and
executes only when the CPU read the vector from RAM (i.e. when
kernal was banked out at the moment of interrupt).  NMI needs no
early-entry shim: the 6502 sets I=1 as part of the NMI vector
sequence, so IRQ interleaving is already prevented.

See [main.md](main.md) for handler details and [memory_design.md
§ Stack contract](../memory_design.md#stack-contract) for the
overall kernel↔userland model.

### CPU-port aware ZP save/restore

The `save_userland_zp` / `restore_userland_zp` / `save_kernel_zp`
/ `restore_kernel_zp` primitives preserve/restore ZP $00..$7F
across kernel↔userland transitions.  $00 (CPU port DDR) and
$01 (data) need special handling because bits configured as
input by $00 read external state, not the value the CPU wrote.

**Save (single-pass DDR stash):**
```
ldy $00              ; snapshot current DDR
lda #$FF / sta $00   ; DDR := all-output (unmask $01)
ldx #$7F
@loop: lda $00,x / sta buf,x / dex / bpl @loop
sty buf              ; overwrite buf[$00] (transient $FF) with saved DDR
```
During the loop, x=$01 reads $01 with every bit CPU-driven
(DDR=$FF), so `buf[$01]` gets the fully latched byte.  The
loop's x=$00 iteration captures the transient $FF; the `sty`
overwrites it with the real DDR.  Postcondition: live $00 = $FF.

**Restore (backwards copy, DDR=$FF inherited from prior save):**
```
ldx #$7F
@loop: lda buf,x / sta $00,x / dex / bpl @loop
```
Precondition: live $00 = $FF (postcondition of the paired
`save_*_zp`, which is the only legitimate predecessor).
Backwards iteration writes `buf[$01]` (x=$01) while DDR=$FF —
full latch.  Then writes `buf[$00]` (x=$0, LAST) — re-applies
the target DDR mask after data bits are set.  No redundant
`lda #$FF / sta $00` at entry: a belt-and-suspenders write
would only mask a regressed save postcondition.

**Bootstrap seed:** `debugger.s::dbg_init` pre-seeds both
buffers with `$00=$2F` / `$01=$36` so the first return_to_userland
(before any userland has populated `userland_zp_buf`) doesn't
restore zeros into the live CPU port.

### Workspace symbols

`define_ws_syms` pre-defines two labels so user programs can
reference the workspace boundaries:
- `workstart` = $0800 (fixed)
- `workend` = `buf_base - 1` (shrinks as source grows)

Called by `main.s` at startup and by `asm_assemble` after `sym_clear`.

## Caveats

- Pure writes to $E000–$FFFF always hit RAM, even with kernal
  mapped in.  Only reads require banking.
- `kernal_bank_out` / `kernal_bank_in` do NOT touch the I flag.
  Phase 18's $FFFE early-entry (`cse_brk_handler_early` +
  `bank_out_stub`) handles an IRQ that fires while KERNAL is
  banked out transparently, so the SEI/CLI pair that used to wrap
  every bank toggle is redundant.  Caller's I state is preserved
  across a bank-out/bank-in pair.
- Interrupt vector ownership has moved to main.s
  (`setup_interrupts`).  mem.s no longer installs trampolines.
