"""
dev/hashes.py

Perfect-hash specifications for the CSE assembler mnemonic classifiers.

Two assembler variants derived from a common base:

    mn6 — 6-bit hash, 56 legal NMOS 6502 mnemonics.  Slim assembler variant.
          Formula:      h  = (c1*8  + c3*15 + T[c2]) & 0x3F
          Fingerprint:  fp = (c1    + c2*218) & 0xFF
          16 known false positives (0.09%); all at min_wdl ≥ 1.5.

    mn7 — 7-bit hash, all 114 mnemonics (legal + illegal + CMOS).
          Formula:      h  = (c1*4 + c3*1 + T[c2]) & 0x7F
          Fingerprint:  fp = (c2<<3) | (c3>>2)  ← 0 false positives
          Bit-pack: 5 bits of c2 in bits 3–7, c3÷4 in bits 0–2; no carry.

Both classes expose an identical interface defined by _MnHash:
    hash(mne)            → slot index
    build_slot_map()     → {slot: mne}
    fingerprint(c1,c2,c3)→ byte  (raises NotImplementedError if not defined)
    fingerprint_table()  → [SLOTS bytes]
    verify()             → asserts no collisions, prints summary
    verify_fingerprint() → counts false positives, prints summary

VICII screencodes: A=$01 .. Z=$1A (1-based); index 0 = $00 guard.
"""

from instruction_set import sc, MNEMONICS


class _MnHash:
    """
    Base class for CSE mnemonic perfect-hash classifiers.

    Subclasses must define:
        BITS       int          number of hash output bits
        SLOTS      int          number of hash table slots (== 1 << BITS)
        C1         int          coefficient for c1 in hash formula
        C3         int          coefficient for c3 in hash formula
        T          list[int]    27-byte lookup table indexed by c2 screencode
        CATEGORIES frozenset|None  set of category strings to include,
                                   or None to include all mnemonics

    Subclasses that use a fingerprint must also define:
        FP_MAX     int          maximum acceptable false-positive count
    and override:
        fingerprint(c1, c2, c3) → int
    """

    BITS       = NotImplemented
    SLOTS      = NotImplemented
    C1         = NotImplemented
    C3         = NotImplemented
    T          = NotImplemented
    CATEGORIES = NotImplemented

    # ----------------------------------------------------------------
    # Hash

    @classmethod
    def _mask(cls):
        return (1 << cls.BITS) - 1

    @classmethod
    def hash(cls, mne):
        """Compute the hash slot index for a 3-character mnemonic string."""
        c1, c2, c3 = sc(mne[0]), sc(mne[1]), sc(mne[2])
        return (c1 * cls.C1 + c3 * cls.C3 + cls.T[c2]) & cls._mask()

    # ----------------------------------------------------------------
    # Slot map

    @classmethod
    def build_slot_map(cls):
        """Return {slot: mne} for the applicable mnemonic subset.

        Raises ValueError on any hash collision (would indicate a broken
        hash design for this instruction set).
        """
        slot_mne = {}
        for mne, (_, _, cat) in MNEMONICS.items():
            if cls.CATEGORIES is not None and cat not in cls.CATEGORIES:
                continue
            h = cls.hash(mne)
            if h in slot_mne:
                raise ValueError(
                    f"{cls.__name__} collision: {mne!r} and {slot_mne[h]!r} "
                    f"both map to slot {h}")
            slot_mne[h] = mne
        return slot_mne

    # ----------------------------------------------------------------
    # Fingerprint

    @classmethod
    def fingerprint(cls, c1, c2, c3):
        """Compute the fingerprint byte for a mnemonic given its screencodes.

        Subclasses that use a fingerprint table must override this method.
        """
        raise NotImplementedError(
            f"{cls.__name__} does not define a fingerprint function")

    @classmethod
    def fingerprint_table(cls):
        """Return a SLOTS-length list of fingerprint bytes (0 = empty slot)."""
        slot_mne = cls.build_slot_map()
        fp = [0] * cls.SLOTS
        for h, mne in slot_mne.items():
            fp[h] = cls.fingerprint(sc(mne[0]), sc(mne[1]), sc(mne[2]))
        return fp

    # ----------------------------------------------------------------
    # Verification

    @classmethod
    def verify(cls):
        """Assert no hash collisions over the applicable mnemonic subset.

        Prints a one-line summary and returns the slot map.
        """
        slot_mne = cls.build_slot_map()
        expected = sum(
            1 for _, (_, _, cat) in MNEMONICS.items()
            if cls.CATEGORIES is None or cat in cls.CATEGORIES
        )
        assert len(slot_mne) == expected, (
            f"{cls.__name__}.verify: expected {expected} mnemonics, "
            f"got {len(slot_mne)}")
        empty = cls.SLOTS - len(slot_mne)
        print(f"{cls.__name__}.verify: OK  "
              f"({len(slot_mne)}/{cls.SLOTS} slots filled, {empty} empty)")
        return slot_mne

    @classmethod
    def verify_fingerprint(cls):
        """Count false positives over all 26^3 = 17,576 three-letter strings.

        A false positive is a non-mnemonic string that passes both the hash
        slot lookup and the fingerprint check.  Prints a summary and returns
        the list of false-positive strings.

        Subclasses may override to add an assertion on the count bound.
        """
        slot_mne  = cls.build_slot_map()
        fp_table  = cls.fingerprint_table()
        legal_set = frozenset(slot_mne.values())
        letters   = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        mask      = cls._mask()
        false_positives = []
        for a in letters:
            for b in letters:
                for c in letters:
                    mne = a + b + c
                    c1v, c2v, c3v = sc(a), sc(b), sc(c)
                    h = (c1v * cls.C1 + c3v * cls.C3 + cls.T[c2v]) & mask
                    if (h in slot_mne
                            and fp_table[h] == cls.fingerprint(c1v, c2v, c3v)
                            and mne not in legal_set):
                        false_positives.append(mne)
        total = len(letters) ** 3
        n = len(false_positives)
        print(f"{cls.__name__}.verify_fingerprint: {n} false positive(s) "
              f"over {total} strings ({n / total * 100:.2f}%)")
        return false_positives


