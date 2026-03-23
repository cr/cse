"""
dev/instruction_set.py

6502/65C02 instruction-set definition tables for the CSE assembler.

Each entry in MNEMONICS is a tuple:
    'MNE': (profile, cmos_bit, category)

    profile  – integer operand profile index 0..29 (NMOS base profile)
    cmos_bit – True if a 65C02 CPU should use profile+1 instead
    category – 'legal' | 'illegal' | 'cmos'

Use mne_modes(profile, cmos_bit) to recover the full addressing-mode frozenset.

OPERAND PROFILE INDEX ZONES  (assembler control-flow)
======================================================
The 5-bit operand profile index (0–29) is arranged so that range checks alone
drive the assembler's main dispatch loop, with no extra flag bits.

  Zone A  idx = 0          {IMP}
    → emit opcode; done (no operand)

  Zone B  idx = 1          {REL}
    → emit opcode; parse branch target → 1-byte PC-relative offset

  Zone C  idx = 2          {IMM}
    → emit opcode; parse immediate value → 1 byte
    (illegal IMM-only mnemonics: AAC ALR ANC … XAA)

  Zone D  idx = 3          {ZP}   ← bit operand
    → read leading bit-number operand (0–7); opcode = base | (bit<<4)
    → parse ZP address → 1 byte                (RMB, SMB)

  Zone E  idx = 4          {ZPREL}  ← bit operand
    → read leading bit-number operand (0–7); opcode = base | (bit<<4)
    → parse ZP address + branch target → 2 bytes  (BBR, BBS)

  Zone F  idx = 5          {ABS}
    → emit opcode; parse absolute address → 2 bytes  (JSR only)

  ── idx ≤ 5: opcode fixed by mnemonic; skip mode disambiguation ──
  ── idx ≤ 2: no leading bit operand                              ──
  ── idx in {3,4}: leading bit operand (0–7) ORed into opcode    ──
  ── idx ≤ 3 (and idx≥1): 1-byte address operand                 ──
  ── idx in {4,5}: 2-byte address operand                         ──

  Zone G  idx = 6–15       NMOS/CMOS paired profiles
    → if idx is even AND cpu == 65C02: idx += 1  (no extra flag bit needed)
    → parse addressing mode token; validate vs mn_modes[idx]; emit
    Sub-zones by opcode formula:
      idx  6– 9  cc=01  ADC AND CMP EOR LDA ORA SBC / STA
      idx 10–11  cc=10  DEC INC (NMOS) / ASL LSR ROL ROR (always CMOS)
      idx 12–15  cc=00  BIT (NMOS) / LDY (always CMOS) / JMP

  Zone H  idx = 16–29      standalone multi-mode, no CMOS upgrade
    → parse addressing mode token; validate; emit

NMOS/CMOS paired profiles — Zone G even=NMOS, odd=CMOS:
  6/7    cc=01 +IMM    ADC AND CMP EOR LDA ORA SBC  (CMOS adds ZPI)
  8/9    cc=01 -IMM    STA only                     (CMOS adds ZPI)
  10/11  shift ±ACC    DEC INC                      (CMOS adds ACC)
  12/13  BIT / LDY     BIT only                     (CMOS adds IMM,ZPX,ABX)
  14/15  JMP           JMP only                     (CMOS adds AIX)

Operand profiles that point directly into Zone G odd slots (no cmos_bit):
  ASL LSR ROL ROR → 11  (always have ACC; bypass the upgrade path)
  LDY             → 13  (identical to BIT CMOS profile)

Zone H operand profiles that share bit-patterns with Zone G (moved out to keep
the CMOS upgrade invariant clean — every even Zone G idx holds only
mnemonics that genuinely upgrade on 65C02):
  27  cc=01 -IMM illegals  {same bits as 8}   ASO DCM DCP INS ISB ISC LSE RLA RRA SLO SRE
  28  shift-ACC misc       {same bits as 10}  STZ IGN
  29  BIT-NMOS cmos        {same bits as 12}  TRB TSB
"""

# ============================================================
# Addressing mode constants
# ============================================================
IMP   = 'IMP'    # Implied / Inherent
ACC   = 'ACC'    # Accumulator
IMM   = 'IMM'    # Immediate             #nn
ZP    = 'ZP'     # Zero Page             nn
ZPX   = 'ZPX'   # Zero Page, X          nn,X
ZPY   = 'ZPY'   # Zero Page, Y          nn,Y
ABS   = 'ABS'   # Absolute              nnnn
ABX   = 'ABX'   # Absolute, X           nnnn,X
ABY   = 'ABY'   # Absolute, Y           nnnn,Y
IND   = 'IND'   # Indirect              (nnnn)   [JMP only]
INX   = 'INX'   # (Indirect, X)         (nn,X)
INY   = 'INY'   # (Indirect), Y         (nn),Y
REL   = 'REL'   # Relative              [branches]
ZPI   = 'ZPI'   # (Zero Page)           (nn)     [65C02 only]
AIX   = 'AIX'   # (Absolute, X)         (nnnn,X) [65C02 JMP only]
ZPREL = 'ZPREL' # Zero Page + Relative  nn,rr    [65C02 BBR/BBS only]

