# debugger — Step State Machine + Kernel↔Userland Gates (L4)

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/debugger.s`](../../src/debugger.s) | implementation: `dbg_init`, the gate primitives, `brk_stub`, the step-target computation and its state |
| [`src/dbg_reason.inc`](../../src/dbg_reason.inc) | the `dbg_reason` enum (`DBG_NONE`…`DBG_NMI`), the one definition, included by main.s and repl.s |
| [`tests/integration/test_kernel_transition.py`](../../tests/integration/test_kernel_transition.py) | tier-I tests: kernel↔user transitions, step chains, the command matrix |
| [`tests/integration/test_step_rom.py`](../../tests/integration/test_step_rom.py) | tier-I tests: step-into-ROM fallback |
| [`tests/emulator/test_m65_break.py`](../../tests/emulator/test_m65_break.py) | tier-X tests (xmega65, P1): a user BRK's snapshot equals M65Emu's; a program's bank state survives a break and a resume |
| [`tests/integration/test_m65_debugger.py`](../../tests/integration/test_m65_debugger.py) | tier-I tests on the m65 PRG (P1–P3): `far_user`, the workspace bound, the line parser in bank 3, the user-ZP view, the transitions and the bank state (with the KERNAL's map record, P3) |

The debugger is the kernel's **userland gateway**: the two gate
primitives that move the machine between CSE and user code, the
`brk_stub` a user program's top-level RTS lands on, and the
computation of where a single step must stop.  Neighbouring parts of
the debugger live elsewhere and are documented by their owners:

| Part | Owner |
|---|---|
| Breakpoint table, patch/unpatch, `dbg_bp_*` | [breakpoints.md](breakpoints.md) |
| BRK/NMI/IRQ handlers, step chaining in the handler, warmstarts | [main.md](main.md) |
| User register shadows `reg_a/x/y/p/sp` | [asm_line.md](asm_line.md) |
| The commands' parsing and dispatch (`b c t o j g r`) | [repl.md](repl.md) |
| What user code may rely on (stack, vectors, banking) | [userland_contract.md](../userland_contract.md) |

This document owns the `dbg_reason` enum, the command × session
matrix, and the stepping machinery as a whole.

## Interface

### dbg_init
**In:** none
**Out:** the step-state block (`brk_pc`, `step_state`,
`step_remaining`, `step_next_lo`, `step_next_hi`, `step_save`,
`_rtu_need_sentinel`) zeroed; `reg_a`, `reg_x`, `reg_y`, `reg_p` = 0;
`dbg_reason = DBG_NONE`; `reg_sp = STACK_TOP`; the CPU-port bytes of both ZP
save buffers seeded: `userland_zp_buf` / `kernel_zp_buf` `[$00] = $2F`,
`[$01] = $36`.  The breakpoint table is not touched.
**Clobbers:** A, X

Called by `_main` at cold init and by `hw_reinit_body`
(`cse_recover`).  The breakpoint table is zeroed only at cold init
(`bp_init`), so breakpoints survive `cse_recover`
([memory_design.md § Breakpoint invariant](../memory_design.md#breakpoint-invariant)).
The seed keeps the first restore of a ZP buffer from writing `$00`
into the DDR ([mem.md § CPU-port aware ZP save/restore](mem.md#cpu-port-aware-zp-saverestore)).

**On m65:** `reg_z` and `reg_b` are zeroed with the others; the
saved bank state (`um_map`, the port in `userland_zp_buf`, `um_d030`,
`um_kmap`, `um_sysflags`) is seeded with the run premise's — the user
map, `$FF` / `$85`, `$64`, `um_kmap` the user map, `SYSFLAGS` 0 —
after `kmap_swap` has written the CSE map into the KERNAL's map
record, which the cold start thus leaves CSE's
([platform_layer.md § User transitions](../platform_layer.md#user-transitions));
there is no `kernel_zp_buf`.  The registers a fresh start installs
are the run premise's: `A X Y Z B` = 0, and P as the CPU keeps it —
`E` = 1, which `RTI` does not load
([userland_contract.md § 3](../userland_contract.md#on-m65)).

### save_userland_state
**In:** called (`jsr`) by `cse_brk_handler` / `cse_nmi_handler` with
the $FF48-shape frame above the return address: SP+3..SP+8 = Y, X,
A, P, PCL, PCH; live ZP is the user's.
**Out:** `reg_y`, `reg_x`, `reg_a`, `reg_p` (raw stacked P) and
`brk_pc` (raw stacked PC) captured; `reg_sp` = SP + 8 = the user's SP
before the interrupt; `userland_zp_buf` = the user's ZP; live ZP =
`kernel_zp_buf` (`$00 = $2F`, `$01 = $36`).  The stack is only read.
**Clobbers:** A, X, Y

Masking P and the BRK `brk_pc − 2` are the calling handler's job,
because they differ by source ([main.md § BRK dispatch](main.md#brk-dispatch)).

**On m65:** the frame is the KERNAL's, SP+3..SP+10 = B, Z, Y, X, A,
P, PCL, PCH; `reg_z` and `reg_b` are captured as well (P − 4, P − 5),
`reg_sp` = SP + 10, and nothing is swapped: base page 0 is the
user's throughout ([platform_layer.md § Base page](../platform_layer.md#base-page));
the bank state was captured before it ran (the stub, the handler);
its m65 tail captures `$D030`, the program's `SYSFLAGS`
(`um_sysflags`) and the KERNAL's map record `0.011C–011F`
(`um_kmap`), and writes the CSE map into the record (`kmap_swap`)
([platform_layer.md § User transitions](../platform_layer.md#user-transitions)).
Every offset derives from `FRAME_DEPTH`.

### return_to_userland
**In:** `brk_pc`, `reg_a/x/y/p`, `reg_sp` = the state to install;
live ZP is the kernel's.
**Out:** does not return — as `restore_userland_state`, but first
pushes the `brk_stub − 1` sentinel (hi, lo) at `reg_sp`, so the user
program's top-level RTS lands on `brk_stub`.
**Clobbers:** everything (control passes to user code).

The fresh-start door: `main_loop` / `main_loop_top` jump here when a
command set `run_user_pending = MODE_JUMP` (`j`, `g`, and the first
`t`/`o`/`c` after a cold preview).

### restore_userland_state
**In:** as `return_to_userland`.
**Out:** does not return.  In order (`_rtu_body`, shared with
`return_to_userland`):
1. `patch_all` — `$00` into every enabled breakpoint and step slot.
2. `save_kernel_zp`, `restore_userland_zp` — live ZP becomes the
   user's.
3. SP := `reg_sp`.
4. (`return_to_userland` only) push the sentinel.
5. Push PCH, PCL (from `brk_pc`), P (`reg_p`).
6. `in_userland := $80` (bit 7, for `cse_nmi_handler`'s `bit`/`bmi`);
   on m65 inside step 7, once its `MAP` holds the NMI off.
7. `PLAT_TO_USER`: on c64 X, Y, A from `reg_*` and `rti`; on m65
   `reg_a`, `reg_x`, `reg_y`, `reg_z`, `reg_b` pushed and `jmp
   stub_user`, which installs the user's map and restores them;
   before it, with interrupts off, `$D030` and the CPU port are the
   user's again ([platform_layer.md § User transitions](../platform_layer.md#user-transitions)).
   Step 2 is c64 only.  `return_to_userland` also seeds the bank
   state with the run premise's, so every fresh start begins as a
   `RUN` does.  On m65, after step 1, the program's `SYSFLAGS` and
   KERNAL map record go back (`um_sysflags`, `um_kmap`): KERNAL state,
   written before `PLAT_TO_USER`'s `MAP` hold.

**Clobbers:** everything.

The resume door: `MODE_RESUME` (`c`, `t`, `o` in a session whose
sentinel is already on the user stack) and the handler's step chain.
A resume pushes no sentinel — the one from the session's fresh start
is still in place; pushing another would creep the stack by 2 bytes
per resume.  SP := `reg_sp` is a no-op on the `main_loop` path (the
handler left SP there) and a correction on the chain path (SP was
BRK-frame deep) or after `r s:XX`.

Both doors put the ZP swap and `patch_all` inside the primitive, so
every kernel → userland transition is the mirror image of the
handlers' `save_userland_state` + `unpatch_all`.

### brk_stub
**Address:** CODE label, exported (imported by main.s and repl.s).

`BRK` followed by the signature byte `$42`.  On m65 it is part of
the resident stub at `0.1FB0–0.1FFF`, which the user map shows
([mem.md § brk_stub](mem.md#brk_stub)); `bp_range_check_step`
accepts it as on c64.  The user program's
top-level RTS pops the `brk_stub − 1` sentinel, lands here, and the
BRK fires; `cse_brk_handler` recognises `brk_pc = brk_stub`, sets
`dbg_reason = DBG_RTS` and `brk_pc := cur_addr` (the address the REPL
was at — the `j` target, or the last break's address).

### step_next_pc
**In:** `brk_pc` (the instruction about to run), `step_state`
(STEP_INTO / STEP_OVER); `reg_sp` (RTS/RTI), `reg_x` (JMP (abs,X)),
`asm_cpu` (65C02 rules, CMOS builds only), `userland_zp_buf` (vectors
in $00–$7F).
**Out:** `step_next_lo` = where the step stops, `step_next_hi` = a
second stop for a branch under STEP_INTO; 0 = none (both 0 for BRK).
**Clobbers:** A, X, Y, `rp_ptr`, `rp_ptr2`, `step_save`

The table is § Next-PC.  It reads the instruction and its vectors
at user addresses: `rp_ptr` and `rp_ptr2` are set with `FAR_USER`
([platform_layer.md § Far memory](../platform_layer.md#far-memory)),
a vector in base page 0 through `peek_user` (the image on c64, base
page 0 itself on m65).  Callers: `repl.s::cmd_step` (first step)
and `cse_brk_handler` (each chained step).

### arm_step_bp
**In:** `step_next_lo`, `step_next_hi`
**Out:** `dbg_step_clear`, then step slot 8 = (`step_next_lo`,
saved 0, flags 1) if nonzero and slot 9 = (`step_next_hi`, saved 0,
flags 1) if nonzero.  Nothing is patched yet (`patch_all` does that
on the way out).
**Clobbers:** A, X

Callers: as `step_next_pc`.

**State** — **BSS (11 bytes):** (16 on m65, with `um_kmap` and `um_sysflags`)

| Variable | Size | Exported | Purpose |
|---|---|---|---|
| `brk_pc` | 2 | yes (main.s, repl.s) | PC of the last break = resume address (`r pc:`) |
| `step_state` | 1 | yes (main.s, repl.s) | `STEP_NONE` (0) / `STEP_INTO` (1, `t`) / `STEP_OVER` (2, `o`) |
| `step_remaining` | 2 | yes (main.s, repl.s) | steps left after the current one (16-bit) |
| `step_next_lo` | 2 | yes (repl.s) | `step_next_pc` result, first stop |
| `step_next_hi` | 2 | yes (repl.s) | `step_next_pc` result, second stop |
| `step_save` | 1 | no | opcode scratch of `step_next_pc` |
| `_rtu_need_sentinel` | 1 | no | per call: 1 from `return_to_userland`, 0 from `restore_userland_state`; read by `_rtu_body` |
| `um_kmap` | 4 (m65 only) | no (debug labels: tests) | the program's KERNAL map record `0.011C–011F` (its bank state; P3) |
| `um_sysflags` | 1 (m65 only) | no (debug labels: tests) | the program's `SYSFLAGS` (its bank state; P2) |

`dbg_reason` and `in_userland` are cross-module flags in `zp.s`
([zp.md § Cross-module flags](zp.md#cross-module-flags));
`dbg_reason`'s values are § `dbg_reason` enum.  `step_bp` (slots 8–9)
is breakpoints.s's; `reg_*` are asm_line.s's; `kernel_zp_buf` /
`userland_zp_buf` are mem.s's.

**Depends on:** asm_line (`reg_a`, `reg_x`, `reg_y`, `reg_sp`,
`reg_p`), mem (`save_userland_zp`, `restore_userland_zp`,
`save_kernel_zp`, `restore_kernel_zp`, `kernel_zp_buf`,
`userland_zp_buf`), breakpoints (`patch_all`, `step_bp`,
`dbg_step_clear`), oplen_tbl, zp (`rp_ptr`, `rp_ptr2`, `in_userland`,
`dbg_reason`, `asm_cpu`)

## Debug session

### `dbg_reason` enum

Defined once, in `src/dbg_reason.inc`, which main.s and repl.s
include (a test pins that no source defines the values itself).
Ordered by liveness:

```
DBG_NONE = 0    ; no session (never started, or ended)
DBG_RTS  = 1    ; session over but inspectable: the program's
                ;   top-level RTS reached brk_stub (clean exit)
