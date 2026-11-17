"""m65emu — the m65 integration harness (M65Emu).

Owner: doc/build_system.md

Layer 1, the CPU: MPU45GS02 (mpu45gs02.py), decoding from the
compendium's instruction table (isa.py), checked against xmega65
through the golden file (golden.py).  Layer 2, the memory
layout: M65Memory (memory.py), checked against translations recorded
in xmega65.  Layer 3 (the devices) and the M65Emu harness class follow
in S2-3c–d.
"""

from .memory import M65Memory
from .mpu45gs02 import (FLAT, FlatRAM, MPU45GS02, ReservedOpcode,
                        UncleanOpcode, UndefinedPrefix)

__all__ = ["FLAT", "FlatRAM", "M65Memory", "MPU45GS02", "ReservedOpcode",
           "UncleanOpcode", "UndefinedPrefix"]
