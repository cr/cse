# main.c — Application Shell

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/main.c`](../../src/main.c) | implementation |
| [`src/cse.h`](../../src/cse.h) | header — shared project-wide declarations |

## Interface

- `main()` — hardware init, main loop, mode dispatch
- `hex_val(ch)` — hex digit → 0–15 or $FF
- `hex_val_to_char(v)` — 0–15 → '0'–'f'
- `is_hex(ch)` — true if hex digit
- `parse_hex4(ptr)` / `parse_hex2(ptr)` — parse 4/2 hex digits from string
- `skip_sp(ptr)` — advance past spaces

**Globals:**
- `state` — 0=STOP, 1=REPL, 2=EDIT
- `SCREEN` — $0400
- `nmi_pending` — set by NMI handler, checked in main loop
- `src_top` / `src_bot` — source region boundaries

**Depends on:** repl, editor, screen, cse_io

## Design

Startup: disable BASIC ROM, init screen, install NMI handler, set
all-keys-repeat, fill free RAM with $FF, enter REPL loop.

Main loop: `io_getc()` → dispatch to `ed_handle_key()` (editor mode)
or `exec_line()` / `show_prompt()` (REPL mode).  RUN/STOP triggers
NMI which sets `nmi_pending`; main loop checks the flag and toggles
mode.

Exit (`q`): JMP $FCE2 (KERNAL cold start).  Restores BASIC.

## Keyboard

The main loop reads keys via `io_getc()` and dispatches based on the
current mode.  Some keys are handled globally (before mode dispatch),
others are mode-specific.

### Global keys (both modes)

| Key | Action |
|-----|--------|
| RUN/STOP | Toggle REPL ↔ editor (via NMI: sets `nmi_pending`, main loop checks flag) |

### REPL mode keys

| Key | Action |
|-----|--------|
| Printable characters | Insert at cursor (line editor rules, see [repl.md](repl.md)) |
| Cursor keys | Move within screen (no wrap, no scroll) |
| RETURN | Execute line at cursor row |
| DEL | Left-delete (shift content left, space fills from right) |
| INS | Right-shift (space opens at cursor) |
| HOME | Cursor to top-left |
| Shift+HOME | Clear screen, show prompt |
| ESC | Clear screen, show prompt |

### Editor mode keys

Handled by `ed_handle_key()`.  See [editor.md](editor.md).

## Caveats

- `hex_val` / `parse_hex*` / `skip_sp` are used by repl.c but defined
  in main.c.  These are general-purpose helpers, not main-loop logic.
- NMI handler lives in cse_io.s, not main.c.  main.c only installs
  the vector and checks the flag.