ALL_MODES = (IMP, ACC, IMM, ZP, ZPX, ZPY, ABS, ABX, ABY,
             IND, INX, INY, REL, ZPI, AIX, ZPREL)

# Operand bytes emitted after the opcode, indexed by mode.
MODE_OPERAND_BYTES = {
    IMP:   0,   # no operand
    ACC:   0,   # 'A' token — syntactic only, no bytes
    IMM:   1,   # immediate value
    ZP:    1,   # zero-page address
    ZPX:   1,   # zero-page address (index in opcode)
    ZPY:   1,   # zero-page address (index in opcode)
    ABS:   2,   # absolute address, little-endian
    ABX:   2,   # absolute address, little-endian
    ABY:   2,   # absolute address, little-endian
    IND:   2,   # absolute address, little-endian  (JMP only)
    INX:   1,   # zero-page address
    INY:   1,   # zero-page address
    REL:   1,   # PC-relative signed offset
    ZPI:   1,   # zero-page address  (65C02)
    AIX:   2,   # absolute address, little-endian  (65C02 JMP only)
    ZPREL: 2,   # zero-page address + PC-relative offset  (65C02)
}

# ============================================================
# Operand profile definitions  (indices 0..29)
#
# Layout mirrors the assembler zone map in the module docstring.
#
# Zone A–F (idx 0–5): single-mode; opcode fixed by mnemonic.
#   idx 0      IMP   – no operand
#   idx 1      REL   – 1-byte relative
#   idx 2      IMM   – 1-byte immediate
#   idx 3      ZP    – leading bit(0-7) operand → opcode; 1-byte ZP addr
#   idx 4      ZPREL – leading bit(0-7) operand → opcode; ZP + rel (2 bytes)
#   idx 5      ABS   – 2-byte absolute  (JSR only)
#
# Zone G (idx 6–15): NMOS/CMOS pairs.
#   Even index = NMOS base; odd index = CMOS extension.
#   Runtime: if (idx & 1 == 0) and cpu == 65C02 → idx += 1
#   Invariant: EVERY mnemonic at an even Zone G index has cmos_bit=True.
#              EVERY mnemonic at an odd  Zone G index has cmos_bit=False.
#
# Zone H (idx 16–29): standalone multi-mode, no CMOS upgrade.
#   Profiles 27/28/29 are bit-identical to 8/10/12 respectively, but live
#   outside Zone G so the upgrade invariant above is not violated.
# ============================================================
OPERAND_PROFILES = [
    # ---- Zone A–F: single-mode (opcode fixed) -----------------
    frozenset({IMP}),                                         # idx=0  no operand
    frozenset({REL}),                                         # idx=1  1-byte relative
    frozenset({IMM}),                                         # idx=2  1-byte immediate
    frozenset({ZP}),                                          # idx=3  bit-op + 1-byte ZP
    frozenset({ZPREL}),                                       # idx=4  bit-op + ZP + rel
    frozenset({ABS}),                                         # idx=5  2-byte absolute (JSR)
    # ---- Zone G: NMOS/CMOS pairs (even=NMOS, odd=CMOS) --------
    frozenset({INX, ZP, IMM, ABS, INY, ZPX, ABY, ABX}),       # idx=6   cc=01 +IMM  NMOS
    frozenset({INX, ZP, IMM, ABS, INY, ZPX, ABY, ABX, ZPI}),  # idx=7   cc=01 +IMM  CMOS (+ZPI)
    frozenset({INX, ZP,      ABS, INY, ZPX, ABY, ABX}),       # idx=8   cc=01 -IMM  NMOS  (STA only)
    frozenset({INX, ZP,      ABS, INY, ZPX, ABY, ABX, ZPI}),  # idx=9   cc=01 -IMM  CMOS (+ZPI)
    frozenset({     ZP,      ABS,      ZPX,      ABX}),       # idx=10  shift -ACC  NMOS  (DEC/INC only)
    frozenset({ACC, ZP,      ABS,      ZPX,      ABX}),       # idx=11  shift +ACC  CMOS (+ACC)
    frozenset({     ZP,      ABS}),                           # idx=12  BIT NMOS          (BIT only)
    frozenset({IMM, ZP,      ABS,      ZPX,      ABX}),       # idx=13  BIT CMOS (+IMM,ZPX,ABX) / LDY
    frozenset({     ABS,                         IND}),       # idx=14  JMP NMOS          (JMP only)
    frozenset({     ABS,                         IND, AIX}),  # idx=15  JMP CMOS (+AIX)
    # ---- Zone H: standalone multi-mode, no CMOS upgrade -------
    frozenset({IMM, ZP,      ABS,           ZPY, ABY}),       # idx=16  LDX
    frozenset({     ZP,      ABS,           ZPY      }),      # idx=17  STX
    frozenset({INX, ZP,      ABS, INY,      ZPY, ABY}),       # idx=18  LAX
    frozenset({INX, ZP,           ZPY, ABS           }),      # idx=19  SAX/AAX
    frozenset({     ZP,      ABS,      ZPX           }),      # idx=20  STY
    frozenset({IMM, ZP,      ABS                     }),      # idx=21  CPX/CPY
    frozenset({     ABS,                     ABX     }),      # idx=22  TOP
    frozenset({     ZP,                  ZPX         }),      # idx=23  DOP
    frozenset({               INY,       ABY         }),      # idx=24  SHA/AXA
    frozenset({                              ABY     }),      # idx=25  SHX/SXA/AHX/SHS/TAS/XAS/LAS/LAR
    frozenset({                          ABX         }),      # idx=26  SHY/SYA/SAY
    # ---- Zone H overflow: bit-identical to 8/10/12 --------
    # Kept outside Zone G so even Zone G indices remain exclusively
    # NMOS-upgradeable (cmos_bit=True) mnemonics.
    frozenset({INX, ZP,      ABS, INY, ZPX, ABY, ABX}),       # idx=27  = profile 8 bits: cc=01 -IMM illegals
    frozenset({     ZP,      ABS,      ZPX,      ABX}),       # idx=28  = profile 10 bits: shift-ACC misc (STZ/IGN)
    frozenset({     ZP,      ABS}),                           # idx=29  = profile 12 bits: BIT-NMOS cmos (TRB/TSB)
]

