# CSE — TODO

## Corpus status snapshot — 2026-04-20 handover

> *Historical reference point captured at the end of the L0–L5 TDD-
> compliance milestone.  Not refreshed; later phases (21 BSS migration,
> 22 debugger workflow, 23 DDD Streamlining) have moved the corpus on.
> Newer phase summaries live in the auto-memory under
> `project_phase*_complete.md`.*


**Full TDD compliance across L0–L5.**  3042 tests passing, 18 vocal
skips, 0 failures.  Every behavioural module's documented contract
is exercised at its prescribed tier:

- **L0** (zp, strings, *_tables, mn_config, oplen_tbl, mn_vars):
  axiomatic per testing.md § Principle 12 — no unit tests, covered
  transitively by every bundled test that links them.
- **L1–L3** (15 modules): every export covered at Tier U.  Includes
  the two new L3 extractions from this session: `breakpoints.s`
  (bundle-tested at L3, was formerly debugger-internal) and
  `gap_buffer.s` (bundle-tested at L3, was formerly editor-internal).
- **L4** (asm_src, editor, disk, debugger): every export covered at
  its correct tier — `asm_src` at U via the asm_core bundle, the
  other three at I via C64Emu.
- **L5** (main, repl): comprehensive C64Emu command-loop coverage at I.
- **L6** (loader): implicit via every integration test's load path,
  acceptable per testing.md's Tier I definition.

**Process ratchets added this session** (DDD System amendments):

- testing.md Principle 10: test bundles mirror production build configs.
- testing.md Principle 11: contract matrices drive test matrices.
- testing.md Principle 12: axiomatic modules need no unit tests.
- testing.md Principle 13: partial-result contracts need position-
  pinning tests (direct or transitive via hot-loop composition).
- README.md § Escape Analysis step 5: two-axis sweep — class-wide
  AND cross-module handoff — on every escape.
- README.md § TDD Maintenance item 11: periodic audit of Principle 13
  compliance + dead-code-sweep gotcha (grep direct calls + `.import`
  references + test-harness lookups before retiring).
- Glossary: solitary / sociable / bundled unit testing, axiomatic
  module / behavioural module, partial-mode function.

**Escape Analyses resolved this session** (5 total): asm_cpu gate on
6510 build, `? 1x` trailing garbage, `. .` silent BRK, log enter-
anywhere under-testing, prompt-row overwrite from the log contract's
cross-module handoff regression.  Class closure applied for the `?`
garbage-trailing pattern across `@` / `B` / `C` / `j` via the shared
`_require_eoi_or_err` helper.  Plus a latent `ed_insert_string`
save_ptr clobber caught by the L3 TDD sweep.

**Structural refactors** (two module extractions): `breakpoints.s`
split from debugger.s, `gap_buffer.s` split from editor.s.  Both
were pure re-layering — zero behavioural change — to convert the
tier boundary from a disciplined convention into a compile-time fact
enforced by the linker.  L3 grew from 5 to 7 modules as a result.

**Remaining open (not blocking):** one TDD follow-up —
class-wide trailing-garbage closure for `+` / `-` — deferred because
their `expr_or_blocksize` fallback creates a double-error-on-undef
risk that needs a design pass.  See the Escape Analysis follow-up
entry below.  Everything else in this file is feature work, not
TDD.

## DDD amendments pending

Session retrospective findings (debugger trace workflow,
2026-04-22 to -24) and 2026-04-25 DDD Maintenance round.

Items are classified by **scope of applicability**, not by their
source.  *Universal* amendments tighten the DDD/TDD method itself;
*domain-class* amendments apply only to projects of a particular
shape; *project-specific* items belong to CSE alone.

**Status (2026-04-27):** Tier A landed three amendments to
README.md (DDD Method + Escape Analysis); Tier B landed two
principles in testing.md (14 + 15) and one in README.md
(Principle 7); Tier C1 was *initially* closed with a documented
"harness limitation" in testing.md, then **re-opened** when
deeper RCA showed the diagnosis was wrong, and finally **closed
2026-04-27 by Phase 24** — the cold-init bug fix landed (F1 +
F2), the testing.md harness-limitations entry was retired, and
three new Escape-Analysis principles (16: cold-init terminal-
state assertion; 17: sequence-prerequisite declaration; 18:
multi-CPU integration-test parity) were promoted from the
bug-entry candidates into testing.md.  `mn_config.s` retirement
closed cleanly under § Architecture.

### Tier A — Universal DDD System amendments

*Apply to any project under DDD discipline, regardless of domain.
These amendments belong in [doc/README.md](README.md) (DDD Method
/ Escape Analysis) or [doc/testing.md](testing.md) at the
process-level layers, not at the principle-list layer.*

- [x] ~~**Escape Analysis "triage" gate between sweep and commit**~~
  (closed 2026-04-25).  README.md § Escape Analysis: step 5
  rewritten to produce a *candidate list* (not yet decisions); new
  step 6 *Triage the sweep* sits between sweep and commit, splitting
  candidates into mechanical-inline / queued-TODO / skip-worthy
  buckets.  Step 6 (commit) renumbered to step 7.

- [x] ~~**Cycle-detection heuristic**~~ (closed 2026-04-25).
  README.md § DDD Method step 4 (Implementation) gained the
  *Cycle-detection rule*: ≥3 modifications of the same proc/section
  in one session for the same concern signals an unclear spec —
  pause and clarify before iterating.

- [x] ~~**Commit granularity rule**~~ (closed 2026-04-25).
  README.md § DDD Method step 6 (Commit) gained the *Granularity
  rule*: one fix per commit unless the fixes are trivially
  co-dependent.  Escape Analysis step 7 explicitly suspends the
  rule (the value of an EA closure is in seeing the bug fix, the
  missing test, and the contract/principle amendment land as one
  auditable unit).

### Tier B — Domain-class amendments

*Apply only to projects of a particular shape.  Not universal:
a project outside the named class does not need the amendment.
Each item names the class it depends on.*

#### B1. State-machine projects

*Projects with enumerated states consumed by multiple sites:
compilers, debuggers, protocol implementations, workflow engines,
game logic.  Pure libraries and stateless tools are out of class.*

- [x] ~~**State-introduction principle** (proposed testing.md
  Principle 14)~~ (closed 2026-04-25).  Landed as testing.md
  Principle 14 (*Enumerated-state introductions enumerate the
  cross-product*) with the dbg_reason × command escape as
  cautionary example.  Scope-limited to projects with enumerated
  states consumed by multiple sites — explicitly NOT universal
  per the Tier B1 classification.

#### B2. Projects with rendered output / UX

*Projects whose contract surface includes pixels, screen layout,
or stream-formatted output: TUI tools, GUIs, REPLs with on-screen
panels.  Pure libraries with structured-data return values are
out of class.*

- [x] ~~**Display-content vs state-content test distinction**
  (proposed testing.md Principle 15)~~ (closed 2026-04-25).
  Landed as testing.md Principle 15 (*Display-content and
  state-content are different contracts*) with the DBG_RTS
  panel-render escape as cautionary example.  Cross-references
  README.md Principle 7 (*Contract the model, not the render*)
  for the doc-side complement.

- [x] ~~**DDD-Lite for UX**~~ (closed 2026-04-25).  Landed as
  README.md Principle 7 (*Contract the model, not the render*)
  with the debugger.md "Step output semantics" appendix as
  cautionary example.  Names testing.md Principle 15 as the
  test-side complement.  Together the two principles draw the
  line: docs specify abstract behaviour, tests assert abstract
  visible results, code owns the render.

### Tier C — Project-specific (CSE)

#### C1. Process / methodology debt

