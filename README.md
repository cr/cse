# CSE Assembler — Two-Pass Design

Single-file, flat, `.org`-based 6502/6510 assembler.  No linker, no segments.

---

## Terminology

All terms below are used consistently across source code, comments, tests, and documentation.

### Source-level constructs

| Term | Definition |
|---|---|
| **instruction** | A complete assembler statement: `mnemonic [operand]` |
| **mnemonic** | The 3-character instruction identifier: `LDA`, `BBR`, `NOP`, etc. |
| **operand** | Everything after the mnemonic on an instruction line: encodes both the addressing mode and the address expression.  Example: `($D020,X)` in `LDA ($D020,X)` |
| **addressing mode** | The syntactic form of the operand: implied, immediate (`#`), ZP, ABS, indexed (`,X` / `,Y`), indirect (`(…)`), relative, etc. |
| **address expression** | The numeric part within the operand: a literal, a symbol, a label, or an arithmetic combination thereof.  Example: `$D020` or `BASE+4` |
| **literal** | A numeric constant written directly in source: `$D020`, `255`, `%11001000` |
| **SYMBOL** | A named constant defined by `SYMBOL = expr`.  Has a **value**. |
| **LABEL** | An address marker defined by `LABEL:`.  Has a **slot**. |
| **value** | The evaluated result of a symbol's expression.  Known at parse time if no forward references. |
| **slot** | The assembled address of a label — the value of the location counter at the point of definition. |
| **directive** | An assembler pseudo-instruction that controls output or assembly state but does not emit a CPU opcode: `.org`, `.res`, `db`, `.cpu`, etc. |
| **mnemonic suffix** | The digit `0`–`7` written immediately after the base mnemonic for bit-manipulation instructions: the `0` in `BBR0`, the `3` in `RMB3`.  Syntactically part of the mnemonic token; semantically a bit index. |
| **bit index** | The 0–7 value encoded by a mnemonic suffix.  Folded into the opcode at assembly time as `base_opcode \| (bit_index << 4)`. |

### Assembler internals

| Term | Definition |
|---|---|
| **location counter (LC)** | The assembler's current output address.  Set explicitly by `.org`; advanced by every emitted byte. |
| **forward reference** | A use of a symbol or label that appears in source before its definition. |
| **deferred symbol** | A symbol whose value cannot be resolved in pass 1 because it contains a forward reference. |
| **pass 1** | First scan of the source: builds the symbol/label table, advances LC, records all slots and values (or marks them deferred). |
| **pass 2** | Second scan: all symbols resolved; emits final opcodes and operand bytes. |
| **ZP** | Zero-page: an address in the range `$00–$FF`.  Selects the shorter 2-byte instruction encoding. |
| **ABS** | Absolute: an address in the range `$0000–$FFFF` (typically `$0100–$FFFF` in practice).  Selects the 3-byte instruction encoding. |
| **base opcode** | The opcode byte with the addressing-mode field (`bbb`) zeroed.  The assembler computes the final opcode as `base_opcode \| (bbb << 2)` for Zone G/H instructions. |
| **operand type** | The syntactic classification of an operand: implied, accumulator, immediate, ZP, ABS, indexed, indirect, relative, etc.  Known in hardware documentation as the *addressing mode*. |
| **operand profile** | An integer index (0–29) into `OPERAND_PROFILES` that describes the set of valid operand types for a group of mnemonics.  Replaces the old "S-set" label. |
| **instruction set** | The full set of mnemonics, operand types, and opcodes available under the active `.cpu` model. |

---

## Operand Types — Parser Test Cases

See `dev/instruction_set.py` → `PARSER_TESTS` for the canonical test set.

Each case is `(source, op_type, bytes)` with all expressions resolved to literals.
REL/ZPREL targets are chosen so the offset byte = `$00` (target = instruction end, PC = `$0000`).

---

## Two-Pass Assembly

### Pass 1 — Symbol table construction

- Scan every line in order, maintaining a **location counter (LC)**.
- For each `LABEL:` encountered, record `LC` as the label's slot.
- For each `SYMBOL = expr`:
  - If `expr` is fully resolvable (no forward references), record its value immediately.
  - If `expr` contains an unresolved forward reference, mark the symbol **deferred**.
- For each instruction or `.res`/`.byte`/`.word` directive, advance `LC` by the
  appropriate byte count (see *Address-mode size* below).
