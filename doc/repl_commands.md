# CSE REPL Command Reference

## CLI Philosophy

The screen IS the command buffer. Every line is executable. Press RETURN
on any line to execute it from column 0 until `;` or end of line.

Line format: `AAAA:cmd [args]` for addressed commands, `cmd [args]` for
bare commands. The `AAAA:` prefix sets the current address.

Commands that modify memory update their screen line in-place to reflect
the result. Auto-advance pre-fills the next line at the continuation
address, ready for RETURN.

`;` ends parsing (inline comments). RETURN on an empty prompt repeats
the last repeatable command at the current address.

## Line Formats (40 columns)

    AAAA:. BB BB BB MNEMONIC OPERAND       asm / disasm
    AAAA:m BB BB BB BB BB BB BB BB cccccccc hex dump / edit
    r A:XX X:XX Y:XX S:XX NV-BDIZC         CPU registers

## Commands — Memory (block-size-aware)

| Key | Name     | Addressed | Example                     | Notes                                      |
|-----|----------|-----------|-----------------------------|----------------------------------------------|
| `m` | memory   | yes       | `1000:m` dump, `1000:m A9 00...` edit | Bare = dump `b` bytes; with hex = edit   |
| `f` | fill     | yes       | `1000:f EA`                 | Fill `b` bytes with value                    |
| `t` | transfer | yes       | `1000:t 2000`               | Copy `b` bytes from AAAA to arg              |
| `c` | compare  | yes       | `1000:c 2000`               | Compare `b` bytes, show diffs                |
| `h` | hunt     | yes       | `1000:h A9 00`              | Search for byte pattern from AAAA            |

## Commands — Assembly / Disassembly

| Key | Name       | Addressed | Example              | Notes                                        |
|-----|------------|-----------|-----------------------|----------------------------------------------|
| `.` | asm/disasm | yes       | `1000:. lda #$00`    | Single instruction; smart detect hex vs mne  |
| `d` | disassemble| yes       | `1000:d`              | Disassemble `b` bytes                        |
| `a` | assemble   | yes       | `1000:a`              | *Future:* 2-pass assembly mode               |

## Commands — Execution

| Key | Name | Addressed | Example    | Notes                                         |
|-----|------|-----------|------------|-----------------------------------------------|
| `j` | JSR  | yes       | `1000:j`   | Call address, returns via RTS; shows registers |
| `g` | go   | yes / bare| `1000:g`   | JMP (no return), or bare `g` = continue from BRK |

## Commands — Debug / Trace

| Key | Name      | Addressed | Example         | Notes                                    |
|-----|-----------|-----------|-----------------|------------------------------------------|
| `n` | next      | bare      | `n` or `n 5`    | *Future:* Step 1 (or N) instructions     |
| `o` | step over | bare      | `o`              | *Future:* Skip into JSR                  |
| `!` | breakpoint| yes / bare| `1000:!` toggle  | Bare `!` = list all breakpoints          |
| `r` | registers | bare      | `r` or `r a:05...` | View / edit CPU registers             |

## Commands — Navigation

| Key | Name    | Type | Example    | Notes                                       |
|-----|---------|------|------------|---------------------------------------------|
| `s` | seek    | bare | `s C000`   | Set current address                          |
| `b` | block   | any  | `b 40`     | Set block size (hex bytes); bare = show      |
| `+` | forward | bare | `+` or `+20` | Advance cur_addr by block_size (or arg)   |
| `-` | back    | bare | `-` or `-20` | Retreat cur_addr by block_size (or arg)   |

## Commands — I/O

| Key | Name   | Type | Example              | Notes                                   |
|-----|--------|------|----------------------|-----------------------------------------|
| `l` | load   | bare | `l "file",8`         | Load PRG file                            |
| `w` | write  | yes  | `w "file",8,1000,2000` | Save memory range to file             |
| `$` | disk   | bare | `$` dir, `$ 9` drive 9 | Directory; may send drive commands    |
| `@` | doscmd | bare | `@ s:file`           | Send command to drive command channel    |

## Commands — Labels / Symbols (future, for 2-pass assembler)

| Key | Name   | Addressed | Example        | Notes                                  |
|-----|--------|-----------|----------------|----------------------------------------|
| `=` | label  | yes       | `1000:= loop`  | Define symbolic label at address        |
| `/` | search | bare      | `/loop`         | Search for label or text                |

## Commands — Utility

| Key   | Name  | Type | Example         | Notes                                    |
|-------|-------|------|-----------------|------------------------------------------|
| `?`   | help  | bare | `?` or `? 1000+20` | Help, or hex expression calculator   |
| `q`   | quit  | bare | `q`              | Exit CSE                                 |
| `clr` | clear | bare | `clr`            | Clear screen                             |

## Reserved / Free Keys

Currently unassigned, available for future use:

    e   editor mode (source buffer)
    i   info / inspect
    k   (free)
    p   print / evaluate
    u   (free)
    v   visual mode (split screen?)
    x   (free — alt quit?)
    y   (free)
    z   (free)
    #   (free)
    >   (free)
    <   (free)
    *   current address in expressions

## Block Size

The `b` command sets a 16-bit block size used by: `m`, `d`, `f`, `t`,
`c`, `h`, and `+`/`-` navigation. Default: `$0010` (16 bytes = 2 hex
dump lines).

    b 40     set to 64 bytes (8 hex lines)
    b C0     set to 192 bytes (full screen of hex)
    b 0100   set to 256 bytes (4-digit)
    b        show current block size

## Auto-advance / Repeat

Commands that naturally page (`m`, `d`) update `cur_addr` to the
continuation point. RETURN on an empty prompt repeats the last
repeatable command at the new address.

Single-instruction commands (`.`) auto-advance by writing the next
instruction line below, ready for immediate editing or RETURN.

## Implementation Status

    [x] .   asm/disasm single instruction
    [x] d   disassemble block
    [x] m   memory dump / edit
    [x] j   JSR to address
    [x] r   registers view / edit
    [x] s   seek
    [x] b   block size (was bs)
    [x] $   directory listing
    [x] q   quit
    [x] clr clear screen
    [ ] g   go / continue
    [ ] n   step next
    [ ] o   step over
    [ ] !   breakpoints
    [ ] f   fill
    [ ] t   transfer
    [ ] c   compare
    [ ] h   hunt
    [ ] l   load
    [ ] w   write / save
    [ ] @   disk command
    [ ] a   2-pass assembler
    [ ] =   labels
    [ ] /   search
    [ ] ?   help / calculator
    [ ] +   seek forward
    [ ] -   seek backward
