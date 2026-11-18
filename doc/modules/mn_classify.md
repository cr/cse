# mn_classify — Mnemonic Classifier

**Template:** [module](../templates/module.md)

## Owned files

| File | Role |
|------|------|
| [`src/mn_classify.s`](../../src/mn_classify.s) | implementation — dispatcher |
| [`src/mn7.s`](../../src/mn7.s) | implementation — 7-bit hash classifier (C64 `mn7` keys and the m65 keys, over their CPU set's tables) |
| [`src/mn6.s`](../../src/mn6.s) | implementation — 6-bit hash classifier |
| [`src/mn_vars.s`](../../src/mn_vars.s) | implementation — ZP variable definitions |
| [`src/mn7_tables.s`](../../src/mn7_tables.s) | generated — one block per `mn7` CPU set: `mn7_hash_t` (27 B) + `mn7_fp` / `mn7_base_op` / `mn7_profile` (3×128 B), produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py); back-link-exempt (generated) |
| [`src/mn6_tables.s`](../../src/mn6_tables.s) | generated — the `mn6` block (CPU set {6502}): `mn6_hash_t` (27 B) + `mn6_fp_c2` (27 B, `(c2·218) & $FF`) + `mn6_fp` / `mn6_base_op` / `mn6_profile` (3×64 B), produced by [`dev/mnemonic_tables.py`](../../dev/mnemonic_tables.py); back-link-exempt (generated) |
| [`tests/unit/test_mn_classify.py`](../../tests/unit/test_mn_classify.py) | test contract |

## Interface

### mn_classify (dispatcher, mn_classify.s)
Forwards to `mn6_classify` or `mn7_classify` depending on build-time
`USE_MN6` define.  Default: mn7.

### mn6_classify / mn7_classify
**In:** `mn_c1`, `mn_c2`, `mn_c3` (ZP, normalized 1–26: A=1..Z=26)
**Out:** C=0 → recognized, A = hash slot.  C=1 → unrecognized.
**Clobbers:** A, X, Y, mn*_h_tmp

On success, index `mn_base_op[slot]` and `mn_profile[slot]` for
the base opcode and operand profile.

**Re-exports:** `mn_base_op`, `mn_profile` — aliases to the selected
classifier's tables.  **Consumer:** `asm_line.s` reads
`mn_base_op[slot]` and `mn_profile[slot]` immediately after a
successful classify to recover the base opcode byte and the packed
(category, profile-index) byte for the matched mnemonic.