# Derived constants for validation
_N_OPERAND_PROFILES = len(OPERAND_PROFILES)  # 30
_CMOS_PAIRS  = {6, 8, 10, 12, 14}  # even Zone G indices; each has a CMOS slot at idx+1
_BIT_OPERAND = {3, 4}              # Zone D/E: leading bit(0-7) operand folded into opcode

def mne_modes(profile, cmos_bit):
    """Return the full mode frozenset for a mnemonic.
    If cmos_bit is True, returns OPERAND_PROFILES[profile + 1] (the CMOS extension).
    Otherwise returns OPERAND_PROFILES[profile].
    """
    return OPERAND_PROFILES[profile + (1 if cmos_bit else 0)]

# ============================================================
# MNEMONICS – 114 entries
# (profile, cmos_bit, category)
#   profile  – integer index into OPERAND_PROFILES (0–29)
#   cmos_bit – True if a 65C02 CPU uses profile+1 instead of profile
#   category – 'legal' | 'illegal' | 'cmos'
# ============================================================
MNEMONICS = {

    # ----------------------------------------------------------
    # LEGAL – standard NMOS 6502  (56)
    # ----------------------------------------------------------

    # cc=01 +IMM group, 8 modes NMOS, +ZPI on 65C02  →  profile 6, cmos_bit
    'ADC': (6,  True,  'legal'),
    'AND': (6,  True,  'legal'),
    'CMP': (6,  True,  'legal'),
    'EOR': (6,  True,  'legal'),
    'LDA': (6,  True,  'legal'),
    'ORA': (6,  True,  'legal'),
    'SBC': (6,  True,  'legal'),

    # cc=01 -IMM, +ZPI on 65C02  →  profile 8, cmos_bit
    'STA': (8,  True,  'legal'),

    # shift+ACC (always, including on 65C02)  →  profile 11, no cmos_bit
    'ASL': (11, False, 'legal'),
    'LSR': (11, False, 'legal'),
    'ROL': (11, False, 'legal'),
    'ROR': (11, False, 'legal'),

    # shift-ACC on NMOS, +ACC on 65C02  →  profile 10, cmos_bit
    'DEC': (10, True,  'legal'),
    'INC': (10, True,  'legal'),

    # branches  →  profile 1
    'BCC': (1,  False, 'legal'),
    'BCS': (1,  False, 'legal'),
    'BEQ': (1,  False, 'legal'),
    'BMI': (1,  False, 'legal'),
    'BNE': (1,  False, 'legal'),
    'BPL': (1,  False, 'legal'),
    'BVC': (1,  False, 'legal'),
    'BVS': (1,  False, 'legal'),

    # BIT NMOS={ZP,ABS}, 65C02 adds IMM,ZPX,ABX  →  profile 12, cmos_bit
    'BIT': (12, True,  'legal'),

    # JMP NMOS={ABS,IND}, 65C02 adds AIX  →  profile 14, cmos_bit
    'JMP': (14, True,  'legal'),
    'JSR': (5,  False, 'legal'),

    # load/store
    'LDX': (16, False, 'legal'),
    'LDY': (13, False, 'legal'), # = BIT CMOS profile
    'STX': (17, False, 'legal'),
    'STY': (20, False, 'legal'),

    # compare
    'CPX': (21, False, 'legal'),
    'CPY': (21, False, 'legal'),

    # implied
    'BRK': (0,  False, 'legal'),
    'CLC': (0,  False, 'legal'),
    'CLD': (0,  False, 'legal'),
    'CLI': (0,  False, 'legal'),
    'CLV': (0,  False, 'legal'),
    'DEX': (0,  False, 'legal'),
    'DEY': (0,  False, 'legal'),
    'INX': (0,  False, 'legal'),
    'INY': (0,  False, 'legal'),
    'NOP': (0,  False, 'legal'),
    'PHA': (0,  False, 'legal'),
    'PHP': (0,  False, 'legal'),
    'PLA': (0,  False, 'legal'),
    'PLP': (0,  False, 'legal'),
    'RTI': (0,  False, 'legal'),
    'RTS': (0,  False, 'legal'),
    'SEC': (0,  False, 'legal'),
    'SED': (0,  False, 'legal'),
    'SEI': (0,  False, 'legal'),
    'TAX': (0,  False, 'legal'),
    'TAY': (0,  False, 'legal'),
    'TSX': (0,  False, 'legal'),
    'TXA': (0,  False, 'legal'),
    'TXS': (0,  False, 'legal'),
    'TYA': (0,  False, 'legal'),

    # ----------------------------------------------------------
    # ILLEGAL – undocumented NMOS  (46)
    # cmos_bit always False: no 65C02 upgrade applies
    # ----------------------------------------------------------

    # ---- profile 2 {IMM}: immediate-only compound / alias ops ----
    'AAC': (2,  False, 'illegal'), # AND→carry; alias ANC $2B
    'ANC': (2,  False, 'illegal'), # AND→carry        $0B
    'ALR': (2,  False, 'illegal'), # AND+LSR           $4B
    'ASR': (2,  False, 'illegal'), # alias ALR         $4B
    'ANE': (2,  False, 'illegal'), # A&X&#→A (unstable)$8B
    'XAA': (2,  False, 'illegal'), # alias ANE         $8B
    'ARR': (2,  False, 'illegal'), # AND+ROR           $6B
    'AXS': (2,  False, 'illegal'), # (A&X)-#→X         $CB
    'SBX': (2,  False, 'illegal'), # alias AXS         $CB
    'LXA': (2,  False, 'illegal'), # (A|magic)&#→A,X   $AB
    'USB': (2,  False, 'illegal'), # unofficial SBC    $EB
    'SKB': (2,  False, 'illegal'), # 2-byte NOP (IMM)  $80+

    # ---- profile 27 {INX,ZP,ABS,INY,ZPX,ABY,ABX}: compound RMW illegals ----
    # Zone H (= profile 8 bits); kept out of Zone G so profile 8 holds STA only.
    'ASO': (27, False, 'illegal'), # ASL+ORA; alias SLO
    'SLO': (27, False, 'illegal'), # alias ASO  $07+
    'LSE': (27, False, 'illegal'), # LSR+EOR; alias SRE
    'SRE': (27, False, 'illegal'), # alias LSE  $47+
    'RLA': (27, False, 'illegal'), # ROL+AND    $27+
    'RRA': (27, False, 'illegal'), # ROR+ADC    $67+
    'DCM': (27, False, 'illegal'), # DEC+CMP; alias DCP
    'DCP': (27, False, 'illegal'), # alias DCM  $C7+
    'INS': (27, False, 'illegal'), # INC+SBC; alias ISB
    'ISB': (27, False, 'illegal'), # alias INS  $E7+
    'ISC': (27, False, 'illegal'), # alias INS  $E7+

    # ---- profile 28 {ZP,ABS,ZPX,ABX}: multi-byte NOP ----
    # Zone H (= profile 10 bits); kept out of Zone G so profile 10 holds DEC/INC only.
    'IGN': (28, False, 'illegal'), # 2/3-byte NOP

    # ---- profile 18 {INX,ZP,ABS,INY,ZPY,ABY}: LAX ----
    'LAX': (18, False, 'illegal'), # LDA+LDX $A7+

    # ---- profile 19 {INX,ZP,ZPY,ABS}: SAX ----
    'SAX': (19, False, 'illegal'), # store A&X $87+
    'AAX': (19, False, 'illegal'), # alias SAX $87+

    # ---- profile 22 {ABS,ABX}: 3-byte NOP ----
    'TOP': (22, False, 'illegal'), # 3-byte NOP $0C+

    # ---- profile 23 {ZP,ZPX}: 2-byte NOP ----
    'DOP': (23, False, 'illegal'), # 2-byte NOP $04+

    # ---- profile 24 {INY,ABY}: SHA variants ----
    'SHA': (24, False, 'illegal'), # A&X&(H+1) $93,$9F
    'AXA': (24, False, 'illegal'), # alias SHA

    # ---- profile 25 {ABY}: high-byte AND ops, ABS,Y only ----
    'SHX': (25, False, 'illegal'), # X&(H+1)→mem $9E
    'SXA': (25, False, 'illegal'), # alias SHX
    'AHX': (25, False, 'illegal'), # A&X&(H+1)  $9F (ABY only)
    'SHS': (25, False, 'illegal'), # S=A&X; SHA $9B
    'TAS': (25, False, 'illegal'), # alias SHS
    'XAS': (25, False, 'illegal'), # alias SHS
    'LAS': (25, False, 'illegal'), # mem&S→A,X,S $BB
    'LAR': (25, False, 'illegal'), # alias LAS

    # ---- profile 26 {ABX}: high-byte AND ops, ABS,X only ----
    'SHY': (26, False, 'illegal'), # Y&(H+1)→mem $9C
    'SYA': (26, False, 'illegal'), # alias SHY
    'SAY': (26, False, 'illegal'), # alias SHY

    # ---- profile 0 {IMP}: crash/halt opcodes ----
    'CIM': (0,  False, 'illegal'), # crash $D2
    'HLT': (0,  False, 'illegal'), # crash (generic)
    'JAM': (0,  False, 'illegal'), # crash (generic)
    'KIL': (0,  False, 'illegal'), # crash (generic)

    # ----------------------------------------------------------
    # CMOS – 65C02-only new mnemonics  (12)
    # cmos_bit is always False: these are CMOS-only, no upgrade needed
    # ----------------------------------------------------------

    'BRA': (1,  False, 'cmos'),
    'BBR': (4,  False, 'cmos'),
    'BBS': (4,  False, 'cmos'),
    'PHX': (0,  False, 'cmos'),
    'PHY': (0,  False, 'cmos'),
    'PLX': (0,  False, 'cmos'),
    'PLY': (0,  False, 'cmos'),
    'RMB': (3,  False, 'cmos'), # Zone D: bit-op + ZP
    'SMB': (3,  False, 'cmos'), # Zone D: bit-op + ZP
    'STZ': (28, False, 'cmos'), # Zone H (= profile 10 bits)
    'TRB': (29, False, 'cmos'), # Zone H (= profile 12 bits)
    'TSB': (29, False, 'cmos'), # Zone H (= profile 12 bits)
}

