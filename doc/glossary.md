# CSE Glossary

All terms are used consistently across source code, comments, tests,
and documentation.

## User-facing

| Term | Definition |
|------|------------|
| **REPL** | Read-eval-print loop.  CSE's command-line mode.  The screen is the command buffer. |
| **editor** | Full-screen source code editor.  RUN/STOP toggles between REPL and editor. |
| **block size** | Number of bytes operated on by `m`, `d`, `f`, `t`, `h`, `+`, `-`.  Set by `b`. |
| **block edit** | Workflow: dump a block (`d`/`m`), cursor to a line, edit in-place, RETURN. |
| **cur_addr** | The REPL's current address.  Set by `AAAA:` prefix; advanced by commands. |

## Source language

| Term | Definition |
|------|------------|
| **instruction** | A complete assembler statement: `mnemonic [operand]`. |
| **mnemonic** | The 3-letter instruction name: `LDA`, `BBR`, `NOP`, etc. |
| **operand** | Everything after the mnemonic: encodes addressing mode and value.  Example: `($D0,X)`. |
| **addressing mode** | The syntactic form of the operand: how the CPU locates the data.  Example: "zero-page indexed X" means `$XX,X`. |
| **expression** | A numeric value: literal, symbol, label, or arithmetic combination.  Example: `BASE+$20`. |
| **literal** | A numeric constant in source: `$D020`, `255`, `%11001000`. |
| **symbol** | A named constant: `.const name expr`.  Has a **value**. |
| **label** | An address marker: `name:`.  Has a **slot** (the LC at the point of definition). |
| **local label** | Dot-prefixed label (`.loop:`), scoped to the last preceding global label.  Stored as `global.local`. |
| **directive** | Pseudo-instruction controlling assembly state, not emitting a CPU opcode: `.org`, `.db`, `.cpu`, etc. |
| **forward reference** | Use of a symbol or label before its definition.  Resolved in pass 1. |

## Assembler internals

| Term | Definition |
|------|------------|
| **LC (location counter)** | The assembler's current output address.  Set by `.org`; advanced by every emitted byte. |
| **pass 0** | First scan: collect labels/constants, compute instruction sizes.  Errors not counted. |
| **pass 1** | Second scan: all symbols resolved; emit bytes, count errors. |
| **ZP** | Zero-page: address $00–$FF.  Selects 2-byte instruction encoding. |
| **ABS** | Absolute: address $0000–$FFFF.  Selects 3-byte instruction encoding. |
| **wide** | `expr_wide = 1`: expression forced to ABS.  Sticky — once wide, stays wide. |
| **base opcode** | Opcode byte with the mode field (`bbb`) zeroed.  Final opcode = `base | (bbb << 2)`. |
| **mode index** | Integer 0–15 encoding an addressing mode.  Used by `au_mode.s` and `opcode_lookup.s`.  The mapping: 0=IMP, 1=ACC, 2=IMM, 3=ZP, 4=ZPX, 5=ZPY, 6=ABS, 7=ABX, 8=ABY, 9=IND, 10=INX, 11=INY, 12=REL, 13=ZPI, 14=AIX, 15=ZPREL. |
| **operand profile** | Index (0–29) describing which mode indices a mnemonic accepts.  Encoded as a 16-bit bitmask in `mn_modes`.  Example: profile 16 (LDA) = {IMM, ZP, ZPX, ABS, ABX, ABY, INX, INY}. |
| **zone** | Dispatch category (A–H) in the line assembler.  Derived from the operand profile.  Zones A–F are fixed single-mode groups; G and H are multi-mode groups that call `au_parse_mode` + `opcode_lookup`. |
| **mnemonic suffix** | Digit `0`–`7` after RMB/SMB/BBR/BBS: the `3` in `RMB3`.  Encodes a bit index. |

## Encoding

| Term | Definition |
|------|------------|
| **PETSCII** | C64 character encoding.  Uppercase A–Z = $41–$5A.  Used in source text, file I/O, strings. |
| **VICII screen code** | Display encoding for screen RAM.  A=$01..Z=$1A (1-based).  Used internally by the line assembler. |
| **shifted PETSCII** | Alternate character set: uppercase A–Z = $C1–$DA.  Folded to $41–$5A by `fold_char`. |
| **screen RAM** | $0400–$07E7.  40×25 bytes of screen codes.  The REPL reads and writes this directly. |
| **color RAM** | $D800–$DBE7.  Per-character color nybbles.  Managed by `restore_colors`. |

## Hardware

| Term | Definition |
|------|------------|
| **KERNAL** | C64 ROM routines ($E000–$FFFF).  CSE uses KERNAL for keyboard, disk I/O, and cursor sync. |
| **NMI** | Non-maskable interrupt.  RUN/STOP+RESTORE triggers NMI; CSE intercepts it for mode switching. |
| **al_cpu** | CPU mode selector: 0=6502 (legal only), 1=6510 (+illegal), 2=65C02 (+CMOS). |
| **cc65** | C compiler for 6502.  CSE's C modules are compiled with cc65; assembly uses ca65. |
| **py65** | Python 6502 emulator used by the test suite to execute assembled test binaries. |
