"""m65emu — the m65 integration harness (M65Emu).

Owner: doc/build_system.md

Layer 1, the CPU: MPU45GS02 (mpu45gs02.py), decoding from the
compendium's instruction table (isa.py), checked against xmega65
through the golden file (golden.py).  Layers 2 and 3 (M65Memory, the
devices) and the M65Emu harness class follow in S2-3b–d.
"""

from .mpu45gs02 import (FLAT, FlatRAM, MPU45GS02, ReservedOpcode,
                        UncleanOpcode, UndefinedPrefix)

__all__ = ["FLAT", "FlatRAM", "MPU45GS02", "ReservedOpcode",
           "UncleanOpcode", "UndefinedPrefix"]