- **Forward-referenced operand default**: if an instruction's operand symbol is not
  yet in the table, assume **ABS** (3-byte instruction) for LC advancement.

### Pass 2 — Code emission

- Repeat the same scan with all symbols and labels now resolved.
- Emit the correct opcode and operand bytes for every instruction.
- Deferred symbols are resolved in dependency order before emission begins;
  a circular dependency is a fatal error.

Because no instruction can *grow* between passes (pass 1 pessimistically assumes
ABS), all label slots computed in pass 1 are guaranteed correct in pass 2.
No iteration or relaxation is required.

---

## ZP vs ABS Classification

The assembler selects zero-page (2-byte) or absolute (3-byte) encoding
automatically.  No explicit override syntax is provided or needed.

### Symbols (`SYMBOL = expr`)

A symbol is classified **ZP** if its fully evaluated value satisfies `0 ≤ value ≤ $FF`.

```asm
CHRPNT  = $7A       ; ZP  — value $7A ≤ $FF
VIC_CR1 = $D011     ; ABS — value $D011 > $FF
MASK    = $100 - 1  ; ZP  — value $FF ≤ $FF
```

### Labels (`LABEL:`)

A label is classified **ZP** if its assembled slot satisfies `0 ≤ slot ≤ $FF`.
The programmer places labels in zero page by preceding them with a `.org`
directive that sets LC into the ZP range.

```asm
        .org $02
ptr:    .res 2      ; slot $02 — ZP
tmp:    .res 1      ; slot $04 — ZP

        .org $FB    ; subroutine scratch pool (may overlap other subroutines)
a_ptr:  .res 2      ; slot $FB — ZP
a_tmp:  .res 1      ; slot $FD — ZP

        .org $0810
start:              ; slot $0810 — ABS
```

### Numeric literals

Literals are classified by digit width, independent of value:

| Form | Classification |
|---|---|
| `$nn` (1–2 hex digits) | ZP |
| `$nnnn` (3–4 hex digits) | ABS |
| Decimal `0`–`255` | ZP |
| Decimal `256`–`65535` | ABS |

### Indirect and immediate modes

These modes are **syntactically unambiguous** — ZP/ABS classification is not
applicable:

- `(LABEL,X)`, `(LABEL),Y` — always ZP indirect (NMOS 6502 hardware requirement)
- `#expr` — always immediate (2-byte instruction regardless of expr value)

---

## Pass 1 Forward-Reference Behaviour

| Situation | Pass 1 assumption | Pass 2 action |
|---|---|---|
| Operand is a forward-referenced symbol, bare | ABS (3 bytes) | Emit ZP or ABS per classification |
| Operand is a forward-referenced symbol, indirect `(sym,X)` / `(sym),Y` | ZP (2 bytes) | Emit ZP |
| Operand is a forward-referenced symbol, immediate `#sym` | IMM (2 bytes) | Emit IMM |
| Operand is a numeric literal | Exact (digit-width rule) | Same |

---

## ZP Classification Summary

```
bare operand is ZP  iff:
    (symbol  AND  0 ≤ value ≤ $FF)
  OR
    (label   AND  0 ≤ slot  ≤ $FF)
  OR
    (literal AND  digit-width rule gives ZP)
```

There is no user-facing force-ZP or force-ABS operator.

---

## Directives

| Directive | Syntax | Bytes emitted | Description |
|---|---|---|---|
| `.org` | `.org expr` | 0 | Set location counter to `expr`. Labels defined after this inherit the new address. Use to place code, data, or ZP reservations at a specific address. |
| `.res` | `.res expr` | `expr` | Reserve `expr` bytes, uninitialized. LC advances by `expr`. Typically used with a label to allocate named storage. |
| `db` | `db expr [, expr …]` | 1 per item | Emit one byte per expression. Each `expr` must evaluate to `0–$FF`; out-of-range is a fatal error. Accepts string literals (see `.pet` / `.scr`). |
| `dw` | `dw expr [, expr …]` | 2 per item | Emit one 16-bit little-endian word per expression. Range `0–$FFFF`. |
| `dd` | `dd expr [, expr …]` | 4 per item | Emit one 32-bit little-endian dword per expression. Range `0–$FFFFFFFF`. |
| `dl` | `dl expr [, expr …]` | 1 per item | Emit the **low byte** `<expr` for each expression. Shorthand for building the low-byte half of a split address table. |
| `dh` | `dh expr [, expr …]` | 1 per item | Emit the **high byte** `>expr` for each expression. Shorthand for building the high-byte half of a split address table. |
| `.pet` | `.pet "string" [, …]` | 1 per char | Emit bytes in **PETSCII** encoding. No implicit terminator. |
| `.pet0` | `.pet0 "string"` | len + 1 | Emit PETSCII string followed by a `$00` null terminator. |
| `.scr` | `.scr "string" [, …]` | 1 per char | Emit bytes in **screen code** encoding. No implicit terminator. |
| `.scr0` | `.scr0 "string"` | len + 1 | Emit screen-code string followed by a `$00` null terminator. |
| `.align` | `.align expr` | 0–(`expr`−1) | Advance LC to the next multiple of `expr` (must be a power of two). Padding bytes are uninitialized. |
| `.incbin` | `.incbin "file"` | file size | Include a raw binary file verbatim at the current LC. |
| `.cpu` | `.cpu model` | 0 | Select instruction set. Valid models: `6502` (NMOS legal only), `6510` (NMOS + illegal opcodes; C64 target), `6502x` (NMOS + illegal opcodes; generic alias for `6510`), `65c02` (CMOS legal only). Default: `6502`. |

