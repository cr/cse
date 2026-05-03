# VICE Test Plan — v0.1 final readiness

The mechanical audits (`dev/audit_doc.py`) and pytest suite catch
all the drift py65 can model against the real KERNAL ROM.  This
checklist covers what neither catches: real screen rendering,
real keyboard timing, real RUN/STOP+RESTORE behaviour, and real
1541 disk I/O.

Each item is < 1 minute.  Tick through linearly; any RED fails
the candidate.

**Build under test:** v0.1-rc3 (cse-cmos.prg, 21688 B compressed).

## A. Boot smoke (3 variants)

Run each PRG cleanly on a freshly-booted C64.

- [ ] **A1.** `LOAD "CSE",8,1` + `RUN` (CMOS build).  Splash
      shows version, ZP/RAM/work line counts, manual URL,
      `0800:` prompt.  No flicker, no error tones.
- [ ] **A2.** Same with `cse-6502-exo.prg` (6502 build).  CMOS
      mnemonics rejected by `.`/`a` with `;?cmos` error.
- [ ] **A3.** Same with `cse-exo.prg` (6510 build).  Illegal
      opcodes accepted by `.`/`a` (e.g. `lax $ff`).

## B. Theme gallery

`make THEME=NAME && exomizer && load on VICE`.  At least four
to spot-check the palette decoder.

- [ ] **B1.** `make THEME=GREENLAND` (default) — light-green
      border, green canvas, black text.
- [ ] **B2.** `make THEME=MATRIX` — black canvas, green text.
- [ ] **B3.** `make THEME=C64` — light-blue / blue / light-blue
      classic.
- [ ] **B4.** Runtime `c 0e6` — same colours as B3 applied via
      REPL command without rebuild.

## C. REPL command spot-checks

At the prompt:

- [ ] **C1.** `@ $C000` then `m` shows 16 bytes hex+ASCII.
      `+` advances, `-` retreats by `B` (default $10).
- [ ] **C2.** `B 8` then `+` advances by 8.  `B` alone shows
      current block size.
- [ ] **C3.** `. lda #$42` assembles 2 bytes at cur_addr,
      advances.  `.` (no operand) re-disassembles previous
      instruction.
- [ ] **C4.** `? $1234 + 100` shows hex/dec/binary/signed
      conversion table.
- [ ] **C5.** `r` shows registers.  `r a:7f x:00 y:80` updates
      reg shadows; subsequent `j` runs with those values.
- [ ] **C6.** `i` shows full memory map (zp / low / work /
      kernal / etc.).
- [ ] **C7.** `x` clears screen, redraws prompt.
- [ ] **C8.** ESC at prompt also redraws (same as `x`).
- [ ] **C9.** RUN/STOP+RESTORE at idle prompt redraws +
      preserves any active debug context.

## D. Editor

Press RUN/STOP from REPL to enter editor.

- [ ] **D1.** Editor opens with cursor at top-left.  Status bar
      at row 22 shows project name + free count + cursor pos.
- [ ] **D2.** Type a few lines.  Cursor up/down/left/right
      moves correctly.  HOME goes to col 0.  CLR/HOME (SHIFT-CLR)
      clears the workspace (with confirm).
- [ ] **D3.** Type a 40-char line — last column shows `>`
      overflow indicator.