# ====================================================================
# mn6 — 6-bit hash, 56 legal NMOS mnemonics
# ====================================================================

class mn6(_MnHash):
    """6-bit perfect hash over the 56 legal NMOS mnemonics (slim variant).

    Hash formula:        h  = (c1*8  + c3*15 + T[c2]) & 0x3F
    Fingerprint formula: fp = (c1    + c2*218) & 0xFF

    6502 arithmetic cost:
        c1*8  — three ASL instructions (pure power of 2; max 208, no carry)
        c3*15 — four ASL then SEC+SBC  (c3*16 − c3; standard 2^k−1 pattern)
        fp c1 — trivially free: A=1, so fp = c1 + lookup(c2).
                Runtime: LDA mn_c1 / CLC / ADC mn6_fp_c2,Y / CMP mn6_fp,X

    Important: two CLC instructions are required in the hash sequence —
    one before `ADC mn6_h_tmp` (after SEC/SBC leaves carry undefined) and
    one before `ADC mn6_hash_t,Y` (after the first ADC may set carry).
    Without both CLCs the hash gives wrong slots for mnemonics whose
    c1*8 + c3*15 overflows 8 bits (RTS, STX, STY, TAX, TAY, TSX, TXS).
    See mn6.s for the correct implementation.

    16 false positives (0.09%); all at min_wdl ≥ 1.5 (every false positive
    is at weighted Hamming distance ≥ 1.5 from the nearest legal mnemonic).
    See dev/mn6_fingerprint_collisions.txt.
    """

    BITS       = 6
    SLOTS      = 64
    C1         = 8
    C3         = 15
    CATEGORIES = frozenset({'legal'})

    # 27-byte table indexed by c2 screencode (0 = $00 guard, 1=A .. 26=Z)
    T = [
        0x00,  # 0   @ guard
        0x1C,  # 1   A
        0x1C,  # 2   B
        0x00,  # 3   C
        0x03,  # 4   D
        0x00,  # 5   E
        0x00,  # 6   F
        0x00,  # 7   G
        0x2C,  # 8   H
        0x04,  # 9   I
        0x00,  # 10  J
        0x00,  # 11  K
        0x01,  # 12  L
        0x01,  # 13  M
        0x00,  # 14  N
        0x08,  # 15  O
        0x03,  # 16  P
        0x00,  # 17  Q
        0x1E,  # 18  R
        0x0E,  # 19  S
        0x02,  # 20  T
        0x00,  # 21  U
        0x21,  # 22  V
        0x00,  # 23  W
        0x2E,  # 24  X
        0x05,  # 25  Y
        0x00,  # 26  Z
    ]

    # Fingerprint: fp = (c1 * FP_C1_COEFF + c2 * FP_C2_COEFF) & 0xFF
    FP_C1_COEFF = 1
    FP_C2_COEFF = 218
    FP_MAX      = 16   # known upper bound on false positives

    @classmethod
    def fingerprint(cls, c1, c2, c3):
        """fp = (c1 + c2*218) & 0xFF."""
        return (c1 * cls.FP_C1_COEFF + c2 * cls.FP_C2_COEFF) & 0xFF

    @classmethod
    def verify_fingerprint(cls):
        """Count false positives and assert the count does not exceed FP_MAX."""
        false_positives = super().verify_fingerprint()
        assert len(false_positives) <= cls.FP_MAX, (
            f"{cls.__name__}.verify_fingerprint: "
            f"{len(false_positives)} false positives exceed bound of {cls.FP_MAX}")
        return false_positives


