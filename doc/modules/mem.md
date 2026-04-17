# mem — Memory manager: banking, segment queries, workspace symbols

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/mem.s`](../../src/mem.s) | implementation |

## Interface

### kernal_bank_out
**In:** none
**Out:** KERNAL ROM hidden (bit 1 of $01 cleared), interrupts disabled
**Clobbers:** A

No-op when `kernal_out` flag is set (batch caller managing banking).

### kernal_bank_in
**In:** none
**Out:** KERNAL ROM restored (bit 1 of $01 set), interrupts enabled
**Clobbers:** A

No-op when `kernal_out` flag is set.

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
- $FFFA/$FFFB (NMI shadow under kernal ROM)     → `cse_nmi_handler` early-entry label
- $FFFE/$FFFF (IRQ/BRK shadow under kernal ROM) → `cse_brk_handler` early-entry label

There are no separate trampolines at $FF00 / $FF04.  The
early-entry prologues are part of the handler bodies in main.s
and execute only when the CPU read the vector from RAM (i.e.
when kernal was banked out at the moment of interrupt).

See [main.md](main.md) for handler details and [memory_design.md
§ Stack contract](../memory_design.md#stack-contract) for the
overall kernel↔userland model.

### Workspace symbols

`define_ws_syms` pre-defines two labels so user programs can
reference the workspace boundaries:
- `workstart` = $0800 (fixed)
- `workend` = `buf_base - 1` (shrinks as source grows)

Called by `main.s` at startup and by `asm_assemble` after `sym_clear`.

## Caveats

- Pure writes to $E000–$FFFF always hit RAM, even with kernal
  mapped in.  Only reads require banking.
- `kernal_bank_out` disables interrupts (SEI); `kernal_bank_in`
  re-enables them (CLI).  Batch callers that set `kernal_out` must
  ensure interrupts are managed correctly.
- Interrupt vector ownership has moved to main.s
  (`setup_interrupts`).  mem.s no longer installs trampolines.
