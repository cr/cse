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

**Caveat:** The base value depends on whether leading zeros are emitted
or stripped.  If a post-loop strip phase removes zero-digits, use
`$2F` (one below '0') so stripped positions hold a sentinel.  If all
digits are emitted (fixed-width), use `$30` ('0') so digit=0 emits
'0' correctly.  Getting this wrong produces '/' ($2F) in the output.

Used in: `_emit_decimal` — Y counts from '0' through '9' directly.

## 14. Consolidate exit points into shared `@done: rts`

When a proc has multiple early-exit `rts` instructions, replace
them with `jmp @done` (or `beq @done`) to a single shared `rts`.
Combine with a shared `@bad` error handler at the proc tail.

Saves 1 byte per eliminated `rts` minus the `jmp` cost (2 net per
converted site when using conditional branch, 0 net with `jmp`).
The real win is when the shared tail also holds error handling
code that was previously duplicated.

**Caveat on flag-based elimination of `cpy #0` / `cpx #0`:**
Only safe when the Z flag comes from an instruction that operates
on the register being tested.  Safe after: `dey`, `dex`, `iny`,
`inx`, `ldy`, `ldx`, `tay`, `tax`.  UNSAFE after: `cmp`, `beq`/`bne`
fall-through, `adc`, `sbc` — Z reflects the comparison or
arithmetic result, not the register value.

Used in: `process_line` — shared `@done: rts` and `@bad` error tail.
`cpy #0` removed after `dey` (safe); kept after `@wscan` loop exit
(Z from `cmp`, not Y).

## 15. Reuse ZP scratch across non-overlapping phases

When two code paths never execute simultaneously, their ZP scratch
bytes can share the same address.  The 6502's limited ZP is a
scarce resource; overlapping non-concurrent uses maximizes it.

```asm
_as_wsize:  .res 1   ; word size in emit_data_bytes
                      ; reused as scratch in .const, emit_align, etc.
```

Used in: `_as_wsize` (word size, digit counter, general scratch),
`asm_tmp`/`asm_tmp2` (instruction scratch, SYS address, close address).

## 16. Extract operator preamble across precedence levels

When a recursive-descent parser has N binary operators at K
precedence levels, and each operator handler starts with the same
setup sequence (advance pointer, skip whitespace, save state, push
left operand), extract that preamble into a shared subroutine.

```asm
; before: 16 bytes inline × 9 operators = 144 bytes
@add:   jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        ...push expr_val...
        jsr parse_mul

; after: 13-byte subroutine + 9 × 9-byte call site = 94 bytes
_ex_op_setup:
        jsr _ex_adv_ptr
        jsr skip_sp
        lda expr_wide
        sta _ex_wide_tmp
        rts

@add:   jsr _ex_op_setup
        ...push expr_val...
        jsr parse_mul
```

**Caveat:** Values pushed onto the hardware stack inside a
subroutine end up *under* the return address.  Either keep the
pushes at the call site (as shown), or use a trampoline that
swaps the return address around the pushed values.

A secondary entry point (`_ex_op_setup_2adv`) handles two-character
operators like `<<` and `>>` that need two `_ex_adv_ptr` calls.

Used in: `expr.s` — 9 operators (`& | ^ + - * / << >>`) across
3 precedence levels (`parse_expr`, `parse_add`, `parse_mul`).

## 17. Extract repeated ZP-to-ZP pointer copies as helpers

When the same `lda src / sta dst / lda src+1 / sta dst+1` copy
appears 4+ times within a module, extract it as a local subroutine.
Each call site shrinks from 8 bytes (ZP) or 12 bytes (absolute) to
3 bytes (`jsr`).

Break-even for ZP→ZP copies (8 B inline):
  subroutine = 9 B; each `jsr` = 3 B; saves 5 B per site.
  Break-even at 2 sites (9 + 2×3 = 15 < 2×8 = 16).

Break-even for absolute-indexed copies (e.g. `lda tbl,x / sta zp`):
  subroutine = 11 B; saves 7 B per site.
  Break-even at 2 sites.