# ============================================================
# Opcode table
# Format: OPCODES['ADC'][ZP] = 0x65
# ============================================================
OPCODES = {
    'ADC': {IMM:0x69, ZP:0x65, ZPX:0x75, ABS:0x6D, ABX:0x7D, ABY:0x79, INX:0x61, INY:0x71, ZPI:0x72},
    'AND': {IMM:0x29, ZP:0x25, ZPX:0x35, ABS:0x2D, ABX:0x3D, ABY:0x39, INX:0x21, INY:0x31, ZPI:0x32},
    'ASL': {ACC:0x0A, ZP:0x06, ZPX:0x16, ABS:0x0E, ABX:0x1E},
    'BCC': {REL:0x90},
    'BCS': {REL:0xB0},
    'BEQ': {REL:0xF0},
    'BIT': {ZP:0x24, ABS:0x2C, IMM:0x89, ZPX:0x34, ABX:0x3C},  # IMM/ZPX/ABX = 65C02
    'BMI': {REL:0x30},
    'BNE': {REL:0xD0},
    'BPL': {REL:0x10},
    'BRK': {IMP:0x00},
    'BVC': {REL:0x50},
    'BVS': {REL:0x70},
    'CLC': {IMP:0x18},
    'CLD': {IMP:0xD8},
    'CLI': {IMP:0x58},
    'CLV': {IMP:0xB8},
    'CMP': {IMM:0xC9, ZP:0xC5, ZPX:0xD5, ABS:0xCD, ABX:0xDD, ABY:0xD9, INX:0xC1, INY:0xD1, ZPI:0xD2},
    'CPX': {IMM:0xE0, ZP:0xE4, ABS:0xEC},
    'CPY': {IMM:0xC0, ZP:0xC4, ABS:0xCC},
    'DEC': {ZP:0xC6, ZPX:0xD6, ABS:0xCE, ABX:0xDE, ACC:0x3A},  # ACC = 65C02
    'DEX': {IMP:0xCA},
    'DEY': {IMP:0x88},
    'EOR': {IMM:0x49, ZP:0x45, ZPX:0x55, ABS:0x4D, ABX:0x5D, ABY:0x59, INX:0x41, INY:0x51, ZPI:0x52},
    'INC': {ZP:0xE6, ZPX:0xF6, ABS:0xEE, ABX:0xFE, ACC:0x1A},  # ACC = 65C02
    'INX': {IMP:0xE8},
    'INY': {IMP:0xC8},
    'JMP': {ABS:0x4C, IND:0x6C, AIX:0x7C},                      # AIX = 65C02
    'JSR': {ABS:0x20},
    'LDA': {IMM:0xA9, ZP:0xA5, ZPX:0xB5, ABS:0xAD, ABX:0xBD, ABY:0xB9, INX:0xA1, INY:0xB1, ZPI:0xB2},
    'LDX': {IMM:0xA2, ZP:0xA6, ZPY:0xB6, ABS:0xAE, ABY:0xBE},
    'LDY': {IMM:0xA0, ZP:0xA4, ZPX:0xB4, ABS:0xAC, ABX:0xBC},
    'LSR': {ACC:0x4A, ZP:0x46, ZPX:0x56, ABS:0x4E, ABX:0x5E},
    'NOP': {IMP:0xEA},
    'ORA': {IMM:0x09, ZP:0x05, ZPX:0x15, ABS:0x0D, ABX:0x1D, ABY:0x19, INX:0x01, INY:0x11, ZPI:0x12},
    'PHA': {IMP:0x48},
    'PHP': {IMP:0x08},
    'PLA': {IMP:0x68},
    'PLP': {IMP:0x28},
    'ROL': {ACC:0x2A, ZP:0x26, ZPX:0x36, ABS:0x2E, ABX:0x3E},
    'ROR': {ACC:0x6A, ZP:0x66, ZPX:0x76, ABS:0x6E, ABX:0x7E},
    'RTI': {IMP:0x40},
    'RTS': {IMP:0x60},
    'SBC': {IMM:0xE9, ZP:0xE5, ZPX:0xF5, ABS:0xED, ABX:0xFD, ABY:0xF9, INX:0xE1, INY:0xF1, ZPI:0xF2},
    'SEC': {IMP:0x38},
    'SED': {IMP:0xF8},
    'SEI': {IMP:0x78},
    'STA': {ZP:0x85, ZPX:0x95, ABS:0x8D, ABX:0x9D, ABY:0x99, INX:0x81, INY:0x91, ZPI:0x92},
    'STX': {ZP:0x86, ZPY:0x96, ABS:0x8E},
    'STY': {ZP:0x84, ZPX:0x94, ABS:0x8C},
    'TAX': {IMP:0xAA},
    'TAY': {IMP:0xA8},
    'TSX': {IMP:0xBA},
    'TXA': {IMP:0x8A},
    'TXS': {IMP:0x9A},
    'TYA': {IMP:0x98},
    # 65C02
    'BRA': {REL:0x80},
    'BBR': {ZPREL:None},   # $0F,$1F,...,$7F (digit encoded in opcode)
    'BBS': {ZPREL:None},   # $8F,$9F,...,$FF
    'PHX': {IMP:0xDA},
    'PHY': {IMP:0x5A},
    'PLX': {IMP:0xFA},
    'PLY': {IMP:0x7A},
    'RMB': {ZP:None},      # $07,$17,...,$77 (digit encoded in opcode)
    'SMB': {ZP:None},      # $87,$97,...,$F7
    'STZ': {ZP:0x64, ZPX:0x74, ABS:0x9C, ABX:0x9E},
    'TRB': {ZP:0x14, ABS:0x1C},
    'TSB': {ZP:0x04, ABS:0x0C},
    # Illegals (representative primary opcodes only)
    'AAC': {IMM:0x2B},
    'AAX': {ZP:0x87, ZPY:0x97, ABS:0x8F, INX:0x83},
    'AHX': {ABY:0x9F},
    'ALR': {IMM:0x4B},
    'ANC': {IMM:0x0B},
    'ANE': {IMM:0x8B},
    'ARR': {IMM:0x6B},
    'ASO': {ZP:0x07, ZPX:0x17, ABS:0x0F, ABX:0x1F, ABY:0x1B, INX:0x03, INY:0x13},
    'ASR': {IMM:0x4B},
    'AXA': {INY:0x93, ABY:0x9F},
    'AXS': {IMM:0xCB},
    'CIM': {IMP:0xD2},
    'DCM': {ZP:0xC7, ZPX:0xD7, ABS:0xCF, ABX:0xDF, ABY:0xDB, INX:0xC3, INY:0xD3},
    'DCP': {ZP:0xC7, ZPX:0xD7, ABS:0xCF, ABX:0xDF, ABY:0xDB, INX:0xC3, INY:0xD3},
    'DOP': {ZP:0x04, ZPX:0x14},
    'HLT': {IMP:0x02},
    'IGN': {ZP:0x04, ZPX:0x14, ABS:0x0C, ABX:0x1C},
    'INS': {ZP:0xE7, ZPX:0xF7, ABS:0xEF, ABX:0xFF, ABY:0xFB, INX:0xE3, INY:0xF3},
    'ISB': {ZP:0xE7, ZPX:0xF7, ABS:0xEF, ABX:0xFF, ABY:0xFB, INX:0xE3, INY:0xF3},
    'ISC': {ZP:0xE7, ZPX:0xF7, ABS:0xEF, ABX:0xFF, ABY:0xFB, INX:0xE3, INY:0xF3},
    'JAM': {IMP:0x02},
    'KIL': {IMP:0x02},
    'LAR': {ABY:0xBB},
    'LAS': {ABY:0xBB},
    'LAX': {ZP:0xA7, ZPY:0xB7, ABS:0xAF, ABY:0xBF, INX:0xA3, INY:0xB3},
    'LSE': {ZP:0x47, ZPX:0x57, ABS:0x4F, ABX:0x5F, ABY:0x5B, INX:0x43, INY:0x53},
    'LXA': {IMM:0xAB},
    'RLA': {ZP:0x27, ZPX:0x37, ABS:0x2F, ABX:0x3F, ABY:0x3B, INX:0x23, INY:0x33},
    'RRA': {ZP:0x67, ZPX:0x77, ABS:0x6F, ABX:0x7F, ABY:0x7B, INX:0x63, INY:0x73},
    'SAX': {ZP:0x87, ZPY:0x97, ABS:0x8F, INX:0x83},
    'SAY': {ABX:0x9C},
    'SBX': {IMM:0xCB},
    'SHA': {INY:0x93, ABY:0x9F},
    'SHX': {ABY:0x9E},
    'SHY': {ABX:0x9C},
    'SHS': {ABY:0x9B},
    'SKB': {IMM:0x80},
    'SLO': {ZP:0x07, ZPX:0x17, ABS:0x0F, ABX:0x1F, ABY:0x1B, INX:0x03, INY:0x13},
    'SRE': {ZP:0x47, ZPX:0x57, ABS:0x4F, ABX:0x5F, ABY:0x5B, INX:0x43, INY:0x53},
    'SXA': {ABY:0x9E},
    'SYA': {ABX:0x9C},
    'TAS': {ABY:0x9B},
    'TOP': {ABS:0x0C, ABX:0x1C},
    'USB': {IMM:0xEB},
    'XAA': {IMM:0x8B},
    'XAS': {ABY:0x9B},
}

