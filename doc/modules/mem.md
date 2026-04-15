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

### kernal_init
**In:** none
**Out:** NMI trampoline at $FF00, IRQ/BRK trampoline at $FF04,
RAM vectors at $FFFA/$FFFE pointed at trampolines
**Clobbers:** A, X

Called once at startup.  Pure writer — stores pass through to
RAM under KERNAL regardless of $01 bit 1.

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

### NMI/IRQ trampolines

When KERNAL ROM is banked out, the CPU reads NMI/IRQ vectors from
RAM at $FFFA/$FFFE.  `kernal_init` installs:

- **$FF00** (4B): NMI trampoline — `SEI; JMP ($0318)`.  The handler
  chain (`cse_nmi_handler`) runs entirely in main-RAM CODE.
- **$FF04** (10B): IRQ/BRK trampoline — saves A, banks KERNAL in,
  restores A, `JMP $FF48`.  Defensive: fires only if BRK occurs
  while KERNAL is out (contract violation).

### Workspace symbols

`define_ws_syms` pre-defines two labels so user programs can
reference the workspace boundaries:
- `workstart` = $0800 (fixed)
- `workend` = `buf_base - 1` (shrinks as source grows)

Called by `main.s` at startup and by `asm_assemble` after `sym_clear`.

## Caveats

- Pure writes to $E000–$FFFF always hit RAM, even with KERNAL
  mapped in.  Only reads require banking.
- `kernal_bank_out` disables interrupts (SEI); `kernal_bank_in`
  re-enables them (CLI).  Batch callers that set `kernal_out` must
  ensure interrupts are managed correctly.
- The NMI trampoline does NOT modify $01 — earlier designs that
  did so permanently corrupted the banking state after RTI.