```asm
; before: 8 bytes × 5 sites = 40 bytes
        lda gap_hi
        sta ed_scr
        lda gap_hi+1
        sta ed_scr+1

; after: 9-byte subroutine + 5 × 3 = 24 bytes
_ed_scr_ghi:
        lda gap_hi
        sta ed_scr
        lda gap_hi+1
        sta ed_scr+1
        rts
```

Used in: `editor.s` — 5 helpers (`_ed_scr_row`, `_ed_scr_top`,
`_ed_scr_ghi`, `_ed_scr_glo`, `_ed_cur_row`) covering 26 call sites.

## 18. Audit feasibility before applying loop/branch transforms

Not every textbook optimization applies on the 6502.  Before
investing time in a transform, check the constraints:

**Downward loops** (`dex; bpl` replacing `inx; cpx; bne`):
only profitable when the register is a pure counter, not an array
index.  If the loop body uses `lda tbl,x` or `sta buf,y`, reversing
the iteration order changes which elements are accessed first.
Most real loops use the register as an index — the transform
rarely applies in practice.

**Branch inversion** (`bXX+jmp` → `b_inv`): only possible when the
inverted branch can reach the target (±127 bytes).  Cross-module
labels and distant `.proc` entries are usually out of range.
Verify each candidate individually.

Used in: Phase 13 audit — 5 of 8 branch-inversion candidates were
feasible; 0 of 16 downward-loop candidates were profitable
(all used registers as array indices).

## 19. ~~Y=$FF indexed-indirect for adjacent byte read~~ INVALID

**This strategy is wrong.**  `(zp),Y` adds Y as an **unsigned**
offset to the full 16-bit address at `zp`.  With Y=$FF, the
effective address is `ptr + 255`, not `ptr - 1`.  There is no
way to use `(zp),Y` to read backward.

This was applied to `puts_imm` and caused the splash screen
(and all `puts` macro calls) to read garbage for the string
low byte.  Reverted to an explicit 16-bit decrement.

## 20. Stack replaces BSS for cross-call temporaries

When a value must survive one `jsr` call, `pha`/`pla` replaces
a BSS byte.  Saves the `.byte 0` allocation (1 byte) and often
trades `sty`+`lda` (4 bytes) for `tya`/`pha`+`pla` (3 bytes).

```asm
; before (5 bytes + 1 BSS)          ; after (3 bytes)
        sty @lv                             tya
        jsr some_func                       pha
        lda @lv                             jsr some_func
@lv:    .byte 0                             pla
```

Saves 3 bytes per site (2 code + 1 BSS).  The `pha`/`pla` pair
is also faster (3+4=7 cycles vs 4+4=8 cycles for `sty abs`/
`lda abs`).

Used in: `log_open` — saving the level character across a `jsr io_putc`
call that clobbers Y.

## 21. Branchless boolean via ADC/EOR

Convert a carry or compare result into a 0/1 boolean without
branching.  `cmp #threshold / lda #0 / adc #0` produces A=1
if carry was set (>= threshold), A=0 otherwise.  Follow with
`eor #1` to invert.

```asm
; before (7 bytes)                   ; after (5 bytes)
        cmp #$FF                            cmp #$10
        beq @no                             lda #0
        lda #1                              adc #0
        rts                                 eor #1
@no:    lda #0                              rts
        rts
```

Saves 2 bytes and eliminates the branch penalty.

Used in: `_is_hex` — converting `_hex_val` result ($00-$0F valid,
$FF invalid) to a Z-flag boolean.

## 22. Extract semantic helpers (compound operations)

Beyond extracting identical instruction sequences (strategy 2),
extract *semantic operations* — named helpers that encapsulate a
meaningful action, even if there are only 1-2 call sites.  The
inline expansion may be 15-30 bytes; the helper body + single
`jsr` is often half that.

Criteria: if the inline code has a clear *what it does* name
(not just *what instructions it runs*), it's a helper candidate.

```
expr_set_curaddr — try_expr + copy result to cur_addr  (3 sites)
expr_or_blocksize — try_expr with block_size default   (2 sites)
bp_open_slot     — format ";bp N" log prefix           (4 sites)
sym_set_curaddr  — sym_lookup + copy to cur_addr       (2 sites)
```

Each helper is 10-15 bytes; each call site shrinks to 3 bytes.
Even at 2 sites the savings are significant because the inline
code is verbose (conditional branches, pointer copies, formatting).

