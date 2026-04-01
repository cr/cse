# asm_line.s — Single-Line Instruction Assembler

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/asm_line.s`](../../src/asm_line.s) | implementation |
| [`src/asm_bridge.s`](../../src/asm_bridge.s) | implementation — C↔asm bridge, PETSCII→VICII, error recovery, `_jsr_addr` user-code runner, register capture |
| [`src/asm_vars.s`](../../src/asm_vars.s) | implementation — shared ZP variable definitions |
| [`tests/test_asm_line.py`](../../tests/test_asm_line.py) | test contract |

## Interface

### al_line_asm
**In:** `au_ptr` (ZP, text pointer, VICII screencodes), `al_pc` (ZP, address),
`al_out` (ZP, output pointer), `al_cpu` (ZP, CPU mode), Y=0
**Out:** bytes written to `[al_out]`, `al_len` = byte count (1–3),
C = 0 (clear) on success
**Clobbers:** A, X, Y, all al_* ZP vars

### _asm_line (C wrapper, in asm_bridge.s)
**In:** A/X = text pointer (PETSCII), C stack = address (uint16)
**Out:** A = byte count (0 = error)
**Clobbers:** all

The C wrapper converts the text buffer from PETSCII to VICII screen
codes in-place before calling `al_line_asm`.

**Depends on:** opcode_lookup, au_mode, mn_classify (mn_base_op,
mn_profile), mn7 tables

## Design

**Zone dispatch:** The mnemonic's operand profile (from mn7_profile)
determines which zone handles assembly.  30 profiles mapped to 8 zones:

| Zone | Profiles | Mode | Examples |
|------|----------|------|---------|
| A | 0 | Implied | BRK, CLC, DEX, NOP, RTS, ... |
| B | 1 | Relative (branch) | BCC, BEQ, BNE, BPL, ... |
| C | 2 | Immediate | LDX #$00, CPX #$FF, ... |
| D | 3 | Bit-op ZP (RMB/SMB) | RMB0–7, SMB0–7 |
| E | 4 | Bit-op ZP,REL (BBR/BBS) | BBR0–7, BBS0–7 |
| F | 5 | Absolute (JSR only) | JSR $XXXX |
| G | 6–15 | Multi-mode (2–5 modes) | LDX, STX, CPX, CPY, DEC, INC, ... |
| H | 16–29 | Multi-mode (3–8 modes) | LDA, STA, ADC, AND, ORA, JMP, ... |

Zones A–F handle fixed single-mode instructions inline.  Zones G and H
call `au_parse_mode` to determine the addressing mode, then
`al_opcode_lookup` to compute the opcode byte.

**Error handling:** On any error, `jmp al_error` (in asm_bridge.s)
restores the 6502 SP from `_ab_saved_sp` and returns 0 to the caller.

## Caveats

- Input must be VICII screen codes (A=$01..Z=$1A), not PETSCII.
  The C wrapper in asm_bridge.s handles conversion.
- `al_cpu` values: 0=6502, 1=6510, 2=65C02 (see repl.c, dasm.s).
  **Note:** asm_line.s treats al_cpu as boolean (0=NMOS, nonzero=CMOS)
  — `beq`/`bne` only.  See TODO.md for 3-valued fix.
- Zone B accepts `$XXXX` absolute target for branches; computes
  signed offset internally.
- `mn7_classify` clobbers Y (sets Y=mn_c2).  `ldy #0` is required
  before zone dispatch.
