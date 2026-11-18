"""m65emu — the m65 integration harness (M65Emu).

Owner: doc/build_system.md

Contract source: [doc/testing.md § M65Emu](../../doc/testing.md#m65emu--the-m65-integration-harness).

Layer 1, the CPU: MPU45GS02 (mpu45gs02.py), decoding from the
compendium's instruction table (isa.py), checked against xmega65
through the golden file (golden.py).  Layer 2, the memory
layout: M65Memory (memory.py), checked against translations recorded
in xmega65.  Layer 3, the devices (devices.py): the DMA controller,
checked against jobs recorded in xmega65, the keyboard queue, the CIA
ports and the VIC interrupt latch.  The harness, M65Emu (harness.py),
runs them behind C64Emu's surface (emu_base.py) — feature parity, not
a full MEGA65 — from a post-boot snapshot recorded in xmega65.
"""

from . import m45_ops
from .harness import M65Emu, SnapshotMissing, load_snapshot
from .memory import M65Memory
from .mpu45gs02 import (FLAT, FlatRAM, MPU45GS02, ReservedOpcode,
                        UncleanOpcode, UndefinedPrefix)

__all__ = ["FLAT", "FlatRAM", "M65Emu", "M65Memory", "MPU45GS02", "m45_ops",
           "ReservedOpcode", "SnapshotMissing", "UncleanOpcode",
           "UndefinedPrefix", "load_snapshot"]