### Notes

- **Endianness**: `dw` and `dd` always emit in 6502 little-endian byte order.  The programmer does not need to manage byte order manually.
- **Split address tables**: `dl`/`dh` are the idiomatic way to build parallel lo/hi jump tables:
  ```asm
  lo_tab: dl handler0, handler1, handler2
  hi_tab: dh handler0, handler1, handler2
  ```
  Equivalent to `db <handler0, <handler1 …` / `db >handler0 …` but more readable.
- **String terminators**: `.pet` and `.scr` emit no terminator; the programmer appends one explicitly with `db $00` or `db $FF` as the protocol requires.  The `0`-suffix variants are a convenience for the common null-terminated case.
- **`.align` padding**: padding bytes are not guaranteed to be zero; code must not execute through alignment gaps.

---

## C / Assembly Boundary

### Philosophy

Code is written in C for readability; assembly is used where static code
size (the primary optimisation target) makes the trade-off worth it.  The
boundary is expected to shift over the life of the project, with C modules
being progressively replaced by assembly.  The design goal is a **full
assembly implementation** at maturity.

### Invariant: no cc65 ABI bleed into assembly

Assembly modules are **never** called through cc65's C calling convention.
cc65 passes arguments on a software stack and returns values in `A:X`; this
ABI is expensive (stack-frame setup/teardown, 16-bit helpers) and would
tightly couple every call site to cc65.  When a C module is later replaced
by assembly the asm-to-asm interface would have to be redesigned from
scratch.

Instead, all asm modules define their own calling convention:

- **Inputs** — written to named zero-page locations before the `JSR`.
- **Outputs** — returned in registers (`A`, `X`, `Y`, carry) and/or
  zero-page locations.
- **Scratch** — private zero-page bytes named in the module; callers must
  not assume they survive a call.

C code participates in this convention by writing the input ZP locations
and reading registers / ZP output locations directly, using `extern`
declarations for the ZP symbols.  When the C caller is eventually replaced
by an assembly caller, the interface contract is **identical** — no
redesign is required.

### Current boundary (as of project start)

```
C — src/main.c
    Command dispatch (". addr …" line assembler,  "a" full assembler)
    Two-pass loop and location-counter tracking
    Symbol / label table  (allocation, insertion, error reporting)
    Expression evaluator framework  (operator dispatch, forward refs)
    Error formatting and PETSCII display

Assembly — src/
    mn_classify   Mnemonic recognition  (mn6.s / mn7.s + tables)
    au_mode       Operand / addressing-mode parser  (au_mode.s)
    ─── planned ───────────────────────────────────────────────
    asm_line      Complete single-line assembly pipeline
    opcode_lookup (slot, mode) → opcode byte + operand length
    parse_number  Numeric-literal parser  (hex / decimal / binary)
```

`asm_line` is the natural unit of asm work: C sets up the input
descriptor (source pointer, target address) and reads back a result
(bytes written, error code); everything between those two points — mnemonic
recognition, mode parsing, opcode lookup, byte emission — runs in assembly.
Both assembler modes call the same `asm_line` entry point.

### Interface contract for asm modules