**Packed profile byte:** `bits 7:6 = cat`, `bits 5:0 = pidx` (the
profile index, numbered per CPU set by the generator — see
[opcode_lookup.md § Profile index layout](opcode_lookup.md#design)).
`cat` is the key's CPU category; its meaning is per platform:

| `cat` | C64 CPU sets | m65 CPU set |
|---|---|---|
| 00 | legal NMOS | legal NMOS |
| 01 | legal NMOS with a 65C02 extension profile at `pidx + 1` | legal NMOS with a 4510 extension profile at `pidx + 1` |
| 10 | 6510 illegal | Q name (`LDQ` `STQ` `ORQ` `DEQ` `INQ`): `pidx` is the Q profile |
| 11 | 65C02-only | 4510-only (the 65C02's own names included) |

The gate that reads `cat` is [asm_line.md § asm_cpu × category gate
matrix](asm_line.md#asm_cpu--category-gate-matrix).

**Depends on:** zp (`mn_c1` / `mn_c2` / `mn_c3` — originally
hosted in mn_vars, migrated to zp.s as `.exportzp` ZP vars),
mn6_tables or mn7_tables (GENERATED — `mn{6,7}_classify`,
`mn{6,7}_base_op`, `mn{6,7}_profile`, selected per build-time
`USE_MN6`)

### Memory

| Location | Symbol | Size | Consumers / contract status |
|---|---|---|---|
| mn_vars.s ZP | `mn_c1`, `mn_c2`, `mn_c3` | 1 B each | **Exported inputs.**  `asm_line.s` writes all three before every `jsr mn_classify`.  Values are 1–26 (A=1..Z=26); callers normalize PETSCII/screencode via `AND #$1F`. |
| mn7.s ZP | `mn7_h_tmp` | 1 B | **Internal scratch.**  Holds `c3>>2` transiently during the fingerprint check.  Not exported; no external contract other than "reserved — do not alias". |
| mn7_tables.s RODATA | `mn7_hash_t` | 27 B | **Internal.**  T[c2] hash perturbation, generated per CPU set from `dev/hashes.py`.  Not exported.  Byte values are an implementation detail subsumed by the classifier's observable behaviour (`test_mn7_full_sweep`). |
| mn6_tables.s RODATA | `mn6_hash_t`, `mn6_fp_c2` | 27 B each | Same status as `mn7_hash_t`; `mn6_fp_c2` is the fingerprint's c2 term. |
| mn7_tables.s RODATA | `mn7_fp`, `mn7_base_op`, `mn7_profile` | 128 B each | `mn7_base_op` / `mn7_profile` are **re-exported via mn_classify** (see above).  `mn7_fp` is internal — only `mn7_classify` reads it. |
| mn6_tables.s RODATA | `mn6_fp`, `mn6_base_op`, `mn6_profile` | 64 B each | Same split: `base_op` / `profile` re-exported; `fp` internal. |

## Variants

|  | mn6 | mn7 (C64) | mn7 (m65) |
|--|-----|-----|-----|
| Builds | c64-6502 | c64-6510, c64-65c02 | m65-45gs02 |
| File | mn6.s + mn6_tables.s | mn7.s + mn7_tables.s | mn7.s + mn7_tables.s |
| Keys | 56 (legal NMOS only) | 114 (legal + CMOS + illegal) | 98 (legal + 65C02 + 4510 + the five Q names) |
| Hash bits | 6 | 7 | 7 |
| Slots | 64 | 128 | 128 |
| Hash | `(c1*8 + c3*15 + T[c2]) & $3F` | `(c1*4 + c3 + T[c2]) & $7F` | same as mn7, its own `T` |
| Fingerprint | `(c1 + c2*218) & $FF` | `(c2<<3) \| (c3>>2)` | same as mn7 |
| False positives | 16 / 17576 (0.09%) | 0 / 17576 | 0 / 17576 |
| Table size | 3×64 + 27 + 27 = 246 B | 3×128 + 27 = 411 B | 3×128 + 27 = 411 B |
| Build flag | `-D USE_MN6` | default | default |

The m65 `mn7` is the same routine over the m65 key set's tables (bbbc64
names that table set `mn7gs`): the form admits no false positive for
any key set on a 7-bit table, so only `T` differs, found by the
generator's displacement search over the sorted keys.

Both use the same table layout per slot: fingerprint (1B),
base_op (1B), profile (1B).  Both use a 27-byte T[c2] lookup in
RODATA (index 0 = guard, 1–26 = A–Z).

## Design

1. Compute hash from the three normalized character values (1–26)
2. Index the fingerprint table at the hash slot
3. Compare computed fingerprint against stored fingerprint
4. Match → C=0, return slot in A.  Mismatch → C=1.

The fingerprint check eliminates false positives (mn7 has zero;
mn6 has 16, all requiring two simultaneous typos from any legal
mnemonic).

**Encoding normalization:** The classifier input (mn_c1/c2/c3)
uses values 1–26 (A=1..Z=26), not raw character codes.  The
caller normalizes with AND #$1F, which maps PETSCII uppercase
($41–$5A), PETSCII lowercase ($61–$7A), and VICII screen codes
($01–$1A) identically to 1–26.  The classifiers themselves are
encoding-agnostic.

## Caveats

- Both classifiers clobber Y.  Caller must `ldy #0` after the call
  if Y is needed.
- Input values are 1-based (A=1..Z=26).  Index 0 in T[] is
  a guard value ($FF).
- mn6 does not recognize CMOS, illegal or 4510 mnemonics.
- The classifier sees the three-letter key only.  A fourth character
  (a bit digit, or `q` on `MEGA_SUPPORT`) is the suffix, scanned by
  asm_line ([asm_line.md § Mnemonic word](asm_line.md#mnemonic-word)).
- Tables are GENERATED by `dev/mnemonic_tables.py`.  Do not edit
  mn6_tables.s or mn7_tables.s by hand.
