# mem — Memory manager: banking, ZP save/restore, segment queries, the m65 resident stub

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/mem.s`](../../src/mem.s) | implementation |
| [`tests/unit/test_mem.py`](../../tests/unit/test_mem.py) | test contract |

## Interface

mem.s hosts the banking seam, the user-ZP swap of the base-page seam
and, on m65, the resident stub ([platform_layer.md](../platform_layer.md)).  The entries below
state the c64 body; each **On m65** paragraph states the m65 body of
the same entry.

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

**On m65:** both are `rts` and clobber nothing.  Nothing of CSE's is
under the KERNAL: the data window is mapped in the CSE map at all
times ([platform_layer.md § Banking](../platform_layer.md#banking)).
Their callers are platform-neutral and stay as they are.

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

**On m65:** the four primitives are not assembled — there is no ZP
swap (§ Design, *ZP swap on m65*).

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

**On m65:** A/X = `PROG_HI + 1`: CSE does not run in bank 0, and the
program region ends below the interface ROM
([memory_design.md § Memory Map — m65](../memory_design.md#memory-map--m65-mega65-mode)).

Callers: `main.s` cold init (end of the workspace fill), `repl.s`
(`i` map).

### cse_end
**In:** none
**Out:** A/X = $D000 (HIMEM, first byte past the runtime image)
**Clobbers:** A, X

Caller: `repl.s` (`i` map).

**On m65:** A/X = `PROG_HI + 1`, as `cse_start`.

### cse_zp_end
**In:** none
**Out:** A = first free ZP byte — `<__ZP_LAST__`, which ld65 defines as
the first address past the ZEROPAGE segment; X = 0
**Clobbers:** A, X

Caller: `main.s` cold init (fills the free ZP with `$FF` from there to
`$7F`).

### far_user (m65 only)
**In:** X = a far pointer's base-page offset; the pointer's offset
(bytes 0–1) holds a user address.
**Out:** bytes 2–3 (bank, megabyte) set by the user map's row for
that address; for `$D000–$DFFF` byte 1 rewritten to the I/O row's
offset (`$3x`) — [platform_layer.md § Far memory](../platform_layer.md#far-memory).
**Clobbers:** nothing — A, X, Y and P preserved.

The body of `FAR_USER` on m65 (the macro loads X, so the macro
clobbers X and N/Z); on c64 there is no routine and `FAR_USER` is
empty.  It lives here because mem.s is the memory driver; the four
rows are one compare chain on the high byte.  It is not idempotent:
the I/O row rewrites the offset's high byte, so a pointer is
translated once per set (`zp_poke`, called per byte, leaves it to
its callers).

### The resident stub (m65 only)

The entries of the `STUB` segment, assembled only under `.ifdef
PLATFORM_M65`; the loader copies it to `STUB_BASE`, where it runs in
both maps (§ Design, *The resident stub*).

#### stub_brk / stub_nmi
**In:** reached through the `IBRK` / `INMI` vector, in either map,
with the KERNAL's frame on the stack and `B = 0` (the KERNAL's entry
set it).
**Out:** in `cse_brk_handler` / `cse_nmi_handler` under the CSE map
with `B = CSE_BP`; the frame as the KERNAL left it; the I flag
unchanged.  With `in_userland` set, the user's bank state captured
first ([platform_layer.md § User transitions](../platform_layer.md#user-transitions)):
the CPU port into `userland_zp_buf` and set to the run premise's,
then `hyppo_get_mapping` into `um_map`; with it clear (a kernel fault,
RUN/STOP+RESTORE at the prompt) nothing is captured.
**Clobbers:** A, X, Y, Z (their user values are in the frame); B;
with `in_userland` set, the CPU port.

#### stub_cold
**In:** reached from the loader by `jmp` with X = 4 (the cold
target's index), interrupts off; no frame.
**Out:** in `_main` under the CSE map with `B = CSE_BP`.
**Clobbers:** A, X, Y, Z, B.

#### stub_user
**In:** reached from `PLAT_TO_USER` (`_rtu_body`, debugger.s) by
`jmp`, interrupts off, the CPU port and `$D030` already the user's;
on the stack above the RTI frame the user's A, X, Y, Z, B and above
them the `MAP` operands of the user's offsets and masks; in A, X, Y,
Z the `MAP` operands of the user's megabytes.
**Out:** in user code under the user's map (megabytes, then offsets
and masks, one `EOM`), every register, P and SP the user's.
**Clobbers:** nothing of the user's.

#### brk_stub
**In:** reached when a program's final `RTS` pops the sentinel
`return_to_userland` pushed.
**Out:** a BRK, which the debugger classifies as the program's clean
exit ([debugger.md](debugger.md)).
**Clobbers:** — (the BRK's own frame).

**State:**

| Variable | Size | Segment | Purpose |
|----------|------|---------|---------|
| `userland_zp_buf` | `ZP_SAVE_LEN` | BSS | User's `[ZP_SAVE_LO, ZP_SAVE_LO + ZP_SAVE_LEN)` snapshot (captured on userland exit, restored on entry) |
| `kernel_zp_buf` | `ZP_SAVE_LEN` | BSS | Kernel's snapshot over the same range (captured on userland entry, restored on exit) |
| `stub_brk_target`, `stub_nmi_target`, `stub_cold_target` | 2 each | CSE's base page (m65; zp.s) | where the stub's CSE entries jump, indexed by X = 0, 2, 4 once the CSE map is back; written by `setup_interrupts` (main.s) and the loader.  Not in the stub: the dispatch runs under the CSE map, and the stub's 80 bytes are full |
| `um_map` | 6 | CSE's base page, `$00–$05` (m65) | the user's `MAP` setting as `hyppo_get_mapping` writes it — the trap writes at a page start, so these are the page's first six bytes |
| `userland_zp_buf` (m65) | 2 | CSE's base page (m65) | the user's CPU port, `$00` and `$01`: the stub writes it under the user map, where only bank 0 is visible |
| `um_d030` | 1 | CSE's base page (m65) | the user's `$D030` |

On m65 `kernel_zp_buf` is not assembled, and `userland_zp_buf` is the
captured CPU port (§ Design, *ZP swap on m65*).

The `kernal_out` batch-banking flag is not owned here; it is one of the
cross-module flags in `zp.s` ([zp.md](zp.md)).

**Exported constants** (defined in mem.s):

| Symbol | Value | Purpose |
|--------|-------|---------|
| `ZP_SAVE_LO` | $00 | First ZP address covered by the save buffers |
| `ZP_SAVE_LEN` | 128; 2 on m65 | Length of the save range (so `[ZP_SAVE_LO, ZP_SAVE_LO + ZP_SAVE_LEN)` = $00..$7F; on m65 the CPU port, $00..$01) |

`userland_zp_buf[i]` mirrors live ZP address `ZP_SAVE_LO + i`.
`repl.s::zp_stage_prep` and `repl.s::zp_poke` (the `m` / `.` user-ZP
view) take their range check and buffer index from these constants.

**Depends on:** zp (`kernal_out`); linker symbols `__ZP_LAST__`,
`__CODE_RUN__`; on m65 `src/m45_ops.inc` (`MAP`, `EOM`, `LDZ`,
`TAB`, `PLZ`, `PLY`, `PLX`) and `platform.inc` (`CSE_BP`, the two
maps' operands).

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
buffers with the platform's CPU-port seeds — `$00=$2F` / `$01=$36` on
c64 ([platform_layer.md § Constants](../platform_layer.md#constants))
— so the first transition (before any userland has populated
`userland_zp_buf`) doesn't restore zeros into the live CPU port.

### ZP swap on m65

The four primitives, their buffers and the seeds are not assembled on
m65: CSE's zero page is its own base page, so the user's base page 0
is never touched and there is nothing to swap — the transitions
switch `B`, and the user's `B` travels in the interrupt frame
([platform_layer.md § Base page](../platform_layer.md#base-page)).
The CPU port is the one exception: the transitions swap it, through
absolute addressing — the stub saves the user's into `userland_zp_buf`
and sets the premise's, `PLAT_TO_USER` writes the user's back — so
the c64's user-ZP view, with a two-byte save range, shows and edits
the user's port; the rest of base page 0 is read live
([platform_layer.md § Base page](../platform_layer.md#base-page)).

### The resident stub

CSE's only code in bank 0, at the top of CSE's base page; it is
visible in both maps because `$0000–$1FFF` is unmapped in both
([memory_design.md § Memory Map — m65](../memory_design.md#memory-map--m65-mega65-mode)).

    stub_brk    X ← 0 ┐
    stub_nmi    X ← 2 ┘ in_userland? port saved, premise port, hyppo_get_mapping
    stub_cold   (X = 4 from the loader) PHA X · MAP megabytes 0 · MAP CSE · EOM
                · B ← CSE_BP · PLA X · JMP (targets,X)
    stub_user   MAP megabytes · PLZ PLY PLX PLA · MAP · EOM
                · PLA TAB · PLZ · PLY · PLX · PLA · RTI
    brk_stub    BRK + signature

The targets are in CSE's base page; the dispatch is `JMP (abs,X)`
(`M45_JMP_IND_X`).

The three CSE entries share one body, the entry's index kept on the
stack across `MAP` (which takes every register).  The capture runs
under the program's map with `B = 0`, so its stores into CSE's page
are absolute (`0.1Fxx`).  It must fit the stub's area,
`0.1FB0–0.1FFF` (the segment's assert); if the implementation cannot
make it fit, `STUB_BASE` moves down within the page and the base
page's bound with it — a delta to memory_design.md and zp.md, not a
second page.

`MAP` takes its operands in A, X, Y and Z, and the register snapshot
is in the data window, which the user map does not show — so
`PLAT_TO_USER` pushes the user's registers and the second `MAP`'s
operands, and `stub_user` pulls them after the switch.  `brk_stub` is here, not in debugger.s as on c64,
because a program's final `RTS` runs in the user map, which shows
bank 0 but not CSE's code — as the KERNAL keeps its own `SYS` return
path in page 3.  The targets are data written from above (main.s, the
loader), so the stub holds no address of CSE's code and imports
nothing from a higher layer.  It replaces the C64's
`cse_brk_handler_early`, `bank_out_stub` and RAM shadows: on m65 the
KERNAL is mapped in every map.

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