Used in: `repl.s` — 7 semantic helpers extracted.

## 23. Table-driven dispatch replaces cascaded comparisons

When dispatching on N multi-byte keys (e.g. "02","10","c0"),
a scan loop over a packed table beats N×(cmp/bne) chains.
Saves code proportional to N and scales without new branches.

```asm
; before (~60 bytes): nested cmp/beq for 3 alternatives
; after (~30 bytes): 9-byte table + 3-byte mask + scan loop

cpu_pair_tbl:  .byte '0','2',0, '1','0',1, 'c','0',2
cpu_mask_bits: .byte 1,2,4
```

The table encodes (key1, key2, result_id) triples; the loop
scans linearly.  A companion bitmask table validates the result
against the compile-time CPU configuration.

Used in: `repl.s` — CPU mode command (`u 6502`/`u 6510`/`u 65c02`).

## 24. Extract behavioral units, not byte patterns

When looking for extraction candidates, identify *what the code
does* (a semantic operation), not *which instructions repeat*
(a byte pattern).  A gap-buffer traversal always does: skip the
gap if the pointer is at it, then check for end-of-buffer.  That
two-phase operation is the extractable unit — not the individual
pointer assignment embedded inside it.

```asm
; before: 13 bytes inline × 5 sites = 65 bytes
        lda ed_scr
        cmp gap_lo
        bne @no_gap
        lda ed_scr+1
        cmp gap_lo+1
        bne @no_gap
        <assign gap_hi to ed_scr>
@no_gap:
        lda ed_scr+1
        cmp #>BUF_END
        ...

; after: two helpers (skip_gap_scr + check_buf_end) called together
        jsr skip_gap_scr
        jsr check_buf_end
        bcs @eof
```

The two helpers compose into a single logical operation.  Each
call site drops from 13+ bytes to 6+branch.

Used in: `editor.s` — `ed_render_line`, `skip_one_line`,
`line_vwidth` (5 call sites of the gap-skip + EOF-check pair).

## 25. Swap register roles to eliminate BSS and shuffling

When a loop uses Y for indirect addressing (`lda (ptr),y`) AND as
a counter, the counter must be saved to BSS before each indirect
load and restored after.  If another register (X) is free, swap
their roles: X = counter/index, Y = indirect.  This eliminates
the BSS byte and the save/restore sequence.

```asm
; before (9 bytes per iteration + 1 BSS)
        lda cur_project_name,y      ; Y = filename index
        pha
        txa                     ; X = screen col → Y
        tay
        pla
        sta (ed_scr),y
        tya / tax               ; restore X
        ... inc @fn_idx / ldy @fn_idx

; after (3 bytes per iteration, 0 BSS)
        lda cur_project_name,x      ; X = filename index
        sta (ed_scr),y          ; Y = screen col
        inx
        iny
```

The key insight: `lda abs,x` and `sta (zp),y` can use different
registers simultaneously.  Choose the register assignment that
avoids conflicts.

Used in: `editor.s` — `ed_status` filename loop (eliminated
`@fn_idx` BSS byte, `pha`/`pla` pair, and `jmp` → `bne`);
`visual_col` (X as vcol counter, eliminated `@vcol_save`);
`copy_leading_ws` (X as counter, eliminated `@save_y`);
`line_vwidth` (reuse `char_width` helper, eliminated `@w_save`).

## 26. Consolidate exit trampolines within a proc

When a large dispatch proc has N handlers that all end with
`jsr X / jmp @common_exit`, extract the pair into a shared
trampoline label within the proc.  Saves 3 bytes per site
(eliminates the `jsr`, replacing `jsr X / jmp @exit` with
`jmp @X_exit`).

```asm
; before: 5 sites × 6 bytes = 30 bytes
@left:  ...
        jsr ed_status_pos
        jmp @repos

; after: 6-byte trampoline + 5 × 3 bytes = 21 bytes
@left:  ...
        jmp @status_repos

@status_repos:
        jsr ed_status_pos
        jmp @repos
```

Used in: `editor.s` — `ed_handle_key` has `@status_repos`
(5 call sites) and `@edited_repos` (4 call sites).

## 27. Carry-preserving tail-call