- [ ] **D4.** Type a `tab` (using the C64-keyboard tab — SHIFT
      + SPACE per the project's convention).  Indents to next
      multiple of `TAB_WIDTH` (default 8).
- [ ] **D5.** RUN/STOP exits to REPL.  Editor content survives
      across REPL commands and back.
- [ ] **D6.** Re-enter editor, scroll past 22 lines.  Top
      stays scrolled when re-entering after REPL excursion.

## E. RC2 fixes — direct repro

Five bugs found via VICE testing of v0.1-rc1.  Each has a
specific scenario; verify the symptom is gone.

### E1. Capital-letter symbols  (commit `96a7239`)

Pre-fix: SHIFTed letters in expressions raised `;?expected`.

- [ ] **E1a.** In editor, type:

      ```
      .const start  $1000
      START:  rts
              .org Start    ; mixed case
              jmp START     ; full caps
      ```

      `a` → no errors.  `m start` shows the assembled bytes.

- [ ] **E1b.** At REPL: `? START + 1` evaluates without error.

### E2. NMI-during-CHROUT cursor jank  (commit `b96156f`)

Pre-fix: pressing RESTORE during a tight `jsr $FFD2` loop
left the editor / REPL cursor in a corrupted state.

- [ ] **E2a.** In editor, write a tight CHROUT loop:

      ```
      .org $C000
      main:   ldx #0
      loop:   txa
              jsr $FFD2
              inx
              jmp loop      ; infinite — exit via RESTORE
      ```

      `a`, then `g`.  After ~half a second, press RUN/STOP+
      RESTORE.

- [ ] **E2b.** Now press cursor-up/down at the REPL prompt
      several times.  Cursor moves cleanly one row per press.
      Pre-fix: first key eaten, second jumped two; cursor
      drifted off-screen.

- [ ] **E2c.** Same in the editor (RUN/STOP to enter).
      Cursor up/down behaves cleanly.

### E3. a+g+NMI+g phantom brk  (commit `5bd916b`)

Pre-fix: after a userland NMI break, the next `g` (after
the "go? y/n" prompt) appeared to hit a phantom BRK.

- [ ] **E3a.** Repeat E2's tight CHROUT loop.  RESTORE during
      the loop.  CSE shows the debug panel.

- [ ] **E3b.** Type `g $c000` (or just `g` since cur_addr is
      at the break PC).  CSE prompts `;!debug` + `go? y/n`.
      Type `y`.

- [ ] **E3c.** Verify: user code RESUMES (you see CHROUT output
      again).  Pre-fix: CSE immediately displayed regs as if a
      break had happened at $C000 without any code running.

### E4. KERNAL ROM disassembly  (commit `a1be6c3`)

Pre-fix: `d $E000` showed every byte as `BRK` / `...` because
dasm read RAM under KERNAL.

- [ ] **E4a.** `@ $e000` then `d`.  Output shows real KERNAL
      mnemonics (CINT, IOINIT-ish entries — opcodes like JMP,
      LDA, etc.).  No long runs of `BRK`.

- [ ] **E4b.** `@ $e9d6` then `d`.  Shows real CHROUT-path
      instructions (this is the address user RC1 reported).

- [ ] **E4c.** Step into a JSR to KERNAL: write `jsr $ffd2;
      rts` at $C000, `g $c000`, `t` (step into).  Falls back
      to step-over (per docs); doesn't enter KERNAL.

### E5. LDTB1 page-encoded line links  (commit `436750a`)

Pre-fix: KERNAL CHROUT after RESTORE landed only in the upper
~third of the screen because LDTB1's low bits encoded the
wrong page.

- [ ] **E5a.** Run E2 again, RESTORE, then assemble + run a
      different program with CHROUT output:

      ```
      .org $C000
      main:   ldx #0
      loop:   lda hello,x
              beq done
              jsr $FFD2
              inx
              jmp loop
      done:   rts
      hello:  .str "hello world", 13, 0
      ```

      Output should appear on the row below the prompt and
      scroll naturally.  Pre-fix: text would land in upper
      third regardless of scroll position.

- [ ] **E5b.** Repeat 5+ times rapidly.  No drift.

## F. Disk I/O

Requires a writable .d64 attached to drive 8 in VICE.

- [ ] **F1.** `$` lists directory.
- [ ] **F2.** In editor, write a small program.  REPL: `s "hi"`
      saves the source.  `$` shows `hi` (SEQ).
- [ ] **F3.** `k` (kill source) with confirm `y` clears editor.
      `l "hi"` reloads it.  Content matches.
- [ ] **F4.** `s "hi" $end` saves the binary.  `$` shows
      `hi.` (with trailing dot).
- [ ] **F5.** `l "hi" 0` loads the binary at its PRG header
      address.
- [ ] **F6.** `s "x"` followed by `s "x"` — second save warns
      `;!unsaved? y/n` only if editor changed in between.

## G. Cross-cutting

- [ ] **G1.** Type a long REPL line spanning two screen rows.
      Cursor wraps cleanly; RETURN executes the full line.
- [ ] **G2.** Type while CSE is mid-output (e.g. during `i`).
      Type-ahead works; keys queue and process after output
      finishes.
- [ ] **G3.** RUN/STOP+RESTORE during disk I/O (`l "huge"`)
      aborts cleanly — no corruption, REPL prompt redraws.
- [ ] **G4.** Quit via `Q` with confirm `y` — returns to BASIC
      `READY.` cleanly.  No screen corruption.

## H. Sign-off

- [ ] **H1.** All A–G items pass on the **CMOS** build.
- [ ] **H2.** A1–A3 pass on **6510** build.
- [ ] **H3.** A1–A3 + a representative subset (C1–C5, E1, E4)
      pass on **6502** build.
- [ ] **H4.** No new findings filed in `doc/TODO.md § Bugs`.

When H1–H4 all green: tag **v0.1**.

If any item fails: file as a new bug entry in `doc/TODO.md`,
fix, rebuild, re-tag as **v0.1-rc4**, restart this plan from A.