# ============================================================
# Base-opcode overrides
# Mnemonics where the general AND-reduce formula cannot be applied.
# _compute_base_opcode() returns these values verbatim; see that
# function in mnemonic_tables.py for full rationale.
# ============================================================
_BASE_OPCODE_OVERRIDES = {
    'RMB': 0x07,  # Zone D: digit-0 ($07,$17,...,$77);  runtime = $07|(bit<<4)
    'SMB': 0x87,  # Zone D: digit-0 ($87,$97,...,$F7);  runtime = $87|(bit<<4)
    'BBR': 0x0F,  # Zone E: digit-0 ($0F,$1F,...,$7F);  runtime = $0F|(bit<<4)
    'BBS': 0x8F,  # Zone E: digit-0 ($8F,$9F,...,$FF);  runtime = $8F|(bit<<4)
    'JMP': 0x4C,  # ABS opcode; IND = base|$20, AIX = base|$30
    # TRB and TSB both AND-reduce to $00 (they share aaa=0,cc=0 with all bbb bits
    # cleared), making them indistinguishable at runtime if we store $00 for both.
    # Override to the minimum (ZP) opcode so the assembler can distinguish them:
    #   opcode_lookup pidx=29 special path: ZP → base, ABS → base|$08
    'TRB': 0x14,  # ZP opcode; ABS = $14|$08 = $1C
    'TSB': 0x04,  # ZP opcode; ABS = $04|$08 = $0C
    # AHX (ABY only, opcode $9F, cc=11 zone): AND-reduce gives $83, which
    # shares base with TAS ($9B).  Storing $9F lets the zone=3/ABY runtime
    # exception in opcode_lookup.s produce the correct opcode: $9F|$18=$9F
    # (the pre-set bbb=7 bits absorb the bbb=6 OR harmlessly).
    'AHX': 0x9F,
}

