# main.s — Application Shell

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/main.s`](../../src/main.s) | implementation (6502 assembly) |

## Interface

- `_main` — initialization + main loop (jumped to by `loader.s`
  after relocation, BSS zero, KDATA copy)
- `state` — exported BSS byte: 0=STOP, 1=REPL, 2=EDIT

**Depends on:** repl, editor, screen, cse_io, debugger, symtab,
disk, mem

### Memory

**ZP (6 bytes):** `rp_ptr` (2), `rp_ptr2` (2), `rp_tmp` (1),
`rp_tmp2` (1) — scratch pointers/bytes shared by repl.s,
debugger.s, asm_bridge.s.

**BSS (1 byte):** `state` (1) — run mode (ST_STOP=0, ST_REPL=1,
ST_EDIT=2).

## Design

Startup (`startup` segment):
1. Reset SP to `$FF` so BASIC's SYS residue is wiped.  CSE
   never returns to BASIC; the main loop is `jmp`-based and
   `@exit` halts.  See [memory_design.md § Stack budget](../memory_design.md#stack-budget).
2. Zero BSS.
3. Copy the KDATA segment (mnemonic / dasm tables) from the
   PRG load area to RAM under KERNAL at `$F100`.  Pure-writer
   path — no banking required.
4. `jmp _main`.

Main init (`_main`):
1. Enable key repeat for all keys (`KEY_REPEAT |= $80`).
2. Disable BASIC ROM (clear bit 0 of `$01`).
3. Init `state`, `cur_device`, `block_size`.
4. `io_init` (disables KERNAL cursor, IRQ-safety invariant).
5. `theme_init` (copy build-time theme defaults to BSS — see
   [screen.md](screen.md)).
6. `reset_screen`, set lowercase charset, `kernal_init`
   (NMI trampoline + KDATA banking flag).
7. `ed_ensure_init` (initialize the gap buffer; required
   *before* `define_ws_syms` because `workend` reads
   `buf_base`).
8. `sym_clear`, `define_ws_syms`, `dbg_init`.
9. Splash, prompt, enter the main loop.

Main loop:
1. `io_getc` → into `@key`.
2. NMI check first (priority over keypress): if `nmi_pending`,
   leave any active editor session, switch to REPL, print the
   `; nmi break` banner, show prompt, loop.
3. RUN/STOP key (`CH_STOP=$03`) toggles REPL ↔ editor by
   calling `enter_editor` / `leave_editor`, then debounces
   the key (waits for release at `$91` and drains queued
   repeats from `$C6`).
4. In editor mode, dispatches the key to `ed_handle_key`.
5. In REPL mode, handles RETURN, DEL, INS, cursor keys, HOME,
   CLR/ESC, and printable characters directly.  Refused keys
   (cursor off-screen, DEL before the AAAA: prompt, etc.)
   route through `@reject` which calls `io_blip` then loops.

Exit (`q` or `state == ST_STOP`): `jmp $FCE2` (KERNAL cold
start).  This re-initializes the C64 to BASIC; CSE memory is
overwritten.

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
- NMI handler lives in cse_io.s.  main.s installs the vector
  and checks the `nmi_pending` flag (owned by cse_io.s).
- `src_top`/`src_bot` are owned by editor.s.
- `ed_ensure_init` is called at startup to initialize the gap
  buffer before `define_ws_syms` (workend needs `buf_base`).