DBG_BRK  = 2    ; resumable: breakpoint, step, cold preview, or a
                ;   BRK in user code
DBG_NMI  = 3    ; resumable: RUN/STOP+RESTORE while user code ran
```

**Ordering invariant:** `dbg_reason >= DBG_BRK` iff the session can
proceed via `c` or `t`/`o` — one compare:

```asm
lda dbg_reason
cmp #DBG_BRK
bcs @resumable       ; DBG_BRK or DBG_NMI
```

| Writer | Value |
|---|---|
| `dbg_init` (cold init, `cse_recover`) | `DBG_NONE` |
| `cse_brk_handler` | `DBG_BRK`; `DBG_RTS` at `brk_stub` (the only site) |
| `cse_nmi_handler` (userland) | `DBG_NMI` |
| `end_debug_body` | `DBG_NONE` |
| `t`/`o` cold preview | `DBG_BRK` |
| `a`, after an error-free assembly | `DBG_NONE` |

Every consumer — the break panel, the command gates,
`hygiene_after_userland`, `main_loop_top` — reads `dbg_reason` alone;
no consumer re-classifies a break from `brk_pc` or from opcodes
(`brk_skip_user`'s opcode peek only decides whether to skip a user
BRK).

### `dbg_reason` × command matrix

| Command | `DBG_NONE` | `DBG_RTS` | `DBG_BRK` / `DBG_NMI` |
|---|---|---|---|
| `c` | `;?no ctx` | `;?no ctx` | resume |
| `t` / `o` | cold preview | `;?no ctx` | step |
| `j` / `g` | run | run | `;!debug`, `;!go? y/n` |
| `a` | assemble | assemble | `;!debug`, `;!asm? y/n` |
| `R` | `;!init? y/n` | `;!init? y/n` | `;!init? y/n` |
| `r`, `b`, `l`, `s`, all others | no debug gate | no debug gate | no debug gate |

- **Ask** (`j`/`g`, `a`): "y" sets `warm_cont = 1` and jumps to
  `cse_end_debug`, which ends the session and replays the typed line
  ([main.md § Layer 4](main.md#layer-4-main_loop-event-loop)); any
  other key cancels and nothing changes.
- **`R`**: on "y", `end_debug_body` (idempotent) then `cse_refresh`,
  whatever the session state.
- **`c`** after a cold preview is a fresh start (§ Cold preview).
- Commands without a debug gate may still have their own (`;!unsaved`
  for `k`, `Q` and a source `l`):
  [repl.md § Gating pattern](repl.md#gating-pattern).

### Break panel

Every return from user code ends in `post_run_cleanup` (repl.s),
which first warns `;!stk N` when `reg_sp` is below 64 (N = `reg_sp`,
decimal), ends a step (`step_cleanup`), and prints the panel:

```
; brk 1 at $1010
r pc:1010 a:00 x:05 y:00 s:fb nv-Bdizc
1010:.  ee 20 d0  inc $d020
```

- **Tag row** — `; brk at $PC` (`DBG_BRK`), `; brk N at $PC` when a
  user breakpoint (slot N, 1-based) hit, `; nmi at $PC` (`DBG_NMI`),
  `; rts` (`DBG_RTS`, no address: `brk_pc` was replaced by
  `cur_addr`).
- **Register row** — `emit_reg`'s `r` line: `brk_pc`, `reg_a/x/y`,
  `reg_sp` as `s:`, `reg_p` as `nv-bdizc` with set flags in
  uppercase.  It re-executes as an `r` command (§ `r`).
- **Lookahead row** — the instruction at `brk_pc` (`emit_dot`),
  omitted for `DBG_RTS`.
- `cur_addr := brk_pc`, so the prompt shows the break address.

A cold preview prints the same rows under `; dbg at $PC`.  After a
step, the row above the panel keeps the instruction that just ran
(single steps only), so repeated RETURN leaves an audit trail:

```
1000:t
1000:.  a2 05     ldx #$05
; brk at $1002
r pc:1002 a:00 x:05 y:00 s:fd nv-Bdizc
1002:.  20 10 10  jsr $1010
```

`j`/`g`/`t`/`o` move to a fresh row (and drain the keyboard buffer)
before user code runs, so user output starts below the command
([userland_contract.md § 6](../userland_contract.md#6-kernal-as-terminal-affordance)).

## Single-step

`t` (into) and `o` (over) step one instruction, or N with `t N` /
`o N` (an expression; 16-bit; 0 or none means 1).  Iteration runs
**inside the BRK handler**: `main_loop` never loops over steps,
because every break longjmps back to `main_loop_top` and discards the
REPL's call chain.

**Seed (`repl.s::cmd_step`)**, in a resumable session:

1. `step_state := STEP_INTO / STEP_OVER`.
2. `o` only: skip a user BRK at `brk_pc` (`brk_skip_user`, § User BRK
   workflow).
3. Disable the breakpoint the session stopped at (`dbg_bp_hit`), so
   the step does not re-break on it at once.
4. `step_next_pc`.  Both results 0 (a BRK at `brk_pc` under `t`) →
   `post_run_cleanup` (panel again, no user code runs).
5. **Workspace gate:** every nonzero target must satisfy
   `$0800 ≤ addr < buf_base` (or be `brk_stub`); else the step is
   undone (`step_cleanup`: `step_state`, step slots, the disabled
   breakpoint enabled again) and `;!range` is printed — the session
   is exactly as before.  The same gate (`step_targets_check`, shared
   with the handler's chain) runs before every chained step of
   `t N` / `o N`: a chained step that would leave the workspace ends
   the chain at the instruction it would have run (bit 7 of
   `step_state`), and `post_run_cleanup` prints the panel and
   `;!range`; the session is kept.
6. `arm_step_bp`; `step_remaining := N − 1`.
7. `run_user_pending := MODE_RESUME`, or `MODE_JUMP` right after a
   cold preview.

**Chain (`cse_brk_handler`, main.s):** a BRK at step slot 8 or 9
while `step_state ≠ 0` and `step_remaining ≠ 0` → `unpatch_all`,
`step_next_pc`, `arm_step_bp`, `step_remaining −= 1`,
`jmp restore_userland_state`.  A user breakpoint, an NMI, `brk_stub`
or an unplanned BRK ends the chain like any break; so does the step
BRK with `step_remaining = 0`.  The chain re-enters userland from the
handler with SP back at `reg_sp`, so `t 1000` uses no more stack than
`t 1`.

**End:** `post_run_cleanup` → `step_cleanup` (step state and slots
cleared, the disabled breakpoint enabled again) and the panel.
`end_debug_body` runs `step_cleanup` too, so ending a session never
leaves a disabled slot behind.

### Next-PC

| Instruction at `brk_pc` | `step_next_lo` | `step_next_hi` |
|---|---|---|
| linear | `PC + length` (`oplen_tbl`) | — |
| conditional branch, `t` | taken target | `PC + 2` |
| conditional branch, `o` | `PC + 2` | — |
| `BRA` (65C02, `asm_cpu` = 65C02) | target | — |
| `JMP abs` | operand | — |
| `JMP (ind)` | the vector at the operand; `JMP ($xxFF)` takes its high byte from `$xx00` (NMOS) unless `asm_cpu` = 65C02 | — |
| `JMP (abs,X)` (65C02) | the vector at operand + `reg_x`, no page wrap | — |
| `JSR`, `t`, target < `$E000` | target (into the subroutine) | — |
| `JSR`, `o`, or target ≥ `$E000` | `PC + 3` (over) | — |
| `RTS` | user stack `($0100 + reg_sp + 1)` + 1 | — |
| `RTI` | user stack PCL/PCH at `reg_sp + 2` / `+ 3` | — |
| `BRK` | — | — |

Vectors are read as the CPU will read them: `$00–$7F` from
`userland_zp_buf` (the live ZP is the kernel's while CSE runs),
everything else live (`peek_user`).  The 65C02 rows apply only to
CMOS builds with `asm_cpu` = 65C02; elsewhere those opcodes are
linear.

`RTS` and `RTI` are followed through the user's stack, so stepping
continues past a return.  Stepping over the program's top-level RTS
reaches `brk_stub` (exempt from the gate) and ends the session as a
clean exit (`; rts`).

`JSR` into `$E000+` is stepped over even under `t`: a BRK written
there lands in the RAM under the KERNAL ROM and is never fetched
while the KERNAL is mapped.

Under `o` a conditional branch arms only the fall-through: a taken
backward branch runs the loop at full speed until it falls through.

### Cold preview

`t`/`o` with no session (`DBG_NONE`) runs nothing: `brk_pc :=
cur_addr`, the panel is printed under `; dbg at $PC`, `dbg_reason :=
DBG_BRK` and `cold_preview_done := 1` (repl.s).  A count is ignored.

```
1000:t
; dbg at $1000
r pc:1000 a:00 x:00 y:00 s:ff nv-bdizc
1000:.  a2 05     ldx #$05
```

No sentinel is on the user stack yet, so the first transition after
the preview — `t`, `o` or `c` — is a fresh start: `set_run_mode`
picks `MODE_JUMP` (sentinel pushed) and clears `cold_preview_done`;
later ones are `MODE_RESUME`.  `end_debug_body` clears the flag with
the rest of the session.

### User BRK workflow

A `brk` the user placed in the program (with a signature byte,
`brk` / `.db $XX`) stops as `DBG_BRK` with `brk_pc` at the `$00`:

- **`o` and `c` skip it.**  `brk_skip_user` (repl.s) advances
  `brk_pc` by 2 when the byte at `brk_pc` is `$00` — BRK plus its
  signature byte, as the CPU's own RTI from BRK would.  The BRK is
  never executed.
- **`t` stays on it.**  `step_next_pc` yields no target for BRK, so
  `t` redisplays the panel without progress; use `o` to go on.
- A `brk` without a signature byte loses the following byte to the
  2-byte skip.
- `d` disassembles BRK as one byte, like other 6502 monitors.

## Commands

The debugger-facing semantics of the REPL commands; their parsing,
dispatch and error conventions are [repl.md](repl.md)'s.

### `b`

```
b               list slots 1-8
b ADDR          set a breakpoint (expression)
b -N            delete slot N (1-8)
b *             delete all
```

`b ADDR` requires `$0800 ≤ addr < buf_base` (else `;?range`) and
reuses the slot that already holds the address; a full table is
`;?full`.  Output: `; bp 1: $1010` (set, list), `; bp 3: $----`
(empty slot), `; bp 1 del`, `; bp clr`.  Breakpoints persist across
sessions and warmstarts ([breakpoints.md](breakpoints.md)).

### `c`

Resumes a `DBG_BRK` / `DBG_NMI` session (else `;?no ctx`).  If the
break was a user breakpoint, that breakpoint is **deleted** first
(`dbg_bp_del` of `dbg_bp_hit`), so `c` never re-breaks on the spot it
leaves; re-set it with `b` to break there again.  A user BRK at
`brk_pc` is skipped (§ User BRK workflow).

### `t` / `o`

§ Single-step.  `t` steps into subroutines, `o` over them.

### `j` / `g`

`j [ADDR]` sets `cur_addr` (when given) and starts the program there
(a bad expression runs nothing); `g` starts at the symbol `main`, or
at `cur_addr` when `main` is undefined.  `brk_pc := cur_addr`,
`MODE_JUMP`: `return_to_userland` pushes the sentinel, so the
program's top-level RTS is a clean exit:

```
0800:j $1010
; rts
r pc:1010 a:00 x:00 y:00 s:ff nv-Bdizc
```

In a resumable session `j`/`g` ask first (§ matrix).

### `r`

```
r                                   show the registers
r pc:XXXX a:XX x:XX y:XX s:XX nv-bdizc
```

Fields are matched by their label, in any order, and any subset may
be given (`r x:05` sets X only).  A register field is `a:`, `x:`,
`y:` or `s:` plus exactly two hex digits; `pc:` takes four.  The
flags field is exactly 8 characters in `nv-bdizc` order: the
uppercase letter sets the flag, the lowercase letter, `-` or `.`
clears it (bit 5 stays 0).  Each field ends at a space, `;` or the
line end.  Anything else — an unknown label, a missing or non-hex
digit, a flags field of the wrong length or with a foreign
character — is `;?syntax` and changes no register: the line is
checked in full before any field is applied.  The echoed line
(`emit_reg`'s format) re-executes unchanged, so cursor-up + edit +
RETURN edits registers in place.

Changed registers are installed by the next transfer to user code
(`c`, `t`, `o`, `j`, `g`); `j`/`g` replace `pc:` with their start
address.  `s:` moves the user's SP.

**On m65** the line has two more fields, `z:` and `b:` (two hex
digits each), after `y:`, and its layout depends on the screen
width.  In 80 columns (80 × 25, 80 × 50) it is one line of 48
characters:

```
r pc:XXXX a:XX x:XX y:XX z:XX b:XX s:XX nv-bdizc
```

In 40 columns (ESC 4) that line does not fit; `r` then prints two
rows — the c64 line, and `r z:XX b:XX` below it:

```
r pc:XXXX a:XX x:XX y:XX s:XX nv-bdizc
r z:XX b:XX
```

Each row re-executes unchanged on its own, because `r` sets the fields
it is given and leaves the rest (§ `r`).  `emit_reg` chooses by the
current width at each call.

Bit 5 of the flags field is `E` on the 45GS02; it stays `-` and
cannot be set, because `RTI` does not load it — user code runs with
the CPU's `E` = 1.  The fields are assembled under `.ifdef
PLATFORM_M65` (the KERNAL's frame carries Z and B on the platform,
whatever the build's CPU set).

## Workflow example

The program: `1000 ldx #$05 / jsr $1010 / dex / bne $1002 / rts`,
`1010 inc $d020 / rts`.