# ============================================================
# Helper
# ============================================================
def sc(ch):
    """VICII screencode for A-Z  (A=1 .. Z=26)."""
    return ord(ch.upper()) - 64       # ord('A')=65 → 1


# ============================================================
# Operand examples per mode
#
# Maps every mode constant to a list of (operand_source, operand_bytes).
#
#   operand_source – the operand text as written in source (no mnemonic)
#   operand_bytes  – the bytes emitted for the operand (after the opcode),
#                    little-endian for multi-byte addresses
#
# The test framework joins this table with OPCODES to build full cases:
#
#   for mne, (profile, cmos_bit, _) in MNEMONICS.items():
#       for mode in mne_modes(profile, cmos_bit):
#           for operand_src, operand_bytes in MODE_EXAMPLES[mode]:
#               source   = f"{mne} {operand_src}".strip()
#               expected = [OPCODES[mne][mode]] + operand_bytes
#
# All address expressions are resolved literals:
#   ZP  address  → $xx    (2 hex digits → ZP)
#   ABS address  → $xxxx  (4 hex digits → ABS)
#   Digit-width rule: $xxxx forces ABS even when value ≤ $FF.
#
# REL / ZPREL: target chosen so the offset byte = $00 (PC = $0000).
#   REL   (2-byte instruction): target = $0002 → offset $00
#   ZPREL (3-byte instruction): target = $0003 → offset $00
#
# IND vs ZPI and AIX vs INX share syntax; the mnemonic resolves the
# ambiguity when the test framework forms the full instruction string.
# ============================================================