| Module | ZP inputs | Register outputs |
|---|---|---|
| `mn6_classify` / `mn7_classify` | `mn_c1`, `mn_c2`, `mn_c3` | `C=0`: A = slot; `C=1`: unrecognised |
| `au_parse_mode` | pointer in ZP (`au_ptr`) | A = mode index; operand bytes in `au_opr` |
| `asm_line` *(planned)* | source ptr, target addr (ZP) | A = bytes emitted; `C=1`: error |
| `opcode_lookup` *(planned)* | slot in X, mode in A | A = opcode, X = operand length |
| `parse_number` *(planned)* | string ptr (ZP) | A:X = 16-bit value; `C=1`: parse error |

---

## mn6 — 6-bit Perfect Hash Mnemonic Classifier

`src/mn6.s` + `src/mn6_tables.s` implement a collision-free 6-bit hash that
identifies all 56 standard NMOS 6502 legal mnemonics in ≈ 20 cycles with a
single-byte false-positive guard.

### Encoding

Characters are VICII screencodes: `A=$01 .. Z=$1A` (1..26).  For a
three-character mnemonic, `c1` is the first letter, `c2` the middle, `c3`
the last.

### Hash formula

```
h = (c1×8 + c3×15 + T[c2]) & $3F
```

- `c1×8`: three `ASL A` instructions (max 208, no carry).
- `c3×15 = c3×16 − c3`: four `ASL A` then `SEC` / `SBC mn_c3`
  (the 2ⁿ−1 pattern; overflows for c3 ≥ 16 but `256 ≡ 0 mod 64`
  means the truncated byte still gives the correct slot after `AND #$3F`).
- `T[c2]`: 27-byte lookup table (index 0 is a guard; 1..26 = A..Z).

Two `CLC` instructions are **required** in the hash sequence:

1. `CLC` before `ADC mn6_h_tmp` — `SEC/SBC` leaves carry undefined.
2. `CLC` before `ADC mn6_hash_t,Y` — `c1×8 + c3×15 mod 256` can exceed 255
   and set carry, which would corrupt the slot for large operands.

### Fingerprint formula

```
fp = (c1 + c2×218) & $FF
```

`A = 1` makes the `c1` term free (plain `LDA mn_c1`).  The `c2` contribution
is read from the 27-byte `mn6_fp_c2` table (`i×218 mod 256` for `i = 0..26`).

### False positives

16 false positives out of 17,576 possible 3-letter strings (0.09%).
Every false positive:

- differs from every legal mnemonic in all three characters (Hamming = 3), and
- is at weighted QWERTY distance ≥ 1.5 from every legal mnemonic.

Two simultaneous independent key errors are required to produce any false
positive from any legal mnemonic.  See
`dev/mn6_fingerprint_collisions.txt` for the complete annotated list.

### Tables (do not edit by hand)

| Symbol | Size | Location | Description |
|---|---|---|---|
| `mn6_hash_t` | 27 B | `mn6.s` RODATA | T[c2] lookup |
| `mn6_fp_c2` | 27 B | `mn6.s` RODATA | `(c2×218)&$FF` lookup |
| `mn6_fp` | 64 B | `mn6_tables.s` | per-slot fingerprint |
| `mn6_base_op` | 64 B | `mn6_tables.s` | per-slot base opcode |
| `mn6_profile` | 64 B | `mn6_tables.s` | per-slot mode-set profile |
| `mn6_h_tmp` | 1 B | ZEROPAGE | scratch: holds `c1×8` |

`mn6_tables.s` is generated by `dev/mnemonic_tables.py`; regenerate after
any change to the mnemonic database or hash parameters.

### Calling convention

```asm
; set up inputs
lda  #screencode_of_first_char
sta  mn_c1
lda  #screencode_of_middle_char
sta  mn_c2
lda  #screencode_of_last_char
sta  mn_c3

jsr  mn6_classify

; on return:
;   C=0 → legal NMOS mnemonic; A = hash slot (0..$3F)
;   C=1 → unrecognised
```

On a recognised mnemonic the caller may index `mn6_base_op,X` and
`mn6_profile,X` (where `X = A` on return) to obtain the base opcode and
operand-profile index.

### Parameter selection

The parameters `C1=8, C3=15, A=1, B=218` were selected from 113 verified
min-wdl=1.5 candidates (out of 1264 collision-free `(C1,C3)` pairs).
Selection criteria: fewest false positives (16), lowest 6502 arithmetic
cost (C1=8 is a pure power of two; A=1 is free).
Full ranked candidate list: `dev/mn6_hash_candidates.txt`.