```
1000:b $1010
; bp 1: $1010
1000:j
; brk 1 at $1010
r pc:1010 a:00 x:05 y:00 s:fb nv-Bdizc
1010:.  ee 20 d0  inc $d020
1010:c
; rts
r pc:1010 a:00 x:00 y:00 s:ff nv-Bdizc
1010:c
;?no ctx
```

`c` deleted breakpoint 1, so the loop ran to the program's RTS — a
clean exit; `pc:` shows `cur_addr` (here the last break), and the
session can no longer be resumed.

## Caveats

- **Shared stack:** user code shares the CSE stack page and must
  leave 64 bytes of headroom below its SP for the kernel's re-entry;
  a break with `reg_sp` below 64 warns `;!stk N`.  See
  [userland_contract.md § 4](../userland_contract.md#4-stack-contract).
- **`return_to_userland` / `restore_userland_state` do not return.**
  The kernel runs again only through `cse_brk_handler` /
  `cse_nmi_handler` and their jump to `main_loop_top`.
- Breakpoints and step BRKs work only in workspace RAM: `b` refuses
  addresses outside `WORKSTART ≤ addr <` the workspace's upper bound
  (`;?range`) — `$0800 ≤ addr < buf_base` on c64, `$2000 ≤ addr <
  $C000` on m65 ([platform_layer.md § Constants](../platform_layer.md#constants)) —
  and every step — chained ones included — refuses targets outside it
  (`;!range`).
- `o` over a `JSR` or a branch whose fall-through is never reached
  (a routine that does not return, a loop that exits sideways) runs
  free; RUN/STOP+RESTORE breaks in.
- Self-modifying code may overwrite a patched BRK byte between the
  patch and the hit, losing the breakpoint, and `unpatch_all` then
  writes the saved byte over the program's own change.
- On m65 a break captures the program's bank state (`MAP`, the CPU
  port, `$D030`) through `hyppo_get_mapping` and the registers
  themselves, and the resume installs it again; `m d030` shows the
  kernel's `$D030` while CSE runs (the user's is in `um_d030`), as
  the c64 shows the VIC registers CSE set
  ([userland_contract.md § 5.5](../userland_contract.md#55-on-m65)).
- $0316/$0318 (BRK/NMI vectors) and $FFFE/$FFFA (RAM shadows) belong
  to CSE.  User code that overwrites them bypasses the corresponding
  path ([userland_contract.md § 5](../userland_contract.md#5-interrupt-vector-and-banking-hazards)).
