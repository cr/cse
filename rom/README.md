# ROM files

This directory holds Commodore 64 ROM images used by CSE's
test harness and by the ROMSET-investigation Makefile target.
The two ROM families are tracked differently:

## CBM ROMs — **gitignored, not in the repo**

| File | Size | Source |
|------|------|--------|
| `kernal_cbm.bin` | 8 KB | Commodore C64 KERNAL ROM |
| `basic_cbm.bin`  | 8 KB | Commodore C64 BASIC ROM |
| `chargen_cbm.bin` | 4 KB | Commodore C64 character ROM |

These are © Commodore Business Machines and **cannot** be
redistributed.  The pytest harness and the C64Emu fixture both
require `kernal_cbm.bin`; CSE's test setup expects you to
copy it from a legitimate VICE installation:

    cp /path/to/vice/C64/kernal-901227-03 rom/kernal_cbm.bin

VICE itself ships with these ROMs under its bundled-tools
distribution.  The CSE test suite reads `kernal_cbm.bin` once
at fixture init and never modifies it.

## MEGA65 Open ROMs — **committed under LGPL-3.0**

| File | Size | Source |
|------|------|--------|
| `kernal_mega.bin` | 8 KB | MEGA65 Open KERNAL |
| `basic_mega.bin`  | 8 KB | MEGA65 Open BASIC |
| `chargen_mega.bin` | 4 KB | MEGA65 Open CHARGEN |

These ROMs are part of the **MEGA65 Open ROMs project** —
clean-room C64-compatible ROM replacements written from scratch
by the MEGA65 team to avoid the CBM copyright.  Upstream:
[github.com/MEGA65/open-roms](https://github.com/MEGA65/open-roms).
Licensed under **GNU LGPL-3.0** (see the upstream repo for the
canonical LICENSE).

CSE includes them as test artifacts for the ROMSET investigation
documented in the Phase-11 commit (`Phase 11: DDD cleanup,
ROMSET support, Open-KERNAL investigation`).  They are NOT
required by any active build target or test path — only by the
optional `ROMSET=mega` Makefile mode (see `Makefile` line 49).

If you reuse these binaries elsewhere, retain the LGPL-3.0
notice and the MEGA65 attribution.

## Local-only artefacts — **gitignored**

| File pattern | Purpose |
|--------------|---------|
| `*_patched.bin`, `*_upatched.bin` | Local instrumentation — patched/unpatched copies used during ROM-side debugging. |
| `.pytest_cache/` | pytest's per-directory cache. |

These are produced by local workflows and are excluded from
the repo via `.gitignore`.