# ====================================================================
# mn6c — rank 12 candidate: C1=11, C3=1, A=1, B=97
# ====================================================================

class mn6c(_MnHash):
    """Candidate 6-bit hash (rank 12): C1=11, C3=1, fp=(c1+c2×97)&$FF.

    Hash formula:        h = (c1*11 + c3*1 + T[c2]) & 0x3F
    Fingerprint formula: fp = (c1 + c2*97) & 0xFF

    6502 arithmetic cost:
        c3*1  — completely free (C3=1; just add c3 directly)
        fp c1 — completely free (A=1; just load c1, no multiply)
        c1*11 — 11 = 8+2+1: LDA c1; STA tmp; ASL; STA tmp2; ASL; ASL; CLC;
                ADC tmp2; ADC tmp  (three-term; costs ~6 instructions after load)

    C3=1 and A=1 eliminate two of the three multiply steps entirely.
    18 false positives; all at min_wdl=1.5.
    """

    BITS       = 6
    SLOTS      = 64
    C1         = 11
    C3         = 1
    CATEGORIES = frozenset({'legal'})

    T = [
        0x00,  # 0   @ guard
        0x14,  # 1   A
        0x0D,  # 2   B
        0x03,  # 3   C
        0x02,  # 4   D
        0x00,  # 5   E
        0x00,  # 6   F
        0x00,  # 7   G
        0x0C,  # 8   H
        0x06,  # 9   I
        0x00,  # 10  J
        0x00,  # 11  K
        0x00,  # 12  L
        0x01,  # 13  M
        0x00,  # 14  N
        0x10,  # 15  O
        0x09,  # 16  P
        0x00,  # 17  Q
        0x12,  # 18  R
        0x01,  # 19  S
        0x04,  # 20  T
        0x00,  # 21  U
        0x10,  # 22  V
        0x00,  # 23  W
        0x17,  # 24  X
        0x06,  # 25  Y
        0x00,  # 26  Z
    ]

    FP_C1_COEFF = 1
    FP_C2_COEFF = 97
    FP_MAX      = 18

    @classmethod
    def fingerprint(cls, c1, c2, c3):
        """fp = (c1 + c2*97) & 0xFF."""
        return (c1 * cls.FP_C1_COEFF + c2 * cls.FP_C2_COEFF) & 0xFF

    @classmethod
    def verify_fingerprint(cls):
        false_positives = super().verify_fingerprint()
        assert len(false_positives) <= cls.FP_MAX, (
            f"{cls.__name__}.verify_fingerprint: "
            f"{len(false_positives)} false positives exceed bound of {cls.FP_MAX}")
        return false_positives


# ====================================================================
# mn6d — rank 56 candidate: C1=3, C3=1, A=4, B=11
# ====================================================================

