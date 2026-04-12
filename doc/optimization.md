# Size Optimization Strategies

Catalog of code-size reduction techniques applied in CSE.  Each entry
shows the pattern, the saving, and an example from the codebase.

## 1. Tail-call elimination

Replace `jsr SUB; rts` with `jmp SUB`.  Saves 1 byte (the `rts`).

```asm
; before (4 bytes)                ; after (3 bytes)
        jsr _bank_out_tmp                 jmp _bank_out_tmp
        rts
```

Used in: `emit_error` → `_bank_out_tmp`, `_emit_word` → `_emit_byte`,
`_emit_byte` → `inc_pc_size`.

## 2. Extract shared inline sequences

When the same instruction sequence appears 3+ times, extract it into
a subroutine.  Break-even is 3 call sites (the `jsr` overhead = 3 bytes
per site; the subroutine body + `rts` = original_size + 1).

```asm
; before: 8 bytes inline × 3 sites = 24 bytes
        sei
        lda $01
        ora #$02
        sta $01
        cli

; after: 14 bytes (subroutine) + 3 × 3 bytes (jsr) = 23 bytes
_bank_in_tmp:
        sei
        lda $01
        ora #$02
        sta $01
        cli
        rts
```

Used in: `_bank_in_tmp`/`_bank_out_tmp` (3 call sites each).

## 3. Downward loop with `dex; bpl`

A loop counting from N-1 down to 0 costs 2 bytes (`dex; bpl @loop`).
An upward loop costs 4 bytes (`inx; cpx #N; bne @loop`).  Saves 2
bytes when the iteration order doesn't matter, or when the data table
can be reversed.

```asm
; before (4 bytes)                ; after (2 bytes)
        inx                               dex
        cpx #5                            bpl @dgt
        bne @dgt
```

Used in: `_emit_decimal` (power tables reversed to match downward index).

## 4. Fixed-format output to avoid sizing logic

When the consumer tolerates padding (leading zeros, fixed-width fields),
emit a fixed number of bytes instead of computing the variable length.
Eliminates the length-computation code entirely.

```asm
; before: _count_digits (30 B) + iteration loop (50 B) = 80 B
; after: always emit 5 digits, stub size = constant.  0 B overhead.
```

BASIC `SYS 02062` works identically to `SYS 2062`.  By always emitting
5 decimal digits, the SYS address becomes `asm_pc + constant` — no
digit-count iteration, no `_count_digits` routine.

Used in: `.bas` directive (`_emit_decimal` always 5 digits).

## 5. Merge pass-check into existing register load

When a function needs to check `_asm_pass` and also set up a register,
combine them if the check result can serve double duty.

```asm
; before (5 bytes)                ; after (4 bytes)
        pha                               ldy _asm_pass
        lda _asm_pass                     beq @skip
        beq @skip                         ldy #0
        pla                               sta (asm_pc),y
        ldy #0                    @skip:  jmp inc_pc_size
        sta (asm_pc),y
        jmp inc_pc_size
@skip:  pla
        jmp inc_pc_size
```

The `ldy _asm_pass` loads Y with the pass number.  If pass 0, Y is
already 0 — but we branch past the store anyway.  If pass 1, we
reload Y=0 for the indirect store.  Saves the `pha/pla` pair.

Used in: `_emit_byte`.

## 6. Streaming output instead of collect-then-print

Print results inline as they are computed, instead of collecting into
a table and iterating the table afterward.  Eliminates the table BSS,
the iteration loop, and the index arithmetic.

```
; before: 40 B BSS table + 230 B print loop + 46 B state = 316 B
; after:  7 B BSS state + ~150 B inline print at event sites = 157 B
```

Each `.org` prints its segment line immediately during pass 1.  No
post-hoc table scan needed.

Used in: per-segment assembly summary.

## 7. Collapse multi-structure output into single structure

When the output format allows combining distinct structures into one,
do so to eliminate the overhead of structure headers and link pointers.

```
; before: 2 BASIC lines (REM + SYS) = 2 link pointers, 2 line numbers
;         separate REM emission branch + SYS emission branch
; after:  1 BASIC line (SYS:REM) = 1 link pointer, 1 line number
;         straight-line emission with optional :REM tail
```