- [x] ~~**Test-harness layout fragility investigation**~~
  (closed 2026-04-27 alongside the cold-init bug fix).  The
  2026-04-25 closure attributed the fragility to a py65 step-
  engine artifact (wrong diagnosis); the 2026-04-25 RCA pass
  showed it was a production cold-init bug; the Phase-24
  dedicated session landed F1 (cold-init order swap) and F2
  (`gb_init` becomes a leaf, `update_workend` lifts to
  `ed_init`'s wrapper).  All 17 previously-fragile tests in
  `test_kernel_transition.py` are stable green without
  per-test triage — exactly as the bug-entry prediction table
  forecast.  See [§ Bugs](#bugs) for the closed bug entry.

#### C2. Corpus-coverage gaps (DDD Maintenance 2026-04-25)

*Tracked further down under § Planned / Corpus.  The items
there are mechanical fixes; this header just acknowledges they
belong in the same taxonomy.*

## Bugs

Open bugs, roughly ordered by priority.

- [x] ~~**★ HIGH — Cold-init silently faults and recovers on CMOS;
  6510 build is fully broken in test path.**~~  **Closed
  2026-04-27, Phase 24.**  Fixed by:

  - **F1** (commit d9cac91 — *Phase 24 F1: order sym_clear before
    ed_ensure_init in cold init*).  Reorders `_main` cold-init
    so `sym_clear` precedes `ed_ensure_init`.  `_st_heap` is
    valid by the time `gb_init`'s tail-call to `update_workend`
    fires; `heap_copy_name` writes to SYM_HEAP ($E600) rather
    than $0000-$0007; the `$01` corruption + BASIC-shadow BRK
    chain is gone.
  - **F2** (this commit — *Phase 24 F2: …*).  Removes
    `gb_init`'s `jmp update_workend` tail-call (gb_init becomes
    a pure leaf with no symbol-table contact); lifts the
    workend publication to `editor.s::ed_init` as an explicit
    `jmp update_workend` tail-call.  Eliminates the layering
    inversion (gap buffer reaching into the symbol table) that
    let the bug exist.

  Net code delta: gap_buffer.s -2 B (jmp→rts), editor.s +3 B
  (added jmp), main.s ±0 B (reorder).  Total +1 B.

  Tier I tests pinning the new contract (testing.md
  Principle 16, *Cold-init terminal-state assertion*) added
  in `test_kernel_transition.py::TestColdInitTerminalState`:
  no-BRK/no-recover, workstart/workend resolvable, $0000-$0007
  uncorrupted, free-ZP `$FF` fill, free-workspace `$00` fill.
  Tier U test pinning F2's leaf contract added in
  `test_gap_buffer.py::TestGbInitLeaf`.

  Verification: full suite 3057 passed / 18 skipped; the 17
  previously-fragile tests now stable green.  6510 build no
  longer enters the BASIC ROM shadow during cold init (the
  fault chain is gone in all variants because the corruption
  itself is gone).  Multi-CPU integration-test parity is
  tracked separately under § Architecture as a follow-up.

  Original symptom + RCA preserved below for the audit trail.

  ### Original RCA (pre-fix)

  #### Symptom

  After `_cold_init_to_prompt(emu)` runs against the production
  CMOS PRG via the integration-test harness, `$01` reads `$36`
  and tests pass.  Pretty-printed banking looks normal.  But the
  intended `_main` flow has not actually completed — control has
  jumped through a kernel-fault recovery path and arrived at
  `main_loop_top` via an entirely different route than `_main`'s
  source code suggests.

  The 17-test fragility under `_cold_init_to_prompt` (previously
  attributed to a py65 step-engine edge case) is in fact this
  bug: the fault chain is layout-dependent because the byte
  patterns in BASIC ROM determine whether the BRK fires cleanly,
  whether `cse_brk_handler` reaches `cse_recover` cleanly, and
  whether `cse_recover`'s subsequent path stays out of the
  shadow.  Real silicon and VICE were never tested against this
  flow because both auto-bank correctly via the `$01` write CSE
  *thinks* it's making — but on emulator + py65 the wild ride
  through BASIC ROM bytes is observable.

  #### Reproduction

  Three probes against `build/debug/cmos/cse-cmos.prg`:

  **Probe 1** — `_cold_init_to_prompt`, then read `$01`:
  ```
  After cold-init: PC=$7C94 (main_loop_top) $01=$36
  ```
  Looks normal.

  **Probe 2** — same, hooking every write to `$01`:
  ```
  [0] save_zp+0xf            $36 →  $36
  [1] kernal_bank_out+0x9    $36 →  $34
  [2] heap_copy_name+0xd     $34 → ★$4F   ← corruption
  [3] kernal_bank_in+0x9     $4F →  $47   ← LORAM=1, BASIC banked IN
  [4] hw_reinit_body+0x3     $47 → ★$36   ← fault recovery resets $01
  ```

  **Probe 3** — same, watching for CPU entries to fault paths:
  ```
  cyc=1137  $A4F4   BRK at define_ws_syms+0x1
  cyc=1148  $7EBD   enter cse_brk_handler  in_userland=0 → fault
  cyc=1151  $7F8C   enter cse_recover
  cyc=1157  $7FC3   enter hw_reinit_body
  cyc=6464  $7C94   REACHED main_loop_top
  ```

  #### Full chain

  1. **Order bug in `main.s` cold-init.**  Line 224 calls
     `ed_ensure_init` before line 227 calls `sym_clear`.
     `ed_ensure_init` → `gb_init` → `update_workend` →
     `sym_define` → `heap_copy_name`.  `heap_copy_name` reads
     `_st_heap` (zp `$3D-$3E`) which is BSS-zero ($0000) at this
     point — `sym_clear` hasn't run.  The inner copy loop
     `sta (_st_heap),y` writes the source name `"workend\0"`
     across `$0000-$0007`.

  2. **DDR + CPU-port corruption.**  `$0000` (DDR) gets the first
     name byte ($57 = `'W'` screen-code).  `$0001` (CPU port latch)
     gets the second ($4F = `'O'`).  After the next
     `kernal_bank_in` ORs bit 1 in, the latch is `$47`: LORAM=1
     (BASIC banked IN), HIRAM=1, CHAREN=1, plus stray bit 6.

  3. **`define_ws_syms` falls in the BASIC shadow.**  At
     `main.s:228` the next instruction is `jsr define_ws_syms`.
     `define_ws_syms` lives at `$A4F3` (CMOS) — inside `$A000-$BFFF`.
     With LORAM=1 the CPU fetches BASIC ROM at `$A4F3`, not the
     real `define_ws_syms`.  BASIC ROM byte at offset `$04F3` is
     a one-byte instruction; PC advances to `$A4F4`; BASIC ROM
     byte at offset `$04F4` is `$00` → BRK fires.

  4. **Kernel-mode BRK trap.**  `cse_brk_handler` reads
     `in_userland`, finds it `0`, takes the kernel-fault branch:
     `jmp cse_recover`.

  5. **Fault recovery as accidental cold-init.**  `cse_recover`
     resets SP to `$FF`, calls `hw_reinit_body` (which writes
     `$36` to `$01` — fixing the banking — then runs
     `setup_interrupts`, `dbg_init`, `reset_globals`, `io_init`,
     `theme_init`, `restore_colors`, `set_charset`), then
     `end_debug_body`, then `refresh_body`, then
     `jmp main_loop_top`.

  #### What this means

  **`main.s` cold-init never reaches lines 227+ on CMOS.**  The
  intended cold-init flow from `sym_clear` onward (sym_clear,
  define_ws_syms, CPU-mode default, free-ZP fill, free-workspace
  fill, the splash sequence, the first userland transition,
  global state init) is dead code in practice.  The production
  CMOS build always cold-boots through the recovery path.

  **6510 build is broken differently.**  Probe against
  `build/debug/6510/cse.prg` shows the same corruption (writes
  [0]–[3] identical) but no write [4] — `hw_reinit_body` never
  fires because the BASIC ROM bytes at 6510's `define_ws_syms`
  address don't produce a clean BRK.  `$01` stays at `$47`.
  `dbg_bp_clear` (`$A226`) and `return_to_userland` (`$A333`) are
  in the shadow and unreachable; the CPU times out wandering
  through BASIC ROM.  Integration tests don't exercise the 6510
  PRG so this is currently invisible.

  **Test suite is only green because** the integration tests
  use only the CMOS PRG, and CMOS happens to fault in a way
  that recovers cleanly.  Layout shifts that change BASIC ROM
  byte patterns at the affected addresses can:
  - move the fault from the clean `BRK at $A4F4` to a different
    address, possibly one where recovery doesn't reach
    `main_loop_top`;
  - cause the recovery path to itself land in the shadow at a
    bad byte;
  - mask the fault entirely (BASIC ROM byte happens to be a
    benign instruction sequence that returns to RAM).

  This is exactly the "fluctuates pass/fail at $B5xx / $7Dxx"
  symptom the C1 entry described — but it's the *production*
  cold-init that's fragile, not the harness.

  #### Fix candidates

  - **F1 — Reorder cold-init.**  Swap `main.s:224` and `:227`:
    `sym_clear` before `ed_ensure_init`.  Prevents the heap
    corruption, prevents the BRK, prevents the silent recovery.
    One-line change.  Low-risk if the rest of cold-init is sound.

  - **F2 — Decouple `gb_init` from the symbol table.**  Remove
    the `jmp update_workend` tail call from `gap_buffer.s::gb_init`.
    Make `update_workend` an explicit call at every cold-init /
    `ed_new` / disk-load site.  Cleaner separation of concerns.
    Subsumes the F1 fix.  More call-site churn.

  - **F3 — Defend `heap_copy_name`.**  If `_st_heap < SYM_HEAP`,
    refuse to write or fall through to `sec; rts`.  Mask only;
    doesn't fix the upstream ordering issue.  Useful as a
    belt-and-braces against future regressions.

  #### Phased landing plan

  Per session DDD Method.  Each phase has an explicit gate.

  **Phase 0 — Read past `main.s:266`.**  Tabulate everything
  `_main` does between line 227 (`sym_clear`) and the final
  `jmp main_loop_top`.  Tabulate everything `cse_recover` does
  between its entry and its `jmp main_loop_top`.  Diff the two.
  The diff is the body of state changes that **today never
  occur on CMOS cold-init**.  Outcome: a delta table that
  predicts what F1 will newly observe.

  **Phase 1 — Predict latent issues from the delta.**  For each
  delta entry, decide: (a) does it matter?  (b) does any test
  assert it post-cold-init?  Likely candidates for surprise:
  - free-ZP fill with `$FF` (lines 237–244)
  - free-workspace fill with `$00` (lines 246–259)
  - the splash + first-userland-transition pair (after line
    266, unread)
  - the symbol table actually getting a real `workstart` /
    `workend` instead of corrupted `$0000` ZP pointers

  **Phase 2 — Apply F1.**  One-line swap.  Run the full test
  suite.  Triage any new failures: they're the latent issues
  Phase 1 predicted (or didn't).

  **Phase 3 — Decide F2.**  After F1 is green, evaluate whether
  `gb_init`'s tail call to `update_workend` should be removed.
  `gb_init` is called from at least three places (`ed_init`,
  `ed_ensure_init`, and possibly disk-load); each needs an
  explicit `update_workend` if F2 lands.

  **Phase 4 — Escape Analysis pass.**  This bug class —
  *layout-dependent silent fault during cold-init recovers
  transparently and the test suite reads recovery state as if
  it were intended behaviour* — escaped because:
  (a) tests don't compare cold-init paths against expected
      sequences;
  (b) `cse_recover` is too willing to act as a cold-init
      fallback (it runs the full hw_reinit + soft-reset
      sequence, which is everything cold-init needs);
  (c) the test suite runs only CMOS, so the 6510 break is
      invisible.

  Candidate principles to amend (testing.md / README.md):
  - **Cold-init terminal-state assertion.**  `_main` must
    reach `main_loop_top` without `cse_brk_handler` or
    `cse_recover` ever being entered.  Asserted by a Tier I
    test that hooks both entry points and fails if either
    fires during cold-init.
  - **Sequence-prerequisite declaration.**  Modules whose
    entry points depend on prior init (e.g. `gb_init` requires
    sym table to be initialised because of its tail call) must
    declare the prerequisite in their module doc and assert it
    in tests if any caller could violate it.
  - **Multi-CPU integration-test parity.**  At least one
    integration test should run against each production PRG
    variant (6502/6510/cmos), not just CMOS.  Otherwise CPU-
    specific cold-init breakage is invisible.

  #### Latent issues F1 may surface

  After F1 lands, anything `_main` 227+ does that `cse_recover`
  doesn't may newly become observable.  Known differences:

  | Step | What `_main` does (line) | Done by `cse_recover`? |
  |------|--------------------------|------------------------|
  | `sym_clear` (227) | clears 256 hash slots, resets `_st_heap` | **No** |
  | `define_ws_syms` (228) | defines `workstart`/`workend` | **No** |
  | `sta asm_cpu` (234) | sets default CPU mode | maybe via `reset_globals` — verify |
  | free-ZP fill `$FF` (237–244) | scratch sentinel | **No** |
  | free-workspace fill `$00` (246–259) | clears user RAM | **No** |
  | `io_init`, `theme_init` (262–263) | I/O + theme | **Yes** (in `hw_reinit_body`) |
  | `reset_screen`, `set_charset` (264–265) | screen + charset | **Yes** (in `hw_reinit_body`) |
  | rest (266+) | unread; tabulate in Phase 0 | ? |

  #### Investigation artifacts

  Probes used during the 2026-04-25 RCA (now removed but
  reproducible):

  - `_rca_probe.py` — confirm `$01=$47` after cold-init, trace
    8 instructions from `return_to_userland`.
  - `_rca_probe2.py` — hook every `$01` write during cold-init,
    log the call site.
  - `_rca_probe3.py` — capture `_st_heap` at the moment of the
    offending `sta (_st_heap),y`.
  - `_rca_probe4.py` — log every write to `$3D`/`$3E` during
    cold-init (proves `sym_clear` runs *after* the corruption).
  - `_rca_callchain.py` — watch every CPU step for entries to
    `cse_brk_handler`, `cse_recover`, `hw_reinit_body`; dump
    BRK frame to identify origin.

- [x] ~~Disable C64 SHIFT+C= mode switch on CSE init~~ (fixed: main.s)
- [x] ~~`i` command output shows stale memory map~~ (fixed: repl.s
  tail table now shows sym $E000-$EEFF, cse $EF00-$F8D9 banked,
  rom $F8DA-$FFFF instead of single rom $E000-$FFFF)
- [x] ~~`.const FOO` then `sta FOO` not found~~ (fixed: expr.s label
  scanner now folds $C1-$DA → $41-$5A in-place; shifted uppercase
  letters from the lowercase/uppercase charset are accepted)
- [x] ~~Uppercase REPL commands parsed as lowercase.~~  (fixed:
  `scr_to_pet` now maps screen code $40–$5F → PETSCII $C0–$DF.
  Latent bug from Phase 6 — `read_line`'s screen→PETSCII
  conversion always collapsed uppercase into the lowercase
  range.  Dispatch table entries $C2/$C3/$D1 were unreachable.
  Phase 17)
- [x] ~~INS in REPL: overwrites char under cursor~~ (fixed: main.s
  INS shift loop had off-by-one — `beq` exited before copying the
  char at cursor position; removed the early exit)
- [x] ~~`?` calculator wrong decimal for >= $2000~~ (fixed: repl.s
  `put_dec5_sp` replaced with `io_putdec` delegation; `utoa_sub`
  rewritten with pha/pla pattern from io_putdec)
- [x] ~~`a` save line writes filename "oup"~~ (fixed: asm_src.s
  seg_print_save now checks for `,s` suffix before poking; if no
  suffix, appends `,p` instead of overwriting last char)
- [x] ~~`l "out,p" $2000` doesn't load to $2000~~ (fixed: disk.s
  SETLFS secondary address was inverted — SA=0 means use X/Y addr,
  SA=1 means use PRG header addr; code had them backwards)
- [x] ~~RUN/STOP debounce~~ (already debounced: `@deb_wait` polls
  $91 until key released, then drains keyboard buffer)
- [x] ~~`.` and `m` show CSE ZP instead of user ZP after j/debugger
  context.~~  (Phase 19 — fixed: unified user-ZP redirect for
  both read and write across `m` and `.` via `zp_stage_prep` /
  `zp_poke` helpers in repl.s.  See [repl.md § User-ZP view](modules/repl.md#user-zp-view).
  Inline mnemonic assembly into ZP during a break remains
  unredirected by design — the hex-poke form handles the real
  use case.)
- [x] ~~**CRITICAL**: save writes wrong memory region~~ (fixed:
  disk.s had a local `_io_tmp = $FB` shadowing the canonical
  symbol in zp.s at `$2D`.  Commit `278a2f6` changed repl.s's
  `sta $FB` → `sta _io_tmp` which resolved to `$2D`, but
  disk.s still read from `$FB`.  Fix: removed the local
  define; disk.s now imports `_io_tmp` from zp.s.  Phase 17.)
- [x] ~~One too many newline before floppy status~~ (fixed:
  disk_done's `log_close` was redundant — callers (prg_line,
  log_err) already close their line with a newline.  Phase 17.)
- [x] ~~l/s accumulates `,p,p,p...` in cur_filename~~ (fixed
  twice in Phase 17.  First pass: `seg_print_save` recognised an
  existing `,p` suffix.  Final fix: the project-name refactor —
  `cur_project_name` stores a clean stem (no suffix, no trailing
  dot), so accumulation is impossible at the source.  See the
  "Refactor internal default filename" item below.)
- [x] ~~`r` command flags decode: the dash becomes a strange char~~
  (fixed: added `cmp #'a'; bcc @fp` before the `and #$DF` so
  non-alphabetic chars like `-` pass through unchanged.  The
  dash now displays as `-` regardless of P-bit state.  The
  deeper convention/flip bug is tracked separately.  Phase 17.)
- [x] ~~`r` command flags handling inverted/broken~~ (fixed:
  display now `cmp #'a'; bcc; ora #$80` for alphabetic letters
  only (lowercase → canonical uppercase $C0-$DF); parser now
  sets bit=1 only when typed char is uppercase ($80 bit set
  after scr_to_pet fold).  Lowercase → bit=0, dash or missing
  → bit=0.  Input is position-based: each slot checks only its
  own flag letter.  Userland update works automatically via
  `@tramp` in dbg_enter which reads reg_a/x/y/p at JSR-to-
  user-code time.  Phase 17.)
- [x] ~~NIT: `.bas` stub lacks a space after `REM`~~ (fixed:
  asm_src's emit_bas now emits a space byte between the REM
  token and the string text.  Stub length adjusted +1.  Phase 17.)
- [x] ~~NIT: unsaved-changes prompt appears twice~~ (fixed:
  merged `check_unsaved` and per-command prompts into a shared
  `confirm_action` helper.  `k`, `q` show `"; del src? y/n"` /
  `"; quit? y/n"` when clean, `";!unsaved. del src? y/n"` /
  `";!unsaved. quit? y/n"` when dirty.  LOG_WARN level when
  dirty, LOG_INFO when clean.  Phase 17.)
- [x] ~~`s:name` overwrite~~ (fixed: PRG save now uses OPEN+CHKOUT+
  CHROUT+CLOSE like SEQ save, with `"@:<name>,p,w"` constructed
  via the shared `build_open_str` helper.  Both paths now have
  symmetric KERNAL call structure and consistent overwrite
  semantics.  PRG payload writes a 2-byte load-address header
  then the bytes.  `build_open_str` generalised to take type
  ('s' or 'p') in X in addition to mode in A.  Phase 17.)
- [x] ~~Debugger: stepping into a subroutine then `c` (continue)
  cannot return through the original JSR's pushed return address.~~
  (fixed via the Phase 18 shared-stack model: user and kernel share
  the hardware stack; kernel never writes below user's SP, so JSR
  return addresses pushed during stepping stay intact across
  break/resume cycles.  The old two-image swap design was
  superseded before implementation.  See
  [memory_design.md § Stack contract](memory_design.md#stack-contract).)
- [x] ~~Assembler: `bne <nonexisting>` reports "bad insn"~~ (fixed:
  `asm_expr_error` entry point sets `asm_expr_err=1`; `.` command
  and source assembler now print `expr_error_str` detail e.g. "undef")
- [ ] Debugger: stepping `t1` over a JSR to KERNAL ROM ($E000+)
  silently falls back to step-over (per @jsr's RAM-target check).
  Consider showing a one-line note (e.g. `; rom step -> over`).
  Low priority.  (Workspace gate added in a follow-up — step BRK
  arming refuses outside [workstart, workend] with ";!range" warn,
  which catches the broader cases.  This specific JSR-to-ROM case
  still falls through silently because step_next_pc rewrites the
  lookahead to PC+3 (in-workspace) before the gate sees it.)
- [x] ~~**TDD Maintenance finding** (Principle 13 sweep 2026-04-20):
  `editor.ed_read_line` has no position-pinning witness.~~  (resolved
  via option b: four new test methods in
  `tests/integration/test_editor.py::TestEdReadLine` pin read_ptr
  advancement — exact-delta for CR-terminated lines, empty-line
  edge case, no-CR-last-line scan-to-EOF behaviour, and post-EOF
  idempotency.  The contract in editor.md was also tightened:
  the earlier "at EOF returns without advance" phrasing was
  imprecise — the *first* EOF call may advance (to cross the gap
  and reach BUF_END); what callers rely on is that subsequent EOF
  calls are idempotent.  Closes L4 TDD parity with L0–L3.)
- [x] ~~**BUG** (class-wide, Escape Analysis 2026-04-20): REPL commands
  that take a single expression silently accept trailing garbage.~~
  (resolved: extracted `_require_eoi_or_err` helper in repl.s and
  applied to `@` (seek), `B` (block size), `C` (color), and `j`
  (jump) — all now reject trailing non-whitespace/non-comment
  content as `;?syntax`.  Tests parametrised in test_repl.py across
  TestAddressCommands / TestBlockSize / TestColorCommand /
  TestCalculator.  repl.md § Single-expression command contract
  updated to list all five commands (`?` `@` `B` `C` `j`) as
  covered.  Remaining: `+` and `-` share the class but are
  complicated by their `expr_or_blocksize` fallback — tracked as a
  follow-up below.)

- [x] ~~**Escape Analysis follow-up** (Principle 11 class closure):
  apply the `_require_eoi_or_err` pattern to `+` and `-`.~~
  (resolved: commit 805ece5 added an unconditional EOI check after
  `expr_or_blocksize` in both `@h_plus` and `@h_minus`.  The double-
  error concern in the original entry turns out to be narrower than
  feared — `try_expr` advances `rp_ptr` past the expression even on
  error, so the EOI check on `+ undefsym\0` sees NUL at rp_ptr and
  passes silently (one error only).  Double-error only fires on
  `+ undefsym GARBAGE` where there's actual trailing content after
  the bad expression — acceptable: the user typed two distinct
  errors and gets one complaint per.  The same migration also
  covered `t`/`o` (via `try_expr_or_err` wrapper — see § 37 of
  optimization.md), `b ADDR`, `m` (both @dump and @ed_done),
  and `d`.  Full Principle 11 class closure on single-expression
  commands.)

- [ ] **BUG** Disk: `l "foo` (filename with missing closing quote)
  errs `;?expr undef` but loads the file anyway.  Two issues
  conflated: (a) the parse path raises an expression error on the
  unterminated string yet still proceeds with the load (should
  abort on syntax error before any I/O); (b) "expr undef" is the
  wrong error class for an unterminated string literal — should
  be `;?syntax` or a dedicated string-parse error.  Reproduce:
  type `l "foo` (no closing quote) at the prompt.  Investigation:
  cmd_load's filename parse — find where the missing `"` is
  detected vs where the load actually fires; the abort path is
  missing or wrongly placed.
- [ ] **BUG** Editor: switching to the editor after `l` always
  inserts a tab on entry, even when the buffer already has
  source loaded (so the first line gets a leading tab where it
  shouldn't).  Should only auto-tab when entering an empty
  buffer.  Reproduce: load a non-empty source via `l NAME`,
  then enter the editor (any path).  Investigation: editor's
  on-entry hook — likely an unconditional "indent for new line"
  that should be gated on buffer-empty.

- [x] ~~**BUG** Debugger: regular RTS from userland with debug
  off prints a bogus `; rts at $<main_addr>` info line~~ — the
  address shown is the j-target (cur_addr the handler reset
  brk_pc to), not the actual rts instruction's location.
  Reproduce: `j main` on a program that returns cleanly; the
  panel reads e.g. `; rts at $0800` even though main's rts
  is at $0814.  Three possible fixes (in order of effort):
    (a) Pure `; rts` (drop the address) — cheapest; clear
        signal that the program returned, no misleading addr.
    (b) Drop the info line entirely, show just the reg dump
        — minimal "session ended" panel.
    (c) `; rts at <real rts addr>` — would need to track the
        actual rts PC at handler entry (before the brk_stub
        reset) and surface it; doable but more state.
  The current behaviour came from the DBG_RTS handler classifier
  (fd1c67b) resetting brk_pc := cur_addr so the disas line in
  the panel showed user-meaningful code; the info-line address
  inherited that reset and now misrepresents.
  (Fixed 1ecc863: option (a) — show_break_result skips the
  " at $PC" emit for DBG_RTS.  Pure "; rts" + reg row.)

- [x] ~~**BUG** Debugger: repeated `t` after a clean-exit RTS
  alternates between `; brk` and `; rts` (visible on tight loops
  like a one-rts test program).  Cause: clean exit lands at
  brk_stub → handler sets DBG_RTS + clears last_cmd.  User must
  type `t` (RETURN no longer repeats).  cmd_step gates DBG_RTS
  to cold-preview path → emits `; dbg`, promotes dbg_reason to
  DBG_BRK, arms cold_preview_done.  Next `t` steps the rts via
  @rts → lands at brk_stub again → DBG_RTS again.  Result: the
  user perceives an alternating `; brk` / `; rts` pattern (the
  `; dbg` cold-preview tag may be misread as `; brk`, or the
  next step's actual `; brk` panel from a non-trivial program
  alternates with the `; rts` clean exit).  Reproduce: tight
  test with `j main / t / t / t / ...` after the program has
  already returned once.  Investigation: cmd_step's cold-preview
  re-firing after every clean exit may be the wrong UX — once a
  session has terminated, perhaps subsequent `t` should be
  rejected entirely (mirroring `c` after DBG_RTS) instead of
  silently restarting.  Or: the cold-preview path could detect
  "this is a re-entry to the same brk_pc" and skip the preview
  emit, going straight to step.  Tied to the broader question
  of "what does `t` mean when the session is terminal?".~~
  (Fixed 1ecc863: cmd_step now rejects t/o on DBG_RTS with
  "; ?no ctx", mirroring cmd_continue.  DBG_NONE still triggers
  cold preview as before; DBG_RTS terminal session needs j/g
  to restart.)

- [x] ~~**Escape Analysis sibling (bug 2)**: enumerate the
  `dbg_reason × command` matrix in doc/modules/debugger.md and
  ensure every cell is specified + tested.~~  (Matrix landed in
  debugger.md § dbg_reason × command matrix; code aligned in
  the same commit.  Three behavioural patterns per command:
  *transparent* (r, l, s, R — no debug gating), *gated by
  reason* (c, t, o), *end-debug-and-replay* (j, g, a — warn,
  ask, end debug, replay command).  Code changes: cmd_jmp got
  the warn+ask gate (covers j and g); cmd_load lost its
  warn_if_debug (l/s now transparent); @h_reset simplified to a
  single "init? y/n" + idempotent end_debug_body.  str_go added
  for the j/g prompt.  Tests still need cell-by-cell coverage —
  separate TODO if pursued.)

- [ ] Assembler: `a` source-assemble warn+ask when emit
  destination is outside [workstart, workend].  `.org $f100\nlda #0`
  silently writes to KDATA today.  Same risk class as bug 3
  (CSE state corruption during a debug workflow), same gate
  range.  Pattern: per-segment check at `_seg_log_open` time
  (or per-byte at emit time, whichever has the lower overhead);
  if first emit address is out-of-range, prompt
  `;!range / asm? y/n`.  Yes proceeds (user override); no
  cancels the assemble.  This is the only sibling from bug 3's
  sweep judged worth chasing — other footguns (m-poke,
  .-assemble at `@`-set cur_addr, l-to-address) are explicit
  user actions and stay un-gated; the assemble case is special
  because `.org` lives in source code and is easy to typo into
  CSE-shadow ranges without realising.

- [ ] **BUG** Assembler: `jsr a` reports "bad insn" but segment
  output still follows (seems to complete the assembly run?).
  Switching to `jsr ax` or `jsr aa` works.  Unclear whether
  single-letter label `a` is being rejected at mnemonic-classify
  time (short labels colliding with instruction-prefix disambiguation),
  at expr-parse time (one-letter labels are valid — e.g. `.const
  a $1000` — so this would be a regression), or somewhere in
  addressing-mode parsing.  The "segment output still follows"
  detail suggests the error is raised but not fatal — the source
  assembler's error recovery may allow the bad line through.
  Reproduce: assemble a source with `.const a $1000` then
  `jsr a` on another line.  Investigation: compare the parse path
  for `a` (single letter) vs `aa` / `ax` (two-letter labels) in
  `au_mode.s` / `asm_line.s` — suspect the branch that checks
  "label? or addressing-mode character (A/X/Y)?" is biased toward
  addressing mode for the single letter `a`.
- [x] ~~**BUG**: `. .` is accepted as a valid dot-assemble source~~
  (fixed via Escape Analysis c8501d2: the actual symptom was
  "silent no-op" not "emits $00" — the cmd_dot @try_mne gate in
  repl.s silently fell through to the display-only @show path for
  non-letter input.  Fixed by splitting the gate: NUL/`;` →
  @show (valid silent redisplay), letter → dot_assemble, anything
  else → @syn_err.  repl.md now documents the `.` command's input-
  shape matrix as a four-cell commitment; testing.md Principle 11
  gains this as a second cautionary example after the asm_cpu gate.)
- [x] ~~**BUG**: not all log functions honour the "enter anywhere,
  exit at col 0" contract~~ (resolved via Escape Analysis: the
  bug turned out to be under-testing, not under-implementation —
  a probe of all 9 line-starters at CUR_COL=12 showed every one
  auto-advances correctly.  The invariant was transitively honoured
  through composition (log_line/err/warn/info → log_open;
  seg/prg/free_line → info_line_head) but only pinned at
  log_open directly.  Fixed by TestEnterAnywhereContract in
  test_log.py: a parametrised sweep over all 9 line-starters,
  each asserting (a) cursor advanced past TEST_ROW, (b) TEST_ROW
  at cols 12+ untouched.  log.md's Contract section now
  enumerates the per-function behaviour as a table (enter-anywhere
  × exit-at-col-0 matrix), turning the compositional guarantee
  into a per-function commitment per Principle 8.)
- [x] ~~Userland exit does not restore screen state.~~ (fixed:
  `vic_reset` in screen.s forces $D011=$1B, $D016=$C8, $D018=$15,
  $D015=0, $D01A=0, $D019=$0F on every userland → kernel
  transition.  Wired into `hygiene_after_userland`; the old
  `ora #$02` on $D018 replaced by absolute `lda #$15 / sta`.
  `restore_colors` still applies theme + colour RAM.  Promotes
  the Planned `vic_reset` item below to Done.)
- [ ] Debugger: fast turnaround in the BRK handler for long
  trace loops.  Today every step iteration runs the full save/
  restore_userland_zp + save/restore_kernel_zp pair — two 128-byte
  ZP copies (one user→buf, one buf→live) per break/resume cycle.
  For `t 100`-class stepping the ZP churn dwarfs the actual user
  instruction cost.  Opportunity: detect "we're mid-chain, no
  REPL code will run between break and resume, kernel ZP state
  hasn't been consumed" and skip the ZP swap entirely — just
  keep user ZP live across the handler's chain body (step_next_pc
  doesn't touch user ZP, only reads abs/stack addresses).  Must
  still handle NMI breakouts: if NMI fires during the fast-turnaround
  chain, the handler needs to fall back to the full ZP swap and
  longjmp so post_run_cleanup sees a consistent ZP view.  Consider
  a flag (`step_fast_chain` or similar) that save_userland_state
  tests to skip the ZP swap when set, and arm it in cmd_step's
  seed + the handler's chain path.  Expected saving: ~2 * 128 =
  256 cycles per step iteration.
- [x] ~~Debugger: what do we do if we trace into an actual BRK?~~
  Resolved (see debugger.md § User BRK workflow).  Rules: `o` and
  `c` skip past via `brk_skip_user` (advance brk_pc by 2 — past
  BRK + signature byte, matching CPU's RTI semantics).  `t`
  deliberately hangs to interrupt the return-step workflow for
  inspection.  No new `dbg_reason` value — opcode peek at command
  time distinguishes user BRK from step BRK / user BP via the
  centralised `brk_skip_user` helper.  IRQ vector is never
  invoked — we side-step BRK entirely.
- [x] ~~**Phase 18 — CSE as a Kernel.**~~  (done.  ISR-style kernel
  model: shared flat stack with 64-byte kernel headroom contract,
  direct vector patching via `setup_interrupts`, unified
  `save_userland_state` / `restore_userland_state` / `return_to_userland`
  gate primitives, command-loop flag-and-rts pattern, CPU-port-aware
  ZP save/restore primitives in mem.s, `vic_reset`, single
  `hygiene_after_userland` in `handler_finalize`.  See
  [design_cse_as_kernel.md](design_cse_as_kernel.md),
  [userland_contract.md](userland_contract.md),
  [memory_design.md § Stack contract](memory_design.md#stack-contract).)

  Sub-item status (all resolved unless marked [ ]):

  - [x] ~~Stack contract — drop the two-image stack swap.~~  (flat
    shared-stack; −512 B KBSS, ~−100 B CODE, ~−1500 cycles per
    transition.)
  - [x] ~~`return_to_userland` helper.~~  (in debugger.s; shares
    `_rtu_body` with `restore_userland_state`.)
  - [x] ~~`brk_stub` and clean userland exit.~~
  - [x] ~~Cold-init userland handoff.~~  (splash stays on
    `main_loop_no_clear` path.)
  - [x] ~~`in_userland` flag.~~  ($80/0 convention for `bit/bmi`
    dispatch; owned by main.s.)
  - [x] ~~`setup_interrupts` — unified vector setup.~~  (direct
    stores to $0316/$0318/$FFFA/$FFFE.)
  - [x] ~~Direct vector patching — no separate trampolines.~~
  - [x] ~~IRQ early-entry bank-out mechanism.~~  (`bank_out_stub`
    in main.s; second-RTI-frame surgery.)
  - [x] ~~Kernel stack-depth measurement.~~  (Phase 19 — done:
    `TestKernelStackDepth` in tests/unit/test_asm_src.py measures the
    `asm_src → asm_line → expr_eval` chain from a fresh SP.
    Current numbers: ~30 B trivial, ~50 B realistic, ~130 B at
    8 levels of paren nesting in an operand.  The contract stays
    at 64 B; those numbers characterise the pipeline and catch
    regressions, not the BRK-tail re-entry path.  See
    [userland_contract.md § Kernel stack budget](userland_contract.md#kernel-stack-budget).)
  - [x] ~~CSE re-entry stack-headroom warning.~~  (Phase 19 — done:
    `post_run_cleanup` (repl.s) checks `reg_sp < 64` on every
    userland exit; emits `;!stk N` where N is the decimal
    headroom.  Three tests in
    `TestStackHeadroomWarning` cover the trigger, the at-budget
    boundary, and the healthy-SP no-warn path.)
  - [x] ~~VIC sanity reset (`vic_reset`).~~  (in screen.s; called
    from `hygiene_after_userland`.  $D011/$D015/$D016/$D018/$D019/
    $D01A.)
  - [x] ~~SID silence at boundary.~~  (Phase 19 — done:
    `hygiene_after_userland` (repl.s) writes $00 to $D404/$D40B/
    $D412, releasing all three voice gates and clobbering the
    waveform selection (SID is write-only so read-modify-write of
    just bit 0 isn't possible; clobber is the practical silence
    primitive).  +11 B.)
  - [x] ~~Userland contract document — published.~~  See
    [userland_contract.md](userland_contract.md).  Three-tier state
    model, kernal-as-terminal affordance, vector/banking hazards.

  Phase 18 tail is complete.

- [x] ~~**Loader reverse-direction copy.**~~  (Phase 19 — done:
  `copy_pages_back` in loader.s, payload-end sanity check
  dropped from `compute_layout.py`.  CODE + RODATA can now grow
  up to `runtime_start`.  See [build_system.md § Copy direction](build_system.md#the-ld65-loadrun-split).
  +11 B in the discardable LOADER segment.)
- [x] ~~Debugger: refuse to write breakpoints outside workspace memory~~
  (fixed: cmd_brk now rejects BP addresses outside [$0800, __CODE_RUN__)
  with a "; ? range" error before calling dbg_bp_set.  Phase 17.)

- [x] ~~**Phase 21 — Dependency-tree simplification.**~~
  (done, commits `45ab846` → `81aaa78`.  Five moves eliminated the
  planned back-edges and established a 7-layer almost-strict DAG.
  See [architecture.md § Layer Diagram](architecture.md).)

  Five moves (as landed):

  - [x] **Move 5 — Rename `au_mode.s` → `addr_mode.s`.** Pure rename.
  - [x] **Move 1 — `mem.s` sheds `define_ws_syms`.** −49 B (6510/6502), −24 B (cmos).
  - [x] **Move 4 — Cross-module flags → `zp.s`.** Seven 1-byte flags
    (`in_userland`, `state`, `warm_cont`, `kernal_out`, `ed_dirty`,
    `dbg_reason`, `cur_device`).  −58 B per build (BSS→ZP access
    shortens every use).
  - [x] **Move 2 — Extract `asm_err.s` (Layer 2).** Owns
    `asm_syntax_error`, `asm_expr_error`, `asm_error`, `asm_expr_err`,
    `asm_pass`.  Size-neutral (pure relocation).
  - [x] **Move 3 — Extract `log.s` (Layer 2, partial).** Owns
    `log_open/close/line/err/warn/info`, `puts_imm`, log.inc.  Size-
    neutral.  Range-line formatters (`seg_line`/`prg_line`/`free_line`)
    stayed in repl.s — see follow-up below.

  **Totals:** −107 B (6510/6502), −82 B (cmos).  2681/2681 tests
  green at every commit.  Every back-edge in the Step-2 DDD Analysis
  was eliminated except the residuals listed below.

  Residual back-edges — **all cleared in Phase 21.1** (commits
  `1362bb6` + `647f0f2`):

  - [x] ~~`asm_src → repl` via `seg_line` + BSS scratch.~~  Phase 21.1
    Move 3B: shared scratch pool (`rp_addr`, `rp_cnt`, `rp_save`,
    `rp_save2`, `rp_next_lo`, `_info_mode`) migrated to `zp.s`;
    range-line formatter family (`seg_line`/`prg_line`/`free_line` +
    `info_line_*` + `_range_core` + `log_err_eol` + `log_close_eol`)
    hoisted from `repl.s` to `log.s`.  −224 to −232 B per build
    (the scratch ZP promotion hits ~209 access sites).
  - [x] ~~`asm_src → repl` via `cur_project_name`.~~  Phase 21.1
    Move 6a: 17-byte filename-stem buffer moved to `zp.s` at
    $5E-$6E.  Y→X refactor in `editor.s::ed_status` filename scan
    recovers 2 extra bytes that would otherwise fall back to abs,Y.
    −8 B per build; 17 ZP bytes spent.
  - [x] ~~`editor → repl` via `cur_project_name`.~~  Same commit.

  **Phase 21 total (including 21.1):** −339 B 6510 / −339 B 6502 /
  −314 B cmos; zero back-edges; workspace gained 256 B (runtime
  start shifted up one page).

  Revisit items:

  - [ ] **If ZP space gets tight, reconsider `cur_project_name` placement.**
    The 17-byte buffer in ZP at $5E-$6E claims space that could
    host hotter single-byte flags or 2-byte pointers.  ~40% of
    the buffer's accesses (the `(rp_ptr2),y` loops in
    `copy_stem_to_project`) can't benefit from zp encoding.
    If user-ZP pressure ever exceeds the current 8-byte free
    margin ($78-$7F), move `cur_project_name` to `disk.s` BSS
    — cost 0 ZP, code-size penalty ~8 bytes, restores no
    back-edge regression.

  Deferred Phase-21 test additions (written up in the TDD Analysis,
  scheduled for a separate commit after the phase lands):

  - [ ] `dev/check_deps.py` — mechanical scanner that parses every
    `.import` / `.importzp` in `src/*.s`, resolves each against
    per-module `.export`s, and asserts every edge is strictly
    downward per the [layer table](architecture.md#modules).
    Permanent enforcement of the strict-DAG invariant.  ~50 LOC
    Python.  Run in CI.
  - [x] ~~`tests/unit/test_asm_err.py`~~ — landed as test-restructure
    Tranche 2 (commit `ee01914`, 7 Tier-U tests covering the
    longjmp unwind contract).
  - [x] ~~`tests/integration/test_log.py`~~ — landed as Tranche 2
    (10 Tier-I tests for log primitives + range-line family via
    C64Emu screen-RAM assertions).

- [x] ~~**Phase 20 — Warmstart restructure and debug-session lifecycle.**~~
  (done, commits `c4c1992` + `08e9756`.  Reason-named entry points
  `cse_recover`/`cse_end_debug`/`cse_refresh` compose from rts-returning
  body subs.  Gates on `a`/`l`/`R` let the user end the current debug
  session cleanly.  `R` command added.  `c` errors out without an
  active debug session.  NMI in kernel mode routes to `cse_refresh`.
  Gating strings decomposed: `warn_if_unsaved` / `warn_if_debug` emit
  `;!unsaved` / `;!debug` log lines ahead of a simple "action? y/n"
  prompt; two warnings stack (unsaved before debug).  +229 B total,
  2681 tests green.  See
  [main.md § Layer 3](modules/main.md),
  [memory_design.md § Warmstart entry points](memory_design.md#warmstart-entry-points),
  [repl.md § Gating pattern](modules/repl.md#gating-pattern).)

  Follow-ups (size + coverage) — each is isolated and post-v0.1:

  - [ ] **Gate shape consolidation.**  `cmd_asm`/`cmd_load`/`cmd_reset`
    share a near-identical skeleton (warn → prompt → on-yes:
    either `end_debug_body + refresh/jmp` or `warm_cont := 1 + jmp
    cse_end_debug`).  A shared `_gate_debug(prompt_str, yes_vec)`
    helper could factor this.  Worth attempting only if the
    per-command continuation differences can be expressed as one
    dispatch byte rather than multiple branches; estimate ~20-30 B
    savings if the shape works out.

  - [ ] **`end_debug_body` zero-loop.**  Currently 8 × 3 B of
    `sta abs` (zero stores) + 3 × 3 B of `sta abs` (`$FF` stores)
    = ~33 B of straight-line stores.  Could drop to ~10 B if the
    11 fields lived contiguously in BSS.  Requires coordinating
    layout across `main.s`/`mem.s`/`repl.s`/`debugger.s` — invasive
    refactor for a ~20 B saving.  Defer until the next BSS
    reshuffle pass.

  - [ ] **Warmstart fall-through from `cse_refresh` into
    `main_loop_top`.**  Placing the three warmstart entry points
    immediately before `main_loop_top` in the file would let
    `cse_refresh` drop its `jmp main_loop_top` (-3 B).  Reorder
    and verify branch ranges don't regress anywhere.

  - [ ] **Shared `@*_cancel` exit in `exec_line` dispatch.**
    Five gated commands (`k`/`Q`/`R`/`a` plus `l`'s gate in
    `cmd_load`) each have a local `jmp nl_clear` cancel tail
    (3 B × 5 = 15 B).  Folding to a single shared label would
    save ~12 B but branch range inside the large `exec_line`
    `.proc` body was the blocker.  Revisit with a linker-map check.

  - [ ] **End-to-end gate tests (keypress injection).**  Current
    `TestGating` covers only the `warn_if_*` helpers directly.
    The full `R`/`a`/`l` flows (warn → prompt → y/n → outcome)
    would benefit from integration tests that inject keys via
    `C64Emu.inject_key`.  Coverage, not size.

  - [x] ~~**String aliasing for new gating strings.**~~  (Done in
    the polish pass — `confirm_action` renamed to `query_user`,
    `"? y/n"` folded into a shared `str_qynq` trailer printed by
    the helper, and each action string shortened to its verb stem.
    -25 B per build.)

  - [ ] **Cold init ↔ `hw_reinit_body` sharing.**  Cold init's
    steps 4/5/11/12 (`setup_interrupts`, `dbg_init`, `io_init`,
    `theme_init`, `set_charset`, `reset_globals`) overlap heavily
    with `hw_reinit_body`.  Different: cold init has `reset_screen`
    between `theme_init` and `set_charset` and lacks `restore_colors`
    (no theme yet).  A unified pipeline with a configurable
    middle step would save ~9-12 B.  Invasive (touches boot
    ordering); defer.

### Fixed bugs (reference)

<details>
<summary>Click to expand</summary>

- [x] `s` command PRG save address stale ZP ref — repl.s wrote to
  hardcoded `$FB/$FC` instead of `_io_tmp`; stale from Phase 12.
- [x] Editor INS key ignored — inserts space via `gb_insert` +
  `gb_cursor_left`; refused at 39-col cap.
- [x] 13 CMOS mnemonic gate bugs — fixed in `2939a94`.
- [x] expr.s test harness: 12 xfails — resolved, 146 tests pass.
- [x] asm_cpu 3-valued semantics — fixed.
- [x] `j` command: reset colors after user code returns.
- [x] `print_load_split_warning` leading-comma bug.
- [x] `ed_scroll_down` memmove broken — rewrote as row-by-row copies.
- [x] Revise TDD framework — Principle 6 + Anti-patterns section.
- [x] 8 xfailed `TestStepIntoJSR_ROMFallback` — ported to
  `test_step_rom.py` using C64Emu.  0 xfails remain.
- [x] Clean up `dev/test.d64`.
- [x] Review all user-facing strings — terse convention established.
- [x] Line-break warnings on file load — one per split.
- [x] `theme_border`/`theme_bg`/`theme_fg` in RODATA — moved to BSS.
- [ ] `.` and `m` show CSE ZP — `m` fixed in `ac1a31f`, `.` still open (see above).
- [x] Stack-snapshot revisit under KERNAL — resolved.
- [x] BASIC SYS residue on hardware stack — SP reset at startup.
- [x] `dbg_enter` ZP save buffer sizing — fixed.
- [x] cc65 -O ternary miscompilation — eliminated (pure asm).
- [x] cc65 -O zero-extension bug — eliminated (pure asm).
- [x] User CHROUT overwrites prompt row — newline before run_user.
- [x] asm_src test stub blank line truncation — $FF EOF sentinel.
- [x] `dev/test.d64` T-COUNT: renamed from COUNTDOWN, loads and
  displays correctly after page-alignment fix.
- [x] NMI trampoline corrupted $01 — trampoline no longer modifies
  $01; handler chain runs in main RAM.  Added IRQ/BRK trampoline
  at $FF04 (defensive).  Phase 14.
- [x] IRQ/BRK trampoline verified safe — IRQs blocked by SEI,
  user BRK path returns through `run_user` which restores $01.
- [x] `t1` step over taken branches — `compute_rel_target` clobbered
  N flag with `ldy #0` before `bpl`.  Negative offsets treated as
  positive.  Fixed with BIT-abs skip trick.  Phase 14.

</details>

## Phase 9 — Test harness rewrite

`C64Emu` emulator class + production PRG replaces per-test build
systems, ASM stubs, and test-specific linker configs.

### Done

- [x] `tests/c64emu.py` — C64Emu class: py65 + KERNAL ROM overlay,
  $01 bank switching, screen RAM, jsr(), sym(), keyboard injection.
- [x] `tests/integration/test_c64emu.py` — 34 smoke tests.
- [x] `tests/integration/test_editor.py` — 10 ASM-level editor tests
  (gap buffer, ed_new, dirty flag, ed_read_line).
- [x] `tests/integration/test_screen.py` — 15 ASM-level screen tests
  (scroll_up, newline, restore_colors, reset_screen, cursor toggle).
- [x] `tests/integration/test_step_rom.py` — 8 debugger step-into ROM tests
  (replaced xfailed tests).
- [x] Makefile: `-Ln` label file, `check-roms` gate, `cse_prg` fixture.
- [x] KERNAL ROM setup: screen line link table ($D9-$F1), HIBASE,
  page-3 vectors via RESTOR.
- [x] `c64emu.py` load/run segment relocation: auto-copies segments
  with load ≠ run addresses (mirrors loader.s).

### Open

- [x] ~~Review l/s command tests~~ (fixed: test_repl.py now resolves
  `save_addr`/`save_size`/`load_result` via RODATA `sym_refs` table
  slots 11–13, replacing fragile hardcoded BSS offsets)
- [ ] Use debug builds and `od65 --dump-all foo.o` for extracting
  all symbols (exported and unexported) from object files for
  testing.  Use stripped production builds only for superficial
  end-to-end integration tests.  This eliminates fragile BSS
  offset computation and map-file parsing in test harnesses.
- [ ] Migrate remaining test files to C64Emu + full PRG.  Each old
  test file (test_repl, test_cse_io, test_expr, test_symtab,
  test_debugger, test_addr_mode, test_mn_classify, test_asm_line,
  test_dasm, test_asm_src) has its own build system, map parser,
  and run loop.  Migration removes ~1200 lines of harness code,
  9 ASM stub files, and 3 linker configs.
- [ ] Editor scroll/render screen-RAM tests.  `ed_scroll_down` and
  `ed_render_line` are `.proc`-scoped (not in .lbl); test path is
  through `ed_handle_key` with cursor keys, which needs full editor
  state.  Deferred until `enter_editor` can be called via C64Emu.
- [ ] Retire `test_editor.py` mirror tests once ASM-level coverage
  is complete.
- [ ] README cross-reference tests: parse command tables in
  `README.md`, verify each command key has a handler symbol in the
  `.lbl` file.  See DDD Maintenance item 8.

### Test restructure Tranche 4 — `test_repl.py` → C64Emu

- [ ] **Migrate `tests/integration/test_repl.py` from the bare-MPU +
  `dev/repl_test_stub.s` harness to full C64Emu + production PRG.**
  Blocked on the C64Emu virtual-IEC-disk extension (see the
  C64Emu extension roadmap below) because `TestSaveCommand` and
  `TestLoadCommand` (~30 tests, ~300 lines) currently observe
  behaviour via the stub's `_save_addr` / `_save_size` / `_save_name` /
  `_load_result` / `_load_name` / `_op_witness` BSS instrumentation
  that records what the commands *would have done*.  Without a
  virtual disk, C64Emu tests for these commands have no way to
  assert success.

  Non-disk classes (17 of 20, ~50 tests covering prompt / read_line /
  address / memory / disasm / calculator / register / block / repeat /
  semicolon / unknown / cpu / dothex) migrate cleanly to C64Emu —
  they already use real production code paths.  Splitting into
  two files to migrate the non-disk half immediately is possible
  but creates a maintenance burden until the disk half can follow.

  Prerequisite: C64Emu virtual IEC disk (below).
  Payoff: drops `dev/repl_test_stub.s` (~300 lines), `dev/repl_test.cfg`,
  the bare-MPU `_build()` / `_parse_map()` / `ReplSymbols` scaffolding
  in test_repl.py, and the `sym_refs` RODATA table workaround.
  Net: -400–500 LOC of test harness, zero new test logic.

### C64Emu extension roadmap

Planned emulator feature additions (scoped during test-restructure
discussion).  Each block is independent; do in any order.

- [x] ~~**Full `$01` banking**~~ — landed as C64Emu extension 1
  (commit `77ef7a4`).  Three-bit banking (LORAM/HIRAM/CHAREN) with
  BASIC + CHARGEN ROM overlays.  Default `$01` now `$36` (CSE
  runtime config) instead of `$37`.
- [x] ~~**DDR-aware `$00`/`$01` model**~~ — landed with extension 1.
  `$01` read returns `(latched & DDR) | (external & ~DDR)`.
- [x] ~~**Scheduled interrupts**~~ — landed as extension 2 (commit
  `a755c9d`).  `schedule_irq` / `schedule_nmi` / `cancel_pending_interrupts`
  + cycle-accurate pending queue honouring I flag + NMI edge.
- [x] ~~**CIA1/CIA2 register shadows + keyboard matrix**~~ — landed
  as extension 3 (commit `30d9dbf`).  `$DC00/$DC01` 8×8 matrix,
  `press_key` / `release_key` / `press_stop` / `press_restore`,
  CIA2 `$DD0D` NMI latch.
- [x] ~~**Jiffy clock tick**~~ — landed as extension 4 (commit
  `d426040`).  `enable_jiffy_clock` / `disable_jiffy_clock` on top
  of the scheduled-IRQ infra; default 16421 cycles matches KERNAL.

- [ ] **Virtual IEC disk (D64-backed)** — intercept KERNAL IEC entry
  points (`$FFC0` OPEN, `$FFD5` LOAD, `$FFD8` SAVE, `$FFCF` CHRIN,
  `$FFD2` CHROUT, etc.) with a Python callback backed by a virtual
  D64 image.  Unlocks Tranche 4 (test_repl migration) + hazard tests
  (overwrite, file-not-found, device-not-present).  Moderate-to-high
  effort; timing-accuracy concerns — flagged as out-of-scope at
  extension-planning time.

- [ ] **VIC raster counter auto-increment** — `$D012` derived from
  cycle counter (~63 cycles/line).  Unlocks raster-synced user
  programs.  Not needed for CSE itself (no raster tricks); low
  priority.  ~30 LOC.

- [ ] **REU / cartridge emulation** — out of scope until R5 (CRT
  build target).  Placeholder for the roadmap.

## Planned

Defined scope, needs work.

### Corpus

- [x] ~~**DDD follow-up for the 2026-04-22 Design Priorities expansion.**~~
  Closed 2026-04-25 by Phase 23 DDD Streamlining maintenance round.
  Six absorption gaps from `background.md` folded into corpus voice in
  `doc/project.md`: §4 keyboard rule gained its "shared surface" *why*;
  §6 Transparency gained an exclusion paragraph (BASIC-like wrappers,
  scripting layers, pseudo-register/pseudo-address illusions); §7 Two
  audiences gained the "fits in the user's head" justification and the
  no-unlearning-step feature filter; § *What Is CSE?* gained a pointer
  to background.md for motivating context.  Principle-3 hygiene:
  `**Dependants:**` annotation added under § Design Priorities;
  background.md indexed in `doc/README.md` § *User-facing behaviour* as
  a derived document.  No corpus contradictions found.  TDD delta
  confirmed nil (priorities are design constraints, no behavioural
  contract).  No copies of the priorities list exist elsewhere
  (verified by grep over `doc/`); architecture.md intro stays focused
  on kernel framing, no drift introduced.

- [x] ~~**L0 data modules unowned** (DDD Maintenance 2026-04-25, item 2).~~
  Closed 2026-04-25.  Each generated table is now claimed by the
  module that consumes it: `mn7_tables.s`, `mn6_tables.s`,
  `mn_config.s` → `mn_classify.md`; `mn_asm_tables.s`, `mn_modes.s`,
  `oplen_tbl.s` → `opcode_lookup.md`; `dasm_tables.s`,
  `dasm_mne_idx.s` → `dasm.md`; `loader.s` → new `loader.md`;
  `mn_vars.s` was already in `mn_classify.md`.  `architecture.md`'s
  L1 module table and Generated-files table now link every L0 file
  to its owning doc.  `mn_config.s` flagged in its claim row as a
  vestigial 256-byte table (predecessor of `mn7_tables.s`); follow-up
  TODO under § Architecture to retire the file from the build.

- [x] ~~**dev/ tooling unowned** (DDD Maintenance 2026-04-25, item 2).~~
  Closed 2026-04-25.  `build_system.md` § Owned files extended to
  claim every previously-unowned `dev/` file: `scs_analysis.py`,
  `scs_pack.py`, `gen_asm_tests.py`, `strings.txt`, `test.cfg`, the
  six test-bundle stubs (`asm_core_test_stub.s`, `asm_src_test_stub.s`,
  `breakpoints_test_stub.s`, `cse_io_test_stub.s`, `dasm_test_stub.s`,
  `repl_test_stub.s`, `symtab_test_stub.s`), the two test-bundle
  configs (`asm_src_test.cfg`, `repl_test.cfg`), the `dev/search/`
  exploration scripts (claimed wholesale as historical hash-search
  provenance), and the two committed disk images (`src.d64`,
  `test.d64`).

- [x] ~~**Tests unclaimed** (DDD Maintenance 2026-04-25, item 2).~~
  Closed 2026-04-25.  Test files added to module-doc Owned files
  blocks: `test_asm_err.py` → `asm_err.md`; `test_gap_buffer.py` →
  `gap_buffer.md` (existing transitive-via-editor row preserved);
  `test_log.py` → `log.md`; `test_repl.py` and `test_repl_disk.py`
  → `repl.md`; `test_screen.py` → `screen.md`.  The five C64Emu
  harness tests (`test_c64emu*.py`) added to `build_system.md`
  alongside `c64emu.py`.  `tests/retired/` was initially claimed by
  `testing.md § Mirror tests` as a worked-example archive, then
  retired entirely (its anti-pattern descriptions inlined into the
  same section); the tree itself was removed when it was found to
  shadow `tests/conftest.py` and break `pytest tests/`.

- [x] ~~**`main.s` lacks dedicated unit tests** (DDD Maintenance
  2026-04-25, item 7).~~  Closed 2026-04-25.  `doc/modules/main.md`
  now declares Pattern A coverage explicitly: dispatcher
  classification (`cse_brk_handler`, `cse_nmi_handler`) covered at
  Tier I via `test_kernel_transition.py` + `test_step_rom.py`;
  vector installation and cold-init covered transitively by every
  integration test that boots the production PRG.  Unit-tier
  isolation rejected as not productive — the synthesised state
  needed to drive the dispatcher is essentially the integration
  setup.

- [x] ~~**`disk.s` coverage gap undocumented** (DDD Maintenance
  2026-04-25, item 7).~~  Closed 2026-04-25.  `doc/modules/disk.md`
  now declares Pattern C coverage explicitly: KERNAL IEC entry
  points are not modelled by py65 + C64Emu (no virtual IEC bus, no
  D64 backend), so coverage is manual VICE walks of `l` / `s` / `$`
  paths.  Cross-references the queued
  § C64Emu extension roadmap → Virtual IEC disk item.

- [x] ~~**`loader.s` triple gap** (DDD Maintenance 2026-04-25, items
  2, 6, 7).~~  Closed 2026-04-25 by the new `doc/modules/loader.md`
  (interface + design + caveats + Pattern A coverage statement) and
  the architecture.md ownership-link update.  The legacy duplicate
  entry under § Architecture (line ~1285, "Missing module doc:
  `src/loader.s`") is now obsolete and removed.

### REPL

- [x] ~~`.` without args: behave like `d` (disassemble one instruction).~~
  (already the behaviour: `cmd_dot` falls through to `emit_dot`
  when no hex bytes and no mnemonic were parsed.)
- [ ] `/` command: search for byte pattern in memory.
- [ ] `f` command: fill memory range with byte.
- [ ] `>` command: transfer/copy memory block.
- [ ] `=` command: define/query symbols from REPL.
- [x] `r` command: uppercase set flags (`Nv-bDizc` vs `nv-bdizc`). (Phase 16)
- [ ] `?` command: for values < 256, show PETSCII and screen code
  character interpretation alongside the hex/decimal/binary output.
- [ ] `m` address argument: accept expression (`m screen+40`).
  Currently plain 4-digit hex only.
- [ ] New `S` command for scratching files. Requires confirmation.
- [x] ~~VIC sanity reset on kernel/userland boundary.~~ (done:
  `vic_reset` in screen.s forces $D011=$1B, $D016=$C8, $D018=$15,
  $D015=0, $D01A=0, $D019=$0F.  Called from `hygiene_after_userland`
  on every break/resume cycle.  Future work: call from
  `cse_refresh` too so ESC/CLR recovers from a kernel-resident
  program that glitched VIC.)
- [ ] SID silence: stop stuck notes when user code leaves SID running.
  Two complementary mechanisms:
  1. **REPL command** (probably one of the existing mnemonic-free
     letters, or a dedicated key chord) — zeroes all SID registers
     (`$D400-$D418`).  Useful when the user's code has SID voices
     playing and leaves them running after a break.
  2. **Contractually at the kernel/userland boundary** — on every
     transition from user code back into the CSE kernel (BRK,
     breakpoint, NMI-userland-break, brk_stub return), zero the
     SID's gate bits (`$D404`/`$D40B`/`$D412` bit 0) to release
     voices.  Keeps SID register values otherwise intact so the
     user can see what was set.  ~6 bytes on the BRK handler
     path.  Pairs with dropping `io_blip` to give the contract
     clause "SID is yours except voice gates at debug entry."
  The two together give the user a clean audio environment on
  break, and a manual way to silence mid-session if a user
  command (like `j` into a program) leaves SID noisy.
- [ ] Disk command channel: unified under `$` (`$ s:file`, `$9`, etc.).
- [ ] Floppy status consistency: `$` prints status inline (always
  shows), `l`/`s` use `floppy_status` via `disk_done`.  Verify
  both paths produce identical output on stock KERNAL.
- [ ] `l` command PRG mode: report actual load address in stats
  line.  Currently shows `cur_addr` which may be wrong when the
  PRG loads at its own header address (addr=0 path).
- [ ] PRG range display: unify format to `AAAA-EEEE  NNNb` (range
  first, size second).  Currently `l` PRG stats prints `NNNb AAAA-EEEE`
  (size first).  Shared `print_prg_range` should use the same
  order as the assembler `; org` lines and the splash screen.
- [ ] SHIFT+RETURN in REPL: clear the repeat buffer (so the next
  RETURN starts empty instead of re-executing the last command) and
  open a fresh prompt line.  Useful for breaking out of a repeated
  `t`/`RETURN` stepping rhythm without having to type a cancel.
- [ ] `e` command: open editor at decimal line number (`e 42`).
  Centers the target line on screen as much as possible.  Ties
  into assembler error line numbers — assemble, see error at
  line 42, type `e 42` to jump straight there.
- [ ] `l`/`s` log line: always show the effective CBM DOS type
  (SEQ vs PRG) in the `; load/save "name"...` output.  Under the
  project-name refactor the on-disk name is derived (`stem` vs
  `stem.`) and the user should still see which classification path
  was taken when derivation was automatic.
- [x] ~~Refactor internal default filename to a project name~~
  (Phase 17.  `cur_filename` → `cur_project_name`, stem only
  (no `,s`/`,p` suffix, no trailing dot).  Derivation: SEQ = stem,
  PRG = stem + `.`.  Shared argument parsing between `l` and `s`
  via `parse_ls_args` — positional, expression parser, 0-2 numeric
  args.  Verbatim names (`,s`/`,p` suffix at tail) bypass
  derivation.  See `doc/modules/repl.md` § Project-name and
  filename semantics.)

### Debugger

- [ ] Show wall-clock execution time on the `j`/`g` clean-exit
  panel.  Sample KERNAL jiffy clock ($A0/$A1/$A2, the TOD-style
  3-byte counter incremented by the IRQ at 60 Hz on NTSC,
  50 Hz on PAL) at userland entry (in `_rtu_body` just before
  the RTI) and again at handler entry (`cse_brk_handler`),
  store the delta somewhere the panel can read (e.g. a 3-byte
  `run_jiffies` slot).  Format on the DBG_RTS panel:
    < 1 s        → `Nms` (jiffy * 1000 / clock_hz, 0–999)
    1 s ..< 1 m  → `Ns` or `N.NNNs`
    1 m ..< 1 h  → `NmNs`
    >= 1 h       → `NhNmNs`
  Render as a tail field on the info or regs row, e.g.
  `; rts at $0800  3.4s` or `r pc:0800 ... s:ff  217ms`.
  Notes:
    - Jiffy clock wraps after ~4.7 days (24-bit counter at
      60 Hz) — fine for typical debug sessions; longer runs
      get `>4d` clamp.
    - PAL/NTSC detection: the assembled binary already knows
      via build flag (CMOS / 6502 / 6510 builds may differ);
      otherwise sample $02A6 at startup (KERNAL sets 0=NTSC,
      1=PAL).
    - Jiffy clock pauses while the kernel runs (IRQ disabled
      during handler), so the delta excludes our overhead —
      only user code time is reported.  Good.
    - `t`/`o` step-result panels probably DON'T need this
      (single steps are sub-microsecond), but a `t100`-class
      batch could surface aggregate time.

- [x] ~~BRK tracer rewrite: use BRK's signature byte ($00 XX)~~
  Scratched: BRK must remain 1 byte only.  The 6502 BRK
  instruction is documented as 1 byte; the byte at PC+1 is a
  user-controlled signature for their own purposes (e.g. the
  ".db" pattern in user BRK debug breakpoints — see "user BRK
  workflow" below).  Encoding metadata into that byte would
  collide with user code.  step BRK / user BP discrimination
  stays via the dbg_bp_find address search.

- [x] ~~Single-RETURN single-step workflow~~  (done: combined
  effect of ef667ce — bare `t` defaults to 1 step (not block_size)
  — and the cold-preview / warm-step / step-through-rts work
  in 9c6abaf..d591a13.  `t / RETURN / RETURN / ...` now does
  rapid single-stepping with full panel after each step.)
- [x] ~~Extend userland ZP backup to $00–$7F~~  (done: Phase 17.
  ZP_SAVE_LO/HI widened to $00/$7F (128 B), covering the full
  user-accessible half.  `m`/`.` now read a uniform user-ZP view —
  the redirect's range check in repl.s simplified from the $02/$5A
  double bounds + subtract to a single `cmp #$80`.  run_user's
  external `lda $01/pha` pair dropped (banking now round-trips via
  zp_save_buf since $01 is inside the saved range).  +80 B BSS,
  −7 B CODE in repl.s, −4 B CODE from the removed $01 dance.)

### Help

- [ ] In-app help system.  Help text lives in KDATA (under
  KERNAL ROM, $F100 area), not RODATA — must not bloat the
  relocatable runtime.  Minimal CODE overhead: a small dispatcher
  that pages through KDATA strings.  Candidates: one-screen
  REPL command cheat sheet, editor key summary, assembler
  syntax quick ref.  Paging output (see below) would pair
  naturally.

### Output

- [ ] Paging for commands that produce more than ~23 lines of
  output (`d`, `m`, `$`, assembler messages).  Pause with
  "more" prompt, any key continues, RUN/STOP aborts.  The
  `log_line` output wrappers already funnel all command output
  through a single path — hooking a line counter there should
  be straightforward.

### Assembler

- [x] `.bas` directive: emit a BASIC SYS stub.  (Phase 12, done)
  Single BASIC line: `.bas` → `0 SYS NNNNN`.
  `.bas "TEXT"` → `0 SYS NNNNN:REM TEXT`.
  Always 5 decimal digits (260 B).  2799 tests.

- [ ] `.brk [n]` directive: emit a 2-byte BRK instruction (BRK
  opcode + signature byte).  Optional `n` is the signature byte
  (default 0).  Replaces the verbose `brk; .db $XX` pattern that
  the lazy-debug user-BRK workflow currently requires (see
  debugger.md § User BRK workflow).  Without `.brk`, the user
  must manually pair `brk` with `.db $XX`; forgetting the .db
  loses the next code byte to CSE's STEP_OVER / continue +2 skip.
  `.brk` makes the convention explicit and forgive-by-default.
  Use cases: `.brk` (default sig byte 0), `.brk $42` (custom),
  `.brk MARKER` (expression).  Single line in source maps to
  the canonical 2-byte BRK that matches CPU's RTI semantics.
- [ ] Assembler error display: show source line number + context.
- [ ] **Error-category tables are part of the contract.**  asm_err,
  expr, and repl each have their own error code → message mapping
  (`asm_expr_err` flag, expr's 0..6 return codes, REPL's string
  table).  Today those tables are partly documented and partly
  implicit.  Make each module's error category list a first-class
  part of its doc (one table per module), and add unit tests that
  assert every documented code maps to the expected message.
  Companion fix: CPU-mode-gate rejection in `asm_line.s` currently
  flows through the generic `asm_error` path and is displayed as
  "syntax" — strictly accurate but misleading.  Introduce a
  distinct "cpu" error category (new `asm_err` entry point, new
  string, REPL dispatch update) as part of the same cleanup so
  PHY-on-6502 displays as `;?cpu` rather than `;?syntax`.
  Uncovered by the asm_cpu gate Escape Analysis (2026-04-20).
- [x] Per-segment assembly summary — bug fixes + streaming design.
  Fixed bugs (pass-0 output, stale asm_pc, asm_org clobber,
  expr_val clobber, filename `,s`→`,p`).  Streaming segment lines
  during pass 1, `; ok` + save command after.  +70 B, 6 tests.
- [ ] Assembly `; ok` line: show symbol count (`; ok  NNN syms`).
  Needs `sym_count` (2B BSS) in symtab.s, incremented by `sym_define`,
  but only if the symbol didn't exist before.

### Editor

- [ ] Handle files > gap buffer capacity (show error, don't crash).
- [ ] Gap buffer floor above directory load area: if `list_directory`
  stays LOAD-based (loads to $0801, max ~5.1 KB), set gap buffer
  bottom to $0801+$1400=$1C01 so `$` can never clobber source.
  Currently BUF_FLOOR is computed dynamically by `compute_layout.py`
  — would need a minimum floor of $1C01.
- [ ] Gap buffer compaction: `buf_base` only grows down (via
  `gb_ensure_room`), never shrinks.  `ed_init`/`n` should reset
  `buf_base` to BUF_END.  Line deletion could trigger compaction
  but consider the trade-off (O(n) vs immediate undo).
- [ ] Page up/down with shift+cursor or F-keys.
- [ ] Search (ctrl+f equivalent via F-key).
- [ ] Goto line number (see `e` command)
- [ ] `$A0` and `$09` should be both be interpreted as TAB, both from
  keyboard input, and when handled in source code.

### Size optimization

**Post-Phase-18 optimization sweep.**  Exhaustive three-agent review
after Phase 18 landed.  Ongoing — see commits `7351292` (A),
`fc52046` (B), `8e60b62` (SEI/CLI), `778a1f4` (disk) for progress.
Net so far: ~−80 B across all builds.

*Done:*

- [x] ~~Phase A: repl.s stale TODO comment removed; loader.s
  `copy_pages` + `zero_pages` helpers; debugger.s `dbg_init` /
  `clear_bp_x` unified sweep; repl.s `peek_brk_opcode` dedup.~~
  (`7351292`)
- [x] ~~Phase B: repl.s `pre_userland_run` helper; dasm.s
  `_compute_branch_target` + `_emit_target` helpers.~~  (`fc52046`)
- [x] ~~SEI/CLI guards dropped from mem.s `kernal_bank_in/out` and
  asm_src.s `_bank_in_tmp` / `_bank_out_tmp` — the Phase 18 IRQ
  early-entry + `bank_out_stub` handles IRQ-during-bank-out
  transparently, so the I-flag management is redundant.~~
  (`8e60b62`)
- [x] ~~disk.s `_disk_open_buf` helper for the three SEQ/PRG OPEN
  sites (disk_load_seq, disk_save_seq, disk_save_prg).~~  (`778a1f4`)

*Evaluated and declined:*

- ~~Phase A: cse_exit_to_basic `and #$FD` removal — **false
  positive**.  That bank-out is required so the subsequent COLD_ZP
  reads resolve to the saved RAM copy at $F8DA (under KERNAL ROM),
  not to the ROM bytes.~~
- ~~Phase A: step_next_pc CMOS gating — **already done**.~~
- ~~Phase B: centralize `_bank_in_tmp` / `_bank_out_tmp` into mem.s
  — **false positive**.  They bypass mem.s's flag-gated helpers on
  purpose (asm_src runs inside a batch with `kernal_out = 1`).~~
- ~~Phase B: skipws_ep / skipws_as consolidation — **no net
  saving**.  Wrapper/macro approaches match or exceed current
  size.~~
- ~~Phase B: patch_all / unpatch_all shared skeleton — **load-
  bearing by design**.  The forward/reverse order is a correctness
  contract for overlapping user-bp / step-bp slots at the same
  address: forward-patch saves the real byte first (later slots
  save $00); reverse-unpatch writes the $00s first and the real
  byte last, leaving the user's RAM correct.  Uniform direction
  would corrupt overlapping addresses.~~
- ~~Phase D: editor.s ed_handle_key table dispatch — **not a size
  win**.  ~10-key cmp/bne chain is ~40 B; table + scan loop +
  indirect-jump glue would be ~56 B.  Could be a clarity win paired
  with handler-tail consolidation, but that's a separate refactor.~~

*Open — Phase C (stack / ZP wins, ~20 B code + ~6 B kernel stack):*

- [ ] **Phase C — promote hot state out of BSS into ZP, and out of
  the hardware stack into ZP scratch.**  Three sub-items:
  1. [screen.s scroll_up] Replace the `pha/pla` pairs for `n` /
     `src_row` / `dst_row` with ZP temps.  ~37 B ZP is free at
     $5B–$7F per zp.s.  Saves ~6 stack bytes per scroll + cycles
     per row.
  2. [asm_src.s .const handling] Similar `pha/pla` dance around
     name-folding.  Move to ZP scratch.  ~4 stack bytes, ~15 B code.
  3. Promote hot BSS flags to ZP: `stop_cooldown`, `dbg_reason`,
     `run_user_pending` — each read at multiple hot sites.  Each
     ZP promotion saves ~1 B code per access and a cycle per read.
     `in_userland` is debatable (only read in interrupt dispatch).
  Total estimate: ~20 B code, ~6 B kernel stack headroom, plus
  hot-path cycle wins in main_loop's `@wait` and scroll_up's row
  loop.

*Open — other small wins flagged during the sweep:*

- [ ] [main.s setup_interrupts] Four vector-write pairs could use a
  small helper or indexed loop.  ~10 B.
- [ ] [debugger.s _rtu_body sentinel push] Branch pattern could be
  slightly tighter.  ~2 B.

**CSE exit cleanup via KERNAL TIMB ($FE66).**  Instead of `cse_exit_to_basic`
hand-rolling the ZP restore + MEM_CONFIG reset + `jsr KERNAL_CINT +
jmp ($A002)` sequence, do only what's ours to undo (e.g. restore the
editor-specific ZP state we disturbed), then `jmp $FE66` (KERNAL's
TIMB — "warm-restart" entry used by BASIC's STOP+RESTORE path).
$FE66 reinitialises I/O, resets vectors, redraws screen, and drops
into BASIC READY.  Eliminates our manual teardown (~30 B code plus
the COLD_ZP KBSS area we reserve just for the restore).  Verify that
the KERNAL routine's prerequisites (banking, stack shape) are met
from our exit context.

- [ ] Table-drive `cmd_info`: replace procedural line-by-line
  memory map display with a data table + loop (~50-80 B saving).
- [ ] PRG/SEQ save dedup: `cmd_write` and `cmd_load` have shared
  patterns in filename parsing and stats display (~30-50 B).
- [ ] `exec_line` handler code sharing: inline `@h_*` handlers
  share common tail code (log_close, nl_clear, error paths).
  Factor into shared exit points.
- [ ] Disassembler `format_operand`: investigate table-driven
  formatting (packed format byte per mode, like Woz's Apple II
  disassembler) instead of procedural per-mode branches.
  Currently 220 B, could save ~80-100 B.
- [ ] Disassembler opcode table: investigate replacing the
  `aaabbbcc` bit-slice decoder with a compact 256-byte opcode
  lookup table.  Trades CODE (~350 B decode_cc00_mem alone)
  for RODATA (256 B).  Changes the architecture fundamentally.

### Architecture

- [x] ~~**Multi-CPU integration-test parity.**~~  Closed
  2026-04-27.  Implemented as a coarse smoke check
  rather than a full per-CPU re-run of detailed contract
  tests, per the principle's actual intent (proving the
  boot path *executes* on every variant, not duplicating
  per-target contract assertions).  Detailed contract
  tests remain on the canonical CMOS-only `emu` fixture.
  Landed:
  - `cse_prg_per_cpu` fixture in
    [tests/conftest.py](../tests/conftest.py)
    (params=`["6510", "6502", "cmos"]`).
  - `emu_per_cpu` fixture +
    `TestBootsCleanly::test_cold_init_completes` in
    [tests/integration/test_kernel_transition.py](
    ../tests/integration/test_kernel_transition.py) —
    pytest expands to 3 invocations.
  - [doc/testing.md § Principle 18](
    testing.md#principles) clarified to spell out the
    coarse-vs-detailed division of labour.

  All three variants currently pass.  Confirms the
  Phase-24 prediction that the heap-corruption root
  cause was CPU-agnostic; F1 + F2 fixed all three even
  though only CMOS was directly tested at fix time.

- [ ] **Triage the 17 cold-init-fragile tests in
  test_kernel_transition.py** — **deferred until the cold-init
  bug lands.**  This entry was originally framed as a per-test
  triage (rewrite on `_minimal_init`, retire with Pattern A
  skip, or retain) under the assumption that the fragility was
  a harness limitation around the BASIC ROM shadow.  The
  2026-04-25 RCA proved otherwise — the fragility is the
  CMOS cold-init recovery path interacting with the BASIC
  shadow, not a harness artifact (see [§ Bugs](#bugs)).
  Once the cold-init bug is fixed, the 17 tests likely pass
  cleanly without per-test triage; if any still fail post-fix,
  they may genuinely need the rewrite/skip/retain decision.
  Defer to that point.

- [x] ~~**Retire `src/mn_config.s`**~~ (closed 2026-04-25).
  Removed from `Makefile` (ASM_SRCS + TABLE_OUTS), from
  `dev/mnemonic_tables.py` (deleted dead `write_config_table`
  function and its caller stub; tidied generator-doc comments
  that referenced it), and from `dev/size_report.py`.  Source
  file deleted.  Doc updates: `mn_classify.md` Owned files row
  removed, `architecture.md` Generated-files + L0 leaves listings
  pruned, `testing.md` Principle 12 + per-module tier table
  pruned, `build_system.md` generator outputs row corrected
  (also gained `oplen_tbl.s` which was missing).  Build verified:
  `make tables` clean, `make CPU=6510` produces a 21031-byte
  PRG (was 21287, exactly **−256 B saved per build variant**;
  3051 tests pass, 18 expected skips).

- [ ] Loader: reverse-direction copy.  `loader.s` currently does a
  forward memcpy (low → high) for CODE+RODATA and KDATA.  Forward
  copy is unsafe when `dst > src` and the ranges overlap, which is
  why `compute_layout.py` enforces `payload_end < runtime_start` and
  fails the build if the binary outgrows the gap.  A backward copy
  (top → bottom, DEY/DEX loops) is safe in exactly the direction we
  copy, so the overlap constraint disappears and CODE+RODATA can
  grow all the way up to `runtime_start` without tripping the build
  check.  Changes: flip both page+remainder loops in loader.s
  (CODE+RODATA copy, KDATA copy — BSS zeroing is direction-
  independent); drop the payload-overlap sanity check in
  `compute_layout.py`; update `doc/memory_design.md` and the
  loader's own comments.  Opens room for modestly larger binaries
  without any layout-math changes elsewhere.

- [x] Relocating startup: done (Roadmap R2, Session 10).

- [x] **PETSCII pipeline unification + expr_eval in line assembler.**
  Phase-level work (~2-3 sessions).  Estimated savings: ~474 B
  CODE + 80 B BSS.  Eliminates the VICII/PETSCII encoding split,
  the `_insn_buf` round-trip, and the duplicate hex parser.  Gives
  the `.` command full expression support (labels, arithmetic) for
  free.  Four steps:

  **Step 1 — Hash encoding: resolved, no work needed.** (Phase 12)
  AND #$1F normalization in `_asm_rd_upper` maps PETSCII
  uppercase ($41–$5A), PETSCII lowercase ($61–$7A), and VICII
  screen codes ($01–$1A) identically to 1–26.  All hash tables,
  fingerprint tables, and T arrays are encoding-agnostic.

  **Step 2 — Switch assembler pipeline to PETSCII + rename.** (Phase 12, done)
  Merged asm_bridge.s into asm_line.s (KERNAL banking, error
  recovery, SP save/restore).  Deleted PETSCII→VICII conversion
  loop.  au_mode.s operates on PETSCII: SC_* constants updated
  (A=$41, X=$58, Y=$59), hex ranges ($41–$46 for A–F).
  Renamed: `al_` → `asm_`, `au_` → `asm_`/`mode_` across all
  source, test, stub, and doc files.  2788 tests pass.

  **Step 3 — Replace mode_parse hex parser with expr_eval.** (Phase 12, done)
  Removed `_au_rd_nib`, `_au_rd_byte`, `_au_is_hex` (-73 B).
  mode_parse calls `_au_read_val` → `expr_eval_nb` (no-banking
  variant).  Operands now accept `$hex`, `%binary`, decimal,
  labels, `*`, and arithmetic.  Fixed `hex_nybble` in expr.s
  to accept uppercase A-F (`ora #$20` case fold; numeric constants
  for portability across ca65 `-t c64` and plain `--cpu 6502`).
  Test framework: asm_core bundle replaces per-module test binaries.
  Pass flag deferred to Step 4.  2797 tests pass.

  **Step 4 — Unify source assembler with line assembler.** (Phase 12, done)
  asm_src.s passes expanded source text directly to asm_line instead
  of pre-evaluating expressions and reconstructing hex.  Removed:
  hex_tab (16 B RODATA), mode detection (#/( flags), expression
  evaluation, hex formatting, suffix copying (~197 B total).
  Local label expansion (.name → scope.name) stays in asm_src.
  Forward-reference handling: pass flag (asm_pass) in _au_read_val
  substitutes asm_pc+2 on pass 0 when symbols are undefined.
  DEFAULT_CPU moved from asm_line.s to main.s init.
  ACC detection in mode_parse hardened: bare 'A' only if followed
  by end/whitespace (not identifier chars like label names).
  2797 tests pass.
- [x] ~~BSS optimization: overlap with `ws_buf`~~ (moot: `ws_buf`
  removed in smart indent rewrite, Phase 15)
- [ ] BSS optimization: collapse `disk_seq_bytes`/`disk_seq_lines`
  with `ed_save_bytes`/`ed_save_lines` (saves 4 B).
- [ ] BSS optimization: overlap `rp_next_lo`/`rp_next_hi` with
  `rp_hexbuf` + `@new_col` (saves 3-4 B).
- [ ] Test framework: migrate dasm, expr, repl test binaries to bundle
  pattern or C64Emu integration tests.  Eliminates per-module stubs.
  See testing.md § Test bundle architecture.
- [x] Central `zp.s` owning the entire zero-page layout.  (Phase 12, done)
  All 85 ZP bytes defined in `src/zp.s` with `.exportzp`.  13 modules
  migrated from local `.segment "ZEROPAGE"` to `.importzp`.  `asm_vars.s`
  deleted (role absorbed by zp.s).  All test stubs and configs updated
  to link zp.s.  Pure refactor: 0 bytes size change, 2797 tests pass.
- [x] ~~DDD template drift~~ (fixed: moved `### Memory` before
  `**Depends on:**` in 11 module docs; Phase 15 audit remediation)
- [x] ~~Missing module doc: `src/mem.s`~~ (fixed: `doc/modules/mem.md`
  created; Phase 15 audit remediation)
- [x] ~~Missing module doc: `src/loader.s` has no `doc/modules/*.md`.~~
  (fixed 2026-04-25: `doc/modules/loader.md` created during Phase 23
  DDD Maintenance round.)
- [x] ~~debugger.md: all symbol names use `_` prefix~~ (fixed:
  stripped `_` prefix from all symbol names throughout the document
  to match actual exports; Phase 17 DDD Maintenance)
- [x] ~~README: missing `.bas` directive~~ (fixed: Phase 15 audit)
- [x] ~~README: `a` command description says "advances past assembled
  code"~~ (fixed: README now reads "Assemble source from editor
  at current address")
- [x] ~~README: "gap buffer grows down from $D000"~~ (fixed: Phase 15)
- [x] ~~editor.md + memory_design.md: `BUF_END` / gap buffer described
  as `$D000`~~ (fixed: updated to `__CODE_RUN__` in editor.md ×3
  and memory_design.md Design Principle 5; Phase 17 DDD Maintenance)
- [ ] Export `LOG_INFO`, `LOG_WARN`, `LOG_ERR` from repl.s so
  consumers (main.s, asm_src.s, disk.s) can import them instead
  of redefining locally.
- [x] ~~Dedup asm_src segment formatter with cmd_info free-line~~
  (fixed: shared `range_line` with two entry points `free_line`
  (suffix "b free") and `seg_line` (suffix "b").  Right-aligned
  5-digit decimal, 1-space gutter.  `s_seg_pfx` removed.  Phase 17)
- [x] ~~Rework `asm_src.s` newline handling~~ (fixed: removed 4
  redundant `jsr newline` calls; `log_close` provides trailing
  newline.  "asm..." line now uses `log_close` instead of bare
  `io_clear_eol`.  `seg_print_save` no longer needs its own
  newline.  Phase 17)
- [x] ~~Global release version: single `VERSION` propagation.~~
  (Phase 19 — done: Makefile generates `build/version.inc`
  per-build; strings.s `.include`s it and composes
  `VERSION_STR` as `"cse v" + VERSION_STRING + " by cr"`.  The
  D64 label format became `cse $(VERSION),01`.  PRG filenames
  stay stable.  See [build_system.md § Version propagation](build_system.md#version-propagation).)

## Roadmap

Long-term milestones in dependency order.

### R1 — Compile-time CPU gating (done)

All CPU-specific code gated with `.ifdef`/`.ifndef` instead of
runtime checks.

### R2 — Relocating startup (done)

CSE runtime relocated to high memory (floating start, page-aligned,
ending at $CFFF).  Discardable loader at $080D copies CODE+RODATA
at boot.  Two-pass link auto-computes runtime start address.
Workspace at $0800, ~30 KB free.  Exomizer SFX compression for
D64 distribution (~38% smaller).

### R3 — Universal C64/C128 binary

Single PRG runs on both machines.  Machine differences isolated to
three leaf functions (banking, NMI trampoline, keyboard).

### R4 — 80-column VDC mode (C128 only)

Self-contained VDC display driver, same interface as VIC-II routines.

### R5 — Cartridge ROM (CRT)

Build target for at least one CRT layout.  Candidates: Ocean Type 1
(simple banked ROM, wide emulator support) or EasyFlash (2×64 banks,
writable, real-hardware friendly).  Dual linker configs — one for
PRG, one for CRT.  Instant boot, no loader needed.  R2 (relocating
startup) provides the foundation: CODE+RODATA already position-
independent relative to their link address.

### R6 — Port C to asm (done)

All C ported to assembly.  cc65 C compiler eliminated.

### R7 — MEGA65 native support (stretch goal)

Native MEGA65 platform target, separate from C64-compatible mode.
The MEGA65 is a much more capable machine (32-bit address space,
relocated ZP internals in native mode, VIC-IV) requiring bigger
adaptations than a compatibility shim.  Alongside C128 native
(R3/R4), this would be a distinct platform target with its own
screen driver and memory model.  Far-future — depends on R3.

## Ideas

Exploratory, not yet scoped.

### Keyboard & input

- [ ] KERNAL keyboard CTRL combos: explore what key combinations
  the default KERNAL keyboard I/O delivers.  CTRL+key produces
  PETSCII control codes ($01–$1F) — identify which are usable
  without conflicting with KERNAL screen editor behaviour.
- [ ] SHIFT+CLR/HOME in REPL: clear screen.  C=+CLR/HOME: clear
  from cursor to end of screen.  Both use KERNAL screen editor
  codes (SHIFT+CLR = $93, CLR/HOME = $13).
- [ ] F-key bindings: assign useful functions to F1–F8 in both
  REPL and editor.  REPL candidates: help, repeat last command,
  toggle hex/dec, disassemble at PC.  Editor candidates: save,
  assemble, goto line, search.
- [x] Revise RUN/STOP+RESTORE and NMI handling.  (Phase 14, done)
  Permanent NMI dispatcher (`cse_nmi_handler`) at $0318.
  NMI-in-REPL → `cse_warm_screen` (clean screen recovery).
  Internal BRK → `cse_warm_start` (idempotent hard recovery).
  Warm-start re-entry guard prevents infinite BRK loops.
  NMI trampoline no longer corrupts $01.

### Features

- [ ] PRG load: auto-detect load address from PRG header.
- [ ] `$` command: filter directory listing by filename glob.
- [ ] `d` command: show ASCII alongside disassembly (like `m`).
- [ ] `.` command: show help when mnemonic given without operand.
- [ ] Color command `C`: show color preview swatches.
- [ ] Disk I/O: timeout handling for unresponsive drives.
- [x] NMI during `j` user code.  (Phase 14, done)
  `cse_nmi_handler` dispatches on `dbg_running` — user-code
  NMI breaks into debugger immediately via `dbg_nmi_break`.
- [ ] REU support for large source files.
- [ ] Macro support: .macro/.endmacro.
- [ ] Conditional assembly: .if/.else/.endif.
- [ ] Include files: .inc.
- [ ] Detect PAL/NTSC at startup.
- [ ] MEGA65 Open-KERNAL compatibility (C64-compatible mode):
  `$` works (LOAD-based).  Floppy status empty (shows `; `)
  — blocked on upstream IEC channel-I/O fixes
  (MEGA65/open-roms#116, #117).  Channel-based dir code
  preserved in `1348247` for when fixes land.  All other
  features work.  Native mode is roadmap R7.
- [ ] DDD back-reference tracking: link source files to their
  documentation via a machine-readable index.  DDD Maintenance
  verifies code changes trigger doc updates for all covering
  documents.
- [x] ~~**RESTORE-only screen recovery.**~~  (Phase 20 — done
  alongside the warmstart restructure.  NMI in kernel mode now
  routes directly to `cse_refresh` instead of swallowing, so
  RUN/STOP+RESTORE at the REPL gets the user their view back —
  the classic C64 affordance.  Debug context is preserved across
  the NMI.  See [main.md § cse_nmi_handler](modules/main.md)
  and [memory_design.md § Warmstart entry points](memory_design.md#warmstart-entry-points).)
