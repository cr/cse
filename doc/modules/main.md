# main.s — Application Shell

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/main.s`](../../src/main.s) | implementation (6502 assembly) |

## Interface

- `_main` — entry point (jumped to by `loader.s` after
  relocation, BSS zero, KDATA copy).  Contains three layers:
  `cse_cold_init`, `cse_warm_start`, and `main_loop`.
- `state` — exported BSS byte: 0=STOP, 1=REPL, 2=EDIT

**Interrupt handlers (owned by main.s):**
- `cse_brk_handler` — permanent BRK dispatcher at $0316/$0317
- `cse_nmi_handler` — permanent NMI dispatcher at $0318/$0319
- `cse_basic_warm_hook` — BASIC warm-start intercept at $0302/$0303

**Depends on:** repl, editor, screen, cse_io, debugger, symtab,
disk, mem

### Memory

**ZP (6 bytes):** `rp_ptr` (2), `rp_ptr2` (2), `rp_tmp` (1),
`rp_tmp2` (1) — scratch pointers/bytes shared by repl.s,
debugger.s, asm_line.s.

**BSS (1 byte):** `state` (1) — run mode (ST_STOP=0, ST_REPL=1,
ST_EDIT=2).

**KBSS (cold-init snapshots, under KERNAL ROM):**
- `_cold_zp` (127 B) — snapshot of $01-$7F at cold-init entry
- `_cold_vectors` (6 B) — snapshot of $0302-$0303, $0316-$0317,
  $0318-$0319 at cold-init entry

## Design

### Three-layer architecture

#### Layer 1: `cse_cold_init` (one-time setup)

Runs once after `loader.s` jumps to `_main`.  Saves $01-$7F
and vectors to KBSS, unmaps BASIC ROM, inits all subsystems,
fills free memory, installs permanent hooks, draws splash,
then jumps directly to `main_loop`.

#### Layer 2: `cse_warm_start` (idempotent recovery)

Reachable from `cse_brk_handler` (internal fault) and
`cse_basic_warm_hook`.  Must NOT depend on previous state.
Resets SP, restores $01=$36, reinstalls hooks, calls `dbg_init`,
resets globals, reinits I/O/theme/colors/charset, falls through
to `cse_warm_screen`.

`cse_warm_screen` — secondary entry point (screen recovery):
clears screen, draws prompt, falls through to `main_loop`.
Used by ESC/CLR key, NMI-in-REPL, and warm-start tail.

Cold init draws the splash then jumps directly to `main_loop`,
bypassing `cse_warm_screen` (which would clear the splash).

| Entry point | Used by | Severity |
|-------------|---------|----------|
| `cse_warm_start` | `cse_brk_handler` (CSE fault), `cse_basic_warm_hook` | Hard recovery |
| `cse_warm_screen` | ESC/CLR key, NMI-in-REPL, warm-start tail | Screen recovery |

#### Layer 3: `main_loop` (event loop)

Reads keys via `io_getc`, dispatches based on mode (NMI check,
RUN/STOP toggle, editor keys, REPL keys).

### Permanent hooks

| Vector | Address | Hook | Purpose |
|--------|---------|------|---------|
| IMAIN | $0302/$0303 | `cse_basic_warm_hook` | Intercept BASIC warm start |
| IBRK | $0316/$0317 | `cse_brk_handler` | Unified BRK dispatch |
| INMIV | $0318/$0319 | `cse_nmi_handler` | Unified NMI dispatch |

### Exit path

`cse_exit_to_basic` restores vectors and $01-$7F from KBSS
snapshots, then `jmp ($0302)` (BASIC warm start).

### Splash screen

Shows zp, lo02, lo03, and work free ranges at startup.

## Keyboard

The main loop reads keys via `io_getc()` and dispatches based on the
current mode.  Some keys are handled globally (before mode dispatch),
others are mode-specific.

### Global keys (both modes)

| Key | Action |
|-----|--------|
| RUN/STOP | Toggle REPL ↔ editor (handled inline in the main loop, with key-release debounce so holding it only toggles once) |
| RUN/STOP+RESTORE | NMI break — handled by the NMI trampoline which sets `nmi_pending`; main loop checks the flag and forces REPL mode |

### REPL mode keys

| Key | Action |
|-----|--------|
| Printable characters | Insert at cursor.  Refused (audible blip) at col 39. |
| Cursor keys | Move within screen, no wrap.  Refused (audible blip) at the screen edges. |
| RETURN | `read_line` the cursor row, `exec_line`, `show_prompt` |
| DEL | Backspace, shifting row left.  Refused at col 0, or at or before col 5 of an `AAAA:cmd` row. |
| INS | Right-shift the row, opening a space at the cursor |
| HOME | Cursor to col 0 of current row |
| Shift+HOME / ESC | `reset_screen` + `show_prompt` |

### Editor mode keys

Handled by `ed_handle_key()`.  See [editor.md](editor.md).

## Caveats

- Hex parsing helpers (`hex_val`, `parse_hex*`, `skip_sp`) are
  local to repl.s.
- NMI and BRK handlers live in main.s.  `nmi_pending` BSS flag
  remains in cse_io.s (main.s imports it).
- `src_top`/`src_bot` are owned by editor.s.
- `ed_ensure_init` is called at startup to initialize the gap
  buffer before `define_ws_syms` (workend needs `buf_base`).
- `cse_warm_start` must not call `leave_editor` — editor state
  may be corrupt.