`0 SYS addr:REM text` is one BASIC line.  Eliminates the second link
pointer computation, second line number, and the if/else branch for
the REM-vs-SYS-only case.

Used in: `.bas` directive (single-line `:REM`).

## 8. Register loop counter instead of BSS variable

When a loop counter's lifetime is confined to one subroutine and
the register is free, use X or Y directly instead of a BSS byte.
Saves the `lda`/`sta` memory round-trips (2 bytes each access).

```asm
; before (BSS counter)            ; after (X register)
        lda #0                            ldx #0
        sta _ib_idx               @lp:    cpx _eb_idx
@lp:    lda _ib_idx                       beq @done
        cmp _eb_idx                       txa
        beq @done                         tay
        tay                               lda (expr_ptr),y
        lda (expr_ptr),y                  jsr _emit_byte
        jsr _emit_byte                    inx
        inc _ib_idx                       bne @lp
        bne @lp
```

Used in: `.bas` string copy loop.

## 9. Invert branch sense to eliminate jmp

When a conditional branch goes to a nearby label but the
fall-through path needs a `jmp` to a distant label, flip the
branch condition so the common path falls through.

```asm
; before (5 bytes)                ; after (2 bytes)
        cmp #';'                          cmp #';'
        beq @no_operand                   bne @has_operand
        jmp @has_operand          @no_operand:
@no_operand:
```

Used in: `process_line` operand detection.

## 10. Apply helpers retroactively to old code

When a new helper is created (e.g. `_emit_byte`), audit ALL existing
code for inline patterns that the helper replaces.  Old code written
before the helper exists will still have the inline version.

Used in: `emit_data_bytes`, `emit_string`, `emit_reserve`, `emit_align`
all had inline emit+pass-check patterns that were replaced with
`jsr _emit_byte` after `_emit_byte` was introduced for `.bas`.

## 11. DRY within a module

When the same inline sequence appears twice in one module, extract
it into a local subroutine — even if it's only 2 call sites.  Unlike
cross-module extraction (which adds export/import overhead), within
a module the `jsr` is the only cost.

Used in: `skipws_as` extracted from two inline whitespace-skip loops
in `process_line` (label scan + mnemonic/operand separator).

## 12. Design helpers for maximum reuse

When creating a helper, invest time to make its interface generic
enough to serve all current AND future callers.  A slightly more
general calling convention (e.g. value in A instead of a fixed
BSS location) may cost 1-2 extra bytes in the helper but save
many more across call sites.

Example: `_emit_byte` takes the byte in A, checks `_asm_pass`
internally, and calls `inc_pc_size`.  This interface is generic
enough for `.db`, `.dw`, `.str`, `.scr`, `.res`, `.align`, `.bas`,
and `_emit_decimal` — 8 consumers from one 7-byte helper.

Counter-example: a helper that reads from `expr_val` directly
would only serve expression-emitting call sites, forcing the
others to set up `expr_val` first or use inline code.

The investment pays compound returns: each new directive or
feature that emits bytes gets the pass-check for free.

## 13. Register as direct character accumulator

When a loop produces a character from a counter (e.g. digit count
→ `adc #$30` → PETSCII), use a register initialized to the base
character code and increment it directly.  Eliminates the separate
counter variable and the post-loop conversion.

```asm
; before (7 bytes init+convert)   ; after (2 bytes init, 0 convert)
        lda #0                            ldy #$30       ; PETSCII '0'
        sta asm_tmp               @sub:   ...subtract...
@sub:   ...subtract...                    iny            ; Y = '0','1',...'9'
        inc asm_tmp                       bne @sub
        bne @sub                  @done:  tya            ; ready to emit
@done:  lda asm_tmp
        clc
        adc #$30
```

Used in: `_emit_decimal` — Y counts from '0' through '9' directly.

## 14. Reuse ZP scratch across non-overlapping phases

When two code paths never execute simultaneously, their ZP scratch
bytes can share the same address.  The 6502's limited ZP is a
scarce resource; overlapping non-concurrent uses maximizes it.

```asm
_as_wsize:  .res 1   ; word size in emit_data_bytes
                      ; reused as scratch in .const, emit_align, etc.
```

Used in: `_as_wsize` (word size, digit counter, general scratch),
`asm_tmp`/`asm_tmp2` (instruction scratch, SYS address, close address).