When a subroutine does not modify carry (e.g. `INC`, `LDA`, `STA`,
`LDY` — none affect C on 6502), pre-clear carry before the tail-call
`jmp` so the caller receives C=0.  Replaces `jsr SUB; clc; rts` (5B)
with `clc; jmp SUB` (4B).  Saves 1 byte per site.

```asm
; before (5 bytes)                  ; after (4 bytes)
        jsr _asm_emit                       clc
        clc                                 jmp _asm_emit
        rts
```

Key insight: on 6502, `INC` does NOT affect carry.  Verify the entire
subroutine body preserves C before applying.

Used in: `asm_line.s` — 5 zone exits use `clc; jmp _asm_emit` instead
of `jsr _asm_emit; clc; rts`.

## 28. Remove no-op mask instructions

When a value is naturally bounded (e.g. 8-bit ZP variable),
`AND #$FF` is a no-op that can be deleted.  Similarly, `AND #SYM_MASK`
where SYM_MASK = $FF.  2 bytes per instance.

```asm
; before (4 bytes)                  ; after (2 bytes)
        lda _st_hash                        lda _st_hash
        and #SYM_MASK                       sta _st_idx
        sta _st_idx
```

Used in: `symtab.s` — 4 instances of `and #$FF` removed (-8 B).

## 29. Dedup through caller-preserving subroutine

When a subroutine is proven not to modify a ZP variable, callers can
set that variable once before a loop of calls instead of re-setting
it each iteration.

```asm
; before: set sym_wide before EACH sym_define call
        lda #1                          ; repeated setup
        sta sym_wide
        jsr sym_define
        ...
        lda #1                          ; redundant
        sta sym_wide
        jsr sym_define

; after: set once, sym_define preserves sym_wide
        lda #1
        sta sym_wide
        jsr sym_define
        ...
        jsr sym_define                  ; sym_wide still valid
```

Prerequisite: trace the called subroutine to confirm it reads but does
not write the variable.

Used in: `mem.s` — `define_ws_syms` sets `sym_wide` once for two
`sym_define` calls (-4 B).

## 30. Cross-module helper sharing

Export a helper from the module that already computes a value, and
import it in other modules that repeat the same computation.  The
`jsr` (3B) replaces the inline sequence (often 12+ bytes).  No
runtime cost beyond the subroutine call overhead.

```asm
; cse_io.s exports _io_scr_setup (13B body, used internally 4×)
; screen.s imports and calls it for cursor_show (saves 9B inline)
```

Apply when: the helper's contract (inputs, outputs, clobbers) is
simple, and the modules are already coupled via other imports.

Used in: `screen.s` — `cursor_show` uses `_io_scr_setup` from
`cse_io.s` (-9 B).  `_col_clamp` shared between `io_putc` and
`io_puthex2` (-6 B).

## 31. Preserve A in predicate subroutines

When a predicate (returns C=1/C=0) only clobbers A on certain
code paths, add a 1-byte register save/restore (`tax`/`txa`) on
those paths so callers skip the `lda (ptr),y` reload after the
predicate returns C=0.

```asm
; _au_is_end: only clobbers A in the '//' lookahead path
; Add tax before lookahead, txa on fall-through (+2 bytes in helper)
; Removes lda (asm_ptr),y reload at 4 call sites (-8 bytes)
; Net: -6 bytes
```

Used in: `au_mode.s` — `_au_is_end` preserves A when returning C=0,
eliminating 4 reload instructions.

## 32. Chain 16-bit adds to skip intermediate store

When computing `a + b + c` (all 16-bit), chain the low-byte adds
with a single `clc` instead of storing intermediate results and
reloading.  Exploit known-zero bytes (e.g. base address lo = $00)
to skip one add entirely.

```asm
; entry_ptr: idx×6 + sym_table (where sym_table lo = $00)
        clc
        txa                     ; A = lo(×2), X cached it
        adc _st_nptr            ; + lo(×4) → lo(×6)
        sta _st_ptr
        lda _st_ptr+1           ; hi(×2)
        adc _st_nptr+1          ; + hi(×4) + carry
        adc #>sym_table         ; + base hi (lo was $00, skip)
        sta _st_ptr+1
```

Used in: `symtab.s` — `entry_ptr` ×6+base with register caching
and chained add (-13 B).
