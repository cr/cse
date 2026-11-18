# Testing — TDD Method and test framework conventions

**Template:** [subsystem](templates/subsystem.md)

## Test tiers

CSE tests fall into four explicit tiers that reflect the module
architecture.  A test lives in exactly one tier; the tier is
determined by the module's dependency profile, not by the test's
size or shape.  Tier I runs the C64 builds on `C64Emu` and the m65
build on `M65Emu` ([§ M65Emu](#m65emu--the-m65-integration-harness)).
Tier X runs the m65 build in xmega65: boot and disk, and the
reference `M65Emu` is checked against.

### Tier U — Unit (module + "linking down")

A module is **unit-testable** when its transitive dependency
closure contains only strictly lower-layer modules (plus acyclic
forward intra-layer edges — see
[architecture.md § Dependency Rules](architecture.md#dependency-rules)).
Link a bundle of [module + closure] with a minimal stub for
linker scaffolding (`__CODE_RUN__`, test entry point, BSS buffers),
and exercise via bare `py65.MPU` — no KERNAL ROM, no BASIC header,
no loader, no interrupt vectors.

Tests live in `tests/unit/`.  One pytest file per module (or
per bundle — the `asm_core` and `mn6`/`mn7` bundles group
tightly-coupled neighbours).

**m65 bundles** run on M65Emu's CPU, `MPU45GS02`
([§ M65Emu](#m65emu--the-m65-integration-harness)), in *clean* mode:
it admits the 6502's documented opcodes plus the opcodes of the
raw-byte macros in `src/m45_ops.inc`, and any other opcode stops the
test.  That is the run-time half of the clean-6502 rule; the static
half is an audit test that refuses a 45GS02-only opcode emitted
outside `m45_ops.inc`.

This is **bundled unit testing** (see [glossary.md § Process](glossary.md#process)):
a CSE-specific variant of Martin Fowler's *sociable unit testing*,
where the SUT runs against its real transitive dependencies instead
of mocks.  Stubs provide linker scaffolding only — never behaviour.
The codebase's stratified shape makes this cheap: a bundle is a
downward slice through the dependency DAG, so every test cell
exercises real code on real code without combinatorial blow-up.

### Tier I — Integration (C64Emu / M65Emu + full PRG)

A test graduates to Tier I when any of the following holds:
- Crosses the Layer-5 `main ↔ repl` cycle — these cannot be
  isolated topologically, only co-exercised.
- Requires the runtime environment: KERNAL ROM, interrupt
  vectors, banked memory, screen RAM at `$0400`, BASIC
  header + loader relocation.
- Exercises multi-module state transitions that depend on
  cold-init wiring (flag seeds, vector patches, dbg_init seed
  values).
- Inspects observable behaviour (screen-RAM contents, key
  dispatch, command prompts, disk I/O through KERNAL).

Tests live in `tests/integration/`.  All go through the
`C64Emu` harness (C64 builds) or the `M65Emu` harness (m65 build)
+ production/debug PRG fixture; no per-test build systems, no stubs
beyond what the harness provides (real KERNAL, real memory map).

### Tier X — xmega65 (m65, automated)

What M65Emu does not model, and the reference M65Emu is checked
against.  A test that needs the MEGA65's boot, its hypervisor or its
disk drive, or that records the 45GS02's behaviour for M65Emu's golden
files, runs in xmega65 (Xemu's MEGA65 emulator), driven by
`tests/xmega65.py` (which also holds what the golden-file recorders
share: the recording session and the file writer):

- **Start:** headless at full speed (`-headless -sleepless
  -skipconfigfile -besure`), the PRG through `-prg` or the D81
  through `-8` with `-autoload`.
- **SD card:** a copy-on-write clone (`cp -c`) of the configured SD
  image in xmega65's data directory, never the image itself.  An
  empty virtual SD card stops at the MEGA65's first-boot onboarding
  screen.
- **Input and state:** the `-uartmon` socket (monitor commands:
  `r` registers, `m` memory read, `s` memory write, `g` go, `t1`/`t0`
  trace mode on/off, `t` one step, `b` breakpoint — a hit is reported
  unprompted, after one more instruction); keystrokes go into the
  KERNAL keyboard buffer.  `s` and `m` address linear (28-bit) memory;
  the CPU's mapped view is the `777xxxx` range.  The socket path is relative to the run
  directory, because a Unix-domain socket path is limited to 104
  characters and xmega65 exits when it cannot bind.
- **Output:** `-dumpscreen`, `-dumpmem`, `-screenshot`, written when
  the test ends xmega65 with SIGTERM.

Tests live in `tests/emulator/` and are skipped, with the reason, when
`$(XMEGA65)` (the driver reads the `XMEGA65` environment variable) or
the SD image is absent.  Boot to the prompt takes
about 5–8 s, so Tier X holds the m65 boot, hypervisor and disk tests
and the recording of M65Emu's golden files, not sweeps; the sweeps
run on M65Emu.  xmega65 is an emulator: an answer it gives to a
hardware question (TODO O1, O3) is provisional until the hardware
confirms it.

### Tier M — Manual (VICE / xmega65 / hardware)

Timing-dependent, audible, visual, or real-I/O behaviour that
py65 cannot faithfully simulate: SID audio envelopes, VIC-II
raster effects, real 1541 drive timing, keyboard autorepeat
rhythms, thermal quirks.  Not automated.  Verified in VICE (C64
builds), xmega65 (m65) or on hardware — a C64 or the MEGA65;
documented in the relevant module's Caveats section.

### The tier-boundary signal

**If a test needs to manually stub out KERNAL calls, it's in the
wrong tier.**  Either link the real KERNAL via C64Emu or M65Emu
(Tier I), run the MEGA65 in xmega65 (Tier X, m65),
or write the test at a level where the KERNAL doesn't matter
(Tier U — pure data structures, pure arithmetic, pure parsing).

Per-module assignment is enumerated in the
[per-module tier table](#per-module-tier-assignment) below.

## M65Emu — the m65 integration harness

`tests/m65emu/` runs the m65 build on the real MEGA65 KERNAL inside
py65, as `C64Emu` runs the C64 builds on the real C64 KERNAL.  It is
built in three layers.

**Layer 1 — the CPU, `MPU45GS02`** (`tests/m65emu/mpu45gs02.py`).
A subclass of py65's 6502 MPU for its interface only — its register
names, `memory`, `step()`, `reset()`, `irq()`, `nmi()` and
`processorCycles` — with its own instruction table in place of
py65's (py65's inherited instruction helpers are unused, and wrong
for this CPU), implementing the whole 45GS02:

- all 256 4510 opcodes, including the 16-bit branches, `BSR`,
  `RTS #n`, the word operations (`INW`, `DEW`, `ASW`, `ROW`, `PHW`),
  `NEG`, `ASR`, and `MAP`/`EOM` with their interrupt latch (`MAP`
  with `X` = `$0F` or `Z` = `$0F` selects a megabyte instead);
- the registers `A X Y Z B`, the 16-bit `SP` (8-bit while the `E`
  flag is set; `PLP` and `RTI` never load `E`), and every zero-page
  access offset by `B`;
- the 45GS02 prefixes, executed as the CPU executes them: `$42` is a
  `NEG` and `$EA` an `EOM`, one step each, leaving a prefix state the
  next opcode reads — `NEG NEG` makes it a Q (32-bit `AXYZ`)
  operation, `EOM` makes a `(zp),Z` operation flat (`[zp],Z`, a
  28-bit pointer), both make a flat Q operation.  An opcode without a
  row for the prefix state runs as the plain opcode; interrupts wait
  while a prefix is pending, as between `MAP` and `EOM`.  The
  compendium's reserved Q rows (`RESQ`, `RSVQ`) and `NEG NEG NEG`
  raise instead of guessing.

Its decoder is built from the MEGA65 compendium's instruction tables,
`tests/fixtures/mega65_instruction_set.csv` (bbbc64's
`dev/mega65_opcode_extract.py` output, copied unchanged), not from
`dev/instruction_set.py`, so the emulator does not share the tables
the assembler is generated from: `tests/m65emu/isa.py` turns each row
into a decode key (the prefix bytes and the opcode) whose mnemonic and
mode select a semantic and an addressing routine; one routine serves
an operation at every width it comes in (8 bits, the 16-bit word
shifts, the 32-bit Q forms).  Cycle counts are not part of its
contract (the speed gate is the C64 builds'); `processorCycles`
counts steps.  In *clean* mode it admits only the
6502's 151 documented opcodes and the decode keys it is given — the
`m45_ops.inc` macros' ([§ Tier U](#tier-u--unit-module--linking-down))
— and raises `UncleanOpcode` on anything else.

It reads and writes through `memory[addr]` (the CPU's 16-bit view)
and `memory.read_flat()` / `memory.write_flat()` (the 28-bit space).
`FlatRAM` is the plain memory its Tier U tests run on (the CPU view is
the first 64 KB of the flat space); `M65Memory` is the real layout.

**Layer 2 — the memory layout, `M65Memory`**
(`tests/m65emu/memory.py`).  The object `MPU45GS02` reads and writes
through, as `C64Emu`'s `BankedMemory` is for py65 (the memory
protocol of layer 1: `memory[addr16]`, `read_flat()`, `write_flat()`):

- **The flat store** (28-bit): 384 KB chip RAM with the ROM image at
  `$20000`–`$3FFFF`, colour RAM at `$FF80000` (32 KB; its first 2 KB
  is the same memory as chip RAM `$1F800`–`$1FFFF`), attic RAM at
  `$8000000` (sparse).  While ROM protection is on — as after boot —
  writes to `$20000`–`$3FFFF` are dropped, flat or mapped.
- **The CPU's 16-bit view**, per 4 KB page, in the hardware's order:
  1. `MAP` (per 8 KB block, lower half `$0000`–`$7FFF`, upper half
     `$8000`–`$FFFF`): a mapped block reads and writes megabyte +
     ((offset + address) & `$FFFFF`) — the offset wraps inside its
     megabyte.
  2. Banking, from the CPU port's configuration ((`$01` |
     ~`$00`) & 7, the C64's table) and the ROM bits of `$D030`
     (`$8000`, `$A000`, `$C000`, `$E000`) — written in the VIC-III or
     VIC-IV I/O mode, and still banking after a switch to VIC-II: a
     ROM page reads `$20000` + address — at `$D000` the character ROM
     — and writes the RAM under it; an I/O page is `$D000`–`$DFFF`.
  3. Otherwise RAM, address = flat address.
- **The CPU port**: `$00` (direction) and `$01` (data) exist only in
  the CPU's view; flat `$0`/`$1` are plain RAM.  While `MAP` covers
  block 0 the port is hidden: `$00`/`$01` are then the mapped memory.
- **The I/O page**, in the mode the `$D02F` key selects (`$47 $53`
  VIC-IV — the post-boot mode —, `$A5 $96` VIC-III, anything else
  VIC-II): `$D800`–`$DBFF` is colour RAM `$000`–`$3FF` (in VIC-II mode
  only the low nibble is written and the high nibble reads as `$F`);
  `$D030` bit 0 maps `$DC00`–`$DFFF` to colour RAM `$400`–`$7FF`,
  hiding the CIAs (full bytes in every mode); `$D02F` and `$D030` act
  as above; every other register is plain storage — one bank, the
  same in every I/O mode — until a layer-3 device claims it.  The
  ethernet I/O mode, the disk buffer and the hypervisor are not
  modelled.
- **The page table**: 16 entries of 4 KB, rebuilt only when a `MAP`
  register changes — by `MAP`, a reset, or an assignment to the CPU's
  `mapl`, `maph`, `map_lo_mb`, `map_hi_mb`; each calls
  `memory.map_changed(cpu)` (which `FlatRAM` ignores), so the CPU and
  the memory cannot disagree — or `$00`, `$01`, `$D02F` or, in the
  VIC-III/IV I/O modes, `$D030` is written.  A byte access is a table
  lookup and, for chip RAM, one index; flat access uses the 28-bit
  address directly.  `load()` puts bytes into the flat
  store past ROM protection, as the monitor and a ROM loader do.

**Layer 3 — the devices** (`tests/m65emu/devices.py`), added one at a
time, each when a test needs it.  A device claims a range of I/O
registers in `M65Memory` (`M65Memory.attach()`); the CPU's accesses to
them go to the device, which reaches memory through the flat
interface and the I/O page through `io_read()`/`io_write()`.  Unclaimed I/O registers read back what was written;
`M65Memory.io_log` counts each access to one (`R $Dxxx` / `W $Dxxx`),
so a test can assert which there were.  What the KERNAL uses decides
the order: it scrolls the screen by DMA, `GETIN` reads the hardware
keyboard queue, and its IRQ handler does its frame work — cursor
blink, key repeat, the STOP scan of the CIA1 matrix into `$91` — only
when `$D019` bit 7 reports a VIC interrupt.  It keeps no jiffy
counter: `RDTIM` reads the CIA1 TOD clock (`$DC08`–`$DC0B`), which,
like the CIA timers and raster timing, is not modelled — `C64Emu`
models none of them either.

- **The DMA controller** (`$D700`–`$D70F`).  A job list is read from
  the flat address `$D700`/`$D701`/`$D702` (bits 0–22; writing `$D702`
  clears the megabyte) and `$D704` (the megabyte) give; `$D70E` sets
  bits 0–7 without starting.  Writing `$D700` starts a list in the
  format of the default revision (`$D703` bit 0: F018A, or F018B with
  its extra sub-command byte; bit 1: megabyte crossing), writing
  `$D705` an enhanced list (an option list before each job).  Commands: copy, fill, swap, mix; each side steps
  up, down or holds; chained jobs; a side with address bit 23 set
  reads or writes the I/O page.  Enhanced options: revision (`$0A`,
  `$0B`), source and target megabyte (`$80`, `$81`), skip rates
  (`$82`–`$85`), transparency (`$06`, `$07`, `$86`), the length's
  third byte (`$90`), the source and target start fractions (`$91`,
  `$92`), megabyte crossing (`$01`); other options are ignored, as
  xemu ignores them.  A job runs to its end
  when it is started — the CPU is halted during DMA on the MEGA65 too.
  Line drawing, modulo mode and lists read through the CPU's view
  (`$D706`, `$D707`) are not modelled: they raise `DMANotModelled`.
  The recording settled three points: DMA writes into protected ROM
  are dropped; an enhanced option holds for the rest of the session,
  chained jobs included (their own option lists add to it); a held
  target keeps the last byte.  After boot the KERNAL runs the
  controller in F018B mode (`$D703` = 1); a snapshot restores the
  registers without starting a job (`M65Memory.restore_io()`).
- **The keyboard queue** (`$D610`, `$D619`, `$D60A`, `$D611`).  Each
  entry is a key as ASCII, as PETSCII and its modifier keys; `$D610`
  reads the head's ASCII (0 when empty), `$D619` its PETSCII (`$FF`
  when empty), `$D60A` its modifiers (bit 7: an entry is waiting);
  writing `$D610` or `$D619` drops the head, writing `$D60A` with bit 7
  clear empties the queue; `$D611` reads the keys held now (none).
  `M65Emu.inject_keys()` queues PETSCII bytes, as `C64Emu`'s does.
- **The CIA1 keyboard matrix** (`$DC00`, `$DC01`): port A selects
  columns (a 0 bit selects), port B reads a 0 in the row of each held
  key in a selected column — the matrix `C64Emu` reads, shared
  (`emu_base.KeyMatrix`); `press_key()`, `press_stop()` and their
  releases set it.  The KERNAL's frame work reads column 7, so
  `press_stop()` and one tick make `STOP` (`$FFE1`) report the key, as
  on the C64.
- **The VIC interrupt latch** (`$D019`), as xmega65 shows it
  (`m65_latches.json`): bits 0–3 latched, cleared by writing 1s to
  them (the KERNAL acknowledges with `TSB $D019`; a 0 clears nothing);
  bits 5–6 read as 1; bit 7 is the IRQ line — whether a latched bit is
  enabled in the mask `$D01A` (plain storage; `$E1` after boot),
  computed when a bit latches and when `$D019` is written, not when
  the mask changes.  Nothing is latched after a snapshot.  The jiffy
  tick latches bit 0, the raster interrupt, before it raises the IRQ —
  the tick stands for a frame, without raster timing.
- **The CIA2 interrupt control register** (`$DD0D`): bit 4 latched by
  `press_restore()`, which also raises an NMI, as `C64Emu` does;
  reading returns the latch and clears it — as xmega65 does for a
  timer A underflow whose source is masked (`m65_latches.json`: `$01`,
  then `$00`).

The hypervisor (`$D640`–`$D67F`) and the floppy controller (`$D080`)
are not modelled: a test that needs them is Tier X.

**Starting state.**  M65Emu does not emulate the boot.
`dev/capture_m65_state.py` (run by hand; about 25 s) boots xmega65 to
the BASIC 65 prompt, stops the CPU in trace mode and reads, over
uartmon, a post-boot state into `build/m65_state/`:

- `chip.bin` (384 KB, the ROM image included), `colour.bin` (32 KB),
  `io.bin` (the I/O page `$D000`–`$D7FF` in VIC-IV mode; not the
  CIAs, whose reads clear their flags);
- `state.json`: the snapshot's format number, the CPU registers and
  `MAP` (the megabyte selectors
  cannot be read; they are 0 after boot, as `m65_mem.json`'s
  post-boot state confirms), the CPU port, `$D030`, the I/O mode,
  the xmega65 version and the ROM's SHA-256 — the ROM must be
  `rom/mega65.rom` (the script runs `make m65-rom`'s discovery first
  and refuses to record when the booted ROM differs:
  [build_system.md § MEGA65 ROM](build_system.md#mega65-rom));
- `reference.json`: what xmega65 did next, run after run from that
  state — each run's code as it was planted (ending in the `JMP` to
  itself that parks it), the address it ends at, the registers and
  the memory changes — the oracle M65Emu's Tier I tests replay in the
  same order: "chrout" (`SEI`,
  `LDA #'A'`, `JSR $FFD2`; single-stepped, so its 125 steps are
  recorded too) and "scroll" (30 RETURNs and an 'A' through `CHROUT`,
  the screen scrolled by DMA; about 140k steps, run at full speed to a
  breakpoint with interrupts off).

The state contains the MEGA65 ROM, so it is never committed; M65Emu's
Tier I tests are skipped, with the reason and the command that makes
it, when it is absent or in an older recorder's format.  Pytest never
starts xmega65 by itself.

**Interface.**  `M65Emu` (`tests/m65emu/harness.py`) has `C64Emu`'s
test surface: what a Tier I test calls is the same on both, so a test
of behaviour both platforms share is parametrised over both
harnesses.  The two share one base class (`tests/emu_base.py`), which
holds:

- the registers `a`, `x`, `y`, `pc`, `p` and the flags, `cpu`,
  `memory`, `jsr()`, `run_until()`, `run_until_with_watch()`,
  `run_steps()` (a fixed number of steps, for code that never ends),
  `read_word()`, `write_word()`, `sym()`, `sym_opt()`, and the
  screen-code decoding behind `screen_text()`;
- the interrupt scheduler: `schedule_irq(n)` and `schedule_nmi(n)`
  raise an interrupt `n` steps from now, `cancel_pending_interrupts()`
  drops them, `enable_jiffy_clock(interval)` (16421 steps by default)
  and `disable_jiffy_clock()` a repeating IRQ, each tick counted from
  the step the last one fired.  An IRQ waits while the CPU refuses it
  (`I` set), an NMI does not; IRQs due together fire one after another,
  NMIs due together once.  Steps, not cycles, count;
- the keyboard: `press_key()`, `release_key()`, `release_all_keys()`,
  `press_stop()`, `release_stop()` on the shared matrix,
  `press_restore()`, `inject_key()` and `inject_keys()`;
- `load_prg()`: the payload at its load address, the symbols of the
  `.lbl` beside the map, and each segment whose load and run
  addresses differ (`__<SEG>_LOAD__`/`_RUN__`/`_SIZE__`) copied to its
  run address, as the loader does;
- `set_cursor(row, col)`: the KERNAL's `PLOT` (`$FFF0`, carry clear),
  called through `jsr()`;
- `init_cse(editor=False)`: cse's cold-init routines by symbol
  (`theme_init`, `restore_colors`, `setup_interrupts`, `dbg_init`,
  `sym_clear`; `ed_ensure_init` with `editor`).

Each harness supplies what differs:

| | `C64Emu` | `M65Emu` |
|---|---|---|
| Interrupt entry | the 6502's frame, vector through the banking | `MPU45GS02.irq()`/`nmi()` — also held off while a prefix or the `MAP` latch is pending |
| Jiffy tick | the IRQ alone (the KERNAL counts `$A0`–`$A2`) | latches `$D019` bit 0 first (the KERNAL's frame work) |
| RESTORE | CIA2 `$DD0D` bit 4 and an NMI | the same, through the `$DD0D` device |
| `inject_key()` | the KERNAL buffer (`$0277`, `$C6`; ten keys, then `OverflowError`) | the hardware keyboard queue (unbounded) |
| `load_prg()` writes | RAM under any ROM | bank 0 |
| Registers of its own | — | `z`, `b`, the 16-bit `sp` (the `MAP` registers through `cpu`) |

and M65Emu besides:

- `jsr()` pushes the return onto the current stack (in the post-boot
  state, BASIC 65's) and stops at a sentinel (`$0002`) compared by PC
  only, never written to memory;
- `screen_text()` finds the screen through the VIC-IV screen pointer
  (`$D060`–`$D063`), the line step (`$D058`–`$D059`) and the width
  (`$D05E`) — the KERNAL's `CHROUT` reads the same pointer;
- `memory.io_log` counts the accesses to I/O registers no device models.

`C64Emu`'s synthesised KERNAL state stays its own; M65Emu starts from
the snapshot instead.

The shared contracts — the scheduler, the jiffy tick, the matrix,
RESTORE, key injection, `load_prg()` relocation, `set_cursor()`,
`init_cse()` — are tested once, parametrised over both harnesses, in
`tests/integration/test_emu_parity.py`; C64-only cases (the vector
fetched through banking, the matrix hidden under the character ROM,
the KERNAL's `$A0`–`$A2`) stay in `test_c64emu_*.py`.

The Tier I tests (`tests/integration/test_m65emu.py`) replay the
reference runs: `CHROUT` on the real MEGA65 KERNAL takes the same 125
steps as in xmega65, and both runs leave the same registers, chip RAM
and colour RAM — the scroll's 700 DMA jobs included.  The character
shows on the screen as `screen_text()` reads it, the scroll touches no
I/O register that no device models but the screen pointer, and `GETIN`
returns injected keys in order, then 0.  On the real KERNAL too: a
jiffy tick runs the IRQ handler's frame work and is acknowledged;
`press_stop()` and a tick make `STOP` report the key; `press_restore()`
enters the KERNAL's NMI handler, which reads `$DD0D`; `set_cursor()`
moves the cursor where `PLOT` reads it back.

**Validation.**  M65Emu is checked against xmega65, not against our
own reading of the compendium:

- `dev/capture_m65_golden.py` runs instruction sequences in xmega65 —
  one per row of the fixture (both outcomes of every conditional
  branch) and edge cases (flags, BCD, stack wraps in both `E` modes,
  base-page wraps, prefixes without a row, `MAP` megabytes), with
  chosen operands, registers and flags, in block 0, which the
  post-boot `MAP` leaves unmapped — and records the registers and the
  memory differences before and after each into
  `tests/fixtures/golden/m65_cpu.json` (no ROM content, so it is
  committed; one case per line; the format is in
  `tests/m65emu/golden.py`).  The registers are set by a preamble the
  CPU executes, and `before` is read after it, so the preamble's own
  semantics do not matter.  `BRK` reads its vector through the `MAP`,
  outside the recorded memory; the case records the two bytes as the
  CPU saw them.  The file records the xmega65 version; it is
  re-recorded when xmega65 is updated or a case is added, and a
  changed `after` in the diff is a behaviour change of the reference,
  which the commit states.
- `tests/unit/test_mpu45gs02.py` (Tier U) runs the same sequences on
  `MPU45GS02` and compares registers and memory; it needs neither
  xmega65 nor the ROM.  It also pins the 45GS02-specific behaviour by
  name and checks the decoder against the fixture row for row.
- `dev/capture_m65_mem.py` sets up banking states in xmega65 —
  `MAP` run in block 0, CPU-view writes (uartmon's `777xxxx`
  addresses) to `$00`, `$01`, `$D02F`, `$D030` — and records, per
  state and probed address (one per 4 KB page, plus the extended
  colour window where `$D030` bit 0 opens it), the flat address a CPU
  read comes from and where a CPU write lands (or that it is
  dropped), into
  `tests/fixtures/golden/m65_mem.json`.  Unique signatures planted in
  the candidate RAM pages make the match unambiguous; a ROM page is
  matched by its own content, which is never recorded; two candidates
  holding the same bytes stop the recording (an alias would make the
  record a guess).  I/O pages other than the colour window are not
  written (side effects).  29 states, the first re-creating what
  xmega65 booted into, plus three observations the probes cannot
  make: a flat `STA [zp],Z` into ROM; one I/O register written in
  VIC-IV mode and read back in every mode; and the CPU port while
  `MAP` covers block 0 (mapped onto itself, so the code keeps
  running).  Two xmega65 limits shape the states: no state maps megabyte
  `$08` (undecoded; xmega65 crashes), and the upper-half attic state
  uses megabyte `$81`, because flat `$8008100` reads the same bytes as
  `$8100`.
- `tests/unit/test_m65memory.py` (Tier U) replays every recorded
  state on `M65Memory`, and pins by name the shared colour RAM, ROM
  protection, flat access, and that the page table is rebuilt only by
  its triggers; one test runs `MAP` on `MPU45GS02` over `M65Memory`.
- `dev/capture_m65_dma.py` plants a job list at `$1C00`, fills the
  memory regions with the pattern and starts the list from code in
  block 0, recording what each job changed into
  `tests/fixtures/golden/m65_dma.json` (28 cases: both list formats,
  every command, stepping, chaining, I/O on either side, a copy into
  ROM, the enhanced options).  A job runs to its end within the step
  of the store that starts it, in xmega65 as in M65Emu.
  `tests/unit/test_m65dma.py` (Tier U) replays them through the CPU's
  view of the DMA registers.
- `dev/capture_m65_latches.py` runs a probe in block 0, interrupts
  off, at full speed to a breakpoint: `$D019` acknowledged, the raster
  bit waited for with `$D01A`'s raster mask on and off, written with
  0 bits; a CIA2 timer A underflow with its sources masked, `$DD0D`
  read twice.  The eight values read go into
  `tests/fixtures/golden/m65_latches.json`;
  `tests/unit/test_m65devices.py` drives the two devices through the
  same steps (a latch call for each raster line waited for) and must
  read the same values.
- A Tier X test (S2-8) re-runs the capture when xmega65 is present and
  fails on any difference from the committed golden file.

An M65Emu answer to a hardware question (O1, O3) is xmega65's answer
at second hand: provisional until the hardware confirms it.

The recording (xmega65 `0870689e`, 2026-11-17, 518 cases) overruled
the compendium reading in two places, which `MPU45GS02` now follows:
decimal-mode `ADC`/`SBC` behave as on the NMOS 6502 (the
flags come from the binary result, not the 65C02's), and `BIT #`
sets `N` and `V` from the operand like the other `BIT` modes.
Everything else recorded — the 16-bit branch base, `BSR`, `RTS #n`,
`PHW`'s byte order, `BRK`, the `E`-flag stack, base-page wraps, the Q
and flat operations — agreed with the reading.

**Not in the recording.**  The monitor cannot raise an interrupt or
show the latch, so these rest on a reading of xemu's source, not on
its behaviour: interrupt entry (`irq()`, `nmi()`), the `MAP` latch
and the pending-prefix interrupt hold.  Of the memory layout, the
translation recording does not cover a `$D030` write in VIC-II mode
(`M65Memory` leaves banking alone), nor what any I/O register does
beyond the colour window, `$D02F`, `$D030` and one plain register.
The keyboard queue rests on xemu's source alone: the monitor cannot
type a key.  Of the parity devices, the recording covers the two
latches' register behaviour; it cannot press RESTORE, so its bit 4 in
`$DD0D` follows `C64Emu`, and the jiffy tick standing for a frame
rests on traces of the MEGA65 KERNAL on M65Emu (its frame work runs
on a latched raster bit; no raster position or frame rate is
modelled).
Two things xmega65 does that `MPU45GS02` does not: it holds an
interrupt off for one instruction after a single-cycle instruction
(no cycles here), and it runs `NEG NEG NEG` as a 32-bit negate (no
compendium row, so it raises).

## The TDD Method

The TDD Method is the testing companion to the CDD Method (see
[README.md § The CDD Method](README.md#the-cdd-method), step 3).  It governs how
tests are written, when they are written, and what they test.

### Principles

1. **Design for testability.**  Code and interface design must keep
   testability in mind from the start.  This does not mean everything
   gets automated tests — it means the question is always asked and
   consciously answered.

2. **Test contracts, not implementation.**  Tests verify the
   documented interface — given these inputs, expect these outputs,
   this carry flag, this error code.  Tests do not assert internal
   state (ZP scratch, loop counters, intermediate buffers) unless
   that state *is* the contract.

   Example: the sticky-OR width rule (`$00 + $0000` → ABS) is a
   design decision.  Tests pin it down because changing it silently
   breaks user code.  But *how* expr.s implements the OR (which ZP
   byte, what order) is an implementation detail tests must not
   depend on.

3. **Automation is a judgement call.**  Not all behaviour is suited
   for automated testing.  The TDD Analysis must evaluate each
   change and explicitly state whether automated tests are
   practical, impractical, or unnecessary.  When automation is
   impractical, say so and state the alternative (CDD audit, manual
   VICE testing, code review).

4. **UI-heavy code gets selective testing.**  The REPL command loop
   (exec_line, read_line, show_prompt) is tested via `test_repl.py`
   by calling real functions in the production binary through
   `C64Emu`.  The editor is tested the same way.  Full
   keyboard/cursor/scroll interaction remains manual (VICE).  The
   principle: test the command logic and data paths; leave visual
   presentation to manual testing.

5. **Don't drown in harness complexity.**  The test harness must
   remain simpler than the code it tests.  `C64Emu` + the real PRG
   binary eliminates per-test build systems, ASM stubs, and KERNAL
   mocking.  If a test still requires elaborate scaffolding beyond
   what `C64Emu` provides, that is a signal to test at a different
   level or to rely on manual verification.

6. **Test the actual ASM, not a Python copy of it.**  Load the
   production binary into `C64Emu` and exercise the real code.
   Do **not** write a Python function that re-implements the
   algorithm and assert that the Python and the Python agree —
   that is a tautology dressed as a test.  See the
   [Anti-patterns](#anti-patterns) section below for the
   cautionary examples currently in the tree.

7. **Pre-cutover stress tests for phase-scale refactors.**  When a
   refactor introduces a new mechanism that *claims to handle* a
   scenario the old code prevented (by masking / locking / guarding),
   write stress tests that force that scenario through the new
   mechanism **before** you trust the design enough to remove the
   old guard.  Passing the existing test suite + documenting the
   desired state (CDD Step 1) is *not* sufficient — the old guard
   was often masking latent bugs that the new mechanism has to
   handle on its own.

   Cautionary example: Phase 18 introduced `cse_brk_handler_early`
   with stack surgery to handle "IRQ fires while KERNAL is banked
   out" transparently.  The pre-existing SEI guards in
   `kernal_bank_out/in` had been masking that scenario entirely.
   Phase 18 landed with the new handler and all tests green
   (`a628e65`).  A later optimisation commit dropped the "now
   redundant" SEIs (`8e60b62`) — which *finally exposed the new
   mechanism to the stress it was designed for*, and three latent
   bugs in the handler surfaced in quick succession (`c347fa8`,
   `941435d`), triggered by the user running common workflows.

   The discipline: for every "new mechanism replaces old guard"
   refactor, write a test that *forces the scenario the old guard
   prevented* and asserts the new mechanism handles it correctly —
   **before** removing the guard.  For IRQs, this means a test
   that schedules an IRQ at each cycle across the critical window.
   For stack-contract changes, tests that exercise the edge case
   the old contract forbade.  The asymmetric C64Emu fixture
   (`test_kernel_transition.py`) is the right shape for these —
   expand it systematically when new mechanisms land.

8. **Contractual coverage is exhaustive, not illustrative.**  Module
   documentation is an API contract.  Every exported symbol is
   load-bearing — internal callers link to it by name, and every
   promise the doc makes is something downstream code is entitled
   to rely on.

   - **Every exported function** gets at least one correctness
     test.  Not a smoke test — a test that would fail if the
     function stopped meeting its documented contract.
   - **Every exported data symbol** (RODATA table, BSS byte,
     constant) gets at least a content/addressability test so a
     stale value or mis-linked symbol is caught.
   - **Edge cases** (zero-length, single-element, boundary
     values, end-of-range clamping) are part of the contract and
     get tested explicitly.  Parametrised tests covering the
     full boundary-adjacent range (0, 1, N-1, N, N+1) are the
     baseline; full sweeps (e.g. all 17 576 mn7 inputs) are the
     ceiling.
   - **"User-facing" vs. "implementation-detail" is not a valid
     excuse.**  A symbol exported across module boundaries is by
     definition not an implementation detail; other modules link
     to it.  (This principle was added after a test-audit round
     in which several L1 exports had been deferred as
     "internal sibling helpers" and received no coverage.  If a
     symbol is exported, someone depends on it; that someone is
     what the test protects.)

9. **Vocal omissions — skipped tests must state a reason in code.**
   When a contractual test is not automated, the omission must be
   explicit and machine-readable.  Use pytest primitives:

   - `@pytest.mark.skip(reason="…")` — permanent skip for a
     behaviour that cannot be exercised at this test tier (e.g.
     hardware side-effect that py65 doesn't model).  The reason
     must say what tier can exercise it (manual VICE, real C64,
     integration-tier C64Emu).
   - `@pytest.mark.skipif(cond, reason="…")` — conditional skip
     when a build flag or environment dictates applicability.
   - `@pytest.mark.xfail(reason="…", strict=…)` — known-failing
     test pinning a pending bug; `strict=True` makes the test
     fail if it starts unexpectedly passing.
   - `pytest.skip(reason="…")` (function body) — runtime skip
     when a precondition can't be established at fixture time.

   Every skip/xfail reason must name the specific contract
   clause that isn't being verified and where it *is* verified
   (another test, another tier, or the manual-VICE checklist).
   "TODO" and silent `pass` bodies are not acceptable
   substitutes — the test file must be vocal about what it
   covers AND what it deliberately doesn't.

   `pytest --runxfail` re-runs xfailed tests without the mark,
   which is useful after a pending fix has landed.  `pytest
   --strict-markers` catches typoed marker names.

   #### Skip-reason patterns

   A skip reason must fit one of three categories.  Unsure which
   one applies → the test probably shouldn't be skipped, it should
   either be written or deleted.

   **A. Out-of-tier.**  The behaviour IS testable, just not in
   this harness.  The reason must name the tier that covers it:

   ```python
   @pytest.mark.skip(reason=(
       "$01 reads fully-latched under DDR=$FF (mem.md § CPU-port "
       "aware ZP save/restore): py65 has no CPU-port emulation. "
       "Byte-level round-trip is verified here (TestSaveUserlandZp); "
       "the fully-latched guarantee is verified on the VICE manual "
       "checklist.  If C64Emu ever gains CPU-port modelling, convert "
       "this skip into a real test."
   ))
   ```

   **B. Subsumed by another test.**  Write this skip only after
   retiring the test — leave a one-line pointer at the same source
   location so `grep` still finds where the coverage lives:

   ```python
   # test_round_trip retired — subsumed by TestSaveRestoreEdgePatterns::
   # test_userland_round_trip (four patterns, strictly better coverage).
   ```

   Prefer pointer-comments over skipped-test-bodies for this case:
   `pytest.mark.skip` wastes a test slot for something that is
   actively redundant.

   **C. Cannot be enforced at any unit tier.**  System-level
   invariants that live outside the module's control.  The reason
   must name the enforcement mechanism that IS used (code review,
   grep, build check).

   ```python
   @pytest.mark.skip(reason=(
       "$CC=1 lifetime invariant (cse_io.md § IRQ Safety): the "
       "invariant requires $CC=1 for the program lifetime.  No "
       "unit test can verify that other modules won't later clear "
       "$CC.  Enforcement today: code review + grep for '$CC' in "
       "src/ (currently only io_init references it)."
   ))
   ```

   #### Risk preamble for high-impact gaps

   When a skip covers a contract clause whose regression would
   ship silently (hardware-only, system-level), mark the gap with
   a dated preamble comment at its source location:

   ```python
   # ⚠  TOP-RISK L1 GAP (per coverage audit 2026-04-20):
   #    The DDR-stash protocol is the most-likely place an undetected
   #    L1 regression could land — a "clever" refactor of save_*_zp
   #    that byte-round-trips on py65 but breaks the fully-latched-$01
   #    read on silicon would pass CI and ship.  The only backstop
   #    is the VICE manual checklist.
   ```

   Risk tiers:
   - **TOP** — silent-ship regression is plausible and impact is
     module-wide (corruption, crash, silent data loss).  Treat
     the VICE checklist as mandatory before merging any change to
     the flagged code path.
   - **HIGH** — silent-ship possible but requires specific
     conditions; scope is bounded.  Code review is the primary
     mitigation.
   - **LOW** — regression requires a separate maintainer mistake
     (e.g. copying a broken harness pattern).  A single existing
     assertion elsewhere is already a de-facto guard — the skip
     exists mainly to document the reasoning.

   The preamble's date stamps the audit pass.  Future audits
   either refresh the date, upgrade/downgrade the risk tier, or
   remove the preamble if the gap is closed (e.g. a new integration
   test covers it).

   #### When to prefer `xfail` over `skip`

   Use `xfail(strict=True)` for a test whose code is WRITTEN and
   whose expected behaviour IS the contract, but which currently
   fails against a known bug.  This makes the test fail the suite
   the moment the bug gets fixed — a free alarm that the skip can
   now go away.

   Use `skip` for behaviour that isn't implemented at the test
   tier at all (no code to run).

   Never use `xfail(strict=False)` — it silences both failure and
   unexpected passes, defeating the point.

10. **Test bundles must mirror production build configs.**  A module
    built by the Makefile as N distinct binaries (different `-D`
    flag combinations, different source subsets) is effectively N
    modules for testing purposes.  The test harness owes coverage
    to each production variant.  One bundle per variant; one fixture
    per bundle; one test class per fixture.

    **Why this is load-bearing.**  Any code path gated by a
    conditional-compilation flag is INVISIBLE to a test bundle
    whose flags don't match.  If asm_line.s has `.ifdef CMOS_SUPPORT`
    around the CMOS reject gate, and the asm_core test bundle always
    sets `-DCMOS_SUPPORT`, then bugs in the non-CMOS_SUPPORT path
    cannot fail a test.  They will ship undetected.

    **Mechanics.**  When a module ships as N production variants,
    [conftest.py](../tests/conftest.py) parametrises the bundle
    config (`_AC_FLAGS[config]`, `_AC_CLASSIFIER_SOURCES[config]`,
    etc.) and exposes N session fixtures (e.g. `asm_syms`,
    `asm_6510_syms`, `asm_6502_syms`).  Each variant has a matching
    test class in the module's test file.  When adding or removing
    a production variant (Makefile `-D` changes), the bundle list
    moves with it — same commit.

    Cautionary example: the asm_cpu gate escape (doc/README.md
    § Escape Analysis, first canonical application).  The gate bug
    was invisible because only one bundle existed, matching only the
    65C02 production build.  Adding 6510 and 6502 bundles made the
    bug a failing test in one commit.

11. **Contract matrices drive test matrices.**  When a doc describes
    behaviour parametrised by N axes (e.g. asm_cpu × category,
    build-flag × classifier, side × operation), the doc enumerates
    each cell and the test suite covers each cell.  "Rejects CMOS
    on NMOS" is one cell of a 12-cell matrix and tells you nothing
    about the other 11.

    **How this shows up in docs.**  Prefer tables over prose for any
    conditional behaviour.  A contract written as "accepts X on Y;
    rejects otherwise" hides the matrix; a two-axis table makes
    every cell an enumerable testable commitment.  Use [asm_line.md
    § asm_cpu × category gate matrix](modules/asm_line.md) and
    [mn_classify.md § Variants](modules/mn_classify.md) as templates.

    **How this shows up in tests.**  Parametrise the test function
    over the matrix axes.  `@pytest.mark.parametrize` over a list
    of `(source, asm_cpu, expected_behaviour)` tuples makes every
    cell a named case with its own failure line.  Cells the
    contract intentionally leaves open (e.g. "undefined behaviour
    on asm_cpu=3") still belong in the matrix — marked with a
    vocal skip per Principle 9.

    Cautionary example (asm_cpu gate): same as Principle 10.
    Pre-amendment asm_line.md documented "asm_cpu values 0/1/2"
    and "the CMOS gate rejects non-CMOS" — a one-axis spec for a
    two-axis problem.  Eleven of twelve cells were unspecified;
    22 of them shipped broken for years before the matrix audit
    surfaced the gap.

    Cautionary example (dot-command input shapes, Escape Analysis
    2026-04-20): the REPL `.` command accepts *four* input shapes
    — empty, hex-pair(s), mnemonic, and an implicit "garbage"
    fallback.  Pre-amendment repl.md listed only three (empty,
    hex, mnemonic); the garbage cell was handled by the code's
    default fallthrough, which silently mapped it to "silent
    redisplay" instead of the intended "syntax error".  Inputs
    like `. .`, `. ,`, `. $`, `. 123` produced no emit and no
    error — the user got zero feedback.  Writing out the full
    four-cell matrix forces the default-case cell to be a named
    commitment ("other → SYNTAX ERROR") rather than whatever the
    code happens to do.  Rule of thumb: every input-classification
    gate needs an explicit rejection cell — "anything else
    silently ignored" is never a contract, it's a bug waiting to
    be found.

12. **Axiomatic modules need no unit tests.**  An **axiomatic module**
    is one that declares only symbol exports — layout slots, RODATA
    literals and tables, BSS reservations, numeric constants — and
    contains no CODE segment.  In CSE these are all of L0 (`zp`,
    `strings`, every `*_tables`, `oplen_tbl`, `dasm_mne_idx`) plus
    `mn_vars` at L1 (pure BSS scratch).  An
    axiomatic module has no testable contract beyond "the symbols
    exist and link," which the linker enforces on every build.

    **Why no unit tests.**  A unit test needs something to assert.
    Asserting a generated mask byte (`mn_modes_lo[pidx] == …`) against
    the generator's own output is a mirror test (see Anti-patterns § Mirror tests).
    Asserting `strings_prompt == "cse>"` against a string literal
    is tautology.  The only meaningful correctness check for
    axiomatic data is "does it make consumers behave correctly" —
    and that check lives in the consumers' bundled tests, which
    already link the module.

    **Transitive coverage is the contract.**  Every bundled test
    that links an axiomatic module is a data-integrity test for
    that module.  A corrupt `oplen_tbl[$A9]` fails `test_dasm`; a
    misaligned ZP slot crashes any bundle that uses it; a wrong
    `mn_modes` bit fails `test_addr_mode`.  Axiomatic-module bugs
    can't hide — they manifest in every bundle that links the
    broken data.

    **Generated-table subtlety.**  Tables produced by
    `dev/mnemonic_tables.py` (`mn_asm_tables`, `mn6/7_tables`,
    `mn_modes`, `oplen_tbl`) have a second failure mode: a
    generator bug that produces *consistently wrong* data could
    hide from a consumer's test if the generator and consumer
    share the wrong assumption.  The guard is that
    `test_asm_line::test_assemble` and `test_dasm` both cross-
    reference every opcode against `dev/instruction_set.py`
    (`instructions(variant)`) — the independent authoritative source
    the generator reads; no test file restates an opcode by hand.  Tables
    are tested against an oracle, not against themselves.  The
    generator's own model (profile placement, row minimality, no
    foreign entries per CPU set) is pinned by
    `tests/unit/test_mnemonic_tables.py`.

    **TDD Maintenance rule.**  Axiomatic modules are not flagged
    as untested.  The per-module tier table below uses `—` in the
    Tier column with a brief note on where coverage lives.  If an
    axiomatic module ever grows behaviour (a runtime helper, a
    computed lookup, anything in a CODE segment), it ceases to be
    axiomatic and gets a test file at that point.

13. **Partial-result contracts need position-pinning tests.**  A
    function whose success value depends on state *other than* its
    return code — the position of an input pointer after a partial
    parse, a side-effect counter, a residual-input marker — must
    have unit tests that pin that ancillary state, not just the
    return code.  Callers composing such a function can only reason
    correctly about it when the partial-result state is both
    documented (module doc) and executable (test file).

    **How this shows up in docs.**  Any function whose contract
    admits "I consumed some of the input" must publish a table of
    stopping positions for representative inputs.  See
    [expr.md § Partial-mode contract](modules/expr.md#partial-mode-contract)
    as the reference template: a short grammar, a stopping-position
    table, a greediness clause.  The prose must explicitly name the
    caller's obligation (here: enforce end-of-input if you wanted a
    complete parse).

    **How this shows up in tests.**  A `TestStopContract` class (or
    equivalent section) parametrises `(input, expected_value,
    expected_ptr_offset)` tuples and asserts all three fields.
    Asserting only `return_code + value` leaves the partial-result
    state under-specified and invites silent-partial-success bugs
    at every caller.

    **Transitive pinning via hot-loop composition** (Pattern C
    subsumption — see Principle 9).  A partial-result function whose
    ancillary state is *consumed in a hot loop* by a higher-level
    test is transitively pinned: the composition can only succeed if
    the advancement is correct on every iteration, so a regression
    in the advancement corrupts every test that walks it.  Examples:
    `expr.skip_sp` and `addr_mode.asm_skip_ws` are pinned by
    `TestStopContract` / `TestModeParseStopContract`'s whitespace-
    surrounding cases; `editor.ed_read_byte` is pinned by
    `test_editor.py::read_back` walking the full gap buffer byte
    by byte.  When a partial-result function is already transitively
    pinned, a direct `TestStopContract` would re-exercise the same
    bytes through a thinner harness without catching additional
    regressions — a vocal skip citing Pattern B (subsumed) with an
    explicit pointer at the hot-loop caller is the correct response.
    The module doc still carries the partial-result clause; only the
    direct unit test is subsumed, not the contract itself.

    Cautionary example (Escape Analysis 2026-04-20): `expr_eval`
    accepted `"1x"` as value `1` and left `expr_ptr` at `'x'`.  This
    is *correct partial-mode behaviour* — assembler-operand callers
    depend on it to parse prefixes like `$10,X`.  But the REPL's `?`
    command, which wanted "one complete expression and nothing
    else," had no way to reason about this because the parser's
    stopping contract was implicit: expr.md mentioned `expr_ptr
    advances past the parsed expression` but never tabulated what
    that meant for `"1x"` vs. `"1+1"` vs. `"1,2"`.  `? 1x` silently
    displayed `$01` for years.  A `TestStopContract` at unit tier
    would have made the contract audit-able at a glance; this
    principle would have forced it to exist.

14. **Enumerated-state introductions enumerate the cross-product.**
    *Applies to projects with enumerated states consumed by multiple
    sites — state machines, dispatch tags, mode flags, error codes.
    Stateless libraries may skip.*

    When a new value is added to an enumerated state, the commit that
    introduces the value must also enumerate the cross-product matrix
    of `consumers × values` and decide every cell explicitly.  Cells
    where the new value behaves identically to an existing one become
    explicit "no change" entries — never implicit fall-through.

    **Why.**  An enumerated state is a contract whose surface area is
    `|values| × |consumers|`.  Adding a value grows the surface in one
    direction only at the doc level, but every consumer silently grows
    in the same direction at the code level — its existing branches
    now have to handle one more case.  Branches that fall through
    by default produce implicit decisions the doc never made and
    tests never assert.

    **How this shows up in docs.**  The owning module doc carries a
    `state × consumer` matrix.  Each cell is one of: a named
    behaviour, "as for value V" (explicit alias), or a vocal "no
    change" with reasoning.  The matrix is updated in the same
    commit as the enum value.

    **How this shows up in tests.**  `@pytest.mark.parametrize` over
    the new value paired with each consumer.  Cells claiming "as for
    V" assert behavioural equivalence; "no change" cells assert the
    pre-existing behaviour still holds.

    Cautionary example (Escape Analysis 2026-04-22): `dbg_reason`
    gained the `DBG_RTS` value (commit fd1c67b) without enumerating
    its interaction with each command consumer (`t`, `o`, `j`, `g`,
    `r`, `a`, `l`, `s`, `R`).  Most commands fell through identically
    to `DBG_BRK`; the one cell that should have differed (`t` /`o`
    after a clean exit) silently looped.  The bug surfaced weeks
    later as user-reported "stepping after a finished program just
    repeats the last instruction."  A 9-row × 5-value matrix in
    debugger.md and a parametrised test would have made the gap a
    failing test in the introduction commit itself.

15. **Display-content and state-content are different contracts.**
    *Applies to projects whose contract surface includes rendered
    output — TUIs, GUIs, REPLs with on-screen panels, stream
    formatters.  Pure libraries returning structured data may skip.*

    `assert state == X` and `assert screen contains Y` exercise
    different code paths.  Any function that produces rendered output
    must have tests for both: the internal state changes AND the
    visible content the user sees.  A test that asserts only one is
    fooled by code that mutates state without rendering, or renders
    without mutating state, or renders into the wrong region.

    **How this shows up in tests.**  For each rendering function,
    pair every state-change assertion with a screen-content
    assertion.  Use the harness's screen-RAM accessor (`C64Emu.scr`
    in CSE) to read the rendered region directly.

    **When the render is implementation detail.**  Per Principle 2
    and the *CDD-Lite for UX* corpus principle ([README.md
    § Principles](README.md)), pixel-level mechanics (cursor
    arithmetic, exact column positions, overwrite sequences) are
    NOT the contract — they belong in code comments.  Display-
    content tests assert the *abstract* visible result ("the panel
    shows the new PC value", "the line begins with `;rts`"), not
    the pixel-level recipe.  When the contract genuinely is
    pixel-level (memory dump column alignment, register-panel
    layout), the doc must promote the pixel layout to an explicit
    interface table — at which point asserting it is asserting a
    contract, not implementation.

    Cautionary example (Escape Analysis 2026-04-22): the DBG_RTS
    classification test
    (`test_clean_rts_classified_as_clean_exit`) asserted internal
    state (`dbg_reason == DBG_RTS`, `brk_pc` correct) but never
    read the rendered debugger panel.  Bug 1 ("`; rts at $<j-target>`"
    instead of the user's `main_addr`) ran the wrong code path
    through the renderer while leaving state correct — and shipped
    silently because the test was state-only.  A paired
    screen-content assertion would have caught it.

16. **Cold-init terminal-state assertion.**  *Applies to projects
    with a fault-recovery path that overlaps cold initialisation
    enough to mask a broken cold-init flow.*

    `_main` (cold init) must reach `main_loop_top` without
    `cse_brk_handler` or `cse_recover` ever being entered.  A
    Tier I test hooks both entry-point addresses and fails if
    either fires during a `_cold_init_to_prompt` run.

    **Why this is its own principle.**  CSE's `cse_recover` runs
    a soft-reset (`hw_reinit_body` + `end_debug_body` +
    `refresh_body`) that overlaps enough of `_main` to produce a
    *working-looking* REPL even when cold init has silently
    faulted partway through.  Without this assertion, a test
    that runs cold init and then asserts post-prompt invariants
    will pass against the recovery state and miss whatever
    `_main` skipped.  This bug class escaped once
    (Phase 24, e47efdf — `ed_ensure_init` ordered before
    `sym_clear` corrupted `$0001`, BRK'd into `cse_recover`,
    suite stayed green for months).

    **How to enforce.**  At Tier I, install address-watchers on
    `cse_brk_handler` and `cse_recover` for the duration of the
    cold-init run.  Per [Principle 7 — Pre-cutover stress
    tests](#principles), this is the kind of overlap-mask check
    that must be added *before* the recovery path is trusted as
    a fallback.

17. **Sequence-prerequisite declaration.**  *Applies to modules
    whose entry points have non-obvious init dependencies on
    sibling modules.*

    A module-level entry point that internally calls into
    another module (transitively or directly) must declare the
    prerequisite in its module doc and pin it with a test if
    any caller could violate it.  "Declared" means the prose
    names the prerequisite explicitly — "X must run after Y has
    initialised" — not just "X is called at cold init."

    Cautionary example (Phase 24): `gap_buffer.s::gb_init`
    tail-called `update_workend` → `sym_define`, an undeclared
    dependency on the symbol table being initialised.
    `_main`'s order swapped `sym_clear` and `ed_ensure_init`,
    triggering `sym_define` against `_st_heap = $0000` and
    corrupting the CPU port.  The fix: make `gb_init` a leaf
    (no symbol-table contact) and lift the workend publication
    to `ed_init`'s wrapper, where the prerequisite is satisfied
    by construction.  General principle: prefer making the
    prerequisite go away over documenting it.

18. **Multi-CPU integration-test parity.**  *Applies to
    projects with multiple production binaries that differ only
    in build flags but exercise distinct memory layouts.*

    At least one Tier I test must run against each production
    PRG variant.  Its job is **coarse**: prove that the boot
    path *executes* on every variant.  When integration
    coverage runs against only one variant, a layout-dependent
    regression that prevents boot on the others is invisible —
    not because the bug is CPU-specific (it usually isn't), but
    because the canonical-target run happens to land on bytes
    that mask the failure.

    **Division of labour with detailed contract tests.**
    Per-target *contract* assertions (specific post-cold-init
    state — symbol resolution, free-region fills, etc.) live
    with the canonical debug target only.  They prevent the bug
    at its source.  The multi-CPU layer doesn't duplicate them —
    it just runs the same boot path on each variant and
    asserts it completed.  Detailed = "did the boot do the
    right things?"; coarse = "did the boot complete at all?"

    Cautionary example (Phase 24): the cold-init bug broke all
    three builds (the heap-corruption root cause was
    CPU-agnostic), but the *manifestation* differed by
    variant — CMOS produced a clean BRK that recovered into a
    working-looking REPL (test passed via fault recovery),
    6510's BASIC-ROM bytes at the affected address didn't
    produce a clean BRK (CPU timed out wandering the ROM),
    6502 was untested.  Multi-CPU smoke coverage would have
    caught the 6510 timeout on day one regardless of which
    contract specifically broke.

    **CSE implementation:** [conftest.py](
    ../tests/conftest.py)'s `cse_prg_per_cpu` fixture
    (params=`["6510", "6502", "cmos"]`) yields the per-variant
    PRG; `test_kernel_transition.py::TestBootsCleanly`
    consumes it.

## Anti-patterns

These exist in the current test tree.  Don't add more of them;
when you touch one of them, consider whether to retire it.

### Mirror tests

A "mirror test" is a Python function that re-implements an
algorithm under test, plus assertions that compare the mirror's
output against expected values.  The trap: the test verifies
the *mirror*, not the ASM.  When the ASM diverges from the
mirror, the test still passes because the mirror is what's
running.

Two cautionary examples from CSE history (the implementations
have since been retired in favour of `C64Emu`-based real-ASM
coverage; the patterns are kept here as descriptions of the
anti-shape):

- **Pure-Python mirror of `editor.s::ed_render_line`.**  A
  `render_line(gb, line_num)` helper re-implemented the
  gap-buffer walk and the PETSCII → screen-code conversion in
  Python, then `TestRendering` asserted its output against
  expected screen rows.  If the real `ed_render_line` changed
  its conversion rule, stopped handling the gap, or read from
  the wrong pointer, the test still passed — because the test
  was running the Python `render_line`, not the ASM.

- **`TestScrollMemmove` mirroring `ed_scroll_up` /
  `ed_scroll_down`.**  Added as a regression test after a
  byte-level memmove bug in `ed_scroll_down` lived undetected
  for months.  The test exercised Python re-implementations
  (`scroll_up_memmove` / `scroll_down_memmove`) of the row-by-row
  copy.  It could not catch the same class of bug because the
  actual ASM memmove never ran under the test.

The right fix for both: load the production PRG into `C64Emu`
and exercise the real `ed_render_line` / `ed_scroll_up` /
`ed_scroll_down` against real screen RAM at `$0400`.  `C64Emu`
provides the KERNAL, screen RAM, and banking — no ASM stubs
needed.  Coverage now lives in
[`tests/integration/test_editor.py`](../tests/integration/test_editor.py).

### Implementation-detail tests

A test that asserts on internal state — a particular ZP byte,
loop counter, intermediate buffer — locks the implementation
to its current shape and prevents legitimate refactoring.

Test contracts.  A contract is what the documented interface
promises: inputs, outputs, side effects on documented state,
return flags, error codes.  Anything else is implementation
detail and the test must not depend on it.

The exception: if the test exists *because* a previous bug was
caused by an internal state slip-up (e.g. a stale accumulator,
a clobbered Y register), and the test is documented as a
regression test for that specific bug, then asserting on the
internal state is fine — but flag it explicitly in the test
docstring so future maintainers know why it looks unusual.

### The TDD Analysis

The TDD Analysis is performed as step 3 of the CDD Method, after
the CDD Analysis and before implementation.  It must:

1. **Identify test gaps** — what existing tests cover the affected
   code, and where are the holes?
2. **Recommend test changes** — new tests to write, existing tests
   to update, obsolete tests to remove.
3. **Assess automation feasibility** — for each change, is automated
   testing practical?  If not, state why and what alternative
   verification is used.
4. **Flag implications** — if the test analysis reveals that the
   intended code change needs adjustment (e.g. an interface must
   change to be testable), this triggers a CDD Feedback Round before
   proceeding.

The TDD Analysis is included in the final CDD Report.

The output of the TDD Analysis — the list of tests to write or
update — feeds directly into Step 4.  Within Step 4, tests are
written first (matching the documentation), then code is written
to pass them.  Tests are the specification in executable form;
they must be green before Step 5 begins.

## Harness limitations

Documented constraints of the `C64Emu` + `py65` harness that put
specific code paths out of reach.  Each entry names the mechanism,
the affected tests, and the recommended skip pattern.

(No entries currently active.  The previous *BASIC ROM shadow
overlap (cold-init resume fragility)* entry was retired
2026-04-27 when Phase 24 fixed the underlying production
cold-init bug; see [TODO.md § Bugs](TODO.md) for the closure
record.)

## Per-module tier assignment

| Module | Layer | Tier | Harness |
|---|---|---|---|
| zp, strings, *_tables, oplen_tbl, dasm_mne_idx | 0 | — | (pure data; generator model tests in `tests/unit/test_mnemonic_tables.py`, `test_dasm_tables.py`) |
| mn_vars | 1 | — | (single-byte ZP scratch; no behaviour) |
| **cse_io** | 1 | U | standalone leaf bundle |
| **mem** | 1 | U | standalone leaf bundle |
| **mn6 / mn7 / mn_classify** | 1 | U | `mn6` / `mn7` bundles |
| **screen** | 2 | I | hardware-adjacent by nature (VIC registers, KERNAL cursor sync); C64Emu is the natural home even though it doesn't model VIC internals |
| **log** | 2 | U | bundle: log + screen + cse_io (PLOT via shared `kplot_stub`) |
| **symtab** | 2 | U | bundle: symtab + mem |
| **asm_err** | 2 | U | bundle: asm_err + mem |
| **expr** | 3 | U | via `asm_core` bundle |
| **opcode_lookup** | 3 | U | via `asm_core` bundle |
| **addr_mode** | 3 | U | via `asm_core` bundle (`test_addr_mode.py`) |
| **asm_line** | 3 | U | `asm_core` bundle |
| **dasm** | 3 | U | `dasm` bundle |
| **breakpoints** | 3 | U | standalone `breakpoints` bundle — BP-table CRUD (extracted from debugger.s at the 2026-04-20 split) |
| **gap_buffer** | 3 | U | standalone `gap_buffer` bundle — gap-buffer primitives + sequential reader (extracted from editor.s at the 2026-04-20 split) |
| **debugger** | 4 | I | step/BRK state + userland-transition gates; BP-table CRUD now lives in `breakpoints` at L3 |
| **asm_src** | 4 | U | `asm_src` bundle |
| **disk** | 4 | I | needs KERNAL LOAD/SAVE/CHKIN |
| **editor** | 4 | I | observable behaviour goes through screen RAM + keys; gap-buffer primitives now live in `gap_buffer` at L3 |
| **repl / main** | 5 | I | Layer-5 cycle; only testable full-PRG |
| **loader** | 6 | I | exercised implicitly by C64Emu `load_prg` |

## Framework

All tests use **pytest**.  The test tree is split into two directories
reflecting the tier boundary:

```
tests/
├── c64emu.py                    — emulator harness
├── conftest.py                  — bundle fixtures + cse_prg fixture
├── unit/                        — Tier U tests (bare MPU + bundles)
└── integration/                 — Tier I tests (C64Emu + full PRG)
```

Unit-tier tests load a small bundle binary (module + its
linking-down closure + a stub for linker scaffolding) into a bare
`py65.MPU`.  No KERNAL, no banked memory, no interrupts — just the
module's code + its data.

Integration-tier tests load the debug CMOS PRG
(`build/debug/cmos/cse-cmos.prg`) into `C64Emu` and call into any
function by its `.lbl`-file address.  Debug builds include `-g`
symbols, so the `.lbl` file contains all labels (~1800 symbols)
rather than just exports (~230).  For build details see
[build_system.md § Test build pipeline](build_system.md#test-build-pipeline).

### C64Emu — emulator class

`C64Emu` is a single class used by every test fixture.  What it shares
with `M65Emu` — the run loops, the interrupt scheduler and jiffy tick,
the keyboard matrix, `load_prg()`, `set_cursor()`, `init_cse()` — lives
in `tests/emu_base.py`
([§ M65Emu, Interface](#m65emu--the-m65-integration-harness)).  It provides
a 6502 CPU, 64 KB RAM, the original C64 KERNAL ROM at $E000–$FFFF,
and just enough C64 hardware modelling to run CSE code under py65.

#### Construction

```python
from c64emu import C64Emu

emu = C64Emu()          # default: KERNAL loaded, screen cleared
```

On construction:

- 64 KB RAM zeroed.
- Original C64 KERNAL ROM (`rom/kernal_cbm.bin`) loaded as a ROM
  overlay at $E000–$FFFF.
- Processor port: DDR (`$00`) = `$2F`, `$01` = `$36` — CSE's runtime
  banking: BASIC out (`$A000`–`$BFFF` is RAM), KERNAL and I/O in.
- Bank-switch emulation: writes to $01 toggle the KERNAL ROM
  overlay — clearing bit 1 exposes the underlying RAM at
  $E000–$FFFF (used by `mem.s::kernal_bank_out`); setting it
  restores the ROM image.
- Screen RAM ($0400–$07E7) filled with $20 (space).
- Color RAM ($D800–$DBE7) filled with $01 (white).
- KERNAL ZP state initialised: cursor at row 0 col 0, screen line
  pointers ($D1/$D2, $F3/$F4) set for row 0, cursor disabled
  ($CC = 1), text colour ($0286) = $01, keyboard buffer empty
  ($C6 = 0).
- CPU stack pointer at $FF.

The KERNAL is **not** initialised via the reset vector — ZP state
is set up directly.  This avoids the KERNAL init routine's
hardware probing (VIC-II, CIA) which has no effect in py65.

#### Execution

```python
cycles = emu.jsr(addr, a=0, x=0, y=0, max_cycles=500_000)
```

`jsr(addr)` simulates a JSR to `addr`:

1. Pushes a sentinel return address onto the stack.
2. Sets A/X/Y from keyword arguments, sets PC = `addr`.
3. Steps the CPU until PC reaches the sentinel address.
4. Returns the cycle count.
5. Raises `TimeoutError` if `max_cycles` is exceeded (reports
   the stuck PC).

After `jsr()` returns, the CPU registers and memory are
available for assertions:

```python
assert emu.a == 0x42
assert emu.memory[result_addr] == expected
assert emu.carry                # carry flag
```

#### Register accessors

`emu.a`, `emu.x`, `emu.y`, `emu.sp`, `emu.p` — read/write CPU
registers.  `emu.carry`, `emu.zero`, `emu.negative`,
`emu.overflow` — read/write individual status flags.
`emu.pc` — program counter.  `emu.memory` — the 64 KB
address space (with bank-switching applied transparently).

#### Keyboard injection

```python
emu.inject_key(petscii_byte)    # enqueue one byte at $0277+
emu.inject_keys(b"HELLO\r")    # enqueue a string
```

Writes to the KERNAL keyboard buffer ($0277–$0280) and
increments $C6.  Used by tests that exercise `GETIN`-based
input (cse_io.s `io_kbhit`, REPL `read_line`).

#### PRG loading

```python
emu = C64Emu()              # KERNAL + screen ready
emu.load_prg("build/cse.prg")   # load production binary
```

`load_prg(path)` reads a `.prg` file (2-byte load-address header
+ payload), writes the payload at the load address, loads every
symbol of the `.lbl` file beside the companion `.map`, and copies
each relocated segment to its run address (shared with M65Emu:
[§ M65Emu, Interface](#m65emu--the-m65-integration-harness)).
Symbols are looked up by name:

```python
addr = emu.sym("_asm_line_core")      # look up any exported symbol
```

Since the full production binary is loaded, every module's real
code satisfies every import — no ASM stubs are needed for
inter-module dependencies.  The emulator + real KERNAL provide
the hardware environment (PLOT, GETIN, screen RAM, banking).

Application-level test setup (writing input buffers, pre-loading
symbols, preparing gap-buffer content) is done from Python by
writing directly to memory at the symbol's address.

### SymbolTable — encapsulated symbol resolution

All symbol lookups — in conftest bundles, leaf module tests, and
C64Emu integration tests — go through the `SymbolTable` class in
`conftest.py`.  Test code accesses symbols by name and never
touches file formats, paths, or parsing logic:

```python
from conftest import SymbolTable

s = SymbolTable(lbl_path)
addr = s["mode_parse"]       # KeyError with helpful message if missing
addr = s.get("sym_wide")     # None if missing
"bar" in s                   # membership test
```

`SymbolTable` parses ld65 `.lbl` files (VICE label format).  All
test binaries are assembled with `ca65 -g` and linked with
`ld65 -Ln`, so the `.lbl` file contains every label — exported,
module-internal, and `@local` — at absolute addresses.  No
map-file regex, no listing-file segment offsets, no BSS arithmetic.

### conftest.py — fixtures and auto-rebuild

`conftest.py` provides session-scoped fixtures that auto-build
test binaries when sources change.

**Test bundle architecture.**  Interdependent modules are linked
into a single "bundle" test binary rather than per-module binaries
with expanding mock stubs.  True leaf modules (zero or few imports)
get their own small binary.

#### conftest bundles

| Bundle | Modules | Stub | Tests |
|--------|---------|------|-------|
| `asm_core` | zp, opcode_lookup, asm_line, addr_mode, asm_err, expr, symtab, mem, mn7, mn_classify, mn_modes, mn_asm_tables | `asm_core_test_stub.s` (linker symbols) | test_addr_mode, test_asm_line, test_opcode_lookup |
| `mn6` / `mn7` | mn_classify + mn_vars + mn6/mn7 + tables | (none — pure leaf) | test_mn_classify |
| `asm_src` | asm_core + asm_src | `asm_src_test_stub.s` (ed_read_line mock) | test_asm_src |
| `dasm` | zp, dasm, dasm_tables, mem | `dasm_test_stub.s` (linker scaffolding only) | test_dasm |

**Variants (Principle 10).**  Each bundle ships one variant per CPU
set its modules are built for: `asm_core` and `dasm` — `6502`,
`6510`, `65c02`, `m65`; `mn6` — `6502`; `mn7` — `65c02` (C64 keys),
`m65`; `asm_src` and `symtab` — `65c02`, `m65` (the `m65` variant
carries the pass stamp: `sym_stamp`, `sym_fwd`, `expr_fwd`).  Each
variant is named after its CPU set (the generator's `CPU_SETS`) and
uses the production `-D` set of its build (`conftest.PROD_DEFS`;
[build_system.md § Builds and CPU sets](build_system.md#builds-and-cpu-sets)).
One `conftest.Bundle` builds every variant and rebuilds it when a
source, the linker config or the `-D` set changed.
| `log` | zp, strings, cse_io, screen, log | `cse_io_test_stub.s` (shared `kplot_stub`) | test_log |

The `asm_core` bundle includes the `asm_err` leaf module for
error-state primitives that `addr_mode`, `opcode_lookup`, and
`asm_line` share.

The bundle principle: when adding a cross-module dependency, add
the module to the existing bundle rather than creating new mocks.
Only create a new bundle when the dependency graph forks into a
genuinely separate subsystem.

#### Shared slim mocks

The stubs listed in the tables above are almost all pure linker
scaffolding (`__CODE_RUN__`, BSS buffers, test entry points) — no
behavioural substitution for real modules.  One exception is
sanctioned: **`cse_io_test_stub.s` exposes `kplot_stub`, a short
functional replacement for KERNAL `$FFF0` (PLOT)** using cse_io's
own `scr_lo` / `scr_hi` tables.  py65 has no KERNAL ROM, so every
Tier U bundle that exercises `io_sync` (directly or transitively)
must supply PLOT from somewhere.  Giving each bundle its own inline
re-implementation would violate Principle 5 (mock scope) — instead
all bundles that need PLOT link the shared `cse_io_test_stub.s`
and patch `$FFF0 → kplot_stub` at setup time.

Policy:
- Behavioural mocks are *exceptional* and must be *shared* — one
  implementation in `dev/`, linked into every bundle that needs it.
- Each behavioural mock is documented here with its justification
  (why an inline replacement is necessary, what production behaviour
  it replicates).
- A mock that drifts from production behaviour is a bug; the
  `kplot_stub` tracks PLOT's CLC-set / SEC-get contract exactly,
  using cse_io's production row-address tables so mock/prod
  divergence is structurally impossible.
- New mocks require explicit sign-off via CDD Method (contract
  clause + test policy change).  Not an ad-hoc decision.

#### Leaf module tests

Well-encapsulated leaf modules — those with zero or near-zero
cross-module dependencies — build their own test binaries inline.
The stub provides only linker-required scaffolding (banking
helpers, BSS buffers), not reimplementations of other modules.

| Test file | Module | Stub | Why leaf |
|-----------|--------|------|----------|
| `test_cse_io.py` | cse_io.s | `cse_io_test_stub.s` | Zero imports |
| `test_symtab.py` | symtab.s | `symtab_test_stub.s` | Only banking helpers |
| `test_debugger.py` | debugger.s | `debugger_test_stub.s` | Only register BSS buffers |

Leaf tests build with `ca65 -g` + `ld65 -Ln` and use `SymbolTable`
for all symbol lookups — the same encapsulation as conftest bundles.

Complex modules with substantive production dependencies should NOT
build standalone test binaries.  They belong in a conftest bundle
(if they share an import graph with existing bundles) or in C64Emu
integration tests (if they depend on most of the codebase).

**TODO:** migrate test_expr.py to the asm_core bundle (expr.s is
already linked there) and test_repl.py to C64Emu integration
(repl.s is the central hub with 8+ subsystem dependencies).

**test_repl.py witness resolution:** Disk I/O witness addresses
(`save_addr`, `save_size`, `load_result`) are resolved from the
stub's RODATA `sym_refs` table (slots 11–13), not from hardcoded
BSS offsets.  The old `stub_bss + 185` pattern broke whenever BSS
layout changed.  All stub-local addresses should be resolved via
the `sym_refs` table or via `SymbolTable` when the test migrates
to C64Emu.

### Running a test

```python
def test_something(cse):
    emu = C64Emu()
    cse.load_into(emu)
    emu.memory[emu.sym("asm_ptr")]     = lo
    emu.memory[emu.sym("asm_ptr") + 1] = hi
    emu.jsr(emu.sym("_asm_line_core"))
    assert emu.a == expected
```

Functions under test end with `rts` which returns to the sentinel
address pushed by `jsr()`, halting the emulation loop.

### Conventions

- **PETSCII encoding:** Test inputs use a `_petscii()` helper that
  converts Python strings to C64 PETSCII (lowercase → $41-$5A
  uppercase).

- **ca65 character literals:** With `-t c64`, ca65 maps character
  literals to PETSCII (`'a'` = $41, not $61).  Without `-t c64`,
  literals use ASCII (`'a'` = $61).  **Use numeric constants**
  (`$41`, `$61`) for PETSCII values in code shared across both
  build modes.  The asm_core bundle builds without `-t c64`.

- **Auto-rebuild:** `conftest.py` invokes `make debug` (or
  `make release`) which handles dependency tracking.  PRGs are
  cached in `build/debug/` and `build/release/`.

- **xfail:** Known limitations (e.g. CMOS gate bugs) are marked
  `pytest.mark.xfail` with a reason string.

- **KERNAL ROM:** Tests require the original C64 KERNAL ROM at
  `rom/kernal_cbm.bin` (copied from a local VICE installation; not
  committed to the repository — see `.gitignore`).  Run `make test`
  for instructions if the ROM is missing.
