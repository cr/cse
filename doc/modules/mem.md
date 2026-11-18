# mem — Memory manager: banking, ZP save/restore, segment queries

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/mem.s`](../../src/mem.s) | implementation |
| [`tests/unit/test_mem.py`](../../tests/unit/test_mem.py) | test contract |

## Interface

### kernal_bank_out
**In:** `kernal_out` (zp.s batch flag)
**Out:** KERNAL ROM hidden ($01 bit 1 cleared) — unless `kernal_out`
is nonzero, then nothing changes.  The I flag is not touched.
**Clobbers:** A

### kernal_bank_in
**In:** `kernal_out`
**Out:** KERNAL ROM visible ($01 bit 1 set) — unless `kernal_out` is
nonzero, then nothing changes.  The I flag is not touched.
**Clobbers:** A

### save_userland_zp / save_kernel_zp
**In:** none
**Out:** `userland_zp_buf` / `kernel_zp_buf` = live $00..$7F, with
`buf[$01]` the fully latched CPU-port byte and `buf[$00]` the DDR as it
was at entry.  Live $00 = $FF afterwards (postcondition the restore
primitives rely on).
**Clobbers:** A, X, Y

### restore_userland_zp / restore_kernel_zp
**In:** live $00 = $FF (the paired save's postcondition)
**Out:** live $00..$7F = `userland_zp_buf` / `kernel_zp_buf`; $01 is
written before $00, so every data bit latches before the DDR is
re-applied.
**Clobbers:** A, X

The four primitives swap live ZP against the two buffers at every
kernel↔userland transition.  Callers (debugger.s, the only ones):

- `save_userland_state` — `save_userland_zp` + `restore_kernel_zp`
  (userland → kernel).
- `_rtu_body` (shared by `return_to_userland` and
  `restore_userland_state`) — `save_kernel_zp` + `restore_userland_zp`
  (kernel → userland).

Each restore is reached only through its paired save, which is what
makes the `$00 = $FF` precondition hold (§ CPU-port aware ZP
save/restore).

### cse_start
**In:** none
**Out:** A/X = `__CODE_RUN__` (runtime start address, lo/hi)
**Clobbers:** A, X

Callers: `main.s` cold init (end of the workspace fill), `repl.s`
(`i` map).

### cse_end
**In:** none
**Out:** A/X = $D000 (HIMEM, first byte past the runtime image)
**Clobbers:** A, X

Caller: `repl.s` (`i` map).

### cse_zp_end
**In:** none
**Out:** A = first free ZP byte — `<__ZP_LAST__`, which ld65 defines as
the first address past the ZEROPAGE segment; X = 0
**Clobbers:** A, X

Caller: `main.s` cold init (fills the free ZP with `$FF` from there to
`$7F`).

**State:**

| Variable | Size | Segment | Purpose |
|----------|------|---------|---------|
| `userland_zp_buf` | `ZP_SAVE_LEN` | BSS | User's `[ZP_SAVE_LO, ZP_SAVE_LO + ZP_SAVE_LEN)` snapshot (captured on userland exit, restored on entry) |
| `kernel_zp_buf` | `ZP_SAVE_LEN` | BSS | Kernel's snapshot over the same range (captured on userland entry, restored on exit) |

The `kernal_out` batch-banking flag is not owned here; it is one of the
cross-module flags in `zp.s` ([zp.md](zp.md)).

**Exported constants** (defined in mem.s):

| Symbol | Value | Purpose |
|--------|-------|---------|
| `ZP_SAVE_LO` | $00 | First ZP address covered by the save buffers |
| `ZP_SAVE_LEN` | 128 | Length of the save range (so `[ZP_SAVE_LO, ZP_SAVE_LO + ZP_SAVE_LEN)` = $00..$7F) |

`userland_zp_buf[i]` mirrors live ZP address `ZP_SAVE_LO + i`.
`repl.s::zp_stage_prep` and `repl.s::zp_poke` (the `m` / `.` user-ZP
view) take their range check and buffer index from these constants.

**Depends on:** zp (`kernal_out`); linker symbols `__ZP_LAST__`,
`__CODE_RUN__`

## Design

### Banking protocol

Both `kernal_bank_out` and `kernal_bank_in` short-circuit when
`kernal_out` is nonzero.  Batch callers (e.g. `asm_assemble`) must
perform the real bank operation BEFORE setting/clearing the flag:

    ; enter batch          ; leave batch
    jsr kernal_bank_out    lda #0
    lda #1                 sta kernal_out
    sta kernal_out         jsr kernal_bank_in

The helpers need no SEI/CLI: an IRQ that fires while the KERNAL is
banked out is routed through `cse_brk_handler_early` and
`bank_out_stub`, which restore the interrupted `$01` exactly
([main.md § IRQ early-entry bank-out](main.md#irq-early-entry-bank-out)).

### CPU-port aware ZP save/restore

The four primitives preserve/restore ZP $00..$7F across
kernel↔userland transitions.  $00 (CPU port DDR) and $01 (data) need
special handling because bits configured as input by $00 read
external state, not the value the CPU wrote.

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
buffers with `$00=$2F` / `$01=$36` so the first transition (before
any userland has populated `userland_zp_buf`) doesn't restore zeros
into the live CPU port.

## Caveats

- Pure writes to $E000–$FFFF always hit RAM, even with the KERNAL
  mapped in.  Only reads require banking.
- `kernal_bank_out` / `kernal_bank_in` do not nest: `kernal_bank_in`
  banks in even when an outer caller banked out, unless that caller
  set `kernal_out`.  A routine that may run inside someone else's
  bank-out window saves and restores `$01` itself (as
  `sym_define` / `sym_lookup` do).
- `kernal_bank_out` / `kernal_bank_in` do not touch the I flag; the
  caller's I state survives a bank-out/bank-in pair.
- `debugger.s::peek_user` (step targets through a ZP vector) reads
  `userland_zp_buf` with the range `$00–$7F` built in, not through
  `ZP_SAVE_LO` / `ZP_SAVE_LEN`; changing the save range means
  changing it too.
- Workspace symbols (`workstart`, `workend`) are not mem.s's: they are
  defined by `gap_buffer.s::define_ws_syms` / `update_workend`
  ([gap_buffer.md](gap_buffer.md)).