MODE_EXAMPLES = {

    IMP:   [                        # no operand
                ('',        []),
    ],

    ACC:   [                        # accumulator token
                ('A',       []),
                ('a',       []),    # lowercase
                (' A',      []),    # leading space
    ],

    IMM:   [                        # #$xx
                ('#$00',    [0x00]),
                ('#$FF',    [0xFF]),
                (' #$00',   [0x00]),  # leading space
                ('#$00 ',   [0x00]),  # trailing space
    ],

    ZP:    [                        # $xx  (2 hex digits)
                ('$00',     [0x00]),
                ('$FF',     [0xFF]),
                (' $00',    [0x00]),  # leading space
    ],

    ZPX:   [                        # $xx,X
                ('$00,X',   [0x00]),
                ('$FF,X',   [0xFF]),
                ('$00,x',   [0x00]),  # lowercase index
                ('$00 ,X',  [0x00]),  # space before comma
                ('$00, X',  [0x00]),  # space after comma
                ('$00 , X', [0x00]),  # spaces around comma
    ],

    ZPY:   [                        # $xx,Y
                ('$00,Y',   [0x00]),
                ('$FF,Y',   [0xFF]),
                ('$00,y',   [0x00]),  # lowercase index
                ('$00 , Y', [0x00]),  # spaces around comma
    ],

    ABS:   [                        # $xxxx  (4 hex digits)
                ('$0000',   [0x00, 0x00]),
                ('$0100',   [0x00, 0x01]),  # just above ZP
                ('$D020',   [0x20, 0xD0]),  # typical C64 address
                ('$00FF',   [0xFF, 0x00]),  # 4-digit forces ABS despite value ≤ $FF
                (' $0000',  [0x00, 0x00]),  # leading space
    ],

    ABX:   [                        # $xxxx,X
                ('$0000,X',   [0x00, 0x00]),
                ('$D000,X',   [0x00, 0xD0]),
                ('$00FF,X',   [0xFF, 0x00]),  # 4-digit forces ABS
                ('$0000,x',   [0x00, 0x00]),  # lowercase index
                ('$0000 , X', [0x00, 0x00]),  # spaces around comma
    ],

    ABY:   [                        # $xxxx,Y
                ('$0000,Y',   [0x00, 0x00]),
                ('$D000,Y',   [0x00, 0xD0]),
                ('$00FF,Y',   [0xFF, 0x00]),  # 4-digit forces ABS
                ('$0000,y',   [0x00, 0x00]),  # lowercase index
                ('$0000 , Y', [0x00, 0x00]),  # spaces around comma
    ],

    INX:   [                        # ($xx,X)
                ('($00,X)',      [0x00]),
                ('($FF,X)',      [0xFF]),
                ('($00,x)',      [0x00]),  # lowercase index
                ('( $00,X)',     [0x00]),  # space after open paren
                ('($00,X )',     [0x00]),  # space before close paren
                ('( $00 , X )',  [0x00]),  # spaces throughout
    ],

    INY:   [                        # ($xx),Y
                ('($00),Y',     [0x00]),
                ('($FF),Y',     [0xFF]),
                ('($00),y',     [0x00]),  # lowercase index
                ('( $00),Y',    [0x00]),  # space after open paren
                ('($00) ,Y',    [0x00]),  # space before comma
                ('( $00 ) , Y', [0x00]),  # spaces throughout
    ],

    IND:   [                        # ($xxxx)  — JMP only
                ('($0000)',    [0x00, 0x00]),
                ('($FFFC)',    [0xFC, 0xFF]),  # reset vector
                ('( $0000 )',  [0x00, 0x00]),  # spaces inside parens
    ],

    ZPI:   [                        # ($xx)  — 65C02, any mne except JMP
                ('($00)',      [0x00]),
                ('($FF)',      [0xFF]),
                ('( $00 )',    [0x00]),  # spaces inside parens
    ],

    AIX:   [                        # ($xxxx,X)  — 65C02 JMP only
                ('($0000,X)',    [0x00, 0x00]),
                ('($0000,x)',    [0x00, 0x00]),  # lowercase index
                ('( $0000,X )',  [0x00, 0x00]),  # spaces inside parens
    ],

    REL:   [                        # $xxxx target; PC=$0000, target=$0002 → offset=$00
                ('$0002',   [0x00]),
                (' $0002',  [0x00]),  # leading space
    ],

    ZPREL: [                        # $xx,$xxxx; PC=$0000, target=$0003 → offset=$00
                ('$00,$0003',  [0x00, 0x00]),
                ('$FF,$0003',  [0xFF, 0x00]),  # max ZP address
                ('$00, $0003', [0x00, 0x00]),  # space after comma
    ],
}

# Validate MODE_EXAMPLES operand byte counts against MODE_OPERAND_BYTES.
def _check_mode_examples():
    errors = []
    for mode, examples in MODE_EXAMPLES.items():
        expected_len = MODE_OPERAND_BYTES[mode]
        for operand_src, operand_bytes in examples:
            if len(operand_bytes) != expected_len:
                errors.append(
                    f"{mode} {operand_src!r}: "
                    f"expected {expected_len} operand byte(s), "
                    f"got {len(operand_bytes)}")
    for e in errors:
        print(f"MODE_EXAMPLES ERROR: {e}")
    assert not errors, "MODE_EXAMPLES byte-count validation failed"

_check_mode_examples()