class mn6d(_MnHash):
    """Candidate 6-bit hash (rank 56): C1=3, C3=1, fp=(c1×4+c2×11)&$FF.

    Hash formula:        h = (c1*3 + c3*1 + T[c2]) & 0x3F
    Fingerprint formula: fp = (c1*4 + c2*11) & 0xFF

    6502 arithmetic cost:
        c3*1  — completely free (C3=1; just add c3 directly)
        c1*3 and fp c1*4 share computation:
            LDA c1 / STA tmp       ; save c1
            ASL / ASL              ; A = c1*4  ← store for fingerprint
            STA fp_tmp
            SEC / SBC tmp          ; A = c1*4 - c1 = c1*3  ← use for hash
        The fingerprint c1 term (c1*4) costs zero extra instructions —
        it is a by-product of computing c1*3 for the hash.

    26 false positives; all at min_wdl=1.5.
    Most compact combined hash+fingerprint computation of the three candidates.
    """

    BITS       = 6
    SLOTS      = 64
    C1         = 3
    C3         = 1
    CATEGORIES = frozenset({'legal'})

    T = [
        0x00,  # 0   @ guard
        0x00,  # 1   A
        0x0E,  # 2   B
        0x0A,  # 3   C
        0x02,  # 4   D
        0x00,  # 5   E
        0x00,  # 6   F
        0x00,  # 7   G
        0x04,  # 8   H
        0x03,  # 9   I
        0x00,  # 10  J
        0x00,  # 11  K
        0x00,  # 12  L
        0x17,  # 13  M
        0x00,  # 14  N
        0x01,  # 15  O
        0x08,  # 16  P
        0x00,  # 17  Q
        0x0B,  # 18  R
        0x02,  # 19  S
        0x07,  # 20  T
        0x00,  # 21  U
        0x12,  # 22  V
        0x00,  # 23  W
        0x11,  # 24  X
        0x24,  # 25  Y
        0x00,  # 26  Z
    ]

    FP_C1_COEFF = 4
    FP_C2_COEFF = 11
    FP_MAX      = 26

    @classmethod
    def fingerprint(cls, c1, c2, c3):
        """fp = (c1*4 + c2*11) & 0xFF."""
        return (c1 * cls.FP_C1_COEFF + c2 * cls.FP_C2_COEFF) & 0xFF

    @classmethod
    def verify_fingerprint(cls):
        false_positives = super().verify_fingerprint()
        assert len(false_positives) <= cls.FP_MAX, (
            f"{cls.__name__}.verify_fingerprint: "
            f"{len(false_positives)} false positives exceed bound of {cls.FP_MAX}")
        return false_positives


# ====================================================================
# mn7 — 7-bit hash, all 114 mnemonics
# ====================================================================

class mn7(_MnHash):
    """7-bit hash over all 114 mnemonics — legal + illegal + CMOS (full variant).

    Hash formula:        h  = (c1*4 + c3*1 + T[c2]) & 0x7F
    Fingerprint formula: fp = (c2 << 3) | (c3 >> 2)

    The fingerprint is a pure bit-pack — no multiply, no carry:
        bits 3–7  ←  low 5 bits of c2  (c2 ≤ 26, fits in 5 bits)
        bits 0–2  ←  c3 >> 2           (c3 ≤ 26 → c3>>2 ≤ 6, 3 bits)
    Since c2<<3 always has bits 0–2 clear, and c3>>2 ≤ 6 < 8, the OR is
    a clean pack with no overlap.  Zero false positives over all 17,462
    non-mnemonic 3-letter strings.

    6502 fingerprint sequence (Y still holds mn_c2 from hash computation):
        lda  mn_c3
        lsr  a              ; c3 >> 1
        lsr  a              ; c3 >> 2  (≤ 6; bits 0–2 only)
        sta  mn7_h_tmp      ; save
        lda  mn_c2
        asl  a              ; c2 × 2
        asl  a              ; c2 × 4
        asl  a              ; c2 × 8  (= c2 << 3; bits 0–2 = 0)
        ora  mn7_h_tmp      ; | (c3 >> 2)
        cmp  mn7_fp,x
    """

    BITS       = 7
    SLOTS      = 128
    C1         = 4
    C3         = 1
    CATEGORIES = None   # all mnemonics

    # 27-byte table indexed by c2 screencode (0 = $FF guard, 1=A .. 26=Z)
    T = [
        0xFF, 0x7B, 0x5B, 0x50, 0x0F, 0x4F, 0x7B, 0x00,  # @ A B C D E F G
        0x0D, 0x15, 0x7B, 0x7B, 0x7B, 0x69, 0x13, 0x2C,  # H I J K L M N O
        0x45, 0x7B, 0x32, 0x7F, 0x47, 0x7B, 0x7E, 0x7B,  # P Q R S T U V W
        0x30, 0x56, 0x7B,                                  # X Y Z
    ]

    FP_MAX = 0   # proven zero false positives

    @classmethod
    def fingerprint(cls, c1, c2, c3):
        """fp = (c2 << 3) | (c3 >> 2)."""
        return ((c2 << 3) | (c3 >> 2)) & 0xFF

    @classmethod
    def verify_fingerprint(cls):
        """Count false positives and assert the count is exactly zero."""
        false_positives = super().verify_fingerprint()
        assert len(false_positives) == 0, (
            f"{cls.__name__}.verify_fingerprint: "
            f"{len(false_positives)} false positives (expected 0)")
        return false_positives
